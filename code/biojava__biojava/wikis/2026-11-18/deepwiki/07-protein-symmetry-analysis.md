# Protein Symmetry Analysis

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [biojava-structure-gui/src/main/java/demo/DemoCeSymm.java](biojava-structure-gui/src/main/java/demo/DemoCeSymm.java)
- [biojava-structure-gui/src/main/java/org/biojava/nbio/structure/symmetry/gui/SymmetryCalc.java](biojava-structure-gui/src/main/java/org/biojava/nbio/structure/symmetry/gui/SymmetryCalc.java)
- [biojava-structure-gui/src/main/java/org/biojava/nbio/structure/symmetry/gui/SymmetryDisplay.java](biojava-structure-gui/src/main/java/org/biojava/nbio/structure/symmetry/gui/SymmetryDisplay.java)
- [biojava-structure-gui/src/main/java/org/biojava/nbio/structure/symmetry/gui/SymmetryListener.java](biojava-structure-gui/src/main/java/org/biojava/nbio/structure/symmetry/gui/SymmetryListener.java)
- [biojava-structure/src/main/java/demo/DemoCeSymm.java](biojava-structure/src/main/java/demo/DemoCeSymm.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/align/util/RotationAxis.java](biojava-structure/src/main/java/org/biojava/nbio/structure/align/util/RotationAxis.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/CESymmParameters.java](biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/CESymmParameters.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/CeSymm.java](biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/CeSymm.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/CeSymmIterative.java](biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/CeSymmIterative.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/CeSymmResult.java](biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/CeSymmResult.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/GraphComponentOrderDetector.java](biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/GraphComponentOrderDetector.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/GraphComponentRefiner.java](biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/GraphComponentRefiner.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/ResidueGroup.java](biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/ResidueGroup.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/SymmOptimizer.java](biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/SymmOptimizer.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/SymmetryAxes.java](biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/SymmetryAxes.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/utils/SymmetryTools.java](biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/utils/SymmetryTools.java)
- [biojava-structure/src/test/java/org/biojava/nbio/structure/align/util/RotationAxisTest.java](biojava-structure/src/test/java/org/biojava/nbio/structure/align/util/RotationAxisTest.java)
- [biojava-structure/src/test/java/org/biojava/nbio/structure/symmetry/internal/TestSymmetryAxes.java](biojava-structure/src/test/java/org/biojava/nbio/structure/symmetry/internal/TestSymmetryAxes.java)

</details>



This document covers BioJava's internal protein symmetry detection capabilities, primarily implemented through the CE-Symm (CeSymm) algorithm. The system analyzes protein structures to identify repeating structural units and their spatial relationships, supporting both closed symmetries (circular, dihedral) and open symmetries (helical, protein repeats). 

For quaternary symmetry analysis of multi-chain complexes, see [Subunit Clustering and Quaternary Structure](#3.3). For general structure alignment capabilities, see [Multiple Structure Alignment](#3.4).

## Algorithm Overview

The CE-Symm algorithm detects internal symmetries by performing a self-alignment of a protein structure against itself, then refining the results to identify consistent repeating units. The approach supports hierarchical symmetries and can detect multiple levels of symmetry within a single structure.

### Core CE-Symm Workflow

```mermaid
flowchart TD
    Input["Atom[] atoms"] --> SelfAlign["Self-Alignment"]
    SelfAlign --> Order["Order Detection"] 
    Order --> Refine["Refinement"]
    Refine --> Optimize["Optimization"]
    Optimize --> Result["CeSymmResult"]
    
    SelfAlign --> |"AFPChain"| BlankDiag["Blank Diagonal Matrix"]
    BlankDiag --> CECalc["CE Calculation"]
    CECalc --> SelfAlign
    
    Order --> |"SequenceFunctionOrderDetector"| SeqOrder["Sequence-based Order"]
    Order --> |"GraphComponentOrderDetector"| GraphOrder["Graph-based Order"] 
    Order --> |"AngleOrderDetectorPlus"| AngleOrder["Angle-based Order"]
    
    Refine --> |"SequenceFunctionRefiner"| SeqRefine["Sequence Refinement"]
    Refine --> |"GraphComponentRefiner"| GraphRefine["Graph Refinement"]
    
    Optimize --> |"SymmOptimizer"| MCOpt["Monte Carlo Optimization"]
```

**Sources:** [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/CeSymm.java:170-344](), [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/CeSymmIterative.java:105-111]()

## Core Classes and Architecture

### Primary Analysis Classes

```mermaid
classDiagram
    class CeSymm {
        +analyze(Atom[] atoms) CeSymmResult
        +analyze(Atom[] atoms, CESymmParameters params) CeSymmResult
        +analyzeLevel(Atom[] atoms, CESymmParameters params) CeSymmResult
        -align(AFPChain afpChain, Atom[] ca1, Atom[] ca2, CESymmParameters params) Matrix
    }
    
    class CeSymmResult {
        -MultipleAlignment multipleAlignment
        -AFPChain selfAlignment
        -SymmetryAxes axes
        -CESymmParameters params
        +isSignificant() boolean
        +getRepeatsID() List~StructureIdentifier~
        +getSymmGroup() String
    }
    
    class CESymmParameters {
        -int maxSymmOrder
        -SymmetryType symmType
        -OrderDetectorMethod orderDetectorMethod
        -RefineMethod refineMethod
        -boolean optimization
        +clone() CESymmParameters
    }
    
    class SymmetryAxes {
        -List~Axis~ axes
        +addAxis(Matrix4d axis, int order, SymmetryType type)
        +getRepeatTransform(int repeat) Matrix4d
        +getSymmetryAxes() List~Axis~
    }
    
    CeSymm --> CeSymmResult
    CeSymmResult --> CESymmParameters
    CeSymmResult --> SymmetryAxes
```

**Sources:** [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/CeSymm.java:72-95](), [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/CeSymmResult.java:51-95](), [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/CESymmParameters.java:36-86](), [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/SymmetryAxes.java:63-196]()

### Supporting Analysis Components

```mermaid
classDiagram
    class CeSymmIterative {
        -CESymmParameters params
        -List~CeSymmResult~ levels
        +execute(Atom[] atoms) CeSymmResult
        -iterate(Atom[] atoms) void
        -reconstructSymmResult(Atom[] atoms) CeSymmResult
    }
    
    class SymmOptimizer {
        -MultipleAlignment msa
        -SymmetryAxes axes
        -double mcScore
        +optimize() MultipleAlignment
        -shiftRow() boolean
        -expandBlock() boolean
        -shrinkBlock() boolean
    }
    
    class SymmetryTools {
        +blankOutPreviousAlignment() Matrix
        +buildSymmetryGraph() List~List~Integer~~
        +divideStructure() List~Structure~
        +toRepeatsAlignment() MultipleAlignment
        +updateSymmetryTransformation() void
    }
    
    CeSymmIterative --> CeSymmResult
    SymmOptimizer --> MultipleAlignment
    SymmetryTools --> MultipleAlignment
```

**Sources:** [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/CeSymmIterative.java:71-92](), [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/SymmOptimizer.java:62-136](), [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/utils/SymmetryTools.java:85-92]()

## Symmetry Detection Pipeline

### Self-Alignment Process

The algorithm begins by creating a self-alignment where the structure is compared against itself with diagonal masking to prevent trivial identity matches.

```mermaid
flowchart LR
    Atoms["Atom[] atoms"] --> Clone["StructureTools.duplicateCA2()"]
    Clone --> ca2["Atom[] ca2"]
    
    Atoms --> Matrix["Distance Matrix"]
    ca2 --> Matrix
    Matrix --> Blank["blankOutPreviousAlignment()"]
    Blank --> CECalc["CECalculator.extractFragments()"]
    CECalc --> AFP["AFPChain selfAlignment"]
    
    AFP --> TMScore["TM-Score Calculation"]
    TMScore --> |"< threshold"| Reject["Asymmetric"]
    TMScore --> |">= threshold"| Continue["Continue Processing"]
```

**Sources:** [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/CeSymm.java:177-189](), [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/utils/SymmetryTools.java:326-331]()

### Order Detection Methods

Multiple algorithms determine the order of symmetry from the self-alignment:

```mermaid
flowchart TD
    SelfAlign["AFPChain selfAlignment"] --> OrderMethod{"OrderDetectorMethod"}
    
    OrderMethod --> |"SEQUENCE_FUNCTION"| SeqFunc["SequenceFunctionOrderDetector"]
    OrderMethod --> |"GRAPH_COMPONENT"| GraphComp["GraphComponentOrderDetector"] 
    OrderMethod --> |"ANGLE"| AngleDet["AngleOrderDetectorPlus"]
    OrderMethod --> |"USER_INPUT"| UserOrder["params.getUserOrder()"]
    
    SeqFunc --> |"CLOSED only"| SeqOrder["Sequence-based order"]
    GraphComp --> GraphOrder["Component size maximization"]
    AngleDet --> |"CLOSED only"| AngleOrder["Rotation angle analysis"]
    UserOrder --> FixedOrder["Fixed order"]
    
    SeqOrder --> FinalOrder["int order"]
    GraphOrder --> FinalOrder
    AngleOrder --> FinalOrder
    FixedOrder --> FinalOrder
```

**Sources:** [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/CeSymm.java:276-303](), [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/CESymmParameters.java:54-57]()

## Refinement and Optimization

### Graph-Based Refinement

The `GraphComponentRefiner` converts the self-alignment into a graph structure and identifies maximally connected components:

```mermaid
flowchart TD
    AFP["AFPChain selfAlignment"] --> Graph["buildSymmetryGraph()"]
    Graph --> Connect["ConnectivityInspector"]
    Connect --> Components["List<Set<Integer>> components"]
    
    Components --> Filter["Filter by order == targetOrder"]
    Filter --> Groups["List<ResidueGroup> groups"]
    
    Groups --> CompatMatrix["Compatibility Matrix"]
    CompatMatrix --> Scores["Row Scores (compatibility)"]
    Scores --> Select["Select most compatible"]
    Select --> |"Iterative"| Combine["Combine with alignment"]
    Combine --> |"Until no compatible groups"| FinalMSA["MultipleAlignment"]
```

**Sources:** [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/GraphComponentRefiner.java:58-82](), [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/GraphComponentRefiner.java:121-139]()

### Monte Carlo Optimization

The `SymmOptimizer` uses Monte Carlo methods to improve alignment quality:

```mermaid
flowchart LR
    MSA["MultipleAlignment"] --> Init["Initialize block & freePool"]
    Init --> MCLoop["Monte Carlo Loop"]
    
    MCLoop --> Move{"Select Move Type"}
    Move --> |"40%"| Shift["shiftRow()"]
    Move --> |"30%"| Expand["expandBlock()"]
    Move --> |"15%"| Shrink["shrinkBlock()"]
    Move --> |"15%"| Gap["insertGap()"]
    
    Shift --> Score["Calculate MC Score"]
    Expand --> Score
    Shrink --> Score 
    Gap --> Score
    
    Score --> Accept{"Accept Move?"}
    Accept --> |"Better score"| Keep["Keep changes"]
    Accept --> |"Probability function"| Maybe["Maybe keep"]
    Accept --> |"Reject"| Revert["Revert changes"]
    
    Keep --> MCLoop
    Maybe --> MCLoop
    Revert --> MCLoop
    
    MCLoop --> |"Convergence"| Final["Optimized MSA"]
```

**Sources:** [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/SymmOptimizer.java:192-330](), [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/SymmOptimizer.java:229-246]()

## Symmetry Types and Parameters

### Symmetry Classification

The algorithm supports different symmetry types defined in `CESymmParameters.SymmetryType`:

| Type | Description | Detection Criteria |
|------|-------------|-------------------|
| `CLOSED` | Circular, dihedral symmetries | Multiple blocks in AFPChain (circular permutation) |
| `OPEN` | Helical, protein repeats | Single block in AFPChain |
| `AUTO` | Automatic detection | Determined by block count in self-alignment |

**Sources:** [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/CESymmParameters.java:79-82](), [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/CeSymm.java:254-263]()

### Key Configuration Parameters

```mermaid
flowchart TD
    Params["CESymmParameters"] --> Detection["Detection Parameters"]
    Params --> Refinement["Refinement Parameters"]
    Params --> Optimization["Optimization Parameters"]
    
    Detection --> MaxOrder["maxSymmOrder: 8"]
    Detection --> SymmType["symmType: AUTO"]
    Detection --> OrderMethod["orderDetectorMethod"]
    Detection --> UnrefThresh["unrefinedScoreThreshold: 0.4"]
    
    Refinement --> RefineMethod["refineMethod: SEQUENCE_FUNCTION"]
    Refinement --> RefThresh["refinedScoreThreshold: 0.36"]
    Refinement --> MinCore["minCoreLength: 15"]
    Refinement --> SSEThresh["sseThreshold: 0"]
    
    Optimization --> OptFlag["optimization: true"]
    Optimization --> OptSteps["optimizationSteps: 0 (auto)"]
    Optimization --> DistCutoff["distanceCutoff: 7.0"]
    Optimization --> Gaps["gaps: true"]
```

**Sources:** [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/CESymmParameters.java:126-143]()

## Results and Visualization

### CeSymmResult Analysis

The `CeSymmResult` class provides comprehensive analysis of detected symmetries:

```mermaid
flowchart TD
    Result["CeSymmResult"] --> Significant{"isSignificant()"}
    
    Significant --> |"true"| ValidSymm["Valid Symmetry"]
    Significant --> |"false"| Asymmetric["Asymmetric Structure"]
    
    ValidSymm --> MSA["getMultipleAlignment()"]
    ValidSymm --> Axes["getAxes()"]
    ValidSymm --> Group["getSymmGroup()"]
    ValidSymm --> Repeats["getRepeatsID()"]
    
    MSA --> Superposition["Structural superposition"]
    Axes --> Transform["Transformation matrices"]
    Group --> |"QuaternarySymmetry"| PointGroup["Point group (C3, D4, etc.)"]
    Repeats --> SubStruct["SubstructureIdentifier list"]
    
    Asymmetric --> Reason["getReason()"]
    Reason --> SelfAlign["Show self-alignment only"]
```

**Sources:** [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/CeSymmResult.java:72-95](), [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/CeSymmResult.java:194-221]()

### Visualization Integration

The system integrates with Jmol for 3D visualization through `SymmetryDisplay`:

```mermaid
flowchart TD
    Display["SymmetryDisplay"] --> RepeatView["displayRepeats()"]
    Display --> FullView["displayFull()"]
    Display --> MainView["display()"]
    
    RepeatView --> RepeatAlign["Superposed repeats"]
    FullView --> FullStruct["Full structure alignment"]
    MainView --> ColorRepeats["Color by repeat"]
    
    MainView --> AxesScript["printSymmetryAxes()"]
    MainView --> GroupScript["printSymmetryGroup()"]
    
    AxesScript --> JmolAxes["Jmol axis visualization"]
    GroupScript --> JmolPoly["Jmol polyhedron display"]
    
    RepeatAlign --> JmolDisplay["MultipleAlignmentJmol"]
    FullStruct --> JmolDisplay
    ColorRepeats --> JmolDisplay
```

**Sources:** [biojava-structure-gui/src/main/java/org/biojava/nbio/structure/symmetry/gui/SymmetryDisplay.java:111-152](), [biojava-structure-gui/src/main/java/org/biojava/nbio/structure/symmetry/gui/SymmetryDisplay.java:209-255]()

## Usage Examples

### Basic Symmetry Analysis

```java
// Load structure
AtomCache cache = new AtomCache();
Structure s = cache.getStructure("1u6d");
Atom[] atoms = StructureTools.getRepresentativeAtomArray(s);

// Configure parameters
CESymmParameters params = new CESymmParameters();
params.setRefineMethod(RefineMethod.SEQUENCE_FUNCTION);
params.setSymmType(SymmetryType.AUTO);
params.setOptimization(true);

// Run analysis
CeSymmResult result = CeSymm.analyze(atoms, params);

// Check results
if (result.isSignificant()) {
    System.out.println("Symmetry: " + result.getSymmGroup());
    System.out.println("Repeats: " + result.getNumRepeats());
}
```

**Sources:** [biojava-structure-gui/src/main/java/demo/DemoCeSymm.java:76-94]()

### Iterative Multi-Level Analysis

For detecting hierarchical symmetries, the system automatically uses `CeSymmIterative`:

```java
CESymmParameters params = new CESymmParameters();
params.setSymmLevels(0); // Unlimited levels
CeSymmResult result = CeSymm.analyze(atoms, params);

// Access hierarchical information
int levels = result.getSymmLevels();
SymmetryAxes axes = result.getAxes();
```

**Sources:** [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/CeSymm.java:387-405](), [biojava-structure/src/main/java/org/biojava/nbio/structure/symmetry/internal/CeSymmIterative.java:105-111]()

---