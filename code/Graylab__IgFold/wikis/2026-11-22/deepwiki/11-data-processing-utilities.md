# Data Processing Utilities

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [igfold/utils/constants.py](igfold/utils/constants.py)
- [igfold/utils/coordinates.py](igfold/utils/coordinates.py)
- [igfold/utils/geometry.py](igfold/utils/geometry.py)
- [igfold/utils/pdb.py](igfold/utils/pdb.py)

</details>



This document covers IgFold's core data processing utilities that handle PDB files, coordinate extraction, geometric calculations, and antibody-specific processing. These utilities form the foundation layer that supports the structure prediction pipeline and refinement components.

For information about the overall processing pipeline workflow, see [Processing Pipeline](#5.2). For details about neural network model components, see [IgFold Model](#5.1).

## Overview

The data processing utilities are organized into four main modules that work together to handle structural data:

```mermaid
graph TD
    subgraph "PDB Processing"
        PDB_UTILS["igfold.utils.pdb"]
        PDB_FUNCS["renumber_pdb<br/>get_atom_coords<br/>save_PDB<br/>cdr_indices"]
    end
    
    subgraph "Geometric Operations"
        GEOM_UTILS["igfold.utils.geometry"]
        GEOM_FUNCS["normed_vec<br/>dist<br/>angle<br/>dihedral"]
    end
    
    subgraph "Coordinate Manipulation"
        COORD_UTILS["igfold.utils.coordinates"] 
        COORD_FUNCS["place_fourth_atom<br/>get_ideal_coords<br/>place_o_coords"]
    end
    
    subgraph "Physical Constants"
        CONST_UTILS["igfold.utils.constants"]
        CONST_VALS["BL_N_CA<br/>BA_N_CA_C<br/>VDW_N"]
    end
    
    PDB_UTILS --> PDB_FUNCS
    GEOM_UTILS --> GEOM_FUNCS
    COORD_UTILS --> COORD_FUNCS
    CONST_UTILS --> CONST_VALS
    
    PDB_FUNCS --> COORD_FUNCS
    GEOM_FUNCS --> COORD_FUNCS
    CONST_VALS --> COORD_FUNCS
```

**Sources:** [igfold/utils/pdb.py:1-515](), [igfold/utils/geometry.py:1-77](), [igfold/utils/coordinates.py:1-76](), [igfold/utils/constants.py:1-22]()

## PDB File Processing

The `igfold.utils.pdb` module provides comprehensive tools for reading, writing, and manipulating PDB files. The main data flow processes raw PDB files into structured coordinate tensors:

```mermaid
flowchart TD
    INPUT_PDB["PDB File Input"] --> PARSE_PDB["PDBParser.get_structure"]
    FASTA_INPUT["FASTA File (optional)"] --> PARSE_PDB
    
    PARSE_PDB --> EXTRACT_COORDS["get_atom_coords"]
    EXTRACT_COORDS --> ATOM_EXTRACTION["Extract N, CA, C, CB, O coordinates"]
    
    ATOM_EXTRACTION --> MISSING_ATOMS["place_missing_cb_o"]
    MISSING_ATOMS --> COORD_TENSORS["PyTorch Coordinate Tensors"]
    
    COORD_TENSORS --> MASKS["get_atom_coords_mask"]
    MASKS --> FINAL_OUTPUT["Structured Coordinate Data"]
    
    subgraph "Chain Processing"
        CHAIN_COUNT["count_pdb_chains"]
        CHAIN_REORDER["reorder_pdb_chains"] 
        CHAIN_SEQ["get_pdb_chain_seq"]
    end
    
    subgraph "CDR Identification"
        CDR_INDICES["cdr_indices"]
        CDR_RANGES["get_cdr_range_dict"]
        H3_INDICES["h3_indices"]
    end
    
    subgraph "AbNumber Integration"
        RENUMBER["renumber_pdb"]
        ABNUMBER_SERVICE["AbNum Web Service"]
        RENUMBER --> ABNUMBER_SERVICE
    end
```

**Sources:** [igfold/utils/pdb.py:194-251](), [igfold/utils/pdb.py:21-59](), [igfold/utils/pdb.py:314-378]()

### Coordinate Extraction

The primary function `get_atom_coords` extracts backbone and side-chain coordinates from PDB files:

| Function | Purpose | Input | Output |
|----------|---------|--------|--------|
| `get_atom_coords` | Extract all atom coordinates | PDB file, optional FASTA | Dict of coordinate tensors |
| `get_atom_coord` | Get single atom coordinate | Residue, atom type | 3D coordinate array |
| `get_cb_or_ca_coord` | Get CB coordinate (CA fallback) | Residue | 3D coordinate array |
| `place_missing_cb_o` | Fill missing CB and O atoms | Coordinate dict | Updated coordinates |

**Sources:** [igfold/utils/pdb.py:194-251](), [igfold/utils/pdb.py:120-137](), [igfold/utils/pdb.py:160-192]()

### Chain Management

Chain processing functions handle multi-chain antibody structures:

- `count_pdb_chains`: Returns the number of chains in a PDB file [igfold/utils/pdb.py:61-68]()
- `reorder_pdb_chains`: Reorders chains according to specified sequence [igfold/utils/pdb.py:71-117]()
- `get_pdb_chain_seq`: Extracts amino acid sequence from specific chain [igfold/utils/pdb.py:294-311]()

### CDR Loop Identification

Antibody-specific processing includes CDR (Complementarity Determining Region) identification using Chothia numbering:

```mermaid
graph TD
    CHOTHIA_PDB["Chothia Numbered PDB"] --> CDR_FUNC["cdr_indices"]
    CDR_TYPE["CDR Type (h1, h2, h3, l1, l2, l3)"] --> CDR_FUNC
    
    CDR_FUNC --> CHOTHIA_RANGES["Chothia Range Dictionary"]
    CHOTHIA_RANGES --> BINARY_SEARCH["Binary Search on Residue IDs"]
    BINARY_SEARCH --> CDR_START_END["CDR Start/End Indices"]
    
    subgraph "CDR Ranges"
        H1["h1: (26, 32)"]
        H2["h2: (52, 56)"]
        H3["h3: (95, 102)"]
        L1["l1: (24, 34)"]
        L2["l2: (50, 56)"]
        L3["l3: (89, 97)"]
    end
```

**Sources:** [igfold/utils/pdb.py:314-378](), [igfold/utils/pdb.py:381-402]()

## Geometric Calculations

The `igfold.utils.geometry` module provides fundamental geometric operations for structural calculations:

| Function | Purpose | Formula |
|----------|---------|---------|
| `normed_vec` | Vector normalization | `vec / ||vec||` |
| `dist` | Euclidean distance | `sqrt(sum((x1-x2)²))` |
| `angle` | Bond angle | `arccos(a·b)` |
| `dihedral` | Dihedral angle | `atan2(y, x)` using cross products |
| `coords_to_frame` | Local coordinate frame | N-CA-C backbone frame |

**Sources:** [igfold/utils/geometry.py:7-77]()

### Reference Frame Calculations

The `coords_to_frame` function converts backbone coordinates into local reference frames for structural analysis:

```mermaid
graph LR
    COORDS["Backbone Coordinates<br/>(N, CA, C, O)"] --> VECTORS["Vector Calculations"]
    VECTORS --> CA_N["CA-N vector"]
    VECTORS --> CA_C["CA-C vector"]
    
    CA_N --> N1["n1 = normalized CA-N"]
    CA_C --> N2["n2 = cross(n1, CA-C)"]
    N1 --> N3["n3 = cross(n1, n2)"]
    N2 --> N3
    
    N1 --> ROTATION_MATRIX["Rotation Matrix [n1, n2, n3]"]
    N2 --> ROTATION_MATRIX
    N3 --> ROTATION_MATRIX
    
    ROTATION_MATRIX --> LOCAL_FRAME["Local Coordinate Frame"]
```

**Sources:** [igfold/utils/geometry.py:61-77]()

## Coordinate Manipulation

The `igfold.utils.coordinates` module handles precise atom placement and coordinate transformations:

### Fourth Atom Placement

The `place_fourth_atom` function uses geometric constraints to determine atom positions:

```mermaid
graph TD
    INPUT_ATOMS["Three Known Atoms<br/>(A, B, C)"] --> CONSTRAINTS["Geometric Constraints"]
    CONSTRAINTS --> BOND_LENGTH["Bond Length"]
    CONSTRAINTS --> PLANAR_ANGLE["Planar Angle"] 
    CONSTRAINTS --> DIHEDRAL_ANGLE["Dihedral Angle"]
    
    BOND_LENGTH --> CALC["Coordinate Calculation"]
    PLANAR_ANGLE --> CALC
    DIHEDRAL_ANGLE --> CALC
    
    CALC --> BC_VEC["bc_vec = normalized(B-C)"]
    CALC --> N_VEC["n_vec = cross(B-A, bc_vec)"]
    CALC --> M_VEC["m_vec basis vectors"]
    
    BC_VEC --> D_COORD["Fourth Atom Position"]
    N_VEC --> D_COORD
    M_VEC --> D_COORD
```

**Sources:** [igfold/utils/coordinates.py:4-30]()

### Ideal Coordinates

Standard backbone geometry is provided through `get_ideal_coords` with ideal bond lengths and angles:

- N: `[0, 0, -1.458]`
- CA: `[0, 0, 0]` (reference point)
- CB: `[0, 1.426, 0.531]`
- C: Calculated using `place_fourth_atom`

**Sources:** [igfold/utils/coordinates.py:33-54]()

## Physical Constants

The `igfold.utils.constants` module defines standard structural parameters from Engh and Huber:

| Constant Type | Examples | Value (Å or degrees) |
|---------------|----------|---------------------|
| Bond Lengths | `BL_N_CA`, `BL_CA_C`, `BL_C_N` | 1.459, 1.525, 1.336 |
| Bond Angles | `BA_N_CA_C`, `BA_CA_C_N` | 111.0°, 117.2° |
| VdW Radii | `VDW_N`, `VDW_C` | 1.55, 1.7 |

**Sources:** [igfold/utils/constants.py:1-22]()

## AbNumber Integration

PDB renumbering uses the AbNumber web service for consistent antibody numbering:

```mermaid
sequenceDiagram
    participant CLIENT as "renumber_pdb"
    participant ABNUM as "AbNum Web Service"
    participant FILE as "PDB File"
    
    CLIENT->>FILE: Read PDB file
    CLIENT->>ABNUM: POST pdb file with parameters
    Note over ABNUM: scheme="-c" (Chothia)<br/>output="-HL"<br/>plain="1"
    
    alt Success
        ABNUM-->>CLIENT: Renumbered PDB text
        CLIENT->>FILE: Write renumbered PDB
    else Failure
        ABNUM-->>CLIENT: Error response
        CLIENT->>CLIENT: Retry with exponential backoff
    end
```

**Sources:** [igfold/utils/pdb.py:21-59]()

## Structure Output

The `save_PDB` function writes coordinate tensors back to standard PDB format:

| Parameter | Purpose | Type |
|-----------|---------|------|
| `coords` | Atom coordinates | `torch.Tensor` |
| `seq` | Amino acid sequence | `str` |
| `chains` | Chain identifiers | `List[str]` |
| `error` | B-factor values | `torch.Tensor` |
| `delim` | Chain boundaries | `List[int]` |

The function handles chain assignment, residue numbering, and proper PDB formatting including TER and END records.

**Sources:** [igfold/utils/pdb.py:428-478]()

---