"""Particle-Mesh Ewald (PME / P3M) spectral electrostatics and Exact Ewald reference.

Implements smooth Cardinal B-spline charge interpolation onto a 3D reciprocal
FFT grid, analytical B-spline modulus influence function, reciprocal-space forces
and virial tensor, real-space damped Coulomb with 1-2/1-3/1-4 exclusion
corrections, self-energy, and neutralizing background correction.
"""

from __future__ import annotations

from typing import List, Optional, Tuple
import numpy as np
from scipy.special import erfc, erf

from chemi_verlet.pbc import minimum_image_displacement
from chemi_verlet.types import (
    COULOMB_CONST_KJ_MOL_NM_E2,
    FloatArray,
    IntArray,
    SimulationBox,
    Topology,
)


def optimal_ewald_alpha(cutoff: float, tolerance: float = 1e-5) -> float:
    """Compute Ewald splitting parameter alpha (1/nm) from cutoff and error tolerance."""
    if cutoff <= 0.0:
        raise ValueError("Ewald cutoff must be strictly positive")
    if not (0.0 < tolerance < 1.0):
        raise ValueError("Ewald tolerance must lie in (0, 1)")
    # Solve erfc(alpha * r_c) = tolerance via binary search
    lo, hi = 0.05 / cutoff, 10.0 / cutoff
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if float(erfc(mid * cutoff)) > tolerance:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def bspline_values_and_derivatives(w: FloatArray, order: int = 4) -> Tuple[FloatArray, FloatArray]:
    """Evaluate Cardinal B-spline weights M_p(w + k) and derivatives M_p'(w + k).

    Parameters
    ----------
    w:
        Fractional grid remainder in ``[0, 1)`` of shape ``(N, 3)``.
    order:
        B-spline interpolation order ``p >= 3`` (default 4, cubic).

    Returns
    -------
    tuple
        ``(M, dM)`` each of shape ``(N, 3, order)`` where axis 2 indexes ``k = 0..order-1``.
    """
    if order < 3:
        raise ValueError("B-spline order must be >= 3")
    n_atoms = w.shape[0]
    m_cur = np.zeros((n_atoms, 3, order), dtype=np.float64)
    # Order 2 base: M_2(x) = x on [0,1), 2-x on [1,2) -> at k=0: w, at k=1: 1-w
    m_cur[:, :, 0] = w
    m_cur[:, :, 1] = 1.0 - w

    dm_cur = np.zeros_like(m_cur)
    for n in range(3, order + 1):
        m_prev = m_cur.copy()
        if n == order:
            # Derivative M_n'(u) = M_{n-1}(u) - M_{n-1}(u - 1)
            dm_cur[:, :, 0] = m_prev[:, :, 0]
            for k in range(1, order):
                dm_cur[:, :, k] = m_prev[:, :, k] - m_prev[:, :, k - 1]
        m_next = np.zeros_like(m_cur)
        inv_nm1 = 1.0 / (n - 1)
        for k in range(n):
            val = np.zeros((n_atoms, 3), dtype=np.float64)
            if k < n - 1:
                val += (w + k) * m_prev[:, :, k]
            if k >= 1:
                val += (n - (w + k)) * m_prev[:, :, k - 1]
            m_next[:, :, k] = val * inv_nm1
        m_cur = m_next

    return m_cur, dm_cur


def _bspline_euler_modulus_sq(grid_size: int, order: int) -> FloatArray:
    """Compute ``|b(m)|^2`` Euler exponential spline correction for 1D FFT frequencies."""
    # Evaluate M_order(k + 1) at integer nodes k = 0..order-2
    zero_w = np.zeros((1, 3), dtype=np.float64)
    m_vals, _ = bspline_values_and_derivatives(zero_w, order=order)
    # At w=0, x = k in 0..order-1; M_p(k) is non-zero for k = 1..order-1
    weights = m_vals[0, 0, 1:order]  # M_p(1), ..., M_p(p-1)
    freqs = np.fft.fftfreq(grid_size) * grid_size  # integer frequencies m
    denom = np.zeros(grid_size, dtype=np.complex128)
    for k in range(order - 1):
        denom += weights[k] * np.exp(2j * np.pi * freqs * k / grid_size)
    denom_sq = np.abs(denom) ** 2
    # Odd-order B-splines on even grids vanish identically at Nyquist (m = K/2); zero that mode safely
    mod_sq = np.where(denom_sq > 1e-8, 1.0 / np.maximum(denom_sq, 1e-8), 0.0)
    return mod_sq.astype(np.float64)


class ParticleMeshEwald:
    """Smooth Particle-Mesh Ewald (PME) electrostatic solver using 3D NumPy FFT."""

    def __init__(
        self,
        cutoff: float = 0.9,
        alpha: Optional[float] = None,
        grid_spacing: float = 0.12,
        spline_order: int = 4,
        tolerance: float = 1e-5,
    ) -> None:
        self.cutoff = float(cutoff)
        self.alpha = float(alpha) if alpha is not None else optimal_ewald_alpha(cutoff, tolerance)
        self.grid_spacing = float(grid_spacing)
        self.spline_order = int(spline_order)
        if self.spline_order < 3:
            raise ValueError("PME spline_order must be >= 3")

    def choose_grid_dimensions(self, box: SimulationBox) -> Tuple[int, int, int]:
        """Choose smooth FFT-friendly grid dimensions (>= 8) from box lengths."""
        lengths = box.lengths()
        dims: List[int] = []
        for length in lengths:
            raw = max(8, int(np.ceil(length / self.grid_spacing)))
            # Round up to next even number >= max(8, spline_order + 2)
            raw = max(raw, self.spline_order + 2)
            if raw % 2 == 1:
                raw += 1
            dims.append(raw)
        return (dims[0], dims[1], dims[2])

    def compute_reciprocal(
        self,
        positions: FloatArray,
        charges: FloatArray,
        box: SimulationBox,
        grid_dims: Optional[Tuple[int, int, int]] = None,
    ) -> Tuple[float, FloatArray, FloatArray]:
        """Compute PME reciprocal-space energy, forces, and virial tensor.

        Returns
        -------
        tuple
            ``(u_recip, forces_recip, virial_recip)`` where energy is in kJ/mol,
            forces in kJ/(mol*nm), and virial in kJ/mol.
        """
        n_atoms = positions.shape[0]
        if n_atoms == 0 or np.all(np.abs(charges) < 1e-15):
            return 0.0, np.zeros_like(positions), np.zeros((3, 3), dtype=np.float64)

        kx, ky, kz = grid_dims or self.choose_grid_dimensions(box)
        k_vec = np.array([kx, ky, kz], dtype=np.float64)

        # Fractional scaled coordinates u = K * (H^{-1} r mod 1)
        frac = (positions @ box.inv_vectors.T) % 1.0
        u = frac * k_vec[None, :]
        n_floor = np.floor(u).astype(np.int64)
        w = u - n_floor

        m_weights, dm_weights = bspline_values_and_derivatives(w, order=self.spline_order)
        p = self.spline_order

        # Precompute grid indices per atom and dimension: shape (N, 3, p)
        idx_grid = np.empty((n_atoms, 3, p), dtype=np.int64)
        for k_off in range(p):
            idx_grid[:, 0, k_off] = (n_floor[:, 0] - k_off) % kx
            idx_grid[:, 1, k_off] = (n_floor[:, 1] - k_off) % ky
            idx_grid[:, 2, k_off] = (n_floor[:, 2] - k_off) % kz

        # Charge spreading onto 3D mesh Q(kx, ky, kz)
        q_grid = np.zeros((kx, ky, kz), dtype=np.float64)
        for a in range(p):
            wa = charges * m_weights[:, 0, a]
            ia = idx_grid[:, 0, a]
            for b in range(p):
                wab = wa * m_weights[:, 1, b]
                ib = idx_grid[:, 1, b]
                for c in range(p):
                    wabc = wab * m_weights[:, 2, c]
                    ic = idx_grid[:, 2, c]
                    np.add.at(q_grid, (ia, ib, ic), wabc)

        q_hat = np.fft.fftn(q_grid)

        # Reciprocal lattice vectors m' = H^{-T} m (physical k = 2*pi * m')
        mx = np.fft.fftfreq(kx) * kx
        my = np.fft.fftfreq(ky) * ky
        mz = np.fft.fftfreq(kz) * kz
        gx, gy, gz = np.meshgrid(mx, my, mz, indexing="ij")
        # Physical reciprocal wavevector components m' = H^{-T} m
        inv_h = box.inv_vectors
        mpx = gx * inv_h[0, 0] + gy * inv_h[1, 0] + gz * inv_h[2, 0]
        mpy = gx * inv_h[0, 1] + gy * inv_h[1, 1] + gz * inv_h[2, 1]
        mpz = gx * inv_h[0, 2] + gy * inv_h[1, 2] + gz * inv_h[2, 2]
        mp_sq = mpx * mpx + mpy * mpy + mpz * mpz

        bx_sq = _bspline_euler_modulus_sq(kx, p)
        by_sq = _bspline_euler_modulus_sq(ky, p)
        bz_sq = _bspline_euler_modulus_sq(kz, p)
        b_mod = bx_sq[:, None, None] * by_sq[None, :, None] * bz_sq[None, None, :]

        alpha_sq = self.alpha * self.alpha
        pref = COULOMB_CONST_KJ_MOL_NM_E2 * float(kx * ky * kz) / (np.pi * box.volume)
        nz_mask = mp_sq > 1e-18
        c_grid = np.zeros_like(mp_sq)
        exp_term = np.zeros_like(mp_sq)
        exp_term[nz_mask] = np.exp(-np.pi * np.pi * mp_sq[nz_mask] / alpha_sq)
        c_grid[nz_mask] = pref * (exp_term[nz_mask] / mp_sq[nz_mask]) * b_mod[nz_mask]

        phi_grid = np.real(np.fft.ifftn(c_grid * q_hat))
        u_recip = 0.5 * float(np.sum(q_grid * phi_grid))

        # Reciprocal virial tensor Xi_ab = sum_{k!=0} u_k [d_ab - 2*(1+pi^2 m'^2/a^2)*m'_a m'_b / m'^2]
        q_abs_sq = np.real(q_hat * np.conj(q_hat))
        u_k = 0.5 * (c_grid / float(kx * ky * kz)) * q_abs_sq
        factor_k = np.zeros_like(mp_sq)
        factor_k[nz_mask] = 2.0 * (1.0 + (np.pi * np.pi * mp_sq[nz_mask]) / alpha_sq) / mp_sq[nz_mask]

        mp_comps = (mpx, mpy, mpz)
        virial = np.zeros((3, 3), dtype=np.float64)
        u_rec_sum = float(np.sum(u_k))
        for alpha_i in range(3):
            for beta_j in range(3):
                val = (u_rec_sum if alpha_i == beta_j else 0.0) - float(
                    np.sum(u_k * factor_k * mp_comps[alpha_i] * mp_comps[beta_j])
                )
                virial[alpha_i, beta_j] = val

        # Interpolate gradient dU/du_alpha back to atoms
        grad_u = np.zeros((n_atoms, 3), dtype=np.float64)
        for a in range(p):
            ia = idx_grid[:, 0, a]
            ma = m_weights[:, 0, a]
            dma = dm_weights[:, 0, a]
            for b in range(p):
                ib = idx_grid[:, 1, b]
                mb = m_weights[:, 1, b]
                dmb = dm_weights[:, 1, b]
                for c in range(p):
                    ic = idx_grid[:, 2, c]
                    mc = m_weights[:, 2, c]
                    dmc = dm_weights[:, 2, c]
                    phi_val = phi_grid[ia, ib, ic]
                    grad_u[:, 0] += phi_val * dma * mb * mc
                    grad_u[:, 1] += phi_val * ma * dmb * mc
                    grad_u[:, 2] += phi_val * ma * mb * dmc

        grad_u *= charges[:, None] * k_vec[None, :]
        # F = -dU/dr = - (grad_u @ H^{-1})
        forces_recip = -(grad_u @ box.inv_vectors)
        return u_recip, forces_recip, virial

    def compute_self_and_background(self, charges: FloatArray, box: SimulationBox) -> float:
        """Return Ewald self-energy plus neutralizing background correction (kJ/mol)."""
        q_sq_sum = float(np.sum(charges * charges))
        q_net = float(np.sum(charges))
        u_self = -COULOMB_CONST_KJ_MOL_NM_E2 * (self.alpha / np.sqrt(np.pi)) * q_sq_sum
        u_bg = -COULOMB_CONST_KJ_MOL_NM_E2 * (np.pi / (2.0 * box.volume * self.alpha * self.alpha)) * (q_net * q_net)
        return float(u_self + u_bg)

    def compute_real_and_exclusions(
        self,
        positions: FloatArray,
        charges: FloatArray,
        box: SimulationBox,
        pair_i: IntArray,
        pair_j: IntArray,
        dr_ij: FloatArray,
        dist_ij: FloatArray,
        topology: Topology,
        lambda_elec: float = 1.0,
    ) -> Tuple[float, FloatArray, FloatArray, float]:
        """Compute PME real-space erfc energy/forces + 1-2/1-3/1-4 bonded erf corrections.

        Returns ``(u_real, forces, virial, dU_dlambda_elec)``.
        """
        forces = np.zeros_like(positions)
        virial = np.zeros((3, 3), dtype=np.float64)
        u_real = 0.0
        du_dlam = 0.0

        eff_charges = charges.copy()
        if lambda_elec < 1.0:
            eff_charges = np.where(topology.alchemical_mask, charges * lambda_elec, charges)

        # 1. Real-space active nonbonded pairs: f * q_i * q_j * erfc(alpha * r) / r
        if pair_i.size > 0:
            qi = eff_charges[pair_i]
            qj = eff_charges[pair_j]
            qq = qi * qj
            nz = np.abs(qq) > 1e-16
            if np.any(nz):
                r = dist_ij[nz]
                dr = dr_ij[nz]
                qq_nz = qq[nz]
                ar = self.alpha * r
                erfc_ar = erfc(ar)
                gauss = (2.0 * self.alpha / np.sqrt(np.pi)) * np.exp(-ar * ar)
                inv_r = 1.0 / r
                inv_r2 = inv_r * inv_r

                u_pairs = COULOMB_CONST_KJ_MOL_NM_E2 * qq_nz * erfc_ar * inv_r
                u_real += float(np.sum(u_pairs))

                # F_j = -dU/dr_j = +f*qq*(erfc(ar)/r + gauss) * (dr/r^2) ... wait:
                # dr = r_j - r_i; dU/dr_j = dU/dr * (dr/r) = -f*qq*(erfc(ar)/r^2 + gauss/r) * (dr/r)
                # So force on j is -dU/dr_j = +f*qq*(erfc(ar)/r + gauss)*inv_r2 * dr
                # Force on i is -F_j!
                scalar = COULOMB_CONST_KJ_MOL_NM_E2 * qq_nz * (erfc_ar * inv_r + gauss) * inv_r2
                f_ij = dr * scalar[:, None]
                pi_nz = pair_i[nz]
                pj_nz = pair_j[nz]
                np.add.at(forces, pi_nz, -f_ij)
                np.add.at(forces, pj_nz, f_ij)
                virial += dr.T @ f_ij

                if np.any(topology.alchemical_mask):
                    # d(q_i(lam) q_j(lam)) / dlam
                    alch_i = topology.alchemical_mask[pi_nz]
                    alch_j = topology.alchemical_mask[pj_nz]
                    dqq = np.zeros_like(qq_nz)
                    c_i = charges[pi_nz]
                    c_j = charges[pj_nz]
                    both = alch_i & alch_j
                    only_i = alch_i & ~alch_j
                    only_j = ~alch_i & alch_j
                    dqq[both] = 2.0 * lambda_elec * c_i[both] * c_j[both]
                    dqq[only_i] = c_i[only_i] * c_j[only_i]
                    dqq[only_j] = c_i[only_j] * c_j[only_j]
                    du_dlam += float(np.sum(COULOMB_CONST_KJ_MOL_NM_E2 * dqq * erfc_ar * inv_r))

        # 2. Subtract reciprocal erf(alpha*r)/r over 1-2 & 1-3 exclusions (and (1-fudge_qq) for 1-4)
        seen_excl: set[Tuple[int, int]] = set()
        excl_pairs: List[Tuple[int, int, float]] = []
        for a, excl_set in topology.exclusions.items():
            for b in excl_set:
                if a < b and (a, b) not in seen_excl:
                    seen_excl.add((a, b))
                    excl_pairs.append((a, b, 1.0))
        for a, b in topology.pairs_14:
            pair = (min(a, b), max(a, b))
            if pair not in seen_excl:
                seen_excl.add(pair)
                # Full 1-4 Coulomb scales by fudge_qq; subtract (1 - fudge_qq)/r since real+recip sum to 1/r
                excl_pairs.append((pair[0], pair[1], 1.0 - topology.fudge_qq))

        if excl_pairs:
            pa = np.array([p[0] for p in excl_pairs], dtype=np.int64)
            pb = np.array([p[1] for p in excl_pairs], dtype=np.int64)
            w_sub = np.array([p[2] for p in excl_pairs], dtype=np.float64)
            qq_ex = eff_charges[pa] * eff_charges[pb] * w_sub
            nz_ex = np.abs(qq_ex) > 1e-16
            if np.any(nz_ex):
                pa_nz = pa[nz_ex]
                pb_nz = pb[nz_ex]
                qq_nz = qq_ex[nz_ex]
                dr_ex = minimum_image_displacement(positions[pb_nz] - positions[pa_nz], box)
                r_ex = np.maximum(np.linalg.norm(dr_ex, axis=1), 1e-9)
                ar_ex = self.alpha * r_ex
                # For 1-2/1-3: subtract erf(ar)/r; for 1-4: we had erfc(ar)/r in real + erf(ar)/r in recip = 1/r,
                # so subtracting (1 - fudge_qq)/r leaves fudge_qq/r!
                is_14 = w_sub[nz_ex] < 0.999
                val_factor = np.where(is_14, 1.0 / r_ex, erf(ar_ex) / r_ex)
                dval_dr_over_r = np.where(
                    is_14,
                    -1.0 / (r_ex * r_ex * r_ex),
                    ((2.0 * self.alpha / np.sqrt(np.pi)) * np.exp(-ar_ex * ar_ex) * r_ex - erf(ar_ex))
                    / (r_ex * r_ex * r_ex),
                )
                u_real -= float(np.sum(COULOMB_CONST_KJ_MOL_NM_E2 * qq_nz * val_factor))
                # U_corr = -f*qq*val(r) -> F_b = -dU_corr/dr_b = +f*qq*(dval/dr / r)*dr
                f_ex = dr_ex * (COULOMB_CONST_KJ_MOL_NM_E2 * qq_nz * dval_dr_over_r)[:, None]
                np.add.at(forces, pa_nz, -f_ex)
                np.add.at(forces, pb_nz, f_ex)
                virial += dr_ex.T @ f_ex

                if np.any(topology.alchemical_mask):
                    alch_a = topology.alchemical_mask[pa_nz]
                    alch_b = topology.alchemical_mask[pb_nz]
                    dqq_ex = np.zeros_like(qq_nz)
                    ca = charges[pa_nz]
                    cb = charges[pb_nz]
                    ws = w_sub[nz_ex]
                    both = alch_a & alch_b
                    only_a = alch_a & ~alch_b
                    only_b = ~alch_a & alch_b
                    dqq_ex[both] = 2.0 * lambda_elec * ca[both] * cb[both] * ws[both]
                    dqq_ex[only_a] = ca[only_a] * cb[only_a] * ws[only_a]
                    dqq_ex[only_b] = ca[only_b] * cb[only_b] * ws[only_b]
                    du_dlam -= float(np.sum(COULOMB_CONST_KJ_MOL_NM_E2 * dqq_ex * val_factor))

        return u_real, forces, virial, du_dlam


def exact_ewald_energy_forces(
    positions: FloatArray,
    charges: FloatArray,
    box: SimulationBox,
    alpha: float,
    cutoff: float,
    k_max: int = 7,
) -> Tuple[float, FloatArray]:
    """Direct O(N * N_k) Exact Ewald summation (no exclusions) for PME verification.

    Computes exact real-space + exact k-space lattice sum + self/background energy
    on a pure point-charge periodic system.
    """
    n = positions.shape[0]
    forces = np.zeros_like(positions)

    # Real-space all pairs within cutoff
    u_real = 0.0
    for i in range(n):
        for j in range(i + 1, n):
            dr = minimum_image_displacement(positions[j] - positions[i], box)
            r = float(np.linalg.norm(dr))
            if r <= cutoff and r > 1e-12:
                ar = alpha * r
                e_val = float(erfc(ar))
                g_val = (2.0 * alpha / np.sqrt(np.pi)) * float(np.exp(-ar * ar))
                qq = float(charges[i] * charges[j])
                u_real += COULOMB_CONST_KJ_MOL_NM_E2 * qq * e_val / r
                f_ij = COULOMB_CONST_KJ_MOL_NM_E2 * qq * (e_val / r + g_val) / (r * r) * dr
                forces[i] -= f_ij
                forces[j] += f_ij

    # Exact reciprocal lattice sum over integer vectors m in [-k_max, k_max]^3 \ {0}
    inv_h = box.inv_vectors
    rng = np.arange(-k_max, k_max + 1, dtype=np.float64)
    mx, my, mz = np.meshgrid(rng, rng, rng, indexing="ij")
    m_all = np.column_stack([mx.ravel(), my.ravel(), mz.ravel()])
    nz = np.any(m_all != 0.0, axis=1)
    m_all = m_all[nz]
    # k = 2*pi * m @ inv_h
    k_vecs = 2.0 * np.pi * (m_all @ inv_h)
    k_sq = np.sum(k_vecs * k_vecs, axis=1)

    pref_k = (2.0 * np.pi / box.volume) * COULOMB_CONST_KJ_MOL_NM_E2
    weights = pref_k * np.exp(-k_sq / (4.0 * alpha * alpha)) / k_sq

    phases = positions @ k_vecs.T  # (N, M_k)
    cos_p = np.cos(phases)
    sin_p = np.sin(phases)
    re_s = charges @ cos_p
    im_s = charges @ sin_p
    s_sq = re_s * re_s + im_s * im_s
    u_recip = float(np.sum(weights * s_sq))

    # dU/dr_i = sum_k 2 * weights_k * q_i * ( -re_s_k * sin(k.r_i) + im_s_k * cos(k.r_i) ) * k
    # So F_i = -dU/dr_i = 2 * q_i * sum_k weights_k * (re_s_k * sin_p - im_s_k * cos_p) * k
    coeff = 2.0 * weights[None, :] * (re_s[None, :] * sin_p - im_s[None, :] * cos_p)
    forces += charges[:, None] * (coeff @ k_vecs)

    q_sq = float(np.sum(charges * charges))
    q_net = float(np.sum(charges))
    u_self = -COULOMB_CONST_KJ_MOL_NM_E2 * (alpha / np.sqrt(np.pi)) * q_sq
    u_bg = -COULOMB_CONST_KJ_MOL_NM_E2 * (np.pi / (2.0 * box.volume * alpha * alpha)) * (q_net * q_net)
    return u_real + u_recip + u_self + u_bg, forces
