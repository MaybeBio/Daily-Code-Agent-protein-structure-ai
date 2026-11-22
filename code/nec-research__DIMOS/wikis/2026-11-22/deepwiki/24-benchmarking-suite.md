# Benchmarking Suite

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [benchmark/proteins/benchmark_proteins.py](benchmark/proteins/benchmark_proteins.py)
- [benchmark/water/dimos_water.py](benchmark/water/dimos_water.py)
- [benchmark/water/dimos_water_ml.py](benchmark/water/dimos_water_ml.py)

</details>



The DIMOS benchmarking suite is a collection of scripts and test systems designed to systematically evaluate the performance and accuracy of the DIMOS simulation engine. The suite compares DIMOS against established molecular dynamics platforms (OpenMM, TorchMD, ASE) across multiple dimensions: force field types (classical, ML, hybrid), system sizes, precision configurations, and compilation strategies.

The benchmarking infrastructure serves two primary purposes:
1. **Validation**: Ensuring DIMOS produces physically correct results comparable to reference implementations
2. **Performance Profiling**: Measuring throughput (nanoseconds per day) and identifying optimization opportunities

For information about the specific test systems used, see [Protein Benchmark Systems](#6.1) and [Water System Benchmarks](#6.2). For detailed performance analysis and platform comparisons, see [Platform Comparison and Performance](#6.3).

**Sources**: [benchmark/proteins/benchmark_proteins.py:1-73](), [benchmark/water/dimos_water.py:1-223](), [benchmark/water/dimos_water_ml.py:1-207]()

## Benchmark Architecture

The benchmarking suite is organized into two main directories: `benchmark/proteins/` for protein system tests and `benchmark/water/` for water box tests. Each directory contains benchmark scripts that can run simulations with different configurations and collect performance metrics.

### Benchmark Script Organization

```mermaid
graph TB
    subgraph "benchmark/proteins/"
        PROT_SCRIPT["benchmark_proteins.py"]
        PROT_DATA["Test System Files<br/>ala2_tip3p.gro/.top<br/>dhfr.gro/.top<br/>trp-cage_sol.gro/.top"]
    end
    
    subgraph "benchmark/water/"
        WATER_CLASS_SCRIPT["dimos_water.py"]
        WATER_ML_SCRIPT["dimos_water_ml.py"]
        WATER_DATA["Amber Files<br/>amberN.prmtop<br/>amberN.inpcrd"]
        GEN_SCRIPT["generate_water_box_amber.py"]
    end
    
    subgraph "Configuration Inputs"
        CLI_ARGS["Command Line Arguments"]
        SYSTEM_ARG["System name"]
        PLATFORM_ARG["Platform: dimos/openMM/torchmd/ase"]
        CONFIG_ARG["Configuration: constraints/nonbonded"]
        PRECISION_ARG["Precision: ff_accuracy/integration_accuracy"]
        MODEL_ARG["ML Model: mace-small/medium/large/orb"]
    end
    
    subgraph "Output Metrics"
        TIMING_FILE[".dat files<br/>system_config_benchmark.dat"]
        NSDAY["ns/day throughput"]
        ENERGY_LOG["Energy measurements"]
        TRAJ_FILE[".pdb trajectory files"]
    end
    
    CLI_ARGS --> SYSTEM_ARG
    CLI_ARGS --> PLATFORM_ARG
    CLI_ARGS --> CONFIG_ARG
    CLI_ARGS --> PRECISION_ARG
    CLI_ARGS --> MODEL_ARG
    
    SYSTEM_ARG --> PROT_SCRIPT
    CONFIG_ARG --> PROT_SCRIPT
    
    PLATFORM_ARG --> WATER_CLASS_SCRIPT
    CONFIG_ARG --> WATER_CLASS_SCRIPT
    PRECISION_ARG --> WATER_CLASS_SCRIPT
    
    PLATFORM_ARG --> WATER_ML_SCRIPT
    MODEL_ARG --> WATER_ML_SCRIPT
    PRECISION_ARG --> WATER_ML_SCRIPT
    
    GEN_SCRIPT --> WATER_DATA
    
    PROT_DATA --> PROT_SCRIPT
    WATER_DATA --> WATER_CLASS_SCRIPT
    WATER_DATA --> WATER_ML_SCRIPT
    
    PROT_SCRIPT --> TIMING_FILE
    WATER_CLASS_SCRIPT --> TIMING_FILE
    WATER_ML_SCRIPT --> TIMING_FILE
    
    TIMING_FILE --> NSDAY
    TIMING_FILE --> ENERGY_LOG
    PROT_SCRIPT --> TRAJ_FILE
    WATER_CLASS_SCRIPT --> TRAJ_FILE
    WATER_ML_SCRIPT --> TRAJ_FILE
```

**Sources**: [benchmark/proteins/benchmark_proteins.py:16-21](), [benchmark/water/dimos_water.py:24-31](), [benchmark/water/dimos_water_ml.py:34-39]()

### Force Field Configuration Matrix

The protein benchmark script supports six distinct force field configurations, controlled by the `name` command-line argument:

| Configuration | Force Field Type | Constraints | Timestep | Implementation |
|---------------|------------------|-------------|----------|----------------|
| `no_constraints_mm` | Classical MM | None | 0.5 fs | `GromacsForceField` |
| `constraints_mm` | Classical MM | H-angles | 2.0 fs | `GromacsForceField` |
| `no_constraints_mlmm` | Hybrid ML/MM | None | 0.5 fs | `MLMMsystem` |
| `constraints_mlmm` | Hybrid ML/MM | H-angles | 2.0 fs | `MLMMsystem` |
| `no_constraints_ml` | Pure ML | None | 0.5 fs | `as_mace_system` |
| `constraints_ml` | Pure ML | H-angles | 2.0 fs | `as_mace_system` |

The constraint option `h_angles` constrains hydrogen bonds and angles, allowing for a 4x larger timestep (2.0 fs vs 0.5 fs) while maintaining stability.

**Sources**: [benchmark/proteins/benchmark_proteins.py:24-44]()

## Benchmark Execution Workflow

### Protein Benchmark Workflow

```mermaid
graph TD
    START["Start: benchmark_proteins.py"]
    PARSE["Parse CLI Arguments<br/>sys.argv[1]: system<br/>sys.argv[2]: name"]
    
    SET_DEFAULT["Set Default Device<br/>torch.set_default_device"]
    
    LOAD_POS["Load Positions<br/>dimos.read_positions"]
    
    CONFIG_CONSTRAINT{"Constraint<br/>in name?"}
    
    SET_CONSTRAINT_NONE["constraint_option = None<br/>timestep = 0.5"]
    SET_CONSTRAINT_HANG["constraint_option = 'h_angles'<br/>timestep = 2.0"]
    
    CREATE_BASE["Create Base System<br/>dimos.GromacsForceField"]
    
    CHECK_FF{"Force Field<br/>Type?"}
    
    USE_MM["Use Classical MM<br/>syst = base_sys"]
    
    CREATE_MLMM["Create ML/MM Hybrid<br/>system_excluding_protein<br/>as_mace_system<br/>dimos.mlmm.MLMMsystem"]
    
    CREATE_ML["Create Pure ML<br/>base_sys.as_mace_system<br/>syst.constraint_handler"]
    
    CREATE_INTEGRATOR["Create Integrator<br/>dimos.NoseHooverDynamics<br/>dtype=torch.float64"]
    
    CREATE_SIM["Create Simulation<br/>dimos.MDSimulation"]
    
    COMPILE["Compile Step Function<br/>torch.compile(sim.step)"]
    
    WARMUP["Warmup Loop<br/>warmup_iterations × steps_per_warmup"]
    
    MEASURE["Measurement Loop<br/>measure_iterations × steps_per_measure"]
    
    CALC_METRICS["Calculate Metrics<br/>time_period<br/>ns/day = timestep*steps/fraction_of_day"]
    
    WRITE_OUTPUT["Write Output<br/>system_name_benchmark.dat<br/>mean ± std_error"]
    
    END["End"]
    
    START --> PARSE
    PARSE --> SET_DEFAULT
    SET_DEFAULT --> LOAD_POS
    LOAD_POS --> CONFIG_CONSTRAINT
    
    CONFIG_CONSTRAINT -->|"'no_constraints'"| SET_CONSTRAINT_NONE
    CONFIG_CONSTRAINT -->|"'constraints'"| SET_CONSTRAINT_HANG
    
    SET_CONSTRAINT_NONE --> CREATE_BASE
    SET_CONSTRAINT_HANG --> CREATE_BASE
    
    CREATE_BASE --> CHECK_FF
    
    CHECK_FF -->|"'_mm'"| USE_MM
    CHECK_FF -->|"'_mlmm'"| CREATE_MLMM
    CHECK_FF -->|"'_ml'"| CREATE_ML
    
    USE_MM --> CREATE_INTEGRATOR
    CREATE_MLMM --> CREATE_INTEGRATOR
    CREATE_ML --> CREATE_INTEGRATOR
    
    CREATE_INTEGRATOR --> CREATE_SIM
    CREATE_SIM --> COMPILE
    COMPILE --> WARMUP
    WARMUP --> MEASURE
    MEASURE --> CALC_METRICS
    CALC_METRICS --> WRITE_OUTPUT
    WRITE_OUTPUT --> END
```

**Sources**: [benchmark/proteins/benchmark_proteins.py:1-73]()

### Water Benchmark Workflow

The water benchmarks follow a similar pattern but support multiple platforms and configuration options:

```mermaid
graph TD
    START["Start: dimos_water.py or dimos_water_ml.py"]
    
    PARSE["Parse CLI Arguments<br/>tool, nonbonded/model, box_size<br/>ff_accuracy, integration_accuracy"]
    
    SET_DTYPE["Set Data Types<br/>dtype_ff: torch.float32/64<br/>dtype_integration: torch.float32/64"]
    
    CHECK_TOOL{"Which<br/>Platform?"}
    
    SETUP_DIMOS["Setup DIMOS<br/>AmberForceField<br/>LangevinDynamics<br/>MDSimulation"]
    
    SETUP_OPENMM["Setup OpenMM<br/>AmberPrmtopFile<br/>createSystem<br/>LangevinMiddleIntegrator"]
    
    SETUP_TORCHMD["Setup TorchMD<br/>ParmedForcefield<br/>Parameters<br/>Forces<br/>System<br/>Integrator"]
    
    SETUP_ASE["Setup ASE<br/>mace_mp/ORB<br/>Atoms<br/>Langevin"]
    
    CHECK_COMPILE{"Compile<br/>Enabled?"}
    
    COMPILE_STEP["Compile Step Function<br/>torch.compile(step)"]
    
    NO_COMPILE["Use step function directly"]
    
    WARMUP["Warmup Phase<br/>warmup × warmup_steps_between_pause"]
    
    MEASURE["Measurement Phase<br/>measure_steps × steps_between_pause"]
    
    COLLECT_METRICS["Collect Per-Step Metrics<br/>runtime = time/steps_between_pause"]
    
    CALC_STATS["Calculate Statistics<br/>mean_time<br/>std_sem = std/sqrt(n)<br/>ns/day"]
    
    WRITE_OUTPUT["Write to .dat File<br/>box_size, num_atoms, metrics"]
    
    END["End"]
    
    START --> PARSE
    PARSE --> SET_DTYPE
    SET_DTYPE --> CHECK_TOOL
    
    CHECK_TOOL -->|"'dimos'"| SETUP_DIMOS
    CHECK_TOOL -->|"'openMM'"| SETUP_OPENMM
    CHECK_TOOL -->|"'torchmd'"| SETUP_TORCHMD
    CHECK_TOOL -->|"'ase'"| SETUP_ASE
    
    SETUP_DIMOS --> CHECK_COMPILE
    SETUP_OPENMM --> CHECK_COMPILE
    SETUP_TORCHMD --> CHECK_COMPILE
    SETUP_ASE --> CHECK_COMPILE
    
    CHECK_COMPILE -->|"'compile' in tool"| COMPILE_STEP
    CHECK_COMPILE -->|"else"| NO_COMPILE
    
    COMPILE_STEP --> WARMUP
    NO_COMPILE --> WARMUP
    
    WARMUP --> MEASURE
    MEASURE --> COLLECT_METRICS
    COLLECT_METRICS --> CALC_STATS
    CALC_STATS --> WRITE_OUTPUT
    WRITE_OUTPUT --> END
```

**Sources**: [benchmark/water/dimos_water.py:1-223](), [benchmark/water/dimos_water_ml.py:1-207]()

## Benchmark Configuration Options

### Precision Control

DIMOS benchmarks support independent precision control for force field calculations and integration steps, enabling mixed-precision workflows:

```mermaid
graph LR
    subgraph "Precision Configuration"
        FF_ACC["ff_accuracy<br/>CLI Argument"]
        INT_ACC["integration_accuracy<br/>CLI Argument"]
    end
    
    subgraph "Force Field Precision"
        FF_32["dtype_ff = torch.float32"]
        FF_64["dtype_ff = torch.float64"]
    end
    
    subgraph "Integration Precision"
        INT_32["dtype_integration = torch.float32"]
        INT_64["dtype_integration = torch.float64"]
    end
    
    subgraph "Component Application"
        FF_CALC["Force Field Constructor<br/>AmberForceField(dtype=dtype_ff)"]
        INTEGRATOR["Integrator Constructor<br/>LangevinDynamics(dtype=dtype_integration)"]
    end
    
    subgraph "OpenMM Precision Mapping"
        OMM_SINGLE["Precision='single'<br/>ff=32, int=32"]
        OMM_DOUBLE["Precision='double'<br/>ff=64, int=64"]
        OMM_MIXED["Precision='mixed'<br/>ff=32, int=64"]
    end
    
    FF_ACC -->|"32"| FF_32
    FF_ACC -->|"64"| FF_64
    INT_ACC -->|"32"| INT_32
    INT_ACC -->|"64"| INT_64
    
    FF_32 --> FF_CALC
    FF_64 --> FF_CALC
    INT_32 --> INTEGRATOR
    INT_64 --> INTEGRATOR
    
    FF_32 --> OMM_SINGLE
    INT_32 --> OMM_SINGLE
    FF_64 --> OMM_DOUBLE
    INT_64 --> OMM_DOUBLE
    FF_32 --> OMM_MIXED
    INT_64 --> OMM_MIXED
```

**Sources**: [benchmark/water/dimos_water.py:30-40](), [benchmark/water/dimos_water.py:95-100]()

### Platform-Specific Setup

The benchmark scripts implement platform-specific initialization to ensure fair comparisons:

| Platform | Device Control | Compilation | Threading |
|----------|----------------|-------------|-----------|
| DIMOS CPU | `torch.set_default_device("cpu")` | `torch.compile(..., mode="max-autotune-no-cudagraphs")` | `OMP_NUM_THREADS` |
| DIMOS CUDA | `torch.set_default_device("cuda:0")` | `torch.compile(..., mode="max-autotune-no-cudagraphs")` | N/A |
| OpenMM Reference | `Platform.getPlatformByName('Reference')` | N/A | N/A |
| OpenMM CPU | `Platform.getPlatformByName('CPU')` | N/A | `OPENMM_CPU_THREADS` |
| OpenMM CUDA | `Platform.getPlatformByName('CUDA')`, `properties["DeviceIndex"]` | N/A | N/A |
| TorchMD | `device="cpu"` or `"cuda:0"` | `torch.compile(integrator.step)` | N/A |
| ASE | `device="cpu"` or `"cuda:0"` | `torch.compile(calculator)` | N/A |

**Sources**: [benchmark/water/dimos_water.py:50-108](), [benchmark/water/dimos_water_ml.py:58-176]()

## Performance Metrics Collection

### Timing and Throughput Calculation

```mermaid
graph TD
    subgraph "Warmup Phase"
        WARM_START["Start Warmup"]
        WARM_LOOP["for warm_it in range(warmup_iterations)"]
        WARM_STEP["sim_step(steps_per_warmup)"]
        WARM_END["End Warmup<br/>Discard timings"]
    end
    
    subgraph "Measurement Phase"
        MEAS_START["Start Measurement"]
        MEAS_LOOP["for meas_it in range(measure_iterations)"]
        START_TIMER["start_time = time()"]
        MEAS_STEP["sim_step(steps_per_measure)"]
        END_TIMER["end_time = time()"]
        CALC_TIME["time_period = end_time - start_time"]
        CALC_FRACTION["fraction_of_day = time_period/(24*60*60)"]
        CALC_NSDAY["ns/day = timestep * steps * 1e-6 / fraction_of_day"]
        STORE["Store measurement"]
    end
    
    subgraph "Statistical Analysis"
        COMPUTE_MEAN["mean_time = measurements.mean()"]
        COMPUTE_SEM["std_sem = measurements.std(ddof=1) / sqrt(n)"]
        WRITE_FILE["Write mean ± std_sem to .dat file"]
    end
    
    WARM_START --> WARM_LOOP
    WARM_LOOP --> WARM_STEP
    WARM_STEP --> WARM_LOOP
    WARM_LOOP --> WARM_END
    
    WARM_END --> MEAS_START
    MEAS_START --> MEAS_LOOP
    MEAS_LOOP --> START_TIMER
    START_TIMER --> MEAS_STEP
    MEAS_STEP --> END_TIMER
    END_TIMER --> CALC_TIME
    CALC_TIME --> CALC_FRACTION
    CALC_FRACTION --> CALC_NSDAY
    CALC_NSDAY --> STORE
    STORE --> MEAS_LOOP
    
    MEAS_LOOP --> COMPUTE_MEAN
    COMPUTE_MEAN --> COMPUTE_SEM
    COMPUTE_SEM --> WRITE_FILE
```

The warmup phase ensures that:
1. JIT compilation is completed (for `torch.compile` runs)
2. GPU kernels are loaded and cached
3. Memory allocations are stable
4. CPU/GPU frequency scaling reaches steady state

Only measurements from the measurement phase are used for performance statistics.

**Sources**: [benchmark/proteins/benchmark_proteins.py:49-72](), [benchmark/water/dimos_water.py:193-218]()

### Output File Format

Benchmark results are written to `.dat` files with tab-separated values:

**Protein Benchmarks** (`{system}_{config}_benchmark.dat`):
```
ns_per_day_mean    ns_per_day_std_error
```

**Water Benchmarks** (`{tool}_nonbonded{method}_dtype*.dat` or `{tool}model{name}_dtype*.dat`):
```
box_size    num_atoms    total_time    time_per_step    ns_per_day    mean_time    std_sem
```

**Sources**: [benchmark/proteins/benchmark_proteins.py:57-72](), [benchmark/water/dimos_water.py:218]()

## Compilation Strategy

Both protein and water benchmarks utilize `torch.compile` to optimize the simulation step function. The compilation process is distinct from the warmup phase:

```mermaid
graph TD
    RESET["torch.compiler.reset()<br/>torch._dynamo.reset()"]
    
    COMPILE["torch.compile(sim.step)<br/>mode='max-autotune-no-cudagraphs'"]
    
    FIRST_CALL["First call to compiled function<br/>Triggers PyTorch compilation"]
    
    TRACE["Trace execution graph"]
    OPTIMIZE["Apply optimizations<br/>max-autotune: aggressive tuning"]
    CODEGEN["Generate optimized kernel"]
    CACHE["Cache compiled function"]
    
    WARMUP_RUNS["Warmup runs<br/>Ensure GPU kernel stability"]
    
    MEASURE["Measurement runs<br/>Use cached compiled function"]
    
    RESET --> COMPILE
    COMPILE --> FIRST_CALL
    FIRST_CALL --> TRACE
    TRACE --> OPTIMIZE
    OPTIMIZE --> CODEGEN
    CODEGEN --> CACHE
    CACHE --> WARMUP_RUNS
    WARMUP_RUNS --> MEASURE
```

The `max-autotune-no-cudagraphs` mode:
- **max-autotune**: Aggressively tunes kernel launches and memory layouts for maximum performance
- **no-cudagraphs**: Disables CUDA graphs to avoid compatibility issues with dynamic operations

**Sources**: [benchmark/proteins/benchmark_proteins.py:49-51](), [benchmark/water/dimos_water.py:67-70](), [benchmark/water/dimos_water_ml.py:90-94]()

## ML Potential Benchmark Configuration

The ML water benchmarks support multiple ML potentials and optimization strategies:

### MACE Model Variants

```mermaid
graph TD
    subgraph "MACE Model Selection"
        MODEL_ARG["model CLI argument"]
        SMALL["'mace-small'<br/>mace_name='mace-mp-small'"]
        MEDIUM["'mace-medium'<br/>mace_name='mace-mp-medium'"]
        LARGE["'mace-large'<br/>mace_name='mace-mp-large'"]
    end
    
    subgraph "cuEq Optimization"
        CUEQ_CHECK{"'cuEq'<br/>in tool?"}
        CUEQ_ENABLED["enable_cueq=True<br/>Use cuEquivariance library"]
        CUEQ_DISABLED["enable_cueq=False<br/>Standard implementation"]
    end
    
    subgraph "System Conversion"
        MM_SYSTEM["mm_system = AmberForceField<br/>cutoff=5.0, switch_distance=3.5"]
        AS_MACE["dimos_system = mm_system.as_mace_system<br/>mace_name, enable_cueq"]
    end
    
    subgraph "ASE Integration"
        ASE_CALC["mace_mp calculator<br/>enable_cueq, model, dtype, device"]
        ASE_COMPILE["torch.compile(macemp)<br/>mode='max-autotune-no-cudagraphs'"]
        ASE_ATOMS["atoms.calc = macemp"]
    end
    
    MODEL_ARG --> SMALL
    MODEL_ARG --> MEDIUM
    MODEL_ARG --> LARGE
    
    SMALL --> CUEQ_CHECK
    MEDIUM --> CUEQ_CHECK
    LARGE --> CUEQ_CHECK
    
    CUEQ_CHECK -->|"Yes"| CUEQ_ENABLED
    CUEQ_CHECK -->|"No"| CUEQ_DISABLED
    
    CUEQ_ENABLED --> MM_SYSTEM
    CUEQ_DISABLED --> MM_SYSTEM
    
    MM_SYSTEM --> AS_MACE
    
    CUEQ_ENABLED --> ASE_CALC
    CUEQ_DISABLED --> ASE_CALC
    ASE_CALC --> ASE_COMPILE
    ASE_COMPILE --> ASE_ATOMS
```

The cuEquivariance (`enable_cueq=True`) option uses optimized CUDA kernels for equivariant operations, potentially improving MACE performance on GPUs.

**Sources**: [benchmark/water/dimos_water_ml.py:72-84](), [benchmark/water/dimos_water_ml.py:112-141]()

### ORB Potential Integration

For ORB (Orbital) potentials, the benchmarks support both DIMOS and ASE implementations:

**DIMOS Integration**:
```python
dimos_system = mm_system.as_orb_system()
```

**ASE Integration**:
```python
from orb_models.forcefield import atomic_system, pretrained
from orb_models.forcefield.calculator import ORBCalculator

orbff = pretrained.orb_v2(device=device_str)
system_config = atomic_system.SystemConfig(radius=6.0, max_num_neighbors=150)
calc = ORBCalculator(orbff, system_config=system_config, device=device_str)
atoms.calc = calc
```

**Sources**: [benchmark/water/dimos_water_ml.py:83-84](), [benchmark/water/dimos_water_ml.py:149-167]()

## Benchmark Execution Examples

### Running Protein Benchmarks

```bash
# Classical MM with constraints
python benchmark_proteins.py ala2_tip3p constraints_mm

# Pure ML without constraints
python benchmark_proteins.py dhfr no_constraints_ml

# Hybrid ML/MM with constraints
python benchmark_proteins.py trp-cage_sol constraints_mlmm
```

**Sources**: [benchmark/proteins/benchmark_proteins.py:16-21]()

### Running Water Benchmarks

```bash
# DIMOS with PME, float32 force field, float64 integration
python dimos_water.py dimosCUDAcompile PME 40 32 64

# OpenMM with Cutoff, double precision
python dimos_water.py openMMCUDA Cutoff 60 64 64

# TorchMD with PME, mixed precision
python dimos_water.py torchmdCUDAcompile PME 50 32 64
```

**Sources**: [benchmark/water/dimos_water.py:26-31]()

### Running ML Water Benchmarks

```bash
# DIMOS with MACE-large, float32
python dimos_water_ml.py dimosCUDAcompile mace-large 40 32 32

# DIMOS with MACE-medium + cuEq, float64
python dimos_water_ml.py dimosCUDAcuEqcompile mace-medium 50 64 64

# ASE with ORB, float32
python dimos_water_ml.py aseCUDA orb 30 32 32
```

**Sources**: [benchmark/water/dimos_water_ml.py:34-39]()

## Thread Control and Environment Variables

The benchmarks respect standard threading environment variables for CPU runs:

- **`OMP_NUM_THREADS`**: Controls OpenMP threading for PyTorch CPU operations
- **`OPENMM_CPU_THREADS`**: Controls threading for OpenMM CPU platform (automatically set from `OMP_NUM_THREADS`)

This ensures consistent threading behavior across platforms for fair CPU comparisons.

**Sources**: [benchmark/water/dimos_water.py:42-43]()

## Key Benchmarking Parameters

### Protein Benchmark Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| `c_graph` | `False` | Disable computation graph creation |
| `warmup_iterations` | `50` | Number of warmup cycles |
| `steps_per_warmup` | `25` | Simulation steps per warmup cycle |
| `measure_iterations` | `50` | Number of measurement cycles |
| `steps_per_measure` | `50` | Simulation steps per measurement cycle |
| `timestep` | `0.5` or `2.0` fs | Integration timestep (depends on constraints) |
| `temperature` | `300.0` K | Simulation temperature |
| `integrator_dtype` | `torch.float64` | Integrator precision |

**Sources**: [benchmark/proteins/benchmark_proteins.py:8-15](), [benchmark/proteins/benchmark_proteins.py:26-29](), [benchmark/proteins/benchmark_proteins.py:46]()

### Water Benchmark Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| `warmup` | `5` | Number of warmup cycles |
| `warmup_steps_between_pause` | `25` | Steps per warmup cycle |
| `steps_between_pause` | `35` | Steps per measurement cycle |
| `measure_steps` | `40` | Number of measurement cycles |
| `stepsize` | `0.5` fs | Integration timestep |
| `temperature` | `300` K | Simulation temperature |
| `cutoff` | `10.0` Å | Nonbonded cutoff distance |
| `switch_distance` | `7.5` Å | Switching function start distance |
| `langevin_gamma` | `1.0` or `0.1` ps⁻¹ | Friction coefficient (classical/ML) |

**Sources**: [benchmark/water/dimos_water.py:18-22](), [benchmark/water/dimos_water.py:61-63](), [benchmark/water/dimos_water_ml.py:26-30](), [benchmark/water/dimos_water_ml.py:69-86]()

## Trajectory Output

Both benchmark scripts support trajectory output for validation purposes:

- **Protein benchmarks**: Not written during benchmark runs
- **Classical water benchmarks**: Optional, written to `dimos{box_size}.pdb`
- **ML water benchmarks**: Written to `water{box_size}_ml.pdb`

The trajectory files can be used for visual inspection and trajectory analysis to verify simulation stability and correctness.

**Sources**: [benchmark/water/dimos_water.py:201-211](), [benchmark/water/dimos_water_ml.py:183-196]()

---