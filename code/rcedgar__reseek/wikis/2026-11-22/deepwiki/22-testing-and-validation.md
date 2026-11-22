# Testing and Validation

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [test_data/dom_scopid.tsv](test_data/dom_scopid.tsv)
- [test_results/success_list.txt](test_results/success_list.txt)
- [test_scripts/check_scop40.py](test_scripts/check_scop40.py)
- [test_scripts/scop40.py](test_scripts/scop40.py)

</details>



This document covers the comprehensive testing and validation framework for the reseek protein structure search system. The testing infrastructure focuses on performance benchmarking, statistical validation, and quality assurance procedures to ensure search accuracy and reliability.

For information about the benchmarking analysis tools, see [Analysis and Benchmarking](#7). For details about the core alignment algorithms being tested, see [Core Alignment Engine](#3).

## Testing Framework Overview

The reseek testing system implements a multi-layered validation approach combining automated performance benchmarking, statistical analysis, and continuous integration testing. The framework validates search sensitivity, specificity, and computational performance across different algorithm configurations.

```mermaid
graph TB
    subgraph "Test Infrastructure"
        A[check_scop40.py] --> B[scop40.py]
        C[success_list.txt] --> D["Version Tracking"]
        E["Test Scripts"] --> F["Automated Execution"]
    end
    
    subgraph "Validation Targets"
        G["Fast Mode"] --> H["Performance Metrics"]
        I["Sensitive Mode"] --> H
        J["Very Sensitive Mode"] --> H
        K["E-value Calibration"] --> H
    end
    
    subgraph "Benchmark Data"
        L["SCOP40 Database"] --> M["Gold Standard"]
        N["Domain Classifications"] --> M
        O["Test Queries"] --> M
    end
    
    subgraph "Output Validation"
        P["ROC Analysis"] --> Q["Quality Metrics"]
        R["Sensitivity Curves"] --> Q
        S["Statistical Tests"] --> Q
    end
    
    A --> G
    A --> I
    A --> J
    A --> K
    
    B --> L
    B --> N
    B --> O
    
    H --> P
    H --> R
    H --> S
    
    D --> F
    F --> A
    Q --> C
```

**Test Architecture Overview**

The testing framework operates through coordinated Python scripts that execute reseek with different parameter configurations and validate results against known benchmarks.

Sources: [test_scripts/check_scop40.py:1-55](), [test_scripts/scop40.py:1-571](), [test_results/success_list.txt:1-25]()

## SCOP40 Benchmarking System

The primary validation system uses the SCOP40 benchmark, a gold standard dataset for protein structure classification. The `Scop40` class provides comprehensive evaluation capabilities for measuring search performance across different classification levels.

```mermaid
graph LR
    subgraph "SCOP40 Evaluation Pipeline"
        A["Query Results"] --> B["scop40.py"]
        C["Domain Mapping"] --> B
        D["SCOP Classifications"] --> B
        
        B --> E["TP/FP Classification"]
        E --> F["Statistical Analysis"]
        F --> G["Performance Metrics"]
    end
    
    subgraph "Classification Levels"
        H["Family Level"] --> I["fam1"]
        J["Superfamily Level"] --> K["sf2/sf3/sf4"]
        L["Fold Level"] --> M["fold5/fold6"]
    end
    
    subgraph "Performance Measures"
        N["Sensitivity (TPR)"] --> O["SEPQ Metrics"]
        P["Specificity"] --> O
        Q["ROC Area"] --> O
        R["Precision"] --> O
    end
    
    I --> E
    K --> E
    M --> E
    
    G --> N
    G --> P
    G --> Q
    G --> R
```

**SCOP40 Benchmark Architecture**

The benchmark system evaluates protein structure search results against hierarchical SCOP classifications to measure true positive and false positive rates at different stringency levels.

### Key Validation Components

| Component | Class/Function | Purpose |
|-----------|----------------|---------|
| Benchmark Controller | `Scop40` | Main evaluation class for SCOP40 analysis |
| Classification Logic | `is_tp()` | Determines true/false positives by SCOP level |
| Performance Metrics | `eval_sorted()` | Calculates sensitivity and specificity |
| Statistical Analysis | `get_summary()` | Generates performance summary statistics |

The `Scop40` class supports multiple evaluation levels:
- **fam1**: Family-level classification (most stringent)
- **sf2/sf3/sf4**: Superfamily-level variants
- **fold5/fold6**: Fold-level classification (most permissive)

Sources: [test_scripts/scop40.py:26-427](), [test_scripts/scop40.py:176-247]()

## Performance Validation Metrics

The validation system calculates comprehensive performance metrics to assess search quality across different algorithm configurations.

```mermaid
graph TB
    subgraph "Input Processing"
        A["Search Results TSV"] --> B["read_file()"]
        C["Score Threshold"] --> B
        D["Query/Target Pairs"] --> B
    end
    
    subgraph "Scoring Analysis"
        B --> E["eval_sorted()"]
        F["SCOP Domain Mapping"] --> E
        G["Classification Rules"] --> E
        
        E --> H["TP/FP Counting"]
        H --> I["TPR Calculation"]
        H --> J["FPR Calculation"]
    end
    
    subgraph "Key Metrics"
        K["SEPQ0.1"] --> L["Performance Thresholds"]
        M["SEPQ1"] --> L
        N["SEPQ10"] --> L
        O["ROC Area"] --> L
        P["Precision"] --> L
    end
    
    subgraph "Validation Thresholds"
        Q["Fast Mode Expected"] --> R["0.2107, 0.3144, 0.3882"]
        S["Sensitive Mode Expected"] --> T["0.2173, 0.3411, 0.4745"]
        U["E-value Mode Expected"] --> V["0.2106, 0.2950, 0.2950"]
    end
    
    I --> K
    I --> M
    I --> N
    J --> O
    I --> P
    
    L --> Q
    L --> S
    L --> U
```

**Performance Metrics Calculation Pipeline**

The system processes search results through statistical analysis to generate standardized performance measures for algorithm validation.

### Critical Performance Thresholds

The validation system enforces minimum performance requirements:

```python
# Expected performance thresholds from check_scop40.py
FAST_MODE_THRESHOLDS = {
    'SEPQ0.1': 0.2107,  # Sensitivity at 0.1 false positives per query
    'SEPQ1': 0.3144,    # Sensitivity at 1 false positive per query  
    'SEPQ10': 0.3882    # Sensitivity at 10 false positives per query
}
```

The test framework validates that each algorithm mode meets or exceeds these performance benchmarks, with a tolerance of -0.01 for regression detection.

Sources: [test_scripts/check_scop40.py:44-50](), [test_scripts/scop40.py:249-427]()

## Automated Testing Infrastructure

The testing system maintains automated validation through structured test execution and result tracking.

```mermaid
graph LR
    subgraph "Test Execution Flow"
        A["Test Runner"] --> B["check_scop40.py"]
        B --> C["Algorithm Modes"]
        C --> D["reseek Execution"]
        D --> E["Result Validation"]
    end
    
    subgraph "Result Processing"
        F["scop40-fast.tsv"] --> G["Fast Mode Analysis"]
        H["scop40-sensitive.tsv"] --> I["Sensitive Mode Analysis"]
        J["scop40-evalue1.tsv"] --> K["E-value Mode Analysis"]
    end
    
    subgraph "Success Tracking"
        L["success_list.txt"] --> M["Version History"]
        N["Build Hash"] --> M
        O["Timestamp"] --> M
        P["Test Status"] --> M
    end
    
    subgraph "Quality Gates"
        Q["Performance Thresholds"] --> R["Pass/Fail Decision"]
        S["Regression Detection"] --> R
        T["Statistical Validation"] --> R
    end
    
    E --> F
    E --> H
    E --> J
    
    G --> Q
    I --> Q
    K --> Q
    
    R --> L
    M --> A
```

**Automated Test Execution and Tracking**

The testing infrastructure automatically executes benchmark tests and tracks results over time to detect performance regressions.

### Test Results Format

The `success_list.txt` file maintains a chronological record of successful test runs:

| Field | Description | Example |
|-------|-------------|---------|
| Version | Software version with build hash | `reseekv2.6.i86linux64[a4334f7]` |
| Timestamp | Test execution time | `2025-07-09/08:28:10` |
| Status | Test outcome tracking | Implicit success if listed |

The system tracks 25 successful test runs spanning from version 1.0 to 2.6, demonstrating continuous validation across major releases.

Sources: [test_results/success_list.txt:1-25](), [test_scripts/check_scop40.py:10-54]()

## Statistical Validation Framework

The testing system implements comprehensive statistical analysis to ensure robust performance evaluation.

```mermaid
graph TB
    subgraph "Statistical Analysis Components"
        A["eval_sorted()"] --> B["Hit Classification"]
        C["Domain Mapping"] --> B
        D["Score Sorting"] --> B
        
        B --> E["TP/FP Accumulation"]
        E --> F["TPR Calculation"]
        E --> G["FPR Calculation"]
        E --> H["Precision Calculation"]
    end
    
    subgraph "Performance Curves"
        I["plot_tprs[]"] --> J["ROC Curve Data"]
        K["plot_fprs[]"] --> J
        L["plot_epqs[]"] --> J
        M["plot_scores[]"] --> J
        N["plot_precisions[]"] --> J
    end
    
    subgraph "Key Statistics"
        O["roc_area()"] --> P["AUC Calculation"]
        Q["sens_to_firstfp"] --> R["First FP Sensitivity"]
        S["tpr_at_fpepq*"] --> T["Threshold Metrics"]
    end
    
    subgraph "Validation Logic"
        U["is_tp()"] --> V["Classification Rules"]
        W["SCOP Hierarchy"] --> V
        X["Domain Relationships"] --> V
    end
    
    F --> I
    G --> K
    H --> N
    
    J --> O
    J --> Q
    J --> S
    
    V --> B
    P --> T
    R --> T
```

**Statistical Validation Architecture**

The framework provides detailed statistical analysis including ROC curves, precision-recall metrics, and threshold-based performance measures.

### Classification Logic

The `is_tp()` method implements hierarchical classification rules:

- **Family Level (fam1)**: Same family = TP, different fold = FP, same fold = ignore
- **Superfamily Level (sf2)**: Same superfamily = TP, different = FP
- **Fold Level (fold5/fold6)**: Same fold = TP, different = FP

This hierarchical approach enables evaluation at multiple stringency levels, from strict family-based classification to permissive fold-based matching.

Sources: [test_scripts/scop40.py:176-247](), [test_scripts/scop40.py:249-427](), [test_scripts/scop40.py:460-468]()

## Quality Assurance Procedures

The testing framework enforces quality standards through automated validation and regression detection.

| Quality Check | Implementation | Threshold |
|---------------|---------------|-----------|
| Performance Regression | `check_scop40.py` error detection | -0.01 tolerance |
| Statistical Validation | ROC analysis and AUC calculation | Mode-specific targets |
| Data Integrity | Sort order validation | Score monotonicity |
| Version Tracking | Build hash and timestamp logging | Continuous integration |

The system automatically fails tests that fall below performance thresholds, providing immediate feedback on algorithm changes that may degrade search quality.

Sources: [test_scripts/check_scop40.py:28-54](), [test_scripts/scop40.py:301-305]()