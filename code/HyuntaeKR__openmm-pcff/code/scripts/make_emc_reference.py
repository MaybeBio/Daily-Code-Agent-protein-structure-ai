"""Build the reference systems with EMC (typing and parameters by EMC, used as the reference for openmm_pcff).

For every system this writes reference/<system>/input.esh and runs, in that directory,
    emc.pl input.esh                 -> build.emc
    emc_linux_x86_64 build.emc       -> <system>.data, <system>.params (+ by-products that are not tracked)
EMC builds take about a second each.

The systems and their SMILES are defined in validation/reference_systems.py (EMC_SYSTEMS), so that the tests use the same molecules.
butane and polyethylene were built by hand from their own input.esh and are not rebuilt here.
Run from the repository root:

    python scripts/make_emc_reference.py [system ...]
"""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from validation.reference_systems import EMC_SYSTEMS, REFERENCE_ROOT


# Same settings as butane and polyethylene: density 0.5 g/cc keeps the boxes above twice the 9.5 Angstrom cutoff with few atoms.
DENSITY_G_CC = 0.5
SEED = 2026

ESH_HEADER = """# EMC chemistry file, written by {script} ({purpose}).
#
# Prepare (from this directory):
#   emc.pl input.esh                              -> build.emc
#   emc_linux_x86_64 build.emc                    -> {name}.data, {name}.params
#
# Notes:
# - Columns are separated by tabs (EMC manual, Sec. 4.5.2).
# - No field_location: EMC uses its own PCFF files (EMC_ROOT/field/cff/pcff, the default field location).
# - {description}
"""


def options_section(name: str, n_atoms_total: int, density_g_cc: float) -> list[str]:
    return [
        "ITEM\tOPTIONS",
        "",
        f"project\t{name}",
        f"seed\t{SEED}",
        "",
        "replace\ttrue",
        "build_dir\t.",
        "field\tpcff",
        "field_id\tpcff",
        f"density\t{density_g_cc}",
        f"ntotal\t{n_atoms_total}",
        "",
        "ITEM\tEND",
        "",
    ]


def write_input_esh(name: str, system: dict, directory: Path, density_g_cc: float, script: str, purpose: str) -> None:
    """Write directory/input.esh for one system of the EMC_SYSTEMS form; the force field is EMC's own PCFF."""
    header = ESH_HEADER.format(script=script, purpose=purpose, name=name, description=system["description"])
    lines = header.splitlines() + [""]
    lines += options_section(name, system["n_atoms_total"], density_g_cc)

    if system["kind"] == "molecules":
        # One group and one cluster per molecule; clusters get equal mole fractions.
        lines += ["ITEM\tGROUPS", ""]
        lines += [f"{group}\t{smiles}" for group, smiles in system["groups"].items()]
        lines += ["", "ITEM\tEND", "", "ITEM\tCLUSTERS", ""]
        lines += [f"{group}\t{group}\t1" for group in system["groups"]]
        lines += ["", "ITEM\tEND"]

    elif system["kind"] == "polymer":
        # Repeat unit with connection points 1 and 2 (head-to-tail), end groups attached to connection 1 and 2 of the repeat unit.
        lines += ["ITEM\tGROUPS", ""]
        lines += [f"repeat\t{system['repeat_group']}\t1\trepeat:2"]
        lines += [f"{group}\t{smiles}\t1\trepeat:{connection}" for group, (smiles, connection) in system["end_groups"].items()]
        lines += ["", "ITEM\tEND", "", "ITEM\tCLUSTERS", "", "poly\talternate\t1", "", "ITEM\tEND", "", "ITEM\tPOLYMERS", "", "poly"]
        end_group_counts = "\t".join(f"{group}\t1" for group in system["end_groups"])
        lines += [f"1\trepeat\t{system['n_repeat_units']}\t{end_group_counts}", "", "ITEM\tEND"]

    (directory / "input.esh").write_text("\n".join(lines) + "\n")


def run_emc(name: str, system_directory: Path) -> None:
    # EMC_ROOT: the EMC installation directory (environment variable).
    emc_root = Path(os.environ["EMC_ROOT"])

    subprocess.run(["perl", str(emc_root / "scripts/emc.pl"), "input.esh"], cwd=system_directory, check=True, capture_output=True)

    result = subprocess.run([str(emc_root / "bin/emc_linux_x86_64"), "build.emc"], cwd=system_directory, capture_output=True, text=True)

    if result.returncode != 0 or not (system_directory / f"{name}.params").exists():
        emc_messages = [line for line in (result.stdout + result.stderr).splitlines() if line.startswith(("Warning", "Error"))]
        raise RuntimeError(f"EMC failed for {name}:\n" + "\n".join(emc_messages))


if __name__ == "__main__":
    names = sys.argv[1:] or list(EMC_SYSTEMS)

    for name in names:
        system_directory = REFERENCE_ROOT / name
        system_directory.mkdir(exist_ok=True)
        write_input_esh(
            name,
            EMC_SYSTEMS[name],
            system_directory,
            DENSITY_G_CC,
            script="scripts/make_emc_reference.py",
            purpose="reference: EMC typing and parameters",
        )
        run_emc(name, system_directory)
        print(f"{name} done")
