# Infrastructure and Configuration

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.env](.env)
- [README.md](README.md)
- [models/rf3/configs/trainer/xpu.yaml](models/rf3/configs/trainer/xpu.yaml)
- [models/rfd3/README.md](models/rfd3/README.md)
- [models/rfd3/configs/trainer/xpu.yaml](models/rfd3/configs/trainer/xpu.yaml)
- [src/foundry/__init__.py](src/foundry/__init__.py)
- [src/foundry/inference_engines/base.py](src/foundry/inference_engines/base.py)
- [src/foundry/inference_engines/checkpoint_registry.py](src/foundry/inference_engines/checkpoint_registry.py)
- [src/foundry/metrics/metric.py](src/foundry/metrics/metric.py)
- [src/foundry/testing/__init__.py](src/foundry/testing/__init__.py)
- [src/foundry/testing/pytest_hooks.py](src/foundry/testing/pytest_hooks.py)
- [src/foundry/trainers/fabric.py](src/foundry/trainers/fabric.py)
- [src/foundry/utils/logging.py](src/foundry/utils/logging.py)
- [src/foundry/utils/squashfs.py](src/foundry/utils/squashfs.py)
- [src/foundry/utils/xpu/__init__.py](src/foundry/utils/xpu/__init__.py)
- [src/foundry/utils/xpu/single_xpu_strategy.py](src/foundry/utils/xpu/single_xpu_strategy.py)
- [src/foundry/utils/xpu/xpu_accelerator.py](src/foundry/utils/xpu/xpu_accelerator.py)
- [src/foundry/utils/xpu/xpu_precision.py](src/foundry/utils/xpu/xpu_precision.py)
- [src/foundry_cli/__init__.py](src/foundry_cli/__init__.py)
- [src/foundry_cli/download_checkpoints.py](src/foundry_cli/download_checkpoints.py)

</details>



This page documents the infrastructure components that support model training and inference in Foundry, including checkpoint management, configuration systems, environment setup, command-line interfaces, and distributed execution utilities. For model-specific configuration details, see the individual model pages: [RFdiffusion3 (RFD3)](#4), [RosettaFold3 (RF3)](#5), and [ProteinMPNN and LigandMPNN](#6). For training infrastructure details, see [Training Infrastructure](#8.4).

---

## Checkpoint Management System

Foundry provides a centralized checkpoint registry and download system that manages model weights across all models in the ecosystem.

### Checkpoint Registry

The checkpoint registry maintains metadata about available model checkpoints and provides utilities for locating and downloading them.

```mermaid
graph TB
    subgraph "Checkpoint Registry"
        RegDict["REGISTERED_CHECKPOINTS<br/>dict[str, RegisteredCheckpoint]"]
        RegCheckpoint["RegisteredCheckpoint<br/>- url: str<br/>- filename: str<br/>- description: str<br/>- sha256: str | None"]
    end
    
    subgraph "Search Paths"
        DefaultDir["DEFAULT_CHECKPOINT_DIR<br/>~/.foundry/checkpoints"]
        EnvDirs["FOUNDRY_CHECKPOINT_DIRS<br/>colon-separated paths"]
        SearchFunc["get_default_checkpoint_dirs()<br/>returns list[Path]"]
    end
    
    subgraph "Download System"
        FoundryCLI["foundry CLI<br/>install/list-available/<br/>list-installed/clean"]
        DownloadFile["download_file()<br/>progress bar + SHA256 verify"]
    end
    
    RegDict --> RegCheckpoint
    RegCheckpoint --> FoundryCLI
    
    DefaultDir --> SearchFunc
    EnvDirs --> SearchFunc
    SearchFunc --> FoundryCLI
    SearchFunc --> RegCheckpoint
    
    FoundryCLI --> DownloadFile
```

**Checkpoint Search Path Resolution**

The `get_default_checkpoint_dirs()` function in [src/foundry/inference_engines/checkpoint_registry.py:25-41]() returns an ordered list of directories to search for checkpoints:

1. Directories specified in `FOUNDRY_CHECKPOINT_DIRS` environment variable (colon-separated)
2. Default directory: `~/.foundry/checkpoints`

The `RegisteredCheckpoint` class [src/foundry/inference_engines/checkpoint_registry.py:64-77]() encapsulates checkpoint metadata and provides `get_default_path()` which searches the checkpoint directories in order and returns the first existing match, or the default location if none exist.

**Available Checkpoints**

The `REGISTERED_CHECKPOINTS` dictionary [src/foundry/inference_engines/checkpoint_registry.py:80-117]() contains:

| Checkpoint Key | Filename | Description |
|---|---|---|
| `rfd3` | `rfd3_latest.ckpt` | RFdiffusion3 checkpoint |
| `rfd3na` | `rfd3na_1190.ckpt` | RFdiffusion3NA checkpoint |
| `rf3` | `rf3_foundry_01_24_latest_remapped.ckpt` | Latest RF3 (trained with data until 1/2024) |
| `proteinmpnn` | `proteinmpnn_v_48_020.pt` | ProteinMPNN checkpoint |
| `ligandmpnn` | `ligandmpnn_v_32_010_25.pt` | LigandMPNN checkpoint |
| `rf3_preprint_921` | `rf3_foundry_09_21_preprint_remapped.ckpt` | RF3 preprint (9/2021 data) |
| `rf3_preprint_124` | `rf3_foundry_01_24_preprint_remapped.ckpt` | RF3 preprint (1/2024 data) |
| `solublempnn` | `solublempnn_v_48_020.pt` | SolubleMPNN checkpoint |

**Sources:** [src/foundry/inference_engines/checkpoint_registry.py:1-118](), [README.md:44-57]()

---

### Download CLI

The `foundry` CLI command provides checkpoint management utilities.

**Installation Command**

```bash
foundry install <models> [--checkpoint-dir PATH] [--force]
```

The `install` command [src/foundry_cli/download_checkpoints.py:144-186]() supports:

- **Model selectors**: `all` (all models), `base-models` (rfd3, rfd3na, rf3, proteinmpnn, ligandmpnn), or individual model names
- **Checkpoint directory**: Optional custom directory; defaults to `~/.foundry/checkpoints`
- **Force flag**: Overwrites existing checkpoints when present

The download process [src/foundry_cli/download_checkpoints.py:54-103]():
1. Creates destination directory if needed
2. Downloads file with progress bar showing transfer speed and time remaining
3. Verifies SHA256 hash if provided in registry
4. Removes corrupted file if hash mismatch occurs

**Listing Commands**

```bash
foundry list-available    # Show all checkpoints in registry
foundry list-installed    # Show downloaded checkpoints with sizes
```

The `list-installed` command [src/foundry_cli/download_checkpoints.py:196-223]() searches all checkpoint directories and reports total disk usage.

**Environment Variable Updates**

When installing to a custom directory, `append_checkpoint_to_env()` [src/foundry/inference_engines/checkpoint_registry.py:49-61]() attempts to update the `.env` file to add the directory to `FOUNDRY_CHECKPOINT_DIRS`, making it persistent across sessions.

**Sources:** [src/foundry_cli/download_checkpoints.py:1-274](), [src/foundry/inference_engines/checkpoint_registry.py:1-118]()

---

## Configuration System

Foundry uses [Hydra](https://hydra.cc/) for compositional configuration management, enabling flexible hierarchical configs with runtime overrides.

### Configuration Architecture

```mermaid
graph TB
    subgraph "Configuration Sources"
        YAMLBase["Base YAML Configs<br/>models/*/configs/"]
        YAMLExperiment["Experiment Configs<br/>experiment/"]
        YAMLInference["Inference Engine Configs<br/>inference_engine/"]
        CLIOverrides["CLI Overrides<br/>key=value args"]
        EnvVars["Environment Variables<br/>from .env file"]
    end
    
    subgraph "Hydra Core"
        HydraCompose["hydra.compose()<br/>config_name + overrides"]
        ConfigDir["initialize_config_dir()<br/>version_base=1.3"]
        DictConfig["OmegaConf.DictConfig<br/>resolved config tree"]
    end
    
    subgraph "Model Configs"
        RFD3Configs["models/rfd3/configs/"]
        RF3Configs["models/rf3/configs/"]
    end
    
    YAMLBase --> HydraCompose
    YAMLExperiment --> HydraCompose
    YAMLInference --> HydraCompose
    CLIOverrides --> HydraCompose
    EnvVars -.->|loaded via dotenv| HydraCompose
    
    ConfigDir --> HydraCompose
    HydraCompose --> DictConfig
    
    RFD3Configs -.->|read by| ConfigDir
    RF3Configs -.->|read by| ConfigDir
```

**Configuration Composition**

Each model package contains a `configs/` directory with hierarchical YAML files. Hydra composes the final configuration by loading base configs and applying experiment-specific overrides.

**Inference Engine Initialization**

The `BaseInferenceEngine` [src/foundry/inference_engines/base.py:32-61]() handles the initialization logic for inference. It loads the training configuration stored within the checkpoint and applies runtime overrides [src/foundry/inference_engines/base.py:160-163]().

**Sources:** [src/foundry/inference_engines/base.py:32-205](), [models/rfd3/README.md:46-54]()

---

## Environment Configuration

The `.env` file provides system-wide configuration for external dependencies and resource locations. Foundry uses the [python-dotenv](https://pypi.org/project/python-dotenv/) library to load environment variables.

### Environment Variable Reference

```mermaid
graph TB
    subgraph "Data Mirrors"
        PDB_MIRROR["PDB_MIRROR_PATH<br/>Local PDB mirror"]
        CCD_MIRROR["CCD_MIRROR_PATH<br/>Local CCD mirror"]
        LOCAL_MSA["LOCAL_MSA_DIRS<br/>Pre-computed MSA storage"]
    end
    
    subgraph "External Tools"
        HBPLUS["HBPLUS_PATH<br/>Hydrogen bond calculation"]
        X3DNA["X3DNA_PATH<br/>DNA structure analysis"]
        DSSP["DSSP_PATH<br/>Secondary structure prediction"]
        HHFILTER["HHFILTER_PATH<br/>MSA filtering (HH-suite)"]
        MMSEQS2["MMSEQS2_PATH<br/>Fast sequence search"]
    end
    
    subgraph "MSA Databases"
        COLABFOLD_GPU["COLABFOLD_LOCAL_DB_PATH_GPU<br/>ColabFold DB (GPU)"]
        COLABFOLD_CPU["COLABFOLD_LOCAL_DB_PATH_CPU<br/>ColabFold DB (CPU)"]
    end
    
    subgraph "Checkpoint System"
        CHECKPOINT_DIRS["FOUNDRY_CHECKPOINT_DIRS<br/>Colon-separated search paths"]
    end
    
    subgraph "Usage"
        AtomWorks["AtomWorks<br/>Uses PDB/CCD mirrors"]
        RF3MSA["RF3<br/>Uses MSA databases"]
        Training["Training<br/>Uses HBPLUS, X3DNA"]
        Inference["Inference Engines<br/>Uses checkpoint dirs"]
    end
    
    PDB_MIRROR --> AtomWorks
    CCD_MIRROR --> AtomWorks
    
    COLABFOLD_GPU --> RF3MSA
    COLABFOLD_CPU --> RF3MSA
    
    HBPLUS --> Training
    X3DNA --> Training
    HHFILTER --> RF3MSA
    MMSEQS2 --> RF3MSA
    
    CHECKPOINT_DIRS --> Inference
```

### Mirror Setup

**PDB Mirror**
The `PDB_MIRROR_PATH` [.env:9-13]() points to a local mirror of the Protein Data Bank following RCSB conventions.

**CCD Mirror**
The `CCD_MIRROR_PATH` [.env:15-22]() points to a Chemical Component Dictionary mirror. If not provided, Foundry falls back to Biotite's internal CCD.

**External Tool Paths**
- **HBPLUS_PATH** [.env:29-32](): Used for hydrogen bond calculation during training and metrics computation.
- **X3DNA_PATH** [.env:34-36](): Used for DNA structure analysis.
- **MMSEQS2_PATH** [.env:46-48](): Used for fast sequence searching in RF3 pipelines.

**Sources:** [.env:1-63](), [models/rfd3/README.md:32-39](), [models/rfd3/README.md:106-115]()

---

## Training Infrastructure

Foundry utilizes **Lightning Fabric** to provide a flexible training harness that supports distributed execution, mixed precision, and hardware acceleration.

### FabricTrainer

The `FabricTrainer` [src/foundry/trainers/fabric.py:57-84]() is the base class for all training activities. It abstracts standard features like:
- **Gradient Accumulation** [src/foundry/trainers/fabric.py:101]()
- **Mixed Precision** [src/foundry/trainers/fabric.py:96-97]()
- **Distributed Training (DDP)** [src/foundry/trainers/fabric.py:90-91]()
- **EMA (Exponential Moving Average)** [src/foundry/trainers/fabric.py:30]()

### Hardware Support

Foundry supports a variety of hardware accelerators through Fabric:
- **CUDA**: Standard NVIDIA GPU acceleration.
- **XPU**: Native support for Intel GPUs using `XPUAccelerator` [src/foundry/utils/xpu/xpu_accelerator.py:9-14](), `SingleXPUStrategy` [src/foundry/utils/xpu/single_xpu_strategy.py:13-17](), and `XPUMixedPrecision` [src/foundry/utils/xpu/xpu_precision.py:11-16]().
- **MPS**: Support for Apple Silicon via community forks [README.md:28-36]().

**Sources:** [src/foundry/trainers/fabric.py:1-129](), [src/foundry/utils/xpu/__init__.py:1-27](), [README.md:18-43]()

---

## Logging Infrastructure

Foundry provides distributed-aware logging utilities that handle multi-GPU training and inference scenarios.

### RankedLogger

The `RankedLogger` class [src/foundry/utils/ddp.py:50-104]() extends Python's standard `LoggerAdapter` to provide rank-aware logging in distributed contexts. It automatically prefixes messages with rank information [src/foundry/utils/ddp.py:88-103]().

### Logging Configuration

**Minimal Inference Logging**
For inference workloads, `configure_minimal_inference_logging()` [src/foundry/utils/logging.py:98-124]() reduces logging verbosity by suppressing noisy loggers and setting the root level to `WARNING`.

**Warning Suppression**
The `suppress_warnings()` context manager [src/foundry/utils/logging.py:69-96]() provides scoped warning filtering, particularly useful for silencing common NumPy or Biotite warnings [src/foundry/utils/logging.py:30-67]().

**Sources:** [src/foundry/utils/logging.py:1-206](), [src/foundry/utils/ddp.py:50-104]()

---