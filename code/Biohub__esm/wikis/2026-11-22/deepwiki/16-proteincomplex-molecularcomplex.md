# ProteinComplex & MolecularComplex

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [esm/utils/structure/metrics.py](esm/utils/structure/metrics.py)
- [esm/utils/structure/molecular_complex.py](esm/utils/structure/molecular_complex.py)
- [esm/utils/structure/normalize_coordinates.py](esm/utils/structure/normalize_coordinates.py)
- [esm/utils/structure/predicted_aligned_error.py](esm/utils/structure/predicted_aligned_error.py)
- [esm/utils/structure/protein_complex.py](esm/utils/structure/protein_complex.py)

</details>



This page details the high-level data structures used for representing multi-chain assemblies and heterogeneous molecular systems. While `ProteinChain` handles individual protein units, `ProteinComplex` manages multi-chain protein assemblies, and `MolecularComplex` provides a unified, flat atom representation for systems containing proteins, nucleic acids, and ligands.

## ProteinComplex

The `ProteinComplex` class is a frozen dataclass designed to represent an entire protein assembly using the Atom37 format [esm/utils/structure/protein_complex.py:150-167](). It aggregates multiple chains and maintains metadata regarding entity and symmetry relationships.

### Data Structure and Validation
The class stores coordinate data, sequence information, and identifiers as NumPy arrays. Upon initialization, it validates that all arrays (positions, masks, indices, etc.) match the length of the sequence [esm/utils/structure/protein_complex.py:170-183]().

| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | `str` | Unique identifier for the complex. |
| `sequence` | `str` | Full sequence, using `|` as a chain break delimiter. |
| `entity_id` | `np.ndarray` | Maps residues to unique sequences (entities). |
| `chain_id` | `np.ndarray` | Maps residues to specific chain instances. |
| `atom37_positions` | `np.ndarray` | [L, 37, 3] coordinates in Atom37 format. |
| `metadata` | `ProteinComplexMetadata` | Entity/chain lookups and assembly composition. |

### Assembly and Transformation
`ProteinComplex` supports biological assembly generation from mmCIF files. It uses `_parse_operation_expression` to interpret symmetry operations [esm/utils/structure/protein_complex.py:57-86]() and `_apply_transformations_fast` to generate copies of chains based on rotation and translation matrices [esm/utils/structure/protein_complex.py:89-114]().

### Key Methods
*   **`from_mmcif`**: Parses an mmCIF file or `MmcifWrapper` into a `ProteinComplex`, supporting specific assembly IDs [esm/utils/structure/protein_complex.py:231-309]().
*   **`to_mmcif`**: Exports the complex to an mmCIF file format [esm/utils/structure/protein_complex.py:466-527]().
*   **`to_pdb`**: Exports the complex to a PDB file format [esm/utils/structure/protein_complex.py:436-464]().
*   **`chain_iter`**: Returns an iterator of `ProteinChain` objects for each individual chain in the complex [esm/utils/structure/protein_complex.py:381-403]().

**Sources:** [esm/utils/structure/protein_complex.py:57-114](), [esm/utils/structure/protein_complex.py:150-527]()

---

## MolecularComplex

`MolecularComplex` is a more general representation designed to support heterogeneous systems, including RNA, DNA, and ligands, which do not fit the standard protein-only Atom37 model [esm/utils/structure/molecular_complex.py:77-83](). It uses a flat atom representation where atoms are indexed globally and mapped back to "tokens" (residues or molecules) [esm/utils/structure/molecular_complex.py:89-93]().

### Flat Atom Representation
Unlike `ProteinComplex`, which assumes a fixed 37-atom slot per residue, `MolecularComplex` stores:
*   **`atom_positions`**: A flat `[N_atoms, 3]` array [esm/utils/structure/molecular_complex.py:89]().
*   **`token_to_atoms`**: A `[N_tokens, 2]` array storing the start and end indices for each token's atoms in the flat array [esm/utils/structure/molecular_complex.py:93]().

### Code Entity Space: Molecular Mapping
This diagram shows how `MolecularComplex` bridges high-level biological sequences to flat coordinate arrays.

```mermaid
graph TD
    subgraph "Natural Language Space"
        P1["Protein Sequence (MET KYS...)"]
        L1["Ligand (ATP)"]
    end

    subgraph "Code Entity Space: MolecularComplex"
        MC["MolecularComplex [esm/utils/structure/molecular_complex.py:77]"]
        Seq["sequence: list[str]"]
        T2A["token_to_atoms: np.ndarray [N_tokens, 2]"]
        APos["atom_positions: np.ndarray [N_atoms, 3]"]
        Meta["MolecularComplexMetadata [esm/utils/structure/molecular_complex.py:53]"]
    end

    P1 --> MC
    L1 --> MC
    MC --> Seq
    MC --> T2A
    MC --> APos
    T2A -- "slices" --> APos
    MC --> Meta
```
**Sources:** [esm/utils/structure/molecular_complex.py:53-109]()

### Conversions
*   **`from_protein_complex`**: Converts an Atom37 `ProteinComplex` into the flat `MolecularComplex` format by filtering masked atoms [esm/utils/structure/molecular_complex.py:176-242]().
*   **`to_protein_complex`**: Attempts to reconstruct a `ProteinComplex` from a `MolecularComplex`, provided the tokens are valid amino acids [esm/utils/structure/molecular_complex.py:244-328]().

**Sources:** [esm/utils/structure/molecular_complex.py:176-328]()

---

## Metric Methods

The repository provides several utilities for evaluating the quality of complexes, primarily located in `esm.utils.structure.metrics`.

### Structural Metrics
*   **RMSD**: Computed via `compute_rmsd` [esm/utils/structure/metrics.py:14](), which uses Procrustes alignment.
*   **LDDT**: `compute_lddt` calculates the Local Distance Difference Test, measuring local environment preservation without requiring global alignment [esm/utils/structure/metrics.py:140-238]().
*   **DockQ**: For protein complexes, the `compute_dockq` method (via external tool or internal logic) evaluates interface quality [esm/utils/structure/protein_complex.py:529-616]().

### Complex Evaluation Flow
This diagram illustrates the data flow from structural prediction to metric calculation.

```mermaid
graph LR
    subgraph "Inference Output"
        Result["MolecularComplexResult [esm/utils/structure/molecular_complex.py:35]"]
        MC["MolecularComplex"]
    end

    subgraph "Metric Evaluation [esm/utils/structure/metrics.py]"
        RMSD["compute_rmsd [line 14]"]
        LDDT["compute_lddt [line 140]"]
        DockQ["compute_dockq [esm/utils/structure/protein_complex.py:529]"]
    end

    Result --> MC
    MC -- "atom_positions" --> RMSD
    MC -- "atom_positions" --> LDDT
    MC -- "chain_id" --> DockQ
```
**Sources:** [esm/utils/structure/metrics.py:14](), [esm/utils/structure/metrics.py:140-238](), [esm/utils/structure/molecular_complex.py:35-44](), [esm/utils/structure/protein_complex.py:529-616]()

---

## Serialization and Blobs

To facilitate efficient storage and network transfer, complexes can be serialized into compressed "blobs".

1.  **Serialization**: The `to_blob` method uses `msgpack` and `brotli` compression to convert the dataclass into a byte string [esm/utils/structure/protein_complex.py:405-419]().
2.  **Deserialization**: `from_blob` reverses this process, reconstructing the full `ProteinComplex` or `MolecularComplex` object [esm/utils/structure/protein_complex.py:421-434]().

This mechanism is used by the `_BaseForgeInferenceClient` when `return_bytes` is requested [esm/sdk/base_forge_client.py:81-83]().

**Sources:** [esm/utils/structure/protein_complex.py:405-434](), [esm/sdk/base_forge_client.py:70-84]()

---

## Input Construction for Prediction

The `StructurePredictionInput` class acts as the bridge between raw sequences/ligands and the ESMFold2 model [esm/utils/structure/input_builder.py:75-80]().

*   **`ProteinInput` / `RNAInput` / `DNAInput`**: Represent individual polymer chains [esm/utils/structure/input_builder.py:24-43]().
*   **`LigandInput`**: Represents non-polymer molecules via SMILES or CCD codes [esm/utils/structure/input_builder.py:46-50]().
*   **Conditioning**: Supports `PocketConditioning`, `DistogramConditioning`, and `CovalentBond` constraints to guide the folding process [esm/utils/structure/input_builder.py:53-73]().

The `serialize_structure_prediction_input` function converts these complex objects into a JSON-serializable dictionary for API requests [esm/utils/structure/input_builder.py:82-153]().

**Sources:** [esm/utils/structure/input_builder.py:24-153]()

---