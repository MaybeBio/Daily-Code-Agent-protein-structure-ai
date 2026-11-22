"""E14b: are a block's units wired to single units of the block before it? Read from weights alone.

Tigges and colleagues (Goodfire, 2026) report that in a language model a neuron's input vector often lies along the
output vector of one neuron of the layer before, where it lies along no random direction of that layer's output. The
same reading here needs no data. A unit of block b + 1 reads the stream through the block's layer norm, so its gate and
up rows, scaled by the norm's gain, are the directions it reads; a unit of block b writes along its column of the down
projection. Per reading unit, the link is the largest absolute cosine with any writing unit of the block before, and
the control replaces those writing units by a Haar rotation of them, the same writes mixed. The layer norm removes each
residue's mean across dimensions, so both directions are compared with theirs removed.

Symbols: f units; d model width.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import torch

from collections.abc import Sequence
from torch import Tensor, nn

from .capture import DOWN_PROJECTION_INDEX
from .causal import transformer_blocks
from .rotations import haar_rotation


NORM_INDEX, PROJECTION_INDEX = 0, 1  # positions of the layer norm and of the gate-and-up projection inside a block's `ffn`
STRONG_LINK = 0.3  # Goodfire's mark for a strong link
ROTATION_SEEDS = (0, 1, 2)
SIDES = ("gate", "up")


def read_directions(block: nn.Module) -> dict[str, Tensor]:
    """The directions of the stream a block's units read through their gate and their up projection."""
    gain = block.ffn[NORM_INDEX].weight.detach().float()  # (d,)
    rows = block.ffn[PROJECTION_INDEX].weight.detach().float() * gain[None]  # (2f, d)
    gate, up = rows.chunk(2, dim=0)  # (f, d), (f, d): the SwiGLU's first half is the gate
    return {"gate": gate, "up": up}  # (f, d) each


def write_directions(block: nn.Module, rotation: Tensor | None = None) -> Tensor:
    """The direction each unit of a block writes along, or each rotated unit when a rotation is given."""
    # rotation: (f, f)
    down = block.ffn[DOWN_PROJECTION_INDEX].weight.detach().float()  # (d, f)
    return (down if rotation is None else down @ rotation.to(down.device, down.dtype)).T  # (f, d)


def strongest_links(reads: Tensor, writes: Tensor, chunk: int = 2048) -> Tensor:
    """Per reading direction, the largest absolute cosine with any writing direction, each with its mean across
    dimensions removed."""
    # reads: (f, d); writes: (f_w, d)
    reads = torch.nn.functional.normalize(reads - reads.mean(dim=1, keepdim=True), dim=1)  # (f, d)
    writes = torch.nn.functional.normalize(writes - writes.mean(dim=1, keepdim=True), dim=1)  # (f_w, d)
    return torch.cat([(reads[start:start + chunk] @ writes.T).abs().amax(dim=1) for start in range(0, len(reads), chunk)])  # (f,)


def wiring_table(model: nn.Module, rotation_seeds: Sequence[int] = ROTATION_SEEDS) -> pd.DataFrame:
    """Per pair of adjacent blocks, side and arm (the writing units, or a rotation of them): the share of reading units
    with a strong link, the links' quantiles, and the share of links above the largest link to any rotated unit of the
    pair, a mark that moves with the model's width as the fixed one does not."""
    blocks = transformer_blocks(model)
    units = blocks[0].ffn[DOWN_PROJECTION_INDEX].weight.shape[1]
    device = blocks[0].ffn[DOWN_PROJECTION_INDEX].weight.device
    rotations = {seed: haar_rotation(units, seed, dtype=torch.float32, device=device) for seed in rotation_seeds}  # (f, f)
    rows = []
    for writer in range(len(blocks) - 1):
        writes = {"native": write_directions(blocks[writer]),
                  **{f"rotation{seed}": write_directions(blocks[writer], rotation) for seed, rotation in rotations.items()}}
        for side, reads in read_directions(blocks[writer + 1]).items():  # (f, d)
            linked = {arm: strongest_links(reads, directions).cpu().numpy() for arm, directions in writes.items()}  # (f,) each
            ceiling = max(float(links.max()) for arm, links in linked.items() if arm != "native")
            for arm, links in linked.items():
                rows.append({"writer_block": writer, "reader_block": writer + 1, "side": side, "arm": arm, "units": len(links),
                             "strong_share": float((links > STRONG_LINK).mean()),
                             "above_rotations_share": float((links > ceiling).mean()), "median": float(np.median(links)),
                             "p90": float(np.quantile(links, 0.9)), "p99": float(np.quantile(links, 0.99)),
                             "max": float(links.max())})
    return pd.DataFrame(rows)


def wiring_summary(table: pd.DataFrame) -> dict[str, object]:
    """Per side: the native strong-link share over all pairs and its range across pairs, the same for the share of
    native links above every rotated link of their pair, the rotations' largest strong-link share at any pair, and the
    pairs at which the native strong-link share is above every rotation's."""
    summary: dict[str, object] = {}
    for side in SIDES:
        rows = table[table["side"] == side]
        native = rows[rows["arm"] == "native"].set_index("writer_block")
        rotated = rows[rows["arm"] != "native"]
        ceiling = rotated.groupby("writer_block")["strong_share"].max()
        summary[side] = {"pairs": int(len(native)), "native_strong_share": float(np.average(native["strong_share"], weights=native["units"])),
                         "native_strong_share_range": [float(native["strong_share"].min()), float(native["strong_share"].max())],
                         "native_above_rotations_share": float(np.average(native["above_rotations_share"], weights=native["units"])),
                         "native_above_rotations_share_range": [float(native["above_rotations_share"].min()),
                                                                float(native["above_rotations_share"].max())],
                         "native_median_link_range": [float(native["median"].min()), float(native["median"].max())],
                         "rotation_strong_share_max": float(rotated["strong_share"].max()),
                         "rotation_median_link_range": [float(rotated["median"].min()), float(rotated["median"].max())],
                         "rotation_max_link": float(rotated["max"].max()),
                         "pairs_native_above_every_rotation": int((native["strong_share"] > ceiling.reindex(native.index)).sum())}
    return summary
