from types import MethodType

import torch
from esm.models.esmfold2.layers import TriangleMultiplicativeBlock


def enable_row_tiling(model, tile_rows=64):
    def tiled(engine, pair_grid, visibility=None):
        batch, length, other_length, channels = pair_grid.shape
        if length <= tile_rows:
            return TriangleMultiplicativeBlock.forward(engine, pair_grid, visibility)
        hidden = engine.latent_channels
        stream_shape = (batch, length, other_length, hidden)
        left = pair_grid.new_empty(stream_shape, dtype=torch.float32)
        right = pair_grid.new_empty(stream_shape, dtype=torch.float32)
        for start in range(0, length, tile_rows):
            end = min(start + tile_rows, length)
            bundle = engine.proj_bundle(engine.norm_start(pair_grid[:, start:end]))
            signal, gate = bundle.split(2 * hidden, dim=-1)
            routed = signal * torch.sigmoid(gate)
            if visibility is not None:
                routed = routed * visibility[:, start:end].unsqueeze(-1)
            left_tile, right_tile = routed.chunk(2, dim=-1)
            left[:, start:end].copy_(left_tile)
            right[:, start:end].copy_(right_tile)
        del bundle, signal, gate, routed, left_tile, right_tile
        output = None
        for start in range(0, length, tile_rows):
            end = min(start + tile_rows, length)
            selected = left[:, start:end] if engine.flow == 'outgoing' else left[:, :, start:end]
            contracted = torch.einsum(engine._einsum_equation, selected, right)
            mixed = engine.proj_emit(engine.norm_mix(contracted))
            output_gate = torch.sigmoid(engine.proj_gate(engine.norm_start(pair_grid[:, start:end])))
            product = mixed * output_gate
            if output is None:
                output = product.new_empty((batch, length, other_length, channels))
            output[:, start:end].copy_(product)
        return output

    count = 0
    for module in model.modules():
        if isinstance(module, TriangleMultiplicativeBlock):
            module.forward = MethodType(tiled, module)
            count += 1
    if not count:
        raise RuntimeError('No triangle blocks found in ESMFold2')
    return count


def enable_esmc_offload(model):
    model.esmc.to('cpu')
    compute = model._compute_lm_hidden_states

    def embed_then_offload(*inputs, **kwargs):
        model.esmc.to('cuda')
        try:
            return compute(*inputs, **kwargs)
        finally:
            model.esmc.to('cpu')
            torch.cuda.empty_cache()

    model._compute_lm_hidden_states = embed_then_offload
