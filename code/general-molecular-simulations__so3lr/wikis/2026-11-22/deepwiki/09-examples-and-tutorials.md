# Examples and Tutorials

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [examples/npt_jaxmd.ipynb](examples/npt_jaxmd.ipynb)
- [examples/nvt_jaxmd.ipynb](examples/nvt_jaxmd.ipynb)

</details>



This page provides practical examples demonstrating how to use SO3LR for molecular dynamics simulations. The examples cover basic NVT and NPT simulations using JAX-MD integration, structure relaxation workflows, and efficient data handling for production runs. These tutorials bridge the gap between the high-level SO3LR concepts and their implementation in working simulation code.

For information about the Python API interfaces, see [Python API](#3). For details about the CLI tools, see [Command Line Interface](#2). For technical documentation of the core components, see [Core Components](#5).

## Example Workflow Overview

The SO3LR examples demonstrate three main simulation workflows: structure relaxation, canonical (NVT) dynamics, and isothermal-isobaric (NPT) dynamics. Each workflow follows a common pattern of system setup, potential initialization, neighbor list allocation, and iterative simulation steps.

### Basic Simulation Workflow

```mermaid
flowchart TD
    subgraph "Input Preparation"
        XYZ["XYZ/EXTXYZ Files<br/>Molecular Structures"]
        ASERead["ase.io.read()<br/>Structure Loading"]
        Arrays["JAX Arrays<br/>positions, species, masses"]
    end
    
    subgraph "SO3LR Setup"
        Potential["So3lrPotential<br/>Model Initialization"]
        JAXMDConv["to_jax_md()<br/>JAX-MD Integration"]
        EnergyFn["energy_fn<br/>JIT Compiled"]
        ForceFn["force_fn<br/>jax_md.quantity.force()"]
    end
    
    subgraph "Neighbor Management"
        NbrAlloc["neighbor_fn.allocate()<br/>Short-range Neighbors"]
        NbrLRAlloc["neighbor_fn_lr.allocate()<br/>Long-range Neighbors"]
        NbrUpdate["nbrs.update()<br/>Dynamic Updates"]
    end
    
    subgraph "Simulation Execution"
        StructRelax["fire_descent()<br/>Structure Relaxation"]
        MDInit["init_fn()<br/>NVT/NPT Initialization"]
        MDStep["apply_fn()<br/>Time Integration"]
        Trajectory["positions_md<br/>Trajectory Storage"]
    end
    
    XYZ --> ASERead
    ASERead --> Arrays
    Arrays --> Potential
    Potential --> JAXMDConv
    JAXMDConv --> EnergyFn
    JAXMDConv --> ForceFn
    JAXMDConv --> NbrAlloc
    JAXMDConv --> NbrLRAlloc
    
    EnergyFn --> StructRelax
    ForceFn --> StructRelax
    StructRelax --> MDInit
    MDInit --> MDStep
    NbrUpdate --> MDStep
    MDStep --> Trajectory
    
    style Potential fill:#fff3e0
    style JAXMDConv fill:#fff3e0
    style StructRelax fill:#e8f5e8
    style MDStep fill:#e8f5e8
```

Sources: [examples/nvt_jaxmd.ipynb:1-606](), [examples/npt_jaxmd.ipynb:1-737]()

### Code Entity Mapping

```mermaid
graph TB
    subgraph "High-Level Concepts"
        NVT["NVT Simulation<br/>(Canonical Ensemble)"]
        NPT["NPT Simulation<br/>(Isothermal-Isobaric)"]
        Relax["Structure Relaxation<br/>(Energy Minimization)"]
        PBC["Periodic Boundaries<br/>(Box Constraints)"]
    end
    
    subgraph "JAX-MD Functions"
        NVTFunc["jax_md.simulate.nvt_nose_hoover()"]
        NPTFunc["jax_md.simulate.npt_nose_hoover()"]
        FIREFunc["jax_md.minimize.fire_descent()"]
        SpaceFunc["jax_md.space.periodic_general()"]
    end
    
    subgraph "SO3LR Integration"
        So3lrPot["So3lrPotential<br/>dtype=jnp.float64"]
        ToJAXMD["to_jax_md()<br/>displacement_or_metric"]
        NbrFn["neighbor_fn<br/>Short-range"]
        NbrLRFn["neighbor_fn_lr<br/>Long-range"]
    end
    
    subgraph "Execution Pattern"
        InitFn["init_fn<br/>State Initialization"]
        ApplyFn["apply_fn<br/>JIT Compiled Step"]
        ForiLoop["jax.lax.fori_loop<br/>Batch Processing"]
        BlockReady["jax.block_until_ready<br/>Synchronization"]
    end
    
    NVT --> NVTFunc
    NPT --> NPTFunc
    Relax --> FIREFunc
    PBC --> SpaceFunc
    
    NVTFunc --> So3lrPot
    NPTFunc --> So3lrPot
    FIREFunc --> So3lrPot
    SpaceFunc --> ToJAXMD
    
    So3lrPot --> ToJAXMD
    ToJAXMD --> NbrFn
    ToJAXMD --> NbrLRFn
    
    NVTFunc --> InitFn
    NPTFunc --> InitFn
    InitFn --> ApplyFn
    ApplyFn --> ForiLoop
    ForiLoop --> BlockReady
    
    style So3lrPot fill:#ffeb3b
    style ToJAXMD fill:#ffeb3b
    style ApplyFn fill:#c8e6c9
    style ForiLoop fill:#c8e6c9
```

Sources: [examples/nvt_jaxmd.ipynb:21-33](), [examples/nvt_jaxmd.ipynb:138-151](), [examples/npt_jaxmd.ipynb:186-199]()

## Basic Molecular Dynamics Examples

### NVT Simulation in Vacuum

The NVT (canonical ensemble) example demonstrates molecular dynamics simulation of a small molecule in vacuum without periodic boundary conditions. This workflow is suitable for isolated molecular systems.

**Key Components:**
- **Structure Loading**: Uses `ase.io.read()` to load molecular geometry from XYZ files
- **Vacuum Simulation**: Employs `jax_md.space.free()` for unbounded space
- **Temperature Control**: Implements Nosé-Hoover chain thermostat via `jax_md.simulate.nvt_nose_hoover()`

**Critical Code Pattern:**
```python
displacement, shift = jax_md.space.free()
neighbor_fn, neighbor_fn_lr, energy_fn = to_jax_md(
    potential=So3lrPotential(dtype=jnp.float64),
    displacement_or_metric=displacement,
    disable_cell_list=True
)
```

The example includes structure relaxation using the FIRE algorithm before starting dynamics, demonstrating the typical workflow of optimizing initial configurations.

Sources: [examples/nvt_jaxmd.ipynb:88-101](), [examples/nvt_jaxmd.ipynb:134-151](), [examples/nvt_jaxmd.ipynb:227-233]()

### NPT Simulation with Periodic Boundaries

The NPT (isothermal-isobaric ensemble) example shows simulation of a water box with periodic boundary conditions and pressure control. This represents the most common production simulation scenario.

**Key Components:**
- **Periodic Boundaries**: Uses `jax_md.space.periodic_general()` with fractional coordinates
- **Pressure Control**: Implements Nosé-Hoover chain barostat alongside thermostat
- **Box Updates**: Handles dynamic simulation box changes via `jax_md.simulate.npt_box()`

**Critical Code Pattern:**
```python
box = jnp.array([lattice_parameter])
displacement, shift = jax_md.space.periodic_general(
    box=box, 
    fractional_coordinates=True
)
```

The example demonstrates proper handling of both short-range and long-range neighbor list updates as the simulation box fluctuates during NPT dynamics.

Sources: [examples/npt_jaxmd.ipynb:84-91](), [examples/npt_jaxmd.ipynb:127-141](), [examples/npt_jaxmd.ipynb:509-520]()

## Neighbor List Management

Both examples showcase the dual neighbor list architecture required by SO3LR's hybrid potential design:

**Neighbor List Allocation:**
```python
nbrs = neighbor_fn.allocate(positions_init, box=box)
nbrs_lr = neighbor_fn_lr.allocate(positions_init, box=box)
```

**Dynamic Updates:**
```python
nbrs = nbrs.update(state.position, neighbor=nbrs.idx, box=box)
nbrs_lr = nbrs_lr.update(state.position, neighbor_lr=nbrs_lr.idx, box=box)
```

**Overflow Handling:**
The examples include proper overflow detection and reallocation logic to handle cases where neighbor lists exceed their allocated capacity during simulation.

Sources: [examples/nvt_jaxmd.ipynb:157-165](), [examples/npt_jaxmd.ipynb:205-213](), [examples/npt_jaxmd.ipynb:605-617]()

## Structure Relaxation Workflow

Both examples begin with FIRE algorithm optimization to relax initial structures:

### FIRE Implementation Pattern

```mermaid
flowchart LR
    subgraph "FIRE Setup"
        FireInit["fire_init<br/>jax_md.minimize.fire_descent()"]
        FireApply["fire_apply<br/>JIT Compiled"]
        FireState["fire_state<br/>Initial Configuration"]
    end
    
    subgraph "Iterative Loop"
        StepFn["step_fire_fn<br/>Custom Step Function"]
        ForiLoop["jax.lax.fori_loop<br/>Batch Steps"]
        NbrUpdate["Neighbor Updates<br/>nbrs.update()"]
    end
    
    subgraph "Convergence Check"
        EnergyCalc["energy_fn<br/>Energy Evaluation"]
        ForceCalc["force_fn<br/>Force Evaluation"]
        MaxForce["np.abs(F).max()<br/>Convergence Criterion"]
    end
    
    FireInit --> FireState
    FireApply --> StepFn
    FireState --> StepFn
    StepFn --> ForiLoop
    ForiLoop --> NbrUpdate
    NbrUpdate --> EnergyCalc
    EnergyCalc --> ForceCalc
    ForceCalc --> MaxForce
    
    style FireState fill:#fff3e0
    style StepFn fill:#e8f5e8
    style MaxForce fill:#f3e5f5
```

**Typical Parameters:**
- `dt_start = 0.05` - Initial time step
- `dt_max = 0.1` - Maximum time step
- `n_min = 2` - Minimum steps before acceleration

Sources: [examples/nvt_jaxmd.ipynb:227-233](), [examples/npt_jaxmd.ipynb:299-305](), [examples/nvt_jaxmd.ipynb:243-265]()

## Production Simulation Considerations

The examples demonstrate several patterns important for production simulations:

### Performance Optimization
- **JIT Compilation**: All simulation functions are wrapped with `jax.jit()` for optimal performance
- **Batch Processing**: Uses `jax.lax.fori_loop()` for efficient batched time stepping
- **Memory Management**: Includes `jax.clear_caches()` to prevent memory accumulation

### Data Management
- **Trajectory Storage**: Simple list accumulation for short runs: `positions_md.append(np.array(state.position))`
- **Synchronization**: Uses `jax.block_until_ready()` for accurate timing measurements
- **Unit Conversion**: Proper handling of JAX-MD metal unit system

### Error Handling
- **Buffer Overflow**: Automatic detection and reallocation of neighbor lists
- **State Recovery**: Proper state management during neighbor list reallocation

Sources: [examples/nvt_jaxmd.ipynb:460-532](), [examples/npt_jaxmd.ipynb:594-601](), [examples/npt_jaxmd.ipynb:659-660]()

## Visualization and Output

Both examples include patterns for trajectory visualization and file output:

**ASE Integration for Visualization:**
```python
atoms_traj = []
for positions in positions_md:
    atoms_traj.append(
        Atoms(numbers=species, positions=positions)
    )
nv.show_asetraj(atoms_traj)
```

**XYZ File Output:**
```python
for frame in atoms_traj:
    write('trajectory.xyz', frame, append=True)
```

The examples note that for production runs, HDF5 format should be used instead of XYZ for efficient I/O operations with large systems.

Sources: [examples/nvt_jaxmd.ipynb:556-562](), [examples/npt_jaxmd.ipynb:684-693](), [examples/npt_jaxmd.ipynb:670-671]()

---