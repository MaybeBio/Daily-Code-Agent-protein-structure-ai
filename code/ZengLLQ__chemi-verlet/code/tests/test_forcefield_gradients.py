"""Tests verifying analytical forces & alchemical derivatives against finite differences."""

from __future__ import annotations

import numpy as np
import pytest

from chemi_verlet.forcefield import (
    ForceField,
    ForceFieldConfig,
    HarmonicCOMRestraint,
    finite_difference_forces,
)
from chemi_verlet.topology import build_alkane_chain, build_solvated_ligand_box, smiles_to_topology
from chemi_verlet.types import AlchemicalLambda, AtomSpec, ImproperTerm, SimulationBox, Topology


def _assert_forces_match_fd(
    ff: ForceField,
    pos: np.ndarray,
    box: SimulationBox,
    alchemical: AlchemicalLambda | None = None,
    atol: float = 1e-3,
    rtol: float = 1e-4,
) -> None:
    _, f_ana = ff.evaluate(pos, box, alchemical=alchemical, force_rebuild=True)
    f_fd = finite_difference_forces(ff, pos, box, alchemical=alchemical, eps=1e-6)
    np.testing.assert_allclose(f_ana, f_fd, rtol=rtol, atol=atol)


def test_bonded_and_rb_dihedral_forces_match_finite_difference() -> None:
    topo, coords = build_alkane_chain(5, constrain_bonds=False)
    rng = np.random.default_rng(101)
    pos = coords + 1.2 + rng.normal(0.0, 0.03, size=coords.shape)
    box = SimulationBox.orthorhombic(3.0, 3.0, 3.0)
    ff = ForceField(
        topo,
        ForceFieldConfig(cutoff=0.9, electrostatics="cutoff", dispersion_correction=False, switch_distance=None),
    )
    _assert_forces_match_fd(ff, pos, box, atol=1e-2, rtol=1e-4)


def test_proper_dihedral_and_improper_forces_match_finite_difference() -> None:
    topo, coords, _ = smiles_to_topology("CC(=O)O", constrain_h_bonds=False, seed=33)
    rng = np.random.default_rng(102)
    pos = coords + 1.5 + rng.normal(0.0, 0.015, size=coords.shape)
    box = SimulationBox.orthorhombic(3.0, 3.0, 3.0)
    ff = ForceField(
        topo,
        ForceFieldConfig(cutoff=1.0, switch_distance=0.8, electrostatics="reaction_field", dispersion_correction=False),
    )
    _assert_forces_match_fd(ff, pos, box, atol=2e-2, rtol=2e-4)

    # Standalone improper torsion check
    atoms = [AtomSpec(i, f"A{i}", "C", "IMP", 1, 12.0, 0.0, 0.34, 0.0) for i in range(4)]
    imp_topo = Topology(atoms=atoms, impropers=[ImproperTerm(0, 1, 2, 3, omega0=0.0, k_omega=150.0)])
    imp_pos = np.array([[0.0, 0.0, 0.05], [0.14, 0.0, 0.0], [-0.07, 0.12, 0.0], [-0.07, -0.12, 0.0]]) + 1.5
    ff_imp = ForceField(imp_topo, ForceFieldConfig(cutoff=0.9, electrostatics="cutoff", dispersion_correction=False))
    _assert_forces_match_fd(ff_imp, imp_pos, box, atol=1e-3, rtol=1e-5)


def test_softcore_alchemical_forces_and_dudlambda() -> None:
    topo, coords, box = build_solvated_ligand_box("CO", box_length_nm=2.2, n_waters=4, constrain_solvent=False, seed=9)
    # Remove solute H constraints so all coordinates are unconstrained for FD
    topo_free = Topology(
        atoms=topo.atoms,
        bonds=topo.bonds,
        angles=topo.angles,
        dihedrals=topo.dihedrals,
        impropers=topo.impropers,
        name="free_test",
    )
    ff = ForceField(topo_free, ForceFieldConfig(cutoff=0.9, switch_distance=0.7, electrostatics="reaction_field"))
    lam = AlchemicalLambda(lambda_elec=0.45, lambda_vdw=0.6)
    _assert_forces_match_fd(ff, coords, box, alchemical=lam, atol=3e-2, rtol=3e-4)

    # Verify analytical dU/dlambda_vdw and dU/dlambda_elec against finite difference in lambda
    eps_l = 1e-6
    eb_vp, _ = ff.evaluate(coords, box, AlchemicalLambda(lambda_elec=0.45, lambda_vdw=0.6 + eps_l), force_rebuild=True)
    eb_vm, _ = ff.evaluate(coords, box, AlchemicalLambda(lambda_elec=0.45, lambda_vdw=0.6 - eps_l), force_rebuild=True)
    fd_vdw = (eb_vp.potential - eb_vm.potential) / (2.0 * eps_l)

    eb_ep, _ = ff.evaluate(coords, box, AlchemicalLambda(lambda_elec=0.45 + eps_l, lambda_vdw=0.6), force_rebuild=True)
    eb_em, _ = ff.evaluate(coords, box, AlchemicalLambda(lambda_elec=0.45 - eps_l, lambda_vdw=0.6), force_rebuild=True)
    fd_elec = (eb_ep.potential - eb_em.potential) / (2.0 * eps_l)

    eb_mid, _ = ff.evaluate(coords, box, lam, force_rebuild=True)
    assert pytest.approx(eb_mid.dU_dlambda_vdw, rel=1e-4, abs=1e-3) == fd_vdw
    assert pytest.approx(eb_mid.dU_dlambda_elec, rel=1e-4, abs=1e-3) == fd_elec


def test_com_restraint_forces_match_finite_difference() -> None:
    atoms = [AtomSpec(i, f"A{i}", "C", "RES", 1, 12.0 + i, 0.0, 0.3, 0.0) for i in range(4)]
    topo = Topology(atoms=atoms)
    box = SimulationBox.orthorhombic(3.0, 3.0, 3.0)
    ff = ForceField(topo, ForceFieldConfig(cutoff=0.9, electrostatics="cutoff", dispersion_correction=False))
    ff.add_com_restraint(HarmonicCOMRestraint((0, 1), (2, 3), r0=0.45, k_restraint=2000.0))
    pos = np.array([[1.0, 1.0, 1.0], [1.15, 1.05, 1.0], [1.55, 1.2, 1.1], [1.7, 1.15, 1.05]])
    _assert_forces_match_fd(ff, pos, box, atol=1e-3, rtol=1e-5)
