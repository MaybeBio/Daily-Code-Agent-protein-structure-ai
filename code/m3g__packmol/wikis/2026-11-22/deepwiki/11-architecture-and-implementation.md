# Architecture and Implementation

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [app/packmol.f90](app/packmol.f90)
- [src/checkpoint.f90](src/checkpoint.f90)
- [src/computef.f90](src/computef.f90)
- [src/computeg.f90](src/computeg.f90)
- [src/getinp.f90](src/getinp.f90)
- [src/initial.f90](src/initial.f90)
- [src/input.f90](src/input.f90)
- [src/output.f90](src/output.f90)

</details>



This page provides a comprehensive overview of Packmol's internal architecture, implementation patterns, and core algorithms. It covers the structural organization of the Fortran codebase, the flow of data through the system, and the key computational abstractions that enable efficient molecular packing.

For specific build system details, see [Build System Architecture](#4.1). For step-by-step execution flow, see [Program Execution Flow](#4.2). For optimization algorithms, see [Optimization Engine (GENCAN)](#4.4).

## System Overview

Packmol is implemented as a monolithic Fortran 90/95 application with modular organization through Fortran modules. The architecture follows a pipeline model where input is parsed, an initial configuration is generated, an optimization loop refines the solution, and output is written. The system maintains separation of concerns through distinct modules for input handling, computation, spatial management, and optimization control.

### High-Level Module Architecture

```mermaid
graph TB
    subgraph "Entry Point"
        MAIN["app/packmol.f90<br/>main program"]
    end
    
    subgraph "Configuration Modules"
        SIZES["sizes.f90<br/>Array dimensions"]
        INPUT["input.f90<br/>Input parameters"]
        CLI["cli_parser.f90<br/>Command-line parsing"]
    end
    
    subgraph "Computation Modules"
        COMPUTE["compute_data.f90<br/>Coordinates, energies"]
        PBC["pbc.f90<br/>Periodic boundaries"]
        CELL["cell_indexing.f90<br/>Spatial partitioning"]
    end
    
    subgraph "Core Algorithms"
        GETINP["getinp.f90<br/>Parse input file"]
        SETSIZES["setsizes.f90<br/>Allocate arrays"]
        INITIAL["initial.f90<br/>Generate initial point"]
        COMPUTEF["computef.f90<br/>Objective function"]
        COMPUTEG["computeg.f90<br/>Gradient computation"]
        GENCAN["pgencan.f90<br/>GENCAN wrapper"]
        OUTPUT["output.f90<br/>Write results"]
    end
    
    subgraph "Support Modules"
        HEURISTICS["heuristics.f90<br/>movebad function"]
        SWAPTYPE["swaptypemod.f90<br/>Type isolation"]
        FLASH["flashsort.f90<br/>Sorting utilities"]
        USEGENCAN["usegencan.f90<br/>GENCAN parameters"]
    end
    
    MAIN --> CLI
    MAIN --> SETSIZES
    MAIN --> GETINP
    MAIN --> INITIAL
    MAIN --> COMPUTEF
    MAIN --> COMPUTEG
    MAIN --> GENCAN
    MAIN --> OUTPUT
    
    SETSIZES --> SIZES
    SETSIZES --> INPUT
    
    GETINP --> INPUT
    GETINP --> SIZES
    
    INITIAL --> COMPUTE
    INITIAL --> CELL
    INITIAL --> PBC
    INITIAL --> HEURISTICS
    INITIAL --> SWAPTYPE
    
    COMPUTEF --> COMPUTE
    COMPUTEF --> CELL
    COMPUTEF --> PBC
    
    COMPUTEG --> COMPUTE
    COMPUTEG --> CELL
    COMPUTEG --> PBC
    
    GENCAN --> USEGENCAN
    GENCAN --> COMPUTEF
    GENCAN --> COMPUTEG
    
    OUTPUT --> INPUT
    OUTPUT --> COMPUTE
```

Sources: [app/packmol.f90](), [src/sizes.f90](), [src/input.f90](), [src/compute_data.f90]()

## Core Data Structures

Packmol maintains several primary data structures that flow through the system. The central data arrays are managed through Fortran modules and accessed globally during computation.

### Key Data Arrays

| Array | Module | Purpose | Dimensions |
|-------|--------|---------|------------|
| `x` | Local in main | Generalized coordinates (xcm + angles) | `(n)` where n = ntotmol*6 |
| `xcart` | compute_data | Cartesian atom coordinates | `(ntotat, 3)` |
| `coor` | compute_data | Reference molecular coordinates | `(ntotat, 3)` |
| `radius` | compute_data | Per-atom distance tolerances | `(ntotat)` |
| `latomfirst` | compute_data | Cell head pointers | `(ncells(1), ncells(2), ncells(3))` |
| `latomnext` | compute_data | Atom linked list | `(ntotat)` |
| `idfirst` | compute_data | First atom index per type | `(ntype)` |
| `nmols` | compute_data | Number of molecules per type | `(ntype)` |

Sources: [src/compute_data.f90](), [app/packmol.f90:95]()

### Coordinate Representation System

```mermaid
graph LR
    subgraph "Generalized Space"
        X["x array<br/>6*ntotmol elements"]
        XCM["xcm(1:3)<br/>Center of mass"]
        ANGLES["angles(1:3)<br/>Beta, Gamma, Theta"]
    end
    
    subgraph "Rotation Matrix"
        EULER["eulerrmat()<br/>Compute v1,v2,v3"]
        V1["v1: First basis vector"]
        V2["v2: Second basis vector"]
        V3["v3: Third basis vector"]
    end
    
    subgraph "Reference Space"
        COOR["coor array<br/>Molecular template"]
    end
    
    subgraph "Cartesian Space"
        COMPCART["compcart()<br/>Transform coords"]
        XCART["xcart array<br/>Final positions"]
    end
    
    X --> XCM
    X --> ANGLES
    ANGLES --> EULER
    EULER --> V1
    EULER --> V2
    EULER --> V3
    
    XCM --> COMPCART
    V1 --> COMPCART
    V2 --> COMPCART
    V3 --> COMPCART
    COOR --> COMPCART
    COMPCART --> XCART
```

The system uses three coordinate representations:
1. **Generalized coordinates** (`x` array): 6 values per molecule (3 for center of mass + 3 Euler angles)
2. **Reference coordinates** (`coor` array): Template atomic positions for each molecule type
3. **Cartesian coordinates** (`xcart` array): Final 3D positions of all atoms

The transformation is performed by `eulerrmat()` (computes rotation matrix) and `compcart()` (applies rotation and translation).

Sources: [src/computef.f90:52-72](), [src/computeg.f90:43-66](), [src/eulerrmat.f90](), [src/compcart.f90]()

## Module Dependency Structure

### Size Configuration Flow

```mermaid
graph TD
    START["Program Start"] --> CLI_PARSE["cli_parser.f90<br/>parse_command_line_args()"]
    CLI_PARSE --> READ_INPUT["Read input file<br/>Store in inputfile array"]
    READ_INPUT --> KEYWORD_PARSE["Parse keywords<br/>Store in keyword array"]
    KEYWORD_PARSE --> COUNT_LINES["Count lines, structures,<br/>atoms, molecules"]
    COUNT_LINES --> SETSIZES["setsizes.f90<br/>Allocate all arrays"]
    SETSIZES --> GETINP["getinp.f90<br/>Parse detailed input"]
    
    SETSIZES --> ALLOC_INPUT["Allocate input module arrays"]
    SETSIZES --> ALLOC_COMPUTE["Allocate compute_data arrays"]
    SETSIZES --> ALLOC_GENCAN["Allocate usegencan arrays"]
```

Sources: [src/setsizes.f90](), [src/getinp.f90](), [src/cli_parser.f90]()

### Computation Module Dependencies

The computation modules maintain shared state through module variables. Key dependency relationships:

- **compute_data**: Central module containing coordinates, energies, molecular topology
- **pbc**: Periodic boundary condition parameters and helper functions
- **cell_indexing**: Spatial partitioning functions (setcell, index_cell, cell_ind)
- **usegencan**: GENCAN solver parameters and state

Sources: [src/compute_data.f90](), [src/pbc.f90](), [src/cell_indexing.f90]()

## Optimization Architecture

### Two-Phase Strategy

Packmol employs a two-phase optimization strategy implemented in [initial.f90]() and [app/packmol.f90]():

**Phase 1: Constraint Satisfaction** ([initial.f90:167-224]())
- Process each molecule type independently using `swaptype()`
- Optimize only constraint violations (spatial restrictions)
- Use reduced problem size for faster convergence
- Apply `movebad()` heuristic to fix problematic molecules
- Controlled by `nloop0_type` parameter

**Phase 2: Full Optimization** ([app/packmol.f90:740-943]())
- Can pack types separately first, then together (default)
- Or pack all types simultaneously (`packall` option)
- Optimize both distance penalties and constraints
- Use `radscale` to gradually tighten tolerances
- Continue until convergence or maximum iterations

### Type Isolation Mechanism

```mermaid
graph LR
    subgraph "swaptype Operation"
        MODE0["Mode 0: Initialize<br/>Save full system state"]
        MODE1["Mode 1: Activate Type<br/>Set comptype mask"]
        MODE2["Mode 2: Save Type<br/>Store current state"]
        MODE3["Mode 3: Restore All<br/>Reconstruct full system"]
    end
    
    subgraph "Effect on Computation"
        COMP["comptype array<br/>Boolean mask"]
        COMPUTEF["computef checks:<br/>if comptype(itype)"]
        COMPUTEG["computeg checks:<br/>if comptype(itype)"]
    end
    
    MODE1 --> COMP
    COMP --> COMPUTEF
    COMP --> COMPUTEG
```

The `swaptype` mechanism ([swaptypemod.f90]()) allows the optimization to focus on a subset of molecules:
- Saves/restores coordinates for inactive types
- Sets `comptype` boolean mask
- `computef` and `computeg` skip inactive types
- Enables incremental packing without recomputing fixed molecules

Sources: [src/swaptypemod.f90](), [src/computef.f90:45-52](), [src/computeg.f90:48-52]()

## Spatial Management Architecture

### Cell-Based Spatial Indexing

```mermaid
graph TB
    subgraph "Grid Configuration"
        BOUNDS["Spatial bounds<br/>sizemin, sizemax"]
        PBC_BOX["PBC box<br/>pbc_min, pbc_max"]
        NCELLS["Grid dimensions<br/>ncells(3)"]
        CELL_LEN["Cell size<br/>cell_length(3)"]
    end
    
    subgraph "Indexing Functions"
        SETCELL["setcell(xcart, cell)<br/>atom → 3D cell index"]
        INDEX_CELL["index_cell(cell, ncells)<br/>3D → linear index"]
        CELL_IND["cell_ind(i, n)<br/>PBC wrapping"]
    end
    
    subgraph "Linked Lists"
        LATOMFIRST["latomfirst(i,j,k)<br/>First atom in cell"]
        LATOMNEXT["latomnext(iatom)<br/>Next atom"]
        LCELLFIRST["lcellfirst<br/>First non-empty cell"]
        LCELLNEXT["lcellnext(icell)<br/>Next cell"]
    end
    
    BOUNDS --> NCELLS
    PBC_BOX --> NCELLS
    NCELLS --> SETCELL
    NCELLS --> INDEX_CELL
    
    SETCELL --> LATOMFIRST
    INDEX_CELL --> LCELLFIRST
    
    LATOMFIRST --> LATOMNEXT
    LCELLFIRST --> LCELLNEXT
```

The spatial indexing system achieves O(N) scaling for pairwise interactions:
- Space is divided into a 3D grid where `cell_length ≈ discale * radmax`
- Each cell contains a linked list of atoms (`latomfirst`/`latomnext`)
- Non-empty cells are tracked via linked list (`lcellfirst`/`lcellnext`)
- Neighbor search examines only 14 adjacent cells (forward stencil)

Sources: [src/cell_indexing.f90](), [src/initial.f90:278-289](), [src/computef.f90:83-96]()

### Neighbor Search Pattern

The system searches 14 cells to avoid double-counting:
- Current cell (self interactions)
- 3 face-sharing cells (forward in x, y, z)
- 6 edge-sharing cells (forward diagonal faces)
- 4 vertex-sharing cells (forward diagonal corners)

This is implemented in [computef.f90:115-151]() and [computeg.f90:99-141]() using `cell_ind()` for periodic wrapping.

Sources: [src/computef.f90:115-151](), [src/computeg.f90:99-141]()

## Function Evaluation Architecture

### Objective Function Structure

```mermaid
graph TD
    COMPUTEF["computef(n, x, f)"] --> TRANSFORM["Transform x to xcart<br/>Loop over molecules/atoms"]
    
    TRANSFORM --> COMPREST["comprest(icart, fplus)<br/>Constraint penalties"]
    TRANSFORM --> BUILD_CELLS["Build cell lists<br/>latomfirst, latomnext"]
    
    BUILD_CELLS --> CELL_LOOP["Loop over non-empty cells<br/>icell = lcellfirst"]
    CELL_LOOP --> ATOM_LOOP["Loop over atoms in cell<br/>icart = latomfirst"]
    ATOM_LOOP --> FPARC["fparc(icart, jcart)<br/>Distance penalties"]
    
    FPARC --> F["Accumulate f"]
    COMPREST --> F
    COMPREST --> FREST["Track frest<br/>Max constraint violation"]
    FPARC --> FDIST["Track fdist<br/>Max distance violation"]
```

The objective function has two components:
1. **Constraint penalties** (`comprest`): Penalizes molecules outside spatial constraints
2. **Distance penalties** (`fparc`): Penalizes atoms closer than `radius(i) + radius(j)`

Both are smooth, differentiable functions that increase as violations worsen.

Sources: [src/computef.f90:9-154](), [src/comprest.f90](), [src/fparc.f90]()

### Gradient Computation

```mermaid
graph TD
    COMPUTEG["computeg(n, x, g)"] --> GXC["Initialize gxcar = 0<br/>Cartesian gradients"]
    
    GXC --> GWALLS["gwalls(icart, irest)<br/>Constraint gradients"]
    GWALLS --> ACC_GXC["Accumulate to gxcar"]
    
    GXC --> GPARC["gparc(icart, jcart)<br/>Distance gradients"]
    GPARC --> ACC_GXC
    
    ACC_GXC --> CHAIN["Chain rule transformation<br/>gxcar → g(x)"]
    CHAIN --> DERIV_ROT["Rotation matrix derivatives<br/>dv1beta, dv1gama, dv1teta"]
    DERIV_ROT --> G["Final gradient g"]
```

Gradient computation follows the coordinate transformation chain:
1. Compute gradients in Cartesian space (`gxcar`)
2. Apply chain rule to transform to generalized coordinates
3. Uses rotation matrix derivatives computed analytically

Sources: [src/computeg.f90:9-244](), [src/gwalls.f90](), [src/gparc.f90]()

## Output Generation

The output system supports multiple file formats through a single interface in [output.f90]():

### Output Flow

```mermaid
graph TD
    OUTPUT["output(n, x, output_file_name)"] --> RESTART["Write restart files<br/>if restart_to defined"]
    
    OUTPUT --> FORMAT_CHECK{File format?}
    
    FORMAT_CHECK -->|xyz=true| XYZ["Write XYZ format<br/>Lines 93-131"]
    FORMAT_CHECK -->|pdb=true| PDB["Write PDB format<br/>Lines 134-469"]
    FORMAT_CHECK -->|tinker=true| TINKER["Write Tinker XYZ<br/>Lines 473-536"]
    
    PDB --> TRANSFORM_LOOP["Loop molecules/atoms<br/>Transform to Cartesian"]
    TRANSFORM_LOOP --> PDB_RECORD["Format PDB records<br/>Handle residues, chains"]
    PDB_RECORD --> CONNECT["Write CONECT records<br/>if connectivity defined"]
    
    PDB --> CRD_CHECK{crd=true?}
    CRD_CHECK -->|yes| CRD["Write CHARMM CRD<br/>Parallel to PDB output"]
```

Key features:
- **PDB output**: Handles chain assignments, residue numbering, connectivity records
- **Restart files**: Can save/load per-type or full system state
- **CHARMM CRD**: Optional parallel output for CHARMM compatibility
- **Hexadecimal indices**: For systems exceeding 99,999 atoms

Sources: [src/output.f90:9-539]()

## Error Handling and Exit Codes

The system uses structured exit codes defined in [exit_codes.f90]():
- `exit_code_normal = 0`: Success
- `exit_code_input_error = 1`: Invalid input
- `exit_code_open_file = 2`: File I/O error
- `exit_code_failed_to_converge = 3`: Optimization failure

Error handling is immediate with `stop exit_code_*` statements throughout the codebase.

Sources: [src/exit_codes.f90]()

## Related Documentation

For deeper exploration of specific subsystems:
- Build configuration and compilation: [Build System Architecture](#4.1)
- Detailed execution sequence: [Program Execution Flow](#4.2)
- Initial point generation: [System Initialization](#4.3)
- GENCAN integration: [Optimization Engine (GENCAN)](#4.4)
- Cell indexing details: [Spatial Management System](#4.5)
- Energy function details: [Objective Function Evaluation](#4.6)
- Distance calculations: [Atom-to-Atom Interactions](#4.7)
- Coordinate transformations: [Coordinate Transformations](#4.8)

---