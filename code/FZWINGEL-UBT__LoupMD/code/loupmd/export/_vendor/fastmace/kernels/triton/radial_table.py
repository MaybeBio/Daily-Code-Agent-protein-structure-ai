# SPDX-License-Identifier: MIT
# Vendored from FastMACE 9b8012295267d3e162d22010ac7612618a0ca14f: kernels/triton/radial_table.py (fastmace/), trimmed to what LoupMD's
# exporters use by tools/release/vendor_fastmace.py. Do not edit: change FastMACE and vendor again.
"""Piecewise Chebyshev radial tables: edge length r -> the folded radial layer's input and the edge density.

``radial_tables`` (opt-6 OPT6-T05) replaces, per (sender species, receiver species) pair of a factored MH-1
interaction, the chain from the edge length to the folded last radial layer's input ``[h c, c]`` and to the
edge density ``tanh(density(r))^2 c`` by tables fitted at setup (``fastmace.rewrites.radial``). Every pair
shares one set of pieces; a piece holds a degree-``D`` Chebyshev series per output.

- **Lookup:** ``n_bins`` uniform bins over ``[r_lo, r_max)``, each inside exactly one piece (the pieces are a
  dyadic refinement of the bins' grid), give the piece of ``r`` in one gather: ``bins[(r - r_lo) * bin_scale]``.
  With ``x = (r - start) * scale - 1`` in ``[-1, 1]``, Clenshaw's recurrence sums the series.
- **Outside the domain:** ``r >= r_max`` (beyond the cutoff, also the engine's padded edges) gives exactly zero
  values and derivatives, as the cutoff does. ``r < r_lo`` is evaluated at ``r_lo`` with a zero derivative; the
  domain's lower end is set below any distance an MD run reaches (the fit's ``R_LO``).
- **Backward:** ``dL/dr = sum_j dL/dg_j g_j'(r)`` from the derivative series (``dcoef``, the Chebyshev
  derivative times the piece's ``scale``), recomputed: nothing is saved but ``r`` and the pair index.

Layouts: ``coef [P, K, D + 1, J]``, ``dcoef [P, K, D, J]``, ``starts``, ``scales [K]`` (all in the tables'
dtype: float32, or float64 for float64 plans, which then take float64 lengths), ``bins [n_bins]`` (int32);
``J = Q + 1``, the folded input's width ``Q`` and the edge density. On the CPU (and as the certification's
reference) ``evaluate`` runs the same recurrence in PyTorch.
"""

from __future__ import annotations

import torch


def evaluate(r, pair, coef, starts, scales, bins, r_lo, bin_scale, r_max, derivative=False):
    """PyTorch values ``[E, J]`` (or their r-derivatives, with ``dcoef`` as ``coef``) in ``coef``'s dtype."""
    r = r.reshape(-1).to(coef.dtype)
    inside = r < r_max
    clamped = torch.clamp(r, min=r_lo)
    index = torch.clamp(((clamped - r_lo) * bin_scale).to(torch.int64), 0, bins.shape[0] - 1)
    piece = bins[index].to(torch.int64)
    x = (clamped - starts[piece]) * scales[piece] - 1.0
    series = coef[pair.to(torch.int64), piece]  # [E, terms, J]
    b1 = torch.zeros_like(series[:, 0])
    b2 = torch.zeros_like(b1)
    for k in range(series.shape[1] - 1, 0, -1):
        b1, b2 = series[:, k] + 2.0 * x[:, None] * b1 - b2, b1
    values = series[:, 0] + x[:, None] * b1 - b2
    keep = inside if not derivative else inside & (r >= r_lo)
    return torch.where(keep[:, None], values, torch.zeros_like(values))
