"""Core physical constants, geometric containers, topology terms, and state types.

All quantities follow GROMACS internal molecular dynamics units:
    * Length: nanometer (nm)
    * Time: picosecond (ps)
    * Mass: atomic mass unit (amu, g/mol)
    * Energy: kJ/mol
    * Force: kJ/(mol*nm)
    * Velocity: nm/ps
    * Charge: elementary charge (e)
    * Temperature: Kelvin (K)
    * Pressure: bar (1 bar = 0.0602214076 kJ/(mol*nm^3))
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]

# Physical constants in GROMACS units (nm, ps, amu, kJ/mol, K, e)
KB_KJ_MOL_K: float = 8.31446261815324e-3
COULOMB_CONST_KJ_MOL_NM_E2: float = 138.935457644382
AVOGADRO: float = 6.02214076e23
KJ_MOL_NM3_TO_BAR: float = 16.605390671738466
BAR_TO_KJ_MOL_NM3: float = 1.0 / KJ_MOL_NM3_TO_BAR
ATM_TO_BAR: float = 1.01325
EPSILON_FLOOR: float = 1e-12


@dataclass
class SimulationBox:
    """Periodic simulation cell supporting both orthorhombic and triclinic geometries.

    The lattice matrix ``vectors`` has box vectors stored as columns:
    ``H = [a, b, c]``, so fractional coordinates satisfy ``r = H @ s``.
    """

    vectors: FloatArray
    inv_vectors: FloatArray = field(init=False, repr=False)
    volume: float = field(init=False)
    is_orthorhombic: bool = field(init=False)

    def __post_init__(self) -> None:
        arr = np.asarray(self.vectors, dtype=np.float64)
        if arr.shape == (3,):
            arr = np.diag(arr)
        if arr.shape != (3, 3):
            raise ValueError(f"Expected (3, 3) or (3,) box vectors, got {arr.shape}")
        det = float(np.linalg.det(arr))
        if det <= 0.0:
            raise ValueError(f"Simulation box must be right-handed with positive volume, got det={det}")
        self.vectors = arr.copy()
        self.inv_vectors = np.asarray(np.linalg.inv(self.vectors), dtype=np.float64)
        self.volume = det
        off_diag = self.vectors - np.diag(np.diag(self.vectors))
        self.is_orthorhombic = bool(np.all(np.abs(off_diag) < 1e-12))

    @classmethod
    def orthorhombic(cls, lx: float, ly: float, lz: float) -> "SimulationBox":
        """Create an axis-aligned orthorhombic periodic box in nm."""
        if lx <= 0.0 or ly <= 0.0 or lz <= 0.0:
            raise ValueError("Box dimensions must be strictly positive")
        return cls(np.diag([float(lx), float(ly), float(lz)]))

    @classmethod
    def triclinic(
        cls,
        a: float,
        b: float,
        c: float,
        alpha_deg: float = 90.0,
        beta_deg: float = 90.0,
        gamma_deg: float = 90.0,
    ) -> "SimulationBox":
        """Construct a right-handed triclinic cell from edge lengths and angles (degrees)."""
        alpha = np.deg2rad(alpha_deg)
        beta = np.deg2rad(beta_deg)
        gamma = np.deg2rad(gamma_deg)
        cos_a, cos_b, cos_g = np.cos(alpha), np.cos(beta), np.cos(gamma)
        sin_g = np.sin(gamma)
        if sin_g <= 1e-9:
            raise ValueError("Degenerate triclinic gamma angle")
        ax, ay, az = a, 0.0, 0.0
        bx, by, bz = b * cos_g, b * sin_g, 0.0
        cx = c * cos_b
        cy = c * (cos_a - cos_b * cos_g) / sin_g
        cz_sq = c * c - cx * cx - cy * cy
        if cz_sq <= 0.0:
            raise ValueError("Inconsistent triclinic cell angles yield non-positive volume")
        cz = float(np.sqrt(cz_sq))
        mat = np.array([[ax, bx, cx], [ay, by, cy], [az, bz, cz]], dtype=np.float64)
        return cls(mat)

    def lengths(self) -> FloatArray:
        """Return Euclidean lengths (nm) of the three lattice vectors."""
        return np.asarray(np.linalg.norm(self.vectors, axis=0), dtype=np.float64)

    def scaled(self, factor: float | FloatArray) -> "SimulationBox":
        """Return a new box scaled isotropically or anisotropically along axes."""
        scale = np.asarray(factor, dtype=np.float64)
        if scale.ndim == 0:
            return SimulationBox(self.vectors * float(scale))
        if scale.shape == (3,):
            return SimulationBox(self.vectors @ np.diag(scale))
        raise ValueError(f"Invalid scaling factor shape: {scale.shape}")


@dataclass(frozen=True)
class AtomSpec:
    """Atomic identity, mass, partial charge, Lennard-Jones parameters, and alchemical role."""

    index: int
    name: str
    element: str
    residue_name: str
    residue_id: int
    mass: float
    charge: float
    sigma: float
    epsilon: float
    atom_type: str = "GAFF"
    is_alchemical: bool = False
    is_donor: bool = False
    is_acceptor: bool = False
    is_hydrophobic: bool = False
    formal_charge: int = 0


@dataclass(frozen=True)
class BondTerm:
    """Harmonic bond term ``0.5 * k_b * (r - r0)^2``."""

    i: int
    j: int
    r0: float
    kb: float


@dataclass(frozen=True)
class AngleTerm:
    """Harmonic angle term ``0.5 * k_theta * (theta - theta0)^2`` (radians)."""

    i: int
    j: int
    k: int
    theta0: float
    k_theta: float


@dataclass(frozen=True)
class DihedralTerm:
    """Proper periodic torsion ``k_phi * (1 + cos(n * phi - delta))``."""

    i: int
    j: int
    k: int
    l: int
    k_phi: float
    periodicity: int
    phase: float


@dataclass(frozen=True)
class RyckaertBellemansTerm:
    """Ryckaert-Bellemans torsion potential ``sum_{m=0}^5 C_m * cos(phi - pi)^m``."""

    i: int
    j: int
    k: int
    l: int
    coefficients: Tuple[float, float, float, float, float, float]


@dataclass(frozen=True)
class ImproperTerm:
    """Harmonic improper dihedral ``0.5 * k_omega * (omega - omega0)^2``."""

    i: int
    j: int
    k: int
    l: int
    omega0: float
    k_omega: float


@dataclass(frozen=True)
class ConstraintPair:
    """Holonomic distance constraint ``|r_i - r_j| = distance``."""

    i: int
    j: int
    distance: float


@dataclass(frozen=True)
class AlchemicalLambda:
    """Coupling parameters for alchemical free energy perturbation.

    ``lambda_elec`` scales solute-environment electrostatic interactions and
    ``lambda_vdw`` scales Beutler soft-core Lennard-Jones interactions.
    """

    lambda_elec: float = 1.0
    lambda_vdw: float = 1.0
    alpha_sc: float = 0.5
    p_power: int = 1
    q_power: int = 1

    def __post_init__(self) -> None:
        if not (0.0 <= self.lambda_elec <= 1.0 and 0.0 <= self.lambda_vdw <= 1.0):
            raise ValueError("Alchemical lambda parameters must lie in [0, 1]")


@dataclass
class Topology:
    """Complete molecular mechanics topology with vectorized parameter arrays."""

    atoms: List[AtomSpec]
    bonds: List[BondTerm] = field(default_factory=list)
    angles: List[AngleTerm] = field(default_factory=list)
    dihedrals: List[DihedralTerm] = field(default_factory=list)
    rb_dihedrals: List[RyckaertBellemansTerm] = field(default_factory=list)
    impropers: List[ImproperTerm] = field(default_factory=list)
    constraints: List[ConstraintPair] = field(default_factory=list)
    pairs_14: List[Tuple[int, int]] = field(default_factory=list)
    exclusions: Dict[int, set[int]] = field(default_factory=dict)
    fudge_lj: float = 0.5
    fudge_qq: float = 0.8333333333
    name: str = "system"

    # Cached vectorized arrays populated in __post_init__
    masses: FloatArray = field(init=False, repr=False)
    inv_masses: FloatArray = field(init=False, repr=False)
    charges: FloatArray = field(init=False, repr=False)
    sigmas: FloatArray = field(init=False, repr=False)
    epsilons: FloatArray = field(init=False, repr=False)
    alchemical_mask: NDArray[np.bool_] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.atoms:
            raise ValueError("Topology must contain at least one atom")
        n = len(self.atoms)
        self.masses = np.array([a.mass for a in self.atoms], dtype=np.float64)
        if np.any(self.masses <= 0.0):
            raise ValueError("All atomic masses must be strictly positive")
        self.inv_masses = 1.0 / self.masses
        self.charges = np.array([a.charge for a in self.atoms], dtype=np.float64)
        self.sigmas = np.array([a.sigma for a in self.atoms], dtype=np.float64)
        self.epsilons = np.array([a.epsilon for a in self.atoms], dtype=np.float64)
        self.alchemical_mask = np.array([a.is_alchemical for a in self.atoms], dtype=bool)
        if not self.exclusions:
            self.exclusions = {idx: {idx} for idx in range(n)}
            self._build_default_exclusions()

    def _build_default_exclusions(self) -> None:
        """Populate 1-2 and 1-3 exclusions and 1-4 nonbonded scaling pairs from bond graph."""
        n = len(self.atoms)
        adj: List[set[int]] = [set() for _ in range(n)]
        for b in self.bonds:
            adj[b.i].add(b.j)
            adj[b.j].add(b.i)
        for c in self.constraints:
            adj[c.i].add(c.j)
            adj[c.j].add(c.i)
        pairs_14_set: set[Tuple[int, int]] = set(self.pairs_14)
        for i in range(n):
            excl = {i}
            for j in adj[i]:
                excl.add(j)
                for k in adj[j]:
                    excl.add(k)
                    if not self.pairs_14:
                        for l_idx in adj[k]:
                            if l_idx != j and l_idx != i and l_idx not in adj[i]:
                                a, b_idx = (i, l_idx) if i < l_idx else (l_idx, i)
                                if b_idx not in excl:
                                    pairs_14_set.add((a, b_idx))
            self.exclusions[i] = excl
        # Ensure 1-4 pairs are not also marked as full 1-2/1-3 exclusions
        clean_14: List[Tuple[int, int]] = []
        for a, b_idx in sorted(pairs_14_set):
            if b_idx not in self.exclusions.get(a, set()):
                clean_14.append((a, b_idx))
        self.pairs_14 = clean_14

    @property
    def n_atoms(self) -> int:
        """Return total number of atoms in the system."""
        return len(self.atoms)

    @property
    def degrees_of_freedom(self) -> int:
        """Return mechanical degrees of freedom after holonomic constraints and COM removal."""
        dof = 3 * len(self.atoms) - len(self.constraints) - 3
        return max(1, dof)


@dataclass
class EnergyBreakdown:
    """Decomposed potential, kinetic, and thermodynamic state observables."""

    bond: float = 0.0
    angle: float = 0.0
    dihedral: float = 0.0
    improper: float = 0.0
    lj: float = 0.0
    lj_tail: float = 0.0
    coulomb_real: float = 0.0
    coulomb_recip: float = 0.0
    coulomb_self: float = 0.0
    restraint: float = 0.0
    kinetic: float = 0.0
    temperature: float = 0.0
    pressure_bar: float = 0.0
    virial_tensor: FloatArray = field(default_factory=lambda: np.zeros((3, 3), dtype=np.float64))
    dU_dlambda_vdw: float = 0.0
    dU_dlambda_elec: float = 0.0

    @property
    def potential(self) -> float:
        """Total potential energy in kJ/mol."""
        return (
            self.bond
            + self.angle
            + self.dihedral
            + self.improper
            + self.lj
            + self.lj_tail
            + self.coulomb_real
            + self.coulomb_recip
            + self.coulomb_self
            + self.restraint
        )

    @property
    def total(self) -> float:
        """Total mechanical energy K + U in kJ/mol."""
        return self.kinetic + self.potential


@dataclass
class MDState:
    """Instantaneous phase-space state and extended thermostat variables."""

    positions: FloatArray
    velocities: FloatArray
    forces: FloatArray
    box: SimulationBox
    step: int = 0
    time_ps: float = 0.0
    energy: EnergyBreakdown = field(default_factory=EnergyBreakdown)
    nhc_eta: FloatArray = field(default_factory=lambda: np.zeros(3, dtype=np.float64))
    nhc_v_eta: FloatArray = field(default_factory=lambda: np.zeros(3, dtype=np.float64))
    conserved_energy: float = 0.0
    constraint_rms_error: float = 0.0


@dataclass
class TrajectoryFrame:
    """Single saved simulation snapshot."""

    step: int
    time_ps: float
    positions: FloatArray
    velocities: Optional[FloatArray]
    box: SimulationBox
    energy: EnergyBreakdown
    conserved_energy: float


@dataclass
class Trajectory:
    """Collection of sampled trajectory frames with summary energy diagnostics."""

    frames: List[TrajectoryFrame]
    topology_name: str = "system"

    def positions_array(self) -> FloatArray:
        """Return trajectory coordinates stacked as ``(n_frames, n_atoms, 3)``."""
        return np.stack([f.positions for f in self.frames], axis=0)

    def times(self) -> FloatArray:
        """Return frame timestamps in ps."""
        return np.array([f.time_ps for f in self.frames], dtype=np.float64)

    def potential_energies(self) -> FloatArray:
        """Return potential energy series in kJ/mol."""
        return np.array([f.energy.potential for f in self.frames], dtype=np.float64)

    def kinetic_energies(self) -> FloatArray:
        """Return kinetic energy series in kJ/mol."""
        return np.array([f.energy.kinetic for f in self.frames], dtype=np.float64)

    def total_energies(self) -> FloatArray:
        """Return total energy series in kJ/mol."""
        return np.array([f.energy.total for f in self.frames], dtype=np.float64)

    def conserved_energies(self) -> FloatArray:
        """Return extended conserved Hamiltonian series in kJ/mol."""
        return np.array([f.conserved_energy for f in self.frames], dtype=np.float64)

    def temperatures(self) -> FloatArray:
        """Return instantaneous kinetic temperatures in K."""
        return np.array([f.energy.temperature for f in self.frames], dtype=np.float64)

    def pressures(self) -> FloatArray:
        """Return instantaneous pressures in bar."""
        return np.array([f.energy.pressure_bar for f in self.frames], dtype=np.float64)


@dataclass
class FreeEnergyEstimate:
    """Results of multistate alchemical free-energy estimation (FEP/TI/BAR/MBAR)."""

    delta_g_mbar: float
    sigma_mbar: float
    delta_g_bar: float
    sigma_bar: float
    delta_g_ti: float
    sigma_ti: float
    delta_g_fep_fwd: float
    delta_g_fep_rev: float
    hysteresis_kj_mol: float
    window_free_energies: FloatArray
    window_uncertainties: FloatArray
    overlap_matrix: FloatArray
    effective_sample_sizes: FloatArray
    lambda_schedule: List[AlchemicalLambda]


@dataclass
class PMFProfile:
    """Potential of Mean Force reconstructed via WHAM with bootstrap errors."""

    bin_centers: FloatArray
    pmf_kj_mol: FloatArray
    pmf_uncertainty_kj_mol: FloatArray
    probability_density: FloatArray
    window_free_energies: FloatArray
    iterations: int
    residual: float
    overlap_fractions: FloatArray


@dataclass
class MarkovModelResult:
    """TICA + reversible Markov State Model kinetic summary."""

    lag_steps: int
    lag_time_ps: float
    n_states: int
    transition_matrix: FloatArray
    stationary_distribution: FloatArray
    eigenvalues: FloatArray
    implied_timescales_ps: FloatArray
    ck_error: float
    mfpt_matrix_ps: FloatArray
    tica_eigenvalues: FloatArray
    state_assignments: IntArray


@dataclass
class DockingScoreBreakdown:
    """Vina-inspired empirical + GBSA desolvation scoring decomposition (kJ/mol)."""

    total_score: float
    gauss1: float
    gauss2: float
    repulsion: float
    hydrophobic: float
    hbond: float
    gbsa_desolvation: float
    torsion_entropy: float
    rmsd_from_initial: float
    optimized_positions: FloatArray


@dataclass
class CalibrationResult:
    """Outcome of bounded Nelder-Mead parameter calibration and Sobol sensitivity."""

    best_params: Dict[str, float]
    best_loss: float
    initial_loss: float
    evaluations: int
    history_losses: List[float]
    sobol_first_order: Dict[str, float]
    sobol_total_order: Dict[str, float]
