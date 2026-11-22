"""Check both triangle directions, masks, input dtypes, and a partial row tile."""

import torch
from esm.models.esmfold2.layers import TriangleMultiplicativeBlock
from triton.runtime.errors import OutOfResources

import blackwell_trimul as bw


def preflight(safe):
    # Odd length covers the final row tile and the padded contraction stride.
    rng = torch.Generator(device='cuda').manual_seed(42)
    z = torch.randn((1, 257, 257, 256), device='cuda', generator=rng)
    mask = (torch.rand((1, 257, 257), device='cuda', generator=rng) > 0.12).float()
    checks = []
    with torch.inference_mode(), torch.autocast('cuda', dtype=torch.bfloat16):
        for direction in ('outgoing', 'incoming'):
            with torch.random.fork_rng(devices=[torch.cuda.current_device()]):
                torch.manual_seed(42)
                eng = TriangleMultiplicativeBlock(256, 256, direction).cuda().eval()
            for dtype in (torch.float32, torch.bfloat16):
                pair = z.to(dtype)
                reference = eng(pair, mask).float()
                candidate = bw.trimul(eng, pair, mask, safe=safe).float()
                torch.cuda.synchronize()
                error = candidate - reference
                denom = reference.square().mean().sqrt().clamp_min(1e-8)
                rrms = float(error.square().mean().sqrt() / denom)
                maximum = float(error.abs().max())
                # These are bf16-fused kernels with different rounding locations
                # from the reference. Reject large operator differences before folding.
                if not torch.isfinite(candidate).all() or rrms > 0.05:
                    raise RuntimeError(f'TriMul preflight failed: {direction}, {dtype}, rrms={rrms}')
                check = dict(direction=direction, dtype=str(dtype), relative_rms_error=rrms, max_abs_error=maximum)
                print('TriMul preflight:', check, flush=True)
                checks.append(check)
    return checks


def select_tile():
    safe = bw.cells.safe_cfg('12.0')
    if safe is None:
        raise RuntimeError('Missing Blackwell portable tile configuration')
    try:
        checks = preflight(safe)
    except OutOfResources:
        safe = {name: dict(safe[name], BM=32, BN=32) for name in ('k1', 'k3')}
        safe['overrides'] = {}
        checks = preflight(safe)
    return safe, checks
