# Format Conversion System

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/chainreader2.cpp](src/chainreader2.cpp)
- [src/chainreader2.h](src/chainreader2.h)
- [src/cif.cpp](src/cif.cpp)
- [src/convert.cpp](src/convert.cpp)
- [src/pdbchain.cpp](src/pdbchain.cpp)
- [src/pdbchain.h](src/pdbchain.h)

</details>



The Format Conversion System provides comprehensive conversion capabilities between multiple protein structure data formats. This system handles the ingestion, processing, and output of protein chain data in formats including PDB, CIF, CAL, BCA, and FASTA. It serves as the primary data preprocessing pipeline for the reseek structural search engine.

For information about the core alignment algorithms that process converted data, see [Core Alignment Engine](#3). For details about database search operations using converted formats, see [Database Search System](#4).

## System Overview

The format conversion system is implemented primarily through the `cmd_convert()` function and supporting classes. It employs a multi-threaded architecture to efficiently process large datasets while maintaining data integrity through mutex-protected operations.

## Core Architecture

### Conversion Pipeline

```mermaid
graph TB
    subgraph "Input Layer"
        A[PDBFileScanner] --> B[ChainReader2]
        B --> C["PDB Files"]
        B --> D["CIF Files"] 
        B --> E["CAL Files"]
        B --> F["BCA Files"]
    end
    
    subgraph "Processing Layer"
        G["ThreadBody()"] --> H["PDBChain Objects"]
        H --> I["Format Validation"]
        I --> J["Chain Length Filtering"]
        J --> K["Feature Extraction"]
    end
    
    subgraph "Output Layer"
        L["CAL Format"] --> M["ToCal()"]
        N["FASTA Format"] --> O["ToFasta()"]
        P["BCA Format"] --> Q["BCAData::WriteChain()"]
        R["PDB Format"] --> S["ToPDB()"]
        T["Feature FASTA"] --> U["DSS Feature Extraction"]
    end
    
    A --> G
    K --> L
    K --> N
    K --> P
    K --> R
    K --> T
```

The conversion pipeline processes input files through a state machine implemented in `ChainReader2`, converts them to `PDBChain` objects, and outputs them in the requested formats.

Sources: [src/convert.cpp:248-376](), [src/chainreader2.cpp:90-184]()

### Threading Model

```mermaid
graph TB
    subgraph "Main Thread"
        A["cmd_convert()"] --> B["ThreadCount = GetRequestedThreadCount()"]
        B --> C["Create Worker Threads"]
    end
    
    subgraph "Worker Threads"
        D["ThreadBody(ThreadIndex)"] --> E["ChainReader2::GetNext()"]
        E --> F["Process PDBChain"]
        F --> G["Mutex-Protected Output"]
    end
    
    subgraph "Shared Resources"
        H["PDBFileScanner"] --> I["s_ptrFS"]
        J["Output Files"] --> K["s_fCal, s_fFasta, s_fMultiPDB"]
        L["Statistics"] --> M["s_Converted, s_TooShort, s_InputCount"]
    end
    
    C --> D
    D --> H
    G --> J
    G --> L
    
    subgraph "Synchronization"
        N["s_LockStats"] --> O["Statistics Updates"]
        P["s_LockCal"] --> Q["CAL Output"]
        R["s_LockFasta"] --> S["FASTA Output"]
        T["s_LockBCA"] --> U["BCA Output"]
    end
    
    G --> N
    G --> P
    G --> R
    G --> T
```

The system uses multiple worker threads that share a common file scanner and synchronize access to output files and statistics through dedicated mutexes.

Sources: [src/convert.cpp:74-246](), [src/convert.cpp:315-325]()

## Format Support Matrix

| Input Format | Extension | Reader Method | Output Formats |
|--------------|-----------|---------------|----------------|
| PDB | `.pdb`, `.pdb.gz`, `.ent`, `.ent.gz` | `GetFirst_PDB()` | CAL, FASTA, BCA, PDB, Feature FASTA |
| CIF/mmCIF | `.cif`, `.cif.gz`, `.mmcif`, `.mmcif.gz` | `GetFirst_CIF()` | CAL, FASTA, BCA, PDB, Feature FASTA |
| CAL | `.cal` | `GetFirst_CAL()` | CAL, FASTA, BCA, PDB, Feature FASTA |
| BCA | `.bca` | `GetFirst_BCA()` | CAL, FASTA, BCA, PDB, Feature FASTA |

Sources: [src/chainreader2.cpp:49-88]()

## Core Data Structures

### PDBChain Class

```mermaid
classDiagram
    class PDBChain {
        +string m_Label
        +string m_Seq
        +vector~float~ m_Xs
        +vector~float~ m_Ys
        +vector~float~ m_Zs
        +uint m_Idx
        +vector~string~ m_Lines
        +GetSeqLength() uint
        +FromPDBLines(Label, Lines, SaveLines) bool
        +ToCal(FILE*) void
        +ToFasta(FILE*) void
        +ToPDB(FILE*, TruncateAtZ) void
        +ToFeatureFasta(FILE*, DSS&, FEATURE) void
        +GetXYZ(Pos, x, y, z) void
        +Reverse() void
        +Flip() void
    }
    
    class ChainReader2 {
        +STATE m_State
        +PDBFileScanner* m_ptrFS
        +BCAData m_BCA
        +LineReader2 m_LR
        +Open(FileName) void
        +GetNext() PDBChain*
        +GetFirst_PDB(FN) PDBChain*
        +GetFirst_CIF(FN) PDBChain*
        +GetFirst_CAL(FN) PDBChain*
        +GetFirst_BCA(FN) PDBChain*
    }
    
    class BCAData {
        +Open(FileName) void
        +WriteChain(PDBChain&) void
        +ReadChain(Index, PDBChain&) void
        +GetChainCount() uint64
        +Close() void
    }
    
    ChainReader2 --> PDBChain : creates
    PDBChain --> BCAData : serializes to
```

The `PDBChain` class serves as the central data structure, containing both sequence information and 3D coordinates. It provides methods for conversion to all supported output formats.

Sources: [src/pdbchain.h:10-91](), [src/pdbchain.cpp:110-498]()

### State Machine Implementation

```mermaid
stateDiagram-v2
    [*] --> STATE_Closed
    STATE_Closed --> STATE_PendingFile : Open()
    STATE_PendingFile --> STATE_ReadingPDBFile : .pdb file
    STATE_PendingFile --> STATE_ReadingCIFFile : .cif file
    STATE_PendingFile --> STATE_ReadingCALFile : .cal file
    STATE_PendingFile --> STATE_ReadingBCAFile : .bca file
    STATE_ReadingPDBFile --> STATE_PendingFile : file complete
    STATE_ReadingCIFFile --> STATE_PendingFile : file complete
    STATE_ReadingCALFile --> STATE_PendingFile : file complete
    STATE_ReadingBCAFile --> STATE_PendingFile : file complete
    STATE_PendingFile --> [*] : no more files
```

The `ChainReader2` class implements a state machine that handles the sequential processing of multiple files and formats within each file.

Sources: [src/chainreader2.h:12-21](), [src/chainreader2.cpp:116-184]()

## Format-Specific Processing

### CAL Format Processing

CAL (C-Alpha List) format stores protein chains as tab-separated values with amino acid and coordinates:

```
>102l
M    43.619  -1.924  8.869
N    40.445  -0.876  10.670
I    38.254   2.240  11.220
```

The `GetNext_CAL()` method processes these files line by line, extracting amino acid sequences and 3D coordinates.

Sources: [src/chainreader2.cpp:234-288]()

### CIF Format Processing

CIF (Crystallographic Information Format) parsing involves:

1. **Parser State Machine**: `PS_WaitingForLoop` → `PS_AtLoop` → `PS_InFieldList` → `PS_InATOMs` → `PS_Finished`
2. **Field Mapping**: Dynamic field index resolution using `FieldToIdx` map
3. **Required Fields**: `_atom_site.auth_asym_id`, `_atom_site.label_atom_id`, `_atom_site.Cartn_x/y/z`

Sources: [src/cif.cpp:124-310]()

### BCA Format Processing

BCA (Binary C-Alpha) format provides efficient storage for large datasets:

- **Binary serialization** of coordinate data
- **Random access** capability through `ChainIdx_BCA`
- **Compact storage** using 16-bit integer coordinates via `CoordToIC()` conversion

Sources: [src/chainreader2.cpp:204-222](), [src/pdbchain.cpp:423-471]()

## Feature Extraction

### DSS Feature Processing

When outputting feature FASTA, the system uses the `DSS` class for structural feature extraction:

```mermaid
graph LR
    A["PDBChain"] --> B["DSS::Init()"]
    B --> C["Feature Calculation"]
    C --> D["GetFeature(FEATURE, Pos)"]
    D --> E["GetFeatureChar()"]
    E --> F["Feature FASTA Output"]
    
    subgraph "Feature Types"
        G["FEATURE_SS3"]
        H["FEATURE_NENSS3"] 
        I["FEATURE_RENDist4"]
        J["FEATURE_Mu"]
    end
    
    C --> G
    C --> H
    C --> I
    C --> J
```

The `GetFeatureFromCmdLine()` function maps command-line alphabet specifications to internal feature types.

Sources: [src/convert.cpp:34-72](), [src/convert.cpp:185-203]()

## Error Handling and Statistics

The system maintains comprehensive statistics and error tracking:

- **Format Errors**: Tracked via `ChainReader2::m_CRGlobalFormatErrors`
- **Chain Filtering**: Minimum length filtering with `MinChainLength`
- **Progress Reporting**: Thread-safe progress updates with statistics
- **Label Filtering**: Optional filtering by specific chain labels

### Statistics Tracking

```mermaid
graph TB
    subgraph "Global Statistics"
        A["s_InputCount"] --> B["Total chains processed"]
        C["s_OutputCount"] --> D["Chains meeting criteria"]
        E["s_TooShort"] --> F["Chains below minimum length"]
        G["s_Converted"] --> H["Successfully converted chains"]
    end
    
    subgraph "Thread Safety"
        I["s_LockStats"] --> J["Mutex protection"]
        J --> A
        J --> C
        J --> E
        J --> G
    end
    
    subgraph "Error Tracking"
        K["ChainReader2::m_CRGlobalFormatErrors"] --> L["Format parsing errors"]
        M["Label filtering"] --> N["Missing chains report"]
    end
```

Sources: [src/convert.cpp:89-108](), [src/convert.cpp:327-368]()

## Command-Line Interface

The format conversion system integrates with the broader command-line interface supporting:

- **Input specification**: Single files or directories via `g_Arg1`
- **Output format selection**: Multiple simultaneous output formats
- **Feature extraction**: Configurable alphabet types for feature FASTA
- **Threading control**: Automatic thread count determination
- **Filtering options**: Chain length, label filtering, coordinate transformations

Key options processed by `cmd_convert()`:
- `opt(cal)`, `opt(fasta)`, `opt(bca)` - Output file specifications
- `opt(minchainlength)` - Minimum chain length filter
- `opt(alpha)` - Feature alphabet for feature FASTA
- `opt(labels)`, `opt(label)` - Chain label filtering

Sources: [src/convert.cpp:248-376]()

---