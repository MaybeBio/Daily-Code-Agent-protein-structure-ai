# Analysis and Computation

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/components/ramachandran/ramachandran.cpp](src/components/ramachandran/ramachandran.cpp)
- [src/components/shapespace/shapespace.cpp](src/components/shapespace/shapespace.cpp)
- [src/components/veloxchem/veloxchem.cpp](src/components/veloxchem/veloxchem.cpp)
- [src/event.h](src/event.h)
- [src/main.cpp](src/main.cpp)
- [src/task_system.cpp](src/task_system.cpp)
- [src/task_system.h](src/task_system.h)
- [src/viamd.h](src/viamd.h)

</details>



This document covers VIAMD's analysis and computation capabilities, including the parallel task system, molecular dynamics analysis components, and quantum chemistry integration. The analysis system provides specialized tools for protein structure analysis (Ramachandran plots), molecular shape characterization (shape space), and electronic structure visualization (VeloxChem integration).

For information about the graphics rendering pipeline, see [Graphics and Visualization Pipeline](#3). For details about the user interface components that display analysis results, see [User Interface Framework](#5).

## Analysis System Architecture

VIAMD's analysis system is built around an event-driven architecture with asynchronous task processing. The system coordinates multiple specialized analysis components through a centralized event system and executes computationally intensive work using a parallel task scheduler.

### Component Overview

```mermaid
graph TB
    subgraph "Event Coordination Layer"
        ES["viamd::event_system"]
        EH["viamd::EventHandler Interface"]
    end
    
    subgraph "Task Processing Layer"
        TS["task_system Namespace"]
        POOL["Pool Tasks (Worker Threads)"]
        MAIN["Main Tasks (Main Thread)"]
    end
    
    subgraph "Analysis Components"
        RAMA["Ramachandran Component"]
        SHAPE["Shapespace Component"] 
        VLX["VeloxChem Component"]
    end
    
    subgraph "Data Structures"
        AS["ApplicationState"]
        PROPS["DisplayProperty[]"]
        TASKS["task_system::ID handles"]
    end
    
    ES --> EH
    EH --> RAMA
    EH --> SHAPE
    EH --> VLX
    
    RAMA --> TS
    SHAPE --> TS
    VLX --> TS
    
    TS --> POOL
    TS --> MAIN
    
    RAMA --> AS
    SHAPE --> AS
    VLX --> AS
    
    AS --> PROPS
    AS --> TASKS
```

**Sources:** [src/event.h:72-75](), [src/task_system.h:9-64](), [src/components/ramachandran/ramachandran.cpp:432](), [src/components/shapespace/shapespace.cpp:42](), [src/components/veloxchem/veloxchem.cpp:288]()

### Event-Driven Component Coordination

The analysis system uses a centralized event system to coordinate between components and the main application. Each analysis component implements the `viamd::EventHandler` interface and registers itself to receive relevant events.

```mermaid
graph LR
    subgraph "Event Types"
        INIT["EventType_ViamdInitialize"]
        TICK["EventType_ViamdFrameTick"] 
        TOPO["EventType_ViamdTopologyInit"]
        MENU["EventType_ViamdWindowDrawMenu"]
        REP["EventType_RepresentationInfoFill"]
    end
    
    subgraph "Analysis Components"
        RAMA_H["Ramachandran::process_events()"]
        SHAPE_H["Shapespace::process_events()"]
        VLX_H["VeloxChem::process_events()"]
    end
    
    INIT --> RAMA_H
    INIT --> SHAPE_H
    INIT --> VLX_H
    
    TICK --> RAMA_H
    TICK --> SHAPE_H
    TICK --> VLX_H
    
    TOPO --> RAMA_H
    TOPO --> VLX_H
    
    MENU --> RAMA_H
    MENU --> SHAPE_H
    MENU --> VLX_H
    
    REP --> VLX_H
```

**Sources:** [src/event.h:16-52](), [src/components/ramachandran/ramachandran.cpp:518-548](), [src/components/shapespace/shapespace.cpp:76-127](), [src/components/veloxchem/veloxchem.cpp:503-786]()

## Parallel Task System

The task system provides asynchronous computation capabilities through a thread pool architecture. It supports both main thread tasks (for UI updates) and worker pool tasks (for computation-intensive operations).

### Task Management Architecture

```mermaid
graph TB
    subgraph "Task Creation"
        CREATE_MAIN["create_main_task()"]
        CREATE_POOL["create_pool_task()"]
        CREATE_RANGE["create_pool_task() with RangeTask"]
    end
    
    subgraph "Task Storage"
        MAIN_SLOTS["main::task_data[MAX_TASKS]"]
        POOL_SLOTS["pool::task_data[MAX_TASKS]"]
        FREE_MAIN["main::free_slots queue"]
        FREE_POOL["pool::free_slots queue"]
    end
    
    subgraph "Execution Engine" 
        TS["enki::TaskScheduler"]
        MAIN_EXEC["execute_main_task_queue()"]
        POOL_EXEC["Worker Thread Pool"]
    end
    
    CREATE_MAIN --> FREE_MAIN
    CREATE_POOL --> FREE_POOL
    CREATE_RANGE --> FREE_POOL
    
    FREE_MAIN --> MAIN_SLOTS
    FREE_POOL --> POOL_SLOTS
    
    MAIN_SLOTS --> MAIN_EXEC
    POOL_SLOTS --> POOL_EXEC
    
    MAIN_EXEC --> TS
    POOL_EXEC --> TS
```

**Sources:** [src/task_system.cpp:22-296](), [src/task_system.h:9-64]()

### Task Lifecycle and Dependencies

The task system manages task lifecycles through unique IDs and supports dependency chains between tasks:

| Task State | Description | Key Functions |
|------------|-------------|---------------|
| Created | Task allocated but not queued | `create_main_task()`, `create_pool_task()` |
| Dependent | Waiting for dependency completion | `set_task_dependency()` |
| Queued | Ready for execution | `enqueue_task()` |
| Running | Currently executing | `task_is_running()` |
| Complete | Finished execution | Automatic cleanup |

**Sources:** [src/task_system.cpp:158-296](), [src/task_system.h:29-62]()

## Ramachandran Plot Analysis

The Ramachandran component analyzes protein backbone conformation by computing phi-psi angle distributions. It generates density maps for different residue types and provides interactive visualization.

### Ramachandran Component Structure

```mermaid
graph TB
    subgraph "Ramachandran Class"
        RAMA_DATA["rama_data (ref/full/filt)"]
        RAMA_REP["rama_rep_t structures"]
        INDICES["rama_type_indices[4]"]
        TASKS["compute_density_full/filt IDs"]
    end
    
    subgraph "Density Computation"
        COMPUTE["rama_rep_compute_density()"]
        BLUR["blur_density_gaussian()"]
        TEXTURE["OpenGL texture upload"]
    end
    
    subgraph "Visualization Pipeline"
        MAP_SHADER["map.program (colormap)"]
        ISO_SHADER["iso.program (isolines)"]
        FBO["framebuffer rendering"]
    end
    
    RAMA_DATA --> COMPUTE
    INDICES --> COMPUTE
    COMPUTE --> BLUR
    BLUR --> TEXTURE
    
    RAMA_REP --> MAP_SHADER
    RAMA_REP --> ISO_SHADER
    MAP_SHADER --> FBO
    ISO_SHADER --> FBO
    
    TASKS --> COMPUTE
```

**Sources:** [src/components/ramachandran/ramachandran.cpp:432-476](), [src/components/ramachandran/ramachandran.cpp:390-431](), [src/components/ramachandran/ramachandran.cpp:550-611]()

### Ramachandran Types and Processing

The system classifies residues into four Ramachandran types and processes them separately:

| Type | Enum Value | Description |
|------|------------|-------------|
| General | `MD_RAMACHANDRAN_TYPE_GENERAL` | Standard amino acids |
| Glycine | `MD_RAMACHANDRAN_TYPE_GLYCINE` | Glycine residues |
| Proline | `MD_RAMACHANDRAN_TYPE_PROLINE` | Proline residues |
| Pre-Proline | `MD_RAMACHANDRAN_TYPE_PREPROL` | Residues before proline |

**Sources:** [src/components/ramachandran/ramachandran.cpp:637-645]()

## Shape Space Analysis

The shape space component characterizes molecular shapes using principal moment analysis, projecting structures onto a triangular shape space defined by linear, planar, and spherical extremes.

### Shape Space Computation Pipeline

```mermaid
graph LR
    subgraph "Input Processing"
        FILTER["md_filter_evaluate()"]
        BITFIELDS["md_bitfield_t structures"]
    end
    
    subgraph "Frame Analysis"
        LOAD["md_trajectory_load_frame()"]
        COM["md_util_com_compute_vec4()"]
        DEPBC["md_util_deperiodize_vec4()"]
        COV["mat3_covariance_matrix_vec4()"]
        SHAPE["md_util_shape_weights()"]
    end
    
    subgraph "Visualization"
        COORDS["triangular coordinates"]
        PLOT["ImPlot::PlotScatterG()"]
    end
    
    FILTER --> BITFIELDS
    BITFIELDS --> LOAD
    LOAD --> COM
    COM --> DEPBC
    DEPBC --> COV
    COV --> SHAPE
    SHAPE --> COORDS
    COORDS --> PLOT
```

**Sources:** [src/components/shapespace/shapespace.cpp:360-428](), [src/components/shapespace/shapespace.cpp:394-421]()

### Shape Weight Calculation

The system computes three shape descriptors that sum to 1.0:

```mermaid
graph TB
    subgraph "Shape Triangle Vertices"
        LIN["Linear (0,0)"]
        PLA["Planar (1,0)"] 
        ISO["Spherical (0.5, 0.866)"]
    end
    
    subgraph "Weight Computation"
        MOMENTS["Principal moments λ₁ ≥ λ₂ ≥ λ₃"]
        W_LIN["w_linear = (λ₁-λ₂)/(λ₁+λ₂+λ₃)"]
        W_PLA["w_planar = 2(λ₂-λ₃)/(λ₁+λ₂+λ₃)"]
        W_ISO["w_spherical = 3λ₃/(λ₁+λ₂+λ₃)"]
    end
    
    subgraph "Final Coordinates"
        COORD["coord = w_lin*LIN + w_pla*PLA + w_iso*ISO"]
    end
    
    MOMENTS --> W_LIN
    MOMENTS --> W_PLA  
    MOMENTS --> W_ISO
    
    W_LIN --> COORD
    W_PLA --> COORD
    W_ISO --> COORD
    
    LIN --> COORD
    PLA --> COORD
    ISO --> COORD
```

**Sources:** [src/components/shapespace/shapespace.cpp:394-422]()

## VeloxChem Integration

The VeloxChem component integrates quantum chemistry calculations, providing molecular orbital visualization, natural transition orbital analysis, and electronic structure properties.

### VeloxChem Component Architecture

```mermaid
graph TB
    subgraph "VeloxChem Class"
        VLX_PTR["md_vlx_t* vlx"]
        GPU_PATH["use_gpu_path flag"]
        ARENA["md_allocator_i* arena"]
    end
    
    subgraph "Analysis Modules"
        ORB["orb (Molecular Orbitals)"]
        NTO["nto (Natural Transition Orbitals)"]
        RSP["rsp (Response Properties)"]
        VIB["vib (Vibrational Analysis)"]
        OPT["opt (Geometry Optimization)"]
    end
    
    subgraph "Computation Paths"
        GPU["GPU computation (OpenGL compute)"]
        CPU["CPU computation (async tasks)"]
    end
    
    VLX_PTR --> ORB
    VLX_PTR --> NTO
    VLX_PTR --> RSP
    VLX_PTR --> VIB
    VLX_PTR --> OPT
    
    GPU_PATH --> GPU
    GPU_PATH --> CPU
    
    ORB --> GPU
    ORB --> CPU
    NTO --> GPU  
    NTO --> CPU
```

**Sources:** [src/components/veloxchem/veloxchem.cpp:288-491](), [src/components/veloxchem/veloxchem.cpp:683-748]()

### Electronic Structure Evaluation Pipeline

The VeloxChem component handles requests for electronic structure visualization through the event system:

```mermaid
graph LR
    subgraph "Event Processing"
        REP_EVENT["RepresentationEvalElectronicStructure"]
        EVAL_DATA["EvalElectronicStructure payload"]
    end
    
    subgraph "Structure Types"
        MO["MolecularOrbital"]
        MO_DEN["MolecularOrbitalDensity"] 
        NTO_P["NTO Particle"]
        NTO_H["NTO Hole"]
        ATTACH["AttachmentDensity"]
        DETACH["DetachmentDensity"]
        ELEC_DEN["ElectronDensity"]
    end
    
    subgraph "Computation Methods"
        GPU_COMP["compute_mo_GPU()"]
        CPU_COMP["compute_mo_async()"]
        GRID_INIT["init_grid()"]
        VOL_INIT["init_volume()"]
    end
    
    REP_EVENT --> EVAL_DATA
    EVAL_DATA --> MO
    EVAL_DATA --> MO_DEN
    EVAL_DATA --> NTO_P
    EVAL_DATA --> NTO_H
    EVAL_DATA --> ATTACH
    EVAL_DATA --> DETACH
    EVAL_DATA --> ELEC_DEN
    
    MO --> GRID_INIT
    MO_DEN --> GRID_INIT
    GRID_INIT --> VOL_INIT
    VOL_INIT --> GPU_COMP
    VOL_INIT --> CPU_COMP
```

**Sources:** [src/components/veloxchem/veloxchem.cpp:683-751](), [src/viamd.h:313-324]()

## Analysis Data Flow

The analysis system processes molecular dynamics data through several stages, from raw trajectory frames to interactive visualizations:

### Overall Data Processing Pipeline

```mermaid
graph TB
    subgraph "Input Data"
        TRAJ["md_trajectory_i* traj"]
        MOL["md_molecule_t mol"]
        BACKBONE["backbone_angles.data"]
    end
    
    subgraph "Analysis Processing"
        RAMA_TASK["Ramachandran density computation"]
        SHAPE_TASK["Shape space evaluation"]
        VLX_TASK["Electronic structure evaluation"]
    end
    
    subgraph "Intermediate Results"
        DENSITY["Density maps (RGBA textures)"]
        WEIGHTS["Shape weights (vec3_t arrays)"]
        VOLUMES["Volume data (3D textures)"]
    end
    
    subgraph "Display Properties"
        TEMPORAL["Temporal plots"]
        DISTRIBUTION["Distribution plots"] 
        VOLUME_VIS["Volume visualization"]
        SCATTER["Scatter plots"]
    end
    
    TRAJ --> RAMA_TASK
    MOL --> SHAPE_TASK
    BACKBONE --> RAMA_TASK
    
    RAMA_TASK --> DENSITY
    SHAPE_TASK --> WEIGHTS
    VLX_TASK --> VOLUMES
    
    DENSITY --> DISTRIBUTION
    WEIGHTS --> SCATTER
    VOLUMES --> VOLUME_VIS
    
    DENSITY --> TEMPORAL
    WEIGHTS --> TEMPORAL
```

**Sources:** [src/main.cpp:467-471](), [src/components/ramachandran/ramachandran.cpp:652-679](), [src/components/shapespace/shapespace.cpp:344-430](), [src/components/veloxchem/veloxchem.cpp:683-748]()

### Task Coordination and Dependencies

Analysis components coordinate their computations through the task system, ensuring proper dependency management and resource utilization:

| Component | Task Types | Dependencies | Output |
|-----------|------------|--------------|---------|
| Ramachandran | `compute_density_full`, `compute_density_filt` | Backbone angles data | Density textures |
| Shape Space | `evaluate_task` (range task) | Trajectory frames | Weight arrays |
| VeloxChem | Various async orbital tasks | VLX data loaded | Volume textures |

**Sources:** [src/components/ramachandran/ramachandran.cpp:511-512](), [src/components/shapespace/shapespace.cpp:70](), [src/components/veloxchem/veloxchem.cpp:325-358]()

---