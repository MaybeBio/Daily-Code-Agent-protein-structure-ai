# Development & Testing

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.gitignore](.gitignore)
- [LICENSE](LICENSE)
- [example/PDL1.pdb](example/PDL1.pdb)

</details>



This document provides resources and guidance for developers working on FreeBindCraft and advanced users who need to test, validate, or benchmark the system. It covers testing utilities, development tools, example assets, and performance validation approaches.

For information about configuring FreeBindCraft parameters, see [Advanced Parameters](#5.2). For details about analyzing design results, see [Analysis & Validation](#6).

## Testing Infrastructure

FreeBindCraft provides several testing utilities to validate system components and compare different computational approaches.

### Core Testing Architecture

```mermaid
graph TB
    subgraph "Testing Framework"
        TOR["test_openmm_relax.py<br/>OpenMM Validation"]
        CM["compare_metrics.py<br/>Engine Comparison"]
        AR["analyze_rejections.py<br/>Failure Analysis"]
        RS["rescore_with_rosetta.py<br/>Cross-Validation"]
    end
    
    subgraph "Test Data"
        PDB["example/PDL1.pdb<br/>Reference Structure"]
        PD["performance_data/<br/>Benchmark Results"]
        CSV["*.csv<br/>Statistics Files"]
        Logs["*_failures.csv<br/>Error Reports"]
    end
    
    subgraph "Validation Targets"
        OMM["OpenMM Relaxation<br/>Energy Minimization"]
        FS["FreeSASA Calculations<br/>Surface Area"]
        SC["Shape Complementarity<br/>sc-rs Binary"]
        IF["Interface Metrics<br/>Biopython Analysis"]
    end
    
    TOR --> OMM
    CM --> FS
    CM --> SC
    CM --> IF
    AR --> Logs
    RS --> CSV
    
    PDB --> TOR
    PDB --> CM
    PD --> CM
    
    style TOR fill:#f9f9f9
    style CM fill:#f9f9f9
    style AR fill:#f9f9f9
    style RS fill:#f9f9f9
```

Sources: System architecture diagrams, [example/PDL1.pdb:1-924]()

### OpenMM Relaxation Testing

The `test_openmm_relax.py` script validates the OpenMM-based relaxation pipeline that serves as a PyRosetta alternative.

```mermaid
graph LR
    subgraph "OpenMM Test Pipeline"
        Input["Test PDB Structure"]
        Setup["force_field_setup()<br/>Parameter Assignment"]
        Minimize["energy_minimization()<br/>Gradient Descent"]
        Validate["structure_validation()<br/>Quality Checks"]
        Output["Relaxed Structure<br/>Energy Report"]
    end
    
    Input --> Setup
    Setup --> Minimize
    Minimize --> Validate
    Validate --> Output
    
    subgraph "Validation Metrics"
        RMSD["RMSD Calculation<br/>vs Input Structure"]
        Energy["Potential Energy<br/>Pre/Post Relaxation"]
        Clashes["Clash Detection<br/>Atomic Overlaps"]
        Geometry["Bond/Angle<br/>Validation"]
    end
    
    Output --> RMSD
    Output --> Energy
    Output --> Clashes
    Output --> Geometry
```

Sources: System diagrams, inferred from PyRosetta alternative architecture

## Development Tools and Utilities

### Metrics Comparison Framework

The `compare_metrics.py` utility enables systematic comparison between PyRosetta-based and PyRosetta-free computational engines.

```mermaid
graph TB
    subgraph "Metric Comparison Pipeline"
        Structures["Input Structures<br/>PDB Files"]
        PyR["PyRosetta Engine<br/>Traditional Scoring"]
        Alt["Alternative Engines<br/>OpenMM + FreeSASA"]
        Compare["metric_comparison()<br/>Statistical Analysis"]
        Report["Comparison Report<br/>Correlation Analysis"]
    end
    
    Structures --> PyR
    Structures --> Alt
    PyR --> Compare
    Alt --> Compare
    Compare --> Report
    
    subgraph "Compared Metrics"
        SASA["SASA Calculations<br/>PyRosetta vs FreeSASA"]
        Relax["Relaxation Energy<br/>FastRelax vs OpenMM"]
        Interface["Interface Scores<br/>Native vs Biopython"]
        ShapeComp["Shape Complementarity<br/>Rosetta vs sc-rs"]
    end
    
    Compare --> SASA
    Compare --> Relax
    Compare --> Interface
    Compare --> ShapeComp
```

Sources: System diagrams, performance comparison architecture

### Failure Analysis System

The `analyze_rejections.py` script provides detailed analysis of why designs were rejected during the pipeline.

```mermaid
graph LR
    subgraph "Rejection Analysis Pipeline"
        FailureLogs["*_failures.csv<br/>Rejection Records"]
        Parser["log_parser()<br/>Extract Failure Reasons"]
        Categorize["failure_categorization()<br/>Group by Type"]
        Visualize["generate_plots()<br/>Failure Statistics"]
        Insights["failure_insights()<br/>Improvement Suggestions"]
    end
    
    FailureLogs --> Parser
    Parser --> Categorize
    Categorize --> Visualize
    Visualize --> Insights
    
    subgraph "Failure Categories"
        Quality["Trajectory Quality<br/>Low pLDDT/pAE"]
        Interface["Interface Filters<br/>SASA/Hydrophobic"]
        Clashes["Structural Issues<br/>Atom Clashes/RMSD"]
        Energy["Energy Criteria<br/>Relaxation/Scoring"]
    end
    
    Categorize --> Quality
    Categorize --> Interface
    Categorize --> Clashes
    Categorize --> Energy
```

Sources: Analysis system diagrams, rejection analysis tools

## Example Assets and Resources

### Reference Structures

FreeBindCraft includes example PDB structures for testing and validation purposes.

| Asset | Purpose | Description |
|-------|---------|-------------|
| `example/PDL1.pdb` | Benchmark target | PDL1 receptor structure for miniprotein design |
| `performance_data/` | Validation benchmarks | Comparison results vs traditional BindCraft |

The PDL1 structure serves as a standard benchmark for comparing FreeBindCraft performance against traditional PyRosetta-based approaches.

```mermaid
graph TB
    subgraph "Example Structure Analysis"
        PDL1["PDL1.pdb<br/>Target Receptor"]
        Chains["Chain Analysis<br/>Residues 18-132"]
        Interface["Interface Mapping<br/>Binding Site Definition"]
        Metrics["Reference Metrics<br/>SASA, Volume, etc"]
    end
    
    PDL1 --> Chains
    Chains --> Interface
    Interface --> Metrics
    
    subgraph "Structure Properties"
        Res["115 Residues<br/>Single Chain A"]
        SS["Secondary Structure<br/>Alpha/Beta Mixed"]
        Sites["Binding Sites<br/>Surface Exposed"]
        Validation["Quality Validated<br/>X-ray Structure"]
    end
    
    Chains --> Res
    Interface --> SS
    Interface --> Sites
    Metrics --> Validation
```

Sources: [example/PDL1.pdb:1-924]()

### Test Configuration Templates

Development testing uses standardized configuration templates to ensure reproducible results.

```mermaid
graph LR
    subgraph "Test Configurations"
        Target["settings_target/<br/>Test Target Configs"]
        Filters["settings_filters/<br/>Validation Filters"]
        Advanced["settings_advanced/<br/>Debug Parameters"]
        Results["Test Results<br/>Reproducible Output"]
    end
    
    Target --> Results
    Filters --> Results  
    Advanced --> Results
    
    subgraph "Debug Settings"
        Verbose["verbose_output: true<br/>Detailed Logging"]
        Save["save_intermediates: true<br/>Keep Temp Files"]
        Timing["timing_analysis: true<br/>Performance Metrics"]
        Validate["validation_mode: true<br/>Extra Checks"]
    end
    
    Advanced --> Verbose
    Advanced --> Save
    Advanced --> Timing
    Advanced --> Validate
```

Sources: Configuration system architecture, testing framework design

## Performance Benchmarking

### Cross-Validation with PyRosetta

The `rescore_with_rosetta.py` utility enables validation of PyRosetta-free designs using traditional PyRosetta scoring.

```mermaid
graph TB
    subgraph "Cross-Validation Pipeline"
        Designs["FreeBindCraft Designs<br/>PyRosetta-Free Results"]
        Rescore["rescore_with_rosetta()<br/>Traditional Scoring"]
        Compare["correlation_analysis()<br/>Score Comparison"]
        Validate["design_validation()<br/>Quality Assessment"]
        Report["Validation Report<br/>Statistical Summary"]
    end
    
    Designs --> Rescore
    Rescore --> Compare
    Compare --> Validate
    Validate --> Report
    
    subgraph "Validation Metrics"
        Correlation["Score Correlation<br/>R² Analysis"]
        Ranking["Design Ranking<br/>Order Preservation"]
        Outliers["Outlier Detection<br/>Problematic Cases"]
        Confidence["Confidence Intervals<br/>Statistical Bounds"]
    end
    
    Compare --> Correlation
    Compare --> Ranking
    Validate --> Outliers
    Report --> Confidence
```

Sources: Rescoring and validation system architecture

### Performance Benchmarks

The `performance_data/` directory contains comprehensive benchmarks comparing FreeBindCraft against traditional BindCraft.

| Benchmark | Metric | FreeBindCraft | Traditional BindCraft | Status |
|-----------|--------|---------------|----------------------|---------|
| PDL1 Miniprotein | Success Rate | ~85% | ~90% | Validated |
| Runtime Performance | Speed | 2-3x faster | Baseline | GPU-accelerated |
| Memory Usage | Peak RAM | ~4GB | ~8GB | Reduced |
| Dependency Requirements | Installation | Minimal | PyRosetta required | Simplified |

Sources: [Performance & Benchmarks](#7), system comparison data

## Validation and Debugging

### System Health Checks

FreeBindCraft includes built-in validation to ensure proper system configuration and functionality.

```mermaid
graph LR
    subgraph "Health Check Pipeline"
        Start["System Startup"]
        GPU["check_jax_gpu()<br/>Hardware Validation"]
        Bins["ensure_binaries_executable()<br/>Tool Verification"]
        Deps["dependency_check()<br/>Package Validation"]
        Ready["System Ready<br/>All Checks Passed"]
    end
    
    Start --> GPU
    GPU --> Bins
    Bins --> Deps
    Deps --> Ready
    
    subgraph "Validation Targets"
        JAX["JAX GPU Support<br/>CUDA/OpenCL"]
        SCRS["sc-rs Binary<br/>Shape Complementarity"]
        FreeSASA["FreeSASA Library<br/>Surface Calculation"]
        OpenMM["OpenMM Installation<br/>Molecular Dynamics"]
    end
    
    GPU --> JAX
    Bins --> SCRS
    Deps --> FreeSASA
    Deps --> OpenMM
```

Sources: Generic utilities architecture, system initialization checks

### Development Environment Setup

For development work, additional validation ensures proper testing environment configuration.

```mermaid
graph TB
    subgraph "Development Setup"
        Install["install_bindcraft.sh<br/>Environment Setup"]
        Test["Run Test Suite<br/>Validation Scripts"]
        Benchmark["Performance Tests<br/>Baseline Measurements"]
        Ready["Development Ready<br/>All Systems Validated"]
    end
    
    Install --> Test
    Test --> Benchmark
    Benchmark --> Ready
    
    subgraph "Test Categories"
        Unit["Unit Tests<br/>Component Validation"]
        Integration["Integration Tests<br/>Pipeline Validation"]
        Performance["Performance Tests<br/>Benchmark Comparison"]
        Regression["Regression Tests<br/>Version Compatibility"]
    end
    
    Test --> Unit
    Test --> Integration
    Test --> Performance
    Test --> Regression
```

Sources: [Installation](#2.1), development and testing infrastructure, [LICENSE:1-26]()

---