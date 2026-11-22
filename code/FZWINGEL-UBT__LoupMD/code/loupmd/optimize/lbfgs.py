# SPDX-License-Identifier: LGPL-2.1-or-later
# Provenance: port of ASE 3.27's ase/optimize/lbfgs.py (LBFGS, use_line_search=False), LGPL-2.1-or-later; see
# NOTICE.md.
"""ASE 3.27's ``LBFGS`` on host arrays.

ASE's step at iteration ``k`` with positions ``x``, gradient ``g`` (minus the forces, zero on fixed atoms) and
the previous ``r0``, ``g0``:

- the history gains ``s = x - r0``, ``y = g - g0``, ``rho = 1 / (y . s)`` (from ``k = 1``) and loses its oldest
  pair once it holds more than ``memory``;
- the two-loop recursion gives ``z ~ H g`` with ``H0 = 1 / alpha``; the direction is ``p = -z``;
- if the largest per-atom length of ``p`` is ``>= maxstep`` the whole step is scaled to it; then times ``damping``.

**The two-loop recursion in matrix form** (as FastMACE's device LBFGS). ASE's loops over the chronological history,

    a_i = rho_i s_i . (q0 - sum_{j > i} a_j y_j)                       (newest to oldest)
    b_i = rho_i y_i . (H0 q + sum_{j < i} s_j c_j),  c_j = a_j - b_j   (oldest to newest)

are two unit-triangular systems in the Gram matrix ``G_ij = s_i . y_j``:
``(I + diag(rho) triu(G)) a = diag(rho) S q0`` and ``(I + diag(rho) tril(G^T)) c = a - diag(rho) Y H0 q`` with
``q = q0 - Y^T a`` and ``z = H0 q + S^T c``. That is four matrix-vector products with the history and two small
triangular solves per step, and two more products to keep ``G`` current: a few hundred Python-level vector
operations become six BLAS calls. The result equals ASE's to rounding (the order of the sums differs).
"""
from __future__ import annotations

import numpy as np

MAX_MAXSTEP_A = 1.0       # ASE's limit on maxstep, in A


def _dot(a, b) -> float:
    """A plain dot product: for vectors of this length a threaded BLAS call costs more than the sum."""
    return float(np.einsum("i,i->", a, b))


class LBFGSState:
    """The optimiser's state for ``n`` rows of three. ``step(positions, forces)`` returns the next positions."""

    def __init__(self, n_atoms, maxstep_A=0.2, memory=100, damping=1.0, alpha=70.0):
        self.maxstep, self.memory, self.damping, self.H0 = float(maxstep_A), int(memory), float(damping), 1.0 / alpha
        self.s = np.zeros((self.memory, 3 * n_atoms))     # the history, oldest first
        self.y = np.zeros((self.memory, 3 * n_atoms))
        self.rho = np.zeros(self.memory)
        self.gram = np.zeros((self.memory, self.memory))  # gram[i, j] = s_i . y_j
        self.count = 0                                    # pairs in the history
        self.iteration = 0
        self.r0 = self.g0 = None

    def _append(self, s, y):
        if self.count == self.memory:                     # drop the oldest pair
            self.s[:-1] = self.s[1:]
            self.y[:-1] = self.y[1:]
            self.rho[:-1] = self.rho[1:]
            self.gram[:-1, :-1] = self.gram[1:, 1:]
            self.count -= 1
        k = self.count
        self.s[k], self.y[k], self.rho[k] = s, y, 1.0 / _dot(y, s)
        self.gram[k, :k + 1] = self.y[:k + 1] @ s         # s_k . y_j
        self.gram[:k + 1, k] = self.s[:k + 1] @ y         # s_i . y_k
        self.count += 1

    def direction(self, g):
        """ASE's ``p = -z`` for the gradient ``g``."""
        from scipy.linalg import solve_triangular

        n = self.count
        if n == 0:
            return -self.H0 * g
        S, Y, R = self.s[:n], self.y[:n], self.rho[:n]
        gram = self.gram[:n, :n]
        a = solve_triangular(R[:, None] * gram, R * (S @ g), lower=False, unit_diagonal=True)
        z = self.H0 * (g - a @ Y)
        c = solve_triangular(R[:, None] * gram.T, a - R * (Y @ z), lower=True, unit_diagonal=True)
        return -(z + c @ S)

    def step(self, positions, forces):
        x = np.asarray(positions, dtype=float).reshape(-1)
        g = -np.asarray(forces, dtype=float).reshape(-1)
        if self.iteration > 0:
            self._append(x - self.r0, g - self.g0)
        p = self.direction(g).reshape(-1, 3)
        longest = np.sqrt(np.einsum("ij,ij->i", p, p).max())
        if longest >= self.maxstep:
            p *= self.maxstep / longest
        self.iteration += 1
        self.r0, self.g0 = x.copy(), g
        return (x + (p * self.damping).reshape(-1)).reshape(-1, 3)
