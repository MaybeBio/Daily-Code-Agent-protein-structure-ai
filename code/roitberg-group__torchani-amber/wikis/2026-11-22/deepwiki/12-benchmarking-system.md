# Benchmarking System

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [benchmark/bench](benchmark/bench)
- [benchmark/templates/hpg.slurm.sh.jinja](benchmark/templates/hpg.slurm.sh.jinja)

</details>



The benchmarking system provides a comprehensive framework for performance testing and scaling studies of TorchANI-Amber simulations. It enables automated execution of molecular dynamics simulations across different system sizes, neural network models, and hardware configurations, with integrated analysis and visualization tools.

For information about configuring individual simulations, see [Simulation Configuration](#4.1). For details about the command-line interface specifically, see [Bench CLI Tool](#5.1).

## System Architecture

The benchmarking framework consists of a Python-based CLI tool that orchestrates simulation execution, data collection, and performance analysis across both local and HPC environments.

```mermaid
graph TB
    subgraph "Benchmarking Frontend"
        CLI["bench CLI Tool"]
        CONFIG["ScalingConfig"]
        TEMPLATES["Jinja2 Templates"]
    end
    
    subgraph "Execution Environment"
        LOCAL["Local Execution"]
        HPC["HPC/SLURM Execution"]
        SCHEDULER["send_to_scheduler()"]
    end
    
    subgraph "Simulation Systems"
        WATER["Water Box Systems"]
        SIZES["1k - 200k atoms"]
        FILES["prmtop/inpcrd files"]
    end
    
    subgraph "Models & Configuration"
        MODELS["Neural Network Models"]
        ANI["ANI variants"]
        AIMNET["AimNet2"]
        NUTMEG["NutMeg"]
    end
    
    subgraph "Output & Analysis"
        TIMING["walltime_ms.dat"]
        RESULTS["Performance Data"]
        PLOTS["Scaling Plots"]
        CSV["CSV Reports"]
    end
    
    CLI --> CONFIG
    CLI --> TEMPLATES
    CLI --> LOCAL
    CLI --> SCHEDULER
    SCHEDULER --> HPC
    
    CONFIG --> MODELS
    TEMPLATES --> WATER
    WATER --> SIZES
    SIZES --> FILES
    
    LOCAL --> TIMING
    HPC --> TIMING
    TIMING --> RESULTS
    RESULTS --> PLOTS
    RESULTS --> CSV
```

Sources: [benchmark/bench:1-471]()

## Benchmark Types and Configuration

The system supports different benchmark types through the `BenchKind` enum and configurable parameters via the `ScalingConfig` dataclass.

### Benchmark Categories

| Benchmark Type | Purpose | Implementation Status |
|----------------|---------|----------------------|
| `SCALING` | Performance scaling across system sizes | Implemented |
| `REMD` | Replica Exchange MD benchmarks | Not implemented |

### Configuration Parameters

The `ScalingConfig` dataclass defines the core benchmark parameters:

```mermaid
graph LR
    subgraph "ScalingConfig Parameters"
        CUAEV["cuaev: bool"]
        CUDA["cuda: bool"] 
        CUTOFF["cutoff: float"]
        TSTEPS["tstep_num: int"]
        MODEL["model: str"]
        SHAKE["shake: bool"]
        TRAJ["dump_traj: bool"]
        AMBER_NB["use_all_amber_nonbond: bool"]
        AMBER_NL["use_amber_neighborlist: bool"]
    end
    
    subgraph "Model-Specific Defaults"
        ANI_CUTOFF["ANI models: 5.2 Å"]
        ANI2DR_CUTOFF["ani2dr: 8.0 Å"] 
        AIMNET_CUTOFF["AimNet2/NutMeg: 10.0 Å"]
    end
    
    CUTOFF --> ANI_CUTOFF
    CUTOFF --> ANI2DR_CUTOFF
    CUTOFF --> AIMNET_CUTOFF
```

Sources: [benchmark/bench:33-52](), [benchmark/bench:241-247]()

## System Size Matrix

The benchmarking framework uses predefined water box systems spanning multiple orders of magnitude in system size:

```mermaid
graph TB
    subgraph "Small Systems (1k-10k atoms)"
        S1["water-1k"]
        S2["water-2_5k"]
        S3["water-3k"]
        S4["water-4k"] 
        S5["water-5k"]
        S6["water-6k"]
        S7["water-7k"]
        S8["water-8k"]
        S9["water-9k"]
        S10["water-10k"]
    end
    
    subgraph "Medium Systems (15k-75k atoms)"
        M1["water-15k"]
        M2["water-20k"]
        M3["water-25k"]
        M4["water-30k"]
        M5["water-45k"]
        M6["water-60k"]
        M7["water-75k"]
    end
    
    subgraph "Large Systems (100k-200k atoms)"
        L1["water-100k"]
        L2["water-125k"]
        L3["water-150k"]
        L4["water-175k"]
        L5["water-200k"]
    end
```

Sources: [benchmark/bench:177-200]()

## Execution Workflow

The benchmark execution follows a structured workflow that handles both local and HPC environments:

```mermaid
flowchart TD
    START["bench run command"]
    DETECT["Detect execution environment"]
    
    subgraph "Environment Detection"
        LOCAL_CHECK["Check --hpg flag"]
        HOSTNAME_CHECK["Check hostname pattern"]
        HPC_DECISION{"Execute on HPC?"}
    end
    
    subgraph "HPC Execution Path"
        SLURM_TEMPLATE["Load hpg.slurm.sh.jinja"]
        SUBMIT_JOB["Submit SLURM job"]
        SCHEDULER_EXEC["Execute via send_to_scheduler()"]
    end
    
    subgraph "Local Execution Path"
        SETUP_ENV["Set TORCHANI_AMBER_WALLTIME=1"]
        ITERATE_SYSTEMS["Iterate through systems"]
        GENERATE_MDIN["Generate mdin from template"]
        COPY_FILES["Copy prmtop/inpcrd files"]
        RUN_AMBER["Execute sander/pmemd"]
        COLLECT_TIMING["Collect timing data"]
    end
    
    subgraph "Results Processing"
        WALLTIME_DATA["walltime_ms.dat files"]
        CONFIG_JSON["config.json files"]
        OUTPUT_DIR["Organized output directory"]
    end
    
    START --> DETECT
    DETECT --> LOCAL_CHECK
    LOCAL_CHECK --> HOSTNAME_CHECK
    HOSTNAME_CHECK --> HPC_DECISION
    
    HPC_DECISION -->|Yes| SLURM_TEMPLATE
    SLURM_TEMPLATE --> SUBMIT_JOB
    SUBMIT_JOB --> SCHEDULER_EXEC
    
    HPC_DECISION -->|No| SETUP_ENV
    SETUP_ENV --> ITERATE_SYSTEMS
    ITERATE_SYSTEMS --> GENERATE_MDIN
    GENERATE_MDIN --> COPY_FILES
    COPY_FILES --> RUN_AMBER
    RUN_AMBER --> COLLECT_TIMING
    
    SCHEDULER_EXEC --> WALLTIME_DATA
    COLLECT_TIMING --> WALLTIME_DATA
    WALLTIME_DATA --> CONFIG_JSON
    CONFIG_JSON --> OUTPUT_DIR
```

Sources: [benchmark/bench:224-237](), [benchmark/bench:278-307]()

## HPC Integration

The system provides sophisticated HPC integration through SLURM templates and environment management:

### SLURM Configuration

| Parameter | Purpose | Configuration |
|-----------|---------|---------------|
| `job-name` | Job identification | `{{ unique_id }}-v{{ version }}-{{ name }}` |
| `partition` | Queue selection | Configurable via `--gpu` parameter |
| `gres` | GPU resources | `gpu:{{ gpu }}` specification |
| `time` | Walltime limit | `{{ hours }}:00:00` format |
| `nodes` | Node allocation | Fixed at 1 node |
| `cpus-per-task` | CPU cores | Fixed at 1 core |

### Environment Management

The SLURM template supports multiple installation configurations:

```mermaid
graph TB
    subgraph "Installation Types"
        MODULES["modules: Shared module system"]
        LOCAL["local: User conda environment"]
        SHARED["shared-env: Shared conda environment"]
        BLACKWELL["b200:1: Blackwell GPU support"]
    end
    
    subgraph "Module Loading"
        CUDA["CUDA modules"]
        GCC["GCC compiler"]
        MPI["OpenMPI"]
        CONDA["Conda environment"]
        CMAKE["CMake build system"]
    end
    
    subgraph "Environment Activation"
        AMBER_ENV["Amber environment"]
        CONDA_ACT["Conda activation"]
        MAMBA_ACT["Mamba activation"]
    end
    
    MODULES --> CUDA
    MODULES --> GCC
    MODULES --> MPI
    MODULES --> CONDA
    MODULES --> CMAKE
    
    LOCAL --> CONDA_ACT
    LOCAL --> MAMBA_ACT
    
    SHARED --> CONDA_ACT
    SHARED --> AMBER_ENV
    
    BLACKWELL --> CUDA
    BLACKWELL --> MAMBA_ACT
```

Sources: [benchmark/templates/hpg.slurm.sh.jinja:1-32]()

## Performance Analysis and Visualization

The benchmarking system includes comprehensive analysis capabilities through the `plot` command:

### Data Processing Pipeline

```mermaid
flowchart LR
    subgraph "Raw Data"
        WALLTIME["walltime_ms.dat"]
        INPCRD["inpcrd files"]
        CONFIG["config.json"]
    end
    
    subgraph "Processing Steps"
        PARSE["Parse timing data"]
        BURNIN["Apply burn-in filter"]
        ATOMS["Extract atom counts"]
        STATS["Calculate statistics"]
    end
    
    subgraph "Metrics Calculation"
        MEAN["Mean walltime per step"]
        STD["Standard deviation"]
        NSDAY["ns/day conversion"]
        SCALING["Scaling analysis"]
    end
    
    subgraph "Visualization"
        SCATTER["Scatter plots"]
        TREND["Trend lines"]
        CSV_OUT["CSV export"]
        PLOTS["Interactive plots"]
    end
    
    WALLTIME --> PARSE
    INPCRD --> ATOMS
    PARSE --> BURNIN
    BURNIN --> STATS
    ATOMS --> STATS
    
    STATS --> MEAN
    STATS --> STD
    MEAN --> NSDAY
    NSDAY --> SCALING
    
    SCALING --> SCATTER
    SCALING --> TREND
    SCALING --> CSV_OUT
    SCATTER --> PLOTS
```

### Performance Metrics

The system generates two primary performance metrics:

| Metric | Units | Calculation | Purpose |
|--------|-------|-------------|---------|
| Walltime per timestep | milliseconds | Direct measurement | Low-level performance |
| Simulation rate | ns/day | `86.4 / walltime_ms` | Production throughput |

Sources: [benchmark/bench:309-467](), [benchmark/bench:441-444]()

## Model Support and Optimization

The benchmarking framework supports multiple neural network models with model-specific optimizations:

### Supported Models

```mermaid
graph TB
    subgraph "ANI Model Family"
        ANI1X["ani1x"]
        ANI2X["ani2x"] 
        ANI2XR["ani2xr"]
        ANI2DR["ani2dr"]
    end
    
    subgraph "AimNet2 Models"
        AIMNET_BASE["aimnet2-wb97m-dsf"]
        AIMNET_VARIANTS["AimNet2 variants"]
    end
    
    subgraph "NutMeg Models"
        NUTMEG_SMALL["nutmeg-small"]
        NUTMEG_VARIANTS["NutMeg variants"]
    end
    
    subgraph "Model-Specific Features"
        CUAEV_SUPPORT["CUAEV acceleration"]
        CHARGE_PRED["Charge prediction"]
        CUTOFF_OPT["Cutoff optimization"]
    end
    
    ANI1X --> CUAEV_SUPPORT
    ANI2X --> CUAEV_SUPPORT
    ANI2XR --> CUAEV_SUPPORT
    ANI2DR --> CUTOFF_OPT
    
    AIMNET_BASE --> CHARGE_PRED
    NUTMEG_SMALL --> CHARGE_PRED
```

### Hardware Optimization

The system automatically detects and configures hardware-specific optimizations:

| Feature | Detection Method | Configuration |
|---------|------------------|---------------|
| CUDA availability | `torch.cuda.is_available()` | Automatic GPU usage |
| CUAEV acceleration | Model name pattern matching | ANI models only |
| Amber neighborlist | User configuration | Optional optimization |
| Amber nonbonded | User configuration | Performance trade-off |

Sources: [benchmark/bench:26](), [benchmark/bench:156-158](), [benchmark/bench:239-252](), [benchmark/bench:282-285]()

---