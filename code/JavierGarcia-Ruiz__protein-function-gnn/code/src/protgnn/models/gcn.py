"""Graph Convolutional Network (GCN) for protein 3D residue contact graphs."""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


def scatter_add(src: torch.Tensor, index: torch.Tensor, dim_size: int) -> torch.Tensor:
    """Sum aggregation along index without external C++ dependencies."""
    out = torch.zeros((dim_size, src.shape[1]), device=src.device, dtype=src.dtype)
    out.scatter_add_(0, index.unsqueeze(1).expand_as(src), src)
    return out


class GCNLayer(nn.Module):
    """Residual GCN layer with edge feature modulation."""

    def __init__(self, d_in: int, d_out: int, d_edge: int = 17, dropout: float = 0.2):
        super().__init__()
        self.linear = nn.Linear(d_in, d_out, bias=False)
        self.edge_proj = nn.Linear(d_edge, d_out)
        self.norm = nn.LayerNorm(d_out)
        self.dropout = nn.Dropout(dropout)
        self.residual = nn.Linear(d_in, d_out) if d_in != d_out else nn.Identity()

    def forward(self, x: torch.Tensor, edge_index: torch.Tensor, edge_attr: torch.Tensor) -> torch.Tensor:
        """Forward pass.

        Args:
            x: (N, d_in) node features
            edge_index: (2, E) directed edges [src, dst]
            edge_attr: (E, d_edge) edge features
        """
        N = x.shape[0]
        src, dst = edge_index[0], edge_index[1]

        # Compute degree for symmetric normalization: deg_i = count of edges into i
        deg = torch.zeros(N, device=x.device, dtype=x.dtype)
        deg.scatter_add_(0, dst, torch.ones_like(dst, dtype=x.dtype))
        deg_inv_sqrt = torch.pow(deg.clamp(min=1.0), -0.5)

        norm_factor = deg_inv_sqrt[src] * deg_inv_sqrt[dst]  # (E,)

        h = self.linear(x)  # (N, d_out)
        e = self.edge_proj(edge_attr)  # (E, d_out)

        # Message: (h_src + e) * norm
        msg = (h[src] + e) * norm_factor.unsqueeze(-1)
        aggr = scatter_add(msg, dst, dim_size=N)

        out = aggr + self.residual(x)
        out = self.norm(out)
        out = F.gelu(out)
        out = self.dropout(out)
        return out


class ProteinGCN(nn.Module):
    """Multi-layer Graph Convolutional Network with attention pooling for EC prediction."""

    def __init__(
        self,
        d_node_in: int = 26,
        d_edge_in: int = 17,
        d_hidden: int = 128,
        num_layers: int = 4,
        num_classes: int = 25,
        dropout: float = 0.2,
    ):
        super().__init__()
        self.node_embed = nn.Sequential(
            nn.Linear(d_node_in, d_hidden),
            nn.LayerNorm(d_hidden),
            nn.GELU(),
        )

        self.layers = nn.ModuleList([
            GCNLayer(d_hidden, d_hidden, d_edge=d_edge_in, dropout=dropout)
            for _ in range(num_layers)
        ])

        # Global Attention Pooling
        self.pool_attn = nn.Sequential(
            nn.Linear(d_hidden, d_hidden // 2),
            nn.Tanh(),
            nn.Linear(d_hidden // 2, 1),
        )

        self.classifier = nn.Sequential(
            nn.Linear(d_hidden, d_hidden),
            nn.LayerNorm(d_hidden),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_hidden, num_classes),
        )

    def forward(
        self,
        x: torch.Tensor,
        edge_index: torch.Tensor,
        edge_attr: torch.Tensor,
        batch: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        """Forward pass.

        Args:
            x: (N_total, d_node_in)
            edge_index: (2, E_total)
            edge_attr: (E_total, d_edge_in)
            batch: (N_total,) graph batch assignments
        """
        B = int(batch.max().item()) + 1
        h = self.node_embed(x)

        for layer in self.layers:
            h = layer(h, edge_index, edge_attr)

        # Attention pooling
        scores = self.pool_attn(h).squeeze(-1)  # (N,)

        # Softmax per graph in batch
        max_scores = torch.zeros(B, device=x.device, dtype=scores.dtype).scatter_reduce(0, batch, scores, reduce="amax", include_self=False)
        exp_scores = torch.exp(scores - max_scores[batch])
        sum_exp = torch.zeros(B, device=x.device, dtype=scores.dtype).scatter_add(0, batch, exp_scores)
        alpha = exp_scores / (sum_exp[batch] + 1e-8)  # (N,)

        weighted = h * alpha.unsqueeze(-1)
        pooled = torch.zeros((B, h.shape[1]), device=x.device, dtype=h.dtype)
        pooled.scatter_add_(0, batch.unsqueeze(1).expand_as(weighted), weighted)

        logits = self.classifier(pooled)
        probs = torch.sigmoid(logits)

        return {
            "logits": logits,
            "probs": probs,
            "pooled": pooled,
            "node_embeddings": h,
            "attention_weights": alpha,
        }

