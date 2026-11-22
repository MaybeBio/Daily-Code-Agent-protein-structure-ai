"""``loupmd quench`` (plan task S4-T12): the frame selection, the quench of a finished run and its files, on the
fake spring engine. Needs neither a GPU nor the library."""
from __future__ import annotations

import json

import numpy as np
import pytest
from ase.build import bulk
from ase.io import read
from fake_core import SpringEngine

import loupmd
from loupmd import output, protocols, quench
from loupmd.cli import main
from loupmd.cli import quench as cli_quench
from loupmd.errors import InputError

SITES = bulk("NaCl", "rocksalt", a=5.64, cubic=True)


def _spring_evaluate(atoms, stress=False, skin=0.5):
    """Springs to the lattice sites: the minimum of every frame is the perfect crystal, energy -3 eV/atom."""
    delta = atoms.positions - SITES.positions
    return 1.0 * float((delta ** 2).sum()) - 3.0 * len(atoms), -2.0 * delta, None


@pytest.fixture
def run(tmp_path, monkeypatch):
    checkpoint = tmp_path / "some.model"
    checkpoint.write_bytes(b"never unpickled here")
    SpringEngine.made, SpringEngine.poison_at = [], None
    ff = loupmd.load(str(checkpoint), trusted=True, engine_factory=SpringEngine,
                     ensure_bundle=lambda path, numbers, **kw: path.with_name("bundle.loup"), probe=lambda p: None)
    ff.evaluate = _spring_evaluate
    schedule = protocols.ramp(0, 400, ps=0.1) + protocols.ramp(400, 100, ps=0.2)       # 100 + 200 steps at 1 fs
    result = loupmd.md(SITES, model=ff, schedule=schedule, timestep_fs=1.0, seed=2, initial_velocities=50.0,
                       output=loupmd.Output(str(tmp_path / "run"), thermo_every=10, trajectory_every=10))
    result.simulation.close()
    monkeypatch.setattr(cli_quench, "load", lambda model, head=None, **options: ff)
    return type("Run", (), {"directory": tmp_path / "run", "ff": ff, "schedule": schedule})


SETTINGS = {"min_K": 200.0, "bin_K": 100.0, "per_bin": 2, "fmax": 0.01, "optimizer": "gpu-LBFGS", "max_steps": 200}


def test_frames_are_picked_per_bin_on_each_ramp_evenly_spaced():
    resolved = (protocols.ramp(0, 400, ps=0.1) + protocols.ramp(400, 100, ps=0.2)).resolve(1.0)
    table = quench.frame_table(resolved, 10)
    assert len(table) == 31 and table[10] == {"index": 10, "step": 100, "phase": "heating", "target_K": 400.0}
    chosen = quench.picks(resolved, 10, SETTINGS)
    assert [(p["phase"], p["bin"], p["step"]) for p in chosen] == [
        ("heating", "200-300 K", 50), ("heating", "200-300 K", 60), ("heating", "300-400 K", 80),
        ("heating", "300-400 K", 90), ("cooling", "300-400 K", 120), ("cooling", "300-400 K", 150),
        ("cooling", "200-300 K", 180), ("cooling", "200-300 K", 210), ("final", "final", 300)]
    # (The heating bin 200-300 K holds the frames of steps 50, 60 and 70: the goals 55 and 65 lie between two
    # frames each, and a tie goes to the earlier one.)
    # A bin with fewer frames than per_bin gives what it has; nothing is picked twice.
    few = quench.select_frames(table[:8], 0.0, 400.0, 20, 400.0)
    assert len(few) == 8 and len({p["step"] for p in few}) == 8


def test_a_quench_relaxes_the_picks_and_writes_fastmace_s_files(run):
    lines = []
    summary = quench.quench_run(run.directory, run.ff, SETTINGS, log=lines.append)
    out = run.directory / "quench"
    assert sorted(p.name for p in out.iterdir()) == ["captured.traj", "quench.csv", "quench.json", "quenched.traj",
                                                     "settings.json"]
    assert summary["frames"] == 9 and summary["not_converged"] == 0 and summary["trajectory_frames"] == 31
    assert summary["settings"]["selection"] == quench.SELECTION and summary["settings"]["fixed_cell"] is True
    assert summary["heating"]["frames"] == 4 and summary["cooling"]["frames"] == 4
    assert summary["final_quenched_eV_atom"] == pytest.approx(-3.0, abs=1e-6)       # every minimum is the crystal
    rows = quench._read_rows(out / "quench.csv")
    assert [r["step"] for r in rows] == [50, 60, 80, 90, 120, 150, 180, 210, 300]
    assert all(r["converged"] and r["fmax_eV_A"] < 0.01 and r["quenched_eV_atom"] < r["singlepoint_eV_atom"]
               for r in rows)
    frames = output.read_frames(run.directory)
    captured, quenched = read(out / "captured.traj", index=":"), read(out / "quenched.traj", index=":")
    assert len(captured) == len(quenched) == 9
    assert np.array_equal(captured[0].positions, frames[5].positions)               # step 50 is frame 5
    assert np.abs(quenched[0].positions - SITES.positions).max() < 0.01
    thermo = {int(r[0]): r for r in output.read_thermo(run.directory)[1]}
    assert rows[0]["md_temperature_K"] == float(thermo[50][4]) and rows[0]["target_K"] == 200.0
    assert len(lines) == 9 and lines[0].startswith("quench 1/9: heating 200 K -> -3.0000")
    assert quench.quench_run(run.directory, run.ff, SETTINGS, log=lines.append) == json.loads(
        (out / "quench.json").read_text()) and len(lines) == 9                      # complete: returned as it is


def test_an_interrupted_quench_continues_with_its_settings(run):
    calls = {"n": 0}

    def evaluate(atoms, stress=False, skin=0.5):
        calls["n"] += 1
        if calls["n"] == 8:
            raise KeyboardInterrupt
        return _spring_evaluate(atoms)

    run.ff.evaluate = evaluate
    with pytest.raises(KeyboardInterrupt):
        quench.quench_run(run.directory, run.ff, SETTINGS, log=lambda text: None)
    out = run.directory / "quench"
    done = len(quench._read_rows(out / "quench.csv"))
    assert 0 < done < 9 and not (out / "quench.json").exists()
    with pytest.raises(InputError, match="an unfinished quench with other settings"):
        quench.quench_run(run.directory, run.ff, dict(SETTINGS, fmax=0.02))
    run.ff.evaluate = _spring_evaluate
    lines = []
    summary = quench.quench_run(run.directory, run.ff, SETTINGS, log=lines.append)
    assert lines[0] == f"quench: continuing after {done} of 9 frames" and summary["frames"] == 9
    assert len(read(out / "quenched.traj", index=":")) == 9


def test_refusals(run, tmp_path):
    with pytest.raises(InputError, match="has no metadata.json"):
        quench.quench_run(tmp_path / "nowhere", run.ff, SETTINGS)
    with pytest.raises(InputError, match="quench settings need exactly the keys"):
        quench.quench_run(run.directory, run.ff, {"fmax": 0.01})
    with pytest.raises(InputError, match="optimizer 'ase-BFGS' is not in this version"):
        quench.quench_run(run.directory, run.ff, dict(SETTINGS, optimizer="ase-BFGS"))
    with pytest.raises(InputError, match="per_bin must be a positive int"):
        quench.quench_run(run.directory, run.ff, dict(SETTINGS, per_bin=0))
    plain = loupmd.md(SITES, model=run.ff, temperature_K=300, steps=20, output=str(tmp_path / "plain"), seed=1,
                      initial_velocities="maxwell_boltzmann")
    plain.simulation.close()
    with pytest.raises(InputError, match="no temperature schedule or no trajectory"):
        quench.quench_run(tmp_path / "plain", run.ff, SETTINGS)


def test_the_command_quenches_with_the_given_settings(run, capsys):
    assert main(["quench", str(run.directory), "--min-K", "200", "--per-bin", "1", "--max-steps", "200",
                 "--name", "quench-coarse"]) == 0
    out = capsys.readouterr().out
    assert "heating: 2 frames, quenched energies -3.0000" in out and "final frame: -3.000000 eV/atom; 5 frames" in out
    settings = json.loads((run.directory / "quench-coarse" / "settings.json").read_text())
    assert settings == {"min_K": 200.0, "bin_K": 100.0, "per_bin": 1, "fmax": 0.01, "optimizer": "gpu-LBFGS",
                        "max_steps": 200}


def test_a_quench_relaxes_with_the_run_s_dispersion_term(run, monkeypatch):
    """A run with D3 is quenched with the same term (FastMACE's quench uses the run's D3 record)."""
    record = run.directory / "metadata.json"
    metadata = json.loads(record.read_text())
    metadata["arguments"]["dispersion"] = {"preset": "d3bj", "functional": "pbe"}
    record.write_text(json.dumps(metadata))
    seen = []
    real = quench.optimize.relax

    def watch(*args, **kwargs):
        seen.append(kwargs.get("dispersion"))
        return real(*args, **kwargs)

    monkeypatch.setattr(quench.optimize, "relax", watch)
    quench.quench_run(run.directory, run.ff, dict(SETTINGS, max_steps=5), log=lambda *a: None)
    assert seen and all(d == {"preset": "d3bj", "functional": "pbe"} for d in seen)
