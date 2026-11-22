# Shape Space Analysis

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/components/ramachandran/ramachandran.cpp](src/components/ramachandran/ramachandran.cpp)
- [src/components/shapespace/shapespace.cpp](src/components/shapespace/shapespace.cpp)
- [src/event.h](src/event.h)
- [src/task_system.cpp](src/task_system.cpp)
- [src/task_system.h](src/task_system.h)

</details>



## Purpose and Scope

The Shape Space Analysis component provides real-time computation and visualization of molecular shape descriptors for trajectory analysis. It computes principal moments of inertia for selected atoms across trajectory frames and plots the resulting shape weights in a triangular coordinate system that represents the spectrum from linear to planar to spherical molecular conformations.

For general analysis and computation framework information, see [Analysis and Computation](#4). For parallel processing details used by this component, see [Task System and Parallel Processing](#4.1).

## Overview

The Shape Space Analysis system analyzes molecular shapes by computing three normalized shape weights (linear, planar, and isotropic) based on the eigenvalues of the covariance matrix of atomic coordinates. These weights are visualized in a triangular plot where the vertices represent idealized linear, planar, and spherical shapes.

```mermaid
graph TB
    subgraph "Shape Space Analysis Workflow"
        INPUT[User Filter Expression] --> PARSE[md_filter_evaluate]
        PARSE --> BITFIELDS[Atom Selection Bitfields]
        BITFIELDS --> TASK[Parallel Frame Processing]
        TASK --> COM[Center of Mass Computation]
        COM --> COV[Covariance Matrix Calculation]
        COV --> EIGEN[Principal Moments Analysis]
        EIGEN --> WEIGHTS[Shape Weight Computation]
        WEIGHTS --> COORDS[Triangular Coordinates]
        COORDS --> PLOT[ImPlot Visualization]
    end
    
    subgraph "Core Components"
        SHAPESPACE[Shapespace Event Handler]
        ARENA[Arena Allocator]
        TASK_SYS[Task System]
        EXPORT[Export System]
    end
    
    SHAPESPACE --> ARENA
    SHAPESPACE --> TASK_SYS
    SHAPESPACE --> EXPORT
    TASK --> TASK_SYS
    PLOT --> SHAPESPACE
```

**Shape Space Triangle Coordinate System**
```mermaid
graph TB
    subgraph "Triangular Shape Space"
        LINEAR["Linear (0,0)"]
        PLANAR["Planar (1,0)"] 
        SPHERICAL["Spherical (0.5, 0.866)"]
        
        LINEAR -.-> PLANAR
        PLANAR -.-> SPHERICAL  
        SPHERICAL -.-> LINEAR
    end
    
    subgraph "Shape Weight Computation"
        LAMBDA1[λ₁ ≥ λ₂ ≥ λ₃] --> NORM[Normalize Eigenvalues]
        NORM --> W1[w_linear = λ₁ - λ₂]
        NORM --> W2[w_planar = λ₂ - λ₃] 
        NORM --> W3[w_spherical = λ₃]
        W1 --> COORDS[Barycentric Coordinates]
        W2 --> COORDS
        W3 --> COORDS
    end
```

Sources: [src/components/shapespace/shapespace.cpp:1-503]()

## Core Architecture

### Main Component Structure

The `Shapespace` struct serves as the primary component, inheriting from `viamd::EventHandler` to integrate with the event system:

```mermaid
classDiagram
    class Shapespace {
        +char input[256]
        +char error[256]
        +bool input_valid
        +bool show_window
        +uint64_t eval_hash
        +size_t num_frames
        +size_t num_structures
        +md_array(vec3_t) weights
        +md_array(vec2_t) coords
        +md_array(md_bitfield_t) bitfields
        +md_bitfield_t joined_bitfield
        +md_allocator_i* arena
        +float marker_size
        +bool use_mass
        +ColorMode mode
        +task_system::ID evaluate_task
        +ApplicationState* app_state
        +process_events()
        +draw_window()
        +export_shape_space()
    }
    
    class EventHandler {
        <<interface>>
        +process_events()
    }
    
    Shapespace --|> EventHandler
```

The component maintains arrays for shape weights (`vec3_t`), 2D plot coordinates (`vec2_t`), and atom selection bitfields for each analyzed structure.

Sources: [src/components/shapespace/shapespace.cpp:42-74]()

### Event System Integration

The component responds to key application events through the event system:

| Event Type | Handler Function | Purpose |
|------------|------------------|---------|
| `ViamdInitialize` | Initialize arena allocator | Setup memory management |
| `ViamdShutdown` | Cleanup and task interruption | Resource cleanup |
| `ViamdFrameTick` | `draw_window()` | Update UI and trigger evaluation |
| `ViamdWindowDrawMenu` | Menu checkbox | Window visibility control |
| `ViamdSerialize/Deserialize` | State persistence | Save/load configuration |

```mermaid
sequenceDiagram
    participant App as Application
    participant Event as Event System
    participant Shape as Shapespace
    participant Task as Task System
    
    App->>Event: ViamdInitialize
    Event->>Shape: process_events()
    Shape->>Shape: Initialize arena allocator
    
    App->>Event: ViamdFrameTick
    Event->>Shape: process_events()
    Shape->>Shape: draw_window()
    Shape->>Shape: Check eval_hash
    
    alt Hash changed
        Shape->>Task: create_pool_task()
        Shape->>Task: enqueue_task()
    end
    
    App->>Event: ViamdShutdown
    Event->>Shape: process_events()
    Shape->>Task: task_interrupt_and_wait_for()
```

Sources: [src/components/shapespace/shapespace.cpp:76-127]()

## Shape Computation Algorithm

### Parallel Frame Processing

The core computation is parallelized across trajectory frames using the task system:

```mermaid
graph LR
    subgraph "Frame Processing Pipeline"
        FRAME[Frame Data] --> COORDS[Extract Coordinates]
        COORDS --> FILTER[Apply Atom Filter]
        FILTER --> COM[Compute Center of Mass]
        COM --> DEPERIODIZE[Deperiodize Coordinates]
        DEPERIODIZE --> COV[Covariance Matrix]
        COV --> EIGEN[Principal Moments]
        EIGEN --> NORMALIZE[Shape Weights]
        NORMALIZE --> BARY[Barycentric Coords]
    end
    
    subgraph "Parallel Execution"
        TASK1[Thread 1: Frames 0-N/4]
        TASK2[Thread 2: Frames N/4-N/2]
        TASK3[Thread 3: Frames N/2-3N/4]
        TASK4[Thread 4: Frames 3N/4-N]
    end
```

The computation occurs in the lambda function passed to `task_system::create_pool_task()`:

- Allocates thread-local coordinate arrays
- Iterates through assigned frame range
- Loads frame coordinates using `md_trajectory_load_frame()`
- Processes each structure's atom selection
- Computes center of mass with `md_util_com_compute_vec4()`
- Calculates covariance matrix with `mat3_covariance_matrix_vec4()`
- Derives shape weights using `md_util_shape_weights()`

Sources: [src/components/shapespace/shapespace.cpp:382-426]()

### Mathematical Foundation

The shape analysis is based on the eigenvalue decomposition of the covariance matrix:

1. **Covariance Matrix**: Computed from deperiodized atomic coordinates
2. **Eigenvalues**: Ordered as λ₁ ≥ λ₂ ≥ λ₃  
3. **Shape Weights**: 
   - Linear: λ₁ - λ₂ (elongation along primary axis)
   - Planar: λ₂ - λ₃ (flattening in secondary plane) 
   - Spherical: λ₃ (isotropic distribution)
4. **Normalization**: Weights sum to 1.0
5. **Triangular Coordinates**: Barycentric mapping to triangle vertices

The triangular coordinate system maps shape weights to visualization coordinates:
```
p[0] = {0.0f, 0.0f}         // Linear vertex
p[1] = {1.0f, 0.0f}         // Planar vertex  
p[2] = {0.5f, 0.86602540378f} // Spherical vertex (equilateral triangle)
```

Sources: [src/components/shapespace/shapespace.cpp:394-422]()

## Visualization System

### ImPlot Integration

The component uses ImPlot for interactive 2D visualization:

```mermaid
graph TB
    subgraph "Plot Rendering"
        SETUP[Plot Setup] --> TRIANGLE[Draw Shape Triangle]
        TRIANGLE --> POINTS[Draw Data Points]
        POINTS --> HOVER[Handle Hover Events]
        HOVER --> TOOLTIP[Show Tooltips]
        TOOLTIP --> SELECTION[Handle Selection]
    end
    
    subgraph "Interactive Features"
        CLICK[Mouse Click] --> FRAME[Set Animation Frame]
        HOVER_POINT[Point Hover] --> HIGHLIGHT[Highlight Atoms]
        HOVER_LEGEND[Legend Hover] --> STRUCTURE[Highlight Structure]
    end
```

Key visualization features:
- **Triangle Background**: Semi-transparent filled triangle with vertex labels
- **Data Points**: Scatter plot with configurable marker size
- **Interactive Hover**: Shows frame index and shape weights in tooltip
- **Frame Navigation**: Click to jump to specific trajectory frame
- **Structure Highlighting**: Hover effects update atom selection masks

Sources: [src/components/shapespace/shapespace.cpp:187-340]()

### Data Export

The system supports exporting computed shape data to standard formats:

| Format | Function | Contents |
|--------|----------|----------|
| CSV | `md_csv_write_to_file()` | Tabular data with headers |
| XVG | `md_xvg_format()` | GROMACS-style plot data |

Export columns include:
- Time/Frame index
- Linear, planar, and spherical weights for each structure

Sources: [src/components/shapespace/shapespace.cpp:433-499]()

## Memory Management

The component uses arena allocation for efficient memory management:

```mermaid
graph LR
    subgraph "Memory Layout"
        ARENA[Arena Allocator] --> BITFIELDS[Structure Bitfields]
        ARENA --> WEIGHTS[Shape Weights Array]
        ARENA --> COORDS[Plot Coordinates Array]
        ARENA --> JOINED[Joined Bitfield]
    end
    
    subgraph "Lifecycle"
        INIT[Initialize] --> ALLOCATE[Allocate Arrays]
        ALLOCATE --> RESET[Reset on Re-evaluation]
        RESET --> DEALLOCATE[Cleanup on Shutdown]
    end
```

Memory allocation strategy:
- **Arena Size**: 1 MB allocated from persistent allocator
- **Array Sizing**: `num_frames * num_structures` elements
- **Reset Strategy**: Arena reset on filter expression changes
- **Thread Safety**: Separate heap allocations for worker threads

Sources: [src/components/shapespace/shapespace.cpp:82-84](), [src/components/shapespace/shapespace.cpp:354-356](), [src/components/shapespace/shapespace.cpp:387-388]()

## Integration Points

### Filter System Integration

The component integrates with the molecular filter system to define atom selections:

```mermaid
graph LR
    subgraph "Filter Processing"
        INPUT[User Filter Expression] --> PARSE[md_filter_evaluate]
        PARSE --> VALIDATE[Input Validation]
        VALIDATE --> BITFIELDS[Generate Bitfields]
        BITFIELDS --> JOIN[Create Joined Bitfield]
    end
    
    subgraph "Error Handling"
        ERROR[Parse Error] --> DISPLAY[Show Error Tooltip]
        VALID[Valid Input] --> HIGHLIGHT[Update Highlight Mask]
    end
```

Filter evaluation produces bitfields for each structure that define which atoms participate in the shape analysis.

Sources: [src/components/shapespace/shapespace.cpp:360-376]()

### Task System Integration

The component leverages the task system for parallel computation across trajectory frames:

- **Task Creation**: `task_system::create_pool_task()` with frame-based parallelization
- **Task Management**: Interrupt running tasks on parameter changes
- **Thread Safety**: Each worker thread allocates separate coordinate arrays
- **Synchronization**: Task completion updates UI state

Sources: [src/components/shapespace/shapespace.cpp:346-348](), [src/components/shapespace/shapespace.cpp:382-427]()

# Shape Space Analysis

## Purpose and Scope

The Shape Space Analysis component provides real-time computation and visualization of molecular shape descriptors for trajectory analysis. It computes principal moments of inertia for selected atoms across trajectory frames and plots the resulting shape weights in a triangular coordinate system that represents the spectrum from linear to planar to spherical molecular conformations.

For general analysis and computation framework information, see [Analysis and Computation](#4). For parallel processing details used by this component, see [Task System and Parallel Processing](#4.1).

## Overview

The Shape Space Analysis system analyzes molecular shapes by computing three normalized shape weights (linear, planar, and isotropic) based on the eigenvalues of the covariance matrix of atomic coordinates. These weights are visualized in a triangular plot where the vertices represent idealized linear, planar, and spherical shapes.

**Shape Space Analysis Workflow**
```mermaid
graph TB
    subgraph "Shape Space Analysis Workflow"
        INPUT["User Filter Expression"] --> PARSE["md_filter_evaluate"]
        PARSE --> BITFIELDS["Atom Selection Bitfields"]
        BITFIELDS --> TASK["Parallel Frame Processing"]
        TASK --> COM["Center of Mass Computation"]
        COM --> COV["Covariance Matrix Calculation"]
        COV --> EIGEN["Principal Moments Analysis"]
        EIGEN --> WEIGHTS["Shape Weight Computation"]
        WEIGHTS --> COORDS["Triangular Coordinates"]
        COORDS --> PLOT["ImPlot Visualization"]
    end
    
    subgraph "Core Components"
        SHAPESPACE["Shapespace Event Handler"]
        ARENA["Arena Allocator"]
        TASK_SYS["Task System"]
        EXPORT["Export System"]
    end
    
    SHAPESPACE --> ARENA
    SHAPESPACE --> TASK_SYS
    SHAPESPACE --> EXPORT
    TASK --> TASK_SYS
    PLOT --> SHAPESPACE
```

**Shape Space Triangle Coordinate System**
```mermaid
graph TB
    subgraph "Triangular Shape Space"
        LINEAR["Linear (0,0)"]
        PLANAR["Planar (1,0)"] 
        SPHERICAL["Spherical (0.5, 0.866)"]
        
        LINEAR -.-> PLANAR
        PLANAR -.-> SPHERICAL  
        SPHERICAL -.-> LINEAR
    end
    
    subgraph "Shape Weight Computation"
        LAMBDA1["λ₁ ≥ λ₂ ≥ λ₃"] --> NORM["Normalize Eigenvalues"]
        NORM --> W1["w_linear = λ₁ - λ₂"]
        NORM --> W2["w_planar = λ₂ - λ₃"] 
        NORM --> W3["w_spherical = λ₃"]
        W1 --> COORDS["Barycentric Coordinates"]
        W2 --> COORDS
        W3 --> COORDS
    end
```

Sources: [src/components/shapespace/shapespace.cpp:1-503]()

## Core Architecture

### Main Component Structure

The `Shapespace` struct serves as the primary component, inheriting from `viamd::EventHandler` to integrate with the event system:

**Shapespace Component Architecture**
```mermaid
classDiagram
    class Shapespace {
        +char input[256]
        +char error[256]
        +bool input_valid
        +bool show_window
        +uint64_t eval_hash
        +size_t num_frames
        +size_t num_structures
        +md_array_vec3_t weights
        +md_array_vec2_t coords
        +md_array_md_bitfield_t bitfields
        +md_bitfield_t joined_bitfield
        +md_allocator_i arena
        +float marker_size
        +bool use_mass
        +ColorMode mode
        +task_system_ID evaluate_task
        +ApplicationState app_state
        +process_events()
        +draw_window()
        +export_shape_space()
    }
    
    class EventHandler {
        <<interface>>
        +process_events()
    }
    
    Shapespace --|> EventHandler
```

The component maintains arrays for shape weights (`vec3_t`), 2D plot coordinates (`vec2_t`), and atom selection bitfields for each analyzed structure.

Sources: [src/components/shapespace/shapespace.cpp:42-74]()

### Event System Integration

The component responds to key application events through the event system:

| Event Type | Handler Function | Purpose |
|------------|------------------|---------|
| `ViamdInitialize` | Initialize arena allocator | Setup memory management |
| `ViamdShutdown` | Cleanup and task interruption | Resource cleanup |
| `ViamdFrameTick` | `draw_window()` | Update UI and trigger evaluation |
| `ViamdWindowDrawMenu` | Menu checkbox | Window visibility control |
| `ViamdSerialize/Deserialize` | State persistence | Save/load configuration |

**Event Processing Sequence**
```mermaid
sequenceDiagram
    participant App as "Application"
    participant Event as "Event System"
    participant Shape as "Shapespace"
    participant Task as "Task System"
    
    App->>Event: ViamdInitialize
    Event->>Shape: process_events()
    Shape->>Shape: Initialize arena allocator
    
    App->>Event: ViamdFrameTick
    Event->>Shape: process_events()
    Shape->>Shape: draw_window()
    Shape->>Shape: Check eval_hash
    
    alt Hash changed
        Shape->>Task: create_pool_task()
        Shape->>Task: enqueue_task()
    end
    
    App->>Event: ViamdShutdown
    Event->>Shape: process_events()
    Shape->>Task: task_interrupt_and_wait_for()
```

Sources: [src/components/shapespace/shapespace.cpp:76-127]()

## Shape Computation Algorithm

### Parallel Frame Processing

The core computation is parallelized across trajectory frames using the task system:

**Frame Processing Pipeline**
```mermaid
graph LR
    subgraph "Frame Processing Pipeline"
        FRAME["Frame Data"] --> COORDS["Extract Coordinates"]
        COORDS --> FILTER["Apply Atom Filter"]
        FILTER --> COM["Compute Center of Mass"]
        COM --> DEPERIODIZE["Deperiodize Coordinates"]
        DEPERIODIZE --> COV["Covariance Matrix"]
        COV --> EIGEN["Principal Moments"]
        EIGEN --> NORMALIZE["Shape Weights"]
        NORMALIZE --> BARY["Barycentric Coords"]
    end
    
    subgraph "Parallel Execution"
        TASK1["Thread 1: Frames 0-N/4"]
        TASK2["Thread 2: Frames N/4-N/2"]
        TASK3["Thread 3: Frames N/2-3N/4"]
        TASK4["Thread 4: Frames 3N/4-N"]
    end
```

The computation occurs in the lambda function passed to `task_system::create_pool_task()`:

- Allocates thread-local coordinate arrays
- Iterates through assigned frame range
- Loads frame coordinates using `md_trajectory_load_frame()`
- Processes each structure's atom selection
- Computes center of mass with `md_util_com_compute_vec4()`
- Calculates covariance matrix with `mat3_covariance_matrix_vec4()`
- Derives shape weights using `md_util_shape_weights()`

Sources: [src/components/shapespace/shapespace.cpp:382-426]()

### Mathematical Foundation

The shape analysis is based on the eigenvalue decomposition of the covariance matrix:

1. **Covariance Matrix**: Computed from deperiodized atomic coordinates
2. **Eigenvalues**: Ordered as λ₁ ≥ λ₂ ≥ λ₃  
3. **Shape Weights**: 
   - Linear: λ₁ - λ₂ (elongation along primary axis)
   - Planar: λ₂ - λ₃ (flattening in secondary plane) 
   - Spherical: λ₃ (isotropic distribution)
4. **Normalization**: Weights sum to 1.0
5. **Triangular Coordinates**: Barycentric mapping to triangle vertices

The triangular coordinate system maps shape weights to visualization coordinates:
```
p[0] = {0.0f, 0.0f}         // Linear vertex
p[1] = {1.0f, 0.0f}         // Planar vertex  
p[2] = {0.5f, 0.86602540378f} // Spherical vertex (equilateral triangle)
```

Sources: [src/components/shapespace/shapespace.cpp:394-422]()

## Visualization System

### ImPlot Integration

The component uses ImPlot for interactive 2D visualization:

**Visualization Rendering Pipeline**
```mermaid
graph TB
    subgraph "Plot Rendering"
        SETUP["Plot Setup"] --> TRIANGLE["Draw Shape Triangle"]
        TRIANGLE --> POINTS["Draw Data Points"]
        POINTS --> HOVER["Handle Hover Events"]
        HOVER --> TOOLTIP["Show Tooltips"]
        TOOLTIP --> SELECTION["Handle Selection"]
    end
    
    subgraph "Interactive Features"
        CLICK["Mouse Click"] --> FRAME["Set Animation Frame"]
        HOVER_POINT["Point Hover"] --> HIGHLIGHT["Highlight Atoms"]
        HOVER_LEGEND["Legend Hover"] --> STRUCTURE["Highlight Structure"]
    end
```

Key visualization features:
- **Triangle Background**: Semi-transparent filled triangle with vertex labels
- **Data Points**: Scatter plot with configurable marker size
- **Interactive Hover**: Shows frame index and shape weights in tooltip
- **Frame Navigation**: Click to jump to specific trajectory frame
- **Structure Highlighting**: Hover effects update atom selection masks

Sources: [src/components/shapespace/shapespace.cpp:187-340]()

### Data Export

The system supports exporting computed shape data to standard formats:

| Format | Function | Contents |
|--------|----------|----------|
| CSV | `md_csv_write_to_file()` | Tabular data with headers |
| XVG | `md_xvg_format()` | GROMACS-style plot data |

Export columns include:
- Time/Frame index
- Linear, planar, and spherical weights for each structure

Sources: [src/components/shapespace/shapespace.cpp:433-499]()

## Memory Management

The component uses arena allocation for efficient memory management:

**Memory Management Architecture**
```mermaid
graph LR
    subgraph "Memory Layout"
        ARENA["Arena Allocator"] --> BITFIELDS["Structure Bitfields"]
        ARENA --> WEIGHTS["Shape Weights Array"]
        ARENA --> COORDS["Plot Coordinates Array"]
        ARENA --> JOINED["Joined Bitfield"]
    end
    
    subgraph "Lifecycle"
        INIT["Initialize"] --> ALLOCATE["Allocate Arrays"]
        ALLOCATE --> RESET["Reset on Re-evaluation"]
        RESET --> DEALLOCATE["Cleanup on Shutdown"]
    end
```

Memory allocation strategy:
- **Arena Size**: 1 MB allocated from persistent allocator
- **Array Sizing**: `num_frames * num_structures` elements
- **Reset Strategy**: Arena reset on filter expression changes
- **Thread Safety**: Separate heap allocations for worker threads

Sources: [src/components/shapespace/shapespace.cpp:82-84](), [src/components/shapespace/shapespace.cpp:354-356](), [src/components/shapespace/shapespace.cpp:387-388]()

## Integration Points

### Filter System Integration

The component integrates with the molecular filter system to define atom selections:

**Filter System Integration**
```mermaid
graph LR
    subgraph "Filter Processing"
        INPUT["User Filter Expression"] --> PARSE["md_filter_evaluate"]
        PARSE --> VALIDATE["Input Validation"]
        VALIDATE --> BITFIELDS["Generate Bitfields"]
        BITFIELDS --> JOIN["Create Joined Bitfield"]
    end
    
    subgraph "Error Handling"
        ERROR["Parse Error"] --> DISPLAY["Show Error Tooltip"]
        VALID["Valid Input"] --> HIGHLIGHT["Update Highlight Mask"]
    end
```

Filter evaluation produces bitfields for each structure that define which atoms participate in the shape analysis.

Sources: [src/components/shapespace/shapespace.cpp:360-376]()

### Task System Integration

The component leverages the task system for parallel computation across trajectory frames:

- **Task Creation**: `task_system::create_pool_task()` with frame-based parallelization
- **Task Management**: Interrupt running tasks on parameter changes
- **Thread Safety**: Each worker thread allocates separate coordinate arrays
- **Synchronization**: Task completion updates UI state

Sources: [src/components/shapespace/shapespace.cpp:346-348](), [src/components/shapespace/shapespace.cpp:382-427]()

---