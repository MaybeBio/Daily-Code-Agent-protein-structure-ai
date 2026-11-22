# Performance Testing and Analysis

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [benchmark/bench](benchmark/bench)
- [benchmark/templates/hpg.slurm.sh.jinja](benchmark/templates/hpg.slurm.sh.jinja)
- [tests/test_values_cpu_1ccx_ensemble.txt](tests/test_values_cpu_1ccx_ensemble.txt)
- [tests/test_values_cpu_1x_ensemble.txt](tests/test_values_cpu_1x_ensemble.txt)
- [tests/test_values_cpu_2x_ensemble.txt](tests/test_values_cpu_2x_ensemble.txt)
- [tests/test_values_cpu_mbis_ensemble.txt](tests/test_values_cpu_mbis_ensemble.txt)
- [tests/test_values_cuda_1ccx_ensemble.txt](tests/test_values_cuda_1ccx_ensemble.txt)
- [tests/test_values_cuda_1x_ensemble.txt](tests/test_values_cuda_1x_ensemble.txt)
- [tests/test_values_cuda_2x_ensemble.txt](tests/test_values_cuda_2x_ensemble.txt)
- [tests/test_values_cuda_mbis_ensemble.txt](tests/test_values_cuda_mbis_ensemble.txt)

</details>



This page covers the performance testing and analysis capabilities of TorchANI-Amber, focusing on how to conduct scaling studies, interpret benchmark results, and generate performance visualizations. For information about the bench CLI tool itself and basic usage, see [Bench CLI Tool](#5.1).

## Purpose and Scope

The performance testing system provides comprehensive tools for analyzing TorchANI-Amber's computational performance across different system sizes, hardware configurations, and model types. The analysis framework supports:

- Scaling studies across different molecular system sizes
- Performance comparison between different neural network models
- Hardware performance analysis (CPU vs GPU, different GPU types)
- HPC cluster scaling analysis
- Automated visualization and reporting

Sources: [benchmark/bench:1-470]()

## Scaling Study Workflow

The typical scaling study workflow involves running benchmarks across multiple system sizes and then analyzing the results to understand performance characteristics.

```mermaid
flowchart TD
    A[Configure scaling study] --> B["bench run --bench-kind scaling"]
    B --> C["Execute across system sizes"]
    C --> D["Collect walltime_ms.dat files"]
    D --> E["Generate performance plots"]
    E --> F["Analyze scaling behavior"]
    
    subgraph "System sizes"
        G["water-1k"]
        H["water-5k"] 
        I["water-10k"]
        J["water-25k"]
        K["water-100k+"]
    end
    
    subgraph "Analysis outputs"
        L["Performance plots"]
        M["CSV data files"]
        N["ns/day metrics"]
    end
    
    C --> G
    C --> H
    C --> I
    C --> J
    C --> K
    
    E --> L
    E --> M
    E --> N
```

The scaling study automatically tests predefined system sizes ranging from 1,000 to 200,000 atoms, allowing comprehensive performance characterization.

Sources: [benchmark/bench:169-200](), [benchmark/bench:277-307]()

## Benchmark Data Structure

Each benchmark execution generates a structured output directory containing performance data and configuration information:

```mermaid
graph TD
    A["benchmark-output-dir/"] --> B["unique-id-model-name/"]
    B --> C["water-1k/"]
    B --> D["water-5k/"]
    B --> E["water-10k/"]
    
    C --> F["walltime_ms.dat"]
    C --> G["config.json"]
    C --> H["mdin"]
    C --> I["inpcrd"]
    C --> J["prmtop"]
    C --> K["mdout"]
    
    D --> L["walltime_ms.dat"]
    D --> M["config.json"]
    E --> N["walltime_ms.dat"]
    E --> O["config.json"]
```

**Key Data Files:**

| File | Purpose |
|------|---------|
| `walltime_ms.dat` | Per-timestep walltime measurements in milliseconds |
| `config.json` | ScalingConfig parameters for reproducibility |
| `mdin` | Generated Amber input file |
| `mdout` | Amber simulation output |

The `walltime_ms.dat` file contains one measurement per line, with each value representing the walltime for a single MD timestep.

Sources: [benchmark/bench:418-421](), [benchmark/bench:291-294]()

## Performance Visualization

The plotting system provides automated visualization of benchmark results with multiple analysis modes:

### Basic Performance Plotting

```bash
bench plot ani2xr-scaling aimnet2-scaling --label "ANI-2xr" --label "AimNet2"
```

### Throughput Analysis

```bash
bench plot ani2xr-scaling --ns-per-day --ymax 6
```

The plotting system generates two key metrics:

```mermaid
graph LR
    A["walltime_ms.dat"] --> B["Walltime per timestep (ms)"]
    A --> C["ns/day calculation"]
    
    B --> D["Performance comparison"]
    C --> E["Throughput analysis"]
    
    F["Formula: 86.4 / walltime_ms"] --> C
```

**Performance Metrics:**

| Metric | Formula | Purpose |
|--------|---------|---------|
| Walltime per timestep | Direct from data | Raw performance measurement |
| ns/day throughput | `86.4 / walltime_ms` | Simulation productivity metric |

Sources: [benchmark/bench:441-445](), [benchmark/bench:324-327]()

## Statistical Analysis and Burn-in

The analysis system incorporates statistical rigor through burn-in periods and error analysis:

```mermaid
flowchart LR
    A["Raw walltime data"] --> B["Apply burn-in filter"]
    B --> C["Calculate statistics"]
    C --> D["Mean walltime"]
    C --> E["Standard deviation"]
    
    F["burn_in_tstep_num=50"] --> B
    
    D --> G["Performance plots"]
    E --> H["Error bars"]
```

The system automatically:
- Excludes initial timesteps (default: 50) to account for initialization overhead
- Calculates mean and standard deviation for each system size
- Generates CSV output with statistical summaries

Sources: [benchmark/bench:421-433](), [benchmark/bench:460-466]()

## Model and Hardware Performance Analysis

The benchmarking system supports comparative analysis across different configurations:

### Model Comparison Framework

```mermaid
graph TD
    A["ScalingConfig parameters"] --> B["Model selection"]
    A --> C["Hardware configuration"] 
    A --> D["Optimization settings"]
    
    B --> E["ani1x, ani2x, ani2xr"]
    B --> F["aimnet2-wb97m-dsf"]
    B --> G["nutmeg variants"]
    
    C --> H["CUDA vs CPU"]
    C --> I["cuAEV acceleration"]
    
    D --> J["Amber neighborlist"]
    D --> K["Amber nonbonded"]
    D --> L["SHAKE constraints"]
```

**Key Configuration Parameters:**

| Parameter | Options | Impact |
|-----------|---------|--------|
| `cuaev` | true/false | Enables CUDA-accelerated AEV computation |
| `cuda` | true/false | GPU vs CPU execution |
| `use_amber_neighborlist` | true/false | Amber vs TorchANI neighbor detection |
| `use_all_amber_nonbond` | true/false | Hybrid force calculation |
| `shake` | true/false | Bond constraint algorithm |

Sources: [benchmark/bench:39-48](), [benchmark/bench:239-247]()

## HPC Scaling Analysis

For large-scale performance studies, the system integrates with HPC schedulers:

```mermaid
sequenceDiagram
    participant User
    participant CLI as "bench CLI"
    participant SLURM as "HPC Scheduler"
    participant Compute as "Compute Nodes"
    
    User->>CLI: bench run --hpg
    CLI->>SLURM: Submit job via template
    SLURM->>Compute: Allocate resources
    Compute->>Compute: Execute scaling study
    Compute->>CLI: Return results
    CLI->>User: Performance data
```

The HPC integration automatically:
- Detects HPC environment based on hostname pattern
- Submits jobs via SLURM templates
- Manages environment modules and conda activation
- Handles GPU resource allocation

Sources: [benchmark/bench:224-237](), [benchmark/templates/hpg.slurm.sh.jinja:1-32]()

## Automated Analysis Pipeline

A complete performance analysis typically follows this pipeline:

```mermaid
flowchart TD
    A["Define test systems"] --> B["Execute scaling study"]
    B --> C["Collect performance data"]
    C --> D["Generate visualizations"]
    D --> E["Export CSV data"]
    E --> F["Analyze scaling trends"]
    
    subgraph "Quality control"
        G["Burn-in filtering"]
        H["Statistical validation"]
        I["Outlier detection"]
    end
    
    C --> G
    G --> H
    H --> I
    I --> D
    
    subgraph "Output products"
        J["Performance plots"]
        K["CSV datasets"]
        L["Scaling coefficients"]
    end
    
    D --> J
    E --> K
    F --> L
```

The system ensures reproducibility by:
- Saving complete configuration in `config.json`
- Using consistent system definitions
- Applying standardized analysis methods
- Generating machine-readable output formats

Sources: [benchmark/bench:264-274](), [benchmark/bench:413-466]()

---