"""Acceptance tests: OpenMM (Reference platform) against LAMMPS single points.

Reference data are produced by scripts/make_lammps_reference.py.
"""

import functools

import numpy as np
import pytest

from validation.comparison import compare_case
from validation.reference_systems import SYSTEMS, case_files
from openmm_pcff.lammps_io import read_emc_lammps
from openmm_pcff.builder import excluded_pairs_12_13


# Relative energy difference per LAMMPS keyword (bonded and LJ).
ENERGY_RELATIVE_TOLERANCE = 1e-6

# Maximum absolute per-atom force difference in kcal/mol/Angstrom.
FORCE_ABSOLUTE_TOLERANCE = 1e-4

# Coulomb against the tight LAMMPS Ewald reference.
COULOMB_EWALD_RELATIVE_TOLERANCE = 1e-5

# OpenMM integrates the tail numerically and stops at a relative change below 1e-5 (CustomNonbondedForceImpl.cpp, integrateInteraction).
OPENMM_TAIL_QUADRATURE_RELATIVE_TOLERANCE = 1e-5

BONDED_KEYWORDS = ["ebond", "eangle", "edihed", "eimp"]

EXPECTED_TERM_COUNTS = {
    "butane": {"atoms": 1400, "bonds": 1300, "angles": 2400, "dihedrals": 2700, "impropers": 1600},
    "polyethylene": {"atoms": 1280, "bonds": 1270, "angles": 2520, "dihedrals": 3690, "impropers": 1680},
}


@functools.cache
def cached_comparison(system_name: str, case: str) -> dict:
    return compare_case(system_name, case)


def relative_difference(value: float, reference: float) -> float:
    return abs(value - reference) / abs(reference)


@pytest.mark.parametrize("system_name", SYSTEMS)
def test_term_counts(system_name):
    files = case_files(system_name, "periodic_nocoul")
    topology, positions = read_emc_lammps(files["data"], files["params"])

    counts = {
        "atoms": len(topology.masses_amu),
        "bonds": len(topology.bonds),
        "angles": len(topology.angles),
        "dihedrals": len(topology.dihedrals),
        "impropers": len(topology.impropers),
    }

    assert counts == EXPECTED_TERM_COUNTS[system_name]


@pytest.mark.parametrize("system_name", SYSTEMS)
def test_exclusions_are_bonds_plus_angle_ends(system_name):
    # Without rings, every 1-3 pair is the end-atom pair of exactly one angle, so the exclusions are the bond pairs plus the angle end pairs.
    files = case_files(system_name, "periodic_nocoul")
    topology, positions = read_emc_lammps(files["data"], files["params"])

    excluded = excluded_pairs_12_13(len(topology.masses_amu), [bond.atoms for bond in topology.bonds])

    expected = set()
    for bond in topology.bonds:
        expected.add(tuple(sorted(bond.atoms)))
    for angle in topology.angles:
        expected.add(tuple(sorted((angle.atoms[0], angle.atoms[2]))))

    assert set(excluded) == expected
    assert len(excluded) == len(topology.bonds) + len(topology.angles)


@pytest.mark.parametrize("system_name", SYSTEMS)
@pytest.mark.parametrize("case", ["isolated", "isolated_modified", "periodic_nocoul", "periodic_ewald"])
def test_bonded_energies(system_name, case):
    comparison = cached_comparison(system_name, case)

    for keyword in BONDED_KEYWORDS:
        lammps_energy, openmm_energy = comparison["keyword_energies"][keyword]
        assert relative_difference(openmm_energy, lammps_energy) < ENERGY_RELATIVE_TOLERANCE, keyword


@pytest.mark.parametrize("system_name", SYSTEMS)
@pytest.mark.parametrize("case", ["isolated", "isolated_modified"])
def test_isolated_lj_and_coulomb_energies(system_name, case):
    # No cutoff and no tail: LJ and Coulomb sums must agree directly.
    comparison = cached_comparison(system_name, case)

    lammps_lj, openmm_lj = comparison["keyword_energies"]["evdwl"]
    lammps_coulomb, openmm_coulomb = comparison["keyword_energies"]["ecoul+elong"]

    assert relative_difference(openmm_lj, lammps_lj) < ENERGY_RELATIVE_TOLERANCE

    # The two Coulomb constants differ by 1e-8 relative (LAMMPS 332.06371, OpenMM 332.0637133).
    assert relative_difference(openmm_coulomb, lammps_coulomb) < ENERGY_RELATIVE_TOLERANCE


@pytest.mark.parametrize("system_name", SYSTEMS)
@pytest.mark.parametrize("case", ["periodic_nocoul", "periodic_ewald"])
def test_periodic_lj_pair_energy_and_tail(system_name, case):
    comparison = cached_comparison(system_name, case)
    tail = comparison["lj_tail"]
    lammps_thermo = comparison["lammps_thermo"]
    lammps_lj, openmm_lj = comparison["keyword_energies"]["evdwl"]

    # Pair sum within the cutoff (evdwl includes the tail in both codes).
    lammps_pair = lammps_lj - lammps_thermo["etail"]
    openmm_pair = openmm_lj - tail["openmm_measured"]
    assert relative_difference(openmm_pair, lammps_pair) < ENERGY_RELATIVE_TOLERANCE

    # Each code's tail matches its own pair-counting formula; the two formulas differ by O(1/N) (documented, not a bug).
    assert relative_difference(lammps_thermo["etail"], tail["lammps_formula"]) < ENERGY_RELATIVE_TOLERANCE
    assert relative_difference(tail["openmm_measured"], tail["openmm_formula"]) < OPENMM_TAIL_QUADRATURE_RELATIVE_TOLERANCE


@pytest.mark.parametrize("system_name", SYSTEMS)
def test_coulomb_against_tight_ewald(system_name):
    comparison = cached_comparison(system_name, "periodic_ewald")
    lammps_coulomb, openmm_coulomb = comparison["keyword_energies"]["ecoul+elong"]

    assert relative_difference(openmm_coulomb, lammps_coulomb) < COULOMB_EWALD_RELATIVE_TOLERANCE


@pytest.mark.parametrize("system_name", SYSTEMS)
@pytest.mark.parametrize("case", ["isolated", "isolated_modified", "periodic_nocoul", "periodic_ewald"])
def test_forces(system_name, case):
    comparison = cached_comparison(system_name, case)
    largest_difference = np.abs(comparison["openmm_forces"] - comparison["lammps_forces"]).max()

    assert largest_difference < FORCE_ABSOLUTE_TOLERANCE
