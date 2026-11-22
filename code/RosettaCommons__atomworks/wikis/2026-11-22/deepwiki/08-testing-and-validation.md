# Testing and Validation

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



This document covers the testing and validation framework within the atomworks.io data processing system. It describes the validation strategies, error handling mechanisms, and testing approaches used to ensure data quality and system reliability throughout the parsing and transformation pipeline.

For information about the core parsing functionality, see [Core Parser System](#2.1). For details about data processing workflows, see [Data Processing Pipeline](#2.2).

## Validation Architecture

The atomworks.io system implements a multi-layered validation approach that operates at different stages of the data processing pipeline:

### Validation System Overview

```mermaid
graph TB
    subgraph "Input Validation Layer"
        A1["parse() function"] --> A2["File Type Validation"]
        A2 --> A3["CCD Code Validation"]
        A3 --> A4["Argument Validation"]
    end
    
    subgraph "Processing Validation Layer"
        B1["AtomArray Validation"] --> B2["Bond Validation"]
        B2 --> B3["Coordinate Validation"]
        B3 --> B4["Occupancy Validation"]
    end
    
    subgraph "Transform Validation Layer"
        C1["check_input() methods"] --> C2["Annotation Validation"]
        C2 --> C3["Data Type Validation"]
        C3 --> C4["Transform Compatibility"]
    end
    
    subgraph "Chemical Validation Layer"
        D1["RDKit Sanitization"] --> D2["fix_mol() function"]
        D2 --> D3["Valence Checking"]
        D3 --> D4["Bond Type Validation"]
    end
    
    subgraph "Testing Framework"
        E1["Regression Tests"] --> E2["Component Tests"]
        E2 --> E3["Integration Tests"]
        E3 --> E4["Validation Tests"]
    end
    
    A1 --> B1
    B4 --> C1
    C4 --> D1
    D4 --> E1
    
    style A1 fill:#e1f5fe
    style B1 fill:#f3e5f5
    style C1 fill:#e8f5e8
    style D1 fill:#fff8e1
    style E1 fill:#fce4ec
```

**Sources:** [src/atomworks/io/parser.py:73-319](), [src/atomworks/ml/transforms/base.py](), [src/atomworks/io/tools/rdkit.py:266-347]()

### Validation Flow Architecture

```mermaid
flowchart TD
    A["File Input"] --> B["infer_pdb_file_type()"]
    B --> C["check_ccd_codes_are_available()"]
    C --> D["parse() validation"]
    
    D --> E["AtomArray Creation"]
    E --> F["_add_bonds() validation"]
    F --> G["get_structure() validation"]
    
    G --> H["Transform.check_input()"]
    H --> I["Transform.forward()"]
    I --> J["Output Validation"]
    
    J --> K["fix_mol() sanitization"]
    K --> L["_has_correct_valence()"]
    L --> M["Validated Output"]
    
    style D fill:#e1f5fe
    style H fill:#f3e5f5
    style K fill:#fff8e1
```

**Sources:** [src/atomworks/io/parser.py:180-181](), [src/atomworks/io/utils/io_utils.py:84-177](), [src/atomworks/ml/transforms/base.py]()

## Input Validation

The system performs comprehensive input validation at the entry point of the parsing pipeline:

### File and Argument Validation

The `parse()` function implements several validation checks before processing begins:

| Validation Type | Function/Method | Purpose |
|----------------|----------------|---------|
| File Type Detection | `infer_pdb_file_type()` | Validates and infers file format |
| CCD Code Validation | `check_ccd_codes_are_available()` | Ensures CCD codes exist in dictionary |
| Cache Directory | Cache path validation | Verifies cache directory existence for load/save operations |
| Argument Consistency | Multiple checks | Validates argument combinations and dependencies |

**Key validation logic in `parse()`:**
- CCD mirror path existence checking [src/atomworks/io/parser.py:170-174]()
- Cache directory validation [src/atomworks/io/parser.py:183-187]()
- Formal charge validation dependencies [src/atomworks/io/parser.py:189-194]()

**Sources:** [src/atomworks/io/parser.py:169-194](), [src/atomworks/io/utils/io_utils.py:283-317]()

## Data Processing Validation

### AtomArray Structure Validation

The system validates AtomArray structures throughout the processing pipeline:

```mermaid
graph LR
    A["AtomArray Input"] --> B["Bond List Validation"]
    B --> C["Annotation Validation"]
    C --> D["Coordinate Validation"]
    D --> E["Occupancy Validation"]
    E --> F["Chain Validation"]
    
    B --> B1["struc.BondList creation"]
    C --> C1["Required annotations check"]
    D --> D1["NaN coordinate handling"]
    E --> E1["Zero occupancy filtering"]
    F --> F1["Chain continuity check"]
```

**Sources:** [src/atomworks/io/parser.py:360-362](), [src/atomworks/io/utils/io_utils.py:105-115]()

### Bond Validation System

The `_add_bonds()` function implements sophisticated bond validation:

- **Spurious Bond Detection**: Identifies incorrect inter-residue bonds due to uninformative sequence IDs [src/atomworks/io/utils/io_utils.py:134-141]()
- **Auth Seq ID Validation**: Ensures proper sequence ID annotations exist [src/atomworks/io/utils/io_utils.py:109-115]()
- **Bond Type Validation**: Validates bond types against allowed categories [src/atomworks/io/utils/io_utils.py:87-100]()

**Sources:** [src/atomworks/io/utils/io_utils.py:84-177]()

## Transform Validation

### Transform Input Validation Framework

All transforms implement a standardized validation framework through the `check_input()` method:

```mermaid
graph TB
    subgraph "Transform Validation"
        A["Transform.check_input()"] --> B["check_contains_keys()"]
        B --> C["check_is_instance()"]
        C --> D["check_atom_array_annotation()"]
    end
    
    subgraph "Validation Functions"
        E["check_contains_keys()"] --> E1["Validates required data keys"]
        F["check_is_instance()"] --> F1["Validates data types"]
        G["check_atom_array_annotation()"] --> G1["Validates AtomArray annotations"]
    end
    
    A --> E
    A --> F
    A --> G
```

**Sources:** [src/atomworks/ml/transforms/_checks.py](), [src/atomworks/ml/transforms/featurize_unresolved_residues.py:134-137]()

### Annotation Validation Examples

Several transforms demonstrate comprehensive annotation validation:

- **MaskResiduesWithSpecificUnresolvedAtoms**: Validates `occupancy` and `chain_type` annotations [src/atomworks/ml/transforms/featurize_unresolved_residues.py:137]()
- **RemoveUnsupportedChainTypes**: Validates `chain_type` and `pn_unit_iid` annotations [src/atomworks/ml/transforms/filters.py:150]()
- **HandleUndesiredResTokens**: Validates multiple required annotations [src/atomworks/ml/transforms/filters.py:440]()

**Sources:** [src/atomworks/ml/transforms/featurize_unresolved_residues.py:134-137](), [src/atomworks/ml/transforms/filters.py:149-151]()

## Regression Testing

### Pipeline Regression Framework

The system implements comprehensive regression testing for ML pipelines:

```mermaid
graph LR
    subgraph "Regression Test Flow"
        A["instantiate_example()"] --> B["build_pipelines()"]
        B --> C["_run_pipeline_test()"]
        C --> D["_assert_pipeline_results_equal()"]
    end
    
    subgraph "Validation Steps"
        E["Feature Comparison"] --> F["AtomArray Comparison"]
        F --> G["Coordinate Validation"]
        G --> H["Bond Validation"]
    end
    
    C --> E
    D --> H
```

**Test Structure:**
- **Example Data**: Uses cached PDB structures like "1wym" [tests/ml/pipelines/test_pipeline_regression.py:24]()
- **Pipeline Modes**: Tests both inference and training modes [tests/ml/pipelines/test_pipeline_regression.py:29-30]()
- **Feature Validation**: Compares all pipeline output features [tests/ml/pipelines/test_pipeline_regression.py:132-136]()
- **Reproducibility**: Uses fixed random seeds for deterministic testing [tests/ml/pipelines/test_pipeline_regression.py:97-98]()

**Sources:** [tests/ml/pipelines/test_pipeline_regression.py:73-235]()

### Assertion Framework

The regression tests use sophisticated assertion methods:

| Method | Purpose | Tolerance |
|--------|---------|-----------|
| `_assert_tensor_or_array_equal()` | Compares tensors/arrays with appropriate tolerance | 1e-4 for floats |
| `assert_same_atom_array()` | Compares AtomArray structures | Configurable annotations |
| `_assert_features_equal()` | Compares feature dictionaries | Type-specific tolerances |

**Sources:** [tests/ml/pipelines/test_pipeline_regression.py:164-183](), [src/atomworks/io/utils/testing.py]()

## Component Testing

### Token Utility Testing

Comprehensive testing of token-based operations:

```mermaid
graph TB
    subgraph "Token Tests"
        A["test_tokens_are_residues_without_atomization()"] --> B["Residue = Token validation"]
        C["test_tokens_are_atoms_with_full_atomization()"] --> D["Atom = Token validation"]
        E["test_add_global_token_id_annotation()"] --> F["Token ID consistency"]
    end
    
    subgraph "Validation Points"
        G["Token Count"] --> H["get_token_count()"]
        I["Token Starts"] --> J["get_token_starts()"]
        K["Token Iteration"] --> L["token_iter()"]
    end
    
    B --> G
    D --> I
    F --> K
```

**Sources:** [tests/ml/transforms/test_token_utils.py:27-138]()

### Hydrogen Handling Tests

Validates hydrogen removal and retention:

- **Removal Validation**: Ensures no hydrogen atoms remain after removal [tests/io/components/test_remove_hydrogens.py:24]()
- **Retention Validation**: Confirms hydrogens are preserved when requested [tests/io/components/test_remove_hydrogens.py:35]()
- **Consistency Testing**: Compares filtered results with direct removal [tests/io/components/test_remove_hydrogens.py:41-45]()

**Sources:** [tests/io/components/test_remove_hydrogens.py:11-46]()

## Chemical Structure Validation

### RDKit Sanitization Framework

The system implements comprehensive chemical validation through RDKit:

```mermaid
graph LR
    A["RDKit Molecule"] --> B["fix_mol()"]
    B --> C["Sanitization Checks"]
    C --> D["Valence Validation"]
    D --> E["Bond Type Validation"]
    E --> F["Charge Validation"]
    
    subgraph "Fix Strategies"
        G["ChEMBL Normalization"] --> H["RDKit Normalization"]
        H --> I["Charge Calculation"]
        I --> J["Metal Bond Conversion"]
    end
    
    B --> G
    C --> H
    D --> I
    E --> J
```

**Validation Methods:**
- **Valence Checking**: `_has_correct_valence()` validates atomic valences [src/atomworks/io/tools/rdkit.py:199-204]()
- **Sanitization**: `fix_mol()` attempts multiple fixing strategies [src/atomworks/io/tools/rdkit.py:266-347]()
- **Bond Validation**: Converts and validates bond types between RDKit and Biotite [src/atomworks/io/tools/rdkit.py:60-97]()

**Sources:** [src/atomworks/io/tools/rdkit.py:199-347]()

### Chemical Component Dictionary Validation

The system validates CCD codes and chemical components:

- **Availability Checking**: `check_ccd_codes_are_available()` validates CCD code existence
- **Known CCD Tracking**: Maintains set of available CCD codes [src/atomworks/ml/transforms/af3_reference_molecule.py:28]()
- **Fallback Handling**: Provides graceful degradation for unknown CCD codes [src/atomworks/ml/transforms/af3_reference_molecule.py:89-91]()

**Sources:** [src/atomworks/ml/transforms/af3_reference_molecule.py:28-91]()

---