# Enhanced Sampling with PLUMED

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [python/BioSimSpace/Metadynamics/CollectiveVariable/_funnel.py](python/BioSimSpace/Metadynamics/CollectiveVariable/_funnel.py)
- [python/BioSimSpace/Metadynamics/CollectiveVariable/_rmsd.py](python/BioSimSpace/Metadynamics/CollectiveVariable/_rmsd.py)
- [python/BioSimSpace/Process/_plumed.py](python/BioSimSpace/Process/_plumed.py)
- [python/BioSimSpace/Protocol/_metadynamics.py](python/BioSimSpace/Protocol/_metadynamics.py)
- [python/BioSimSpace/Sandpit/Exscientia/Metadynamics/CollectiveVariable/_funnel.py](python/BioSimSpace/Sandpit/Exscientia/Metadynamics/CollectiveVariable/_funnel.py)
- [python/BioSimSpace/Sandpit/Exscientia/Metadynamics/CollectiveVariable/_rmsd.py](python/BioSimSpace/Sandpit/Exscientia/Metadynamics/CollectiveVariable/_rmsd.py)
- [python/BioSimSpace/Sandpit/Exscientia/Metadynamics/_restraint.py](python/BioSimSpace/Sandpit/Exscientia/Metadynamics/_restraint.py)
- [python/BioSimSpace/Sandpit/Exscientia/Process/_plumed.py](python/BioSimSpace/Sandpit/Exscientia/Process/_plumed.py)
- [tests/Metadynamics/test_metadynamics.py](tests/Metadynamics/test_metadynamics.py)

</details>



This page documents BioSimSpace's integration with PLUMED for enhanced sampling simulations, including metadynamics and steered molecular dynamics. It covers the `Plumed` utility class, collective variable configuration, and the workflow for generating PLUMED input files from BioSimSpace protocols.

For information about defining metadynamics protocols, see [Simulation Protocols](#4.1). For details about free energy calculations using metadynamics, see [Relative Free Energy Perturbation](#5.1).

## PLUMED Integration Architecture

BioSimSpace provides a unified interface to PLUMED through the `Plumed` utility class, which translates BioSimSpace protocols and collective variables into PLUMED configuration files. This enables enhanced sampling simulations across multiple MD engines.

```mermaid
graph TB
    subgraph "BioSimSpace Protocol Layer"
        METAD["Metadynamics Protocol"]
        STEER["Steering Protocol"]
        CV["CollectiveVariable Classes"]
    end
    
    subgraph "PLUMED Interface Layer"
        PLUMED_CLASS["Plumed Class"]
        CONFIG_GEN["createConfig()"]
        METAD_CONFIG["_createMetadynamicsConfig()"]
        STEER_CONFIG["_createSteeringConfig()"]
    end
    
    subgraph "Collective Variable Types"
        DISTANCE["Distance CV"]
        TORSION["Torsion CV"]
        RMSD["RMSD CV"]
        FUNNEL["Funnel CV"]
    end
    
    subgraph "PLUMED Output"
        PLUMED_CONF["plumed.dat"]
        AUX_FILES["Auxiliary Files"]
        REF_PDB["Reference PDB"]
    end
    
    subgraph "MD Engine Integration"
        GROMACS["GROMACS Process"]
        OPENMM["OpenMM Process"]
        SOMD["SOMD Process"]
    end
    
    METAD --> CONFIG_GEN
    STEER --> CONFIG_GEN
    CV --> CONFIG_GEN
    
    CONFIG_GEN --> METAD_CONFIG
    CONFIG_GEN --> STEER_CONFIG
    
    DISTANCE --> METAD_CONFIG
    TORSION --> METAD_CONFIG
    RMSD --> METAD_CONFIG
    FUNNEL --> METAD_CONFIG
    
    METAD_CONFIG --> PLUMED_CONF
    STEER_CONFIG --> PLUMED_CONF
    METAD_CONFIG --> AUX_FILES
    RMSD --> REF_PDB
    
    PLUMED_CONF --> GROMACS
    PLUMED_CONF --> OPENMM
    PLUMED_CONF --> SOMD
    
    style PLUMED_CLASS fill:#e1f5fe
    style CONFIG_GEN fill:#fff3e0
    style PLUMED_CONF fill:#e8f5e8
```

Sources: [python/BioSimSpace/Process/_plumed.py:59-156](), [python/BioSimSpace/Process/_plumed.py:157-201]()

## The Plumed Class

The `Plumed` class serves as the central interface for PLUMED integration, handling version checking, configuration file generation, and auxiliary file management.

### Core Functionality

| Method | Purpose | Input | Output |
|--------|---------|-------|--------|
| `__init__(work_dir)` | Initialize PLUMED interface | Working directory path | Configured `Plumed` instance |
| `createConfig()` | Generate PLUMED configuration | System, Protocol, property_map | Config strings, auxiliary files |
| `_createMetadynamicsConfig()` | Generate metadynamics config | System, Metadynamics protocol | PLUMED metadynamics setup |
| `_createSteeringConfig()` | Generate steering config | System, Steering protocol | PLUMED steering setup |

### Version Management and Validation

The `Plumed` class performs automatic version detection and validation during initialization:

```mermaid
graph LR
    INIT["Plumed.__init__()"] --> FIND_EXE["findExe('plumed')"]
    FIND_EXE --> VERSION_CHECK["Query version via subprocess"]
    VERSION_CHECK --> VALIDATE["Validate version >= 2.5"]
    VALIDATE --> READY["Ready for configuration"]
    
    FIND_EXE -->|"Not found"| ERROR1["MissingSoftwareError"]
    VERSION_CHECK -->|"Failed"| ERROR2["IncompatibleError"]
    VALIDATE -->|"< 2.5"| ERROR3["IncompatibleError"]
```

Sources: [python/BioSimSpace/Process/_plumed.py:81-114]()

## Collective Variable Configuration

The `Plumed` class supports multiple collective variable types, each with specific configuration requirements and PLUMED syntax generation.

### Collective Variable Type Mapping

```mermaid
graph TB
    subgraph "CollectiveVariable Types"
        DISTANCE_CV["Distance CV<br/>atom0, atom1<br/>weights, CoM"]
        TORSION_CV["Torsion CV<br/>4 atoms<br/>periodic bounds"]
        RMSD_CV["RMSD CV<br/>reference system<br/>align/rmsd selections"]
        FUNNEL_CV["Funnel CV<br/>atoms0, atoms1<br/>funnel parameters"]
    end
    
    subgraph "PLUMED Directives"
        DISTANCE_DIR["DISTANCE ATOMS="]
        TORSION_DIR["TORSION ATOMS="]
        RMSD_DIR["RMSD REFERENCE="]
        FUNNEL_DIR["PROJECTION_ON_AXIS<br/>MATHEVAL funnel"]
    end
    
    subgraph "Supporting Elements"
        CENTER["CENTER (for groups)"]
        WHOLEMOL["WHOLEMOLECULES"]
        WALLS["UPPER_WALLS/LOWER_WALLS"]
        GRID["GRID parameters"]
    end
    
    DISTANCE_CV --> DISTANCE_DIR
    TORSION_CV --> TORSION_DIR
    RMSD_CV --> RMSD_DIR
    FUNNEL_CV --> FUNNEL_DIR
    
    DISTANCE_CV --> CENTER
    RMSD_CV --> WHOLEMOL
    DISTANCE_CV --> WALLS
    FUNNEL_CV --> GRID
    
    style DISTANCE_CV fill:#e1f5fe
    style TORSION_CV fill:#e1f5fe
    style RMSD_CV fill:#e1f5fe
    style FUNNEL_CV fill:#e1f5fe
```

Sources: [python/BioSimSpace/Process/_plumed.py:476-661](), [python/BioSimSpace/Process/_plumed.py:662-752]()

### Distance Collective Variable Processing

Distance collective variables support various atom specifications and center-of-mass calculations:

- **Single atoms**: Direct atom index specification
- **Atom groups**: Automatic `CENTER` directive generation with optional weighting
- **Fixed coordinates**: `FIXEDATOM` directive for static reference points
- **Periodic boundaries**: Optional `NOPBC` flag
- **Components**: X, Y, Z distance components via `COMPONENT` flag

Sources: [python/BioSimSpace/Process/_plumed.py:476-600]()

### RMSD Collective Variable Processing

RMSD collective variables require reference structure generation and atom mapping:

1. **Reference PDB generation**: Creates formatted PDB files with proper atom indexing
2. **Atom selection mapping**: Processes Sire selection strings for alignment and RMSD atoms
3. **Molecule entity creation**: Generates `WHOLEMOLECULES` directives for involved molecules
4. **Alignment type specification**: Supports "optimal" and "simple" alignment methods

Sources: [python/BioSimSpace/Metadynamics/CollectiveVariable/_rmsd.py:337-347](), [python/BioSimSpace/Process/_plumed.py:629-660]()

### Funnel Collective Variable Processing

Funnel collective variables implement complex restraint geometries for binding free energy calculations:

```mermaid
graph TD
    FUNNEL_SETUP["Funnel CV Setup"] --> BOX_CHECK["Validate box size"]
    BOX_CHECK --> MOL_DETECT["Detect protein/ligand"]
    MOL_DETECT --> COM_DEF["Define COM groups"]
    COM_DEF --> PROJ_AXIS["PROJECTION_ON_AXIS"]
    PROJ_AXIS --> FUNNEL_CALC["MATHEVAL funnel calculation"]
    FUNNEL_CALC --> BIAS_POTENTIAL["BIASVALUE potential"]
    
    BOX_CHECK -->|"Too small"| ERROR["IncompatibleError"]
    
    subgraph "PLUMED Directives Generated"
        COM_DIR["lig: COM ATOMS="]
        P1_DIR["p1: COM ATOMS="]
        P2_DIR["p2: COM ATOMS="]
        PP_DIR["pp: PROJECTION_ON_AXIS"]
        MATH_DIR["MATHEVAL wall calculation"]
        BIAS_DIR["finalbias: BIASVALUE"]
    end
    
    COM_DEF --> COM_DIR
    COM_DEF --> P1_DIR
    COM_DEF --> P2_DIR
    PROJ_AXIS --> PP_DIR
    FUNNEL_CALC --> MATH_DIR
    BIAS_POTENTIAL --> BIAS_DIR
```

Sources: [python/BioSimSpace/Process/_plumed.py:662-750](), [python/BioSimSpace/Metadynamics/CollectiveVariable/_funnel.py:711-753]()

## Configuration Generation Workflow

The configuration generation process follows a systematic workflow that handles molecule entity detection, collective variable processing, and protocol-specific setup.

### Metadynamics Configuration Workflow

```mermaid
flowchart TD
    START["createConfig()"] --> VALIDATE["Validate inputs"]
    VALIDATE --> CLEAR["Clear previous data"]
    CLEAR --> RESTART_CHECK["Check for restart files"]
    RESTART_CHECK --> MOL_ENTITIES["Generate WHOLEMOLECULES"]
    
    MOL_ENTITIES --> CV_LOOP["Process each CollectiveVariable"]
    CV_LOOP --> CV_CONFIG["Generate CV directives"]
    CV_CONFIG --> BOUNDS["Add wall restraints"]
    BOUNDS --> GRID_CONFIG["Configure grid parameters"]
    
    GRID_CONFIG --> METAD_SETUP["Generate METAD directive"]
    METAD_SETUP --> PRINT_SETUP["Add PRINT directive"]
    PRINT_SETUP --> RETURN["Return config + aux files"]
    
    subgraph "CollectiveVariable Processing"
        CV_CONFIG --> DISTANCE_PROC["Process Distance"]
        CV_CONFIG --> TORSION_PROC["Process Torsion"]
        CV_CONFIG --> RMSD_PROC["Process RMSD"]
        CV_CONFIG --> FUNNEL_PROC["Process Funnel"]
    end
    
    RESTART_CHECK -->|"Files exist"| RESTART_YES["RESTART"]
    RESTART_CHECK -->|"No files"| RESTART_NO["RESTART NO"]
```

Sources: [python/BioSimSpace/Process/_plumed.py:242-907]()

### Key Configuration Elements

| Configuration Section | Purpose | Example Directives |
|----------------------|---------|-------------------|
| **Restart handling** | Resume from existing simulation | `RESTART` / `RESTART NO` |
| **Molecule entities** | Define whole molecule units | `WHOLEMOLECULES ENTITY0=1-100` |
| **Collective variables** | Define CVs and their parameters | `d1: DISTANCE ATOMS=1,10` |
| **Wall restraints** | Apply bounds to CV values | `UPPER_WALLS ARG=d1 AT=2.0` |
| **Metadynamics setup** | Configure hill deposition | `METAD ARG=d1 SIGMA=0.1 HEIGHT=1.0` |
| **Output control** | Specify data recording | `PRINT STRIDE=1000 ARG=* FILE=COLVAR` |

Sources: [python/BioSimSpace/Process/_plumed.py:261-267](), [python/BioSimSpace/Process/_plumed.py:435-451](), [python/BioSimSpace/Process/_plumed.py:839-902]()

## Engine Integration

PLUMED configurations are integrated into MD engine processes through engine-specific mechanisms:

### Process Integration Points

```mermaid
graph LR
    subgraph "MD Engine Processes"
        GROMACS_PROC["Gromacs Process"]
        OPENMM_PROC["OpenMM Process"]
        SOMD_PROC["SOMD Process"]
    end
    
    subgraph "PLUMED Integration"
        PLUMED_CONFIG["plumed.dat"]
        AUX_FILES["Auxiliary files"]
        REF_FILES["Reference PDB files"]
    end
    
    subgraph "Engine-Specific Setup"
        GMX_ARGS["-plumed plumed.dat"]
        OMM_PLUGIN["OpenMM PLUMED plugin"]
        SOMD_CONFIG["SOMD config integration"]
    end
    
    PLUMED_CONFIG --> GMX_ARGS
    PLUMED_CONFIG --> OMM_PLUGIN
    PLUMED_CONFIG --> SOMD_CONFIG
    
    AUX_FILES --> GROMACS_PROC
    REF_FILES --> GROMACS_PROC
    
    GMX_ARGS --> GROMACS_PROC
    OMM_PLUGIN --> OPENMM_PROC
    SOMD_CONFIG --> SOMD_PROC
```

### File Management

The `Plumed` class manages multiple file types required for enhanced sampling simulations:

- **Configuration files**: Main `plumed.dat` with all directives
- **Auxiliary files**: Engine-specific code for custom collective variables
- **Reference structures**: PDB files for RMSD calculations
- **Restart files**: `HILLS` and `COLVAR` files for simulation continuation

Sources: [python/BioSimSpace/Process/_plumed.py:139-141](), [python/BioSimSpace/Process/_plumed.py:386-399]()

## Error Handling and Validation

The PLUMED integration includes comprehensive validation and error handling:

### Validation Checks

| Check Type | Location | Error Type |
|------------|----------|------------|
| **PLUMED availability** | `__init__()` | `MissingSoftwareError` |
| **Version compatibility** | `__init__()` | `IncompatibleError` |
| **Atom index bounds** | CV processing | `IncompatibleError` |
| **Box size constraints** | Funnel CV | `IncompatibleError` |
| **CV consistency** | Protocol validation | `ValueError` |

Sources: [python/BioSimSpace/Process/_plumed.py:85-87](), [python/BioSimSpace/Process/_plumed.py:104-107](), [python/BioSimSpace/Process/_plumed.py:414-419]()

---