"""The neighbour-list skin of an MD run, chosen from how far atoms move per step (``skin="auto"``).

The engine's run loop is fastest in its pipelined mode, which it enters while four times the largest distance an
atom moves in one step stays below half the skin (``src/engine.cu``, ``run_md_loop``). The engine's default skin of
0.5 A covers heavy atoms at any usual timestep; hydrogen at 300 K moves about 0.08 A per 1 fs step and needs about
1 A. A larger skin costs neighbours, so it is not simply made large: the skin is eight times the largest step with
a margin, at least 0.5 A and at most 1.5 A (the largest value with a measurement on file: water at 300 K ran 2.90
ms/step at 1.5 A against 3.13 at 0.5 A).

The choice never changes a result: the engine checks its neighbour list against the skin in every step, in either
loop. It decides speed only.
"""
from __future__ import annotations

import math

SKIN_MIN_A = 0.5          # the engine's default
SKIN_MAX_A = 1.5
SKIN_STEPS = 8.0          # the pipelined loop needs 4 x (largest step) < skin / 2
SKIN_MARGIN = 1.25
SKIN_GRID_A = 0.05
EXTREME_SPEED = 5.0       # the fastest atom of a thermal system, in units of sqrt(kT / m) of the lightest atom
PROBE_STEPS = 200         # steps before the measured step size replaces the estimate
PROBE_TARGET_FRACTION = 0.8   # of the run's highest target that must be reached before the measurement counts
GROW_BY_A, SHRINK_BY_A = 0.05, 0.2   # the skin is changed when the measurement asks for this much more or less


def skin_for_step(step_A: float) -> float:
    """The skin for a largest per-step displacement, on a 0.05 A grid within [0.5, 1.5] A."""
    wanted = SKIN_STEPS * SKIN_MARGIN * float(step_A)
    on_grid = math.ceil(wanted / SKIN_GRID_A - 1e-9) * SKIN_GRID_A
    return round(min(SKIN_MAX_A, max(SKIN_MIN_A, on_grid)), 2)


def estimate_step_A(atoms, timestep_fs: float, temperature_K=None, fixed=None) -> float:
    """The largest distance an atom is expected to move in one step, before anything has run: the fastest atom
    now, or the thermal estimate ``5 sqrt(kT / m_min) dt`` at ``temperature_K`` if that is larger."""
    import numpy as np
    from ase import units

    dt = float(timestep_fs) * units.fs
    masses = np.asarray(atoms.get_masses(), dtype=float)
    velocities = np.asarray(atoms.get_velocities(), dtype=float)
    if fixed is not None:
        masses, velocities = masses[~fixed], velocities[~fixed]
    now = float(np.sqrt((velocities ** 2).sum(axis=1).max())) * dt if len(masses) else 0.0
    thermal = 0.0
    if temperature_K and len(masses):
        thermal = EXTREME_SPEED * math.sqrt(units.kB * float(temperature_K) / float(masses.min())) * dt
    return max(now, thermal)


def adjusted(current_A: float, measured_step_A: float):
    """The skin a measured largest step asks for, or ``None`` when the current one is close enough: it grows as
    soon as more is needed and shrinks only when 0.2 A could be saved."""
    wanted = skin_for_step(measured_step_A)
    if wanted >= current_A + GROW_BY_A - 1e-9 or wanted <= current_A - SHRINK_BY_A + 1e-9:
        return wanted
    return None
