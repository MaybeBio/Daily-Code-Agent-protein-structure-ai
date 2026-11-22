"""Tests for NVE, Langevin BAOAB NVT, Nosé-Hoover Chain NVT, and NPT barostats."""

from __future__ import annotations

import numpy as np

from chemi_verlet.forcefield import ForceField, ForceFieldConfig
from chemi_verlet.integrators import SimulationConfig, minimize_energy, run_simulation
from chemi_verlet.topology import build_alkane_chain, build_solvated_ligand_box
from chemi_verlet.types import SimulationBox


def test_velocity_verlet_nve_conserves_total_energy() -> None:
    topo, coords = build_alkane_chain(4, constrain_bonds=False)
    box = SimulationBox.orthorhombic(2.5, 2.5, 2.5)
    ff = ForceField(topo, ForceFieldConfig(cutoff=0.9, electrostatics="cutoff", dispersion_correction=False))
    _, traj = run_simulation(
        topo,
        ff,
        coords + 1.25,
        box,
        config=SimulationConfig(dt_ps=0.001, n_steps=200, ensemble="nve", constraint_mode="none",
                                save_interval=5, seed=41),
    )
    etot = traj.total_energies()
    rel_fluct = float(np.std(etot) / max(abs(float(np.mean(etot))), 1.0))
    assert rel_fluct < 5e-3


def test_nose_hoover_chain_conserves_extended_hamiltonian() -> None:
    topo, coords, box = build_solvated_ligand_box("CO", box_length_nm=2.2, n_waters=6, seed=42)
    ff = ForceField(topo, ForceFieldConfig(cutoff=0.9, electrostatics="pme"))
    _, traj = run_simulation(
        topo,
        ff,
        coords,
        box,
        config=SimulationConfig(dt_ps=0.0015, n_steps=100, ensemble="nvt", thermostat="nhc",
                                temperature_k=300.0, constraint_mode="lincs", save_interval=5, seed=42),
    )
    h_ext = traj.conserved_energies()
    rel_drift = float(np.std(h_ext) / max(abs(float(np.mean(h_ext))), 1.0))
    assert rel_drift < 2e-2


def test_langevin_baoab_maintains_target_temperature() -> None:
    topo, coords, box = build_solvated_ligand_box("CCO", box_length_nm=2.3, n_waters=10, seed=43)
    ff = ForceField(topo, ForceFieldConfig(cutoff=0.9, electrostatics="pme"))
    _, traj = run_simulation(
        topo,
        ff,
        coords,
        box,
        config=SimulationConfig(dt_ps=0.002, n_steps=160, ensemble="nvt", thermostat="baoab",
                                temperature_k=320.0, friction_ps_inv=4.0, save_interval=4, seed=43),
    )
    temps = traj.temperatures()[len(traj.frames) // 2:]
    mean_t = float(np.mean(temps))
    assert 220.0 < mean_t < 420.0


def test_npt_barostats_compress_under_high_pressure() -> None:
    topo, coords, box = build_solvated_ligand_box("C", box_length_nm=2.4, n_waters=10, seed=44)
    ff = ForceField(topo, ForceFieldConfig(cutoff=0.9, electrostatics="reaction_field"))
    v0 = box.volume

    # High external pressure with MC barostat on unconstrained waters or Berendsen
    state_hi, _ = run_simulation(
        topo,
        ff,
        coords,
        box,
        config=SimulationConfig(dt_ps=0.002, n_steps=80, ensemble="npt", barostat="mc",
                                pressure_bar=5000.0, mc_barostat_freq=5, seed=44),
    )
    state_ber, _ = run_simulation(
        topo,
        ff,
        coords,
        box,
        config=SimulationConfig(dt_ps=0.002, n_steps=60, ensemble="npt", barostat="berendsen",
                                pressure_bar=5000.0, seed=45),
    )
    assert state_hi.box.volume > 0.0 and state_ber.box.volume < v0


def test_energy_minimization_decreases_potential() -> None:
    topo, coords = build_alkane_chain(4, constrain_bonds=False)
    box = SimulationBox.orthorhombic(2.5, 2.5, 2.5)
    ff = ForceField(topo, ForceFieldConfig(cutoff=0.9, electrostatics="cutoff", dispersion_correction=False))
    rng = np.random.default_rng(46)
    strained = coords + 1.25 + rng.normal(0.0, 0.04, size=coords.shape)
    e_before, _ = ff.evaluate(strained, box, force_rebuild=True)
    _, e_after = minimize_energy(ff, strained, box, max_steps=120)
    assert e_after.potential <= e_before.potential
