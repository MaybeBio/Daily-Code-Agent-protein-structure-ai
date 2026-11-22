# Command-Line Interface

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [README.md](README.md)
- [src/cmds.h](src/cmds.h)
- [src/myopts.h](src/myopts.h)
- [src/reseek.vcxproj](src/reseek.vcxproj)
- [src/reseek.vcxproj.filters](src/reseek.vcxproj.filters)
- [src/usage.h](src/usage.h)
- [src/userfieldnames.h](src/userfieldnames.h)
- [src/userfields.cpp](src/userfields.cpp)

</details>



This document provides an overview of the reseek command-line interface architecture, including command dispatch, parameter processing, and output formatting systems. For detailed listings of all available commands and parameters, see [Commands and Options](#6.1). For information about customizable output columns and formats, see [Output Formatting](#6.2).

## Overview

The reseek command-line interface provides a comprehensive system for protein structure search, alignment, and format conversion operations. The CLI is built around a command-dispatch architecture where users specify a primary command followed by various options and parameters. The system supports 69 distinct commands and over 217 configuration parameters, making it highly flexible for diverse bioinformatics workflows.

## Command Architecture

The CLI system is organized around a two-level hierarchy: primary commands that determine the operation type, and options that configure the behavior of those commands.

```mermaid
graph TB
    CLI["reseek CLI Entry Point"]
    
    subgraph "Primary Commands"
        SEARCH["-search<br/>Database Search & Alignment"]
        CONVERT["-convert<br/>Format Conversion"]
        ALIGNPAIR["-alignpair<br/>Pairwise Alignment"]
        OTHER["Other Commands<br/>69 total in cmds.h"]
    end
    
    subgraph "Option Categories"
        STR_OPT["String Options<br/>Input/Output Files"]
        UNS_OPT["Unsigned Options<br/>Numeric Parameters"]
        FLT_OPT["Float Options<br/>Scoring Parameters"]
        FLAG_OPT["Boolean Flags<br/>Mode Switches"]
    end
    
    subgraph "Core Systems"
        MYOPTS["myopts.h<br/>Option Definitions"]
        CMDS["cmds.h<br/>Command Registry"]
        USAGE["usage.h<br/>Help System"]
    end
    
    CLI --> SEARCH
    CLI --> CONVERT
    CLI --> ALIGNPAIR
    CLI --> OTHER
    
    SEARCH --> STR_OPT
    SEARCH --> UNS_OPT
    SEARCH --> FLT_OPT
    SEARCH --> FLAG_OPT
    
    STR_OPT --> MYOPTS
    UNS_OPT --> MYOPTS
    FLT_OPT --> MYOPTS
    FLAG_OPT --> MYOPTS
    
    OTHER --> CMDS
    USAGE --> CLI
```

**Command Dispatch System**

The command system uses a macro-based approach to define available commands. Each command is registered in `cmds.h` using the `C()` macro, which generates the necessary dispatch table entries.

Sources: [src/cmds.h:1-78](), [src/myopts.h:1-150](), [src/usage.h:1-90]()

## Parameter Processing System

The parameter system uses a sophisticated macro-based approach to handle different types of command-line options with type safety and automatic help generation.

```mermaid
graph LR
    subgraph "Option Type Macros"
        STR["STR_OPT<br/>String Parameters"]
        UNS["UNS_OPT<br/>Unsigned Integer Parameters"]
        FLT["FLT_OPT<br/>Floating Point Parameters"]
        FLAG["FLAG_OPT<br/>Boolean Flags"]
    end
    
    subgraph "Parameter Categories"
        IO_PARAMS["I/O Parameters<br/>-input, -output, -db, -fasta"]
        ALGO_PARAMS["Algorithm Parameters<br/>-threads, -evalue, -gapopen"]
        MODE_PARAMS["Mode Parameters<br/>-fast, -sensitive, -verysensitive"]
        DEBUG_PARAMS["Debug Parameters<br/>-verbose, -log, -trace_*"]
    end
    
    subgraph "Processing Pipeline"
        PARSE["Option Parsing"]
        VALIDATE["Parameter Validation"]
        DISPATCH["Command Dispatch"]
    end
    
    STR --> IO_PARAMS
    UNS --> ALGO_PARAMS
    FLT --> ALGO_PARAMS
    FLAG --> MODE_PARAMS
    FLAG --> DEBUG_PARAMS
    
    IO_PARAMS --> PARSE
    ALGO_PARAMS --> PARSE
    MODE_PARAMS --> PARSE
    DEBUG_PARAMS --> PARSE
    
    PARSE --> VALIDATE
    VALIDATE --> DISPATCH
```

**Option Definition System**

The options are defined using four primary macros in `myopts.h`:
- `STR_OPT()` for string parameters like file paths and labels
- `UNS_OPT()` for unsigned integer parameters like thread counts and sizes
- `FLT_OPT()` for floating-point parameters like scoring weights and thresholds
- `FLAG_OPT()` for boolean flags that enable/disable features

Sources: [src/myopts.h:8-64](), [src/myopts.h:66-96](), [src/myopts.h:98-116](), [src/myopts.h:117-145]()

## Output Formatting Architecture

The CLI provides a flexible output formatting system through the UserField mechanism, allowing users to customize which columns appear in their results.

```mermaid
graph TB
    subgraph "UserField System"
        USERFIELD_ENUM["USERFIELD Enum<br/>Field Type Definitions"]
        USERFIELD_NAMES["userfieldnames.h<br/>Field Name Registry"]
        USERFIELD_CODE["userfields.cpp<br/>Field Processing Logic"]
    end
    
    subgraph "Output Field Categories"
        BASIC_FIELDS["Basic Fields<br/>query, target, evalue, pvalue"]
        ALIGNMENT_FIELDS["Alignment Fields<br/>qlo, qhi, tlo, thi, pctid"]
        SEQUENCE_FIELDS["Sequence Fields<br/>qrow, trow, qrowg, trowg"]
        SCORE_FIELDS["Score Fields<br/>aq, ts, dpscore, lddt"]
    end
    
    subgraph "Output Formats"
        TSV["TSV Format<br/>Tabular Output"]
        ALN["ALN Format<br/>Human-readable Alignments"]
        CUSTOM["Custom Columns<br/>-columns parameter"]
    end
    
    USERFIELD_ENUM --> BASIC_FIELDS
    USERFIELD_ENUM --> ALIGNMENT_FIELDS
    USERFIELD_ENUM --> SEQUENCE_FIELDS
    USERFIELD_ENUM --> SCORE_FIELDS
    
    BASIC_FIELDS --> TSV
    ALIGNMENT_FIELDS --> TSV
    SEQUENCE_FIELDS --> ALN
    SCORE_FIELDS --> CUSTOM
    
    USERFIELD_NAMES --> USERFIELD_CODE
    USERFIELD_CODE --> TSV
    USERFIELD_CODE --> ALN
    USERFIELD_CODE --> CUSTOM
```

**Field Processing Pipeline**

The output system converts internal alignment results into user-specified output formats through the `DSSAligner::WriteUserField()` method, which handles formatting and value conversion for each field type.

Sources: [src/userfields.cpp:45-151](), [src/userfieldnames.h:1-34]()

## Usage Patterns

The CLI supports three primary usage patterns, each optimized for different bioinformatics workflows:

| Usage Pattern | Command | Primary Purpose | Key Options |
|---------------|---------|-----------------|-------------|
| Database Search | `-search` | Search query structures against a database | `-db`, `-output`, `-evalue`, `-threads` |
| Format Conversion | `-convert` | Convert between file formats | `-cal`, `-bca`, `-fasta` |
| Pairwise Alignment | `-alignpair` | Align and superpose two structures | `-input2`, `-aln`, `-output` |

**Algorithm Mode Selection**

All search operations require specifying an algorithm mode that balances speed versus sensitivity:

```mermaid
graph LR
    subgraph "Algorithm Modes"
        FAST["-fast<br/>High Speed<br/>Lower Sensitivity"]
        SENSITIVE["-sensitive<br/>Balanced<br/>Default Mode"]
        VERYSENSITIVE["-verysensitive<br/>High Sensitivity<br/>Lower Speed"]
    end
    
    subgraph "Parameter Effects"
        FILTERING["Filtering Thresholds"]
        SCORING["Scoring Parameters"]
        SEARCH_DEPTH["Search Depth"]
    end
    
    FAST --> FILTERING
    SENSITIVE --> FILTERING
    VERYSENSITIVE --> FILTERING
    
    FILTERING --> SCORING
    SCORING --> SEARCH_DEPTH
```

**Input Format Support**

The system supports multiple input formats through a unified interface:

| Format | Extension | Description | Use Case |
|--------|-----------|-------------|----------|
| PDB | `.pdb` | Legacy PDB format | Small datasets, compatibility |
| mmCIF | `.cif`, `.mmcif` | Modern PDB format | Large structures, complete metadata |
| CAL | `.cal` | C-alpha text format | Custom preprocessing |
| BCA | `.bca` | Binary C-alpha format | Large databases, performance |
| Directory | (none) | Directory traversal | Batch processing |

Sources: [src/usage.h:2-89](), [README.md:15-92]()

## Help and Documentation System

The CLI includes a comprehensive help system that provides usage information, parameter descriptions, and example commands. The help text is generated from the same macro definitions used for option processing, ensuring consistency between the implementation and documentation.

Sources: [src/usage.h:2-89](), [README.md:15-92]()

---