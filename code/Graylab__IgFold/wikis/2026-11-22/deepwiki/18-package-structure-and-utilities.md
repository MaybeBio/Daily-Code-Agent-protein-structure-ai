# Package Structure and Utilities

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [igfold/refine/__init__.py](igfold/refine/__init__.py)
- [igfold/utils/__init__.py](igfold/utils/__init__.py)
- [igfold/utils/general.py](igfold/utils/general.py)

</details>



This document provides an overview of IgFold's package organization, initialization files, utility modules, and development infrastructure. It covers the codebase structure, common utility functions, and setup considerations for developers working on IgFold internals.

For information about the core neural network components, see [Model Components](#7.1). For training-related utilities and metrics, see [Training and Loss Functions](#7.2).

## Package Organization

IgFold follows a modular package structure that separates core functionality, utilities, and optional components into distinct modules. The codebase is organized to support both end-user interfaces and internal development workflows.

### Top-Level Package Structure

```mermaid
graph TD
    subgraph "igfold/"
        INIT["__init__.py"]
        MAIN["IgFoldRunner"]
        FOLDING["folding/"]
        EMBEDDING["embedding/"]
        TRAINING["training/"]
        UTILS["utils/"]
        REFINE["refine/"]
    end
    
    subgraph "Core Modules"
        FOLDING --> FOLD_UTILS["fold utilities"]
        EMBEDDING --> EMBED_UTILS["embed utilities"] 
        TRAINING --> TRAIN_UTILS["training utilities"]
    end
    
    subgraph "Support Modules"
        UTILS --> GENERAL["general.py"]
        UTILS --> PDB_UTILS["pdb utilities"]
        UTILS --> COORD_UTILS["coordinate utilities"]
        REFINE --> OPENMM_REF["openmm refinement"]
        REFINE --> PYROSETTA_REF["pyrosetta refinement"]
    end
    
    INIT --> MAIN
    MAIN --> FOLDING
    MAIN --> EMBEDDING
```

**Sources:** [igfold/refine/__init__.py:1](), [igfold/utils/__init__.py:1]()

### Module Hierarchy

The package structure reflects the logical separation of concerns in the IgFold system:

| Module | Purpose | Key Components |
|--------|---------|----------------|
| `igfold/` | Main package entry point | `IgFoldRunner`, core APIs |
| `igfold/folding/` | Structure prediction pipeline | Folding utilities, model interfaces |
| `igfold/embedding/` | Sequence embedding functionality | AntiBERTy integration, embeddings |
| `igfold/training/` | Model training components | Loss functions, training loops |
| `igfold/utils/` | General utilities | Data processing, constants, helpers |
| `igfold/refine/` | Structure refinement | OpenMM, PyRosetta integration |

## Initialization Files

The package uses `__init__.py` files to define module boundaries and control import behavior. These files are typically minimal, focusing on exposing the primary interfaces from each module.

### Package Initialization Pattern

```mermaid
graph LR
    subgraph "Package Structure"
        ROOT["igfold/__init__.py"]
        UTILS_INIT["igfold/utils/__init__.py"]
        REFINE_INIT["igfold/refine/__init__.py"]
    end
    
    subgraph "Import Behavior"
        ROOT --> RUNNER["IgFoldRunner"]
        ROOT --> FOLD_API["fold()"]
        ROOT --> EMBED_API["embed()"]
        
        UTILS_INIT --> UTIL_FUNCS["utility functions"]
        REFINE_INIT --> REFINE_FUNCS["refinement functions"]
    end
```

The initialization files follow a consistent pattern:
- **Empty initialization files** - Most `__init__.py` files are empty, serving only as package markers
- **Selective exports** - Main package exposes primary user-facing APIs
- **Lazy loading** - Heavy dependencies loaded only when needed

**Sources:** [igfold/refine/__init__.py:1](), [igfold/utils/__init__.py:1]()

## Utility Modules

The `utils` package contains shared functionality used across the IgFold system, including data processing utilities, constants, and helper functions.

### General Utilities

The `general.py` module provides fundamental constants and utility functions used throughout the codebase:

```mermaid
graph TD
    subgraph "igfold/utils/general.py"
        AA_DICT["_aa_dict"]
        AA_1_3_DICT["_aa_1_3_dict"] 
        EXISTS_FUNC["exists()"]
        DEFAULT_FUNC["default()"]
    end
    
    subgraph "Amino Acid Mappings"
        AA_DICT --> SINGLE_TO_NUM["Single letter → Number"]
        AA_1_3_DICT --> SINGLE_TO_THREE["Single letter → Three letter"]
    end
    
    subgraph "Utility Functions"
        EXISTS_FUNC --> NULL_CHECK["None value checking"]
        DEFAULT_FUNC --> DEFAULT_VAL["Default value assignment"]
    end
```

#### Amino Acid Constants

The module defines standard amino acid mappings used for sequence processing:

- **`_aa_dict`** - Maps single-letter amino acid codes to numeric representations [igfold/utils/general.py:1-22]()
- **`_aa_1_3_dict`** - Maps single-letter codes to three-letter codes [igfold/utils/general.py:24-46]()

These dictionaries support 20 standard amino acids plus a gap character, providing consistent encoding across the system.

#### Helper Functions

Core utility functions provide common functionality:

- **`exists(x)`** - Checks if a value is not None [igfold/utils/general.py:49-50]()
- **`default(val, d)`** - Returns value if it exists, otherwise returns default [igfold/utils/general.py:53-57]()

**Sources:** [igfold/utils/general.py:1-57]()

### Utility Module Structure

```mermaid
graph TD
    subgraph "Utils Package Structure"
        UTILS_INIT["utils/__init__.py"]
        GENERAL["utils/general.py"]
        PDB_UTILS["utils/pdb_utils.py"]
        COORD_UTILS["utils/coord_utils.py"]
        GEOMETRY["utils/geometry.py"]
    end
    
    subgraph "Functional Areas"
        GENERAL --> CONSTANTS["Constants & Helpers"]
        PDB_UTILS --> PDB_IO["PDB File I/O"]
        COORD_UTILS --> COORDINATES["Coordinate Processing"]
        GEOMETRY --> TRANSFORMATIONS["Geometric Operations"]
    end
    
    subgraph "Usage Pattern"
        CONSTANTS --> ENCODING["Sequence Encoding"]
        PDB_IO --> STRUCTURE_IO["Structure File Handling"]
        COORDINATES --> COORD_CALC["Coordinate Calculations"]
        TRANSFORMATIONS --> GEOM_OPS["Geometric Transformations"]
    end
```

**Sources:** [igfold/utils/__init__.py:1](), [igfold/utils/general.py:1-57]()

## Common Functionality Patterns

### Data Type Conventions

IgFold follows consistent patterns for data representation and processing:

| Data Type | Representation | Usage |
|-----------|---------------|-------|
| Amino Acids | Single-letter codes | Primary sequence representation |
| Coordinates | NumPy arrays | 3D structure coordinates |
| Sequences | Dictionary format | Multi-chain sequence input |
| Templates | PDB format | Structure templates |

### Error Handling Utilities

The utility functions support robust error handling throughout the system:

```mermaid
graph LR
    subgraph "Error Handling Pattern"
        INPUT["Input Value"]
        EXISTS["exists() check"]
        DEFAULT["default() assignment"]
        RESULT["Safe Output"]
    end
    
    INPUT --> EXISTS
    EXISTS -->|"not None"| RESULT
    EXISTS -->|"None"| DEFAULT
    DEFAULT --> RESULT
```

**Sources:** [igfold/utils/general.py:49-57]()

## Development Setup Considerations

### Package Dependencies

The modular structure allows for flexible dependency management:

- **Core utilities** - Minimal dependencies for basic functionality
- **Refinement modules** - Optional heavy dependencies (OpenMM, PyRosetta)
- **Visualization** - Optional display dependencies (py3Dmol, matplotlib)

### Import Organization

The package structure supports clean imports and minimal coupling:

```mermaid
graph TD
    subgraph "Import Hierarchy"
        USER_CODE["User Code"]
        MAIN_API["igfold main API"]
        CORE_MODULES["Core modules"]
        UTILS["Utils modules"]
    end
    
    USER_CODE --> MAIN_API
    MAIN_API --> CORE_MODULES
    CORE_MODULES --> UTILS
    
    subgraph "Dependency Direction"
        UTILS --> EXTERNAL["External libraries"]
        CORE_MODULES --> MODELS["PyTorch models"]
        MAIN_API --> INTERFACES["User interfaces"]
    end
```

### Testing and Validation

The package structure supports systematic testing:
- **Unit tests** for utility functions
- **Integration tests** for module interfaces  
- **End-to-end tests** for complete workflows

**Sources:** [igfold/refine/__init__.py:1](), [igfold/utils/__init__.py:1](), [igfold/utils/general.py:1-57]()