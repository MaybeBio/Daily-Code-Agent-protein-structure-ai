# Analysis & Validation

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [extras/README.md](extras/README.md)

</details>



This document provides an overview of the post-processing and analysis tools available in FreeBindCraft for validating design results and understanding system performance. These tools enable users to analyze rejected designs, compare different computational engines, and validate PyRosetta-free results using traditional metrics.

For detailed guides on specific analysis workflows, see: [Rejection Analysis](#6.1), [Rescoring & Validation](#6.2), and [Interface Metrics Comparison](#6.3).

## Overview

FreeBindCraft provides a comprehensive suite of analysis tools located in the `extras/` directory that support various validation and debugging workflows. These tools are particularly important for understanding the performance differences between PyRosetta-based and PyRosetta-free design approaches, and for troubleshooting design failures.

## Analysis Workflow Architecture

The analysis system follows a modular approach where different tools can be used independently or in combination to validate and understand design results.

### Analysis Tools System Map

```mermaid
graph TB
    subgraph "Design Outputs"
        CSV["CSV Statistics<br/>design_stats.csv"]
        PDB["PDB Structures<br/>*.pdb files"]
        Logs["Failure Logs<br/>rejection details"]
    end
    
    subgraph "Core Analysis Tools"
        AR["analyze_bindcraft_rejections.py<br/>Rejection Analysis"]
        RS["rescore_accepted_with_rosetta.py<br/>PyRosetta Rescoring"]
        CM["compare_interface_metrics_all.py<br/>Multi-Engine Comparison"]
        CB["compare_pyrosetta_bypass_scores.py<br/>PyRosetta vs Bypass"]
    end
    
    subgraph "Testing & Validation"
        TR["test_openmm_relax.py<br/>Relaxation Testing"]
        UL["check_ulimit.sh<br/>System Resource Check"]
    end
    
    subgraph "Analysis Outputs"
        RA["Rejection Analysis<br/>CSV Reports"]
        SC["Score Comparisons<br/>Side-by-side Metrics"]
        VM["Validation Metrics<br/>Engine Performance"]
    end
    
    CSV --> AR
    Logs --> AR
    AR --> RA
    
    CSV --> RS
    PDB --> RS
    RS --> SC
    
    PDB --> CM
    CM --> VM
    
    PDB --> CB
    CSV --> CB
    CB --> SC
    
    PDB --> TR
    TR --> VM
    
    style AR fill:#f9f9f9
    style RS fill:#f9f9f9  
    style CM fill:#f9f9f9
    style CB fill:#f9f9f9
```

Sources: [extras/README.md:1-78]()

## Core Analysis Components

### Rejection Analysis System

The rejection analysis system examines why designs were filtered out during the design process, providing insights into which filters are most restrictive and whether rejections are related to PyRosetta-specific metrics.

```mermaid
graph TB
    subgraph "Input Sources"
        RD["Run Directory<br/>--input-dir"]
        FM["Filter Mode<br/>--filter-mode"]
        FP["Filters Path<br/>--filters-path"]
    end
    
    subgraph "analyze_bindcraft_rejections.py"
        LP["load_rejection_logs()"]
        AF["analyze_filters()"]
        PR["check_pyrosetta_related()"]
        ER["estimate_rank()"]
    end
    
    subgraph "Analysis Outputs"
        FS["Filter Statistics<br/>Most restrictive filters"]
        PV["PyRosetta Violations<br/>Bypass-specific issues"]
        HR["Hypothetical Rankings<br/>Estimated positions"]
    end
    
    RD --> LP
    FM --> AF
    FP --> AF
    
    LP --> AF
    AF --> PR
    PR --> ER
    
    AF --> FS
    PR --> PV
    ER --> HR
```

Sources: [extras/README.md:7-18]()

### Multi-Engine Validation System

The validation system compares results across different computational engines to assess the reliability and consistency of PyRosetta-free alternatives.

```mermaid
graph TB
    subgraph "Computational Engines"
        PyR["PyRosetta Engine<br/>Traditional Scoring"]
        FSA["FreeSASA Engine<br/>SASA Calculations"]
        BiP["Biopython Engine<br/>Structure Analysis"]
    end
    
    subgraph "Comparison Tools"
        CIM["compare_interface_metrics_all.py<br/>Three-way Comparison"]
        CPB["compare_pyrosetta_bypass_scores.py<br/>Two-way Comparison"]
    end
    
    subgraph "Metric Categories"
        SASA["SASA Metrics<br/>Surface Areas"]
        RMSD["RMSD Metrics<br/>Structural Deviation"]
        IF["Interface Metrics<br/>Binding Analysis"]
        SC["Shape Complementarity<br/>Geometric Fit"]
    end
    
    PyR --> CIM
    FSA --> CIM
    BiP --> CIM
    
    PyR --> CPB
    BiP --> CPB
    
    CIM --> SASA
    CIM --> RMSD
    CIM --> IF
    CIM --> SC
    
    CPB --> SASA
    CPB --> IF
```

Sources: [extras/README.md:32-46]()

## Validation Workflow Types

FreeBindCraft supports several validation workflows depending on the analysis needs:

| Workflow Type | Primary Tool | Purpose | Input Requirements |
|---------------|--------------|---------|-------------------|
| Rejection Analysis | `analyze_bindcraft_rejections.py` | Understand design failures | Run directories with rejection logs |
| PyRosetta Rescoring | `rescore_accepted_with_rosetta.py` | Validate PyRosetta-free results | Accepted designs from `--no-pyrosetta` runs |
| Engine Comparison | `compare_interface_metrics_all.py` | Compare computational engines | PDB structures with interface definitions |
| Relaxation Testing | `test_openmm_relax.py` | Test relaxation protocols | Single PDB structure |

Sources: [extras/README.md:7-65]()

### Rescoring and Validation Pipeline

The rescoring system provides a critical validation pathway for designs generated without PyRosetta, allowing users to apply traditional PyRosetta filters to assess design quality.

```mermaid
graph TB
    subgraph "Input Processing"
        NPR["No-PyRosetta Run<br/>--no-pyrosetta results"]
        FLT["Filter Configuration<br/>default|relaxed|design|custom"]
        WRK["Worker Processes<br/>--workers N"]
    end
    
    subgraph "rescore_accepted_with_rosetta.py"
        LP["load_pdb_files()"]
        OFR["optional_fast_relax()"]
        RS["rosetta_scoring()"]
        FC["filter_comparison()"]
        RP["report_generation()"]
    end
    
    subgraph "Output Analysis"
        SM["Side-by-side Metrics<br/>bypass_ vs rosetta_"]
        PF["Pass/Fail Analysis<br/>Filter compliance"]
        FR["Filter Reports<br/>Rejection reasons"]
    end
    
    NPR --> LP
    FLT --> FC
    WRK --> RS
    
    LP --> OFR
    OFR --> RS
    RS --> FC
    FC --> RP
    
    RP --> SM
    RP --> PF
    RP --> FR
```

Sources: [extras/README.md:48-58]()

## System Integration Points

The analysis tools integrate with several core FreeBindCraft components:

- **Configuration System**: Analysis tools read the same filter configurations used during design ([Configuration System](#5))
- **Core Pipeline**: Analysis tools process outputs from `bindcraft.py` runs ([Core Pipeline](#3))
- **PyRosetta Integration**: Rescoring tools interface with PyRosetta utilities ([PyRosetta Integration](#4))
- **PyRosetta Alternatives**: Comparison tools validate alternative implementations ([PyRosetta-Free Alternatives](#4.1))

## Environment and Dependencies

The analysis tools require specific setup considerations:

- Repository root must be importable via `sys.path` modifications
- Binary executables in `functions/` directory (e.g., `dssp`, `DAlphaBall.gcc`, `sc`)
- Automatic executable permissions via `chmod +x` when needed
- Optional PyRosetta installation for rescoring and comparison workflows

Sources: [extras/README.md:67-77]()

---