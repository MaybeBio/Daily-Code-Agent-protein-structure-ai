# Utility Functions

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [openmmtools/scripts/test_openmm_platforms.py](openmmtools/scripts/test_openmm_platforms.py)
- [openmmtools/tests/test_utils.py](openmmtools/tests/test_utils.py)
- [openmmtools/utils/__init__.py](openmmtools/utils/__init__.py)
- [openmmtools/utils/equilibration.py](openmmtools/utils/equilibration.py)
- [openmmtools/utils/utils.py](openmmtools/utils/utils.py)

</details>



OpenMMTools provides a collection of utility functions that assist with various aspects of molecular dynamics simulations using OpenMM. These utilities simplify common tasks such as managing temporary directories, timing code execution, working with quantities and units, interacting with different hardware platforms, serializing objects, and performing system equilibration.

## Utility Categories Overview

This diagram shows the major categories of utility functions available in OpenMMTools:

```mermaid
graph TD
    Utils["OpenMMTools Utility Functions"]
    GenUtils["General Utilities"]
    OMMUtils["OpenMM-Specific Utilities"]
    SerUtils["Serialization Utilities"]
    MetaUtils["Metaclass Utilities"]
    RestUtils["RestorableOpenMMObject"]
    EquilUtils["Equilibration Utilities"]
    
    Utils --> GenUtils
    Utils --> OMMUtils
    Utils --> SerUtils
    Utils --> MetaUtils
    Utils --> RestUtils
    Utils --> EquilUtils
    
    GenUtils --> TempDir["temporary_directory()"]
    GenUtils --> TimeBench["Timer, time_it(), with_timer()"]
    
    OMMUtils --> Platform["platform_supports_precision(),\nget_available_platforms(),\nget_fastest_platform()"]
    OMMUtils --> Quantity["TrackedQuantity,\nis_quantity_close(),\nquantity_from_string()"]
    OMMUtils --> MathExpr["math_eval(),\nsanitize_expression()"]
```

Sources: [openmmtools/utils/__init__.py:1-41](), [openmmtools/utils/utils.py:1-11]()

## General Utilities

### Temporary Directory Management

The `temporary_directory` context manager provides a safe way to create temporary directories that are automatically cleaned up when they're no longer needed.

```python
with temporary_directory() as tmp_dir:
    # Use temporary directory for operations
    # Directory will be automatically removed when exiting the with block
```

Sources: [openmmtools/utils/utils.py:48-59]()

### Timing and Benchmarking

OpenMMTools includes tools for timing code execution and benchmarking, which are useful for performance analysis:

- `Timer`: A class with stopwatch-style timing functions
- `time_it`: A context manager for timing code blocks
- `with_timer`: A decorator for timing function calls

Example usage patterns:

```mermaid
sequenceDiagram
    participant Code as "User Code"
    participant Timer as "Timer Utilities"
    
    Code->>Timer: with time_it("my_task")
    activate Timer
    Note right of Timer: Timing starts
    Code->>Code: execute task
    Code->>Timer: exit context
    deactivate Timer
    Note right of Timer: Timing ends and logs
    
    Code->>Timer: @with_timer("my_function")
    activate Timer
    Note right of Timer: Decorator wraps function
    Code->>Code: call decorated function()
    activate Code
    Code->>Timer: start timing
    Code->>Code: execute function body
    Code->>Timer: stop timing
    deactivate Code
    Timer->>Timer: report timing
    deactivate Timer
    
    Code->>Timer: timer = Timer()
    Code->>Timer: timer.start("benchmark")
    Note right of Timer: Manual timing starts
    Code->>Code: execute code
    Code->>Timer: elapsed = timer.stop("benchmark")
    Note right of Timer: Manual timing ends
    Code->>Timer: timer.report_timing()
    Note right of Timer: Logs all timing results
```

Sources: [openmmtools/utils/utils.py:64-184]()

## OpenMM-Specific Utilities

### Platform Utilities

OpenMMTools provides functions for working with OpenMM's hardware platforms:

- `platform_supports_precision`: Checks if a platform supports a specific precision
- `get_available_platforms`: Returns platforms that support a minimum precision
- `get_fastest_platform`: Returns the fastest available platform for a given precision

```mermaid
sequenceDiagram
    participant User as "User Code"
    participant Utils as "Platform Utilities"
    participant Platforms as "OpenMM Platforms"
    
    User->>Utils: platform_supports_precision("CUDA", "mixed")
    Utils->>Platforms: getPlatformByName("CUDA")
    Platforms-->>Utils: CUDA Platform object
    Utils->>Utils: Try Context creation with mixed precision
    Utils-->>User: True/False
    
    User->>Utils: get_available_platforms("mixed")
    Utils->>Platforms: getNumPlatforms()
    Platforms-->>Utils: Number of platforms
    loop For each platform
        Utils->>Platforms: getPlatform(i)
        Platforms-->>Utils: Platform object
        Utils->>Utils: platform_supports_precision(platform, "mixed")
    end
    Utils-->>User: List of compatible platforms
    
    User->>Utils: get_fastest_platform("mixed")
    Utils->>Utils: get_available_platforms("mixed")
    Utils->>Platforms: platform.getSpeed() for each platform
    Platforms-->>Utils: Speed values
    Utils-->>User: Fastest compatible platform
```

Sources: [openmmtools/utils/utils.py:518-601](), [openmmtools/tests/test_utils.py:36-69]()

### Quantity Utilities

These utilities help with managing OpenMM's unit system:

- `TrackedQuantity`: A subclass of `unit.Quantity` that tracks whether it has been modified
- `is_quantity_close`: Compares two quantities with specified tolerance
- `quantity_from_string`: Converts a string mathematical expression to a Quantity

```mermaid
classDiagram
    class UnitQuantity {
        +value
        +unit
        +__getitem__()
        +__setitem__()
    }
    
    class TrackedQuantity {
        +has_changed: bool
        +__getitem__()
        +__setitem__()
        +append()
        +extend()
    }
    
    class TrackedQuantityView {
        +_tracked_quantity
        +__getitem__()
        +__setitem__()
    }
    
    UnitQuantity <|-- TrackedQuantity
    UnitQuantity <|-- TrackedQuantityView
    TrackedQuantity <-- TrackedQuantityView: references
```

Sources: [openmmtools/utils/utils.py:336-475](), [openmmtools/tests/test_utils.py:137-242]()

### Mathematical Expression Parsing

OpenMMTools provides functions for safely evaluating mathematical expressions:

- `math_eval`: Evaluates mathematical expressions with variables and functions
- `sanitize_expression`: Sanitizes expressions containing reserved words

```python
# Examples of math_eval usage
math_eval("x + y", {"x": 1.5, "y": 2})  # Returns 3.5
math_eval("(x + lambda) / z * 4", {"x": 1, "lambda": 2, "z": 3})  # Returns 4.0
math_eval("ceil(0.8) + step(0.5)", {"x": 0})  # Returns 2.0
```

Sources: [openmmtools/utils/utils.py:187-333](), [openmmtools/tests/test_utils.py:74-129]()

## Serialization Utilities

OpenMMTools includes functions to serialize and deserialize Python objects:

- `serialize`: Converts an object to a serializable dictionary representation
- `deserialize`: Reconstructs an object from its serialized form

```mermaid
sequenceDiagram
    participant User as "User Code"
    participant SerUtil as "Serialization Utilities"
    participant Object as "User Object"
    
    User->>SerUtil: serialize(object)
    SerUtil->>Object: __getstate__()
    Object-->>SerUtil: state dictionary
    SerUtil->>SerUtil: Add module and class info
    SerUtil-->>User: Serialized dictionary
    
    User->>SerUtil: deserialize(serialized_dict)
    SerUtil->>SerUtil: Extract module and class info
    SerUtil->>SerUtil: Import module
    SerUtil->>SerUtil: Get class object
    SerUtil->>Object: Create new instance
    SerUtil->>Object: __setstate__(state_dict)
    SerUtil-->>User: Restored object
```

Sources: [openmmtools/utils/utils.py:608-684](), [openmmtools/tests/test_utils.py:249-292]()

## Metaclass Utilities

These utilities assist with Python metaclass operations and inheritance management:

- `SubhookedABCMeta`: Abstract base class with implementation of `__subclasshook__`
- `find_all_subclasses`: Finds all subclasses of a parent class
- `find_subclass`: Finds a specific subclass by name

```mermaid
classDiagram
    class ABCMeta {
        +__abstractmethods__
    }
    
    class SubhookedABCMeta {
        +__subclasshook__()
    }
    
    class Interface {
        +abstract_method()
    }
    
    class Implementation {
        +abstract_method()
    }
    
    ABCMeta <|-- SubhookedABCMeta
    SubhookedABCMeta <|-- Interface
    Implementation ..> Interface: implements
    
    note for Implementation "Does not need to inherit\nfrom Interface"
```

Sources: [openmmtools/utils/utils.py:691-798](), [openmmtools/tests/test_utils.py:300-371]()

## Restorable OpenMM Objects

The `RestorableOpenMMObject` class provides a mechanism to preserve class identity when OpenMM objects are serialized or copied:

```mermaid
classDiagram
    class OpenMMForce {
        +serialize()
    }
    
    class OpenMMIntegrator {
        +serialize()
    }
    
    class RestorableOpenMMObject {
        +__init__()
        +is_restorable()
        +restore_interface()
        +deserialize_xml()
        +__copy__()
        +__deepcopy__()
    }
    
    class CustomForce {
        +_hash_parameter_name
        +special_method()
    }
    
    class CustomIntegrator {
        +_hash_parameter_name
        +special_method()
    }
    
    OpenMMForce <|-- RestorableOpenMMObject
    OpenMMIntegrator <|-- RestorableOpenMMObject
    RestorableOpenMMObject <|-- CustomForce
    RestorableOpenMMObject <|-- CustomIntegrator
```

This utility solves a common issue in OpenMM where custom forces and integrators lose their Python class information when they are serialized or copied. The `RestorableOpenMMObject` adds a hash parameter to the OpenMM object to track its class, enabling restoration after serialization.

Sources: [openmmtools/utils/utils.py:805-1036](), [openmmtools/tests/test_utils.py:379-521]()

## Equilibration Utilities

OpenMMTools provides utilities for system equilibration, particularly the `run_gentle_equilibration` function, which implements a multi-stage equilibration protocol:

```mermaid
graph TD
    Start(["Start"])
    CreateSystem["Create System Copy"]
    AddRestraints["Add Restraints if Specified"]
    SetupIntegrator["Setup Integrator"]
    CreateContext["Create Context"]
    RunPhase["Run Minimization/MD Based on 'EOM'"]
    NextStage{"More\nStages?"}
    SaveStructure["Save Final Structure"]
    
    Start --> CreateSystem
    CreateSystem --> AddRestraints
    AddRestraints --> SetupIntegrator
    SetupIntegrator --> CreateContext
    CreateContext --> RunPhase
    RunPhase --> NextStage
    NextStage -->|"Yes"| CreateSystem
    NextStage -->|"No"| SaveStructure
```

The `run_gentle_equilibration` function takes a multi-stage approach to equilibration, where each stage can have different parameters:

| Parameter | Description |
|-----------|-------------|
| EOM | Equilibration operation mode: 'minimize', 'MD', or 'MD_interpolate' |
| n_steps | Number of steps to run in this stage |
| temperature | Temperature for the stage |
| ensemble | 'NPT', 'NVT', or None |
| restraint_selection | MDTraj selection syntax for atoms to restrain |
| force_constant | Restraint force constant |
| collision_rate | Langevin collision rate |
| timestep | Integration timestep |

Each stage builds upon the previous one, gradually relaxing the system toward production conditions.

Sources: [openmmtools/utils/equilibration.py:1-164](), [openmmtools/tests/test_utils.py:524-778]()

## Summary

The utility functions in OpenMMTools provide a broad set of tools that simplify many common tasks in molecular dynamics simulations. From managing temporary directories and measuring performance to working with OpenMM's platforms, quantities, and serialization mechanisms, these utilities form a foundation for the more specialized components of OpenMMTools. The equilibration utilities, in particular, provide ready-to-use protocols for preparing systems for production simulations.

---