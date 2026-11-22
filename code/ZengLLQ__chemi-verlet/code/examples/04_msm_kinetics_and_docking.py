"""Example 4: Structure-Based Vina+GBSA Docking & Reversible Alkane MSM Kinetics."""

from __future__ import annotations

import numpy as np

from chemi_verlet.calibration import calibrate_lj_parameters, run_conservation_audit
from chemi_verlet.docking import optimize_binding_pose
from chemi_verlet.forcefield import ForceField, ForceFieldConfig
from chemi_verlet.integrators import SimulationConfig, run_simulation
from chemi_verlet.topology import build_alkane_chain, build_host_guest_complex, smiles_to_topology
from chemi_verlet.trajectory import build_markov_state_model, compute_dihedral_angle
from chemi_verlet.types import SimulationBox
from chemi_verlet.visualizer import assert_strict_ascii, render_docking_summary, render_msm_summary


def main() -> None:
    # 1. Structure-based docking of aspirin in receptor pocket
    aspirin_smiles = "CC(=O)Oc1ccccc1C(=O)O"
    _, _, asp_graph = smiles_to_topology(aspirin_smiles, seed=303)
    comp_topo, comp_coords, _, rec_idx, lig_idx = build_host_guest_complex(aspirin_smiles, seed=303)
    dock_res = optimize_binding_pose(
        comp_topo,
        comp_coords,
        rec_idx,
        lig_idx,
        ligand_graph=asp_graph,
        n_iterations=180,
        seed=303,
    )
    print(render_docking_summary(dock_res, aspirin_smiles))
    print()

    # 2. Multi-trajectory pentane Langevin sampling -> TICA -> Reversible MSM
    alk_topo, alk_coords = build_alkane_chain(5, constrain_bonds=False)
    box = SimulationBox.orthorhombic(2.5, 2.5, 2.5)
    ff = ForceField(alk_topo, ForceFieldConfig(cutoff=0.9, electrostatics="cutoff", dispersion_correction=False))
    feature_trajs = []
    for idx in range(4):
        cfg = SimulationConfig(
            dt_ps=0.002,
            n_steps=120,
            ensemble="nvt",
            thermostat="baoab",
            temperature_k=450.0,
            constraint_mode="none",
            save_interval=2,
            seed=303 + idx * 17,
        )
        _, traj = run_simulation(alk_topo, ff, alk_coords + 1.25, box, config=cfg)
        feats = []
        for frame in traj.frames:
            p = frame.positions
            phi1 = compute_dihedral_angle(p[0], p[1], p[2], p[3], box)
            phi2 = compute_dihedral_angle(p[1], p[2], p[3], p[4], box)
            feats.append([np.cos(phi1), np.sin(phi1), np.cos(phi2), np.sin(phi2)])
        feature_trajs.append(np.asarray(feats, dtype=np.float64))

    msm = build_markov_state_model(feature_trajs, dt_frame_ps=0.004, lag_steps=3, n_states=4, seed=303)
    print(render_msm_summary(msm))
    print()

    # 3. Calibration + Conservation check
    cal = calibrate_lj_parameters(max_iter=15, seed=303)
    audit = run_conservation_audit(seed=303)
    print(assert_strict_ascii(
        f"Calibration Loss: {cal.initial_loss:.4f} -> {cal.best_loss:.4f} | "
        f"PME Energy RelErr={audit.pme_vs_exact_energy_rel_err:.2e} | "
        f"LINCS RMS={audit.lincs_constraint_rms_nm:.2e} nm"
    ))


if __name__ == "__main__":
    main()
