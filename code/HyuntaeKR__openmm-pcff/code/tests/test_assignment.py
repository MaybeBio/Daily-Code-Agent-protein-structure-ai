"""Acceptance tests: openmm_pcff typing and parameter assignment against EMC, and the resulting energies against LAMMPS.

For every reference system (butane, polyethylene, and the systems of validation.reference_systems.EMC_SYSTEMS):
- generated angles, dihedrals, impropers are the same sets as in EMC's data file;
- atom types from pcff_templates.dat equal EMC's types;
- parameters from pcff.frc equal EMC's .params, term by term (with EMC's types, and with openmm_pcff's types);
- the OpenMM system built from openmm_pcff's types and parameters reproduces the LAMMPS single points (which use EMC's parameters).
The rule-specific tests at the end pin down the lookup rules inferred from EMC.
pcff.frc and pcff_templates.dat are read from the EMC installation (EMC_ROOT); the tests are skipped without them.
"""

import functools

import numpy as np
import pytest
from rdkit import Chem

from openmm_pcff.assign import load_force_field, parameterize
from openmm_pcff.atomtyping import assign_atom_types, assign_system_atom_types, element_from_mass, hybridization_mismatches, read_templates
from openmm_pcff.lammps_io import read_data_file, read_emc_lammps
from openmm_pcff.topology import bonded_neighbours, generate_angles, generate_dihedrals, generate_impropers
from validation.comparison import compare_case, openmm_pcff_topology_like, parameter_differences
from validation.reference_systems import (
    EMC_SYSTEMS,
    FRC_PATH,
    PCFF_FILES_AVAILABLE,
    SYSTEMS,
    TEMPLATES_PATH,
    case_files,
    reference_molecules,
)


pytestmark = pytest.mark.skipif(
    not PCFF_FILES_AVAILABLE,
    reason="pcff.frc and pcff_templates.dat are read from EMC_ROOT/field/cff/pcff; set EMC_ROOT to the EMC installation directory",
)

ALL_SYSTEMS = SYSTEMS + list(EMC_SYSTEMS)

# Same tolerances as tests/test_lammps_reference.py.
ENERGY_RELATIVE_TOLERANCE = 1e-6
FORCE_ABSOLUTE_TOLERANCE = 1e-4
COULOMB_CORRECTED_RELATIVE_TOLERANCE = 1e-6

BONDED_KEYWORDS = ["ebond", "eangle", "edihed", "eimp"]


@functools.cache
def force_field():
    return load_force_field(FRC_PATH)


@functools.cache
def typing_rules():
    return read_templates(TEMPLATES_PATH)


@functools.cache
def emc_topology(system_name: str):
    files = case_files(system_name, "periodic_nocoul")
    topology, positions = read_emc_lammps(files["data"], files["params"])
    return topology


@functools.cache
def cached_comparison(system_name: str, case: str) -> dict:
    return compare_case(system_name, case, parameter_source="openmm_pcff")


def energies_agree(openmm_energy: float, lammps_energy: float, relative_tolerance: float) -> bool:
    # A term without any interaction (water: no dihedrals; one isolated water: no nonbonded pairs) must be exactly zero in both codes.
    if lammps_energy == 0.0:
        return openmm_energy == 0.0

    return abs(openmm_energy - lammps_energy) / abs(lammps_energy) < relative_tolerance


def canonical_terms(atoms_list, kind):
    if kind == "angles":
        return sorted(min(atoms, atoms[::-1]) for atoms in atoms_list)
    if kind == "dihedrals":
        return sorted(min(atoms, atoms[::-1]) for atoms in atoms_list)
    # Impropers: central atom (second) and the set of outer atoms.
    return sorted((atoms[1], tuple(sorted((atoms[0], atoms[2], atoms[3])))) for atoms in atoms_list)


# --- Against EMC: terms, types, parameters -----------------------------------------------------------------------


@pytest.mark.parametrize("system_name", ALL_SYSTEMS)
def test_generated_terms_match_emc(system_name):
    data = read_data_file(case_files(system_name, "periodic_nocoul")["data"])
    bonds = [atoms for bond_type, atoms in data["bonds"]]
    neighbours = bonded_neighbours(len(data["atom_types"]), bonds)

    generated = {
        "angles": generate_angles(neighbours),
        "dihedrals": generate_dihedrals(neighbours, bonds),
        "impropers": generate_impropers(neighbours),
    }

    for kind, terms in generated.items():
        emc_terms = [atoms for term_type, atoms in data[kind]]
        assert canonical_terms(terms, kind) == canonical_terms(emc_terms, kind), kind


@pytest.mark.parametrize("system_name", ALL_SYSTEMS)
def test_atom_types_match_emc(system_name):
    data = read_data_file(case_files(system_name, "periodic_nocoul")["data"])
    elements = [element_from_mass(data["type_masses_amu"][atom_type]) for atom_type in data["atom_types"]]
    bonds = [atoms for bond_type, atoms in data["bonds"]]

    openmm_pcff_types = assign_system_atom_types(elements, bonds, reference_molecules(system_name), typing_rules())
    emc_types = [data["type_names"][atom_type] for atom_type in data["atom_types"]]

    assert openmm_pcff_types == emc_types


@pytest.mark.parametrize("system_name", ALL_SYSTEMS)
def test_parameter_lookup_with_emc_types_matches_emc(system_name):
    # Parameter assignment alone: EMC's own atom types as input.
    reference = emc_topology(system_name)

    topology, report = parameterize(
        reference.atom_type_names,
        [bond.atoms for bond in reference.bonds],
        force_field(),
        reference.box_lengths_angstrom,
        reference.lj_cutoff_angstrom,
        reference.coulomb_cutoff_angstrom,
        reference.lj_tail_correction,
    )

    assert parameter_differences(topology, reference) == []


@pytest.mark.parametrize("system_name", ALL_SYSTEMS)
def test_full_pipeline_matches_emc_parameters(system_name):
    # Typing and parameter assignment together, from the structure only.
    reference = emc_topology(system_name)
    topology, report = openmm_pcff_topology_like(system_name, case_files(system_name, "periodic_nocoul")["data"], reference)

    assert parameter_differences(topology, reference) == []


# --- Against LAMMPS: energies and forces of the openmm_pcff-parameterized system -------------------------------------------


@pytest.mark.parametrize("system_name", ALL_SYSTEMS)
@pytest.mark.parametrize("case", ["isolated", "periodic_nocoul", "periodic_ewald"])
def test_bonded_energies_and_forces(system_name, case):
    comparison = cached_comparison(system_name, case)

    for keyword in BONDED_KEYWORDS:
        lammps_energy, openmm_energy = comparison["keyword_energies"][keyword]

        assert energies_agree(openmm_energy, lammps_energy, ENERGY_RELATIVE_TOLERANCE), keyword

    largest_force_difference = np.abs(comparison["openmm_forces"] - comparison["lammps_forces"]).max()
    assert largest_force_difference < FORCE_ABSOLUTE_TOLERANCE


@pytest.mark.parametrize("system_name", ALL_SYSTEMS)
def test_isolated_nonbonded_energies(system_name):
    comparison = cached_comparison(system_name, "isolated")

    for keyword in ["evdwl", "ecoul+elong"]:
        lammps_energy, openmm_energy = comparison["keyword_energies"][keyword]
        assert energies_agree(openmm_energy, lammps_energy, ENERGY_RELATIVE_TOLERANCE), keyword


@pytest.mark.parametrize("system_name", ALL_SYSTEMS)
def test_periodic_nonbonded_energies(system_name):
    comparison = cached_comparison(system_name, "periodic_ewald")
    lammps_thermo = comparison["lammps_thermo"]

    # LJ pair sum within the cutoff; the tail corrections differ by the documented O(1/N) pair-counting difference.
    lammps_lj, openmm_lj = comparison["keyword_energies"]["evdwl"]
    lammps_pair = lammps_lj - lammps_thermo["etail"]
    openmm_pair = openmm_lj - comparison["lj_tail"]["openmm_measured"]
    assert energies_agree(openmm_pair, lammps_pair, ENERGY_RELATIVE_TOLERANCE)

    # LAMMPS's approximate erfc shifts its Coulomb energy by a predictable amount (up to 7.6e-5 relative for water, with large charges);
    # once that is removed, OpenMM and LAMMPS agree to 1e-6 (largest observed 4.4e-7, polystyrene).
    lammps_coulomb, openmm_coulomb = comparison["keyword_energies"]["ecoul+elong"]
    assert energies_agree(openmm_coulomb + comparison["lammps_erfc_error"], lammps_coulomb, COULOMB_CORRECTED_RELATIVE_TOLERANCE)


# --- Rules inferred from EMC ----------------------------------------------------------------------------------------


def parameterize_smiles(smiles: str):
    molecule = Chem.AddHs(Chem.MolFromSmiles(smiles))
    atom_types = assign_atom_types(molecule, typing_rules())
    bonds = [(bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()) for bond in molecule.GetBonds()]

    topology, report = parameterize(atom_types, bonds, force_field(), (30.0, 30.0, 30.0), 9.5, 9.5, True)
    return topology, report


def angle_quartic(topology, center_type: str, end_types: set) -> set:
    found = set()
    for angle in topology.angles:
        types = [topology.atom_type_names[atom] for atom in angle.atoms]
        if types[1] == center_type and {types[0], types[2]} == end_types:
            found.add(angle.quartic)
    return found


def test_automatic_angle_uses_sorted_end_types():
    # cl-cp-cp: ends cl_ and c_ sort as (c_, cp_, cl_); '*7 cp_ c_' does not fit this orientation, so '* cp_ *' (65) applies.
    chlorobenzene, report = parameterize_smiles("Clc1ccccc1")
    assert angle_quartic(chlorobenzene, "cp", {"cl", "cp"}) == {(120.0, 65.0, 0.0, 0.0)}

    # br-cp-cp: ends br_ and c_ sort as (br_, cp_, c_), so the numbered entry '*7 cp_ c_' (80) applies.
    bromobenzene, report = parameterize_smiles("Brc1ccccc1")
    assert angle_quartic(bromobenzene, "cp", {"br", "cp"}) == {(120.0, 80.0, 0.0, 0.0)}


def test_automatic_torsion_phase():
    # torsion_1 '* cp_ cp_ *' is Kphi = 3, n = 2, phi0 = 180 in E = K [1 + cos(n phi - phi0)]; LAMMPS gets K2 = 3, phi2 = 0.
    chlorobenzene, report = parameterize_smiles("Clc1ccccc1")
    torsions = {dihedral.torsion for dihedral in chlorobenzene.dihedrals if chlorobenzene.atom_type_names[dihedral.atoms[0]] == "cl"}
    assert torsions == {(0.0, 0.0, 3.0, 0.0, 0.0, 0.0)}


def test_missing_wilson_is_zero_even_with_automatic_entry():
    # '* cp_ * *' (K = 10) exists in wilson_out_of_plane cff91_auto, but EMC leaves the ipso carbon of chlorobenzene at K = 0.
    chlorobenzene, report = parameterize_smiles("Clc1ccccc1")
    ipso_wilson = {
        improper.wilson
        for improper in chlorobenzene.impropers
        if "cl" in [chlorobenzene.atom_type_names[atom] for atom in improper.atoms]
    }
    assert ipso_wilson == {(0.0, 0.0)}
    assert ("cp", ("cl", "cp", "cp")) in report["zero_wilson"]


def test_explicit_wildcard_torsion():
    # '* c_1 o_2 *' in torsion_3 applies before the automatic torsions (methyl methacrylate, c=2-c_1-o_2-c).
    mma, report = parameterize_smiles("CC(=C)C(=O)OC")
    torsions = set()
    for dihedral in mma.dihedrals:
        types = [mma.atom_type_names[atom] for atom in dihedral.atoms]
        if types[1:3] in (["c_1", "o_2"], ["o_2", "c_1"]) and "c=2" in types:
            torsions.add(dihedral.torsion)
    assert torsions == {(-2.5594, 0.0, 2.2013, 0.0, 0.0325, 0.0)}


def test_alkane_carbons_are_generic_c():
    # Only the first top-level 'c' node of the precedence tree is reached, so c2 and c3 are never assigned.
    molecule = Chem.AddHs(Chem.MolFromSmiles("CCCC"))
    assert set(assign_atom_types(molecule, typing_rules())) == {"c", "hc"}


def test_amide_nitrogen_differs_from_emc():
    # Documented deviation: with backtracking, the n_2 template matches the amide N of N-methylacetamide.
    # EMC's greedy matcher misses it, types the N as na, and then stops with a missing c_1-na bond increment.
    molecule = Chem.AddHs(Chem.MolFromSmiles("CC(=O)NC"))
    atom_types = assign_atom_types(molecule, typing_rules())
    nitrogen = [atom.GetIdx() for atom in molecule.GetAtoms() if atom.GetSymbol() == "N"][0]
    assert atom_types[nitrogen] == "n_2"


def test_hybridization_mismatch_is_reported():
    # Typing skips hybridization tests as EMC does, so the sp central carbon of allene gets the sp3 type 'c'; the mismatch is reported.
    allene = Chem.AddHs(Chem.MolFromSmiles("C=C=C"))
    assert hybridization_mismatches(allene, typing_rules()) == [(1, "c", "SP")]

    propane = Chem.AddHs(Chem.MolFromSmiles("CCC"))
    assert hybridization_mismatches(propane, typing_rules()) == []


@pytest.mark.parametrize("smiles", ["CS(=O)(=O)C", "COP(=O)(OC)OC", "O=C=O"])
def test_missing_bond_increments_raise(smiles):
    # EMC stops on these too (missing bond increments c-sf, p=-o-, c-o=).
    with pytest.raises(ValueError, match="bond_increment"):
        parameterize_smiles(smiles)
