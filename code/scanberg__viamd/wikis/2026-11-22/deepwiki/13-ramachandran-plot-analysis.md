# Ramachandran Plot Analysis

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

The Ramachandran Plot Analysis system provides interactive visualization and analysis of protein backbone dihedral angles (phi and psi) in molecular dynamics trajectories. This component generates density plots, reference comparisons, and enables interactive selection of protein conformations through 2D plot interfaces.

This system is part of the broader analysis framework and integrates with the parallel task system for computational performance. For general task scheduling and parallel processing, see [Task System and Parallel Processing](#4.1). For molecular visualization components, see [Molecular Data Structures and Display](#2.4).

## System Architecture

### High-Level Component Architecture

```mermaid
graph TB
    subgraph "Ramachandran Analysis System"
        RamaMain["Ramachandran<br/>ramachandran.cpp<br/>Main Event Handler"]
        RamaRep["rama_rep_t<br/>Texture & Density Storage"]
        DensityComp["Density Computation<br/>rama_rep_compute_density()"]
        RefData["Reference Data<br/>density_gen.inl, density_gly.inl<br/>density_pro.inl, density_pre.inl"]
    end
    
    subgraph "Rendering Pipeline"
        GLShaders["GLSL Shaders<br/>f_shader_map_src<br/>f_shader_iso_src"]
        TexSystem["OpenGL Textures<br/>map_tex[4], iso_tex[4]<br/>den_tex"]
        RenderLogic["GPU Rendering<br/>rama_render_density()"]
    end
    
    subgraph "UI & Interaction"
        ImPlotInt["ImPlot Integration<br/>BeginPlot(), PlotScatterG()"]
        Selection["Selection System<br/>selection_rect<br/>highlight_mask"]
        Menu["Menu System<br/>ViamdWindowDrawMenu"]
    end
    
    subgraph "External Systems"
        TaskSys["task_system::<br/>create_pool_task()<br/>enqueue_task()"]
        EventSys["viamd::EventHandler<br/>process_events()"]
        MolData["md_molecule_t<br/>protein_backbone"]
    end
    
    RamaMain --> RamaRep
    RamaMain --> DensityComp
    RamaMain --> RefData
    
    DensityComp --> GLShaders
    RamaRep --> TexSystem
    TexSystem --> RenderLogic
    
    RamaMain --> ImPlotInt
    ImPlotInt --> Selection
    RamaMain --> Menu
    
    RamaMain --> TaskSys
    RamaMain --> EventSys
    DensityComp --> MolData
    
    style RamaMain fill:#e1f5fe,stroke:#01579b,stroke-width:2px
    style TaskSys fill:#f3e5f5,stroke:#4a148c
    style EventSys fill:#e8f5e8,stroke:#1b5e20
```

**Sources:** [src/components/ramachandran/ramachandran.cpp:432-1249](), [src/task_system.h:9-64](), [src/event.h:1-89]()

### Data Flow and Processing Pipeline

```mermaid
graph LR
    subgraph "Input Data"
        BackboneAngles["trajectory_data.<br/>backbone_angles"]
        MolBackbone["mol.protein_backbone.<br/>angle[], ramachandran_type[]"]
        RefDensity["Reference Density Maps<br/>density_gen[], density_gly[]<br/>density_pro[], density_pre[]"]
    end
    
    subgraph "Computation Tasks"
        DensityTask["rama_rep_compute_density()<br/>task_system::ID"]
        BlurOps["blur_density_gaussian()<br/>blur_density_box()"]
        TypeClassify["Ramachandran Type Classification<br/>rama_type_indices[4]"]
    end
    
    subgraph "GPU Textures"
        DenTex["den_tex<br/>GL_RGBA32F 512x512"]
        MapTex["map_tex[4]<br/>GL_RGBA8 1024x1024"]
        IsoTex["iso_tex[4]<br/>GL_RGBA8 1024x1024"]
    end
    
    subgraph "Visualization"
        Colormap["Colormap Rendering<br/>f_shader_map_src"]
        Isolines["Isoline Rendering<br/>f_shader_iso_src"]
        ScatterPlot["Current Frame Points<br/>PlotScatterG()"]
    end
    
    BackboneAngles --> DensityTask
    MolBackbone --> TypeClassify
    RefDensity --> DenTex
    
    DensityTask --> BlurOps
    BlurOps --> DenTex
    TypeClassify --> DensityTask
    
    DenTex --> MapTex
    DenTex --> IsoTex
    
    MapTex --> Colormap
    IsoTex --> Isolines
    MolBackbone --> ScatterPlot
    
    style DensityTask fill:#fff3e0,stroke:#e65100
    style DenTex fill:#e1f5fe,stroke:#01579b
```

**Sources:** [src/components/ramachandran/ramachandran.cpp:651-684](), [src/components/ramachandran/ramachandran.cpp:1250-1450](), [src/components/ramachandran/ramachandran.cpp:369-388]()

## Core Components

### Ramachandran Main Class

The central `Ramachandran` class inherits from `viamd::EventHandler` and manages the entire analysis pipeline:

| Component | Type | Purpose |
|-----------|------|---------|
| `map.program` | `GLuint` | OpenGL shader program for colormap rendering |
| `iso.program` | `GLuint` | OpenGL shader program for isoline rendering |
| `rama_data.ref` | `rama_rep_t` | Reference density data and textures |
| `rama_data.full` | `rama_rep_t` | Full trajectory density data |
| `rama_data.filt` | `rama_rep_t` | Filtered trajectory density data |
| `rama_type_indices[4]` | `md_array(uint32_t)` | Indices for General, Glycine, Proline, Pre-Proline |

**Sources:** [src/components/ramachandran/ramachandran.cpp:432-516]()

### Density Representation Structure

The `rama_rep_t` structure encapsulates all GPU resources for ramachandran visualization:

```cpp
struct rama_rep_t {
    uint32_t map_tex[4];  // Colormap textures for 4 types
    uint32_t iso_tex[4];  // Isoline textures for 4 types  
    float    den_sum[4];  // Density normalization values
    uint32_t den_tex;     // Combined 4-channel density texture
};
```

**Sources:** [src/components/ramachandran/ramachandran.cpp:58-63]()

### Event-Driven Architecture Integration

```mermaid
graph TD
    subgraph "Event Processing"
        InitEvent["ViamdInitialize<br/>initialize()"]
        ShutdownEvent["ViamdShutdown<br/>shutdown()"]
        TickEvent["ViamdFrameTick<br/>update() + draw()"]
        TopoEvent["ViamdTopologyInit<br/>on_topology_init()"]
        MenuEvent["ViamdWindowDrawMenu<br/>Checkbox toggle"]
    end
    
    subgraph "State Management"
        StateInit["OpenGL Resource Creation<br/>rama_rep_init()"]
        StateUpdate["Fingerprint Comparison<br/>full_fingerprint<br/>filt_fingerprint"]
        StateCleanup["Resource Cleanup<br/>rama_rep_free()"]
    end
    
    subgraph "Task Coordination"
        TaskCreate["task_system::create_pool_task()"]
        TaskEnqueue["task_system::enqueue_task()"]
        TaskInterrupt["task_system::task_interrupt()"]
    end
    
    InitEvent --> StateInit
    TopoEvent --> StateUpdate
    TickEvent --> StateUpdate
    ShutdownEvent --> StateCleanup
    
    StateUpdate --> TaskCreate
    TaskCreate --> TaskEnqueue
    StateUpdate --> TaskInterrupt
    
    style InitEvent fill:#e8f5e8,stroke:#1b5e20
    style TaskCreate fill:#fff3e0,stroke:#e65100
```

**Sources:** [src/components/ramachandran/ramachandran.cpp:518-548](), [src/components/ramachandran/ramachandran.cpp:621-650](), [src/components/ramachandran/ramachandran.cpp:652-686]()

## Parallel Density Computation

### Task System Integration

The system leverages the task system for parallel density computation across trajectory frames:

```cpp
compute_density_full = rama_rep_compute_density(
    &rama_data.full, 
    state.trajectory_data.backbone_angles.data, 
    frame_beg, frame_end, frame_stride
);
```

This creates a `task_system::ID` that can be monitored, interrupted, and synchronized.

**Sources:** [src/components/ramachandran/ramachandran.cpp:664](), [src/task_system.h:29-31]()

### Density Computation Algorithm

| Phase | Function | Purpose |
|-------|----------|---------|
| Classification | Type assignment | Assigns residues to General/Glycine/Proline/Pre-Proline |
| Accumulation | Angle binning | Accumulates phi/psi angles into 180x180 density grid |
| Smoothing | `blur_density_gaussian()` | Applies Gaussian blur for smooth visualization |
| Normalization | Density scaling | Normalizes density values for texture upload |

**Sources:** [src/components/ramachandran/ramachandran.cpp:369-388](), [src/components/ramachandran/ramachandran.cpp:286-367]()

## GPU Rendering Pipeline

### Shader-Based Visualization

The system uses two specialized fragment shaders for different visualization modes:

#### Colormap Shader (`f_shader_map_src`)
- Maps density values to colors using configurable colormaps
- Supports 4 ramachandran types in single pass
- Handles viewport transformation and texture sampling

#### Isoline Shader (`f_shader_iso_src`)
- Generates contour lines at specified density levels
- Anti-aliased line rendering using `fwidth()` derivatives
- Supports both filled regions and contour outlines

**Sources:** [src/components/ramachandran/ramachandran.cpp:91-131](), [src/components/ramachandran/ramachandran.cpp:133-195]()

### Texture Management

```mermaid
graph TB
    subgraph "Texture Types"
        DensityTex["den_tex<br/>GL_RGBA32F<br/>512x512<br/>4-channel density"]
        ColormapTex["map_tex[4]<br/>GL_RGBA8<br/>1024x1024<br/>Rendered colormaps"]
        IsolineTex["iso_tex[4]<br/>GL_RGBA8<br/>1024x1024<br/>Rendered isolines"]
    end
    
    subgraph "Processing Flow"
        DensityUpload["glTexSubImage2D()<br/>Raw density data"]
        MapRender["Colormap shader pass<br/>f_shader_map_src"]
        IsoRender["Isoline shader pass<br/>f_shader_iso_src"]
    end
    
    DensityUpload --> DensityTex
    DensityTex --> MapRender
    DensityTex --> IsoRender
    MapRender --> ColormapTex
    IsoRender --> IsolineTex
    
    style DensityTex fill:#e1f5fe,stroke:#01579b
```

**Sources:** [src/components/ramachandran/ramachandran.cpp:390-424](), [src/components/ramachandran/ramachandran.cpp:1467-1600]()

## Interactive Visualization

### ImPlot Integration

The visualization uses ImPlot for interactive 2D plotting with the following key features:

| Feature | Implementation | Purpose |
|---------|----------------|---------|
| Multiple layouts | `layout_mode` 0-4 | Side-by-side or individual ramachandran types |
| Layer control | `show_layer[4]` | Toggle reference/full/filtered/current display |
| Selection rectangles | `selection_rect` | Interactive region selection |
| Point highlighting | Scatter plot overlay | Current frame angle visualization |

**Sources:** [src/components/ramachandran/ramachandran.cpp:688-1023]()

### Selection and Highlighting System

```mermaid
graph LR
    subgraph "Input Events"
        MouseClick["Mouse Click<br/>Shift + Click"]
        MouseDrag["Mouse Drag<br/>Rectangle selection"]
        Hover["Mouse Hover<br/>Point highlighting"]
    end
    
    subgraph "Selection Logic" 
        RectSelect["ImPlotRect selection_rect"]
        PointTest["Distance-based point test"]
        ResidueMap["residue_idx mapping"]
    end
    
    subgraph "Mask Operations"
        HighlightMask["highlight_mask updates"]
        SelectionMask["selection_mask updates"]
        GranularityGrow["grow_mask_by_selection_granularity()"]
    end
    
    MouseClick --> RectSelect
    MouseDrag --> RectSelect
    Hover --> PointTest
    
    RectSelect --> ResidueMap
    PointTest --> ResidueMap
    
    ResidueMap --> HighlightMask
    ResidueMap --> SelectionMask
    HighlightMask --> GranularityGrow
```

**Sources:** [src/components/ramachandran/ramachandran.cpp:854-1014](), [src/components/ramachandran/ramachandran.cpp:920-935]()

## Performance Optimization

### Memory Management

The system uses arena allocators for efficient memory management:

```cpp
arena = md_arena_allocator_create(state.allocator.persistent, MEGABYTES(1));
```

### Computational Optimizations

| Technique | Implementation | Benefit |
|-----------|----------------|---------|
| Block transpose | `transpose()` function | Cache-efficient blur operations |
| Box filter approximation | `boxes_for_gauss()` | Fast Gaussian blur via separable box filters |
| Texture caching | Fingerprint comparison | Avoid redundant computation |
| Task interruption | `task_interrupt()` | Responsive UI during computation |

**Sources:** [src/components/ramachandran/ramachandran.cpp:317-332](), [src/components/ramachandran/ramachandran.cpp:334-345](), [src/components/ramachandran/ramachandran.cpp:622-627]()

---