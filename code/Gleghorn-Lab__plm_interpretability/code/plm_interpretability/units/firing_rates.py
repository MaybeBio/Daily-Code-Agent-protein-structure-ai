"""Firing-rate matching: every basis sparsified to the SAE's distribution of residue firing rates.

Specificity depends on how often a unit fires, and SAE latents are sparse by construction while neuron poles are not,
so no basis is compared before this step. The reference is the matched SAE's latents on the calibration proteins: each
latent's rate is the share of residues where it is nonzero. A basis of P poles receives the reference's rate quantiles
at (i - 0.5) / P, assigned in the order of the poles' own natural rates, so the pole that fires most often keeps the
highest target. Each pole is thresholded at its own quantile so that it fires on its target share of calibration
residues, and everything at or below the threshold is set to zero. A pole that fires less often than its target, which
ties at zero force, keeps its natural rate and is reported. The match is accepted when the Kolmogorov-Smirnov distance
between the basis's and the reference's rates on held-out residues is below 0.05 (preregistration).

Symbols: r residues; p poles of the basis; m reference latents.
"""

from __future__ import annotations

import torch

from dataclasses import dataclass
from torch import Tensor


KS_TOLERANCE = 0.05


@dataclass(frozen=True)
class RateMatch:
    """The thresholds that sparsify one basis to the reference's rates, and what they achieved on calibration."""

    thresholds: Tensor  # (p,), fire where activation > threshold
    targets: Tensor  # (p,), the target rate assigned to each pole
    natural: Tensor  # (p,), the share of calibration residues where each pole is nonzero
    achieved: Tensor  # (p,), the share of calibration residues above each threshold

    @property
    def below_target(self) -> Tensor:
        """Poles whose natural rate is below their target, which keep their natural rate."""
        return self.natural < self.targets  # (p,)


def firing_rates(activations: Tensor) -> Tensor:
    """The share of residues at which each unit is nonzero."""
    # activations: (r, p), nonnegative
    if activations.ndim != 2 or activations.shape[0] == 0:
        raise ValueError(f"Firing rates need a nonempty (residues, units) matrix, got {tuple(activations.shape)}.")
    return (activations > 0).double().mean(dim=0)  # (p,)


def target_rates(reference_rates: Tensor, n_poles: int) -> Tensor:
    """The reference's rate quantiles at (i - 0.5) / n_poles, ascending, by linear interpolation."""
    # reference_rates: (m,)
    if n_poles < 1 or reference_rates.ndim != 1 or reference_rates.numel() == 0:
        raise ValueError("Target rates need a nonempty reference and at least one pole.")
    sorted_reference = torch.sort(reference_rates.double()).values  # (m,)
    levels = (torch.arange(n_poles, dtype=torch.float64, device=sorted_reference.device) + 0.5) / n_poles  # (p,)
    positions = levels * (sorted_reference.numel() - 1)  # (p,)
    lower = positions.floor().long()  # (p,)
    upper = positions.ceil().long()  # (p,)
    weight = positions - lower  # (p,)
    return sorted_reference[lower] * (1 - weight) + sorted_reference[upper] * weight  # (p,)


def assign_targets(natural: Tensor, targets: Tensor) -> Tensor:
    """Give the poles the target rates in the order of their natural rates (ties broken by column)."""
    # natural, targets: (p,)
    if natural.shape != targets.shape:
        raise ValueError("Natural and target rates must have one entry per pole.")
    order = torch.argsort(natural, stable=True)  # (p,)
    assigned = torch.empty_like(targets, dtype=torch.float64)  # (p,)
    assigned[order] = torch.sort(targets.double()).values  # (p,)
    return assigned  # (p,)


def rate_thresholds(activations: Tensor, targets: Tensor, chunk: int = 1024) -> Tensor:
    """Per pole, the value above which it fires on its target share of the given residues.

    The threshold is the (k + 1)-th largest activation with k = round(target * r), so exactly k residues lie strictly
    above it when there are no ties; ties at the threshold, zero above all, make a pole fire less often, never more.
    Columns are sorted in chunks to bound memory.
    """
    # activations: (r, p), nonnegative; targets: (p,)
    n_residues, n_poles = activations.shape
    if targets.shape != (n_poles,):
        raise ValueError(f"Expected {n_poles} targets, got {tuple(targets.shape)}.")
    counts = torch.round(targets.double().clamp(0, 1) * n_residues).long()  # (p,)
    thresholds = torch.empty(n_poles, dtype=torch.float64, device=activations.device)  # (p,)
    for start in range(0, n_poles, chunk):
        stop = min(start + chunk, n_poles)
        descending = torch.sort(activations[:, start:stop].double(), dim=0, descending=True).values  # (r, chunk)
        index = counts[start:stop].clamp(max=n_residues - 1).to(activations.device)  # (chunk,)
        selected = descending.gather(0, index.unsqueeze(0)).squeeze(0)  # (chunk,)
        # A pole asked to fire on every residue fires wherever it is nonnegative.
        thresholds[start:stop] = torch.where(counts[start:stop].to(activations.device) >= n_residues, -1.0, selected)  # (chunk,)
    return thresholds  # (p,)


def sparsify(activations: Tensor, thresholds: Tensor) -> Tensor:
    """Zero every activation at or below its pole's threshold."""
    # activations: (r, p); thresholds: (p,)
    keep = activations > thresholds.to(activations.device, activations.dtype).unsqueeze(0)  # (r, p)
    return torch.where(keep, activations, activations.new_zeros(()))  # (r, p)


def ks_distance(first: Tensor, second: Tensor) -> float:
    """The two-sample Kolmogorov-Smirnov statistic between two sets of rates: the largest gap between their
    empirical distribution functions."""
    # first: (p,); second: (m,)
    first = torch.sort(first.double().flatten()).values  # (p,)
    second = torch.sort(second.double().flatten().to(first.device)).values  # (m,)
    support = torch.cat((first, second))  # (p + m,)
    cdf_first = torch.searchsorted(first, support, right=True).double() / first.numel()  # (p + m,)
    cdf_second = torch.searchsorted(second, support, right=True).double() / second.numel()  # (p + m,)
    return float((cdf_first - cdf_second).abs().max())  # ()


def match_firing_rates(calibration: Tensor, reference_rates: Tensor) -> RateMatch:
    """Thresholds that give a basis the reference's firing-rate distribution on the calibration residues."""
    # calibration: (r, p), nonnegative pole activations; reference_rates: (m,)
    if bool((calibration < 0).any()):
        raise ValueError("Pole activations must be nonnegative; split signed states with `poles.sign_poles` first.")
    reference_rates = reference_rates.to(calibration.device)  # (m,), loaded rates arrive on the CPU
    natural = firing_rates(calibration)  # (p,)
    targets = assign_targets(natural, target_rates(reference_rates, calibration.shape[1]))  # (p,)
    thresholds = rate_thresholds(calibration, targets)  # (p,)
    achieved = firing_rates(sparsify(calibration, thresholds))  # (p,)
    return RateMatch(thresholds=thresholds, targets=targets, natural=natural, achieved=achieved)


def accept_rates(rates: Tensor, reference_rates: Tensor) -> float:
    """The Kolmogorov-Smirnov distance between a sparsified basis's and the reference's rates, both measured on the same
    held-out residues; raises when it reaches the preregistered tolerance."""
    # rates: (p,); reference_rates: (m,)
    distance = ks_distance(rates, reference_rates)
    if distance >= KS_TOLERANCE:
        raise ValueError(f"Firing-rate match rejected: Kolmogorov-Smirnov distance {distance:.4f} >= {KS_TOLERANCE}.")
    return distance
