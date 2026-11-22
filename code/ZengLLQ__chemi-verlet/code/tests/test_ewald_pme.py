"""Tests for Particle-Mesh Ewald (PME) spectral electrostatics vs Exact Ewald."""

from __future__ import annotations

import numpy as np
import pytest

from chemi_verlet.ewald import ParticleMeshEwald, bspline_values_and_derivatives, exact_ewald_energy_forces
from chemi_verlet.forcefield import ForceField, ForceFieldConfig, finite_difference_forces
from chemi_verlet.types import AtomSpec, SimulationBox, Topology


def test_bspline_partition_of_unity() -> None:
    rng = np.random.default_rng(7)
    w = rng.uniform(0.0, 1.0, size=(25, 3))
    for order in (3, 4, 5):
        m_vals, dm_vals = bspline_values_and_derivatives(w, order=order)
        np.testing.assert_allclose(np.sum(m_vals, axis=-1), 1.0, atol=1e-12)
        np.testing.assert_allclose(np.sum(dm_vals, axis=-1), 0.0, atol=1e-12)


@pytest.mark.parametrize("triclinic", [False, True])
def test_pme_matches_exact_ewald_energy_and_forces(triclinic: bool) -> None:
    rng = np.random.default_rng(21 if not triclinic else 22)
    box = (
        SimulationBox.triclinic(2.5, 2.5, 2.5, alpha_deg=84.0, beta_deg=86.0, gamma_deg=82.0)
        if triclinic
        else SimulationBox.orthorhombic(2.5, 2.5, 2.5)
    )
    n_ions = 12
    frac = rng.uniform(0.05, 0.95, size=(n_ions, 3))
    pos = frac @ box.vectors.T
    charges = np.array([1.0, -1.0] * (n_ions // 2), dtype=np.float64)

    cutoff = 0.95
    pme = ParticleMeshEwald(cutoff=cutoff, grid_spacing=0.07, spline_order=6, tolerance=1e-6)
    u_exact, f_exact = exact_ewald_energy_forces(pos, charges, box, pme.alpha, cutoff=cutoff, k_max=11)

    atoms = [AtomSpec(i, f"Q{i}", "C", "ION", i + 1, 12.0, float(charges[i]), 0.3, 0.0) for i in range(n_ions)]
    topo = Topology(atoms=atoms, name="ion_box")
    ff = ForceField(
        topo,
        ForceFieldConfig(
            cutoff=cutoff,
            switch_distance=None,
            electrostatics="pme",
            pme_grid_spacing=0.07,
            pme_spline_order=6,
            pme_tolerance=1e-6,
            dispersion_correction=False,
        ),
    )
    eb, f_pme = ff.evaluate(pos, box, force_rebuild=True)
    u_pme = eb.coulomb_real + eb.coulomb_recip + eb.coulomb_self

    rel_e_err = abs(u_pme - u_exact) / max(abs(u_exact), 1e-9)
    rel_f_rmse = float(np.sqrt(np.mean((f_pme - f_exact) ** 2)) / np.sqrt(np.mean(f_exact ** 2)))
    assert rel_e_err < 1e-3
    assert rel_f_rmse < 2e-3


def test_pme_reciprocal_forces_match_finite_difference() -> None:
    rng = np.random.default_rng(23)
    box = SimulationBox.orthorhombic(2.4, 2.4, 2.4)
    pos = rng.uniform(0.2, 2.2, size=(8, 3))
    charges = np.array([0.6, -0.6, 0.4, -0.4, 0.8, -0.8, 0.3, -0.3], dtype=np.float64)

    atoms = [AtomSpec(i, f"A{i}", "C", "PME", 1, 12.0, float(charges[i]), 0.3, 0.0) for i in range(8)]
    topo = Topology(atoms=atoms)
    ff = ForceField(
        topo,
        ForceFieldConfig(
            cutoff=0.9,
            switch_distance=None,
            electrostatics="pme",
            pme_grid_spacing=0.10,
            pme_spline_order=4,
            dispersion_correction=False,
        ),
    )
    _, f_ana = ff.evaluate(pos, box, force_rebuild=True)
    f_fd = finite_difference_forces(ff, pos, box, eps=1e-6)
    np.testing.assert_allclose(f_ana, f_fd, rtol=1e-3, atol=5e-2)
