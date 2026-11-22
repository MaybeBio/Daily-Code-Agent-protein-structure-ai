"""The sparsest-rotation search: from a random start, does the rotation that concentrates activity land on the neurons?

Cammarata (Goodfire, 2026) reports that searching a layer's rotations for the one in which a handful of units carry the
most activity, from a random rotation, returns to the neuron basis in every block of a vision model. Here the activity
of a block's units is standardized per unit, and the rotation Q maximizes the mean over residues of the sum of fourth
powers of the rotated coordinates (an orthomax criterion: since each residue's norm is unchanged by Q, a larger sum of
fourth powers means fewer coordinates carry the residue). Q climbs the orthogonal group by Riemannian gradient ascent
with an exponential-map retraction and a backtracking step. Where it lands is read with `rotations.basis_recovery`.

Symbols: r residues; f units.
"""

from __future__ import annotations

import torch

from dataclasses import dataclass
from torch import Tensor

from .rotations import haar_rotation


RECOVERY_REFERENCE = 0.9  # the closeness to the native axes a search is read against (preregistration, sparsest_rotation)
SEARCH_SEEDS = (24895, 24896, 24897)  # E8's Haar starts, the study's three seeds


@dataclass(frozen=True)
class Standardization:
    """Each unit's mean and standard deviation over the sampled residues, the coordinates the search runs in."""

    mean: Tensor  # (f,)
    scale: Tensor  # (f,), zero for a unit constant over the sample

    def apply(self, state: Tensor) -> Tensor:
        """Residues' units centered and scaled in the mean's dtype; a constant unit stays zero."""
        # state: (r, f)
        centered = state.to(self.mean.dtype) - self.mean  # (r, f)
        varies = self.scale > 0  # (f,)
        return torch.where(varies, centered / torch.where(varies, self.scale, 1.0), torch.zeros_like(centered))  # (r, f)

    def to(self, device: torch.device | str, dtype: torch.dtype) -> Standardization:
        return Standardization(self.mean.to(device, dtype), self.scale.to(device, dtype))


def standardization(samples: Tensor) -> Standardization:
    """The sample's per-unit mean and standard deviation, in float64."""
    # samples: (r, f)
    samples = samples.double()  # (r, f)
    mean = samples.mean(dim=0)  # (f,)
    return Standardization(mean, (samples - mean).std(dim=0))


def standardize(samples: Tensor) -> Tensor:
    """Each unit centered and scaled to unit variance over the sampled residues; constant units stay zero."""
    # samples: (r, f)
    return standardization(samples).apply(samples)  # (r, f), float64


def fourth_power_objective(samples: Tensor, rotation: Tensor) -> Tensor:
    """Mean over residues of the sum of the rotated coordinates' fourth powers."""
    # samples: (r, f); rotation: (f, f)
    return ((samples @ rotation) ** 4).sum(dim=1).mean()  # ()


def native_objective(samples: Tensor) -> Tensor:
    """The objective of the native basis itself, the identity rotation, without the product."""
    # samples: (r, f)
    return (samples**4).sum(dim=1).mean()  # ()


@dataclass(frozen=True)
class SearchResult:
    rotation: Tensor  # (f, f)
    objective: tuple[float, ...]  # the objective after each accepted step


def sparsest_rotation(
    samples: Tensor,
    *,
    seed: int,
    steps: int = 300,
    step_size: float = 0.5,
    min_step: float = 1e-6,
    tolerance: float = 1e-7,
) -> SearchResult:
    """Climb from a Haar rotation (seeded) toward the rotation that maximizes the fourth-power objective.

    The climb stops after `steps` accepted steps, when no step down to `min_step` improves the objective, or when an
    accepted step improves it by less than `tolerance` relative to its value.
    """
    # samples: (r, f), standardized
    width = samples.shape[1]
    rotation = haar_rotation(width, seed, dtype=samples.dtype, device=samples.device)  # (f, f)
    current = float(fourth_power_objective(samples, rotation))
    history = [current]
    size = step_size
    for _ in range(steps):
        rotated = samples @ rotation  # (r, f)
        gradient = 4 * samples.T @ rotated**3 / samples.shape[0]  # (f, f), Euclidean gradient
        tangent = rotation.T @ gradient  # (f, f)
        skew = (tangent - tangent.T) / 2  # (f, f), the ascent direction in the Lie algebra
        norm = float(torch.linalg.matrix_norm(skew))
        if norm < 1e-12:
            break
        gain = None
        while size >= min_step:
            candidate = rotation @ torch.linalg.matrix_exp(size * skew / norm)  # (f, f)
            value = float(fourth_power_objective(samples, candidate))
            if value > current:
                gain = (value - current) / abs(current)
                rotation, current = candidate, value
                history.append(current)
                size = min(size * 1.5, step_size)
                break
            size /= 2
        if gain is None or gain < tolerance:
            break
    return SearchResult(rotation=rotation, objective=tuple(history))
