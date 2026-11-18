"""Tests for GNN and baseline models on protein contact graphs."""

import pytest
import torch

from protgnn.models.gcn import ProteinGCN
from protgnn.models.gat import ProteinGAT
from protgnn.models.baselines import ProteinSequenceCNN


def make_dummy_graph(B=2, N_per_graph=15, d_node=26, d_edge=17):
    N_total = B * N_per_graph
    x = torch.randn(N_total, d_node)
    
    # Create simple cyclic edges per graph
    src_list, dst_list = [], []
    for b in range(B):
        offset = b * N_per_graph
        for i in range(N_per_graph):
            j = (i + 1) % N_per_graph
            src_list.append(offset + i)
            dst_list.append(offset + j)

    edge_index = torch.tensor([src_list, dst_list], dtype=torch.long)
    edge_attr = torch.randn(len(src_list), d_edge)
    batch = torch.repeat_interleave(torch.arange(B), N_per_graph)
    return x, edge_index, edge_attr, batch


def test_protein_gcn():
    x, edge_index, edge_attr, batch = make_dummy_graph(B=2, N_per_graph=12)
    model = ProteinGCN(d_node_in=26, d_edge_in=17, d_hidden=32, num_layers=2, num_classes=25)
    out = model(x, edge_index, edge_attr, batch)

    assert out["logits"].shape == (2, 25)
    assert out["probs"].shape == (2, 25)
    assert out["pooled"].shape == (2, 32)
    assert out["attention_weights"].shape == (24,)
    assert torch.all(out["probs"] >= 0.0) and torch.all(out["probs"] <= 1.0)


def test_protein_gat():
    x, edge_index, edge_attr, batch = make_dummy_graph(B=2, N_per_graph=12)
    model = ProteinGAT(d_node_in=26, d_edge_in=17, d_hidden=32, num_layers=2, num_heads=2, num_classes=25)
    out = model(x, edge_index, edge_attr, batch)

    assert out["logits"].shape == (2, 25)
    assert out["probs"].shape == (2, 25)
    assert out["pooled"].shape == (2, 32)
    assert out["attention_weights"].shape == (24,)
    assert torch.all(out["probs"] >= 0.0) and torch.all(out["probs"] <= 1.0)


def test_protein_sequence_cnn():
    x, edge_index, edge_attr, batch = make_dummy_graph(B=2, N_per_graph=12)
    model = ProteinSequenceCNN(d_node_in=26, d_hidden=32, num_layers=2, num_classes=25)
    out = model(x, edge_index, edge_attr, batch)

    assert out["logits"].shape == (2, 25)
    assert out["probs"].shape == (2, 25)
    assert out["pooled"].shape == (2, 32)
    assert torch.all(out["probs"] >= 0.0) and torch.all(out["probs"] <= 1.0)

