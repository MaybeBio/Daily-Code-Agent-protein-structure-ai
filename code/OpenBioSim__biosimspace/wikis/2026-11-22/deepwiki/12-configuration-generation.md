# Configuration Generation

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.github/workflows/Sandpit_exs.yml](.github/workflows/Sandpit_exs.yml)
- [python/BioSimSpace/FreeEnergy/_relative.py](python/BioSimSpace/FreeEnergy/_relative.py)
- [python/BioSimSpace/Protocol/_custom.py](python/BioSimSpace/Protocol/_custom.py)
- [python/BioSimSpace/Protocol/_equilibration.py](python/BioSimSpace/Protocol/_equilibration.py)
- [python/BioSimSpace/Protocol/_free_energy_equilibration.py](python/BioSimSpace/Protocol/_free_energy_equilibration.py)
- [python/BioSimSpace/Protocol/_minimisation.py](python/BioSimSpace/Protocol/_minimisation.py)
- [python/BioSimSpace/Protocol/_production.py](python/BioSimSpace/Protocol/_production.py)
- [python/BioSimSpace/Sandpit/Exscientia/Align/_squash.py](python/BioSimSpace/Sandpit/Exscientia/Align/_squash.py)
- [python/BioSimSpace/Sandpit/Exscientia/Protocol/_config.py](python/BioSimSpace/Sandpit/Exscientia/Protocol/_config.py)
- [python/BioSimSpace/_Config/_amber.py](python/BioSimSpace/_Config/_amber.py)
- [python/BioSimSpace/_Config/_config.py](python/BioSimSpace/_Config/_config.py)
- [python/BioSimSpace/_Config/_gromacs.py](python/BioSimSpace/_Config/_gromacs.py)
- [python/BioSimSpace/_Config/_somd.py](python/BioSimSpace/_Config/_somd.py)

</details>



This document covers BioSimSpace's configuration generation system, which converts `Protocol` objects and `System` objects into engine-specific configuration files for molecular dynamics simulations. The system provides a unified interface for generating configuration files for AMBER, GROMACS, SOMD, and other MD engines.

For information about defining simulation protocols, see [Simulation Protocols](#4.1). For information about running simulations with these configurations, see [Process Classes and MD Engines](#4.2).

## Architecture Overview

BioSimSpace's configuration generation system uses a hierarchical class structure with a base `Config` class and engine-specific implementations. The system transforms protocol parameters and system properties into the specific syntax required by each MD engine.

### Configuration Class Hierarchy

```mermaid
classDiagram
    class Config {
        +hasBox(system, property_map) bool
        +hasWater(system) bool
        +reportInterval() int
        +restartInterval() int
        +steps() int
        +isRestart() bool
        #_system System
        #_protocol Protocol
        #_property_map dict
    }
    
    class Amber {
        +createConfig(version, is_pmemd, is_pmemd_cuda, explicit_dummies, extra_options, extra_lines) list
        +_create_restraint_mask(atom_idxs) str
        +_generate_amber_fep_masks(system, is_vacuum, is_pmemd_cuda, timestep, explicit_dummies) dict
    }
    
    class Gromacs {
        +createConfig(version, extra_options, extra_lines) list
    }
    
    class Somd {
        +createConfig(extra_options, extra_lines) list
    }
    
    class ConfigFactory {
        +generateAmberConfig(extra_options, extra_lines) list
        +generateGromacsConfig(extra_options, extra_lines, restraint, perturbation_type) list
        +generateSomdConfig(extra_options, extra_lines, restraint, perturbation_type) list
        +_generate_amber_fep_masks(timestep) dict
        +_has_box bool
        +_has_water bool
    }
    
    Config <|-- Amber
    Config <|-- Gromacs  
    Config <|-- Somd
```

Sources: [python/BioSimSpace/_Config/_config.py:38-219](), [python/BioSimSpace/_Config/_amber.py:42-563](), [python/BioSimSpace/_Config/_gromacs.py:39-308](), [python/BioSimSpace/_Config/_somd.py:39-277](), [python/BioSimSpace/Sandpit/Exscientia/Protocol/_config.py:15-775]()

### Configuration Generation Workflow

```mermaid
flowchart TD
    A["System + Protocol"] --> B["Config.__init__()"]
    B --> C["Validate Inputs"]
    C --> D["Store system, protocol, property_map"]
    
    D --> E["createConfig()"]
    E --> F["Check System Properties"]
    F --> G["hasBox()"]
    F --> H["hasWater()"]
    
    G --> I["Generate Protocol Dict"]
    H --> I
    I --> J["Add Engine-Specific Options"]
    
    J --> K{"Protocol Type?"}
    K -->|"Minimisation"| L["Minimisation Settings"]
    K -->|"Equilibration"| M["Temperature/Pressure Control"] 
    K -->|"Production"| N["Production Settings"]
    K -->|"FreeEnergy"| O["FEP Settings + Masks"]
    
    L --> P["Format Config Lines"]
    M --> P
    N --> P
    O --> P
    
    P --> Q["Return config list[str]"]
```

Sources: [python/BioSimSpace/_Config/_config.py:41-81](), [python/BioSimSpace/_Config/_amber.py:67-409]()

## Base Configuration System

The `Config` base class provides common functionality shared across all MD engines, including system property detection and protocol parameter extraction.

### Core Utilities

The base class provides several utility methods:

| Method | Purpose | Returns |
|--------|---------|---------|
| `hasBox(system, property_map)` | Check if system has periodic boundary conditions | bool |
| `hasWater(system)` | Check if system contains water molecules | bool |
| `reportInterval()` | Get report interval from protocol | int |
| `restartInterval()` | Get restart interval from protocol | int |
| `steps()` | Calculate total integration steps | int |
| `isRestart()` | Check if this is a restart simulation | bool |

```mermaid
flowchart LR
    A["Protocol Object"] --> B["steps()"]
    A --> C["reportInterval()"]
    A --> D["restartInterval()"]
    A --> E["isRestart()"]
    
    F["System Object"] --> G["hasBox()"]
    F --> H["hasWater()"]
    
    B --> I["Protocol Dict"]
    C --> I
    D --> I
    E --> I
    G --> I
    H --> I
    
    I --> J["Engine-Specific Config"]
```

Sources: [python/BioSimSpace/_Config/_config.py:82-219]()

## Engine-Specific Implementations

Each MD engine has specific configuration syntax and requirements. BioSimSpace provides dedicated classes for generating engine-appropriate configuration files.

### AMBER Configuration

The `Amber` class generates configuration files for AMBER's `sander` and `pmemd` engines:

```mermaid
flowchart TD
    A["Amber.createConfig()"] --> B["Initialize protocol_dict"]
    B --> C["Set Basic Options"]
    C --> D["ntpr, ntwr, ntwx, ntxo, irest"]
    
    D --> E{"Protocol Type?"}
    E -->|"Minimisation"| F["imin=1, ntmin=2, maxcyc, ncyc"]
    E -->|"MD"| G["dt, nstlim, ntc=2, ntf=2"]
    
    F --> H["Boundary Conditions"]
    G --> H
    H --> I["ntb, cut, iwrap"]
    
    I --> J{"Position Restraints?"}
    J -->|"Yes"| K["ntr=1, restraint_wt, restraintmask"]
    J -->|"No"| L["Pressure Control"]
    K --> L
    
    L --> M{"Pressure?"}
    M -->|"Yes"| N["ntp=1, pres0, barostat"]
    M -->|"No"| O["Temperature Control"]
    N --> O
    
    O --> P["ntt=3, gamma_ln, temp0"]
    
    P --> Q{"Free Energy?"}
    Q -->|"Yes"| R["icfe=1, ifsc=1, mbar_states"]
    Q -->|"No"| S["Format Output"]
    R --> T["Generate FEP Masks"]
    T --> U["timask1, timask2, scmask1, scmask2"]
    U --> S
    
    S --> V["Return config list"]
```

Sources: [python/BioSimSpace/_Config/_amber.py:67-409]()

#### AMBER Free Energy Masks

For free energy calculations, AMBER requires specific atom masks to define which atoms participate in the perturbation:

- `timask1`: Atoms that exist at λ=0
- `timask2`: Atoms that exist at λ=1  
- `scmask1`: Dummy atoms at λ=0
- `scmask2`: Dummy atoms at λ=1
- `noshakemask`: Atoms to exclude from SHAKE constraints

Sources: [python/BioSimSpace/_Config/_amber.py:484-563]()

### GROMACS Configuration  

The `Gromacs` class generates `.mdp` parameter files for GROMACS simulations:

```mermaid
flowchart TD
    A["Gromacs.createConfig()"] --> B["protocol_dict initialization"]
    B --> C["nstlog, nstenergy, nstxout-compressed"]
    
    C --> D{"Protocol Type?"}
    D -->|"Minimisation"| E["integrator = steep"]
    D -->|"MD"| F["integrator = md/sd, dt"]
    
    E --> G["nsteps"]
    F --> G
    G --> H["Constraints"]
    H --> I["constraints = h-bonds, constraint-algorithm = LINCS"]
    
    I --> J["PBC Settings"]
    J --> K["pbc = xyz, cutoff-scheme = Verlet"]
    
    K --> L{"Has Box + Water?"}
    L -->|"Yes"| M["PME: rlist=0.8, rcoulomb=0.8, coulombtype=PME"]
    L -->|"No"| N["Vacuum: rlist=333.3, coulombtype=Cut-off"]
    
    M --> O["Pressure Control"]
    N --> O
    O --> P{"Pressure?"}
    P -->|"Yes"| Q["pcoupl = c-rescale/berendsen"]
    P -->|"No"| R["Temperature Control"]
    Q --> R
    
    R --> S["tc-grps = system, tau-t, ref-t"]
    
    S --> T{"Free Energy?"}
    T -->|"Yes"| U["free-energy = yes, init-lambda-state"]
    T -->|"No"| V["Format Output"]
    U --> W["fep-lambdas, calc-lambda-neighbors"]
    W --> V
    
    V --> X["Return config list"]
```

Sources: [python/BioSimSpace/_Config/_gromacs.py:64-308]()

### SOMD Configuration

The `Somd` class generates configuration files for SOMD (Sire OpenMM Molecular Dynamics):

```mermaid
flowchart TD
    A["Somd.createConfig()"] --> B["protocol_dict initialization"]
    B --> C["save coordinates = True"]
    
    C --> D{"Protocol Type?"}
    D -->|"Minimisation"| E["minimise = True, minimise maximum iterations"]
    D -->|"MD"| F["Calculate ncycles and nmoves"]
    
    F --> G["timestep, ncycles_per_snap"]
    G --> H{"timestep >= 4fs?"}
    H -->|"Yes"| I["integrator_type = langevinmiddle"]
    H -->|"No"| J["Default integrator"]
    
    E --> K["Cutoff Settings"]
    I --> K
    J --> K
    
    K --> L{"Has Water?"}
    L -->|"Yes"| M["reaction field dielectric = 78.3"]
    L -->|"No"| N["No dielectric"]
    
    M --> O{"Has Box?"}
    N --> O
    O -->|"Yes"| P["cutoff type = cutoffperiodic"]
    O -->|"No"| Q["cutoff type = cutoffnonperiodic"]
    
    P --> R["cutoff distance = 10 angstrom"]
    Q --> R
    
    R --> S{"Free Energy?"}
    S -->|"Yes"| T["lambda array, lambda_val, perturbed residue number"]
    S -->|"No"| U["Format Output"]
    T --> U
    
    U --> V["Return config list"]
```

Sources: [python/BioSimSpace/_Config/_somd.py:64-277]()

## ConfigFactory Alternative Implementation

The Sandpit contains an alternative `ConfigFactory` class that provides a different approach to configuration generation, with more explicit handling of different molecular dynamics engines:

```mermaid
classDiagram
    class ConfigFactory {
        +system System
        +protocol Protocol
        +explicit_dummies bool
        +_has_box bool
        +_has_water bool
        +_report_interval int
        +_restart_interval int
        +_steps int
        +generateAmberConfig() list
        +generateGromacsConfig() list
        +generateSomdConfig() list
    }
    
    class System {
        +nWaterMolecules() int
        +getRestraintAtoms() list
        +nAtoms() int
    }
    
    class Protocol {
        +getTimeStep() Time
        +getRunTime() Time
        +getTemperature() Temperature
        +getPressure() Pressure
        +getReportInterval() int
    }
    
    ConfigFactory --> System
    ConfigFactory --> Protocol
```

The `ConfigFactory` approach combines all engine-specific generation methods in a single class, using composition rather than inheritance.

Sources: [python/BioSimSpace/Sandpit/Exscientia/Protocol/_config.py:15-775]()

## Integration with Protocols and Systems

Configuration generation is tightly integrated with BioSimSpace's protocol and system objects:

### Protocol Integration

Different protocol types require different configuration parameters:

| Protocol Type | Key Parameters | Configuration Impact |
|--------------|----------------|---------------------|
| `Minimisation` | `steps` | Sets `maxcyc` (AMBER), `nsteps` (GROMACS) |
| `Equilibration` | `temperature_start`, `temperature_end`, `runtime` | Temperature ramping, simulation length |
| `Production` | `temperature`, `pressure`, `runtime` | Constant conditions, long simulations |
| `FreeEnergyProduction` | `lambda`, `lambda_values` | Alchemical parameters, MBAR energies |

Sources: [python/BioSimSpace/Protocol/_equilibration.py:39-547](), [python/BioSimSpace/Protocol/_production.py:39-454](), [python/BioSimSpace/Protocol/_minimisation.py:37-148]()

### System Property Detection

The configuration system automatically detects system properties and adjusts settings accordingly:

```mermaid
flowchart LR
    A["System"] --> B["hasBox()"]
    A --> C["hasWater()"]
    A --> D["nPerturbableMolecules()"]
    
    B -->|"True"| E["Periodic Boundary Conditions"]
    B -->|"False"| F["Vacuum Simulation"]
    
    C -->|"True"| G["Solvated System Settings"]
    C -->|"False"| H["Gas Phase Settings"]
    
    D -->|"> 0"| I["Free Energy Calculation"]
    D -->|"= 0"| J["Regular MD"]
    
    E --> K["Final Configuration"]
    F --> K
    G --> K
    H --> K
    I --> K
    J --> K
```

Sources: [python/BioSimSpace/_Config/_config.py:82-149]()

---