"""Accuracy checks on the relaxed benchmark systems.

1. Precision: forces of every force group on CUDA (mixed precision) vs the Reference platform (double), same settings.
   Criterion: relative RMS difference at most 1e-4 per group and in total.
   CUDA double vs Reference is also reported for the Coulomb group and the total, to show which part of a difference is precision.
   Groups whose forces are zero in the Reference (e.g. bond_bond_13 without aromatic rings) are reported with their largest CUDA force instead.
2. Coulomb accuracy at production settings, against a converged reference (Reference platform, PME tolerance 1e-7):
   - LAMMPS pppm/cg 0.001 and pppm 0.001 (pppm/kk under KOKKOS), total forces of a run-0 force dump of the same configuration;
     all other terms agree between the codes to about 1e-5 relative (tests/test_lammps_reference.py), so the total-force difference measures the Coulomb error;
   - OpenMM PME on CUDA (mixed) at several error tolerances, Coulomb group only, so the single-precision error of the bonded terms does not enter.
   Errors are reported as RMS force error in kcal/mol/Angstrom and relative to the RMS Coulomb force.
   LAMMPS's accuracy is relative to the force between two unit charges 1 Angstrom apart, 332.06 kcal/mol/Angstrom (doc/src/kspace_style.rst),
   while OpenMM's tolerance is "roughly equal to the fractional error in the forces" (OpenMM user guide, 02_running_sims.rst),
   so the same number means different accuracy for PCFF's small partial charges.

Run from the repository root (LAMMPS runs take seconds; the Reference platform takes about a minute per system):

    python scripts/check_gpu_accuracy.py [system ...]
"""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import openmm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_benchmark_systems import BENCHMARK_POLYMERS, LAMMPS_EXECUTABLE, LAMMPS_KOKKOS_ARGUMENTS
from benchmark_tools import (
    BENCHMARK_ROOT,
    build_benchmark_system,
    forces_by_group,
    make_context,
    read_relaxed_benchmark,
    relative_rms_difference,
)
from openmm_pcff.builder import FORCE_GROUPS
from openmm_pcff.lammps_io import read_lammps_forces
from validation.comparison import KCAL_MOL_ANGSTROM_PER_KJ_MOL_NM


PRECISION_CHECK_TOLERANCE = 5e-4
PRECISION_CRITERION = 1e-4

REFERENCE_EWALD_TOLERANCE = 1e-7
OPENMM_EWALD_TOLERANCES = [5e-2, 2e-2, 1e-2, 5e-3, 2e-3, 1e-3, 5e-4, 2e-4, 1e-4]
LAMMPS_KSPACE_STYLES = {"pppm_cg": "pppm/cg 0.001", "pppm": "pppm 0.001"}


def lammps_run0_forces(name: str, case: str, kspace_command: str) -> np.ndarray:
    """Run LAMMPS (KOKKOS) for 0 steps on the relaxed configuration; returns forces in kcal/mol/Angstrom ordered by atom id."""
    case_directory = BENCHMARK_ROOT / name / "accuracy" / case
    case_directory.mkdir(parents=True, exist_ok=True)

    input_lines = [
        "# Run-0 forces for the Coulomb accuracy check, written by scripts/check_gpu_accuracy.py",
        "units\t\treal",
        "atom_style\tfull",
        "boundary\tp p p",
        "read_data\t../../relax/relaxed.data",
        f"include\t\t../../{name}.params",
        f"kspace_style\t{kspace_command}",
        "thermo_style\tcustom pe ebond eangle edihed eimp evdwl ecoul elong etail press",
        "thermo_modify\tformat float %.15g",
        "dump\t\tforces all custom 1 forces.dump id fx fy fz",
        "dump_modify\tforces format float %.15g sort id",
        "run\t\t0",
    ]
    (case_directory / "in.lmp").write_text("\n".join(input_lines) + "\n")

    subprocess.run(
        [str(LAMMPS_EXECUTABLE), *LAMMPS_KOKKOS_ARGUMENTS, "-in", "in.lmp", "-log", "log.lammps", "-screen", "none"],
        cwd=case_directory,
        check=True,
    )

    return read_lammps_forces(case_directory / "forces.dump")


def rms_norm(forces: np.ndarray) -> float:
    return np.sqrt(np.mean(np.sum(forces**2, axis=1)))


def check_system(name: str) -> dict:
    topology, positions_angstrom, velocities = read_relaxed_benchmark(name)
    results = {"n_atoms": len(positions_angstrom), "box_lengths_angstrom": topology.box_lengths_angstrom}

    # 1. Precision: CUDA mixed vs Reference double, same PME tolerance, every force group.
    # Every force group means every sub-term (FORCE_GROUPS), so this check uses the per-sub-term layout.
    system = build_benchmark_system(topology, PRECISION_CHECK_TOLERANCE, merge_bonded=False)
    reference_context = make_context(system, openmm.VerletIntegrator(0.001), "Reference", None, positions_angstrom, None)
    cuda_context = make_context(system, openmm.VerletIntegrator(0.001), "CUDA", "mixed", positions_angstrom, None)

    reference_forces = forces_by_group(reference_context)
    cuda_forces = forces_by_group(cuda_context)

    results["precision_relative_rms"] = {}
    results["precision_zero_groups_largest_cuda_force"] = {}

    for sub_term in reference_forces:
        if np.all(reference_forces[sub_term] == 0.0):
            results["precision_zero_groups_largest_cuda_force"][sub_term] = float(np.abs(cuda_forces[sub_term]).max())
        else:
            results["precision_relative_rms"][sub_term] = relative_rms_difference(cuda_forces[sub_term], reference_forces[sub_term])

    results["precision_criterion_met"] = bool(max(results["precision_relative_rms"].values()) <= PRECISION_CRITERION)

    cuda_double_context = make_context(system, openmm.VerletIntegrator(0.001), "CUDA", "double", positions_angstrom, None)
    results["cuda_double_vs_reference_relative_rms"] = {}

    for sub_term, groups in [("coulomb", {FORCE_GROUPS["coulomb"]}), ("total", set(FORCE_GROUPS.values()))]:
        forces = cuda_double_context.getState(getForces=True, groups=groups).getForces(asNumpy=True).value_in_unit(openmm.unit.kilojoule_per_mole / openmm.unit.nanometer)
        results["cuda_double_vs_reference_relative_rms"][sub_term] = relative_rms_difference(np.array(forces), reference_forces[sub_term])

    # 2. Coulomb accuracy against converged PME (Reference platform, double).
    tight_system = build_benchmark_system(topology, REFERENCE_EWALD_TOLERANCE, merge_bonded=False)
    tight_context = make_context(tight_system, openmm.VerletIntegrator(0.001), "Reference", None, positions_angstrom, None)
    tight_forces = forces_by_group(tight_context)

    tight_total_kcal = tight_forces["total"] * KCAL_MOL_ANGSTROM_PER_KJ_MOL_NM
    tight_coulomb_kcal = tight_forces["coulomb"] * KCAL_MOL_ANGSTROM_PER_KJ_MOL_NM
    coulomb_rms_kcal = rms_norm(tight_coulomb_kcal)
    results["total_rms_force_kcal_mol_angstrom"] = rms_norm(tight_total_kcal)
    results["coulomb_rms_force_kcal_mol_angstrom"] = coulomb_rms_kcal

    coulomb_errors = {}

    for case, kspace_command in LAMMPS_KSPACE_STYLES.items():
        lammps_forces = lammps_run0_forces(name, case, kspace_command)
        error_kcal = rms_norm(lammps_forces - tight_total_kcal)
        coulomb_errors[f"lammps {kspace_command}"] = {"rms_error_kcal_mol_angstrom": error_kcal, "relative_to_coulomb_rms": error_kcal / coulomb_rms_kcal}

    for tolerance in OPENMM_EWALD_TOLERANCES:
        context = make_context(build_benchmark_system(topology, tolerance, merge_bonded=False), openmm.VerletIntegrator(0.001), "CUDA", "mixed", positions_angstrom, None)
        state = context.getState(getForces=True, groups={FORCE_GROUPS["coulomb"]})
        coulomb_forces_kcal = np.array(state.getForces(asNumpy=True).value_in_unit(openmm.unit.kilojoule_per_mole / openmm.unit.nanometer)) * KCAL_MOL_ANGSTROM_PER_KJ_MOL_NM

        pme_parameters = [force for force in context.getSystem().getForces() if isinstance(force, openmm.NonbondedForce)][0].getPMEParametersInContext(context)
        error_kcal = rms_norm(coulomb_forces_kcal - tight_coulomb_kcal)
        coulomb_errors[f"openmm pme {tolerance:g}"] = {
            "rms_error_kcal_mol_angstrom": error_kcal,
            "relative_to_coulomb_rms": error_kcal / coulomb_rms_kcal,
            "alpha_per_nm_and_grid": [pme_parameters[0], pme_parameters[1], pme_parameters[2], pme_parameters[3]],
        }

    results["coulomb_errors"] = coulomb_errors
    return results


if __name__ == "__main__":
    names = sys.argv[1:] or list(BENCHMARK_POLYMERS)

    for name in names:
        results = check_system(name)
        output_path = BENCHMARK_ROOT / name / "accuracy" / "accuracy.json"
        output_path.write_text(json.dumps(results, indent=2) + "\n")
        print(json.dumps({name: results}, indent=2))
