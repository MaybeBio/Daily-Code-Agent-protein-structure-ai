"""Cluster-bootstrap intervals and fixed-precision recall for held-out feature assignments.

A point estimate over a few hundred held-out clusters is not enough to act on. The resampling unit
has to be the MMseqs2 cluster rather than the protein, because proteins inside a cluster are
homologous and resampling them independently would understate the interval by treating correlated
observations as independent.

AUROC is recomputed inside the bootstrap by ranking, not by calling a scikit-learn scorer per
feature per resample, which would be thousands of times slower for the same number.

Symbols: `n` held-out proteins, `c` assigned features, `b` bootstrap resamples.
"""

import numpy as np
import torch

from dataclasses import dataclass


DEFAULT_RESAMPLES = 200


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    """Percentile interval for a statistic computed over resampled clusters."""

    point: float
    lower: float
    upper: float
    n_resamples: int

    def as_dict(self, prefix: str) -> dict[str, float]:
        return {
            prefix: self.point,
            f"{prefix}_ci_low": self.lower,
            f"{prefix}_ci_high": self.upper,
            f"{prefix}_n_resamples": float(self.n_resamples),
        }


def _column_auroc(activation: torch.Tensor, membership: torch.Tensor) -> torch.Tensor:
    """Return the AUROC of each column against its own binary label column.

    Ties get midranks, which matters because TopK activations are exactly zero for most proteins.
    """
    # activation: (n, c); membership: (n, c) bool
    n = activation.shape[0]
    sorted_values, order = torch.sort(activation, dim=0)  # (n, c)

    is_new = torch.ones_like(sorted_values, dtype=torch.bool)  # (n, c)
    is_new[1:] = sorted_values[1:] != sorted_values[:-1]
    group = is_new.to(torch.int64).cumsum(0) - 1  # (n, c)
    positions = torch.arange(n, device=activation.device, dtype=torch.float32).unsqueeze(1)
    positions = positions.expand_as(sorted_values)  # (n, c)

    first = torch.full_like(positions, float(n))  # (n, c)
    first.scatter_reduce_(0, group, positions, reduce="amin", include_self=True)
    last = torch.full_like(positions, -1.0)  # (n, c)
    last.scatter_reduce_(0, group, positions, reduce="amax", include_self=True)
    midrank_sorted = (first.gather(0, group) + last.gather(0, group)) / 2.0 + 1.0  # (n, c)

    ranks = torch.empty_like(midrank_sorted)  # (n, c)
    ranks.scatter_(0, order, midrank_sorted)

    positive = membership.to(torch.float32)  # (n, c)
    n_positive = positive.sum(dim=0)  # (c,)
    n_negative = n - n_positive  # (c,)
    rank_sum = (ranks * positive).sum(dim=0)  # (c,)
    u_statistic = rank_sum - n_positive * (n_positive + 1.0) / 2.0  # (c,)

    return torch.where(
        (n_positive > 0) & (n_negative > 0),
        u_statistic / torch.clamp(n_positive * n_negative, min=1.0),
        torch.full_like(u_statistic, float("nan")),
    )  # (c,)


def cluster_bootstrap_auroc(
    activation: np.ndarray,
    membership: np.ndarray,
    cluster_index: np.ndarray,
    n_resamples: int = DEFAULT_RESAMPLES,
    seed: int = 20260826,
    device: str = "cuda",
    quantiles: tuple[float, float] = (2.5, 97.5),
) -> BootstrapResult:
    """Return a percentile interval for the median held-out AUROC, resampling whole clusters."""
    # activation: (n, c); membership: (n, c) bool; cluster_index: (n,)
    generator = np.random.default_rng(seed)
    clusters, membership_of_cluster = np.unique(cluster_index, return_inverse=True)
    rows_by_cluster = [np.flatnonzero(membership_of_cluster == index) for index in range(len(clusters))]

    activation_gpu = torch.from_numpy(np.ascontiguousarray(activation)).to(device)  # (n, c)
    membership_gpu = torch.from_numpy(np.ascontiguousarray(membership)).to(device)  # (n, c)

    point_auroc = _column_auroc(activation_gpu, membership_gpu)  # (c,)
    point = float(np.nanmedian(point_auroc.cpu().numpy()))

    medians: list[float] = []
    for _ in range(n_resamples):
        chosen = generator.integers(0, len(clusters), size=len(clusters))
        rows = np.concatenate([rows_by_cluster[index] for index in chosen])
        index_tensor = torch.from_numpy(rows).to(device)
        resampled = _column_auroc(activation_gpu[index_tensor], membership_gpu[index_tensor])
        medians.append(float(np.nanmedian(resampled.cpu().numpy())))

    low, high = np.percentile(medians, quantiles)
    return BootstrapResult(point=point, lower=float(low), upper=float(high), n_resamples=n_resamples)


def recall_at_precision(
    scores: np.ndarray,
    labels: np.ndarray,
    target_precision: float = 0.5,
) -> float:
    """Return the highest recall reaching `target_precision`, or NaN when it is never reached.

    NaN is deliberate. Imputing zero would silently convert "this question has no answer on this
    test set" into "the method scored zero", and with a median term prevalence of a few percent that
    distinction covers a large share of terms.
    """
    # scores, labels: (n,)
    order = np.argsort(-scores)  # (n,)
    ordered = labels[order].astype(np.float64)  # (n,)
    true_positive = np.cumsum(ordered)  # (n,)
    precision = true_positive / np.arange(1, len(ordered) + 1)  # (n,)
    total_positive = ordered.sum()
    if total_positive == 0:
        return float("nan")

    reaching = precision >= target_precision
    if not reaching.any():
        return float("nan")

    return float((true_positive[reaching] / total_positive).max())
