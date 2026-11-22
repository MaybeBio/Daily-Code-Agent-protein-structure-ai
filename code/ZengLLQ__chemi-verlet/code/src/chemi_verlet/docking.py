"""Structure-based protein-ligand scoring (Vina empirical + GBSA) and pose optimization.

Implements:
    * Vina-style empirical interaction terms: Gauss1, Gauss2, steric repulsion,
      hydrophobic contact, and directional hydrogen-bond terms
    * Still Generalized Born / SASA implicit-solvent desolvation energy
    * Quaternion-based rigid-body simulated annealing pose optimizer inside a
      receptor pocket
"""

from __future__ import annotations

from typing import Optional, Sequence
import numpy as np

from chemi_verlet.topology import MolecularGraph
from chemi_verlet.types import (
    COULOMB_CONST_KJ_MOL_NM_E2,
    DockingScoreBreakdown,
    FloatArray,
    Topology,
)

# Standard van der Waals radii (nm) for surface/Born calculations
VDW_RADII_NM: dict[str, float] = {
    "H": 0.120,
    "B": 0.192,
    "C": 0.170,
    "N": 0.155,
    "O": 0.152,
    "F": 0.147,
    "P": 0.180,
    "S": 0.180,
    "Cl": 0.175,
    "Br": 0.185,
    "I": 0.198,
}

# Atomic solvation parameters sigma_SASA (kJ / (mol * nm^2))
ASP_KJ_MOL_NM2: dict[str, float] = {
    "C": 18.0,
    "H": 5.0,
    "N": -28.0,
    "O": -32.0,
    "S": 10.0,
    "P": -12.0,
    "F": 6.0,
    "Cl": 12.0,
    "Br": 14.0,
    "I": 16.0,
}


def _quaternion_to_matrix(q: FloatArray) -> FloatArray:
    """Convert unit quaternion ``(w, x, y, z)`` to ``3x3`` rotation matrix."""
    q = q / max(float(np.linalg.norm(q)), 1e-12)
    w, x, y, z = float(q[0]), float(q[1]), float(q[2]), float(q[3])
    return np.array(
        [
            [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - w * z), 2.0 * (x * z + w * y)],
            [2.0 * (x * y + w * z), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - w * x)],
            [2.0 * (x * z - w * y), 2.0 * (y * z + w * x), 1.0 - 2.0 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def compute_gbsa_desolvation(
    topology: Topology,
    positions: FloatArray,
    atom_indices: Sequence[int],
    eps_in: float = 1.0,
    eps_out: float = 78.5,
) -> float:
    """Estimate Still Generalized Born + SASA solvation free energy (kJ/mol) for a subset."""
    idx = np.asarray(atom_indices, dtype=np.int64)
    if idx.size == 0:
        return 0.0
    pos = positions[idx]
    charges = topology.charges[idx]
    radii = np.array([VDW_RADII_NM.get(topology.atoms[i].element, 0.17) for i in idx], dtype=np.float64)

    dr = pos[None, :, :] - pos[:, None, :]
    r2 = np.sum(dr * dr, axis=-1)
    r = np.sqrt(np.maximum(r2, 1e-12))

    # Effective Born radii via pairwise Still volume-occlusion approximation
    n = idx.size
    born_inv = 1.0 / radii
    for a in range(n):
        occ = 0.0
        for b in range(n):
            if a == b:
                continue
            rab = float(r[a, b])
            if rab > 0.05:
                v_b = (4.0 / 3.0) * np.pi * (radii[b] ** 3)
                occ += v_b / (4.0 * np.pi * (rab ** 4))
        born_inv[a] = max(0.1 / radii[a], born_inv[a] - occ * 0.25)
    born_r = 1.0 / born_inv

    # Generalized Born polarization energy: -0.5 * f_el * (1/eps_in - 1/eps_out) * sum_{i,j} q_i q_j / f_GB
    prod_r = born_r[:, None] * born_r[None, :]
    f_gb = np.sqrt(r2 + prod_r * np.exp(-r2 / np.maximum(4.0 * prod_r, 1e-12)))
    pref = -0.5 * COULOMB_CONST_KJ_MOL_NM_E2 * (1.0 / eps_in - 1.0 / eps_out)
    u_gb = pref * float(np.sum((charges[:, None] * charges[None, :]) / f_gb))

    # Solute-solvent SASA hydrophobic contribution modulated by neighbor burying
    u_sa = 0.0
    probe = 0.14
    for a in range(n):
        ra_eff = radii[a] + probe
        area = 4.0 * np.pi * ra_eff * ra_eff
        burial = 0.0
        for b in range(n):
            if a == b:
                continue
            rb_eff = radii[b] + probe
            rab = float(r[a, b])
            if rab < ra_eff + rb_eff:
                overlap = (ra_eff + rb_eff - rab) / (2.0 * ra_eff)
                burial += min(0.25, max(0.0, overlap))
        exposed = max(0.05, 1.0 - burial)
        asp = ASP_KJ_MOL_NM2.get(topology.atoms[idx[a]].element, 10.0)
        u_sa += asp * area * exposed

    return u_gb + u_sa


def score_protein_ligand_pose(
    topology: Topology,
    positions: FloatArray,
    receptor_indices: Sequence[int],
    ligand_indices: Sequence[int],
    rotatable_bonds: int = 2,
    initial_ligand_positions: Optional[FloatArray] = None,
) -> DockingScoreBreakdown:
    """Evaluate Vina-inspired empirical binding score plus GBSA binding desolvation (kJ/mol)."""
    rec_idx = np.asarray(receptor_indices, dtype=np.int64)
    lig_idx = np.asarray(ligand_indices, dtype=np.int64)
    r_pos = positions[rec_idx]
    l_pos = positions[lig_idx]

    # Pairwise receptor-ligand surface distances d_ij = r_ij - R_i - R_j (in Angstrom for Vina terms)
    dr_nm = l_pos[None, :, :] - r_pos[:, None, :]  # (N_rec, N_lig, 3)
    dist_ang = np.linalg.norm(dr_nm, axis=-1) * 10.0

    rec_rad = np.array([VDW_RADII_NM.get(topology.atoms[i].element, 0.17) * 10.0 for i in rec_idx])
    lig_rad = np.array([VDW_RADII_NM.get(topology.atoms[i].element, 0.17) * 10.0 for i in lig_idx])
    d_surf = dist_ang - (rec_rad[:, None] + lig_rad[None, :])

    # Ignore pairs beyond 8.0 A
    within = dist_ang <= 8.0
    d_w = np.where(within, d_surf, 100.0)

    # Vina weights (converted from kcal/mol to kJ/mol via * 4.184)
    kcal_to_kj = 4.184
    w_g1 = -0.035579 * kcal_to_kj
    w_g2 = -0.005156 * kcal_to_kj
    w_rep = 0.840245 * kcal_to_kj
    w_hyd = -0.035069 * kcal_to_kj
    w_hb = -0.587439 * kcal_to_kj
    w_rot = 0.05846 * kcal_to_kj

    g1 = float(np.sum(np.where(within, np.exp(-((d_w / 0.5) ** 2)), 0.0))) * w_g1
    g2 = float(np.sum(np.where(within, np.exp(-(((d_w - 3.0) / 2.0) ** 2)), 0.0))) * w_g2
    rep = float(np.sum(np.where(within & (d_w < 0.0), d_w * d_w, 0.0))) * w_rep

    rec_hyd = np.array([topology.atoms[i].is_hydrophobic for i in rec_idx], dtype=bool)
    lig_hyd = np.array([topology.atoms[i].is_hydrophobic for i in lig_idx], dtype=bool)
    hyd_mask = within & (rec_hyd[:, None] & lig_hyd[None, :])
    # Smooth linear ramp from 1.0 at d<=0.5 A to 0.0 at d>=1.5 A
    hyd_ramp = np.clip((1.5 - d_w) / 1.0, 0.0, 1.0)
    hydrophobic = float(np.sum(np.where(hyd_mask, hyd_ramp, 0.0))) * w_hyd

    rec_don = np.array([topology.atoms[i].is_donor for i in rec_idx], dtype=bool)
    rec_acc = np.array([topology.atoms[i].is_acceptor for i in rec_idx], dtype=bool)
    lig_don = np.array([topology.atoms[i].is_donor for i in lig_idx], dtype=bool)
    lig_acc = np.array([topology.atoms[i].is_acceptor for i in lig_idx], dtype=bool)
    hb_mask = within & ((rec_don[:, None] & lig_acc[None, :]) | (rec_acc[:, None] & lig_don[None, :]))
    hb_ramp = np.clip((-d_w) / 0.7, 0.0, 1.0)
    hbond = float(np.sum(np.where(hb_mask, hb_ramp, 0.0))) * w_hb

    # GBSA desolvation change upon complexation: dG_solv(complex) - dG_solv(rec) - dG_solv(lig)
    g_comp = compute_gbsa_desolvation(topology, positions, list(receptor_indices) + list(ligand_indices))
    g_rec = compute_gbsa_desolvation(topology, positions, receptor_indices)
    g_lig = compute_gbsa_desolvation(topology, positions, ligand_indices)
    # Scale down slightly to pair harmoniously with empirical Vina terms
    gbsa_delta = 0.05 * (g_comp - g_rec - g_lig)

    raw_inter = g1 + g2 + rep + hydrophobic + hbond + gbsa_delta
    torsion_pen = abs(raw_inter) * w_rot * rotatable_bonds / 4.184 if raw_inter < 0 else w_rot * rotatable_bonds
    total = raw_inter + torsion_pen

    rmsd = 0.0
    if initial_ligand_positions is not None:
        rmsd = float(np.sqrt(np.mean(np.sum((l_pos - initial_ligand_positions) ** 2, axis=1))))

    return DockingScoreBreakdown(
        total_score=total,
        gauss1=g1,
        gauss2=g2,
        repulsion=rep,
        hydrophobic=hydrophobic,
        hbond=hbond,
        gbsa_desolvation=gbsa_delta,
        torsion_entropy=torsion_pen,
        rmsd_from_initial=rmsd,
        optimized_positions=positions.copy(),
    )


def optimize_binding_pose(
    topology: Topology,
    positions: FloatArray,
    receptor_indices: Sequence[int],
    ligand_indices: Sequence[int],
    ligand_graph: Optional[MolecularGraph] = None,
    n_iterations: int = 300,
    pocket_radius_nm: float = 0.45,
    seed: int = 42,
) -> DockingScoreBreakdown:
    """Optimize rigid-body ligand pose in a receptor pocket via simulated annealing."""
    rng = np.random.default_rng(seed)
    rec_idx = np.asarray(receptor_indices, dtype=np.int64)
    lig_idx = np.asarray(ligand_indices, dtype=np.int64)

    rot_bonds = ligand_graph.rotatable_bond_count() if ligand_graph is not None else 2
    pocket_center = np.mean(positions[rec_idx], axis=0)
    lig_init = positions[lig_idx].copy()

    cur_pos = positions.copy()
    # Center ligand near pocket center initially if far away
    cur_lig_com = np.mean(cur_pos[lig_idx], axis=0)
    if float(np.linalg.norm(cur_lig_com - pocket_center)) > pocket_radius_nm:
        cur_pos[lig_idx] += pocket_center - cur_lig_com

    cur_score = score_protein_ligand_pose(
        topology, cur_pos, receptor_indices, ligand_indices,
        rotatable_bonds=rot_bonds, initial_ligand_positions=lig_init,
    )
    best_score = cur_score
    best_pos = cur_pos.copy()

    t_start = 8.0
    t_end = 0.3
    for step in range(n_iterations):
        frac = step / max(1, n_iterations - 1)
        temp = t_start * ((t_end / t_start) ** frac)
        trans_scale = 0.045 * (1.0 - 0.7 * frac)
        rot_scale = 0.35 * (1.0 - 0.7 * frac)

        trial_pos = cur_pos.copy()
        lig_coords = trial_pos[lig_idx]
        com = np.mean(lig_coords, axis=0)
        centered = lig_coords - com[None, :]

        # Random small quaternion perturbation
        dq = np.array([1.0, *rng.normal(0.0, rot_scale, size=3)], dtype=np.float64)
        rot_mat = _quaternion_to_matrix(dq)
        dtrans = rng.normal(0.0, trans_scale, size=3)
        new_com = com + dtrans
        # Soft tether inside receptor pocket
        offset = new_com - pocket_center
        off_norm = float(np.linalg.norm(offset))
        if off_norm > pocket_radius_nm:
            new_com = pocket_center + offset * (pocket_radius_nm / off_norm)

        trial_pos[lig_idx] = (centered @ rot_mat.T) + new_com[None, :]
        trial_score = score_protein_ligand_pose(
            topology, trial_pos, receptor_indices, ligand_indices,
            rotatable_bonds=rot_bonds, initial_ligand_positions=lig_init,
        )

        delta = trial_score.total_score - cur_score.total_score
        if delta <= 0.0 or rng.uniform() < float(np.exp(-delta / max(temp, 1e-6))):
            cur_pos = trial_pos
            cur_score = trial_score
            if trial_score.total_score < best_score.total_score:
                best_score = trial_score
                best_pos = trial_pos.copy()

    best_score.optimized_positions = best_pos
    return best_score
