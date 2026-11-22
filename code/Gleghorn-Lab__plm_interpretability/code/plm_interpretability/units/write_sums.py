"""E15a, exploratory: each SAE latent's decoder direction as a sparse sum of units' write vectors, from weights alone.

After Tigges and colleagues (Goodfire, November 2026), who sorted a transcoder's features by how many neurons' output
vectors rebuild a feature's decoder direction: orthogonal matching pursuit adds, at each step, the write vector that
lies closest to what is left of the direction, refits all chosen vectors by least squares, and stops when the fit's
cosine with the direction reaches `STOP` or `CAP` vectors are in. A latent is a copy when one vector suffices, a
coalition when 2 to `CAP` do, and unmatched otherwise. E14c fit latents with units' activity (`coalitions`); this is
that report's own measure, which needs no activation.

Controls: the same pursuit over the write vectors of a Haar rotation of the units (`rotated`), which span the same
space with no unit's vector among them, and of random directions in place of the decoder's (`random`), which give the
count a direction of no meaning needs. As in E8's write cosines, each vector's mean across the stream's dimensions is
removed first.

Symbols: m directions; a atoms (write vectors); d stream width; f units; q pursuit steps.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import torch

from collections.abc import Sequence
from torch import Tensor
from torch.nn import functional


STOP = 0.7
CAP = 64
NULL_CAP_FACTOR = 4
RANDOM_DIRECTIONS = 4_096
SEED = 24895
CHUNK = 2_048


def centered_unit(vectors: Tensor) -> Tensor:
    """Row vectors with their mean across dimensions removed, at unit length, in float32."""
    # vectors: (m, d)
    vectors = vectors.float()  # (m, d)
    return functional.normalize(vectors - vectors.mean(dim=1, keepdim=True), dim=1)  # (m, d)


@torch.no_grad()
def pursuit(directions: Tensor, atoms: Tensor, *, cap: int = CAP, chunk: int = CHUNK) -> tuple[Tensor, Tensor]:
    """Orthogonal matching pursuit of each direction over the atoms, both at unit length: the cosine between the
    direction and its least-squares fit after each step, and the atom each step adds."""
    # directions: (m, d); atoms: (a, d)
    steps = min(cap, atoms.shape[0], atoms.shape[1])
    cosines, chosen = [], []
    for start in range(0, directions.shape[0], chunk):
        target = directions[start:start + chunk]  # (c, d)
        rows = torch.arange(target.shape[0], device=target.device)  # (c,)
        residual = target.clone()  # (c, d)
        basis = torch.zeros(target.shape[0], steps, target.shape[1], device=target.device)  # (c, q, d), orthonormal
        used = torch.zeros(target.shape[0], atoms.shape[0], dtype=torch.bool, device=target.device)  # (c, a)
        part_cosines = torch.zeros(target.shape[0], steps, device=target.device)  # (c, q)
        part_chosen = torch.zeros(target.shape[0], steps, dtype=torch.int64, device=target.device)  # (c, q)
        for step in range(steps):
            score = (residual @ atoms.T).abs().masked_fill(used, -1.0)  # (c, a)
            pick = score.argmax(dim=1)  # (c,)
            used[rows, pick] = True
            fresh = atoms[pick]  # (c, d)
            for _ in range(2):  # twice, so that float32 leaves the new vector orthogonal to those before it
                fresh = fresh - torch.einsum("cqd,cd->cq", basis[:, :step], fresh).unsqueeze(-1).mul(basis[:, :step]).sum(dim=1)
            fresh = functional.normalize(fresh, dim=1)  # (c, d)
            basis[:, step] = fresh
            residual = residual - (residual * fresh).sum(dim=1, keepdim=True) * fresh  # (c, d)
            part_cosines[:, step] = (1 - residual.pow(2).sum(dim=1)).clamp(min=0).sqrt()
            part_chosen[:, step] = pick
        cosines.append(part_cosines.cpu())
        chosen.append(part_chosen.cpu())
    return torch.cat(cosines), torch.cat(chosen)  # (m, q), (m, q)


def sizes(cosines: Tensor, stop: float = STOP) -> Tensor:
    """The number of atoms at which each direction's fit first reaches `stop`; one more than the steps run when none
    does."""
    # cosines: (m, q)
    reached = cosines >= stop  # (m, q)
    first = reached.double().argmax(dim=1) + 1  # (m,)
    return torch.where(reached.any(dim=1), first, torch.full_like(first, cosines.shape[1] + 1))  # (m,)


def taxonomy(size: Tensor, cap: int = CAP) -> dict[str, float]:
    """The shares of directions that one atom rebuilds, that 2 to `cap` rebuild, and that none do, with the median
    count among those rebuilt."""
    # size: (m,)
    matched = size <= cap  # (m,)
    return {"copy": float((size == 1).double().mean()), "coalition": float(((size > 1) & matched).double().mean()),
            "unmatched": float((~matched).double().mean()),
            "median_size": float(size[matched].double().quantile(0.5)) if bool(matched.any()) else float("nan")}


def write_atoms(writes: Sequence[Tensor], rotation_seed: int | None = None) -> Tensor:
    """The write vectors of some blocks' units as atoms, block by block; with a seed, those of a Haar rotation of each
    block's units instead."""
    # writes: (d, f) each, a block's down projection
    from .rotations import haar_rotation

    atoms = []
    for index, write in enumerate(writes):
        write = write.float()  # (d, f)
        if rotation_seed is not None:
            write = write @ haar_rotation(write.shape[1], rotation_seed * 1_000 + index, device=write.device)  # (d, f)
        atoms.append(write.T)
    return centered_unit(torch.cat(atoms))  # (a, d)


def run_write_sums(decoder: Tensor, writes: Sequence[Tensor], *, cap: int = CAP, stop: float = STOP,
                   random_directions: int = RANDOM_DIRECTIONS, seed: int = SEED) -> tuple[pd.DataFrame, dict[str, object]]:
    """Every decoder direction over the units' write vectors and over a rotation's, and random directions over the
    units'. Returns one row a latent (its size and first and last cosines in each basis, its first eight units) and
    the three taxonomies."""
    # decoder: (m, d); writes: (d, f) for each block whose units may enter the sum
    directions = centered_unit(decoder)  # (m, d)
    native = write_atoms(writes)  # (a, d)
    rotated = write_atoms(writes, rotation_seed=0)  # (a, d)
    generator = torch.Generator().manual_seed(seed)
    noise = centered_unit(torch.randn(random_directions, decoder.shape[1], generator=generator)).to(directions.device)
    cosines, chosen = pursuit(directions, native, cap=cap)  # (m, q), (m, q)
    rotated_cosines, _ = pursuit(directions, rotated, cap=cap)  # (m, q)
    # Random directions run four times as many steps, so that the count they need is read and not only bounded.
    random_cosines, _ = pursuit(noise, native, cap=NULL_CAP_FACTOR * cap)  # (r, q_null)
    size, rotated_size, random_size = sizes(cosines, stop), sizes(rotated_cosines, stop), sizes(random_cosines, stop)
    frame = pd.DataFrame({
        "latent": np.arange(len(size)), "size": size.numpy(), "cosine_one": cosines[:, 0].numpy(),
        "cosine_cap": cosines[:, -1].numpy(), "rotated_size": rotated_size.numpy(),
        "rotated_cosine_one": rotated_cosines[:, 0].numpy(), "rotated_cosine_cap": rotated_cosines[:, -1].numpy(),
        "first_atoms": list(chosen[:, :8].numpy()),
    })
    report = {"stop": stop, "cap": cap, "atoms": int(native.shape[0]), "latents": int(len(size)),
              "native": taxonomy(size, cap), "rotated": taxonomy(rotated_size, cap),
              "random": {**taxonomy(random_size, cap), "directions": random_directions, "steps": int(random_cosines.shape[1]),
                         "size_quantiles": {str(level): float(random_size.double().quantile(level)) for level in (0.1, 0.5, 0.9)},
                         "median_cosine_at_cap": float(random_cosines[:, min(cap, random_cosines.shape[1]) - 1].median())}}
    return frame, report
