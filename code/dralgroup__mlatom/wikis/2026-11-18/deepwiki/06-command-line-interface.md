# Command Line Interface

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [mlatom/MLatom.py](mlatom/MLatom.py)
- [mlatom/MLtasks.py](mlatom/MLtasks.py)
- [mlatom/args_class.py](mlatom/args_class.py)
- [mlatom/interfaces/xtb_interface.py](mlatom/interfaces/xtb_interface.py)

</details>



The Command Line Interface (CLI) is the primary entry point for users to interact with MLatom. It provides a unified command-line interface that handles argument parsing, task dispatching, and execution flow control for all MLatom functionality including machine learning tasks, molecular simulations, and quantum chemistry calculations.

For information about the core task implementations, see [Task Management and Arguments](#3.2). For details on the underlying data structures used by CLI tasks, see [Data Structures](#2.1).

## CLI Architecture Overview

The MLatom CLI follows a three-layer architecture that separates user input processing, argument parsing, and task execution:

```mermaid
graph TB
    subgraph "User Interface Layer"
        CLI["`MLatom.py
        Main Entry Point`"]
        VERSION["`Version Check
        -v, --version`"]
        LIST["`Installation List
        -l, --list`"]
    end
    
    subgraph "Argument Processing Layer"  
        ARGS["`args_class.py
        mlatom_args`"]
        PARSE["`Argument Parsing
        File & CLI Args`"]
        VALID["`Argument Validation
        Task & Method Detection`"]
    end
    
    subgraph "Task Execution Layer"
        DISPATCH["`MLtasks.py
        CLItasks`"]
        MLATOMF["`MLatomF Interface
        Legacy Tasks`"]
        TASKS["`Python Task Functions
        Modern Implementation`"]
    end
    
    CLI --> VERSION
    CLI --> LIST  
    CLI --> ARGS
    ARGS --> PARSE
    PARSE --> VALID
    VALID --> DISPATCH
    DISPATCH --> MLATOMF
    DISPATCH --> TASKS
```

**CLI Entry Point Flow**
Sources: [mlatom/MLatom.py:63-173](), [mlatom/args_class.py:401-762](), [mlatom/MLtasks.py:14-29]()

## Command Line Execution Flow

The CLI execution follows a structured pipeline from user input to task completion:

```mermaid
flowchart TD
    START["`User Command
    mlatom [options] or [file]`"] --> ENTRY["`run() function
    MLatom.py:63`"]
    
    ENTRY --> CHECK{"`Special Flags?`"}
    CHECK -->|"-v, --version"| VER["`Version Display
    MLatom.py:84-98`"]
    CHECK -->|"-l, --list"| LST["`Installation List
    MLatom.py:99-136`"]
    CHECK -->|"No"| LOAD["`Dynamic Module Loading
    MLatom.py:64-78`"]
    
    LOAD --> PARSE["`mlatom_args.parse()
    args_class.py:645-655`"]
    PARSE --> VALIDATE["`Argument Validation
    args_class.py:695-738`"]
    VALIDATE --> DISPATCH["`CLItasks(args).run()
    MLtasks.py:25-29`"]
    
    DISPATCH --> ROUTE{"`Task Type?`"}
    ROUTE -->|"MLatomF Compatible"| MLF["`run_with_mlatomF()
    MLtasks.py:31-40`"]
    ROUTE -->|"Python Implementation"| PY["`Python Task Function
    MLtasks.py:43+`"]
    
    MLF --> RESULT["`Task Results`"]
    PY --> RESULT
    RESULT --> TIMING["`Wall-clock Timing
    MLatom.py:166-171`"]
    
    VER --> EXIT["`Program Exit`"]
    LST --> EXIT
    TIMING --> EXIT
```

**Command Execution Pipeline**
Sources: [mlatom/MLatom.py:63-173](), [mlatom/args_class.py:645-655](), [mlatom/MLtasks.py:25-40]()

## Argument Parsing System

The argument parsing system provides flexible input handling that supports both command-line arguments and input files:

| Component | Class/Function | Purpose |
|-----------|---------------|---------|
| Base Parser | `ArgsBase` | Generic argument parsing with key-value support |
| MLatom Parser | `mlatom_args` | MLatom-specific argument handling and validation |
| Task Detection | `_checkArgs()` | Automatic task identification from arguments |
| Method Detection | Built-in | Automatic method identification from arguments |

```mermaid
graph LR
    subgraph "Input Sources"
        CLI_ARGS["`Command Line Args
        sys.argv[1:]`"]
        INPUT_FILE["`Input File
        Single file argument`"]
    end
    
    subgraph "Parsing Core"
        EXTRACTOR["`_args_extractor()
        args_class.py:203-233`"]
        CONTENT["`parse_input_content()
        args_class.py:240-267`"]
        CONVERTER["`_convert_to_value_with_type()
        args_class.py:380-398`"]
    end
    
    subgraph "Validation & Processing"
        TASK_CHECK["`_checkArgs()
        args_class.py:695-738`"]
        ALIAS["`_restore_alias_key()
        args_class.py:349-353`"]
        POST_OPS["`_post_operations()
        args_class.py:657-666`"]
    end
    
    CLI_ARGS --> EXTRACTOR
    INPUT_FILE --> EXTRACTOR
    EXTRACTOR --> CONTENT
    CONTENT --> CONVERTER
    CONVERTER --> TASK_CHECK
    TASK_CHECK --> ALIAS
    ALIAS --> POST_OPS
```

**Argument Processing Pipeline**
Sources: [mlatom/args_class.py:203-267](), [mlatom/args_class.py:695-738](), [mlatom/args_class.py:349-398]()

## Task Categories and Dispatch

MLatom organizes functionality into distinct task categories, each handled by specific dispatch logic:

| Category | Tasks | Handler |
|----------|-------|---------|
| ML Tasks | `useMLmodel`, `createMLmodel`, `estAccMLmodel` | Python or MLatomF |
| Data Tasks | `XYZ2X`, `analyze`, `sample` | Mixed implementation |
| Simulation Tasks | `geomopt`, `freq`, `MD`, `al` | Python implementation |
| Specialized | `learningCurve`, `crossSection`, `MLQD` | Python implementation |

```mermaid
graph TD
    subgraph "Task Dispatch Logic"
        CLITASKS["`CLItasks.__init__()
        MLtasks.py:23-24`"]
        RUN["`CLItasks.run()
        MLtasks.py:25-29`"]
        CHECK{"`MLatomF Compatible?
        MLtasks.py:26`"}
    end
    
    subgraph "MLatomF Tasks"
        MLF_LIST["`MLatomF_tasks
        ['useMLmodel', 'createMLmodel', 
         'estAccMLmodel', 'XYZ2X', 
         'analize', 'sample']`"]
        MLF_RUN["`run_with_mlatomF()
        MLtasks.py:31-40`"]
    end
    
    subgraph "Python Tasks"
        PY_TASKS["`Python Task Functions
        useMLmodel(), createMLmodel(),
        geomopt(), freq(), MD(), etc.`"]
        GLOBALS["`globals()[task]()
        MLtasks.py:29`"]
    end
    
    CLITASKS --> RUN
    RUN --> CHECK
    CHECK -->|"Yes & Conditions Met"| MLF_LIST
    CHECK -->|"No"| GLOBALS
    MLF_LIST --> MLF_RUN
    GLOBALS --> PY_TASKS
```

**Task Dispatch Architecture**
Sources: [mlatom/MLtasks.py:14-29](), [mlatom/MLtasks.py:31-40]()

## Dynamic Module Loading

MLatom implements sophisticated dynamic module loading to ensure that the CLI uses the same instance of the mlatom package from which it's executed:

```mermaid
sequenceDiagram
    participant U as "User"
    participant CLI as "MLatom.py run()"
    participant IMP as "importlib.util" 
    participant MOD as "mlatom module"
    participant SYS as "sys.modules"
    
    U->>CLI: "Execute mlatom command"
    CLI->>CLI: "Get directory path of __file__"
    CLI->>IMP: "spec_from_file_location(dirname, path2init)"
    IMP->>CLI: "Return module spec"
    CLI->>IMP: "module_from_spec(spec)"
    IMP->>CLI: "Return module object"
    CLI->>SYS: "sys.modules[dirname] = module"
    CLI->>IMP: "spec.loader.exec_module(module)"
    IMP->>MOD: "Load module components"
    CLI->>CLI: "Extract header, CLItasks, mlatom_args"
```

**Dynamic Loading Sequence**
Sources: [mlatom/MLatom.py:64-78]()

## Version and Installation Management

The CLI provides built-in version checking and installation discovery capabilities:

| Flag | Function | Purpose |
|------|----------|---------|
| `-v`, `--version` | Version display | Shows current version, checks for updates |
| `-l`, `--list` | Installation list | Lists all available MLatom installations |

The version checking system [mlatom/MLatom.py:84-98]() queries PyPI for the latest version and notifies users of available updates. The installation listing system [mlatom/MLatom.py:99-136]() searches multiple locations including:

- Current installation directory
- PYTHONPATH directories  
- Site-packages directories

Sources: [mlatom/MLatom.py:84-136]()

## Error Handling and User Feedback

The CLI implements comprehensive error handling and user feedback mechanisms:

```mermaid
graph TB
    subgraph "Error Handling Chain"
        START["`User Input`"] --> VALIDATE["`Argument Validation
        args_class.py:695-738`"]
        VALIDATE --> TASK["`Task Execution`"]
        TASK --> RESULT["`Results`"]
    end
    
    subgraph "Error Types"
        ARG_ERR["`Argument Errors
        Missing task/method`"]
        TASK_ERR["`Task Errors
        File not found, etc.`"]
        SYS_ERR["`System Errors
        Program failures`"]
    end
    
    subgraph "User Feedback"
        HELP["`Help Display
        Doc.printDoc()`"]
        ERROR_MSG["`Error Messages
        stopper.stopMLatom()`"]
        WARNING["`Warning Messages
        Print statements`"]
    end
    
    VALIDATE --> ARG_ERR
    TASK --> TASK_ERR
    TASK --> SYS_ERR
    
    ARG_ERR --> HELP
    TASK_ERR --> ERROR_MSG
    SYS_ERR --> ERROR_MSG
    
    ARG_ERR --> WARNING
```

**Error Handling Flow**
Sources: [mlatom/args_class.py:695-738](), [mlatom/MLtasks.py:653-665]()

---