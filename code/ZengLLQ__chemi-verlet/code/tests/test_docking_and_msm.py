"""Tests for Vina+GBSA docking scoring, Kabsch RMSD, RDF, H-bonds, TICA, and MSM."""

from __future__ import annotations

import numpy as np
import pytest

from chemi_verlet.docking import optimize_binding_pose, score_protein_ligand_pose
from chemi_verlet.forcefield import ForceField, ForceFieldConfig
from chemi_verlet.integrators import SimulationConfig, run_simulation
from chemi_verlet.topology import build_host_guest_complex, build_solvated_ligand_box, smiles_to_topology
from chemi_verlet.trajectory import (
    build_markov_state_model,
    compute_radius_of_gyration,
    compute_rdf,
    compute_rmsf,
    detect_hydrogen_bonds,
    estimate_reversible_msm,
    kabsch_rmsd,
)


def test_docking_optimization_improves_or_maintains_favorable_score() -> None:
    _, _, lig_graph = smiles_to_topology("c1ccccc1O", seed=71)
    topo, coords, _, rec_idx, lig_idx = build_host_guest_complex("c1ccccc1O", seed=71)
    # Displace ligand slightly outside pocket so annealing must dock it back favorably
    displaced = coords.copy()
    displaced[list(lig_idx)] += np.array([0.25, 0.20, 0.35])
    init_score = score_protein_ligand_pose(topo, displaced, rec_idx, lig_idx, rotatable_bonds=1)
    opt_score = optimize_binding_pose(
        topo, displaced, rec_idx, lig_idx, ligand_graph=lig_graph, n_iterations=180, seed=71
    )
    assert opt_score.total_score <= init_score.total_score
    assert opt_score.optimized_positions.shape == coords.shape


def test_kabsch_rmsd_invariance_and_rg() -> None:
    rng = np.random.default_rng(72)
    ref = rng.normal(0.0, 0.4, size=(15, 3))
    q_mat, _ = np.linalg.qr(rng.normal(size=(3, 3)))
    if np.linalg.det(q_mat) < 0:
        q_mat[:, 0] *= -1.0
    transformed = (ref @ q_mat.T) + np.array([1.2, -0.7, 2.3])
    assert kabsch_rmsd(transformed, ref) < 1e-12

    masses = np.ones(15, dtype=np.float64) * 12.0
    assert pytest.approx(compute_radius_of_gyration(transformed, masses), rel=1e-10) == compute_radius_of_gyration(
        ref, masses
    )


def test_rdf_and_hbonds_on_solvated_trajectory() -> None:
    topo, coords, box = build_solvated_ligand_box("CCO", box_length_nm=2.2, n_waters=12, seed=73)
    ff = ForceField(topo, ForceFieldConfig(cutoff=0.9, electrostatics="pme"))
    _, traj = run_simulation(
        topo,
        ff,
        coords,
        box,
        config=SimulationConfig(dt_ps=0.002, n_steps=50, ensemble="nvt", save_interval=5, seed=73),
    )
    ow_idx = [a.index for a in topo.atoms if a.name == "OW"]
    r_nm, g_r = compute_rdf(traj, ow_idx, ow_idx, r_max=0.9, n_bins=20)
    assert r_nm.shape == g_r.shape == (20,)
    # Core exclusion: g(r) near r=0.05 nm must be zero
    assert g_r[0] == 0.0
    rmsf = compute_rmsf(traj)
    assert rmsf.shape == (topo.n_atoms,)
    assert np.all(rmsf >= 0.0)
    hbonds = detect_hydrogen_bonds(topo, traj.frames[-1].positions, traj.frames[-1].box)
    assert isinstance(hbonds, list)


def test_reversible_msm_detailed_balance_and_tica() -> None:
    # Construct synthetic 2-state Markov chain transitions with detailed balance
    rng = np.random.default_rng(74)
    true_t = np.array([[0.90, 0.10], [0.20, 0.80]], dtype=np.float64)
    trajs = []
    for _ in range(4):
        state = 0
        feats = []
        for _ in range(250):
            mean = np.array([1.0, 0.0, 0.5]) if state == 0 else np.array([-1.0, 0.0, -0.5])
            feats.append(mean + rng.normal(0.0, 0.15, size=3))
            state = int(rng.choice(2, p=true_t[state]))
        trajs.append(np.asarray(feats, dtype=np.float64))

    msm = build_markov_state_model(trajs, dt_frame_ps=0.01, lag_steps=2, n_states=2, seed=74)
    t_mat, pi = msm.transition_matrix, msm.stationary_distribution
    # Row stochasticity
    np.testing.assert_allclose(np.sum(t_mat, axis=1), 1.0, atol=1e-9)
    # Detailed balance: pi_i * T_ij == pi_j * T_ji
    flux = pi[:, None] * t_mat
    np.testing.assert_allclose(flux, flux.T, atol=1e-7)
    assert msm.ck_error < 0.25
    assert msm.mfpt_matrix_ps[0, 1] > 0.0 and msm.mfpt_matrix_ps[1, 0] > 0.0

    # Direct reversible estimator check
    t_est, pi_est = estimate_reversible_msm(np.array([[90.0, 10.0], [15.0, 85.0]]))
    np.testing.assert_allclose(pi_est @ t_est, pi_est, atol=1e-9)
