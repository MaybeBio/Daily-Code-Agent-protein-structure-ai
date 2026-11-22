# Advanced Topics

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/atomworks/io/parser.py](src/atomworks/io/parser.py)
- [src/atomworks/io/tools/rdkit.py](src/atomworks/io/tools/rdkit.py)
- [src/atomworks/io/utils/io_utils.py](src/atomworks/io/utils/io_utils.py)
- [src/atomworks/ml/transforms/af3_reference_molecule.py](src/atomworks/ml/transforms/af3_reference_molecule.py)
- [src/atomworks/ml/transforms/featurize_unresolved_residues.py](src/atomworks/ml/transforms/featurize_unresolved_residues.py)
- [src/atomworks/ml/transforms/filters.py](src/atomworks/ml/transforms/filters.py)
- [tests/io/components/test_remove_hydrogens.py](tests/io/components/test_remove_hydrogens.py)
- [tests/ml/pipelines/test_pipeline_regression.py](tests/ml/pipelines/test_pipeline_regression.py)
- [tests/ml/transforms/test_token_utils.py](tests/ml/transforms/test_token_utils.py)

</details>



This document covers advanced usage patterns, external tool integration, and extensibility features in AtomWorks. It provides guidance for users who need to extend the system with custom functionality or integrate with external scientific computing tools.

For basic usage and getting started, see [Overview](#1). For details on the core data processing pipeline, see [atomworks.io - Data Processing](#2). For machine learning pipeline details, see [atomworks.ml - Machine Learning](#3).

## External Tool Integration

AtomWorks provides seamless integration with several external scientific computing libraries, enabling advanced molecular analysis and processing workflows.

### RDKit Integration

AtomWorks offers comprehensive integration with RDKit for small molecule processing and analysis. The integration supports bidirectional conversion between AtomArray objects and RDKit Mol objects.

## RDKit-AtomWorks Integration Architecture

```mermaid
graph TB
    subgraph "RDKit Ecosystem"
        A1[Chem.Mol]
        A2[Chem.SDMolSupplier]
        A3[SMILES]
        A4[SDF Files]
        A5[Morgan Fingerprints]
    end
    
    subgraph "AtomWorks RDKit Bridge"
        B1["atom_array_from_rdkit()"]
        B2["smiles_to_rdkit()"]
        B3["sdf_to_rdkit()"]
        B4["fix_mol()"]
        B5["preserve_annotations decorator"]
        B6["get_morgan_fingerprint_from_rdkit_mol()"]
    end
    
    subgraph "AtomWorks Core"
        C1[AtomArray]
        C2[BondList]
        C3[Molecular Annotations]
    end
    
    subgraph "Advanced Features"
        D1["ChEMBLNormalizer"]
        D2["change_metal_bonds_to_dative()"]
        D3["fix_charge_based_on_valence()"]
        D4["RDKIT_BOND_TYPE_TO_BIOTITE mapping"]
    end
    
    A1 --> B1
    A3 --> B2
    A4 --> B3
    B1 --> C1
    B2 --> A1
    B3 --> A1
    A1 --> B6
    B6 --> A5
    
    B4 --> D1
    B4 --> D2
    B4 --> D3
    D4 --> B1
    
    B5 -.-> B1
    B5 -.-> B2
    B5 -.-> B3
    
    C1 --> C2
    C1 --> C3
```

The core conversion functions provide robust molecular data exchange:

- `atom_array_from_rdkit()` converts RDKit Mol objects to AtomArray format, preserving bond information and molecular annotations
- `smiles_to_rdkit()` generates RDKit molecules from SMILES strings with conformer generation
- `sdf_to_rdkit()` loads molecules from SDF files with sanitization options

Advanced molecular processing features include:

- `ChEMBLNormalizer` class for standardizing molecules using ChEMBL pipeline rules
- `fix_mol()` function for automated molecular sanitization and error recovery
- Metal coordination bond handling via `change_metal_bonds_to_dative()`
- Valence-based formal charge correction through `fix_charge_based_on_valence()`

Sources: [src/atomworks/io/tools/rdkit.py:1-766]()

### Biotite Integration

AtomWorks extends Biotite's structural biology capabilities while maintaining full compatibility with the Biotite ecosystem.

## Biotite-AtomWorks Integration Layers

```mermaid
graph TB
    subgraph "Biotite Foundation"
        A1[struc.AtomArray]
        A2[struc.AtomArrayStack] 
        A3[struc.BondList]
        A4["pdbx.CIFFile"]
        A5["biotite_pdb.PDBFile"]
    end
    
    subgraph "AtomWorks Extensions"
        B1["get_structure()"]
        B2["load_any()"]
        B3["read_any()"]
        B4["_add_bonds()"]
        B5["template.add_missing_atoms()"]
    end
    
    subgraph "Enhanced I/O Capabilities"
        C1[BCIF Support]
        C2[Gzip Decompression]
        C3[Buffer I/O]
        C4[Auto Format Detection]
        C5[Enhanced Bond Inference]
    end
    
    subgraph "AtomWorks Annotations"
        D1[chain_type]
        D2[occupancy]
        D3[is_polymer]
        D4[pn_unit_iid]
        D5[atomic_number]
    end
    
    A1 --> B1
    A4 --> B1
    A5 --> B1
    B1 --> C5
    B2 --> B3
    B3 --> C1
    B3 --> C2
    B3 --> C3
    B3 --> C4
    
    B4 --> A3
    B5 --> A1
    
    A1 --> D1
    A1 --> D2
    A1 --> D3
    A1 --> D4
    A1 --> D5
```

Key enhancements to Biotite functionality:

- Enhanced structure loading via `get_structure()` with improved bond inference and altloc handling
- Universal file reader `read_any()` supporting CIF, BCIF, PDB, and compressed formats
- Automated missing atom placement through template-based reconstruction
- Extended annotation system for chain typing and molecular classification

Sources: [src/atomworks/io/utils/io_utils.py:1-774]()

### File Format Ecosystem

AtomWorks supports a comprehensive range of molecular file formats with automatic type detection and conversion capabilities.

| Format | Extension | Read Support | Write Support | Compression |
|--------|-----------|-------------|---------------|-------------|
| mmCIF | `.cif` | ✓ | ✓ | ✓ |
| Binary CIF | `.bcif` | ✓ | ✓ | ✓ |
| PDB | `.pdb` | ✓ | ✓ | ✓ |
| SDF | `.sdf` | ✓ | ✗ | ✗ |
| FASTA | `.fasta` | ✓ | ✗ | ✗ |
| MOL | `.mol` | ✓ | ✗ | ✗ |

The `infer_pdb_file_type()` function automatically detects file formats, while `parse()` provides a unified interface for all supported formats.

Sources: [src/atomworks/io/utils/io_utils.py:283-318]()

## Extending AtomWorks

AtomWorks is designed for extensibility through its modular transform system and pipeline architecture.

### Transform System Architecture

The transform system provides a standardized interface for data processing operations with built-in validation and composition capabilities.

## Transform System Class Hierarchy

```mermaid
graph TB
    subgraph "Base Transform Infrastructure"
        A1["Transform (ABC)"]
        A2["Compose"]
        A3["ApplyFunctionToAtomArray"]
    end
    
    subgraph "Core Transform Categories"
        B1["Filtering Transforms"]
        B2["Feature Transforms"]
        B3["Encoding Transforms"]
        B4["Geometry Transforms"]
    end
    
    subgraph "Specific Transform Examples"
        C1["RemoveHydrogens"]
        C2["AtomizeByCCDName"] 
        C3["EncodeAtomArray"]
        C4["GetAF3ReferenceMoleculeFeatures"]
        C5["MaskResiduesWithSpecificUnresolvedAtoms"]
        C6["PlaceUnresolvedTokenOnClosestResolvedTokenInSequence"]
    end
    
    subgraph "Validation System"
        D1["check_contains_keys()"]
        D2["check_is_instance()"]
        D3["check_atom_array_annotation()"]
        D4["incompatible_previous_transforms"]
        D5["requires_previous_transforms"]
    end
    
    A1 --> A2
    A1 --> A3
    A1 --> B1
    A1 --> B2
    A1 --> B3
    A1 --> B4
    
    B1 --> C1
    B2 --> C2
    B3 --> C3
    B4 --> C4
    B1 --> C5
    B4 --> C6
    
    A1 --> D1
    A1 --> D2
    A1 --> D3
    C5 --> D4
    C6 --> D5
```

### Custom Transform Development

Creating custom transforms involves implementing the `Transform` abstract base class with proper validation and forward processing logic.

Essential methods for custom transforms:
- `check_input()`: Validates input data structure and required annotations
- `forward()`: Implements the core transformation logic
- Class variables for dependency management: `requires_previous_transforms`, `incompatible_previous_transforms`

Example transform structure pattern:

```python
class CustomTransform(Transform):
    def __init__(self, param1: type, param2: type = default):
        self.param1 = param1
        self.param2 = param2
    
    def check_input(self, data: dict[str, Any]) -> None:
        check_contains_keys(data, ["atom_array"])
        check_is_instance(data, "atom_array", AtomArray)
        check_atom_array_annotation(data, ["required_annotation"])
    
    def forward(self, data: dict[str, Any]) -> dict[str, Any]:
        # Transform implementation
        return data
```

Sources: [src/atomworks/ml/transforms/base.py](), [src/atomworks/ml/transforms/featurize_unresolved_residues.py:100-144]()

### Pipeline Construction Patterns

AtomWorks supports both declarative and programmatic pipeline construction approaches.

## Pipeline Construction Strategies

```mermaid
graph LR
    subgraph "Programmatic Construction"
        A1["Compose([transform1, transform2])"]
        A2["build_af3_transform_pipeline()"]
        A3["build_rf2aa_transform_pipeline()"]
    end
    
    subgraph "Declarative Construction" 
        B1["Hydra YAML Configs"]
        B2["_target_: atomworks.ml.transforms.RemoveHydrogens"]
        B3["StructuralDatasetWrapper"]
    end
    
    subgraph "Pipeline Execution"
        C1["Sequential Transform Application"]
        C2["RNG State Management"]
        C3["Error Handling & Recovery"]
        C4["Performance Monitoring"]
    end
    
    A1 --> C1
    A2 --> C1  
    A3 --> C1
    B1 --> B3
    B2 --> B3
    B3 --> C1
    
    C1 --> C2
    C1 --> C3
    C1 --> C4
```

The `Compose` class enables sequential transform chaining with optional RNG state tracking:

```python
pipeline = Compose([
    RemoveHydrogens(),
    AtomizeByCCDName(atomize_by_default=True),
    EncodeAtomArray(encoding=AF3_ATOM37_ENCODING)
], track_rng_state=True)
```

Pre-built pipeline functions like `build_af3_transform_pipeline()` provide model-specific processing workflows with comprehensive parameter configuration.

Sources: [src/atomworks/ml/pipelines/af3.py](), [tests/ml/pipelines/test_pipeline_regression.py:27-67]()

## Advanced Usage Patterns

### Caching and Performance Optimization

AtomWorks implements multi-level caching strategies for computational efficiency in large-scale processing workflows.

The `parse()` function supports persistent caching with content-based cache keys:

- Cache key generation via argument hashing: `string_to_md5_hash(args_string, truncate=8)`
- Assembly-aware cache file naming: `{stem}_assembly_{assembly_info}.pkl.gz`
- Selective caching excluding assemblies for space efficiency

Cache directory structure and management:
```
cache_dir/
├── {args_hash}/
│   ├── {structure_id}_assembly_all.pkl.gz
│   ├── {structure_id}_assembly_1.pkl.gz
│   └── ...
```

Sources: [src/atomworks/io/parser.py:200-257]()

### Error Handling and Recovery

AtomWorks implements robust error handling with graceful degradation strategies:

**Molecular Sanitization Recovery**:
- ChEMBL-style normalization via `ChEMBLNormalizer`
- RDKit standard normalization fallback
- Valence-based charge correction
- Configurable failure modes: `raise_on_failure` parameter

**File Processing Recovery**:
- Automatic format detection with fallback parsing
- Multi-model handling with graceful single-model fallback
- Invalid file error recovery through model selection

**Transform Pipeline Recovery**:
- Transform dependency validation
- Annotation requirement checking
- Graceful handling of missing optional features

Sources: [src/atomworks/io/tools/rdkit.py:266-347](), [src/atomworks/io/utils/io_utils.py:629-647]()

### Testing and Validation Framework

AtomWorks employs comprehensive regression testing for ML pipelines and data processing stability.

## Testing Architecture

```mermaid
graph TB
    subgraph "Test Categories"
        A1["Unit Tests"]
        A2["Integration Tests"] 
        A3["Regression Tests"]
        A4["Property-Based Tests"]
    end
    
    subgraph "ML Pipeline Testing"
        B1["test_af3_pipeline_regression()"]
        B2["_run_pipeline_test()"]
        B3["_assert_pipeline_results_equal()"]
        B4["_assert_features_equal()"]
    end
    
    subgraph "Data Validation"
        C1["assert_same_atom_array()"]
        C2["_assert_tensor_or_array_equal()"]
        C3["cached_parse()"]
        C4["create_rng_state_from_seeds()"]
    end
    
    subgraph "Test Data Management"
        D1["regression_test_data/"]
        D2["{example}_{mode}.pkl"]
        D3["test_data/ examples"]
        D4["Fixture Management"]
    end
    
    A3 --> B1
    B1 --> B2
    B2 --> B3
    B3 --> B4
    
    B1 --> C1
    B4 --> C2
    B2 --> C3
    B2 --> C4
    
    B1 --> D1
    B1 --> D2
    C3 --> D3
    C3 --> D4
```

The regression testing framework ensures ML pipeline stability across code changes:

- Deterministic testing with fixed RNG seeds
- Feature-level comparison with appropriate tolerances
- Automatic test data generation and validation
- Parametrized testing across multiple examples and modes

Key testing utilities:
- `cached_parse()` for efficient test data loading
- `assert_same_atom_array()` for structural comparison
- `create_rng_state_from_seeds()` for reproducible randomness

Sources: [tests/ml/pipelines/test_pipeline_regression.py:1-236](), [tests/ml/transforms/test_token_utils.py:27-40]()

---