"""Headless CLI for ChemiVerlet molecular dynamics, FEP/MBAR, WHAM, docking, and MSM."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional, Sequence
import numpy as np

from chemi_verlet.alchemical import build_default_lambda_schedule, run_alchemical_fep
from chemi_verlet.calibration import calibrate_lj_parameters, run_conservation_audit
from chemi_verlet.docking import optimize_binding_pose
from chemi_verlet.forcefield import ForceField, ForceFieldConfig
from chemi_verlet.integrators import SimulationConfig, run_simulation
from chemi_verlet.topology import (
    build_alkane_chain,
    build_host_guest_complex,
    build_solvated_ligand_box,
    smiles_to_topology,
)
from chemi_verlet.trajectory import build_markov_state_model, compute_dihedral_angle, compute_rdf, kabsch_rmsd
from chemi_verlet.types import SimulationBox
from chemi_verlet.umbrella import run_umbrella_sampling
from chemi_verlet.visualizer import (
    assert_strict_ascii,
    render_docking_summary,
    render_energy_profile,
    render_mbar_summary,
    render_msm_summary,
    render_pmf_profile,
    render_rdf_plot,
)


def _cmd_simulate(args: argparse.Namespace) -> Dict[str, Any]:
    """Run NVE/NVT/NPT molecular dynamics on a solvated SMILES ligand."""
    topo, coords, box = build_solvated_ligand_box(
        smiles=args.smiles,
        box_length_nm=args.box_nm,
        n_waters=args.waters,
        seed=args.seed,
    )
    ff = ForceField(topo, ForceFieldConfig(cutoff=0.9, electrostatics=args.electrostatics))
    cfg = SimulationConfig(
        dt_ps=args.dt,
        n_steps=args.steps,
        ensemble=args.ensemble,
        thermostat=args.thermostat,
        temperature_k=args.temp,
        pressure_bar=args.pressure,
        constraint_mode=args.constraints,
        save_interval=max(1, args.steps // 20),
        seed=args.seed,
    )
    state, traj = run_simulation(topo, ff, coords, box, config=cfg)

    ow_indices = [a.index for a in topo.atoms if a.name == "OW"]
    rdf_text = ""
    if len(ow_indices) >= 2:
        r_nm, g_r = compute_rdf(traj, ow_indices, ow_indices, r_max=min(0.95, args.box_nm * 0.45), n_bins=24)
        rdf_text = render_rdf_plot(r_nm, g_r)

    rmsd = kabsch_rmsd(traj.frames[-1].positions, traj.frames[0].positions)
    print(assert_strict_ascii(f"ChemiVerlet MD | system={topo.name} | atoms={topo.n_atoms} | "
                              f"ensemble={args.ensemble.upper()} | final_T={state.energy.temperature:.2f} K | "
                              f"final_P={state.energy.pressure_bar:.2f} bar | "
                              f"LINCS_RMS={state.constraint_rms_error:.2e} nm | RMSD={rmsd:.4f} nm"))
    print(render_energy_profile(traj))
    if rdf_text:
        print()
        print(rdf_text)

    return {
        "atoms": topo.n_atoms,
        "final_potential_kj_mol": state.energy.potential,
        "final_temperature_k": state.energy.temperature,
        "final_pressure_bar": state.energy.pressure_bar,
        "constraint_rms_nm": state.constraint_rms_error,
        "rmsd_nm": rmsd,
    }


def _cmd_alchemical(args: argparse.Namespace) -> Dict[str, Any]:
    """Run multi-lambda alchemical hydration free-energy perturbation."""
    topo, coords, box = build_solvated_ligand_box(
        smiles=args.smiles,
        box_length_nm=2.2,
        n_waters=args.waters,
        seed=args.seed,
    )
    ff = ForceField(topo, ForceFieldConfig(cutoff=0.9, electrostatics="pme"))
    schedule = build_default_lambda_schedule(args.windows)
    est = run_alchemical_fep(
        topo,
        ff,
        coords,
        box,
        lambda_schedule=schedule,
        steps_per_window=args.steps_per_window,
        equilibration_steps=max(10, args.steps_per_window // 4),
        sample_interval=max(2, args.steps_per_window // 12),
        temperature_k=args.temp,
        seed=args.seed,
    )
    print(render_mbar_summary(est))
    return {
        "delta_g_mbar_kj_mol": est.delta_g_mbar,
        "sigma_mbar_kj_mol": est.sigma_mbar,
        "delta_g_bar_kj_mol": est.delta_g_bar,
        "delta_g_ti_kj_mol": est.delta_g_ti,
        "hysteresis_kj_mol": est.hysteresis_kj_mol,
    }


def _cmd_umbrella(args: argparse.Namespace) -> Dict[str, Any]:
    """Run multi-window umbrella sampling and WHAM PMF reconstruction."""
    topo, coords, box, rec_idx, lig_idx = build_host_guest_complex(args.smiles, seed=args.seed)
    ff = ForceField(topo, ForceFieldConfig(cutoff=1.0, electrostatics="reaction_field"))
    pmf, _ = run_umbrella_sampling(
        topo,
        ff,
        coords,
        box,
        rec_idx,
        lig_idx,
        r_start_nm=0.22,
        r_end_nm=0.82,
        n_windows=args.windows,
        k_restraint=2200.0,
        steps_per_window=args.steps_per_window,
        equilibration_steps=max(10, args.steps_per_window // 4),
        sample_interval=max(2, args.steps_per_window // 15),
        seed=args.seed,
    )
    print(render_pmf_profile(pmf))
    valid_pmf = pmf.pmf_kj_mol[~np.isnan(pmf.pmf_kj_mol)]
    barrier = float(np.max(valid_pmf) - np.min(valid_pmf)) if valid_pmf.size else 0.0
    return {
        "pmf_barrier_kj_mol": barrier,
        "wham_iterations": pmf.iterations,
        "wham_residual": pmf.residual,
    }


def _cmd_dock(args: argparse.Namespace) -> Dict[str, Any]:
    """Dock a SMILES ligand into the receptor pocket using Vina + GBSA scoring."""
    _, _, lig_graph = smiles_to_topology(args.smiles, seed=args.seed)
    topo, coords, _, rec_idx, lig_idx = build_host_guest_complex(args.smiles, seed=args.seed)
    result = optimize_binding_pose(
        topo,
        coords,
        rec_idx,
        lig_idx,
        ligand_graph=lig_graph,
        n_iterations=args.iterations,
        seed=args.seed,
    )
    print(render_docking_summary(result, args.smiles))
    return {
        "total_score_kj_mol": result.total_score,
        "hbond_kj_mol": result.hbond,
        "gbsa_desolvation_kj_mol": result.gbsa_desolvation,
        "rmsd_nm": result.rmsd_from_initial,
    }


def _cmd_msm(args: argparse.Namespace) -> Dict[str, Any]:
    """Sample multi-trajectory alkane conformations and build a reversible Markov State Model."""
    topo, base_coords = build_alkane_chain(5, constrain_bonds=False)
    box = SimulationBox.orthorhombic(2.5, 2.5, 2.5)
    ff = ForceField(topo, ForceFieldConfig(cutoff=0.9, electrostatics="cutoff", dispersion_correction=False))
    feature_trajs: List[np.ndarray] = []

    for traj_idx in range(args.n_trajectories):
        cfg = SimulationConfig(
            dt_ps=0.002,
            n_steps=args.steps,
            ensemble="nvt",
            thermostat="baoab",
            temperature_k=450.0,
            friction_ps_inv=1.5,
            constraint_mode="none",
            save_interval=2,
            seed=args.seed + traj_idx * 41,
        )
        _, traj = run_simulation(topo, ff, base_coords + 1.25, box, config=cfg)
        feats = []
        for frame in traj.frames:
            p = frame.positions
            phi1 = compute_dihedral_angle(p[0], p[1], p[2], p[3], box)
            phi2 = compute_dihedral_angle(p[1], p[2], p[3], p[4], box)
            feats.append([np.cos(phi1), np.sin(phi1), np.cos(phi2), np.sin(phi2)])
        feature_trajs.append(np.asarray(feats, dtype=np.float64))

    msm = build_markov_state_model(
        feature_trajs,
        dt_frame_ps=0.004,
        lag_steps=3,
        n_states=args.states,
        seed=args.seed,
    )
    print(render_msm_summary(msm))
    return {
        "n_states": msm.n_states,
        "ck_error": msm.ck_error,
        "slowest_timescale_ps": float(msm.implied_timescales_ps[0]) if msm.implied_timescales_ps.size else 0.0,
    }


def _cmd_calibrate(args: argparse.Namespace) -> Dict[str, Any]:
    """Run Nelder-Mead LJ parameter calibration, Sobol sensitivity, and conservation audit."""
    cal = calibrate_lj_parameters(max_iter=args.max_iter, seed=args.seed)
    audit = run_conservation_audit(seed=args.seed)
    lines = [
        "=== Force-Field Calibration & Sobol Sensitivity ===",
        f"  Initial Loss  : {cal.initial_loss:.5f}",
        f"  Final Loss    : {cal.best_loss:.5f} (evals={cal.evaluations})",
        f"  Best sigma_nm : {cal.best_params['sigma_nm']:.5f}",
        f"  Best eps_kj   : {cal.best_params['epsilon_kj_mol']:.5f}",
        f"  Sobol S1      : {cal.sobol_first_order}",
        f"  Sobol ST      : {cal.sobol_total_order}",
        "",
        "=== Physics Conservation & Spectral Accuracy Audit ===",
        f"  NVE Relative Energy Drift     : {audit.nve_relative_energy_drift:.3e}",
        f"  LINCS Constraint RMS Error    : {audit.lincs_constraint_rms_nm:.3e} nm",
        f"  PME vs Exact Energy Rel Error : {audit.pme_vs_exact_energy_rel_err:.3e}",
        f"  PME vs Exact Force Rel RMSE   : {audit.pme_vs_exact_force_rel_rmse:.3e}",
        f"  NHC Extended Hamiltonian Drift: {audit.nhc_conserved_drift_rel:.3e}",
    ]
    print(assert_strict_ascii("\n".join(lines)))
    return {
        "best_loss": cal.best_loss,
        "pme_energy_rel_err": audit.pme_vs_exact_energy_rel_err,
        "lincs_rms_nm": audit.lincs_constraint_rms_nm,
    }


def _cmd_demo(args: argparse.Namespace) -> Dict[str, Any]:
    """Run an end-to-end showcase across MD, Docking, MBAR, WHAM, and Conservation Audit."""
    print(assert_strict_ascii("================ CHEMI-VERLET END-TO-END DEMO ================"))
    sim_ns = argparse.Namespace(
        smiles="CCO", box_nm=2.2, waters=10, electrostatics="pme",
        dt=0.002, steps=60, ensemble="nvt", thermostat="nhc",
        temp=300.0, pressure=1.0, constraints="lincs", seed=args.seed,
    )
    res_sim = _cmd_simulate(sim_ns)
    print()
    dock_ns = argparse.Namespace(smiles="c1ccccc1O", iterations=120, seed=args.seed)
    res_dock = _cmd_dock(dock_ns)
    print()
    cal_ns = argparse.Namespace(max_iter=12, seed=args.seed)
    res_cal = _cmd_calibrate(cal_ns)
    return {"simulate": res_sim, "dock": res_dock, "calibrate": res_cal}


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser with 7 scientific subcommands."""
    parser = argparse.ArgumentParser(
        prog="chemi-verlet",
        description="Atomistic molecular dynamics, PME electrostatics, MBAR FEP, WHAM, and docking CLI",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON summary after ASCII report")
    sub = parser.add_subparsers(dest="command", required=True)

    p_sim = sub.add_parser("simulate", help="Run NVE/NVT/NPT MD simulation on a solvated SMILES solute")
    p_sim.add_argument("--smiles", default="CCO", help="Solute SMILES string")
    p_sim.add_argument("--waters", type=int, default=12, help="Number of explicit 3-site water molecules")
    p_sim.add_argument("--box-nm", type=float, default=2.2, help="Cubic box edge length (nm)")
    p_sim.add_argument("--ensemble", choices=["nve", "nvt", "npt"], default="nvt")
    p_sim.add_argument("--thermostat", choices=["baoab", "nhc"], default="baoab")
    p_sim.add_argument("--electrostatics", choices=["pme", "reaction_field", "cutoff"], default="pme")
    p_sim.add_argument("--constraints", choices=["lincs", "shake", "none"], default="lincs")
    p_sim.add_argument("--dt", type=float, default=0.002, help="Timestep (ps)")
    p_sim.add_argument("--steps", type=int, default=100, help="Integration steps")
    p_sim.add_argument("--temp", type=float, default=300.0, help="Target temperature (K)")
    p_sim.add_argument("--pressure", type=float, default=1.0, help="Target pressure (bar)")
    p_sim.add_argument("--seed", type=int, default=42)

    p_alc = sub.add_parser("alchemical", help="Run multi-lambda alchemical FEP/TI/BAR/MBAR")
    p_alc.add_argument("--smiles", default="CCO")
    p_alc.add_argument("--waters", type=int, default=8)
    p_alc.add_argument("--windows", type=int, default=5)
    p_alc.add_argument("--steps-per-window", type=int, default=80)
    p_alc.add_argument("--temp", type=float, default=300.0)
    p_alc.add_argument("--seed", type=int, default=42)

    p_umb = sub.add_parser("umbrella", help="Run umbrella sampling and WHAM PMF reconstruction")
    p_umb.add_argument("--smiles", default="c1ccccc1O")
    p_umb.add_argument("--windows", type=int, default=6)
    p_umb.add_argument("--steps-per-window", type=int, default=80)
    p_umb.add_argument("--seed", type=int, default=42)

    p_dock = sub.add_parser("dock", help="Score and optimize a SMILES ligand in a receptor pocket")
    p_dock.add_argument("--smiles", default="CC(=O)Oc1ccccc1C(=O)O")
    p_dock.add_argument("--iterations", type=int, default=200)
    p_dock.add_argument("--seed", type=int, default=42)

    p_msm = sub.add_parser("msm", help="Build TICA + reversible Markov State Model from alkane MD")
    p_msm.add_argument("--n-trajectories", type=int, default=4)
    p_msm.add_argument("--steps", type=int, default=120)
    p_msm.add_argument("--states", type=int, default=4)
    p_msm.add_argument("--seed", type=int, default=42)

    p_cal = sub.add_parser("calibrate", help="Calibrate LJ parameters, Sobol indices, and conservation audit")
    p_cal.add_argument("--max-iter", type=int, default=20)
    p_cal.add_argument("--seed", type=int, default=42)

    p_demo = sub.add_parser("demo", help="Run end-to-end showcase across core subsystems")
    p_demo.add_argument("--seed", type=int, default=42)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point for ``chemi-verlet`` CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)
    dispatch = {
        "simulate": _cmd_simulate,
        "alchemical": _cmd_alchemical,
        "umbrella": _cmd_umbrella,
        "dock": _cmd_dock,
        "msm": _cmd_msm,
        "calibrate": _cmd_calibrate,
        "demo": _cmd_demo,
    }
    summary = dispatch[args.command](args)
    if args.json:
        print(assert_strict_ascii(json.dumps(summary, indent=2)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
