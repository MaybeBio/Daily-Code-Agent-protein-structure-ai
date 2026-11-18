"""Construction of 3D residue contact graphs from protein structural coordinates."""

from __future__ import annotations

import numpy as np
import torch
from scipy.spatial.distance import cdist

from protgnn.data.constants import AA_TO_IDX


def rbf_distance_expansion(distances: np.ndarray, num_rbf: int = 16, d_min: float = 0.0, d_max: float = 12.0) -> np.ndarray:
    """Expand scalar Euclidean distances into Gaussian Radial Basis Function (RBF) features."""
    centers = np.linspace(d_min, d_max, num_rbf)
    gamma = 1.0 / ((d_max - d_min) / num_rbf) ** 2
    # distances: (E,), centers: (K,) -> (E, K)
    diff = distances[:, None] - centers[None, :]
    return np.exp(-gamma * (diff ** 2)).astype(np.float32)


def compute_dihedral_features(coords: np.ndarray) -> np.ndarray:
    """Compute local pseudo-dihedral angles (sin, cos) along C-alpha backbone chain (L, 6)."""
    L = len(coords)
    feats = np.zeros((L, 6), dtype=np.float32)
    if L < 4:
        return feats

    # Vectors between consecutive C-alphas
    v1 = coords[1:-2] - coords[:-3]   # (L-3, 3)
    v2 = coords[2:-1] - coords[1:-2]  # (L-3, 3)
    v3 = coords[3:] - coords[2:-1]    # (L-3, 3)

    # Normals
    n1 = np.cross(v1, v2)
    n2 = np.cross(v2, v3)

    norm_n1 = np.linalg.norm(n1, axis=-1, keepdims=True) + 1e-8
    norm_n2 = np.linalg.norm(n2, axis=-1, keepdims=True) + 1e-8
    norm_v2 = np.linalg.norm(v2, axis=-1, keepdims=True) + 1e-8

    n1 /= norm_n1
    n2 /= norm_n2

    m1 = np.cross(n1, v2 / norm_v2)
    x = np.sum(n1 * n2, axis=-1)
    y = np.sum(m1 * n2, axis=-1)
    angle = np.arctan2(y, x)

    # Assign to central residues
    feats[1:-2, 0] = np.sin(angle)
    feats[1:-2, 1] = np.cos(angle)

    # Bond angles
    cos_theta = np.sum(-v1 * v2, axis=-1) / (np.linalg.norm(v1, axis=-1) * np.linalg.norm(v2, axis=-1) + 1e-8)
    cos_theta = np.clip(cos_theta, -1.0, 1.0)
    theta = np.arccos(cos_theta)
    feats[1:-2, 2] = np.sin(theta)
    feats[1:-2, 3] = np.cos(theta)

    # Consecutive distance
    d12 = np.linalg.norm(v2, axis=-1)
    feats[1:-2, 4] = np.clip(d12 / 4.0, 0.0, 2.0)
    feats[1:-2, 5] = 1.0

    return feats


def build_protein_graph(
    sequence: str,
    coords: np.ndarray,
    contact_threshold: float = 10.0,
    max_neighbors: int = 30,
    num_rbf: int = 16,
) -> dict[str, torch.Tensor]:
    """Construct a PyTorch residue contact graph from amino acid sequence and C-alpha coordinates.

    Args:
        sequence: Amino acid sequence string of length L.
        coords: (L, 3) C-alpha Cartesian coordinates in Angstroms.
        contact_threshold: Distance cutoff for spatial contacts (default 10.0 A).
        max_neighbors: Maximum k-NN degree per residue node.
        num_rbf: Number of Gaussian RBF distance bins.

    Returns:
        Dictionary with:
            - "node_feat": (L, 26) node features (20 one-hot + 6 backbone dihedral)
            - "edge_index": (2, E) directed edge indices
            - "edge_feat": (E, num_rbf + 1) edge features (RBF distances + sequence separation)
            - "num_nodes": L
    """
    seq = sequence.strip().upper()
    L = len(seq)
    coords = np.asarray(coords, dtype=np.float32)
    assert len(coords) == L, f"Sequence length ({L}) != coords length ({len(coords)})"

    # 1. Node Features (L, 26)
    node_feat = np.zeros((L, 26), dtype=np.float32)
    for i, aa in enumerate(seq):
        idx = AA_TO_IDX.get(aa, -1)
        if 0 <= idx < 20:
            node_feat[i, idx] = 1.0

    dihedrals = compute_dihedral_features(coords)
    node_feat[:, 20:26] = dihedrals

    # 2. Pairwise Distances
    dist_mat = cdist(coords, coords)  # (L, L)

    # 3. Construct Edges
    src_list = []
    dst_list = []
    dist_list = []
    seq_sep_list = []

    for i in range(L):
        # Always include immediate chain neighbors (|i - j| <= 2)
        chain_nbrs = [j for j in range(max(0, i - 2), min(L, i + 3)) if j != i]

        # Spatial neighbors within threshold
        spatial_nbrs = [
            j for j in range(L)
            if j != i and dist_mat[i, j] <= contact_threshold and j not in chain_nbrs
        ]
        # Sort spatial neighbors by distance and take top
        spatial_nbrs.sort(key=lambda j: dist_mat[i, j])
        nbrs = chain_nbrs + spatial_nbrs[: max(0, max_neighbors - len(chain_nbrs))]

        for j in nbrs:
            src_list.append(i)
            dst_list.append(j)
            d = dist_mat[i, j]
            dist_list.append(d)
            # Normalized sequence separation
            sep = np.sign(j - i) * np.log(abs(j - i) + 1.0) / 5.0
            seq_sep_list.append(sep)

    if len(src_list) == 0:
        # Fallback for single residue or disconnected: self-loop
        edge_index = np.zeros((2, 1), dtype=np.int64)
        edge_feat = np.zeros((1, num_rbf + 1), dtype=np.float32)
    else:
        edge_index = np.array([src_list, dst_list], dtype=np.int64)
        rbf_feats = rbf_distance_expansion(np.array(dist_list), num_rbf=num_rbf)
        sep_feats = np.array(seq_sep_list, dtype=np.float32)[:, None]
        edge_feat = np.concatenate([rbf_feats, sep_feats], axis=-1)

    return {
        "node_feat": torch.from_numpy(node_feat),
        "edge_index": torch.from_numpy(edge_index),
        "edge_feat": torch.from_numpy(edge_feat),
        "num_nodes": L,
    }

