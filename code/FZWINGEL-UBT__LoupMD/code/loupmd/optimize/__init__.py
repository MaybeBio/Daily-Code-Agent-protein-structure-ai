"""``lm.optimize``: structure relaxation with ASE 3.27's optimisers.

The records take ASE's arguments and defaults under FastMACE's names (``fm.optimize``); lengths are in A. ``relax``
runs one until the largest force on an atom is below ``fmax``. Atoms under ASE's ``FixAtoms`` do not move.

Where the steps are taken: LBFGS at fixed cell runs on the GPU inside the engine (``loup_minimize``: the history
and its products on the device, so a step costs little more than its force call). FIRE, and every relaxation with
``cell_filter=FrechetCell(...)``, takes its steps on host arrays around the engine's force call. Both give ASE's
steps. With the cell filter the cell is relaxed with the positions (ASE's ``FrechetCellFilter``, pressure in
GPa); it is refused with fixed atoms and for models with long-range terms (MACE-POLAR-1), as in FastMACE.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

from ..errors import InputError, NonFiniteError, PlanRefused

__all__ = ["FIRE", "LBFGS", "RECORDS", "FrechetCell", "RelaxResult", "relax"]


def _number(record, name, *, positive=False, minimum=None):
    value = getattr(record, name)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise InputError(f"{type(record).__name__}.{name} must be a finite number, got {value!r}")
    if positive and value <= 0:
        raise InputError(f"{type(record).__name__}.{name} must be positive, got {value!r}")
    if minimum is not None and value < minimum:
        raise InputError(f"{type(record).__name__}.{name} must be at least {minimum}, got {value!r}")


def _flag(record, name):
    if not isinstance(getattr(record, name), bool):
        raise InputError(f"{type(record).__name__}.{name} must be a bool, got {getattr(record, name)!r}")


@dataclass(frozen=True, kw_only=True)
class FrechetCell:
    """ASE 3.27's ``FrechetCellFilter``: positions and the log of the deformation gradient relaxed together.

    ``scalar_pressure_GPa`` is ASE's ``scalar_pressure`` in GPa; ``hydrostatic_strain``, ``constant_volume``,
    ``mask`` (six Voigt flags or a 3x3 of flags) and ``exp_cell_factor`` (``None``: the number of atoms) as ASE's.
    """

    scalar_pressure_GPa: float = 0.0
    hydrostatic_strain: bool = False
    constant_volume: bool = False
    mask: tuple | None = None
    exp_cell_factor: float | None = None

    def __post_init__(self):
        _number(self, "scalar_pressure_GPa")
        _flag(self, "hydrostatic_strain")
        _flag(self, "constant_volume")
        if self.exp_cell_factor is not None:
            _number(self, "exp_cell_factor", positive=True)
        if self.mask is not None:
            mask = tuple(tuple(row) if isinstance(row, (list, tuple)) else row for row in self.mask)
            flat = [flag for row in mask for flag in (row if isinstance(row, tuple) else (row,))]
            shape_ok = (len(mask) == 6 and len(flat) == 6) or (len(mask) == 3 and len(flat) == 9)
            if not shape_ok or any(isinstance(flag, bool) or flag not in (0, 1) for flag in flat):
                raise InputError(f"FrechetCell.mask must be six Voigt 0/1 flags or a 3x3 of 0/1 flags, got "
                                 f"{self.mask!r}")
            object.__setattr__(self, "mask", mask)

    def view(self, atoms):
        from ase import units

        from .cell import FrechetCellView

        return FrechetCellView(atoms, scalar_pressure=self.scalar_pressure_GPa * units.GPa,
                               hydrostatic_strain=self.hydrostatic_strain, constant_volume=self.constant_volume,
                               mask=self.mask, exp_cell_factor=self.exp_cell_factor)


def _no_cell_filter(record):
    if record.cell_filter is not None and not isinstance(record.cell_filter, FrechetCell):
        raise InputError(f"{type(record).__name__}.cell_filter must be lm.optimize.FrechetCell or None, got "
                         f"{type(record.cell_filter).__name__}")


@dataclass(frozen=True, kw_only=True)
class LBFGS:
    """ASE 3.27's ``LBFGS``: ``maxstep_A`` (ASE ``maxstep``), ``memory``, ``damping`` and ``alpha`` with ASE's
    defaults. ``use_line_search`` is not offered."""

    maxstep_A: float = 0.2
    memory: int = 100
    damping: float = 1.0
    alpha: float = 70.0
    cell_filter: object = None

    def __post_init__(self):
        _number(self, "maxstep_A", positive=True)
        _number(self, "damping", positive=True)
        _number(self, "alpha", positive=True)
        if isinstance(self.memory, bool) or not isinstance(self.memory, int) or self.memory < 1:
            raise InputError(f"LBFGS.memory must be an int of at least 1, got {self.memory!r}")
        from .lbfgs import MAX_MAXSTEP_A

        if self.maxstep_A > MAX_MAXSTEP_A:
            raise InputError(f"LBFGS.maxstep_A = {self.maxstep_A:g} A is too large (ASE's LBFGS refuses a maximum "
                             f"step above {MAX_MAXSTEP_A:g} A)")
        _no_cell_filter(self)

    def state(self, n_atoms):
        from .lbfgs import LBFGSState

        return LBFGSState(n_atoms, self.maxstep_A, self.memory, self.damping, self.alpha)


@dataclass(frozen=True, kw_only=True)
class FIRE:
    """ASE 3.27's ``FIRE`` with ASE's arguments and defaults: ``dt`` and ``dtmax`` in ASE time units, ``maxstep_A``
    (ASE ``maxstep``), ``Nmin``, ``finc``, ``fdec``, ``astart``, ``fa`` and ``a``. ``downhill_check`` is not in this
    version."""

    dt: float = 0.1
    maxstep_A: float = 0.2
    dtmax: float = 1.0
    Nmin: int = 5
    finc: float = 1.1
    fdec: float = 0.5
    astart: float = 0.1
    fa: float = 0.99
    a: float = 0.1
    downhill_check: bool = False
    cell_filter: object = None

    def __post_init__(self):
        for name in ("dt", "maxstep_A", "dtmax", "finc", "fdec", "astart", "fa"):
            _number(self, name, positive=True)
        _number(self, "a", minimum=0)
        if isinstance(self.Nmin, bool) or not isinstance(self.Nmin, int) or self.Nmin < 0:
            raise InputError(f"FIRE.Nmin must be a nonnegative int, got {self.Nmin!r}")
        if self.downhill_check is not False:
            raise PlanRefused("FIRE.downhill_check is not in this version", next_step="Leave it at False.")
        _no_cell_filter(self)

    def state(self, n_atoms):
        from .fire import FIREState

        return FIREState(n_atoms, self.dt, self.maxstep_A, self.dtmax, self.Nmin, self.finc, self.fdec, self.astart,
                         self.fa, self.a)


RECORDS = {cls.__name__: cls for cls in (LBFGS, FIRE)}


@dataclass(frozen=True)
class RelaxResult:
    """What ``relax`` returns."""

    atoms: object            # the relaxed structure, with energy and forces (and the stress, when the cell was
                             # relaxed) on a single-point calculator
    steps: int               # optimiser steps taken
    converged: bool          # the largest force on an atom is below fmax
    max_force: float         # eV/A, the largest force on a free atom (or on a cell row, when the cell is relaxed)
    energy: float            # eV
    force_calls: int         # steps + 1
    optimizer_s: float       # time spent in the optimiser's own arithmetic
    force_s: float           # time spent in the force calls

    def __str__(self):
        state = "converged" if self.converged else "not converged"
        return (f"{state} after {self.steps} steps: largest force {self.max_force:.4f} eV/A, energy "
                f"{self.energy:.6f} eV")


def _dispersion_record(force_field, dispersion):
    """``dispersion`` (a preset name, an ``lm.Dispersion`` or its table) resolved for the model, as ``lm.calc``
    resolves it; ``None`` for none."""
    if dispersion is None:
        return None
    from .. import dispersion as _dispersion

    record = _dispersion.resolve(_dispersion.parse(dispersion), functional=getattr(force_field, "functional", None),
                                 family=getattr(force_field, "family", None), model=getattr(force_field, "name", None))
    if record is not None:
        _dispersion.runnable(record)
    return record


def _install_dispersion(force_field, work, skin, record):
    """Put exactly ``record`` (or no term) on the engine the relaxation uses: the force field's shared engine may
    hold the term another user (``lm.calc``) set."""
    if not hasattr(force_field, "engine_for"):
        if record is not None:
            raise PlanRefused("dispersion with this force field", why="it has no engine to add the D3 term to")
        return
    engine = force_field.engine_for(work, skin)
    if getattr(engine, "dispersion", None) == record:
        return
    if not hasattr(engine, "set_dispersion"):
        if record is not None:
            raise PlanRefused("dispersion with the tiled execution", why="the relaxation's engine has no D3 term",
                              next_step="Relax a cell that fits the GPU whole, or relax without dispersion.")
        return
    engine.set_dispersion(record)


def relax(force_field, atoms, optimizer=None, *, fmax=0.05, steps=100_000_000, skin=0.5, dispersion=None,
          callback=None, _on_step=None) -> RelaxResult:
    """Relax ``atoms`` until the largest force on an atom is below ``fmax`` (eV/A), or ``steps`` optimiser steps
    were taken. ``optimizer`` is an ``lm.optimize`` record (default ``LBFGS()``); with its ``cell_filter`` the cell
    is relaxed too and the cell's rows count for ``fmax`` as in ASE. ``force_field`` is what ``lm.load`` returned.
    ``dispersion`` (a preset name or an ``lm.Dispersion``, as ``lm.calc`` takes it) adds the D3 term to the
    energy, forces and stress; ``long_range="auto"`` is the plain sum here, without the setup check. ``atoms`` is
    not changed; ``callback(step, atoms positions, energy, max force)`` is called after every force call."""
    import numpy as np
    from ase.calculators.singlepoint import SinglePointCalculator

    from ..simulation import fixed_mask

    optimizer = LBFGS() if optimizer is None else optimizer
    if type(optimizer) not in RECORDS.values():
        raise InputError(f"optimizer must be an lm.optimize record ({', '.join(RECORDS)}), got "
                         f"{type(optimizer).__name__}")
    if isinstance(fmax, bool) or not isinstance(fmax, (int, float)) or not math.isfinite(fmax) or fmax <= 0:
        raise InputError(f"fmax must be positive and finite (eV/A), got {fmax!r}")
    if isinstance(steps, bool) or not isinstance(steps, int) or steps < 0:
        raise InputError(f"steps must be a whole number of at least 0, got {steps!r}")
    record = _dispersion_record(force_field, dispersion)          # a wrong record: refused before the export
    work = atoms.copy()
    fixed = fixed_mask(work)                      # refuses other constraints before anything is exported
    view = None
    if optimizer.cell_filter is not None:
        if fixed is not None:
            raise PlanRefused("the cell cannot be relaxed while atoms are fixed",
                              next_step="Remove the FixAtoms constraint, or relax at fixed cell (cell_filter=None).")
        if getattr(force_field, "long_range", False):
            raise PlanRefused(f"the cell cannot be relaxed with {force_field.name}: its long-range part has no "
                              "stress the filter can use", next_step="Relax at fixed cell (cell_filter=None).")
        view = optimizer.cell_filter.view(work)
    _install_dispersion(force_field, work, skin, record)
    if view is None and isinstance(optimizer, LBFGS) and hasattr(force_field, "engine_for"):
        engine = force_field.engine_for(work, skin)
        if hasattr(engine, "minimize"):
            return _relax_on_device(engine, work, fixed, optimizer, fmax, steps, callback, _on_step)
    state = optimizer.state(len(work) + (3 if view is not None else 0))
    timers = {"force": 0.0, "optimizer": 0.0}
    last = {}

    def evaluate():
        started = time.perf_counter()
        energy, forces, stress = force_field.evaluate(work, stress=view is not None, skin=skin)
        timers["force"] += time.perf_counter() - started
        if not math.isfinite(energy) or not np.isfinite(forces).all():
            raise NonFiniteError("non-finite energy or forces during the relaxation",
                                 why="the step led to a configuration the model cannot evaluate")
        forces = np.array(forces, dtype=float)
        last.update(forces=forces, stress=stress)
        if fixed is not None:
            forces[fixed] = 0.0
        rows = forces if view is None else view.forces(forces, stress)
        return float(energy), rows, float(np.sqrt((rows ** 2).sum(axis=1).max()))

    def notify(step):
        if callback is not None:
            callback(step, work.positions, energy, largest)
        if _on_step is not None:       # the ASE drop-ins: the structure with its results, and ASE's logged value
            work.calc = SinglePointCalculator(work, energy=energy, forces=last["forces"], **results_extra())
            _on_step(step, work, energy if view is None else view.value(energy), largest)

    def results_extra():
        if view is None:
            return {}
        from ase.stress import full_3x3_to_voigt_6_stress

        return {"stress": full_3x3_to_voigt_6_stress(last["stress"])}

    energy, forces, largest = evaluate()
    taken = 0
    notify(taken)
    while largest >= fmax and taken < steps:
        started = time.perf_counter()
        if view is None:
            work.positions[:] = state.step(work.positions, forces)
        else:
            view.set_x(state.step(view.get_x(), forces))
        timers["optimizer"] += time.perf_counter() - started
        energy, forces, largest = evaluate()
        taken += 1
        notify(taken)
    work.calc = SinglePointCalculator(work, energy=energy, forces=last["forces"], **results_extra())
    return RelaxResult(atoms=work, steps=taken, converged=bool(largest < fmax), max_force=largest, energy=energy,
                       force_calls=taken + 1, optimizer_s=timers["optimizer"], force_s=timers["force"])


def _relax_on_device(engine, work, fixed, optimizer, fmax, steps, callback, on_step) -> RelaxResult:
    """LBFGS at fixed cell inside the engine (``loup_minimize``). With a callback the engine takes one step per
    call, so that the caller sees every step; without one it takes them all in one call."""
    from ase.calculators.singlepoint import SinglePointCalculator

    engine.set_state(work.positions, None, work.cell.array)
    if fixed is not None:
        engine.set_fixed_atoms(fixed)              # the force field's shared engine: freed again below
    settings = dict(fmax=fmax, maxstep_A=optimizer.maxstep_A, memory=optimizer.memory, damping=optimizer.damping,
                    alpha=optimizer.alpha)
    watched = callback is not None or on_step is not None
    force_ms = optimizer_ms = 0.0
    taken = passes = 0

    def notify(stats):
        positions, _, forces, energy = engine.get_state()
        if callback is not None:
            callback(taken, positions, energy, stats.max_force_ev_a)
        if on_step is not None:
            work.set_positions(positions, apply_constraint=False)
            work.calc = SinglePointCalculator(work, energy=energy, forces=forces)
            on_step(taken, work, energy, stats.max_force_ev_a)

    try:
        try:
            stats = engine.minimize(0, **settings)                        # the starting structure's forces
            force_ms, optimizer_ms, passes = stats.force_ms, stats.optimizer_ms, stats.force_passes
            if watched:
                notify(stats)
            while not stats.converged and taken < steps:
                stats = engine.minimize(1 if watched else steps - taken, **settings)
                taken += stats.steps
                passes += stats.force_passes
                force_ms += stats.force_ms
                optimizer_ms += stats.optimizer_ms
                if watched:
                    notify(stats)
        except Exception as error:
            if "non-finite" in str(error):
                raise NonFiniteError("non-finite energy or forces during the relaxation",
                                     why="the step led to a configuration the model cannot evaluate") from None
            raise
        positions, _, forces, energy = engine.get_state()
    finally:
        if fixed is not None:
            engine.set_fixed_atoms(None)
    work.set_positions(positions, apply_constraint=False)
    work.calc = SinglePointCalculator(work, energy=energy, forces=forces)
    return RelaxResult(atoms=work, steps=taken, converged=bool(stats.converged), max_force=stats.max_force_ev_a,
                       energy=energy, force_calls=max(passes, 1), optimizer_s=optimizer_ms / 1e3,
                       force_s=force_ms / 1e3)
