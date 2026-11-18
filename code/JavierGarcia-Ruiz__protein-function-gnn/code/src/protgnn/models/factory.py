"""Factory for protein function prediction models."""

from __future__ import annotations

import torch.nn as nn

from protgnn.models.baselines import ProteinSequenceCNN
from protgnn.models.gcn import ProteinGCN
from protgnn.models.gat import ProteinGAT


def build_model(cfg: dict) -> nn.Module:
    """Build GNN or baseline model from configuration."""
    m_cfg = cfg.get("model", {})
    name = m_cfg.get("name", "gat")

    d_node_in = m_cfg.get("d_node_in", 26)
    d_edge_in = m_cfg.get("d_edge_in", 17)
    d_hidden = m_cfg.get("d_hidden", 128)
    num_layers = m_cfg.get("num_layers", 4)
    num_heads = m_cfg.get("num_heads", 4)
    num_classes = m_cfg.get("num_classes", 25)
    dropout = m_cfg.get("dropout", 0.2)

    if name == "cnn_baseline":
        return ProteinSequenceCNN(
            d_node_in=d_node_in,
            d_hidden=d_hidden,
            num_layers=num_layers,
            num_classes=num_classes,
            dropout=dropout,
        )
    elif name == "gcn":
        return ProteinGCN(
            d_node_in=d_node_in,
            d_edge_in=d_edge_in,
            d_hidden=d_hidden,
            num_layers=num_layers,
            num_classes=num_classes,
            dropout=dropout,
        )
    elif name == "gat":
        return ProteinGAT(
            d_node_in=d_node_in,
            d_edge_in=d_edge_in,
            d_hidden=d_hidden,
            num_layers=num_layers,
            num_heads=num_heads,
            num_classes=num_classes,
            dropout=dropout,
        )
    else:
        raise ValueError(f"Unknown model name: {name}")

