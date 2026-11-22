# Configuration System

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.env](.env)
- [README.md](README.md)
- [models/rf3/configs/experiment/pretrained/rf3.yaml](models/rf3/configs/experiment/pretrained/rf3.yaml)
- [models/rf3/configs/inference.yaml](models/rf3/configs/inference.yaml)
- [models/rf3/configs/train.yaml](models/rf3/configs/train.yaml)
- [models/rf3/configs/validate.yaml](models/rf3/configs/validate.yaml)
- [models/rf3/src/rf3/callbacks/dump_validation_structures.py](models/rf3/src/rf3/callbacks/dump_validation_structures.py)
- [models/rf3/src/rf3/cli.py](models/rf3/src/rf3/cli.py)
- [models/rf3/src/rf3/utils/io.py](models/rf3/src/rf3/utils/io.py)
- [models/rfd3/README.md](models/rfd3/README.md)
- [models/rfd3/configs/dev.yaml](models/rfd3/configs/dev.yaml)
- [models/rfd3/configs/inference.yaml](models/rfd3/configs/inference.yaml)
- [models/rfd3/configs/train.yaml](models/rfd3/configs/train.yaml)
- [models/rfd3/configs/validate.yaml](models/rfd3/configs/validate.yaml)
- [models/rfd3/src/rfd3/cli.py](models/rfd3/src/rfd3/cli.py)
- [pyproject.toml](pyproject.toml)
- [src/foundry/inference_engines/base.py](src/foundry/inference_engines/base.py)
- [src/foundry/inference_engines/checkpoint_registry.py](src/foundry/inference_engines/checkpoint_registry.py)
- [src/foundry_cli/__init__.py](src/foundry_cli/__init__.py)
- [src/foundry_cli/download_checkpoints.py](src/foundry_cli/download_checkpoints.py)

</details>



## Purpose and Scope

This document describes the Hydra-based configuration system used throughout Foundry for managing inference and training parameters. The configuration system provides compositional YAML configurations with command-line override support, enabling flexible parameter management for all models including RFdiffusion3 (RFD3), RosettaFold3 (RF3), and ProteinMPNN.

For checkpoint-related path configuration, see **8.1 Checkpoint Management**. For environment variables and external paths, see **8.3 Environment Configuration**. For training-specific configuration details, see **8.4 Training Infrastructure**.

---

## System Architecture

Foundry's configuration system is built on [Hydra](https://hydra.cc/), which provides hierarchical configuration composition with command-line overrides. Each model package maintains its own configuration directory structure, allowing independent management while sharing common patterns.

### Configuration Flow Diagram

This diagram bridges the Natural Language space of user commands to the Code Entity space of Hydra functions and config files.

```mermaid
graph TB
    subgraph "User Input Layer"
        CLI["CLI Command<br/>'rfd3 design' or 'rf3 fold'"]
        CLIOverrides["Command-Line Overrides<br/>'out_dir=logs/' 'ckpt_path=rfd3'"]
        EnvFile[".env File<br/>'PDB_MIRROR_PATH'<br/>'FOUNDRY_CHECKPOINT_DIRS'"]
    end
    
    subgraph "Hydra Initialization Space"
        InitConfigDir["'initialize_config_dir()'<br/>version_base='1.3'"]
        Compose["'compose()'<br/>config_name='inference'<br/>overrides=args"]
    end
    
    subgraph "Config Directory Space"
        BaseConfig["'models/*/configs/'<br/>'inference.yaml'<br/>'train.yaml'"]
        InfEngineConfigs["'inference_engine/'<br/>'rfdiffusion3.yaml'<br/>'rf3.yaml'"]
        PathConfigs["'paths/'<br/>'default.yaml'"]
        TrainerConfigs["'trainer/'<br/>'rfd3_base.yaml'"]
        DatasetConfigs["'datasets/'<br/>'design_base.yaml'"]
    end
    
    subgraph "Configuration Composition"
        Defaults["'defaults' List<br/>Merging Strategy"]
        Resolution["Variable Resolution<br/>'${model.param}'<br/>'???' placeholders"]
        FinalConfig["'DictConfig' Object<br/>Fully Resolved"]
    end
    
    subgraph "Runtime Usage Space"
        InstantiateEngine["'BaseInferenceEngine' Setup<br/>'_target_': 'rfd3.engine.RFD3InferenceEngine'"]
        ConfigValidation["'prevalidate_inputs'<br/>Check '???' values"]
        ExecuteModel["'run_inference(cfg)'<br/>Execute Model Logic"]
    end
    
    CLI --> CLIOverrides
    EnvFile --> InitConfigDir
    CLIOverrides --> Compose
    
    InitConfigDir --> BaseConfig
    BaseConfig --> Defaults
    InfEngineConfigs --> Defaults
    PathConfigs --> Defaults
    TrainerConfigs --> Defaults
    DatasetConfigs --> Defaults
    
    Defaults --> Resolution
    Compose --> Resolution
    Resolution --> FinalConfig
    
    FinalConfig --> ConfigValidation
    ConfigValidation --> InstantiateEngine
    InstantiateEngine --> ExecuteModel
```

**Sources:** [models/rfd3/src/rfd3/cli.py:9-43](), [models/rf3/src/rf3/cli.py:9-70](), [pyproject.toml:26-28]()

---

## Configuration Directory Structure

Each model maintains a hierarchical configuration directory following Hydra conventions. These are typically located in `models/<model_name>/configs/`.

| Directory | Purpose | Example Files |
|-----------|---------|---------------|
| `configs/` | Root config directory | `inference.yaml`, `train.yaml`, `validate.yaml` |
| `inference_engine/` | Engine-specific parameters | `rfdiffusion3.yaml`, `rf3.yaml` |
| `paths/` | Data and output paths | `default.yaml` |
| `trainer/` | Training infrastructure settings | `rfd3_base.yaml` |
| `datasets/` | Dataset definitions | `design_base.yaml` |
| `experiment/` | Named hyperparameter sets | `pretrain.yaml` |

### Configuration File Locations

```mermaid
graph LR
    subgraph "RFD3 Package Space"
        RFD3Root["'models/rfd3/configs/'"]
        RFD3Inf["'inference_engine/rfdiffusion3.yaml'"]
        RFD3Train["'trainer/rfd3_base.yaml'"]
        RFD3Loss["'trainer/loss/losses/diffusion_loss.yaml'"]
    end
    
    subgraph "RF3 Package Space"
        RF3Root["'models/rf3/configs/'"]
        RF3Inf["'inference_engine/rf3.yaml'"]
        RF3Train["'trainer/???'"]
    end
    
    subgraph "Infrastructure Space"
        Paths["'paths/default.yaml'"]
        Logger["'logger/csv.yaml'"]
    end
    
    RFD3Root --> RFD3Inf
    RFD3Root --> RFD3Train
    RFD3Train --> RFD3Loss
    
    RF3Root --> RF3Inf
    RF3Root --> RF3Train
    
    RFD3Root --> Paths
    RF3Root --> Paths
    RFD3Root --> Logger
    RF3Root --> Logger
```

**Sources:** [models/rfd3/configs/train.yaml:1-19](), [models/rf3/configs/train.yaml:1-28](), [models/rfd3/configs/validate.yaml:1-19]()

---

## Hydra Configuration Composition

### Defaults System

Foundry configurations use a `defaults` list to compose multiple config files. The composition follows a merge strategy where later entries override earlier ones.

**Example from `models/rfd3/configs/train.yaml`:**

[models/rfd3/configs/train.yaml:7-19]()

```yaml
defaults:
  - model: rfd3_base
  - trainer: rfd3_base
  - datasets: design_base
  - callbacks: design_callbacks
  - dataloader: fast
  - paths: default
  - hydra: default
  - logger: default
  - _self_
  - experiment: ???
  - debug: null
```

The `_self_` keyword allows the current file to override values from the preceding items in the list. The `???` indicates a mandatory override required from the user or an experiment file.

### Variable Interpolation

Hydra supports variable interpolation using `${path.to.value}` syntax, allowing values to be shared across different config modules.

| Syntax | Meaning | Usage |
|--------|---------|-------|
| `${key}` | Reference within same config | `${seed}` |
| `${model.param}` | Reference nested key | Cross-module sharing |
| `???` | Required placeholder | Forces user override |
| `null` | Explicit empty value | Disables features |

**Sources:** [models/rfd3/configs/train.yaml:1-30](), [models/rf3/configs/train.yaml:1-48]()

---

## CLI Integration and Overrides

### Command-Line Override Mechanism

The `rfd3` and `rf3` CLI tools use `typer` to handle initial commands and then pass extra arguments directly to Hydra's `compose` function.

#### RFD3 CLI Logic
[models/rfd3/src/rfd3/cli.py:12-43]()
The `design` command identifies the config directory, appends a default `inference_engine=rfdiffusion3` if missing, and initializes Hydra with `initialize_config_dir`.

#### RF3 CLI Logic
[models/rf3/src/rf3/cli.py:40-69]()
The `fold` command supports "old style" positional arguments (mapped to `inputs=`) and "new style" Hydra overrides. It defaults to `inference_engine=rf3`.

### Common Override Patterns

| Override Type | Syntax Example | Description |
|---------------|----------------|-------------|
| Simple value | `out_dir=logs/test` | Set output path |
| Nested value | `inference_sampler.num_timesteps=50` | Change sampling depth |
| Config group | `experiment=pretrain` | Switch entire config set |
| Boolean | `dump_trajectories=True` | Enable trajectory saving |

**Sources:** [models/rfd3/src/rfd3/cli.py:9-43](), [models/rf3/src/rf3/cli.py:9-70](), [models/rfd3/README.md:45-54]()

---

## BaseInferenceEngine Integration

The `BaseInferenceEngine` class is responsible for resolving overrides and merging them with the configuration stored inside model checkpoints.

### Config Merging Flow
[src/foundry/inference_engines/base.py:129-142]()
1. The engine loads the checkpoint using `torch.load`.
2. It extracts `train_cfg` from the checkpoint.
3. It calls `_override_checkpoint_config`, which uses `OmegaConf.merge` to apply user-provided `self.overrides`.

### Programmatic Overrides
[src/foundry/inference_engines/base.py:102-120]()
The engine constructor accepts several override dictionaries:
- `transform_overrides`
- `inference_sampler_overrides`
- `trainer_overrides`

These are converted to dotted-path keys (e.g., `model.net.inference_sampler.num_timesteps`) via `_assign_override` and merged into the final configuration.

**Sources:** [src/foundry/inference_engines/base.py:28-30](), [src/foundry/inference_engines/base.py:102-120](), [src/foundry/inference_engines/base.py:160-163]()

---

## Environment Variable Integration

The configuration system interacts with the environment via the `.env` file and `os.environ`.

### .env File Loading
Foundry uses `dotenv.load_dotenv(override=True)` to load variables from a `.env` file into the environment.

### Key Environment Variables
[.env:1-63]()
- `FOUNDRY_CHECKPOINT_DIRS`: Search paths for model weights.
- `PDB_MIRROR_PATH`: Path to local PDB structures.
- `CCD_MIRROR_PATH`: Path to local Chemical Component Dictionary.
- `HBPLUS_PATH`: Path to the `hbplus` tool for hydrogen bond analysis.

### Variable Resolution in Code
[src/foundry/inference_engines/checkpoint_registry.py:25-41]()
Functions like `get_default_checkpoint_dirs` explicitly check `os.environ.get("FOUNDRY_CHECKPOINT_DIRS")` to build search paths, which are then used by the `RegisteredCheckpoint` class to find model files.

**Sources:** [.env:1-63](), [src/foundry/inference_engines/checkpoint_registry.py:25-41](), [src/foundry_cli/download_checkpoints.py:27]()

---

## Config Discovery and Path Resolution

Foundry models implement logic to find their configuration files regardless of whether they are installed as packages or running in a development clone.

### Path Resolution Logic
[models/rfd3/src/rfd3/cli.py:19-24]()
The CLI checks for a `configs` directory relative to the file location. If `../../../../configs` exists, it assumes development mode; otherwise, it falls back to the package location.

### Hydra Search Path
[models/rfd3/configs/train.yaml:2-5]()
Configurations often specify a `hydra.searchpath` to include package-specific configurations:
```yaml
hydra:
  searchpath:
    - pkg://rfd3.configs
    - pkg://configs
```

**Sources:** [models/rfd3/src/rfd3/cli.py:14-24](), [models/rf3/src/rf3/cli.py:25-38](), [models/rfd3/configs/train.yaml:2-5]()

---