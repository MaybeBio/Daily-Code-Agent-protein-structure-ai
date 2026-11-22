# ImGui Core and Widgets

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

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

</details>



This document covers the Dear ImGui immediate-mode graphical user interface integration within VIAMD, including the core widget system, application integration patterns, and the extended widget ecosystem. This encompasses the foundational GUI framework that powers all interactive elements in VIAMD's user interface.

For information about custom UI components and plotting extensions, see [Custom UI Components](#5.2). For text editing capabilities, see [Text Editor and Script Interface](#5.3).

## Core ImGui Architecture

VIAMD integrates Dear ImGui v1.90.5 as its primary GUI framework, providing an immediate-mode interface paradigm where UI elements are created and managed through function calls each frame rather than through persistent widget objects.

### ImGui Context and Lifecycle

The ImGui system operates through a global context that manages all GUI state, input handling, and rendering data. The core architecture revolves around frame-based processing where the entire UI is reconstructed each frame.

```mermaid
graph TB
    subgraph "ImGui Core System"
        CTX["ImGuiContext"]
        IO["ImGuiIO"]
        STYLE["ImGuiStyle"]
        DRAWDATA["ImDrawData"]
    end
    
    subgraph "Frame Lifecycle"
        NEWFRAME["NewFrame()"]
        WIDGETS["Widget Calls"]
        RENDER["Render()"]
        ENDFRAME["EndFrame()"]
    end
    
    subgraph "Application Integration"
        VIAMD_MAIN["VIAMD Main Loop"]
        EVENT_SYS["Event System"]
        BACKENDS["Platform Backends"]
    end
    
    CTX --> IO
    CTX --> STYLE
    CTX --> DRAWDATA
    
    NEWFRAME --> WIDGETS
    WIDGETS --> RENDER
    RENDER --> ENDFRAME
    ENDFRAME --> NEWFRAME
    
    VIAMD_MAIN --> NEWFRAME
    EVENT_SYS --> IO
    BACKENDS --> IO
    DRAWDATA --> BACKENDS

    WIDGETS --> CTX
```

**Sources:** [ext/imgui/imgui.h:308-311](), [ext/imgui/imgui.cpp:4140-4180](), [ext/imgui/imgui_internal.h:1875-1950]()

### Core Data Structures

The ImGui system is built around several key data structures that manage state and rendering:

| Structure | Purpose | Key Members |
|-----------|---------|-------------|
| `ImGuiContext` | Global state container | `IO`, `Style`, `Windows`, `Tables`, `DrawData` |
| `ImGuiIO` | Input/output interface | `MousePos`, `KeysDown`, `DisplaySize`, `DeltaTime` |
| `ImGuiStyle` | Visual styling parameters | `Colors[]`, `FramePadding`, `ItemSpacing` |
| `ImGuiWindow` | Window state management | `Pos`, `Size`, `DrawList`, `IDStack` |
| `ImDrawData` | Rendering command output | `CmdLists[]`, `DisplayPos`, `DisplaySize` |

**Sources:** [ext/imgui/imgui.h:2015-2118](), [ext/imgui/imgui_internal.h:1875-2100]()

## Widget System Overview

The ImGui widget system follows an immediate-mode paradigm where widgets are stateless functions that return values indicating user interaction. Each widget function handles input processing, state management, and rendering in a single call.

### Widget Function Patterns

```mermaid
graph LR
    subgraph "Widget Function Flow"
        INPUT["Input Parameters"]
        STATE["Internal State Management"]
        RENDER["Rendering Commands"]
        OUTPUT["Return Value/Modified State"]
    end
    
    subgraph "Core Widget Categories"
        TEXT["Text Widgets<br/>Text(), TextColored()"]
        BUTTONS["Button Widgets<br/>Button(), SmallButton()"]
        INPUTS["Input Widgets<br/>InputText(), DragFloat()"]
        SELECTS["Selection Widgets<br/>Combo(), Listbox()"]
        LAYOUT["Layout Widgets<br/>BeginChild(), Columns()"]
    end
    
    INPUT --> STATE
    STATE --> RENDER
    RENDER --> OUTPUT
    
    TEXT --> INPUT
    BUTTONS --> INPUT
    INPUTS --> INPUT
    SELECTS --> INPUT
    LAYOUT --> INPUT
```

**Sources:** [ext/imgui/imgui_widgets.cpp:148-400](), [ext/imgui/imgui_widgets.cpp:693-748]()

### Widget State Management

ImGui manages widget state through a combination of ID-based tracking and immediate return values. The system uses string IDs and ID stacks to maintain state between frames while keeping the API stateless.

```mermaid
graph TB
    subgraph "ID Generation System"
        LABEL["Label String"]
        IDSTACK["ID Stack"]
        HASH["Hash Function"]
        WIDGETID["Widget ID"]
    end
    
    subgraph "State Storage"
        STORAGE["ImGuiStorage"]
        WINDOW_STATE["Window State"]
        CONTEXT_STATE["Context State"]
    end
    
    subgraph "Widget Behavior"
        BUTTON_BEHAVIOR["ButtonBehavior()"]
        INPUT_BEHAVIOR["InputText Behavior"]
        DRAG_BEHAVIOR["Drag/Slider Behavior"]
    end
    
    LABEL --> HASH
    IDSTACK --> HASH
    HASH --> WIDGETID
    
    WIDGETID --> STORAGE
    STORAGE --> WINDOW_STATE
    WINDOW_STATE --> CONTEXT_STATE
    
    WIDGETID --> BUTTON_BEHAVIOR
    WIDGETID --> INPUT_BEHAVIOR
    WIDGETID --> DRAG_BEHAVIOR
```

**Sources:** [ext/imgui/imgui_widgets.cpp:483-691](), [ext/imgui/imgui_internal.h:2900-3000]()

## Application Integration

VIAMD integrates ImGui through a frame-based rendering loop that coordinates with the application's event system and graphics pipeline.

### Frame Processing Integration

The ImGui integration follows a standard pattern where each frame begins with input collection, processes UI calls, and ends with command list generation for rendering.

```mermaid
sequenceDiagram
    participant APP as "VIAMD Application"
    participant IMGUI as "ImGui Context"
    participant BACKENDS as "Platform Backends"
    participant RENDER as "Renderer"
    
    APP->>BACKENDS: Update Input State
    BACKENDS->>IMGUI: io.AddMousePosEvent()
    BACKENDS->>IMGUI: io.AddKeyEvent()
    
    APP->>IMGUI: NewFrame()
    IMGUI->>IMGUI: Process Input
    IMGUI->>IMGUI: Update State
    
    APP->>APP: UI Function Calls
    APP->>IMGUI: Begin(), Button(), etc.
    
    APP->>IMGUI: Render()
    IMGUI->>IMGUI: Generate DrawData
    
    APP->>RENDER: Process DrawData
    RENDER->>RENDER: Submit GPU Commands
```

**Sources:** [ext/imgui/imgui.cpp:4140-4220](), [ext/imgui/imgui.cpp:4580-4650]()

### Window and Layout Management

ImGui provides a hierarchical window system where the main application creates windows that contain widgets. VIAMD uses this for organizing different UI panels and tools.

```mermaid
graph TB
    subgraph "Window Hierarchy"
        MAIN["Main Application Window"]
        TOOL1["Tool Window 1"]
        TOOL2["Tool Window 2"]
        POPUP["Popup Windows"]
    end
    
    subgraph "Layout System"
        BEGINEND["Begin()/End() Pairs"]
        CHILD["BeginChild()/EndChild()"]
        GROUPS["BeginGroup()/EndGroup()"]
        COLUMNS["Columns()/NextColumn()"]
    end
    
    subgraph "Widget Positioning"
        CURSOR["Cursor Position"]
        SPACING["Item Spacing"]
        ALIGNMENT["Text Alignment"]
        SIZING["Auto/Manual Sizing"]
    end
    
    MAIN --> TOOL1
    MAIN --> TOOL2
    MAIN --> POPUP
    
    BEGINEND --> CHILD
    CHILD --> GROUPS
    GROUPS --> COLUMNS
    
    CURSOR --> SPACING
    SPACING --> ALIGNMENT
    ALIGNMENT --> SIZING
```

**Sources:** [ext/imgui/imgui.cpp:6100-6300](), [ext/imgui/imgui_widgets.cpp:2500-2700]()

## Widget Categories and Usage Patterns

ImGui provides a comprehensive set of widgets organized into functional categories. Each category serves specific interaction patterns common in technical interfaces.

### Text and Display Widgets

Text widgets handle static and formatted text display with various styling options.

| Widget Function | Purpose | Return Type |
|----------------|---------|-------------|
| `Text()` | Basic text display | `void` |
| `TextColored()` | Colored text display | `void` |
| `TextWrapped()` | Word-wrapped text | `void` |
| `BulletText()` | Bulleted text items | `void` |
| `LabelText()` | Label-value pairs | `void` |

**Sources:** [ext/imgui/imgui_widgets.cpp:148-400]()

### Input and Control Widgets

Input widgets provide interactive controls for data entry and manipulation.

```mermaid
graph TB
    subgraph "Input Widget Types"
        TEXT_INPUT["InputText<br/>InputTextMultiline"]
        NUMERIC["DragFloat, SliderInt<br/>InputFloat, InputInt"]
        COLOR["ColorEdit4<br/>ColorPicker4"]
        BOOL["Checkbox<br/>RadioButton"]
    end
    
    subgraph "Behavior Flags"
        FLAGS["ImGuiInputTextFlags"]
        DRAG_FLAGS["ImGuiSliderFlags"]
        COLOR_FLAGS["ImGuiColorEditFlags"]
    end
    
    subgraph "Data Validation"
        CALLBACKS["Input Callbacks"]
        CONSTRAINTS["Value Constraints"]
        FORMATTING["Display Formatting"]
    end
    
    TEXT_INPUT --> FLAGS
    NUMERIC --> DRAG_FLAGS
    COLOR --> COLOR_FLAGS
    
    FLAGS --> CALLBACKS
    DRAG_FLAGS --> CONSTRAINTS
    COLOR_FLAGS --> FORMATTING
```

**Sources:** [ext/imgui/imgui_widgets.cpp:4000-5500](), [ext/imgui/imgui_widgets.cpp:2800-3500]()

### Selection and Navigation Widgets

Selection widgets handle choosing from sets of options and navigation between interface elements.

| Widget Category | Widgets | Use Cases |
|----------------|---------|-----------|
| **Buttons** | `Button()`, `SmallButton()`, `InvisibleButton()` | Actions, triggers |
| **Selection** | `Selectable()`, `ListBox()`, `Combo()` | Single/multi selection |
| **Trees** | `TreeNode()`, `CollapsingHeader()` | Hierarchical data |
| **Menus** | `BeginMenu()`, `MenuItem()` | Command organization |
| **Tables** | `BeginTable()`, `TableNextColumn()` | Tabular data display |

**Sources:** [ext/imgui/imgui_widgets.cpp:693-1500](), [ext/imgui/imgui_tables.cpp:300-800]()

## Font and Rendering System

ImGui uses a custom font atlas system that supports both raster and vector fonts through multiple rendering backends.

### Font Atlas Architecture

```mermaid
graph TB
    subgraph "Font Loading"
        FONT_CONFIG["ImFontConfig"]
        FONT_DATA["Font Data (TTF/OTF)"]
        GLYPH_RANGES["Glyph Ranges"]
    end
    
    subgraph "Font Atlas"
        ATLAS["ImFontAtlas"]
        TEXTURE["Font Texture"]
        FONTS["ImFont Objects"]
    end
    
    subgraph "Rendering Backend"
        STB["STB TrueType"]
        FREETYPE["FreeType (Optional)"]
        RASTERIZER["Glyph Rasterizer"]
    end
    
    subgraph "Text Rendering"
        TEXT_CALC["Text Size Calculation"]
        GLYPH_CACHE["Glyph Cache Lookup"]
        DRAW_COMMANDS["Draw Command Generation"]
    end
    
    FONT_CONFIG --> ATLAS
    FONT_DATA --> ATLAS
    GLYPH_RANGES --> ATLAS
    
    ATLAS --> TEXTURE
    ATLAS --> FONTS
    
    STB --> RASTERIZER
    FREETYPE --> RASTERIZER
    RASTERIZER --> ATLAS
    
    FONTS --> TEXT_CALC
    FONTS --> GLYPH_CACHE
    GLYPH_CACHE --> DRAW_COMMANDS
```

**Sources:** [ext/imgui/imgui_draw.cpp:1500-2000](), [ext/imgui/misc/freetype/imgui_freetype.cpp:150-300]()

### FreeType Integration

VIAMD supports enhanced font rendering through FreeType integration, providing improved glyph quality and additional font format support.

**Sources:** [ext/imgui/misc/freetype/imgui_freetype.cpp:177-253]()

## Extension Ecosystem

The ImGui ecosystem in VIAMD includes several specialized extensions that enhance the core widget functionality.

### Available Extensions

```mermaid
graph TB
    subgraph "Core ImGui"
        CORE["ext/imgui/"]
        WIDGETS["Standard Widgets"]
        TABLES["Tables System"]
    end
    
    subgraph "Plotting Extensions"
        IMPLOT["ext/implot/<br/>Advanced Plotting"]
        PLOTS["PlotLines(), PlotHistogram()"]
    end
    
    subgraph "Text Editing"
        EDITOR["ext/ImGuiColorTextEdit/<br/>Syntax Highlighting"]
        INPUT_TEXT["InputText Extensions"]
    end
    
    subgraph "Custom Widgets"
        VIAMD_WIDGETS["src/imgui_widgets.cpp<br/>VIAMD-specific UI"]
        IMAGE_UTILS["Image Display Utils"]
        FILE_DIALOGS["Native File Dialogs"]
    end
    
    CORE --> WIDGETS
    CORE --> TABLES
    
    PLOTS --> IMPLOT
    INPUT_TEXT --> EDITOR
    WIDGETS --> VIAMD_WIDGETS
    
    IMPLOT --> VIAMD_WIDGETS
    EDITOR --> VIAMD_WIDGETS
```

**Sources:** Based on architectural diagrams and file structure analysis

### Integration Patterns

Extensions follow consistent patterns for integration with the core ImGui system, typically providing additional widget functions that maintain the immediate-mode paradigm while adding specialized functionality.

**Sources:** [ext/imgui/imgui_demo.cpp:2000-3000]() for extension examples and patterns

---