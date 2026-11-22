"""Example 3: Umbrella Sampling Pulling & Self-Consistent WHAM PMF Reconstruction."""

from __future__ import annotations

import numpy as np

from chemi_verlet.forcefield import ForceField, ForceFieldConfig
from chemi_verlet.topology import build_host_guest_complex
from chemi_verlet.umbrella import jarzynski_free_energy, run_umbrella_sampling
from chemi_verlet.visualizer import assert_strict_ascii, render_pmf_profile


def main() -> None:
    topo, coords, box, rec_idx, lig_idx = build_host_guest_complex("c1ccccc1O", seed=202)
    ff = ForceField(topo, ForceFieldConfig(cutoff=1.0, electrostatics="reaction_field"))

    pmf, window_samples = run_umbrella_sampling(
        topo,
        ff,
        coords,
        box,
        rec_idx,
        lig_idx,
        r_start_nm=0.22,
        r_end_nm=0.80,
        n_windows=6,
        k_restraint=2200.0,
        steps_per_window=70,
        equilibration_steps=20,
        sample_interval=2,
        seed=202,
    )

    valid = pmf.pmf_kj_mol[~np.isnan(pmf.pmf_kj_mol)]
    barrier = float(np.max(valid) - np.min(valid)) if valid.size else 0.0
    print(render_pmf_profile(pmf))
    print(assert_strict_ascii(
        f"\nReconstructed PMF Barrier = {barrier:.3f} kJ/mol across {len(window_samples)} windows"
    ))

    # Demonstrate Jarzynski equality on synthetic pulling work values
    rng = np.random.default_rng(202)
    works = rng.normal(loc=barrier + 1.8, scale=2.2, size=500)
    df_jarz, df_cum2 = jarzynski_free_energy(works, temperature_k=300.0)
    print(assert_strict_ascii(
        f"Jarzynski Steered-MD Estimate: dF_exp={df_jarz:.3f} kJ/mol, dF_cum2={df_cum2:.3f} kJ/mol"
    ))


if __name__ == "__main__":
    main()
