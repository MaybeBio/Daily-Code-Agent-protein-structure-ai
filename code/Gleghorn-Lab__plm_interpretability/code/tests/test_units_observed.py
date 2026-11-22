from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from plm_interpretability.units import observed


def _labels(seed: int, n: int = 90, n_terms: int = 7, n_units: int = 3) -> tuple[pd.DataFrame, np.ndarray]:
    """Proteins with positives, masked carriers and units; terms 0 to 5 in units 0 to 2, term 6 in none."""
    rng = np.random.default_rng(seed)
    unit = np.array([0, 0, 1, 1, 2, 2, -1])  # (t,)
    rows = []
    for _ in range(n):
        units = sorted(int(value) for value in np.flatnonzero(rng.random(n_units) < 0.7))
        annotations = [term for term in range(6) if unit[term] in units and rng.random() < 0.3]
        masked = [term for term in range(6) if term not in annotations and rng.random() < 0.15]  # some outside their unit
        rows.append({"annotations": annotations, "masked": masked, "units": units})
    return pd.DataFrame(rows), unit  # unit (t,)


def _scores(seed: int, n: int, c: int = 9) -> np.ndarray:
    rng = np.random.default_rng(seed)
    values = rng.integers(0, 5, size=(n, c)).astype(np.float32)  # many ties
    values[:, 0] = 0.0  # a pole that never fires: every pair a tie
    return values  # (n, c)


def _pairwise(scores: np.ndarray, frame: pd.DataFrame, unit: np.ndarray, term: int) -> np.ndarray:
    """Each pole's AUROC for one term, counting every (positive, negative) pair, ties a half."""
    # scores: (n, c); unit: (t,)
    positive = np.array([term in row for row in frame["annotations"]])
    negative = np.array([unit[term] in units and term not in annotations and term not in masked
                         for annotations, masked, units in zip(frame["annotations"], frame["masked"], frame["units"], strict=True)])
    first, second = scores[positive][:, None, :], scores[negative][None, :, :]  # (a, 1, c), (1, b, c)
    wins = (first > second).sum(axis=(0, 1)) + 0.5 * (first == second).sum(axis=(0, 1))  # (c,)
    return wins / (positive.sum() * negative.sum())  # (c,)


def test_observed_auroc_counts_every_pair() -> None:
    frame, unit = _labels(0)
    labels = observed.TermLabels.from_frame(frame, 7, unit)
    scores = _scores(1, len(frame))
    auroc = observed.observed_auroc(scores, labels, min_support=3, block=4)  # (c, t)
    n_positive, n_negative = labels.counts()
    for term in range(6):
        assert n_positive[term] >= 3 and n_negative[term] >= 3  # every scored term is exercised
        np.testing.assert_allclose(auroc[:, term], _pairwise(scores, frame, unit, term), rtol=0, atol=1e-12)
    assert np.isnan(auroc[:, 6]).all()  # no unit scores it
    np.testing.assert_allclose(auroc[:, :6][0], 0.5)  # the silent pole ties every pair


def test_observed_auroc_without_masks_is_the_whole_ranking() -> None:
    frame, unit = _labels(2)
    frame = frame.assign(masked=[[] for _ in range(len(frame))], units=[[0, 1, 2] for _ in range(len(frame))])
    labels = observed.TermLabels.from_frame(frame, 7, unit)
    scores = _scores(3, len(frame))
    auroc = observed.observed_auroc(scores, labels, min_support=3)
    from scipy import stats
    for term in range(6):
        positive = np.array([term in row for row in frame["annotations"]])
        ranks = stats.rankdata(scores, axis=0)  # (n, c)
        expected = (ranks[positive].sum(axis=0) - positive.sum() * (positive.sum() + 1) / 2) / (positive.sum() * (~positive).sum())
        np.testing.assert_allclose(auroc[:, term], expected, rtol=0, atol=1e-12)


def test_held_out_auroc_takes_the_same_rule() -> None:
    frame, unit = _labels(4)
    labels = observed.TermLabels.from_frame(frame, 7, unit)
    scores = _scores(5, len(frame))
    selected = np.array([0, 1, 2, 3, 4, 5, 6, -1, 2])  # (c,)
    held_out = observed.held_out_auroc(scores, labels, selected, min_support=3)
    for pole, term in enumerate(selected):
        if term < 0 or term == 6:
            assert np.isnan(held_out[pole])
            continue
        np.testing.assert_allclose(held_out[pole], _pairwise(scores, frame, unit, int(term))[pole], rtol=0, atol=1e-12)


def test_held_out_auroc_matches_sklearn_with_ties_and_needs_support() -> None:
    from sklearn.metrics import roc_auc_score

    rng = np.random.default_rng(0)
    scores = np.round(rng.random((200, 3)), 1)  # (n, p), many ties
    held = rng.random((200, 2)) < 0.3  # (n, t)
    frame = pd.DataFrame({"annotations": [list(np.flatnonzero(row)) for row in held], "masked": [[] for _ in range(200)],
                          "units": [[0] for _ in range(200)]})
    labels = observed.TermLabels.from_frame(frame, 2, np.array([0, 0]))
    aurocs = observed.held_out_auroc(scores, labels, np.array([0, 1, -1]))
    assert aurocs[0] == pytest.approx(roc_auc_score(held[:, 0], scores[:, 0]))
    assert aurocs[1] == pytest.approx(roc_auc_score(held[:, 1], scores[:, 1]))
    assert np.isnan(aurocs[2])
    sparse = frame.assign(annotations=[[0] if row < 3 else [] for row in range(200)])
    labels = observed.TermLabels.from_frame(sparse, 2, np.array([0, 0]))
    assert np.isnan(observed.held_out_auroc(scores, labels, np.array([0, 0, 0]))[0])  # three positives: no support


def test_a_positive_outside_its_unit_raises() -> None:
    frame = pd.DataFrame({"annotations": [[0]], "masked": [[]], "units": [[1]]})
    with pytest.raises(ValueError):
        observed.TermLabels.from_frame(frame, 2, np.array([0, 1]))
