# SPDX-License-Identifier: LGPL-2.1-or-later
# Provenance: port of ASE 3.27's ase/optimize/fire.py (FIRE, downhill_check=False), LGPL-2.1-or-later; see
# NOTICE.md.
"""ASE 3.27's ``FIRE`` on host arrays.

ASE's step with forces ``f`` and the velocity ``v`` (zero at the first step):

- if ``f . v > 0``: ``v = (1 - a) v + a f |v| / |f|``; after more than ``Nmin`` such steps in a row the timestep
  grows by ``finc`` (up to ``dtmax``) and ``a`` shrinks by ``fa``;
- else: ``v = 0``, ``a = astart``, the timestep shrinks by ``fdec``;
- ``v += dt f``; ``dr = dt v``, scaled to ``maxstep`` when its norm over all atoms is longer.

``dt`` and ``dtmax`` are in ASE time units, as ASE's: they are step-size parameters, not physical times.
"""
from __future__ import annotations

import numpy as np


def _dot(a, b) -> float:
    """A plain sum over all components (no threaded BLAS call for arrays of this size)."""
    return float(np.einsum("ij,ij->", a, b))


class FIREState:
    """The optimiser's state. ``step(positions, forces)`` returns the next positions."""

    def __init__(self, n_atoms, dt=0.1, maxstep_A=0.2, dtmax=1.0, Nmin=5, finc=1.1, fdec=0.5, astart=0.1, fa=0.99,
                 a=0.1):
        self.dt, self.maxstep, self.dtmax, self.Nmin = float(dt), float(maxstep_A), float(dtmax), int(Nmin)
        self.finc, self.fdec, self.astart, self.fa, self.a = float(finc), float(fdec), float(astart), float(fa), float(a)
        self.v = None
        self.Nsteps = 0

    def step(self, positions, forces):
        f = np.asarray(forces, dtype=float)
        if self.v is None:
            self.v = np.zeros_like(f)
        else:
            vf = _dot(f, self.v)
            if vf > 0.0:
                self.v = (1.0 - self.a) * self.v + self.a * f / np.sqrt(_dot(f, f)) * np.sqrt(_dot(self.v, self.v))
                if self.Nsteps > self.Nmin:
                    self.dt = min(self.dt * self.finc, self.dtmax)
                    self.a *= self.fa
                self.Nsteps += 1
            else:
                self.v[:] *= 0.0
                self.a = self.astart
                self.dt *= self.fdec
                self.Nsteps = 0
        self.v += self.dt * f
        dr = self.dt * self.v
        normdr = np.sqrt(_dot(dr, dr))
        if normdr > self.maxstep:
            dr = self.maxstep * dr / normdr
        return np.asarray(positions, dtype=float) + dr
