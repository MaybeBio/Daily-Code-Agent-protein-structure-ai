"""Force-field parameter calibration, Sobol sensitivity, and conservation audits.

Implements:
    * Bounded Nelder-Mead simplex optimization for Lennard-Jones / torsion
      force-field parameter fitting against target thermodynamic observables
    * Saltelli Sobol variance-based global sensitivity analysis (S_i and S_Ti)
    * Quantitative NVE energy-drift, LINCS constraint-RMS, and PME accuracy audit
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Sequence, Tuple
import numpy as np

from chemi_verlet.ewald import ParticleMeshEwald, exact_ewald_energy_forces
from chemi_verlet.forcefield import ForceField, ForceFieldConfig
from chemi_verlet.integrators import SimulationConfig, run_simulation
from chemi_verlet.topology import build_alkane_chain, build_solvated_ligand_box
from chemi_verlet.types import AtomSpec, CalibrationResult, FloatArray, SimulationBox, Topology


def bounded_nelder_mead(
    objective: Callable[[FloatArray], float],
    x0: FloatArray,
    bounds: Sequence[Tuple[float, float]],
    max_iter: int = 40,
    tol: float = 1e-5,
) -> Tuple[FloatArray, float, int, List[float]]:
    """Minimize ``objective(x)`` subject to box ``bounds`` via Nelder-Mead simplex."""
    dim = len(x0)
    lo = np.array([b[0] for b in bounds], dtype=np.float64)
    hi = np.array([b[1] for b in bounds], dtype=np.float64)
    x_init = np.clip(np.asarray(x0, dtype=np.float64), lo, hi)

    evals = 0

    def _eval(x: FloatArray) -> float:
        nonlocal evals
        xc = np.clip(x, lo, hi)
        evals += 1
        return float(objective(xc))

    # Build initial simplex with 12% parameter-range perturbations
    simplex = np.zeros((dim + 1, dim), dtype=np.float64)
    simplex[0] = x_init
    for i in range(dim):
        step = 0.12 * (hi[i] - lo[i])
        pt = x_init.copy()
        pt[i] = pt[i] + step if pt[i] + step <= hi[i] else pt[i] - step
        simplex[i + 1] = np.clip(pt, lo, hi)

    f_vals = np.array([_eval(pt) for pt in simplex], dtype=np.float64)
    history: List[float] = [float(np.min(f_vals))]

    alpha, gamma, rho, sigma = 1.0, 2.0, 0.5, 0.5
    for _ in range(max_iter):
        order = np.argsort(f_vals)
        simplex = simplex[order]
        f_vals = f_vals[order]
        history.append(float(f_vals[0]))

        if float(np.max(np.abs(f_vals - f_vals[0]))) < tol and float(np.max(np.ptp(simplex, axis=0))) < tol:
            break

        centroid = np.mean(simplex[:-1], axis=0)
        xr = np.clip(centroid + alpha * (centroid - simplex[-1]), lo, hi)
        fr = _eval(xr)

        if f_vals[0] <= fr < f_vals[-2]:
            simplex[-1] = xr
            f_vals[-1] = fr
        elif fr < f_vals[0]:
            xe = np.clip(centroid + gamma * (xr - centroid), lo, hi)
            fe = _eval(xe)
            if fe < fr:
                simplex[-1] = xe
                f_vals[-1] = fe
            else:
                simplex[-1] = xr
                f_vals[-1] = fr
        else:
            if fr < f_vals[-1]:
                xc = np.clip(centroid + rho * (xr - centroid), lo, hi)
                fc = _eval(xc)
                if fc <= fr:
                    simplex[-1] = xc
                    f_vals[-1] = fc
                    continue
            else:
                xc = np.clip(centroid - rho * (centroid - simplex[-1]), lo, hi)
                fc = _eval(xc)
                if fc < f_vals[-1]:
                    simplex[-1] = xc
                    f_vals[-1] = fc
                    continue
            # Shrink simplex toward best vertex
            for i in range(1, dim + 1):
                simplex[i] = np.clip(simplex[0] + sigma * (simplex[i] - simplex[0]), lo, hi)
                f_vals[i] = _eval(simplex[i])

    order = np.argsort(f_vals)
    return simplex[order[0]].copy(), float(f_vals[order[0]]), evals, history


def sobol_sensitivity_indices(
    model_fn: Callable[[FloatArray], float],
    param_names: Sequence[str],
    bounds: Sequence[Tuple[float, float]],
    n_samples: int = 64,
    seed: int = 42,
) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Compute Saltelli-Jansen first-order ``S_i`` and total-order ``S_Ti`` Sobol indices."""
    rng = np.random.default_rng(seed)
    d = len(param_names)
    lo = np.array([b[0] for b in bounds], dtype=np.float64)
    hi = np.array([b[1] for b in bounds], dtype=np.float64)

    # Independent uniform matrices A and B mapped to parameter bounds
    a_mat = lo[None, :] + (hi - lo)[None, :] * rng.uniform(size=(n_samples, d))
    b_mat = lo[None, :] + (hi - lo)[None, :] * rng.uniform(size=(n_samples, d))

    ya = np.array([model_fn(row) for row in a_mat], dtype=np.float64)
    yb = np.array([model_fn(row) for row in b_mat], dtype=np.float64)
    y_all = np.concatenate([ya, yb])
    var_y = float(np.var(y_all, ddof=0))
    if var_y < 1e-16:
        zeros = {name: 0.0 for name in param_names}
        return zeros, dict(zeros)

    s1: Dict[str, float] = {}
    st: Dict[str, float] = {}
    for idx, name in enumerate(param_names):
        ab_i = a_mat.copy()
        ab_i[:, idx] = b_mat[:, idx]
        y_abi = np.array([model_fn(row) for row in ab_i], dtype=np.float64)

        # Saltelli (2010) first-order & Jansen (1999) total-order estimators
        val_s1 = float(np.mean(yb * (y_abi - ya))) / var_y
        val_st = 0.5 * float(np.mean((ya - y_abi) ** 2)) / var_y
        s1[name] = float(np.clip(val_s1, 0.0, 1.0))
        st[name] = float(np.clip(val_st, 0.0, 1.0))

    return s1, st


def calibrate_lj_parameters(
    target_interaction_kj_mol: float = -22.0,
    target_equil_dist_nm: float = 0.365,
    max_iter: int = 30,
    seed: int = 42,
) -> CalibrationResult:
    """Calibrate nonbonded LJ (sigma, epsilon) against dimer binding energy & minimum distance."""
    box = SimulationBox.orthorhombic(3.0, 3.0, 3.0)

    def _dimer_observables(sigma_nm: float, eps_kj: float) -> Tuple[float, float]:
        atoms = [
            AtomSpec(0, "L1", "C", "LIG", 1, 12.0, 0.0, sigma_nm, eps_kj),
            AtomSpec(1, "L2", "C", "LIG", 2, 12.0, 0.0, sigma_nm, eps_kj),
        ]
        topo = Topology(atoms=atoms, name="lj_dimer")
        ff = ForceField(topo, ForceFieldConfig(cutoff=1.0, switch_distance=None, electrostatics="cutoff",
                                               dispersion_correction=False, shift_lj=False))
        r_grid = np.linspace(0.28, 0.55, 55)
        energies = np.empty_like(r_grid)
        for k, r in enumerate(r_grid):
            pos = np.array([[1.0, 1.0, 1.0], [1.0 + r, 1.0, 1.0]], dtype=np.float64)
            eb, _ = ff.evaluate(pos, box, force_rebuild=True)
            energies[k] = eb.lj
        min_idx = int(np.argmin(energies))
        return float(energies[min_idx]), float(r_grid[min_idx])

    def _loss(vec: FloatArray) -> float:
        e_min, r_min = _dimer_observables(float(vec[0]), float(vec[1]))
        # Multi-atom cluster scale factor (4-contact surrogate)
        e_eff = 4.0 * e_min
        return ((e_eff - target_interaction_kj_mol) / 5.0) ** 2 + ((r_min - target_equil_dist_nm) / 0.02) ** 2

    bounds = [(0.28, 0.42), (0.8, 10.0)]
    x0 = np.array([0.35, 3.5], dtype=np.float64)
    init_loss = _loss(x0)
    best_x, best_loss, evals, history = bounded_nelder_mead(_loss, x0, bounds, max_iter=max_iter)

    # Sobol sensitivity of calibrated objective around optimum
    s1, st = sobol_sensitivity_indices(
        _loss,
        param_names=["sigma_nm", "epsilon_kj_mol"],
        bounds=bounds,
        n_samples=32,
        seed=seed,
    )
    return CalibrationResult(
        best_params={"sigma_nm": float(best_x[0]), "epsilon_kj_mol": float(best_x[1])},
        best_loss=best_loss,
        initial_loss=init_loss,
        evaluations=evals,
        history_losses=history,
        sobol_first_order=s1,
        sobol_total_order=st,
    )


@dataclass(frozen=True)
class ConservationAuditReport:
    """Numerical accuracy & conservation diagnostics across core physics engines."""

    nve_relative_energy_drift: float
    lincs_constraint_rms_nm: float
    pme_vs_exact_energy_rel_err: float
    pme_vs_exact_force_rel_rmse: float
    nhc_conserved_drift_rel: float


def run_conservation_audit(seed: int = 42) -> ConservationAuditReport:
    """Execute quick end-to-end physics conservation and spectral accuracy verification."""
    # 1. NVE energy drift on unconstrained butane
    topo_alk, pos_alk = build_alkane_chain(4, constrain_bonds=False)
    box_alk = SimulationBox.orthorhombic(2.5, 2.5, 2.5)
    ff_alk = ForceField(topo_alk, ForceFieldConfig(cutoff=0.9, electrostatics="cutoff", dispersion_correction=False))
    _, traj_nve = run_simulation(
        topo_alk,
        ff_alk,
        pos_alk + 1.25,
        box_alk,
        config=SimulationConfig(dt_ps=0.001, n_steps=120, ensemble="nve", constraint_mode="none",
                                save_interval=5, seed=seed),
    )
    etot = traj_nve.total_energies()
    nve_drift = float(np.std(etot) / max(abs(float(np.mean(etot))), 1.0))

    # 2. LINCS constraint RMS on rigid solvated ethanol
    topo_sol, pos_sol, box_sol = build_solvated_ligand_box("CCO", box_length_nm=2.2, n_waters=10, seed=seed)
    ff_sol = ForceField(topo_sol, ForceFieldConfig(cutoff=0.9, electrostatics="pme"))
    final_lincs, traj_nhc = run_simulation(
        topo_sol,
        ff_sol,
        pos_sol,
        box_sol,
        config=SimulationConfig(dt_ps=0.002, n_steps=60, ensemble="nvt", thermostat="nhc",
                                constraint_mode="lincs", save_interval=5, seed=seed),
    )
    nhc_e = traj_nhc.conserved_energies()
    nhc_drift = float(np.std(nhc_e) / max(abs(float(np.mean(nhc_e))), 1.0))

    # 3. PME vs Exact Ewald comparison on neutral random ion cluster
    rng = np.random.default_rng(seed)
    box_ew = SimulationBox.orthorhombic(2.4, 2.4, 2.4)
    pos_ew = rng.uniform(0.2, 2.2, size=(10, 3))
    q_ew = np.array([1.0, -1.0] * 5, dtype=np.float64)
    pme = ParticleMeshEwald(cutoff=0.9, grid_spacing=0.07, spline_order=6, tolerance=1e-6)
    u_exact, f_exact = exact_ewald_energy_forces(pos_ew, q_ew, box_ew, pme.alpha, cutoff=0.9, k_max=11)

    # Evaluate PME total electrostatic energy + forces with dummy zero-LJ topology
    atoms_ew = [AtomSpec(i, f"I{i}", "C", "ION", i + 1, 12.0, float(q_ew[i]), 0.3, 0.0) for i in range(10)]
    topo_ew = Topology(atoms=atoms_ew, name="ewald_test")
    ff_ew = ForceField(
        topo_ew,
        ForceFieldConfig(
            cutoff=0.9,
            switch_distance=None,
            electrostatics="pme",
            pme_grid_spacing=0.07,
            pme_spline_order=6,
            pme_tolerance=1e-6,
            dispersion_correction=False,
        ),
    )
    eb_ew, f_pme = ff_ew.evaluate(pos_ew, box_ew, force_rebuild=True)
    u_pme = eb_ew.coulomb_real + eb_ew.coulomb_recip + eb_ew.coulomb_self
    e_rel = abs(u_pme - u_exact) / max(abs(u_exact), 1e-9)
    f_rmse = float(np.sqrt(np.mean((f_pme - f_exact) ** 2)) / max(float(np.sqrt(np.mean(f_exact ** 2))), 1e-9))

    return ConservationAuditReport(
        nve_relative_energy_drift=nve_drift,
        lincs_constraint_rms_nm=final_lincs.constraint_rms_error,
        pme_vs_exact_energy_rel_err=e_rel,
        pme_vs_exact_force_rel_rmse=f_rmse,
        nhc_conserved_drift_rel=nhc_drift,
    )
