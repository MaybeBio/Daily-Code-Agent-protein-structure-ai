"""The missing-annotation correction: inheritance from matched proteins, average precision and a basis rescored (CPU)."""

import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp

from sklearn.metrics import average_precision_score

from plm_interpretability.units import missing
from plm_interpretability.units.observed import TermLabels, held_out_auroc


UNIT = np.array([0, 0, 0, 1, 1])  # terms 0 to 2 in a unit every protein observes, terms 3 and 4 in one some observe


def _labels(rows: dict[int, list[int]], n_proteins: int, observed_second: list[int],
            masked: dict[int, list[int]] | None = None) -> TermLabels:
    annotations = [[term for term, proteins in rows.items() if protein in proteins] for protein in range(n_proteins)]
    hidden = [[term for term, proteins in (masked or {}).items() if protein in proteins] for protein in range(n_proteins)]
    units = [[0, 1] if protein in observed_second else [0] for protein in range(n_proteins)]
    frame = pd.DataFrame({"annotations": annotations, "masked": hidden, "units": units})
    return TermLabels.from_frame(frame, len(UNIT), UNIT)


def _matrix(rows: dict[int, list[int]], n_proteins: int) -> sp.csr_matrix:
    pairs = [(protein, term) for term, proteins in rows.items() for protein in proteins]
    proteins, terms = zip(*pairs, strict=True)
    return sp.csr_matrix((np.ones(len(pairs), dtype=bool), (proteins, terms)), shape=(n_proteins, len(UNIT)))


@pytest.fixture
def basis() -> dict[str, object]:
    """Forty test proteins: inheritance makes term 1 testable, widens term 2, and brings protein 30 into term 3's unit
    through term 4; term 0 is unchanged."""
    generator = np.random.default_rng(7)
    n_proteins = 40
    own = _labels({0: list(range(12)), 1: list(range(12, 17)), 2: list(range(17, 32)), 3: list(range(12))}, n_proteins,
                  list(range(25)))
    inherited = _matrix({1: list(range(32, 38)), 2: [0, 1, 2], 0: [3], 4: [30]}, n_proteins)  # protein 3 already holds term 0
    maxima = generator.integers(0, 6, size=(n_proteins, 6)).astype(np.float32)  # (n, p), tied values on purpose
    maxima[np.r_[12:17, 32:38], 1] += 10  # pole 1 fires on its term's carriers, annotated or inherited
    best = np.array([0, 1, 2, 2, -1, 0])  # (p,)
    recorded = held_out_auroc(maxima.astype(np.float64), own, best)  # (p,) as global_scores ranks
    table = pd.DataFrame({"pole": np.arange(6), "best_term": best, "held_out_auroc": recorded})
    return {"own": own, "inherited": inherited, "maxima": maxima, "best": best, "table": table}


def test_inheritable_drops_entry_aspects_and_unscored_terms() -> None:
    terms = pd.DataFrame({"token": [2, 0, 1, 3], "aspect": ["keyword", "go_mf", "go_bp", "taxonomy"], "unit": [4, 0, 1, -1]})
    np.testing.assert_array_equal(missing.inheritable(terms), [True, True, False, False])
    with pytest.raises(ValueError, match="contiguous"):
        missing.inheritable(terms.assign(token=[0, 1, 2, 5]))


def test_inherited_positives_skip_the_query_itself_and_uninherited_terms() -> None:
    matches = {"A": ("A", "B", "C"), "D": ()}
    annotations = {"A": [0], "B": [1, 2], "C": [2, 3]}
    inherit = np.array([True, True, True, False])
    inherited = missing.inherited_positives(["A", "D"], matches, annotations, inherit).toarray()
    np.testing.assert_array_equal(inherited, [[0, 1, 1, 0], [0, 0, 0, 0]])
    with pytest.raises(KeyError):
        missing.inherited_positives(["E"], matches, annotations, inherit)


def test_with_inherited_adds_positives_units_and_unmasks(basis: dict[str, object]) -> None:
    own = basis["own"]
    propagated = missing.with_inherited(own, basis["inherited"])
    expected = own.positives.toarray() | basis["inherited"].toarray()
    np.testing.assert_array_equal(propagated.positives.toarray(), expected)
    assert not own.observed[30, 1] and propagated.observed[30, 1]  # term 4's unit, observed once inherited
    np.testing.assert_array_equal(missing.changed_terms(own, propagated), [False, True, True, True, True])
    masked = _labels({0: [0]}, 4, [], masked={1: [2, 3]})
    after = missing.with_inherited(masked, _matrix({1: [2]}, 4))
    assert after.masked.toarray()[:, 1].tolist() == [False, False, False, True]  # protein 2 now holds term 1


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_average_precision_matches_scikit_learn_with_ties(seed: int) -> None:
    generator = np.random.default_rng(seed)
    scores = generator.integers(0, 5, size=(8, 60)).astype(np.float32)  # (c, n)
    scores[0] = 2.0  # one row tied throughout scores its prevalence
    labels = generator.random(60) < 0.3  # (n,)
    expected = [average_precision_score(labels, row) for row in scores]
    np.testing.assert_allclose(missing.average_precision(scores, labels), expected, rtol=1e-12)
    assert missing.average_precision(scores[:1], labels)[0] == pytest.approx(labels.mean())


def test_held_out_average_precision_follows_the_auroc_rule(basis: dict[str, object]) -> None:
    own = basis["own"]
    precision = missing.held_out_average_precision(basis["maxima"], own, basis["best"])
    auroc = held_out_auroc(basis["maxima"], own, basis["best"])
    np.testing.assert_array_equal(np.isfinite(precision), np.isfinite(auroc))
    labels = own.positives.toarray()[:, 2]
    assert precision[2] == pytest.approx(average_precision_score(labels, basis["maxima"][:, 2]))
    third = missing.held_out_average_precision(basis["maxima"], own, np.array([3, 3, 3, 3, 3, 3]))  # within its unit only
    scored = np.arange(25)
    assert third[0] == pytest.approx(average_precision_score(own.positives.toarray()[scored, 3], basis["maxima"][scored, 0]))


def test_basis_scores_rescore_only_changed_terms(basis: dict[str, object]) -> None:
    propagated = missing.with_inherited(basis["own"], basis["inherited"])
    scored = missing.basis_scores(basis["maxima"], basis["own"], propagated, basis["table"])
    np.testing.assert_array_equal(scored["rescored"], [False, True, True, True, False, False])
    after = held_out_auroc(basis["maxima"], propagated, np.where(scored["rescored"], basis["best"], -1))
    np.testing.assert_allclose(scored.loc[scored["rescored"], "auroc_after"], after[scored["rescored"].to_numpy()])
    unchanged = ~scored["rescored"]
    np.testing.assert_array_equal(scored.loc[unchanged, "auroc_after"], scored.loc[unchanged, "auroc_before"])
    np.testing.assert_array_equal(scored.loc[unchanged, "precision_after"], scored.loc[unchanged, "precision_before"])
    assert np.isnan(scored.loc[1, "auroc_before"]) and scored.loc[1, "auroc_after"] == 1.0  # testable only after
    assert scored.loc[2, "prevalence_before"] == pytest.approx(15 / 40)
    assert scored.loc[2, "prevalence_after"] == pytest.approx(18 / 40)
    assert np.isnan(scored.loc[4, ["auroc_after", "precision_after", "prevalence_after"]].to_numpy(dtype=float)).all()


def test_basis_scores_refuse_rows_that_are_not_the_pass(basis: dict[str, object]) -> None:
    propagated = missing.with_inherited(basis["own"], basis["inherited"])
    recorded = basis["table"]["held_out_auroc"].to_numpy()  # (p,)
    shifted = basis["table"].assign(held_out_auroc=recorded + np.array([0, 0, 0.01, 0, 0, 0]))
    with pytest.raises(ValueError, match="not the pass"):
        missing.basis_scores(basis["maxima"], basis["own"], propagated, shifted)
    with pytest.raises(ValueError, match="one row per pole"):
        missing.basis_scores(basis["maxima"][:, :5], basis["own"], propagated, basis["table"])


def test_missing_summary_counts_and_medians(basis: dict[str, object]) -> None:
    propagated = missing.with_inherited(basis["own"], basis["inherited"])
    scored = missing.basis_scores(basis["maxima"], basis["own"], propagated, basis["table"])
    summary = missing.missing_summary({"block0/native": scored})["block0/native"]
    both = scored[np.isfinite(scored["auroc_before"]) & np.isfinite(scored["auroc_after"])]
    counts = (summary["poles"], summary["rescored"], summary["scored_both"], summary["scored_after_only"])
    assert counts == (6, 3, len(both), 1)
    assert summary["median_auroc_after"] == pytest.approx(float(np.median(both["auroc_after"])))
    gain = both["precision_after"] - both["precision_before"]
    assert summary["median_precision_gain"] == pytest.approx(float(np.median(gain)))
    assert summary["share_raised"] == pytest.approx(float(np.mean(gain > 0)))
