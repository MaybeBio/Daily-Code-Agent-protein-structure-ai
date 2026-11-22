import math
import torch
import torch.nn as nn
import torch.nn.functional as F

from graph_transformer_model import ProtT5GraphTransformer


class ResidualMLPExpert(nn.Module):
    """
    Modality-Specific Residual FNN/MLP Expert (inspired by Multimodal-AlgPro, Yu et al. 2025).
    Encodes a single evolutionary descriptor family (e.g., PSSM400 [400], DPC_PSSM [400],
    DFMCA_PSSM [210], or Single_Average [400]) into a 192-dim semantic token with
    Pre-LayerNorm, GELU, Squeeze-and-Excitation channel gating, and a skip projection.
    """
    def __init__(self, in_dim: int, out_dim: int = 192, dropout: float = 0.25):
        super().__init__()
        hidden_dim = max(out_dim, in_dim // 2)
        self.in_norm = nn.LayerNorm(in_dim)
        self.skip_proj = nn.Linear(in_dim, out_dim)

        self.mlp = nn.Sequential(
            nn.Linear(in_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, out_dim),
            nn.Dropout(dropout),
        )
        # Squeeze-and-Excitation (SE) feature recalibration gate
        self.se_gate = nn.Sequential(
            nn.Linear(out_dim, out_dim // 4),
            nn.GELU(),
            nn.Linear(out_dim // 4, out_dim),
            nn.Sigmoid(),
        )
        self.out_norm = nn.LayerNorm(out_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x_n = self.in_norm(x)
        h = self.mlp(x_n)
        h = h * self.se_gate(h)
        return self.out_norm(h + self.skip_proj(x_n))


class AminoAcidCNN_MHSAExpert(nn.Module):
    """
    DeepAlgPro-inspired Multi-Scale 1D-CNN + Multi-Head Self-Attention (MHSA) Expert
    (He et al., Briefings in Bioinformatics 2023).
    Operates on the natural 20-amino-acid 2D matrix structure of PSSM400 [20x20],
    DPC_PSSM [20x20], and Single_Average [20x20] stacked as [B, 20, 60] (20 standard
    amino acid tokens x 60 evolutionary profile channels).
    """
    def __init__(self, in_channels: int = 60, out_dim: int = 192, num_heads: int = 4, dropout: float = 0.25):
        super().__init__()
        mid_ch = out_dim // 2  # 96

        # Multi-scale 1D convolutions across the 20 amino-acid profile tokens
        self.conv_k1 = nn.Conv1d(in_channels, mid_ch, kernel_size=1, padding=0)
        self.conv_k3 = nn.Conv1d(in_channels, mid_ch, kernel_size=3, padding=1)
        self.conv_proj = nn.Sequential(
            nn.Linear(out_dim, out_dim),
            nn.LayerNorm(out_dim),
            nn.GELU(),
            nn.Dropout(dropout),
        )

        # Learnable 20-amino-acid positional embedding
        self.aa_pos_emb = nn.Parameter(torch.randn(1, 20, out_dim) * 0.02)

        # Multi-Head Self-Attention (MHSA) + Pre-LN Transformer block
        self.mhsa_norm1 = nn.LayerNorm(out_dim)
        self.mhsa = nn.MultiheadAttention(
            embed_dim=out_dim, num_heads=num_heads, dropout=dropout, batch_first=True
        )
        self.mhsa_drop = nn.Dropout(dropout)

        self.mhsa_norm2 = nn.LayerNorm(out_dim)
        self.ffn = nn.Sequential(
            nn.Linear(out_dim, out_dim * 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(out_dim * 2, out_dim),
            nn.Dropout(dropout),
        )

        # Attention pooling over the 20 amino-acid tokens -> [B, 192]
        self.attn_pool = nn.Sequential(
            nn.Linear(out_dim, out_dim // 2),
            nn.Tanh(),
            nn.Linear(out_dim // 2, 1),
        )
        self.out_norm = nn.LayerNorm(out_dim)

    def forward(self, aa_profile_20x60: torch.Tensor) -> torch.Tensor:
        # aa_profile_20x60: [B, 20, 60]
        x_c = aa_profile_20x60.transpose(1, 2)  # [B, 60, 20]
        c1 = F.gelu(self.conv_k1(x_c))          # [B, 96, 20]
        c3 = F.gelu(self.conv_k3(x_c))          # [B, 96, 20]
        tokens = torch.cat([c1, c3], dim=1).transpose(1, 2)  # [B, 20, 192]
        tokens = self.conv_proj(tokens) + self.aa_pos_emb

        # Pre-LN Multi-Head Self-Attention
        t_norm = self.mhsa_norm1(tokens)
        attn_out, _ = self.mhsa(t_norm, t_norm, t_norm, need_weights=False)
        tokens = tokens + self.mhsa_drop(attn_out)
        tokens = tokens + self.ffn(self.mhsa_norm2(tokens))  # [B, 20, 192]

        # Attention readout + mean readout
        w = F.softmax(self.attn_pool(tokens), dim=1)         # [B, 20, 1]
        pooled = torch.sum(w * tokens, dim=1) + tokens.mean(dim=1)
        return self.out_norm(pooled)                         # [B, 192]


class EvoHybridBranch(nn.Module):
    """
    Multi-Expert Evolutionary Feature Mining Module (Hybrid MLP + CNN-MHSA).
    Processes the 4 Multimodal-AlgPro descriptors (1,410 dims total):
      - Expert 1 (Residual MLP): PSSM400        [0:400]     (400 dims -> 192)
      - Expert 2 (Residual MLP): DPC_PSSM       [400:800]   (400 dims -> 192)
      - Expert 3 (Residual MLP): DFMCA_PSSM     [800:1010]  (210 dims -> 192)
      - Expert 4 (Residual MLP): Single_Average [1010:1410] (400 dims -> 192)
      - Expert 5 (DeepAlgPro CNN + MHSA): 20x60 Amino-Acid Profile ([PSSM400, DPC_PSSM, Single_Average]
        reshaped to [B, 20, 60]) -> 192

    Supports arch modes for ablation studies:
      - "hybrid": all 5 experts (4 Residual MLPs + 1 CNN-MHSA)
      - "mlp":    only the 4 Residual MLP experts (w/o CNN-MHSA)
      - "cnn_mhsa": only the DeepAlgPro 2D Amino-Acid CNN + MHSA expert (w/o MLP experts)
    """
    def __init__(
        self,
        in_features: int = 1410,
        out_dim: int = 192,
        dropout: float = 0.25,
        arch: str = "hybrid",
    ):
        super().__init__()
        self.in_features = in_features
        self.out_dim = out_dim
        self.arch = arch.lower()

        if self.arch in ("hybrid", "mlp"):
            self.mlp_pssm400 = ResidualMLPExpert(400, out_dim=out_dim, dropout=dropout)
            self.mlp_dpc = ResidualMLPExpert(400, out_dim=out_dim, dropout=dropout)
            self.mlp_dfmca = ResidualMLPExpert(210, out_dim=out_dim, dropout=dropout)
            self.mlp_single = ResidualMLPExpert(400, out_dim=out_dim, dropout=dropout)

        if self.arch in ("hybrid", "cnn_mhsa"):
            self.cnn_mhsa_expert = AminoAcidCNN_MHSAExpert(
                in_channels=60, out_dim=out_dim, num_heads=4, dropout=dropout
            )
            self.dfmca_context = ResidualMLPExpert(210, out_dim=out_dim, dropout=dropout)

        num_tokens = 5 if self.arch == "hybrid" else (4 if self.arch == "mlp" else 2)
        self.num_tokens = num_tokens

        # Inter-modality self-attention over the active expert tokens [B, T_e, 192]
        self.token_type_emb = nn.Parameter(torch.randn(1, num_tokens, out_dim) * 0.02)
        self.inter_expert_norm = nn.LayerNorm(out_dim)
        self.inter_expert_mhsa = nn.MultiheadAttention(
            embed_dim=out_dim, num_heads=4, dropout=dropout, batch_first=True
        )

        # Softmax expert routing gate to aggregate [B, T_e, 192] -> f_p [B, 192]
        self.expert_router = nn.Sequential(
            nn.Linear(out_dim, out_dim // 2),
            nn.GELU(),
            nn.Linear(out_dim // 2, 1),
        )
        self.out_norm = nn.LayerNorm(out_dim)

        # Auxiliary classification head for Deep Multi-Task Gradient Blending
        self.aux_classifier = nn.Sequential(
            nn.LayerNorm(out_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(out_dim, 1),
        )

    def forward(self, p: torch.Tensor, return_tokens: bool = False):
        if p.dim() == 1:
            p = p.unsqueeze(0)
        bs = p.size(0)

        # Exact biological descriptor slices (400 + 400 + 210 + 400 = 1410)
        p_pssm400 = p[:, 0:400]
        p_dpc = p[:, 400:800]
        p_dfmca = p[:, 800:1010]
        p_single = p[:, 1010:1410]

        if self.arch == "mlp":
            t1 = self.mlp_pssm400(p_pssm400)
            t2 = self.mlp_dpc(p_dpc)
            t3 = self.mlp_dfmca(p_dfmca)
            t4 = self.mlp_single(p_single)
            evo_tokens = torch.stack([t1, t2, t3, t4], dim=1)  # [B, 4, 192]
        elif self.arch == "cnn_mhsa":
            aa_mat = torch.cat(
                [
                    p_pssm400.view(bs, 20, 20),
                    p_dpc.view(bs, 20, 20),
                    p_single.view(bs, 20, 20),
                ],
                dim=-1,
            )  # [B, 20, 60]
            t_cnn = self.cnn_mhsa_expert(aa_mat)
            t_dfmca = self.dfmca_context(p_dfmca)
            evo_tokens = torch.stack([t_cnn, t_dfmca], dim=1)  # [B, 2, 192]
        else:
            t1 = self.mlp_pssm400(p_pssm400)
            t2 = self.mlp_dpc(p_dpc)
            t3 = self.mlp_dfmca(p_dfmca)
            t4 = self.mlp_single(p_single)
            aa_mat = torch.cat(
                [
                    p_pssm400.view(bs, 20, 20),
                    p_dpc.view(bs, 20, 20),
                    p_single.view(bs, 20, 20),
                ],
                dim=-1,
            )  # [B, 20, 60]
            t5 = self.cnn_mhsa_expert(aa_mat)
            evo_tokens = torch.stack([t1, t2, t3, t4, t5], dim=1)  # [B, 5, 192]

        # Contextualize evolutionary tokens via inter-expert MHSA
        evo_tokens = evo_tokens + self.token_type_emb
        t_norm = self.inter_expert_norm(evo_tokens)
        attn_out, _ = self.inter_expert_mhsa(t_norm, t_norm, t_norm, need_weights=False)
        evo_tokens = evo_tokens + attn_out  # [B, T_e, 192]

        # Learned attention routing over active experts -> f_p [B, 192]
        route_w = F.softmax(self.expert_router(evo_tokens), dim=1)  # [B, T_e, 1]
        f_p = self.out_norm(torch.sum(route_w * evo_tokens, dim=1) + evo_tokens.mean(dim=1))

        if return_tokens:
            evo_logits = self.aux_classifier(f_p)
            return f_p, evo_tokens, evo_logits
        return f_p


class EvoHybridOnlyClassifier(nn.Module):
    """
    Standalone Evolutionary Classifier for Per-Component Ablation Studies:
      - arch="hybrid":   4 Residual MLPs + DeepAlgPro CNN-MHSA (Full Evolutionary Branch)
      - arch="mlp":      4 Residual MLPs only (w/o CNN-MHSA)
      - arch="cnn_mhsa": DeepAlgPro CNN-MHSA only (w/o Residual MLPs)
    """
    def __init__(
        self,
        desc_dim: int = 1410,
        hidden_dim: int = 192,
        dropout: float = 0.25,
        arch: str = "hybrid",
    ):
        super().__init__()
        self.evo_branch = EvoHybridBranch(
            in_features=desc_dim,
            out_dim=hidden_dim,
            dropout=dropout,
            arch=arch,
        )
        self.head = nn.Sequential(
            nn.LayerNorm(hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 1),
        )

    def forward(self, desc: torch.Tensor) -> torch.Tensor:
        f_p = self.evo_branch(desc)
        return self.head(f_p)


class BidirectionalCrossModalAttention(nn.Module):
    """
    True Multi-Token Bidirectional Cross-Modal Attention Fusion Module:
      - Structural queries/keys: 3 multi-view structural tokens derived from f_g [B, 3, 192]
      - Evolutionary queries/keys: T_e descriptor expert tokens [B, T_e, 192]
      - 4 heads (head_dim = 48, scale = 1/sqrt(48)) and exact identity residuals at gate=0.
    """
    def __init__(self, dim: int = 192, num_heads: int = 4, dropout: float = 0.2):
        super().__init__()
        self.dim = dim
        self.num_heads = num_heads
        self.head_dim = dim // num_heads  # 48
        self.scale = self.head_dim ** -0.5

        # Expand f_g [B, 192] into 3 complementary structural sub-view tokens [B, 3, 192]
        self.struct_view_proj = nn.Linear(dim, dim * 3)
        self.norm_g = nn.LayerNorm(dim)
        self.norm_p = nn.LayerNorm(dim)

        # g -> p cross-attention (Structural queries attend to Evolutionary expert tokens)
        self.wq_g = nn.Linear(dim, dim, bias=False)
        self.wk_p = nn.Linear(dim, dim, bias=False)
        self.wv_p = nn.Linear(dim, dim, bias=False)
        self.wo_g = nn.Sequential(nn.Linear(dim, dim), nn.Dropout(dropout))

        # p -> g cross-attention (Evolutionary expert tokens attend to Structural tokens)
        self.wq_p = nn.Linear(dim, dim, bias=False)
        self.wk_g = nn.Linear(dim, dim, bias=False)
        self.wv_g = nn.Linear(dim, dim, bias=False)
        self.wo_p = nn.Sequential(nn.Linear(dim, dim), nn.Dropout(dropout))

        self.attn_drop = nn.Dropout(dropout)

        # Zero-initialized learnable modality gates (exact identity preservation at epoch 0)
        self.gate_g = nn.Parameter(torch.zeros(1))
        self.gate_p = nn.Parameter(torch.zeros(1))

    def _mh_cross_attn(
        self, q_tokens: torch.Tensor, kv_tokens: torch.Tensor, wq, wk, wv, wo
    ) -> torch.Tensor:
        bs, t_q, _ = q_tokens.shape
        t_k = kv_tokens.size(1)

        q = wq(q_tokens).view(bs, t_q, self.num_heads, self.head_dim).transpose(1, 2)   # [B, H, T_q, d]
        k = wk(kv_tokens).view(bs, t_k, self.num_heads, self.head_dim).transpose(1, 2)  # [B, H, T_k, d]
        v = wv(kv_tokens).view(bs, t_k, self.num_heads, self.head_dim).transpose(1, 2)  # [B, H, T_k, d]

        scores = torch.matmul(q, k.transpose(-1, -2)) * self.scale                      # [B, H, T_q, T_k]
        attn = self.attn_drop(F.softmax(scores, dim=-1))
        ctx = torch.matmul(attn, v).transpose(1, 2).contiguous().view(bs, t_q, self.dim)
        return wo(ctx)                                                                  # [B, T_q, D]

    def forward(
        self,
        f_g: torch.Tensor,
        f_p: torch.Tensor,
        evo_tokens: torch.Tensor = None,
    ) -> torch.Tensor:
        bs = f_g.size(0)
        if evo_tokens is None:
            evo_tokens = f_p.unsqueeze(1)

        g_tokens = f_g.unsqueeze(1) + 0.1 * self.struct_view_proj(f_g).view(bs, 3, self.dim)
        g_norm = self.norm_g(g_tokens)     # [B, 3, 192]
        p_norm = self.norm_p(evo_tokens)   # [B, T_e, 192]

        delta_g = self._mh_cross_attn(
            g_norm, p_norm, self.wq_g, self.wk_p, self.wv_p, self.wo_g
        ).mean(dim=1)  # [B, 192]
        delta_p = self._mh_cross_attn(
            p_norm, g_norm, self.wq_p, self.wk_g, self.wv_g, self.wo_p
        ).mean(dim=1)  # [B, 192]

        f_g_prime = f_g + torch.tanh(self.gate_g) * delta_g  # [B, 192]
        f_p_prime = f_p + torch.tanh(self.gate_p) * delta_p  # [B, 192]

        return torch.cat([f_g_prime, f_p_prime], dim=-1)     # [B, 384]


class MultimodalGTHybridModel(nn.Module):
    """
    End-to-End Dual-Branch Multimodal Allergenicity Framework with Configurable Ablation Switches:
      - evo_arch="hybrid" | "mlp" | "cnn_mhsa"
      - use_cross_attn=True (BidirectionalCrossModalAttention) | False (Direct Concatenation ablation)
    """
    def __init__(
        self,
        prot_dim: int = 1024,
        gt_hidden_dim: int = 256,
        desc_dim: int = 1410,
        hidden_dim: int = 192,
        dropout: float = 0.2,
        evo_arch: str = "hybrid",
        use_cross_attn: bool = True,
        modality_drop_prob: float = 0.15,
    ):
        super().__init__()
        self.use_cross_attn = use_cross_attn
        self.modality_drop_prob = modality_drop_prob

        self.gt_branch = ProtT5GraphTransformer(
            prot_dim=prot_dim,
            hidden_dim=gt_hidden_dim,
            out_dim=hidden_dim,
            num_heads=4,
            dropout=dropout,
        )
        self.evo_branch = EvoHybridBranch(
            in_features=desc_dim,
            out_dim=hidden_dim,
            dropout=max(dropout, 0.25),
            arch=evo_arch,
        )
        self.fusion_module = BidirectionalCrossModalAttention(
            dim=hidden_dim,
            num_heads=4,
            dropout=dropout,
        )

        # Cross-modal interaction head with bilinear-style Hadamard product [f_g', f_p', f_g' * f_p']
        self.fusion_proj = nn.Sequential(
            nn.Linear(hidden_dim * 3, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.GELU(),
            nn.Dropout(p=dropout),
        )
        self.classifier = nn.Linear(hidden_dim, 1)

        # Learnable logit combination weights
        self.fusion_logit_scale = nn.Parameter(torch.tensor(0.35, dtype=torch.float32))
        self.evo_logit_scale = nn.Parameter(torch.tensor(0.25, dtype=torch.float32))

    def forward(
        self,
        x: torch.Tensor,
        residue_mask: torch.Tensor,
        desc: torch.Tensor,
        contact_map: torch.Tensor = None,
        return_aux: bool = False,
    ):
        # 1. Structural Graph Transformer branch (keeps gt_logits active!)
        gt_logits, x_recon, f_g = self.gt_branch(x, residue_mask, contact_map=contact_map)

        # 2. Multi-Expert Evolutionary branch
        f_p, evo_tokens, evo_logits = self.evo_branch(desc, return_tokens=True)

        if self.training and self.modality_drop_prob > 0.0:
            keep_mask = (
                torch.rand((f_p.size(0), 1), device=f_p.device) >= self.modality_drop_prob
            ).float()
        else:
            keep_mask = 1.0

        # 3. Cross-Modal Attention Fusion (or Direct Concatenation when use_cross_attn=False)
        if self.use_cross_attn:
            f_fusion = self.fusion_module(f_g, f_p, evo_tokens=evo_tokens)
            f_g_prime, f_p_prime = f_fusion.chunk(2, dim=-1)
        else:
            f_g_prime, f_p_prime = f_g, f_p
            f_fusion = torch.cat([f_g_prime, f_p_prime], dim=-1)

        interaction = torch.cat([f_g_prime, f_p_prime, f_g_prime * f_p_prime], dim=-1)  # [B, 576]
        fusion_hidden = self.fusion_proj(interaction)
        fusion_logits = self.classifier(fusion_hidden)

        # 4. Calibrated Logit Residual Ensemble anchored on gt_logits
        w_fus = F.softplus(self.fusion_logit_scale)
        w_evo = F.softplus(self.evo_logit_scale)
        logits = gt_logits + keep_mask * (w_fus * fusion_logits + w_evo * evo_logits)

        if return_aux:
            return logits, x_recon, f_fusion, gt_logits, evo_logits
        return logits, x_recon, f_fusion