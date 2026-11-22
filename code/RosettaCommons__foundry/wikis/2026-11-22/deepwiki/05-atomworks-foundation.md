# AtomWorks Foundation

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.env](.env)
- [README.md](README.md)
- [examples/all.ipynb](examples/all.ipynb)
- [models/rf3/configs/inference_engine/base.yaml](models/rf3/configs/inference_engine/base.yaml)
- [models/rf3/configs/inference_engine/rf3.yaml](models/rf3/configs/inference_engine/rf3.yaml)
- [models/rf3/src/rf3/data/extra_xforms.py](models/rf3/src/rf3/data/extra_xforms.py)
- [models/rf3/src/rf3/data/pipelines.py](models/rf3/src/rf3/data/pipelines.py)
- [models/rf3/src/rf3/inference.py](models/rf3/src/rf3/inference.py)
- [models/rf3/src/rf3/inference_engines/rf3.py](models/rf3/src/rf3/inference_engines/rf3.py)
- [models/rf3/src/rf3/symmetry/resolve.py](models/rf3/src/rf3/symmetry/resolve.py)
- [models/rf3/src/rf3/utils/inference.py](models/rf3/src/rf3/utils/inference.py)
- [models/rfd3/README.md](models/rfd3/README.md)
- [models/rfd3/src/rfd3/engine.py](models/rfd3/src/rfd3/engine.py)
- [models/rfd3/src/rfd3/inference/datasets.py](models/rfd3/src/rfd3/inference/datasets.py)
- [models/rfd3/src/rfd3/utils/inference.py](models/rfd3/src/rfd3/utils/inference.py)
- [models/rfd3na/src/rfd3na/utils/inference.py](models/rfd3na/src/rfd3na/utils/inference.py)
- [src/foundry/inference_engines/base.py](src/foundry/inference_engines/base.py)
- [src/foundry/inference_engines/checkpoint_registry.py](src/foundry/inference_engines/checkpoint_registry.py)
- [src/foundry_cli/__init__.py](src/foundry_cli/__init__.py)
- [src/foundry_cli/download_checkpoints.py](src/foundry_cli/download_checkpoints.py)

</details>



## Purpose and Scope

This document describes **AtomWorks** as the foundational framework underlying the entire Foundry ecosystem. AtomWorks provides the unified infrastructure for manipulating and processing biomolecular structures, serving as the core dependency for all Foundry models. This page covers AtomWorks' role in the system architecture, the `Biotite AtomArray` data structure that enables interoperability between models, and the key operations provided by the framework.

For information about specific model implementations that use AtomWorks, see [RFD3 Overview and Capabilities](#4.1), [RF3 Overview](#5.1), and [MPNN Overview](#6.1). For details on the transform pipeline that builds upon AtomWorks, see [Data Pipeline and Transforms](#8.5).

---

## AtomWorks in the Foundry Architecture

### Strict Dependency Hierarchy

Foundry enforces a **unidirectional dependency flow**: `foundry → atomworks`. This means:
- Foundry depends on AtomWorks for all structure operations. [README.md:112-113]()
- AtomWorks remains independent and can be used standalone. [README.md:5]()
- All model packages (RFD3, RF3, MPNN) access AtomWorks through Foundry shared utilities or direct imports. [README.md:114-115]()
- No reverse dependencies are allowed.

**Diagram: Dependency Architecture**

```mermaid
graph TB
    subgraph "External Framework"
        AtomWorks["<b>AtomWorks</b><br/>github.com/RosettaCommons/atomworks"]
    end
    
    subgraph "Foundry Core"
        FoundryCore["<b>foundry package</b><br/>src/foundry/"]
    end
    
    subgraph "Model Packages"
        RFD3["<b>RFD3</b><br/>models/rfd3/"]
        RF3["<b>RF3</b><br/>models/rf3/"]
        MPNN["<b>MPNN</b><br/>models/mpnn/"]
    end
    
    subgraph "Data Mirrors"
        PDB["PDB Mirror<br/>PDB_MIRROR_PATH"]
        CCD["CCD Mirror<br/>CCD_MIRROR_PATH"]
    end
    
    FoundryCore --> AtomWorks
    RFD3 --> FoundryCore
    RF3 --> FoundryCore
    MPNN --> FoundryCore
    
    AtomWorks -.->|reads structures| PDB
    AtomWorks -.->|reads ligands| CCD
```
**Sources:** [README.md:5-6](), [README.md:112-115](), [.env:9-22]()

### Core Capabilities

AtomWorks provides three primary categories of functionality:

| Category | Description | Key Operations |
|----------|-------------|----------------|
| **Structure I/O** | Reading and writing biomolecular structure files | CIF/PDB parsing, format conversion, mirror access |
| **Preprocessing** | Preparing structures for model consumption | Bond detection, atom annotation, non-standard residue handling |
| **Featurization** | Extracting model-ready features from structures | Token-level, atom-level, and pair-level feature extraction |

**Sources:** [README.md:114-115](), [models/rfd3/src/rfd3/utils/inference.py:11-23]()

---

## The Biotite AtomArray Data Structure

### Universal Data Representation

The **`biotite.structure.AtomArray`** serves as the universal data structure throughout Foundry, enabling seamless interoperability between all models and pipeline components. [examples/all.ipynb:20]()

**Diagram: AtomArray as the Universal Format**

```mermaid
graph LR
    subgraph "Input Sources"
        PDBFiles["PDB/CIF Files"]
        JSONSpec["JSON Specifications"]
    end
    
    subgraph "AtomWorks Parsing"
        Parser["atomworks.parse"]
        AtomArray["<b>Biotite AtomArray</b><br/>Universal structure representation"]
    end
    
    subgraph "Model Consumption"
        RFD3Input["RFD3InferenceEngine"]
        MPNNInput["MPNNInferenceEngine"]
        RF3Input["RF3InferenceEngine"]
    end
    
    subgraph "Model Output"
        RFD3Output["RFD3Output.atom_array"]
        MPNNOutput["MPNNOutput.atom_array"]
        RF3Output["RF3Output.atom_array"]
    end
    
    PDBFiles --> Parser
    JSONSpec --> Parser
    Parser --> AtomArray
    
    AtomArray --> RFD3Input
    AtomArray --> MPNNInput
    AtomArray --> RF3Input
    
    RFD3Input --> RFD3Output
    MPNNInput --> MPNNOutput
    RF3Input --> RF3Output
    
    RFD3Output --> AtomArray
    MPNNOutput --> AtomArray
    RF3Output --> AtomArray
```
**Sources:** [models/rfd3/src/rfd3/engine.py:91-92](), [models/rf3/src/rf3/inference_engines/rf3.py:99-106](), [models/rfd3/src/rfd3/utils/inference.py:11-13]()

### AtomArray Properties and Annotations

An `AtomArray` is a structured representation of atomic coordinates and properties. In Foundry, it is often enriched with custom annotations required for specific model logic. [models/rfd3/src/rfd3/utils/inference.py:53-73]()

```python
# Example from the codebase
atom_array = outputs[first_key][0].atom_array  # RFD3 output
# atom_array contains:
# - Coordinates: atom_array.coord
# - Atom names: atom_array.atom_name
# - Residue names: atom_array.res_name
# - Chain IDs: atom_array.chain_id
# - Custom annotations (e.g., is_motif_atom_with_fixed_coord)
```

Common annotations include:
- `is_motif_atom_with_fixed_coord`: Boolean mask for design constraints. [models/rfd3/src/rfd3/utils/inference.py:128-134]()
- `src_component`: Tracks the origin of a residue or ligand. [models/rfd3/src/rfd3/utils/inference.py:61-72]()
- `molecule_id`: Groups atoms into distinct molecules. [models/rfd3/src/rfd3/utils/inference.py:80]()
- `occupancy`, `b_factor`, `charge`: Standard PDB properties. [models/rfd3/src/rfd3/utils/inference.py:55-60]()

**Sources:** [models/rfd3/src/rfd3/utils/inference.py:53-85](), [models/rfd3/src/rfd3/engine.py:105-110]()

---

## Structure I/O and Parsing

### File Format Support

AtomWorks provides parsers for standard biomolecular structure formats:

| Format | Extension | Usage |
|--------|-----------|-------|
| **CIF** | `.cif`, `.cif.gz` | Primary format, supports metadata. [models/rfd3/src/rfd3/engine.py:105-111]() |
| **PDB** | `.pdb` | Legacy format, widely compatible. [models/rf3/src/rf3/utils/inference.py:80-83]() |

**Diagram: Structure Parsing Flow**

```mermaid
graph TB
    subgraph "Input Files"
        CIF["CIF/PDB Files<br/>Local or from mirrors"]
    end
    
    subgraph "Parser Configuration"
        ParserArgs["STANDARD_PARSER_ARGS<br/>hydrogen_policy<br/>add_missing_atoms"]
    end
    
    subgraph "AtomWorks Parsing"
        ParseFunc["atomworks.parse"]
        AtomArray["<b>Biotite AtomArray</b><br/>Enriched with chain_info"]
    end
    
    CIF --> ParseFunc
    ParserArgs --> ParseFunc
    ParseFunc --> AtomArray
```
**Sources:** [models/rf3/src/rf3/utils/inference.py:94-105](), [models/rfd3/src/rfd3/utils/inference.py:11-15]()

### Mirror Access for Training Data

AtomWorks integrates with local mirrors of PDB and CCD databases for efficient access during training. [models/rfd3/README.md:110-114]()

**PDB Mirror Structure:**
```
PDB_MIRROR_PATH/
  ├── a2/
  │   └── 1a2b.cif.gz
  ├── b3/
  │   └── 2b3c.cif.gz
```

**CCD Mirror Structure:**
```
CCD_MIRROR_PATH/
  ├── H/
  │   └── HEM/
  │       └── HEM.cif
```

**Sources:** [.env:9-22](), [models/rfd3/README.md:110-115]()

---

## Preprocessing Operations

### Bond Detection and Annotation

AtomWorks automatically detects bonds and adds structural annotations during preprocessing. This is critical for non-standard residues like PTMs or modified amino acids. [models/rfd3/src/rfd3/utils/inference.py:167-184]()

Operations include:
- **Covalent bond detection**: Identifies bonds based on atomic distances and chemical rules. [models/rfd3/src/rfd3/utils/inference.py:186-187]()
- **Chain identification**: Determines polypeptide/nucleotide chains. [models/rfd3/src/rfd3/utils/inference.py:141-146]()
- **Non-standard residue handling**: Restores bonds for PTMs from source structures. [models/rfd3/src/rfd3/utils/inference.py:167-171]()

**Sources:** [models/rfd3/src/rfd3/utils/inference.py:167-187](), [models/rfd3/src/rfd3/utils/inference.py:141-160]()

### Token-Level Operations

AtomWorks provides utilities for working at the **token level** (residues/ligands) rather than the atom level. [models/rfd3/src/rfd3/utils/inference.py:20-23]()

**Key Functions:**

| Function | Module | Description |
|----------|--------|-------------|
| `get_token_starts` | `atomworks.ml.utils.token` | Get indices of first atom in each token. [models/rfd3/src/rfd3/utils/inference.py:21]() |
| `spread_token_wise` | `atomworks.ml.utils.token` | Broadcast token-level values to all atoms in token. [models/rfd3/src/rfd3/utils/inference.py:22]() |

**Sources:** [models/rfd3/src/rfd3/utils/inference.py:20-23]()

---

## Featurization Framework

### Multi-Level Feature Extraction

AtomWorks extracts features at three levels of granularity:

1.  **Token-Level**: Per-residue features (residue type, sequence encoding). [models/rfd3/src/rfd3/utils/inference.py:44-46]()
2.  **Atom-Level**: Per-atom features (coordinates, element type). [models/rfd3/src/rfd3/engine.py:92]()
3.  **Pair-Level**: Token-token interactions (distances, contact maps).

**Sources:** [models/rfd3/src/rfd3/utils/inference.py:16-23](), [models/rfd3/src/rfd3/engine.py:92-93]()

### Token Encoding Systems

Different models use encoding schemes defined in AtomWorks, such as the `AF3SequenceEncoding` which categorizes residues into amino acids, nucleic acids, and ligands. [models/rfd3/src/rfd3/utils/inference.py:16](), [models/rfd3/src/rfd3/utils/inference.py:44-46]()

**Sources:** [models/rfd3/src/rfd3/utils/inference.py:16-46]()

---

## Summary

AtomWorks serves as the **universal adapter layer** for biomolecular structures in Foundry:

| Aspect | Role |
|--------|------|
| **Dependency** | Core external framework, strict unidirectional dependency. [README.md:112-113]() |
| **Data Structure** | Provides `Biotite AtomArray` as universal format. [examples/all.ipynb:20]() |
| **I/O** | Handles all structure reading/writing (CIF, PDB). [models/rfd3/src/rfd3/engine.py:12-13]() |
| **Preprocessing** | Bond detection, annotation, residue handling. [models/rfd3/src/rfd3/utils/inference.py:167-171]() |
| **Interoperability** | Enables seamless data flow between RFD3, MPNN, and RF3. [examples/all.ipynb:24-27]() |

**Sources:** [README.md:112-113](), [examples/all.ipynb:20-27](), [models/rfd3/src/rfd3/engine.py:12-13]()

---