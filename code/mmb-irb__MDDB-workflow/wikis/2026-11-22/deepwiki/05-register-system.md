# Register System

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [model_workflow/analyses/rmsd_check.py](model_workflow/analyses/rmsd_check.py)
- [model_workflow/utils/register.py](model_workflow/utils/register.py)

</details>



The Register System is a component of the MDDB-workflow framework that provides test tracking and result caching capabilities. It allows the workflow to maintain state across multiple runs, avoid repeating tests that have already succeeded, and record warnings for issues that were allowed to proceed via mercy flags.

## Overview

The Register System serves several key functions:

1. **Test Tracking**: Records which tests have passed or failed across workflow runs
2. **Result Caching**: Stores computed values to avoid redundant calculations 
3. **Warning Management**: Maintains a list of warnings for test failures allowed via mercy flags
4. **Modification Tracking**: Monitors changes to input files to determine when cached results should be invalidated

The system operates by maintaining a JSON-based history file that records each workflow run, preserving important state information between executions.

Sources: [model_workflow/utils/register.py:11-151]()

## Architecture

```mermaid
classDiagram
    class Register {
        +file: File
        +call: str
        +date: str
        +mtimes: dict
        +cache: dict
        +tests: dict
        +warnings: list
        +entries: list
        +__init__(register_file: File)
        +to_dict(): dict
        +get_mtime(target_file: File): tuple
        +update_mtime(target_file: File)
        +is_file_new(target_file: File): bool
        +is_file_modified(target_file: File): bool
        +update_cache(key: str, value)
        +reset_cache()
        +update_test(key: str, value: bool)
        +get_warnings(tag: str): list
        +add_warning(tag: str, message: str)
        +remove_warnings(tag: str)
        +save()
    }
```

**Register Class Components:**

| Component | Type | Purpose |
|-----------|------|---------|
| `file` | File | Reference to the JSON file storing register data |
| `call` | str | Command line arguments used for current workflow run |
| `date` | str | Timestamp of current workflow execution |
| `mtimes` | dict | Maps filenames to modification timestamps |
| `cache` | dict | Stores computed values for reuse across runs |
| `tests` | dict | Maps test names to boolean results (pass/fail) |
| `warnings` | list | Collection of warning messages with tags |
| `entries` | list | Historical record of all workflow runs |

Sources: [model_workflow/utils/register.py:14-68]()

## Persistence Mechanism

The Register System maintains a file-based persistence mechanism that tracks workflow execution history. Each time the workflow runs, a new entry is added to the register file containing:

```mermaid
flowchart TD
    RegisterFile["Register File (JSON)"] --> Entries["Entries Array"]
    Entries --> Entry1["Entry 1"]
    Entries --> Entry2["Entry 2"]
    Entries --> EntryN["Entry N (Current)"]
    
    Entry1 --> Call1["call: Command line"]
    Entry1 --> Date1["date: Timestamp"]
    Entry1 --> MTimes1["mtimes: File modification times"]
    Entry1 --> Cache1["cache: Computed values"]
    Entry1 --> Tests1["tests: Test results"]
    Entry1 --> Warnings1["warnings: Test warnings"]
```

When a new Register instance is created, it:
1. Loads the existing register file (if it exists)
2. Inherits the previous state (cache, tests, warnings) from the last entry
3. Creates a new entry for the current run
4. Persists any changes via the `save()` method

This approach ensures that successful test results and calculated values persist across workflow runs, avoiding redundant computations.

Sources: [model_workflow/utils/register.py:15-54](), [model_workflow/utils/register.py:142-152]()

## File Modification Tracking

The Register System monitors input file modification times to intelligently determine when cached values should be invalidated.

```mermaid
sequenceDiagram
    participant Workflow as "MD Workflow"
    participant Register
    participant FileSystem
    
    Workflow->>Register: is_file_modified(file)
    Register->>FileSystem: Get current mtime
    FileSystem-->>Register: Current mtime
    Register->>Register: Compare with stored mtime
    Register-->>Workflow: true/false
    
    alt File Modified
        Workflow->>Register: reset_cache()
        Register->>Register: Clear cached values
    end
    
    Workflow->>Register: update_mtime(file)
    Register->>Register: Store new mtime
    Register->>FileSystem: Save register file
```

The `is_file_modified()` method checks if a file's current modification time differs from the previously recorded time, allowing the workflow to detect when input files have changed.

Sources: [model_workflow/utils/register.py:72-104]()

## Test Tracking

The Register System tracks test results using a simple key-value structure where:
- The key is a string identifier for the test (e.g., `TRAJECTORY_INTEGRITY_FLAG`)
- The value is a boolean indicating whether the test passed (`true`), failed (`false`), or was not applicable (`'na'`)

```mermaid
flowchart LR
    Test["Test Function"] -->|"run test"| Result["Test Result"]
    Result -->|"success"| Pass["register.update_test(key, true)"]
    Result -->|"failure + mercy"| Warn["register.add_warning(key, message)
register.update_test(key, false)"]
    Result -->|"failure + no mercy"| Fail["raise TestFailure"]
    Result -->|"N/A"| NA["register.update_test(key, 'na')"]
```

When a test is about to run, it first checks `register.tests.get(TEST_KEY, None)` to determine if the test has already passed in a previous run. If so, the test can be skipped.

Sources: [model_workflow/analyses/rmsd_check.py:36-42](), [model_workflow/utils/register.py:116-119]()

## Warning Management

The Register System maintains warnings for tests that failed but were allowed to proceed because they were in the "mercy" list:

```mermaid
flowchart TD
    AddWarning["register.add_warning(tag, message)"] --> WarnList["warnings list"]
    GetWarnings["register.get_warnings(tag)"] --> FilteredWarnings["Filtered warnings by tag"]
    RemoveWarnings["register.remove_warnings(tag)"] --> UpdatedList["Updated warnings list"]
    
    WarnList --> Metadata["Included in metadata"]
    WarnList --> Console["Displayed to user"]
```

Warning records include:
- A tag identifier (typically matching the test name)
- A message describing the issue

These warnings serve as both documentation of potential issues and as alerts to users about aspects of the data that might require attention.

Sources: [model_workflow/utils/register.py:121-140](), [model_workflow/analyses/rmsd_check.py:132-135]()

## Integration Example: Trajectory Integrity Testing

The following diagram illustrates how the Register System integrates with the trajectory integrity test:

```mermaid
sequenceDiagram
    participant MD as "MD Class"
    participant Check as "check_trajectory_integrity"
    participant Register
    
    MD->>Check: check_trajectory_integrity(...)
    
    Check->>Register: tests.get(TRAJECTORY_INTEGRITY_FLAG, None)
    alt Test already passed
        Register-->>Check: true
        Check-->>MD: true (Skip test)
    else Test not passed yet
        Register-->>Check: None
        Check->>Register: remove_warnings(TRAJECTORY_INTEGRITY_FLAG)
        Check->>Check: Perform integrity checks on trajectory
        
        alt Test passes
            Check->>Register: update_test(TRAJECTORY_INTEGRITY_FLAG, true)
            Register->>Register: Save to file
            Check-->>MD: true
        else Test fails but in mercy list
            Check->>Register: add_warning(TRAJECTORY_INTEGRITY_FLAG, message)
            Check->>Register: update_test(TRAJECTORY_INTEGRITY_FLAG, false)
            Register->>Register: Save to file
            Check-->>MD: false
        else Test fails and not in mercy list
            Check-->>MD: raise TestFailure
        end
    end
```

This pattern is common throughout the codebase, where tests first check the register to see if they need to run, and then update the register with their results.

Sources: [model_workflow/analyses/rmsd_check.py:19-145]()

## Caching Mechanism

The Register's caching mechanism allows computationally expensive results to be stored and reused:

```mermaid
flowchart TD
    Workflow["MD Workflow"] -->|"Need computed value"| CacheCheck["Check cache"]
    CacheCheck -->|"Value exists"| UseCache["Use cached value"]
    CacheCheck -->|"Value missing"| Compute["Compute value"]
    Compute -->|"Store result"| UpdateCache["register.update_cache(key, value)"]
    UpdateCache --> SaveRegister["register.save()"]
    
    InputCheck["Check if inputs modified"] -->|"Modified"| ResetCache["register.reset_cache()"]
    ResetCache --> SaveRegister
```

The cache is implemented as a simple key-value store within the register file, allowing any serializable Python object to be stored for later retrieval.

Sources: [model_workflow/utils/register.py:105-114]()

## Best Practices

When working with the Register System:

1. Use consistent keys for tests and cached values
2. Always check the register before performing expensive calculations
3. Update file modification times when files are processed
4. Use warning tags that match test names for easier filtering
5. Remember that mercy flags allow failures to proceed but warnings will still be recorded

## Integration with MD Class

The Register System is tightly integrated with the MD class, which manages individual molecular dynamics simulations:

```mermaid
flowchart LR
    MD["MD Class"] -->|"creates"| Register["Register"]
    MD -->|"executes"| Tests["Tests"]
    Tests -->|"record results"| Register
    MD -->|"caches values"| Register
    MD -->|"retrieves results"| Register
    Register -->|"provides status"| MD
```

The MD class initializes a Register for each simulation and uses it throughout the processing pipeline to track test statuses and cache intermediate results.

Sources: [model_workflow/analyses/rmsd_check.py:19-145]()

---