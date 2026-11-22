# Encoding, Decoding & Generation Pipeline

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [esm/utils/decoding.py](esm/utils/decoding.py)
- [esm/utils/encoding.py](esm/utils/encoding.py)
- [esm/utils/generation.py](esm/utils/generation.py)
- [esm/utils/sampling.py](esm/utils/sampling.py)

</details>



The ESM3 ecosystem revolves around a unified pipeline that converts high-level protein descriptions into discrete tensor representations, performs iterative generation via masked language modeling, and decodes those tensors back into physically realizable protein structures and annotations. This lifecycle is managed by the `ESM3InferenceClient` and supported by specialized utility modules in `esm.utils`.

### High-Level Pipeline Flow

The pipeline operates across three primary stages:
1.  **Encoding**: Converting an `ESMProtein` object (containing sequences, coordinates, and labels) into an `ESMProteinTensor` using track-specific tokenizers and VQ-VAE encoders.
2.  **Generation**: Using the transformer backbone to fill in masked tokens across multiple tracks (sequence, structure, function, etc.) through iterative sampling.
3.  **Decoding**: Converting the predicted `ESMProteinTensor` back into an `ESMProtein` object, which involves backbone reconstruction from structure tokens and keyword extraction from function tokens.

### Data Flow Diagram

The following diagram maps the conceptual pipeline stages to the specific code entities and data structures used in the ESM repository.

**Pipeline Entity Mapping**
```mermaid
graph TD
    subgraph "Input Space"
        P["ESMProtein (esm/sdk/api.py)"]
    end

    subgraph "Encoding Logic (esm/utils/encoding.py)"
        TE["StructureTokenEncoder (esm/models/vqvae.py)"]
        TC["TokenizerCollection (esm/tokenization/collection.py)"]
        EF["encode_function_annotations (esm/utils/function/encode_decode.py)"]
    end

    subgraph "Tensor Space"
        EPT["ESMProteinTensor (esm/sdk/api.py)"]
    end

    subgraph "Generation Logic (esm/utils/generation.py)"
        IS["iterative_sampling_raw (esm/utils/generation.py)"]
        SL["sample_logits (esm/utils/sampling.py)"]
        NS["NOISE_SCHEDULE_REGISTRY (esm/utils/noise_schedules.py)"]
    end

    subgraph "Decoding Logic (esm/utils/decoding.py)"
        TD["StructureTokenDecoder (esm/models/vqvae.py)"]
        FD["FunctionTokenDecoder (esm/models/function_decoder.py)"]
        DPT["decode_protein_tensor (esm/utils/decoding.py)"]
    end

    P -->|encode| TC
    TC --> TE
    TE --> EF
    EF --> EPT
    EPT --> IS
    IS --> SL
    SL --> NS
    NS --> EPT
    EPT -->|decode| DPT
    DPT --> TD
    DPT --> FD
    TD --> P
    FD --> P
```
**Sources:** [esm/sdk/api.py:11-21](), [esm/utils/encoding.py:144-152](), [esm/utils/decoding.py:31-36](), [esm/utils/generation.py:99-103]()

---

### 6.1 Encoding Proteins into Tensors
The encoding phase transforms human-readable protein data into the discrete multi-track format required by ESM3. This process involves:
*   **Sequence Tokenization**: Mapping amino acids to vocabulary indices using `tokenize_sequence` [esm/utils/encoding.py:35-45]().
*   **Structure Quantization**: Using the `StructureTokenEncoder` [esm/models/vqvae.py:6]() via `tokenize_structure` [esm/utils/encoding.py:48-97]() to map 3D coordinates into discrete structure tokens.
*   **Function Encoding**: Converting `FunctionAnnotation` objects into multi-depth tensors using `encode_function_annotations` [esm/utils/function/encode_decode.py:13-19]() and `tokenize_function_annotations` [esm/utils/encoding.py:138-152]().
*   **Special Tokens**: Automatic addition of `BOS` (Beginning of Sequence) and `EOS` (End of Sequence) tokens to every track, as seen in `get_default_sequence_tokens` [esm/utils/encoding.py:156-169]().

For details, see [Encoding Proteins into Tensors](#6.1).

**Sources:** [esm/utils/encoding.py:35-45](), [esm/models/vqvae.py:6](), [esm/utils/encoding.py:48-97](), [esm/utils/function/encode_decode.py:13-19](), [esm/utils/encoding.py:138-152](), [esm/utils/encoding.py:156-169]()

---

### 6.2 Decoding Tensors Back to Proteins
Decoding is the inverse process, reconstructing physical properties from model outputs. Key components include:
*   **Backbone Reconstruction**: The `StructureTokenDecoder` [esm/models/vqvae.py:10]() converts structure tokens back into 3D coordinates via `decode_structure` [esm/utils/decoding.py:138-169](). The pipeline then uses `ProteinChain.infer_oxygen()` [esm/utils/decoding.py:168]() to complete the backbone.
*   **Annotation Merging**: `decode_function_tokens` [esm/utils/function/encode_decode.py:84-91]() uses a `FunctionTokenDecoder` [esm/models/function_decoder.py:9]() to convert high-dimensional logits into a list of `FunctionAnnotation` objects.
*   **Metric Extraction**: The decoder extracts confidence metrics like `pLDDT`, `pTM`, and `PAE` directly from the structure decoder's output [esm/utils/decoding.py:159-165]().

For details, see [Decoding Tensors Back to Proteins](#6.2).

**Sources:** [esm/models/vqvae.py:10](), [esm/utils/decoding.py:138-169](), [esm/utils/decoding.py:168](), [esm/utils/function/encode_decode.py:84-91](), [esm/models/function_decoder.py:9](), [esm/utils/decoding.py:159-165]()

---

### 6.3 Iterative Masked Generation
Generation in ESM3 is an iterative process where the model unmasks tokens over a series of steps. The `iterative_sampling_raw` function [esm/utils/generation.py:99-128]() orchestrates this by:
*   **Noise Scheduling**: Determining the unmasking rate using schedules like `cosine`, `linear`, or `cubic` from the `NOISE_SCHEDULE_REGISTRY` [esm/utils/noise_schedules.py:1]().
*   **Multi-Track Sampling**: Simultaneously sampling sequence, structure, and function tracks using functions like `sample_logits` [esm/utils/sampling.py:153-197](), `sample_function_logits` [esm/utils/sampling.py:201-206](), and `sample_residue_annotation_logits` [esm/utils/sampling.py:208-213]() while maintaining consistency between them.
*   **Temperature Control**: Applying sampling temperatures defined in `SamplingTrackConfig` [esm/sdk/api.py:20]() to control the diversity of the generated proteins.

For details, see [Iterative Masked Generation](#6.3).

**Sources:** [esm/utils/generation.py:99-128](), [esm/utils/noise_schedules.py:1](), [esm/utils/sampling.py:153-197](), [esm/utils/sampling.py:201-206](), [esm/utils/sampling.py:208-213](), [esm/sdk/api.py:20]()

---

### Utility Entity Association
This table bridges the high-level pipeline concepts to the specific classes and functions implemented in the codebase.

| Pipeline Stage | Code Entity | File Path |
| :--- | :--- | :--- |
| **Encoding** | `tokenize_structure` | [esm/utils/encoding.py:48]() |
| **Encoding** | `encode_function_annotations` | [esm/utils/function/encode_decode.py:13]() |
| **Generation** | `iterative_sampling_raw` | [esm/utils/generation.py:99]() |
| **Generation** | `get_sampling_mask` | [esm/utils/sampling.py:29]() |
| **Decoding** | `decode_protein_tensor` | [esm/utils/decoding.py:31]() |
| **Decoding** | `decode_structure` | [esm/utils/decoding.py:138]()

**Sources:** [esm/utils/encoding.py:48-54](), [esm/utils/function/encode_decode.py:13-19](), [esm/utils/generation.py:99-103](), [esm/utils/sampling.py:29](), [esm/utils/decoding.py:31-36](), [esm/utils/decoding.py:138-143]()

---