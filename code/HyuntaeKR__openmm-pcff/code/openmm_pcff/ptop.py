"""Parameterized topology: the intermediate representation between the parameter sources and the OpenMM system builder.

Every term stores its atom indices in the exact order used for its parameters, and its coefficients in LAMMPS real units,
grouped and ordered exactly as in the LAMMPS class2 coefficient lines.
Angles in coefficients are in degrees, as in the LAMMPS files.
Atom indices are 0-based.
"""

from dataclasses import dataclass, field


@dataclass
class BondTerm:
    # Atoms i, j.
    atoms: tuple[int, int]

    # E = K2 (r - r0)^2 + K3 (r - r0)^3 + K4 (r - r0)^4; coefficients (r0, K2, K3, K4).
    quartic: tuple[float, float, float, float]


@dataclass
class AngleTerm:
    # Atoms i, j, k with j the vertex.
    atoms: tuple[int, int, int]

    # E = K2 dtheta^2 + K3 dtheta^3 + K4 dtheta^4; coefficients (theta0, K2, K3, K4).
    quartic: tuple[float, float, float, float]

    # E = M (r_ij - r1)(r_jk - r2); coefficients (M, r1, r2).
    bond_bond: tuple[float, float, float]

    # E = N1 (r_ij - r1)(theta - theta0) + N2 (r_jk - r2)(theta - theta0); coefficients (N1, N2, r1, r2).
    bond_angle: tuple[float, float, float, float]


@dataclass
class DihedralTerm:
    # Atoms i, j, k, l; the middle bond is j-k.
    atoms: tuple[int, int, int, int]

    # E = sum_n Kn [1 - cos(n phi - phi_n)]; coefficients (K1, phi1, K2, phi2, K3, phi3).
    torsion: tuple[float, float, float, float, float, float]

    # E = (r_jk - r2) sum_n An cos(n phi); coefficients (A1, A2, A3, r2).
    middle_bond_torsion: tuple[float, float, float, float]

    # E = (r_ij - r1) sum_n Bn cos(n phi) + (r_kl - r3) sum_n Cn cos(n phi); coefficients (B1, B2, B3, C1, C2, C3, r1, r3).
    end_bond_torsion: tuple[float, float, float, float, float, float, float, float]

    # E = (theta_ijk - theta1) sum_n Dn cos(n phi) + (theta_jkl - theta2) sum_n En cos(n phi); coefficients (D1, D2, D3, E1, E2, E3, theta1, theta2).
    angle_torsion: tuple[float, float, float, float, float, float, float, float]

    # E = M (theta_ijk - theta1)(theta_jkl - theta2) cos(phi); coefficients (M, theta1, theta2).
    angle_angle_torsion: tuple[float, float, float]

    # E = N (r_ij - r1)(r_kl - r3); coefficients (N, r1, r3).
    bond_bond_13: tuple[float, float, float]


@dataclass
class ImproperTerm:
    # Atoms i, j, k, l with j the central atom.
    atoms: tuple[int, int, int, int]

    # E = K [(chi_ijkl + chi_kjli + chi_ljik)/3 - chi0]^2; coefficients (K, chi0).
    wilson: tuple[float, float]

    # E = M1 (theta_ijk - theta1)(theta_kjl - theta3) + M2 (theta_ijk - theta1)(theta_ijl - theta2) + M3 (theta_ijl - theta2)(theta_kjl - theta3);
    # coefficients (M1, M2, M3, theta1, theta2, theta3).
    angle_angle: tuple[float, float, float, float, float, float]


@dataclass
class ParameterizedTopology:
    # Per-atom data, indexed by atom.
    atom_type_names: list[str]
    masses_amu: list[float]
    charges_e: list[float]

    # 9-6 LJ per atom: E(r) = eps [2 (sigma/r)^9 - 3 (sigma/r)^6], sigma is the position of the minimum.
    # Unlike pairs are mixed with the sixth-power rule; explicit unlike-pair coefficients are not supported.
    lj_epsilon_kcal_mol: list[float]
    lj_sigma_angstrom: list[float]

    # Box edge lengths of an orthorhombic cell; None for a structure without a box (non-periodic only).
    box_lengths_angstrom: tuple[float, float, float] | None

    # Pair settings from the LAMMPS pair_style / pair_modify lines.
    lj_cutoff_angstrom: float
    coulomb_cutoff_angstrom: float | None
    lj_tail_correction: bool

    # special_bonds weights for 1-2, 1-3, 1-4 pairs; only (0, 0, 1) is supported (1-2 and 1-3 excluded, 1-4 at full strength).
    special_bonds_lj: tuple[float, float, float]
    special_bonds_coul: tuple[float, float, float]

    bonds: list[BondTerm] = field(default_factory=list)
    angles: list[AngleTerm] = field(default_factory=list)
    dihedrals: list[DihedralTerm] = field(default_factory=list)
    impropers: list[ImproperTerm] = field(default_factory=list)
