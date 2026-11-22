# User Interface Framework

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [ext/ImGuiColorTextEdit/CMakeLists.txt](ext/ImGuiColorTextEdit/CMakeLists.txt)
- [ext/imgui/CMakeLists.txt](ext/imgui/CMakeLists.txt)
- [ext/imgui/docs/CHANGELOG.txt](ext/imgui/docs/CHANGELOG.txt)
- [ext/imgui/docs/README.md](ext/imgui/docs/README.md)
- [ext/imgui/imgui.cpp](ext/imgui/imgui.cpp)
- [ext/imgui/imgui.h](ext/imgui/imgui.h)
- [ext/imgui/imgui_demo.cpp](ext/imgui/imgui_demo.cpp)
- [ext/imgui/imgui_draw.cpp](ext/imgui/imgui_draw.cpp)
- [ext/imgui/imgui_internal.h](ext/imgui/imgui_internal.h)
- [ext/imgui/imgui_tables.cpp](ext/imgui/imgui_tables.cpp)
- [ext/imgui/imgui_widgets.cpp](ext/imgui/imgui_widgets.cpp)
- [ext/imgui/misc/freetype/imgui_freetype.cpp](ext/imgui/misc/freetype/imgui_freetype.cpp)
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



This document covers VIAMD's comprehensive user interface framework built on top of Dear ImGui. It includes the core ImGui integration, custom widget system, plotting capabilities, file dialogs, and text editing components that provide the interactive interface for molecular visualization and analysis.

For information about the main application event system that drives UI updates, see [Event System](#2.3). For details about the graphics rendering pipeline that displays the UI, see [Graphics and Visualization Pipeline](#3).

## Core ImGui Integration

VIAMD's user interface is built around Dear ImGui, an immediate-mode GUI library that provides efficient, code-driven UI creation. The core integration handles window management, input processing, and rendering coordination.

### ImGui Library Structure

```mermaid
graph TD
    subgraph "Core ImGui Library"
        ImGuiCore["imgui.cpp<br/>Core functionality"]
        ImGuiWidgets["imgui_widgets.cpp<br/>Standard widgets"]
        ImGuiDraw["imgui_draw.cpp<br/>Drawing primitives"]
        ImGuiDemo["imgui_demo.cpp<br/>Demo and examples"]
        ImGuiTables["imgui_tables.cpp<br/>Table system"]
    end
    
    subgraph "VIAMD Extensions"
        CustomWidgets["src/imgui_widgets.cpp<br/>Custom widget implementations"]
        PlotWidgets["src/implot_widgets.cpp<br/>Custom plotting widgets"]
        ImageUtils["src/image.cpp<br/>Image export utilities"]
    end
    
    subgraph "Additional Libraries"
        ImPlot["ext/implot/<br/>Plotting library"]
        TextEditor["ext/ImGuiColorTextEdit/<br/>Text editor component"]
        FileDialog["ext/nativefiledialog/<br/>Native file dialogs"]
    end
    
    ImGuiCore --> CustomWidgets
    ImGuiWidgets --> CustomWidgets
    ImGuiDraw --> CustomWidgets
    ImPlot --> PlotWidgets
    CustomWidgets --> ImageUtils
```

**Application Layout Management**

The framework provides specialized layout functions for creating the main application structure:

- `CreateDockspace()` - Creates an invisible full-viewport dockspace for window management
- `BeginCanvas()` / `EndCanvas()` - Creates overlay canvases for rendering on top of the viewport
- Custom theme initialization through `init_theme()` with dark color scheme optimized for molecular visualization

Sources: [src/imgui_widgets.cpp:245-294](), [src/imgui_widgets.h:16-59](), [ext/imgui/CMakeLists.txt:1-31]()

## Custom Widget System

VIAMD extends ImGui with specialized widgets tailored for molecular analysis workflows, providing enhanced interactivity and domain-specific controls.

### Widget Architecture

```mermaid
graph LR
    subgraph "Standard ImGui Widgets"
        Button["Button"]
        Slider["Slider"] 
        Input["InputText"]
        ColorEdit["ColorEdit"]
    end
    
    subgraph "VIAMD Custom Widgets"
        RangeSlider["RangeSliderFloat<br/>Dual-handle range selection"]
        DeleteBtn["DeleteButton<br/>Styled delete button"]
        CoordWidget["DrawCoordinateSystemWidget<br/>3D coordinate system"]
        ColorMinimal["ColorEdit3Minimal/4Minimal<br/>Compact color pickers"]
        InputQuery["InputQuery<br/>Validated input fields"]
    end
    
    subgraph "State Management"
        PushDisabled["PushDisabled/PopDisabled<br/>Widget state control"]
        PushInvalid["PushInvalid/PopInvalid<br/>Validation styling"]
    end
    
    Slider --> RangeSlider
    Button --> DeleteBtn
    Input --> InputQuery
    ColorEdit --> ColorMinimal
    
    RangeSlider --> PushDisabled
    InputQuery --> PushInvalid
```

**Core Custom Widgets:**

- **Range Slider**: `RangeSliderFloat()` provides dual-handle range selection with wheel scrolling support and drag behavior for both individual handles and range translation
- **Coordinate System Widget**: `DrawCoordinateSystemWidget()` renders an interactive 3D coordinate system gizmo with camera orientation control and axis highlighting
- **Delete Button**: `DeleteButton()` provides consistently styled deletion controls with distinctive red coloring
- **Minimal Color Editors**: Compact color pickers without labels or input fields for space-efficient interfaces

**Input Validation System:**

The `InputQuery()` function combines text input with visual validation feedback, automatically styling invalid inputs with colored backgrounds and providing tooltip error messages.

Sources: [src/imgui_widgets.cpp:13-189](), [src/imgui_widgets.cpp:300-566](), [src/imgui_widgets.h:16-59]()

## Plotting and Data Visualization  

ImPlot integration provides sophisticated plotting capabilities for molecular analysis data, enhanced with custom widgets for interactive data exploration.

### Plot Widget Extensions

```mermaid
graph TD
    subgraph "ImPlot Core"
        ImPlotBase["implot.cpp<br/>Core plotting functionality"]
        PlotItems["implot_items.cpp<br/>Plot item types"]
        PlotDemo["implot_demo.cpp<br/>Examples and demos"]
    end
    
    subgraph "VIAMD Plot Widgets"
        DragRange["DragRangeX<br/>Interactive range selection"]
        ColormapSel["ColormapSelection<br/>Colormap chooser widget"]
        AxisSync["SyncAxesY<br/>Multi-axis synchronization"]
        QualCheck["ColormapQualitative<br/>Colormap type detection"]
    end
    
    subgraph "Plot Features"
        RangeBar["Range bar dragging"]
        RangeLines["Range line handles"]
        RangeLabel["Dynamic range labels"]
        ColorPicker["Colormap popup selector"]
    end
    
    ImPlotBase --> DragRange
    ImPlotBase --> ColormapSel
    ImPlotBase --> AxisSync
    
    DragRange --> RangeBar
    DragRange --> RangeLines
    DragRange --> RangeLabel
    ColormapSel --> ColorPicker
```

**Interactive Range Selection:**

`DragRangeX()` provides sophisticated range selection within plots with:
- Individual handle dragging for range endpoints
- Unified range translation by dragging the range bar
- Visual feedback with highlighted range areas and dynamic labels
- Configurable styling through `ImPlotDragRangeStyle`

**Colormap Management:**

`ColormapSelection()` creates popup-based colormap choosers that display available colormaps as preview buttons, enabling quick colormap switching for data visualization.

**Axis Synchronization:**

`SyncAxesY()` synchronizes multiple Y-axes to use consistent ranges, essential for comparative molecular analysis plots.

Sources: [src/implot_widgets.cpp:1-179](), [src/implot_widgets.h:1-30](), [ext/implot/CMakeLists.txt:1-24]()

## File Operations and Dialogs

The framework integrates native file dialogs for seamless file operations across different operating systems, along with image export capabilities.

### File Dialog Integration

```mermaid
graph LR
    subgraph "Platform Implementations"
        WinDialog["nfd_win.cpp<br/>Windows native dialogs"]
        MacDialog["nfd_cocoa.m<br/>macOS native dialogs"] 
        LinuxGTK["nfd_gtk.c<br/>Linux GTK dialogs"]
        LinuxZen["nfd_zenity.c<br/>Linux Zenity fallback"]
    end
    
    subgraph "Common Interface"
        NFDCommon["nfd_common.c<br/>Cross-platform API"]
    end
    
    subgraph "Image Export"
        ImageCore["src/image.cpp<br/>Image writing functions"]
        STBWrite["stb_image_write<br/>Format encoding"]
    end
    
    WinDialog --> NFDCommon
    MacDialog --> NFDCommon  
    LinuxGTK --> NFDCommon
    LinuxZen --> NFDCommon
    
    NFDCommon --> ImageCore
    ImageCore --> STBWrite
```

**Cross-Platform File Dialogs:**

The native file dialog system automatically selects the appropriate implementation:
- Windows: Win32 native dialogs
- macOS: Cocoa native dialogs  
- Linux: GTK3 dialogs with Zenity fallback

**Image Export System:**

The image export functionality supports multiple formats:
- `image_write_jpg()` - JPEG with quality control
- `image_write_png()` - PNG with transparency support
- `image_write_bmp()` - Bitmap format

All functions use a streaming interface that works with VIAMD's file I/O system.

Sources: [ext/nativefiledialog/CMakeLists.txt:1-73](), [src/image.cpp:1-52](), [src/image.h:1-10]()

## Text Editor Integration

VIAMD incorporates a sophisticated text editor component for script editing and text-based molecular data manipulation.

### Text Editor Architecture

```mermaid
graph TD
    subgraph "ImGuiColorTextEdit Library"
        TextEditorCore["TextEditor.cpp<br/>Core editor implementation"]
        TextEditorHeader["TextEditor.h<br/>Editor interface"]
    end
    
    subgraph "Editor Features"
        SyntaxHL["Syntax highlighting"]
        CodeFold["Code folding"]
        LineNum["Line numbering"]
        SearchReplace["Search and replace"]
        Undo["Undo/redo system"]
    end
    
    subgraph "Language Support"
        CPP["C++ syntax"]
        Python["Python syntax"]  
        GLSL["GLSL shader syntax"]
        Generic["Generic text"]
    end
    
    TextEditorCore --> SyntaxHL
    TextEditorCore --> CodeFold
    TextEditorCore --> LineNum
    TextEditorCore --> SearchReplace
    TextEditorCore --> Undo
    
    SyntaxHL --> CPP
    SyntaxHL --> Python
    SyntaxHL --> GLSL
    SyntaxHL --> Generic
```

The text editor provides a full-featured editing environment within the ImGui framework, supporting:
- Multi-language syntax highlighting
- Advanced text editing operations
- Integration with VIAMD's script execution system
- Customizable color schemes that match the application theme

Sources: [ext/ImGuiColorTextEdit/CMakeLists.txt:1-21](), [ext/ImGuiColorTextEdit/TextEditor.h](), [ext/ImGuiColorTextEdit/TextEditor.cpp]()

## Styling and Theming

VIAMD implements a consistent dark theme optimized for molecular visualization work, with specialized styling for different widget states and validation feedback.

### Theme System

```mermaid
graph LR
    subgraph "Color Scheme"
        BaseColors["Base window colors<br/>Dark backgrounds"]
        WidgetColors["Widget colors<br/>Blue accent theme"]
        TextColors["Text colors<br/>High contrast white"]
        StateColors["State colors<br/>Hover, active, disabled"]
    end
    
    subgraph "Specialized Styling"
        DeleteStyle["Delete button styling<br/>Red color variants"]
        InvalidStyle["Invalid input styling<br/>Red background tint"]
        DisabledStyle["Disabled widget styling<br/>Alpha transparency"]
        ValidationStyle["Validation feedback<br/>Color and tooltip"]
    end
    
    subgraph "Theme Functions"
        InitTheme["init_theme()<br/>Core theme setup"]
        PushDisabled["PushDisabled/PopDisabled<br/>State management"]
        PushInvalid["PushInvalid/PopInvalid<br/>Validation styling"]
    end
    
    BaseColors --> InitTheme
    WidgetColors --> InitTheme
    TextColors --> InitTheme
    StateColors --> InitTheme
    
    InitTheme --> DeleteStyle
    PushDisabled --> DisabledStyle
    PushInvalid --> InvalidStyle
```

**Core Theme Implementation:**

The `init_theme()` function establishes a comprehensive dark theme with:
- Dark gray/black background colors for reduced eye strain
- Blue accent colors for interactive elements
- High contrast white text for readability
- Consistent hover and active state feedback

**Dynamic State Styling:**

- `PushDisabled()` / `PopDisabled()` - Temporarily disables widgets with visual feedback
- `PushInvalid()` / `PopInvalid()` - Applies error styling to invalid inputs
- `DeleteButton()` - Uses distinctive red coloring for destructive actions

Sources: [src/imgui_widgets.cpp:191-243](), [src/imgui_widgets.cpp:296-330](), [src/imgui_widgets.h:26-50]()

## UI Framework Event Flow

The UI framework integrates with VIAMD's event system to provide responsive, real-time updates to the molecular visualization interface.

### Event Integration Architecture

```mermaid
graph TD
    subgraph "Application Events"
        FrameTick["ViamdFrameTick<br/>Per-frame updates"]
        TopologyInit["ViamdTopologyInit<br/>Molecule loading"]
        WindowDraw["ViamdWindowDrawMenu<br/>Menu rendering"]
    end
    
    subgraph "UI Framework Response"
        ImGuiNewFrame["ImGui::NewFrame()<br/>Input processing"]
        WidgetUpdate["Widget state updates"]
        PlotRefresh["Plot data refresh"]
        MenuUpdate["Menu state updates"]
    end
    
    subgraph "User Interactions"
        WidgetEvents["Widget interactions"]
        PlotEvents["Plot manipulations"]
        FileEvents["File dialog operations"]
        TextEvents["Text editor changes"]
    end
    
    subgraph "Application Response"
        StateChanges["Application state changes"]
        DataUpdates["Molecular data updates"]
        ViewChanges["Visualization updates"]
    end
    
    FrameTick --> ImGuiNewFrame
    TopologyInit --> WidgetUpdate
    WindowDraw --> MenuUpdate
    
    ImGuiNewFrame --> WidgetEvents
    WidgetUpdate --> PlotEvents
    MenuUpdate --> FileEvents
    
    WidgetEvents --> StateChanges
    PlotEvents --> DataUpdates
    FileEvents --> ViewChanges
    TextEvents --> StateChanges
```

The UI framework operates in tight integration with the main application loop, processing user inputs each frame and triggering appropriate application responses through the event system. This ensures that UI interactions immediately reflect in the molecular visualization and analysis components.

Sources: [src/main.cpp](), [src/event.cpp](), [src/imgui_widgets.cpp:245-294]()

---