"""Assign PCFF parameters from pcff.frc to a typed molecular graph.

The rules reproduce what EMC v9.4.4 writes for PCFF.

Explicit parameters:
1. Duplicate entries: the highest version wins; for equal versions the first entry in the file wins.
2. Atom types are mapped through #equivalence before the lookup:
   NonB column for the 9-6 LJ terms; Bond column for bonds;
   Angle column for angles, bond-bond, and bond-angle;
   Torsion column for torsions and all torsion cross terms;
   OOP column for Wilson and angle-angle terms.
   Masses use the atom type itself.
3. Entries match forward or reversed.
   A reversed match swaps the left/right blocks of asymmetric cross terms (bond-angle, end-bond-torsion, angle-torsion).
   An entry without a right block is symmetric (right = left).
   Exact entries come first; the five #torsion_3 entries with wildcard ends ('* c_1 o_2 *', '* cp p= *', ...) apply next.
4. Wilson entries I J K L (J central) match any order of the three outer atoms.
5. Reference values of cross terms are copied from the assigned base terms: r0 of the bonds, theta0 of the angles.
6. Missing cross terms are zero, also when the base term is automatic.

Automatic parameters (base terms without an explicit entry; types mapped through #auto_equivalence):
7. Bonds: #quadratic_bond, forward or reversed; K3 = K4 = 0.
8. Angles: #quadratic_angle with (end, apex, end) types; K3 = K4 = 0.
   The two end types are sorted alphabetically (byte order); exact entries match in either orientation,
   wildcard entries match only this sorted orientation, and the priority is exact > *1 > *2 > ... > *9 > *.
9. Torsions: #torsion_1 with (end, center, center, end) types; an entry with fewer wildcards wins.
   E = Kphi [1 + cos(n phi - phi0)] = Kphi [1 - cos(n phi - (phi0 + 180))], so LAMMPS gets K_n = Kphi and phi_n = phi0 + 180 (mod 360).
   n = 0 entries (all with Kphi = 0) are written as K1 = 0, phi1 = 180, as EMC does.
10. Wilson: no automatic parameters are used; a missing explicit entry gives K = chi0 = 0 (EMC does this even where #wilson_out_of_plane cff91_auto has an entry).

Charges:
11. q_i = sum over bonded j of delta_ij from #bond_increments, matched forward (delta_ij) or reversed (delta_ji),
    first with the atom types themselves and then with the Bond Inct column of #auto_equivalence.

Anything still missing (a bond, angle, or torsion without explicit or automatic parameters, or a bond increment) raises an error listing the atom types.
"""

from itertools import permutations
from pathlib import Path

from openmm_pcff.frc import read_frc
from openmm_pcff.ptop import AngleTerm, BondTerm, DihedralTerm, ImproperTerm, ParameterizedTopology
from openmm_pcff.topology import bonded_neighbours, generate_angles, generate_dihedrals, generate_impropers


EQUIVALENCE_COLUMNS = ["nonbond", "bond", "angle", "torsion", "oop"]

AUTO_EQUIVALENCE_COLUMNS = [
    "nonbond",
    "bond_increment",
    "bond",
    "angle_end",
    "angle_apex",
    "torsion_end",
    "torsion_center",
    "oop_end",
    "oop_center",
]

# Short name -> (section name, label) in pcff.frc.
FORCE_FIELD_SECTIONS = {
    "bond_increments": ("bond_increments", "cff91_auto"),
    "quadratic_bond": ("quadratic_bond", "cff91_auto"),
    "quartic_bond": ("quartic_bond", "cff91"),
    "quadratic_angle": ("quadratic_angle", "cff91_auto"),
    "quartic_angle": ("quartic_angle", "cff91"),
    "torsion_1": ("torsion_1", "cff91_auto"),
    "torsion_3": ("torsion_3", "cff91"),
    "wilson": ("wilson_out_of_plane", "cff91"),
    "nonbond": ("nonbond(9-6)", "cff91"),
    "bond_bond": ("bond-bond", "cff91"),
    "bond_bond_13": ("bond-bond_1_3", "cff91"),
    "bond_angle": ("bond-angle", "cff91"),
    "angle_angle": ("angle-angle", "cff91"),
    "end_bond_torsion": ("end_bond-torsion_3", "cff91"),
    "middle_bond_torsion": ("middle_bond-torsion_3", "cff91"),
    "angle_torsion": ("angle-torsion_3", "cff91"),
    "angle_angle_torsion": ("angle-angle-torsion_1", "cff91"),
}


def index_section(rows: list[dict]) -> dict:
    """Return {types: row}; for duplicates the highest version wins, and the first entry wins among equal versions."""
    table = {}

    for row in rows:
        types = row["types"]

        if types not in table or row["version"] > table[types]["version"]:
            table[types] = row

    return table


def load_force_field(frc_path: Path) -> dict:
    """
    Read pcff.frc and index every section used for PCFF.

    Returns a dict with
    masses_amu {type: mass}, equivalence {type: {column: type}}, auto_equivalence {type: {column: type}},
    and one {types: row} table per parameter section, keyed by the short names of FORCE_FIELD_SECTIONS.
    """
    sections = read_frc(frc_path)

    force_field = {}

    force_field["masses_amu"] = {}
    for types, row in index_section(sections[("atom_types", "cff91")]).items():
        force_field["masses_amu"][types[0]] = row["values"][0]

    force_field["equivalence"] = {}
    for types, row in index_section(sections[("equivalence", "cff91")]).items():
        force_field["equivalence"][types[0]] = dict(zip(EQUIVALENCE_COLUMNS, types[1:]))

    force_field["auto_equivalence"] = {}
    for types, row in index_section(sections[("auto_equivalence", "cff91_auto")]).items():
        force_field["auto_equivalence"][types[0]] = dict(zip(AUTO_EQUIVALENCE_COLUMNS, types[1:]))

    for short_name, section_key in FORCE_FIELD_SECTIONS.items():
        force_field[short_name] = index_section(sections[section_key])

    return force_field


def find_forward_or_reversed(table: dict, types: tuple) -> tuple[dict | None, bool]:
    """Return (row, reversed) for an exact match of types or of reversed types, or (None, False)."""
    if types in table:
        return table[types], False

    if types[::-1] in table:
        return table[types[::-1]], True

    return None, False


def equivalent_types(force_field: dict, atom_types: tuple, column: str) -> tuple:
    return tuple(force_field["equivalence"][atom_type][column] for atom_type in atom_types)


def left_right_blocks(values: list[float], block_length: int, reversed_match: bool) -> list[float]:
    """Return left + right blocks oriented to the query; a missing right block means right = left."""
    left = values[:block_length]
    right = values[block_length:]

    if not right:
        right = left

    if reversed_match:
        return right + left

    return left + right


def is_wildcard(frc_type: str) -> bool:
    # '*' alone or numbered ('*1' ... '*9') in the automatic sections.
    return frc_type.startswith("*")


def matches_with_wildcards(entry_types: tuple, query_types: tuple) -> bool:
    return all(is_wildcard(entry_type) or entry_type == query_type for entry_type, query_type in zip(entry_types, query_types))


# --- Automatic parameters ---------------------------------------------------------------------------------


def auto_bond(force_field: dict, atom_types: tuple) -> tuple | None:
    """Rule 7: quadratic bond from the auto-equivalenced types; returns (r0, K2, 0, 0) and the matched entry types."""
    auto_types = tuple(force_field["auto_equivalence"][atom_type]["bond"] for atom_type in atom_types)

    row, reversed_match = find_forward_or_reversed(force_field["quadratic_bond"], auto_types)

    if row is None:
        return None

    r0, k2 = row["values"]
    return (r0, k2, 0.0, 0.0), row["types"]


def auto_angle(force_field: dict, atom_types: tuple) -> tuple | None:
    """Rule 8: quadratic angle from the auto-equivalenced types; returns (theta0, K2, 0, 0) and the matched entry types."""
    auto_equivalence = force_field["auto_equivalence"]
    end_a = auto_equivalence[atom_types[0]]["angle_end"]
    apex = auto_equivalence[atom_types[1]]["angle_apex"]
    end_b = auto_equivalence[atom_types[2]]["angle_end"]

    # EMC builds the lookup key with the end types in sorted order; wildcard entries are compared with this orientation only.
    sorted_key = (min(end_a, end_b), apex, max(end_a, end_b))

    candidates = []

    for entry_types, row in force_field["quadratic_angle"].items():
        n_wildcards = sum(is_wildcard(entry_type) for entry_type in entry_types)

        if n_wildcards == 0:
            if entry_types == sorted_key or entry_types[::-1] == sorted_key:
                candidates.append((0, row))
            continue

        if not matches_with_wildcards(entry_types, sorted_key):
            continue

        # Priority of a wildcard entry: its number (1-9), with an unnumbered '*' last.
        wildcard_numbers = [entry_type[1:] for entry_type in entry_types if is_wildcard(entry_type)]
        if n_wildcards == 1 and wildcard_numbers[0]:
            priority = int(wildcard_numbers[0])
        else:
            priority = 10 + n_wildcards

        candidates.append((priority, row))

    if not candidates:
        return None

    best_priority = min(priority for priority, row in candidates)
    best_rows = [row for priority, row in candidates if priority == best_priority]

    if len(best_rows) > 1:
        raise ValueError(f"Ambiguous automatic angle for {atom_types} ({sorted_key}): {[row['types'] for row in best_rows]}.")

    theta0, k2 = best_rows[0]["values"]
    return (theta0, k2, 0.0, 0.0), best_rows[0]["types"]


def auto_torsion(force_field: dict, atom_types: tuple) -> tuple | None:
    """Rule 9: one-term torsion from the auto-equivalenced types; returns (K1, phi1, K2, phi2, K3, phi3) and the matched entry types."""
    auto_equivalence = force_field["auto_equivalence"]
    auto_types = (
        auto_equivalence[atom_types[0]]["torsion_end"],
        auto_equivalence[atom_types[1]]["torsion_center"],
        auto_equivalence[atom_types[2]]["torsion_center"],
        auto_equivalence[atom_types[3]]["torsion_end"],
    )

    candidates = []

    for entry_types, row in force_field["torsion_1"].items():
        if matches_with_wildcards(entry_types, auto_types) or matches_with_wildcards(entry_types, auto_types[::-1]):
            n_wildcards = sum(is_wildcard(entry_type) for entry_type in entry_types)
            candidates.append((n_wildcards, row))

    if not candidates:
        return None

    fewest_wildcards = min(n_wildcards for n_wildcards, row in candidates)
    best_rows = [row for n_wildcards, row in candidates if n_wildcards == fewest_wildcards]

    if len({tuple(row["values"]) for row in best_rows}) > 1:
        raise ValueError(f"Ambiguous automatic torsion for {atom_types} ({auto_types}): {[row['types'] for row in best_rows]}.")

    k_phi, multiplicity, phi0 = best_rows[0]["values"]
    multiplicity = int(multiplicity)

    # [1 + cos(x)] = [1 - cos(x - 180)], so the LAMMPS phase is phi0 + 180.
    lammps_phase = (phi0 + 180.0) % 360.0

    torsion = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    if multiplicity == 0:
        # A constant; all such entries in pcff.frc have Kphi = 0, and EMC writes them into the n = 1 slot.
        if k_phi != 0.0:
            raise ValueError(f"Automatic torsion with n = 0 and nonzero K for {atom_types}.")
        torsion[1] = lammps_phase
    elif multiplicity in (1, 2, 3):
        torsion[2 * (multiplicity - 1)] = k_phi
        torsion[2 * (multiplicity - 1) + 1] = lammps_phase
    else:
        raise ValueError(f"Automatic torsion with n = {multiplicity} cannot be written as a class2 dihedral for {atom_types}.")

    return tuple(torsion), best_rows[0]["types"]


# --- Term assignment ----------------------------------------------------------------------------------------


def assign_bond(force_field: dict, atom_types: tuple, report: dict) -> tuple | None:
    """Return (r0, K2, K3, K4) for a bond of atom types (type_i, type_j), or None if nothing matches."""
    row, reversed_match = find_forward_or_reversed(force_field["quartic_bond"], equivalent_types(force_field, atom_types, "bond"))

    if row is not None:
        return tuple(row["values"])

    automatic = auto_bond(force_field, atom_types)

    if automatic is None:
        report["missing"].add(("bond", atom_types))
        return None

    quartic, entry_types = automatic
    report["automatic"].add(("bond", atom_types, entry_types))
    return quartic


def assign_angle(force_field: dict, atom_types: tuple, bond_r0: tuple, report: dict) -> dict:
    """
    Return {"quartic": (theta0, K2, K3, K4), "bond_bond": (M, r1, r2), "bond_angle": (N1, N2, r1, r2)}
    for an angle of atom types (type_i, type_j, type_k); bond_r0 is (r0 of i-j, r0 of j-k).
    """
    angle_types = equivalent_types(force_field, atom_types, "angle")

    row, reversed_match = find_forward_or_reversed(force_field["quartic_angle"], angle_types)

    if row is not None:
        quartic = tuple(row["values"])
    else:
        automatic = auto_angle(force_field, atom_types)

        if automatic is None:
            report["missing"].add(("angle", atom_types))
            quartic = None
        else:
            quartic, entry_types = automatic
            report["automatic"].add(("angle", atom_types, entry_types))

    row, reversed_match = find_forward_or_reversed(force_field["bond_bond"], angle_types)
    bond_bond_m = row["values"][0] if row is not None else 0.0

    row, reversed_match = find_forward_or_reversed(force_field["bond_angle"], angle_types)
    bond_angle_n = left_right_blocks(row["values"], 1, reversed_match) if row is not None else [0.0, 0.0]

    return {
        "quartic": quartic,
        "bond_bond": (bond_bond_m, bond_r0[0], bond_r0[1]),
        "bond_angle": (bond_angle_n[0], bond_angle_n[1], bond_r0[0], bond_r0[1]),
    }


def find_explicit_torsion_with_wildcards(force_field: dict, torsion_types: tuple) -> dict | None:
    """Rule 3b: a few #torsion_3 entries have wildcard ends (e.g. '* c_1 o_2 *'); they apply after exact entries and before automatic ones."""
    for entry_types, row in force_field["torsion_3"].items():
        if not any(is_wildcard(entry_type) for entry_type in entry_types):
            continue

        if matches_with_wildcards(entry_types, torsion_types) or matches_with_wildcards(entry_types, torsion_types[::-1]):
            return row

    return None


def assign_dihedral(force_field: dict, atom_types: tuple, bond_r0: tuple, angle_theta0: tuple, report: dict) -> dict:
    """
    Return the DihedralTerm coefficient groups for a dihedral of atom types (type_i, type_j, type_k, type_l).
    bond_r0 is (r0 of i-j, r0 of j-k, r0 of k-l); angle_theta0 is (theta0 of i-j-k, theta0 of j-k-l).
    """
    torsion_types = equivalent_types(force_field, atom_types, "torsion")

    row, reversed_match = find_forward_or_reversed(force_field["torsion_3"], torsion_types)

    if row is None:
        row = find_explicit_torsion_with_wildcards(force_field, torsion_types)

    if row is not None:
        # torsion_3 lists V1 phi1 V2 phi2 V3 phi3; EMC copies them unchanged to LAMMPS K1 phi1 K2 phi2 K3 phi3.
        torsion = tuple(row["values"])
    else:
        automatic = auto_torsion(force_field, atom_types)

        if automatic is None:
            report["missing"].add(("torsion", atom_types))
            torsion = None
        else:
            torsion, entry_types = automatic
            report["automatic"].add(("torsion", atom_types, entry_types))

    row, reversed_match = find_forward_or_reversed(force_field["middle_bond_torsion"], torsion_types)
    middle_bond_torsion_a = row["values"] if row is not None else [0.0, 0.0, 0.0]

    row, reversed_match = find_forward_or_reversed(force_field["end_bond_torsion"], torsion_types)
    end_bond_torsion_bc = left_right_blocks(row["values"], 3, reversed_match) if row is not None else [0.0] * 6

    row, reversed_match = find_forward_or_reversed(force_field["angle_torsion"], torsion_types)
    angle_torsion_de = left_right_blocks(row["values"], 3, reversed_match) if row is not None else [0.0] * 6

    row, reversed_match = find_forward_or_reversed(force_field["angle_angle_torsion"], torsion_types)
    angle_angle_torsion_m = row["values"][0] if row is not None else 0.0

    row, reversed_match = find_forward_or_reversed(force_field["bond_bond_13"], torsion_types)
    bond_bond_13_n = row["values"][0] if row is not None else 0.0

    return {
        "torsion": torsion,
        "middle_bond_torsion": (*middle_bond_torsion_a, bond_r0[1]),
        "end_bond_torsion": (*end_bond_torsion_bc, bond_r0[0], bond_r0[2]),
        "angle_torsion": (*angle_torsion_de, angle_theta0[0], angle_theta0[1]),
        "angle_angle_torsion": (angle_angle_torsion_m, angle_theta0[0], angle_theta0[1]),
        "bond_bond_13": (bond_bond_13_n, bond_r0[0], bond_r0[2]),
    }


def find_wilson(table: dict, oop_types: tuple) -> dict | None:
    """Match a Wilson entry I J K L (J central) to oop_types (i, j, k, l) with any order of the three outer atoms."""
    outer_types = (oop_types[0], oop_types[2], oop_types[3])

    for type_a, type_b, type_c in permutations(outer_types):
        candidate = (type_a, oop_types[1], type_b, type_c)

        if candidate in table:
            return table[candidate]

    return None


def assign_improper(force_field: dict, atom_types: tuple, angle_theta0: tuple, report: dict) -> dict:
    """
    Return {"wilson": (K, chi0), "angle_angle": (M1, M2, M3, theta1, theta2, theta3)} for an improper (i, j, k, l), j central.
    angle_theta0 is (theta0 of i-j-k, theta0 of i-j-l, theta0 of k-j-l).

    LAMMPS couples M1 to (theta_ijk, theta_kjl), M2 to (theta_ijk, theta_ijl), M3 to (theta_ijl, theta_kjl).
    A frc angle-angle entry I J K L couples angles I-J-K and K-J-L, i.e. K is the outer atom shared by both angles.
    """
    oop_types = equivalent_types(force_field, atom_types, "oop")

    row = find_wilson(force_field["wilson"], oop_types)

    if row is not None:
        wilson = tuple(row["values"])
    else:
        wilson = (0.0, 0.0)
        report["zero_wilson"].add((atom_types[1], tuple(sorted((atom_types[0], atom_types[2], atom_types[3])))))

    type_i, type_j, type_k, type_l = oop_types
    angle_angle_m = []

    # Shared outer atom k for M1, i for M2, l for M3; the two other outer atoms are the ends of the entry.
    for end_a, shared, end_b in [(type_i, type_k, type_l), (type_k, type_i, type_l), (type_i, type_l, type_k)]:
        # The entry is symmetric in its two ends, so (end_a, J, shared, end_b) and (end_b, J, shared, end_a) describe the same pair of angles.
        row = force_field["angle_angle"].get((end_a, type_j, shared, end_b))

        if row is None:
            row = force_field["angle_angle"].get((end_b, type_j, shared, end_a))

        angle_angle_m.append(row["values"][0] if row is not None else 0.0)

    return {
        "wilson": wilson,
        "angle_angle": (*angle_angle_m, *angle_theta0),
    }


def bond_increment(force_field: dict, type_i: str, type_j: str) -> float | None:
    """Rule 11: return delta_ij, the charge that bond i-j contributes to atom i, or None if nothing matches."""
    auto_equivalence = force_field["auto_equivalence"]

    for lookup_i, lookup_j in [
        (type_i, type_j),
        (auto_equivalence[type_i]["bond_increment"], auto_equivalence[type_j]["bond_increment"]),
    ]:
        row = force_field["bond_increments"].get((lookup_i, lookup_j))

        if row is not None:
            return row["values"][0]

        row = force_field["bond_increments"].get((lookup_j, lookup_i))

        if row is not None:
            return row["values"][1]

    return None


# --- Whole system -------------------------------------------------------------------------------------------


def parameterize(
    atom_type_names: list[str],
    bonds: list[tuple[int, int]],
    force_field: dict,
    box_lengths_angstrom: tuple[float, float, float] | None,
    lj_cutoff_angstrom: float,
    coulomb_cutoff_angstrom: float | None,
    lj_tail_correction: bool,
) -> tuple[ParameterizedTopology, dict]:
    """
    Build the parameterized topology of a typed molecular graph (0-based atom indices in bonds).

    Returns (topology, report). The report lists, as sorted lists of tuples,
    automatic: (term kind, atom types, matched frc entry types) for every base term taken from the automatic sections,
    zero_wilson: (central type, sorted outer types) for every improper whose Wilson term is zero because no explicit entry exists.
    Raises ValueError if a bond, angle, torsion, or bond increment has no parameter.

    The box and the pair settings are simulation settings, not force-field data; they are copied into the topology unchanged.
    """
    n_atoms = len(atom_type_names)
    report = {"automatic": set(), "zero_wilson": set(), "missing": set()}

    neighbours = bonded_neighbours(n_atoms, bonds)
    angles = generate_angles(neighbours)
    dihedrals = generate_dihedrals(neighbours, bonds)
    impropers = generate_impropers(neighbours)

    def types_of(atoms):
        return tuple(atom_type_names[atom] for atom in atoms)

    # Per-atom data.
    masses_amu = [force_field["masses_amu"][atom_type] for atom_type in atom_type_names]

    charges_e = [0.0] * n_atoms
    for atom_i, atom_j in bonds:
        for atom_a, atom_b in [(atom_i, atom_j), (atom_j, atom_i)]:
            delta = bond_increment(force_field, atom_type_names[atom_a], atom_type_names[atom_b])

            if delta is None:
                report["missing"].add(("bond_increment", types_of((atom_a, atom_b))))
            else:
                charges_e[atom_a] += delta

    # nonbond(9-6) rows are (r*, eps); r* is the position of the minimum, which is sigma in the LAMMPS lj/class2 convention.
    lj_epsilon_kcal_mol = []
    lj_sigma_angstrom = []
    for atom_type in atom_type_names:
        nonbond_type = force_field["equivalence"][atom_type]["nonbond"]
        r_min_angstrom, epsilon_kcal_mol = force_field["nonbond"][(nonbond_type,)]["values"]
        lj_epsilon_kcal_mol.append(epsilon_kcal_mol)
        lj_sigma_angstrom.append(r_min_angstrom)

    topology = ParameterizedTopology(
        atom_type_names=list(atom_type_names),
        masses_amu=masses_amu,
        charges_e=charges_e,
        lj_epsilon_kcal_mol=lj_epsilon_kcal_mol,
        lj_sigma_angstrom=lj_sigma_angstrom,
        box_lengths_angstrom=box_lengths_angstrom,
        lj_cutoff_angstrom=lj_cutoff_angstrom,
        coulomb_cutoff_angstrom=coulomb_cutoff_angstrom,
        lj_tail_correction=lj_tail_correction,
        special_bonds_lj=(0.0, 0.0, 1.0),
        special_bonds_coul=(0.0, 0.0, 1.0),
    )

    # Bonds first: their r0 values are the reference lengths of the cross terms.
    bond_r0 = {}
    for atom_i, atom_j in bonds:
        quartic = assign_bond(force_field, types_of((atom_i, atom_j)), report)
        topology.bonds.append(BondTerm(atoms=(atom_i, atom_j), quartic=quartic))

        r0 = quartic[0] if quartic is not None else None
        bond_r0[(atom_i, atom_j)] = r0
        bond_r0[(atom_j, atom_i)] = r0

    # Angles next: their theta0 values are the reference angles of the torsion and angle-angle cross terms.
    angle_theta0 = {}
    for atoms in angles:
        atom_i, atom_j, atom_k = atoms
        coefficients = assign_angle(force_field, types_of(atoms), (bond_r0[(atom_i, atom_j)], bond_r0[(atom_j, atom_k)]), report)
        topology.angles.append(AngleTerm(atoms=atoms, **coefficients))

        theta0 = coefficients["quartic"][0] if coefficients["quartic"] is not None else None
        angle_theta0[atoms] = theta0
        angle_theta0[atoms[::-1]] = theta0

    for atoms in dihedrals:
        atom_i, atom_j, atom_k, atom_l = atoms
        coefficients = assign_dihedral(
            force_field,
            types_of(atoms),
            (bond_r0[(atom_i, atom_j)], bond_r0[(atom_j, atom_k)], bond_r0[(atom_k, atom_l)]),
            (angle_theta0[(atom_i, atom_j, atom_k)], angle_theta0[(atom_j, atom_k, atom_l)]),
            report,
        )
        topology.dihedrals.append(DihedralTerm(atoms=atoms, **coefficients))

    for atoms in impropers:
        atom_i, atom_j, atom_k, atom_l = atoms
        coefficients = assign_improper(
            force_field,
            types_of(atoms),
            (angle_theta0[(atom_i, atom_j, atom_k)], angle_theta0[(atom_i, atom_j, atom_l)], angle_theta0[(atom_k, atom_j, atom_l)]),
            report,
        )
        topology.impropers.append(ImproperTerm(atoms=atoms, **coefficients))

    if report["missing"]:
        missing_lines = "\n".join(f"  {kind}: {' '.join(types)}" for kind, types in sorted(report["missing"]))
        raise ValueError(f"No PCFF parameters (explicit or automatic) for:\n{missing_lines}")

    report.pop("missing")

    return topology, {key: sorted(entries) for key, entries in report.items()}
