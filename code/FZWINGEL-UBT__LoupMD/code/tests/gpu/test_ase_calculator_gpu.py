"""``lm.calc`` on the GPU (plan task S2-T10): the calculator gives what ``LoupEngine.evaluate`` gives, and ASE's
``VelocityVerlet`` driven by it conserves the energy. Skips when the model file is absent."""
from __future__ import annotations

import numpy as np
import pytest
from gpu_support import maxwell_velocities, srtio3

import loupmd
from loupmd import LoupEngine, ensure_loup_bundle


def _oxide(seed=7):
    at = srtio3(3)                                    # 135 atoms
    at.positions += np.random.default_rng(seed).normal(scale=0.04, size=at.positions.shape)
    return at


def test_the_calculator_equals_evaluate(model_path):
    at = _oxide()
    at.calc = loupmd.calc(model_path, trusted=True)
    forces = at.get_forces()                          # a call without stress first, as MD and optimisers make it
    energy = at.get_potential_energy()
    assert at.get_potential_energy(force_consistent=True) == energy          # the same result: no second pass
    stress = at.get_stress(voigt=False)                                      # a second pass, now with the stress
    # Two passes over one state agree to the order of the sums on the device (seen: 5e-13 eV of 1,076 eV).
    assert abs(at.get_potential_energy() - energy) < 1e-9 * abs(energy)
    assert at.get_potential_energy(force_consistent=True) == at.get_potential_energy()

    engine = LoupEngine(ensure_loup_bundle(model_path, [8, 22, 38]), device_id=0)
    engine.set_system(at.numbers, at.get_masses(), skin=0.5)
    e_ref, f_ref, s_ref = engine.evaluate(at.positions, at.cell.array, True)
    # Two engines of one bundle: equal up to the order of float32 sums on the device, and up to the hybrid GEMMs'
    # rounding where the two engines' autotunes pick different kernels for a shape (PLAN.md D16; seen once on
    # 15 November with a fresh plan directory: 3.0e-7 eV/atom, then five passes in a row).
    assert abs(energy - e_ref) / len(at) < 1e-6, (energy, e_ref)
    assert np.abs(forces - f_ref).max() < 2e-5, np.abs(forces - f_ref).max()
    assert np.abs(stress - s_ref).max() < 2e-7, np.abs(stress - s_ref).max()
    assert np.abs(stress - stress.T).max() == 0.0 and at.get_stress().shape == (6,)
    # The calculator's own engine, asked again for the same state.
    e_own, f_own, _ = at.calc.engine.evaluate(at.positions, at.cell.array, False)
    assert abs(energy - e_own) / len(at) < 2e-7 and np.abs(forces - f_own).max() < 2e-5


def test_velocity_verlet_with_the_calculator_conserves_energy(model_path):
    """The plan's criterion: a drift of at most 0.05 meV/atom/ps on SrTiO3 3x3x3."""
    from ase import units
    from ase.md.verlet import VelocityVerlet

    at = srtio3(3)
    at.set_velocities(maxwell_velocities(at, 300.0, seed=11))
    at.calc = loupmd.calc(model_path, trusted=True)
    steps, dt_fs = 1000, 1.0
    total = [at.get_total_energy()]
    dynamics = VelocityVerlet(at, timestep=dt_fs * units.fs)
    dynamics.attach(lambda: total.append(at.get_total_energy()), interval=1)
    dynamics.run(steps)
    total = np.array(total[-(steps + 1):]) / len(at) * 1e3                 # meV/atom at steps 0 .. 1000
    time_ps = np.arange(total.size) * dt_fs * 1e-3
    drift = np.polyfit(time_ps, total, 1)[0]
    assert 100.0 < at.get_temperature() < 250.0                            # half the kinetic energy went into the lattice
    assert abs(drift) <= 0.05, f"drift {drift:.4f} meV/atom/ps, fluctuation {total.std():.4f} meV/atom"
    print(f"drift {drift:+.4f} meV/atom/ps over {time_ps[-1]:.1f} ps, fluctuation {total.std():.4f} meV/atom, "
          f"T {at.get_temperature():.0f} K")


def test_a_relaxation_with_ase_lowers_the_forces(model_path):
    from ase.optimize import FIRE

    at = _oxide(seed=9)
    at.calc = loupmd.calc(model_path, trusted=True)
    start = np.abs(at.get_forces()).max()
    FIRE(at, logfile=None).run(fmax=0.05, steps=200)
    assert np.abs(at.get_forces()).max() < 0.05 < start
