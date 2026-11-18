# Protein Structure Handling

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [Figure/content.png](Figure/content.png)
- [saprot/data/data_transform.py](saprot/data/data_transform.py)
- [saprot/data/parse.py](saprot/data/parse.py)

</details>



This page documents how SaprotHub processes and handles protein structures for model input, feature extraction, and analysis tasks. The protein structure handling components provide essential functionality for converting between different structural representations and extracting structural features needed for protein language models.

## 1. Overview

The protein structure handling system in SaprotHub supports loading protein structures from standard file formats (PDB and mmCIF), extracting and manipulating structural data, and converting structures into specialized features for input to structure-aware protein language models.

```mermaid
flowchart TD
    subgraph "Protein Structure Input"
        PDB["PDB Files (.pdb)"]
        mmCIF["mmCIF Files (.cif)"]
        Structure["In-memory Structure Objects"]
        
        PDB --> |"parse_structure()"| Structure
        mmCIF --> |"parse_structure()"| Structure
    end
    
    subgraph "Structure Processing"
        Manipulation["Structure Manipulation
        - Chain extraction
        - Sequence alignment
        - Residue filtering"]
        
        Representation["Structure Representation
        - Dictionary format
        - Tensor format
        - Coordinate frames"]
        
        Structure --> Manipulation
        Structure --> Representation
    end
    
    subgraph "Feature Extraction"
        DistanceMap["Distance Maps
        make_dist_map()"]
        
        RBF["Radial Basis Functions
        make_rbf()"]
        
        Orientations["Orientation Features
        make_orientations()"]
        
        Structure --> DistanceMap
        Structure --> RBF
        Structure --> Orientations
    end
    
    subgraph "Model Input"
        SASequence["Structure-Aware Sequence"]
        ModelFeatures["Model Feature Tensors"]
        
        DistanceMap --> ModelFeatures
        RBF --> ModelFeatures
        Orientations --> ModelFeatures
        Representation --> SASequence
    end
    
    ModelFeatures --> PLM["Protein Language Models"]
    SASequence --> PLM
```

Sources: [saprot/data/parse.py:1-439](), [saprot/data/data_transform.py:1-99]()

## 2. Structure Parsing and File Handling

SaprotHub uses BioPython's PDB module to parse protein structure files (PDB and mmCIF formats) and extract structural information.

### 2.1. Parsers and File I/O

The system instantiates specialized parsers for both PDB and mmCIF formats:

```python
mmcif_parser = FastMMCIFParser(QUIET=True)
mmcif_io = MMCIFIO()
pdb_parser = PDBParser(QUIET=True)
pdb_io = PDBIO()
```

Sources: [saprot/data/parse.py:15-18]()

### 2.2. Structure Parsing

The core parsing function `parse_structure` reads protein structure files and extracts essential information:

```mermaid
flowchart TD
    Start["parse_structure()"] --> DetectFormat["Detect file format
    (PDB or mmCIF)"]
    DetectFormat --> SelectParser["Select appropriate parser"]
    SelectParser --> ParseStructure["Parse structure file"]
    ParseStructure --> ProcessChains["Process requested chains"]
    ProcessChains --> ExtractResidues["Extract valid residues"]
    ExtractResidues --> BuildDict["Build dictionary with:
    - Sequence
    - Atom coordinates
    - Metadata"]
    BuildDict --> Return["Return parsed structure dictionary"]
```

The returned dictionary contains:
- `seq`: Amino acid sequence as a string
- `coords`: Dictionary of atom coordinates with keys `N`, `CA`, `C`, `O`
- `name`: Name of the PDB
- `chain`: Chain ID

Sources: [saprot/data/parse.py:421-448]()

### 2.3. Structure Manipulation Functions

The system provides several functions for manipulating protein structures:

| Function | Purpose |
|----------|---------|
| `split_chain` | Extract a single chain from a structure file |
| `extract_pdb_section` | Extract a segment of residues from a structure |
| `remove_pdb_section` | Remove specific residues from a structure |
| `align_structure_output` | Align two structures and save the aligned result |
| `get_chain_ids` | Get all chain IDs in a structure file |
| `is_residue_valid` | Check if a residue has all required atoms |
| `create_pdb_from_backbone` | Generate a PDB file from backbone coordinates |

Sources: [saprot/data/parse.py:294-318](), [saprot/data/parse.py:320-340](), [saprot/data/parse.py:342-382](), [saprot/data/parse.py:383-419](), [saprot/data/parse.py:177-248](), [saprot/data/parse.py:26-75]()

## 3. Structure Representation and Transformations

SaprotHub uses several representations for protein structures and provides functions to convert between them.

### 3.1. Coordinate Systems and Transformations

```mermaid
flowchart LR
    subgraph "Coordinate Representations"
        direction TB
        DictFormat["Dictionary Format
        {'N': [[x,y,z], ...], 
         'CA': [[x,y,z], ...],
         'C': [[x,y,z], ...],
         'O': [[x,y,z], ...]}"]
        
        TensorFormat["Tensor Format
        [L, 4, 3]
        L: sequence length
        4: N, CA, C, O atoms
        3: x, y, z coordinates"]
        
        DictFormat <-->|"dict2tensor()/tensor2dict()"| TensorFormat
    end
    
    subgraph "Coordinate Frames"
        direction TB
        GlobalCoords["Global Coordinates
        (External reference frame)"]
        
        LocalCoords["Local Coordinates
        (Residue-centered frame)"]
        
        GlobalCoords <-->|"global_to_local()/local_to_global()"| LocalCoords
    end
    
    DictFormat -->|"dict2trans()"| GlobalCoords
```

Sources: [saprot/data/data_transform.py:370-427](), [saprot/data/data_transform.py:261-326]()

### 3.2. Frame Construction and Manipulation

The system defines a local coordinate frame for each residue based on its backbone atoms:

1. The origin is at the CA atom position
2. The x-axis points from CA to C
3. The y-axis is perpendicular to both the x-axis and the CA-N vector
4. The z-axis completes the right-handed coordinate system

This frame allows for residue-centric operations and feature calculations.

```mermaid
flowchart TD
    subgraph "Frame Construction"
        direction LR
        Backbone["Protein Backbone
        N, CA, C, O atoms"]
        
        Basis["Local Basis Matrix
        construct_3d_basis()"]
        
        Backbone --> |"Calculate vectors"| Basis
    end
    
    subgraph "Transforms"
        direction LR
        Rotation["Rotation Matrix
        [L, 3, 3]"]
        
        Translation["Translation Vector
        [L, 3]"]
        
        Basis --> Rotation
        Basis --> Translation
    end
    
    subgraph "Operations"
        direction TB
        FrameNoise["add_frame_noise()
        Add noise to the coordinate frame"]
        
        Quaternions["rot2quat()/quat2rot()
        Convert between rotations and quaternions"]
        
        Transforms["Frame transformations
        local_to_global()/global_to_local()"]
    end
    
    Rotation --> Quaternions
    Rotation --> Transforms
    Translation --> Transforms
    Quaternions --> FrameNoise
    Transforms --> FrameNoise
```

Sources: [saprot/data/data_transform.py:261-326](), [saprot/data/data_transform.py:155-244](), [saprot/data/data_transform.py:330-367]()

## 4. Feature Extraction from Structures

SaprotHub extracts various structural features that can be used as input for protein language models.

### 4.1. Distance Maps

Distance maps compute the pairwise distances between atoms in the protein:

```mermaid
flowchart LR
    subgraph "Distance Map Generation"
        direction TB
        Coords["Protein Coordinates
        [L, 4, 3]"]
        
        PseudoCB["Calculate Pseudo-CB
        coordinates"]
        
        PairwiseDist["Calculate pairwise
        distances between atoms"]
        
        DistMap["Distance Map
        [L, L, 25]
        (25 atom pair combinations)"]
        
        Coords --> PseudoCB
        Coords --> PairwiseDist
        PseudoCB --> PairwiseDist
        PairwiseDist --> DistMap
    end
```

The `make_dist_map` function calculates a distance map that includes all pairwise distances between N, CA, C, O, and pseudo-CB atoms.

Sources: [saprot/data/data_transform.py:58-92]()

### 4.2. Radial Basis Function Features

```mermaid
flowchart LR
    DistMap["Distance Map"] --> RBF["Radial Basis Functions
    [L, L, 25 * num_rbf]"]
    
    subgraph "RBF Transformation"
        direction TB
        Values["Distance values"] 
        Centers["RBF centers"] 
        Gaussian["Gaussian functions
        exp(-z²)"]
        
        Values --> Gaussian
        Centers --> Gaussian
    end
    
    DistMap --> Values
    RBF --> ModelInput["Model Input Features"]
```

The `make_rbf` function converts distance maps into radial basis function features, which provide a smoother, fixed-dimension representation of the distance information.

Sources: [saprot/data/data_transform.py:38-115]()

### 4.3. Orientation Features

Orientation features capture the relative orientation of residues in 3D space:

```mermaid
flowchart TD
    subgraph "Orientation Feature Extraction"
        Coords["Protein Coordinates"] --> LocalFrames["Calculate local reference frames"]
        LocalFrames --> RelativeOrientations["Calculate relative orientations"]
        RelativeOrientations --> Quaternions["Convert to quaternions"]
        RelativeOrientations --> DirectionVectors["Direction unit vectors"]
        Quaternions --> Combine["Combine features"]
        DirectionVectors --> Combine
        Combine --> OrientationFeatures["Orientation Features
        [L, L, 7]
        (3 for direction, 4 for rotation)"]
    end
```

The `make_orientations` function calculates the relative orientations between all pairs of residues, encoded as direction vectors and quaternions.

Sources: [saprot/data/data_transform.py:118-152]()

## 5. Integration with Model Pipeline

Protein structure handling is a key component in SaprotHub's processing pipeline, transforming raw structural data into model-ready features.

```mermaid
flowchart TD
    subgraph "Input Processing"
        PDBInput["PDB/mmCIF Input"] --> StructureParsing["parse_structure()"]
        StructureParsing --> StructureDict["Parsed Structure Dict"]
    end
    
    subgraph "Feature Extraction"
        StructureDict --> |"make_rbf()"| RBFFeatures["RBF Features"]
        StructureDict --> |"make_orientations()"| OrientFeatures["Orientation Features"]
        StructureDict --> |"make_dist_map()"| DistMapFeatures["Distance Map"]
    end
    
    subgraph "Model Integration"
        RBFFeatures --> FeatureCombination["Combined Structure Features"]
        OrientFeatures --> FeatureCombination
        DistMapFeatures --> FeatureCombination
        
        StructureDict --> |"Extract sequence"| ProteinSequence["Protein Sequence"]
        
        FeatureCombination --> ModelInput["Structure-Aware Model Input"]
        ProteinSequence --> ModelInput
    end
    
    ModelInput --> PLM["Protein Language Models"]
```

The extracted structural features can be used in various downstream tasks:

1. **Structure-aware sequence modeling**: Enhancing protein language models with structural information
2. **Structure prediction validation**: Comparing predicted structures with experimental ones
3. **Mutation effect prediction**: Understanding how mutations affect protein structure and function
4. **Design of structure-based protein properties**: Engineering proteins with specific structural characteristics

For more information about how these features are used in model training, see [Training Pipeline](#5) and [Model Architecture](#3).

Sources: [saprot/data/parse.py:421-448](), [saprot/data/data_transform.py:95-152]()

## 6. Common Operations

This section documents common operations for working with protein structures in SaprotHub.

### 6.1. Structure Alignment

Structure alignment is an important operation for comparing protein structures:

```python
# Align two protein chains and save the result
align_structure_output(chain1, chain2, save_path1="aligned1.pdb", save_path2="aligned2.pdb")

# Align two structure dictionaries, removing residues that don't match
aligned_dicts = align_structure(dict1, dict2)
```

The alignment is based on the amino acid sequence and removes residues that don't align between the two structures.

Sources: [saprot/data/parse.py:177-248](), [saprot/data/parse.py:251-291]()

### 6.2. Chain and Residue Manipulation

```python
# Extract a chain from a structure
split_chain("input.pdb", "output.pdb", "A")

# Extract a section of a structure
extract_pdb_section("input.pdb", "output.pdb", "A", 10, 50)

# Remove specific residues from a structure
remove_pdb_section("input.pdb", "output.pdb", "A", [15, 16, 17])
```

These functions allow for precise manipulation of structure files.

Sources: [saprot/data/parse.py:294-318](), [saprot/data/parse.py:342-382](), [saprot/data/parse.py:383-419]()

### 6.3. Conversion Between Representations

```python
# Convert coordinate dictionary to tensor
coords_tensor = dict2tensor(coord_dict)

# Convert tensor back to dictionary
coords_dict = tensor2dict(coords_tensor)

# Get rotation matrix and translation vector from coordinates
coords, rots, trans = dict2trans(coord_dict)
```

These utilities allow for easy conversion between different representations of protein structure.

Sources: [saprot/data/data_transform.py:370-427]()

## 7. Considerations for Structure Pre-processing

When working with protein structures in SaprotHub, consider the following:

1. **Structure validity**: Use `is_residue_valid()` to ensure residues have all required atoms (N, CA, C, O)
2. **Chain selection**: Most functions operate on single chains; use `split_chain()` to extract chains if needed
3. **Residue numbering**: Be aware that residue numbering in PDB files may not be sequential; SaprotHub reindexes residues from 0
4. **Structure alignment**: When comparing structures, use alignment functions to ensure proper residue correspondence
5. **Performance**: For large-scale processing, consider batching operations to optimize memory usage

Sources: [saprot/data/parse.py:77-96]()

---