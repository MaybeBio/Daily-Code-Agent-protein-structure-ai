

AtomWorks provides a comprehensive framework for encoding molecular structures into numerical representations suitable for machine learning applications. The encoding system bridges the gap between biological data structures and tensor-based neural network inputs through standardized tokenization schemes.

## TokenEncoding Architecture

The core of the encoding system is the `TokenEncoding` class, which defines how molecular components are mapped to numerical indices and coordinate arrays [encoding_definitions.py#L36-L250](src/atomworks/ml/encoding_definitions.py#L36-L250). Each encoding scheme consists of:

- **Token-to-atom mappings**: Fixed-length arrays defining which atoms belong to each residue type
- **Unknown token handling**: Chemical component type mappings for unresolved residues
- **Bidirectional lookups**: Efficient token/atom index conversion for encoding and decoding operations

> [!TIP]
> The encoding system follows CCD conventions where residues use 3-letter standardized names, atoms use atomic numbers as tokens, and masked tokens use angle bracket syntax (e.g., `<M>`) to avoid conflicts with existing residue names.

## Standard Encoding Schemes

### AlphaFold 2 Encodings

**AF2_ATOM14_ENCODING**: Heavy atom encoding for proteins with maximum 14 atoms per residue [encoding_definitions.py#L254-L281](src/atomworks/ml/encoding_definitions.py#L254-L281). Covers all 20 standard amino acids plus an unknown token (`UNK`), with atoms ordered consistently across residue types.

**AF2_ATOM37_ENCODING**: Extended protein encoding with 37 atom positions per residue [encoding_definitions.py#L288-L332](src/atomworks/ml/encoding_definitions.py#L288-L332). Includes additional atom positions for comprehensive structural representation, maintaining compatibility with AlphaFold 2's coordinate system.

### RoseTTAFold 2 Encodings

**RF2_ATOM14_ENCODING**: Protein-specific heavy atom encoding similar to AF2 but with RoseTTAFold conventions [encoding_definitions.py#L422-L449](src/atomworks/ml/encoding_definitions.py#L422-L449). Supports 20 amino acids with unknown and mask tokens.

**RF2_ATOM23_ENCODING**: Extended encoding supporting both proteins and nucleic acids [encoding_definitions.py#L455-L500](src/atomworks/ml/encoding_definitions.py#L455-L500). Handles up to 23 heavy atoms per residue, covering DNA/RNA bases with type-specific unknown tokens (`DN` for DNA, `N` for RNA).

**RF2AA_ATOM36_ENCODING**: Comprehensive all-atom encoding for proteins, nucleic acids, and ligands [encoding_definitions.py#L545-L643](src/atomworks/ml/encoding_definitions.py#L545-L643). Includes both heavy atoms and hydrogens (maximum 36 atoms), supporting:
- 20 amino acids + unknown + mask tokens
- 4 DNA bases + unknown
- 4 RNA bases + unknown  
- 45 atom-level tokens for elemental representation
- Legacy histidine token (`HIS_D`) for backward compatibility

### AlphaFold 3 Sequence Encoding

The `AF3SequenceEncoding` class provides sequence-level tokenization [encoding_definitions.py#L689-L753](src/atomworks/ml/encoding_definitions.py#L689-L753), mapping residue names to integer indices for:
- Standard amino acids (20 tokens)
- RNA bases (4 tokens) + unknown
- DNA bases (4 tokens) + unknown
- Gap tokens for alignment operations

## Encoding Process

The `atom_array_to_encoding` function transforms `AtomArray` objects into tensor-ready representations [encoding.py#L34-L100](src/atomworks/ml/transforms/encoding.py#L34-L100):

```python
encoded_data = atom_array_to_encoding(
    atom_array=structure,
    encoding=RF2AA_ATOM36_ENCODING,
    default_coord=float("nan"),
    occupancy_threshold=0.0
)
```

This generates:
- **xyz**: Coordinate tensor of shape `[n_tokens, n_atoms_per_token, 3]`
- **mask**: Resolution mask indicating which atoms are present
- **seq**: Integer sequence of token indices
- **token_is_atom**: Boolean flag distinguishing residue vs atom tokens
- **annotations**: Additional metadata (chain IDs, entity IDs, etc.)

> [!TIP]
> The encoding system automatically handles atomization - when the `atomize` annotation is present, individual atoms become separate tokens, enabling mixed residue/atom representations within the same structure.

## Encoding Selection Guide

| Use Case | Recommended Encoding | Atoms per Token | Coverage |
|----------|---------------------|-----------------|----------|
| Protein structure prediction | AF2_ATOM14_ENCODING | 14 | 20 amino acids |
| Protein-ligand complexes | RF2AA_ATOM36_ENCODING | 36 | Proteins, nucleic acids, ligands |
| Nucleic acid modeling | RF2_ATOM23_ENCODING | 23 | Proteins + DNA/RNA |
| Sequence-only tasks | AF3SequenceEncoding | N/A | All standard biomolecules |

## Integration with ML Pipelines

Feature encoding integrates seamlessly with AtomWorks' transform system through the `EncodeAtomArray` transform [encoding.py#L299-L362](src/atomworks/ml/transforms/encoding.py#L299-L362). This enables encoding as part of larger preprocessing pipelines:

```python
pipeline = Transform([
    AtomizeResidues(),
    EncodeAtomArray(encoding=RF2AA_ATOM36_ENCODING),
    AddTokenAnnotation(encoding=RF2AA_ATOM36_ENCODING)
])
```

The encoding system provides the foundational representation layer for downstream machine learning tasks, ensuring consistent and efficient conversion from biological structures to neural network inputs.

For practical implementation details and examples of encoding usage in ML pipelines, see [Dataset Sampling and Batching](15-dataset-sampling-and-batching).