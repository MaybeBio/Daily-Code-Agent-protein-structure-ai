"""Structure input from an openmm.app.Topology, a PDB file, or a PDBx/mmCIF file.

1. Equivalence: an openmm.app.Topology built from a reference LAMMPS data file gives exactly the parameterized topology of the validated data-file route (topology_from_lammps_data).
2. Files: a mixture built with RDKit and written as PDB (with CONECT records) and as PDBx/mmCIF gives the same atom types, charges, and parameters as the RDKit molecules themselves.
3. Molecules split across the box are made whole with a warning; unsupported input raises.
pcff.frc and pcff_templates.dat are read from the EMC installation (EMC_ROOT); the tests are skipped without them.
"""

import numpy as np
import openmm
import openmm.app
import openmm.unit
import pytest
from rdkit import Chem
from rdkit.Chem import AllChem

from openmm_pcff import system_from_pdb, topology_from_openmm_topology, topology_from_lammps_data, type_and_parameterize
from openmm_pcff.atomtyping import assign_atom_types, element_from_mass, read_templates
from openmm_pcff.lammps_io import read_data_file
from validation.comparison import parameter_differences
from validation.reference_systems import FRC_PATH, PCFF_FILES_AVAILABLE, TEMPLATES_PATH, case_files, reference_molecules


pytestmark = pytest.mark.skipif(
    not PCFF_FILES_AVAILABLE,
    reason="pcff.frc and pcff_templates.dat are read from EMC_ROOT/field/cff/pcff; set EMC_ROOT to the EMC installation directory",
)

PAIR_SETTINGS = {"lj_cutoff_angstrom": 9.5, "coulomb_cutoff_angstrom": 9.5, "lj_tail_correction": True}

EQUIVALENCE_SYSTEMS = ["butane", "polyethylene", "benzene", "methyl_acetate", "pmma", "probe_mixture_a"]

# Mixture for the file tests: molecules in this order, side by side along x in a cubic box.
MIXTURE_SMILES = ["CCO", "c1ccccc1", "CC(=O)OC", "CCO"]
MIXTURE_SPACING_ANGSTROM = 7.0
MIXTURE_BOX_ANGSTROM = 30.0

# PDB coordinates have 3 decimals.
PDB_POSITION_TOLERANCE_ANGSTROM = 6e-4


# --- 1. openmm.app.Topology against the validated LAMMPS data-file route ---------------------------------------------


def openmm_topology_from_lammps_data(data_path) -> tuple[openmm.app.Topology, openmm.unit.Quantity]:
    """Elements, bonds, box, and exact positions of a LAMMPS data file as an openmm.app.Topology (one residue for all atoms)."""
    data = read_data_file(data_path)

    omm_topology = openmm.app.Topology()
    residue = omm_topology.addResidue("ALL", omm_topology.addChain())

    atoms = []
    for atom_type in data["atom_types"]:
        element = openmm.app.Element.getBySymbol(element_from_mass(data["type_masses_amu"][atom_type]))
        atoms.append(omm_topology.addAtom(element.symbol, element, residue))

    for bond_type, (atom_i, atom_j) in data["bonds"]:
        omm_topology.addBond(atoms[atom_i], atoms[atom_j])

    lx, ly, lz = data["box_lengths_angstrom"]
    omm_topology.setPeriodicBoxVectors([openmm.Vec3(lx, 0, 0), openmm.Vec3(0, ly, 0), openmm.Vec3(0, 0, lz)] * openmm.unit.angstrom)

    return omm_topology, data["positions_angstrom"] * openmm.unit.angstrom


@pytest.mark.parametrize("system_name", EQUIVALENCE_SYSTEMS)
def test_openmm_topology_matches_data_file_route(system_name):
    data_path = case_files(system_name, "periodic_nocoul")["data"]
    if not data_path.exists():
        pytest.skip(f"reference data for {system_name} not generated (see README)")

    molecules = reference_molecules(system_name)
    reference, reference_positions, _ = topology_from_lammps_data(data_path, molecules, FRC_PATH, TEMPLATES_PATH, **PAIR_SETTINGS)

    omm_topology, positions = openmm_topology_from_lammps_data(data_path)
    topology, positions_angstrom, _ = topology_from_openmm_topology(omm_topology, positions, molecules, FRC_PATH, TEMPLATES_PATH, **PAIR_SETTINGS)

    # Same inputs to typing and assignment, so the terms must be identical, not just close.
    assert topology.atom_type_names == reference.atom_type_names
    assert topology.charges_e == reference.charges_e
    assert topology.bonds == reference.bonds
    assert topology.angles == reference.angles
    assert topology.dihedrals == reference.dihedrals
    assert topology.impropers == reference.impropers
    assert np.allclose(topology.box_lengths_angstrom, reference.box_lengths_angstrom, rtol=1e-12, atol=0.0)
    assert np.allclose(positions_angstrom, reference_positions, rtol=1e-12, atol=1e-12)


# --- 2. PDB and PDBx/mmCIF files -------------------------------------------------------------------------------------


def mixture_molecules() -> list[Chem.Mol]:
    """Embedded RDKit molecules (explicit hydrogens) of MIXTURE_SMILES, placed side by side inside the box."""
    molecules = []

    for index, smiles in enumerate(MIXTURE_SMILES):
        molecule = Chem.AddHs(Chem.MolFromSmiles(smiles))
        AllChem.EmbedMolecule(molecule, randomSeed=2026)

        conformer = molecule.GetConformer()
        for atom in range(molecule.GetNumAtoms()):
            position = conformer.GetAtomPosition(atom)
            conformer.SetAtomPosition(atom, (position.x + 4.0 + MIXTURE_SPACING_ANGSTROM * index, position.y + 15.0, position.z + 15.0))

        molecules.append(molecule)

    return molecules


def combined_molecule(molecules: list[Chem.Mol]) -> Chem.Mol:
    combined = molecules[0]
    for molecule in molecules[1:]:
        combined = Chem.CombineMols(combined, molecule)
    return combined


def write_mixture_pdb(path, with_box: bool = True, with_conect: bool = True) -> Chem.Mol:
    """Write the mixture as PDB (RDKit writes a CONECT record for every bond) and return the combined RDKit molecule."""
    combined = combined_molecule(mixture_molecules())
    lines = Chem.MolToPDBBlock(combined).splitlines()

    if not with_conect:
        lines = [line for line in lines if not line.startswith("CONECT")]

    if with_box:
        box = MIXTURE_BOX_ANGSTROM
        lines.insert(0, f"CRYST1{box:9.3f}{box:9.3f}{box:9.3f}  90.00  90.00  90.00 P 1           1")

    path.write_text("\n".join(lines) + "\n")
    return combined


def unique_mixture_molecules() -> list[Chem.Mol]:
    return [Chem.AddHs(Chem.MolFromSmiles(smiles)) for smiles in dict.fromkeys(MIXTURE_SMILES)]


def build_from_file(path, **options):
    return system_from_pdb(
        path,
        unique_mixture_molecules(),
        FRC_PATH,
        TEMPLATES_PATH,
        **PAIR_SETTINGS,
        **{"periodic": True, "coulomb_method": "pme", "ewald_error_tolerance": 5e-4, **options},
    )


def test_pdb_and_mmcif_match_rdkit_molecules(tmp_path):
    pdb_path = tmp_path / "mixture.pdb"
    combined = write_mixture_pdb(pdb_path)

    # Reference: the combined RDKit molecule itself (elements, bonds, and exact positions in memory).
    elements = [atom.GetSymbol() for atom in combined.GetAtoms()]
    bonds = [(bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()) for bond in combined.GetBonds()]
    box = (MIXTURE_BOX_ANGSTROM,) * 3
    reference, _ = type_and_parameterize(elements, bonds, box, unique_mixture_molecules(), FRC_PATH, TEMPLATES_PATH, **PAIR_SETTINGS)
    reference_positions = combined.GetConformer().GetPositions()

    # Independent check of the atom types: type every molecule on its own and concatenate in file order.
    typing_rules = read_templates(TEMPLATES_PATH)
    expected_types = [atom_type for molecule in mixture_molecules() for atom_type in assign_atom_types(molecule, typing_rules)]
    assert reference.atom_type_names == expected_types

    pdb = openmm.app.PDBFile(str(pdb_path))
    mmcif_path = tmp_path / "mixture.cif"
    with open(mmcif_path, "w") as mmcif_file:
        openmm.app.PDBxFile.writeFile(pdb.topology, pdb.positions, mmcif_file)

    for path in [pdb_path, mmcif_path]:
        structure_file = openmm.app.PDBFile(str(path)) if path.suffix == ".pdb" else openmm.app.PDBxFile(str(path))
        topology, positions_angstrom, _ = topology_from_openmm_topology(
            structure_file.topology, structure_file.positions, unique_mixture_molecules(), FRC_PATH, TEMPLATES_PATH, **PAIR_SETTINGS
        )

        assert topology.atom_type_names == reference.atom_type_names, path.name
        assert parameter_differences(topology, reference) == [], path.name
        assert np.abs(positions_angstrom - reference_positions).max() < PDB_POSITION_TOLERANCE_ANGSTROM, path.name

        # The public file entry point builds a System with one particle per atom and returns the file's topology.
        system, returned_topology, positions_nm, report = build_from_file(path)
        assert system.getNumParticles() == combined.GetNumAtoms()
        assert returned_topology.getNumAtoms() == combined.GetNumAtoms()
        assert positions_nm.shape == (combined.GetNumAtoms(), 3)


# --- 3. Making molecules whole, and unsupported input ----------------------------------------------------------------


def test_split_molecule_is_made_whole_with_warning(tmp_path):
    pdb_path = tmp_path / "mixture.pdb"
    write_mixture_pdb(pdb_path)
    pdb = openmm.app.PDBFile(str(pdb_path))

    original_angstrom = np.array(pdb.positions.value_in_unit(openmm.unit.angstrom))

    # Move the first atom (a carbon of the first ethanol) by one box length, splitting that molecule across the boundary.
    wrapped_angstrom = original_angstrom.copy()
    wrapped_angstrom[0, 0] += MIXTURE_BOX_ANGSTROM

    with pytest.warns(UserWarning, match="made whole|make them whole"):
        _, positions_angstrom, _ = topology_from_openmm_topology(
            pdb.topology, wrapped_angstrom * openmm.unit.angstrom, unique_mixture_molecules(), FRC_PATH, TEMPLATES_PATH, **PAIR_SETTINGS
        )

    # Atom 0 is the start of the walk, so its bonded neighbours are moved next to it; the molecule is whole again, one box length away.
    first_molecule = slice(0, mixture_molecules()[0].GetNumAtoms())
    shift = positions_angstrom[first_molecule] - original_angstrom[first_molecule]
    assert np.allclose(shift, [MIXTURE_BOX_ANGSTROM, 0.0, 0.0], atol=1e-9)
    assert np.allclose(positions_angstrom[first_molecule.stop :], original_angstrom[first_molecule.stop :], atol=1e-9)


def test_missing_conect_records_raise(tmp_path):
    pdb_path = tmp_path / "no_conect.pdb"
    write_mixture_pdb(pdb_path, with_conect=False)

    with pytest.raises(ValueError, match="matches none of the given molecules"):
        build_from_file(pdb_path)


def test_periodic_without_box_raises(tmp_path):
    pdb_path = tmp_path / "no_box.pdb"
    write_mixture_pdb(pdb_path, with_box=False)

    with pytest.raises(ValueError, match="needs a box"):
        build_from_file(pdb_path)


def test_triclinic_box_raises(tmp_path):
    pdb_path = tmp_path / "mixture.pdb"
    write_mixture_pdb(pdb_path)
    pdb = openmm.app.PDBFile(str(pdb_path))

    box = MIXTURE_BOX_ANGSTROM
    pdb.topology.setPeriodicBoxVectors([openmm.Vec3(box, 0, 0), openmm.Vec3(5.0, box, 0), openmm.Vec3(0, 0, box)] * openmm.unit.angstrom)

    with pytest.raises(ValueError, match="orthorhombic"):
        topology_from_openmm_topology(pdb.topology, pdb.positions, unique_mixture_molecules(), FRC_PATH, TEMPLATES_PATH, **PAIR_SETTINGS)


def test_positions_without_units_raise(tmp_path):
    pdb_path = tmp_path / "mixture.pdb"
    write_mixture_pdb(pdb_path)
    pdb = openmm.app.PDBFile(str(pdb_path))

    positions_without_units = np.array(pdb.positions.value_in_unit(openmm.unit.nanometer))

    with pytest.raises(TypeError, match="Quantity"):
        topology_from_openmm_topology(pdb.topology, positions_without_units, unique_mixture_molecules(), FRC_PATH, TEMPLATES_PATH, **PAIR_SETTINGS)
