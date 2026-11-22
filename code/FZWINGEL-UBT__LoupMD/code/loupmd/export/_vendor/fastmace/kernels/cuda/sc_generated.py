# SPDX-License-Identifier: MIT
# Vendored from FastMACE 9b8012295267d3e162d22010ac7612618a0ca14f: kernels/cuda/sc_generated.py (fastmace/), trimmed to what LoupMD's
# exporters use by tools/release/vendor_fastmace.py. Do not edit: change FastMACE and vendor again.
"""A cuEquivariance symmetric contraction with the density division before it, as generated straight-line kernels
(results/sc0-bound-20261109: bound and lab; Codex report v3 proposal 5).

On the H200, cuEq's ``uniform_1d`` kernels for OMAT-0 medium's interaction 0 are FP32-issue bound and execute
1,381 / 2,935 FP32 instructions per (atom, channel) forward / backward. The polynomial itself has 480 distinct
(weight, monomial, output) terms over 410 monomials; cuEq rebuilds each monomial's product per term. The kernels here
are rendered from the module's own descriptor (``merged_terms``: the descriptor's paths with the same weight segment,
sorted monomial and output summed) and compiled with NVRTC, one block of ``mul`` threads per atom, ``ch =
threadIdx.x``, on cuEq's ir_mul layouts (x [n, segments * mul], weights [elements, weight segments * mul]):

- forward ``x = m * s`` with ``s = 1 / (D + 1)`` (the division fused); each degree-2 prefix's product, then its
  degree-3 monomials, each term added to its (weight, output) accumulator with the coefficient as an immediate;
  ``y_C = sum_a w_a t_aC``;
- backward: ``q_aC = w_a dy_C``; per monomial the adjoint ``h = sum coef q``; for a prefix ``p = x_i x_j`` each
  monomial (i, j, k) adds ``h p`` to ``dx_k`` and ``h x_k`` to the pair adjoint ``H``, then ``dx_i += H x_j``,
  ``dx_j += H x_i`` (repeated indices come out right); ``dm = dx s``, ``dD = -s sum(dx x)`` (a block reduction).

Rounding: another summation order than cuEq's (rms differences about 3e-7 relative), so a switch that uses it is
checked with the force/stress gate (decision 66).
"""

from __future__ import annotations

from collections import defaultdict

import torch


def merged_terms(polynomial):
    """``{(weight segment, sorted input segments, output segment): coefficient}`` of a cuEq ``SegmentedPolynomial``
    with inputs (weights, x) and one output, the paths with equal keys summed (x's operands are identical, so a
    monomial's permutations are one term)."""
    terms = defaultdict(float)
    for operation, stp in polynomial.operations:
        buffers = operation.buffers
        out_buffer = buffers[-1]
        for path in stp.paths:
            a, xs, c = None, [], None
            for buffer, index in zip(buffers, path.indices):
                if buffer == out_buffer and buffer >= polynomial.num_inputs:
                    c = index
                elif buffer == 0:
                    a = index
                else:
                    xs.append(index)
            coefficient = path.coefficients
            coefficient = float(coefficient.reshape(-1)[0]) if hasattr(coefficient, "reshape") else float(coefficient)
            terms[(a, tuple(sorted(xs)), c)] += coefficient
    return {key: value for key, value in terms.items() if value != 0.0}


def shape_of(module):
    """``(segments_in, segments_w, segments_out, mul)`` of a cuEq ``SymmetricContraction`` whose kernels can be
    generated, else None: float32, degree 1-3 in x, one multiplicity that is a multiple of 32 up to 1024, uniform
    segments of that size."""
    etp = getattr(module, "etp", None)
    polynomial = getattr(etp, "polynomial", etp)
    weight = getattr(module, "weight", None)
    if polynomial is None or not isinstance(weight, torch.Tensor) or weight.dtype != torch.float32:
        return None
    try:
        if polynomial.num_inputs != 2 or polynomial.num_outputs != 1:
            return None
        operands = list(polynomial.inputs) + list(polynomial.outputs)
        mul = int(weight.shape[-1])
        for operand in operands:
            if any(tuple(seg) != (mul,) for seg in operand.segments):
                return None
        for operation, stp in polynomial.operations:
            if len(operation.buffers) - 2 > 3:
                return None
    except (AttributeError, TypeError):
        return None
    if mul % 32 or not 32 <= mul <= 1024:
        return None
    return (len(operands[1].segments), len(operands[0].segments), len(operands[2].segments), mul)
