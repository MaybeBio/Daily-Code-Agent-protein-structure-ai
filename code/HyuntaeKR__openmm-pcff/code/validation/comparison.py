"""Comparisons of openmm_pcff with the EMC + LAMMPS references (see validation/reference_systems.py).

- Energies and forces against the LAMMPS single points in reference/<system>/singlepoint/<case>/.
- Parameterized topologies from openmm_pcff against those read from EMC's .params files, term by term.

Used by the tests and by scripts/compare_with_lammps.py and scripts/report_assignment.py.
All returned energies are in kcal/mol and forces in kcal/mol/Angstrom, i.e. LAMMPS real units.
"""

import copy
import math
import re
from pathlib import Path

import numpy as np
import openmm
from scipy.special import erfc

from openmm_pcff import topology_from_lammps_data
from openmm_pcff.builder import FORCE_GROUPS, LAMMPS_KEYWORD_SUB_TERMS, build_system
from openmm_pcff.lammps_io import read_emc_lammps, read_lammps_forces, read_lammps_thermo
from openmm_pcff.ptop import ParameterizedTopology
from openmm_pcff.units import KJ_PER_KCAL, NM_PER_ANGSTROM
from validation.reference_systems import CASE_SETTINGS, FRC_PATH, TEMPLATES_PATH, case_files, reference_molecules


KCAL_MOL_ANGSTROM_PER_KJ_MOL_NM = NM_PER_ANGSTROM / KJ_PER_KCAL


def openmm_energies_and_forces(system: openmm.System, positions_nm: np.ndarray) -> dict:
    """Evaluate every force group on the Reference platform; returns energies by sub-term and total forces in LAMMPS units."""
    integrator = openmm.VerletIntegrator(0.001)
    platform = openmm.Platform.getPlatformByName("Reference")
    context = openmm.Context(system, integrator, platform)
    context.setPositions(positions_nm)

    sub_term_energies_kcal_mol = {}

    for sub_term, group in FORCE_GROUPS.items():
        state = context.getState(getEnergy=True, groups={group})
        energy_kj_mol = state.getPotentialEnergy().value_in_unit(openmm.unit.kilojoule_per_mole)
        sub_term_energies_kcal_mol[sub_term] = energy_kj_mol / KJ_PER_KCAL

    state = context.getState(getForces=True)
    forces_kj_mol_nm = state.getForces(asNumpy=True).value_in_unit(openmm.unit.kilojoule_per_mole / openmm.unit.nanometer)

    return {
        "sub_term_energies": sub_term_energies_kcal_mol,
        "forces": np.array(forces_kj_mol_nm) * KCAL_MOL_ANGSTROM_PER_KJ_MOL_NM,
    }


def lj_tail_energies(topology, system: openmm.System, positions_nm: np.ndarray) -> dict[str, float]:
    """
    LJ tail correction in kcal/mol by three routes:
    lammps_formula: sum over ordered type pairs of 2 pi N_i N_j eps_ij sig_ij^6 (sig_ij^3 - 3 rc^3) / (3 rc^6) / V (pair_lj_class2.cpp);
    openmm_formula: OpenMM's pair counting (N_i (N_i + 1)/2 for like classes, normalized by N/(N + 1)) with the same analytic integral;
    openmm_measured: OpenMM LJ energy with minus without setUseLongRangeCorrection.
    """
    cutoff = topology.lj_cutoff_angstrom
    volume = math.prod(topology.box_lengths_angstrom)

    # Atom classes are the distinct (sigma, epsilon) pairs, as in OpenMM.
    class_counts = {}
    for sigma, epsilon in zip(topology.lj_sigma_angstrom, topology.lj_epsilon_kcal_mol):
        class_counts[(sigma, epsilon)] = class_counts.get((sigma, epsilon), 0) + 1

    classes = list(class_counts)
    n_atoms = len(topology.lj_sigma_angstrom)

    def tail_integral(class_i, class_j):
        # Integral of E(r) r^2 dr from rc to infinity for the 9-6 form with sixth-power mixing.
        sigma_i, epsilon_i = class_i
        sigma_j, epsilon_j = class_j
        sigma_ij = ((sigma_i**6 + sigma_j**6) / 2) ** (1 / 6)
        epsilon_ij = 2 * math.sqrt(epsilon_i * epsilon_j) * sigma_i**3 * sigma_j**3 / (sigma_i**6 + sigma_j**6)
        return epsilon_ij * sigma_ij**6 * (sigma_ij**3 - 3 * cutoff**3) / (3 * cutoff**6)

    lammps_sum = 0.0
    for class_i in classes:
        for class_j in classes:
            lammps_sum += 2 * math.pi * class_counts[class_i] * class_counts[class_j] * tail_integral(class_i, class_j)

    openmm_pair_sum = 0.0
    for index_i, class_i in enumerate(classes):
        for index_j, class_j in enumerate(classes):
            if index_j < index_i:
                continue
            if index_i == index_j:
                pair_count = class_counts[class_i] * (class_counts[class_i] + 1) / 2
            else:
                pair_count = class_counts[class_i] * class_counts[class_j]
            openmm_pair_sum += pair_count * tail_integral(class_i, class_j)

    # OpenMM: coefficient = 2 pi N^2 <integral>, with the average taken over N (N + 1)/2 pairs (CustomNonbondedForceImpl.cpp).
    openmm_formula = 2 * math.pi * n_atoms**2 * openmm_pair_sum / (n_atoms * (n_atoms + 1) / 2) / volume

    # Measured: the same system without the correction.
    system_without_tail = copy.deepcopy(system)
    for force in system_without_tail.getForces():
        if isinstance(force, openmm.CustomNonbondedForce):
            force.setUseLongRangeCorrection(False)

    with_tail = openmm_energies_and_forces(system, positions_nm)["sub_term_energies"]["lj_9_6"]
    without_tail = openmm_energies_and_forces(system_without_tail, positions_nm)["sub_term_energies"]["lj_9_6"]

    return {
        "lammps_formula": lammps_sum / volume,
        "openmm_formula": openmm_formula,
        "openmm_measured": with_tail - without_tail,
    }


# LAMMPS coul/long evaluates erfc with Abramowitz and Stegun 7.1.26 (pair_lj_class2_coul_long.cpp, EWALD_P and A1-A5).
LAMMPS_EWALD_P = 0.3275911
LAMMPS_ERFC_COEFFICIENTS = [0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429]

# Coulomb constant of LAMMPS real units (update.cpp).
LAMMPS_COULOMB_CONSTANT = 332.06371


def lammps_g_ewald(log_path: Path) -> float:
    """Ewald splitting parameter (1/Angstrom) printed by LAMMPS kspace ewald."""
    match = re.search(r"G vector \(1/distance\) = ([0-9.eE+-]+)", log_path.read_text())
    return float(match.group(1))


def lammps_erfc_approximation_error(topology: ParameterizedTopology, positions_angstrom: np.ndarray, g_ewald: float) -> float:
    """
    Expected LAMMPS - exact real-space Coulomb energy (kcal/mol) caused by the approximate erfc of coul/long:
    sum over all pairs within the cutoff of C q_i q_j (erfc_AS(g r) - erfc(g r)) / r, with minimum-image distances.
    Excluded pairs are included, because LAMMPS evaluates them as erfc - 1 and so carries the same erfc error.
    """
    charges_e = np.array(topology.charges_e)
    box_angstrom = np.array(topology.box_lengths_angstrom)
    cutoff_angstrom = topology.coulomb_cutoff_angstrom

    def erfc_abramowitz_stegun(x):
        t = 1.0 / (1.0 + LAMMPS_EWALD_P * x)
        a1, a2, a3, a4, a5 = LAMMPS_ERFC_COEFFICIENTS
        return t * (a1 + t * (a2 + t * (a3 + t * (a4 + t * a5)))) * np.exp(-x * x)

    energy_error = 0.0

    for atom_i in range(len(charges_e) - 1):
        separation = positions_angstrom[atom_i + 1 :] - positions_angstrom[atom_i]
        separation -= box_angstrom * np.round(separation / box_angstrom)
        distance = np.linalg.norm(separation, axis=1)

        within_cutoff = distance < cutoff_angstrom
        r = distance[within_cutoff]
        charge_products = charges_e[atom_i] * charges_e[atom_i + 1 :][within_cutoff]

        energy_error += np.sum(LAMMPS_COULOMB_CONSTANT * charge_products * (erfc_abramowitz_stegun(g_ewald * r) - erfc(g_ewald * r)) / r)

    return energy_error


def openmm_pcff_topology_like(system_name: str, data_path: Path, emc_topology: ParameterizedTopology) -> tuple[ParameterizedTopology, dict]:
    """Type and parameterize the structure of data_path with openmm_pcff, using the pair settings of the EMC topology of the same case."""
    topology, positions_angstrom, report = topology_from_lammps_data(
        data_path,
        reference_molecules(system_name),
        FRC_PATH,
        TEMPLATES_PATH,
        lj_cutoff_angstrom=emc_topology.lj_cutoff_angstrom,
        coulomb_cutoff_angstrom=emc_topology.coulomb_cutoff_angstrom,
        lj_tail_correction=emc_topology.lj_tail_correction,
    )

    return topology, report


def compare_case(system_name: str, case: str, settings: dict | None = None, parameter_source: str = "emc") -> dict:
    """
    Build the OpenMM system for one reference case and return LAMMPS and OpenMM values side by side:
    keyword_energies {keyword: (lammps, openmm)}, sub_term_energies {sub_term: openmm}, lammps_thermo,
    lammps_forces, openmm_forces, and for periodic cases with a tail correction, lj_tail (see lj_tail_energies).

    parameter_source "emc" reads types and parameters from EMC's files;
    "openmm_pcff" assigns them with openmm_pcff from pcff.frc and pcff_templates.dat, using only the structure of the data file.
    LAMMPS always uses EMC's parameters, so the second route tests typing, parameter assignment, and the OpenMM forces together.
    """
    files = case_files(system_name, case)

    if settings is None:
        settings = CASE_SETTINGS[case]

    topology, positions_angstrom = read_emc_lammps(files["data"], files["params"])
    positions_nm = positions_angstrom * NM_PER_ANGSTROM

    if parameter_source == "openmm_pcff":
        topology, report = openmm_pcff_topology_like(system_name, files["data"], topology)
    elif parameter_source != "emc":
        raise ValueError(f"Unknown parameter_source '{parameter_source}'.")

    # Energies per sub-term (FORCE_GROUPS) need the per-sub-term layout.
    system = build_system(topology, **settings, merge_bonded=False)
    openmm_result = openmm_energies_and_forces(system, positions_nm)

    lammps_thermo = read_lammps_thermo(files["log"])
    lammps_forces = read_lammps_forces(files["forces"])

    keyword_energies = {}
    for keyword, sub_terms in LAMMPS_KEYWORD_SUB_TERMS.items():
        openmm_energy = sum(openmm_result["sub_term_energies"][sub_term] for sub_term in sub_terms)

        if keyword == "ecoul+elong":
            lammps_energy = lammps_thermo["ecoul"] + lammps_thermo["elong"]
        else:
            lammps_energy = lammps_thermo[keyword]

        keyword_energies[keyword] = (lammps_energy, openmm_energy)

    comparison = {
        "keyword_energies": keyword_energies,
        "sub_term_energies": openmm_result["sub_term_energies"],
        "lammps_thermo": lammps_thermo,
        "lammps_forces": lammps_forces,
        "openmm_forces": openmm_result["forces"],
    }

    if settings["periodic"] and topology.lj_tail_correction:
        comparison["lj_tail"] = lj_tail_energies(topology, system, positions_nm)

    if settings["coulomb_method"] == "ewald":
        comparison["lammps_erfc_error"] = lammps_erfc_approximation_error(topology, positions_angstrom, lammps_g_ewald(files["log"]))

    return comparison


# --- Term-by-term comparison of parameterized topologies ------------------------------------------------------------

# EMC writes coefficients with 5 decimals and charges with 4; pcff.frc values have at most 4 decimals.
COEFFICIENT_TOLERANCE = 1e-5
CHARGE_TOLERANCE_E = 6e-5


def reversed_angle_coefficients(angle) -> dict:
    """Coefficients of an angle term rewritten for the reversed atom order k-j-i."""
    m, r1, r2 = angle.bond_bond
    n1, n2, ba_r1, ba_r2 = angle.bond_angle

    return {
        "quartic": angle.quartic,
        "bond_bond": (m, r2, r1),
        "bond_angle": (n2, n1, ba_r2, ba_r1),
    }


def reversed_dihedral_coefficients(dihedral) -> dict:
    """Coefficients of a dihedral term rewritten for the reversed atom order l-k-j-i (phi is unchanged)."""
    end_bond = dihedral.end_bond_torsion
    angle_torsion = dihedral.angle_torsion
    angle_angle_torsion = dihedral.angle_angle_torsion
    bond_bond_13 = dihedral.bond_bond_13

    return {
        "torsion": dihedral.torsion,
        "middle_bond_torsion": dihedral.middle_bond_torsion,
        "end_bond_torsion": (*end_bond[3:6], *end_bond[0:3], end_bond[7], end_bond[6]),
        "angle_torsion": (*angle_torsion[3:6], *angle_torsion[0:3], angle_torsion[7], angle_torsion[6]),
        "angle_angle_torsion": (angle_angle_torsion[0], angle_angle_torsion[2], angle_angle_torsion[1]),
        "bond_bond_13": (bond_bond_13[0], bond_bond_13[2], bond_bond_13[1]),
    }


def improper_coefficients_by_atoms(improper) -> dict:
    """
    Improper coefficients keyed by atoms instead of positions, so that any order of the outer atoms compares equal.
    M1, M2, M3 couple the two angles that share outer atom k, i, l respectively; theta1, theta2, theta3 belong to the outer pairs (i, k), (i, l), (k, l).
    The Wilson term is symmetric in the outer atoms when chi0 = 0, which holds for every entry used here.
    """
    atom_i, atom_j, atom_k, atom_l = improper.atoms
    m1, m2, m3, theta1, theta2, theta3 = improper.angle_angle

    return {
        "wilson": improper.wilson,
        ("angle_angle M, shared atom", atom_k): (m1,),
        ("angle_angle M, shared atom", atom_i): (m2,),
        ("angle_angle M, shared atom", atom_l): (m3,),
        ("angle_angle theta0, outer pair", frozenset((atom_i, atom_k))): (theta1,),
        ("angle_angle theta0, outer pair", frozenset((atom_i, atom_l))): (theta2,),
        ("angle_angle theta0, outer pair", frozenset((atom_k, atom_l))): (theta3,),
    }


def values_equal(values, reference_values, tolerance: float) -> bool:
    if values is None or reference_values is None or len(values) != len(reference_values):
        return False

    return all(abs(value - reference_value) <= tolerance for value, reference_value in zip(values, reference_values))


def parameter_differences(topology: ParameterizedTopology, reference: ParameterizedTopology) -> list[str]:
    """
    Compare two parameterized topologies of the same structure term by term, independent of the atom order within each term.
    Returns one line per kind of difference (empty if they agree): what differs, the atom types, and both values.
    """
    differences = set()
    types = reference.atom_type_names

    def record(kind, atoms, value, reference_value):
        differences.add(f"{kind} {'-'.join(types[atom] for atom in atoms)}: {value} vs {reference_value}")

    # Per atom.
    for atom in range(len(types)):
        if topology.atom_type_names[atom] != types[atom]:
            record("type", (atom,), topology.atom_type_names[atom], types[atom])
        if abs(topology.charges_e[atom] - reference.charges_e[atom]) > CHARGE_TOLERANCE_E:
            record("charge", (atom,), topology.charges_e[atom], reference.charges_e[atom])
        if abs(topology.masses_amu[atom] - reference.masses_amu[atom]) > COEFFICIENT_TOLERANCE:
            record("mass", (atom,), topology.masses_amu[atom], reference.masses_amu[atom])

        lj = (topology.lj_epsilon_kcal_mol[atom], topology.lj_sigma_angstrom[atom])
        reference_lj = (reference.lj_epsilon_kcal_mol[atom], reference.lj_sigma_angstrom[atom])
        if not values_equal(lj, reference_lj, COEFFICIENT_TOLERANCE):
            record("lj", (atom,), lj, reference_lj)

    # Term sets must be identical up to atom order within each term.
    term_lists = {
        "bonds": (topology.bonds, reference.bonds),
        "angles": (topology.angles, reference.angles),
        "dihedrals": (topology.dihedrals, reference.dihedrals),
        "impropers": (topology.impropers, reference.impropers),
    }

    reference_bonds = {frozenset(bond.atoms): bond for bond in reference.bonds}

    reference_angles = {}
    for angle in reference.angles:
        reference_angles[angle.atoms] = {"quartic": angle.quartic, "bond_bond": angle.bond_bond, "bond_angle": angle.bond_angle}
        reference_angles[angle.atoms[::-1]] = reversed_angle_coefficients(angle)

    reference_dihedrals = {}
    for dihedral in reference.dihedrals:
        reference_dihedrals[dihedral.atoms] = {
            "torsion": dihedral.torsion,
            "middle_bond_torsion": dihedral.middle_bond_torsion,
            "end_bond_torsion": dihedral.end_bond_torsion,
            "angle_torsion": dihedral.angle_torsion,
            "angle_angle_torsion": dihedral.angle_angle_torsion,
            "bond_bond_13": dihedral.bond_bond_13,
        }
        reference_dihedrals[dihedral.atoms[::-1]] = reversed_dihedral_coefficients(dihedral)

    def improper_key(improper):
        atom_i, atom_j, atom_k, atom_l = improper.atoms
        return (atom_j, frozenset((atom_i, atom_k, atom_l)))

    reference_impropers = {improper_key(improper): improper_coefficients_by_atoms(improper) for improper in reference.impropers}

    for kind, (terms, reference_terms) in term_lists.items():
        if len(terms) != len(reference_terms):
            differences.add(f"number of {kind}: {len(terms)} vs {len(reference_terms)}")

    for bond in topology.bonds:
        reference_bond = reference_bonds.get(frozenset(bond.atoms))
        if reference_bond is None:
            record("bond missing in reference", bond.atoms, bond.quartic, None)
        elif not values_equal(bond.quartic, reference_bond.quartic, COEFFICIENT_TOLERANCE):
            record("bond", bond.atoms, bond.quartic, reference_bond.quartic)

    for angle in topology.angles:
        reference_coefficients = reference_angles.get(angle.atoms)
        if reference_coefficients is None:
            record("angle missing in reference", angle.atoms, None, None)
            continue
        for sub_term in ["quartic", "bond_bond", "bond_angle"]:
            if not values_equal(getattr(angle, sub_term), reference_coefficients[sub_term], COEFFICIENT_TOLERANCE):
                record(f"angle {sub_term}", angle.atoms, getattr(angle, sub_term), reference_coefficients[sub_term])

    for dihedral in topology.dihedrals:
        reference_coefficients = reference_dihedrals.get(dihedral.atoms)
        if reference_coefficients is None:
            record("dihedral missing in reference", dihedral.atoms, None, None)
            continue
        for sub_term, reference_values in reference_coefficients.items():
            if not values_equal(getattr(dihedral, sub_term), reference_values, COEFFICIENT_TOLERANCE):
                record(f"dihedral {sub_term}", dihedral.atoms, getattr(dihedral, sub_term), reference_values)

    for improper in topology.impropers:
        reference_coefficients = reference_impropers.get(improper_key(improper))
        if reference_coefficients is None:
            record("improper missing in reference", improper.atoms, None, None)
            continue
        for key, values in improper_coefficients_by_atoms(improper).items():
            if not values_equal(values, reference_coefficients[key], COEFFICIENT_TOLERANCE):
                label = key if isinstance(key, str) else key[0]
                record(f"improper {label}", improper.atoms, values, reference_coefficients[key])

    return sorted(differences)
