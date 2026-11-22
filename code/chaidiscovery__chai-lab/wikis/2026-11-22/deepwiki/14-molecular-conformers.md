# Molecular Conformers

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [chai_lab/data/parsing/templates/m8.py](chai_lab/data/parsing/templates/m8.py)
- [chai_lab/data/sources/rdkit.py](chai_lab/data/sources/rdkit.py)
- [tests/test_rdkit.py](tests/test_rdkit.py)

</details>



This document covers the molecular conformer generation system in chai-lab, which is responsible for creating 3D molecular structures from chemical representations like SMILES strings or Chemical Component Dictionary (CCD) codes. The system primarily handles ligand conformer generation using RDKit, with caching mechanisms for performance optimization.

For information about parsing molecular sequences and entity type identification, see [FASTA and Sequence Parsing](./4.1) and [Entity Type Identification](./4.2).

## System Overview

The conformer generation system provides two main pathways for obtaining 3D molecular structures:

1. **Cached Conformers**: Pre-computed conformers for standard residues and common ligands stored in the Chemical Component Dictionary.
2. **Dynamic Generation**: Real-time conformer generation from SMILES strings for novel ligands.

The system is built around the `RefConformerGenerator` class, which manages both cached and dynamically generated conformers, ensuring consistent data structures and handling edge cases in molecular structure generation.

### Code Entity Space Bridge: Conformer Generation

The following diagram maps the high-level generation process to specific code entities within `chai_lab/data/sources/rdkit.py`.

```mermaid
graph TB
    subgraph "Input Sources"
        SMILES["SMILES String"]
        CCD["CCD Code"]
        Cache["cached_conformers.apkl"]
    end
    
    subgraph "RefConformerGenerator [chai_lab/data/sources/rdkit.py]"
        Generator["RefConformerGenerator"]
        GetMethod["get(residue_name)"]
        GenerateMethod["generate(smiles)"]
    end
    
    subgraph "RDKit Processing"
        MolFromSmiles["Chem.MolFromSmiles"]
        AddHs["Chem.AddHs"]
        EmbedConfs["rdDistGeom.EmbedMultipleConfs"]
        DetermineBonds["DetermineBonds"]
        GetSymmetries["get_intra_res_atom_symmetries"]
    end
    
    subgraph "Data Structures"
        ConformerData["ConformerData [chai_lab/data/parsing/structure/residue.py]"]
        Position["position: torch.Tensor"]
        Element["element: torch.Tensor"]
        Charge["charge: torch.Tensor"]
        AtomNames["atom_names: list[str]"]
        Bonds["bonds: list[tuple]"]
        Symmetries["symmetries: torch.Tensor"]
    end
    
    CCD --> GetMethod
    SMILES --> GenerateMethod
    Cache --> GetMethod
    
    GetMethod --> ConformerData
    GenerateMethod --> MolFromSmiles
    MolFromSmiles --> AddHs
    AddHs --> EmbedConfs
    EmbedConfs --> DetermineBonds
    DetermineBonds --> GetSymmetries
    GetSymmetries --> ConformerData
    
    ConformerData --> Position
    ConformerData --> Element
    ConformerData --> Charge
    ConformerData --> AtomNames
    ConformerData --> Bonds
    ConformerData --> Symmetries
```

Sources: [chai_lab/data/sources/rdkit.py:38-175](), [chai_lab/data/parsing/structure/residue.py:1-25]()

## Conformer Generation Process

The conformer generation process involves several steps to ensure high-quality 3D structures:

### Dynamic Generation from SMILES

When generating conformers from SMILES strings via `RefConformerGenerator.generate`, the system follows a standardized pipeline using `ETKDGv3` [chai_lab/data/sources/rdkit.py:144-175]():

1. **Molecule Creation**: Convert SMILES to RDKit molecule object using `Chem.MolFromSmiles`.
2. **Hydrogen Addition**: Add explicit hydrogens via `Chem.AddHs` for accurate geometry.
3. **3D Embedding**: Generate 3D coordinates using the `ETKDGv3` algorithm with `useSmallRingTorsions=True` and `enforceChirality=True`.
4. **Bond Determination**: Infer bond connectivity and types.
5. **Symmetry Calculation**: Compute atom symmetries using `get_intra_res_atom_symmetries`.
6. **Data Extraction**: Convert to `ConformerData` format via `_load_ref_conformer_from_rdkit`.

### ETKDGv3 Parameters

The generator uses specific parameters for `rdDistGeom.EmbedMultipleConfs` to ensure convergence and quality:

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `useSmallRingTorsions` | `True` | Better handling of small rings [chai_lab/data/sources/rdkit.py:153]() |
| `randomSeed` | `123` | Deterministic generation [chai_lab/data/sources/rdkit.py:154]() |
| `enforceChirality` | `True` | Maintain stereochemistry [chai_lab/data/sources/rdkit.py:155]() |
| `maxIterations` | `100` | Prevent hanging on difficult molecules [chai_lab/data/sources/rdkit.py:158]() |
| `numThreads` | `-1` | Utilize all available CPU cores [chai_lab/data/sources/rdkit.py:162]() |

Sources: [chai_lab/data/sources/rdkit.py:144-175]()

## Data Structures

The conformer system uses the `ConformerData` dataclass to represent molecular structures.

### Code Entity Space Bridge: ConformerData Mapping

This diagram shows how RDKit `Mol` properties are mapped to the `ConformerData` fields within `_load_ref_conformer_from_rdkit`.

```mermaid
graph TD
    subgraph "RDKit Mol Object"
        Mol["Chem.Mol"]
        GetPos["GetConformer().GetPositions()"]
        GetAtoms["GetAtoms()"]
        GetBonds["GetBonds()"]
        GetSymm["get_intra_res_atom_symmetries()"]
    end

    subgraph "ConformerData [chai_lab/data/parsing/structure/residue.py]"
        CD_Pos["position: torch.float"]
        CD_Elem["element: torch.int"]
        CD_Charge["charge: torch.int"]
        CD_Names["atom_names: list[str]"]
        CD_Bonds["bonds: list[tuple]"]
        CD_Symm["symmetries: torch.Tensor"]
    end

    GetPos --> CD_Pos
    GetAtoms -- "GetAtomicNum" --> CD_Elem
    GetAtoms -- "GetFormalCharge" --> CD_Charge
    GetAtoms -- "GetProp('name')" --> CD_Names
    GetBonds --> CD_Bonds
    GetSymm --> CD_Symm
```

Sources: [chai_lab/data/sources/rdkit.py:97-130](), [chai_lab/data/parsing/structure/residue.py:1-25]()

## Caching and Performance

Initialization of `RefConformerGenerator` is expensive, so it is designed to be cached and reused [chai_lab/data/sources/rdkit.py:43-46]().

### Antipickle Cache

The system uses `antipickle` to load serialized conformers. This is preferred over standard pickle for safety and performance.

*   **Cache File**: Loaded from `paths.cached_conformers.get_path()` [chai_lab/data/sources/rdkit.py:60-63]().
*   **Adapters**: Uses `TorchAntipickleAdapter` and `DataclassAdapter` for `ConformerData` to handle complex types during deserialization [chai_lab/data/sources/rdkit.py:178-182]().
*   **Validation**: The constructor ensures that standard residues (defined in `standard_residue_pdb_codes`) are present in the loaded cache to handle missing protein residues correctly [chai_lab/data/sources/rdkit.py:89-94]().

### Leaving Atoms Cache

The generator also maintains a mapping of `leaving_atoms` [chai_lab/data/sources/rdkit.py:55-57](). This dictionary maps molecule names to a tuple containing a list of atom names and a boolean mask indicating which atoms are "leaving" (e.g., in polymerization reactions).

Sources: [chai_lab/data/sources/rdkit.py:38-73](), [chai_lab/utils/pickle.py]()

## Error Handling and Robustness

Molecular processing can be prone to infinite loops or high resource consumption in RDKit. The system implements safeguards:

### Timeout Protection

The `@timeout` decorator is applied to functions that might hang, such as bond determination or symmetry calculation for complex graphs [chai_lab/data/sources/rdkit.py:28]().

*   **Bond Determination**: Uses `DetermineBonds` with a fallback if it fails or times out.
*   **Symmetry Detection**: `get_intra_res_atom_symmetries` calculates topological symmetries using `GetSubstructMatches`. If this times out, it defaults to identity symmetry (no atoms equivalent) [chai_lab/data/sources/rdkit.py:117-121]().

### Residue Naming

For new ligands generated from SMILES, the system automatically assigns atom names using the element symbol and a counter (e.g., `C1`, `C2`, `O1`) to ensure uniqueness within the residue [chai_lab/data/sources/rdkit.py:167-171]().

Sources: [chai_lab/data/sources/rdkit.py:115-121](), [chai_lab/data/sources/rdkit.py:167-175](), [chai_lab/utils/timeout.py]()

---