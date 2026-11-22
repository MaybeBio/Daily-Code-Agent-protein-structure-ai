# Autobatching and Memory Management

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [tests/test_autobatching.py](tests/test_autobatching.py)
- [torch_sim/autobatching.py](torch_sim/autobatching.py)
- [torch_sim/typing.py](torch_sim/typing.py)

</details>



This document covers torch-sim's automatic batching system for efficient GPU memory management and utilization. The autobatching system dynamically determines optimal batch sizes based on GPU memory constraints and provides two complementary strategies for processing multiple simulation states efficiently.

For information about trajectory management and HDF5 storage during simulations, see [Trajectory Management and I/O](#6.2). For details about the core simulation methods that use autobatching, see [Molecular Dynamics](#5.1), [Structure Optimization](#5.2), and [Static Calculations](#5.3).

## System Overview

The autobatching system consists of two main strategies for managing GPU memory and batch processing:

```mermaid
graph TB
    subgraph "Memory Estimation"
        measure_model_memory_forward["measure_model_memory_forward()"]
        determine_max_batch_size["determine_max_batch_size()"]
        estimate_max_memory_scaler["estimate_max_memory_scaler()"]
        calculate_memory_scaler["calculate_memory_scaler()"]
    end
    
    subgraph "Batching Strategies"
        BinningAutoBatcher["BinningAutoBatcher"]
        InFlightAutoBatcher["InFlightAutoBatcher"]
        to_constant_volume_bins["to_constant_volume_bins()"]
    end
    
    subgraph "High-Level API Integration"
        ts_integrate["ts.integrate()"]
        ts_optimize["ts.optimize()"]
        ts_static["ts.static()"]
    end
    
    subgraph "Core Components"
        ModelInterface["ModelInterface"]
        SimState["SimState"]
        concatenate_states["concatenate_states()"]
    end
    
    measure_model_memory_forward --> determine_max_batch_size
    determine_max_batch_size --> estimate_max_memory_scaler
    calculate_memory_scaler --> BinningAutoBatcher
    calculate_memory_scaler --> InFlightAutoBatcher
    
    to_constant_volume_bins --> BinningAutoBatcher
    estimate_max_memory_scaler --> BinningAutoBatcher
    estimate_max_memory_scaler --> InFlightAutoBatcher
    
    BinningAutoBatcher --> ts_integrate
    BinningAutoBatcher --> ts_optimize
    BinningAutoBatcher --> ts_static
    
    InFlightAutoBatcher --> ts_integrate
    InFlightAutoBatcher --> ts_optimize
    InFlightAutoBatcher --> ts_static
    
    ModelInterface --> measure_model_memory_forward
    SimState --> calculate_memory_scaler
    SimState --> concatenate_states
```

**Sources:** [torch_sim/autobatching.py:1-32](), [tests/test_runners.py:198-230]()

## Memory Estimation and Scaling

The autobatching system uses memory scaling metrics to estimate GPU memory requirements and determine optimal batch sizes without exhausting available memory.

### Memory Scaling Metrics

Two primary metrics are supported for estimating memory requirements:

| Metric | Description | Use Case |
|--------|-------------|----------|
| `n_atoms` | Uses only atom count | Models with fixed neighbor counts |
| `n_atoms_x_density` | Atom count × number density | Models with radial cutoffs |

The `calculate_memory_scaler()` function computes these metrics for individual states:

```mermaid
graph LR
    SimState["SimState"] --> calculate_memory_scaler["calculate_memory_scaler()"]
    memory_scales_with["memory_scales_with"] --> calculate_memory_scaler
    
    calculate_memory_scaler --> n_atoms_metric["n_atoms"]
    calculate_memory_scaler --> density_metric["n_atoms × density"]
    
    n_atoms_metric --> BinPacking["Bin Packing Algorithm"]
    density_metric --> BinPacking
```

**Sources:** [torch_sim/autobatching.py:310-357](), [tests/test_autobatching.py:92-107]()

### GPU Memory Measurement

The `measure_model_memory_forward()` function measures actual GPU memory usage during model forward passes:

```mermaid
graph TB
    start["Start Memory Measurement"] --> clear_cache["torch.cuda.empty_cache()"]
    clear_cache --> reset_stats["torch.cuda.reset_peak_memory_stats()"]
    reset_stats --> forward_pass["model(state)"]
    forward_pass --> measure_peak["torch.cuda.max_memory_allocated()"]
    measure_peak --> convert["Convert to GB"]
```

**Sources:** [torch_sim/autobatching.py:202-247]()

### Batch Size Determination

The `determine_max_batch_size()` function uses a geometric sequence to find the maximum batch size that fits in GPU memory:

```mermaid
graph TB
    start_size["start_size = 1"] --> generate_sequence["Generate geometric sequence"]
    scale_factor["scale_factor = 1.6"] --> generate_sequence
    
    generate_sequence --> test_batch["Test batch size"]
    test_batch --> measure_memory["measure_model_memory_forward()"]
    
    measure_memory --> oom_check{"CUDA OOM?"}
    oom_check -->|No| next_size["Try larger batch"]
    oom_check -->|Yes| return_safe["Return safe size with margin"]
    
    next_size --> test_batch
```

**Sources:** [torch_sim/autobatching.py:250-307](), [tests/test_autobatching.py:355-403]()

## BinningAutoBatcher

The `BinningAutoBatcher` groups states into bins of similar computational cost using a bin packing algorithm. This strategy is optimal for scenarios where all states need the same number of processing steps.

### Core Workflow

```mermaid
graph TB
    load_states["load_states()"] --> calculate_metrics["Calculate memory scalers"]
    calculate_metrics --> estimate_memory["Estimate max_memory_scaler"]
    estimate_memory --> bin_packing["to_constant_volume_bins()"]
    
    bin_packing --> create_batches["Create batched_states"]
    create_batches --> iteration["Iterator Interface"]
    
    iteration --> next_batch["next_batch()"]
    next_batch --> concatenate["concatenate_states()"]
    concatenate --> process["Process batch"]
    
    process --> restore_order["restore_original_order()"]
```

**Sources:** [torch_sim/autobatching.py:417-702](), [tests/test_autobatching.py:127-166]()

### Bin Packing Algorithm

The `to_constant_volume_bins()` function implements a first-fit decreasing algorithm:

```mermaid
graph LR
    items["Input items with weights"] --> sort["Sort by weight (descending)"]
    sort --> iterate["For each item"]
    
    iterate --> find_candidates["Find candidate bins"]
    find_candidates --> fit_check{"Item fits in existing bin?"}
    
    fit_check -->|Yes| add_to_fullest["Add to fullest candidate bin"]
    fit_check -->|No| create_new_bin["Create new bin"]
    
    add_to_fullest --> next_item["Next item"]
    create_new_bin --> next_item
    next_item --> iterate
```

**Sources:** [torch_sim/autobatching.py:34-199](), [tests/test_autobatching.py:18-90]()

### Usage Pattern

```python
# Create batcher
batcher = BinningAutoBatcher(
    model=model,
    memory_scales_with="n_atoms",
    max_memory_scaler=1000.0
)

# Load and process states
batcher.load_states(states)
final_states = []
for batch in batcher:
    final_states.append(process_batch(batch))

# Restore original order
ordered_results = batcher.restore_original_order(final_states)
```

**Sources:** [torch_sim/autobatching.py:442-456](), [tests/test_runners.py:210-230]()

## InFlightAutoBatcher

The `InFlightAutoBatcher` dynamically swaps states based on convergence, removing completed states and adding new ones to maintain optimal GPU utilization. This strategy is ideal for iterative processes where states converge at different rates.

### Dynamic Batching Workflow

```mermaid
graph TB
    load_states["load_states()"] --> first_batch["_get_first_batch()"]
    first_batch --> estimate_memory["Estimate max_memory_scaler"]
    estimate_memory --> initial_states["_get_next_states()"]
    
    initial_states --> process_batch["Process batch"]
    process_batch --> check_convergence["Check convergence"]
    
    check_convergence --> next_batch_call["next_batch()"]
    next_batch_call --> remove_converged["Remove converged states"]
    remove_converged --> add_new["Add new states"]
    
    add_new --> more_states{"More states to process?"}
    more_states -->|Yes| process_batch
    more_states -->|No| restore_order["restore_original_order()"]
```

**Sources:** [torch_sim/autobatching.py:704-1129](), [tests/test_autobatching.py:307-354]()

### State Swapping Mechanism

```mermaid
graph LR
    updated_state["Updated batch"] --> convergence_check["convergence_tensor"]
    convergence_check --> identify_converged["torch.where(convergence_tensor)"]
    
    identify_converged --> pop_converged["state.pop(completed_idx)"]
    pop_converged --> update_tracking["_delete_old_states()"]
    
    update_tracking --> get_new["_get_next_states()"]
    get_new --> concatenate_new["concatenate_states()"]
    
    concatenate_new --> next_batch["Return next batch"]
```

**Sources:** [torch_sim/autobatching.py:961-1074](), [tests/test_autobatching.py:460-507]()

### Convergence and Max Iterations

The `InFlightAutoBatcher` supports a `max_iterations` parameter to prevent infinite processing:

```mermaid
graph TB
    process_state["Process state"] --> increment_counter["Increment swap_attempts[idx]"]
    increment_counter --> check_limit{"swap_attempts >= max_iterations?"}
    
    check_limit -->|Yes| force_convergence["Set convergence_tensor[idx] = True"]
    check_limit -->|No| natural_convergence["Use actual convergence"]
    
    force_convergence --> remove_state["Remove from batch"]
    natural_convergence --> continue_processing["Continue processing"]
```

**Sources:** [torch_sim/autobatching.py:1038-1046](), [tests/test_autobatching.py:550-600]()

## Integration with High-Level API

The autobatching system integrates seamlessly with torch-sim's high-level API functions through the `autobatcher` parameter.

### API Integration Points

```mermaid
graph TB
    subgraph "High-Level Functions"
        integrate["ts.integrate()"]
        optimize["ts.optimize()"]
        static["ts.static()"]
    end
    
    subgraph "Autobatcher Parameter Options"
        auto_true["autobatcher=True"]
        auto_binning["autobatcher=BinningAutoBatcher(...)"]
        auto_inflight["autobatcher=InFlightAutoBatcher(...)"]
    end
    
    subgraph "Default Behavior"
        default_binning["Default: BinningAutoBatcher"]
        default_inflight["optimize: InFlightAutoBatcher"]
    end
    
    integrate --> auto_true
    optimize --> auto_true
    static --> auto_true
    
    auto_true --> default_binning
    optimize --> default_inflight
    
    integrate --> auto_binning
    optimize --> auto_binning
    static --> auto_binning
    
    integrate --> auto_inflight
    optimize --> auto_inflight
```

**Sources:** [tests/test_runners.py:478-548]()

### Usage Examples

#### With ts.integrate()

```python
final_state = ts.integrate(
    system=multiple_states,
    model=model,
    integrator=nvt_langevin,
    n_steps=100,
    autobatcher=BinningAutoBatcher(
        model=model,
        memory_scales_with="n_atoms",
        max_memory_scaler=1000
    )
)
```

#### With ts.optimize()

```python
final_states = ts.optimize(
    system=states_to_relax,
    model=model,
    optimizer=unit_cell_fire,
    convergence_fn=force_convergence_fn,
    autobatcher=InFlightAutoBatcher(
        model=model,
        max_memory_scaler=800
    )
)
```

#### With ts.static()

```python
properties = ts.static(
    system=batched_states,
    model=model,
    autobatcher=True  # Uses default BinningAutoBatcher
)
```

**Sources:** [tests/test_runners.py:231-287](), [tests/test_runners.py:415-476](), [tests/test_runners.py:621-652]()

### Trajectory Reporting with Autobatching

The autobatching system maintains proper ordering when used with trajectory reporting:

```mermaid
graph LR
    autobatcher["Autobatcher processes states"] --> batched_results["Batched results"]
    batched_results --> restore_order["restore_original_order()"]
    restore_order --> trajectory_reporter["TrajectoryReporter"]
    trajectory_reporter --> individual_files["Individual trajectory files"]
```

**Sources:** [tests/test_runners.py:654-760]()

---