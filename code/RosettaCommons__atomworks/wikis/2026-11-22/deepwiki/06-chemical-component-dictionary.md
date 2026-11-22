# Chemical Component Dictionary

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.github/workflows/lint_and_test.yaml](.github/workflows/lint_and_test.yaml)
- [.gitignore](.gitignore)
- [pyproject.toml](pyproject.toml)
- [src/atomworks/io/utils/ccd.py](src/atomworks/io/utils/ccd.py)
- [src/atomworks/io/utils/sequence.py](src/atomworks/io/utils/sequence.py)
- [src/atomworks/ml/encoding_definitions.py](src/atomworks/ml/encoding_definitions.py)
- [src/atomworks/ml/transforms/msa/_msa_constants.py](src/atomworks/ml/transforms/msa/_msa_constants.py)
- [tests/io/utils/test_sequence_maps.py](tests/io/utils/test_sequence_maps.py)
- [tests/io/utils/test_sequence_utils.py](tests/io/utils/test_sequence_utils.py)

</details>



The Chemical Component Dictionary (CCD) system provides access to standardized chemical component information for biomolecular structures. It serves as the foundation for residue identification, sequence conversion, and molecular structure parsing throughout AtomWorks. For information about the broader data processing pipeline, see [Data Processing Pipeline](#2.2). For sequence processing specifically, see [Sequence Utilities](#2.4).

## System Overview

The CCD system integrates multiple data sources and provides a unified interface for accessing chemical component information. It supports both biotite's built-in CCD and local mirror installations, enabling robust handling of standard and non-standard residues.

### CCD System Architecture

```mermaid
graph TB
    subgraph "Data Sources"
        A1[biotite_built_in_ccd]
        A2[local_ccd_mirror]
    end
    
    subgraph "Core CCD Functions"
        B1[get_available_ccd_codes]
        B2[atom_array_from_ccd_code]
        B3[parse_ccd_cif]
        B4[chem_comp_to_one_letter]
    end
    
    subgraph "Component Type Classification"
        C1[get_chem_comp_type]
        C2[get_chain_type_from_ccd_code]
        C3[aa_chem_comps]
        C4[na_chem_comps]
    end
    
    subgraph "Sequence Conversion"
        D1[get_1_from_3_letter_code]
        D2[get_3_from_1_letter_code]
        D3[aa_chem_comp_3to1]
        D4[na_chem_comp_3to1]
    end
    
    subgraph "ML Integration"
        E1[TokenEncoding]
        E2[resolve_unknown_token_name]
    end
    
    subgraph "Structure Analysis"
        F1[get_chem_comp_leaving_atom_names]
        F2[get_std_to_alt_atom_name_map]
    end
    
    A1 --> B1
    A2 --> B1
    B1 --> B2
    B2 --> B3
    B1 --> B4
    
    B4 --> C1
    C1 --> C2
    B1 --> C3
    B1 --> C4
    
    B4 --> D3
    B4 --> D4
    D3 --> D1
    D4 --> D1
    D3 --> D2
    D4 --> D2
    
    C1 --> E2
    D1 --> E1
    D2 --> E1
    
    B2 --> F1
    B2 --> F2
    
    style B2 fill:#e1f5fe,stroke:#01579b,stroke-width:3px
    style B1 fill:#f3e5f5,stroke:#4a148c
```

Sources: [src/atomworks/io/utils/ccd.py:1-615](), [src/atomworks/io/utils/sequence.py:1-185](), [src/atomworks/ml/encoding_definitions.py:1-700]()

## Core CCD Data Access

### Available CCD Codes

The system provides functions to check which CCD codes are available from different sources:

| Function | Purpose | Return Type |
|----------|---------|-------------|
| `get_available_ccd_codes_in_biotite()` | Codes in biotite's built-in CCD | `frozenset[str]` |
| `get_available_ccd_codes_in_mirror()` | Codes in local CCD mirror | `frozenset[str]` |
| `get_available_ccd_codes()` | Combined codes from all sources | `frozenset[str]` |

The main entry point `get_available_ccd_codes()` combines both sources, prioritizing local mirror data when available.

Sources: [src/atomworks/io/utils/ccd.py:78-126]()

### Chemical Component Retrieval

The primary function for obtaining chemical component structures is `atom_array_from_ccd_code()`, which returns a biotite `AtomArray` containing the complete atomic structure and metadata for a given CCD code.

```mermaid
flowchart LR
    A[ccd_code] --> B{local_mirror_available?}
    B -->|Yes| C[get_ccd_component_from_mirror]
    B -->|No| D[get_ccd_component_from_biotite]
    C --> E[parse_ccd_cif]
    D --> E
    E --> F[AtomArray]
    
    subgraph "CIF Parsing Options"
        G1["coords: model"]
        G2["coords: ideal_pdbx"]
        G3["coords: ideal_rdkit"]
        G4["add_properties: bool"]
        G5["add_mapping: bool"]
    end
    
    G1 --> E
    G2 --> E
    G3 --> E
    G4 --> E
    G5 --> E
```

Sources: [src/atomworks/io/utils/ccd.py:398-429](), [src/atomworks/io/utils/ccd.py:203-368]()

## Chemical Component Classification

### Component Type System

The CCD system classifies chemical components using standardized types from the RCSB PDB:

```mermaid
graph TD
    A[ccd_code] --> B[get_chem_comp_type]
    B --> C{component_type}
    
    C -->|"L-PEPTIDE LINKING"| D[ChainType.POLYPEPTIDE_L]
    C -->|"DNA LINKING"| E[ChainType.DNA]
    C -->|"RNA LINKING"| F[ChainType.RNA]
    C -->|"SACCHARIDE"| G[ChainType.CARBOHYDRATE]
    C -->|"OTHER"| H[ChainType.OTHER_POLYMER]
    
    D --> I[aa_chem_comps]
    E --> J[dna_chem_comps]
    F --> K[rna_chem_comps]
    
    I --> L[STANDARD_AA]
    J --> M[STANDARD_DNA]
    K --> N[STANDARD_RNA]
```

Sources: [src/atomworks/io/utils/ccd.py:546-597](), [src/atomworks/io/utils/ccd.py:32-54]()

### Chemical Component Sets

Pre-computed frozensets provide fast lookup for different component categories:

| Function | Coverage | Example Members |
|----------|----------|-----------------|
| `aa_chem_comps()` | Amino acid-like components | `{'ALA', 'ARG', 'ASN', ...}` |
| `na_chem_comps()` | Nucleic acid components | `{'DA', 'DC', 'DG', 'DT', 'A', 'C', 'G', 'U', ...}` |
| `dna_chem_comps()` | DNA-specific components | `{'DA', 'DC', 'DG', 'DT', ...}` |
| `rna_chem_comps()` | RNA-specific components | `{'A', 'C', 'G', 'U', ...}` |

Sources: [src/atomworks/io/utils/ccd.py:32-54]()

## Sequence Conversion Utilities

### One-Letter to Three-Letter Mapping

The CCD system enables bidirectional conversion between one-letter and three-letter residue codes:

```mermaid
flowchart TD
    A[chem_comp_to_one_letter] --> B[aa_chem_comp_3to1]
    A --> C[na_chem_comp_3to1]
    
    B --> D[get_1_from_3_letter_code]
    C --> D
    
    B --> E[aa_chem_comp_1to3]
    C --> F1[dna_chem_comp_1to3]
    C --> F2[rna_chem_comp_1to3]
    
    E --> G[get_3_from_1_letter_code]
    F1 --> G
    F2 --> G
    
    D --> H[ChainType.is_protein]
    D --> I[ChainType.is_nucleic_acid]
    G --> H
    G --> I
    
    H --> J["Returns: single letter or 'X'"]
    I --> K["Returns: three letters or UNKNOWN_*"]
```

The conversion functions handle different chain types and provide appropriate fallbacks for unknown residues.

Sources: [src/atomworks/io/utils/sequence.py:37-154]()

## Structure Analysis Features

### Leaving Group Detection

The CCD system can identify leaving groups within chemical components based on bond connectivity and PDB annotations:

| Function | Purpose | Return Type |
|----------|---------|-------------|
| `get_chem_comp_leaving_atom_names()` | Maps atoms to their leaving groups | `dict[str, tuple[str, ...]]` |
| `_find_connected_components_after_removal()` | Analyzes bond graph connectivity | `list[list[int]]` |

Example output for alanine:
```python
{'N': ('H2',), 'C': ('OXT', 'HXT'), 'OXT': ('HXT',)}
```

Sources: [src/atomworks/io/utils/ccd.py:467-544]()

### Alternative Atom Names

The system provides mappings between standard and alternative atom naming conventions:

```python
get_std_to_alt_atom_name_map(ccd_code: str) -> dict[str, str]
```

Sources: [src/atomworks/io/utils/ccd.py:611-615]()

## Integration with ML Encodings

### Token Resolution

The CCD system integrates with the ML encoding framework to resolve unknown tokens:

```mermaid
graph LR
    A[unknown_token] --> B[resolve_unknown_token_name]
    B --> C{token_is_atom?}
    
    C -->|Yes| D[UNKNOWN_ELEMENT_TOKEN]
    C -->|No| E[get_chem_comp_type]
    
    E --> F[chemcomp_type_to_unknown]
    F --> G[resolved_token]
    
    D --> H[TokenEncoding]
    G --> H
```

This enables automatic handling of non-standard residues in ML pipelines by mapping them to appropriate unknown tokens based on their chemical component type.

Sources: [src/atomworks/ml/encoding_definitions.py:111-156]()

### Sequence Validation

The sequence utility functions work with CCD data to validate and convert molecular sequences for ML applications:

| Function | ML Usage | Chain Types |
|----------|----------|-------------|
| `is_standard_aa()` | Filter standard amino acids | Protein chains |
| `is_purine()` / `is_pyrimidine()` | Classify nucleotides | DNA/RNA chains |
| `is_unknown_nucleotide()` | Handle unknown nucleotides | DNA/RNA chains |

Sources: [src/atomworks/io/utils/sequence.py:157-185](), [tests/io/utils/test_sequence_utils.py:1-304]()

## Configuration and Data Sources

### Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `CCD_MIRROR_PATH` | Path to local CCD mirror | Biotite built-in CCD |

### CCD Mirror Structure

Local CCD mirrors follow this directory structure:
```
ccd_mirror/
├── A/
│   ├── ALA/
│   │   └── ALA.cif
│   └── ARG/
│       └── ARG.cif
└── G/
    └── GLY/
        └── GLY.cif
```

The system optimizes file system scanning for this layout pattern.

Sources: [src/atomworks/io/utils/ccd.py:78-108](), [src/atomworks/constants.py]()

---