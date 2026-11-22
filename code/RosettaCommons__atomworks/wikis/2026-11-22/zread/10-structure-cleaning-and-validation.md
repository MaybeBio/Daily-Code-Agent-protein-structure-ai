

Structure cleaning and validation in AtomWorks provides a comprehensive toolkit for ensuring atomic structures meet quality standards before downstream processing. These operations address common issues found in biological structure data from sources like the Protein Data Bank, including coordinate problems, chemical inconsistencies, and annotation gaps.

## Core Cleaning Operations

AtomWorks implements a systematic approach to structure cleaning through a series of atomic-level transformations that operate on Biotite's `AtomArray` and `AtomArrayStack` objects [src/atomworks/io/transforms/atom_array.py](src/atomworks/io/transforms/atom_array.py#L1-L4).

### Coordinate Validation and Repair

The foundation of structure cleaning begins with coordinate validation:

```python
def is_any_coord_nan(atom_array: AtomArray | AtomArrayStack) -> np.ndarray:
    """Returns a boolean mask indicating whether any coordinate is NaN for each atom."""
```

This function identifies atoms with missing or invalid coordinates, enabling their removal through `remove_nan_coords()` which filters out problematic atoms while preserving the overall structure integrity [src/atomworks/io/transforms/atom_array.py#L42-L52].

### Chemical Component Filtering

AtomWorks provides utilities for removing unwanted chemical components:

- **Hydrogen removal**: `remove_hydrogens()` eliminates hydrogen atoms using predefined hydrogen-like symbols
- **Water removal**: `remove_waters()` filters out water molecules based on CCD codes
- **Custom component filtering**: `remove_ccd_components()` allows specification of particular CCD codes to exclude [src/atomworks/io/transforms/atom_array.py#L55-L80]

### Chemical Standardization

The system handles common chemical inconsistencies through targeted transformations:

**MSE to MET conversion**: Selenomethionine residues are converted to standard methionine, updating residue names, hetero flags, and atomic properties while maintaining canonical atom ordering [src/atomworks/io/transforms/atom_array.py#L133-L162].

**Arginine naming ambiguity resolution**: Ensures NH1 is always positioned closer to CD than NH2, maintaining structural consistency across arginine residues [src/atomworks/io/transforms/atom_array.py#L93-L132].

## Advanced Structure Validation

### Hydrogen Addition and Management

AtomWorks incorporates sophisticated hydrogen handling through biotite's hydride library:

```python
def add_hydrogen_atom_positions(
    atom_array: AtomArray | AtomArrayStack,
    residue_level_annots_to_copy_to_hydrogens: list[str] = [],
) -> AtomArray | AtomArrayStack:
```

This function provides NaN-tolerant hydrogen addition, managing cases where heavy atoms have missing coordinates by temporarily setting them to zero during hydrogen placement, then restoring NaN values appropriately [src/atomworks/io/transforms/atom_array.py#L423-L511].

> [!TIP]
> The hydrogen addition system intelligently handles coordinate ambiguity by setting newly-added hydrogens to NaN coordinates when bonded to heavy atoms with missing positions, preventing false geometry assumptions.

### RDKit Integration for Chemical Validation

For small molecules and ligands, AtomWorks leverages RDKit's chemistry engine through specialized tools:

**ChEMBL Normalizer**: Implements the ChEMBL structure pipeline normalization rules using SMIRKS transformations, providing rescue capabilities for molecules that fail standard RDKit sanitization [src/atomworks/io/tools/rdkit.py#L105-L124].

**Molecule fixing**: The `fix_mol()` function attempts to infer aromaticity, valences, implicit hydrogens, and formal charges to produce chemically valid molecules without altering heavy atom frameworks [src/atomworks/io/tools/rdkit.py#L266-L280].

## Annotation and Metadata Management

### Entity and Chain Identification

Structure cleaning extends to proper annotation management:

- **Polymer annotation**: `add_polymer_annotation()` marks polymer chains based on chain information dictionaries
- **Entity assignment**: `annotate_entities()` establishes hierarchical relationships between chains, polymer/non-polymer units, and molecules [src/atomworks/io/transforms/atom_array.py#L607-L706]

### Instance ID Management

For assembly handling and multi-model structures, AtomWorks manages instance IDs across different organizational levels:

```python
def add_iid_annotations_to_assemblies(
    assemblies_dict: dict[str | int, AtomArray | AtomArrayStack],
) -> dict[str | int, AtomArray | AtomArrayStack]:
```

This ensures proper tracking of chain, PN unit, and molecule instances across complex assemblies [src/atomworks/io/transforms/atom_array.py#L719-L742].

## Error Handling and Validation

AtomWorks implements robust error handling through context managers that provide detailed traceback formatting and cleanup capabilities [src/atomworks/io/utils/error.py#L30-L112]. This ensures that structure cleaning operations fail gracefully with informative error messages, facilitating debugging of structure processing pipelines.

## Integration with Processing Pipelines

Structure cleaning functions are designed to work seamlessly within AtomWorks transform pipelines, allowing composition of multiple cleaning operations into efficient processing workflows. The modular nature enables selective application of cleaning steps based on specific data requirements and quality standards.

For comprehensive structure processing, these cleaning operations should be combined with parsing operations described in [Parsing Biological Files (PDB, mmCIF, FASTA)](8-parsing-biological-files-pdb-mmcif-fasta) and followed by assembly generation detailed in [Assembly Generation and Symmetry Operations](11-assembly-generation-and-symmetry-operations).