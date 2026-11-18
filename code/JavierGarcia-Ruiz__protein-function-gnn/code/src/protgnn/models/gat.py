"""Graph Attention Network (GAT) for protein 3D residue contact graphs."""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


class GATLayer(nn.Module):
    """Multi-head Graph Attention Layer with edge feature conditioning."""

    def __init__(self, d_in: int, d_out: int, d_edge: int = 17, num_heads: int = 4, dropout: float = 0.2):
        super().__init__()
        assert d_out % num_heads == 0, f"d_out ({d_out}) must be divisible by num_heads ({num_heads})"
        self.d_in = d_in
        self.d_out = d_out
        self.num_heads = num_heads
        self.d_head = d_out // num_heads

        self.lin_src = nn.Linear(d_in, d_out, bias=False)
        self.lin_dst = nn.Linear(d_in, d_out, bias=False)
        self.lin_edge = nn.Linear(d_edge, d_out, bias=False)

        self.attn_src = nn.Parameter(torch.empty(1, num_heads, self.d_head))
        self.attn_dst = nn.Parameter(torch.empty(1, num_heads, self.d_head))
        self.attn_edge = nn.Parameter(torch.empty(1, num_heads, self.d_head))

        nn.init.xavier_uniform_(self.attn_src)
        nn.init.xavier_uniform_(self.attn_dst)
        nn.init.xavier_uniform_(self.attn_edge)

        self.norm = nn.LayerNorm(d_out)
        self.dropout = nn.Dropout(dropout)
        self.residual = nn.Linear(d_in, d_out) if d_in != d_out else nn.Identity()

    def forward(self, x: torch.Tensor, edge_index: torch.Tensor, edge_attr: torch.Tensor) -> torch.Tensor:
        N = x.shape[0]
        E = edge_index.shape[1]
        src, dst = edge_index[0], edge_index[1]

        # Multi-head linear projections: (N, H, D_head)
        h_src = self.lin_src(x).view(-1, self.num_heads, self.d_head)
        h_dst = self.lin_dst(x).view(-1, self.num_heads, self.d_head)
        e = self.lin_edge(edge_attr).view(-1, self.num_heads, self.d_head)  # (E, H, D_head)

        # Attention scores on edges
        score_src = (h_src[src] * self.attn_src).sum(dim=-1)      # (E, H)
        score_dst = (h_dst[dst] * self.attn_dst).sum(dim=-1)      # (E, H)
        score_edge = (e * self.attn_edge).sum(dim=-1)             # (E, H)

        scores = F.leaky_relu(score_src + score_dst + score_edge, negative_slope=0.2)

        # Softmax over incoming edges per destination node
        # Compute max per dst for numerical stability
        max_s = torch.zeros((N, self.num_heads), device=x.device).scatter_reduce(
            0, dst.unsqueeze(1).expand_as(scores), scores, reduce="amax", include_self=False
        )
        exp_s = torch.exp(scores - max_s[dst])
        sum_exp = torch.zeros((N, self.num_heads), device=x.device).scatter_add(
            0, dst.unsqueeze(1).expand_as(exp_s), exp_s
        )
        alpha = exp_s / (sum_exp[dst] + 1e-8)  # (E, H)
        alpha = self.dropout(alpha)

        # Message passing: alpha * (h_src + e)
        msg = alpha.unsqueeze(-1) * (h_src[src] + e)  # (E, H, D_head)
        msg = msg.view(E, self.d_out)

        # Aggregate along destination
        out = torch.zeros((N, self.d_out), device=x.device, dtype=x.dtype)
        out.scatter_add_(0, dst.unsqueeze(1).expand_as(msg), msg)

        out = out + self.residual(x)
        out = self.norm(out)
        out = F.gelu(out)
        out = self.dropout(out)
        return out


class ProteinGAT(nn.Module):
    """Multi-layer Graph Attention Network with edge conditioning and attention pooling."""

    def __init__(
        self,
        d_node_in: int = 26,
        d_edge_in: int = 17,
        d_hidden: int = 128,
        num_layers: int = 4,
        num_heads: int = 4,
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
            GATLayer(d_hidden, d_hidden, d_edge=d_edge_in, num_heads=num_heads, dropout=dropout)
            for _ in range(num_layers)
        ])

        # Global Multi-Head Attention Pooling
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
        B = int(batch.max().item()) + 1
        h = self.node_embed(x)

        for layer in self.layers:
            h = layer(h, edge_index, edge_attr)

        # Attention pooling
        scores = self.pool_attn(h).squeeze(-1)  # (N,)

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

