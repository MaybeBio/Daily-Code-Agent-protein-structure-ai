"""Drop-in MD classes with ASE's arguments and units: ``from loupmd.ase.md import Langevin, VelocityVerlet, Bussi``.

A script written for ``ase.md`` runs after changing its import line and naming the model:

    dyn = Langevin(atoms, 1.0 * units.fs, temperature_K=300, friction=0.01 / units.fs, model="omat0-medium",
                   trajectory="md.traj", logfile="md.log", loginterval=10)
    dyn.attach(report, interval=100)
    dyn.run(1000)

The engine owns the loop: ``run`` hands it the steps between two observer calls in one piece, and the ``atoms`` are
brought up to date (positions, momenta, a calculator holding the energy and forces) before every observer call and
at the end of ``run``. ASE's ``trajectory``, ``logfile``, ``loginterval`` and ``append_trajectory`` mean what they
mean in ASE (an ASE trajectory file and ASE's ``MDLogger`` lines); they are observers, so the run stops at every
``loginterval`` steps for them. LoupMD's own output (``output=``, a directory or ``lm.Output``) is written without
stopping the run and is the faster choice for long runs.

Beyond ASE's arguments: ``model=`` (a label, path or ``lm.load`` result; required), ``head=``, ``seed=`` (the
thermostat's noise seed), ``output=``, ``check=`` and what ``lm.load`` takes. ASE's ``rng``, ``comm`` and ``master``
are refused when given: the noise is drawn on the GPU from ``seed``.

Built: ``Langevin``, ``VelocityVerlet``, ``Bussi``, ``NoseHooverChainNVT`` and ``NVTBerendsen``. Langevin's ``fixcm=True`` (ASE's default) keeps the centre
of mass at rest with the mass-weighted projection of the noise, which is canonical for unequal masses too; ASE's
own projection differs from it for unequal masses. ``VelocityVerlet``, ``Bussi`` and ``NoseHooverChainNVT``
remove no centre-of-mass motion, as ASE's classes, and count 3 N degrees of freedom less three for each fixed
atom (ASE's chain counts 3 N even with fixed atoms). The other classes of FastMACE's ``fastmace.ase`` are
refused by name until their integrators are built.
"""
from __future__ import annotations

import os
from math import gcd

from ..errors import InputError, PlanRefused
from ..forcefield import ForceField, load

_NOT_BUILT = ()
_LOAD_OPTIONS = ("checkpoint", "sha256", "trusted", "download", "charge", "spin_multiplicity", "device")
# ASE's arguments that have no meaning here: accepted at None, refused otherwise.
_ASE_REFUSED = {"rng": "the noise is drawn on the GPU: pass seed=", "comm": "LoupMD runs in one process",
                "master": "LoupMD runs in one process"}


def __getattr__(name):
    if name in _NOT_BUILT:
        raise PlanRefused(f"loupmd.ase.md.{name} is not in this version",
                          why="its integrator is not built in the engine yet (PLAN.md Stage 4)",
                          next_step="Use LangevinBAOAB or NPTBerendsen for constant pressure, or ASE's class with "
                                    "lm.calc as the calculator.")
    raise AttributeError(f"module 'loupmd.ase.md' has no attribute {name!r}")


def take_ase_arguments(options, what) -> dict:
    """Remove ASE's own optional arguments from ``options`` and return those that are set. ``rng``, ``comm`` and
    ``master`` are refused unless ``None``."""
    for name, why in _ASE_REFUSED.items():
        if options.pop(name, None) is not None:
            raise InputError(f"{what}: {name}= is not taken", why=why)
    return {name: options.pop(name) for name in ("trajectory", "logfile", "loginterval", "append_trajectory",
                                                 "restart") if name in options}


def open_trajectory(trajectory, atoms, append=False):
    """ASE's ``trajectory=``: ``(write function, object to close or None)``. A path opens an ASE trajectory file
    of ``atoms``; anything else is taken as a trajectory object and its ``write`` is called."""
    if isinstance(trajectory, (str, os.PathLike)):
        from ase.io.trajectory import Trajectory

        writer = Trajectory(os.fspath(trajectory), mode="a" if append else "w", atoms=atoms)
        return writer.write, writer
    if not hasattr(trajectory, "write"):
        raise InputError(f"trajectory must be a path or a trajectory object, got {type(trajectory).__name__}")
    return trajectory.write, None


def force_field_of(model, head, options, what):
    """The ``ForceField`` of a drop-in's ``model=``."""
    unknown = sorted(set(options) - set(_LOAD_OPTIONS))
    if unknown:
        raise TypeError(f"{what} got unexpected keyword arguments {', '.join(unknown)}")
    if model is None:
        raise InputError(f"{what} needs model=: a label (`loupmd models`), a checkpoint path or an lm.load result")
    if isinstance(model, ForceField):
        if head is not None or options:
            raise InputError("the model is already loaded; head and the load options belong to lm.load")
        return model
    return load(model, head, **options)


class _Dynamics:
    """What the drop-ins share: observers, ``run`` in pieces, the ``atoms`` kept up to date."""

    def __init__(self, atoms, timestep, integrator, model, head, seed, output, check, options):
        from ..config import Output
        from ..simulation import Simulation

        what = type(self).__name__
        ase_arguments = take_ase_arguments(options, what)
        if ase_arguments.pop("restart", None) is not None:
            raise TypeError(f"{what} got an unexpected keyword argument restart")
        if output is not None and not isinstance(output, Output):
            output = Output(output)
        self.atoms = atoms
        self.dt = timestep                                   # ASE's attribute, in ASE time units
        self.simulation = Simulation(atoms, force_field_of(model, head, options, what),
                                     integrator=integrator, output=output, seed=seed, check=check, skin="auto")
        self.observers = []
        self.nsteps = 0
        self._closables = []
        interval = ase_arguments.get("loginterval", 1)
        if ase_arguments.get("trajectory") is not None:
            write, closable = open_trajectory(ase_arguments["trajectory"], atoms,
                                              ase_arguments.get("append_trajectory", False))
            self.attach(write, interval=interval)
            if closable is not None:
                self._closables.append(closable)
        if ase_arguments.get("logfile"):
            from ase.md.logger import MDLogger

            logger = MDLogger(dyn=self, atoms=atoms, logfile=ase_arguments["logfile"])
            self.attach(logger, interval=interval)
            self._closables.append(logger)

    @property
    def summary(self) -> str:
        """The run report of what has run so far, as ``lm.md``'s ``RunResult.summary``."""
        from .. import provenance, report

        return report.text(provenance.collect(self.simulation))

    def attach(self, function, interval=1, *args, **kwargs):
        """Call ``function(*args, **kwargs)`` every ``interval`` steps (and at step 0), with ``atoms`` up to date."""
        if isinstance(interval, bool) or not isinstance(interval, int) or interval < 1:
            raise InputError(f"interval must be a positive int, got {interval!r}")
        if hasattr(function, "write") and not callable(function):
            function = function.write
        self.observers.append((function, interval, args, kwargs))

    def get_number_of_steps(self):
        return self.nsteps

    def get_time(self):
        """The simulated time in ASE time units, as ASE's."""
        return self.nsteps * self.dt

    def _sync(self):
        current = self.simulation.atoms
        if self.simulation.config.ensemble == "npt":             # the barostat's cell
            self.atoms.set_cell(current.cell, scale_atoms=False, apply_constraint=False)
        self.atoms.set_positions(current.positions, apply_constraint=False)
        self.atoms.set_momenta(current.get_momenta(), apply_constraint=False)
        self.atoms.calc = current.calc
        self.atoms.calc.atoms = self.atoms.copy()

    def _call_observers(self):
        for function, interval, args, kwargs in self.observers:
            if self.nsteps % interval == 0:
                function(*args, **kwargs)

    def run(self, steps):
        """``steps`` MD steps. Returns ``True``, as ASE's ``run`` does when it completes."""
        if isinstance(steps, bool) or not isinstance(steps, int) or steps < 0:
            raise InputError(f"steps must be a whole number of at least 0, got {steps!r}")
        if self.nsteps == 0 and self.observers:
            self.simulation.start()                      # ASE calls its observers before the first step, with the
            self._sync()                                 # starting structure's energy and forces
            self._call_observers()
        piece = 0
        for _, interval, _, _ in self.observers:
            piece = gcd(piece, interval)
        done = 0
        while done < steps:
            n = steps - done if not piece else min(steps - done, piece - self.nsteps % piece)
            self.simulation.run(steps=n)
            done += n
            self.nsteps += n
            if self.observers:
                self._sync()
                self._call_observers()
        if steps:
            self._sync()
        return True

    def close(self):
        """Close the files this object opened (``trajectory=``, ``logfile=``) and the simulation's output."""
        for closable in self._closables:
            closable.close()
        self._closables = []
        self.simulation.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class Langevin(_Dynamics):
    """``ase.md.langevin.Langevin`` on LoupMD's engine: ``timestep`` and ``friction`` in ASE units, ``temperature_K``
    in K (or ASE's older ``temperature`` in eV)."""

    def __init__(self, atoms, timestep, temperature=None, friction=None, fixcm=True, *, temperature_K=None,
                 model=None, head=None, seed=None, output=None, check="skip", **options):
        from ase import units

        from .. import integrators

        if temperature is not None and temperature_K is not None:
            raise TypeError("Langevin takes temperature (in eV) or temperature_K, not both")
        if temperature is not None:
            temperature_K = temperature / units.kB
        if temperature_K is None or friction is None:
            raise InputError("Langevin needs temperature_K and friction (in inverse ASE time units, for example "
                             "0.01 / units.fs)")
        record = integrators.Langevin(timestep_fs=timestep / units.fs, temperature_K=temperature_K,
                                      friction_per_fs=friction * units.fs, fixcm=fixcm)
        super().__init__(atoms, timestep, record, model, head, seed, output, check, options)


class VelocityVerlet(_Dynamics):
    """``ase.md.verlet.VelocityVerlet`` on LoupMD's engine: ``timestep`` in ASE units."""

    def __init__(self, atoms, timestep, trajectory=None, logfile=None, loginterval=1, *, model=None, head=None,
                 seed=None, output=None, check="skip", **options):
        from ase import units

        from .. import integrators

        options.update(trajectory=trajectory, logfile=logfile, loginterval=loginterval)
        super().__init__(atoms, timestep, integrators.NVE(timestep_fs=timestep / units.fs, fixcm=False), model,
                         head, seed, output, check, options)


class Bussi(_Dynamics):
    """``ase.md.bussi.Bussi`` (canonical sampling through velocity rescaling) on LoupMD's engine: ``timestep`` and
    ``taut`` in ASE units, ``temperature_K`` in K. As ASE's class, it refuses a structure at rest and counts
    ASE's degrees of freedom."""

    def __init__(self, atoms, timestep, temperature_K, taut, rng=None, *, model=None, head=None, seed=None,
                 output=None, check="skip", **options):
        from ase import units

        from .. import integrators

        options["rng"] = rng
        record = integrators.CSVR(timestep_fs=timestep / units.fs, temperature_K=temperature_K,
                                  tau_fs=taut / units.fs, fixcm=False)
        super().__init__(atoms, timestep, record, model, head, seed, output, check, options)
        self.transferred_energy = 0.0                    # ASE's attribute; the engine keeps the running sum


class NoseHooverChainNVT(_Dynamics):
    """``ase.md.nose_hoover_chain.NoseHooverChainNVT`` on LoupMD's engine: ``timestep`` and ``tdamp`` in ASE
    units, ``temperature_K`` in K, ``tchain`` thermostats, ``tloop`` sub-steps."""

    def __init__(self, atoms, timestep, temperature_K, tdamp, tchain=3, tloop=1, *, model=None, head=None,
                 seed=None, output=None, check="skip", **options):
        from ase import units

        from .. import integrators

        record = integrators.NoseHooverChain(timestep_fs=timestep / units.fs, temperature_K=temperature_K,
                                             tdamp_fs=tdamp / units.fs, tchain=tchain, tloop=tloop, fixcm=False)
        super().__init__(atoms, timestep, record, model, head, seed, output, check, options)


class NVTBerendsen(_Dynamics):
    """``ase.md.nvtberendsen.NVTBerendsen`` on LoupMD's engine: ``timestep`` and ``taut`` in ASE units,
    ``temperature_K`` in K (or ASE's older ``temperature`` in eV). ``fixcm=True`` (ASE's default) keeps the
    centre of mass at rest; the temperature then counts three degrees of freedom fewer than ASE's."""

    def __init__(self, atoms, timestep, temperature=None, taut=None, fixcm=True, *, temperature_K=None, model=None,
                 head=None, seed=None, output=None, check="skip", **options):
        from ase import units

        from .. import integrators

        if temperature is not None and temperature_K is not None:
            raise TypeError("NVTBerendsen takes temperature (in eV) or temperature_K, not both")
        if temperature is not None:
            temperature_K = temperature / units.kB
        if temperature_K is None or taut is None:
            raise InputError("NVTBerendsen needs temperature_K and taut (in ASE time units, for example "
                             "100 * units.fs)")
        record = integrators.Berendsen(timestep_fs=timestep / units.fs, temperature_K=temperature_K,
                                       taut_fs=taut / units.fs, fixcm=fixcm)
        super().__init__(atoms, timestep, record, model, head, seed, output, check, options)


class NPTBerendsen(_Dynamics):
    """``ase.md.nptberendsen.NPTBerendsen`` on LoupMD's engine (experimental): ``timestep``, ``taut`` and
    ``taup`` in ASE units, ``temperature_K`` in K, ``pressure_au`` in eV/A^3 and ``compressibility_au`` in
    A^3/eV, as ASE's class. ``fixcm=True`` (ASE's default) keeps the centre of mass at rest; the temperature
    then counts three degrees of freedom fewer than ASE's.

    One difference from ASE's class: the engine makes one force call per step, so the first kick of a step uses
    the forces of the cell before the barostat scaled it, where ASE evaluates again. The two agree to the order
    of ``dt * compressibility * |pressure - P| / taup`` per step."""

    _mask = None

    def __init__(self, atoms, timestep, temperature=None, *, temperature_K=None, pressure=None, pressure_au=None,
                 taut=None, taup=None, compressibility=None, compressibility_au=None, fixcm=True, model=None,
                 head=None, seed=None, output=None, check="skip", **options):
        from ase import units

        from .. import integrators

        name = type(self).__name__
        if temperature is not None and temperature_K is not None:
            raise TypeError(f"{name} takes temperature (in eV) or temperature_K, not both")
        if temperature is not None:
            temperature_K = temperature / units.kB
        if pressure is not None or compressibility is not None:
            raise InputError(f"{name}: pressure= (bar) and compressibility= (1/bar) are ASE's deprecated units",
                             next_step="Pass pressure_au (eV/A^3, for example 1.01325 * units.bar) and "
                                       "compressibility_au (A^3/eV, for example 4.57e-5 / units.bar).")
        missing = [label for label, value in (("temperature_K", temperature_K), ("pressure_au", pressure_au),
                                              ("compressibility_au", compressibility_au)) if value is None]
        if missing:
            raise InputError(f"{name} needs {', '.join(missing)}")
        taut = 0.5e3 * units.fs if taut is None else taut             # ASE's defaults
        taup = 1e3 * units.fs if taup is None else taup
        record = integrators.Berendsen(timestep_fs=timestep / units.fs, temperature_K=temperature_K,
                                       taut_fs=taut / units.fs, pressure_GPa=pressure_au / units.GPa,
                                       taup_fs=taup / units.fs,
                                       compressibility_per_GPa=compressibility_au * units.GPa, mask=self._mask,
                                       fixcm=fixcm)
        super().__init__(atoms, timestep, record, model, head, seed, output, check, options)


class Inhomogeneous_NPTBerendsen(NPTBerendsen):
    """``ase.md.nptberendsen.Inhomogeneous_NPTBerendsen`` on LoupMD's engine (experimental): as ``NPTBerendsen``,
    with each cell vector scaled by its own stress and ``mask`` (three 0 / 1 entries, ASE's default (1, 1, 1))
    naming the vectors the barostat may scale. The angles stay."""

    def __init__(self, *args, mask=(1, 1, 1), **kwargs):
        self._mask = tuple(int(m) for m in mask)
        super().__init__(*args, **kwargs)


class LangevinBAOAB(_Dynamics):
    """``ase.md.langevinbaoab.LangevinBAOAB`` with a barostat on LoupMD's engine (experimental): ``timestep``,
    ``T_tau`` and ``P_tau`` in ASE units, ``temperature_K`` in K, ``externalstress`` a scalar in eV/A^3 (minus
    the target pressure, ASE's sign), ``hydrostatic`` as ASE's (default ``False``: the full cell).

    As ASE's class: ``T_tau`` defaults to 50 timesteps, ``P_tau`` to 20 ``T_tau``, the barostat's mass is ASE's
    heuristic, and the centre of mass is not held. Differences: the noise is drawn on the GPU (``seed=``, not
    ``rng=``); with the full cell the barostat's drag on the velocities is Quigley and Probert's, where ASE 3.27
    adds its trace term to all nine elements. Refused: no ``temperature_K`` or no ``externalstress`` (use
    ``VelocityVerlet`` or ``Langevin``), a stress tensor as target, ``P_mass``, ``P_mass_factor`` other than 1,
    ``disable_cell_langevin=True``."""

    def __init__(self, atoms, timestep, *, temperature_K=None, externalstress=None, hydrostatic=False, T_tau=None,
                 P_tau=None, P_mass=None, P_mass_factor=1.0, disable_cell_langevin=False, model=None, head=None,
                 seed=None, output=None, check="skip", **options):
        import numpy as np
        from ase import units

        from .. import integrators

        if temperature_K is None or externalstress is None:
            raise PlanRefused("LangevinBAOAB without temperature_K or without externalstress is not in this version",
                              why="the engine's BAOAB is the NPT integrator: thermostat and barostat together",
                              next_step="Use Langevin for constant volume, VelocityVerlet for constant energy.")
        stress = np.asarray(externalstress, dtype=float)
        if stress.size != 1:
            raise PlanRefused(f"LangevinBAOAB(externalstress=...) with {stress.size} components is not in this "
                              "version", why="the target is a pressure",
                              next_step="Pass a scalar: externalstress=-pressure in eV/A^3.")
        for name, value, default in (("P_mass", P_mass, None), ("P_mass_factor", P_mass_factor, 1.0),
                                     ("disable_cell_langevin", disable_cell_langevin, False)):
            if value != default:
                raise PlanRefused(f"LangevinBAOAB({name}={value!r}) is not in this version",
                                  why="the barostat's mass is ASE's heuristic and its thermostat is on")
        if T_tau is None:
            T_tau = 50.0 * timestep                                   # ASE's default
        record = integrators.LangevinBAOAB(
            timestep_fs=timestep / units.fs, temperature_K=temperature_K, friction_per_fs=units.fs / T_tau,
            pressure_GPa=-float(stress.reshape(-1)[0]) / units.GPa,
            cell_mode="hydrostatic" if hydrostatic else "full",
            barostat_tau_fs=None if P_tau is None else P_tau / units.fs)
        super().__init__(atoms, timestep, record, model, head, seed, output, check, options)


class IsotropicMTKNPT(_Dynamics):
    """``ase.md.nose_hoover_chain.IsotropicMTKNPT`` on LoupMD's engine (experimental): ``timestep``, ``tdamp`` and
    ``pdamp`` in ASE units, ``temperature_K`` in K, ``pressure_au`` in eV/A^3; ``tchain``, ``pchain``, ``tloop``
    and ``ploop`` as ASE's (chains of at most 8 links). The centre of mass is not held, as in ASE's class."""

    _cell_mode = "hydrostatic"

    def __init__(self, atoms, timestep, temperature_K, pressure_au, tdamp, pdamp, tchain=3, pchain=3, tloop=1,
                 ploop=1, *, model=None, head=None, seed=None, output=None, check="skip", **options):
        from ase import units

        from .. import integrators

        record = integrators.MTK(timestep_fs=timestep / units.fs, temperature_K=temperature_K,
                                 pressure_GPa=pressure_au / units.GPa, tdamp_fs=tdamp / units.fs,
                                 pdamp_fs=pdamp / units.fs, tchain=tchain, pchain=pchain, tloop=tloop, ploop=ploop,
                                 cell_mode=self._cell_mode, fixcm=False)
        super().__init__(atoms, timestep, record, model, head, seed, output, check, options)


class MTKNPT(IsotropicMTKNPT):
    """``ase.md.nose_hoover_chain.MTKNPT`` on LoupMD's engine (experimental): as ``IsotropicMTKNPT``, with the
    full cell."""

    _cell_mode = "full"

