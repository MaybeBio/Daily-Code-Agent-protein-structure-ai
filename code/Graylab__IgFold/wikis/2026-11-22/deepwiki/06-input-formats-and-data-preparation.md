# Input Formats and Data Preparation

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [igfold/model/interface.py](igfold/model/interface.py)
- [igfold/utils/fasta.py](igfold/utils/fasta.py)
- [igfold/utils/pdb.py](igfold/utils/pdb.py)

</details>



This page documents the input formats accepted by IgFold and the data preparation steps required for antibody structure prediction. It covers sequence input requirements, template structure usage, and the processing pipeline that converts raw inputs into the standardized format required by the IgFold model.

For information about using the processed data with the main API, see [IgFoldRunner API](#4.1). For details about the internal model input structure, see [Core Architecture](#5).

## Supported Input Formats

IgFold accepts antibody sequences in multiple formats and provides utilities to process template structures for enhanced prediction accuracy.

### Sequence Input Formats

#### FASTA Format
The primary input format for antibody sequences is FASTA, with specific chain identification conventions:

```mermaid
graph TD
    FASTA["FASTA File"] --> PARSE["get_fasta_chain_seq()"]
    PARSE --> CHAIN_ID["Chain ID Detection"]
    CHAIN_ID --> H_CHAIN[":H (Heavy Chain)"]
    CHAIN_ID --> L_CHAIN[":L (Light Chain)"]
    H_CHAIN --> SEQ_DICT["Sequence Dictionary"]
    L_CHAIN --> SEQ_DICT
    SEQ_DICT --> VALIDATION["Sequence Validation"]
```

**FASTA Chain Identification**
- Heavy chain sequences must include `:H` in the sequence identifier
- Light chain sequences must include `:L` in the sequence identifier
- Example header format: `>antibody_name:H` or `>antibody_name:L`

#### Dictionary Format
Sequences can also be provided as Python dictionaries:

| Key | Value | Description |
|-----|--------|-------------|
| `"H"` | `str` | Heavy chain amino acid sequence |
| `"L"` | `str` | Light chain amino acid sequence (optional) |

Sources: [igfold/utils/fasta.py:4-18]()

### Template Structure Input

Template PDB structures can be provided to improve prediction accuracy through structural templating:

```mermaid
graph TD
    PDB["Template PDB File"] --> PARSE_PDB["PDBParser"]
    PARSE_PDB --> COORDS["get_atom_coords()"]
    COORDS --> ATOMS["Atom Coordinates"]
    ATOMS --> N["N atoms"]
    ATOMS --> CA["CA atoms"] 
    ATOMS --> C["C atoms"]
    ATOMS --> CB["CB atoms"]
    ATOMS --> O["O atoms"]
    
    FASTA_REF["Reference FASTA"] --> ALIGN["Sequence Alignment"]
    ATOMS --> ALIGN
    ALIGN --> TEMPLATE_COORDS["template_coords"]
    ALIGN --> TEMPLATE_MASK["template_mask"]
```

**Supported Template Features:**
- Standard PDB format with ATOM records
- Multi-chain antibody structures
- Automatic missing atom placement for CB and O atoms
- Chain reordering and renumbering capabilities

Sources: [igfold/utils/pdb.py:194-252](), [igfold/utils/pdb.py:160-192]()

## Sequence Requirements and Validation

### Amino Acid Sequences
IgFold expects standard single-letter amino acid codes. The system handles:

- **Heavy chains**: Typically 110-130 residues for antibody variable domains
- **Light chains**: Typically 105-115 residues for antibody variable domains  
- **Standard amino acids**: All 20 canonical amino acids supported
- **Non-standard residues**: Converted or flagged during processing

### Chain Processing Pipeline

```mermaid
flowchart TD
    INPUT["Raw Sequence Input"] --> FORMAT_CHECK["Format Detection"]
    FORMAT_CHECK --> FASTA_PATH["FASTA File"]
    FORMAT_CHECK --> DICT_PATH["Dictionary"]
    
    FASTA_PATH --> FASTA_PARSE["get_fasta_chain_dict()"]
    DICT_PATH --> DICT_VALIDATE["Dictionary Validation"]
    
    FASTA_PARSE --> CHAIN_EXTRACT["Chain Extraction"]
    DICT_VALIDATE --> CHAIN_EXTRACT
    
    CHAIN_EXTRACT --> H_SEQ["Heavy Chain Sequence"]
    CHAIN_EXTRACT --> L_SEQ["Light Chain Sequence"]
    
    H_SEQ --> SEQ_VALIDATE["Sequence Validation"]
    L_SEQ --> SEQ_VALIDATE
    
    SEQ_VALIDATE --> ANTIBERTY["AntiBERTy Processing"]
    ANTIBERTY --> EMBEDDINGS["Sequence Embeddings"]
    ANTIBERTY --> ATTENTIONS["Attention Weights"]
    
    EMBEDDINGS --> IGFOLD_INPUT["IgFoldInput"]
    ATTENTIONS --> IGFOLD_INPUT
```

Sources: [igfold/utils/fasta.py:13-18](), [igfold/model/interface.py:7-20]()

## Template Structure Processing

When template structures are provided, IgFold performs sophisticated alignment and coordinate extraction:

### PDB Processing Workflow

```mermaid
graph TD
    PDB_FILE["Template PDB"] --> PDB_PARSER["PDBParser"]
    PDB_PARSER --> STRUCTURE["Bio.PDB Structure"]
    
    STRUCTURE --> CHAINS["Chain Extraction"]
    CHAINS --> RESIDUES["Residue Lists"]
    
    RESIDUES --> CONTINUOUS["get_continuous_ranges()"]
    CONTINUOUS --> PEPTIDE_BONDS["Peptide Bond Validation"]
    
    FASTA_INPUT["FASTA Sequence"] --> ALIGNMENT["Sequence Alignment"]
    PEPTIDE_BONDS --> ALIGNMENT
    
    ALIGNMENT --> COORD_EXTRACT["Coordinate Extraction"]
    COORD_EXTRACT --> BACKBONE["Backbone Atoms (N,CA,C)"]
    COORD_EXTRACT --> SIDECHAIN["Side Chain (CB)"]
    COORD_EXTRACT --> CARBONYL["Carbonyl (O)"]
    
    BACKBONE --> MISSING_ATOM["place_missing_cb_o()"]
    SIDECHAIN --> MISSING_ATOM
    CARBONYL --> MISSING_ATOM
    
    MISSING_ATOM --> ATOM_COORDS["Complete Atom Coordinates"]
    ATOM_COORDS --> TEMPLATE_INPUT["Template Input Tensors"]
```

**Key Processing Functions:**
- `get_atom_coords()`: Extracts atomic coordinates from PDB structures
- `get_continuous_ranges()`: Identifies continuous peptide segments 
- `place_missing_cb_o()`: Reconstructs missing CB and O atoms using geometric constraints

Sources: [igfold/utils/pdb.py:139-157](), [igfold/utils/pdb.py:194-251]()

## Data Processing Utilities

### PDB Manipulation Functions

| Function | Purpose | Input | Output |
|----------|---------|--------|---------|
| `pdb2fasta()` | Convert PDB to FASTA | PDB file path | FASTA string |
| `get_pdb_chain_seq()` | Extract chain sequence | PDB file, chain ID | Amino acid sequence |
| `renumber_pdb()` | AbNumber renumbering | PDB file path | Renumbered PDB |
| `reorder_pdb_chains()` | Reorder chains | PDB file, chain order | Reordered PDB |
| `count_pdb_chains()` | Count chains | PDB file path | Integer count |

### Coordinate Processing

```mermaid
graph LR
    RAW_PDB["Raw PDB Coordinates"] --> EXTRACT["get_atom_coord()"]
    EXTRACT --> ATOM_TYPES["Atom Type Specific"]
    ATOM_TYPES --> N_COORDS["N Coordinates"]
    ATOM_TYPES --> CA_COORDS["CA Coordinates"] 
    ATOM_TYPES --> C_COORDS["C Coordinates"]
    ATOM_TYPES --> CB_COORDS["CB Coordinates"]
    ATOM_TYPES --> O_COORDS["O Coordinates"]
    
    CB_COORDS --> MISSING_CHECK["Missing Atom Check"]
    O_COORDS --> MISSING_CHECK
    MISSING_CHECK --> GEOMETRIC["Geometric Reconstruction"]
    GEOMETRIC --> COMPLETE["Complete Coordinates"]
```

**Coordinate Tensors:**
- All coordinates stored as PyTorch tensors
- Shape: `[num_residues, 3]` for each atom type
- Automatic masking for missing atoms
- Geometric reconstruction for standard missing atoms

Sources: [igfold/utils/pdb.py:120-137](), [igfold/utils/pdb.py:254-265]()

## IgFoldInput Data Structure

The processed input data is consolidated into the `IgFoldInput` dataclass:

```mermaid
classDiagram
    class IgFoldInput {
        +List~List~torch.FloatTensor~~ embeddings
        +List~List~torch.FloatTensor~~ attentions  
        +Optional~torch.FloatTensor~ template_coords
        +Optional~torch.BoolTensor~ template_mask
        +Optional~torch.BoolTensor~ batch_mask
        +Optional~torch.BoolTensor~ align_mask
        +Optional~torch.FloatTensor~ coords_label
        +Optional~bool~ return_embeddings
    }
```

**Field Descriptions:**
- `embeddings`: AntiBERTy sequence embeddings per layer
- `attentions`: Multi-head attention weights per layer  
- `template_coords`: Template structure coordinates (optional)
- `template_mask`: Mask indicating valid template positions
- `batch_mask`: Mask for batch processing
- `align_mask`: Alignment mask between sequence and template

Sources: [igfold/model/interface.py:6-20]()

## CDR Loop Processing

IgFold includes specialized utilities for CDR (Complementarity-Determining Region) identification and processing:

### CDR Identification Pipeline

```mermaid
graph TD
    CHOTHIA_PDB["Chothia-numbered PDB"] --> CDR_FUNC["cdr_indices()"]
    CDR_FUNC --> CDR_RANGES["CDR Range Dictionary"]
    
    CDR_RANGES --> H1["H1: 26-32"]
    CDR_RANGES --> H2["H2: 52-56"] 
    CDR_RANGES --> H3["H3: 95-102"]
    CDR_RANGES --> L1["L1: 24-34"]
    CDR_RANGES --> L2["L2: 50-56"]
    CDR_RANGES --> L3["L3: 89-97"]
    
    H1 --> BINARY_SEARCH["Binary Search Mapping"]
    H2 --> BINARY_SEARCH
    H3 --> BINARY_SEARCH
    L1 --> BINARY_SEARCH
    L2 --> BINARY_SEARCH
    L3 --> BINARY_SEARCH
    
    BINARY_SEARCH --> INDICES["Sequence Indices"]
```

**CDR Processing Functions:**
- `cdr_indices()`: Maps Chothia numbering to sequence indices
- `get_cdr_range_dict()`: Returns all CDR ranges for a structure
- `h3_indices()`: Specialized H3 loop identification

Sources: [igfold/utils/pdb.py:314-403]()

## AbNumber Integration

IgFold integrates with the AbNumber web service for antibody renumbering:

### Renumbering Workflow

```mermaid
sequenceDiagram
    participant User
    participant IgFold
    participant AbNumber as "AbNumber Web Service"
    participant PDB as "PDB File"
    
    User->>IgFold: renumber_pdb(old_pdb)
    IgFold->>PDB: Read PDB file
    PDB-->>IgFold: Raw PDB data
    IgFold->>AbNumber: POST request with PDB
    AbNumber-->>IgFold: Renumbered PDB response
    IgFold->>PDB: Write renumbered PDB
    IgFold-->>User: Success/failure status
```

**Renumbering Features:**
- Automatic retry logic for network failures
- Chothia numbering scheme by default
- Heavy and light chain processing
- Error handling and validation

Sources: [igfold/utils/pdb.py:21-59]()

---