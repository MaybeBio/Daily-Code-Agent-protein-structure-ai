"""Runtime compatibility patches for unmodified Boltz-2 installs.

Boltz-DAP CPU-offloads the diffusion token transformer bias to keep large
complexes from OOMing. Stock Boltz assumes that bias is already on the same
CUDA device as the attention activations, so we patch the narrow call sites
that consume the bias instead of requiring users to edit Boltz source files.
"""

from __future__ import annotations

import math
import os
from typing import Any

import torch
import torch.nn.functional as F
from torch.nn.attention import SDPBackend, sdpa_kernel


_DIFFUSION_ATTN_BACKEND_ENV = "BOLTZ_DIFFUSION_ATTN_BACKEND"
_DIFFUSION_ATTN_DTYPE_ENV = "BOLTZ_DIFFUSION_ATTN_SDPA_DTYPE"


class _LayerMajorBiasAdapter:
    def __init__(self, bias: torch.Tensor) -> None:
        if bias.ndim != 5:
            raise ValueError(f"layer-major token bias must be 5D, got {bias.shape}")
        layers, batch, rows, cols, heads = bias.shape
        self._bias = bias
        self._heads = heads
        self.device = bias.device
        self.shape = torch.Size((batch, rows, cols, layers * heads))

    def __getitem__(self, key: Any) -> torch.Tensor:
        if not isinstance(key, tuple) or len(key) != 2 or key[0] is not Ellipsis:
            raise IndexError(f"unsupported layer-major token bias index: {key!r}")
        channel_slice = key[1]
        if not isinstance(channel_slice, slice):
            raise IndexError(f"token bias channels require a slice, got {key!r}")
        start = 0 if channel_slice.start is None else channel_slice.start
        stop = self.shape[-1] if channel_slice.stop is None else channel_slice.stop
        if channel_slice.step not in {None, 1} or stop - start != self._heads:
            raise IndexError(f"token bias slice must select one layer, got {key!r}")
        if start % self._heads != 0:
            raise IndexError(f"token bias slice is not layer-aligned: {key!r}")
        layer_index = start // self._heads
        if not 0 <= layer_index < self._bias.shape[0]:
            raise IndexError(f"token bias layer is out of range: {key!r}")
        return self._bias[layer_index]


def _attention_supports_cpu_bias_streaming(layer: torch.nn.Module) -> bool:
    forward = type(layer.pair_bias_attn).forward
    code = getattr(forward, "__code__", None)
    return bool(
        getattr(forward, "_boltz_dap_sdpa_backend", None)
        or (code is not None and "query_chunk" in code.co_varnames)
    )


def _diffusion_sdpa_config() -> tuple[str, SDPBackend | None, torch.dtype | None]:
    backend_name = os.environ.get(_DIFFUSION_ATTN_BACKEND_ENV, "explicit").lower()
    backends = {
        "efficient": SDPBackend.EFFICIENT_ATTENTION,
        "cudnn": SDPBackend.CUDNN_ATTENTION,
    }
    if backend_name == "explicit":
        return backend_name, None, None
    if backend_name not in backends:
        allowed = "explicit, efficient, cudnn"
        raise ValueError(
            f"Invalid {_DIFFUSION_ATTN_BACKEND_ENV}={backend_name!r}; "
            f"expected one of: {allowed}"
        )

    dtype_name = os.environ.get(_DIFFUSION_ATTN_DTYPE_ENV, "fp32").lower()
    dtypes = {"fp32": torch.float32, "bf16": torch.bfloat16}
    if dtype_name not in dtypes:
        raise ValueError(
            f"Invalid {_DIFFUSION_ATTN_DTYPE_ENV}={dtype_name!r}; "
            "expected one of: fp32, bf16"
        )
    return backend_name, backends[backend_name], dtypes[dtype_name]


def _patch_diffusion_attention() -> tuple[bool, str | None]:
    from boltz.model.layers.attentionv2 import AttentionPairBias

    backend_name, backend, sdpa_dtype = _diffusion_sdpa_config()
    if backend_name == "explicit":
        return False, None

    patched_backend = getattr(
        AttentionPairBias.forward,
        "_boltz_dap_sdpa_backend",
        None,
    )
    patched_dtype = getattr(
        AttentionPairBias.forward,
        "_boltz_dap_sdpa_dtype",
        None,
    )
    if patched_backend is not None:
        if patched_backend != backend_name or patched_dtype != sdpa_dtype:
            raise RuntimeError(
                "Diffusion attention is already patched for "
                f"backend={patched_backend!r}, dtype={patched_dtype}; requested "
                f"backend={backend_name!r}, dtype={sdpa_dtype}"
            )
        return False, backend_name

    original_forward = AttentionPairBias.forward
    logged_selection = False

    def forward_with_forced_sdpa(
        self: torch.nn.Module,
        s: torch.Tensor,
        z: torch.Tensor,
        mask: torch.Tensor,
        k_in: torch.Tensor,
        multiplicity: int = 1,
    ) -> torch.Tensor:
        nonlocal logged_selection

        if self.training or self.compute_pair_bias:
            return original_forward(self, s, z, mask, k_in, multiplicity)

        batch = s.shape[0]
        q = self.proj_q(s).view(batch, -1, self.num_heads, self.head_dim)
        k = self.proj_k(k_in).view(batch, -1, self.num_heads, self.head_dim)
        v = self.proj_v(k_in).view(batch, -1, self.num_heads, self.head_dim)
        g = self.proj_g(s).sigmoid()

        query_chunk = int(os.environ.get("BOLTZ_DIFFUSION_ATTN_Q_CHUNK", "0"))
        if not 0 < query_chunk < q.shape[1]:
            raise RuntimeError(
                f"{_DIFFUSION_ATTN_BACKEND_ENV}={backend_name} requires "
                "eval-mode streamed diffusion attention with "
                "0 < BOLTZ_DIFFUSION_ATTN_Q_CHUNK < sequence length"
            )

        output = torch.empty_like(q)
        scale = 1.0 / math.sqrt(self.head_dim)
        with torch.autocast(device_type=q.device.type, enabled=False):
            key_sdpa = k.permute(0, 2, 1, 3).to(dtype=sdpa_dtype)
            value_sdpa = v.permute(0, 2, 1, 3).to(dtype=sdpa_dtype)
            mask_bias = (1 - mask[:, None, None].to(dtype=sdpa_dtype)) * -self.inf

            for query_start in range(0, q.shape[1], query_chunk):
                query_end = min(query_start + query_chunk, q.shape[1])
                bias_chunk = z[:, query_start:query_end]
                if bias_chunk.device != q.device:
                    bias_chunk = bias_chunk.to(q.device)
                bias_chunk = self.proj_z(bias_chunk)
                bias_chunk = bias_chunk.repeat_interleave(multiplicity, 0)
                attention_mask = bias_chunk.to(dtype=sdpa_dtype) + mask_bias
                query_sdpa = q[:, query_start:query_end].permute(0, 2, 1, 3)
                query_sdpa = query_sdpa.to(dtype=sdpa_dtype)

                with sdpa_kernel(backend):
                    output_chunk = F.scaled_dot_product_attention(
                        query_sdpa,
                        key_sdpa,
                        value_sdpa,
                        attn_mask=attention_mask,
                        dropout_p=0.0,
                        is_causal=False,
                        scale=scale,
                        enable_gqa=False,
                    )

                if not logged_selection:
                    device_name = str(q.device)
                    allocated_mib = reserved_mib = peak_mib = 0.0
                    if q.device.type == "cuda":
                        device_name = torch.cuda.get_device_name(q.device)
                        allocated_mib = torch.cuda.memory_allocated(q.device) / 1024**2
                        reserved_mib = torch.cuda.memory_reserved(q.device) / 1024**2
                        peak_mib = torch.cuda.max_memory_allocated(q.device) / 1024**2
                    if os.environ.get("RANK", "0") == "0":
                        print(
                            "[BOLTZ-DAP][SDPA] "
                            f"forced_backend={backend_name} dtype={sdpa_dtype} "
                            f"torch={torch.__version__} cuda={torch.version.cuda} "
                            f"cudnn={torch.backends.cudnn.version()} "
                            f"device={device_name} q={tuple(query_sdpa.shape)} "
                            f"k={tuple(key_sdpa.shape)} v={tuple(value_sdpa.shape)} "
                            f"mask={tuple(attention_mask.shape)} "
                            f"strides={query_sdpa.stride()}/{key_sdpa.stride()}/"
                            f"{value_sdpa.stride()}/{attention_mask.stride()} "
                            f"q_chunk={query_chunk} scale={scale:.12g} "
                            f"allocated_mib={allocated_mib:.1f} "
                            f"reserved_mib={reserved_mib:.1f} peak_mib={peak_mib:.1f}",
                            flush=True,
                        )
                    logged_selection = True

                output_chunk = output_chunk.permute(0, 2, 1, 3).to(v.dtype)
                output[:, query_start:query_end].copy_(output_chunk)
                del bias_chunk, attention_mask, query_sdpa, output_chunk

            del key_sdpa, value_sdpa, mask_bias

        output = output.reshape(batch, -1, self.c_s)
        return self.proj_o(g * output)

    forward_with_forced_sdpa._boltz_dap_sdpa_backend = backend_name
    forward_with_forced_sdpa._boltz_dap_sdpa_dtype = sdpa_dtype
    forward_with_forced_sdpa._boltz_dap_original_forward = original_forward
    AttentionPairBias.forward = forward_with_forced_sdpa
    return True, backend_name


def _move_conditioning_tensors_to_device(
    diffusion_conditioning: dict[str, Any],
    device: torch.device,
) -> None:
    """Move small conditioning tensors to ``device`` in-place.

    ``token_trans_bias`` can be huge, so it stays CPU-resident and is moved one
    layer at a time by the DiffusionTransformer patch below.
    """

    for key, value in list(diffusion_conditioning.items()):
        if key == "token_trans_bias":
            continue
        if isinstance(value, torch.Tensor) and value.device != device:
            diffusion_conditioning[key] = value.to(device)


def _ensure_to_keys(
    module: torch.nn.Module,
    feats: dict[str, torch.Tensor],
    diffusion_conditioning: dict[str, Any],
    device: torch.device,
) -> None:
    """Create ``to_keys`` locally when DAP broadcast omitted non-tensor values."""

    if callable(diffusion_conditioning.get("to_keys")):
        return

    from boltz.model.modules.encodersv2 import get_indexing_matrix, single_to_keys

    _, num_atoms, _ = feats["ref_pos"].shape
    window_queries = module.atoms_per_window_queries
    window_keys = module.atoms_per_window_keys
    num_windows = num_atoms // window_queries
    indexing_matrix = get_indexing_matrix(
        num_windows,
        window_queries,
        window_keys,
        device=device,
    )

    def to_keys(single: torch.Tensor) -> torch.Tensor:
        return single_to_keys(
            single,
            indexing_matrix=indexing_matrix,
            W=window_queries,
            H=window_keys,
        )

    diffusion_conditioning["to_keys"] = to_keys


def _patch_diffusion_module() -> bool:
    from boltz.model.modules.diffusionv2 import DiffusionModule

    if getattr(DiffusionModule.forward, "_boltz_dap_compat_patched", False):
        return False

    original_forward = DiffusionModule.forward

    def forward_with_dap_compat(
        self: torch.nn.Module,
        s_inputs: torch.Tensor,
        s_trunk: torch.Tensor,
        r_noisy: torch.Tensor,
        times: torch.Tensor,
        feats: dict[str, torch.Tensor],
        diffusion_conditioning: dict[str, Any],
        multiplicity: int = 1,
    ) -> torch.Tensor:
        device = r_noisy.device
        _move_conditioning_tensors_to_device(diffusion_conditioning, device)
        _ensure_to_keys(self, feats, diffusion_conditioning, device)
        token_bias = diffusion_conditioning.get("token_trans_bias")
        if isinstance(token_bias, torch.Tensor) and token_bias.ndim == 5:
            diffusion_conditioning["token_trans_bias"] = _LayerMajorBiasAdapter(
                token_bias
            )
        try:
            return original_forward(
                self,
                s_inputs=s_inputs,
                s_trunk=s_trunk,
                r_noisy=r_noisy,
                times=times,
                feats=feats,
                diffusion_conditioning=diffusion_conditioning,
                multiplicity=multiplicity,
            )
        finally:
            if isinstance(token_bias, torch.Tensor) and token_bias.ndim == 5:
                diffusion_conditioning["token_trans_bias"] = token_bias

    forward_with_dap_compat._boltz_dap_compat_patched = True
    forward_with_dap_compat._boltz_dap_original_forward = original_forward
    DiffusionModule.forward = forward_with_dap_compat
    return True


def _patch_diffusion_transformer() -> bool:
    from boltz.model.modules.transformersv2 import DiffusionTransformer

    if getattr(DiffusionTransformer.forward, "_boltz_dap_compat_patched", False):
        return False

    def forward_with_dap_compat(
        self: torch.nn.Module,
        a: torch.Tensor,
        s: torch.Tensor,
        bias: torch.Tensor | list[torch.Tensor] | tuple[torch.Tensor, ...] | None = None,
        mask: torch.Tensor | None = None,
        to_keys: Any = None,
        multiplicity: int = 1,
    ) -> torch.Tensor:
        bias_is_list = isinstance(bias, (list, tuple))
        if self.pair_bias_attn and not bias_is_list:
            if bias is None:
                raise ValueError("DiffusionTransformer requires bias when pair_bias_attn=True")
            batch, rows, cols, channels = bias.shape
            num_layers = len(self.layers)
            bias = bias.view(batch, rows, cols, num_layers, channels // num_layers)

        for i, layer in enumerate(self.layers):
            if self.pair_bias_attn:
                if bias_is_list:
                    bias_l = bias[i]
                else:
                    bias_l = bias[:, :, :, i]

                query_chunk = int(
                    os.environ.get("BOLTZ_DIFFUSION_ATTN_Q_CHUNK", "0")
                )
                stream_cpu_bias = (
                    os.environ.get(
                        "BOLTZ_DIFFUSION_BIAS_LAYOUT",
                        "concat",
                    ).lower()
                    == "layer_major"
                    and not self.training
                    and bias_l.device.type == "cpu"
                    and 0 < query_chunk < a.shape[1]
                    and _attention_supports_cpu_bias_streaming(layer)
                )
                if not stream_cpu_bias:
                    if bias_l.device != a.device:
                        bias_l = bias_l.to(device=a.device, dtype=torch.float32)
                    else:
                        bias_l = bias_l.float()
            else:
                bias_l = None

            if self.activation_checkpointing and self.training:
                a = torch.utils.checkpoint.checkpoint(
                    layer,
                    a,
                    s,
                    bias_l,
                    mask,
                    to_keys,
                    multiplicity,
                )
            else:
                a = layer(
                    a,
                    s,
                    bias_l,
                    mask,
                    to_keys,
                    multiplicity,
                )
        return a

    forward_with_dap_compat._boltz_dap_compat_patched = True
    DiffusionTransformer.forward = forward_with_dap_compat
    return True


def apply_template_t_chunk_size(
    model: torch.nn.Module, template_t_chunk_size: int | None
) -> None:
    """Set the template module's T-axis chunk size, if supported.

    Defined here (instead of imported from ``boltz.main``) so Boltz-DAP runs on an
    unmodified Boltz-2 install. On stock Boltz the template module has no
    ``template_t_chunk_size`` attribute, so this is a no-op; the chunking feature
    only takes effect on a Boltz build that supports it.
    """

    if template_t_chunk_size is None:
        return
    if not getattr(model, "use_templates", False):
        return
    tmpl = model.template_module
    if getattr(model, "is_template_compiled", False):
        tmpl = tmpl._orig_mod  # noqa: SLF001
    if hasattr(tmpl, "template_t_chunk_size"):
        tmpl.template_t_chunk_size = int(template_t_chunk_size)


# Backwards-compatible alias for the symbol previously imported from boltz.main.
_apply_template_t_chunk_size = apply_template_t_chunk_size


def apply_boltz_compat_patches() -> list[str]:
    """Apply Boltz-DAP compatibility patches and return patched component names."""

    patched = []
    attention_patched, attention_backend = _patch_diffusion_attention()
    if attention_patched:
        patched.append(f"AttentionPairBias.forward[sdpa:{attention_backend}]")
    if _patch_diffusion_module():
        patched.append("DiffusionModule.forward")
    if _patch_diffusion_transformer():
        patched.append("DiffusionTransformer.forward")
    return patched
