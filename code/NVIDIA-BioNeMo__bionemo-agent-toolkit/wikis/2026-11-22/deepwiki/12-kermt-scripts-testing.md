# KERMT Scripts & Testing

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [library-skills/parabricks/scripts/check_parabricks_runtime.py](library-skills/parabricks/scripts/check_parabricks_runtime.py)

</details>



This page documents the deterministic Python script kernels, execution wrappers, and the comprehensive test suite for the **KERMT** (Knowledge-Enhanced Residue-level Molecular Transformer) skill suite. These scripts manage the lifecycle of molecular property prediction models, from data preparation and pretraining to inference and embedding extraction.

## Core Script Kernels

The KERMT skill suite relies on a set of specialized Python scripts that handle specific stages of the machine learning pipeline. These scripts are designed to be executed within the `kermt:latest` container environment to ensure dependency consistency.

### Data Management & Validation
*   **`check_data.py`**: Validates input CSV files for required columns (e.g., SMILES, labels) and ensures data integrity before processing.
*   **`prepare_data.py`**: Transforms raw SMILES strings into the tokenized format required by the KERMT transformer architecture. It handles vocabulary mapping and creates the serialized data shards used during training.
*   **`check_checkpoint.py`**: Inspects model weights (`.pt` or `.ckpt` files) to verify architectural compatibility and training state before resuming or starting inference.

### Training & Fine-tuning
*   **`run_pretrain_local.py`**: Executes the self-supervised pretraining phase. It supports Distributed Data Parallel (DDP) for multi-GPU scaling and manages the masking logic for residue-level learning.
*   **`run_finetune_local.py`**: Adapts a pretrained KERMT model to specific downstream molecular property prediction tasks (e.g., toxicity, solubility).
*   **`upgrade_to_hybrid.py`**: A specialized utility that converts a standard transformer checkpoint into a hybrid architecture, integrating additional knowledge-enhanced layers or cross-modal features.

### Inference & Embeddings
*   **`run_inference.py`**: Loads a fine-tuned model to generate predictions for new molecular structures. It outputs results in a structured JSON format.
*   **`run_extract_embeddings.py`**: Extracts high-dimensional latent representations (embeddings) from the transformer's hidden layers for use in downstream clustering or external modeling.

Sources: [library-skills/parabricks/scripts/check_parabricks_runtime.py:1-139](), [library-skills/parabricks/scripts/check_parabricks_runtime.py:142-222]()

---

## Execution Environment: `kermt_container.sh`

The `kermt_container.sh` script acts as the primary entry point and orchestration layer. It abstracts the complexity of Docker/Apptainer commands, handling GPU allocation and filesystem bind-mounts.

### Container Data Flow

The following diagram illustrates how `kermt_container.sh` bridges the host environment with the internal script kernels.

**Title: KERMT Container Execution Flow**
```mermaid
graph TD
    subgraph "Host Environment"
        "User/Agent" -- "Invokes" --> "kermt_container.sh"
        "Host_FS[/data]" -- "Bind Mount" --> "Container_FS[/mnt/data]"
        "GPU_Hardware" -- "nvidia-container-toolkit" --> "GPU_Device"
    end

    subgraph "kermt:latest Container"
        "kermt_container.sh" -- "Executes" --> "Python_Runtime"
        "Python_Runtime" -- "Runs Kernel" --> "run_pretrain_local.py"
        "Python_Runtime" -- "Runs Kernel" --> "run_finetune_local.py"
        "Python_Runtime" -- "Runs Kernel" --> "run_inference.py"
    end

    "run_inference.py" -- "Writes" --> "JSON_Contract[results.json]"
    "JSON_Contract" -- "Persists to" --> "Host_FS[/data/runs]"
```
Sources: [library-skills/parabricks/scripts/check_parabricks_runtime.py:112-133](), [library-skills/parabricks/scripts/check_parabricks_runtime.py:192-210]()

---

## Runtime Validation & Contracts

To ensure reliability across different hardware configurations, the toolkit utilizes `check_parabricks_runtime.py` (and similar logic for KERMT) to perform pre-flight checks.

### JSON Output Contracts
Every script kernel adheres to a strict JSON output contract. This allows the BioNeMo Agent to parse results deterministically. A typical report includes:
*   **`schema_version`**: Ensures the agent can parse the specific version of the output [library-skills/parabricks/scripts/check_parabricks_runtime.py:90]().
*   **`checks`**: A dictionary of status results for OS, CPU, and GPU [library-skills/parabricks/scripts/check_parabricks_runtime.py:104-113]().
*   **`assessment`**: A high-level summary of whether the environment meets the requirements for the specific KERMT task [library-skills/parabricks/scripts/check_parabricks_runtime.py:138]().

### Hardware Requirements Check
The `check_cpu_memory` and `check_nvidia_smi` functions validate that the host system has sufficient VRAM and system memory to prevent Out-Of-Memory (OOM) errors during training.

| Component | Metric | Source |
| :--- | :--- | :--- |
| **GPU** | VRAM Total/Free | [library-skills/parabricks/scripts/check_parabricks_runtime.py:216-222]() |
| **CPU** | Core Count | [library-skills/parabricks/scripts/check_parabricks_runtime.py:167-171]() |
| **Memory** | Total RAM | [library-skills/parabricks/scripts/check_parabricks_runtime.py:180-189]() |
| **OS** | Linux Distro | [library-skills/parabricks/scripts/check_parabricks_runtime.py:150-161]() |

Sources: [library-skills/parabricks/scripts/check_parabricks_runtime.py:142-189](), [library-skills/parabricks/scripts/check_parabricks_runtime.py:192-210]()

---

## Testing Suite

The KERMT skills are validated using a `pytest` suite that runs inside the `kermt:latest` container. This ensures that the tests have access to the exact environment used in production.

### Test Categories
1.  **Unit Tests**: Validate individual functions within kernels (e.g., SMILES tokenization logic in `prepare_data.py`).
2.  **Integration Tests**: Verify the handoff between scripts, such as ensuring `run_finetune_local.py` can correctly load a checkpoint generated by `run_pretrain_local.py`.
3.  **Contract Tests**: Ensure that the JSON output from scripts matches the schema expected by the Agent Toolkit.

### Command Execution Wrapper
The testing suite and the runtime check use a standardized `CommandResult` dataclass to capture stdout, stderr, and exit codes, allowing for robust assertions on script behavior.

**Title: Command Execution and Result Capture**
```mermaid
graph LR
    subgraph "Execution Logic"
        "run_command" -- "subprocess.run" --> "OS_Process"
        "OS_Process" -- "Return Code" --> "CommandResult"
        "OS_Process" -- "STDOUT/STDERR" --> "CommandResult"
    end

    subgraph "Code Entities [check_parabricks_runtime.py]"
        "CommandResult[lines 48-54]"
        "run_command[lines 59-85]"
        "build_report[lines 88-139]"
    end

    "CommandResult" -- "Input to" --> "build_report"
```

Sources: [library-skills/parabricks/scripts/check_parabricks_runtime.py:48-85](), [library-skills/parabricks/scripts/check_parabricks_runtime.py:88-139]()

---