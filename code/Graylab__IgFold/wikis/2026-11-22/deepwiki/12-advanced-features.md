# Advanced Features

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [igfold/__init__.py](igfold/__init__.py)
- [igfold/refine/openmm_ref.py](igfold/refine/openmm_ref.py)
- [igfold/refine/pyrosetta_ref.py](igfold/refine/pyrosetta_ref.py)

</details>



This page documents IgFold's advanced capabilities beyond basic structure prediction, including post-prediction refinement methods, specialized antibody analysis tools, and integration with external bioinformatics software. These features enable enhanced structure quality, domain-specific analysis, and customized workflows for specialized research applications.

For basic structure prediction workflows, see [Quick Start Guide](#3) and [User Guide](#4). For technical details on the core model architecture, see [Core Architecture](#5).

## Overview

IgFold provides several advanced features that extend beyond standard structure prediction:

- **Structure Refinement**: Post-prediction optimization using molecular dynamics and energy minimization
- **Antibody-Specific Tools**: Integration with specialized antibody analysis software
- **Advanced Analysis**: Enhanced metrics, validation, and visualization capabilities
- **External Tool Integration**: Seamless workflow integration with established bioinformatics tools

```mermaid
graph TD
    subgraph "Core Prediction"
        IGFOLD["IgFold.fold()"]
        COORDS["Raw Coordinates"]
    end
    
    subgraph "Structure Refinement"
        OPENMM_REF["openmm_ref.refine()"]
        PYROSETTA_REF["pyrosetta_ref.refine()"]
        MINIMIZATION["Energy Minimization"]
        CONSTRAINTS["Structural Constraints"]
    end
    
    subgraph "Antibody Analysis"
        ABNUMBER["AbNumber Integration"]
        CDR_ANALYSIS["CDR Identification"]
        RENUMBERING["Chain Renumbering"]
    end
    
    subgraph "Advanced Output"
        REFINED_PDB["Refined PDB Structures"]
        PRMSD_ANALYSIS["pRMSD Analysis"]
        VISUALIZATION["3D Visualization"]
        VALIDATION["Structure Validation"]
    end
    
    IGFOLD --> COORDS
    COORDS --> OPENMM_REF
    COORDS --> PYROSETTA_REF
    
    OPENMM_REF --> MINIMIZATION
    PYROSETTA_REF --> MINIMIZATION
    MINIMIZATION --> CONSTRAINTS
    
    COORDS --> ABNUMBER
    ABNUMBER --> CDR_ANALYSIS
    CDR_ANALYSIS --> RENUMBERING
    
    CONSTRAINTS --> REFINED_PDB
    RENUMBERING --> REFINED_PDB
    REFINED_PDB --> PRMSD_ANALYSIS
    REFINED_PDB --> VISUALIZATION
    REFINED_PDB --> VALIDATION
```

Sources: [igfold/refine/openmm_ref.py:1-44](), [igfold/refine/pyrosetta_ref.py:1-125](), [igfold/__init__.py:1-3]()

## Structure Refinement Pipeline

IgFold supports two primary refinement backends that can be applied after initial structure prediction to improve geometric quality and energy profiles.

### Refinement Workflow

```mermaid
flowchart TD
    INPUT_PDB["Input PDB Structure"]
    
    subgraph "OpenMM Refinement"
        PDBFIXER["pdbfixer.PDBFixer"]
        MISSING_ATOMS["findMissingAtoms()"]
        ADD_HYDROGENS["addHydrogens()"]
        FORCE_FIELD["amber14/protein.ff14SB.xml"]
        CUSTOM_FORCE["CustomExternalForce"]
        HARMONIC_CONSTRAINTS["Harmonic Constraints"]
        ENERGY_MIN["minimizeEnergy()"]
    end
    
    subgraph "PyRosetta Refinement"
        POSE_IMPORT["pose_from_pdbstring()"]
        COORD_CST["AtomCoordinateCstMover"]
        MIN_MOVER["get_min_mover()"]
        SCORE_FUNCTION["ref2015_cst"]
        REPACK_MOVER["get_repack_mover()"]
        IDEALIZE_MOVER["IdealizeMover"]
    end
    
    INPUT_PDB --> PDBFIXER
    INPUT_PDB --> POSE_IMPORT
    
    PDBFIXER --> MISSING_ATOMS
    MISSING_ATOMS --> ADD_HYDROGENS
    ADD_HYDROGENS --> FORCE_FIELD
    FORCE_FIELD --> CUSTOM_FORCE
    CUSTOM_FORCE --> HARMONIC_CONSTRAINTS
    HARMONIC_CONSTRAINTS --> ENERGY_MIN
    
    POSE_IMPORT --> COORD_CST
    COORD_CST --> MIN_MOVER
    MIN_MOVER --> SCORE_FUNCTION
    SCORE_FUNCTION --> REPACK_MOVER
    REPACK_MOVER --> IDEALIZE_MOVER
    
    ENERGY_MIN --> OUTPUT_PDB["Refined PDB Structure"]
    IDEALIZE_MOVER --> OUTPUT_PDB
```

Sources: [igfold/refine/openmm_ref.py:7-44](), [igfold/refine/pyrosetta_ref.py:92-125]()

### Refinement Configuration Options

Both refinement backends provide configurable parameters for customizing the refinement process:

| Backend | Key Parameters | Description |
|---------|----------------|-------------|
| OpenMM | `stiffness` | Harmonic constraint strength (default: 10.0) |
| OpenMM | `tolerance` | Energy minimization tolerance (default: 2.39) |
| OpenMM | `use_gpu` | Enable GPU acceleration (default: False) |
| PyRosetta | `minimization_iter` | Maximum minimization iterations (default: 100) |
| PyRosetta | `constrain` | Apply coordinate constraints (default: True) |
| PyRosetta | `idealize` | Apply geometry idealization (default: False) |

### PyRosetta Refinement Components

The PyRosetta refinement system uses several specialized movers and scoring functions:

```mermaid
graph TD
    subgraph "Scoring Functions"
        REF2015["ref2015_cst"]
        CART_BONDED["cart_bonded weight"]
        COORD_CST["coordinate_constraint"]
        DIHED_CST["dihedral_constraint"]
    end
    
    subgraph "Movement Configuration"
        MOVEMAP["MoveMap"]
        BB_MOVES["set_bb(True)"]
        CHI_MOVES["set_chi(False)"]
        JUMP_MOVES["set_jump(False)"]
    end
    
    subgraph "Refinement Movers"
        MIN_MOVER["MinMover"]
        RELAX_MOVER["FastRelax"]
        REPACK_MOVER["PackRotamersMover"]
        CST_MOVER["AtomCoordinateCstMover"]
    end
    
    REF2015 --> MIN_MOVER
    CART_BONDED --> MIN_MOVER
    COORD_CST --> MIN_MOVER
    DIHED_CST --> MIN_MOVER
    
    MOVEMAP --> MIN_MOVER
    BB_MOVES --> MOVEMAP
    CHI_MOVES --> MOVEMAP
    JUMP_MOVES --> MOVEMAP
    
    MIN_MOVER --> CST_MOVER
    RELAX_MOVER --> REPACK_MOVER
```

Sources: [igfold/refine/pyrosetta_ref.py:12-54](), [igfold/refine/pyrosetta_ref.py:57-89]()

## External Tool Integration

IgFold integrates with several external bioinformatics tools to provide specialized antibody analysis capabilities and enhanced structure processing.

### Integration Architecture

```mermaid
graph LR
    subgraph "IgFold Core"
        RUNNER["IgFoldRunner"]
        FOLD_METHOD["fold()"]
        EMBED_METHOD["embed()"]
    end
    
    subgraph "Structure Processing"
        PDBFIXER_LIB["pdbfixer"]
        OPENMM_LIB["openmm"]
        PYROSETTA_LIB["pyrosetta"]
        BIOPYTHON["Bio.PDB"]
    end
    
    subgraph "Antibody Tools"
        ANTIBERTY["AntiBERTy"]
        ABNUMBER["AbNumber"]
        CDR_TOOLS["CDR Analysis"]
    end
    
    subgraph "Visualization"
        PY3DMOL["py3Dmol"]
        MATPLOTLIB["matplotlib"]
        VISUALIZATION_TOOLS["3D Structure Viewer"]
    end
    
    RUNNER --> FOLD_METHOD
    RUNNER --> EMBED_METHOD
    
    FOLD_METHOD --> PDBFIXER_LIB
    FOLD_METHOD --> OPENMM_LIB
    FOLD_METHOD --> PYROSETTA_LIB
    FOLD_METHOD --> BIOPYTHON
    
    EMBED_METHOD --> ANTIBERTY
    FOLD_METHOD --> ABNUMBER
    ABNUMBER --> CDR_TOOLS
    
    FOLD_METHOD --> PY3DMOL
    FOLD_METHOD --> MATPLOTLIB
    PY3DMOL --> VISUALIZATION_TOOLS
```

Sources: [igfold/refine/openmm_ref.py:1-3](), [igfold/refine/pyrosetta_ref.py:1-1]()

## Advanced Configuration

Advanced users can customize IgFold's behavior through various configuration options and programmatic interfaces.

### Refinement Method Selection

The refinement backend can be selected and configured through the main API:

- **OpenMM Backend**: Molecular dynamics-based refinement with GPU acceleration support
- **PyRosetta Backend**: Rosetta-based refinement with advanced scoring functions
- **No Refinement**: Direct output of predicted coordinates

### Scoring and Constraint Configuration

PyRosetta refinement allows fine-tuning of scoring function weights:

| Score Term | Default Weight | Purpose |
|------------|----------------|---------|
| `cart_bonded` | 1.0 | Cartesian bonded geometry |
| `pro_close` | 0.0 | Proline closure (disabled) |
| `coordinate_constraint` | 1.0 | Position constraints |
| `dihedral_constraint` | 1.0 | Dihedral angle constraints |

### Minimization Parameters

Both backends support customizable minimization settings:

- **Iteration Limits**: Control computational cost vs. convergence
- **Constraint Strengths**: Balance refinement vs. structure preservation
- **Move Maps**: Specify which degrees of freedom to optimize

For detailed information on structure refinement methods, see [Structure Refinement](#6.1). For antibody-specific analysis tools and integrations, see [Antibody-Specific Tools](#6.2).

Sources: [igfold/refine/pyrosetta_ref.py:12-54](), [igfold/refine/openmm_ref.py:7-44]()

---