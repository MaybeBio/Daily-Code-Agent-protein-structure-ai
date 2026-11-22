"""NVE energy drift on the relaxed benchmark systems.

From the end of the LAMMPS relaxation (benchmark/<system>/relax/relaxed.data, positions and velocities), with a 1 fs time step:
- LAMMPS KOKKOS (double precision), pppm 0.001 (pppm/kk), fix nve, 20 ps, total energy every 100 steps;
- OpenMM CUDA mixed precision, VerletIntegrator, PME tolerance 0.02 (matched to the LAMMPS accuracy) and 5e-4 (OpenMM default), 100 ps each, total energy every 100 steps.
Drift = slope of a linear fit of total energy against time, also in kT/ns per degree of freedom (3N - 3) at 300 K, the unit of the OpenMM user guide's drift test.
For a like-for-like comparison, the OpenMM drift over the first 20 ps is reported too.
The LJ tail correction is constant at fixed volume, so it does not change the drift.
Outputs go to benchmark/<system>/nve/.
Run from the repository root:

    python scripts/check_benchmark_nve_drift.py [system ...]
"""

import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import openmm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_benchmark_systems import BENCHMARK_POLYMERS, LAMMPS_EXECUTABLE, LAMMPS_KOKKOS_ARGUMENTS, TEMPERATURE_K
from nve_energy_drift import read_lammps_nve_energies
from benchmark_tools import BENCHMARK_ROOT, NM_PER_PS_PER_ANGSTROM_PER_FS, build_benchmark_system, make_context, read_relaxed_benchmark
from openmm_pcff.units import KJ_PER_KCAL


TIMESTEP_FS = 1.0
REPORT_INTERVAL_STEPS = 100
LAMMPS_NVE_STEPS = 20000
OPENMM_NVE_STEPS = 100000
OPENMM_EWALD_TOLERANCES = [0.02, 5e-4]

# Boltzmann constant in kcal/mol/K.
BOLTZMANN_KCAL_MOL_K = 0.0019872043


def run_lammps_nve(name: str, nve_directory: Path) -> np.ndarray:
    input_lines = [
        "# NVE drift, written by scripts/check_benchmark_nve_drift.py",
        "units\t\treal",
        "atom_style\tfull",
        "boundary\tp p p",
        "read_data\t../relax/relaxed.data",
        f"include\t\t../{name}.params",
        "kspace_style\tpppm 0.001",
        f"timestep\t{TIMESTEP_FS}",
        "fix\t\tintegration all nve",
        f"thermo\t\t{REPORT_INTERVAL_STEPS}",
        "thermo_style\tcustom step time pe ke etotal temp",
        "thermo_modify\tformat float %.15g",
        f"run\t\t{LAMMPS_NVE_STEPS}",
    ]
    (nve_directory / "in.lmp").write_text("\n".join(input_lines) + "\n")

    subprocess.run(
        [str(LAMMPS_EXECUTABLE), *LAMMPS_KOKKOS_ARGUMENTS, "-in", "in.lmp", "-log", "log.lammps", "-screen", "none"],
        cwd=nve_directory,
        check=True,
    )

    return read_lammps_nve_energies(nve_directory / "log.lammps")


def run_openmm_nve(
    topology,
    positions_angstrom,
    velocities_angstrom_per_fs,
    ewald_error_tolerance: float,
    precision: str = "mixed",
    timestep_fs: float = TIMESTEP_FS,
    length_ps: float = OPENMM_NVE_STEPS * TIMESTEP_FS / 1000.0,
) -> np.ndarray:
    """Return rows (time in ps, total energy in kcal/mol), one row every REPORT_INTERVAL_STEPS * TIMESTEP_FS (0.1 ps) of simulated time."""
    # Per-sub-term layout.
    system = build_benchmark_system(topology, ewald_error_tolerance, merge_bonded=False)
    integrator = openmm.VerletIntegrator(timestep_fs / 1000.0)
    context = make_context(system, integrator, "CUDA", precision, positions_angstrom, None)

    # LAMMPS velocities are on-step values v(t); OpenMM's VerletIntegrator is leapfrog and takes v(t - dt/2).
    forces_kj_mol_nm = context.getState(getForces=True).getForces(asNumpy=True).value_in_unit(openmm.unit.kilojoule_per_mole / openmm.unit.nanometer)
    accelerations_nm_ps2 = np.array(forces_kj_mol_nm) / np.array(topology.masses_amu)[:, None]
    velocities_nm_ps = velocities_angstrom_per_fs * NM_PER_PS_PER_ANGSTROM_PER_FS
    context.setVelocities(velocities_nm_ps - 0.5 * (timestep_fs / 1000.0) * accelerations_nm_ps2)

    # Report at the same simulated times whatever the time step.
    report_interval_ps = REPORT_INTERVAL_STEPS * TIMESTEP_FS / 1000.0
    steps_per_report = round(report_interval_ps * 1000.0 / timestep_fs)
    n_reports = round(length_ps / report_interval_ps)

    rows = []
    for report in range(n_reports + 1):
        if report > 0:
            integrator.step(steps_per_report)

        state = context.getState(getEnergy=True)
        total_energy_kj_mol = (state.getPotentialEnergy() + state.getKineticEnergy()).value_in_unit(openmm.unit.kilojoule_per_mole)
        rows.append((report * report_interval_ps, total_energy_kj_mol / KJ_PER_KCAL))

    return np.array(rows)


def drift_summary(energies: np.ndarray, n_atoms: int) -> dict:
    times_ps = energies[:, 0]
    total_energy_kcal_mol = energies[:, 1]

    slope_kcal_mol_ps, intercept = np.polyfit(times_ps, total_energy_kcal_mol, 1)
    residual_std = np.std(total_energy_kcal_mol - (slope_kcal_mol_ps * times_ps + intercept))

    n_degrees_of_freedom = 3 * n_atoms - 3
    kt_kcal_mol = BOLTZMANN_KCAL_MOL_K * TEMPERATURE_K

    return {
        "length_ps": float(times_ps[-1]),
        "drift_kcal_mol_ns": slope_kcal_mol_ps * 1000.0,
        "drift_kt_per_ns_per_dof": slope_kcal_mol_ps * 1000.0 / (kt_kcal_mol * n_degrees_of_freedom),
        "fluctuation_about_fit_kcal_mol": float(residual_std),
        "end_minus_start_kcal_mol": float(total_energy_kcal_mol[-1] - total_energy_kcal_mol[0]),
    }


if __name__ == "__main__":
    names = sys.argv[1:] or list(BENCHMARK_POLYMERS)

    for name in names:
        nve_directory = BENCHMARK_ROOT / name / "nve"
        nve_directory.mkdir(exist_ok=True)

        topology, positions_angstrom, velocities = read_relaxed_benchmark(name)
        n_atoms = len(positions_angstrom)
        results = {}

        start = time.perf_counter()
        lammps_energies = run_lammps_nve(name, nve_directory)
        np.savetxt(nve_directory / "lammps_pppm_energy.txt", lammps_energies, header="time_ps total_energy_kcal_mol")
        results["lammps pppm/kk 0.001"] = drift_summary(lammps_energies, n_atoms)
        results["lammps pppm/kk 0.001"]["wall_seconds"] = time.perf_counter() - start

        for tolerance in OPENMM_EWALD_TOLERANCES:
            start = time.perf_counter()
            openmm_energies = run_openmm_nve(topology, positions_angstrom, velocities, tolerance)
            np.savetxt(nve_directory / f"openmm_cuda_mixed_pme{tolerance:g}_energy.txt", openmm_energies, header="time_ps total_energy_kcal_mol")

            label = f"openmm cuda mixed pme {tolerance:g}"
            results[label] = drift_summary(openmm_energies, n_atoms)
            results[label]["wall_seconds"] = time.perf_counter() - start

            first_20_ps = openmm_energies[openmm_energies[:, 0] <= LAMMPS_NVE_STEPS * TIMESTEP_FS / 1000.0]
            results[f"{label} (first 20 ps)"] = drift_summary(first_20_ps, n_atoms)

        (nve_directory / "drift.json").write_text(json.dumps(results, indent=2) + "\n")
        print(json.dumps({name: results}, indent=2), flush=True)
