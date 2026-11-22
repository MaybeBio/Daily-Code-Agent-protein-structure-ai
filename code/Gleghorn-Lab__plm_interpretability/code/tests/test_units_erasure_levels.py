from __future__ import annotations

import numpy as np
import pandas as pd
import torch

from torch import nn

from plm_interpretability.units import causal, erasure_levels


def _classes(proteins: int = 600, width: int = 12, seed: int = 0) -> tuple[torch.Tensor, torch.Tensor]:
    generator = torch.Generator().manual_seed(seed)
    labels = torch.randint(0, 3, (proteins,), generator=generator)
    centers = torch.randn(3, width, generator=generator) * 2
    mixing = torch.randn(width, width, generator=generator)
    return (centers[labels] + torch.randn(proteins, width, generator=generator)) @ mixing, labels  # (n, d), (n,)


def test_leace_equalizes_the_class_means() -> None:
    states, labels = _classes()
    projection, mean = erasure_levels.fit_leace(states, labels)
    erased = erasure_levels.erase(states.double(), projection, mean)
    spread = torch.stack([erased[labels == label].mean(dim=0) for label in range(3)]).std(dim=0)
    before = torch.stack([states[labels == label].double().mean(dim=0) for label in range(3)]).std(dim=0)
    assert float(spread.max()) < 1e-8 < float(before.max())
    torch.testing.assert_close(erasure_levels.erase(erased, projection, mean), erased)
    assert int(torch.linalg.matrix_rank(projection)) == 2
    probe = erasure_levels.train_probe(erased, labels, 3, steps=120)
    assert erasure_levels.score(probe, erased, labels, 3)["accuracy"] < 0.5
    clean = erasure_levels.train_probe(states, labels, 3, steps=120)
    assert erasure_levels.score(clean, states, labels, 3)["balanced_accuracy"] > 0.9


def test_erasing_tokens_erases_the_pooled_mean(tiny_esmc: nn.Module) -> None:
    sequences = ["MKTAYIAKQRQISFVKSHFSRQ", "MSDNELTRAVQEAGYKPTWLAHHGKEIRV", "MAHHHHHHVGTGSNDDDDKSP", "MLEERLGLIEVQAPILSRVGDGTQ"]
    device = torch.device("cpu")
    clean = erasure_levels.pooled_streams(tiny_esmc, sequences, [0, 1, 2], device, token_budget=64)
    assert clean[0][0].shape == (4, 64) and bool((clean[2][1] >= 0).all())
    again = erasure_levels.pooled_streams(tiny_esmc, sequences, [0, 1, 2], device, token_budget=1_000)
    torch.testing.assert_close(again[1][0], clean[1][0], rtol=1e-4, atol=1e-5)
    generator = torch.Generator().manual_seed(1)
    direction = torch.nn.functional.normalize(torch.randn(64, generator=generator), dim=0)
    projection, mean = torch.outer(direction, direction).double(), torch.randn(64, generator=generator).double()
    with erasure_levels.stream_eraser(tiny_esmc, 0, projection, mean):
        erased = erasure_levels.pooled_streams(tiny_esmc, sequences, [0, 1], device, token_budget=64)
    assert not causal.transformer_blocks(tiny_esmc)[1]._forward_pre_hooks
    expected = erasure_levels.erase(clean[0][0].double(), projection, mean).float()
    torch.testing.assert_close(erased[0][0], expected, rtol=1e-4, atol=1e-5)
    assert not torch.allclose(erased[1][0], clean[1][0], atol=1e-4)


def test_run_erasure_levels_reads_every_block_after_the_erased_one(tiny_esmc: nn.Module, monkeypatch) -> None:
    monkeypatch.setattr(erasure_levels, "STEPS", 40)
    generator = np.random.default_rng(0)
    letters = np.array(list("ACDEFGHIKLMNPQRSTVWY"))

    def frame(count: int) -> pd.DataFrame:
        labels = generator.integers(0, 2, size=count)
        # Class 1 is rich in tryptophan, so the tiny model's stream separates the classes.
        sequences = ["".join(generator.choice(letters, size=24)) + ("W" * 8 if label else "A" * 8) for label in labels]
        return pd.DataFrame({"id": np.arange(count), "sequence": sequences, "label": labels})

    table = erasure_levels.run_erasure_levels(tiny_esmc, "toy", {"train": frame(160), "test": frame(60)}, torch.device("cpu"),
                                              erased_blocks=(0,), token_budget=2_048, max_residues=100, log=lambda _: None)
    assert set(table["read_block"]) == {0, 1, 2} and set(table["reader"]) == set(erasure_levels.READERS)
    assert len(table) == 3 * 4 and set(table["erased_block"]) == {0} and int(table["classes"].iloc[0]) == 2
    at_site = table[table["read_block"] == 0].set_index("reader")
    assert at_site.loc["linear", "intact_accuracy"] > 0.9
    assert at_site.loc["linear_original", "accuracy"] < 0.75
