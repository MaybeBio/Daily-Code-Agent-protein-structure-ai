"""Tests for Zwanzig FEP, BAR, MBAR statistical mechanics and alchemical cycles."""

from __future__ import annotations

import numpy as np
import pytest

from chemi_verlet.alchemical import (
    build_default_lambda_schedule,
    compute_relative_binding_ddg,
    run_alchemical_fep,
    solve_bar_pair,
    solve_mbar,
    zwanzig_fep,
)
from chemi_verlet.forcefield import ForceField, ForceFieldConfig
from chemi_verlet.topology import build_solvated_ligand_box


def test_bar_and_mbar_recover_analytical_gaussian_free_energy() -> None:
    """For 1D harmonic oscillators U_k(x) = 0.5 * k_k * (x - x_k)^2 at beta=1:

    F_k = -0.5 * ln(2*pi / k_k), so F_1 - F_0 = 0.5 * ln(k_1 / k_0).
    """
    rng = np.random.default_rng(51)
    k_vals = [1.0, 2.5, 6.0]
    x_centers = [0.0, 0.7, 1.4]
    n_per_state = 1200

    samples = [
        rng.normal(loc=xc, scale=1.0 / np.sqrt(kv), size=n_per_state)
        for kv, xc in zip(k_vals, x_centers)
    ]
    x_all = np.concatenate(samples)
    u_kn = np.vstack([0.5 * kv * ((x_all - xc) ** 2) for kv, xc in zip(k_vals, x_centers)])

    true_df_02 = 0.5 * np.log(k_vals[2] / k_vals[0])
    true_df_01 = 0.5 * np.log(k_vals[1] / k_vals[0])

    # Check BAR on pair (0, 1)
    du_f = u_kn[1, :n_per_state] - u_kn[0, :n_per_state]
    du_r = u_kn[0, n_per_state: 2 * n_per_state] - u_kn[1, n_per_state: 2 * n_per_state]
    bar_df, bar_sig = solve_bar_pair(du_f, du_r)
    assert abs(bar_df - true_df_01) < max(0.08, 4.0 * bar_sig)

    # Check MBAR across all 3 states
    f_k, df_sig, overlap, ess = solve_mbar(u_kn, [n_per_state] * 3)
    assert pytest.approx(f_k[0], abs=1e-12) == 0.0
    assert abs(f_k[2] - true_df_02) < max(0.08, 4.0 * df_sig[0, 2])
    np.testing.assert_allclose(np.sum(overlap, axis=1), 1.0, atol=1e-9)
    assert np.all(ess > 50.0)


def test_bar_and_mbar_identical_states_zero_uncertainty() -> None:
    rng = np.random.default_rng(52)
    x = rng.normal(0.0, 1.0, size=200)
    u_0 = 0.5 * x * x
    df_bar, sig_bar = solve_bar_pair(np.zeros(200), np.zeros(200))
    assert pytest.approx(df_bar, abs=1e-10) == 0.0
    assert pytest.approx(sig_bar, abs=1e-10) == 0.0

    u_kn = np.vstack([u_0, u_0])
    f_k, df_sig, _, _ = solve_mbar(u_kn, [100, 100])
    assert pytest.approx(f_k[1], abs=1e-9) == 0.0
    assert pytest.approx(df_sig[0, 1], abs=1e-7) == 0.0
    assert pytest.approx(zwanzig_fep(np.zeros(50)), abs=1e-12) == 0.0


def test_alchemical_hydration_pipeline_consistency() -> None:
    topo, coords, box = build_solvated_ligand_box("CO", box_length_nm=2.2, n_waters=6, seed=53)
    ff = ForceField(topo, ForceFieldConfig(cutoff=0.9, electrostatics="pme"))
    sched = build_default_lambda_schedule(5)
    est = run_alchemical_fep(
        topo,
        ff,
        coords,
        box,
        lambda_schedule=sched,
        steps_per_window=60,
        equilibration_steps=15,
        sample_interval=5,
        seed=53,
    )
    assert np.isfinite(est.delta_g_mbar)
    assert np.isfinite(est.delta_g_bar)
    assert np.isfinite(est.delta_g_ti)
    assert est.sigma_mbar >= 0.0
    assert abs(est.delta_g_mbar - est.delta_g_bar) < 12.0
    ddg, sig = compute_relative_binding_ddg(est, est)
    assert pytest.approx(ddg, abs=1e-12) == 0.0
    assert sig >= 0.0
