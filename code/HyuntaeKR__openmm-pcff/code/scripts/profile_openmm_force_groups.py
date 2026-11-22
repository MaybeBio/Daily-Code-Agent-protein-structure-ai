"""GPU time per force group in OpenMM (CUDA, mixed precision) on the relaxed benchmark systems.

The per-group getState timing of scripts/benchmark_openmm.py is dominated by a fixed cost per call (synchronization and copying forces to the host).
Here each set of force groups is evaluated repeatedly on the GPU without leaving it, by a CustomIntegrator whose step reads the forces ("x = x + zero*v; v = v + zero*f")
with its integration force groups set to that set; positions never change, no neighbor list is rebuilt, and nothing is copied to the host until the end of the timed loop.
The fixed cost of such a step without any force evaluation is measured too ("no forces").
The PME reciprocal-space part is put in its own force group, so Coulomb is split into direct space (erfc pair sum) and reciprocal space (PME grid).
The cost of a full MD step that is not force evaluation (integration, neighbor-list rebuilds, PME/nonbonded stream overlap) is the VerletIntegrator step time minus the all-groups evaluation time.
LAYOUT is the bonded-force layout of openmm_pcff.builder.build_system: per_sub_term (one force per sub-term) or merged (one force per family, merge_bonded=True).
Results go to benchmark/<system>/openmm/profile_<layout>_tolerance_<tolerance>.json.
Run from the repository root:

    python scripts/profile_openmm_force_groups.py EWALD_TOLERANCE LAYOUT [system ...]
"""

import json
import sys
from pathlib import Path

import openmm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_benchmark_systems import BENCHMARK_POLYMERS
from benchmark_tools import BENCHMARK_ROOT, build_benchmark_system, make_context, read_relaxed_benchmark, time_md_steps
from openmm_pcff.builder import FORCE_GROUPS, MERGED_FORCE_GROUPS


TIMESTEP_PS = 0.001
N_EVALUATIONS = 2000
N_MD_STEPS = 5000

# Force group for the PME reciprocal-space part of the Coulomb force (FORCE_GROUPS and MERGED_FORCE_GROUPS use 1-14).
RECIPROCAL_SPACE_GROUP = 15

LAYOUT_FORCE_GROUPS = {"per_sub_term": FORCE_GROUPS, "merged": MERGED_FORCE_GROUPS}
LAYOUT_NONBONDED_NAMES = {"per_sub_term": ("lj_9_6", "coulomb"), "merged": ("evdwl", "ecoul+elong")}


def evaluation_integrator(groups: set[int] | None) -> openmm.CustomIntegrator:
    """An integrator whose step evaluates the forces of the given groups (None: no forces) and leaves the state unchanged."""
    integrator = openmm.CustomIntegrator(TIMESTEP_PS)

    # A literal 0 would be simplified away by OpenMM's expression parser (0*f -> 0), so the zero factor is a global variable.
    integrator.addGlobalVariable("zero", 0.0)

    # Assigning x (unchanged) marks the cached forces invalid, so they are recomputed every step.
    integrator.addComputePerDof("x", "x + zero*v")

    if groups is not None:
        # "f" is the force of the integration force groups only; the zero factor keeps v unchanged.
        integrator.addComputePerDof("v", "v + zero*f")
        integrator.setIntegrationForceGroups(groups)

    return integrator


def profile_system(name: str, ewald_error_tolerance: float, layout: str) -> dict:
    topology, positions_angstrom, velocities = read_relaxed_benchmark(name)

    system = build_benchmark_system(topology, ewald_error_tolerance, merge_bonded=(layout == "merged"))
    coulomb_force = [force for force in system.getForces() if isinstance(force, openmm.NonbondedForce)][0]
    coulomb_force.setReciprocalSpaceForceGroup(RECIPROCAL_SPACE_GROUP)

    force_groups = LAYOUT_FORCE_GROUPS[layout]
    lj_name, coulomb_name = LAYOUT_NONBONDED_NAMES[layout]

    group_sets = {name: {group} for name, group in force_groups.items()}
    group_sets[coulomb_name] = {force_groups[coulomb_name], RECIPROCAL_SPACE_GROUP}
    group_sets["coulomb direct space"] = {force_groups[coulomb_name]}
    group_sets["coulomb reciprocal space"] = {RECIPROCAL_SPACE_GROUP}
    group_sets["all bonded"] = {group for name, group in force_groups.items() if name not in (lj_name, coulomb_name)}
    group_sets["all"] = set(force_groups.values()) | {RECIPROCAL_SPACE_GROUP}
    group_sets["no forces"] = None

    milliseconds_per_evaluation = {}

    for label, groups in group_sets.items():
        context = make_context(system, evaluation_integrator(groups), "CUDA", "mixed", positions_angstrom, None)

        # Warm-up compiles the kernels and sizes the neighbor list.
        context.getIntegrator().step(100)

        seconds = time_md_steps(context, N_EVALUATIONS)
        milliseconds_per_evaluation[label] = seconds / N_EVALUATIONS * 1000.0
        del context

    # Full NVE step for comparison, same system (the separate reciprocal-space group does not change the forces).
    context = make_context(system, openmm.VerletIntegrator(TIMESTEP_PS), "CUDA", "mixed", positions_angstrom, velocities)
    context.getIntegrator().step(1000)
    md_step_ms = time_md_steps(context, N_MD_STEPS) / N_MD_STEPS * 1000.0

    pme_parameters = coulomb_force.getPMEParametersInContext(context)

    return {
        "layout": layout,
        "ewald_error_tolerance": ewald_error_tolerance,
        "pme_alpha_per_nm_and_grid": [pme_parameters[0], pme_parameters[1], pme_parameters[2], pme_parameters[3]],
        "n_evaluations": N_EVALUATIONS,
        "ms_per_evaluation": milliseconds_per_evaluation,
        "md_nve_ms_per_step": md_step_ms,
        "md_step_minus_all_evaluation_ms": md_step_ms - milliseconds_per_evaluation["all"],
    }


if __name__ == "__main__":
    ewald_error_tolerance = float(sys.argv[1])
    layout = sys.argv[2]
    names = sys.argv[3:] or list(BENCHMARK_POLYMERS)

    if layout not in LAYOUT_FORCE_GROUPS:
        raise ValueError(f"LAYOUT must be one of {list(LAYOUT_FORCE_GROUPS)}.")

    for name in names:
        results = profile_system(name, ewald_error_tolerance, layout)

        output_path = BENCHMARK_ROOT / name / "openmm" / f"profile_{layout}_tolerance_{ewald_error_tolerance:g}.json"
        output_path.write_text(json.dumps(results, indent=2) + "\n")
        print(json.dumps({name: results}, indent=2), flush=True)
