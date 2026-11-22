"""A cutoff crossing must not turn a smooth reciprocal term's stress into a 1/h energy jump."""
import numpy as np
import pytest
import torch
import mace.modules.extensions as extensions

from polar_reference import frozen_kset


@pytest.mark.parametrize("rotated", [False, True])
def test_frozen_reciprocal_indices_keep_the_correct_strain_derivative(rotated):
    angle = 0.3 if rotated else 0.0
    rotation = np.array([[np.cos(angle), -np.sin(angle), 0], [np.sin(angle), np.cos(angle), 0], [0, 0, 1]])
    cell = np.diag(2 * np.pi * np.array([1 + 1e-6, 1.2, 0.8])) @ rotation
    cutoff = torch.tensor(1.0, dtype=torch.float64)

    def terms(strain):
        c = torch.tensor(cell @ (np.eye(3) + strain), dtype=torch.float64)[None]
        reciprocal = 2 * np.pi * torch.linalg.inv(c.transpose(-1, -2))
        return extensions.compute_k_vectors_flat(cutoff=cutoff, cell_vectors=c, r_cell_vectors=reciprocal)

    vectors, _, _, _ = terms(np.zeros((3, 3)))
    expected = -2 * vectors.numpy().T @ vectors.numpy() / np.linalg.det(cell)
    h = 1e-4
    crossing = np.diag([h, 0.0, 0.0])
    assert len(terms(crossing)[0]) != len(terms(-crossing)[0])  # this fixture really crosses the live cutoff
    stress = np.zeros((3, 3))
    with frozen_kset(cutoff, cell):
        for i in range(3):
            for j in range(i, 3):
                eps = np.zeros((3, 3))
                eps[i, j] = eps[j, i] = h
                eplus = float(terms(eps)[1].sum())
                eminus = float(terms(-eps)[1].sum())
                stress[i, j] = stress[j, i] = (eplus - eminus) / (2 * h * np.linalg.det(cell) * (1 if i == j else 2))
    np.testing.assert_allclose(stress, expected, rtol=1e-6, atol=1e-10)
