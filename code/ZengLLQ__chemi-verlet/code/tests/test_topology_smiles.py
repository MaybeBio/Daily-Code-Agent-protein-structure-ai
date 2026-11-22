"""Tests for SMILES parsing, SSSR ring perception, Gasteiger charges, and builders."""

from __future__ import annotations

import numpy as np
import pytest

from chemi_verlet.topology import (
    build_alkane_chain,
    build_host_guest_complex,
    build_solvated_ligand_box,
    parse_smiles,
    read_pdb_coordinates,
    smiles_to_topology,
    write_gro,
    write_pdb,
)


def test_smiles_sssr_and_gasteiger_charge_conservation() -> None:
    # Aspirin: 1 aromatic 6-membered ring
    asp = parse_smiles("CC(=O)Oc1ccccc1C(=O)O")
    assert len(asp.rings) == 1
    assert len(asp.rings[0]) == 6
    assert asp.rotatable_bond_count() >= 2
    total_q = sum(a.gasteiger_charge for a in asp.atoms)
    assert pytest.approx(total_q, abs=1e-9) == 0.0

    # Naphthalene: 2 rings in SSSR
    naph = parse_smiles("c1ccc2ccccc2c1")
    assert len(naph.rings) == 2

    # Charged ammonium acetate zwitterion / bracket formal charge
    gly_ion = parse_smiles("[NH3+]CC(=O)[O-]")
    assert pytest.approx(sum(a.gasteiger_charge for a in gly_ion.atoms), abs=1e-9) == 0.0
    cat = parse_smiles("C[NH3+]")
    assert pytest.approx(sum(a.gasteiger_charge for a in cat.atoms), abs=1e-9) == 1.0


def test_smiles_to_topology_halogen_and_exclusions() -> None:
    topo, coords, graph = smiles_to_topology("Clc1ccc(Br)cc1", name="bromochlorobenzene")
    elems = [a.element for a in topo.atoms]
    assert "Cl" in elems and "Br" in elems
    assert coords.shape == (topo.n_atoms, 3)
    assert len(topo.dihedrals) > 0
    assert len(topo.impropers) > 0
    # 1-2/1-3 exclusions should include atom itself
    for idx in range(topo.n_atoms):
        assert idx in topo.exclusions[idx]
    assert len(graph.rings) == 1


def test_pdb_and_gro_roundtrip() -> None:
    topo, coords, box = build_solvated_ligand_box("CCO", box_length_nm=2.2, n_waters=6, seed=7)
    pdb_str = write_pdb(topo, coords, box)
    parsed_coords, parsed_box = read_pdb_coordinates(pdb_str)
    assert parsed_box is not None
    np.testing.assert_allclose(parsed_coords, coords, atol=1e-3)
    np.testing.assert_allclose(parsed_box.lengths(), box.lengths(), atol=1e-3)

    gro_str = write_gro(topo, coords, box)
    lines = gro_str.strip().splitlines()
    assert int(lines[1].strip()) == topo.n_atoms


def test_builders_produce_clash_free_systems() -> None:
    alk_topo, alk_coords = build_alkane_chain(5)
    assert alk_topo.n_atoms == 5
    assert len(alk_topo.rb_dihedrals) == 2
    assert alk_coords.shape == (5, 3)

    comp_topo, comp_coords, comp_box, rec_idx, lig_idx = build_host_guest_complex("c1ccccc1O", seed=19)
    assert len(rec_idx) == 16
    assert len(lig_idx) > 6
    assert comp_topo.n_atoms == len(rec_idx) + len(lig_idx)
    assert comp_coords.shape == (comp_topo.n_atoms, 3)
    assert comp_box.volume > 10.0
