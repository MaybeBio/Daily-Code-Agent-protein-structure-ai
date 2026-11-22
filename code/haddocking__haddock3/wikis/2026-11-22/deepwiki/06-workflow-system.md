# Workflow System

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/haddock/__init__.py](src/haddock/__init__.py)
- [src/haddock/clis/cli.py](src/haddock/clis/cli.py)
- [src/haddock/core/defaults.py](src/haddock/core/defaults.py)
- [src/haddock/gear/config.py](src/haddock/gear/config.py)
- [src/haddock/gear/prepare_run.py](src/haddock/gear/prepare_run.py)
- [src/haddock/gear/zerofill.py](src/haddock/gear/zerofill.py)
- [src/haddock/libs/libutil.py](src/haddock/libs/libutil.py)
- [src/haddock/libs/libworkflow.py](src/haddock/libs/libworkflow.py)
- [src/haddock/modules/__init__.py](src/haddock/modules/__init__.py)
- [tests/test_examples_general.py](tests/test_examples_general.py)
- [tests/test_gear_config.py](tests/test_gear_config.py)
- [tests/test_gear_prepare_run.py](tests/test_gear_prepare_run.py)
- [tests/test_gear_zerofill.py](tests/test_gear_zerofill.py)
- [tests/test_libutil.py](tests/test_libutil.py)
- [tests/test_modules_general.py](tests/test_modules_general.py)
- [tests/test_validations.py](tests/test_validations.py)

</details>



## Purpose and Scope

This page documents the **Workflow System** in HADDOCK3, which is responsible for defining, validating, and executing docking workflows. The workflow system orchestrates the sequential execution of multiple modules, manages data flow between steps, and handles the complete lifecycle from configuration parsing to final execution.

For information about individual module implementations, see [Module Architecture](#3.2). For data exchange between modules, see [Data Flow and ModuleIO](#3.3). For configuration file syntax and parameter definitions, see [Configuration Files](#5.1).

## System Overview

The workflow system is built around three core phases:

1. **Setup Phase**: Configuration parsing, validation, and preparation via `setup_run()`
2. **Orchestration Phase**: Workflow decomposition into steps via `WorkflowManager` and `Workflow`
3. **Execution Phase**: Sequential step execution via `Step` objects that instantiate and run modules

**Key Design Principles**:
- **Linear Execution**: Steps execute sequentially in the order defined in the configuration file
- **Zero-Based Indexing**: Step folders are numbered starting from 0 (e.g., `0_topoaa`, `1_rigidbody`)
- **Stateless Steps**: Each step is independent; data flows through `ModuleIO` serialization
- **Validation-First**: All parameters are validated before any execution begins

Sources: [src/haddock/libs/libworkflow.py:1-191](), [src/haddock/gear/prepare_run.py:214-431]()

## Workflow Phases and Key Components

```mermaid
graph TB
    subgraph "Phase 1: Setup (prepare_run.py)"
        CLI[haddock3 CLI<br/>cli.py:main]
        ParseCfg[load config<br/>config.py:load]
        SetupRun[setup_run<br/>prepare_run.py:214-431]
        ValidateModules[validate_module_names_are_not_misspelled<br/>prepare_run.py:1076-1096]
        ValidateParams[validate_modules_params<br/>prepare_run.py:557-631]
        CreateDir[create_data_dir<br/>prepare_run.py:926-937]
        CopyFiles[copy_molecules_to_data_dir<br/>prepare_run.py:948-1002]
    end
    
    subgraph "Phase 2: Orchestration (libworkflow.py)"
        WFManager[WorkflowManager<br/>libworkflow.py:23-96]
        WFClass[Workflow<br/>libworkflow.py:98-140]
        StepList[List of Step objects<br/>libworkflow.py:118]
    end
    
    subgraph "Phase 3: Execution Loop"
        StepExec[Step.execute<br/>libworkflow.py:157-182]
        ModuleImport[importlib.import_module<br/>libworkflow.py:165]
        ModuleInst[HaddockModule instance<br/>libworkflow.py:166]
        ModuleRun[module.run<br/>libworkflow.py:173]
        Clean[Step.clean<br/>libworkflow.py:183-190]
    end
    
    CLI --> ParseCfg
    ParseCfg --> SetupRun
    SetupRun --> ValidateModules
    SetupRun --> ValidateParams
    SetupRun --> CreateDir
    SetupRun --> CopyFiles
    
    SetupRun --> |modules_params<br/>general_params| WFManager
    WFManager --> WFClass
    WFClass --> StepList
    
    WFManager --> |workflow.run| StepExec
    StepExec --> ModuleImport
    ModuleImport --> ModuleInst
    ModuleInst --> ModuleRun
    ModuleRun --> Clean
    Clean --> |next step| StepExec
    
    style SetupRun fill:#f9f9f9,stroke:#333,stroke-width:2px
    style WFManager fill:#f9f9f9,stroke:#333,stroke-width:2px
    style StepExec fill:#f9f9f9,stroke:#333,stroke-width:2px
```

**Workflow Phases and Code Mapping**

| Phase | Primary Class/Function | File Location | Responsibility |
|-------|------------------------|---------------|----------------|
| Setup | `setup_run()` | prepare_run.py:214-431 | Parse, validate, prepare run directory |
| Orchestration | `WorkflowManager` | libworkflow.py:23-96 | Coordinate workflow execution |
| Orchestration | `Workflow` | libworkflow.py:98-140 | Decompose config into Step objects |
| Execution | `Step` | libworkflow.py:142-191 | Execute individual module |
| Module | `BaseHaddockModule` | modules/__init__.py:115-394 | Base class for all modules |

Sources: [src/haddock/libs/libworkflow.py:23-191](), [src/haddock/gear/prepare_run.py:214-431](), [src/haddock/clis/cli.py:81-214]()

## Setup Phase: setup_run()

The `setup_run()` function is the entry point for workflow preparation. It performs comprehensive validation and file preparation before execution begins.

### Setup Workflow

```mermaid
graph TD
    Start[setup_run called] --> ReadCfg[read_config<br/>config.py:load]
    ReadCfg --> UpdateDefaults[recursive_dict_update<br/>Merge with defaults]
    UpdateDefaults --> SplitParams[Split general_params<br/>and modules_params]
    
    SplitParams --> CheckSpelling[validate_module_names_are_not_misspelled<br/>prepare_run.py:1076-1096]
    CheckSpelling --> CheckInstalled[check_if_modules_are_installed<br/>prepare_run.py:870-894]
    CheckInstalled --> CheckMandatory[check_mandatory_argments_are_present<br/>prepare_run.py:525-535]
    
    CheckMandatory --> DetermineMode{from_scratch?<br/>restart?<br/>extend?}
    
    DetermineMode -->|from_scratch| CheckRunDir[check_run_dir_exists<br/>prepare_run.py:1046-1058]
    CheckRunDir --> CopyTopoMols[copy_molecules_to_topology<br/>prepare_run.py:941-946]
    CopyTopoMols --> PopulateParams[populate_topology_molecule_params<br/>populate_mol_parameters]
    
    DetermineMode -->|restart| RemoveFolders[remove_folders_after_number<br/>restart_run.py]
    RemoveFolders --> Unpack[unpack_compressed_and_archived_files<br/>clean_steps.py]
    Unpack --> Renum[renum_step_folders<br/>extend_run.py]
    
    DetermineMode -->|extend| ReadNumMols[read_num_molecules_from_folder<br/>extend_run.py]
    ReadNumMols --> SetZerofill[zero_fill.set_zerofill_number]
    
    PopulateParams --> ValidateAll[validate_modules_params<br/>prepare_run.py:557-631]
    Renum --> ValidateAll
    SetZerofill --> ValidateAll
    
    ValidateAll --> CreateData[create_data_dir<br/>prepare_run.py:926-937]
    CreateData --> SaveConfigs[save_configuration_files<br/>prepare_run.py:433-512]
    SaveConfigs --> CopyInputFiles[copy_input_files_to_data_dir<br/>prepare_run.py:1004-1044]
    
    CopyInputFiles --> Return[Return modules_params<br/>general_params]
    
    style Start fill:#f9f9f9,stroke:#333,stroke-width:2px
    style ValidateAll fill:#f9f9f9,stroke:#333,stroke-width:2px
    style Return fill:#f9f9f9,stroke:#333,stroke-width:2px
```

### Key Functions in Setup Phase

| Function | Location | Purpose |
|----------|----------|---------|
| `setup_run()` | prepare_run.py:214-431 | Main orchestrator for workflow setup |
| `validate_modules_params()` | prepare_run.py:557-631 | Validate each module's parameters against defaults.yaml |
| `validate_param_type()` | prepare_run.py:689-717 | Check parameter type matches expected type |
| `validate_param_range()` | prepare_run.py:719-762 | Check parameter value is in allowed range/choices |
| `validate_ncs_params()` | prepare_run.py:764-868 | Special validation for NCS restraints |
| `copy_molecules_to_data_dir()` | prepare_run.py:948-1002 | Copy and preprocess input PDB files |
| `populate_mol_parameters()` | prepare_run.py:1306-1337 | Expand mol1, mol2, etc. parameters |

**Validation Levels**: The setup phase performs five levels of validation:

1. **Spelling**: Module names match known modules ([prepare_run.py:1076-1096]())
2. **Installation**: Third-party dependencies are available ([prepare_run.py:870-894]())
3. **Type**: Parameter types match YAML definitions ([prepare_run.py:689-717]())
4. **Range**: Parameter values are in allowed ranges ([prepare_run.py:719-762]())
5. **Logic**: Special rules like NCS parameter consistency ([prepare_run.py:764-868]())

Sources: [src/haddock/gear/prepare_run.py:214-431](), [src/haddock/gear/prepare_run.py:557-868](), [src/haddock/gear/prepare_run.py:1076-1096]()

## Orchestration Phase: WorkflowManager and Workflow

After `setup_run()` completes, the `WorkflowManager` is instantiated to coordinate execution.

### WorkflowManager Class

```mermaid
classDiagram
    class WorkflowManager {
        +int start
        +Workflow recipe
        +int _terminated
        +__init__(workflow_params, start, **other_params)
        +run() void
        +clean(terminated) void
        +postprocess(self_contained) void
    }
    
    class Workflow {
        +list~Step~ steps
        +__init__(modules_parameters, start, **other_params)
    }
    
    class Step {
        +dict config
        +str module_name
        +int order
        +Path working_path
        +BaseHaddockModule module
        +__init__(module_name, order, **config_params)
        +execute() void
        +clean() void
    }
    
    class BaseHaddockModule {
        +int order
        +Path path
        +ModuleIO previous_io
        +dict params
        +run(**params) void
        +export_io_models(faulty_tolerance) void
    }
    
    WorkflowManager "1" --> "1" Workflow : creates
    Workflow "1" --> "*" Step : contains
    Step "1" --> "0..1" BaseHaddockModule : instantiates
```

**WorkflowManager Responsibilities**:
- **Execution Loop**: Iterates through steps sequentially ([libworkflow.py:39-46]())
- **Error Handling**: Catches `HaddockTermination` exceptions ([libworkflow.py:44-46]())
- **Cleanup**: Calls `clean()` on completed steps ([libworkflow.py:48-60]())
- **Post-processing**: Generates analysis reports via `cli_analyse` ([libworkflow.py:62-96]())

**Workflow Responsibilities**:
- **Step Creation**: Builds `Step` objects from `modules_parameters` dict ([libworkflow.py:118-135]())
- **Parameter Merging**: Combines global and module-specific parameters ([libworkflow.py:127]())
- **Zero-fill Management**: Determines folder naming prefix ([libworkflow.py:373]() in prepare_run)

Sources: [src/haddock/libs/libworkflow.py:23-140]()

## Execution Phase: Step Lifecycle

Each `Step` object represents one module in the workflow. The execution lifecycle follows a strict sequence.

### Step Execution Sequence

```mermaid
stateDiagram-v2
    [*] --> Instantiated: Step.__init__
    Instantiated --> FolderCreated: working_path.mkdir()
    note right of FolderCreated: Creates 00_topoaa, 01_rigidbody, etc.
    
    FolderCreated --> ModuleImported: importlib.import_module
    note right of ModuleImported: Dynamically imports haddock.modules.{category}.{name}
    
    ModuleImported --> ModuleInstantiated: HaddockModule(order, path)
    note right of ModuleInstantiated: Creates instance of specific module class
    
    ModuleInstantiated --> ParamsUpdated: module.update_params(**config)
    ModuleInstantiated --> ConfigSaved: module.save_config(params.cfg)
    
    ParamsUpdated --> Running: module.run()
    ConfigSaved --> Running
    
    Running --> Completed: Success
    Running --> Failed: Exception
    
    Completed --> Cleaned: module.clean_output()
    note right of Cleaned: Compress/archive outputs if clean=true
    
    Cleaned --> [*]
    Failed --> [*]
```

### Step.execute() Method Flow

The `Step.execute()` method ([libworkflow.py:157-182]()) performs these operations:

1. **Create Working Directory**: `self.working_path.resolve().mkdir()` ([libworkflow.py:159]())
   - Path format: `{zerofill}_{module_name}` (e.g., `01_rigidbody`)
   - `zerofill` determined by `zero_fill.fill()` ([zerofill.py:84-99]())

2. **Import Module**: `importlib.import_module(module_name)` ([libworkflow.py:165]())
   - Module path: `haddock.modules.{category}.{module_name}`
   - Category from `modules_category` dict ([modules/__init__.py:43-49]())

3. **Instantiate Module**: `module_lib.HaddockModule(order, path)` ([libworkflow.py:166]())
   - Calls `BaseHaddockModule.__init__()` ([modules/__init__.py:120-143]())
   - Loads previous step's `io.json` via `_load_previous_io()` ([modules/__init__.py:320-336]())

4. **Update Parameters**: `module.update_params(**self.config)` ([libworkflow.py:171]())
   - Merges defaults with user parameters ([modules/__init__.py:154-207]())

5. **Save Configuration**: `module.save_config(params.cfg)` ([libworkflow.py:172]())
   - Writes module config to `{step_folder}/params.cfg`

6. **Execute Module**: `module.run()` ([libworkflow.py:173]())
   - Calls module's `_run()` implementation ([modules/__init__.py:236-249]())

7. **Log Time**: Records execution duration ([libworkflow.py:169-181]())

Sources: [src/haddock/libs/libworkflow.py:142-191](), [src/haddock/modules/__init__.py:115-269]()

## Module Directory Structure and Zero-Fill

HADDOCK3 uses zero-filled numeric prefixes to ensure folders sort correctly regardless of the number of steps.

### Zero-Fill Logic

```mermaid
graph LR
    subgraph "zero_fill singleton (zerofill.py)"
        ZF[_ZeroFill instance<br/>zerofill.py:102]
        Read[read method<br/>zerofill.py:70-82]
        Fill[fill method<br/>zerofill.py:84-99]
        ZFNum[zfnum property<br/>Number of digits]
    end
    
    subgraph "Calculation"
        ModCount[Count modules<br/>len of modules_params]
        CalcDigits[get_number_of_digits<br/>zerofill.py:105-113]
        Result[zerofill number]
    end
    
    Read --> ModCount
    ModCount --> CalcDigits
    CalcDigits --> ZFNum
    ZFNum --> Fill
    Fill --> |Returns| FolderName["XX_modulename"]
    
    style ZF fill:#f9f9f9,stroke:#333,stroke-width:2px
```

**Zero-Fill Examples**:

| Number of Modules | Zero-Fill Digits | Folder Names |
|-------------------|------------------|--------------|
| 1-10 | 1 | `0_topoaa`, `1_rigidbody`, ..., `9_caprieval` |
| 11-100 | 2 | `00_topoaa`, `01_rigidbody`, ..., `99_analysis` |
| 101-1000 | 3 | `000_topoaa`, `001_rigidbody`, ..., `999_end` |

**Key Functions**:
- `get_number_of_digits(num)`: Returns digit count ([zerofill.py:105-113]())
- `get_zerofill_for_modules(modules)`: Calculates zero-fill for module list ([zerofill.py:116-130]())
- `zero_fill.fill(name, num)`: Creates formatted folder name ([zerofill.py:84-99]())

Sources: [src/haddock/gear/zerofill.py:1-136](), [src/haddock/libs/libworkflow.py:154]()

## Configuration Flow: TOML to Execution

The configuration undergoes multiple transformations before execution:

```mermaid
graph TB
    subgraph "User Input"
        TOML[config.cfg or config.toml<br/>User configuration file]
    end
    
    subgraph "Parsing (config.py)"
        Load[config.load<br/>config.py:116-143]
        Loads[config.loads<br/>config.py:145-237]
        TomlLib[toml.loads<br/>External library]
        Normalize[Normalize headers<br/>Add .1, .2 suffixes]
        ConvertPaths[convert_variables_to_paths<br/>config.py:239-266]
    end
    
    subgraph "Validation (prepare_run.py)"
        RecursiveUpdate[recursive_dict_update<br/>Merge with defaults]
        SplitParams[Separate general<br/>and module params]
        ValidateNames[validate_module_names_are_not_misspelled]
        ValidateTypes[validate_modules_params<br/>Type and range checks]
    end
    
    subgraph "Execution (libworkflow.py)"
        WorkflowInit[Workflow.__init__<br/>Create Step objects]
        StepInit[Step.__init__<br/>Store config_params]
        ModuleUpdate[module.update_params<br/>Final parameter merge]
    end
    
    TOML --> Load
    Load --> Loads
    Loads --> Normalize
    Normalize --> TomlLib
    TomlLib --> ConvertPaths
    ConvertPaths --> |raw_input<br/>cleaned_input<br/>loaded_cleaned_input<br/>final_cfg| RecursiveUpdate
    
    RecursiveUpdate --> SplitParams
    SplitParams --> ValidateNames
    ValidateNames --> ValidateTypes
    ValidateTypes --> |modules_params<br/>general_params| WorkflowInit
    
    WorkflowInit --> StepInit
    StepInit --> ModuleUpdate
    
    style TOML fill:#f9f9f9,stroke:#333,stroke-width:2px
    style ValidateTypes fill:#f9f9f9,stroke:#333,stroke-width:2px
    style ModuleUpdate fill:#f9f9f9,stroke:#333,stroke-width:2px
```

**Configuration Dictionary Structure**:

The `config.loads()` function returns a dictionary with four keys:

```
{
    'raw_input': <original config string>,
    'cleaned_input': <normalized TOML string>,
    'loaded_cleaned_input': <parsed dict before path conversion>,
    'final_cfg': <dict with Path objects>
}
```

**Module Header Normalization**:

Input headers are normalized to the format `'modulename.N'`:

- `[topoaa]` → `['topoaa.1']`
- `[rigidbody]` → `['rigidbody.1']`
- `[rigidbody]` (second occurrence) → `['rigidbody.2']`
- `['flexref.3']` → `['flexref.1']` (renumbered sequentially)

This normalization happens via regex matching ([config.py:176-214]()).

Sources: [src/haddock/gear/config.py:116-237](), [src/haddock/gear/prepare_run.py:276-431]()

## Restart and Extend-Run Modes

HADDOCK3 supports three execution modes:

### Execution Mode Comparison

| Mode | CLI Flag | Starting Condition | Behavior |
|------|----------|-------------------|----------|
| **From Scratch** | None | Empty or non-existent run_dir | Full setup and execution |
| **Restart** | `--restart N` | Existing run_dir | Remove folders after step N, re-execute from N |
| **Extend** | `--extend-run PATH` | Copy of previous run | Continue from last step, add new steps |

### Restart Mode Flow

When `--restart N` is provided:

1. **Remove Folders**: `remove_folders_after_number(run_dir, N)` ([restart_run.py]())
   - Deletes step folders > N
   - Deletes data folders > N

2. **Unpack Archives**: `unpack_compressed_and_archived_files()` ([clean_steps.py]())
   - Decompresses `.tgz` files from previous steps

3. **Renumber Steps**: `renum_step_folders()` ([extend_run.py]())
   - Adjusts folder prefixes to match new workflow

4. **Partial File Copy**: `copy_input_files_to_data_dir(start=restart_from)` ([prepare_run.py:1004-1044]())
   - Only copies input files for steps >= N

### Extend-Run Mode Flow

When `--extend-run PATH` is provided:

1. **Read Existing Steps**: `get_module_steps_folders(extend_run)` ([modules/__init__.py:446-494]())
   - Scans existing run directory

2. **Calculate Start Point**: `restart_step = max([int(fold.split('_')[0]) for fold in steps]) + 1`
   - Starts after last existing step

3. **Adjust Zero-Fill**: `zero_fill.set_zerofill_number(num_steps + _num_modules)` ([prepare_run.py:358]())
   - Accounts for existing + new steps

4. **Use Extended Manager**: `WorkflowManagerExtend` instead of `WorkflowManager` ([cli.py:179]())

Sources: [src/haddock/gear/prepare_run.py:319-425](), [src/haddock/clis/cli.py:175-183]()

## Error Handling and Validation

The workflow system implements defensive validation at multiple levels:

### Validation Hierarchy

```mermaid
graph TD
    subgraph "Configuration Validation"
        V1[Module Name Spelling<br/>validate_module_names_are_not_misspelled]
        V2[Module Installation<br/>check_if_modules_are_installed]
        V3[Parameter Spelling<br/>validate_parameters_are_not_misspelled]
        V4[Mandatory Parameters<br/>check_mandatory_argments_are_present]
    end
    
    subgraph "Parameter Validation"
        P1[Type Validation<br/>validate_param_type]
        P2[Range Validation<br/>validate_param_range]
        P3[Special Rules<br/>validate_ncs_params<br/>confirm_resdic_chainid_length]
        P4[Incompatibility Checks<br/>validate_parameters_are_not_incompatible]
    end
    
    subgraph "Runtime Validation"
        R1[File Existence<br/>_confirm_fnames_exist]
        R2[Previous IO<br/>_load_previous_io]
        R3[Output Validation<br/>export_io_models<br/>faulty_tolerance]
    end
    
    V1 --> V2
    V2 --> V3
    V3 --> V4
    V4 --> P1
    
    P1 --> P2
    P2 --> P3
    P3 --> P4
    P4 --> R1
    
    R1 --> R2
    R2 --> R3
    
    style V1 fill:#f9f9f9,stroke:#333,stroke-width:2px
    style P1 fill:#f9f9f9,stroke:#333,stroke-width:2px
    style R1 fill:#f9f9f9,stroke:#333,stroke-width:2px
```

**Type Validation** ([prepare_run.py:689-717]()):
- Uses `TYPES_MAPPER` dict to map YAML types to Python types
- Example: `"integer"` maps to `(int, float)`

**Range Validation** ([prepare_run.py:719-762]()):
- Checks `choices` for enumerated options
- Checks `min`/`max` for numeric ranges
- Checks `minitems`/`maxitems` for lists
- Checks `minchars`/`maxchars` for strings

**Fuzzy Matching** ([prepare_run.py:1118-1142]()):
- When parameter misspelled, suggests closest match using `difflib.get_close_matches()`
- Example: `"loong-format"` suggests `"long-format"`

**Exception Types**:
- `ConfigurationError`: Raised for configuration issues ([core/exceptions.py]())
- `ModuleError`: Raised for module-specific problems ([core/exceptions.py]())
- `HaddockTermination`: Clean workflow exit signal ([core/exceptions.py]())
- `StepError`: Raised during step execution failures ([core/exceptions.py]())

Sources: [src/haddock/gear/prepare_run.py:557-868](), [src/haddock/gear/prepare_run.py:1118-1142](), [src/haddock/modules/__init__.py:383-394]()

## Post-Processing and Analysis

After workflow execution completes, the `WorkflowManager.postprocess()` method generates analysis outputs:

### Post-Processing Flow

```mermaid
graph LR
    Complete[Workflow Complete] --> PostProcess[WorkflowManager.postprocess]
    PostProcess --> IdentifyCAPRI[Identify caprieval steps]
    IdentifyCAPRI --> CallAnalyse[cli_analyse<br/>clis/cli_analyse.py]
    CallAnalyse --> CallTraceback[cli_traceback<br/>clis/cli_traceback.py]
    
    CallAnalyse --> GenerateHTML[HTML Reports]
    CallAnalyse --> GeneratePlots[Interactive Plots]
    CallAnalyse --> GenerateTables[TSV Tables]
    
    PostProcess --> Archive{gen_archive?}
    Archive -->|true| CreateArchive[archive_run<br/>gear/postprocessing.py]
    Archive -->|false| Skip[Skip archiving]
    
    CreateArchive --> RunTGZ[run_archive.tgz]
    CreateArchive --> AnalysisTGZ[analysis.tgz]
    
    style PostProcess fill:#f9f9f9,stroke:#333,stroke-width:2px
```

**Post-Processing Configuration**:

The `postprocess()` method reads configuration from the first step:
- `clean`: Whether to compress intermediate files
- `offline`: Whether to skip external resources
- `mode`: Execution mode (local/mpi/grid)
- `ncores`: Number of cores for parallel analysis

**Archive Creation**:

If `gen_archive=true`, creates two archives:
1. **run_archive.tgz**: Complete run directory with all outputs
2. **analysis.tgz**: Analysis-only results (plots, tables, HTML)

Sources: [src/haddock/libs/libworkflow.py:62-96]()

---