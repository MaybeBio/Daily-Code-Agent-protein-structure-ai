"""Memory bounded, single-input adapter for the Blackwell kit's TriMul kernels."""

from collections import Counter
from types import MethodType

import torch
import triton
from esm.models.esmfold2.layers import TriangleMultiplicativeBlock
from opt_core.kernels.fpf_trimul_v4 import cells, generic, kernels


def supported(engine, pair):
    return (pair.is_cuda and pair.ndim == 4 and pair.shape[0] == 1
            and pair.shape[1] == pair.shape[2] and pair.is_contiguous()
            and pair.dtype in (torch.float32, torch.bfloat16)
            and engine.input_channels in kernels.SUPPORTED_C
            and engine.latent_channels in kernels.SUPPORTED_D)


def trimul(engine, pair, mask, *, row_block=128, safe=None):
    if not supported(engine, pair):
        raise ValueError(f'unsupported TriMul input {pair.shape}, {pair.dtype}')
    safe = cells.safe_cfg('12.0') if safe is None else safe
    if safe is None:
        raise RuntimeError('Blackwell kit has no portable tile for SM120')
    c, d, n = engine.input_channels, engine.latent_channels, pair.shape[1]
    k1, k3 = kernels.resolve_cfg(safe, c, d, False)
    if k1.get('impl', 'ptr') != 'ptr' or k3.get('impl', 'ptr') != 'ptr':
        raise RuntimeError('The row-block adapter requires the pointer kernels')
    w = generic.pack_weights(ln_in_w=engine.norm_start.weight, ln_in_b=engine.norm_start.bias,
                             ln_out_w=engine.norm_mix.weight, ln_out_b=engine.norm_mix.bias,
                             w_proj=engine.proj_bundle.weight, proj_split=('ap', 'bp', 'ag', 'bg'),
                             w_o=engine.proj_emit.weight, w_og=engine.proj_gate.weight,
                             cache_owner=engine)
    n_pad = kernels.ceil_to(n, 16)
    ab = torch.empty((2, 1, d, n_pad, n_pad), dtype=torch.bfloat16, device=pair.device)
    mask = None if mask is None else mask.float().contiguous()
    outgoing = engine.flow == 'outgoing'
    eps = engine.norm_start.eps
    transposed = kernels.launch_k1(pair, w, mask, ab, n, n_pad, k1, eps,
                                    kernels.MASK_SHARED, outgoing, k3)
    if transposed:
        raise RuntimeError('The pointer prologue must write untransposed planes')
    left, right = ab[0, 0], ab[1, 0]
    if outgoing:
        right = right.transpose(-1, -2)
    else:
        left = left.transpose(-1, -2)
    output = torch.empty_like(pair)
    # K3 sees a local row index and the original column stride. Batch=1 is
    # required: the row slice starts at a different address for each batch.
    with torch.autocast('cuda', enabled=False):
        for i in range(0, n, row_block):
            end = min(i + row_block, n)
            x = torch.bmm(left[:, i:end], right)
            grid = (triton.cdiv(n, k3['BM']), end - i, 1)
            kernels._k3c[grid](x, pair[:, i:end], w['ln_out_w'], w['ln_out_b'],
                               w['ln_in_w'], w['ln_in_b'], w['wz'], w['wg_out'],
                               w['ln_in_w'], w['ln_in_w'], output[:, i:end],
                               n, n_pad, (end - i) * n_pad, eps, n * n,
                               C=c, CH=d, BM=k3['BM'], BN=k3['BN'], RESIDUAL=False,
                               STOCK_ROUND=True, HAS_BIAS=False, IN_F32=pair.dtype == torch.float32,
                               num_warps=k3['num_warps'], num_stages=k3['num_stages'])
    return output


def enable(model, safe, row_block=128):
    counts = Counter()
    disabled = set()

    def replace(engine, fallback, name):
        def forward(self, pair, visibility=None):
            if name not in disabled and supported(self, pair):
                try:
                    output = trimul(self, pair, visibility, row_block=row_block, safe=safe)
                except torch.cuda.OutOfMemoryError:
                    disabled.add(name)
                    print(f'Blackwell TriMul OOM in {name}; reverting to baseline tiling for this module', flush=True)
                else:
                    counts['blackwell'] += 1
                    return output
                # Release the exception traceback and its tensor references first.
                torch.cuda.empty_cache()
            counts['baseline'] += 1
            return fallback(pair, visibility)
        engine.forward = MethodType(forward, engine)

    modules = [(name, module) for name, module in model.named_modules()
               if isinstance(module, TriangleMultiplicativeBlock)]
    for name, module in modules:
        replace(module, module.forward, name)
    return modules, counts, disabled
