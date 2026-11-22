# SCOP40 Benchmarking

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/scop40bench.cpp](src/scop40bench.cpp)
- [src/scop40bench.h](src/scop40bench.h)
- [src/scop40benchroc.cpp](src/scop40benchroc.cpp)
- [test_data/dom_scopid.tsv](test_data/dom_scopid.tsv)
- [test_results/success_list.txt](test_results/success_list.txt)
- [test_scripts/check_scop40.py](test_scripts/check_scop40.py)
- [test_scripts/scop40.py](test_scripts/scop40.py)

</details>



This document covers the SCOP40 benchmarking system used for evaluating protein structure search performance in reseek. The system performs ROC analysis against the SCOP40 gold standard database to measure search sensitivity and specificity.

For information about the core alignment engine being benchmarked, see [Core Alignment Engine](#3). For database search implementation details, see [Database Search System](#4).

## System Overview

The SCOP40 benchmarking system evaluates protein structure search algorithms using the Structural Classification of Proteins (SCOP) database as ground truth. It performs comprehensive ROC analysis to generate sensitivity metrics at various error rate thresholds.

### SCOP40Bench Class Architecture

```mermaid
graph TB
    DBSearcher["DBSearcher<br/>Base Class"]
    SCOP40Bench["SCOP40Bench<br/>Benchmarking Engine"]
    DSSAligner["DSSAligner<br/>Alignment Engine"]
    
    subgraph "Domain Classification"
        ParseScopLabel["ParseScopLabel()<br/>Label Parser"]
        DomainMaps["Domain Index Maps<br/>m_DomToIdx, m_SFToIdx"]
        ClassificationLevels["Classification Levels<br/>SF, Fold, Family"]
    end
    
    subgraph "ROC Analysis"
        SetTFs["SetTFs()<br/>True/False Assignment"]
        GetROCSteps["GetROCSteps()<br/>ROC Calculation"]
        ROCMetrics["ROC Metrics<br/>SEPQ0.1, SEPQ1, SEPQ10"]
    end
    
    subgraph "Output Generation"
        WriteSummary["WriteSummary()<br/>Results Output"]
        WriteCurve["WriteCurve()<br/>ROC Curve Data"]
        WriteBit["WriteBit()<br/>Binary Results"]
    end
    
    DBSearcher --> SCOP40Bench
    SCOP40Bench --> DSSAligner
    SCOP40Bench --> ParseScopLabel
    SCOP40Bench --> DomainMaps
    SCOP40Bench --> ClassificationLevels
    SCOP40Bench --> SetTFs
    SCOP40Bench --> GetROCSteps
    SCOP40Bench --> ROCMetrics
    SCOP40Bench --> WriteSummary
    SCOP40Bench --> WriteCurve
    SCOP40Bench --> WriteBit
```

Sources: [src/scop40bench.h:9-178](), [src/scop40bench.cpp:133-144]()

## SCOP Domain Classification System

The system uses hierarchical protein structure classification to determine true and false positives:

### Domain Label Format and Parsing

```mermaid
graph LR
    subgraph "SCOP Label Structure"
        DomainLabel["d1a0o__ /a.1.1.1<br/>Domain/Class.Fold.SF.Family"]
        DomainPart["d1a0o__<br/>Domain ID"]
        ScopPart["a.1.1.1<br/>SCOP Classification"]
    end
    
    subgraph "Parsed Components"
        Class["a<br/>Class"]
        Fold["a.1<br/>Fold"]
        SF["a.1.1<br/>Superfamily"]
        Family["a.1.1.1<br/>Family"]
    end
    
    subgraph "Index Maps"
        DomToIdx["m_DomToIdx<br/>Domain → Index"]
        SFToIdx["m_SFToIdx<br/>SF → Index"]
        FoldToIdx["m_FoldToIdx<br/>Fold → Index"]
    end
    
    DomainLabel --> DomainPart
    DomainLabel --> ScopPart
    ScopPart --> Class
    ScopPart --> Fold
    ScopPart --> SF
    ScopPart --> Family
    
    Class --> DomToIdx
    Fold --> FoldToIdx
    SF --> SFToIdx
    Family --> SFToIdx
```

The `ParseScopLabel` function extracts hierarchical classification from domain labels:

| Level | Format | Example | Description |
|-------|--------|---------|-------------|
| Class | `a` | `a` | Protein class |
| Fold | `a.1` | `a.1` | Structural fold |
| Superfamily | `a.1.1` | `a.1.1` | Superfamily |
| Family | `a.1.1.1` | `a.1.1.1` | Family |

Sources: [src/scop40bench.cpp:57-90](), [src/scop40bench.cpp:29-40]()

### True/False Positive Determination

```mermaid
graph TD
    PairComparison["Domain Pair Comparison<br/>Dom1, Dom2"]
    
    subgraph "Classification Levels"
        SFLevel["m_Level = 'sf'<br/>Superfamily Level"]
        FoldLevel["m_Level = 'fold'<br/>Fold Level"]
        IgnoreLevel["m_Level = 'ignore'<br/>Ignore Same-fold"]
    end
    
    subgraph "Decision Logic"
        SameIdx["Same Index?"]
        DifferentIdx["Different Index?"]
        TPResult["Return 1 (TP)"]
        FPResult["Return 0 (FP)"]
        IgnoreResult["Return -1 (Ignore)"]
    end
    
    PairComparison --> SFLevel
    PairComparison --> FoldLevel
    PairComparison --> IgnoreLevel
    
    SFLevel --> SameIdx
    FoldLevel --> SameIdx
    IgnoreLevel --> SameIdx
    
    SameIdx -->|Yes| TPResult
    SameIdx -->|No| DifferentIdx
    DifferentIdx -->|Yes| FPResult
    DifferentIdx -->|Special Cases| IgnoreResult
```

The `IsT` function determines classification based on the benchmarking level:

```cpp
int SCOP40Bench::IsT(uint DomIdx1, uint DomIdx2) const
{
    if (m_Level == "sf") {
        if (SFIdx1 == SFIdx2) return 1;  // TP
        else return 0;  // FP
    }
    // Similar logic for fold and ignore levels
}
```

Sources: [src/scop40benchroc.cpp:166-216]()

## ROC Analysis and Metrics

### ROC Calculation Workflow

```mermaid
graph TB
    subgraph "Data Preparation"
        StoreScore["StoreScore()<br/>Collect Alignment Scores"]
        SetTFs["SetTFs()<br/>Assign True/False Labels"]
        SetScoreOrder["SetScoreOrder()<br/>Sort by Score"]
    end
    
    subgraph "ROC Step Generation"
        GetROCSteps["GetROCSteps()<br/>Generate ROC Points"]
        CurrentScore["Current Score Threshold"]
        NTP["Count True Positives"]
        NFP["Count False Positives"]
    end
    
    subgraph "Metrics Calculation"
        TPR["TPR = NTP / m_NT<br/>True Positive Rate"]
        EPQ["EPQ = NFP / QueryCount<br/>Errors Per Query"]
        Thresholds["SEPQ Thresholds<br/>0.1, 1.0, 10.0"]
    end
    
    subgraph "Output Generation"
        SmoothROC["SmoothROCSteps()<br/>Smooth Curve"]
        WriteCurve["WriteCurve()<br/>Export Data"]
        WriteSummary["WriteSummary()<br/>Final Metrics"]
    end
    
    StoreScore --> SetTFs
    SetTFs --> SetScoreOrder
    SetScoreOrder --> GetROCSteps
    GetROCSteps --> CurrentScore
    CurrentScore --> NTP
    CurrentScore --> NFP
    NTP --> TPR
    NFP --> EPQ
    TPR --> Thresholds
    EPQ --> Thresholds
    Thresholds --> SmoothROC
    SmoothROC --> WriteCurve
    SmoothROC --> WriteSummary
```

### Key Performance Metrics

The system calculates several standard benchmarking metrics:

| Metric | Description | Calculation |
|--------|-------------|-------------|
| `m_nt_epq0_1` | True positives at EPQ ≤ 0.1 | `GetNTPAtEPQThreshold(0.1)` |
| `m_nt_epq1` | True positives at EPQ ≤ 1.0 | `GetNTPAtEPQThreshold(1.0)` |
| `m_nt_epq10` | True positives at EPQ ≤ 10.0 | `GetNTPAtEPQThreshold(10.0)` |
| `m_nt_firstfp` | Sensitivity to first FP | `GetSens1stFP()` |
| `m_Area` | Area under ROC curve | `GetArea(TPRs, Log10EPQs)` |

Sources: [src/scop40benchroc.cpp:454-513](), [src/scop40bench.cpp:566-585]()

## Benchmarking Process

### Complete Benchmarking Workflow

```mermaid
graph TB
    subgraph "Initialization"
        LoadDB["LoadDB()<br/>Load SCOP40 Database"]
        BuildIndexes["BuildDomSFIndexesFromDBChainLabels()<br/>Build Domain Indexes"]
        SetupParams["Setup()<br/>Initialize Parameters"]
    end
    
    subgraph "Search Execution"
        RunSelf["RunSelf()<br/>All-vs-All Search"]
        OnAln["OnAln()<br/>Process Each Alignment"]
        StoreScore["StoreScore()<br/>Collect Results"]
    end
    
    subgraph "Analysis"
        SetStats["SetStats()<br/>Calculate ROC Statistics"]
        ScanDomHits["ScanDomHits()<br/>Analyze Domain Hits"]
        GetROCSteps["GetROCSteps()<br/>Generate ROC Data"]
    end
    
    subgraph "Output"
        WriteSummary["WriteSummary()<br/>Performance Summary"]
        WriteCurve["WriteCurve()<br/>ROC Curve Data"]
        WriteBit["WriteBit()<br/>Binary Results"]
        WriteOutput["WriteOutput()<br/>Final Results"]
    end
    
    LoadDB --> BuildIndexes
    BuildIndexes --> SetupParams
    SetupParams --> RunSelf
    RunSelf --> OnAln
    OnAln --> StoreScore
    StoreScore --> SetStats
    SetStats --> ScanDomHits
    ScanDomHits --> GetROCSteps
    GetROCSteps --> WriteSummary
    WriteSummary --> WriteCurve
    WriteCurve --> WriteBit
    WriteBit --> WriteOutput
```

### Command Entry Point

The main benchmarking command is `cmd_scop40bench()` which:

1. Loads the SCOP40 database from `.cal` format
2. Initializes `DSSParams` for alignment configuration
3. Executes all-vs-all search using `RunSelf()`
4. Processes results and generates performance metrics
5. Outputs summary statistics and detailed results

Sources: [src/scop40bench.cpp:767-824]()

## Configuration and Scoring

### Scoring Modes

The system supports different scoring interpretations:

```mermaid
graph LR
    subgraph "Score Types"
        EValues["E-values<br/>m_ScoresAreEvalues = true"]
        RawScores["Raw Scores<br/>m_ScoresAreEvalues = false"]
    end
    
    subgraph "Comparison Logic"
        BetterEvalue["Lower E-value is Better<br/>Score1 < Score2"]
        BetterRaw["Higher Raw Score is Better<br/>Score1 > Score2"]
    end
    
    subgraph "Thresholds"
        VeryGood["GetVeryGoodScore()<br/>Best Possible"]
        VeryBad["GetVeryBadScore()<br/>Worst Possible"]
    end
    
    EValues --> BetterEvalue
    RawScores --> BetterRaw
    BetterEvalue --> VeryGood
    BetterRaw --> VeryGood
    BetterEvalue --> VeryBad
    BetterRaw --> VeryBad
```

### Benchmark Levels

The system supports different classification levels via `m_Level`:

- `"sf"` - Superfamily level (default)
- `"fold"` - Fold level
- `"ignore"` - Ignore same-fold different-superfamily pairs

Sources: [src/scop40bench.cpp:376-405](), [src/scop40benchroc.cpp:188-214]()

## Output and Results

### Result Files Generated

| File Type | Function | Description |
|-----------|----------|-------------|
| CVE | `WriteCVE()` | Curve vs E-value data |
| ROC | `ROCStepsToTsv()` | ROC curve points |
| Curve | `WriteCurve()` | Smoothed curve data |
| Summary | `WriteSummary()` | Performance metrics |
| Binary | `WriteBit()` | Compressed results |

### Performance Summary Format

```
SEPQ0.1=0.2107 SEPQ1=0.3144 SEPQ10=0.3882 Area=7.14 secs=120 [git-version]
```

Where:
- `SEPQ0.1` = Sensitivity at 0.1 errors per query
- `SEPQ1` = Sensitivity at 1.0 errors per query  
- `SEPQ10` = Sensitivity at 10.0 errors per query
- `Area` = Area under ROC curve
- `secs` = Execution time

Sources: [src/scop40bench.cpp:587-611](), [src/scop40bench.cpp:660-676]()

## Integration with Test Framework

The benchmarking system integrates with Python test scripts for validation:

### Test Validation Process

```mermaid
graph TB
    subgraph "C++ Benchmarking"
        Scop40Bench["SCOP40Bench<br/>C++ Implementation"]
        WriteSummary["WriteSummary()<br/>Output Metrics"]
        TsvOutput["TSV Output Files<br/>scop40-fast.tsv, etc."]
    end
    
    subgraph "Python Validation"
        CheckScop40["check_scop40.py<br/>Validation Script"]
        Scop40Class["Scop40 Class<br/>Python Implementation"]
        EvalFile["eval_file()<br/>Independent Analysis"]
    end
    
    subgraph "Metrics Comparison"
        ExpectedValues["Expected SEPQ Values<br/>From Previous Runs"]
        ActualValues["Actual SEPQ Values<br/>From Current Run"]
        Validation["Validation Logic<br/>±0.01 Tolerance"]
    end
    
    Scop40Bench --> WriteSummary
    WriteSummary --> TsvOutput
    TsvOutput --> CheckScop40
    CheckScop40 --> Scop40Class
    Scop40Class --> EvalFile
    EvalFile --> ActualValues
    ExpectedValues --> Validation
    ActualValues --> Validation
```

The Python validation ensures consistency across different algorithm modes:
- Fast mode: `SEPQ0.1=0.2107, SEPQ1=0.3144, SEPQ10=0.3882`
- Sensitive mode: `SEPQ0.1=0.2173, SEPQ1=0.3411, SEPQ10=0.4745`
- E-value mode: `SEPQ0.1=0.2106, SEPQ1=0.2950, SEPQ10=0.2950`

Sources: [test_scripts/check_scop40.py:44-50](), [test_scripts/scop40.py:26-468]()

---