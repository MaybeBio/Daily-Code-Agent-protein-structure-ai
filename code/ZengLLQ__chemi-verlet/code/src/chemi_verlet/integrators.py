"""Symplectic and stochastic molecular dynamics integrators, minimizers, and barostats.

Implements:
    * Steepest-descent / adaptive step-size energy minimization
    * Maxwell-Boltzmann velocity initialization with linear/angular momentum removal
    * Velocity-Verlet (NVE) with LINCS/SHAKE + RATTLE holonomic constraints
    * Langevin BAOAB (NVT) symmetric operator splitting
    * Nosé-Hoover Chain (NVT, M=3) Martyna-Klein-Tuckerman symmetric Trotter integrator
    * Berendsen and Monte-Carlo isotropic barostats (NPT)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple, Union
import numpy as np

from chemi_verlet.constraints import LincsSolver, ShakeSolver, constraint_rms_deviation
from chemi_verlet.forcefield import ForceField
from chemi_verlet.pbc import wrap_positions
from chemi_verlet.types import (
    AlchemicalLambda,
    BAR_TO_KJ_MOL_NM3,
    EnergyBreakdown,
    FloatArray,
    KB_KJ_MOL_K,
    KJ_MOL_NM3_TO_BAR,
    MDState,
    SimulationBox,
    Topology,
    Trajectory,
    TrajectoryFrame,
)

ConstraintSolver = Union[LincsSolver, ShakeSolver]


def compute_kinetic_and_temperature(
    velocities: FloatArray,
    topology: Topology,
) -> Tuple[float, float, FloatArray]:
    """Return ``(kinetic_energy_kJ_mol, temperature_K, kinetic_tensor_2K)``."""
    m = topology.masses
    mv2 = m[:, None] * velocities * velocities
    kinetic = 0.5 * float(np.sum(mv2))
    # Kinetic tensor sum_i m_i v_i (x) v_i
    kin_tensor = (m[:, None] * velocities).T @ velocities
    temp = 2.0 * kinetic / (topology.degrees_of_freedom * KB_KJ_MOL_K)
    return kinetic, temp, kin_tensor


def compute_instantaneous_pressure(
    kin_tensor: FloatArray,
    virial_tensor: FloatArray,
    volume: float,
) -> float:
    """Compute scalar pressure (bar) from ``P = Tr(K_2 + Xi) / (3 V)``."""
    # Clausius virial: P = (2*K + Tr(virial)) / (3 * V), where virial = sum_{i<j} r_ij (x) F_j
    p_internal = (float(np.trace(kin_tensor)) + float(np.trace(virial_tensor))) / (3.0 * max(volume, 1e-12))
    return p_internal * KJ_MOL_NM3_TO_BAR


def remove_com_motion(
    positions: FloatArray,
    velocities: FloatArray,
    masses: FloatArray,
    remove_angular: bool = True,
) -> FloatArray:
    """Zero center-of-mass linear velocity and optionally net angular momentum."""
    v = velocities.copy()
    total_mass = float(np.sum(masses))
    v_com = np.sum(masses[:, None] * v, axis=0) / total_mass
    v -= v_com[None, :]

    if remove_angular and positions.shape[0] > 2:
        r_com = np.sum(masses[:, None] * positions, axis=0) / total_mass
        r_rel = positions - r_com[None, :]
        ang_mom = np.sum(masses[:, None] * np.cross(r_rel, v), axis=0)
        # Moment of inertia tensor I = sum m (|r|^2 I_3 - r (x) r)
        r_sq = np.sum(r_rel * r_rel, axis=1)
        inertia = float(np.sum(masses * r_sq)) * np.eye(3) - (masses[:, None] * r_rel).T @ r_rel
        eigvals = np.linalg.eigvalsh(inertia)
        if np.min(eigvals) > 1e-8:
            omega = np.linalg.solve(inertia, ang_mom)
            v -= np.cross(omega[None, :], r_rel)
    return v


def initialize_velocities(
    topology: Topology,
    positions: FloatArray,
    temperature_k: float,
    box: SimulationBox,
    seed: int = 42,
    constraint_solver: Optional[ConstraintSolver] = None,
) -> FloatArray:
    """Sample Maxwell-Boltzmann velocities rescaled to exact target kinetic temperature."""
    rng = np.random.default_rng(seed)
    sigma_v = np.sqrt(KB_KJ_MOL_K * temperature_k / topology.masses)
    vel = rng.normal(0.0, 1.0, size=(topology.n_atoms, 3)) * sigma_v[:, None]
    vel = remove_com_motion(positions, vel, topology.masses, remove_angular=False)
    if constraint_solver is not None:
        vel = constraint_solver.constrain_velocities(positions, vel, box)
    kinetic, temp, _ = compute_kinetic_and_temperature(vel, topology)
    if temp > 1e-9 and temperature_k > 0.0:
        vel *= np.sqrt(temperature_k / temp)
    return vel


def minimize_energy(
    force_field: ForceField,
    positions: FloatArray,
    box: SimulationBox,
    max_steps: int = 250,
    force_tol: float = 50.0,
    initial_step_nm: float = 0.005,
    alchemical: Optional[AlchemicalLambda] = None,
    constraint_solver: Optional[ConstraintSolver] = None,
) -> Tuple[FloatArray, EnergyBreakdown]:
    """Adaptive steepest-descent energy minimizer with backtracking step scaling."""
    pos = positions.copy()
    step_size = float(initial_step_nm)
    energy, forces = force_field.evaluate(pos, box, alchemical=alchemical, force_rebuild=True)

    for _ in range(max_steps):
        f_norms = np.linalg.norm(forces, axis=1)
        max_f = float(np.max(f_norms))
        if max_f <= force_tol or max_f < 1e-12:
            break
        trial_pos = pos + step_size * (forces / max_f)
        if constraint_solver is not None:
            trial_pos, _ = constraint_solver.constrain_positions(pos, trial_pos, box, dt=0.001)
        trial_energy, trial_forces = force_field.evaluate(trial_pos, box, alchemical=alchemical)
        if trial_energy.potential <= energy.potential:
            pos = trial_pos
            energy = trial_energy
            forces = trial_forces
            step_size = min(step_size * 1.2, 0.025)
        else:
            step_size *= 0.5
            if step_size < 1e-7:
                break
    return pos, energy


@dataclass
class SimulationConfig:
    """Parameters controlling MD integration, thermostatting, and barostatting."""

    dt_ps: float = 0.002
    n_steps: int = 500
    ensemble: str = "nvt"  # "nve", "nvt", "npt"
    thermostat: str = "baoab"  # "baoab" or "nhc"
    barostat: str = "mc"  # "mc" or "berendsen"
    temperature_k: float = 300.0
    pressure_bar: float = 1.0
    friction_ps_inv: float = 1.0
    tau_t_ps: float = 0.2
    tau_p_ps: float = 1.0
    compressibility_bar_inv: float = 4.5e-5
    mc_barostat_freq: int = 10
    mc_max_volume_scale: float = 0.02
    constraint_mode: str = "lincs"  # "lincs", "shake", or "none"
    save_interval: int = 5
    com_removal_freq: int = 50
    seed: int = 42


def _make_constraint_solver(topology: Topology, mode: str) -> Optional[ConstraintSolver]:
    if mode == "none" or not topology.constraints:
        return None
    if mode == "lincs":
        return LincsSolver(topology)
    if mode == "shake":
        return ShakeSolver(topology)
    raise ValueError(f"Unsupported constraint mode: {mode}")


def _update_state_observables(
    state: MDState,
    topology: Topology,
    constraint_virial: Optional[FloatArray] = None,
) -> None:
    """Populate kinetic energy, temperature, pressure, and constraint error on ``state``."""
    kin, temp, kin_tensor = compute_kinetic_and_temperature(state.velocities, topology)
    if constraint_virial is not None:
        state.energy.virial_tensor = state.energy.virial_tensor + constraint_virial
    state.energy.kinetic = kin
    state.energy.temperature = temp
    state.energy.pressure_bar = compute_instantaneous_pressure(
        kin_tensor, state.energy.virial_tensor, state.box.volume
    )
    state.constraint_rms_error = constraint_rms_deviation(state.positions, topology.constraints, state.box)


class VelocityVerletIntegrator:
    """Symplectic NVE Velocity-Verlet integrator with LINCS/SHAKE + RATTLE."""

    def __init__(
        self,
        topology: Topology,
        force_field: ForceField,
        dt_ps: float = 0.002,
        constraint_mode: str = "lincs",
    ) -> None:
        self.topology = topology
        self.force_field = force_field
        self.dt = float(dt_ps)
        self.solver = _make_constraint_solver(topology, constraint_mode)

    def step(
        self,
        state: MDState,
        alchemical: Optional[AlchemicalLambda] = None,
    ) -> MDState:
        """Advance state by one symplectic Velocity-Verlet step."""
        inv_m = self.topology.inv_masses[:, None]
        dt = self.dt
        r_old = state.positions

        v_half = state.velocities + 0.5 * dt * state.forces * inv_m
        r_new = r_old + dt * v_half

        c_virial = np.zeros((3, 3), dtype=np.float64)
        if self.solver is not None:
            r_new, c_virial = self.solver.constrain_positions(r_old, r_new, state.box, dt)
            v_half = (r_new - r_old) / dt

        energy, forces_new = self.force_field.evaluate(r_new, state.box, alchemical=alchemical)
        v_new = v_half + 0.5 * dt * forces_new * inv_m
        if self.solver is not None:
            v_new = self.solver.constrain_velocities(r_new, v_new, state.box)

        state.positions = r_new
        state.velocities = v_new
        state.forces = forces_new
        state.energy = energy
        state.step += 1
        state.time_ps += dt
        _update_state_observables(state, self.topology, c_virial)
        state.conserved_energy = state.energy.total
        return state


class LangevinBAOABIntegrator:
    """Canonical NVT Langevin integrator using symmetric B-A-O-A-B operator splitting."""

    def __init__(
        self,
        topology: Topology,
        force_field: ForceField,
        dt_ps: float = 0.002,
        temperature_k: float = 300.0,
        friction_ps_inv: float = 1.0,
        constraint_mode: str = "lincs",
        seed: int = 42,
    ) -> None:
        self.topology = topology
        self.force_field = force_field
        self.dt = float(dt_ps)
        self.temperature_k = float(temperature_k)
        self.gamma = float(friction_ps_inv)
        self.solver = _make_constraint_solver(topology, constraint_mode)
        self.rng = np.random.default_rng(seed)

    def step(
        self,
        state: MDState,
        alchemical: Optional[AlchemicalLambda] = None,
    ) -> MDState:
        """Advance state by one BAOAB Langevin step."""
        dt = self.dt
        inv_m = self.topology.inv_masses[:, None]
        r_old = state.positions

        # B: half-step velocity kick
        v = state.velocities + 0.5 * dt * state.forces * inv_m
        # A: half-step position drift
        r = r_old + 0.5 * dt * v
        if self.solver is not None:
            r, _ = self.solver.constrain_positions(r_old, r, state.box, 0.5 * dt)
            v = (r - r_old) / (0.5 * dt)

        # O: exact Ornstein-Uhlenbeck thermostat step
        c1 = float(np.exp(-self.gamma * dt))
        c2 = np.sqrt(KB_KJ_MOL_K * self.temperature_k * (1.0 - c1 * c1) * inv_m)
        v = c1 * v + c2 * self.rng.normal(0.0, 1.0, size=v.shape)
        if self.solver is not None:
            v = self.solver.constrain_velocities(r, v, state.box)

        # A: second half-step position drift
        r_mid = r
        r_new = r_mid + 0.5 * dt * v
        c_virial = np.zeros((3, 3), dtype=np.float64)
        if self.solver is not None:
            r_new, c_virial = self.solver.constrain_positions(r_mid, r_new, state.box, 0.5 * dt)
            v = (r_new - r_mid) / (0.5 * dt)

        # Force evaluation + B: second half-step velocity kick
        energy, forces_new = self.force_field.evaluate(r_new, state.box, alchemical=alchemical)
        v = v + 0.5 * dt * forces_new * inv_m
        if self.solver is not None:
            v = self.solver.constrain_velocities(r_new, v, state.box)

        state.positions = r_new
        state.velocities = v
        state.forces = forces_new
        state.energy = energy
        state.step += 1
        state.time_ps += dt
        _update_state_observables(state, self.topology, c_virial * 0.5)
        state.conserved_energy = state.energy.total
        return state


class NoseHooverChainIntegrator:
    """Deterministic NVT Nosé-Hoover Chain (M=3) via Martyna-Klein-Tuckerman splitting."""

    def __init__(
        self,
        topology: Topology,
        force_field: ForceField,
        dt_ps: float = 0.002,
        temperature_k: float = 300.0,
        tau_t_ps: float = 0.2,
        chain_length: int = 3,
        constraint_mode: str = "lincs",
    ) -> None:
        self.topology = topology
        self.force_field = force_field
        self.dt = float(dt_ps)
        self.temperature_k = float(temperature_k)
        self.tau_t = float(tau_t_ps)
        self.chain_length = max(2, int(chain_length))
        self.solver = _make_constraint_solver(topology, constraint_mode)
        self.dof = topology.degrees_of_freedom
        kbt = KB_KJ_MOL_K * self.temperature_k
        # Martyna-Tuckerman thermostat masses Q_1 = N_f * kBT * tau^2, Q_k = kBT * tau^2
        q_masses = np.full(self.chain_length, max(kbt * self.tau_t * self.tau_t, 1e-6), dtype=np.float64)
        q_masses[0] = max(self.dof * kbt * self.tau_t * self.tau_t, 1e-6)
        self.q_masses = q_masses

    def _apply_nhc_half_step(self, state: MDState, velocities: FloatArray, half_dt: float) -> FloatArray:
        """Apply half-step symmetric Nosé-Hoover chain Liouville propagator."""
        v = velocities.copy()
        kbt = KB_KJ_MOL_K * self.temperature_k
        m_len = self.chain_length
        eta = state.nhc_eta
        v_eta = state.nhc_v_eta
        q = self.q_masses

        # Multi-timestep Yoshida-Suzuki 3-step sub-stepping for stiff thermostat chains
        n_ys = 3
        sub_dt = half_dt / n_ys
        for _ in range(n_ys):
            kin_2 = float(np.sum(self.topology.masses[:, None] * v * v))
            g = np.zeros(m_len, dtype=np.float64)
            g[0] = (kin_2 - self.dof * kbt) / q[0]
            for k in range(1, m_len):
                g[k] = (q[k - 1] * v_eta[k - 1] * v_eta[k - 1] - kbt) / q[k]

            # Update from top of chain down
            v_eta[m_len - 1] += 0.5 * sub_dt * g[m_len - 1]
            for k in range(m_len - 2, -1, -1):
                scale = float(np.exp(-0.25 * sub_dt * v_eta[k + 1]))
                v_eta[k] = v_eta[k] * scale + 0.5 * sub_dt * g[k] * scale
                v_eta[k] *= scale

            # Scale particle velocities and propagate eta
            v *= float(np.exp(-sub_dt * v_eta[0]))
            eta += sub_dt * v_eta

            # Recompute g[0] after velocity scaling and update upward
            kin_2 = float(np.sum(self.topology.masses[:, None] * v * v))
            g[0] = (kin_2 - self.dof * kbt) / q[0]
            for k in range(m_len - 1):
                scale = float(np.exp(-0.25 * sub_dt * v_eta[k + 1]))
                v_eta[k] = v_eta[k] * scale + 0.5 * sub_dt * g[k] * scale
                v_eta[k] *= scale
                g[k + 1] = (q[k] * v_eta[k] * v_eta[k] - kbt) / q[k + 1]
            v_eta[m_len - 1] += 0.5 * sub_dt * g[m_len - 1]

        return v

    def conserved_hamiltonian(self, state: MDState) -> float:
        """Return extended conserved Nosé-Hoover Chain Hamiltonian (kJ/mol)."""
        kbt = KB_KJ_MOL_K * self.temperature_k
        nhc_ke = 0.5 * float(np.sum(self.q_masses * state.nhc_v_eta * state.nhc_v_eta))
        nhc_pe = kbt * (self.dof * float(state.nhc_eta[0]) + float(np.sum(state.nhc_eta[1:])))
        return state.energy.total + nhc_ke + nhc_pe

    def step(
        self,
        state: MDState,
        alchemical: Optional[AlchemicalLambda] = None,
    ) -> MDState:
        """Advance state by one MKT symmetric Nosé-Hoover Chain step."""
        if state.nhc_eta.shape[0] != self.chain_length:
            state.nhc_eta = np.zeros(self.chain_length, dtype=np.float64)
            state.nhc_v_eta = np.zeros(self.chain_length, dtype=np.float64)

        dt = self.dt
        inv_m = self.topology.inv_masses[:, None]
        v = self._apply_nhc_half_step(state, state.velocities, 0.5 * dt)

        r_old = state.positions
        v = v + 0.5 * dt * state.forces * inv_m
        r_new = r_old + dt * v
        c_virial = np.zeros((3, 3), dtype=np.float64)
        if self.solver is not None:
            r_new, c_virial = self.solver.constrain_positions(r_old, r_new, state.box, dt)
            v = (r_new - r_old) / dt

        energy, forces_new = self.force_field.evaluate(r_new, state.box, alchemical=alchemical)
        v = v + 0.5 * dt * forces_new * inv_m
        if self.solver is not None:
            v = self.solver.constrain_velocities(r_new, v, state.box)
        v = self._apply_nhc_half_step(state, v, 0.5 * dt)

        state.positions = r_new
        state.velocities = v
        state.forces = forces_new
        state.energy = energy
        state.step += 1
        state.time_ps += dt
        _update_state_observables(state, self.topology, c_virial)
        state.conserved_energy = self.conserved_hamiltonian(state)
        return state


class MonteCarloBarostat:
    """Isotropic Monte-Carlo barostat sampling exact NPT volume fluctuations."""

    def __init__(
        self,
        topology: Topology,
        force_field: ForceField,
        pressure_bar: float = 1.0,
        temperature_k: float = 300.0,
        max_volume_scale: float = 0.02,
        seed: int = 42,
    ) -> None:
        self.topology = topology
        self.force_field = force_field
        self.target_pressure_bar = float(pressure_bar)
        self.temperature_k = float(temperature_k)
        self.max_volume_scale = float(max_volume_scale)
        self.rng = np.random.default_rng(seed)
        self.accepted: int = 0
        self.attempted: int = 0

    def attempt_volume_move(
        self,
        state: MDState,
        alchemical: Optional[AlchemicalLambda] = None,
    ) -> bool:
        """Propose an isotropic volume scaling move and accept via Metropolis criterion."""
        self.attempted += 1
        v_old = state.box.volume
        dv = self.rng.uniform(-self.max_volume_scale, self.max_volume_scale) * v_old
        v_new = max(v_old + dv, 0.1 * v_old)
        scale = (v_new / v_old) ** (1.0 / 3.0)
        new_box = state.box.scaled(scale)

        # Scale molecular/atomic fractional coordinates uniformly; keep rigid constraints exact by scaling COMs
        # For general atomistic topologies without rigid solvent COM tracking, scale atomic coordinates and re-project
        new_pos = state.positions * scale
        u_old = state.energy.potential
        new_energy, new_forces = self.force_field.evaluate(new_pos, new_box, alchemical=alchemical, force_rebuild=True)
        u_new = new_energy.potential

        p_ext = self.target_pressure_bar * BAR_TO_KJ_MOL_NM3
        kbt = KB_KJ_MOL_K * self.temperature_k
        n_particles = self.topology.n_atoms
        delta_w = (u_new - u_old) + p_ext * (v_new - v_old) - n_particles * kbt * float(np.log(v_new / v_old))

        if delta_w <= 0.0 or self.rng.uniform() < float(np.exp(-delta_w / max(kbt, 1e-9))):
            state.box = new_box
            state.positions = new_pos
            state.energy = new_energy
            state.forces = new_forces
            _update_state_observables(state, self.topology)
            self.accepted += 1
            return True
        return False


def apply_berendsen_barostat(
    state: MDState,
    topology: Topology,
    force_field: ForceField,
    dt_ps: float,
    target_pressure_bar: float,
    tau_p_ps: float = 1.0,
    compressibility_bar_inv: float = 4.5e-5,
    alchemical: Optional[AlchemicalLambda] = None,
) -> None:
    """Apply weak-coupling Berendsen isotropic box & coordinate rescaling."""
    dp = target_pressure_bar - state.energy.pressure_bar
    mu = (1.0 - (dt_ps / max(tau_p_ps, 1e-6)) * compressibility_bar_inv * dp) ** (1.0 / 3.0)
    mu = float(np.clip(mu, 0.99, 1.01))
    state.box = state.box.scaled(mu)
    state.positions = state.positions * mu
    energy, forces = force_field.evaluate(state.positions, state.box, alchemical=alchemical, force_rebuild=True)
    state.energy = energy
    state.forces = forces
    _update_state_observables(state, topology)


def create_initial_state(
    topology: Topology,
    force_field: ForceField,
    positions: FloatArray,
    box: SimulationBox,
    temperature_k: float = 300.0,
    minimize: bool = True,
    constraint_mode: str = "lincs",
    alchemical: Optional[AlchemicalLambda] = None,
    seed: int = 42,
) -> MDState:
    """Minimize clashes, initialize Maxwell-Boltzmann velocities, and assemble :class:`MDState`."""
    solver = _make_constraint_solver(topology, constraint_mode)
    pos = positions.copy()
    if minimize:
        pos, _ = minimize_energy(
            force_field,
            pos,
            box,
            alchemical=alchemical,
            constraint_solver=solver,
        )
    pos = wrap_positions(pos, box)
    vel = initialize_velocities(topology, pos, temperature_k, box, seed=seed, constraint_solver=solver)
    energy, forces = force_field.evaluate(pos, box, alchemical=alchemical, force_rebuild=True)
    state = MDState(
        positions=pos,
        velocities=vel,
        forces=forces,
        box=box,
        step=0,
        time_ps=0.0,
        energy=energy,
    )
    _update_state_observables(state, topology)
    state.conserved_energy = state.energy.total
    return state


def run_simulation(
    topology: Topology,
    force_field: ForceField,
    initial_positions: FloatArray,
    box: SimulationBox,
    config: Optional[SimulationConfig] = None,
    alchemical: Optional[AlchemicalLambda] = None,
    minimize: bool = True,
) -> Tuple[MDState, Trajectory]:
    """Execute a complete NVE, NVT, or NPT molecular dynamics simulation."""
    cfg = config or SimulationConfig()
    state = create_initial_state(
        topology=topology,
        force_field=force_field,
        positions=initial_positions,
        box=box,
        temperature_k=cfg.temperature_k,
        minimize=minimize,
        constraint_mode=cfg.constraint_mode,
        alchemical=alchemical,
        seed=cfg.seed,
    )

    integrator: Union[VelocityVerletIntegrator, LangevinBAOABIntegrator, NoseHooverChainIntegrator]
    if cfg.ensemble == "nve":
        integrator = VelocityVerletIntegrator(topology, force_field, cfg.dt_ps, cfg.constraint_mode)
    elif cfg.ensemble in ("nvt", "npt"):
        if cfg.thermostat == "nhc":
            integrator = NoseHooverChainIntegrator(
                topology, force_field, cfg.dt_ps, cfg.temperature_k, cfg.tau_t_ps, constraint_mode=cfg.constraint_mode
            )
        else:
            integrator = LangevinBAOABIntegrator(
                topology,
                force_field,
                cfg.dt_ps,
                cfg.temperature_k,
                cfg.friction_ps_inv,
                cfg.constraint_mode,
                seed=cfg.seed + 101,
            )
    else:
        raise ValueError(f"Unsupported ensemble '{cfg.ensemble}' (use nve, nvt, or npt)")

    mc_barostat: Optional[MonteCarloBarostat] = None
    if cfg.ensemble == "npt" and cfg.barostat == "mc":
        mc_barostat = MonteCarloBarostat(
            topology,
            force_field,
            pressure_bar=cfg.pressure_bar,
            temperature_k=cfg.temperature_k,
            max_volume_scale=cfg.mc_max_volume_scale,
            seed=cfg.seed + 202,
        )

    frames = [
        TrajectoryFrame(
            step=state.step,
            time_ps=state.time_ps,
            positions=state.positions.copy(),
            velocities=state.velocities.copy(),
            box=SimulationBox(state.box.vectors),
            energy=state.energy,
            conserved_energy=state.conserved_energy,
        )
    ]

    for step_idx in range(1, cfg.n_steps + 1):
        state = integrator.step(state, alchemical=alchemical)
        if cfg.ensemble == "npt":
            if mc_barostat is not None and (step_idx % cfg.mc_barostat_freq == 0):
                mc_barostat.attempt_volume_move(state, alchemical=alchemical)
            elif cfg.barostat == "berendsen":
                apply_berendsen_barostat(
                    state,
                    topology,
                    force_field,
                    cfg.dt_ps,
                    cfg.pressure_bar,
                    cfg.tau_p_ps,
                    cfg.compressibility_bar_inv,
                    alchemical=alchemical,
                )
        if cfg.com_removal_freq > 0 and (step_idx % cfg.com_removal_freq == 0):
            state.velocities = remove_com_motion(
                state.positions, state.velocities, topology.masses, remove_angular=False
            )
        if step_idx % max(1, cfg.save_interval) == 0 or step_idx == cfg.n_steps:
            frames.append(
                TrajectoryFrame(
                    step=state.step,
                    time_ps=state.time_ps,
                    positions=state.positions.copy(),
                    velocities=state.velocities.copy(),
                    box=SimulationBox(state.box.vectors),
                    energy=state.energy,
                    conserved_energy=state.conserved_energy,
                )
            )

    return state, Trajectory(frames=frames, topology_name=topology.name)
