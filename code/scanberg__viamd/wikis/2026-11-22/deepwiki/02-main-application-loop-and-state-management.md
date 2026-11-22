# Main Application Loop and State Management

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/components/veloxchem/veloxchem.cpp](src/components/veloxchem/veloxchem.cpp)
- [src/main.cpp](src/main.cpp)
- [src/viamd.h](src/viamd.h)

</details>



This document covers the core application loop, the central `ApplicationState` structure, and state management patterns in VIAMD. It explains how the application coordinates between different subsystems and manages the lifecycle of molecular data, UI state, and rendering resources.

For information about the event system architecture and inter-component communication, see [Event System](#2.3). For details about molecular data structures and display components, see [Molecular Data Structures and Display](#2.4).

## ApplicationState Structure

The `ApplicationState` structure serves as the central hub for all application state, containing subsystem data, UI state, and molecular information. This structure is passed throughout the application to provide unified access to all components.

### Core State Components

```mermaid
graph TB
    subgraph AS["ApplicationState"]
        subgraph CORE["Core Systems"]
            APP["app: application::Context"]
            ALLOC["allocator: frame/persistent"]
            FILES["files: molecule/trajectory/workspace paths"]
        end
        
        subgraph MOLECULAR["Molecular Data"]
            MOLD["mold: md_molecule_t, md_trajectory_i"]
            REP["representation: md_array(Representation)"]
            SEL["selection: selection_mask, highlight_mask"]
        end
        
        subgraph RENDERING["Rendering State"]
            VIEW["view: Camera, ViewParam, jitter"]
            GBUF["gbuffer: GBuffer"]
            PICK["picking: PickingData"]
            VIS["visuals: background, ssao, tonemapping"]
        end
        
        subgraph ANIMATION["Animation & Timeline"]
            ANIM["animation: frame, fps, interpolation"]
            TIME["timeline: x_values, filter"]
            TASKS["tasks: async task handles"]
        end
        
        subgraph SCRIPTING["Script System"]
            SCRIPT["script: ir, eval, vis"]
            PROPS["display_properties: DisplayProperty*"]
        end
        
        subgraph UI["UI State"]
            LOAD["load_dataset: LoadDatasetWindowState"]
            DIST["distributions: show_window, filter"]
            DVOL["density_volume: Volume, Camera, IsoDesc"]
        end
    end
    
    APP --> ALLOC
    MOLD --> REP
    REP --> SEL
    VIEW --> GBUF
    GBUF --> PICK
    ANIM --> TIME
    SCRIPT --> PROPS
```

**ApplicationState Component Breakdown**
Sources: [src/viamd.h:396-808]()

### Memory Management Architecture

```mermaid
graph LR
    subgraph ALLOC["Allocator Hierarchy"]
        HEAP["md_get_heap_allocator()"]
        PERSISTENT["persistent_alloc"]
        FRAME["frame_alloc (arena)"]
        ARENA["component arenas"]
    end
    
    subgraph LIFETIME["Memory Lifetimes"]
        APP_LIFE["Application Lifetime"]
        FRAME_LIFE["Frame Lifetime"]
        COMPONENT_LIFE["Component Lifetime"]
    end
    
    HEAP --> PERSISTENT
    PERSISTENT --> FRAME
    PERSISTENT --> ARENA
    
    PERSISTENT --> APP_LIFE
    FRAME --> FRAME_LIFE
    ARENA --> COMPONENT_LIFE
```

**Memory Management Strategy**
Sources: [src/main.cpp:662-669](), [src/main.cpp:93-94]()

## Main Application Loop

The main application loop coordinates initialization, event processing, state updates, and rendering. The loop structure follows a clear pattern of input processing, state updates, and output generation.

### Application Lifecycle

```mermaid
flowchart TD
    START[["main(argc, argv)"]] --> INIT_ALLOC["Initialize Allocators"]
    INIT_ALLOC --> INIT_APP["application::initialize()"]
    INIT_APP --> INIT_GFX["Initialize Graphics Subsystems"]
    INIT_GFX --> INIT_EVENTS["Broadcast ViamdInitialize Event"]
    INIT_EVENTS --> SETUP_UI["Setup ImGui and Editor"]
    SETUP_UI --> LOAD_ARGS["Process Command Line Files"]
    LOAD_ARGS --> MAIN_LOOP["Main Loop"]
    
    MAIN_LOOP --> CHECK_EXIT{"app.window.should_close?"}
    CHECK_EXIT -->|No| UPDATE_APP["application::update()"]
    UPDATE_APP --> DOCKSPACE["ImGui::CreateDockspace()"]
    DOCKSPACE --> PROCESS_FILES["Process file_queue"]
    PROCESS_FILES --> BROADCAST_TICK["Broadcast ViamdFrameTick"]
    BROADCAST_TICK --> DRAW_UI["Draw UI Windows"]
    DRAW_UI --> HANDLE_INPUT["Handle Keyboard/Camera Input"]
    HANDLE_INPUT --> UPDATE_ANIM["Update Animation State"]
    UPDATE_ANIM --> SCRIPT_COMPILE["Script Compilation & Evaluation"]
    SCRIPT_COMPILE --> UPDATE_REP["Update Representations"]
    UPDATE_REP --> RENDER["Rendering Pipeline"]
    RENDER --> MAIN_LOOP
    
    CHECK_EXIT -->|Yes| SHUTDOWN["Cleanup & Exit"]
```

**Main Application Loop Flow**
Sources: [src/main.cpp:830-1431]()

### File Processing System

The application uses a priority-based file queue to handle file loading operations. Files are processed based on their type and priority to ensure proper loading order.

```mermaid
graph TB
    subgraph QUEUE["FileQueue System"]
        FILEDROP["File Drop/Command Line"] --> QUEUE_PUSH["file_queue_push()"]
        QUEUE_PUSH --> PRIORITY["Priority Assignment"]
        PRIORITY --> QUEUE_STORE["Queue Storage (ring buffer)"]
    end
    
    subgraph PROCESS["File Processing"]
        QUEUE_EMPTY{"file_queue_empty()?"}
        QUEUE_POP["file_queue_pop()"]
        EXT_CHECK["extract_ext()"]
        WORKSPACE_CHECK{"Workspace file?"}
        SCRIPT_CHECK{"Script import?"}
        LOADER_CHECK{"Has loader?"}
        SHOW_DIALOG["Show Load Dialog"]
        LOAD_FILE["load_dataset_from_file()"]
    end
    
    QUEUE_STORE --> QUEUE_EMPTY
    QUEUE_EMPTY -->|No| QUEUE_POP
    QUEUE_POP --> EXT_CHECK
    EXT_CHECK --> WORKSPACE_CHECK
    WORKSPACE_CHECK -->|Yes| LOAD_WORKSPACE["load_workspace()"]
    WORKSPACE_CHECK -->|No| SCRIPT_CHECK
    SCRIPT_CHECK -->|Yes| SCRIPT_IMPORT["Import to Editor"]
    SCRIPT_CHECK -->|No| LOADER_CHECK
    LOADER_CHECK -->|Yes| LOAD_FILE
    LOADER_CHECK -->|No| SHOW_DIALOG
    SHOW_DIALOG --> LOAD_FILE
```

**File Processing Priority System**
Sources: [src/main.cpp:326-378](), [src/main.cpp:842-911]()

## Event System Integration

The main loop integrates with the event system to coordinate between different components. Key events are broadcast at specific points in the application lifecycle.

### Event Broadcasting Points

```mermaid
sequenceDiagram
    participant ML as "Main Loop"
    participant ES as "Event System"
    participant COMP as "Components"
    
    Note over ML,COMP: Application Startup
    ML->>ES: ViamdInitialize
    ES->>COMP: Initialize component state
    
    Note over ML,COMP: Each Frame
    ML->>ES: ViamdFrameTick
    ES->>COMP: Update component state
    
    Note over ML,COMP: File Loading
    ML->>ES: ViamdTopologyInit
    ES->>COMP: Process new molecular data
    
    Note over ML,COMP: Menu Drawing
    ML->>ES: ViamdWindowDrawMenu
    ES->>COMP: Render component UI
    
    Note over ML,COMP: State Changes
    ML->>ES: ViamdHoverMaskChanged
    ML->>ES: ViamdSelectionMaskChanged
    ES->>COMP: Update selection visualization
```

**Event System Integration Points**
Sources: [src/main.cpp:778](), [src/main.cpp:913](), [src/components/veloxchem/veloxchem.cpp:508-547]()

## State Update Patterns

The application follows consistent patterns for state updates, ensuring proper coordination between subsystems and maintaining data consistency.

### Animation and Timeline Management

```mermaid
stateDiagram-v2
    [*] --> Stopped
    Stopped --> Playing: KEY_PLAY_PAUSE
    Playing --> Stopped: KEY_PLAY_PAUSE / End of frames
    Playing --> Playing: Update frame position
    
    state Playing {
        [*] --> UpdateFrame
        UpdateFrame --> InterpolateProps: "interpolate_atomic_properties()"
        InterpolateProps --> UpdateReps: "update_representation()"
        UpdateReps --> PrefetchFrames: "task_system prefetch"
        PrefetchFrames --> [*]
    }
    
    state Stopped {
        [*] --> ClearVelocity
        ClearVelocity --> [*]: "MolBit_ClearVelocity"
    }
```

**Animation State Management**
Sources: [src/main.cpp:970-1045](), [src/main.cpp:1079-1102]()

### Script Compilation and Evaluation

The script system manages compilation and evaluation of user scripts with careful synchronization to prevent conflicts.

```mermaid
graph TD
    TEXT_CHANGE["Text Changed"] --> COMPILE_DELAY["Compilation Delay Timer"]
    COMPILE_DELAY --> ACQUIRE_SEM["Try Acquire IR Semaphores"]
    ACQUIRE_SEM -->|Success| COMPILE_IR["md_script_ir_compile_from_source()"]
    ACQUIRE_SEM -->|Fail| RETRY["Retry Next Frame"]
    COMPILE_IR --> VALID_CHECK{"IR Valid?"}
    VALID_CHECK -->|Yes| UPDATE_MARKERS["Update Editor Markers"]
    VALID_CHECK -->|No| FREE_IR["md_script_ir_free()"]
    UPDATE_MARKERS --> RELEASE_SEM["Release Semaphores"]
    
    EVAL_INIT["eval_init trigger"] --> CREATE_EVAL["Create Script Evaluators"]
    CREATE_EVAL --> FULL_EVAL["Launch Full Evaluation Task"]
    CREATE_EVAL --> FILT_EVAL["Launch Filtered Evaluation Task"]
    
    FULL_EVAL --> ASYNC_TASK["task_system::create_pool_task()"]
    FILT_EVAL --> ASYNC_TASK_FILT["task_system::create_pool_task()"]
```

**Script System State Management**
Sources: [src/main.cpp:1110-1338]()

## Rendering Integration

The main loop coordinates with the rendering pipeline to ensure proper frame generation and resource management.

### Rendering State Updates

| Update Type | Trigger | Function | Sources |
|-------------|---------|----------|---------|
| View Parameters | Camera changes | `update_view_param()` | [src/main.cpp:1396]() |
| MD Buffers | Molecular data changes | `update_md_buffers()` | [src/main.cpp:1430]() |
| Representations | Filter/color changes | `update_representation()` | [src/main.cpp:1088-1095]() |
| G-Buffer | Framebuffer resize | `init_gbuffer()` | [src/main.cpp:1390-1394]() |

### Hash-Based Change Detection

The application uses hash-based change detection to minimize expensive GPU operations:

```mermaid
graph LR
    subgraph HASH["Hash Computation"]
        VIS_HASH["visibility_mask_hash"]
        HIGH_HASH["highlight_mask hash"]
        SEL_HASH["selection_mask hash"]
        FLAG_HASH["combined flag hash"]
    end
    
    subgraph CHECK["Change Detection"]
        STATIC_HASH["Static hash storage"]
        COMPARE["Hash comparison"]
        UPDATE_FLAG["Set dirty flags"]
    end
    
    VIS_HASH --> FLAG_HASH
    HIGH_HASH --> FLAG_HASH
    SEL_HASH --> FLAG_HASH
    FLAG_HASH --> COMPARE
    STATIC_HASH --> COMPARE
    COMPARE --> UPDATE_FLAG
    UPDATE_FLAG --> GPU_UPLOAD["GPU buffer upload"]
```

**Hash-Based Change Detection System**
Sources: [src/main.cpp:1403-1428]()

Sources: [src/main.cpp:661-1431](), [src/viamd.h:396-808](), [src/components/veloxchem/veloxchem.cpp:503-790]()

---