# Custom UI Components

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [ext/ImGuiColorTextEdit/CMakeLists.txt](ext/ImGuiColorTextEdit/CMakeLists.txt)
- [ext/imgui/CMakeLists.txt](ext/imgui/CMakeLists.txt)
- [ext/implot/CMakeLists.txt](ext/implot/CMakeLists.txt)
- [ext/nativefiledialog/CMakeLists.txt](ext/nativefiledialog/CMakeLists.txt)
- [ext/nativefiledialog/cmake/FindGTK3.cmake](ext/nativefiledialog/cmake/FindGTK3.cmake)
- [src/image.cpp](src/image.cpp)
- [src/image.h](src/image.h)
- [src/imgui_widgets.cpp](src/imgui_widgets.cpp)
- [src/imgui_widgets.h](src/imgui_widgets.h)
- [src/implot_widgets.cpp](src/implot_widgets.cpp)
- [src/implot_widgets.h](src/implot_widgets.h)

</details>



This document covers the custom UI components and utilities that extend the base ImGui and ImPlot functionality in VIAMD. These components provide specialized widgets, styling, image export capabilities, and native file dialog integration to create a cohesive molecular visualization interface.

For information about the core ImGui integration and widget system, see [ImGui Core and Widgets](#5.1). For text editing capabilities, see [Text Editor and Script Interface](#5.3).

## Custom Widget Architecture

VIAMD extends the base ImGui/ImPlot functionality through several custom widget implementations and utility functions that provide specialized molecular visualization UI components.

```mermaid
graph TB
    subgraph "Base Libraries"
        IMGUI["ImGui Core"]
        IMPLOT["ImPlot Core"]
        STB["STB Image"]
        NFD["Native File Dialog"]
    end
    
    subgraph "Custom ImGui Extensions"
        RANGE_SLIDER["RangeSliderFloat"]
        COORD_WIDGET["DrawCoordinateSystemWidget"]
        THEME["init_theme"]
        DOCKSPACE["CreateDockspace"]
        CANVAS["BeginCanvas/EndCanvas"]
        DELETE_BTN["DeleteButton"]
        COLOR_EDIT["ColorEdit3/4Minimal"]
        CHECKERBOARD["DrawCheckerboard"]
    end
    
    subgraph "Custom ImPlot Extensions"
        DRAG_RANGE["DragRangeX"]
        COLORMAP_SEL["ColormapSelection"]
        SYNC_AXES["SyncAxesY"]
    end
    
    subgraph "Image Utilities"
        IMG_JPG["image_write_jpg"]
        IMG_PNG["image_write_png"]
        IMG_BMP["image_write_bmp"]
    end
    
    subgraph "File Dialog Integration"
        NFD_WRAPPER["Native File Dialog\nCMake Integration"]
    end
    
    IMGUI --> RANGE_SLIDER
    IMGUI --> COORD_WIDGET
    IMGUI --> THEME
    IMGUI --> DOCKSPACE
    IMGUI --> CANVAS
    IMGUI --> DELETE_BTN
    IMGUI --> COLOR_EDIT
    IMGUI --> CHECKERBOARD
    
    IMPLOT --> DRAG_RANGE
    IMPLOT --> COLORMAP_SEL
    IMPLOT --> SYNC_AXES
    
    STB --> IMG_JPG
    STB --> IMG_PNG
    STB --> IMG_BMP
    
    NFD --> NFD_WRAPPER
    
    style IMGUI fill:#e1f5fe
    style IMPLOT fill:#f3e5f5
    style STB fill:#e8f5e8
    style NFD fill:#fff3e0
```

**Sources:** [src/imgui_widgets.cpp:1-569](), [src/implot_widgets.cpp:1-179](), [src/image.cpp:1-52](), [ext/nativefiledialog/CMakeLists.txt:1-73]()

## Custom ImGui Widget Components

The custom ImGui widgets provide specialized functionality for molecular visualization interfaces, including range controls, coordinate system visualization, and enhanced styling.

### Range Slider Widget

The `RangeSliderFloat` widget allows users to select a range of values with two handles, commonly used for filtering and parameter adjustment in molecular analysis.

```mermaid
graph LR
    subgraph "RangeSliderFloat Implementation"
        BEHAVIOR["RangeSliderBehavior"]
        RENDER["RenderFrame"]
        INTERACTION["Mouse/Wheel Input"]
    end
    
    subgraph "Key Functions"
        SCALE_RATIO["ScaleRatioFromValueT"]
        SCALE_VALUE["ScaleValueFromRatioT"]
        ROUND_SCALAR["RoundScalarWithFormatT"]
    end
    
    BEHAVIOR --> SCALE_RATIO
    BEHAVIOR --> SCALE_VALUE
    BEHAVIOR --> ROUND_SCALAR
    RENDER --> BEHAVIOR
    INTERACTION --> BEHAVIOR
```

**Sources:** [src/imgui_widgets.cpp:13-189](), [src/imgui_widgets.h:18-18]()

### Coordinate System Widget

The `DrawCoordinateSystemWidget` provides an interactive 3D coordinate system visualization that allows users to quickly orient the camera view by clicking on coordinate planes.

```mermaid
graph TB
    subgraph "CoordSystemWidgetParam Structure"
        POS["pos: ImVec2"]
        SIZE["size: ImVec2"]
        VIEW_MAT["view_matrix: mat4_t"]
        CAM_ORI["camera_ori: quat_t"]
        CAM_POS["camera_pos: vec3_t"]
        CAM_DIST["camera_dist: float"]
    end
    
    subgraph "Rendering Pipeline"
        PROJECTION["Perspective Projection"]
        TRANSFORM["Matrix Transforms"]
        DRAW_AXES["Draw X/Y/Z Axes"]
        DRAW_PLANES["Draw Interaction Planes"]
        Z_SORTING["Z-Order Sorting"]
    end
    
    subgraph "Interaction Handling"
        HIT_TEST["Triangle Hit Testing"]
        CAM_UPDATE["Camera Orientation Update"]
        AXIS_ALIGN["Axis Alignment Logic"]
    end
    
    POS --> PROJECTION
    SIZE --> PROJECTION
    VIEW_MAT --> TRANSFORM
    TRANSFORM --> DRAW_AXES
    TRANSFORM --> DRAW_PLANES
    DRAW_AXES --> Z_SORTING
    DRAW_PLANES --> Z_SORTING
    
    HIT_TEST --> CAM_UPDATE
    CAM_UPDATE --> AXIS_ALIGN
    CAM_ORI --> CAM_UPDATE
    CAM_POS --> CAM_UPDATE
    CAM_DIST --> CAM_UPDATE
```

**Sources:** [src/imgui_widgets.cpp:351-566](), [src/imgui_widgets.h:6-14]()

### Theme and Styling Components

VIAMD provides a custom dark theme and styling utilities to maintain visual consistency across the interface.

| Function | Purpose | File Reference |
|----------|---------|----------------|
| `init_theme` | Sets up dark color scheme | [src/imgui_widgets.cpp:191-243]() |
| `ColorEdit3Minimal` | Minimal color picker without labels | [src/imgui_widgets.cpp:318-323]() |
| `ColorEdit4Minimal` | Minimal RGBA color picker | [src/imgui_widgets.cpp:325-330]() |
| `DrawCheckerboard` | Draws checkerboard pattern | [src/imgui_widgets.cpp:332-349]() |
| `DeleteButton` | Red-styled delete button | [src/imgui_widgets.cpp:300-307]() |

**Sources:** [src/imgui_widgets.cpp:191-349](), [src/imgui_widgets.h:21-53]()

### Layout and Window Management

Custom window management functions provide specialized layouts for molecular visualization.

```mermaid
graph LR
    subgraph "Window Management Functions"
        DOCKSPACE["CreateDockspace"]
        CANVAS_BEGIN["BeginCanvas"]
        CANVAS_END["EndCanvas"]
    end
    
    subgraph "Dockspace Configuration"
        VIEWPORT["ImGuiViewport"]
        WINDOW_FLAGS["Window Flags"]
        DOCK_FLAGS["Dock Node Flags"]
    end
    
    subgraph "Canvas Configuration"
        INPUT_CONTROL["Input Control"]
        OVERLAY["Overlay Rendering"]
        TRANSPARENT["Transparent Background"]
    end
    
    DOCKSPACE --> VIEWPORT
    DOCKSPACE --> WINDOW_FLAGS
    DOCKSPACE --> DOCK_FLAGS
    
    CANVAS_BEGIN --> INPUT_CONTROL
    CANVAS_BEGIN --> OVERLAY
    CANVAS_BEGIN --> TRANSPARENT
    CANVAS_END --> CANVAS_BEGIN
```

**Sources:** [src/imgui_widgets.cpp:245-294](), [src/imgui_widgets.h:22-24]()

## Custom ImPlot Extensions

VIAMD extends ImPlot with specialized plotting widgets for molecular data visualization and analysis.

### Drag Range Widget

The `DragRangeX` widget provides interactive range selection on plot axes, commonly used for time series analysis and data filtering.

```mermaid
graph TB
    subgraph "DragRangeX Components"
        LINE_DRAG["DragLineX Handles"]
        RANGE_BAR["Draggable Range Bar"]
        VISUAL_FEEDBACK["Visual Range Display"]
        LABEL_DISPLAY["Range Value Labels"]
    end
    
    subgraph "Interaction Modes"
        HANDLE_DRAG["Individual Handle Dragging"]
        BAR_DRAG["Entire Range Dragging"]
        CONSTRAINT["Min/Max Constraints"]
    end
    
    subgraph "ImPlotDragRangeStyle"
        LINE_COL["line_col: ImVec4"]
        RANGE_COL["range_col: ImVec4"]
        LINE_THICK["line_thickness: float"]
    end
    
    LINE_DRAG --> HANDLE_DRAG
    RANGE_BAR --> BAR_DRAG
    HANDLE_DRAG --> CONSTRAINT
    BAR_DRAG --> CONSTRAINT
    
    LINE_COL --> VISUAL_FEEDBACK
    RANGE_COL --> VISUAL_FEEDBACK
    LINE_THICK --> VISUAL_FEEDBACK
```

**Sources:** [src/implot_widgets.cpp:6-130](), [src/implot_widgets.h:3-21]()

### Colormap Selection Widget

The `ColormapSelection` widget provides a dropdown interface for choosing from available ImPlot colormaps.

| Function | Purpose | Return Type |
|----------|---------|-------------|
| `ColormapSelection` | Dropdown colormap selector | `bool` |
| `ColormapQualitative` | Check if colormap is qualitative | `bool` |
| `SyncAxesY` | Synchronize Y-axis ranges | `void` |

**Sources:** [src/implot_widgets.cpp:132-177](), [src/implot_widgets.h:23-27]()

## Image Export Utilities

VIAMD provides image export functionality using the STB image library for saving visualization results in multiple formats.

```mermaid
graph LR
    subgraph "Image Export Functions"
        WRITE_JPG["image_write_jpg"]
        WRITE_PNG["image_write_png"]
        WRITE_BMP["image_write_bmp"]
    end
    
    subgraph "STB Integration"
        STB_JPG["stbi_write_jpg_to_func"]
        STB_PNG["stbi_write_png_to_func"]
        STB_BMP["stbi_write_bmp_to_func"]
    end
    
    subgraph "File I/O"
        MD_FILE["md_file_o"]
        WRITE_FUNC["write_func callback"]
        OPEN_FILE["open_file helper"]
    end
    
    WRITE_JPG --> STB_JPG
    WRITE_PNG --> STB_PNG
    WRITE_BMP --> STB_BMP
    
    STB_JPG --> WRITE_FUNC
    STB_PNG --> WRITE_FUNC
    STB_BMP --> WRITE_FUNC
    
    WRITE_FUNC --> MD_FILE
    OPEN_FILE --> MD_FILE
```

### Image Format Support

| Format | Function | Parameters | Quality Control |
|--------|----------|------------|-----------------|
| JPEG | `image_write_jpg` | `filename, rgba, width, height, quality` | 0-100 quality |
| PNG | `image_write_png` | `filename, rgba, width, height` | Lossless |
| BMP | `image_write_bmp` | `filename, rgba, width, height` | Uncompressed |

All functions expect 32-bit RGBA pixel data (8 bits per channel) and return `bool` success status.

**Sources:** [src/image.cpp:1-52](), [src/image.h:1-10]()

## Native File Dialog Integration

VIAMD integrates native file dialogs through a cross-platform wrapper that provides system-appropriate file selection interfaces.

```mermaid
graph TB
    subgraph "Platform Support"
        WINDOWS["Windows\nnfd_win.cpp"]
        MACOS["macOS\nnfd_cocoa.m"]
        LINUX_GTK["Linux GTK\nnfd_gtk.c"]
        LINUX_ZENITY["Linux Zenity\nnfd_zenity.c"]
    end
    
    subgraph "Build Configuration"
        CMAKE_DETECT["Platform Detection"]
        GTK_OPTION["NATIVEFILEDIALOG_USE_GTK"]
        LIBRARY_DEPS["Library Dependencies"]
    end
    
    subgraph "Common Interface"
        NFD_COMMON["nfd_common.c"]
        NFD_HEADER["nfd.h"]
    end
    
    CMAKE_DETECT --> WINDOWS
    CMAKE_DETECT --> MACOS
    CMAKE_DETECT --> GTK_OPTION
    
    GTK_OPTION --> LINUX_GTK
    GTK_OPTION --> LINUX_ZENITY
    
    WINDOWS --> NFD_COMMON
    MACOS --> NFD_COMMON
    LINUX_GTK --> NFD_COMMON
    LINUX_ZENITY --> NFD_COMMON
    
    NFD_COMMON --> NFD_HEADER
```

### Platform-Specific Dependencies

| Platform | Implementation | Dependencies |
|----------|----------------|--------------|
| Windows | `nfd_win.cpp` | Win32 API |
| macOS | `nfd_cocoa.m` | AppKit Framework |
| Linux (GTK) | `nfd_gtk.c` | GTK3 libraries |
| Linux (Zenity) | `nfd_zenity.c` | Zenity command |

The build system automatically selects the appropriate implementation based on the target platform and available dependencies.

**Sources:** [ext/nativefiledialog/CMakeLists.txt:1-73](), [ext/nativefiledialog/cmake/FindGTK3.cmake:1-567]()

## Utility Functions and Helpers

Additional utility functions support the custom UI components with common operations and state management.

| Function | Purpose | Parameters |
|----------|---------|------------|
| `PushDisabled/PopDisabled` | Disable UI elements | None |
| `InputQuery` | Validated input field | `label, buf, is_valid, err_text` |
| `PushInvalid/PopInvalid` | Invalid state styling | None |

These utilities provide consistent behavior across the VIAMD interface for common UI patterns like input validation and element state management.

**Sources:** [src/imgui_widgets.cpp:309-316](), [src/imgui_widgets.h:26-43]()

---