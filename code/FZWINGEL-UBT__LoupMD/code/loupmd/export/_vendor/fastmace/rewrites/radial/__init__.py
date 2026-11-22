# SPDX-License-Identifier: MIT
# Vendored from FastMACE 9b8012295267d3e162d22010ac7612618a0ca14f: rewrites/radial/__init__.py (fastmace/), trimmed to what LoupMD's
# exporters use by tools/release/vendor_fastmace.py. Do not edit: change FastMACE and vendor again.
"""``radial_tables`` (opt-6 OPT6-T05): certified per-species-pair Chebyshev tables for MH-1's radial chain.

In a factored, cutoff-folded MH-1 interaction, for a fixed (sender, receiver) species pair, everything from the
edge length ``r`` to the folded last radial layer's input ``[h c, c]`` and to the edge density
``tanh(density(r))^2 c`` is a function of ``r`` alone: the Bessel basis and Agnesi transform of the radial
embedding, the projected species embeddings, the first layers, the hidden LayerNorm/SiLU layers and the
cutoff. The record replaces that chain by piecewise Chebyshev tables (``fastmace.kernels.triton.radial_table``):

- **Fit (apply):** per interaction and ordered pair of the structure's species superset, in float64 on the CPU
  from copies of the model's own modules (the weights are the model's float32 weights). Degree ``DEGREE``
  pieces, a dyadic refinement of ``INITIAL_PIECES`` uniform pieces over ``[R_LO, r_max)``, shared by all pairs,
  split until every output's interpolation error at ``2 * DEGREE + 3`` test points is below ``TOLERANCE`` of its
  largest value on the piece (with a floor of ``FLOOR`` of its largest value on the domain).
- **Certificate (apply, held by the self-check):** on a dense grid the float32 table and the model's own float32
  radial chain are both compared with the float64 chain, at the per-edge tensor-product weights
  ``w = [h c, c] @ [W, b]^T``, their r-derivatives, the edge density and its r-derivative, each normalised per
  output, over the whole domain and over ``[R_PHYSICAL, r_max)``. The certificate's ratio is the table's error
  over the network's; the self-check fails, and rule 13 turns the record off, if any ratio exceeds 1.
- **Cache:** the fitted tables and their certificate are stored under ``FASTMACE_CACHE/radial-tables`` by
  ``cache_key`` (the model's state, the species set, dtype, ``r_max``, the constants and this module's source) and
  reused by later builds; the self-check still runs on cached tables, so a bad entry turns the record off.
- **Model:** the record sets each interaction's ``radial_table`` and replaces ``model.radial_embedding`` by
  ``LengthsEmbedding``, which hands the interactions the edge lengths ``[E, 1]`` and no cutoff. The folded forward
  takes the table path when its ``edge_feats`` have width 1 and the network path otherwise (the other records'
  self-checks feed random radial features).

Exactness class ``certified`` (SPEC §6.1, owner decision 61): float32 plans only; the planner refuses it in
float64 plans, whose rounding the certificate does not bound. Deterministic: no atomics.
"""

from __future__ import annotations

import copy

R_LO = 0.3  # Å: the domain's lower end, below any distance MD reaches; shorter edges are evaluated here

R_PHYSICAL = 1.0  # Å: the certificate's second region, where every MD edge lies

# Degree 5 (owner, 4 November 2026; degree 10 before): fewer terms per edge in the table forward, its backward and
# wprime's slope, more pieces at the same tolerance and certificate. MD step against degree 10: OMAT-0 medium on
# Benchmark_loup 0.903 / 0.905 (A100-SXM4-80GB), 0.908 (RTX 4000 Ada), 0.935 (RTX 5060 Ti); MH-1 on the Ada neutral
# (NaCl 0.978, NaNbO3 and NbCl5 within 0.6 %); results/omat0-kernel-lab-20261103.
DEGREE = 5

INITIAL_PIECES = 8

MAX_DEPTH = 9  # bins: INITIAL_PIECES * 2**MAX_DEPTH, so that every piece boundary is a bin boundary

TOLERANCE = 1e-7

FLOOR = 1e-6

# Float64 tables (float64 plans; owner request, 27 October 2026): the same fit held to float64 rounding.
DEGREE_64 = 16

TOLERANCE_64 = 3e-13  # MH-1 NaCl, NbCl5: certificate <= 0.52 (1e-12 failed at 1.25-1.96)

FLOOR_64 = 1e-1  # with TOLERANCE_64: within 3e-14 of each output's largest value on the domain

# Their certificate: the largest error, per output scale, over this bound (about 5,000 float64 ulps). The float32
# certificate's yardstick, the network's own rounding error, is zero when the float64 network is the reference.
CERTIFY_BOUND_64 = 1e-12

# Their domain's lower end: exact in float32, as Triton passes the kernels' scalar bounds in float32 (0.3 rounds
# up, and an edge at exactly 0.3 Å then reads as below the domain, with a zero slope).
R_LO_64 = 0.25

CERTIFY_POINTS = 6000  # uniform and as many random lengths; the w-level tensors are [12000, 1280] float64


def power_basis(coef):
    """``coef [P, K, T, J]`` (Chebyshev coefficients in x along axis 2) in the power basis of x: float64 from the
    stored values, returned in ``coef``'s dtype."""
    import numpy as np
    import torch

    terms = coef.shape[2]
    basis = np.zeros((terms, terms))  # column k: T_k in the power basis
    for k in range(terms):
        unit = np.zeros(terms)
        unit[k] = 1.0
        power = np.polynomial.chebyshev.cheb2poly(unit)
        basis[: power.size, k] = power
    m = torch.as_tensor(basis, dtype=torch.float64, device=coef.device)
    return torch.einsum("tk,pkj->ptj", m, coef.to(torch.float64).reshape(-1, terms, coef.shape[3])).reshape(
        coef.shape).to(coef.dtype).contiguous() if coef.numel() else coef.clone()


def _nodes(count, dtype):
    import torch

    k = torch.arange(count, dtype=dtype)
    return torch.cos(torch.pi * (k + 0.5) / count)


def _coefficients(values):
    """Chebyshev coefficients ``[..., T, J]`` of values at the ``T`` Chebyshev nodes (axis -2)."""
    import torch

    count = values.shape[-2]
    k = torch.arange(count, dtype=values.dtype)
    basis = torch.cos(torch.pi * torch.outer(k, k + 0.5) / count) * (2.0 / count)  # [term, node]
    basis[0] /= 2.0
    return torch.einsum("tn,...nj->...tj", basis, values)


def _series(coef, x):
    """Clenshaw sum of ``coef [..., T, J]`` at ``x [..., M]``: ``[..., M, J]``."""
    import torch

    b1 = torch.zeros((*x.shape, coef.shape[-1]), dtype=coef.dtype)
    b2 = torch.zeros_like(b1)
    for k in range(coef.shape[-2] - 1, 0, -1):
        b1, b2 = coef[..., k:k + 1, :] + 2.0 * x[..., None] * b1 - b2, b1
    return coef[..., 0:1, :] + x[..., None] * b1 - b2


def _truth(chain, pairs, r, derivative=False):
    """``[P, n, J]`` values of ``chain`` (and their r-derivatives, with ``derivative``) for every pair."""
    import torch

    with torch.no_grad():
        if not derivative:
            return torch.stack([chain(r, s, t) for s, t in pairs])
        both = [chain.with_derivative(r, s, t) for s, t in pairs]
        return torch.stack([v for v, _ in both]), torch.stack([d for _, d in both])


def fit(chain, pairs, r_max, table_dtype=None):
    """The tables of ``chain`` for ``pairs`` (float64 fit; float32 tables, or float64 ones with
    ``table_dtype=torch.float64``): a dict of tensors and constants.

    A piece is split until both its values and its r-derivatives (the derivative series) are within
    ``TOLERANCE`` (float64 tables: ``TOLERANCE_64``) of the local largest value or derivative at the test points."""
    import numpy as np
    import torch

    dtype = torch.float64
    table_dtype = torch.float32 if table_dtype is None else table_dtype
    wide = table_dtype == torch.float64
    degree, tolerance, floor_factor = (DEGREE_64, TOLERANCE_64, FLOOR_64) if wide else (DEGREE, TOLERANCE, FLOOR)
    terms = degree + 1
    r_lo = R_LO_64 if wide else R_LO
    domain = torch.linspace(r_lo, r_max, 4097, dtype=dtype)[:-1]
    values, slopes = _truth(chain, pairs, domain, derivative=True)
    floor = floor_factor * values.abs().amax(dim=1, keepdim=True)  # [P, 1, J]
    dfloor = floor_factor * slopes.abs().amax(dim=1, keepdim=True)
    nodes, tests = _nodes(terms, dtype), torch.linspace(-1.0, 1.0, 2 * terms + 1, dtype=dtype)
    points = torch.cat([nodes, tests])
    unit = (r_max - r_lo) / INITIAL_PIECES
    pending = [(r_lo + i * unit, r_lo + (i + 1) * unit, 0) for i in range(INITIAL_PIECES)]
    accepted, worst = [], 0.0
    while pending:
        starts = torch.tensor([a for a, _, _ in pending], dtype=dtype)
        widths = torch.tensor([b - a for a, b, _ in pending], dtype=dtype)
        r = (starts[:, None] + (points[None, :] + 1.0) * widths[:, None] / 2.0).reshape(-1)
        values, slopes = _truth(chain, pairs, r, derivative=True)
        shape = (len(pairs), len(pending), len(points), -1)
        values, slopes = values.reshape(shape), slopes.reshape(shape)  # [P, pieces, points, J]
        coef = _coefficients(values[:, :, :terms])
        if wide:  # float64: the derivative series from the exact derivatives, as differentiating the value series
            dcoef = _coefficients(slopes[:, :, :terms])  # amplifies its rounding by ~degree^2 / width (f64-T01)
        else:
            dcoef = torch.from_numpy(np.polynomial.chebyshev.chebder(coef.numpy(), axis=2)) * (
                2.0 / widths)[None, :, None, None]
        x = tests.expand(len(pairs), len(pending), -1)
        error = (_series(coef, x) - values[:, :, terms:]).abs() / torch.maximum(
            values.abs().amax(dim=2, keepdim=True), floor[:, None])
        derror = (_series(dcoef, x) - slopes[:, :, terms:]).abs() / torch.maximum(
            slopes.abs().amax(dim=2, keepdim=True), dfloor[:, None])
        # An output (or its derivative) that is zero on the whole domain has nothing to fit: a residual block's
        # density column, a constant cutoff column when the embedding applies the cutoff itself (generic tables).
        # Without this, 0/0 and x/0 would decide the split.
        error = torch.where(floor[:, None] > 0, error, torch.zeros_like(error))
        derror = torch.where(dfloor[:, None] > 0, derror, torch.zeros_like(derror))
        relative = torch.maximum(error.amax(dim=(0, 2, 3)), derror.amax(dim=(0, 2, 3)))  # per piece
        following = []
        for (a, b, level), err, piece_coef, piece_dcoef in zip(pending, relative.tolist(), coef.unbind(1),
                                                               dcoef.unbind(1)):
            if err > tolerance and level < MAX_DEPTH:
                middle = 0.5 * (a + b)
                following += [(a, middle, level + 1), (middle, b, level + 1)]
            else:
                accepted.append((a, b, piece_coef, piece_dcoef))
                worst = max(worst, err)
        pending = following
    accepted.sort(key=lambda item: item[0])
    coef = torch.stack([c for _, _, c, _ in accepted], dim=1)  # [P, K, T, J]
    scales = torch.tensor([2.0 / (b - a) for a, b, _, _ in accepted], dtype=dtype)
    if wide:
        dcoef = torch.stack([d for _, _, _, d in accepted], dim=1)
    else:
        dcoef = torch.from_numpy(np.polynomial.chebyshev.chebder(coef.numpy(), axis=2)) * scales[None, :, None, None]
    starts = torch.tensor([a for a, _, _, _ in accepted], dtype=dtype)
    n_bins = INITIAL_PIECES * 2 ** MAX_DEPTH
    centres = r_lo + (torch.arange(n_bins, dtype=dtype) + 0.5) * (r_max - r_lo) / n_bins
    bins = (torch.searchsorted(starts, centres, right=True) - 1).to(torch.int32)
    return dict(coef=coef.to(table_dtype).contiguous(), dcoef=dcoef.to(table_dtype).contiguous(),
                starts=starts.to(table_dtype), scales=scales.to(table_dtype), bins=bins,
                r_lo=float(r_lo), bin_scale=float(n_bins / (r_max - r_lo)), r_max=float(r_max), fit_error=worst)


def _table_values(table, r, pair):
    """``(values, r-derivatives)`` ``[n, J]`` of the float32 table, by the arithmetic that will run: the Triton
    kernels on CUDA (the derivatives column by column through the backward with one-hot gradients), else
    ``radial_table.evaluate``."""
    import torch

    from loupmd.export._vendor.fastmace.kernels.triton.radial_table import evaluate
    radial_table_backward = radial_table_forward = None  # not vendored: a path the exporters do not take

    args = (table.starts, table.scales, table.bins)
    constants = (table.r_lo, table.bin_scale, table.r_max)
    if not r.is_cuda:
        return (evaluate(r, pair, table.coef, *args, *constants),
                evaluate(r, pair, table.dcoef, *args, *constants, derivative=True))
    g, density = radial_table_forward(r, pair, table.coef, *args, *constants)
    width = table.coef.shape[-1]
    slopes = []
    for column in range(width):
        grad_g = torch.zeros_like(g)
        grad_density = torch.zeros_like(density)
        if column < width - 1:
            grad_g[:, column] = 1.0
        else:
            grad_density[:, 0] = 1.0
        slopes.append(radial_table_backward(r, pair, table.dcoef, *args, grad_g, grad_density, *constants).reshape(-1))
    return torch.cat([g, density], dim=1), torch.stack(slopes, dim=1)


def certify(table, chain64, chain32, pairs, r_max, seed=0):
    """Per pair, the float32 table's error over the float32 chain's, both against the float64 chain (module
    docstring). Returns ``{"worst": ratio, "pairs": {"s-t": ratio}, ...}`` (superset indices)."""
    import torch

    generator = torch.Generator().manual_seed(seed)
    r_lo = table.r_lo
    r64 = torch.cat([torch.linspace(r_lo, r_max, CERTIFY_POINTS + 1, dtype=torch.float64)[:-1],
                     r_lo + (r_max - r_lo) * torch.rand(CERTIFY_POINTS, generator=generator, dtype=torch.float64)])
    r64 = r64.to(table.coef.dtype).to(torch.float64)  # the lengths the GPU sees (float32 for float32 tables)
    physical = r64 >= R_PHYSICAL
    folded64 = chain64.folded
    r32 = r64.to(device=table.coef.device, dtype=table.coef.dtype)
    wide = table.coef.dtype == torch.float64
    out, worst, largest = {}, 0.0, 0.0

    def to_w(g):
        g = g.detach().to(torch.float64).cpu()
        return torch.cat([g[:, :-1] @ folded64.T, g[:, -1:]], dim=1)  # [n, Q + 1]: w and the density

    for index, (s, t) in enumerate(pairs):
        truth, dtruth = chain64.with_derivative(r64, s, t)
        net, dnet = chain32.with_derivative(r32, s, t)
        pair = torch.full(r32.shape, index, dtype=torch.int32, device=r32.device)
        tab, dtab = _table_values(table, r32, pair)
        ratios = []
        for exact, network, tabled in ((truth, net, tab), (dtruth, dnet, dtab)):
            exact, network, tabled = to_w(exact), to_w(network), to_w(tabled)
            for region in (slice(None), physical):
                e = exact[region]
                scale = e.abs().amax(dim=0).clamp_min(1e-300)
                net_error = (network[region] - e).abs() / scale
                tab_error = (tabled[region] - e).abs() / scale
                for columns in (slice(0, -1), slice(-1, None)):  # w, then the density
                    err_net, err_tab = net_error[:, columns].max().item(), tab_error[:, columns].max().item()
                    largest = max(largest, err_tab)
                    if wide:  # the float64 network is the reference itself: a fixed bound instead (f64-T01)
                        ratios.append(err_tab / CERTIFY_BOUND_64)
                    else:
                        ratios.append(0.0 if err_tab == 0.0 else (err_tab / err_net if err_net > 0 else float("inf")))
        out[f"{s}-{t}"] = max(ratios)
        worst = max(worst, out[f"{s}-{t}"])
    return {"worst": worst, "pairs": out, "points": int(r64.numel()), "r": [r_lo, r_max],
            "physical_from": R_PHYSICAL, "largest_error": largest,
            "bound": "CERTIFY_BOUND_64 of each output's scale" if wide else "the float32 network's error"}


def _radial_net(interaction):
    """The interaction's radial network (MACE-OFF's stock block keeps it as ``radial_original`` once tabled)."""
    original = getattr(interaction, "radial_original", None)
    return original if original is not None else interaction.conv_tp_weights


class _GenericChain:
    """One generic interaction's radial chain ``r -> [h c, c, density]`` (``c`` the cutoff, 1 when the embedding
    applies it itself; the density column 0 for a residual block), per species pair, in one dtype and device.

    ``radial`` is the radial embedding (default ``model.radial_embedding``); the hidden layers are a copy of the
    split network's (``generic_fused_radial_backward``'s ``radial_hidden``), so forward-mode derivatives exist."""

    def __init__(self, model, interaction, columns, dtype, device, radial=None):
        import torch

        from loupmd.export._vendor.fastmace.rewrites.generic import modules as gm

        self.dtype, self.device = dtype, device
        self.elements = len(model.atomic_numbers)
        self.atomic_numbers = model.atomic_numbers.to(device)
        self.columns = list(columns)
        self.radial = copy.deepcopy(radial if radial is not None else model.radial_embedding).to(
            device=device, dtype=dtype)
        hidden, last = gm.fc_split(_radial_net(interaction))
        self.hidden = copy.deepcopy(hidden).to(device=device, dtype=dtype)
        kind = gm.GENERIC_INTERACTIONS.get(type(interaction).__name__, ("stock",))[0]
        self.density = (copy.deepcopy(interaction.density_fn).to(device=device, dtype=dtype)
                        if kind not in ("residual", "stock") else None)
        weight = gm.fc_last_weight(last).detach().to(device=device, dtype=dtype)
        self.folded = torch.cat([weight, weight.new_zeros(weight.shape[0], 1)], dim=1)  # [W, 0]: (h W) c

    def __call__(self, r, sender, receiver):
        """``[n, Q_in + 2]``: ``[h c, c]`` and the edge density for edges ``sender -> receiver`` (superset indices)
        of lengths ``r`` (``[n]``)."""
        import torch

        n = r.shape[0]
        node_attrs = torch.zeros((2, self.elements), dtype=self.dtype, device=self.device)
        node_attrs[0, self.columns[sender]] = 1
        node_attrs[1, self.columns[receiver]] = 1
        edge_index = torch.stack([torch.zeros(n, dtype=torch.long, device=self.device),
                                  torch.ones(n, dtype=torch.long, device=self.device)])
        out = self.radial(r[:, None], node_attrs, edge_index, self.atomic_numbers)
        feats, cutoff = out if isinstance(out, tuple) else (out, None)
        cutoff = torch.ones_like(r[:, None]) if cutoff is None else cutoff
        hidden = self.hidden(feats)
        density = (torch.tanh(self.density(feats) ** 2) * cutoff if self.density is not None
                   else torch.zeros_like(cutoff))
        return torch.cat([hidden * cutoff, cutoff, density], dim=1)

    def with_derivative(self, r, sender, receiver):
        import torch

        return torch.func.jvp(lambda x: self(x, sender, receiver), (r,), (torch.ones_like(r),))
