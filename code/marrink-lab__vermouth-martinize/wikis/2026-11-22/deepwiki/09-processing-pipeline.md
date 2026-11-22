# Processing Pipeline

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [bin/martinize2](bin/martinize2)
- [vermouth/dssp/dssp.py](vermouth/dssp/dssp.py)
- [vermouth/graph_utils.py](vermouth/graph_utils.py)
- [vermouth/ismags.py](vermouth/ismags.py)
- [vermouth/map_input.py](vermouth/map_input.py)
- [vermouth/map_parser.py](vermouth/map_parser.py)
- [vermouth/processors/__init__.py](vermouth/processors/__init__.py)
- [vermouth/processors/annotate_idrs.py](vermouth/processors/annotate_idrs.py)
- [vermouth/processors/canonicalize_modifications.py](vermouth/processors/canonicalize_modifications.py)
- [vermouth/processors/do_mapping.py](vermouth/processors/do_mapping.py)
- [vermouth/processors/repair_graph.py](vermouth/processors/repair_graph.py)
- [vermouth/tests/helper_functions.py](vermouth/tests/helper_functions.py)
- [vermouth/tests/test_annotate_idrs.py](vermouth/tests/test_annotate_idrs.py)
- [vermouth/tests/test_do_mapping.py](vermouth/tests/test_do_mapping.py)
- [vermouth/tests/test_dssp.py](vermouth/tests/test_dssp.py)
- [vermouth/tests/test_graph_utils.py](vermouth/tests/test_graph_utils.py)
- [vermouth/tests/test_ismags.py](vermouth/tests/test_ismags.py)
- [vermouth/tests/test_map_input.py](vermouth/tests/test_map_input.py)
- [vermouth/tests/test_mapping_integrative.py](vermouth/tests/test_mapping_integrative.py)
- [vermouth/tests/test_ptm_detection.py](vermouth/tests/test_ptm_detection.py)
- [vermouth/tests/test_repair_graph.py](vermouth/tests/test_repair_graph.py)
- [vermouth/tests/test_selectors.py](vermouth/tests/test_selectors.py)
- [vermouth/tests/test_version.py](vermouth/tests/test_version.py)

</details>



The Processing Pipeline is the core workflow in VerMoUTH that transforms molecular structures through a series of well-defined steps. It handles everything from reading input files to generating coarse-grained models with the desired structural features. This page explains how the pipeline is structured, how each processor works, and how they combine to create a flexible transformation system.

For information about specific processors, see their respective dedicated pages in the [Core Components](#2) section. For details on adding structural features like elastic networks, see [Structural Features](#3.4).

## Pipeline Overview

The Processing Pipeline applies a sequence of transformation steps (processors) to molecular structures. Each processor performs a specific task and can be combined flexibly to achieve different outcomes.

```mermaid
flowchart TD
    Input["Input Files (PDB/GRO/CIF)"] --> Reader["File Reader (PDBInput/GROInput/CIFInput)"]
    Reader --> MakeBonds["Make Bonds"]
    MakeBonds --> RepairGraph["Repair Graph"]
    RepairGraph --> CanonMods["Canonicalize Modifications"]
    CanonMods --> DoMapping["Force Field Mapping"]
    DoMapping --> DoAveraging["Average Beads"]
    DoAveraging --> DoLinks["Apply Links"]
    DoLinks --> ChargeDummies["Locate Charge Dummies"]
    
    subgraph "Optional Structural Features"
        ChargeDummies --> ElasticNetwork["Apply Elastic Network"]
        ChargeDummies --> GoModel["Apply Go Model"]
        ElasticNetwork -.-> WaterBias["Apply Water Bias"]
        GoModel --> WaterBias
    end
    
    WaterBias --> WriteOutput["Write Topology"]
```

Sources: [bin/martinize2:106-167](), [bin/martinize2:162-191](), [vermouth/processors/__init__.py]()

## Processor Architecture

Processors are the building blocks of the pipeline. Each processor implements a standard interface allowing them to be chained together.

```mermaid
classDiagram
    class Processor {
        +run_system(system)
        +run_molecule(molecule)
        +name: str
    }
    
    class RepairGraph {
        +run_system(system)
        +delete_unknown: bool
    }
    
    class DoMapping {
        +run_system(system)
        +mappings: dict
        +to_ff: ForceField
    }
    
    class DoLinks {
        +run_system(system)
    }
    
    Processor <|-- RepairGraph
    Processor <|-- DoMapping
    Processor <|-- DoLinks
    Processor <|-- CanonicalizeModifications
    Processor <|-- ApplyRubberBand
```

Each processor follows a common pattern:
1. Accepts a `System` object containing `Molecule` objects
2. Transforms the system or its molecules
3. Returns the modified system

Sources: [vermouth/processors/processor.py](), [vermouth/processors/__init__.py]()

## Key Pipeline Stages

### Input Reading

The pipeline begins by reading input files and creating a molecular system.

```mermaid
flowchart TD
    subgraph "Input File Types"
        PDB["PDB File (.pdb)"]
        GRO["GRO File (.gro)"]
        CIF["CIF File (.cif)"]
    end
    
    subgraph "Reader Processors"
        PDBInput["PDBInput"]
        GROInput["GROInput"] 
        CIFInput["CIFInput"]
    end
    
    PDB --> PDBInput
    GRO --> GROInput
    CIF --> CIFInput
    
    PDBInput --> System["System with Molecules"]
    GROInput --> System
    CIFInput --> System
```

The system is populated with molecules containing atoms but typically without explicitly defined bonds. Bonds are added in the next step.

Sources: [bin/martinize2:81-104](), [vermouth/processors/pdb_reader.py](), [vermouth/processors/gro_reader.py](), [vermouth/processors/cif_reader.py]()

### Making Bonds

The `MakeBonds` processor creates connections between atoms in the molecule.

```mermaid
flowchart LR
    subgraph "Bond Creation Methods"
        Name["By Atom Names"]
        Distance["By Distance"]
        CONECT["From CONECT records"]
    end
    
    Atoms["Atoms without bonds"] --> MakeBonds["MakeBonds Processor"]
    Name --> MakeBonds
    Distance --> MakeBonds
    CONECT --> MakeBonds
    MakeBonds --> BondedMol["Molecule with bonds"]
```

Bonds can be created based on:
- Atom naming conventions in standard residues
- Distance between atoms (using van der Waals radii)
- CONECT records from input files (if available)

Sources: [bin/martinize2:132-136](), [vermouth/processors/make_bonds.py]()

### Graph Repair

The `RepairGraph` processor is responsible for fixing incomplete molecular structures by:
1. Identifying missing atoms
2. Adding these atoms with the correct connectivity
3. Correcting atom names that don't match the reference force field

```mermaid
flowchart TD
    Input["Incomplete Molecule"] --> RepairGraph["RepairGraph Processor"]
    ForceField["Force Field Reference Graphs"] --> RepairGraph
    
    subgraph "Repair Process"
        MakeRef["Create Reference"]
        RepairRes["Repair Each Residue"]
    end
    
    RepairGraph --> MakeRef
    MakeRef --> RepairRes
    RepairRes --> Complete["Complete Molecule"]
```

This step ensures that all molecules contain the complete set of atoms expected by the force field.

Sources: [bin/martinize2:144-147](), [vermouth/processors/repair_graph.py](), [vermouth/graph_utils.py]()

### Canonicalization of Modifications

The `CanonicalizeModifications` processor handles post-translational modifications (PTMs) and other molecular modifications:

```mermaid
flowchart TD
    Input["Molecule with PTM atoms"] --> FindPTM["Find PTM Atoms"]
    FindPTM --> IdentifyPTM["Identify PTMs"]
    IdentifyPTM --> ApplyPTM["Apply PTM Templates"]
    ApplyPTM --> Output["Molecule with Canonical PTMs"]
    
    ForceField["Force Field Modifications"] --> IdentifyPTM
```

This processor:
1. Identifies atoms marked as modifications
2. Matches them against known modification patterns
3. Applies the correct templates from the force field

Sources: [bin/martinize2:156-157](), [vermouth/processors/canonicalize_modifications.py]()

### Resolution Mapping (DoMapping)

The `DoMapping` processor is central to coarse-graining, transforming molecules from one resolution to another:

```mermaid
flowchart TD
    Input["Molecule at Source Resolution"] --> DoMapping["DoMapping Processor"]
    Mappings["Mapping Definitions"] --> DoMapping
    SourceFF["Source Force Field"] --> DoMapping
    TargetFF["Target Force Field"] --> DoMapping
    
    DoMapping --> BlockMatch["Match Blocks"]
    BlockMatch --> ApplyMapping["Apply Mappings"]
    ApplyMapping --> TransferAttrs["Transfer Attributes"]
    TransferAttrs --> Output["Molecule at Target Resolution"]
```

The mapping process involves:
1. Finding correspondences between atoms in the source molecule and beads in the target molecule
2. Creating a new molecule at the target resolution
3. Transferring appropriate properties from the source to the target

Sources: [bin/martinize2:174-177](), [vermouth/processors/do_mapping.py]()

### Bead Position Averaging

After mapping, the `DoAverageBead` processor calculates positions for the coarse-grained beads:

```mermaid
flowchart LR
    Molecule["Mapped Molecule"] --> DoAverageBead["DoAverageBead Processor"]
    DoAverageBead --> Weighted["Calculate Weighted Positions"]
    Weighted --> Positioned["Molecule with Bead Positions"]
```

Bead positions are typically calculated as a weighted average of the positions of the atoms that map to each bead.

Sources: [bin/martinize2:183-184](), [vermouth/processors/average_beads.py]()

### Applying Links

The `DoLinks` processor applies links between residues and adds the appropriate interactions:

```mermaid
flowchart TD
    Molecule["Coarse-grained Molecule"] --> DoLinks["DoLinks Processor"]
    ForceField["Force Field Links"] --> DoLinks
    
    DoLinks --> FindMatches["Find Link Matches"]
    FindMatches --> ApplyLinks["Apply Links"]
    ApplyLinks --> AddInter["Add Interactions"]
    AddInter --> Complete["Molecule with Interactions"]
```

This step adds bonds, angles, dihedrals, and other interactions between residues according to the force field definition.

Sources: [bin/martinize2:188-189](), [vermouth/processors/do_links.py]()

### Secondary Structure Assignment

Secondary structure can be assigned in several ways:

```mermaid
flowchart TD
    Input["Protein Molecule"] --> Method["Secondary Structure Method"]
    
    Method --> DSSP["DSSP Assignment"]
    Method --> Manual["Manual Assignment"]
    Method --> Collagen["Collagen Parameters"]
    
    DSSP --> Annotate["Annotate Molecule"]
    Manual --> Annotate
    Collagen --> Annotate
    
    Annotate --> Convert["Convert to Martini SS"]
    Convert --> Output["Molecule with CG Secondary Structure"]
```

The secondary structure assignment is crucial for determining the appropriate parameters for the coarse-grained model, particularly for elastic networks and backbone parameters.

Sources: [bin/martinize2:924-949](), [vermouth/dssp/dssp.py]()

## Optional Structural Features

### Elastic Networks

Elastic networks can be added to maintain the tertiary structure of proteins:

```mermaid
flowchart TD
    Molecule["CG Molecule"] --> ApplyRubberBand["ApplyRubberBand Processor"]
    
    Parameters["Elastic Network Parameters"] --> ApplyRubberBand
    
    ApplyRubberBand --> SelectNodes["Select Nodes"]
    SelectNodes --> CalcDistances["Calculate Distances"]
    CalcDistances --> ApplyForces["Apply Force Constants"]
    ApplyForces --> Output["Molecule with Elastic Network"]
```

The elastic network adds harmonic bonds between selected beads (typically backbone beads) within a certain distance cutoff, with force constants that can decay with distance.

Sources: [bin/martinize2:472-546](), [vermouth/processors/apply_rubber_band.py]()

### Go Models

Go models provide an alternative approach to maintaining structure:

```mermaid
flowchart TD
    Molecule["Input Molecule"] --> GenerateMap["Generate Contact Map"]
    GenerateMap --> GoPipeline["Go Pipeline"]
    
    Parameters["Go Model Parameters"] --> GoPipeline
    
    GoPipeline --> CreateVS["Create Virtual Sites"]
    CreateVS --> AddBias["Add Go Bias Interactions"]
    AddBias --> Output["Molecule with Go Model"]
```

Go models use structure-based potentials between virtual sites to maintain the native structure of proteins.

Sources: [bin/martinize2:547-608](), [vermouth/rcsu/go_pipeline.py](), [vermouth/rcsu/contact_map.py]()

### Water Bias

Water bias can be applied to affect the solvation behavior of different regions:

```mermaid
flowchart TD
    Molecule["CG Molecule"] --> ComputeWaterBias["ComputeWaterBias Processor"]
    
    SecStructure["Secondary Structure"] --> ComputeWaterBias
    IDRs["Disordered Regions"] --> ComputeWaterBias
    BiasParams["Bias Parameters"] --> ComputeWaterBias
    
    ComputeWaterBias --> ModifyInteractions["Modify Interactions"]
    ModifyInteractions --> Output["Molecule with Water Bias"]
```

Water bias adjusts the interactions of specific regions (like helices, sheets, or disordered regions) with water to better reproduce experimental behavior.

Sources: [bin/martinize2:610-645](), [vermouth/processors/water_bias.py]()

## Integration in Martinize2

The entire pipeline is integrated into the `martinize2` command-line tool, which configures and runs the appropriate processors based on user arguments:

```mermaid
flowchart TD
    Arguments["Command-line Arguments"] --> SetupSystem["Set Up System"]
    SetupSystem --> ConfigurePipeline["Configure Pipeline"]
    
    subgraph "Core Pipeline"
        Read["Read Input Files"]
        Repair["Repair and Canonicalize"]
        Map["Map to Target Force Field"]
        Links["Apply Links"]
    end
    
    subgraph "Optional Features"
        Elastic["Elastic Network"]
        Go["Go Model"]
        WaterBias["Water Bias"]
        PosRes["Position Restraints"]
    end
    
    ConfigurePipeline --> Read
    Read --> Repair
    Repair --> Map
    Map --> Links
    
    Links --> Features["Apply Optional Features"]
    Features --> Elastic
    Features --> Go
    Features --> WaterBias
    Features --> PosRes
    
    Elastic --> WriteOutput["Write Output Files"]
    Go --> WriteOutput
    WaterBias --> WriteOutput
    PosRes --> WriteOutput
```

This integration provides a flexible and powerful tool for coarse-graining molecular structures with various customization options.

Sources: [bin/martinize2:289-781](), [bin/martinize2:923-1057]()

## Error Handling and Logging

The pipeline includes comprehensive error handling and logging to help users identify and fix issues:

| Log Level | Purpose | Example |
|-----------|---------|---------|
| ERROR | Critical issues that prevent completion | Can't find isomorphism between residue and its reference |
| WARNING | Issues that might affect results | Unknown post-translational modifications |
| INFO | Major processing steps | Reading input, applying mappings |
| DEBUG | Detailed processing information | Adding specific atoms |

Sources: [bin/martinize2:54-77](), [vermouth/log_helpers.py]()

## Extending the Pipeline

The modular nature of the processing pipeline makes it relatively straightforward to extend:

1. Create a new processor class inheriting from `Processor`
2. Implement the `run_system` and/or `run_molecule` methods
3. Insert the processor at the appropriate point in the pipeline

This architecture allows for great flexibility in customizing the coarse-graining process to meet specific research needs.

Sources: [vermouth/processors/processor.py](), [vermouth/processors/__init__.py]()

---