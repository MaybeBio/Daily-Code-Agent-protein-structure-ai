# Task Management and Arguments

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [mlatom/MLtasks.py](mlatom/MLtasks.py)
- [mlatom/args_class.py](mlatom/args_class.py)
- [mlatom/interfaces/xtb_interface.py](mlatom/interfaces/xtb_interface.py)

</details>



This page documents MLatom's command-line interface task management and argument parsing system. It covers how user input is parsed, validated, and dispatched to appropriate task implementations. For information about the main entry point and execution flow, see [Entry Point and Execution](#3.1).

## Architecture Overview

The CLI system consists of two main components: argument parsing handled by the `mlatom_args` class, and task dispatch managed by the `CLItasks` class. The system supports both legacy Fortran implementations (MLatomF) and modern Python implementations for various computational tasks.

```mermaid
flowchart TD
    A["User Input"] --> B["mlatom_args.parse()"]
    B --> C["Argument Validation"]
    C --> D["Task Identification"]
    D --> E["CLItasks.run()"]
    E --> F{{"Task Route Decision"}}
    F -->|"MLatomF Compatible"| G["run_with_mlatomF()"]
    F -->|"Python Implementation"| H["Task Function"]
    G --> I["interface_MLatomF.run()"]
    H --> J["Task-Specific Logic"]
    I --> K["Results"]
    J --> K
```

Sources: [mlatom/args_class.py:645-656](), [mlatom/MLtasks.py:25-29](), [mlatom/MLtasks.py:31-40]()

## Argument Parsing System

### Core Classes

The argument parsing is built on a hierarchical class structure with specialized handling for MLatom's diverse parameter set:

```mermaid
classDiagram
    class ArgsBase {
        +data: AttributeDict
        +add_default_dict_args()
        +parse_input_content()
        +args_string_list()
        +_multi_level_dict()
    }
    
    class mlatom_args {
        +_task_list: List[str]
        +_method_list: List[str] 
        +parse(argsraw)
        +_checkArgs()
        +_check_hyperopt()
        +task: str
        +args2pass: List[str]
    }
    
    class AttributeDict {
        +lower_key_set: Set
        +lower_key_to_key: Dict
        +merge_dict()
        +key_in_dict()
    }
    
    ArgsBase <|-- mlatom_args
    ArgsBase --> AttributeDict
```

Sources: [mlatom/args_class.py:153-172](), [mlatom/args_class.py:401-407](), [mlatom/args_class.py:53-62]()

### Supported Tasks and Methods

The system defines comprehensive lists of supported computational tasks and quantum chemistry methods:

| Task Category | Examples | Implementation |
|---------------|----------|----------------|
| ML Tasks | `useMLmodel`, `createMLmodel`, `estAccMLmodel` | Python/MLatomF |
| Data Tasks | `XYZ2SMI`, `sample`, `analyze` | Mixed |
| Simulation Tasks | `geomopt`, `freq`, `MD`, `irc` | Python |
| Analysis Tasks | `crossSection`, `MLQD`, `al` | Python |

Sources: [mlatom/args_class.py:410-437](), [mlatom/args_class.py:444]()

### Argument Processing Flow

```mermaid
sequenceDiagram
    participant U as "User Input"
    participant P as "mlatom_args.parse()"
    participant V as "_checkArgs()"
    participant H as "_check_hyperopt()" 
    participant T as "Task Dispatcher"
    
    U->>P: Raw arguments
    P->>P: parse_input_content()
    P->>V: Validate arguments
    V->>V: Identify task
    V->>V: Set method flags
    P->>H: Process hyperparameters
    P->>T: Validated args
```

Sources: [mlatom/args_class.py:645-656](), [mlatom/args_class.py:695-738](), [mlatom/args_class.py:680-693]()

## Task Dispatch Mechanism

### CLItasks Class

The `CLItasks` class serves as the central dispatcher, routing tasks between MLatomF (Fortran) and Python implementations based on compatibility and feature requirements:

```mermaid
flowchart LR
    A["CLItasks.__init__(args)"] --> B["CLItasks.run()"]
    B --> C{{"Check MLatomF Compatibility"}}
    C -->|"Compatible Task"| D["run_with_mlatomF()"]
    C -->|"Python Only"| E["globals()[task](args)"]
    D --> F["interface_MLatomF.run()"]
    E --> G["Task Function Call"]
    
    H["MLatomF_tasks List"] --> C
    I["Method Checks"] --> C
    J["Hyperopt Checks"] --> C
```

Sources: [mlatom/MLtasks.py:14-29](), [mlatom/MLtasks.py:15-22]()

### Task Implementation Categories

The system implements tasks through several patterns:

| Pattern | Examples | Description |
|---------|----------|-------------|
| Direct Functions | `useMLmodel()`, `createMLmodel()` | Core ML workflow tasks |
| Simulation Tasks | `geomopt()`, `freq()`, `MD()` | Molecular simulation workflows |
| Data Processing | `XYZ2SMI()`, `sample()` | File format conversion and sampling |
| Interface Wrappers | `al()`, `MLQD()` | Calls to specialized modules |

Sources: [mlatom/MLtasks.py:43-651]()

## Key Task Functions

### Machine Learning Tasks

The core ML tasks follow a consistent pattern of data loading, model setup, and execution:

```mermaid
flowchart TD
    A["useMLmodel(args)"] --> B["loading_data()"]
    B --> C["loading_model()"]
    C --> D["predicting()"]
    D --> E["saving_predictions()"]
    
    F["createMLmodel(args)"] --> G["loading_data()"]
    G --> H["sampling()"]
    H --> I["loading_model()"]
    I --> J["training()"]
    
    K["estAccMLmodel(args)"] --> L["Cross-validation Logic"]
    L --> M["training() + predicting()"]
    M --> N["analyzing()"]
```

Sources: [mlatom/MLtasks.py:43-77](), [mlatom/MLtasks.py:79-93](), [mlatom/MLtasks.py:95-148]()

### Reusable Utility Functions

The system provides several reusable functions that support multiple tasks:

| Function | Purpose | Key Parameters |
|----------|---------|----------------|
| `loading_data()` | Load molecular databases from files | `XYZfile`, `Yfile`, `YgradXYZfile` |
| `loading_model()` | Instantiate ML models or methods | `MLprog`, `method`, `MLmodelIn` |
| `sampling()` | Generate train/test splits | `sampling`, `Ntrain`, `CVtest` |
| `predicting()` | Run model predictions | `value`, `gradient`, `hessian` |
| `analyzing()` | Compute statistical metrics | `ref_value`, `est_value` |

Sources: [mlatom/MLtasks.py:653-666](), [mlatom/MLtasks.py:693-717](), [mlatom/MLtasks.py:719-825](), [mlatom/MLtasks.py:827-844](), [mlatom/MLtasks.py:887-1013]()

## Integration with Model Framework

The task system integrates with MLatom's model framework through standardized interfaces:

```mermaid
flowchart LR
    A["Task Function"] --> B["loading_model(args)"]
    B --> C{{"Method vs ML Model"}}
    C -->|"Method"| D["loading_method()"]
    C -->|"ML Model"| E["Model Class Factory"]
    D --> F["models.methods()"]
    E --> G["models.kreg/ani/mace/etc"]
    F --> H["QM Interface"]
    G --> I["ML Interface"]
    
    J["args.method"] --> D
    K["args.MLprog"] --> E
    L["args.MLmodelIn"] --> E
```

Sources: [mlatom/MLtasks.py:693-717](), [mlatom/MLtasks.py:668-691]()

## Error Handling and Validation

The argument validation system performs several checks to ensure proper task execution:

### Task Detection Logic

```mermaid
flowchart TD
    A["_checkArgs()"] --> B{{"Count Active Tasks"}}
    B -->|"One Task"| C["Set _task"]
    B -->|"Multiple Tasks"| D{{"Special Combinations?"}}
    B -->|"No Tasks"| E{{"Method Specified?"}}
    
    D -->|"selfCorrect"| F["task = 'selfCorrect'"]
    D -->|"geomopt + freq"| G["task = 'optfreq'"]
    D -->|"ts + freq"| H["task = 'tsfreq'"]
    D -->|"Other"| I["Use First Task"]
    
    E -->|"Yes"| J["task = 'useMLmodel'"]
    E -->|"No"| K["Print Help & Exit"]
```

Sources: [mlatom/args_class.py:695-738]()

### Hyperparameter Optimization Setup

The system automatically detects and configures hyperparameter optimization based on argument patterns:

```mermaid
flowchart LR
    A["_check_hyperopt()"] --> B["Scan args2pass"]
    B --> C{{"Find 'hyperopt.x(...)' pattern?"}}
    C -->|"Yes"| D["Extract hyperparameters"]
    C -->|"No"| E["Standard execution"]
    D --> F["Set optimization_algorithm"]
    F --> G["Build hyperparameter_optimization dict"]
```

Sources: [mlatom/args_class.py:680-693]()

This architecture provides a flexible and extensible system for managing diverse computational chemistry tasks while maintaining compatibility with legacy components and supporting advanced features like hyperparameter optimization and cross-validation.

---