# HOOMD-blue Overview

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.github/ISSUE_TEMPLATE/config.yml](.github/ISSUE_TEMPLATE/config.yml)
- [.mailmap](.mailmap)
- [CHANGELOG.rst](CHANGELOG.rst)
- [README.md](README.md)
- [hoomd/Analyzer.cc](hoomd/Analyzer.cc)
- [hoomd/Analyzer.h](hoomd/Analyzer.h)
- [hoomd/Compute.cc](hoomd/Compute.cc)
- [hoomd/Compute.h](hoomd/Compute.h)
- [hoomd/System.cc](hoomd/System.cc)
- [hoomd/System.h](hoomd/System.h)
- [hoomd/Updater.cc](hoomd/Updater.cc)
- [hoomd/Updater.h](hoomd/Updater.h)
- [hoomd/box.py](hoomd/box.py)
- [hoomd/conftest.py](hoomd/conftest.py)
- [hoomd/hpmc/.gitignore](hoomd/hpmc/.gitignore)
- [hoomd/pytest/test_box.py](hoomd/pytest/test_box.py)
- [hoomd/simulation.py](hoomd/simulation.py)
- [hoomd/snapshot.py](hoomd/snapshot.py)
- [hoomd/state.py](hoomd/state.py)
- [sphinx-doc/credits.rst](sphinx-doc/credits.rst)
- [sphinx-doc/deprecated.rst](sphinx-doc/deprecated.rst)
- [sphinx-doc/index.rst](sphinx-doc/index.rst)
- [sphinx-doc/migrating.rst](sphinx-doc/migrating.rst)

</details>



This document provides an overview of the HOOMD-blue simulation framework architecture, its core components, and how they interact to enable particle-based simulations. For detailed information about specific features like Hard Particle Monte Carlo (HPMC), Molecular Dynamics (MD), or Multi-Particle Collision Dynamics (MPCD), see their respective documentation pages.

## Core Architecture

HOOMD-blue is a particle simulation package that performs both hard particle Monte Carlo simulations and molecular dynamics simulations on CPUs and GPUs. The framework follows a layered architecture with Python interfaces built on top of high-performance C++ implementations.

```mermaid
graph TD
    User["User Python Code"] --> Simulation["Simulation"]
    Simulation --> State["State"]
    Simulation --> Operations["Operations"]
    Simulation --> Device["Device"]
    
    Device --> CPU["CPU"]
    Device --> GPU["GPU"]
    
    Operations --> Integrators["Integrator"]
    Operations --> Updaters["Updater List"]
    Operations --> Writers["Writer List"]
    Operations --> Tuners["Tuner List"]
    
    Integrators --> HPMC["HPMC Integrators"]
    Integrators --> MD["MD Integrator"]
    Integrators --> MPCD["MPCD Integrator"]
    
    State --> ParticleData["Particle Data"]
    State --> Box["Box"]
    State --> BondData["Bond Data"]
```

Sources: [hoomd/simulation.py:34-130](), [hoomd/state.py:80-140](), [hoomd/System.cc:37-52]()

## Simulation Workflow

A typical HOOMD-blue simulation follows this sequence:

```mermaid
sequenceDiagram
    participant User as "User Code"
    participant Sim as "Simulation"
    participant State as "State"
    participant Ops as "Operations"
    participant Int as "Integrator"
    
    User->>Sim: Create Simulation(device, seed)
    User->>Sim: create_state_from_gsd/snapshot()
    Sim->>State: Initialize state
    User->>Ops: Configure integrator, updaters, writers, tuners
    User->>Sim: run(steps)
    
    loop For each timestep
        Sim->>Ops: Run tuners
        Sim->>Ops: Run updaters
        Sim->>Int: Integrate timestep
        Sim->>Ops: Run writers
    end
```

Sources: [hoomd/simulation.py:484-524](), [hoomd/System.cc:128-180]()

## Key Components

### Simulation Class

The `Simulation` class is the central controller that orchestrates the entire simulation process. It manages the device, state, and operations, coordinating their interactions during the simulation run.

```mermaid
classDiagram
    class Simulation {
        +device: Device
        +state: State
        +operations: Operations
        +timestep: int
        +seed: int
        +tps: float
        +walltime: float
        +run(steps, write_at_start)
        +create_state_from_gsd(filename, frame, domain_decomposition)
        +create_state_from_snapshot(snapshot, domain_decomposition)
    }
```

The `Simulation` class provides methods to initialize the simulation state from various sources and to run the simulation for a specified number of steps. It also exposes properties like the current timestep, random seed, and performance metrics.

Sources: [hoomd/simulation.py:34-95](), [hoomd/simulation.py:484-546]()

### State

The `State` class stores and manages the current state of the simulation, including particles, bonds, angles, dihedrals, and the simulation box.

```mermaid
classDiagram
    class State {
        +box: Box
        +particle_types: list
        +bond_types: list
        +angle_types: list
        +dihedral_types: list
        +improper_types: list
        +special_pair_types: list
        +N_particles: int
        +N_bonds: int
        +N_angles: int
        +N_dihedrals: int
        +N_impropers: int
        +N_special_pairs: int
        +N_constraints: int
        +get_snapshot()
        +set_snapshot(snapshot)
        +set_box(box)
        +replicate(nx, ny, nz)
    }
```

The `State` provides methods to access and modify data, and to save and restore the system state through snapshots.

Sources: [hoomd/state.py:80-258](), [hoomd/state.py:280-316]()

### Operations

The `Operations` class manages all the operations that apply to the state during a simulation run, which include:

```mermaid
classDiagram
    class Operations {
        +integrator: Integrator
        +updaters: list
        +writers: list
        +tuners: list
    }
    
    class Integrator {
        +update(timestep)
    }
    
    class Updater {
        +update(timestep)
        +trigger
    }
    
    class Writer {
        +write(timestep)
        +trigger
    }
    
    class Tuner {
        +tune(timestep)
        +trigger
    }
    
    Operations --> Integrator: "contains"
    Operations --> Updater: "contains many"
    Operations --> Writer: "contains many"
    Operations --> Tuner: "contains many"
```

During each simulation timestep, operations are executed in this order:
1. Tuners optimize performance parameters
2. Updaters modify the simulation state
3. The integrator advances the system
4. Writers output data

Sources: [hoomd/System.cc:131-174](), [hoomd/Updater.h:56-67](), [hoomd/Analyzer.h:57-68](), [hoomd/Compute.h:58-69]()

### Device

The `Device` class represents the computational hardware where the simulation runs (CPU or GPU) and manages related resources.

```mermaid
classDiagram
    class Device {
        +communicator
        +notice_level
    }
    
    class CPU {
        +communicator
    }
    
    class GPU {
        +gpu_id
        +gpu_error_checking
    }
    
    Device <|-- CPU
    Device <|-- GPU
```

HOOMD-blue supports both CPU and GPU execution with optional MPI parallelization for distributed computing.

Sources: [hoomd/simulation.py:147-186](), [hoomd/conftest.py:74-88]()

## Simulation Engines

HOOMD-blue provides three major simulation engines:

### Hard Particle Monte Carlo (HPMC)

The HPMC engine simulates hard particles using Monte Carlo methods. It handles various particle shapes and rejection-free trial moves.

```mermaid
graph TD
    HPMC["HPMC Integrator"] --> Shapes["Shape Definitions"]
    HPMC --> MoveGen["Move Generation"]
    HPMC --> Overlap["Overlap Detection"]
    HPMC --> Accept["Move Acceptance/Rejection"]
    
    Shapes --> Sphere["Sphere"]
    Shapes --> Poly["Polyhedron"]
    Shapes --> Ellipsoid["Ellipsoid"]
    Shapes --> Union["ShapeUnion"]
    
    Overlap --> AABB["AABB Trees"]
    Overlap --> OBB["OBB Trees"]
    
    HPMC --> PairPot["Pair Potentials"]
    HPMC --> ExtPot["External Potentials"]
```

Sources: (Based on diagrams provided)

### Molecular Dynamics (MD)

The MD engine simulates particles interacting through continuous potentials by integrating Newton's equations of motion.

```mermaid
graph TD
    MD["MD Integrator"] --> Forces["Force Computation"]
    MD --> Methods["Integration Methods"]
    MD --> NLists["Neighbor Lists"]
    
    Forces --> PairForces["Pair Forces"]
    Forces --> BondForces["Bond Forces"]
    Forces --> AngleForces["Angle Forces"]
    Forces --> DihedralForces["Dihedral Forces"]
    Forces --> External["External Forces"]
    
    Methods --> ConstVol["ConstantVolume"]
    Methods --> ConstPress["ConstantPressure"]
    Methods --> Thermostats["Thermostats"]
    
    NLists --> Cell["Cell List"]
    NLists --> Tree["Tree List"]
```

Sources: (Based on diagrams provided)

### Multi-Particle Collision Dynamics (MPCD)

The MPCD engine simulates fluid dynamics and hydrodynamic interactions for soft matter systems.

```mermaid
graph TD
    MPCD["MPCD Integrator"] --> Stream["Streaming"]
    MPCD --> Collide["Collision"]
    MPCD --> Geometries["Geometries"]
    MPCD --> VirtualParts["Virtual Particles"]
    
    Geometries --> Channel["Channel"]
    Geometries --> Cylinder["Cylinder"]
    Geometries --> Plates["Parallel Plates"]
```

Sources: (Based on diagrams provided)

## System Implementation

The Python interface is backed by a C++ implementation with these core classes:

```mermaid
classDiagram
    class SystemDefinition {
        +getParticleData()
        +getBondData()
        +getAngleData()
        +getDihedralData()
        +getImproperData()
        +getPairData()
        +getConstraintData()
    }
    
    class System {
        +run(nsteps, write_at_start)
        +setIntegrator(integrator)
        +getIntegrator()
        +getLastTPS()
        +getCurrentTimeStep()
    }
    
    class Action {
        +SystemDefinition sysdef
        +ExecutionConf exec_conf
    }
    
    class Integrator {
        +update(timestep)
        +prepRun(timestep)
    }
    
    class Analyzer {
        +analyze(timestep)
        +Trigger trigger
    }
    
    class Updater {
        +update(timestep)
        +Trigger trigger
    }
    
    Action <|-- Integrator
    Action <|-- Analyzer
    Action <|-- Updater
    
    System --> Integrator: "contains"
    System --> Analyzer: "contains many"
    System --> Updater: "contains many"
    System --> SystemDefinition: "references"
```

This diagram shows the relationship between the key C++ classes that implement the simulation framework. The `System` class orchestrates the execution of operations during a simulation run.

Sources: [hoomd/System.h:61-146](), [hoomd/System.cc:37-188](), [hoomd/Compute.h:58-69](), [hoomd/Analyzer.h:57-68](), [hoomd/Updater.h:56-67]()

## Box and Boundary Conditions

HOOMD-blue simulations occur in a triclinic box with periodic boundary conditions:

```mermaid
classDiagram
    class Box {
        +Lx: float
        +Ly: float
        +Lz: float
        +xy: float
        +xz: float
        +yz: float
        +dimensions: int
        +is2D: bool
        +volume: float
        +L: array
        +tilts: array
        +cube(L)
        +square(L)
        +from_matrix(box_matrix)
        +from_basis_vectors(box_matrix)
    }
```

The `Box` class defines the simulation domain with its dimensions and tilt factors, supporting both 2D and 3D simulations.

Sources: [hoomd/box.py:58-183](), [hoomd/state.py:537-593]()

## Snapshot System

The `Snapshot` class provides a mechanism to capture and manipulate the complete state of a simulation:

```mermaid
classDiagram
    class Snapshot {
        +configuration
        +particles
        +bonds
        +angles
        +dihedrals
        +impropers
        +pairs
        +constraints
        +mpcd
        +replicate(nx, ny, nz)
        +from_gsd_frame(frame)
    }
    
    class State {
        +get_snapshot()
        +set_snapshot(snapshot)
    }
    
    State --> Snapshot: "creates/uses"
```

`Snapshot` is a self-contained copy of the simulation state that can be used to save, restore, or initialize simulations. It is also compatible with the GSD file format for persistent storage.

Sources: [hoomd/snapshot.py:52-92](), [hoomd/state.py:280-316]()

## Conclusion

HOOMD-blue provides a flexible, high-performance framework for particle simulations across diverse hardware platforms. Its modular architecture allows researchers to:

1. Choose between different simulation methods (HPMC, MD, MPCD)
2. Run on various computing platforms (CPU, GPU, distributed systems)
3. Configure detailed simulation parameters
4. Capture and analyze simulation data efficiently

This overview document covers the main architectural components and their interactions. For detailed usage of specific features, refer to the respective documentation sections.

---