"""OpenMM speed on the relaxed benchmark systems (CUDA, mixed precision, 1 fs).

For each system, starting from the LAMMPS relaxed positions and velocities:
- MD speed in ns/day for NVE (VerletIntegrator), NVT (NoseHooverIntegrator, 300 K, collision frequency 10/ps = 1/(100 fs) as LAMMPS Tdamp),
  and NPT (NVT + MonteCarloBarostat at 1 atm, 300 K, attempt every 25 steps; OpenMM has no Nose-Hoover barostat);
- time of one force evaluation per force group and for all groups (getState with forces, so it includes copying forces to the host).
The PME error tolerance must be given; it is chosen from scripts/check_gpu_accuracy.py.
LAYOUT is the bonded-force layout of openmm_pcff.builder.build_system: per_sub_term (one force per sub-term) or merged (one force per family, merge_bonded=True).
Results go to benchmark/<system>/openmm/benchmark_<layout>_tolerance_<tolerance>.json.
Run from the repository root:

    python scripts/benchmark_openmm.py EWALD_TOLERANCE LAYOUT [system ...]
"""

import json
import sys
from pathlib import Path

import openmm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_benchmark_systems import BENCHMARK_POLYMERS, TEMPERATURE_K
from benchmark_tools import BENCHMARK_ROOT, build_benchmark_system, make_context, read_relaxed_benchmark, time_force_evaluations, time_md_steps
from openmm_pcff.builder import FORCE_GROUPS, MERGED_FORCE_GROUPS


TIMESTEP_PS = 0.001
NOSE_HOOVER_COLLISION_FREQUENCY_PER_PS = 10.0
PRESSURE_BAR = 1.01325
BAROSTAT_FREQUENCY = 25

WARMUP_STEPS = 1000
TARGET_TIMING_SECONDS = 30.0
N_FORCE_EVALUATIONS = 50

LAYOUT_FORCE_GROUPS = {"per_sub_term": FORCE_GROUPS, "merged": MERGED_FORCE_GROUPS}


def integrator_for(ensemble: str) -> openmm.Integrator:
    if ensemble == "nve":
        return openmm.VerletIntegrator(TIMESTEP_PS)
    return openmm.NoseHooverIntegrator(TEMPERATURE_K, NOSE_HOOVER_COLLISION_FREQUENCY_PER_PS, TIMESTEP_PS)


def benchmark_md(topology, positions_angstrom, velocities, ewald_error_tolerance: float, layout: str, ensemble: str) -> dict:
    system = build_benchmark_system(topology, ewald_error_tolerance, merge_bonded=(layout == "merged"))

    if ensemble == "npt":
        system.addForce(openmm.MonteCarloBarostat(PRESSURE_BAR, TEMPERATURE_K, BAROSTAT_FREQUENCY))

    context = make_context(system, integrator_for(ensemble), "CUDA", "mixed", positions_angstrom, velocities)

    # Warm-up (kernel compilation, neighbor list sizing), then a short run to choose the length of the timed run.
    context.getIntegrator().step(WARMUP_STEPS)
    seconds_per_step = time_md_steps(context, WARMUP_STEPS) / WARMUP_STEPS
    n_steps = max(WARMUP_STEPS, int(TARGET_TIMING_SECONDS / seconds_per_step))

    seconds = time_md_steps(context, n_steps)
    simulated_ns = n_steps * TIMESTEP_PS / 1000.0

    return {"n_steps": n_steps, "seconds": seconds, "ns_per_day": simulated_ns / seconds * 86400.0, "ms_per_step": seconds / n_steps * 1000.0}


def benchmark_force_groups(topology, positions_angstrom, ewald_error_tolerance: float, layout: str) -> dict:
    system = build_benchmark_system(topology, ewald_error_tolerance, merge_bonded=(layout == "merged"))
    context = make_context(system, openmm.VerletIntegrator(TIMESTEP_PS), "CUDA", "mixed", positions_angstrom, None)
    force_groups = LAYOUT_FORCE_GROUPS[layout]

    milliseconds = {}
    for name, group in force_groups.items():
        milliseconds[name] = time_force_evaluations(context, {group}, N_FORCE_EVALUATIONS) * 1000.0

    milliseconds["all groups"] = time_force_evaluations(context, set(force_groups.values()), N_FORCE_EVALUATIONS) * 1000.0

    return milliseconds


if __name__ == "__main__":
    ewald_error_tolerance = float(sys.argv[1])
    layout = sys.argv[2]
    names = sys.argv[3:] or list(BENCHMARK_POLYMERS)

    if layout not in LAYOUT_FORCE_GROUPS:
        raise ValueError(f"LAYOUT must be one of {list(LAYOUT_FORCE_GROUPS)}.")

    for name in names:
        topology, positions_angstrom, velocities = read_relaxed_benchmark(name)

        results = {
            "platform": "CUDA",
            "precision": "mixed",
            "layout": layout,
            "ewald_error_tolerance": ewald_error_tolerance,
            "openmm_version": openmm.__version__,
            "md": {ensemble: benchmark_md(topology, positions_angstrom, velocities, ewald_error_tolerance, layout, ensemble) for ensemble in ["nve", "nvt", "npt"]},
            "force_evaluation_ms": benchmark_force_groups(topology, positions_angstrom, ewald_error_tolerance, layout),
        }

        output_directory = BENCHMARK_ROOT / name / "openmm"
        output_directory.mkdir(exist_ok=True)
        (output_directory / f"benchmark_{layout}_tolerance_{ewald_error_tolerance:g}.json").write_text(json.dumps(results, indent=2) + "\n")
        print(json.dumps({name: results}, indent=2))
