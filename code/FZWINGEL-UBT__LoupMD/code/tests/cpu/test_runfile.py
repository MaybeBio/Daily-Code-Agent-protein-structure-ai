"""``loupmd md``, ``loupmd init`` and ``loupmd run`` (plan task S3-T08) and run files, on the fake spring engine.
Needs neither a GPU nor the library."""
from __future__ import annotations

import json

import pytest
from ase.build import bulk
from ase.io import write
from fake_core import SpringEngine

import loupmd
from loupmd import _core, output, protocols, quick, runfile, simulation
from loupmd.cli import main
from loupmd.cli import md as cli_md
from loupmd.errors import InputError

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A structure file, a model file and a loader that gives the fake engine."""
    checkpoint = tmp_path / "some.model"
    checkpoint.write_bytes(b"never unpickled here")
    write(tmp_path / "salt.cif", bulk("NaCl", "rocksalt", a=5.64, cubic=True))
    SpringEngine.made, SpringEngine.poison_at = [], None
    loads = []

    def fake_load(model, head=None, **options):
        loads.append((str(model), head, {k: v for k, v in options.items() if v not in (None, False, 0)}))
        return loupmd.forcefield.load(str(checkpoint), head, trusted=True, engine_factory=SpringEngine,
                                      ensure_bundle=lambda path, numbers, **kw: path.with_name("bundle.loup"),
                                      probe=lambda p: None)

    monkeypatch.setattr(quick, "load", fake_load)
    monkeypatch.setattr(simulation, "load", fake_load)
    monkeypatch.chdir(tmp_path)
    return type("World", (), {"path": tmp_path, "model": str(checkpoint), "loads": loads})


BASE = ["salt.cif", "--model", "MODEL", "--trusted", "--temperature", "300", "--steps", "40", "--timestep", "1",
        "--seed", "3", "--initial-velocities", "maxwell_boltzmann", "--repeat", "2", "1", "1"]


def _args(world, *more):
    return [world.model if a == "MODEL" else a for a in BASE] + list(more)


def _rows(directory):
    return output.read_thermo(directory)[1]


# ------------------------------------------------------------------------------------------------ run files

def test_a_run_file_lists_every_argument_and_reads_back(world):
    arguments = {"structure": "salt.cif", "model": "omat0-medium", "temperature_K": 300.0, "steps": 2000,
                 "repeat": [3, 3, 3], "output": {"directory": "run", "restart_every": None},
                 "schedule": [{"kind": "hold", "temperature_K": 300.0, "ps": 1.0}]}
    del arguments["temperature_K"]                                    # a schedule gives the targets
    text = runfile.to_toml(arguments)
    for key in runfile.KEYS:
        assert f"\n{key} = " in text or f"\n# {key} =" in text, key
    assert '# ensemble = "NVT"' in text and "\nsteps = 2000" in text and "\nrestart_every = 0 " in text
    assert tomllib.loads(text) == {"structure": "salt.cif", "model": "omat0-medium", "steps": 2000,
                                   "repeat": [3, 3, 3], "output": {"directory": "run", "restart_every": 0},
                                   "schedule": [{"kind": "hold", "temperature_K": 300.0, "ps": 1.0}]}


def test_a_run_file_turns_files_off_with_zero(world):
    """TOML has no null: 0 in [output] turns the trajectory or the restarts off, and a written file keeps that."""
    arguments = {"structure": "salt.cif", "model": "m", "steps": 10, "temperature_K": 300.0,
                 "output": {"trajectory_every": None, "restart_every": None}}
    file = world.path / "off.toml"
    file.write_text(runfile.to_toml(arguments))
    _, options = runfile.md_options(runfile.load(file))
    assert (options["output"].trajectory_every, options["output"].restart_every) == (None, None)
    _, fast = runfile.md_options({"structure": "salt.cif", "model": "m", "profile": "fast",
                                  "output": {"trajectory_every": 0}})
    assert fast["output"].trajectory_every is None


def test_a_hand_written_mc_table_gives_the_move(world, tmp_path):
    """The [[mc]] example of docs/guide/monte-carlo.md."""
    from loupmd import mc

    file = tmp_path / "mc.toml"
    file.write_text('structure = "salt.cif"\nmodel = "m"\nsteps = 10\ntemperature_K = 300\n\n'
                    '[[mc]]\nmove = "swap"\npairs = [["Cu", "Au"]]\nevery = 100\nattempts = 20\n')
    _, options = runfile.md_options(runfile.load(file))
    move = mc.from_record(options["mc"][0])
    assert isinstance(move, mc.Swap) and (move.every, move.attempts) == (100, 20)


def test_unknown_keys_are_refused_by_name(world):
    file = world.path / "run.toml"
    file.write_text('structure = "salt.cif"\nmodel = "omat0-medium"\ntemperture_K = 300\nstep = 10\n')
    with pytest.raises(InputError) as caught:
        runfile.load(file)
    assert str(caught.value).startswith("unknown keys 'temperture_K', 'step' in the run file")
    assert "Keys: structure, model, head" in str(caught.value)
    assert main(["run", str(file)]) == 1
    file.write_text('structure = "salt.cif"\nmodel = "m"\nsteps = 10\ntemperature_K = 300\n[output]\nevery = 5\n')
    with pytest.raises(InputError, match=r"unknown key 'every' in \[output\]"):
        runfile.md_options(runfile.load(file))
    file.write_text("structure = \n")
    with pytest.raises(InputError, match="is not valid TOML"):
        runfile.load(file)
    with pytest.raises(InputError, match="the run file lacks model"):
        runfile.md_options({"structure": "salt.cif"})


def test_a_profile_gives_the_schedule_and_the_cadences(world):
    structure, options = runfile.md_options({"structure": "salt.cif", "model": "m", "profile": "anneal"})
    assert options["schedule"] == protocols.PROFILES["anneal"].schedule
    assert (options["output"].thermo_every, options["output"].trajectory_every) == (20, 20)
    assert options["output"].directory == "salt.loupmd"
    _, fast = runfile.md_options({"structure": "salt.cif", "model": "m", "profile": "fast",
                                  "output": {"thermo_every": 10}})
    assert (fast["output"].thermo_every, fast["output"].trajectory_every) == (10, 100)
    with pytest.raises(InputError, match="profile and \\[\\[schedule\\]\\] exclude each other"):
        runfile.md_options({"structure": "s", "model": "m", "profile": "fast",
                            "schedule": [{"kind": "hold", "temperature_K": 300.0, "ps": 1.0}]})


PRESS = ('name = "press"\nensemble = "NPT"\npressure_GPa = 0.5\nsample_interval = 10\ntrajectory_interval = 20\n'
         '[[segments]]\nkind = "hold"\ntemperature_K = 300\nps = 0.04\n')


def test_an_npt_profile_gives_the_ensemble_and_the_pressure(world):
    """Owner's decision O23. The run file's own pressure stands before the profile's; an [integrator] table's
    barostat runs at the profile's pressure unless the table names one."""
    (world.path / "press.toml").write_text(PRESS)
    base = {"structure": "salt.cif", "model": "m", "profile": "press.toml"}
    _, options = runfile.md_options(base)
    assert (options["ensemble"], options["pressure_GPa"]) == ("NPT", 0.5) and "integrator" not in options
    _, own = runfile.md_options(dict(base, ensemble="npt", pressure_GPa=1.0, cell_mode="full"))
    assert (own["ensemble"], own["pressure_GPa"], own["cell_mode"]) == ("NPT", 1.0, "full")
    with pytest.raises(InputError, match="profile 'press' runs NPT, the run file asks for ensemble='NVE'"):
        runfile.md_options(dict(base, ensemble="NVE"))
    mtk = {"type": "MTK", "tdamp_fs": 100.0, "pdamp_fs": 1000.0}
    _, table = runfile.md_options(dict(base, timestep_fs=1.0, integrator=mtk))
    assert table["ensemble"] == "NPT" and "pressure_GPa" not in table
    assert (type(table["integrator"]).__name__, table["integrator"].pressure_GPa) == ("MTK", 0.5)
    assert table["integrator"].temperature_K == 300.0 and mtk == {"type": "MTK", "tdamp_fs": 100.0, "pdamp_fs": 1000.0}
    _, named = runfile.md_options(dict(base, timestep_fs=1.0, integrator=dict(mtk, pressure_GPa=2.0)))
    assert named["integrator"].pressure_GPa == 2.0
    with pytest.raises(InputError, match="profile 'press' runs NPT, and \\[integrator\\] of type Langevin has no "
                                         "barostat"):
        runfile.md_options(dict(base, integrator={"type": "Langevin", "friction_per_fs": 0.01}))
    _, nvt = runfile.md_options({"structure": "salt.cif", "model": "m", "profile": "fast"})
    assert "ensemble" not in nvt and "pressure_GPa" not in nvt


# ------------------------------------------------------------------------------------------------- commands

def test_md_prints_the_report_and_writes_the_run(world, capsys):
    assert main(["md", *_args(world, "--output", "a")]) == 0
    out = capsys.readouterr().out
    assert f"LoupMD {loupmd.__version__}: MD run, status idle" in out and "salt.cif x (2, 1, 1): 16 atoms" in out
    assert [int(r[0]) for r in _rows(world.path / "a")] == [0, 20, 40]
    assert world.loads == [(world.model, None, {"trusted": True})]
    metadata = json.loads((world.path / "a" / "metadata.json").read_text())
    assert metadata["arguments"]["sha256"] == metadata["model"]["sha256"]       # a file: its hash is recorded


def test_init_then_run_equals_md(world, capsys):
    assert main(["md", *_args(world, "--output", "a")]) == 0
    capsys.readouterr()
    assert main(["init", "md", *_args(world, "--output", "b")]) == 0
    text = capsys.readouterr().out
    (world.path / "run.toml").write_text(text)
    assert tomllib.loads(text) == {"structure": "salt.cif", "model": world.model, "trusted": True,
                                   "temperature_K": 300.0, "timestep_fs": 1.0, "steps": 40, "repeat": [2, 1, 1],
                                   "seed": 3, "initial_velocities": "maxwell_boltzmann",
                                   "output": {"directory": "b"}}
    assert not (world.path / "b").exists()                                       # init runs nothing
    assert main(["run", "run.toml"]) == 0
    assert _rows(world.path / "a") == _rows(world.path / "b")
    for one, two in zip(output.read_frames(world.path / "a"), output.read_frames(world.path / "b")):
        assert (one.positions == two.positions).all() and (one.get_momenta() == two.get_momenta()).all()


def test_the_metadata_of_a_run_repeats_it(world, capsys):
    assert main(["md", *_args(world, "--output", "a")]) == 0
    metadata = json.loads((world.path / "a" / "metadata.json").read_text())
    metadata["arguments"]["output"]["directory"] = "again"
    (world.path / "again.json").write_text(json.dumps(metadata))
    assert main(["run", "again.json"]) == 0
    assert _rows(world.path / "a") == _rows(world.path / "again")
    assert world.loads[-1] == (world.model, None, {"sha256": metadata["model"]["sha256"]})
    # The original record names a directory that holds the run: running it again there is refused.
    assert main(["run", str(world.path / "a" / "metadata.json")]) == 1
    assert "already holds output chunks" in capsys.readouterr().err


def test_schedules_and_cadences_on_the_command_line(world, capsys):
    assert main(["md", "salt.cif", "--model", world.model, "--trusted", "--timestep", "1", "--seed", "1",
                 "--schedule", "ramp:100:300:0.04, hold:300:0.02", "--initial-velocities", "100", "--output", "s",
                 "--thermo-every", "10", "--trajectory-every", "0", "--restart-every", "0"]) == 0
    rows = _rows(world.path / "s")
    assert [int(r[0]) for r in rows] == list(range(0, 61, 10)) and rows[-1][2] == "hold"
    assert output.read_frames(world.path / "s") == []
    assert "schedule: heating 100 -> 300 K in 0.04 ps (40 steps); hold 300 K for 0.02 ps (20 steps)" in \
        capsys.readouterr().out
    assert main(["md", "salt.cif", "--model", world.model, "--schedule", "ramp:100:300"]) == 1
    assert "is not ramp:START_K:END_K:PS or hold:K:PS" in capsys.readouterr().err
    assert main(["md", "salt.cif", "--model", world.model, "--temperature", "300", "--steps", "5",
                 "--initial-velocities", "warm"]) == 1
    assert "is not keep, maxwell_boltzmann or a temperature in K" in capsys.readouterr().err


def test_resume_continues_a_run_and_updates_its_record(world, capsys):
    assert main(["md", *_args(world, "--output", "a")]) == 0
    capsys.readouterr()
    assert main(["run", "--resume", "a"]) == 1
    assert "is at step 40 and has no steps left" in capsys.readouterr().err
    assert main(["run", "--resume", "a", "--steps", "20"]) == 0
    out = capsys.readouterr().out
    assert "20 steps (0.02 ps) to step 60" in out and "resumed at step 40" in out
    assert [int(r[0]) for r in _rows(world.path / "a")] == [0, 20, 40, 60]
    metadata = json.loads((world.path / "a" / "metadata.json").read_text())
    assert metadata["step"] == 60 and metadata["structure"]["source"] == "salt.cif"
    assert main(["run", "--resume", "a", "--steps", "20"]) == 0                  # and again
    assert json.loads((world.path / "a" / "metadata.json").read_text())["step"] == 80


def test_usage(world, capsys):
    assert main(["run"]) == 1 and "takes a run file or --resume DIR" in capsys.readouterr().err
    assert main(["run", "run.toml", "--steps", "5"]) == 1 and "--steps is for --resume" in capsys.readouterr().err
    assert main(["run", "nothing.toml"]) == 1 and "run file nothing.toml not found" in capsys.readouterr().err
    assert main(["init"]) == 2
    with pytest.raises(SystemExit):
        main(["md", "salt.cif"])                                                # --model is required
    assert cli_md._segments("hold:300:1") == [{"kind": "hold", "temperature_K": 300.0, "ps": 1.0}]


def test_the_thermostat_on_the_command_line_and_in_a_run_file(world, capsys):
    csvr = ["--thermostat", "csvr", "--tau", "50"]
    assert main(["md", *_args(world, "--output", "c", *csvr)]) == 0
    assert "NVT, CSVR (Bussi), timestep 1 fs, time constant 50 fs, 300 K" in capsys.readouterr().out
    assert {e[2] for e in SpringEngine.made[-1].log if isinstance(e, tuple) and e[0] == "run"} == {_core.LOUP_CSVR}
    metadata = json.loads((world.path / "c" / "metadata.json").read_text())
    assert metadata["arguments"]["integrator"] == {"type": "CSVR", "timestep_fs": 1.0, "temperature_K": 300.0,
                                                   "tau_fs": 50.0, "fixcm": "auto"}
    # init writes the table, run reads it; the record of the first run repeats it.
    assert main(["init", "md", *_args(world, "--output", "d", *csvr)]) == 0
    text = capsys.readouterr().out
    assert tomllib.loads(text)["integrator"] == {"type": "CSVR", "tau_fs": 50.0}
    (world.path / "csvr.toml").write_text(text)
    assert main(["run", "csvr.toml"]) == 0
    metadata["arguments"]["output"]["directory"] = "e"
    (world.path / "again.json").write_text(json.dumps(metadata))
    assert main(["run", "again.json"]) == 0
    assert _rows(world.path / "c") == _rows(world.path / "d") == _rows(world.path / "e")
    assert {e[2] for e in SpringEngine.made[-1].log if isinstance(e, tuple) and e[0] == "run"} == {_core.LOUP_CSVR}
    capsys.readouterr()
    assert main(["md", *_args(world, "--output", "f", "--friction", "0.05")]) == 0
    assert "NVT, Langevin, timestep 1 fs, friction 0.05/fs" in capsys.readouterr().out
    for more, message in ((["--thermostat", "csvr"], "--thermostat csvr takes --tau FS"),
                          (["--tau", "50"], "--tau is the time constant of --thermostat csvr"),
                          ([*csvr, "--friction", "0.1"], "--thermostat csvr takes --tau FS"),
                          ([*csvr, "--ensemble", "NVE"], "conflicts with integrator=CSVR")):
        assert main(["md", *_args(world, "--output", "g", *more)]) == 1
        assert message in capsys.readouterr().err
    (world.path / "bad.toml").write_text(text.replace("tau_fs = 50.0", "tau = 50.0"))
    assert main(["run", "bad.toml"]) == 1
    assert "unknown key 'tau' in [integrator] of type CSVR" in capsys.readouterr().err
