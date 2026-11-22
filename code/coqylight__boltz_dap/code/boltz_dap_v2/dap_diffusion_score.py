from __future__ import annotations

from collections.abc import Callable
import os

import torch

from boltz.model.layers.token_bias import LayerwiseTokenBias
from dap_atom_diffusion_transformer import run_chunked_atom_layer, run_window_sharded_atom_layer
from dap_diffusion_transformer import run_chunked_diffusion_layer, run_query_sharded_diffusion_layer
from dap_features import atom_to_token_indices


StageCallback = Callable[[str, torch.Tensor], None]


def _pool_atom_features_deterministically(*args, **kwargs) -> torch.Tensor:
    enabled = torch.are_deterministic_algorithms_enabled()
    warn_only = torch.is_deterministic_algorithms_warn_only_enabled()
    try:
        torch.use_deterministic_algorithms(True)
        return _pool_atom_features_by_token(*args, **kwargs)
    finally:
        torch.use_deterministic_algorithms(enabled, warn_only=warn_only)


def _pool_atom_features_by_token(
    atom_features: torch.Tensor,
    atom_token_idx: torch.Tensor,
    atom_token_valid: torch.Tensor,
    token_count: int,
) -> torch.Tensor:
    safe_indices = atom_token_idx.clamp(min=0, max=token_count - 1)
    valid = atom_token_valid.unsqueeze(-1).to(dtype=atom_features.dtype)
    pooled = torch.zeros(
        atom_features.shape[0],
        token_count,
        atom_features.shape[-1],
        dtype=atom_features.dtype,
        device=atom_features.device,
    )
    pooled.scatter_add_(
        1,
        safe_indices.unsqueeze(-1).expand_as(atom_features),
        atom_features * valid,
    )
    counts = torch.zeros(
        atom_features.shape[0],
        token_count,
        1,
        dtype=atom_features.dtype,
        device=atom_features.device,
    )
    counts.scatter_add_(1, safe_indices.unsqueeze(-1), valid)
    return pooled / (counts + 1e-6)


def _broadcast_token_features_to_atoms(
    token_features: torch.Tensor,
    atom_token_idx: torch.Tensor,
    atom_token_valid: torch.Tensor,
) -> torch.Tensor:
    safe_indices = atom_token_idx.clamp(min=0, max=token_features.shape[1] - 1)
    gathered = torch.gather(
        token_features,
        1,
        safe_indices.unsqueeze(-1).expand(
            -1,
            -1,
            token_features.shape[-1],
        ),
    )
    return gathered * atom_token_valid.unsqueeze(-1).to(dtype=gathered.dtype)


def _run_atom_stack(
    atom_transformer: torch.nn.Module,
    activation: torch.Tensor,
    conditioning: torch.Tensor,
    concatenated_bias: torch.Tensor,
    mask: torch.Tensor,
    to_keys,
    window_rows: int,
) -> torch.Tensor:
    batch_size, atoms, atom_dim = activation.shape
    reuse_projections = os.environ.get("BOLTZ_DIFFUSION_REUSE_ATOM_PROJECTIONS", "0")
    if reuse_projections not in ("0", "1"):
        raise ValueError("BOLTZ_DIFFUSION_REUSE_ATOM_PROJECTIONS must be 0 or 1")
    query_width = atom_transformer.attn_window_queries
    key_width = atom_transformer.attn_window_keys
    if atoms % query_width:
        raise ValueError(f"atom count {atoms} is not divisible by {query_width}")
    windows_per_batch = atoms // query_width
    batch_windows = batch_size * windows_per_batch
    window_activation = activation.view(batch_windows, query_width, atom_dim)
    window_conditioning = conditioning.view(batch_windows, query_width, atom_dim)
    window_mask = mask.view(batch_windows, query_width).float()
    window_bias = concatenated_bias.view(
        batch_windows,
        query_width,
        key_width,
        -1,
    )
    layers = atom_transformer.diffusion_transformer.layers
    if window_bias.shape[-1] % len(layers):
        raise ValueError("atom bias width is not divisible by layer count")
    bias_per_layer = window_bias.shape[-1] // len(layers)
    window_bias = window_bias.view(
        batch_windows,
        query_width,
        key_width,
        len(layers),
        bias_per_layer,
    )

    def to_window_keys(value: torch.Tensor) -> torch.Tensor:
        return to_keys(value.view(batch_size, atoms, -1)).view(
            batch_windows,
            key_width,
            -1,
        )

    for layer_index, layer in enumerate(layers):
        layer_bias = window_bias[..., layer_index, :]
        if reuse_projections == "1":
            window_activation = run_chunked_atom_layer(
                layer, window_activation, window_conditioning, layer_bias,
                window_mask, to_window_keys, window_rows,
            )
            del layer_bias
            continue
        layer_output = torch.empty_like(window_activation)
        for window_start in range(0, batch_windows, window_rows):
            window_end = min(window_start + window_rows, batch_windows)
            local_bias = layer_bias[window_start:window_end].to(
                window_activation.device,
                non_blocking=True,
            )
            layer_output[window_start:window_end] = run_window_sharded_atom_layer(
                layer,
                window_activation,
                window_conditioning,
                local_bias,
                window_mask,
                to_window_keys,
                window_start,
                window_end,
            )
        window_activation = layer_output
    return window_activation.view(batch_size, atoms, atom_dim)


def _run_token_stack(
    token_transformer: torch.nn.Module,
    activation: torch.Tensor,
    conditioning: torch.Tensor,
    token_bias: torch.Tensor | LayerwiseTokenBias,
    mask: torch.Tensor,
    query_rows: int,
) -> torch.Tensor:
    cache_service = getattr(token_transformer, "_dap_token_attention_service", None)
    if cache_service is not None:
        return cache_service.run(token_transformer, activation, conditioning, token_bias, mask, query_rows)
    layers = token_transformer.layers
    reuse_projections = os.environ.get("BOLTZ_DIFFUSION_REUSE_TOKEN_PROJECTIONS", "0")
    if reuse_projections not in ("0", "1"):
        raise ValueError("BOLTZ_DIFFUSION_REUSE_TOKEN_PROJECTIONS must be 0 or 1")
    stream_bias = os.environ.get("BOLTZ_DIFFUSION_STREAM_TOKEN_BIAS", "0")
    if stream_bias not in ("0", "1"):
        raise ValueError("BOLTZ_DIFFUSION_STREAM_TOKEN_BIAS must be 0 or 1")
    if stream_bias == "1" and not isinstance(token_bias, LayerwiseTokenBias):
        raise ValueError("Streamed token bias requires the layerwise provider")
    if isinstance(token_bias, LayerwiseTokenBias):
        if torch.is_grad_enabled() or token_transformer.training or len(token_bias) != len(layers):
            raise ValueError("Layerwise token bias requires matching inference-only layers")
        if activation.dtype != torch.float32 or conditioning.dtype != torch.float32:
            raise ValueError("Layerwise token bias requires FP32 inputs")

        def get_layer_bias(layer_index: int):
            if stream_bias == "1":
                return lambda start, end: token_bias.project_rows(layer_index, start, end, activation.device)
            return token_bias.project_layer(layer_index, activation.device)

    elif token_bias.ndim == 4:
        if token_bias.shape[-1] % len(layers):
            raise ValueError("token bias width is not divisible by layer count")
        bias_per_layer = token_bias.shape[-1] // len(layers)
        layer_biases = token_bias.view(
            *token_bias.shape[:-1],
            len(layers),
            bias_per_layer,
        )

        def get_layer_bias(layer_index: int) -> torch.Tensor:
            return layer_biases[..., layer_index, :]

    elif token_bias.ndim == 5:
        if token_bias.shape[0] != len(layers):
            raise ValueError(
                "layer-major token bias first dimension does not match layer count"
            )

        def get_layer_bias(layer_index: int) -> torch.Tensor:
            return token_bias[layer_index]

    else:
        raise ValueError(
            f"token bias must use concat (4D) or layer-major (5D) layout, "
            f"got shape {tuple(token_bias.shape)}"
        )

    tokens = activation.shape[1]
    for layer_index, layer in enumerate(layers):
        layer_bias = get_layer_bias(layer_index)
        if reuse_projections == "1":
            activation = run_chunked_diffusion_layer(
                layer, activation, conditioning, layer_bias, mask, query_rows,
            )
            del layer_bias
            continue
        layer_output = torch.empty_like(activation)
        for query_start in range(0, tokens, query_rows):
            query_end = min(query_start + query_rows, tokens)
            local_bias = (layer_bias(query_start, query_end) if callable(layer_bias) else
                          layer_bias[:, query_start:query_end].to(activation.device, non_blocking=True))
            layer_output[:, query_start:query_end] = (
                run_query_sharded_diffusion_layer(
                    layer,
                    activation,
                    conditioning,
                    local_bias,
                    mask,
                    query_start,
                    query_end,
                )
            )
        activation = layer_output
        del layer_bias, local_bias
    return activation


def run_sharded_diffusion_score(
    score_model: torch.nn.Module,
    *,
    s_inputs: torch.Tensor,
    s_trunk: torch.Tensor,
    r_noisy: torch.Tensor,
    times: torch.Tensor,
    feats: dict[str, torch.Tensor],
    diffusion_conditioning: dict[str, torch.Tensor],
    token_query_rows: int,
    atom_window_rows: int,
    stage_callback: StageCallback | None = None,
) -> torch.Tensor:
    """Run one FP32 score call with query- and window-sharded attention."""
    if token_query_rows <= 0 or atom_window_rows <= 0:
        raise ValueError("shard extents must be positive")
    if r_noisy.dtype != torch.float32:
        raise TypeError("Phase 4 score reference requires FP32 coordinates")
    deterministic_pooling = os.environ.get("BOLTZ_DIFFUSION_DETERMINISTIC_POOLING", "0")
    if deterministic_pooling not in ("0", "1"):
        raise ValueError("BOLTZ_DIFFUSION_DETERMINISTIC_POOLING must be 0 or 1")

    def record(name: str, value: torch.Tensor) -> None:
        if stage_callback is not None:
            stage_callback(name, value)

    single_conditioning, _ = score_model.single_conditioner(
        times,
        s_trunk,
        s_inputs,
    )
    record("single_conditioning", single_conditioning)

    encoder = score_model.atom_attention_encoder
    atom_activation = diffusion_conditioning["q"].float()
    atom_conditioning = diffusion_conditioning["c"].float()
    atom_activation = atom_activation + encoder.r_to_q_trans(r_noisy)
    atom_activation = _run_atom_stack(
        encoder.atom_encoder,
        atom_activation,
        atom_conditioning,
        diffusion_conditioning["atom_enc_bias"].float(),
        feats["atom_pad_mask"],
        diffusion_conditioning["to_keys"],
        atom_window_rows,
    )
    record("atom_encoder_q", atom_activation)
    record("atom_encoder_c", atom_conditioning)

    with torch.autocast(device_type=r_noisy.device.type, enabled=False):
        atom_token_idx, atom_token_valid = atom_to_token_indices(feats)
        pool = (_pool_atom_features_deterministically if deterministic_pooling == "1" else
            _pool_atom_features_by_token)
        token_activation = pool(
            encoder.atom_to_token_trans(atom_activation).float(),
            atom_token_idx,
            atom_token_valid,
            s_inputs.shape[1],
        )
    token_activation = token_activation.to(atom_activation)
    record("atom_encoder_token", token_activation)
    token_activation = token_activation + score_model.s_to_a_linear(
        single_conditioning
    )
    record("token_input", token_activation)

    token_bias = diffusion_conditioning["token_trans_bias"]
    token_activation = _run_token_stack(
        score_model.token_transformer,
        token_activation,
        single_conditioning,
        token_bias if isinstance(token_bias, LayerwiseTokenBias) else token_bias.float(),
        feats["token_pad_mask"].float(),
        token_query_rows,
    )
    record("token_transformer_output", token_activation)
    token_activation = score_model.a_norm(token_activation)
    record("token_norm_output", token_activation)

    decoder = score_model.atom_attention_decoder
    with torch.autocast(device_type=r_noisy.device.type, enabled=False):
        token_to_atom = decoder.a_to_q_trans(token_activation.float())
        token_to_atom = _broadcast_token_features_to_atoms(
            token_to_atom,
            atom_token_idx,
            atom_token_valid,
        )
    atom_activation = atom_activation + token_to_atom.to(atom_activation)
    atom_activation = _run_atom_stack(
        decoder.atom_decoder,
        atom_activation,
        atom_conditioning,
        diffusion_conditioning["atom_dec_bias"].float(),
        feats["atom_pad_mask"],
        diffusion_conditioning["to_keys"],
        atom_window_rows,
    )
    position_update = decoder.atom_feat_to_atom_pos_update(atom_activation)
    record("atom_decoder_output", position_update)
    return position_update