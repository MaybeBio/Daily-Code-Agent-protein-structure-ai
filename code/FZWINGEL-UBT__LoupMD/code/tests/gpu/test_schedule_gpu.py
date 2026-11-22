"""Temperature ramps on the GPU (plan task S3-T06): the thermostat's target lives on the device and moves every
step; a schedule's run tracks its target. Skips when the model file is absent."""
from __future__ import annotations

import numpy as np
import pytest
from gpu_support import maxwell_velocities, srtio3

import loupmd
from loupmd import BackendError, _core, integrators, output, protocols


def _engine_at(sto_engine, temp_k, seed=5):
    at = srtio3(3)
    sto_engine.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    sto_engine.set_state(at.positions, maxwell_velocities(at, temp_k, seed), at.cell.array)
    return sto_engine


def _langevin(temp_k, rate=0.0, friction=0.1, seed=2):
    return _core.integrator(_core.LOUP_LANGEVIN, 1.0, temp_k=temp_k, temp_rate_k_per_step=rate,
                            friction_per_fs=friction, seed=seed)


def test_the_target_of_a_call_moves_by_its_rate_every_step(sto_engine):
    """135 atoms, friction 0.1/fs (10 fs): the kinetic temperature follows 100 K -> 700 K within its fluctuation
    (about 7% of T for 135 atoms), and stays where the ramp ended."""
    eng = _engine_at(sto_engine, 200.0)
    eng.run(200, _langevin(100.0))
    cold = np.mean([eng.run(20, _langevin(100.0)).final_temperature_k for _ in range(10)])
    eng.run(600, _langevin(100.0, rate=1.0))                      # ends at a target of 700 K
    hot = np.mean([eng.run(20, _langevin(700.0)).final_temperature_k for _ in range(10)])
    assert 80.0 < cold < 120.0 and 600.0 < hot < 800.0, (cold, hot)
    eng.run(600, _langevin(700.0, rate=-1.0))                     # and back down
    cold_again = np.mean([eng.run(20, _langevin(100.0)).final_temperature_k for _ in range(10)])
    assert 80.0 < cold_again < 125.0, cold_again


def test_a_ramp_below_zero_kelvin_is_refused(sto_engine):
    eng = _engine_at(sto_engine, 100.0)
    with pytest.raises(BackendError, match="must not take the target below 0 K: 100 K \\+ 50 steps of -3 K"):
        eng.run(50, _langevin(100.0, rate=-3.0))
    with pytest.raises(BackendError, match="temp_rate_k_per_step must be finite"):
        eng.run(50, _langevin(100.0, rate=float("nan")))
    eng.run(50, _langevin(100.0, rate=-2.0))                      # exactly to 0 K is allowed


@pytest.mark.full
def test_a_schedule_tracks_its_target_on_5000_atoms(model_path, tmp_path):
    """S3-T06: hold at 200 K, then 200 K -> 400 K at 100 K/ps. The mean kinetic temperature of the ramp's rows is
    within 5% of their mean target, and the ramp's steps cost what the hold's cost (nothing is captured again)."""
    at = srtio3(10)
    at.set_velocities(maxwell_velocities(at, 400.0, seed=11))     # half of it goes into the lattice at once
    sim = loupmd.Simulation(at, loupmd.load(model_path, trusted=True),
                            integrator=integrators.Langevin(timestep_fs=1.0, temperature_K=200.0,
                                                            friction_per_fs=0.02),
                            output=loupmd.Output(str(tmp_path / "run"), trajectory_every=None, restart_every=None),
                            seed=1)
    hold = sim.run(schedule=protocols.hold(200, ps=0.5))
    ramp = sim.run(schedule=protocols.ramp(200, 400, ps=2.0))
    sim.close()
    rows = [(int(r[0]), r[2], float(r[3]), float(r[4])) for r in output.read_thermo(tmp_path / "run")[1]]
    heating = [(target, temperature) for step, phase, target, temperature in rows if phase == "heating" and step > 500]
    assert len(heating) == 100 and heating[-1][0] == 400.0 and heating[0][0] == pytest.approx(202.0)
    mean_target = np.mean([t for t, _ in heating])
    mean_kinetic = np.mean([k for _, k in heating])
    last = np.mean([k for _, k in heating[-10:]])
    print(f"ramp: mean target {mean_target:.1f} K, mean kinetic temperature {mean_kinetic:.1f} K "
          f"({mean_kinetic / mean_target:.4f}); last ten rows {last:.1f} K for targets "
          f"{np.mean([t for t, _ in heating[-10:]]):.1f} K; ms/step hold {hold.ms_per_step:.3f}, ramp "
          f"{ramp.ms_per_step:.3f}")
    assert abs(mean_kinetic / mean_target - 1.0) < 0.05
    assert ramp.ms_per_step < 1.03 * hold.ms_per_step
    assert ramp.dangerous_builds == 0
