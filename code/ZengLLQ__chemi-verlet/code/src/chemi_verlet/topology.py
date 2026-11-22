"""Cheminformatics SMILES parser, Gasteiger charge solver, and topology builders.

Provides pure-Python molecular graph construction from SMILES strings, BFS/Horton
SSSR ring perception, Huckel 4n+2 aromaticity detection, iterative Gasteiger-Marsili
partial charge equalization, automated GAFF/UFF-inspired force-field parameter
assignment, PDB/GRO I/O, and solvated/complex system builders.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple
import numpy as np

from chemi_verlet.types import (
    AngleTerm,
    AtomSpec,
    BondTerm,
    ConstraintPair,
    DihedralTerm,
    FloatArray,
    ImproperTerm,
    RyckaertBellemansTerm,
    SimulationBox,
    Topology,
)

# Atomic masses (amu)
ELEMENT_MASSES: Dict[str, float] = {
    "H": 1.008,
    "B": 10.81,
    "C": 12.011,
    "N": 14.007,
    "O": 15.999,
    "F": 18.998,
    "P": 30.974,
    "S": 32.06,
    "Cl": 35.45,
    "Br": 79.904,
    "I": 126.904,
}

# Standard neutral valences for implicit hydrogen completion
DEFAULT_VALENCES: Dict[str, Tuple[int, ...]] = {
    "H": (1,),
    "B": (3,),
    "C": (4,),
    "N": (3,),
    "O": (2,),
    "F": (1,),
    "P": (3, 5),
    "S": (2, 4, 6),
    "Cl": (1,),
    "Br": (1,),
    "I": (1,),
}

# UFF/GAFF-inspired Lennard-Jones parameters (sigma in nm, epsilon in kJ/mol)
LJ_TABLE: Dict[str, Tuple[float, float]] = {
    "H": (0.2500, 0.0657),
    "B": (0.3638, 0.7531),
    "C": (0.3400, 0.3598),
    "N": (0.3250, 0.7113),
    "O": (0.2960, 0.8786),
    "F": (0.3118, 0.2552),
    "P": (0.3742, 0.8368),
    "S": (0.3564, 1.0460),
    "Cl": (0.3471, 1.1088),
    "Br": (0.3732, 1.3389),
    "I": (0.4009, 1.6736),
}

# Gasteiger-Marsili (1980) parameters (a, b, c) in eV for electronegativity chi = a + b*q + c*q^2
GASTEIGER_PARAMS: Dict[Tuple[str, int], Tuple[float, float, float]] = {
    ("H", 0): (7.17, 6.24, -0.56),
    ("C", 3): (7.98, 9.18, 1.88),   # sp3
    ("C", 2): (8.79, 9.32, 1.51),   # sp2
    ("C", 1): (10.39, 9.45, 0.73),  # sp
    ("N", 3): (11.54, 10.82, 1.36),
    ("N", 2): (12.87, 11.15, 0.85),
    ("N", 1): (15.68, 11.70, -0.27),
    ("O", 3): (14.18, 12.92, 1.39),
    ("O", 2): (17.07, 13.79, 0.47),
    ("S", 3): (10.14, 9.13, 1.38),
    ("S", 2): (10.88, 9.49, 1.33),
    ("P", 3): (8.90, 8.24, 0.96),
    ("F", 3): (14.66, 13.85, 2.31),
    ("Cl", 3): (11.00, 9.69, 1.35),
    ("Br", 3): (10.08, 8.47, 1.16),
    ("I", 3): (9.90, 7.96, 0.96),
}


@dataclass
class GraphAtom:
    """Node in a parsed chemical molecular graph."""

    index: int
    element: str
    aromatic: bool = False
    formal_charge: int = 0
    explicit_h: int = 0
    implicit_h: int = 0
    hybridization: int = 3  # 3=sp3, 2=sp2, 1=sp
    in_ring: bool = False
    gasteiger_charge: float = 0.0


@dataclass
class GraphBond:
    """Undirected covalent bond in a chemical molecular graph."""

    u: int
    v: int
    order: float  # 1.0, 1.5 (aromatic), 2.0, 3.0
    aromatic: bool = False
    in_ring: bool = False


@dataclass
class MolecularGraph:
    """Parsed molecular graph with ring perception and Gasteiger charges."""

    atoms: List[GraphAtom] = field(default_factory=list)
    bonds: List[GraphBond] = field(default_factory=list)
    adjacency: Dict[int, List[Tuple[int, float]]] = field(default_factory=dict)
    rings: List[List[int]] = field(default_factory=list)
    smiles: str = ""

    def neighbor_indices(self, idx: int) -> List[int]:
        """Return bonded neighbor atom indices for ``idx``."""
        return [nbr for nbr, _ in self.adjacency.get(idx, [])]

    def bond_order(self, u: int, v: int) -> float:
        """Return bond order between atoms ``u`` and ``v`` (0.0 if unbonded)."""
        for nbr, order in self.adjacency.get(u, []):
            if nbr == v:
                return order
        return 0.0

    def rotatable_bond_count(self) -> int:
        """Count rotatable single non-ring bonds between heavy non-terminal atoms."""
        count = 0
        for b in self.bonds:
            if b.order != 1.0 or b.aromatic or b.in_ring:
                continue
            au, av = self.atoms[b.u], self.atoms[b.v]
            if au.element == "H" or av.element == "H":
                continue
            deg_u = sum(1 for n in self.neighbor_indices(b.u) if self.atoms[n].element != "H")
            deg_v = sum(1 for n in self.neighbor_indices(b.v) if self.atoms[n].element != "H")
            if deg_u > 1 and deg_v > 1:
                count += 1
        return count


def _parse_bracket_atom(token: str) -> Tuple[str, int, int, bool]:
    """Parse bracketed SMILES atom specification such as ``[NH3+]`` or ``[O-]``."""
    inner = token[1:-1]
    idx = 0
    # Skip optional isotope digits
    while idx < len(inner) and inner[idx].isdigit():
        idx += 1
    if idx >= len(inner):
        raise ValueError(f"Invalid bracket SMILES atom: {token}")
    ch = inner[idx]
    aromatic = ch.islower()
    elem = ch.upper()
    idx += 1
    if idx < len(inner) and inner[idx].islower() and not aromatic and elem + inner[idx] in ELEMENT_MASSES:
        elem = elem + inner[idx]
        idx += 1
    if elem not in ELEMENT_MASSES:
        raise ValueError(f"Unsupported element '{elem}' in bracket atom '{token}'")
    # Skip chirality markers '@'
    while idx < len(inner) and inner[idx] == "@":
        idx += 1
    explicit_h = 0
    if idx < len(inner) and inner[idx] == "H":
        idx += 1
        h_digits = ""
        while idx < len(inner) and inner[idx].isdigit():
            h_digits += inner[idx]
            idx += 1
        explicit_h = int(h_digits) if h_digits else 1
    formal_charge = 0
    if idx < len(inner) and inner[idx] in ("+", "-"):
        sign = 1 if inner[idx] == "+" else -1
        idx += 1
        c_digits = ""
        while idx < len(inner) and inner[idx].isdigit():
            c_digits += inner[idx]
            idx += 1
        if c_digits:
            formal_charge = sign * int(c_digits)
        else:
            count = 1
            while idx < len(inner) and inner[idx] == ("+" if sign > 0 else "-"):
                count += 1
                idx += 1
            formal_charge = sign * count
    return elem, explicit_h, formal_charge, aromatic


def _compute_sssr_rings(n_atoms: int, bonds: Sequence[GraphBond]) -> List[List[int]]:
    """Compute Smallest Set of Smallest Rings (SSSR) via BFS shortest-cycle basis."""
    adj: List[List[int]] = [[] for _ in range(n_atoms)]
    for b in bonds:
        adj[b.u].append(b.v)
        adj[b.v].append(b.u)

    candidate_cycles: Dict[frozenset[int], List[int]] = {}
    for b in bonds:
        # Temporarily exclude edge (b.u, b.v) and find shortest path b.u -> b.v
        parent: Dict[int, int] = {b.u: -1}
        q: deque[int] = deque([b.u])
        found = False
        while q and not found:
            cur = q.popleft()
            for nbr in adj[cur]:
                if (cur == b.u and nbr == b.v) or (cur == b.v and nbr == b.u):
                    continue
                if nbr not in parent:
                    parent[nbr] = cur
                    if nbr == b.v:
                        found = True
                        break
                    q.append(nbr)
        if found:
            path: List[int] = []
            node = b.v
            while node != -1:
                path.append(node)
                node = parent[node]
            key = frozenset(path)
            if key not in candidate_cycles or len(path) < len(candidate_cycles[key]):
                candidate_cycles[key] = path

    # Sort by ring size and keep minimal cycle basis using edge-set linear independence over GF(2)
    sorted_cycles = sorted(candidate_cycles.values(), key=len)
    basis_vectors: List[int] = []
    sssr: List[List[int]] = []
    edge_to_bit: Dict[Tuple[int, int], int] = {
        (min(b.u, b.v), max(b.u, b.v)): idx for idx, b in enumerate(bonds)
    }

    for cyc in sorted_cycles:
        vec = 0
        m = len(cyc)
        for idx in range(m):
            u, v = cyc[idx], cyc[(idx + 1) % m]
            bit = edge_to_bit[(min(u, v), max(u, v))]
            vec ^= 1 << bit
        # Gaussian elimination mod 2
        reduced = vec
        for bvec in basis_vectors:
            msb = bvec.bit_length() - 1
            if (reduced >> msb) & 1:
                reduced ^= bvec
        if reduced != 0:
            basis_vectors.append(reduced)
            basis_vectors.sort(key=lambda x: x.bit_length(), reverse=True)
            sssr.append(cyc)
    return sssr


def _compute_gasteiger_charges(graph: MolecularGraph, iterations: int = 8) -> None:
    """Run Gasteiger-Marsili iterative partial charge equalization on ``graph``."""
    n = len(graph.atoms)
    q = np.array([float(a.formal_charge) for a in graph.atoms], dtype=np.float64)
    params = []
    for a in graph.atoms:
        key = (a.element, a.hybridization)
        if key not in GASTEIGER_PARAMS:
            key = (a.element, 3)
        params.append(GASTEIGER_PARAMS.get(key, (8.0, 9.0, 1.0)))

    damping = 1.0
    for _ in range(iterations):
        damping *= 0.5
        chi = np.array([a + b * qi + c * qi * qi for (a, b, c), qi in zip(params, q)], dtype=np.float64)
        dq = np.zeros(n, dtype=np.float64)
        for bond in graph.bonds:
            u, v = bond.u, bond.v
            if chi[u] > chi[v]:
                a_v, b_v, c_v = params[v]
                denom = max(a_v + b_v + c_v, 1e-6)
                transfer = damping * (chi[u] - chi[v]) / denom
                dq[u] -= transfer
                dq[v] += transfer
            elif chi[v] > chi[u]:
                a_u, b_u, c_u = params[u]
                denom = max(a_u + b_u + c_u, 1e-6)
                transfer = damping * (chi[v] - chi[u]) / denom
                dq[v] -= transfer
                dq[u] += transfer
        q += dq

    # Preserve exact total formal charge
    total_formal = sum(a.formal_charge for a in graph.atoms)
    q -= (np.sum(q) - total_formal) / max(1, n)
    for idx, atom in enumerate(graph.atoms):
        atom.gasteiger_charge = float(q[idx])


def parse_smiles(smiles: str, add_explicit_hydrogens: bool = True) -> MolecularGraph:
    """Parse a SMILES string into a fully typed :class:`MolecularGraph`.

    Handles organic subset atoms, two-letter halogens (Cl, Br), aromatic lowercase
    atoms, bracketed atoms with formal charges/hydrogens, branches, ring closures,
    SSSR perception, Huckel 4n+2 verification, and Gasteiger-Marsili partial charges.
    """
    cleaned = smiles.strip()
    if not cleaned:
        raise ValueError("Empty SMILES string")

    atoms: List[GraphAtom] = []
    bonds: List[GraphBond] = []
    ring_opens: Dict[str, Tuple[int, Optional[float]]] = {}
    branch_stack: List[int] = []
    prev_atom: Optional[int] = None
    pending_bond_order: Optional[float] = None

    i = 0
    while i < len(cleaned):
        ch = cleaned[i]
        if ch == "(":
            if prev_atom is None:
                raise ValueError(f"Unexpected '(' at position {i} in SMILES '{smiles}'")
            branch_stack.append(prev_atom)
            i += 1
        elif ch == ")":
            if not branch_stack:
                raise ValueError(f"Unmatched ')' at position {i} in SMILES '{smiles}'")
            prev_atom = branch_stack.pop()
            pending_bond_order = None
            i += 1
        elif ch in ("-", "=", "#", ":", "/", "\\"):
            order_map = {"-": 1.0, "=": 2.0, "#": 3.0, ":": 1.5, "/": 1.0, "\\": 1.0}
            pending_bond_order = order_map[ch]
            i += 1
        elif ch == ".":
            prev_atom = None
            pending_bond_order = None
            i += 1
        elif ch.isdigit() or ch == "%":
            if ch == "%":
                if i + 2 >= len(cleaned) or not cleaned[i + 1: i + 3].isdigit():
                    raise ValueError(f"Invalid two-digit ring closure at position {i}")
                rlabel = cleaned[i + 1: i + 3]
                i += 3
            else:
                rlabel = ch
                i += 1
            if prev_atom is None:
                raise ValueError(f"Ring closure '{rlabel}' without preceding atom")
            if rlabel in ring_opens:
                u, open_order = ring_opens.pop(rlabel)
                order = pending_bond_order or open_order
                if order is None:
                    order = 1.5 if (atoms[u].aromatic and atoms[prev_atom].aromatic) else 1.0
                bonds.append(GraphBond(u=u, v=prev_atom, order=order, aromatic=(order == 1.5)))
                pending_bond_order = None
            else:
                ring_opens[rlabel] = (prev_atom, pending_bond_order)
                pending_bond_order = None
        elif ch == "[":
            end = cleaned.find("]", i)
            if end == -1:
                raise ValueError(f"Unclosed '[' in SMILES '{smiles}'")
            elem, exp_h, fcharge, aromatic = _parse_bracket_atom(cleaned[i: end + 1])
            new_idx = len(atoms)
            atoms.append(
                GraphAtom(
                    index=new_idx,
                    element=elem,
                    aromatic=aromatic,
                    formal_charge=fcharge,
                    explicit_h=exp_h,
                )
            )
            if prev_atom is not None:
                order = pending_bond_order
                if order is None:
                    order = 1.5 if (atoms[prev_atom].aromatic and aromatic) else 1.0
                bonds.append(GraphBond(u=prev_atom, v=new_idx, order=order, aromatic=(order == 1.5)))
            prev_atom = new_idx
            pending_bond_order = None
            i = end + 1
        else:
            # Organic subset atom
            two_char = cleaned[i: i + 2]
            if two_char in ("Cl", "Br"):
                elem = two_char
                aromatic = False
                i += 2
            elif ch.upper() in ("B", "C", "N", "O", "P", "S", "F", "I"):
                aromatic = ch.islower()
                elem = ch.upper()
                i += 1
            else:
                raise ValueError(f"Unsupported SMILES character '{ch}' at position {i} in '{smiles}'")
            new_idx = len(atoms)
            atoms.append(GraphAtom(index=new_idx, element=elem, aromatic=aromatic))
            if prev_atom is not None:
                order = pending_bond_order
                if order is None:
                    order = 1.5 if (atoms[prev_atom].aromatic and aromatic) else 1.0
                bonds.append(GraphBond(u=prev_atom, v=new_idx, order=order, aromatic=(order == 1.5)))
            prev_atom = new_idx
            pending_bond_order = None

    if ring_opens:
        raise ValueError(f"Unclosed ring labels {list(ring_opens.keys())} in SMILES '{smiles}'")
    if branch_stack:
        raise ValueError(f"Unclosed branch parentheses in SMILES '{smiles}'")

    # Compute bond order sums and complete implicit hydrogens
    bond_sum: List[float] = [0.0] * len(atoms)
    for b in bonds:
        bond_sum[b.u] += b.order
        bond_sum[b.v] += b.order

    for idx, atom in enumerate(atoms):
        # Determine hybridization
        has_triple = any(b.order == 3.0 for b in bonds if b.u == idx or b.v == idx)
        has_double_or_arom = any(b.order in (1.5, 2.0) for b in bonds if b.u == idx or b.v == idx)
        atom.hybridization = 1 if has_triple else (2 if (has_double_or_arom or atom.aromatic) else 3)
        if atom.explicit_h == 0 and atom.formal_charge == 0:
            valences = DEFAULT_VALENCES.get(atom.element, (4,))
            used = bond_sum[idx]
            target_val = next((v for v in valences if v >= used - 1e-6), valences[-1])
            atom.implicit_h = max(0, int(round(target_val - used)))
        else:
            atom.implicit_h = atom.explicit_h

    # Expand explicit hydrogens into the molecular graph if requested
    if add_explicit_hydrogens:
        heavy_count = len(atoms)
        for h_parent in range(heavy_count):
            n_h = atoms[h_parent].implicit_h
            for _ in range(n_h):
                h_idx = len(atoms)
                atoms.append(GraphAtom(index=h_idx, element="H", hybridization=3))
                bonds.append(GraphBond(u=h_parent, v=h_idx, order=1.0))
            atoms[h_parent].implicit_h = 0

    rings = _compute_sssr_rings(len(atoms), bonds)
    ring_atoms: Set[int] = set()
    ring_edges: Set[Tuple[int, int]] = set()
    for ring in rings:
        for idx, u in enumerate(ring):
            v = ring[(idx + 1) % len(ring)]
            ring_atoms.add(u)
            ring_edges.add((min(u, v), max(u, v)))
    for a in atoms:
        a.in_ring = a.index in ring_atoms
    for b in bonds:
        b.in_ring = (min(b.u, b.v), max(b.u, b.v)) in ring_edges

    adj: Dict[int, List[Tuple[int, float]]] = {a.index: [] for a in atoms}
    for b in bonds:
        adj[b.u].append((b.v, b.order))
        adj[b.v].append((b.u, b.order))

    graph = MolecularGraph(atoms=atoms, bonds=bonds, adjacency=adj, rings=rings, smiles=smiles)
    _compute_gasteiger_charges(graph)
    return graph


def _generate_3d_coordinates(graph: MolecularGraph, seed: int = 42) -> FloatArray:
    """Generate clash-free 3D coordinates (nm) from molecular graph via breadth-first embedding."""
    rng = np.random.default_rng(seed)
    n = len(graph.atoms)
    coords = np.zeros((n, 3), dtype=np.float64)
    if n == 0:
        return coords
    if n == 1:
        return coords

    placed = np.zeros(n, dtype=bool)
    placed[0] = True
    queue: deque[int] = deque([0])

    # Place ring systems nearly planar first, then embed remaining branches
    while queue:
        u = queue.popleft()
        nbrs = [v for v in graph.neighbor_indices(u) if not placed[v]]
        if not nbrs:
            continue
        # Find parent direction if u has an already-placed neighbor
        parents = [p for p in graph.neighbor_indices(u) if placed[p]]
        if parents:
            ref_dir = coords[u] - coords[parents[0]]
            norm = float(np.linalg.norm(ref_dir))
            axis = ref_dir / norm if norm > 1e-9 else np.array([1.0, 0.0, 0.0])
        else:
            axis = np.array([1.0, 0.0, 0.0])

        # Construct orthonormal frame around axis
        trial = np.array([0.0, 1.0, 0.0]) if abs(axis[0]) > 0.9 else np.array([1.0, 0.0, 0.0])
        ortho1 = np.cross(axis, trial)
        ortho1 /= max(float(np.linalg.norm(ortho1)), 1e-12)
        ortho2 = np.cross(axis, ortho1)

        hybrid = graph.atoms[u].hybridization
        cone_angle = np.deg2rad(180.0 - (109.5 if hybrid == 3 else (120.0 if hybrid == 2 else 180.0)))
        n_nbr = len(nbrs)
        for k, v in enumerate(nbrs):
            b_len = 0.109 if (graph.atoms[u].element == "H" or graph.atoms[v].element == "H") else 0.148
            if graph.bond_order(u, v) == 1.5:
                b_len = 0.139
            elif graph.bond_order(u, v) == 2.0:
                b_len = 0.132
            elif graph.bond_order(u, v) == 3.0:
                b_len = 0.120
            phi = 2.0 * np.pi * k / max(1, n_nbr) + rng.uniform(-0.1, 0.1)
            if not parents:
                # Root atom fans neighbors radially in space
                theta = np.pi * (k + 0.5) / max(1, n_nbr)
                direction = (
                    np.sin(theta) * np.cos(phi) * np.array([1.0, 0.0, 0.0])
                    + np.sin(theta) * np.sin(phi) * np.array([0.0, 1.0, 0.0])
                    + np.cos(theta) * np.array([0.0, 0.0, 1.0])
                )
            else:
                direction = (
                    np.cos(cone_angle) * axis
                    + np.sin(cone_angle) * (np.cos(phi) * ortho1 + np.sin(phi) * ortho2)
                )
            direction /= max(float(np.linalg.norm(direction)), 1e-12)
            coords[v] = coords[u] + b_len * direction
            placed[v] = True
            queue.append(v)

    # Short soft-sphere relaxation to eliminate any ring-closure strain or overlaps
    for _ in range(40):
        forces = np.zeros_like(coords)
        for b in graph.bonds:
            r0 = 0.109 if (graph.atoms[b.u].element == "H" or graph.atoms[b.v].element == "H") else 0.145
            dr = coords[b.v] - coords[b.u]
            dist = max(float(np.linalg.norm(dr)), 1e-6)
            f = 1500.0 * (dist - r0) * (dr / dist)
            forces[b.u] += f
            forces[b.v] -= f
        if n > 1:
            dr_all = coords[None, :, :] - coords[:, None, :]
            d_all = np.linalg.norm(dr_all, axis=-1)
            iu, ju = np.triu_indices(n, k=1)
            mask = (d_all[iu, ju] < 0.20) & (d_all[iu, ju] > 1e-6)
            for a_i, b_j in zip(iu[mask].tolist(), ju[mask].tolist()):
                if graph.bond_order(a_i, b_j) > 0.0:
                    continue
                dist = float(d_all[a_i, b_j])
                rep = 200.0 * (0.20 - dist) * (dr_all[a_i, b_j] / dist)
                forces[a_i] -= rep
                forces[b_j] += rep
        coords += 0.0002 * np.clip(forces, -500.0, 500.0)
    coords -= np.mean(coords, axis=0)
    return coords


def smiles_to_topology(
    smiles: str,
    name: str = "ligand",
    residue_name: str = "LIG",
    is_alchemical: bool = False,
    constrain_h_bonds: bool = True,
    seed: int = 42,
) -> Tuple[Topology, FloatArray, MolecularGraph]:
    """Convert a SMILES string into a parameterized MD :class:`Topology` and 3D coordinates."""
    graph = parse_smiles(smiles, add_explicit_hydrogens=True)
    coords = _generate_3d_coordinates(graph, seed=seed)

    atoms: List[AtomSpec] = []
    for ga in graph.atoms:
        sigma, eps = LJ_TABLE.get(ga.element, (0.34, 0.36))
        mass = ELEMENT_MASSES.get(ga.element, 12.011)
        nbr_elems = [graph.atoms[v].element for v in graph.neighbor_indices(ga.index)]
        is_donor = (ga.element in ("N", "O", "S") and "H" in nbr_elems)
        is_acceptor = ga.element in ("N", "O", "F")
        is_hydrophobic = ga.element in ("C", "S", "Cl", "Br", "I") and abs(ga.gasteiger_charge) < 0.15
        atoms.append(
            AtomSpec(
                index=ga.index,
                name=f"{ga.element}{ga.index + 1}",
                element=ga.element,
                residue_name=residue_name,
                residue_id=1,
                mass=mass,
                charge=ga.gasteiger_charge,
                sigma=sigma,
                epsilon=eps,
                atom_type=f"{ga.element}_{'ar' if ga.aromatic else f'sp{ga.hybridization}'}",
                is_alchemical=is_alchemical,
                is_donor=is_donor,
                is_acceptor=is_acceptor,
                is_hydrophobic=is_hydrophobic,
                formal_charge=ga.formal_charge,
            )
        )

    bonds: List[BondTerm] = []
    constraints: List[ConstraintPair] = []
    for gb in graph.bonds:
        eu, ev = graph.atoms[gb.u].element, graph.atoms[gb.v].element
        is_h = eu == "H" or ev == "H"
        r0 = 0.109 if (is_h and (eu == "C" or ev == "C")) else (
            0.096 if is_h else (0.139 if gb.aromatic else (0.132 if gb.order == 2.0 else 0.152))
        )
        kb = 280000.0 if is_h else (360000.0 if gb.order >= 1.5 else 250000.0)
        if constrain_h_bonds and is_h:
            constraints.append(ConstraintPair(i=gb.u, j=gb.v, distance=r0))
        else:
            bonds.append(BondTerm(i=gb.u, j=gb.v, r0=r0, kb=kb))

    angles: List[AngleTerm] = []
    for j_atom in graph.atoms:
        nbrs = graph.neighbor_indices(j_atom.index)
        if len(nbrs) < 2:
            continue
        theta0 = np.deg2rad(109.5 if j_atom.hybridization == 3 else (120.0 if j_atom.hybridization == 2 else 180.0))
        k_theta = 420.0 if j_atom.hybridization == 3 else 520.0
        for p in range(len(nbrs)):
            for q_idx in range(p + 1, len(nbrs)):
                angles.append(AngleTerm(i=nbrs[p], j=j_atom.index, k=nbrs[q_idx], theta0=theta0, k_theta=k_theta))

    dihedrals: List[DihedralTerm] = []
    seen_dihedrals: Set[Tuple[int, int, int, int]] = set()
    for gb in graph.bonds:
        j_idx, k_idx = gb.u, gb.v
        j_nbrs = [n for n in graph.neighbor_indices(j_idx) if n != k_idx]
        k_nbrs = [n for n in graph.neighbor_indices(k_idx) if n != j_idx]
        if not j_nbrs or not k_nbrs:
            continue
        is_planar = gb.aromatic or gb.order >= 2.0
        periodicity = 2 if is_planar else 3
        phase = np.pi if is_planar else 0.0
        k_phi = 15.0 if is_planar else 1.4
        for i_idx in j_nbrs:
            for l_idx in k_nbrs:
                if i_idx == l_idx:
                    continue
                canon = (i_idx, j_idx, k_idx, l_idx)
                rev = (l_idx, k_idx, j_idx, i_idx)
                if canon in seen_dihedrals or rev in seen_dihedrals:
                    continue
                seen_dihedrals.add(canon)
                dihedrals.append(
                    DihedralTerm(
                        i=i_idx,
                        j=j_idx,
                        k=k_idx,
                        l=l_idx,
                        k_phi=k_phi,
                        periodicity=periodicity,
                        phase=phase,
                    )
                )

    impropers: List[ImproperTerm] = []
    for ga in graph.atoms:
        if ga.hybridization == 2 and ga.element in ("C", "N"):
            nbrs = graph.neighbor_indices(ga.index)
            if len(nbrs) == 3:
                impropers.append(
                    ImproperTerm(
                        i=ga.index,
                        j=nbrs[0],
                        k=nbrs[1],
                        l=nbrs[2],
                        omega0=0.0,
                        k_omega=120.0,
                    )
                )

    topo = Topology(
        atoms=atoms,
        bonds=bonds,
        angles=angles,
        dihedrals=dihedrals,
        impropers=impropers,
        constraints=constraints,
        name=name,
    )
    return topo, coords, graph


def build_alkane_chain(
    n_carbons: int = 4,
    constrain_bonds: bool = False,
) -> Tuple[Topology, FloatArray]:
    """Build an all-atom united/explicit alkane chain (e.g., butane) with RB torsions."""
    if n_carbons < 3:
        raise ValueError("Alkane chain requires at least 3 carbons")
    atoms: List[AtomSpec] = []
    bonds: List[BondTerm] = []
    angles: List[AngleTerm] = []
    rb_dihedrals: List[RyckaertBellemansTerm] = []
    constraints: List[ConstraintPair] = []
    coords = np.zeros((n_carbons, 3), dtype=np.float64)

    # Trans zigzag geometry (united-atom CH3/CH2 carbons for crisp dihedral validation)
    r_cc = 0.153
    ang = np.deg2rad(109.5)
    for idx in range(n_carbons):
        is_term = idx == 0 or idx == n_carbons - 1
        atoms.append(
            AtomSpec(
                index=idx,
                name=f"C{idx + 1}",
                element="C",
                residue_name="ALK",
                residue_id=1,
                mass=15.035 if is_term else 14.027,
                charge=0.0,
                sigma=0.3905,
                epsilon=0.4937 if is_term else 0.3905,
                atom_type="CH3" if is_term else "CH2",
                is_hydrophobic=True,
            )
        )
        if idx > 0:
            dx = r_cc * np.sin(ang / 2.0)
            dy = r_cc * np.cos(ang / 2.0) * (1.0 if idx % 2 == 1 else -1.0)
            coords[idx] = coords[idx - 1] + np.array([dx, dy, 0.0])
            if constrain_bonds:
                constraints.append(ConstraintPair(i=idx - 1, j=idx, distance=r_cc))
            else:
                bonds.append(BondTerm(i=idx - 1, j=idx, r0=r_cc, kb=259408.0))

    for idx in range(n_carbons - 2):
        angles.append(AngleTerm(i=idx, j=idx + 1, k=idx + 2, theta0=ang, k_theta=520.0))

    # Standard OPLS/GROMACS Ryckaert-Bellemans alkane parameters (kJ/mol)
    rb_coeffs = (9.2789, 12.1557, -13.1201, -3.0597, 26.2403, -31.4950)
    for idx in range(n_carbons - 3):
        rb_dihedrals.append(
            RyckaertBellemansTerm(i=idx, j=idx + 1, k=idx + 2, l=idx + 3, coefficients=rb_coeffs)
        )

    coords -= np.mean(coords, axis=0)
    topo = Topology(
        atoms=atoms,
        bonds=bonds,
        angles=angles,
        rb_dihedrals=rb_dihedrals,
        constraints=constraints,
        name=f"alkane_C{n_carbons}",
    )
    return topo, coords


def build_solvated_ligand_box(
    smiles: str = "CCO",
    box_length_nm: float = 2.4,
    n_waters: int = 24,
    constrain_solvent: bool = True,
    seed: int = 42,
) -> Tuple[Topology, FloatArray, SimulationBox]:
    """Build a solute from SMILES solvated in explicit 3-site TIP3P water molecules."""
    solute_topo, solute_coords, _ = smiles_to_topology(
        smiles, name="solvated_ligand", residue_name="LIG", is_alchemical=True, seed=seed
    )
    box = SimulationBox.orthorhombic(box_length_nm, box_length_nm, box_length_nm)
    center = np.array([box_length_nm / 2.0] * 3, dtype=np.float64)
    solute_coords = solute_coords - np.mean(solute_coords, axis=0) + center

    atoms = list(solute_topo.atoms)
    bonds = list(solute_topo.bonds)
    angles = list(solute_topo.angles)
    dihedrals = list(solute_topo.dihedrals)
    impropers = list(solute_topo.impropers)
    constraints = list(solute_topo.constraints)
    all_coords = [solute_coords]

    # TIP3P geometry: r_OH = 0.09572 nm, theta_HOH = 104.52 deg
    r_oh = 0.09572
    half_theta = np.deg2rad(104.52 / 2.0)
    r_hh = 2.0 * r_oh * np.sin(half_theta)
    local_water = np.array(
        [
            [0.0, 0.0, 0.0],
            [r_oh * np.sin(half_theta), r_oh * np.cos(half_theta), 0.0],
            [-r_oh * np.sin(half_theta), r_oh * np.cos(half_theta), 0.0],
        ],
        dtype=np.float64,
    )

    # Generate cubic lattice candidate sites excluding solute core radius
    grid_n = max(3, int(np.ceil((n_waters + 8) ** (1.0 / 3.0))))
    spacing = box_length_nm / grid_n
    rng = np.random.default_rng(seed)
    candidates: List[FloatArray] = []
    for gx in range(grid_n):
        for gy in range(grid_n):
            for gz in range(grid_n):
                pt = np.array([(gx + 0.5) * spacing, (gy + 0.5) * spacing, (gz + 0.5) * spacing])
                if float(np.min(np.linalg.norm(solute_coords - pt, axis=1))) > 0.32:
                    candidates.append(pt)
    rng.shuffle(candidates)
    if len(candidates) < n_waters:
        # Relax clearance slightly if tight box
        candidates = []
        for gx in range(grid_n + 1):
            for gy in range(grid_n + 1):
                for gz in range(grid_n + 1):
                    pt = np.array([(gx + 0.5) * box_length_nm / (grid_n + 1),
                                   (gy + 0.5) * box_length_nm / (grid_n + 1),
                                   (gz + 0.5) * box_length_nm / (grid_n + 1)])
                    if float(np.min(np.linalg.norm(solute_coords - pt, axis=1))) > 0.25:
                        candidates.append(pt)
        rng.shuffle(candidates)

    placed_waters = min(n_waters, len(candidates))
    for w_idx in range(placed_waters):
        base_idx = len(atoms)
        res_id = 2 + w_idx
        atoms.extend(
            [
                AtomSpec(
                    index=base_idx,
                    name="OW",
                    element="O",
                    residue_name="SOL",
                    residue_id=res_id,
                    mass=15.9994,
                    charge=-0.834,
                    sigma=0.315061,
                    epsilon=0.636386,
                    atom_type="OW",
                    is_donor=True,
                    is_acceptor=True,
                ),
                AtomSpec(
                    index=base_idx + 1,
                    name="HW1",
                    element="H",
                    residue_name="SOL",
                    residue_id=res_id,
                    mass=1.008,
                    charge=0.417,
                    sigma=0.04,
                    epsilon=0.01,
                    atom_type="HW",
                ),
                AtomSpec(
                    index=base_idx + 2,
                    name="HW2",
                    element="H",
                    residue_name="SOL",
                    residue_id=res_id,
                    mass=1.008,
                    charge=0.417,
                    sigma=0.04,
                    epsilon=0.01,
                    atom_type="HW",
                ),
            ]
        )
        if constrain_solvent:
            constraints.extend(
                [
                    ConstraintPair(base_idx, base_idx + 1, r_oh),
                    ConstraintPair(base_idx, base_idx + 2, r_oh),
                    ConstraintPair(base_idx + 1, base_idx + 2, r_hh),
                ]
            )
        else:
            bonds.extend(
                [
                    BondTerm(base_idx, base_idx + 1, r_oh, 460000.0),
                    BondTerm(base_idx, base_idx + 2, r_oh, 460000.0),
                ]
            )
            angles.append(AngleTerm(base_idx + 1, base_idx, base_idx + 2, np.deg2rad(104.52), 420.0))

        # Random 3D rotation via QR decomposition
        q_mat, _ = np.linalg.qr(rng.normal(size=(3, 3)))
        if np.linalg.det(q_mat) < 0:
            q_mat[:, 0] *= -1.0
        w_coords = (local_water @ q_mat.T) + candidates[w_idx]
        all_coords.append(w_coords)

    coords = np.vstack(all_coords)
    topo = Topology(
        atoms=atoms,
        bonds=bonds,
        angles=angles,
        dihedrals=dihedrals,
        impropers=impropers,
        constraints=constraints,
        name=f"solvated_{smiles}",
    )
    return topo, coords, box


def build_host_guest_complex(
    ligand_smiles: str = "c1ccccc1O",
    box_length_nm: float = 3.2,
    seed: int = 42,
) -> Tuple[Topology, FloatArray, SimulationBox, Tuple[int, ...], Tuple[int, ...]]:
    """Construct a structured receptor binding pocket + SMILES guest ligand.

    Returns ``(topology, coords, box, receptor_indices, ligand_indices)``.
    """
    lig_topo, lig_coords, _ = smiles_to_topology(
        ligand_smiles, name="guest", residue_name="LIG", is_alchemical=True, seed=seed
    )
    box = SimulationBox.orthorhombic(box_length_nm, box_length_nm, box_length_nm)
    center = np.array([box_length_nm / 2.0] * 3, dtype=np.float64)

    # Create a 16-bead receptor binding cleft around the origin, open along +Z for pulling
    pocket_templates = [
        ("C", -0.34, -0.34, -0.30, 0.0, True, False, False),
        ("C", 0.34, -0.34, -0.30, 0.0, True, False, False),
        ("C", -0.34, 0.34, -0.30, 0.0, True, False, False),
        ("C", 0.34, 0.34, -0.30, 0.0, True, False, False),
        ("O", 0.00, 0.00, -0.44, -0.42, False, False, True),
        ("N", -0.42, 0.00, 0.02, -0.36, False, True, True),
        ("N", 0.42, 0.00, 0.02, -0.36, False, True, True),
        ("C", 0.00, -0.42, 0.02, 0.05, True, False, False),
        ("C", 0.00, 0.42, 0.02, 0.05, True, False, False),
        ("C", -0.36, -0.36, 0.24, 0.0, True, False, False),
        ("C", 0.36, -0.36, 0.24, 0.0, True, False, False),
        ("C", -0.36, 0.36, 0.24, 0.0, True, False, False),
        ("C", 0.36, 0.36, 0.24, 0.0, True, False, False),
        ("O", -0.40, 0.00, -0.22, -0.35, False, False, True),
        ("H", -0.36, 0.00, 0.09, 0.28, False, False, False),
        ("H", 0.36, 0.00, 0.09, 0.28, False, False, False),
    ]
    rec_atoms: List[AtomSpec] = []
    rec_coords = np.zeros((len(pocket_templates), 3), dtype=np.float64)
    rec_bonds: List[BondTerm] = []

    for idx, (elem, x, y, z, chg, hyd, don, acc) in enumerate(pocket_templates):
        sig, eps = LJ_TABLE[elem]
        rec_atoms.append(
            AtomSpec(
                index=idx,
                name=f"P{elem}{idx + 1}",
                element=elem,
                residue_name="REC",
                residue_id=1,
                mass=ELEMENT_MASSES[elem] * 2.0,
                charge=chg,
                sigma=sig,
                epsilon=eps * 1.4,
                atom_type=f"REC_{elem}",
                is_alchemical=False,
                is_donor=don,
                is_acceptor=acc,
                is_hydrophobic=hyd,
            )
        )
        rec_coords[idx] = center + np.array([x, y, z])

    # Elastic scaffold bonds keep the receptor pocket structurally rigid yet slightly compliant
    for i in range(len(pocket_templates)):
        for j in range(i + 1, len(pocket_templates)):
            d = float(np.linalg.norm(rec_coords[j] - rec_coords[i]))
            if d < 0.56:
                rec_bonds.append(BondTerm(i=i, j=j, r0=d, kb=6000.0))

    offset = len(rec_atoms)
    lig_atoms = [
        AtomSpec(
            index=offset + a.index,
            name=a.name,
            element=a.element,
            residue_name="LIG",
            residue_id=2,
            mass=a.mass,
            charge=a.charge,
            sigma=a.sigma,
            epsilon=a.epsilon,
            atom_type=a.atom_type,
            is_alchemical=True,
            is_donor=a.is_donor,
            is_acceptor=a.is_acceptor,
            is_hydrophobic=a.is_hydrophobic,
            formal_charge=a.formal_charge,
        )
        for a in lig_topo.atoms
    ]
    lig_bonds = [BondTerm(b.i + offset, b.j + offset, b.r0, b.kb) for b in lig_topo.bonds]
    lig_angles = [AngleTerm(a.i + offset, a.j + offset, a.k + offset, a.theta0, a.k_theta) for a in lig_topo.angles]
    lig_dihedrals = [
        DihedralTerm(d.i + offset, d.j + offset, d.k + offset, d.l + offset, d.k_phi, d.periodicity, d.phase)
        for d in lig_topo.dihedrals
    ]
    lig_constraints = [ConstraintPair(c.i + offset, c.j + offset, c.distance) for c in lig_topo.constraints]

    lig_coords_placed = lig_coords - np.mean(lig_coords, axis=0) + center + np.array([0.0, 0.0, 0.02])
    coords = np.vstack([rec_coords, lig_coords_placed])
    topo = Topology(
        atoms=rec_atoms + lig_atoms,
        bonds=rec_bonds + lig_bonds,
        angles=lig_angles,
        dihedrals=lig_dihedrals,
        constraints=lig_constraints,
        name=f"complex_{ligand_smiles}",
    )
    rec_indices = tuple(range(offset))
    lig_indices = tuple(range(offset, offset + len(lig_atoms)))
    return topo, coords, box, rec_indices, lig_indices


def write_pdb(topology: Topology, positions: FloatArray, box: SimulationBox) -> str:
    """Serialize coordinates and box dimensions to standard PDB format (Angstroms)."""
    lines: List[str] = []
    if box.is_orthorhombic:
        lx, ly, lz = np.diag(box.vectors) * 10.0
        lines.append(f"CRYST1{lx:9.3f}{ly:9.3f}{lz:9.3f}  90.00  90.00  90.00 P 1           1")
    for idx, atom in enumerate(topology.atoms):
        x, y, z = positions[idx] * 10.0
        lines.append(
            f"ATOM  {idx + 1:5d} {atom.name:<4s} {atom.residue_name:>3s} A{atom.residue_id:4d}    "
            f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00          {atom.element:>2s}"
        )
    lines.append("END")
    return "\n".join(lines) + "\n"


def read_pdb_coordinates(pdb_text: str) -> Tuple[FloatArray, Optional[SimulationBox]]:
    """Parse ATOM/HETATM coordinates (converted from Angstrom to nm) and optional CRYST1 box."""
    coords: List[List[float]] = []
    box: Optional[SimulationBox] = None
    for line in pdb_text.splitlines():
        if line.startswith("CRYST1") and len(line) >= 54:
            a = float(line[6:15]) * 0.1
            b = float(line[15:24]) * 0.1
            c = float(line[24:33]) * 0.1
            alpha = float(line[33:40])
            beta = float(line[40:47])
            gamma = float(line[47:54])
            box = SimulationBox.triclinic(a, b, c, alpha, beta, gamma)
        elif line.startswith(("ATOM  ", "HETATM")) and len(line) >= 54:
            x = float(line[30:38]) * 0.1
            y = float(line[38:46]) * 0.1
            z = float(line[46:54]) * 0.1
            coords.append([x, y, z])
    if not coords:
        raise ValueError("No ATOM/HETATM records found in PDB input")
    return np.asarray(coords, dtype=np.float64), box


def write_gro(topology: Topology, positions: FloatArray, box: SimulationBox, title: str = "ChemiVerlet") -> str:
    """Serialize system to GROMACS .gro format (nm)."""
    lines = [title, f"{topology.n_atoms:5d}"]
    for idx, atom in enumerate(topology.atoms):
        x, y, z = positions[idx]
        lines.append(f"{atom.residue_id:5d}{atom.residue_name:<5s}{atom.name:>5s}{idx + 1:5d}{x:8.3f}{y:8.3f}{z:8.3f}")
    v = box.vectors
    if box.is_orthorhombic:
        lines.append(f"  {v[0, 0]:10.5f}  {v[1, 1]:10.5f}  {v[2, 2]:10.5f}")
    else:
        lines.append(
            f"  {v[0, 0]:10.5f}  {v[1, 1]:10.5f}  {v[2, 2]:10.5f}  "
            f"{v[0, 1]:10.5f}  {v[0, 2]:10.5f}  {v[1, 0]:10.5f}  "
            f"{v[1, 2]:10.5f}  {v[2, 0]:10.5f}  {v[2, 1]:10.5f}"
        )
    return "\n".join(lines) + "\n"
