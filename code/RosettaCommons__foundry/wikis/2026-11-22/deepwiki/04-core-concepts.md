# Core Concepts

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.env](.env)
- [README.md](README.md)
- [models/rf3/configs/experiment/pretrained/rf3.yaml](models/rf3/configs/experiment/pretrained/rf3.yaml)
- [models/rf3/src/rf3/callbacks/dump_validation_structures.py](models/rf3/src/rf3/callbacks/dump_validation_structures.py)
- [models/rf3/src/rf3/cli.py](models/rf3/src/rf3/cli.py)
- [models/rf3/src/rf3/utils/io.py](models/rf3/src/rf3/utils/io.py)
- [models/rfd3/README.md](models/rfd3/README.md)
- [models/rfd3/src/rfd3/cli.py](models/rfd3/src/rfd3/cli.py)
- [pyproject.toml](pyproject.toml)
- [src/foundry/inference_engines/base.py](src/foundry/inference_engines/base.py)
- [src/foundry/inference_engines/checkpoint_registry.py](src/foundry/inference_engines/checkpoint_registry.py)
- [src/foundry_cli/__init__.py](src/foundry_cli/__init__.py)
- [src/foundry_cli/download_checkpoints.py](src/foundry_cli/download_checkpoints.py)

</details>



This document introduces the fundamental concepts and architectural patterns that underpin the Foundry ecosystem. These concepts apply across all models (RFD3, RF3, MPNN) and provide the foundation for understanding how to use and extend the platform.

For detailed information on specific topics:
- AtomWorks data structures and utilities: see [AtomWorks Foundation](#3.1)
- How foundry core, models, and atomworks interact: see [Model Architecture](#3.2)
- The inference engine interface pattern: see [Inference Engines](#3.3)
- Model-specific design workflows: see [RFdiffusion3 (RFD3)](#4), [RosettaFold3 (RF3)](#5), and [ProteinMPNN and LigandMPNN](#6)

---

## The Foundry Ecosystem

Foundry is built on a strict dependency hierarchy that ensures consistency and modularity across all models.

**Foundry Dependency Architecture**

```mermaid
graph TB
    subgraph "External Dependencies"
        PDB["PDB_MIRROR_PATH<br/>/path/to/pdb_mirror"]
        CCD["CCD_MIRROR_PATH<br/>/path/to/ccd_mirror"]
        CKPT["FOUNDRY_CHECKPOINT_DIRS<br/>~/.foundry/checkpoints"]
    end
    
    subgraph "Core Infrastructure (src/foundry/)"
        AW["atomworks<br/>biotite.structure.AtomArray<br/>atomworks.io.parse"]
        FC["foundry package<br/>src/foundry/inference_engines/base.py<br/>BaseInferenceEngine<br/>src/foundry/trainers/fabric.py<br/>FabricTrainer"]
    end
    
    subgraph "Model Packages"
        RFD3["models/rfd3/src/rfd3/<br/>engine.RFD3InferenceEngine"]
        RF3["models/rf3/src/rf3/<br/>inference.run_inference"]
        MPNN["models/mpnn/src/mpnn/<br/>inference.MPNNInferenceEngine"]
    end
    
    User["User Code"] --> RFD3
    User --> RF3
    User --> MPNN
    
    RFD3 --> FC
    RF3 --> FC
    MPNN --> FC
    
    FC --> AW
    
    AW --> PDB
    AW --> CCD
    FC --> CKPT
```

**Sources:** [README.md:112-117](), [pyproject.toml:24-51](), [src/foundry/inference_engines/base.py:32-50]()

### Dependency Flow

The architecture enforces a strict unidirectional dependency flow:

| Layer | Key Classes/Modules | File Locations |
|-------|---------------------|----------------|
| **atomworks** | `biotite.structure.AtomArray`<br/>`atomworks.io.utils.io_utils.to_cif_file` | External dependency |
| **foundry** | `foundry.inference_engines.base.BaseInferenceEngine`<br/>`foundry.inference_engines.checkpoint_registry.RegisteredCheckpoint` | `src/foundry/` |
| **models/** | `rfd3.cli.design`<br/>`rf3.cli.fold`<br/>`mpnn.inference.main` | `models/*/src/` |

This separation allows:
- Independent installation of models via extras: `pip install "rc-foundry[rfd3]"` [pyproject.toml:58-60]().
- Shared utilities for checkpoint management and distributed inference [src/foundry/inference_engines/checkpoint_registry.py:1-122]().
- Easy addition of new models as independent packages in `models/` [README.md:134-142]().

**Sources:** [README.md:112-117](), [pyproject.toml:54-70](), [src/foundry/inference_engines/base.py:32-50]()

---

## Central Data Structure: biotite.structure.AtomArray

All models in Foundry operate on `biotite.structure.AtomArray` objects. This is the unified framework for manipulating and processing biomolecular structures [README.md:5]().

**AtomArray Processing Flow**

```mermaid
graph LR
    subgraph "Input Sources"
        CIF["CIF/PDB Files"]
        AA_Obj["biotite.structure.AtomArray"]
    end
    
    subgraph "AtomWorks Processing"
        Parser["atomworks.io.parse()"]
        AA["biotite.structure.AtomArray<br/>+ annotations"]
    end
    
    subgraph "Foundry Models"
        RFD3["rfd3 design<br/>models/rfd3/src/rfd3/cli.py"]
        RF3["rf3 fold<br/>models/rf3/src/rf3/cli.py"]
        MPNN["mpnn inference<br/>models/mpnn/src/mpnn/inference.py"]
    end
    
    CIF --> Parser
    AA_Obj --> Parser
    Parser --> AA
    
    AA --> RFD3
    AA --> RF3
    AA --> MPNN
    
    RFD3 --> Out1["CIF Output"]
    RF3 --> Out2["CIF Output"]
    MPNN --> Out3["CIF Output"]
```

**Sources:** [README.md:1-5](), [models/rf3/src/rf3/utils/io.py:61-94](), [models/rf3/src/rf3/callbacks/dump_validation_structures.py:78-87]()

### Handling Multi-Model Stacks

During diffusion or ensemble prediction, Foundry uses `AtomArrayStack` to manage multiple conformations of the same structure. The utility `build_stack_from_atom_array_and_batched_coords` is used to convert model coordinate outputs (tensors) back into structured `AtomArrayStack` objects [models/rf3/src/rf3/utils/io.py:61-94]().

**Sources:** [models/rf3/src/rf3/utils/io.py:61-94](), [models/rf3/src/rf3/callbacks/dump_validation_structures.py:78-87]()

---

## The Inference Engine Pattern

All models implement a common interface via `foundry.inference_engines.base.BaseInferenceEngine`, which separates expensive model setup from the actual inference execution [src/foundry/inference_engines/base.py:32-36]().

**BaseInferenceEngine Class Hierarchy**

```mermaid
graph TB
    subgraph "Base Class (src/foundry/inference_engines/base.py)"
        Base["BaseInferenceEngine"]
        Init["__init__(ckpt_path, ...)"]
        Initialize["initialize()<br/>- Loads weights<br/>- Constructs trainer"]
        Run["run(inputs) -> dict"]
    end
    
    subgraph "Model Implementations"
        RFD3E["RFD3InferenceEngine"]
        RF3E["RF3InferenceEngine"]
        MPNNE["MPNNInferenceEngine"]
    end
    
    Base --> Init
    Init --> Initialize
    Initialize --> Run
    
    RFD3E -- "inherits" --> Base
    RF3E -- "inherits" --> Base
    MPNNE -- "inherits" --> Base
```

**Sources:** [src/foundry/inference_engines/base.py:32-155]()

### Inference Engine Lifecycle

1. **Initialization** (`__init__`): Stores overrides and resolves the checkpoint path [src/foundry/inference_engines/base.py:38-120]().
2. **Setup** (`initialize()`): Loads the model weights from the checkpoint and instantiates the `FabricTrainer` for hardware-agnostic execution [src/foundry/inference_engines/base.py:125-142]().
3. **Execution** (`run()`): Subclasses implement the specific logic to process inputs and return structural predictions or designs [src/foundry/inference_engines/base.py:144-154]().

**Sources:** [src/foundry/inference_engines/base.py:32-246]()

### Checkpoint Resolution System

Foundry uses a centralized registry to manage model weights. The `foundry install` command downloads these weights to a searchable directory [README.md:44-56]().

**Checkpoint Resolution Flow**

```mermaid
graph LR
    CLI["foundry install base-models"] --> Reg["REGISTERED_CHECKPOINTS<br/>src/foundry/inference_engines/checkpoint_registry.py"]
    Reg --> DL["download_file()<br/>src/foundry_cli/download_checkpoints.py"]
    DL --> Disk["~/.foundry/checkpoints/"]
    
    Engine["BaseInferenceEngine(ckpt_path='rf3')"] --> Search["get_default_checkpoint_dirs()"]
    Search --> Disk
```

**Sources:** [src/foundry/inference_engines/checkpoint_registry.py:80-122](), [src/foundry_cli/download_checkpoints.py:144-185]()

---

## Configuration Management with Hydra

Foundry uses **Hydra** for hierarchical configuration. This allows users to override any part of the model or inference engine behavior via the CLI [models/rf3/src/rf3/cli.py:44-59]().

| Override Level | Example Syntax | Purpose |
|----------------|----------------|---------|
| **Inference Engine** | `inference_engine=rf3` | Selects the engine implementation |
| **Model Parameters** | `model.net.inference_sampler.num_timesteps=50` | Modifies diffusion sampling steps |
| **Input Selection** | `inputs=path/to/input.json` | Specifies the design task |
| **Hardware** | `trainer.devices_per_node=2` | Configures multi-GPU execution |

**Sources:** [models/rf3/src/rf3/cli.py:44-69](), [models/rfd3/src/rfd3/cli.py:30-43](), [src/foundry/inference_engines/base.py:118-119]()

---

## Environment Configuration

The system relies on a `.env` file to locate external tools and data mirrors.

| Variable | Description |
|----------|-------------|
| `PDB_MIRROR_PATH` | Path to local PDB mirror (RCSB convention) [.env:9-13](). |
| `CCD_MIRROR_PATH` | Path to local Chemical Component Dictionary mirror [.env:15-22](). |
| `HBPLUS_PATH` | Path to `hbplus` executable for hydrogen bond calculation [.env:29-32](). |
| `FOUNDRY_CHECKPOINT_DIRS` | Colon-separated list of directories to search for weights [.env:61-63](). |

**Sources:** [.env:1-63](), [src/foundry/inference_engines/checkpoint_registry.py:25-41]()

---

## Summary

The Foundry ecosystem is built on four core concepts:

1. **AtomWorks Foundation**: `AtomArray` as the universal data structure for biomolecular structures.
2. **Inference Engine Pattern**: `BaseInferenceEngine` providing consistent interfaces across models.
3. **Configuration System**: Hydra-based hierarchical configuration with flexible CLI overrides.
4. **Data Flow**: Structures flow between models (RFD3 → MPNN → RF3) as standardized `AtomArray` objects.

For implementation details, see the subsections on [AtomWorks Foundation](#3.1), [Model Architecture](#3.2), and [Inference Engines](#3.3).

**Sources:** [README.md:1-106](), [src/foundry/inference_engines/base.py:32-50]()

---