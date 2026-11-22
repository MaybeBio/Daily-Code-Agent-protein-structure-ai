"""Reference stress must differentiate every geometry input, including stiff reciprocal energies."""
from types import SimpleNamespace

import numpy as np
import pytest
import torch
from ase import Atoms
from graph_longrange.gto_utils import GTOBasis

from polar_reference import energy_stress


def calculator(atoms, energy):
    def batch(_):
        cell = torch.tensor(atoms.cell.array, dtype=torch.float64)
        data = {
            "positions": torch.tensor(atoms.positions, dtype=torch.float64),
            "shifts": torch.tensor([[1., -1., 0.], [0., 0., 1.]], dtype=torch.float64) @ cell,
            "cell": cell,
            "rcell": 2 * torch.pi * torch.linalg.inv(cell).T,
            "volume": torch.tensor([atoms.get_volume()], dtype=torch.float64),
        }
        return SimpleNamespace(to_dict=lambda: data)

    def model(data, **_):
        return {"energy": energy(data)}

    return SimpleNamespace(models=[model], _atoms_to_batch=batch, energy_units_to_eV=1., length_units_to_A=1.)


@pytest.mark.parametrize("angle", [0., 0.37])
def test_strain_derivative_includes_positions_shifts_reciprocal_cell_and_volume(angle):
    rotation = np.array([[np.cos(angle), -np.sin(angle), 0.], [np.sin(angle), np.cos(angle), 0.], [0., 0., 1.]])
    atoms = Atoms("H2", positions=np.array([[.3, .6, .1], [1.2, .4, .8]]) @ rotation,
                  cell=np.diag([3., 4., 5.]) @ rotation, pbc=True)
    calc = calculator(atoms, lambda d: 1.7*d["volume"] + .3*d["positions"].square().sum()
                      + .2*d["shifts"].square().sum() + .4*d["rcell"].square().sum())
    cell = atoms.cell.array
    reciprocal = 2*np.pi*np.linalg.inv(cell).T
    shifts = np.array([[1., -1., 0.], [0., 0., 1.]]) @ cell
    expected = 1.7*np.eye(3) + (.6*atoms.positions.T@atoms.positions + .4*shifts.T@shifts
                               - .8*reciprocal.T@reciprocal)/atoms.get_volume()
    energy, stress = energy_stress(calc, atoms)
    expected_energy = 1.7*atoms.get_volume() + .3*np.square(atoms.positions).sum() + .2*np.square(shifts).sum() + .4*np.square(reciprocal).sum()
    assert energy == pytest.approx(expected_energy, rel=1e-13)
    np.testing.assert_allclose(stress, expected, rtol=1e-12, atol=1e-13)


def test_stiff_volume_energy_has_no_finite_difference_truncation_bias():
    atoms = Atoms("H", positions=[[0., 0., 0.]], cell=[3., 4., 5.], pbc=True)
    volume = atoms.get_volume()
    pole = volume - .01
    calc = calculator(atoms, lambda d: 1/(d["volume"]-pole))
    _, stress = energy_stress(calc, atoms)
    derivative = -1/(volume-pole)**2
    np.testing.assert_allclose(stress, derivative*np.eye(3), rtol=1e-12, atol=1e-10)
    h = 1e-5
    coarse = (1/(volume*(1+h)-pole) - 1/(volume*(1-h)-pole))/(2*h*volume)
    assert abs(coarse-derivative) > .001*abs(derivative)


@pytest.mark.parametrize("max_l", [0, 1])
def test_radial_basis_stress_is_finite_at_zero_wavevector(max_l):
    atoms = Atoms("H", positions=[[0., 0., 0.]], cell=[3., 4., 5.], pbc=True)
    sigma = .4
    previous_dtype = torch.get_default_dtype()
    try:
        torch.set_default_dtype(torch.float64)
        basis = GTOBasis(max_l=max_l, sigmas=[sigma], kspace_cutoff=10., normalize="none", use_spline=False)
    finally:
        torch.set_default_dtype(previous_dtype)
    integers = torch.tensor([[0., 0., 0.], [1., 0., 0.], [0., 1., 1.]], dtype=torch.float64)

    def energy(data):
        vectors = integers @ data["rcell"]
        norm2 = vectors.square().sum(-1)
        moduli = basis._prepare_k_moduli(norm2, torch.tensor([True, False, False]))
        return basis.radial_spline(moduli).sum()

    _, stress = energy_stress(calculator(atoms, energy), atoms)
    vectors = integers.numpy()[1:] @ (2*np.pi*np.linalg.inv(atoms.cell.array).T)
    norms = np.linalg.norm(vectors, axis=1)
    prefactor = 4*np.pi*np.sqrt(np.pi/2)
    gaussian = np.exp(-.5*sigma**2*norms**2)
    weights = prefactor*sigma**5*gaussian
    if max_l == 1:
        weights -= prefactor*sigma**5*gaussian*(1-sigma**2*norms**2)/norms
    expected = np.einsum("n,ni,nj->ij", weights, vectors, vectors)/atoms.get_volume()
    np.testing.assert_allclose(stress, expected, rtol=1e-12, atol=1e-13)
