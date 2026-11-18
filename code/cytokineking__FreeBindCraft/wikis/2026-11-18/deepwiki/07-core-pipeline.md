# Core Pipeline

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [bindcraft.py](bindcraft.py)

</details>



This document details the main design pipeline orchestrated by `bindcraft.py`, which serves as the central coordinator for FreeBindCraft's protein design workflow. The core pipeline manages the complete binder design process from initial hallucination through final validation and filtering.

For configuration details, see [Configuration System](#5). For PyRosetta alternatives, see [PyRosetta-Free Alternatives](#4.1). For analysis tools, see [Analysis & Validation](#6).

## Pipeline Overview

The core pipeline follows a multi-stage approach that iteratively generates, optimizes, and validates protein binders until the target number of accepted designs is reached.

### Main Design Loop Architecture

```mermaid
flowchart TD
    Start["bindcraft.py startup"] --> Setup["System Setup & Validation"]
    Setup --> Loop{"Main Design Loop"}
    
    Loop --> CheckTargets["check_accepted_designs()"]
    CheckTargets --> TargetReached{"Target designs reached?"}
    TargetReached -->|Yes| End["Pipeline Complete"]
    TargetReached -->|No| CheckMax["check_n_trajectories()"]
    
    CheckMax --> MaxReached{"Max trajectories reached?"}
    MaxReached -->|Yes| End
    MaxReached -->|No| InitDesign["Initialize Design Parameters"]
    
    InitDesign --> Hallucination["binder_hallucination()"]
    Hallucination --> TrajectoryAnalysis["Trajectory Scoring & Analysis"]
    TrajectoryAnalysis --> MPNNCheck{"MPNN enabled?"}
    
    MPNNCheck -->|No| Loop
    MPNNCheck -->|Yes| MPNNGen["mpnn_gen_sequence()"]
    MPNNGen --> MPNNLoop["MPNN Sequence Processing"]
    MPNNLoop --> ComplexPred["predict_binder_complex()"]
    ComplexPred --> BinderPred["predict_binder_alone()"]
    BinderPred --> Filtering["check_filters()"]
    
    Filtering --> FilterPass{"Pass filters?"}
    FilterPass -->|Yes| Accept["Copy to Accepted/"]
    FilterPass -->|No| Reject["Copy to Rejected/"]
    Accept --> MPNNComplete{"More MPNN sequences?"}
    Reject --> MPNNComplete
    MPNNComplete -->|Yes| MPNNLoop
    MPNNComplete -->|No| Loop
```

**Sources:** [bindcraft.py:526-982]()

## Initialization and Setup Phase

The pipeline begins with comprehensive system initialization that prepares the environment for protein design.

### System Preparation

```mermaid
flowchart TD
    Start["Script Start"] --> FDLimit["_bump_open_files_limit()"]
    FDLimit --> BinSetup["ensure_binaries_executable()"]
    BinSetup --> ArgParse["Argument Parsing"]
    
    ArgParse --> Interactive{"Interactive mode?"}
    Interactive -->|Yes| InteractiveSetup["_prompt_interactive_and_prepare_args()"]
    Interactive -->|No| DirectArgs["Direct CLI args"]
    
    InteractiveSetup --> InputCheck["perform_input_check()"]
    DirectArgs --> InputCheck
    
    InputCheck --> JAXCheck["check_jax_gpu()"]
    JAXCheck --> LoadSettings["load_json_settings()"]
    LoadSettings --> AF2Models["load_af2_models()"]
    AF2Models --> AdvancedCheck["perform_advanced_settings_check()"]
    AdvancedCheck --> DirGen["generate_directories()"]
    DirGen --> DataFrames["generate_dataframe_labels()"]
    DataFrames --> PyRosettaInit["PyRosetta Initialization"]
    PyRosettaInit --> Ready["Pipeline Ready"]
```

**Sources:** [bindcraft.py:34-513]()

### Configuration Loading

The system loads three types of configuration files:
- **Target settings**: Basic design parameters from JSON files
- **Filter settings**: Acceptance criteria and thresholds  
- **Advanced settings**: Algorithm parameters and model configurations

Key initialization functions:
- `perform_input_check()`: Validates configuration file paths and formats
- `perform_advanced_settings_check()`: Validates advanced algorithm parameters
- `generate_directories()`: Creates output directory structure
- `generate_dataframe_labels()`: Sets up CSV column headers for results tracking

**Sources:** [bindcraft.py:413-469]()

## Trajectory Generation Phase

Each design iteration begins with generating a new binder trajectory using ColabDesign and AlphaFold2.

### Binder Hallucination Process

```mermaid
flowchart TD
    InitDesign["Design Initialization"] --> GenSeed["np.random.randint(0, 999999)"]
    GenSeed --> GenLength["Sample binder length from target range"]
    GenLength --> LoadHelicity["load_helicity()"]
    LoadHelicity --> GenName["Generate design_name"]
    
    GenName --> CheckExists{"Trajectory exists?"}
    CheckExists -->|Yes| Loop["Return to main loop"]
    CheckExists -->|No| Hallucination["binder_hallucination()"]
    
    Hallucination --> TrajectoryPDB["Save trajectory PDB"]
    TrajectoryPDB --> CheckTerminate{"trajectory.aux['terminate'] == ''?"}
    CheckTerminate -->|No| Loop
    CheckTerminate -->|Yes| Relax["pr_relax()"]
    
    Relax --> ClashCalc["calculate_clash_score()"]
    ClashCalc --> SSAnalysis["calc_ss_percentage()"]
    SSAnalysis --> InterfaceScore["score_interface()"]
    InterfaceScore --> SeqValidation["validate_design_sequence()"]
    SeqValidation --> RMSD["target_pdb_rmsd()"]
    RMSD --> SaveStats["insert_data(trajectory_csv)"]
```

**Sources:** [bindcraft.py:541-616]()

### Trajectory Analysis

After successful hallucination, each trajectory undergoes comprehensive analysis:

| Analysis Type | Function | Purpose |
|---------------|----------|---------|
| Clash Detection | `calculate_clash_score()` | Detects atomic clashes before/after relaxation |
| Secondary Structure | `calc_ss_percentage()` | Calculates helix/sheet/loop content |
| Interface Scoring | `score_interface()` | Analyzes binding interface properties |
| Sequence Validation | `validate_design_sequence()` | Checks for problematic amino acids |
| Target RMSD | `target_pdb_rmsd()` | Measures target structure deviation |

**Sources:** [bindcraft.py:581-615]()

## MPNN Optimization Phase

If MPNN is enabled, the pipeline optimizes the hallucinated trajectory through sequence design.

### MPNN Sequence Generation

```mermaid
flowchart TD
    EnabledCheck{"advanced_settings['enable_mpnn']?"}
    EnabledCheck -->|No| SkipMPNN["Skip to next trajectory"]
    EnabledCheck -->|Yes| MPNNGen["mpnn_gen_sequence()"]
    
    MPNNGen --> LoadExisting["Load existing MPNN sequences"]
    LoadExisting --> FilterAA["Filter restricted amino acids"]
    FilterAA --> RemoveDuplicates["Remove duplicate sequences"]
    RemoveDuplicates --> SortByScore["Sort by MPNN score"]
    
    SortByScore --> CompileModels["Compile prediction models"]
    CompileModels --> ComplexModel["complex_prediction_model"]
    CompileModels --> BinderModel["binder_prediction_model"]
    
    ComplexModel --> MPNNLoop["Iterate MPNN sequences"]
    BinderModel --> MPNNLoop
```

**Sources:** [bindcraft.py:623-686]()

### Sequence Processing Loop

For each MPNN sequence, the pipeline performs:

1. **Complex Prediction**: `predict_binder_complex()` - Predicts binder-target complex
2. **Early Filtering**: Basic AF2 quality filters applied immediately  
3. **Full Analysis**: Interface scoring and structural analysis for passing designs
4. **Monomer Prediction**: `predict_binder_alone()` - Predicts binder stability
5. **Final Filtering**: `check_filters()` - Applies all acceptance criteria

**Sources:** [bindcraft.py:687-932]()

## Structure Prediction and Analysis

The pipeline uses AlphaFold2 models for structure prediction with comprehensive analysis.

### Prediction Workflow

```mermaid
flowchart TD
    MPNNSeq["MPNN Sequence"] --> ComplexPred["predict_binder_complex()"]
    ComplexPred --> EarlyFilter["Apply AF2 filters"]
    EarlyFilter --> PassEarly{"Pass early filters?"}
    
    PassEarly -->|No| LogReject["Log to rejected_mpnn_full_stats.csv"]
    PassEarly -->|Yes| MultiModel["Predict multiple models"]
    
    MultiModel --> Model1["Model 1 prediction"]
    MultiModel --> Model2["Model 2 prediction"] 
    MultiModel --> ModelN["Model N prediction"]
    
    Model1 --> Analysis1["Full interface analysis"]
    Model2 --> Analysis2["Full interface analysis"]
    ModelN --> AnalysisN["Full interface analysis"]
    
    Analysis1 --> BinderPred["predict_binder_alone()"]
    Analysis2 --> BinderPred
    AnalysisN --> BinderPred
    
    BinderPred --> CalcAverages["calculate_averages()"]
    CalcAverages --> FinalFilter["check_filters()"]
```

**Sources:** [bindcraft.py:703-858]()

### Interface Analysis Metrics

The pipeline calculates comprehensive interface metrics for each model:

| Metric Category | Key Measurements | Functions |
|----------------|------------------|-----------|
| Structural Quality | pLDDT, pTM, i_pTM, pAE, i_pAE | From ColabDesign prediction |
| Interface Geometry | Shape complementarity, PackStat | `score_interface()` |
| Energetics | dG, dSASA, binding energy | PyRosetta or alternatives |
| Hydrogen Bonding | Interface H-bonds, unsatisfied bonds | Interface analysis |
| Secondary Structure | Helix/sheet/loop percentages | `calc_ss_percentage()` |
| Structural Deviation | Hotspot RMSD, target RMSD | `unaligned_rmsd()`, `target_pdb_rmsd()` |

**Sources:** [bindcraft.py:741-791]()

## Filtering and Validation

The final stage applies comprehensive filters to determine design acceptance.

### Filter Application Process

```mermaid
flowchart TD
    DesignData["mpnn_data array"] --> CheckFilters["check_filters()"]
    CheckFilters --> FilterResult{"filter_conditions"}
    
    FilterResult -->|True| Accept["Design Accepted"]
    FilterResult -->|List| Reject["Design Rejected"]
    
    Accept --> CopyAccepted["Copy to Accepted/"]
    Accept --> UpdateFinal["insert_data(final_csv)"]
    Accept --> CopyAssets["Copy plots & animations"]
    
    Reject --> CopyRejected["Copy to Rejected/"]
    Reject --> UpdateFailure["Update failure_csv counters"]
    Reject --> LogRejected["Log to rejected_mpnn_full_stats.csv"]
    
    CopyAccepted --> CheckMore{"More MPNN sequences?"}
    CopyRejected --> CheckMore
    CheckMore -->|Yes| NextMPNN["Process next MPNN sequence"]
    CheckMore -->|No| NextTrajectory["Next trajectory iteration"]
```

**Sources:** [bindcraft.py:870-932]()

### Data Management

The pipeline maintains several CSV files for tracking:
- `trajectory_stats.csv`: Hallucination trajectory metrics
- `mpnn_design_stats.csv`: MPNN sequence analysis results  
- `final_design_stats.csv`: Accepted designs with full statistics
- `failure_csv.csv`: Filter failure counters
- `rejected_mpnn_full_stats.csv`: Detailed rejection reasons

**Sources:** [bindcraft.py:461-490]()

## Memory and Resource Management

The pipeline includes several optimization strategies for long-running design campaigns:

```mermaid
flowchart TD
    Pipeline["Main Pipeline"] --> GC1["gc.collect() after each MPNN"]
    Pipeline --> GC2["gc.collect() every 10 trajectories"]
    Pipeline --> DSSP["clear_dssp_cache() every 10 trajectories"]
    Pipeline --> FileCleanup["Optional PDB cleanup"]
    
    FileCleanup --> RemoveUnrelaxed["remove_unrelaxed_complex"]
    FileCleanup --> RemoveBinder["remove_binder_monomer"]
    FileCleanup --> RemoveTraj["remove_unrelaxed_trajectory"]
    
    GC1 --> MemoryOpt["Memory Optimization"]
    GC2 --> MemoryOpt
    DSSP --> MemoryOpt
```

**Sources:** [bindcraft.py:936-980]()

---