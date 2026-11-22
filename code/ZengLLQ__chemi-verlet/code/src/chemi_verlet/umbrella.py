"""Umbrella sampling, self-consistent WHAM PMF reconstruction, and Jarzynski SMD.

Implements:
    * Log-space self-consistent Weighted Histogram Analysis Method (WHAM)
      computing unbiased bin probabilities, window free-energy offsets, and
      block-bootstrap PMF uncertainty bands
    * Multi-window umbrella sampling MD driver along a receptor-ligand COM
      distance collective variable
    * Jarzynski exponential work equality for non-equilibrium steered MD
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple
import numpy as np
from scipy.special import logsumexp

from chemi_verlet.forcefield import ForceField, HarmonicCOMRestraint
from chemi_verlet.integrators import SimulationConfig, run_simulation
from chemi_verlet.pbc import minimum_image_displacement
from chemi_verlet.types import FloatArray, KB_KJ_MOL_K, PMFProfile, SimulationBox, Topology


def solve_wham(
    window_samples: Sequence[FloatArray],
    window_centers: Sequence[float],
    spring_constants: Sequence[float],
    temperature_k: float = 300.0,
    n_bins: int = 25,
    xi_range: Optional[Tuple[float, float]] = None,
    tol: float = 1e-9,
    max_iter: int = 2000,
    n_bootstrap: int = 40,
    seed: int = 42,
) -> PMFProfile:
    """Reconstruct unbiased Potential of Mean Force via self-consistent WHAM.

    Parameters
    ----------
    window_samples:
        Sequence of 1D arrays containing sampled collective variable ``xi`` values
        for each umbrella window.
    window_centers:
        Harmonic restraint centers ``xi_0^(w)``.
    spring_constants:
        Harmonic force constants ``k_w`` in ``kJ / (mol * [xi]^2)`` for
        ``U_bias(xi) = 0.5 * k_w * (xi - xi_0)^2``.
    """
    n_win = len(window_samples)
    if n_win < 2:
        raise ValueError("WHAM requires at least 2 umbrella windows")
    if len(window_centers) != n_win or len(spring_constants) != n_win:
        raise ValueError("window_centers and spring_constants must match window_samples length")

    samples_list = [np.asarray(s, dtype=np.float64).ravel() for s in window_samples]
    if any(s.size == 0 for s in samples_list):
        raise ValueError("All umbrella windows must contain at least one sample")

    kbt = KB_KJ_MOL_K * temperature_k
    beta = 1.0 / kbt
    all_xi = np.concatenate(samples_list)
    xi_min = float(np.min(all_xi)) if xi_range is None else float(xi_range[0])
    xi_max = float(np.max(all_xi)) if xi_range is None else float(xi_range[1])
    if xi_max <= xi_min:
        xi_max = xi_min + 1e-3

    edges = np.linspace(xi_min, xi_max, n_bins + 1)
    centers = 0.5 * (edges[:-1] + edges[1:])

    # Histogram counts M_{w, b}
    hist_counts = np.zeros((n_win, n_bins), dtype=np.float64)
    n_w = np.zeros(n_win, dtype=np.float64)
    for w, samp in enumerate(samples_list):
        counts, _ = np.histogram(samp, bins=edges)
        hist_counts[w] = counts.astype(np.float64)
        n_w[w] = float(np.sum(counts))

    # Avoid empty tail bins breaking log-space normalization
    total_bin_counts = np.sum(hist_counts, axis=0)
    active_bins = total_bin_counts > 0.0

    # Reduced bias matrix u_bias[w, b] = beta * 0.5 * k_w * (xi_b - xi_0_w)^2
    xi0 = np.asarray(window_centers, dtype=np.float64)[:, None]
    kw = np.asarray(spring_constants, dtype=np.float64)[:, None]
    u_bias = beta * 0.5 * kw * ((centers[None, :] - xi0) ** 2)

    def _run_wham_core(counts_wb: FloatArray, nw_vec: FloatArray) -> Tuple[FloatArray, FloatArray, int, float]:
        tot_b = np.sum(counts_wb, axis=0)
        act = tot_b > 0.0
        f_w = np.zeros(n_win, dtype=np.float64)
        log_nw = np.log(np.maximum(nw_vec, 1.0))
        log_prob = np.full(n_bins, -np.inf, dtype=np.float64)
        residual = 0.0
        iters = 0

        for it in range(1, max_iter + 1):
            iters = it
            # log P_b = log(sum_w M_{w,b}) - logsumexp_w (log N_w + f_w - u_{w,b})
            log_denom_b = logsumexp((log_nw + f_w)[:, None] - u_bias[:, act], axis=0)
            log_prob_act = np.log(tot_b[act]) - log_denom_b
            log_prob_act -= logsumexp(log_prob_act)
            log_prob[act] = log_prob_act

            # f_w_new = -logsumexp_b (log P_b - u_{w,b})
            f_new = -logsumexp(log_prob_act[None, :] - u_bias[:, act], axis=1)
            f_new -= f_new[0]
            residual = float(np.max(np.abs(f_new - f_w)))
            f_w = f_new
            if residual < tol:
                break

        prob = np.zeros(n_bins, dtype=np.float64)
        prob[act] = np.exp(log_prob[act])
        prob /= max(float(np.sum(prob)), 1e-15)
        return prob, f_w, iters, residual

    prob_main, fw_main, iters_main, res_main = _run_wham_core(hist_counts, n_w)

    pmf = np.full(n_bins, np.nan, dtype=np.float64)
    pmf[active_bins] = -kbt * np.log(np.maximum(prob_main[active_bins], 1e-300))
    min_pmf = float(np.nanmin(pmf))
    pmf = np.where(active_bins, pmf - min_pmf, np.nan)

    # Bootstrap uncertainty estimation across windows
    rng = np.random.default_rng(seed)
    boot_pmfs = np.full((n_bootstrap, n_bins), np.nan, dtype=np.float64)
    for b_idx in range(n_bootstrap):
        b_counts = np.zeros_like(hist_counts)
        b_nw = np.zeros_like(n_w)
        for w, samp in enumerate(samples_list):
            # Block bootstrap by splitting window into 5 contiguous blocks when possible
            m = samp.size
            if m >= 10:
                block_len = max(2, m // 5)
                n_blocks = max(1, m // block_len)
                chosen = rng.integers(0, n_blocks, size=n_blocks)
                resampled = np.concatenate([samp[c * block_len: (c + 1) * block_len] for c in chosen])
            else:
                resampled = rng.choice(samp, size=m, replace=True)
            cnt, _ = np.histogram(resampled, bins=edges)
            b_counts[w] = cnt.astype(np.float64)
            b_nw[w] = float(np.sum(cnt))
        if np.any(b_nw <= 0):
            continue
        p_b, _, _, _ = _run_wham_core(b_counts, b_nw)
        act_b = p_b > 1e-300
        if np.any(act_b):
            w_pmf = np.full(n_bins, np.nan, dtype=np.float64)
            w_pmf[act_b] = -kbt * np.log(p_b[act_b])
            w_pmf[act_b] -= float(np.nanmin(w_pmf))
            boot_pmfs[b_idx] = w_pmf

    pmf_unc = np.zeros(n_bins, dtype=np.float64)
    for idx in range(n_bins):
        col = boot_pmfs[:, idx]
        valid = col[~np.isnan(col)]
        if valid.size >= 2:
            pmf_unc[idx] = float(np.std(valid, ddof=1))

    # Neighbor-window histogram overlap metric (Bhattacharyya coefficient)
    overlaps = np.zeros(max(0, n_win - 1), dtype=np.float64)
    for w in range(n_win - 1):
        p1 = hist_counts[w] / max(n_w[w], 1.0)
        p2 = hist_counts[w + 1] / max(n_w[w + 1], 1.0)
        overlaps[w] = float(np.sum(np.sqrt(p1 * p2)))

    return PMFProfile(
        bin_centers=centers,
        pmf_kj_mol=pmf,
        pmf_uncertainty_kj_mol=pmf_unc,
        probability_density=prob_main,
        window_free_energies=fw_main * kbt,
        iterations=iters_main,
        residual=res_main,
        overlap_fractions=overlaps,
    )


def compute_com_distance(
    positions: FloatArray,
    masses: FloatArray,
    group_a: Sequence[int],
    group_b: Sequence[int],
    box: SimulationBox,
) -> float:
    """Compute minimum-image distance (nm) between centers of mass of two groups."""
    ia = np.asarray(group_a, dtype=np.int64)
    ib = np.asarray(group_b, dtype=np.int64)
    wa = masses[ia] / np.sum(masses[ia])
    wb = masses[ib] / np.sum(masses[ib])
    com_a = np.sum(positions[ia] * wa[:, None], axis=0)
    com_b = np.sum(positions[ib] * wb[:, None], axis=0)
    dr = minimum_image_displacement(com_b - com_a, box)
    return float(np.linalg.norm(dr))


def run_umbrella_sampling(
    topology: Topology,
    force_field: ForceField,
    initial_positions: FloatArray,
    box: SimulationBox,
    group_a: Sequence[int],
    group_b: Sequence[int],
    r_start_nm: float = 0.25,
    r_end_nm: float = 0.95,
    n_windows: int = 8,
    k_restraint: float = 2500.0,
    steps_per_window: int = 120,
    equilibration_steps: int = 30,
    sample_interval: int = 2,
    temperature_k: float = 300.0,
    dt_ps: float = 0.002,
    seed: int = 42,
) -> Tuple[PMFProfile, List[FloatArray]]:
    """Run multi-window umbrella sampling along COM distance and reconstruct PMF via WHAM."""
    centers = np.linspace(r_start_nm, r_end_nm, n_windows)
    springs = np.full(n_windows, k_restraint, dtype=np.float64)
    window_samples: List[FloatArray] = []

    ia = tuple(int(i) for i in group_a)
    ib = tuple(int(i) for i in group_b)
    cur_pos = initial_positions.copy()

    for w_idx, r0 in enumerate(centers):
        # Gently shift group_b toward target r0 before equilibration
        masses = topology.masses
        wa = masses[list(ia)] / np.sum(masses[list(ia)])
        wb = masses[list(ib)] / np.sum(masses[list(ib)])
        com_a = np.sum(cur_pos[list(ia)] * wa[:, None], axis=0)
        com_b = np.sum(cur_pos[list(ib)] * wb[:, None], axis=0)
        dr = minimum_image_displacement(com_b - com_a, box)
        d_cur = max(float(np.linalg.norm(dr)), 1e-6)
        unit = dr / d_cur if d_cur > 1e-5 else np.array([0.0, 0.0, 1.0])
        cur_pos[list(ib)] += (float(r0) - d_cur) * unit

        force_field.clear_restraints()
        force_field.add_com_restraint(HarmonicCOMRestraint(ia, ib, float(r0), float(k_restraint)))
        cfg = SimulationConfig(
            dt_ps=dt_ps,
            n_steps=steps_per_window,
            ensemble="nvt",
            thermostat="baoab",
            temperature_k=temperature_k,
            friction_ps_inv=2.5,
            constraint_mode="lincs",
            save_interval=max(1, sample_interval),
            seed=seed + 53 * w_idx,
        )
        final_state, traj = run_simulation(
            topology, force_field, cur_pos, box, config=cfg, minimize=(w_idx == 0)
        )
        cur_pos = final_state.positions.copy()
        prod = [f for f in traj.frames if f.step >= equilibration_steps]
        if not prod:
            prod = traj.frames[max(0, len(traj.frames) // 2):]
        xis = np.array(
            [compute_com_distance(f.positions, masses, ia, ib, f.box) for f in prod],
            dtype=np.float64,
        )
        window_samples.append(xis)

    force_field.clear_restraints()
    pmf = solve_wham(
        window_samples=window_samples,
        window_centers=centers.tolist(),
        spring_constants=springs.tolist(),
        temperature_k=temperature_k,
        n_bins=max(16, 3 * n_windows),
        seed=seed + 999,
    )
    return pmf, window_samples


def jarzynski_free_energy(work_values_kj_mol: Sequence[float], temperature_k: float = 300.0) -> Tuple[float, float]:
    """Estimate equilibrium ``Delta F`` from non-equilibrium work values via Jarzynski equality.

    Returns ``(delta_f_jarzynski, delta_f_cumulant_2nd_order)`` in kJ/mol.
    """
    w = np.asarray(work_values_kj_mol, dtype=np.float64)
    if w.size == 0:
        raise ValueError("Jarzynski estimator requires at least one work trajectory")
    kbt = KB_KJ_MOL_K * temperature_k
    beta = 1.0 / kbt
    df_exp = -kbt * float(logsumexp(-beta * w) - np.log(w.size))
    var_w = float(np.var(w, ddof=1)) if w.size > 1 else 0.0
    df_cum2 = float(np.mean(w)) - 0.5 * beta * var_w
    return df_exp, df_cum2
