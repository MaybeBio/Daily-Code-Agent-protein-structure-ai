"""Stage 2: Spearman rank correlation, numpy only.

ProteinGym's headline metric. Each assay measures fitness in its own units (binding, growth,
stability...), so only the ORDER of the predictions is compared, never their values.
"""

from __future__ import annotations

import numpy as np


def rankdata(x) -> np.ndarray:
    """Ranks starting at 1. Tied values all get the average of the ranks they span.

    rankdata([30, 10, 20]) -> [3, 1, 2];  rankdata([10, 20, 20, 30]) -> [1, 2.5, 2.5, 4]
    """
    x = np.asarray(x, dtype=float)
    _, inverse, counts = np.unique(x, return_inverse=True, return_counts=True)
    ends = np.cumsum(counts)          # rank of the last element in each tie group
    avg = ends - (counts - 1) / 2     # average rank within each group
    return avg[inverse]               # send each group's rank back to its elements


def spearman(pred, target) -> float:
    """Pearson correlation of the ranks. Drop pairs where either value is NaN first."""
    pred = np.asarray(pred)
    target = np.asarray(target)

    mask = ~(np.isnan(pred) | np.isnan(target))

    pred_rank = rankdata(pred[mask])
    target_rank = rankdata(target[mask])

    rp = pred_rank - pred_rank.mean()
    rt = target_rank - target_rank.mean()

    return (rp*rt).sum() / np.sqrt((rp**2).sum() * (rt**2).sum())

def paired_bootstrap(pred_a, pred_b, target, n_boot=1000, ci=0.95, seed=0):
    """Stage 6: is model A really better than model B on this assay?

    Returns (delta, lo, hi) as Python floats:
      delta  = spearman(pred_a, target) - spearman(pred_b, target) on all the data
      lo, hi = the central `ci` interval of that difference over `n_boot` resamples

    Paired: each round draws ONE set of mutant indices (with replacement) and uses it for
    both models, so the luck of which mutants were drawn cancels in the difference.
    Drop rows where any of the three inputs is NaN before resampling.
    Use np.random.default_rng(seed) so results are reproducible.
    """
    mask = ~(np.isnan(pred_a) | np.isnan(pred_b) | np.isnan(target))
    pred_a, pred_b, target = pred_a[mask], pred_b[mask], target[mask]
    size = len(pred_a)
    deltas = np.zeros(n_boot)
    rng = np.random.default_rng(seed)
    for i in range(n_boot):
        rolls =  rng.integers(low=0, high=size, size=size)
        sub_pred_a = pred_a[rolls]
        sub_pred_b = pred_b[rolls]
        sub_target = target[rolls]
        delta = spearman(sub_pred_a, sub_target) - spearman(sub_pred_b, sub_target)
        deltas[i] = delta
    lo, hi = np.percentile(deltas, (1-ci)/2*100), np.percentile(deltas, 100*(ci + (1 - ci)/2))
    delta = spearman(pred_a, target) - spearman(pred_b, target)
    return delta, lo, hi
    
