import math
import torch
import torch.nn as nn
import torch.nn.functional as F


class NodeAttentionPreprocessing(nn.Module):
    # Refines initial ProtT5 residue node features X [B, L, 1024] using a two-layer fully connected attention network before graph transformer layers.
    def __init__(self, in_dim: int = 1024, hidden_dim: int = 256):
        super().__init__()
        self.attn_mlp = nn.Sequential(
            nn.Linear(in_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 1),
            nn.Sigmoid(),
        )

    def forward(self, x: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        scores = self.attn_mlp(x)  # [B, L, 1]
        scores = scores * mask.unsqueeze(-1).float()
        return x * scores


class StructuralPositionalEncoding(nn.Module):
    """
    Encodes residue sequence positions and local adjacency topology into:
    1. Node-level sinusoidal + local degree positional embeddings added to X_hat.
    2. Pairwise structural & relative-distance attention bias matrix B_struct for global self-attention (distinguishing virtual token connections, self-loops |i-j|=0, adjacent residue edges |i-j|=1, and clipped relative distances).
    """
    def __init__(self, dim: int = 256, max_len: int = 1024, max_rel_dist: int = 16, num_heads: int = 4):
        super().__init__()
        self.max_rel_dist = max_rel_dist

        # Sinusoidal positional encoding table [1, max_len, dim]
        pe = torch.zeros(max_len, dim)
        position = torch.arange(0, max_len, dtype=torch.float32).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, dim, 2, dtype=torch.float32) * (-math.log(10000.0) / dim))
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        self.register_buffer("pe", pe.unsqueeze(0), persistent=False)
        # Learnable scale (init 0.1) to avoid overpowering calibrated ProtT5 embeddings
        self.pe_scale = nn.Parameter(torch.tensor(0.1, dtype=torch.float32))

        # Learnable node degree embedding (degree 1 for N/C-termini, degree 2 for internal residues)
        self.degree_emb = nn.Embedding(3, dim)

        # Learnable pairwise structural bias embeddings for global attention
        # Bucket 0: |i-j|=0 (self-loop)
        # Bucket 1: |i-j|=1 (direct adjacent residue bond E)
        # Buckets 2..max_rel_dist: relative sequence distance |i-j|
        # Bucket max_rel_dist + 1: virtual graph token <-> residue global connection
        # Bucket max_rel_dist + 2: optional 3D spatial contact edge
        self.rel_bias_4h = nn.Embedding(max_rel_dist + 3, num_heads)
        self.rel_bias_1h = nn.Embedding(max_rel_dist + 3, 1)

    def augment_nodes(self, x_hat: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        batch_size, seq_len, _ = x_hat.shape
        pos_enc = self.pe_scale * self.pe[:, :seq_len, :]

        # Compute residue node degree in sequence graph (internal nodes = 2, terminal nodes = 1)
        lengths = mask.sum(dim=1)  # [B]
        degrees = torch.full((batch_size, seq_len), 2, dtype=torch.long, device=x_hat.device)
        degrees[:, 0] = 1
        for b in range(batch_size):
            last_idx = max(int(lengths[b].item()) - 1, 0)
            degrees[b, last_idx] = 1
        degrees = degrees * mask.long()

        out = x_hat + pos_enc + self.degree_emb(degrees)
        return out * mask.unsqueeze(-1).float()

    def get_attention_bias(
        self, seq_len: int, device: torch.device, contact_map: torch.Tensor = None
    ):
        # Builds pairwise structural bias matrices for (1 + seq_len) tokens (index 0 = virtual graph token, indices 1..seq_len = residue nodes).
        # Returns bias_4h: [1, 4, 1+L, 1+L] for Layers 1-3 and bias_1h: [1, 1, 1+L, 1+L] for Layer 4
        idx = torch.arange(seq_len, device=device)
        rel_dist = torch.abs(idx.unsqueeze(0) - idx.unsqueeze(1)).clamp(max=self.max_rel_dist)

        # Full bucket matrix of size [1 + L, 1 + L] initialized to virtual token bucket (max_rel_dist + 1)
        v_bucket = self.max_rel_dist + 1
        contact_bucket = self.max_rel_dist + 2

        if contact_map is None:
            buckets = torch.full((1 + seq_len, 1 + seq_len), v_bucket, dtype=torch.long, device=device)
            buckets[0, 0] = 0
            buckets[1:, 1:] = rel_dist

            bias_4h = self.rel_bias_4h(buckets).permute(2, 0, 1).unsqueeze(0)  # [1, 4, 1+L, 1+L]
            bias_1h = self.rel_bias_1h(buckets).permute(2, 0, 1).unsqueeze(0)  # [1, 1, 1+L, 1+L]
            return bias_4h, bias_1h

        # Optional 3D contact map [B, L, L] routing for non-local spatial contacts (|i-j| > 1)
        bs = contact_map.size(0)
        buckets = torch.full((bs, 1 + seq_len, 1 + seq_len), v_bucket, dtype=torch.long, device=device)
        buckets[:, 0, 0] = 0
        rel_expanded = rel_dist.unsqueeze(0).expand(bs, -1, -1).clone()
        non_local_contacts = (contact_map > 0) & (rel_expanded > 1)
        rel_expanded[non_local_contacts] = contact_bucket
        buckets[:, 1:, 1:] = rel_expanded

        bias_4h = self.rel_bias_4h(buckets).permute(0, 3, 1, 2)  # [B, 4, 1+L, 1+L]
        bias_1h = self.rel_bias_1h(buckets).permute(0, 3, 1, 2)  # [B, 1, 1+L, 1+L]
        return bias_4h, bias_1h


class GraphTransformerLayer(nn.Module):
    # Global Self-Attention Graph Transformer Layer
    # Incorporating structural/positional attention biases, LayerNorm, optional ELU activation (Layers 1-3), and Residual Connections.
    # Upgraded with Shi et al. (UniMP / PyG TransformerConv) Gated Residual (beta=True) and Graphormer Pre-LN stabilization.
    def __init__(
        self,
        in_dim: int,
        head_dim: int,
        num_heads: int = 4,
        concat: bool = True,
        use_elu: bool = True,
        dropout: float = 0.2,
        beta: bool = True,
    ):
        super().__init__()
        self.num_heads = num_heads
        self.head_dim = head_dim
        self.concat = concat
        self.out_dim = head_dim * num_heads if concat else head_dim
        self.scale = 1.0 / math.sqrt(head_dim)
        self.use_beta = beta

        # Pre-LayerNorm (Graphormer Ying et al.) for smooth gradient flow without premature early stopping
        self.pre_norm = nn.LayerNorm(in_dim)

        self.q_proj = nn.Linear(in_dim, num_heads * head_dim, bias=True)
        self.k_proj = nn.Linear(in_dim, num_heads * head_dim, bias=True)
        self.v_proj = nn.Linear(in_dim, num_heads * head_dim, bias=True)
        # Linear output projection (W_O) to mix concatenated attention heads
        self.out_proj = nn.Linear(self.out_dim, self.out_dim, bias=True)

        # Root weight & Gated Residual connection (Shi et al. UniMP / PyG TransformerConv beta=True)
        self.lin_skip = nn.Linear(in_dim, self.out_dim, bias=True)
        if self.use_beta:
            self.lin_beta = nn.Linear(3 * self.out_dim, 1, bias=False)

        self.attn_drop = nn.Dropout(dropout)
        self.res_drop = nn.Dropout(dropout)
        self.layer_norm = nn.LayerNorm(self.out_dim)
        self.act = nn.ELU() if use_elu else nn.Identity()

        # Compact channel-mixing FFN sublayer with residual connection
        self.ffn_norm = nn.LayerNorm(self.out_dim)
        self.ffn = nn.Sequential(
            nn.Linear(self.out_dim, self.out_dim * 2),
            nn.ELU() if use_elu else nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(self.out_dim * 2, self.out_dim),
            nn.Dropout(dropout),
        )

    def forward(
        self,
        h: torch.Tensor,
        struct_bias: torch.Tensor,
        full_mask: torch.Tensor,
    ) -> torch.Tensor:
        # h: [B, 1+L, in_dim]
        # struct_bias: [1, num_heads, 1+L, 1+L]
        # full_mask: [B, 1+L] boolean mask (True for virtual token & valid residues, False for pad)
        batch_size, total_len, _ = h.shape

        h_norm = self.pre_norm(h)
        q = self.q_proj(h_norm).view(batch_size, total_len, self.num_heads, self.head_dim).transpose(1, 2)
        k = self.k_proj(h_norm).view(batch_size, total_len, self.num_heads, self.head_dim).transpose(1, 2)
        v = self.v_proj(h_norm).view(batch_size, total_len, self.num_heads, self.head_dim).transpose(1, 2)

        # Global self-attention scores + structural/positional bias
        attn_logits = torch.matmul(q, k.transpose(-1, -2)) * self.scale + struct_bias

        # Mask out padded key positions
        key_mask = full_mask.unsqueeze(1).unsqueeze(2)  # [B, 1, 1, 1+L]
        attn_logits = attn_logits.masked_fill(~key_mask, -1e4)

        attn_probs = F.softmax(attn_logits, dim=-1)
        attn_probs = self.attn_drop(attn_probs)

        context = torch.matmul(attn_probs, v)  # [B, num_heads, 1+L, head_dim]
        if self.concat:
            context = context.transpose(1, 2).contiguous().view(batch_size, total_len, self.out_dim)
        else:
            context = context.mean(dim=1)  # [B, 1+L, out_dim]

        out_msg = self.res_drop(self.out_proj(context))
        x_r = self.lin_skip(h)

        # Shi et al. (UniMP / TransformerConv) Gated Residual: beta_i = sigmoid(W_beta [out_msg, x_r, out_msg - x_r])
        if self.use_beta:
            beta_gate = torch.sigmoid(self.lin_beta(torch.cat([out_msg, x_r, out_msg - x_r], dim=-1)))
            fused = beta_gate * x_r + (1.0 - beta_gate) * out_msg
        else:
            fused = x_r + out_msg

        # Eqs. (11)-(12): LayerNorm(Conv) + Residual, followed by ELU on Layers 1-3
        out = self.act(self.layer_norm(fused))
        out = out + self.ffn(self.ffn_norm(out))
        return out * full_mask.unsqueeze(-1).float()


class GlobalAttentionReadout(nn.Module):
    """
    Eq. (13) of Jia et al.: Aggregates node-level features H_4 [B, L, 192] into a
    graph-level structural vector F_attn [B, 192] using global attention weights
    alpha_i = Softmax(GlobalPool(H_4(i))).
    """
    def __init__(self, node_dim: int = 192):
        super().__init__()
        self.global_pool = nn.Sequential(
            nn.Linear(node_dim, node_dim // 2),
            nn.ReLU(),
            nn.Linear(node_dim // 2, 1),
        )

    def forward(self, h_nodes: torch.Tensor, residue_mask: torch.Tensor) -> torch.Tensor:
        attn_logits = self.global_pool(h_nodes)  # [B, L, 1]
        attn_logits = attn_logits.masked_fill(~residue_mask.unsqueeze(-1), -1e4)
        alpha = F.softmax(attn_logits, dim=1)  # [B, L, 1]
        return torch.sum(alpha * h_nodes, dim=1)  # [B, 192]


class ProtT5GraphTransformer(nn.Module):
    """
    4-Layer ProtT5 + Graph Transformer Architecture:
    - NodeAttentionPreprocessing (Eq. 9)
    - Bottleneck Input Projection (1024 -> 256) to prevent early overfitting on fold splits
    - Structural & Positional Encoding + Learnable Virtual Graph Token
    - Layers 1, 2, 3: 4-Head Global Graph Transformer + Gated Residual (beta=True) + LayerNorm + ELU (256-dim)
    - Layer 4: 1-Head Global Graph Transformer + Gated Residual (beta=True) + LayerNorm (192-dim)
    - Tri-Modal Graph Readout (Virtual Token + Paper Eq. 13 Global Attention Pooling + Masked Max-Pool) -> F_g [B, 192]
    - Classifier Head & Self-Supervised Node Reconstruction Branch
    """
    def __init__(
        self,
        prot_dim: int = 1024,
        hidden_dim: int = 256,
        out_dim: int = 192,
        num_heads: int = 4,
        dropout: float = 0.2,
    ):
        super().__init__()
        # Bottleneck width (256 by default; if 512 is passed from legacy script, still works seamlessly)
        bottleneck_dim = 256 if hidden_dim == 512 else hidden_dim
        head_dim = bottleneck_dim // num_heads  # 256 // 4 = 64

        # Node Attention Preprocessing (Eq. 9)
        self.node_attention = NodeAttentionPreprocessing(in_dim=prot_dim)

        # Bottleneck input projection (1024 -> 256) to regularize high-dim PLM features
        self.input_proj = nn.Sequential(
            nn.Linear(prot_dim, bottleneck_dim),
            nn.LayerNorm(bottleneck_dim),
            nn.Dropout(dropout),
        )

        # Structural/Positional Biases & Learnable Virtual Graph Token
        self.struct_pos = StructuralPositionalEncoding(
            dim=bottleneck_dim, max_len=1024, max_rel_dist=16, num_heads=num_heads
        )
        self.virtual_token = nn.Parameter(torch.randn(1, 1, bottleneck_dim) * 0.02)

        # Layers 1, 2, 3: 4-Head Global Self-Attention + Gated Residual + LayerNorm + ELU (Eqs. 10-11)
        self.gt_layer1 = GraphTransformerLayer(
            in_dim=bottleneck_dim, head_dim=head_dim, num_heads=num_heads, concat=True, use_elu=True, dropout=dropout, beta=True
        )
        self.gt_layer2 = GraphTransformerLayer(
            in_dim=bottleneck_dim, head_dim=head_dim, num_heads=num_heads, concat=True, use_elu=True, dropout=dropout, beta=True
        )
        self.gt_layer3 = GraphTransformerLayer(
            in_dim=bottleneck_dim, head_dim=head_dim, num_heads=num_heads, concat=True, use_elu=True, dropout=dropout, beta=True
        )

        # Layer 4: Single-Head Global Self-Attention + LayerNorm + Projection Residual -> 192-dim (Eq. 12)
        self.gt_layer4 = GraphTransformerLayer(
            in_dim=bottleneck_dim, head_dim=out_dim, num_heads=1, concat=False, use_elu=False, dropout=dropout, beta=True
        )

        # Paper Eq. (13) Global Attention Readout + Hybrid Virtual Token & Masked Max-Pool Readout -> F_g [B, 192]
        self.global_attn_pool = GlobalAttentionReadout(node_dim=out_dim)
        self.readout_proj = nn.Sequential(
            nn.Linear(out_dim * 3, out_dim),
            nn.LayerNorm(out_dim),
            nn.ELU(),
            nn.Dropout(dropout),
        )

        # Downstream Allergenicity Classification Head
        self.classifier = nn.Sequential(
            nn.Linear(out_dim, out_dim),
            nn.ReLU(),
            nn.Dropout(p=dropout),
            nn.Linear(out_dim, 1),
        )

        # Self-Supervised Node Feature Reconstruction Branch (192 -> 1024)
        self.reconstructor = nn.Sequential(
            nn.Linear(out_dim, out_dim * 2),
            nn.ReLU(),
            nn.Linear(out_dim * 2, prot_dim),
        )

    def forward(
        self,
        x: torch.Tensor,
        residue_mask: torch.Tensor,
        contact_map: torch.Tensor = None,
    ):
        # x: Padded ProtT5 residue features [B, L, 1024]
        # residue_mask: Boolean mask [B, L] (True = valid residue, False = padding)
        # logits: [B, 1] classification logits
        # x_recon: [B, L, 1024] reconstructed residue features
        # f_g: [B, 192] graph-level representation (ready for Cross-Modal Fusion)
        batch_size, seq_len, _ = x.shape

        # 1. Node Attention Preprocessing (Eq. 9), Bottleneck Projection, & Structural/Positional Augmentation
        x_hat = self.node_attention(x, residue_mask)
        x_proj = self.input_proj(x_hat) * residue_mask.unsqueeze(-1).float()
        x_aug = self.struct_pos.augment_nodes(x_proj, residue_mask)

        # 2. Prepend Learnable Virtual Graph Token -> [B, 1 + L, 256]
        v_tok = self.virtual_token.expand(batch_size, 1, -1)
        z0 = torch.cat([v_tok, x_aug], dim=1)

        v_mask = torch.ones((batch_size, 1), dtype=torch.bool, device=x.device)
        full_mask = torch.cat([v_mask, residue_mask], dim=1)  # [B, 1 + L]

        bias_4h, bias_1h = self.struct_pos.get_attention_bias(
            seq_len, x.device, contact_map=contact_map
        )

        # 3. 4-Layer Graph Transformer Forward Pass (Eqs. 10-12)
        h1 = self.gt_layer1(z0, bias_4h, full_mask)  # [B, 1 + L, 256]
        h2 = self.gt_layer2(h1, bias_4h, full_mask)  # [B, 1 + L, 256]
        h3 = self.gt_layer3(h2, bias_4h, full_mask)  # [B, 1 + L, 256]
        h4 = self.gt_layer4(h3, bias_1h, full_mask)  # [B, 1 + L, 192]

        # 4. Extract Virtual Graph Token + Paper Eq. (13) Global Attention Pooling + Masked Max-Pool
        v_out = h4[:, 0, :]       # [B, 192]
        h4_nodes = h4[:, 1:, :]   # [B, L, 192]

        attn_pool = self.global_attn_pool(h4_nodes, residue_mask)  # [B, 192] (Paper Eq. 13)
        nodes_masked = h4_nodes.masked_fill(~residue_mask.unsqueeze(-1), -1e4)
        max_pool = nodes_masked.max(dim=1).values                  # [B, 192]

        # Residual fusion into unified 192-dim graph representation F_g
        f_g = v_out + attn_pool + self.readout_proj(torch.cat([v_out, attn_pool, max_pool], dim=-1))  # [B, 192]

        # 5. Classification & Self-Supervised Node Feature Reconstruction
        logits = self.classifier(f_g)            # [B, 1]
        x_recon = self.reconstructor(h4_nodes)   # [B, L, 1024]

        return logits, x_recon, f_g


class LabelSmoothedFocalLoss(nn.Module):
    # Label-Smoothed Focal Loss (Paper Eqs. 24-25)
    def __init__(self, alpha: float = 0.5, gamma: float = 1.0, smoothing: float = 0.1):
        super().__init__()
        self.alpha = alpha
        self.gamma = gamma
        self.smoothing = smoothing

    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        targets = targets.view_as(logits).float()
        p = torch.sigmoid(logits).clamp(min=1e-7, max=1.0 - 1e-7)
        y_hat = targets * (1.0 - self.smoothing) + 0.5 * self.smoothing

        term_pos = y_hat * torch.log(p) * torch.pow(1.0 - p, self.gamma)
        term_neg = (1.0 - y_hat) * torch.log(1.0 - p) * torch.pow(p, self.gamma)
        return (-(self.alpha * term_pos + (1.0 - self.alpha) * term_neg)).mean()


def masked_l1_reconstruction_loss(
    x_recon: torch.Tensor, x_true: torch.Tensor, residue_mask: torch.Tensor
) -> torch.Tensor:
    # Computes the Mean Absolute Error (MAE) strictly over valid (non-padded) amino acid residues in the batch.
    mask_3d = residue_mask.unsqueeze(-1).float()  # [B, L, 1]
    abs_diff = torch.abs(x_recon - x_true) * mask_3d
    denom = (mask_3d.sum() * x_true.size(-1)).clamp(min=1.0)
    return abs_diff.sum() / denom