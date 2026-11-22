"""
DAP Trunk Wrapper for Boltz 2.

This module monkey-patches the Boltz 2 model to use DAP-aware layers
in the trunk loop. The approach:
1. ALL GPUs: Run input embedding, z_init, recycling (small ops)
2. ALL GPUs: Scatter z, run template/MSA/pairformer with DAP layers
3. ALL GPUs: Gather z back to full
4. GPU 0 ONLY: Run post-trunk (distogram, diffusion, structure, confidence)
   Non-primary GPUs skip post-trunk entirely — those modules
   aren't even loaded on their GPUs.

No model duplication — non-primary GPUs only have trunk weights.
Activations (z) are sharded across GPUs during the trunk.
"""

import torch
from torch import Tensor, nn
from typing import Callable, Optional
import time
import json
from datetime import datetime

import sys
import os

# Late-imported in _run_template_dap when dap_size > 1
# from dap_tri_att import DAPTriAttStart, DAPTriAttEnd
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from boltz_distributed.comm import (
    col_to_row,
    col_to_row_inplace,
    gather,
    gather_to_rank0_cpu,
    row_to_col,
    scatter,
)
from boltz_distributed.core import get_dap_size, get_dap_rank
from boltz.model.layers.token_bias import LayerwiseTokenBias

from dap_msa import DAPMSALayer
from dap_pairformer import DAPPairformerLayer
from dap_pairformer_noseq import DAPPairformerNoSeqLayer
from dap_confidence import inject_dap_into_confidence, run_confidence_dap
from dap_features import atom_to_token_indices, relative_position_inputs_for_rows
from pairformer_capture import maybe_capture_pairformer_entry


class Phase2ShadowComplete(RuntimeError):
    """Signal that the validation-only trunk/distogram shadow run completed."""


def _process_ram_mb() -> tuple[int | None, int | None, int | None]:
    """Return process RSS plus cgroup memory usage/limit in MB when available."""
    rss_mb = None
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    rss_mb = int(line.split()[1]) // 1024
                    break
    except OSError:
        pass

    cgroup_used_mb = None
    cgroup_limit_mb = None
    try:
        with open("/sys/fs/cgroup/memory.current") as f:
            cgroup_used_mb = int(f.read().strip()) // (1024 * 1024)
        with open("/sys/fs/cgroup/memory.max") as f:
            raw_limit = f.read().strip()
            if raw_limit != "max":
                cgroup_limit_mb = int(raw_limit) // (1024 * 1024)
    except OSError:
        pass

    return rss_mb, cgroup_used_mb, cgroup_limit_mb


def _env_positive_int(name: str) -> Optional[int]:
    raw = os.environ.get(name, "").strip()
    if raw == "":
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _tri_attn_chunk_size(n_tokens: int, *, default_long: int, default_small: int) -> int:
    override = _env_positive_int("BOLTZ_TRI_ATT_CHUNK")
    if override is not None:
        return override
    if n_tokens >= 8000:
        return 2
    if n_tokens > 2000:
        return default_long
    return default_small


def _pin_memory_enabled() -> bool:
    return bool(torch.cuda.is_available())


def _diffusion_cpu_storage_dtype() -> torch.dtype:
    name = os.environ.get("BOLTZ_DC_CPU_STORAGE_DTYPE", "fp32").strip().lower()
    dtypes = {"fp32": torch.float32, "bf16": torch.bfloat16}
    if name not in dtypes:
        raise ValueError(
            f"invalid BOLTZ_DC_CPU_STORAGE_DTYPE={name!r}; expected fp32 or bf16"
        )
    return dtypes[name]


def _project_msa_features_chunked(
    msa_proj: nn.Module,
    msa: Tensor,
    has_deletion: Tensor,
    deletion_value: Tensor,
    is_paired: Tensor,
    use_paired_feature: bool,
    num_tokens: int,
    sequence_chunk: int,
) -> Tensor:
    projected = None
    chunk_size = max(1, min(int(sequence_chunk), msa.shape[1]))
    for sequence_start in range(0, msa.shape[1], chunk_size):
        sequence_end = min(sequence_start + chunk_size, msa.shape[1])
        feature_parts = [
            torch.nn.functional.one_hot(
                msa[:, sequence_start:sequence_end], num_classes=num_tokens
            ),
            has_deletion[:, sequence_start:sequence_end],
            deletion_value[:, sequence_start:sequence_end],
        ]
        if use_paired_feature:
            feature_parts.append(is_paired[:, sequence_start:sequence_end])
        feature_chunk = torch.cat(feature_parts, dim=-1)
        projected_chunk = msa_proj(feature_chunk)
        if projected is None:
            projected = torch.empty(
                (*msa.shape, projected_chunk.shape[-1]),
                dtype=projected_chunk.dtype,
                device=projected_chunk.device,
            )
        projected[:, sequence_start:sequence_end].copy_(projected_chunk)
        del feature_parts, feature_chunk, projected_chunk
    if projected is None:
        raise ValueError("MSA must contain at least one sequence")
    return projected


def _add_cpu_row_residual_(target: Tensor, residual_cpu: Tensor, chunk_rows: int) -> None:
    if residual_cpu.device.type != "cpu":
        raise ValueError("residual_cpu must be a CPU tensor")
    if target.shape != residual_cpu.shape:
        raise ValueError(
            f"target and residual_cpu shapes differ: {target.shape} != {residual_cpu.shape}"
        )

    row_chunk = max(1, int(chunk_rows))
    for row_start in range(0, target.shape[1], row_chunk):
        row_end = min(row_start + row_chunk, target.shape[1])
        residual_chunk = residual_cpu[:, row_start:row_end].to(
            device=target.device,
            dtype=target.dtype,
            non_blocking=residual_cpu.is_pinned(),
        )
        target[:, row_start:row_end].add_(residual_chunk)
        del residual_chunk


def _module_device(module: nn.Module) -> torch.device:
    return next(module.parameters()).device


def _run_relative_position_encoding_to_cpu(
    rel_pos: nn.Module,
    feats: dict[str, Tensor],
    chunk_rows: int,
) -> Tensor:
    """Compute full relative-position features with bounded CPU temporaries."""
    if any(value.device.type != "cpu" for value in feats.values()):
        raise ValueError("relative-position features must be CPU tensors")
    from torch.nn.functional import one_hot

    batch_size, n_tokens = feats["asym_id"].shape
    out_dim = rel_pos.linear_layer.out_features
    output = torch.empty(
        batch_size,
        n_tokens,
        n_tokens,
        out_dim,
        dtype=rel_pos.linear_layer.weight.dtype,
        device="cpu",
    )
    row_chunk = max(1, int(chunk_rows))
    for row_start in range(0, n_tokens, row_chunk):
        row_end = min(row_start + row_chunk, n_tokens)
        same_chain = torch.eq(
            feats["asym_id"][:, row_start:row_end, None],
            feats["asym_id"][:, None, :],
        )
        same_residue = torch.eq(
            feats["residue_index"][:, row_start:row_end, None],
            feats["residue_index"][:, None, :],
        )
        same_entity = torch.eq(
            feats["entity_id"][:, row_start:row_end, None],
            feats["entity_id"][:, None, :],
        )

        d_residue = (
            feats["residue_index"][:, row_start:row_end, None]
            - feats["residue_index"][:, None, :]
        )
        if rel_pos.cyclic_pos_enc and torch.any(feats["cyclic_period"] > 0):
            period = torch.where(
                feats["cyclic_period"] > 0,
                feats["cyclic_period"],
                torch.zeros_like(feats["cyclic_period"]) + 10000,
            )
            d_residue = (
                d_residue - period * torch.round(d_residue / period)
            ).long()
        d_residue = torch.clip(d_residue + rel_pos.r_max, 0, 2 * rel_pos.r_max)
        d_residue = torch.where(
            same_chain,
            d_residue,
            torch.zeros_like(d_residue) + 2 * rel_pos.r_max + 1,
        )
        relative_position = one_hot(d_residue, 2 * rel_pos.r_max + 2)

        d_token = torch.clip(
            feats["token_index"][:, row_start:row_end, None]
            - feats["token_index"][:, None, :]
            + rel_pos.r_max,
            0,
            2 * rel_pos.r_max,
        )
        d_token = torch.where(
            same_chain & same_residue,
            d_token,
            torch.zeros_like(d_token) + 2 * rel_pos.r_max + 1,
        )
        relative_token = one_hot(d_token, 2 * rel_pos.r_max + 2)

        d_chain = torch.clip(
            feats["sym_id"][:, row_start:row_end, None]
            - feats["sym_id"][:, None, :]
            + rel_pos.s_max,
            0,
            2 * rel_pos.s_max,
        )
        condition = (~same_entity) if rel_pos.fix_sym_check else same_chain
        d_chain = torch.where(
            condition,
            torch.zeros_like(d_chain) + 2 * rel_pos.s_max + 1,
            d_chain,
        )
        relative_chain = one_hot(d_chain, 2 * rel_pos.s_max + 2)
        encoded = rel_pos.linear_layer(
            torch.cat(
                [
                    relative_position.float(),
                    relative_token.float(),
                    same_entity.unsqueeze(-1).float(),
                    relative_chain.float(),
                ],
                dim=-1,
            )
        )
        output[:, row_start:row_end].copy_(encoded)
        del encoded, relative_position, relative_token, relative_chain
        del d_residue, d_token, d_chain, same_chain, same_residue, same_entity
    return output


def _add_relative_position_encoding_to_row_shard_(
    rel_pos: nn.Module,
    feats: dict[str, Tensor],
    z_row: Tensor,
    *,
    original_size: int,
    global_row_start: int,
    valid_rows: int,
    chunk_rows: int,
    boundary_callback: Optional[Callable[[int, int, Tensor], None]] = None,
) -> Tensor:
    """Add relative-position rows in bounded chunks during inference."""
    if z_row.ndim != 4 or z_row.dtype not in (torch.float32, torch.bfloat16):
        raise TypeError("streamed relative-position encoding requires FP32 or BF16 pair rows")
    if z_row.dtype == torch.bfloat16 and not (
        torch.is_autocast_enabled(z_row.device.type)
        and torch.get_autocast_dtype(z_row.device.type) == torch.bfloat16
    ):
        raise TypeError("BF16 pair rows require BF16 mixed precision")
    if chunk_rows <= 0:
        raise ValueError("chunk_rows must be positive")
    if valid_rows < 0 or valid_rows > z_row.shape[1]:
        raise ValueError("valid row count does not match the pair shard")
    if global_row_start < 0 or global_row_start + valid_rows > original_size:
        raise ValueError("global row range is outside the original token count")
    if z_row.shape[2] < original_size:
        raise ValueError("pair-shard column axis is smaller than the token count")
    if _module_device(rel_pos) != z_row.device:
        raise ValueError("relative-position encoder and pair shard must use one device")

    for local_start in range(0, valid_rows, chunk_rows):
        local_end = min(local_start + chunk_rows, valid_rows)
        row_start = global_row_start + local_start
        row_end = global_row_start + local_end
        inputs = relative_position_inputs_for_rows(
            rel_pos,
            feats,
            row_start=row_start,
            row_end=row_end,
        )
        encoded = rel_pos.linear_layer(inputs)
        del inputs
        if boundary_callback is not None:
            boundary_callback(row_start, row_end, encoded)
        result_dtype = torch.promote_types(z_row.dtype, encoded.dtype)
        if result_dtype != z_row.dtype:
            z_row = z_row.to(dtype=result_dtype)
        z_row[:, local_start:local_end, :original_size].add_(encoded)
        del encoded
    return z_row


def _add_contact_conditioning_to_row_shard_(
    contact_conditioning: nn.Module,
    feats: dict[str, Tensor],
    z_row: Tensor,
    *,
    chunk_rows: int,
    boundary_callback: Optional[Callable[[int, int, Tensor], None]] = None,
) -> Tensor:
    """Add contact-conditioning rows in bounded chunks during inference."""
    if z_row.ndim != 4 or z_row.dtype not in (torch.float32, torch.bfloat16):
        raise TypeError("streamed contact conditioning requires FP32 or BF16 pair rows")
    if z_row.dtype == torch.bfloat16 and not (
        torch.is_autocast_enabled(z_row.device.type)
        and torch.get_autocast_dtype(z_row.device.type) == torch.bfloat16
    ):
        raise TypeError("BF16 pair rows require BF16 mixed precision")
    if chunk_rows <= 0:
        raise ValueError("chunk_rows must be positive")
    if _module_device(contact_conditioning) != z_row.device:
        raise ValueError("contact conditioner and pair shard must use one device")
    required = ("contact_conditioning", "contact_threshold")
    for name in required:
        if name not in feats or feats[name].ndim < 3:
            raise ValueError(f"contact feature {name!r} is missing or invalid")
        if feats[name].device != z_row.device:
            raise ValueError(f"contact feature {name!r} is on the wrong device")
        if feats[name].shape[:3] != z_row.shape[:3]:
            raise ValueError(f"contact feature {name!r} does not match pair rows")

    for row_start in range(0, z_row.shape[1], chunk_rows):
        row_end = min(row_start + chunk_rows, z_row.shape[1])
        encoded = contact_conditioning(
            {
                "contact_conditioning": feats["contact_conditioning"][
                    :, row_start:row_end
                ],
                "contact_threshold": feats["contact_threshold"][:, row_start:row_end],
            }
        )
        if boundary_callback is not None:
            boundary_callback(row_start, row_end, encoded)
        result_dtype = torch.promote_types(z_row.dtype, encoded.dtype)
        if result_dtype != z_row.dtype:
            z_row = z_row.to(dtype=result_dtype)
        z_row[:, row_start:row_end].add_(encoded)
        del encoded
    return z_row


def _run_pairwise_conditioner_to_cpu(
    pairwise_conditioner: nn.Module,
    z_cpu: Tensor,
    relative_position_encoding: Tensor,
    chunk_rows: int,
    transition_chunk: Optional[int] = None,
    storage_dtype: Optional[torch.dtype] = None,
    mem_log=None,
    boundary_callback: Optional[Callable[[str, int, int, Tensor], None]] = None,
) -> Tensor:
    """Run diffusion pairwise conditioning row chunks and stage output on CPU."""
    if z_cpu.device.type != "cpu" or relative_position_encoding.device.type != "cpu":
        raise ValueError("z_cpu and relative_position_encoding must be CPU tensors")

    device = _module_device(pairwise_conditioner)
    if device.type != "cuda":
        pairwise_conditioner.cuda()
        device = _module_device(pairwise_conditioner)

    n_tokens = z_cpu.shape[1]
    row_chunk = max(1, int(chunk_rows))
    probe = torch.zeros(
        1,
        1,
        1,
        z_cpu.shape[-1] + relative_position_encoding.shape[-1],
        dtype=z_cpu.dtype,
        device=device,
    )
    probe_out = pairwise_conditioner.dim_pairwise_init_proj(probe)
    out_dim = probe_out.shape[-1]
    del probe, probe_out
    if mem_log is not None:
        mem_log("  dc: pairwise out_dim probed")

    pin = _pin_memory_enabled()
    storage_dtype = storage_dtype or z_cpu.dtype
    z_cond_cpu = torch.empty(
        1,
        n_tokens,
        n_tokens,
        out_dim,
        dtype=storage_dtype,
        device="cpu",
        pin_memory=pin,
    )
    if mem_log is not None:
        mem_log("  dc: z_cond CPU buffer allocated")

    for row_start in range(0, n_tokens, row_chunk):
        row_end = min(row_start + row_chunk, n_tokens)
        chunk_in = torch.cat(
            (
                z_cpu[:, row_start:row_end],
                relative_position_encoding[:, row_start:row_end],
            ),
            dim=-1,
        ).to(device=device, non_blocking=pin)
        chunk_out = pairwise_conditioner.dim_pairwise_init_proj(chunk_in)
        del chunk_in
        if boundary_callback is not None:
            boundary_callback("initial_projection", row_start, row_end, chunk_out)
        for transition_index, transition in enumerate(pairwise_conditioner.transitions):
            chunk_out = transition(chunk_out, transition_chunk) + chunk_out
            if boundary_callback is not None:
                boundary_callback(
                    f"transition_{transition_index}",
                    row_start,
                    row_end,
                    chunk_out,
                )
        z_cond_cpu[:, row_start:row_end].copy_(chunk_out, non_blocking=pin)
        del chunk_out

    if pin:
        torch.cuda.synchronize(device)
    return z_cond_cpu


def _run_pairwise_conditioner_on_row_shard_inplace(
    pairwise_conditioner: nn.Module,
    rel_pos: nn.Module,
    feats: dict[str, Tensor],
    z_row: Tensor,
    *,
    original_size: int,
    global_row_start: int,
    chunk_rows: int,
    transition_chunk: Optional[int] = None,
    boundary_callback: Optional[Callable[[str, int, int, Tensor], None]] = None,
) -> Tensor:
    """Stage trunk rows on CPU, then replace the GPU shard with conditioned rows."""
    if z_row.ndim != 4 or z_row.dtype != torch.float32:
        raise TypeError("row-sharded pairwise conditioning requires four-dimensional FP32 z")
    if z_row.device.type != "cuda":
        raise ValueError("row-sharded pairwise conditioning requires a CUDA row shard")
    if chunk_rows <= 0:
        raise ValueError("chunk_rows must be positive")
    if z_row.shape[2] < original_size:
        raise ValueError("row-shard column axis is smaller than the original token count")
    if _module_device(pairwise_conditioner) != z_row.device:
        raise ValueError("pairwise conditioner and row shard must use the same device")
    if _module_device(rel_pos) != z_row.device:
        raise ValueError("relative-position encoder and row shard must use the same device")

    valid_rows = max(
        0,
        min(z_row.shape[1], original_size - global_row_start),
    )
    trunk_rows_cpu = z_row[:, :, :original_size].detach().cpu().contiguous()
    for local_start in range(0, valid_rows, chunk_rows):
        local_end = min(local_start + chunk_rows, valid_rows)
        row_start = global_row_start + local_start
        row_end = global_row_start + local_end
        rel_inputs = relative_position_inputs_for_rows(
            rel_pos,
            feats,
            row_start=row_start,
            row_end=row_end,
        )
        rel_encoded = rel_pos.linear_layer(rel_inputs)
        del rel_inputs
        chunk_out = pairwise_conditioner.dim_pairwise_init_proj(
            torch.cat(
                (z_row[:, local_start:local_end, :original_size], rel_encoded),
                dim=-1,
            )
        )
        del rel_encoded
        if boundary_callback is not None:
            boundary_callback("initial_projection", row_start, row_end, chunk_out)
        for transition_index, transition in enumerate(pairwise_conditioner.transitions):
            chunk_out = transition(chunk_out, transition_chunk) + chunk_out
            if boundary_callback is not None:
                boundary_callback(
                    f"transition_{transition_index}",
                    row_start,
                    row_end,
                    chunk_out,
                )
        z_row[:, local_start:local_end, :original_size].copy_(chunk_out)
        del chunk_out
    return trunk_rows_cpu


def _run_token_trans_bias_from_zcond_cpu(
    layers: nn.ModuleList,
    z_cond_cpu: Tensor,
    chunk_rows: int,
    layout: str = "concat",
    storage_dtype: Optional[torch.dtype] = None,
) -> Tensor | LayerwiseTokenBias:
    """Project CPU-staged z_cond into pageable host storage.

    The quadratic output can exceed the CUDA pinned-host allocation limit;
    blocking chunk copies keep it pageable without changing the projections.
    """
    if z_cond_cpu.device.type != "cpu":
        raise ValueError("z_cond_cpu must be a CPU tensor")
    if not layers:
        raise ValueError("token transformer projection layers are empty")
    if layout == "layerwise":
        if storage_dtype is not None and storage_dtype != torch.float32:
            raise ValueError("Layerwise token bias requires FP32 storage")
        return LayerwiseTokenBias(layers, z_cond_cpu, chunk_rows)
    if layout not in {"concat", "layer_major"}:
        raise ValueError(
            f"unsupported diffusion token bias layout {layout!r}; "
            "expected 'concat', 'layer_major', or 'layerwise'"
        )

    device = _module_device(layers[0])
    if device.type != "cuda":
        for layer in layers:
            layer.cuda()
        device = _module_device(layers[0])

    pin = False
    n_tokens = z_cond_cpu.shape[1]
    row_chunk = max(1, int(chunk_rows))
    compute_dtype = next(layers[0].parameters()).dtype
    storage_dtype = storage_dtype or z_cond_cpu.dtype
    probe = torch.zeros(
        1,
        1,
        1,
        z_cond_cpu.shape[-1],
        dtype=compute_dtype,
        device=device,
    )
    probe_out = layers[0](probe)
    per_layer_dim = probe_out.shape[-1]
    del probe, probe_out
    if layout == "concat":
        token_trans_bias_cpu = torch.empty(
            1,
            n_tokens,
            n_tokens,
            len(layers) * per_layer_dim,
            dtype=storage_dtype,
            device="cpu",
            pin_memory=pin,
        )
    else:
        token_trans_bias_cpu = torch.empty(
            len(layers),
            1,
            n_tokens,
            n_tokens,
            per_layer_dim,
            dtype=storage_dtype,
            device="cpu",
            pin_memory=pin,
        )
    for row_start in range(0, n_tokens, row_chunk):
        row_end = min(row_start + row_chunk, n_tokens)
        z_chunk = z_cond_cpu[:, row_start:row_end].to(
            device=device,
            dtype=compute_dtype,
            non_blocking=pin,
        )
        if layout == "concat":
            bias_gpu = torch.cat([layer(z_chunk) for layer in layers], dim=-1)
            token_trans_bias_cpu[:, row_start:row_end].copy_(
                bias_gpu,
                non_blocking=pin,
            )
            del bias_gpu
        else:
            for layer_index, layer in enumerate(layers):
                bias_gpu = layer(z_chunk)
                token_trans_bias_cpu[
                    layer_index, :, row_start:row_end
                ].copy_(bias_gpu, non_blocking=pin)
                del bias_gpu
        del z_chunk
    if pin:
        torch.cuda.synchronize(device)
    return token_trans_bias_cpu


def _run_atom_encoder_with_chunked_zcond(
    ae,
    feats,
    s_trunk,
    z_cond,
    chunk_rows: int,
    atom_window_chunk: Optional[int] = None,
    mem_log=None,
):
    """Run :class:`AtomEncoder` forward with chunked ``z_to_p`` from ``z_cond``.

    Mirrors ``boltz.model.modules.encodersv2.AtomEncoder.forward`` for
    ``structure_prediction=True``, but the ``z_to_p_trans(z)`` + einsum block is
    fused into a loop over token rows so we never materialize a full
    ``[B, Nt, Nt, D]`` ``z_to_p`` tensor on GPU.

    Parameters
    ----------
    z_cond
        Pairwise conditioning ``[B, Nt, Nt, tz]`` on CPU or CUDA (same ``B``/``Nt`` as trunk).
    chunk_rows
        Kept for backward-compatible callers; the indexed path does not need token-row
        chunks because it gathers only the atom-window token pairs it consumes.
    atom_window_chunk
        Number of atom windows to project per CUDA chunk.
    """
    from functools import partial

    from torch.nn.functional import one_hot

    from boltz.model.modules.encodersv2 import get_indexing_matrix, single_to_keys

    with torch.autocast("cuda", enabled=False):
        B, N, _ = feats["ref_pos"].shape
        atom_mask = feats["atom_pad_mask"].bool()
        atom_token_idx, atom_token_valid = atom_to_token_indices(feats)

        def gather_token_features(token_features: Tensor) -> Tensor:
            gather_idx = atom_token_idx.clamp(
                min=0, max=token_features.shape[1] - 1
            ).to(device=token_features.device)
            gathered = torch.gather(
                token_features,
                1,
                gather_idx.unsqueeze(-1).expand(-1, -1, token_features.shape[-1]),
            )
            valid = atom_token_valid.to(device=token_features.device)
            return gathered * valid.unsqueeze(-1).to(dtype=gathered.dtype)

        atom_ref_pos = feats["ref_pos"]
        atom_uid = feats["ref_space_uid"]

        atom_feats = [
            atom_ref_pos,
            feats["ref_charge"].unsqueeze(-1),
            feats["ref_element"],
        ]
        if not ae.use_no_atom_char:
            atom_feats.append(feats["ref_atom_name_chars"].reshape(B, N, 4 * 64))
        if ae.use_atom_backbone_feat:
            atom_feats.append(feats["atom_backbone_feat"])
        if ae.use_residue_feats_atoms:
            res_feats = torch.cat(
                [
                    feats["res_type"],
                    feats["modified"].unsqueeze(-1),
                    one_hot(feats["mol_type"], num_classes=4).float(),
                ],
                dim=-1,
            )
            atom_feats.append(gather_token_features(res_feats))

        atom_feats = torch.cat(atom_feats, dim=-1)

        c = ae.embed_atom_features(atom_feats)
        if mem_log is not None:
            mem_log("  dc: atom_encoder embedded atom features")

        W, H = ae.atoms_per_window_queries, ae.atoms_per_window_keys
        B, N = c.shape[:2]
        K = N // W
        keys_indexing_matrix = get_indexing_matrix(K, W, H, c.device)
        to_keys = partial(
            single_to_keys, indexing_matrix=keys_indexing_matrix, W=W, H=H
        )
        if mem_log is not None:
            mem_log("  dc: atom_encoder built key indexer")

        atom_ref_pos_queries = atom_ref_pos.view(B, K, W, 1, 3)
        atom_ref_pos_keys = to_keys(atom_ref_pos).view(B, K, 1, H, 3)

        d = atom_ref_pos_keys - atom_ref_pos_queries
        d_norm = torch.sum(d * d, dim=-1, keepdim=True)
        d_norm = 1 / (1 + d_norm)

        atom_mask_queries = atom_mask.view(B, K, W, 1)
        atom_mask_keys = (
            to_keys(atom_mask.unsqueeze(-1).float()).view(B, K, 1, H).bool()
        )
        atom_uid_queries = atom_uid.view(B, K, W, 1)
        atom_uid_keys = (
            to_keys(atom_uid.unsqueeze(-1).float()).view(B, K, 1, H).long()
        )
        v = (
            (
                atom_mask_queries
                & atom_mask_keys
                & (atom_uid_queries == atom_uid_keys)
            )
            .float()
            .unsqueeze(-1)
        )

        p = ae.embed_atompair_ref_pos(d) * v
        p = p + ae.embed_atompair_ref_dist(d_norm) * v
        p = p + ae.embed_atompair_mask(v) * v
        if mem_log is not None:
            mem_log("  dc: atom_encoder built base pair features")

        q = c

        if ae.structure_prediction:
            s_to_c = ae.s_to_c_trans(s_trunk.float())
            c = c + gather_token_features(s_to_c).to(c)

            Nt = z_cond.shape[1]
            atom_token_idx = atom_token_idx.clamp(min=0, max=Nt - 1)
            atom_token_queries = atom_token_idx.view(B, K, W)
            atom_token_query_valid = atom_token_valid.view(B, K, W)
            atom_token_keys = to_keys(atom_token_idx.float().unsqueeze(-1)).squeeze(-1).long()
            atom_token_keys = atom_token_keys.clamp(min=0, max=Nt - 1)
            atom_token_key_valid = to_keys(atom_token_valid.float().unsqueeze(-1)).squeeze(-1) > 0.5
            if mem_log is not None:
                mem_log("  dc: atom_encoder built compact token indices")

            ztp = ae.z_to_p_trans
            z_device = _module_device(ztp)
            kw = atom_window_chunk if atom_window_chunk is not None else chunk_rows
            kw = max(1, int(kw))
            pin = z_cond.device.type == "cpu" and _pin_memory_enabled()
            for k0 in range(0, K, kw):
                k1 = min(k0 + kw, K)
                q_idx = atom_token_queries[:, k0:k1].to(device=z_cond.device)
                k_idx = atom_token_keys[:, k0:k1].to(device=z_cond.device)
                z_pairs = []
                for batch_idx in range(B):
                    z_pairs.append(
                        z_cond[
                            batch_idx,
                            q_idx[batch_idx, :, :, None],
                            k_idx[batch_idx, :, None, :],
                        ]
                    )
                z_pair = torch.stack(z_pairs, dim=0)
                if z_pair.device != z_device:
                    z_pair = z_pair.to(device=z_device, non_blocking=pin)
                z_pair = ztp(z_pair.float())
                valid_pair = (
                    atom_token_query_valid[:, k0:k1, :, None]
                    & atom_token_key_valid[:, k0:k1, None, :]
                ).to(device=z_pair.device)
                z_pair = z_pair * valid_pair.unsqueeze(-1)
                p[:, k0:k1].add_(z_pair.to(dtype=p.dtype))
                del z_pair, z_pairs, valid_pair
                if mem_log is not None and (k0 == 0 or k1 == K):
                    mem_log(f"  dc: atom_encoder projected atom windows [{k0}:{k1}]")

        p = p + ae.c_to_p_trans_q(c.view(B, K, W, 1, c.shape[-1]))
        p = p + ae.c_to_p_trans_k(to_keys(c).view(B, K, 1, H, c.shape[-1]))
        p = p + ae.p_mlp(p)

    return q, c, p, to_keys


def _run_distogram_from_cpu(
    distogram_module,
    z_cpu: Tensor,
    chunk_rows: int,
    contact_only: bool = False,
) -> Tensor:
    """Run the distogram head row-by-row from CPU-backed pair features."""
    B, N, _, _ = z_cpu.shape
    linear = distogram_module.distogram
    if not linear.weight.is_cuda:
        distogram_module.cuda()
    device = linear.weight.device
    dtype = linear.weight.dtype
    if contact_only and (
        distogram_module.num_distograms != 1 or distogram_module.num_bins != 64
    ):
        raise ValueError("contact-only distogram streaming requires one 64-bin distogram")
    out_shape = (
        (B, N, N)
        if contact_only
        else (B, N, N, distogram_module.num_distograms, distogram_module.num_bins)
    )
    pdistogram_cpu = torch.empty(out_shape, dtype=dtype, device="cpu")
    for row_start in range(0, N, chunk_rows):
        row_end = min(row_start + chunk_rows, N)
        row_chunk = z_cpu[:, row_start:row_end, :, :].to(
            device=device, dtype=dtype, non_blocking=False
        )
        col_chunk = z_cpu[:, :, row_start:row_end, :].transpose(1, 2).to(
            device=device, dtype=dtype, non_blocking=False
        )
        logits = linear(row_chunk + col_chunk).reshape(
            B,
            row_end - row_start,
            N,
            distogram_module.num_distograms,
            distogram_module.num_bins,
        )
        if contact_only:
            contact_probability = torch.softmax(logits[:, :, :, 0], dim=-1)[
                :, :, :, :20
            ].sum(dim=-1)
            pdistogram_cpu[:, row_start:row_end].copy_(contact_probability.cpu())
            del contact_probability
        else:
            pdistogram_cpu[:, row_start:row_end].copy_(logits.cpu())
        del row_chunk, col_chunk, logits
    return pdistogram_cpu


def _run_distogram_from_cpu_rank_aligned(
    distogram_module,
    z_cpu: Tensor,
    chunk_rows: int,
    local_rows: int,
) -> Tensor:
    """Run stock distogram tiles with the same row boundaries as DAP ranks."""
    batch_size, num_tokens, _, _ = z_cpu.shape
    linear = distogram_module.distogram
    if not linear.weight.is_cuda:
        distogram_module.cuda()
    device = linear.weight.device
    dtype = linear.weight.dtype
    output = torch.empty(
        (
            batch_size,
            num_tokens,
            num_tokens,
            distogram_module.num_distograms,
            distogram_module.num_bins,
        ),
        dtype=dtype,
        device="cpu",
    )
    for rank_start in range(0, num_tokens, local_rows):
        rank_end = min(rank_start + local_rows, num_tokens)
        for row_start in range(rank_start, rank_end, chunk_rows):
            row_end = min(row_start + chunk_rows, rank_end)
            row_chunk = z_cpu[:, row_start:row_end].to(
                device=device, dtype=dtype, non_blocking=False
            )
            col_chunk = z_cpu[:, :, row_start:row_end].transpose(1, 2).to(
                device=device, dtype=dtype, non_blocking=False
            )
            logits = linear(row_chunk + col_chunk).reshape(
                batch_size,
                row_end - row_start,
                num_tokens,
                distogram_module.num_distograms,
                distogram_module.num_bins,
            )
            output[:, row_start:row_end].copy_(logits.cpu())
            del row_chunk, col_chunk, logits
    return output


def _phase2_comparison(expected: Tensor, actual: Tensor) -> dict:
    """Return exhaustive FP32 comparison metrics for a Phase 2 boundary."""
    if expected.shape != actual.shape:
        return {
            "shape_equal": False,
            "expected_shape": list(expected.shape),
            "actual_shape": list(actual.shape),
            "dtype_equal": expected.dtype == actual.dtype,
            "expected_dtype": str(expected.dtype),
            "actual_dtype": str(actual.dtype),
            "finite": False,
            "bitwise_equal": False,
            "mean_abs_error": None,
            "max_abs_error": None,
            "mean_rel_error": None,
            "max_rel_error": None,
        }
    expected_fp32 = expected.float()
    actual_fp32 = actual.float()
    finite = bool(
        torch.isfinite(expected_fp32).all() and torch.isfinite(actual_fp32).all()
    )
    difference = (expected_fp32 - actual_fp32).abs()
    denominator = torch.maximum(expected_fp32.abs(), actual_fp32.abs()).clamp_min(
        torch.finfo(torch.float32).eps
    )
    relative = difference / denominator
    metrics = {
        "shape_equal": True,
        "expected_shape": list(expected.shape),
        "actual_shape": list(actual.shape),
        "dtype_equal": expected.dtype == actual.dtype,
        "expected_dtype": str(expected.dtype),
        "actual_dtype": str(actual.dtype),
        "finite": finite,
        "bitwise_equal": bool(torch.equal(expected, actual)),
        "mean_abs_error": difference.mean().item(),
        "max_abs_error": difference.max().item(),
        "mean_rel_error": relative.mean().item(),
        "max_rel_error": relative.max().item(),
    }
    del expected_fp32, actual_fp32, difference, denominator, relative
    return metrics


def _run_distogram_from_row_shard(
    distogram_module,
    z_row: Tensor,
    original_size: int,
    chunk_rows: int,
    contact_only: bool = False,
) -> Tensor:
    """Run the stock distogram head while keeping its pair input row-sharded."""
    if z_row.ndim != 4:
        raise ValueError(f"expected four-dimensional z_row, got shape {tuple(z_row.shape)}")
    if z_row.dtype != torch.float32:
        raise TypeError(f"row-sharded distogram requires FP32 z, got {z_row.dtype}")
    if chunk_rows <= 0:
        raise ValueError("chunk_rows must be positive")

    batch_size, local_rows, column_size, _ = z_row.shape
    dap_size = get_dap_size()
    dap_rank = get_dap_rank()
    padded_rows = local_rows * dap_size
    if original_size <= 0 or original_size > padded_rows:
        raise ValueError(
            f"original_size must be in [1, {padded_rows}], got {original_size}"
        )
    if column_size not in (original_size, padded_rows):
        raise ValueError(
            f"pair column size must be original size {original_size} or padded "
            f"row size {padded_rows}, got {column_size}"
        )

    linear = distogram_module.distogram
    if linear.weight.device != z_row.device:
        raise ValueError("distogram module and row shard must be on the same device")
    if linear.weight.dtype != torch.float32:
        raise TypeError(
            f"row-sharded distogram requires FP32 weights, got {linear.weight.dtype}"
        )
    if contact_only and (
        distogram_module.num_distograms != 1 or distogram_module.num_bins != 64
    ):
        raise ValueError("contact-only distogram requires one 64-bin distogram")

    valid_rows = max(
        0,
        min(local_rows, original_size - dap_rank * local_rows),
    )
    output_shape = (
        (batch_size, local_rows, original_size)
        if contact_only
        else (
            batch_size,
            local_rows,
            original_size,
            distogram_module.num_distograms,
            distogram_module.num_bins,
        )
    )
    output = torch.zeros(output_shape, dtype=torch.float32, device=z_row.device)
    z_col = row_to_col(z_row.contiguous()).transpose(1, 2)
    for row_start in range(0, valid_rows, chunk_rows):
        row_end = min(row_start + chunk_rows, valid_rows)
        logits = linear(
            z_row[:, row_start:row_end, :original_size]
            + z_col[:, row_start:row_end, :original_size]
        ).reshape(
            batch_size,
            row_end - row_start,
            original_size,
            distogram_module.num_distograms,
            distogram_module.num_bins,
        )
        if contact_only:
            output[:, row_start:row_end].copy_(
                torch.softmax(logits[:, :, :, 0], dim=-1)[:, :, :, :20].sum(dim=-1)
            )
        else:
            output[:, row_start:row_end].copy_(logits)
        del logits
    del z_col
    return output


def inject_dap_into_model(model):
    """Inject DAP wrappers into a Boltz 2 model in-place.

    Replaces:
    - msa_module.layers[i] → DAPMSALayer (wraps MSALayer)
    - pairformer_module.layers[i] → DAPPairformerLayer (wraps PairformerLayer)
    - template_module.pairformer.layers[i] → DAPPairformerNoSeqLayer (wraps PairformerNoSeqLayer)

    Returns the model with a modified forward function.
    """
    dap_rank = get_dap_rank()
    dap_size = get_dap_size()

    if dap_size <= 1:
        print("[DAP] DAP size <= 1, wrapping layers anyway for bitwise reproducibility")

    # 1. Wrap MSA module layers
    if hasattr(model, 'msa_module'):
        msa = model.msa_module
        if hasattr(msa, '_orig_mod'):
            msa = msa._orig_mod
        for i in range(len(msa.layers)):
            original_layer = msa.layers[i]
            msa.layers[i] = DAPMSALayer(original_layer)
        if dap_rank == 0:
            print(f"  [DAP] Wrapped {len(msa.layers)} MSA layers")

    # 2. Wrap main pairformer layers
    if hasattr(model, 'pairformer_module'):
        pf = model.pairformer_module
        if hasattr(pf, '_orig_mod'):
            pf = pf._orig_mod
        for i in range(len(pf.layers)):
            original_layer = pf.layers[i]
            pf.layers[i] = DAPPairformerLayer(original_layer)
        if dap_rank == 0:
            print(f"  [DAP] Wrapped {len(pf.layers)} pairformer layers")

    # 3. Wrap template module's pairformer layers with DAP
    if hasattr(model, 'template_module') and model.use_templates:
        tmpl = model.template_module
        if hasattr(tmpl, '_orig_mod'):
            tmpl = tmpl._orig_mod
        pf_noseq = tmpl.pairformer
        for i in range(len(pf_noseq.layers)):
            original_layer = pf_noseq.layers[i]
            pf_noseq.layers[i] = DAPPairformerNoSeqLayer(original_layer)
        if dap_rank == 0:
            print(f"  [DAP] Wrapped {len(pf_noseq.layers)} template pairformer layers")

    # 4. Wrap confidence module's pairformer layers
    if hasattr(model, 'confidence_module') and model.confidence_prediction:
        inject_dap_into_confidence(model.confidence_module)
        if dap_rank == 0:
            print(f"  [DAP] Wrapped confidence pairformer layers")

    # 5. Store original forward and install DAP-aware forward
    model._original_forward = model.forward
    model.forward = _make_dap_forward(model)

    # 6. CRITICAL: Re-apply eval() so that newly created DAP wrapper modules
    #    (which default to training=True as new nn.Module instances) inherit
    #    training=False. Without this, dropout masks are randomly applied
    #    during inference, causing massive output divergence.
    if not model.training:
        model.eval()

    if dap_rank == 0:
        print(f"  [DAP] Installed DAP forward pass (scatter z before trunk, gather after)")

    return model


def _zs_checkpoint(label, z_scattered, s, original_N):
    """Save full z/s tensors from scattered z for comparison with baseline.
    
    z_scattered is [B, N/dap, N_padded, D]. We gather to full z.
    Returns dict with full tensors (bf16, CPU) for exact comparison.
    """
    dap_rank = get_dap_rank()
    dap_size = get_dap_size()

    # When trunk checkpoint saving is disabled, skip gather and heavy CPU copies.
    # torch.save is also skipped (see BOLTZ_SAVE_TRUNK_CKPT gate); placeholders only.
    if os.environ.get("BOLTZ_SAVE_TRUNK_CKPT", "0") != "1":
        if dap_rank == 0:
            _v = os.environ.get("BOLTZ_SAVE_TRUNK_CKPT", "")
            print(
                f"    [CKP] [{label}]  (skipped full gather — BOLTZ_SAVE_TRUNK_CKPT={_v})"
            )
        return {"z": torch.zeros(1), "s": torch.zeros(1)}
    if dap_size > 1:
        N_padded = ((original_N + dap_size - 1) // dap_size) * dap_size
        z_full = gather(z_scattered.contiguous(), dim=1, original_size=N_padded)
        if N_padded != original_N:
            z_full = z_full[:, :original_N, :original_N, :]
    else:
        z_full = z_scattered[:, :original_N, :original_N, :]
    
    zf = z_full.float()
    sf = s.float()
    
    if dap_rank == 0:
        print(f"    [CKP] [{label}]  z: mean={zf.mean():.6f} std={zf.std():.4f} "
              f"absmax={zf.abs().max():.4f}  |  s: mean={sf.mean():.6f} std={sf.std():.4f} "
              f"absmax={sf.abs().max():.4f}")
    
    result = {
        "z": z_full.cpu().to(torch.bfloat16),
        "s": s.cpu().to(torch.bfloat16),
    }
    del z_full
    return result


def _make_dap_forward(model):
    """Create a DAP-aware forward function that wraps the original.

    Key modifications:
    - After z_init is computed, scatter it across GPUs
    - After the trunk loop (template + MSA + pairformer), gather z back
    - Everything else (distogram, diffusion, structure, confidence) uses full z
    """
    original_forward = model._original_forward

    def dap_forward(
        feats,
        recycling_steps=0,
        num_sampling_steps=None,
        multiplicity_diffusion_train=1,
        diffusion_samples=1,
        max_parallel_samples=None,
        run_confidence_sequentially=False,
    ):
        dap_size = get_dap_size()
        dap_rank = get_dap_rank()
        cached_diffusion_config = getattr(model, "_dap_cached_diffusion_config", None)
        if cached_diffusion_config is not None:
            projection_rows = int(os.environ.get("BOLTZ_DC_TOKEN_BIAS_CHUNK", "256"))
            if (model.training or dap_size <= 1 or diffusion_samples != 1
                    or os.environ.get("BOLTZ_DIFFUSION_BIAS_LAYOUT") != "layerwise"
                    or projection_rows <= 0 or cached_diffusion_config["query_rows"] % projection_rows):
                raise ValueError("Cached diffusion requires distributed single-sample inference and aligned layerwise tiles")
            model._dap_cache_prediction_index = getattr(model, "_dap_cache_prediction_index", 0) + 1
        if os.environ.get("BOLTZ_DIFFUSION_BIAS_LAYOUT", "concat").lower() == "layerwise":
            if model.training or (dap_size > 1 and diffusion_samples != 1):
                raise ValueError("Layerwise token bias requires inference without distributed sample broadcasting")
            if _diffusion_cpu_storage_dtype() != torch.float32:
                raise ValueError("Layerwise token bias requires FP32 storage")
            diffusion_query_rows = (cached_diffusion_config["query_rows"] if cached_diffusion_config is not None
                                    else int(os.environ.get("BOLTZ_DIFFUSION_ATTN_Q_CHUNK", "0")))
            if not 0 < diffusion_query_rows < feats["token_pad_mask"].shape[1]:
                raise ValueError("Layerwise token bias requires bounded diffusion query chunks")
        sharded_trunk_handoff = os.environ.get(
            "BOLTZ_DAP_SHARDED_TRUNK_HANDOFF", "0"
        ).strip().lower() in {"1", "true", "yes", "on"}
        if sharded_trunk_handoff and (dap_size <= 1 or model.training):
            raise ValueError(
                "sharded trunk handoff requires distributed inference with DAP size > 1"
            )
        checkpoint_save = os.environ.get("BOLTZ_TRUNK_CHECKPOINT_SAVE", "")
        checkpoint_resume = os.environ.get("BOLTZ_TRUNK_CHECKPOINT_RESUME", "")
        checkpoint_context = None
        if checkpoint_save or checkpoint_resume:
            import trunk_checkpoint

            if checkpoint_save and checkpoint_resume:
                raise ValueError("Choose checkpoint save or resume, not both")
            checkpoint_error = None
            try:
                checkpoint_context = trunk_checkpoint.build_context(model, feats, {
                    "recycling_steps": recycling_steps, "num_sampling_steps": num_sampling_steps,
                    "diffusion_samples": diffusion_samples, "max_parallel_samples": max_parallel_samples,
                    "multiplicity_diffusion_train": multiplicity_diffusion_train,
                    "run_confidence_sequentially": run_confidence_sequentially,
                }, allow_mixed_precision=True)
                if checkpoint_resume:
                    trunk_checkpoint.inspect(checkpoint_resume, checkpoint_context)
            except Exception as exception:
                checkpoint_error = repr(exception)
            trunk_checkpoint._agree(checkpoint_error)
        _t0 = time.time()

        # ── Peak tracker: records every checkpoint and detects peak changes ──
        _timeline = []  # list of (elapsed, alloc, peak, label)
        _peak_changes = []  # list of (label, old_peak, new_peak) — when peak increases

        def _mem_log(label):
            """Log memory checkpoint and detect if this checkpoint set a new peak."""
            if dap_rank != 0:
                return
            elapsed = time.time() - _t0
            alloc = torch.cuda.memory_allocated() // 1024**2
            peak = torch.cuda.max_memory_allocated() // 1024**2
            prev_peak = _timeline[-1][2] if _timeline else 0
            _timeline.append((elapsed, alloc, peak, label))
            marker = ""
            if peak > prev_peak:
                _peak_changes.append((label, prev_peak, peak))
                marker = f"  ◀◀ NEW PEAK (+{peak - prev_peak}MB)"
            rss_mb, cgroup_used_mb, cgroup_limit_mb = _process_ram_mb()
            ram = f" | rss={rss_mb:>6d}MB" if rss_mb is not None else ""
            if cgroup_used_mb is not None:
                if cgroup_limit_mb is None:
                    ram += f" | cgroup={cgroup_used_mb:>6d}MB/max"
                else:
                    ram += f" | cgroup={cgroup_used_mb:>6d}/{cgroup_limit_mb}MB"
            print(f"    [TIMELINE] {elapsed:7.1f}s | alloc={alloc:>6d}MB | peak={peak:>6d}MB{ram} | {label}{marker}")

        def _print_peak_summary():
            """Print definitive summary of where the peak was set."""
            if dap_rank != 0 or not _timeline:
                return
            final_peak = _timeline[-1][2]
            print(f"\n{'='*72}")
            print(f"  PEAK SUMMARY  (final peak = {final_peak} MB)")
            print(f"{'='*72}")
            if _peak_changes:
                for label, old, new in _peak_changes:
                    print(f"    {old:>6d}MB → {new:>6d}MB  (+{new-old:>5d}MB)  at: {label}")
                # The last peak change is the one that set the final peak
                winner = _peak_changes[-1]
                print(f"\n  ▶▶ DEFINITIVE PEAK SET BY: \"{winner[0]}\"")
                print(f"     {winner[1]}MB → {winner[2]}MB (+{winner[2]-winner[1]}MB)")
            else:
                print("    No peak changes detected (peak was 0 throughout)")
            print(f"{'='*72}\n")

        # NOTE: We no longer short-circuit for dap_size <= 1.
        # scatter/gather are no-ops when dap_size=1, so the DAP path
        # produces identical results — but we need the checkpoint-saving
        # code below to run for divergence diagnosis.

        # ── Input embedding ──────────────────────────────────────────────
        # s_inputs [B, N, token_s] is small, computed on all GPUs.
        # z_init [B, N, N, C] is large. We compute it on all GPUs because
        # scatter() is an all-to-all collective requiring all ranks to
        # participate. We immediately scatter and delete the full tensor
        # so the transient peak is brief.
        with torch.set_grad_enabled(
            model.training and model.structure_prediction_training
        ):
            if dap_rank == 0:
                ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                print(f"\n{'='*72}")
                print(f"  MEMORY TIMELINE  (run started {ts})")
                print(f"{'='*72}")
                torch.cuda.reset_peak_memory_stats()
            _mem_log("start")

            s_inputs = model.input_embedder(feats)
            s_init = model.s_init(s_inputs)
            _mem_log("after input_embedder + s_init")

            # Compute masks (small, all GPUs)
            mask = feats["token_pad_mask"].float()
            pair_mask = mask[:, :, None] * mask[:, None, :]

            # ── Fine-grained checkpoint dict ──
            _checkpoints = {}

            # ── Compute z_init in DIRECT-LOCAL mode ──────────────────────
            # Each GPU computes ONLY its local shard of the N×N pairwise
            # tensor, never allocating the full N×N. This reduces peak
            # memory from O(N²) to O(N²/dap_size) per GPU.
            # Previous approach (scatter-first) still built full N×N
            # intermediates during rel_pos (one_hot expansions ≈ 30GB for
            # N=4642), causing OOM.
            
            original_N = s_inputs.shape[1]
            split_size = (original_N + dap_size - 1) // dap_size
            N_padded = split_size * dap_size
            row_start = dap_rank * split_size
            row_end = min(row_start + split_size, original_N)
            local_rows = row_end - row_start
            need_row_pad = split_size - local_rows  # >0 only for last rank when N not divisible

            def _pad_dim1(t):
                """Pad tensor along dim=1 if this rank has fewer rows than split_size."""
                if need_row_pad == 0:
                    return t
                pad_shape = list(t.shape)
                pad_shape[1] = need_row_pad
                return torch.cat([t, torch.zeros(pad_shape, dtype=t.dtype, device=t.device)], dim=1)

            # Step 1: Outer product — only local rows × all columns
            _z1 = model.z_init_1(s_inputs)  # [B, N, C] — small (~1MB)
            _z2 = model.z_init_2(s_inputs)  # [B, N, C] — small (~1MB)
            z_init_scattered = _pad_dim1(
                _z1[:, row_start:row_end, None, :] + _z2[:, None, :, :]
            )  # [B, split_size, N, C] — only local shard, never full N×N
            del _z1, _z2
            _mem_log("after z_init outer product (direct local)")

            # Sub-checkpoint: s_inputs
            _checkpoints["sub/s_inputs"] = {
                "s": s_inputs.cpu().to(torch.bfloat16),
                "z": torch.zeros(1),
            }
            if dap_rank == 0:
                sf = s_inputs.float()
                print(f"    [CKP] [sub/s_inputs]  s_inputs: mean={sf.mean():.6f} std={sf.std():.4f} absmax={sf.abs().max():.4f}  shape={list(sf.shape)}")

            # Sub-checkpoint: s_init
            _checkpoints["sub/s_init"] = {
                "s": s_init.cpu().to(torch.bfloat16),
                "z": torch.zeros(1),
            }
            if dap_rank == 0:
                sf = s_init.float()
                print(f"    [CKP] [sub/s_init]  s_init: mean={sf.mean():.6f} std={sf.std():.4f} absmax={sf.abs().max():.4f}  shape={list(sf.shape)}")

            # Sub-checkpoint: z_outer_product
            _checkpoints["sub/z_outer_product"] = _zs_checkpoint("sub/z_outer_product", z_init_scattered, s_init, original_N)

            # Step 2: Relative position encoding — local rows only
            _rp = model.rel_pos
            if sharded_trunk_handoff:
                _trunk_rel_pos_chunk = int(
                    os.environ.get("BOLTZ_TRUNK_REL_POS_CHUNK", "16")
                )
                z_init_scattered = _add_relative_position_encoding_to_row_shard_(
                    _rp,
                    feats,
                    z_init_scattered,
                    original_size=original_N,
                    global_row_start=row_start,
                    valid_rows=local_rows,
                    chunk_rows=_trunk_rel_pos_chunk,
                )
            else:
                _rpe_inputs = relative_position_inputs_for_rows(
                    _rp,
                    feats,
                    row_start=row_start,
                    row_end=row_end,
                )
                _rpe_local = _rp.linear_layer(_rpe_inputs)
                del _rpe_inputs
                z_init_scattered = z_init_scattered + _pad_dim1(_rpe_local)
                del _rpe_local

            # For diffusion_conditioning (rank 0 only, later): recompute
            # full rel_pos on CPU. rel_pos weights are tiny (~70KB) so
            # the CPU↔GPU transfer is negligible.
            if dap_rank == 0 and not sharded_trunk_handoff:
                with torch.no_grad():
                    _rp_feats_cpu = {k: feats[k].cpu() for k in
                                     ("asym_id", "residue_index", "entity_id",
                                      "token_index", "sym_id", "cyclic_period")}
                    model.rel_pos.cpu()
                    relative_position_encoding = _run_relative_position_encoding_to_cpu(
                        model.rel_pos,
                        _rp_feats_cpu,
                        int(os.environ.get("BOLTZ_DC_REL_POS_CHUNK", "64")),
                    )
                    model.rel_pos.cuda()
                    del _rp_feats_cpu
            else:
                relative_position_encoding = None
            _mem_log("after rel_pos_enc (direct local)")

            # Sub-checkpoint: z after rel_pos
            _checkpoints["sub/z_after_rel_pos"] = _zs_checkpoint("sub/z_after_rel_pos", z_init_scattered, s_init, original_N)

            # Step 3: Token bonds — local rows only
            _compact_pair_features = feats.get("_compact_pair_features")
            if _compact_pair_features is None:
                _pair_tile = None
                _tb_local = feats["token_bonds"][:, row_start:row_end, :].float()
            else:
                _pair_tile = _compact_pair_features.materialize_tile(
                    row_start,
                    min(row_end, original_N),
                    device=s_init.device,
                )
                _tb_local = _pair_tile["token_bonds"].float()
            z_init_scattered = z_init_scattered + _pad_dim1(model.token_bonds(_tb_local))
            del _tb_local
            if model.bond_type_feature:
                if _pair_tile is None:
                    _tbt_local = feats["type_bonds"][:, row_start:row_end, :].long()
                else:
                    _tbt_local = _pair_tile["type_bonds"].long()
                z_init_scattered = z_init_scattered + _pad_dim1(model.token_bonds_type(_tbt_local))
                del _tbt_local
            _mem_log("after token_bonds (direct local)")

            # Sub-checkpoint: z after token_bonds
            _checkpoints["sub/z_after_token_bonds"] = _zs_checkpoint("sub/z_after_token_bonds", z_init_scattered, s_init, original_N)

            # Step 4: Contact conditioning — local rows only
            if _pair_tile is None:
                _contact_conditioning = feats["contact_conditioning"][:, row_start:row_end]
                _contact_threshold = feats["contact_threshold"][:, row_start:row_end]
            else:
                _contact_conditioning = _pair_tile["contact_conditioning"]
                _contact_threshold = _pair_tile["contact_threshold"]
            cc_feats_local = {
                "contact_conditioning": _pad_dim1(_contact_conditioning),
                "contact_threshold": _pad_dim1(_contact_threshold),
            }
            del _contact_conditioning, _contact_threshold, _pair_tile
            if sharded_trunk_handoff:
                _trunk_contact_chunk = int(
                    os.environ.get("BOLTZ_TRUNK_CONTACT_CHUNK", "16")
                )
                z_init_scattered = _add_contact_conditioning_to_row_shard_(
                    model.contact_conditioning,
                    cc_feats_local,
                    z_init_scattered,
                    chunk_rows=_trunk_contact_chunk,
                )
            else:
                _z_component = model.contact_conditioning(cc_feats_local)
                z_init_scattered = z_init_scattered + _z_component
                del _z_component
            del cc_feats_local
            torch.cuda.empty_cache()
            _mem_log("after contact_conditioning (direct local, all z_init done)")

            # Sub-checkpoint: z after contact_conditioning (= full z_init)
            _checkpoints["sub/z_after_contact_cond"] = _zs_checkpoint("sub/z_after_contact_cond", z_init_scattered, s_init, original_N)

            # Initialize recycling tensors as SCATTERED
            s = torch.zeros_like(s_init)
            z_scattered = torch.zeros_like(z_init_scattered)
            pair_mask_scattered = scatter(pair_mask, dim=1)

            # Full init checkpoint (same as sub/z_after_contact_cond)
            cp = _zs_checkpoint("init", z_init_scattered, s_init, original_N)
            _checkpoints["init"] = cp

            if model.run_trunk_and_structure:
                if checkpoint_resume:
                    del z_scattered, s
                    restored_trunk = trunk_checkpoint.load(
                        checkpoint_resume, checkpoint_context, s_inputs.device
                    )
                    z_scattered = restored_trunk.pop("z")
                    s = restored_trunk.pop("s")
                    s_inputs = restored_trunk.pop("s_inputs")
                    del restored_trunk
                    _mem_log("resumed completed FP32 trunk")
                for i in range(0 if checkpoint_resume else recycling_steps + 1):
                    with torch.set_grad_enabled(
                        model.training
                        and model.structure_prediction_training
                        and (i == recycling_steps)
                    ):
                        if (
                            model.training
                            and (i == recycling_steps)
                            and torch.is_autocast_enabled()
                        ):
                            torch.clear_autocast_cache()

                        # Recycling: s is full (small), z stays scattered
                        s = s_init + model.s_recycle(model.s_norm(s))
                        z_scattered = z_init_scattered + model.z_recycle(
                            model.z_norm(z_scattered)
                        )

                        cp = _zs_checkpoint(f"R{i}/after_recycle", z_scattered, s, original_N)
                        _checkpoints[f"R{i}/after_recycle"] = cp

                        # Template module
                        if model.use_templates:
                            tmpl = model.template_module
                            if hasattr(tmpl, '_orig_mod') and not model.training:
                                tmpl = tmpl._orig_mod
                            z_scattered = _run_template_dap(
                                tmpl, z_scattered, feats, pair_mask,
                                model.use_kernels, original_N, _mem_log,
                                recycle_idx=i,
                            )
                            _mem_log("after template_module")

                            cp = _zs_checkpoint(f"R{i}/after_template", z_scattered, s, original_N)
                            _checkpoints[f"R{i}/after_template"] = cp

                        # MSA module
                        # CRITICAL: Original Boltz2 does z = z + msa_module(z).
                        # msa_module internally modifies z (z += opm, z = pf(z)),
                        # returns z_modified, and the outer call adds z_before again.
                        # _run_msa_dap must match this: z_final = z_before + msa_result.
                        msa = model.msa_module
                        if hasattr(msa, '_orig_mod') and not model.training:
                            msa = msa._orig_mod

                        _save_gran_ckpt = os.environ.get("BOLTZ_SAVE_GRAN_CKPT", "0") == "1"
                        _msa_mutates_input = not (
                            msa.training and torch.is_grad_enabled()
                        )
                        if _msa_mutates_input:
                            z_before_msa = None
                            z_before_msa_cpu = z_scattered.detach().to(device="cpu")
                        else:
                            z_before_msa = z_scattered
                            z_before_msa_cpu = None
                        z_msa_out = _run_msa_dap(
                            msa, z_scattered, s_inputs, feats,
                            pair_mask, model.use_kernels,
                            mem_log=_mem_log,
                            _msa_diag=(i == 0),
                        )

                        # Save msa/z_out_residual granular checkpoint
                        # ALL ranks must participate in gather (collective op)
                        if i == 0 and _save_gran_ckpt:
                            _z_msa_full = gather(z_msa_out.contiguous(), dim=1, original_size=N_padded)
                            if dap_rank == 0:
                                _msa_gran = getattr(_run_msa_dap, '_gran_ckpts', {})
                                _msa_gran["msa/z_out_residual"] = _z_msa_full[:, :original_N, :original_N, :].cpu().to(torch.bfloat16)
                                _run_msa_dap._gran_ckpts = _msa_gran
                            del _z_msa_full

                        if z_before_msa_cpu is not None:
                            _add_cpu_row_residual_(
                                z_msa_out,
                                z_before_msa_cpu,
                                _env_positive_int("BOLTZ_MSA_RESIDUAL_CHUNK") or 32,
                            )
                            z_scattered = z_msa_out
                        else:
                            z_scattered = z_before_msa + z_msa_out
                        del z_before_msa, z_before_msa_cpu, z_msa_out
                        _mem_log("after msa_module")

                        cp = _zs_checkpoint(f"R{i}/after_msa", z_scattered, s, original_N)
                        _checkpoints[f"R{i}/after_msa"] = cp

                        maybe_capture_pairformer_entry(
                            recycle_index=i,
                            z=z_scattered,
                            s=s,
                            token_mask=mask,
                            pair_mask=pair_mask_scattered,
                            original_n=original_N,
                        )

                        # Merge MSA granular checkpoints into granular_ckpts.pt
                        if i == 0 and _save_gran_ckpt and dap_rank == 0 and hasattr(_run_msa_dap, '_gran_ckpts') and _run_msa_dap._gran_ckpts:
                            import os as _os
                            _out_dir = _os.environ.get('BOLTZ_OUT_DIR', '')
                            if _out_dir:
                                _gran_path = _os.path.join(_out_dir, 'granular_ckpts.pt')
                                if _os.path.exists(_gran_path):
                                    _existing = torch.load(_gran_path, map_location='cpu')
                                else:
                                    _existing = {}
                                # Trim padded tensors to original_N
                                for _gk, _gv in _run_msa_dap._gran_ckpts.items():
                                    if _gv.dim() == 4 and _gv.shape[1] > original_N:
                                        _gv = _gv[:, :original_N, :original_N, :]
                                    _existing[_gk] = _gv
                                torch.save(_existing, _gran_path)
                                print(f"      [GRAN] Merged {len(_run_msa_dap._gran_ckpts)} MSA checkpoints → {len(_existing)} total in {_gran_path}")
                                del _existing
                            _run_msa_dap._gran_ckpts = {}  # clear

                        # Pairformer module
                        pf = model.pairformer_module
                        if hasattr(pf, '_orig_mod') and not model.training:
                            pf = pf._orig_mod

                        s, z_scattered = _run_pairformer_dap(
                            pf, s, z_scattered, mask, pair_mask,
                            model.use_kernels,
                            mem_log=_mem_log
                        )
                        _mem_log("after pairformer_module")

                        cp = _zs_checkpoint(f"R{i}/after_pairformer", z_scattered, s, original_N)
                        _checkpoints[f"R{i}/after_pairformer"] = cp

                if not model.training:
                    _log_trunk_diffusion_memory("before_trunk_cleanup", {
                        "recycling_pair": z_init_scattered, "recycling_single": s_init,
                        "pair_mask": pair_mask, "pair_mask_scattered": pair_mask_scattered,
                        "final_pair": z_scattered, "final_single": s, "single_inputs": s_inputs,
                    })
                    del z_init_scattered, s_init, pair_mask, pair_mask_scattered
                    torch.cuda.empty_cache()
                    _log_trunk_diffusion_memory("after_trunk_cleanup", {
                        "final_pair": z_scattered, "final_single": s, "single_inputs": s_inputs,
                    })

                if checkpoint_save:
                    trunk_checkpoint.save(checkpoint_save, {
                        "z": z_scattered, "s": s, "s_inputs": s_inputs,
                    }, checkpoint_context)
                    _mem_log("saved completed FP32 trunk")

                phase2_report_path = os.environ.get("BOLTZ_PHASE2_SHADOW_REPORT", "")
                phase2_shadow = bool(phase2_report_path)
                if sharded_trunk_handoff and phase2_shadow:
                    raise ValueError(
                        "sharded trunk handoff cannot be combined with Phase 2 shadow"
                    )
                shadow_z_cpu = None
                shadow_logits_cpu = None
                shadow_contacts_cpu = None
                if phase2_shadow:
                    if z_scattered.dtype != torch.float32:
                        raise TypeError(
                            f"Phase 2 shadow requires FP32 trunk z, got {z_scattered.dtype}"
                        )
                    distogram_chunk = int(
                        os.environ.get("BOLTZ_DISTOGRAM_CHUNK", "256")
                    )
                    local_rows = z_scattered.shape[1]
                    shadow_z_full = gather(
                        z_scattered.contiguous(), dim=1, original_size=N_padded
                    )
                    shadow_logits_row = _run_distogram_from_row_shard(
                        model.distogram_module,
                        z_scattered,
                        original_size=original_N,
                        chunk_rows=distogram_chunk,
                    )
                    shadow_contacts_row = _run_distogram_from_row_shard(
                        model.distogram_module,
                        z_scattered,
                        original_size=original_N,
                        chunk_rows=distogram_chunk,
                        contact_only=True,
                    )
                    shadow_logits_cpu = gather_to_rank0_cpu(
                        shadow_logits_row, dim=1, original_size=original_N
                    )
                    shadow_contacts_cpu = gather_to_rank0_cpu(
                        shadow_contacts_row, dim=1, original_size=original_N
                    )
                    if dap_rank == 0:
                        shadow_z_cpu = shadow_z_full[
                            :, :original_N, :original_N
                        ].cpu().contiguous()
                    del shadow_z_full, shadow_logits_row, shadow_contacts_row
                    torch.cuda.empty_cache()
                    _mem_log("after Phase 2 live-shard shadow outputs")

                sharded_pdistogram = None
                z_trunk_row_cpu = None
                z_cond_cpu = None
                if sharded_trunk_handoff:
                    distogram_chunk = int(
                        os.environ.get("BOLTZ_DISTOGRAM_CHUNK", "256")
                    )
                    pdistogram_row = _run_distogram_from_row_shard(
                        model.distogram_module,
                        z_scattered,
                        original_size=original_N,
                        chunk_rows=distogram_chunk,
                        contact_only=True,
                    )
                    sharded_pdistogram = gather_to_rank0_cpu(
                        pdistogram_row,
                        dim=1,
                        original_size=original_N,
                    )
                    del pdistogram_row
                    model.distogram_module.cpu()
                    torch.cuda.empty_cache()
                    _mem_log("after sharded contact distogram gather")

                    dc = model.diffusion_conditioning
                    if hasattr(model, "structure_module"):
                        model.structure_module.cpu()
                    if hasattr(model, "confidence_module"):
                        model.confidence_module.cpu()
                    dc.atom_encoder.cpu()
                    for layer in dc.token_trans_proj_z:
                        layer.cpu()
                    for layer in dc.atom_enc_proj_z:
                        layer.cpu()
                    for layer in dc.atom_dec_proj_z:
                        layer.cpu()
                    torch.cuda.empty_cache()
                    _mem_log("after sharded-handoff downstream module offload")

                # ── OFFLOAD TRUNK WEIGHTS TO CPU FIRST ─────────────────────
                # Free ~22GB of model weights BEFORE gathering full z,
                # otherwise trunk weights + full z exceed GPU memory for 9MME.
                trunk_module_names = [
                    "input_embedder", "s_init", "z_init_1", "z_init_2",
                    "rel_pos", "token_bonds", "contact_conditioning",
                    "s_recycle", "z_recycle", "s_norm", "z_norm",
                    "msa_module", "pairformer_module", "template_module",
                ]
                if sharded_trunk_handoff:
                    trunk_module_names.remove("rel_pos")
                if model.bond_type_feature:
                    trunk_module_names.append("token_bonds_type")
                for name in trunk_module_names:
                    if hasattr(model, name):
                        getattr(model, name).cpu()
                torch.cuda.empty_cache()
                _mem_log("after trunk offload to CPU")

                if sharded_trunk_handoff:
                    dc = model.diffusion_conditioning
                    dc.pairwise_conditioner.to(z_scattered.device)
                    pairwise_chunk = int(
                        os.environ.get("BOLTZ_DC_PAIRWISE_CHUNK", "512")
                    )
                    transition_chunk = _env_positive_int(
                        "BOLTZ_DC_PAIRWISE_TRANSITION_CHUNK"
                    )
                    if transition_chunk is None:
                        transition_chunk = _env_positive_int(
                            "BOLTZ_TRANSITION_Z_CHUNK"
                        )
                    z_trunk_row_cpu = _run_pairwise_conditioner_on_row_shard_inplace(
                        dc.pairwise_conditioner,
                        model.rel_pos,
                        feats,
                        z_scattered,
                        original_size=original_N,
                        global_row_start=row_start,
                        chunk_rows=pairwise_chunk,
                        transition_chunk=transition_chunk,
                    )
                    model.rel_pos.cpu()
                    dc.pairwise_conditioner.cpu()
                    torch.cuda.empty_cache()
                    _mem_log("after in-place row-sharded pairwise conditioning")
                    z_cond_cpu = gather_to_rank0_cpu(
                        z_scattered.contiguous(),
                        dim=1,
                        original_size=original_N,
                    )
                    z_cpu = None
                    del z_scattered
                    torch.cuda.empty_cache()
                    _mem_log("after gather conditioned z to rank0 CPU")
                else:
                    # ── GATHER z to rank 0 CPU and TRIM to original_N ──
                    z_cpu = gather_to_rank0_cpu(
                        z_scattered.contiguous(), dim=1, original_size=original_N
                    )
                    del z_scattered
                    torch.cuda.empty_cache()
                    _mem_log("after gather z to rank0 CPU")
                    if dap_rank == 0 and N_padded != original_N:
                        z_cpu = z_cpu[:, :, :original_N, :].contiguous()

                phase3_trunk_artifact_path = os.environ.get(
                    "BOLTZ_PHASE3_TRUNK_ARTIFACT",
                    "",
                )
                if dap_rank == 0 and phase2_shadow and phase3_trunk_artifact_path:
                    os.makedirs(
                        os.path.dirname(phase3_trunk_artifact_path),
                        exist_ok=True,
                    )
                    torch.save(
                        {
                            "format_version": 1,
                            "scope": "validated_live_fp32_trunk",
                            "original_tokens": original_N,
                            "padded_tokens": N_padded,
                            "dap_size": dap_size,
                            "s": s.detach().cpu().contiguous(),
                            "z": z_cpu,
                        },
                        phase3_trunk_artifact_path,
                    )
                    print(
                        "    [PHASE3] saved validated FP32 trunk artifact: "
                        f"{phase3_trunk_artifact_path}",
                        flush=True,
                    )

                # Save checkpoints only when explicitly enabled; these artifacts are
                # very large and not needed for normal inference runs.
                _save_trunk_ckpt = os.environ.get("BOLTZ_SAVE_TRUNK_CKPT", "0") == "1"
                if dap_rank == 0 and _save_trunk_ckpt:
                    import os as _os
                    _out_dir = _os.environ.get('BOLTZ_OUT_DIR', '')
                    if _out_dir:
                        _ckpt_path = _os.path.join(_out_dir, 'trunk_checkpoints.pt')
                        torch.save(_checkpoints, _ckpt_path)
                        _ckpt_size = _os.path.getsize(_ckpt_path) / (1024**2)
                        print(f"    [CKP] Saved {len(_checkpoints)} full-tensor checkpoints to {_ckpt_path} ({_ckpt_size:.0f} MB)")

            if dap_rank == 0:
                distogram_chunk = int(os.environ.get("BOLTZ_DISTOGRAM_CHUNK", "256"))
                phase2_report = None
                if sharded_trunk_handoff:
                    if sharded_pdistogram is None or z_cond_cpu is None:
                        raise RuntimeError(
                            "sharded trunk handoff did not produce rank-0 pair outputs"
                        )
                    pdistogram = sharded_pdistogram
                elif phase2_shadow:
                    stock_logits_cpu = _run_distogram_from_cpu(
                        model.distogram_module,
                        z_cpu,
                        distogram_chunk,
                    )
                    stock_rank_logits_cpu = _run_distogram_from_cpu_rank_aligned(
                        model.distogram_module,
                        z_cpu,
                        distogram_chunk,
                        local_rows,
                    )
                if not sharded_trunk_handoff:
                    pdistogram = _run_distogram_from_cpu(
                        model.distogram_module,
                        z_cpu,
                        distogram_chunk,
                        contact_only=dap_size > 1,
                    )
                dict_out = {"pdistogram": pdistogram, "s": s}

                if phase2_shadow:
                    from dap_confidence import _stream_contact_probability

                    candidate_consumer = _stream_contact_probability(
                        shadow_logits_cpu[:, :, :, 0],
                        torch.device("cuda:0"),
                        int(os.environ.get("BOLTZ_CONF_DISTOGRAM_ROW_CHUNK", "16")),
                    ).cpu()
                    stock_consumer = _stream_contact_probability(
                        stock_logits_cpu[:, :, :, 0],
                        torch.device("cuda:0"),
                        int(os.environ.get("BOLTZ_CONF_DISTOGRAM_ROW_CHUNK", "16")),
                    ).cpu()
                    comparisons = {
                        "trunk_reconstruction": _phase2_comparison(
                            z_cpu, shadow_z_cpu
                        ),
                        "candidate_vs_rank_aligned_logits": _phase2_comparison(
                            stock_rank_logits_cpu, shadow_logits_cpu
                        ),
                        "candidate_vs_established_logits": _phase2_comparison(
                            stock_logits_cpu, shadow_logits_cpu
                        ),
                        "candidate_vs_established_contacts": _phase2_comparison(
                            pdistogram, shadow_contacts_cpu
                        ),
                        "next_consumer_candidate_vs_stock": _phase2_comparison(
                            stock_consumer, candidate_consumer
                        ),
                        "candidate_consumer_vs_distributed_contacts": _phase2_comparison(
                            candidate_consumer, shadow_contacts_cpu
                        ),
                    }
                    exact_names = (
                        "trunk_reconstruction",
                        "candidate_vs_rank_aligned_logits",
                    )
                    tolerance_names = (
                        "candidate_vs_established_logits",
                        "candidate_vs_established_contacts",
                        "next_consumer_candidate_vs_stock",
                        "candidate_consumer_vs_distributed_contacts",
                    )
                    tolerances = {
                        "logits": {"max_abs_error": 5e-6, "mean_abs_error": 1e-6},
                        "contacts": {"max_abs_error": 5e-7, "mean_abs_error": 1e-7},
                    }
                    passed = all(
                        comparisons[name]["shape_equal"]
                        and comparisons[name]["dtype_equal"]
                        and comparisons[name]["finite"]
                        and comparisons[name]["bitwise_equal"]
                        for name in exact_names
                    )
                    for name in tolerance_names:
                        tolerance = (
                            tolerances["logits"]
                            if "logits" in name
                            else tolerances["contacts"]
                        )
                        metrics = comparisons[name]
                        passed = passed and bool(
                            metrics["shape_equal"]
                            and metrics["dtype_equal"]
                            and metrics["finite"]
                            and metrics["max_abs_error"] <= tolerance["max_abs_error"]
                            and metrics["mean_abs_error"] <= tolerance["mean_abs_error"]
                        )
                    phase2_report = {
                        "format_version": 1,
                        "complete": True,
                        "passed": passed,
                        "scope": "live_trunk_distogram_shadow",
                        "production_path_selected": False,
                        "phase2_complete": False,
                        "next_consumer_checked": "confidence contact probability",
                        "dap_size": dap_size,
                        "original_tokens": original_N,
                        "padded_tokens": N_padded,
                        "local_rows": local_rows,
                        "trunk_dtype": str(z_cpu.dtype),
                        "distogram_weight_dtype": str(
                            model.distogram_module.distogram.weight.dtype
                        ),
                        "chunk_rows": distogram_chunk,
                        "tolerances": tolerances,
                        "comparisons": comparisons,
                    }
                    os.makedirs(os.path.dirname(phase2_report_path), exist_ok=True)
                    with open(phase2_report_path, "w") as report_file:
                        json.dump(phase2_report, report_file, indent=2, sort_keys=True)
                    print(
                        f"    [PHASE2] live trunk/distogram shadow passed={passed}; "
                        f"report={phase2_report_path}",
                        flush=True,
                    )
                    del stock_logits_cpu, stock_rank_logits_cpu
                    del candidate_consumer, stock_consumer
                    del shadow_z_cpu, shadow_logits_cpu, shadow_contacts_cpu

                # Offload distogram after use
                model.distogram_module.cpu()
                torch.cuda.empty_cache()
                _mem_log("after distogram (streamed to CPU, offloaded)")
            else:
                dict_out = {"s": s}

            if phase2_shadow:
                import torch.distributed as tdist

                phase2_passed = torch.tensor(
                    [int(phase2_report["passed"]) if dap_rank == 0 else 0],
                    dtype=torch.int32,
                    device=torch.device(f"cuda:{dap_rank}"),
                )
                tdist.broadcast(phase2_passed, src=0)
                if not phase2_passed.item():
                    raise RuntimeError(
                        f"Phase 2 live trunk/distogram shadow failed; "
                        f"report={phase2_report_path}"
                    )
                raise Phase2ShadowComplete(
                    f"Phase 2 live trunk/distogram shadow passed: {phase2_report_path}"
                )

            # GPU 0: runs distogram, diffusion, structure (GPU 1 waits)
            # Both GPUs: participate in confidence pairformer DAP

            if (
                model.run_trunk_and_structure
                and ((not model.training) or model.confidence_prediction)
                and (not model.skip_run_structure)
            ):
                if dap_rank == 0:
                    # ── Inlined diffusion_conditioning with chunked Transitions ──
                    _mem_log("before diffusion_conditioning (inlined)")
                    dc = model.diffusion_conditioning

                    # Keep only the pairwise conditioner resident while building z_cond.
                    # The 465335 frontier entered this block with little headroom, and
                    # these modules are not needed until later conditioning stages.
                    if hasattr(model, 'structure_module'):
                        model.structure_module.cpu()
                    if hasattr(model, 'confidence_module'):
                        model.confidence_module.cpu()
                    dc.atom_encoder.cpu()
                    for layer in dc.token_trans_proj_z:
                        layer.cpu()
                    for layer in dc.atom_enc_proj_z:
                        layer.cpu()
                    for layer in dc.atom_dec_proj_z:
                        layer.cpu()
                    torch.cuda.empty_cache()
                    _mem_log("  dc: downstream modules offloaded before pairwise")

                    # ① PairwiseConditioning — row-chunked and CPU-staged.
                    # A full [1,N,N,128] CUDA z_cond is too large for pentadecamer rank 0.
                    _mem_log("  dc: before pairwise_conditioner")
                    pw = dc.pairwise_conditioner
                    pairwise_chunk = int(os.environ.get("BOLTZ_DC_PAIRWISE_CHUNK", "512"))
                    cpu_storage_dtype = _diffusion_cpu_storage_dtype()
                    transition_chunk = _env_positive_int("BOLTZ_DC_PAIRWISE_TRANSITION_CHUNK")
                    if transition_chunk is None:
                        transition_chunk = _env_positive_int("BOLTZ_TRANSITION_Z_CHUNK")
                    if sharded_trunk_handoff:
                        if z_cond_cpu.dtype != cpu_storage_dtype:
                            raise TypeError(
                                "sharded conditioned pair storage dtype does not match "
                                f"the requested CPU storage dtype: {z_cond_cpu.dtype} != "
                                f"{cpu_storage_dtype}"
                            )
                    else:
                        z_cond_cpu = _run_pairwise_conditioner_to_cpu(
                            pw,
                            z_cpu,
                            relative_position_encoding,
                            pairwise_chunk,
                            transition_chunk,
                            storage_dtype=cpu_storage_dtype,
                            mem_log=_mem_log,
                        )
                        del relative_position_encoding
                    torch.cuda.empty_cache()
                    _mem_log("  dc: after pairwise_conditioner (CPU-staged)")

                    # Offload pairwise_conditioner weights — no longer needed
                    pw.cpu()
                    torch.cuda.empty_cache()
                    _mem_log("  dc: pairwise_conditioner offloaded")

                    # ② Token transformer biases — streamed from CPU-staged z_cond.
                    _mem_log("  dc: before token_trans_bias")
                    layers = dc.token_trans_proj_z
                    chunk_size_ttb = int(os.environ.get("BOLTZ_DC_TOKEN_BIAS_CHUNK", "256"))
                    token_bias_layout = os.environ.get(
                        "BOLTZ_DIFFUSION_BIAS_LAYOUT",
                        "concat",
                    ).lower()
                    token_trans_bias_cpu = _run_token_trans_bias_from_zcond_cpu(
                        layers,
                        z_cond_cpu,
                        chunk_size_ttb,
                        layout=token_bias_layout,
                        storage_dtype=cpu_storage_dtype,
                    )
                    _mem_log(
                        "  dc: after token_trans_bias "
                        f"(layout={token_bias_layout}, storage={cpu_storage_dtype}, "
                        "CPU-staged z_cond)"
                    )

                    # Offload token_trans_proj_z weights
                    for layer in dc.token_trans_proj_z:
                        layer.cpu()
                    torch.cuda.empty_cache()
                    _mem_log("  dc: struct/conf/bias all offloaded before atom_enc")

                    # ③ AtomEncoder — indexed atom-window z_to_p streaming.
                    _mem_log("  dc: before atom_encoder (indexed atom-window z_to_p)")
                    ae = dc.atom_encoder
                    ae.cuda()
                    chunk_ae = max(1, int(os.environ.get("BOLTZ_DC_ATOM_ENCODER_CHUNK", "256")))
                    atom_window_chunk = max(1, int(os.environ.get("BOLTZ_DC_ATOM_WINDOW_CHUNK", "16")))
                    q, c, p, to_keys = _run_atom_encoder_with_chunked_zcond(
                        ae,
                        feats,
                        s,
                        z_cond_cpu,
                        chunk_ae,
                        atom_window_chunk=atom_window_chunk,
                        mem_log=_mem_log,
                    )
                    del z_cond_cpu
                    torch.cuda.empty_cache()
                    _mem_log("  dc: after atom_encoder")




                    # Offload diffusion_conditioning weights
                    dc.cpu()
                    torch.cuda.empty_cache()
                    _mem_log("after diffusion_conditioning (offloaded)")

                    if not sharded_trunk_handoff:
                        dict_out["z"] = z_cpu
                        _mem_log("  mem_opt: z already on CPU, stored in dict_out")

                    # token_trans_bias already on CPU (offloaded before atom_encoder)
                    _mem_log("  mem_opt: token_trans_bias already on CPU")

                    # Reload atom_enc/dec_proj_z for bias computation
                    for layer in dc.atom_enc_proj_z:
                        layer.cuda()
                    for layer in dc.atom_dec_proj_z:
                        layer.cuda()

                    # Compute atom biases (p is from atom_encoder, on GPU)
                    atom_enc_bias = torch.cat([layer(p) for layer in dc.atom_enc_proj_z], dim=-1)
                    atom_dec_bias = torch.cat([layer(p) for layer in dc.atom_dec_proj_z], dim=-1)
                    del p
                    # Offload atom proj z after use
                    for layer in dc.atom_enc_proj_z:
                        layer.cpu()
                    for layer in dc.atom_dec_proj_z:
                        layer.cpu()
                    torch.cuda.empty_cache()
                    _mem_log("  dc: atom biases computed, proj offloaded")

                    diffusion_conditioning = {
                        "q": q, "c": c, "to_keys": to_keys,
                        "atom_enc_bias": atom_enc_bias,
                        "atom_dec_bias": atom_dec_bias,
                        "token_trans_bias": token_trans_bias_cpu,
                    }
                    del token_trans_bias_cpu

                    _mem_log("before structure_module.sample")

                # ── Distributed Diffusion Sampling ──────────────────────
                # Instead of rank 0 running ALL diffusion samples alone,
                # broadcast conditioning to all ranks and split samples.
                # Each rank runs an independent subset → ~4× memory savings.
                import torch.distributed as _tdist

                if dap_size > 1 and diffusion_samples > 1:
                    # ── Phase 1: Broadcast conditioning data to all ranks ──
                    _mem_log("  dist_diff: broadcasting conditioning")

                    # s and s_inputs are already replicated on all ranks after trunk.
                    # (s is replicated by pairformer DAP, s_inputs computed on all ranks)
                    # No broadcast needed for either.

                    # Broadcast diffusion_conditioning dict
                    if dap_rank == 0:
                        # Send shape metadata first
                        dc_meta = {}
                        for k, v in diffusion_conditioning.items():
                            if isinstance(v, torch.Tensor):
                                dc_meta[k] = {"shape": list(v.shape), "dtype": str(v.dtype), "device": str(v.device)}
                        import pickle
                        meta_bytes = pickle.dumps(dc_meta)
                        meta_size = torch.tensor([len(meta_bytes)], dtype=torch.long, device="cuda")
                    else:
                        meta_size = torch.tensor([0], dtype=torch.long, device="cuda")
                        diffusion_conditioning = {}

                    _tdist.broadcast(meta_size, src=0)

                    if dap_rank == 0:
                        meta_tensor = torch.frombuffer(bytearray(meta_bytes), dtype=torch.uint8).cuda()
                    else:
                        meta_tensor = torch.empty(meta_size.item(), dtype=torch.uint8, device="cuda")
                    _tdist.broadcast(meta_tensor, src=0)

                    if dap_rank != 0:
                        import pickle
                        dc_meta = pickle.loads(meta_tensor.cpu().numpy().tobytes())
                    del meta_tensor

                    # Broadcast each conditioning tensor
                    _dtype_map = {
                        "torch.float32": torch.float32, "torch.float16": torch.float16,
                        "torch.bfloat16": torch.bfloat16, "torch.int64": torch.int64,
                    }
                    for k, meta in dc_meta.items():
                        shape = meta["shape"]
                        dtype = _dtype_map.get(meta["dtype"], torch.float32)
                        is_cpu = "cpu" in meta["device"]

                        if dap_rank != 0:
                            diffusion_conditioning[k] = torch.empty(shape, dtype=dtype, device="cuda")

                        # If on CPU (e.g. token_trans_bias), move to GPU for broadcast
                        if dap_rank == 0 and is_cpu:
                            diffusion_conditioning[k] = diffusion_conditioning[k].cuda()

                        _tdist.broadcast(diffusion_conditioning[k], src=0)

                        # Move back to CPU if it was CPU-offloaded (saves GPU memory)
                        if is_cpu:
                            diffusion_conditioning[k] = diffusion_conditioning[k].cpu()

                    _mem_log("  dist_diff: conditioning broadcast complete")

                    # ── Phase 2: Split samples across ranks ──
                    # With FK steering, multiplicity is expanded by num_particles.
                    # Split at the sample level (before FK expansion) to keep
                    # FK particle groups intact on each rank.
                    base_per_rank = diffusion_samples // dap_size
                    remainder = diffusion_samples % dap_size
                    local_samples = base_per_rank + (1 if dap_rank < remainder else 0)

                    _mem_log(f"  dist_diff: rank {dap_rank} running {local_samples}/{diffusion_samples} samples")

                    # ── Phase 3: Each rank runs structure_module.sample() ──
                    model.structure_module.cuda()
                    _mem_log("  dist_diff: struct module reloaded to GPU")

                    if local_samples > 0:
                        with torch.autocast("cuda", enabled=False):
                            local_structure_output = model.structure_module.sample(
                                s_trunk=s.float(),
                                s_inputs=s_inputs.float(),
                                feats=feats,
                                num_sampling_steps=num_sampling_steps,
                                atom_mask=feats["atom_pad_mask"].float(),
                                fixed_atom_coords=feats["fixed_atom_coords"].float(),
                                fixed_atom_mask=feats["fixed_atom_mask"],
                                multiplicity=local_samples,
                                max_parallel_samples=max_parallel_samples,
                                steering_args=getattr(model, 'steering_args', None),
                                diffusion_conditioning=diffusion_conditioning,
                            )
                        local_coords = local_structure_output["sample_atom_coords"]
                    else:
                        # This rank has no samples (edge case: more GPUs than samples)
                        n_atoms = feats["atom_pad_mask"].shape[1]
                        local_coords = torch.empty(0, n_atoms, 3, dtype=torch.float32, device="cuda")

                    _mem_log("  dist_diff: local sampling complete")
                    model.structure_module.cpu()
                    # Free conditioning on non-primary ranks
                    if dap_rank != 0:
                        del diffusion_conditioning
                    torch.cuda.empty_cache()

                    # ── Phase 4: Gather sample_atom_coords to rank 0 ──
                    # Collect local_coords sizes from all ranks
                    local_count = torch.tensor([local_coords.shape[0]], dtype=torch.long, device="cuda")
                    all_counts = [torch.tensor([0], dtype=torch.long, device="cuda") for _ in range(dap_size)]
                    _tdist.all_gather(all_counts, local_count)
                    counts = [c.item() for c in all_counts]

                    if dap_rank == 0:
                        # Allocate buffer for all samples
                        total_samples = sum(counts)
                        n_atoms = local_coords.shape[1]
                        _coord_dtype = local_coords.dtype
                        all_coords = torch.empty(total_samples, n_atoms, 3, dtype=_coord_dtype, device="cuda")
                        offset = 0
                        all_coords[0:counts[0]] = local_coords
                        del local_coords  # free rank 0's local copy
                        offset += counts[0]
                        for src_rank in range(1, dap_size):
                            if counts[src_rank] > 0:
                                recv_buf = torch.empty(counts[src_rank], n_atoms, 3, dtype=_coord_dtype, device="cuda")
                                _tdist.recv(recv_buf, src=src_rank)
                                all_coords[offset:offset + counts[src_rank]] = recv_buf
                                del recv_buf
                            offset += counts[src_rank]
                    else:
                        if local_coords.shape[0] > 0:
                            _tdist.send(local_coords, dst=0)
                        del local_coords

                    torch.cuda.empty_cache()

                    if dap_rank == 0:
                        structure_output = {"sample_atom_coords": all_coords, "diff_token_repr": None}
                        dict_out.update(structure_output)
                        del all_coords

                    _mem_log("  dist_diff: gather complete")

                else:
                    # Single GPU or single sample — original path
                    sample_kwargs = None
                    if dap_rank == 0:
                        # Reload structure_module to GPU (was offloaded before atom_encoder)
                        model.structure_module.cuda()
                        _mem_log("  struct module reloaded to GPU")

                        sample_kwargs = dict(
                            s_trunk=s.float(),
                            s_inputs=s_inputs.float(),
                            feats=feats,
                            num_sampling_steps=num_sampling_steps,
                            atom_mask=feats["atom_pad_mask"].float(),
                            fixed_atom_coords=feats["fixed_atom_coords"].float(),
                            fixed_atom_mask=feats["fixed_atom_mask"],
                            multiplicity=diffusion_samples,
                            max_parallel_samples=max_parallel_samples,
                            steering_args=getattr(model, 'steering_args', None),
                            diffusion_conditioning=diffusion_conditioning,
                        )
                    with torch.autocast("cuda", enabled=False):
                        if cached_diffusion_config is not None:
                            from dap_cached_token_attention import run_cached_diffusion_sampling

                            _log_trunk_diffusion_memory("before_diffusion_cache", {
                                "final_single": s, "single_inputs": s_inputs,
                                "confidence_pair_cpu": z_trunk_row_cpu,
                            })
                            structure_output = run_cached_diffusion_sampling(
                                model.structure_module, model.diffusion_conditioning.token_trans_proj_z,
                                sample_kwargs, device=torch.device("cuda", torch.cuda.current_device()),
                                binding=f"fresh-prediction-{model._dap_cache_prediction_index}",
                                projection_rows=projection_rows, **cached_diffusion_config,
                            )
                        elif dap_rank == 0:
                            structure_output = model.structure_module.sample(**sample_kwargs)
                    del sample_kwargs

                    if dap_rank == 0:
                        dict_out.update(structure_output)
                        _mem_log("after structure_module.sample")
                        model.structure_module.cpu()
                        del diffusion_conditioning
                        torch.cuda.empty_cache()

                if sharded_trunk_handoff:
                    local_device = torch.device(
                        "cuda", torch.cuda.current_device()
                    )
                    z_trunk_row_gpu = z_trunk_row_cpu.to(
                        device=local_device,
                        dtype=torch.float32,
                        non_blocking=False,
                    )
                    del z_trunk_row_cpu
                    z_cpu = gather_to_rank0_cpu(
                        z_trunk_row_gpu,
                        dim=1,
                        original_size=original_N,
                    )
                    del z_trunk_row_gpu
                    torch.cuda.empty_cache()
                    _mem_log("after delayed gather z to rank0 CPU")
                    if dap_rank == 0:
                        if z_cpu is None:
                            raise RuntimeError(
                                "delayed sharded trunk gather produced no rank-0 tensor"
                            )
                        z_cpu = z_cpu[:, :, :original_N, :].contiguous()

                if dap_rank == 0:
                    # When DAP>1: keep z on CPU so run_confidence_dap can scatter-from-CPU (avoids OOM).
                    # When single GPU: need z on GPU for model.confidence_module().
                    if dap_size > 1:
                        dict_out["z"] = z_cpu
                        _mem_log("after structure_module (offloaded, z kept on CPU for confidence DAP)")
                    else:
                        z = z_cpu.cuda()
                        dict_out["z"] = z
                        del z_cpu
                        _mem_log("after structure_module (offloaded, z restored)")

                    if model.predict_bfactor:
                        dict_out["bfactors_logits"] = model.bfactor_module(s)
                        model.bfactor_module.cpu()
                        torch.cuda.empty_cache()

                # Sync before confidence DAP (GPU 1 was waiting)
                if dap_size > 1:
                    # Release stale CUDA reserved memory from trunk on ALL ranks
                    # (ranks 1-3 peaked at ~70GB during trunk PF, still reserved)
                    torch.cuda.empty_cache()
                    import torch.distributed as tdist
                    try:
                        tdist.barrier(device_ids=[torch.cuda.current_device()])
                    except TypeError:
                        tdist.barrier()

                # Confidence module with DAP (ALL GPUs participate)
                if model.confidence_prediction:
                    if dap_size > 1:
                        # Grab conf-specific data before offloading dict_out
                        if dap_rank == 0:
                            conf_x_pred = dict_out.get("sample_atom_coords", feats["coords"])
                            conf_pdist = dict_out["pdistogram"]
                            if conf_pdist.ndim == 5:
                                conf_pdist = conf_pdist[:, :, :, 0]
                        else:
                            conf_x_pred = torch.empty(0)
                            conf_pdist = torch.empty(0)

                        # ── Offload ALL dict_out to CPU ──
                        # z/s/pdistogram/structure_outputs all go to CPU.
                        # The local vars z, s, s_inputs still hold GPU refs.
                        if dap_rank == 0:
                            for key in list(dict_out.keys()):
                                if isinstance(dict_out[key], torch.Tensor) and dict_out[key].is_cuda:
                                    dict_out[key] = dict_out[key].cpu()
                            torch.cuda.empty_cache()

                        _mem_log("before confidence (dict_out offloaded)")

                        # Reload confidence_module to GPU (was offloaded before atom_encoder)
                        if hasattr(model, 'confidence_module'):
                            model.confidence_module.cuda()
                        _mem_log("  confidence module reloaded to GPU")

                        # Pass z via mutable list — run_confidence_dap clears z_holder[0] after scatter.
                        # Fix (job 353074): Rank 1,2,3 never have z_cpu in scope → use [None] to avoid
                        # UnboundLocalError. Only Rank 0 has z_cpu (kept on CPU for scatter-from-CPU in DAP).
                        if dap_rank == 0:
                            z_holder = [z_cpu]
                        else:
                            z_holder = [None]
                        predict_args = getattr(model, "predict_args", {}) or {}
                        confidence_output = run_confidence_dap(
                            model,
                            s_inputs=s_inputs,
                            s=s,
                            z_holder=z_holder,
                            x_pred=conf_x_pred,
                            feats=feats,
                            pred_distogram_logits=conf_pdist,
                            multiplicity=diffusion_samples,
                            run_sequentially=run_confidence_sequentially,
                            use_kernels=model.use_kernels,
                            write_full_pae=bool(predict_args.get("write_full_pae", True)),
                            write_full_pde=bool(predict_args.get("write_full_pde", True)),
                        )
                        # Release remaining local GPU refs
                        del s, s_inputs, conf_x_pred, conf_pdist, z_holder

                        _mem_log("after confidence_module")
                    else:
                        model.confidence_module.cuda()
                        _mem_log("  confidence module reloaded to GPU")
                        confidence_output = model.confidence_module(
                            s_inputs=s_inputs.detach(),
                            s=s.detach(),
                            z=z.detach(),
                            x_pred=(
                                dict_out["sample_atom_coords"].detach()
                                if not model.skip_run_structure
                                else feats["coords"].repeat_interleave(diffusion_samples, 0)
                            ),
                            feats=feats,
                            pred_distogram_logits=dict_out["pdistogram"][:, :, :, 0]
                            .detach()
                            .cuda(),
                            multiplicity=diffusion_samples,
                            run_sequentially=run_confidence_sequentially,
                            use_kernels=model.use_kernels,
                        )
                    if dap_rank == 0:
                        dict_out.update(confidence_output)
                        # Move any CPU-offloaded tensors back to GPU for writer.
                        # Keep large confidence tensors on CPU to avoid OOM (e.g. hexamer 13 samples).
                        _confidence_cpu_keys = frozenset({
                            "z", "pdistogram",
                            "pae_logits", "pde_logits", "pde", "pae", "plddt",
                            "complex_pde", "complex_pae", "complex_plddt", "complex_iplddt", "complex_ipde",
                            "ptm", "iptm", "ligand_iptm", "protein_iptm",
                            "s_conf", "z_conf",
                        })
                        for key in list(dict_out.keys()):
                            if key in _confidence_cpu_keys:
                                continue
                            if isinstance(dict_out[key], torch.Tensor) and not dict_out[key].is_cuda:
                                dict_out[key] = dict_out[key].cuda(0)
                    model.confidence_module.cpu()
                    torch.cuda.empty_cache()

        _print_peak_summary()

        # Save memory timeline as JSON for graphing
        if dap_rank == 0 and _timeline:
            _out_dir = os.environ.get('BOLTZ_OUT_DIR', '')
            if _out_dir:
                _mem_path = os.path.join(_out_dir, 'mem_timeline.json')
                _records = [{"step": lbl, "alloc_mb": a, "peak_mb": p, "elapsed_s": round(t, 2)} for t, a, p, lbl in _timeline]
                with open(_mem_path, 'w') as _mf:
                    json.dump(_records, _mf, indent=2)
                print(f"    [MEM] Saved {len(_records)} memory timeline records to {_mem_path}")

        return dict_out

    return dap_forward


def _project_template_pair_chunked(tmpl_module, pair):
    chunk_rows = _env_positive_int("BOLTZ_TEMPLATE_PROJECTION_CHUNK") or 16
    projected = None
    for start in range(0, pair.shape[1], chunk_rows):
        stop = min(start + chunk_rows, pair.shape[1])
        part = tmpl_module.z_proj(tmpl_module.z_norm(pair[:, None, start:stop]))
        if projected is None:
            projected = torch.empty(
                (pair.shape[0], 1, pair.shape[1], pair.shape[2], part.shape[-1]),
                dtype=part.dtype, device=part.device,
            )
        projected[:, :, start:stop].copy_(part)
        del part
    if projected is None:
        return tmpl_module.z_proj(tmpl_module.z_norm(pair[:, None]))
    return projected


def _log_trunk_diffusion_memory(stage, tensors):
    import json

    device = torch.device("cuda", torch.cuda.current_device())
    free, total = torch.cuda.mem_get_info(device)
    report = {
        "stage": stage,
        "rank": torch.distributed.get_rank() if torch.distributed.is_initialized() else 0,
        "allocated_bytes": torch.cuda.memory_allocated(device),
        "reserved_bytes": torch.cuda.memory_reserved(device),
        "driver_free_bytes": free,
        "gpu_total_bytes": total,
        "tensors": {
            name: {"shape": list(tensor.shape), "dtype": str(tensor.dtype),
                   "device": str(tensor.device), "bytes": tensor.numel() * tensor.element_size()}
            for name, tensor in tensors.items() if isinstance(tensor, torch.Tensor)
        },
    }
    print("[TRUNK_DIFFUSION_MEMORY] " + json.dumps(report, sort_keys=True), flush=True)


def _run_template_dap(tmpl_module, z_scattered, feats, pair_mask, use_kernels, original_N, mem_log=None, recycle_idx=0):
    """Run template module with DAP-scattered z.

    Computes template features in SCATTERED form (N/dap rows × N cols)
    so no GPU ever holds a full N×N tensor. Diagnostic gathers are gated
    behind BOLTZ_TEMPLATE_DEBUG to avoid OOM on large inputs.

    z_scattered: [B, N/dap, N_padded, D] — row-scattered
    pair_mask: [B, N, N] — full (unscattered)
    Returns: z_scattered + template_output (still row-scattered)
    """
    from boltz.data import const
    from torch.nn.functional import one_hot

    dap_size = get_dap_size()
    dap_rank = get_dap_rank()
    _save_gran_ckpt = os.environ.get("BOLTZ_SAVE_GRAN_CKPT", "0") == "1"
    _tmpl_debug = os.environ.get("BOLTZ_TEMPLATE_DEBUG", "0") == "1" and _save_gran_ckpt

    # Granular checkpoint dict (R0 only, rank 0 only, debug only)
    _gran_ckpts = {} if _tmpl_debug else None

    # Load template features (all on full N — these are per-residue, small)
    res_type = feats["template_restype"]            # [B, T, N, C]
    frame_rot = feats["template_frame_rot"]         # [B, T, N, 3, 3]
    frame_t = feats["template_frame_t"]             # [B, T, N, 3]
    frame_mask = feats["template_mask_frame"]       # [B, T, N]
    cb_coords = feats["template_cb"]                # [B, T, N, 3]
    ca_coords = feats["template_ca"]                # [B, T, N, 3]
    cb_mask = feats["template_mask_cb"]             # [B, T, N]
    visibility_ids = feats["visibility_ids"]        # [B, T, N] — per-template!
    template_mask = feats["template_mask"].any(dim=2).float()  # [B, T]
    num_templates = template_mask.sum(dim=1).clamp(min=1)      # [B]

    B, T = res_type.shape[:2]
    N = original_N

    if mem_log:
        mem_log("  template: loaded per-residue features")

    # ── Scatter row-dimension inputs BEFORE feature computation ──
    # Each GPU computes only its row shard of the N×N features.
    # Column dimension stays full (N) — row dimension becomes N/dap.
    if dap_size > 1:
        def _scat_bt(x, last_dims):
            """Scatter on the N (residue) dimension for [B, T, N, ...] tensors."""
            shape = x.shape  # [B, T, N, ...]
            x_flat = x.reshape(B * T, N, *shape[3:])  # [B*T, N, ...]
            x_scat = scatter(x_flat, dim=1)  # [B*T, N/dap, ...]
            return x_scat.reshape(B, T, x_scat.shape[1], *shape[3:])

        cb_coords_scat = _scat_bt(cb_coords, 3)      # [B, T, N/dap, 3]
        ca_coords_scat = _scat_bt(ca_coords, 3)      # [B, T, N/dap, 3]
        frame_mask_scat = _scat_bt(frame_mask.unsqueeze(-1), 1).squeeze(-1)  # [B, T, N/dap]
        cb_mask_scat = _scat_bt(cb_mask.unsqueeze(-1), 1).squeeze(-1)        # [B, T, N/dap]
        res_type_scat = _scat_bt(res_type, res_type.shape[-1])               # [B, T, N/dap, C]
        vis_ids_scat = _scat_bt(visibility_ids.unsqueeze(-1), 1).squeeze(-1) # [B, T, N/dap]
        N_scat = cb_coords_scat.shape[2]
    else:
        cb_coords_scat = cb_coords
        ca_coords_scat = ca_coords
        frame_mask_scat = frame_mask
        cb_mask_scat = cb_mask
        res_type_scat = res_type
        vis_ids_scat = visibility_ids
        N_scat = N

    if mem_log:
        mem_log("  template: scattered row-dim coords")

    # ── Compute features in scattered form: [B,T,N/dap,N,...] ──
    # Row dim = scattered (N/dap), col dim = full (N). No full N×N anywhere.
    # Pairwise masks: [B, T, N/dap, N, 1]
    b_cb_mask = (cb_mask_scat[:, :, :, None] * cb_mask[:, :, None, :])[..., None]
    b_frame_mask = (frame_mask_scat[:, :, :, None] * frame_mask[:, :, None, :])[..., None]

    # Template pair mask: [B, T, N/dap, N]
    tmlp_pair_mask = (vis_ids_scat[:, :, :, None] == visibility_ids[:, :, None, :]).float()

    if mem_log:
        mem_log("  template: computed pairwise masks (scattered)")

    # Compute template pair features in scattered form
    with torch.autocast(device_type="cuda", enabled=False):
        # Distogram: cdist(scattered_rows, all_cols) → [B, T, N/dap, N]
        cb_dists = torch.cdist(cb_coords_scat, cb_coords)
        boundaries = torch.linspace(tmpl_module.min_dist, tmpl_module.max_dist,
                                     tmpl_module.num_bins - 1).to(cb_dists.device)
        distogram = (cb_dists[..., None] > boundaries).sum(dim=-1).long()
        distogram = one_hot(distogram, num_classes=tmpl_module.num_bins)  # [B,T,N/dap,N,bins]
        del cb_dists

        if mem_log:
            mem_log("  template: distogram computed (scattered)")

        frame_rot_t = frame_rot.unsqueeze(2).transpose(-1, -2)
        frame_t_exp = frame_t.unsqueeze(2).unsqueeze(-1)
        ca_exp = ca_coords_scat.unsqueeze(3).unsqueeze(-1)
        vector = torch.matmul(frame_rot_t, (ca_exp - frame_t_exp))
        norm = torch.norm(vector, dim=-1, keepdim=True)
        unit_vector = torch.where(norm > 0, vector / norm, torch.zeros_like(vector))
        unit_vector = unit_vector.squeeze(-1)  # [B,T,N/dap,N,3]
        del frame_rot_t, frame_t_exp, ca_exp, vector, norm

        if mem_log:
            mem_log("  template: unit_vector computed (scattered)")

        # Concatenate and project: a_tij [B, T, N/dap, N, template_dim]
        a_tij = torch.cat([distogram, b_cb_mask, unit_vector, b_frame_mask], dim=-1)
        a_tij = a_tij * tmlp_pair_mask.unsqueeze(-1)
        del distogram, b_cb_mask, unit_vector, b_frame_mask

        res_type_i = res_type_scat[:, :, :, None].expand(-1, -1, -1, N, -1)  # [B,T,N/dap,N,C]
        res_type_j = res_type[:, :, None, :].expand(-1, -1, N_scat, -1, -1)  # [B,T,N/dap,N,C]
        a_tij = torch.cat([a_tij, res_type_i, res_type_j], dim=-1)
        del res_type_i, res_type_j
        a_tij = tmpl_module.a_proj(a_tij)  # [B, T, N/dap, N, template_dim]

    # Free scattered coords (no longer needed)
    del cb_coords_scat, ca_coords_scat
    del frame_mask_scat, cb_mask_scat, res_type_scat, vis_ids_scat, tmlp_pair_mask

    _ri = recycle_idx  # alias for compact logging

    if mem_log:
        mem_log("  template: a_tij computed (scattered, no full N×N)")

    # Save upstream template checkpoints (debug only — requires gather)
    if _tmpl_debug and recycle_idx == 0:
        # Gather a_tij for comparison (collective)
        _a_full = gather(a_tij.reshape(B * T, *a_tij.shape[2:]).contiguous(), dim=1)
        if dap_rank == 0:
            _af = _a_full[:, :N, :N, :].float()
            print(f"      [R{_ri}/TMPL] a_tij: mean={_af.mean():.6f} std={_af.std():.4f} absmax={_af.abs().max():.4f} (gathered)")
            _gran_ckpts["tmpl/a_tij"] = _a_full[:, :N, :N, :].cpu().to(torch.bfloat16)
        del _a_full

    # a_tij is already [B, T, N/dap, N, D] — no scatter needed!

    # z_scattered is [B, N/dap, N_padded, D]. Trim to original_N for template ops
    # and project: z_proj(z_norm(z_scattered[:,None])) → [B, 1, N/dap, N, template_dim]
    z_for_tmpl = z_scattered[:, :, :original_N, :]  # [B, N/dap, N, D]
    z_proj_out = _project_template_pair_chunked(tmpl_module, z_for_tmpl)

    if mem_log:
        mem_log("  template: z_proj computed")

    # Save z_proj output (debug only — requires gather)
    if _tmpl_debug and recycle_idx == 0:
        _zp_bt = z_proj_out.reshape(-1, *z_proj_out.shape[2:])  # [B*1, N/dap, N, D]
        _zp_full = gather(_zp_bt.contiguous(), dim=1)
        if dap_rank == 0:
            _zpf = _zp_full[:, :N, :N, :].float()
            print(f"      [R{_ri}/TMPL] z_proj_out: mean={_zpf.mean():.6f} std={_zpf.std():.4f} absmax={_zpf.abs().max():.4f} (gathered)")
            _gran_ckpts["tmpl/z_proj_out"] = _zp_full[:, :N, :N, :].cpu().to(torch.bfloat16)
        del _zp_full, _zp_bt

    v = z_proj_out + a_tij
    del a_tij, z_proj_out

    # Log v_input stats (debug only)
    if _tmpl_debug:
        _v_full = gather(v.reshape(B * T, *v.shape[2:]).contiguous(), dim=1)
        if dap_rank == 0:
            _vf = _v_full[:, :N, :N, :].float()
            print(f"      [R{_ri}/TMPL] v_input: mean={_vf.mean():.6f} std={_vf.std():.4f} absmax={_vf.abs().max():.4f} (gathered)")
            if recycle_idx == 0:
                _gran_ckpts["tmpl/v_input"] = _v_full[:, :N, :N, :].cpu().to(torch.bfloat16)
        del _v_full

    if mem_log:
        mem_log("  template: v = z_proj + a_tij")

    # Prepare pair_mask for scattered template PF
    # pair_mask is [B, N, N]. We need it scattered: [B, N/dap, N]
    pair_mask_tmpl = pair_mask[:, :, :original_N]  # ensure original_N
    if dap_size > 1:
        pair_mask_tmpl = scatter(pair_mask_tmpl, dim=1)  # [B, N/dap, N]

    # Expand mask for T templates: [B*T, N/dap, N]
    pair_mask_tmpl = pair_mask_tmpl[:, None].expand(-1, T, -1, -1)
    pair_mask_tmpl = pair_mask_tmpl.reshape(B * T, *pair_mask_tmpl.shape[2:])

    # v: [B, T, N/dap, N, template_dim] → [B*T, N/dap, N, template_dim]
    v = v.view(B * T, *v.shape[2:])

    if mem_log:
        mem_log("  template: v scattered, entering PF")

    # Run DAP-wrapped pairformer (2 layers)
    # Set chunk size
    if not tmpl_module.pairformer.training:
        if original_N > const.chunk_size_threshold:
            chunk_size_transition_z = int(os.environ.get("BOLTZ_TRANSITION_Z_CHUNK", "64"))
            if chunk_size_transition_z <= 0:
                chunk_size_transition_z = None
            # For very long sequences, use even smaller chunks to prevent OOM
            # Q@K^T shape: [chunk, H, N, N] × 4 bytes
            chunk_size_tri_attn = _tri_attn_chunk_size(
                original_N,
                default_long=8,
                default_small=32,
            )
        else:
            chunk_size_transition_z = None
            chunk_size_tri_attn = 128
    else:
        chunk_size_transition_z = None
        chunk_size_tri_attn = None

    _template_reuses_row_storage = not (
        tmpl_module.pairformer.training and torch.is_grad_enabled()
    )
    if _template_reuses_row_storage:
        v_residual_cpu = v.detach().to(device="cpu")
    else:
        v_residual_cpu = None
    if _template_reuses_row_storage:
        pf_input = v.detach()
        del v
    else:
        pf_input = v
    from dap_pairformer_noseq import get_dropout_mask as _pfnoseq_dropout

    def _save_subop_gather(label, z_scat, li):
        """Gather scattered z for sub-op checkpoint (debug only, collective)."""
        if not _tmpl_debug:
            return
        _full = gather(z_scat.contiguous(), dim=1)
        if dap_rank == 0 and recycle_idx == 0:
            _trimmed = _full[:, :N, :N, :].cpu().to(torch.bfloat16)
            _gran_ckpts[f"tmpl/pf{li}/{label}"] = _trimmed
            _fl = _full[:, :N, :N, :].float()
            print(f"        [SUBOP pf{li}] {label}: mean={_fl.mean():.6f} std={_fl.std():.4f} absmax={_fl.abs().max():.4f}")
        del _full

    for _li, layer in enumerate(tmpl_module.pairformer.layers):
        # IMPORTANT: Force use_kernels=False so both 1-GPU (original layers)
        # and 2-GPU (DAP-wrapped layers) use the same PyTorch-native code path.
        _tmpl_use_kernels = False
        _save_subop_gather("input", pf_input, _li)

        # 1. tri_mul_out
        dropout = _pfnoseq_dropout(
            layer.dropout,
            pf_input,
            layer.training,
            stock_pair_size=original_N,
            legacy_stock_behavior=True,
        )
        if _template_reuses_row_storage:
            pf_input = layer.tri_mul_out.forward_with_residual(
                pf_input,
                pair_mask_tmpl,
                dropout,
                use_kernels=_tmpl_use_kernels,
            )
        else:
            pf_input = pf_input + dropout * layer.tri_mul_out(
                pf_input, mask=pair_mask_tmpl, use_kernels=_tmpl_use_kernels
            )
        if mem_log:
            mem_log(f"  template: PF[{_li}] after tri_mul_out")
        _save_subop_gather("after_tri_mul_out", pf_input, _li)

        # 2. tri_mul_in — needs row_to_col transpose for DAP
        if dap_size > 1:
            z_col = row_to_col(pf_input)
            pair_mask_col = row_to_col(pair_mask_tmpl.unsqueeze(-1)).squeeze(-1)
            # Zero out padded positions
            N_pad = z_col.shape[1]
            if N_pad > original_N:
                z_col[:, original_N:, :, :] = 0
                pair_mask_col[:, original_N:, :] = 0
            dropout = _pfnoseq_dropout(
                layer.dropout,
                z_col,
                layer.training,
                stock_pair_size=original_N,
                legacy_stock_behavior=True,
            )
            if _template_reuses_row_storage:
                z_col = layer.tri_mul_in.forward_with_residual(
                    z_col,
                    pair_mask_col,
                    dropout,
                    use_kernels=_tmpl_use_kernels,
                )
                col_to_row_inplace(z_col, pf_input)
            else:
                z_col = z_col + dropout * layer.tri_mul_in(
                    z_col, mask=pair_mask_col, use_kernels=_tmpl_use_kernels
                )
                pf_input = col_to_row(z_col)
            del z_col, pair_mask_col, dropout
            if pf_input.shape[2] > original_N:
                pf_input = pf_input[:, :, :original_N, :]
        else:
            dropout = _pfnoseq_dropout(
                layer.dropout,
                pf_input,
                layer.training,
                stock_pair_size=original_N,
                legacy_stock_behavior=True,
            )
            pf_input = pf_input + dropout * layer.tri_mul_in(
                pf_input, mask=pair_mask_tmpl, use_kernels=_tmpl_use_kernels
            )
        if mem_log:
            mem_log(f"  template: PF[{_li}] after tri_mul_in")
        _save_subop_gather("after_tri_mul_in", pf_input, _li)

        # 3. tri_att_start (already DAP-wrapped via DAPPairformerNoSeqLayer injection)
        dropout = _pfnoseq_dropout(
            layer.dropout,
            pf_input,
            layer.training,
            stock_pair_size=original_N,
            legacy_stock_behavior=True,
        )
        if dap_size > 1:
            pf_input = layer.tri_att_start.forward_with_residual(
                pf_input,
                pair_mask_tmpl,
                dropout,
                chunk_size=chunk_size_tri_attn,
                use_kernels=_tmpl_use_kernels,
            )
        else:
            pf_input = pf_input + dropout * layer.tri_att_start(
                pf_input, mask=pair_mask_tmpl, chunk_size=chunk_size_tri_attn,
                use_kernels=_tmpl_use_kernels,
            )
        if mem_log:
            mem_log(f"  template: PF[{_li}] after tri_att_start")
        _save_subop_gather("after_tri_att_start", pf_input, _li)

        # 4. tri_att_end (already DAP-wrapped via DAPPairformerNoSeqLayer injection)
        dropout = _pfnoseq_dropout(
            layer.dropout,
            pf_input,
            layer.training,
            columnwise=True,
            stock_pair_size=original_N,
            legacy_stock_behavior=True,
        )
        if dap_size > 1:
            pf_input = layer.tri_att_end.forward_with_residual(
                pf_input,
                pair_mask_tmpl,
                dropout,
                chunk_size=chunk_size_tri_attn,
                use_kernels=_tmpl_use_kernels,
            )
        else:
            pf_input = pf_input + dropout * layer.tri_att_end(
                pf_input, mask=pair_mask_tmpl, chunk_size=chunk_size_tri_attn,
                use_kernels=_tmpl_use_kernels,
            )
        if mem_log:
            mem_log(f"  template: PF[{_li}] after tri_att_end")
        _save_subop_gather("after_tri_att_end", pf_input, _li)

        # 5. transition_z
        if _template_reuses_row_storage:
            pf_input = layer.transition_z.forward_with_residual(pf_input, chunk_size_transition_z)
        else:
            pf_input = pf_input + layer.transition_z(
                pf_input, chunk_size_transition_z
            )
        if mem_log:
            mem_log(f"  template: PF[{_li}] after transition")
        _save_subop_gather("after_transition", pf_input, _li)

        # Log PF layer output (debug only — gather is collective)
        if _tmpl_debug:
            _pf_full = gather(pf_input.contiguous(), dim=1)
            if dap_rank == 0:
                _pff = _pf_full[:, :N, :N, :].float()
                print(f"      [R{_ri}/TMPL] v_after_pf{_li}: mean={_pff.mean():.6f} std={_pff.std():.4f} absmax={_pff.abs().max():.4f} (gathered)")
                if recycle_idx == 0:
                    _gran_ckpts[f"tmpl/v_after_pf{_li}"] = _pf_full[:, :N, :N, :].cpu().to(torch.bfloat16)
            del _pf_full
        if mem_log:
            mem_log(f"  template: PF layer[{_li}] done")

    # v = v + pf_output (residual)
    if v_residual_cpu is not None:
        _add_cpu_row_residual_(
            pf_input,
            v_residual_cpu,
            _env_positive_int("BOLTZ_TEMPLATE_RESIDUAL_CHUNK") or 16,
        )
        v = pf_input
    else:
        v = v + pf_input
    del pf_input, v_residual_cpu

    if mem_log:
        mem_log("  template: PF residual added")

    # Log v_residual (debug only)
    if _tmpl_debug:
        _vr_full = gather(v.contiguous(), dim=1)
        if dap_rank == 0:
            _vrf = _vr_full[:, :N, :N, :].float()
            print(f"      [R{_ri}/TMPL] v_residual: mean={_vrf.mean():.6f} std={_vrf.std():.4f} absmax={_vrf.abs().max():.4f} (gathered)")
            if recycle_idx == 0:
                _gran_ckpts["tmpl/v_residual"] = _vr_full[:, :N, :N, :].cpu().to(torch.bfloat16)
        del _vr_full

    # Post-PF: norm, reshape, aggregate over templates
    v = tmpl_module.v_norm(v)
    v = v.view(B, T, *v.shape[1:])  # [B, T, N/dap, N, template_dim]

    # Granular: v_norm (debug only)
    if _tmpl_debug:
        _vn_full = gather(v.reshape(B * T, *v.shape[2:]).contiguous(), dim=1)
        if dap_rank == 0 and recycle_idx == 0:
            _gran_ckpts["tmpl/v_norm"] = _vn_full[:, :N, :N, :].cpu().to(torch.bfloat16)
        del _vn_full

    # Aggregate templates
    tmask = template_mask[:, :, None, None, None]
    ntemplates = num_templates[:, None, None, None]
    u = (v * tmask).sum(dim=1) / ntemplates.to(v)  # [B, N/dap, N, template_dim]
    del v

    if mem_log:
        mem_log("  template: aggregated over templates")

    # Log u_agg (debug only)
    if _tmpl_debug:
        _u_full = gather(u.contiguous(), dim=1)
        if dap_rank == 0:
            _uf = _u_full[:, :N, :N, :].float()
            print(f"      [R{_ri}/TMPL] u_agg: mean={_uf.mean():.6f} std={_uf.std():.4f} absmax={_uf.abs().max():.4f} (gathered)")
            if recycle_idx == 0:
                _gran_ckpts["tmpl/u_agg"] = _u_full[:, :N, :N, :].cpu().to(torch.bfloat16)
        del _u_full

    # Project back to z dim
    u = tmpl_module.relu(u)
    u = tmpl_module.u_proj(u)  # [B, N/dap, N, token_z]

    if mem_log:
        mem_log("  template: u_proj computed")

    # Log u_proj (debug only)
    if _tmpl_debug:
        _u_full = gather(u.contiguous(), dim=1)
        if dap_rank == 0:
            _uf = _u_full[:, :N, :N, :].float()
            print(f"      [R{_ri}/TMPL] u_proj: mean={_uf.mean():.6f} std={_uf.std():.4f} absmax={_uf.abs().max():.4f} (gathered)")
            if recycle_idx == 0:
                _gran_ckpts["tmpl/u_proj"] = _u_full[:, :N, :N, :].cpu().to(torch.bfloat16)
        del _u_full

    # Pad dim 2 to match z_scattered's padded N if needed
    if u.shape[2] < z_scattered.shape[2]:
        pad_n = z_scattered.shape[2] - u.shape[2]
        u = torch.nn.functional.pad(u, (0, 0, 0, pad_n))

    # Add to z_scattered
    if _template_reuses_row_storage:
        torch.add(z_scattered, u, out=u)
        z_scattered = u
    else:
        z_scattered = z_scattered + u
    del u

    if mem_log:
        mem_log("  template: added to z_scattered")

    # Granular: z_final (debug only)
    if _tmpl_debug:
        _z_full = gather(z_scattered.contiguous(), dim=1)
        if dap_rank == 0 and recycle_idx == 0:
            _gran_ckpts["tmpl/z_final"] = _z_full[:, :N, :N, :].cpu().to(torch.bfloat16)
        del _z_full

    # Save granular checkpoints to disk (debug only)
    if _tmpl_debug and recycle_idx == 0 and dap_rank == 0:
        _out_dir = os.environ.get('BOLTZ_OUT_DIR', '')
        if _out_dir and _gran_ckpts:
            _gran_path = os.path.join(_out_dir, 'granular_ckpts.pt')
            torch.save(_gran_ckpts, _gran_path)
            _gran_size = os.path.getsize(_gran_path) / (1024**2)
            print(f"      [GRAN] Saved {len(_gran_ckpts)} granular checkpoints to {_gran_path} ({_gran_size:.0f} MB)")

    return z_scattered


def _run_msa_dap(msa_module, z_scattered, s_inputs, feats, full_pair_mask, use_kernels, mem_log=None, _msa_diag=False):
    """Run MSA module with DAP-scattered z.

    z_scattered: [B, N/dap, N, D]
    """
    torch.cuda.empty_cache()
    if mem_log:
        mem_log("before MSA feature preparation (after cache release)")

    # Set chunk sizes (same logic as original, with OOM-safe overrides)
    N = z_scattered.shape[2]  # full N
    if not msa_module.training:
        from boltz.data import const
        if N > const.chunk_size_threshold:
            chunk_heads_pwa = True
            chunk_size_transition_z = int(os.environ.get("BOLTZ_TRANSITION_Z_CHUNK", "64"))
            if chunk_size_transition_z <= 0:
                chunk_size_transition_z = None
            chunk_size_transition_msa = 32
            chunk_size_outer_product = 4
            # For very long sequences, reduce tri_att chunk to prevent
            # Q@K^T score matrix OOM: [chunk, H, N, N] × 4 bytes
            chunk_size_tri_attn = _tri_attn_chunk_size(
                N,
                default_long=16,
                default_small=128,
            )
        else:
            chunk_heads_pwa = False
            chunk_size_transition_z = None
            chunk_size_transition_msa = None
            chunk_size_outer_product = None
            chunk_size_tri_attn = 512
    else:
        chunk_heads_pwa = False
        chunk_size_transition_z = None
        chunk_size_transition_msa = None
        chunk_size_outer_product = None
        chunk_size_tri_attn = None

    # Prepare MSA features
    from boltz.data import const
    msa = feats["msa"]
    has_deletion = feats["has_deletion"].unsqueeze(-1)
    deletion_value = feats["deletion_value"].unsqueeze(-1)
    is_paired = feats["msa_paired"].unsqueeze(-1)
    msa_mask = feats["msa_mask"]
    token_mask = feats["token_pad_mask"].float()
    token_mask_2d = token_mask[:, :, None] * token_mask[:, None, :]

    if msa_module.subsample_msa:
        msa_indices = torch.randperm(msa.shape[1])[:msa_module.num_subsampled_msa]
        msa = msa[:, msa_indices]
        has_deletion = has_deletion[:, msa_indices]
        deletion_value = deletion_value[:, msa_indices]
        is_paired = is_paired[:, msa_indices]
        msa_mask = msa_mask[:, msa_indices]

    projection_sequence_chunk = (
        _env_positive_int("BOLTZ_MSA_PROJECTION_S_CHUNK") or 4
    )
    m_projected = _project_msa_features_chunked(
        msa_module.msa_proj,
        msa,
        has_deletion,
        deletion_value,
        is_paired,
        msa_module.use_paired_feature,
        const.num_tokens,
        projection_sequence_chunk,
    )
    del msa, has_deletion, deletion_value, is_paired
    if msa_module.training and torch.is_grad_enabled():
        m = m_projected + msa_module.s_proj(s_inputs).unsqueeze(1)
    else:
        m = m_projected
        m.add_(msa_module.s_proj(s_inputs).unsqueeze(1))
    del m_projected

    # Run MSA blocks with DAP layers
    for i in range(msa_module.msa_blocks):
        # Enable fine-grained diagnostics for layers 0,1 on first trunk cycle
        layer = msa_module.layers[i]
        layer._diag_enabled = _msa_diag and (i <= 1)

        # Enable granular checkpoints on block 0 when diagnostics are active
        _save_gran_ckpt = os.environ.get("BOLTZ_SAVE_GRAN_CKPT", "0") == "1"

        if _msa_diag and _save_gran_ckpt and i == 0:
            layer._save_gran_ckpts = True
            layer._gran_ckpt_data = {}

        z_scattered, m = layer(
            z_scattered, m, token_mask_2d, msa_mask,
            chunk_heads_pwa,
            chunk_size_transition_z,
            chunk_size_transition_msa,
            chunk_size_outer_product,
            chunk_size_tri_attn,
            use_kernels,
        )

        # Collect granular checkpoints — dap_msa.py already gathered & saved to CPU
        # NOTE: _gran_ckpt_data is only populated on rank 0, so we must reset
        # _save_gran_ckpts unconditionally to prevent rank 1 from doing extra
        # gathers in subsequent recycles.
        if _msa_diag and _save_gran_ckpt and i == 0:
            _dap_rank = get_dap_rank()
            if _dap_rank == 0 and hasattr(layer, '_gran_ckpt_data') and layer._gran_ckpt_data:
                _gran_ckpts = getattr(_run_msa_dap, '_gran_ckpts', {})
                for key, val in layer._gran_ckpt_data.items():
                    _gran_ckpts[f"msa/blk0/{key}"] = val  # already CPU bf16
                _run_msa_dap._gran_ckpts = _gran_ckpts
            layer._save_gran_ckpts = False
            layer._gran_ckpt_data = {}

        if mem_log:
            mem_log(f"  msa_module.layer[{i}]")

        if os.environ.get("BOLTZ_MSA_EMPTY_CACHE_BETWEEN_BLOCKS", "0") == "1":
            torch.cuda.empty_cache()
            if mem_log:
                mem_log(f"  msa_module.layer[{i}] after empty_cache")

    return z_scattered


def _run_pairformer_dap(pf_module, s, z_scattered, mask, full_pair_mask, use_kernels, mem_log=None):
    """Run pairformer module with DAP-scattered z.

    z_scattered: [B, N/dap, N, D]
    s: [B, N, 384] — replicated
    """
    dap_size = get_dap_size()
    dap_rank = get_dap_rank()
    pair_mask_scattered = scatter(full_pair_mask, dim=1) if dap_size > 1 else full_pair_mask

    # Set chunk sizes for large N (same logic as MSA module)
    N = z_scattered.shape[2]
    if not pf_module.training:
        from boltz.data import const
        if N > const.chunk_size_threshold:
            chunk_size_transition_z = int(os.environ.get("BOLTZ_TRANSITION_Z_CHUNK", "64"))
            if chunk_size_transition_z <= 0:
                chunk_size_transition_z = None
            # Reduce chunk size for very long sequences to prevent OOM
            # in Q@K^T attention score computation
            chunk_size_tri_attn = _tri_attn_chunk_size(
                N,
                default_long=16,
                default_small=128,
            )
        else:
            chunk_size_transition_z = None
            chunk_size_tri_attn = 512
    else:
        chunk_size_transition_z = None
        chunk_size_tri_attn = None

    # Per-layer checkpoint saving (controlled by env var)
    _layer_dir = os.environ.get("BOLTZ_SAVE_LAYER_CKPT", "")
    if _layer_dir and dap_rank == 0:
        import pathlib
        pathlib.Path(_layer_dir).mkdir(parents=True, exist_ok=True)

    num_layers = len(pf_module.layers)
    for i, layer in enumerate(pf_module.layers):
        s, z_scattered = layer(
            s, z_scattered, mask, pair_mask_scattered,
            chunk_size_tri_attn=chunk_size_tri_attn,
            chunk_size_transition_z=chunk_size_transition_z,
            use_kernels=use_kernels,
            layer_idx=i,
        )

        # Save z every 4th layer + last layer for divergence analysis
        # gather() is NCCL collective — ALL ranks must call it
        if _layer_dir and (i % 4 == 0 or i == num_layers - 1):
            z_full = gather(z_scattered.contiguous(), dim=1, original_size=N)
            if dap_rank == 0:
                torch.save(z_full.detach().cpu(), f"{_layer_dir}/layer_{i:03d}.pt")
            del z_full

        # Log every 8th layer to avoid spam (48 layers total)
        if mem_log and (i % 8 == 0 or i == num_layers - 1):
            mem_log(f"  pairformer.layer[{i}]")

    # Clear env var so only R0 (first recycling step) saves per-layer checkpoints
    if _layer_dir:
        os.environ.pop("BOLTZ_SAVE_LAYER_CKPT", None)

    # Save z at end of each recycling step (BOLTZ_SAVE_RECYCLE_CKPT)
    _recycle_dir = os.environ.get("BOLTZ_SAVE_RECYCLE_CKPT", "")
    if _recycle_dir:
        _rc = int(os.environ.get("_BOLTZ_RECYCLE_CTR", "0"))
        # gather is collective — all ranks must call
        z_full = gather(z_scattered.contiguous(), dim=1, original_size=N)
        if dap_rank == 0:
            import pathlib
            pathlib.Path(_recycle_dir).mkdir(parents=True, exist_ok=True)
            torch.save(z_full.detach().cpu(), f"{_recycle_dir}/recycle_{_rc:02d}.pt")
        del z_full
        os.environ["_BOLTZ_RECYCLE_CTR"] = str(_rc + 1)

    return s, z_scattered
