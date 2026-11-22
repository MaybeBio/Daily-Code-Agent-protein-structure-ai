"""Generate LAMMPS single-point reference data.

For every system in reference/<system>/ (EMC .data + .params) this writes one directory per case,
reference/<system>/singlepoint/<case>/, containing the LAMMPS input, the case-specific .params copy,
the LAMMPS log (energies by thermo keyword), and a dump of per-atom forces.

Cases:

    periodic_pppm      production settings: lj/class2/coul/long 9.5 9.5, tail yes, kspace pppm/cg 0.001
    periodic_ewald     same pair style, kspace ewald 1e-10 and pair_modify table 0 (tight Coulomb reference)
    periodic_nocoul    pair_style lj/class2 9.5, tail yes, no kspace (bonded + LJ only)
    isolated           molecule 1 alone, non-periodic, lj/class2/coul/cut 100 100, no tail, no kspace
    isolated_modified  as isolated, with nonzero Wilson K and chi0, nonzero bb13 N, and a 30 degree torsion phase

butane and polyethylene get all cases.
The EMC-built systems (validation/reference_systems.py, EMC_SYSTEMS) get periodic_nocoul, periodic_ewald, and isolated; their own chemistry
already has nonzero Wilson, bb13, and torsion phase terms, so isolated_modified is not needed.

The script only reads the EMC files; it never modifies them.
Run from the repository root:

    python scripts/make_lammps_reference.py [system ...]
"""

import re
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from validation.reference_systems import EMC_SYSTEMS


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
REFERENCE_ROOT = REPOSITORY_ROOT / "reference"
# LAMMPS executable, found on PATH.
LAMMPS_EXECUTABLE = "lmp"

ALL_CASES = ["periodic_pppm", "periodic_ewald", "periodic_nocoul", "isolated", "isolated_modified"]
EMC_SYSTEM_CASES = ["periodic_ewald", "periodic_nocoul", "isolated"]

SYSTEM_CASES = {"butane": ALL_CASES, "polyethylene": ALL_CASES}
SYSTEM_CASES.update({name: EMC_SYSTEM_CASES for name in EMC_SYSTEMS})

# Cutoff for the isolated-molecule cases; it must exceed every intramolecular distance so that the cutoff sum equals the full sum.
ISOLATED_CUTOFF_ANGSTROM = 100.0

# Margin added around the molecule for the non-periodic box of the isolated cases.
ISOLATED_BOX_MARGIN_ANGSTROM = 10.0

PERIODIC_CASES = {
    "periodic_pppm": {
        "pair_style": "pair_style\tlj/class2/coul/long ${cutoff} ${charge_cutoff}",
        "pair_modify": "pair_modify\tmix sixthpower tail yes",
        "kspace": ["kspace_style\tpppm/cg 0.001"],
    },
    "periodic_ewald": {
        "pair_style": "pair_style\tlj/class2/coul/long ${cutoff} ${charge_cutoff}",
        # Direct erfc evaluation instead of the default Coulomb table, to keep only the Ewald accuracy in the reference.
        "pair_modify": "pair_modify\tmix sixthpower tail yes table 0",
        "kspace": ["kspace_style\tewald 1e-10"],
    },
    "periodic_nocoul": {
        "pair_style": "pair_style\tlj/class2 ${cutoff}",
        "pair_modify": "pair_modify\tmix sixthpower tail yes",
        "kspace": [],
    },
}

ISOLATED_PAIR_STYLE = f"pair_style\tlj/class2/coul/cut {ISOLATED_CUTOFF_ANGSTROM} {ISOLATED_CUTOFF_ANGSTROM}"
ISOLATED_PAIR_MODIFY = "pair_modify\tmix sixthpower tail no"

# Coefficient changes for the isolated_modified case, by LAMMPS line prefix and type index.
# These values are not physical; they make the terms that are zero in alkanes contribute, so that their implementation can be compared with LAMMPS.
MODIFIED_COEFFICIENTS = {
    # improper_coeff type K chi0
    ("improper_coeff", "1"): "8.0 0.0",
    ("improper_coeff", "2"): "5.0 3.0",
    ("improper_coeff", "3"): "12.0 -4.0",
    # dihedral_coeff type bb13 N r1 r3
    ("dihedral_coeff", "1 bb13"): "2.5 1.53 1.53",
    ("dihedral_coeff", "2 bb13"): "-1.7 1.53 1.101",
    ("dihedral_coeff", "3 bb13"): "3.1 1.101 1.101",
    # dihedral_coeff type K1 phi1 K2 phi2 K3 phi3: a 30 degree phase tests the sign convention of the dihedral angle.
    ("dihedral_coeff", "1"): "0.3 30.0 0.0514 0.0 -0.143 0.0",
}

THERMO_KEYWORDS = "pe ebond eangle edihed eimp evdwl ecoul elong etail press"


def replace_line(params_text: str, line_prefix: str, new_line: str) -> str:
    """Replace the single line that starts with line_prefix (a LAMMPS command) by new_line."""
    pattern = re.compile(rf"^{line_prefix}\s.*$", re.MULTILINE)
    matches = pattern.findall(params_text)

    if len(matches) != 1:
        raise ValueError(f"Expected exactly one '{line_prefix}' line, found {len(matches)}.")

    return pattern.sub(lambda match: new_line, params_text)


def modify_coefficients(params_text: str) -> str:
    """Apply MODIFIED_COEFFICIENTS, keeping the trailing type comment of each line."""
    for (command, type_and_keyword), new_values in MODIFIED_COEFFICIENTS.items():
        # Match e.g. "dihedral_coeff\t1 bb13   0.0 1.53 1.53  # c,c,c,c" but not "dihedral_coeff\t1 mbt ...".
        pattern = re.compile(
            rf"^({command}\s+{re.escape(type_and_keyword)})((?:\s+-?[0-9.]+)+)(\s+#.*)$",
            re.MULTILINE,
        )
        matches = pattern.findall(params_text)

        if len(matches) != 1:
            raise ValueError(f"Expected exactly one '{command} {type_and_keyword}' line, found {len(matches)}.")

        params_text = pattern.sub(lambda match: f"{match.group(1)} {new_values}{match.group(3)}", params_text)

    return params_text


def write_single_molecule_data(full_data_path: Path, molecule_id: int, output_path: Path) -> float:
    """
    Write a LAMMPS data file containing only one molecule of full_data_path, renumbered from 1.
    Returns the largest intramolecular distance in Angstrom.
    The box is the coordinate range plus a margin; it is used with non-periodic boundaries.
    """
    lines = full_data_path.read_text().splitlines()

    section_names = {"Masses", "Atoms", "Bonds", "Angles", "Dihedrals", "Impropers"}
    sections = {}
    current_section = None
    header_lines = []

    for line in lines:
        stripped = line.strip()

        if stripped.split("#")[0].strip() in section_names:
            current_section = stripped.split("#")[0].strip()
            sections[current_section] = []
            continue

        if current_section is None:
            header_lines.append(line)
        elif stripped:
            sections[current_section].append(line)

    # Atoms (atom_style full): id mol type q x y z # comment
    old_to_new_atom_id = {}
    kept_atom_lines = []
    coordinates = []

    for line in sections["Atoms"]:
        fields = line.split()

        if int(fields[1]) != molecule_id:
            continue

        new_id = len(old_to_new_atom_id) + 1
        old_to_new_atom_id[int(fields[0])] = new_id
        comment = line[line.index("#"):] if "#" in line else ""
        kept_atom_lines.append(f"{new_id:8d} {fields[1]:>7} {fields[2]:>3} {fields[3]:>7}  {fields[4]:>16} {fields[5]:>16} {fields[6]:>16}  {comment}")
        coordinates.append([float(fields[4]), float(fields[5]), float(fields[6])])

    coordinates = np.array(coordinates)

    # Terms: id type atom1 ... atomN # comment; keep only terms whose atoms all belong to the molecule.
    kept_term_lines = {}

    for section in ["Bonds", "Angles", "Dihedrals", "Impropers"]:
        kept_term_lines[section] = []

        # Water has no dihedrals or impropers, so EMC writes no such sections.
        for line in sections.get(section, []):
            fields = line.split("#")[0].split()
            atom_ids = [int(value) for value in fields[2:]]

            if not all(atom_id in old_to_new_atom_id for atom_id in atom_ids):
                continue

            new_term_id = len(kept_term_lines[section]) + 1
            new_atom_ids = " ".join(f"{old_to_new_atom_id[atom_id]:7d}" for atom_id in atom_ids)
            comment = line[line.index("#"):] if "#" in line else ""
            kept_term_lines[section].append(f"{new_term_id:8d} {fields[1]:>7} {new_atom_ids}  {comment}")

    # Count lines and type counts of the header are rewritten; type counts stay as in the full system so the .params file applies unchanged.
    type_count_lines = [line for line in header_lines if line.strip().endswith("types")]

    box_low = coordinates.min(axis=0) - ISOLATED_BOX_MARGIN_ANGSTROM
    box_high = coordinates.max(axis=0) + ISOLATED_BOX_MARGIN_ANGSTROM

    output = [
        f"Molecule {molecule_id} of {full_data_path.name}, written by scripts/make_lammps_reference.py",
        "",
        f"{len(kept_atom_lines):12d}  atoms",
        f"{len(kept_term_lines['Bonds']):12d}  bonds",
        f"{len(kept_term_lines['Angles']):12d}  angles",
        f"{len(kept_term_lines['Dihedrals']):12d}  dihedrals",
        f"{len(kept_term_lines['Impropers']):12d}  impropers",
        "",
        *type_count_lines,
        "",
        f"{box_low[0]:16.8f} {box_high[0]:16.8f}  xlo xhi",
        f"{box_low[1]:16.8f} {box_high[1]:16.8f}  ylo yhi",
        f"{box_low[2]:16.8f} {box_high[2]:16.8f}  zlo zhi",
        "",
        "Masses",
        "",
        *sections["Masses"],
        "",
        "Atoms",
        "",
        *kept_atom_lines,
    ]

    for section in ["Bonds", "Angles", "Dihedrals", "Impropers"]:
        if kept_term_lines[section]:
            output += ["", section, "", *kept_term_lines[section]]

    output_path.write_text("\n".join(output) + "\n")

    pair_distances = np.sqrt(((coordinates[:, None, :] - coordinates[None, :, :]) ** 2).sum(axis=-1))

    return pair_distances.max()


def write_lammps_input(case_directory: Path, data_file_name: str, params_file_name: str, boundary: str, kspace_lines: list[str]) -> None:
    """Write a run-0 LAMMPS input that prints energies by thermo keyword and dumps per-atom forces."""
    input_lines = [
        f"# Single-point reference, written by scripts/make_lammps_reference.py",
        "",
        "units\t\treal",
        "atom_style\tfull",
        f"boundary\t{boundary}",
        "",
        f"read_data\t{data_file_name}",
        f"include\t\t{params_file_name}",
        *kspace_lines,
        "",
        f"thermo_style\tcustom {THERMO_KEYWORDS}",
        "thermo_modify\tformat float %.15g",
        "",
        "dump\t\tforces all custom 1 forces.dump id fx fy fz",
        "dump_modify\tforces format float %.15g sort id",
        "",
        "run\t\t0",
    ]

    (case_directory / "in.lmp").write_text("\n".join(input_lines) + "\n")


def run_lammps(case_directory: Path) -> None:
    subprocess.run(
        [str(LAMMPS_EXECUTABLE), "-in", "in.lmp", "-log", "log.lammps", "-screen", "none"],
        cwd=case_directory,
        check=True,
    )


def make_system_reference(system: str, cases: list[str]) -> None:
    system_directory = REFERENCE_ROOT / system
    full_data_path = system_directory / f"{system}.data"
    params_text = (system_directory / f"{system}.params").read_text()

    singlepoint_directory = system_directory / "singlepoint"

    # Periodic cases use the original data file and differ only in pair style, tail, and kspace settings.
    for case, settings in PERIODIC_CASES.items():
        if case not in cases:
            continue

        case_directory = singlepoint_directory / case
        case_directory.mkdir(parents=True, exist_ok=True)

        case_params = replace_line(params_text, "pair_style", settings["pair_style"])
        case_params = replace_line(case_params, "pair_modify", settings["pair_modify"])
        (case_directory / f"{system}.params").write_text(case_params)

        write_lammps_input(
            case_directory,
            data_file_name=f"../../{system}.data",
            params_file_name=f"{system}.params",
            boundary="p p p",
            kspace_lines=settings["kspace"],
        )
        run_lammps(case_directory)
        print(f"{system}/{case} done")

    # Isolated cases: molecule 1 alone, non-periodic, all pairs inside the cutoff.
    isolated_params = replace_line(params_text, "pair_style", ISOLATED_PAIR_STYLE)
    isolated_params = replace_line(isolated_params, "pair_modify", ISOLATED_PAIR_MODIFY)

    for case in ["isolated", "isolated_modified"]:
        if case not in cases:
            continue

        case_directory = singlepoint_directory / case
        case_directory.mkdir(parents=True, exist_ok=True)

        largest_distance = write_single_molecule_data(full_data_path, molecule_id=1, output_path=case_directory / f"{system}_molecule1.data")

        if largest_distance >= ISOLATED_CUTOFF_ANGSTROM:
            raise ValueError(f"{system}: largest intramolecular distance {largest_distance:.1f} A exceeds the isolated cutoff.")

        if case == "isolated":
            case_params = isolated_params
        else:
            case_params = modify_coefficients(isolated_params)

        (case_directory / f"{system}.params").write_text(case_params)

        write_lammps_input(
            case_directory,
            data_file_name=f"{system}_molecule1.data",
            params_file_name=f"{system}.params",
            boundary="f f f",
            kspace_lines=[],
        )
        run_lammps(case_directory)
        print(f"{system}/{case} done (largest intramolecular distance {largest_distance:.2f} A)")


if __name__ == "__main__":
    for system in sys.argv[1:] or SYSTEM_CASES:
        make_system_reference(system, SYSTEM_CASES[system])
