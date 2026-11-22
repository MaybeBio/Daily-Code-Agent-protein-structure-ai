# Data Processing and Formats

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/chainreader2.cpp](src/chainreader2.cpp)
- [src/chainreader2.h](src/chainreader2.h)
- [src/cif.cpp](src/cif.cpp)
- [src/convert.cpp](src/convert.cpp)
- [src/msta_scores.cpp](src/msta_scores.cpp)
- [src/pdbchain.cpp](src/pdbchain.cpp)
- [src/pdbchain.h](src/pdbchain.h)
- [src/seqdb.cpp](src/seqdb.cpp)
- [src/seqdb.h](src/seqdb.h)

</details>



This document covers the data processing pipeline and file format handling systems in reseek. It describes the supported input/output formats, core data structures for representing protein chains, and the unified processing architecture that converts between different structural biology file formats.

For specific details about the conversion commands and utilities, see [Format Conversion System](#5.1). For information about the internal data structures and chain management, see [Sequence and Structure Data](#5.2).

## Supported File Formats

Reseek supports multiple structural biology file formats for both input and output:

| Format | Extension | Type | Description |
|--------|-----------|------|-------------|
| PDB | `.pdb`, `.ent` | Text | Legacy Protein Data Bank format |
| CIF/mmCIF | `.cif`, `.mmcif` | Text | Modern crystallographic format |
| CAL | `.cal` | Text | C-alpha coordinate format |
| BCA | `.bca` | Binary | Binary C-alpha format |
| FASTA | `.fasta`, `.fa` | Text | Sequence-only format |

The system handles both compressed (`.gz`) and uncompressed versions of these formats automatically.

Sources: [src/chainreader2.cpp:49-87](), [src/convert.cpp:248-376]()

## Core Data Structures

### PDBChain Class

The `PDBChain` class serves as the universal internal representation for protein structures:

```mermaid
classDiagram
    class PDBChain {
        +string m_Label
        +string m_Seq
        +vector~float~ m_Xs
        +vector~float~ m_Ys
        +vector~float~ m_Zs
        +vector~string~ m_Lines
        +uint m_Idx
        +GetSeqLength() uint
        +ToCal(FILE*)
        +ToFasta(FILE*)
        +ToPDB(FILE*)
        +FromPDBLines(vector~string~)
        +FromCalLines(vector~string~)
        +GetDist(uint, uint) float
        +GetXYZ(uint, float&, float&, float&)
    }
```

Key components:
- **Sequence data**: `m_Seq` stores the amino acid sequence
- **Coordinates**: `m_Xs`, `m_Ys`, `m_Zs` store C-alpha coordinates
- **Metadata**: `m_Label` for chain identification, `m_Lines` for original file content
- **Conversion methods**: `ToCal()`, `ToFasta()`, `ToPDB()` for format output

Sources: [src/pdbchain.h:10-95](), [src/pdbchain.cpp:1-498]()

### SeqDB Class

The `SeqDB` class manages collections of sequences for analysis:

```mermaid
classDiagram
    class SeqDB {
        +vector~string~ m_Labels
        +vector~string~ m_Seqs
        +map~string,uint~ m_LabelToIndex
        +bool m_IsAligned
        +uint m_ColCount
        +AddSeq(string, string) uint
        +GetSeq(uint) string
        +GetLabel(uint) string
        +GetSeqByLabel(string) bool
        +FromFasta(string, bool)
        +GetSeqCount() uint
        +IsAligned() bool
    }
```

Sources: [src/seqdb.h:9-62](), [src/seqdb.cpp:9-373]()

## Processing Pipeline Architecture

The data processing pipeline follows a multi-stage architecture:

```mermaid
flowchart TD
    A["Input Files<br/>(PDB, CIF, CAL, BCA, FASTA)"] --> B["PDBFileScanner"]
    B --> C["ChainReader2"]
    C --> D["Format-Specific Parsers"]
    D --> E["PDBChain Objects"]
    E --> F["Processing/Analysis"]
    F --> G["Output Writers"]
    G --> H["Output Files<br/>(Multiple Formats)"]
    
    D --> D1["GetNext_PDB()"]
    D --> D2["GetNext_CIF()"]
    D --> D3["GetNext_CAL()"]
    D --> D4["GetNext_BCA()"]
    
    G --> G1["ToCal()"]
    G --> G2["ToFasta()"]
    G --> G3["ToPDB()"]
    G --> G4["BCAData.WriteChain()"]
```

### Key Processing Components

1. **PDBFileScanner**: Discovers and queues input files
2. **ChainReader2**: Universal file reader with format detection
3. **Format-specific parsers**: Handle PDB, CIF, CAL, BCA formats
4. **PDBChain**: Universal internal representation
5. **Output writers**: Generate multiple output formats

Sources: [src/chainreader2.cpp:21-367](), [src/convert.cpp:74-246]()

## ChainReader2 State Machine

The `ChainReader2` class implements a state machine for processing different file formats:

```mermaid
stateDiagram-v2
    [*] --> STATE_Closed
    STATE_Closed --> STATE_PendingFile : Open()
    STATE_PendingFile --> STATE_ReadingCALFile : .cal file
    STATE_PendingFile --> STATE_ReadingBCAFile : .bca file
    STATE_PendingFile --> STATE_ReadingPDBFile : .pdb/.ent file
    STATE_PendingFile --> STATE_ReadingCIFFile : .cif/.mmcif file
    STATE_ReadingCALFile --> STATE_PendingFile : End of file
    STATE_ReadingBCAFile --> STATE_PendingFile : End of file
    STATE_ReadingPDBFile --> STATE_PendingFile : End of file
    STATE_ReadingCIFFile --> STATE_PendingFile : End of file
    STATE_PendingFile --> STATE_Closed : No more files
```

Each state corresponds to a specific file format parser with dedicated `GetNext_*()` methods.

Sources: [src/chainreader2.h:12-21](), [src/chainreader2.cpp:116-184]()

## Multi-threaded Conversion System

The conversion system uses a thread-safe architecture for high-performance processing:

```mermaid
flowchart TD
    A["cmd_convert()"] --> B["Thread Pool Creation"]
    B --> C["ThreadBody() instances"]
    C --> D["Shared Resources"]
    D --> E["Output Files"]
    
    D --> D1["s_fCal (CAL output)"]
    D --> D2["s_fFasta (FASTA output)"]
    D --> D3["s_fMultiPDB (PDB output)"]
    D --> D4["s_ptrBCA (BCA output)"]
    
    C --> C1["Thread 0"]
    C --> C2["Thread 1"]
    C --> C3["Thread N"]
    
    subgraph "Synchronization"
        M1["s_LockCal"]
        M2["s_LockFasta"]
        M3["s_LockMultiPDB"]
        M4["s_LockBCA"]
        M5["s_LockStats"]
    end
```

Thread safety is ensured through mutex locks for shared resources:
- `s_LockCal`: Protects CAL file writing
- `s_LockFasta`: Protects FASTA file writing  
- `s_LockMultiPDB`: Protects multi-PDB file writing
- `s_LockBCA`: Protects BCA file writing
- `s_LockStats`: Protects progress statistics

Sources: [src/convert.cpp:8-33](), [src/convert.cpp:314-325]()

## Format-Specific Processing

### PDB Format Processing

PDB files are processed using `GetFieldsFromATOMLine()` to extract:
- Atom coordinates from columns 31-54
- Amino acid type from columns 18-20
- Chain identifier from column 22
- Atom name filtering (CA atoms only)

Sources: [src/pdbchain.cpp:231-263]()

### CIF Format Processing

CIF/mmCIF files use a tabular parser that:
1. Identifies `loop_` sections with `_atom_site.*` fields
2. Maps field names to column indices
3. Extracts data from ATOM records
4. Handles model numbers and chain identifiers

Sources: [src/cif.cpp:133-309]()

### CAL Format Processing

CAL format uses a simple tab-delimited structure:
```
>chain_label
AA    X_coord    Y_coord    Z_coord
M     43.619     -1.924     8.869
N     40.445     -0.876     10.670
```

Sources: [src/chainreader2.cpp:224-288]()

### BCA Format Processing

BCA format provides binary storage for efficient access:
- Uses `BCAData` class for reading/writing
- Supports random access by chain index
- Compressed coordinate representation

Sources: [src/chainreader2.cpp:204-222]()

## Output Generation

The system supports multiple output formats simultaneously:

| Output Type | Implementation | Thread Safety |
|-------------|----------------|---------------|
| CAL | `PDBChain::ToCal()` | `s_LockCal` |
| FASTA | `PDBChain::ToFasta()` | `s_LockFasta` |
| Multi-PDB | `PDBChain::ToPDB()` | `s_LockMultiPDB` |
| BCA | `BCAData::WriteChain()` | `s_LockBCA` |
| Feature FASTA | DSS feature extraction | `s_LockFasta` |

Sources: [src/convert.cpp:157-238](), [src/pdbchain.cpp:152-188]()

---