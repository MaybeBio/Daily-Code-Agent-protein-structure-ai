"""The states every unit basis is read from, captured block by block during one ESMC forward pass.

Hooks on each requested block hand a consumer, once that block has run, its SwiGLU gate and up projections and, when
asked, its feed-forward write (the down projection's output, before the residual scaling) and the residual stream it
outputs. That stream is FastPLMs' hidden state `block + 1`, the input to the next block, which Biohub's layer `block + 1`
SAE reads. Every state is restricted to biological residues, concatenated protein by protein in batch order, before the
consumer sees it, and the pass stops after the deepest requested block, so reading block 59 of an 80-block model runs 60
blocks.

The gate is the first half of the SwiGLU's input and the up projection the second, as FastPLMs' `SwiGLU` applies SiLU to
the first half; `tests/test_units_capture.py` checks that SiLU(gate) * up reproduces the module's own output. These are
the states Protify's `interpretability.capture` names `mlp_gate`, `mlp_up`, `mlp_out` and `resid_post`.

Symbols: b sequences; l token columns; r residues of the batch; d model width; f units.
"""

from __future__ import annotations

import torch

from collections.abc import Callable, Collection, Sequence
from contextlib import suppress
from dataclasses import dataclass
from torch import Tensor, nn
from torch.nn import functional

from .causal import SWIGLU_INDEX, split_projection, transformer_blocks


DOWN_PROJECTION_INDEX = 3  # position of the down projection inside a block's `ffn`


@dataclass(frozen=True)
class BlockStates:
    """One block's states at the batch's biological residues, in the model's dtype."""

    block: int
    gate: Tensor  # (r, f)
    up: Tensor  # (r, f)
    write: Tensor | None = None  # (r, d), the feed-forward write before the residual scaling
    stream: Tensor | None = None  # (r, d), the block's output

    def product(self) -> Tensor:
        """z = SiLU(gate) * up in float32, the SwiGLU output each unit writes."""
        return functional.silu(self.gate.float()) * self.up.float()  # (r, f)


class _StopForward(Exception):
    """Raised after the deepest requested block, so the rest of the model never runs."""


class BlockReader:
    """Context manager holding the hooks; `run` makes one forward pass and calls `consumer` once per requested block,
    with the feed-forward write at `write_blocks` and the output stream at `stream_blocks`.

    The consumer must not keep the states: they are views of the batch's activations, released when the pass ends.
    """

    def __init__(
        self,
        model: nn.Module,
        blocks: Sequence[int],
        consumer: Callable[[BlockStates], None],
        *,
        write_blocks: Collection[int] = (),
        stream_blocks: Collection[int] = (),
    ) -> None:
        self.model = model
        self.transformer_blocks = transformer_blocks(model)
        self.blocks = tuple(sorted({int(block) for block in blocks}))
        if not self.blocks or self.blocks[0] < 0 or self.blocks[-1] >= len(self.transformer_blocks):
            raise ValueError(f"Blocks {list(blocks)} fall outside 0..{len(self.transformer_blocks) - 1}.")
        self.consumer = consumer
        self.write_blocks, self.stream_blocks = frozenset(write_blocks), frozenset(stream_blocks)
        if not (self.write_blocks | self.stream_blocks) <= set(self.blocks):
            raise ValueError("Writes and streams can only be read at requested blocks.")
        self._residues: Tensor | None = None
        self._pending: dict[int, dict[str, Tensor]] = {}
        self._handles: list[torch.utils.hooks.RemovableHandle] = []

    def __enter__(self) -> BlockReader:
        for block in self.blocks:
            module = self.transformer_blocks[block]
            self._handles.append(module.ffn[SWIGLU_INDEX].register_forward_pre_hook(self._swiglu_hook(block)))
            if block in self.write_blocks:
                self._handles.append(module.ffn[DOWN_PROJECTION_INDEX].register_forward_hook(self._write_hook(block)))
            self._handles.append(module.register_forward_hook(self._block_hook(block)))
        return self

    def __exit__(self, *exc: object) -> None:
        for handle in self._handles:
            handle.remove()
        self._handles.clear()

    def _keep(self, block: int, name: str, state: Tensor) -> None:
        # state: (b, l, w)
        if self._residues is None:
            raise RuntimeError("States arrived outside `BlockReader.run`.")
        self._pending.setdefault(block, {})[name] = state[self._residues]  # (r, w)

    def _swiglu_hook(self, block: int) -> Callable[[nn.Module, tuple[Tensor, ...]], None]:
        def hook(module: nn.Module, args: tuple[Tensor, ...]) -> None:
            # args: ((b, l, 2f),), the SwiGLU's input
            gate, up = split_projection(args[0])  # (b, l, f), (b, l, f)
            self._keep(block, "gate", gate)
            self._keep(block, "up", up)
        return hook  # reads (b, l, 2f) projections

    def _write_hook(self, block: int) -> Callable[[nn.Module, tuple[Tensor, ...], Tensor], None]:
        def hook(module: nn.Module, args: tuple[Tensor, ...], output: Tensor) -> None:
            # args: ((b, l, f),); output: (b, l, d)
            self._keep(block, "write", output)
        return hook  # reads (b, l, d) writes

    def _block_hook(self, block: int) -> Callable[[nn.Module, tuple[Tensor, ...], object], None]:
        def hook(module: nn.Module, args: tuple[Tensor, ...], output: object) -> None:
            # args: (b, l, d) inputs, unread; output: (b, l, d) or a tuple whose first item is (b, l, d)
            if block in self.stream_blocks:
                self._keep(block, "stream", output[0] if isinstance(output, tuple) else output)
            states = self._pending.pop(block, {})
            if "gate" not in states:
                raise RuntimeError(f"Block {block} ran without its SwiGLU hook firing.")
            self.consumer(BlockStates(block=block, **states))
            if block == self.blocks[-1]:
                raise _StopForward
        return hook  # hands (r, w) states to the consumer

    def run(self, input_ids: Tensor, attention_mask: Tensor, residues: Tensor) -> None:
        """One forward pass over a batch, consumed block by block and stopped after the deepest requested block."""
        # input_ids, attention_mask, residues: (b, l); residues marks biological residues
        if not self._handles:
            raise RuntimeError("Enter the BlockReader context before running it.")
        self._residues = residues.to(input_ids.device)
        self._pending.clear()
        try:
            # The deepest block's hook ends the pass by raising; the model's output is never needed.
            with suppress(_StopForward), torch.inference_mode():
                self.model(input_ids=input_ids, attention_mask=attention_mask)
        finally:
            self._residues = None
        if self._pending:
            raise RuntimeError(f"Blocks {sorted(self._pending)} never completed.")


def residue_mask(attention_mask: Tensor, lengths: Tensor) -> Tensor:
    """Biological residues of a right-padded batch with one leading BOS token: columns 1 to each length."""
    # attention_mask: (b, l); lengths: (b,)
    if not torch.equal(attention_mask.sum(dim=1), lengths.to(attention_mask.device) + 2):
        raise ValueError("The tokenizer did not add exactly one BOS and one EOS token around one token per residue.")
    columns = torch.arange(attention_mask.shape[1], device=attention_mask.device).unsqueeze(0)  # (1, l)
    return (columns >= 1) & (columns <= lengths.to(attention_mask.device).unsqueeze(1))  # (b, l)
