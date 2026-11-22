"""Build an OpenMM System from a ParameterizedTopology.

All unit conversion from LAMMPS real units happens here, next to the expression that uses each coefficient.
By default (merge_bonded=True) each bonded family (angle, dihedral, improper) is one force in one force group per LAMMPS energy keyword (MERGED_FORCE_GROUPS).
With merge_bonded=False every PCFF sub-term is a separate force in its own force group (FORCE_GROUPS), written as a readable expression
that follows the LAMMPS class2 definition; this per-sub-term layout is the validated reference for the merged one.
LAMMPS_KEYWORD_SUB_TERMS maps the per-sub-term groups back to the LAMMPS thermo keywords for comparison.
"""

import math

import openmm

from openmm_pcff.ptop import ParameterizedTopology
from openmm_pcff.units import KJ_PER_KCAL, NM_PER_ANGSTROM, RADIANS_PER_DEGREE


FORCE_GROUPS = {
    "bond": 1,
    "angle": 2,
    "bond_bond": 3,
    "bond_angle": 4,
    "torsion": 5,
    "middle_bond_torsion": 6,
    "end_bond_torsion": 7,
    "angle_torsion": 8,
    "angle_angle_torsion": 9,
    "bond_bond_13": 10,
    "wilson": 11,
    "angle_angle": 12,
    "lj_9_6": 13,
    "coulomb": 14,
}

# LAMMPS reports Coulomb as ecoul (real space) + elong (k-space); the split depends on the Ewald parameter, so only the sum is comparable.
LAMMPS_KEYWORD_SUB_TERMS = {
    "ebond": ["bond"],
    "eangle": ["angle", "bond_bond", "bond_angle"],
    "edihed": ["torsion", "middle_bond_torsion", "end_bond_torsion", "angle_torsion", "angle_angle_torsion", "bond_bond_13"],
    "eimp": ["wilson", "angle_angle"],
    "evdwl": ["lj_9_6"],
    "ecoul+elong": ["coulomb"],
}

# Force groups of the merged bonded layout (build_system(..., merge_bonded=True)): one group per LAMMPS energy keyword.
# Group numbers reuse those of the first sub-term of each family.
MERGED_FORCE_GROUPS = {
    "ebond": 1,
    "eangle": 2,
    "edihed": 5,
    "eimp": 11,
    "evdwl": 13,
    "ecoul+elong": 14,
}

COULOMB_METHODS = ["pme", "ewald", "no_cutoff"]


def nm(length_angstrom: float) -> float:
    return length_angstrom * NM_PER_ANGSTROM


def rad(angle_degree: float) -> float:
    return angle_degree * RADIANS_PER_DEGREE


def kj_per_mol(energy_kcal_mol: float) -> float:
    """Convert any coefficient whose unit is kcal/mol per radian^n (radians are unchanged)."""
    return energy_kcal_mol * KJ_PER_KCAL


def kj_per_mol_per_nm(coefficient_kcal_mol_per_angstrom_n: float, length_power: int) -> float:
    """Convert a coefficient in kcal/mol/Angstrom^n (times radians^m) to kJ/mol/nm^n."""
    return coefficient_kcal_mol_per_angstrom_n * KJ_PER_KCAL / NM_PER_ANGSTROM**length_power


def excluded_pairs_12_13(n_atoms: int, bonds: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Return all 1-2 and 1-3 pairs (i < j) of the bond graph; this is what 'special_bonds lj/coul 0 0 1' excludes."""
    neighbors = [set() for _ in range(n_atoms)]

    for i, j in bonds:
        neighbors[i].add(j)
        neighbors[j].add(i)

    pairs = set()

    for center in range(n_atoms):
        for i in neighbors[center]:
            # 1-2 pair.
            pairs.add((min(center, i), max(center, i)))

            # 1-3 pairs through this center.
            for j in neighbors[center]:
                if i < j:
                    pairs.add((i, j))

    return sorted(pairs)


def add_bond_force(system: openmm.System, topology: ParameterizedTopology) -> None:
    force = openmm.CustomBondForce("K2*dr^2 + K3*dr^3 + K4*dr^4; dr = r - r0")

    for name in ["r0", "K2", "K3", "K4"]:
        force.addPerBondParameter(name)

    for bond in topology.bonds:
        r0, k2, k3, k4 = bond.quartic
        force.addBond(
            *bond.atoms,
            [
                nm(r0),
                kj_per_mol_per_nm(k2, 2),
                kj_per_mol_per_nm(k3, 3),
                kj_per_mol_per_nm(k4, 4),
            ],
        )

    force.setForceGroup(FORCE_GROUPS["bond"])
    system.addForce(force)


def add_angle_forces(system: openmm.System, topology: ParameterizedTopology) -> None:
    # Quartic angle term.
    angle_force = openmm.CustomAngleForce("K2*dtheta^2 + K3*dtheta^3 + K4*dtheta^4; dtheta = theta - theta0")

    for name in ["theta0", "K2", "K3", "K4"]:
        angle_force.addPerAngleParameter(name)

    # Bond-bond coupling of the two bonds of the angle.
    bond_bond_force = openmm.CustomCompoundBondForce(3, "M*(distance(p1,p2) - r1)*(distance(p2,p3) - r2)")

    for name in ["M", "r1", "r2"]:
        bond_bond_force.addPerBondParameter(name)

    # Bond-angle coupling; theta0 is the quartic-angle reference, as in LAMMPS.
    bond_angle_force = openmm.CustomCompoundBondForce(
        3,
        "(N1*(distance(p1,p2) - r1) + N2*(distance(p2,p3) - r2))*(angle(p1,p2,p3) - theta0)",
    )

    for name in ["N1", "N2", "r1", "r2", "theta0"]:
        bond_angle_force.addPerBondParameter(name)

    for angle in topology.angles:
        theta0, k2, k3, k4 = angle.quartic
        bb_m, bb_r1, bb_r2 = angle.bond_bond
        ba_n1, ba_n2, ba_r1, ba_r2 = angle.bond_angle

        angle_force.addAngle(
            *angle.atoms,
            [
                rad(theta0),
                kj_per_mol(k2),
                kj_per_mol(k3),
                kj_per_mol(k4),
            ],
        )

        bond_bond_force.addBond(
            list(angle.atoms),
            [
                kj_per_mol_per_nm(bb_m, 2),
                nm(bb_r1),
                nm(bb_r2),
            ],
        )

        bond_angle_force.addBond(
            list(angle.atoms),
            [
                kj_per_mol_per_nm(ba_n1, 1),
                kj_per_mol_per_nm(ba_n2, 1),
                nm(ba_r1),
                nm(ba_r2),
                rad(theta0),
            ],
        )

    angle_force.setForceGroup(FORCE_GROUPS["angle"])
    bond_bond_force.setForceGroup(FORCE_GROUPS["bond_bond"])
    bond_angle_force.setForceGroup(FORCE_GROUPS["bond_angle"])

    system.addForce(angle_force)
    system.addForce(bond_bond_force)
    system.addForce(bond_angle_force)


def add_dihedral_forces(system: openmm.System, topology: ParameterizedTopology) -> None:
    # OpenMM's dihedral angle is 0 for cis and +-pi for trans, as in LAMMPS class2.
    torsion_force = openmm.CustomTorsionForce(
        "K1*(1 - cos(theta - phi1)) + K2*(1 - cos(2*theta - phi2)) + K3*(1 - cos(3*theta - phi3))"
    )

    for name in ["K1", "phi1", "K2", "phi2", "K3", "phi3"]:
        torsion_force.addPerTorsionParameter(name)

    middle_bond_torsion_force = openmm.CustomCompoundBondForce(
        4,
        "(distance(p2,p3) - r2)*(A1*cos(phi) + A2*cos(2*phi) + A3*cos(3*phi));"
        " phi = dihedral(p1,p2,p3,p4)",
    )

    for name in ["A1", "A2", "A3", "r2"]:
        middle_bond_torsion_force.addPerBondParameter(name)

    end_bond_torsion_force = openmm.CustomCompoundBondForce(
        4,
        "(distance(p1,p2) - r1)*(B1*cos(phi) + B2*cos(2*phi) + B3*cos(3*phi))"
        " + (distance(p3,p4) - r3)*(C1*cos(phi) + C2*cos(2*phi) + C3*cos(3*phi));"
        " phi = dihedral(p1,p2,p3,p4)",
    )

    for name in ["B1", "B2", "B3", "C1", "C2", "C3", "r1", "r3"]:
        end_bond_torsion_force.addPerBondParameter(name)

    angle_torsion_force = openmm.CustomCompoundBondForce(
        4,
        "(angle(p1,p2,p3) - theta1)*(D1*cos(phi) + D2*cos(2*phi) + D3*cos(3*phi))"
        " + (angle(p2,p3,p4) - theta2)*(E1*cos(phi) + E2*cos(2*phi) + E3*cos(3*phi));"
        " phi = dihedral(p1,p2,p3,p4)",
    )

    for name in ["D1", "D2", "D3", "E1", "E2", "E3", "theta1", "theta2"]:
        angle_torsion_force.addPerBondParameter(name)

    angle_angle_torsion_force = openmm.CustomCompoundBondForce(
        4,
        "M*(angle(p1,p2,p3) - theta1)*(angle(p2,p3,p4) - theta2)*cos(dihedral(p1,p2,p3,p4))",
    )

    for name in ["M", "theta1", "theta2"]:
        angle_angle_torsion_force.addPerBondParameter(name)

    bond_bond_13_force = openmm.CustomCompoundBondForce(4, "N*(distance(p1,p2) - r1)*(distance(p3,p4) - r3)")

    for name in ["N", "r1", "r3"]:
        bond_bond_13_force.addPerBondParameter(name)

    for dihedral in topology.dihedrals:
        atoms = list(dihedral.atoms)

        k1, phi1, k2, phi2, k3, phi3 = dihedral.torsion
        torsion_force.addTorsion(
            *atoms,
            [
                kj_per_mol(k1),
                rad(phi1),
                kj_per_mol(k2),
                rad(phi2),
                kj_per_mol(k3),
                rad(phi3),
            ],
        )

        a1, a2, a3, mbt_r2 = dihedral.middle_bond_torsion
        middle_bond_torsion_force.addBond(
            atoms,
            [
                kj_per_mol_per_nm(a1, 1),
                kj_per_mol_per_nm(a2, 1),
                kj_per_mol_per_nm(a3, 1),
                nm(mbt_r2),
            ],
        )

        b1, b2, b3, c1, c2, c3, ebt_r1, ebt_r3 = dihedral.end_bond_torsion
        end_bond_torsion_force.addBond(
            atoms,
            [
                kj_per_mol_per_nm(b1, 1),
                kj_per_mol_per_nm(b2, 1),
                kj_per_mol_per_nm(b3, 1),
                kj_per_mol_per_nm(c1, 1),
                kj_per_mol_per_nm(c2, 1),
                kj_per_mol_per_nm(c3, 1),
                nm(ebt_r1),
                nm(ebt_r3),
            ],
        )

        d1, d2, d3, e1, e2, e3, at_theta1, at_theta2 = dihedral.angle_torsion
        angle_torsion_force.addBond(
            atoms,
            [
                kj_per_mol(d1),
                kj_per_mol(d2),
                kj_per_mol(d3),
                kj_per_mol(e1),
                kj_per_mol(e2),
                kj_per_mol(e3),
                rad(at_theta1),
                rad(at_theta2),
            ],
        )

        aat_m, aat_theta1, aat_theta2 = dihedral.angle_angle_torsion
        angle_angle_torsion_force.addBond(
            atoms,
            [
                kj_per_mol(aat_m),
                rad(aat_theta1),
                rad(aat_theta2),
            ],
        )

        bb13_n, bb13_r1, bb13_r3 = dihedral.bond_bond_13
        bond_bond_13_force.addBond(
            atoms,
            [
                kj_per_mol_per_nm(bb13_n, 2),
                nm(bb13_r1),
                nm(bb13_r3),
            ],
        )

    torsion_force.setForceGroup(FORCE_GROUPS["torsion"])
    middle_bond_torsion_force.setForceGroup(FORCE_GROUPS["middle_bond_torsion"])
    end_bond_torsion_force.setForceGroup(FORCE_GROUPS["end_bond_torsion"])
    angle_torsion_force.setForceGroup(FORCE_GROUPS["angle_torsion"])
    angle_angle_torsion_force.setForceGroup(FORCE_GROUPS["angle_angle_torsion"])
    bond_bond_13_force.setForceGroup(FORCE_GROUPS["bond_bond_13"])

    system.addForce(torsion_force)
    system.addForce(middle_bond_torsion_force)
    system.addForce(end_bond_torsion_force)
    system.addForce(angle_torsion_force)
    system.addForce(angle_angle_torsion_force)
    system.addForce(bond_bond_13_force)


def add_improper_forces(system: openmm.System, topology: ParameterizedTopology) -> None:
    # Wilson out-of-plane, following improper_class2.cpp with atoms A=p1, B=p2 (center), C=p3, D=p4.
    # The triple product (rCB x rDB) . rAB is cyclic, so all three out-of-plane angles share it:
    # chi_ABCD = asin(triple / (|rAB||rCB||rDB| sin(theta_CBD))), chi_CBDA uses sin(theta_ABD), chi_DBAC uses sin(theta_ABC).
    wilson_force = openmm.CustomCompoundBondForce(
        4,
        "K*(chi - chi0)^2;"
        " chi = (asin(s/sin(angle(p3,p2,p4))) + asin(s/sin(angle(p1,p2,p4))) + asin(s/sin(angle(p1,p2,p3))))/3;"
        " s = triple/(distance(p1,p2)*distance(p3,p2)*distance(p4,p2));"
        " triple = xab*(ycb*zdb - zcb*ydb) + yab*(zcb*xdb - xcb*zdb) + zab*(xcb*ydb - ycb*xdb);"
        " xab = x1 - x2; yab = y1 - y2; zab = z1 - z2;"
        " xcb = x3 - x2; ycb = y3 - y2; zcb = z3 - z2;"
        " xdb = x4 - x2; ydb = y4 - y2; zdb = z4 - z2",
    )

    for name in ["K", "chi0"]:
        wilson_force.addPerBondParameter(name)

    # Angle-angle coupling of the three angles at the center: theta_ijk (theta1), theta_ijl (theta2), theta_kjl (theta3).
    angle_angle_force = openmm.CustomCompoundBondForce(
        4,
        "M1*(theta_ijk - theta1)*(theta_kjl - theta3)"
        " + M2*(theta_ijk - theta1)*(theta_ijl - theta2)"
        " + M3*(theta_ijl - theta2)*(theta_kjl - theta3);"
        " theta_ijk = angle(p1,p2,p3); theta_ijl = angle(p1,p2,p4); theta_kjl = angle(p3,p2,p4)",
    )

    for name in ["M1", "M2", "M3", "theta1", "theta2", "theta3"]:
        angle_angle_force.addPerBondParameter(name)

    for improper in topology.impropers:
        atoms = list(improper.atoms)

        wilson_k, chi0 = improper.wilson

        # LAMMPS skips the Wilson term when K = 0 (improper_class2.cpp, 'if (k0[type] == 0.0) continue'); the angle-angle part is kept.
        if wilson_k != 0.0:
            wilson_force.addBond(
                atoms,
                [
                    kj_per_mol(wilson_k),
                    rad(chi0),
                ],
            )

        m1, m2, m3, aa_theta1, aa_theta2, aa_theta3 = improper.angle_angle
        angle_angle_force.addBond(
            atoms,
            [
                kj_per_mol(m1),
                kj_per_mol(m2),
                kj_per_mol(m3),
                rad(aa_theta1),
                rad(aa_theta2),
                rad(aa_theta3),
            ],
        )

    wilson_force.setForceGroup(FORCE_GROUPS["wilson"])
    angle_angle_force.setForceGroup(FORCE_GROUPS["angle_angle"])

    system.addForce(wilson_force)
    system.addForce(angle_angle_force)


# --- Merged bonded layout -------------------------------------------------------------------------------------------
# Same energy as the per-sub-term forces above, with fewer forces: each family is one expression, so the geometry
# (distances, angles, dihedral) is computed once per interaction instead of once per sub-term.
# Zero parts are left out where that removes whole interactions: dihedrals without cross terms go to OpenMM's built-in periodic torsion,
# torsion components with K = 0 and impropers whose Wilson and angle-angle coefficients are all zero are dropped.
# This changes nothing in the energy or forces; zero sub-terms inside a kept interaction are still evaluated.


def add_merged_angle_force(system: openmm.System, topology: ParameterizedTopology) -> None:
    # Quartic angle + bond-bond + bond-angle; theta0 of the bond-angle term is the quartic-angle reference, as in LAMMPS.
    angle_force = openmm.CustomCompoundBondForce(
        3,
        "K2*dtheta^2 + K3*dtheta^3 + K4*dtheta^4"
        " + M*(r12 - bb_r1)*(r23 - bb_r2)"
        " + (N1*(r12 - ba_r1) + N2*(r23 - ba_r2))*dtheta;"
        " dtheta = angle(p1,p2,p3) - theta0;"
        " r12 = distance(p1,p2); r23 = distance(p2,p3)",
    )

    for name in ["theta0", "K2", "K3", "K4", "M", "bb_r1", "bb_r2", "N1", "N2", "ba_r1", "ba_r2"]:
        angle_force.addPerBondParameter(name)

    for angle in topology.angles:
        theta0, k2, k3, k4 = angle.quartic
        bb_m, bb_r1, bb_r2 = angle.bond_bond
        ba_n1, ba_n2, ba_r1, ba_r2 = angle.bond_angle

        angle_force.addBond(
            list(angle.atoms),
            [
                rad(theta0),
                kj_per_mol(k2),
                kj_per_mol(k3),
                kj_per_mol(k4),
                kj_per_mol_per_nm(bb_m, 2),
                nm(bb_r1),
                nm(bb_r2),
                kj_per_mol_per_nm(ba_n1, 1),
                kj_per_mol_per_nm(ba_n2, 1),
                nm(ba_r1),
                nm(ba_r2),
            ],
        )

    angle_force.setForceGroup(MERGED_FORCE_GROUPS["eangle"])
    system.addForce(angle_force)


def dihedral_has_cross_terms(dihedral) -> bool:
    """True if any coefficient of the five dihedral cross terms is nonzero (reference values excluded)."""
    a1, a2, a3, _ = dihedral.middle_bond_torsion
    b1, b2, b3, c1, c2, c3, _, _ = dihedral.end_bond_torsion
    d1, d2, d3, e1, e2, e3, _, _ = dihedral.angle_torsion
    aat_m, _, _ = dihedral.angle_angle_torsion
    bb13_n, _, _ = dihedral.bond_bond_13

    return any(value != 0.0 for value in [a1, a2, a3, b1, b2, b3, c1, c2, c3, d1, d2, d3, e1, e2, e3, aat_m, bb13_n])


def add_merged_dihedral_forces(system: openmm.System, topology: ParameterizedTopology) -> None:
    # Dihedrals with cross terms: torsion + middle-bond-torsion + end-bond-torsion + angle-torsion + angle-angle-torsion + bond-bond-13 in one expression.
    dihedral_force = openmm.CustomCompoundBondForce(
        4,
        "K1*(1 - cos(phi - phi1)) + K2*(1 - cos(2*phi - phi2)) + K3*(1 - cos(3*phi - phi3))"
        " + (r23 - mbt_r2)*(A1*cos1 + A2*cos2 + A3*cos3)"
        " + (r12 - ebt_r1)*(B1*cos1 + B2*cos2 + B3*cos3)"
        " + (r34 - ebt_r3)*(C1*cos1 + C2*cos2 + C3*cos3)"
        " + (theta123 - at_theta1)*(D1*cos1 + D2*cos2 + D3*cos3)"
        " + (theta234 - at_theta2)*(E1*cos1 + E2*cos2 + E3*cos3)"
        " + aat_M*(theta123 - aat_theta1)*(theta234 - aat_theta2)*cos1"
        " + bb13_N*(r12 - bb13_r1)*(r34 - bb13_r3);"
        " cos1 = cos(phi); cos2 = cos(2*phi); cos3 = cos(3*phi);"
        " phi = dihedral(p1,p2,p3,p4);"
        " theta123 = angle(p1,p2,p3); theta234 = angle(p2,p3,p4);"
        " r12 = distance(p1,p2); r23 = distance(p2,p3); r34 = distance(p3,p4)",
    )

    parameter_names = [
        "K1", "phi1", "K2", "phi2", "K3", "phi3",
        "A1", "A2", "A3", "mbt_r2",
        "B1", "B2", "B3", "C1", "C2", "C3", "ebt_r1", "ebt_r3",
        "D1", "D2", "D3", "E1", "E2", "E3", "at_theta1", "at_theta2",
        "aat_M", "aat_theta1", "aat_theta2",
        "bb13_N", "bb13_r1", "bb13_r3",
    ]  # fmt: skip

    for name in parameter_names:
        dihedral_force.addPerBondParameter(name)

    # Dihedrals without cross terms: the torsion alone, as OpenMM's built-in periodic torsion.
    # K*(1 - cos(n*phi - phi_n)) = K*(1 + cos(n*phi - (phi_n + pi))), the PeriodicTorsionForce form with phase phi_n + pi.
    periodic_torsion_force = openmm.PeriodicTorsionForce()

    for dihedral in topology.dihedrals:
        atoms = list(dihedral.atoms)
        k1, phi1, k2, phi2, k3, phi3 = dihedral.torsion

        if not dihedral_has_cross_terms(dihedral):
            for periodicity, k, phi in [(1, k1, phi1), (2, k2, phi2), (3, k3, phi3)]:
                if k != 0.0:
                    periodic_torsion_force.addTorsion(*atoms, periodicity, rad(phi) + math.pi, kj_per_mol(k))
            continue

        a1, a2, a3, mbt_r2 = dihedral.middle_bond_torsion
        b1, b2, b3, c1, c2, c3, ebt_r1, ebt_r3 = dihedral.end_bond_torsion
        d1, d2, d3, e1, e2, e3, at_theta1, at_theta2 = dihedral.angle_torsion
        aat_m, aat_theta1, aat_theta2 = dihedral.angle_angle_torsion
        bb13_n, bb13_r1, bb13_r3 = dihedral.bond_bond_13

        dihedral_force.addBond(
            atoms,
            [
                kj_per_mol(k1), rad(phi1), kj_per_mol(k2), rad(phi2), kj_per_mol(k3), rad(phi3),
                kj_per_mol_per_nm(a1, 1), kj_per_mol_per_nm(a2, 1), kj_per_mol_per_nm(a3, 1), nm(mbt_r2),
                kj_per_mol_per_nm(b1, 1), kj_per_mol_per_nm(b2, 1), kj_per_mol_per_nm(b3, 1),
                kj_per_mol_per_nm(c1, 1), kj_per_mol_per_nm(c2, 1), kj_per_mol_per_nm(c3, 1), nm(ebt_r1), nm(ebt_r3),
                kj_per_mol(d1), kj_per_mol(d2), kj_per_mol(d3),
                kj_per_mol(e1), kj_per_mol(e2), kj_per_mol(e3), rad(at_theta1), rad(at_theta2),
                kj_per_mol(aat_m), rad(aat_theta1), rad(aat_theta2),
                kj_per_mol_per_nm(bb13_n, 2), nm(bb13_r1), nm(bb13_r3),
            ],
        )  # fmt: skip

    for force in [dihedral_force, periodic_torsion_force]:
        force.setForceGroup(MERGED_FORCE_GROUPS["edihed"])
        system.addForce(force)


def add_merged_improper_forces(system: openmm.System, topology: ParameterizedTopology) -> None:
    # Angle-angle coupling of the three angles at the center (same definition as add_improper_forces).
    angle_angle_energy = (
        "M1*(theta_ijk - theta1)*(theta_kjl - theta3)"
        " + M2*(theta_ijk - theta1)*(theta_ijl - theta2)"
        " + M3*(theta_ijl - theta2)*(theta_kjl - theta3)"
    )
    angles_at_center = "theta_ijk = angle(p1,p2,p3); theta_ijl = angle(p1,p2,p4); theta_kjl = angle(p3,p2,p4)"

    # Impropers with a Wilson term: Wilson + angle-angle, sharing the three angles at the center.
    # Wilson as in add_improper_forces: chi_ABCD uses sin(theta_CBD) = sin(theta_kjl), chi_CBDA sin(theta_ABD) = sin(theta_ijl), chi_DBAC sin(theta_ABC) = sin(theta_ijk).
    wilson_angle_angle_force = openmm.CustomCompoundBondForce(
        4,
        f"K*(chi - chi0)^2 + {angle_angle_energy};"
        " chi = (asin(s/sin(theta_kjl)) + asin(s/sin(theta_ijl)) + asin(s/sin(theta_ijk)))/3;"
        " s = triple/(distance(p1,p2)*distance(p3,p2)*distance(p4,p2));"
        " triple = xab*(ycb*zdb - zcb*ydb) + yab*(zcb*xdb - xcb*zdb) + zab*(xcb*ydb - ycb*xdb);"
        " xab = x1 - x2; yab = y1 - y2; zab = z1 - z2;"
        " xcb = x3 - x2; ycb = y3 - y2; zcb = z3 - z2;"
        " xdb = x4 - x2; ydb = y4 - y2; zdb = z4 - z2;"
        f" {angles_at_center}",
    )

    # Impropers without a Wilson term (K = 0, skipped by LAMMPS): angle-angle only.
    angle_angle_force = openmm.CustomCompoundBondForce(4, f"{angle_angle_energy}; {angles_at_center}")

    for name in ["K", "chi0", "M1", "M2", "M3", "theta1", "theta2", "theta3"]:
        wilson_angle_angle_force.addPerBondParameter(name)

    for name in ["M1", "M2", "M3", "theta1", "theta2", "theta3"]:
        angle_angle_force.addPerBondParameter(name)

    for improper in topology.impropers:
        atoms = list(improper.atoms)
        wilson_k, chi0 = improper.wilson
        m1, m2, m3, aa_theta1, aa_theta2, aa_theta3 = improper.angle_angle

        angle_angle_parameters = [
            kj_per_mol(m1),
            kj_per_mol(m2),
            kj_per_mol(m3),
            rad(aa_theta1),
            rad(aa_theta2),
            rad(aa_theta3),
        ]

        if wilson_k != 0.0:
            wilson_angle_angle_force.addBond(atoms, [kj_per_mol(wilson_k), rad(chi0), *angle_angle_parameters])
        elif any(m != 0.0 for m in [m1, m2, m3]):
            angle_angle_force.addBond(atoms, angle_angle_parameters)

    for force in [wilson_angle_angle_force, angle_angle_force]:
        force.setForceGroup(MERGED_FORCE_GROUPS["eimp"])
        system.addForce(force)


def add_lj_force(system: openmm.System, topology: ParameterizedTopology, periodic: bool, excluded_pairs: list[tuple[int, int]]) -> None:
    # 9-6 LJ with sixth-power mixing, as lj/class2 (pair_lj_class2.cpp, init_one); sigma is the position of the minimum.
    lj_force = openmm.CustomNonbondedForce(
        "epsilon_ij*(2*(sigma_ij/r)^9 - 3*(sigma_ij/r)^6);"
        " sigma_ij = ((sigma1^6 + sigma2^6)/2)^(1/6);"
        " epsilon_ij = 2*sqrt(epsilon1*epsilon2)*sigma1^3*sigma2^3/(sigma1^6 + sigma2^6)"
    )
    lj_force.addPerParticleParameter("sigma")
    lj_force.addPerParticleParameter("epsilon")

    for sigma_angstrom, epsilon_kcal_mol in zip(topology.lj_sigma_angstrom, topology.lj_epsilon_kcal_mol):
        lj_force.addParticle([nm(sigma_angstrom), kj_per_mol(epsilon_kcal_mol)])

    if periodic:
        # Plain truncation at the cutoff (no switch, no shift), as lj/class2.
        lj_force.setNonbondedMethod(openmm.CustomNonbondedForce.CutoffPeriodic)
        lj_force.setCutoffDistance(nm(topology.lj_cutoff_angstrom))
        lj_force.setUseSwitchingFunction(False)
        lj_force.setUseLongRangeCorrection(topology.lj_tail_correction)
    else:
        lj_force.setNonbondedMethod(openmm.CustomNonbondedForce.NoCutoff)

    for i, j in excluded_pairs:
        lj_force.addExclusion(i, j)

    lj_force.setForceGroup(FORCE_GROUPS["lj_9_6"])
    system.addForce(lj_force)


def add_coulomb_force(
    system: openmm.System,
    topology: ParameterizedTopology,
    coulomb_method: str,
    ewald_error_tolerance: float | None,
    excluded_pairs: list[tuple[int, int]],
) -> None:
    coulomb_force = openmm.NonbondedForce()

    # LJ is handled by the 9-6 force, so every particle has epsilon = 0 here; sigma is then irrelevant.
    for charge_e in topology.charges_e:
        coulomb_force.addParticle(charge_e, 0.1, 0.0)

    # Excluded 1-2 and 1-3 pairs are omitted from the direct sum; 1-4 pairs get no exception and interact at full strength.
    for i, j in excluded_pairs:
        coulomb_force.addException(i, j, 0.0, 0.1, 0.0)

    if coulomb_method == "no_cutoff":
        coulomb_force.setNonbondedMethod(openmm.NonbondedForce.NoCutoff)
    else:
        if coulomb_method == "pme":
            coulomb_force.setNonbondedMethod(openmm.NonbondedForce.PME)
        else:
            coulomb_force.setNonbondedMethod(openmm.NonbondedForce.Ewald)

        coulomb_force.setCutoffDistance(nm(topology.coulomb_cutoff_angstrom))
        coulomb_force.setEwaldErrorTolerance(ewald_error_tolerance)

    coulomb_force.setUseDispersionCorrection(False)
    coulomb_force.setForceGroup(FORCE_GROUPS["coulomb"])
    system.addForce(coulomb_force)


def build_system(
    topology: ParameterizedTopology,
    periodic: bool,
    coulomb_method: str | None,
    ewald_error_tolerance: float | None = None,
    merge_bonded: bool = True,
) -> openmm.System:
    """
    Build an OpenMM System reproducing LAMMPS class2 energies for this topology.

    Parameters
    ----------
    topology : ParameterizedTopology
        Coefficients in LAMMPS real units.
    periodic : bool
        True: orthorhombic box from the topology, LJ truncated at its cutoff with the tail correction if enabled.
        False: no box and no cutoff for LJ or Coulomb; equivalent to LAMMPS only if its cutoff exceeds every pair distance.
    coulomb_method : str or None
        "pme" or "ewald" (periodic), "no_cutoff" (non-periodic), or None for no Coulomb interaction at all.
    ewald_error_tolerance : float, optional
        OpenMM Ewald/PME error tolerance; required for "pme" and "ewald" and never set implicitly.
    merge_bonded : bool, optional
        True (default): one force per bonded family with all-zero terms left out (MERGED_FORCE_GROUPS, one group per LAMMPS keyword); same energy, faster.
        False: every bonded sub-term is its own force in its own group (FORCE_GROUPS), for energies per sub-term and term-by-term validation.
    """
    if coulomb_method is not None and coulomb_method not in COULOMB_METHODS:
        raise ValueError(f"coulomb_method must be one of {COULOMB_METHODS} or None.")

    if coulomb_method in ("pme", "ewald") and (not periodic or ewald_error_tolerance is None):
        raise ValueError("PME and Ewald need periodic=True and an explicit ewald_error_tolerance.")

    if coulomb_method == "no_cutoff" and periodic:
        raise ValueError("coulomb_method 'no_cutoff' is only valid for a non-periodic system.")

    if periodic and topology.box_lengths_angstrom is None:
        raise ValueError("periodic=True needs a box, but the structure has none (e.g. no CRYST1 record in a PDB file).")

    if coulomb_method is not None and topology.coulomb_cutoff_angstrom is None:
        raise ValueError("The pair style of this topology has no Coulomb interaction; use coulomb_method=None.")

    system = openmm.System()

    for mass_amu in topology.masses_amu:
        system.addParticle(mass_amu)

    if periodic:
        lx, ly, lz = (nm(length) for length in topology.box_lengths_angstrom)
        system.setDefaultPeriodicBoxVectors(
            openmm.Vec3(lx, 0.0, 0.0),
            openmm.Vec3(0.0, ly, 0.0),
            openmm.Vec3(0.0, 0.0, lz),
        )

    # Bonded forces use raw coordinates (no periodic wrapping), so molecules must be unwrapped, as in EMC data files.
    add_bond_force(system, topology)

    if merge_bonded:
        add_merged_angle_force(system, topology)
        add_merged_dihedral_forces(system, topology)
        add_merged_improper_forces(system, topology)
    else:
        add_angle_forces(system, topology)
        add_dihedral_forces(system, topology)
        add_improper_forces(system, topology)

    # Both nonbonded forces must share the same exclusion list (required by the GPU platforms).
    bond_pairs = [bond.atoms for bond in topology.bonds]
    excluded_pairs = excluded_pairs_12_13(len(topology.masses_amu), bond_pairs)

    add_lj_force(system, topology, periodic, excluded_pairs)

    if coulomb_method is not None:
        add_coulomb_force(system, topology, coulomb_method, ewald_error_tolerance, excluded_pairs)

    return system
