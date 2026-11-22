"""Stability metrics.

Pooled and per-protein Spearman answer different questions and are never comparable with
each other: pooled asks whether the model ranks all mutations together, per-protein asks
whether it ranks the mutations within one protein, which is what matters if you are using
it to design a variant.
"""
from collections.abc import Sequence

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


def rmse(pred: Sequence[float], true: Sequence[float]) -> float:
    return float(np.sqrt(np.mean((np.asarray(pred) - np.asarray(true)) ** 2)))


def pooled_spearman(pred: Sequence[float], true: Sequence[float]) -> float:
    return float(spearmanr(pred, true).statistic)


def per_protein_spearman(pred: Sequence[float], true: Sequence[float],
                         proteins: Sequence[str],
                         min_mutations: int = 10) -> tuple[float, int]:
    """Median Spearman within each protein. Returns (median, number of proteins used)."""
    df = pd.DataFrame({"pred": pred, "true": true, "protein": proteins})
    scores = []
    for _, group in df.groupby("protein"):
        if len(group) < min_mutations or group.true.nunique() < 2:
            continue
        rho = spearmanr(group.pred, group.true).statistic
        if np.isfinite(rho):
            scores.append(rho)
    return (float(np.median(scores)) if scores else float("nan")), len(scores)


def evaluate(pred: Sequence[float], true: Sequence[float], proteins: Sequence[str],
             min_mutations: int = 10) -> dict[str, float]:
    median, n_proteins = per_protein_spearman(pred, true, proteins, min_mutations)
    return {
        "pooled_spearman": pooled_spearman(pred, true),
        "per_protein_median_spearman": median,
        "n_proteins_scored": n_proteins,
        "rmse": rmse(pred, true),
        "n_mutations": len(true),
    }
