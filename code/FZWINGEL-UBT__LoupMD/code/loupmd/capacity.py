"""The capacity mode (plan task S5-T05): a single-point evaluation that runs the whole-system call when the
system fits the GPU and the tiled call when it does not.

The engine plans the execution (``loup_plan_execution``): one probe tile of at most 4,096 receivers measures the
workspace per row and per edge, the whole-system call is chosen when it fits in ``memory_fraction`` of the memory
free for it, and otherwise the tiled call with the largest receiver cap of 4,096 to 65,536 that fits. A mode or a
cap set in :class:`~loupmd.config.CapacityConfig` is kept as given.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import _core
from .config import CapacityConfig
from .errors import PlanRefused


@dataclass(frozen=True)
class CapacityResult:
    """Energy (eV), forces (eV/A, [n, 3]) and stress (eV/A^3, [3, 3]) with the execution that produced them."""

    energy: float
    forces: np.ndarray
    stress: np.ndarray
    mode: str               # "whole", "tiled" or "wavefront" (the tiled call with the wavefront schedule, S5-T08)
    receivers: int          # receiver cap of the tiled call; 0 for the whole-system call
    tiles: int
    plan: _core.MemoryPlan
    budget_bytes: int       # device memory free for the call (the handle's own buffers included)
    peak_bytes: int         # tiled: measured device peak of the call; whole: the plan's estimate


def evaluate(engine, atoms, config: CapacityConfig | None = None, skin: float = 0.5) -> CapacityResult:
    """Evaluate ``atoms`` (periodic) on ``engine`` (a ``LoupEngine``) in the mode the capacity plan chooses. The
    handle afterwards holds the system (whole) or the tile workspace (tiled): call ``set_system`` before other
    calls."""
    config = config or CapacityConfig()
    reasons = []
    if config.state == "host":
        reasons.append("state='host' (the tiled state in pinned host memory) is not in this version (plan task S5-T07)")
    if reasons:
        raise PlanRefused(reasons, next_step="Use state 'auto' or 'device'.")
    numbers = np.asarray(atoms.get_atomic_numbers())
    positions, cell = np.asarray(atoms.positions), np.asarray(atoms.cell.array)
    engine.set_execution(config.exec_mode, config.receivers or 0, config.memory_fraction)
    plan = engine.plan_execution(numbers, positions, cell, skin)
    if plan.mode == _core.LOUP_EXEC_WHOLE:
        engine.set_system(numbers, atoms.get_masses(), skin=skin)
        energy, forces, stress = engine.evaluate(positions, cell)
        return CapacityResult(energy, forces, stress, "whole", 0, 1, plan, plan.free_bytes, plan.whole_bytes)
    energy, forces, stress, tiles = engine.evaluate_tiled(numbers, positions, cell, plan.receivers, skin=skin)
    done = engine.last_execution()
    mode = "wavefront" if done.mode == _core.LOUP_EXEC_WAVEFRONT else "tiled"
    return CapacityResult(energy, forces, stress, mode, plan.receivers, tiles, plan, done.budget_bytes,
                          done.peak_bytes)


@dataclass(frozen=True)
class NVEResult:
    """A constant-energy run of :func:`run_nve`: energies (eV) every ``every`` steps and the final state."""

    times_ps: np.ndarray
    potential: np.ndarray
    kinetic: np.ndarray
    positions: np.ndarray
    velocities: np.ndarray   # ASE units
    mode: str
    receivers: int
    tiles: int
    list_builds: int         # tiled: calls that built their tile lists (the first and one per skin/2 crossing)
    seconds_per_step: float  # wall time per step after the first force call

    @property
    def total(self) -> np.ndarray:
        return self.potential + self.kinetic

    def drift_mev_per_atom_ps(self, n_atoms: int) -> float:
        """Slope of the total energy, meV per atom per ps (least squares)."""
        return float(np.polyfit(self.times_ps, self.total / n_atoms * 1e3, 1)[0])


def run_nve(engine, atoms, n_steps: int, dt_fs: float = 1.0, config: CapacityConfig | None = None,
            skin: float = 0.5, every: int = 10) -> NVEResult:
    """Velocity Verlet on the host with forces from the capacity plan's call (plan task S5-T06): the whole-system
    call when the system fits, else the tiled call, whose tile lists the engine keeps until an atom has moved
    skin/2. ``atoms`` gives positions, velocities (ASE units) and masses; the cell stays fixed. The integrator on the
    device in tiled mode is a later step (PLAN.md D63)."""
    from ase import units

    if n_steps < 0 or every <= 0:
        raise PlanRefused([f"n_steps must not be negative and every positive, got {n_steps} and {every}"])
    numbers = np.asarray(atoms.get_atomic_numbers())
    cell = np.asarray(atoms.cell.array)
    first = evaluate(engine, atoms, config, skin=skin)
    builds0 = engine.last_execution().list_builds if first.mode != "whole" else 0
    if first.mode == "whole":
        def force(x):
            e, f, _ = engine.evaluate(x, cell, compute_stress=False)
            return e, f
    else:
        def force(x):
            e, f, _, _ = engine.evaluate_tiled(numbers, x, cell, first.receivers, skin=skin)
            return e, f
    m = np.asarray(atoms.get_masses(), dtype=np.float64)[:, None]
    x = np.array(atoms.positions, dtype=np.float64)
    v = np.array(atoms.get_velocities(), dtype=np.float64)
    e, f = first.energy, first.forces
    dt = dt_fs * units.fs
    times, pot, kin = [0.0], [e], [0.5 * float(np.sum(m * v * v))]
    import time

    t0 = time.perf_counter()
    for step in range(1, n_steps + 1):
        v += 0.5 * dt * f / m
        x += dt * v
        e, f = force(x)
        v += 0.5 * dt * f / m
        if step % every == 0 or step == n_steps:
            times.append(step * dt_fs * 1e-3)
            pot.append(e)
            kin.append(0.5 * float(np.sum(m * v * v)))
    wall = (time.perf_counter() - t0) / max(n_steps, 1)
    builds = engine.last_execution().list_builds - builds0 + 1 if first.mode != "whole" else 0
    return NVEResult(np.array(times), np.array(pot), np.array(kin), x, v, first.mode, first.receivers, first.tiles,
                     builds, wall)
