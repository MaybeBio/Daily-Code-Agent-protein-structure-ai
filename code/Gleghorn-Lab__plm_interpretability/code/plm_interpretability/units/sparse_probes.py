"""E6: k-sparse probes, whether a handful of native units reads a concept better than a handful of rotated ones.

Each protein-level concept task gives targets: a binary task its label, a multiclass task each class against the rest, a
multilabel task each label, a regression task each of its values. A binary target is kept with at least 20 positive and
20 negative training proteins and 5 of each among test proteins. For each target the k units with the largest
standardized effect on training proteins (|Cohen's d| for a binary target, |Pearson r| for a continuous one) feed an
L2-regularized logistic regression (ridge for a continuous target) fitted on training proteins and read on test
proteins by ROC AUC (Spearman's rho), for k of 1, 2, 4, 8 and 16 (Gurnee et al., 2023), beside a dense probe on every
unit. Units are the mean-pooled products z of each depth block, in the native basis and under the ten preregistered
rotations (mean pooling commutes with a rotation, so a rotated basis's pooled units are the native ones times the
rotation), and at the rotation block the products' maxima and minima, native and rotated, which the extraction keeps
because they do not commute; mean poles and mean gates are probed natively. At each k the native median over targets is
set against the ten rotation medians (`bootstrap.rotation_test`).

Symbols: n proteins; w units; t targets; k selected units.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import torch

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from scipy import stats
from torch import Tensor

from .bootstrap import rotation_test
from .concepts import ConceptProteins, ConceptTask, ExtractionPlan, read_feature
from .experiments import ROTATION_SEEDS
from .rotations import haar_rotation


KS = (1, 2, 4, 8, 16)
MIN_TRAIN = 20
MIN_TEST = 5
PENALTY = 1.0  # L2 weight on the summed loss, scikit-learn's C = 1
NEWTON_STEPS = 50
TOLERANCE = 1e-10
HALVINGS = 40  # a step halved this often is about 1e-12 of Newton's
CURVATURE_FLOOR = 1e-12  # keeps the intercept's curvature positive when every probability saturates
LOSS_SLACK = 1e-12  # a trial loss within this relative rounding of the current one counts as no rise


@dataclass(frozen=True)
class Targets:
    task: str
    kind: str  # "binary" or "continuous"
    names: tuple[str, ...]
    values: dict[str, np.ndarray]  # split -> (n_split, t), bool for binary targets, float64 for continuous ones


def task_targets(task: ConceptTask, *, min_train: int = MIN_TRAIN, min_test: int = MIN_TEST) -> Targets:
    """A task's targets, binary ones filtered by their training and test counts."""
    if task.kind == "regression":
        values = {split: np.stack(frame["label"].to_numpy()).astype(np.float64) for split, frame in task.frames.items()}
        return Targets(task.name, "continuous", task.label_names, values)  # (n_split, t)
    if task.kind == "binary":
        values = {split: frame["label"].to_numpy().astype(bool)[:, None] for split, frame in task.frames.items()}
    elif task.kind == "multiclass":
        classes = np.arange(len(task.label_names))  # (t,)
        values = {split: frame["label"].to_numpy()[:, None] == classes[None, :] for split, frame in task.frames.items()}
    elif task.kind == "multilabel":
        values = {split: np.stack(frame["label"].to_numpy()).astype(bool) for split, frame in task.frames.items()}
    else:
        raise ValueError(f"Task {task.name} has an unknown type {task.kind!r}.")
    keep = np.ones(values["train"].shape[1], dtype=bool)  # (t,)
    for split, minimum in (("train", min_train), ("test", min_test)):
        positives = values[split].sum(axis=0)  # (t,)
        keep &= (positives >= minimum) & (len(values[split]) - positives >= minimum)
    names = tuple(name for name, kept in zip(task.label_names, keep, strict=True) if kept)
    return Targets(task.name, "binary", names, {split: value[:, keep] for split, value in values.items()})  # (n_split, t)


def standardized(train: np.ndarray, *others: np.ndarray) -> list[Tensor]:
    """Features centered and scaled by their training mean and standard deviation (constant columns stay zero)."""
    # train: (n_train, w); others: (n_other, w) each
    mean = train.mean(axis=0, keepdims=True)  # (1, w)
    scale = train.std(axis=0, keepdims=True)  # (1, w)
    scale = np.where(scale > 0, scale, 1.0)  # (1, w)
    return [torch.from_numpy((array - mean) / scale) for array in (train, *others)]  # (n_split, w) each


def effect_order(features: Tensor, values: Tensor, kind: str) -> Tensor:
    """Per target, the units by decreasing |Cohen's d| (binary) or |Pearson r| (continuous) on these proteins."""
    # features: (n, w) standardized; values: (n, t)
    if kind == "continuous":
        target = (values - values.mean(dim=0)) / values.std(dim=0, unbiased=False).clamp(min=1e-12)  # (n, t)
        effect = features.T @ target / features.shape[0]  # (w, t), Pearson r since features are standardized
    else:
        positive = values.double()  # (n, t)
        count = positive.sum(dim=0)  # (t,)
        rest = features.shape[0] - count  # (t,)
        mean_positive = features.T @ positive / count  # (w, t)
        mean_rest = features.T @ (1 - positive) / rest  # (w, t)
        square_positive = (features**2).T @ positive / count  # (w, t)
        square_rest = (features**2).T @ (1 - positive) / rest  # (w, t)
        pooled = (count * (square_positive - mean_positive**2) + rest * (square_rest - mean_rest**2)) / (count + rest - 2)  # (w, t)
        effect = (mean_positive - mean_rest) / pooled.clamp(min=1e-12).sqrt()  # (w, t)
    return effect.abs().T.argsort(dim=1, descending=True, stable=True)  # (t, w)


def penalized_logistic_loss(design: Tensor, target: Tensor, weights: Tensor, ridge: Tensor) -> Tensor:
    """Each target's summed logistic loss plus half its ridge-weighted squared weights, the objective `fit_logistic`
    minimizes."""
    # design: (t, n, k + 1); target: (t, n); weights: (t, k + 1); ridge: (k + 1,)
    logits = torch.einsum("tnk,tk->tn", design, weights)  # (t, n)
    fit = (torch.nn.functional.softplus(logits) - target * logits).sum(dim=1)  # (t,)
    return fit + 0.5 * (ridge * weights**2).sum(dim=1)  # (t,)


def fit_logistic(features: Tensor, labels: Tensor, *, penalty: float = PENALTY) -> Tensor:
    """L2-regularized logistic regression for every target at once by Newton's method, the intercept unpenalized;
    returns (t, k + 1) weights with the intercept last.

    A step that raises a target's penalized loss is halved until it does not, and the curvature is floored: from
    standardized features with extreme values a full step can saturate every probability, which leaves the unpenalized
    intercept no curvature and the Hessian singular (ESMC-600's block 17 in E6, 2026-11-07). Where full steps descend,
    the iterates are plain Newton's.
    """
    # features: (t, n, k); labels: (t, n) bool
    design = torch.cat((features, features.new_ones(features.shape[:2] + (1,))), dim=2)  # (t, n, k + 1)
    target = labels.to(design.dtype)  # (t, n)
    ridge = torch.full((design.shape[2],), penalty, dtype=design.dtype, device=design.device)  # (k + 1,)
    ridge[-1] = 0.0
    weights = design.new_zeros(design.shape[0], design.shape[2])  # (t, k + 1)
    loss = penalized_logistic_loss(design, target, weights, ridge)  # (t,)
    for _ in range(NEWTON_STEPS):
        probability = torch.sigmoid(torch.einsum("tnk,tk->tn", design, weights))  # (t, n)
        gradient = torch.einsum("tnk,tn->tk", design, probability - target) + ridge * weights  # (t, k + 1)
        curvature = (probability * (1 - probability)).clamp(min=CURVATURE_FLOOR)  # (t, n)
        hessian = torch.einsum("tnk,tn,tnj->tkj", design, curvature, design) + torch.diag(ridge)  # (t, k + 1, k + 1)
        step = torch.linalg.solve(hessian, gradient)  # (t, k + 1)
        scale = torch.ones_like(loss)  # (t,)
        for _ in range(HALVINGS):
            trial = penalized_logistic_loss(design, target, weights - scale[:, None] * step, ridge)  # (t,)
            rising = trial > loss + LOSS_SLACK * loss.abs().clamp(min=1.0)  # (t,)
            if not bool(rising.any()):
                break
            scale = torch.where(rising, scale / 2, scale)
        step = scale[:, None] * step  # (t, k + 1)
        weights = weights - step
        loss = penalized_logistic_loss(design, target, weights, ridge)  # (t,)
        if float(step.abs().max()) < TOLERANCE:
            break
    return weights  # (t, k + 1)


def fit_ridge(features: Tensor, values: Tensor, *, penalty: float = PENALTY) -> Tensor:
    """Ridge regression for every target at once, the intercept unpenalized; returns (t, k + 1) weights, intercept last."""
    # features: (t, n, k); values: (t, n)
    feature_mean = features.mean(dim=1, keepdim=True)  # (t, 1, k)
    value_mean = values.mean(dim=1, keepdim=True)  # (t, 1)
    centered = features - feature_mean  # (t, n, k)
    gram = centered.transpose(1, 2) @ centered + penalty * torch.eye(features.shape[2], dtype=features.dtype)  # (t, k, k)
    slope = torch.linalg.solve(gram, torch.einsum("tnk,tn->tk", centered, values - value_mean))  # (t, k)
    intercept = value_mean.squeeze(1) - torch.einsum("tk,tk->t", feature_mean.squeeze(1), slope)  # (t,)
    return torch.cat((slope, intercept.unsqueeze(1)), dim=1)  # (t, k + 1)


def fit_dense_logistic(features: Tensor, labels: Tensor, *, penalty: float = PENALTY, iterations: int = 1000) -> Tensor:
    """L2-regularized logistic regression of every target on all units, the intercept unpenalized; returns (w + 1, t)
    weights, intercept last. The targets' losses are separate, so one L-BFGS run over all of them reaches each one's
    optimum."""
    # features: (n, w); labels: (n, t) bool
    design = torch.cat((features, features.new_ones(features.shape[0], 1)), dim=1)  # (n, w + 1)
    target = labels.to(design.dtype)  # (n, t)
    penalized = torch.ones(design.shape[1], 1, dtype=design.dtype, device=design.device)  # (w + 1, 1)
    penalized[-1] = 0.0
    weights = design.new_zeros(design.shape[1], target.shape[1]).requires_grad_()  # (w + 1, t)
    optimizer = torch.optim.LBFGS([weights], lr=1.0, max_iter=iterations, tolerance_grad=1e-9, tolerance_change=1e-14,
                                  history_size=20, line_search_fn="strong_wolfe")

    def objective() -> Tensor:
        optimizer.zero_grad()
        logits = design @ weights  # (n, t)
        loss = (torch.nn.functional.softplus(logits) - target * logits).sum() + 0.5 * penalty * ((weights * penalized) ** 2).sum()
        loss.backward()
        return loss  # ()

    optimizer.step(objective)
    return weights.detach()  # (w + 1, t)


def fit_dense_ridge(features: Tensor, values: Tensor, *, penalty: float = PENALTY) -> Tensor:
    """Ridge regression of every target on all units, the intercept unpenalized; returns (w + 1, t), intercept last."""
    # features: (n, w); values: (n, t)
    feature_mean, value_mean = features.mean(dim=0), values.mean(dim=0)  # (w,), (t,)
    centered = features - feature_mean  # (n, w)
    gram = centered.T @ centered + penalty * torch.eye(features.shape[1], dtype=features.dtype)  # (w, w)
    slope = torch.linalg.solve(gram, centered.T @ (values - value_mean))  # (w, t)
    return torch.cat((slope, (value_mean - feature_mean @ slope).unsqueeze(0)), dim=0)  # (w + 1, t)


def column_auroc(scores: np.ndarray, labels: np.ndarray) -> np.ndarray:
    """Tie-corrected ROC AUC of each score column against its own label column."""
    # scores: (n, t); labels: (n, t) bool
    ranks = stats.rankdata(scores, axis=0)  # (n, t)
    positives = labels.sum(axis=0)  # (t,)
    negatives = len(labels) - positives  # (t,)
    rank_sum = (ranks * labels).sum(axis=0)  # (t,)
    return (rank_sum - positives * (positives + 1) / 2) / (positives * negatives)  # (t,)


def column_spearman(predicted: np.ndarray, truth: np.ndarray) -> np.ndarray:
    """Spearman's rho of each prediction column against its own truth column."""
    # predicted, truth: (n, t)
    first = stats.rankdata(predicted, axis=0)  # (n, t)
    second = stats.rankdata(truth, axis=0)  # (n, t)
    first = (first - first.mean(axis=0)) / first.std(axis=0).clip(min=1e-12)  # (n, t)
    second = (second - second.mean(axis=0)) / second.std(axis=0).clip(min=1e-12)  # (n, t)
    return (first * second).mean(axis=0)  # (t,)


def _test_scores(predicted: np.ndarray, targets: Targets) -> np.ndarray:
    # predicted: (n_test, t)
    truth = np.asarray(targets.values["test"])  # (n_test, t)
    return column_spearman(predicted, truth) if targets.kind == "continuous" else column_auroc(predicted, truth)  # (t,)


def probe_scores(features: Mapping[str, np.ndarray], targets: Targets, *, ks: Sequence[int] = KS, dense: bool = False) -> pd.DataFrame:
    """Test scores of every target's k-sparse probes, and with `dense` of its probe on every unit (k = 0)."""
    # features: (n_split, w) by split
    train, test = standardized(features["train"], features["test"])  # (n_train, w), (n_test, w)
    train_values = torch.from_numpy(np.asarray(targets.values["train"], dtype=np.float64))  # (n_train, t)
    order = effect_order(train, train_values, targets.kind)  # (t, w)
    scores: dict[int, np.ndarray] = {}
    for k in ks:
        train_chosen = train.T[order[:, :k]].transpose(1, 2)  # (t, n_train, k)
        test_chosen = test.T[order[:, :k]].transpose(1, 2)  # (t, n_test, k)
        if targets.kind == "continuous":
            weights = fit_ridge(train_chosen, train_values.T)  # (t, k + 1)
        else:
            weights = fit_logistic(train_chosen, train_values.T.bool())  # (t, k + 1)
        predicted = torch.einsum("tnk,tk->tn", test_chosen, weights[:, :-1]) + weights[:, -1:]  # (t, n_test)
        scores[k] = _test_scores(predicted.T.numpy(), targets)  # (t,)
    if dense:
        if targets.kind == "continuous":
            weights = fit_dense_ridge(train, train_values)  # (w + 1, t)
        else:
            weights = fit_dense_logistic(train, train_values.bool())  # (w + 1, t)
        scores[0] = _test_scores((test @ weights[:-1] + weights[-1]).numpy(), targets)  # (t,)
    return pd.DataFrame([{"task": targets.task, "target": name, "k": k, "score": float(value)}
                         for k, values in scores.items() for name, value in zip(targets.names, values, strict=True)])


def feature_sets(extraction: Path, plan: ExtractionPlan, seeds: Sequence[int] = ROTATION_SEEDS) -> Iterator[tuple[int, str, str, np.ndarray]]:
    """Every (block, features, basis, array) E6 probes: mean-pooled products at each depth, native and under each rotation
    (the pooled native means times the rotation); native mean poles and mean gates; and at the rotation block the
    products' maxima and minima side by side, native and under each stored rotation."""
    for block in plan.depths:
        native = np.asarray(read_feature(extraction, block, "z_mean"), dtype=np.float64)  # (n, f)
        yield block, "mean", "native", native
        for seed in seeds:
            yield block, "mean", f"rotation{seed}", native @ haar_rotation(native.shape[1], seed, dtype=torch.float64).numpy()  # (n, f)
        for features, stored in (("poles", "poles_mean"), ("gate", "gate_mean")):
            yield block, features, "native", np.asarray(read_feature(extraction, block, stored), dtype=np.float64)  # (n, w)
    if plan.rotation_block is not None:
        block = plan.rotation_block
        for basis, prefix in (("native", "z"), *((f"rotation{seed}", f"rotation{seed}") for seed in plan.rotation_seeds)):
            extremes = [read_feature(extraction, block, f"{prefix}_{statistic}") for statistic in ("max", "min")]  # (n, f) each
            yield block, "extremes", basis, np.hstack(extremes).astype(np.float64)  # (n, 2f)


def run_e6(
    extraction: Path,
    proteins: ConceptProteins,
    tasks: Mapping[str, ConceptTask],
    plan: ExtractionPlan,
    *,
    seeds: Sequence[int] = ROTATION_SEEDS,
    log: Callable[[str], None] = print,
) -> pd.DataFrame:
    """Every target of every task probed on every feature set of an extraction; the native mean-pooled products also
    get the dense probe, the reference for every k."""
    targets = {name: task_targets(task) for name, task in tasks.items()}
    targets = {name: target for name, target in targets.items() if target.names}
    tables = []
    for block, features, basis, array in feature_sets(extraction, plan, seeds):  # (n, w)
        dense = features == "mean" and basis == "native"
        for name, target in targets.items():
            split_features = {split: array[proteins.rows[name][split]] for split in ("train", "test")}  # (n_split, w)
            tables.append(probe_scores(split_features, target, dense=dense).assign(block=block, features=features, basis=basis))
        log(f"E6 block {block}, {features}, {basis}: {len(targets)} tasks probed")
    return pd.concat(tables, ignore_index=True)


def rotation_summary(table: pd.DataFrame) -> pd.DataFrame:
    """Per block and feature set (when the table has them) and k, the native median score over targets against the
    rotations' (`bootstrap.rotation_test`); the dense probe (k = 0) and feature sets without rotations are left out."""
    # table: basis ("native" or "rotation<seed>"), k, score, and optionally block and features
    keys = [key for key in ("block", "features", "k") if key in table.columns]
    rows = []
    for key, group in table[table["k"] > 0].groupby(keys):
        native = group.loc[group["basis"] == "native", "score"].to_numpy()  # (t,)
        rotated = [values["score"].to_numpy() for basis, values in group.groupby("basis") if basis != "native"]
        if not rotated:
            continue
        test = rotation_test(native, rotated)
        rows.append({**dict(zip(keys, (key if isinstance(key, tuple) else (key,)), strict=True)), "native": test.native,
                     "best_rotation": max(test.rotations), "rotation_range": max(test.rotations) - min(test.rotations),
                     "rank_p": test.rank_p, "privileged": test.privileged})
    return pd.DataFrame(rows)
