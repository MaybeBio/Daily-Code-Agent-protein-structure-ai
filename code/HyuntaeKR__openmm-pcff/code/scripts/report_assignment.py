"""Print the summary of openmm_pcff typing and parameters against EMC, and openmm_pcff-parameterized OpenMM energies against LAMMPS.

For every reference system: the number of parameter differences from EMC (expected 0), the automatic parameters used,
the atoms whose type ignores a template hybridization test (listed below the row),
and the largest relative energy difference per LAMMPS case (bonded and LJ pair terms; Coulomb after removing LAMMPS's erfc approximation).
With --automatic, also list every automatic parameter (atom types and the matched pcff.frc entry).
The pass/fail criteria are asserted by tests/test_assignment.py.
Run from the repository root:

    python scripts/report_assignment.py [--automatic] [system ...]
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openmm_pcff.lammps_io import read_emc_lammps
from validation.comparison import compare_case, openmm_pcff_topology_like, parameter_differences
from validation.reference_systems import EMC_SYSTEMS, SYSTEMS, case_files


def largest_relative_energy_difference(comparison: dict) -> float:
    largest = 0.0

    for keyword, (lammps_energy, openmm_energy) in comparison["keyword_energies"].items():
        if keyword == "evdwl" and "lj_tail" in comparison:
            # Pair sum only; the tail corrections differ by the documented pair-counting convention.
            lammps_energy -= comparison["lammps_thermo"]["etail"]
            openmm_energy -= comparison["lj_tail"]["openmm_measured"]

        if keyword == "ecoul+elong" and "lammps_erfc_error" in comparison:
            openmm_energy += comparison["lammps_erfc_error"]

        if lammps_energy != 0.0:
            largest = max(largest, abs(openmm_energy - lammps_energy) / abs(lammps_energy))

    return largest


if __name__ == "__main__":
    arguments = sys.argv[1:]
    list_automatic = "--automatic" in arguments
    system_names = [argument for argument in arguments if argument != "--automatic"] or SYSTEMS + list(EMC_SYSTEMS)

    print(f"{'system':<22} {'param diffs':>11} {'automatic':>9} {'zero Wilson':>11} {'hybrid.':>7}   largest relative energy difference / largest force difference (kcal/mol/A)")

    for system_name in system_names:
        files = case_files(system_name, "periodic_nocoul")
        emc_topology, positions = read_emc_lammps(files["data"], files["params"])
        topology, report = openmm_pcff_topology_like(system_name, files["data"], emc_topology)
        differences = parameter_differences(topology, emc_topology)

        case_summaries = []
        for case in ["isolated", "periodic_nocoul", "periodic_ewald"]:
            comparison = compare_case(system_name, case, parameter_source="openmm_pcff")
            force_difference = np.abs(comparison["openmm_forces"] - comparison["lammps_forces"]).max()
            case_summaries.append(f"{case} {largest_relative_energy_difference(comparison):.1e} / {force_difference:.1e}")

        print(f"{system_name:<22} {len(differences):>11} {len(report['automatic']):>9} {len(report['zero_wilson']):>11} {len(report['hybridization_mismatches']):>7}   {'; '.join(case_summaries)}")

        for difference in differences:
            print(f"    {difference}")

        for smiles, atom_index, atom_type, hybridization in report["hybridization_mismatches"]:
            print(f"    hybridization: {smiles} atom {atom_index} typed {atom_type}, RDKit {hybridization}")

        if list_automatic:
            for kind, atom_types, entry_types in report["automatic"]:
                print(f"    automatic {kind:<8} {' '.join(atom_types):<24} from {' '.join(entry_types)}")
