"""E11: does an axis-aligned learner reward the native basis? XGBoost on native, rotated and SAE fingerprints.

A tree splits on one feature at a time, so it can use a basis whose axes mean something, while a linear or MLP readout is
blind to a rotation of its input. At each model's 75% block, the atlas and SAE site, XGBoost is trained on training
proteins for each concept target on six fingerprints of the extraction (`concepts.ConceptExtraction`): the products'
per-protein maxima and minima side by side, native and under rotations 0 and 1; their per-protein means, native and under
rotation 0; and the SAE's max-pooled latents. Means commute with a rotation, so the mean pair holds the same information
in two bases and any difference between them is the learner's; extremes do not commute, so their pair adds what pooling
in the native basis keeps. Settings are XGBoost's defaults, stated in `SETTINGS`, with 100 rounds, identical for every
fingerprint and fixed before any result.

Targets are those E6 keeps (`sparse_probes.task_targets`) that also have 5 positive and 5 negative validation proteins,
at most 10 a task drawn with a fixed seed, a bound on the run's cost; ProtParam's 31 values are all regressed. Test
proteins are scored by PR AUC, ROC AUC and balanced MCC at the threshold validation proteins choose
(`foundry.controls.metrics.binary_scores`), continuous targets by Spearman's rho.

Symbols: n proteins; f units; c SAE latents; w a fingerprint's width; t targets.
"""

from __future__ import annotations

import json
import numpy as np
import pandas as pd
import torch
import xgboost

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from foundry.controls.metrics import binary_scores
from foundry.pilot import Pilot
from .bootstrap import median_interval
from .concepts import ConceptProteins, ConceptTask, read_feature
from .rotations import haar_rotation
from .sparse_probes import Targets, column_spearman, task_targets


SEED = 24895
ROTATIONS = (0, 1)  # of the extremes; the mean pair uses the first
TARGETS_PER_TASK = 10
MIN_VALIDATION = 5
ROUNDS = 100
SETTINGS = {"eta": 0.3, "max_depth": 6, "min_child_weight": 1.0, "subsample": 1.0, "colsample_bytree": 1.0, "lambda": 1.0,
            "max_bin": 256, "tree_method": "hist", "seed": SEED}  # XGBoost's defaults, stated so a release cannot move them
OBJECTIVES = {"binary": "binary:logistic", "continuous": "reg:squarederror"}
SPLITS = ("train", "validation", "test")
COMPARISONS = {  # name -> (first, second) fingerprints as (features, basis group); the difference is first minus second
    "extremes: native - rotated": (("extremes", "native"), ("extremes", "rotation")),
    "mean: native - rotated": (("mean", "native"), ("mean", "rotation")),
    "native extremes - SAE": (("extremes", "native"), ("sae", "native")),
}


@dataclass(eq=False)
class Fingerprint:
    features: str  # "extremes", "mean" or "sae"
    basis: str  # "native" or "rotation<seed>"
    parts: tuple[np.ndarray, ...]  # stored (n, w_i) arrays, joined side by side
    rotation: np.ndarray | None = field(default=None, repr=False)  # (w, w), applied to the joined parts

    @property
    def width(self) -> int:
        return sum(part.shape[1] for part in self.parts)

    def take(self, rows: np.ndarray) -> np.ndarray:
        """The fingerprint of the proteins at `rows`, float32."""
        # rows: (r,)
        joined = np.hstack([np.asarray(part[rows]) for part in self.parts])  # (r, w)
        if self.rotation is not None:
            joined = joined.astype(np.float64) @ self.rotation  # (r, w)
        return joined.astype(np.float32, copy=False)  # (r, w)


@dataclass(frozen=True)
class PayoffPlan:
    block: int
    prints: tuple[Fingerprint, ...]
    targets: dict[str, Targets]  # task -> its chosen targets
    fits: tuple[tuple[str, int, int], ...]  # (task, fingerprint index, target column), task by task

    def work(self, fit: tuple[str, int, int], proteins: ConceptProteins) -> int:
        """Training proteins times fingerprint width, the pilot's item count for one fit."""
        return len(proteins.rows[fit[0]]["train"]) * self.prints[fit[1]].width


def fingerprints(extraction: Path, block: int, *, rotations: Sequence[int] = ROTATIONS) -> tuple[Fingerprint, ...]:
    """The six fingerprints E11 compares at one block of an extraction, memory-mapped until taken."""
    def extremes(prefix: str) -> tuple[np.ndarray, ...]:
        return tuple(read_feature(extraction, block, f"{prefix}_{statistic}") for statistic in ("max", "min"))  # (n, f) each

    mean = read_feature(extraction, block, "z_mean")  # (n, f)
    rotation = haar_rotation(mean.shape[1], rotations[0], dtype=torch.float64).numpy()  # (f, f)
    return (Fingerprint("extremes", "native", extremes("z")),
            *(Fingerprint("extremes", f"rotation{seed}", extremes(f"rotation{seed}")) for seed in rotations),
            Fingerprint("mean", "native", (mean,)), Fingerprint("mean", f"rotation{rotations[0]}", (mean,), rotation),
            Fingerprint("sae", "native", (read_feature(extraction, block, "sae_max"),)))


def chosen_targets(targets: Targets, *, limit: int = TARGETS_PER_TASK, minimum: int = MIN_VALIDATION, seed: int = SEED) -> Targets:
    """A task's binary targets with `minimum` positive and negative validation proteins, at most `limit` of them drawn
    with `seed`; continuous targets are kept whole."""
    if targets.kind == "continuous":
        return targets
    validation = targets.values["validation"]  # (n_validation, t)
    positives = validation.sum(axis=0)  # (t,)
    keep = np.flatnonzero((positives >= minimum) & (len(validation) - positives >= minimum))  # (e,)
    if len(keep) > limit:
        keep = np.sort(np.random.default_rng(seed).choice(keep, size=limit, replace=False))  # (limit,)
    return Targets(targets.task, targets.kind, tuple(targets.names[index] for index in keep),
                   {split: values[:, keep] for split, values in targets.values.items()})  # (n_split, t_kept)


def payoff_plan(extraction: Path, tasks: Mapping[str, ConceptTask], block: int) -> PayoffPlan:
    """Every fit of E11 at one block: each task's chosen targets on each fingerprint."""
    prints = fingerprints(extraction, block)
    targets = {name: chosen_targets(task_targets(task)) for name, task in tasks.items()}
    targets = {name: target for name, target in targets.items() if target.names}
    fits = tuple((name, index, column) for name, target in targets.items() for index in range(len(prints))
                 for column in range(len(target.names)))
    return PayoffPlan(block, prints, targets, fits)


def check_device(device: str) -> None:
    """Fail unless XGBoost trains on `device`: a build or machine without CUDA falls back to the CPU with a warning."""
    sample = xgboost.DMatrix(np.array([[0.0], [1.0]], dtype=np.float32), label=np.array([0.0, 1.0], dtype=np.float32))
    booster = xgboost.train({"tree_method": "hist", "device": device}, sample, num_boost_round=1)
    used = json.loads(booster.save_config())["learner"]["generic_param"]["device"]
    if used.split(":")[0] != device.split(":")[0]:
        raise RuntimeError(f"XGBoost was asked for {device} and trained on {used}.")


def split_matrices(train: np.ndarray, held_out: Mapping[str, np.ndarray]) -> dict[str, xgboost.DMatrix]:
    """Quantile matrices of one fingerprint's splits, the held-out ones binned at the training split's cuts."""
    # train: (n_train, w); held_out: (n_split, w) by split
    matrices: dict[str, xgboost.DMatrix] = {"train": xgboost.QuantileDMatrix(train, max_bin=SETTINGS["max_bin"])}
    for split, features in held_out.items():
        matrices[split] = xgboost.QuantileDMatrix(features, ref=matrices["train"], max_bin=SETTINGS["max_bin"])
    return matrices


def fit_target(matrices: Mapping[str, xgboost.DMatrix], labels: Mapping[str, np.ndarray], kind: str, *, device: str,
               rounds: int = ROUNDS) -> dict[str, float | None]:
    """One XGBoost model on one target's training labels, scored on test proteins; a binary target's balanced MCC is
    read at the threshold that maximizes it on validation proteins."""
    # labels: (n_split,) by split
    matrices["train"].set_label(np.asarray(labels["train"], dtype=np.float32))
    booster = xgboost.train({**SETTINGS, "objective": OBJECTIVES[kind], "device": device}, matrices["train"],
                            num_boost_round=rounds)
    test = booster.predict(matrices["test"])  # (n_test,)
    if kind == "continuous":
        return {"spearman": float(column_spearman(test[:, None], np.asarray(labels["test"])[:, None])[0])}
    chosen = binary_scores(labels["validation"], booster.predict(matrices["validation"]), None)["threshold"]
    if chosen is None:
        raise ValueError("A binary target reached E11 without both classes among validation proteins.")
    return binary_scores(labels["test"], test, chosen)


def run_e11(
    plan: PayoffPlan,
    proteins: ConceptProteins,
    *,
    device: str = "cpu",
    rounds: int = ROUNDS,
    pilot: Pilot | None = None,
    log: Callable[[str], None] = print,
) -> pd.DataFrame:
    """Every fit of `plan`, task by task so each fingerprint's matrices are built once a task; under a pilot the loop
    is timed and ends when its window closes."""
    check_device(device)
    rows = []
    built: tuple[tuple[str, int], dict[str, xgboost.DMatrix]] | None = None
    fits = pilot.watch(plan.fits) if pilot is not None else plan.fits
    for position, (task, index, column) in enumerate(fits):
        fingerprint, target = plan.prints[index], plan.targets[task]
        if built is None or built[0] != (task, index):
            split_rows = proteins.rows[task]
            built = ((task, index), split_matrices(fingerprint.take(split_rows["train"]),
                                                   {split: fingerprint.take(split_rows[split]) for split in ("validation", "test")}))
        labels = {split: target.values[split][:, column] for split in SPLITS}  # (n_split,) each
        rows.append({"task": task, "target": target.names[column], "kind": target.kind, "features": fingerprint.features,
                     "basis": fingerprint.basis, **fit_target(built[1], labels, target.kind, device=device, rounds=rounds)})
        if position + 1 == len(plan.fits) or plan.fits[position + 1][0] != task:
            log(f"E11 block {plan.block}: {task} done, {position + 1} of {len(plan.fits)} fits")
    return pd.DataFrame(rows).assign(block=plan.block)


def paired_differences(table: pd.DataFrame, metric: str,
                       comparisons: Mapping[str, tuple[tuple[str, str], tuple[str, str]]] = COMPARISONS) -> pd.DataFrame:
    """Per comparison and target, both fingerprints' `metric` and the first's minus the second's, a target's rotations
    averaged before it is paired: comparison, task, target, first, second, difference, comparisons in their order."""
    # table: task, target, features, basis and one column per metric
    grouped = table.assign(group=table["basis"].where(~table["basis"].str.startswith("rotation"), "rotation"))
    wide = grouped.groupby(["task", "target", "features", "group"])[metric].mean().unstack(["features", "group"])
    frames = []
    for name, (first, second) in comparisons.items():
        if first not in wide.columns or second not in wide.columns:
            continue
        paired = wide[[first, second]].dropna()  # (t, 2)
        frames.append(pd.DataFrame({"comparison": name, "task": paired.index.get_level_values("task"),
                                    "target": paired.index.get_level_values("target"), "first": paired[first].to_numpy(),
                                    "second": paired[second].to_numpy(),
                                    "difference": (paired[first] - paired[second]).to_numpy()}))
    columns = ["comparison", "task", "target", "first", "second", "difference"]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=columns)


def payoff_summary(table: pd.DataFrame, comparisons: Mapping[str, tuple[tuple[str, str], tuple[str, str]]] = COMPARISONS) -> pd.DataFrame:
    """Per metric and comparison, both fingerprints' medians over targets and the median per-target difference with its
    bootstrap interval (`paired_differences`)."""
    # table: task, target, features, basis and one column per metric
    rows = []
    for metric in ("pr_auc", "roc_auc", "balanced_mcc", "spearman"):
        if metric not in table.columns or table[metric].isna().all():
            continue
        for name, paired in paired_differences(table, metric, comparisons).groupby("comparison", sort=False):
            difference = median_interval(paired["difference"].to_numpy(dtype=np.float64))
            rows.append({"metric": metric, "comparison": name, "targets": len(paired),
                         "first_median": float(paired["first"].median()), "second_median": float(paired["second"].median()),
                         "difference": difference.estimate, "low": difference.low, "high": difference.high,
                         "first_wins": float((paired["first"] > paired["second"]).mean())})
    return pd.DataFrame(rows)
