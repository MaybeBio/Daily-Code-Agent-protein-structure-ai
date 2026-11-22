from __future__ import annotations

import pytest
import torch

from plm_interpretability.units import firing_rates


def _sparse_reference(n_latents: int, seed: int) -> torch.Tensor:
    """Skewed SAE-like rates: most latents rare, a few dense."""
    generator = torch.Generator().manual_seed(seed)
    return torch.exp(torch.randn(n_latents, generator=generator, dtype=torch.float64) * 1.2 - 5.5).clamp(max=0.2)  # (m,)


def test_target_rates_are_the_reference_quantiles() -> None:
    reference = torch.tensor([0.0, 0.1, 0.2, 0.3, 0.4], dtype=torch.float64)  # (m,)
    targets = firing_rates.target_rates(reference, 5)  # (p,)
    # Quantile levels 0.1, 0.3, 0.5, 0.7, 0.9 over five points interpolate to 0.04, 0.12, 0.2, 0.28, 0.36.
    torch.testing.assert_close(targets, torch.tensor([0.04, 0.12, 0.2, 0.28, 0.36], dtype=torch.float64))


def test_targets_follow_the_order_of_natural_rates() -> None:
    natural = torch.tensor([0.5, 0.1, 0.3], dtype=torch.float64)  # (p,)
    targets = torch.tensor([0.01, 0.02, 0.03], dtype=torch.float64)  # (p,)
    assigned = firing_rates.assign_targets(natural, targets)  # (p,)
    assert assigned.tolist() == [0.03, 0.01, 0.02]


def test_thresholds_hit_targets_on_continuous_activations() -> None:
    generator = torch.Generator().manual_seed(0)
    activations = torch.rand(10_000, 6, generator=generator, dtype=torch.float64)  # (r, p)
    targets = torch.tensor([0.0, 0.001, 0.01, 0.05, 0.2, 1.0], dtype=torch.float64)  # (p,)
    thresholds = firing_rates.rate_thresholds(activations, targets)  # (p,)
    achieved = firing_rates.firing_rates(firing_rates.sparsify(activations, thresholds))  # (p,)
    torch.testing.assert_close(achieved, targets, rtol=0, atol=1e-4)


def test_ties_at_zero_keep_the_natural_rate() -> None:
    activations = torch.zeros(1_000, 1, dtype=torch.float64)  # (r, p)
    activations[:20, 0] = torch.linspace(1, 2, 20, dtype=torch.float64)
    match = firing_rates.match_firing_rates(activations, torch.full((50,), 0.3, dtype=torch.float64))
    assert float(match.achieved[0]) == pytest.approx(0.02)
    assert bool(match.below_target[0])


def test_matching_reproduces_a_skewed_reference_distribution() -> None:
    reference = _sparse_reference(4_096, seed=1)  # (m,)
    generator = torch.Generator().manual_seed(2)
    # Dense, heavy-tailed poles that fire on about half the residues, unlike the SAE.
    calibration = torch.relu(torch.randn(20_000, 512, generator=generator, dtype=torch.float64)) ** 2  # (r, p)
    held_out = torch.relu(torch.randn(20_000, 512, generator=generator, dtype=torch.float64)) ** 2  # (r, p)
    match = firing_rates.match_firing_rates(calibration, reference)
    assert firing_rates.ks_distance(match.achieved, reference) < 0.01
    held_out_rates = firing_rates.firing_rates(firing_rates.sparsify(held_out, match.thresholds))  # (p,)
    assert firing_rates.accept_rates(held_out_rates, reference) < firing_rates.KS_TOLERANCE
    assert not bool(match.below_target.any())


def test_a_bad_match_is_rejected() -> None:
    reference = _sparse_reference(1_000, seed=3)  # (m,)
    dense = torch.ones(1_000, 64, dtype=torch.float64)  # (r, p), every residue ties at one value
    match = firing_rates.match_firing_rates(dense, reference)
    with pytest.raises(ValueError):
        firing_rates.accept_rates(firing_rates.firing_rates(firing_rates.sparsify(dense, match.thresholds)), reference)


def test_ks_distance_of_identical_and_disjoint_sets() -> None:
    values = torch.tensor([0.1, 0.2, 0.3], dtype=torch.float64)  # (p,)
    assert firing_rates.ks_distance(values, values) == 0.0
    assert firing_rates.ks_distance(values, values + 1.0) == 1.0


def test_negative_activations_are_refused() -> None:
    with pytest.raises(ValueError):
        firing_rates.match_firing_rates(-torch.ones(10, 2), torch.full((5,), 0.1))
