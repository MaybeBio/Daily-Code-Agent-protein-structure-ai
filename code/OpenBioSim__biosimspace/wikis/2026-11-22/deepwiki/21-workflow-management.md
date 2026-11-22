# Workflow Management

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [python/BioSimSpace/FreeEnergy/__init__.py](python/BioSimSpace/FreeEnergy/__init__.py)
- [python/BioSimSpace/Gateway/_node.py](python/BioSimSpace/Gateway/_node.py)
- [python/BioSimSpace/Gateway/_requirements.py](python/BioSimSpace/Gateway/_requirements.py)
- [python/BioSimSpace/Process/_process_runner.py](python/BioSimSpace/Process/_process_runner.py)
- [python/BioSimSpace/Protocol/__init__.py](python/BioSimSpace/Protocol/__init__.py)
- [python/BioSimSpace/Sandpit/Exscientia/Gateway/_node.py](python/BioSimSpace/Sandpit/Exscientia/Gateway/_node.py)
- [python/BioSimSpace/Sandpit/Exscientia/Gateway/_requirements.py](python/BioSimSpace/Sandpit/Exscientia/Gateway/_requirements.py)
- [python/BioSimSpace/Sandpit/Exscientia/MD/_utils.py](python/BioSimSpace/Sandpit/Exscientia/MD/_utils.py)
- [python/BioSimSpace/Types/__init__.py](python/BioSimSpace/Types/__init__.py)

</details>



BioSimSpace's workflow management system provides tools for creating reusable computational workflows and managing complex simulation processes. This system enables users to build interoperable workflow components that can run in various environments (Jupyter notebooks, command-line, workflow engines) and efficiently manage multiple simulation processes.

For information about specific simulation execution, see [Simulation Execution](#4). For details about free energy calculation workflows, see [Free Energy Calculations](#5).

## Architecture Overview

The workflow management system consists of two primary components that work together to provide comprehensive workflow capabilities:

```mermaid
graph TB
    subgraph "Workflow Management System"
        subgraph "Gateway System"
            NODE["Node"]
            REQ["Requirements"]
            VAL["Validation"]
            ENV["Multi-Environment Support"]
        end
        
        subgraph "Process Management"
            RUNNER["ProcessRunner"]
            BATCH["Batch Processing"]
            MONITOR["Process Monitoring"]
            RETRY["Error Handling"]
        end
    end
    
    subgraph "Execution Environments"
        JUPYTER["Jupyter Notebooks"]
        CLI["Command Line"]
        KNIME["Knime Workflow Engine"]
        CWL["Common Workflow Language"]
    end
    
    subgraph "Simulation Components"
        PROC["Process Classes"]
        PROT["Protocol Objects"]
        SYS["System Objects"]
    end
    
    NODE --> JUPYTER
    NODE --> CLI
    NODE --> KNIME
    NODE --> CWL
    
    RUNNER --> PROC
    NODE --> RUNNER
    
    REQ --> VAL
    VAL --> NODE
    
    PROC --> PROT
    PROC --> SYS
```

Sources: [python/BioSimSpace/Gateway/_node.py:253-280](), [python/BioSimSpace/Process/_process_runner.py:39-61]()

## Gateway System

The Gateway system provides a framework for creating reusable workflow components called nodes. These nodes collect and validate user input, document workflow intentions, and ensure output validity across different execution environments.

```mermaid
graph LR
    subgraph "Node Creation"
        NODE_INIT["Node.__init__()"]
        ADD_INPUT["addInput()"]
        ADD_OUTPUT["addOutput()"]
        REQ_TYPES["Requirement Types"]
    end
    
    subgraph "Input Processing"
        GET_INPUT["getInput()"]
        VALIDATE["_validateInput()"]
        WIDGETS["Jupyter Widgets"]
        ARGPARSE["CLI Arguments"]
    end
    
    subgraph "Output Handling"
        SET_OUTPUT["setOutput()"]
        VALIDATE_OUT["validate()"]
        FILE_NAMING["Strict File Naming"]
    end
    
    subgraph "Requirements System"
        BOOLEAN["Boolean"]
        INTEGER["Integer"]
        FLOAT["Float"]
        STRING["String"]
        FILE["File"]
        FILESET["FileSet"]
        UNITS["Unit Types"]
    end
    
    NODE_INIT --> ADD_INPUT
    ADD_INPUT --> REQ_TYPES
    REQ_TYPES --> REQUIREMENTS
    
    GET_INPUT --> VALIDATE
    VALIDATE --> WIDGETS
    VALIDATE --> ARGPARSE
    
    SET_OUTPUT --> VALIDATE_OUT
    VALIDATE_OUT --> FILE_NAMING
    
    REQUIREMENTS --> BOOLEAN
    REQUIREMENTS --> INTEGER
    REQUIREMENTS --> FLOAT
    REQUIREMENTS --> STRING
    REQUIREMENTS --> FILE
    REQUIREMENTS --> FILESET
    REQUIREMENTS --> UNITS
```

Sources: [python/BioSimSpace/Gateway/_node.py:419-461](), [python/BioSimSpace/Gateway/_requirements.py:61-348]()

### Node Interface

The `Node` class serves as the primary interface for workflow components. Key methods include:

| Method | Purpose | Environment Support |
|--------|---------|-------------------|
| `addInput(name, requirement)` | Define input parameters | All |
| `addOutput(name, requirement)` | Define output parameters | All |
| `getInput(name)` | Retrieve validated input | All |
| `setOutput(name, value)` | Set output values | All |
| `validate()` | Validate all outputs | All |
| `showControls()` | Display Jupyter widgets | Jupyter only |

Sources: [python/BioSimSpace/Gateway/_node.py:419-438](), [python/BioSimSpace/Gateway/_node.py:938-967](), [python/BioSimSpace/Gateway/_node.py:1027-1057]()

### Requirement Types

The requirements system provides strongly-typed input/output validation with support for physical units:

**Basic Types:**
- `Boolean` - Boolean flags with defaults
- `Integer` - Integer values with range validation  
- `Float` - Floating-point values with constraints
- `String` - Text with optional allowed values

**File Types:**
- `File` - Single file with existence validation
- `FileSet` - Multiple files with archive support

**Physical Unit Types:**
- `Length`, `Area`, `Volume` - Spatial measurements
- `Energy`, `Mass`, `Pressure` - Physical properties
- `Temperature`, `Time` - Simulation parameters
- `Charge` - Electrostatic properties

Sources: [python/BioSimSpace/Gateway/_requirements.py:350-576](), [python/BioSimSpace/Gateway/_requirements.py:733-851]()

## ProcessRunner

The `ProcessRunner` class manages multiple simulation processes with support for both serial and parallel execution modes. It provides resource management, error handling, and progress monitoring for complex workflows.

```mermaid
graph TB
    subgraph "ProcessRunner Lifecycle"
        INIT["ProcessRunner.__init__()"]
        ADD_PROC["addProcess()"]
        START_ALL["startAll()"]
        MONITOR["Process Monitoring"]
        COMPLETE["Completion"]
    end
    
    subgraph "Execution Modes"
        SERIAL["Serial Execution"]
        PARALLEL["Parallel Execution"]
        BATCH["Batch Processing"]
    end
    
    subgraph "Process States"
        QUEUED["_is_queued"]
        RUNNING["isRunning()"]
        ERROR["isError()"]
        FINISHED["_is_finished"]
    end
    
    subgraph "Management Operations"
        N_RUNNING["nRunning()"]
        N_QUEUED["nQueued()"]
        N_ERROR["nError()"]
        RESTART["restartFailed()"]
        KILL_ALL["killAll()"]
    end
    
    INIT --> ADD_PROC
    ADD_PROC --> START_ALL
    START_ALL --> SERIAL
    START_ALL --> PARALLEL
    PARALLEL --> BATCH
    
    START_ALL --> MONITOR
    MONITOR --> QUEUED
    MONITOR --> RUNNING
    MONITOR --> ERROR
    MONITOR --> FINISHED
    
    MONITOR --> N_RUNNING
    MONITOR --> N_QUEUED
    MONITOR --> N_ERROR
    ERROR --> RESTART
```

Sources: [python/BioSimSpace/Process/_process_runner.py:63-131](), [python/BioSimSpace/Process/_process_runner.py:526-592]()

### Execution Modes

**Serial Execution:**
Processes run sequentially with automatic retry on failure. Each process completes before the next begins.

**Parallel Execution:**
Multiple processes run simultaneously with configurable batch sizes. The system monitors resource usage and manages process queues.

**Key Parameters:**
- `serial` - Boolean flag for execution mode
- `batch_size` - Maximum concurrent processes (defaults to `cpu_count()`)
- `max_retries` - Retry attempts for failed processes (default: 5)

Sources: [python/BioSimSpace/Process/_process_runner.py:641-678](), [python/BioSimSpace/Process/_process_runner.py:686-736]()

### Process State Management

The ProcessRunner tracks process states through internal flags and provides query methods:

| State Method | Purpose | Internal Flag |
|-------------|---------|---------------|
| `isQueued()` | Check queued processes | `_is_queued` |
| `isRunning()` | Check active processes | Process-specific |
| `isError()` | Check failed processes | `_is_error` |
| `nProcesses()` | Total process count | `len(_processes)` |

Sources: [python/BioSimSpace/Process/_process_runner.py:331-367](), [python/BioSimSpace/Process/_process_runner.py:447-487]()

## Integration with Simulation Components

The workflow management system integrates with BioSimSpace's simulation infrastructure to enable complex computational workflows.

```mermaid
graph LR
    subgraph "Workflow Input"
        FILES["Input Files"]
        PARAMS["Parameters"]
        PROTOCOLS["Protocol Selection"]
    end
    
    subgraph "Gateway Processing"
        NODE_INPUT["Node.getInput()"]
        VALIDATION["Input Validation"]
        SYSTEM_CREATE["System Creation"]
    end
    
    subgraph "Process Management"
        PROC_CREATE["Process Creation"]
        RUNNER_ADD["ProcessRunner.addProcess()"]
        EXECUTION["Parallel/Serial Execution"]
    end
    
    subgraph "Simulation Execution"
        MD_ENGINES["MD Engines"]
        GROMACS["GROMACS Process"]
        AMBER["AMBER Process"]
        OPENMM["OpenMM Process"]
        SOMD["SOMD Process"]
    end
    
    subgraph "Output Processing"
        RESULTS["Simulation Results"]
        ANALYSIS["Trajectory Analysis"]
        NODE_OUTPUT["Node.setOutput()"]
    end
    
    FILES --> NODE_INPUT
    PARAMS --> NODE_INPUT
    PROTOCOLS --> NODE_INPUT
    
    NODE_INPUT --> VALIDATION
    VALIDATION --> SYSTEM_CREATE
    SYSTEM_CREATE --> PROC_CREATE
    
    PROC_CREATE --> RUNNER_ADD
    RUNNER_ADD --> EXECUTION
    
    EXECUTION --> MD_ENGINES
    MD_ENGINES --> GROMACS
    MD_ENGINES --> AMBER
    MD_ENGINES --> OPENMM
    MD_ENGINES --> SOMD
    
    GROMACS --> RESULTS
    AMBER --> RESULTS
    OPENMM --> RESULTS
    SOMD --> RESULTS
    
    RESULTS --> ANALYSIS
    ANALYSIS --> NODE_OUTPUT
```

Sources: [python/BioSimSpace/Gateway/_node.py:1027-1057](), [python/BioSimSpace/Process/_process_runner.py:214-256]()

## Common Workflow Patterns

**Energy Minimization Node:**
```python
node = BSS.Gateway.Node("Perform energy minimisation")
node.addInput("files", BSS.Gateway.FileSet(help="Molecular input files"))
node.addInput("steps", BSS.Gateway.Integer(help="Minimisation steps", default=10000))
node.addOutput("minimised", BSS.Gateway.FileSet(help="Minimised system"))
```

**Multi-Lambda Free Energy Calculation:**
```python
runner = BSS.ProcessRunner(processes, name="FEP_calculation")
runner.startAll(serial=False, batch_size=4, max_retries=3)
```

Sources: [python/BioSimSpace/Gateway/_node.py:265-279](), [python/BioSimSpace/Process/_process_runner.py:526-548]()

---