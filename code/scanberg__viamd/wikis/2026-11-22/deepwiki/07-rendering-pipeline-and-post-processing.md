# Rendering Pipeline and Post-Processing

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/gfx/immediate_draw_utils.cpp](src/gfx/immediate_draw_utils.cpp)
- [src/gfx/immediate_draw_utils.h](src/gfx/immediate_draw_utils.h)
- [src/gfx/postprocessing_utils.cpp](src/gfx/postprocessing_utils.cpp)
- [src/gfx/postprocessing_utils.h](src/gfx/postprocessing_utils.h)

</details>



This document covers the deferred rendering pipeline and comprehensive post-processing system in VIAMD. The system implements a modern deferred shading approach with G-buffer management, followed by a chain of post-processing effects including SSAO, temporal anti-aliasing, depth of field, and various tonemapping operators.

For volume rendering specifics, see [Volume Rendering System](#3.2). For camera controls and view parameters, see [Camera System and Controls](#3.3). For GLSL shader implementations, see [GLSL Shaders](#3.4).

## Architecture Overview

The rendering pipeline follows a deferred shading architecture where geometry is first rendered to a G-buffer containing multiple render targets, followed by a composition pass and post-processing chain.

### Pipeline Flow Diagram

```mermaid
graph TD
    GEOM["Geometry Rendering"] --> GBUFFER["G-Buffer Generation"]
    GBUFFER --> LINEAR["Linear Depth Computation"]
    LINEAR --> SSAO["SSAO Generation"]
    SSAO --> COMPOSE["Deferred Composition"]
    COMPOSE --> DOF["Depth of Field"]
    DOF --> TEMPORAL["Temporal Anti-Aliasing"]
    TEMPORAL --> TONEMAP["Tone Mapping"]
    TONEMAP --> FXAA["FXAA"]
    FXAA --> SHARPEN["Sharpening"]
    SHARPEN --> FINAL["Final Output"]
    
    GBUFFER --> VELOCITY["Velocity Buffer"]
    VELOCITY --> TEMPORAL
    
    subgraph "G-Buffer Targets"
        DEPTH["Depth Buffer"]
        COLOR["Color Buffer"]
        NORMAL["Normal Buffer"] 
        VEL["Velocity Buffer"]
        PICK["Picking Buffer"]
        TRANS["Transparency Buffer"]
    end
```

Sources: [src/gfx/postprocessing_utils.cpp:1-1500](), [src/gfx/postprocessing_utils.h:1-142]()

## G-Buffer Architecture

The G-buffer system manages multiple render targets to store geometric and material information for deferred shading.

### G-Buffer Layout

| Attachment | Format | Purpose |
|------------|--------|---------|
| `GL_COLOR_ATTACHMENT0` | `GL_R11F_G11F_B10F` | HDR Color |
| `GL_COLOR_ATTACHMENT1` | `GL_RG16_SNORM` | Encoded Normals |
| `GL_COLOR_ATTACHMENT2` | `GL_RG16F` | Velocity Vectors |
| `GL_COLOR_ATTACHMENT3` | `GL_R32UI` | Picking IDs |
| `GL_COLOR_ATTACHMENT4` | `GL_RGBA8` | Transparency |
| `GL_COLOR_ATTACHMENT5` | `GL_RGB16` | Temporal Accumulation |

### G-Buffer Data Structure

```mermaid
graph TB
    subgraph "GBuffer Structure"
        TEX["tex"] --> DEPTH["depth: uint32_t"]
        TEX --> COLOR["color: uint32_t"]
        TEX --> NORMAL["normal: uint32_t"]
        TEX --> VELOCITY["velocity: uint32_t"]
        TEX --> PICKING["picking: uint32_t"]
        TEX --> TRANSPARENCY["transparency: uint32_t"]
        TEX --> TEMPORAL["temporal_accumulation[2]: uint32_t"]
        
        PBO["pbo_picking"] --> PCOLOR["color[2]: uint32_t"]
        PBO --> PDEPTH["depth[2]: uint32_t"]
        PBO --> FRAME["frame: uint32_t"]
        
        PARAMS["Parameters"] --> FBO["fbo: uint32_t"]
        PARAMS --> WIDTH["width: uint32_t"]
        PARAMS --> HEIGHT["height: uint32_t"]
    end
```

Sources: [src/gfx/postprocessing_utils.h:18-40]()

## Post-Processing Effect Chain

The post-processing system is organized into modular namespaces, each handling specific effects with their own initialization and rendering functions.

### Effect Modules

```mermaid
graph LR
    subgraph "postprocessing namespace"
        SSAO["ssao::"] --> SSAO_INIT["initialize()"]
        SSAO --> SSAO_COMP["compute_ssao()"]
        
        DOF["dof::"] --> DOF_INIT["initialize()"]
        DOF --> DOF_RENDER["render_dof()"]
        
        TEMPORAL["temporal::"] --> TEMP_INIT["initialize()"]
        TEMPORAL --> TEMP_APPLY["apply_temporal_aa()"]
        
        TONEMAP["tonemapping::"] --> TONE_INIT["initialize()"]
        TONEMAP --> TONE_APPLY["apply_tonemapping()"]
        
        FXAA["fxaa::"] --> FXAA_INIT["initialize()"]
        FXAA --> FXAA_APPLY["apply_fxaa()"]
        
        VELOCITY["velocity::"] --> VEL_INIT["initialize()"]
        VEL_INIT --> VEL_COMP["compute_velocity()"]
    end
```

Sources: [src/gfx/postprocessing_utils.cpp:286-441](), [src/gfx/postprocessing_utils.cpp:443-460](), [src/gfx/postprocessing_utils.cpp:921-953]()

## Screen Space Ambient Occlusion (SSAO)

The SSAO implementation uses Horizon-Based Ambient Occlusion (HBAO) based on NVIDIA's technique, with support for both perspective and orthographic projections.

### SSAO Pipeline

```mermaid
graph TD
    DEPTH["Depth Buffer"] --> LINEAR["linearize_depth()"]
    LINEAR --> HBAO["HBAO Computation"]
    HBAO --> BLUR["Bilateral Blur"]
    BLUR --> OUTPUT["AO Texture"]
    
    subgraph "HBAO Data"
        UBO["HBAOData UBO"] --> RADIUS["radius_to_screen"]
        UBO --> NEG_INV["neg_inv_r2"]
        UBO --> BIAS["n_dot_v_bias"]
        UBO --> PROJ["proj_info"]
        UBO --> PATTERN["sample_pattern[32]"]
    end
    
    RANDOM["Random Texture 4x4"] --> HBAO
    UBO --> HBAO
```

The `HBAOData` structure contains all parameters needed for HBAO computation:

| Field | Type | Purpose |
|-------|------|---------|
| `radius_to_screen` | `float` | Screen-space radius scaling |
| `neg_inv_r2` | `float` | Negative inverse radius squared |
| `n_dot_v_bias` | `float` | Normal dot view bias |
| `proj_info` | `vec4_t` | Projection matrix information |
| `sample_pattern` | `vec4_t[32]` | Pre-computed sample pattern |

Sources: [src/gfx/postprocessing_utils.cpp:286-441](), [src/gfx/postprocessing_utils.cpp:306-364]()

## Temporal Anti-Aliasing and Motion Blur

The temporal anti-aliasing system combines current and previous frames using velocity vectors to reduce aliasing and optionally add motion blur effects.

### Velocity Buffer Generation

```mermaid
graph TD
    DEPTH["Current Depth"] --> VELOCITY["velocity::blit_velocity"]
    PREVMAT["Previous MVP Matrix"] --> VELOCITY
    CURRMAT["Current MVP Matrix"] --> VELOCITY
    JITTER["Jitter UV"] --> VELOCITY
    
    VELOCITY --> TILEMAX["velocity::blit_tilemax"]
    TILEMAX --> NEIGHBORMAX["velocity::blit_neighbormax"]
    
    subgraph "Velocity Textures"
        VTEX["Velocity Texture RG16F"]
        TILE["Tile Max Texture"]
        NEIGHBOR["Neighbor Max Texture"]
    end
    
    NEIGHBORMAX --> TILE
    NEIGHBORMAX --> NEIGHBOR
```

### Temporal AA Implementation

The system supports two modes via separate shader programs:
- `temporal::with_motion_blur` - Includes motion blur sampling
- `temporal::no_motion_blur` - Pure temporal anti-aliasing

Key parameters:
- `feedback_min/max` - Controls temporal feedback strength
- `motion_scale` - Scales motion blur intensity
- `jitter_uv` - Sub-pixel jittering for sample distribution

Sources: [src/gfx/postprocessing_utils.cpp:825-919](), [src/gfx/postprocessing_utils.cpp:921-953]()

## Depth of Field System

The depth of field implementation uses a two-pass approach with half-resolution preprocessing and full-resolution composition.

### DOF Pipeline

```mermaid
graph TD
    COLOR["Color Buffer"] --> HALF["Half-Res Prepass"]
    DEPTH["Depth Buffer"] --> HALF
    FOCUS["Focus Parameters"] --> HALF
    
    HALF --> COC["Color + CoC Texture"]
    COC --> BOKEH["Bokeh DOF Pass"]
    
    subgraph "DOF Parameters"
        POINT["focus_point: float"]
        SCALE["focus_scale: float"]
        TIME["time: float"]
    end
    
    POINT --> BOKEH
    SCALE --> BOKEH
    TIME --> BOKEH
```

The half-resolution prepass computes circle of confusion (CoC) values alongside downsampled color, which are then used in the full-resolution bokeh pass for efficient depth of field rendering.

Sources: [src/gfx/postprocessing_utils.cpp:648-698]()

## Tone Mapping Operators

The system provides multiple tone mapping operators for HDR to LDR conversion:

### Available Operators

```mermaid
graph TD
    INPUT["HDR Input"] --> PASS["Passthrough"]
    INPUT --> EXPO["Exposure + Gamma"]
    INPUT --> FILM["Filmic (Uncharted)"]
    INPUT --> ACES["ACES"]
    INPUT --> FAST["Fast Reversible"]
    
    subgraph "Tone Mapping Types"
        T1["Tonemapping_Passthrough"]
        T2["Tonemapping_ExposureGamma"]
        T3["Tonemapping_Filmic"]
        T4["Tonemapping_ACES"]
    end
```

| Mode | Purpose | Parameters |
|------|---------|------------|
| `Passthrough` | No tone mapping | None |
| `ExposureGamma` | Simple exposure + gamma | `exposure`, `gamma` |
| `Filmic` | Uncharted 2 tone mapper | `exposure`, `gamma` |
| `ACES` | ACES filmic tone mapper | `exposure`, `gamma` |
| `Fast Reversible` | Reversible for temporal AA | None |

Sources: [src/gfx/postprocessing_utils.cpp:558-646]()

## Immediate Mode Rendering Integration

The immediate mode drawing system provides debug and utility rendering that integrates with the deferred pipeline.

### Immediate Rendering Flow

```mermaid
graph TD
    SETUP["immediate::set_model_view_matrix()"] --> DRAW["Draw Commands"]
    PROJ["immediate::set_proj_matrix()"] --> DRAW
    
    DRAW --> POINT["draw_point()"]
    DRAW --> LINE["draw_line()"]
    DRAW --> TRI["draw_triangle()"]
    DRAW --> PLANE["draw_plane()"]
    
    POINT --> BATCH["Batching System"]
    LINE --> BATCH
    TRI --> BATCH
    PLANE --> BATCH
    
    BATCH --> RENDER["immediate::render()"]
    RENDER --> GBUFFER["G-Buffer Output"]
    
    subgraph "Vertex Format"
        COORD["coord: vec3_t"]
        COLOR["color: uint32_t"]
    end
```

The immediate mode system outputs to the same G-buffer as the main geometry, using a simple vertex format with position and packed color. Draw commands are batched by primitive type and matrix state to minimize state changes.

Sources: [src/gfx/immediate_draw_utils.cpp:89-116](), [src/gfx/immediate_draw_utils.cpp:206-274](), [src/gfx/immediate_draw_utils.h:7-10]()

## Implementation Details

### Initialization and Resource Management

The post-processing system uses a centralized initialization approach:

```mermaid
graph TD
    INIT["postprocessing::initialize()"] --> SSAO_I["ssao::initialize()"]
    INIT --> DOF_I["dof::initialize()"]
    INIT --> VEL_I["velocity::initialize()"]
    INIT --> TEMP_I["temporal::initialize()"]
    INIT --> TONE_I["tonemapping::initialize()"]
    INIT --> FXAA_I["fxaa::initialize()"]
    INIT --> OTHER["Other modules..."]
    
    subgraph "Global Resources"
        VAO["Fullscreen VAO"]
        VSHADER["v_shader_fs_quad"]
        TARGETS["Color/Temporal Targets"]
        LINEAR["Linear Depth Target"]
    end
```

Each module manages its own OpenGL resources (programs, textures, framebuffers) with proper cleanup in corresponding `shutdown()` functions.

### Shader Program Management

The system uses a common pattern for shader program creation via `setup_program_from_source()`:

1. Compile fragment shader with optional defines
2. Link with shared fullscreen quad vertex shader
3. Store uniform locations for efficient updates
4. Error handling with detailed logging

Sources: [src/gfx/postprocessing_utils.cpp:999-1112](), [src/gfx/postprocessing_utils.cpp:259-282]()

---