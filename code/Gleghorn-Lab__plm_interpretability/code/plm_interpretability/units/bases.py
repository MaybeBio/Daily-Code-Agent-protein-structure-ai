"""Every basis a block's units are read in, each as nonnegative poles (preregistration, `poles` and `bases`).

| Kind | Read from | Poles |
|---|---|---|
| `native` | SwiGLU gate and up | the positive and negative gate-tagged poles, 2f |
| `leak` | SwiGLU gate and up | the two gate-closed leak poles, 2f |
| `sign` | the product z | z's two signs, ignoring the gate (the sign-only sensitivity), 2f |
| `gate` | the gate | its open and closed parts (the gate-alone secondary), 2f |
| `rotation` | z times a seeded Haar rotation | the rotated coordinates' two signs, 2f |
| `residual` | the block's output stream | its coordinates' two signs, 2d |
| `sae` | the stream (Biohub's layer SAEs) or the feed-forward write (its MLP-output SAEs) | the SAE's TopK codes, c |

Rotations act on z itself, so a rotated basis spans the same space as the native units, and every pole construction
after it is the same. SAE codes come from `foundry.embedding.encode_topk`, the atlas study's encoder.

Symbols: r residues; d model width; f units; c SAE codebook.
"""

from __future__ import annotations

import torch

from dataclasses import dataclass
from torch import Tensor, nn

from foundry.embedding import encode_topk
from .capture import BlockStates
from .poles import sign_poles, swiglu_poles
from .rotations import rotate


KINDS = ("native", "leak", "sign", "gate", "rotation", "residual", "sae")
SAE_SOURCES = ("stream", "write")


@dataclass(frozen=True)
class Basis:
    """One basis at one block; `seed` names a rotation, `sae` the run's name for an SAE and `reads` its input."""

    kind: str
    block: int
    seed: int | None = None
    sae: str | None = None
    reads: str = "stream"

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"Basis kind {self.kind!r} is not one of {KINDS}.")
        if (self.kind == "rotation") != (self.seed is not None):
            raise ValueError("A rotation basis needs a seed, and no other basis takes one.")
        if (self.kind == "sae") != (self.sae is not None):
            raise ValueError("An SAE basis needs the SAE's name, and no other basis takes one.")
        if self.reads not in SAE_SOURCES or (self.kind != "sae" and self.reads != "stream"):
            raise ValueError(f"Only an SAE basis reads something other than the stream, from {SAE_SOURCES}.")

    @property
    def name(self) -> str:
        label = {"rotation": f"rotation{self.seed}", "sae": f"sae:{self.sae}"}.get(self.kind, self.kind)
        return f"block{self.block}/{label}"

    @property
    def needs_stream(self) -> bool:
        return self.kind == "residual" or (self.kind == "sae" and self.reads == "stream")

    @property
    def needs_write(self) -> bool:
        return self.kind == "sae" and self.reads == "write"


def basis_width(basis: Basis, d: int, f: int, codebook: int | None = None) -> int:
    """Number of poles the basis has at a block of width d with f units, or the SAE's codebook."""
    if basis.kind == "sae":
        if codebook is None:
            raise ValueError("An SAE basis's width is its codebook, which must be given.")
        return codebook
    return 2 * d if basis.kind == "residual" else 2 * f


def basis_activations(
    basis: Basis,
    states: BlockStates,
    *,
    rotation: Tensor | None = None,
    sae: nn.Module | None = None,
    chunk_rows: int = 2048,
) -> Tensor:
    """The basis's pole activations at every residue of the batch, float32 and nonnegative."""
    # rotation: (f, f), for rotation bases only
    if states.block != basis.block:
        raise ValueError(f"States of block {states.block} cannot be read in a basis of block {basis.block}.")
    if basis.kind in ("native", "leak"):
        poles = swiglu_poles(states.gate, states.up)
        return poles.main() if basis.kind == "native" else poles.leaks()  # (r, 2f)
    if basis.kind == "sign":
        return sign_poles(states.product())  # (r, 2f)
    if basis.kind == "gate":
        return sign_poles(states.gate)  # (r, 2f)
    if basis.kind == "rotation":
        if rotation is None:
            raise ValueError(f"{basis.name} needs its rotation matrix.")
        return sign_poles(rotate(states.product(), rotation.to(states.gate.device, torch.float32)))  # (r, 2f)
    source = _source(basis, states)  # (r, d)
    if basis.kind == "residual":
        return sign_poles(source)  # (r, 2d)
    if sae is None:
        raise ValueError(f"{basis.name} needs its SAE layer.")
    codes = encode_topk(source, sae, chunk_rows=chunk_rows)  # indices, values: (r, k)
    dense = torch.zeros((source.shape[0], codes.codebook_dim), dtype=torch.float32, device=source.device)  # (r, c)
    return dense.scatter_(1, codes.indices, codes.values.float())  # (r, c)


def sae_firing_rates(basis: Basis, states: BlockStates, sae: nn.Module, *, chunk_rows: int = 2048) -> Tensor:
    """The share of residues at which each latent of an SAE basis is nonzero, counted from its top-k codes.

    Equal to `firing_rates.firing_rates(basis_activations(...))` without the dense (residues, latents) matrix, which a
    131,072-latent SAE cannot hold for every calibration residue (128 GiB, the e2_sweep pilot on 2026-11-07).
    """
    if basis.kind != "sae":
        raise ValueError(f"{basis.name} is not an SAE basis.")
    if states.block != basis.block:
        raise ValueError(f"States of block {states.block} cannot be read in a basis of block {basis.block}.")
    source = _source(basis, states)  # (r, d)
    codes = encode_topk(source, sae, chunk_rows=chunk_rows)  # indices, values: (r, k)
    fired = codes.indices[codes.values > 0]  # (e,), each residue's latents distinct
    return torch.bincount(fired, minlength=codes.codebook_dim).double() / source.shape[0]  # (c,)


def _source(basis: Basis, states: BlockStates) -> Tensor:
    """The stream or feed-forward write a residual or SAE basis reads."""
    source = states.stream if basis.reads == "stream" else states.write
    if source is None:
        raise ValueError(f"{basis.name} reads the {basis.reads}, which was not captured.")
    return source  # (r, d)
