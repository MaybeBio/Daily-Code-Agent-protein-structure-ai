"""PolarMACE stress from the native energy's complete cell dependence.

Strain autograd avoids finite-difference truncation and cutoff jumps. The independent finite-difference
diagnostic freezes reciprocal integer indices, not Cartesian vectors. Scoped dependency patches require
serial reference evaluations, as used by test_gate.py.
"""
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

import numpy as np


@contextmanager
def frozen_kset(cutoff, cell):
    """Hold integer reciprocal indices, while allowing their vectors/norms to follow each strained cell."""
    import torch
    import mace.modules.extensions as extensions

    original = extensions.compute_k_vectors_flat
    cell_tensor = torch.as_tensor(np.asarray(cell), dtype=cutoff.dtype, device=cutoff.device)[None]
    reciprocal = 2 * np.pi * torch.linalg.inv(cell_tensor.transpose(-1, -2))
    with torch.no_grad():
        vectors, _, batch, zero = original(cutoff, cell_tensor, reciprocal)
        indices = (vectors @ torch.linalg.inv(reciprocal[0])).round()

    def fixed(cutoff, cell_vectors, r_cell_vectors):
        if cell_vectors.shape[0] != 1:
            raise ValueError("the frozen reciprocal set belongs to one configuration")
        vectors = indices @ r_cell_vectors[0]
        return vectors, (vectors * vectors).sum(-1), batch, zero

    with patch.object(extensions, "compute_k_vectors_flat", fixed):
        yield len(indices)


def _radial_direct(self, k_mods):
    """graph_longrange's formula, preserving multiplication order without out= writes."""
    import torch

    exp_term = torch.exp(-0.5 * (k_mods * k_mods).unsqueeze(-1) * self.sigma2)
    monopole = self.pref0 * exp_term
    if self.max_l == 0:
        return monopole.unsqueeze(-1)
    dipole = self.pref1 * (k_mods.unsqueeze(-1) * exp_term)
    return torch.stack((monopole, dipole), dim=-1)


def _k_moduli(self, k_norm2, k0_mask):
    """Keep sqrt's saved output intact and its derivative finite at the zero wavevector."""
    import torch

    zero = k0_mask > 0
    return torch.where(zero, 0.0, torch.sqrt(torch.clamp_min(torch.where(zero, 1.0, k_norm2), 0.0)))


def energy_stress(calc, atoms):
    """Native energy and symmetric strain derivative for one periodic PolarMACE configuration.

    MACE's original stress misses the reciprocal cell and volume dependence. Deform all input geometry
    before its energy-only forward instead; the unstrained values and native summation order are preserved.
    Boolean cutoff selection naturally differentiates only the terms included at the unstrained cell.
    """
    import torch
    from graph_longrange.gto_utils import GTOBasis, RadialIntegralDirect

    if len(calc.models) != 1:
        raise ValueError("strain reference requires one model")
    batch = calc._atoms_to_batch(atoms).to_dict()
    position = batch["positions"]
    with torch.enable_grad():
        strain = torch.zeros((3, 3), dtype=position.dtype, device=position.device, requires_grad=True)
        transform = torch.eye(3, dtype=position.dtype, device=position.device) + strain
        batch["positions"] = batch["positions"] @ transform
        batch["shifts"] = batch["shifts"] @ transform
        batch["cell"] = batch["cell"] @ transform
        batch["rcell"] = batch["rcell"] @ torch.linalg.inv(transform).T
        batch["volume"] = batch["volume"] * torch.linalg.det(transform)
        with ExitStack() as stack:
            stack.enter_context(patch.object(RadialIntegralDirect, "forward", _radial_direct))
            stack.enter_context(patch.object(GTOBasis, "_prepare_k_moduli", _k_moduli))
            energy = calc.models[0](batch, compute_force=False, compute_stress=False)["energy"].sum()
            gradient = torch.autograd.grad(energy, strain)[0]
        stress = (gradient + gradient.T) / (2 * atoms.get_volume())
        stress = stress * calc.energy_units_to_eV / calc.length_units_to_A**3
    return float(energy.detach()) * calc.energy_units_to_eV, stress.detach().cpu().numpy()


def stress_reference(model_path, configs, *, device):
    """Float64 strain-autograd targets; no finite-difference step or altered gate allowance."""
    from mace.calculators import MACECalculator

    calc = MACECalculator(model_paths=model_path, device=device, default_dtype="float64")
    return [energy_stress(calc, atoms)[1] for _, atoms in configs]


def fd_stress(model_path, configs, *, device, h):
    """Independent finite-difference diagnostic; check convergence in h before treating it as a target."""
    from mace.calculators import MACECalculator

    calc = MACECalculator(model_paths=model_path, device=device, default_dtype="float64")
    out = []
    for _, atoms in configs:
        def energy(eps):
            at = atoms.copy()
            transform = np.eye(3) + eps
            at.set_cell(atoms.cell.array @ transform, scale_atoms=False)
            at.positions = atoms.positions @ transform
            at.calc = calc
            return at.get_potential_energy()

        volume = atoms.get_volume()
        stress = np.zeros((3, 3))
        with frozen_kset(calc.models[0].kspace_cutoff, atoms.cell.array):
            for i in range(3):
                for j in range(i, 3):
                    eps = np.zeros((3, 3))
                    eps[i, j] = eps[j, i] = h
                    value = (energy(eps) - energy(-eps)) / (2 * h * volume * (1 if i == j else 2))
                    stress[i, j] = stress[j, i] = value
        out.append(stress)
    return out
