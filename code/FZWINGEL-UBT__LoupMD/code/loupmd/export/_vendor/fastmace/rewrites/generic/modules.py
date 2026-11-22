# SPDX-License-Identifier: MIT
# Vendored from FastMACE 9b8012295267d3e162d22010ac7612618a0ca14f: rewrites/generic/modules.py (fastmace/), trimmed to what LoupMD's
# exporters use by tools/release/vendor_fastmace.py. Do not edit: change FastMACE and vendor again.
"""Modules and forward of the generic family: MACE-MP-0, the density family and MACE-OFF's later blocks.

``generic_interaction_forward`` reproduces the mace-torch 0.3.16 forward of every class in
``GENERIC_INTERACTIONS`` (its source is pinned by sha256) and reads the attributes the generic
records set on an interaction:

- ``first_reassociation`` (``generic_reassociate``): the first interaction summed per receiver
  and sender species before its last radial layer;
- ``fused_radial_backward`` (``generic_fused_radial_backward``): the last radial layer as
  ``hidden @ W.T`` through ``folded_linear``, whose Triton input gradient replaces cuBLAS's;
- ``streaming_kernels`` (``generic_streaming``): the receiver-streaming OEq convolution;
- ``chunked_backward_edges`` and ``generic_folded`` (``generic_chunked_conv_backward``): the streaming convolution
  takes the last radial layer's input ``[h c, c]`` and its weight ``[W, 0]`` (MH-1's folded layer,
  ``GenericFoldedRadial``), so its backward runs in L2-sized edge chunks and the ``[E, W]`` weight gradient is
  never formed in full;
- ``skip_tp`` replaced by a ``SpeciesSkip`` (``generic_species_skip``), which needs no change of
  the forward;
- ``radial_table`` (``generic_radial_tables``, fastmace.rewrites.radial): with edge lengths ``[E, 1]`` as
  ``edge_feats`` (the record's ``LengthsEmbedding``), the certified table gives ``[h c, c]`` and the edge density in
  place of the radial network, the cutoff product and the density network.

``density_before_linear`` (the research engine's ``GENERIC_DENSITY_FIRST``) is still read, so the
forward stays a faithful copy, but no record sets it: it was not carried over (phase 1a
decision after wave 0).
"""

from __future__ import annotations

from collections.abc import Mapping

from types import MappingProxyType

import torch

# Class name -> (variant, sha256 of inspect.getsource(<class>.forward) in mace-torch 0.3.16);
# generic_interaction_forward reproduces each of them.
GENERIC_INTERACTIONS: Mapping[str, tuple[str, str]] = MappingProxyType({
    "RealAgnosticResidualInteractionBlock":
        ("residual", "5148c60b11fd7dcb8fca624aa0447b9e508fcb4d7869a2b3d79e1ac14f768b62"),
    "RealAgnosticDensityInteractionBlock":
        ("density", "80fd7bc7ea53c17b3212db3ff42ac87b6e42ee8e986c9b408aec06922ad91dad"),
    "RealAgnosticDensityResidualInteractionBlock":
        ("density_residual", "228610bc97daa842d6ecc8770142d1ad4bce24cc3060fecebc13e3df726a8316"),
})


def fc_split(network):
    """(hidden layers, last layer) of a bias-free e3nn FullyConnectedNet without output activation."""
    layers = list(network.children())
    last = layers[-1] if layers else None
    if type(network).__name__ != "FullyConnectedNet" or getattr(last, "act", True) is not None:
        raise ValueError(f"needs an e3nn FullyConnectedNet without output activation, got {type(network).__name__}")
    return torch.nn.Sequential(*layers[:-1]), last


def fc_last_weight(last):
    """Effective [out, in] matrix of an e3nn last layer: x @ w / sqrt(h_in var_in / var_out) == x @ result.T."""
    return (last.weight / (last.h_in * last.var_in / last.var_out) ** 0.5).t()

# Every atom's rows through its own species' matrix only (``fastmace.kernels.triton.species_gemm``), instead of
# through all present species' matrices followed by the selection of its block: a third of the products and no
# species-expanded intermediates for three species. Exact (the same dot products; bitwise in the species skip lab).
# CUDA float32 only (4 November 2026, Benchmark_loup speed goal). None: on for SPECIES_GEMM_GPUS (decision 66;
# owner, 4 November 2026: "Yes both"); True / False: an A/B side's choice on every GPU. Benchmark_loup (OMAT-0
# medium, SrTiO3 5,000 atoms) MD step b/a in both orders: RTX 4000 Ada 0.955 / 0.952, RTX 5060 Ti 0.950 / 0.953;
# A100-SXM4-80GB 0.992 / 0.991 (not adopted there: its skip runs as 3xTF32, where the Triton dot is about 3x slower
# per product than the concatenated CUTLASS GEMM; our own mma.sync kernel, species_gemm.TENSOR_CORES, did no better).
SPECIES_GEMM = None

SPECIES_GEMM_GPUS = ("NVIDIA GeForce RTX 5060 Ti", "NVIDIA RTX 4000 Ada Generation")


class SpeciesSkip(torch.nn.Module):
    """Element-dependent skip connection restricted to the structure's species (``generic_species_skip``).

    MACE's skip_tp is a fully connected tensor product of the node features with the
    one-hot node attributes (89x0e for the MP/MPA/OMAT/MatPES tables). For a one-hot
    input of element z it is a linear map L_z per irrep block, and cuEquivariance
    evaluates it for all elements (an [atoms, channels x 89] expansion). This keeps
    only the species present at setup: per block one GEMM against the concatenated
    [channels, species x channels] matrices, then the atom's own column block.
    Matrices are measured from the original module; atoms may change places later,
    but not to species absent at setup.
    """

    def __init__(self, columns, segments_in, segments_out, blocks, layout):
        super().__init__()
        self.register_buffer("columns", columns)
        self.segments_in = [tuple(s) for s in segments_in]
        self.segments_out = [tuple(s) for s in segments_out]
        self.layout = layout
        self.pairs = []
        for index, (i, j, weight) in enumerate(blocks):  # weight [species, mul_in, mul_out]
            species, mul_in, mul_out = weight.shape
            self.register_buffer(f"w{index}", weight.permute(1, 0, 2).reshape(mul_in, species * mul_out).contiguous())
            self.register_buffer(f"ws{index}", weight.contiguous(), persistent=False)  # [species, mul_in, mul_out]
            self.register_buffer(f"wt{index}", weight.transpose(1, 2).contiguous(), persistent=False)
            self.pairs.append((i, j))
        self.tf32x3 = False  # tf32x3_gemms: the products as 3xTF32 (OPT4-T03)
        self.skip_select = False  # idea 31 (kernels.cutlass.skip_select), set by precision.route
        # SPECIES_GEMM None: the device's default, fixed when the module is built on it
        self.species_gemm_gpu = (columns.is_cuda and torch.cuda.get_device_name(columns.device) in SPECIES_GEMM_GPUS)

    def plan_columns(self):
        """The node_attrs columns of the species plan the grouped forward builds (``SPECIES_GEMM``), or None where it
        builds none: the force field builds the plan outside the step and binds it (``species_gemm.bind_plan``)."""
        on = self.species_gemm_gpu if SPECIES_GEMM is None else SPECIES_GEMM
        return self.columns if on else None

    def _view(self, x, segment):
        offset, mul, dim = segment
        block = x[:, offset:offset + dim]
        if self.layout == "ir_mul":  # component m of channel u at m * mul + u
            return block.reshape(x.shape[0], dim // mul, mul)
        return block.reshape(x.shape[0], mul, dim // mul).transpose(1, 2)

    def _select_layout(self):
        """Whether ``kernels.cutlass.skip_select`` can join the products: ir_mul, one product per output block, the
        blocks side by side from column 0 (static: no graph break)."""
        if self.layout != "ir_mul" or sorted(j for _, j in self.pairs) != list(range(len(self.segments_out))):
            return False
        offset = 0
        for start, _, dim in self.segments_out:
            if start != offset:
                return False
            offset += dim
        return True

    def _selected(self, x1, blocks_in, onehot):
        """The skip through ``tf32x3_skip_select`` (each product's own-species columns stored into the joined
        output by the epilogue), or None where it does not apply."""
        from loupmd.export._vendor.fastmace.kernels.cutlass import skip_select

        atoms = onehot.shape[0]
        lefts, weights, offsets = [], [], []
        for index, (i, j) in enumerate(self.pairs):
            xi = blocks_in[i] if blocks_in is not None else self._view(x1, self.segments_in[i])
            lefts.append(xi.reshape(atoms * xi.shape[1], -1))
            weights.append(getattr(self, f"w{index}"))
            offsets.append(self.segments_out[j][0])
        width = self.segments_out[-1][0] + self.segments_out[-1][2]
        if not skip_select.applies(lefts, weights, onehot, offsets, width):
            return None
        kind = onehot.argmax(dim=1).to(torch.int32)
        return skip_select.tf32x3_skip_select(lefts, weights, onehot, kind, offsets, width)

    def forward(self, x1, x2):
        onehot = x2[:, self.columns]  # [atoms, species]
        atoms, species = onehot.shape
        outputs = [None] * len(self.segments_out)
        blocks_in = x1 if isinstance(x1, tuple) else None  # first_div: each input segment as [atoms, size, mul]
        x1 = x1[0] if blocks_in is not None else x1
        on = self.species_gemm_gpu if SPECIES_GEMM is None else SPECIES_GEMM
        grouped = on and x1.is_cuda and x1.dtype == torch.float32
        if not grouped and self.tf32x3 and self.skip_select and self._select_layout():
            selected = self._selected(x1, blocks_in, onehot)
            if selected is not None:
                return selected
        if grouped:
            from loupmd.export._vendor.fastmace.kernels.triton.species_gemm import bound_plan, species_mm, species_plan
            precision = "tf32x3" if self.tf32x3 else "ieee"
            plan = bound_plan(self, atoms)  # the force field's, built outside the step (species_gemm.bind_plan)
            if plan is not None:
                kind, order, counts = plan
            else:
                kind = onehot.argmax(dim=1)
                order, counts = species_plan(kind, species)
        for index, (i, j) in enumerate(self.pairs):
            weight = getattr(self, f"w{index}")
            xi = blocks_in[i] if blocks_in is not None else self._view(x1, self.segments_in[i])  # [atoms, size, mul]
            if grouped:
                y = species_mm(xi, getattr(self, f"ws{index}"), getattr(self, f"wt{index}"), kind, order, counts,
                               precision)
                outputs[j] = y if outputs[j] is None else outputs[j] + y
                continue
            size, mul_out = xi.shape[1], weight.shape[1] // species
            left = xi.reshape(atoms * size, -1)
            if self.tf32x3:
                from loupmd.export._vendor.fastmace.kernels.triton.tf32x3_gemm import tf32x3_matmul

                y = tf32x3_matmul(left, weight).view(atoms, size, species, mul_out)
            else:
                y = (left @ weight).view(atoms, size, species, mul_out)
            y = (y * onehot[:, None, :, None]).sum(dim=2)  # the atom's own species block
            outputs[j] = y if outputs[j] is None else outputs[j] + y
        blocks = []
        for j, (offset, mul, dim) in enumerate(self.segments_out):
            y = outputs[j]
            if y is None:
                y = x1.new_zeros(atoms, dim // mul, mul)
            if self.layout == "ir_mul":
                blocks.append(y.reshape(atoms, dim))
            else:
                blocks.append(y.transpose(1, 2).reshape(atoms, dim))
        return torch.cat(blocks, dim=1)


def irrep_segments(irreps):
    from e3nn import o3
    segments, offset = [], 0
    for mul, ir in o3.Irreps(str(irreps)):
        segments.append((offset, mul, mul * ir.dim, str(ir)))
        offset += mul * ir.dim
    return segments


def scalar_second_input(skip):
    """The element count of a skip_tp whose second input is all scalars (one-hot attributes), else None."""
    from e3nn import o3
    irreps_in2 = getattr(skip, "irreps_in2", None)
    if irreps_in2 is None:
        return None
    irreps = o3.Irreps(str(irreps_in2))
    if any(ir != o3.Irrep("0e") for _, ir in irreps):
        return None
    return irreps.dim


def species_skip(skip, columns):
    """A SpeciesSkip measured from ``skip`` (fully connected TP with one-hot scalar second input), or None."""
    elements = scalar_second_input(skip)
    if elements is None:
        return None
    segments_in, segments_out = irrep_segments(skip.irreps_in1), irrep_segments(skip.irreps_out)
    dim_in = sum(s[2] for s in segments_in)
    parameter = next(skip.parameters())
    device, dtype = parameter.device, parameter.dtype
    tolerance = 1e-4 if dtype == torch.float32 else 1e-10
    with torch.no_grad():
        for layout in ("ir_mul", "mul_ir"):
            blocks = []
            for i, (offset, mul, dim, ir) in enumerate(segments_in):
                size = dim // mul
                basis = torch.zeros((mul, dim_in), device=device, dtype=dtype)
                position = offset + (torch.arange(mul) if layout == "ir_mul" else torch.arange(mul) * size)
                basis[torch.arange(mul), position] = 1  # component m = 0 of every channel
                for j, (offset_out, mul_out, dim_out, ir_out) in enumerate(segments_out):
                    if ir_out != ir:
                        continue
                    weights = []
                    for column in columns.tolist():
                        attrs = torch.zeros((mul, elements), device=device, dtype=dtype)
                        attrs[:, column] = 1
                        response = skip(basis, attrs)
                        out = (response[:, offset_out:offset_out + mul_out] if layout == "ir_mul" else
                               response[:, offset_out:offset_out + dim_out:dim_out // mul_out])
                        weights.append(out.clone())
                    blocks.append((i, j, torch.stack(weights)))
            replacement = SpeciesSkip(columns.to(device), [s[:3] for s in segments_in],
                                      [s[:3] for s in segments_out], blocks, layout).to(device)
            generator = torch.Generator(device="cpu").manual_seed(0)
            probe = torch.randn((11, dim_in), generator=generator, dtype=dtype).to(device)
            picks = columns[torch.randint(len(columns), (11,), generator=generator)]
            attrs = torch.zeros((11, elements), device=device, dtype=dtype)
            attrs[torch.arange(11), picks.to(device)] = 1
            expected, got = skip(probe, attrs), replacement(probe, attrs)
            scale = float(expected.abs().max()) + 1e-30
            if got.shape == expected.shape and float((got - expected).abs().max()) <= tolerance * scale:
                return replacement
    raise ValueError(f"generic_species_skip: replacement of {type(skip).__name__} does not reproduce it")
