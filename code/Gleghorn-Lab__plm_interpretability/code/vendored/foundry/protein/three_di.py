"""Per-residue 3Di states predicted from a protein language model's per-residue views, so a search that takes only amino
acids can still score by Foldseek's 3Di+AA. The head reads two views of each residue (ESMC's layer-23 hidden state and
its structural stream, as Atlas v3's `SequenceViews` carries them); alignment_atlas trains it (`three_di.py`) and the
search service runs it on the same views.

Symbols: b sequences, l view rows (CLS, the residues, EOS), a hidden width, s structural width, w head width.
"""

from __future__ import annotations

import torch

from typing import Protocol
from torch import nn

from foundry.protein.gpu_alignment import RESIDUES


STATES = len(RESIDUES)  # Foldseek's 3Di alphabet has 20 letters, encoded in `RESIDUES` order like the amino acids


class Views(Protocol):
    """What the head reads of a batch: Atlas v3's `SequenceViews` is one."""

    hidden: torch.Tensor  # (b, l, a)
    summary: torch.Tensor  # (b, l, s)
    mask: torch.Tensor  # (b, l) bool, True on real rows


class ThreeDiHead(nn.Module):
    """Per-residue 3Di logits from the two views: (b, l, 20), CLS and EOS rows included (callers drop them)."""

    def __init__(self, hidden_width: int, summary_width: int, width: int = 512, kernel: int = 5, blocks: int = 0) -> None:
        super().__init__()
        self.config = {"hidden_width": hidden_width, "summary_width": summary_width, "width": width, "kernel": kernel,
                       "blocks": blocks}
        self.hidden_norm, self.summary_norm = nn.LayerNorm(hidden_width), nn.LayerNorm(summary_width)
        self.project = nn.Linear(hidden_width + summary_width, width)
        self.convolve = nn.Conv1d(width, width, kernel, padding=kernel // 2) if kernel > 1 else None
        # Transformer blocks over the residues, for states set by contacts far along the chain; none by default.
        self.blocks = nn.ModuleList([nn.TransformerEncoderLayer(width, 8, 4 * width, 0.1, activation="gelu", batch_first=True,
                                                                norm_first=True) for _ in range(blocks)])
        self.classify = nn.Sequential(nn.GELU(), nn.Linear(width, width), nn.GELU(), nn.Linear(width, STATES))

    def forward(self, views: Views) -> torch.Tensor:
        mask = views.mask[..., None]  # (b, l, 1)
        joined = torch.cat((self.hidden_norm(views.hidden.float()), self.summary_norm(views.summary.float())), dim=-1)  # (b, l, a + s)
        x = self.project(joined).masked_fill(~mask, 0)  # (b, l, w)
        if self.convolve is not None:
            x = x + self.convolve(x.transpose(1, 2)).transpose(1, 2).masked_fill(~mask, 0)  # (b, l, w)
        for block in self.blocks:
            x = block(x, src_key_padding_mask=~views.mask).masked_fill(~mask, 0)  # (b, l, w)
        return self.classify(x)  # (b, l, 20)
