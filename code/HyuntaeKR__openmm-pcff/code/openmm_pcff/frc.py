"""Read a Biosym/Accelrys .frc force-field file (pcff.frc as shipped with EMC).

The file is a sequence of sections, each starting with '#<section name> <label>'.
Data rows start with a version number and a reference number, followed by a fixed number of type columns and then numeric values.
Lines starting with '!' (column headers), '>' (formula comments), and '@' (directives) are not data.

Only the parsing is done here; the lookup rules live in openmm_pcff/assign.py.
"""

from pathlib import Path


# Number of atom-type columns per section, in file order.
# The equivalence tables are type + 5 (explicit) or type + 9 (automatic) type-name columns.
TYPE_COLUMNS_PER_SECTION = {
    "equivalence": 6,
    "auto_equivalence": 10,
    "bond_increments": 2,
    "quadratic_bond": 2,
    "quartic_bond": 2,
    "quadratic_angle": 3,
    "quartic_angle": 3,
    "torsion_1": 4,
    "torsion_3": 4,
    "wilson_out_of_plane": 4,
    "nonbond(9-6)": 1,
    "bond-bond": 3,
    "bond-bond_1_3": 4,
    "bond-angle": 3,
    "angle-angle": 4,
    "end_bond-torsion_3": 4,
    "middle_bond-torsion_3": 4,
    "angle-torsion_3": 4,
    "angle-angle-torsion_1": 4,
}

# Header blocks (#define, #version, #reference, #end) and the torsion-torsion_1 section, which is empty in pcff.frc and has no LAMMPS class2 counterpart.
IGNORED_SECTIONS = ["define", "version", "reference", "end", "torsion-torsion_1"]


def read_frc(frc_path: Path) -> dict:
    """
    Read all parameter sections of an .frc file.

    Returns {(section name, label): list of rows}, where label is e.g. 'cff91' or 'cff91_auto'.
    Each row is a dict with keys
    version (float), reference (int), types (tuple of str), values (list of float), line_number (int, 1-based).
    The atom_types section rows instead have values [mass] and extra keys element and n_connections.
    Rows are kept in file order; duplicates are kept, so that the lookup can apply an explicit duplicate rule.
    """
    sections = {}
    current_key = None

    for line_number, line in enumerate(frc_path.read_text().splitlines(), start=1):
        stripped = line.strip()

        if not stripped:
            continue

        if stripped.startswith("#"):
            header_fields = stripped[1:].split()
            section_name = header_fields[0]

            if section_name in IGNORED_SECTIONS:
                current_key = None
                continue

            if section_name != "atom_types" and section_name not in TYPE_COLUMNS_PER_SECTION:
                raise ValueError(f"{frc_path}:{line_number}: unknown section '#{section_name}'.")

            label = header_fields[1]
            current_key = (section_name, label)

            if current_key in sections:
                raise ValueError(f"{frc_path}:{line_number}: section {current_key} appears twice.")

            sections[current_key] = []
            continue

        if current_key is None or stripped[0] in "!>@":
            continue

        fields = stripped.split()
        section_name = current_key[0]

        if section_name == "atom_types":
            # Columns: version reference type mass element connection [charge] [comment ...]
            row = {
                "version": float(fields[0]),
                "reference": int(fields[1]),
                "types": (fields[2],),
                "values": [float(fields[3])],
                "element": fields[4],
                "n_connections": int(fields[5]),
                "line_number": line_number,
            }
        else:
            n_type_columns = TYPE_COLUMNS_PER_SECTION[section_name]
            row = {
                "version": float(fields[0]),
                "reference": int(fields[1]),
                "types": tuple(fields[2 : 2 + n_type_columns]),
                "values": [float(value) for value in fields[2 + n_type_columns :]],
                "line_number": line_number,
            }

            if len(row["types"]) != n_type_columns:
                raise ValueError(f"{frc_path}:{line_number}: expected {n_type_columns} type columns in #{section_name}.")

        sections[current_key].append(row)

    return sections
