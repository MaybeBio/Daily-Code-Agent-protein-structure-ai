"""Haar-random rotations: the null that separates a privileged basis from an arbitrary one.

A rotated basis keeps every geometric property of the space (distances, the subspace a concept spans, what a dense
linear probe reads) and changes only which directions count as units. If the native neurons label concepts no better
than the coordinates of a random rotation of the same space, the basis is not privileged.

Symbols: r residues; f the rotated space's width.
"""

from __future__ import annotations

import torch

from torch import Tensor


def haar_rotation(width: int, seed: int, dtype: torch.dtype = torch.float32, device: str | torch.device = "cpu") -> Tensor:
    """An orthogonal matrix drawn from the Haar measure: the Q of a Gaussian matrix's QR, with R's diagonal signs
    absorbed (without them QR's sign convention biases the draw). Built in float64 on the CPU, so a seed gives the same
    rotation on every machine."""
    if width < 1:
        raise ValueError(f"A rotation needs a positive width, got {width}.")
    generator = torch.Generator(device="cpu").manual_seed(seed)
    gaussian = torch.randn(width, width, generator=generator, dtype=torch.float64)  # (f, f)
    orthogonal, triangular = torch.linalg.qr(gaussian)  # (f, f), (f, f)
    signs = torch.sign(torch.diagonal(triangular))  # (f,)
    assert bool((signs != 0).all()), "A Gaussian matrix's QR gave a zero on R's diagonal."
    return (orthogonal * signs.unsqueeze(0)).to(dtype=dtype, device=device)  # (f, f)


def rotate(state: Tensor, rotation: Tensor) -> Tensor:
    """The state's coordinates in the rotated basis: column k is the projection on the rotation's k-th column."""
    # state: (r, f); rotation: (f, f)
    if rotation.shape != (state.shape[-1], state.shape[-1]):
        raise ValueError(f"Rotation {tuple(rotation.shape)} does not match state width {state.shape[-1]}.")
    return state.to(rotation.dtype) @ rotation  # (r, f)


def basis_recovery(rotation: Tensor) -> float:
    """How close a rotation's axes lie to the native axes: the mean over its columns of the largest absolute cosine
    with a standard basis vector. A signed permutation of the native basis scores 1; a Haar rotation of width f scores
    about sqrt(2 log f / f)."""
    # rotation: (f, f), orthonormal columns
    return float(rotation.abs().amax(dim=0).mean())  # ()
