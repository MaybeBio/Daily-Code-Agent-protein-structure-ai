"""Shared trajectory contract; coordinates must already be unwrapped."""
from dataclasses import dataclass
from typing import Protocol
import numpy as np

@dataclass(frozen=True)
class Trajectory:
    """Positions (frames, atoms, 3), time in ps, positions in angstrom.

    Atom order must be stable across frames. Periodic image reconstruction
    is the caller's responsibility; wrapped coordinates are rejected.
    """
    positions: np.ndarray
    times: np.ndarray
    unwrapped: bool = False

    def __post_init__(self):
        p = np.array(self.positions, dtype=float, copy=True)
        t = np.array(self.times, dtype=float, copy=True)
        if p.ndim != 3 or p.shape[2] != 3 or min(p.shape[:2]) < 1:
            raise ValueError("positions must have shape (frames>=1, atoms>=1, 3)")
        if t.shape != (p.shape[0],):
            raise ValueError("times must contain one value per frame")
        if not np.isfinite(p).all() or not np.isfinite(t).all():
            raise ValueError("positions and times must be finite")
        if np.any(np.diff(t) <= 0):
            raise ValueError("times must be strictly increasing")
        if self.unwrapped is not True:
            raise ValueError("explicitly confirm unwrapped coordinates")
        p.setflags(write=False)
        t.setflags(write=False)
        object.__setattr__(self, "positions", p)
        object.__setattr__(self, "times", t)

class AnalysisPlugin(Protocol):
    """Initial callable interface; no discovery/registration system yet."""
    def __call__(self, trajectory: Trajectory) -> dict[str, np.ndarray]: ...
