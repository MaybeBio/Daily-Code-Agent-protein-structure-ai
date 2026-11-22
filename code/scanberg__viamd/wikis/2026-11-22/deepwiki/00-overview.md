# Overview

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.github/workflows/macos.yml](.github/workflows/macos.yml)
- [.github/workflows/ubuntu22.yml](.github/workflows/ubuntu22.yml)
- [.github/workflows/windows.yml](.github/workflows/windows.yml)
- [CMakeLists.txt](CMakeLists.txt)
- [README.md](README.md)
- [src/components/veloxchem/veloxchem.cpp](src/components/veloxchem/veloxchem.cpp)
- [src/main.cpp](src/main.cpp)
- [src/viamd.h](src/viamd.h)

</details>



This document provides a high-level introduction to VIAMD (Visual Interactive Analysis of Molecular Dynamics), summarizing its purpose, core architecture, and key components. For detailed information about specific subsystems, see the [Core Application Architecture](#2), [Graphics and Visualization Pipeline](#3), [Analysis and Computation](#4), and [User Interface Framework](#5).

## Purpose and Scope

VIAMD is an interactive analysis tool for molecular dynamics (MD) simulations written in C/C++. The application enables scientists to visualize molecular trajectories, perform computational analysis, and interact with molecular data through a comprehensive scripting language. VIAMD supports multiple molecular file formats and provides specialized analysis capabilities including Ramachandran plots, shape space analysis, and quantum chemistry visualization through VeloxChem integration.

The software is designed as a real-time, interactive application that processes molecular trajectories and provides immediate visual feedback through a modern graphics pipeline built on OpenGL. The core architecture follows an event-driven pattern with parallel task execution for computationally intensive operations.

Sources: [README.md:1-5](), [src/main.cpp:99-117]()

## System Architecture Overview

VIAMD follows a modular architecture centered around a main application state (`ApplicationState`) that coordinates between subsystems through an event-driven communication pattern.

```mermaid
graph TB
    subgraph "Application Core"
        AppLoop["main() Application Loop<br/>src/main.cpp"]
        AppState["ApplicationState<br/>src/viamd.h:396"]
        EventSys["Event System<br/>src/event.cpp"]
    end
    
    subgraph "Data Loading & Management"
        FileQueue["FileQueue<br/>src/viamd.h:199"]
        LoaderSys["Load System<br/>src/loader.cpp"]
        MolData["md_molecule_t & md_trajectory_i<br/>MDLib Integration"]
    end
    
    subgraph "Graphics Pipeline"
        GBuffer["GBuffer<br/>Deferred Rendering"]
        VolRender["Volume Rendering<br/>src/gfx/volumerender_utils.cpp"]
        PostFX["Post-Processing<br/>src/gfx/postprocessing_utils.cpp"]
        GLShaders["md_gl_shaders_t<br/>GLSL Shader Management"]
    end
    
    subgraph "Analysis Components"
        TaskSys["Task System<br/>src/task_system.cpp"]
        ScriptEval["Script Evaluation<br/>md_script_eval_t"]
        RamaComp["Ramachandran Component<br/>src/components/ramachandran/"]
        ShapeComp["Shape Space Component<br/>src/components/shapespace/"]
        VeloxComp["VeloxChem Component<br/>src/components/veloxchem/"]
    end
    
    subgraph "User Interface"
        ImGuiCore["ImGui Framework<br/>ext/imgui/"]
        CustomWidgets["Custom Widgets<br/>src/imgui_widgets.cpp"]
        TextEditor["Script Editor<br/>ext/ImGuiColorTextEdit/"]
        PlotSystem["ImPlot<br/>ext/implot/"]
    end
    
    AppLoop --> AppState
    AppState --> EventSys
    EventSys --> LoaderSys
    EventSys --> RamaComp
    EventSys --> ShapeComp
    EventSys --> VeloxComp
    
    LoaderSys --> MolData
    FileQueue --> LoaderSys
    
    AppState --> GBuffer
    AppState --> TaskSys
    AppState --> ScriptEval
    
    GBuffer --> VolRender
    GBuffer --> PostFX
    VolRender --> GLShaders
    PostFX --> GLShaders
    
    TaskSys --> RamaComp
    TaskSys --> ShapeComp
    TaskSys --> VeloxComp
    
    AppState --> ImGuiCore
    ImGuiCore --> CustomWidgets
    ImGuiCore --> TextEditor
    ImGuiCore --> PlotSystem
```

The architecture separates concerns into distinct subsystems that communicate through the central `ApplicationState` and event system. This design enables modular development and clean separation between rendering, analysis, and user interface components.

Sources: [src/main.cpp:661-943](), [src/viamd.h:396-808](), [src/event.cpp]()

## Core Data Structures

The application state is managed through several key data structures that represent the current state of loaded molecular data, user interface, and computational tasks.

### ApplicationState Structure

```mermaid
graph LR
    subgraph "ApplicationState Core Fields"
        App["app: application::Context<br/>Platform & Window Management"]
        Allocator["allocator: frame/persistent<br/>Memory Management"]
        Files["files: molecule/trajectory/workspace<br/>File Path Tracking"]
    end
    
    subgraph "Molecular Data"
        Mold["mold: md_molecule_t & md_trajectory_i<br/>Core Molecular Structures"]
        Representations["representation: md_array(Representation)<br/>Visual Representations"]
        Selection["selection: md_bitfield_t masks<br/>Atom Selection State"]
    end
    
    subgraph "Visualization State"
        View["view: Camera & ViewParam<br/>Camera Controls & Projection"]
        Visuals["visuals: SSAO/DOF/Tonemapping<br/>Rendering Parameters"]
        GBuf["gbuffer: GBuffer<br/>Deferred Rendering Targets"]
    end
    
    subgraph "Analysis & Scripting"
        Script["script: md_script_ir_t & md_script_eval_t<br/>Script Compilation & Evaluation"]
        Timeline["timeline: frame timestamps<br/>Temporal Data Navigation"]
        Tasks["tasks: task_system::ID handles<br/>Async Computation Tracking"]
    end
    
    App --> Mold
    Mold --> Representations
    Representations --> View
    View --> GBuf
    Script --> Tasks
    Timeline --> Script
```

The `ApplicationState` serves as the central data hub, containing all necessary state for molecular visualization, user interactions, and computational analysis.

Sources: [src/viamd.h:396-808]()

### Representation System

```mermaid
graph TB
    subgraph "Representation Types"
        RepType["RepresentationType enum<br/>SpaceFill, Licorice, BallAndStick, Ribbons, Cartoon, ElectronicStructure"]
        ColorMap["ColorMapping enum<br/>Uniform, CPK, AtomLabel, ResName, Property"]
    end
    
    subgraph "Representation Structure"
        RepStruct["Representation struct<br/>src/viamd.h:326"]
        AtomMask["atom_mask: md_bitfield_t<br/>Filtered Atom Selection"]
        GLRep["md_rep: md_gl_rep_t<br/>OpenGL Rendering Data"]
        ElecStruct["electronic_structure: Volume & IsoDesc<br/>Quantum Chemistry Visualization"]
    end
    
    subgraph "Filtering & Selection"
        FilterExpr["filt: char[256]<br/>Selection Expression"]
        FilterEval["Script Filter Evaluation<br/>md_script_eval_t"]
        DynamicEval["dynamic_evaluation: bool<br/>Real-time Filter Updates"]
    end
    
    RepType --> RepStruct
    ColorMap --> RepStruct
    RepStruct --> AtomMask
    RepStruct --> GLRep
    RepStruct --> ElecStruct
    FilterExpr --> FilterEval
    FilterEval --> AtomMask
    DynamicEval --> FilterEval
```

The representation system provides flexible visualization of molecular data through configurable rendering types, color mappings, and dynamic filtering capabilities.

Sources: [src/viamd.h:326-394](), [src/viamd.h:57-103]()

## Event-Driven Communication

VIAMD uses an event system to coordinate between components, enabling loose coupling and modular design.

```mermaid
graph LR
    subgraph "Event Types"
        InitEvent["ViamdInitialize<br/>Component Setup"]
        TickEvent["ViamdFrameTick<br/>Per-Frame Updates"]
        TopoEvent["ViamdTopologyInit<br/>Molecular Data Loaded"]
        RepEvent["RepresentationInfoFill<br/>Available Representations"]
        EvalEvent["RepresentationEvalElectronicStructure<br/>Volume Computation"]
    end
    
    subgraph "Event Handlers"
        VeloxHandler["VeloxChem::process_events<br/>src/components/veloxchem/veloxchem.cpp:503"]
        RamaHandler["Ramachandran Handler<br/>src/components/ramachandran/"]
        ShapeHandler["Shape Space Handler<br/>src/components/shapespace/"]
        MainHandler["Main Application Handler<br/>src/main.cpp"]
    end
    
    subgraph "Event Broadcasting"
        EventBroadcast["viamd::event_system_broadcast_event<br/>src/event.cpp"]
        EventRegistration["viamd::event_system_register_handler<br/>Component Registration"]
    end
    
    InitEvent --> EventBroadcast
    TickEvent --> EventBroadcast
    TopoEvent --> EventBroadcast
    
    EventBroadcast --> VeloxHandler
    EventBroadcast --> RamaHandler
    EventBroadcast --> ShapeHandler
    EventBroadcast --> MainHandler
    
    VeloxHandler --> EventRegistration
    RamaHandler --> EventRegistration
    ShapeHandler --> EventRegistration
```

Components register as event handlers and receive relevant events through the centralized broadcasting system, enabling coordinated responses to application state changes.

Sources: [src/components/veloxchem/veloxchem.cpp:503-561](), [src/main.cpp:778](), [src/main.cpp:913]()

## Key Subsystem Integration Points

### Task System Integration

```mermaid
graph TB
    subgraph "Task System"
        TaskInit["task_system::initialize<br/>src/main.cpp:772"]
        TaskPool["Worker Thread Pool<br/>VIAMD_NUM_WORKER_THREADS"]
        TaskIDs["task_system::ID handles<br/>Async Operation Tracking"]
    end
    
    subgraph "Computational Tasks"
        BackboneTask["backbone_computations<br/>Secondary Structure Analysis"]
        PrefetchTask["prefetch_frames<br/>Trajectory Frame Loading"]
        EvalTask["evaluate_full/evaluate_filt<br/>Script Evaluation"]
        VeloxTask["VeloxChem Volume Tasks<br/>Orbital/Density Computation"]
    end
    
    subgraph "Integration"
        AppState["ApplicationState.tasks<br/>Task Handle Storage"]
        TaskInterrupt["interrupt_async_tasks<br/>Task Cancellation"]
        TaskComplete["Task Completion Callbacks<br/>Result Integration"]
    end
    
    TaskInit --> TaskPool
    TaskPool --> BackboneTask
    TaskPool --> PrefetchTask
    TaskPool --> EvalTask
    TaskPool --> VeloxTask
    
    BackboneTask --> TaskIDs
    PrefetchTask --> TaskIDs
    EvalTask --> TaskIDs
    VeloxTask --> TaskIDs
    
    TaskIDs --> AppState
    AppState --> TaskInterrupt
    TaskIDs --> TaskComplete
```

The task system enables parallel execution of computationally intensive operations while maintaining responsive user interaction through proper task lifecycle management.

Sources: [src/main.cpp:770-772](), [src/viamd.h:472-478](), [src/task_system.cpp]()

### Graphics Pipeline Integration

```mermaid
graph TB
    subgraph "Rendering Pipeline"
        GBufferInit["init_gbuffer<br/>src/main.cpp:756"]
        FillGBuffer["fill_gbuffer<br/>Geometry Rendering"]
        PostProcess["apply_postprocessing<br/>SSAO, DOF, Temporal AA"]
        Present["Final Image Presentation"]
    end
    
    subgraph "Volume Rendering"
        VolInit["volume::initialize<br/>src/main.cpp:769"]
        VolTexture["Volume Texture Management<br/>OpenGL 3D Textures"]
        IsoSurface["Isosurface Extraction<br/>Marching Cubes"]
        DVR["Direct Volume Rendering<br/>Ray Casting"]
    end
    
    subgraph "Shader System"
        ShaderSnippet["shader_output_snippet<br/>src/main.cpp:119-155"]
        GLShaders["md_gl_shaders_create<br/>src/main.cpp:775-776"]
        ShaderRecomp["Shader Recompilation<br/>F5 Key Handler"]
    end
    
    GBufferInit --> FillGBuffer
    FillGBuffer --> PostProcess
    PostProcess --> Present
    
    VolInit --> VolTexture
    VolTexture --> IsoSurface
    VolTexture --> DVR
    
    ShaderSnippet --> GLShaders
    GLShaders --> FillGBuffer
    GLShaders --> IsoSurface
    GLShaders --> DVR
    
    ShaderRecomp --> GLShaders
```

The graphics pipeline provides both traditional molecular rendering and advanced volume visualization capabilities through a unified shader system and deferred rendering approach.

Sources: [src/main.cpp:756](), [src/main.cpp:769](), [src/main.cpp:775-776](), [src/main.cpp:119-155]()

This overview establishes the foundation for understanding VIAMD's architecture. For detailed exploration of specific subsystems, refer to the dedicated sections on [Core Application Architecture](#2), [Graphics and Visualization Pipeline](#3), [Analysis and Computation](#4), [User Interface Framework](#5), and [Build System and Dependencies](#6).

---