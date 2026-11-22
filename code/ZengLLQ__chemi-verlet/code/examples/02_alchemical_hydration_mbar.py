"""Example 2: Alchemical Hydration Free Energy via Staged Lambda-Schedule MBAR/BAR/TI/FEP."""

from __future__ import annotations

from chemi_verlet.alchemical import (
    build_default_lambda_schedule,
    compute_relative_binding_ddg,
    run_alchemical_fep,
)
from chemi_verlet.forcefield import ForceField, ForceFieldConfig
from chemi_verlet.topology import build_host_guest_complex, build_solvated_ligand_box
from chemi_verlet.visualizer import assert_strict_ascii, render_mbar_summary


def main() -> None:
    schedule = build_default_lambda_schedule(n_windows=5)

    # Leg 1: Solvent decoupling of methanol (CO) in explicit TIP3P water
    sol_topo, sol_coords, sol_box = build_solvated_ligand_box("CO", box_length_nm=2.2, n_waters=8, seed=101)
    sol_ff = ForceField(sol_topo, ForceFieldConfig(cutoff=0.9, electrostatics="pme"))
    sol_est = run_alchemical_fep(
        sol_topo,
        sol_ff,
        sol_coords,
        sol_box,
        lambda_schedule=schedule,
        steps_per_window=60,
        equilibration_steps=15,
        sample_interval=5,
        seed=101,
    )

    # Leg 2: Complex decoupling of methanol in structured receptor pocket
    comp_topo, comp_coords, comp_box, _, _ = build_host_guest_complex("CO", seed=102)
    comp_ff = ForceField(comp_topo, ForceFieldConfig(cutoff=1.0, electrostatics="reaction_field"))
    comp_est = run_alchemical_fep(
        comp_topo,
        comp_ff,
        comp_coords,
        comp_box,
        lambda_schedule=schedule,
        steps_per_window=60,
        equilibration_steps=15,
        sample_interval=5,
        seed=102,
    )

    ddg_bind, ddg_sig = compute_relative_binding_ddg(comp_est, sol_est)
    print(assert_strict_ascii("=== Leg 1: Solvent Decoupling (CO in Water) ==="))
    print(render_mbar_summary(sol_est))
    print()
    print(assert_strict_ascii("=== Leg 2: Complex Decoupling (CO in Pocket) ==="))
    print(render_mbar_summary(comp_est))
    print()
    print(assert_strict_ascii(
        f"Thermodynamic Cycle dG_bind (MBAR) = {ddg_bind:.3f} +/- {ddg_sig:.3f} kJ/mol"
    ))


if __name__ == "__main__":
    main()
