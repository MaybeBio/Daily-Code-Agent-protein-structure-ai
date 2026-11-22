

This documentation examines Colvars' parallel computing architecture, focusing on shared-memory parallelization (SMP) and GPU acceleration through CUDA/HIP. The design prioritizes thread-safe collective variable calculations while maintaining compatibility with multiple simulation engines and parallel execution models.

## SMP Architecture Overview

Colvars implements a three-tier parallel computing strategy through the `colvarproxy_smp` abstraction layer. The architecture distinguishes between three distinct parallelization modes based on computational granularity and thread safety requirements.

The core SMP modes are:

| Mode | Description | Use Case |
|------|-------------|----------|
| `cvcs` | Parallel execution of collective variable components | Complex variables with multiple CVCs |
| `inner_loop` | Parallel inner loops within calculations | Compute-intensive distance calculations |
| `none` | Sequential execution | Default or thread-hostile operations |

The SMP infrastructure is built on the proxy pattern, with `colvarproxy_smp` serving as the base class that concrete engine implementations (NAMD, LAMMPS, GROMACS) inherit and potentially override [colvarproxy.h](/src/colvarproxy.h#L459-L509).

Sources: [colvarproxy.h](/src/colvarproxy.h#L459-L509), [colvarproxy.cpp](/src/colvarproxy.cpp#L244-L402)

## Thread Management and Synchronization

### Thread Identification and Configuration

The proxy provides methods to query thread identity and concurrency levels:

- `smp_thread_id()`: Returns the current thread's index (0-based)
- `smp_num_threads()`: Returns total number of available threads
- `get_smp_mode()`: Retrieves current parallelization mode
- `set_smp_mode()`: Dynamically switches between SMP modes

Thread identification is critical for debugging and for per-thread data allocation. The implementation defaults to OpenMP primitives but can be overridden by engines with custom threading models [colvarproxy.h](/src/colvarproxy.h#L486-L490).

Sources: [colvarproxy.h](/src/colvarproxy.h#L486-L490), [colvarproxy.cpp](/src/colvarproxy.cpp#L362-L381)

### Locking Mechanisms

For thread-safe access to shared data structures, Colvars implements three locking primitives:

```cpp
int smp_lock();           // Acquire lock (blocking)
int smp_trylock();        // Non-blocking lock attempt
int smp_unlock();         // Release lock
```

These functions use OpenMP's `omp_lock_t` internally but can be overridden to use engine-specific synchronization primitives. The lock protects shared atomic data structures during concurrent access from multiple threads [colvarproxy.cpp](/src/colvarproxy.cpp#L382-L402).

Sources: [colvarproxy.cpp](/src/colvarproxy.cpp#L382-L402)

## Parallel Collective Variable Calculation

### CVC-Level Parallelization

The primary parallel computation occurs in `colvarmodule::calc_colvars()`, which detects SMP mode and dispatches work accordingly. When `smp_mode_t::cvcs` is active, the algorithm follows this pattern:

1. **Work Partitioning**: Determine which collective variables are active and calculate their component counts
2. **Task Creation**: Duplicate colvar references into `colvars_smp` vector with corresponding component indices in `colvars_smp_items`
3. **Parallel Execution**: Execute `smp_loop()` to distribute component calculations across threads
4. **Data Collection**: Aggregate results from parallel threads back into main colvar structures

The work partitioning strategy is key to load balancing: complex variables with multiple active CVCs generate multiple parallel tasks, while simpler variables generate fewer tasks [colvarmodule.cpp](/src/colvarmodule.cpp#L986-L1022).

Sources: [colvarmodule.cpp](/src/colvarmodule.cpp#L986-L1022)

### Parallel Component Calculation

The per-thread worker function `calc_component_smp()` executes a single CVC calculation:

```cpp
int colvarmodule::calc_component_smp(int i) {
  colvar *x = (*(variables_active_smp()))[i];
  int x_item = (*(variables_active_smp_items()))[i];
  return x->calc_cvcs(x_item, 1);
}
```

Each thread receives an index into the parallel task queue and calls the colvar's component calculation with the specific CVC index. Debug logging includes thread identification to aid troubleshooting [colvarmodule.cpp](/src/colvarmodule.cpp#L225-L236).

Sources: [colvarmodule.cpp](/src/colvarmodule.cpp#L225-L236)

> [!TIP]
> The SMP architecture creates duplicate colvar references for parallel execution rather than duplicating the actual colvar objects. This design minimizes memory overhead while enabling true parallel CVC evaluation. However, it requires careful synchronization when accessing shared data structures like atomic positions.

## Parallel Bias Calculation

### Multi-Threaded Bias Execution

Colvars provides two strategies for parallel bias calculation through `smp_biases_loop()` and `smp_biases_script_loop()`. These methods distribute bias energy and force calculations across available threads.

The key distinction between the two methods is scripted bias handling: `smp_biases_loop()` distributes all biases across threads, while `smp_biases_script_loop()` reserves thread 0 for scripted biases to ensure thread safety for user-provided code that may not be reentrant [colvarproxy.h](/src/colvarproxy.h#L480-L484).

Sources: [colvarproxy.h](/src/colvarproxy.h#L480-L484), [colvarproxy.cpp](/src/colvarproxy.cpp#L310-L361)

## GPU Acceleration (CUDA/HIP)

### CUDA-Aware Memory Allocation

When compiled with `COLVARS_CUDA` or `COLVARS_HIP` defined, Colvars uses a custom allocator `CudaHostAllocator` for all atomic data structures:

```cpp
template <typename T>
class CudaHostAllocator {
  T* allocate(size_t n) {
    T* ptr;
    if (cudaHostAlloc(&ptr, n * sizeof(T), cudaHostAllocMapped) != cudaSuccess) {
      throw std::bad_alloc();
    }
    return ptr;
  }
};
```

This allocator uses `cudaHostAlloc()` with `cudaHostAllocMapped` flag, creating page-locked memory that is accessible from both CPU and GPU. The mapped allocation eliminates explicit data transfer overhead by providing direct GPU access to the same physical memory [colvarmodule.h](/src/colvarmodule.h#L89-L123).

Sources: [colvarmodule.h](/src/colvarmodule.h#L89-L123)

### GPU-Compatible Data Structures

Atomic data arrays (positions, forces, masses, charges) in `colvarproxy_atoms` use the CUDA-aware allocator through conditional compilation:

```cpp
#if ( defined(COLVARS_CUDA) || defined(COLVARS_HIP) )
  using allocator_type = cvm::CudaHostAllocator<T>;
#else
  using allocator_type = std::allocator<T>;
#endif
```

This design ensures that when GPU support is enabled, all atomic data resides in memory regions accessible to GPU kernels, enabling efficient heterogeneous computation without manual memory management [colvarproxy.h](/src/colvarproxy.h#L47-L55).

Sources: [colvarproxy.h](/src/colvarproxy.h#L47-L55)

> [!TIP]
> The CUDA/HIP integration requires engine-specific implementations to launch actual GPU kernels. The memory allocator provides the foundation, but actual GPU acceleration depends on the host MD engine's implementation of GPU-aware colvar component calculations.

## Memory Architecture for Parallel Execution

### Thread-Local vs Shared Data

Colvars distinguishes between thread-local and shared memory regions:

| Data Type | Scope | Access Pattern |
|-----------|-------|----------------|
| `colvars_smp` | Module-level | Read-only during parallel execution |
| `colvars_smp_items` | Module-level | Read-only during parallel execution |
| `atoms_positions` | Proxy-level | Shared (requires locking) |
| `atoms_new_colvar_forces` | Proxy-level | Shared (reduction required) |

The parallel task vectors (`colvars_smp`, `colvars_smp_items`) are populated before parallel execution and remain read-only during the parallel phase, eliminating race conditions. Atomic data requires synchronization due to both reads (for position access) and writes (for force application) [colvarmodule.h](/src/colvarmodule.h#L344-L348).

Sources: [colvarmodule.h](/src/colvarmodule.h#L344-L348)

### Reference Counting for Shared Atoms

Atomic data uses reference counting to track usage across multiple colvars and threads:

```cpp
std::vector<size_t> atoms_refcount;
```

Each atom has a reference count incremented when used by a colvar and decremented when released. This system prevents premature deallocation when atoms are shared between multiple collective variables, a common scenario in complex simulation configurations [colvarproxy.h](/src/colvarproxy.h#L268).

Sources: [colvarproxy.h](/src/colvarproxy.h#L268)

## Implementation Pattern by Engine

Different MD engines implement SMP support through inheritance and method overriding:

| Engine | SMP Implementation | Notes |
|--------|-------------------|-------|
| NAMD | Custom thread pool | Overrides `smp_loop()` with Charm++-based parallelism |
| LAMMPS | OpenMP-based | Uses default OpenMP implementation |
| GROMACS | OpenMP-based | Uses default OpenMP implementation |
| VMD | Sequential | Typically runs without parallel acceleration |

The proxy architecture enables each engine to provide optimal threading strategies while maintaining a consistent interface. Engines can override the default OpenMP-based `smp_loop()` implementation with native threading models [colvarproxy.cpp](/src/colvarproxy.cpp#L291-L309).

Sources: [colvarproxy.cpp](/src/colvarproxy.cpp#L291-L309)

## Debugging and Profiling Support

### Thread-Aware Logging

Debug logging includes thread identification when SMP is active:

```cpp
cvm::log("Thread "+cvm::to_str(proxy->smp_thread_id())+"/"+
         cvm::to_str(proxy->smp_num_threads())+
         ": calc_component_smp(), i = "+cvm::to_str(i)+", cv = "+
         x->name+", cvc = "+cvm::to_str(x_item)+"\n");
```

This output helps identify load imbalances and verify correct thread assignment. Debug mode must be explicitly enabled to generate these messages [colvarmodule.cpp](/src/colvarmodule.cpp#L229-L234).

Sources: [colvarmodule.cpp](/src/colvarmodule.cpp#L229-L234)

### Force Statistics

The proxy tracks RMS and maximum applied forces per atom and atom group:

- `rms_atoms_applied_force()`: Root-mean-square of applied atomic forces
- `max_atoms_applied_force()`: Maximum force magnitude applied
- `max_atoms_applied_force_id()`: Atom ID with maximum force

These statistics help identify potential instability issues that may be exacerbated by parallel execution [colvarproxy.h](/src/colvarproxy.h#L214-L237).

Sources: [colvarproxy.h](/src/colvarproxy.h#L214-L237)

## Configuration and Usage

### Enabling SMP Support

SMP support is typically configured through engine-specific parameters rather than Colvars configuration files. The key requirements are:

1. **Compile-time**: Build Colvars with OpenMP support (`-fopenmp` on GCC/Clang)
2. **Runtime**: Configure the MD engine to use multiple threads
3. **Colvars**: Ensure variables have multiple active CVCs to benefit from CVC-level parallelization

The SMP mode is detected and configured automatically based on the number of available threads and the complexity of defined collective variables.

### Performance Considerations

Effective parallelization requires:

- **Load Balance**: Variables with uneven CVC complexity may create thread imbalance
- **Atomicity**: Force application must be atomic or properly synchronized
- **Memory Bandwidth**: Parallel access to atomic positions may saturate memory bandwidth

Performance scales with the number of active CVCs rather than the number of collective variables. Simple variables with single CVCs cannot benefit from CVC-level parallelization [colvarmodule.cpp](/src/colvarmodule.cpp#L1003-L1009).

Sources: [colvarmodule.cpp](/src/colvarmodule.cpp#L1003-L1009)

## Next Steps

For deeper understanding of related topics, explore:

- **Proxy Interface and Engine Integration**: [Proxy Interface and Engine Integration](20-proxy-interface-and-engine-integration) - Details the proxy pattern that enables SMP abstraction
- **Atom and Atom Group Management**: [Atom and Atom Group Management](21-atom-and-atom-group-management) - Covers atomic data structures used in parallel execution
- **Core Architecture and Design Patterns**: [Core Architecture and Design Patterns](5-core-architecture-and-design-patterns) - Provides broader architectural context
- **Multiple Replica Communication**: [Multiple Replica Communication](25-multiple-replica-communication) - Covers distributed parallelism beyond shared memory