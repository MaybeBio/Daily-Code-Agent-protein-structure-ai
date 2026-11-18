"""Tests for 3D residue contact graph construction and dataset collation."""

import numpy as np
import pytest
import torch

from protgnn.data.constants import EC_CLASSES, AA_TO_IDX
from protgnn.data.graph_builder import rbf_distance_expansion, compute_dihedral_features, build_protein_graph
from protgnn.data.dataset import ProteinGraphDataset, collate_protein_graphs


def test_rbf_distance_expansion():
    distances = np.array([2.0, 5.0, 10.0], dtype=np.float32)
    rbf = rbf_distance_expansion(distances, num_rbf=16)
    assert rbf.shape == (3, 16)
    assert np.all(rbf >= 0.0) and np.all(rbf <= 1.0)


def test_compute_dihedral_features():
    coords = np.array([
        [0.0, 0.0, 0.0],
        [3.8, 0.0, 0.0],
        [3.8, 3.8, 0.0],
        [3.8, 3.8, 3.8],
        [0.0, 3.8, 3.8],
    ], dtype=np.float32)
    feats = compute_dihedral_features(coords)
    assert feats.shape == (5, 6)


def test_build_protein_graph():
    seq = "ACDEFGHIKL"
    L = len(seq)
    # Simulate a straight alpha-carbon chain with 3.8 A spacing
    coords = np.zeros((L, 3), dtype=np.float32)
    for i in range(L):
        coords[i] = [i * 3.8, 0.0, 0.0]

    graph = build_protein_graph(seq, coords, contact_threshold=10.0, max_neighbors=10, num_rbf=16)
    assert graph["node_feat"].shape == (L, 26)
    assert graph["edge_index"].ndim == 2 and graph["edge_index"].shape[0] == 2
    assert graph["edge_feat"].shape[1] == 17  # 16 RBF + 1 sep
    assert graph["num_nodes"] == L


def test_dataset_and_collation():
    records = []
    for idx in range(3):
        L = 10 + idx * 5
        seq = "A" * L
        coords = np.random.randn(L, 3).astype(np.float32)
        records.append({
            "sequence": seq,
            "coords": coords,
            "ec_annotations": "1.1.1; 2.7.1",
            "pdb_chain": f"1abc_{idx}",
        })

    ds = ProteinGraphDataset(records, contact_threshold=10.0, max_neighbors=10)
    assert len(ds) == 3

    batch = [ds[i] for i in range(3)]
    collated = collate_protein_graphs(batch)

    N_total = sum(item["num_nodes"] for item in batch)
    E_total = sum(item["edge_index"].shape[1] for item in batch)

    assert collated["x"].shape == (N_total, 26)
    assert collated["edge_index"].shape == (2, E_total)
    assert collated["edge_attr"].shape == (E_total, 17)
    assert collated["batch"].shape == (N_total,)
    assert collated["y"].shape == (3, len(EC_CLASSES))
    assert collated["num_graphs"] == 3

