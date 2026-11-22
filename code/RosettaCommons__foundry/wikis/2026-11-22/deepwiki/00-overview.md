# Overview

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.env](.env)
- [CONTRIBUTING.md](CONTRIBUTING.md)
- [README.md](README.md)
- [docs/docs_requirements.txt](docs/docs_requirements.txt)
- [docs/source/_static/ga.js](docs/source/_static/ga.js)
- [docs/source/conf.py](docs/source/conf.py)
- [docs/source/contributing_link.rst](docs/source/contributing_link.rst)
- [docs/source/index.rst](docs/source/index.rst)
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



## Purpose and Scope

Foundry is a unified platform for training and deploying protein design models, providing infrastructure for three complementary deep learning systems: **RFdiffusion3 (RFD3)** for all-atom generative design, **RosettaFold3 (RF3)** for structure prediction, and **ProteinMPNN/LigandMPNN** for sequence design. All models share a common foundation built on [AtomWorks](https://github.com/RosettaCommons/atomworks), ensuring consistent biomolecular structure handling across training and inference workflows.

This page provides an architectural overview of the Foundry ecosystem. For installation instructions, see [Getting Started](#2). For model-specific documentation, see [RFdiffusion3 (RFD3)](#4), [RosettaFold3 (RF3)](#5), and [ProteinMPNN and LigandMPNN](#6). For infrastructure details, see [Infrastructure and Configuration](#8) and [Advanced Topics](#9).

Sources: [README.md:1-6]()

---

## Core Architecture

Foundry follows a strict dependency hierarchy where all model packages depend on a shared core, which in turn depends on AtomWorks for structure handling. This architecture enables independent model installation while maintaining consistency across the platform.

### System Dependency Hierarchy

```mermaid
graph TB
    subgraph UserInterface["User Interface Layer"]
        FoundryCLI["foundry CLI<br/>foundry_cli.download_checkpoints:app"]
        RFD3CLI["rfd3 CLI<br/>rfd3.cli:app"]
        RF3CLI["rf3 CLI<br/>rf3.cli:app"]
        MPNNCLI["mpnn CLI<br/>mpnn.inference:main"]
        PythonAPI["Python API<br/>InferenceEngine classes"]
    end
    
    subgraph FoundryCore["Foundry Core (src/foundry/)"]
        BaseEngine["BaseInferenceEngine<br/>inference_engines/base.py:32"]
        CheckpointReg["REGISTERED_CHECKPOINTS<br/>checkpoint_registry.py:80"]
        FabricTrainer["FabricTrainer<br/>trainers/fabric.py"]
        MetricMgr["MetricManager<br/>metrics/metric.py"]
        RankedLogger["RankedLogger<br/>utils/ddp.py:50"]
    end
    
    subgraph AtomWorks["AtomWorks Foundation (External)"]
        AtomArray["biotite.structure.AtomArray<br/>Core data structure"]
        ParseFunc["atomworks.io.parse()<br/>Structure parsing"]
        TokenUtils["atomworks.ml.utils.token<br/>get_token_starts()"]
    end
    
    subgraph ModelPackages["Model Packages (models/*)"]
        RFD3Eng["RFD3InferenceEngine<br/>rfd3/src/rfd3/engine.py:135"]
        RF3Eng["RF3InferenceEngine<br/>rf3/src/rf3/inference_engines/rf3.py"]
        MPNNEng["MPNNInferenceEngine<br/>mpnn/src/mpnn/inference_engines/mpnn.py:37"]
    end
    
    FoundryCLI --> CheckpointReg
    RFD3CLI --> RFD3Eng
    RF3CLI --> RF3Eng
    MPNNCLI --> MPNNEng
    PythonAPI --> BaseEngine
    
    RFD3Eng --> BaseEngine
    RF3Eng --> BaseEngine
    MPNNEng -.uses.-> CheckpointReg
    
    BaseEngine --> FabricTrainer
    BaseEngine --> MetricMgr
    BaseEngine --> RankedLogger
    
    RFD3Eng --> AtomArray
    RF3Eng --> AtomArray
    MPNNEng --> AtomArray
    
    FabricTrainer --> AtomArray
    MetricMgr --> AtomArray
    
    AtomArray --> ParseFunc
    AtomArray --> TokenUtils
```

**Dependency Flow**: `models` → `foundry` → `atomworks` → `biotite`

The strict dependency hierarchy ensures:
- **No circular dependencies**: Models depend on foundry core, not vice versa [README.md:112-117]().
- **Shared infrastructure**: All models use the same `BaseInferenceEngine` [src/foundry/inference_engines/base.py:32-35]().
- **Consistent data structures**: All models operate on `biotite.structure.AtomArray` objects via AtomWorks [README.md:5-6]().
- **Independent installation**: Each model can be installed separately or as a group [pyproject.toml:54-70]().

| Component | Location | Key Classes | Purpose |
|-----------|----------|-------------|---------|
| **foundry** | `src/foundry/` | `BaseInferenceEngine`, `FabricTrainer` | Shared training/inference infrastructure [pyproject.toml:118]() |
| **AtomWorks** | External | `AtomArray` (via Biotite) | Structure I/O, preprocessing, featurization [README.md:5]() |
| **rfd3** | `models/rfd3/` | `RFD3InferenceEngine` | All-atom generative protein design [README.md:71-73]() |
| **rf3** | `models/rf3/` | `RF3InferenceEngine` | Structure prediction with confidence scores [README.md:91-93]() |
| **mpnn** | `models/mpnn/` | `MPNNInferenceEngine` | Fixed-backbone sequence design [README.md:101-102]() |

Sources: [README.md:1-117](), [pyproject.toml:54-124](), [src/foundry/inference_engines/base.py:32-35]()

---

## The Three Models

### RFdiffusion3 (RFD3)

**All-atom generative design** via conditional diffusion. Generates novel protein backbones under complex constraints including small molecule binding, enzyme active sites, protein-protein interfaces, and nucleic acid interactions [models/rfd3/README.md:1-4]().

**Key capabilities**:
- Small molecule binder design [models/rfd3/README.md:82-84]().
- Enzyme design [models/rfd3/README.md:92-94]().
- Protein binder design with hotspot targeting [models/rfd3/README.md:86-88]().
- Nucleic acid complex design (via RFD3NA) [README.md:81-83]().
- Symmetric oligomer design [models/rfd3/README.md:96-98]().

**Entry point**: `rfd3` CLI mapping to `rfd3.cli:app` [pyproject.toml:91]().

Sources: [README.md:71-90](), [models/rfd3/README.md:1-100](), [pyproject.toml:91]()

### RosettaFold3 (RF3)

**All-atom structure prediction** for proteins, nucleic acids, small molecules, and their complexes [README.md:91-93]().

**Key capabilities**:
- Protein-DNA/RNA complex prediction [README.md:95-97]().
- Confidence scoring for designability validation [README.md:93]().
- MSA processing and template selection [models/rf3/src/rf3/cli.py:12-18]().

**Entry point**: `rf3` CLI mapping to `rf3.cli:app` [pyproject.toml:90]().

Sources: [README.md:91-99](), [pyproject.toml:90](), [models/rf3/src/rf3/cli.py:1-86]()

### ProteinMPNN and LigandMPNN

**Inverse folding** models that design amino acid sequences to fold into target backbone structures [README.md:101-102]().

**Key capabilities**:
- Sequence design for fixed backbones [README.md:102]().
- Ligand-aware design (LigandMPNN) [README.md:102]().
- Soluble protein optimization (SolubleMPNN) [src/foundry/inference_engines/checkpoint_registry.py:117-121]().

**Entry point**: `mpnn` CLI mapping to `mpnn.inference:main` [pyproject.toml:93]().

Sources: [README.md:101-105](), [pyproject.toml:93](), [src/foundry/inference_engines/checkpoint_registry.py:96-121]()

---

## Checkpoint Management

Foundry provides centralized checkpoint management through the `foundry` CLI and a registry system. All checkpoints are tracked in `REGISTERED_CHECKPOINTS` and resolved automatically.

### Checkpoint Registry System

```mermaid
graph TB
    subgraph Environment["Environment (.env)"]
        EnvVar["FOUNDRY_CHECKPOINT_DIRS<br/>colon-separated paths"]
        DefaultDir["DEFAULT_CHECKPOINT_DIR<br/>~/.foundry/checkpoints"]
    end
    
    subgraph Registry["Registry (checkpoint_registry.py)"]
        RegDict["REGISTERED_CHECKPOINTS<br/>Dict[str, RegisteredCheckpoint]"]
        RFD3Entry["'rfd3'<br/>RegisteredCheckpoint(url=..., filename='rfd3_latest.ckpt')"]
        RF3Entry["'rf3'<br/>RegisteredCheckpoint(url=..., filename='rf3_foundry_01_24...')"]
        ProteinMPNN["'proteinmpnn'<br/>RegisteredCheckpoint(url=..., filename='proteinmpnn_v_48_020.pt')"]
    end
    
    subgraph CLI["CLI Commands (foundry_cli/download_checkpoints.py)"]
        InstallCmd["install(models, checkpoint_dir)<br/>foundry_cli.download_checkpoints:install"]
        ListAvail["list-available()<br/>foundry_cli.download_checkpoints:list_available"]
        ListInst["list-installed()<br/>foundry_cli.download_checkpoints:list_installed"]
    end
    
    subgraph Engines["Inference Engines"]
        BaseInit["BaseInferenceEngine<br/>src/foundry/inference_engines/base.py"]
        GetDefPath["RegisteredCheckpoint.get_default_path()<br/>src/foundry/inference_engines/checkpoint_registry.py:71"]
    end
    
    EnvVar --> InstallCmd
    DefaultDir --> GetDefPath
    
    RegDict --> RFD3Entry
    RegDict --> RF3Entry
    RegDict --> ProteinMPNN
    
    InstallCmd --> RFD3Entry
    ListAvail --> RegDict
    ListInst --> DefaultDir
    
    BaseInit --> GetDefPath
    GetDefPath --> RegDict
```

**CLI Usage**:
```bash
# Install latest RFD3, RF3 and MPNN variants
foundry install base-models

# List available models in registry
foundry list-available

# List installed checkpoints and search paths
foundry list-installed
```

**Checkpoint Resolution**: Foundry searches `~/.foundry/checkpoints` plus any colon-separated entries in `$FOUNDRY_CHECKPOINT_DIRS` [README.md:44-48]().

Sources: [README.md:44-56](), [src/foundry/inference_engines/checkpoint_registry.py:1-122](), [src/foundry_cli/download_checkpoints.py:1-198](), [pyproject.toml:94]()

---

## Configuration System

Foundry uses **Hydra** for configuration management. Models define configs in `models/*/configs/`, composed at runtime with CLI overrides.

### Configuration Composition Flow

```mermaid
graph TB
    subgraph EnvLayer["Environment Layer (.env)"]
        DotEnv[".env file<br/>loaded via load_dotenv()"]
        EnvVars["Paths:<br/>PDB_MIRROR_PATH<br/>CCD_MIRROR_PATH<br/>HBPLUS_PATH"]
    end
    
    subgraph HydraConfigs["Hydra Config Directory (models/*/configs/)"]
        ConfigYAML["inference.yaml<br/>Top-level config"]
        InfEngineYAML["inference_engine/rf3.yaml<br/>Model settings"]
    end
    
    subgraph Runtime["Runtime Composition"]
        HydraInit["initialize_config_dir()<br/>models/rf3/src/rf3/cli.py:64"]
        CLIOverrides["CLI overrides:<br/>inputs=path/to/file.cif"]
        Compose["hydra.compose()<br/>models/rf3/src/rf3/cli.py:65"]
    end
    
    DotEnv --> EnvVars
    ConfigYAML --> HydraInit
    InfEngineYAML --> HydraInit
    CLIOverrides --> Compose
    HydraInit --> Compose
    Compose --> FinalCfg["Final DictConfig"]
```

**Environment Configuration**: The `.env` file stores paths to external tools (e.g., `HBPLUS_PATH`) and data mirrors (`PDB_MIRROR_PATH`, `CCD_MIRROR_PATH`) [.env:1-63]().

Sources: [.env:1-63](), [models/rf3/src/rf3/cli.py:4-69](), [models/rfd3/src/rfd3/cli.py:1-48]()

---

## External Dependencies

Foundry relies on several external tools for specialized functionality:

| Tool | Purpose | Environment Variable |
|------|---------|----------------------|
| **HBPLUS** | Hydrogen bond calculation during training and metrics [models/rfd3/README.md:32-38]() | `HBPLUS_PATH` [.env:29-32]() |
| **x3dna** | DNA structure analysis [.env:34-36]() | `X3DNA_PATH` [.env:36]() |
| **mmseqs2** | Fast sequence searching [.env:46-48]() | `MMSEQS2_PATH` [.env:48]() |
| **hhfilter** | Filtering MSAs to reduce redundancy [.env:41-44]() | `HHFILTER_PATH` [.env:44]() |

Sources: [.env:1-63](), [models/rfd3/README.md:32-38]()

---