# File Loading System

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/app/application.cpp](src/app/application.cpp)
- [src/color_utils.cpp](src/color_utils.cpp)
- [src/color_utils.h](src/color_utils.h)
- [src/event.cpp](src/event.cpp)
- [src/loader.cpp](src/loader.cpp)
- [src/loader.h](src/loader.h)

</details>



## Purpose and Scope

The File Loading System is responsible for parsing and loading molecular data from various file formats into VIAMD's internal data structures. It handles both static molecular structure files and dynamic trajectory files, providing a unified interface for accessing molecular coordinates, topology, and metadata. The system includes intelligent format detection, frame caching for trajectory data, and periodic boundary condition (PBC) handling.

For information about the core molecular data structures used by the loaded data, see [Molecular Data Structures and Display](#2.4). For details about the task system used for parallel loading operations, see [Task System and Parallel Processing](#4.1).

## Architecture Overview

The File Loading System follows a modular architecture with separate handling for molecule and trajectory data, built around format-specific loader APIs and a centralized management system.

```mermaid
graph TB
    subgraph "File Format Detection"
        FD["File Extension Analysis<br/>mol_loader_from_ext()<br/>traj_loader_from_ext()"]
        LS["LoaderState<br/>Configuration & Arguments"]
    end
    
    subgraph "Molecule Loading"
        ML["Molecule Loaders<br/>md_molecule_loader_i"]
        PDB_MOL["PDB Molecule API<br/>md_pdb_molecule_api()"]
        GRO_MOL["GRO Molecule API<br/>md_gro_molecule_api()"]
        XYZ_MOL["XYZ Molecule API<br/>md_xyz_molecule_api()"]
        CIF_MOL["mmCIF Molecule API<br/>md_mmcif_molecule_api()"]
        LAM_MOL["LAMMPS Molecule API<br/>md_lammps_molecule_api()"]
    end
    
    subgraph "Trajectory Loading"
        TL["Trajectory Loaders<br/>md_trajectory_loader_i"]
        PDB_TRAJ["PDB Trajectory API<br/>md_pdb_trajectory_loader()"]
        XTC_TRAJ["XTC Trajectory API<br/>md_xtc_trajectory_loader()"]
        TRR_TRAJ["TRR Trajectory API<br/>md_trr_trajectory_loader()"]
        XYZ_TRAJ["XYZ Trajectory API<br/>md_xyz_trajectory_loader()"]
        LAM_TRAJ["LAMMPS Trajectory API<br/>md_lammps_trajectory_loader()"]
    end
    
    subgraph "Trajectory Management"
        LT["LoadedTrajectory<br/>Instance Management"]
        FC["Frame Cache<br/>md_frame_cache_t"]
        PBC["PBC Processing<br/>Recentering & Wrapping"]
    end
    
    subgraph "Data Storage"
        LM["LoadedMolecule<br/>Static Arrays[8]"]
        LTArray["LoadedTrajectory<br/>Static Arrays[8]"]
    end
    
    FD --> LS
    LS --> ML
    LS --> TL
    
    ML --> PDB_MOL
    ML --> GRO_MOL
    ML --> XYZ_MOL
    ML --> CIF_MOL
    ML --> LAM_MOL
    
    TL --> PDB_TRAJ
    TL --> XTC_TRAJ
    TL --> TRR_TRAJ
    TL --> XYZ_TRAJ
    TL --> LAM_TRAJ
    
    TL --> LT
    LT --> FC
    LT --> PBC
    
    ML --> LM
    LT --> LTArray
```

Sources: [src/loader.cpp:29-113](), [src/loader.h:27-63]()

## Supported File Formats

The system supports multiple molecular file formats through dedicated loader APIs, organized into molecule (static structure) and trajectory (dynamic coordinate) categories.

| Format | Extension(s) | Molecule Loader | Trajectory Loader | Description |
|--------|-------------|----------------|-------------------|-------------|
| PDB | `.pdb` | ✓ | ✓ | Standard Protein Data Bank format |
| GRO | `.gro` | ✓ | ✗ | Gromacs structure format |
| XTC | `.xtc` | ✗ | ✓ | Gromacs compressed trajectory |
| TRR | `.trr` | ✗ | ✓ | Gromacs lossless trajectory |
| XYZ | `.xyz`, `.xmol`, `.arc` | ✓ | ✓ | Simple coordinate format |
| mmCIF | `.cif` | ✓ | ✗ | PDBx/mmCIF crystallographic format |
| LAMMPS | `.data` | ✓ | ✗ | LAMMPS data file |
| LAMMPS Trajectory | `.lammpstrj` | ✗ | ✓ | LAMMPS trajectory format |
| VeloxChem | `.out`, `.h5` | ✓ | ✗ | Quantum chemistry output (optional) |

Sources: [src/loader.cpp:42-76](), [src/loader.cpp:88-113](), [src/loader.cpp:232-299]()

## Loader Detection and Initialization

The system automatically detects appropriate loaders based on file extensions and initializes the necessary state for loading operations.

```mermaid
graph TD
    FP["File Path Input"]
    EE["extract_ext()<br/>Extract File Extension"]
    MLD["mol_loader_from_ext()<br/>Find Molecule Loader"]
    TLD["traj_loader_from_ext()<br/>Find Trajectory Loader"]
    PC["Preload Check<br/>mol_loader_preload_check()"]
    LS["LoaderState<br/>Configuration Result"]
    
    FP --> EE
    EE --> MLD
    EE --> TLD
    MLD --> PC
    TLD --> PC
    PC --> LS
    
    subgraph "Special Cases"
        LAMMPS["LAMMPS Format Detection<br/>md_lammps_atom_format_from_file()"]
        DIALOG["RequiresDialogue Flag<br/>User Input Needed"]
    end
    
    PC --> LAMMPS
    LAMMPS --> DIALOG
```

The `init_loader_state()` function serves as the main entry point for loader initialization:

```cpp
bool init_loader_state(LoaderState* state, str_t file_path, md_allocator_i* alloc)
```

This function analyzes the file extension, determines compatible loaders, and performs format-specific preload checks. For LAMMPS files, it attempts automatic format detection and sets flags if user dialogue is required.

Sources: [src/loader.cpp:330-352](), [src/loader.cpp:190-210]()

## Molecule Loading

Molecule loading handles static structural data through format-specific APIs that implement the `md_molecule_loader_i` interface.

```mermaid
graph LR
    subgraph "Loader Selection"
        EXT["File Extension"]
        API["mol_loader_api[]<br/>Format-Specific APIs"]
    end
    
    subgraph "Loader APIs"
        PDB["md_pdb_molecule_api()"]
        GRO["md_gro_molecule_api()"]
        XYZ["md_xyz_molecule_api()"]
        CIF["md_mmcif_molecule_api()"]
        LAMMPS["md_lammps_molecule_api()"]
        VLX["md_vlx_molecule_api()"]
    end
    
    subgraph "Output"
        MOL["md_molecule_t<br/>Parsed Structure"]
        LM["LoadedMolecule<br/>Tracking Entry"]
    end
    
    EXT --> API
    API --> PDB
    API --> GRO
    API --> XYZ
    API --> CIF
    API --> LAMMPS
    API --> VLX
    
    PDB --> MOL
    GRO --> MOL
    XYZ --> MOL
    CIF --> MOL
    LAMMPS --> MOL
    VLX --> MOL
    
    MOL --> LM
```

The system maintains a static array of loaded molecules with simple key-based tracking:

```cpp
static LoadedMolecule loaded_molecules[8] = {};
static int64_t num_loaded_molecules = 0;
```

Each `LoadedMolecule` contains a unique key and allocator reference for memory management.

Sources: [src/loader.cpp:66-76](), [src/loader.cpp:115-158](), [src/loader.cpp:375-397]()

## Trajectory Loading and Caching

Trajectory loading involves more complex processing due to the dynamic nature of coordinate data and the need for efficient frame access through caching.

```mermaid
graph TD
    subgraph "Trajectory Opening"
        OF["traj::open_file()"]
        TL["Trajectory Loader<br/>md_trajectory_loader_i"]
        IT["Internal Trajectory<br/>loader->create()"]
        AC["Atom Count Validation<br/>mol->atom.count == traj_atom_count"]
    end
    
    subgraph "Cache Initialization"
        CS["Cache Size Calculation<br/>VIAMD_FRAME_CACHE_SIZE"]
        FS["Frame Size Estimation<br/>atom_count * 3 * sizeof(float)"]
        NF["Max Cache Frames<br/>cache_size / frame_size"]
        CI["md_frame_cache_init()"]
    end
    
    subgraph "Trajectory Wrapper"
        LT["LoadedTrajectory Instance"]
        TW["Trajectory Wrapper<br/>md_trajectory_i"]
        RI["Recenter Indices<br/>md_array(int32_t)"]
    end
    
    OF --> TL
    TL --> IT
    IT --> AC
    AC --> CS
    CS --> FS
    FS --> NF
    NF --> CI
    CI --> LT
    LT --> TW
    LT --> RI
```

The `LoadedTrajectory` structure encapsulates all trajectory-related state:

```cpp
struct LoadedTrajectory {
    uint64_t key;
    const md_molecule_t* mol;
    md_trajectory_loader_i* loader;
    md_trajectory_i* traj;
    md_frame_cache_t cache;
    md_allocator_i* alloc;
    md_array(int32_t) recenter_indices;
};
```

Frame cache size is dynamically calculated based on available system memory and trajectory characteristics, with a default target of `VIAMD_FRAME_CACHE_SIZE` megabytes.

Sources: [src/loader.cpp:120-129](), [src/loader.cpp:561-615](), [src/loader.cpp:599-607]()

## Frame Loading with PBC Handling

Frame loading implements sophisticated caching and periodic boundary condition (PBC) processing to ensure efficient access to trajectory data.

```mermaid
graph TD
    subgraph "Frame Request"
        LF["load_frame()<br/>Frame Index Request"]
        CC["Cache Check<br/>md_frame_cache_find_or_reserve()"]
        CH["Cache Hit"]
        CM["Cache Miss"]
    end
    
    subgraph "Cache Miss Processing"
        TLF["md_trajectory_load_frame()<br/>Load from Disk"]
        FD["Frame Data<br/>Coordinates & Header"]
        PBC["PBC Processing"]
    end
    
    subgraph "PBC Operations"
        RC["Recenter Check<br/>recenter_indices.size > 0"]
        COM["Center of Mass<br/>md_util_com_compute()"]
        PBCW["PBC Wrapping<br/>md_util_pbc()"]
        TRANS["Translation<br/>vec3_batch_translate_inplace()"]
    end
    
    subgraph "Output"
        FH["Frame Header<br/>md_trajectory_frame_header_t"]
        COORD["Coordinates<br/>float* x, y, z"]
        LR["Lock Release<br/>md_frame_cache_frame_lock_release()"]
    end
    
    LF --> CC
    CC --> CH
    CC --> CM
    CM --> TLF
    TLF --> FD
    FD --> PBC
    PBC --> RC
    RC --> COM
    COM --> PBCW
    PBCW --> TRANS
    
    CH --> FH
    TRANS --> FH
    FH --> COORD
    COORD --> LR
```

The frame loading process includes automatic recentering based on user-defined atom selections:

```cpp
bool set_recenter_target(md_trajectory_i* traj, const md_bitfield_t* atom_mask)
```

When recentering is enabled, the system computes the center of mass of the selected atoms and translates all coordinates to center the system within the periodic box.

Sources: [src/loader.cpp:490-559](), [src/loader.cpp:520-538](), [src/loader.cpp:639-656]()

## Management and Lifecycle

The system provides comprehensive management functions for both molecules and trajectories, including memory cleanup and cache control.

| Function Category | Key Functions | Purpose |
|------------------|---------------|---------|
| Loader Discovery | `loader_count()`, `loader_names()`, `loader_extensions()` | Enumerate available loaders |
| State Management | `init_loader_state()`, `free_loader_state()` | Configure loading parameters |
| Trajectory Control | `traj::open_file()`, `traj::close()` | Trajectory lifecycle |
| Cache Management | `traj::clear_cache()`, `traj::num_cache_frames()` | Cache optimization |
| Recentering | `traj::set_recenter_target()`, `traj::has_recenter_target()` | PBC handling |

The system maintains static arrays with fixed capacity for loaded objects:

```cpp
static LoadedMolecule loaded_molecules[8] = {};
static LoadedTrajectory loaded_trajectories[8] = {};
```

This design provides predictable memory usage and efficient lookup operations while supporting typical use cases with multiple concurrent molecular systems.

Sources: [src/loader.cpp:131-187](), [src/loader.cpp:363-373](), [src/loader.cpp:617-680]()

---