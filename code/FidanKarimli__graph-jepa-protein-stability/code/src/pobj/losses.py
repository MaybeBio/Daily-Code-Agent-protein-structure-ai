"""The two pretraining losses, and the combination used by arm D."""
import torch.nn.functional as F
from torch import Tensor


def letter_loss(logits: Tensor, targets: Tensor) -> Tensor:
    """Arm C. logits: [M, 20], targets: [M] -> scalar"""
    return F.cross_entropy(logits, targets)


def vector_loss(predicted: Tensor, target: Tensor) -> Tensor:
    """Arm B. Both [M, dim] -> scalar.

    One minus cosine similarity, so only the direction of the embedding is matched. The
    target carries no gradient; it comes from the teacher.
    """
    return (1 - F.cosine_similarity(predicted, target.detach(), dim=-1)).mean()


def combined(letter: Tensor, vector: Tensor, lam: float) -> Tensor:
    """Arm D."""
    return letter + lam * vector
