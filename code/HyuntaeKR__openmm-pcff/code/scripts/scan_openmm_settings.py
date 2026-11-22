"""OpenMM settings that do not change the model, timed on the relaxed benchmark systems (CUDA, mixed precision, NVE, 1 fs).

Scanned:
- PME error tolerance (sets the Ewald alpha and the PME grid); the Coulomb error at each tolerance is in benchmark/<system>/accuracy/accuracy.json;
- the CUDA platform property DisablePmeStream (by default PME runs on its own CUDA stream, overlapping the other forces).
Each case: 1000 warm-up steps, then N_STEPS timed steps.
Results go to benchmark/<system>/openmm/settings_scan.json.
Run from the repository root:

    python scripts/scan_openmm_settings.py [system ...]
"""

import json
import sys
from pathlib import Path

import openmm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_benchmark_systems import BENCHMARK_POLYMERS
from benchmark_tools import BENCHMARK_ROOT, NM_PER_PS_PER_ANGSTROM_PER_FS, build_benchmark_system, read_relaxed_benchmark, time_md_steps
from openmm_pcff.units import NM_PER_ANGSTROM


TIMESTEP_PS = 0.001
WARMUP_STEPS = 1000
N_STEPS = 10000

EWALD_ERROR_TOLERANCES = [2e-2, 1e-2, 5e-3, 2e-3, 1e-3, 5e-4, 2e-4, 1e-4]
DISABLE_PME_STREAM_TOLERANCE = 5e-4


def time_nve(topology, positions_angstrom, velocities, ewald_error_tolerance: float, cuda_properties: dict) -> dict:
    # Per-sub-term layout.
    system = build_benchmark_system(topology, ewald_error_tolerance, merge_bonded=False)
    integrator = openmm.VerletIntegrator(TIMESTEP_PS)

    platform = openmm.Platform.getPlatformByName("CUDA")
    context = openmm.Context(system, integrator, platform, {"Precision": "mixed"} | cuda_properties)
    context.setPositions(positions_angstrom * NM_PER_ANGSTROM)
    context.setVelocities(velocities * NM_PER_PS_PER_ANGSTROM_PER_FS)

    integrator.step(WARMUP_STEPS)
    seconds = time_md_steps(context, N_STEPS)

    coulomb_force = [force for force in system.getForces() if isinstance(force, openmm.NonbondedForce)][0]
    alpha_per_nm, nx, ny, nz = coulomb_force.getPMEParametersInContext(context)

    return {
        "ms_per_step": seconds / N_STEPS * 1000.0,
        "ns_per_day": N_STEPS * TIMESTEP_PS / 1000.0 / seconds * 86400.0,
        "pme_alpha_per_nm": alpha_per_nm,
        "pme_grid": [nx, ny, nz],
    }


if __name__ == "__main__":
    names = sys.argv[1:] or list(BENCHMARK_POLYMERS)

    for name in names:
        topology, positions_angstrom, velocities = read_relaxed_benchmark(name)
        results = {"n_steps": N_STEPS, "ewald_error_tolerance": {}, "disable_pme_stream": {}}

        for tolerance in EWALD_ERROR_TOLERANCES:
            results["ewald_error_tolerance"][f"{tolerance:g}"] = time_nve(topology, positions_angstrom, velocities, tolerance, {})

        for disable in ["false", "true"]:
            results["disable_pme_stream"][disable] = time_nve(topology, positions_angstrom, velocities, DISABLE_PME_STREAM_TOLERANCE, {"DisablePmeStream": disable})

        (BENCHMARK_ROOT / name / "openmm" / "settings_scan.json").write_text(json.dumps(results, indent=2) + "\n")
        print(json.dumps({name: results}, indent=2), flush=True)
