"""Minimal, physics-checked trajectory analysis primitives."""
from .core import Trajectory
from .msd import mean_squared_displacement

__all__ = ["Trajectory", "mean_squared_displacement"]
