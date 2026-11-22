# High-Level API Functions

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [tests/test_runners.py](tests/test_runners.py)
- [tests/test_trajectory.py](tests/test_trajectory.py)
- [torch_sim/runners.py](torch_sim/runners.py)
- [torch_sim/trajectory.py](torch_sim/trajectory.py)

</details>



This page covers the three main entry points for running atomistic simulations in torch-sim: `integrate`, `optimize`, and `static`. These functions provide a simplified interface that abstracts away the complexity of state management, batching, and trajectory handling while still allowing customization through their parameters.

For details about the underlying simulation methods and algorithms, see [Simulation Methods](#5). For information about autobatching and memory management, see [Autobatching and Memory Management](#6.1).

## Overview

The high-level API consists of three primary functions in the `torch_sim.runners` module that handle different types of atomistic calculations:

| Function | Purpose | Returns | Primary Use Cases |
|----------|---------|---------|-------------------|
| `integrate` | Molecular dynamics simulations | Final `SimState` | MD trajectories, thermodynamic sampling |
| `optimize` | Geometry optimization | Optimized `SimState` | Structure relaxation, energy minimization |
| `static` | Single-point calculations | List of property dictionaries | Property evaluation, benchmarking |

## Function Architecture

The following diagram shows how the high-level API functions relate to the core torch-sim components:

```mermaid
graph TB
    subgraph "High-Level API"
        integrate["integrate()"]
        optimize["optimize()"] 
        static["static()"]
    end
    
    subgraph "Input Processing"
        initialize_state["initialize_state()"]
        configure_reporter["_configure_reporter()"]
        configure_batches["_configure_batches_iterator()"]
        configure_inflight["_configure_in_flight_autobatcher()"]
    end
    
    subgraph "Core Components"
        SimState["SimState"]
        ModelInterface["ModelInterface"]
        Integrators["Integrators<br/>(nvt_langevin, nve, etc.)"]
        Optimizers["Optimizers<br/>(fire, gradient_descent, etc.)"]
        TrajectoryReporter["TrajectoryReporter"]
    end
    
    subgraph "Execution Engines"
        BinningAutoBatcher["BinningAutoBatcher"]
        InFlightAutoBatcher["InFlightAutoBatcher"]
    end
    
    integrate --> initialize_state
    integrate --> configure_reporter
    integrate --> configure_batches
    integrate --> Integrators
    integrate --> BinningAutoBatcher
    integrate --> TrajectoryReporter
    
    optimize --> initialize_state
    optimize --> configure_reporter
    optimize --> configure_inflight
    optimize --> Optimizers
    optimize --> InFlightAutoBatcher
    optimize --> TrajectoryReporter
    
    static --> initialize_state
    static --> configure_reporter
    static --> configure_batches
    static --> BinningAutoBatcher
    static --> TrajectoryReporter
    
    initialize_state --> SimState
    Integrators --> ModelInterface
    Optimizers --> ModelInterface
    
    style integrate fill:#e1f5fe
    style optimize fill:#f3e5f5
    style static fill:#fff3e0
```

Sources: [torch_sim/runners.py:1-597]()

## integrate Function

The `integrate` function runs molecular dynamics simulations by repeatedly applying an integrator to evolve the system over time.

### Function Signature and Parameters

```mermaid
graph LR
    subgraph "integrate() Parameters"
        system["system<br/>(StateLike)"]
        model["model<br/>(ModelInterface)"]
        integrator["integrator<br/>(Callable)"]
        n_steps["n_steps<br/>(int)"]
        temperature["temperature<br/>(float|list|Tensor)"]
        timestep["timestep<br/>(float)"]
        trajectory_reporter["trajectory_reporter<br/>(TrajectoryReporter|dict|None)"]
        autobatcher["autobatcher<br/>(BinningAutoBatcher|bool)"]
        pbar["pbar<br/>(bool|dict)"]
    end
    
    subgraph "Processing Pipeline"
        init["initialize_state()"]
        setup_integrator["integrator(model, kT, dt, ...)"]
        batching["_configure_batches_iterator()"]
        reporting["_configure_reporter()"]
        evolution["MD Evolution Loop"]
        final_state["SimState"]
    end
    
    system --> init
    model --> setup_integrator
    integrator --> setup_integrator
    n_steps --> evolution
    temperature --> setup_integrator
    timestep --> setup_integrator
    trajectory_reporter --> reporting
    autobatcher --> batching
    
    init --> evolution
    setup_integrator --> evolution
    batching --> evolution
    reporting --> evolution
    evolution --> final_state
```

### Integration Workflow

The integration process follows this sequence:

```mermaid
sequenceDiagram
    participant User
    participant integrate
    participant BinningAutoBatcher
    participant Integrator
    participant TrajectoryReporter
    participant ModelInterface

    User->>integrate: Call with system, model, integrator
    integrate->>integrate: initialize_state()
    integrate->>integrate: setup integrator init/update functions
    integrate->>BinningAutoBatcher: configure batch iterator
    integrate->>TrajectoryReporter: configure reporter
    
    loop For each batch
        BinningAutoBatcher->>integrate: Return batch and indices
        integrate->>Integrator: init_fn(state)
        
        loop For n_steps
            integrate->>Integrator: update_fn(state, kT)
            Integrator->>ModelInterface: Forward pass
            ModelInterface-->>Integrator: forces, energy
            integrate->>TrajectoryReporter: report(state, step)
        end
        
        integrate->>integrate: Collect final state
    end
    
    integrate->>BinningAutoBatcher: restore_original_order()
    integrate-->>User: Final concatenated SimState
```

Sources: [torch_sim/runners.py:111-210](), [examples/tutorials/high_level_tutorial.py:74-83]()

## optimize Function

The `optimize` function performs geometry optimization using algorithms like FIRE or gradient descent until convergence criteria are met.

### Dynamic Batch Management

Unlike `integrate`, `optimize` uses `InFlightAutoBatcher` to dynamically remove converged structures and add new ones:

```mermaid
graph TB
    subgraph "Optimization Workflow"
        start["Initialize States"]
        load["InFlightAutoBatcher.load_states()"]
        next_batch["next_batch(state, convergence_tensor)"]
        check_result{{"result[0] is not None?"}}
        optimize_batch["Run optimization steps"]
        check_convergence["convergence_fn(state, last_energy)"]
        update_batch["Update batch with convergence"]
        collect_converged["Collect converged states"]
        restore_order["restore_original_order()"]
        final_result["Final SimState"]
    end
    
    start --> load
    load --> next_batch
    next_batch --> check_result
    check_result -->|Yes| optimize_batch
    optimize_batch --> check_convergence
    check_convergence --> update_batch
    update_batch --> collect_converged
    collect_converged --> next_batch
    check_result -->|No| restore_order
    restore_order --> final_result
    
    style check_result fill:#ffe0e0
    style optimize_batch fill:#e0f0ff
    style check_convergence fill:#f0ffe0
```

### Convergence Functions

The `optimize` function supports custom convergence criteria through convergence functions:

| Function | Purpose | Signature |
|----------|---------|-----------|
| `generate_force_convergence_fn` | Force-based convergence | `(force_tol: float) -> Callable` |
| `generate_energy_convergence_fn` | Energy-based convergence | `(energy_tol: float) -> Callable` |
| Custom function | User-defined criteria | `(state: SimState, last_energy: Tensor) -> Tensor` |

Sources: [torch_sim/runners.py:358-480](), [torch_sim/runners.py:291-356](), [examples/tutorials/high_level_tutorial.py:383-413]()

## static Function

The `static` function performs single-point calculations on a collection of systems without any evolution, returning computed properties rather than states.

### Static Calculation Pipeline

```mermaid
graph LR
    subgraph "static() Workflow"
        input["Input Systems"]
        init["initialize_state()"]
        batching["_configure_batches_iterator()"]
        reporting["_configure_reporter()"]
        
        subgraph "Batch Processing"
            model_call["model(sub_state)"]
            create_static["Create StaticState"]
            report_props["reporter.report()"]
        end
        
        reorder["restore_original_order()"]
        output["List[Dict[str, Tensor]]"]
    end
    
    input --> init
    init --> batching
    batching --> reporting
    reporting --> model_call
    model_call --> create_static
    create_static --> report_props
    report_props --> reorder
    reorder --> output
```

### StaticState Construction

The `static` function dynamically creates a `StaticState` class that includes computed properties:

```mermaid
classDiagram
    class SimState {
        +positions: Tensor
        +masses: Tensor
        +cell: Tensor
        +atomic_numbers: Tensor
        +system_idx: Tensor
    }
    
    class StaticState {
        +energy: Tensor
        +forces: Tensor
        +stress: Tensor
        +_atom_attributes
        +_system_attributes
    }
    
    SimState <|-- StaticState
    
    note for StaticState "Created dynamically at runtime\nwith model outputs"
```

Sources: [torch_sim/runners.py:483-596](), [torch_sim/runners.py:538-549](), [examples/tutorials/high_level_tutorial.py:432-456]()

## Autobatching Integration

All three high-level functions integrate with the autobatching system to manage GPU memory efficiently:

### Autobatcher Selection

```mermaid
flowchart TD
    function_call[/"High-Level Function Call"/]
    check_function{"Function Type?"}
    
    function_call --> check_function
    
    check_function -->|integrate/static| binning["BinningAutoBatcher"]
    check_function -->|optimize| inflight["InFlightAutoBatcher"]
    
    binning --> binning_config["_configure_batches_iterator()"]
    inflight --> inflight_config["_configure_in_flight_autobatcher()"]
    
    binning_config --> fixed_batches["Fixed batch processing"]
    inflight_config --> dynamic_batches["Dynamic batch processing"]
    
    fixed_batches --> restore_binning["restore_original_order()"]
    dynamic_batches --> restore_inflight["restore_original_order()"]
    
    restore_binning --> final_result["Final Result"]
    restore_inflight --> final_result
```

### Memory Management Configuration

| Parameter | Purpose | Functions |
|-----------|---------|-----------|
| `autobatcher=True` | Enable automatic memory management | All three |
| `autobatcher=False` | Disable batching (single batch) | All three |
| `autobatcher=BinningAutoBatcher(...)` | Custom binning configuration | `integrate`, `static` |
| `autobatcher=InFlightAutoBatcher(...)` | Custom in-flight configuration | `optimize` |

Sources: [torch_sim/runners.py:73-108](), [torch_sim/runners.py:213-254]()

## Trajectory Reporting Integration

All high-level functions support trajectory reporting through the `TrajectoryReporter` system:

### Reporter Configuration

```mermaid
graph LR
    subgraph "Reporter Input Options"
        none["None"]
        dict_input["Dict"]
        reporter_obj["TrajectoryReporter"]
    end
    
    subgraph "_configure_reporter()"
        setup_props["Setup default properties"]
        create_calculators["Create prop_calculators"]
        setup_frequencies["Setup frequencies"]
        create_reporter["Create TrajectoryReporter"]
    end
    
    subgraph "Default Properties by Function"
        integrate_props["kinetic_energy<br/>potential_energy<br/>temperature"]
        optimize_props["potential_energy"]
        static_props["potential_energy<br/>forces<br/>stress"]
    end
    
    none --> create_reporter
    dict_input --> setup_props
    reporter_obj --> create_reporter
    
    setup_props --> create_calculators
    create_calculators --> setup_frequencies
    setup_frequencies --> create_reporter
    
    create_reporter --> integrate_props
    create_reporter --> optimize_props
    create_reporter --> static_props
```

### Multi-System Trajectory Handling

When processing multiple systems, the trajectory reporter handles file management automatically:

```mermaid
sequenceDiagram
    participant Function as High-Level Function
    participant Reporter as TrajectoryReporter
    participant Batcher as AutoBatcher
    participant Files as HDF5 Files

    Function->>Reporter: Initialize with filenames list
    Function->>Batcher: Process batches
    
    loop For each batch
        Batcher->>Function: Return batch + system_indices
        Function->>Reporter: load_new_trajectories(indices)
        Reporter->>Files: Open relevant files
        Function->>Reporter: report(state, step)
        Reporter->>Files: Write data
    end
    
    Function->>Reporter: finish()
    Reporter->>Files: Close all files
```

Sources: [torch_sim/runners.py:32-70](), [torch_sim/trajectory.py](), [examples/tutorials/high_level_tutorial.py:269-288]()

## Usage Patterns

### Basic Usage

```python
# Molecular dynamics
final_state = ts.integrate(
    system=atoms,
    model=model,
    integrator=ts.nvt_langevin,
    n_steps=1000,
    temperature=300,
    timestep=0.001
)

# Geometry optimization  
final_state = ts.optimize(
    system=atoms,
    model=model,
    optimizer=ts.fire
)

# Static calculation
results = ts.static(
    system=atoms_list,
    model=model
)
```

### Advanced Configuration

```python
# With autobatching and trajectory reporting
final_state = ts.integrate(
    system=many_systems,
    model=model,
    integrator=ts.nvt_langevin,
    n_steps=1000,
    temperature=300,
    timestep=0.001,
    autobatcher=True,
    trajectory_reporter={
        "filenames": ["traj_{i}.h5" for i in range(len(many_systems))],
        "state_frequency": 10
    }
)
```

Sources: [examples/tutorials/high_level_tutorial.py:74-516](), [examples/scripts/4_High_level_api/4.2_auto_batching_api.py:1-122]()

---