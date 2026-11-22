"""Heads attached to the encoder: one per pretraining target, plus the ddG head."""
import torch
import torch.nn as nn
from torch import Tensor

from ..data.graph import N_TOKENS
from .encoder import mlp

N_AMINO_ACIDS = 20


class LetterHead(nn.Module):
    """Arm C: which amino acid was hidden here?"""

    def __init__(self, dim: int) -> None:
        super().__init__()
        self.net = nn.Linear(dim, N_AMINO_ACIDS)

    def forward(self, z: Tensor) -> Tensor:
        """z: [M, dim] -> [M, 20] logits"""
        return self.net(z)


class Predictor(nn.Module):
    """Arm B: map a masked node's embedding onto the teacher's embedding of it.

    Kept separate from the encoder and thrown away afterwards, as I-JEPA does, so that the
    encoder is not shaped by having to match the teacher exactly.
    """

    def __init__(self, dim: int, hidden: int | None = None,
                 layers: int = 2, dropout: float = 0.0) -> None:
        super().__init__()
        hidden = hidden or 2 * dim
        self.net = mlp([dim] + [hidden] * layers + [dim], dropout)

    def forward(self, z: Tensor) -> Tensor:
        """z: [M, dim] -> [M, dim]"""
        return self.net(z)


class DDGHead(nn.Module):
    """(residue embedding, wild-type letter, mutant letter) -> ddG."""

    def __init__(self, dim: int, hidden: int = 256, layers: int = 2,
                 aa_dim: int = 32, dropout: float = 0.1) -> None:
        super().__init__()
        self.aa = nn.Embedding(N_TOKENS, aa_dim)
        sizes = [dim + 2 * aa_dim] + [hidden] * layers + [1]
        self.net = mlp(sizes, dropout)

    def forward(self, z: Tensor, wt_aa: Tensor, mut_aa: Tensor) -> Tensor:
        """z: [M, dim], wt_aa/mut_aa: [M] -> [M]"""
        x = torch.cat([z, self.aa(wt_aa), self.aa(mut_aa)], dim=-1)
        return self.net(x).squeeze(-1)


class DDGModel(nn.Module):
    """Encoder plus ddG head, evaluated at the mutated positions.

    One encoder pass covers a whole protein, and every mutation of that protein reads its
    own residue embedding from it.
    """

    def __init__(self, encoder: nn.Module, head: nn.Module,
                 freeze_encoder: bool = False) -> None:
        super().__init__()
        self.encoder = encoder
        self.head = head
        self.freeze_encoder = freeze_encoder
        if freeze_encoder:
            for p in self.encoder.parameters():
                p.requires_grad = False

    def train(self, mode=True):
        super().train(mode)
        if self.freeze_encoder:
            self.encoder.eval()          # a frozen encoder keeps dropout off
        return self

    def forward(self, batch) -> Tensor:
        with torch.set_grad_enabled(not self.freeze_encoder and torch.is_grad_enabled()):
            z = self.encoder.encode(batch)
        return self.head(z[batch.mut_node], batch.mut_wt, batch.mut_aa)
