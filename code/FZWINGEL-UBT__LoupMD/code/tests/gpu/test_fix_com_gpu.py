"""``fix_com`` on the GPU (plan task S4-T01): Langevin's noise without its mass-weighted mean, NVE's total momentum
removed at the start, three degrees of freedom fewer in the temperature."""
from __future__ import annotations

import numpy as np
import pytest
from ase import units
from gpu_support import maxwell_velocities, srtio3

import loupmd
from loupmd import BackendError, _core, integrators, output


def _start(eng, drift=0.0, seed=5):
    at = srtio3(3)                                                   # 135 atoms, three masses
    at.positions += np.random.default_rng(seed).normal(scale=0.03, size=at.positions.shape)
    eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    velocities = maxwell_velocities(at, 300.0, seed) + drift         # Stationary, plus a common drift
    eng.set_state(at.positions, velocities, at.cell.array)
    return at


def _momentum(eng, at):
    return (at.get_masses()[:, None] * eng.get_state()[1]).sum(axis=0)


def _langevin(fix_com, thermo_every=0):
    return _core.integrator(_core.LOUP_LANGEVIN, 1.0, temp_k=300.0, friction_per_fs=0.02, seed=3, fix_com=fix_com,
                            thermo_every=thermo_every)


def test_langevin_with_fix_com_puts_no_momentum_into_the_centre_of_mass(sto_engine):
    eng = sto_engine
    at = _start(eng)
    typical = float(np.sqrt(at.get_masses().sum() * units.kB * 300.0))       # the thermal momentum of the whole cell
    stats = eng.run(500, _langevin(1, thermo_every=100))
    held = np.abs(_momentum(eng, at)).max()
    rows = eng.read_thermo()
    # 3N - 3 = 402 degrees of freedom in every reported temperature.
    kinetic = 0.5 * float((at.get_masses()[:, None] * eng.get_state()[1] ** 2).sum())
    assert stats.final_temperature_k == pytest.approx(2 * kinetic / (402 * units.kB), rel=1e-10)
    assert np.allclose(rows["temp_k"], 2 * rows["e_kin"] / (402 * units.kB), rtol=1e-12)
    assert 200.0 < rows["temp_k"].mean() < 400.0
    at = _start(eng)
    eng.run(500, _langevin(0))
    free = np.abs(_momentum(eng, at)).max()
    print(f"total momentum after 500 Langevin steps: {held / typical:.2e} of the thermal value with fix_com, "
          f"{free / typical:.2e} without")
    assert held < 1e-6 * typical and free > 1e-2 * typical


def test_nve_with_fix_com_removes_the_total_momentum_at_the_start(sto_engine):
    eng = sto_engine
    at = _start(eng, drift=0.02)
    before = np.abs(_momentum(eng, at)).max()
    eng.run(50, _core.integrator(_core.LOUP_NVE, 1.0, fix_com=1))
    after = np.abs(_momentum(eng, at)).max()
    assert before > 1.0 and after < 1e-7 * before, (before, after)
    at = _start(eng, drift=0.02)
    eng.run(50, _core.integrator(_core.LOUP_NVE, 1.0))
    assert np.abs(_momentum(eng, at)).max() == pytest.approx(before, rel=1e-6)   # conserved, not removed


def test_fix_com_is_refused_with_fixed_atoms(sto_engine):
    eng = sto_engine
    at = _start(eng)
    fixed = np.zeros(len(at), dtype=bool)
    fixed[:3] = True
    eng.set_fixed_atoms(fixed)
    with pytest.raises(BackendError, match="loup_run: fix_com with fixed atoms: 3 fixed atoms pin the frame already"):
        eng.run(10, _langevin(1))
    eng.run(10, _langevin(0))


@pytest.mark.full
def test_what_keeping_the_centre_of_mass_at_rest_costs(model_path, tmp_path):
    """5,000 atoms and 1,944-atom-sized steps are what matter; here 5,000 atoms through lm.Simulation, a b b a."""
    at = srtio3(10)
    at.set_velocities(maxwell_velocities(at, 300.0, seed=11))
    runs = {}
    for name, fixcm in (("on", True), ("off", False)):
        runs[name] = loupmd.Simulation(at, loupmd.load(model_path, trusted=True), seed=1,
                                       integrator=integrators.Langevin(timestep_fs=1.0, temperature_K=300.0,
                                                                       friction_per_fs=0.01, fixcm=fixcm))
        runs[name].run(steps=100)
    times = {"on": [], "off": []}
    for name in ("off", "on", "on", "off"):
        times[name].append(runs[name].run(steps=400).ms_per_step)
    ratio = sum(times["on"]) / sum(times["off"])
    print(f"Langevin, 5,000 atoms: ms/step with fix_com {times['on']}, without {times['off']}, ratio {ratio:.4f}")
    assert ratio < 1.02
    for run in runs.values():
        run.close()
