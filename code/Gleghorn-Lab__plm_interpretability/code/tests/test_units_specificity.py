from __future__ import annotations

import numpy as np
import pytest
import scipy.sparse as sp

from plm_interpretability.units import bootstrap, specificity


def _relations(membership: np.ndarray, parent_of: dict[int, int] | None = None) -> specificity.TermRelations:
    # membership: (n, t)
    n_terms = membership.shape[1]
    ancestors = sp.lil_matrix((n_terms, n_terms), dtype=bool)
    for child, parent in (parent_of or {}).items():
        ancestors[child, parent] = True
    return specificity.TermRelations(ancestors.tocsr(), sp.csc_matrix(membership))


def test_related_terms_cover_ancestry_and_overlap() -> None:
    membership = np.array([
        [1, 1, 0, 1], [1, 1, 0, 0], [1, 0, 1, 0], [0, 0, 1, 1],
    ])  # (n, t): terms 0 and 1 share 2 of 3 proteins (Jaccard 2/3)
    relations = _relations(membership, parent_of={2: 3})
    assert relations.related(0).tolist() == [True, True, False, False]
    assert relations.related(3).tolist() == [False, False, True, True]  # term 2 descends from 3
    assert relations.related(2).tolist() == [False, False, True, True]


def test_margin_skips_relatives_of_the_best_term() -> None:
    membership = np.eye(4, dtype=int).repeat(5, axis=0)  # (n, t), four disjoint terms
    relations = _relations(membership, parent_of={1: 0})
    auroc = np.array([
        [0.95, 0.94, 0.70, np.nan],  # best 0; 1 is its child, so the unrelated best is 2
        [0.60, 0.65, 0.90, 0.80],  # best 2; unrelated best 1 (0.65 < 0.80, so 3)
        [np.nan, np.nan, np.nan, np.nan],
    ])  # (p, t)
    margins = specificity.global_specificity(auroc, relations)
    assert margins.best_term.tolist() == [0, 2, -1]
    assert margins.unrelated_term.tolist() == [2, 3, -1]
    np.testing.assert_allclose(margins.margin[:2], [0.25, 0.10])
    assert np.isnan(margins.margin[2])


def test_single_dominant_term_counts_relatives_as_one() -> None:
    membership = np.eye(3, dtype=int).repeat(4, axis=0)  # (n, t)
    relations = _relations(membership, parent_of={1: 0})
    contrast = np.array([
        [0.90, 0.88, 0.10],  # 1 is 0's child: dominant
        [0.90, 0.10, 0.87],  # an unrelated term within 0.05: not dominant
        [0.20, 0.05, 0.01],  # below the contrast floor
        [0.50, 0.95, 0.10],  # its best term lacks informative proteins, so 0 is best and dominant
    ])  # (p, t)
    informative = np.array([60, 80, 70])  # (t,)
    informative_low = np.array([60, 10, 70])  # (t,)
    best, dominant = specificity.single_dominant_term(contrast[:3], informative, relations)
    assert best.tolist() == [0, 0, 0] and dominant.tolist() == [True, False, False]
    best, dominant = specificity.single_dominant_term(contrast[3:], informative_low, relations)
    assert best.tolist() == [0] and dominant.tolist() == [True]


def test_median_difference_interval_covers_a_known_shift() -> None:
    rng = np.random.default_rng(2)
    first, second = rng.normal(0.3, 0.1, 2_000), rng.normal(0.2, 0.1, 3_000)
    interval = bootstrap.median_difference(first, second)
    assert interval.low < 0.1 < interval.high and interval.excludes(0.0)
    assert bootstrap.median_difference(first, first, level=0.90).inside(-0.05, 0.05)


@pytest.mark.parametrize("sizes", [(7, 9), (101, 250), (2_001, 333)])
def test_chunked_resampling_draws_what_one_draw_would(sizes: tuple[int, int]) -> None:
    generator = np.random.default_rng(sizes[0])
    first, second = generator.normal(0.3, 0.1, sizes[0]), generator.normal(0.2, 0.1, sizes[1])  # (a,), (b,)
    one = np.random.default_rng(bootstrap.SEED)
    first_draws = np.median(first[one.integers(0, first.size, (bootstrap.DRAWS, first.size))], axis=1)  # (draws,)
    second_draws = np.median(second[one.integers(0, second.size, (bootstrap.DRAWS, second.size))], axis=1)  # (draws,)
    low, high = np.percentile(first_draws - second_draws, [2.5, 97.5])
    difference = bootstrap.median_difference(first, second)
    assert (difference.low, difference.high) == (low, high)  # exactly the stream of one draw
    low, high = np.percentile(np.median(first[np.random.default_rng(bootstrap.SEED).integers(
        0, first.size, (bootstrap.DRAWS, first.size))], axis=1), [2.5, 97.5])
    assert (bootstrap.median_interval(first).low, bootstrap.median_interval(first).high) == (low, high)


def test_rotation_test_requires_the_gap_to_exceed_the_spread() -> None:
    rotated = [np.full(10, value) for value in np.linspace(0.40, 0.44, 10)]
    assert bootstrap.rotation_test(np.full(10, 0.60), rotated).privileged
    narrow = bootstrap.rotation_test(np.full(10, 0.45), rotated)
    assert not narrow.privileged and narrow.rank_p == pytest.approx(1 / 11)
    assert bootstrap.rotation_test(np.full(10, 0.41), rotated).rank_p > 0.5
