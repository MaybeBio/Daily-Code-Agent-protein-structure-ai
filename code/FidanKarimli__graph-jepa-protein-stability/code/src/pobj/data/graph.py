"""Coordinates -> residue graph.

One node per residue at its CA atom, joined to its k nearest neighbours in 3D. Residues far
apart in the chain can end up adjacent in the graph, which is the whole reason for using
one: 62% of our edges are such contacts, and a sequence model cannot see them.

Shared by every arm, so a change here changes all four at once.
"""
import numpy as np
import torch
from torch_geometric.data import Data

from .features import CA_ATOM, edge_features, node_features
from .megascale import AA_IDX

UNK = 20                 # 'X' and anything not one of the 20 standard amino acids
N_TOKENS = 21            # 20 amino acids + UNK. The mask token is added by the model.

K_NEIGHBOURS = 16        # ProteinWorkshop's choice


def knn_edges(ca: torch.Tensor, k: int = K_NEIGHBOURS) -> torch.Tensor:
    """k nearest neighbours by CA distance, symmetrised. ca: [N, 3] -> [2, E].

    A dense distance matrix is fine here: our proteins are 32-72 residues.
    """
    num = ca.shape[0]
    d = torch.cdist(ca, ca)
    d.fill_diagonal_(float("inf"))
    kk = min(k, num - 1)
    nbr = d.topk(kk, largest=False).indices              # [N, kk]
    dst = torch.arange(num).unsqueeze(1).expand(-1, kk).reshape(-1)
    src = nbr.reshape(-1)

    edges = torch.stack([src, dst])
    edges = torch.cat([edges, edges.flip(0)], dim=1)     # if i sees j, j sees i
    return torch.unique(edges, dim=1)


def build_graph(seq: str, coords: np.ndarray, name: str | None = None,
                k: int = K_NEIGHBOURS) -> Data:
    """seq: str of length N, coords: [N, 4, 3] array -> torch_geometric Data.

    Fields:
      x          [N]      residue type index, 0..20; masking replaces these
      node_feat  [N, 10]  backbone geometry, carries no residue identity
      edge_index [2, E]   undirected kNN graph
      edge_attr  [E, 24]  distance RBF and sequence separation
      pos        [N, 3]   CA coordinates, for plotting and checks only
    """
    coords = torch.as_tensor(np.asarray(coords), dtype=torch.float32)
    ca = coords[:, CA_ATOM]                              # [N, 3]
    edge_index = knn_edges(ca, k=k)

    return Data(
        x=torch.tensor([AA_IDX.get(c, UNK) for c in seq], dtype=torch.long),
        node_feat=node_features(coords),
        edge_index=edge_index,
        edge_attr=edge_features(ca, edge_index),
        pos=ca,
        num_nodes=len(seq),
        seq=seq,
        name=name,
    )


def build_graphs(structures: dict[str, tuple[str, np.ndarray]],
                 k: int = K_NEIGHBOURS) -> dict[str, Data]:
    """{name: (seq, coords)} -> {name: Data}."""
    return {name: build_graph(seq, coords, name=name, k=k)
            for name, (seq, coords) in structures.items()}
