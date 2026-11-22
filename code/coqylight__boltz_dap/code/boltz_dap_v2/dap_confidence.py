"""
DAP-aware Confidence Module for Boltz 2.

Distributes ALL confidence computation across GPUs:
1. Scatter z early (before pre-PF ops)
2. Pre-pairformer ops computed per-chunk on each GPU
3. DAP pairformer (all GPUs)
4. Gather z → confidence heads (GPU 0)

Usage:
    Called from dap_trunk.py's dap_forward() instead of the original
    model.confidence_module() call.
"""

import torch
from torch import Tensor
from typing import Optional

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from boltz_distributed.comm import scatter, gather
from boltz_distributed.core import get_dap_size, get_dap_rank

from dap_features import representative_atom_indices
from dap_pairformer import DAPPairformerLayer

# Diagnostic: sequential inner-call index (set by outer loop, read after broadcast to debug shape corruption)
_DEBUG_CONF_CALL_IDX = [0]


def _add_confidence_relative_position_(
    z_chunk: Tensor,
    rel_pos: torch.nn.Module,
    feats: dict[str, Tensor],
    row_start: int,
    tile_rows: int = 16,
) -> None:
    if tile_rows < 1:
        raise ValueError("confidence relative-position tile_rows must be positive")
    if torch.is_grad_enabled():
        raise RuntimeError("tiled confidence relative-position encoding is inference-only")
    keys = ("asym_id", "residue_index", "entity_id", "sym_id", "token_index")
    num_tokens = feats["asym_id"].shape[1]
    local_rows = z_chunk.shape[1]
    if row_start < 0 or z_chunk.shape[2] != num_tokens:
        raise ValueError("invalid confidence relative-position shard geometry")
    padding = max(0, row_start + local_rows - num_tokens)
    row_feats = {
        key: torch.nn.functional.pad(feats[key], (0, padding)) if padding else feats[key]
        for key in keys
    }
    for start in range(0, local_rows, tile_rows):
        end = min(start + tile_rows, local_rows)
        rows = {key: value[:, row_start + start:row_start + end] for key, value in row_feats.items()}
        same_chain = rows["asym_id"][:, :, None] == feats["asym_id"][:, None, :]
        same_residue = rows["residue_index"][:, :, None] == feats["residue_index"][:, None, :]
        same_entity = rows["entity_id"][:, :, None] == feats["entity_id"][:, None, :]
        residue_delta = rows["residue_index"][:, :, None] - feats["residue_index"][:, None, :]
        if getattr(rel_pos, "cyclic_pos_enc", False) and "cyclic_period" in feats:
            periods = feats["cyclic_period"]
            periods = torch.where(periods > 0, periods, torch.zeros_like(periods) + 10000)
            residue_delta = (residue_delta - periods[:, None, :] * torch.round(residue_delta / periods[:, None, :])).long()
        residue_delta = torch.clip(residue_delta + rel_pos.r_max, 0, 2 * rel_pos.r_max)
        residue_delta = torch.where(same_chain, residue_delta, torch.zeros_like(residue_delta) + 2 * rel_pos.r_max + 1).long()
        relative_position = torch.nn.functional.one_hot(residue_delta, 2 * rel_pos.r_max + 2)
        token_delta = torch.clip(
            rows["token_index"][:, :, None] - feats["token_index"][:, None, :] + rel_pos.r_max,
            0, 2 * rel_pos.r_max,
        )
        token_delta = torch.where(same_chain & same_residue, token_delta, torch.zeros_like(token_delta) + 2 * rel_pos.r_max + 1).long()
        relative_token = torch.nn.functional.one_hot(token_delta, 2 * rel_pos.r_max + 2)
        chain_delta = torch.clip(
            rows["sym_id"][:, :, None] - feats["sym_id"][:, None, :] + rel_pos.s_max,
            0, 2 * rel_pos.s_max,
        )
        chain_delta = torch.where(
            (~same_entity) if getattr(rel_pos, "fix_sym_check", False) else same_chain,
            torch.zeros_like(chain_delta) + 2 * rel_pos.s_max + 1,
            chain_delta,
        ).long()
        relative_chain = torch.nn.functional.one_hot(chain_delta, 2 * rel_pos.s_max + 2)
        encoded = rel_pos.linear_layer(torch.cat([
            relative_position.float(), relative_token.float(),
            same_entity.unsqueeze(-1).float(), relative_chain.float(),
        ], dim=-1))
        z_chunk[:, start:end].add_(encoded)
        del encoded, relative_position, relative_token, relative_chain
        del residue_delta, token_delta, chain_delta, same_chain, same_residue, same_entity


def _add_confidence_pair_inputs_(
    z_chunk: Tensor,
    conf: torch.nn.Module,
    feats: dict[str, Tensor],
    row_start: int,
    tile_rows: int = 16,
) -> None:
    _add_confidence_relative_position_(z_chunk, conf.rel_pos, feats, row_start, tile_rows)
    for start in range(0, z_chunk.shape[1], tile_rows):
        end = min(start + tile_rows, z_chunk.shape[1])
        pair = z_chunk[:, start:end]
        bonds = feats["token_bonds"][:, start:end]
        pair.add_(conf.token_bonds(bonds.unsqueeze(-1) if bonds.dim() == 3 else bonds))
        if conf.bond_type_feature:
            pair.add_(conf.token_bonds_type(feats["type_bonds"][:, start:end].long()))
        if "contact_conditioning" in feats:
            pair.add_(conf.contact_conditioning({
                key: feats[key][:, start:end]
                for key in ("contact_conditioning", "contact_threshold")
            }))


def _confidence_pre_pairformer(
    conf: torch.nn.Module,
    s_inputs: Tensor,
    s: Tensor,
    z_chunk: Tensor,
    feats_chunk: dict[str, Tensor],
    row_start: int,
    mask: Tensor,
    x_pred_repr: Tensor,
    multiplicity: int = 1,
    tile_rows: int = 16,
) -> tuple[Tensor, Tensor, Tensor, Tensor, Tensor]:
    if torch.is_grad_enabled():
        raise RuntimeError("tiled confidence inputs are inference-only")
    if tile_rows < 1 or multiplicity < 1:
        raise ValueError("confidence tile_rows and multiplicity must be positive")
    num_tokens = s_inputs.shape[1]
    local_rows = z_chunk.shape[1]
    row_end = row_start + local_rows
    if row_start < 0 or z_chunk.shape[2] != num_tokens:
        raise ValueError("invalid confidence input shard geometry")
    padding = max(0, row_end - num_tokens)
    s_inputs_n = conf.s_inputs_norm(s_inputs)
    if not conf.no_update_s:
        s = conf.s_norm(s)
    if conf.add_s_input_to_s:
        s = s + conf.s_input_to_s(s_inputs_n)
    for start in range(0, local_rows, tile_rows):
        pair = z_chunk[:, start:start + tile_rows]
        pair.copy_(conf.z_norm(pair))
    if conf.add_z_input_to_z:
        _add_confidence_pair_inputs_(z_chunk, conf, feats_chunk, row_start, tile_rows)

    s_rows = conf.s_to_z(s_inputs_n)
    s_columns = conf.s_to_z_transpose(s_inputs_n)
    if padding:
        s_rows = torch.nn.functional.pad(s_rows, (0, 0, 0, padding))
    for start in range(0, local_rows, tile_rows):
        end = min(start + tile_rows, local_rows)
        pair = z_chunk[:, start:end]
        pair.add_(s_rows[:, row_start + start:row_start + end, None, :])
        pair.add_(s_columns[:, None, :, :])
    del s_rows, s_columns
    if conf.add_s_to_z_prod:
        product_rows = conf.s_to_z_prod_in1(s_inputs_n)
        product_columns = conf.s_to_z_prod_in2(s_inputs_n)
        if padding:
            product_rows = torch.nn.functional.pad(product_rows, (0, 0, 0, padding))
        for start in range(0, local_rows, tile_rows):
            end = min(start + tile_rows, local_rows)
            z_chunk[:, start:end].add_(conf.s_to_z_prod_out(
                product_rows[:, row_start + start:row_start + end, None, :]
                * product_columns[:, None, :, :]
            ))
        del product_rows, product_columns

    s = s.repeat_interleave(multiplicity, 0)
    if multiplicity != 1:
        z_chunk = z_chunk.repeat_interleave(multiplicity, 0)
    x_rows = torch.nn.functional.pad(x_pred_repr, (0, 0, 0, padding)) if padding else x_pred_repr
    d_chunk = torch.cdist(
        x_rows.repeat_interleave(multiplicity, 0)[:, row_start:row_end],
        x_pred_repr.repeat_interleave(multiplicity, 0),
    )
    for start in range(0, local_rows, tile_rows):
        end = min(start + tile_rows, local_rows)
        bins = (d_chunk[:, start:end].unsqueeze(-1) > conf.boundaries).sum(dim=-1).long()
        z_chunk[:, start:end].add_(conf.dist_bin_pairwise_embed(bins))
    mask = mask.repeat_interleave(multiplicity, 0)
    row_mask = torch.nn.functional.pad(mask, (0, padding)) if padding else mask
    pair_mask_chunk = row_mask[:, row_start:row_end].unsqueeze(-1) * mask.unsqueeze(1)
    valid_rows = max(0, min(local_rows, num_tokens - row_start))
    if valid_rows < local_rows:
        z_chunk[:, valid_rows:].zero_()
    return s, z_chunk, mask, pair_mask_chunk, d_chunk


def _gather_confidence_symmetric_tile(
    z_chunk: Tensor,
    row_start: int,
    row_end: int,
    num_tokens: int,
    dap_rank: int,
    dap_size: int,
) -> Optional[Tensor]:
    if torch.is_grad_enabled():
        raise RuntimeError("streamed confidence pair gathering is inference-only")
    batch, local_rows, columns, pair_dim = z_chunk.shape
    if not 0 <= row_start < row_end <= num_tokens or columns != num_tokens:
        raise ValueError("invalid confidence PDE tile geometry")
    owner = row_start // local_rows
    if owner != (row_end - 1) // local_rows or owner >= dap_size:
        raise ValueError("confidence PDE tile must stay within one row shard")
    tile_rows = row_end - row_start
    result = z_chunk.new_empty(batch, tile_rows, num_tokens, pair_dim) if dap_rank == 0 else None
    torch.distributed.barrier()
    if dap_rank == owner:
        source = z_chunk[:, row_start - owner * local_rows:row_end - owner * local_rows]
        if owner == 0:
            result.copy_(source)
        else:
            torch.distributed.send(source.contiguous(), dst=0)
    elif dap_rank == 0:
        torch.distributed.recv(result, src=owner)
    torch.distributed.barrier()
    for source_rank in range(dap_size):
        column_start = source_rank * local_rows
        valid_rows = max(0, min(local_rows, num_tokens - column_start))
        if not valid_rows:
            continue
        if dap_rank == 0:
            if source_rank == 0:
                transposed = z_chunk[:, :valid_rows, row_start:row_end].transpose(1, 2)
                result[:, :, column_start:column_start + valid_rows].add_(transposed)
                del transposed
            else:
                received = z_chunk.new_empty(batch, valid_rows, tile_rows, pair_dim)
                torch.distributed.recv(received, src=source_rank)
                result[:, :, column_start:column_start + valid_rows].add_(received.transpose(1, 2))
                del received
        elif dap_rank == source_rank:
            torch.distributed.send(z_chunk[:, :valid_rows, row_start:row_end].contiguous(), dst=0)
    return result


def _confidence_pde(
    heads: torch.nn.Module,
    z_chunk: Tensor,
    pred_distogram_logits: Tensor,
    token_pad_mask: Tensor,
    asym_id: Tensor,
    dap_rank: int,
    dap_size: int,
    multiplicity: int = 1,
    keep_logits: bool = False,
    tile_rows: int = 16,
    progress=None,
) -> tuple[Optional[Tensor], Optional[Tensor], Optional[Tensor], Optional[Tensor]]:
    from boltz.model.layers.confidence_utils import compute_aggregated_metric

    if torch.is_grad_enabled() or tile_rows < 1 or multiplicity < 1:
        raise ValueError("confidence PDE requires inference mode and positive tile size/multiplicity")
    batch, local_rows, tokens, _ = z_chunk.shape
    if local_rows != (tokens + dap_size - 1) // dap_size:
        raise ValueError("invalid confidence PDE row shard")
    device = z_chunk.device
    pde_cpu = logits_cpu = complex_pde = complex_ipde = None
    if dap_rank == 0:
        pad_mask = token_pad_mask.repeat_interleave(multiplicity, 0)
        chain_id = asym_id.repeat_interleave(multiplicity, 0)
        if pad_mask.shape != (batch, tokens) or chain_id.shape != (batch, tokens):
            raise ValueError("confidence PDE metadata does not match expanded batch")
        pair_mask = _stream_contact_probability(
            pred_distogram_logits, device,
            int(os.environ.get("BOLTZ_CONF_DISTOGRAM_ROW_CHUNK", "16")),
        )
        if multiplicity != 1:
            pair_mask = pair_mask.repeat_interleave(multiplicity, 0)
        elif pred_distogram_logits.ndim == 3 and pred_distogram_logits.device == device:
            pair_mask = pair_mask.clone()
        interface_mask = torch.empty_like(pair_mask)
        token_indices = torch.arange(tokens, device=device)
        for start in range(0, tokens, tile_rows):
            end = min(start + tile_rows, tokens)
            padding = pad_mask[:, start:end, None] * pad_mask[:, None, :]
            padding *= (token_indices[start:end, None] != token_indices[None, :])
            pair_mask[:, start:end].mul_(padding)
            different = chain_id[:, start:end, None] != chain_id[:, None, :]
            interface_mask[:, start:end].copy_(pair_mask[:, start:end] * different)
            del padding, different
        pde_cpu = torch.empty((batch, tokens, tokens), dtype=torch.float32,
                              device="cpu", pin_memory=z_chunk.is_cuda)
    for owner in range(dap_size):
        owner_end = min((owner + 1) * local_rows, tokens)
        if progress is not None:
            progress(f"PDE shard {owner + 1}/{dap_size} start")
        for start in range(owner * local_rows, owner_end, tile_rows):
            end = min(start + tile_rows, owner_end)
            symmetric = _gather_confidence_symmetric_tile(z_chunk, start, end, tokens, dap_rank, dap_size)
            if dap_rank == 0:
                if heads.use_separate_heads:
                    same = (chain_id[:, start:end, None] == chain_id[:, None, :]).unsqueeze(-1)
                    intra = heads.to_pde_intra_logits(symmetric) * same.float()
                    inter = heads.to_pde_inter_logits(symmetric) * (~same).float()
                    logits = inter + intra
                    del intra, inter, same
                else:
                    logits = heads.to_pde_logits(symmetric)
                del symmetric
                expected = compute_aggregated_metric(logits, end=32).float().transpose(1, 2)
                pde_cpu[:, :, start:end].copy_(expected.cpu())
                if keep_logits:
                    if logits_cpu is None:
                        logits_cpu = torch.empty((batch, tokens, tokens, logits.shape[-1]),
                                                 dtype=logits.dtype, device="cpu")
                    logits_cpu[:, start:end].copy_(logits.cpu())
                del logits, expected
        if progress is not None:
            progress(f"PDE shard {owner + 1}/{dap_size} done")
    if dap_rank == 0:
        metric = pde_cpu.to(device=device, non_blocking=False)
        complex_pde = (metric * pair_mask).sum(dim=(1, 2)) / pair_mask.sum(dim=(1, 2))
        complex_ipde = (metric * interface_mask).sum(dim=(1, 2)) / (interface_mask.sum(dim=(1, 2)) + 1e-5)
    torch.distributed.barrier()
    return pde_cpu, logits_cpu, complex_pde, complex_ipde


def _confidence_z_transport_dtype() -> torch.dtype:
    name = os.environ.get("BOLTZ_CONFIDENCE_Z_TRANSPORT_DTYPE", "bf16").lower()
    dtypes = {"fp32": torch.float32, "bf16": torch.bfloat16}
    if name not in dtypes:
        raise ValueError(
            "BOLTZ_CONFIDENCE_Z_TRANSPORT_DTYPE must be 'fp32' or 'bf16', "
            f"got {name!r}"
        )
    return dtypes[name]


def _scatter_confidence_z_rows(
    z: Optional[Tensor],
    *,
    batch_size: int,
    num_tokens: int,
    pair_dim: int,
    padded_tokens: int,
    chunk_tokens: int,
    dap_rank: int,
    dap_size: int,
    local_device: torch.device,
) -> Tensor:
    """Scatter pair rows using the explicitly selected transport dtype."""
    transport_dtype = _confidence_z_transport_dtype()

    if dap_rank == 0:
        if z is None:
            raise ValueError("rank 0 must provide the full confidence pair tensor")
        if z.shape != (batch_size, num_tokens, num_tokens, pair_dim):
            raise ValueError(
                "unexpected confidence pair shape: "
                f"{tuple(z.shape)} != "
                f"{(batch_size, num_tokens, num_tokens, pair_dim)}"
            )
        mixed_bf16_source = (
            z.dtype == torch.bfloat16
            and torch.is_autocast_enabled(local_device.type)
            and torch.get_autocast_dtype(local_device.type) == torch.bfloat16
        )
        if z.dtype != torch.float32 and not mixed_bf16_source:
            raise TypeError(f"confidence pair source must be FP32, got {z.dtype}")

        local_chunk = None
        for rank in range(dap_size):
            row_start = rank * chunk_tokens
            valid_rows = max(0, min(chunk_tokens, num_tokens - row_start))
            if valid_rows == chunk_tokens:
                source_chunk = z[:, row_start : row_start + chunk_tokens].contiguous()
            else:
                source_chunk = torch.zeros(
                    batch_size,
                    chunk_tokens,
                    num_tokens,
                    pair_dim,
                    dtype=z.dtype,
                    device=z.device,
                )
                if valid_rows:
                    source_chunk[:, :valid_rows].copy_(
                        z[:, row_start : row_start + valid_rows]
                    )
            transported = source_chunk.to(
                device=local_device,
                dtype=transport_dtype,
                non_blocking=False,
            )
            if rank == 0:
                local_chunk = transported
            else:
                torch.distributed.send(transported, dst=rank)
            del source_chunk, transported
        if local_chunk is None:
            raise AssertionError("rank 0 confidence pair chunk was not created")
    else:
        local_chunk = torch.empty(
            batch_size,
            chunk_tokens,
            num_tokens,
            pair_dim,
            dtype=transport_dtype,
            device=local_device,
        )
        torch.distributed.recv(local_chunk, src=0)

    if local_chunk.dtype == torch.float32:
        return local_chunk
    return local_chunk.float()


def _local_cuda_device() -> torch.device:
    """Return the process-local CUDA device selected by DAP initialization."""
    return torch.device("cuda", torch.cuda.current_device())


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


def _dict_tensors_to_cpu(obj):
    """Recursively move tensors in nested dict to CPU (for pair_chains_iptm)."""
    if isinstance(obj, torch.Tensor):
        return obj.cpu() if obj.is_cuda else obj
    if isinstance(obj, dict):
        return {k: _dict_tensors_to_cpu(v) for k, v in obj.items()}
    return obj


def _stage_confidence_feats(feats: dict, conf, dap_rank: int) -> dict[str, Tensor]:
    """Keep only confidence inputs, with one CPU copy on global rank 0."""
    required = {
        "asym_id",
        "atom_pad_mask",
        "atom_to_token",
        "atom_to_token_idx",
        "frames_idx",
        "mol_type",
        "token_pad_mask",
        "token_to_rep_atom",
        "token_to_rep_atom_idx",
    }
    if conf.add_z_input_to_z:
        required.update(
            {
                "contact_conditioning",
                "contact_threshold",
                "entity_id",
                "residue_index",
                "sym_id",
                "token_bonds",
                "token_index",
            }
        )
        if conf.bond_type_feature:
            required.add("type_bonds")
        if (
            hasattr(conf, "rel_pos")
            and hasattr(conf.rel_pos, "cyclic_pos_enc")
            and conf.rel_pos.cyclic_pos_enc
        ):
            required.add("cyclic_period")

    feats_cpu = {}
    for key, value in list(feats.items()):
        if not isinstance(value, torch.Tensor):
            continue
        if dap_rank == 0 and key in required:
            cpu_value = value.cpu() if value.is_cuda else value
            feats[key] = cpu_value
            feats_cpu[key] = cpu_value
        else:
            del feats[key]
    return feats_cpu


def _stream_contact_probability(
    pred_distogram_logits: Tensor,
    device: torch.device,
    row_chunk: int,
) -> Tensor:
    """Compute contact probability without materializing full logits on GPU."""
    if pred_distogram_logits.ndim == 3:
        batch_size, num_tokens, num_tokens_2 = pred_distogram_logits.shape
        if num_tokens != num_tokens_2:
            raise ValueError(
                "Expected contact probability with shape [B, N, N], got "
                f"{tuple(pred_distogram_logits.shape)}"
            )
        return pred_distogram_logits.to(device=device, non_blocking=False)
    batch_size, num_tokens, num_tokens_2, num_bins = pred_distogram_logits.shape
    if num_tokens != num_tokens_2 or num_bins != 64:
        raise ValueError(
            "Expected distogram logits with shape [B, N, N, 64], got "
            f"{tuple(pred_distogram_logits.shape)}"
        )
    row_chunk = max(1, row_chunk)
    prob_contact = torch.empty(
        batch_size,
        num_tokens,
        num_tokens,
        dtype=pred_distogram_logits.dtype,
        device=device,
    )
    contacts = torch.zeros(
        (1, 1, 1, num_bins),
        dtype=pred_distogram_logits.dtype,
        device=device,
    )
    contacts[:, :, :, :20] = 1.0
    for row_start in range(0, num_tokens, row_chunk):
        row_end = min(row_start + row_chunk, num_tokens)
        logits_rows = pred_distogram_logits[:, row_start:row_end].to(
            device=device, non_blocking=False
        )
        probability_rows = torch.nn.functional.softmax(logits_rows, dim=-1)
        prob_contact[:, row_start:row_end].copy_(
            (probability_rows * contacts).sum(-1)
        )
        del logits_rows, probability_rows
    return prob_contact


def inject_dap_into_confidence(confidence_module):
    """Replace confidence module's pairformer layers with DAP wrappers.

    confidence_module.pairformer_stack is a PairformerModule
    with .layers = ModuleList of PairformerLayer.
    """
    pf = confidence_module.pairformer_stack
    if hasattr(pf, '_orig_mod'):
        pf = pf._orig_mod

    num_layers = len(pf.layers)
    for i in range(num_layers):
        original_layer = pf.layers[i]
        wrapped_layer = DAPPairformerLayer(original_layer)
        wrapped_layer.train(original_layer.training)
        pf.layers[i] = wrapped_layer

    dap_rank = get_dap_rank()
    if dap_rank == 0:
        print(f"  ✓ Wrapped {num_layers} confidence pairformer layers with DAP")

    return confidence_module


def load_confidence_pre_pf_weights(model, device):
    """Load confidence pre-PF sub-module weights onto a GPU.

    These are small (~10 MB total): LayerNorms, small Linears, Embeddings.
    Called for GPU 1+ so they can compute pre-PF ops on their z chunk.
    """
    conf = model.confidence_module

    # Move pre-PF modules to device
    conf.s_inputs_norm.to(device)
    if not conf.no_update_s:
        conf.s_norm.to(device)
    conf.z_norm.to(device)
    conf.s_to_z.to(device)
    conf.s_to_z_transpose.to(device)

    if conf.add_s_input_to_s:
        conf.s_input_to_s.to(device)

    if conf.add_s_to_z_prod:
        conf.s_to_z_prod_in1.to(device)
        conf.s_to_z_prod_in2.to(device)
        conf.s_to_z_prod_out.to(device)

    if conf.add_z_input_to_z:
        conf.rel_pos.to(device)
        conf.token_bonds.to(device)
        if conf.bond_type_feature:
            conf.token_bonds_type.to(device)
        conf.contact_conditioning.to(device)

    conf.dist_bin_pairwise_embed.to(device)
    # Move boundaries buffer
    conf.boundaries = conf.boundaries.to(device)

    # PAE head weights needed for distributed PAE computation (Phase 3a)
    heads = conf.confidence_heads
    if heads.use_separate_heads:
        heads.to_pae_intra_logits.to(device)
        heads.to_pae_inter_logits.to(device)
    else:
        heads.to_pae_logits.to(device)


def run_confidence_dap(
    model,
    s_inputs: Tensor,
    s: Tensor,
    z_holder,
    x_pred: Tensor,
    feats: dict,
    pred_distogram_logits: Tensor,
    multiplicity: int = 1,
    run_sequentially: bool = True,
    use_kernels: bool = False,
    write_full_pae: bool = True,
    write_full_pde: bool = True,
):
    """Run the confidence module with DAP on ALL operations.

    All GPUs: scatter z early, compute pre-PF ops per-chunk, run DAP PF.
    GPU 0: gather z, run confidence heads.

    Parameters match model.confidence_module.forward().
    """
    dap_size = get_dap_size()
    dap_rank = get_dap_rank()
    conf = model.confidence_module
    local_device = _local_cuda_device()

    def _barrier() -> None:
        try:
            torch.distributed.barrier(device_ids=[local_device.index])
        except TypeError:
            torch.distributed.barrier()

    # Extract z from z_holder early (before multiplicity branch)
    # NOTE: on non-primary ranks, z may be None (only rank 0 holds full z).
    # The scatter phase inside each recursive call distributes z from rank 0.
    z = z_holder[0] if isinstance(z_holder, list) else z_holder

    # Handle sequential processing of multiple samples
    if run_sequentially and multiplicity > 1:
        # Only rank 0 has z; assert batch=1 only there
        if dap_rank == 0:
            assert z.shape[0] == 1, "Not supported with batch size > 1"
        if dap_rank == 0:
            # Rank 0: avoid holding 25 full outputs in memory (OOM on hexamer).
            # Run first sample, pre-allocate merged buffers, then fill in remaining samples.
            _DEBUG_CONF_CALL_IDX[0] = 0
            x_pred_0 = x_pred[0:1]
            out_0 = run_confidence_dap(
                model, s_inputs, s, z, x_pred_0, feats, pred_distogram_logits,
                multiplicity=1, run_sequentially=False, use_kernels=use_kernels,
                write_full_pae=write_full_pae, write_full_pde=write_full_pde,
            )
            # Keep merged on CPU so GPU only holds one confidence run at a time (avoids OOM on hexamer).
            merged = {}
            pair_chains_list = []
            for key in out_0:
                val0 = out_0[key]
                if val0 is None:
                    merged[key] = None
                elif key == "pair_chains_iptm":
                    pair_chains_list.append(_dict_tensors_to_cpu(val0))
                elif isinstance(val0, torch.Tensor):
                    # val0 has leading batch dim (1, ...); merged stacks over multiplicity without that dim.
                    merged[key] = torch.empty(
                        (multiplicity,) + val0.shape[1:],
                        dtype=val0.dtype,
                        device="cpu",
                    )
                    merged[key][0].copy_(val0[0].cpu())
                else:
                    merged[key] = [val0]
            del out_0
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            for sample_idx in range(1, multiplicity):
                _DEBUG_CONF_CALL_IDX[0] = sample_idx
                x_pred_i = x_pred[sample_idx : sample_idx + 1]
                out_i = run_confidence_dap(
                    model, s_inputs, s, z, x_pred_i, feats, pred_distogram_logits,
                    multiplicity=1, run_sequentially=False, use_kernels=use_kernels,
                    write_full_pae=write_full_pae, write_full_pde=write_full_pde,
                )
                for key in out_i:
                    vali = out_i[key]
                    if vali is None:
                        pass
                    elif key == "pair_chains_iptm":
                        pair_chains_list.append(_dict_tensors_to_cpu(vali))
                    elif isinstance(vali, torch.Tensor):
                        merged[key][sample_idx].copy_(vali[0].cpu())
                del out_i
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            # Build final out_dict: merged tensors as-is; pair_chains_iptm from list
            out_dict = {}
            for key in merged:
                if merged[key] is None:
                    out_dict[key] = None
                elif isinstance(merged[key], torch.Tensor):
                    out_dict[key] = merged[key]
                else:
                    out_dict[key] = merged[key][0]  # fallback single value
            if pair_chains_list:
                pair_chains_iptm = {}
                for chain_idx1 in pair_chains_list[0]:
                    chains_iptm = {}
                    for chain_idx2 in pair_chains_list[0][chain_idx1]:
                        chains_iptm[chain_idx2] = torch.cat(
                            [pair_chains_list[i][chain_idx1][chain_idx2] for i in range(multiplicity)],
                            dim=0,
                        )
                    pair_chains_iptm[chain_idx1] = chains_iptm
                out_dict["pair_chains_iptm"] = pair_chains_iptm
            return out_dict
        else:
            # Non-primary ranks: run all calls (no output collection)
            for sample_idx in range(multiplicity):
                _DEBUG_CONF_CALL_IDX[0] = sample_idx
                x_pred_i = x_pred  # empty on non-zero ranks
                run_confidence_dap(
                    model, s_inputs, s, z, x_pred_i, feats, pred_distogram_logits,
                    multiplicity=1, run_sequentially=False, use_kernels=use_kernels,
                    write_full_pae=write_full_pae, write_full_pde=write_full_pde,
                )
            return {}

    # ── Memory logging helper ──────────────────────────────────────────
    import time as _time
    _conf_t0 = _time.time()
    _conf_diag = os.environ.get("BOLTZ_CONFIDENCE_DIAG", "").strip().lower() in {
        "1", "true", "yes", "on",
    }
    def _cmem(label):
        if not _conf_diag:
            return
        torch.cuda.synchronize(local_device)
        alloc = torch.cuda.memory_allocated(local_device) // (1024 * 1024)
        peak = torch.cuda.max_memory_allocated(local_device) // (1024 * 1024)
        resv = torch.cuda.memory_reserved(local_device) // (1024 * 1024)
        free_cuda, total_cuda = torch.cuda.mem_get_info(local_device)
        free_mb = free_cuda // (1024 * 1024)
        elapsed = _time.time() - _conf_t0
        rss_mb, cgroup_used_mb, cgroup_limit_mb = _process_ram_mb()
        ram = f" | rss={rss_mb:6d}MB" if rss_mb is not None else ""
        if cgroup_used_mb is not None:
            if cgroup_limit_mb is None:
                ram += f" | cgroup={cgroup_used_mb:6d}MB/max"
            else:
                ram += f" | cgroup={cgroup_used_mb:6d}/{cgroup_limit_mb}MB"
        print(f"    [CONF R{dap_rank}]  {elapsed:6.1f}s | alloc={alloc:6d}MB | peak={peak:6d}MB | resv={resv:6d}MB | free={free_mb:6d}MB{ram} | {label}", flush=True)

    _cmem("conf entry")

    feats_cpu = _stage_confidence_feats(feats, conf, dap_rank)
    torch.cuda.empty_cache()
    _cmem(
        f"confidence feats staged (rank0_cpu_keys={len(feats_cpu)}, "
        f"remaining_keys={len(feats)})"
    )

    def _rank0_feat(name: str, dtype: Optional[torch.dtype] = None) -> Tensor:
        tensor = feats[name]
        if dtype is None:
            return tensor.to(device=local_device, non_blocking=True)
        return tensor.to(device=local_device, dtype=dtype, non_blocking=True)

    # ══════════════════════════════════════════════════════════════════
    # Phase 0: Scatter z + broadcast small data to all GPUs
    # ══════════════════════════════════════════════════════════════════

    # z was already extracted from z_holder above (before multiplicity branch)
    z_on_cpu = getattr(z, "device", None) and str(z.device).startswith("cpu")

    if dap_rank == 0:
        N = z.shape[1]
        B = z.shape[0]
        D_z = z.shape[3]
        D_s = s.shape[2]
        shape_tensor = torch.tensor(
            [B, N, D_z, D_s], dtype=torch.long, device=local_device
        )
    else:
        shape_tensor = torch.zeros(4, dtype=torch.long, device=local_device)

    torch.distributed.broadcast(shape_tensor, src=0)
    # On rank 1: compare GPU .tolist() vs .cpu().tolist() before using (to pinpoint .tolist() vs broadcast/sync cause)
    if _conf_diag and dap_rank == 1:
        _gpu_list = shape_tensor.tolist()
    raw_list = shape_tensor.cpu().tolist()
    if _conf_diag and dap_rank == 1:
        if _gpu_list != raw_list:
            print(
                f"    [CONF SHAPE diag] rank=1 call_idx={_DEBUG_CONF_CALL_IDX[0]} GPU_tolist={_gpu_list} CPU_tolist={raw_list} MISMATCH",
                flush=True,
            )
    # Use raw_list (from .cpu().tolist()) for reliable Python ints
    B, N, D_z, D_s = int(raw_list[0]), int(raw_list[1]), int(raw_list[2]), int(raw_list[3])
    # Guard against corrupted/overflowed dimensions (e.g. from bad broadcast on non-zero ranks)
    if not (0 < B <= 1000 and 0 < N <= 100000 and 0 < D_z <= 2048 and 0 < D_s <= 2048):
        raise ValueError(
            f"Invalid shape after broadcast: B={B} N={N} D_z={D_z} D_s={D_s} (dap_rank={dap_rank}). "
            "Check that z_holder is correct on rank 0 and that sequential calls pass z per sample."
        )
    # Diagnostic: compare Rank 0 vs Rank 1 shape after broadcast (to pinpoint .tolist() vs buffer/sync cause)
    if _conf_diag and dap_rank in (0, 1):
        _diag_call = _DEBUG_CONF_CALL_IDX[0]
        print(
            f"    [CONF SHAPE diag] rank={dap_rank} call_idx={_diag_call} raw_list={raw_list} -> B={B} N={N} D_z={D_z} D_s={D_s}",
            flush=True,
        )

    # Pad N to be divisible by dap_size
    N_padded = ((N + dap_size - 1) // dap_size) * dap_size
    chunk_N = N_padded // dap_size
    row_start = dap_rank * chunk_N
    row_end = row_start + chunk_N

    # Scatter z: each GPU gets [B, chunk_N, N, D_z]. Legacy BF16 remains the
    # default; candidate FP32 transport is enabled only by an explicit flag.
    z_chunk = _scatter_confidence_z_rows(
        z if dap_rank == 0 else None,
        batch_size=B,
        num_tokens=N,
        pair_dim=D_z,
        padded_tokens=N_padded,
        chunk_tokens=chunk_N,
        dap_rank=dap_rank,
        dap_size=dap_size,
        local_device=local_device,
    )
    if dap_rank == 0 and isinstance(z_holder, list):
        z_holder[0] = None
    if dap_rank == 0:
        _cmem("after z scatter (full z freed)")
    torch.cuda.empty_cache()

    # Broadcast small 1D data: s, s_inputs, mask
    if dap_rank != 0:
        s = torch.empty(B, N, D_s, dtype=torch.float32, device=local_device)
        s_inputs = torch.empty(B, N, D_s, dtype=torch.float32, device=local_device)
        mask = torch.empty(B, N, dtype=torch.float32, device=local_device)
    else:
        mask = _rank0_feat("token_pad_mask", torch.float32)
    torch.distributed.broadcast(s, src=0)
    torch.distributed.broadcast(s_inputs, src=0)
    torch.distributed.broadcast(mask, src=0)

    # Scatter N² feats entries needed for pre-PF ops
    # Helper: scatter rows of a [B,N,N,...] tensor
    def _scatter_rows(full_tensor_or_none, name, dtype=torch.float32):
        """Scatter rows of an N² tensor, staging rank-0 chunks to GPU only as needed."""
        if dap_rank == 0:
            full = full_tensor_or_none
            # Broadcast ndim and last dim so other ranks can allocate
            info = torch.tensor([full.dim(), full.shape[-1] if full.dim() == 4 else 0],
                                device=local_device, dtype=torch.long)
        else:
            info = torch.zeros(2, dtype=torch.long, device=local_device)
        torch.distributed.broadcast(info, src=0)
        ndim, last_d = info.tolist()

        if dap_rank == 0:
            if N_padded != N:
                if ndim == 4:
                    full = torch.nn.functional.pad(full, (0, 0, 0, 0, 0, N_padded - N))
                else:
                    full = torch.nn.functional.pad(full, (0, 0, 0, N_padded - N))
            for r in range(1, dap_size):
                rs = r * chunk_N
                re = rs + chunk_N
                chunk = full[:, rs:re].contiguous()
                chunk_send = chunk.to(device=local_device, dtype=dtype, non_blocking=True)
                torch.distributed.send(chunk_send, dst=r)
                del chunk, chunk_send
            chunk = full[:, row_start:row_end].contiguous().to(
                device=local_device, dtype=dtype, non_blocking=True
            )
            del full
            torch.cuda.empty_cache()
            return chunk
        else:
            if ndim == 4:
                chunk = torch.empty(B, chunk_N, N, int(last_d), dtype=dtype, device=local_device)
            else:
                chunk = torch.empty(B, chunk_N, N, dtype=dtype, device=local_device)
            torch.distributed.recv(chunk, src=0)
            return chunk

    feats_chunk = {}

    if conf.add_z_input_to_z:
        # rel_pos needs 1D feats (full, for both row & col indexing)
        for key in ["asym_id", "residue_index", "entity_id", "sym_id", "token_index"]:
            if dap_rank == 0:
                t = _rank0_feat(key, torch.float32)
            else:
                t = torch.empty(B, N, dtype=torch.float32, device=local_device)
            torch.distributed.broadcast(t, src=0)
            feats_chunk[key] = t

        if hasattr(conf, 'rel_pos') and hasattr(conf.rel_pos, 'cyclic_pos_enc') and conf.rel_pos.cyclic_pos_enc:
            if dap_rank == 0:
                t = _rank0_feat("cyclic_period", torch.float32)
            else:
                t = torch.empty(B, N, dtype=torch.float32, device=local_device)
            torch.distributed.broadcast(t, src=0)
            feats_chunk["cyclic_period"] = t

        compact_pair_features = feats.get("_compact_pair_features")
        if compact_pair_features is None:
            feats_chunk["token_bonds"] = _scatter_rows(
                feats["token_bonds"] if dap_rank == 0 else None, "token_bonds")
            if conf.bond_type_feature:
                feats_chunk["type_bonds"] = _scatter_rows(
                    feats["type_bonds"] if dap_rank == 0 else None, "type_bonds")
            feats_chunk["contact_conditioning"] = _scatter_rows(
                feats["contact_conditioning"] if dap_rank == 0 else None, "contact_conditioning")
            feats_chunk["contact_threshold"] = _scatter_rows(
                feats["contact_threshold"] if dap_rank == 0 else None, "contact_threshold")
        else:
            pair_tile = compact_pair_features.materialize_tile(
                row_start,
                min(row_end, N),
                device=local_device,
            )
            row_padding = chunk_N - pair_tile["token_bonds"].shape[1]
            if row_padding:
                pair_tile["token_bonds"] = torch.nn.functional.pad(
                    pair_tile["token_bonds"], (0, 0, 0, 0, 0, row_padding)
                )
                pair_tile["type_bonds"] = torch.nn.functional.pad(
                    pair_tile["type_bonds"], (0, 0, 0, row_padding)
                )
                pair_tile["contact_conditioning"] = torch.nn.functional.pad(
                    pair_tile["contact_conditioning"],
                    (0, 0, 0, 0, 0, row_padding),
                )
                pair_tile["contact_threshold"] = torch.nn.functional.pad(
                    pair_tile["contact_threshold"], (0, 0, 0, row_padding)
                )
            feats_chunk["token_bonds"] = pair_tile["token_bonds"]
            if conf.bond_type_feature:
                feats_chunk["type_bonds"] = pair_tile["type_bonds"]
            feats_chunk["contact_conditioning"] = pair_tile["contact_conditioning"]
            feats_chunk["contact_threshold"] = pair_tile["contact_threshold"]

    # Broadcast x_pred_repr for distance bins (small: [B, N, 3])
    if dap_rank == 0:
        rep_atom_idx, rep_atom_valid = representative_atom_indices(feats)
        rep_atom_idx = rep_atom_idx.to(
            device=local_device, dtype=torch.long, non_blocking=True
        )
        rep_atom_valid = rep_atom_valid.to(device=local_device, non_blocking=True)
        rep_atom_idx = rep_atom_idx.repeat_interleave(multiplicity, 0)
        rep_atom_valid = rep_atom_valid.repeat_interleave(multiplicity, 0)
        if len(x_pred.shape) == 4:
            Bx, mult, N_atoms, _ = x_pred.shape
            x_pred = x_pred.reshape(Bx * mult, N_atoms, -1)
        x_pred = x_pred.to(device=local_device, non_blocking=True)
        x_pred_repr = torch.gather(
            x_pred,
            1,
            rep_atom_idx.clamp(min=0).unsqueeze(-1).expand(-1, -1, x_pred.shape[-1]),
        )
        x_pred_repr = x_pred_repr * rep_atom_valid.unsqueeze(-1)
        del rep_atom_idx, rep_atom_valid
        # x_pred_repr is [B, N, 3] — small
    else:
        x_pred_repr = torch.empty(B, N, 3, dtype=torch.float32, device=local_device)
    torch.distributed.broadcast(x_pred_repr, src=0)

    if dap_rank == 0:
        torch.cuda.empty_cache()

    _cmem("after scatter + broadcast")

    # ══════════════════════════════════════════════════════════════════
    # Phase 1: Distributed pre-PF ops (all GPUs, on z_chunk)
    # ══════════════════════════════════════════════════════════════════

    s, z_chunk, mask, pair_mask_chunk, d_chunk = _confidence_pre_pairformer(
        conf, s_inputs, s, z_chunk, feats_chunk, row_start, mask, x_pred_repr, multiplicity,
    )
    del feats_chunk

    _cmem("pre-PF done, PF start")

    # Phase 1 broadcasts are done; rank 0 features stay on CPU until Phase 3 heads.
    # Release reserved-but-unused CUDA blocks on ALL ranks
    torch.cuda.empty_cache()
    _cmem("feats offloaded + cache cleared")

    # ══════════════════════════════════════════════════════════════════
    # Phase 2: DAP Pairformer (all GPUs) — unchanged
    # ══════════════════════════════════════════════════════════════════

    pf = conf.pairformer_stack
    if hasattr(pf, '_orig_mod'):
        pf = pf._orig_mod

    from boltz.data import const
    if not pf.training:
        configured_tri_attn_chunk = os.environ.get(
            "BOLTZ_CONFIDENCE_TRI_ATTN_CHUNK", ""
        ).strip()
        if configured_tri_attn_chunk:
            chunk_size_tri_attn = int(configured_tri_attn_chunk)
            if chunk_size_tri_attn <= 0:
                raise ValueError(
                    "BOLTZ_CONFIDENCE_TRI_ATTN_CHUNK must be positive"
                )
        elif N > 2000:
            chunk_size_tri_attn = 16  # 9MME: 128 → ~44GB transient, 16 → ~5.5GB
        else:
            chunk_size_tri_attn = 128
    else:
        chunk_size_tri_attn = None

    for li, layer in enumerate(pf.layers):
        s, z_chunk = layer(
            s, z_chunk, mask, pair_mask_chunk,
            chunk_size_tri_attn=chunk_size_tri_attn,
            use_kernels=use_kernels,
        )
        _cmem(f"  conf PF layer[{li}]")

    _cmem("PF done")

    # Phase 3 only needs a small subset of features; keep dense setup tensors on CPU.
    if dap_rank == 0:
        torch.cuda.empty_cache()
        _cmem("post-PF cache cleared, feats remain CPU-backed")

    phase3_feats: dict[str, Tensor] = {}

    def _phase3_source(name: str):
        if name in feats_cpu:
            return feats_cpu[name]
        return feats[name]

    def _phase3_feat(name: str, dtype: Optional[torch.dtype] = None) -> Tensor:
        tensor = phase3_feats.get(name)
        if tensor is None:
            source = _phase3_source(name)
            tensor = source.to(device=local_device, non_blocking=True)
            phase3_feats[name] = tensor
        if dtype is not None and tensor.dtype != dtype:
            return tensor.to(dtype=dtype)
        return tensor

    def _phase3_feat_dict(names: list[str]) -> dict:
        staged = {}
        for name in names:
            if name not in feats_cpu and name not in feats:
                continue
            value = _phase3_source(name)
            staged[name] = _phase3_feat(name) if isinstance(value, torch.Tensor) else value
        return staged

    # ══════════════════════════════════════════════════════════════════
    # Phase 3: Distributed confidence heads — stream PAE, chunk PDE
    # ══════════════════════════════════════════════════════════════════

    heads = conf.confidence_heads
    B_conf = z_chunk.shape[0]
    row_valid = max(0, min(chunk_N, N - row_start))

    def _broadcast_token_feat(name: str, dtype: torch.dtype) -> Tensor:
        if dap_rank == 0:
            tensor = _phase3_feat(name, dtype=dtype)
        else:
            tensor = torch.empty(B, N, dtype=dtype, device=local_device)
        torch.distributed.broadcast(tensor, src=0)
        return tensor

    from boltz.data import const
    from boltz.model.layers.confidence_utils import (
        compute_collinear_mask,
        tm_function,
    )

    asym_id_token = _broadcast_token_feat("asym_id", torch.long)
    token_pad_mask_base = _broadcast_token_feat("token_pad_mask", torch.float32)
    token_type_base = _broadcast_token_feat("mol_type", torch.long)
    asym_id_rep = asym_id_token.repeat_interleave(multiplicity, 0)
    token_pad_mask_m = token_pad_mask_base.repeat_interleave(multiplicity, 0).float()
    token_type = token_type_base.repeat_interleave(multiplicity, 0)
    is_ligand_token = (token_type == const.chain_type_ids["NONPOLYMER"]).float()
    is_protein_token = (token_type == const.chain_type_ids["PROTEIN"]).float()

    def _phase3_atom_token_index() -> Tensor:
        if "atom_to_token_idx" in feats_cpu or "atom_to_token_idx" in feats:
            return _phase3_feat("atom_to_token_idx", torch.long)
        source = _phase3_source("atom_to_token")
        return source.argmax(dim=-1).to(device=local_device, dtype=torch.long, non_blocking=True)

    def _compute_frame_mask_sparse() -> Tensor:
        frames_idx_true = _phase3_feat("frames_idx").long()
        atom_pad_mask_base = _phase3_feat("atom_pad_mask", torch.float32)
        atom_token_idx = _phase3_atom_token_index().clamp_(0, N - 1)
        asym_id_atom = torch.gather(asym_id_token, 1, atom_token_idx)

        B_atom, _, _ = x_pred.shape
        pred_atom_coords = x_pred.reshape(B_atom // multiplicity, multiplicity, -1, 3)
        frames_idx_pred = (
            frames_idx_true.clone()
            .repeat_interleave(multiplicity, 0)
            .reshape(B_atom // multiplicity, multiplicity, -1, 3)
        )

        for batch_idx, pred_atom_coord in enumerate(pred_atom_coords):
            token_idx = 0
            atom_idx = 0
            for chain_id in torch.unique(asym_id_token[batch_idx]):
                mask_chain_token = (asym_id_token[batch_idx] == chain_id) * token_pad_mask_base[batch_idx]
                mask_chain_atom = (asym_id_atom[batch_idx] == chain_id) * atom_pad_mask_base[batch_idx]
                num_tokens = int(mask_chain_token.sum().item())
                num_atoms = int(mask_chain_atom.sum().item())
                if (
                    token_type_base[batch_idx, token_idx] != const.chain_type_ids["NONPOLYMER"]
                    or num_atoms < 3
                ):
                    token_idx += num_tokens
                    atom_idx += num_atoms
                    continue
                chain_atom_mask = mask_chain_atom.bool()
                chain_coords = pred_atom_coord[:, chain_atom_mask]
                dist_mat = ((chain_coords[:, None, :, :] - chain_coords[:, :, None, :]) ** 2).sum(-1) ** 0.5
                resolved_pair = 1 - (
                    atom_pad_mask_base[batch_idx][chain_atom_mask][None, :]
                    * atom_pad_mask_base[batch_idx][chain_atom_mask][:, None]
                ).to(torch.float32)
                resolved_pair[resolved_pair == 1] = torch.inf
                indices = torch.sort(dist_mat + resolved_pair, axis=2).indices
                frames = torch.cat(
                    [indices[:, :, 1:2], indices[:, :, 0:1], indices[:, :, 2:3]], dim=2
                ) + atom_idx
                try:
                    frames_idx_pred[batch_idx, :, token_idx : token_idx + num_atoms, :] = frames
                except Exception as exc:
                    print(f"Failed to process {feats.get('pdb_id', '<unknown>')} due to {exc}")
                token_idx += num_tokens
                atom_idx += num_atoms

        device = frames_idx_pred.device
        frames_expanded = pred_atom_coords[
            torch.arange(0, B_atom // multiplicity, 1, device=device)[:, None, None, None],
            torch.arange(0, multiplicity, 1, device=device)[None, :, None, None],
            frames_idx_pred,
        ].reshape(-1, 3, 3)
        mask_collinear_pred = compute_collinear_mask(
            frames_expanded[:, 1] - frames_expanded[:, 0],
            frames_expanded[:, 1] - frames_expanded[:, 2],
        ).reshape(B_atom // multiplicity, multiplicity, -1)
        return (mask_collinear_pred * token_pad_mask_base[:, None, :]).reshape(-1, N).float()

    if dap_rank == 0:
        try:
            maski = _compute_frame_mask_sparse()
        except Exception as exc:
            print(f"Error in streamed PAE/PTM frame mask: {exc}")
            maski = torch.zeros(B_conf, N, dtype=torch.float32, device=local_device)
    else:
        maski = torch.empty(B_conf, N, dtype=torch.float32, device=local_device)
    torch.distributed.broadcast(maski, src=0)

    z_pae = z_chunk[:, :row_valid, :, :]
    if heads.use_separate_heads:
        row_asym = asym_id_rep[:, row_start : row_start + row_valid]
        same_chain_chunk = row_asym.unsqueeze(-1) == asym_id_rep.unsqueeze(1)
        pae_logits_chunk = heads.to_pae_intra_logits(z_pae)
        m_same = same_chain_chunk.to(dtype=pae_logits_chunk.dtype).unsqueeze(-1)
        pae_logits_chunk.mul_(m_same)
        pae_inter_chunk = heads.to_pae_inter_logits(z_pae)
        pae_logits_chunk.addcmul_(pae_inter_chunk, 1.0 - m_same)
        del pae_inter_chunk, m_same, same_chain_chunk, row_asym
    else:
        pae_logits_chunk = heads.to_pae_logits(z_pae)
    del z_pae

    num_pae_bins = pae_logits_chunk.shape[-1]
    pae_bin_width = 32.0 / num_pae_bins
    pae_bounds = torch.arange(
        start=0.5 * pae_bin_width,
        end=32.0,
        step=pae_bin_width,
        device=local_device,
        dtype=torch.float32,
    )
    pae_probs = torch.nn.functional.softmax(pae_logits_chunk, dim=-1)
    del pae_logits_chunk
    pae_chunk_value = torch.sum(
        pae_probs * pae_bounds.view(*((1,) * (pae_probs.ndim - 1)), num_pae_bins),
        dim=-1,
    ).float()

    pae_full_cpu: Optional[Tensor] = None
    if write_full_pae:
        _pae_stream_pin = bool(torch.cuda.is_available())
        if dap_rank == 0:
            pae_full_cpu = torch.empty((B_conf, N, N), dtype=torch.float32, device="cpu", pin_memory=_pae_stream_pin)
            if row_valid > 0:
                pae_full_cpu[:, row_start : row_start + row_valid].copy_(
                    pae_chunk_value.cpu(), non_blocking=_pae_stream_pin
                )
            for src_rank in range(1, dap_size):
                src_start = src_rank * chunk_N
                src_valid = max(0, min(chunk_N, N - src_start))
                if src_valid <= 0:
                    continue
                recv_buf = torch.empty(B_conf, src_valid, N, dtype=torch.float32, device=local_device)
                torch.distributed.recv(recv_buf, src=src_rank)
                pae_full_cpu[:, src_start : src_start + src_valid].copy_(
                    recv_buf.cpu(), non_blocking=_pae_stream_pin
                )
                del recv_buf
        elif row_valid > 0:
            torch.distributed.send(pae_chunk_value.contiguous(), dst=0)

    N_res = token_pad_mask_m.sum(dim=-1, keepdim=True)
    tm_values = tm_function(pae_bounds.unsqueeze(0), N_res).view(B_conf, 1, 1, num_pae_bins)
    tm_expected_chunk = torch.sum(pae_probs.float() * tm_values, dim=-1)
    del pae_probs, tm_values

    if row_valid < chunk_N:
        tm_expected_chunk = torch.nn.functional.pad(
            tm_expected_chunk,
            (0, 0, 0, chunk_N - row_valid),
        )
    tm_expected_value = gather(
        tm_expected_chunk.contiguous(),
        dim=1,
        original_size=N,
    )
    del tm_expected_chunk

    def _full_max_score(pair_mask: Tensor) -> Tensor:
        return torch.max(
            torch.sum(tm_expected_value * pair_mask, dim=-1)
            / (torch.sum(pair_mask, dim=-1) + 1e-5),
            dim=1,
        ).values

    pair_mask_ptm = (
        maski[:, :, None]
        * token_pad_mask_m[:, None, :]
        * token_pad_mask_m[:, :, None]
    )
    ptm = _full_max_score(pair_mask_ptm)
    pair_mask_iptm = (
        maski[:, :, None]
        * (asym_id_rep[:, None, :] != asym_id_rep[:, :, None])
        * token_pad_mask_m[:, None, :]
        * token_pad_mask_m[:, :, None]
    )
    iptm = _full_max_score(pair_mask_iptm)
    ligand_iptm_mask = pair_mask_iptm * (
        (is_ligand_token[:, :, None] * is_protein_token[:, None, :])
        + (is_protein_token[:, :, None] * is_ligand_token[:, None, :])
    )
    ligand_iptm = _full_max_score(ligand_iptm_mask)
    protein_iptm_mask = pair_mask_iptm * (
        is_protein_token[:, :, None] * is_protein_token[:, None, :]
    )
    protein_iptm = _full_max_score(protein_iptm_mask)

    pair_chains_iptm = {}
    asym_ids_list = [int(idx) for idx in torch.unique(asym_id_rep).tolist()]
    for idx1 in asym_ids_list:
        chain_iptm = {}
        for idx2 in asym_ids_list:
            mask_pair_chain = (
                maski[:, :, None]
                * (asym_id_rep[:, None, :] == idx1)
                * (asym_id_rep[:, :, None] == idx2)
                * token_pad_mask_m[:, None, :]
                * token_pad_mask_m[:, :, None]
            )
            chain_iptm[idx2] = _full_max_score(mask_pair_chain)
            del mask_pair_chain
        pair_chains_iptm[idx1] = chain_iptm
    del pair_mask_ptm, pair_mask_iptm, ligand_iptm_mask, protein_iptm_mask
    del tm_expected_value, pae_chunk_value, maski
    torch.cuda.empty_cache()
    _cmem("streamed PAE summaries done")

    # Gather d_chunk → full d (collective, small)
    d_full = gather(d_chunk.contiguous(), dim=1, original_size=N)
    del d_chunk

    keep_pde_logits = os.environ.get("BOLTZ_DAP_KEEP_PDE_LOGITS", "0") == "1"
    pde_full_cpu, pde_logits, complex_pde, complex_ipde = _confidence_pde(
        heads, z_chunk, pred_distogram_logits, token_pad_mask_base, asym_id_token,
        dap_rank, dap_size, multiplicity, keep_pde_logits, progress=_cmem,
    )
    del z_chunk
    pde = pde_full_cpu if write_full_pde else None
    _barrier()
    _cmem("chunked PDE done")

    # 3c. GPU 0: run metrics (no full z)
    if dap_rank == 0:
        torch.cuda.empty_cache()
        out_dict = {}

        if conf.return_latent_feats:
            out_dict["s_conf"] = s
            out_dict["z_conf"] = None  # not kept to save memory

        _cmem("PDE done")

        # s-only heads
        resolved_logits = heads.to_resolved_logits(s)
        plddt_logits = heads.to_plddt_logits(s)

        # ── Metric aggregation (from original ConfidenceHeads.forward) ──
        from boltz.data import const
        from boltz.model.layers.confidence_utils import (
            compute_aggregated_metric,
        )

        ligand_weight = 20
        non_interface_weight = 1
        interface_weight = 10

        if heads.token_level_confidence:
            plddt = compute_aggregated_metric(plddt_logits)
            token_pad_mask = token_pad_mask_base.repeat_interleave(multiplicity, 0)
            complex_plddt = (plddt * token_pad_mask).sum(dim=-1) / token_pad_mask.sum(dim=-1)

            is_contact = (d_full < 8).float()
            is_different_chain_metric = (
                asym_id_token.unsqueeze(-1) != asym_id_token.unsqueeze(-2)
            ).float()
            is_different_chain_metric = is_different_chain_metric.repeat_interleave(multiplicity, 0)
            token_interface_mask = torch.max(
                is_contact * is_different_chain_metric * (1 - is_ligand_token).unsqueeze(-1),
                dim=-1,
            ).values
            token_non_interface_mask = (1 - token_interface_mask) * (1 - is_ligand_token)
            iplddt_weight = (
                is_ligand_token * ligand_weight
                + token_interface_mask * interface_weight
                + token_non_interface_mask * non_interface_weight
            )
            complex_iplddt = (plddt * token_pad_mask * iplddt_weight).sum(dim=-1) / torch.sum(
                token_pad_mask * iplddt_weight, dim=-1
            )
        else:
            from torch.nn.functional import pad as nn_pad
            B_h, N_h, _ = resolved_logits.shape
            resolved_logits = resolved_logits.reshape(B_h, N_h, heads.max_num_atoms_per_token, 2)
            arange_max = torch.arange(heads.max_num_atoms_per_token).reshape(1, 1, -1).to(resolved_logits.device)
            atom_pad_mask_base = _phase3_feat("atom_pad_mask")
            atom_token_idx = _phase3_atom_token_index()
            atom_token_valid = atom_pad_mask_base.bool() & (atom_token_idx >= 0)
            safe_atom_token_idx = atom_token_idx.clamp(min=0, max=N_h - 1)
            atom_counts = torch.zeros(
                B_h,
                N_h,
                dtype=torch.long,
                device=resolved_logits.device,
            )
            atom_counts.scatter_add_(
                1,
                safe_atom_token_idx,
                atom_token_valid.long(),
            )
            max_atoms_mask = atom_counts.unsqueeze(-1) > arange_max
            resolved_logits = resolved_logits[:, max_atoms_mask.squeeze(0)]
            resolved_logits = nn_pad(resolved_logits, (0, 0, 0, int(atom_pad_mask_base.shape[1] - atom_pad_mask_base.sum().item())), value=0)
            plddt_logits = plddt_logits.reshape(B_h, N_h, heads.max_num_atoms_per_token, -1)
            plddt_logits = plddt_logits[:, max_atoms_mask.squeeze(0)]
            plddt_logits = nn_pad(plddt_logits, (0, 0, 0, int(atom_pad_mask_base.shape[1] - atom_pad_mask_base.sum().item())), value=0)
            atom_pad_mask = atom_pad_mask_base.repeat_interleave(multiplicity, 0)
            plddt = compute_aggregated_metric(plddt_logits)
            complex_plddt = (plddt * atom_pad_mask).sum(dim=-1) / atom_pad_mask.sum(dim=-1)
            token_type_f = token_type_base.float()
            chain_id_token = asym_id_token.float()
            atom_type = torch.gather(token_type_f, 1, safe_atom_token_idx)
            is_ligand_atom = (atom_type == const.chain_type_ids["NONPOLYMER"]).float()
            d_atom = torch.cdist(x_pred, x_pred)
            is_contact = (d_atom < 8).float()
            chain_id_atom = torch.gather(chain_id_token, 1, safe_atom_token_idx)
            is_different_chain_metric = (chain_id_atom.unsqueeze(-1) != chain_id_atom.unsqueeze(-2)).float()
            atom_interface_mask = torch.max(
                is_contact * is_different_chain_metric * (1 - is_ligand_atom).unsqueeze(-1), dim=-1
            ).values
            atom_non_interface_mask = (1 - atom_interface_mask) * (1 - is_ligand_atom)
            iplddt_weight = (
                is_ligand_atom * ligand_weight
                + atom_interface_mask * interface_weight
                + atom_non_interface_mask * non_interface_weight
            )
            complex_iplddt = (plddt * atom_pad_mask_base * iplddt_weight).sum(dim=-1) / torch.sum(
                atom_pad_mask_base * iplddt_weight, dim=-1
            )

        # gPDE / giPDE / pde field: already computed during chunked PDE (same formulas as confidencev2).

        out_dict.update(dict(
            pde_logits=pde_logits,
            plddt_logits=plddt_logits,
            resolved_logits=resolved_logits,
            pde=pde,
            plddt=plddt,
            complex_plddt=complex_plddt,
            complex_iplddt=complex_iplddt,
            complex_pde=complex_pde,
            complex_ipde=complex_ipde,
            ptm=ptm,
            iptm=iptm,
            ligand_iptm=ligand_iptm,
            protein_iptm=protein_iptm,
            pair_chains_iptm=pair_chains_iptm,
        ))
        if write_full_pae:
            out_dict["pae"] = pae_full_cpu

        return out_dict
    else:
        return {}
