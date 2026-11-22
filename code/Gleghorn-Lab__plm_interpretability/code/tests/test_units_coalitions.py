from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import torch

from plm_interpretability.units import coalitions, dictionary


def _activity(seed: int, residues: int = 6_000) -> tuple[torch.Tensor, torch.Tensor]:
    """Twelve sparse nonnegative poles, and three latents: a copy of pole 3, the sum of poles 1, 4 and 7 with unequal
    weights, and noise no pole carries."""
    generator = torch.Generator().manual_seed(seed)
    fires = torch.rand(residues, 12, generator=generator, dtype=torch.float64) < 0.15  # (r, p)
    poles = torch.where(fires, torch.rand(residues, 12, generator=generator, dtype=torch.float64) + 0.2, 0.0)  # (r, p)
    noise = torch.relu(torch.randn(residues, generator=generator, dtype=torch.float64))  # (r,)
    latents = torch.stack((2.0 * poles[:, 3], poles[:, 1] + 0.7 * poles[:, 4] + 1.5 * poles[:, 7], noise), dim=1)  # (r, m)
    return latents, poles  # (r, m), (r, p)


def _moments(latents: torch.Tensor, poles: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    """Covariance of latents with poles and of poles with one another, and both sides' deviations, written out."""
    # latents: (r, m); poles: (r, p)
    centered_latents, centered_poles = latents - latents.mean(dim=0), poles - poles.mean(dim=0)  # (r, m), (r, p)
    count = latents.shape[0]
    return (centered_latents.T @ centered_poles / count, centered_poles.T @ centered_poles / count,
            centered_latents.pow(2).mean(dim=0).sqrt(), centered_poles.pow(2).mean(dim=0).sqrt())  # (m, p), (p, p), (m,), (p,)


def test_greedy_fit_finds_a_copy_in_one_pole_and_a_group_in_its_members() -> None:
    latents, poles = _activity(0)
    covariance, pole_covariance, latent_sd, pole_sd = _moments(latents, poles)
    correlation = covariance / torch.outer(latent_sd, pole_sd)  # (m, p)
    gram = pole_covariance / torch.outer(pole_sd, pole_sd)  # (p, p)
    chosen, coefficients = coalitions.greedy_poles(correlation, gram, torch.ones(12, dtype=torch.bool), steps=4)
    assert int(chosen[0, 0]) == 3 and set(chosen[1, :3].tolist()) == {1, 4, 7}
    fitted = coalitions.fit_correlations(correlation, chosen, coefficients, sizes=(1, 2, 4))  # (m, s)
    assert float(fitted[0, 0]) == pytest.approx(1.0, abs=1e-6)
    assert float(fitted[1, 0]) < 0.9 and float(fitted[1, 2]) == pytest.approx(1.0, abs=1e-6)
    assert float(fitted[2, 2]) < 0.2
    # the fit of the first three poles is ordinary least squares on them
    picked = chosen[1, :3]
    design = (poles[:, picked] - poles[:, picked].mean(dim=0)) / pole_sd[picked]  # (r, 3)
    target = (latents[:, 1] - latents[:, 1].mean()) / latent_sd[1]  # (r,)
    expected = torch.linalg.lstsq(design, target[:, None]).solution.reshape(-1)  # (3,)
    torch.testing.assert_close(coefficients[1, 2, :3], expected, rtol=1e-5, atol=1e-6)


def test_a_pole_that_never_varies_is_never_chosen() -> None:
    latents, poles = _activity(1)
    poles[:, 5] = 0.0
    covariance, pole_covariance, latent_sd, pole_sd = _moments(latents, poles)
    scale = torch.outer(pole_sd, pole_sd)  # (p, p)
    gram = torch.where(scale > 0, pole_covariance / scale.clamp(min=1e-300), torch.zeros_like(scale))  # (p, p)
    scale = torch.outer(latent_sd, pole_sd)  # (m, p)
    correlation = torch.where(scale > 0, covariance / scale.clamp(min=1e-300), torch.zeros_like(scale))  # (m, p)
    chosen, _ = coalitions.greedy_poles(correlation, gram, pole_sd > 0, steps=11)
    assert not bool((chosen == 5).any()) and all(len(set(row.tolist())) == 11 for row in chosen)
    with pytest.raises(ValueError):
        coalitions.greedy_poles(correlation, gram, pole_sd > 0, steps=12)


def test_held_out_correlation_is_the_fitted_sum_s_correlation_on_other_residues() -> None:
    latents, poles = _activity(2)
    held_latents, held_poles = _activity(3)
    covariance, pole_covariance, latent_sd, pole_sd = _moments(latents, poles)
    correlation = covariance / torch.outer(latent_sd, pole_sd)  # (m, p)
    chosen, coefficients = coalitions.greedy_poles(correlation, pole_covariance / torch.outer(pole_sd, pole_sd),
                                                   torch.ones(12, dtype=torch.bool), steps=4)
    held_covariance, held_pole_covariance, held_latent_sd, _ = _moments(held_latents, held_poles)
    readings = coalitions.held_out_correlations(chosen, coefficients, pole_sd, held_covariance, held_pole_covariance,
                                                held_latent_sd, sizes=(1, 2, 4))  # (m, s)
    for latent in range(3):
        for position, size in enumerate((1, 2, 4)):
            picked = chosen[latent, :size]
            fitted = held_poles[:, picked] @ (coefficients[latent, size - 1, :size] / pole_sd[picked])  # (r,)
            expected = torch.corrcoef(torch.stack((fitted, held_latents[:, latent])))[0, 1]
            assert float(readings[latent, position]) == pytest.approx(float(expected), abs=1e-9)
    assert float(readings[0, 0]) > 0.999 and float(readings[1, 2]) > 0.999 and abs(float(readings[2, 2])) < 0.1


def test_smallest_sizes_and_mass_shares() -> None:
    correlations = np.array([[0.9, 0.95, 0.99], [0.3, 0.6, 0.8], [0.1, 0.2, np.nan], [0.69, 0.71, 0.5]])  # (m, s)
    smallest = coalitions.smallest_sizes(correlations, 0.7, sizes=(1, 2, 4))
    np.testing.assert_array_equal(smallest, [1, 4, 0, 2])
    shares = coalitions.mass_shares(np.array([5.0, 3.0, 1.0, 1.0]), smallest, sizes=(1, 2, 4))
    assert shares == {1: pytest.approx(0.5), 2: pytest.approx(0.6), 4: pytest.approx(0.9)}
    with pytest.raises(ValueError):
        coalitions.mass_shares(np.zeros(4), smallest, sizes=(1, 2, 4))


def test_report_and_concept_reading_follow_the_latents_fits() -> None:
    sizes = coalitions.SIZES
    held = np.zeros((4, len(sizes)))  # (m, s)
    held[0] = 0.95  # a copy
    held[1, 3:] = 0.8  # reached by eight poles
    held[3, 1:] = 0.75  # reached by two
    frame = pd.DataFrame({"latent": np.arange(4), "mass": [4.0, 3.0, 2.0, 1.0],
                          **{f"native_held_out_{size}": held[:, position] for position, size in enumerate(sizes)},
                          **{f"rotation_held_out_{size}": np.zeros(4) for size in sizes}})
    report = coalitions.coalition_report(frame, thresholds=(0.7,))["0.7"]
    assert report["native"]["mass_share"]["1"] == pytest.approx(0.4) and report["native"]["mass_share"]["2"] == pytest.approx(0.5)
    assert report["native"]["mass_share"]["64"] == pytest.approx(0.8) and report["native"]["unreached_latents"] == 1
    assert report["rotation"]["mass_share"]["64"] == 0 and report["rotation"]["unreached_latents"] == 4
    per_concept = pd.DataFrame({
        "arm": ["sae:tiny"] * 4 + ["mlp_poles"] * 4, "concept": list("abcd") * 2,
        "best_feature": [0, 1, 2, 3, 9, 9, 9, 9], "best_test_f1": [0.9, 0.8, 0.7, 0.2, 0.6, 0.1, 0.3, 0.9]})
    groups = coalitions.concept_latents(per_concept, "sae:tiny", "mlp_poles", frame)
    assert groups["shared"]["concepts"] == 1 and groups["shared"]["native"]["reached_by_size"]["1"] == 1
    assert groups["sae_only"]["concepts"] == 2 and groups["sae_only"]["native"]["reached_by_size"]["8"] == 1
    assert groups["sae_only"]["native"]["unreached"] == 1 and groups["sae_only"]["rotation"]["unreached"] == 2


def test_accumulator_moments_and_absorb_in_float32() -> None:
    latents, poles = _activity(4, residues=4_000)
    whole = dictionary.CorrelationAccumulator(3, 12)
    whole.update(latents, poles)
    first, second = (dictionary.CorrelationAccumulator(3, 12, dtype=torch.float32) for _ in range(2))
    first.update(latents[:1_500], poles[:1_500])
    second.update(latents[1_500:], poles[1_500:])
    first.absorb(second)
    assert first.count == whole.count == 4_000
    covariance, latent_sd, pole_sd = first.moments(torch.tensor([2, 0]))
    expected_covariance, _, expected_latent_sd, expected_pole_sd = _moments(latents, poles)
    assert covariance.dtype == torch.float64
    torch.testing.assert_close(covariance, expected_covariance[[2, 0]], rtol=1e-4, atol=1e-6)
    torch.testing.assert_close(latent_sd, expected_latent_sd[[2, 0]], rtol=1e-4, atol=1e-6)
    torch.testing.assert_close(pole_sd, expected_pole_sd, rtol=1e-4, atol=1e-6)
    torch.testing.assert_close(first.correlations(), whole.correlations(), rtol=1e-4, atol=1e-5)
    with pytest.raises(ValueError):
        first.absorb(dictionary.CorrelationAccumulator(3, 11))
