# Overview

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.github/workflows/release_and_docs.yaml](.github/workflows/release_and_docs.yaml)
- [.releaserc.js](.releaserc.js)
- [README.md](README.md)
- [docs/_static/atomworks_datapipelines.svg](docs/_static/atomworks_datapipelines.svg)
- [docs/_static/atomworks_logo_color.svg](docs/_static/atomworks_logo_color.svg)
- [docs/_static/atomworks_logo_dark.svg](docs/_static/atomworks_logo_dark.svg)
- [docs/_static/atomworks_logo_light.svg](docs/_static/atomworks_logo_light.svg)
- [docs/_static/atomworks_overview.png](docs/_static/atomworks_overview.png)
- [docs/_static/default_thumbnail.png](docs/_static/default_thumbnail.png)
- [docs/_static/favicon-16x16.png](docs/_static/favicon-16x16.png)
- [docs/_static/favicon-32x32.png](docs/_static/favicon-32x32.png)
- [docs/conf.py](docs/conf.py)
- [docs/index.rst](docs/index.rst)

</details>



This document provides a high-level introduction to AtomWorks, a Python platform for biomolecular deep learning that accelerates research velocity through unified data processing and modular ML pipelines. AtomWorks consists of two symbiotic libraries that work together to streamline the entire workflow from raw biological data to trained models.

For detailed installation instructions, see [Installation and Getting Started](#1.2). For information about extending AtomWorks with custom functionality, see [Extending AtomWorks](#6.2).

## What is AtomWorks?

AtomWorks is an open-source platform designed to maximize research velocity for biomolecular modeling tasks. Similar to how PyTorch's data utilities enable rapid prototyping in vision and language domains, AtomWorks aims to accelerate development and experimentation within biomolecular modeling by providing:

- **Universal data processing** for biological file formats (PDB, mmCIF, FASTA, SMILES, etc.)
- **Modular ML pipelines** with pre-built, composable transforms
- **Unified data representation** using biotite's `AtomArray` as the backbone
- **Production-ready tooling** for training on large datasets like the PDB

The platform is built atop [biotite](https://www.biotite-python.org/) and integrates seamlessly with PyTorch, RDKit, and other scientific Python libraries.

## Core Components

AtomWorks consists of two main libraries that work together:

```mermaid
graph TB
    subgraph "Input Data"
        A1["PDB/mmCIF Files"]
        A2["FASTA Sequences"] 
        A3["SMILES/MOL"]
        A4["Metadata"]
    end
    
    subgraph "atomworks.io"
        B1["parse()"]
        B2["load_any()"]
        B3["CCD Integration"]
        B4["RDKit Integration"]
    end
    
    subgraph "Core Representation"
        C1["AtomArray"]
    end
    
    subgraph "atomworks.ml"
        D1["Transform System"]
        D2["Dataset Wrappers"]
        D3["Model Pipelines"]
        D4["Token Encodings"]
    end
    
    subgraph "ML Models"
        E1["AlphaFold 3"]
        E2["RoseTTAFold 2AA"]
        E3["Custom Models"]
    end
    
    A1 --> B1
    A2 --> B1
    A3 --> B1
    A4 --> D2
    
    B1 --> C1
    B2 --> C1
    B3 --> C1
    B4 --> C1
    
    C1 --> D1
    D2 --> D1
    D1 --> D3
    D3 --> E1
    D3 --> E2
    D3 --> E3
    
    style C1 fill:#f9f9f9
    style B1 fill:#f9f9f9
    style D1 fill:#f9f9f9
```

**Sources:** [README.md:15-22](), [README.md:26-53]()

### atomworks.io - Universal Data Processing

The `atomworks.io` library provides universal Python toolkit for parsing, cleaning, manipulating, and converting biological data. Key capabilities include:

- **Universal parsing** via the `parse()` function that handles multiple file formats automatically
- **Chemical component integration** through CCD (Chemical Component Dictionary) lookup
- **Cross-format conversion** between PDB, mmCIF, FASTA, SMILES, MOL, and other formats
- **Data cleaning and validation** with proper handling of occupancies, ligands, and missing atoms
- **RDKit integration** for small molecule processing

The library transforms all input data into a consistent `AtomArray` representation for downstream analysis.

**Sources:** [README.md:26-36]()

### atomworks.ml - Modular ML Pipelines

The `atomworks.ml` library provides advanced dataset featurization and sampling for deep learning workflows. Core features include:

- **Transform system** with pre-built, composable transforms for common tasks
- **Model-specific pipelines** for AlphaFold 3, RoseTTAFold 2AA, and custom models  
- **Dataset management** with filtering, sampling, and batching utilities
- **Token encoding systems** for converting molecular data to ML-compatible formats
- **MSA and template processing** for evolutionary and structural features

The transform system maintains a common vocabulary where each transform operates on and outputs updated `AtomArray` objects, enabling seamless composition of processing steps.

**Sources:** [README.md:40-53]()

## System Architecture

The following diagram shows how the major system components interact, using specific code entities from the codebase:

```mermaid
graph TB
    subgraph "CLI Layer"
        CLI1["atomworks pdb sync"]
        CLI2["atomworks setup metadata"]
        CLI3["atomworks setup tests"]
    end
    
    subgraph "atomworks.io Processing"
        IO1["parse()"]
        IO2["load_any()"]
        IO3["CcdReaderSingleton"]
        IO4["sequence_utils"]
        IO5["rdkit_utils"]
    end
    
    subgraph "Core Data"
        CORE1["AtomArray"]
        CORE2["AtomArrayStack"]
    end
    
    subgraph "atomworks.ml Transform System"
        ML1["Transform"]
        ML2["Compose"]
        ML3["StructuralDatasetWrapper"]
        ML4["PandasDataset"]
    end
    
    subgraph "Model Pipelines"
        PIPE1["build_af3_transform_pipeline()"]
        PIPE2["build_rf2aa_transform_pipeline()"]
    end
    
    subgraph "Token Encodings"
        TOK1["AF2TokenEncoding"]
        TOK2["AF3TokenEncoding"] 
        TOK3["RF2AATokenEncoding"]
    end
    
    subgraph "External Systems"
        EXT1["PDB Database"]
        EXT2["biotite"]
        EXT3["torch"]
        EXT4["rdkit"]
    end
    
    CLI1 --> EXT1
    CLI2 --> ML4
    
    IO1 --> CORE1
    IO2 --> CORE1
    IO3 --> CORE1
    IO4 --> CORE1
    IO5 --> CORE1
    
    CORE1 --> ML1
    CORE2 --> ML1
    ML3 --> ML1
    ML4 --> ML1
    
    ML1 --> ML2
    ML2 --> PIPE1
    ML2 --> PIPE2
    
    TOK1 --> PIPE1
    TOK2 --> PIPE1
    TOK3 --> PIPE2
    
    EXT2 -.-> IO1
    EXT3 -.-> ML1
    EXT4 -.-> IO5
    
    style CORE1 fill:#f9f9f9
    style ML1 fill:#f9f9f9
    style IO1 fill:#f9f9f9
```

**Sources:** [README.md:88-104](), [README.md:124-291]()

## Data Flow Pipeline

AtomWorks implements a consistent data flow from raw biological files to ML-ready features:

```mermaid
flowchart LR
    subgraph "Input Processing"
        IN1["File Detection"]
        IN2["Format Parsing"]
        IN3["Data Cleaning"]
        IN4["Assembly Building"]
    end
    
    subgraph "Transform Pipeline"
        T1["RemoveHydrogens"]
        T2["AtomizeByCCDName"]
        T3["EncodeAtomArray"]
        T4["LoadMSA"]
        T5["LoadTemplates"]
    end
    
    subgraph "Model Features"
        OUT1["AF3Features"]
        OUT2["RF2AAFeatures"] 
        OUT3["CustomFeatures"]
    end
    
    FILES["Raw Files<br/>(PDB/mmCIF/FASTA)"] --> IN1
    IN1 --> IN2
    IN2 --> IN3
    IN3 --> IN4
    IN4 --> ATOM["AtomArray"]
    
    ATOM --> T1
    T1 --> T2
    T2 --> T3
    T3 --> T4
    T4 --> T5
    
    T5 --> OUT1
    T5 --> OUT2
    T5 --> OUT3
    
    style ATOM fill:#f9f9f9
```

**Sources:** [README.md:165-277]()

## Key Design Principles

AtomWorks follows several core design principles that enable its modularity and extensibility:

### Unified Data Representation
All structural data flows through biotite's `AtomArray` objects, providing a consistent interface regardless of input format. This eliminates the need for format-specific processing logic in downstream components.

### Composable Transforms
The transform system allows building complex processing pipelines by chaining simple, focused transforms. Each transform receives and returns `AtomArray` objects, making the system highly modular.

### Declarative Configuration
ML pipelines can be configured declaratively using Hydra YAML files, enabling reproducible experiments and easy parameter sweeps without code changes.

### Production Scale
The system is designed to handle large datasets like the full PDB, with efficient data loading, caching, and distributed processing capabilities.

**Sources:** [README.md:51-52](), [README.md:165-277]()

## Integration with External Tools

AtomWorks integrates seamlessly with the broader scientific Python ecosystem:

| Tool | Integration Point | Purpose |
|------|------------------|---------|
| biotite | Core data structures | Structural representation and file I/O |
| PyTorch | ML transforms | Tensor operations and model training |
| RDKit | Chemical processing | Small molecule handling and descriptors |
| Hydra | Configuration | Declarative pipeline configuration |
| NumPy | Numerical operations | Array processing and mathematical operations |

**Sources:** [README.md:22](), [README.md:165-277]()

This overview provides the foundation for understanding AtomWorks' architecture and capabilities. For detailed information about specific components, refer to the dedicated sections on [atomworks.io](#2), [atomworks.ml](#3), and [Model-Specific Pipelines](#3.3).

---