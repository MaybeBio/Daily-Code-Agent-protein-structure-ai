"""Molecular mechanics force field: bonded terms, soft-core LJ, electrostatics, and virials.

Computes potential energy decompositions, exact analytical atomic forces
``F_i = -grad_{r_i} U``, molecular/atomic virial tensors, long-range isotropic
dispersion tail corrections, and analytical alchemical derivatives
``dU/dlambda_vdw`` and ``dU/dlambda_elec``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple
import numpy as np

from chemi_verlet.ewald import ParticleMeshEwald
from chemi_verlet.pbc import CellListNeighborFinder, minimum_image_displacement
from chemi_verlet.types import (
    AlchemicalLambda,
    COULOMB_CONST_KJ_MOL_NM_E2,
    EnergyBreakdown,
    FloatArray,
    IntArray,
    SimulationBox,
    Topology,
)


@dataclass(frozen=True)
class ForceFieldConfig:
    """Configuration for nonbonded cutoffs, electrostatics, and switching functions."""

    cutoff: float = 0.9
    switch_distance: Optional[float] = 0.75
    skin: float = 0.15
    electrostatics: str = "pme"  # "pme", "reaction_field", or "cutoff"
    epsilon_rf: float = 78.5
    pme_grid_spacing: float = 0.12
    pme_spline_order: int = 4
    pme_tolerance: float = 1e-5
    dispersion_correction: bool = True
    shift_lj: bool = True

    def __post_init__(self) -> None:
        if self.cutoff <= 0.0:
            raise ValueError("Force-field cutoff must be positive")
        if self.switch_distance is not None and not (0.0 < self.switch_distance < self.cutoff):
            raise ValueError("switch_distance must satisfy 0 < r_switch < r_cutoff")
        if self.electrostatics not in ("pme", "reaction_field", "cutoff"):
            raise ValueError(f"Unsupported electrostatics mode: {self.electrostatics}")


@dataclass(frozen=True)
class HarmonicCOMRestraint:
    """Harmonic bias potential on distance between two atom-group centers of mass."""

    group_a: Tuple[int, ...]
    group_b: Tuple[int, ...]
    r0: float
    k_restraint: float


class ForceField:
    """Vectorized atomistic force-field evaluator with analytical forces and virial."""

    def __init__(self, topology: Topology, config: Optional[ForceFieldConfig] = None) -> None:
        self.topology = topology
        self.config = config or ForceFieldConfig()
        self.neighbor_finder = CellListNeighborFinder(
            cutoff=self.config.cutoff,
            skin=self.config.skin,
            exclusions=topology.exclusions,
        )
        self.pme: Optional[ParticleMeshEwald] = None
        if self.config.electrostatics == "pme":
            self.pme = ParticleMeshEwald(
                cutoff=self.config.cutoff,
                grid_spacing=self.config.pme_grid_spacing,
                spline_order=self.config.pme_spline_order,
                tolerance=self.config.pme_tolerance,
            )
        self._restraints: List[HarmonicCOMRestraint] = []

        # Precompute 1-4 pair index arrays and Lorentz-Berthelot combined parameters
        self._p14_i = np.array([p[0] for p in topology.pairs_14], dtype=np.int64)
        self._p14_j = np.array([p[1] for p in topology.pairs_14], dtype=np.int64)
        self._c6_tail_sum = self._compute_c6_tail_sum()

    def add_com_restraint(self, restraint: HarmonicCOMRestraint) -> None:
        """Attach a harmonic center-of-mass distance restraint (used by umbrella sampling)."""
        self._restraints.append(restraint)

    def clear_restraints(self) -> None:
        """Remove all attached center-of-mass restraints."""
        self._restraints.clear()

    def _compute_c6_tail_sum(self) -> float:
        """Precompute sum_{i,j} 4*epsilon_ij*sigma_ij^6 for analytical dispersion tail."""
        sigs = self.topology.sigmas
        epss = self.topology.epsilons
        # Mean-field approximation sum_i sum_j C6_ij via Lorentz-Berthelot
        n = len(sigs)
        if n < 2:
            return 0.0
        sig_ij = 0.5 * (sigs[:, None] + sigs[None, :])
        eps_ij = np.sqrt(epss[:, None] * epss[None, :])
        c6 = 4.0 * eps_ij * (sig_ij ** 6)
        np.fill_diagonal(c6, 0.0)
        return float(0.5 * np.sum(c6))

    def evaluate(
        self,
        positions: FloatArray,
        box: SimulationBox,
        alchemical: Optional[AlchemicalLambda] = None,
        force_rebuild: bool = False,
    ) -> Tuple[EnergyBreakdown, FloatArray]:
        """Compute full potential energy decomposition, forces, and virial tensor."""
        n = self.topology.n_atoms
        forces = np.zeros((n, 3), dtype=np.float64)
        virial = np.zeros((3, 3), dtype=np.float64)
        energy = EnergyBreakdown()
        lam = alchemical or AlchemicalLambda()

        # 1. Bonded terms
        u_b, f_b, v_b = self._eval_bonds(positions, box)
        energy.bond = u_b
        forces += f_b
        virial += v_b

        u_a, f_a, v_a = self._eval_angles(positions, box)
        energy.angle = u_a
        forces += f_a
        virial += v_a

        u_d, f_d, v_d = self._eval_dihedrals(positions, box)
        energy.dihedral = u_d
        forces += f_d
        virial += v_d

        u_imp, f_imp, v_imp = self._eval_impropers(positions, box)
        energy.improper = u_imp
        forces += f_imp
        virial += v_imp

        # 2. Nonbonded neighbor pairs
        pair_i, pair_j, dr_ij, dist_ij = self.neighbor_finder.get_pairs(
            positions, box, force_rebuild=force_rebuild
        )

        # Lennard-Jones (with optional Beutler soft-core alchemical coupling)
        u_lj, f_lj, v_lj, du_vdw = self._eval_lennard_jones(
            pair_i, pair_j, dr_ij, dist_ij, lam
        )
        energy.lj = u_lj
        energy.dU_dlambda_vdw = du_vdw
        forces += f_lj
        virial += v_lj

        # 1-4 Lennard-Jones scaled by fudge_lj
        if self._p14_i.size > 0:
            dr_14 = minimum_image_displacement(positions[self._p14_j] - positions[self._p14_i], box)
            dist_14 = np.linalg.norm(dr_14, axis=1)
            u_lj14, f_lj14, v_lj14, du_vdw14 = self._eval_lennard_jones(
                self._p14_i,
                self._p14_j,
                dr_14,
                dist_14,
                lam,
                scale=self.topology.fudge_lj,
            )
            energy.lj += u_lj14
            energy.dU_dlambda_vdw += du_vdw14
            forces += f_lj14
            virial += v_lj14

        # Isotropic dispersion tail correction
        if self.config.dispersion_correction and self._c6_tail_sum > 0.0:
            rc = self.config.cutoff
            tail_pref = -2.0 * np.pi / (3.0 * box.volume * (rc ** 3))
            u_tail_base = tail_pref * self._c6_tail_sum
            u_tail = u_tail_base
            if np.any(self.topology.alchemical_mask):
                alch_frac = float(np.mean(self.topology.alchemical_mask))
                scale_eff = (1.0 - alch_frac) + alch_frac * lam.lambda_vdw
                u_tail = u_tail_base * scale_eff
                energy.dU_dlambda_vdw += u_tail_base * alch_frac
            energy.lj_tail = u_tail
            # Virial correction: dU/dV = -U_tail/V -> Xi_ab += -U_tail * delta_ab
            virial += np.eye(3, dtype=np.float64) * (-u_tail)

        # 3. Electrostatics
        if self.config.electrostatics == "pme" and self.pme is not None:
            eff_charges = np.where(
                self.topology.alchemical_mask,
                self.topology.charges * lam.lambda_elec,
                self.topology.charges,
            )
            u_real, f_real, v_real, du_elec_real = self.pme.compute_real_and_exclusions(
                positions,
                self.topology.charges,
                box,
                pair_i,
                pair_j,
                dr_ij,
                dist_ij,
                self.topology,
                lambda_elec=lam.lambda_elec,
            )
            u_rec, f_rec, v_rec = self.pme.compute_reciprocal(positions, eff_charges, box)
            u_self = self.pme.compute_self_and_background(eff_charges, box)

            du_elec_rec_self = 0.0
            if np.any(self.topology.alchemical_mask) and np.any(np.abs(self.topology.charges) > 1e-14):
                # Exact numerical or analytical derivative of reciprocal + self wrt lambda_elec
                alch_q = np.where(self.topology.alchemical_mask, self.topology.charges, 0.0)
                if np.any(np.abs(alch_q) > 1e-14):
                    eps_l = 1e-5
                    lp = min(1.0, lam.lambda_elec + eps_l)
                    lm = max(0.0, lam.lambda_elec - eps_l)
                    if lp > lm:
                        qp = np.where(self.topology.alchemical_mask, self.topology.charges * lp, self.topology.charges)
                        qm = np.where(self.topology.alchemical_mask, self.topology.charges * lm, self.topology.charges)
                        up, _, _ = self.pme.compute_reciprocal(positions, qp, box)
                        um, _, _ = self.pme.compute_reciprocal(positions, qm, box)
                        up += self.pme.compute_self_and_background(qp, box)
                        um += self.pme.compute_self_and_background(qm, box)
                        du_elec_rec_self = (up - um) / (lp - lm)

            energy.coulomb_real = u_real
            energy.coulomb_recip = u_rec
            energy.coulomb_self = u_self
            energy.dU_dlambda_elec = du_elec_real + du_elec_rec_self
            forces += f_real + f_rec
            virial += v_real + v_rec
        else:
            u_rf, f_rf, v_rf, du_elec = self._eval_reaction_field_or_cutoff(
                positions, box, pair_i, pair_j, dr_ij, dist_ij, lam
            )
            energy.coulomb_real = u_rf
            energy.dU_dlambda_elec = du_elec
            forces += f_rf
            virial += v_rf

        # 4. Harmonic COM restraints
        if self._restraints:
            u_res, f_res, v_res = self._eval_restraints(positions, box)
            energy.restraint = u_res
            forces += f_res
            virial += v_res

        energy.virial_tensor = virial
        return energy, forces

    def _eval_bonds(self, positions: FloatArray, box: SimulationBox) -> Tuple[float, FloatArray, FloatArray]:
        """Evaluate harmonic bond potentials ``0.5 * k_b * (r - r0)^2``."""
        forces = np.zeros_like(positions)
        virial = np.zeros((3, 3), dtype=np.float64)
        bonds = self.topology.bonds
        if not bonds:
            return 0.0, forces, virial
        bi = np.array([b.i for b in bonds], dtype=np.int64)
        bj = np.array([b.j for b in bonds], dtype=np.int64)
        r0 = np.array([b.r0 for b in bonds], dtype=np.float64)
        kb = np.array([b.kb for b in bonds], dtype=np.float64)

        dr = minimum_image_displacement(positions[bj] - positions[bi], box)
        r = np.maximum(np.linalg.norm(dr, axis=1), 1e-12)
        diff = r - r0
        u_bond = float(0.5 * np.sum(kb * diff * diff))

        # U = 0.5*kb*(r - r0)^2 -> F_j = -kb*(r-r0)*(dr/r)
        f_j = dr * (-kb * diff / r)[:, None]
        np.add.at(forces, bi, -f_j)
        np.add.at(forces, bj, f_j)
        virial += dr.T @ f_j
        return u_bond, forces, virial

    def _eval_angles(self, positions: FloatArray, box: SimulationBox) -> Tuple[float, FloatArray, FloatArray]:
        """Evaluate harmonic angle potentials ``0.5 * k_theta * (theta - theta0)^2``."""
        forces = np.zeros_like(positions)
        virial = np.zeros((3, 3), dtype=np.float64)
        angles = self.topology.angles
        if not angles:
            return 0.0, forces, virial

        ai = np.array([a.i for a in angles], dtype=np.int64)
        aj = np.array([a.j for a in angles], dtype=np.int64)
        ak = np.array([a.k for a in angles], dtype=np.int64)
        theta0 = np.array([a.theta0 for a in angles], dtype=np.float64)
        k_th = np.array([a.k_theta for a in angles], dtype=np.float64)

        r_ji = minimum_image_displacement(positions[ai] - positions[aj], box)
        r_jk = minimum_image_displacement(positions[ak] - positions[aj], box)
        d_ji = np.maximum(np.linalg.norm(r_ji, axis=1), 1e-12)
        d_jk = np.maximum(np.linalg.norm(r_jk, axis=1), 1e-12)

        u_ji = r_ji / d_ji[:, None]
        u_jk = r_jk / d_jk[:, None]
        cos_t = np.clip(np.sum(u_ji * u_jk, axis=1), -1.0 + 1e-10, 1.0 - 1e-10)
        theta = np.arccos(cos_t)
        sin_t = np.maximum(np.sqrt(np.maximum(1.0 - cos_t * cos_t, 0.0)), 1e-9)

        dtheta = theta - theta0
        u_ang = float(0.5 * np.sum(k_th * dtheta * dtheta))

        # dU/dtheta = k_th * (theta - theta0); dtheta/dcos = -1/sin_t
        pref = k_th * dtheta / sin_t
        grad_i = pref[:, None] * (u_jk - cos_t[:, None] * u_ji) / d_ji[:, None]
        grad_k = pref[:, None] * (u_ji - cos_t[:, None] * u_jk) / d_jk[:, None]
        # Force = -grad U
        # Since d(cos_t)/d(r_i) = (u_jk - cos_t*u_ji)/d_ji and dU/dr_i = (-pref)*d(cos_t)/dr_i = -grad_i
        # Thus F_i = -dU/dr_i = +grad_i! Let's verify sign:
        # When theta > theta0, dtheta > 0, pref > 0. Moving i toward k increases cos_t (decreases theta),
        # so force F_i should point toward u_jk - cos_t*u_ji (i.e. +grad_i)! Correct!
        f_i = grad_i
        f_k = grad_k
        f_j = -(f_i + f_k)

        np.add.at(forces, ai, f_i)
        np.add.at(forces, aj, f_j)
        np.add.at(forces, ak, f_k)
        virial += r_ji.T @ f_i + r_jk.T @ f_k
        return u_ang, forces, virial

    def _dihedral_geometry_and_forces(
        self,
        r_i: FloatArray,
        r_j: FloatArray,
        r_k: FloatArray,
        r_l: FloatArray,
        box: SimulationBox,
    ) -> Tuple[FloatArray, FloatArray, FloatArray, FloatArray, FloatArray, FloatArray, FloatArray, FloatArray]:
        """Compute dihedral angle phi in [-pi, pi] and Blondel-Karplus gradient vectors."""
        # Standard vector conventions: F_vec = r_i - r_j, G_vec = r_j - r_k, H_vec = r_l - r_k
        f_vec = minimum_image_displacement(r_i - r_j, box)
        g_vec = minimum_image_displacement(r_j - r_k, box)
        h_vec = minimum_image_displacement(r_l - r_k, box)

        a_vec = np.cross(f_vec, g_vec)
        b_vec = np.cross(h_vec, g_vec)
        g_norm = np.maximum(np.linalg.norm(g_vec, axis=1), 1e-12)
        a_sq = np.maximum(np.sum(a_vec * a_vec, axis=1), 1e-12)
        b_sq = np.maximum(np.sum(b_vec * b_vec, axis=1), 1e-12)

        # Sign via (a x b) . g_hat
        cos_phi = np.clip(
            np.sum(a_vec * b_vec, axis=1) / np.sqrt(a_sq * b_sq), -1.0, 1.0
        )
        sin_phi = np.sum(np.cross(b_vec, a_vec) * g_vec, axis=1) / (g_norm * np.sqrt(a_sq * b_sq))
        phi = np.arctan2(sin_phi, cos_phi)

        # Blondel-Karplus (1996) exact gradients dphi/dr_i, dphi/dr_j, dphi/dr_k, dphi/dr_l:
        # dphi/dr_i = -(|G|/A^2) * A
        # dphi/dr_l = +(|G|/B^2) * B
        # dphi/dr_j = (|G|/A^2)*A + (F.G)/(|G|*A^2)*A - (H.G)/(|G|*B^2)*B
        # dphi/dr_k = -(dphi/dr_i + dphi/dr_j + dphi/dr_l)
        fg = np.sum(f_vec * g_vec, axis=1)
        hg = np.sum(h_vec * g_vec, axis=1)

        dphi_di = -(g_norm / a_sq)[:, None] * a_vec
        dphi_dl = (g_norm / b_sq)[:, None] * b_vec
        dphi_dj = (
            ((g_norm + fg / g_norm) / a_sq)[:, None] * a_vec
            - ((hg / g_norm) / b_sq)[:, None] * b_vec
        )
        dphi_dk = -(dphi_di + dphi_dj + dphi_dl)
        return phi, dphi_di, dphi_dj, dphi_dk, dphi_dl, f_vec, g_vec, h_vec

    def _eval_dihedrals(self, positions: FloatArray, box: SimulationBox) -> Tuple[float, FloatArray, FloatArray]:
        """Evaluate proper periodic and Ryckaert-Bellemans torsion potentials."""
        forces = np.zeros_like(positions)
        virial = np.zeros((3, 3), dtype=np.float64)
        total_u = 0.0

        # 1. Proper periodic dihedrals: U = k_phi * (1 + cos(n*phi - delta))
        diheds = self.topology.dihedrals
        if diheds:
            di = np.array([d.i for d in diheds], dtype=np.int64)
            dj = np.array([d.j for d in diheds], dtype=np.int64)
            dk = np.array([d.k for d in diheds], dtype=np.int64)
            dl = np.array([d.l for d in diheds], dtype=np.int64)
            k_phi = np.array([d.k_phi for d in diheds], dtype=np.float64)
            mult = np.array([d.periodicity for d in diheds], dtype=np.float64)
            phase = np.array([d.phase for d in diheds], dtype=np.float64)

            phi, g_i, g_j, g_k, g_l, f_v, g_v, h_v = self._dihedral_geometry_and_forces(
                positions[di], positions[dj], positions[dk], positions[dl], box
            )
            arg = mult * phi - phase
            total_u += float(np.sum(k_phi * (1.0 + np.cos(arg))))
            # dU/dphi = -k_phi * mult * sin(mult*phi - phase), so F = -dU/dr = -(dU/dphi) * dphi/dr
            du_dphi = -k_phi * mult * np.sin(arg)
            fi = -du_dphi[:, None] * g_i
            fj = -du_dphi[:, None] * g_j
            fk = -du_dphi[:, None] * g_k
            fl = -du_dphi[:, None] * g_l
            np.add.at(forces, di, fi)
            np.add.at(forces, dj, fj)
            np.add.at(forces, dk, fk)
            np.add.at(forces, dl, fl)
            # Virial from internal vectors r_i - r_k = f_v + g_v, r_j - r_k = g_v, r_l - r_k = h_v
            virial += (f_v + g_v).T @ fi + g_v.T @ fj + h_v.T @ fl

        # 2. Ryckaert-Bellemans dihedrals: U = sum_{m=0}^5 C_m * cos(phi - pi)^m
        rbs = self.topology.rb_dihedrals
        if rbs:
            ri = np.array([d.i for d in rbs], dtype=np.int64)
            rj = np.array([d.j for d in rbs], dtype=np.int64)
            rk = np.array([d.k for d in rbs], dtype=np.int64)
            rl = np.array([d.l for d in rbs], dtype=np.int64)
            coeffs = np.array([d.coefficients for d in rbs], dtype=np.float64)  # (M, 6)

            phi, g_i, g_j, g_k, g_l, f_v, g_v, h_v = self._dihedral_geometry_and_forces(
                positions[ri], positions[rj], positions[rk], positions[rl], box
            )
            psi = phi - np.pi
            cos_psi = np.cos(psi)
            sin_psi = np.sin(psi)
            u_rb = np.zeros_like(phi)
            du_dcos = np.zeros_like(phi)
            for m in range(6):
                u_rb += coeffs[:, m] * (cos_psi ** m)
                if m > 0:
                    du_dcos += m * coeffs[:, m] * (cos_psi ** (m - 1))
            total_u += float(np.sum(u_rb))
            # dU/dphi = dU/d(cos_psi) * (-sin_psi)
            du_dphi = -du_dcos * sin_psi
            fi = -du_dphi[:, None] * g_i
            fj = -du_dphi[:, None] * g_j
            fk = -du_dphi[:, None] * g_k
            fl = -du_dphi[:, None] * g_l
            np.add.at(forces, ri, fi)
            np.add.at(forces, rj, fj)
            np.add.at(forces, rk, fk)
            np.add.at(forces, rl, fl)
            virial += (f_v + g_v).T @ fi + g_v.T @ fj + h_v.T @ fl

        return total_u, forces, virial

    def _eval_impropers(self, positions: FloatArray, box: SimulationBox) -> Tuple[float, FloatArray, FloatArray]:
        """Evaluate harmonic improper dihedrals ``0.5 * k_omega * (omega - omega0)^2``."""
        forces = np.zeros_like(positions)
        virial = np.zeros((3, 3), dtype=np.float64)
        imps = self.topology.impropers
        if not imps:
            return 0.0, forces, virial

        ii = np.array([d.i for d in imps], dtype=np.int64)
        ij = np.array([d.j for d in imps], dtype=np.int64)
        ik = np.array([d.k for d in imps], dtype=np.int64)
        il = np.array([d.l for d in imps], dtype=np.int64)
        omega0 = np.array([d.omega0 for d in imps], dtype=np.float64)
        k_om = np.array([d.k_omega for d in imps], dtype=np.float64)

        omega, g_i, g_j, g_k, g_l, f_v, g_v, h_v = self._dihedral_geometry_and_forces(
            positions[ii], positions[ij], positions[ik], positions[il], box
        )
        # Wrap periodic difference into [-pi, pi]
        domega = (omega - omega0 + np.pi) % (2.0 * np.pi) - np.pi
        u_imp = float(0.5 * np.sum(k_om * domega * domega))
        du_domega = k_om * domega
        fi = -du_domega[:, None] * g_i
        fj = -du_domega[:, None] * g_j
        fk = -du_domega[:, None] * g_k
        fl = -du_domega[:, None] * g_l
        np.add.at(forces, ii, fi)
        np.add.at(forces, ij, fj)
        np.add.at(forces, ik, fk)
        np.add.at(forces, il, fl)
        virial += (f_v + g_v).T @ fi + g_v.T @ fj + h_v.T @ fl
        return u_imp, forces, virial

    def _eval_lennard_jones(
        self,
        pair_i: IntArray,
        pair_j: IntArray,
        dr_ij: FloatArray,
        dist_ij: FloatArray,
        lam: AlchemicalLambda,
        scale: float = 1.0,
    ) -> Tuple[float, FloatArray, FloatArray, float]:
        """Evaluate switched/shifted LJ 12-6 with optional Beutler soft-core coupling."""
        n = self.topology.n_atoms
        forces = np.zeros((n, 3), dtype=np.float64)
        virial = np.zeros((3, 3), dtype=np.float64)
        if pair_i.size == 0:
            return 0.0, forces, virial, 0.0

        sig_ij = 0.5 * (self.topology.sigmas[pair_i] + self.topology.sigmas[pair_j])
        eps_ij = scale * np.sqrt(self.topology.epsilons[pair_i] * self.topology.epsilons[pair_j])
        active = eps_ij > 1e-15
        if not np.any(active):
            return 0.0, forces, virial, 0.0

        pi = pair_i[active]
        pj = pair_j[active]
        dr = dr_ij[active]
        r = np.maximum(dist_ij[active], 1e-6)
        sig = sig_ij[active]
        eps = eps_ij[active]

        # Identify pairs involving alchemical atoms
        alch_pair = self.topology.alchemical_mask[pi] ^ self.topology.alchemical_mask[pj]
        # Note: intramolecular alchemical-alchemical pairs stay coupled unless both decouple;
        # standard absolute hydration/binding decouples solute-environment (XOR) or full solute.
        # Here we decouple solute-environment interactions (XOR) so internal ligand geometry stays intact.
        use_sc = (lam.lambda_vdw < 1.0) and np.any(alch_pair)

        # Standard LJ + optional C^2 switching function S(r) on [r_switch, r_cut]
        sr6 = (sig / r) ** 6
        u_raw = 4.0 * eps * (sr6 * sr6 - sr6)
        # Force factor -dU_raw/dr / r = 24*eps*(2*sr6^2 - sr6)/r^2
        f_over_r_raw = 24.0 * eps * (2.0 * sr6 * sr6 - sr6) / (r * r)

        rc = self.config.cutoff
        if self.config.shift_lj and self.config.switch_distance is None:
            src6 = (sig / rc) ** 6
            u_raw = u_raw - 4.0 * eps * (src6 * src6 - src6)
        elif self.config.switch_distance is not None:
            rs = self.config.switch_distance
            sw_mask = r > rs
            if np.any(sw_mask):
                t = np.clip((r[sw_mask] - rs) / (rc - rs), 0.0, 1.0)
                s_val = 1.0 - 10.0 * t**3 + 15.0 * t**4 - 6.0 * t**5
                ds_dr = (-30.0 * t**2 + 60.0 * t**3 - 30.0 * t**4) / (rc - rs)
                # U_sw = S * U_raw; F_over_r = -(S' * U_raw + S * U_raw') / r
                u_sw = u_raw[sw_mask]
                f_over_r_raw[sw_mask] = s_val * f_over_r_raw[sw_mask] - (ds_dr * u_sw) / r[sw_mask]
                u_raw[sw_mask] = s_val * u_sw

        du_dlam = 0.0
        if use_sc:
            lv = lam.lambda_vdw
            alpha_sc = lam.alpha_sc
            p_pow = lam.p_power
            q_pow = lam.q_power
            # Replace alchemical-environment pairs with Beutler soft-core potential
            m = alch_pair
            sig_m = sig[m]
            eps_m = eps[m]
            r_m = r[m]
            one_m_lam = 1.0 - lv
            soft_shift = alpha_sc * (one_m_lam ** q_pow)
            denom_core = soft_shift + (r_m / sig_m) ** 6
            inv_d = 1.0 / denom_core
            inv_d2 = inv_d * inv_d

            lam_p = lv ** p_pow
            u_sc = 4.0 * eps_m * lam_p * (inv_d2 - inv_d)
            # dU_sc / dr = 4*eps*lam^p * (-2*inv_d^3 + inv_d^2) * 6*(r/sig)^5 / sig
            # So -dU_sc/dr / r = 24*eps*lam^p * (2*inv_d^3 - inv_d^2) * (r^4 / sig^6)
            f_over_r_sc = (
                24.0 * eps_m * lam_p * (2.0 * inv_d2 * inv_d - inv_d2) * (r_m ** 4) / (sig_m ** 6)
            )
            # Apply cutoff switch if configured
            if self.config.switch_distance is not None:
                rs = self.config.switch_distance
                sw_m = r_m > rs
                if np.any(sw_m):
                    t = np.clip((r_m[sw_m] - rs) / (rc - rs), 0.0, 1.0)
                    s_val = 1.0 - 10.0 * t**3 + 15.0 * t**4 - 6.0 * t**5
                    ds_dr = (-30.0 * t**2 + 60.0 * t**3 - 30.0 * t**4) / (rc - rs)
                    f_over_r_sc[sw_m] = s_val * f_over_r_sc[sw_m] - (ds_dr * u_sc[sw_m]) / r_m[sw_m]
                    u_sc[sw_m] = s_val * u_sc[sw_m]

            # Analytical dU_sc / dlambda_vdw
            dlam_p = p_pow * (lv ** max(0, p_pow - 1)) if p_pow > 0 else 0.0
            dsoft_dlam = -alpha_sc * q_pow * (one_m_lam ** max(0, q_pow - 1)) if q_pow > 0 else 0.0
            du_dlam_pairs = 4.0 * eps_m * (
                dlam_p * (inv_d2 - inv_d)
                + lam_p * (-2.0 * inv_d2 * inv_d + inv_d2) * dsoft_dlam
            )
            if self.config.switch_distance is not None:
                rs = self.config.switch_distance
                sw_m = r_m > rs
                if np.any(sw_m):
                    t = np.clip((r_m[sw_m] - rs) / (rc - rs), 0.0, 1.0)
                    s_val = 1.0 - 10.0 * t**3 + 15.0 * t**4 - 6.0 * t**5
                    du_dlam_pairs[sw_m] *= s_val

            u_raw[m] = u_sc
            f_over_r_raw[m] = f_over_r_sc
            du_dlam = float(np.sum(du_dlam_pairs))
        elif np.any(alch_pair) and lam.lambda_vdw == 1.0:
            # Evaluate exact dU/dlambda at lambda = 1
            sig_m = sig[alch_pair]
            eps_m = eps[alch_pair]
            r_m = r[alch_pair]
            sr6_m = (sig_m / r_m) ** 6
            sr12_m = sr6_m * sr6_m
            p_pow = lam.p_power
            q_pow = lam.q_power
            dsoft = -lam.alpha_sc if q_pow == 1 else 0.0
            # At lambda=1, denom_core = (r/sig)^6 -> inv_d = sr6
            du_pairs = 4.0 * eps_m * (
                p_pow * (sr12_m - sr6_m)
                + (-2.0 * sr12_m * sr6_m + sr12_m) * dsoft
            )
            du_dlam = float(np.sum(du_pairs))

        u_lj = float(np.sum(u_raw))
        f_ij = dr * f_over_r_raw[:, None]
        np.add.at(forces, pi, -f_ij)
        np.add.at(forces, pj, f_ij)
        virial += dr.T @ f_ij
        return u_lj, forces, virial, du_dlam

    def _eval_reaction_field_or_cutoff(
        self,
        positions: FloatArray,
        box: SimulationBox,
        pair_i: IntArray,
        pair_j: IntArray,
        dr_ij: FloatArray,
        dist_ij: FloatArray,
        lam: AlchemicalLambda,
    ) -> Tuple[float, FloatArray, FloatArray, float]:
        """Evaluate Reaction-Field (Onsager continuum) or shifted cutoff Coulomb."""
        forces = np.zeros_like(positions)
        virial = np.zeros((3, 3), dtype=np.float64)
        u_elec = 0.0
        du_dlam = 0.0

        eff_q = np.where(
            self.topology.alchemical_mask,
            self.topology.charges * lam.lambda_elec,
            self.topology.charges,
        )
        rc = self.config.cutoff
        if self.config.electrostatics == "reaction_field":
            eps_rf = self.config.epsilon_rf
            k_rf = (eps_rf - 1.0) / (2.0 * eps_rf + 1.0) / (rc ** 3)
            c_rf = (3.0 * eps_rf) / (2.0 * eps_rf + 1.0) / rc
        else:
            k_rf = 0.0
            c_rf = 1.0 / rc

        def _eval_subset(
            pa: IntArray, pb: IntArray, dr: FloatArray, r: FloatArray, scale: float
        ) -> Tuple[float, float]:
            if pa.size == 0:
                return 0.0, 0.0
            qq = scale * eff_q[pa] * eff_q[pb]
            nz = np.abs(qq) > 1e-16
            if not np.any(nz):
                return 0.0, 0.0
            pa_n, pb_n = pa[nz], pb[nz]
            dr_n = dr[nz]
            r_n = np.maximum(r[nz], 1e-9)
            qq_n = qq[nz]
            inv_r = 1.0 / r_n
            u_pair = COULOMB_CONST_KJ_MOL_NM_E2 * qq_n * (inv_r + k_rf * r_n * r_n - c_rf)
            # F_j = -dU/dr_j = f*qq*(1/r^3 - 2*k_rf)*dr
            f_over_r = COULOMB_CONST_KJ_MOL_NM_E2 * qq_n * (inv_r * inv_r * inv_r - 2.0 * k_rf)
            f_ij = dr_n * f_over_r[:, None]
            np.add.at(forces, pa_n, -f_ij)
            np.add.at(forces, pb_n, f_ij)
            virial[:] += dr_n.T @ f_ij

            du = 0.0
            if np.any(self.topology.alchemical_mask):
                ca = self.topology.charges[pa_n]
                cb = self.topology.charges[pb_n]
                aa = self.topology.alchemical_mask[pa_n]
                ab = self.topology.alchemical_mask[pb_n]
                dqq = np.zeros_like(qq_n)
                both = aa & ab
                only_a = aa & ~ab
                only_b = ~aa & ab
                dqq[both] = 2.0 * lam.lambda_elec * ca[both] * cb[both] * scale
                dqq[only_a] = ca[only_a] * cb[only_a] * scale
                dqq[only_b] = ca[only_b] * cb[only_b] * scale
                du = float(np.sum(COULOMB_CONST_KJ_MOL_NM_E2 * dqq * (inv_r + k_rf * r_n * r_n - c_rf)))
            return float(np.sum(u_pair)), du

        u1, du1 = _eval_subset(pair_i, pair_j, dr_ij, dist_ij, 1.0)
        u_elec += u1
        du_dlam += du1

        if self._p14_i.size > 0:
            dr_14 = minimum_image_displacement(positions[self._p14_j] - positions[self._p14_i], box)
            dist_14 = np.linalg.norm(dr_14, axis=1)
            u2, du2 = _eval_subset(self._p14_i, self._p14_j, dr_14, dist_14, self.topology.fudge_qq)
            u_elec += u2
            du_dlam += du2

        return u_elec, forces, virial, du_dlam

    def _eval_restraints(self, positions: FloatArray, box: SimulationBox) -> Tuple[float, FloatArray, FloatArray]:
        """Evaluate harmonic COM distance restraints ``0.5 * k * (r_AB - r0)^2``."""
        forces = np.zeros_like(positions)
        virial = np.zeros((3, 3), dtype=np.float64)
        u_res = 0.0
        masses = self.topology.masses

        for rest in self._restraints:
            ia = np.asarray(rest.group_a, dtype=np.int64)
            ib = np.asarray(rest.group_b, dtype=np.int64)
            ma = masses[ia]
            mb = masses[ib]
            wa = ma / np.sum(ma)
            wb = mb / np.sum(mb)
            com_a = np.sum(positions[ia] * wa[:, None], axis=0)
            com_b = np.sum(positions[ib] * wb[:, None], axis=0)
            dr = minimum_image_displacement(com_b - com_a, box)
            dist = max(float(np.linalg.norm(dr)), 1e-12)
            diff = dist - rest.r0
            u_res += 0.5 * rest.k_restraint * diff * diff
            f_com_b = -rest.k_restraint * diff * (dr / dist)
            forces[ib] += wb[:, None] * f_com_b[None, :]
            forces[ia] -= wa[:, None] * f_com_b[None, :]
            virial += np.outer(dr, f_com_b)

        return u_res, forces, virial


def finite_difference_forces(
    force_field: ForceField,
    positions: FloatArray,
    box: SimulationBox,
    alchemical: Optional[AlchemicalLambda] = None,
    eps: float = 1e-6,
) -> FloatArray:
    """Compute central finite-difference reference forces ``-dU/dr`` for verification."""
    n = positions.shape[0]
    fd_forces = np.zeros((n, 3), dtype=np.float64)
    pos_work = positions.copy()
    for i in range(n):
        for dim in range(3):
            orig = pos_work[i, dim]
            pos_work[i, dim] = orig + eps
            ep, _ = force_field.evaluate(pos_work, box, alchemical=alchemical, force_rebuild=True)
            pos_work[i, dim] = orig - eps
            em, _ = force_field.evaluate(pos_work, box, alchemical=alchemical, force_rebuild=True)
            pos_work[i, dim] = orig
            fd_forces[i, dim] = -(ep.potential - em.potential) / (2.0 * eps)
    return fd_forces
