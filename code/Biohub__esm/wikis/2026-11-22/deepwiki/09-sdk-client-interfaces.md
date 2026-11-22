# SDK & Client Interfaces

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [esm/sdk/__init__.py](esm/sdk/__init__.py)
- [esm/sdk/api.py](esm/sdk/api.py)
- [esm/sdk/forge.py](esm/sdk/forge.py)

</details>



The `esm.sdk` package provides a high-level, unified interface for interacting with ESM models, whether they are running locally or hosted on remote platforms like Biohub Forge or AWS SageMaker. It abstracts away the complexities of serialization, transport protocols, and model-specific configurations into a set of consistent Python interfaces.

### Client Factory Functions

The SDK provides three primary entry points for creating inference clients. These functions automatically handle authentication via the `ESM_API_KEY` environment variable and default to the Biohub Platform (`https://biohub.ai`).

| Function | Return Type | Primary Use Case |
| :--- | :--- | :--- |
| `client()` | `ESM3InferenceClient` | Multimodal generation, folding, and inverse folding with ESM3. |
| `esmc_client()` | `ESMCInferenceClient` | Sequence embeddings and zero-shot mutation scoring with ESMC. |
| `esmfold2_client()` | `SequenceStructureForgeInferenceClient` | High-speed structure prediction and inverse folding. |

**Sources:** [esm/sdk/__init__.py:14-70]()

### Core Architecture Overview

The SDK is built on a hierarchy of abstract base classes that define the "API Contract" for each model family. These contracts ensure that switching between a remote Forge client and a local model instance requires minimal code changes.

#### System Entity Mapping
The following diagram maps high-level SDK concepts to their concrete implementation classes and factory functions.

**SDK Interface Mapping**
```mermaid
graph TD
    subgraph "Natural Language Space"
        A["ESM3 Client"]
        B["ESMC Client"]
        C["ESMFold2 Client"]
        D["Batch Execution"]
    end

    subgraph "Code Entity Space"
        A --- E["client()"]
        E --> F["ESM3ForgeInferenceClient"]
        F -- "implements" --> G["ESM3InferenceClient"]
        
        B --- H["esmc_client()"]
        H --> I["ESMCForgeInferenceClient"]
        I -- "implements" --> J["ESMCInferenceClient"]
        
        C --- K["esmfold2_client()"]
        K --> L["SequenceStructureForgeInferenceClient"]
        
        D --- M["batch_executor()"]
        M --> N["ForgeBatchExecutor"]
    end

    style G stroke-dasharray: 5 5
    style J stroke-dasharray: 5 5
```
**Sources:** [esm/sdk/__init__.py:1-83](), [esm/sdk/api.py:350-1000]()

### Data Models & API Contracts
The SDK centers around the `ESMProtein` class, which acts as a multimodal container for sequence, structure (coordinates), secondary structure, SASA, and function annotations. The inference clients operate on these objects (or their tensorized counterparts, `ESMProteinTensor`).

*   **`ESMProtein`**: High-level object with PDB/mmCIF I/O capabilities.
*   **`InferenceClient`**: Abstract interfaces defining methods like `encode()`, `decode()`, `generate()`, and `logits()`.

For details on data models and abstract interfaces, see [SDK API Contracts – ESMProtein & Inference Clients](#3.1).

**Sources:** [esm/sdk/api.py:27-163](), [esm/sdk/api.py:350-450]()

### Execution Backends

The SDK supports multiple backends for executing model inference:

1.  **Forge / Biohub Platform**: The default remote backend. It uses a specialized transport layer (`_BaseForgeInferenceClient`) that handles JSON/Pickle serialization and provides robust retry logic for network stability.
    *   For details, see [Forge / Biohub Platform Client](#3.2).
2.  **SageMaker**: A backend for AWS SageMaker endpoints. It wraps the Forge client logic but adapts the request format for SageMaker's `boto3` requirements.
    *   For details, see [SageMaker & Alternative Backends](#3.3).
3.  **Local Execution**: While the SDK provides the interfaces, local execution is typically handled by passing a local model instance (e.g., `esm.models.esm3.ESM3`) into the same generation logic used by the SDK.

### Batch Processing & Rate Limiting

For high-throughput tasks, the SDK provides the `ForgeBatchExecutor`. This utility manages a pool of concurrent requests and implements an **AIMD (Additive Increase/Multiplicative Decrease)** rate limiter to maximize throughput while respecting server constraints (e.g., handling `429 Too Many Requests` errors).

**Batch Execution Flow**
```mermaid
sequenceDiagram
    participant U as User Code
    participant BE as ForgeBatchExecutor
    participant RL as AIMDRateLimiter
    participant F as Forge API

    U->>BE: execute_batch(client.generate, proteins)
    loop For each protein
        BE->>RL: Check current_concurrency
        RL-->>BE: Allowed
        BE->>F: POST /generate
    end
    F-->>BE: 200 OK / 429 Rate Limit
    BE->>RL: adjust_concurrency(error_seen)
    BE-->>U: List[ESMProtein | ESMProteinError]
```

**Sources:** [esm/utils/forge_context_manager.py:46-156](), [esm/sdk/__init__.py:73-83]()

### Experimental Features

The SDK includes experimental support for **Guided & Constrained Generation**. This allows users to steer the model's output using soft scoring functions (e.g., maximizing a specific property) or hard constraints (e.g., fixing specific residues or motifs).

For details, see [Experimental: Guided & Constrained Generation](#3.4).

**Sources:** [esm/sdk/api.py:1020-1150]() (referencing internal constraint types)

---