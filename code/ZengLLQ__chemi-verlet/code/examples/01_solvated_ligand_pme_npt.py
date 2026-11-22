"""Example 1: Solvated Ethanol PME Molecular Dynamics with LINCS and NPT Equilibration."""

from __future__ import annotations

from chemi_verlet.forcefield import ForceField, ForceFieldConfig
from chemi_verlet.integrators import SimulationConfig, run_simulation
from chemi_verlet.topology import build_solvated_ligand_box, write_pdb
from chemi_verlet.trajectory import compute_rdf, detect_hydrogen_bonds, kabsch_rmsd
from chemi_verlet.visualizer import assert_strict_ascii, render_energy_profile, render_rdf_plot


def main() -> None:
    topo, coords, box = build_solvated_ligand_box(
        smiles="CCO",
        box_length_nm=2.3,
        n_waters=14,
        constrain_solvent=True,
        seed=42,
    )
    ff = ForceField(
        topo,
        ForceFieldConfig(
            cutoff=0.9,
            switch_distance=0.75,
            electrostatics="pme",
            pme_grid_spacing=0.12,
            pme_spline_order=4,
        ),
    )

    # Stage 1: NVT Nosé-Hoover Chain equilibration with LINCS rigid X-H & TIP3P constraints
    nvt_cfg = SimulationConfig(
        dt_ps=0.002,
        n_steps=80,
        ensemble="nvt",
        thermostat="nhc",
        temperature_k=300.0,
        constraint_mode="lincs",
        save_interval=4,
        seed=42,
    )
    state_nvt, traj_nvt = run_simulation(topo, ff, coords, box, config=nvt_cfg)

    # Stage 2: NPT Monte-Carlo barostat relaxation at 1.0 bar
    npt_cfg = SimulationConfig(
        dt_ps=0.002,
        n_steps=60,
        ensemble="npt",
        thermostat="baoab",
        barostat="mc",
        temperature_k=300.0,
        pressure_bar=1.0,
        mc_barostat_freq=10,
        constraint_mode="lincs",
        save_interval=5,
        seed=43,
    )
    state_npt, traj_npt = run_simulation(
        topo, ff, state_nvt.positions, state_nvt.box, config=npt_cfg, minimize=False
    )

    ow_idx = [a.index for a in topo.atoms if a.name == "OW"]
    r_nm, g_r = compute_rdf(traj_npt, ow_idx, ow_idx, r_max=0.95, n_bins=22)
    hbonds = detect_hydrogen_bonds(topo, state_npt.positions, state_npt.box)
    rmsd = kabsch_rmsd(state_npt.positions, coords)
    pdb_preview = write_pdb(topo, state_npt.positions, state_npt.box).splitlines()[:5]

    print(assert_strict_ascii(
        f"Solvated Ethanol PME+LINCS | Atoms={topo.n_atoms} | "
        f"NVT_T={state_nvt.energy.temperature:.2f} K | NPT_V={state_npt.box.volume:.3f} nm^3 | "
        f"LINCS_RMS={state_npt.constraint_rms_error:.2e} nm | H-bonds={len(hbonds)} | RMSD={rmsd:.4f} nm"
    ))
    print(render_energy_profile(traj_nvt))
    print()
    print(render_rdf_plot(r_nm, g_r))
    print("\nPDB header preview:")
    print(assert_strict_ascii("\n".join(pdb_preview)))


if __name__ == "__main__":
    main()
