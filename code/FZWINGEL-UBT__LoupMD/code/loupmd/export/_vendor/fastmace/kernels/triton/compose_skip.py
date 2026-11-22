# SPDX-License-Identifier: MIT
# Vendored from FastMACE 9b8012295267d3e162d22010ac7612618a0ca14f: kernels/triton/compose_skip.py (fastmace/), trimmed to what LoupMD's
# exporters use by tools/release/vendor_fastmace.py. Do not edit: change FastMACE and vendor again.
"""Interaction 1's reassociated projection composed with its receiver-species skip (Codex H200 follow-up, item 1;
7 November 2026; ``results/h200-compose-quads-20261107``).

In a density interaction the first interaction's message per degree l is ``left_l @ right_l``
(``FirstInteractionReassociation``), through the linear's ``L_l`` (a per-l ``BlockLinear``, or the identity after
the generic fold), divided by ``density + 1`` and multiplied by the receiver's species matrix ``B_l,z``
(``SpeciesSkip``). The division is per row, so the products compose:
``(left_l right_l L_l / (d + 1)) B_l,z = left_l (right_l L_l B_l,z) / (d + 1)``. ``composed`` builds
``C_l [species, K, mul_out]`` (in float64, stored in the input's dtype) and the reassociation runs
``species_mm(left_l, C_l)``: one per-species product per l instead of the projection, the linear and the skip's
all-species product (3x the columns, forward and backward). The interaction then skips its linear and ``skip_tp``.

Not bitwise: the composed matrices round differently from the two products (a rounding-class change: force/stress
gate). Lab, H200, forward + backward at OMAT-0 medium's shapes: 0.960 -> 0.448 ms (species_mm's CUTLASS launch).

``COMPOSE_SKIP``: None: on for ``COMPOSE_SKIP_GPUS``; True / False: an A/B side's choice. Set at build
(``precision.route``) where the interaction qualifies (``generic.modules.compose_skip_products``).
"""

from __future__ import annotations

import torch


def composed(right, ws, linear=None, rotation=None):
    """``right [K, c] @ linear [c, mul_in] @ ws[z] [mul_in, mul_out]`` for every species z (``linear`` None: the
    identity), as ``(C [species, K, mul_out], C transposed [species, mul_out, K])``, both contiguous, computed in
    float64 and returned in ``right``'s dtype. ``rotation [species, K, K]`` (float64; ``rewrites.radial.nested``):
    ``C[z]`` is ``rotation[z] @ C[z]``, the nested radial basis's map composed in before the rounding."""
    left = right.double() if linear is None else right.double() @ linear.double()
    c = torch.matmul(left[None], ws.double())
    if rotation is not None:
        c = torch.matmul(rotation.to(device=c.device, dtype=torch.float64), c)
    c = c.to(right.dtype)
    return c.contiguous(), c.transpose(1, 2).contiguous()
