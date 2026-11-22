# Analysis and Advanced Features

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [regtest/basic/rt-make-4/Makefile](regtest/basic/rt-make-4/Makefile)
- [regtest/basic/rt-make-4/config](regtest/basic/rt-make-4/config)
- [regtest/basic/rt-make-4/main.cpp](regtest/basic/rt-make-4/main.cpp)
- [regtest/basic/rt-make-4/output.reference](regtest/basic/rt-make-4/output.reference)
- [regtest/basic/rt64-pca/Makefile](regtest/basic/rt64-pca/Makefile)
- [regtest/basic/rt64-pca/check.reference](regtest/basic/rt64-pca/check.reference)
- [regtest/basic/rt64-pca/colvar.reference](regtest/basic/rt64-pca/colvar.reference)
- [regtest/basic/rt64-pca/config](regtest/basic/rt64-pca/config)
- [regtest/basic/rt64-pca/plumed.dat](regtest/basic/rt64-pca/plumed.dat)
- [regtest/basic/rt64-pca/wrongcolvar.reference](regtest/basic/rt64-pca/wrongcolvar.reference)
- [regtest/basic/rt65-rmsd2/test.cpp](regtest/basic/rt65-rmsd2/test.cpp)
- [regtest/trajectories/pca/average.pdb](regtest/trajectories/pca/average.pdb)
- [regtest/trajectories/pca/eigenvec.pdb](regtest/trajectories/pca/eigenvec.pdb)
- [regtest/trajectories/pca/eigenvec1.pdb](regtest/trajectories/pca/eigenvec1.pdb)
- [src/colvar/PCARMSD.cpp](src/colvar/PCARMSD.cpp)
- [src/colvar/PathMSDBase.cpp](src/colvar/PathMSDBase.cpp)
- [src/colvar/PathMSDBase.h](src/colvar/PathMSDBase.h)
- [src/core/ActionPilot.cpp](src/core/ActionPilot.cpp)
- [src/core/ActionPilot.h](src/core/ActionPilot.h)
- [src/dimred/PCA.cpp](src/dimred/PCA.cpp)
- [src/dimred/SketchMap.cpp](src/dimred/SketchMap.cpp)
- [src/dimred/SketchMapProjection.cpp](src/dimred/SketchMapProjection.cpp)
- [src/function/Sum.cpp](src/function/Sum.cpp)
- [src/gridtools/ActionWithGrid.cpp](src/gridtools/ActionWithGrid.cpp)
- [src/gridtools/ActionWithGrid.h](src/gridtools/ActionWithGrid.h)
- [src/gridtools/ConvertToFES.cpp](src/gridtools/ConvertToFES.cpp)
- [src/gridtools/GetGridVolumeElement.cpp](src/gridtools/GetGridVolumeElement.cpp)
- [src/mapping/Path.cpp](src/mapping/Path.cpp)
- [src/tools/Log.h](src/tools/Log.h)
- [src/tools/RMSD.cpp](src/tools/RMSD.cpp)
- [src/tools/RMSD.h](src/tools/RMSD.h)

</details>



This document describes the advanced analysis capabilities and high-level features in PLUMED, focusing on grid-based methods, dimensionality reduction, and advanced collective variable (CV) analysis. The systems and code entities discussed here enable users to perform sophisticated post-processing, data reduction, and feature extraction on molecular simulation data.

**Scope:**  
- Grid-based analysis and free energy surface (FES) conversion
- Principal Component Analysis (PCA) and related dimensionality reduction
- Path-based collective variables and advanced RMSD analysis
- Sketch-map and nonlinear dimensionality reduction
- Underlying code structure and key classes

**Not covered here:**  
- For enhanced sampling methods (e.g., Metadynamics, OPES, VES), see [Enhanced Sampling Methods](#3).
- For command-line tools and general utilities, see [Tools and Utilities](#5).
- For the core Action framework and CV system, see [Action Framework](#2.3).

---

## Purpose and System Overview

PLUMED's analysis and advanced features provide tools for extracting meaningful information from high-dimensional simulation data. These include:

- Calculation and manipulation of free energy surfaces on grids
- Dimensionality reduction (PCA, sketch-map)
- Path-based CVs for reaction coordinate analysis
- Advanced RMSD and alignment calculations

These features are implemented as a combination of core classes, shortcut actions, and specialized modules.

**Sources:**  
[src/gridtools/ConvertToFES.cpp](), [src/dimred/PCA.cpp](), [src/dimred/SketchMap.cpp](), [src/colvar/PathMSDBase.cpp](), [src/tools/RMSD.cpp](), [src/colvar/PCARMSD.cpp](), [src/mapping/Path.cpp]()

---

## System Architecture: Analysis and Advanced Features

### Diagram: High-Level System and Code Entity Mapping

```mermaid
flowchart TD
    "ConvertToFES.cpp"["ConvertToFES.cpp (class ConvertToFES)"]
    "PCA.cpp"["PCA.cpp (class PCA)"]
    "SketchMap.cpp"["SketchMap.cpp (class SketchMap)"]
    "PCARMSD.cpp"["PCARMSD.cpp (class PCARMSD)"]
    "PathMSDBase.cpp"["PathMSDBase.cpp (class PathMSDBase)"]
    "RMSD.cpp"["RMSD.cpp (class RMSD)"]
    "Path.cpp"["Path.cpp (class Path)"]

    subgraph "Grid-based Analysis"
        "ConvertToFES.cpp"
    end
    subgraph "Dimensionality Reduction"
        "PCA.cpp"
        "SketchMap.cpp"
    end
    subgraph "Path and RMSD Analysis"
        "PCARMSD.cpp"
        "PathMSDBase.cpp"
        "RMSD.cpp"
        "Path.cpp"
    end

    "ConvertToFES.cpp" --> "Grid-based Analysis"
    "PCA.cpp" --> "Dimensionality Reduction"
    "SketchMap.cpp" --> "Dimensionality Reduction"
    "PCARMSD.cpp" --> "Path and RMSD Analysis"
    "PathMSDBase.cpp" --> "Path and RMSD Analysis"
    "RMSD.cpp" --> "Path and RMSD Analysis"
    "Path.cpp" --> "Path and RMSD Analysis"
```
**Sources:**  
[src/gridtools/ConvertToFES.cpp](), [src/dimred/PCA.cpp](), [src/dimred/SketchMap.cpp](), [src/colvar/PCARMSD.cpp](), [src/colvar/PathMSDBase.cpp](), [src/tools/RMSD.cpp](), [src/mapping/Path.cpp]()

---

## 1. Grid-Based Analysis and Free Energy Surfaces

PLUMED provides tools for manipulating and analyzing data on grids, such as histograms and free energy surfaces (FES).

### 1.1. Free Energy Surface Conversion

The `ConvertToFES` action converts a histogram (e.g., from the `HISTOGRAM` action) into a free energy surface using the formula:

$$
F(x) = -k_B T \ln H(x)
$$

- **Class:** `ConvertToFES`  
- **File:** [src/gridtools/ConvertToFES.cpp]()

**Key Features:**
- Converts histogram data to FES
- Supports temperature specification and shifting minimum to zero
- Output is compatible with grid-based actions like `DUMPGRID`

**Example Usage:**
```plumed
x: DISTANCE ATOMS=1,2
hA1: HISTOGRAM ARG=x GRID_MIN=0.0 GRID_MAX=3.0 GRID_BIN=100 BANDWIDTH=0.1
ff: CONVERT_TO_FES ARG=hA1 TEMP=300
DUMPGRID ARG=ff FILE=fes.dat
```

**Sources:**  
[src/gridtools/ConvertToFES.cpp:26-121]()

---

## 2. Principal Component Analysis (PCA) and Dimensionality Reduction

PLUMED supports both linear and nonlinear dimensionality reduction for analyzing high-dimensional simulation data.

### 2.1. Principal Component Analysis (PCA)

The `PCA` action performs principal component analysis on a set of input vectors (e.g., atomic positions or CVs), producing orthogonal directions of maximal variance.

- **Class:** `PCA`
- **File:** [src/dimred/PCA.cpp]()

**Key Features:**
- Supports both atomic positions and arbitrary CVs as input
- Removes translational and rotational degrees of freedom if desired
- Outputs projections and principal components

**Example Usage:**
```plumed
ff: COLLECT_FRAMES ATOMS=1-22 STRIDE=1
pca: PCA ARG=ff NLOW_DIM=2 FILE=pca-comp.pdb
DUMPVECTOR ARG=pca,pca_weights FILE=colvar STRIDE=0
```

**Sources:**  
[src/dimred/PCA.cpp:30-221]()

---

### 2.2. PCA with RMSD Alignment: `PCARMSD`

The `PCARMSD` action projects the current structure onto a set of PCA eigenvectors, after optimal RMSD alignment to a reference structure.

- **Class:** `PCARMSD`
- **File:** [src/colvar/PCARMSD.cpp]()

**Key Features:**
- Reads average structure and eigenvectors from PDB files
- Performs optimal alignment before projection
- Outputs projections and residuals

**Sources:**  
[src/colvar/PCARMSD.cpp:32-268]()

---

### 2.3. Sketch-Map: Nonlinear Dimensionality Reduction

The `SketchMap` action implements the sketch-map algorithm for nonlinear dimensionality reduction, mapping high-dimensional data to a low-dimensional space.

- **Class:** `SketchMap`
- **File:** [src/dimred/SketchMap.cpp]()

**Key Features:**
- Supports both direct and landmark-based projections
- Configurable switching functions for high/low dimensions
- Supports SMACOF optimization and out-of-sample projections

**Sources:**  
[src/dimred/SketchMap.cpp:28-315]()

---

#### Diagram: Dimensionality Reduction Code Entities

```mermaid
flowchart TD
    "PCA.cpp"["PCA.cpp (PCA)"]
    "PCARMSD.cpp"["PCARMSD.cpp (PCARMSD)"]
    "SketchMap.cpp"["SketchMap.cpp (SketchMap)"]
    "COLLECT_FRAMES"["COLLECT_FRAMES (input data)"]

    "COLLECT_FRAMES" --> "PCA.cpp"
    "COLLECT_FRAMES" --> "SketchMap.cpp"
    "PCARMSD.cpp" --> "PCA.cpp"
```
**Sources:**  
[src/dimred/PCA.cpp](), [src/colvar/PCARMSD.cpp](), [src/dimred/SketchMap.cpp]()

---

## 3. Path-Based Collective Variables and Advanced RMSD

PLUMED provides advanced path-based CVs and RMSD analysis for reaction coordinate and conformational pathway studies.

### 3.1. PathMSD and PathMSDBase

The `PathMSDBase` class implements the core logic for path-based CVs using mean squared displacement (MSD) or RMSD as the distance metric.

- **Class:** `PathMSDBase`
- **File:** [src/colvar/PathMSDBase.cpp](), [src/colvar/PathMSDBase.h]()

**Key Features:**
- Supports neighbor lists for efficiency
- Implements "close structure" optimization for repeated RMSD calculations
- Handles multiple reference frames and properties

**Sources:**  
[src/colvar/PathMSDBase.cpp:34-377](), [src/colvar/PathMSDBase.h:34-95]()

---

### 3.2. Path CVs: Flexible Path Metrics

The `Path` class (and related actions) allow the definition of path-based CVs using various distance metrics, not limited to RMSD.

- **Class:** `Path`
- **File:** [src/mapping/Path.cpp]()

**Key Features:**
- Supports both geometric and RMSD-based path metrics
- Allows property mapping along the path
- Flexible input via PDB files and argument lists

**Sources:**  
[src/mapping/Path.cpp:134-343]()

---

### 3.3. Advanced RMSD Calculation

The `RMSD` class provides a comprehensive implementation of RMSD and MSD calculations, including optimal alignment, derivatives, and support for weighted atoms.

- **Class:** `RMSD`
- **File:** [src/tools/RMSD.cpp](), [src/tools/RMSD.h]()

**Key Features:**
- Multiple alignment methods: SIMPLE, OPTIMAL, OPTIMAL-FAST
- Calculation of derivatives with respect to positions and reference
- Support for close structure optimization and PCA elements

**Sources:**  
[src/tools/RMSD.cpp:38-917](), [src/tools/RMSD.h:65-276]()

---

#### Table: Key Classes and Their Roles

| Class Name         | File Path                        | Main Role                                      |
|--------------------|----------------------------------|------------------------------------------------|
| `ConvertToFES`     | src/gridtools/ConvertToFES.cpp   | Histogram to FES conversion                    |
| `PCA`              | src/dimred/PCA.cpp               | Principal component analysis                   |
| `PCARMSD`          | src/colvar/PCARMSD.cpp           | PCA projection with RMSD alignment             |
| `SketchMap`        | src/dimred/SketchMap.cpp         | Nonlinear dimensionality reduction (sketch-map)|
| `PathMSDBase`      | src/colvar/PathMSDBase.cpp       | Path-based CVs using RMSD/MSD                  |
| `Path`             | src/mapping/Path.cpp             | Flexible path-based CVs                        |
| `RMSD`             | src/tools/RMSD.cpp, RMSD.h       | RMSD/MSD calculation and alignment             |

**Sources:**  
[src/gridtools/ConvertToFES.cpp](), [src/dimred/PCA.cpp](), [src/colvar/PCARMSD.cpp](), [src/dimred/SketchMap.cpp](), [src/colvar/PathMSDBase.cpp](), [src/mapping/Path.cpp](), [src/tools/RMSD.cpp](), [src/tools/RMSD.h]()

---

## 4. Integration and Extensibility

These analysis features are implemented as PLUMED actions and can be combined in input files for complex workflows. They are extensible via the module system and can be used in both online (during simulation) and offline (post-processing) modes.

### Diagram: Analysis Feature Integration in PLUMED

```mermaid
flowchart TD
    "Simulation Data"["Simulation Data"]
    "GridTools"["src/gridtools/ConvertToFES.cpp"]
    "DimRed"["src/dimred/PCA.cpp, src/dimred/SketchMap.cpp"]
    "PathCV"["src/colvar/PathMSDBase.cpp, src/mapping/Path.cpp"]
    "RMSD"["src/tools/RMSD.cpp"]

    "Simulation Data" --> "GridTools"
    "Simulation Data" --> "DimRed"
    "Simulation Data" --> "PathCV"
    "PathCV" --> "RMSD"
    "DimRed" --> "RMSD"
```
**Sources:**  
[src/gridtools/ConvertToFES.cpp](), [src/dimred/PCA.cpp](), [src/dimred/SketchMap.cpp](), [src/colvar/PathMSDBase.cpp](), [src/mapping/Path.cpp](), [src/tools/RMSD.cpp]()

---

## 5. Summary

PLUMED's analysis and advanced features provide a robust set of tools for extracting, reducing, and interpreting high-dimensional simulation data. The system is built around modular, extensible code entities that support a wide range of scientific workflows, from free energy surface analysis to nonlinear dimensionality reduction and advanced path-based CVs.

For further details on the implementation of specific features, refer to the cited source files and class definitions.

---

**Sources for this page:**  
[src/gridtools/ConvertToFES.cpp](), [src/dimred/PCA.cpp](), [src/dimred/SketchMap.cpp](), [src/colvar/PCARMSD.cpp](), [src/colvar/PathMSDBase.cpp](), [src/mapping/Path.cpp](), [src/tools/RMSD.cpp](), [src/tools/RMSD.h]()