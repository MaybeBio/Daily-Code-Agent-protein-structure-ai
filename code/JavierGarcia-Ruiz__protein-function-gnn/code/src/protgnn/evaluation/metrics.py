"""Multi-label evaluation metrics for Enzyme Commission function prediction."""

from __future__ import annotations

from typing import Any
import numpy as np
from sklearn.metrics import (
    f1_score,
    matthews_corrcoef,
    precision_score,
    recall_score,
    label_ranking_average_precision_score,
    average_precision_score,
)

from protgnn.data.constants import EC_CLASSES


def find_optimal_thresholds(y_true: np.ndarray, y_probs: np.ndarray) -> np.ndarray:
    """Find per-class threshold maximizing F1 score."""
    N, C = y_true.shape
    thresholds = np.zeros(C, dtype=np.float32)
    candidates = np.linspace(0.05, 0.95, 19)

    for c in range(C):
        y_t = y_true[:, c]
        y_p = y_probs[:, c]
        if y_t.sum() == 0 or y_t.sum() == N:
            thresholds[c] = 0.5
            continue

        best_f1 = -1.0
        best_th = 0.5
        for th in candidates:
            pred = (y_p >= th).astype(int)
            f1 = f1_score(y_t, pred, zero_division=0)
            if f1 > best_f1:
                best_f1 = f1
                best_th = th
        thresholds[c] = best_th

    return thresholds


def compute_ec_metrics(
    y_true: np.ndarray,
    y_probs: np.ndarray,
    thresholds: float | np.ndarray = 0.5,
    ec_names: list[str] | None = None,
) -> dict[str, Any]:
    """Compute comprehensive multi-label evaluation metrics across EC classes."""
    y_true = np.asarray(y_true, dtype=np.int32)
    y_probs = np.asarray(y_probs, dtype=np.float32)
    N, C = y_true.shape
    ec_names = ec_names or EC_CLASSES[:C]

    if isinstance(thresholds, (int, float)):
        th_arr = np.full(C, thresholds, dtype=np.float32)
    else:
        th_arr = np.asarray(thresholds, dtype=np.float32)

    y_pred = (y_probs >= th_arr).astype(int)

    # Global multi-label metrics
    micro_f1 = float(f1_score(y_true, y_pred, average="micro", zero_division=0))
    macro_f1 = float(f1_score(y_true, y_pred, average="macro", zero_division=0))
    micro_prec = float(precision_score(y_true, y_pred, average="micro", zero_division=0))
    micro_rec = float(recall_score(y_true, y_pred, average="micro", zero_division=0))
    lrap = float(label_ranking_average_precision_score(y_true, y_probs))

    # Per-class metrics
    per_f1 = []
    per_mcc = []
    per_aupr = []
    for c in range(C):
        yt_c = y_true[:, c]
        yp_c = y_probs[:, c]
        ypr_c = y_pred[:, c]

        per_f1.append(float(f1_score(yt_c, ypr_c, zero_division=0)))
        per_mcc.append(float(matthews_corrcoef(yt_c, ypr_c)) if len(np.unique(yt_c)) > 1 else 0.0)
        try:
            aupr = float(average_precision_score(yt_c, yp_c)) if yt_c.sum() > 0 else 0.0
        except Exception:
            aupr = 0.0
        per_aupr.append(aupr)

    macro_mcc = float(np.mean(per_mcc))
    macro_aupr = float(np.mean(per_aupr))

    # Exact Match Ratio (Subset Accuracy) & Hamming Loss
    exact_match = float(np.all(y_true == y_pred, axis=-1).mean())
    hamming_loss = float(np.mean(y_true != y_pred))

    return {
        "macro_f1": macro_f1,
        "micro_f1": micro_f1,
        "macro_mcc": macro_mcc,
        "macro_aupr": macro_aupr,
        "lrap": lrap,
        "micro_precision": micro_prec,
        "micro_recall": micro_rec,
        "exact_match": exact_match,
        "hamming_loss": hamming_loss,
        "per_class_f1": dict(zip(ec_names, per_f1)),
        "per_class_mcc": dict(zip(ec_names, per_mcc)),
        "per_class_aupr": dict(zip(ec_names, per_aupr)),
    }

