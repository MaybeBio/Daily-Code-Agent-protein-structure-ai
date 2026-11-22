"""``lm.md`` and ``RunResult``: MD in one call, with FastMACE's keyword names.

``md`` checks its arguments, builds the integrator record and the ``Output``, loads the model and hands everything
to a ``Simulation``, which gates (if asked), runs and writes. Every argument error is raised before the model is
loaded. What ``md`` decides itself:

- the integrator: ``ensemble="NVT"`` is ``lm.integrators.Langevin``, ``"NVE"`` is ``NVE``, ``"NPT"`` is
  ``LangevinBAOAB`` at ``pressure_GPa`` with ``cell_mode`` (experimental). An explicit
  ``integrator=`` (any ``lm.integrators`` record, for example
  ``CSVR``) wins; a conflicting argument is an error;
- NVE has no target: the momenta are the structure's, and ``temperature_K=`` and ``schedule=`` are errors;
- the defaults: friction 0.02 per ASE time unit (about 0.001965/fs, FastMACE's), a drawn and recorded seed, the
  output directory ``./<structure stem>.loupmd/`` (``./loupmd-run/`` for an in-memory ``Atoms``),
  ``repeat=(1, 1, 1)``.

Arguments that select FastMACE internals (``mode``, ``allow_reference``, ``fallback``, ``runner``, ``engine``,
``neighbours``, ``calibrate``) are accepted at their defaults and refused by name otherwise. ``mc=`` takes
``lm.mc`` moves (S6-T04); ``min_mc_temperature_K=`` is refused. ``dispersion=`` (a preset name or an
``lm.Dispersion``) is checked against the model (``loupmd.dispersion.resolve``) and adds the D3 pair term to every
step (S6-D04); the three-body term and the long-range methods are refused until they are built.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

from . import integrators, models, provenance, report
from .config import GateConfig, Output
from .errors import InputError, PlanRefused
from .forcefield import ForceField, load
from .protocols import Schedule, ScheduleState
from .simulation import CHECK_MODES, Simulation

DEFAULT_FRICTION_ASE = 0.02          # per ASE time unit, FastMACE's default
DEFAULT_OUTPUT = "loupmd-run"        # the output directory for an in-memory Atoms
OUTPUT_SUFFIX = ".loupmd"            # ./<structure stem>.loupmd/ for a structure file
ENSEMBLES = ("NVE", "NVT", "NPT")
INITIAL_VELOCITIES = ("keep", "maxwell_boltzmann")
CAPACITIES = ("auto", "whole", "tiled", "wavefront")
VELOCITY_STREAM = 0x76656C            # the velocities' random stream, apart from the thermostat's
_SEED_BOUND = 2 ** 31
# FastMACE's planner inputs: accepted at these defaults, refused by name otherwise.
_FASTMACE_INTERNALS = {"mode": None, "allow_reference": False, "fallback": None, "runner": None, "engine": None,
                       "neighbours": None, "calibrate": False}


def default_friction_per_fs() -> float:
    """``lm.md``'s Langevin friction per fs: 0.02 per ASE time unit, about 0.001965/fs."""
    from ase import units

    return DEFAULT_FRICTION_ASE * units.fs


@dataclass(frozen=True)
class RunResult:
    """What ``lm.md`` returns.

    - ``summary``: the one-screen report;
    - ``plan``: the execution plan as recorded (``metadata["plan"]``);
    - ``gate``: the gate's status and record;
    - ``simulation``: the ``Simulation``, which can run on, save a restart or be closed;
    - ``metadata``: the dict written to ``metadata.json``;
    - ``output``: the output directory.
    """

    summary: str
    plan: dict
    gate: dict
    simulation: Simulation
    metadata: dict
    output: str

    def __str__(self):
        return self.summary


def draw_initial_velocities(atoms, temperature_K, seed) -> bool:
    """Seeded Maxwell-Boltzmann momenta at ``temperature_K`` on ``atoms`` if it is at rest. ``True`` when drawn,
    ``False`` when the structure already moves: its momenta are kept."""
    if not math.isclose(float(atoms.get_kinetic_energy()), 0.0, rel_tol=0, abs_tol=1e-12):
        return False
    import numpy as np
    from ase.md.velocitydistribution import MaxwellBoltzmannDistribution

    MaxwellBoltzmannDistribution(atoms, temperature_K=temperature_K, rng=np.random.default_rng([seed, VELOCITY_STREAM]))
    return True


def _repeat(repeat):
    if isinstance(repeat, (str, bytes)) or not hasattr(repeat, "__len__") or len(repeat) != 3 \
            or any(isinstance(n, bool) or not isinstance(n, int) or n < 1 for n in repeat):
        raise InputError(f"repeat must be three positive ints, got {repeat!r}")
    return tuple(repeat)


def _initial_velocities(value):
    if isinstance(value, str):
        if value not in INITIAL_VELOCITIES:
            raise InputError(f"initial_velocities={value!r} is not one of {INITIAL_VELOCITIES} or a temperature in K")
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise InputError(f"initial_velocities must be one of {INITIAL_VELOCITIES} or a temperature in K above 0, got "
                         f"{value!r}")
    return float(value)


def _output(output, structure) -> Output:
    if isinstance(output, Output):
        return output
    if output is None:
        if isinstance(structure, (str, os.PathLike)):
            return Output(Path(structure).stem + OUTPUT_SUFFIX)
        return Output(DEFAULT_OUTPUT)
    if isinstance(output, (str, os.PathLike)):
        return Output(output)
    raise InputError(f"output must be a directory, an lm.Output or None, got {type(output).__name__}")


def _structure(structure):
    from ase import Atoms

    if isinstance(structure, Atoms):
        return structure.copy(), None
    if isinstance(structure, (str, os.PathLike)):
        path = Path(structure)
        if not path.is_file():
            raise InputError(f"structure file {path} not found")
        from ase.io import read

        return read(path), str(path)
    raise InputError(f"structure must be a path or an ase.Atoms, got {type(structure).__name__}")


def md(structure, *, model, head=None, charge=None, spin_multiplicity=None, sha256=None, trusted=False,
       checkpoint=None, download=False, ensemble="NVT", temperature_K=None, schedule=None, pressure_GPa=0.0,
       cell_mode="hydrostatic", timestep_fs=0.5, steps=None, mc=None, min_mc_temperature_K=None, dispersion=None,
       repeat=(1, 1, 1), output=None, seed=None, initial_velocities="keep", check="skip", integrator=None,
       capacity="auto", device=0, gate=None, skin="auto", mode=None, allow_reference=False, fallback=None,
       runner=None, engine=None, neighbours=None, calibrate=False) -> RunResult:
    """Run MD on ``structure`` (a path or an ``Atoms``) with ``model`` and return a ``RunResult``.

    - ``model``: a label, path or URL, with ``head``, ``charge``, ``spin_multiplicity``, ``sha256`` / ``trusted``,
      ``checkpoint`` and ``download`` as ``lm.load``; or an ``lm.load`` result (then without those);
    - ``ensemble``: ``"NVT"`` (Langevin) or ``"NVE"`` (velocity Verlet from the structure's momenta, no
      ``temperature_K``). ``integrator=`` chooses an ``lm.integrators`` record explicitly;
    - ``temperature_K`` or ``schedule`` (an ``lm.protocols`` schedule, or a profile's name for its schedule
      alone, as FastMACE); ``steps`` (optional with a schedule: the
      whole schedule); ``timestep_fs``;
    - ``repeat``: the supercell, ``(1, 1, 1)`` by default (never expanded silently);
    - ``output``: a directory or an ``lm.Output``; default ``./<structure stem>.loupmd/``, or ``./loupmd-run/``
      for an ``Atoms``;
    - ``seed``: the noise seed; ``None`` draws one, recorded in ``metadata.json``;
    - ``initial_velocities``: what a structure at rest starts with. ``"keep"`` (default): at rest.
      ``"maxwell_boltzmann"``: seeded Maxwell-Boltzmann momenta at the run's starting target. A temperature in K:
      Maxwell-Boltzmann momenta at it. A structure that already moves keeps its momenta; the report says which;
    - ``check``: ``"skip"`` (default), ``"gate"`` or ``"allow_unavailable"``, with ``gate=`` a ``GateConfig``;
    - ``skin``: the neighbour-list skin in A, or ``"auto"`` (default): chosen from how far the atoms move per
      step (``loupmd.skin``). It decides speed only;
    - ``capacity``: ``"auto"`` (default): the whole system when it fits the GPU, else tiles of up to 65,536 atoms
      (PLAN.md D65; barostats on the device loop, LAMMPS_TILED_PLAN.md LT6 (a)), from 2^20 atoms with the
      wavefront schedule where the cell is long
      enough; ``"whole"``, ``"tiled"`` or ``"wavefront"`` force one;
    - ``device``: the GPU index.
    """
    # ---- everything below up to "load" needs no model file ----
    given = {"mode": mode, "allow_reference": allow_reference, "fallback": fallback, "runner": runner,
             "engine": engine, "neighbours": neighbours, "calibrate": calibrate}
    set_internals = [name for name, value in given.items() if value != _FASTMACE_INTERNALS[name]]
    if allow_reference or fallback is not None:
        raise PlanRefused("allow_reference= and fallback=: the fallback to the MACE calculator is not in LoupMD",
                          why="it was cut from the release (PLAN.md decision A3): a model LoupMD cannot run is "
                              "refused with the reason instead of running slowly through PyTorch",
                          next_step="Run the model with MACE itself: atoms.calc = mace.calculators.MACECalculator("
                                    "model_paths=...), then ASE's MD drivers. loupmd models lists what LoupMD runs.")
    if set_internals:
        raise PlanRefused([f"{name}= selects FastMACE's internals and has no meaning in LoupMD" for name in
                           set_internals], next_step="Drop these arguments: LoupMD has one execution path.")
    if min_mc_temperature_K is not None:
        raise PlanRefused("min_mc_temperature_K=: a temperature floor for Monte Carlo moves is not in this version",
                          next_step="Run the moves with mc= over the whole run, or split the schedule into runs "
                                    "with and without mc= (Simulation.run).")
    from . import mc as _mc

    moves = [] if mc is None else [_mc.from_record(m) for m in (mc if isinstance(mc, (list, tuple)) else [mc])]
    from . import dispersion as _dispersion

    dispersion = _dispersion.parse(dispersion)          # an unknown preset or a bad record: refused before loading
    if capacity not in CAPACITIES:
        raise InputError(f"capacity={capacity!r} is not one of {CAPACITIES}")
    repeat = _repeat(repeat)
    if not isinstance(ensemble, str) or ensemble.upper() not in ENSEMBLES:
        raise InputError(f"ensemble={ensemble!r} is not one of {ENSEMBLES}")
    ensemble = ensemble.upper()
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int) or seed < 0):
        raise InputError(f"seed must be a nonnegative int or None, got {seed!r}")
    initial_velocities = _initial_velocities(initial_velocities)
    if check not in CHECK_MODES:
        raise InputError(f"check={check!r} is not one of {CHECK_MODES}")
    if gate is not None and not isinstance(gate, GateConfig):
        raise InputError(f"gate must be a GateConfig or None, got {type(gate).__name__}")
    if skin != "auto" and (isinstance(skin, bool) or not isinstance(skin, (int, float)) or not math.isfinite(skin)
                           or skin < 0):
        raise InputError(f"skin must be a length in A (0 or more) or 'auto', got {skin!r}")

    if isinstance(model, ForceField):
        options = {"head": head, "charge": charge, "spin_multiplicity": spin_multiplicity, "sha256": sha256,
                   "checkpoint": checkpoint}
        named = [name for name, value in options.items() if value is not None] + [
            name for name, value in (("trusted", trusted), ("download", download)) if value]
        if named:
            raise InputError(f"model is already loaded; {', '.join(named)} belong to lm.load")
    elif isinstance(model, (str, os.PathLike)):
        if not isinstance(model, os.PathLike) and not str(model).startswith(("https://", "http://")):
            models.find(str(model), head)          # a multi-head model without head= is refused here, with its heads
    else:
        raise InputError(f"model must be a label, path, URL or lm.load result, got {type(model).__name__}")

    if integrator is not None:
        if not isinstance(integrator, tuple(integrators.RECORDS.values())):
            raise InputError(f"integrator must be an lm.integrators record, got {type(integrator).__name__}")
        record_ensemble = ("NVE" if isinstance(integrator, integrators.NVE) else
                           "NPT" if getattr(integrator, "barostat", False) else "NVT")
        if ensemble != "NVT" and ensemble != record_ensemble:
            raise InputError(f"ensemble={ensemble!r} conflicts with integrator={type(integrator).__name__}; the "
                             "explicit integrator decides, so drop ensemble=")
        ensemble = record_ensemble
        conflicts = []
        if temperature_K is not None and temperature_K != getattr(integrator, "temperature_K", None):
            conflicts.append(f"temperature_K={temperature_K!r}")
        if timestep_fs != 0.5 and timestep_fs != integrator.timestep_fs:
            conflicts.append(f"timestep_fs={timestep_fs!r}")
        if conflicts:
            raise InputError(f"{', '.join(conflicts)} conflicts with the explicit integrator's fields; set them in "
                             "the integrator record only")
        timestep_fs = integrator.timestep_fs
    if isinstance(pressure_GPa, bool) or not isinstance(pressure_GPa, (int, float)) or not math.isfinite(pressure_GPa):
        raise InputError(f"pressure_GPa must be a finite number of GPa, got {pressure_GPa!r}")
    if cell_mode not in ("hydrostatic", "full"):
        raise InputError(f"cell_mode={cell_mode!r} is not one of ('hydrostatic', 'full')")
    if ensemble != "NPT" and (pressure_GPa != 0.0 or cell_mode != "hydrostatic"):
        raise InputError(f"pressure_GPa= and cell_mode= belong to ensemble='NPT', and the ensemble is {ensemble!r}")
    if integrator is not None and getattr(integrator, "barostat", False) and (
            pressure_GPa != 0.0 or cell_mode != "hydrostatic"):
        raise InputError("pressure_GPa= and cell_mode= conflict with the explicit integrator's fields; set them in "
                         "the integrator record only")
    nve = ensemble == "NVE"
    if nve:
        named = [name for name, value in (("temperature_K", temperature_K), ("schedule", schedule))
                 if value is not None]
        if named:
            raise InputError(f"ensemble='NVE' has no target temperature, so {', '.join(named)} cannot apply; the "
                             "momenta are the structure's")
        if initial_velocities == "maxwell_boltzmann":
            raise InputError("initial_velocities='maxwell_boltzmann' draws at the starting target, and NVE has none; "
                             "pass a temperature in K, for example initial_velocities=300.0")
    if isinstance(schedule, str):                   # FastMACE's spelling: a profile's schedule, not its cadences
        from .protocols import find_profile

        schedule = find_profile(schedule).schedule
    if schedule is not None:
        if not isinstance(schedule, Schedule):
            raise InputError(f"schedule must be an lm.protocols schedule (ramp, hold, +), got "
                             f"{type(schedule).__name__}")
        if temperature_K is not None:
            raise InputError("temperature_K and schedule= exclude each other: the schedule gives every target")
        position = ScheduleState(schedule, timestep_fs)
        position.steps_to_run(steps)
        start = float(integrator.temperature_K) if integrator is not None else float(position.target_K)
    else:
        if temperature_K is None and integrator is None and not nve:
            raise InputError("lm.md needs temperature_K= or schedule=")
        if steps is None:
            raise InputError("steps= is required without a schedule: nothing else fixes the run's length")
        if isinstance(steps, bool) or not isinstance(steps, int) or steps <= 0:
            raise InputError(f"steps must be a positive whole number, got {steps!r}")
        start = None if nve else float(integrator.temperature_K if integrator is not None else temperature_K)

    atoms, source = _structure(structure)
    if repeat != (1, 1, 1):
        atoms = atoms.repeat(repeat)
    warnings = []
    if seed is None:
        import secrets

        seed = secrets.randbelow(_SEED_BOUND)
    if initial_velocities != "keep":
        if initial_velocities == "maxwell_boltzmann" and not start > 0:
            raise InputError(f"initial_velocities='maxwell_boltzmann' draws at the starting target, which is "
                             f"{start:g} K; pass a temperature in K instead, for example initial_velocities=10.0")
        velocities_K = start if initial_velocities == "maxwell_boltzmann" else initial_velocities
        if draw_initial_velocities(atoms, velocities_K, seed):
            warnings.append(f"starting velocities: Maxwell-Boltzmann at {velocities_K:g} K, drawn from seed {seed} "
                            f"(initial_velocities={initial_velocities!r}; the structure was at rest)")
        else:
            warnings.append(f"starting velocities: the structure's own; initial_velocities={initial_velocities!r} "
                            "draws only for a structure at rest")
    explicit = integrator
    if integrator is None and ensemble == "NPT":
        integrator = integrators.LangevinBAOAB(timestep_fs=timestep_fs, temperature_K=start,
                                               friction_per_fs=default_friction_per_fs(),
                                               pressure_GPa=float(pressure_GPa), cell_mode=cell_mode)
    elif integrator is None:
        integrator = (integrators.NVE(timestep_fs=timestep_fs) if nve else
                      integrators.Langevin(timestep_fs=timestep_fs, temperature_K=start,
                                           friction_per_fs=default_friction_per_fs()))
    out = _output(output, structure)
    arguments = {"structure": source, "model": model.label or str(model.path) if isinstance(model, ForceField)
                 else str(model), "head": head, "charge": charge, "spin_multiplicity": spin_multiplicity,
                 "ensemble": ensemble, "temperature_K": temperature_K,
                 **({"pressure_GPa": float(pressure_GPa), "cell_mode": cell_mode}
                    if ensemble == "NPT" and explicit is None else {}),
                 "schedule": schedule.to_data() if schedule is not None else None, "timestep_fs": timestep_fs,
                 "steps": steps, "repeat": list(repeat), "seed": seed, "initial_velocities": initial_velocities,
                 "check": check, "capacity": capacity, "device": device, "skin": skin,
                 "mc": [_mc.record(m) for m in moves] or None,
                 "dispersion": _dispersion.argument(dispersion),
                 "output": {"directory": out.directory, "trajectory_every": out.trajectory_every,
                            "thermo_every": out.thermo_every, "restart_every": out.restart_every}}
    if explicit is not None:                    # so that the record repeats the run: `loupmd run metadata.json`
        arguments["integrator"] = integrators.to_data(explicit)

    # ---- load: from here on the model file is needed ----
    force_field = model if isinstance(model, ForceField) else load(
        model, head, checkpoint=checkpoint, sha256=sha256, trusted=trusted, download=download, charge=charge,
        spin_multiplicity=spin_multiplicity, device=device)
    if force_field.label is None:              # a file outside the table: its hash, so the record can load it again
        arguments.update(model=str(force_field.path), sha256=force_field.sha256)
    transmuted = sorted({z for m in moves if isinstance(m, _mc.Transmute) for z in m.species})
    sim = Simulation(atoms, force_field, integrator=integrator, output=out, seed=seed, check=check, gate=gate,
                     skin=skin, capacity=capacity, elements=transmuted or None, dispersion=dispersion)
    sim.run(steps=steps, schedule=schedule, mc=moves or None)
    sim.save_restart()
    metadata = provenance.collect(sim, source=source, repeat=repeat, arguments=arguments, warnings=warnings)
    provenance.write(metadata, out.directory)
    return RunResult(summary=report.text(metadata), plan=metadata["plan"], gate=sim.gate, simulation=sim,
                     metadata=metadata, output=out.directory)
