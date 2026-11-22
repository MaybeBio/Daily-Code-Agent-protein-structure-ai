# Token Encodings

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



This document covers the token encoding system in AtomWorks, which converts molecular sequences and structures into numerical representations suitable for machine learning models. The system provides standardized encodings for different foundation models like AlphaFold 2, AlphaFold 3, and RoseTTAFold 2 All-Atom.

For information about the broader ML transform pipeline that uses these encodings, see [Transform Pipeline](#3.1). For model-specific pipeline implementations, see [Model-Specific Pipelines](#3.3).

## System Overview

The token encoding system bridges the gap between biological sequence representations (1-letter codes, 3-letter codes, atom names) and the numerical tensors required by ML models. It handles both residue-level tokenization (e.g., "ALA" → integer) and atom-level tokenization within residues (e.g., "CA" atom within "ALA" → position index).

## Token Encoding Architecture

```mermaid
graph TB
    subgraph "Input Representations"
        A1["`One-letter codes
        A, R, N, D, C, ...`"]
        A2["`Three-letter codes
        ALA, ARG, ASN, ASP, CYS, ...`"]
        A3["`Atom names
        N, CA, C, O, CB, ...`"]
        A4["`Chemical Component Dictionary
        CCD codes and metadata`"]
    end
    
    subgraph "Core Token Encoding System"
        B1["TokenEncoding class"]
        B2["`token_atoms mapping
        residue → atom positions`"]
        B3["`chemcomp_type_to_unknown
        unknown residue handling`"]
        B4["`resolve_unknown_token_name()
        fallback resolution`"]
    end
    
    subgraph "Predefined Encodings"
        C1["AF2_ATOM14_ENCODING"]
        C2["AF2_ATOM37_ENCODING"] 
        C3["RF2_ATOM14_ENCODING"]
        C4["RF2_ATOM23_ENCODING"]
        C5["RF2_ATOM36_ENCODING"]
    end
    
    subgraph "Sequence Utilities"
        D1["`get_1_from_3_letter_code()
        3-letter → 1-letter`"]
        D2["`get_3_from_1_letter_code()
        1-letter → 3-letter`"]
        D3["`aa_chem_comp_3to1()
        amino acid mappings`"]
        D4["`na_chem_comp_3to1()
        nucleic acid mappings`"]
    end
    
    subgraph "Output Tensors"
        E1["`Token indices
        [0, 1, 2, 3, ...]`"]
        E2["`Atom indices
        [0, 1, 2, 3, ..., 13]`"]
        E3["`Element types
        [N, C, C, O, C, ...]`"]
        E4["`Coordinate masks
        [1, 1, 1, 1, 0, ...]`"]
    end
    
    A1 --> D1
    A2 --> D2
    A3 --> B2
    A4 --> B3
    
    D1 --> B1
    D2 --> B1
    B2 --> B1
    B3 --> B1
    B4 --> B1
    
    B1 --> C1
    B1 --> C2
    B1 --> C3
    B1 --> C4
    B1 --> C5
    
    C1 --> E1
    C2 --> E1
    C3 --> E1
    C4 --> E1
    C5 --> E1
    
    C1 --> E2
    C2 --> E2
    C3 --> E2
    C4 --> E2
    C5 --> E2
    
    B1 --> E3
    B1 --> E4
```

Sources: [src/atomworks/ml/encoding_definitions.py:36-251](), [src/atomworks/io/utils/sequence.py:80-154]()

## Core TokenEncoding Class

The `TokenEncoding` class is the foundation of the encoding system, providing a standardized interface for converting between biological sequences and numerical representations.

### Key Components

```mermaid
classDiagram
    class TokenEncoding {
        +dict token_atoms
        +dict chemcomp_type_to_unknown
        +np.ndarray tokens
        +int n_tokens
        +int n_atoms_per_token
        +dict token_to_idx
        +dict atom_to_idx
        +resolve_unknown_token_name()
        +to_str()
    }
    
    class SequenceUtils {
        +get_1_from_3_letter_code()
        +get_3_from_1_letter_code()
        +aa_chem_comp_3to1()
        +na_chem_comp_3to1()
    }
    
    class CCDIntegration {
        +get_chem_comp_type()
        +atom_array_from_ccd_code()
        +chem_comp_to_one_letter()
    }
    
    TokenEncoding --> SequenceUtils : uses
    TokenEncoding --> CCDIntegration : uses
```

| Property | Type | Description |
|----------|------|-------------|
| `token_atoms` | `dict[str, np.ndarray]` | Maps residue names to ordered atom name arrays |
| `chemcomp_type_to_unknown` | `dict[str, str]` | Maps chemical component types to unknown tokens |
| `tokens` | `np.ndarray` | Array of all token names in the encoding |
| `n_tokens` | `int` | Total number of tokens in the encoding |
| `n_atoms_per_token` | `int` | Fixed number of atom positions per token |

Sources: [src/atomworks/ml/encoding_definitions.py:36-109](), [src/atomworks/ml/encoding_definitions.py:158-221]()

### Unknown Token Resolution

The encoding system handles unknown residues and atoms through a hierarchical fallback mechanism:

```mermaid
flowchart TD
    A["Input: token_name, token_is_atom"] --> B{"Token in encoding?"}
    B -->|Yes| C["Return token_name"]
    B -->|No| D{"Is atom token?"}
    D -->|Yes| E{"UNKNOWN_ELEMENT_TOKEN in encoding?"}
    E -->|Yes| F["Return UNKNOWN_ELEMENT_TOKEN (0)"]
    E -->|No| G["Raise KeyError"]
    D -->|No| H{"chemcomp_type_to_unknown defined?"}
    H -->|Yes| I["Get chem_comp_type from CCD"]
    I --> J{"Chem type in mapping?"}
    J -->|Yes| K["Return unknown token for type"]
    J -->|No| L["Raise KeyError with guidance"]
    H -->|No| M["Raise KeyError"]
```

Sources: [src/atomworks/ml/encoding_definitions.py:111-156](), [src/atomworks/ml/encoding_definitions.py:222-223]()

## Predefined Model Encodings

The system provides several predefined encodings optimized for different ML models:

### AlphaFold 2 Encodings

| Encoding | Atoms per Token | Token Count | Purpose |
|----------|-----------------|-------------|---------|
| `AF2_ATOM14_ENCODING` | 14 | 21 | Standard AF2 protein encoding |
| `AF2_ATOM37_ENCODING` | 37 | 21 | Extended AF2 encoding with all atom types |

```mermaid
graph LR
    subgraph "AF2_ATOM14_ENCODING"
        A1["ALA: [N, CA, C, O, CB, '', '', ...]"]
        A2["ARG: [N, CA, C, O, CB, CG, CD, NE, CZ, NH1, NH2, '', '', '']"]
        A3["TRP: [N, CA, C, O, CB, CG, CD1, CD2, NE1, CE2, CE3, CZ2, CZ3, CH2]"]
        A4["UNK: ['', '', '', '', '', '', '', '', '', '', '', '', '', '']"]
    end
```

Sources: [src/atomworks/ml/encoding_definitions.py:254-286](), [src/atomworks/ml/encoding_definitions.py:288-332]()

### RoseTTAFold 2 All-Atom Encodings

RF2AA provides multiple encoding granularities for different use cases:

| Encoding | Atoms per Token | Supports | Purpose |
|----------|-----------------|----------|---------|
| `RF2_ATOM14_ENCODING` | 14 | Proteins only | Protein-focused encoding |
| `RF2_ATOM23_ENCODING` | 23 | Proteins + DNA/RNA | Multi-molecule support |
| `RF2_ATOM36_ENCODING` | 36 | All molecular types + elements | Universal encoding |

```mermaid
graph TB
    subgraph "RF2_ATOM36_ENCODING Coverage"
        B1["`Proteins (20 standard AA)
        ALA, ARG, ASN, ..., UNK`"]
        B2["`DNA (4 bases + unknown)
        DA, DC, DG, DT, DN`"]
        B3["`RNA (4 bases + unknown)
        A, C, G, U, N`"]
        B4["`Elements (atomic numbers)
        6 (Carbon), 7 (Nitrogen), 8 (Oxygen), ...`"]
        B5["`Special tokens
        <M> (mask), 0 (unknown element)`"]
    end
```

Sources: [src/atomworks/ml/encoding_definitions.py:422-448](), [src/atomworks/ml/encoding_definitions.py:455-488](), [src/atomworks/ml/encoding_definitions.py:490-560]()

## Sequence Conversion Pipeline

The system provides utilities for converting between different sequence representations:

```mermaid
flowchart LR
    subgraph "Input Formats"
        A1["`1-letter codes
        ARNDCQEGHIL...`"]
        A2["`3-letter codes
        ALA-ARG-ASN-ASP...`"]
        A3["`Chemical Component Dictionary
        CCD entries`"]
    end
    
    subgraph "Conversion Functions"
        B1["get_1_from_3_letter_code()"]
        B2["get_3_from_1_letter_code()"]
        B3["aa_chem_comp_3to1()"]
        B4["na_chem_comp_3to1()"]
    end
    
    subgraph "Chain Type Context"
        C1["ChainType.POLYPEPTIDE_L"]
        C2["ChainType.DNA"]
        C3["ChainType.RNA"]
    end
    
    subgraph "Output"
        D1["`Standardized sequences
        for tokenization`"]
    end
    
    A1 --> B2
    A2 --> B1
    A3 --> B3
    A3 --> B4
    
    C1 --> B1
    C2 --> B1
    C3 --> B1
    C1 --> B2
    C2 --> B2
    C3 --> B2
    
    B1 --> D1
    B2 --> D1
    B3 --> D1
    B4 --> D1
```

Sources: [src/atomworks/io/utils/sequence.py:37-78](), [src/atomworks/io/utils/sequence.py:115-154]()

### Sequence Type Detection

The system automatically handles different molecular types through chemical component type detection:

| Chemical Component Type | Chain Type | 1-letter → 3-letter Example |
|------------------------|------------|------------------------------|
| `L-PEPTIDE LINKING` | `POLYPEPTIDE_L` | `A` → `ALA` |
| `DNA LINKING` | `DNA` | `A` → `DA` |
| `RNA LINKING` | `RNA` | `A` → `A` |

Sources: [src/atomworks/io/utils/sequence.py:106-112](), [src/atomworks/io/utils/ccd.py:560-596]()

## Integration with Chemical Component Dictionary

The encoding system leverages the Chemical Component Dictionary (CCD) for robust residue identification and unknown token handling:

```mermaid
graph TB
    subgraph "CCD Integration"
        A1["chem_comp_to_one_letter()"]
        A2["get_chem_comp_type()"]
        A3["atom_array_from_ccd_code()"]
    end
    
    subgraph "Token Resolution Process"
        B1["Input: Residue name"]
        B2["Look up in CCD"]
        B3["Get chemical component type"]
        B4{"Known residue?"}
        B5["Map to standard token"]
        B6["Map to unknown token by type"]
    end
    
    subgraph "Unknown Token Mapping"
        C1["`AA_LIKE_CHEM_TYPES → UNK`"]
        C2["`DNA_LIKE_CHEM_TYPES → DN`"]
        C3["`RNA_LIKE_CHEM_TYPES → N`"]
    end
    
    A1 --> B2
    A2 --> B3
    A3 --> B2
    
    B1 --> B2
    B2 --> B3
    B3 --> B4
    B4 -->|Yes| B5
    B4 -->|No| B6
    
    B6 --> C1
    B6 --> C2
    B6 --> C3
```

Sources: [src/atomworks/io/utils/ccd.py:57-75](), [src/atomworks/io/utils/ccd.py:560-596](), [src/atomworks/ml/encoding_definitions.py:134-149]()

## MSA and Sequence Encoding

For Multiple Sequence Alignment (MSA) processing, the system provides specialized integer mappings:

| Sequence Type | Encoding Range | Unknown Token | Gap Token |
|---------------|----------------|---------------|-----------|
| Amino Acids | 0-26 | `X` (21) | `-` (20) |
| RNA Nucleotides | 27-41 | `N` (31) | `-` (20) |

```mermaid
graph LR
    subgraph "MSA Integer Encoding"
        A1["`AMINO_ACID_ONE_LETTER_TO_INT
        A:0, R:1, ..., X:21`"]
        A2["`RNA_NUCLEOTIDE_ONE_LETTER_TO_INT
        A:27, C:28, G:29, U:30, N:31`"]
    end
    
    subgraph "Lookup Tables"
        B1["AMINO_ACID_ONE_LETTER_ASCII_TO_INT_LOOKUP_TABLE"]
        B2["RNA_NUCLEOTIDE_ONE_LETTER_ASCII_TO_INT_LOOKUP_TABLE"]
    end
    
    subgraph "Conversion Mappings"
        C1["MSA_INTEGER_TO_THREE_LETTER"]
        C2["THREE_LETTER_TO_MSA_INTEGER"]
    end
    
    A1 --> B1
    A2 --> B2
    B1 --> C1
    B2 --> C1
    C1 --> C2
```

Sources: [src/atomworks/ml/transforms/msa/_msa_constants.py:43-154]()

## Usage in Transform Pipelines

Token encodings integrate with the broader ML transform system through encoding transforms that convert AtomArray structures to numerical tensors:

```mermaid
sequenceDiagram
    participant AA as AtomArray
    participant ET as EncodeAtomArray Transform
    participant TE as TokenEncoding
    participant ML as ML Model
    
    AA->>ET: Structure with residue names
    ET->>TE: resolve_unknown_token_name()
    TE->>ET: Standardized token indices
    ET->>TE: atom_to_idx lookup
    TE->>ET: Atom position indices
    ET->>ML: Numerical tensors
```

The encoding system supports both residue-level and atom-level tokenization, enabling flexible model architectures from coarse-grained sequence models to fine-grained atomic structure models.

Sources: [src/atomworks/ml/encoding_definitions.py:36-251](), [src/atomworks/io/utils/sequence.py:1-185]()

---