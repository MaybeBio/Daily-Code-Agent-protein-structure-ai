"""Interventions that ask whether ESMC uses the units we label, read through its own masked-token prediction.

Each intervention is a context manager that registers forward hooks on an ESMC (FastPLMs ESM++) model and removes them
on exit, so the model is never left altered. A block's feed-forward branch is `Sequential(LayerNorm, Linear(d, 2f),
SwiGLU, Linear(f, d))`; the hooks read the SwiGLU's input (the gate and up projections) and replace its output z.

- `PoleAblation`: at chosen residues, where one pole of one unit fires, replace z by a value (the unit's mean over
  residues where the pole does not fire, from calibration), as a mean ablation conditioned on the pole.
- `ActivationRemoval`: network-wide, zero each unit's activations below a per-unit magnitude threshold (the weakest
  share) or above one (the strongest share), as in Cammarata's weak-against-strong test.
- `stream_shift`: add an offset to the residual stream entering a block at chosen residues, for steering along a fitted
  manifold or a straight line; `stream_reading` keeps that stream instead.

Symbols: b sequences; l token columns; d model width; f units.
"""

from __future__ import annotations

import torch

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from torch import Tensor, nn
from torch.nn import functional


SWIGLU_INDEX = 2  # position of the SwiGLU module inside a block's `ffn`


def transformer_blocks(model: nn.Module) -> nn.ModuleList:
    """The blocks of an ESM++ model, wherever the transformer sits."""
    for module in model.modules():
        blocks = getattr(module, "blocks", None)
        if isinstance(blocks, nn.ModuleList) and len(blocks) and hasattr(blocks[0], "ffn"):
            return blocks
    raise ValueError("No transformer with feed-forward blocks was found in the model.")


def split_projection(projection: Tensor) -> tuple[Tensor, Tensor]:
    """The SwiGLU's input as its gate (the first half, SiLU's input) and its up projection (the second half)."""
    # projection: (b, l, 2f), the SwiGLU's input
    gate, up = projection.chunk(2, dim=-1)  # (b, l, f), (b, l, f)
    return gate, up  # (b, l, f), (b, l, f)


@dataclass(frozen=True)
class PoleTarget:
    """One pole of one unit and what its ablation writes in its place."""

    block: int
    unit: int
    sign: str  # "positive" or "negative"
    value: float  # the product z written where the pole fires at the chosen residues

    def __post_init__(self) -> None:
        if self.sign not in ("positive", "negative"):
            raise ValueError(f"A pole's sign is positive or negative, not {self.sign!r}.")


@contextmanager
def pole_ablation(model: nn.Module, targets: Sequence[PoleTarget], residues: Tensor) -> Iterator[None]:
    """Ablate each target pole at the chosen residues while the context is open.

    `residues` (b, l) marks where ablation applies; outside it, and wherever the pole does not fire, z is untouched.
    """
    # residues: (b, l) bool
    blocks = transformer_blocks(model)
    by_block: dict[int, list[PoleTarget]] = {}
    for target in targets:
        by_block.setdefault(target.block, []).append(target)
    handles = []

    def hook_for(block_targets: list[PoleTarget]) -> Callable[[nn.Module, tuple[Tensor, ...], Tensor], Tensor]:
        def hook(module: nn.Module, args: tuple[Tensor, ...], output: Tensor) -> Tensor:
            # args: ((b, l, 2f),), the SwiGLU's input; output: (b, l, f)
            gate, up = split_projection(args[0])  # (b, l, f), (b, l, f)
            edited = output.clone()  # (b, l, f)
            chosen = residues.to(output.device)  # (b, l)
            for target in block_targets:
                fires = (gate[..., target.unit] > 0) & ((up[..., target.unit] > 0) if target.sign == "positive" else (up[..., target.unit] < 0))  # (b, l)
                mask = fires & chosen  # (b, l)
                edited[..., target.unit] = torch.where(mask, torch.full_like(edited[..., target.unit], target.value), edited[..., target.unit])
            return edited  # (b, l, f)
        return hook  # edits (b, l, f) products

    try:
        for block, block_targets in by_block.items():
            handles.append(blocks[block].ffn[SWIGLU_INDEX].register_forward_hook(hook_for(block_targets)))
        yield
    finally:
        for handle in handles:
            handle.remove()


@contextmanager
def activation_removal(model: nn.Module, lower: dict[int, Tensor] | None = None, upper: dict[int, Tensor] | None = None) -> Iterator[None]:
    """Zero, in each listed block, every unit's |z| at or below `lower[block]` and at or above `upper[block]`.

    Thresholds are per unit, (f,), from calibration residues: the weakest-share test passes `lower`, the strongest-share
    test passes `upper`.
    """
    blocks = transformer_blocks(model)
    # lower, upper: (f,) per listed block
    lower, upper = lower or {}, upper or {}
    handles = []

    def hook_for(block: int) -> Callable[[nn.Module, tuple[Tensor, ...], Tensor], Tensor]:
        def hook(module: nn.Module, args: tuple[Tensor, ...], output: Tensor) -> Tensor:
            # args: ((b, l, 2f),); output: (b, l, f)
            magnitude = output.abs().float()  # (b, l, f)
            remove = torch.zeros_like(magnitude, dtype=torch.bool)  # (b, l, f)
            if block in lower:
                remove |= magnitude <= lower[block].to(output.device)
            if block in upper:
                remove |= magnitude >= upper[block].to(output.device)
            return torch.where(remove, torch.zeros_like(output), output)  # (b, l, f)
        return hook  # edits (b, l, f) products

    try:
        for block in sorted(set(lower) | set(upper)):
            handles.append(blocks[block].ffn[SWIGLU_INDEX].register_forward_hook(hook_for(block)))
        yield
    finally:
        for handle in handles:
            handle.remove()


@contextmanager
def stream_shift(model: nn.Module, block: int, residues: Tensor, offsets: Tensor) -> Iterator[None]:
    """Add `offsets` to the residual stream entering `block` at the chosen residues, in order of the chosen residues
    (row by row), on every forward pass while the context is open."""
    # residues: (b, l) bool; offsets: (s, d) with s the number of chosen residues
    blocks = transformer_blocks(model)

    def hook(module: nn.Module, args: tuple[Tensor, ...], kwargs: dict[str, object]) -> tuple[tuple[Tensor, ...], dict[str, object]]:
        # args: ((b, l, d), ...) unless the stream comes as the keyword x
        stream = kwargs["x"] if "x" in kwargs else args[0]
        chosen = residues.to(stream.device)  # (b, l)
        edited = stream.clone()  # (b, l, d)
        edited[chosen] = (stream[chosen].float() + offsets.to(stream.device).float()).to(stream.dtype)
        if "x" in kwargs:
            return args, {**kwargs, "x": edited}  # the stream (b, l, d) edited
        return (edited, *args[1:]), kwargs  # the stream (b, l, d) edited

    handle = blocks[block].register_forward_pre_hook(hook, with_kwargs=True)
    try:
        yield
    finally:
        handle.remove()


@contextmanager
def stream_reading(model: nn.Module, block: int, residues: Tensor, kept: list[Tensor]) -> Iterator[None]:
    """Append the residual stream entering `block` at the chosen residues, row by row, in float32 on the CPU, to `kept`
    on every forward pass while the context is open."""
    # residues: (b, l) bool; kept: (s, d) tensors, one appended per pass
    blocks = transformer_blocks(model)

    def hook(module: nn.Module, args: tuple[Tensor, ...], kwargs: dict[str, object]) -> None:
        # args: ((b, l, d), ...) unless the stream comes as the keyword x
        stream = kwargs["x"] if "x" in kwargs else args[0]
        kept.append(stream[residues.to(stream.device)].float().cpu())  # (s, d)

    handle = blocks[block].register_forward_pre_hook(hook, with_kwargs=True)
    try:
        yield
    finally:
        handle.remove()


def nonfiring_means(gate: Tensor, up: Tensor) -> Tensor:
    """Each pole's ablation value: its unit's mean product z over the residues where that pole does not fire, in the
    `poles.SwigluPoles.main` layout (positive poles, then negative)."""
    # gate, up: (r, f), calibration residues of one block
    product = functional.silu(gate.double()) * up.double()  # (r, f)
    is_open = gate > 0  # (r, f)
    means = []
    for fires in (is_open & (up > 0), is_open & (up < 0)):  # (r, f) each
        quiet = (~fires).double()  # (r, f)
        means.append((product * quiet).sum(dim=0) / quiet.sum(dim=0).clamp(min=1))  # (f,)
    return torch.cat(means)  # (2f,)


@torch.inference_mode()
def masked_readout(model: nn.Module, input_ids: Tensor, attention_mask: Tensor, positions: Tensor, mask_token_id: int) -> tuple[Tensor, Tensor]:
    """The log probability of the true token at each chosen position, and whether it is the top prediction, with those
    positions masked in one forward pass."""
    # input_ids, attention_mask: (b, l); positions: (b, l) bool
    masked = input_ids.masked_fill(positions, mask_token_id)  # (b, l)
    logits = model(input_ids=masked, attention_mask=attention_mask).logits.float()  # (b, l, v)
    log_probs = functional.log_softmax(logits, dim=-1)  # (b, l, v)
    true = log_probs.gather(-1, input_ids.unsqueeze(-1)).squeeze(-1)[positions]  # (s,)
    correct = (logits.argmax(dim=-1) == input_ids)[positions]  # (s,)
    return true, correct  # (s,), (s,)


def magnitude_thresholds(products: Tensor, weakest: float) -> tuple[Tensor, Tensor]:
    """Per unit: the |z| quantile at `weakest` (removing at or below it drops the weakest share), and the |z| above
    which the strongest residues carry the same total magnitude as the weakest share, so both tests remove equal mass."""
    # products: (r, f), calibration residues of one block
    magnitude = products.abs().double()  # (r, f)
    ascending = torch.sort(magnitude, dim=0).values  # (r, f)
    count = int(round(weakest * magnitude.shape[0]))
    lower = ascending[max(count - 1, 0)]  # (f,)
    weak_mass = ascending[:count].sum(dim=0)  # (f,)
    descending = ascending.flip(0)  # (r, f)
    cumulative = descending.cumsum(dim=0)  # (r, f)
    # The first rank at which the strongest residues' cumulative magnitude reaches the weak mass.
    reach = (cumulative >= weak_mass.unsqueeze(0)).double().argmax(dim=0)  # (f,)
    upper = descending.gather(0, reach.unsqueeze(0)).squeeze(0)  # (f,)
    # A unit whose weakest share carries no magnitude loses nothing in the strongest-share test either.
    upper = torch.where(weak_mass > 0, upper, torch.full_like(upper, float("inf")))  # (f,)
    return lower, upper  # (f,), (f,)
