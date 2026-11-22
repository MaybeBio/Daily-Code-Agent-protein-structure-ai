"""``lm.Simulation``: an MD run with output, restart and resume.

The engine owns the loop. ``run`` hands it the steps in chunks that end where the host has something to do: a
trajectory frame, a restart point, the end of the call. Thermo rows are written by the device inside the captured
step (``LoupIntegrator.thermo_every``) and read once per chunk; rows and frames go to disk on a background thread.

Steps are counted from the start of the run (``Simulation.step``). The engine counts from its last ``set_state`` or
``import_state`` and writes a thermo row where its own count is a multiple of the cadence; a run resumed between
two thermo steps therefore first runs to the next one without the buffer and moves the state onto a fresh count
there (export and import of the state block, which changes nothing else), so rows stay on multiples of the cadence.
"""
from __future__ import annotations

import dataclasses
import json
import math
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from . import output as _output
from . import skin as _skin
from .config import CapacityConfig, GateConfig, IntegratorConfig, Output
from .errors import (BackendError, CellDivergedError, GateFailed, GateUnavailable, InputError, LoupError,
                     NonFiniteError, PlanRefused, RestartMismatch)
from .forcefield import ForceField, load
from .protocols import Schedule, ScheduleState

RESTART_NAME = "restart.npz"
SIMULATION_NAME = "simulation.json"
RESTART_FORMAT = "loupmd.restart/1"
SIMULATION_FORMAT = "loupmd.simulation/1"
# Thermo rows one engine call may write: the device buffer holds 4,096 unread rows (src/thermo.hpp).
THERMO_ROWS_PER_CALL = 4000
# check="skip": the gate does not run (the default). check="gate": the accuracy gate runs on the structure before
# the first step; failed -> GateFailed, unavailable -> GateUnavailable. check="allow_unavailable": as "gate", but
# an unavailable gate is recorded and the run goes on.
CHECK_MODES = ("skip", "gate", "allow_unavailable")
CAPACITY_MODES = ("auto", "whole", "tiled", "wavefront")
# what the tiled mode integrates (PLAN.md D65, O31): every scheme, the barostats (baoab, mtk, berendsen NPT) on the
# device loop of a library with loup_tiled_get_cell (LAMMPS_TILED_PLAN.md LT6 (a)). On the host loop (a dispersion term
# or a library without loup_tiled_run) only NVE and Langevin; TiledEngine refuses the others there.
TILED_SCHEMES = ("nve", "langevin", "csvr", "nose_hoover", "berendsen", "baoab", "mtk")


def fixed_mask(atoms):
    """The mask of the atoms ASE's ``FixAtoms`` holds in place, or ``None`` without constraints. Any other
    constraint is refused by name: the engine holds atoms in place and nothing else."""
    import numpy as np
    from ase.constraints import FixAtoms

    mask = np.zeros(len(atoms), dtype=bool)
    for constraint in atoms.constraints:
        if not isinstance(constraint, FixAtoms):
            raise PlanRefused(f"the structure has the constraint {type(constraint).__name__}, which is not supported",
                              why="LoupMD holds atoms in place (ase.constraints.FixAtoms) and nothing else",
                              next_step="Remove the constraint, or express it with FixAtoms.")
        mask[constraint.get_indices()] = True
    if mask.all() and len(atoms):
        raise PlanRefused("every atom of the structure is fixed, so nothing would move")
    return mask if mask.any() else None


@dataclass(frozen=True)
class RunSummary:
    """What one ``run`` call did."""

    steps: int
    ms_per_step: float            # the engine's step time, averaged over the call's chunks
    pipelined_steps: int
    rebuilds: int
    dangerous_builds: int
    final_temperature_K: float


class Simulation:
    """``lm.Simulation(atoms, force_field, integrator=lm.integrators.Langevin(...), output=lm.Output("run/"),
    seed=1)``.

    - ``atoms``: the starting structure with its momenta (a structure at rest starts at rest); it is not changed.
      Atoms under ASE's ``FixAtoms`` stay where they are and count no degrees of freedom; other constraints are
      refused;
    - ``force_field``: what ``lm.load`` returned;
    - ``integrator``: an ``lm.integrators`` record;
    - ``output``: an ``lm.Output`` (directory and cadences), or ``None`` for no files;
    - ``seed``: the thermostat's noise seed; ``None`` draws one (``Simulation.seed``, written to
      ``simulation.json``);
    - ``skin``: the neighbour-list skin in A, or ``"auto"``: chosen from how far the atoms move per step, first
      estimated from the temperature and the lightest atom, then corrected once from what the engine measured
      (``loupmd.skin``; ``Simulation.skin_record``). It decides speed only;
    - ``check``: ``"skip"`` (default), ``"gate"`` or ``"allow_unavailable"``: the accuracy gate (the 3x rule
      against MACE float64, ``loupmd.validate``) on rattled copies of the structure before the first step;
      ``gate`` is its ``GateConfig``. ``Simulation.gate`` holds the status and the record;
    - ``capacity``: ``"auto"`` (default), ``"whole"``, ``"tiled"``, ``"wavefront"`` or a ``CapacityConfig``.
      ``"auto"`` plans the execution before the first step and runs a system that does not fit the GPU whole in
      tiles of at most ``receivers`` atoms (``Simulation.execution`` says which); from 2^20 atoms in a cell long
      enough for 12 layers of tiles it uses the wavefront schedule, which ``"wavefront"`` forces (two-layer models;
      S5-T08). The tiled modes run every integrator on the device (PLAN.md O31), the barostats too (Langevin
      BAOAB, MTK and Berendsen NPT; LAMMPS_TILED_PLAN.md LT6 (a)). With a dispersion term the integrator runs on
      the host, NVE and Langevin only.

    - ``elements``: more elements (symbols or atomic numbers) for the run's bundle than the structure has, for
      species events (``set_species``) and transmute moves that bring them in.

    Nothing is exported and no engine is made before the first ``run``; argument errors come before that.
    """

    def __init__(self, atoms, force_field, *, integrator, output=None, seed=None, skin=0.5, check="skip", gate=None,
                 capacity="auto", elements=None, dispersion=None):
        from ase import Atoms

        from . import dispersion as _dispersion

        if not isinstance(atoms, Atoms):
            raise InputError(f"atoms must be an ase.Atoms, got {type(atoms).__name__}")
        if not isinstance(force_field, ForceField):
            raise InputError(f"force_field must be what lm.load returns, got {type(force_field).__name__}",
                             next_step="ff = lm.load(model); lm.Simulation(atoms, ff, ...)")
        if output is not None and not isinstance(output, Output):
            raise InputError(f"output must be an lm.Output or None, got {type(output).__name__}",
                             next_step='output=lm.Output("run/")')
        if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2 ** 63):
            raise InputError(f"seed must be an int from 0 to 2**63 - 1 or None, got {seed!r}")
        fixed = fixed_mask(atoms)                  # refuses other constraints before anything is exported
        if isinstance(integrator, IntegratorConfig):
            self.seed = integrator.seed if seed is None else seed
            self.config = dataclasses.replace(integrator, seed=self.seed)
            if self.config.fixcm and fixed is not None:
                raise PlanRefused("fixcm with fixed atoms", why="the fixed atoms pin the frame already")
        elif hasattr(integrator, "to_config"):
            self.seed = secrets.randbits(62) if seed is None else seed
            self.config = integrator.to_config(seed=self.seed, fixed_atoms=fixed is not None)
        else:
            raise InputError(f"integrator must be an lm.integrators record, got {type(integrator).__name__}",
                             next_step="integrator=lm.integrators.Langevin(temperature_K=300, friction_per_fs=0.01)")
        if self.config.scheme == "csvr" and math.isclose(float(atoms.get_kinetic_energy()), 0.0, rel_tol=0,
                                                         abs_tol=1e-12):
            raise InputError("the structure is at rest, and CSVR rescales the velocities it finds (as ASE's Bussi)",
                             why="a structure at rest has no velocities to rescale",
                             next_step="Draw velocities first: lm.md(..., initial_velocities='maxwell_boltzmann'), "
                                       "or ase.md.velocitydistribution.MaxwellBoltzmannDistribution(atoms, "
                                       "temperature_K=...).")
        if check not in CHECK_MODES:
            raise InputError(f"check={check!r} is not one of {CHECK_MODES}")
        if gate is not None and not isinstance(gate, GateConfig):
            raise InputError(f"gate must be a GateConfig or None, got {type(gate).__name__}")
        if isinstance(capacity, str):
            if capacity not in CAPACITY_MODES:
                raise InputError(f"capacity={capacity!r} is not one of {CAPACITY_MODES} or a CapacityConfig")
            capacity = CapacityConfig(mode=capacity)
        elif not isinstance(capacity, CapacityConfig):
            raise InputError(f"capacity must be one of {CAPACITY_MODES} or a CapacityConfig, got "
                             f"{type(capacity).__name__}")
        self.capacity = capacity
        if capacity.state == "host":
            raise PlanRefused("state='host' is not in this version (plan task S5-T07)",
                              next_step="Use state 'auto' or 'device'.")
        self.execution = None             # {"mode": "whole", "tiled" or "wavefront", "receivers", "plan"} once made
        self.check, self.gate_config = check, gate or GateConfig()
        self.gate = {"status": "skipped"}  # then "passed", "failed" or "unavailable", with the gate's record
        self.totals = {"steps": 0, "engine_ms": 0.0, "wall_s": 0.0, "rebuilds": 0, "pipelined_steps": 0,
                       "dangerous_builds": 0}
        self.setup_s = None                # export, engine, gate and the first force evaluation
        self.relaxation = None             # the RelaxResult of relax(), if it was called
        self.force_field, self.output = force_field, output
        if skin == "auto":
            self.skin = _skin.skin_for_step(_skin.estimate_step_A(atoms, self.config.timestep_fs,
                                                                  self.config.temperature_K, fixed))
            self.skin_record = {"mode": "auto", "estimated_A": self.skin, "measured_step_A": None,
                                "skin_A": self.skin}
        elif isinstance(skin, bool) or not isinstance(skin, (int, float)) or not math.isfinite(skin) or skin < 0:
            raise InputError(f"skin must be a length in A (0 or more) or 'auto', got {skin!r}")
        else:
            self.skin = float(skin)
            self.skin_record = {"mode": "fixed", "skin_A": self.skin}
        self._skin_probe = None            # auto: the step the measurement counts from and the run's highest target
        self.step = 0
        self.status = "new"                # "new", "running", "idle", "non-finite", "closed"
        self._atoms = atoms.copy()
        from .mc import species_number

        extra = {species_number(e) for e in (elements or ())}
        if extra:
            force_field.check_elements(sorted(extra))
        self._extra_elements = tuple(sorted(extra))
        self._elements = set(int(z) for z in atoms.numbers) | extra   # the bundle's elements, once it is made
        self._fixed = fixed
        self._dof = (3 * (len(atoms) - (int(fixed.sum()) if fixed is not None else 0))
                     - (3 if self.config.fixcm else 0))
        self._engine = self._bundle = None
        self._chunks = self._writer = None
        self._npt = self.config.ensemble == "npt"   # the cell is the engine's: rows carry volume and pressure
        if self._npt and fixed is not None:
            raise PlanRefused("a barostat with fixed atoms", why="the cell's scaling would move the fixed atoms")
        self._reference_volume = float(atoms.get_volume()) if self._npt else None   # V0 of the cell limits
        self._base = 0                     # the step at which the engine's own count was zero
        self._resume = None                # (state block, step, output indices) of a resumed run
        self._schedule = None              # the ScheduleState of the schedule attached last
        self._schedule_origin = 0          # the step at which that schedule's position was 0
        self._stopped = None               # the error that ended the run
        self.mc_counters = {}              # Monte Carlo counters by move kind (loupmd.mc.Counters)
        self.mc_moves = None               # the moves of the last run(mc=...), as records
        if capacity.mode in ("tiled", "wavefront"):
            self._check_tiled_scheme()
        # The dispersion term (PLAN.md Stage 6D): resolved against the model, refused when not built; every engine
        # of the run gets it (_install_dispersion).
        self.dispersion = _dispersion.resolve(dispersion, functional=force_field.functional,
                                              family=force_field.family, model=force_field.name)
        self.dispersion_method = _dispersion.runnable(self.dispersion) if self.dispersion is not None else None
        # what the engines get: the record with long_range="auto" replaced by the method the setup check chose
        # (S6-D07, _choose_dispersion), and that check's findings
        self.dispersion_used, self.dispersion_choice = self.dispersion, None

    def _check_tiled_scheme(self, engine=None):
        if self.config.scheme not in TILED_SCHEMES:
            raise PlanRefused(f"the {self.config.scheme} {self.config.ensemble} integrator in tiled mode",
                              why="the tiled mode has no such integrator",
                              next_step="Use an NVE, NVT or NPT integrator, or a cell that fits the GPU whole.")
        runs = getattr(engine, "runs_barostats", None)
        if self._npt and runs is not None and not runs():
            raise PlanRefused(f"the {self.config.scheme} barostat in tiled mode",
                              why="this tiled run integrates on the host (a dispersion term, LOUP_TILED_HOST_MD=1, or a "
                                  "library without the tiled barostats), which keeps the cell fixed",
                              next_step="Run without the dispersion term or LOUP_TILED_HOST_MD, or a cell that fits "
                                        "the GPU whole.")

    # ---------------------------------------------------------------------------------------------- start

    def _start(self):
        import numpy as np

        atoms = self._atoms
        if self.output is not None:        # first: a directory that holds a run is refused before any export
            header = _output.THERMO_HEADER + (_output.NPT_COLUMNS if self._npt else ())
            self._chunks = _output.ChunkedOutput(self.output.directory, atoms, header,
                                                 resume_from=self._resume[2] if self._resume else None)
            self._writer = _output.AsyncWriter()
        if self._resume is None and self.check != "skip":
            self._run_gate()
        if self.skin_record["mode"] == "auto":
            hottest = self.config.temperature_K
            state = self._schedule
            if state is not None:            # a schedule attached before the start: its highest target counts
                hottest = max(state.resolved.target(b) for b in state.resolved.boundaries)
                self.skin = max(self.skin, _skin.skin_for_step(_skin.estimate_step_A(
                    atoms, self.config.timestep_fs, hottest, self._fixed)))
                self.skin_record.update(estimated_A=self.skin, skin_A=self.skin)
            self._skin_probe = {"from": self._resume[1] if self._resume else 0, "hottest_K": hottest}
        engine = self.force_field.new_engine(atoms, self.skin, capacity=self.capacity,
                                             extra_elements=self._extra_elements)
        self._choose_dispersion(engine, atoms)
        self._install_dispersion(engine)
        self.dispersion_cost = self._time_dispersion(engine, atoms)
        self._bundle = self.force_field.last_bundle
        self.execution = dict(self.force_field.last_execution or {"mode": "whole", "receivers": 0, "plan": None})
        if self.execution["mode"] in ("tiled", "wavefront"):
            self._check_tiled_scheme(engine)
        if self._npt and getattr(getattr(engine, "info", lambda: None)(), "has_long_range", False):
            raise PlanRefused("a barostat with a long-range model (MACE-POLAR-1)",
                              why="the model's k-space terms are set up for one cell in this version")
        if self._fixed is not None:
            engine.set_fixed_atoms(self._fixed)
        self._masses = np.asarray(atoms.get_masses(), dtype=float)
        if self._resume is not None:
            blob, self.step, _ = self._resume
            try:
                engine.import_state(blob)
            except BackendError as error:
                raise RestartMismatch("the restart's state does not fit its own record",
                                      why=str(error).splitlines()[0],
                                      next_step="Use the restart file as it was written, or start a new run.") from None
            self._base = self.step
            self._engine = engine
            if self._npt:
                engine.set_reference_volume(self._reference_volume)
        else:
            positions, velocities = atoms.positions, atoms.get_velocities()
            engine.set_state(positions, velocities, atoms.cell.array)
            energy, forces, stress = engine.evaluate(positions, atoms.cell.array, compute_stress=self._npt)
            self._engine = engine
            if self.output is not None:
                self._write_record()
                self._submit_row(self._host_row(0, energy, velocities, stress))
                if self.output.trajectory_every is not None:
                    self._submit_frame(positions.copy(), velocities, forces, energy)
        self.status = "idle"

    def _install_dispersion(self, engine):
        if self.dispersion is None:
            return
        if not hasattr(engine, "set_dispersion"):
            raise PlanRefused("dispersion with this engine", why="it has no set_dispersion",
                              next_step="Run without dispersion.")
        engine.set_dispersion(self.dispersion_used)

    def _choose_dispersion(self, engine, atoms):
        """``long_range="auto"``: the setup check on ``atoms`` (PLAN.md S6-D07, :func:`loupmd.dispersion.choose`)
        with the library's engine; with another engine the first allowed built method, unchecked."""
        if self.dispersion is None:
            return
        from . import _core
        from . import dispersion as _dispersion
        from .tiled_engine import TiledEngine

        if self.dispersion.long_range != "auto":
            self.dispersion_used, self.dispersion_choice = self.dispersion, None
        elif isinstance(engine, (_core.LoupEngine, TiledEngine)):
            from . import _d3

            self.dispersion_used, self.dispersion_choice = _dispersion.choose(
                self.dispersion, atoms, evaluate=_d3.evaluate, cufft=_core.ensure_cufft())
        else:
            cands, left = _dispersion.candidates(self.dispersion)
            name, used = cands[0]
            self.dispersion_used = used
            self.dispersion_choice = {"reference": None, "left_out": left, "chosen": name, "candidates": [
                {"name": name, "long_range": used.long_range, "pair_cutoff_bohr": used.pair_cutoff_bohr,
                 "checked": False, "kept": True, "why": "this engine is not the library's: no setup check"}]}
        self.dispersion_method = self.dispersion_used.long_range

    def recheck_dispersion(self):
        """Repeat the setup check of ``long_range="auto"`` on the structure as it is now and install the method it
        chooses (PLAN.md S6-D07: on request; an event that changes the composition repeats it by itself)."""
        if self.dispersion is None or self.dispersion.long_range != "auto" or self._engine is None:
            return self.dispersion_choice
        atoms = self.atoms
        atoms.calc = None
        if self._npt:
            atoms.set_cell(self._engine.get_cell(), scale_atoms=False)
        self._choose_dispersion(self._engine, atoms)
        self._install_dispersion(self._engine)
        return self.dispersion_choice

    def _time_dispersion(self, engine, atoms):
        """The term's time per force evaluation on the starting structure (ms, the mean of three captured replays),
        and the three-body term's share of it, for the record and the report (PLAN.md S6-D08). Only with the library's
        engine; None otherwise."""
        from . import _core
        from .tiled_engine import TiledEngine

        if self.dispersion is None or not isinstance(engine, (_core.LoupEngine, TiledEngine)):
            return None
        from dataclasses import replace

        from . import _d3

        total = _d3.evaluate(atoms, self.dispersion_used, repeat=3)["ms"]
        cost = {"ms_per_evaluation": round(total, 3)}
        if self.dispersion.three_body:
            pair = _d3.evaluate(atoms, replace(self.dispersion_used, three_body=False), repeat=3)["ms"]
            cost["three_body_ms"] = round(max(total - pair, 0.0), 3)
        return cost

    def _run_gate(self):
        """The accuracy gate on rattled copies of the structure; the run does not start when it fails."""
        from . import validate

        ff = self.force_field
        options = dict(head=ff.head, sha256=ff.sha256, structures=[self._atoms], gate_config=self.gate_config,
                       charge=ff.charge, spin_multiplicity=ff.spin_multiplicity, device=ff.device,
                       environ=ff._environ)
        try:
            record = validate.run_gate(str(ff.path), **options)
        except GateUnavailable as error:
            if self.check == "gate":
                raise
            self.gate = {"status": "unavailable", "why": str(error).splitlines()[0]}
            return
        self.gate = dict(record, status="passed" if record["passed"] else "failed")
        if not record["passed"]:
            worst = record["worst"]
            raise GateFailed(
                f"the accuracy gate failed on this structure: worst ratios energy {worst['energy_ratio']:.2f}, "
                f"force {worst['force_ratio']:.2f}, stress {worst['stress_ratio']:.2f} (a quantity passes up to "
                f"{record['rule']['factor']:g})",
                why="LoupMD's result is further from MACE float64 than three times MACE float32's own deviation",
                gate_record=record)

    def _write_record(self):
        from . import __version__

        ff = self.force_field
        record = {
            "format": SIMULATION_FORMAT, "loupmd": __version__,
            "model": {"label": ff.label, "path": str(ff.path), "head": ff.head, "sha256": ff.sha256,
                      "charge": ff.charge, "spin_multiplicity": ff.spin_multiplicity},
            "integrator": dataclasses.asdict(self.config),
            "output": dataclasses.asdict(self.output),
            "seed": self.seed, "skin": self.skin, "atoms": len(self._atoms),
            "elements": sorted(self._elements),       # the bundle's: a resume exports the same
            # the execution the run took, so that a resume takes it again (the state blocks of the two differ)
            "capacity": {"mode": self.execution["mode"], "receivers": self.execution["receivers"] or None,
                         "memory_fraction": self.capacity.memory_fraction},
            "dispersion": _dispersion_entry(self),
        }
        text = json.dumps(record, indent=2) + "\n"
        _output.write_atomically(Path(self.output.directory) / SIMULATION_NAME,
                                 lambda handle: handle.write(text.encode("utf-8")))

    # -------------------------------------------------------------------------------------------- relax

    def relax(self, optimizer=None, *, fmax=0.05, steps=100_000_000):
        """Relax the starting structure at fixed cell before the first step (``lm.optimize.relax``, with the run's
        dispersion term): the run then starts from the relaxed positions with the structure's velocities. Returns the ``RelaxResult``. Refused
        once steps have run."""
        from . import optimize

        if self._engine is not None or self._resume is not None:
            raise InputError("relax applies to the starting structure, and this run has started",
                             next_step="Relax before the first run(), or relax sim.atoms with lm.optimize.relax.")
        if getattr(optimizer, "cell_filter", None) is not None:
            raise InputError("Simulation.relax relaxes at fixed cell, and the optimiser has a cell filter",
                             why="the simulation's cell is fixed when it is made",
                             next_step="Relax the structure with lm.optimize.relax(..., cell_filter=...) first and "
                                       "make the Simulation from result.atoms.")
        result = optimize.relax(self.force_field, self._atoms, optimizer, fmax=fmax, steps=steps, skin=self.skin,
                                dispersion=self.dispersion)
        self._atoms.set_positions(result.atoms.positions)
        self.relaxation = result
        return result

    # ------------------------------------------------------------------------------------------- output

    def _phase_target(self, step):
        """The phase and target columns of a row: the schedule's at that step, else ``constant`` and the
        thermostat's temperature (``nan`` for NVE)."""
        state = self._schedule
        if state is not None and 0 <= step - self._schedule_origin <= state.total_steps:
            position = step - self._schedule_origin
            return state.resolved.phase(position), state.resolved.target(position)
        temperature = self.config.temperature_K
        return _output.CONSTANT_PHASE, float("nan") if temperature is None else float(temperature)

    def _row(self, step, e_pot, e_kin, temperature, volume=None, pressure=None):
        n = len(self._atoms)
        phase, target = self._phase_target(step)
        row = (int(step), step * self.config.timestep_fs / 1000.0, phase, target, float(temperature), e_pot / n,
               e_kin / n, (e_pot + e_kin) / n)
        if self._npt:                      # _output.NPT_COLUMNS
            row += (float(volume) / n, float(pressure))
        return row

    def _host_row(self, step, e_pot, velocities, stress=None):
        """A row made from the state on the host, as the device makes its rows: used at step 0 and where the
        engine's count starts anew. A variable-cell run passes the stress of that state (eV/A^3); the pressure
        is minus a third of its trace plus the ideal-gas part 2 E_kin / (3 V), as the engine's rows."""
        import numpy as np
        from ase import units

        e_kin = 0.5 * float((self._masses[:, None] * velocities ** 2).sum())
        if not self._npt:
            return self._row(step, e_pot, e_kin, 2 * e_kin / (self._dof * units.kB))
        volume = abs(float(np.linalg.det(self._engine.get_cell())))
        pressure = (-float(np.trace(stress)) / 3.0 + 2.0 * e_kin / (3.0 * volume)) / units.GPa
        return self._row(step, e_pot, e_kin, 2 * e_kin / (self._dof * units.kB), volume, pressure)

    def _state_row(self, step, state):
        """The host row of an engine state (``get_state``). A variable-cell run evaluates once more for the
        stress of that state: the engine's own rows carry it, a state read back does not."""
        stress = None
        if self._npt:
            _, _, stress = self._engine.evaluate(state[0], self._engine.get_cell(), compute_stress=True)
        return self._host_row(step, state[3], state[1], stress)

    def _check_finite(self, row):
        for name, value in zip(_output.THERMO_HEADER, row):
            if isinstance(value, float) and not math.isfinite(value) and name != "target_K":
                raise NonFiniteError(f"non-finite {name} ({value}) at step {row[0]}",
                                     why="the run stops at a non-finite value; it is never patched over")

    def _submit_row(self, row):
        self._check_finite(row)
        self._writer.submit(self._chunks.write_row, row)

    def _submit_frame(self, positions, velocities, forces, energy):
        cell = self._engine.get_cell() if self._npt else None   # a variable-cell run's frames carry their cell
        self._writer.submit(self._chunks.write_frame, positions, velocities, forces, energy, cell)

    # ---------------------------------------------------------------------------------------------- run

    def start(self):
        """What the first ``run`` does before its first step: the gate (if asked), the bundle, the engine and the
        force evaluation of the starting structure, whose row and frame are written. Does nothing when the run
        has started."""
        if self._engine is None and self.status != "closed":
            started = time.perf_counter()
            self._start()
            self.setup_s = time.perf_counter() - started

    def run(self, steps=None, *, schedule=None, mc=None) -> RunSummary:
        """``steps`` more MD steps; returns what the call did. ``Simulation.step`` counts all steps of the run.

        ``schedule`` (an ``lm.protocols`` schedule: ramps and holds) moves the thermostat's target: every step of a
        ramp runs at the target of its end point, as in FastMACE. Without ``steps`` the whole schedule runs (or
        what remains of it); ``steps`` beyond its end are refused, never cut short. Rows and frames are also
        written at the end of every segment. When the schedule is finished the thermostat stays at its last target.

        ``mc``: Monte Carlo moves (an ``lm.mc.Swap``, ``Transmute`` or ``Displace``, or a list of them) for this
        call: after every ``move.every``-th step of the run (counted by ``Simulation.step``) the move makes
        ``move.attempts`` attempts at the thermostat's target temperature. The counters are in
        ``Simulation.mc_counters``, ``metadata.json`` and the restart file.
        """
        if steps is not None and (isinstance(steps, bool) or not isinstance(steps, int) or steps <= 0):
            raise InputError(f"steps must be a positive whole number, got {steps!r}")
        moves = self._mc_moves(mc)
        if self._stopped is not None:
            raise self._stopped
        if self.status == "closed":
            raise InputError("this simulation is closed", next_step="Resume it: lm.Simulation.resume(directory).")
        active = self._schedule if self._schedule is not None and not self._schedule.finished else None
        if schedule is not None:
            if not isinstance(schedule, Schedule):
                raise InputError(f"schedule must be an lm.protocols schedule, got {type(schedule).__name__}",
                                 next_step="schedule=lm.protocols.ramp(0, 400, ps=3) + lm.protocols.hold(400, ps=1)")
            if self.config.temperature_K is None:
                raise InputError("a schedule moves a thermostat's target, and NVE has none",
                                 next_step="Use lm.integrators.Langevin or lm.integrators.CSVR.")
            if active is not None:
                raise InputError(f"a schedule is in progress: {active.remaining} of its {active.total_steps} steps "
                                 "remain", next_step="Finish it with run() first.")
            active = ScheduleState(schedule, self.config.timestep_fs)
        if steps is None:
            if active is None:
                raise InputError("steps is needed: there is no schedule to take the number of steps from")
            steps = active.remaining
        elif active is not None:
            active.steps_to_run(steps)             # refuses steps beyond the schedule before anything runs
        if schedule is not None:
            self._schedule, self._schedule_origin = active, self.step
        self.start()
        started = time.perf_counter()
        try:
            summary = self._advance(steps, moves)
            self.totals["wall_s"] += time.perf_counter() - started
            return summary
        except NonFiniteError as error:
            self.status, self._stopped = "non-finite", error
            self._settle()
            raise

    def _settle(self):
        """After an error: what was written before it stays; nothing is written after it."""
        if self._writer is not None:
            try:
                self._writer.drain()
            except LoupError:
                pass
            self._chunks.flush()

    def _mc_moves(self, mc):
        from . import mc as _mc

        if mc is None:
            return ()
        moves = tuple(mc) if isinstance(mc, (list, tuple)) else (mc,)
        for move in moves:
            _mc.kind(move)                                     # refuses anything else
        if moves and self.config.temperature_K is None:
            raise InputError("Monte Carlo moves need a temperature, and NVE has none",
                             next_step="Use a thermostat (lm.integrators.Langevin, CSVR, ...) with mc=.")
        self.mc_moves = [_mc.record(move) for move in moves]
        return moves

    def _mc_after_steps(self, moves):
        """The moves due at this step, in their order; each block's random stream follows from the seed, the
        step and the move's place, so a resumed run makes the same attempts."""
        import numpy as np
        from ase import units

        for index, move in enumerate(moves):
            if self.step % move.every:
                continue
            kT = units.kB * float(self._phase_target(self.step)[1])
            rng = np.random.default_rng([self.seed, self.step, index])
            self._mc_apply(move, kT, rng)

    def _advance(self, steps, moves=()) -> RunSummary:
        engine, out = self._engine, self.output
        thermo = out.thermo_every if out is not None else None
        frames = out.trajectory_every if out is not None else None
        restarts = out.restart_every if out is not None else None
        end = self.step + steps
        wall_ms, pipelined, rebuilds, dangerous, temperature = 0.0, 0, 0, 0, float("nan")
        self.status = "running"
        while self.step < end:
            n = end - self.step
            for every in (frames, restarts) + tuple(move.every for move in moves):
                if every is not None:
                    n = min(n, every - self.step % every)
            buffered = thermo is not None and self._base % thermo == 0
            if buffered:
                n = min(n, thermo * THERMO_ROWS_PER_CALL)
            elif thermo is not None:
                n = min(n, thermo - self.step % thermo)          # to the next thermo step, without the buffer
            schedule = self._schedule if self._schedule is not None and not self._schedule.finished else None
            target, rate = None, 0.0
            if schedule is not None:                             # one call stays inside one segment: a linear ramp
                position = schedule.step
                n = min(n, schedule.resolved.next_boundary(position) - position)
                target = schedule.resolved.target(position)
                rate = (schedule.resolved.target(position + n) - target) / n
            try:
                stats = engine.run(n, self.config.to_struct(thermo_every=thermo if buffered else 0,
                                                            temperature_K=target, rate_K_per_step=rate))
            except BackendError as error:
                if "non-finite" in str(error):
                    raise NonFiniteError(f"non-finite energy between steps {self.step} and {self.step + n}",
                                         why=str(error).splitlines()[0],
                                         next_step=NonFiniteError.default_next_step) from None
                if "the cell diverged" in str(error):
                    raise CellDivergedError(f"the cell left its limits between steps {self.step} and "
                                            f"{self.step + n}", why=str(error).splitlines()[0],
                                            step=self.step + n) from None
                raise
            self.step += n
            segment_end = False
            if schedule is not None:
                schedule.advance(n)
                segment_end = schedule.step in schedule.resolved.boundaries
                if schedule.finished:                            # the thermostat stays at the last target
                    self.config = dataclasses.replace(self.config, temperature_K=schedule.target_K)
            wall_ms += stats.step_ms * n
            pipelined += stats.pipelined_steps
            rebuilds += stats.rebuilds
            dangerous += stats.dangerous_builds
            for key, value in (("steps", n), ("engine_ms", stats.step_ms * n), ("rebuilds", stats.rebuilds),
                               ("pipelined_steps", stats.pipelined_steps),
                               ("dangerous_builds", stats.dangerous_builds)):
                self.totals[key] += value
            temperature = stats.final_temperature_k
            if buffered:
                for row in engine.read_thermo():
                    self._submit_row(self._row(self._base + int(row["step"]), float(row["e_pot"]),
                                               float(row["e_kin"]), float(row["temp_k"]),
                                               float(row["volume_a3"]), float(row["pressure_gpa"])))
            if moves:
                self._mc_after_steps(moves)                      # before this step's frame and restart
                engine = self._engine
            state = None
            if thermo is not None and not buffered and self.step % thermo == 0:
                state = engine.get_state()
                self._submit_row(self._state_row(self.step, state))
                engine.import_state(engine.export_state())      # the engine's count starts anew on a thermo step
                self._base = self.step
            elif thermo is not None and segment_end and self.step % thermo != 0:
                state = engine.get_state()                       # the end of a segment between two thermo steps
                self._submit_row(self._state_row(self.step, state))
            if frames is not None and (self.step % frames == 0 or segment_end):
                positions, velocities, forces, energy = state or engine.get_state()
                self._submit_frame(positions, velocities, forces, energy)
            if restarts is not None and self.step % restarts == 0:
                self.save_restart()
            if self._skin_probe is not None:
                self._adjust_skin(thermo)
        if self._writer is not None:
            self._writer.drain()
        self.status = "idle"
        return RunSummary(steps=steps, ms_per_step=wall_ms / steps, pipelined_steps=pipelined, rebuilds=rebuilds,
                          dangerous_builds=dangerous, final_temperature_K=temperature)

    def _adjust_skin(self, thermo):
        """``skin="auto"``: once enough steps have run near the run's highest target, replace the estimated skin
        by the one the measured step size asks for. The engine's system is set again with it and the state moved
        across, which changes nothing else; its step count starts anew, so this happens on a thermo step."""
        probe = self._skin_probe
        if self.step - probe["from"] < _skin.PROBE_STEPS or (thermo is not None and self.step % thermo != 0):
            return
        target = self._phase_target(self.step)[1]
        if probe["hottest_K"] and not target >= _skin.PROBE_TARGET_FRACTION * probe["hottest_K"]:
            return                               # still heating: the atoms will be faster than they are now
        self._skin_probe = None
        measured = self._engine.step_displacement()
        self.skin_record.update(measured_step_A=measured, measured_at_step=self.step)
        wanted = _skin.adjusted(self.skin, measured)
        if wanted is None:
            return
        engine = self._engine
        blob = engine.export_state()
        engine.set_system(self._atoms.numbers, self._masses, skin=wanted)
        if self._fixed is not None:
            engine.set_fixed_atoms(self._fixed)
        engine.import_state(blob)
        self._base = self.step
        self.skin = wanted
        self.skin_record["skin_A"] = wanted

    # --------------------------------------------------------------------------------------------- events

    def update(self, *, positions=None, momenta=None, masses=None, species=None, charges=None, total_charge=None,
               spin_multiplicity=None, friction_per_fs=None):
        """Any combination of host changes between two ``run`` calls, as one transaction (plan task S6-T01):
        everything is checked first, then applied and the new state evaluated once; if any part fails, the run is
        left as it was before the call and the error is raised.

        - ``positions`` (A) and ``momenta`` (ASE units), ``(N, 3)``; momenta are taken with the new masses;
        - ``masses`` (amu, ``(N,)``): the momenta stay (as in ASE), so the velocities change, v' = v m / m';
        - ``species`` (atomic numbers or symbols, ``(N,)``): within the elements of the run's bundle (the starting
          structure's), so nothing is exported; an atom whose element changes takes the new element's standard
          mass unless ``masses`` is given too, and keeps its momentum;
        - ``total_charge``, ``spin_multiplicity``: for models that take them (OMOL-0). They are export arguments
          (PLAN.md O7), so the model is loaded again with them and a new bundle and engine are made;
        - ``charges``: per-atom charges are an input of no model LoupMD runs, and are refused;
        - ``friction_per_fs``: the Langevin (or BAOAB) friction in 1/fs.

        Every change but the friction sets the engine's state anew: its step count restarts (the thermo rows stay
        on their cadence) and a barostat's own momentum starts from zero.
        """
        import numpy as np
        from ase.data import atomic_masses, atomic_numbers

        if self._stopped is not None:
            raise self._stopped
        if self.status in ("closed", "running"):
            raise InputError(f"this simulation is {self.status}; events apply between two run() calls")
        if charges is not None:
            raise PlanRefused("per-atom charges as an input",
                              why="no model LoupMD runs takes per-atom charges; OMOL-0 takes the cell's total charge "
                                  "and spin multiplicity (PLAN.md O7)",
                              next_step="Use update(total_charge=..., spin_multiplicity=...) for OMOL-0.")
        n = len(self._atoms)

        def per_atom(value, name, shape):
            array = np.array(value, dtype=float)
            if array.shape != shape or not np.isfinite(array).all():
                raise InputError(f"{name} must be finite numbers of shape {shape}, got shape {array.shape}")
            return array

        # Check everything on the host; nothing has changed yet.
        new_positions = per_atom(positions, "positions", (n, 3)) if positions is not None else None
        new_momenta = per_atom(momenta, "momenta", (n, 3)) if momenta is not None else None
        numbers = np.array(self._atoms.numbers)
        new_masses = np.array(self._atoms.get_masses(), dtype=float)
        if species is not None:
            raw = list(np.atleast_1d(species))
            if len(raw) != n:
                raise InputError(f"species must name {n} atoms, got {len(raw)}")
            try:
                new_numbers = np.array([atomic_numbers[str(s)] if isinstance(s, (str, np.str_)) else int(s)
                                        for s in raw])
            except (KeyError, TypeError, ValueError):
                raise InputError("species must be atomic numbers or element symbols") from None
            if not ((new_numbers >= 1) & (new_numbers < len(atomic_masses))).all():
                raise InputError("species must be atomic numbers of elements")
            outside = sorted(set(new_numbers.tolist()) - self._elements)
            if outside and self._engine is not None:   # before the start the bundle is not made yet
                raise PlanRefused(f"species {outside}, which the run's bundle does not have",
                                  why="the bundle is exported for the starting structure's elements; another would "
                                      "need a new engine",
                                  next_step="Start the run from a structure that holds every element it will take, "
                                            "or save_restart and start a new Simulation from sim.atoms.")
            changed = new_numbers != numbers
            new_masses[changed] = atomic_masses[new_numbers[changed]]
            numbers = new_numbers
        if masses is not None:
            new_masses = per_atom(masses, "masses", (n,))
            if not (new_masses > 0).all():
                raise InputError("masses must be positive")
        config = self.config
        if friction_per_fs is not None:
            if config.friction_per_fs is None:
                raise InputError(f"the {config.scheme} integrator has no friction to change",
                                 next_step="Friction applies to Langevin and BAOAB NPT.")
            config = dataclasses.replace(config, friction_per_fs=float(friction_per_fs))   # checks it
        force_field = self.force_field
        if total_charge is not None or spin_multiplicity is not None:
            ff = self.force_field
            force_field = load(ff.label if ff.label is not None else str(ff.path), ff.head,
                               sha256=None if ff.label is not None else ff.sha256,
                               charge=ff.charge if total_charge is None else total_charge,
                               spin_multiplicity=ff.spin_multiplicity if spin_multiplicity is None else spin_multiplicity,
                               device=ff.device, engine_factory=ff._engine_factory, ensure_bundle=ff._ensure_bundle,
                               probe=ff._probe, environ=ff._environ)
        state_change = (new_positions is not None or new_momenta is not None or species is not None
                        or masses is not None or force_field is not self.force_field)
        if self._engine is None:              # before the first step: the starting structure takes the change
            atoms = self._atoms
            momenta_now = atoms.get_momenta()
            atoms.numbers = numbers
            atoms.set_masses(new_masses)
            atoms.set_momenta(new_momenta if new_momenta is not None else momenta_now)
            if new_positions is not None:
                atoms.set_positions(new_positions)
            self._elements |= set(numbers.tolist())
            self.config, self.force_field = config, force_field
            return
        if state_change:
            self._apply_state_event(new_positions, new_momenta, numbers, new_masses, force_field)
        if config is not self.config:
            self.config = config
            if self.output is not None:
                self._write_record()

    def set_positions(self, positions):
        """Set every atom's position (A, ``(N, 3)``), one event (``update``); the momenta stay."""
        self.update(positions=positions)

    def set_momenta(self, momenta):
        """Set every atom's momentum (ASE units, ``(N, 3)``), one event (``update``)."""
        self.update(momenta=momenta)

    def set_masses(self, masses):
        """Set every atom's mass (amu, ``(N,)``), one event (``update``); the momenta stay, as in ASE."""
        self.update(masses=masses)

    def set_species(self, species):
        """Set every atom's element (atomic numbers or symbols, ``(N,)``), one event (``update``): within the
        run's bundle, with no export; atoms whose element changes take its standard mass."""
        self.update(species=species)

    def set_charges(self, charges=None, *, total_charge=None, spin_multiplicity=None):
        """The cell's total charge and spin multiplicity (OMOL-0), one event (``update``): the model is loaded
        again with them. Per-atom ``charges`` are refused."""
        if charges is None and total_charge is None and spin_multiplicity is None:
            raise InputError("set_charges needs total_charge or spin_multiplicity")
        self.update(charges=charges, total_charge=total_charge, spin_multiplicity=spin_multiplicity)

    def set_friction(self, friction_per_fs):
        """Set the Langevin (or BAOAB) friction in 1/fs, one event (``update``)."""
        self.update(friction_per_fs=friction_per_fs)

    def _mc_block(self, move, kT, rng, attempts=None):
        """One block of Monte Carlo attempts on the engine's state (``loupmd.mc``). The chain's last state is set
        on the engine (or, with nothing accepted, the state block put back); the engine's step count restarts."""
        if self._stopped is not None:
            raise self._stopped
        if self.status in ("closed", "running"):
            raise InputError(f"this simulation is {self.status}; Monte Carlo moves apply between two run() calls")
        self.start()
        return self._mc_apply(move, kT, rng, attempts)

    def _mc_apply(self, move, kT, rng, attempts=None):
        import numpy as np

        from . import mc

        engine = self._engine
        positions, velocities, _, energy = engine.get_state()
        cell = engine.get_cell() if self._npt else np.asarray(self._atoms.cell.array, dtype=float)
        if isinstance(move, mc.Transmute):
            return self._transmute_block(move, kT, rng, attempts, positions, velocities, cell, float(energy))
        numbers = np.array(self._atoms.numbers)
        if self._fixed is not None:
            numbers[self._fixed] = 0                      # fixed atoms stay where they are: never chosen
        blob = engine.export_state()
        try:
            if isinstance(move, mc.Displace):
                positions, energy, counters = mc.displace_block(engine, move, positions, np.flatnonzero(numbers),
                                                                cell, float(energy), kT, rng, attempts)
            else:
                positions, velocities, energy, counters = mc.swap_block(engine, move, positions, velocities,
                                                                         numbers, cell, float(energy), kT, rng,
                                                                         attempts)
            if counters.accepted:
                engine.set_state(positions, velocities, cell)
                if self._npt:
                    engine.set_reference_volume(self._reference_volume)
            else:
                engine.import_state(blob)
        except BaseException:
            engine.import_state(blob)
            raise
        self._base = self.step
        self.mc_counters.setdefault(mc.kind(move), mc.Counters()).add(counters)
        return mc.SwapResult(counters, float(energy))

    def _transmute_block(self, move, kT, rng, attempts, positions, velocities, cell, energy):
        """Transmute attempts: each sets the engine's system for the trial composition and runs the energy-only
        pass; the chain's last composition and state are set on the engine at the end (D72)."""
        import numpy as np
        from ase.data import atomic_masses

        from . import mc

        outside = sorted(set(move.species) - self._elements)
        if outside:
            raise PlanRefused(f"Transmute to element(s) {outside}, which the run's bundle does not have",
                              next_step="Name them when the run is made: lm.Simulation(..., elements=[...]).")
        engine = self._engine
        numbers, masses = np.array(self._atoms.numbers), np.array(self._masses, dtype=float)
        eligible = np.flatnonzero(np.isin(numbers, move.species)
                                  & (~self._fixed if self._fixed is not None else True))
        if not len(eligible):
            raise InputError(f"no atom of the structure is one of Transmute.species {move.species}")
        blob = engine.export_state()
        counters = mc.Counters()
        held = numbers                                    # the composition the engine holds

        def put(nums, ms, vel):
            started = time.perf_counter()
            engine.set_system(nums, ms, skin=self.skin)
            if self._fixed is not None:
                engine.set_fixed_atoms(self._fixed)
            engine.set_state(positions, vel, cell)
            if self._npt:
                engine.set_reference_volume(self._reference_volume)
            counters.setup_s += time.perf_counter() - started

        try:
            for _ in range(move.attempts if attempts is None else attempts):
                i = int(rng.choice(eligible))
                old = int(numbers[i])
                new = int(rng.choice([s for s in move.species if s != old]))
                trial_numbers, trial_masses, trial_velocities = numbers.copy(), masses.copy(), velocities.copy()
                trial_numbers[i], trial_masses[i] = new, atomic_masses[new]
                trial_velocities[i] *= math.sqrt(masses[i] / trial_masses[i])    # its kinetic energy kept
                put(trial_numbers, trial_masses, trial_velocities)
                held = trial_numbers
                trial_energy = mc._energy(engine, positions, cell)
                counters.attempted += 1
                if not math.isfinite(trial_energy):
                    counters.rejected_nonfinite += 1
                    continue
                excess = (trial_energy - energy) - (move.mu_of(new) - move.mu_of(old))
                if excess <= 0.0 or rng.random() < math.exp(-excess / kT):
                    numbers, masses, velocities, energy = trial_numbers, trial_masses, trial_velocities, trial_energy
                    counters.accepted += 1
            if counters.accepted:
                if not np.array_equal(held, numbers):
                    put(numbers, masses, velocities)
            elif not np.array_equal(held, numbers):
                put(numbers, masses, velocities)
                engine.import_state(blob)
        except BaseException:
            put(np.array(self._atoms.numbers), np.array(self._masses, dtype=float), velocities)
            engine.import_state(blob)
            raise
        if counters.accepted:
            self._atoms.numbers = numbers
            self._atoms.set_masses(masses)
            self._masses = masses
            if self._chunks is not None:
                self._writer.submit(self._chunks.set_composition, numbers, masses)
        self._base = self.step
        self.mc_counters.setdefault("transmute", mc.Counters()).add(counters)
        return mc.SwapResult(counters, float(energy))

    def _apply_state_event(self, new_positions, new_momenta, numbers, new_masses, force_field):
        """The engine part of an event: the state read back, changed and set, then one evaluation. Any failure
        puts the engine back where it was (its state block) and raises."""
        import numpy as np

        engine = self._engine
        positions, velocities, _, _ = engine.get_state()
        cell = engine.get_cell() if self._npt else np.asarray(self._atoms.cell.array, dtype=float)
        momenta = new_momenta if new_momenta is not None else velocities * self._masses[:, None]
        positions = new_positions if new_positions is not None else positions
        velocities = momenta / new_masses[:, None]
        blob = engine.export_state()
        recomposed = (not np.array_equal(numbers, self._atoms.numbers)
                      or not np.array_equal(new_masses, self._masses))
        new_engine = None
        try:
            if force_field is not self.force_field:
                atoms = self._atoms.copy()
                atoms.numbers = numbers
                atoms.set_masses(new_masses)
                new_engine = force_field.new_engine(atoms, self.skin, capacity=self.capacity,
                                                    extra_elements=self._extra_elements)
                self._install_dispersion(new_engine)
                target = new_engine
                if self._fixed is not None:
                    target.set_fixed_atoms(self._fixed)
            else:
                target = engine
                if recomposed:
                    target.set_system(numbers, new_masses, skin=self.skin)
                    if self._fixed is not None:
                        target.set_fixed_atoms(self._fixed)
            target.set_state(positions, velocities, cell)
            if self._npt:
                target.set_reference_volume(self._reference_volume)
            energy, forces, _ = target.evaluate(positions, cell, compute_stress=self._npt)
            if not (np.isfinite(energy) and np.isfinite(forces).all()):
                raise NonFiniteError("the event's state has a non-finite energy or forces",
                                     why="an event is applied only when its state evaluates to finite numbers")
        except BaseException:
            new_engine = None
            if recomposed and force_field is self.force_field:
                engine.set_system(self._atoms.numbers, self._masses, skin=self.skin)
                if self._fixed is not None:
                    engine.set_fixed_atoms(self._fixed)
                if self._npt:
                    engine.set_reference_volume(self._reference_volume)
            engine.import_state(blob)
            raise
        # Commit.
        if new_engine is not None:
            self._engine = new_engine
            self._bundle = force_field.last_bundle
            self.force_field = force_field
        if recomposed:
            self._atoms.numbers = numbers
            self._atoms.set_masses(new_masses)
            self._masses = np.array(new_masses, dtype=float)
            if self._chunks is not None:
                self._writer.submit(self._chunks.set_composition, numbers, new_masses)
            if self.dispersion is not None and self.dispersion.long_range == "auto":
                self.recheck_dispersion()      # S6-D07: the choice is made for the composition it was checked on
        self._base = self.step
        if self.output is not None:       # simulation.json names the model's charge: a resume takes the new one
            self._write_record()

    @property
    def atoms(self):
        """The structure as it is now: a copy with positions, momenta and a calculator holding the potential
        energy and the forces. Before the first ``run`` it is the starting structure."""
        atoms = self._atoms.copy()
        if self._engine is None:
            return atoms
        from ase.calculators.singlepoint import SinglePointCalculator

        positions, velocities, forces, energy = self._engine.get_state()
        if self._npt:
            atoms.set_cell(self._engine.get_cell(), scale_atoms=False)
        atoms.set_positions(positions)
        atoms.set_velocities(velocities)
        atoms.calc = SinglePointCalculator(atoms, energy=energy, forces=forces)
        return atoms

    def save_restart(self, path=None) -> Path:
        """Write the restart file (``restart.npz`` in the output directory unless ``path`` is given). With output,
        this is a chunk boundary: rows and frames up to this step are closed and fsynced first."""
        import numpy as np

        if self._engine is None:
            raise InputError("nothing has run yet, so there is no state to save")
        if path is None:
            if self.output is None:
                raise InputError("save_restart needs a path when the simulation has no output directory",
                                 next_step='sim.save_restart("restart.npz")')
            path = Path(self.output.directory) / RESTART_NAME
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        indices = dict(output_chunk=-1, output_rows=0, output_frames=0)
        if self._chunks is not None:
            self._writer.drain()
            indices = self._chunks.restart_point()
        positions, velocities, _, energy = self._engine.get_state()
        atoms = self._atoms
        cell = self._engine.get_cell() if self._npt else np.asarray(atoms.cell.array, dtype=float)
        extra = {"reference_volume_A3": np.array(self._reference_volume)} if self._npt else {}
        arrays = dict(format=np.array(RESTART_FORMAT), step=np.array(self.step, dtype=np.int64),
                      blob=np.frombuffer(self._engine.export_state(), dtype=np.uint8),
                      model_sha256=np.array(self.force_field.sha256), seed=np.array(self.seed, dtype=np.int64),
                      numbers=np.asarray(atoms.numbers, dtype=np.int64), masses=self._masses,
                      pbc=np.asarray(atoms.pbc, dtype=bool), cell=cell, **extra,
                      fixed=(self._fixed if self._fixed is not None else np.zeros(len(atoms), dtype=bool)),
                      positions=positions, velocities=velocities, potential_energy=np.array(energy),
                      mc_counters=np.array(json.dumps({k: c.as_dict() for k, c in self.mc_counters.items()})),
                      schedule=np.array(json.dumps(None if self._schedule is None else dict(
                          self._schedule.to_restart(), origin=self._schedule_origin))),
                      temperature_K=np.array(float("nan") if self.config.temperature_K is None
                                             else self.config.temperature_K),
                      **{key: np.array(value, dtype=np.int64) for key, value in indices.items()})
        return _output.write_atomically(path, lambda handle: np.savez(handle, **arrays))

    def close(self):
        """Finish writing and close the output files. The run can be resumed from its last restart."""
        if self._writer is not None:
            self._writer.close(raise_errors=self._stopped is None)
            self._chunks.close()
            self._writer = self._chunks = None
        self._engine = None
        self.status = "closed"

    # --------------------------------------------------------------------------------------------- resume

    @classmethod
    def resume(cls, directory, *, force_field=None, restart=None):
        """Continue the run of ``directory`` from its restart file: ``sim = lm.Simulation.resume("run/")``.

        The model is loaded again as ``simulation.json`` names it (a label through the label table; a file by its
        path with the recorded SHA-256), or pass ``force_field``. A restart of another model, a state that does
        not fit, or output chunks that do not fit the restart raise ``RestartMismatch`` before anything is
        changed.
        """
        import numpy as np
        from ase import Atoms

        directory = Path(directory)
        restart = Path(restart) if restart is not None else directory / RESTART_NAME
        record_file = directory / SIMULATION_NAME
        if not restart.is_file() or not record_file.is_file():
            missing = restart if not restart.is_file() else record_file
            raise RestartMismatch(f"no restart to resume in {directory}: {missing.name} is missing",
                                  next_step="A run writes it every Output.restart_every steps and when "
                                            "save_restart() is called.")
        record = json.loads(record_file.read_text())
        try:
            with np.load(restart, allow_pickle=False) as data:
                data = {key: data[key] for key in data.files}
        except (ValueError, OSError, EOFError) as error:        # pickled arrays, or no npz file at all
            raise RestartMismatch(f"{restart} is not a restart this version reads",
                                  why=str(error).splitlines()[0]) from None
        found_format = str(data["format"]) if "format" in data else None
        if found_format != RESTART_FORMAT or record.get("format") != SIMULATION_FORMAT:
            raise RestartMismatch(f"{restart} has format {found_format!r} and {record_file.name} "
                                  f"{record.get('format')!r}; this version reads {RESTART_FORMAT!r} and "
                                  f"{SIMULATION_FORMAT!r}")
        saved_sha = str(data["model_sha256"])
        model = record["model"]
        if force_field is None:
            try:
                if model["label"] is not None:
                    force_field = load(model["label"], model["head"], charge=model["charge"],
                                       spin_multiplicity=model["spin_multiplicity"])
                else:
                    force_field = load(model["path"], model["head"], sha256=saved_sha, charge=model["charge"],
                                       spin_multiplicity=model["spin_multiplicity"])
            except LoupError as error:
                raise RestartMismatch(f"the model of the restart in {directory} cannot be loaded again",
                                      why=str(error).splitlines()[0],
                                      next_step="Pass force_field= with the model the run was written with.") from None
        if force_field.sha256 != saved_sha:
            raise RestartMismatch(
                f"the restart in {directory} was written with the model of SHA-256 {saved_sha}; "
                f"{force_field.path.name} has {force_field.sha256}",
                next_step=RestartMismatch.default_next_step)
        atoms = Atoms(numbers=data["numbers"], positions=data["positions"], cell=data["cell"], pbc=data["pbc"])
        atoms.set_masses(data["masses"])
        atoms.set_velocities(data["velocities"])
        if data["fixed"].any():
            from ase.constraints import FixAtoms

            atoms.set_constraint(FixAtoms(mask=data["fixed"]))
        out = Output(**record["output"]) if record.get("output") else None
        if out is not None and Path(out.directory).resolve() != directory.resolve():
            out = dataclasses.replace(out, directory=str(directory))     # the directory was moved or is relative
        capacity = CapacityConfig(**record["capacity"]) if record.get("capacity") else "whole"   # older records
        sim = cls(atoms, force_field, integrator=IntegratorConfig(**record["integrator"]), output=out,
                  seed=int(data["seed"]), skin=float(record["skin"]), capacity=capacity,
                  elements=record.get("elements"), dispersion=record.get("dispersion"))
        stored = json.loads(str(data["schedule"]))
        if stored is not None:
            sim._schedule_origin = int(stored.pop("origin"))
            sim._schedule = ScheduleState.from_restart(stored)
        if sim.config.temperature_K is not None:                 # a finished schedule left the thermostat there
            sim.config = dataclasses.replace(sim.config, temperature_K=float(data["temperature_K"]))
        if sim._npt and "reference_volume_A3" in data:
            sim._reference_volume = float(data["reference_volume_A3"])
        if "mc_counters" in data:
            from .mc import Counters

            sim.mc_counters = {k: Counters(**v) for k, v in json.loads(str(data["mc_counters"])).items()}
        indices = {key: int(data[key]) for key in _output.OUTPUT_KEYS}
        sim._resume = (data["blob"].tobytes(), int(data["step"]), indices if out is not None else None)
        sim._start()
        return sim


def _dispersion_entry(sim):
    """The run's dispersion record as metadata and the run record hold it, with the summation method it uses."""
    if getattr(sim, "dispersion", None) is None:
        return None
    from . import dispersion as _dispersion

    entry = dict(_dispersion.entry(sim.dispersion), long_range_used=sim.dispersion_method)
    if getattr(sim, "dispersion_choice", None) is not None:
        entry["long_range_choice"] = sim.dispersion_choice
    if getattr(sim, "dispersion_cost", None):
        entry["cost"] = sim.dispersion_cost
    return entry
