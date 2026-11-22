"""Generate angles, dihedrals, and impropers from a bond list.

Conventions (atom indices are 0-based):
- angle (i, j, k): j is the vertex; each angle is generated once, with i < k.
- dihedral (i, j, k, l): j-k is the middle bond; each dihedral is generated once, with j < k.
  Dihedrals with i == l (a three-membered ring closing on itself) are not generated.
- improper (i, j, k, l): j is the central atom and i < k < l are three of its neighbours.
  Every atom with three or more neighbours gets one improper per triplet of neighbours (4 for an sp3 carbon), as EMC writes for PCFF.

The order chosen here only fixes how coefficients must be oriented; the parameter assignment (openmm_pcff/assign.py) orients them to these atom orders.
"""

from itertools import combinations


def bonded_neighbours(n_atoms: int, bonds: list[tuple[int, int]]) -> list[list[int]]:
    """Return the sorted neighbour list of every atom."""
    neighbours = [[] for atom in range(n_atoms)]

    for atom_i, atom_j in bonds:
        if atom_i == atom_j:
            raise ValueError(f"Bond from atom {atom_i} to itself.")

        neighbours[atom_i].append(atom_j)
        neighbours[atom_j].append(atom_i)

    for atom in range(n_atoms):
        if len(set(neighbours[atom])) != len(neighbours[atom]):
            raise ValueError(f"Atom {atom} has a duplicated bond.")

        neighbours[atom].sort()

    return neighbours


def generate_angles(neighbours: list[list[int]]) -> list[tuple[int, int, int]]:
    angles = []

    for vertex, vertex_neighbours in enumerate(neighbours):
        for atom_i, atom_k in combinations(vertex_neighbours, 2):
            angles.append((atom_i, vertex, atom_k))

    return angles


def generate_dihedrals(neighbours: list[list[int]], bonds: list[tuple[int, int]]) -> list[tuple[int, int, int, int]]:
    dihedrals = []

    for bond in bonds:
        atom_j, atom_k = sorted(bond)

        for atom_i in neighbours[atom_j]:
            if atom_i == atom_k:
                continue

            for atom_l in neighbours[atom_k]:
                if atom_l == atom_j or atom_l == atom_i:
                    continue

                dihedrals.append((atom_i, atom_j, atom_k, atom_l))

    return dihedrals


def generate_impropers(neighbours: list[list[int]]) -> list[tuple[int, int, int, int]]:
    impropers = []

    for center, center_neighbours in enumerate(neighbours):
        for atom_i, atom_k, atom_l in combinations(center_neighbours, 3):
            impropers.append((atom_i, center, atom_k, atom_l))

    return impropers
