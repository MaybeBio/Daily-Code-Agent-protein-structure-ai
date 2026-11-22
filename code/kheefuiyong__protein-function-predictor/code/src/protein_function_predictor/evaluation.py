import numpy as np
from sklearn.metrics import (
    average_precision_score,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
)


def probability_metrics(
    targets: np.ndarray,
    probabilities: np.ndarray,
    vocabulary: list[str],
) -> dict:
    """Calculate probability-based multilabel metrics."""

    if targets.shape != probabilities.shape:
        raise ValueError(
            "Target and probability matrices must "
            "have identical shapes."
        )

    if targets.shape[1] != len(vocabulary):
        raise ValueError(
            "Vocabulary length does not match "
            "the target matrix."
        )

    per_label = {}

    for index, label in enumerate(vocabulary):
        per_label[label] = {
            "average_precision": float(
                average_precision_score(
                    targets[:, index],
                    probabilities[:, index],
                )
            )
        }

    return {
        "micro_average_precision": float(
            average_precision_score(
                targets,
                probabilities,
                average="micro",
            )
        ),
        "macro_average_precision": float(
            average_precision_score(
                targets,
                probabilities,
                average="macro",
            )
        ),
        "per_label": per_label,
    }


def select_f1_thresholds(
    targets: np.ndarray,
    probabilities: np.ndarray,
) -> np.ndarray:
    """Choose one validation threshold per label by maximum F1."""

    if targets.shape != probabilities.shape:
        raise ValueError(
            "Target and probability matrices must "
            "have identical shapes."
        )

    thresholds = []

    for index in range(targets.shape[1]):
        precision, recall, candidates = (
            precision_recall_curve(
                targets[:, index],
                probabilities[:, index],
            )
        )

        if len(candidates) == 0:
            thresholds.append(0.5)
            continue

        precision = precision[:-1]
        recall = recall[:-1]

        denominator = precision + recall

        f1 = np.divide(
            2 * precision * recall,
            denominator,
            out=np.zeros_like(denominator),
            where=denominator != 0,
        )

        best_index = int(
            np.argmax(f1)
        )

        thresholds.append(
            float(candidates[best_index])
        )

    return np.asarray(
        thresholds,
        dtype=np.float32,
    )


def apply_thresholds(
    probabilities: np.ndarray,
    thresholds: np.ndarray,
) -> np.ndarray:
    """Convert probabilities into multilabel predictions."""

    if probabilities.shape[1] != len(thresholds):
        raise ValueError(
            "Threshold count does not match "
            "probability columns."
        )

    return (
        probabilities
        >= thresholds[np.newaxis, :]
    ).astype(np.int8)


def threshold_metrics(
    targets: np.ndarray,
    predictions: np.ndarray,
    vocabulary: list[str],
) -> dict:
    """Calculate threshold-dependent multilabel metrics."""

    if targets.shape != predictions.shape:
        raise ValueError(
            "Target and prediction matrices must "
            "have identical shapes."
        )

    per_label = {}

    for index, label in enumerate(vocabulary):
        per_label[label] = {
            "precision": float(
                precision_score(
                    targets[:, index],
                    predictions[:, index],
                    zero_division=0,
                )
            ),
            "recall": float(
                recall_score(
                    targets[:, index],
                    predictions[:, index],
                    zero_division=0,
                )
            ),
            "f1": float(
                f1_score(
                    targets[:, index],
                    predictions[:, index],
                    zero_division=0,
                )
            ),
        }

    return {
        "micro_precision": float(
            precision_score(
                targets,
                predictions,
                average="micro",
                zero_division=0,
            )
        ),
        "micro_recall": float(
            recall_score(
                targets,
                predictions,
                average="micro",
                zero_division=0,
            )
        ),
        "micro_f1": float(
            f1_score(
                targets,
                predictions,
                average="micro",
                zero_division=0,
            )
        ),
        "macro_f1": float(
            f1_score(
                targets,
                predictions,
                average="macro",
                zero_division=0,
            )
        ),
        "per_label": per_label,
    }