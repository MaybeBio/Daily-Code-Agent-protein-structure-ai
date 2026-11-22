# ESM3 – Multimodal Protein Language Model

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [esm/models/esm3.py](esm/models/esm3.py)
- [esm/models/function_decoder.py](esm/models/function_decoder.py)
- [esm/pretrained.py](esm/pretrained.py)
- [esm/utils/structure/affine3d.py](esm/utils/structure/affine3d.py)

</details>



ESM3 is a multimodal generative protein language model capable of reasoning across sequence, structure, and functional annotations. It is implemented as a transformer-based architecture that integrates multiple data tracks into a unified latent space, enabling tasks such as structure prediction, inverse folding, and functional design.

## ESM3 Architecture Overview

The `ESM3` class in `esm/models/esm3.py` serves as the primary implementation of the model. It inherits from `nn.Module` and implements the `ESM3InferenceClient` interface [esm/models/esm3.py:188-188](). The architecture consists of three main stages:
1.  **Input Encoding**: Projecting multimodal tracks (sequence, structure tokens, etc.) into a shared embedding.
2.  **Transformer Backbone**: A stack of unified transformer blocks supporting both standard and geometric attention.
3.  **Output Heads**: Regressing logits for each track from the final transformer hidden states.

### Data Flow and Code Entity Mapping

The following diagram maps the high-level multimodal data flow to the specific classes and modules within the ESM3 codebase.

**ESM3 Multimodal Pipeline**
```mermaid
graph TD
    subgraph InputSpace ["Input Space (ESMProteinTensor)"]
        SEQ["sequence_tokens"]
        STR["structure_tokens"]
        SS8["ss8_tokens"]
        SASA["sasa_tokens"]
        FUNC["function_tokens"]
        RES["residue_annotation_tokens"]
        AVG_PLDDT["average_plddt"]
        PER_RES_PLDDT["per_res_plddt"]
    end

    subgraph Encoder ["esm.models.esm3.EncodeInputs"]
        EI["EncodeInputs.forward()"]
        EMB_SEQ["sequence_embed (nn.Embedding)"]
        EMB_STR["structure_tokens_embed (nn.Embedding)"]
        EMB_SS8["ss8_embed (nn.Embedding)"]
        EMB_SASA["sasa_embed (nn.Embedding)"]
        EMB_FUNC["function_embed (nn.ModuleList)"]
        EMB_RES["residue_embed (nn.EmbeddingBag)"]
        PROJ_PLDDT["plddt_projection (nn.Linear)"]
        PROJ_PER_RES_PLDDT["structure_per_res_plddt_projection (nn.Linear)"]
    end

    subgraph Backbone ["esm.layers.transformer_stack.TransformerStack"]
        TS["TransformerStack.forward()"]
        UTB["UnifiedTransformerBlock"]
        GA["GeometricReasoningOriginalImpl"]
    end

    subgraph Heads ["esm.models.esm3.OutputHeads"]
        OH["OutputHeads.forward()"]
        RH_SEQ["sequence_head (RegressionHead)"]
        RH_STR["structure_head (RegressionHead)"]
        RH_SS8["ss8_head (RegressionHead)"]
        RH_SASA["sasa_head (RegressionHead)"]
        RH_FUNC["function_head (RegressionHead)"]
        RH_RES["residue_head (RegressionHead)"]
    end

    SEQ --> EMB_SEQ
    STR --> EMB_STR
    SS8 --> EMB_SS8
    SASA --> EMB_SASA
    FUNC --> EMB_FUNC
    RES --> EMB_RES
    AVG_PLDDT --> PROJ_PLDDT
    PER_RES_PLDDT --> PROJ_PER_RES_PLDDT

    EMB_SEQ --> EI
    EMB_STR --> EI
    EMB_SS8 --> EI
    EMB_SASA --> EI
    EMB_FUNC --> EI
    EMB_RES --> EI
    PROJ_PLDDT --> EI
    PROJ_PER_RES_PLDDT --> EI

    EI -- "Summed Embeddings" --> TS
    TS -- "x (Post-Norm)" --> OH
    OH --> ESMO["ESMOutput"]

    Sources: [esm/models/esm3.py:62-148](), [esm/layers/transformer_stack.py:10-116](), [esm/models/esm3.py:151-185]()
```

**Sources:** [esm/models/esm3.py:62-185](), [esm/layers/transformer_stack.py:10-116]()

---

## Input Encoding (EncodeInputs)

The `EncodeInputs` module handles the initial projection of eight distinct tracks into a single $d_{model}$ vector per residue [esm/models/esm3.py:62-70]().

| Track | Token Source | Encoding Mechanism |
| :--- | :--- | :--- |
| **Sequence** | Amino Acid Tokens | `nn.Embedding(64, d_model)` [esm/models/esm3.py:74-74]() |
| **Structure** | VQ-VAE Tokens | `nn.Embedding(4096 + 5, d_model)` [esm/models/esm3.py:80-80]() |
| **SS8** | Secondary Structure | `nn.Embedding(8 + 3, d_model)` [esm/models/esm3.py:83-83]() |
| **SASA** | Solvent Accessibility | `nn.Embedding(16 + 3, d_model)` [esm/models/esm3.py:84-84]() |
| **Function** | InterPro LSH | `nn.ModuleList` of 8 `nn.Embedding` (dim $d/8$) [esm/models/esm3.py:87-89]() |
| **Residue** | Annotations | `nn.EmbeddingBag(1478, d_model, mode="sum", padding_idx=0)` [esm/models/esm3.py:91-91]() |
| **pLDDT** | Global/Per-Res | RBF kernels + `nn.Linear` projection [esm/models/esm3.py:106-112]() |

The forward pass sums these embeddings element-wise:
$$X_{input} = E_{seq} + E_{struct} + E_{ss8} + E_{sasa} + E_{func} + E_{res} + E_{plddt\_avg} + E_{plddt\_per\_res}$$
[esm/models/esm3.py:139-148]()

**Sources:** [esm/models/esm3.py:62-148]()

---

## Transformer Backbone and Geometric Conditioning

The backbone is a `TransformerStack` composed of `UnifiedTransformerBlock` layers [esm/models/esm3.py:212-212]().

### UnifiedTransformerBlock
Each block can perform two types of attention:
1.  **Standard Attention**: Multi-head attention (optionally using `FlashMultiHeadAttention`).
2.  **Geometric Attention**: Enabled via `use_geom_attn`. It uses `GeometricReasoningOriginalImpl` to incorporate 3D spatial relationships.

### Affine3D Conditioning
Geometric attention is conditioned on `Affine3D` frames, which represent the local coordinate system (orientation and position) of each residue [esm/models/esm3.py:255-265](). These frames are built from backbone coordinates during the forward pass using `build_affine3d_from_coordinates` [esm/utils/structure/affine3d.py:290-300]().

**Sources:** [esm/models/esm3.py:212-212](), [esm/models/esm3.py:255-265](), [esm/utils/structure/affine3d.py:290-300]()

---

## Output Heads and ESMOutput

The `OutputHeads` module contains `RegressionHead` instances for each input track [esm/models/esm3.py:151-160]().

*   **RegressionHead**: A standard block consisting of a Linear layer, GELU activation, LayerNorm, and a final Linear projection to the vocabulary size [esm/layers/regression_head.py:13-20]().
*   **ESMOutput**: A dataclass that aggregates the resulting logits for sequence, structure, SS8, SASA, function, and residue tracks, along with the final embeddings and optional attention weights [esm/models/esm3.py:50-59]().

**Sources:** [esm/models/esm3.py:50-59](), [esm/models/esm3.py:151-185](), [esm/layers/regression_head.py:13-20]()

---

## Pretrained Factory Functions

ESM3 models are typically instantiated using factory functions in `esm/pretrained.py` which handle architecture configuration and weight loading.

**Model Loading Logic**
```mermaid
graph LR
    subgraph Registry ["esm.pretrained.LOCAL_MODEL_REGISTRY"]
        R1["ESM3_OPEN_SMALL"]
    end

    subgraph Builder ["esm.pretrained.ESM3_sm_open_v0"]
        B1["Initialize ESM3 Architecture"]
        B2["Load weights (esm3_sm_open_v1.pth)"]
        B3["Attach Tokenizers"]
    end

    subgraph SubComponents ["Component Builders"]
        SE["ESM3_structure_encoder_v0"]
        SD["ESM3_structure_decoder_v0"]
        FD["ESM3_function_decoder_v0"]
    end

    R1 --> B1
    B1 --> SE
    B1 --> SD
    B1 --> FD
    B2 --> B3
    B3 --> Final["ESM3 Model Instance"]

    Sources: [esm/pretrained.py:108-136]()
```

Key factory functions include:
*   `ESM3_sm_open_v0`: Loads the open-source small ESM3 model (1.4B parameters, 48 layers, $d_{model}=1536$) [esm/pretrained.py:108-125]().
*   `ESM3_structure_encoder_v0` / `ESM3_structure_decoder_v0`: Loads the VQ-VAE components for structural tokenization [esm/pretrained.py:28-51]().
*   `ESM3_function_decoder_v0`: Loads the decoder for InterPro and keyword prediction [esm/pretrained.py:54-63]().

**Sources:** [esm/pretrained.py:28-136]()

---

## Forward Pass Implementation

The `ESM3.forward()` method orchestrates the multimodal data flow [esm/models/esm3.py:238-306]():

1.  **Coordinate Processing**: If raw coordinates are provided, it builds `Affine3D` frames and calculates per-residue pLDDT [esm/models/esm3.py:255-265]().
2.  **Encoding**: Calls `self.encoder` to generate the initial latent representation [esm/models/esm3.py:276-286]().
3.  **Transformer Stack**: Passes the embeddings through `self.transformer`, applying geometric attention if structural frames are present [esm/models/esm3.py:288-295]().
4.  **Heads**: Passes the transformer output to `self.heads` to generate `ESMOutput` [esm/models/esm3.py:297-306]().

**Sources:** [esm/models/esm3.py:238-306]()

---