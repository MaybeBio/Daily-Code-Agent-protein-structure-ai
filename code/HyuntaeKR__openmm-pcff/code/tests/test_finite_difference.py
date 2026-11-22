"""Finite-difference check of every force group: analytic forces against central differences of the energy.

OpenMM derives forces from the expressions analytically, so this checks the expressions are differentiable where they are evaluated
(e.g. no asin at its domain edge in the Wilson term) and that each group's forces belong to its energy.
"""

import numpy as np
import openmm
import pytest

from openmm_pcff.builder import FORCE_GROUPS, build_system
from openmm_pcff.lammps_io import read_emc_lammps
from openmm_pcff.units import NM_PER_ANGSTROM
from validation.reference_systems import CASE_SETTINGS, SYSTEMS, case_files


FINITE_DIFFERENCE_RELATIVE_TOLERANCE = 1e-5

# Displacement step along a random unit direction of all coordinates (nm).
STEP_NM = 1e-6


def group_energy_kj_mol(context: openmm.Context, group: int) -> float:
    state = context.getState(getEnergy=True, groups={group})
    return state.getPotentialEnergy().value_in_unit(openmm.unit.kilojoule_per_mole)


@pytest.mark.parametrize("system_name", SYSTEMS)
@pytest.mark.parametrize("case", ["isolated_modified", "periodic_ewald"])
def test_forces_match_energy_differences(system_name, case):
    files = case_files(system_name, case)
    topology, positions_angstrom = read_emc_lammps(files["data"], files["params"])
    positions_nm = positions_angstrom * NM_PER_ANGSTROM

    # The check runs per sub-term (FORCE_GROUPS), so it needs the per-sub-term layout.
    system = build_system(topology, **CASE_SETTINGS[case], merge_bonded=False)
    context = openmm.Context(system, openmm.VerletIntegrator(0.001), openmm.Platform.getPlatformByName("Reference"))

    random_generator = np.random.default_rng(20261106)
    direction = random_generator.normal(size=positions_nm.shape)
    direction /= np.linalg.norm(direction)

    for sub_term, group in FORCE_GROUPS.items():
        context.setPositions(positions_nm)
        state = context.getState(getForces=True, groups={group})
        forces = state.getForces(asNumpy=True).value_in_unit(openmm.unit.kilojoule_per_mole / openmm.unit.nanometer)

        # dE/ds along the direction from the analytic forces.
        analytic_derivative = -np.sum(np.array(forces) * direction)

        context.setPositions(positions_nm + STEP_NM * direction)
        energy_plus = group_energy_kj_mol(context, group)
        context.setPositions(positions_nm - STEP_NM * direction)
        energy_minus = group_energy_kj_mol(context, group)

        numerical_derivative = (energy_plus - energy_minus) / (2 * STEP_NM)

        # Groups without terms (e.g. Wilson with K = 0 everywhere, Coulomb absent) have zero energy and force.
        if analytic_derivative == 0.0 and numerical_derivative == 0.0:
            continue

        relative_error = abs(numerical_derivative - analytic_derivative) / abs(analytic_derivative)
        assert relative_error < FINITE_DIFFERENCE_RELATIVE_TOLERANCE, f"{sub_term}: analytic {analytic_derivative}, numerical {numerical_derivative}"
