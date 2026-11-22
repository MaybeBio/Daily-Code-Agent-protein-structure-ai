"""``Simulation`` (plan tasks S3-T04 and S3-T05) on the fake engine of ``fake_core.py``. Deterministic, so runs
can be compared exactly. Needs neither a GPU nor the library; ``tests/gpu/test_simulation_gpu.py`` has the real
runs."""
from __future__ import annotations

import json
import pickle

import numpy as np
import pytest
from ase import units
from ase.build import bulk
from fake_core import SpringEngine

import loupmd
from loupmd import _core, integrators, output, protocols, simulation
from loupmd.config import IntegratorConfig, Output
from loupmd.errors import InputError, NonFiniteError, PlanRefused, RestartMismatch

@pytest.fixture
def setup(tmp_path):
    checkpoint = tmp_path / "some.model"
    checkpoint.write_bytes(b"never unpickled here")
    SpringEngine.made, SpringEngine.poison_at = [], None

    def ensure_bundle(model_path, numbers, head=None, charge=None, spin_multiplicity=None, environ=None):
        return model_path.with_name("bundle.loup")

    def force_field(path=checkpoint):
        return loupmd.load(str(path), trusted=True, engine_factory=SpringEngine, ensure_bundle=ensure_bundle,
                           probe=lambda p: None)

    atoms = bulk("NaCl", "rocksalt", a=5.64, cubic=True).repeat((2, 1, 1))          # 16 atoms
    atoms.set_velocities(np.random.default_rng(3).normal(0.0, 0.02, atoms.positions.shape))

    def make(directory=None, integrator=None, **more):
        out = Output(str(tmp_path / directory), **more) if directory else None
        return loupmd.Simulation(atoms, force_field(), integrator=integrator or integrators.NVE(timestep_fs=1.0),
                                 output=out, seed=7)

    make.atoms, make.force_field, make.tmp_path, make.checkpoint = atoms, force_field, tmp_path, checkpoint
    return make


def _steps(directory):
    return [int(row[0]) for row in output.read_thermo(directory)[1]]


# ------------------------------------------------------------------------------------------------ the run

def test_a_run_writes_fastmace_s_rows_and_frames(setup):
    sim = setup("run")
    summary = sim.run(steps=100)
    directory = setup.tmp_path / "run"
    assert sim.step == 100 and summary.steps == 100 and summary.pipelined_steps == 95 and summary.rebuilds == 5
    assert _steps(directory) == [0, 20, 40, 60, 80, 100]                     # step 0, then every 20
    frames = output.read_frames(directory)
    assert len(frames) == 6
    engine, = SpringEngine.made
    position, velocity, forces, energy = engine.get_state()
    assert np.array_equal(frames[-1].positions, position) and frames[-1].get_potential_energy() == energy
    assert np.allclose(frames[-1].get_momenta(), setup.atoms.get_masses()[:, None] * velocity)
    assert np.array_equal(frames[0].positions, setup.atoms.positions)
    header, rows = output.read_thermo(directory)
    assert header == list(output.THERMO_HEADER)
    last = rows[-1]
    assert float(last[1]) == pytest.approx(0.1) and last[2] == "constant" and last[3] == "nan"   # NVE: no target
    assert float(last[5]) == pytest.approx(energy / 16)
    assert float(last[7]) == pytest.approx(float(last[5]) + float(last[6]))
    # The first row is made on the host from the state at step 0; energy is conserved to the integrator's order.
    assert abs(float(rows[0][7]) - float(last[7])) < 1e-5
    # One force evaluation before the first step, none per call after it; chunks of 20 steps with thermo on.
    assert engine.log[:2] == ["set_state", "evaluate"] and "force pass" not in engine.log
    assert [entry for entry in engine.log if isinstance(entry, tuple)] == [("run", 20, _core.LOUP_NVE, 20)] * 5
    # No restart point was due (every 10,000 steps) and none was asked for: one chunk, no restart file.
    assert sorted(p.name for p in directory.iterdir()) == ["simulation.json", "thermo.0.csv", "trajectory.0.traj"]


def test_rows_between_frames_come_from_the_device_buffer(setup):
    sim = setup("run", thermo_every=5, trajectory_every=20, restart_every=None)
    sim.run(steps=40)
    directory = setup.tmp_path / "run"
    assert _steps(directory) == list(range(0, 41, 5)) and len(output.read_frames(directory)) == 3
    assert [e for e in SpringEngine.made[0].log if isinstance(e, tuple)] == [("run", 20, _core.LOUP_NVE, 5)] * 2
    assert not (directory / "restart.npz").exists()


def test_without_a_trajectory_the_chunks_are_as_long_as_the_buffer_allows(setup, monkeypatch):
    monkeypatch.setattr(simulation, "THERMO_ROWS_PER_CALL", 10)
    sim = setup("run", thermo_every=2, trajectory_every=None, restart_every=None)
    sim.run(steps=50)
    assert _steps(setup.tmp_path / "run") == list(range(0, 51, 2)) and output.read_frames(setup.tmp_path / "run") == []
    assert [e[1] for e in SpringEngine.made[0].log if isinstance(e, tuple)] == [20, 20, 10]


def test_two_calls_equal_one(setup):
    one = setup("one")
    one.run(steps=100)
    two = setup("two")
    two.run(steps=60)
    two.run(steps=40)
    assert output.read_thermo(setup.tmp_path / "one") == output.read_thermo(setup.tmp_path / "two")
    for a, b in zip(output.read_frames(setup.tmp_path / "one"), output.read_frames(setup.tmp_path / "two")):
        assert np.array_equal(a.positions, b.positions) and np.array_equal(a.get_momenta(), b.get_momenta())


def test_a_run_without_output_writes_nothing_and_gives_the_atoms(setup):
    sim = setup()
    sim.run(steps=30)
    engine, = SpringEngine.made
    assert [e for e in engine.log if isinstance(e, tuple)] == [("run", 30, _core.LOUP_NVE, 0)]
    current = sim.atoms
    assert np.array_equal(current.positions, engine.pos) and current.get_potential_energy() == engine._energy()
    assert np.allclose(current.get_velocities(), engine.vel)
    assert not np.array_equal(current.positions, setup.atoms.positions)       # the caller's atoms are untouched
    assert list(setup.tmp_path.iterdir()) == [setup.checkpoint]


def test_langevin_reaches_the_engine_with_its_settings(setup):
    sim = setup("run", integrator=integrators.Langevin(timestep_fs=2.0, temperature_K=350.0, friction_per_fs=0.02))
    sim.run(steps=20)
    engine, = SpringEngine.made
    assert [e for e in engine.log if isinstance(e, tuple)] == [("run", 20, _core.LOUP_LANGEVIN, 20)]
    rows = output.read_thermo(setup.tmp_path / "run")[1]
    assert rows[-1][3] == "350.0" and float(rows[-1][1]) == pytest.approx(0.04)
    record = json.loads((setup.tmp_path / "run" / "simulation.json").read_text())
    assert record["integrator"] == {"ensemble": "nvt", "scheme": "langevin", "timestep_fs": 2.0,
                                    "temperature_K": 350.0, "friction_per_fs": 0.02, "tau_fs": None, "tchain": None,
                                    "tloop": None, "mass_temperature_K": None, "pressure_GPa": None,
                                    "taup_fs": None, "compressibility_per_GPa": None, "mask": None,
                                    "cell_mode": None, "pchain": None, "ploop": None, "seed": 7, "fixcm": True}
    assert record["seed"] == 7 and record["model"]["sha256"] == sim.force_field.sha256


# ----------------------------------------------------------------------------------------------- refusals

def test_argument_errors_come_before_anything_is_exported(setup):
    ff = setup.force_field()
    with pytest.raises(InputError, match="integrator"):
        loupmd.Simulation(setup.atoms, ff, integrator="langevin")
    with pytest.raises(InputError, match="force_field"):
        loupmd.Simulation(setup.atoms, "omat0-medium", integrator=integrators.NVE(timestep_fs=1.0))
    with pytest.raises(InputError, match="output"):
        loupmd.Simulation(setup.atoms, ff, integrator=integrators.NVE(timestep_fs=1.0), output="run/")
    with pytest.raises(InputError, match="seed"):
        loupmd.Simulation(setup.atoms, ff, integrator=integrators.NVE(timestep_fs=1.0), seed=-1)
    sim = setup()
    for steps in (0, -5, 2.5):
        with pytest.raises(InputError, match="steps must be a positive whole number"):
            sim.run(steps=steps)
    with pytest.raises(PlanRefused, match="fixcm=True with fixed atoms"):
        integrators.Langevin(temperature_K=300, friction_per_fs=0.01, fixcm=True).to_config(seed=1, fixed_atoms=True)
    assert SpringEngine.made == []


def test_a_directory_that_holds_a_run_is_refused(setup):
    setup("run").run(steps=20)
    with pytest.raises(InputError, match="already holds output chunks"):
        setup("run").run(steps=20)


def test_a_non_finite_energy_stops_the_run(setup):
    SpringEngine.poison_at = 40
    sim = setup("run")
    with pytest.raises(NonFiniteError, match="step 40"):
        sim.run(steps=100)
    assert sim.status == "non-finite" and _steps(setup.tmp_path / "run") == [0, 20]
    with pytest.raises(NonFiniteError):
        sim.run(steps=20)                                           # it stays stopped


# ------------------------------------------------------------------------------------------------ restart

def test_restart_points_end_chunks_and_resume_continues_the_run(setup):
    whole = setup("whole", restart_every=40)
    whole.run(steps=100)
    part = setup("part", restart_every=40)
    part.run(steps=50)                                              # a restart point at 40
    part.save_restart()                                             # and one asked for at 50
    saved = SpringEngine.made[-1].export_state()
    part.close()
    directory = setup.tmp_path / "part"
    assert output.chunk_indices(directory) == [0, 1, 2]
    resumed = loupmd.Simulation.resume(directory, force_field=setup.force_field())
    assert resumed.step == 50 and SpringEngine.made[-1].export_state() == saved      # the state, bitwise
    resumed.run(steps=50)
    assert output.read_thermo(directory) == output.read_thermo(setup.tmp_path / "whole")
    for a, b in zip(output.read_frames(directory), output.read_frames(setup.tmp_path / "whole")):
        assert np.array_equal(a.positions, b.positions) and np.array_equal(a.get_momenta(), b.get_momenta())
    assert resumed.atoms.positions.tolist() == whole.atoms.positions.tolist()


def test_a_restart_between_thermo_steps_keeps_the_rows_on_multiples_of_the_cadence(setup):
    whole = setup("whole", restart_every=None)
    whole.run(steps=100)
    part = setup("part", restart_every=None)
    part.run(steps=50)
    part.save_restart()
    part.close()
    resumed = loupmd.Simulation.resume(setup.tmp_path / "part", force_field=setup.force_field())
    resumed.run(steps=50)
    assert _steps(setup.tmp_path / "part") == [0, 20, 40, 60, 80, 100]
    engine = SpringEngine.made[-1]
    # 10 steps without the buffer to step 60, the state moved onto a fresh step count there, then 20 + 20.
    assert [e for e in engine.log if e != "set_state"] == ["import_state", "force pass", ("run", 10, 0, 0),
                                                           "import_state", "force pass", ("run", 20, 0, 20),
                                                           ("run", 20, 0, 20)]
    assert np.array_equal(resumed.atoms.positions, whole.atoms.positions)
    assert output.read_thermo(setup.tmp_path / "part") == output.read_thermo(setup.tmp_path / "whole")


def test_resume_rebuilds_the_run_from_its_directory(setup, monkeypatch):
    sim = setup("run", integrator=integrators.Langevin(temperature_K=300.0, friction_per_fs=0.01), thermo_every=10)
    sim.run(steps=40)
    sim.save_restart()
    sim.close()
    made = {}

    def fake_load(model, head=None, **options):
        made.update(model=model, head=head, options=options)
        return setup.force_field()

    monkeypatch.setattr(simulation, "load", fake_load)
    resumed = loupmd.Simulation.resume(setup.tmp_path / "run")
    assert made["model"] == str(setup.checkpoint.resolve()) and made["options"]["sha256"] == sim.force_field.sha256
    assert resumed.step == 40 and resumed.seed == 7 and resumed.output.thermo_every == 10
    assert resumed.config == IntegratorConfig(temperature_K=300.0, friction_per_fs=0.01, seed=7, fixcm=True)
    assert np.array_equal(resumed.atoms.numbers, setup.atoms.numbers) and all(resumed.atoms.pbc)


def test_a_restart_of_another_model_or_atom_count_is_refused(setup, tmp_path):
    sim = setup("run")
    sim.run(steps=20)
    sim.save_restart()
    sim.close()
    directory = setup.tmp_path / "run"
    other = tmp_path / "other.model"
    other.write_bytes(b"another file")
    with pytest.raises(RestartMismatch) as caught:
        loupmd.Simulation.resume(directory, force_field=setup.force_field(other))
    assert "was written with the model of SHA-256" in str(caught.value) and "other.model" in str(caught.value)
    # A restart whose state block holds another number of atoms than its own record.
    data = dict(np.load(directory / "restart.npz", allow_pickle=False))
    data["blob"] = np.frombuffer(pickle.dumps((15,) + pickle.loads(data["blob"].tobytes())[1:]), dtype=np.uint8)
    np.savez(directory / "restart.npz", **data)
    with pytest.raises(RestartMismatch, match="does not fit"):
        loupmd.Simulation.resume(directory, force_field=setup.force_field())
    with pytest.raises(RestartMismatch, match="no restart"):
        loupmd.Simulation.resume(tmp_path / "nothing-here", force_field=setup.force_field())
    assert _steps(directory) == [0, 20]                             # a refused resume deletes nothing
    # A restart.npz of another program is refused as a mismatch too, not with a KeyError or a ValueError.
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "simulation.json").write_text("{}")
    np.savez(foreign / "restart.npz", positions=np.zeros((2, 3)))
    with pytest.raises(RestartMismatch, match="has format None"):
        loupmd.Simulation.resume(foreign, force_field=setup.force_field())
    np.savez(foreign / "restart.npz", state=np.array([{"a": 1}], dtype=object))
    with pytest.raises(RestartMismatch, match="is not a restart this version reads"):
        loupmd.Simulation.resume(foreign, force_field=setup.force_field())


def test_save_restart_without_output_needs_a_path(setup, tmp_path):
    sim = setup()
    sim.run(steps=10)
    with pytest.raises(InputError, match="path"):
        sim.save_restart()
    target = sim.save_restart(tmp_path / "state" / "restart.npz")
    data = np.load(target, allow_pickle=False)
    assert int(data["step"]) == 10 and str(data["format"]) == "loupmd.restart/1"
    assert str(data["model_sha256"]) == sim.force_field.sha256 and int(data["output_chunk"]) == -1


# ----------------------------------------------------------------------------------------------- schedules

LANGEVIN = integrators.Langevin(timestep_fs=1.0, temperature_K=100.0, friction_per_fs=0.01)


def _columns(directory):
    return [(int(row[0]), row[2], float(row[3])) for row in output.read_thermo(directory)[1]]


def test_a_schedule_moves_the_target_every_step_and_names_the_phase(setup):
    sim = setup("run", integrator=LANGEVIN)
    summary = sim.run(schedule=protocols.ramp(100, 300, ps=0.04) + protocols.hold(300, ps=0.02))
    assert summary.steps == 60 and sim.step == 60
    # Each call starts at the target of the step before its first and changes it by the ramp's rate per step.
    assert SpringEngine.made[0].targets == [(20, 100.0, 5.0), (20, 200.0, 5.0), (20, 300.0, 0.0)]
    assert _columns(setup.tmp_path / "run") == [(0, "heating", 100.0), (20, "heating", 200.0), (40, "heating", 300.0),
                                                (60, "hold", 300.0)]
    # The thermostat stays at the last target, and a run after the schedule is at a constant temperature.
    assert sim.config.temperature_K == 300.0
    sim.run(steps=20)
    assert SpringEngine.made[0].targets[-1] == (20, 300.0, 0.0)
    assert _columns(setup.tmp_path / "run")[-1] == (80, "constant", 300.0)


def test_the_end_of_a_segment_gets_a_row_and_a_frame(setup):
    sim = setup("run", integrator=LANGEVIN)
    sim.run(schedule=protocols.ramp(100, 400, ps=0.03) + protocols.ramp(400, 100, ps=0.03))
    directory = setup.tmp_path / "run"
    assert _columns(directory) == [(0, "heating", 100.0), (20, "heating", 300.0), (30, "heating", 400.0),
                                   (40, "cooling", 300.0), (60, "cooling", 100.0)]
    assert len(output.read_frames(directory)) == 5
    assert SpringEngine.made[0].targets == [(20, 100.0, 10.0), (10, 300.0, 10.0), (10, 400.0, -10.0),
                                            (20, 300.0, -10.0)]
    # The row at step 30 is made on the host between two device rows; all are in step order.
    engine = SpringEngine.made[0]
    assert [e for e in engine.log if isinstance(e, tuple)] == [("run", 20, 1, 20), ("run", 10, 1, 20),
                                                               ("run", 10, 1, 20), ("run", 20, 1, 20)]


def test_steps_and_schedules_are_checked_before_anything_runs(setup):
    schedule = protocols.ramp(100, 300, ps=0.04)
    sim = setup("run", integrator=LANGEVIN)
    with pytest.raises(InputError, match="steps is needed"):
        sim.run()
    with pytest.raises(InputError, match="beyond the schedule: 40 of its 40 steps remain"):
        sim.run(steps=50, schedule=schedule)
    with pytest.raises(InputError, match="schedule must be an lm.protocols schedule"):
        sim.run(schedule=[100, 300])
    assert SpringEngine.made == [] and sim.step == 0
    sim.run(steps=10, schedule=schedule)
    with pytest.raises(InputError, match="a schedule is in progress: 30 of its 40 steps remain"):
        sim.run(schedule=schedule)
    sim.run()                                                       # the rest of the schedule
    assert sim.step == 40 and [t[0] for t in SpringEngine.made[0].targets] == [10, 10, 20]
    assert SpringEngine.made[0].targets[1] == (10, 150.0, 5.0)
    sim.run(schedule=protocols.hold(300, ps=0.02))                  # a finished schedule can be followed by another
    assert sim.step == 60
    with pytest.raises(InputError, match="NVE has none"):
        setup("nve").run(schedule=schedule)


def test_a_restart_inside_a_schedule_resumes_at_its_position(setup):
    schedule = protocols.ramp(100, 300, ps=0.04) + protocols.hold(300, ps=0.04)
    whole = setup("whole", integrator=LANGEVIN, restart_every=None)
    whole.run(schedule=schedule)
    part = setup("part", integrator=LANGEVIN, restart_every=None)
    part.run(steps=20, schedule=schedule)
    part.save_restart()
    part.close()
    resumed = loupmd.Simulation.resume(setup.tmp_path / "part", force_field=setup.force_field())
    assert resumed.step == 20 and resumed._schedule.step == 20 and resumed._schedule.remaining == 60
    resumed.run()
    assert resumed.step == 80 and resumed.config.temperature_K == 300.0
    assert SpringEngine.made[-1].targets == [(20, 200.0, 5.0), (20, 300.0, 0.0), (20, 300.0, 0.0)]
    assert output.read_thermo(setup.tmp_path / "part") == output.read_thermo(setup.tmp_path / "whole")


# --------------------------------------------------------------------------------------------- fixed atoms

def _with_fixed(setup, indices):
    from ase.constraints import FixAtoms

    atoms = setup.atoms.copy()
    atoms.set_constraint(FixAtoms(indices=indices))
    return atoms


def test_fixed_atoms_stay_and_count_no_degrees_of_freedom(setup):
    atoms = _with_fixed(setup, [0, 3, 5])
    sim = loupmd.Simulation(atoms, setup.force_field(), integrator=integrators.NVE(timestep_fs=1.0),
                            output=Output(str(setup.tmp_path / "run")), seed=1)
    sim.run(steps=40)
    engine, = SpringEngine.made
    assert ("fixed", 3) in engine.log and engine.log.index(("fixed", 3)) < engine.log.index("set_state")
    frames = output.read_frames(setup.tmp_path / "run")
    for frame in frames:
        assert np.array_equal(frame.positions[[0, 3, 5]], setup.atoms.positions[[0, 3, 5]])
        assert not np.abs(frame.get_velocities()[[0, 3, 5]]).any()
    assert not np.array_equal(frames[-1].positions[1], setup.atoms.positions[1])
    # Every row's temperature counts 3 (16 - 3) degrees of freedom: the host's row at step 0 and the device's.
    for row in output.read_thermo(setup.tmp_path / "run")[1]:
        kinetic = float(row[6]) * 16
        assert float(row[4]) == pytest.approx(2 * kinetic / (39 * units.kB), rel=1e-12)
    assert len(sim.atoms.constraints) == 1


def test_fixed_atoms_survive_a_restart(setup):
    atoms = _with_fixed(setup, [2, 4])
    sim = loupmd.Simulation(atoms, setup.force_field(), integrator=integrators.NVE(timestep_fs=1.0),
                            output=Output(str(setup.tmp_path / "run")), seed=1)
    sim.run(steps=20)
    sim.save_restart()
    sim.close()
    resumed = loupmd.Simulation.resume(setup.tmp_path / "run", force_field=setup.force_field())
    assert resumed._fixed.tolist() == [i in (2, 4) for i in range(16)] and ("fixed", 2) in SpringEngine.made[-1].log
    resumed.run(steps=20)
    assert np.array_equal(resumed.atoms.positions[[2, 4]], setup.atoms.positions[[2, 4]])


def test_other_constraints_are_refused_by_name_before_anything_is_exported(setup):
    from ase.constraints import FixAtoms, FixBondLength

    atoms = setup.atoms.copy()
    atoms.set_constraint([FixAtoms(indices=[0]), FixBondLength(1, 2)])
    with pytest.raises(PlanRefused, match="the constraint FixBondLengths, which is not supported"):
        loupmd.Simulation(atoms, setup.force_field(), integrator=integrators.NVE(timestep_fs=1.0))
    everything = setup.atoms.copy()
    everything.set_constraint(FixAtoms(mask=[True] * 16))
    with pytest.raises(PlanRefused, match="every atom of the structure is fixed"):
        loupmd.Simulation(everything, setup.force_field(), integrator=integrators.NVE(timestep_fs=1.0))
    assert SpringEngine.made == []


# ----------------------------------------------------------------------------------------- centre of mass

def test_fixcm_is_on_by_default_off_with_fixed_atoms_and_counts_three_degrees_fewer(setup):
    assert integrators.Langevin(temperature_K=300, friction_per_fs=0.01).to_config(seed=1).fixcm is True
    assert integrators.NVE(timestep_fs=1.0).to_config(seed=1, fixed_atoms=True).fixcm is False
    assert integrators.NVE(timestep_fs=1.0, fixcm=False).to_config(seed=1).fixcm is False
    with pytest.raises(InputError, match="fixcm must be a bool"):
        IntegratorConfig(ensemble="nve", fixcm="auto")
    sim = setup("run")                                              # NVE, fixcm "auto": on
    sim.run(steps=20)
    assert SpringEngine.made[0].fix_com is True and sim._dof == 45
    for row in output.read_thermo(setup.tmp_path / "run")[1]:
        assert float(row[4]) == pytest.approx(2 * float(row[6]) * 16 / (45 * units.kB), rel=1e-12)
    held = loupmd.Simulation(_with_fixed(setup, [0]), setup.force_field(), integrator=integrators.NVE(timestep_fs=1.0))
    held.run(steps=5)
    assert SpringEngine.made[-1].fix_com is False and held._dof == 45
    with pytest.raises(PlanRefused, match="fixcm with fixed atoms"):
        loupmd.Simulation(_with_fixed(setup, [0]), setup.force_field(),
                          integrator=IntegratorConfig(ensemble="nve", fixcm=True))


def test_csvr_runs_with_its_time_constant_and_refuses_a_structure_at_rest(setup):
    record = integrators.CSVR(timestep_fs=1.0, temperature_K=200.0, tau_fs=50.0)
    at_rest = setup.atoms.copy()
    at_rest.set_velocities(np.zeros(at_rest.positions.shape))
    with pytest.raises(InputError, match="the structure is at rest, and CSVR rescales the velocities it finds"):
        loupmd.Simulation(at_rest, setup.force_field(), integrator=record)
    assert SpringEngine.made == []
    sim = loupmd.Simulation(setup.atoms, setup.force_field(), integrator=record, seed=5)
    assert (sim.config.scheme, sim.config.tau_fs, sim.config.fixcm) == ("csvr", 50.0, True)
    sim.run(schedule=protocols.ramp(200, 300, ps=0.04))
    engine, = SpringEngine.made
    assert [e for e in engine.log if isinstance(e, tuple) and e[0] == "run"] == [("run", 40, _core.LOUP_CSVR, 0)]
    assert engine.targets == [(40, 200.0, pytest.approx(2.5))] and engine.fix_com is True
    assert sim.config.temperature_K == 300.0                 # the thermostat stays at the schedule's last target
    for fields, message in (({"tau_fs": 0.0}, "IntegratorConfig.tau_fs must be positive and finite"),
                            ({"fixcm": "yes"}, "CSVR.fixcm must be True, False or 'auto'")):
        with pytest.raises(InputError, match=message):
            integrators.CSVR(**{"timestep_fs": 1.0, "temperature_K": 300.0, "tau_fs": 50.0, **fields})


def test_records_as_tables():
    record = integrators.CSVR(timestep_fs=1.0, temperature_K=300.0, tau_fs=100.0)
    table = integrators.to_data(record)
    assert table == {"type": "CSVR", "timestep_fs": 1.0, "temperature_K": 300.0, "tau_fs": 100.0, "fixcm": "auto"}
    assert integrators.from_data(table) == record
    assert integrators.from_data({"type": "CSVR", "tau_fs": 100.0}, timestep_fs=1.0, temperature_K=300.0) == record
    assert integrators.from_data({"type": "NVE"}, timestep_fs=2.0, temperature_K=300.0) == integrators.NVE(
        timestep_fs=2.0)
    for data, message in (({"type": "Verlet"}, "type 'Verlet' is not one of NVE, Langevin, CSVR, NoseHooverChain, "
                                               "Berendsen, LangevinBAOAB, MTK"),
                          ({"tau_fs": 1.0}, "type None is not one of"),
                          ({"type": "CSVR", "tau_fs": 100.0, "friction": 1}, "unknown key 'friction' in .integrator. "
                                                                             "of type CSVR"),
                          ({"type": "Langevin"}, "of type Langevin lacks temperature_K, friction_per_fs"),
                          ("CSVR", "is not a table")):
        with pytest.raises(InputError, match=message):
            integrators.from_data(data)


def test_a_schedule_moves_the_chain_s_target_and_leaves_its_masses(setup):
    record = integrators.NoseHooverChain(timestep_fs=1.0, temperature_K=200.0, tdamp_fs=50.0)
    sim = loupmd.Simulation(setup.atoms, setup.force_field(), integrator=record, seed=5)
    sim.run(schedule=protocols.ramp(200, 300, ps=0.04))
    engine, = SpringEngine.made
    assert [e for e in engine.log if isinstance(e, tuple) and e[0] == "run"] == [("run", 40, _core.LOUP_NHC, 0)]
    assert engine.targets == [(40, 200.0, pytest.approx(2.5))]
    assert (sim.config.temperature_K, sim.config.mass_temperature_K) == (300.0, 200.0)
    assert sim.config.to_struct().mass_temp_k == 200.0
