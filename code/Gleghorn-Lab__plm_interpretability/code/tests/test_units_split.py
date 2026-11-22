from __future__ import annotations

import pandas as pd
import pytest

import compendium_fixtures as fixtures

from plm_interpretability.units import split


def test_sample_keeps_release_splits_and_draws_by_cluster() -> None:
    found = fixtures.release()
    sample = split.atlas_sample(found.pool, found.examined, sizes=fixtures.SIZES)
    pool = found.pool.set_index("protein_id")
    drawn = pool.loc[sample["protein_id"]]
    assert (drawn["split"].to_numpy() == sample["split"].to_numpy()).all()  # every protein keeps its release split
    train = drawn[drawn["split"] == "train"]
    assert train["reviewed"].all() and train["cluster"].is_unique  # one reviewed protein per training cluster
    assert len(train) == found.pool.loc[found.pool["split"] == "train", "cluster"].nunique()
    held = drawn[drawn["split"] != "train"]
    assert held["eligible"].all() and held.groupby("cluster").size().max() <= split.HELD_OUT_PER_CLUSTER
    assert not set(held.index) & {"p0060", "p0070"}  # the atlas study's held-out accessions never come back
    counts = sample["split"].value_counts()
    assert counts["validation"] == fixtures.SIZES["validation"] and counts["calibration"] == fixtures.SIZES["calibration"]
    assert sample["protein_id"].is_monotonic_increasing


def test_sample_and_digest_are_seeded_and_order_free() -> None:
    found = fixtures.release()
    first = split.atlas_sample(found.pool, found.examined, sizes=fixtures.SIZES)
    shuffled = found.pool.sample(frac=1.0, random_state=3)
    again = split.atlas_sample(shuffled, found.examined, sizes=fixtures.SIZES)
    pd.testing.assert_frame_equal(first, again)
    assert split.assignment_digest(first) == split.assignment_digest(first.iloc[::-1])
    other = split.atlas_sample(found.pool, found.examined, seed=1, sizes=fixtures.SIZES)
    assert split.assignment_digest(other) != split.assignment_digest(first)


def test_sample_refuses_a_short_split_and_unknown_columns() -> None:
    found = fixtures.release()
    with pytest.raises(ValueError):
        split.atlas_sample(found.pool, found.examined, sizes={"validation": 10_000})
    with pytest.raises(ValueError):
        split.atlas_sample(found.pool.drop(columns="eligible"), found.examined)
