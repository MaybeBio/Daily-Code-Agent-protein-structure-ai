"""E16c, exploratory: the protein-level concept tasks read from several models' pooled streams, model against model.

Each model reads every distinct protein of the tasks once, and its stream is mean-pooled over the protein's residues at
a quarter, a half, three quarters and the end of its stack (`pooled_means`). A task's labels become target columns
(`sparse_probes.task_targets`): one for a binary task, one per class or label that has enough positives and negatives
for a multiclass or multilabel task, one per value for a regression task. Per task, depth and probe (`linear`, or `mlp`
with one hidden layer), one probe predicts all the task's targets from the pooled stream standardized on training
proteins, fitted by full-batch AdamW on the training split and kept at its step of lowest validation loss. The depth
and probe a model uses for a task are the pair of best primary metric on validation proteins, and its test metrics
are read there.

Metrics, macro over a task's targets: for binary targets PR AUC (the primary metric), ROC AUC and balanced MCC at the
threshold chosen on validation proteins (`foundry.metrics.binary.balanced_mcc`); for continuous targets Spearman's rho
(primary) and R squared.

`paired_differences` redraws each task's test proteins, the same draw for both models, and gives the mean over tasks
of one model's primary metric less another's with its 95% interval.

Symbols: p proteins; n proteins of a split; d model width; t targets of a task; r redraws.
"""

from __future__ import annotations

import math
import numpy as np
import pandas as pd
import torch

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from torch import Tensor, nn
from torch.nn import functional

from foundry.metrics.binary import balanced_mcc
from .causal import transformer_blocks
from .erasure_levels import pooled_streams
from .sparse_probes import Targets, column_auroc, column_spearman


DEPTH_SHARES = (0.25, 0.5, 0.75, 1.0)
PROBES = ("linear", "mlp")
HIDDEN = 512
STEPS = 500
CHECK_EVERY = 20
LEARNING_RATE = 5e-3
WEIGHT_DECAY = 1e-2
REDRAWS = 1_000
SEED = 24895


@dataclass(frozen=True)
class Choice:
    """The depth and probe a model reads a task with, and what it predicts for the held-out proteins."""

    share: float
    probe: str
    validation_primary: float
    validation: np.ndarray  # (n_validation, t), scores of binary targets or values of continuous ones
    test: np.ndarray  # (n_test, t)


def depth_blocks(blocks: int) -> tuple[int, ...]:
    """The 0-based block at a quarter, a half, three quarters and the end of a stack of `blocks`."""
    return tuple(math.ceil(share * blocks) - 1 for share in DEPTH_SHARES)


def pooled_means(model: nn.Module, sequences: Sequence[str], device: torch.device, *, token_budget: int) -> dict[float, np.ndarray]:
    """Each protein's mean stream at each depth share, in protein order."""
    blocks = depth_blocks(len(transformer_blocks(model)))
    pooled = pooled_streams(model, sequences, blocks, device, token_budget=token_budget)
    return {share: pooled[block][0].numpy() for share, block in zip(DEPTH_SHARES, blocks, strict=True)}  # (p, d) each


def fit_probe(features: Tensor, targets: Tensor, held_features: Tensor, held_targets: Tensor, *, kind: str, hidden: int | None,
              steps: int = STEPS, seed: int = SEED) -> Callable[[Tensor], Tensor]:
    """A probe of all a task's targets, kept at its step of lowest loss on the held proteins. The returned function
    gives scores (logits) for binary targets and values for continuous ones."""
    # features: (n, d); targets: (n, t), 0 or 1 for binary targets; held_features: (m, d); held_targets: (m, t)
    center, scale = features.mean(dim=0), features.std(dim=0).clamp(min=1e-6)  # (d,), (d,)
    shift = targets.mean(dim=0) if kind == "continuous" else torch.zeros(targets.shape[1], device=targets.device)  # (t,)
    spread = targets.std(dim=0).clamp(min=1e-6) if kind == "continuous" else torch.ones_like(shift)  # (t,)
    inputs, held_inputs = (features - center) / scale, (held_features - center) / scale  # (n, d), (m, d)
    wanted, held_wanted = (targets - shift) / spread, (held_targets - shift) / spread  # (n, t), (m, t)
    loss = functional.mse_loss if kind == "continuous" else functional.binary_cross_entropy_with_logits  # noqa: pytorch-cross-entropy - E16's recorded probes were fitted with it
    torch.manual_seed(seed)
    width, outputs = features.shape[1], targets.shape[1]
    head = nn.Linear(width, outputs) if hidden is None else nn.Sequential(nn.Linear(width, hidden), nn.GELU(), nn.Linear(hidden, outputs))
    head = head.to(features.device)
    optimizer = torch.optim.AdamW(head.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
    best, best_state = math.inf, None
    for step in range(steps):
        optimizer.zero_grad()
        loss(head(inputs), wanted).backward()
        optimizer.step()
        if (step + 1) % CHECK_EVERY == 0 or step + 1 == steps:
            with torch.no_grad():
                held_loss = float(loss(head(held_inputs), held_wanted))
            if held_loss < best:
                best, best_state = held_loss, {name: value.clone() for name, value in head.state_dict().items()}
    head.load_state_dict(best_state)
    head.eval()

    @torch.no_grad()
    def predict(given: Tensor) -> Tensor:
        # given: (n, d)
        return head((given - center) / scale) * spread + shift  # (n, t)

    return predict  # (n, d) -> (n, t)


def average_precisions(scores: np.ndarray, labels: np.ndarray, weights: np.ndarray | None = None, *,
                       device: str | torch.device = "cpu") -> np.ndarray:
    """Each target's average precision under each column of row weights (one column of ones when none are given). A
    protein drawn k times weighs k; tied scores are ranked in row order; a target with no positive weight is NaN."""
    # scores: (n, t); labels: (n, t) bool; weights: (n, r)
    ranked = torch.as_tensor(scores, device=device)  # (n, t)
    truth = torch.as_tensor(labels, device=device).double()  # (n, t)
    weight = torch.ones(len(scores), 1, dtype=torch.float64, device=device) if weights is None else torch.as_tensor(
        weights, dtype=torch.float64, device=device)  # (n, r)
    values = torch.empty(scores.shape[1], weight.shape[1], dtype=torch.float64, device=device)  # (t, r)
    for target in range(scores.shape[1]):
        order = torch.argsort(ranked[:, target], descending=True, stable=True)  # (n,)
        drawn = weight[order]  # (n, r)
        positive = truth[order, target].unsqueeze(1) * drawn  # (n, r)
        found, seen = positive.cumsum(dim=0), drawn.cumsum(dim=0)  # (n, r) each
        precision = torch.where(seen > 0, found / seen.clamp_min(1e-300), torch.zeros_like(found))  # (n, r)
        total = found[-1]  # (r,)
        values[target] = torch.where(total > 0, (positive * precision).sum(dim=0) / total.clamp_min(1e-300),
                                     torch.full_like(total, torch.nan))
    return values.cpu().numpy()  # (t, r)


def primary(kind: str, predicted: np.ndarray, truth: np.ndarray, *, device: str | torch.device = "cpu") -> float:
    """A task's primary metric on one split: macro PR AUC over the binary targets that have a positive there, or the
    mean Spearman's rho of the continuous ones. NaN when no binary target has a positive."""
    # predicted, truth: (n, t)
    if kind == "continuous":
        return float(column_spearman(predicted, truth).mean())
    precisions = average_precisions(predicted, truth, device=device)[:, 0]  # (t,)
    return float(np.nanmean(precisions)) if np.isfinite(precisions).any() else float("nan")


def held_out_metrics(kind: str, choice: Choice, validation_truth: np.ndarray, test_truth: np.ndarray) -> dict[str, float]:
    """A task's test metrics, macro over its targets."""
    # choice.validation, validation_truth: (n_validation, t); choice.test, test_truth: (n_test, t)
    if kind == "continuous":
        residual = ((choice.test - test_truth) ** 2).sum(axis=0)  # (t,)
        total = ((test_truth - test_truth.mean(axis=0)) ** 2).sum(axis=0).clip(min=1e-12)  # (t,)
        return {"spearman": float(column_spearman(choice.test, test_truth).mean()), "r_squared": float((1.0 - residual / total).mean())}
    balanced = []
    for target in range(test_truth.shape[1]):
        held = validation_truth[:, target]  # (n_validation,)
        if held.any() and not held.all():
            threshold = balanced_mcc(held.astype(np.int64), choice.validation[:, target])["threshold"]
            balanced.append(balanced_mcc(test_truth[:, target].astype(np.int64), choice.test[:, target], threshold=threshold)["balanced_mcc"])
    return {"pr_auc": primary(kind, choice.test, test_truth),
            "roc_auc": float(column_auroc(choice.test, test_truth).mean()),
            "balanced_mcc": float(np.mean(balanced)) if balanced else float("nan"), "targets_with_mcc": float(len(balanced))}


def read_task(features: Mapping[float, np.ndarray], rows: Mapping[str, np.ndarray], targets: Targets, device: torch.device, *,
              steps: int = STEPS) -> tuple[Choice, pd.DataFrame]:
    """The depth and probe of best validation primary metric for one model and task, and every pair's validation
    metric."""
    # features: (p, d) for each depth share; rows: (n_split,) each example's protein, for each split
    # targets.values: (n_split, t) for each split
    truth = {split: torch.from_numpy(values.astype(np.float32)).to(device) for split, values in targets.values.items()}
    tried, best = [], None
    for share, pooled in features.items():
        given = {split: torch.from_numpy(pooled[rows[split]]).float().to(device) for split in truth}  # (n_split, d) each
        for probe in PROBES:
            predict = fit_probe(given["train"], truth["train"], given["validation"], truth["validation"], kind=targets.kind,
                                hidden=None if probe == "linear" else HIDDEN, steps=steps)
            held = predict(given["validation"]).cpu().numpy()  # (n_validation, t)
            score = primary(targets.kind, held, targets.values["validation"], device=device)
            tried.append({"share": share, "probe": probe, "validation_primary": score})
            score = -math.inf if math.isnan(score) else score
            if best is None or score > best.validation_primary:
                best = Choice(share, probe, score, held, predict(given["test"]).cpu().numpy())
    return best, pd.DataFrame(tried)


def paired_differences(kinds: Mapping[str, str], first: Mapping[str, np.ndarray], second: Mapping[str, np.ndarray],
                       truth: Mapping[str, np.ndarray], *, redraws: int = REDRAWS, seed: int = SEED,
                       device: str | torch.device = "cpu") -> dict[str, object]:
    """The mean over tasks of the first model's primary test metric less the second's, with its 95% interval from
    redrawing each task's test proteins, the same proteins for both models."""
    # first, second, truth: (n_test, t) for each task
    generator = np.random.default_rng(seed)
    observed, drawn = {}, []
    for task, kind in kinds.items():
        labels = truth[task]
        observed[task] = primary(kind, first[task], labels, device=device) - primary(kind, second[task], labels, device=device)
        picks = generator.integers(0, len(labels), size=(redraws, len(labels)))  # (r, n_test)
        if kind == "continuous":
            drawn.append(np.array([column_spearman(first[task][pick], labels[pick]).mean()
                                   - column_spearman(second[task][pick], labels[pick]).mean() for pick in picks]))
        else:
            weights = np.stack([np.bincount(pick, minlength=len(labels)) for pick in picks], axis=1).astype(np.float64)  # (n_test, r)
            drawn.append(np.nanmean(average_precisions(first[task], labels, weights, device=device), axis=0)
                         - np.nanmean(average_precisions(second[task], labels, weights, device=device), axis=0))
    means = np.mean(np.stack(drawn), axis=0)  # (r,)
    return {"mean": float(np.mean(list(observed.values()))), "low": float(np.quantile(means, 0.025)),
            "high": float(np.quantile(means, 0.975)), "by_task": observed, "redraws": redraws}
