# Distributed Training and Inference

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [models/mpnn/src/mpnn/inference_engines/mpnn.py](models/mpnn/src/mpnn/inference_engines/mpnn.py)
- [models/mpnn/src/mpnn/model/mpnn.py](models/mpnn/src/mpnn/model/mpnn.py)
- [models/rf3/configs/inference_engine/base.yaml](models/rf3/configs/inference_engine/base.yaml)
- [models/rf3/configs/inference_engine/rf3.yaml](models/rf3/configs/inference_engine/rf3.yaml)
- [models/rf3/configs/trainer/xpu.yaml](models/rf3/configs/trainer/xpu.yaml)
- [models/rf3/src/rf3/data/extra_xforms.py](models/rf3/src/rf3/data/extra_xforms.py)
- [models/rf3/src/rf3/data/pipelines.py](models/rf3/src/rf3/data/pipelines.py)
- [models/rf3/src/rf3/inference.py](models/rf3/src/rf3/inference.py)
- [models/rf3/src/rf3/inference_engines/rf3.py](models/rf3/src/rf3/inference_engines/rf3.py)
- [models/rf3/src/rf3/symmetry/resolve.py](models/rf3/src/rf3/symmetry/resolve.py)
- [models/rf3/src/rf3/utils/inference.py](models/rf3/src/rf3/utils/inference.py)
- [models/rfd3/configs/trainer/xpu.yaml](models/rfd3/configs/trainer/xpu.yaml)
- [src/foundry/trainers/fabric.py](src/foundry/trainers/fabric.py)
- [src/foundry/utils/ddp.py](src/foundry/utils/ddp.py)
- [src/foundry/utils/xpu/__init__.py](src/foundry/utils/xpu/__init__.py)
- [src/foundry/utils/xpu/single_xpu_strategy.py](src/foundry/utils/xpu/single_xpu_strategy.py)
- [src/foundry/utils/xpu/xpu_accelerator.py](src/foundry/utils/xpu/xpu_accelerator.py)
- [src/foundry/utils/xpu/xpu_precision.py](src/foundry/utils/xpu/xpu_precision.py)

</details>



This page documents the distributed training and inference infrastructure in Foundry, which enables efficient training and inference across multiple GPUs and multiple nodes using Lightning Fabric. The system provides transparent abstractions for data parallelism, gradient synchronization, and checkpoint management, with native support for NVIDIA GPUs, Intel XPUs, and Apple MPS.

For model-specific training details, see [RF3 Training](#5.8) and [RFD3 Training](#4.6). For the underlying training infrastructure components, see [Training Infrastructure](#8.4).

## Overview

Foundry's distributed system is built on **Lightning Fabric**, which provides hardware-agnostic abstractions for distributed computing. The core component is `FabricTrainer`, a base class that handles:

- Multi-GPU training within a single node.
- Multi-node training across compute clusters.
- Intel XPU support via custom accelerator and precision plugins [src/foundry/utils/xpu/__init__.py:1-27]().
- Distributed data loading with proper rank-based sharding.
- Gradient accumulation and synchronization [src/foundry/trainers/fabric.py:101-128]().
- Checkpoint saving/loading in distributed contexts.
- Mixed precision training (fp16, bf16).

The system supports multiple distribution strategies, with **DDP (Distributed Data Parallel)** as the primary approach for model parallelism.

**Sources:** [src/foundry/trainers/fabric.py:57-128](), [src/foundry/utils/xpu/__init__.py:1-27]()

## Architecture Overview

```mermaid
graph TB
    subgraph "User Entry Points"
        TrainScript["train.py / validate.py"]
        InferenceScript["inference.py"]
        HydraConfig["Hydra Configuration<br/>trainer.*, datasets.*"]
    end
    
    subgraph "Lightning Fabric Layer"
        Fabric["lightning.Fabric<br/>accelerator, strategy,<br/>devices, num_nodes"]
        DDPStrategy["DDPStrategy<br/>timeout, process_group"]
        XPUComponents["XPUAccelerator / XPUMixedPrecision<br/>Intel GPU Support"]
    end
    
    subgraph "FabricTrainer Core"
        FabricTrainer["FabricTrainer<br/>Base ABC"]
        Setup["setup_model_optimizers_<br/>and_schedulers()"]
        FitLoop["fit()<br/>Training loop"]
        ValLoop["validation_loop()"]
    end
    
    subgraph "Data Distribution"
        DistLoader["assemble_distributed_loader()"]
        LoadBalancedSampler["LoadBalancedDistributedSampler<br/>rank-aware sharding"]
        FabricDataLoader["_FabricDataLoader<br/>wrapped loaders"]
    end
    
    subgraph "Model & Optimizer Setup"
        ModelConstruct["construct_model()"]
        OptimizerConstruct["construct_optimizer()"]
        FabricSetup["fabric.setup()<br/>Wrap for distribution"]
    end
    
    TrainScript --> HydraConfig
    HydraConfig --> FabricTrainer
    FabricTrainer --> Fabric
    Fabric --> DDPStrategy
    Fabric --> XPUComponents
    
    FabricTrainer --> Setup
    Setup --> ModelConstruct
    Setup --> OptimizerConstruct
    Setup --> FabricSetup
    
    FabricTrainer --> FitLoop
    FabricTrainer --> ValLoop
    
    FitLoop --> DistLoader
    DistLoader --> LoadBalancedSampler
    DistLoader --> FabricDataLoader
```

**Sources:** [src/foundry/trainers/fabric.py:57-128](), [src/foundry/utils/xpu/xpu_accelerator.py:9-15](), [models/rf3/src/rf3/inference_engines/rf3.py:17-17]()

## FabricTrainer: Core Training Harness

### Initialization and Configuration

The `FabricTrainer` class [src/foundry/trainers/fabric.py:57-128]() wraps Lightning Fabric and provides a standardized interface for distributed training:

| Parameter | Type | Purpose |
|-----------|------|---------|
| `accelerator` | str \| Accelerator | Hardware type: "cpu", "cuda", "gpu", "mps", "xpu", "auto" |
| `strategy` | str \| Strategy | Distribution strategy: "ddp", "ddp_spawn", "fsdp", "deepspeed" |
| `devices_per_node` | int \| list \| str | Number/list of devices per node or "auto" |
| `num_nodes` | int | Number of machines for multi-node training |
| `precision` | str \| int | Numeric precision: "32-true", "16-mixed", "bf16-mixed" |
| `grad_accum_steps` | int | Gradient accumulation steps before optimizer.step() |
| `nccl_timeout` | int | NCCL timeout in seconds (default: 3200) |

**XPU Support:** If Intel XPUs are detected, the system automatically configures the `XPUAccelerator` and `XPUMixedPrecision` plugin [src/foundry/utils/ddp.py:39-41](). `XPUMixedPrecision` overrides the default behavior to use `torch.autocast(device_type="xpu")` [src/foundry/utils/xpu/xpu_precision.py:44-49]().

**Sources:** [src/foundry/trainers/fabric.py:57-128](), [src/foundry/utils/ddp.py:22-55](), [src/foundry/utils/xpu/xpu_precision.py:11-49]()

### Process Spawning and Setup

```mermaid
sequenceDiagram
    participant Main as Main Process
    participant Fabric as Fabric Instance
    participant Trainer as FabricTrainer
    participant R0 as Rank 0
    participant R1 as Rank 1..N
    
    Main->>Trainer: instantiate trainer
    Main->>Trainer: fit(train_loader, val_loaders)
    
    Trainer->>Fabric: fabric.launch()
    Note over Fabric: Spawn N processes
    
    Fabric-->>R0: Initialize Rank 0
    Fabric-->>R1: Initialize Rank 1..N
    
    R0->>Fabric: setup_dataloaders(train_loader)
    R1->>Fabric: setup_dataloaders(train_loader)
    
    R0->>Trainer: setup_model_optimizers_and_schedulers()
    R1->>Trainer: setup_model_optimizers_and_schedulers()
    
    Note over R0,R1: Models wrapped in DDP / SingleDevice
```

**Sources:** [src/foundry/trainers/fabric.py:57-128](), [src/foundry/utils/xpu/single_xpu_strategy.py:13-48]()

## Distributed Data Loading

### Load Balancing

For inference, especially in models like RF3, a `LoadBalancedDistributedSampler` is used to distribute work across ranks [models/rf3/src/rf3/inference_engines/rf3.py:17-17](). This ensures that different GPUs do not process the same structures and that the workload is distributed evenly based on the dataset size.

### Training Data Distribution

The `FabricTrainer` handles the setup of distributed dataloaders by wrapping them in `_FabricDataLoader` [src/foundry/trainers/fabric.py:23-27](). This ensures that:
- Data is sharded across ranks.
- Workers are properly seeded for reproducibility.
- Prefetching and pinning are optimized for the specific accelerator.

**Sources:** [src/foundry/trainers/fabric.py:23-27](), [models/rf3/src/rf3/inference_engines/rf3.py:17-17]()

## Distributed Inference Management

Inference engines like `RF3InferenceEngine` and `MPNNInferenceEngine` are designed to be rank-aware.

```mermaid
graph LR
    subgraph "Distributed Inference Flow"
        InfRun["inference.run()"]
        Engine["InferenceEngine<br/>RF3 / MPNN"]
        DeviceSet["Device Detection<br/>CUDA / XPU / MPS"]
        Sharding["Output Sharding<br/>get_sharded_output_path()"]
    end
    
    subgraph "Outputs"
        Rank0Out["Rank 0 Outputs"]
        RankNOut["Rank N Outputs"]
    end
    
    InfRun --> Engine
    Engine --> DeviceSet
    DeviceSet --> Sharding
    Sharding --> Rank0Out
    Sharding --> RankNOut
```

### Rank-Aware Output Sharding
To prevent file collisions when running inference on multiple GPUs, the system uses sharding patterns. In RF3, `get_sharded_output_path` ensures that each rank writes to a distinct subdirectory or file prefix [models/rf3/src/rf3/inference_engines/rf3.py:34-35]().

### Device Detection logic
Inference engines implement a standard fallback for device selection [models/mpnn/src/mpnn/inference_engines/mpnn.py:70-80]():
1. Use explicit `device` if provided.
2. Fallback to `cuda` if available.
3. Fallback to `xpu` if available.
4. Fallback to `mps` if available.
5. Default to `cpu`.

**Sources:** [models/mpnn/src/mpnn/inference_engines/mpnn.py:70-80](), [models/rf3/src/rf3/inference_engines/rf3.py:31-35]()

## Rank-Aware Logging

The `RankedLogger` [src/foundry/utils/ddp.py:58-112]() is a wrapper around the standard Python logger that prefixes messages with the process rank.

- **Rank Zero Only:** Loggers can be configured with `rank_zero_only=True` to suppress output from worker ranks [src/foundry/utils/ddp.py:79-80]().
- **Rank Prefixing:** Messages are automatically prefixed with `[Rank N]` to help disambiguate logs in multi-GPU environments [src/foundry/utils/ddp.py:103-103]().

```python
# Usage in inference engines
ranked_logger = RankedLogger(__name__, rank_zero_only=True)
ranked_logger.info("Starting inference...") # Only logs once
```

**Sources:** [src/foundry/utils/ddp.py:58-112](), [models/rf3/src/rf3/inference_engines/rf3.py:47-47]()

## Implementation Details

### Accelerator Detection
The `set_accelerator_based_on_availability` function modifies the Hydra configuration in-place to match the local hardware [src/foundry/utils/ddp.py:22-55]().

```python
if torch.cuda.is_available():
    cfg.trainer.accelerator = "gpu"
elif hasattr(torch, "xpu") and torch.xpu.is_available():
    cfg.trainer.accelerator = "xpu"
```

### Intel XPU Integration
Intel GPU support is facilitated through three primary components:
1. **XPUAccelerator:** Implements device setup and parsing for `torch.xpu` [src/foundry/utils/xpu/xpu_accelerator.py:9-91]().
2. **SingleXPUStrategy:** Manages execution on a single XPU device [src/foundry/utils/xpu/single_xpu_strategy.py:13-48]().
3. **XPUMixedPrecision:** Handles autocast contexts specifically for the XPU device type [src/foundry/utils/xpu/xpu_precision.py:11-73]().

**Sources:** [src/foundry/utils/ddp.py:22-55](), [src/foundry/utils/xpu/xpu_accelerator.py:9-91](), [src/foundry/utils/xpu/single_xpu_strategy.py:13-48](), [src/foundry/utils/xpu/xpu_precision.py:11-73]()

---