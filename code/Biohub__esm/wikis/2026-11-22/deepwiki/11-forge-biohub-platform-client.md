# Forge / Biohub Platform Client

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [esm/sdk/base_forge_client.py](esm/sdk/base_forge_client.py)
- [esm/sdk/forge.py](esm/sdk/forge.py)
- [esm/sdk/retry.py](esm/sdk/retry.py)
- [esm/utils/constants/api.py](esm/utils/constants/api.py)
- [esm/utils/forge_context_manager.py](esm/utils/forge_context_manager.py)
- [esm/utils/msa/filter_sequences.py](esm/utils/msa/filter_sequences.py)

</details>



The Forge client ecosystem provides the remote execution backend for the ESM SDK, allowing users to perform inference on ESM3, ESMC, and ESMFold2 without local GPU resources. These clients manage the full request/response lifecycle, including data serialization, authentication via API tokens, and robust error handling with retry logic.

### Transport Layer: `_BaseForgeInferenceClient`

All Forge clients inherit from `_BaseForgeInferenceClient` [esm/sdk/base_forge_client.py:10-11](), which abstracts the underlying HTTP transport using `httpx`. It manages connection pooling for both synchronous and asynchronous requests.

| Feature | Implementation |
| :--- | :--- |
| **Authentication** | Bearer token passed in the `Authorization` header [esm/sdk/base_forge_client.py:28-28](). |
| **HTTP Engine** | Uses `httpx.Client` for sync and `httpx.AsyncClient` for async operations [esm/sdk/base_forge_client.py:38-47](). |
| **Payload Assembly** | Uses `assemble_message` to combine headers and body into a processed dictionary [esm/sdk/base_forge_client.py:91-91](). |
| **Serialization** | Supports standard JSON and optimized binary formats via `return-bytes` headers [esm/sdk/base_forge_client.py:81-83](). |

**Sources:**
- [esm/sdk/base_forge_client.py:10-47]()
- [esm/sdk/base_forge_client.py:85-102]()

---

### Client Implementations

#### 1. `SequenceStructureForgeInferenceClient`
This client handles structural tasks, specifically protein folding (Sequence → Structure) and inverse folding (Structure → Sequence). It integrates with `ESMFold2` and handles complex inputs like MSAs and multi-chain complexes.

*   **Folding**: Converts a sequence and optional `MSA` into a 3D `ESMProtein` [esm/sdk/forge.py:133-177]().
*   **Inverse Folding**: Takes 3D coordinates and returns the predicted sequence [esm/sdk/forge.py:204-268]().
*   **Complex Support**: Uses `serialize_structure_prediction_input` to handle `ProteinInput`, `RNAInput`, `DNAInput`, and `LigandInput` [esm/sdk/forge.py:44-45]().

#### 2. `ESM3ForgeInferenceClient`
The primary interface for the multimodal ESM3 model. It implements the `ESM3InferenceClient` protocol, supporting:
*   `generate`: Iterative sampling across sequence, structure, and function tracks [esm/sdk/forge.py:347-384]().
*   `forward_and_sample`: Single-step forward pass and token sampling [esm/sdk/forge.py:386-425]().
*   `encode`/`decode`: Conversion between `ESMProtein` and `ESMProteinTensor` using remote tokenizers [esm/sdk/forge.py:288-345]().

#### 3. `ESMCForgeInferenceClient`
A specialized client for the ESMC (Sequence-only) model family. It focuses on high-throughput sequence embeddings and logit generation [esm/sdk/forge.py:539-577]().

**Sources:**
- [esm/sdk/forge.py:102-130]()
- [esm/sdk/forge.py:270-286]()
- [esm/sdk/forge.py:539-550]()

---

### Data Flow & Serialization

The client bridges the gap between high-level Python objects and wire-compatible JSON/Pickle payloads.

#### Request Lifecycle Diagram
This diagram illustrates how a request moves from the SDK's high-level entities into the Forge transport layer.

**Forge Request Lifecycle**
```mermaid
graph TD
    subgraph "SDK User Space"
        A["ESMProtein / MSA"] --> B["Client Method (e.g., generate)"]
    end

    subgraph "Serialization Logic"
        B --> C{"Input Type?"}
        C -- "Structure" --> D["serialize_structure_prediction_input"]
        C -- "ESM3/ESMC" --> E["ESMProteinTensor.to_dict()"]
        D --> F["Base64 / JSON Payload"]
        E --> F
    end

    subgraph "Transport Layer (_BaseForgeInferenceClient)"
        F --> G["_post / _async_post"]
        G --> H["httpx.Request"]
        H --> I["Forge API Endpoint"]
    end

    subgraph "Response Handling"
        I --> J["assemble_message"]
        J --> K["deserialize_tensors"]
        K --> L["ESMProtein / LogitsOutput"]
    end
```
**Sources:**
- [esm/sdk/forge.py:133-177]()
- [esm/sdk/base_forge_client.py:104-162]()
- [esm/utils/structure/input_builder.py:44-45]()

---

### Retry Logic and Error Handling

The client utilizes a custom `retry_decorator` [esm/sdk/retry.py:41-85]() built on the `tenacity` library to handle transient network issues and API rate limits.

| Error Code | Action | Reason |
| :--- | :--- | :--- |
| `429` | Retry | Rate limit exceeded [esm/sdk/retry.py:23-23](). |
| `500`, `502`, `504` | Retry | Server-side transient failure [esm/sdk/retry.py:24-28](). |
| `400`, `401`, `403` | Fail | Client-side error (Invalid input/auth) [esm/sdk/retry.py:18-28](). |

The retry mechanism uses **incremental backoff**, starting at `min_retry_wait` and increasing by 1 second per attempt up to `max_retry_wait` [esm/sdk/retry.py:59-61]().

**Sources:**
- [esm/sdk/retry.py:18-28]()
- [esm/sdk/retry.py:41-85]()

---

### MSA and Complex Handling

For folding tasks, the client manages MSA (Multiple Sequence Alignment) depth. If an MSA exceeds `ESMFOLD2_MAX_MSA_SEQS` (default 4096), the client issues a warning and the server performs truncation [esm/sdk/forge.py:153-159]().

#### Entity Mapping Diagram
This diagram maps the SDK's structural data classes to their API representations.

**Structural Entity Mapping**
```mermaid
classDiagram
    class ProteinInput {
        +str sequence
        +list modifications
        +MSA msa
    }
    class StructurePredictionInput {
        +list sequences
        +PocketConditioning pocket
    }
    class ForgeAPI_Payload {
        +dict sequences
        +dict pocket
        +bool include_pae
    }
    
    ProteinInput --|> StructurePredictionInput : "contained in"
    StructurePredictionInput ..> ForgeAPI_Payload : "serialized by serialize_structure_prediction_input"
    
    class MolecularComplex {
        +np.ndarray atom_positions
        +np.ndarray chain_id
    }
    MolecularComplex ..> ProteinComplex : "from_protein_complex()"
```
**Sources:**
- [esm/utils/structure/input_builder.py:42-45]()
- [esm/utils/structure/molecular_complex.py:46-49]()
- [esm/sdk/forge.py:133-177]()
- [esm/utils/constants/models.py:10-12]()

---