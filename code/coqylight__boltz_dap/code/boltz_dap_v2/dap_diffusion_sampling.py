from __future__ import annotations

import torch

from dap_diffusion_score import run_sharded_diffusion_score


def run_sharded_preconditioned_network_forward(
    structure_module: torch.nn.Module,
    noised_atom_coords: torch.Tensor,
    sigma: torch.Tensor | float,
    network_condition_kwargs: dict,
    *,
    token_query_rows: int,
    atom_window_rows: int,
) -> torch.Tensor:
    """Apply stock preconditioning around one sharded FP32 score call."""
    batch_size = noised_atom_coords.shape[0]
    if isinstance(sigma, float):
        sigma = torch.full(
            (batch_size,),
            sigma,
            dtype=noised_atom_coords.dtype,
            device=noised_atom_coords.device,
        )
    padded_sigma = sigma.reshape(batch_size, 1, 1)
    multiplicity = int(network_condition_kwargs.get("multiplicity", batch_size))
    if multiplicity != 1 or batch_size != 1:
        raise ValueError("Phase 4 sampling reference currently requires multiplicity 1")
    score_update = run_sharded_diffusion_score(
        structure_module.score_model,
        s_inputs=network_condition_kwargs["s_inputs"],
        s_trunk=network_condition_kwargs["s_trunk"],
        r_noisy=structure_module.c_in(padded_sigma) * noised_atom_coords,
        times=structure_module.c_noise(sigma),
        feats=network_condition_kwargs["feats"],
        diffusion_conditioning=network_condition_kwargs["diffusion_conditioning"],
        token_query_rows=token_query_rows,
        atom_window_rows=atom_window_rows,
    )
    return (
        structure_module.c_skip(padded_sigma) * noised_atom_coords
        + structure_module.c_out(padded_sigma) * score_update
    )