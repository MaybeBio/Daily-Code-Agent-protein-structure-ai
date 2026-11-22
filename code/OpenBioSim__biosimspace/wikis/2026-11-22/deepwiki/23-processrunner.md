# ProcessRunner

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [python/BioSimSpace/FreeEnergy/__init__.py](python/BioSimSpace/FreeEnergy/__init__.py)
- [python/BioSimSpace/Process/_process_runner.py](python/BioSimSpace/Process/_process_runner.py)
- [python/BioSimSpace/Protocol/__init__.py](python/BioSimSpace/Protocol/__init__.py)

</details>



The ProcessRunner provides centralized management and execution of multiple simulation processes within BioSimSpace. It is designed for scenarios requiring coordinated execution of multiple related simulations, such as free energy calculations across lambda windows or parameter sweeps. The ProcessRunner handles process lifecycle management, resource allocation, error recovery, and directory organization.

For information about individual Process classes and MD engine integration, see [Process Classes and MD Engines](#4.2). For workflow orchestration using Gateway nodes, see [Gateway System](#7.1).

## Purpose and Scope

The ProcessRunner addresses the need to execute multiple simulation processes in a coordinated manner while avoiding the complexity of external process management tools. It provides both serial and parallel execution modes with built-in retry logic, state tracking, and resource management suitable for computational chemistry workflows.

Sources: [python/BioSimSpace/Process/_process_runner.py:39-61]()

## Architecture Overview

The ProcessRunner manages a collection of Process objects through a unified interface, providing state tracking, execution control, and directory management:

```mermaid
graph TB
    subgraph "ProcessRunner"
        RUNNER["ProcessRunner"] 
        PROCESSES["_processes[]"]
        THREAD["_thread"]
        WORKDIR["_work_dir"]
    end
    
    subgraph "Process Management"
        QUEUE["Queued Processes"]
        RUNNING["Running Processes"] 
        ERROR["Error Processes"]
        FINISHED["Finished Processes"]
    end
    
    subgraph "Execution Control"
        SERIAL["Serial Execution"]
        PARALLEL["Parallel Execution"]
        BATCH["Batch Size Control"]
        RETRY["Retry Logic"]
    end
    
    subgraph "External Process Objects"
        GROMACS["Gromacs Process"]
        AMBER["Amber Process"]
        OPENMM["OpenMM Process"]
        SOMD["SOMD Process"]
    end
    
    RUNNER --> PROCESSES
    RUNNER --> THREAD
    RUNNER --> WORKDIR
    
    PROCESSES --> QUEUE
    PROCESSES --> RUNNING
    PROCESSES --> ERROR
    PROCESSES --> FINISHED
    
    RUNNER --> SERIAL
    RUNNER --> PARALLEL
    PARALLEL --> BATCH
    RUNNER --> RETRY
    
    PROCESSES --> GROMACS
    PROCESSES --> AMBER
    PROCESSES --> OPENMM
    PROCESSES --> SOMD
```

**ProcessRunner Core Architecture**

The ProcessRunner maintains internal state through several key components: a list of Process objects, a background thread for execution management, and a working directory for file organization.

Sources: [python/BioSimSpace/Process/_process_runner.py:109-131]()

## Process State Management

The ProcessRunner tracks each process through distinct states during execution lifecycle:

```mermaid
stateDiagram-v2
    [*] --> Queued: "Process Added"
    Queued --> Running: "start()"
    Running --> Finished: "Success"
    Running --> Error: "Failure"
    Error --> Queued: "Retry (< max_retries)"
    Error --> Finished: "Max Retries Reached"
    Finished --> [*]
    
    note right of Error: "_num_failed" counter\nincremented on failure
    note right of Queued: "_is_queued = True"
    note right of Running: "isRunning() = True"
```

**Process State Lifecycle**

Each process maintains internal state flags including `_is_queued`, `_is_finished`, and `_num_failed` counters for retry logic.

The ProcessRunner provides methods to query process states:

| Method | Return Type | Description |
|--------|-------------|-------------|
| `nQueued()` | int | Number of queued processes |
| `nRunning()` | int | Number of currently running processes |
| `nError()` | int | Number of processes in error state |
| `queued()` | [int] | Indices of queued processes |
| `running()` | [int] | Indices of running processes |
| `errored()` | [int] | Indices of errored processes |

Sources: [python/BioSimSpace/Process/_process_runner.py:127-131](), [python/BioSimSpace/Process/_process_runner.py:331-424]()

## Execution Modes

The ProcessRunner supports two primary execution modes controlled through the `startAll()` method:

### Serial Execution

In serial mode (`serial=True`), processes execute sequentially with each process completing before the next begins:

```mermaid
sequenceDiagram
    participant PR as "ProcessRunner"
    participant P1 as "Process 1"
    participant P2 as "Process 2" 
    participant P3 as "Process 3"
    
    PR->>P1: "start()"
    P1-->>PR: "running"
    PR->>P1: "wait()"
    P1-->>PR: "finished"
    
    PR->>P2: "start()"
    P2-->>PR: "running"
    PR->>P2: "wait()"
    P2-->>PR: "finished"
    
    PR->>P3: "start()"
    P3-->>PR: "running"
    PR->>P3: "wait()"
    P3-->>PR: "finished"
```

**Serial Execution Flow**

### Parallel Execution

In parallel mode (`serial=False`), processes execute concurrently up to a specified batch size limit:

```mermaid
graph TB
    subgraph "Batch Management"
        BATCHSIZE["batch_size parameter"]
        CPUCOUNT["multiprocessing.cpu_count()"]
        BATCHSIZE -.-> CPUCOUNT
    end
    
    subgraph "Process Pool"
        P1["Process 1"]
        P2["Process 2"]
        P3["Process 3"]
        PN["Process N"]
    end
    
    subgraph "Execution Loop"
        CHECK["Check Running < batch_size"]
        SUBMIT["Submit Queued Processes"]
        MONITOR["Monitor Running Processes"]
        SLEEP["Sleep 5 seconds"]
    end
    
    CHECK --> SUBMIT
    SUBMIT --> P1
    SUBMIT --> P2
    SUBMIT --> P3
    SUBMIT --> MONITOR
    MONITOR --> SLEEP
    SLEEP --> CHECK
```

**Parallel Execution Batch Management**

Sources: [python/BioSimSpace/Process/_process_runner.py:526-592](), [python/BioSimSpace/Process/_process_runner.py:641-736]()

## Error Handling and Retry Logic

The ProcessRunner implements automatic retry logic for failed processes with configurable retry limits:

```mermaid
flowchart TD
    START["Process Starts"] --> RUNNING["Process Running"]
    RUNNING --> SUCCESS["Process Success"]
    RUNNING --> FAILURE["Process Failure"]
    
    FAILURE --> CHECK_RETRIES{"_num_failed < max_retries?"}
    CHECK_RETRIES -->|Yes| INCREMENT["_num_failed++"]
    INCREMENT --> REQUEUE["Add to Queue"]
    REQUEUE --> RETRY["Retry Process"]
    RETRY --> RUNNING
    
    CHECK_RETRIES -->|No| FINAL_ERROR["Final Error State"]
    SUCCESS --> FINISHED["Process Finished"]
    FINAL_ERROR --> FINISHED
```

**Error Handling and Retry Flow**

The retry mechanism tracks failure counts per process and automatically requeues failed processes until the maximum retry limit is reached (default 5 retries).

Key methods for error management:

- `restartFailed()`: Manually restart all processes in error state
- `killAll()`: Terminate all processes and set `_is_killed` flag
- `nError()`: Query number of processes in error state

Sources: [python/BioSimSpace/Process/_process_runner.py:653-668](), [python/BioSimSpace/Process/_process_runner.py:714-732](), [python/BioSimSpace/Process/_process_runner.py:788-803]()

## Directory Management

The ProcessRunner automatically organizes process working directories through the `_nest_directories()` method:

```mermaid
graph TB
    subgraph "Runner Directory Structure"
        RUNNER_DIR["ProcessRunner work_dir/"]
        PROC1_DIR["ProcessRunner work_dir/process1/"]
        PROC2_DIR["ProcessRunner work_dir/process2/"]
        PROC3_DIR["ProcessRunner work_dir/process3/"]
    end
    
    subgraph "Original Process Directories"
        ORIG1["/tmp/process1/"]
        ORIG2["/tmp/process2/"]
        ORIG3["/tmp/process3/"]
    end
    
    ORIG1 -.-> PROC1_DIR
    ORIG2 -.-> PROC2_DIR  
    ORIG3 -.-> PROC3_DIR
    
    RUNNER_DIR --> PROC1_DIR
    RUNNER_DIR --> PROC2_DIR
    RUNNER_DIR --> PROC3_DIR
```

**Directory Nesting Structure**

When a ProcessRunner is initialized with a `work_dir`, it creates new Process objects with working directories nested under the runner's directory. This prevents file conflicts and organizes output files hierarchically.

The nesting process handles engine-specific Process constructors differently, particularly for SOMD processes which require additional platform parameters.

Sources: [python/BioSimSpace/Process/_process_runner.py:123-126](), [python/BioSimSpace/Process/_process_runner.py:822-877]()

## Integration with BioSimSpace Ecosystem

The ProcessRunner integrates with several BioSimSpace components to enable complex simulation workflows:

```mermaid
graph TB
    subgraph "Free Energy Calculations"
        LAMBDA_WINDOWS["Lambda Windows"]
        RELATIVE_FEP["Relative FEP"]
        ATM_METHOD["ATM Method"]
    end
    
    subgraph "Process Management"
        PROCESS_RUNNER["ProcessRunner"]
        GROMACS_PROC["Gromacs Process"]
        AMBER_PROC["Amber Process"]
        SOMD_PROC["SOMD Process"]
        OPENMM_PROC["OpenMM Process"]
    end
    
    subgraph "System Preparation"
        SYSTEM["System Objects"]
        PROTOCOL["Protocol Objects"]
    end
    
    subgraph "Analysis Pipeline"
        RESULTS["Simulation Results"]
        TRAJECTORY["Trajectory Analysis"]
        FREE_ENERGY["Free Energy Analysis"]
    end
    
    LAMBDA_WINDOWS --> PROCESS_RUNNER
    RELATIVE_FEP --> PROCESS_RUNNER
    ATM_METHOD --> PROCESS_RUNNER
    
    SYSTEM --> GROMACS_PROC
    SYSTEM --> AMBER_PROC
    SYSTEM --> SOMD_PROC
    SYSTEM --> OPENMM_PROC
    
    PROTOCOL --> GROMACS_PROC
    PROTOCOL --> AMBER_PROC
    PROTOCOL --> SOMD_PROC
    PROTOCOL --> OPENMM_PROC
    
    PROCESS_RUNNER --> GROMACS_PROC
    PROCESS_RUNNER --> AMBER_PROC
    PROCESS_RUNNER --> SOMD_PROC
    PROCESS_RUNNER --> OPENMM_PROC
    
    GROMACS_PROC --> RESULTS
    AMBER_PROC --> RESULTS
    SOMD_PROC --> RESULTS
    OPENMM_PROC --> RESULTS
    
    RESULTS --> TRAJECTORY
    RESULTS --> FREE_ENERGY
```

**ProcessRunner Integration in BioSimSpace Workflow**

The ProcessRunner is particularly important for free energy calculations where multiple simulations must be coordinated across lambda windows. It provides the infrastructure for managing these multi-stage calculations while maintaining BioSimSpace's unified interface to different MD engines.

Common usage patterns include:
- Free energy perturbation calculations with multiple lambda values
- Parameter sweeps across different simulation conditions  
- Replica exchange simulations requiring coordinated process management
- Complex workflows requiring staged execution with dependencies

Sources: [python/BioSimSpace/Process/_process_runner.py:40-50](), [python/BioSimSpace/FreeEnergy/__init__.py:22-48](), [python/BioSimSpace/Protocol/__init__.py:40-54]()

---