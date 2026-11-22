# Data Formats and Sample Data

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [datasets/1ALA-500.pdb](datasets/1ALA-500.pdb)
- [src/app/application.cpp](src/app/application.cpp)
- [src/color_utils.cpp](src/color_utils.cpp)
- [src/color_utils.h](src/color_utils.h)
- [src/event.cpp](src/event.cpp)
- [src/loader.cpp](src/loader.cpp)
- [src/loader.h](src/loader.h)

</details>



This document describes the molecular data formats supported by VIAMD and the file loading infrastructure. It covers structure formats, trajectory formats, format detection mechanisms, and the loader architecture that handles various molecular dynamics file types.

For information about the file loading system implementation and caching mechanisms, see [File Loading System](#2.2). For details about molecular data structures used internally, see [Molecular Data Structures and Display](#2.4).

## Supported Molecular Structure Formats

VIAMD supports loading molecular structure data from multiple standard formats through a unified loader interface. Each format is handled by a specific loader implementation within the MDLib library.

### Structure Format Overview

| Format | Extension(s) | Description | Loader Type |
|--------|-------------|-------------|-------------|
| PDB | `.pdb` | Standard Protein Data Bank format | `MOL_LOADER_PDB` |
| GRO | `.gro` | Gromacs structure format | `MOL_LOADER_GRO` |
| XYZ | `.xyz`, `.xmol`, `.arc` | Simple coordinate format | `MOL_LOADER_XYZ` |
| mmCIF | `.cif` | PDBx/mmCIF crystallographic format | `MOL_LOADER_CIF` |
| LAMMPS | `.data` | LAMMPS data format | `MOL_LOADER_LAMMPS` |
| VeloxChem | `.out`, `.h5` | Quantum chemistry output | `MOL_LOADER_VELOXCHEM` |

```mermaid
graph TD
    subgraph "Molecular Structure Formats"
        PDB["PDB Format<br/>(.pdb)"]
        GRO["GRO Format<br/>(.gro)"]
        XYZ["XYZ Format<br/>(.xyz, .xmol, .arc)"]
        CIF["mmCIF Format<br/>(.cif)"]
        LAMMPS["LAMMPS Format<br/>(.data)"]
        VLX["VeloxChem Format<br/>(.out, .h5)"]
    end
    
    subgraph "Loader APIs"
        PDB_API["md_pdb_molecule_api()"]
        GRO_API["md_gro_molecule_api()"]
        XYZ_API["md_xyz_molecule_api()"]
        CIF_API["md_mmcif_molecule_api()"]
        LAMMPS_API["md_lammps_molecule_api()"]
        VLX_API["md_vlx_molecule_api()"]
    end
    
    subgraph "Loader Enum"
        ENUM["mol_loader_t"]
    end
    
    PDB --> PDB_API
    GRO --> GRO_API
    XYZ --> XYZ_API
    CIF --> CIF_API
    LAMMPS --> LAMMPS_API
    VLX --> VLX_API
    
    PDB_API --> ENUM
    GRO_API --> ENUM
    XYZ_API --> ENUM
    CIF_API --> ENUM
    LAMMPS_API --> ENUM
    VLX_API --> ENUM
```

Sources: [src/loader.cpp:29-76]()

### Format-Specific Features

The **LAMMPS loader** requires additional configuration and supports automatic atom format detection. When loading LAMMPS data files, the system performs a preload check to determine the atom format automatically, or prompts the user for configuration if needed.

```mermaid
graph LR
    subgraph "LAMMPS Loading Process"
        FILE["LAMMPS .data file"]
        PRECHECK["mol_loader_preload_check()"]
        AUTO["Auto-detect format"]
        DIALOG["User dialog"]
        LOADER["md_lammps_molecule_api()"]
    end
    
    FILE --> PRECHECK
    PRECHECK --> AUTO
    PRECHECK --> DIALOG
    AUTO --> LOADER
    DIALOG --> LOADER
```

Sources: [src/loader.cpp:190-210]()

The **VeloxChem loader** is conditionally compiled and only available when `MD_VLX` is defined, providing integration with quantum chemistry calculations.

## Supported Trajectory Formats

Trajectory formats store time-series coordinate data for molecular dynamics simulations. VIAMD supports both compressed and uncompressed trajectory formats.

### Trajectory Format Overview

| Format | Extension | Description | Compression | Loader Type |
|--------|-----------|-------------|------------|-------------|
| XTC | `.xtc` | Gromacs compressed trajectory | Lossy | `TRAJ_LOADER_XTC` |
| TRR | `.trr` | Gromacs full-precision trajectory | Lossless | `TRAJ_LOADER_TRR` |
| PDB | `.pdb` | Multi-model PDB trajectory | None | `TRAJ_LOADER_PDB` |
| XYZ | `.xyz`, `.xmol`, `.arc` | Simple coordinate trajectory | None | `TRAJ_LOADER_XYZ` |
| LAMMPSTRJ | `.lammpstrj` | LAMMPS trajectory (ASCII) | None | `TRAJ_LOADER_LAMMPSTRJ` |

```mermaid
graph TD
    subgraph "Trajectory Formats"
        XTC["XTC<br/>Compressed<br/>(.xtc)"]
        TRR["TRR<br/>Lossless<br/>(.trr)"]
        PDB_TRAJ["PDB Multi-model<br/>(.pdb)"]
        XYZ_TRAJ["XYZ Trajectory<br/>(.xyz, .xmol, .arc)"]
        LAMMPS_TRAJ["LAMMPS Trajectory<br/>(.lammpstrj)"]
    end
    
    subgraph "Trajectory Loaders"
        XTC_LOAD["md_xtc_trajectory_loader()"]
        TRR_LOAD["md_trr_trajectory_loader()"]
        PDB_LOAD["md_pdb_trajectory_loader()"]
        XYZ_LOAD["md_xyz_trajectory_loader()"]
        LAMMPS_LOAD["md_lammps_trajectory_loader()"]
    end
    
    subgraph "Frame Cache System"
        CACHE["md_frame_cache_t"]
        MEMORY["Memory Management"]
    end
    
    XTC --> XTC_LOAD
    TRR --> TRR_LOAD
    PDB_TRAJ --> PDB_LOAD
    XYZ_TRAJ --> XYZ_LOAD
    LAMMPS_TRAJ --> LAMMPS_LOAD
    
    XTC_LOAD --> CACHE
    TRR_LOAD --> CACHE
    PDB_LOAD --> CACHE
    XYZ_LOAD --> CACHE
    LAMMPS_LOAD --> CACHE
    
    CACHE --> MEMORY
```

Sources: [src/loader.cpp:78-113](), [src/loader.cpp:561-615]()

## File Format Detection and Loading Pipeline

VIAMD uses a unified loading pipeline that automatically detects file formats based on extensions and initializes appropriate loaders.

### Format Detection Process

```mermaid
graph TD
    INPUT["File Path Input"]
    EXT_CHECK["extract_ext()"]
    MOL_DETECT["mol_loader_from_ext()"]
    TRAJ_DETECT["traj_loader_from_ext()"]
    
    subgraph "LoaderState Initialization"
        STATE["LoaderState"]
        MOL_LOADER["mol_loader"]
        TRAJ_LOADER["traj_loader"]
        PRECHECK["mol_loader_preload_check()"]
        FLAGS["LoaderStateFlags"]
    end
    
    subgraph "Format Tables"
        MOL_TABLE["mol_loader_ext[]"]
        TRAJ_TABLE["traj_loader_ext[]"]
        API_TABLE["mol_loader_api[]"]
    end
    
    INPUT --> EXT_CHECK
    EXT_CHECK --> MOL_DETECT
    EXT_CHECK --> TRAJ_DETECT
    
    MOL_DETECT --> MOL_TABLE
    TRAJ_DETECT --> TRAJ_TABLE
    MOL_TABLE --> API_TABLE
    
    MOL_DETECT --> STATE
    TRAJ_DETECT --> STATE
    STATE --> MOL_LOADER
    STATE --> TRAJ_LOADER
    STATE --> PRECHECK
    STATE --> FLAGS
```

Sources: [src/loader.cpp:330-352](), [src/loader.cpp:302-328]()

### Loader State Management

The `LoaderState` structure encapsulates all information needed to load a file, including format-specific arguments and configuration flags.

```cpp
struct LoaderState {
    md_molecule_loader_i*   mol_loader = 0;
    md_trajectory_loader_i* traj_loader = 0;
    const void*             mol_loader_arg = 0;
    LoaderStateFlags        flags = LoaderStateFlag_None;
    size_t data_size = 0;
    void* data_ptr = 0;
};
```

Key functions for loader state management:
- `init_loader_state()` - Initialize loader based on file path
- `free_loader_state()` - Clean up allocated loader arguments
- `mol_loader_preload_check()` - Format-specific preprocessing

Sources: [src/loader.h:29-37](), [src/loader.cpp:330-361]()

## Trajectory Loading and Caching

VIAMD implements sophisticated trajectory handling with frame caching, periodic boundary condition (PBC) processing, and memory management optimizations.

### Trajectory Instance Management

```mermaid
graph TD
    subgraph "Trajectory Loading"
        OPEN["traj::open_file()"]
        VALIDATE["Atom Count Validation"]
        CACHE_INIT["md_frame_cache_init()"]
        WRAPPER["Trajectory Wrapper"]
    end
    
    subgraph "LoadedTrajectory Structure"
        KEY["uint64_t key"]
        MOL_REF["const md_molecule_t* mol"]
        INTERNAL["md_trajectory_i* traj"]
        CACHE["md_frame_cache_t cache"]
        RECENTER["recenter_indices"]
        ALLOC["md_allocator_i* alloc"]
    end
    
    subgraph "Frame Processing"
        LOAD_FRAME["load_frame()"]
        PBC["PBC Processing"]
        RECENTERING["COM Recentering"]
        CACHE_LOOKUP["Cache Lookup"]
    end
    
    OPEN --> VALIDATE
    VALIDATE --> CACHE_INIT
    CACHE_INIT --> WRAPPER
    
    WRAPPER --> KEY
    WRAPPER --> MOL_REF
    WRAPPER --> INTERNAL
    WRAPPER --> CACHE
    WRAPPER --> RECENTER
    WRAPPER --> ALLOC
    
    LOAD_FRAME --> CACHE_LOOKUP
    LOAD_FRAME --> PBC
    LOAD_FRAME --> RECENTERING
```

Sources: [src/loader.cpp:561-615](), [src/loader.cpp:115-129](), [src/loader.cpp:490-559]()

### Frame Cache Configuration

The frame cache system automatically determines optimal cache size based on available system memory and trajectory characteristics:

- **Cache Size**: Clamped between 4MB minimum and 25% of physical RAM
- **Frame Estimation**: Based on `atom_count × 3 × sizeof(float)` per frame
- **Cache Frames**: `MIN(total_frames, max_cache_frames)`

Sources: [src/loader.cpp:599-607]()

## Unified Format Interface

VIAMD provides a unified interface for accessing both molecule and trajectory formats through common API functions.

### Format Enumeration Interface

```mermaid
graph LR
    subgraph "Public Interface"
        COUNT["loader_count()"]
        NAMES["loader_names()"]
        EXTS["loader_extensions()"]
    end
    
    subgraph "Internal Tables"
        TABLE["table_entry_t"]
        NAME_ARRAY["name[NUM_ENTRIES]"]
        EXT_ARRAY["ext[NUM_ENTRIES]"]
        MOL_ARRAY["mol_loader[NUM_ENTRIES]"]
        TRAJ_ARRAY["traj_loader[NUM_ENTRIES]"]
    end
    
    COUNT --> TABLE
    NAMES --> NAME_ARRAY
    EXTS --> EXT_ARRAY
    
    TABLE --> NAME_ARRAY
    TABLE --> EXT_ARRAY
    TABLE --> MOL_ARRAY
    TABLE --> TRAJ_ARRAY
```

Sources: [src/loader.cpp:218-301](), [src/loader.cpp:363-373]()

The system maintains a unified table structure that maps format names, extensions, and loader implementations, enabling consistent access to format information across the application.

## Sample Data and Testing

While specific sample data files are not visible in the current codebase analysis, VIAMD's comprehensive format support suggests it can handle standard molecular dynamics and structural biology datasets. The loader system is designed to work with:

- **Protein structures** from the Protein Data Bank (PDB format)
- **Molecular dynamics trajectories** from simulation packages like Gromacs
- **Quantum chemistry calculations** through VeloxChem integration
- **Molecular dynamics simulations** from LAMMPS

The robust error handling and validation in the loader system ensures reliable processing of real-world molecular data files with varying formats and quality.

Sources: [src/loader.cpp:1-684]()