"""Per-pole specificity from an atlas pass: AUROC against every testable term, the best term and its margin over the best
unrelated term, the held-out AUROC of the training-selected term, and the dominant local term.

Global AUROC follows the compendium's rule for negatives (`observed`): a term's positives against the proteins observed in
its unit that neither hold it nor are masked for it, exact for every pole and term at once. Local association reads the
pass's accumulator sums (`accumulate`), whose pairs already take each term's scope and masked residues, through the atlas
study's `local_metrics`; the study's frozen local selection, with Benjamini-Hochberg over the basis's local tests on
upward-rounded p-values, runs only where labels are needed (`selected_labels`).

Symbols: n proteins; p poles; c poles of one chunk; t terms.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from annotation_vocabulary.study.association import RoundedBH, local_metrics, select_local

from .observed import TermLabels, held_out_auroc, observed_auroc
from .specificity import MIN_SUPPORT, TermRelations, global_specificity, single_dominant_term


def global_scores(
    maxima: np.ndarray,
    split: np.ndarray,
    labels: TermLabels,
    relations: TermRelations,
    *,
    chunk: int = 1024,
    device: str = "cpu",
    min_support: int = MIN_SUPPORT,
) -> pd.DataFrame:
    """One row per pole: best training term and AUROC, the best unrelated term and AUROC, the margin, and the test AUROC
    of the best training term. `maxima` and `labels` are in pass order, `split` names each protein's split."""
    # maxima: (n, p); split: (n,)
    train, test = np.flatnonzero(split == "train"), np.flatnonzero(split == "test")  # (n_train,), (n_test,)
    train_labels, test_labels = labels.rows(train), labels.rows(test)
    frames = []
    for start in range(0, maxima.shape[1], chunk):
        columns = np.asarray(maxima[:, start:start + chunk], dtype=np.float64)  # (n, c)
        train_scores = columns[train]  # (n_train, c)
        specificity = global_specificity(observed_auroc(train_scores, train_labels, min_support=min_support, device=device),
                                         relations)
        frames.append(pd.DataFrame({
            "pole": np.arange(start, start + columns.shape[1]),
            "best_term": specificity.best_term, "best_auroc": specificity.best_auroc,
            "unrelated_term": specificity.unrelated_term, "unrelated_auroc": specificity.unrelated_auroc,
            "margin": specificity.margin,
            "held_out_auroc": held_out_auroc(columns[test], test_labels, specificity.best_term, min_support),
            "active_train_proteins": (train_scores > 0).sum(axis=0),
        }))
    return pd.concat(frames, ignore_index=True)


def local_scores(sums: dict[str, np.ndarray], tokens: np.ndarray, relations: TermRelations) -> pd.DataFrame:
    """One row per pole: its best local term by mean paired contrast, whether it dominates, and its occupancy enrichment.

    `sums` are a `contrast` or `selection` accumulator's study sums over the dominance terms, whose tokens are `tokens`
    in column order; `relations` is built over those terms.
    """
    # sums: (p, t) and (t,) arrays; tokens: (t,)
    with np.errstate(invalid="ignore", divide="ignore"):
        contrast = sums["sum_difference"] / sums["n_informative"][None, :]  # (p, t)
        enrichment = sums["sum_inside"] / sums["sum_outside"]  # (p, t)
    best, dominant = single_dominant_term(contrast, sums["n_informative"], relations)  # (p,), (p,)
    rows = np.arange(len(best))  # (p,)
    found = best >= 0  # (p,)
    column = np.maximum(best, 0)  # (p,)
    return pd.DataFrame({
        "pole": rows, "best_local_term": np.where(found, tokens[column], -1),
        "best_contrast": np.where(found, contrast[rows, column], np.nan),
        "best_enrichment": np.where(found, enrichment[rows, column], np.nan),
        "dominant": dominant & found & (np.where(found, enrichment[rows, column], 0) >= 2),
    })


def selected_labels(
    local_sums: dict[str, np.ndarray],
    local_tokens: np.ndarray,
    *,
    chunk: int = 1024,
    alpha: float = 0.01,
    enrichment: float = 2.0,
    min_support: int = 10,
) -> pd.DataFrame:
    """The atlas study's frozen local selection on one basis: the (pole, term) pairs that pass, with BH over every local
    test of the basis on upward-rounded p-values (`RoundedBH`), as in the study's `run_association`."""
    # local_sums: (p, t_local) and (t_local,); local_tokens: (t_local,)
    correction = RoundedBH()
    parts = []
    n_poles = next(value.shape[0] for value in local_sums.values() if value.ndim == 2)
    for start in range(0, n_poles, chunk):
        block = {key: value[start:start + chunk] if value.ndim == 2 else value for key, value in local_sums.items()}
        metrics = local_metrics(block, min_support)
        correction.add(metrics["local_p"])
        parts.append((start, metrics))
    correction.finalize()
    rows = []
    for start, metrics in parts:
        passed = select_local(metrics, correction.transform(metrics["local_p"]), alpha=alpha, enrichment=enrichment,
                              min_support=min_support)  # (c, t_local)
        poles, columns = np.nonzero(passed)  # (pairs,), (pairs,)
        rows.append(pd.DataFrame({"pole": poles + start, "term": local_tokens[columns],
                                  "mean_difference": metrics["mean_difference"][poles, columns]}))
    return pd.concat(rows, ignore_index=True)
