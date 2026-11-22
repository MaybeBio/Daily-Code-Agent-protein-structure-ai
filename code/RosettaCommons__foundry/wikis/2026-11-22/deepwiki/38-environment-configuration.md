# Environment Configuration

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.env](.env)
- [README.md](README.md)
- [models/rfd3/README.md](models/rfd3/README.md)
- [models/rfd3/configs/datasets/train/pdb/af3_train_interface.yaml](models/rfd3/configs/datasets/train/pdb/af3_train_interface.yaml)
- [models/rfd3/configs/datasets/train/pdb/af3_train_pn_unit.yaml](models/rfd3/configs/datasets/train/pdb/af3_train_pn_unit.yaml)
- [models/rfd3/configs/logger/default.yaml](models/rfd3/configs/logger/default.yaml)
- [models/rfd3/configs/paths/data/default.yaml](models/rfd3/configs/paths/data/default.yaml)
- [src/foundry/inference_engines/base.py](src/foundry/inference_engines/base.py)
- [src/foundry/inference_engines/checkpoint_registry.py](src/foundry/inference_engines/checkpoint_registry.py)
- [src/foundry_cli/__init__.py](src/foundry_cli/__init__.py)
- [src/foundry_cli/download_checkpoints.py](src/foundry_cli/download_checkpoints.py)

</details>



## Purpose and Scope

This page documents Foundry's environment configuration system, which controls paths to model checkpoints, data mirrors, MSA directories, and external tools. Environment variables are used throughout Foundry to enable flexible deployment across different computing environments without hardcoding paths.

For checkpoint management and download procedures, see [Checkpoint Management](8.1). For Hydra-based configuration of model training and inference parameters, see [Configuration System](8.2).

---

## Overview

Foundry uses environment variables to configure:
- **Checkpoint storage**: Where model weights are stored and loaded from.
- **Data mirrors**: Local copies of PDB and CCD databases for offline operation.
- **MSA directories**: Paths to precomputed multiple sequence alignments.
- **External tools**: Paths to third-party binaries (HBPLUS, x3dna, mmseqs2, etc.).

The recommended approach is to create a `.env` file in the repository root and use `python-dotenv` to automatically load these variables.

**Sources**: [.env:1-63](), [src/foundry_cli/download_checkpoints.py:9-27]()

---

## Environment Variable Loading

Foundry utilizes `python-dotenv` to load configurations from a `.env` file into the process environment. This occurs early in the execution of CLI tools and inference engines.

**Diagram: Configuration Loading Data Flow**

Title: Environment Variable Resolution and Application Flow
```mermaid
graph TB
    subgraph "ConfigurationSources" ["Configuration Sources"]
        EnvFile[".env file<br/>(repository root)"]
        SysEnv["System Environment<br/>Variables"]
        Defaults["Hardcoded Defaults<br/>(fallback)"]
    end
    
    subgraph "LoadingProcess" ["Loading Process"]
        DotenvLoad["python-dotenv<br/>load_dotenv()"]
        EnvLookup["os.environ.get()"]
    end
    
    subgraph "ApplicationLayer" ["Application Layer"]
        CheckpointReg["checkpoint_registry.py<br/>get_default_checkpoint_dirs()"]
        Parser["AtomWorks Parser<br/>PDB/CCD loading"]
        Tools["External Tool Wrappers<br/>(HBPLUS, x3dna, etc.)"]
        MSA["MSA Loading<br/>(RF3 pipelines)"]
    end
    
    EnvFile --> DotenvLoad
    DotenvLoad --> SysEnv
    SysEnv --> EnvLookup
    Defaults --> EnvLookup
    
    EnvLookup --> CheckpointReg
    EnvLookup --> Parser
    EnvLookup --> Tools
    EnvLookup --> MSA
```

**Priority Order**:
1. System environment variables (highest priority).
2. Variables defined in `.env` file.
3. Hardcoded defaults in code (lowest priority).

**Sources**: [src/foundry_cli/download_checkpoints.py:9-27](), [src/foundry/inference_engines/checkpoint_registry.py:8-32]()

---

## Core Environment Variables

### Checkpoint Configuration

Foundry manages checkpoints through a search path system.

| Variable | Purpose | Default | Used By |
|----------|---------|---------|---------|
| `FOUNDRY_CHECKPOINT_DIRS` | Colon-separated list of checkpoint directories to search | `~/.foundry/checkpoints` | All inference engines |
| `FOUNDRY_CHECKPOINTS_DIR` | Single checkpoint directory (backward compatibility) | `~/.foundry/checkpoints` | All inference engines |

The `get_default_checkpoint_dirs` function [src/foundry/inference_engines/checkpoint_registry.py:25-42]() resolves these variables into a prioritized list of `Path` objects.

```python
# From RegisteredCheckpoint.get_default_path()
def get_default_path(self):
    checkpoint_dirs = get_default_checkpoint_dirs()
    for checkpoint_dir in checkpoint_dirs:
        candidate = checkpoint_dir / self.filename
        if candidate.exists():
            return candidate
    return checkpoint_dirs[0] / self.filename  # Default to first dir
```

The `foundry install` command can persist new checkpoint directories to your `.env` file using `append_checkpoint_to_env` [src/foundry/inference_engines/checkpoint_registry.py:49-61]().

**Sources**: [.env:61-63](), [src/foundry/inference_engines/checkpoint_registry.py:25-42,71-77](), [src/foundry_cli/download_checkpoints.py:33-51]()

---

### Data Mirrors

#### PDB_MIRROR_PATH
Local mirror of the RCSB Protein Data Bank. AtomWorks uses this for offline structure loading [README.md:112-115](). It expects the standard RCSB flat-file structure: `{PDB_MIRROR_PATH}/{middle_two_chars}/{pdb_id}.cif.gz`.

**Sources**: [.env:9-13](), [models/rfd3/README.md:108-115]()

#### CCD_MIRROR_PATH
Local mirror of the Chemical Component Dictionary (ligand definitions). It follows the convention: `{CCD_MIRROR_PATH}/{first_char}/{ccd_name}/{ccd_name}.cif`. If unset, the system falls back to the internal Biotite CCD [env:15-22]().

**Sources**: [.env:15-22](), [models/rfd3/README.md:115-115]()

#### LOCAL_MSA_DIRS
Colon-separated list of paths to directories containing precomputed MSAs. Used primarily by RF3 for training and inference pipelines [.env:24-25]().

---

### External Tool Dependencies

Foundry integrates with several third-party tools for structural analysis and feature generation.

| Variable | Tool | Purpose | Required For |
|----------|------|---------|--------------|
| `HBPLUS_PATH` | HBPLUS | Hydrogen bond calculation | RFD3 H-bond conditioning [models/rfd3/README.md:32-38]() |
| `X3DNA_PATH` | x3dna-v2.4 | DNA structure analysis | DNA-containing structures [.env:34-36]() |
| `DSSP_PATH` | DSSP | Secondary structure prediction | Currently unused [.env:38-39]() |
| `HHFILTER_PATH` | HH-suite | MSA filtering | MSA preprocessing [.env:41-44]() |
| `MMSEQS2_PATH` | MMseqs2 | Sequence searching | MSA generation [.env:46-48]() |

**Sources**: [.env:29-48](), [models/rfd3/README.md:32-38]()

---

### CollabFold Database Paths

For performance, MMseqs2 databases used by CollabFold should be stored on local compute node drives [.env:50-55]().

- `COLABFOLD_LOCAL_DB_PATH_GPU`: Local GPU-optimized database.
- `COLABFOLD_LOCAL_DB_PATH_CPU`: Local CPU-optimized database.
- `COLABFOLD_NET_DB_PATH_GPU`: Network-accessible fallback (GPU).
- `COLABFOLD_NET_DB_PATH_CPU`: Network-accessible fallback (CPU).

**Sources**: [.env:50-60]()

---

## Environment Variables to Code Entities Mapping

This diagram illustrates how environment variables propagate through the `BaseInferenceEngine` and CLI utilities.

Title: Environment Variables to Code Entity Mapping
```mermaid
graph TB
    subgraph "EnvVars" ["Environment Variables"]
        CKPT_DIRS["FOUNDRY_CHECKPOINT_DIRS"]
        PDB["PDB_MIRROR_PATH"]
        HBPLUS["HBPLUS_PATH"]
    end
    
    subgraph "Registry" ["checkpoint_registry.py"]
        GetCkptDirs["get_default_checkpoint_dirs()"]
        RegCkpt["RegisteredCheckpoint"]
        CKPT_MAP["REGISTERED_CHECKPOINTS"]
    end
    
    subgraph "CLI" ["foundry_cli/"]
        InstallCmd["install_model()"]
        Download["download_file()"]
    end
    
    subgraph "Engines" ["foundry/inference_engines/"]
        BaseEng["BaseInferenceEngine"]
        RFD3Eng["RFD3InferenceEngine"]
    end

    CKPT_DIRS --> GetCkptDirs
    GetCkptDirs --> RegCkpt
    RegCkpt --> CKPT_MAP
    
    CKPT_MAP --> BaseEng
    BaseEng --> RFD3Eng
    
    GetCkptDirs --> InstallCmd
    InstallCmd --> Download
    
    PDB --> RFD3Eng
    HBPLUS --> RFD3Eng
```

**Sources**: [src/foundry/inference_engines/checkpoint_registry.py:25-80](), [src/foundry/inference_engines/base.py:71-91](), [src/foundry_cli/download_checkpoints.py:106-142]()

---

## Setting Up Your Environment

### Step 1: Initialize .env
Copy the template provided in the repository root:
```bash
cp .env.example .env
```
Update `FOUNDRY_CHECKPOINT_DIRS` and `HBPLUS_PATH` as needed.

### Step 2: Install Checkpoints
The `foundry install` command uses the search path logic to determine the primary installation target [src/foundry_cli/download_checkpoints.py:166-170]().

```bash
foundry install base-models --checkpoint-dir ~/.foundry/checkpoints
```

**Sources**: [README.md:44-48](), [src/foundry_cli/download_checkpoints.py:144-186]()

---

## Low Memory Mode

RFD3 supports a memory-efficient tokenization mode toggled via environment variable. This is typically managed by the `RFD3InferenceEngine` based on the `low_memory_mode` flag.

```python
# Internal behavior in RFD3
if low_memory_mode:
    os.environ["RFD3_LOW_MEMORY_MODE"] = "1"
```

**Sources**: [models/rfd3/src/rfd3/engine.py:68-71,195-198]() (Reference to conceptual usage in engine)

---

## Troubleshooting

### Checkpoint Resolution Order
Foundry searches directories in the following order:
1. Any directory passed explicitly via `--checkpoint-dir` in CLI [src/foundry_cli/download_checkpoints.py:33-40]().
2. Directories in `FOUNDRY_CHECKPOINT_DIRS` [.env:61-63]().
3. The default `~/.foundry/checkpoints` [src/foundry/inference_engines/checkpoint_registry.py:10-10]().

### Verifying Installation
Use the CLI to inspect the environment's view of installed models:
```bash
foundry list-installed
```
This command iterates through all resolved `checkpoint_dirs` and identifies `.ckpt` or `.pt` files [src/foundry_cli/download_checkpoints.py:196-210]().

**Sources**: [src/foundry/inference_engines/checkpoint_registry.py:25-42](), [src/foundry_cli/download_checkpoints.py:196-210]()

---