# Core Architecture

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [mlatom/__init__.py](mlatom/__init__.py)
- [mlatom/data.py](mlatom/data.py)
- [mlatom/models.py](mlatom/models.py)

</details>



This document covers MLatom's fundamental data structures, model framework, and package organization that form the foundation for all molecular simulations and machine learning workflows. For command-line interface details, see [Command Line Interface](#3). For specific machine learning implementations, see [Machine Learning Systems](#4).

## Overview

MLatom's architecture is built around a hierarchy of core data structures and a flexible model framework that enables seamless integration between quantum chemistry calculations, machine learning models, and molecular simulations. The architecture follows a layered design where data flows from fundamental atomic representations through molecular assemblies to machine learning databases.

```mermaid
graph TB
    subgraph "Core Data Layer"
        ATOM["atom<br/>Individual atomic data"]
        MOLECULE["molecule<br/>Collections of atoms<br/>+ properties"]
        MOLDB["molecular_database<br/>Collections of molecules"]
        MLDB["ml_database<br/>ML training data"]
    end
    
    subgraph "Model Framework"
        BASE["model (base class)"]
        MLMODEL["ml_model (base class)"]
        KRR["krr<br/>Kernel Ridge Regression"]
        KREG["kreg<br/>KREG implementation"]
        METHODS["methods()<br/>Universal model factory"]
    end
    
    subgraph "Integration Layer"
        INTERFACES["Program Interfaces<br/>(ANI, MACE, Gaussian, etc.)"]
        TASKS["MLtasks.py<br/>Task orchestration"]
    end
    
    ATOM --> MOLECULE
    MOLECULE --> MOLDB
    MOLDB --> MLDB
    MLDB --> KRR
    MLDB --> KREG
    BASE --> MLMODEL
    MLMODEL --> KRR
    MLMODEL --> KREG
    METHODS --> KRR
    METHODS --> KREG
    METHODS --> INTERFACES
    TASKS --> MOLDB
    TASKS --> METHODS
```

Sources: [mlatom/data.py:1-2000](), [mlatom/models.py:1-800](), [mlatom/__init__.py:1-16]()

## Data Structure Hierarchy

The core data structures form a hierarchical system where atomic data aggregates into molecular representations, which then organize into databases for machine learning workflows.

### Atomic Level: `atom` Class

The `atom` class represents individual atoms with their nuclear properties and coordinates:

```mermaid
classDiagram
    class atom {
        +atomic_number: int
        +element_symbol: str
        +nuclear_charge: int
        +nuclear_mass: float
        +xyz_coordinates: ndarray
        +copy() atom
    }
    class Properties {
        +multiplicity: float
        +H0: float 
        +nuclear_spin: float
    }
    atom --> Properties : "derived properties"
```

Key features include automatic element symbol resolution and isotope property lookup through the periodic table mapping system.

Sources: [mlatom/data.py:191-294]()

### Molecular Level: `molecule` Class

The `molecule` class aggregates atoms and manages molecular properties:

```mermaid
classDiagram
    class molecule {
        +atoms: List[atom]
        +charge: int
        +multiplicity: int
        +xyz_coordinates: ndarray
        +electronic_states: List
        +pbc: ndarray
        +cell: ndarray
        +read_from_xyz_file()
        +copy() molecule
        +get_internuclear_distance_matrix()
    }
    class MolecularProperties {
        +energy: float
        +energy_gradients: ndarray
        +frequencies: ndarray
        +state_energies: ndarray
    }
    class GeometryOps {
        +bond_length()
        +bond_angle()
        +dihedral_angle()
        +proliferate()
    }
    molecule --> atom : "contains"
    molecule --> MolecularProperties : "stores"
    molecule --> GeometryOps : "geometry operations"
```

The class supports multiple file formats (XYZ, SMILES, Gaussian), periodic boundary conditions, and vectorial properties for gradients and forces.

Sources: [mlatom/data.py:329-1320]()

### Database Level: `molecular_database` and `ml_database`

Two complementary database classes handle different data organization needs:

```mermaid
graph TD
    subgraph "molecular_database"
        MOLDB_CLASS["molecular_database"]
        MOLS["molecules: List[molecule]"]
        MOLDB_OPS["read_from_xyz_file()<br/>read_from_h5_file()<br/>get_properties()"]
    end
    
    subgraph "ml_database" 
        MLDB_CLASS["ml_database"]
        ENTRIES["entries: List[entry]"]
        ENTRY_CLASS["entry<br/>x: ndarray<br/>y: Union[float, ndarray]"]
        MLDB_OPS["split()<br/>get_x()<br/>get_property()"]
    end
    
    MOLDB_CLASS --> MOLS
    MOLDB_CLASS --> MOLDB_OPS
    MLDB_CLASS --> ENTRIES
    ENTRIES --> ENTRY_CLASS
    MLDB_CLASS --> MLDB_OPS
    
    MOLS -.-> ENTRIES : "can convert"
```

The `molecular_database` focuses on chemical structure and properties, while `ml_database` provides a general-purpose container for machine learning with arbitrary feature vectors and targets.

Sources: [mlatom/data.py:364-1600](), [mlatom/data.py:38-177]()

## Model Framework Architecture

The model framework provides a unified interface for various computational methods through an inheritance hierarchy and factory pattern.

### Base Model Classes

```mermaid
classDiagram
    class model {
        +predict()
        +parse_args()
        +generate_model_dict()
        +set_num_threads()
    }
    class ml_model {
        +train()
        +hyperparameters: hyperparameters
        +hyperparameter_optimization()
    }
    class OMP_model {
        +nthreads: int
    }
    class MKL_model {
        +nthreads: int
    }
    
    model <|-- ml_model
    ml_model <|-- OMP_model
    ml_model <|-- MKL_model
```

Base classes define common interfaces while specialized classes add training capabilities and threading support.

Sources: [mlatom/model_cls.py](), [mlatom/models.py:16-17]()

### Core ML Implementations

The framework includes two primary kernel-based implementations:

```mermaid
graph TB
    subgraph "KRR Implementation"
        KRR_CLASS["krr"]
        KRR_SCIPY["scipy backend"]
        KRR_JULIA["mlatom.jl backend"]
        KRR_KERNELS["Gaussian, Matern,<br/>periodic kernels"]
    end
    
    subgraph "KREG Implementation"
        KREG_CLASS["kreg"]
        KREG_API["KREG_API backend"]
        KREG_MLF["MLatomF backend"]
        KREG_DESC["RE descriptor<br/>generation"]
    end
    
    ml_model --> KRR_CLASS
    ml_model --> KREG_CLASS
    KRR_CLASS --> KRR_SCIPY
    KRR_CLASS --> KRR_JULIA
    KRR_CLASS --> KRR_KERNELS
    KREG_CLASS --> KREG_API
    KREG_CLASS --> KREG_MLF
    KREG_CLASS --> KREG_DESC
```

Both classes support energy and gradient predictions with automatic hyperparameter optimization capabilities.

Sources: [mlatom/models.py:18-342](), [mlatom/models.py:343-553]()

### Universal Method Factory

The `methods()` function provides a unified entry point for all computational methods:

```mermaid
flowchart TD
    A["methods(method, program, **kwargs)"] --> B{program specified?}
    B -->|Yes| C["Load program-specific<br/>method class"]
    B -->|No| D["Search known_classes<br/>for method support"]
    
    C --> E["Return method instance"]
    D --> F{Method found?}
    F -->|Yes| E
    F -->|No| G["Raise ValueError"]
    
    H["known_classes list:<br/>aiqm1, aiqm2, ani_methods,<br/>gaussian_methods, pyscf_methods,<br/>etc."] --> D
```

This factory pattern enables automatic method detection and provides consistent interfaces across different quantum chemistry programs and ML models.

Sources: [mlatom/models.py:626-690](), [mlatom/models.py:624-625]()

## Package Organization

MLatom's modular structure separates concerns while enabling flexible composition:

```mermaid
graph TB
    subgraph "Core Modules"
        DATA["data.py<br/>Fundamental data structures"]
        MODELS["models.py<br/>Model framework + implementations"]
        MODEL_CLS["model_cls.py<br/>Base classes"]
    end
    
    subgraph "Task Management"
        MLATOM["MLatom.py<br/>Main entry point"]
        MLTASKS["MLtasks.py<br/>Task orchestration"]
        ARGS["args_class.py<br/>Argument parsing"]
    end
    
    subgraph "Domain-Specific"
        SIM["simulations.py<br/>Molecular simulations"]
        AL["al.py<br/>Active learning"]
        NAMD["namd.py<br/>Nonadiabatic dynamics"]
        SPECTRA["spectra.py<br/>Spectroscopic analysis"]
    end
    
    subgraph "Interfaces"
        INTERFACES["interfaces/<br/>External program interfaces"]
    end
    
    MLATOM --> MLTASKS
    MLTASKS --> DATA
    MLTASKS --> MODELS
    MODELS --> MODEL_CLS
    MODELS --> INTERFACES
    SIM --> DATA
    AL --> MODELS
    NAMD --> SIM
```

The `__init__.py` exposes key classes and functions for direct user access while maintaining clean module boundaries.

Sources: [mlatom/__init__.py:1-16](), [mlatom/MLatom.py](), [mlatom/MLtasks.py]()

---