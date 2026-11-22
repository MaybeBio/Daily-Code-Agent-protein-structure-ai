"""Print the comparison table for butane and polyethylene: OpenMM (Reference platform) against the LAMMPS single-point references.

Energies in kcal/mol, forces in kcal/mol/Angstrom.
The pass/fail criteria are asserted by tests/test_lammps_reference.py; this script shows the numbers behind them.
Run from the repository root:

    python scripts/compare_with_lammps.py
"""

import sys
from pathlib import Path

import numpy as np
import openmm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openmm_pcff.builder import FORCE_GROUPS, build_system
from openmm_pcff.lammps_io import read_emc_lammps, read_lammps_forces, read_lammps_thermo
from openmm_pcff.units import KJ_PER_KCAL, NM_PER_ANGSTROM
from validation.comparison import compare_case
from validation.reference_systems import CASE_SETTINGS, SYSTEMS, case_files


PME_TOLERANCES = [1e-3, 5e-4, 1e-4, 1e-5]


def print_case(system_name: str, case: str) -> None:
    comparison = compare_case(system_name, case)

    print(f"\n{system_name} / {case}")
    print(f"  {'keyword':<12} {'LAMMPS':>20} {'OpenMM':>20} {'relative diff':>14}")

    for keyword, (lammps_energy, openmm_energy) in comparison["keyword_energies"].items():
        if lammps_energy == 0.0 and openmm_energy == 0.0:
            relative = "-"
        else:
            relative = f"{abs(openmm_energy - lammps_energy) / abs(lammps_energy):.2e}"

        print(f"  {keyword:<12} {lammps_energy:20.10f} {openmm_energy:20.10f} {relative:>14}")

    force_difference = np.abs(comparison["openmm_forces"] - comparison["lammps_forces"]).max()
    print(f"  max |F_openmm - F_lammps| = {force_difference:.2e}   (max |F_lammps| = {np.abs(comparison['lammps_forces']).max():.1f})")

    if "lj_tail" in comparison:
        tail = comparison["lj_tail"]
        lammps_etail = comparison["lammps_thermo"]["etail"]
        lammps_pair = comparison["keyword_energies"]["evdwl"][0] - lammps_etail
        openmm_pair = comparison["keyword_energies"]["evdwl"][1] - tail["openmm_measured"]

        print(f"  LJ pair part: LAMMPS {lammps_pair:.10f}  OpenMM {openmm_pair:.10f}  rel {abs(openmm_pair - lammps_pair) / abs(lammps_pair):.2e}")
        print(f"  LJ tail: LAMMPS etail {lammps_etail:.8f}  LAMMPS formula {tail['lammps_formula']:.8f}")
        print(f"           OpenMM measured {tail['openmm_measured']:.8f}  OpenMM formula {tail['openmm_formula']:.8f}")
        print(f"           OpenMM - LAMMPS = {tail['openmm_measured'] - lammps_etail:+.6f} ({(tail['openmm_measured'] - lammps_etail) / abs(lammps_etail):+.2e} relative)")


def coulomb_only(system_name: str, coulomb_method: str, ewald_error_tolerance: float) -> tuple[float, np.ndarray]:
    """Coulomb energy (kcal/mol) and forces (kcal/mol/Angstrom) of the periodic system on the Reference platform."""
    files = case_files(system_name, "periodic_ewald")
    topology, positions_angstrom = read_emc_lammps(files["data"], files["params"])

    system = build_system(topology, periodic=True, coulomb_method=coulomb_method, ewald_error_tolerance=ewald_error_tolerance, merge_bonded=False)
    context = openmm.Context(system, openmm.VerletIntegrator(0.001), openmm.Platform.getPlatformByName("Reference"))
    context.setPositions(positions_angstrom * NM_PER_ANGSTROM)

    state = context.getState(getEnergy=True, getForces=True, groups={FORCE_GROUPS["coulomb"]})
    energy = state.getPotentialEnergy().value_in_unit(openmm.unit.kilojoule_per_mole) / KJ_PER_KCAL
    forces = state.getForces(asNumpy=True).value_in_unit(openmm.unit.kilojoule_per_mole / openmm.unit.nanometer)

    return energy, np.array(forces) * NM_PER_ANGSTROM / KJ_PER_KCAL


def print_production_coulomb_accuracy(system_name: str) -> None:
    """Each code's production-style Coulomb against its own converged Ewald sum (informational)."""
    ewald_energy, ewald_forces = coulomb_only(system_name, "ewald", 1e-10)
    rms_force = np.sqrt((ewald_forces**2).sum(axis=1).mean())

    pppm_thermo = read_lammps_thermo(case_files(system_name, "periodic_pppm")["log"])
    ewald_thermo = read_lammps_thermo(case_files(system_name, "periodic_ewald")["log"])
    pppm_energy_error = (pppm_thermo["ecoul"] + pppm_thermo["elong"]) - (ewald_thermo["ecoul"] + ewald_thermo["elong"])

    # Only the Coulomb part differs between the two LAMMPS cases, so the total force difference is the Coulomb force error.
    pppm_force_error = read_lammps_forces(case_files(system_name, "periodic_pppm")["forces"]) - read_lammps_forces(case_files(system_name, "periodic_ewald")["forces"])
    pppm_relative_rms_error = np.sqrt((pppm_force_error**2).sum(axis=1).mean()) / rms_force

    print(f"\n{system_name}: Coulomb at production-style settings against converged Ewald (E = {ewald_energy:.4f}, RMS Coulomb force {rms_force:.3f})")
    print(f"  {'method':<24} {'energy error':>13} {'RMS force error / RMS force':>28}")
    print(f"  {'LAMMPS pppm/cg 0.001':<24} {pppm_energy_error:+13.4f} {pppm_relative_rms_error:28.2e}")

    for tolerance in PME_TOLERANCES:
        pme_energy, pme_forces = coulomb_only(system_name, "pme", tolerance)
        relative_rms_error = np.sqrt(((pme_forces - ewald_forces) ** 2).sum(axis=1).mean()) / rms_force
        label = f"OpenMM PME {tolerance:g}"
        print(f"  {label:<24} {pme_energy - ewald_energy:+13.4f} {relative_rms_error:28.2e}")


if __name__ == "__main__":
    print(f"OpenMM {openmm.__version__}, Reference platform")

    for system_name in SYSTEMS:
        for case in CASE_SETTINGS:
            print_case(system_name, case)

    for system_name in SYSTEMS:
        print_production_coulomb_accuracy(system_name)
