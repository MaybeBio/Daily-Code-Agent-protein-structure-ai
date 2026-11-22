# SDK API Contracts – ESMProtein & Inference Clients

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [esm/sdk/api.py](esm/sdk/api.py)

</details>



This page documents the core data models and abstract client interfaces that form the foundation of the ESM SDK. These contracts ensure consistency across different execution backends, such as local PyTorch models, Biohub Forge (remote API), and AWS SageMaker.

## Core Data Models

The SDK uses two primary representations for protein data: `ESMProtein` (high-level, human-readable) and `ESMProteinTensor` (low-level, tokenized).

### ESMProtein
`ESMProtein` is the primary interface for users to interact with protein data. it stores raw sequences, structure coordinates, and metadata such as function annotations [esm/sdk/api.py:26-54]().

| Field | Type | Description |
| :--- | :--- | :--- |
| `sequence` | `str \| None` | Amino acid sequence (1-letter codes). |
| `secondary_structure` | `str \| None` | SS8 or SS3 labels. |
| `sasa` | `list[float] \| None` | Solvent Accessible Surface Area values. |
| `function_annotations` | `list[FunctionAnnotation]` | InterPro labels with start/end positions. |
| `coordinates` | `torch.Tensor \| None` | Atom37 format coordinates [L, 37, 3]. |
| `plddt` | `torch.Tensor \| None` | Per-residue confidence scores. |
| `ptm` | `torch.Tensor \| None` | Predicted TM-score. |
| `pae` | `torch.Tensor \| None` | Predicted Alignment Error. |
| `crmsd` | `torch.Tensor \| None` | C-alpha RMSD. |
| `globularity` | `torch.Tensor \| None` | Globularity score. |
| `interface_annotations` | `list[str] \| None` | Annotations related to protein interfaces. |
| `interface_ptm` | `torch.Tensor \| None` | Interface PTM score. |
| `pair_chains_iptm` | `torch.Tensor \| None` | Pairwise chain iPTM scores. |
| `output_embedding_sequence` | `torch.Tensor \| None` | Sequence-level output embedding. |
| `output_embedding_pair_pooled` | `torch.Tensor \| None` | Pair-pooled output embedding. |
| `residue_index` | `torch.Tensor \| None` | Original residue indices. |
| `entity_id` | `torch.Tensor \| None` | Entity IDs for multi-chain complexes. |
| `potential_sequence_of_concern` | `bool` | Flag for sequences that may have concerns. |

**Key Methods:**
* `from_pdb()`: Loads protein data from a PDB file [esm/sdk/api.py:69-94]().
* `to_pdb()`: Exports the current state (sequence + coordinates) to a PDB file [esm/sdk/api.py:138-142]().
* `from_protein_chain()`: Converts a `ProteinChain` object to `ESMProtein` [esm/sdk/api.py:97-117]().
* `from_protein_complex()`: Converts a `ProteinComplex` object to `ESMProtein` [esm/sdk/api.py:119-137]().
* `to_protein_chain()`: Converts `ESMProtein` to a `ProteinChain` object [esm/sdk/api.py:148-163]().
* `to_protein_complex()`: Converts `ESMProtein` to a `ProteinComplex` object [esm/sdk/api.py:165-201]().

### ESMProteinTensor
`ESMProteinTensor` represents a protein after it has been processed by a tokenizer. It holds discrete integer tokens for each track, making it ready for model consumption [esm/sdk/api.py:204-230]().

| Field | Type | Description |
| :--- | :--- | :--- |
| `sequence_tokens` | `torch.Tensor \| None` | Tokenized amino acid sequence. |
| `secondary_structure_tokens` | `torch.Tensor \| None` | Tokenized secondary structure. |
| `sasa_tokens` | `torch.Tensor \| None` | Tokenized SASA values. |
| `function_annotation_tokens` | `torch.Tensor \| None` | Tokenized function annotations. |
| `coordinates` | `torch.Tensor \| None` | Atom37 format coordinates [L, 37, 3]. |
| `plddt` | `torch.Tensor \| None` | Per-residue confidence scores. |
| `ptm` | `torch.Tensor \| None` | Predicted TM-score. |
| `pae` | `torch.Tensor \| None` | Predicted Alignment Error. |
| `crmsd` | `torch.Tensor \| None` | C-alpha RMSD. |
| `globularity` | `torch.Tensor \| None` | Globularity score. |
| `interface_annotations` | `list[str] \| None` | Annotations related to protein interfaces. |
| `interface_ptm` | `torch.Tensor \| None` | Interface PTM score. |
| `pair_chains_iptm` | `torch.Tensor \| None` | Pairwise chain iPTM scores. |
| `output_embedding_sequence` | `torch.Tensor \| None` | Sequence-level output embedding. |
| `output_embedding_pair_pooled` | `torch.Tensor \| None` | Pair-pooled output embedding. |
| `residue_index` | `torch.Tensor \| None` | Original residue indices. |
| `entity_id` | `torch.Tensor \| None` | Entity IDs for multi-chain complexes. |
| `potential_sequence_of_concern` | `bool` | Flag for sequences that may have concerns. |

### Data Flow: Natural Language to Code Entity Space

The following diagram illustrates how raw protein data (Natural Language/Physical Space) is mapped to the SDK's internal code entities.

**Protein Representation Mapping**
```mermaid
graph TD
    subgraph "Natural Language / Physical Space"
        PDB["PDB File (1UTN.pdb)"]
        SEQ["Amino Acid String (MKT...)"]
        ANNOT["InterPro Label (Peptidase)"]
    end

    subgraph "Code Entity Space (esm.sdk.api)"
        ESMP["ESMProtein Class"]
        ESMPT["ESMProteinTensor Class"]
        FA["FunctionAnnotation Class"]
    end

    PDB -->|"ESMProtein.from_pdb()"| ESMP
    SEQ -->|"ESMProtein(sequence=...)"| ESMP
    ANNOT -->|"FunctionAnnotation(label=...)"| FA
    FA -->|"protein.function_annotations"| ESMP
    ESMP -->|"client.encode()"| ESMPT
```
Sources: [esm/sdk/api.py:26-54](), [esm/sdk/api.py:69-94](), [esm/sdk/api.py:204-230](), [esm/sdk/api.py:97-117](), [esm/sdk/api.py:119-137](), [esm/sdk/api.py:148-163](), [esm/sdk/api.py:165-201]()

---

## Inference Client Interfaces

The SDK defines abstract base classes (ABCs) that specify the methods any ESM inference backend must implement.

### ESM3InferenceClient
The ESM3 client supports multimodal generation, encoding, and decoding across multiple tracks (sequence, structure, function, etc.) [esm/sdk/api.py:461-558]().

| Method | Description |
| :--- | :--- |
| `encode(protein)` | Converts `ESMProtein` to `ESMProteinTensor` using internal tokenizers [esm/sdk/api.py:476](). |
| `decode(tensor)` | Converts `ESMProteinTensor` back to `ESMProtein` (reconstructs coordinates/sequences) [esm/sdk/api.py:483](). |
| `generate(input, config)` | Performs iterative masked generation for a specific track [esm/sdk/api.py:490](). |
| `logits(input, config)` | Returns raw log-probabilities and optionally hidden embeddings [esm/sdk/api.py:516](). |
| `forward_and_sample(input, config)` | Single-step forward pass followed by sampling [esm/sdk/api.py:530](). |

### ESMCInferenceClient
The ESMC client is specialized for sequence-only embeddings and masked language modeling tasks [esm/sdk/api.py:612-638]().

| Method | Description |
| :--- | :--- |
| `encode(sequence)` | Tokenizes a raw string sequence [esm/sdk/api.py:617](). |
| `logits(input, config)` | Returns sequence logits and embeddings [esm/sdk/api.py:623]().

### Client Interaction Lifecycle

This diagram bridges the functional requirements of protein generation to the specific methods in the `ESM3InferenceClient`.

**ESM3 Generation Lifecycle**
```mermaid
sequenceDiagram
    participant User
    participant Client as ESM3InferenceClient
    participant Forge as Forge/Remote Backend

    User->>Client: encode(ESMProtein)
    Client-->>User: ESMProteinTensor
    User->>Client: generate(ESMProteinTensor, GenerationConfig)
    Client->>Forge: POST /generate (Serialized Tokens)
    Forge-->>Client: Updated Tokens
    Client-->>User: ESMProteinTensor (Generated)
    User->>Client: decode(ESMProteinTensor)
    Client-->>User: ESMProtein (Final Structure/Seq)
```
Sources: [esm/sdk/api.py:461-558]()

---

## Configuration Objects

The behavior of the inference clients is controlled via standardized configuration dataclasses.

### GenerationConfig
Controls the iterative sampling process [esm/sdk/api.py:335-349]().
* `track`: Which track to generate (`"sequence"`, `"structure"`, `"function"`, etc.) [esm/sdk/api.py:336]().
* `num_steps`: Number of iterative refinement steps [esm/sdk/api.py:337]().
* `temperature`: Sampling temperature (0.0 for greedy) [esm/sdk/api.py:338]().
* `schedule`: Noise schedule (e.g., `"cosine"`, `"linear"`) [esm/sdk/api.py:339]().
* `unmask_strategy`: Strategy for unmasking tokens (e.g., `"random"`, `"entropy"`) [esm/sdk/api.py:340]().
* `top_k`: Top-k sampling [esm/sdk/api.py:341]().
* `top_p`: Top-p (nucleus) sampling [esm/sdk/api.py:342]().
* `guided_decoding_config`: Configuration for guided decoding [esm/sdk/api.py:343]().
* `constraint_config`: Configuration for constrained generation [esm/sdk/api.py:344]().
* `return_intermediate_steps`: Whether to return intermediate steps of generation [esm/sdk/api.py:345]().
* `return_logits`: Whether to return logits for generated tokens [esm/sdk/api.py:346]().
* `return_embeddings`: Whether to return embeddings for generated tokens [esm/sdk/api.py:347]().
* `return_attention`: Whether to return attention weights [esm/sdk/api.py:348]().
* `return_sae_features`: Whether to return SAE features [esm/sdk/api.py:349]().

### SamplingConfig & LogitsConfig
* `SamplingConfig`: Nested configuration per track (sequence, structure, etc.) for `forward_and_sample` [esm/sdk/api.py:312-326]().
    * `sequence_sampling_config`: Configuration for sequence sampling [esm/sdk/api.py:313]().
    * `structure_sampling_config`: Configuration for structure sampling [esm/sdk/api.py:314]().
    * `sasa_sampling_config`: Configuration for SASA sampling [esm/sdk/api.py:315]().
    * `secondary_structure_sampling_config`: Configuration for secondary structure sampling [esm/sdk/api.py:316]().
    * `function_annotation_sampling_config`: Configuration for function annotation sampling [esm/sdk/api.py:317]().
    * `temperature`: Sampling temperature [esm/sdk/api.py:318]().
    * `top_k`: Top-k sampling [esm/sdk/api.py:319]().
    * `top_p`: Top-p (nucleus) sampling [esm/sdk/api.py:320]().
    * `return_logits`: Whether to return logits [esm/sdk/api.py:321]().
    * `return_embeddings`: Whether to return embeddings [esm/sdk/api.py:322]().
    * `return_attention`: Whether to return attention weights [esm/sdk/api.py:323]().
    * `return_sae_features`: Whether to return SAE features [esm/sdk/api.py:324]().
    * `sae_config`: SAE configuration [esm/sdk/api.py:325]().
* `LogitsConfig`: Boolean flags to toggle logit/embedding returns for specific tracks [esm/sdk/api.py:361-375]().
    * `return_sequence_logits`: Whether to return sequence logits [esm/sdk/api.py:362]().
    * `return_structure_logits`: Whether to return structure logits [esm/sdk/api.py:363]().
    * `return_sasa_logits`: Whether to return SASA logits [esm/sdk/api.py:364]().
    * `return_secondary_structure_logits`: Whether to return secondary structure logits [esm/sdk/api.py:365]().
    * `return_function_annotation_logits`: Whether to return function annotation logits [esm/sdk/api.py:366]().
    * `return_sequence_embeddings`: Whether to return sequence embeddings [esm/sdk/api.py:367]().
    * `return_pair_pooled_embeddings`: Whether to return pair-pooled embeddings [esm/sdk/api.py:368]().
    * `return_attention`: Whether to return attention weights [esm/sdk/api.py:369]().
    * `return_sae_features`: Whether to return SAE features [esm/sdk/api.py:370]().
    * `sae_config`: SAE configuration [esm/sdk/api.py:371]().
    * `return_plddt`: Whether to return pLDDT scores [esm/sdk/api.py:372]().
    * `return_ptm`: Whether to return PTM scores [esm/sdk/api.py:373]().
    * `return_pae`: Whether to return PAE scores [esm/sdk/api.py:374]().
    * `return_crmsd`: Whether to return cRMSD scores [esm/sdk/api.py:375]().

### SAEConfig
Used for Sparse Autoencoder (SAE) feature extraction in ESMC models [esm/sdk/api.py:440-447]().
* `sae_id`: Identifier for the specific SAE version (e.g., `"esmc-600m-v1-residue-sae"`) [esm/sdk/api.py:441]().
* `hook_layer`: The model layer to hook for feature extraction [esm/sdk/api.py:442]().
* `return_activations`: Whether to return raw SAE activations [esm/sdk/api.py:443]().
* `return_decoded_activations`: Whether to return decoded SAE activations [esm/sdk/api.py:444]().
* `return_feature_densities`: Whether to return feature densities [esm/sdk/api.py:445]().
* `return_feature_sparsity`: Whether to return feature sparsity [esm/sdk/api.py:446]().
* `return_feature_indices`: Whether to return indices of active features [esm/sdk/api.py:447]().

Sources: [esm/sdk/api.py:312-349](), [esm/sdk/api.py:361-375](), [esm/sdk/api.py:440-447]()

---

## Batch Execution & Rate Limiting

The SDK provides a `ForgeBatchExecutor` to handle high-throughput requests to the Biohub Platform. It implements an **AIMD (Additive Increase/Multiplicative Decrease)** rate limiter to dynamically adjust concurrency based on server response codes (e.g., HTTP 429) [esm/utils/forge_context_manager.py:18-45]().

**Usage Example:**
```python
with batch_executor(max_workers=32) as executor:
    results = executor.execute_batch(client.generate, prompts, configs)
```
Sources: [esm/sdk/__init__.py:73-83](), [esm/utils/forge_context_manager.py:46-86]()

---