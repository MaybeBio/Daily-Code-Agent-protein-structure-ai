# GPU Kernel Stack

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [bionemo_ir/_torch/attention_backend/pairwise_attention/_cubin.py](bionemo_ir/_torch/attention_backend/pairwise_attention/_cubin.py)
- [bionemo_ir/_torch/attention_backend/pairwise_attention/cutedsl.py](bionemo_ir/_torch/attention_backend/pairwise_attention/cutedsl.py)
- [bionemo_ir/_torch/attention_backend/triangle_attention/_cubin.py](bionemo_ir/_torch/attention_backend/triangle_attention/_cubin.py)
- [bionemo_ir/_torch/custom_ops/outer_product_mean/_cubin.py](bionemo_ir/_torch/custom_ops/outer_product_mean/_cubin.py)
- [bionemo_ir/_torch/utils/kernel/__init__.py](bionemo_ir/_torch/utils/kernel/__init__.py)
- [bionemo_ir/_torch/utils/kernel/_cutedsl_kernel_library.py](bionemo_ir/_torch/utils/kernel/_cutedsl_kernel_library.py)
- [cpp/kernels/cutedsl_adaln_layernorm_sigmoid/cubins/index.json](cpp/kernels/cutedsl_adaln_layernorm_sigmoid/cubins/index.json)
- [cpp/kernels/cutedsl_attn_epilogue/cubins/index.json](cpp/kernels/cutedsl_attn_epilogue/cubins/index.json)
- [cpp/kernels/cutedsl_dual_gemm_x0_x1/cubins/index.json](cpp/kernels/cutedsl_dual_gemm_x0_x1/cubins/index.json)
- [cpp/kernels/cutedsl_dual_gemm_x_x/cubins/index.json](cpp/kernels/cutedsl_dual_gemm_x_x/cubins/index.json)
- [cpp/kernels/cutedsl_gated_sigmoid/cubins/index.json](cpp/kernels/cutedsl_gated_sigmoid/cubins/index.json)
- [cpp/kernels/cutedsl_launch_utils.h](cpp/kernels/cutedsl_launch_utils.h)
- [cpp/kernels/cutedsl_outer_product_mean/cubins/index.json](cpp/kernels/cutedsl_outer_product_mean/cubins/index.json)
- [cpp/kernels/cutedsl_pair_weighted_averaging/cubins/index.json](cpp/kernels/cutedsl_pair_weighted_averaging/cubins/index.json)
- [cpp/kernels/cutedsl_pairwise_attention/cubins/index.json](cpp/kernels/cutedsl_pairwise_attention/cubins/index.json)
- [cpp/kernels/cutedsl_pairwise_attention/launcher.cpp](cpp/kernels/cutedsl_pairwise_attention/launcher.cpp)
- [cpp/kernels/cutedsl_transition_mlp/cubins/index.json](cpp/kernels/cutedsl_transition_mlp/cubins/index.json)
- [cpp/kernels/cutedsl_triangle_attention/cubins/index.json](cpp/kernels/cutedsl_triangle_attention/cubins/index.json)
- [tests/_torch/test_cutedsl_kernel_library.py](tests/_torch/test_cutedsl_kernel_library.py)
- [tests/_torch/test_pairwise_attention_cutedsl.py](tests/_torch/test_pairwise_attention_cutedsl.py)

</details>



The GPU Kernel Stack in BioNeMo Inference Runtime (BioIR) provides high-performance, fused GPU operators tailored for structural biology models (such as OpenFold and Boltz). It combines Triton kernels, cuEquivariance integrations, and CuTeDSL-based C++ compiled launchers backed by precompiled CUBIN packages. This architecture bypasses standard PyTorch dispatch overheads for compute-intensive blocks like triangle attention, pairwise attention, gated activations, and dual matrix multiplications.

As a parent page, this overview outlines the main structural components of the kernel stack. For in-depth technical details, implementation specifics, and tuning tables, refer to the respective child pages:
- [Attention Backends](#5.1) — Triangle, pairwise and window attention backends: vanilla, SDPA, cuEquivariance, ClaudeKit and CuTeDSL paths, backend selection heuristics.
- [Custom Fused Ops](#5.2) — `adaln_layernorm_sigmoid`, `gated_sigmoid`, dual GEMM, `outer_product_mean`, `pair_weighted_averaging`, `transition_mlp`, `attn_epilogue`, `trimul_kf` chain: Python op wrappers, config resolution, cubin loading.
- [C++ CuTeDSL Launchers and Bindings](#5.3) — `cpp/kernels` launcher architecture (`launcher.cpp/.h`), config resolution, validation, SM80/SM90 dispatch, TMA descriptors, nanobind bindings, embedded cubins, and kernel registry.
- [Triton Kernel Cache and Fused Triton Kernels](#5.4) — `TritonKernelCache`/`CachedKernel`/`DriverLauncher` compilation and caching, `cute_cache`, and the `dsl_kernels/triton` kernel family.

---

## 5.1 Attention Backends

BioIR abstracts attention mechanisms through the `AttentionBackend` interface, supporting triangle attention, pairwise attention, and window attention nodes [bionemo_ir/_torch/attention_backend/interface.py]() / [bionemo_ir/_torch/attention_backend/pairwise_attention/cutedsl.py:16-51](). The framework supports multiple execution paths to balance numerical portability and peak hardware efficiency across different NVIDIA GPU architectures:
- **Vanilla**: Pure PyTorch reference implementations for numerical parity checking.
- **SDPA**: PyTorch scaled dot-product attention wrappers leveraging hardware-accelerated FlashAttention paths.
- **cuEquivariance**: Specialized equivariant attention blocks for geometry-aware feature transformations.
- **CuTeDSL Paths**: Highly optimized CUBIN-backed kernels (`TriangleAttentionCuTeLeftMask`, `PairwiseAttentionCuTeLeftMask`) that process left-aligned packed KV buffers directly [bionemo_ir/_torch/attention_backend/pairwise_attention/cutedsl.py:22-29]().

Backend selection heuristics dynamically route calls to the optimal execution path based on device capability and tensor data types [bionemo_ir/_torch/attention_backend/pairwise_attention/cutedsl.py:17-20]().

### 5.1.1 Attention Kernel Tuning Configs
Per-head-dimension and per-SM JSON tuning tables supply optimal block sizes, thread counts, swizzling parameters, and sequence length buckets for triangle, pairwise, and window attention backends [bionemo_ir/_torch/attention_backend/pairwise_attention/cutedsl.py:52-57]().

For detailed architectures, execution paths, and tuning parameter structures, see [Attention Backends](#5.1).

```mermaid
graph TD
    A["AutoSelectAttentionBackend"] -->|"SM80-90 + Half Dtype"| B["PairwiseAttentionCuTeLeftMask"]
    A -->|"Standard Path"| C["SDPAPairwiseAttention"]
    B --> D["CPPCuTeDSLLauncher"]
    D --> E["EmbeddedCubinPack"]

    sub: Sources
    style sub fill:none,stroke:none
    end
```
*Sources: [bionemo_ir/_torch/attention_backend/pairwise_attention/cutedsl.py:16-58]()*

---

## 5.2 Custom Fused Ops

To eliminate redundant memory round-trips during intermediate transformation stages, BioIR implements a collection of custom fused operators. These are exposed via Python wrappers that manage configuration lookup, device placement validation, and CUBIN image materialization:
- **AdaLN & Gated Activations**: `adaln_layernorm_sigmoid` and `gated_sigmoid` fuse layer normalization, gating projections, and sigmoid activations [cpp/kernels/cutedsl_adaln_layernorm_sigmoid/cubins/index.json:1-110](), [cpp/kernels/cutedsl_gated_sigmoid/cubins/index.json:1-94]().
- **Dual GEMMs**: Optimized matrix multiplication pairs (`dual_gemm_x_x` and `dual_gemm_x0_x1`) execute parallel projections over shared activation inputs with fused biases [cpp/kernels/cutedsl_dual_gemm_x_x/cubins/index.json:1-102](), [cpp/kernels/cutedsl_dual_gemm_x0_x1/cubins/index.json:1-102]().
- **Pairwise Aggregations**: `outer_product_mean` and `pair_weighted_averaging` combine tensor outer products and mask reductions into single-pass GPU kernels [cpp/kernels/cutedsl_outer_product_mean/cubins/index.json:1-94](), [cpp/kernels/cutedsl_pair_weighted_averaging/cubins/index.json:1-94]().
- **MLP & Epilogue Chains**: `transition_mlp`, `attn_epilogue`, and the `trimul_kf` chain optimize multi-layer perceptron blocks and attention output projections [cpp/kernels/cutedsl_transition_mlp/cubins/index.json:1-94](), [cpp/kernels/cutedsl_attn_epilogue/cubins/index.json:1-94]().

### 5.2.1 Custom Op Tuning Config Tables
Per-N, per-K, and per-SM JSON configuration files define tile sizes, warp configurations, and scheduling policies for adaln, gated sigmoid, dual GEMM, trimul_kf, transition MLP, outer product mean, and pair-weighted averaging [cpp/kernels/cutedsl_dual_gemm_x_x/cubins/index.json:1-102]().

For detailed operator signatures, Python wrappers, and tuning table specifications, see [Custom Fused Ops](#5.2).

```mermaid
graph TD
    Z["PyTorchModuleForward"] --> Y["CustomOpPythonWrapper"]
    Y --> X["ConfigResolutionAndValidation"]
    X --> W["CUBINLibraryLoader"]
    W --> V["CPPCuTeDSLLauncher"]
    V --> U["GPUDeviceExecution"]

    sub: Sources
    style sub fill:none,stroke:none
    end
```
*Sources: [cpp/kernels/cutedsl_dual_gemm_x_x/cubins/index.json:1-102](), [cpp/kernels/cutedsl_adaln_layernorm_sigmoid/cubins/index.json:1-110]()*

---

## 5.3 C++ CuTeDSL Launchers and Bindings

The foundation of the CuTeDSL kernel stack resides in the C++ layer under `cpp/kernels/`. This directory implements host-side launchers and validation harnesses for compiled CUBINs without relying on runtime JIT compilation overheads.

Key architectural responsibilities handled by the C++ layer include:
- **Parameter Validation**: Ensuring strict tensor layout alignment, compatible shapes, and matching CUDA device IDs across operands [tests/_torch/test_cutedsl_kernel_library.py:114-148]().
- **SM80 / SM90 Dispatch**: Branching between standard cooperative launch grids and advanced Hopper features such as persistent grid rasterization factors, cluster dimensions, and Tensor Memory Accelerator (TMA) descriptor configurations [cpp/kernels/cutedsl_triangle_attention/cubins/index.json:1-102]().
- **nanobind Bindings**: Exposing zero-overhead Python bindings that map directly to underlying C++ launcher entrypoints.

### 5.3.1 Embedded Cubin Packs and the Kernel Registry
Precompiled CUBIN tarballs are packed and indexed via `index.json` (specifying fingerprints, shards, and architecture packs like `sm_80`, `sm_90a`, `sm_100a`, `sm_103a`), materialized at build time, and preloaded at runtime through `CuTeDSLKernelLibraryExecutable` and related helper utilities [cpp/kernels/cutedsl_dual_gemm_x0_x1/cubins/index.json:1-102](), [tests/_torch/test_cutedsl_kernel_library.py:29-56]().

For detailed breakdown of launcher header structures, TMA metadata validation, and the CUBIN packaging pipeline, see [C++ CuTeDSL Launchers and Bindings](#5.3).

```mermaid
graph TD
    T["nanobindModule"] --> S["LauncherValidation"]
    S --> R["SM80OrSM90DispatchHandler"]
    R --> Q["TMADescriptorVerification"]
    Q --> P["CuLaunchKernelOrCluster"]

    sub: Sources
    style sub fill:none,stroke:none
    end
```
*Sources: [cpp/kernels/cutedsl_dual_gemm_x0_x1/cubins/index.json:1-102](), [tests/_torch/test_cutedsl_kernel_library.py:29-56]()*

---

## 5.4 Triton Kernel Cache and Fused Triton Kernels

In addition to CuTeDSL CUBINs, BioIR integrates Triton-based kernels via `TritonKernelCache`, `CachedKernel`, and `DriverLauncher` classes. These components manage on-the-fly compilation, disk caching, and execution dispatch for Triton operators.

The `dsl_kernels/triton` kernel family includes specialized fused operators:
- **Fused LayerNorm + Projection**: Combines normalization and linear projections into a single memory-efficient pass.
- **SwiGLU Activations**: Optimized gated linear unit variants.
- **EDM Churn**: Specialized sampling and noise-scaling routines for diffusion models.
- **Query-to-Keys & Atom Operations**: `query_to_keys`, atom gather operations, relative position embedding (`relpos_embed`), and `rigid_align`.

For detailed architecture, compilation caching policies, and Triton kernel specifications, see [Triton Kernel Cache and Fused Triton Kernels](#5.4).

```mermaid
graph TD
    A["TritonKernelRequest"] --> B["TritonKernelCache"]
    B --> C["CachedKernelCompilation"]
    C --> D["DriverLauncherDispatch"]
    D --> E["GPUExecution"]

    sub: Sources
    style sub fill:none,stroke:none
    end
```
*Sources: [bionemo_ir/_torch/attention_backend/pairwise_attention/cutedsl.py:40-48](), [tests/_torch/test_cutedsl_kernel_library.py:25-28]()*

---