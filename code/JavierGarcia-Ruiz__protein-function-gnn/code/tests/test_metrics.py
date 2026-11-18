"""Tests for Enzyme Commission multi-label metrics."""

import numpy as np
import pytest

from protgnn.data.constants import EC_CLASSES
from protgnn.evaluation.metrics import compute_ec_metrics, find_optimal_thresholds


def test_compute_ec_metrics():
    N, C = 30, len(EC_CLASSES)
    rng = np.random.RandomState(42)
    y_true = (rng.rand(N, C) > 0.85).astype(np.float32)
    y_true[0, :] = 1.0  # Ensure all classes have at least one positive
    y_probs = np.clip(y_true * 0.7 + rng.rand(N, C) * 0.3, 0.0, 1.0)

    m = compute_ec_metrics(y_true, y_probs, thresholds=0.5)
    assert 0.0 <= m["macro_f1"] <= 1.0
    assert 0.0 <= m["micro_f1"] <= 1.0
    assert -1.0 <= m["macro_mcc"] <= 1.0
    assert 0.0 <= m["macro_aupr"] <= 1.0
    assert 0.0 <= m["lrap"] <= 1.0
    assert 0.0 <= m["hamming_loss"] <= 1.0
    assert len(m["per_class_f1"]) == C


def test_find_optimal_thresholds():
    N, C = 25, len(EC_CLASSES)
    rng = np.random.RandomState(42)
    y_true = (rng.rand(N, C) > 0.8).astype(np.float32)
    y_true[0, :] = 1.0
    y_probs = rng.rand(N, C).astype(np.float32)

    ths = find_optimal_thresholds(y_true, y_probs)
    assert len(ths) == C
    assert np.all(ths >= 0.05) and np.all(ths <= 0.95)

