"""The archive's compacted test-half statistics pool to exactly the statistics of the uncompacted scores."""

from __future__ import annotations

import numpy as np
import pandas as pd

from plm_interpretability.pooling import pool_halves


def test_pool_halves_matches_uncompacted_scores() -> None:
    generator = np.random.default_rng(24895)
    rows = [{"probe_name": f"resid_post:{probe}", "replicate": replicate, "score": score}
            for probe in range(4) for replicate in range(3) for score in generator.normal(0.5, 0.1, size=7)]
    scores = pd.DataFrame(rows)
    expected = scores.groupby("probe_name")["score"].agg(["mean", "std"])
    compact = scores.groupby(["probe_name", "replicate"])["score"].agg(halves_mean="mean", halves_std="std", halves="count").reset_index()
    pooled = pool_halves(compact, ["probe_name"])
    np.testing.assert_allclose(pooled["mean"].to_numpy(), expected["mean"].to_numpy(), rtol=0, atol=1e-12)
    np.testing.assert_allclose(pooled["std"].to_numpy(), expected["std"].to_numpy(), rtol=0, atol=1e-12)


def test_a_row_of_one_half_still_counts_toward_the_pooled_spread() -> None:
    """One half has no sample std; its value still belongs to the group's mean and variance."""
    scores = pd.DataFrame({"probe_name": ["q:1"] * 4, "replicate": [0, 0, 0, 1], "score": [0.2, 0.4, 0.6, 0.9]})
    expected = scores.groupby("probe_name")["score"].agg(["mean", "std"])
    compact = scores.groupby(["probe_name", "replicate"])["score"].agg(halves_mean="mean", halves_std="std", halves="count").reset_index()
    assert np.isnan(compact.loc[compact["replicate"] == 1, "halves_std"]).all()

    pooled = pool_halves(compact, ["probe_name"])

    np.testing.assert_allclose(pooled["mean"].to_numpy(), expected["mean"].to_numpy(), rtol=0, atol=1e-12)
    np.testing.assert_allclose(pooled["std"].to_numpy(), expected["std"].to_numpy(), rtol=0, atol=1e-12)


def test_pool_halves_of_one_replicate_is_that_replicate() -> None:
    compact = pd.DataFrame({"probe_name": ["q:3"], "halves_mean": [0.42], "halves_std": [0.031], "halves": [7]})
    pooled = pool_halves(compact, ["probe_name"])
    assert pooled.loc["q:3", "mean"] == 0.42
    np.testing.assert_allclose(pooled.loc["q:3", "std"], 0.031, rtol=1e-12)
