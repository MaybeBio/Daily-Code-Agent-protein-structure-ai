"""Read EMC-written LAMMPS files (.data and .params) into a ParameterizedTopology, and read LAMMPS reference output.

Only the subset written by EMC for PCFF is supported: atom_style full, orthorhombic box, class2 styles,
lj/class2 pair styles with per-type (i i) coefficients, and special_bonds lj/coul 0 0 1.
Anything else raises an error instead of being silently ignored.
"""

import re
from pathlib import Path

import numpy as np

from openmm_pcff.ptop import AngleTerm, BondTerm, DihedralTerm, ImproperTerm, ParameterizedTopology


DATA_SECTION_NAMES = ["Masses", "Atoms", "Bonds", "Angles", "Dihedrals", "Impropers"]

SUPPORTED_PAIR_STYLES = ["lj/class2", "lj/class2/coul/cut", "lj/class2/coul/long"]

# LAMMPS thermo column labels for the thermo_style custom keywords used in the reference inputs.
THERMO_LABEL_TO_KEYWORD = {
    "PotEng": "pe",
    "E_bond": "ebond",
    "E_angle": "eangle",
    "E_dihed": "edihed",
    "E_impro": "eimp",
    "E_vdwl": "evdwl",
    "E_coul": "ecoul",
    "E_long": "elong",
    "E_tail": "etail",
    "Press": "press",
}


def read_data_file(data_path: Path) -> dict:
    """
    Read a LAMMPS data file (atom_style full) as written by EMC.

    Returns a dictionary with
    box_lengths_angstrom, type_masses_amu {type: mass}, type_names {type: name from the Masses comment},
    atom_types, charges_e, positions_angstrom (N x 3 array, as stored, i.e. unwrapped for EMC files),
    and bonds, angles, dihedrals, impropers as lists of (type, (0-based atom indices...)).
    """
    lines = data_path.read_text().splitlines()

    # Header: counts and box.
    box_bounds = {}
    section_lines = {}
    current_section = None

    for line in lines[1:]:
        content = line.split("#")[0].strip()
        comment = line.split("#", 1)[1].strip() if "#" in line else ""

        if content in DATA_SECTION_NAMES:
            current_section = content
            section_lines[current_section] = []
            continue

        if not content:
            continue

        if current_section is not None:
            section_lines[current_section].append((content.split(), comment))
            continue

        fields = content.split()

        if fields[-2:] in (["xlo", "xhi"], ["ylo", "yhi"], ["zlo", "zhi"]):
            box_bounds[fields[-2][0]] = (float(fields[0]), float(fields[1]))
        elif fields[-3:] == ["xy", "xz", "yz"]:
            raise ValueError(f"{data_path}: triclinic boxes are not supported.")

    unknown_sections = [name for name in section_lines if name not in DATA_SECTION_NAMES]
    if unknown_sections:
        raise ValueError(f"{data_path}: unsupported sections {unknown_sections}.")

    box_lengths_angstrom = tuple(box_bounds[axis][1] - box_bounds[axis][0] for axis in "xyz")

    # Masses: type mass # name
    type_masses_amu = {}
    type_names = {}

    for fields, comment in section_lines["Masses"]:
        atom_type = int(fields[0])
        type_masses_amu[atom_type] = float(fields[1])
        type_names[atom_type] = comment

    # Atoms (atom_style full): id mol type q x y z, optionally followed by image flags.
    atom_records = []

    for fields, comment in section_lines["Atoms"]:
        # Image flags would mean the stored coordinates are wrapped; EMC writes unwrapped coordinates without them.
        if len(fields) != 7:
            raise ValueError(f"{data_path}: expected 'id mol type q x y z' in Atoms, got {len(fields)} fields.")

        atom_records.append(
            (
                int(fields[0]),
                int(fields[2]),
                float(fields[3]),
                [float(fields[4]), float(fields[5]), float(fields[6])],
            )
        )

    atom_records.sort(key=lambda record: record[0])
    atom_ids = [record[0] for record in atom_records]

    # Atom ids are mapped to 0-based indices by subtracting 1, which requires ids 1..N.
    if atom_ids != list(range(1, len(atom_ids) + 1)):
        raise ValueError(f"{data_path}: atom ids must be 1..N without gaps.")

    atom_types = [record[1] for record in atom_records]
    charges_e = [record[2] for record in atom_records]
    positions_angstrom = np.array([record[3] for record in atom_records])

    # Terms: id type atom1 ... atomN, converted to (type, 0-based atom indices) in file order.
    terms = {}
    atoms_per_term = {"Bonds": 2, "Angles": 3, "Dihedrals": 4, "Impropers": 4}

    for section, n_atoms in atoms_per_term.items():
        terms[section] = []

        for fields, comment in section_lines.get(section, []):
            if len(fields) != 2 + n_atoms:
                raise ValueError(f"{data_path}: malformed line in {section}: {fields}")

            term_type = int(fields[1])
            atom_indices = tuple(int(value) - 1 for value in fields[2:])
            terms[section].append((term_type, atom_indices))

    return {
        "box_lengths_angstrom": box_lengths_angstrom,
        "type_masses_amu": type_masses_amu,
        "type_names": type_names,
        "atom_types": atom_types,
        "charges_e": charges_e,
        "positions_angstrom": positions_angstrom,
        "bonds": terms["Bonds"],
        "angles": terms["Angles"],
        "dihedrals": terms["Dihedrals"],
        "impropers": terms["Impropers"],
    }


def read_params_file(params_path: Path) -> dict:
    """
    Read an EMC .params file (LAMMPS commands) for class2 styles.

    Returns a dictionary with pair settings and per-type coefficient tuples in LAMMPS order:
    pair_style, lj_cutoff_angstrom, coulomb_cutoff_angstrom, lj_tail_correction, special_bonds_lj, special_bonds_coul,
    pair_coeffs {type: (epsilon, sigma)},
    bond_coeffs {type: (r0, K2, K3, K4)},
    angle_coeffs {type: {"quartic": ..., "bb": ..., "ba": ...}},
    dihedral_coeffs {type: {"torsion": ..., "mbt": ..., "ebt": ..., "at": ..., "aat": ..., "bb13": ...}},
    improper_coeffs {type: {"wilson": ..., "aa": ...}}.
    """
    index_variables = {}
    params = {
        "pair_style": None,
        "lj_tail_correction": False,
        "special_bonds_lj": None,
        "special_bonds_coul": None,
        "pair_coeffs": {},
        "bond_coeffs": {},
        "angle_coeffs": {},
        "dihedral_coeffs": {},
        "improper_coeffs": {},
    }

    for line in params_path.read_text().splitlines():
        content = line.split("#")[0].strip()

        if not content:
            continue

        # Substitute ${name} with index-style variables defined earlier in the file.
        content = re.sub(r"\$\{(\w+)\}", lambda match: index_variables[match.group(1)], content)

        fields = content.split()
        command = fields[0]
        arguments = fields[1:]

        if command == "variable":
            # LAMMPS keeps the first definition of an index variable.
            if arguments[1] == "index" and arguments[0] not in index_variables:
                index_variables[arguments[0]] = arguments[2]

        elif command == "mass":
            # Masses are taken from the data file.
            pass

        elif command == "pair_style":
            pair_style = arguments[0]

            if pair_style not in SUPPORTED_PAIR_STYLES:
                raise ValueError(f"{params_path}: unsupported pair_style {pair_style}.")

            params["pair_style"] = pair_style
            params["lj_cutoff_angstrom"] = float(arguments[1])

            if pair_style == "lj/class2":
                params["coulomb_cutoff_angstrom"] = None
            elif len(arguments) > 2:
                params["coulomb_cutoff_angstrom"] = float(arguments[2])
            else:
                params["coulomb_cutoff_angstrom"] = float(arguments[1])

        elif command in ("bond_style", "angle_style", "dihedral_style", "improper_style"):
            if arguments != ["class2"]:
                raise ValueError(f"{params_path}: unsupported {command} {arguments}.")

        elif command == "pair_modify":
            for keyword, value in zip(arguments[0::2], arguments[1::2]):
                if keyword == "mix" and value != "sixthpower":
                    raise ValueError(f"{params_path}: only 'pair_modify mix sixthpower' is supported.")
                elif keyword == "tail":
                    params["lj_tail_correction"] = value == "yes"
                elif keyword not in ("mix", "table"):
                    raise ValueError(f"{params_path}: unsupported pair_modify keyword {keyword}.")

        elif command == "special_bonds":
            # Accept "lj/coul w12 w13 w14" or "lj w12 w13 w14 coul w12 w13 w14".
            position = 0
            while position < len(arguments):
                keyword = arguments[position]
                weights = tuple(float(value) for value in arguments[position + 1 : position + 4])

                if keyword in ("lj/coul", "lj"):
                    params["special_bonds_lj"] = weights
                if keyword in ("lj/coul", "coul"):
                    params["special_bonds_coul"] = weights
                if keyword not in ("lj/coul", "lj", "coul"):
                    raise ValueError(f"{params_path}: unsupported special_bonds keyword {keyword}.")

                position += 4

        elif command == "pair_coeff":
            type_i = int(arguments[0])
            type_j = int(arguments[1])

            # Unlike pairs must come from sixth-power mixing, which is what the builder implements.
            if type_i != type_j:
                raise ValueError(f"{params_path}: explicit unlike-pair coefficients ({type_i} {type_j}) are not supported.")

            params["pair_coeffs"][type_i] = (float(arguments[2]), float(arguments[3]))

        elif command == "bond_coeff":
            params["bond_coeffs"][int(arguments[0])] = tuple(float(value) for value in arguments[1:5])

        elif command in ("angle_coeff", "dihedral_coeff", "improper_coeff"):
            term_type = int(arguments[0])
            base_name = {"angle_coeff": "quartic", "dihedral_coeff": "torsion", "improper_coeff": "wilson"}[command]

            # A keyword (bb, ba, mbt, ...) after the type marks a cross-term line; otherwise it is the base term.
            if re.fullmatch(r"[a-z]+[0-9]*", arguments[1]):
                sub_term = arguments[1]
                values = tuple(float(value) for value in arguments[2:])
            else:
                sub_term = base_name
                values = tuple(float(value) for value in arguments[1:])

            coefficient_table = params[command.replace("_coeff", "_coeffs")]
            coefficient_table.setdefault(term_type, {})[sub_term] = values

        else:
            raise ValueError(f"{params_path}: unsupported command '{command}'.")

    if params["pair_style"] is None:
        raise ValueError(f"{params_path}: no pair_style found.")

    return params


# Number of coefficients of every sub-term, in LAMMPS order.
SUB_TERM_COEFFICIENT_COUNTS = {
    "angle_coeffs": {"quartic": 4, "bb": 3, "ba": 4},
    "dihedral_coeffs": {"torsion": 6, "mbt": 4, "ebt": 8, "at": 8, "aat": 3, "bb13": 3},
    "improper_coeffs": {"wilson": 2, "aa": 6},
}


def check_coefficients_complete(params: dict, data: dict, params_path: Path) -> None:
    """Every type used in the data file must have every sub-term, with the right number of coefficients."""
    used_types = {
        "pair_coeffs": set(data["atom_types"]),
        "bond_coeffs": {term_type for term_type, atoms in data["bonds"]},
        "angle_coeffs": {term_type for term_type, atoms in data["angles"]},
        "dihedral_coeffs": {term_type for term_type, atoms in data["dihedrals"]},
        "improper_coeffs": {term_type for term_type, atoms in data["impropers"]},
    }

    for table_name, types in used_types.items():
        for term_type in sorted(types):
            if term_type not in params[table_name]:
                raise ValueError(f"{params_path}: no {table_name} entry for type {term_type}.")

            if table_name in ("pair_coeffs", "bond_coeffs"):
                continue

            for sub_term, n_coefficients in SUB_TERM_COEFFICIENT_COUNTS[table_name].items():
                values = params[table_name][term_type].get(sub_term)

                if values is None or len(values) != n_coefficients:
                    raise ValueError(f"{params_path}: {table_name} type {term_type} '{sub_term}' missing or has wrong length.")


def read_emc_lammps(data_path: Path, params_path: Path) -> tuple[ParameterizedTopology, np.ndarray]:
    """
    Build the parameterized topology from an EMC LAMMPS .data and .params pair.
    Returns (topology, positions in Angstrom as stored in the data file).
    The atom order of every term is kept exactly as in the data file.
    """
    data = read_data_file(data_path)
    params = read_params_file(params_path)

    check_coefficients_complete(params, data, params_path)

    # Only 1-2 and 1-3 exclusion with full-strength 1-4 pairs is implemented in the builder.
    if params["special_bonds_lj"] != (0.0, 0.0, 1.0) or params["special_bonds_coul"] != (0.0, 0.0, 1.0):
        raise ValueError(f"{params_path}: only 'special_bonds lj/coul 0 0 1' is supported.")

    atom_types = data["atom_types"]

    topology = ParameterizedTopology(
        atom_type_names=[data["type_names"][atom_type] for atom_type in atom_types],
        masses_amu=[data["type_masses_amu"][atom_type] for atom_type in atom_types],
        charges_e=data["charges_e"],
        lj_epsilon_kcal_mol=[params["pair_coeffs"][atom_type][0] for atom_type in atom_types],
        lj_sigma_angstrom=[params["pair_coeffs"][atom_type][1] for atom_type in atom_types],
        box_lengths_angstrom=data["box_lengths_angstrom"],
        lj_cutoff_angstrom=params["lj_cutoff_angstrom"],
        coulomb_cutoff_angstrom=params["coulomb_cutoff_angstrom"],
        lj_tail_correction=params["lj_tail_correction"],
        special_bonds_lj=params["special_bonds_lj"],
        special_bonds_coul=params["special_bonds_coul"],
    )

    for bond_type, atoms in data["bonds"]:
        topology.bonds.append(
            BondTerm(
                atoms=atoms,
                quartic=params["bond_coeffs"][bond_type],
            )
        )

    for angle_type, atoms in data["angles"]:
        coefficients = params["angle_coeffs"][angle_type]
        topology.angles.append(
            AngleTerm(
                atoms=atoms,
                quartic=coefficients["quartic"],
                bond_bond=coefficients["bb"],
                bond_angle=coefficients["ba"],
            )
        )

    for dihedral_type, atoms in data["dihedrals"]:
        coefficients = params["dihedral_coeffs"][dihedral_type]
        topology.dihedrals.append(
            DihedralTerm(
                atoms=atoms,
                torsion=coefficients["torsion"],
                middle_bond_torsion=coefficients["mbt"],
                end_bond_torsion=coefficients["ebt"],
                angle_torsion=coefficients["at"],
                angle_angle_torsion=coefficients["aat"],
                bond_bond_13=coefficients["bb13"],
            )
        )

    for improper_type, atoms in data["impropers"]:
        coefficients = params["improper_coeffs"][improper_type]
        topology.impropers.append(
            ImproperTerm(
                atoms=atoms,
                wilson=coefficients["wilson"],
                angle_angle=coefficients["aa"],
            )
        )

    return topology, data["positions_angstrom"]


def read_lammps_thermo(log_path: Path) -> dict[str, float]:
    """Read the single thermo line of a run-0 LAMMPS log; returns {thermo keyword: value} in LAMMPS real units."""
    lines = log_path.read_text().splitlines()

    for line_index, line in enumerate(lines):
        labels = line.split()

        if labels and labels[0] == "PotEng":
            values = [float(value) for value in lines[line_index + 1].split()]
            return {THERMO_LABEL_TO_KEYWORD[label]: value for label, value in zip(labels, values)}

    raise ValueError(f"{log_path}: no thermo output found.")


def read_lammps_forces(dump_path: Path) -> np.ndarray:
    """Read a 'dump custom id fx fy fz' file of one snapshot; returns forces in kcal/mol/Angstrom ordered by atom id."""
    lines = dump_path.read_text().splitlines()
    header_index = next(index for index, line in enumerate(lines) if line.startswith("ITEM: ATOMS"))

    if lines[header_index].split()[2:] != ["id", "fx", "fy", "fz"]:
        raise ValueError(f"{dump_path}: expected columns 'id fx fy fz'.")

    table = np.array([[float(value) for value in line.split()] for line in lines[header_index + 1 :] if line.strip()])
    table = table[np.argsort(table[:, 0])]

    return table[:, 1:]
