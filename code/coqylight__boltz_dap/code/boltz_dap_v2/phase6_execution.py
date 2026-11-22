from __future__ import annotations

import os
from types import MethodType

import torch

from dap_diffusion_sampling import run_sharded_preconditioned_network_forward


EXECUTION_MODES = ("legacy_dap", "candidate_sharded_fp32")
INFERENCE_PRECISIONS = ("32-true", "bf16-mixed")


def validate_trunk_acceleration(*, precision: str, no_kernels: bool, execution_mode: str) -> dict[str, object]:
    switches = {}
    for name in ("BOLTZ_DAP_FUSED_TRI_ATT", "BOLTZ_TRIMUL_IN_OVERLAP_ONLY"):
        value = os.environ.get(name, "0")
        if value not in ("0", "1"):
            raise ValueError(f"{name} must be 0 or 1")
        switches[name] = value == "1"
    reuse_group = int(os.environ.get("BOLTZ_TRIMUL_IN_REUSE_GROUP", "1"))
    if not 1 <= reuse_group <= 8:
        raise ValueError("BOLTZ_TRIMUL_IN_REUSE_GROUP must be between 1 and 8")
    fused = switches["BOLTZ_DAP_FUSED_TRI_ATT"]
    if fused and (precision != "bf16-mixed" or no_kernels or execution_mode != "candidate_sharded_fp32"):
        raise ValueError("Fused DAP attention requires bf16-mixed, candidate_sharded_fp32 and enabled kernels")
    return {"fused_triangle_attention": fused, "fused_triangle_query_tile": 1024 if fused else None,
            "trimul_in_overlap_only": switches["BOLTZ_TRIMUL_IN_OVERLAP_ONLY"],
            "trimul_in_reuse_group": reuse_group}


def inference_precision_context(precision: str, device_type: str = "cuda"):
    if precision not in INFERENCE_PRECISIONS:
        raise ValueError(f"unsupported inference precision: {precision}")
    return torch.autocast(
        device_type=device_type,
        dtype=torch.bfloat16,
        enabled=precision == "bf16-mixed",
    )


def configure_phase6_execution(
    model: torch.nn.Module,
    *,
    execution_mode: str,
    diffusion_samples: int,
    token_query_rows: int,
    atom_window_rows: int,
    precision: str = "32-true",
) -> dict[str, object]:
    if execution_mode not in EXECUTION_MODES:
        raise ValueError(f"unsupported execution mode: {execution_mode}")
    cache_switch = os.environ.get("BOLTZ_DIFFUSION_CACHED_TOKEN_ATTENTION", "0")
    if cache_switch not in ("0", "1"):
        raise ValueError("BOLTZ_DIFFUSION_CACHED_TOKEN_ATTENTION must be 0 or 1")
    cached_attention = cache_switch == "1"
    if cached_attention and (execution_mode != "candidate_sharded_fp32"
                             or precision not in INFERENCE_PRECISIONS
                             or os.environ.get("BOLTZ_DIFFUSION_BIAS_LAYOUT") != "layerwise"):
        raise ValueError("Cached token attention requires candidate execution, explicit precision and layerwise bias")
    if execution_mode == "legacy_dap":
        return {
            "execution_mode": execution_mode,
            "candidate_score_selected": False,
            "confidence_transport": "legacy_default",
            "stock_eval_rng_schedule": False,
        }
    if diffusion_samples != 1:
        raise ValueError(
            "candidate_sharded_fp32 currently requires one diffusion sample"
        )
    if token_query_rows <= 0 or atom_window_rows <= 0:
        raise ValueError("candidate shard extents must be positive")

    projection_reuse = {}
    for kind in ("token", "atom"):
        name = f"BOLTZ_DIFFUSION_REUSE_{kind.upper()}_PROJECTIONS"
        value = os.environ.get(name, "0")
        if value not in ("0", "1"):
            raise ValueError(f"{name} must be 0 or 1")
        projection_reuse[f"reuse_{kind}_projections"] = value == "1"

    for name, field in (("BOLTZ_DIFFUSION_STREAM_TOKEN_BIAS", "stream_token_bias"),
                        ("BOLTZ_DIFFUSION_DETERMINISTIC_POOLING", "deterministic_pooling")):
        value = os.environ.get(name, "0")
        if value not in ("0", "1"):
            raise ValueError(f"{name} must be 0 or 1")
        projection_reuse[field] = value == "1"

    if cached_attention:
        model._dap_cached_diffusion_config = {
            "projection_precision": precision, "query_rows": token_query_rows,
        }
    elif hasattr(model, "_dap_cached_diffusion_config"):
        del model._dap_cached_diffusion_config
    structure_module = model.structure_module

    def candidate_preconditioned(
        self,
        noised_atom_coords,
        sigma,
        network_condition_kwargs,
    ):
        return run_sharded_preconditioned_network_forward(
            self,
            noised_atom_coords,
            sigma,
            network_condition_kwargs,
            token_query_rows=token_query_rows,
            atom_window_rows=atom_window_rows,
        )

    structure_module.preconditioned_network_forward = MethodType(
        candidate_preconditioned,
        structure_module,
    )
    return {
        "execution_mode": execution_mode,
        "candidate_score_selected": True,
        "confidence_transport": "fp32",
        "stock_eval_rng_schedule": True,
        "token_query_rows": token_query_rows,
        "atom_window_rows": atom_window_rows,
        "cached_token_attention": cached_attention,
        "cache_projection_precision": precision if cached_attention else None,
        **projection_reuse,
    }