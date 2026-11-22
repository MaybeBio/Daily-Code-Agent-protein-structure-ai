"""Hiding residues for the pretraining task.

We replace the residue type of a fifth of the residues with a learned mask token and leave
the structure untouched, so the question put to the model is "what belongs at this position
given its surroundings". The geometry carries no residue identity (see features.py), so the
answer cannot be read off the inputs.
"""
import torch
from torch import Tensor

from ..models.encoder import MASK

MASK_RATE = 0.2


def sample_mask(batch, rate: float = MASK_RATE,
                generator: torch.Generator | None = None) -> Tensor:
    """-> bool [N] on the batch's device. Every graph gets at least one masked residue.

    The draw happens on the cpu so that a seed gives the same masks whatever the model is
    training on.
    """
    assignment = batch.batch.cpu()
    draw = torch.rand(batch.num_nodes, generator=generator)
    mask = draw < rate

    counts = torch.zeros(batch.num_graphs, dtype=torch.long)
    counts.index_add_(0, assignment, mask.long())
    for graph in (counts == 0).nonzero(as_tuple=True)[0]:
        nodes = (assignment == graph).nonzero(as_tuple=True)[0]
        mask[nodes[draw[nodes].argmin()]] = True
    return mask.to(batch.x.device)


def apply_mask(batch, mask: Tensor) -> tuple[Tensor, Tensor]:
    """Replace the masked residue types with the mask token, leaving the batch unchanged.

    -> (x with the mask applied, the true residue types at the masked positions)
    """
    x = batch.x.clone()
    targets = x[mask].clone()
    x[mask] = MASK
    return x, targets
