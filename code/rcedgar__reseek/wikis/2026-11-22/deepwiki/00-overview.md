# Overview

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



This document provides a comprehensive technical overview of the Reseek codebase, a high-performance protein structure search and alignment tool. Reseek implements a novel sequence alignment algorithm using a "mega-alphabet" of ~10^11 distinct states to achieve improved sensitivity over existing methods like DALI, TM-align, and Foldseek.

For detailed information about specific subsystems, see the related wiki pages: [Getting Started](#2) covers installation and basic usage, [Core Alignment Engine](#3) documents the central algorithms, [Database Search System](#4) covers multi-threaded search architecture, and [Command-Line Interface](#6) provides complete reference documentation.

## System Architecture

Reseek is organized as a modular C++ application with five primary architectural layers:

```mermaid
graph TB
    subgraph "Command Interface Layer"
        CLI["`reseek_main.cpp`<br/>Main Entry Point"]
        OPTS["`myopts.h`<br/>217+ Configuration Parameters"]
        CMDS["`cmds.h`<br/>69 Commands"]
        USAGE["`usage.h`<br/>Help System"]
    end
    
    subgraph "Core Processing Layer"
        ALIGNER["`DSSAligner`<br/>Central Alignment Engine"]
        PARAMS["`DSSParams`<br/>Algorithm Configuration"]
        SEARCH["`DBSearcher`<br/>Database Search Orchestrator"]
        LOADER["`ProfileLoader`<br/>Multi-threaded Chain Loading"]
    end
    
    subgraph "Data Processing Layer"
        CONVERT["`cmd_convert`<br/>Format Conversion"]
        READER["`ChainReader2`<br/>Universal Format Parser"]
        FILTER["`MuFilter + PostMuFilter`<br/>Two-Stage Filtering"]
        CHAIN["`PDBChain`<br/>Structure Representation"]
    end
    
    subgraph "Output Layer"
        FIELDS["`UserField System`<br/>Configurable Output Columns"]
        FORMATS["`Multiple Output Formats`<br/>TSV, FASTA, Alignments"]
    end
    
    subgraph "Analysis Layer"
        BENCH["`SCOP40Bench`<br/>Performance Benchmarking"]
        CALIB["`Calibration System`<br/>Statistical Model Tuning"]
    end
    
    CLI --> OPTS
    CLI --> CMDS
    CLI --> USAGE
    CLI --> ALIGNER
    CLI --> SEARCH
    CLI --> CONVERT
    CLI --> BENCH
    
    ALIGNER --> PARAMS
    SEARCH --> LOADER
    SEARCH --> FILTER
    CONVERT --> READER
    READER --> CHAIN
    FILTER --> ALIGNER
    ALIGNER --> FIELDS
    FIELDS --> FORMATS
    BENCH --> CALIB
    
    style CLI fill:#f9f9f9
    style ALIGNER fill:#f9f9f9
    style SEARCH fill:#f9f9f9
```

Sources: [src/reseek_main.cpp](), [src/myopts.h:1-150](), [src/cmds.h:1-79](), [src/usage.h:1-90]()

## Core Components

### Command System and Configuration

The application uses a sophisticated command and parameter system centered around three key files:

| Component | Purpose | Scale |
|-----------|---------|-------|
| `myopts.h` | Parameter definitions | 217+ parameters across STR_OPT, UNS_OPT, FLT_OPT, FLAG_OPT types |
| `cmds.h` | Command definitions | 69 commands including search, convert, alignpair, benchmarking |
| `usage.h` | Help system | Comprehensive usage documentation |

The parameter system supports string options (`STR_OPT`), unsigned integer options (`UNS_OPT`), floating-point options (`FLT_OPT`), and boolean flags (`FLAG_OPT`).

Sources: [src/myopts.h:1-150](), [src/cmds.h:1-79](), [src/usage.h:1-90]()

### Data Processing Pipeline

```mermaid
graph LR
    subgraph "Input Formats"
        PDB["`PDB Files`<br/>Legacy Format"]
        CIF["`CIF/mmCIF Files`<br/>Modern Standard"]
        CAL["`CAL Files`<br/>C-alpha Coordinates"]
        BCA["`BCA Files`<br/>Binary C-alpha"]
        FASTA["`FASTA Files`<br/>Sequence Data"]
    end
    
    subgraph "Processing Core"
        READER2["`ChainReader2`<br/>Universal Parser"]
        CHAIN2["`PDBChain`<br/>Unified Representation"]
        SEQDB["`SeqDB`<br/>Sequence Management"]
    end
    
    subgraph "Search Pipeline"
        MUKMER["`MuKmerFilter`<br/>K-mer Pre-screening"]
        MUFILTER["`MuFilter`<br/>Fast Initial Filter"]
        POSTMU["`PostMuFilter`<br/>Detailed Alignment"]
        DSSALN["`DSSAligner`<br/>Core Alignment Engine"]
    end
    
    subgraph "Output Generation"
        USERFIELDS["`UserField System`<br/>Configurable Columns"]
        OUTPUTS["`Multiple Formats`<br/>TSV, FASTA, Alignments"]
    end
    
    PDB --> READER2
    CIF --> READER2
    CAL --> READER2
    BCA --> READER2
    FASTA --> READER2
    
    READER2 --> CHAIN2
    READER2 --> SEQDB
    
    CHAIN2 --> MUKMER
    MUKMER --> MUFILTER
    MUFILTER --> POSTMU
    POSTMU --> DSSALN
    
    DSSALN --> USERFIELDS
    USERFIELDS --> OUTPUTS
```

The pipeline implements a multi-stage filtering approach to balance speed and sensitivity, with each stage progressively more computationally intensive but more selective.

Sources: [src/chainreader2.h](), [src/pdbchain.h](), [src/seqdb.h](), [src/mukmerfilter.h](), [src/postmufilter.cpp](), [src/dssaligner.h]()

### Algorithm Modes and Configuration

Reseek provides three primary algorithm modes controlled by the `DSSParams` configuration system:

| Mode | Purpose | Performance Trade-off |
|------|---------|----------------------|
| `--fast` | High-speed searches | Optimized for speed, moderate sensitivity |
| `--sensitive` | Balanced performance | Default mode balancing speed and sensitivity |
| `--verysensitive` | Maximum sensitivity | Comprehensive search, slower execution |

The `DSSParams` class centralizes algorithm configuration, managing feature weights, gap penalties, score matrices, and statistical models.

Sources: [src/dssparams.h](), [src/dssparams.cpp]()

### Output System

The flexible output system uses the `UserField` enumeration to provide configurable column selection:

```mermaid
graph TB
    subgraph "Core Output Fields"
        QUERY["`UF_query`<br/>Query identifier"]
        TARGET["`UF_target`<br/>Target identifier"]
        COORDS["`UF_qlo, UF_qhi, UF_tlo, UF_thi`<br/>Alignment coordinates"]
        STATS["`UF_evalue, UF_pvalue`<br/>Statistical significance"]
    end
    
    subgraph "Alignment Details"
        IDENTITY["`UF_pctid`<br/>Percent identity"]
        CIGAR["`UF_cigar`<br/>CIGAR string"]
        ROWS["`UF_qrow, UF_trow`<br/>Aligned sequences"]
        QUALITY["`UF_aq`<br/>Alignment quality score"]
    end
    
    subgraph "Advanced Metrics"
        LDDT["`UF_lddt`<br/>Local Distance Difference Test"]
        SCORES["`UF_raw, UF_dpscore`<br/>Raw alignment scores"]
        GAPS["`UF_gaps, UF_ids`<br/>Gap and identity counts"]
    end
    
    subgraph "Output Generation"
        WRITER["`DSSAligner::WriteUserField`<br/>Field formatting and output"]
    end
    
    QUERY --> WRITER
    TARGET --> WRITER
    COORDS --> WRITER
    STATS --> WRITER
    IDENTITY --> WRITER
    CIGAR --> WRITER
    ROWS --> WRITER
    QUALITY --> WRITER
    LDDT --> WRITER
    SCORES --> WRITER
    GAPS --> WRITER
```

Default output includes `aq+query+target+evalue+pvalue`, with standard output (`std`) providing `query+target+qlo+qhi+ql+tlo+thi+tl+pctid+evalue`.

Sources: [src/userfields.cpp:1-152](), [src/userfieldnames.h:1-34]()

## Build System and Platform Support

Reseek supports cross-platform compilation with dedicated build configurations:

| Platform | Build Method | Configuration |
|----------|--------------|---------------|
| Linux x86 | `build_linux_x86.bash` | GCC with OpenMP |
| macOS x86 | `build_osx_x86.bash` | Clang with OpenMP |
| Windows | Visual Studio | `reseek.vcxproj` with MSVC |

The Visual Studio project file defines comprehensive build configurations with optimization settings, OpenMP support, and multi-processor compilation enabled.

Sources: [src/reseek.vcxproj:1-564](), [src/reseek.vcxproj.filters:1-874]()

## Performance and Benchmarking

The codebase includes extensive benchmarking infrastructure centered around the SCOP40 benchmark:

```mermaid
graph TB
    subgraph "Benchmarking Infrastructure"
        SCOP40["`SCOP40Bench`<br/>Gold Standard Evaluation"]
        ROC["`ROC Analysis`<br/>Sensitivity/Specificity"]
        CALIB["`Calibration System`<br/>Statistical Model Fitting"]
    end
    
    subgraph "Performance Metrics"
        SENS["`Sensitivity`<br/>True Positive Rate"]
        SPEC["`Specificity`<br/>True Negative Rate"]
        EVAL["`E-value Calibration`<br/>Statistical Significance"]
    end
    
    subgraph "Quality Outputs"
        CURVES["`ROC Curves`<br/>Performance Visualization"]
        REPORTS["`Sensitivity Reports`<br/>Detection Rates"]
        MODELS["`Statistical Models`<br/>Null Distributions"]
    end
    
    SCOP40 --> SENS
    SCOP40 --> SPEC
    ROC --> CURVES
    CALIB --> EVAL
    CALIB --> MODELS
    SENS --> REPORTS
    SPEC --> REPORTS
    EVAL --> REPORTS
```

The benchmarking system measures performance against the SCOP40 superfamily classification, focusing on the regime with false-positive rates <10 per query.

Sources: [src/scop40bench.h](), [src/scop40bench.cpp](), [src/scop40benchroc.cpp]()

## Threading and Memory Management

Reseek implements multi-threaded processing with custom memory management:

- **Threading**: OpenMP-based parallelization controlled by `--threads` parameter
- **Memory**: Custom allocators in `mymalloc.cpp` with platform-specific implementations
- **Database Loading**: `ProfileLoader` class manages multi-threaded chain loading
- **Search**: `DBSearcher` orchestrates parallel database searches

The threading model scales automatically to available CPU cores while providing manual control for performance tuning.

Sources: [src/profileloader.h](), [src/dbsearcher.h](), [src/mymalloc.cpp](), [src/runthreads.cpp]()

---