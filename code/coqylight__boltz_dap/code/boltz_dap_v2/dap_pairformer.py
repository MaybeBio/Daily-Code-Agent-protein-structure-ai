"""
DAP-aware PairformerLayer for Boltz 2 (main pairformer with sequence attention).

Flow per layer (row-scattered z [B, N/dap, N, D]):
  z → tri_mul_out(z)         — row-scattered, DAP-wrapped
  z → row_to_col → z_col → tri_mul_in(z_col) → col_to_row → z
  z → DAPTriAttStart(z)      — scattered, gathers only small bias
  z → DAPTriAttEnd(z)        — internally uses row_to_col for ending
  z → transition_z(z)        — pointwise
  s, z → seq_attention       — gathers only pair bias (H channels), not full z
"""

import torch
from torch import Tensor, nn
from typing import Callable, Optional
import pathlib

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from boltz_distributed.comm import (
    row_to_col, col_to_row, gather, scatter,
    row_to_col_destructive, col_to_row_streamed,
)
from boltz_distributed.core import get_dap_size, get_dap_rank

from dap_trimul import DAPTriMulOut, DAPTriMulIn
from dap_tri_att import DAPTriAttStart, DAPTriAttEnd
from dap_pairformer_noseq import get_dropout_mask


class DAPPairformerLayer(nn.Module):
    """DAP wrapper for PairformerLayer (with sequence attention).

    z stays row-scattered [B, N/dap, N, D] throughout pair ops.
    Sequence attention gathers only the H-channel pair bias, not full z.
    """

    def __init__(self, original_layer):
        super().__init__()
        self.tri_mul_out = DAPTriMulOut(original_layer.tri_mul_out)
        self.tri_mul_in = DAPTriMulIn(original_layer.tri_mul_in)
        self.tri_att_start = DAPTriAttStart(original_layer.tri_att_start)
        self.tri_att_end = DAPTriAttEnd(original_layer.tri_att_end)
        self.transition_z = original_layer.transition_z

        # Sequence attention (uses pair bias from z)
        self.pre_norm_s = original_layer.pre_norm_s
        self.attention = original_layer.attention
        self.transition_s = original_layer.transition_s
        self.s_post_norm = original_layer.s_post_norm

        self.dropout = original_layer.dropout

    def forward(
        self,
        s: Tensor,
        z: Tensor,
        mask: Tensor,
        pair_mask: Tensor,
        chunk_size_tri_attn: Optional[int] = None,
        use_kernels: bool = False,
        use_cuequiv_mul: bool = False,
        use_cuequiv_attn: bool = False,
        layer_idx: int = -1,
        chunk_size_transition_z: Optional[int] = None,
        boundary_callback: Optional[Callable[[str, Tensor], None]] = None,
    ) -> tuple[Tensor, Tensor]:
        """Forward.

        s: [B, N, 384] — replicated
        z: [B, N/dap, N, D] — row-scattered
        mask: [B, N] — replicated
        pair_mask: [B, N/dap, N] — row-scattered
        """
        dap_size = get_dap_size()
        dap_rank = get_dap_rank()
        original_N = z.shape[2]

        # Sub-op checkpointing: only for layer 0
        # NOTE: gather() is NCCL collective — ALL ranks must call it!
        _subop_dir = os.environ.get("BOLTZ_SAVE_SUBOP_CKPT", "")
        _do_subop = bool(_subop_dir) and layer_idx == 0
        if layer_idx == 0 and dap_rank == 0:
            print(f"[SUBOP-DEBUG] layer_idx={layer_idx} _subop_dir='{_subop_dir}' _do_subop={_do_subop}", flush=True)
        if _do_subop and dap_rank == 0:
            _subop_path = pathlib.Path(_subop_dir)
            _subop_path.mkdir(parents=True, exist_ok=True)

        def _save_z(name):
            """Gather scattered z (collective!) and save on rank 0."""
            if not _do_subop:
                return
            # ALL ranks must call gather (NCCL collective)
            z_full = gather(z.contiguous(), dim=1, original_size=original_N)
            if dap_rank == 0:
                torch.save(z_full.detach().cpu(), pathlib.Path(_subop_dir) / f"{name}.pt")
            del z_full

        def _mem(label):
            pass  # Disabled: use [TIMELINE] logs in dap_trunk.py instead

        _mem("start")

        # === Pair operations (all on scattered z) ===

        # 1. TriMulOut
        dropout = get_dropout_mask(
            self.dropout, z, self.training, stock_pair_size=original_N
        )
        def emit_tri_mul_out(name: str, value: Tensor) -> None:
            if boundary_callback is not None:
                boundary_callback(f"tri_mul_out_{name}", value)

        if self.training and torch.is_grad_enabled():
            z = z + dropout * self.tri_mul_out(
                z,
                mask=pair_mask,
                use_kernels=use_kernels,
                boundary_callback=emit_tri_mul_out,
            )
        else:
            z = self.tri_mul_out.forward_with_residual(
                z,
                pair_mask,
                dropout,
                use_kernels=use_kernels,
                boundary_callback=emit_tri_mul_out,
            )
        _mem("after tri_mul_out")
        if boundary_callback is not None:
            boundary_callback("z_after_tri_mul_out", z)
        _save_z("after_trimul_out")

        # 2. TriMulIn (col-scattered round-trip)
        bounded_transport = z.shape[0] == 1 and not self.training and not torch.is_grad_enabled()
        if bounded_transport:
            z_col = row_to_col_destructive(z)
        else:
            z_col = row_to_col(z)
        pair_mask_col = row_to_col(pair_mask.unsqueeze(-1)).squeeze(-1)
        dropout = get_dropout_mask(
            self.dropout, z_col, self.training, stock_pair_size=original_N
        )
        if self.training and torch.is_grad_enabled():
            z_col = z_col + dropout * self.tri_mul_in(
                z_col,
                mask=pair_mask_col,
                use_kernels=use_kernels,
            )
        else:
            z_col = self.tri_mul_in.forward_with_residual(
                z_col,
                pair_mask_col,
                dropout,
                use_kernels=use_kernels,
            )
        if bounded_transport:
            z.set_(col_to_row_streamed(z_col, original_size=original_N))
        else:
            z_row = col_to_row(z_col)
            if z_row.shape[2] > original_N:
                z_row = z_row[:, :, :original_N, :]
            if self.training and torch.is_grad_enabled():
                z = z_row
            else:
                z.copy_(z_row)
                del z_row
        del z_col, pair_mask_col, dropout
        _mem("after tri_mul_in")
        if boundary_callback is not None:
            boundary_callback("z_after_tri_mul_in", z)
        _save_z("after_trimul_in")

        # 3. TriAttStart (scattered, gathers only bias)
        tri_att_use_kernels = use_kernels and not (
            dap_size > 1 and not self.training and not torch.is_grad_enabled()
        )
        dropout = get_dropout_mask(
            self.dropout, z, self.training, stock_pair_size=original_N
        )
        z = self.tri_att_start.forward_with_residual(
            z,
            pair_mask,
            dropout,
            chunk_size=chunk_size_tri_attn,
            use_kernels=tri_att_use_kernels,
        )
        _mem("after tri_att_start")
        if boundary_callback is not None:
            boundary_callback("z_after_tri_att_start", z)
        _save_z("after_triatt_start")

        # 4. TriAttEnd (internally handles row_to_col)
        dropout = get_dropout_mask(
            self.dropout,
            z,
            self.training,
            columnwise=True,
            stock_pair_size=original_N,
        )
        z = self.tri_att_end.forward_with_residual(
            z,
            pair_mask,
            dropout,
            chunk_size=chunk_size_tri_attn,
            use_kernels=tri_att_use_kernels,
        )
        _mem("after tri_att_end")
        if boundary_callback is not None:
            boundary_callback("z_after_tri_att_end", z)
        _save_z("after_triatt_end")

        # 5. Transition (pointwise, chunked to avoid 4×D expansion spike)
        if not self.training and not torch.is_grad_enabled():
            z = self.transition_z.forward_with_residual(z, chunk_size_transition_z)
        else:
            transition_update = self.transition_z(z, chunk_size_transition_z)
            if self.training and torch.is_grad_enabled():
                z = z + transition_update
            else:
                z.add_(transition_update)
            del transition_update
        _mem("after transition_z")
        if boundary_callback is not None:
            boundary_callback("z_after_transition", z)

        # === Sequence attention ===
        with torch.autocast("cuda", enabled=False):
            s_normed = self.pre_norm_s(s.float())
            B = s_normed.shape[0]
            attn_mod = self.attention
            q = attn_mod.proj_q(s_normed).view(B, -1, attn_mod.num_heads, attn_mod.head_dim)
            k = attn_mod.proj_k(s_normed).view(B, -1, attn_mod.num_heads, attn_mod.head_dim)
            v = attn_mod.proj_v(s_normed).view(B, -1, attn_mod.num_heads, attn_mod.head_dim)
            g = attn_mod.proj_g(s_normed).sigmoid()
            if boundary_callback is not None:
                boundary_callback("sequence_s_normed", s_normed)
                boundary_callback("sequence_queries", q)
                boundary_callback("sequence_keys", k)
                boundary_callback("sequence_values", v)
                boundary_callback("sequence_gate", g)

            if dap_size > 1 and not self.training and not torch.is_grad_enabled():
                pair_bias_local = attn_mod.proj_z(z.float())
                local_rows = z.shape[1]
                row_offset = dap_rank * local_rows
                valid_rows = max(0, min(local_rows, original_N - row_offset))
                q_chunk = int(os.environ.get("BOLTZ_SEQ_ATTN_Q_CHUNK", "64"))
                q_chunk = min(max(1, q_chunk), max(1, valid_rows))
                local_pre_projection = torch.zeros(
                    B,
                    local_rows,
                    attn_mod.c_s,
                    dtype=s_normed.dtype,
                    device=s_normed.device,
                )
                diagnostic_logits = diagnostic_probabilities = None
                diagnostic_values = None
                if boundary_callback is not None:
                    diagnostic_logits = torch.empty(
                        B,
                        attn_mod.num_heads,
                        valid_rows,
                        original_N,
                        dtype=torch.float32,
                        device=s_normed.device,
                    )
                    diagnostic_probabilities = torch.empty_like(diagnostic_logits)
                    diagnostic_values = torch.empty(
                        B,
                        valid_rows,
                        attn_mod.num_heads,
                        attn_mod.head_dim,
                        dtype=v.dtype,
                        device=v.device,
                    )

                for q_start in range(0, valid_rows, q_chunk):
                    q_end = min(q_start + q_chunk, valid_rows)
                    global_start = row_offset + q_start
                    global_end = row_offset + q_end
                    q_part = q[:, global_start:global_end]
                    g_part = g[:, global_start:global_end]
                    pair_bias_part = pair_bias_local[:, :, q_start:q_end].float()

                    attn = torch.einsum("bihd,bjhd->bhij", q_part.float(), k.float())
                    attn = attn / (attn_mod.head_dim ** 0.5) + pair_bias_part
                    attn = attn + (1 - mask[:, None, None].float()) * -attn_mod.inf
                    if diagnostic_logits is not None:
                        diagnostic_logits[:, :, q_start:q_end].copy_(attn)
                    attn = attn.softmax(dim=-1)
                    if diagnostic_probabilities is not None:
                        diagnostic_probabilities[:, :, q_start:q_end].copy_(attn)
                    o_part = torch.einsum(
                        "bhij,bjhd->bihd",
                        attn,
                        v.float(),
                    ).to(v.dtype)
                    if diagnostic_values is not None:
                        diagnostic_values[:, q_start:q_end].copy_(o_part)
                    o_part = o_part.reshape(B, q_end - q_start, attn_mod.c_s)
                    pre_projection = g_part * o_part
                    local_pre_projection[:, q_start:q_end].copy_(pre_projection)
                    del attn, g_part, o_part, pair_bias_part, q_part

                if boundary_callback is not None:
                    boundary_callback("sequence_pair_bias", pair_bias_local)
                    boundary_callback("sequence_logits", diagnostic_logits)
                    boundary_callback(
                        "sequence_probabilities",
                        diagnostic_probabilities,
                    )
                    boundary_callback("sequence_value_output", diagnostic_values)
                    boundary_callback(
                        "sequence_pre_output_projection",
                        local_pre_projection[:, :valid_rows],
                    )
                del pair_bias_local
                pre_projection = gather(
                    local_pre_projection.contiguous(),
                    dim=1,
                    original_size=original_N,
                )
                sequence_update = attn_mod.proj_o(pre_projection)
                if boundary_callback is not None:
                    boundary_callback(
                        "sequence_attention_update_rows",
                        sequence_update[:, row_offset:row_offset + valid_rows],
                    )
                    boundary_callback("sequence_attention_update", sequence_update)
                del local_pre_projection, pre_projection
                s = s.float() + sequence_update
                if boundary_callback is not None:
                    boundary_callback("sequence_attention_residual", s)
                del sequence_update
                del diagnostic_logits, diagnostic_probabilities
                del diagnostic_values
            else:
                pair_bias = attn_mod.proj_z(z.float())
                if dap_size > 1:
                    pair_bias = gather(
                        pair_bias.contiguous(),
                        dim=2,
                        original_size=original_N,
                    )
                attn = torch.einsum("bihd,bjhd->bhij", q.float(), k.float())
                attn = attn / (attn_mod.head_dim ** 0.5) + pair_bias.float()
                attn = attn + (1 - mask[:, None, None].float()) * -attn_mod.inf
                attn = attn.softmax(dim=-1)
                o = torch.einsum("bhij,bjhd->bihd", attn, v.float()).to(v.dtype)
                del pair_bias
                o = o.reshape(B, -1, attn_mod.c_s)
                s = s.float() + attn_mod.proj_o(g * o)
                del attn, o

            del g, k, q, s_normed, v
            transition_update = self.transition_s(s)
            if boundary_callback is not None:
                boundary_callback("sequence_transition_update", transition_update)
            s = s + transition_update
            if boundary_callback is not None:
                boundary_callback("sequence_transition_residual", s)
            del transition_update
            s = self.s_post_norm(s)

        _mem("after seq_attn")
        if boundary_callback is not None:
            boundary_callback("s_after_sequence", s)
        self._logged = True

        if _do_subop:
            # Clear env var so only first recycling step saves
            os.environ.pop("BOLTZ_SAVE_SUBOP_CKPT", None)

        row_offset = dap_rank * z.shape[1]
        valid_rows = max(0, min(z.shape[1], original_N - row_offset))
        if valid_rows < z.shape[1]:
            z[:, valid_rows:].zero_()

        # z stays scattered
        return s, z
