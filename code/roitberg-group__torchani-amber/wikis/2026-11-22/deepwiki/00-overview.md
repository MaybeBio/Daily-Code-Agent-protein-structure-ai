# Overview

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [README.md](README.md)
- [ani-amber-logo-dark.png](ani-amber-logo-dark.png)
- [ani-amber-logo-light.png](ani-amber-logo-light.png)
- [jit/jit.py](jit/jit.py)
- [jit/make_bulk.py](jit/make_bulk.py)
- [src/torchani.cpp](src/torchani.cpp)

</details>



## Purpose and Scope

TorchANI-Amber is a high-performance interface that integrates neural network potentials from the ANI family with the Amber molecular dynamics simulation suite. This system enables both full machine learning (ML) simulations where the entire potential energy surface is computed by neural networks, and hybrid ML/MM simulations where quantum mechanical regions are handled by neural networks while molecular mechanical regions use classical force fields.

This document provides a technical overview of the system architecture, core components, and integration mechanisms. For detailed installation instructions, see [Installation and Build](#2.1). For simulation configuration details, see [Simulation Configuration](#4.1). For performance testing information, see [Benchmarking System](#5).

## System Architecture

The following diagram illustrates the overall system architecture, showing how the various components interact during runtime:

```mermaid
graph TB
    subgraph "Build System"
        CMAKE["CMakeLists.txt<br/>Build Configuration"]
        JIT_PY["jit/jit.py<br/>Model Compilation"]
        MODELS["Pre-trained Models<br/>ANI1x, ANI2x, AimNet2"]
    end
    
    subgraph "Core Runtime Engine"
        TORCHANI_CPP["torchani.cpp<br/>C++ Implementation"]
        TORCHANI_H["torchani.h<br/>C API Interface"]
        GLOBAL_CONFIG["GlobalConfig<br/>Device & Precision"]
        JIT_MODELS["JIT Models<br/>.pt files"]
    end
    
    subgraph "Amber Integration Layer"
        TORCHANI_F90["torchani.F90<br/>Fortran Interface"]
        EXTPOT["External Potential<br/>iextpot=1"]
        QMMM["QM/MM Interface<br/>ifqnt=1"]
        MDIN["mdin Configuration<br/>&ani namelist"]
    end
    
    subgraph "MD Engines"
        SANDER["sander<br/>Amber MD Engine"]
        PMEMD["pmemd<br/>Amber MD Engine"]
    end
    
    CMAKE --> JIT_PY
    JIT_PY --> JIT_MODELS
    MODELS --> JIT_MODELS
    
    JIT_MODELS --> TORCHANI_CPP
    TORCHANI_CPP --> TORCHANI_H
    GLOBAL_CONFIG --> TORCHANI_CPP
    
    TORCHANI_H --> TORCHANI_F90
    MDIN --> EXTPOT
    MDIN --> QMMM
    
    TORCHANI_F90 --> SANDER
    EXTPOT --> SANDER
    QMMM --> SANDER
    EXTPOT --> PMEMD
    TORCHANI_F90 --> PMEMD
```

**Sources:** [src/torchani.cpp:1-918](), [include/torchani.h](), [jit/jit.py:1-180](), [README.md:9-18]()

## Core Runtime Components

### C++ Computational Engine

The core computational engine is implemented in `torchani.cpp` and provides the primary interface between Amber and PyTorch. Key global components include:

| Component | Type | Purpose |
|-----------|------|---------|
| `model` | `torch::jit::Module` | Loaded JIT-compiled neural network model |
| `torchani_atomic_numbers` | `torch::Tensor` | Atomic numbers tensor for the system |
| `config` | `GlobalConfig` | Device, precision, and runtime configuration |
| `torchani_builtin_models` | `std::vector<std::string>` | List of supported model names |

The following diagram shows the data flow through the C++ engine:

```mermaid
flowchart LR
    subgraph "Input Processing"
        COORDS["coords_buf[][]<br/>Atomic Coordinates"]
        ATOMIC_NUMS["atomic_nums[]<br/>Element Types"]
        CELL["cell_buf[][]<br/>Unit Cell"]
    end
    
    subgraph "Tensor Building"
        DBL_BUF_TO_COORDS["dbl_buf_to_coords_tensor()"]
        DBL_BUF_TO_CELL["dbl_buf_to_cell_tensor()"]
        SETUP_INPUTS["setup_inputs_pbc()<br/>setup_inputs_nopbc()"]
    end
    
    subgraph "Model Execution"
        MODEL_FORWARD["model.forward()"]
        JIT_IVALUE["torch::jit::IValue<br/>Output Tuple"]
        VALIDATE["validate_model_output()"]
    end
    
    subgraph "Output Processing"
        CALC_FORCES["calculate_and_populate_forces()"]
        POP_ENERGY["populate_potential_energy()"]
        POP_CHARGES["populate_atomic_charges()"]
    end
    
    COORDS --> DBL_BUF_TO_COORDS
    ATOMIC_NUMS --> SETUP_INPUTS
    CELL --> DBL_BUF_TO_CELL
    
    DBL_BUF_TO_COORDS --> SETUP_INPUTS
    DBL_BUF_TO_CELL --> SETUP_INPUTS
    SETUP_INPUTS --> MODEL_FORWARD
    
    MODEL_FORWARD --> JIT_IVALUE
    JIT_IVALUE --> VALIDATE
    VALIDATE --> CALC_FORCES
    VALIDATE --> POP_ENERGY
    VALIDATE --> POP_CHARGES
```

**Sources:** [src/torchani.cpp:22-70](), [src/torchani.cpp:372-563](), [include/build_tensors.h]()

### Model Loading and JIT Compilation

The system uses PyTorch's JIT compilation to convert Python models into optimized `.pt` files that can be loaded by the C++ runtime:

```mermaid
graph TD
    subgraph "JIT Compilation Phase"
        PYTHON_MODELS["Python ANI Models<br/>torchani.models.*"]
        JIT_SCRIPT["torch.jit.script()"]
        JIT_SAVE["torch.jit.save()"]
        PT_FILES[".pt Model Files<br/>ani1x.pt, ani2x.pt"]
    end
    
    subgraph "Runtime Loading"
        TORCHANI_INIT["torchani_initialize()"]
        JIT_LOAD["torch::jit::load()"]
        MODEL_CONFIG["Model Configuration<br/>set_active_members()"]
        DTYPE_CAST["model.to(config.dtype())"]
    end
    
    PYTHON_MODELS --> JIT_SCRIPT
    JIT_SCRIPT --> JIT_SAVE
    JIT_SAVE --> PT_FILES
    
    PT_FILES --> TORCHANI_INIT
    TORCHANI_INIT --> JIT_LOAD
    JIT_LOAD --> MODEL_CONFIG
    MODEL_CONFIG --> DTYPE_CAST
```

**Sources:** [jit/jit.py:76-93](), [src/torchani.cpp:485-558]()

## Integration Workflows

### Full-ML Simulation Workflow

For simulations where the entire system potential is computed by neural networks:

```mermaid
sequenceDiagram
    participant AMBER as "Amber (sander/pmemd)"
    participant EXTPOT as "External Potential"
    participant TORCHANI as "torchani_calc_energy_force()"
    participant MODEL as "torch::jit::Module"
    
    AMBER->>EXTPOT: "Coordinates + Configuration"
    EXTPOT->>TORCHANI: "torchani_calc_energy_force()"
    TORCHANI->>MODEL: "setup_inputs_pbc() + model.forward()"
    MODEL->>TORCHANI: "Energy + Forces Tensors"
    TORCHANI->>EXTPOT: "Forces + Potential Energy"
    EXTPOT->>AMBER: "Energy/Force Values"
```

**Sources:** [src/torchani.cpp:645-702](), [README.md:116-169]()

### ML/MM Simulation Workflow

For hybrid simulations with quantum and classical regions:

```mermaid
sequenceDiagram
    participant AMBER as "Amber sander"
    participant QMMM as "QM/MM Interface"
    participant TORCHANI as "torchani_energy_force_with_coupling()"
    participant ELECTRO as "electro.h (Coupling)"
    
    AMBER->>QMMM: "QM Region + MM Environment"
    QMMM->>TORCHANI: "QM coords + MM charges"
    TORCHANI->>TORCHANI: "ene_pot_invacuo = model.forward()"
    TORCHANI->>ELECTRO: "coulombic_embedding_energy()"
    ELECTRO->>TORCHANI: "Coupling Energy"
    TORCHANI->>QMMM: "Total Energy + Forces"
    QMMM->>AMBER: "Combined ML/MM Potential"
```

**Sources:** [src/torchani.cpp:730-833](), [include/electro.h](), [README.md:172-257]()

## Key Capabilities

### Supported Neural Network Models

The system supports multiple neural network potentials through the `torchani_builtin_models` vector:

| Model Family | Variants | Elements Supported |
|--------------|----------|--------------------|
| ANI-1x | `ani1x`, `ani1x-infer` | H, C, N, O |
| ANI-2x | `ani2x`, `ani2x-infer` | H, C, N, O, F, Cl, S |
| ANI-1ccx | `ani1ccx`, `ani1ccx-infer` | H, C, N, O |
| AimNet2 | `aimnet2-*-dsf/ewald/nocut` | Multiple variants |
| NutMeg | `nutmeg-small/medium/large` | Condensed phase systems |

### Runtime Configuration

The `GlobalConfig` class manages critical runtime parameters:

- **Device Selection**: CPU vs CUDA device configuration
- **Precision Control**: Float32 vs Float64 tensor operations  
- **PBC Support**: Periodic boundary condition handling
- **Atom Masking**: Selective evaluation for efficiency

### Performance Features

- **cuAEV Extension**: CUDA-accelerated atomic environment vectors via `use_cuaev`
- **External Neighborlists**: Amber-managed neighbor lists through `use_amber_neighborlist`
- **JIT Optimizations**: Disabled for accuracy via `torch::jit::setGraphExecutorOptimize(false)`
- **Ensemble Support**: Multiple network evaluation for uncertainty quantification

**Sources:** [src/torchani.cpp:34-69](), [src/torchani.cpp:474-539](), [include/config.h]()

---