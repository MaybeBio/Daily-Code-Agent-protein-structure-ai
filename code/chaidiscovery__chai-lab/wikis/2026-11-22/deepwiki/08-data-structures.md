# Data Structures

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [chai_lab/data/dataset/structure/all_atom_structure_context.py](chai_lab/data/dataset/structure/all_atom_structure_context.py)
- [chai_lab/data/dataset/structure/chain.py](chai_lab/data/dataset/structure/chain.py)
- [chai_lab/data/features/token_utils.py](chai_lab/data/features/token_utils.py)
- [chai_lab/data/parsing/structure/all_atom_entity_data.py](chai_lab/data/parsing/structure/all_atom_entity_data.py)
- [chai_lab/data/parsing/structure/entity_type.py](chai_lab/data/parsing/structure/entity_type.py)
- [chai_lab/data/parsing/structure/residue.py](chai_lab/data/parsing/structure/residue.py)
- [requirements.dev](requirements.dev)

</details>



## Purpose and Scope

This document covers the core data structures used throughout the Chai-1 system, with a particular focus on the `AllAtomStructureContext` class. This class serves as the central data container for molecular structure information, bridging input processing, feature generation, and model inference. It also documents supporting structures like `AllAtomEntityData`, `Chain`, and `Residue` that facilitate the transition from raw structural files to tensorized representations.

## Core Data Entities

The system uses a hierarchy of data structures to represent molecular information from raw sequence/structure data down to atom-level tensors.

### Entity and Residue Representation

Before data is tensorized into a context, it is managed as Python objects that preserve chemical metadata.

| Class | File Path | Purpose |
| :--- | :--- | :--- |
| `AllAtomEntityData` | [chai_lab/data/parsing/structure/all_atom_entity_data.py:34-51]() | Stores metadata for a unique chemical entity (protein, ligand, etc.), including its full sequence and source PDB info. |
| `Chain` | [chai_lab/data/dataset/structure/chain.py:14-20]() | A container linking `AllAtomEntityData` with its tokenized `AllAtomStructureContext`. |
| `Residue` | [chai_lab/data/parsing/structure/residue.py:72-82]() | Represents a single monomer (amino acid, nucleotide, or ligand) and its associated `ConformerData`. |
| `ConformerData` | [chai_lab/data/parsing/structure/residue.py:19-26]() | Stores 3D positions, elements, charges, and symmetries for atoms within a residue. |

**Sources:** [chai_lab/data/parsing/structure/all_atom_entity_data.py:34-51](), [chai_lab/data/dataset/structure/chain.py:14-20](), [chai_lab/data/parsing/structure/residue.py:19-82]()

### Molecular Entity Types

The system classifies entities using the `EntityType` enum, which dictates how they are tokenized and processed.

```mermaid
graph TD
    subgraph "EntityType Classification [chai_lab/data/parsing/structure/entity_type.py]"
        ET["EntityType Enum"]
        ET --> PROTEIN["PROTEIN (0)"]
        ET --> RNA["RNA (1)"]
        ET --> DNA["DNA (2)"]
        ET --> LIGAND["LIGAND (3)"]
        ET --> POLY_HYBRID["POLYMER_HYBRID (4)"]
        ET --> GLYCAN["MANUAL_GLYCAN (7)"]
    end

    subgraph "Code Logic: get_entity_type"
        GEMMI["gemmi.Entity"] -- "Match PolymerType" --> ET
    end
```

**Sources:** [chai_lab/data/parsing/structure/entity_type.py:13-48]()

## AllAtomStructureContext

The `AllAtomStructureContext` is the primary tensorized data structure. It organizes molecular data using a hierarchical token-atom relationship, where tokens typically represent residues or small molecular fragments.

### Data Organization Hierarchy

```mermaid
graph TD
    subgraph "Molecular System [AllAtomStructureContext]"
        Structure["AllAtomStructureContext"]
    end
    
    subgraph "Token Level [n_tokens]"
        Token1["Token 0<br/>token_residue_type"]
        Token2["Token 1<br/>token_asym_id"]
        TokenN["Token N<br/>token_entity_type"]
    end
    
    subgraph "Atom Level [n_atoms]"
        Atom1["Atom 0"]
        Atom2["Atom 1"]
        AtomM["Atom M"]
    end
    
    subgraph "Indexing System"
        TokenIndex["token_index [26-30]"]
        AtomTokenIndex["atom_token_index [43]<br/>Maps atoms to tokens"]
        AtomWithinIndex["atom_within_token_index [44]<br/>Position within token"]
    end
    
    Structure --> Token1
    Structure --> Token2
    Structure --> TokenN
    
    Token1 --> Atom1
    Token1 --> Atom2
    Token2 --> AtomM
    
    TokenIndex --> Token1
    AtomTokenIndex --> Atom1
    AtomTokenIndex --> Atom2
```

**Sources:** [chai_lab/data/dataset/structure/all_atom_structure_context.py:26-73]()

### Field Categories

| Category | Purpose | Key Fields |
| :--- | :--- | :--- |
| **Token-level** | Residue/monomer properties | `token_residue_type`, `token_asym_id`, `token_entity_type`, `token_residue_index` |
| **Atom-level** | Individual atom properties | `atom_ref_pos`, `atom_ref_element`, `atom_ref_charge`, `atom_ref_name_chars` |
| **Indexing** | Token-atom relationships | `atom_token_index`, `atom_within_token_index`, `token_centre_atom_index` |
| **Structure-level** | Global metadata | `pdb_id`, `resolution`, `is_distillation` |
| **Connectivity** | Molecular bonds | `atom_covalent_bond_indices`, `symmetries` |

**Sources:** [chai_lab/data/dataset/structure/all_atom_structure_context.py:27-73]()

## Core Operations

### Data Manipulation

`AllAtomStructureContext` provides methods for subsetting and combining molecular systems.

*   **`index_select(idxs)`**: Selects a subset of tokens. It reindexes both tokens and their associated atoms, ensuring that `atom_token_index` and `atom_covalent_bond_indices` remain valid for the new subset [chai_lab/data/dataset/structure/all_atom_structure_context.py:99-194]().
*   **`merge(contexts)`**: A class method that concatenates multiple contexts into one. It calculates offsets for token and atom indices to maintain the global mapping [chai_lab/data/dataset/structure/all_atom_structure_context.py:360-495]().
*   **`to(device)`**: Transfers all constituent tensors to the specified hardware (CPU/GPU) [chai_lab/data/dataset/structure/all_atom_structure_context.py:497-503]().

### Reference Atom Utilities

The system uses specific atoms as "anchors" for tokens (e.g., C-alpha for proteins). The utility `token_utils.py` provides functions to extract these:
*   `get_centre_positions_and_mask`: Retrieves coordinates for the atom defined by `token_centre_atom_index` [chai_lab/data/features/token_utils.py:13-30]().
*   `get_token_reference_atom_positions_and_mask`: Retrieves positions for reference atoms (like CB for proteins or C2/C4 for nucleic acids) [chai_lab/data/features/token_utils.py:34-54]().

**Sources:** [chai_lab/data/dataset/structure/all_atom_structure_context.py:99-503](), [chai_lab/data/features/token_utils.py:13-54]()

## Validation and Integrity

The `__post_init__` method of `AllAtomStructureContext` enforces structural constraints:
1.  **Coordinate Check**: Errors if no valid coordinates are found while `num_atoms > 0` [chai_lab/data/dataset/structure/all_atom_structure_context.py:78-80]().
2.  **Mask Consistency**: Verifies that if an atom exists, its parent token must also be marked as existing [chai_lab/data/dataset/structure/all_atom_structure_context.py:84-88]().
3.  **Bond Validity**: Ensures `atom_covalent_bond_indices` do not exceed the total atom count [chai_lab/data/dataset/structure/all_atom_structure_context.py:91-92]().

**Sources:** [chai_lab/data/dataset/structure/all_atom_structure_context.py:74-93]()

## Integration with System Architecture

The data structures bridge the gap between input parsing and the inference engine.

```mermaid
graph TB
    subgraph "Input Parsing [chai_lab/data/parsing]"
        FASTA["FASTA/CIF Parser"]
        EntityData["AllAtomEntityData"]
        ResidueData["Residue/ConformerData"]
    end
    
    subgraph "Core Structure [chai_lab/data/dataset/structure]"
        AllAtomCtx["AllAtomStructureContext"]
        ChainObj["Chain"]
    end
    
    subgraph "Inference Engine [chai_lab/model]"
        FeatureCtx["AllAtomFeatureContext"]
        Model["Chai-1 Model"]
    end
    
    FASTA --> EntityData
    EntityData --> ResidueData
    ResidueData -- "Tensorization" --> AllAtomCtx
    AllAtomCtx --> ChainObj
    
    AllAtomCtx -- "Feature Factory" --> FeatureCtx
    FeatureCtx --> Model
```

**Sources:** [chai_lab/data/dataset/structure/all_atom_structure_context.py:1-536](), [chai_lab/data/parsing/structure/all_atom_entity_data.py:1-134](), [chai_lab/data/dataset/structure/chain.py:1-27]()

---