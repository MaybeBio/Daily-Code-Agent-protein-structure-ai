"""Tests for WHAM umbrella sampling PMF reconstruction and Jarzynski work estimator."""

from __future__ import annotations

import numpy as np

from chemi_verlet.forcefield import ForceField, ForceFieldConfig
from chemi_verlet.topology import build_host_guest_complex
from chemi_verlet.types import KB_KJ_MOL_K
from chemi_verlet.umbrella import jarzynski_free_energy, run_umbrella_sampling, solve_wham


def test_wham_recovers_analytical_double_well_pmf() -> None:
    """Sample biased Langevin/Metropolis draws on a known double-well potential and recover W(x)."""
    rng = np.random.default_rng(61)
    temp = 300.0
    kbt = KB_KJ_MOL_K * temp
    beta = 1.0 / kbt

    # Analytical potential W(x) = 8 * (x^2 - 1)^2 + 1.5 * x (in kJ/mol) on [-1.5, 1.5]
    def _w_true(x: float | np.ndarray) -> float | np.ndarray:
        return 8.0 * ((x * x - 1.0) ** 2) + 1.5 * x

    centers = np.linspace(-1.3, 1.3, 11)
    k_spring = 45.0
    samples = []
    for xc in centers:
        # Metropolis-Hastings sampling under W(x) + 0.5*k*(x-xc)^2
        x_cur = float(xc)
        u_cur = float(_w_true(x_cur)) + 0.5 * k_spring * (x_cur - xc) ** 2
        draws = []
        for step in range(900):
            x_prop = x_cur + float(rng.normal(0.0, 0.14))
            if -1.6 < x_prop < 1.6:
                u_prop = float(_w_true(x_prop)) + 0.5 * k_spring * (x_prop - xc) ** 2
                if u_prop <= u_cur or rng.uniform() < np.exp(-beta * (u_prop - u_cur)):
                    x_cur, u_cur = x_prop, u_prop
            if step >= 150:
                draws.append(x_cur)
        samples.append(np.asarray(draws, dtype=np.float64))

    pmf = solve_wham(
        window_samples=samples,
        window_centers=centers.tolist(),
        spring_constants=[k_spring] * len(centers),
        temperature_k=temp,
        n_bins=24,
        xi_range=(-1.35, 1.35),
        n_bootstrap=20,
        seed=61,
    )
    assert pmf.residual < 1e-7
    assert np.all(pmf.overlap_fractions > 0.05)

    # Compare interior bins [-1.15, 1.15] against shifted analytical W_true
    mask = (~np.isnan(pmf.pmf_kj_mol)) & (np.abs(pmf.bin_centers) <= 1.15)
    w_ref = _w_true(pmf.bin_centers[mask])
    w_ref -= np.min(w_ref)
    w_est = pmf.pmf_kj_mol[mask]
    w_est -= np.min(w_est)
    rmse = float(np.sqrt(np.mean((w_est - w_ref) ** 2)))
    assert rmse < 1.2


def test_jarzynski_equality_on_gaussian_work_distribution() -> None:
    rng = np.random.default_rng(62)
    temp = 300.0
    kbt = KB_KJ_MOL_K * temp
    df_true = 10.0
    sigma_w = 2.0
    # Fluctuation-dissipation identity for Gaussian work: mean(W) = dF + 0.5 * beta * sigma_W^2
    mean_w = df_true + 0.5 * (1.0 / kbt) * (sigma_w ** 2)
    works = rng.normal(mean_w, sigma_w, size=4000)
    df_exp, df_cum2 = jarzynski_free_energy(works, temperature_k=temp)
    assert abs(df_exp - df_true) < 0.35
    assert abs(df_cum2 - df_true) < 0.25


def test_host_guest_umbrella_sampling_pipeline() -> None:
    topo, coords, box, rec_idx, lig_idx = build_host_guest_complex("CO", seed=63)
    ff = ForceField(topo, ForceFieldConfig(cutoff=1.0, electrostatics="reaction_field"))
    pmf, win_samples = run_umbrella_sampling(
        topo,
        ff,
        coords,
        box,
        rec_idx,
        lig_idx,
        r_start_nm=0.25,
        r_end_nm=0.75,
        n_windows=5,
        k_restraint=2000.0,
        steps_per_window=50,
        equilibration_steps=15,
        sample_interval=2,
        seed=63,
    )
    assert len(win_samples) == 5
    assert np.any(~np.isnan(pmf.pmf_kj_mol))
    assert np.all(pmf.pmf_uncertainty_kj_mol >= 0.0)
