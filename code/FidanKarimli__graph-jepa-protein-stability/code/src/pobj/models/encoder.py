"""The GINE encoder. Every arm uses this, unchanged."""
import torch
import torch.nn as nn
from torch import Tensor
from torch_geometric.nn import GINEConv

from ..data.features import EDGE_FEAT_DIM, NODE_FEAT_DIM
from ..data.graph import N_TOKENS

MASK = N_TOKENS                      # the extra token that replaces a hidden residue
N_TOKENS_WITH_MASK = N_TOKENS + 1


def mlp(sizes: list[int], dropout: float = 0.0) -> nn.Sequential:
    layers = []
    for i, (a, b) in enumerate(zip(sizes[:-1], sizes[1:])):
        layers.append(nn.Linear(a, b))
        if i < len(sizes) - 2:
            layers += [nn.ReLU(), nn.Dropout(dropout)]
    return nn.Sequential(*layers)


class Encoder(nn.Module):
    """Residue graph -> one embedding per residue, [N, dim].

    The residue type and the backbone geometry enter separately and are added, so that
    masking only has to replace the residue type.
    """

    def __init__(self, dim: int = 128, layers: int = 4, dropout: float = 0.1) -> None:
        super().__init__()
        self.dim = dim
        self.aa = nn.Embedding(N_TOKENS_WITH_MASK, dim)
        self.geom = nn.Linear(NODE_FEAT_DIM, dim)

        self.convs = nn.ModuleList(
            GINEConv(mlp([dim, 2 * dim, dim], dropout), edge_dim=EDGE_FEAT_DIM)
            for _ in range(layers)
        )
        self.norms = nn.ModuleList(nn.LayerNorm(dim) for _ in range(layers))
        self.dropout = nn.Dropout(dropout)
        # Every layer adds to h, so without a final norm the output scale grows with
        # depth. That showed up as an untrained letter loss of 4.34 instead of ln(20).
        self.out_norm = nn.LayerNorm(dim)

    def forward(self, x: Tensor, node_feat: Tensor,
                edge_index: Tensor, edge_attr: Tensor) -> Tensor:
        h = self.aa(x) + self.geom(node_feat)
        for conv, norm in zip(self.convs, self.norms):
            h = h + self.dropout(torch.relu(conv(norm(h), edge_index, edge_attr)))
        return self.out_norm(h)

    def encode(self, batch) -> Tensor:
        return self(batch.x, batch.node_feat, batch.edge_index, batch.edge_attr)
