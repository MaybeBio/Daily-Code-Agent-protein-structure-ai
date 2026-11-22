"""
DAP-aware Triangle Attention for Boltz 2 — exact matching edition.

Uses the ORIGINAL attention code path (explicit Q@K^T + bias + softmax_no_cast)
to produce bit-identical results to the baseline. Chunks over the row dim
for memory efficiency (~6.9 GB transient per chunk vs ~0 for SDPA).

Starting node: row-scattered z works directly (all N columns available).
Ending node: needs row_to_col to get all N rows, then operates like starting.
"""

import math
import os
import sys
import torch
import torch.distributed as dist
from torch import Tensor, nn
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from boltz_distributed.comm import (
    row_to_col, row_to_col_destructive, col_to_row, col_to_row_streamed, gather,
)
from boltz_distributed.core import get_dap_size, get_dap_rank, get_dap_group

from boltz.model.layers.triangular_attention.utils import (
    permute_final_dims,
)
from boltz.model.layers.triangular_attention.primitives import (
    _attention,
    kernel_triangular_attn,
)


def _m():
    return torch.cuda.memory_allocated() / (1024**2)


def _p():
    return torch.cuda.max_memory_allocated() / (1024**2)


def _diag_enabled() -> bool:
    return os.environ.get("BOLTZ_TRI_ATT_DIAG", "0") != "0"


def _log(prefix: str, tag: str, a0=None):
    if not _diag_enabled() or not torch.cuda.is_available():
        return _m() if torch.cuda.is_available() else 0.0
    a = _m(); p = _p()
    reserved = torch.cuda.memory_reserved() / (1024**2)
    free, total = torch.cuda.mem_get_info()
    delta = f"Δ{a - a0:+.0f}" if a0 is not None else ""
    print(f"          [{prefix}] {tag:40s} | alloc={a:8.0f}MB | reserved={reserved:8.0f}MB | "
          f"free={free // (1024**2):8.0f}/{total // (1024**2):8.0f}MB | peak={p:8.0f}MB | {delta}", flush=True)
    return a


def _tri_att_q_chunk_size(n_query: int) -> int:
    raw = os.environ.get("BOLTZ_TRI_ATT_Q_CHUNK", "").strip()
    if raw == "" or raw == "0":
        return min(n_query, 512) if n_query > 2048 else n_query
    try:
        value = int(raw)
    except ValueError:
        return min(n_query, 512) if n_query > 2048 else n_query
    if value <= 0:
        return n_query
    return min(n_query, value)


def _project_kv(mha: nn.Module, kv_x: Tensor):
    k = mha.linear_k(kv_x)
    v = mha.linear_v(kv_x)

    k = k.view(k.shape[:-1] + (mha.no_heads, -1))
    v = v.view(v.shape[:-1] + (mha.no_heads, -1))

    k = k.transpose(-2, -3)
    v = v.transpose(-2, -3)
    return k, v


def _project_q(mha: nn.Module, q_x: Tensor) -> Tensor:
    q = mha.linear_q(q_x)
    q = q.view(q.shape[:-1] + (mha.no_heads, -1))
    q = q.transpose(-2, -3)
    q /= math.sqrt(mha.c_hidden)
    return q


def _gather_triangle_bias_packed(
    local_bias: Tensor,
    original_size: int,
) -> Tensor:
    dap_size = get_dap_size()
    if dap_size <= 1:
        return local_bias

    packed = local_bias.movedim(2, 0).contiguous()
    output_shape = (packed.shape[0] * dap_size, *packed.shape[1:])
    gathered = torch.empty(
        output_shape,
        dtype=packed.dtype,
        device=packed.device,
    )
    dist.all_gather_into_tensor(
        gathered,
        packed,
        group=get_dap_group(),
        async_op=False,
    )
    del packed
    full_bias = gathered.movedim(0, 2)
    if full_bias.shape[2] > original_size:
        full_bias = full_bias[:, :, :original_size, :]
    return full_bias


def _mha_q_chunked_fused(
    mha: nn.Module,
    q_x: Tensor,
    kv_x: Tensor,
    tri_bias: Tensor,
    mask: Tensor,
    q_chunk: int = 1024,
) -> Tensor:
    keys, values = _project_kv(mha, kv_x)
    output = torch.empty_like(q_x)
    start = 0
    while start < q_x.shape[-2]:
        end = min(start + q_chunk, q_x.shape[-2])
        if q_x.shape[-2] - end < q_chunk:
            end = q_x.shape[-2]
        part = q_x[..., start:end, :]
        queries = mha.linear_q(part)
        queries = queries.view(queries.shape[:-1] + (mha.no_heads, -1)).transpose(-2, -3)
        attended = kernel_triangular_attn(queries, keys, values, tri_bias[..., start:end, :],
                                         mask, 1 / math.sqrt(mha.c_hidden))
        output[..., start:end, :] = mha._wrap_up(attended.transpose(-2, -3), part)
        start = end
    return output


def _mha_q_chunked(
    mha: nn.Module,
    q_x: Tensor,
    kv_x: Tensor,
    tri_bias: Tensor,
    mask_bias: Tensor,
    mask: Tensor,
    *,
    q_chunk: int,
    prefix: str,
) -> Tensor:
    fused = os.environ.get("BOLTZ_DAP_FUSED_TRI_ATT", "0")
    if fused not in ("0", "1"):
        raise ValueError("BOLTZ_DAP_FUSED_TRI_ATT must be 0 or 1")
    if fused == "1":
        if (q_x.device.type != "cuda" or torch.is_grad_enabled() or mha.training
                or not torch.is_autocast_enabled("cuda")
                or torch.get_autocast_dtype("cuda") != torch.bfloat16):
            raise ValueError("Fused DAP triangle attention requires BF16 CUDA evaluation without gradients")
        return _mha_q_chunked_fused(mha, q_x, kv_x, tri_bias, mask)
    n_query = q_x.shape[-2]
    if q_chunk >= n_query:
        return mha(q_x, kv_x, tri_bias, mask_bias, mask, use_kernels=False)

    a0 = _log(prefix, f"q-chunked exact attention q_chunk={q_chunk}")
    k, v = _project_kv(mha, kv_x)
    out = torch.empty_like(q_x)
    a0 = _log(prefix, "after k/v projection + output alloc", a0)

    for q0 in range(0, n_query, q_chunk):
        q1 = min(q0 + q_chunk, n_query)
        q_x_part = q_x[..., q0:q1, :]
        q = _project_q(mha, q_x_part)
        tri_bias_part = tri_bias[..., q0:q1, :]
        attn = _attention(q, k, v, [mask_bias, tri_bias_part])
        attn = attn.transpose(-2, -3)
        out[..., q0:q1, :] = mha._wrap_up(attn, q_x_part)
        del q, tri_bias_part, attn
        a0 = _log(prefix, f"after q[{q0}:{q1}]", a0)

    del k, v
    _log(prefix, "after q-chunked exact attention", a0)
    return out


def _mha_row_chunked(
    mha: nn.Module,
    q_x: Tensor,
    kv_x: Tensor,
    tri_bias: Tensor,
    mask_bias: Tensor,
    mask: Tensor,
    *,
    row_chunk: int,
    q_chunk: int,
    prefix: str,
) -> Tensor:
    out = torch.empty_like(q_x)
    row_chunk = min(max(1, row_chunk), q_x.shape[-3])
    a0 = _log(prefix, f"row-chunked exact attention row_chunk={row_chunk}")

    for batch_index in range(q_x.shape[0]):
        tri_bias_batch = (
            tri_bias if tri_bias.shape[0] == 1 else tri_bias[batch_index:batch_index + 1]
        )
        for row_start in range(0, q_x.shape[-3], row_chunk):
            row_end = min(row_start + row_chunk, q_x.shape[-3])
            q_part = q_x[batch_index:batch_index + 1, row_start:row_end]
            kv_part = kv_x[batch_index:batch_index + 1, row_start:row_end]
            mask_bias_part = mask_bias[
                batch_index:batch_index + 1, row_start:row_end
            ]
            mask_part = mask[batch_index:batch_index + 1, row_start:row_end]

            if q_chunk < q_part.shape[-2]:
                update = _mha_q_chunked(
                    mha,
                    q_part,
                    kv_part,
                    tri_bias_batch,
                    mask_bias_part,
                    mask_part,
                    q_chunk=q_chunk,
                    prefix=prefix,
                )
            else:
                update = mha(
                    q_part,
                    kv_part,
                    tri_bias_batch,
                    mask_bias_part,
                    mask_part,
                    use_kernels=False,
                )
            out[batch_index:batch_index + 1, row_start:row_end].copy_(update)
            del update
            a0 = _log(prefix, f"after rows[{row_start}:{row_end}]", a0)

    _log(prefix, "after row-chunked exact attention", a0)
    return out


def _mha_row_chunked_update_(
    mha: nn.Module,
    x_normed: Tensor,
    tri_bias: Tensor,
    mask_bias: Tensor,
    mask: Tensor,
    *,
    row_chunk: int,
    q_chunk: int,
    prefix: str,
    use_kernels: bool,
) -> Tensor:
    row_chunk = min(max(1, row_chunk), x_normed.shape[-3])
    a0 = _log(prefix, f"reuse update rows row_chunk={row_chunk}")

    for batch_index in range(x_normed.shape[0]):
        tri_bias_batch = (
            tri_bias
            if tri_bias.shape[0] == 1
            else tri_bias[batch_index:batch_index + 1]
        )
        for row_start in range(0, x_normed.shape[-3], row_chunk):
            row_end = min(row_start + row_chunk, x_normed.shape[-3])
            x_part = x_normed[
                batch_index:batch_index + 1, row_start:row_end
            ]
            mask_bias_part = mask_bias[
                batch_index:batch_index + 1, row_start:row_end
            ]
            mask_part = mask[batch_index:batch_index + 1, row_start:row_end]

            if q_chunk < x_part.shape[-2] and not use_kernels:
                update = _mha_q_chunked(
                    mha,
                    x_part,
                    x_part,
                    tri_bias_batch,
                    mask_bias_part,
                    mask_part,
                    q_chunk=q_chunk,
                    prefix=prefix,
                )
            else:
                update = mha(
                    x_part,
                    x_part,
                    tri_bias_batch,
                    mask_bias_part,
                    mask_part,
                    use_kernels=use_kernels,
                )

            x_part.copy_(update)
            del update
            a0 = _log(prefix, f"after update rows[{row_start}:{row_end}]", a0)

    _log(prefix, "after reused row update", a0)
    return x_normed


def _mha_row_chunked_residual_(
    mha: nn.Module,
    residual: Tensor,
    q_x: Tensor,
    kv_x: Tensor,
    tri_bias: Tensor,
    mask_bias: Tensor,
    mask: Tensor,
    residual_scale,
    *,
    row_chunk: int,
    q_chunk: int,
    prefix: str,
    use_kernels: bool,
) -> Tensor:
    row_chunk = min(max(1, row_chunk), q_x.shape[-3])
    a0 = _log(prefix, f"stream residual rows row_chunk={row_chunk}")

    for batch_index in range(q_x.shape[0]):
        tri_bias_batch = (
            tri_bias if tri_bias.shape[0] == 1 else tri_bias[batch_index:batch_index + 1]
        )
        for row_start in range(0, q_x.shape[-3], row_chunk):
            row_end = min(row_start + row_chunk, q_x.shape[-3])
            q_part = q_x[batch_index:batch_index + 1, row_start:row_end]
            kv_part = kv_x[batch_index:batch_index + 1, row_start:row_end]
            mask_bias_part = mask_bias[
                batch_index:batch_index + 1, row_start:row_end
            ]
            mask_part = mask[batch_index:batch_index + 1, row_start:row_end]

            if q_chunk < q_part.shape[-2] and not use_kernels:
                update = _mha_q_chunked(
                    mha,
                    q_part,
                    kv_part,
                    tri_bias_batch,
                    mask_bias_part,
                    mask_part,
                    q_chunk=q_chunk,
                    prefix=prefix,
                )
            else:
                update = mha(
                    q_part,
                    kv_part,
                    tri_bias_batch,
                    mask_bias_part,
                    mask_part,
                    use_kernels=use_kernels,
                )

            scale_part = _scale_slice(
                residual_scale,
                row_start,
                row_end,
                0,
                q_x.shape[-2],
            )
            if torch.is_tensor(scale_part):
                scale_part = scale_part[batch_index:batch_index + 1]
                update = update * scale_part
            elif scale_part != 1.0:
                update = update * scale_part
            residual[
                batch_index:batch_index + 1, row_start:row_end
            ].add_(update)
            del update
            a0 = _log(prefix, f"after residual rows[{row_start}:{row_end}]", a0)

    _log(prefix, "after streamed row residual", a0)
    return residual


def _mha_row_chunked_cpu_residual_(
    mha: nn.Module,
    x_normed: Tensor,
    residual_cpu: Tensor,
    tri_bias: Tensor,
    mask_bias: Tensor,
    mask: Tensor,
    residual_scale,
    *,
    row_chunk: int,
    q_chunk: int,
    prefix: str,
    use_kernels: bool,
) -> Tensor:
    row_chunk = min(max(1, row_chunk), x_normed.shape[-3])
    a0 = _log(prefix, f"stream CPU residual rows row_chunk={row_chunk}")

    for batch_index in range(x_normed.shape[0]):
        tri_bias_batch = (
            tri_bias
            if tri_bias.shape[0] == 1
            else tri_bias[batch_index:batch_index + 1]
        )
        for row_start in range(0, x_normed.shape[-3], row_chunk):
            row_end = min(row_start + row_chunk, x_normed.shape[-3])
            x_part = x_normed[
                batch_index:batch_index + 1, row_start:row_end
            ]
            mask_bias_part = mask_bias[
                batch_index:batch_index + 1, row_start:row_end
            ]
            mask_part = mask[batch_index:batch_index + 1, row_start:row_end]

            if q_chunk < x_part.shape[-2] and not use_kernels:
                update = _mha_q_chunked(
                    mha,
                    x_part,
                    x_part,
                    tri_bias_batch,
                    mask_bias_part,
                    mask_part,
                    q_chunk=q_chunk,
                    prefix=prefix,
                )
            else:
                update = mha(
                    x_part,
                    x_part,
                    tri_bias_batch,
                    mask_bias_part,
                    mask_part,
                    use_kernels=use_kernels,
                )

            scale_part = _scale_slice(
                residual_scale,
                row_start,
                row_end,
                0,
                x_normed.shape[-2],
            )
            if torch.is_tensor(scale_part):
                scale_part = scale_part[batch_index:batch_index + 1]
                update = update * scale_part
            elif scale_part != 1.0:
                update = update * scale_part

            residual_part = residual_cpu[
                batch_index:batch_index + 1, row_start:row_end
            ].to(device=x_normed.device)
            x_part.copy_(residual_part)
            x_part.add_(update)
            del residual_part, update
            a0 = _log(
                prefix,
                f"after CPU residual rows[{row_start}:{row_end}]",
                a0,
            )

    _log(prefix, "after streamed CPU row residual", a0)
    return x_normed


def _scale_slice(scale, i0: int, i1: int, j0: int, j1: int):
    if not torch.is_tensor(scale):
        return scale
    i_sel = slice(None) if scale.shape[1] == 1 else slice(i0, i1)
    j_sel = slice(None) if scale.shape[2] == 1 else slice(j0, j1)
    return scale[:, i_sel, j_sel, :]


def _residual_tile_size(n_tokens: int) -> int:
    raw = os.environ.get("BOLTZ_TRI_ATT_RESIDUAL_TILE", "").strip()
    if raw == "" or raw == "0":
        return min(n_tokens, 1024) if n_tokens > 2048 else n_tokens
    try:
        value = int(raw)
    except ValueError:
        return min(n_tokens, 1024) if n_tokens > 2048 else n_tokens
    if value <= 0:
        return n_tokens
    return min(n_tokens, value)


def _tri_att_end_col_tile_size(n_local: int) -> int:
    raw = os.environ.get(
        "BOLTZ_TRI_ATT_END_COL_TILE",
        os.environ.get("BOLTZ_TRI_ATT_END_ROW_TILE", ""),
    ).strip()
    if raw == "" or raw == "0":
        return min(n_local, 128) if n_local > 128 else n_local
    try:
        value = int(raw)
    except ValueError:
        return min(n_local, 128) if n_local > 128 else n_local
    if value <= 0:
        return n_local
    return min(n_local, value)


def _add_residual_from_update_(x: Tensor, update: Tensor, scale, prefix: str) -> Tensor:
    i_tile = _residual_tile_size(update.shape[1])
    j_tile = _residual_tile_size(update.shape[2])
    a0 = _log(prefix, "residual add from attention update")
    for i0 in range(0, update.shape[1], i_tile):
        i1 = min(i0 + i_tile, update.shape[1])
        for j0 in range(0, update.shape[2], j_tile):
            j1 = min(j0 + j_tile, update.shape[2])
            update_part = update[:, i0:i1, j0:j1, :]
            scale_part = _scale_slice(scale, i0, i1, j0, j1)
            if torch.is_tensor(scale_part):
                update_part = update_part * scale_part
            elif scale_part != 1.0:
                update_part = update_part * scale_part
            x[:, i0:i1, j0:j1, :].add_(update_part)
            del update_part
    _log(prefix, "after residual add", a0)
    return x


def _add_col_to_row_residual_streamed_(
    x: Tensor,
    col_update: Tensor,
    scale,
    original_size: int,
    prefix: str,
) -> Tensor:
    dap_size = get_dap_size()
    if dap_size <= 1:
        return _add_residual_from_update_(x, col_update, scale, prefix)

    group = get_dap_group()
    row_split = (col_update.shape[1] + dap_size - 1) // dap_size
    col_tile = _tri_att_end_col_tile_size(col_update.shape[2])
    a0 = _log(prefix, f"stream col_to_row residual col_tile={col_tile}")

    for j0 in range(0, col_update.shape[2], col_tile):
        j1 = min(j0 + col_tile, col_update.shape[2])
        col_tile_tensor = col_update[:, :, j0:j1, :]
        input_tensor_list = [
            part.contiguous()
            for part in torch.split(col_tile_tensor, row_split, dim=1)
        ]
        output_tensor_list = [torch.empty_like(part) for part in input_tensor_list]
        dist.all_to_all(output_tensor_list, input_tensor_list, group=group, async_op=False)
        del input_tensor_list, col_tile_tensor

        for src, update_part in enumerate(output_tensor_list):
            col0 = src * col_update.shape[2] + j0
            col1 = min(src * col_update.shape[2] + j1, original_size)
            if col1 <= col0:
                continue
            valid_width = col1 - col0
            update_view = update_part[:, :, :valid_width, :]
            scale_part = _scale_slice(scale, 0, x.shape[1], col0, col1)
            if torch.is_tensor(scale_part):
                update_view.mul_(scale_part)
            elif scale_part != 1.0:
                update_view.mul_(scale_part)
            x[:, :, col0:col1, :].add_(update_view)
        del output_tensor_list
        a0 = _log(prefix, f"after col_to_row tile j[{j0}:{j1}]", a0)

    _log(prefix, "after streamed col_to_row residual", a0)
    return x


class DAPTriAttStart(nn.Module):
    """DAP wrapper for TriangleAttentionStartingNode.

    Operates on row-scattered z [B, N/dap, N, D].
    Starting node attention: iterate over rows (N/dap, local),
    attend across columns (N, full). Only the bias is gathered.
    Uses the ORIGINAL attention code for exact numerical matching.
    """

    def __init__(self, original_tri_att):
        super().__init__()
        self.inner = original_tri_att

    def forward(
        self,
        x: Tensor,
        mask: Optional[Tensor] = None,
        chunk_size: Optional[int] = None,
        use_kernels: bool = False,
    ) -> Tensor:
        dap_size = get_dap_size()
        if dap_size <= 1:
            return self.inner(x, mask, chunk_size, use_kernels)

        if mask is None:
            mask = x.new_ones(x.shape[:-1])

        # Layer norm (pointwise)
        x = self.inner.layer_norm(x)

        # Mask bias: [B, N/dap, 1, 1, N]
        mask_bias = self.inner.inf * (mask[..., :, None, None, :] - 1)

        # Triangle bias: gather only H channels (not D)
        local_bias = self.inner.linear(x)
        local_bias = permute_final_dims(local_bias, (2, 0, 1))

        # Gather dim 2 (N/dap -> N): gives [B, H, N, N]
        N = x.shape[2]
        full_bias = gather(local_bias.contiguous(), dim=2, original_size=N)
        del local_bias
        full_bias = full_bias.unsqueeze(-4)  # [B, 1, H, N, N]
        _log("TRI-ATT-START", "after full_bias gather")

        # Use original _chunk / mha path for exact matching
        q_chunk = _tri_att_q_chunk_size(x.shape[-2])
        if chunk_size is not None and not use_kernels:
            x = _mha_row_chunked(
                self.inner.mha,
                x,
                x,
                full_bias,
                mask_bias,
                mask[..., :, None, None, :],
                row_chunk=chunk_size,
                q_chunk=q_chunk,
                prefix="TRI-ATT-START",
            )
        else:
            x = self.inner.mha(
                x, x, full_bias, mask_bias,
                mask[..., :, None, None, :],
                use_kernels=use_kernels,
            )

        return x

    def forward_with_residual(
        self,
        x: Tensor,
        mask: Optional[Tensor],
        residual_scale,
        chunk_size: Optional[int] = None,
        use_kernels: bool = False,
    ) -> Tensor:
        if get_dap_size() <= 1:
            return x + residual_scale * self.inner(x, mask, chunk_size, use_kernels)
        if not self.training and not torch.is_grad_enabled():
            if mask is None:
                mask = x.new_ones(x.shape[:-1])

            residual_cpu = x.detach().to(device="cpu")
            norm_rows = chunk_size or 1
            for row_start in range(0, x.shape[1], norm_rows):
                row_end = min(row_start + norm_rows, x.shape[1])
                x[:, row_start:row_end].copy_(
                    self.inner.layer_norm(x[:, row_start:row_end])
                )
            mask_bias = self.inner.inf * (mask[..., :, None, None, :] - 1)
            local_bias = self.inner.linear(x)
            local_bias = permute_final_dims(local_bias, (2, 0, 1))
            full_bias = _gather_triangle_bias_packed(
                local_bias,
                x.shape[2],
            ).unsqueeze(-4)
            del local_bias

            return _mha_row_chunked_cpu_residual_(
                self.inner.mha,
                x,
                residual_cpu,
                full_bias,
                mask_bias,
                mask[..., :, None, None, :],
                residual_scale,
                row_chunk=chunk_size or x.shape[-3],
                q_chunk=_tri_att_q_chunk_size(x.shape[-2]),
                prefix="TRI-ATT-START",
                use_kernels=use_kernels,
            )
        update = self.forward(x, mask=mask, chunk_size=chunk_size, use_kernels=use_kernels)
        try:
            return _add_residual_from_update_(x, update, residual_scale, "TRI-ATT-START")
        finally:
            del update


class DAPTriAttEnd(nn.Module):
    """DAP wrapper for TriangleAttentionEndingNode.

    Ending node needs all N rows for keys/queries.
    Strategy: row_to_col -> transpose -> operate like starting node.
    Uses the ORIGINAL attention code for exact numerical matching.
    """

    def __init__(self, original_tri_att):
        super().__init__()
        self.inner = original_tri_att

    def _forward_col_update(
        self,
        x: Tensor,
        mask: Optional[Tensor] = None,
        chunk_size: Optional[int] = None,
        use_kernels: bool = False,
        *,
        release_input: bool = False,
    ):
        if mask is None:
            mask = x.new_ones(x.shape[:-1])

        original_N = x.shape[2]

        # 1. row_to_col: [B, N/dap, N, D] -> [B, N_pad, N/dap, D]
        x_col = (
            row_to_col_destructive(x, host_staging=True)
            if release_input else row_to_col(x)
        )
        mask_col = row_to_col(mask.unsqueeze(-1)).squeeze(-1)

        # Zero out padded positions to prevent them from affecting attention
        N_pad = x_col.shape[1]
        if N_pad > original_N:
            x_col[:, original_N:, :, :] = 0
            mask_col[:, original_N:, :] = 0

        # 2. Transpose for ending node: [B, N/dap, N_pad, D]
        x_t = x_col.transpose(-2, -3)
        mask_t = mask_col.transpose(-1, -2)
        del x_col, mask_col

        # 3. Layer norm (pointwise)
        reuse_col_storage = not self.training and not torch.is_grad_enabled()
        if reuse_col_storage and release_input:
            norm_rows = chunk_size or 1
            for row_start in range(0, x_t.shape[1], norm_rows):
                row_end = min(row_start + norm_rows, x_t.shape[1])
                x_t[:, row_start:row_end].copy_(
                    self.inner.layer_norm(x_t[:, row_start:row_end])
                )
        elif reuse_col_storage:
            x_t.copy_(self.inner.layer_norm(x_t))
        else:
            x_t = self.inner.layer_norm(x_t)

        # 4. Mask bias: [B, N/dap, 1, 1, N_pad]
        mask_bias = self.inner.inf * (mask_t[..., :, None, None, :] - 1)

        # 5. Triangle bias: gather the small bias
        local_bias = self.inner.linear(x_t)
        local_bias = permute_final_dims(local_bias, (2, 0, 1))
        if reuse_col_storage:
            full_bias = _gather_triangle_bias_packed(
                local_bias,
                N_pad,
            )
        else:
            full_bias = gather(
                local_bias.contiguous(),
                dim=2,
                original_size=N_pad,
            )
        del local_bias
        full_bias = full_bias.unsqueeze(-4)  # [B, 1, H, N_pad, N_pad]
        _log("TRI-ATT-END ", "after full_bias gather")

        # 6. Use original _chunk / mha path for exact matching
        mask_expanded = mask_t[..., :, None, None, :]
        q_chunk = _tri_att_q_chunk_size(x_t.shape[-2])
        if reuse_col_storage:
            x_t = _mha_row_chunked_update_(
                self.inner.mha,
                x_t,
                full_bias,
                mask_bias,
                mask_expanded,
                row_chunk=chunk_size or x_t.shape[-3],
                q_chunk=q_chunk,
                prefix="TRI-ATT-END ",
                use_kernels=use_kernels,
            )
        elif chunk_size is not None and not use_kernels:
            x_t = _mha_row_chunked(
                self.inner.mha,
                x_t,
                x_t,
                full_bias,
                mask_bias,
                mask_expanded,
                row_chunk=chunk_size,
                q_chunk=q_chunk,
                prefix="TRI-ATT-END ",
            )
        else:
            x_t = self.inner.mha(
                x_t, x_t, full_bias, mask_bias,
                mask_expanded,
                use_kernels=use_kernels,
            )

        # 7. Transpose back + col_to_row
        del full_bias, mask_bias, mask_expanded, mask_t
        x_col_out = x_t.transpose(-2, -3)
        if release_input:
            x_col_out = x_col_out.detach()
        del x_t
        return x_col_out, original_N

    def forward(
        self,
        x: Tensor,
        mask: Optional[Tensor] = None,
        chunk_size: Optional[int] = None,
        use_kernels: bool = False,
    ) -> Tensor:
        dap_size = get_dap_size()
        if dap_size <= 1:
            return self.inner(x, mask, chunk_size, use_kernels)

        x_col_out, original_N = self._forward_col_update(
            x, mask=mask, chunk_size=chunk_size, use_kernels=use_kernels,
        )
        x_out = col_to_row(x_col_out)
        del x_col_out

        # 8. Trim padding
        if x_out.shape[2] > original_N:
            x_out = x_out[:, :, :original_N, :]

        return x_out

    def forward_with_residual(
        self,
        x: Tensor,
        mask: Optional[Tensor],
        residual_scale,
        chunk_size: Optional[int] = None,
        use_kernels: bool = False,
    ) -> Tensor:
        if get_dap_size() <= 1:
            return x + residual_scale * self.inner(x, mask, chunk_size, use_kernels)
        if not self.training and not torch.is_grad_enabled() and x.ndim == 4 and x.shape[0] == 1:
            residual_cpu = x.detach().to(device="cpu", copy=True)
            update, original_N = self._forward_col_update(
                x, mask=mask, chunk_size=chunk_size, use_kernels=use_kernels,
                release_input=True,
            )
            row_update = col_to_row_streamed(
                update, original_size=original_N, host_staging=True,
            )
            del update
            row_tile = _residual_tile_size(row_update.shape[1])
            col_tile = _residual_tile_size(row_update.shape[2])
            for row_start in range(0, row_update.shape[1], row_tile):
                row_end = min(row_start + row_tile, row_update.shape[1])
                for col_start in range(0, row_update.shape[2], col_tile):
                    col_end = min(col_start + col_tile, row_update.shape[2])
                    target = row_update[:, row_start:row_end, col_start:col_end]
                    residual = residual_cpu[:, row_start:row_end, col_start:col_end].to(target.device)
                    scale = _scale_slice(residual_scale, row_start, row_end, col_start, col_end)
                    target.copy_(residual + scale * target)
                    del residual, target
            x.set_(row_update)
            return x
        update, original_N = self._forward_col_update(
            x, mask=mask, chunk_size=chunk_size, use_kernels=use_kernels,
        )
        try:
            return _add_col_to_row_residual_streamed_(
                x,
                update,
                residual_scale,
                original_N,
                "TRI-ATT-END ",
            )
        finally:
            del update
