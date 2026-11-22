# NAMD Integration

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [README-versions.md](README-versions.md)
- [devel-tools/compile-gromacs.sh](devel-tools/compile-gromacs.sh)
- [doc/.gitignore](doc/.gitignore)
- [doc/Makefile](doc/Makefile)
- [doc/colvars-code-refs.bib](doc/colvars-code-refs.bib)
- [doc/colvars-engine-flags.tex](doc/colvars-engine-flags.tex)
- [doc/colvars-refman-gromacs.tex](doc/colvars-refman-gromacs.tex)
- [doc/colvars-refman-lammps.tex](doc/colvars-refman-lammps.tex)
- [doc/colvars-refman-main.tex](doc/colvars-refman-main.tex)
- [doc/colvars-refman-namd.tex](doc/colvars-refman-namd.tex)
- [doc/colvars-refman-tinkerhp.tex](doc/colvars-refman-tinkerhp.tex)
- [doc/colvars-refman-vmd.tex](doc/colvars-refman-vmd.tex)
- [doc/colvars-refman.bib](doc/colvars-refman.bib)
- [doc/colvars-refman.tex](doc/colvars-refman.tex)
- [doc/extract_code_refs.py](doc/extract_code_refs.py)
- [doc/print_engine_versions.sh](doc/print_engine_versions.sh)
- [namd/src/colvarproxy_namd.C](namd/src/colvarproxy_namd.C)
- [namd/src/colvarproxy_namd.h](namd/src/colvarproxy_namd.h)
- [namd/ug/ug_colvars.tex](namd/ug/ug_colvars.tex)
- [src/colvarmodule.cpp](src/colvarmodule.cpp)
- [src/colvarmodule.h](src/colvarmodule.h)
- [src/colvarmodule_refs.h](src/colvarmodule_refs.h)
- [src/colvarparse.cpp](src/colvarparse.cpp)
- [src/colvarparse.h](src/colvarparse.h)
- [src/colvarproxy.cpp](src/colvarproxy.cpp)
- [src/colvarproxy.h](src/colvarproxy.h)
- [update-colvars-code.sh](update-colvars-code.sh)
- [vmd/doc/ug_colvars.tex](vmd/doc/ug_colvars.tex)
- [vmd/src/colvarproxy_vmd.C](vmd/src/colvarproxy_vmd.C)
- [vmd/src/colvarproxy_vmd.h](vmd/src/colvarproxy_vmd.h)

</details>



This document describes how the Colvars module integrates with the NAMD (NAnoscale Molecular Dynamics) simulation engine. It covers the technical implementation details of the interface between Colvars and NAMD, including initialization, data exchange, and force application mechanisms.

## Introduction

The Colvars module is designed with a modular architecture that allows it to interface with multiple molecular dynamics engines. For NAMD, this integration is accomplished through a specialized proxy class that translates between Colvars' internal representation and NAMD's data structures and runtime model.

The NAMD integration takes advantage of NAMD's "GlobalMaster" mechanism, which allows external modules to influence the simulation by applying forces to atoms based on collective variables calculated from atomic positions.

## Architecture Overview

The integration architecture follows a proxy pattern, where a NAMD-specific implementation of the colvarproxy interface handles all communication between the Colvars module and NAMD.

```mermaid
classDiagram
    class colvarmodule {
        +colvars : vector~colvar*~
        +biases : vector~colvarbias*~
        +calc()
        +setup_output()
        +update_colvar_forces()
    }
    
    class colvarproxy {
        <<interface>>
        +atoms_positions : vector~rvector~
        +atoms_total_forces : vector~rvector~
        +atoms_new_colvar_forces : vector~rvector~
        +setup()
        +update_input()
        +add_energy()
        +apply_atom_force()
    }
    
    class GlobalMaster {
        <<NAMD>>
        +calculate()
    }
    
    class colvarproxy_namd {
        -atoms_map : vector~int~
        -simparams : SimParameters*
        -controller : Controller*
        -random : Random
        +calculate()
        +setup()
        +update_atoms_map()
    }
    
    colvarproxy <|-- colvarproxy_namd
    GlobalMaster <|-- colvarproxy_namd
    colvarproxy_namd --> colvarmodule : creates/owns
```

Sources: [src/colvarmodule.h:55-900](), [src/colvarproxy.h:55-244](), [namd/src/colvarproxy_namd.h:39-291]()

## Integration Components

The NAMD integration consists of the following primary components:

1. **colvarproxy_namd**: This class serves as the bridge between NAMD and the Colvars module. It inherits from both NAMD's GlobalMaster class and the Colvars colvarproxy interface.

2. **GlobalMaster mechanism**: NAMD provides this extension point for modules that need to compute forces during simulation.

3. **Atom mapping system**: Maintains a mapping between NAMD atom indices and Colvars' internal representation.

4. **Force communication channels**: NAMD provides mechanisms for modules to apply forces to atoms, which Colvars uses to implement biasing methods.

### The colvarproxy_namd Class

The `colvarproxy_namd` class is the central component of the integration. It must satisfy the requirements of both NAMD's GlobalMaster interface and the Colvars module's proxy interface.

Key responsibilities include:
- Translating atom selections between NAMD and Colvars
- Converting forces from Colvars to NAMD
- Managing I/O operations
- Handling configuration parameters

Sources: [namd/src/colvarproxy_namd.h:39-291](), [namd/src/colvarproxy_namd.C:46-154]()

## Data Flow and Runtime Execution

The diagram below illustrates the data flow between NAMD and the Colvars module during a simulation step:

```mermaid
sequenceDiagram
    participant NAMD as NAMD Engine
    participant Proxy as colvarproxy_namd
    participant Module as colvarmodule
    participant CV as colvars
    participant Bias as biases
    
    Note over NAMD,Bias: Each simulation timestep
    NAMD->>Proxy: calculate() call
    Proxy->>Proxy: Update atom positions
    Proxy->>Module: calc()
    Module->>CV: calc_colvars()
    CV-->>Module: Updated CV values
    Module->>Bias: calc_biases()
    Bias-->>Module: Bias forces on CVs
    Module->>Module: update_colvar_forces()
    Module-->>Proxy: Atomic forces
    Proxy->>NAMD: Apply forces to atoms
    Proxy->>NAMD: Submit energy to NAMD
```

Sources: [namd/src/colvarproxy_namd.C:345-620](), [src/colvarmodule.cpp:850-905]()

### Key Methods in the Execution Flow

1. **calculate()**: Called by NAMD at each timestep, this method updates atomic positions from NAMD and triggers the Colvars calculation.

2. **update_atoms_map()**: Maintains the mapping between NAMD atoms and Colvars atoms.

3. **calc()**: The main computational method in the Colvars module that calculates variables and biases.

4. **update_colvar_forces()**: Translates forces from collective variables to atomic forces.

Sources: [namd/src/colvarproxy_namd.C:345-620](), [src/colvarmodule.cpp:580-605]()

## Initialization and Configuration

The initialization process follows these steps:

```mermaid
flowchart TB
    A["NAMD starts simulation"] --> B["colvarproxy_namd constructor"]
    B --> C["Create colvarmodule instance"]
    C --> D["Parse configuration file/string"]
    D --> E["Parse global parameters"]
    E --> F["Parse collective variables"]
    F --> G["Parse biases"]
    G --> H["setup() called"]
    H --> I["Update atomic data"]
    I --> J["Begin simulation loop"]
    
    subgraph "Each timestep"
    J --> K["calculate() method called"]
    K --> L["Update positions"]
    L --> M["Call colvarmodule::calc()"]
    M --> N["Apply forces to NAMD"]
    N --> J
    end
```

Sources: [namd/src/colvarproxy_namd.C:46-154](), [namd/src/colvarproxy_namd.C:234-310](), [src/colvarmodule.cpp:383-435]()

### Configuration Path

NAMD provides several ways to configure the Colvars module:

1. **colvars** - Flag to enable the Colvars module (in NAMD config file)
2. **colvarsConfig** - Path to Colvars configuration file (in NAMD config file)
3. **colvarsInput** - Path to input state file for restarting (in NAMD config file)
4. **cv config** - Tcl command to provide configuration as a string
5. **cv configfile** - Tcl command to specify configuration file

Sources: [doc/colvars-refman-main.tex:414-451]()

## Atom Selection and Management

The NAMD integration maps between NAMD's atom numbering and Colvars' internal atom indices. This mapping is maintained in the `atoms_map` vector:

```mermaid
flowchart LR
    A["NAMD Atom ID <br>(1-based)"] --> B["atoms_map lookup"]
    B --> C["Colvars internal index <br>(0-based)"]
    
    D["Atom request"] --> E["add_atom_slot()"]
    E --> F["atoms_ids vector"]
    E --> G["atoms_positions vector"]
    E --> H["atoms_forces vector"]
    
    I["Atoms position update"] --> J["NAMD provides<br>positions"]
    J --> K["Copy to<br>atoms_positions"]
    
    L["Force application"] --> M["Update<br>atoms_new_colvar_forces"]
    M --> N["Send forces<br>to NAMD"]
```

Sources: [namd/src/colvarproxy_namd.C:191-223](), [namd/src/colvarproxy_namd.C:452-469](), [namd/src/colvarproxy_namd.C:570-574]()

## Force Application

Colvars calculates biasing forces based on collective variables and applies them to atoms in the simulation. The force application process involves:

1. Calculation of forces on collective variables
2. Distribution of these forces to individual atoms
3. Communication of atomic forces to NAMD

The NAMD proxy implements this by:

```mermaid
flowchart TD
    A["Colvars calculates bias forces<br>on collective variables"] --> B["Forces distributed to atoms<br>using chain rule"]
    B --> C["Forces stored in<br>atoms_new_colvar_forces"]
    C --> D["Forces added to NAMD's<br>modifyForcedAtoms and<br>modifyAppliedForces arrays"]
    D --> E["NAMD applies forces<br>during integration step"]
```

Sources: [namd/src/colvarproxy_namd.C:570-600]()

## Special Features in NAMD Integration

### Accelerated MD Support

NAMD's integration specifically supports accelerated molecular dynamics (aMD) with Colvars through the `update_accelMD_info()` method, which retrieves the aMD boost factor from the controller and makes it available to Colvars biases.

Sources: [namd/src/colvarproxy_namd.C:622-625](), [namd/src/colvarproxy_namd.h:68-70]()

### Volumetric Maps Support

In recent versions of NAMD (2.14 and later), the integration supports NAMD's volumetric maps (GridForce) functionality, allowing Colvars to use and manipulate volumetric data.

Sources: [namd/src/colvarproxy_namd.h:224-263]()

### SMP Parallelism

NAMD's Colvars integration supports shared memory parallelism (SMP) through Charm++ when available, enabling parallel calculation of collective variables.

Sources: [namd/src/colvarproxy_namd.h:128-177]()

## Update and Maintenance

The Colvars module in NAMD is updated using the `update-colvars-code.sh` script, which copies files from the Colvars repository to the appropriate locations in the NAMD source tree.

```mermaid
flowchart LR
    A["Colvars Repository"] -->|"update-colvars-code.sh"| B["NAMD Source Tree"]
    
    subgraph "Colvars Repository"
    A1["Core Module Files<br>src/*.h, src/*.cpp"]
    A2["NAMD Interface Files<br>namd/src/*.h, namd/src/*.C"]
    end
    
    subgraph "NAMD Source Tree"
    B1["Core Module Files<br>colvars/src/*.h, colvars/src/*.cpp"]
    B2["Interface Files<br>src/colvarproxy_namd.*"]
    B3["Documentation<br>ug/ug_colvars.tex"]
    end
    
    A1 --> B1
    A2 --> B2
```

Sources: [update-colvars-code.sh:344-425]()

## Summary

The NAMD integration for Colvars provides a complete interface between the Colvars module and NAMD simulation engine. It leverages NAMD's GlobalMaster mechanism to implement enhanced sampling methods based on collective variables.

The main components are:
1. The `colvarproxy_namd` class that bridges NAMD and Colvars
2. Atom selection and force application mechanisms
3. Configuration and I/O interfaces
4. Special features like accelerated MD and volumetric maps support

This architecture provides a robust and performance-efficient way to use the Colvars module's enhanced sampling methods in NAMD simulations.

---