from __future__ import annotations

from collections.abc import Callable
import math

import torch


BoundaryCallback = Callable[[str, torch.Tensor], None]


def run_chunked_atom_layer(
    layer: torch.nn.Module,
    activation: torch.Tensor,
    single_conditioning: torch.Tensor,
    pair_bias: torch.Tensor,
    mask: torch.Tensor,
    to_keys: Callable[[torch.Tensor], torch.Tensor],
    window_rows: int,
) -> torch.Tensor:
    """Reuse window projections and key indexing across bounded attention chunks."""
    if torch.is_grad_enabled() or layer.training:
        raise ValueError("Projection reuse requires inference-only evaluation")
    if activation.ndim != 3 or single_conditioning.shape != activation.shape:
        raise ValueError("activation and conditioning must have matching [BW, W, D] shapes")
    if pair_bias.ndim != 4 or pair_bias.shape[:2] != activation.shape[:2]:
        raise ValueError("pair_bias must match the full window interval")
    if mask.shape != activation.shape[:2] or window_rows <= 0:
        raise ValueError("mask must match the windows and window_rows must be positive")
    if any(value.dtype != torch.float32 for value in (activation, single_conditioning, pair_bias)):
        raise TypeError("Projection reuse requires FP32 inputs")
    if torch.is_autocast_enabled(activation.device.type):
        raise ValueError("Projection reuse requires disabled autocast")

    attention = layer.pair_bias_attn
    conditioned = layer.adaln(activation, single_conditioning)
    key_conditioned = to_keys(conditioned)
    key_mask = to_keys(mask.unsqueeze(-1)).squeeze(-1)
    batch_windows, query_atoms, _ = activation.shape
    queries = attention.proj_q(conditioned).view(
        batch_windows, query_atoms, attention.num_heads, attention.head_dim,
    )
    keys = attention.proj_k(key_conditioned).view(
        batch_windows, key_conditioned.shape[1], attention.num_heads, attention.head_dim,
    )
    values = attention.proj_v(key_conditioned).view_as(keys)
    gate = attention.proj_g(conditioned).sigmoid()
    del conditioned, key_conditioned
    pre_output = torch.empty_like(activation)
    for window_start in range(0, batch_windows, window_rows):
        window_end = min(window_start + window_rows, batch_windows)
        local_bias = pair_bias[window_start:window_end].to(activation.device, non_blocking=True)
        projected_bias = attention.proj_z(local_bias)
        logits = torch.einsum(
            "bihd,bjhd->bhij", queries[window_start:window_end], keys[window_start:window_end],
        )
        logits = logits / math.sqrt(attention.head_dim) + projected_bias
        logits = logits + (1 - key_mask[window_start:window_end, None, None].float()) * -attention.inf
        probabilities = logits.softmax(dim=-1)
        value_output = torch.einsum("bhij,bjhd->bihd", probabilities, values[window_start:window_end])
        pre_output[window_start:window_end] = gate[window_start:window_end] * value_output.reshape(
            window_end - window_start, query_atoms, attention.c_s,
        )
        del local_bias, projected_bias, logits, probabilities, value_output
    del queries, keys, values, gate, key_mask
    attention_output = attention.proj_o(pre_output)
    del pre_output
    attention_residual = activation + layer.output_projection(single_conditioning) * attention_output
    del attention_output
    transition_update = layer.transition(attention_residual, single_conditioning)
    return layer.post_lnorm(attention_residual + transition_update)


def run_window_sharded_atom_layer(
    layer: torch.nn.Module,
    activation: torch.Tensor,
    single_conditioning: torch.Tensor,
    pair_bias_windows: torch.Tensor,
    mask: torch.Tensor,
    to_keys: Callable[[torch.Tensor], torch.Tensor],
    window_start: int,
    window_end: int,
    *,
    boundary_callback: BoundaryCallback | None = None,
) -> torch.Tensor:
    """Evaluate one atom-transformer layer for a local interval of windows."""
    if activation.ndim != 3 or single_conditioning.shape != activation.shape:
        raise ValueError("activation and conditioning must have matching [BW, W, D] shapes")
    if not 0 <= window_start < window_end <= activation.shape[0]:
        raise ValueError(f"invalid window interval [{window_start}, {window_end})")
    if mask.shape != activation.shape[:2]:
        raise ValueError("mask must have shape [BW, W]")
    if activation.dtype != torch.float32 or pair_bias_windows.dtype != torch.float32:
        raise TypeError("Phase 4 reference path requires FP32 activation and pair bias")

    def record(name: str, value: torch.Tensor) -> None:
        if boundary_callback is not None:
            boundary_callback(name, value)

    attention = layer.pair_bias_attn
    conditioned = layer.adaln(activation, single_conditioning)
    key_conditioned = to_keys(conditioned)
    key_mask = to_keys(mask.unsqueeze(-1)).squeeze(-1)
    local_conditioned = conditioned[window_start:window_end]
    local_conditioning = single_conditioning[window_start:window_end]
    local_activation = activation[window_start:window_end]

    batch_windows = activation.shape[0]
    queries = attention.proj_q(conditioned).view(
        batch_windows,
        activation.shape[1],
        attention.num_heads,
        attention.head_dim,
    )[window_start:window_end]
    all_keys = attention.proj_k(key_conditioned).view(
        batch_windows,
        key_conditioned.shape[1],
        attention.num_heads,
        attention.head_dim,
    )
    keys = all_keys[window_start:window_end]
    values = attention.proj_v(key_conditioned).view_as(all_keys)[
        window_start:window_end
    ]
    gate = attention.proj_g(conditioned).sigmoid()[window_start:window_end]
    projected_bias = attention.proj_z(pair_bias_windows)

    with torch.autocast(device_type=activation.device.type, enabled=False):
        logits = torch.einsum(
            "bihd,bjhd->bhij",
            queries.float(),
            keys.float(),
        )
        logits = logits / math.sqrt(attention.head_dim) + projected_bias.float()
        logits = logits + (
            1 - key_mask[window_start:window_end, None, None].float()
        ) * -attention.inf
        probabilities = logits.softmax(dim=-1)
        value_output = torch.einsum(
            "bhij,bjhd->bihd",
            probabilities,
            values.float(),
        ).to(values.dtype)

    pre_output_projection = gate * value_output.reshape(
        window_end - window_start,
        activation.shape[1],
        attention.c_s,
    )
    staged_pre_output = torch.zeros_like(activation)
    staged_pre_output[window_start:window_end] = pre_output_projection
    attention_output = attention.proj_o(staged_pre_output)[window_start:window_end]
    layer_output_gate = layer.output_projection(single_conditioning)[
        window_start:window_end
    ]
    gated_update = layer_output_gate * attention_output
    attention_residual = local_activation + gated_update
    staged_attention_residual = torch.zeros_like(activation)
    staged_attention_residual[window_start:window_end] = attention_residual
    transition_update = layer.transition(
        staged_attention_residual,
        single_conditioning,
    )[window_start:window_end]
    transition_residual = attention_residual + transition_update
    final = layer.post_lnorm(transition_residual)

    for name, value in (
        ("conditioned_queries", local_conditioned),
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