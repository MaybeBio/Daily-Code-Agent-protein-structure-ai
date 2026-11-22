# SPDX-License-Identifier: LGPL-2.1-or-later
# Provenance: port of ASE 3.27's ase/filters.py (UnitCellFilter and FrechetCellFilter), LGPL-2.1-or-later; see
# NOTICE.md.
"""ASE 3.27's ``FrechetCellFilter`` on host arrays: positions and the cell relaxed together.

The degrees of freedom are ``n + 3`` rows: the positions in the original, undeformed cell, and the matrix
logarithm of the deformation gradient ``F`` (``cell = orig_cell F^T``) times ``exp_cell_factor`` (the number of
atoms by default). The gradient with respect to the logarithm comes from the Frechet derivative of the matrix
exponential, so forces and energy are consistent. ``scalar_pressure`` adds the enthalpy term ``p V``.

As in ASE, the cell rows hold ``logm(cell_factor F) exp_cell_factor`` with ``cell_factor`` the number of atoms: a
constant offset from ``logm(F)`` that drops out of every step.
"""
from __future__ import annotations

from itertools import product

import numpy as np


class FrechetCellView:
    """The filter over a working ``Atoms`` (changed in place by ``set_x``)."""

    def __init__(self, atoms, scalar_pressure=0.0, hydrostatic_strain=False, constant_volume=False, mask=None,
                 exp_cell_factor=None):
        from ase.stress import voigt_6_to_full_3x3_stress

        self.atoms = atoms
        self.orig_cell = atoms.cell.array.copy()
        mask = np.ones(6) if mask is None else np.asarray(mask, dtype=float)
        self.mask = voigt_6_to_full_3x3_stress(mask) if mask.shape == (6,) else mask
        self.hydrostatic_strain, self.constant_volume = bool(hydrostatic_strain), bool(constant_volume)
        self.scalar_pressure = float(scalar_pressure)
        self.cell_factor = float(len(atoms))
        self.exp_cell_factor = float(len(atoms)) if exp_cell_factor is None else float(exp_cell_factor)
        self.stress = None               # the Cauchy stress the convergence is judged on (3x3), after gradient()

    def __len__(self):
        return len(self.atoms) + 3

    def deform_grad(self):
        return np.linalg.solve(self.orig_cell, self.atoms.cell.array).T

    def get_x(self):
        from scipy.linalg import logm

        deform = self.deform_grad()
        n = len(self.atoms)
        x = np.zeros((n + 3, 3))
        x[:n] = np.linalg.solve(deform, self.atoms.positions.T).T
        x[n:] = logm(self.cell_factor * deform) * self.exp_cell_factor
        return x

    def set_x(self, x):
        from scipy.linalg import expm

        n = len(self.atoms)
        new_deform_grad = expm(x[n:] / self.exp_cell_factor) / self.cell_factor
        deform = (new_deform_grad - np.eye(3)).T * self.mask
        self.atoms.set_cell(self.orig_cell @ (np.eye(3) + deform), scale_atoms=True)
        self.atoms.set_positions(x[:n] @ (np.eye(3) + deform))

    def value(self, energy):
        """The enthalpy: the potential energy plus ``p V``."""
        return energy + self.scalar_pressure * self.atoms.get_volume()

    def forces(self, forces, stress):
        """The ``n + 3`` force rows from the atoms' forces and the stress (3x3, eV/A^3)."""
        from scipy.linalg import expm_frechet, logm

        stress = 0.5 * (np.asarray(stress, dtype=float) + np.asarray(stress, dtype=float).T)
        volume = self.atoms.get_volume()
        virial = -volume * (stress + np.diag([self.scalar_pressure] * 3))
        deform = self.deform_grad()
        deform_log = logm(deform)
        if self.hydrostatic_strain:
            trace = virial.trace()
            virial = np.diag([trace / 3.0, trace / 3.0, trace / 3.0])
        if (self.mask != 1.0).any():
            virial *= self.mask
        cell_grad = virial @ np.linalg.inv(deform.T)
        log_force = np.zeros((3, 3))
        for mu, nu in product(range(3), repeat=2):
            direction = np.zeros((3, 3))
            direction[mu, nu] = 1.0
            derivative = expm_frechet(deform_log, direction, compute_expm=False)
            log_force[mu, nu] = np.sum(derivative * cell_grad)
        criterion_stress = -(virial / volume)
        if self.constant_volume:
            np.fill_diagonal(log_force, np.diag(log_force) - log_force.trace() / 3.0)
            np.fill_diagonal(criterion_stress, np.diag(criterion_stress) - criterion_stress.trace() / 3.0)
        n = len(self.atoms)
        out = np.zeros((n + 3, 3))
        out[:n] = np.asarray(forces, dtype=float) @ deform
        out[n:] = log_force / self.exp_cell_factor
        self.stress = criterion_stress
        return out
