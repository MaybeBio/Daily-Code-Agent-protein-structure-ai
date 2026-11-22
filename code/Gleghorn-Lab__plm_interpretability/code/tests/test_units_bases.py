from __future__ import annotations

import pytest
import torch

from collections.abc import Callable
from torch import nn

from plm_interpretability.units import atlas, bases, capture, firing_rates, poles, rotations


SEQUENCES = ["MKTAYIAKQRQISFVKSHFSRQ", "MSTNPKPQRKTKRNTNRRPQD", "MKVLAAGIVGLLW"]


def _states(model: nn.Module, block: int) -> capture.BlockStates:
    input_ids, attention_mask, residues = atlas.encode_batch(model.tokenizer, SEQUENCES, torch.device("cpu"))
    seen: list[capture.BlockStates] = []
    with capture.BlockReader(model, [block], seen.append, write_blocks=[block], stream_blocks=[block]) as reader:
        reader.run(input_ids, attention_mask, residues)
    return seen[0]


def test_unit_bases_follow_their_definitions(tiny_esmc: nn.Module) -> None:
    states = _states(tiny_esmc, 1)
    n_residues = sum(len(sequence) for sequence in SEQUENCES)
    split = poles.swiglu_poles(states.gate, states.up)
    expected = {
        "native": split.main(), "leak": split.leaks(), "sign": poles.sign_poles(states.product()),
        "gate": poles.sign_poles(states.gate), "residual": poles.sign_poles(states.stream),
    }
    for kind, values in expected.items():
        basis = bases.Basis(kind, 1)
        found = bases.basis_activations(basis, states)  # (r, w)
        assert found.shape == (n_residues, bases.basis_width(basis, d=64, f=256))
        assert found.dtype == torch.float32 and bool((found >= 0).all())
        torch.testing.assert_close(found, values.float())


def test_rotation_basis_is_the_rotated_product(tiny_esmc: nn.Module) -> None:
    states = _states(tiny_esmc, 2)
    rotation = rotations.haar_rotation(256, seed=3)  # (f, f)
    found = bases.basis_activations(bases.Basis("rotation", 2, seed=3), states, rotation=rotation)  # (r, 2f)
    torch.testing.assert_close(found, poles.sign_poles(states.product() @ rotation.float()))
    identity = bases.basis_activations(bases.Basis("rotation", 2, seed=0), states, rotation=torch.eye(256))  # (r, 2f)
    torch.testing.assert_close(identity, bases.basis_activations(bases.Basis("sign", 2), states))


def test_sae_basis_matches_the_fastplms_layer(tiny_esmc: nn.Module, tiny_sae: Callable[..., nn.Module]) -> None:
    states = _states(tiny_esmc, 1)
    layer = tiny_sae()
    for reads, source in (("stream", states.stream), ("write", states.write)):
        basis = bases.Basis("sae", 1, sae="tiny", reads=reads)
        found = bases.basis_activations(basis, states, sae=layer, chunk_rows=7)  # (r, c)
        with torch.no_grad():
            expected = layer(source.float()).feature_magnitudes  # (r, c)
        torch.testing.assert_close(found, expected)
        assert int((found > 0).sum(dim=1).max()) <= 8
        assert bases.basis_width(basis, d=64, f=256, codebook=96) == 96


def test_sae_firing_rates_count_the_dense_codes(tiny_esmc: nn.Module, tiny_sae: Callable[..., nn.Module]) -> None:
    states = _states(tiny_esmc, 1)
    layer = tiny_sae()
    for reads in ("stream", "write"):
        basis = bases.Basis("sae", 1, sae="tiny", reads=reads)
        dense = bases.basis_activations(basis, states, sae=layer, chunk_rows=7)  # (r, c)
        found = bases.sae_firing_rates(basis, states, layer, chunk_rows=7)  # (c,)
        assert found.dtype == torch.float64 and found.shape == (96,)
        torch.testing.assert_close(found, firing_rates.firing_rates(dense), rtol=0, atol=0)
    with pytest.raises(ValueError):
        bases.sae_firing_rates(bases.Basis("native", 1), states, layer)


def test_invalid_bases_raise(tiny_esmc: nn.Module) -> None:
    for arguments in ({"kind": "rotation", "block": 1}, {"kind": "native", "block": 1, "seed": 2},
                      {"kind": "sae", "block": 1}, {"kind": "residual", "block": 1, "reads": "write"},
                      {"kind": "neuron", "block": 1}):
        with pytest.raises(ValueError):
            bases.Basis(**arguments)
    states = _states(tiny_esmc, 0)
    with pytest.raises(ValueError):
        bases.basis_activations(bases.Basis("native", 1), states)
    with pytest.raises(ValueError):
        bases.basis_activations(bases.Basis("rotation", 0, seed=1), states)
    assert bases.Basis("sae", 26, sae="esmc_600_layer27_k64_8192").name == "block26/sae:esmc_600_layer27_k64_8192"
