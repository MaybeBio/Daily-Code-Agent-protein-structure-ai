"""Diagnose the OpenMM NVE energy loss on the benchmark systems.

In the 1 fs runs of scripts/check_benchmark_nve_drift.py (CUDA mixed precision), the total energy falls during the first 30-50 ps and then stays flat.
This script repeats the PME 5e-4 run with a 0.5 fs time step, same start state and length (100 ps), same reporting times (every 0.1 ps).
Verlet integration conserves a shadow energy that differs from the true energy by a term of order dt^2, so an energy change caused by the time step shrinks about 4-fold at half the time step,
while one caused by single-precision forces or by forces that are not the gradient of the energy does not shrink that way.
Reported for each run: total-energy change between the first and last 10 ps block means, slopes of linear fits over 0-50 ps and 50-100 ps, and the fluctuation about the 100 ps fit.
Results go to benchmark/<system>/nve/drift_cause.json; energies to benchmark/<system>/nve/openmm_cuda_<precision>_pme<tolerance>_dt<timestep>fs_energy.txt.
Run from the repository root:

    python scripts/check_nve_drift_cause.py [system ...]
"""

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_benchmark_nve_drift import drift_summary, run_openmm_nve
from make_benchmark_systems import BENCHMARK_POLYMERS
from benchmark_tools import BENCHMARK_ROOT, read_relaxed_benchmark


EWALD_ERROR_TOLERANCE = 5e-4
LENGTH_PS = 100.0
BLOCK_PS = 10.0

# (precision, time step in fs); the 1 fs mixed run is read from the earlier check instead of rerun.
DIAGNOSTIC_RUNS = [("mixed", 0.5)]


def energy_change_summary(energies: np.ndarray) -> dict:
    times_ps = energies[:, 0]
    total_energy_kcal_mol = energies[:, 1]

    first_block = total_energy_kcal_mol[times_ps < BLOCK_PS]
    last_block = total_energy_kcal_mol[times_ps > times_ps[-1] - BLOCK_PS]

    first_half = energies[times_ps <= LENGTH_PS / 2]
    second_half = energies[times_ps >= LENGTH_PS / 2]

    return {
        "last_minus_first_block_mean_kcal_mol": float(last_block.mean() - first_block.mean()),
        "slope_0_to_50_ps_kcal_mol_ns": float(np.polyfit(first_half[:, 0], first_half[:, 1], 1)[0] * 1000.0),
        "slope_50_to_100_ps_kcal_mol_ns": float(np.polyfit(second_half[:, 0], second_half[:, 1], 1)[0] * 1000.0),
    }


if __name__ == "__main__":
    names = sys.argv[1:] or list(BENCHMARK_POLYMERS)

    for name in names:
        nve_directory = BENCHMARK_ROOT / name / "nve"
        topology, positions_angstrom, velocities = read_relaxed_benchmark(name)
        n_atoms = len(positions_angstrom)
        results = {}

        baseline_energies = np.loadtxt(nve_directory / f"openmm_cuda_mixed_pme{EWALD_ERROR_TOLERANCE:g}_energy.txt")
        results["mixed, dt 1 fs (from check_benchmark_nve_drift.py)"] = drift_summary(baseline_energies, n_atoms) | energy_change_summary(baseline_energies)

        for precision, timestep_fs in DIAGNOSTIC_RUNS:
            start = time.perf_counter()
            energies = run_openmm_nve(topology, positions_angstrom, velocities, EWALD_ERROR_TOLERANCE, precision, timestep_fs, LENGTH_PS)
            wall_seconds = time.perf_counter() - start

            np.savetxt(
                nve_directory / f"openmm_cuda_{precision}_pme{EWALD_ERROR_TOLERANCE:g}_dt{timestep_fs:g}fs_energy.txt",
                energies,
                header="time_ps total_energy_kcal_mol",
            )

            label = f"{precision}, dt {timestep_fs:g} fs"
            results[label] = drift_summary(energies, n_atoms) | energy_change_summary(energies)
            results[label]["wall_seconds"] = wall_seconds

        (nve_directory / "drift_cause.json").write_text(json.dumps(results, indent=2) + "\n")
        print(json.dumps({name: results}, indent=2), flush=True)
