"""Trajectory observables, structural diagnostics, TICA, and reversible Markov State Models.

Implements:
    * Kabsch optimal SVD structural superposition RMSD and per-atom RMSF
    * Periodic Radial Distribution Function g(r) with shell density normalization
    * Radius of gyration, dihedral angle time series, and hydrogen-bond occupancy
    * Time-Lagged Independent Component Analysis (TICA)
    * Reversible Transition Matrix Markov State Model (MSM) with MLE symmetrization,
      implied timescales, Chapman-Kolmogorov validation, and MFPT kinetic matrices
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple
import numpy as np
from scipy.linalg import eigh

from chemi_verlet.pbc import minimum_image_displacement
from chemi_verlet.types import FloatArray, IntArray, MarkovModelResult, SimulationBox, Topology, Trajectory


def kabsch_rmsd(coords: FloatArray, reference: FloatArray) -> float:
    """Compute minimum heavy-atom RMSD (nm) via Kabsch SVD optimal rigid alignment."""
    p = np.asarray(coords, dtype=np.float64)
    q = np.asarray(reference, dtype=np.float64)
    if p.shape != q.shape or p.ndim != 2 or p.shape[1] != 3:
        raise ValueError("Kabsch RMSD requires two coordinate arrays of shape (N, 3)")
    p_c = p - np.mean(p, axis=0)
    q_c = q - np.mean(q, axis=0)
    cov = p_c.T @ q_c
    u_mat, _, vt_mat = np.linalg.svd(cov)
    d_sign = 1.0 if np.linalg.det(vt_mat.T @ u_mat.T) >= 0.0 else -1.0
    diag = np.diag([1.0, 1.0, d_sign])
    rot = vt_mat.T @ diag @ u_mat.T
    p_aligned = p_c @ rot.T
    diff = p_aligned - q_c
    return float(np.sqrt(np.mean(np.sum(diff * diff, axis=1))))


def compute_rmsf(trajectory: Trajectory, atom_indices: Optional[Sequence[int]] = None) -> FloatArray:
    """Compute per-atom Root-Mean-Square Fluctuation (nm) after Kabsch alignment."""
    pos_all = trajectory.positions_array()
    if atom_indices is not None:
        pos_all = pos_all[:, np.asarray(atom_indices, dtype=np.int64), :]
    n_frames, n_atoms, _ = pos_all.shape
    if n_frames == 0:
        return np.empty(0, dtype=np.float64)
    ref = pos_all[0]
    aligned = np.zeros_like(pos_all)
    for t in range(n_frames):
        p_c = pos_all[t] - np.mean(pos_all[t], axis=0)
        q_c = ref - np.mean(ref, axis=0)
        u_m, _, vt_m = np.linalg.svd(p_c.T @ q_c)
        d_sign = 1.0 if np.linalg.det(vt_m.T @ u_m.T) >= 0.0 else -1.0
        rot = vt_m.T @ np.diag([1.0, 1.0, d_sign]) @ u_m.T
        aligned[t] = p_c @ rot.T + np.mean(ref, axis=0)
    mean_pos = np.mean(aligned, axis=0)
    sq_dev = np.sum((aligned - mean_pos[None, :, :]) ** 2, axis=2)
    return np.asarray(np.sqrt(np.mean(sq_dev, axis=0)), dtype=np.float64)


def compute_radius_of_gyration(positions: FloatArray, masses: FloatArray) -> float:
    """Compute mass-weighted radius of gyration R_g (nm)."""
    total_m = float(np.sum(masses))
    com = np.sum(positions * masses[:, None], axis=0) / max(total_m, 1e-12)
    r_sq = np.sum((positions - com[None, :]) ** 2, axis=1)
    return float(np.sqrt(np.sum(masses * r_sq) / max(total_m, 1e-12)))


def compute_dihedral_angle(
    r_i: FloatArray,
    r_j: FloatArray,
    r_k: FloatArray,
    r_l: FloatArray,
    box: Optional[SimulationBox] = None,
) -> float:
    """Compute signed dihedral angle in [-pi, pi] radians between four points."""
    b1 = r_j - r_i
    b2 = r_k - r_j
    b3 = r_l - r_k
    if box is not None:
        b1 = minimum_image_displacement(b1, box)
        b2 = minimum_image_displacement(b2, box)
        b3 = minimum_image_displacement(b3, box)
    n1 = np.cross(b1, b2)
    n2 = np.cross(b2, b3)
    b2_norm = max(float(np.linalg.norm(b2)), 1e-12)
    m1 = np.cross(n1, b2 / b2_norm)
    x = float(np.dot(n1, n2))
    y = float(np.dot(m1, n2))
    return float(np.arctan2(y, x))


def compute_rdf(
    trajectory: Trajectory,
    group_a: Sequence[int],
    group_b: Sequence[int],
    r_max: float = 1.0,
    n_bins: int = 50,
) -> Tuple[FloatArray, FloatArray]:
    """Compute periodic Radial Distribution Function ``g(r)`` between two atom groups."""
    ia = np.asarray(group_a, dtype=np.int64)
    ib = np.asarray(group_b, dtype=np.int64)
    same_group = np.array_equal(ia, ib)
    edges = np.linspace(0.0, r_max, n_bins + 1)
    centers = 0.5 * (edges[:-1] + edges[1:])
    hist = np.zeros(n_bins, dtype=np.float64)
    norm_factor = 0.0

    for frame in trajectory.frames:
        pos = frame.positions
        dr = minimum_image_displacement(pos[None, ib, :] - pos[ia, None, :], frame.box)
        dists = np.linalg.norm(dr, axis=-1)
        if same_group:
            iu, ju = np.triu_indices(ia.size, k=1)
            d_vals = dists[iu, ju]
            n_pairs = ia.size * (ia.size - 1) / 2.0
        else:
            d_vals = dists.ravel()
            n_pairs = float(ia.size * ib.size)
        cnt, _ = np.histogram(d_vals, bins=edges)
        hist += cnt.astype(np.float64)
        # Ideal gas pair density per unit volume = n_pairs / V
        norm_factor += n_pairs / max(frame.box.volume, 1e-12)

    shell_vols = (4.0 / 3.0) * np.pi * (edges[1:] ** 3 - edges[:-1] ** 3)
    denom = np.maximum(norm_factor * shell_vols, 1e-15)
    g_r = hist / denom
    return centers, g_r


def detect_hydrogen_bonds(
    topology: Topology,
    positions: FloatArray,
    box: SimulationBox,
    donor_acceptor_cutoff_nm: float = 0.35,
    min_angle_deg: float = 135.0,
) -> List[Tuple[int, int, int, float, float]]:
    """Detect geometric D-H...A hydrogen bonds returning ``(donor, H, acceptor, d_DA, angle_deg)``."""
    # Map donor heavy atoms to attached H atoms
    donor_h: List[Tuple[int, int]] = []
    bond_adj: dict[int, List[int]] = {}
    for b in topology.bonds:
        bond_adj.setdefault(b.i, []).append(b.j)
        bond_adj.setdefault(b.j, []).append(b.i)
    for c in topology.constraints:
        bond_adj.setdefault(c.i, []).append(c.j)
        bond_adj.setdefault(c.j, []).append(c.i)

    for atom in topology.atoms:
        if atom.is_donor:
            for nbr in bond_adj.get(atom.index, []):
                if topology.atoms[nbr].element == "H":
                    donor_h.append((atom.index, nbr))

    acceptors = [a.index for a in topology.atoms if a.is_acceptor]
    hits: List[Tuple[int, int, int, float, float]] = []
    for d_idx, h_idx in donor_h:
        for a_idx in acceptors:
            if a_idx == d_idx or a_idx == h_idx:
                continue
            v_da = minimum_image_displacement(positions[a_idx] - positions[d_idx], box)
            d_da = float(np.linalg.norm(v_da))
            if d_da > donor_acceptor_cutoff_nm:
                continue
            v_hd = minimum_image_displacement(positions[d_idx] - positions[h_idx], box)
            v_ha = minimum_image_displacement(positions[a_idx] - positions[h_idx], box)
            n_hd = max(float(np.linalg.norm(v_hd)), 1e-12)
            n_ha = max(float(np.linalg.norm(v_ha)), 1e-12)
            cos_a = float(np.clip(np.dot(v_hd, v_ha) / (n_hd * n_ha), -1.0, 1.0))
            ang_deg = float(np.rad2deg(np.arccos(cos_a)))
            if ang_deg >= min_angle_deg:
                hits.append((d_idx, h_idx, a_idx, d_da, ang_deg))
    return hits


def compute_tica(
    feature_trajectories: Sequence[FloatArray],
    lag_steps: int = 5,
    n_components: int = 2,
    reg_eps: float = 1e-6,
) -> Tuple[List[FloatArray], FloatArray, FloatArray]:
    """Compute Time-Lagged Independent Component Analysis (TICA) projections.

    Solves ``C(tau) v = lambda C(0) v`` for maximally autocorrelated slow modes.
    Returns ``(projected_trajs, eigenvalues, eigenvectors)``.
    """
    trajs = [np.asarray(t, dtype=np.float64) for t in feature_trajectories]
    if not trajs:
        raise ValueError("TICA requires at least one feature trajectory")
    n_feat = trajs[0].shape[1]
    mean_vec = np.mean(np.vstack(trajs), axis=0)

    c0 = np.zeros((n_feat, n_feat), dtype=np.float64)
    c_tau = np.zeros((n_feat, n_feat), dtype=np.float64)
    n_pairs = 0
    n_tot = 0

    for tr in trajs:
        centered = tr - mean_vec[None, :]
        n_tot += centered.shape[0]
        c0 += centered.T @ centered
        if tr.shape[0] > lag_steps:
            x0 = centered[:-lag_steps]
            xt = centered[lag_steps:]
            c_tau += x0.T @ xt
            n_pairs += x0.shape[0]

    c0 /= max(n_tot, 1)
    c0 += reg_eps * np.eye(n_feat)
    c_tau = (c_tau + c_tau.T) / (2.0 * max(n_pairs, 1))

    eigvals, eigvecs = eigh(c_tau, c0)
    # Sort descending by absolute autocorrelation eigenvalue
    order = np.argsort(np.abs(eigvals))[::-1][:n_components]
    vals_sel = eigvals[order]
    vecs_sel = eigvecs[:, order]
    projected = [(tr - mean_vec[None, :]) @ vecs_sel for tr in trajs]
    return projected, vals_sel, vecs_sel


def _kmeans_cluster(data: FloatArray, n_clusters: int, seed: int = 42, max_iter: int = 50) -> IntArray:
    """Deterministic k-means++ initialization and Lloyd refinement for MSM microstates."""
    n = data.shape[0]
    k = min(n_clusters, n)
    rng = np.random.default_rng(seed)
    centers = np.zeros((k, data.shape[1]), dtype=np.float64)
    centers[0] = data[int(rng.integers(0, n))]
    for c_idx in range(1, k):
        d2 = np.min(np.sum((data[:, None, :] - centers[None, :c_idx, :]) ** 2, axis=2), axis=1)
        probs = d2 / max(float(np.sum(d2)), 1e-15)
        centers[c_idx] = data[int(rng.choice(n, p=probs))]

    labels = np.zeros(n, dtype=np.int64)
    for _ in range(max_iter):
        d2_mat = np.sum((data[:, None, :] - centers[None, :, :]) ** 2, axis=2)
        new_labels = np.argmin(d2_mat, axis=1)
        if np.array_equal(new_labels, labels):
            break
        labels = new_labels
        for c_idx in range(k):
            pts = data[labels == c_idx]
            if pts.shape[0] > 0:
                centers[c_idx] = np.mean(pts, axis=0)
    return labels


def estimate_reversible_msm(
    count_matrix: FloatArray,
    max_iter: int = 500,
    tol: float = 1e-10,
) -> Tuple[FloatArray, FloatArray]:
    """Estimate reversible row-stochastic transition matrix T and stationary distribution pi.

    Uses Bowman-Beauchamp-Pande / Trendelkamp-Schroer fixed-point MLE satisfying
    detailed balance ``pi_i T_{ij} = pi_j T_{ji}``.
    """
    c_mat = np.asarray(count_matrix, dtype=np.float64)
    # Add tiny pseudo-count prior only to disconnected diagonal to guarantee ergodicity
    c_sym = c_mat + c_mat.T
    row_sums = np.sum(c_mat, axis=1)
    c_i = np.maximum(row_sums, 1e-12)
    pi = c_i / np.sum(c_i)

    for _ in range(max_iter):
        denom = (c_i / np.maximum(pi, 1e-15))[:, None] + (c_i / np.maximum(pi, 1e-15))[None, :]
        x_mat = c_sym / np.maximum(denom, 1e-15)
        pi_new = np.sum(x_mat, axis=1)
        pi_new /= max(float(np.sum(pi_new)), 1e-15)
        if float(np.max(np.abs(pi_new - pi))) < tol:
            pi = pi_new
            break
        pi = pi_new

    denom = (c_i / np.maximum(pi, 1e-15))[:, None] + (c_i / np.maximum(pi, 1e-15))[None, :]
    flux = c_sym / np.maximum(denom, 1e-15)
    t_mat = flux / np.maximum(np.sum(flux, axis=1, keepdims=True), 1e-15)
    # Recompute exact left eigenvector pi of T
    eigvals, eigvecs = np.linalg.eig(t_mat.T)
    stat_idx = int(np.argmin(np.abs(eigvals - 1.0)))
    pi_exact = np.real(eigvecs[:, stat_idx])
    pi_exact = np.maximum(pi_exact, 0.0)
    pi_exact /= max(float(np.sum(pi_exact)), 1e-15)
    return t_mat, pi_exact


def compute_mfpt_matrix(transition_matrix: FloatArray, lag_time_ps: float) -> FloatArray:
    """Compute exact Mean First-Passage Time (MFPT) matrix ``M_{ij}`` (ps) between all state pairs."""
    t_mat = np.asarray(transition_matrix, dtype=np.float64)
    k = t_mat.shape[0]
    mfpt = np.zeros((k, k), dtype=np.float64)
    for target in range(k):
        mask = [i for i in range(k) if i != target]
        if not mask:
            continue
        sub_a = np.eye(k - 1) - t_mat[np.ix_(mask, mask)]
        rhs = np.full(k - 1, lag_time_ps, dtype=np.float64)
        sol = np.linalg.lstsq(sub_a, rhs, rcond=None)[0]
        for idx, state_i in enumerate(mask):
            mfpt[state_i, target] = float(max(0.0, sol[idx]))
    return mfpt


def build_markov_state_model(
    feature_trajectories: Sequence[FloatArray],
    dt_frame_ps: float = 0.01,
    lag_steps: int = 5,
    n_states: int = 4,
    tica_dim: int = 2,
    seed: int = 42,
) -> MarkovModelResult:
    """Build TICA + reversible Markov State Model with implied timescales and CK validation."""
    tica_trajs, tica_vals, _ = compute_tica(
        feature_trajectories, lag_steps=lag_steps, n_components=min(tica_dim, feature_trajectories[0].shape[1])
    )
    stacked = np.vstack(tica_trajs)
    labels_all = _kmeans_cluster(stacked, n_clusters=n_states, seed=seed)

    # Split labels back per trajectory
    traj_labels: List[IntArray] = []
    offset = 0
    for tr in tica_trajs:
        m = tr.shape[0]
        traj_labels.append(labels_all[offset: offset + m])
        offset += m

    actual_states = int(np.max(labels_all)) + 1

    def _count_transitions(lag: int) -> FloatArray:
        c_mat = np.zeros((actual_states, actual_states), dtype=np.float64)
        for lbl in traj_labels:
            if lbl.size <= lag:
                continue
            for t in range(lbl.size - lag):
                c_mat[lbl[t], lbl[t + lag]] += 1.0
        # Tiny ergodic self-prior on empty rows
        for i in range(actual_states):
            if np.sum(c_mat[i]) < 1.0:
                c_mat[i, i] = 1.0
        return c_mat

    c_lag = _count_transitions(lag_steps)
    t_mat, pi = estimate_reversible_msm(c_lag)

    eigvals = np.real(np.linalg.eigvals(t_mat))
    eigvals = np.sort(eigvals)[::-1]
    lag_ps = lag_steps * dt_frame_ps
    its = np.zeros(max(0, actual_states - 1), dtype=np.float64)
    for idx in range(1, actual_states):
        ev = float(np.clip(abs(eigvals[idx]), 1e-12, 1.0 - 1e-12))
        its[idx - 1] = -lag_ps / np.log(ev)

    # Chapman-Kolmogorov test at 2 * lag_steps: || T(tau)^2 - T(2*tau) ||_F
    c_2lag = _count_transitions(2 * lag_steps)
    t_2lag, _ = estimate_reversible_msm(c_2lag)
    ck_error = float(np.linalg.norm((t_mat @ t_mat) - t_2lag, ord="fro"))

    mfpt = compute_mfpt_matrix(t_mat, lag_ps)
    return MarkovModelResult(
        lag_steps=lag_steps,
        lag_time_ps=lag_ps,
        n_states=actual_states,
        transition_matrix=t_mat,
        stationary_distribution=pi,
        eigenvalues=eigvals,
        implied_timescales_ps=its,
        ck_error=ck_error,
        mfpt_matrix_ps=mfpt,
        tica_eigenvalues=tica_vals,
        state_assignments=labels_all,
    )
