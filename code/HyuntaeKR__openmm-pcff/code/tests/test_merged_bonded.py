"""The merged bonded layout (build_system(..., merge_bonded=True)) against the per-sub-term layout validated against LAMMPS.

The merged layout must give the same energy per LAMMPS keyword and the same forces, to round-off, on the Reference platform.
Since the per-sub-term layout matches LAMMPS within the tolerances of test_lammps_reference.py, this carries the LAMMPS agreement over.
A finite-difference check confirms the merged forces are the gradients of the merged energies.
"""

import numpy as np
import openmm
import pytest

from openmm_pcff.builder import FORCE_GROUPS, LAMMPS_KEYWORD_SUB_TERMS, MERGED_FORCE_GROUPS, build_system
from openmm_pcff.lammps_io import read_emc_lammps
from openmm_pcff.units import NM_PER_ANGSTROM
from validation.reference_systems import CASE_SETTINGS, EMC_SYSTEMS, SYSTEMS, case_files


# Round-off level: both layouts evaluate the same expressions in double precision, in a different order.
ENERGY_RELATIVE_TOLERANCE = 1e-12
FORCE_RELATIVE_TOLERANCE = 1e-10

FINITE_DIFFERENCE_RELATIVE_TOLERANCE = 1e-5
STEP_NM = 1e-6

BONDED_KEYWORDS = ["ebond", "eangle", "edihed", "eimp"]

# Systems with nonzero Wilson terms, bond-bond-13, and dihedrals without cross terms, besides butane and polyethylene.
FINITE_DIFFERENCE_SYSTEMS = SYSTEMS + ["benzene", "acetone", "methyl_acetate", "pmma"]


def reference_context(system: openmm.System, positions_nm: np.ndarray) -> openmm.Context:
    context = openmm.Context(system, openmm.VerletIntegrator(0.001), openmm.Platform.getPlatformByName("Reference"))
    context.setPositions(positions_nm)
    return context


def energy_kj_mol(context: openmm.Context, groups: set[int]) -> float:
    return context.getState(getEnergy=True, groups=groups).getPotentialEnergy().value_in_unit(openmm.unit.kilojoule_per_mole)


def forces_kj_mol_nm(context: openmm.Context) -> np.ndarray:
    forces = context.getState(getForces=True).getForces(asNumpy=True)
    return np.array(forces.value_in_unit(openmm.unit.kilojoule_per_mole / openmm.unit.nanometer))


@pytest.mark.parametrize("system_name", SYSTEMS + list(EMC_SYSTEMS))
def test_merged_layout_matches_per_sub_term_layout(system_name):
    files = case_files(system_name, "isolated")
    topology, positions_angstrom = read_emc_lammps(files["data"], files["params"])
    positions_nm = positions_angstrom * NM_PER_ANGSTROM

    per_sub_term_context = reference_context(build_system(topology, **CASE_SETTINGS["isolated"], merge_bonded=False), positions_nm)
    merged_context = reference_context(build_system(topology, **CASE_SETTINGS["isolated"], merge_bonded=True), positions_nm)

    for keyword in BONDED_KEYWORDS:
        per_sub_term_groups = {FORCE_GROUPS[sub_term] for sub_term in LAMMPS_KEYWORD_SUB_TERMS[keyword]}
        per_sub_term_energy = energy_kj_mol(per_sub_term_context, per_sub_term_groups)
        merged_energy = energy_kj_mol(merged_context, {MERGED_FORCE_GROUPS[keyword]})

        assert abs(merged_energy - per_sub_term_energy) <= ENERGY_RELATIVE_TOLERANCE * abs(per_sub_term_energy), keyword

    per_sub_term_forces = forces_kj_mol_nm(per_sub_term_context)
    merged_forces = forces_kj_mol_nm(merged_context)

    assert np.abs(merged_forces - per_sub_term_forces).max() <= FORCE_RELATIVE_TOLERANCE * np.abs(per_sub_term_forces).max()


@pytest.mark.parametrize("system_name", FINITE_DIFFERENCE_SYSTEMS)
def test_merged_forces_match_energy_differences(system_name):
    files = case_files(system_name, "isolated")
    topology, positions_angstrom = read_emc_lammps(files["data"], files["params"])
    positions_nm = positions_angstrom * NM_PER_ANGSTROM

    context = reference_context(build_system(topology, **CASE_SETTINGS["isolated"], merge_bonded=True), positions_nm)

    random_generator = np.random.default_rng(20261113)
    direction = random_generator.normal(size=positions_nm.shape)
    direction /= np.linalg.norm(direction)

    for keyword in BONDED_KEYWORDS:
        group = MERGED_FORCE_GROUPS[keyword]

        context.setPositions(positions_nm)
        forces = context.getState(getForces=True, groups={group}).getForces(asNumpy=True)
        analytic_derivative = -np.sum(np.array(forces.value_in_unit(openmm.unit.kilojoule_per_mole / openmm.unit.nanometer)) * direction)

        context.setPositions(positions_nm + STEP_NM * direction)
        energy_plus = energy_kj_mol(context, {group})
        context.setPositions(positions_nm - STEP_NM * direction)
        energy_minus = energy_kj_mol(context, {group})

        numerical_derivative = (energy_plus - energy_minus) / (2 * STEP_NM)

        relative_error = abs(numerical_derivative - analytic_derivative) / abs(analytic_derivative)
        assert relative_error < FINITE_DIFFERENCE_RELATIVE_TOLERANCE, f"{keyword}: analytic {analytic_derivative}, numerical {numerical_derivative}"
