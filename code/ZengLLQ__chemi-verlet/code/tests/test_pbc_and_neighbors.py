"""Tests for periodic boundary geometry and O(N) cell-linked neighbor lists."""

from __future__ import annotations

import numpy as np
import pytest

from chemi_verlet.pbc import (
    CellListNeighborFinder,
    compute_pair_list_direct,
    minimum_image_displacement,
    minimum_image_pair_vectors,
    wrap_positions,
)
from chemi_verlet.types import SimulationBox


def test_triclinic_box_volume_and_wrapping() -> None:
    box = SimulationBox.triclinic(2.5, 2.8, 3.0, alpha_deg=82.0, beta_deg=85.0, gamma_deg=78.0)
    assert box.volume > 0.0
    assert not box.is_orthorhombic
    rng = np.random.default_rng(10)
    pos = rng.uniform(-5.0, 8.0, size=(30, 3))
    wrapped = wrap_positions(pos, box)
    frac = wrapped @ box.inv_vectors.T
    assert np.all(frac >= -1e-12)
    assert np.all(frac < 1.0 + 1e-12)


def test_minimum_image_invariance_under_lattice_shifts() -> None:
    box = SimulationBox.triclinic(3.0, 3.2, 3.4, alpha_deg=80.0, beta_deg=88.0, gamma_deg=75.0)
    rng = np.random.default_rng(11)
    r_a = rng.uniform(0.0, 3.0, size=(20, 3))
    r_b = rng.uniform(0.0, 3.0, size=(20, 3))
    mic_orig = minimum_image_displacement(r_b - r_a, box)

    shifts = rng.integers(-3, 4, size=(20, 3))
    r_b_shifted = r_b + shifts @ box.vectors.T
    mic_shifted = minimum_image_displacement(r_b_shifted - r_a, box)
    np.testing.assert_allclose(mic_orig, mic_shifted, atol=1e-11)


@pytest.mark.parametrize("triclinic", [False, True])
def test_cell_list_matches_direct_pair_list(triclinic: bool) -> None:
    rng = np.random.default_rng(12 if not triclinic else 13)
    box = (
        SimulationBox.triclinic(4.2, 4.4, 4.1, alpha_deg=85.0, beta_deg=87.0, gamma_deg=80.0)
        if triclinic
        else SimulationBox.orthorhombic(4.2, 4.4, 4.1)
    )
    pos = wrap_positions(rng.uniform(0.0, 4.0, size=(120, 3)), box)
    exclusions = {0: {0, 1, 2}, 1: {0, 1}, 2: {0, 2}}
    cutoff = 0.95

    ref_i, ref_j = compute_pair_list_direct(pos, box, cutoff, exclusions=exclusions)
    ref_set = set(zip(ref_i.tolist(), ref_j.tolist()))

    finder = CellListNeighborFinder(cutoff=cutoff, skin=0.20, exclusions=exclusions)
    ci, cj, dr, dist = finder.get_pairs(pos, box)
    cell_set = set(zip(ci.tolist(), cj.tolist()))

    assert cell_set == ref_set
    assert np.all(dist <= cutoff + 1e-12)
    assert finder.rebuild_count == 1

    # Small perturbation within skin/2 should reuse Verlet list without rebuilding
    pos_small = pos + rng.uniform(-0.02, 0.02, size=pos.shape)
    ci2, cj2, _, _ = finder.get_pairs(pos_small, box)
    assert finder.rebuild_count == 1
    ref_i2, ref_j2 = compute_pair_list_direct(pos_small, box, cutoff, exclusions=exclusions)
    assert set(zip(ci2.tolist(), cj2.tolist())) == set(zip(ref_i2.tolist(), ref_j2.tolist()))

    # Large perturbation beyond skin/2 triggers rebuild
    pos_large = pos + rng.uniform(-0.18, 0.18, size=pos.shape)
    _ = finder.get_pairs(pos_large, box)
    assert finder.rebuild_count == 2


def test_minimum_image_pair_vectors_symmetry() -> None:
    box = SimulationBox.orthorhombic(3.0, 3.0, 3.0)
    pos = np.array([[0.1, 0.2, 0.3], [2.9, 0.2, 0.3], [1.5, 1.5, 1.5]], dtype=np.float64)
    dr, dist = minimum_image_pair_vectors(pos, box)
    assert pytest.approx(dist[0, 1], abs=1e-12) == 0.2
    np.testing.assert_allclose(dr, -np.transpose(dr, (1, 0, 2)), atol=1e-12)
