# Amber Integration

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [README.md](README.md)
- [ani-amber-logo-dark.png](ani-amber-logo-dark.png)
- [ani-amber-logo-light.png](ani-amber-logo-light.png)
- [src/electro.cpp](src/electro.cpp)
- [src/electro.h](src/electro.h)
- [tests/templates/input.mdin.jinja](tests/templates/input.mdin.jinja)
- [tests/test_amber_integration.py](tests/test_amber_integration.py)

</details>



This document provides a comprehensive overview of how TorchANI integrates with the Amber molecular dynamics simulation suite. It covers the architecture, integration modes, and configuration mechanisms that enable neural network potentials to be used within Amber's `pmemd` and `sander` engines.

For detailed configuration options and namelist parameters, see [Simulation Configuration](#4.1). For ML/MM setup specifics and coupling schemes, see [ML/MM Setup and Coupling](#4.2). For example configurations and templates, see [Input Templates and Examples](#4.3).

## Integration Architecture

TorchANI-Amber provides two primary integration pathways with Amber: external potential interface for full-ML simulations and QM/MM interface for hybrid ML/MM simulations. Both pathways utilize the same core C++ engine but interface with different Amber subsystems.

```mermaid
graph TB
    subgraph "Amber MD Engines"
        PMEMD["pmemd"]
        SANDER["sander"]
    end
    
    subgraph "Integration Interfaces"
        EXTPOT["External Potential Interface<br/>iextpot=1, extprog='TORCHANI'"]
        QMMM["QM/MM Interface<br/>ifqnt=1, qm_theory='EXTERN'"]
    end
    
    subgraph "TorchANI Core Engine"
        CAPI["torchani.h<br/>C API Functions"]
        FAPI["torchani.F90<br/>Fortran Interface"]
        CPP["torchani.cpp<br/>Core Implementation"]
    end
    
    subgraph "Neural Network Backend"
        JIT["PyTorch JIT Models<br/>.pt files"]
        CUAEV["cuAEV Extensions<br/>CUDA Acceleration"]
    end
    
    PMEMD --> EXTPOT
    PMEMD --> QMMM
    SANDER --> EXTPOT
    SANDER --> QMMM
    
    EXTPOT --> FAPI
    QMMM --> FAPI
    FAPI --> CAPI
    CAPI --> CPP
    
    CPP --> JIT
    CPP --> CUAEV
```

Sources: [README.md:9-18](), [README.md:172-184](), [tests/test_amber_integration.py:32-76]()

## Integration Modes

TorchANI-Amber supports two distinct integration modes, each targeting different simulation scenarios and utilizing different Amber interfaces.

### Full-ML Mode

```mermaid
graph LR
    subgraph "Amber Configuration"
        MDIN1["mdin file<br/>iextpot=1"]
        EXTPOT1["&extpot namelist<br/>extprog='TORCHANI'"]
        ANI1["&ani namelist<br/>model configuration"]
    end
    
    subgraph "Integration Flow"
        AMBER1["Amber Engine"] --> EXT_IF["External Potential<br/>Interface"]
        EXT_IF --> TORCHANI1["TorchANI Engine"]
        TORCHANI1 --> FORCES1["Forces & Energies"]
        FORCES1 --> AMBER1
    end
    
    MDIN1 --> AMBER1
    EXTPOT1 --> EXT_IF
    ANI1 --> TORCHANI1
```

In full-ML mode, the entire molecular system's potential energy is calculated using neural network models. This mode uses Amber's external potential interface (`iextpot=1`) and requires the `&extpot` namelist with `extprog='TORCHANI'`.

### ML/MM Mode

```mermaid
graph LR
    subgraph "Amber Configuration"
        MDIN2["mdin file<br/>ifqnt=1"]
        QMMM2["&qmmm namelist<br/>qm_theory='EXTERN'"]
        ANI2["&ani namelist<br/>ML/MM options"]
    end
    
    subgraph "System Partitioning"
        QM_REGION["QM Region<br/>(Neural Network)"]
        MM_REGION["MM Region<br/>(Force Field)"]
        COUPLING["ML/MM Coupling<br/>Electrostatic"]
    end
    
    subgraph "Integration Flow"
        AMBER2["Sander Engine"] --> QMMM_IF["QM/MM Interface"]
        QMMM_IF --> QM_REGION
        QMMM_IF --> MM_REGION
        QM_REGION --> COUPLING
        MM_REGION --> COUPLING
        COUPLING --> FORCES2["Combined Forces"]
        FORCES2 --> AMBER2
    end
    
    MDIN2 --> AMBER2
    QMMM2 --> QMMM_IF
    ANI2 --> QM_REGION
```

ML/MM mode partitions the system into QM and MM regions, using neural networks for the QM region and classical force fields for the MM region. This mode requires `ifqnt=1` and uses Amber's QM/MM subsystem with `qm_theory='EXTERN'`.

Sources: [README.md:116-170](), [README.md:172-257](), [tests/templates/input.mdin.jinja:3-47]()

## Electrostatic Coupling Mechanisms

The ML/MM interface implements sophisticated electrostatic coupling schemes to handle the interaction between QM and MM regions.

```mermaid
graph TB
    subgraph "Coupling Types"
        COULOMBIC["Coulombic Coupling<br/>mlmm_coupling=0<br/>Fixed charges"]
        POLARIZABLE["Simple Polarizable Coupling<br/>mlmm_coupling=1<br/>Variable charges"]
    end
    
    subgraph "Charge Handling"
        FIXED["use_torchani_charges=false<br/>Topology charges"]
        PREDICTED["use_torchani_charges=true<br/>Neural network charges"]
    end
    
    subgraph "Electrostatic Functions"
        COULOMB_FUNC["coulombic_embedding_energy()<br/>electro.cpp:78-88"]
        POLAR_FUNC["polarizable_embedding_energy()<br/>electro.cpp:61-77"]
        EFIELD["calc_efield()<br/>electro.cpp:24-39"]
    end
    
    COULOMBIC --> FIXED
    COULOMBIC --> COULOMB_FUNC
    POLARIZABLE --> PREDICTED
    POLARIZABLE --> POLAR_FUNC
    POLAR_FUNC --> EFIELD
```

The electrostatic coupling is implemented through dedicated functions in the `electro` namespace that calculate electric fields, polarization energies, and Coulombic interactions between QM and MM regions.

Sources: [src/electro.cpp:78-88](), [src/electro.cpp:61-77](), [src/electro.h:4-18](), [README.md:197-212]()

## Configuration Flow

```mermaid
graph TD
    subgraph "Input Configuration"
        TEMPLATE["Jinja2 Templates<br/>input.mdin.jinja"]
        MDIN["Generated mdin file"]
        SYSTEM["System Files<br/>.prmtop, .inpcrd"]
    end
    
    subgraph "Runtime Configuration"
        NAMELISTS["Amber Namelists<br/>&cntrl, &extpot, &qmmm, &ani"]
        INIT["torchani_initialize()"]
        MODEL_LOAD["Model Loading<br/>torch::jit::load()"]
    end
    
    subgraph "Execution Flow"
        MD_LOOP["MD Time Step"]
        COORD_PASS["Coordinate Transfer"]
        ENERGY_CALC["Energy/Force Calculation"]
        FORCE_RETURN["Force Return"]
    end
    
    TEMPLATE --> MDIN
    MDIN --> NAMELISTS
    NAMELISTS --> INIT
    INIT --> MODEL_LOAD
    MODEL_LOAD --> MD_LOOP
    
    MD_LOOP --> COORD_PASS
    COORD_PASS --> ENERGY_CALC
    ENERGY_CALC --> FORCE_RETURN
    FORCE_RETURN --> MD_LOOP
```

The configuration process involves template-based mdin file generation, namelist parsing, model initialization, and runtime execution through Amber's MD loop.

Sources: [tests/templates/input.mdin.jinja:1-98](), [tests/test_amber_integration.py:344-380]()

## Interface API Structure

The integration is implemented through a layered API structure that provides both C and Fortran interfaces to accommodate Amber's mixed-language codebase.

| Interface Layer | File | Purpose |
|----------------|------|---------|
| Fortran Interface | `torchani.F90` | Amber-compatible Fortran bindings |
| C API | `torchani.h` | C function declarations and types |
| Core Implementation | `torchani.cpp` | PyTorch JIT model execution |
| Electrostatic Coupling | `electro.cpp` | ML/MM interaction calculations |

The API supports both full-ML calculations where TorchANI handles the entire system potential and ML/MM calculations where it integrates with Amber's QM/MM infrastructure.

## Configuration Namelist Overview

TorchANI-Amber uses Amber's namelist system for configuration, with different namelists required for different integration modes:

| Namelist | Required For | Key Parameters |
|----------|-------------|----------------|
| `&cntrl` | All modes | `iextpot=1` (full-ML) or `ifqnt=1` (ML/MM) |
| `&extpot` | Full-ML only | `extprog='TORCHANI'` |
| `&qmmm` | ML/MM only | `qm_theory='EXTERN'`, `qmmask` |
| `&ani` | All modes | `model_type`, `use_cuda_device`, coupling options |

The `&ani` namelist contains TorchANI-specific options including model selection, precision settings, CUDA configuration, and ML/MM coupling parameters.

Sources: [README.md:123-151](), [README.md:180-207](), [tests/templates/input.mdin.jinja:48-96]()

---