from __future__ import annotations

import pytest
import torch

from torch import nn

from plm_interpretability.units import causal


def _batch() -> tuple[torch.Tensor, torch.Tensor]:
    generator = torch.Generator().manual_seed(1)
    input_ids = torch.randint(4, 24, (2, 20), generator=generator)  # (b, l)
    input_ids[:, 0] = 0  # CLS
    input_ids[:, -1] = 2  # EOS
    return input_ids, torch.ones_like(input_ids)  # (b, l), (b, l)


def _capture(model: nn.Module, block: int, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    """The SwiGLU input and output of one block, as the model ran them."""
    # input_ids, attention_mask: (b, l)
    seen: dict[str, torch.Tensor] = {}

    def hook(module: nn.Module, args: tuple[torch.Tensor, ...], output: torch.Tensor) -> None:
        # args: ((b, l, 2f),); output: (b, l, f)
        seen["projection"], seen["product"] = args[0].detach().clone(), output.detach().clone()

    handle = causal.transformer_blocks(model)[block].ffn[causal.SWIGLU_INDEX].register_forward_hook(hook)
    with torch.inference_mode():
        model(input_ids=input_ids, attention_mask=attention_mask)
    handle.remove()
    return seen["projection"], seen["product"]  # (b, l, 2f), (b, l, f)


def test_pole_ablation_edits_only_where_the_pole_fires(tiny_esmc: nn.Module) -> None:
    input_ids, attention_mask = _batch()
    projection, before = _capture(tiny_esmc, 1, input_ids, attention_mask)
    gate, up = projection.chunk(2, dim=-1)
    unit = int(((gate > 0) & (up > 0)).sum(dim=(0, 1)).argmax())  # a unit whose positive pole fires somewhere
    chosen = torch.zeros(2, 20, dtype=torch.bool)
    chosen[:, 5:15] = True
    target = causal.PoleTarget(block=1, unit=unit, sign="positive", value=-7.0)
    with causal.pole_ablation(tiny_esmc, [target], chosen):
        _, after = _capture(tiny_esmc, 1, input_ids, attention_mask)
    fires = (gate[..., unit] > 0) & (up[..., unit] > 0) & chosen
    assert bool(fires.any())
    assert torch.equal(after[..., unit][fires], torch.full_like(after[..., unit][fires], -7.0))
    untouched = torch.ones_like(before, dtype=torch.bool)
    untouched[..., unit] = ~fires
    torch.testing.assert_close(after[untouched], before[untouched])


def test_ablation_without_chosen_residues_changes_nothing(tiny_esmc: nn.Module) -> None:
    input_ids, attention_mask = _batch()
    with torch.inference_mode():
        reference = tiny_esmc(input_ids=input_ids, attention_mask=attention_mask).logits
    target = causal.PoleTarget(block=0, unit=3, sign="negative", value=5.0)
    with causal.pole_ablation(tiny_esmc, [target], torch.zeros(2, 20, dtype=torch.bool)), torch.inference_mode():
        ablated = tiny_esmc(input_ids=input_ids, attention_mask=attention_mask).logits
    torch.testing.assert_close(ablated, reference)
    # The hooks are gone after the context closes.
    assert not causal.transformer_blocks(tiny_esmc)[0].ffn[causal.SWIGLU_INDEX]._forward_hooks


def test_activation_removal_and_equal_mass_thresholds(tiny_esmc: nn.Module) -> None:
    input_ids, attention_mask = _batch()
    _, product = _capture(tiny_esmc, 2, input_ids, attention_mask)
    flat = product.reshape(-1, product.shape[-1])  # (r, f)
    lower, upper = causal.magnitude_thresholds(flat, weakest=0.75)
    magnitude = flat.abs().double()
    weak = (magnitude * (magnitude <= lower)).sum(dim=0)  # (f,)
    strong = (magnitude * (magnitude >= upper)).sum(dim=0)  # (f,)
    # The strongest residues reach the weak mass with at most one residue's magnitude to spare.
    assert bool((strong >= weak - 1e-9).all())
    assert bool((strong - weak <= magnitude.max(dim=0).values + 1e-9).all())
    assert float((magnitude <= lower).double().mean()) == pytest.approx(0.75, abs=0.03)
    with causal.activation_removal(tiny_esmc, lower={2: torch.full((flat.shape[1],), float("inf"))}):
        _, removed = _capture(tiny_esmc, 2, input_ids, attention_mask)
    assert bool((removed == 0).all())


def test_stream_shift_adds_to_the_stream_it_reads(tiny_esmc: nn.Module) -> None:
    input_ids, attention_mask = _batch()
    chosen = torch.zeros(2, 20, dtype=torch.bool)
    chosen[0, 7] = chosen[1, 4] = True
    before: list[torch.Tensor] = []
    with causal.stream_reading(tiny_esmc, block=1, residues=chosen, kept=before), torch.inference_mode():
        reference = tiny_esmc(input_ids=input_ids, attention_mask=attention_mask).logits
    # (2, 64): not constant, since the blocks' layer norms remove a constant shift; the second residue is left as it was
    offsets = torch.stack((3.0 * torch.linspace(-1, 1, 64), torch.zeros(64)))
    after: list[torch.Tensor] = []
    with (causal.stream_shift(tiny_esmc, block=1, residues=chosen, offsets=offsets),
          causal.stream_reading(tiny_esmc, block=1, residues=chosen, kept=after), torch.inference_mode()):
        steered = tiny_esmc(input_ids=input_ids, attention_mask=attention_mask).logits
    torch.testing.assert_close(after[0], before[0] + offsets)
    assert not torch.allclose(steered[0, 7], reference[0, 7])
    torch.testing.assert_close(steered[1], reference[1])


def test_masked_readout_reads_the_true_tokens(tiny_esmc: nn.Module) -> None:
    input_ids, attention_mask = _batch()
    positions = torch.zeros(2, 20, dtype=torch.bool)
    positions[:, 3] = True
    scores, correct = causal.masked_readout(tiny_esmc, input_ids, attention_mask, positions, mask_token_id=32)
    assert scores.shape == correct.shape == (2,) and bool((scores <= 0).all())
    with torch.inference_mode():
        logits = tiny_esmc(input_ids=input_ids.masked_fill(positions, 32), attention_mask=attention_mask).logits
    assert torch.equal(correct, (logits.argmax(dim=-1) == input_ids)[positions])


def test_nonfiring_means_average_each_unit_where_its_pole_is_silent() -> None:
    gate = torch.tensor([[1.0, -1.0], [2.0, 1.0], [-1.0, 3.0]])  # (r, f)
    up = torch.tensor([[2.0, 1.0], [-1.0, -2.0], [4.0, 1.0]])  # (r, f)
    product = torch.nn.functional.silu(gate.double()) * up.double()  # (r, f)
    means = causal.nonfiring_means(gate, up)  # (2f,)
    # Unit 0's positive pole fires at residue 0 only, its negative pole at residue 1 only.
    assert float(means[0]) == pytest.approx(float(product[1:, 0].mean()))
    assert float(means[2]) == pytest.approx(float(product[[0, 2], 0].mean()))
    # Unit 1's positive pole fires at residue 2, its negative pole at residue 1.
    assert float(means[1]) == pytest.approx(float(product[:2, 1].mean()))
    assert float(means[3]) == pytest.approx(float(product[[0, 2], 1].mean()))


def test_a_pole_needs_a_sign() -> None:
    with pytest.raises(ValueError):
        causal.PoleTarget(block=0, unit=0, sign="up", value=0.0)
