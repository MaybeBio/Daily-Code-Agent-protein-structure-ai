# Sandpit and Experimental Features

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [python/BioSimSpace/Sandpit/Exscientia/Align/_alch_ion.py](python/BioSimSpace/Sandpit/Exscientia/Align/_alch_ion.py)
- [python/BioSimSpace/Sandpit/Exscientia/Align/_decouple.py](python/BioSimSpace/Sandpit/Exscientia/Align/_decouple.py)
- [python/BioSimSpace/Sandpit/Exscientia/FreeEnergy/_restraint.py](python/BioSimSpace/Sandpit/Exscientia/FreeEnergy/_restraint.py)
- [python/BioSimSpace/Sandpit/Exscientia/FreeEnergy/_restraint_search.py](python/BioSimSpace/Sandpit/Exscientia/FreeEnergy/_restraint_search.py)
- [python/BioSimSpace/Sandpit/Exscientia/Process/_amber.py](python/BioSimSpace/Sandpit/Exscientia/Process/_amber.py)
- [python/BioSimSpace/Sandpit/Exscientia/Process/_gromacs.py](python/BioSimSpace/Sandpit/Exscientia/Process/_gromacs.py)
- [python/BioSimSpace/Sandpit/Exscientia/Process/_process.py](python/BioSimSpace/Sandpit/Exscientia/Process/_process.py)
- [python/BioSimSpace/Sandpit/Exscientia/Process/_somd.py](python/BioSimSpace/Sandpit/Exscientia/Process/_somd.py)
- [python/BioSimSpace/Sandpit/Exscientia/Units/Volume/__init__.py](python/BioSimSpace/Sandpit/Exscientia/Units/Volume/__init__.py)
- [tests/Sandpit/Exscientia/Align/test_alchemical_ion.py](tests/Sandpit/Exscientia/Align/test_alchemical_ion.py)
- [tests/Sandpit/Exscientia/FreeEnergy/test_restraint.py](tests/Sandpit/Exscientia/FreeEnergy/test_restraint.py)
- [tests/Sandpit/Exscientia/FreeEnergy/test_restraint_search.py](tests/Sandpit/Exscientia/FreeEnergy/test_restraint_search.py)
- [tests/Sandpit/Exscientia/Process/test_amber.py](tests/Sandpit/Exscientia/Process/test_amber.py)
- [tests/Sandpit/Exscientia/Process/test_gromacs.py](tests/Sandpit/Exscientia/Process/test_gromacs.py)
- [tests/Sandpit/Exscientia/Process/test_position_restraint.py](tests/Sandpit/Exscientia/Process/test_position_restraint.py)
- [tests/Sandpit/Exscientia/Process/test_restart.py](tests/Sandpit/Exscientia/Process/test_restart.py)
- [tests/Sandpit/Exscientia/Protocol/test_config.py](tests/Sandpit/Exscientia/Protocol/test_config.py)
- [tests/Sandpit/Exscientia/output/amber_fep.out](tests/Sandpit/Exscientia/output/amber_fep.out)
- [tests/Sandpit/Exscientia/output/amber_fep_min.out](tests/Sandpit/Exscientia/output/amber_fep_min.out)

</details>



The Sandpit represents BioSimSpace's experimental development branch, specifically the `BioSimSpace.Sandpit.Exscientia` namespace, which contains cutting-edge features that are being developed and tested before potential integration into the main BioSimSpace package. These features provide enhanced capabilities for advanced molecular dynamics simulations, particularly focused on free energy calculations, restraint selection, and specialized simulation protocols.

This document covers the experimental features available in the Sandpit branch. For information about stable simulation execution, see [Simulation Execution](#4). For established free energy calculation methods, see [Free Energy Calculations](#5).

## Sandpit Architecture Overview

The Sandpit branch mirrors the main BioSimSpace structure but with experimental enhancements and additional functionality:

```mermaid
graph TB
    subgraph "Main BioSimSpace"
        MAIN_PROC["Process Classes<br/>Gromacs, Amber, SOMD"]
        MAIN_FE["FreeEnergy<br/>Basic RBFE/ABFE"]
        MAIN_ALIGN["Align<br/>Standard Alignment"]
    end
    
    subgraph "BioSimSpace.Sandpit.Exscientia"
        SAND_PROC["Enhanced Process Classes<br/>_gromacs.py, _amber.py, _somd.py"]
        SAND_FE["Advanced FreeEnergy<br/>RestraintSearch, Restraint"]
        SAND_ALIGN["Enhanced Align<br/>_decouple.py, _alch_ion.py"]
        SAND_PROTO["Extended Protocols<br/>Enhanced Config Generation"]
    end
    
    subgraph "Key Experimental Features"
        REST_SEARCH["RestraintSearch<br/>Automated restraint selection"]
        REST_OBJ["Restraint<br/>Boresch & distance restraints"]
        ALCH_ION["Alchemical Ion<br/>Specialized ion handling"]
        ENH_PROC["Enhanced Processes<br/>Better error handling & metrics"]
    end
    
    MAIN_PROC -.-> SAND_PROC
    MAIN_FE -.-> SAND_FE
    MAIN_ALIGN -.-> SAND_ALIGN
    
    SAND_FE --> REST_SEARCH
    SAND_FE --> REST_OBJ
    SAND_ALIGN --> ALCH_ION
    SAND_PROC --> ENH_PROC
    
    style SAND_PROC fill:#f9f9f9
    style SAND_FE fill:#f9f9f9
    style SAND_ALIGN fill:#f9f9f9
    style SAND_PROTO fill:#f9f9f9
```

Sources: [python/BioSimSpace/Sandpit/Exscientia/Process/_gromacs.py:22-27](), [python/BioSimSpace/Sandpit/Exscientia/FreeEnergy/_restraint_search.py:22-30](), [python/BioSimSpace/Sandpit/Exscientia/FreeEnergy/_restraint.py:22-24]()

## Enhanced Process Classes

The Sandpit provides enhanced versions of the core Process classes with experimental improvements:

### Key Enhancements

| Process Class | Main Enhancements | File Location |
|---------------|-------------------|---------------|
| `Gromacs` | Enhanced trajectory handling, better error reporting, improved restraint support | `_gromacs.py` |
| `Amber` | Advanced FEP mask generation, enhanced parsing, squashing support | `_amber.py` |
| `SOMD` | Improved perturbation file handling, better GPU support detection | `_somd.py` |
| `Process` (base) | Enhanced metrics collection, better error handling, advanced property mapping | `_process.py` |

### Enhanced Process Architecture

```mermaid
graph TB
    subgraph "Sandpit Process Hierarchy"
        BASE["Process (Base Class)<br/>_process.py"]
        GROMACS["Gromacs<br/>_gromacs.py"]
        AMBER["Amber<br/>_amber.py"]
        SOMD["Somd<br/>_somd.py"]
    end
    
    subgraph "Enhanced Features"
        METRICS["Advanced Metrics<br/>saveMetric(), parquet export"]
        ERROR["Enhanced Error Handling<br/>Better diagnostics"]
        RESTRAINTS["Advanced Restraints<br/>ABFE restraint support"]
        TRAJ["Improved Trajectory<br/>Better frame handling"]
    end
    
    subgraph "Engine-Specific Enhancements"
        GROMACS_ENH["GROMACS Enhancements<br/>• Binary run file generation<br/>• Enhanced MDP writing<br/>• Better warning handling"]
        AMBER_ENH["AMBER Enhancements<br/>• FEP mask generation<br/>• Squashing/unsquashing<br/>• Advanced parsing"]
        SOMD_ENH["SOMD Enhancements<br/>• Better GPU detection<br/>• Enhanced perturbation files<br/>• Improved mapping"]
    end
    
    BASE --> GROMACS
    BASE --> AMBER
    BASE --> SOMD
    
    BASE --> METRICS
    BASE --> ERROR
    
    GROMACS --> RESTRAINTS
    GROMACS --> TRAJ
    GROMACS --> GROMACS_ENH
    
    AMBER --> AMBER_ENH
    SOMD --> SOMD_ENH
```

Sources: [python/BioSimSpace/Sandpit/Exscientia/Process/_process.py:74-89](), [python/BioSimSpace/Sandpit/Exscientia/Process/_gromacs.py:78-97](), [python/BioSimSpace/Sandpit/Exscientia/Process/_amber.py:75-91]()

## Restraint Search and Selection

One of the most significant experimental features is the automated restraint selection system for absolute binding free energy (ABFE) calculations:

### RestraintSearch Class

The `RestraintSearch` class provides automated selection of optimal restraints from unrestrained simulations:

```mermaid
graph LR
    subgraph "RestraintSearch Workflow"
        SYSTEM["System<br/>with decoupled molecule"]
        PROTOCOL["Production Protocol<br/>Short simulation"]
        SEARCH["RestraintSearch<br/>_restraint_search.py"]
        ANALYSIS["analyse()<br/>MDRestraintsGenerator or BSS"]
        RESTRAINT["Restraint Object<br/>_restraint.py"]
    end
    
    subgraph "Supported Engines"
        GROMACS_ENGINE["GROMACS"]
        SOMD_ENGINE["SOMD"]
        AMBER_ENGINE["AMBER"]
    end
    
    subgraph "Analysis Methods"
        MDR["MDRestraintsGenerator<br/>External library"]
        BSS_METHOD["BSS Native<br/>Built-in analysis"]
    end
    
    subgraph "Restraint Types"
        BORESCH["Boresch Restraints<br/>1 bond, 2 angles, 3 dihedrals"]
        MULTIPLE["Multiple Distance<br/>Flat-bottom restraints"]
    end
    
    SYSTEM --> SEARCH
    PROTOCOL --> SEARCH
    SEARCH --> ANALYSIS
    ANALYSIS --> RESTRAINT
    
    SEARCH --> GROMACS_ENGINE
    SEARCH --> SOMD_ENGINE
    SEARCH --> AMBER_ENGINE
    
    ANALYSIS --> MDR
    ANALYSIS --> BSS_METHOD
    
    RESTRAINT --> BORESCH
    RESTRAINT --> MULTIPLE
```

Sources: [python/BioSimSpace/Sandpit/Exscientia/FreeEnergy/_restraint_search.py:106-131](), [python/BioSimSpace/Sandpit/Exscientia/FreeEnergy/_restraint_search.py:486-499]()

### Restraint Types and Implementation

The Sandpit supports advanced restraint types with comprehensive free energy corrections:

| Restraint Type | Description | Supported Engines | Correction Methods |
|----------------|-------------|-------------------|-------------------|
| Boresch | 1 bond + 2 angles + 3 dihedrals | GROMACS, SOMD | Analytical, Numerical |
| Multiple Distance | Multiple flat-bottom distance restraints | GROMACS, SOMD | Analytical only |

### Restraint Object Architecture

```mermaid
graph TB
    subgraph "Restraint Class Structure"
        RESTRAINT["Restraint<br/>_restraint.py:75-136"]
        
        subgraph "Boresch Components"
            ANCHORS["anchor_points<br/>r1,r2,r3,l1,l2,l3"]
            EQUIL["equilibrium_values<br/>r0,thetaA0,thetaB0,phiA0,phiB0,phiC0"]
            FORCE["force_constants<br/>kr,kthetaA,kthetaB,kphiA,kphiB,kphiC"]
        end
        
        subgraph "Distance Components"
            DIST_REST["distance_restraints[]<br/>List of restraints"]
            PERM_REST["permanent_distance_restraint<br/>Final restraint"]
            DIST_PROPS["r1,l1,r0,kr,r_fb<br/>Per restraint"]
        end
        
        subgraph "Engine Output"
            GROMACS_OUT["_gromacs_boresch()<br/>Topology format"]
            SOMD_OUT["_somd_restraint()<br/>Config format"]
            AMBER_OUT["_amber_restraint()<br/>Input format"]
        end
    end
    
    RESTRAINT --> ANCHORS
    RESTRAINT --> EQUIL
    RESTRAINT --> FORCE
    
    RESTRAINT --> DIST_REST
    RESTRAINT --> PERM_REST
    DIST_REST --> DIST_PROPS
    PERM_REST --> DIST_PROPS
    
    RESTRAINT --> GROMACS_OUT
    RESTRAINT --> SOMD_OUT
    RESTRAINT --> AMBER_OUT
```

Sources: [python/BioSimSpace/Sandpit/Exscientia/FreeEnergy/_restraint.py:144-162](), [python/BioSimSpace/Sandpit/Exscientia/FreeEnergy/_restraint.py:408-424]()

## Alchemical Ion Support

The Sandpit includes specialized support for alchemical ions in free energy calculations:

### Alchemical Ion Implementation

```mermaid
graph TB
    subgraph "Alchemical Ion System"
        ION["Ion Molecule"]
        MARK["_mark_alchemical_ion()<br/>_alch_ion.py"]
        MARKED_ION["Marked Alchemical Ion<br/>AlchemicalIon property = True"]
    end
    
    subgraph "System Integration"
        SYSTEM["System Object"]
        GET_ION["getAlchemicalIon()<br/>Returns ion atom"]
        GET_IDX["getAlchemicalIonIdx()<br/>Returns global index"]
        CHECK["isAlchemicalIon()<br/>Check if molecule is alchemical ion"]
    end
    
    subgraph "Process Integration"
        RESTRAINTS["Position Restraints<br/>Automatic COM reference"]
        FE_CALC["Free Energy Calculations<br/>Special handling in protocols"]
        COM_REF["_get_protein_com_idx()<br/>Protein COM as reference"]
    end
    
    ION --> MARK
    MARK --> MARKED_ION
    MARKED_ION --> SYSTEM
    
    SYSTEM --> GET_ION
    SYSTEM --> GET_IDX
    SYSTEM --> CHECK
    
    SYSTEM --> RESTRAINTS
    SYSTEM --> FE_CALC
    RESTRAINTS --> COM_REF
```

Sources: [python/BioSimSpace/Sandpit/Exscientia/Align/_alch_ion.py:6-52](), [python/BioSimSpace/Sandpit/Exscientia/Align/_alch_ion.py:55-73]()

## Decoupling and Annihilation

Enhanced decoupling functionality provides more control over alchemical transformations:

### Decouple Function Features

The enhanced `decouple()` function in the Sandpit provides fine-grained control over interaction scaling:

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `charge` | `Tuple[bool, bool]` | Charge interactions at λ=0 and λ=1 | `(True, False)` |
| `LJ` | `Tuple[bool, bool]` | Lennard-Jones interactions at λ=0 and λ=1 | `(True, False)` |
| `intramol` | `bool` | Whether to couple intramolecular forces | `True` |

```mermaid
graph LR
    subgraph "Decoupling Options"
        MOLECULE["Input Molecule"]
        DECOUPLE["decouple()<br/>_decouple.py"]
        
        subgraph "Interaction Control"
            CHARGE_CTRL["charge=(True,False)<br/>Turn off charges"]
            LJ_CTRL["LJ=(True,False)<br/>Turn off LJ"]
            INTRA_CTRL["intramol=True<br/>Keep intramolecular"]
        end
        
        DECOUPLED["Decoupled Molecule<br/>Property: decouple"]
    end
    
    subgraph "Use Cases"
        ABFE["ABFE Calculations<br/>Complete decoupling"]
        PARTIAL["Partial Decoupling<br/>Selective interactions"]
        ANNIHILATION["Annihilation<br/>intramol=False"]
    end
    
    MOLECULE --> DECOUPLE
    DECOUPLE --> CHARGE_CTRL
    DECOUPLE --> LJ_CTRL
    DECOUPLE --> INTRA_CTRL
    DECOUPLE --> DECOUPLED
    
    DECOUPLED --> ABFE
    DECOUPLED --> PARTIAL
    DECOUPLED --> ANNIHILATION
```

Sources: [python/BioSimSpace/Sandpit/Exscientia/Align/_decouple.py:14-56](), [python/BioSimSpace/Sandpit/Exscientia/Align/_decouple.py:68-85]()

## Enhanced Configuration Generation

The Sandpit includes improved configuration generation for various simulation engines:

### Advanced Configuration Features

```mermaid
graph TB
    subgraph "ConfigFactory Enhancements"
        CONFIG_FACTORY["ConfigFactory<br/>Enhanced protocol handling"]
        
        subgraph "Engine-Specific Configs"
            GROMACS_CONFIG["generateGromacsConfig()<br/>• Enhanced FEP support<br/>• Better restraint handling<br/>• Advanced lambda scheduling"]
            AMBER_CONFIG["generateAmberConfig()<br/>• FEP mask generation<br/>• Advanced restraint masks<br/>• Tau_t parameter handling"]
            SOMD_CONFIG["generateSomdConfig()<br/>• Platform detection<br/>• GPU optimization<br/>• Perturbation file handling"]
        end
        
        subgraph "Advanced Features"
            FEP_MASKS["_generate_amber_fep_masks()<br/>Automatic TI region detection"]
            RESTRAINT_MASKS["Enhanced restraint handling<br/>Automatic mask generation"]
            LAMBDA_SCHED["Advanced lambda scheduling<br/>Multi-stage protocols"]
        end
    end
    
    CONFIG_FACTORY --> GROMACS_CONFIG
    CONFIG_FACTORY --> AMBER_CONFIG
    CONFIG_FACTORY --> SOMD_CONFIG
    
    AMBER_CONFIG --> FEP_MASKS
    CONFIG_FACTORY --> RESTRAINT_MASKS
    CONFIG_FACTORY --> LAMBDA_SCHED
```

Sources: [tests/Sandpit/Exscientia/Protocol/test_config.py:61-71](), [tests/Sandpit/Exscientia/Protocol/test_config.py:74-78]()

## Testing and Validation

The Sandpit includes comprehensive test suites that demonstrate usage patterns and validate functionality:

### Test Coverage Areas

| Test Module | Coverage | Key Features Tested |
|-------------|----------|-------------------|
| `test_gromacs.py` | Enhanced GROMACS processes | Restraints, FEP protocols, position restraints |
| `test_amber.py` | Advanced AMBER functionality | FEP output parsing, restraint masks |
| `test_restraint_search.py` | Restraint selection | MDRestraintsGenerator integration, BSS analysis |
| `test_restraint.py` | Restraint objects | Boresch and distance restraints, corrections |
| `test_position_restraint.py` | Position restraints | Alchemical ions, reference systems |

### Usage Examples from Tests

The test files provide practical examples of Sandpit usage:

```python
# Restraint search example
restraint_search = BSS.FreeEnergy.RestraintSearch(
    system, protocol=protocol, engine="GROMACS"
)
restraint = restraint_search.analyse(
    method="BSS", restraint_type="Boresch"
)

# Enhanced process with restraints
process = BSS.Process.Gromacs(
    system, protocol, restraint=restraint
)
```

Sources: [tests/Sandpit/Exscientia/FreeEnergy/test_restraint_search.py:47-55](), [tests/Sandpit/Exscientia/Process/test_gromacs.py:271-275]()

## Future Development

The Sandpit serves as the testing ground for features that may eventually be integrated into the main BioSimSpace package. Key areas of ongoing development include:

- Enhanced free energy calculation methods
- Improved restraint selection algorithms  
- Better integration with external analysis tools
- Advanced simulation protocols for specialized systems
- Expanded support for emerging MD engines

The experimental nature of these features means they may undergo significant changes before stabilization and potential integration into the main codebase.

---