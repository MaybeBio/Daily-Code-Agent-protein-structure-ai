"""``lm.Simulation`` on the GPU: the acceptance runs of plan tasks S3-T03 (output), S3-T04 (restart) and S3-T05
(the run loop's cost). Skips when the model file is absent."""
from __future__ import annotations

import time

import numpy as np
import pytest
from gpu_support import find_model, maxwell_velocities, srtio3

import loupmd
from loupmd import LoupEngine, ensure_loup_bundle, integrators, output
from loupmd.errors import RestartMismatch


def _moving(rep, seed=11):
    at = srtio3(rep)
    at.set_velocities(maxwell_velocities(at, 300.0, seed=seed))
    return at


def test_a_thousand_steps_write_fastmace_s_rows_and_frames(model_path, tmp_path):
    """S3-T03: rows and frames at step 0 and every 20 steps; each frame is the engine's state at its step."""
    at = _moving(3)
    sim = loupmd.Simulation(at, loupmd.load(model_path, trusted=True), integrator=integrators.NVE(timestep_fs=1.0),
                            output=loupmd.Output(str(tmp_path / "run")), seed=1)
    summary = sim.run(steps=1000)
    final = sim.atoms
    sim.close()
    header, rows = output.read_thermo(tmp_path / "run")
    frames = output.read_frames(tmp_path / "run")
    assert [int(row[0]) for row in rows] == list(range(0, 1001, 20)) and len(frames) == 51
    assert summary.steps == 1000 and summary.dangerous_builds == 0
    # The last frame is the state the engine holds at the end, bit for bit.
    assert np.array_equal(frames[-1].positions, final.positions)
    assert np.array_equal(frames[-1].get_forces(), final.get_forces())
    assert frames[-1].get_potential_energy() == final.get_potential_energy()
    assert np.array_equal(frames[0].positions, at.positions)
    # A row and the frame of the same step come from the same force pass.
    for row, frame in zip(rows, frames):
        assert float(row[5]) * len(at) == pytest.approx(frame.get_potential_energy(), rel=1e-12)
        kinetic = 0.5 * float((frame.get_masses()[:, None] * frame.get_velocities() ** 2).sum())
        assert float(row[6]) * len(at) == pytest.approx(kinetic, rel=1e-9)
    # NVE: the total energy of the rows is conserved (0.05 meV/atom over the picosecond).
    total = np.array([float(row[7]) for row in rows])
    assert np.ptp(total) < 5e-5, np.ptp(total)
    # Frame 1 against a plain engine that ran the same 20 steps in one call.
    engine = LoupEngine(ensure_loup_bundle(model_path, [8, 22, 38]), device_id=0)
    engine.set_system(at.numbers, at.get_masses(), skin=0.5)
    engine.set_state(at.positions, at.get_velocities(), at.cell.array)
    engine.run_nve(20, dt_fs=1.0)
    assert np.abs(engine.get_state()[0] - frames[1].positions).max() < 1e-6


def test_resume_after_half_the_run_ends_where_the_uninterrupted_run_ends(model_path, tmp_path):
    """S3-T04: 500 of 1,000 NVE steps, restart, resume, 500 more: within 1e-3 A of the uninterrupted run, and the
    restored state equals the saved one bitwise."""
    at = _moving(3)

    def run(name, steps):
        sim = loupmd.Simulation(at, loupmd.load(model_path, trusted=True),
                                integrator=integrators.NVE(timestep_fs=1.0),
                                output=loupmd.Output(str(tmp_path / name), restart_every=None), seed=1)
        sim.run(steps=steps)
        return sim

    whole_a, whole_b = run("a", 1000), run("b", 1000)
    spread = np.abs(whole_a.atoms.positions - whole_b.atoms.positions).max()
    part = run("c", 500)
    part.save_restart()
    saved = part._engine.export_state()
    part.close()
    resumed = loupmd.Simulation.resume(tmp_path / "c")
    assert resumed.step == 500 and resumed._engine.export_state() == saved
    resumed.run(steps=500)
    deviation = np.abs(resumed.atoms.positions - whole_a.atoms.positions).max()
    print(f"two uninterrupted runs differ by {spread:.2e} A; the resumed run by {deviation:.2e} A")
    assert deviation <= max(1e-3, spread)
    assert [int(row[0]) for row in output.read_thermo(tmp_path / "c")[1]] == list(range(0, 1001, 20))
    assert len(output.read_frames(tmp_path / "c")) == 51
    for sim in (whole_a, whole_b, resumed):
        sim.close()
    # Another model's force field is refused before anything is changed.
    other = loupmd.load(find_model("mace-omat-0-small.model"), trusted=True)
    with pytest.raises(RestartMismatch, match="was written with the model of SHA-256"):
        loupmd.Simulation.resume(tmp_path / "c", force_field=other)


@pytest.mark.full
def test_output_every_20_steps_costs_at_most_three_percent(model_path, tmp_path):
    """S3-T05: 5,000 atoms, Langevin, wall time of run() with rows and frames every 20 steps against none."""
    at = _moving(10)
    langevin = integrators.Langevin(timestep_fs=1.0, temperature_K=300.0, friction_per_fs=0.01)
    plain = loupmd.Simulation(at, loupmd.load(model_path, trusted=True), integrator=langevin, seed=1)
    written = loupmd.Simulation(at, loupmd.load(model_path, trusted=True), integrator=langevin,
                                output=loupmd.Output(str(tmp_path / "run")), seed=1)
    for sim in (plain, written):
        sim.run(steps=100)                                        # warm-up: export, tuning, graph capture
    times = {"plain": [], "written": []}
    for name, sim in (("plain", plain), ("written", written), ("written", written), ("plain", plain)):
        started = time.perf_counter()
        sim.run(steps=400)
        times[name].append((time.perf_counter() - started) * 1e3 / 400)
    ratio = sum(times["written"]) / sum(times["plain"])
    print(f"ms/step without output {times['plain']}, with output every 20 steps {times['written']}, ratio {ratio:.4f}")
    written.close()
    plain.close()
    assert len(output.read_frames(tmp_path / "run")) == 1 + 900 // 20
    assert ratio <= 1.03, ratio
