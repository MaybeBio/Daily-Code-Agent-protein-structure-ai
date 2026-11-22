"""Metric checks, including one case where pooled and per-protein disagree."""
import numpy as np
import pytest

from pobj.eval.metrics import evaluate, per_protein_spearman, pooled_spearman, rmse


def test_perfect_and_inverted():
    true = np.arange(20, dtype=float)
    assert pooled_spearman(true, true) == pytest.approx(1.0)
    assert pooled_spearman(-true, true) == pytest.approx(-1.0)


def test_rmse():
    assert rmse([1.0, 2.0], [1.0, 2.0]) == 0.0
    assert rmse([0.0, 0.0], [3.0, 3.0]) == 3.0
    assert rmse([0.0, 0.0], [3.0, 4.0]) == np.sqrt(12.5)


def test_per_protein_ignores_small_proteins():
    """A protein with fewer than min_mutations is left out of the median."""
    pred = list(range(12)) + [0.0, 1.0]
    true = list(range(12)) + [1.0, 0.0]          # the 2-mutation protein is inverted
    proteins = ["big"] * 12 + ["small"] * 2

    median, n = per_protein_spearman(pred, true, proteins, min_mutations=10)
    assert n == 1 and median == pytest.approx(1.0)

    median, n = per_protein_spearman(pred, true, proteins, min_mutations=2)
    assert n == 2 and median == pytest.approx(0.0, abs=1e-12)   # median of 1.0 and -1.0


def test_pooled_and_per_protein_can_disagree():
    """Two proteins on different scales: ranking is right within each, wrong pooled."""
    pred = [0.0, 1.0, 2.0, 10.0, 11.0, 12.0] * 2
    true = [10.0, 11.0, 12.0, 0.0, 1.0, 2.0] * 2
    proteins = (["a"] * 3 + ["b"] * 3) * 2

    out = evaluate(pred, true, proteins, min_mutations=3)
    assert out["per_protein_median_spearman"] == pytest.approx(1.0)
    assert out["pooled_spearman"] < 0
