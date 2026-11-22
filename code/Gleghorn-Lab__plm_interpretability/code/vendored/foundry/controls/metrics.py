"""The scores a control reports, and the cluster bootstrap that puts an interval on the headline.

Regression reports Spearman (the headline), Pearson, RMSE and MAE. A binary task reports average precision (the
headline, `pr_auc`), the trapezoidal PR area, ROC AUC and balanced MCC at the threshold validation chose. Multiclass
reports macro F1 (the headline), accuracy and MCC. Multilabel reports micro average precision over the observed entries
(the headline), micro ROC AUC, macro average precision over the columns with both classes in the split, and the micro
balanced MCC. Intervals resample whole finest clusters, REPLICATES times under SEED, and score the headline through row
weights, so a replicate costs one pass over the sorted scores and never a sort.

NumPy at import time; `binary_scores` loads scikit-learn through `foundry.metrics.ranking`. Symbols: n rows, v label columns, k classes, c finest clusters, e observed entries.
"""

from __future__ import annotations

import numpy as np

from collections.abc import Callable
from typing import Any

from foundry.metrics.binary import balanced_mcc


REPLICATES = 1_000
SEED = 42
BALANCED_SEED = 0
HEADLINE = {"regression": "spearman", "binary": "pr_auc", "multiclass": "macro_f1", "multilabel": "micro_pr_auc"}
Weighted = Callable[[np.ndarray], float]


def finite(value: float) -> float | None:
    """A float for the record: None where the number is not finite."""
    return float(value) if np.isfinite(value) else None


def average_ranks(values: np.ndarray) -> np.ndarray:
    """Ranks from 1 with ties averaged, as Spearman needs."""
    # values: (n,)
    order = np.argsort(values, kind="stable")  # (n,)
    ranks = np.empty(len(values), dtype=np.float64)  # (n,)
    ranks[order] = np.arange(1, len(values) + 1)
    sorted_values = values[order]  # (n,)
    boundaries = np.flatnonzero(np.diff(sorted_values)) + 1  # (t-1,) where a new tie group starts
    starts = np.concatenate(([0], boundaries))  # (t,)
    stops = np.concatenate((boundaries, [len(values)]))  # (t,)
    for start, stop in zip(starts.tolist(), stops.tolist(), strict=True):
        if stop - start > 1:
            ranks[order[start:stop]] = (start + stop + 1) / 2
    return ranks  # (n,)


def pearson(left: np.ndarray, right: np.ndarray) -> float:
    # left, right: (n,)
    if len(left) < 2 or left.std() == 0 or right.std() == 0:
        return float("nan")
    return float(np.corrcoef(left, right)[0, 1])


def spearman(left: np.ndarray, right: np.ndarray) -> float:
    # left, right: (n,)
    return pearson(average_ranks(np.asarray(left, dtype=np.float64)), average_ranks(np.asarray(right, dtype=np.float64)))


def weighted_spearman(left: np.ndarray, right: np.ndarray, weights: np.ndarray) -> float:
    """Spearman of the rows repeated `weights` times each: a bootstrap replicate's value."""
    # left, right, weights: (n,)
    counts = weights.astype(np.int64)  # (n,)
    return spearman(np.repeat(left, counts), np.repeat(right, counts))


def regression_scores(value: np.ndarray, prediction: np.ndarray) -> dict[str, float | None]:
    # value, prediction: (n,)
    residual = prediction - value  # (n,)
    return {"spearman": finite(spearman(value, prediction)), "pearson": finite(pearson(value, prediction)),
            "rmse": finite(float(np.sqrt(np.mean(residual ** 2)))), "mae": finite(float(np.mean(np.abs(residual))))}


def average_precision(labels: np.ndarray, scores: np.ndarray, weights: np.ndarray | None = None) -> float:
    """Average precision of binary labels: the positive share at each distinct score, averaged over positives.

    With `weights` (a count per row) the rows are weighted, which is how a bootstrap replicate is scored without
    rebuilding the sample; equal scores form one threshold group.
    """
    # labels, scores, weights: (n,)
    truth = np.asarray(labels, dtype=np.float64) > 0  # (n,)
    weight = np.ones(len(truth), dtype=np.float64) if weights is None else np.asarray(weights, dtype=np.float64)  # (n,)
    order = np.argsort(-np.asarray(scores, dtype=np.float64), kind="stable")  # (n,)
    sorted_scores, sorted_truth, sorted_weight = scores[order], truth[order], weight[order]  # (n,) each
    positive = np.cumsum(sorted_weight * sorted_truth)  # (n,) weighted positives at or above each row
    total = np.cumsum(sorted_weight)  # (n,)
    last_of_group = np.concatenate((sorted_scores[1:] != sorted_scores[:-1], [True]))  # (n,) a group's last row
    group_positive = np.diff(np.concatenate(([0.0], positive[last_of_group])))  # (t,) positives the group adds
    group_total = total[last_of_group]  # (t,)
    precision = np.divide(positive[last_of_group], group_total, out=np.zeros_like(group_total), where=group_total > 0)  # (t,)
    if positive[-1] <= 0:
        return float("nan")
    return float(np.sum(group_positive * precision) / positive[-1])


def binary_scores(labels: np.ndarray, scores: np.ndarray, threshold: float | None) -> dict[str, float | None]:
    """Ranking metrics and balanced MCC at `threshold`, or at the threshold the split itself chooses when None."""
    from foundry.metrics.ranking import binary_ranking_metrics

    # labels, scores: (n,)
    ranking = binary_ranking_metrics(np.asarray(labels, dtype=np.float64), np.asarray(scores, dtype=np.float64))
    report: dict[str, float | None] = {"pr_auc": ranking["average_precision"], "pr_auc_trapezoidal": ranking["pr_auc_trapezoidal"],
                                       "roc_auc": ranking["auroc"]}
    if len(np.unique(labels > 0)) < 2:
        report.update({"balanced_mcc": None, "balanced_mcc_std": None, "threshold": threshold})
        return report
    balanced = balanced_mcc(labels > 0, scores, seed=BALANCED_SEED, threshold=threshold)
    report.update({"balanced_mcc": balanced["balanced_mcc"], "balanced_mcc_std": balanced["balanced_mcc_std"],
                   "threshold": balanced["threshold"]})
    return report


def confusion(labels: np.ndarray, predicted: np.ndarray, classes: int, weights: np.ndarray | None = None) -> np.ndarray:
    """The (k, k) weighted confusion matrix, true class by row."""
    # labels, predicted, weights: (n,)
    weight = np.ones(len(labels), dtype=np.float64) if weights is None else np.asarray(weights, dtype=np.float64)  # (n,)
    flat = labels.astype(np.int64) * classes + predicted.astype(np.int64)  # (n,)
    return np.bincount(flat, weights=weight, minlength=classes * classes).reshape(classes, classes)  # (k, k)


def macro_f1(labels: np.ndarray, predicted: np.ndarray, classes: int, weights: np.ndarray | None = None) -> float:
    """Macro F1 over the classes present in the labels; a class predicted without support scores 0."""
    # labels, predicted, weights: (n,)
    counts = confusion(labels, predicted, classes, weights)  # (k, k)
    true_positive = np.diag(counts)  # (k,)
    support, predicted_count = counts.sum(axis=1), counts.sum(axis=0)  # (k,), (k,)
    denominator = support + predicted_count  # (k,)
    f1 = np.where(denominator > 0, 2 * true_positive / np.maximum(denominator, 1), 0.0)  # (k,)
    present = support > 0  # (k,)
    return float(f1[present].mean()) if present.any() else float("nan")


def multiclass_mcc(counts: np.ndarray) -> float:
    """Matthews correlation of a (k, k) confusion matrix, Gorodkin's form."""
    # counts: (k, k)
    total = counts.sum()
    correct = np.trace(counts)
    support, predicted = counts.sum(axis=1), counts.sum(axis=0)  # (k,), (k,)
    covariance = correct * total - float(support @ predicted)
    denominator = np.sqrt((total ** 2 - float(predicted @ predicted)) * (total ** 2 - float(support @ support)))
    return float(covariance / denominator) if denominator > 0 else float("nan")


def multiclass_scores(labels: np.ndarray, probabilities: np.ndarray, classes: int) -> dict[str, float | None]:
    # labels: (n,); probabilities: (n, k)
    predicted = probabilities.argmax(axis=1)  # (n,)
    counts = confusion(labels, predicted, classes)  # (k, k)
    return {"macro_f1": finite(macro_f1(labels, predicted, classes)),
            "accuracy": finite(float(np.trace(counts) / counts.sum())) if counts.sum() else None,
            "mcc": finite(multiclass_mcc(counts))}


def micro_average_precision(labels: np.ndarray, observed: np.ndarray, scores: np.ndarray,
                            weights: np.ndarray | None = None) -> float:
    """Average precision over every observed (row, column) entry, each weighted by its row's weight."""
    # labels, observed, scores: (n, v); weights: (n,)
    rows, columns = np.nonzero(observed)  # (e,), (e,)
    entry_weights = None if weights is None else np.asarray(weights, dtype=np.float64)[rows]  # (e,)
    return average_precision(labels[rows, columns], scores[rows, columns], entry_weights)


def multilabel_scores(labels: np.ndarray, observed: np.ndarray, scores: np.ndarray, threshold: float | None) -> dict[str, float | None]:
    """Micro metrics over the observed entries, and macro average precision over the columns with both classes observed."""
    # labels, observed, scores: (n, v)
    rows, columns = np.nonzero(observed)  # (e,), (e,)
    flat_labels, flat_scores = labels[rows, columns] > 0, scores[rows, columns]  # (e,), (e,)
    micro = binary_scores(flat_labels.astype(np.float64), flat_scores, threshold)
    per_column: list[float] = []
    for column in range(labels.shape[1]):
        mask = observed[:, column]  # (n,)
        truth = labels[mask, column] > 0  # (n_column,)
        if truth.any() and not truth.all():
            per_column.append(average_precision(truth, scores[mask, column]))
    return {"micro_pr_auc": micro["pr_auc"], "micro_roc_auc": micro["roc_auc"],
            "macro_pr_auc": finite(float(np.mean(per_column))) if per_column else None, "columns_scored": float(len(per_column)),
            "micro_balanced_mcc": micro["balanced_mcc"], "micro_balanced_mcc_std": micro["balanced_mcc_std"],
            "threshold": micro["threshold"]}


def headline_statistic(task_type: str, labels: np.ndarray, observed: np.ndarray, prediction: np.ndarray, classes: int) -> Weighted:
    """The task's headline as a function of row weights, for the cluster bootstrap."""
    # labels, observed: (n,) or (n, v); prediction: (n,), (n, k) or (n, v)
    if task_type == "regression":
        return lambda weights: weighted_spearman(labels[observed], prediction[observed], weights[observed])
    if task_type == "binary":
        return lambda weights: average_precision(labels[observed], prediction[observed], weights[observed])
    if task_type == "multiclass":
        return lambda weights: macro_f1(labels[observed].astype(np.int64), prediction[observed].argmax(axis=1), classes,
                                        weights[observed])
    return lambda weights: micro_average_precision(labels, observed, prediction, weights)


def cluster_bootstrap(statistic: Weighted, cluster: np.ndarray, *, replicates: int = REPLICATES,
                      seed: int = SEED) -> tuple[float | None, float | None]:
    """The 2.5 and 97.5 percentiles of `statistic` over replicates that resample whole clusters with replacement.

    A replicate's row weights are how many times the row's cluster was drawn, so a statistic that takes weights is
    scored without materializing the resampled rows. Non-finite replicate values are dropped; the interval is None
    when fewer than half the replicates are finite.
    """
    # cluster: (n,)
    _, membership = np.unique(cluster, return_inverse=True)  # (c,), (n,) each row's cluster index
    count = int(membership.max()) + 1 if len(membership) else 0  # c
    generator = np.random.default_rng(seed)
    draws: list[float] = []
    for _ in range(replicates):
        picks = generator.integers(0, count, count)  # (c,) the clusters drawn
        cluster_weights = np.bincount(picks, minlength=count).astype(np.float64)  # (c,)
        draws.append(statistic(cluster_weights[membership]))
    finite_draws = np.array([draw for draw in draws if np.isfinite(draw)], dtype=np.float64)  # (d,)
    if len(finite_draws) < replicates / 2:
        return None, None
    low, high = np.percentile(finite_draws, [2.5, 97.5])
    return float(low), float(high)


def task_scores(task_type: str, labels: np.ndarray, observed: np.ndarray, prediction: np.ndarray, classes: int,
                threshold: float | None) -> dict[str, float | None]:
    """The task's report on one split, at a carried `threshold` for the balanced MCC when the task has one."""
    # labels, observed: (n,) or (n, v); prediction: (n,), (n, k) or (n, v)
    if task_type == "regression":
        return regression_scores(labels[observed], prediction[observed])
    if task_type == "binary":
        return binary_scores(labels[observed], prediction[observed], threshold)
    if task_type == "multiclass":
        return multiclass_scores(labels[observed].astype(np.int64), prediction[observed], classes)
    return multilabel_scores(labels, observed, prediction, threshold)


def carried_threshold(task_type: str, validation_scores: dict[str, Any]) -> float | None:
    """The threshold validation chose, carried to test; None for a task without one."""
    if task_type in ("binary", "multilabel"):
        threshold = validation_scores.get("threshold")
        return None if threshold is None else float(threshold)
    return None
