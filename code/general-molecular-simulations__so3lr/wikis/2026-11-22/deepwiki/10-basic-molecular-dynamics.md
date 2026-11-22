# Basic Molecular Dynamics

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [examples/npt_jaxmd.ipynb](examples/npt_jaxmd.ipynb)
- [examples/nvt_jaxmd.ipynb](examples/nvt_jaxmd.ipynb)

</details>



This document provides step-by-step tutorials for running molecular dynamics simulations using SO3LR with JAX-MD integration. It covers NVT (canonical ensemble) and NPT (isothermal-isobaric ensemble) simulations, including structure relaxation and simulation monitoring. For information about production-scale simulations with efficient data handling, see [Production Simulations](#4.2). For ASE-based workflow examples, see [ASE Integration](#3.1).

## Simulation Workflow Overview

The following diagram shows the complete workflow for running molecular dynamics simulations with SO3LR:

```mermaid
flowchart TD
    subgraph "Input"
        XYZ["XYZ File<br/>Molecular Structure"]
        Params["Simulation Parameters<br/>T, P, timestep, cycles"]
    end
    
    subgraph "System Setup"
        ASERead["ase.io.read()"]
        Species["species = atoms.get_atomic_numbers()"]
        Masses["masses = atoms.get_masses()"]
        Positions["positions = atoms.get_positions()"]
    end
    
    subgraph "JAX-MD Integration"
        Space["jax_md.space.free()<br/>or periodic_general()"]
        Potential["So3lrPotential()"]
        ToJAXMD["to_jax_md()"]
        EnergyFn["energy_fn"]
        NeighborFn["neighbor_fn, neighbor_fn_lr"]
    end
    
    subgraph "Structure Relaxation"
        FIRE["jax_md.minimize.fire_descent()"]
        FireState["fire_state.position"]
    end
    
    subgraph "MD Simulation"
        NVT["jax_md.simulate.nvt_nose_hoover()"]
        NPT["jax_md.simulate.npt_nose_hoover()"]
        StepFn["step_fn with neighbor updates"]
        ForiLoop["jax.lax.fori_loop()"]
    end
    
    subgraph "Output"
        Trajectory["positions_md[]<br/>Trajectory Data"]
        Analysis["Energy, Temperature<br/>Pressure Analysis"]
        Files["XYZ Files<br/>or HDF5 Output"]
    end
    
    XYZ --> ASERead
    Params --> NVT
    Params --> NPT
    
    ASERead --> Species
    ASERead --> Masses  
    ASERead --> Positions
    
    Species --> ToJAXMD
    Positions --> Space
    Space --> ToJAXMD
    Potential --> ToJAXMD
    
    ToJAXMD --> EnergyFn
    ToJAXMD --> NeighborFn
    
    EnergyFn --> FIRE
    NeighborFn --> FIRE
    Positions --> FIRE
    FIRE --> FireState
    
    FireState --> NVT
    FireState --> NPT
    EnergyFn --> StepFn
    NeighborFn --> StepFn
    
    NVT --> ForiLoop
    NPT --> ForiLoop
    StepFn --> ForiLoop
    
    ForiLoop --> Trajectory
    ForiLoop --> Analysis
    Trajectory --> Files
```

**Sources:** [examples/nvt_jaxmd.ipynb:1-605](), [examples/npt_jaxmd.ipynb:1-737]()

## System Setup and Initialization

### Loading Molecular Structures

The first step involves loading a molecular structure and extracting essential atomic properties:

| Property | Code | Purpose |
|----------|------|---------|
| Atomic positions | `atoms.get_positions()` | Initial coordinates |
| Atomic numbers | `atoms.get_atomic_numbers()` | Species identification |
| Atomic masses | `atoms.get_masses()` | Dynamics calculations |

### Boundary Conditions Setup

Different simulation scenarios require different spatial treatments:

```mermaid
graph LR
    subgraph "Vacuum Simulations"
        FreeSpace["jax_md.space.free()"]
        NoBox["box = None"]
        DisableCL["disable_cell_list = True"]
    end
    
    subgraph "Periodic Simulations"
        PeriodicSpace["jax_md.space.periodic_general()"]
        BoxSize["box = jnp.array([L])"]
        FracCoords["fractional_coordinates = True"]
        CellList["disable_cell_list = False"]
    end
    
    subgraph "Common Output"
        Displacement["displacement function"]
        Shift["shift function"]
    end
    
    FreeSpace --> Displacement
    FreeSpace --> Shift
    PeriodicSpace --> Displacement
    PeriodicSpace --> Shift
    
    NoBox --> DisableCL
    BoxSize --> CellList
```

**Sources:** [examples/nvt_jaxmd.ipynb:135-136](), [examples/npt_jaxmd.ipynb:136-140]()

### SO3LR Potential Integration

The `to_jax_md()` function converts SO3LR potentials into JAX-MD compatible format:

```mermaid
graph TD
    subgraph "Input Parameters"
        Potential["So3lrPotential(dtype=jnp.float64)"]
        Displacement["displacement function"]
        BoxSize["box_size"]
        Species["species array"]
        Multipliers["capacity_multiplier<br/>buffer_size_multiplier_sr/lr"]
    end
    
    subgraph "to_jax_md Function"
        ToJAXMD["to_jax_md()"]
    end
    
    subgraph "Output"
        NeighborFn["neighbor_fn<br/>(short-range)"]
        NeighborFnLR["neighbor_fn_lr<br/>(long-range)"]
        EnergyFn["energy_fn<br/>(JIT compiled)"]
    end
    
    Potential --> ToJAXMD
    Displacement --> ToJAXMD
    BoxSize --> ToJAXMD
    Species --> ToJAXMD
    Multipliers --> ToJAXMD
    
    ToJAXMD --> NeighborFn
    ToJAXMD --> NeighborFnLR
    ToJAXMD --> EnergyFn
```

**Sources:** [examples/nvt_jaxmd.ipynb:138-151](), [examples/npt_jaxmd.ipynb:186-199]()

## Structure Relaxation with FIRE Algorithm

Before running dynamics, structures are typically relaxed using the FIRE (Fast Inertial Relaxation Engine) algorithm:

### FIRE Implementation Pattern

```mermaid
graph TD
    subgraph "FIRE Setup"
        FireInit["fire_init, fire_apply = jax_md.minimize.fire_descent()"]
        FireParams["dt_start=0.05<br/>dt_max=0.1<br/>n_min=2"]
    end
    
    subgraph "State Management"
        InitState["fire_state = fire_init()"]
        StepFn["step_fire_fn()"]
        NeighborUpdate["nbrs.update()<br/>nbrs_lr.update()"]
    end
    
    subgraph "Optimization Loop"
        ForiLoop["jax.lax.fori_loop()"]
        MinCycles["min_cycles iterations"]
        MinSteps["min_steps per cycle"]
    end
    
    subgraph "Monitoring"
        Energy["energy_fn()"]
        Forces["force_fn()"]
        Convergence["Monitor Fmax"]
    end
    
    FireInit --> InitState
    FireParams --> FireInit
    InitState --> StepFn
    StepFn --> NeighborUpdate
    StepFn --> ForiLoop
    MinCycles --> ForiLoop
    MinSteps --> ForiLoop
    ForiLoop --> Energy
    ForiLoop --> Forces
    Energy --> Convergence
    Forces --> Convergence
```

**Sources:** [examples/nvt_jaxmd.ipynb:227-293](), [examples/npt_jaxmd.ipynb:299-367]()

## NVT Simulations (Canonical Ensemble)

NVT simulations maintain constant number of particles, volume, and temperature using Nosé-Hoover thermostats.

### Key NVT Components

| Component | Function | Purpose |
|-----------|----------|---------|
| Thermostat | `jax_md.simulate.nvt_nose_hoover()` | Temperature control |
| Chain parameters | `default_nhc_kwargs()` | Thermostat configuration |
| Time integration | `apply_fn()` | State evolution |
| Invariant monitoring | `nvt_nose_hoover_invariant()` | Energy conservation |

### NVT Simulation Loop Structure

The simulation follows a standard pattern with JIT-compiled step functions and neighbor list management:

```python
@jax.jit
def step_nvt_fn(i, state):
    state, nbrs, nbrs_lr, box, temp_i = state
    
    state = apply_fn(state, neighbor=nbrs.idx, neighbor_lr=nbrs_lr.idx, kT=temp_i, box=box)
    
    nbrs = nbrs.update(state.position, neighbor=nbrs.idx, box=box)
    nbrs_lr = nbrs_lr.update(state.position, neighbor_lr=nbrs_lr.idx, box=box)
    
    return state, nbrs, nbrs_lr, box, temp_i
```

**Sources:** [examples/nvt_jaxmd.ipynb:410-532]()

## NPT Simulations (Isothermal-Isobaric Ensemble)

NPT simulations maintain constant number of particles, pressure, and temperature, allowing volume fluctuations.

### NPT-Specific Features

```mermaid
graph LR
    subgraph "NPT Components"
        Barostat["Barostat<br/>Pressure Control"]
        Thermostat["Thermostat<br/>Temperature Control"]
        BoxUpdate["jax_md.simulate.npt_box()"]
    end
    
    subgraph "Additional Monitoring"
        Invariant["npt_nose_hoover_invariant()"]
        EnergyDrift["Energy drift calculation"]
        PressureCalc["Pressure monitoring"]
    end
    
    subgraph "Dynamic Updates"
        NeighborUpdate["Neighbor list updates<br/>with changing box"]
        FracCoords["Fractional coordinate<br/>transformations"]
    end
    
    Barostat --> BoxUpdate
    Thermostat --> BoxUpdate
    BoxUpdate --> NeighborUpdate
    BoxUpdate --> FracCoords
    Invariant --> EnergyDrift
    BoxUpdate --> PressureCalc
```

### Periodic Boundary Conditions in NPT

NPT simulations typically use periodic boundary conditions with fractional coordinates:

| Aspect | Implementation | Purpose |
|--------|----------------|---------|
| Box representation | `box = jnp.array([L])` | Cubic cell |
| Coordinate system | `fractional_coordinates=True` | Handle box changes |
| Position scaling | `positions_init / box` | Normalize to [0,1] |
| Real space conversion | `jax_md.space.transform()` | Output processing |

**Sources:** [examples/npt_jaxmd.ipynb:509-661]()

## Key Classes and Functions

The following diagram maps the primary code entities used in MD simulations:

```mermaid
graph TB
    subgraph "SO3LR Core Classes"
        So3lrPotential["So3lrPotential<br/>Main potential class"]
        ToJaxMD["to_jax_md()<br/>Integration function"]
    end
    
    subgraph "JAX-MD Simulation Functions"
        NVTNoseHoover["jax_md.simulate.nvt_nose_hoover()"]
        NPTNoseHoover["jax_md.simulate.npt_nose_hoover()"]
        FireDescent["jax_md.minimize.fire_descent()"]
    end
    
    subgraph "Space and Neighbor Management"
        SpaceFree["jax_md.space.free()"]
        SpacePeriodic["jax_md.space.periodic_general()"]
        NeighborFn["neighbor_fn.allocate()<br/>neighbor_fn.update()"]
    end
    
    subgraph "Quantity Calculations"
        KineticEnergy["jax_md.quantity.kinetic_energy()"]
        Temperature["jax_md.quantity.temperature()"]
        Force["jax_md.quantity.force()"]
    end
    
    subgraph "Control Flow"
        ForiLoop["jax.lax.fori_loop()"]
        JaxJit["@jax.jit decorators"]
        BlockUntilReady["jax.block_until_ready()"]
    end
    
    So3lrPotential --> ToJaxMD
    ToJaxMD --> NeighborFn
    
    SpaceFree --> ToJaxMD
    SpacePeriodic --> ToJaxMD
    
    ToJaxMD --> NVTNoseHoover
    ToJaxMD --> NPTNoseHoover
    ToJaxMD --> FireDescent
    
    NVTNoseHoover --> ForiLoop
    NPTNoseHoover --> ForiLoop
    FireDescent --> ForiLoop
    
    ForiLoop --> JaxJit
    ForiLoop --> BlockUntilReady
    
    KineticEnergy --> Temperature
    Force --> FireDescent
```

**Sources:** [examples/nvt_jaxmd.ipynb:1-605](), [examples/npt_jaxmd.ipynb:1-737]()

---