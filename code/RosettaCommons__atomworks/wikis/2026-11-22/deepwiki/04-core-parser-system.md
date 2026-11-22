# Core Parser System

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



## Purpose and Scope

The Core Parser System provides the main entry point for converting biological structure files into AtomWorks' unified data representation. This system handles multiple file formats (CIF, PDB, BCIF, SDF) and converts them into Biotite AtomArray objects with standardized annotations and metadata. 

For information about the subsequent ML pipeline processing of parsed structures, see [Transform Pipeline](#3.1). For details about Chemical Component Dictionary integration during parsing, see [Chemical Component Dictionary](#2.3).

## System Architecture

The parser system follows a layered architecture with format detection, file reading, and structured processing phases:

```mermaid
graph TB
    subgraph "Input Layer"
        A1["File Input"] --> A2["Buffer Input"]
        A1 --> A3["Path Input"]
    end
    
    subgraph "Detection Layer"
        B1["infer_pdb_file_type()"]
    end
    
    subgraph "Reading Layer"
        C1["read_any()"]
        C2["CIFFile"]
        C3["PDBFile"] 
        C4["BinaryCIFFile"]
        C5["SDFile"]
    end
    
    subgraph "Core Processing"
        D1["parse()"]
        D2["_parse_from_cif()"]
        D3["_parse_from_pdb()"]
        D4["parse_atom_array()"]
    end
    
    subgraph "Structure Building"
        E1["get_structure()"]
        E2["_add_bonds()"]
        E3["template.add_missing_atoms()"]
    end
    
    subgraph "Output Layer"
        F1["AtomArrayStack"]
        F2["chain_info"]
        F3["metadata"]
        F4["assemblies"]
    end
    
    A1 --> B1
    A2 --> B1
    A3 --> B1
    
    B1 --> C1
    C1 --> C2
    C1 --> C3
    C1 --> C4
    C1 --> C5
    
    C2 --> D1
    C3 --> D1
    C4 --> D1
    
    D1 --> D2
    D1 --> D3
    D2 --> D4
    D3 --> D4
    
    D4 --> E1
    D4 --> E2
    D4 --> E3
    
    E1 --> F1
    E2 --> F1
    E3 --> F1
    D4 --> F2
    D4 --> F3
    D4 --> F4
```

**Sources:** [src/atomworks/io/parser.py:1-766](), [src/atomworks/io/utils/io_utils.py:1-779]()

## File Format Support and Detection

The parser automatically detects and handles multiple file formats through a unified interface:

```mermaid
graph LR
    subgraph "File Types"
        A1[".cif"]
        A2[".pdb"] 
        A3[".bcif"]
        A4[".sdf"]
        A5[".gz compressed"]
    end
    
    subgraph "Detection Logic"
        B1["infer_pdb_file_type()"]
        B2["Extension Analysis"]
        B3["Content Analysis"]
    end
    
    subgraph "File Objects"
        C1["pdbx.CIFFile"]
        C2["biotite_pdb.PDBFile"]
        C3["pdbx.BinaryCIFFile"] 
        C4["mol.SDFile"]
    end
    
    A1 --> B1
    A2 --> B1
    A3 --> B1
    A4 --> B1
    A5 --> B1
    
    B1 --> B2
    B1 --> B3
    
    B2 --> C1
    B2 --> C2
    B2 --> C3
    B2 --> C4
    
    B3 --> C1
    B3 --> C2
```

**Sources:** [src/atomworks/io/utils/io_utils.py:283-317](), [src/atomworks/io/utils/io_utils.py:320-367]()

## Core Parser Function Interface

The main `parse` function serves as the primary entry point with comprehensive configuration options:

| Parameter Category | Key Parameters | Description |
|-------------------|----------------|-------------|
| **Input** | `filename`, `file_type` | File path/buffer and optional format specification |
| **Caching** | `cache_dir`, `save_to_cache`, `load_from_cache` | Caching system for processed structures |
| **Structure Processing** | `add_missing_atoms`, `remove_ccds`, `remove_waters` | Core structure cleaning options |
| **Chemical Handling** | `fix_arginines`, `fix_formal_charges`, `convert_mse_to_met` | Chemical standardization |
| **Hydrogen Policy** | `hydrogen_policy` | Control hydrogen handling: "keep", "remove", "infer" |
| **Assembly Building** | `build_assembly` | Assembly construction: "first", "all", or specific IDs |

**Sources:** [src/atomworks/io/parser.py:73-96](), [src/atomworks/io/parser.py:47-59]()

## Data Processing Pipeline

The parser processes structures through a well-defined sequence of transforms and validations:

```mermaid
flowchart TD
    A["Input File"] --> B["File Type Detection"]
    B --> C["File Reading"]
    C --> D["AtomArray Creation"]
    D --> E["Chain Information Extraction"]
    E --> F["Structure Cleaning"]
    
    subgraph "Structure Cleaning"
        F1["Remove Unwanted CCDs"]
        F2["Handle Hydrogens"]
        F3["Fix Chemical Issues"]
        F4["Add Missing Atoms"]
    end
    
    F --> F1
    F1 --> F2
    F2 --> F3
    F3 --> F4
    
    F4 --> G["Bond Processing"]
    G --> H["Assembly Building"]
    H --> I["Metadata Extraction"]
    I --> J["Output Dictionary"]
    
    subgraph "Output Structure"
        J1["asym_unit: AtomArrayStack"]
        J2["assemblies: dict"]
        J3["chain_info: dict"] 
        J4["metadata: dict"]
        J5["extra_info: dict"]
    end
    
    J --> J1
    J --> J2
    J --> J3
    J --> J4
    J --> J5
```

**Sources:** [src/atomworks/io/parser.py:321-588](), [src/atomworks/io/parser.py:591-674]()

## Format-Specific Processing

### CIF File Processing

CIF files receive the most comprehensive processing with full metadata extraction:

```mermaid
graph TD
    A["CIF File"] --> B["_parse_from_cif()"]
    B --> C["CIF Block Extraction"]
    C --> D["Metadata Loading"]
    D --> E["Structure Loading with Extra Fields"]
    E --> F["parse_atom_array()"]
    F --> G["Ligand Information"]
    G --> H["MSA Path Integration"]
    H --> I["Annotation Cleanup"]
```

**Sources:** [src/atomworks/io/parser.py:591-674]()

### PDB File Processing

PDB files require special handling for chain separation and missing metadata:

```mermaid
graph TD
    A["PDB File"] --> B["_parse_from_pdb()"]
    B --> C["Structure Loading"]
    C --> D["Chain Type Validation"]
    D --> E["HETATM/ATOM Separation"]
    E --> F["Chain ID Reassignment"]
    F --> G["parse_atom_array() with Spoofed Assembly"]
```

**Sources:** [src/atomworks/io/parser.py:677-732]()

## Caching System

The parser includes a sophisticated caching mechanism for improved performance:

```mermaid
graph LR
    subgraph "Cache Key Generation"
        A1["Parse Arguments"]
        A2["Argument Hash"]
        A3["Assembly Info"]
        A4["Cache Path"]
    end
    
    subgraph "Cache Operations"
        B1["Cache Check"]
        B2["Load from Cache"]
        B3["Parse from File"] 
        B4["Save to Cache"]
    end
    
    A1 --> A2
    A2 --> A3
    A3 --> A4
    
    A4 --> B1
    B1 --> B2
    B1 --> B3
    B3 --> B4
```

The cache stores all parsing results except assemblies, which are rebuilt on-demand to handle different assembly requirements.

**Sources:** [src/atomworks/io/parser.py:200-257](), [src/atomworks/io/parser.py:300-318]()

## Integration with External Tools

### RDKit Integration

The parser integrates with RDKit for small molecule processing:

```mermaid
graph TD
    A["Small Molecule Input"] --> B["RDKit Conversion"]
    B --> C["Conformer Generation"]  
    C --> D["AtomArray Conversion"]
    D --> E["Bond Type Mapping"]
    E --> F["Annotation Preservation"]
```

**Sources:** [src/atomworks/io/tools/rdkit.py:483-622]()

### Biotite Integration

All structures are converted to Biotite's AtomArray format for standardized processing:

```mermaid
graph LR
    subgraph "Biotite Objects"
        A1["AtomArray"]
        A2["AtomArrayStack"] 
        A3["BondList"]
    end
    
    subgraph "AtomWorks Extensions"
        B1["Chain Annotations"]
        B2["Chemical Annotations"]
        B3["Assembly Information"]
    end
    
    A1 --> B1
    A2 --> B1
    A3 --> B2
    B1 --> B3
```

**Sources:** [src/atomworks/io/utils/io_utils.py:180-281]()

## Error Handling and Validation

The parser includes comprehensive error handling for common structural biology data issues:

- **Invalid file formats**: Automatic fallback and retry mechanisms
- **Missing atoms**: Template-based atom addition from CCD
- **Chemical inconsistencies**: Valence and charge correction
- **Bond perception errors**: Robust bond inference with fallbacks
- **Assembly building failures**: Graceful degradation to asymmetric unit

**Sources:** [src/atomworks/io/parser.py:181-194](), [src/atomworks/io/parser.py:367-377]()

---