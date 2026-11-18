"""PyTorch Dataset and graph batching utilities for protein 3D residue graphs."""

from __future__ import annotations

from typing import Any
import numpy as np
import torch
from torch.utils.data import Dataset

from protgnn.data.deepfri import parse_ec_labels, create_label_vector
from protgnn.data.graph_builder import build_protein_graph


class ProteinGraphDataset(Dataset):
    """Dataset providing 3D residue contact graphs and multi-label EC numbers."""

    def __init__(
        self,
        records: list[dict[str, Any]],
        contact_threshold: float = 10.0,
        max_neighbors: int = 30,
        num_rbf: int = 16,
    ):
        self.records = records
        self.contact_threshold = contact_threshold
        self.max_neighbors = max_neighbors
        self.num_rbf = num_rbf
        self._cache = {}

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, idx: int) -> dict[str, Any]:
        if idx in self._cache:
            return self._cache[idx]

        rec = self.records[idx]
        seq = rec["sequence"]
        coords = np.asarray(rec["coords"], dtype=np.float32)

        graph = build_protein_graph(
            sequence=seq,
            coords=coords,
            contact_threshold=self.contact_threshold,
            max_neighbors=self.max_neighbors,
            num_rbf=self.num_rbf,
        )

        ec_labels = rec.get("ec_annotations", "")
        if isinstance(ec_labels, str):
            ec_list = parse_ec_labels(ec_labels)
        else:
            ec_list = ec_labels
        labels = create_label_vector(ec_list)

        item = {
            "node_feat": graph["node_feat"],
            "edge_index": graph["edge_index"],
            "edge_feat": graph["edge_feat"],
            "num_nodes": graph["num_nodes"],
            "label": torch.from_numpy(labels),
            "pdb_chain": rec.get("pdb_chain", f"protein_{idx}"),
            "sequence": seq,
        }

        # Cache small graphs in memory
        if len(self._cache) < 5000:
            self._cache[idx] = item

        return item


def collate_protein_graphs(batch: list[dict[str, Any]]) -> dict[str, torch.Tensor | list[str]]:
    """Collate variable-sized protein contact graphs into a unified disjoint block-diagonal batch."""
    node_feats = []
    edge_indices = []
    edge_feats = []
    batch_indices = []
    labels = []
    pdb_chains = []

    node_offset = 0

    for b_idx, item in enumerate(batch):
        N = item["num_nodes"]
        node_feats.append(item["node_feat"])
        edge_feats.append(item["edge_feat"])

        # Offset edge indices
        e_idx = item["edge_index"] + node_offset
        edge_indices.append(e_idx)

        # Batch vector (which graph each node belongs to)
        batch_indices.append(torch.full((N,), b_idx, dtype=torch.long))

        labels.append(item["label"])
        pdb_chains.append(item["pdb_chain"])

        node_offset += N

    return {
        "x": torch.cat(node_feats, dim=0),                    # (N_total, d_node)
        "edge_index": torch.cat(edge_indices, dim=1),          # (2, E_total)
        "edge_attr": torch.cat(edge_feats, dim=0),            # (E_total, d_edge)
        "batch": torch.cat(batch_indices, dim=0),              # (N_total,)
        "y": torch.stack(labels, dim=0),                       # (B, num_classes)
        "pdb_chains": pdb_chains,
        "num_graphs": len(batch),
    }

