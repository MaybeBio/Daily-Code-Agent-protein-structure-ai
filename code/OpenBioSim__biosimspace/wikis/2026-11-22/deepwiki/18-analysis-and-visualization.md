# Analysis and Visualization

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [python/BioSimSpace/Gateway/__init__.py](python/BioSimSpace/Gateway/__init__.py)
- [python/BioSimSpace/Gateway/_resources.py](python/BioSimSpace/Gateway/_resources.py)
- [python/BioSimSpace/MD/_md.py](python/BioSimSpace/MD/_md.py)
- [python/BioSimSpace/Notebook/__init__.py](python/BioSimSpace/Notebook/__init__.py)
- [python/BioSimSpace/Notebook/_plot.py](python/BioSimSpace/Notebook/_plot.py)
- [python/BioSimSpace/Notebook/_view.py](python/BioSimSpace/Notebook/_view.py)
- [python/BioSimSpace/Sandpit/Exscientia/Notebook/_plot.py](python/BioSimSpace/Sandpit/Exscientia/Notebook/_plot.py)
- [python/BioSimSpace/Sandpit/Exscientia/Trajectory/_trajectory.py](python/BioSimSpace/Sandpit/Exscientia/Trajectory/_trajectory.py)
- [python/BioSimSpace/Sandpit/Exscientia/__init__.py](python/BioSimSpace/Sandpit/Exscientia/__init__.py)
- [python/BioSimSpace/Trajectory/_trajectory.py](python/BioSimSpace/Trajectory/_trajectory.py)
- [python/BioSimSpace/__init__.py](python/BioSimSpace/__init__.py)

</details>



This page covers BioSimSpace's comprehensive analysis and visualization capabilities for molecular dynamics simulations. The system provides tools for trajectory analysis, interactive molecular visualization, and scientific plotting. For information about the simulation protocols that generate data for analysis, see [Simulation Protocols](#4.1). For details about free energy analysis specifically, see [Free Energy Calculations](#5).

## Overview

BioSimSpace's analysis and visualization system provides a unified interface for extracting insights from molecular simulation data. The system supports multiple analysis backends and offers both programmatic analysis tools and interactive visualization capabilities optimized for Jupyter notebook environments.

```mermaid
graph TB
    subgraph "Simulation Data Sources"
        PROC["Process Objects<br/>(GROMACS, AMBER, etc.)"]
        FILES["Trajectory Files<br/>(.trr, .dcd, .nc)"]
        SYSTEMS["System Objects<br/>(Live/Static)"]
    end
    
    subgraph "Analysis Backends"
        SIRE["Sire Backend"]
        MDANALYSIS["MDAnalysis Backend"]
        MDTRAJ["MDTraj Backend"]
    end
    
    subgraph "Analysis Functions"
        GETFRAME["getFrame()"]
        TRAJECTORY["Trajectory Class"]
        RMSD["RMSD Analysis"]
        FRAMES["getFrames()"]
    end
    
    subgraph "Visualization Layer"
        VIEW["View Class<br/>(NGLview)"]
        PLOT["plot() Functions<br/>(matplotlib)"]
        NOTEBOOK["Jupyter Integration"]
    end
    
    subgraph "Output"
        RESULTS["Analysis Results"]
        PLOTS["Scientific Plots"]
        INTERACTIVE["Interactive 3D Views"]
    end
    
    PROC --> TRAJECTORY
    FILES --> GETFRAME
    SYSTEMS --> VIEW
    
    TRAJECTORY --> SIRE
    TRAJECTORY --> MDANALYSIS
    TRAJECTORY --> MDTRAJ
    GETFRAME --> SIRE
    GETFRAME --> MDANALYSIS
    GETFRAME --> MDTRAJ
    
    SIRE --> FRAMES
    MDANALYSIS --> FRAMES
    MDTRAJ --> FRAMES
    
    FRAMES --> RMSD
    TRAJECTORY --> RMSD
    
    FRAMES --> VIEW
    RMSD --> PLOT
    
    VIEW --> INTERACTIVE
    PLOT --> PLOTS
    RMSD --> RESULTS
    
    VIEW --> NOTEBOOK
    PLOT --> NOTEBOOK
    
    style TRAJECTORY fill:#e1f5fe
    style VIEW fill:#f3e5f5
    style PLOT fill:#e8f5e8
```

Sources: [python/BioSimSpace/Trajectory/_trajectory.py:27-70](), [python/BioSimSpace/Notebook/_view.py:45-497](), [python/BioSimSpace/Notebook/_plot.py:27-722]()

## Trajectory Analysis System

The trajectory analysis system provides a flexible framework for loading, parsing, and analyzing molecular dynamics trajectories from various simulation engines. The system automatically handles backend selection and format conversion.

### Core Components

```mermaid
graph TB
    subgraph "Entry Points"
        GETFRAME_FUNC["getFrame()<br/>Single frame extraction"]
        TRAJECTORY_CLASS["Trajectory Class<br/>Multi-frame analysis"]
        BACKENDS_FUNC["backends()<br/>List supported parsers"]
    end
    
    subgraph "Backend Selection"
        AUTO["AUTO Detection"]
        SIRE_BACK["SIRE Backend"]
        MDA_BACK["MDANALYSIS Backend"] 
        MDT_BACK["MDTRAJ Backend"]
    end
    
    subgraph "Data Processing"
        LOAD["_sire_load()"]
        PARSE["Frame Parsing"]
        CONVERT["Format Conversion"]
        UPDATE["Coordinate Updates"]
    end
    
    subgraph "Analysis Methods"
        NFRAMES["nFrames()"]
        GETFRAMES["getFrames()"]
        RMSD_METHOD["rmsd()"]
        GETTRAJECTORY["getTrajectory()"]
    end
    
    subgraph "Output Types"
        SYSTEM_OUT["System Objects"]
        RMSD_DATA["RMSD Data"]
        BACKEND_OBJ["Backend Objects<br/>(MDTraj/MDAnalysis)"]
    end
    
    GETFRAME_FUNC --> AUTO
    TRAJECTORY_CLASS --> AUTO
    
    AUTO --> SIRE_BACK
    AUTO --> MDA_BACK  
    AUTO --> MDT_BACK
    
    SIRE_BACK --> LOAD
    MDA_BACK --> PARSE
    MDT_BACK --> PARSE
    
    LOAD --> UPDATE
    PARSE --> UPDATE
    CONVERT --> UPDATE
    
    TRAJECTORY_CLASS --> NFRAMES
    TRAJECTORY_CLASS --> GETFRAMES
    TRAJECTORY_CLASS --> RMSD_METHOD
    TRAJECTORY_CLASS --> GETTRAJECTORY
    
    GETFRAMES --> SYSTEM_OUT
    RMSD_METHOD --> RMSD_DATA
    GETTRAJECTORY --> BACKEND_OBJ
    
    style TRAJECTORY_CLASS fill:#e1f5fe
    style AUTO fill:#fff3e0
    style RMSD_METHOD fill:#e8f5e8
```

Sources: [python/BioSimSpace/Trajectory/_trajectory.py:73-314](), [python/BioSimSpace/Trajectory/_trajectory.py:317-496](), [python/BioSimSpace/Trajectory/_trajectory.py:511-653]()

### Backend Architecture

The trajectory analysis system supports three main backends, each with specific strengths and file format compatibilities:

| Backend | Primary Use Cases | Supported Formats | Key Features |
|---------|-------------------|-------------------|--------------|
| **Sire** | Native BioSimSpace integration | All Sire-supported | Fast, preserves all properties |
| **MDAnalysis** | Comprehensive format support | 50+ formats | Robust trajectory handling |
| **MDTraj** | Performance-critical analysis | Common MD formats | Optimized for speed |

The backend selection process follows this hierarchy:

```mermaid
flowchart TD
    START["Trajectory Loading Request"]
    AUTO_CHECK{"format == 'AUTO'?"}
    SPECIFIC_CHECK{"Specific backend requested?"}
    
    SIRE_TRY["Try Sire Backend"]
    SIRE_SUCCESS{"Sire Success?"}
    
    MDTRAJ_TRY["Try MDTraj Backend"]
    MDTRAJ_SUCCESS{"MDTraj Success?"}
    
    MDANALYSIS_TRY["Try MDAnalysis Backend"]
    MDANALYSIS_SUCCESS{"MDAnalysis Success?"}
    
    VALIDATE_SPECIFIC["Validate Specific Backend"]
    SPECIFIC_SUCCESS{"Backend Compatible?"}
    
    SUCCESS["Return Trajectory Object"]
    FAIL["Raise IOError"]
    
    START --> AUTO_CHECK
    AUTO_CHECK -->|Yes| SIRE_TRY
    AUTO_CHECK -->|No| SPECIFIC_CHECK
    
    SPECIFIC_CHECK -->|Yes| VALIDATE_SPECIFIC
    SPECIFIC_CHECK -->|No| SIRE_TRY
    
    VALIDATE_SPECIFIC --> SPECIFIC_SUCCESS
    SPECIFIC_SUCCESS -->|Yes| SUCCESS
    SPECIFIC_SUCCESS -->|No| FAIL
    
    SIRE_TRY --> SIRE_SUCCESS
    SIRE_SUCCESS -->|Yes| SUCCESS
    SIRE_SUCCESS -->|No| MDTRAJ_TRY
    
    MDTRAJ_TRY --> MDTRAJ_SUCCESS
    MDTRAJ_SUCCESS -->|Yes| SUCCESS
    MDTRAJ_SUCCESS -->|No| MDANALYSIS_TRY
    
    MDANALYSIS_TRY --> MDANALYSIS_SUCCESS
    MDANALYSIS_SUCCESS -->|Yes| SUCCESS
    MDANALYSIS_SUCCESS -->|No| FAIL
    
    style SUCCESS fill:#e8f5e8
    style FAIL fill:#ffcdd2
```

Sources: [python/BioSimSpace/Trajectory/_trajectory.py:578-653](), [python/BioSimSpace/Trajectory/_trajectory.py:164-210]()

## Interactive Molecular Visualization

The `View` class provides interactive 3D molecular visualization capabilities optimized for Jupyter notebook environments. It integrates with NGLview to render molecular structures and dynamics.

### View System Architecture

```mermaid
graph TB
    subgraph "Input Sources"
        PROCESS_INPUT["Process Objects"]
        SYSTEM_INPUT["System Objects"]
        FILE_INPUT["File Paths"]
        MOL_INPUT["Molecule Objects"]
    end
    
    subgraph "View Class Core"
        VIEW_INIT["View.__init__()"]
        HANDLE_PROC["_handle Processing"]
        LAMBDA_RECON["_reconstruct_system()"]
        WORK_DIR["Temporary Workspace"]
    end
    
    subgraph "Visualization Methods"
        SYSTEM_VIEW["system()"]
        MOLECULE_VIEW["molecule()"]
        MOLECULES_VIEW["molecules()"]
        RELOAD_VIEW["reload()"]
    end
    
    subgraph "NGLview Integration"
        PDB_WRITE["PDB File Generation"]
        NGLVIEW_IMPORT["nglview.show_file()"]
        GUI_DISPLAY["display(gui=True/False)"]
    end
    
    subgraph "Output Management"
        SAVE_PDB["savePDB()"]
        RESET_VIEWS["reset()"]
        NUM_VIEWS["nViews()"]
    end
    
    PROCESS_INPUT --> VIEW_INIT
    SYSTEM_INPUT --> VIEW_INIT
    FILE_INPUT --> VIEW_INIT
    MOL_INPUT --> VIEW_INIT
    
    VIEW_INIT --> HANDLE_PROC
    VIEW_INIT --> LAMBDA_RECON
    VIEW_INIT --> WORK_DIR
    
    HANDLE_PROC --> SYSTEM_VIEW
    HANDLE_PROC --> MOLECULE_VIEW
    HANDLE_PROC --> MOLECULES_VIEW
    
    SYSTEM_VIEW --> PDB_WRITE
    MOLECULE_VIEW --> PDB_WRITE
    MOLECULES_VIEW --> PDB_WRITE
    RELOAD_VIEW --> PDB_WRITE
    
    PDB_WRITE --> NGLVIEW_IMPORT
    NGLVIEW_IMPORT --> GUI_DISPLAY
    
    SYSTEM_VIEW --> SAVE_PDB
    MOLECULE_VIEW --> SAVE_PDB
    SYSTEM_VIEW --> RESET_VIEWS
    SYSTEM_VIEW --> NUM_VIEWS
    
    style VIEW_INIT fill:#e1f5fe
    style NGLVIEW_IMPORT fill:#f3e5f5
    style GUI_DISPLAY fill:#e8f5e8
```

Sources: [python/BioSimSpace/Notebook/_view.py:48-141](), [python/BioSimSpace/Notebook/_view.py:142-301](), [python/BioSimSpace/Notebook/_view.py:402-496]()

### Perturbable Molecule Support

The visualization system includes special handling for perturbable molecules used in free energy calculations:

```mermaid
graph LR
    PERT_MOL["Perturbable Molecules"]
    LAMBDA_0["Lambda = 0 State"]
    LAMBDA_1["Lambda = 1 State"]
    RECON_SYS["_reconstruct_system()"]
    REG_MOL["Regular Molecules"]
    FINAL_SYS["Final System"]
    
    PERT_MOL --> RECON_SYS
    RECON_SYS --> LAMBDA_0
    RECON_SYS --> LAMBDA_1
    LAMBDA_0 --> REG_MOL
    LAMBDA_1 --> REG_MOL
    REG_MOL --> FINAL_SYS
    
    style PERT_MOL fill:#ffcdd2
    style FINAL_SYS fill:#e8f5e8
```

Sources: [python/BioSimSpace/Notebook/_view.py:464-496](), [python/BioSimSpace/Notebook/_view.py:88-89]()

## Scientific Plotting and Data Visualization

The plotting system provides matplotlib-based visualization capabilities with automatic unit handling and specialized plots for molecular simulation data.

### Plotting Functions Overview

```mermaid
graph TB
    subgraph "Core Plotting Functions"
        PLOT_FUNC["plot()<br/>Line plots with error bars"]
        CONTOUR_FUNC["plotContour()<br/>2D contour plots"]
        OVERLAP_FUNC["plotOverlapMatrix()<br/>FEP overlap visualization"]
    end
    
    subgraph "Data Processing"
        UNIT_DETECT["Unit Detection"]
        TYPE_CONVERT["Type Conversion"]
        MISSING_FILTER["Missing Data Filtering"]
        AUTO_LABEL["Automatic Labeling"]
    end
    
    subgraph "Matplotlib Integration"
        FIG_CREATE["Figure Creation"]
        AXIS_CONFIG["Axis Configuration"]
        ERROR_BARS["Error Bar Handling"]
        COLOR_MAP["Color Mapping"]
    end
    
    subgraph "Specialized Features"
        LOG_SCALE["Logarithmic Scaling"]
        GRID_INTERP["Grid Interpolation"]
        DISCRETE_CBAR["Discrete Color Bars"]
        FONT_CONFIG["Font Configuration"]
    end
    
    PLOT_FUNC --> UNIT_DETECT
    CONTOUR_FUNC --> UNIT_DETECT
    OVERLAP_FUNC --> TYPE_CONVERT
    
    UNIT_DETECT --> TYPE_CONVERT
    TYPE_CONVERT --> MISSING_FILTER
    MISSING_FILTER --> AUTO_LABEL
    
    AUTO_LABEL --> FIG_CREATE
    FIG_CREATE --> AXIS_CONFIG
    AXIS_CONFIG --> ERROR_BARS
    ERROR_BARS --> COLOR_MAP
    
    PLOT_FUNC --> LOG_SCALE
    CONTOUR_FUNC --> GRID_INTERP
    OVERLAP_FUNC --> DISCRETE_CBAR
    
    FIG_CREATE --> FONT_CONFIG
    
    style PLOT_FUNC fill:#e1f5fe
    style CONTOUR_FUNC fill:#f3e5f5
    style OVERLAP_FUNC fill:#e8f5e8
```

Sources: [python/BioSimSpace/Notebook/_plot.py:85-330](), [python/BioSimSpace/Notebook/_plot.py:333-535](), [python/BioSimSpace/Notebook/_plot.py:538-721]()

### Automatic Unit Handling

The plotting system automatically detects and handles BioSimSpace unit types:

| Feature | Implementation | File Reference |
|---------|---------------|----------------|
| **Unit Detection** | `isinstance(x[idx], _Type)` | [python/BioSimSpace/Notebook/_plot.py:192-193]() |
| **Automatic Labels** | `x[0]._print_format[x[0].unit()]` | [python/BioSimSpace/Notebook/_plot.py:274-276]() |
| **Value Extraction** | `x = [x.value() for x in x]` | [python/BioSimSpace/Notebook/_plot.py:292-293]() |
| **Error Bar Units** | Type consistency checking | [python/BioSimSpace/Notebook/_plot.py:188-189]() |

Sources: [python/BioSimSpace/Notebook/_plot.py:144-227](), [python/BioSimSpace/Notebook/_plot.py:266-298]()

## Integration with Simulation Workflows

The analysis and visualization components integrate seamlessly with BioSimSpace's simulation execution system, enabling real-time monitoring and post-simulation analysis.

### Process Integration Workflow

```mermaid
flowchart TB
    subgraph "Simulation Process"
        MD_PROC["MD Process<br/>(GROMACS/AMBER/etc)"]
        TRAJ_GEN["Trajectory Generation"]
        RUNNING_CHECK["isRunning()"]
    end
    
    subgraph "Real-time Analysis"
        LIVE_TRAJ["Live Trajectory Access"]
        AUTO_REFRESH["Automatic Refresh"]
        PARTIAL_DATA["Partial Data Handling"]
    end
    
    subgraph "Analysis Interface"
        TRAJ_OBJ["Trajectory Object"]
        VIEW_OBJ["View Object"]
        PLOT_DATA["Plot Data"]
    end
    
    subgraph "Output Monitoring"
        FRAME_COUNT["Frame Counting"]
        LATEST_FRAME["Latest Frame Access"]
        SYSTEM_UPDATE["System Updates"]
    end
    
    MD_PROC --> TRAJ_GEN
    TRAJ_GEN --> RUNNING_CHECK
    RUNNING_CHECK -->|True| LIVE_TRAJ
    RUNNING_CHECK -->|False| TRAJ_OBJ
    
    LIVE_TRAJ --> AUTO_REFRESH
    AUTO_REFRESH --> PARTIAL_DATA
    
    PARTIAL_DATA --> VIEW_OBJ
    PARTIAL_DATA --> PLOT_DATA
    TRAJ_OBJ --> VIEW_OBJ
    TRAJ_OBJ --> PLOT_DATA
    
    VIEW_OBJ --> FRAME_COUNT
    VIEW_OBJ --> LATEST_FRAME
    PLOT_DATA --> SYSTEM_UPDATE
    
    style MD_PROC fill:#f3e5f5
    style LIVE_TRAJ fill:#fff3e0
    style VIEW_OBJ fill:#e8f5e8
```

Sources: [python/BioSimSpace/Trajectory/_trajectory.py:388-399](), [python/BioSimSpace/Notebook/_view.py:108-116](), [python/BioSimSpace/Trajectory/_trajectory.py:672-678]()

### File Format Compatibility

The analysis system handles the diverse file formats generated by different MD engines:

| Engine | Trajectory Format | Topology Format | Backend Priority |
|--------|-------------------|-----------------|------------------|
| **GROMACS** | `.trr`, `.xtc` | `.tpr`, `.gro` | MDAnalysis, Sire |
| **AMBER** | `.nc`, `.mdcrd` | `.prmtop`, `.parm7` | Sire, MDTraj |
| **NAMD** | `.dcd` | `.psf` | MDAnalysis |
| **OpenMM** | `.dcd`, `.h5` | Various | MDTraj, Sire |
| **SOMD** | `.dcd` | `.prm7` | Sire |

Sources: [python/BioSimSpace/Trajectory/_trajectory.py:558-570](), [python/BioSimSpace/MD/_md.py:55-76]()

## Error Handling and Robustness

The analysis and visualization system includes comprehensive error handling for common failure modes:

```mermaid
graph TB
    subgraph "Input Validation"
        FILE_CHECK["File Existence"]
        FORMAT_CHECK["Format Validation"] 
        TYPE_CHECK["Type Checking"]
    end
    
    subgraph "Backend Fallbacks"
        PRIMARY_FAIL["Primary Backend Fails"]
        SECONDARY_TRY["Try Secondary Backend"]
        FALLBACK_CHAIN["Fallback Chain"]
    end
    
    subgraph "Runtime Error Handling"
        MISSING_DATA["Missing Data Points"]
        COORD_UPDATE_FAIL["Coordinate Update Failures"]
        DISPLAY_ERROR["Display Errors"]
    end
    
    subgraph "User Feedback"
        VERBOSE_MODE["Verbose Error Messages"]
        WARNING_SYSTEM["Warning System"]
        GRACEFUL_DEGRADATION["Graceful Degradation"]
    end
    
    FILE_CHECK --> PRIMARY_FAIL
    FORMAT_CHECK --> PRIMARY_FAIL
    TYPE_CHECK --> PRIMARY_FAIL
    
    PRIMARY_FAIL --> SECONDARY_TRY
    SECONDARY_TRY --> FALLBACK_CHAIN
    
    MISSING_DATA --> GRACEFUL_DEGRADATION
    COORD_UPDATE_FAIL --> WARNING_SYSTEM
    DISPLAY_ERROR --> VERBOSE_MODE
    
    FALLBACK_CHAIN --> WARNING_SYSTEM
    GRACEFUL_DEGRADATION --> WARNING_SYSTEM
    WARNING_SYSTEM --> VERBOSE_MODE
    
    style PRIMARY_FAIL fill:#ffcdd2
    style GRACEFUL_DEGRADATION fill:#e8f5e8
    style WARNING_SYSTEM fill:#fff3e0
```

Sources: [python/BioSimSpace/Trajectory/_trajectory.py:164-210](), [python/BioSimSpace/Notebook/_view.py:447-453](), [python/BioSimSpace/Notebook/_plot.py:126-137]()

---