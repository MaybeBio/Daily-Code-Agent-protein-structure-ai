"""FastMACE's quickstart (`docs/quickstart.md` of FastMACE) with the changes `docs/guide/from-fastmace.md` lists
and no others (plan task S7-T02). Each block is the FastMACE line with only those changes; the steps are fewer.
The engine is the fake of `fake_core.py`; the model is never loaded."""
from __future__ import annotations

import inspect

import pytest
from ase import units
from ase.build import bulk
from ase.io import read
from fake_core import SpringEngine

import loupmd
import loupmd as lm                                  # was: import fastmace as fm
from loupmd import protocols, quick, simulation
from loupmd.ase import md as ase_md
from loupmd.cli import build_parser, main
from loupmd.output import read_frames, read_thermo   # was: from fastmace.io.output import read_frames, read_thermo


@pytest.fixture
def world(tmp_path, monkeypatch):
    checkpoint = tmp_path / "mace-mh-1.model"
    checkpoint.write_bytes(b"never unpickled here")
    SpringEngine.made, SpringEngine.poison_at = [], None
    asked = []

    def fake_load(model, head=None, **options):
        asked.append((model, head))
        return loupmd.forcefield.load(str(checkpoint), None, trusted=True, engine_factory=SpringEngine,
                                      ensure_bundle=lambda path, numbers, **kw: path.with_name("bundle.loup"),
                                      probe=lambda p: None)

    for module in (quick, simulation, ase_md):
        monkeypatch.setattr(module, "load", fake_load)
    monkeypatch.chdir(tmp_path)
    bulk("NaCl", "rocksalt", a=5.64, cubic=True).write("NaCl.cif")
    return type("World", (), {"path": tmp_path, "asked": asked})


def test_step_1_and_2_doctor_and_load_keep_their_names():
    parser = build_parser()
    assert parser.parse_args(["doctor"]).run is not None                    # fastmace doctor -> loupmd doctor
    # fm.load("mh1", head="matpes_r2scan", download=True) -> lm.load, the same arguments
    assert {"head", "download"} <= set(inspect.signature(loupmd.forcefield.load).parameters)


def test_step_3_the_command_line(world, capsys):
    # fastmace md --model mh1 --head matpes_r2scan --structure NaCl.cif --ensemble NVT --temperature 300
    #   --timestep 0.5 --steps 20000 --repeat 3 3 3 --seed 1 --output run/
    assert main(["md", "--model", "mh1", "--head", "matpes_r2scan", "--structure", "NaCl.cif", "--ensemble", "NVT",
                 "--temperature", "300", "--timestep", "0.5", "--steps", "40", "--repeat", "3", "3", "3",
                 "--seed", "1", "--output", "run/"]) == 0
    assert world.asked == [("mh1", "matpes_r2scan")]
    assert len(read_thermo("run/")[1]) == 3 and len(read_frames("run/")) == 3
    assert "216 atoms" in capsys.readouterr().out


def test_step_4_the_same_run_from_python(world):
    run = lm.md("NaCl.cif", model="mh1", head="matpes_r2scan", ensemble="NVT",
                temperature_K=300, timestep_fs=0.5, steps=40, repeat=(3, 3, 3),
                output="run-py/", seed=1)
    assert isinstance(run.summary, str) and isinstance(run.plan, dict)      # the plan is a dict here
    assert run.output.rstrip("/").endswith("run-py") and run.metadata["arguments"]["seed"] == 1
    sim = run.simulation
    sim.run(steps=40)
    assert sim.step == 80


def test_step_5_the_same_run_as_an_ase_script(world):
    from loupmd.ase import Langevin      # was: from fastmace.ase import Langevin

    atoms = read("NaCl.cif").repeat((3, 3, 3))
    dyn = Langevin(atoms, 0.5 * units.fs, temperature_K=300, friction=0.02,
                   model="mh1", head="matpes_r2scan", seed=1,
                   trajectory="run.traj", logfile="run.log", loginterval=20)
    dyn.run(40)
    assert isinstance(dyn.summary, str)
    assert dyn.simulation.config.friction_per_fs == pytest.approx(0.02 * units.fs)   # about 0.002 per fs
    dyn.close()
    assert len(read("run.traj", ":")) == 3 and (world.path / "run.log").is_file()


def test_step_7_resume_from_the_files(world):
    lm.md("NaCl.cif", model="mh1", head="matpes_r2scan", temperature_K=300, steps=40, output="run/", seed=1)
    sim = lm.Simulation.resume("run/")
    sim.run(steps=20)
    assert sim.step == 60
    for name in ("thermo.0.csv", "trajectory.0.traj", "restart.npz", "simulation.json", "metadata.json"):
        assert (world.path / "run" / name).is_file(), name


def test_step_8_run_files(world, capsys):
    # fastmace init --model mh1 --head matpes_r2scan --structure NaCl.cif --temperature 300 --steps 20000 > run.toml
    assert main(["init", "md", "--model", "mh1", "--head", "matpes_r2scan", "--structure", "NaCl.cif",
                 "--temperature", "300", "--steps", "40"]) == 0
    (world.path / "run.toml").write_text(capsys.readouterr().out)
    assert main(["run", "run.toml"]) == 0                                     # fastmace run run.toml
    # The quickstart's CSVR table with sparser output, and a profile name as the schedule.
    (world.path / "csvr.toml").write_text(
        'structure = "NaCl.cif"\nmodel = "mh1"\nhead = "matpes_r2scan"\nsteps = 40\n'
        'initial_velocities = "maxwell_boltzmann"\n\n'                       # listed: CSVR refuses a structure at rest
        '[integrator]\ntype = "CSVR"\ntimestep_fs = 1.0\ntemperature_K = 300.0\ntau_fs = 100.0\n\n'
        '[output]\ndirectory = "run-csvr/"\ntrajectory_every = 100\nthermo_every = 20\n')
    assert main(["run", "csvr.toml"]) == 0
    assert len(read_thermo("run-csvr/")[1]) == 3
    (world.path / "anneal.toml").write_text('structure = "NaCl.cif"\nmodel = "mh1"\nhead = "matpes_r2scan"\n'
                                            'schedule = "anneal"\nsteps = 40\n')
    from loupmd import runfile

    _, options = runfile.md_options(runfile.load(world.path / "anneal.toml"))
    assert options["schedule"] == protocols.PROFILES["anneal"].schedule and "output" not in options
    import shutil

    shutil.rmtree(world.path / "NaCl.loupmd")                                # the first run's default directory
    assert main(["run", "anneal.toml"]) == 0


def test_fastmace_spellings_of_the_structure_and_the_d3_functional(world):
    from loupmd.cli import md as cli_md

    parser = build_parser()
    both = parser.parse_args(["md", "NaCl.cif", "--structure", "NaCl.cif", "--model", "m"])
    with pytest.raises(lm.errors.InputError, match="give the structure file once"):
        cli_md.arguments_of(both)
    args = parser.parse_args(["md", "--structure", "NaCl.cif", "--model", "m", "--dispersion", "d3bj",
                              "--d3-functional", "pbe"])
    assert cli_md.arguments_of(args)["dispersion"] == {"preset": "d3bj", "functional": "pbe"}
    lone = parser.parse_args(["md", "NaCl.cif", "--model", "m", "--d3-functional", "pbe"])
    with pytest.raises(lm.errors.InputError, match="--d3-functional names the parameters of --dispersion"):
        cli_md.arguments_of(lone)
    named = lm.md("NaCl.cif", model="mh1", head="matpes_r2scan", schedule="ultrafast", steps=20, output="sched/")
    assert named.metadata["arguments"]["steps"] == 20
