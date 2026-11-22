from __future__ import annotations

import numpy as np
import pytest
import torch

from plm_interpretability.units import missing, model_probes
from plm_interpretability.units.sparse_probes import Targets, column_auroc


def _binary_task(seed: int = 0, proteins: int = 400, width: int = 12, targets: int = 3) -> tuple[np.ndarray, np.ndarray]:
    generator = np.random.default_rng(seed)
    features = generator.normal(size=(proteins, width)).astype(np.float32)  # (p, d)
    labels = features[:, :targets] + 0.3 * generator.normal(size=(proteins, targets)) > 0.5  # (p, t)
    return features, labels  # (p, d), (p, t)


def test_depth_blocks_are_the_quarters_of_a_stack() -> None:
    assert model_probes.depth_blocks(36) == (8, 17, 26, 35)
    assert model_probes.depth_blocks(30) == (7, 14, 22, 29)


def test_average_precision_agrees_with_the_studys_own_and_with_a_redraw() -> None:
    generator = np.random.default_rng(1)
    scores = generator.normal(size=(60, 4))
    labels = generator.random((60, 4)) < 0.3
    ours = model_probes.average_precisions(scores, labels)
    theirs = np.array([missing.average_precision(scores[:, target][None, :], labels[:, target])[0] for target in range(4)])
    np.testing.assert_allclose(ours[:, 0], theirs, rtol=1e-12)
    picks = generator.integers(0, 60, size=(5, 60))
    weights = np.stack([np.bincount(pick, minlength=60) for pick in picks], axis=1).astype(np.float64)
    weighted = model_probes.average_precisions(scores, labels, weights)
    for draw, pick in enumerate(picks):
        redrawn = np.array([missing.average_precision(scores[pick, target][None, :], labels[pick, target])[0] for target in range(4)])
        np.testing.assert_allclose(weighted[:, draw], redrawn, rtol=1e-9)
    assert np.isnan(model_probes.average_precisions(scores[:, :1], np.zeros((60, 1), dtype=bool))).all()


def test_a_probe_learns_binary_and_continuous_targets() -> None:
    features, labels = _binary_task()
    given, truth = torch.from_numpy(features), torch.from_numpy(labels.astype(np.float32))
    for hidden in (None, 16):
        predict = model_probes.fit_probe(given[:300], truth[:300], given[300:350], truth[300:350], kind="binary", hidden=hidden)
        assert column_auroc(predict(given[350:]).numpy(), labels[350:]).min() > 0.9
    values = torch.from_numpy((3.0 * features[:, :2] + 7.0).astype(np.float32))
    predict = model_probes.fit_probe(given[:300], values[:300], given[300:350], values[300:350], kind="continuous", hidden=None)
    # In the targets' own units, so the probe's standardizing is undone; weight decay leaves a small shrinkage.
    residual = predict(given[350:]).numpy() - values[350:].numpy()
    assert float((residual ** 2).mean()) < 0.02 * float(values[350:].numpy().var())


def test_a_task_is_read_at_the_depth_that_holds_it() -> None:
    features, labels = _binary_task()
    noise = np.random.default_rng(5).normal(size=features.shape).astype(np.float32)
    rows = {"train": np.arange(0, 300), "validation": np.arange(300, 350), "test": np.arange(350, 400)}
    targets = Targets("toy", "binary", ("a", "b", "c"), {split: labels[index] for split, index in rows.items()})
    choice, tried = model_probes.read_task({0.25: noise, 1.0: features}, rows, targets, torch.device("cpu"), steps=300)
    assert choice.share == 1.0 and len(tried) == 2 * len(model_probes.PROBES)
    assert choice.test.shape == (50, 3) and choice.validation.shape == (50, 3)
    metrics = model_probes.held_out_metrics("binary", choice, targets.values["validation"], targets.values["test"])
    assert metrics["pr_auc"] > 0.8 and metrics["roc_auc"] > 0.9 and 0.5 < metrics["balanced_mcc"] <= 1.0
    assert metrics["targets_with_mcc"] == 3.0

    values = {split: (2.0 * features[index, :2] - 1.0).astype(np.float64) for split, index in rows.items()}
    continuous = Targets("toy", "continuous", ("x", "y"), values)
    choice, _ = model_probes.read_task({0.25: noise, 1.0: features}, rows, continuous, torch.device("cpu"), steps=300)
    metrics = model_probes.held_out_metrics("continuous", choice, values["validation"], values["test"])
    assert choice.share == 1.0 and metrics["spearman"] > 0.9 and metrics["r_squared"] > 0.8


def test_paired_differences_separate_a_better_model_from_an_equal_one() -> None:
    generator = np.random.default_rng(2)
    labels = generator.random((200, 3)) < 0.4
    values = generator.normal(size=(150, 2))
    good = {"binary_task": labels + 0.5 * generator.normal(size=labels.shape), "value_task": values + 0.3 * generator.normal(size=values.shape)}
    poor = {"binary_task": generator.normal(size=labels.shape), "value_task": generator.normal(size=values.shape)}
    kinds, truth = {"binary_task": "binary", "value_task": "continuous"}, {"binary_task": labels, "value_task": values}
    better = model_probes.paired_differences(kinds, good, poor, truth, redraws=200)
    assert better["low"] > 0 and better["low"] < better["mean"] < better["high"] and set(better["by_task"]) == set(kinds)
    same = model_probes.paired_differences(kinds, good, good, truth, redraws=50)
    assert same["mean"] == 0.0 and same["low"] == 0.0 and same["high"] == 0.0
    with pytest.raises(KeyError):
        model_probes.paired_differences(kinds, good, {"binary_task": poor["binary_task"]}, truth, redraws=10)
