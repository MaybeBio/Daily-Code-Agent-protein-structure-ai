# Graphics and Visualization Pipeline

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/gfx/camera_utils.cpp](src/gfx/camera_utils.cpp)
- [src/gfx/camera_utils.h](src/gfx/camera_utils.h)
- [src/gfx/gl_utils.cpp](src/gfx/gl_utils.cpp)
- [src/gfx/gl_utils.h](src/gfx/gl_utils.h)
- [src/gfx/immediate_draw_utils.cpp](src/gfx/immediate_draw_utils.cpp)
- [src/gfx/immediate_draw_utils.h](src/gfx/immediate_draw_utils.h)
- [src/gfx/postprocessing_utils.cpp](src/gfx/postprocessing_utils.cpp)
- [src/gfx/postprocessing_utils.h](src/gfx/postprocessing_utils.h)
- [src/gfx/view_param.h](src/gfx/view_param.h)
- [src/gfx/volumerender_utils.cpp](src/gfx/volumerender_utils.cpp)
- [src/gfx/volumerender_utils.h](src/gfx/volumerender_utils.h)

</details>



## Purpose and Scope

This section provides an overview of VIAMD's complete graphics and visualization pipeline, covering the architecture and integration of 3D rendering, volume visualization, and post-processing systems. The pipeline is designed to handle both traditional molecular geometry rendering and advanced volumetric visualization of electronic structure data.

For detailed information about specific components, see:
- Deferred rendering and post-processing implementation details: [Rendering Pipeline and Post-Processing](#3.1)
- Volume ray-casting and transfer functions: [Volume Rendering System](#3.2)  
- Camera controls and projection matrices: [Camera System and Controls](#3.3)
- Shader programs and rendering techniques: [GLSL Shaders](#3.4)

## Pipeline Architecture

The graphics pipeline follows a deferred rendering approach with specialized volume rendering capabilities and extensive post-processing effects. The system is designed around several key components that work together to produce high-quality molecular visualizations.

### High-Level Pipeline Flow

```mermaid
graph TD
    A["Camera System"] --> B["G-Buffer Generation"]
    B --> C["Volume Rendering"]
    C --> D["Post-Processing Pipeline"]
    D --> E["Final Output"]
    
    F["Scene Geometry"] --> B
    G["Volume Data"] --> C
    H["Transfer Functions"] --> C
    
    B --> I["Depth Buffer"]
    B --> J["Color Buffer"] 
    B --> K["Normal Buffer"]
    B --> L["Velocity Buffer"]
    
    I --> C
    J --> D
    K --> D
    L --> D
    
    D --> M["SSAO"]
    D --> N["Temporal AA"]
    D --> O["DOF"]
    D --> P["Tonemapping"]
    D --> Q["FXAA"]
    
    style A fill:#f9f9f9
    style D fill:#f9f9f9
    style C fill:#f9f9f9
```

**Pipeline Flow Overview**

Sources: [src/gfx/postprocessing_utils.h:62-120](), [src/gfx/volumerender_utils.h:43-108](), [src/gfx/view_param.h:5-31]()

### Core Data Structures

The pipeline operates on several key data structures that coordinate rendering state and parameters across different systems:

| Structure | Purpose | Key Fields | File |
|-----------|---------|------------|------|
| `GBuffer` | Deferred rendering buffers | `tex.depth`, `tex.color`, `tex.normal`, `tex.velocity` | [postprocessing_utils.h:18-40]() |
| `ViewParam` | View/projection matrices | `matrix.curr`, `matrix.prev`, `jitter` | [view_param.h:5-31]() |
| `Camera` | Camera state and parameters | `position`, `orientation`, `fov_y` | [camera_utils.h:1-4]() |
| `RenderDesc` | Volume rendering parameters | `texture.volume`, `matrix`, `iso`, `dvr` | [volumerender_utils.h:43-108]() |

### System Integration

```mermaid
graph LR
    subgraph "Graphics Pipeline Systems"
        Camera["camera_utils"]
        Volume["volumerender_utils"] 
        PostFX["postprocessing_utils"]
        Immediate["immediate_draw_utils"]
        GLUtils["gl_utils"]
    end
    
    subgraph "Core Data Flow"
        ViewParam["ViewParam"]
        GBuffer["GBuffer"]
        Textures["GL Textures"]
    end
    
    subgraph "External Dependencies"
        GLFW["GLFW Window"]
        OpenGL["OpenGL Context"]
        Shaders["GLSL Shaders"]
    end
    
    Camera --> ViewParam
    ViewParam --> Volume
    ViewParam --> PostFX
    
    Volume --> GBuffer
    PostFX --> GBuffer
    
    GLUtils --> Textures
    GLUtils --> Shaders
    
    Textures --> Volume
    Textures --> PostFX
    
    OpenGL --> GLUtils
    GLFW --> Camera
    
    Immediate --> OpenGL
```

**System Integration Diagram**

Sources: [src/gfx/camera_utils.cpp:1-286](), [src/gfx/postprocessing_utils.cpp:1-1600](), [src/gfx/volumerender_utils.cpp:1-561]()

## Rendering Systems

### Deferred Rendering Pipeline

The core rendering uses a deferred approach with multiple render targets stored in a `GBuffer`. This allows for efficient post-processing and complex lighting calculations:

```mermaid
graph TD
    A["Geometry Pass"] --> B["G-Buffer"]
    B --> C["tex.depth"]
    B --> D["tex.color"] 
    B --> E["tex.normal"]
    B --> F["tex.velocity"]
    B --> G["tex.picking"]
    
    C --> H["Depth Testing"]
    D --> I["Lighting Pass"]
    E --> I
    F --> J["Motion Blur"]
    G --> K["Object Picking"]
    
    I --> L["Shaded Result"]
    
    style B fill:#f9f9f9
```

**G-Buffer Structure and Usage**

The `GBuffer` structure manages multiple render targets with specific purposes:
- **Depth**: Z-buffer for depth testing and volume ray termination
- **Color**: Base surface colors and material properties  
- **Normal**: Surface normals for lighting calculations
- **Velocity**: Screen-space motion vectors for temporal effects
- **Picking**: Object IDs for interactive selection

Sources: [src/gfx/postprocessing_utils.h:18-40](), [src/gfx/postprocessing_utils.cpp:57-193]()

### Volume Rendering Integration

Volume rendering operates as a separate pass that can composite with or replace the deferred geometry results:

```mermaid
graph LR
    A["Entry/Exit Points"] --> B["Ray Generation"]
    B --> C["Volume Sampling"]
    C --> D["Transfer Function"]
    D --> E["DVR Integration"]
    C --> F["Isosurface Detection"] 
    F --> G["ISO Shading"]
    E --> H["Final Composition"]
    G --> H
    
    I["Depth Buffer"] --> B
    J["Volume Texture"] --> C
    K["Transfer Function Texture"] --> D
    
    style C fill:#f9f9f9
    style H fill:#f9f9f9
```

**Volume Rendering Pipeline**

The volume renderer supports both Direct Volume Rendering (DVR) and isosurface extraction through a unified ray-casting approach. Key functions include:

- `render_volume()`: Main entry point taking a `RenderDesc`
- Entry/exit point generation using cube geometry
- Ray-casting with early termination using depth buffer
- Support for multiple isosurfaces with individual colors

Sources: [src/gfx/volumerender_utils.cpp:349-558](), [src/gfx/volumerender_utils.h:43-108]()

### Post-Processing Effects

The post-processing pipeline applies a series of effects in a specific order to enhance visual quality:

```mermaid
graph TD
    A["Input Buffers"] --> B["SSAO"]
    B --> C["Temporal AA + Motion Blur"]
    C --> D["Depth of Field"]
    D --> E["Tonemapping"]
    E --> F["FXAA"]
    F --> G["Final Output"]
    
    H["Linear Depth"] --> B
    H --> C
    I["Velocity Buffers"] --> C
    J["Previous Frame"] --> C
    
    style B fill:#f9f9f9
    style C fill:#f9f9f9
    style E fill:#f9f9f9
```

**Post-Processing Effect Chain**

Each effect is implemented as a separate shader program with specific uniform parameters controlled by the `postprocessing::Descriptor` structure. Key effects include:

- **SSAO**: Horizon-Based Ambient Occlusion using depth buffer sampling
- **Temporal AA**: Reduces aliasing by accumulating multiple jittered frames
- **Motion Blur**: Screen-space blur based on velocity vectors
- **Depth of Field**: Bokeh-style blur with circle of confusion
- **Tonemapping**: HDR to LDR conversion with multiple curve options

Sources: [src/gfx/postprocessing_utils.cpp:286-1600](), [src/gfx/postprocessing_utils.h:62-136]()

## Camera and View Management

### Camera Control System

The camera system provides multiple control schemes optimized for molecular visualization:

```mermaid
graph LR
    A["TrackballControllerInput"] --> B["camera_controller_trackball()"]
    B --> C["Position Update"]
    B --> D["Orientation Update"]  
    B --> E["Distance Update"]
    
    F["Mouse Events"] --> A
    G["Keyboard Input"] --> A
    
    C --> H["View Matrix"]
    D --> H
    E --> H
    
    H --> I["ViewParam"]
    
    J["Projection Parameters"] --> K["Projection Matrix"]
    K --> I
    
    style B fill:#f9f9f9
    style I fill:#f9f9f9
```

**Camera Control Flow**

The trackball controller provides intuitive 3D navigation with separate rotation, panning, and zoom operations. The system maintains camera state as position, orientation (quaternion), and focus distance for stable interpolation.

Key functions:
- `camera_controller_trackball()`: Main input processing
- `camera_interpolate_look_at()`: Smooth camera transitions
- `camera_perspective_projection_matrix()`: Projection matrix generation with jitter support

Sources: [src/gfx/camera_utils.cpp:202-235](), [src/gfx/camera_utils.h:23-115]()

### View Parameter Management

The `ViewParam` structure encapsulates all view-related matrices and state needed by the rendering pipeline:

| Field | Purpose | Usage |
|-------|---------|-------|
| `matrix.curr` | Current frame matrices | Primary rendering |
| `matrix.prev` | Previous frame matrices | Temporal effects |
| `matrix.inv` | Inverse matrices | Screen-space calculations |
| `jitter.curr/prev` | Temporal jitter offsets | Anti-aliasing |
| `clip_planes` | Near/far planes | Depth reconstruction |

Sources: [src/gfx/view_param.h:5-31]()

## Immediate Mode Drawing

For debug visualization and UI overlays, the system includes an immediate mode drawing API:

```mermaid
graph LR
    A["Draw Commands"] --> B["Vertex Batching"]
    B --> C["Command Buffer"]
    C --> D["Render Pass"]
    
    E["draw_point()"] --> A
    F["draw_line()"] --> A
    G["draw_triangle()"] --> A
    H["draw_box_wireframe()"] --> A
    
    I["Matrix Stack"] --> D
    J["Shader Program"] --> D
    
    style B fill:#f9f9f9
    style D fill:#f9f9f9
```

**Immediate Drawing System**

The immediate drawing system provides a simple API for rendering basic primitives without complex state management. It batches geometry into vertex and index buffers and renders everything in a single pass.

Key functions:
- `immediate::draw_*()`: Primitive drawing functions
- `immediate::set_model_view_matrix()`: Matrix management
- `immediate::render()`: Execute batched commands

Sources: [src/gfx/immediate_draw_utils.cpp:13-544](), [src/gfx/immediate_draw_utils.h:5-66]()

## OpenGL Utilities and Resources

### Shader and Texture Management

The `gl_utils` module provides essential OpenGL resource management:

```mermaid
graph TD
    A["Shader Source"] --> B["compile_shader_from_source()"]
    B --> C["Compiled Shader"]
    C --> D["attach_link_detach()"]
    D --> E["Linked Program"]
    
    F["Texture Specs"] --> G["init_texture_*D()"]
    G --> H["GL Texture"]
    H --> I["set_texture_*D_data()"]
    I --> J["Populated Texture"]
    
    K["Include Files"] --> B
    L["Defines"] --> B
    
    style B fill:#f9f9f9
    style G fill:#f9f9f9
```

**OpenGL Resource Management**

The utilities handle shader compilation with include support, texture creation and data upload, and error checking throughout the pipeline.

Key functions:
- `gl::compile_shader_from_source()`: Shader compilation with includes and defines
- `gl::init_texture_*D()`: Texture creation with format validation
- `gl::set_texture_*D_data()`: Efficient data upload

Sources: [src/gfx/gl_utils.cpp:1-401](), [src/gfx/gl_utils.h:6-30]()

---