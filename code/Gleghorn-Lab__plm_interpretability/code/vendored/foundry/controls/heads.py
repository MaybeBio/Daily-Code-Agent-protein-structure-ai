"""CPU heads for a control's features: ridge regression from the normal equations and scikit-learn's logistic regression.

A head is chosen on the validation split by the task's headline metric and reported on test. Ridge is solved once from
`X^T X` and `X^T Y`, accumulated over row chunks, so a multilabel release with thousands of columns costs a (d, d) and a
(d, v) matrix, never a dense copy of the targets per alpha. The intercept column is never penalized.

Symbols: n rows, d feature columns (d + 1 with the intercept), v target columns, k classes.
"""

from __future__ import annotations

import numpy as np

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from . import metrics
from .features import Features, Matrix
from .release import Release


ALPHAS = (0.1, 1.0, 10.0, 100.0, 1000.0)
INVERSE_REGULARIZATIONS = (0.01, 0.1, 1.0, 10.0)
CHUNK_ROWS = 8192
MAX_ITERATIONS = 2000
RIDGE = "ridge"
LOGISTIC = "logistic_regression"
PRIOR = "label_prior"
STANDARD_DEVIATION_FLOOR = 1e-6


@dataclass(frozen=True)
class Scaling:
    """Column standardization fit on the training split: centered and scaled when dense, scaled only when sparse."""

    mean: np.ndarray | None  # (d,) or None for a sparse matrix, which stays sparse
    scale: np.ndarray  # (d,)

    def apply(self, matrix: Matrix) -> Matrix:
        """The standardized (n, d) matrix, float32 when dense."""
        if is_sparse(matrix):
            from scipy import sparse

            return (matrix @ sparse.diags(1.0 / self.scale)).tocsr().astype(np.float32)  # (n, d)
        assert self.mean is not None
        return ((np.asarray(matrix, dtype=np.float64) - self.mean) / self.scale).astype(np.float32)  # (n, d)


@dataclass(frozen=True)
class Fit:
    """A head's chosen hyperparameter and its predictions on every split."""

    head: str
    hyperparameter: dict[str, float]
    validation_score: float
    predictions: dict[str, np.ndarray]  # split name -> (n,) scores or values, or (n, v) per-column scores


def is_sparse(matrix: Matrix) -> bool:
    return hasattr(matrix, "tocsr")


def fit_scaling(train: Matrix) -> Scaling:
    """Means and standard deviations of a dense training matrix; the largest magnitude per column of a sparse one."""
    if is_sparse(train):
        scale = np.asarray(abs(train).max(axis=0).todense()).ravel().astype(np.float64)  # (d,)
        return Scaling(None, np.where(scale > 0, scale, 1.0))
    dense = np.asarray(train, dtype=np.float64)  # (n, d)
    deviation = dense.std(axis=0)  # (d,)
    return Scaling(dense.mean(axis=0), np.maximum(deviation, STANDARD_DEVIATION_FLOOR))


def with_intercept(matrix: Matrix) -> Matrix:
    """The matrix with a column of ones appended: (n, d + 1)."""
    if is_sparse(matrix):
        from scipy import sparse

        ones = sparse.csr_matrix(np.ones((matrix.shape[0], 1), dtype=np.float32))  # (n, 1)
        return sparse.hstack([matrix, ones], format="csr")
    return np.hstack([np.asarray(matrix, dtype=np.float32), np.ones((matrix.shape[0], 1), dtype=np.float32)])  # (n, d+1)


def normal_equations(x: Matrix, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """`X^T X` (d+1, d+1) and `X^T Y` (d+1, v) in float64, accumulated over chunks of rows of a dense X."""
    # x: (n, d+1); y: (n, v)
    if is_sparse(x):
        gram = np.asarray((x.T @ x).todense(), dtype=np.float64)  # (d+1, d+1)
        moment = np.asarray(x.T @ y, dtype=np.float64)  # (d+1, v)
        return gram, moment  # (d+1, d+1), (d+1, v)
    width = x.shape[1]
    gram = np.zeros((width, width), dtype=np.float64)  # (d+1, d+1)
    moment = np.zeros((width, y.shape[1]), dtype=np.float64)  # (d+1, v)
    for start in range(0, x.shape[0], CHUNK_ROWS):
        chunk = np.asarray(x[start:start + CHUNK_ROWS], dtype=np.float64)  # (c, d+1)
        gram += chunk.T @ chunk
        moment += chunk.T @ np.asarray(y[start:start + CHUNK_ROWS], dtype=np.float64)
    return gram, moment  # (d+1, d+1), (d+1, v)


def ridge_weights(gram: np.ndarray, moment: np.ndarray, alpha: float) -> np.ndarray:
    """The ridge solution (d+1, v) with penalty `alpha` on every column but the intercept's, the last."""
    # gram: (d+1, d+1); moment: (d+1, v)
    penalty = np.full(gram.shape[0], alpha, dtype=np.float64)  # (d+1,)
    penalty[-1] = 0.0
    return np.linalg.solve(gram + np.diag(penalty), moment)  # (d+1, v)


def ridge_predict(x: Matrix, weights: np.ndarray) -> np.ndarray:
    """Predictions (n, v) of a ridge solution on a matrix with the intercept column."""
    # x: (n, d+1); weights: (d+1, v)
    return np.asarray(x @ weights, dtype=np.float64)  # (n, v)


def outscores(value: float, best: float) -> bool:
    """Whether a validation score beats the best so far. An undefined score (NaN, as a correlation of constant
    predictions is) beats nothing and loses to any defined one, so it cannot hold the choice by coming first."""
    return value > best or bool(np.isnan(best) and not np.isnan(value))


def choose_ridge(x: Mapping[str, Matrix], targets: np.ndarray, score: Callable[[np.ndarray], float],
                 alphas: Sequence[float] = ALPHAS) -> Fit:
    """Ridge at the alpha whose validation predictions score best; `score` takes the validation predictions (n, v)."""
    # targets: (n_train, v); score: (n_validation, v) -> float
    gram, moment = normal_equations(x["train"], targets)
    best: tuple[float, float, np.ndarray] | None = None
    for alpha in alphas:
        weights = ridge_weights(gram, moment, alpha)  # (d+1, v)
        value = score(ridge_predict(x["validation"], weights))
        if best is None or outscores(value, best[0]):
            best = (value, alpha, weights)
    assert best is not None, "ridge needs at least one alpha"
    value, alpha, weights = best
    return Fit(RIDGE, {"alpha": alpha}, value, {name: ridge_predict(matrix, weights) for name, matrix in x.items()})


def choose_logistic(x: Mapping[str, Matrix], classes: np.ndarray, score: Callable[[np.ndarray], float], *,
                    inverse_regularizations: Sequence[float] = INVERSE_REGULARIZATIONS, seed: int = 0) -> Fit:
    """Logistic regression at the inverse regularization whose validation probabilities score best.

    `classes` are the training rows' integer classes; the predictions are the probability of class 1 for two classes,
    (n,), and the (n, k) class probabilities otherwise. `score` takes the validation predictions.
    """
    from sklearn.linear_model import LogisticRegression

    # classes: (n_train,); score: (n_validation,) or (n_validation, k) -> float
    best: tuple[float, float, Any] | None = None
    for inverse in inverse_regularizations:
        model = LogisticRegression(C=inverse, max_iter=MAX_ITERATIONS, random_state=seed)
        model.fit(x["train"], classes)
        value = score(class_probabilities(model, x["validation"]))
        if best is None or outscores(value, best[0]):
            best = (value, inverse, model)
    assert best is not None, "logistic regression needs at least one inverse regularization"
    value, inverse, model = best
    return Fit(LOGISTIC, {"C": inverse}, value, {name: class_probabilities(model, matrix) for name, matrix in x.items()})


def class_probabilities(model: Any, x: Matrix) -> np.ndarray:
    """The positive-class probability (n,) of a two-class model, else the (n, k) probabilities."""
    probabilities = np.asarray(model.predict_proba(x), dtype=np.float64)  # (n, k)
    return probabilities[:, 1] if probabilities.shape[1] == 2 else probabilities  # (n,) or (n, k)


def fit_head(features: Features, release: Release) -> Fit:
    """The head of the release's task on a control's features, chosen on validation by the task's headline metric."""
    scaling = fit_scaling(features.matrices["train"])
    scaled = {name: scaling.apply(matrix) for name, matrix in features.matrices.items()}
    train, validation = release.splits["train"], release.splits["validation"]
    if release.task_type == "regression":
        observed = train.observed  # (n_train,)
        x = {name: with_intercept(matrix) for name, matrix in scaled.items()}
        x["train"] = x["train"][observed]
        targets = train.labels[observed][:, None]  # (n_observed, 1)
        fit = choose_ridge(x, targets, lambda predicted: metrics.spearman(validation.labels[validation.observed],
                                                                          predicted[validation.observed, 0]))
        return Fit(fit.head, fit.hyperparameter, fit.validation_score, {name: p[:, 0] for name, p in fit.predictions.items()})
    if release.task_type == "multilabel":
        x = {name: with_intercept(matrix) for name, matrix in scaled.items()}
        fit = choose_ridge(x, np.asarray(train.labels, dtype=np.float32), lambda predicted: metrics.micro_average_precision(
            validation.labels, validation.observed, predicted))
        return fit
    classes = train.labels[train.observed].astype(np.int64)  # (n_observed,)
    x = dict(scaled)
    x["train"] = x["train"][train.observed]
    if release.task_type == "binary":
        return choose_logistic(x, classes, lambda predicted: metrics.average_precision(
            validation.labels[validation.observed], predicted[validation.observed]))
    return choose_logistic(x, classes, lambda predicted: metrics.macro_f1(
        validation.labels[validation.observed].astype(np.int64), predicted[validation.observed].argmax(axis=1), release.width))


def prior_fit(release: Release) -> Fit:
    """The label prior: the training split's mean value, positive rate, class frequencies or per-column positive rates."""
    train = release.splits["train"]
    if release.task_type == "multilabel":
        counts = train.observed.sum(axis=0)  # (v,)
        rate = np.where(counts > 0, (train.labels > 0).sum(axis=0) / np.maximum(counts, 1), 0.0)  # (v,)
        return Fit(PRIOR, {}, float("nan"), {name: np.tile(rate, (split.rows, 1)) for name, split in release.splits.items()})
    observed = train.labels[train.observed]  # (n_observed,)
    if release.task_type == "multiclass":
        frequency = np.bincount(observed.astype(np.int64), minlength=release.width) / max(len(observed), 1)  # (k,)
        return Fit(PRIOR, {}, float("nan"), {name: np.tile(frequency, (split.rows, 1)) for name, split in release.splits.items()})
    constant = float(observed.mean()) if len(observed) else 0.0
    return Fit(PRIOR, {}, float("nan"), {name: np.full(split.rows, constant) for name, split in release.splits.items()})
