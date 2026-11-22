# Transformer Building Blocks

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [esm/layers/attention.py](esm/layers/attention.py)
- [esm/layers/blocks.py](esm/layers/blocks.py)
- [esm/layers/codebook.py](esm/layers/codebook.py)
- [esm/layers/rotary.py](esm/layers/rotary.py)
- [esm/layers/transformer_stack.py](esm/layers/transformer_stack.py)
- [esm/utils/misc.py](esm/utils/misc.py)

</details>



This page provides a technical reference for the reusable neural network layers and architectural components used across the ESM model families (ESM3 and ESMC). These blocks form the backbone of the protein language models, handling sequence processing, geometric reasoning, and structural prediction.

## Overview of Components

The ESM architecture relies on a hierarchical stack of transformer layers. The `TransformerStack` manages a sequence of `UnifiedTransformerBlock` instances, which can dynamically switch between standard multi-head attention and geometric attention.

### Natural Language to Code Entity Mapping

The following diagram maps high-level transformer concepts to their specific implementations in the `esm` codebase.

**Transformer Architecture Mapping**
```mermaid
graph TD
    subgraph "Conceptual Layer"
        A["Transformer Backbone"]
        B["Attention Mechanism"]
        C["Position Encoding"]
        D["Feed-Forward Network"]
        E["Prediction Head"]
    end

    subgraph "Code Entity (esm.layers)"
        A1["TransformerStack"]
        B1["MultiHeadAttention"]
        B2["FlashMultiHeadAttention"]
        B3["GeometricReasoningOriginalImpl"]
        C1["RotaryEmbedding"]
        C2["TritonRotaryEmbedding"]
        D1["SwiGLU"]
        D2["gelu_ln_ffn"]
        E1["RegressionHead"]
    end

    A --- A1
    B --- B1
    B --- B2
    B --- B3
    C --- C1
    C --- C2
    D --- D1
    D --- D2
    E --- E1
```
Sources: [esm/layers/transformer_stack.py:10-40](), [esm/layers/attention.py:16-144](), [esm/layers/blocks.py:15-115](), [esm/layers/rotary.py:68-108]()

---

## TransformerStack

The `TransformerStack` is the primary container for the model's depth. It initializes a series of transformer blocks and handles the distribution of inputs (sequence, structure frames, and masks) through the layers.

- **Residue Scaling**: To stabilize deep networks, it implements a `residue_scaling_factor` calculated as `sqrt(n_layers / 36)` [esm/layers/transformer_stack.py:50-52]().
- **Geometric Integration**: It allows a configurable number of initial layers (`n_layers_geom`) to include geometric attention [esm/layers/transformer_stack.py:32-48]().
- **Normalization**: Applies a final `nn.LayerNorm` after the last block [esm/layers/transformer_stack.py:62-62]().

Sources: [esm/layers/transformer_stack.py:10-116]()

---

## UnifiedTransformerBlock

The `UnifiedTransformerBlock` is a flexible layer that encapsulates the standard Transformer operations with optional geometric reasoning.

**Data Flow within UnifiedTransformerBlock**
```mermaid
graph TD
    Input["Input Tensor (x)"] --> LN1["LayerNorm (Implicit in Attn)"]
    LN1 --> Attn["MultiHeadAttention / FlashMHA"]
    Attn --> Add1["Residual Connection (x + r1 / scale)"]
    
    Add1 --> GeomAttn["GeometricReasoning (Optional)"]
    GeomAttn --> Add2["Residual Connection (x + r2 / scale)"]
    
    Add2 --> FFN["FFN (SwiGLU or GELU)"]
    FFN --> Add3["Residual Connection (x + r3 / scale)"]
    Add3 --> Output["Output Tensor"]
```

### Key Parameters
- `use_geom_attn`: If enabled, the block incorporates `GeometricReasoningOriginalImpl` for structure-aware processing [esm/layers/blocks.py:100-108]().
- `use_flash_attn`: Switches the attention implementation to `FlashMultiHeadAttention` for improved performance [esm/layers/blocks.py:91-98]().
- `ffn_type`: Supports "swiglu" (default for ESM3) or "gelu" [esm/layers/blocks.py:109-114]().

Sources: [esm/layers/blocks.py:51-165]()

---

## Attention Mechanisms

### MultiHeadAttention
The standard implementation uses `F.scaled_dot_product_attention` for efficiency while supporting manual attention weight extraction via `output_attentions=True` [esm/layers/attention.py:74-92](). It integrates `RotaryEmbedding` to handle relative positioning [esm/layers/attention.py:38-46]().

### FlashMultiHeadAttention
A specialized subclass optimized for speed and memory. It utilizes `flash_attn_varlen_qkvpacked_func` to handle variable-length sequences without padding overhead [esm/layers/attention.py:138-140](). It requires inputs to be pre-processed into unpadded tensors with cumulative sequence length indices (`cu_seqlens`) [esm/layers/attention.py:120-122]().

Sources: [esm/layers/attention.py:16-144]()

---

## Position Embeddings: RotaryEmbedding

ESM models use Rotary Positional Embeddings (RoPE) to inject relative position information.

- **RotaryEmbedding**: Implements the standard RoPE logic using PyTorch tensors. It caches `cos` and `sin` frequencies to accelerate the forward pass [esm/layers/rotary.py:118-122]().
- **TritonRotaryEmbedding**: A high-performance variant used in conjunction with Flash Attention, leveraging Triton kernels for the rotation operation [esm/layers/attention.py:108-109]().

Sources: [esm/layers/rotary.py:68-160](), [esm/layers/attention.py:108-109]()

---

## Feed-Forward Networks (FFN)

### SwiGLU FFN
The preferred FFN for modern ESM models. It uses the `SwiGLU` activation function, which splits the input and applies SiLU to one half before multiplication [esm/layers/blocks.py:25-28]().

- **Correction Function**: The `swiglu_correction_fn` ensures the hidden dimension is a multiple of 256 for hardware alignment [esm/layers/blocks.py:10-12]().
- **Structure**: Composed of a `LayerNorm`, a `Linear` layer expanding to `2 * hidden_dim`, the `SwiGLU` activation, and a final `Linear` projection back to `d_model` [esm/layers/blocks.py:30-38]().

### GELU FFN
A standard alternative using the Gaussian Error Linear Unit activation [esm/layers/blocks.py:41-49]().

Sources: [esm/layers/blocks.py:10-50]()

---

## RegressionHead

The `RegressionHead` is a conceptual component representing a module that takes the output of the `TransformerStack` and produces continuous predictions. While not explicitly defined as a single class named `RegressionHead` in the provided files, its functionality is typically implemented as an `nn.Module` that processes the transformer's hidden states for tasks like pLDDT prediction or other continuous value estimations. It usually consists of an MLP with `LayerNorm` and non-linearities.

**Conceptual Data Flow for RegressionHead**
```mermaid
graph TD
    TS_Output["TransformerStack Output (x)"] --> LN_Reg["LayerNorm"]
    LN_Reg --> Linear1["Linear Layer 1"]
    Linear1 --> Activation["Activation (e.g., GELU)"]
    Activation --> Linear2["Linear Layer 2"]
    Linear2 --> Output["Regression Output"]
```

| Component | Description |
| :--- | :--- |
| **Input** | Hidden states from the Transformer (post-norm output of `TransformerStack`). |
| **Structure** | Typically a multi-layer perceptron (MLP) with `LayerNorm` and non-linearities. |
| **Output** | Scalar values per residue or per protein, depending on the task. |

Sources: [esm/layers/transformer_stack.py:115-116]() (Context of `TransformerStack` output usage, which would feed into such a head).

---