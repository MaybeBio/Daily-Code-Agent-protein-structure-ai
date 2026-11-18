# Interface Metrics Comparison

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [extras/compare_interface_metrics_all.py](extras/compare_interface_metrics_all.py)
- [extras/compare_pyrosetta_bypass_scores.py](extras/compare_pyrosetta_bypass_scores.py)
- [extras/test_openmm_relax.py](extras/test_openmm_relax.py)
- [functions/freesasa_naccess.cfg](functions/freesasa_naccess.cfg)

</details>



This document covers the tools and utilities for comparing interface metrics calculated using different computational engines within FreeBindCraft. These tools enable validation of PyRosetta-free alternatives against traditional PyRosetta methods and provide quantitative assessments of agreement between different SASA calculation approaches.

For information about the underlying interface scoring implementations, see [PyRosetta Integration](#4) and [PyRosetta-Free Alternatives](#4.1). For post-design validation workflows, see [Rescoring & Validation](#6.2).

## Overview

FreeBindCraft provides two main comparison utilities that systematically evaluate interface metrics across different computational backends:

- **Dual-engine comparison**: PyRosetta vs Biopython using `compare_pyrosetta_bypass_scores.py`
- **Tri-engine comparison**: PyRosetta vs FreeSASA vs Biopython using `compare_interface_metrics_all.py`

Both tools process collections of PDB files and generate comprehensive CSV outputs with side-by-side metric comparisons, enabling quantitative validation of the PyRosetta-free pathway.

## Comparison Architecture

The interface metrics comparison system operates through a modular architecture that can selectively enable or disable different computational engines based on availability and user preferences.

### Engine Selection Flow

```mermaid
flowchart TD
    Start["PDB Input Directory"] --> CheckPyRosetta["Check PyRosetta Availability"]
    CheckPyRosetta --> PyRosettaAvailable{"PyRosetta Available?"}
    
    PyRosettaAvailable -->|Yes| InitPyRosetta["try_init_pyrosetta()"]
    PyRosettaAvailable -->|No| SkipPyRosetta["Skip PyRosetta Engine"]
    
    InitPyRosetta --> InitSuccess{"Initialization Success?"}
    InitSuccess -->|Yes| EnablePyRosetta["Enable PyRosetta Scoring"]
    InitSuccess -->|No| SkipPyRosetta
    
    EnablePyRosetta --> ScoreEngines["Score with Multiple Engines"]
    SkipPyRosetta --> ScoreEngines
    
    ScoreEngines --> BioPython["score_interface(use_pyrosetta=False)"]
    ScoreEngines --> FreeSASA["pr_alternative_score_interface(sasa_engine='freesasa')"]
    ScoreEngines --> PyRosetta["score_interface(use_pyrosetta=True)"]
    
    BioPython --> CollectResults["Collect Results with Prefixes"]
    FreeSASA --> CollectResults
    PyRosetta --> CollectResults
    
    CollectResults --> OutputCSV["Generate Comparison CSV"]
```

**Sources:** [extras/compare_pyrosetta_bypass_scores.py:55-72](), [extras/compare_interface_metrics_all.py:47-63]()

### Processing Pipeline

```mermaid
flowchart LR
    subgraph Input["Input Processing"]
        PDBDir["PDB Directory"]
        CollectPDBs["collect_pdbs()"]
        PDBFiles["PDB File List"]
    end
    
    subgraph Workers["Parallel Processing"]
        SingleWorker["Sequential Mode<br/>(workers=1)"]
        MultiWorker["Parallel Mode<br/>(ProcessPoolExecutor)"]
    end
    
    subgraph Scoring["Per-PDB Scoring"]
        ScoreOne["score_one_pdb() or<br/>score_all_engines()"]
        EngineA["Engine A Metrics"]
        EngineB["Engine B Metrics"]
        EngineC["Engine C Metrics"]
        ClashRef["Clash Reference Metrics"]
    end
    
    subgraph Output["Output Generation"]
        DataFrame["pandas.DataFrame"]
        CSV["Comparison CSV"]
    end
    
    PDBDir --> CollectPDBs
    CollectPDBs --> PDBFiles
    
    PDBFiles --> SingleWorker
    PDBFiles --> MultiWorker
    
    SingleWorker --> ScoreOne
    MultiWorker --> ScoreOne
    
    ScoreOne --> EngineA
    ScoreOne --> EngineB
    ScoreOne --> EngineC
    ScoreOne --> ClashRef
    
    EngineA --> DataFrame
    EngineB --> DataFrame
    EngineC --> DataFrame
    ClashRef --> DataFrame
    
    DataFrame --> CSV
```

**Sources:** [extras/compare_pyrosetta_bypass_scores.py:149-162](), [extras/compare_interface_metrics_all.py:151-162](), [extras/compare_pyrosetta_bypass_scores.py:208-235]()

## Dual-Engine Comparison

The `compare_pyrosetta_bypass_scores.py` script provides focused comparison between PyRosetta and Biopython-based interface metrics.

### Key Functions

| Function | Purpose | Implementation |
|----------|---------|----------------|
| `score_one_pdb()` | Score single PDB with both engines | [extras/compare_pyrosetta_bypass_scores.py:75-146]() |
| `try_init_pyrosetta()` | Attempt PyRosetta initialization | [extras/compare_pyrosetta_bypass_scores.py:55-72]() |
| `ensure_binaries_executable()` | Make required binaries executable | [extras/compare_pyrosetta_bypass_scores.py:36-53]() |
| `collect_pdbs()` | Gather PDB files from directory | [extras/compare_pyrosetta_bypass_scores.py:149-161]() |

### Usage Pattern

```bash
python compare_pyrosetta_bypass_scores.py \
  --pdb-dir /path/to/pdb/folder \
  --output comparison.csv \
  --binder-chain B \
  --workers 4 \
  --recursive
```

### Output Schema

The dual-engine comparison generates CSV output with the following column structure:

| Column Pattern | Description | Source Engine |
|----------------|-------------|---------------|
| `File` | PDB filename | - |
| `Path` | Full PDB path | - |
| `BinderChain` | Binder chain identifier | - |
| `bypass_*` | Biopython metrics | `score_interface(use_pyrosetta=False)` |
| `rosetta_*` | PyRosetta metrics | `score_interface(use_pyrosetta=True)` |
| `Clashes_AllAtoms` | All-atom clash count | `calculate_clash_score(only_ca=False)` |
| `Clashes_CAOnly` | CA-only clash count | `calculate_clash_score(only_ca=True)` |

**Sources:** [extras/compare_pyrosetta_bypass_scores.py:78-129](), [extras/compare_pyrosetta_bypass_scores.py:131-144]()

## Tri-Engine Comparison

The `compare_interface_metrics_all.py` script extends the comparison to include FreeSASA alongside PyRosetta and Biopython engines.

### Engine-Specific Scoring

```mermaid
flowchart TD
    PDB["Input PDB File"] --> ScoreAll["score_all_engines()"]
    
    ScoreAll --> BioPythonScore["pr_alternative_score_interface()<br/>sasa_engine='biopython'"]
    ScoreAll --> FreeSASAScore["pr_alternative_score_interface()<br/>sasa_engine='freesasa'"]
    ScoreAll --> PyRosettaScore["score_interface()<br/>use_pyrosetta=True"]
    
    BioPythonScore --> BioPythonMetrics["biopython_* columns"]
    FreeSASAScore --> FreeSASAMetrics["freesasa_* columns"]
    PyRosettaScore --> PyRosettaMetrics["rosetta_* columns"]
    
    BioPythonMetrics --> OutputRow["Combined Result Row"]
    FreeSASAMetrics --> OutputRow
    PyRosettaMetrics --> OutputRow
    
    OutputRow --> CSV["Tri-Engine CSV Output"]
```

**Sources:** [extras/compare_interface_metrics_all.py:66-148]()

### Extended Output Schema

The tri-engine comparison produces CSV output with expanded column sets:

| Column Prefix | Engine | SASA Method | Interface Detection |
|---------------|--------|-------------|-------------------|
| `biopython_*` | Biopython | Shrake-Rupley | Distance-based |
| `freesasa_*` | FreeSASA | Lee-Richards | Distance-based |
| `rosetta_*` | PyRosetta | Rosetta SASA | Rosetta interface |

**Sources:** [extras/compare_interface_metrics_all.py:83-130]()

## Parallel Processing Support

Both comparison tools support parallel processing through the `ProcessPoolExecutor` for improved performance on large PDB collections.

### Worker Configuration

```mermaid
graph TB
    WorkerCheck{"workers == 1?"}
    
    WorkerCheck -->|Yes| Sequential["Sequential Processing<br/>Direct function calls<br/>Verbose output"]
    WorkerCheck -->|No| Parallel["Parallel Processing<br/>ProcessPoolExecutor<br/>Batch completion logging"]
    
    Sequential --> ProcessPDB["score_one_pdb() or<br/>score_all_engines()"]
    Parallel --> SubmitJobs["Submit jobs to executor"]
    
    SubmitJobs --> WaitCompletion["as_completed() iterator"]
    WaitCompletion --> CollectResults["Collect results from futures"]
    
    ProcessPDB --> Results["Individual Results"]
    CollectResults --> Results
    
    Results --> DataFrame["pandas.DataFrame"]
```

**Sources:** [extras/compare_pyrosetta_bypass_scores.py:207-235](), [extras/compare_interface_metrics_all.py:210-237]()

## Binary Dependencies

The comparison tools require several external binaries to be executable for complete functionality.

### Required Binaries

| Binary | Purpose | Configuration |
|--------|---------|---------------|
| `dssp` | Secondary structure calculation | Made executable by `ensure_binaries_executable()` |
| `DAlphaBall.gcc` | Cavity/void detection for PyRosetta | Path passed to PyRosetta init |
| `sc` | Shape complementarity calculation | Made executable by `ensure_binaries_executable()` |

### FreeSASA Configuration

FreeSASA engine uses the NACCESS-compatible atom type definitions from `functions/freesasa_naccess.cfg` for consistent SASA calculations across different atom types and residues.

**Sources:** [extras/compare_pyrosetta_bypass_scores.py:36-53](), [extras/compare_interface_metrics_all.py:32-44](), [functions/freesasa_naccess.cfg:1-256]()

## Error Handling and Robustness

The comparison tools implement comprehensive error handling to ensure robust operation across diverse PDB collections.

### Per-Engine Error Isolation

```mermaid
flowchart TD
    StartScoring["Start Engine Scoring"] --> TryEngine["try: Engine Calculation"]
    TryEngine --> EngineSuccess{"Success?"}
    
    EngineSuccess -->|Yes| StoreMetrics["Store Engine Metrics<br/>with engine_ prefix"]
    EngineSuccess -->|No| StoreError["Store Error Message<br/>engine_error column"]
    
    StoreMetrics --> NextEngine["Continue to Next Engine"]
    StoreError --> NextEngine
    
    NextEngine --> AllComplete{"All Engines Done?"}
    AllComplete -->|No| TryEngine
    AllComplete -->|Yes| CompleteRow["Complete Result Row"]
```

This approach ensures that failure in one engine (e.g., PyRosetta unavailable) does not prevent comparison of available engines.

**Sources:** [extras/compare_pyrosetta_bypass_scores.py:89-106](), [extras/compare_interface_metrics_all.py:79-110]()

---