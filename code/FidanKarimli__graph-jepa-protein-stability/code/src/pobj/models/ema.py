"""The teacher that produces arm B's targets.

A frozen copy of the student that trails it, updated as a weighted average rather than by
gradient descent. It reads the unmasked graph, so its embedding at a hidden position is
what the student is asked to predict. Using the student itself as its own target is what
makes the task self-referential, and the lag plus the stop-gradient is what stops the pair
from agreeing on a constant.
"""
import copy

import torch
import torch.nn as nn
from torch import Tensor


class EMATeacher(nn.Module):
    def __init__(self, student: nn.Module, momentum_start: float = 0.99,
                 momentum_end: float = 0.9999, total_steps: int = 1) -> None:
        super().__init__()
        self.encoder = copy.deepcopy(student)
        for p in self.encoder.parameters():
            p.requires_grad = False
        self.start = momentum_start
        self.end = momentum_end
        self.total_steps = max(1, total_steps)
        self.steps = 0

    def momentum(self) -> float:
        """Rises from start to end, so the teacher moves freely early and settles later."""
        fraction = min(1.0, self.steps / self.total_steps)
        return self.start + (self.end - self.start) * fraction

    @torch.no_grad()
    def update(self, student: nn.Module) -> None:
        m = self.momentum()
        for teacher_p, student_p in zip(self.encoder.parameters(), student.parameters()):
            teacher_p.mul_(m).add_(student_p.detach(), alpha=1 - m)
        for teacher_b, student_b in zip(self.encoder.buffers(), student.buffers()):
            teacher_b.copy_(student_b)
        self.steps += 1

    @torch.no_grad()
    def forward(self, batch) -> Tensor:
        """The targets: the teacher's view of the graph with nothing hidden."""
        self.encoder.eval()
        return self.encoder.encode(batch).detach()
