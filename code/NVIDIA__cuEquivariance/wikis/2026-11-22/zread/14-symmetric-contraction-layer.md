

The **Symmetric Contraction** layer is a GPU-accelerated PyTorch implementation of the symmetric contraction operation introduced in the MACE framework ([arXiv:2206.07697](https://arxiv.org/abs/2206.07697)). It computes equivariant features by contracting input irreps with themselves up to a specified polynomial degree, producing output irreps suitable for atomic-scale machine learning. This layer bridges the mathematical rigor of group-theoretic polynomial contractions with the performance demands of neural network training, offering both a native cuEquivariance descriptor path and an MACE-compatible emulation mode.

## Architectural Overview

The Symmetric Contraction layer sits at the intersection of the descriptor system and the PyTorch execution backend. Its architecture decomposes into three cooperating layers: a **mathematical descriptor** that encodes the equivariant polynomial structure, a **projection system** that provides MACE backward compatibility, and a **PyTorch module** that orchestrates weight management, layout transposition, and kernel dispatch.

```mermaid
flowchart TB
    subgraph "Descriptor Construction (init-time)"
        A[cue.descriptors.symmetric_contraction] --> B[EquivariantPolynomial<br/>poly2 — native basis]
        C[_symmetric_contraction<br/>MACE U-matrix basis] --> D[EquivariantPolynomial<br/>poly1 — MACE basis]
        B --> E[Projection Computation<br/>a2 → a1 via pinv]
        D --> E
        E --> P[Projection Matrix p]
    end

    subgraph "PyTorch Module — SymmetricContraction"
        P -->|original_mace=True| F[projection buffer]
        B --> G[SegmentedPolynomial f<br/>method: uniform_1d / naive]
        H[Weight Parameter<br/>shape: num_elements × weight_shape] --> I{original_mace?}
        F --> I
        I -->|Yes| J[einsum weight with projection]
        I -->|No| K[use weight directly]
        J --> L[Flatten weight]
        K --> L
        M[Input tensor x] --> N[TransposeIrrepsLayout<br/>layout_in → internal layout]
        N --> G
        L -->|input_indices={0: indices}| G
        G --> O[TransposeIrrepsLayout<br/>internal layout → layout_out]
        O --> P2[Output tensor]
    end
```

Sources: [symmetric_contraction.py](/cuequivariance_torch/cuequivariance_torch/operations/symmetric_contraction.py#L32-L243), [symmetric_contractions.py (descriptors)](/cuequivariance/cuequivariance/group_theory/descriptors/symmetric_contractions.py#L20-L133), [symmetric_contractions.py (mace)](/cuequivariance/cuequivariance/group_theory/experimental/mace/symmetric_contractions.py#L24-L94)

## The Two Descriptor Paths

At the heart of the layer lies a deliberate duality: cuEquivariance provides its own mathematically cleaner descriptor via `cue.descriptors.symmetric_contraction`, while also maintaining a projection from the original MACE basis. Both descriptors encode the same equivariant polynomial but use different internal representations of the symmetric tensor product space.

The **native descriptor** constructs the symmetric contraction using the reduced symmetric tensor product basis. It builds a `SegmentedTensorProduct` with subscripts `"w_a_b_c..._i+abc iw"` where the number of input operands equals the contraction degree, then populates its paths from the `reduced_symmetric_tensor_product_basis` filtered to keep only output irreps present in `irreps_out` [symmetric_contractions.py](/cuequivariance/cuequivariance/group_theory/descriptors/symmetric_contractions.py#L94-L116). The result is a compact polynomial with fewer internal paths and better numerical properties.

The **MACE-compatible descriptor** reconstructs the original MACE approach using `U_matrix_real` — a recursive Clebsch-Gordan contraction that builds the U-matrix basis via repeated coupling of irreps with Wigner nj-symbols [symmetric_contractions.py](/cuequivariance/cuequivariance/group_theory/experimental/mace/symmetric_contractions.py#L123-L169). A pseudoinverse projection matrix is computed at initialization time to map between the two bases:

$$P = A_1 \cdot A_2^+$$

where $A_1$ and $A_2$ are the flattened path-coefficient matrices of poly1 (MACE) and poly2 (native) respectively [symmetric_contractions.py](/cuequivariance/cuequivariance/group_theory/experimental/mace/symmetric_contractions.py#L86-L93).

| Aspect | Native Descriptor (`poly2`) | MACE Descriptor (`poly1`) |
|--------|---------------------------|--------------------------|
| Basis source | `reduced_symmetric_tensor_product_basis` | `U_matrix_real` (recursive Clebsch-Gordan) |
| Path count | Potentially fewer paths | May include redundant paths |
| Weight shape | `(etp.inputs[0].dim // mul, mul)` | `(p.shape[0], mul)` — projection matrix size |
| Numerical properties | Cleaner coefficients | Requires projection rounding to √-rationals |

## Module Initialization

The `SymmetricContraction.__init__` method orchestrates descriptor construction, weight allocation, layout setup, and method selection in a precise sequence [symmetric_contraction.py](/cuequivariance_torch/cuequivariance_torch/operations/symmetric_contraction.py#L106-L210).

**Irreps validation** is the first gate: all multiplicities across both input and output irreps must be identical, enforced by the assertion `len(set(irreps_in.muls) | set(irreps_out.muls)) != 1` [symmetric_contraction.py](/cuequivariance_torch/cuequivariance_torch/operations/symmetric_contraction.py#L129-L130). This constraint exists because the symmetric contraction treats multiplicity as a parallel batch dimension — each channel is contracted independently with the same polynomial structure.

**Descriptor and projection construction** calls `symmetric_contraction(irreps_in, irreps_out, range(1, contraction_degree + 1))` which returns both the native `EquivariantPolynomial` and the projection matrix [symmetric_contraction.py](/cuequivariance_torch/cuequivariance_torch/operations/symmetric_contraction.py#L137-L139). If `original_mace=True`, the projection matrix is registered as a persistent buffer; otherwise it is discarded and weights are sized directly against the polynomial's input dimensionality [symmetric_contraction.py](/cuequivariance_torch/cuequivariance_torch/operations/symmetric_contraction.py#L142-L149).

**Layout transposition** layers are created to bridge between user-facing layouts and the internal layout expected by the polynomial. Two `TransposeIrrepsLayout` modules handle input and output conversion, supporting the standard `ir_mul` and `mul_ir` layout conventions [symmetric_contraction.py](/cuequivariance_torch/cuequivariance_torch/operations/symmetric_contraction.py#L158-L174).

**Method selection** follows a deterministic priority chain. The `method` parameter takes explicit precedence; when absent, the layer inspects `etp.all_same_segment_shape()` — if all polynomial segments share identical dimensions, the fast `"uniform_1d"` CUDA kernel is selected; otherwise a warning is issued and the `"naive"` PyTorch fallback is used [symmetric_contraction.py](/cuequivariance_torch/cuequivariance_torch/operations/symmetric_contraction.py#L176-L204). The deprecated `use_fallback` parameter is still accepted but maps to the `method` parameter with a deprecation warning [symmetric_contraction.py](/cuequivariance_torch/cuequivariance_torch/operations/symmetric_contraction.py#L187-L197).

> [!TIP]
> The `uniform_1d` method requires all segments to have the same shape. If your descriptor mixes irreps of different dimensions, consider whether making segments uniform (e.g., padding) is worthwhile for the CUDA kernel speedup. The layer will raise a `ValueError` if `method="uniform_1d"` is explicitly requested but segments are non-uniform [symmetric_contraction.py](/cuequivariance_torch/cuequivariance_torch/operations/symmetric_contraction.py#L199-L203).

## Constructor Reference

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `irreps_in` | `Irreps` | — | Input irreps; all multiplicities must be identical |
| `irreps_out` | `Irreps` | — | Output irreps; all multiplicities must be identical |
| `contraction_degree` | `int` | — | Maximum polynomial degree (1 = linear, 2 = quadratic, 3 = body-order-3) |
| `num_elements` | `int` | — | Number of element types for the weight table |
| `layout` | `IrrepsLayout` | `None` | Shared layout for both input and output |
| `layout_in` | `IrrepsLayout` | `None` | Input layout (overrides `layout`) |
| `layout_out` | `IrrepsLayout` | `None` | Output layout (overrides `layout`) |
| `device` | `torch.device` | `None` | Target device for weights and buffers |
| `dtype` | `torch.dtype` | `float32` | Weight tensor dtype |
| `math_dtype` | `str / torch.dtype` | `None` | Internal computation dtype; follows input if `None` |
| `original_mace` | `bool` | `False` | Enable MACE-compatible weight space via projection |
| `use_fallback` | `bool` | `None` | *(Deprecated)* `True` → naive, `False` → uniform_1d |
| `method` | `str` | `None` | `"uniform_1d"` or `"naive"`; auto-selected if `None` |

Sources: [symmetric_contraction.py](/cuequivariance_torch/cuequivariance_torch/operations/symmetric_contraction.py#L106-L122)

## Forward Pass Execution

The `forward` method implements a clean two-stage pipeline: weight preparation followed by polynomial evaluation [symmetric_contraction.py](/cuequivariance_torch/cuequivariance_torch/operations/symmetric_contraction.py#L218-L242).

In the **weight preparation** stage, when `original_mace=True`, the stored weight tensor of shape `(num_elements, p.shape[0], mul)` is projected via Einstein summation `einsum("zau,ab->zbu", self.weight, self.projection)` to transform from the MACE parameterization into the native descriptor's weight space [symmetric_contraction.py](/cuequivariance_torch/cuequivariance_torch/operations/symmetric_contraction.py#L236). When `original_mace=False`, the weight is used directly. In both cases, the weight is then flattened along its trailing dimensions to produce a 2D tensor of shape `(num_elements, flattened_weight_dim)` [symmetric_contraction.py](/cuequivariance_torch/cuequivariance_torch/operations/symmetric_contraction.py#L239).

The **polynomial evaluation** stage passes two inputs to the underlying `SegmentedPolynomial`: the prepared weight tensor and the layout-transposed input features. Crucially, `input_indices={0: indices}` signals that the weight operand (index 0) should be indexed per-sample using the `indices` tensor — this is the mechanism that selects element-specific weights from the weight table for each node in the graph [symmetric_contraction.py](/cuequivariance_torch/cuequivariance_torch/operations/symmetric_contraction.py#L241). The output is then transposed back to the user-requested layout before returning.

```mermaid
flowchart LR
    X["x: (batch, irreps_in.dim)"] --> T1[TransposeIrrepsLayout<br/>layout_in → internal]
    W["weight: (num_elements, w_dim)"] --> SP
    IDX["indices: (batch,)"] -->|input_indices={0}| SP
    T1 --> SP["SegmentedPolynomial f"]
    SP --> T2[TransposeIrrepsLayout<br/>internal → layout_out]
    T2 --> Y["output: (batch, irreps_out.dim)"]
```

The input tensor `x` has shape `(batch, irreps_in.dim)` and the `indices` tensor has shape `(batch,)` with integer values in `[0, num_elements)`. The output tensor has shape `(batch, irreps_out.dim)` [symmetric_contraction.py](/cuequivariance_torch/cuequivariance_torch/operations/symmetric_contraction.py#L227-L232).

Sources: [symmetric_contraction.py](/cuequivariance_torch/cuequivariance_torch/operations/symmetric_contraction.py#L218-L242)

> [!TIP]
> The `indices` parameter serves as an element-type lookup: each sample in the batch selects a different row from the weight table. In molecular simulations, this maps naturally to per-node element identities (e.g., H, C, N, O indices). The indexed weight selection happens inside the `SegmentedPolynomial` kernel, avoiding explicit gather operations in user code.

## Usage Patterns

### Basic Construction

The simplest usage creates a degree-3 symmetric contraction mapping from 32-channel O(3) features with even-parity scalars and odd-parity vectors to even-parity scalars [symmetric_contraction.py](/cuequivariance_torch/cuequivariance_torch/operations/symmetric_contraction.py#L58-L61):

```python
import torch
import cuequivariance as cue
import cuequivariance_torch as cuet

device = torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu")
irreps_in = cue.Irreps("O3", "32x0e + 32x1o")
irreps_out = cue.Irreps("O3", "32x0e")
layer = cuet.SymmetricContraction(
    irreps_in, irreps_out,
    contraction_degree=3,
    num_elements=5,
    layout=cue.ir_mul,
    dtype=torch.float32,
    device=device,
)

x = torch.randn(128, irreps_in.dim, dtype=torch.float32, device=device)
indices = torch.randint(0, 5, (128,), dtype=torch.int32, device=device)
output = layer(x, indices)  # shape: (128, irreps_out.dim)
```

### MACE Compatibility Mode

When migrating from the original MACE framework, setting `original_mace=True` ensures that weights trained in MACE produce identical outputs. The key difference is that the MACE parameterization uses the U-matrix basis from its Clebsch-Gordan implementation, while cuEquivariance uses a reduced symmetric tensor product basis [symmetric_contraction.py](/cuequivariance_torch/cuequivariance_torch/operations/symmetric_contraction.py#L65-L98):

```python
feats_irreps = cue.Irreps("O3", "32x0e + 32x1o + 32x2e")
target_irreps = cue.Irreps("O3", "32x0e + 32x1o")

layer = cuet.SymmetricContraction(
    irreps_in=feats_irreps,
    irreps_out=target_irreps,
    contraction_degree=3,
    num_elements=10,
    layout_in=cue.ir_mul,
    layout_out=cue.mul_ir,
    original_mace=True,
    dtype=torch.float64,
    device=device,
)

# MACE stores features as (batch, mul, irrep_dim) — transpose to flat
node_feats = torch.randn(128, 32, feats_irreps.dim // 32, dtype=torch.float64, device=device)
node_feats = node_feats.transpose(1, 2).flatten(1)
node_attrs_index = torch.randint(0, 10, (128,), dtype=torch.int32, device=device)
output = layer(node_feats, node_attrs_index)
```

Note the input tensor reshaping: MACE uses a `(batch, mul, irrep_dim)` layout (i.e., `ir_mul`), while the flat tensor consumed by `forward` has shape `(batch, irreps_in.dim)`. The `layout_in` and `layout_out` parameters handle the internal transposition transparently.

Sources: [symmetric_contraction.py](/cuequivariance_torch/cuequivariance_torch/operations/symmetric_contraction.py#L65-L98), [symmetric_contraction_test.py](/cuequivariance_torch/tests/operations/symmetric_contraction_test.py#L75-L123)

## Export and Deployment

The `SymmetricContraction` module supports three PyTorch export modes verified in the test suite: `torch.compile`, `torch.jit.script`, and `torch.jit.trace` [symmetric_contraction_test.py](/cuequivariance_torch/tests/operations/symmetric_contraction_test.py#L126-L183). This ensures compatibility with production deployment pipelines that require serialized or compiled models. The tests parametrize across float32/float64 dtypes, both layout conventions, both MACE modes, and batch sizes to confirm correctness under all export paths.

## Next Steps

- **[Tensor Product Operations](15-tensor-product-operations)** — Understand the `SegmentedPolynomial` and `SegmentedTensorProduct` primitives that power the symmetric contraction's polynomial evaluation.
- **[PyTorch Segmented Polynomial Module](12-pytorch-segmented-polynomial-module)** — Deep dive into the `SegmentedPolynomial` PyTorch wrapper, including the `uniform_1d` vs `naive` method distinction and `input_indices` mechanics.
- **[Rotation and Symmetric Contraction](11-rotation-and-symmetric-contraction)** — Explore the mathematical foundations of symmetric contractions and their relationship to rotation descriptors.
- **[Model Examples: MACE and NequIP](21-model-examples-mace-and-nequip)** — See how `SymmetricContraction` integrates into full equivariant architectures like MACE.