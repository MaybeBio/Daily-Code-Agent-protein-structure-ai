from __future__ import annotations

import numpy as np
import pandas as pd
import scipy.sparse as sp

from plm_interpretability.units import scores, specificity
from plm_interpretability.units.observed import TermLabels


def _data(seed: int = 0, n: int = 400, poles: int = 12, terms: int = 8) -> tuple[np.ndarray, TermLabels, np.ndarray]:
    """Terms 0 to 6 in one unit every protein observes, term 7 with three positives (untestable at support 10)."""
    rng = np.random.default_rng(seed)
    membership = rng.random((n, terms)) < np.linspace(0.05, 0.5, terms)  # (n, t)
    membership[:, -1] = False
    membership[:3, -1] = True
    maxima = rng.exponential(size=(n, poles)) * (rng.random((n, poles)) < 0.6)  # (n, p), ties at zero
    maxima[:, 0] = membership[:, 2] * 3 + rng.random(n)  # pole 0 tracks term 2
    maxima[:, 1] = np.round(maxima[:, 1], 1)  # heavy ties
    split = np.where(rng.random(n) < 0.7, "train", "test")
    frame = pd.DataFrame({"annotations": [np.flatnonzero(row) for row in membership], "masked": [[] for _ in range(n)],
                          "units": [[0] for _ in range(n)]})
    return maxima, TermLabels.from_frame(frame, terms, np.zeros(terms, dtype=np.int64)), split  # (n, p), labels, (n,)


def test_global_scores_find_the_planted_term() -> None:
    maxima, labels, split = _data(seed=1)
    relations = specificity.TermRelations(sp.csr_matrix((8, 8), dtype=bool), labels.positives[split == "train"])
    table = scores.global_scores(maxima, split, labels, relations, chunk=5)
    assert len(table) == maxima.shape[1] and table["pole"].tolist() == list(range(maxima.shape[1]))
    planted = table.iloc[0]
    assert planted["best_term"] == 2 and planted["best_auroc"] > 0.95 and planted["held_out_auroc"] > 0.95
    assert planted["margin"] > 0.3
    assert np.nanmedian(table["margin"].iloc[2:]) < 0.15
    assert (table["best_term"] != 7).all()  # never testable


def test_local_scores_flag_one_dominant_term() -> None:
    n_informative = np.array([80, 80, 80, 20])  # the fourth term lacks the dominance support
    sums = {
        "sum_difference": np.array([[60.0, 4.0, 0.0, 19.0], [40.0, 38.0, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0]]),  # (p, t)
        "sum_inside": np.array([[70.0, 8.0, 1.0, 19.0], [45.0, 44.0, 1.0, 1.0], [2.0, 1.0, 1.0, 1.0]]),
        "sum_outside": np.array([[10.0, 4.0, 1.0, 1.0], [5.0, 6.0, 1.0, 1.0], [1.0, 1.0, 1.0, 1.0]]),
        "n_informative": n_informative,
    }
    tokens = np.array([11, 22, 33, 44])
    membership = sp.csr_matrix(np.eye(4))  # four unrelated terms
    relations = specificity.TermRelations(sp.csr_matrix((4, 4), dtype=bool), membership)
    table = scores.local_scores(sums, tokens, relations)
    assert table["best_local_term"].tolist() == [11, 11, 11]
    assert table["dominant"].tolist() == [True, False, False]  # pole 1 has a near rival; pole 2 is too weak
    np.testing.assert_allclose(table["best_contrast"], [0.75, 0.5, 0.0125])


def test_selected_labels_pick_the_planted_pair() -> None:
    rng = np.random.default_rng(3)
    local_sums = {
        "sum_difference": rng.normal(0, 1, (12, 3)), "sum_squared_difference": np.full((12, 3), 400.0),
        "sum_inside": np.ones((12, 3)), "sum_outside": np.ones((12, 3)),
        "inside_hits": np.ones((12, 3)), "outside_hits": np.ones((12, 3)), "n_active": np.full((12, 3), 50.0),
        "n_informative": np.array([60, 60, 60]), "inside_exposure": np.full(3, 600), "outside_exposure": np.full(3, 900),
    }
    local_sums["sum_difference"][4, 1] = 40.0  # pole 4 occupies term 1's spans strongly
    local_sums["sum_squared_difference"][4, 1] = 30.0
    local_sums["sum_inside"][4, 1], local_sums["sum_outside"][4, 1] = 50.0, 5.0
    pairs = scores.selected_labels(local_sums, np.array([7, 8, 9]), chunk=5)
    assert pairs[["pole", "term"]].values.tolist() == [[4, 8]]
