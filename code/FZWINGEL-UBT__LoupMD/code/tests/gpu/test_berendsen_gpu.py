"""The Berendsen thermostat on the GPU (plan task S4-T05): the engine's steps are ASE 3.27's ``NVTBerendsen``
steps, and the temperature is drawn to the target."""
from __future__ import annotations

import numpy as np
import pytest
from ase import units
from gpu_support import maxwell_velocities, srtio3

import loupmd
from loupmd import BackendError, _core


def _start(eng, temp=300.0, seed=5, drift=0.0):
    at = srtio3(3)                                                   # 135 atoms, three masses
    at.positions += np.random.default_rng(seed).normal(scale=0.03, size=at.positions.shape)
    eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    velocities = maxwell_velocities(at, temp, seed) + drift
    eng.set_state(at.positions, velocities, at.cell.array)
    at.set_velocities(velocities)
    return at


def _berendsen(taut_fs=50.0, temp_k=300.0, dt_fs=1.0, **fields):
    return _core.integrator(_core.LOUP_BERENDSEN_NVT, dt_fs, temp_k=temp_k, tau_t_fs=taut_fs, **fields)


@pytest.mark.parametrize("start_K,taut_fs", [(300.0, 50.0), (900.0, 2.0)], ids=["gentle", "at-the-bounds"])
def test_the_engine_takes_ase_s_steps(sto_engine, model_path, start_K, taut_fs):
    """The plan's criterion: positions within 1e-4 A of ASE's ``NVTBerendsen`` driven by ``lm.calc`` after 200
    steps. The second case starts three times too hot with a time constant of two steps, so the scale factor
    sits at ASE's lower bound of 0.9 at first."""
    from ase.md.nvtberendsen import NVTBerendsen

    eng, steps = sto_engine, 200
    at = _start(eng, temp=start_K)
    eng.run(steps, _berendsen(taut_fs=taut_fs, thermo_every=10))
    positions, velocities, _, _ = eng.get_state()
    rows = eng.read_thermo()

    ref = at.copy()
    ref.calc = loupmd.calc(model_path, trusted=True)
    dyn = NVTBerendsen(ref, 1.0 * units.fs, temperature_K=300.0, taut=taut_fs * units.fs, fixcm=False)
    dyn.run(steps)
    worst = np.abs(positions - ref.positions).max()
    print(f"Berendsen (taut {taut_fs:g} fs, start {start_K:g} K) against ASE, {steps} steps: positions within "
          f"{worst:.1e} A, velocities within {np.abs(velocities - ref.get_velocities()).max():.1e}; temperature "
          f"{rows['temp_k'][0]:.0f} K after 10 steps, {rows['temp_k'][-1]:.0f} K at the end")
    assert worst < 1e-4
    assert float(rows["e_kin"][-1]) == pytest.approx(ref.get_kinetic_energy(), rel=1e-5)
    assert np.allclose(rows["conserved"], rows["e_pot"] + rows["e_kin"], rtol=1e-15)      # nothing is conserved


def test_the_temperature_follows_the_target_and_a_ramp(sto_engine):
    eng = sto_engine
    _start(eng, temp=100.0)
    eng.run(1_000, _berendsen(taut_fs=20.0, temp_k=300.0, thermo_every=100))
    heated = eng.read_thermo()["temp_k"]
    eng.run(2_000, _berendsen(taut_fs=20.0, temp_k=300.0, temp_rate_k_per_step=0.1, thermo_every=100))    # to 500 K
    ramp = eng.read_thermo()["temp_k"]
    print(f"Berendsen from 100 K to a 300 K target: {heated[0]:.0f} K after 0.1 ps, {heated[-1]:.0f} K after 1 ps; "
          f"ramp to 500 K: {ramp[9]:.0f} K at 400 K, {ramp[-1]:.0f} K at the end")
    assert 270 < heated[-1] < 330 and 350 < ramp[9] < 450 and 450 < ramp[-1] < 550


def test_fix_com_fixed_atoms_and_refusals(sto_engine):
    eng = sto_engine
    at = _start(eng, drift=0.02)
    masses = at.get_masses()[:, None]
    before = np.abs((masses * eng.get_state()[1]).sum(axis=0)).max()
    eng.run(200, _berendsen(fix_com=1, thermo_every=100))
    after = np.abs((masses * eng.get_state()[1]).sum(axis=0)).max()
    rows = eng.read_thermo()
    assert before > 1.0 and after < 1e-7 * before
    assert np.allclose(rows["temp_k"], 2 * rows["e_kin"] / (402 * units.kB), rtol=1e-12)

    at = _start(eng)
    fixed = np.zeros(len(at), dtype=bool)
    fixed[::5] = True
    eng.set_fixed_atoms(fixed)
    start = eng.get_state()[0]
    eng.run(200, _berendsen())
    positions, velocities, _, _ = eng.get_state()
    assert np.array_equal(positions[fixed], start[fixed]) and not velocities[fixed].any()
    eng.set_fixed_atoms(None)

    _start(eng)
    for fields, reason in ((dict(taut_fs=0.0), "tau_t_fs must be finite and positive, got 0 fs"),
                           (dict(taut_fs=0.5), "tau_t_fs must be at least the timestep for the Berendsen thermostat"),
                           (dict(temp_k=-1.0), "temp_k must be finite and not negative, got -1 K")):
        with pytest.raises(BackendError, match="loup_run: " + reason):
            eng.run(10, _berendsen(**fields))
    _start(eng, temp=0.0)                                           # at rest: the bound 1.1 scales nothing
    assert eng.run(300, _berendsen(taut_fs=20.0)).final_temperature_k > 100.0
