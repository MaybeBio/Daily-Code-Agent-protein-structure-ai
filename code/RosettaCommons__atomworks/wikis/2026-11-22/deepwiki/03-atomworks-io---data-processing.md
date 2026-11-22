# atomworks.io - Data Processing

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.github/workflows/lint_and_test.yaml](.github/workflows/lint_and_test.yaml)
- [.gitignore](.gitignore)
- [pyproject.toml](pyproject.toml)
- [src/atomworks/io/parser.py](src/atomworks/io/parser.py)
- [src/atomworks/io/tools/rdkit.py](src/atomworks/io/tools/rdkit.py)
- [src/atomworks/io/utils/ccd.py](src/atomworks/io/utils/ccd.py)
- [src/atomworks/io/utils/io_utils.py](src/atomworks/io/utils/io_utils.py)
- [src/atomworks/io/utils/sequence.py](src/atomworks/io/utils/sequence.py)
- [src/atomworks/ml/encoding_definitions.py](src/atomworks/ml/encoding_definitions.py)
- [src/atomworks/ml/transforms/af3_reference_molecule.py](src/atomworks/ml/transforms/af3_reference_molecule.py)
- [src/atomworks/ml/transforms/featurize_unresolved_residues.py](src/atomworks/ml/transforms/featurize_unresolved_residues.py)
- [src/atomworks/ml/transforms/filters.py](src/atomworks/ml/transforms/filters.py)
- [src/atomworks/ml/transforms/msa/_msa_constants.py](src/atomworks/ml/transforms/msa/_msa_constants.py)
- [tests/io/components/test_remove_hydrogens.py](tests/io/components/test_remove_hydrogens.py)
- [tests/io/utils/test_sequence_maps.py](tests/io/utils/test_sequence_maps.py)
- [tests/io/utils/test_sequence_utils.py](tests/io/utils/test_sequence_utils.py)
- [tests/ml/pipelines/test_pipeline_regression.py](tests/ml/pipelines/test_pipeline_regression.py)
- [tests/ml/transforms/test_token_utils.py](tests/ml/transforms/test_token_utils.py)

</details>



This document covers the `atomworks.io` library, which provides comprehensive data processing capabilities for biomolecular structure files. The library serves as the foundation for converting, cleaning, and standardizing structural data from formats like PDB, mmCIF, and BCIF into biotite-compatible `AtomArray` and `AtomArrayStack` representations.

For machine learning workflows built on top of this processed data, see [atomworks.ml - Machine Learning](#3). For command-line data synchronization tools, see [Command Line Interface](#4).

## Core System Architecture

The `atomworks.io` system is built around a central `parse` function that orchestrates the entire data processing pipeline. The architecture follows a layered approach where raw structural files are progressively cleaned, validated, and augmented before being assembled into standardized data structures.

```mermaid
graph TB
    subgraph "Input Layer"
        PDB["PDB Files"]
        CIF["mmCIF Files"] 
        BCIF["BCIF Files"]
        BUFFER["StringIO/BytesIO Buffers"]
    end
    
    subgraph "Core Processing Engine"
        PARSE_FUNC["parse()"]
        PARSE_CIF["_parse_from_cif()"]
        PARSE_PDB["_parse_from_pdb()"]
        PARSE_ARRAY["parse_atom_array()"]
    end
    
    subgraph "Data Structures"
        ATOM_ARRAY["AtomArray"]
        ATOM_STACK["AtomArrayStack"]
        CIF_FILE["CIFFile/BinaryCIFFile"]
    end
    
    subgraph "Processing Modules"
        TEMPLATES["template.add_missing_atoms()"]
        TRANSFORMS["transforms.atom_array.*"]
        ASSEMBLY["utils.assembly.*"]
        CATEGORIES["transforms.categories.*"]
    end
    
    subgraph "Output Data"
        CHAIN_INFO["chain_info dict"]
        LIGAND_INFO["ligand_info dict"] 
        ASYM_UNIT["asym_unit AtomArrayStack"]
        ASSEMBLIES["assemblies dict"]
        METADATA["metadata dict"]
    end
    
    PDB --> PARSE_FUNC
    CIF --> PARSE_FUNC
    BCIF --> PARSE_FUNC
    BUFFER --> PARSE_FUNC
    
    PARSE_FUNC --> PARSE_CIF
    PARSE_FUNC --> PARSE_PDB
    PARSE_CIF --> PARSE_ARRAY
    PARSE_PDB --> PARSE_ARRAY
    
    PARSE_CIF --> CIF_FILE
    PARSE_PDB --> ATOM_ARRAY
    CIF_FILE --> ATOM_STACK
    
    PARSE_ARRAY --> TEMPLATES
    PARSE_ARRAY --> TRANSFORMS
    PARSE_ARRAY --> ASSEMBLY
    PARSE_ARRAY --> CATEGORIES
    
    TEMPLATES --> CHAIN_INFO
    TRANSFORMS --> ASYM_UNIT
    ASSEMBLY --> ASSEMBLIES
    CATEGORIES --> LIGAND_INFO
    CATEGORIES --> METADATA
```

**Core Parser Architecture**

Sources: [src/atomworks/io/parser.py:73-319](), [src/atomworks/io/parser.py:591-674](), [src/atomworks/io/parser.py:677-733]()

## Main Parse Function Interface

The `parse` function serves as the primary entry point for all data processing operations. It accepts various file formats and provides extensive configuration options for data cleaning and processing.

```mermaid
graph LR
    subgraph "parse() Function Parameters"
        FILE["filename: PathLike|Buffer"]
        CACHE["cache_dir, load_from_cache, save_to_cache"]
        CLEAN["add_missing_atoms, remove_ccds, remove_waters"]
        FIX["fix_arginines, fix_formal_charges, fix_bond_types"]
        POLICY["hydrogen_policy: keep|remove|infer"]
        ASSEMBLY["build_assembly: first|all|list"]
        FIELDS["extra_fields, keep_cif_block"]
    end
    
    subgraph "Processing Arguments"
        CCD["ccd_mirror_path"]
        LIGANDS["fix_ligands_at_symmetry_centers"]
        CONVERT["convert_mse_to_met"]
        BONDS["add_bond_types_from_struct_conn"]
        ANNOTATIONS["add_id_and_entity_annotations"]
    end
    
    subgraph "Return Dictionary"
        CHAIN["chain_info: dict"]
        LIG["ligand_info: dict"]
        ASYM["asym_unit: AtomArrayStack"]
        ASSEM["assemblies: dict"]
        META["metadata: dict"]
        EXTRA["extra_info: dict"]
    end
    
    FILE --> CHAIN
    CACHE --> ASYM
    CLEAN --> ASYM
    FIX --> ASYM
    POLICY --> ASYM
    ASSEMBLY --> ASSEM
    FIELDS --> ASYM
    
    CCD --> CHAIN
    LIGANDS --> ASSEM
    CONVERT --> ASYM
    BONDS --> ASYM
    ANNOTATIONS --> ASYM
```

**Parse Function Interface and Configuration**

Sources: [src/atomworks/io/parser.py:47-60](), [src/atomworks/io/parser.py:73-167]()

## Data Processing Pipeline

The processing pipeline consists of several distinct stages that transform raw structural data into clean, standardized representations. Each stage performs specific validation, cleaning, and augmentation operations.

```mermaid
graph TD
    subgraph "File Loading Stage"
        READ_ANY["read_any()"]
        GET_STRUCTURE["get_structure()"]
        INFER_TYPE["infer_pdb_file_type()"]
    end
    
    subgraph "Initial Processing"
        ENSURE_STACK["ensure_atom_array_stack()"]
        REMOVE_CCD["remove_ccd_components()"]
        INIT_CHAIN["initialize_chain_info_from_category()"]
        LOAD_SEQ["load_monomer_sequence_information_from_category()"]
    end
    
    subgraph "Data Cleaning"
        KEEP_LAST["keep_last_residue()"]
        ADD_POLYMER["add_polymer_annotation()"]
        ADD_CHAIN_TYPE["add_chain_type_annotation()"]
        HYDROGEN_POLICY["remove_hydrogens() | add_hydrogen_atom_positions()"]
    end
    
    subgraph "Missing Atoms & Bonds"
        ADD_MISSING["template.add_missing_atoms()"]
        RESOLVE_ARG["resolve_arginine_naming_ambiguity()"]
        MSE_TO_MET["mse_to_met()"]
        ADD_IDS["add_id_and_entity_annotations()"]
    end
    
    subgraph "Assembly Building"
        BUILD_ASSEM["build_assemblies_from_asym_unit()"]
        CRYSTAL_DETAILS["extract_crystallization_details()"]
        CLEAN_ANNOTATIONS["_remove_tmp_annotations()"]
    end
    
    READ_ANY --> ENSURE_STACK
    GET_STRUCTURE --> ENSURE_STACK
    INFER_TYPE --> READ_ANY
    
    ENSURE_STACK --> REMOVE_CCD
    REMOVE_CCD --> INIT_CHAIN
    INIT_CHAIN --> LOAD_SEQ
    
    LOAD_SEQ --> KEEP_LAST
    KEEP_LAST --> ADD_POLYMER
    ADD_POLYMER --> ADD_CHAIN_TYPE
    ADD_CHAIN_TYPE --> HYDROGEN_POLICY
    
    HYDROGEN_POLICY --> ADD_MISSING
    ADD_MISSING --> RESOLVE_ARG
    RESOLVE_ARG --> MSE_TO_MET
    MSE_TO_MET --> ADD_IDS
    
    ADD_IDS --> BUILD_ASSEM
    BUILD_ASSEM --> CRYSTAL_DETAILS
    CRYSTAL_DETAILS --> CLEAN_ANNOTATIONS
```

**Data Processing Pipeline Flow**

Sources: [src/atomworks/io/parser.py:417-588](), [src/atomworks/io/transforms/atom_array.py](), [src/atomworks/io/template.py]()

## Output Data Structures

The `parse` function returns a comprehensive dictionary containing multiple data structures that provide different views and representations of the processed molecular structure.

| Key | Type | Description |
|-----|------|-------------|
| `chain_info` | `dict` | Chain-level metadata including sequences, types, and entity information |
| `ligand_info` | `dict` | Information about ligands of interest and binding sites |
| `asym_unit` | `AtomArrayStack` | Asymmetric unit representation with all models |
| `assemblies` | `dict[str, AtomArrayStack]` | Biological assemblies keyed by assembly ID |
| `metadata` | `dict` | Structure metadata (resolution, deposition date, method, etc.) |
| `extra_info` | `dict` | Additional information for caching and cross-compatibility |

### Chain Information Structure

The `chain_info` dictionary provides detailed information about each molecular chain:

```python
{
    "A": {
        "chain_type": ChainType.POLYPEPTIDE_L,
        "res_name": ["MET", "ALA", "GLY", ...],
        "res_id": [1, 2, 3, ...],
        "is_polymer": True,
        "entity_id": "1",
        "ec_number": None,
        "msa_path": Path("sequence.a3m")  # Optional
    }
}
```

### Assembly Generation

Biological assemblies are generated using crystallographic symmetry operations defined in the `pdbx_struct_assembly_gen` and `pdbx_struct_oper_list` categories. The system supports building specific assemblies or all available assemblies.

Sources: [src/atomworks/io/parser.py:156-167](), [src/atomworks/io/transforms/categories.py:28-31](), [src/atomworks/io/utils/assembly.py]()

## Caching System

The parser includes a sophisticated caching mechanism that can save and load pre-processed structures to improve performance on repeated operations.

```mermaid
graph LR
    subgraph "Cache Key Generation"
        ARGS["parse_arguments"]
        HASH["md5_hash_string()"]
        ASSEMBLY["assembly_info"]
        PATH["cache_file_path"]
    end
    
    subgraph "Cache Operations"
        SAVE["save_to_cache"]
        LOAD["load_from_cache"]
        PICKLE["pd.to_pickle() / pd.read_pickle()"]
    end
    
    subgraph "Cached Data"
        ASYM_CACHED["asym_unit"]
        CHAIN_CACHED["chain_info"]
        META_CACHED["metadata"]
        EXTRA_CACHED["extra_info"]
        ASSEM_GEN["assembly_gen_category"]
        STRUCT_OPER["struct_oper_category"]
    end
    
    ARGS --> HASH
    HASH --> PATH
    ASSEMBLY --> PATH
    
    PATH --> SAVE
    PATH --> LOAD
    SAVE --> PICKLE
    LOAD --> PICKLE
    
    PICKLE --> ASYM_CACHED
    PICKLE --> CHAIN_CACHED
    PICKLE --> META_CACHED
    PICKLE --> EXTRA_CACHED
    ASYM_CACHED --> ASSEM_GEN
    ASYM_CACHED --> STRUCT_OPER
```

**Caching System Architecture**

The cache stores all parsing results except assemblies, which are rebuilt on-demand using stored assembly generation and operation categories. This approach balances storage efficiency with reconstruction speed.

Sources: [src/atomworks/io/parser.py:200-257](), [src/atomworks/io/parser.py:300-318](), [src/atomworks/io/common.py:md5_hash_string]()

## Data Validation and Quality Control

The system includes extensive validation and quality control mechanisms to ensure data integrity and consistency across different input formats and sources.

### Supported File Formats

- **mmCIF/PDBx**: Primary format with full metadata support
- **BCIF**: Binary CIF format for efficient storage and transfer  
- **PDB**: Legacy format with automatic chain separation for mixed polymer/non-polymer residues

### Validation Features

- CCD code availability checking via `check_ccd_codes_are_available()`
- Argument validation for processing parameters
- Automatic detection and correction of common structural issues
- Symmetry center clash detection and resolution
- Bond type validation and correction

### Quality Assurance

- Regression testing against stored reference structures
- Consistency validation between different parsing paths
- Comprehensive test coverage for edge cases and complex structures

Sources: [src/atomworks/io/utils/ccd.py](), [tests/io/components/test_regression.py:16-42](), [tests/io/utils/test_io.py:400-421]()

## Integration Points

The `atomworks.io` system integrates with several external libraries and internal components:

### External Dependencies
- **biotite**: Core structural biology data structures (`AtomArray`, `AtomArrayStack`, `BondList`)
- **pandas**: Data manipulation and metadata handling
- **numpy**: Numerical operations and array processing

### Internal Integration  
- **atomworks.ml**: Provides cleaned data for machine learning pipelines
- **atomworks.cli**: Uses parsing functions for data synchronization operations
- **CCD Mirror**: Local chemical component dictionary for validation and templates

The parser system serves as the foundational layer that enables all downstream analysis and modeling workflows within the AtomWorks framework.

Sources: [src/atomworks/io/parser.py:12-19](), [src/atomworks/io/constants.py](), [src/atomworks/io/utils/io_utils.py]()

---