from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import torch

from pathlib import Path
from scipy import stats
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import roc_auc_score

from plm_interpretability.units import sparse_probes
from plm_interpretability.units.concepts import ConceptProteins, ConceptTask, ExtractionPlan
from plm_interpretability.units.rotations import haar_rotation


def _binary_data(seed: int, n: int = 600, w: int = 5) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    features = rng.normal(size=(n, w))  # (n, w)
    labels = (features @ rng.normal(size=w) + rng.normal(size=n)) > 0.3  # (n,)
    return features, labels  # (n, w), (n,)


def test_logistic_solvers_match_scikit_learn() -> None:
    reference_weights = []
    batched_features, batched_labels = [], []
    for seed in range(3):
        features, labels = _binary_data(seed)
        model = LogisticRegression(C=sparse_probes.PENALTY, tol=1e-12, max_iter=10_000).fit(features, labels)
        reference_weights.append(np.concatenate((model.coef_[0], model.intercept_)))
        batched_features.append(features)
        batched_labels.append(labels)
    weights = sparse_probes.fit_logistic(torch.from_numpy(np.stack(batched_features)), torch.from_numpy(np.stack(batched_labels)))
    np.testing.assert_allclose(weights.numpy(), np.stack(reference_weights), atol=1e-6)
    features, labels = _binary_data(0)
    second = (features[:, :1] + np.random.default_rng(9).normal(size=(600, 1))) > 0  # (n, 1)
    dense = sparse_probes.fit_dense_logistic(torch.from_numpy(features), torch.from_numpy(np.column_stack((labels, second))))
    np.testing.assert_allclose(dense[:, 0].numpy(), reference_weights[0], atol=1e-5)
    other = LogisticRegression(C=sparse_probes.PENALTY, tol=1e-12, max_iter=10_000).fit(features, second[:, 0])
    np.testing.assert_allclose(dense[:, 1].numpy(), np.concatenate((other.coef_[0], other.intercept_)), atol=1e-5)


def test_logistic_solver_reaches_the_optimum_on_saturating_features() -> None:
    # Standardized mean poles of a nearly silent block: about -0.05 for most proteins and above 20 for a few.
    rng = np.random.default_rng(11)
    raw = np.zeros((2000, 3))  # (n, k)
    hits = rng.choice(2000, size=(3, 4), replace=False)  # (k, 4)
    for column in range(3):
        raw[hits[column], column] = rng.uniform(1, 5, size=4)
    features = (raw - raw.mean(axis=0)) / raw.std(axis=0)  # (n, k)
    labels = rng.random(2000) < 0.02  # (n,)
    labels[hits[0]] = True
    model = LogisticRegression(C=sparse_probes.PENALTY, tol=1e-12, max_iter=10_000).fit(features, labels)
    weights = sparse_probes.fit_logistic(torch.from_numpy(features[None]), torch.from_numpy(labels[None]))  # (1, k + 1)
    np.testing.assert_allclose(weights[0].numpy(), np.concatenate((model.coef_[0], model.intercept_)), atol=1e-5)
    design = torch.cat((torch.from_numpy(features[None]), torch.ones(1, 2000, 1, dtype=torch.float64)), dim=2)
    ridge = torch.tensor([sparse_probes.PENALTY] * 3 + [0.0], dtype=torch.float64)
    target = torch.from_numpy(labels[None]).double()
    zero = sparse_probes.penalized_logistic_loss(design, target, torch.zeros(1, 4, dtype=torch.float64), ridge)
    assert float(sparse_probes.penalized_logistic_loss(design, target, weights, ridge)) < float(zero)


def test_ridge_solvers_match_scikit_learn() -> None:
    rng = np.random.default_rng(4)
    features = rng.normal(size=(2, 300, 4))  # (t, n, k)
    values = features @ np.array([1.0, -2.0, 0.0, 0.5]) + rng.normal(size=(2, 300)) + 3.0  # (t, n)
    weights = sparse_probes.fit_ridge(torch.from_numpy(features), torch.from_numpy(values))  # (t, k + 1)
    for target in range(2):
        model = Ridge(alpha=sparse_probes.PENALTY).fit(features[target], values[target])
        np.testing.assert_allclose(weights[target].numpy(), np.concatenate((model.coef_, [model.intercept_])), atol=1e-10)
    dense = sparse_probes.fit_dense_ridge(torch.from_numpy(features[0]), torch.from_numpy(values.T))  # (k + 1, t)
    model = Ridge(alpha=sparse_probes.PENALTY).fit(features[0], values[1])
    np.testing.assert_allclose(dense[:, 1].numpy(), np.concatenate((model.coef_, [model.intercept_])), atol=1e-10)


def test_column_metrics_match_their_references() -> None:
    rng = np.random.default_rng(5)
    scores = np.round(rng.normal(size=(200, 3)), 1)  # (n, t), with ties
    labels = rng.random((200, 3)) < 0.3  # (n, t)
    np.testing.assert_allclose(sparse_probes.column_auroc(scores, labels),
                               [roc_auc_score(labels[:, column], scores[:, column]) for column in range(3)], atol=1e-12)
    truth = scores + rng.normal(size=(200, 3))  # (n, t)
    np.testing.assert_allclose(sparse_probes.column_spearman(scores, truth),
                               [stats.spearmanr(scores[:, column], truth[:, column]).statistic for column in range(3)], atol=1e-10)


def _task(kind: str, labels: dict[str, list[object]], names: tuple[str, ...]) -> ConceptTask:
    frames = {split: pd.DataFrame({"id": [f"{split}{row}" for row in range(len(values))], "sequence": ["A"] * len(values),
                                   "label": values}) for split, values in labels.items()}
    return ConceptTask("task", "protein", kind, names, frames)


def test_task_targets_split_and_filter_labels() -> None:
    multiclass = _task("multiclass", {"train": [0] * 30 + [1] * 30 + [2] * 5, "validation": [0, 1], "test": [0] * 6 + [1] * 6 + [2] * 6},
                       ("a", "b", "c"))
    targets = sparse_probes.task_targets(multiclass)
    assert targets.kind == "binary" and targets.names == ("a", "b")
    assert targets.values["test"].shape == (18, 2) and targets.values["test"][:6, 0].all()
    multilabel = _task("multilabel", {split: [np.array([1, 0], dtype=np.int8)] * 25 + [np.array([0, 0], dtype=np.int8)] * 25
                                      for split in ("train", "validation", "test")}, ("x", "y"))
    assert sparse_probes.task_targets(multilabel).names == ("x",)
    regression = _task("regression", {split: [np.array([1.0, 2.0])] * 3 for split in ("train", "validation", "test")}, ("u", "v"))
    continuous = sparse_probes.task_targets(regression)
    assert continuous.kind == "continuous" and continuous.values["train"].shape == (3, 2)


def test_sparse_probes_find_a_planted_unit_and_rotations_lose_it() -> None:
    rng = np.random.default_rng(6)
    width, n = 24, 1500
    # Sparse, heavy-tailed units; each of units 0 to 7 alone carries one concept.
    units = rng.laplace(size=(n, width)) * (rng.random((n, width)) < 0.3)  # (n, w)
    labels = (units[:, :8] + 0.05 * rng.normal(size=(n, 8))) > 0.5  # (n, t)
    split = np.array(["train"] * 1000 + ["test"] * 500)  # (n,)
    targets = sparse_probes.Targets("planted", "binary", tuple(f"concept{unit}" for unit in range(8)),
                                    {name: labels[split == name] for name in ("train", "test")})
    tables = []
    for basis, rotation in [("native", np.eye(width))] + [(f"rotation{seed}", haar_rotation(width, seed, dtype=torch.float64).numpy())
                                                           for seed in range(10)]:
        features = units @ rotation  # (n, w)
        table = sparse_probes.probe_scores({name: features[split == name] for name in ("train", "test")}, targets,
                                           dense=basis == "native")
        tables.append(table.assign(basis=basis))
    combined = pd.concat(tables, ignore_index=True)
    native = combined[combined["basis"] == "native"].groupby("k")["score"].median()
    assert native[1] > 0.95 and native[0] > 0.95 and set(native.index) == {0, *sparse_probes.KS}
    summary = sparse_probes.rotation_summary(combined).set_index("k")
    assert 0 not in summary.index
    assert bool(summary.loc[1, "privileged"]) and summary.loc[1, "native"] > summary.loc[1, "best_rotation"]
    with pytest.raises(ValueError, match="unknown type"):
        sparse_probes.task_targets(_task("ranking", {split: [0] for split in ("train", "validation", "test")}, ("a",)))


def test_e6_reads_every_feature_set_of_an_extraction(tmp_path: Path) -> None:
    rng = np.random.default_rng(7)
    units = rng.laplace(size=(300, 12)) * (rng.random((300, 12)) < 0.4)  # (n, w)
    (tmp_path / "features").mkdir()
    stored = {"z_mean": units, "z_max": np.maximum(units, 0), "z_min": np.minimum(units, 0), "gate_mean": units[:, ::-1],
              "poles_mean": np.hstack((np.maximum(units, 0), np.maximum(-units, 0)))}
    for seed in (0, 1):
        rotated = units @ haar_rotation(12, seed, dtype=torch.float64).numpy()  # (n, w)
        stored |= {f"rotation{seed}_max": np.maximum(rotated, 0), f"rotation{seed}_min": np.minimum(rotated, 0)}
    for name, array in stored.items():
        np.save(tmp_path / "features" / f"block3_{name}.npy", array.astype(np.float32))
    rows = {"train": np.arange(0, 200), "validation": np.arange(200, 220), "test": np.arange(220, 300)}
    labels = {split: [np.array([unit > 0.3, unit < -0.3], dtype=np.int8) for unit in units[index, 2]]
              for split, index in rows.items()}
    task = ConceptTask("signs", "protein", "multilabel", ("high", "low"),
                       {split: pd.DataFrame({"id": index.astype(str), "sequence": ["A"] * len(index), "label": labels[split]})
                        for split, index in rows.items()})
    proteins = ConceptProteins([f"P{row}" for row in range(300)], {"signs": rows})
    plan = ExtractionPlan(depths=(3,), rotation_block=3, rotation_seeds=(0, 1))
    table = sparse_probes.run_e6(tmp_path, proteins, {"signs": task}, plan, seeds=(0, 1), log=lambda message: None)
    combos = set(zip(table["features"], table["basis"], strict=True))
    assert combos == {("mean", "native"), ("mean", "rotation0"), ("mean", "rotation1"), ("poles", "native"), ("gate", "native"),
                      ("extremes", "native"), ("extremes", "rotation0"), ("extremes", "rotation1")}
    assert set(table.loc[table["k"] == 0, "features"]) == {"mean"} and set(table.loc[table["k"] == 0, "basis"]) == {"native"}
    assert len(table) == 2 * (len(sparse_probes.KS) * len(combos) + 1)
    native = table[(table["basis"] == "native") & (table["k"] == 1) & table["features"].isin(["mean", "poles", "extremes"])]
    assert (native["score"] > 0.95).all()
    summary = sparse_probes.rotation_summary(table)
    assert set(summary["features"]) == {"mean", "extremes"} and len(summary) == 2 * len(sparse_probes.KS)
