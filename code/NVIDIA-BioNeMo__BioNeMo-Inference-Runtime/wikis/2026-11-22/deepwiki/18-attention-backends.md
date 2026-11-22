# Attention Backends

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [bionemo_ir/_torch/attention_backend/__init__.py](bionemo_ir/_torch/attention_backend/__init__.py)
- [bionemo_ir/_torch/attention_backend/pairwise_attention/__init__.py](bionemo_ir/_torch/attention_backend/pairwise_attention/__init__.py)
- [bionemo_ir/_torch/attention_backend/pairwise_attention/_config.py](bionemo_ir/_torch/attention_backend/pairwise_attention/_config.py)
- [bionemo_ir/_torch/attention_backend/triangle_attention/__init__.py](bionemo_ir/_torch/attention_backend/triangle_attention/__init__.py)
- [bionemo_ir/_torch/attention_backend/triangle_attention/_config.py](bionemo_ir/_torch/attention_backend/triangle_attention/_config.py)
- [bionemo_ir/_torch/attention_backend/triangle_attention/claude_kit.py](bionemo_ir/_torch/attention_backend/triangle_attention/claude_kit.py)
- [bionemo_ir/_torch/attention_backend/triangle_attention/configs/D32_sm100.json](bionemo_ir/_torch/attention_backend/triangle_attention/configs/D32_sm100.json)
- [bionemo_ir/_torch/attention_backend/triangle_attention/configs/D32_sm103.json](bionemo_ir/_torch/attention_backend/triangle_attention/configs/D32_sm103.json)
- [bionemo_ir/_torch/attention_backend/triangle_attention/configs/D32_sm90.json](bionemo_ir/_torch/attention_backend/triangle_attention/configs/D32_sm90.json)
- [bionemo_ir/_torch/attention_backend/triangle_attention/configs/D64_sm100.json](bionemo_ir/_torch/attention_backend/triangle_attention/configs/D64_sm100.json)
- [bionemo_ir/_torch/attention_backend/triangle_attention/configs/D64_sm103.json](bionemo_ir/_torch/attention_backend/triangle_attention/configs/D64_sm103.json)
- [bionemo_ir/_torch/attention_backend/triangle_attention/cuequiv.py](bionemo_ir/_torch/attention_backend/triangle_attention/cuequiv.py)
- [bionemo_ir/_torch/attention_backend/triangle_attention/cutedsl.py](bionemo_ir/_torch/attention_backend/triangle_attention/cutedsl.py)
- [bionemo_ir/_torch/attention_backend/triangle_attention/heuristic.py](bionemo_ir/_torch/attention_backend/triangle_attention/heuristic.py)
- [bionemo_ir/_torch/attention_backend/utils.py](bionemo_ir/_torch/attention_backend/utils.py)
- [bionemo_ir/_torch/attention_backend/window_attention/__init__.py](bionemo_ir/_torch/attention_backend/window_attention/__init__.py)
- [bionemo_ir/_torch/attention_backend/window_attention/_config.py](bionemo_ir/_torch/attention_backend/window_attention/_config.py)
- [bionemo_ir/_torch/attention_backend/window_attention/_cubin.py](bionemo_ir/_torch/attention_backend/window_attention/_cubin.py)
- [bionemo_ir/_torch/attention_backend/window_attention/configs/D32_W32_K128_sm100.json](bionemo_ir/_torch/attention_backend/window_attention/configs/D32_W32_K128_sm100.json)
- [bionemo_ir/_torch/attention_backend/window_attention/configs/D32_W32_K128_sm103.json](bionemo_ir/_torch/attention_backend/window_attention/configs/D32_W32_K128_sm103.json)
- [bionemo_ir/_torch/attention_backend/window_attention/configs/D32_W32_K128_sm80.json](bionemo_ir/_torch/attention_backend/window_attention/configs/D32_W32_K128_sm80.json)
- [bionemo_ir/_torch/attention_backend/window_attention/configs/D32_W32_K128_sm86.json](bionemo_ir/_torch/attention_backend/window_attention/configs/D32_W32_K128_sm86.json)
- [bionemo_ir/_torch/attention_backend/window_attention/configs/D32_W32_K128_sm89.json](bionemo_ir/_torch/attention_backend/window_attention/configs/D32_W32_K128_sm89.json)
- [bionemo_ir/_torch/attention_backend/window_attention/configs/D32_W32_K128_sm90.json](bionemo_ir/_torch/attention_backend/window_attention/configs/D32_W32_K128_sm90.json)
- [bionemo_ir/_torch/attention_backend/window_attention/cutedsl.py](bionemo_ir/_torch/attention_backend/window_attention/cutedsl.py)
- [bionemo_ir/_torch/custom_ops/adaln_layernorm_sigmoid/__init__.py](bionemo_ir/_torch/custom_ops/adaln_layernorm_sigmoid/__init__.py)
- [bionemo_ir/dsl_kernels/triton/rigid_align.py](bionemo_ir/dsl_kernels/triton/rigid_align.py)
- [cpp/kernels/cutedsl_triangle_attention/launcher.cpp](cpp/kernels/cutedsl_triangle_attention/launcher.cpp)
- [cpp/kernels/cutedsl_triangle_attention/launcher.h](cpp/kernels/cutedsl_triangle_attention/launcher.h)
- [tests/_torch/test_attention_backend.py](tests/_torch/test_attention_backend.py)
- [tests/_torch/test_pairformer.py](tests/_torch/test_pairformer.py)
- [tests/_torch/test_triangle_attention.py](tests/_torch/test_triangle_attention.py)
- [tests/_torch/test_triangle_attention_claude_kit.py](tests/_torch/test_triangle_attention_claude_kit.py)
- [tests/_torch/test_vanilla_attention.py](tests/_torch/test_vanilla_attention.py)

</details>



The BioNeMo Inference Runtime (BioIR) GPU kernel stack provides specialized attention backends optimized for structure-prediction models such as OpenFold and Boltz. These backends handle **triangle attention** (operating over pair representations with spatial/residue biases), **pairwise attention**, and **window attention** across various GPU architectures (Ampere SM80/86/89, Hopper SM90, and Blackwell SM100/103) [bionemo_ir/_torch/attention_backend/utils.py:37-128]().

This page serves as a high-level parent guide to the attention backend subsystem, covering core interface abstractions, implementation variants (vanilla PyTorch, SDPA, cuEquivariance, ClaudeKit, and CuTeDSL paths), and automated backend selection heuristics. For deep technical details on per-head-dim/per-SM JSON tuning tables, block sizes, thread counts, swizzling, and sequence buckets, see [Attention Kernel Tuning Configs](#5.1.1).

```mermaid
graph TD
    subgraph "NaturalLanguageSpace"
        A["Triangle Attention"] --> B["Vanilla Reference"]
        A --> C["PyTorch SDPA"]
        A --> D["cuEquivariance"]
        A --> E["CuTeDSL Left-Mask"]
        A --> F["ClaudeKit SM90 D=32"]
        A --> G["Heuristic Router"]
        
        H["Pairwise Attention"] --> I["Vanilla Reference"]
        H --> J["PyTorch SDPA"]
        H --> K["CuTeDSL Left-Mask"]
    end

    subgraph "CodeEntitySpace"
        B --> BT["VanillaTriangleAttention"]
        C --> ST["SDPATriangleAttention"]
        D --> CE["CuEquivAttention"]
        E --> CT["TriangleAttentionCuTeLeftMask"]
        F --> CK["ClaudeKitTriangleAttentionSM90D32"]
        G --> HT["HeuristicTriangleAttention"]
        
        I --> VP["VanillaPairwiseAttention"]
        J --> SP["SDPAPairwiseAttention"]
        K --> PT["PairwiseAttentionCuTeLeftMask"]
    end
    
    Sources: bionemo_ir/_torch/attention_backend/utils.py:24-32
```

---

## 1. Core Interfaces and Metadata Abstractions

All attention implementations inherit from the base `AttentionBackend` class, defining a standard forward signature that accepts queries, keys, values, optional bias tensors, and an `AttentionMetadata` container [bionemo_ir/_torch/attention_backend/interface.py:1-50]().

The attention subsystem supports primary logical categories defined by `AttentionType` [bionemo_ir/_torch/attention_backend/interface.py:15-25]():
* `AttentionType.TRIANGLE`: Operates on tensors shaped as `[*, I, J, H * D]` with row-wise single masks and shared triangle biases.
* `AttentionType.PAIRWISE`: Operates on pairwise representations with left-aligned KV masks.

```mermaid
graph TD
    subgraph "NaturalLanguageSpace"
        AB["Attention Backend Interface"] --> AT["Attention Type"]
        AB --> AM["Attention Metadata"]
    end

    subgraph "CodeEntitySpace"
        AB --> Base["AttentionBackend"]
        AT --> Enum["AttentionType"]
        AM --> Meta["AttentionMetadata"]
        Meta --> TCM["TriangleAttentionCuTeLeftMaskMetadata"]
        Meta --> PCM["PairwiseAttentionCuTeLeftMaskMetadata"]
        Meta --> CCM["ClaudeKitTriangleAttentionMetadata"]
    end

    Sources: bionemo_ir/_torch/attention_backend/interface.py:1-40
```

---

## 2. Triangle Attention Implementations

Triangle attention modules update residue pair representations and participate in Evoformer blocks. BioIR exposes multiple backend paths for triangle attention, resolvable via `get_attention_backend()` [bionemo_ir/_torch/attention_backend/utils.py:136-164]():

* **`VanillaTriangleAttention`**: A pure-PyTorch reference implementation using explicit matrix multiplication and softmax operations, useful for testing, debugging, and numerical validation [tests/_torch/test_vanilla_attention.py:91-120]().
* **`SDPATriangleAttention`**: Wraps PyTorch's native `F.scaled_dot_product_attention`, merging row biases and triangle bias into a unified attention mask [bionemo_ir/_torch/attention_backend/triangle_attention/sdpa.py:24-60]().
* **`CuEquivAttention`**: Integrates `cuequivariance_ops_torch` when available for specialized equivariant operations across supported architectures [bionemo_ir/_torch/attention_backend/utils.py:49-54]().
* **`TriangleAttentionCuTeLeftMask`**: High-performance CuTeDSL-based custom CUDA kernel path optimized for left-aligned pair masks on Ampere through Blackwell architectures [bionemo_ir/_torch/attention_backend/triangle_attention/cutedsl.py:15-32]().
* **`ClaudeKitTriangleAttentionSM90D32`**: Specialized Hopper SM90 D=32 kernel optimized for large attention score volumes [tests/_torch/test_attention_backend.py:43-55]().
* **`HeuristicTriangleAttention`**: Shape-based router that dynamically dispatches between `ClaudeKit`, `CuTeDSL`, and other backends based on batch size, token count, head dimension, and measured crossover thresholds [bionemo_ir/_torch/attention_backend/triangle_attention/heuristic.py:15-96]().

Sources: [bionemo_ir/_torch/attention_backend/utils.py:136-164](), [bionemo_ir/_torch/attention_backend/triangle_attention/heuristic.py:15-96]()

---

## 3. Pairwise Attention Implementations

Pairwise attention computes cross-attention or self-attention over sequence dimensions conditioned on pair features. Three backends are supported [bionemo_ir/_torch/attention_backend/utils.py:149-155]():

* **`VanillaPairwiseAttention`**: Pure-PyTorch implementation of pairwise attention with additive masking [bionemo_ir/_torch/attention_backend/pairwise_attention/vanilla.py]().
* **`SDPAPairwiseAttention`**: Optimized PyTorch SDPA wrapper for pairwise shapes [bionemo_ir/_torch/attention_backend/pairwise_attention/sdpa.py]().
* **`PairwiseAttentionCuTeLeftMask`**: CuTeDSL kernel launcher supporting left-aligned KV masks (`actual_s_kv`), handling packed QKV inputs and providing Hopper/Ampere dispatch [bionemo_ir/_torch/attention_backend/pairwise_attention/cutedsl.py]().

Sources: [bionemo_ir/_torch/attention_backend/utils.py:149-155]()

---

## 4. Window Attention Backends

Window attention restricts attention computation to local neighborhoods (windows) around query positions to reduce memory and compute overhead in large protein models. BioIR integrates CuTeDSL window attention kernels (`window_attention`, `window_attention_supported`) that serve `fp16` and `bf16` `D=32` heads in configurable window sizes over key sequences on SM80 through SM103 architectures [bionemo_ir/_torch/attention_backend/utils.py:110-134]().

Sources: [bionemo_ir/_torch/attention_backend/utils.py:110-134]()

---

## 5. Backend Selection Heuristics

To achieve optimal performance across different hardware targets, BioIR provides heuristic selection routines that inspect the GPU SM version, data types, and tensor dimensions [bionemo_ir/_torch/attention_backend/utils.py:37-134]():

* `auto_select_triangle_attention_backend(dtype, head_dim)`: Prioritizes `Heuristic` router for half-precision (`fp16`/`bf16`) on supported SM versions, falls back to `CUEQUIV` if available, and defaults to `SDPA` [bionemo_ir/_torch/attention_backend/utils.py:37-70]().
* `auto_select_pairwise_attention_backend(dtype)`: Selects `CuTeDSL` for half-precision on supported SM architectures, falling back to `SDPA` otherwise [bionemo_ir/_torch/attention_backend/utils.py:91-108]().
* `auto_select_window_attention_backend(...)`: Inspects device and window support to return `CuTeDSL` when compatible kernels serve the query/key configuration [bionemo_ir/_torch/attention_backend/utils.py:110-134]().

Sources: [bionemo_ir/_torch/attention_backend/utils.py:37-134]()

---

## 6. Kernel Tuning and Configuration

Tuned configurations, sequence bucket boundaries, tile shapes, and architecture-specific parameters for CuTeDSL triangle and pairwise attention kernels are stored in per-head-dim/per-SM JSON files [bionemo_ir/_torch/attention_backend/triangle_attention/_config.py:49-56]().

For detailed documentation on these tuning tables, block sizes, thread counts, swizzling, and sequence buckets, refer to the child page:
* [Attention Kernel Tuning Configs](#5.1.1)

Sources: [bionemo_ir/_torch/attention_backend/triangle_attention/_config.py:49-56]()

---