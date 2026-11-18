# Molecular Simulations

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [mlatom/EEEDDDD.py](mlatom/EEEDDDD.py)
- [mlatom/constants.py](mlatom/constants.py)
- [mlatom/gen_ts_methods.py](mlatom/gen_ts_methods.py)
- [mlatom/initial_conditions.py](mlatom/initial_conditions.py)
- [mlatom/interfaces/sparrow_interface.py](mlatom/interfaces/sparrow_interface.py)
- [mlatom/md_cmd.py](mlatom/md_cmd.py)
- [mlatom/namd.py](mlatom/namd.py)
- [mlatom/simulations.py](mlatom/simulations.py)

</details>



This document covers MLatom's molecular simulation capabilities, including geometry optimization, frequency analysis, molecular dynamics, and nonadiabatic dynamics. These simulation methods form the core computational engines that utilize machine learning models and quantum chemistry methods to study molecular structure and dynamics.

For machine learning models used in simulations, see [Machine Learning Systems](#4). For quantum chemistry interfaces that provide electronic structure calculations, see [Quantum Chemistry Interfaces](#6).

## Simulation Architecture Overview

MLatom's simulation system is built around a modular architecture that separates simulation algorithms from the underlying computational methods (ML models or quantum chemistry programs).

### Core Simulation Framework

```mermaid
graph TD
    subgraph "Simulation Entry Points"
        SimPy["simulations.py<br/>Main simulation module"]
        NAMD["namd.py<br/>Nonadiabatic MD"]
        MDCMD["md_cmd.py<br/>MD command interface"]
        EEEDDDD["EEEDDDD.py<br/>Neural network MD"]
    end
    
    subgraph "Core Simulation Classes"
        OptGeom["optimize_geometry<br/>Geometry optimization"]
        FreqAnal["freq<br/>Frequency analysis"]
        SurfHop["surface_hopping_md<br/>Surface hopping dynamics"]
        IRC["irc<br/>Reaction coordinate"]
        GenTS["gen_ts<br/>Transition state generation"]
    end
    
    subgraph "Supporting Systems"
        InitCond["generate_initial_conditions<br/>Initial condition sampling"]
        RunPar["run_in_parallel<br/>Parallel execution"]
        Wigner["wigner_sampling<br/>Quantum sampling"]
    end
    
    subgraph "Computational Methods"
        MLModels["ML Models<br/>(ANI, MACE, etc.)"]
        QMIntf["QM Interfaces<br/>(PySCF, Gaussian, etc.)"]
        Methods["methods<br/>Composite methods"]
    end
    
    SimPy --> OptGeom
    SimPy --> FreqAnal
    SimPy --> IRC
    SimPy --> GenTS
    NAMD --> SurfHop
    MDCMD --> InitCond
    EEEDDDD --> RunPar
    
    InitCond --> Wigner
    OptGeom --> MLModels
    FreqAnal --> QMIntf
    SurfHop --> Methods
    
    RunPar --> OptGeom
    RunPar --> FreqAnal
    RunPar --> SurfHop
```

Sources: [mlatom/simulations.py:1-50](), [mlatom/namd.py:1-30](), [mlatom/initial_conditions.py:1-20](), [mlatom/EEEDDDD.py:1-30]()

### Simulation Type Classification

MLatom organizes simulations into several categories based on their computational requirements and physical phenomena:

| Simulation Type | Primary Classes | Key Methods | Typical Use Cases |
|----------------|----------------|-------------|-------------------|
| **Static Properties** | `optimize_geometry`, `freq` | Energy, gradients, Hessian | Structure optimization, vibrational analysis |
| **Classical Dynamics** | `md`, `MD_CMD` | Energy, forces | Thermal sampling, conformational search |
| **Quantum Dynamics** | `surface_hopping_md` | Energies, forces, couplings | Photochemistry, excited state dynamics |
| **Neural Network MD** | `EEEDDDD` | Trajectory prediction | Long timescale dynamics |

Sources: [mlatom/simulations.py:75-200](), [mlatom/namd.py:20-80](), [mlatom/md_cmd.py:50-100]()

## Integration with Computational Methods

The simulation framework is designed to work seamlessly with both machine learning models and quantum chemistry programs through a unified interface.

### Method Integration Pattern

```mermaid
graph LR
    subgraph "Simulation Algorithm"
        Sim["Simulation Class<br/>(optimize_geometry, freq, etc.)"]
        Predict["model.predict()"]
        Props["Properties<br/>(energy, gradients, etc.)"]
    end
    
    subgraph "Method Layer"
        Model["model<br/>Base class"]
        Kwargs["model_predict_kwargs<br/>Method-specific options"]
    end
    
    subgraph "Implementation Layer"
        ML["ML Models<br/>ANI, MACE, KRR"]
        QM["QM Methods<br/>PySCF, Gaussian"]
        Hybrid["Hybrid Methods<br/>AIQM1, AIQM2"]
    end
    
    Sim --> Predict
    Predict --> Model
    Model --> ML
    Model --> QM 
    Model --> Hybrid
    Kwargs --> Model
    Props --> Sim
```

Sources: [mlatom/simulations.py:115-130](), [mlatom/simulations.py:200-220]()

### Property Calculation Flow

The simulation classes interact with computational methods through standardized property requests:

```mermaid
flowchart TD
    Start["Simulation Initialization"] --> SetKwargs["Set model_predict_kwargs"]
    SetKwargs --> ReqProps["Request Properties<br/>calculate_energy: True<br/>calculate_energy_gradients: True<br/>calculate_hessian: False"]
    ReqProps --> CallPredict["model.predict(molecule, **kwargs)"]
    CallPredict --> CheckProps["Check Available Properties"]
    
    CheckProps --> HasEnergy{"Energy Available?"}
    HasEnergy -->|Yes| HasGrad{"Gradients Available?"}
    HasEnergy -->|No| Error["Raise ValueError"]
    
    HasGrad -->|Yes| UseAnalytic["Use Analytic Gradients"]
    HasGrad -->|No| UseNumeric["Use Numerical Derivatives"]
    
    UseAnalytic --> Continue["Continue Simulation"]
    UseNumeric --> Continue
    Error --> Stop["Stop Simulation"]
```

Sources: [mlatom/simulations.py:202-207](), [mlatom/simulations.py:324-330]()

## Parallel Execution Framework

MLatom provides a sophisticated parallel execution system for running simulations across multiple molecules or trajectories.

### Parallel Execution Architecture

The `run_in_parallel` function [mlatom/simulations.py:23-73]() provides a flexible framework for parallelizing any simulation task:

```mermaid
graph TD
    subgraph "Input"
        MolDB["molecular_database<br/>Collection of molecules"]
        Task["task<br/>Simulation function"]
        Kwargs["task_kwargs<br/>Simulation parameters"]
    end
    
    subgraph "Thread Management"
        JobLib["joblib.Parallel<br/>Thread pool management"]
        NThreads["nthreads<br/>Thread allocation"]
        TempDir["Temporary Directories<br/>Isolated workspaces"]
    end
    
    subgraph "Execution"
        TaskLoc["task_loc<br/>Per-molecule wrapper"]
        Results["Parallel Results<br/>List of simulation outputs"]
    end
    
    MolDB --> JobLib
    Task --> TaskLoc
    Kwargs --> TaskLoc
    JobLib --> NThreads
    NThreads --> TempDir
    TaskLoc --> Results
```

The parallel system automatically:
- Distributes available threads among molecules
- Creates isolated temporary directories when requested
- Handles thread-specific model configurations
- Collects results from all parallel executions

Sources: [mlatom/simulations.py:23-73]()

## Simulation Data Flow

The simulation system follows a consistent data flow pattern that ensures compatibility across different simulation types:

### Standard Simulation Pipeline

```mermaid
flowchart TD
    Input["Input Molecule<br/>+ Simulation Parameters"] --> Init["Initialize Simulation Class"]
    Init --> Validate["Validate Parameters<br/>Check method compatibility"]
    Validate --> SetupModel["Setup Model Interface<br/>Configure predict_kwargs"]
    
    SetupModel --> Program{"Optimization Program?"}
    Program -->|Gaussian| GaussOpt["opt_geom_gaussian()"]
    Program -->|ASE| ASEOpt["opt_geom_ase()"] 
    Program -->|geometric| GeomOpt["opt_geom_geometric()"]
    Program -->|scipy| ScipyOpt["opt_geom()"]
    
    GaussOpt --> SaveTraj["Save Trajectory"]
    ASEOpt --> SaveTraj
    GeomOpt --> SaveTraj
    ScipyOpt --> SaveTraj
    
    SaveTraj --> OptMol["optimized_molecule<br/>Final structure + properties"]
    OptMol --> Output["Output Results<br/>JSON, H5MD, plain text"]
```

Sources: [mlatom/simulations.py:215-218](), [mlatom/simulations.py:227-416]()

This architecture ensures that simulations can utilize any available computational method while maintaining consistent interfaces and output formats across the entire MLatom ecosystem.

---