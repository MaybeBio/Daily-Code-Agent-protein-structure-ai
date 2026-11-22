"""Helpers to load the relaxed benchmark systems (scripts/make_benchmark_systems.py) and time OpenMM on them.

The parameters come from EMC's .data/.params pair (identical to openmm_pcff's own assignment).
Positions, box, and velocities come from the end of the LAMMPS compression and relaxation, so OpenMM and LAMMPS start from the same state.
"""

import time
from pathlib import Path

import numpy as np
import openmm

from openmm_pcff.builder import FORCE_GROUPS, build_system
from openmm_pcff.lammps_io import read_emc_lammps
from openmm_pcff.ptop import ParameterizedTopology
from openmm_pcff.units import NM_PER_ANGSTROM


BENCHMARK_ROOT = Path(__file__).resolve().parent.parent / "benchmark"

# LAMMPS real units store velocities in Angstrom/fs; OpenMM uses nm/ps.
NM_PER_PS_PER_ANGSTROM_PER_FS = 100.0


def read_positions_dump(dump_path: Path) -> tuple[np.ndarray, tuple[float, float, float]]:
    """Read a one-snapshot 'dump custom id xu yu zu' file; returns (unwrapped positions in Angstrom ordered by atom id, box lengths in Angstrom)."""
    lines = dump_path.read_text().splitlines()

    box_index = next(index for index, line in enumerate(lines) if line.startswith("ITEM: BOX BOUNDS"))
    if lines[box_index].split()[3:] != ["pp", "pp", "pp"]:
        raise ValueError(f"{dump_path}: expected an orthorhombic periodic box.")

    box_lengths_angstrom = []
    for line in lines[box_index + 1 : box_index + 4]:
        low, high = (float(value) for value in line.split())
        box_lengths_angstrom.append(high - low)

    atoms_index = next(index for index, line in enumerate(lines) if line.startswith("ITEM: ATOMS"))
    if lines[atoms_index].split()[2:] != ["id", "xu", "yu", "zu"]:
        raise ValueError(f"{dump_path}: expected columns 'id xu yu zu'.")

    table = np.array([[float(value) for value in line.split()] for line in lines[atoms_index + 1 :] if line.strip()])
    table = table[np.argsort(table[:, 0])]

    if not np.array_equal(table[:, 0], np.arange(1, len(table) + 1)):
        raise ValueError(f"{dump_path}: atom ids must be 1..N.")

    return table[:, 1:], tuple(box_lengths_angstrom)


def read_data_velocities(data_path: Path, n_atoms: int) -> np.ndarray:
    """Read the Velocities section of a LAMMPS write_data file; returns velocities in Angstrom/fs ordered by atom id."""
    lines = data_path.read_text().splitlines()
    start = next(index for index, line in enumerate(lines) if line.strip() == "Velocities") + 2

    rows = []
    for line in lines[start : start + n_atoms]:
        fields = line.split()
        rows.append([int(fields[0]), float(fields[1]), float(fields[2]), float(fields[3])])

    table = np.array(rows)
    table = table[np.argsort(table[:, 0])]

    if not np.array_equal(table[:, 0], np.arange(1, n_atoms + 1)):
        raise ValueError(f"{data_path}: expected one velocity per atom id 1..{n_atoms}.")

    return table[:, 1:]


def read_relaxed_benchmark(name: str) -> tuple[ParameterizedTopology, np.ndarray, np.ndarray]:
    """Return (topology with the relaxed box, positions in Angstrom, velocities in Angstrom/fs) of one benchmark system."""
    system_directory = BENCHMARK_ROOT / name
    relax_directory = system_directory / "relax"

    topology, build_positions_angstrom = read_emc_lammps(system_directory / f"{name}.data", system_directory / f"{name}.params")
    positions_angstrom, box_lengths_angstrom = read_positions_dump(relax_directory / "relaxed_positions.dump")

    # The parameters are those of the EMC build; only the box changed during compression.
    topology.box_lengths_angstrom = box_lengths_angstrom

    velocities_angstrom_per_fs = read_data_velocities(relax_directory / "relaxed.data", len(positions_angstrom))

    return topology, positions_angstrom, velocities_angstrom_per_fs


def make_context(
    system: openmm.System,
    integrator: openmm.Integrator,
    platform_name: str,
    precision: str | None,
    positions_angstrom: np.ndarray,
    velocities_angstrom_per_fs: np.ndarray | None,
) -> openmm.Context:
    """Create a context on the named platform; precision ('single', 'mixed', 'double') applies to CUDA only."""
    platform = openmm.Platform.getPlatformByName(platform_name)
    properties = {"Precision": precision} if platform_name == "CUDA" else {}

    context = openmm.Context(system, integrator, platform, properties)
    context.setPositions(positions_angstrom * NM_PER_ANGSTROM)

    if velocities_angstrom_per_fs is not None:
        context.setVelocities(velocities_angstrom_per_fs * NM_PER_PS_PER_ANGSTROM_PER_FS)

    return context


def forces_by_group(context: openmm.Context) -> dict[str, np.ndarray]:
    """Return the forces of every sub-term force group (FORCE_GROUPS, per-sub-term layout) and of all groups together, in kJ/mol/nm (N x 3 arrays)."""
    forces = {}

    for sub_term, group in FORCE_GROUPS.items():
        state = context.getState(getForces=True, groups={group})
        forces[sub_term] = state.getForces(asNumpy=True).value_in_unit(openmm.unit.kilojoule_per_mole / openmm.unit.nanometer)

    state = context.getState(getForces=True)
    forces["total"] = state.getForces(asNumpy=True).value_in_unit(openmm.unit.kilojoule_per_mole / openmm.unit.nanometer)

    return forces


def relative_rms_difference(forces: np.ndarray, reference_forces: np.ndarray) -> float:
    """sqrt(mean |F - F_ref|^2) / sqrt(mean |F_ref|^2) over all atoms."""
    return np.sqrt(np.mean(np.sum((forces - reference_forces) ** 2, axis=1))) / np.sqrt(np.mean(np.sum(reference_forces**2, axis=1)))


def time_md_steps(context: openmm.Context, n_steps: int) -> float:
    """Run n_steps and return the wall time in seconds; getState forces the GPU to finish before the clock stops."""
    context.getState(getEnergy=True)
    start = time.perf_counter()

    context.getIntegrator().step(n_steps)
    context.getState(getEnergy=True)

    return time.perf_counter() - start


def time_force_evaluations(context: openmm.Context, groups: set[int], n_evaluations: int) -> float:
    """Return the mean wall time in seconds of one force evaluation of the given force groups (includes copying the forces to the host)."""
    context.getState(getForces=True, groups=groups)
    start = time.perf_counter()

    for evaluation in range(n_evaluations):
        context.getState(getForces=True, groups=groups)

    return (time.perf_counter() - start) / n_evaluations


def build_benchmark_system(topology: ParameterizedTopology, ewald_error_tolerance: float, merge_bonded: bool = True) -> openmm.System:
    return build_system(topology, periodic=True, coulomb_method="pme", ewald_error_tolerance=ewald_error_tolerance, merge_bonded=merge_bonded)
