from __future__ import annotations

from collections.abc import Callable
import math

import torch


BoundaryCallback = Callable[[str, torch.Tensor], None]


def query_row_interval(tokens: int, query_rows: int, world_size: int, rank: int) -> tuple[int, int]:
    if tokens < 1 or query_rows < 1 or world_size < 1 or not 0 <= rank < world_size:
        raise ValueError("Invalid query partition dimensions")
    chunks = (tokens + query_rows - 1) // query_rows
    per_rank, extra = divmod(chunks, world_size)
    first = rank * per_rank + min(rank, extra)
    count = per_rank + int(rank < extra)
    return min(first * query_rows, tokens), min((first + count) * query_rows, tokens)


def run_chunked_diffusion_layer(
    layer: torch.nn.Module,
    activation: torch.Tensor,
    single_conditioning: torch.Tensor,
    pair_bias: torch.Tensor | Callable[[int, int], torch.Tensor],
    mask: torch.Tensor,
    query_rows: int,
    *,
    query_interval: tuple[int, int] | None = None,
    gather_pre_output: Callable[[torch.Tensor], torch.Tensor] | None = None,
) -> torch.Tensor:
    """Reuse full-sequence projections while bounding quadratic attention storage."""
    if torch.is_grad_enabled() or layer.training:
        raise ValueError("Projection reuse requires inference-only evaluation")
    if activation.ndim != 3 or single_conditioning.shape != activation.shape:
        raise ValueError("activation and conditioning must have matching [B, N, D] shapes")
    batch, tokens, _ = activation.shape
    if not callable(pair_bias) and (pair_bias.ndim != 4 or pair_bias.shape[:3] != (batch, tokens, tokens)):
        raise ValueError("pair_bias must match the full token interval")
    if mask.shape != activation.shape[:2] or query_rows <= 0:
        raise ValueError("mask must have shape [B, N] and query_rows must be positive")
    if any(value.dtype != torch.float32 for value in (activation, single_conditioning)) or (
            not callable(pair_bias) and pair_bias.dtype != torch.float32):
        raise TypeError("Projection reuse requires FP32 inputs")
    if torch.is_autocast_enabled(activation.device.type):
        raise ValueError("Projection reuse requires disabled autocast")
    owned_start, owned_end = query_interval if query_interval is not None else (0, tokens)
    if not 0 <= owned_start <= owned_end <= tokens or (
            owned_start != tokens and owned_start % query_rows) or (
            owned_end != tokens and owned_end % query_rows):
        raise ValueError("Query ownership must preserve the original query chunks")
    if (owned_start, owned_end) != (0, tokens) and gather_pre_output is None:
        raise ValueError("Partial query ownership requires a pre-output gather")

    attention = layer.pair_bias_attn
    conditioned = layer.adaln(activation, single_conditioning)
    queries = attention.proj_q(conditioned).view(
        batch, tokens, attention.num_heads, attention.head_dim,
    )
    keys = attention.proj_k(conditioned).view_as(queries)
    values = attention.proj_v(conditioned).view_as(queries)
    gate = attention.proj_g(conditioned).sigmoid()
    del conditioned
    pre_output = activation.new_empty(batch, owned_end - owned_start, activation.shape[-1])
    for query_start in range(owned_start, owned_end, query_rows):
        query_end = min(query_start + query_rows, tokens)
        local_bias = (pair_bias(query_start, query_end) if callable(pair_bias) else
                      pair_bias[:, query_start:query_end].to(activation.device, non_blocking=True))
        if local_bias.shape[:3] != (batch, query_end - query_start, tokens) or local_bias.ndim != 4:
            raise ValueError("Streamed token bias must match the query interval")
        if local_bias.dtype != torch.float32 or local_bias.device != activation.device:
            raise ValueError("Streamed token bias must remain FP32 on the activation device")
        projected_bias = attention.proj_z(local_bias)
        logits = torch.einsum("bihd,bjhd->bhij", queries[:, query_start:query_end], keys)
        logits = logits / math.sqrt(attention.head_dim) + projected_bias
        logits = logits + (1 - mask[:, None, None].float()) * -attention.inf
        probabilities = logits.softmax(dim=-1)
        value_output = torch.einsum("bhij,bjhd->bihd", probabilities, values)
        pre_output[:, query_start - owned_start:query_end - owned_start] = gate[:, query_start:query_end] * value_output.reshape(
            batch, query_end - query_start, attention.c_s,
        )
        del local_bias, projected_bias, logits, probabilities, value_output
    del queries, keys, values, gate
    if gather_pre_output is not None:
        pre_output = gather_pre_output(pre_output)
        if (pre_output.shape != activation.shape or pre_output.dtype != activation.dtype
                or pre_output.device != activation.device):
            raise ValueError("Gathered pre-output must match the full FP32 activation")
    attention_output = attention.proj_o(pre_output)
    del pre_output
    attention_residual = activation + layer.output_projection(single_conditioning) * attention_output
    del attention_output
    transition_update = layer.transition(attention_residual, single_conditioning)
    return layer.post_lnorm(attention_residual + transition_update)


def run_query_sharded_diffusion_layer(
    layer: torch.nn.Module,
    activation: torch.Tensor,
    single_conditioning: torch.Tensor,
    pair_bias_rows: torch.Tensor,
    mask: torch.Tensor,
    query_start: int,
    query_end: int,
    *,
    boundary_callback: BoundaryCallback | None = None,
) -> torch.Tensor:
    """Evaluate one diffusion-transformer layer for a local query interval."""
    if activation.ndim != 3 or single_conditioning.shape != activation.shape:
        raise ValueError("activation and conditioning must have matching [B, N, D] shapes")
    if not 0 <= query_start < query_end <= activation.shape[1]:
        raise ValueError(f"invalid query interval [{query_start}, {query_end})")
    if pair_bias_rows.shape[:3] != (
        activation.shape[0],
        query_end - query_start,
        activation.shape[1],
    ):
        raise ValueError("pair_bias_rows does not match the requested query interval")
    if mask.shape != activation.shape[:2]:
        raise ValueError("mask must have shape [B, N]")
    if activation.dtype != torch.float32 or pair_bias_rows.dtype != torch.float32:
        raise TypeError("Phase 4 reference path requires FP32 activation and pair bias")

    def record(name: str, value: torch.Tensor) -> None:
        if boundary_callback is not None:
            boundary_callback(name, value)

    attention = layer.pair_bias_attn
    conditioned = layer.adaln(activation, single_conditioning)
    conditioned_queries = conditioned[:, query_start:query_end]
    conditioning_rows = single_conditioning[:, query_start:query_end]
    activation_rows = activation[:, query_start:query_end]

    batch = activation.shape[0]
    all_queries = attention.proj_q(conditioned).view(
        batch,
        activation.shape[1],
        attention.num_heads,
        attention.head_dim,
    )
    queries = all_queries[:, query_start:query_end]
    keys = attention.proj_k(conditioned).view(
        batch,
        activation.shape[1],
        attention.num_heads,
        attention.head_dim,
    )
    values = attention.proj_v(conditioned).view_as(keys)
    all_gates = attention.proj_g(conditioned).sigmoid()
    gate = all_gates[:, query_start:query_end]
    projected_bias = attention.proj_z(pair_bias_rows)

    with torch.autocast(device_type=activation.device.type, enabled=False):
        logits = torch.einsum(
            "bihd,bjhd->bhij",
            queries.float(),
            keys.float(),
        )
        logits = logits / math.sqrt(attention.head_dim) + projected_bias.float()
        logits = logits + (1 - mask[:, None, None].float()) * -attention.inf
        probabilities = logits.softmax(dim=-1)
        value_output = torch.einsum(
            "bhij,bjhd->bihd",
            probabilities,
            values.float(),
        ).to(values.dtype)

    pre_output_projection = gate * value_output.reshape(
        batch,
        query_end - query_start,
        attention.c_s,
    )
    staged_pre_output = torch.zeros_like(activation)
    staged_pre_output[:, query_start:query_end] = pre_output_projection
    attention_output = attention.proj_o(staged_pre_output)[:, query_start:query_end]
    layer_output_gate = layer.output_projection(single_conditioning)[
        :, query_start:query_end
    ]
    gated_update = layer_output_gate * attention_output
    attention_residual = activation_rows + gated_update
    staged_attention_residual = torch.zeros_like(activation)
    staged_attention_residual[:, query_start:query_end] = attention_residual
    transition_update = layer.transition(
        staged_attention_residual,
        single_conditioning,
    )[:, query_start:query_end]
    transition_residual = attention_residual + transition_update
    final = layer.post_lnorm(transition_residual)

    for name, value in (
        ("conditioned_queries", conditioned_queries),
        ("queries", queries),
        ("keys", keys),
        ("values", values),
        ("attention_gate", gate),
        ("projected_pair_bias", projected_bias),
        ("pre_softmax_logits", logits),
        ("probabilities", probabilities),
        ("value_output", value_output),
        ("pre_output_projection", pre_output_projection),
        ("attention_output", attention_output),
        ("layer_output_gate", layer_output_gate),
        ("gated_update", gated_update),
        ("attention_residual", attention_residual),
        ("transition_update", transition_update),
        ("transition_residual", transition_residual),
        ("final", final),
    ):
        record(name, value)
    return final