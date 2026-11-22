"""NVE energy-conservation check: OpenMM (GPU, mixed precision) against LAMMPS from the same starting state.

Workflow for one system (outputs in reference/<system>/nve/):
1. LAMMPS: EMC-style equilibration at 300 K (1000 steps Langevin + nve/limit 0.2, then Langevin + nve), production settings (pppm/cg 0.001).
2. LAMMPS writes the final state (unwrapped positions, velocities, net momentum removed) to start_state.dump.
3. LAMMPS: NVE from that state, 1 fs time step, total energy every 100 steps.
4. OpenMM: NVE from the same state with VerletIntegrator, 1 fs, PME, same reporting interval.
5. Drift = slope of a linear fit of total energy against time.

The LJ tail correction is a constant at fixed volume, so it shifts but does not change the drift.
Run from the repository root:

    python scripts/nve_energy_drift.py butane [--nve-ps 50] [--pme-tolerance 5e-4] [--platform CUDA] [--skip-lammps]
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import openmm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openmm_pcff.builder import build_system
from openmm_pcff.lammps_io import read_emc_lammps
from openmm_pcff.units import KJ_PER_KCAL, NM_PER_ANGSTROM


REFERENCE_ROOT = Path(__file__).resolve().parent.parent / "reference"
# LAMMPS executable, found on PATH.
LAMMPS_EXECUTABLE = "lmp"

TEMPERATURE_K = 300.0
TIMESTEP_FS = 1.0
REPORT_INTERVAL_STEPS = 100
NVE_LIMIT_STEPS = 1000
EQUILIBRATION_STEPS = 10000
LANGEVIN_DAMP_FS = 100.0
VELOCITY_SEED = 87989670
LANGEVIN_SEED = 63052109

# 1 Angstrom/fs = 0.1 nm / 0.001 ps = 100 nm/ps.
NM_PS_PER_ANGSTROM_FS = 100.0


def write_lammps_input(system_name: str, nve_directory: Path, nve_steps: int) -> None:
    input_lines = [
        "# NVE drift reference, written by scripts/nve_energy_drift.py",
        "",
        "units\t\treal",
        "atom_style\tfull",
        "boundary\tp p p",
        "",
        f"read_data\t../{system_name}.data",
        f"include\t\t../{system_name}.params",
        "kspace_style\tpppm/cg 0.001",
        f"timestep\t{TIMESTEP_FS}",
        "",
        "# Equilibration as in the EMC-generated input: Langevin with nve/limit, then Langevin with nve.",
        f"velocity\tall create {TEMPERATURE_K} {VELOCITY_SEED} dist gaussian rot yes mom yes sum yes",
        f"fix\t\ttemp all langevin {TEMPERATURE_K} {TEMPERATURE_K} {LANGEVIN_DAMP_FS} {LANGEVIN_SEED}",
        "fix\t\tint all nve/limit 0.2",
        "thermo\t\t1000",
        f"run\t\t{NVE_LIMIT_STEPS}",
        "unfix\t\tint",
        "fix\t\tint all nve",
        f"run\t\t{EQUILIBRATION_STEPS}",
        "unfix\t\ttemp",
        "",
        "# Start state shared with OpenMM: net momentum removed, unwrapped coordinates.",
        "velocity\tall zero linear",
        "write_dump\tall custom start_state.dump id xu yu zu vx vy vz modify sort id format float %.15g",
        "",
        "# NVE.",
        "reset_timestep\t0",
        f"thermo\t\t{REPORT_INTERVAL_STEPS}",
        "thermo_style\tcustom step time pe ke etotal temp",
        "thermo_modify\tformat float %.15g",
        f"run\t\t{nve_steps}",
    ]

    (nve_directory / "in.lmp").write_text("\n".join(input_lines) + "\n")


def read_lammps_nve_energies(log_path: Path) -> np.ndarray:
    """Return rows (time in ps, total energy in kcal/mol) of the last thermo block (the NVE run)."""
    lines = log_path.read_text().splitlines()
    header_indices = [index for index, line in enumerate(lines) if line.split()[:2] == ["Step", "Time"]]
    rows = []

    for line in lines[header_indices[-1] + 1 :]:
        fields = line.split()

        if not fields or not fields[0].isdigit():
            break

        time_fs = float(fields[1])
        total_energy = float(fields[4])
        rows.append((time_fs / 1000.0, total_energy))

    return np.array(rows)


def read_start_state(dump_path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Return positions (nm) and velocities (nm/ps) from a 'id xu yu zu vx vy vz' dump."""
    lines = dump_path.read_text().splitlines()
    header_index = next(index for index, line in enumerate(lines) if line.startswith("ITEM: ATOMS"))
    table = np.array([[float(value) for value in line.split()] for line in lines[header_index + 1 :] if line.strip()])
    table = table[np.argsort(table[:, 0])]

    positions_nm = table[:, 1:4] * NM_PER_ANGSTROM
    velocities_nm_ps = table[:, 4:7] * NM_PS_PER_ANGSTROM_FS

    return positions_nm, velocities_nm_ps


def run_openmm_nve(system_name: str, nve_directory: Path, nve_steps: int, pme_tolerance: float, platform_name: str) -> np.ndarray:
    """Return rows (time in ps, total energy in kcal/mol) of an OpenMM NVE run from the LAMMPS start state."""
    system_directory = REFERENCE_ROOT / system_name
    topology, ignored_positions = read_emc_lammps(system_directory / f"{system_name}.data", system_directory / f"{system_name}.params")

    system = build_system(topology, periodic=True, coulomb_method="pme", ewald_error_tolerance=pme_tolerance, merge_bonded=False)
    integrator = openmm.VerletIntegrator(TIMESTEP_FS / 1000.0)

    platform = openmm.Platform.getPlatformByName(platform_name)
    properties = {"Precision": "mixed"} if platform_name in ("CUDA", "OpenCL") else {}
    context = openmm.Context(system, integrator, platform, properties)

    positions_nm, velocities_nm_ps = read_start_state(nve_directory / "start_state.dump")
    context.setPositions(positions_nm)

    # LAMMPS (velocity Verlet) velocities are on-step values v(t); OpenMM's VerletIntegrator is leapfrog and takes v(t - dt/2).
    # Without this shift OpenMM's reported kinetic energy at t = 0 is too high by about 21 kcal/mol for butane.
    forces_kj_mol_nm = context.getState(getForces=True).getForces(asNumpy=True).value_in_unit(openmm.unit.kilojoule_per_mole / openmm.unit.nanometer)
    masses_amu = np.array(topology.masses_amu)[:, None]
    accelerations_nm_ps2 = np.array(forces_kj_mol_nm) / masses_amu
    half_step_velocities_nm_ps = velocities_nm_ps - 0.5 * (TIMESTEP_FS / 1000.0) * accelerations_nm_ps2

    context.setVelocities(half_step_velocities_nm_ps)

    rows = []
    start_time = time.time()

    for report in range(nve_steps // REPORT_INTERVAL_STEPS + 1):
        if report > 0:
            integrator.step(REPORT_INTERVAL_STEPS)

        state = context.getState(getEnergy=True)
        total_energy_kj_mol = (state.getPotentialEnergy() + state.getKineticEnergy()).value_in_unit(openmm.unit.kilojoule_per_mole)
        rows.append((report * REPORT_INTERVAL_STEPS * TIMESTEP_FS / 1000.0, total_energy_kj_mol / KJ_PER_KCAL))

    elapsed_s = time.time() - start_time
    print(f"OpenMM {platform_name}: {nve_steps} steps in {elapsed_s:.1f} s ({nve_steps * TIMESTEP_FS * 1e-6 / (elapsed_s / 86400):.1f} ns/day, including reporting)")

    return np.array(rows)


def summarize_drift(label: str, energies: np.ndarray, n_atoms: int) -> None:
    times_ps = energies[:, 0]
    total_energy = energies[:, 1]

    slope_kcal_mol_ps, intercept = np.polyfit(times_ps, total_energy, 1)
    residual_std = np.std(total_energy - (slope_kcal_mol_ps * times_ps + intercept))

    print(
        f"{label:<34} drift {slope_kcal_mol_ps * 1000:+9.3f} kcal/mol/ns"
        f" ({slope_kcal_mol_ps * 1000 / n_atoms:+.2e} per atom),"
        f" fluctuation about fit {residual_std:.4f} kcal/mol,"
        f" E(end) - E(0) {total_energy[-1] - total_energy[0]:+.4f} kcal/mol"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("system_name")
    parser.add_argument("--nve-ps", type=float, default=50.0)
    parser.add_argument("--pme-tolerance", type=float, default=5e-4)
    parser.add_argument("--platform", default="CUDA")
    parser.add_argument("--skip-lammps", action="store_true", help="reuse an existing LAMMPS run and start state")
    arguments = parser.parse_args()

    nve_steps = int(round(arguments.nve_ps * 1000.0 / TIMESTEP_FS))
    nve_directory = REFERENCE_ROOT / arguments.system_name / "nve"
    nve_directory.mkdir(exist_ok=True)

    if not arguments.skip_lammps:
        write_lammps_input(arguments.system_name, nve_directory, nve_steps)
        start_time = time.time()
        subprocess.run([str(LAMMPS_EXECUTABLE), "-in", "in.lmp", "-log", "log.lammps", "-screen", "none"], cwd=nve_directory, check=True)
        print(f"LAMMPS: equilibration + {nve_steps} NVE steps in {time.time() - start_time:.1f} s")

    lammps_energies = read_lammps_nve_energies(nve_directory / "log.lammps")
    openmm_energies = run_openmm_nve(arguments.system_name, nve_directory, nve_steps, arguments.pme_tolerance, arguments.platform)

    openmm_file = nve_directory / f"openmm_{arguments.platform.lower()}_pme{arguments.pme_tolerance:g}_energy.txt"
    np.savetxt(openmm_file, openmm_energies, header="time_ps total_energy_kcal_mol")
    np.savetxt(nve_directory / "lammps_energy.txt", lammps_energies, header="time_ps total_energy_kcal_mol")

    n_atoms = len(read_start_state(nve_directory / "start_state.dump")[0])
    summarize_drift("LAMMPS pppm/cg 0.001", lammps_energies, n_atoms)
    summarize_drift(f"OpenMM {arguments.platform} mixed PME {arguments.pme_tolerance:g}", openmm_energies, n_atoms)
