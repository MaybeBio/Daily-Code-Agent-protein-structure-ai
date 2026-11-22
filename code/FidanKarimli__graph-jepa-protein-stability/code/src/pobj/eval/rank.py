"""Effective rank of an embedding matrix.

The RankMe quantity: the entropy of the normalised singular values, exponentiated. A matrix
whose rows all point the same way scores near 1; one using every direction equally scores
the full dimension. We log it during pretraining as a warning light for collapse.

It is only comparable between runs computed on the same number of residues, so the sample
size belongs in every table that reports it.
"""
import torch
from torch import Tensor


def effective_rank(z: Tensor, eps: float = 1e-12,
                   sample: int | None = None, seed: int = 0) -> float:
    """z: [N, K] -> a number between 1 and K.

    `sample` fixes how many rows are used, because rank measured on more samples is not
    comparable with rank measured on fewer. Corpora of different sizes would otherwise be
    scored on different N: our SCOPe validation slice is 80,275 residues and the AlphaFold
    one about 205,000.
    """
    if sample and z.shape[0] > sample:
        index = torch.randperm(z.shape[0], generator=torch.Generator().manual_seed(seed))
        z = z[index[:sample]]
    singular = torch.linalg.svdvals(z.float())
    p = singular / (singular.sum() + eps)
    entropy = -(p * (p + eps).log()).sum()
    return float(entropy.exp())


def per_dimension_variance(z: Tensor) -> dict[str, float]:
    """A few large variances with the rest near zero is the other sign of collapse."""
    var = z.float().var(dim=0)
    return {"var_mean": float(var.mean()),
            "var_max": float(var.max()),
            "var_frac_near_zero": float((var < 0.01 * var.max()).float().mean())}
