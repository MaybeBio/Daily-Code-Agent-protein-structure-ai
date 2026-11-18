# Core Utilities

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [functions/generic_utils.py](functions/generic_utils.py)

</details>



## Purpose and Scope

The Core Utilities system provides foundational infrastructure services for FreeBindCraft, implemented primarily in `functions/generic_utils.py`. This module handles essential tasks including directory structure setup, configuration management, data persistence, system validation, and statistical processing that support the main design pipeline.

For information about the main design orchestration, see [Core Pipeline](#3). For configuration file formats and settings, see [Configuration System](#5).

## Directory Management System

The core utilities establish a standardized directory structure for organizing design outputs, intermediate files, and analysis results. The `generate_directories` function creates the complete folder hierarchy needed for a design run.

### Directory Structure

```mermaid
graph TD
    DP["design_path"] --> A["Accepted/"]
    DP --> T["Trajectory/"]  
    DP --> M["MPNN/"]
    DP --> R["Rejected/"]
    
    A --> AR["Ranked/"]
    A --> AA["Animation/"]
    A --> AP["Plots/"]
    A --> APick["Pickle/"]
    
    T --> TR["Relaxed/"]
    T --> TP["Plots/"]
    T --> TC["Clashing/"]
    T --> TL["LowConfidence/"]
    T --> TA["Animation/"]
    T --> TPick["Pickle/"]
    
    M --> MB["Binder/"]
    M --> MS["Sequences/"]
    M --> MR["Relaxed/"]
```

The directory structure serves specific purposes:
- **Accepted**: Final validated designs, ranked by quality
- **Trajectory**: Intermediate hallucination results and analysis  
- **MPNN**: Sequence generation outputs and structure predictions
- **Rejected**: Failed designs for debugging analysis

Sources: [functions/generic_utils.py:44-58]()

### Directory Creation Process

```mermaid
flowchart LR
    start["generate_directories(design_path)"] --> names["design_path_names list"]
    names --> loop["For each folder name"]
    loop --> create["os.makedirs(path, exist_ok=True)"]
    create --> store["design_paths[name] = path"]
    store --> loop
    loop --> return["Return design_paths dict"]
```

Sources: [functions/generic_utils.py:44-58]()

## Configuration and Settings Management  

The utilities provide a comprehensive configuration system that loads and validates settings from multiple JSON files, performs system checks, and ensures proper environment setup.

### Configuration Loading Flow

```mermaid
flowchart TD
    args["Command Line Args"] --> pic["perform_input_check(args)"]
    pic --> paths["settings.json, filters.json, advanced.json paths"]
    paths --> ljs["load_json_settings()"]
    ljs --> target["target_settings"]
    ljs --> filters["filters"]  
    ljs --> advanced["advanced_settings"]
    advanced --> pasc["perform_advanced_settings_check()"]
    pasc --> validated["Validated Settings"]
```

### Settings Validation Process

The `perform_advanced_settings_check` function handles several critical validation tasks:

1. **Path Resolution**: Sets default paths for model weights and executables
2. **Binary Validation**: Ensures required tools like DSSP and DAlphaBall are executable  
3. **Parameter Sanitization**: Validates and formats settings like `omit_AAs`
4. **Default Setting**: Provides fallback values for optional parameters

```mermaid
graph TB  
    pasc["perform_advanced_settings_check()"] --> paths["Set af_params_dir, dssp_path, dalphaball_path"]
    pasc --> omit["Format omit_AAs string"]
    pasc --> defaults["Set animation/plot defaults"]  
    pasc --> exec["_ensure_required_executables()"]
    exec --> dssp["chmod +x dssp binary"]
    exec --> dalpha["chmod +x DAlphaBall.gcc"]
```

Sources: [functions/generic_utils.py:245-276](), [functions/generic_utils.py:278-305]()

## Data Management System

The core utilities manage structured data persistence through CSV files and pandas DataFrames, providing consistent data schemas and efficient I/O operations.

### DataFrame Schema Definition

The `generate_dataframe_labels` function defines three primary data schemas:

| Schema Type | Purpose | Key Fields |
|-------------|---------|------------|
| `trajectory_labels` | Hallucination tracking | pLDDT, pTM, i_pTM, clashes, interface metrics |
| `design_labels` | MPNN design results | Sequence, MPNN scores, averaged metrics |  
| `final_labels` | Ranked final outputs | Rank + all design labels |

```mermaid
graph LR
    gdl["generate_dataframe_labels()"] --> tl["trajectory_labels"]
    gdl --> dl["design_labels"] 
    gdl --> fl["final_labels"]
    
    tl --> csv1["trajectory.csv"]
    dl --> csv2["mpnn.csv"]
    fl --> csv3["final.csv"]
```

Sources: [functions/generic_utils.py:19-41]()

### Failure Tracking System

The utilities implement a comprehensive failure tracking system to monitor which filters cause design rejections:

```mermaid
flowchart TD
    gfpcsv["generate_filter_pass_csv()"] --> filters["Read filters.json"]
    filters --> columns["Generate failure columns"]
    columns --> init["Initialize CSV with zeros"]
    
    update["update_failures()"] --> type{{"Dict or String?"}}
    type -->|Dict| batch["Batch update from complex prediction"]  
    type -->|String| single["Single column update from trajectory"]
    batch --> save["Save to failure CSV"]
    single --> save
```

Sources: [functions/generic_utils.py:61-133]()

## System Validation and Health Checks

The core utilities perform essential system validation to ensure the runtime environment is properly configured before design execution begins.

### GPU Validation

```mermaid
graph TD
    cjg["check_jax_gpu()"] --> devices["jax.devices()"]
    devices --> check{"Has GPU?"}
    check -->|No| exit["Print error, exit()"]
    check -->|Yes| list["List available GPUs"]
    list --> continue["Continue execution"]
```

### Binary Executable Validation  

The `_ensure_required_executables` function validates that bundled tools have proper permissions:

| Binary | Purpose | Validation |
|--------|---------|------------|
| `dssp` | Secondary structure analysis | Check executable bit, chmod if needed |
| `DAlphaBall.gcc` | SASA calculations (PyRosetta mode) | Check executable bit, chmod if needed |

Sources: [functions/generic_utils.py:211-222](), [functions/generic_utils.py:278-305]()

## Statistical Processing

The utilities provide statistical processing capabilities for analyzing design results and calculating performance metrics.

### Averaging System

```mermaid
flowchart TD
    ca["calculate_averages(statistics, handle_aa)"] --> init["Initialize sums and aa_sums dicts"]
    init --> loop["For models 1-5"]
    loop --> exist{"Model exists?"}
    exist -->|No| loop
    exist -->|Yes| process["Process model statistics"]
    process --> aa{"handle_aa AND stat == InterfaceAAs?"}
    aa -->|Yes| amino["Sum amino acid counts separately"]  
    aa -->|No| regular["Add to regular sums"]
    amino --> loop
    regular --> loop
    loop --> calc["Calculate averages from sums"]
    calc --> return["Return averages dict"]
```

### Filter Validation

The `check_filters` function validates design metrics against threshold criteria:

```mermaid
graph TB
    cf["check_filters(mpnn_data, design_labels, filters)"] --> dict["Create mpnn_dict from data/labels"]
    dict --> floop["For each filter"]
    floop --> aa_check{"InterfaceAAs filter?"}
    aa_check -->|Yes| aa_loop["Check each amino acid threshold"]
    aa_check -->|No| regular_check["Check regular threshold"]
    aa_loop --> higher1{"higher == True?"}
    regular_check --> higher2{"higher == True?"}  
    higher1 --> pass_fail1["value >= threshold"]
    higher2 --> pass_fail2["value >= threshold"]
    pass_fail1 --> unmet["Add to unmet_conditions if failed"]
    pass_fail2 --> unmet
    unmet --> floop
    floop --> result{"len(unmet_conditions) == 0?"}
    result -->|Yes| return_true["Return True"]
    result -->|No| return_unmet["Return unmet_conditions list"]
```

Sources: [functions/generic_utils.py:383-422](), [functions/generic_utils.py:425-464]()

## Design Progress Tracking

The utilities provide functions to monitor design progress and determine when target criteria are met.

### Trajectory Monitoring  

```mermaid
graph LR
    cnt["check_n_trajectories()"] --> count["Count .pdb files in Trajectory/Relaxed/"]
    count --> limit{"count >= max_trajectories?"}
    limit -->|Yes| stop["Return True, stop execution"]
    limit -->|No| continue["Return False, continue"]
```

### Accepted Design Management

```mermaid
flowchart TD
    cad["check_accepted_designs()"] --> count["Count accepted binders"]
    count --> target{"count >= number_of_final_designs?"}
    target -->|No| return_false["Return False"]
    target -->|Yes| clear["Clear Ranked/ folder"]
    clear --> load["Load mpnn CSV"]
    load --> sort["Sort by Average_i_pTM descending"]
    sort --> rank["Rank and copy designs"]
    rank --> save["Save final CSV"]
    save --> zip["Zip animations/plots if enabled"]  
    zip --> return_true["Return True"]
```

Sources: [functions/generic_utils.py:136-143](), [functions/generic_utils.py:146-195]()

## Utility Functions

### File Operations

| Function | Purpose | Key Operations |
|----------|---------|----------------|
| `clean_pdb` | Remove Rosetta metadata | Filter ATOM, HETATM, MODEL, TER, END, LINK lines |
| `save_fasta` | Write sequence files | Generate FASTA format for MPNN sequences |
| `zip_and_empty_folder` | Archive large outputs | Compress and remove files by extension |

### AlphaFold Model Management

The `load_af2_models` function manages model selection for different pipeline stages:

```mermaid
graph TD
    lam["load_af2_models(af_multimer_setting)"] --> multimer{"af_multimer_setting?"}
    multimer -->|True| m_path["design_models = [0,1,2,3,4]<br/>prediction_models = [0,1]<br/>multimer_validation = False"]
    multimer -->|False| s_path["design_models = [0,1]<br/>prediction_models = [0,1,2,3,4]<br/>multimer_validation = True"]
    m_path --> return["Return model configurations"]
    s_path --> return
```

Sources: [functions/generic_utils.py:357-364](), [functions/generic_utils.py:350-354](), [functions/generic_utils.py:366-380](), [functions/generic_utils.py:322-332]()

---