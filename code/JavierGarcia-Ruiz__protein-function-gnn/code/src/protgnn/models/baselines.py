"""Sequence-only baseline for protein function prediction (1D CNN without 3D contacts)."""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


class ProteinSequenceCNN(nn.Module):
    """1D Dilated CNN operating purely on amino acid sequence one-hot features."""

    def __init__(
        self,
        d_node_in: int = 26,
        d_hidden: int = 128,
        num_layers: int = 4,
        num_classes: int = 25,
        dropout: float = 0.2,
    ):
        super().__init__()
        # Use amino acid one-hot (first 20 features)
        self.embed = nn.Linear(20, d_hidden)
        
        self.convs = nn.ModuleList([
            nn.Conv1d(d_hidden, d_hidden, kernel_size=5, padding=2 * (2**i), dilation=2**i)
            for i in range(num_layers)
        ])
        self.norms = nn.ModuleList([nn.LayerNorm(d_hidden) for _ in range(num_layers)])
        self.dropout = nn.Dropout(dropout)

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
        """Forward pass ignoring edges to quantify the value of 3D contact graph message passing."""
        B = int(batch.max().item()) + 1
        aa_onehot = x[:, :20]
        h = self.embed(aa_onehot)

        # De-batch to process variable length chains
        # Or pad/transpose for 1D convolution
        # Process node representations per graph
        h_out = []
        for b_idx in range(B):
            mask = (batch == b_idx)
            h_graph = h[mask].unsqueeze(0).transpose(1, 2)  # (1, d, L)
            for conv, norm in zip(self.convs, self.norms):
                res = h_graph
                h_graph = conv(h_graph).transpose(1, 2)
                h_graph = norm(h_graph).transpose(1, 2)
                h_graph = F.gelu(h_graph)
                h_graph = self.dropout(h_graph) + res
            h_out.append(h_graph.squeeze(0).transpose(0, 1))

        h = torch.cat(h_out, dim=0)

        # Attention pooling
        scores = self.pool_attn(h).squeeze(-1)
        max_scores = torch.zeros(B, device=x.device, dtype=scores.dtype).scatter_reduce(0, batch, scores, reduce="amax", include_self=False)
        exp_scores = torch.exp(scores - max_scores[batch])
        sum_exp = torch.zeros(B, device=x.device, dtype=scores.dtype).scatter_add(0, batch, exp_scores)
        alpha = exp_scores / (sum_exp[batch] + 1e-8)

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

