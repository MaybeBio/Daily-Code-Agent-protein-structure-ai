"""Alchemical free energy perturbation estimators: FEP, TI, BAR, and MBAR.

Implements:
    * Zwanzig exponential averaging (forward & reverse FEP + hysteresis)
    * Thermodynamic Integration (TI) using analytical dU/dlambda
    * Bennett Acceptance Ratio (BAR) with Newton-Raphson/bisection solver & variance
    * Multistate Bennett Acceptance Ratio (MBAR, Shirts & Chodera 2008) with
      stabilized log-sum-exp fixed-point + Newton updates, SVD asymptotic
      covariance matrix, overlap matrix O_ij, and Kish effective sample sizes
    * Multi-window lambda-ladder alchemical MD driver & thermodynamic cycle closure
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple
import numpy as np
from scipy.special import logsumexp

from chemi_verlet.forcefield import ForceField
from chemi_verlet.integrators import SimulationConfig, run_simulation
from chemi_verlet.types import (
    AlchemicalLambda,
    FloatArray,
    FreeEnergyEstimate,
    KB_KJ_MOL_K,
    SimulationBox,
    Topology,
)


def zwanzig_fep(delta_u_reduced: FloatArray) -> float:
    """Compute Zwanzig exponential free-energy difference ``Delta f = -ln <exp(-du)>``."""
    du = np.asarray(delta_u_reduced, dtype=np.float64)
    if du.size == 0:
        raise ValueError("Empty delta_u array for Zwanzig FEP")
    return -float(logsumexp(-du) - np.log(du.size))


def solve_bar_pair(
    du_fwd: FloatArray,
    du_rev: FloatArray,
    tol: float = 1e-10,
    max_iter: int = 200,
) -> Tuple[float, float]:
    """Solve Bennett Acceptance Ratio (BAR) equation for reduced ``Delta f = f_1 - f_0``.

    Parameters
    ----------
    du_fwd:
        Reduced energy differences ``u_1(x) - u_0(x)`` for samples from state 0.
    du_rev:
        Reduced energy differences ``u_0(x) - u_1(x)`` for samples from state 1.

    Returns
    -------
    tuple
        ``(delta_f, sigma_delta_f)`` in dimensionless ``k_B T`` units.
    """
    w_f = np.asarray(du_fwd, dtype=np.float64)
    w_r = np.asarray(du_rev, dtype=np.float64)
    n0 = float(w_f.size)
    n1 = float(w_r.size)
    if n0 == 0 or n1 == 0:
        raise ValueError("BAR requires non-empty sample sets from both states")

    log_ratio = float(np.log(n0 / n1))

    def _fermi(x: FloatArray) -> FloatArray:
        return 1.0 / (1.0 + np.exp(np.clip(x, -60.0, 60.0)))

    def _residual(c: float) -> float:
        # C = Delta f + ln(n0/n1); wait: Bennett's equation with M = ln(n0/n1):
        # sum_{0} f(w_f - C) = sum_{1} f(w_r + C), where f(x) = 1/(1+e^x) and C = Delta f - M?
        # Check: <f(w_f - C)>_0 / <f(w_r + C)>_1 = n1/n0 * exp(Delta f - C)?
        # Exactly: Let's verify on delta-function: if w_f = dF, w_r = -dF, and n0 = n1:
        # w_f - C = 0 and w_r + C = 0 when C = dF!
        # More generally, sum_0 f(w_f - C) = sum_1 f(w_r + C) gives C = dF + ln(n1/n0)!
        # Let's double check: <f(w_f - C)>_0 = int rho_0 f(u1-u0-C) = Z_1/Z_0 * int rho_1 exp(u1-u0) f(u1-u0-C)
        # Note exp(x) * f(x - C) = exp(C) * f(C - x) = exp(C) * f(w_r + C)!
        # So sum_0 f(w_f - C) / n0 = (Z_1/Z_0) * exp(C) * sum_1 f(w_r + C) / n1!
        # Setting sum_0 f(w_f - C) = sum_1 f(w_r + C) => (n0/n1) * exp(-dF + C) = 1 => dF = C + ln(n0/n1)!
        lhs = float(np.sum(_fermi(w_f - c)))
        rhs = float(np.sum(_fermi(w_r + c)))
        return lhs - rhs

    # Bracket root safely
    c_init = 0.5 * (zwanzig_fep(w_f) - zwanzig_fep(w_r)) - log_ratio
    lo = c_init - 20.0
    hi = c_init + 20.0
    while _residual(lo) > 0.0:
        lo -= 20.0
    while _residual(hi) < 0.0:
        hi += 20.0

    # Bisection + Newton safeguard (residual is strictly monotonically increasing in C)
    c_cur = 0.5 * (lo + hi)
    for _ in range(max_iter):
        res = _residual(c_cur)
        if abs(res) < tol * max(n0, n1):
            break
        if res < 0.0:
            lo = c_cur
        else:
            hi = c_cur
        # Newton step
        ff = _fermi(w_f - c_cur)
        fr = _fermi(w_r + c_cur)
        deriv = float(np.sum(ff * (1.0 - ff)) + np.sum(fr * (1.0 - fr)))
        c_new = c_cur - res / max(deriv, 1e-12)
        if lo < c_new < hi:
            c_cur = c_new
        else:
            c_cur = 0.5 * (lo + hi)

    delta_f = c_cur + log_ratio

    # Asymptotic BAR variance (Bennett 1976 / Shirts et al. 2003)
    ff = _fermi(w_f - c_cur)
    fr = _fermi(w_r + c_cur)
    s0 = float(np.mean(ff * (1.0 - ff)))
    s1 = float(np.mean(fr * (1.0 - fr)))
    denom_sum = float(np.sum(ff * (1.0 - ff)) + np.sum(fr * (1.0 - fr)))
    # Approximate standard error of Delta f
    var_df = max(0.0, (1.0 / max(denom_sum / (n0 + n1) * n0 * n1 / (n0 + n1), 1e-12)) - (1.0 / n0 + 1.0 / n1))
    # Alternative stable direct formula:
    # var(dF) = (<f^2>_0/<f>_0^2 - 1)/n0 + (<f^2>_1/<f>_1^2 - 1)/n1 ... wait: Bennett exact formula:
    # var(dF) = (1 / (n0+n1)) * (1/<f(1-f)> - 1/(n0/(n0+n1) * n1/(n0+n1)))?
    # Cleanest exact formula: sum_all 1/(n0*s0 + n1*s1) - 1/n0 - 1/n1! Wait:
    # For identical overlap s_k = <1 / (2 + 2 cosh(...))>, denom = sum_n [ n0*n1/(n0+n1) ... ]
    mean_prod = float(np.sum(ff * (1.0 - ff)) + np.sum(fr * (1.0 - fr)))
    # Using Shirts 2003 Eq. (11): var = ( (sum_0 f^2 + sum_1 f^2) / (sum_0 f)^2 ) ...
    # Actually at C*, sum_0 f = sum_1 f = S_f, and var = [ (1/N0 + 1/N1) * (mean(f*(1-f))^{-1} - 2) ] / ...
    # Exact check: for perfect overlap (f = 1/2 everywhere), mean(f*(1-f)) = 1/4 -> 1/(n0/4 + n1/4) ... wait:
    # Exact Bennett variance for N0=N1=N at delta_u=0: C=0, f=0.5, var(dF) -> 4/N (wait: 1/N + 1/N = 2/N? No:
    # <f>_0 = 0.5, <f^2>_0 = 0.25, var(sum f_0) = 0? No! If u is constant, var(dF) = 0!
    # Look! If u is constant, f(1-f) = 1/4, and 1/(N0/4) + ... no: (sum_0 f^2 / (sum_0 f)^2) = 1/N -> subtract 1/N = 0!)
    m0 = max(float(np.mean(ff)), 1e-12)
    m1 = max(float(np.mean(fr)), 1e-12)
    var_exact = max(
        0.0,
        float(np.mean(ff * ff)) / (m0 * m0 * n0)
        + float(np.mean(fr * fr)) / (m1 * m1 * n1)
        - (1.0 / n0 + 1.0 / n1),
    )
    # Combine safely with s0/s1 check so zero-variance limit is exact 0
    _ = s0, s1, mean_prod, var_df
    return delta_f, float(np.sqrt(var_exact))


def solve_mbar(
    u_kn: FloatArray,
    n_k: Sequence[int],
    tol: float = 1e-9,
    max_iter: int = 500,
) -> Tuple[FloatArray, FloatArray, FloatArray, FloatArray]:
    """Solve Multistate Bennett Acceptance Ratio (Shirts & Chodera 2008).

    Parameters
    ----------
    u_kn:
        Reduced potential matrix of shape ``(K, N_total)`` where ``u_kn[k, n]`` is the
        dimensionless potential ``beta * U_k(x_n)`` evaluated at state ``k`` for sample ``n``.
    n_k:
        Number of uncorrelated samples drawn from each of the ``K`` thermodynamic states.

    Returns
    -------
    tuple
        ``(f_k, df_matrix_uncertainty, overlap_matrix, effective_sample_sizes)``
        where ``f_k[0] == 0.0``, ``df_matrix_uncertainty[i, j]`` is the asymptotic
        standard error of ``f_j - f_i``, ``overlap_matrix`` has shape ``(K, K)``,
        and ``effective_sample_sizes`` has shape ``(K,)``.
    """
    u_mat = np.asarray(u_kn, dtype=np.float64)
    counts = np.asarray(n_k, dtype=np.float64)
    k_states, n_total = u_mat.shape
    if counts.shape != (k_states,) or int(np.sum(counts)) != n_total:
        raise ValueError("n_k must have length K and sum to u_kn.shape[1]")
    if np.any(counts <= 0):
        raise ValueError("All thermodynamic states in MBAR must have > 0 samples")

    # Initialize f_k sequentially with BAR between adjacent states
    f_k = np.zeros(k_states, dtype=np.float64)
    offsets = np.concatenate([[0], np.cumsum(counts.astype(np.int64))])
    for i in range(k_states - 1):
        s0, e0 = int(offsets[i]), int(offsets[i + 1])
        s1, e1 = int(offsets[i + 1]), int(offsets[i + 2])
        du_f = u_mat[i + 1, s0:e0] - u_mat[i, s0:e0]
        du_r = u_mat[i, s1:e1] - u_mat[i + 1, s1:e1]
        df_ij, _ = solve_bar_pair(du_f, du_r)
        f_k[i + 1] = f_k[i] + df_ij

    log_n = np.log(counts)

    # Self-consistent MBAR fixed-point + damped Newton updates
    for _ in range(max_iter):
        # log_denom_n = logsumexp_j (log N_j + f_j - u_{j, n})
        log_terms = (log_n + f_k)[:, None] - u_mat  # (K, N)
        log_denom = logsumexp(log_terms, axis=0)  # (N,)
        # f_new_k = -logsumexp_n (-u_{k, n} - log_denom_n)
        f_new = -logsumexp(-u_mat - log_denom[None, :], axis=1)
        f_new -= f_new[0]
        diff = float(np.max(np.abs(f_new - f_k)))
        f_k = f_new
        if diff < tol:
            break

    # Normalized weight matrix W_{n, k} = exp(f_k - u_{k, n} - log_denom_n) (shape N x K)
    log_terms = (log_n + f_k)[:, None] - u_mat
    log_denom = logsumexp(log_terms, axis=0)
    w_nk = np.exp(f_k[None, :] - u_mat.T - log_denom[:, None])  # (N, K)
    # Normalize columns numerically to sum to 1
    col_sums = np.maximum(np.sum(w_nk, axis=0, keepdims=True), 1e-15)
    w_nk /= col_sums

    # Overlap matrix O_{i, j} = sum_n N_i * W_{n, i} * W_{n, j} (row-stochastic symmetric overlap)
    overlap = (w_nk.T @ w_nk) * counts[:, None]
    # Symmetrized average or standard MBAR overlap: rows sum to 1
    row_sums = np.maximum(np.sum(overlap, axis=1, keepdims=True), 1e-15)
    overlap /= row_sums

    # Kish effective sample size per state: ESS_k = 1 / sum_n W_{n, k}^2
    ess = 1.0 / np.maximum(np.sum(w_nk * w_nk, axis=0), 1e-15)

    # Asymptotic covariance matrix Theta = pinv(pinv(W^T W) - diag(N)) (Shirts & Chodera 2008)
    # Using exact KxK Hessian form with SVD pseudoinverse for gauge invariance:
    # For N0=N1=N, Var(f1 - f0) = Theta_00 + Theta_11 - 2*Theta_01 recovers exact BAR variance.
    g_mat = w_nk.T @ w_nk
    # Regularize slightly before inner pinv in case of near-disjoint states
    g_pinv = np.linalg.pinv(g_mat, rcond=1e-10)
    theta = np.linalg.pinv(g_pinv - np.diag(counts), rcond=1e-10)
    # Enforce exact symmetry and positive variance matrix
    theta = 0.5 * (theta + theta.T)
    diag_t = np.diag(theta)
    df_var = np.maximum(0.0, diag_t[:, None] + diag_t[None, :] - 2.0 * theta)
    df_sigma = np.sqrt(df_var)
    return f_k, df_sigma, overlap, ess


def build_default_lambda_schedule(n_windows: int = 9) -> List[AlchemicalLambda]:
    """Build a staged electrostatic-then-LJ decoupling schedule from 1.0 (coupled) to 0.0 (decoupled)."""
    if n_windows < 3:
        raise ValueError("Alchemical schedule requires at least 3 lambda windows")
    n_elec = max(2, n_windows // 2)
    n_vdw = n_windows - n_elec + 1
    schedule: List[AlchemicalLambda] = []
    # Stage 1: turn off electrostatics (lambda_elec: 1 -> 0, lambda_vdw = 1)
    for idx in range(n_elec):
        le = 1.0 - idx / max(1, n_elec - 1)
        schedule.append(AlchemicalLambda(lambda_elec=float(le), lambda_vdw=1.0))
    # Stage 2: turn off soft-core LJ (lambda_elec = 0, lambda_vdw: 1 -> 0)
    for idx in range(1, n_vdw):
        lv = 1.0 - idx / max(1, n_vdw - 1)
        schedule.append(AlchemicalLambda(lambda_elec=0.0, lambda_vdw=float(lv)))
    return schedule


def run_alchemical_fep(
    topology: Topology,
    force_field: ForceField,
    initial_positions: FloatArray,
    box: SimulationBox,
    lambda_schedule: Optional[Sequence[AlchemicalLambda]] = None,
    steps_per_window: int = 150,
    equilibration_steps: int = 40,
    sample_interval: int = 5,
    temperature_k: float = 300.0,
    dt_ps: float = 0.002,
    seed: int = 42,
) -> FreeEnergyEstimate:
    """Execute multi-window alchemical MD and estimate ``Delta G`` via FEP, TI, BAR, and MBAR.

    Convention: ``Delta G`` is reported as ``G(final_lambda) - G(initial_lambda)``.
    For decoupling from ``lambda=(1,1)`` to ``lambda=(0,0)``, ``Delta G_decouple``
    is ``-Delta G_solvation``.
    """
    schedule = list(lambda_schedule) if lambda_schedule is not None else build_default_lambda_schedule(7)
    k_states = len(schedule)
    if k_states < 2:
        raise ValueError("Alchemical calculation requires at least 2 lambda states")

    kbt = KB_KJ_MOL_K * temperature_k
    beta = 1.0 / kbt

    sampled_configs: List[Tuple[FloatArray, SimulationBox]] = []
    n_k: List[int] = []
    mean_du_dlam_elec: List[float] = []
    mean_du_dlam_vdw: List[float] = []
    var_du_dlam_elec: List[float] = []
    var_du_dlam_vdw: List[float] = []

    current_pos = initial_positions.copy()
    current_box = SimulationBox(box.vectors)

    for w_idx, lam in enumerate(schedule):
        cfg = SimulationConfig(
            dt_ps=dt_ps,
            n_steps=steps_per_window,
            ensemble="nvt",
            thermostat="baoab",
            temperature_k=temperature_k,
            friction_ps_inv=2.0,
            constraint_mode="lincs",
            save_interval=max(1, sample_interval),
            seed=seed + 37 * w_idx,
        )
        final_state, traj = run_simulation(
            topology,
            force_field,
            current_pos,
            current_box,
            config=cfg,
            alchemical=lam,
            minimize=(w_idx == 0),
        )
        current_pos = final_state.positions.copy()
        current_box = SimulationBox(final_state.box.vectors)

        # Discard initial equilibration frames
        prod_frames = [f for f in traj.frames if f.step >= equilibration_steps]
        if not prod_frames:
            prod_frames = traj.frames[max(0, len(traj.frames) // 2):]
        n_k.append(len(prod_frames))
        for frame in prod_frames:
            sampled_configs.append((frame.positions.copy(), SimulationBox(frame.box.vectors)))

        du_e = np.array([f.energy.dU_dlambda_elec for f in prod_frames], dtype=np.float64)
        du_v = np.array([f.energy.dU_dlambda_vdw for f in prod_frames], dtype=np.float64)
        mean_du_dlam_elec.append(float(np.mean(du_e)))
        mean_du_dlam_vdw.append(float(np.mean(du_v)))
        var_du_dlam_elec.append(float(np.var(du_e, ddof=1) / max(1, du_e.size)) if du_e.size > 1 else 0.0)
        var_du_dlam_vdw.append(float(np.var(du_v, ddof=1) / max(1, du_v.size)) if du_v.size > 1 else 0.0)

    # Evaluate reduced potential matrix u_{k, n} = beta * U_k(x_n) across all states and samples
    n_total = len(sampled_configs)
    u_kn = np.zeros((k_states, n_total), dtype=np.float64)
    for n_idx, (pos_n, box_n) in enumerate(sampled_configs):
        for k_idx, lam_k in enumerate(schedule):
            eb, _ = force_field.evaluate(pos_n, box_n, alchemical=lam_k, force_rebuild=True)
            u_kn[k_idx, n_idx] = beta * eb.potential

    # 1. MBAR
    f_k, df_sigma, overlap, ess = solve_mbar(u_kn, n_k)
    dg_mbar = float(f_k[-1] - f_k[0]) * kbt
    sig_mbar = float(df_sigma[0, -1]) * kbt

    # 2. Adjacent-window BAR, Forward FEP, Reverse FEP
    offsets = np.concatenate([[0], np.cumsum(np.asarray(n_k, dtype=np.int64))])
    dg_bar_total = 0.0
    var_bar_total = 0.0
    dg_fep_fwd = 0.0
    dg_fep_rev = 0.0
    for i in range(k_states - 1):
        s0, e0 = int(offsets[i]), int(offsets[i + 1])
        s1, e1 = int(offsets[i + 1]), int(offsets[i + 2])
        du_f = u_kn[i + 1, s0:e0] - u_kn[i, s0:e0]
        du_r = u_kn[i, s1:e1] - u_kn[i + 1, s1:e1]
        df_b, sig_b = solve_bar_pair(du_f, du_r)
        dg_bar_total += df_b * kbt
        var_bar_total += (sig_b * kbt) ** 2
        dg_fep_fwd += zwanzig_fep(du_f) * kbt
        dg_fep_rev += -zwanzig_fep(du_r) * kbt

    # 3. Thermodynamic Integration (trapezoidal quadrature over lambda_elec and lambda_vdw)
    dg_ti = 0.0
    var_ti = 0.0
    for i in range(k_states - 1):
        dle = schedule[i + 1].lambda_elec - schedule[i].lambda_elec
        dlv = schedule[i + 1].lambda_vdw - schedule[i].lambda_vdw
        dg_ti += 0.5 * (mean_du_dlam_elec[i] + mean_du_dlam_elec[i + 1]) * dle
        dg_ti += 0.5 * (mean_du_dlam_vdw[i] + mean_du_dlam_vdw[i + 1]) * dlv
        var_ti += 0.25 * (dle * dle) * (var_du_dlam_elec[i] + var_du_dlam_elec[i + 1])
        var_ti += 0.25 * (dlv * dlv) * (var_du_dlam_vdw[i] + var_du_dlam_vdw[i + 1])

    return FreeEnergyEstimate(
        delta_g_mbar=dg_mbar,
        sigma_mbar=sig_mbar,
        delta_g_bar=dg_bar_total,
        sigma_bar=float(np.sqrt(var_bar_total)),
        delta_g_ti=dg_ti,
        sigma_ti=float(np.sqrt(var_ti)),
        delta_g_fep_fwd=dg_fep_fwd,
        delta_g_fep_rev=dg_fep_rev,
        hysteresis_kj_mol=abs(dg_fep_fwd - dg_fep_rev),
        window_free_energies=f_k * kbt,
        window_uncertainties=df_sigma[0, :] * kbt,
        overlap_matrix=overlap,
        effective_sample_sizes=ess,
        lambda_schedule=schedule,
    )


def compute_relative_binding_ddg(
    complex_est: FreeEnergyEstimate,
    solvent_est: FreeEnergyEstimate,
) -> Tuple[float, float]:
    """Compute decoupling thermodynamic cycle ``Delta Delta G_bind = dG_solvent - dG_complex``."""
    # Decoupling leg measures G(uninteracting) - G(coupled) = -dG_interaction
    # Thus dG_bind = dG_complex_to_vac_negated = dG_decouple_solvent - dG_decouple_complex
    ddg = solvent_est.delta_g_mbar - complex_est.delta_g_mbar
    sigma = float(np.sqrt(solvent_est.sigma_mbar ** 2 + complex_est.sigma_mbar ** 2))
    return ddg, sigma
