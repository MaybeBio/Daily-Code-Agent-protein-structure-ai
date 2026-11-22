"""Checks of the merged bonded layout (build_system(..., merge_bonded=True)) on the relaxed benchmark systems.

1. Code: merged layout on CUDA in double precision against the per-sub-term layout on the Reference platform,
   for all bonded groups together and for bonded + LJ (Coulomb is left out because the two platforms' PME implementations differ).
2. Precision: merged layout on CUDA, mixed against double precision, per merged force group and in total.
Relative RMS force differences (scripts/benchmark_tools.py, relative_rms_difference); criterion for 2: at most 1e-4.
PME tolerance 5e-4.
Results go to benchmark/<system>/accuracy/merged_layout.json.
Run from the repository root (the Reference platform takes about a minute per system):

    python scripts/check_merged_layout.py [system ...]
"""

import json
import sys
from pathlib import Path

import numpy as np
import openmm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_benchmark_systems import BENCHMARK_POLYMERS
from benchmark_tools import BENCHMARK_ROOT, build_benchmark_system, make_context, read_relaxed_benchmark, relative_rms_difference
from openmm_pcff.builder import FORCE_GROUPS, MERGED_FORCE_GROUPS


EWALD_ERROR_TOLERANCE = 5e-4
PRECISION_CRITERION = 1e-4

PER_SUB_TERM_BONDED_GROUPS = {group for sub_term, group in FORCE_GROUPS.items() if sub_term not in ("lj_9_6", "coulomb")}
MERGED_BONDED_GROUPS = {MERGED_FORCE_GROUPS[keyword] for keyword in ["ebond", "eangle", "edihed", "eimp"]}


def group_forces(context: openmm.Context, groups: set[int]) -> np.ndarray:
    forces = context.getState(getForces=True, groups=groups).getForces(asNumpy=True)
    return np.array(forces.value_in_unit(openmm.unit.kilojoule_per_mole / openmm.unit.nanometer))


def check_system(name: str) -> dict:
    topology, positions_angstrom, velocities = read_relaxed_benchmark(name)

    per_sub_term_system = build_benchmark_system(topology, EWALD_ERROR_TOLERANCE, merge_bonded=False)
    merged_system = build_benchmark_system(topology, EWALD_ERROR_TOLERANCE, merge_bonded=True)

    reference_context = make_context(per_sub_term_system, openmm.VerletIntegrator(0.001), "Reference", None, positions_angstrom, None)
    merged_double_context = make_context(merged_system, openmm.VerletIntegrator(0.001), "CUDA", "double", positions_angstrom, None)
    merged_mixed_context = make_context(merged_system, openmm.VerletIntegrator(0.001), "CUDA", "mixed", positions_angstrom, None)

    results = {"ewald_error_tolerance": EWALD_ERROR_TOLERANCE}

    # 1. Code check against the validated layout.
    lj_group = FORCE_GROUPS["lj_9_6"]
    results["merged_cuda_double_vs_per_sub_term_reference_relative_rms"] = {
        "all bonded": relative_rms_difference(group_forces(merged_double_context, MERGED_BONDED_GROUPS), group_forces(reference_context, PER_SUB_TERM_BONDED_GROUPS)),
        "bonded + lj": relative_rms_difference(
            group_forces(merged_double_context, MERGED_BONDED_GROUPS | {MERGED_FORCE_GROUPS["evdwl"]}),
            group_forces(reference_context, PER_SUB_TERM_BONDED_GROUPS | {lj_group}),
        ),
    }

    # 2. Precision: mixed against double on the same platform.
    precision = {}
    for keyword, group in MERGED_FORCE_GROUPS.items():
        precision[keyword] = relative_rms_difference(group_forces(merged_mixed_context, {group}), group_forces(merged_double_context, {group}))

    all_groups = set(MERGED_FORCE_GROUPS.values())
    precision["total"] = relative_rms_difference(group_forces(merged_mixed_context, all_groups), group_forces(merged_double_context, all_groups))

    results["merged_cuda_mixed_vs_double_relative_rms"] = precision
    results["precision_criterion_met"] = bool(max(precision.values()) <= PRECISION_CRITERION)

    return results


if __name__ == "__main__":
    names = sys.argv[1:] or list(BENCHMARK_POLYMERS)

    for name in names:
        results = check_system(name)
        output_path = BENCHMARK_ROOT / name / "accuracy" / "merged_layout.json"
        output_path.write_text(json.dumps(results, indent=2) + "\n")
        print(json.dumps({name: results}, indent=2), flush=True)
