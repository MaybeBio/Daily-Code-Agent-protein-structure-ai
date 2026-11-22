# Triton Kernel Cache and Fused Triton Kernels

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.coderabbit.yaml](.coderabbit.yaml)
- [bionemo_ir/_torch/graph_optimization/cudnn_graph/ops.py](bionemo_ir/_torch/graph_optimization/cudnn_graph/ops.py)
- [bionemo_ir/_torch/layers/transition.py](bionemo_ir/_torch/layers/transition.py)
- [bionemo_ir/_torch/modules/protenix/confidence.py](bionemo_ir/_torch/modules/protenix/confidence.py)
- [bionemo_ir/dsl_kernels/cache_base.py](bionemo_ir/dsl_kernels/cache_base.py)
- [bionemo_ir/dsl_kernels/triton/edm.py](bionemo_ir/dsl_kernels/triton/edm.py)
- [bionemo_ir/dsl_kernels/triton/fused_layer_norm_transpose.py](bionemo_ir/dsl_kernels/triton/fused_layer_norm_transpose.py)
- [bionemo_ir/dsl_kernels/triton/fused_ln_proj_moveaxis_pad.py](bionemo_ir/dsl_kernels/triton/fused_ln_proj_moveaxis_pad.py)
- [bionemo_ir/dsl_kernels/triton/fused_swiglu.py](bionemo_ir/dsl_kernels/triton/fused_swiglu.py)
- [bionemo_ir/dsl_kernels/triton/indexed_projection.py](bionemo_ir/dsl_kernels/triton/indexed_projection.py)
- [bionemo_ir/dsl_kernels/triton/ln_pair_bias.py](bionemo_ir/dsl_kernels/triton/ln_pair_bias.py)
- [bionemo_ir/dsl_kernels/triton/moveaxis_pad.py](bionemo_ir/dsl_kernels/triton/moveaxis_pad.py)
- [bionemo_ir/dsl_kernels/triton/quaternion_rotation.py](bionemo_ir/dsl_kernels/triton/quaternion_rotation.py)
- [bionemo_ir/dsl_kernels/triton/query_to_keys.py](bionemo_ir/dsl_kernels/triton/query_to_keys.py)
- [bionemo_ir/dsl_kernels/triton_cache.py](bionemo_ir/dsl_kernels/triton_cache.py)
- [tests/_torch/graph_optimization/test_cudnn_graph.py](tests/_torch/graph_optimization/test_cudnn_graph.py)
- [tests/_torch/test_edm_churn_kernel.py](tests/_torch/test_edm_churn_kernel.py)
- [tests/_torch/test_protenix_indexed_projection.py](tests/_torch/test_protenix_indexed_projection.py)
- [tests/_torch/test_quaternion_kernel.py](tests/_torch/test_quaternion_kernel.py)
- [tests/_torch/test_transition.py](tests/_torch/test_transition.py)
- [tests/_torch/test_triton_cache.py](tests/_torch/test_triton_cache.py)
- [tests/ops/test_fused_layer_norm_transpose.py](tests/ops/test_fused_layer_norm_transpose.py)

</details>



This page documents the compilation, caching, and low-overhead launch infrastructure for Triton kernels in the BioNeMo Inference Runtime (BioIR), alongside the `dsl_kernels/triton` family of fused custom GPU operations. BioIR relies on a custom caching layer (`TritonKernelCache`, `CachedKernel`, and `DriverLauncher`) to compile Triton JIT functions once, isolate disk persistence, and execute them directly via CUDA driver bindings (`cuda.bindings`), bypassing standard Triton dispatch overhead.

---

## 1. Triton Compilation, Caching, and Driver Launch Architecture

The Triton caching and execution stack minimizes Python dispatch latency and prevents redundant kernel compilation across model instantiations. It consists of three primary abstractions:

*   `TritonKernelCache`: Manages isolated disk caching (`BIOIR_TRITON_CACHE_DIR` / `TRITON_CACHE_DIR`), thread-safe locking, and subprocess compilation warming `[bionemo_ir/dsl_kernels/triton_cache.py:19](), [bionemo_ir/dsl_kernels/triton_cache.py:62]()`].
*   `CachedKernel`: Wraps a compiled Triton `CompiledKernel`, maintaining a reference to an optional `DriverLauncher` for direct CUBIN dispatch or falling back to `.run()` `[bionemo_ir/dsl_kernels/triton_cache.py:147](), [bionemo_ir/dsl_kernels/triton_cache.py:182]()`.
*   `DriverLauncher`: Uses `cuda.bindings` to launch compiled CUBINs directly against a `CUstream`, eliminating Python JIT inspection overhead during inference loops `[bionemo_ir/dsl_kernels/cache_base.py]()`.

### Value Specialization and Shape Agnosticism
Because a single CUBIN is reused across arbitrary runtime shapes and strides, Triton JIT parameters must not be specialized on compile-time dummy values. Non-constexpr scalar arguments can trigger two fatal behaviors for reused binaries:
1. `divisible_by_16` alignment assumptions when a dummy value is a multiple of 16.
2. Value folding (`value == 1`) which strips the argument entirely and shifts parameter offsets.

The utility `value_specialized_params` inspects `jit_fn.params` against `dummy_args` to ensure unsafe scalars are explicitly marked with `do_not_specialize` `[bionemo_ir/dsl_kernels/triton_cache.py:116](), [bionemo_ir/dsl_kernels/triton_cache.py:58]()`.

```mermaid
graph TD
    subgraph "NaturalLanguageSpace"
        A["TritonCacheManager"] --> B["KernelCompilation"]
        B --> C["DirectDriverLauncher"]
    end

    subgraph "CodeEntitySpace"
        D["TritonKernelCache"] --> E["CachedKernel"]
        E --> F["DriverLauncher"]
        F --> G["cuda.bindings"]
        H["value_specialized_params"] --> I["_fused_ln_proj_moveaxis_pad_kernel"]
    end

    A -.-> D
    B -.-> E
    C -.-> F

    Sources: bionemo_ir/dsl_kernels/triton_cache.py:16-185
```
Sources: `bionemo_ir/dsl_kernels/triton_cache.py:16-185`

---

## 2. Kernel Caching Infrastructure (`cute_cache` and Base Abstractions)

The underlying caching primitives reside in `bionemo_ir/dsl_kernels/cache_base.py` and `bionemo_ir/dsl_kernels/triton_cache.py`. 

### Disk Caching and File Locking
`DiskCache` manages local artifact directories, ensuring concurrent worker processes do not race during cold-cache compilation. `FileLock` coordinates multi-process access to the cache index and compiled cubin bundles. Cold caches can optionally be warmed in isolated subprocesses using `_compile_in_subprocess` to prevent deadlocks in distributed Ray or multi-GPU environments `[bionemo_ir/dsl_kernels/triton_cache.py:19](), [bionemo_ir/dsl_kernels/cache_base.py]()`.

Sources: `bionemo_ir/dsl_kernels/cache_base.py`, `bionemo_ir/dsl_kernels/triton_cache.py:43-78`

---

## 3. The `dsl_kernels/triton` Kernel Family

BioIR implements a family of highly optimized, fused Triton kernels in `bionemo_ir/dsl_kernels/triton/` to replace multi-pass PyTorch operations in transformer trunks, pair representations, and diffusion/confidence heads.

```mermaid
graph TD
    subgraph "NaturalLanguageSpace"
        TP["FusedPairBiasAndNorm"] --> K1["fused_ln_proj_moveaxis_pad.py"]
        FFN["FusedSwiGLUActivation"] --> K2["fused_swiglu.py"]
        ATTN["TriangleBiasProjection"] --> K3["ln_pair_bias.py"]
        DIFF["EDMDiffusionChurn"] --> K4["edm.py"]
        CONF["IndexedLDDTProjection"] --> K5["indexed_projection.py"]
    end

    subgraph "CodeEntitySpace"
        K1 --> L1["_fused_ln_proj_moveaxis_pad_kernel"]
        K2 --> L2["_fused_swiglu_kernel"]
        K3 --> L3["_ln_pair_bias_kernel"]
        K4 --> L4["_churn_kernel"]
        K5 --> L5["_cached_projection"]
    end

    Sources: bionemo_ir/dsl_kernels/triton/fused_ln_proj_moveaxis_pad.py:58-98, bionemo_ir/dsl_kernels/triton/fused_swiglu.py:56-89, bionemo_ir/dsl_kernels/triton/ln_pair_bias.py:41-60
```
Sources: `bionemo_ir/dsl_kernels/triton/fused_ln_proj_moveaxis_pad.py:58-98`, `bionemo_ir/dsl_kernels/triton/fused_swiglu.py:56-89`, `bionemo_ir/dsl_kernels/triton/ln_pair_bias.py:41-60`

### 3.1. Fused LayerNorm, Linear Projection, Moveaxis, and Pad (`fused_ln_proj_moveaxis_pad.py`)
In attention pair-bias paths (e.g., `AttentionPairBias`), tensors flow as `z: [B, I, J, D]`. Unfused execution requires LayerNorm, Linear projection, and transposition across separate kernels over $O(N^2)$ tensors. 
*   `_fused_ln_proj_moveaxis_pad_kernel`: Reads `z` once, computes LayerNorm statistics in registers, folds the affine transform into a tiled matrix multiplication against `w_proj`, and writes straight into the transposed, zero-padded `[B, H, I, J_padded]` layout `[bionemo_ir/dsl_kernels/triton/fused_ln_proj_moveaxis_pad.py:58-105]`.
*   `FusedLNProjMoveaxisPad`: Class-level wrapper providing JIT compilation management and `cuda.bindings` dispatch.

Sources: `bionemo_ir/dsl_kernels/triton/fused_ln_proj_moveaxis_pad.py:1-105`

### 3.2. Fused LayerNorm and Triangle-Bias Projection (`ln_pair_bias.py`)
*   `_ln_pair_bias_kernel`: Executes a single pass over pair rows, writing `normed = LayerNorm(x)` in ending-node order (`b, j, i`), and projecting `bias = normed @ weight.T` with FP32 accumulation into the attention bias layout `[B, H, R, S_padded]` `[bionemo_ir/dsl_kernels/triton/ln_pair_bias.py:41-100]`.
*   `LNPairBias`: Manages compiled configurations per channel dimension `C`, head count `H`, and transposition flags `[bionemo_ir/dsl_kernels/triton/ln_pair_bias.py:108-144]`.

Sources: `bionemo_ir/dsl_kernels/triton/ln_pair_bias.py:15-100`

### 3.3. Fused SwiGLU Activation (`fused_swiglu.py`)
*   `_fused_swiglu_kernel`: Computes either 2-way (`silu(gate) * x`) or 3-way (`silu(gate) * x * n`) activations directly from a packed input tensor `z` (`[..., 2*d]` or `[..., 3*d]`), eliminating intermediate slice allocations and extra kernel launches `[bionemo_ir/dsl_kernels/triton/fused_swiglu.py:56-89]`.
*   `FusedSwiGLU`: Inherits from `TritonKernelCache` for pre-compilation and low-overhead dispatch `[bionemo_ir/dsl_kernels/triton/fused_swiglu.py:109-195]`.

Sources: `bionemo_ir/dsl_kernels/triton/fused_swiglu.py:21-89`

### 3.4. Moveaxis and Zero-Pad (`moveaxis_pad.py`)
*   `_moveaxis_pad_kernel`: Fuses `moveaxis(-1, -3)` with zero-padding along the `J` dimension. Each threadblock loads a `[BLOCK_J, BLOCK_H]` tile, transposes it in registers, and stores it in the contiguous padded destination buffer `[bionemo_ir/dsl_kernels/triton/moveaxis_pad.py:52-105]`.

Sources: `bionemo_ir/dsl_kernels/triton/moveaxis_pad.py:16-105`

### 3.5. Additional Triton Kernels in `dsl_kernels/triton/`
*   **EDM Churn (`edm.py`)**: Implements stochastic noise augmentation and derivative updates for EDM flow-matching and diffusion sampling schedules `[bionemo_ir/dsl_kernels/triton/edm.py:1]`.
*   **Atom Gather & Reduction (`atom_gather_kernel.py`)**: Performs sparse atom-to-token slot reductions and gather operations for all-atom multimer representation builders `[bionemo_ir/dsl_kernels/triton/atom_gather_kernel.py:1]`.
*   **Query-to-Keys (`query_to_keys.py`)**: Optimizes pairwise query-key distance and attention indexing transformations `[bionemo_ir/dsl_kernels/triton/query_to_keys.py:1]`.
*   **Indexed Projection (`indexed_projection.py`)**: Accelerates confidence head pLDDT and resolved-probability projections by indexing directly into weight tensors without sparse tensor overhead `[bionemo_ir/dsl_kernels/triton/indexed_projection.py:1]`.

Sources: `bionemo_ir/dsl_kernels/triton/edm.py`, `bionemo_ir/dsl_kernels/triton/atom_gather_kernel.py`, `bionemo_ir/dsl_kernels/triton/query_to_keys.py`, `bionemo_ir/dsl_kernels/triton/indexed_projection.py`

---