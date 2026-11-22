from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import torch
import xgboost

from collections.abc import Iterable, Iterator
from pathlib import Path

from foundry.controls.metrics import binary_scores
from plm_interpretability.units import payoff
from plm_interpretability.units.concepts import ConceptProteins, ConceptTask
from plm_interpretability.units.rotations import haar_rotation
from plm_interpretability.units.sparse_probes import Targets, task_targets


ROWS = {"train": np.arange(0, 300), "validation": np.arange(300, 380), "test": np.arange(380, 480)}


def test_chosen_targets_need_both_classes_in_validation_and_are_capped() -> None:
    validation = np.zeros((40, 4), dtype=bool)  # (n_validation, t)
    validation[:5, 0] = validation[:4, 1] = validation[:20, 2] = validation[:36, 3] = True
    values = {"train": np.ones((60, 4), dtype=bool), "validation": validation, "test": np.ones((30, 4), dtype=bool)}
    targets = Targets("task", "binary", ("a", "b", "c", "d"), values)
    chosen = payoff.chosen_targets(targets)
    assert chosen.names == ("a", "c") and chosen.values["validation"].shape == (40, 2)
    np.testing.assert_array_equal(chosen.values["validation"][:, 1], validation[:, 2])
    capped = payoff.chosen_targets(targets, limit=1, seed=3)
    assert len(capped.names) == 1 and capped.names[0] in ("a", "c")
    assert payoff.chosen_targets(targets, limit=1, seed=3).names == capped.names
    continuous = Targets("values", "continuous", ("u",), {split: np.zeros((5, 1)) for split in payoff.SPLITS})
    assert payoff.chosen_targets(continuous) is continuous


def test_check_device_refuses_a_silent_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    payoff.check_device("cpu")
    train = xgboost.train
    monkeypatch.setattr(xgboost, "train", lambda params, *args, **kwargs: train({**params, "device": "cpu"}, *args, **kwargs))
    with pytest.raises(RuntimeError, match="trained on cpu"):
        payoff.check_device("cuda")


def _planted(seed: int, n: int = 480, width: int = 6) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    features = rng.normal(size=(n, width)).astype(np.float32)  # (n, w)
    labels = features[:, 1] + 0.3 * rng.normal(size=n) > 0.4  # (n,)
    return features, labels  # (n, w), (n,)


def test_fit_target_carries_the_validation_threshold_to_test() -> None:
    features, labels = _planted(1)
    matrices = payoff.split_matrices(features[ROWS["train"]], {split: features[ROWS[split]] for split in ("validation", "test")})
    split_labels = {split: labels[index] for split, index in ROWS.items()}
    scores = payoff.fit_target(matrices, split_labels, "binary", device="cpu", rounds=10)
    reference = xgboost.train({**payoff.SETTINGS, "objective": "binary:logistic", "device": "cpu"},
                              xgboost.DMatrix(features[ROWS["train"]], label=split_labels["train"].astype(np.float32)), 10)
    threshold = binary_scores(split_labels["validation"], reference.predict(xgboost.DMatrix(features[ROWS["validation"]])), None)
    assert scores["threshold"] == pytest.approx(threshold["threshold"], abs=1e-6)
    assert scores["roc_auc"] > 0.85 and scores["pr_auc"] > 0.7
    values = {split: features[index, 2] * 2.0 for split, index in ROWS.items()}
    assert payoff.fit_target(matrices, values, "continuous", device="cpu", rounds=10)["spearman"] > 0.9


def test_fingerprint_rotates_the_joined_parts() -> None:
    rng = np.random.default_rng(2)
    first, second = rng.normal(size=(10, 3)), rng.normal(size=(10, 2))  # (n, w_i)
    rotation = haar_rotation(5, 0, dtype=torch.float64).numpy()  # (w, w)
    rows = np.array([4, 1, 7])  # (r,)
    taken = payoff.Fingerprint("extremes", "rotation0", (first, second), rotation).take(rows)  # (r, w)
    assert taken.dtype == np.float32
    np.testing.assert_allclose(taken, np.hstack((first, second))[rows] @ rotation, rtol=1e-5)
    assert payoff.Fingerprint("mean", "native", (first,)).width == 3


class _FirstFits:
    """Stands in for a pilot whose window closes after three fits."""

    def watch(self, fits: Iterable[tuple[str, int, int]]) -> Iterator[tuple[str, int, int]]:
        yield from list(fits)[:3]


def test_e11_runs_every_fingerprint_and_summarizes_its_comparisons(tmp_path: Path) -> None:
    rng = np.random.default_rng(3)
    units = rng.laplace(size=(480, 6)) * (rng.random((480, 6)) < 0.5)  # (n, f)
    (tmp_path / "features").mkdir()
    stored = {"z_max": np.maximum(units, 0), "z_min": np.minimum(units, 0), "z_mean": units / 2,
              "sae_max": np.maximum(np.hstack((units, -units)), 0)}
    for seed in payoff.ROTATIONS:
        rotated = units @ haar_rotation(6, seed, dtype=torch.float64).numpy()  # (n, f)
        stored |= {f"rotation{seed}_max": np.maximum(rotated, 0), f"rotation{seed}_min": np.minimum(rotated, 0)}
    for name, array in stored.items():
        np.save(tmp_path / "features" / f"block3_{name}.npy", array.astype(np.float32))
    flags = np.column_stack((units[:, 0] > 0.3, units[:, 4] < -0.3, np.arange(480) < 3)).astype(np.int8)  # (n, 3)
    multilabel = ConceptTask("sites", "protein", "multilabel", ("high", "low", "rare"),
                             {split: pd.DataFrame({"id": index.astype(str), "sequence": ["A"] * len(index), "label": list(flags[index])})
                              for split, index in ROWS.items()})
    values = np.column_stack((units[:, 1], units[:, 2] + units[:, 3]))  # (n, 2)
    regression = ConceptTask("values", "protein", "regression", ("one", "two"),
                             {split: pd.DataFrame({"id": index.astype(str), "sequence": ["A"] * len(index), "label": list(values[index])})
                              for split, index in ROWS.items()})
    tasks = {"sites": multilabel, "values": regression}
    proteins = ConceptProteins([f"P{row}" for row in range(480)], {name: ROWS for name in tasks})
    plan = payoff.payoff_plan(tmp_path, tasks, 3)
    assert task_targets(multilabel).names == ("high", "low") and plan.targets["sites"].names == ("high", "low")
    assert len(plan.prints) == 6 and len(plan.fits) == 6 * 4
    assert [(fingerprint.features, fingerprint.basis, fingerprint.width) for fingerprint in plan.prints] == [
        ("extremes", "native", 12), ("extremes", "rotation0", 12), ("extremes", "rotation1", 12), ("mean", "native", 6),
        ("mean", "rotation0", 6), ("sae", "native", 12)]
    assert plan.work(plan.fits[0], proteins) == 300 * 12
    messages: list[str] = []
    table = payoff.run_e11(plan, proteins, rounds=20, log=messages.append)
    assert len(table) == 24 and set(table["block"]) == {3} and len(messages) == 2
    binary = table[table["kind"] == "binary"]
    assert binary[["pr_auc", "roc_auc", "balanced_mcc", "threshold"]].notna().all().all()
    native = binary[(binary["features"] == "extremes") & (binary["basis"] == "native")]
    assert (native["roc_auc"] > 0.95).all()
    assert table.loc[table["kind"] == "continuous", "spearman"].notna().all()
    summary = payoff.payoff_summary(table)
    assert set(summary["comparison"]) == set(payoff.COMPARISONS)
    assert set(summary["metric"]) == {"pr_auc", "roc_auc", "balanced_mcc", "spearman"}
    assert (summary.loc[summary["metric"] == "pr_auc", "targets"] == 2).all()
    assert len(payoff.run_e11(plan, proteins, rounds=5, pilot=_FirstFits(), log=messages.append)) == 3


def test_payoff_summary_averages_rotations_before_pairing() -> None:
    rows = []
    for target, base in enumerate((0.5, 0.6, 0.7)):
        for features, basis, score in (("extremes", "native", base + 0.2), ("extremes", "rotation0", base),
                                       ("extremes", "rotation1", base + 0.1), ("sae", "native", base + 0.3)):
            rows.append({"task": "t", "target": f"c{target}", "features": features, "basis": basis, "pr_auc": score})
    summary = payoff.payoff_summary(pd.DataFrame(rows)).set_index("comparison")
    assert list(summary.index) == ["extremes: native - rotated", "native extremes - SAE"]
    assert summary.loc["extremes: native - rotated", "difference"] == pytest.approx(0.15)
    assert summary.loc["extremes: native - rotated", "first_wins"] == 1.0
    assert summary.loc["native extremes - SAE", "difference"] == pytest.approx(-0.1)
    assert summary.loc["native extremes - SAE", "first_median"] == pytest.approx(0.8)
