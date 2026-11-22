"""Stage 6: paired bootstrap CI on a Spearman difference. Run: uv run pytest tests/test_6_bootstrap.py -v"""

import numpy as np
import pytest

from pfit.metrics import paired_bootstrap, spearman


def make(n, noise_a, noise_b, seed=0):
    """Fake assay: n mutants, true fitness y, two models with independent noise."""
    rng = np.random.default_rng(seed)
    y = rng.normal(size=n)
    a = y + noise_a * rng.normal(size=n)
    b = y + noise_b * rng.normal(size=n)
    return a, b, y


def width(result):
    _, lo, hi = result
    return hi - lo


def test_delta_is_the_full_data_difference():
    a, b, y = make(300, 0.5, 2.0)
    delta, _, _ = paired_bootstrap(a, b, y, n_boot=50)
    assert delta == pytest.approx(spearman(a, y) - spearman(b, y))


def test_returns_python_floats_in_order():
    a, b, y = make(300, 0.5, 2.0)
    delta, lo, hi = paired_bootstrap(a, b, y, n_boot=200)
    assert all(isinstance(v, float) for v in (delta, lo, hi))
    assert lo < delta < hi


def test_identical_models_give_a_zero_interval():
    a, _, y = make(200, 1.0, 1.0)
    assert paired_bootstrap(a, a.copy(), y, n_boot=100) == pytest.approx((0.0, 0.0, 0.0))


def test_seed_is_reproducible():
    a, b, y = make(200, 1.0, 1.5)
    r1 = paired_bootstrap(a, b, y, n_boot=100, seed=7)
    r2 = paired_bootstrap(a, b, y, n_boot=100, seed=7)
    r3 = paired_bootstrap(a, b, y, n_boot=100, seed=8)
    assert r1 == r2
    assert r1 != r3, "the seed should drive the resampling"


def test_clear_winner_interval_excludes_zero():
    a, b, y = make(500, 0.3, 5.0)  # a is good, b is close to random
    _, lo, _ = paired_bootstrap(a, b, y, n_boot=200)
    assert lo > 0


def test_swapping_models_flips_the_interval():
    a, b, y = make(300, 0.5, 1.5)
    d, lo, hi = paired_bootstrap(a, b, y, n_boot=200, seed=3)
    d2, lo2, hi2 = paired_bootstrap(b, a, y, n_boot=200, seed=3)
    assert (d2, lo2, hi2) == pytest.approx((-d, -hi, -lo))


def test_pairing_cancels_shared_noise():
    # b is a with tiny extra noise: the two models agree on almost every mutant.
    # Each model's own Spearman is very uncertain (rho ~ 0.4 on 200 mutants), but the
    # DIFFERENCE is nearly constant, as long as both use the same resampled mutants.
    rng = np.random.default_rng(1)
    y = rng.normal(size=200)
    a = y + 2.0 * rng.normal(size=200)
    b = a + 0.05 * rng.normal(size=200)
    w = width(paired_bootstrap(a, b, y, n_boot=300))
    assert w < 0.05, f"width {w:.3f}: resample the SAME indices for both models"


def test_more_mutants_narrow_the_interval():
    small = width(paired_bootstrap(*make(100, 1.0, 2.0), n_boot=300))
    large = width(paired_bootstrap(*make(1600, 1.0, 2.0), n_boot=300))
    assert small / large > 2.5, "16x more mutants should give roughly a 4x narrower interval"


def test_higher_confidence_is_wider():
    a, b, y = make(300, 1.0, 2.0)
    w95 = width(paired_bootstrap(a, b, y, n_boot=400, ci=0.95))
    w99 = width(paired_bootstrap(a, b, y, n_boot=400, ci=0.99975))  # Bonferroni for 201 assays
    assert w99 > w95


def test_nan_rows_are_dropped_for_both_models():
    a, b, y = make(300, 1.0, 2.0)
    a_nan, y_nan = a.copy(), y.copy()
    a_nan[[3, 50]] = np.nan
    y_nan[100] = np.nan
    keep = np.ones(300, bool)
    keep[[3, 50, 100]] = False
    got = paired_bootstrap(a_nan, b, y_nan, n_boot=100, seed=5)
    want = paired_bootstrap(a[keep], b[keep], y[keep], n_boot=100, seed=5)
    assert got == pytest.approx(want)
