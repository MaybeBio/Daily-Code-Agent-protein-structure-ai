"""Structure input from an openmm.app.Topology (e.g. read from PDB or PDBx/mmCIF), and making molecules whole.

A structure is the input of atom typing and parameter assignment: elements, bonds (0-based atom pairs),
an orthorhombic box in Angstrom (None without a box), and positions in Angstrom.
"""

import warnings

import numpy as np
import openmm.unit


# Largest off-diagonal box-vector component (Angstrom) still treated as zero; 90 degree CRYST1 angles give about 1e-15 Angstrom.
ORTHORHOMBIC_TOLERANCE_ANGSTROM = 1e-5


def structure_from_openmm_topology(omm_topology, positions) -> dict:
    """
    Return the structure of an openmm.app.Topology: elements, bonds, box_lengths_angstrom (None without a box), positions_angstrom.

    positions must carry units (an openmm.unit.Quantity, as given by PDBFile(...).positions and PDBxFile(...).positions).
    Bonds are those of the topology (CONECT records in PDB, struct_conn and chem_comp_bond in PDBx/mmCIF); bond orders are not used.
    Only orthorhombic boxes are supported.
    """
    if not openmm.unit.is_quantity(positions):
        raise TypeError("positions must be an openmm.unit.Quantity, e.g. PDBFile(...).positions.")

    positions_angstrom = np.array(positions.value_in_unit(openmm.unit.angstrom), dtype=float)

    if positions_angstrom.shape != (omm_topology.getNumAtoms(), 3):
        raise ValueError(f"Expected {omm_topology.getNumAtoms()} positions for the topology, got an array of shape {positions_angstrom.shape}.")

    elements = []
    for atom in omm_topology.atoms():
        if atom.element is None:
            raise ValueError(f"Atom {atom.index} ({atom.name}, residue {atom.residue.name}) has no element.")
        elements.append(atom.element.symbol)

    # Keep each bond once, in topology order, so that the result does not depend on how the file lists duplicates.
    bonds = []
    seen_pairs = set()
    for bond in omm_topology.bonds():
        pair = (bond.atom1.index, bond.atom2.index)
        unordered_pair = (min(pair), max(pair))

        if unordered_pair not in seen_pairs:
            seen_pairs.add(unordered_pair)
            bonds.append(pair)

    box_vectors = omm_topology.getPeriodicBoxVectors()

    if box_vectors is None:
        box_lengths_angstrom = None
    else:
        box_matrix_angstrom = np.array(box_vectors.value_in_unit(openmm.unit.angstrom), dtype=float)
        off_diagonal = box_matrix_angstrom - np.diag(np.diag(box_matrix_angstrom))

        if np.abs(off_diagonal).max() > ORTHORHOMBIC_TOLERANCE_ANGSTROM:
            raise ValueError("Only orthorhombic boxes are supported (all box angles 90 degrees).")

        box_lengths_angstrom = tuple(float(length) for length in np.diag(box_matrix_angstrom))

    return {
        "elements": elements,
        "bonds": bonds,
        "box_lengths_angstrom": box_lengths_angstrom,
        "positions_angstrom": positions_angstrom,
    }


def make_molecules_whole(positions_angstrom: np.ndarray, bonds: list[tuple[int, int]], box_lengths_angstrom: tuple[float, float, float]) -> np.ndarray:
    """
    Return positions (Angstrom) in which no molecule is split across the periodic boundary.

    Bonded forces are evaluated without periodic boundary conditions, so a split molecule would give wrong bonded energies.
    If no bond spans more than half a box length in any direction, the positions are returned unchanged.
    Otherwise every molecule is walked along its bonds from its first atom, each atom is moved by whole box vectors to the image nearest to the atom it was reached from, and a warning reports how many atoms moved.
    This assumes every bond is shorter than half the box length; a molecule bonded to its own periodic image (an infinite network) raises.
    """
    positions = positions_angstrom.copy()

    if not bonds:
        return positions

    box = np.array(box_lengths_angstrom)
    bond_atoms = np.array(bonds)

    def split_bond_count(positions_to_check: np.ndarray) -> int:
        bond_vectors = positions_to_check[bond_atoms[:, 1]] - positions_to_check[bond_atoms[:, 0]]
        return int(np.any(np.abs(bond_vectors) > box / 2, axis=1).sum())

    if split_bond_count(positions) == 0:
        return positions

    n_atoms = len(positions)
    neighbours = [[] for atom in range(n_atoms)]
    for atom_i, atom_j in bonds:
        neighbours[atom_i].append(atom_j)
        neighbours[atom_j].append(atom_i)

    visited = [False] * n_atoms
    n_moved_atoms = 0

    for start in range(n_atoms):
        if visited[start]:
            continue

        visited[start] = True
        frontier = [start]

        while frontier:
            atom = frontier.pop()

            for neighbour in neighbours[atom]:
                if visited[neighbour]:
                    continue

                # Minimum-image shift of the neighbour relative to the atom it is reached from.
                shift = box * np.round((positions[neighbour] - positions[atom]) / box)
                if np.any(shift != 0.0):
                    positions[neighbour] -= shift
                    n_moved_atoms += 1

                visited[neighbour] = True
                frontier.append(neighbour)

    n_still_split = split_bond_count(positions)
    if n_still_split > 0:
        raise ValueError(
            f"{n_still_split} bonds still span more than half a box length after making molecules whole; "
            "molecules bonded to their own periodic image are not supported."
        )

    warnings.warn(f"Molecules were split across the periodic boundary; {n_moved_atoms} atoms were moved by whole box vectors to make them whole.")

    return positions
