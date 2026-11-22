# RF3 Inference

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [models/rf3/configs/experiment/pretrained/rf3.yaml](models/rf3/configs/experiment/pretrained/rf3.yaml)
- [models/rf3/configs/inference_engine/base.yaml](models/rf3/configs/inference_engine/base.yaml)
- [models/rf3/configs/inference_engine/rf3.yaml](models/rf3/configs/inference_engine/rf3.yaml)
- [models/rf3/src/rf3/callbacks/dump_validation_structures.py](models/rf3/src/rf3/callbacks/dump_validation_structures.py)
- [models/rf3/src/rf3/cli.py](models/rf3/src/rf3/cli.py)
- [models/rf3/src/rf3/data/extra_xforms.py](models/rf3/src/rf3/data/extra_xforms.py)
- [models/rf3/src/rf3/data/pipelines.py](models/rf3/src/rf3/data/pipelines.py)
- [models/rf3/src/rf3/inference.py](models/rf3/src/rf3/inference.py)
- [models/rf3/src/rf3/inference_engines/rf3.py](models/rf3/src/rf3/inference_engines/rf3.py)
- [models/rf3/src/rf3/symmetry/resolve.py](models/rf3/src/rf3/symmetry/resolve.py)
- [models/rf3/src/rf3/utils/inference.py](models/rf3/src/rf3/utils/inference.py)
- [models/rf3/src/rf3/utils/io.py](models/rf3/src/rf3/utils/io.py)
- [models/rfd3/src/rfd3/cli.py](models/rfd3/src/rfd3/cli.py)
- [pyproject.toml](pyproject.toml)

</details>



This page provides detailed documentation of the `RF3InferenceEngine` class, its initialization parameters, execution flow, and inference configuration. The engine implements the structure prediction and validation capabilities of RosettaFold3.

For input preparation and selection details, see [Input Preparation and Selection](). For confidence metrics and scoring, see [Confidence Metrics](). For output format and file organization, see [Output Management]().

---

## Overview

The `RF3InferenceEngine` implements a two-phase design that separates model setup (expensive, performed once) from inference execution (can be run multiple times with different inputs). This architecture enables efficient batch processing and reuse of loaded model weights.

**Key Design Principles:**
- **Stateful Setup**: Model checkpoints and configuration are loaded once during initialization.
- **Stateless Execution**: The `run()` method accepts inputs and parameters, returning results without modifying engine state.
- **Flexible Inputs**: Accepts `InferenceInput` objects, `AtomArray` objects, file paths, or directories.
- **Distributed Support**: Built-in load balancing and multi-GPU inference through `LoadBalancedDistributedSampler`.

### System Data Flow

The following diagram maps the high-level inference process to specific code entities within the `rf3` package.

**RosettaFold3 Inference Logic Mapping**
```mermaid
graph TB
    subgraph "Initialization Space"
        CLI["rf3.cli:fold"] -- "hydra.compose" --> CFG["inference.yaml"]
        CFG -- "instantiate" --> ENGINE["rf3.inference_engines.rf3:RF3InferenceEngine"]
        ENGINE -- "super().initialize()" --> BASE["foundry.inference_engines.base:BaseInferenceEngine"]
        BASE -- "loads" --> CKPT["Model Weights & Hyperparams"]
    end
    
    subgraph "Data Preparation Space"
        INPUTS["Files/Arrays/Dicts"] -- "prepare_inference_inputs_from_paths" --> INF_IN["rf3.utils.inference:InferenceInput"]
        INF_IN -- "dataset wrap" --> DS["rf3.utils.inference:InferenceInputDataset"]
        DS -- "token count balancing" --> SAMPLER["atomworks.ml.samplers:LoadBalancedDistributedSampler"]
    end
    
    subgraph "Execution Space"
        ENGINE -- "run()" --> LOOP["Inference Loop"]
        LOOP -- "transform" --> PIPE["rf3.data.pipelines:build_af3_transform_pipeline"]
        PIPE -- "forward" --> STEP["trainer.validation_step()"]
        STEP -- "output" --> OUT["rf3.inference_engines.rf3:RF3Output"]
    end

    subgraph "Persistence Space"
        OUT -- "dump()" --> CIF["to_cif_file"]
        OUT -- "dump_json" --> JSON["summary_confidences.json"]
    end
```
**Sources:** [models/rf3/src/rf3/inference_engines/rf3.py:222-370](), [models/rf3/src/rf3/inference.py:32-67](), [models/rf3/src/rf3/cli.py:12-69]()

---

## RF3InferenceEngine Class Structure

The `RF3InferenceEngine` inherits from `BaseInferenceEngine` and implements RF3-specific inference logic. The class is defined at [models/rf3/src/rf3/inference_engines/rf3.py:222-736]().

### Class Architecture

```mermaid
classDiagram
    class BaseInferenceEngine {
        <<Abstract>>
        +ckpt_path: PathLike
        +seed: int | None
        +num_nodes: int
        +devices_per_node: int
        +initialize() DictConfig
    }
    
    class RF3InferenceEngine {
        -n_recycles: int
        -diffusion_batch_size: int
        -num_steps: int
        -template_noise_scale: float
        -early_stopping_plddt_threshold: float
        -compress_outputs: bool
        -_metrics_cfg: dict | str
        +__init__(**kwargs)
        +initialize() DictConfig
        +run(**params) dict | None
    }
    
    class InferenceInputDataset {
        +inference_inputs: list
        +key_to_balance: str
        +data: DataFrame
        +__len__() int
        +__getitem__(idx) InferenceInput
    }
    
    class RF3Output {
        +example_id: str
        +atom_array: AtomArray
        +summary_confidences: dict
        +confidences: dict
        +sample_idx: int
        +seed: int
        +dump(out_dir, file_type)
    }
    
    BaseInferenceEngine <|-- RF3InferenceEngine
    RF3InferenceEngine ..> InferenceInputDataset : creates
    RF3InferenceEngine ..> RF3Output : produces
```

**Sources:** [models/rf3/src/rf3/inference_engines/rf3.py:222-240](), [models/rf3/src/rf3/utils/inference.py:628-666](), [models/rf3/src/rf3/inference_engines/rf3.py:98-148]()

---

## Initialization Parameters

The `RF3InferenceEngine.__init__()` method accepts parameters that control model behavior, output format, and metrics computation.

### Parameter Categories

| Category | Parameters | Description |
|----------|-----------|-------------|
| **Model Parameters** | `n_recycles`, `diffusion_batch_size`, `num_steps` | Control the structure prediction process [models/rf3/configs/inference_engine/rf3.yaml:12-16]() |
| **Template/MSA** | `template_noise_scale`, `raise_if_missing_msa_for_protein_of_length_n` | Configure template and MSA handling [models/rf3/configs/inference_engine/rf3.yaml:17-23]() |
| **Output Control** | `compress_outputs` | Whether to gzip output files [models/rf3/configs/inference_engine/base.yaml:10]() |
| **Early Stopping** | `early_stopping_plddt_threshold` | Stop inference if pLDDT falls below threshold [models/rf3/configs/inference_engine/rf3.yaml:20]() |
| **Metrics** | `metrics_cfg` | Configure confidence metrics computation [models/rf3/configs/inference_engine/rf3.yaml:26-33]() |
| **Base Engine** | `ckpt_path`, `seed`, `num_nodes`, `devices_per_node`, `verbose` | Inherited from `BaseInferenceEngine` [models/rf3/configs/inference_engine/base.yaml:7-9]() |

### Model Parameters

*   **`n_recycles`** (int, default: 10): Number of recycle iterations through the Evoformer. [models/rf3/configs/inference_engine/rf3.yaml:12]()
*   **`diffusion_batch_size`** (int, default: 5): Number of structure samples to generate per input. Each sample uses a different noise trajectory. [models/rf3/configs/inference_engine/rf3.yaml:13]()
*   **`num_steps`** (int, default: 50): Number of diffusion timesteps for structure generation. [models/rf3/configs/inference_engine/rf3.yaml:16]()

### Template and MSA Configuration

*   **`template_noise_scale`** (float, default: 1e-5): Noise added to template coordinates to prevent overfitting. [models/rf3/configs/inference_engine/rf3.yaml:17]()
*   **`raise_if_missing_msa_for_protein_of_length_n`** (int | None, default: None): If set, raises error if MSA is missing for proteins longer than specified length. [models/rf3/configs/inference_engine/rf3.yaml:23]()
*   **MSA Directory Configuration**: MSA directories are automatically loaded from environment variables using `get_msa_dirs_from_env`. [models/rf3/src/rf3/inference_engines/rf3.py:15-16]()

### Metrics Configuration

The `metrics_cfg` parameter [models/rf3/src/rf3/inference_engines/rf3.py:332-369]() controls which confidence metrics are computed.

*   **Default**: Uses standard RF3 metrics defined in `DEFAULT_RF3_METRICS_CFG`: `ptm`, `iptm`, and `count_clashing_chains`. [models/rf3/src/rf3/inference_engines/rf3.py:50-56]()
*   **Custom**: Accepts a Hydra configuration dictionary where each key maps to a metric class with a `_target_`. [models/rf3/configs/inference_engine/rf3.yaml:26-33]()

---

## Initialization Process

The initialization process occurs in two stages: `__init__()` sets up configuration overrides, while `initialize()` loads the checkpoint and instantiates the model.

### Initialization Flow

```mermaid
sequenceDiagram
    participant User
    participant Engine as RF3InferenceEngine
    participant Base as BaseInferenceEngine
    participant Fabric as Lightning Fabric
    participant Model as RF3 Model
    
    User->>Engine: __init__(ckpt_path, n_recycles, ...)
    activate Engine
    Note over Engine: Configure MSA & Transform Overrides
    Engine->>Base: super().__init__(**kwargs, overrides)
    activate Base
    Base-->>Engine: 
    deactivate Base
    Engine-->>User: Engine instance
    deactivate Engine
    
    User->>Engine: run(inputs, out_dir, ...)
    activate Engine
    Engine->>Engine: initialize() (Lazy)
    Engine->>Base: super().initialize()
    activate Base
    Base->>Fabric: Setup Lightning Fabric
    Base->>Model: Instantiate RF3 model & load weights
    Base-->>Engine: cfg (DictConfig)
    deactivate Base
    Engine->>Engine: Configure MetricManager on trainer
    Engine-->>Engine: Ready
    deactivate Engine
```

**Sources:** [models/rf3/src/rf3/inference_engines/rf3.py:241-370](), [foundry/inference_engines/base.py]()

---

## Inference Execution Flow

The `run()` method orchestrates the complete inference pipeline from input conversion to output generation.

### Execution Pipeline

```mermaid
graph TB
    subgraph "Input Handling"
        Start["run()"] --> Init["initialize() (if needed)"]
        Init --> Convert["Convert inputs to InferenceInput"]
        Convert --> DS["Create InferenceInputDataset"]
    end
    
    subgraph "Loop & Model"
        DS --> Sampler["LoadBalancedDistributedSampler"]
        Sampler --> Loader["DataLoader (batch_size=1)"]
        Loader --> Transform["rf3.data.pipelines:build_af3_transform_pipeline"]
        Transform --> Step["trainer.validation_step()"]
    end
    
    subgraph "Output Processing"
        Step --> StopCheck{"Early Stopped?"}
        StopCheck -- "No" --> Build["Build AtomArrayStack"]
        Build --> Conf["Compile Confidence Outputs"]
        Conf --> Rank["Compute Ranking Score"]
        Rank --> Save["Dump to Disk / Return Results"]
        
        StopCheck -- "Yes" --> SaveEarly["Save score.csv only"]
    end
```

### Input Conversion and Load Balancing

The engine accepts multiple input types (CIF, PDB, JSON, AtomArray) and converts them to `InferenceInput` objects. [models/rf3/src/rf3/inference_engines/rf3.py:440-478]().

*   **Load Balancing**: The `InferenceInputDataset` calculates approximate token counts using `AddGlobalTokenIdAnnotation` to enable load-balanced distribution across GPUs via `LoadBalancedDistributedSampler`. [models/rf3/src/rf3/utils/inference.py:640-660](), [models/rf3/src/rf3/inference_engines/rf3.py:488-495]().

### Early Stopping

If `early_stopping_plddt_threshold` is set [models/rf3/configs/inference_engine/rf3.yaml:20](), the engine uses `should_early_stop_by_mean_plddt()` to monitor confidence during the diffusion process. If the threshold is not met, inference for that sample terminates early to save compute. [models/rf3/src/rf3/inference_engines/rf3.py:203-219](), [models/rf3/src/rf3/inference_engines/rf3.py:530-540]().

### Output Generation

For successful predictions, outputs are encapsulated in `RF3Output` objects. [models/rf3/src/rf3/inference_engines/rf3.py:98-109]().

*   **Ranking**: A ranking score is computed using the formula: `0.8 * ipTM + 0.2 * pTM - 100 * has_clash`. [models/rf3/src/rf3/inference_engines/rf3.py:79-95]().
*   **B-Factor**: If `annotate_b_factor_with_plddt` is True, the B-factor column of the output CIF is replaced with per-residue pLDDT. [models/rf3/src/rf3/inference_engines/rf3.py:633-639]().
*   **Persistence**: Outputs are saved using `dump_json_compact_arrays` for an AlphaFold3-compatible format. [models/rf3/src/rf3/inference_engines/rf3.py:59-77](), [models/rf3/src/rf3/inference_engines/rf3.py:112-148]().

**Sources:** [models/rf3/src/rf3/inference_engines/rf3.py:372-736](), [models/rf3/src/rf3/utils/inference.py:260-282]()

---

## Configuration and CLI

### Main Entry Point

The `run_inference` function in `models/rf3/src/rf3/inference.py` handles the separation of Hydra configuration into engine initialization and execution parameters. [models/rf3/src/rf3/inference.py:32-67]().

### Command Line Interface

The `rf3` CLI provides `fold` and `predict` commands. [models/rf3/src/rf3/cli.py:12-82]().

```bash
# Basic usage with positional input
rf3 fold my_input.cif

# Advanced usage with Hydra overrides
rf3 fold inputs=my_input.cif out_dir=results n_recycles=20 diffusion_batch_size=10
```

**Sources:** [models/rf3/src/rf3/cli.py:1-87](), [models/rf3/configs/inference_engine/base.yaml:1-26]()

---