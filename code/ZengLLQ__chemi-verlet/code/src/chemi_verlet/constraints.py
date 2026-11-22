"""Holonomic bond-length constraint solvers: SHAKE, RATTLE, and LINCS.

Enforces fixed interatomic bond distances ``|r_i - r_j| = d_{ij}`` and
orthogonal relative velocities ``(v_i - v_j) . (r_i - r_j) = 0`` during
molecular dynamics integration, enabling 2 fs time steps with rigid X-H bonds
and rigid 3-site solvent models.
"""

from __future__ import annotations

from typing import List, Tuple
import numpy as np

from chemi_verlet.pbc import minimum_image_displacement
from chemi_verlet.types import ConstraintPair, FloatArray, SimulationBox, Topology


def constraint_rms_deviation(
    positions: FloatArray,
    constraints: List[ConstraintPair],
    box: SimulationBox,
) -> float:
    """Return root-mean-square bond-length constraint violation in nm."""
    if not constraints:
        return 0.0
    errs = np.empty(len(constraints), dtype=np.float64)
    for idx, c in enumerate(constraints):
        dr = minimum_image_displacement(positions[c.j] - positions[c.i], box)
        errs[idx] = float(np.linalg.norm(dr)) - c.distance
    return float(np.sqrt(np.mean(errs * errs)))


class ShakeSolver:
    """Iterative SHAKE position and RATTLE velocity holonomic constraint solver."""

    def __init__(
        self,
        topology: Topology,
        tolerance: float = 1e-7,
        max_iterations: int = 200,
    ) -> None:
        self.topology = topology
        self.constraints = topology.constraints
        self.tolerance = float(tolerance)
        self.max_iterations = int(max_iterations)

    def constrain_positions(
        self,
        r_ref: FloatArray,
        r_unc: FloatArray,
        box: SimulationBox,
        dt: float,
    ) -> Tuple[FloatArray, FloatArray]:
        """Project unconstrained positions ``r_unc`` onto constraint manifold.

        Returns ``(r_constrained, constraint_virial)``.
        """
        r = r_unc.copy()
        virial = np.zeros((3, 3), dtype=np.float64)
        if not self.constraints:
            return r, virial

        inv_m = self.topology.inv_masses
        inv_dt2 = 1.0 / (dt * dt) if dt > 0.0 else 0.0

        for _ in range(self.max_iterations):
            max_rel_err = 0.0
            for c in self.constraints:
                r_ij_ref = minimum_image_displacement(r_ref[c.j] - r_ref[c.i], box)
                r_ij_cur = minimum_image_displacement(r[c.j] - r[c.i], box)
                d2 = c.distance * c.distance
                diff = float(np.dot(r_ij_cur, r_ij_cur)) - d2
                rel_err = abs(diff) / (2.0 * d2)
                if rel_err > max_rel_err:
                    max_rel_err = rel_err
                if rel_err > self.tolerance:
                    wi = float(inv_m[c.i])
                    wj = float(inv_m[c.j])
                    denom = 2.0 * (wi + wj) * float(np.dot(r_ij_cur, r_ij_ref))
                    if abs(denom) < 1e-16:
                        continue
                    g = diff / denom
                    delta = g * r_ij_ref
                    r[c.i] += wi * delta
                    r[c.j] -= wj * delta
                    # Constraint force on j is -g * r_ij_ref / dt^2 -> virial += r_ij_ref (x) F_j
                    virial += np.outer(r_ij_ref, -delta * inv_dt2)
            if max_rel_err <= self.tolerance:
                break
        return r, virial

    def constrain_velocities(
        self,
        positions: FloatArray,
        velocities: FloatArray,
        box: SimulationBox,
    ) -> FloatArray:
        """Apply RATTLE velocity projection ``(v_j - v_i) . r_ij = 0``."""
        v = velocities.copy()
        if not self.constraints:
            return v
        inv_m = self.topology.inv_masses

        for _ in range(self.max_iterations):
            max_v_err = 0.0
            for c in self.constraints:
                r_ij = minimum_image_displacement(positions[c.j] - positions[c.i], box)
                v_ij = v[c.j] - v[c.i]
                dot_rv = float(np.dot(r_ij, v_ij))
                r2 = float(np.dot(r_ij, r_ij))
                if r2 < 1e-16:
                    continue
                err = abs(dot_rv) / c.distance
                if err > max_v_err:
                    max_v_err = err
                if err > self.tolerance:
                    wi = float(inv_m[c.i])
                    wj = float(inv_m[c.j])
                    k = dot_rv / ((wi + wj) * r2)
                    v[c.i] += wi * k * r_ij
                    v[c.j] -= wj * k * r_ij
            if max_v_err <= self.tolerance:
                break
        return v


class LincsSolver:
    """Linear Constraint Solver (LINCS, Hess et al. 1997) with rotational correction.

    Builds the sparse constraint coupling graph, computes normalized inverse-mass
    weighted projections ``B``, solves ``(I - A)^{-1}`` via truncated Neumann series
    ``I + A + A^2 + ... + A^{n_order}``, and applies second-order lengthening
    correction for rotating rigid bonds.
    """

    def __init__(
        self,
        topology: Topology,
        n_order: int = 8,
        n_iter: int = 4,
    ) -> None:
        self.topology = topology
        self.constraints = topology.constraints
        self.n_order = max(1, int(n_order))
        self.n_iter = max(1, int(n_iter))
        self.n_c = len(self.constraints)

        if self.n_c > 0:
            self.ci = np.array([c.i for c in self.constraints], dtype=np.int64)
            self.cj = np.array([c.j for c in self.constraints], dtype=np.int64)
            self.dists = np.array([c.distance for c in self.constraints], dtype=np.float64)
            inv_m = topology.inv_masses
            self.s_diag = 1.0 / np.sqrt(inv_m[self.ci] + inv_m[self.cj])
            # Precompute adjacency of constraints sharing an atom for sparse coupling
            self._connected_pairs: List[Tuple[int, int, float]] = []
            atom_to_c: dict[int, List[Tuple[int, int]]] = {}
            for k, c in enumerate(self.constraints):
                atom_to_c.setdefault(c.i, []).append((k, -1))
                atom_to_c.setdefault(c.j, []).append((k, +1))
            for atom_idx, entries in atom_to_c.items():
                if len(entries) < 2:
                    continue
                wi = float(inv_m[atom_idx])
                for p in range(len(entries)):
                    c1, sign1 = entries[p]
                    for q in range(p + 1, len(entries)):
                        c2, sign2 = entries[q]
                        # Sign of B_c1 * M^{-1} * B_c2^T contribution
                        # Notice B row k has -1 at i and +1 at j: so r_j - r_i direction!
                        # Coupling coefficient in A = -S * (B M^{-1} B^T - diag) * S
                        coef = -float(sign1 * sign2) * wi * float(self.s_diag[c1] * self.s_diag[c2])
                        self._connected_pairs.append((c1, c2, coef))
                        self._connected_pairs.append((c2, c1, coef))

    def _build_coupling_matrix(self, b_dirs: FloatArray) -> FloatArray:
        """Construct symmetric constraint coupling matrix A (n_c x n_c)."""
        a_mat = np.zeros((self.n_c, self.n_c), dtype=np.float64)
        for c1, c2, coef in self._connected_pairs:
            a_mat[c1, c2] += coef * float(np.dot(b_dirs[c1], b_dirs[c2]))
        return a_mat

    def _solve_neumann(self, a_mat: FloatArray, rhs: FloatArray) -> FloatArray:
        """Apply truncated Neumann expansion ``(I + A + A^2 + ... + A^{n_order}) rhs``."""
        sol = rhs.copy()
        term = rhs.copy()
        for _ in range(self.n_order):
            term = a_mat @ term
            sol += term
        return sol

    def constrain_positions(
        self,
        r_ref: FloatArray,
        r_unc: FloatArray,
        box: SimulationBox,
        dt: float,
    ) -> Tuple[FloatArray, FloatArray]:
        """Project ``r_unc`` using LINCS + iterative rotational lengthening correction."""
        r = r_unc.copy()
        virial = np.zeros((3, 3), dtype=np.float64)
        if self.n_c == 0:
            return r, virial

        dr_ref = minimum_image_displacement(r_ref[self.cj] - r_ref[self.ci], box)
        norms_ref = np.maximum(np.linalg.norm(dr_ref, axis=1), 1e-12)
        b_dirs = dr_ref / norms_ref[:, None]  # unit vectors pointing i -> j
        a_mat = self._build_coupling_matrix(b_dirs)

        inv_m = self.topology.inv_masses
        inv_dt2 = 1.0 / (dt * dt) if dt > 0.0 else 0.0

        # Step 1: linear projection onto tangent plane of old bond directions
        dr_unc = minimum_image_displacement(r[self.cj] - r[self.ci], box)
        proj = np.sum(b_dirs * dr_unc, axis=1)
        rhs = self.s_diag * (proj - self.dists)
        lam = self.s_diag * self._solve_neumann(a_mat, rhs)

        for k in range(self.n_c):
            ci_k, cj_k = int(self.ci[k]), int(self.cj[k])
            corr = lam[k] * b_dirs[k]
            r[ci_k] += inv_m[ci_k] * corr
            r[cj_k] -= inv_m[cj_k] * corr
            # Update virial: force on j is -lam[k]*b_dirs[k]/dt^2
            virial += np.outer(dr_ref[k], -corr * inv_dt2)

        # Step 2: iterative correction for rotational lengthening sqrt(2 d^2 - p^2)
        for _ in range(self.n_iter):
            dr_cur = minimum_image_displacement(r[self.cj] - r[self.ci], box)
            len_sq = np.sum(dr_cur * dr_cur, axis=1)
            p_sq = np.maximum(2.0 * self.dists * self.dists - len_sq, 0.0)
            rhs_rot = self.s_diag * (self.dists - np.sqrt(p_sq))
            lam_rot = self.s_diag * self._solve_neumann(a_mat, rhs_rot)
            for k in range(self.n_c):
                ci_k, cj_k = int(self.ci[k]), int(self.cj[k])
                corr = lam_rot[k] * b_dirs[k]
                r[ci_k] += inv_m[ci_k] * corr
                r[cj_k] -= inv_m[cj_k] * corr
                virial += np.outer(dr_ref[k], -corr * inv_dt2)

        return r, virial

    def constrain_velocities(
        self,
        positions: FloatArray,
        velocities: FloatArray,
        box: SimulationBox,
    ) -> FloatArray:
        """Project velocities orthogonal to constrained bonds using LINCS coupling matrix."""
        v = velocities.copy()
        if self.n_c == 0:
            return v
        dr = minimum_image_displacement(positions[self.cj] - positions[self.ci], box)
        norms = np.maximum(np.linalg.norm(dr, axis=1), 1e-12)
        b_dirs = dr / norms[:, None]
        a_mat = self._build_coupling_matrix(b_dirs)
        inv_m = self.topology.inv_masses

        for _ in range(max(2, self.n_iter + 2)):
            dv = v[self.cj] - v[self.ci]
            proj_v = np.sum(b_dirs * dv, axis=1)
            if float(np.max(np.abs(proj_v))) < 1e-10:
                break
            rhs = self.s_diag * proj_v
            lam = self.s_diag * self._solve_neumann(a_mat, rhs)
            for k in range(self.n_c):
                ci_k, cj_k = int(self.ci[k]), int(self.cj[k])
                corr = lam[k] * b_dirs[k]
                v[ci_k] += inv_m[ci_k] * corr
                v[cj_k] -= inv_m[cj_k] * corr
        return v
