# IO Operations

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [python/BioSimSpace/IO/__init__.py](python/BioSimSpace/IO/__init__.py)
- [python/BioSimSpace/IO/_io.py](python/BioSimSpace/IO/_io.py)
- [python/BioSimSpace/Parameters/_Protocol/_protocol.py](python/BioSimSpace/Parameters/_Protocol/_protocol.py)
- [python/BioSimSpace/Parameters/__init__.py](python/BioSimSpace/Parameters/__init__.py)
- [python/BioSimSpace/Parameters/_process.py](python/BioSimSpace/Parameters/_process.py)
- [python/BioSimSpace/Process/_task.py](python/BioSimSpace/Process/_task.py)
- [python/BioSimSpace/Sandpit/Exscientia/IO/_io.py](python/BioSimSpace/Sandpit/Exscientia/IO/_io.py)
- [python/BioSimSpace/Sandpit/Exscientia/Parameters/_Protocol/_protocol.py](python/BioSimSpace/Sandpit/Exscientia/Parameters/_Protocol/_protocol.py)
- [python/BioSimSpace/Sandpit/Exscientia/Parameters/_process.py](python/BioSimSpace/Sandpit/Exscientia/Parameters/_process.py)
- [python/BioSimSpace/Sandpit/Exscientia/_SireWrappers/_molecule.py](python/BioSimSpace/Sandpit/Exscientia/_SireWrappers/_molecule.py)
- [python/BioSimSpace/Sandpit/Exscientia/_SireWrappers/_system.py](python/BioSimSpace/Sandpit/Exscientia/_SireWrappers/_system.py)
- [python/BioSimSpace/Solvent/__init__.py](python/BioSimSpace/Solvent/__init__.py)
- [python/BioSimSpace/_SireWrappers/_molecule.py](python/BioSimSpace/_SireWrappers/_molecule.py)
- [python/BioSimSpace/_SireWrappers/_system.py](python/BioSimSpace/_SireWrappers/_system.py)

</details>



The IO Operations module provides comprehensive functionality for reading and writing molecular data in various file formats. This system serves as the primary interface between external molecular data files and BioSimSpace's internal data structures, enabling seamless import and export of molecular systems.

For information about the core data structures that IO operations create and manipulate, see [Molecule and System Objects](#2.1). For details about physical unit handling in imported data, see [Types and Units System](#2.2).

## Core Functions and Architecture

The IO module is built around several key functions that handle different aspects of molecular data input/output:

```mermaid
graph TB
    subgraph "IO Module Functions"
        readMolecules["readMolecules()"]
        saveMolecules["saveMolecules()"]
        readPDB["readPDB()"]
        fileFormats["fileFormats()"]
        formatInfo["formatInfo()"]
        expand["expand()"]
    end
    
    subgraph "Core Data Structures"
        System["System"]
        Molecule["Molecule"]
        Molecules["Molecules"]
    end
    
    subgraph "External Data Sources"
        Files["Local Files"]
        URLs["Remote URLs"]
        PDB_DB["PDB Database"]
    end
    
    subgraph "File Formats"
        PDB["PDB"]
        AMBER["AMBER (prm7/rst7)"]
        GROMACS["GROMACS (gro/top)"]
        SDF["SDF/MOL2"]
        Others["Other Formats"]
    end
    
    Files --> readMolecules
    URLs --> readMolecules
    PDB_DB --> readPDB
    readPDB --> readMolecules
    
    readMolecules --> System
    readMolecules --> Molecule
    
    System --> saveMolecules
    Molecule --> saveMolecules
    Molecules --> saveMolecules
    
    saveMolecules --> PDB
    saveMolecules --> AMBER
    saveMolecules --> GROMACS
    saveMolecules --> SDF
    saveMolecules --> Others
    
    fileFormats --> formatInfo
```

Sources: [python/BioSimSpace/IO/_io.py:27-36](), [python/BioSimSpace/IO/__init__.py:25-41]()

## File Format Support

BioSimSpace leverages Sire's extensive file format support, providing access to numerous molecular file formats through a unified interface:

```mermaid
graph LR
    subgraph "Format Detection"
        Parser["Sire MoleculeParser"]
        Formats["_formats_dict"]
        Info["Format Information"]
    end
    
    subgraph "Supported Formats"
        PDB_Format["PDB"]
        AMBER_Format["AMBER (prm7/rst7/top/crd)"]
        GROMACS_Format["GROMACS (gro/top)"]
        MOL2_Format["MOL2"]
        SDF_Format["SDF"]
        XYZ_Format["XYZ"]
        Other_Formats["20+ Other Formats"]
    end
    
    Parser --> Formats
    Formats --> Info
    
    Formats --> PDB_Format
    Formats --> AMBER_Format
    Formats --> GROMACS_Format
    Formats --> MOL2_Format
    Formats --> SDF_Format
    Formats --> XYZ_Format
    Formats --> Other_Formats
```

The format information is captured at module initialization and stored in `_formats_dict` for efficient lookup. Users can query supported formats using `fileFormats()` and get detailed descriptions with `formatInfo()`.

Sources: [python/BioSimSpace/IO/_io.py:89-111](), [python/BioSimSpace/IO/_io.py:154-202]()

## Reading Operations

### Primary Reading Function

The `readMolecules()` function serves as the main entry point for loading molecular data:

| Parameter | Type | Description |
|-----------|------|-------------|
| `files` | `str` or `list[str]` | File paths or URLs to read |
| `make_whole` | `bool` | Unwrap molecules split across periodic boundaries |
| `rotate_box` | `bool` | Align box vectors with coordinate axes |
| `reduce_box` | `bool` | Reduce box vectors |
| `show_warnings` | `bool` | Display parsing warnings |
| `download_dir` | `str` | Directory for downloaded files |
| `property_map` | `dict` | Custom property name mappings |

```mermaid
graph TD
    subgraph "Input Validation"
        ValidateFiles["Validate File Paths"]
        ValidateParams["Validate Parameters"]
        GlobExpansion["Expand Wildcards"]
    end
    
    subgraph "File Processing"
        CheckExists["Check File Existence"]
        DownloadURLs["Download Remote Files"]
        SetPropertyMap["Configure Property Map"]
    end
    
    subgraph "Sire Integration"
        PatchSireLoad["_patch_sire_load()"]
        SireSystem["Sire System Object"]
        WrapSystem["BioSimSpace System"]
    end
    
    subgraph "Post-Processing"
        AddFileFormat["Add File Format Property"]
        RemoveSharedProps["Remove Shared Properties"]
        RotateBox["Apply Box Rotation"]
        ReduceBox["Apply Box Reduction"]
    end
    
    ValidateFiles --> ValidateParams
    ValidateParams --> GlobExpansion
    GlobExpansion --> CheckExists
    CheckExists --> DownloadURLs
    DownloadURLs --> SetPropertyMap
    SetPropertyMap --> PatchSireLoad
    PatchSireLoad --> SireSystem
    SireSystem --> WrapSystem
    WrapSystem --> AddFileFormat
    AddFileFormat --> RemoveSharedProps
    RemoveSharedProps --> RotateBox
    RotateBox --> ReduceBox
```

Sources: [python/BioSimSpace/IO/_io.py:345-591](), [python/BioSimSpace/IO/_io.py:500-507]()

### PDB-Specific Reading

The `readPDB()` function provides specialized handling for Protein Data Bank files and IDs:

```mermaid
graph TB
    subgraph "PDB Input Types"
        PDBID["PDB ID (e.g., '1a3n')"]
        PDBFile["Local PDB File"]
        PDBURL["PDB URL"]
    end
    
    subgraph "Processing Pipeline"
        Download["Download from RCSB"]
        pdb4amber["pdb4amber Processing"]
        ReadMolecules["readMolecules()"]
    end
    
    subgraph "Configuration"
        AmberTools["AmberTools Detection"]
        WorkDir["Working Directory"]
        PropertyMap["Property Mapping"]
    end
    
    PDBID --> Download
    PDBFile --> pdb4amber
    PDBURL --> Download
    
    Download --> pdb4amber
    pdb4amber --> ReadMolecules
    
    AmberTools --> pdb4amber
    WorkDir --> pdb4amber
    PropertyMap --> ReadMolecules
```

Sources: [python/BioSimSpace/IO/_io.py:205-342](), [python/BioSimSpace/IO/_io.py:300-337]()

## Writing Operations

### Molecular System Export

The `saveMolecules()` function handles export of molecular systems to various file formats:

| Parameter | Type | Description |
|-----------|------|-------------|
| `filebase` | `str` | Base name for output files |
| `system` | `System/Molecule/Molecules` | Molecular data to save |
| `fileformat` | `str` or `list[str]` | Target file format(s) |
| `match_water` | `bool` | Update water naming conventions |
| `property_map` | `dict` | Custom property name mappings |

```mermaid
graph TD
    subgraph "Input Processing"
        ValidateInput["Validate Input Types"]
        NormalizeSystem["Convert to System Object"]
        ParseFormats["Parse Format Specifications"]
    end
    
    subgraph "Format Validation"
        CheckFormats["Validate Format Names"]
        FormatDict["_formats_dict Lookup"]
        CreateFilebase["Create Output Directory"]
    end
    
    subgraph "File Generation"
        CheckCache["Check File Cache"]
        SetPropertyMap["Configure Property Map"]
        WaterTopology["Set Water Topology"]
        WriteFiles["Write to Disk"]
    end
    
    subgraph "Post-Processing"
        UpdateCache["Update File Cache"]
        ReturnPaths["Return File Paths"]
    end
    
    ValidateInput --> NormalizeSystem
    NormalizeSystem --> ParseFormats
    ParseFormats --> CheckFormats
    CheckFormats --> FormatDict
    FormatDict --> CreateFilebase
    CreateFilebase --> CheckCache
    CheckCache --> SetPropertyMap
    SetPropertyMap --> WaterTopology
    WaterTopology --> WriteFiles
    WriteFiles --> UpdateCache
    UpdateCache --> ReturnPaths
```

Sources: [python/BioSimSpace/IO/_io.py:594-970](), [python/BioSimSpace/IO/_io.py:750-840]()

## Advanced Features

### Property Mapping System

Property maps allow users to customize how molecular properties are referenced, enabling flexible naming schemes:

```mermaid
graph LR
    subgraph "Standard Properties"
        Coordinates["coordinates"]
        Charge["charge"]
        Mass["mass"]
        Velocity["velocity"]
    end
    
    subgraph "User Mapping"
        PropertyMap["property_map = {...}"]
        CustomNames["Custom Property Names"]
    end
    
    subgraph "Internal Processing"
        MapLookup["Property Map Lookup"]
        SireProperties["Sire Property System"]
    end
    
    Coordinates --> PropertyMap
    Charge --> PropertyMap
    Mass --> PropertyMap
    Velocity --> PropertyMap
    
    PropertyMap --> CustomNames
    CustomNames --> MapLookup
    MapLookup --> SireProperties
```

Sources: [python/BioSimSpace/IO/_io.py:387-391](), [python/BioSimSpace/IO/_io.py:732-736]()

### File Caching System

BioSimSpace implements a caching mechanism to avoid redundant file operations:

```mermaid
graph TB
    subgraph "Cache Operations"
        CacheActive["_cache_active()"]
        CheckCache["_check_cache()"]
        UpdateCache["_update_cache()"]
    end
    
    subgraph "Cache Management"
        EnableCache["enableCache()"]
        DisableCache["disableCache()"]
        ClearCache["clearCache()"]
    end
    
    subgraph "File Operations"
        ReadOperation["Read Operation"]
        WriteOperation["Write Operation"]
        CacheHit["Cache Hit"]
        CacheMiss["Cache Miss"]
    end
    
    CacheActive --> CheckCache
    CheckCache --> CacheHit
    CheckCache --> CacheMiss
    CacheMiss --> ReadOperation
    CacheMiss --> WriteOperation
    WriteOperation --> UpdateCache
    
    EnableCache --> CacheActive
    DisableCache --> CacheActive
    ClearCache --> CacheActive
```

Sources: [python/BioSimSpace/IO/_io.py:69-71](), [python/BioSimSpace/IO/_io.py:751-764]()

### URL and Remote File Support

The IO system supports downloading files from remote URLs and handles various compression formats:

```mermaid
graph TB
    subgraph "URL Processing"
        URLDetection["URL Detection (http/www)"]
        SireResolve["Sire _resolve_path()"]
        DownloadDir["Download Directory"]
    end
    
    subgraph "File Handling"
        LocalFiles["Local Files"]
        RemoteFiles["Remote Files"]
        CompressedFiles["Compressed Files (.bz2)"]
    end
    
    subgraph "Path Expansion"
        GlobExpansion["Wildcard Expansion"]
        PathNormalization["Path Normalization"]
        FileValidation["File Existence Check"]
    end
    
    URLDetection --> SireResolve
    SireResolve --> DownloadDir
    DownloadDir --> RemoteFiles
    
    LocalFiles --> GlobExpansion
    RemoteFiles --> GlobExpansion
    CompressedFiles --> GlobExpansion
    
    GlobExpansion --> PathNormalization
    PathNormalization --> FileValidation
```

Sources: [python/BioSimSpace/IO/_io.py:450-457](), [python/BioSimSpace/IO/_io.py:494-497]()

---