"""``lm.md`` (plan task S3-T07), the report and ``metadata.json`` (S3-T09), and the gate inside a run (S3-T10), on
the fake spring engine of ``test_simulation``. Needs neither a GPU nor the library."""
from __future__ import annotations

import json

import numpy as np
import pytest
from ase import units
from ase.build import bulk
from ase.io import write
from fake_core import SpringEngine

import loupmd
from loupmd import integrators, output, protocols, provenance, quick, report, validate
from loupmd.errors import GateFailed, GateUnavailable, InputError, PlanRefused


@pytest.fixture
def ff(tmp_path):
    checkpoint = tmp_path / "some.model"
    checkpoint.write_bytes(b"never unpickled here")
    SpringEngine.made, SpringEngine.poison_at = [], None
    return loupmd.load(str(checkpoint), trusted=True, engine_factory=SpringEngine,
                       ensure_bundle=lambda path, numbers, **kw: path.with_name("bundle.loup"), probe=lambda p: None)


@pytest.fixture
def atoms():
    return bulk("NaCl", "rocksalt", a=5.64, cubic=True)


# ------------------------------------------------------------------------- errors before the model is loaded

MISSING = "/nowhere/missing.model"


@pytest.mark.parametrize("options,error,message", [
    ({"steps": 10}, InputError, "lm.md needs temperature_K= or schedule="),
    ({"temperature_K": 300}, InputError, "steps= is required without a schedule"),
    ({"temperature_K": 300, "steps": 0}, InputError, "steps must be a positive whole number"),
    ({"temperature_K": 300, "steps": 10, "ensemble": "NPH"}, InputError, "ensemble='NPH' is not one of"),
    ({"temperature_K": 300, "steps": 10, "pressure_GPa": 1.0}, InputError, "belong to ensemble='NPT'"),
    ({"temperature_K": 300, "steps": 10, "cell_mode": "full"}, InputError, "belong to ensemble='NPT'"),
    ({"temperature_K": 300, "steps": 10, "ensemble": "NPT", "cell_mode": "cubic"}, InputError, "cell_mode='cubic'"),
    ({"temperature_K": 300, "steps": 10, "ensemble": "NPT", "pressure_GPa": float("nan")}, InputError,
     "pressure_GPa must be a finite number"),
    ({"temperature_K": 300, "steps": 10, "ensemble": "NVE"}, InputError, "ensemble='NVE' has no target temperature"),
    ({"steps": 10, "ensemble": "NVE", "initial_velocities": "maxwell_boltzmann"}, InputError, "NVE has none"),
    ({"temperature_K": 300, "steps": 10, "repeat": (2, 2)}, InputError, "repeat must be three positive ints"),
    ({"temperature_K": 300, "steps": 10, "seed": -3}, InputError, "seed must be a nonnegative int"),
    ({"temperature_K": 300, "steps": 10, "initial_velocities": "hot"}, InputError, "initial_velocities='hot'"),
    ({"temperature_K": 300, "steps": 10, "check": "maybe"}, InputError, "check='maybe' is not one of"),
    ({"temperature_K": 300, "steps": 10, "capacity": "tiles"}, InputError, "capacity='tiles' is not one of"),
    ({"temperature_K": 300, "steps": 10, "mode": "graph", "calibrate": True}, PlanRefused,
     "mode= selects FastMACE's internals and has no meaning in LoupMD; calibrate= selects"),
    ({"temperature_K": 300, "steps": 10, "mc": object()}, InputError, "a Monte Carlo move record names its move"),
    ({"temperature_K": 300, "steps": 10, "min_mc_temperature_K": 200}, PlanRefused, "a temperature floor"),
    ({"temperature_K": 300, "steps": 10, "dispersion": "d3xyz"}, InputError, "dispersion='d3xyz' is not a preset"),
    ({"temperature_K": 300, "steps": 10, "dispersion": loupmd.Dispersion}, InputError, "dispersion= takes None"),
    ({"temperature_K": 300, "schedule": protocols.hold(300, ps=0.01)}, InputError, "exclude each other"),
    ({"schedule": protocols.hold(300, ps=0.01), "steps": 50, "timestep_fs": 1.0}, InputError, "beyond the schedule"),
    ({"temperature_K": 300, "steps": 10, "integrator": integrators.NVE(timestep_fs=1.0), "ensemble": "NVT"},
     InputError, "temperature_K=300 conflicts with the explicit integrator's fields"),
    ({"steps": 10, "integrator": "langevin"}, InputError, "integrator must be an lm.integrators record"),
    ({"temperature_K": 300, "steps": 10, "output": 5}, InputError, "output must be a directory"),
])
def test_argument_errors_come_before_the_model_is_looked_for(atoms, options, error, message):
    with pytest.raises(error) as caught:
        loupmd.md(atoms, model=MISSING, **options)
    assert message in str(caught.value)
    assert "missing.model" not in str(caught.value)


def test_then_the_model_and_the_structure_are_looked_for(atoms, tmp_path):
    with pytest.raises(InputError, match="neither a model label nor an existing checkpoint"):
        loupmd.md(atoms, model=MISSING, temperature_K=300, steps=10, output=str(tmp_path / "run"))
    with pytest.raises(InputError, match="structure file .*absent.cif not found"):
        loupmd.md(str(tmp_path / "absent.cif"), model=MISSING, temperature_K=300, steps=10)
    with pytest.raises(InputError, match="several heads and no default"):
        loupmd.md(atoms, model="mh1", temperature_K=300, steps=10)                # no file is needed for this
    with pytest.raises(InputError, match="structure must be a path or an ase.Atoms"):
        loupmd.md(42, model=MISSING, temperature_K=300, steps=10)
    assert not (tmp_path / "run").exists()


# --------------------------------------------------------------------------------------------------- a run

def test_one_call_runs_writes_and_reports(ff, atoms, tmp_path):
    result = loupmd.md(atoms, model=ff, temperature_K=300, steps=40, timestep_fs=1.0, repeat=(2, 1, 1),
                       output=str(tmp_path / "run"), seed=3, initial_velocities="maxwell_boltzmann")
    assert isinstance(result, loupmd.RunResult) and result.output == str(tmp_path / "run")
    sim = result.simulation
    assert sim.step == 40 and len(sim.atoms) == 16 and sim.seed == 3
    assert sim.config.friction_per_fs == pytest.approx(0.02 * units.fs) and sim.config.temperature_K == 300.0
    names = sorted(p.name for p in (tmp_path / "run").iterdir())
    assert names == ["metadata.json", "restart.npz", "simulation.json", "thermo.0.csv", "thermo.1.csv",
                     "trajectory.0.traj", "trajectory.1.traj"]
    assert [int(row[0]) for row in output.read_thermo(tmp_path / "run")[1]] == [0, 20, 40]
    metadata = json.loads((tmp_path / "run" / "metadata.json").read_text())
    assert metadata == json.loads(json.dumps(result.metadata)) and provenance.validate(metadata) == []
    assert metadata["schema"] == "loupmd.metadata/1" and metadata["status"] == "idle" and metadata["step"] == 40
    assert metadata["model"]["sha256"] == ff.sha256 and metadata["model"]["file"] == "some.model"
    assert metadata["structure"] == {"source": None, "repeat": [2, 1, 1], "atoms": 16, "elements": {"Cl": 8, "Na": 8},
                                     "fixed_atoms": 0,
                                     "cell": [[11.28, 0.0, 0.0], [0.0, 5.64, 0.0], [0.0, 0.0, 5.64]],
                                     "pbc": [True, True, True]}
    assert metadata["counters"]["steps"] == 40 and metadata["timing"]["ms_per_step"] > 0
    assert metadata["timing"]["ns_per_day"] == pytest.approx(86.4 / metadata["timing"]["ms_per_step"])
    assert metadata["arguments"]["steps"] == 40 and metadata["arguments"]["seed"] == 3
    assert metadata["arguments"]["output"]["directory"] == str(tmp_path / "run")
    assert metadata["gate"] == {"status": "skipped"} and metadata["bundle"] == "bundle.loup"
    assert metadata["warnings"] == ["starting velocities: Maxwell-Boltzmann at 300 K, drawn from seed 3 "
                                    "(initial_velocities='maxwell_boltzmann'; the structure was at rest)"]
    text = result.summary
    assert str(result) == text == report.text(metadata)
    for line in (f"LoupMD {loupmd.__version__}: MD run, status idle", "Model and structure", "some.model, SHA-256",
                 "Atoms x (2, 1, 1): 16 atoms (Cl 8, Na 8), cell 11.28 x 5.64 x 5.64 A",
                 "Physics", "NVT, Langevin, timestep 1 fs, friction 0.001965/fs, 300 K",
                 "40 steps (0.04 ps) to step 40, seed 3", "Plan", "the whole system on", "Gate",
                 'skipped (check="skip")', "Setup", "Speed", "ms/step with output", "ns/day", "million atom-steps/s",
                 "Licence", "model: not in the label table",
                 "LoupMD: MIT, its engine library LGPL-2.1-or-later", "Warnings", "Output",
                 "thermo.*.csv every 20 steps, trajectory.*.traj every 20"):
        assert line in text, line
    assert len(text.splitlines()) <= 30                               # one screen
    # The simulation can run on, and the run can be resumed from what md wrote.
    sim.run(steps=20)
    sim.close()
    assert loupmd.Simulation.resume(tmp_path / "run", force_field=ff).step == 40


def test_the_default_output_directory_and_the_structure_file(ff, atoms, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write(tmp_path / "salt.cif", atoms)
    result = loupmd.md("salt.cif", model=ff, ensemble="NVE", steps=20, timestep_fs=1.0, initial_velocities=250.0,
                       seed=1)
    assert result.output == "salt.loupmd" and (tmp_path / "salt.loupmd" / "metadata.json").is_file()
    assert result.metadata["structure"]["source"] == "salt.cif" and result.metadata["integrator"]["scheme"] == "nve"
    assert "NVE, velocity Verlet, timestep 1 fs" in result.summary
    assert "Maxwell-Boltzmann at 250 K" in result.metadata["warnings"][0]
    assert result.simulation._atoms.get_temperature() > 100.0
    result.simulation.close()
    assert loupmd.md(atoms, model=ff, temperature_K=300, steps=20, seed=1).output == "loupmd-run"


def test_a_structure_that_moves_keeps_its_momenta(ff, atoms, tmp_path):
    atoms.set_velocities(np.full(atoms.positions.shape, 0.01))
    result = loupmd.md(atoms, model=ff, temperature_K=300, steps=20, output=str(tmp_path / "run"),
                       initial_velocities="maxwell_boltzmann")
    assert result.metadata["warnings"] == ["starting velocities: the structure's own; "
                                           "initial_velocities='maxwell_boltzmann' draws only for a structure at rest"]
    assert np.array_equal(output.read_frames(tmp_path / "run")[0].get_velocities(), atoms.get_velocities())
    assert isinstance(result.metadata["seed"], int)                     # drawn and recorded


def test_mc_moves_run_and_are_recorded_so_the_run_file_repeats_them(ff, atoms, tmp_path):
    """S6-T04: lm.md(mc=...) passes the moves to the run; metadata.json holds them and their counters, and the
    record's arguments give the same moves back (``loupmd run metadata.json``)."""
    from loupmd import mc, runfile

    moves = [mc.Displace(delta_A=0.05, every=5, attempts=2), mc.Swap(pairs=[("Na", "Cl")], every=10, attempts=3)]
    result = loupmd.md(atoms, model=ff, temperature_K=300, steps=20, output=str(tmp_path / "run"), seed=4, mc=moves)
    counters = result.metadata["mc"]["counters"]
    assert counters["displace"]["attempted"] == 4 * 2 and counters["swap"]["attempted"] == 2 * 3
    recorded = result.metadata["arguments"]["mc"]
    assert [mc.from_record(r) for r in recorded] == moves
    _, options = runfile.md_options(dict(result.metadata["arguments"], structure="salt.cif"))
    assert [mc.from_record(r) for r in options["mc"]] == moves


def test_a_schedule_runs_whole_and_is_reported(ff, atoms, tmp_path):
    schedule = protocols.ramp(0, 400, ps=0.04) + protocols.hold(400, ps=0.02)
    result = loupmd.md(atoms, model=ff, schedule=schedule, timestep_fs=1.0, output=str(tmp_path / "run"), seed=2,
                       initial_velocities=10.0)
    assert result.simulation.step == 60 and result.metadata["schedule"]["total_steps"] == 60
    assert "schedule: heating 0 -> 400 K in 0.04 ps (40 steps); hold 400 K for 0.02 ps (20 steps)" in result.summary
    assert result.metadata["arguments"]["schedule"] == schedule.to_data()
    assert [row[2] for row in output.read_thermo(tmp_path / "run")[1]] == ["heating", "heating", "heating", "hold"]


def test_a_loaded_model_takes_no_load_arguments(ff, atoms):
    with pytest.raises(InputError, match="model is already loaded; head, trusted belong to lm.load"):
        loupmd.md(atoms, model=ff, head="x", trusted=True, temperature_K=300, steps=10)


# ------------------------------------------------------------------------------------------------- the gate

def _gate_record(passed):
    row = validate.GateRow(config="structure0_r0", variant="default", atoms=8, de_meV_per_atom=0.001, df=2e-5, ds=1e-8,
                           de32=0.002, df32=4e-5, ds32=3e-8, energy_ratio=0.5, force_ratio=0.5 if passed else 4.2,
                           stress_ratio=0.3, passed=passed, failed=() if passed else ("force",))
    return validate.make_record([row], [], passed, set_name="user", model={"label": None, "file": "some.model",
                                "sha256": "ab" * 32, "head": None}, reference={"device": "cpu:x", "file": "/c/x.npz",
                                "cached": False, "mace": "0.3.16", "torch": "2.14.1"}, library="lib", left_out=[])


def test_a_gate_that_passes_is_reported_and_the_run_starts(ff, atoms, tmp_path, monkeypatch):
    seen = {}

    def run_gate(model, **options):
        seen.update(options, model=model)
        return _gate_record(True)

    monkeypatch.setattr(validate, "run_gate", run_gate)
    result = loupmd.md(atoms, model=ff, temperature_K=300, steps=20, output=str(tmp_path / "run"), check="gate")
    assert result.gate["status"] == "passed" and result.metadata["gate"]["passed"] is True
    assert "passed: worst ratios energy 0.50, force 0.50, stress 0.30 of the 3 allowed, on 1 rattled copies" in \
        result.summary
    assert seen["model"] == str(ff.path) and seen["sha256"] == ff.sha256 and len(seen["structures"]) == 1
    assert seen["gate_config"].rattle_A == 0.05 and seen["gate_config"].copies == 2


def test_a_gate_that_fails_stops_the_run_before_its_first_step(ff, atoms, tmp_path, monkeypatch):
    monkeypatch.setattr(validate, "run_gate", lambda model, **options: _gate_record(False))
    with pytest.raises(GateFailed) as caught:
        loupmd.md(atoms, model=ff, temperature_K=300, steps=20, output=str(tmp_path / "run"), check="gate")
    assert "worst ratios energy 0.50, force 4.20, stress 0.30 (a quantity passes up to 3)" in str(caught.value)
    assert caught.value.gate_record["passed"] is False and SpringEngine.made == []
    assert output.read_thermo(tmp_path / "run")[1] == []               # nothing was run or written


def test_an_unavailable_gate_stops_or_is_recorded(ff, atoms, tmp_path, monkeypatch):
    def run_gate(model, **options):
        raise GateUnavailable("the gate needs mace-torch, which is not installed")

    monkeypatch.setattr(validate, "run_gate", run_gate)
    with pytest.raises(GateUnavailable):
        loupmd.md(atoms, model=ff, temperature_K=300, steps=20, output=str(tmp_path / "a"), check="gate")
    result = loupmd.md(atoms, model=ff, temperature_K=300, steps=20, output=str(tmp_path / "b"),
                       check="allow_unavailable")
    assert result.gate == {"status": "unavailable", "why": "the gate needs mace-torch, which is not installed"}
    assert "unavailable: the gate needs mace-torch" in result.summary and result.simulation.step == 20


def test_an_explicit_csvr_record_runs_and_is_recorded(ff, atoms, tmp_path):
    record = integrators.CSVR(timestep_fs=1.0, temperature_K=250.0, tau_fs=40.0)
    result = loupmd.md(atoms, model=ff, steps=20, integrator=record, output=str(tmp_path / "run"), seed=3,
                       initial_velocities="maxwell_boltzmann")
    assert result.simulation.config.scheme == "csvr" and result.simulation.config.tau_fs == 40.0
    assert result.metadata["arguments"]["integrator"] == {"type": "CSVR", "timestep_fs": 1.0, "temperature_K": 250.0,
                                                          "tau_fs": 40.0, "fixcm": "auto"}
    assert "NVT, CSVR (Bussi), timestep 1 fs, time constant 40 fs, 250 K" in result.summary
    assert "Maxwell-Boltzmann at 250 K" in result.metadata["warnings"][0]
    with pytest.raises(InputError, match="the structure is at rest, and CSVR rescales the velocities"):
        loupmd.md(atoms, model=ff, steps=20, integrator=record, output=str(tmp_path / "rest"))
    assert not (tmp_path / "rest").exists()
