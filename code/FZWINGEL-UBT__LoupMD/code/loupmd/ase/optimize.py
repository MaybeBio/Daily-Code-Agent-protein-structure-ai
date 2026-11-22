"""Drop-in optimisers with ASE's arguments: ``from loupmd.ase.optimize import LBFGS, FIRE``.

A script written for ``ase.optimize`` runs after changing its import line and naming the model:

    opt = LBFGS(atoms, trajectory="relax.traj", model="omat0-medium")
    opt.run(fmax=0.05)

relaxes ``atoms`` in place and returns whether it converged. As in ASE, a line per step goes to ``logfile``
(standard output by default; ``None`` for none), ``trajectory`` writes an ASE trajectory, and ``attach`` calls a
function after every step. For a cell relaxation wrap the atoms in ASE's filter, as with ASE,

    opt = LBFGS(FrechetCellFilter(atoms, scalar_pressure=1.0 * units.GPa), model="omat0-medium")

or pass ``cell_filter=lm.optimize.FrechetCell(...)``. ``FrechetCellFilter`` is the one filter taken; ASE's other
filters are refused by name. Not offered: ``restart`` files, ``use_line_search=True``, ``FIRE``'s
``position_reset_callback`` and ``maxmove``.
"""
from __future__ import annotations

import os
import sys
import time

from .. import optimize as _optimize
from ..errors import InputError, PlanRefused
from .md import force_field_of, open_trajectory, take_ase_arguments


def _unwrap(atoms, cell_filter, what):
    """``(atoms, cell filter record)`` of a drop-in's first argument: an ``Atoms``, or ASE's ``FrechetCellFilter``
    around one, whose settings become an ``lm.optimize.FrechetCell``."""
    from ase import Atoms, units
    from ase.filters import Filter, FrechetCellFilter

    if isinstance(atoms, Atoms):
        return atoms, cell_filter
    if isinstance(atoms, FrechetCellFilter):
        if cell_filter is not None:
            raise InputError(f"{what} got a FrechetCellFilter and cell_filter=; one of the two")
        mask = tuple(tuple(int(flag) for flag in row) for row in atoms.mask)
        record = _optimize.FrechetCell(scalar_pressure_GPa=float(atoms.scalar_pressure) / units.GPa,
                                       hydrostatic_strain=bool(atoms.hydrostatic_strain),
                                       constant_volume=bool(atoms.constant_volume), mask=mask,
                                       exp_cell_factor=float(atoms.exp_cell_factor))
        return atoms.atoms, record
    if isinstance(atoms, Filter):
        raise PlanRefused(f"{what} got ASE's {type(atoms).__name__}, which is not supported",
                          why="LoupMD relaxes cells with the Frechet cell filter",
                          next_step="Wrap the atoms in ase.filters.FrechetCellFilter instead.")
    raise InputError(f"{what} takes an ase.Atoms or an ase.filters.FrechetCellFilter, got {type(atoms).__name__}")


class _Optimizer:
    def __init__(self, atoms, record_class, settings, cell_filter, model, head, options):
        what = type(self).__name__
        self.dispersion = options.pop("dispersion", None)   # the D3 term, as lm.calc takes it (lm.optimize.relax)
        ase_arguments = take_ase_arguments(options, what)
        if ase_arguments.get("restart") is not None:
            raise InputError(f"{what}: restart= is not offered", why="the optimiser's history is not written to a file",
                             next_step="Start the relaxation again from the last structure.")
        self.atoms, cell_filter = _unwrap(atoms, cell_filter, what)
        self.record = record_class(cell_filter=cell_filter, **settings)
        self.force_field = force_field_of(model, head, options, what)
        self.observers = []
        self.nsteps = 0
        self.result = None
        self._closables = []
        self._log = None
        logfile = ase_arguments.get("logfile", "-")
        if logfile == "-":
            self._log = sys.stdout
        elif isinstance(logfile, (str, os.PathLike)):
            self._log = open(logfile, "a")                 # ASE appends to a log file
            self._closables.append(self._log)
        elif logfile is not None:
            self._log = logfile                            # a file object, which stays the caller's
        if ase_arguments.get("trajectory") is not None:
            write, closable = open_trajectory(ase_arguments["trajectory"], self.atoms,
                                              ase_arguments.get("append_trajectory", False))
            self.attach(write, interval=ase_arguments.get("loginterval", 1))
            if closable is not None:
                self._closables.append(closable)

    def attach(self, function, interval=1, *args, **kwargs):
        """Call ``function(*args, **kwargs)`` every ``interval`` steps (and before the first), with ``atoms`` up to
        date."""
        if isinstance(interval, bool) or not isinstance(interval, int) or interval < 1:
            raise InputError(f"interval must be a positive int, got {interval!r}")
        if hasattr(function, "write") and not callable(function):
            function = function.write
        self.observers.append((function, interval, args, kwargs))

    def get_number_of_steps(self):
        return self.nsteps

    def _write_log(self, step, value, largest):
        """ASE's ``Optimizer.log`` line."""
        name, now = type(self).__name__, time.localtime()
        if step == 0:
            self._log.write("%s  %4s %8s %15s  %12s\n" % (" " * len(name), "Step", "Time", "Energy", "fmax"))
        self._log.write("%s:  %3d %02d:%02d:%02d %15.6f %15.6f\n" % (name, step, now[3], now[4], now[5], value,
                                                                     largest))
        self._log.flush()

    def _update(self, structure):
        """Bring the caller's ``atoms`` up to ``structure`` (the relaxation's working copy with its results)."""
        if self.record.cell_filter is not None:
            self.atoms.set_cell(structure.cell, scale_atoms=False)
        self.atoms.set_positions(structure.positions, apply_constraint=False)
        self.atoms.calc = structure.calc
        self.atoms.calc.atoms = self.atoms.copy()

    def run(self, fmax=0.05, steps=100_000_000):
        """Relax until the largest force is below ``fmax`` (eV/A) or ``steps`` steps were taken; ``atoms`` is
        updated in place. Returns whether it converged."""
        def on_step(step, structure, value, largest):
            self.nsteps = step
            if self._log is not None:
                self._write_log(step, value, largest)
            if self.observers:
                self._update(structure)
                for function, interval, args, kwargs in self.observers:
                    if step % interval == 0:
                        function(*args, **kwargs)

        self.result = _optimize.relax(self.force_field, self.atoms, self.record, fmax=fmax, steps=steps,
                                      dispersion=self.dispersion, _on_step=on_step)
        self._update(self.result.atoms)
        self.nsteps = self.result.steps
        return self.result.converged

    def close(self):
        """Close the files this object opened (``trajectory=``, ``logfile=``)."""
        for closable in self._closables:
            closable.close()
        self._closables = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class LBFGS(_Optimizer):
    """``ase.optimize.LBFGS`` (without line search) on LoupMD's forces."""

    def __init__(self, atoms, restart=None, logfile="-", trajectory=None, maxstep=None, memory=100, damping=1.0,
                 alpha=70.0, use_line_search=False, *, cell_filter=None, model=None, head=None, **options):
        if use_line_search:
            raise InputError("use_line_search=True is not offered", next_step="Use LBFGS without it, or FIRE.")
        options.update(restart=restart, logfile=logfile, trajectory=trajectory)
        settings = dict(maxstep_A=0.2 if maxstep is None else maxstep, memory=memory, damping=damping, alpha=alpha)
        super().__init__(atoms, _optimize.LBFGS, settings, cell_filter, model, head, options)


class FIRE(_Optimizer):
    """``ase.optimize.FIRE`` on LoupMD's forces."""

    def __init__(self, atoms, restart=None, logfile="-", trajectory=None, dt=0.1, maxstep=None, maxmove=None,
                 dtmax=1.0, Nmin=5, finc=1.1, fdec=0.5, astart=0.1, fa=0.99, a=0.1, downhill_check=False,
                 position_reset_callback=None, *, cell_filter=None, model=None, head=None, **options):
        for name, value in (("maxmove", maxmove), ("position_reset_callback", position_reset_callback)):
            if value is not None:
                raise InputError(f"FIRE: {name}= is not offered",
                                 next_step="Use maxstep=." if name == "maxmove" else "Run without it.")
        options.update(restart=restart, logfile=logfile, trajectory=trajectory)
        settings = dict(dt=dt, maxstep_A=0.2 if maxstep is None else maxstep, dtmax=dtmax, Nmin=Nmin, finc=finc,
                        fdec=fdec, astart=astart, fa=fa, a=a, downhill_check=downhill_check)
        super().__init__(atoms, _optimize.FIRE, settings, cell_filter, model, head, options)
