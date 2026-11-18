# Advanced Dynamics

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [mlatom/EEEDDDD.py](mlatom/EEEDDDD.py)
- [mlatom/gen_ts_methods.py](mlatom/gen_ts_methods.py)
- [mlatom/namd.py](mlatom/namd.py)

</details>



This page covers advanced molecular dynamics capabilities in MLatom beyond traditional classical molecular dynamics. These include nonadiabatic molecular dynamics with surface hopping algorithms, neural network-based trajectory propagation, and transition state generation methods. For basic molecular dynamics simulations, see [Molecular Dynamics](#5.2). For geometry optimization and frequency calculations, see [Core Simulations](#5.1).

## Overview

Advanced dynamics in MLatom encompasses three main areas: nonadiabatic molecular dynamics for studying photochemical processes and excited state dynamics, neural network-based molecular dynamics using machine learning models to propagate trajectories, and computational methods for generating transition state structures. These methods extend beyond the adiabatic Born-Oppenheimer approximation used in classical molecular dynamics.

```mermaid
graph TB
    subgraph "Advanced Dynamics Systems"
        NAMD["surface_hopping_md<br/>Nonadiabatic MD"]
        NNMD["EEEDDDD<br/>Neural Network MD"]  
        TSGEN["gen_ts_ects<br/>Transition State Generation"]
    end
    
    subgraph "Core Infrastructure"
        DATA["data.molecular_trajectory<br/>Trajectory Storage"]
        MD["md<br/>Classical MD Engine"]
        MODELS["models<br/>ML Model Framework"]
    end
    
    subgraph "Surface Hopping Algorithms"
        FSSH["FSSH Algorithm<br/>Fewest Switches"]
        LZBL["LZBL Algorithm<br/>Landau-Zener-Belyaev-Lebedev"]
    end
    
    subgraph "Neural Network Components"
        E3ATTN["E3AttnBlk<br/>Attention Mechanism"]
        EEENNDDDD["EEENNDDDD<br/>Core NN Architecture"]
        ENSEMBLE["ModelEnsemble<br/>Uncertainty Quantification"]
    end
    
    NAMD --> FSSH
    NAMD --> LZBL
    NAMD --> MD
    NAMD --> DATA
    
    NNMD --> E3ATTN
    NNMD --> EEENNDDDD
    NNMD --> ENSEMBLE
    NNMD --> DATA
    
    TSGEN --> DATA
    
    FSSH --> MODELS
    LZBL --> MODELS
    EEENNDDDD --> MODELS
```

**Sources:** [mlatom/namd.py:1-942](), [mlatom/EEEDDDD.py:1-949](), [mlatom/gen_ts_methods.py:1-96]()

## Nonadiabatic Molecular Dynamics

Nonadiabatic molecular dynamics allows the study of processes where the Born-Oppenheimer approximation breaks down, such as photochemical reactions, energy transfer, and electronic relaxation. MLatom implements surface hopping algorithms to handle transitions between electronic states during molecular dynamics.

### Surface Hopping Algorithms

The `surface_hopping_md` class provides two main surface hopping algorithms:

| Algorithm | Description | Key Features |
|-----------|-------------|--------------|
| **FSSH** | Fewest Switches Surface Hopping | Coherent evolution of state coefficients, decoherence corrections |
| **LZBL** | Landau-Zener-Belyaev-Lebedev | Probabilistic hopping based on energy gap dynamics |

```mermaid
flowchart TD
    START["Initialize Trajectory<br/>surface_hopping_md.__init__"]
    
    INITSTATE["Set Initial State<br/>initial_state parameter"]
    PROPAGATE["Classical Propagation<br/>md class integration"]
    
    FSSH_BRANCH{"Algorithm Type"}
    
    FSSH_CALC["FSSH Calculation<br/>fssh() method"]
    LZBL_CALC["LZBL Calculation<br/>lzsh() method"]
    
    TDSE["Solve TDSE<br/>evolve_coeff_* methods"]
    GAPS["Calculate Energy Gaps<br/>lz_prob() method"]
    
    HOP_CHECK{"Hopping Probability<br/>random_number comparison"}
    
    RESCALE["Velocity Rescaling<br/>rescale_velocities()"]
    UPDATE_STATE["Update Current State"]
    
    CONTINUE["Continue Propagation"]
    END["Trajectory Complete"]
    
    START --> INITSTATE
    INITSTATE --> PROPAGATE
    PROPAGATE --> FSSH_BRANCH
    
    FSSH_BRANCH -->|"FSSH"| FSSH_CALC
    FSSH_BRANCH -->|"LZBL"| LZBL_CALC
    
    FSSH_CALC --> TDSE
    LZBL_CALC --> GAPS
    
    TDSE --> HOP_CHECK
    GAPS --> HOP_CHECK
    
    HOP_CHECK -->|"Hop Occurs"| RESCALE
    HOP_CHECK -->|"No Hop"| CONTINUE
    
    RESCALE --> UPDATE_STATE
    UPDATE_STATE --> CONTINUE
    
    CONTINUE --> PROPAGATE
    CONTINUE --> END
```

**Sources:** [mlatom/namd.py:21-251](), [mlatom/namd.py:499-653](), [mlatom/namd.py:451-492]()

### FSSH Implementation Details

The FSSH algorithm evolves quantum state coefficients coherently while allowing probabilistic hops between electronic states. Key components include:

- **Time-dependent Schrödinger equation integration**: Multiple integrators available (`RK4`, `AM5`, `Butcher`)
- **Decoherence corrections**: Simplified Decay of Mixing (SDM) model
- **Velocity rescaling**: Along nonadiabatic coupling vectors or momentum direction

The implementation subdivides each classical time step into smaller quantum time steps for accurate TDSE integration:

```python
# From namd.py lines 514-515
n_substeps = int(self.time_step / self.time_step_tdse)
```

**Sources:** [mlatom/namd.py:238-250](), [mlatom/namd.py:513-653](), [mlatom/namd.py:682-753]()

### Trajectory Analysis and Population Dynamics

The module provides analysis functions for surface hopping trajectories:

- `analyze_trajs()`: Analyzes trajectory completion status
- `plot_population()`: Creates state population plots over time
- `plot_population_from_disk()`: Analysis for trajectories stored on disk

```mermaid
graph LR
    TRAJS["List of Trajectories<br/>molecular_trajectory objects"]
    
    ANALYZE["analyze_trajs()<br/>Check completion status"]
    PLOT["plot_population()<br/>Calculate state populations"]
    
    STATUS["Trajectory Status Report<br/>Normal/Abnormal completion"]
    POP_DATA["Population Data<br/>Time-resolved state populations"]
    POP_PLOT["Population Plot<br/>Visualization (.png file)"]
    
    TRAJS --> ANALYZE
    TRAJS --> PLOT
    
    ANALYZE --> STATUS
    PLOT --> POP_DATA
    PLOT --> POP_PLOT
```

**Sources:** [mlatom/namd.py:767-942]()

## Neural Network-Based Molecular Dynamics

The `EEEDDDD` model implements neural network-based molecular dynamics using E3-equivariant attention mechanisms. This approach learns to propagate molecular trajectories directly from training data, enabling efficient simulation of complex molecular systems.

### Architecture Overview

The neural network architecture combines several advanced components:

| Component | Purpose | Implementation |
|-----------|---------|----------------|
| **Species Embedding** | Atomic type representation | `torch.nn.Embedding` |
| **E3 Attention Blocks** | Equivariant message passing | `E3AttnBlk` class |
| **Time Encoding** | Temporal information embedding | Gaussian basis functions |
| **Spatial Encoding** | Distance-based representations | Soft one-hot encoding |

```mermaid
graph TB
    INPUT["Input State<br/>coordinates, velocities, species, time"]
    
    subgraph "EEENNDDDD Neural Network"
        EMBED["Species Embedding<br/>sp_embed"]
        TIME_EMBED["Time Embedding<br/>soft_one_hot_linspace"]
        
        subgraph "E3 Attention Layers"
            ATTN1["E3AttnBlk Layer 1"]
            ATTN2["E3AttnBlk Layer 2"]
            ATTNX["E3AttnBlk Layer N<br/>num_attn_blocks"]
        end
        
        RESIDUAL["Residual Connections<br/>+ input features"]
    end
    
    OUTPUT["Next State<br/>updated coordinates"]
    
    INPUT --> EMBED
    INPUT --> TIME_EMBED
    
    EMBED --> ATTN1
    TIME_EMBED --> ATTN1
    ATTN1 --> ATTN2
    ATTN2 --> ATTNX
    
    ATTNX --> RESIDUAL
    RESIDUAL --> OUTPUT
    
    EMBED -.->|"Skip connection"| RESIDUAL
    INPUT -.->|"Skip connection"| RESIDUAL
```

**Sources:** [mlatom/EEEDDDD.py:99-197](), [mlatom/EEEDDDD.py:26-96]()

### E3-Equivariant Attention Mechanism

The `E3AttnBlk` class implements rotation-equivariant attention using spherical harmonics and tensor products:

- **Query/Key/Value projections**: Using `o3.Linear` and `o3.FullyConnectedTensorProduct`
- **Spherical harmonics**: Encode directional information
- **Attention weights**: Distance and time-dependent MLP networks
- **Multi-head attention**: Parallel processing of different representation spaces

Key architectural parameters include `lmax` for spherical harmonic order, `num_heads` for attention heads, and various `irreps_*` parameters defining the irreducible representations.

**Sources:** [mlatom/EEEDDDD.py:25-96](), [mlatom/EEEDDDD.py:200-218]()

### Training and Active Learning

The `EEEDDDD` model supports sophisticated training protocols:

```mermaid
flowchart LR
    TRAJS["Training Trajectories<br/>molecular_trajectory data"]
    DATASET["Dataset Creation<br/>trajs_to_dataset()"]
    
    PROVIDER["DataProvider<br/>Train/Valid/Pool splits"]
    TRAIN_LOOP["Training Loop<br/>AdamW optimizer"]
    
    AL_CHECK{"Active Learning<br/>AL_interval"}
    POOL_EVAL["Pool Evaluation<br/>Uncertainty scoring"]
    UPDATE["Update Training Set<br/>High-uncertainty samples"]
    
    CONVERGED["Model Converged<br/>Save best weights"]
    
    TRAJS --> DATASET
    DATASET --> PROVIDER
    PROVIDER --> TRAIN_LOOP
    
    TRAIN_LOOP --> AL_CHECK
    AL_CHECK -->|"No AL"| CONVERGED
    AL_CHECK -->|"AL enabled"| POOL_EVAL
    
    POOL_EVAL --> UPDATE
    UPDATE --> PROVIDER
```

**Sources:** [mlatom/EEEDDDD.py:342-577](), [mlatom/EEEDDDD.py:794-863]()

### Trajectory Propagation

The trained model can propagate molecular trajectories using the `propagate()` method:

- **Time segmentation**: Long trajectories split into manageable segments
- **Energy conservation**: Optional velocity rescaling with potential models
- **Ensemble uncertainty**: Support for model ensembles and uncertainty quantification
- **Periodic boundary conditions**: Support for crystal simulations

**Sources:** [mlatom/EEEDDDD.py:646-717]()

## Transition State Generation

The `gen_ts_ects()` function provides an interface to the EcTs (External Transition State) method for generating transition state structures between reactant and product molecules.

### EcTs Integration

The function integrates with the external EcTs package to generate transition states:

```mermaid
graph TB
    REACTANT["Reactant Molecule<br/>data.molecule"]
    PRODUCT["Product Molecule<br/>data.molecule"]
    
    CONVERT["Molecule Conversion<br/>xyz2mol, xyz2AC"]
    RP_PAIR["RP_pair Object<br/>Reaction pair representation"]
    
    ECTS_MODEL["EcTs_Model<br/>External ML model"]
    
    TS_GEN["Transition State Generation<br/>Sample_TS() or Sample_Path()"]
    
    RESULTS["Results<br/>gen_ts_results tuple"]
    
    REACTANT --> CONVERT
    PRODUCT --> CONVERT
    CONVERT --> RP_PAIR
    
    RP_PAIR --> ECTS_MODEL
    ECTS_MODEL --> TS_GEN
    TS_GEN --> RESULTS
```

**Sources:** [mlatom/gen_ts_methods.py:11-96]()

### Output Structure

The `gen_ts_results` named tuple provides structured output:

| Field | Type | Description |
|-------|------|-------------|
| `ts` | `List[data.molecule]` | Generated transition state structures |
| `avg_ts` | `data.molecule` | Average transition state structure |
| `path` | `List[data.molecular_database]` | Complete reaction paths (if requested) |
| `avg_path` | `data.molecular_database` | Average reaction path |

**Sources:** [mlatom/gen_ts_methods.py:5-10](), [mlatom/gen_ts_methods.py:70-96]()

## Integration with MLatom Ecosystem

Advanced dynamics methods integrate seamlessly with the broader MLatom framework:

```mermaid
graph TB
    subgraph "User Interface"
        CLI["MLatom CLI<br/>Command line interface"]
        PYTHON["Python API<br/>Direct method calls"]
    end
    
    subgraph "Advanced Dynamics"
        NAMD_CLS["surface_hopping_md"]
        NNMD_CLS["EEEDDDD"]
        TS_CLS["gen_ts_ects"]
    end
    
    subgraph "Core Framework"
        DATA_CLS["data.molecular_trajectory<br/>Trajectory storage"]
        MODEL_CLS["models<br/>Energy/force providers"]
        SIM_CLS["simulations<br/>Parallel execution"]
    end
    
    subgraph "External Interfaces"
        QM_INTERFACES["Quantum chemistry<br/>programs (PySCF, Gaussian)"]
        ML_MODELS["Machine learning<br/>models (ANI, MACE)"]
    end
    
    CLI --> NAMD_CLS
    PYTHON --> NAMD_CLS
    PYTHON --> NNMD_CLS  
    PYTHON --> TS_CLS
    
    NAMD_CLS --> DATA_CLS
    NAMD_CLS --> MODEL_CLS
    NNMD_CLS --> DATA_CLS
    TS_CLS --> DATA_CLS
    
    MODEL_CLS --> QM_INTERFACES
    MODEL_CLS --> ML_MODELS
    
    SIM_CLS --> NAMD_CLS
```

**Sources:** [mlatom/namd.py:14-16](), [mlatom/EEEDDDD.py:13-15](), [mlatom/gen_ts_methods.py:3]()

The advanced dynamics capabilities extend MLatom's simulation framework beyond classical molecular dynamics, enabling the study of photochemical processes, machine learning-accelerated dynamics, and transition state chemistry within a unified computational platform.

---