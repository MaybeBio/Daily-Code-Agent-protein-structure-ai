# Clustering

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/Analysis_Clustering.cpp](src/Analysis_Clustering.cpp)
- [src/Analysis_Clustering.h](src/Analysis_Clustering.h)

</details>



This document provides a comprehensive overview of the clustering functionality in CPPTRAJ. Clustering is a powerful analysis technique that groups similar conformations from molecular dynamics trajectories, helping researchers identify predominant structural states and simplify trajectory analysis. For other analysis features, see [Analysis Features](#6).

## Purpose and Overview

Clustering in CPPTRAJ allows users to group trajectory frames based on structural similarity or other metrics. The implementation supports multiple clustering algorithms, distance metrics, and processing options to accommodate different research needs. This system enables:

- Identification of representative structures from large trajectory datasets
- Analysis of conformational space sampling
- Reduction of trajectory complexity for further analysis
- Generation of structural ensembles for visualization and interpretation

Sources: [src/Analysis_Clustering.h:5-6]()

## Integration with CPPTRAJ Architecture

Clustering is implemented as an Analysis module within CPPTRAJ's Analysis Engine. It operates on trajectory data or other datasets and produces clustered datasets that can be further processed or output.

```mermaid
flowchart TD
    subgraph "CPPTRAJ Analysis Engine"
        Analysis["Analysis Base Class"]
        Actions["Actions"]
        Analyses["Analyses"]
        
        Analysis --> Actions
        Analysis --> Analyses
        
        subgraph "Analysis Implementations"
            Clustering["Analysis_Clustering"]
            Statistics["Statistical Analysis"]
            Correlation["Correlation Analysis"]
            GIST["Grid-Based Analysis"]
        end
        
        Analyses --> Clustering
        Analyses --> Statistics
        Analyses --> Correlation
        Analyses --> GIST
    end
    
    subgraph "Clustering Components"
        ClusterControl["Cluster::Control"]
        Algorithms["Clustering Algorithms"]
        Metrics["Distance Metrics"]
        Output["Output Generation"]
        
        ClusterControl --> Algorithms
        ClusterControl --> Metrics
        ClusterControl --> Output
    end
    
    Clustering --> ClusterControl
```

Sources: [src/Analysis_Clustering.h:1-19](), [src/Analysis_Clustering.cpp:4-5]()

## Class Structure

The clustering functionality is primarily implemented through two key classes:

1. `Analysis_Clustering` - Entry point that inherits from the `Analysis` base class
2. `Cpptraj::Cluster::Control` - Core implementation that handles the clustering algorithms and processing

```mermaid
classDiagram
    class Analysis {
        <<abstract>>
        +Setup(ArgList&, AnalysisSetup&, int)
        +Analyze()
        +Help()
    }
    
    class Analysis_Clustering {
        -Cpptraj::Cluster::Control control_
        -DataSetList* masterDSL_
        +Setup(ArgList&, AnalysisSetup&, int)
        +Analyze()
        +Help()
    }
    
    class Control {
        +SetupClustering()
        +Run()
        +Output()
        +Timing()
        +Info()
        +Help()
    }
    
    Analysis <|-- Analysis_Clustering : inherits
    Analysis_Clustering *-- "1" Control : contains
    Analysis_Clustering --> DataSetList : references
```

Sources: [src/Analysis_Clustering.h:4-18](), [src/Analysis_Clustering.cpp:4-15]()

## Processing Workflow

The clustering analysis follows a specific workflow through the CPPTRAJ processing pipeline:

```mermaid
sequenceDiagram
    participant User
    participant Analysis_Clustering
    participant Control
    participant DataSets
    
    User->>Analysis_Clustering: Setup with arguments
    Analysis_Clustering->>DataSets: Get input data sets
    DataSets-->>Analysis_Clustering: Return coordinates or metrics
    Analysis_Clustering->>Control: SetupClustering(inputDsets, coords, args)
    Control-->>Analysis_Clustering: Setup complete
    
    User->>Analysis_Clustering: Analyze()
    Analysis_Clustering->>Control: Run()
    Control->>Control: Perform clustering algorithm
    Control-->>Analysis_Clustering: Clustering complete
    Analysis_Clustering->>Control: Output(*masterDSL_)
    Control->>DataSets: Add cluster results
    Control-->>Analysis_Clustering: Output complete
    Analysis_Clustering-->>User: Analysis results
```

Sources: [src/Analysis_Clustering.cpp:14-75]()

## Data Handling

Clustering can be performed on two types of input data:

1. **Coordinate Data** (`DataSet_Coords`): Clustering based on structural similarity of trajectory frames
2. **Generic Data Sets**: Clustering based on arbitrary data metrics

The input data selection is handled in the `Setup()` method of `Analysis_Clustering`:

```mermaid
flowchart TD
    Start["Setup()"] --> CheckData["Check for 'data' key"]
    
    CheckData -->|"data specified"| GetDataSets["Get multiple data sets"]
    GetDataSets --> CheckCoords["Check for 'crdset' or !nocoords"]
    
    CheckData -->|"data not specified"| CheckCoords
    
    CheckCoords -->|"coords needed"| FindCoords["Find COORDS dataset"]
    FindCoords -->|"no data specified"| AddCoords["Add coordinates to input datasets"]
    FindCoords --> SetupCluster["control_.SetupClustering()"]
    
    CheckCoords -->|"coords not needed"| SetupCluster
    
    SetupCluster --> Info["control_.Info()"]
    Info --> End["Return"]
```

Sources: [src/Analysis_Clustering.cpp:14-56]()

## Clustering Execution

The actual clustering analysis is executed in the `Analyze()` method:

1. Start a timer to measure performance
2. Call `control_.Run()` to execute the clustering algorithm
3. Call `control_.Output(*masterDSL_)` to generate output data
4. Stop the timer and record timing information

Sources: [src/Analysis_Clustering.cpp:59-75]()

## Supported Clustering Algorithms

CPPTRAJ supports multiple clustering algorithms, including:

| Algorithm | Description |
|-----------|-------------|
| Hierarchical | Groups data points based on distance between them in a tree-like structure |
| K-means | Partitions data into k clusters based on the mean distance to cluster centers |
| DBSCAN | Density-based spatial clustering - groups based on regions of high density |
| DPeaks | Density peaks clustering algorithm |

The specific algorithm used is determined by parameters passed during setup.

Sources: System Architecture Diagrams

## Usage Parameters

The clustering functionality accepts several key parameters:

| Parameter | Description |
|-----------|-------------|
| `crdset <crd set>` | Specifies a coordinate dataset for structural clustering |
| `data <dset0>[,<dset1>...]` | Specifies arbitrary datasets for metric-based clustering |
| `nocoords` | Disables use of coordinate data, even if available |

Additional parameters for specific algorithms, distance metrics, and output options are handled by the `Control` class.

Sources: [src/Analysis_Clustering.cpp:8-11](), [src/Analysis_Clustering.cpp:19-46]()

## Practical Workflow

The typical workflow for using clustering in CPPTRAJ involves:

```mermaid
flowchart LR
    LoadData["Load trajectory\nand topology"] --> SetupClustering["Setup clustering\nparameters"]
    SetupClustering --> RunClustering["Run clustering\nanalysis"]
    RunClustering --> AnalyzeResults["Analyze cluster\nstatistics"]
    AnalyzeResults --> ViewRepresentatives["View representative\nstructures"]
```

## Implementation Notes

1. The `Analysis_Clustering` class acts primarily as a wrapper that delegates the actual clustering functionality to the `Cpptraj::Cluster::Control` class.

2. Input data processing is flexible, allowing for:
   - Coordinate-based clustering (structural similarity)
   - Data metric-based clustering (arbitrary metrics)
   - Combinations of both approaches

3. Performance timing is built in to track the efficiency of the clustering operation.

4. Results are stored in the master DataSetList for further processing or output.

Sources: [src/Analysis_Clustering.cpp:1-76](), [src/Analysis_Clustering.h:1-19]()

## Integration with Other CPPTRAJ Components

Clustering analysis interacts with several other components of CPPTRAJ:

1. **Data Management System**: Results are stored as DataSets
2. **Output System**: Cluster statistics and representative structures can be written to various output formats
3. **Command Processing**: Clustering parameters are parsed from user input

For more information on these related systems, see [Data Management](#4.3) and [Command Processing](#3.1).

---