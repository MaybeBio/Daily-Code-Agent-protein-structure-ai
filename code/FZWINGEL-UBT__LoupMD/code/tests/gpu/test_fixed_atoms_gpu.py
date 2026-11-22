"""Fixed atoms on the GPU (plan task S4-T02): ``loup_set_fixed_atoms`` gives a fixed atom zero inverse mass and
zero velocity, so no integrator moves it, and the temperature counts the reduced degrees of freedom."""
from __future__ import annotations

import numpy as np
import pytest
from ase import units
from ase.constraints import FixAtoms
from gpu_support import maxwell_velocities, srtio3

import loupmd
from loupmd import BackendError, InputError, _core, integrators, output


def _start(eng, temp_k=300.0, seed=5):
    at = srtio3(3)                                                   # 135 atoms
    at.positions += np.random.default_rng(seed).normal(scale=0.03, size=at.positions.shape)
    eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    return at, maxwell_velocities(at, temp_k, seed)


def _langevin(thermo_every=0, seed=2):
    return _core.integrator(_core.LOUP_LANGEVIN, 1.0, temp_k=300.0, friction_per_fs=0.02, seed=seed,
                            thermo_every=thermo_every)


def test_fixed_atoms_do_not_move_over_a_thousand_langevin_steps(sto_engine):
    eng = sto_engine
    at, velocities = _start(eng)
    fixed = np.zeros(len(at), dtype=bool)
    fixed[::5] = True                                                # the 27 Sr atoms
    eng.set_fixed_atoms(fixed)
    eng.set_state(at.positions, velocities, at.cell.array)
    stats = eng.run(1000, _langevin(thermo_every=100))
    positions, vel, forces, energy = eng.get_state()
    assert np.array_equal(positions[fixed], at.positions[fixed])     # bit for bit
    assert not np.abs(vel[fixed]).any()
    assert np.abs(positions[~fixed] - at.positions[~fixed]).max() > 0.05
    assert np.abs(forces[fixed]).max() > 0.01                        # they still feel forces; nothing acts on them
    # The temperature counts 3 (N - n_fixed) = 324 degrees of freedom, in the rows and in the run's summary.
    kinetic = 0.5 * float((at.get_masses()[:, None] * vel ** 2).sum())
    assert stats.final_temperature_k == pytest.approx(2 * kinetic / (324 * units.kB), rel=1e-10)
    rows = eng.read_thermo()
    assert len(rows) == 10
    assert np.allclose(rows["temp_k"], 2 * rows["e_kin"] / (324 * units.kB), rtol=1e-12)
    assert 200.0 < rows["temp_k"][3:].mean() < 400.0                 # thermostatted at 300 K with that count
    assert stats.dangerous_builds == 0


def test_nve_with_fixed_atoms_conserves_energy_and_freeing_them_lets_them_move(sto_engine):
    eng = sto_engine
    at, velocities = _start(eng)
    fixed = np.zeros(len(at), dtype=bool)
    fixed[:20] = True
    eng.set_fixed_atoms(fixed)
    eng.set_state(at.positions, velocities, at.cell.array)
    first = eng.run_nve(20, 1.0)
    last = eng.run_nve(600, 1.0)
    drift = (last.final_potential_energy_ev + last.final_kinetic_energy_ev
             - first.final_potential_energy_ev - first.final_kinetic_energy_ev) / len(at)
    assert abs(drift) < 2e-5, drift                                  # eV/atom over 0.6 ps
    held = eng.get_state()[0][fixed]
    assert np.array_equal(held, at.positions[fixed])
    eng.set_fixed_atoms(None)
    eng.run_nve(200, 1.0)
    assert np.abs(eng.get_state()[0][fixed] - held).max() > 1e-3


def test_refusals(sto_engine):
    eng = sto_engine
    at, velocities = _start(eng)
    with pytest.raises(BackendError, match="loup_set_fixed_atoms: every atom is fixed \\(135 atoms\\)"):
        eng.set_fixed_atoms(np.ones(len(at), dtype=bool))
    with pytest.raises(InputError, match="fixed has shape \\(3,\\), expected \\(135,\\)"):
        eng.set_fixed_atoms([True, False, True])
    eng.set_fixed_atoms(np.zeros(len(at), dtype=bool))               # none fixed is allowed


def test_a_simulation_takes_ase_fix_atoms(model_path, tmp_path):
    at = srtio3(3)
    at.set_velocities(maxwell_velocities(at, 300.0, seed=11))
    at.set_constraint(FixAtoms(indices=range(0, 135, 5)))
    result = loupmd.md(at, model=model_path, trusted=True, temperature_K=300, steps=200, timestep_fs=1.0,
                       output=str(tmp_path / "run"), seed=3)
    frames = output.read_frames(tmp_path / "run")
    assert len(frames) == 11
    for frame in frames:
        assert np.array_equal(frame.positions[::5], at.positions[::5])
    assert result.metadata["structure"]["fixed_atoms"] == 27 and "27 fixed" in result.summary
    row = output.read_thermo(tmp_path / "run")[1][-1]
    assert float(row[4]) == pytest.approx(2 * float(row[6]) * 135 / (324 * units.kB), rel=1e-9)
    result.simulation.close()
