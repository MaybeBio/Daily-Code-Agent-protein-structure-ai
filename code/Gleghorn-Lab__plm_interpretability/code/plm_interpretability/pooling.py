"""Exact pooling of compacted test-half scores across replicates.

The archive keeps, for each probe, condition and replicate, the mean, sample standard deviation and count of its scores
on the test halves. The mean and sample standard deviation over every replicate's halves together follow exactly from
those three numbers, so the compacted tables reproduce the statistics Protify computes from the uncompacted scores.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from collections.abc import Sequence


def pool_halves(scores: pd.DataFrame, keys: Sequence[str]) -> pd.DataFrame:
    """Per group of `keys`, `mean` and `std` (sample, ddof 1) of the halves of every row in the group, from each row's
    `halves_mean`, `halves_std` and `halves` (count)."""
    count = scores["halves"].astype(float)
    mean = scores["halves_mean"].astype(float)
    # A row of one half has no sample std (NaN); it adds no within-row spread, and its mean still counts.
    spread = scores["halves_std"].astype(float).where(count > 1, 0.0)
    pooled = scores.assign(weighted=count * mean, square=(count - 1) * spread**2 + count * mean**2)
    grouped = pooled.groupby(list(keys))
    total = grouped["halves"].sum().astype(float)
    pooled_mean = grouped["weighted"].sum() / total
    variance = (grouped["square"].sum() - total * pooled_mean**2) / (total - 1)
    return pd.DataFrame({"mean": pooled_mean, "std": np.sqrt(variance.clip(lower=0.0))})
