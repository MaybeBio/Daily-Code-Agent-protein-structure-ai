from __future__ import annotations

import pytest
import torch

from torch import nn

from plm_interpretability.units import causal, rotations, sparsify


SEQUENCES = ["MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ", "MSDNELTRAVQEAGYKPTWLAHHGKEIRVAMDQ", "MAHHHHHHVGTGSNDDDDKSPDPKLMNQRSTVW"]


def test_cut_keeps_the_chosen_coordinates() -> None:
    product = torch.tensor([[0.5, -3.0, 2.0, -0.1, 1.0, 0.0]])
    assert sparsify.cut(product, 2, "native").tolist() == [[0.0, -3.0, 2.0, 0.0, 0.0, 0.0]]
    assert torch.equal(sparsify.cut(product, 2, "weakest"), product * torch.tensor([0.0, 0.0, 0.0, 1.0, 0.0, 1.0]))
    assert torch.equal(sparsify.cut(product, 6, "native"), product)
    assert not sparsify.cut(product, 0, "native").any()
    drawn = sparsify.cut(product.expand(50, 6), 3, "random", generator=torch.Generator().manual_seed(0))
    assert bool(((drawn == product) | (drawn == 0)).all()) and len({tuple(row) for row in (drawn != 0).tolist()}) > 1
    with pytest.raises(ValueError):
        sparsify.cut(product, 2, "rotation")


def test_a_rotation_cuts_the_same_vector_in_other_coordinates() -> None:
    generator = torch.Generator().manual_seed(1)
    product = torch.randn(7, 12, generator=generator)
    torch.testing.assert_close(sparsify.cut(product, 4, "rotation", torch.eye(12)), sparsify.cut(product, 4, "native"))
    turn = rotations.haar_rotation(12, 3)
    kept = sparsify.cut(product, 4, "rotation", turn)
    coordinates = kept @ turn
    assert bool(((coordinates.abs() > 1e-5).sum(dim=1) == 4).all())
    largest = (product @ turn).abs().topk(4, dim=1).indices
    assert torch.equal((coordinates.abs() > 1e-5).nonzero()[:, 1].view(7, 4), largest.sort(dim=1).values)
    assert bool((kept.norm(dim=1) <= product.norm(dim=1) + 1e-5).all())


def test_keeping_every_unit_changes_nothing(tiny_esmc: nn.Module) -> None:
    table = sparsify.run_sparsify(tiny_esmc, SEQUENCES, torch.device("cpu"), single_block=1, kept=(0, 4, 100_000),
                                  rotation_seeds=(0,), token_budget=256, log=lambda _: None)
    assert not causal.transformer_blocks(tiny_esmc)[1].ffn[causal.SWIGLU_INDEX]._forward_hooks
    assert len(table) == 1 + 2 * (1 + 2 * 4)
    intact = table.iloc[0]
    assert intact["basis"] == "intact" and intact["kl"] == 0.0
    whole = table[table["kept"] == 100_000]
    assert bool((whole["kl"].abs() < 1e-5).all()) and bool(((whole["loss"] - intact["loss"]).abs() < 1e-4).all())
    removed = table[table["basis"] == "removed"]
    assert set(removed["scope"]) == {"all", "block1"} and bool((removed["kl"] > 0).all())
    cut = table[(table["kept"] == 4) & (table["scope"] == "all")]
    assert set(cut["basis"]) == set(sparsify.BASES) and bool((cut["kl"] > 0).all())


def test_a_pilot_stops_after_its_conditions(tiny_esmc: nn.Module) -> None:
    table = sparsify.run_sparsify(tiny_esmc, SEQUENCES, torch.device("cpu"), single_block=1, kept=(0, 4), rotation_seeds=(0,),
                                  token_budget=256, limit=2, log=lambda _: None)
    assert len(table) == 3
