# Free Energy Calculations

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.github/workflows/Sandpit_exs.yml](.github/workflows/Sandpit_exs.yml)
- [doc/source/api/index_FreeEnergy.rst](doc/source/api/index_FreeEnergy.rst)
- [python/BioSimSpace/FreeEnergy/_atm.py](python/BioSimSpace/FreeEnergy/_atm.py)
- [python/BioSimSpace/FreeEnergy/_ddg.py](python/BioSimSpace/FreeEnergy/_ddg.py)
- [python/BioSimSpace/FreeEnergy/_relative.py](python/BioSimSpace/FreeEnergy/_relative.py)
- [python/BioSimSpace/Process/_atm.py](python/BioSimSpace/Process/_atm.py)
- [python/BioSimSpace/Process/_atm_utils.py](python/BioSimSpace/Process/_atm_utils.py)
- [python/BioSimSpace/Protocol/_atm.py](python/BioSimSpace/Protocol/_atm.py)
- [python/BioSimSpace/Sandpit/Exscientia/Align/_squash.py](python/BioSimSpace/Sandpit/Exscientia/Align/_squash.py)
- [python/BioSimSpace/Sandpit/Exscientia/Protocol/_config.py](python/BioSimSpace/Sandpit/Exscientia/Protocol/_config.py)
- [tests/FreeEnergy/test_atm.py](tests/FreeEnergy/test_atm.py)
- [tests/Process/test_atm.py](tests/Process/test_atm.py)
- [tests/conftest.py](tests/conftest.py)

</details>



This document covers BioSimSpace's free energy calculation capabilities, including relative free energy perturbation (FEP), the Alchemical Transfer Method (ATM), and associated analysis tools. The system supports multiple molecular dynamics engines and statistical estimators for computing binding and solvation free energies.

For information about system preparation and molecular alignment required for free energy calculations, see [Alignment and Merging](#3.3). For protocol configuration details, see [Simulation Protocols](#4.1).

## Overview

BioSimSpace provides two main approaches for free energy calculations:

- **Relative Free Energy Perturbation (FEP)**: Traditional lambda-window approach using perturbable molecules
- **Alchemical Transfer Method (ATM)**: Single-simulation approach with both ligands present simultaneously

Both methods support multiple analysis techniques including MBAR, TI, and UWHAM estimators, with integration across various MD engines.

## System Architecture

```mermaid
graph TB
    subgraph "Free Energy Methods"
        REL["Relative<br/>(_relative.py)"]
        ATM_SETUP["ATMSetup<br/>(_atm.py)"]
        ATM_EXEC["ATM<br/>(_atm.py)"]
    end
    
    subgraph "Protocol Layer"
        FE_PROT["FreeEnergy Protocols<br/>FreeEnergyProduction<br/>FreeEnergyEquilibration"]
        ATM_PROT["ATM Protocols<br/>ATMProduction<br/>ATMEquilibration<br/>ATMAnnealing"]
    end
    
    subgraph "Execution Engines"
        GROMACS["GROMACS Process"]
        AMBER["AMBER Process"]
        OPENMM["OpenMM Process"]
        SOMD["SOMD Process"]
    end
    
    subgraph "Analysis Pipeline"
        EXTRACT["Data Extraction<br/>_somd_extract<br/>_gmx_extract<br/>_amber_extract"]
        ESTIMATORS["Statistical Estimators<br/>analyse_MBAR<br/>analyse_UWHAM<br/>AutoMBAR, TI"]
        RESULTS["Free Energy Results<br/>difference()<br/>checkOverlap()"]
    end
    
    REL --> FE_PROT
    ATM_SETUP --> ATM_EXEC
    ATM_EXEC --> ATM_PROT
    
    FE_PROT --> GROMACS
    FE_PROT --> AMBER
    FE_PROT --> SOMD
    ATM_PROT --> OPENMM
    
    GROMACS --> EXTRACT
    AMBER --> EXTRACT
    SOMD --> EXTRACT
    OPENMM --> EXTRACT
    
    EXTRACT --> ESTIMATORS
    ESTIMATORS --> RESULTS
    
    style REL fill:#e8f5e8
    style ATM_SETUP fill:#e8f5e8
    style ESTIMATORS fill:#fff3e0
```

**Free Energy Calculation System Architecture**

Sources: [python/BioSimSpace/FreeEnergy/_relative.py:122-293](), [python/BioSimSpace/FreeEnergy/_atm.py:55-133](), [python/BioSimSpace/FreeEnergy/_ddg.py:26-355]()

## Relative Free Energy Perturbation

The `Relative` class implements traditional lambda-window free energy perturbation using perturbable molecules created through molecular alignment and merging.

```mermaid
graph LR
    subgraph "System Preparation"
        PERT_SYS["Perturbable System<br/>merged molecules"]
        PROTOCOL["FreeEnergy Protocol<br/>lambda windows"]
    end
    
    subgraph "Relative Class Methods"
        CONSTRUCTOR["Relative.__init__()<br/>system validation<br/>engine selection"]
        RUN_METHOD["run(serial=True)<br/>ProcessRunner.startAll()"]
        ANALYSE_METHOD["analyse(estimator)<br/>_analyse_somd<br/>_analyse_gromacs"]
    end
    
    subgraph "Engine Support"
        ENGINES["Supported Engines<br/>AMBER, GROMACS, SOMD"]
        RUNNER["ProcessRunner<br/>lambda window management"]
    end
    
    subgraph "Analysis Output"
        PMF["PMF Data<br/>[(lambda, energy, error)]"]
        OVERLAP["Overlap Matrix<br/>window validation"]
        DIFFERENCE["Free Energy Difference<br/>difference() method"]
    end
    
    PERT_SYS --> CONSTRUCTOR
    PROTOCOL --> CONSTRUCTOR
    CONSTRUCTOR --> RUN_METHOD
    RUN_METHOD --> ENGINES
    ENGINES --> RUNNER
    RUNNER --> ANALYSE_METHOD
    ANALYSE_METHOD --> PMF
    ANALYSE_METHOD --> OVERLAP
    PMF --> DIFFERENCE
```

**Relative FEP Workflow and Code Structure**

| Method | Purpose | Supported Engines |
|--------|---------|-------------------|
| `Relative.__init__()` | Initialize FEP calculation | AMBER, GROMACS, SOMD |
| `run()` | Execute lambda windows | All supported |
| `analyse()` | Extract and analyze data | Engine-specific parsers |
| `difference()` | Compute ΔΔG | Statistical combination |

Sources: [python/BioSimSpace/FreeEnergy/_relative.py:131-293](), [python/BioSimSpace/FreeEnergy/_relative.py:295-336](), [python/BioSimSpace/FreeEnergy/_relative.py:432-511]()

## Alchemical Transfer Method (ATM)

The ATM implementation provides an alternative approach where both ligands exist simultaneously in the simulation, eliminating the need for separate "legs".

```mermaid
graph TD
    subgraph "ATM System Setup"
        SETUP_INIT["ATMSetup.__init__()<br/>receptor + ligands"]
        PREPARE["prepare()<br/>rigid_core definition<br/>displacement calculation"]
        ATM_SYSTEM["ATM System<br/>protein + both ligands<br/>encoded atom_data"]
    end
    
    subgraph "ATM Protocols"
        ATM_MIN["ATMMinimisation<br/>_ATM base class"]
        ATM_EQUIL["ATMEquilibration<br/>lambda1, lambda2 params"]
        ATM_ANNEAL["ATMAnnealing<br/>annealing schedules"]
        ATM_PROD["ATMProduction<br/>lambda windows<br/>analysis_method"]
    end
    
    subgraph "OpenMM Execution"
        OPENMM_ATM["OpenMMATM<br/>_generate_config()"]
        ATM_UTILS["_ATMUtils<br/>createATMForce()<br/>createAlignmentForce()"]
        FORCES["Custom Forces<br/>ATMForce<br/>AlignmentForce<br/>COMRestraint"]
    end
    
    subgraph "ATM Analysis"
        UWHAM["analyse_UWHAM<br/>_estimate_f_i()"]
        MBAR_ATM["analyse_MBAR<br/>forward/reverse legs"]
        DDG_RESULT["ΔΔG ± error<br/>single value"]
    end
    
    SETUP_INIT --> PREPARE
    PREPARE --> ATM_SYSTEM
    ATM_SYSTEM --> ATM_MIN
    ATM_SYSTEM --> ATM_EQUIL
    ATM_SYSTEM --> ATM_ANNEAL
    ATM_SYSTEM --> ATM_PROD
    
    ATM_MIN --> OPENMM_ATM
    ATM_EQUIL --> OPENMM_ATM
    ATM_ANNEAL --> OPENMM_ATM
    ATM_PROD --> OPENMM_ATM
    
    OPENMM_ATM --> ATM_UTILS
    ATM_UTILS --> FORCES
    
    FORCES --> UWHAM
    FORCES --> MBAR_ATM
    UWHAM --> DDG_RESULT
    MBAR_ATM --> DDG_RESULT
```

**ATM Method Implementation and Workflow**

The ATM system requires specific setup parameters:

| Parameter | Purpose | Code Reference |
|-----------|---------|----------------|
| `ligand_bound_rigid_core` | Define alignment atoms for bound ligand | `_setLigandBoundRigidCore()` |
| `ligand_free_rigid_core` | Define alignment atoms for free ligand | `_setLigandFreeRigidCore()` |
| `displacement` | Distance between ligand centers | `_setDisplacement()` |
| `com_distance_restraint` | Enable center-of-mass restraints | `setCOMDistanceRestraint()` |

Sources: [python/BioSimSpace/FreeEnergy/_atm.py:60-133](), [python/BioSimSpace/FreeEnergy/_atm.py:464-566](), [python/BioSimSpace/Protocol/_atm.py:39-132](), [python/BioSimSpace/Process/_atm.py:32-82]()

## Analysis Pipeline

BioSimSpace supports multiple statistical estimators for free energy analysis, with engine-specific data extraction and preprocessing.

```mermaid
graph LR
    subgraph "Data Sources"
        SOMD_OUT["SOMD Output<br/>simfile.dat<br/>gradients.dat"]
        GMX_OUT["GROMACS Output<br/>*.xvg files<br/>dhdl data"]
        AMBER_OUT["AMBER Output<br/>*.out files<br/>mbar energies"]
        SOMD2_OUT["SOMD2 Output<br/>*.parquet files"]
    end
    
    subgraph "Data Extraction"
        SOMD_EXTRACT["_somd_extract()<br/>u_nk, dH/dl parsing"]
        GMX_EXTRACT["_gmx_extract_u_nk<br/>_gmx_extract_dHdl"]
        AMBER_EXTRACT["_amber_extract_u_nk<br/>_amber_extract_dHdl"]
        SOMD2_EXTRACT["_somd2_extract()<br/>parquet processing"]
    end
    
    subgraph "Statistical Analysis"
        MBAR["AutoMBAR<br/>alchemlyb.estimators"]
        TI["TI Estimator<br/>thermodynamic integration"]
        UWHAM["UWHAM<br/>_estimate_f_i()"]
        NATIVE["Native Analysis<br/>analyse_freenrg script"]
    end
    
    subgraph "Results Processing"
        PMF_DATA["PMF Generation<br/>lambda vs ΔG"]
        OVERLAP_CHECK["checkOverlap()<br/>validation"]
        DIFFERENCE_CALC["difference()<br/>error propagation"]
    end
    
    SOMD_OUT --> SOMD_EXTRACT
    GMX_OUT --> GMX_EXTRACT  
    AMBER_OUT --> AMBER_EXTRACT
    SOMD2_OUT --> SOMD2_EXTRACT
    
    SOMD_EXTRACT --> MBAR
    SOMD_EXTRACT --> TI
    SOMD_EXTRACT --> NATIVE
    GMX_EXTRACT --> MBAR
    GMX_EXTRACT --> TI
    GMX_EXTRACT --> NATIVE
    AMBER_EXTRACT --> MBAR
    AMBER_EXTRACT --> TI
    SOMD2_EXTRACT --> MBAR
    SOMD2_EXTRACT --> TI
    
    MBAR --> PMF_DATA
    TI --> PMF_DATA
    UWHAM --> PMF_DATA
    NATIVE --> PMF_DATA
    
    PMF_DATA --> OVERLAP_CHECK
    PMF_DATA --> DIFFERENCE_CALC
```

**Analysis Pipeline Architecture**

### Supported Analysis Methods

| Method | Estimator | Engine Support | Implementation |
|--------|-----------|----------------|----------------|
| MBAR | `AutoMBAR` | All engines | `alchemlyb.estimators.AutoMBAR` |
| TI | `TI` | All engines | `alchemlyb.estimators.TI` |
| UWHAM | Custom | OpenMM (ATM) | `_estimate_f_i()` |
| Native | Engine-specific | GROMACS, SOMD | `analyse_freenrg` script |

### Data Preprocessing

The analysis pipeline includes automated preprocessing steps:
- Equilibrium detection using `_equilibrium_detection()`
- Statistical inefficiency removal with `_statistical_inefficiency()`
- Data slicing and decorrelation via `decorrelate_u_nk()` and `decorrelate_dhdl()`

Sources: [python/BioSimSpace/FreeEnergy/_relative.py:432-511](), [python/BioSimSpace/FreeEnergy/_relative.py:676-800](), [python/BioSimSpace/FreeEnergy/_ddg.py:94-149](), [python/BioSimSpace/FreeEnergy/_ddg.py:202-355]()

## Engine Integration

BioSimSpace provides a unified interface across multiple MD engines, with engine-specific configuration generation and output parsing.

### Engine Support Matrix

| Engine | Relative FEP | ATM | Analysis Methods | Configuration |
|--------|-------------|-----|------------------|---------------|
| AMBER | ✓ | ✗ | MBAR, TI | `generateAmberConfig()` |
| GROMACS | ✓ | ✗ | MBAR, TI, Native | `generateGromacsConfig()` |
| OpenMM | ✓ | ✓ | MBAR, TI, UWHAM | Custom Python scripts |
| SOMD | ✓ | ✗ | MBAR, Native | SOMD configuration |
| SOMD2 | ✗ | ✗ | MBAR, TI | Parquet output |

### Configuration Generation

Each engine requires specific configuration file generation:
- **AMBER**: Uses `timask1`, `timask2`, `scmask1`, `scmask2` for perturbation masks
- **GROMACS**: Implements `free-energy` parameters with lambda coupling
- **OpenMM**: Custom force generation through `_ATMUtils` for ATM simulations

Sources: [python/BioSimSpace/FreeEnergy/_relative.py:125-129](), [python/BioSimSpace/Sandpit/Exscientia/Protocol/_config.py:104-163](), [python/BioSimSpace/Process/_atm.py:71-82](), [python/BioSimSpace/Process/_atm_utils.py:80-105]()

---