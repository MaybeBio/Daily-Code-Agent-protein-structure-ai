"""PCFF (class II) force field for OpenMM.

Builds an openmm.System whose energies and forces reproduce LAMMPS class2 styles as parameterized by EMC.
Routes (see README.md):
- system_from_emc_lammps_files: atom types and parameters read from EMC's LAMMPS .data/.params files.
- system_from_pdb, system_from_openmm_topology, system_from_lammps_data: atom types and parameters assigned by openmm_pcff from pcff.frc and pcff_templates.dat,
  for a structure given as a PDB or PDBx/mmCIF file, as an openmm.app.Topology with positions, or as a LAMMPS data file.
"""

from pathlib import Path

import numpy as np
import openmm
import openmm.app
from rdkit import Chem

from openmm_pcff.assign import load_force_field, parameterize
from openmm_pcff.atomtyping import assign_system_atom_types, element_from_mass, hybridization_mismatches, read_templates
from openmm_pcff.builder import build_system
from openmm_pcff.lammps_io import read_data_file, read_emc_lammps
from openmm_pcff.ptop import ParameterizedTopology
from openmm_pcff.structure import make_molecules_whole, structure_from_openmm_topology
from openmm_pcff.units import NM_PER_ANGSTROM


PDB_SUFFIXES = [".pdb", ".ent"]
PDBX_SUFFIXES = [".cif", ".mmcif", ".pdbx"]


def system_from_emc_lammps_files(
    data_path: Path,
    params_path: Path,
    periodic: bool,
    coulomb_method: str | None,
    ewald_error_tolerance: float | None = None,
    merge_bonded: bool = True,
) -> tuple[openmm.System, np.ndarray]:
    """
    Read an EMC LAMMPS .data/.params pair and return (OpenMM System, positions in nm).
    Positions are the coordinates of the data file, with molecules made whole if they are split across the box (with a warning).
    See openmm_pcff.builder.build_system for the meaning of the options.
    """
    topology, positions_angstrom = read_emc_lammps(Path(data_path), Path(params_path))

    bonds = [bond.atoms for bond in topology.bonds]
    positions_angstrom = make_molecules_whole(positions_angstrom, bonds, topology.box_lengths_angstrom)

    system = build_system(
        topology,
        periodic=periodic,
        coulomb_method=coulomb_method,
        ewald_error_tolerance=ewald_error_tolerance,
        merge_bonded=merge_bonded,
    )

    return system, positions_angstrom * NM_PER_ANGSTROM


def type_and_parameterize(
    elements: list[str],
    bonds: list[tuple[int, int]],
    box_lengths_angstrom: tuple[float, float, float] | None,
    molecules: list[Chem.Mol],
    frc_path: Path,
    templates_path: Path,
    lj_cutoff_angstrom: float,
    coulomb_cutoff_angstrom: float | None,
    lj_tail_correction: bool,
) -> tuple[ParameterizedTopology, dict]:
    """
    Type the atoms of a structure (elements and 0-based bonds) and assign PCFF parameters; returns (topology, report).

    molecules are RDKit molecules with explicit hydrogens (e.g. Chem.AddHs(Chem.MolFromSmiles(...))), one per distinct molecule;
    every molecule of the structure must be the same graph as one of them, and they supply the bond orders, aromaticity, and formal charges used by the typing.
    Atomic charges come from the PCFF bond increments, not from the molecules.
    The pair settings (cutoffs, tail correction) are simulation choices and have no defaults.
    The report lists the automatic parameters and the zero Wilson terms (see openmm_pcff.assign.parameterize),
    and under "hybridization_mismatches" the (molecule SMILES, atom index, type, RDKit hybridization) of every atom whose type matches only because hybridization tests are skipped (see openmm_pcff.atomtyping.hybridization_mismatches).
    """
    typing_rules = read_templates(Path(templates_path))
    atom_types = assign_system_atom_types(elements, bonds, molecules, typing_rules)

    topology, report = parameterize(
        atom_types,
        bonds,
        load_force_field(Path(frc_path)),
        box_lengths_angstrom=box_lengths_angstrom,
        lj_cutoff_angstrom=lj_cutoff_angstrom,
        coulomb_cutoff_angstrom=coulomb_cutoff_angstrom,
        lj_tail_correction=lj_tail_correction,
    )

    # Typing skips the templates' hybridization tests, as EMC does; list the atoms that would fail them.
    report["hybridization_mismatches"] = []
    for molecule in molecules:
        smiles = Chem.MolToSmiles(Chem.RemoveHs(molecule))
        for atom_index, atom_type, hybridization in hybridization_mismatches(molecule, typing_rules):
            report["hybridization_mismatches"].append((smiles, atom_index, atom_type, hybridization))

    return topology, report


def topology_from_lammps_data(
    data_path: Path,
    molecules: list[Chem.Mol],
    frc_path: Path,
    templates_path: Path,
    lj_cutoff_angstrom: float,
    coulomb_cutoff_angstrom: float | None,
    lj_tail_correction: bool,
) -> tuple[ParameterizedTopology, np.ndarray, dict]:
    """
    Type and parameterize the structure of a LAMMPS data file; returns (topology, positions in Angstrom, report).

    Only the structure is taken from the data file: elements (from the masses), bonds, box, and positions.
    Atom types, charges, and all coefficients in the file are ignored.
    Molecules split across the box are made whole (with a warning).
    See type_and_parameterize for molecules, the pair settings, and the report.
    """
    data = read_data_file(Path(data_path))

    elements = [element_from_mass(data["type_masses_amu"][atom_type]) for atom_type in data["atom_types"]]
    bonds = [atoms for bond_type, atoms in data["bonds"]]
    positions_angstrom = make_molecules_whole(data["positions_angstrom"], bonds, data["box_lengths_angstrom"])

    topology, report = type_and_parameterize(
        elements,
        bonds,
        data["box_lengths_angstrom"],
        molecules,
        frc_path,
        templates_path,
        lj_cutoff_angstrom=lj_cutoff_angstrom,
        coulomb_cutoff_angstrom=coulomb_cutoff_angstrom,
        lj_tail_correction=lj_tail_correction,
    )

    return topology, positions_angstrom, report


def system_from_lammps_data(
    data_path: Path,
    molecules: list[Chem.Mol],
    frc_path: Path,
    templates_path: Path,
    lj_cutoff_angstrom: float,
    coulomb_cutoff_angstrom: float | None,
    lj_tail_correction: bool,
    periodic: bool,
    coulomb_method: str | None,
    ewald_error_tolerance: float | None = None,
    merge_bonded: bool = True,
) -> tuple[openmm.System, np.ndarray, dict]:
    """
    topology_from_lammps_data followed by build_system; returns (OpenMM System, positions in nm, report).
    coulomb_cutoff_angstrom is used only by the "pme" and "ewald" methods.
    """
    topology, positions_angstrom, report = topology_from_lammps_data(
        data_path,
        molecules,
        frc_path,
        templates_path,
        lj_cutoff_angstrom=lj_cutoff_angstrom,
        coulomb_cutoff_angstrom=coulomb_cutoff_angstrom,
        lj_tail_correction=lj_tail_correction,
    )

    system = build_system(
        topology,
        periodic=periodic,
        coulomb_method=coulomb_method,
        ewald_error_tolerance=ewald_error_tolerance,
        merge_bonded=merge_bonded,
    )

    return system, positions_angstrom * NM_PER_ANGSTROM, report


def topology_from_openmm_topology(
    omm_topology: openmm.app.Topology,
    positions,
    molecules: list[Chem.Mol],
    frc_path: Path,
    templates_path: Path,
    lj_cutoff_angstrom: float,
    coulomb_cutoff_angstrom: float | None,
    lj_tail_correction: bool,
) -> tuple[ParameterizedTopology, np.ndarray, dict]:
    """
    Type and parameterize the structure of an openmm.app.Topology; returns (topology, positions in Angstrom, report).

    Elements, bonds, and the box are taken from omm_topology (bond orders are ignored); positions must be an openmm.unit.Quantity.
    Atom i of the result is atom i of omm_topology. Only orthorhombic boxes are supported.
    Molecules split across the box are made whole (with a warning).
    See type_and_parameterize for molecules, the pair settings, and the report.
    """
    structure = structure_from_openmm_topology(omm_topology, positions)

    positions_angstrom = structure["positions_angstrom"]
    if structure["box_lengths_angstrom"] is not None:
        positions_angstrom = make_molecules_whole(positions_angstrom, structure["bonds"], structure["box_lengths_angstrom"])

    topology, report = type_and_parameterize(
        structure["elements"],
        structure["bonds"],
        structure["box_lengths_angstrom"],
        molecules,
        frc_path,
        templates_path,
        lj_cutoff_angstrom=lj_cutoff_angstrom,
        coulomb_cutoff_angstrom=coulomb_cutoff_angstrom,
        lj_tail_correction=lj_tail_correction,
    )

    return topology, positions_angstrom, report


def system_from_openmm_topology(
    omm_topology: openmm.app.Topology,
    positions,
    molecules: list[Chem.Mol],
    frc_path: Path,
    templates_path: Path,
    lj_cutoff_angstrom: float,
    coulomb_cutoff_angstrom: float | None,
    lj_tail_correction: bool,
    periodic: bool,
    coulomb_method: str | None,
    ewald_error_tolerance: float | None = None,
    merge_bonded: bool = True,
) -> tuple[openmm.System, np.ndarray, dict]:
    """
    topology_from_openmm_topology followed by build_system; returns (OpenMM System, positions in nm, report).
    periodic=True needs a box in omm_topology. coulomb_cutoff_angstrom is used only by the "pme" and "ewald" methods.
    """
    topology, positions_angstrom, report = topology_from_openmm_topology(
        omm_topology,
        positions,
        molecules,
        frc_path,
        templates_path,
        lj_cutoff_angstrom=lj_cutoff_angstrom,
        coulomb_cutoff_angstrom=coulomb_cutoff_angstrom,
        lj_tail_correction=lj_tail_correction,
    )

    system = build_system(
        topology,
        periodic=periodic,
        coulomb_method=coulomb_method,
        ewald_error_tolerance=ewald_error_tolerance,
        merge_bonded=merge_bonded,
    )

    return system, positions_angstrom * NM_PER_ANGSTROM, report


def system_from_pdb(
    path: Path,
    molecules: list[Chem.Mol],
    frc_path: Path,
    templates_path: Path,
    lj_cutoff_angstrom: float,
    coulomb_cutoff_angstrom: float | None,
    lj_tail_correction: bool,
    periodic: bool,
    coulomb_method: str | None,
    ewald_error_tolerance: float | None = None,
    merge_bonded: bool = True,
) -> tuple[openmm.System, openmm.app.Topology, np.ndarray, dict]:
    """
    Read a PDB (.pdb, .ent) or PDBx/mmCIF (.cif, .mmcif, .pdbx) file and build the system with system_from_openmm_topology.
    Returns (OpenMM System, openmm.app.Topology, positions in nm, report); the topology is the one read from the file, for openmm.app.Simulation and reporters.

    Bonds must be in the file: CONECT records in PDB, struct_conn or chem_comp_bond in PDBx/mmCIF, for every bond including those to hydrogen.
    The box comes from CRYST1 (PDB) or the cell records (PDBx/mmCIF).
    PDB stores coordinates to 0.001 Angstrom and atom serial numbers up to 99999; use PDBx/mmCIF for larger systems.
    """
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix in PDB_SUFFIXES:
        structure_file = openmm.app.PDBFile(str(path))
    elif suffix in PDBX_SUFFIXES:
        structure_file = openmm.app.PDBxFile(str(path))
    else:
        raise ValueError(f"Unknown structure file suffix '{path.suffix}'; expected one of {PDB_SUFFIXES + PDBX_SUFFIXES}.")

    system, positions_nm, report = system_from_openmm_topology(
        structure_file.topology,
        structure_file.positions,
        molecules,
        frc_path,
        templates_path,
        lj_cutoff_angstrom=lj_cutoff_angstrom,
        coulomb_cutoff_angstrom=coulomb_cutoff_angstrom,
        lj_tail_correction=lj_tail_correction,
        periodic=periodic,
        coulomb_method=coulomb_method,
        ewald_error_tolerance=ewald_error_tolerance,
        merge_bonded=merge_bonded,
    )

    return system, structure_file.topology, positions_nm, report
