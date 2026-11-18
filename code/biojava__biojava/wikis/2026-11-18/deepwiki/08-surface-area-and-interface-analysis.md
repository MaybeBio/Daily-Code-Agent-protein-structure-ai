# Surface Area and Interface Analysis

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [biojava-integrationtest/src/test/java/org/biojava/nbio/structure/test/StructureTest.java](biojava-integrationtest/src/test/java/org/biojava/nbio/structure/test/StructureTest.java)
- [biojava-integrationtest/src/test/java/org/biojava/nbio/structure/test/contact/TestInterfaceFinder.java](biojava-integrationtest/src/test/java/org/biojava/nbio/structure/test/contact/TestInterfaceFinder.java)
- [biojava-integrationtest/src/test/java/org/biojava/nbio/structure/test/xtal/TestCrystalBuilder.java](biojava-integrationtest/src/test/java/org/biojava/nbio/structure/test/xtal/TestCrystalBuilder.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/asa/AsaCalculator.java](biojava-structure/src/main/java/org/biojava/nbio/structure/asa/AsaCalculator.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/contact/BoundingBox.java](biojava-structure/src/main/java/org/biojava/nbio/structure/contact/BoundingBox.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/contact/Contact.java](biojava-structure/src/main/java/org/biojava/nbio/structure/contact/Contact.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/contact/Grid.java](biojava-structure/src/main/java/org/biojava/nbio/structure/contact/Grid.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/contact/GridCell.java](biojava-structure/src/main/java/org/biojava/nbio/structure/contact/GridCell.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/contact/InterfaceFinder.java](biojava-structure/src/main/java/org/biojava/nbio/structure/contact/InterfaceFinder.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/contact/StructureInterface.java](biojava-structure/src/main/java/org/biojava/nbio/structure/contact/StructureInterface.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/contact/StructureInterfaceCluster.java](biojava-structure/src/main/java/org/biojava/nbio/structure/contact/StructureInterfaceCluster.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/contact/StructureInterfaceList.java](biojava-structure/src/main/java/org/biojava/nbio/structure/contact/StructureInterfaceList.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/xtal/CrystalBuilder.java](biojava-structure/src/main/java/org/biojava/nbio/structure/xtal/CrystalBuilder.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/xtal/UnitCellBoundingBox.java](biojava-structure/src/main/java/org/biojava/nbio/structure/xtal/UnitCellBoundingBox.java)
- [biojava-structure/src/test/java/org/biojava/nbio/structure/asa/TestAsaCalc.java](biojava-structure/src/test/java/org/biojava/nbio/structure/asa/TestAsaCalc.java)
- [biojava-structure/src/test/java/org/biojava/nbio/structure/contact/TestInterfaceFinder.java](biojava-structure/src/test/java/org/biojava/nbio/structure/contact/TestInterfaceFinder.java)
- [biojava-structure/src/test/java/org/biojava/nbio/structure/redmine/Test1DARSeqAlign.java](biojava-structure/src/test/java/org/biojava/nbio/structure/redmine/Test1DARSeqAlign.java)

</details>



## Purpose and Scope

This document covers BioJava's computational tools for analyzing protein surface areas and molecular interfaces. The system provides algorithms for calculating Accessible Surface Area (ASA) using the rolling ball method, detecting contacts between molecular chains, and identifying crystal interfaces through symmetry operations. For structure visualization and display components, see [Jmol Integration and Structure Visualization](#5.1). For protein comparison applications, see [Protein Comparison Tool](#5.2).

## ASA Calculation System

### Core ASA Algorithm

The `AsaCalculator` class implements the Shrake-Rupley rolling ball algorithm for computing Accessible Surface Areas. The algorithm samples points on a sphere around each atom and determines which points are accessible (not occluded by neighboring atoms).

```mermaid
flowchart TD
    Structure["Structure Input"] --> AsaCalc["AsaCalculator"]
    AsaCalc --> SphereGen["generateSpherePoints()"]
    AsaCalc --> NeighborFind["findNeighborIndices()"]
    AsaCalc --> RadiusLookup["getRadius()"]
    
    SphereGen --> GoldenSpiral["Golden Section Spiral<br/>Algorithm"]
    NeighborFind --> SpatialHash["Spatial Hashing Grid"]
    NeighborFind --> AllToAll["All-to-All Distance"]
    RadiusLookup --> ChothiaRadii["Chothia VDW Radii"]
    
    GoldenSpiral --> AsaCalcSingle["calcSingleAsa()"]
    SpatialHash --> AsaCalcSingle
    ChothiaRadii --> AsaCalcSingle
    
    AsaCalcSingle --> GroupAsa["GroupAsa Results"]
    AsaCalcSingle --> AtomAsa["Per-Atom ASA Values"]
```

**ASA Calculation Pipeline**

The system uses Van der Waals radii from Chothia (1976) to account for different atom types in amino acids and nucleotides. The `DEFAULT_N_SPHERE_POINTS` is set to 1000 for accuracy, with `DEFAULT_PROBE_SIZE` of 1.4 Å.

Sources: [biojava-structure/src/main/java/org/biojava/nbio/structure/asa/AsaCalculator.java:55-669]()

### Spatial Optimization

The ASA calculator employs spatial hashing to efficiently find neighboring atoms within the cutoff distance, avoiding costly all-to-all distance calculations.

```mermaid
flowchart LR
    Atoms["Atom Coordinates"] --> Grid["Grid Spatial Hash"]
    Grid --> CellSize["Cell Size = Cutoff"]
    Grid --> Neighbors["Neighbor Detection"]
    
    Neighbors --> OptimizedCalc["Optimized ASA<br/>Calculation"]
    
    AllToAll["All-to-All O(n²)"] -.-> SpatialHash["Spatial Hash O(n)"]
    SpatialHash --> Performance["~4x Performance<br/>Improvement"]
```

**Spatial Hashing Optimization**

Sources: [biojava-structure/src/main/java/org/biojava/nbio/structure/asa/AsaCalculator.java:389-440](), [biojava-structure/src/main/java/org/biojava/nbio/structure/contact/Grid.java:59-516]()

## Interface Detection and Analysis

### StructureInterface Representation

The `StructureInterface` class represents contacts between two molecular chains, storing atom pairs, contact distances, and buried surface areas.

```mermaid
classDiagram
    class StructureInterface {
        +Pair~Atom[]~ molecules
        +Pair~String~ moleculeIds
        +Pair~CrystalTransform~ transforms
        +AtomContactSet contacts
        +Map~ResidueNumber,GroupAsa~ groupAsas1
        +Map~ResidueNumber,GroupAsa~ groupAsas2
        +double totalArea
        +getTotalArea() double
        +getContactOverlapScore() double
        +isSymRelated() boolean
        +isHomomeric() boolean
    }
    
    class AtomContactSet {
        +List~AtomContact~ contacts
        +double cutoff
        +size() int
    }
    
    class GroupAsa {
        +Group group
        +double asaU
        +double asaC
        +getBsa() double
        +getBsaToAsaRatio() double
    }
    
    StructureInterface *-- AtomContactSet
    StructureInterface *-- GroupAsa
```

**StructureInterface Class Structure**

Sources: [biojava-structure/src/main/java/org/biojava/nbio/structure/contact/StructureInterface.java:62-819]()

### Interface Analysis Workflow

The interface analysis system provides multiple approaches for finding molecular interfaces, from simple contact detection to comprehensive crystal lattice analysis.

```mermaid
flowchart TD
    StructInput["Structure Input"] --> Choice{Analysis Type}
    
    Choice -->|Simple| InterfaceFinder["InterfaceFinder"]
    Choice -->|Crystallographic| CrystalBuilder["CrystalBuilder"]
    
    InterfaceFinder --> BoundingBox["BoundingBox Overlap"]
    InterfaceFinder --> ContactCalc["Contact Calculation"]
    
    CrystalBuilder --> SpaceGroup["Space Group Operations"]
    CrystalBuilder --> CellExpansion["Unit Cell Expansion"]
    CrystalBuilder --> SymmetryCheck["Symmetry Redundancy Check"]
    
    ContactCalc --> StructInterfaceList["StructureInterfaceList"]
    SymmetryCheck --> StructInterfaceList
    
    StructInterfaceList --> AsaAnalysis["ASA Analysis"]
    StructInterfaceList --> Clustering["Interface Clustering"]
    
    AsaAnalysis --> BuriedArea["Buried Surface Area"]
    Clustering --> ContactOverlap["Contact Overlap Scoring"]
```

**Interface Analysis Workflow**

Sources: [biojava-structure/src/main/java/org/biojava/nbio/structure/contact/InterfaceFinder.java:22-107](), [biojava-structure/src/main/java/org/biojava/nbio/structure/xtal/CrystalBuilder.java:45-632]()

### Crystal Interface Analysis

The `CrystalBuilder` class performs comprehensive interface analysis by generating symmetry mates and detecting contacts across the crystal lattice.

| Parameter | Default Value | Description |
|-----------|---------------|-------------|
| `DEF_NUM_CELLS` | 20 | Number of neighboring cells to search |
| `DEFAULT_INTERFACE_DISTANCE_CUTOFF` | 5.5 Å | Maximum distance for interface contacts |
| `DEFAULT_CONTACT_OVERLAP_SCORE_CLUSTER_CUTOFF` | 0.2 | Threshold for interface clustering |

**Crystal Builder Configuration**

The system handles various crystallographic scenarios including non-standard space groups, missing unit cell information, and non-standard coordinate frames.

Sources: [biojava-structure/src/main/java/org/biojava/nbio/structure/xtal/CrystalBuilder.java:65-71]()

## Contact Calculation and Spatial Data Structures

### Grid-Based Contact Detection

The `Grid` class implements spatial hashing for efficient contact calculation, dividing 3D space into cells of size equal to the cutoff distance.

```mermaid
flowchart LR
    Points["3D Coordinates"] --> GridHash["Grid Hash Function"]
    GridHash --> Cells["Grid Cells"]
    
    Cells --> CellContacts["Intra-Cell Contacts"]
    Cells --> NeighborContacts["Inter-Cell Contacts"]
    
    CellContacts --> ContactList["Contact List"]
    NeighborContacts --> ContactList
    
    subgraph "Grid Cell Structure"
        GridCell["GridCell"]
        IIndices["iIndices: List<Integer>"]
        JIndices["jIndices: List<Integer>"]
        GridCell --> IIndices
        GridCell --> JIndices
    end
```

**Grid-Based Spatial Hashing**

Sources: [biojava-structure/src/main/java/org/biojava/nbio/structure/contact/Grid.java:59-96](), [biojava-structure/src/main/java/org/biojava/nbio/structure/contact/GridCell.java:35-175]()

### BoundingBox Optimization

`BoundingBox` objects provide rapid overlap detection to avoid unnecessary contact calculations between distant molecular regions.

```mermaid
flowchart TD
    AtomCoords["Atom Coordinates"] --> BBCalc["BoundingBox Calculation"]
    BBCalc --> MinMax["Min/Max X,Y,Z"]
    
    MinMax --> OverlapTest["overlaps(cutoff)"]
    OverlapTest -->|True| DetailedCalc["Detailed Contact Calculation"]
    OverlapTest -->|False| Skip["Skip Calculation"]
    
    subgraph "Overlap Detection"
        XOverlap["X-dimension overlap"]
        YOverlap["Y-dimension overlap"] 
        ZOverlap["Z-dimension overlap"]
        XOverlap --> AllDims["All 3 dimensions<br/>must overlap"]
        YOverlap --> AllDims
        ZOverlap --> AllDims
    end
```

**BoundingBox Overlap Detection**

Sources: [biojava-structure/src/main/java/org/biojava/nbio/structure/contact/BoundingBox.java:42-255]()

## Interface Clustering and Classification

### Contact Overlap Scoring

The system uses Jaccard similarity (intersection over union) of contact sets to measure interface similarity and perform clustering.

```mermaid
flowchart LR
    Interface1["Interface A Contacts"] --> Jaccard["Jaccard Score Calculation"]
    Interface2["Interface B Contacts"] --> Jaccard
    
    Jaccard --> ScoreMatrix["Similarity Matrix"]
    ScoreMatrix --> SingleLinkage["Single Linkage Clustering"]
    SingleLinkage --> Clusters["Interface Clusters"]
    
    subgraph "Similarity Calculation"
        Intersection["Contact Set Intersection"]
        Union["Contact Set Union"]
        Score["Score = |A ∩ B| / |A ∪ B|"]
        Intersection --> Score
        Union --> Score
    end
```

**Interface Clustering Pipeline**

Sources: [biojava-structure/src/main/java/org/biojava/nbio/structure/contact/StructureInterfaceList.java:375-451]()

### Interface Classification

The system classifies interfaces based on several criteria:

| Classification | Method | Description |
|----------------|---------|-------------|
| Homomeric/Heteromeric | `isHomomeric()` | Same vs different entities |
| Symmetric/Asymmetric | `isSymRelated()` | Crystallographic symmetry |
| Isologous/Heterologous | `isIsologous()` | Self-contact overlap analysis |
| Infinite/Finite | `isInfinite()` | Crystal translation properties |

**Interface Classification Types**

Sources: [biojava-structure/src/main/java/org/biojava/nbio/structure/contact/StructureInterface.java:375-404]()

## Performance Considerations

The system implements several optimization strategies:

1. **Spatial Hashing**: Reduces neighbor finding from O(n²) to O(n)
2. **BoundingBox Pre-filtering**: Eliminates distant molecule pairs early
3. **Multi-threading**: Parallel ASA calculation with configurable thread count
4. **Sorted Neighbor Lists**: Optimizes occlusion checking in ASA calculation

The `DEFAULT_ASA_SPHERE_POINTS` of 3000 provides a balance between accuracy and performance for interface area calculations.

Sources: [biojava-structure/src/main/java/org/biojava/nbio/structure/contact/StructureInterfaceList.java:62-67](), [biojava-structure/src/main/java/org/biojava/nbio/structure/asa/AsaCalculator.java:466-470]()

---