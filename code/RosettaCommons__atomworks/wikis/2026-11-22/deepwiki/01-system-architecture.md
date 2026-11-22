# System Architecture

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



## Purpose and Scope

This document explains the high-level architecture of AtomWorks, focusing on the relationship between its two primary components: `atomworks.io` and `atomworks.ml`. It covers the overall system design, data flow patterns, and how the components interact to support biomolecular deep learning workflows.

For detailed information about specific components:
- Data processing functionality: see [Core Parser System](#2.1) and [Data Processing Pipeline](#2.2)
- Machine learning pipeline details: see [Transform Pipeline](#3.1) and [Model-Specific Pipelines](#3.3)
- Installation and setup: see [Installation and Getting Started](#1.2)

## System Overview

AtomWorks implements a two-layer architecture designed to separate data processing concerns from machine learning workflow concerns. The system is built around a unified `AtomArray` representation from the biotite library, which serves as the common data format throughout the platform.

### Overall Architecture

```mermaid
graph TB
    subgraph "External Data Sources"
        PDB["PDB Files<br/>(.pdb, .cif, .bcif)"]
        FASTA["Sequence Files<br/>(.fasta)"]
        SMILES["Small Molecules<br/>(SMILES, .sdf)"]
        META["Metadata<br/>(.parquet)"]
    end
    
    subgraph "atomworks.io - Data Processing Layer"
        PARSE["parse() function"]
        READERS["File Format Readers"]
        CCD["Chemical Component Dictionary"]
        UTILS["Sequence Utilities"]
        RDKIT["RDKit Integration"]
    end
    
    subgraph "Core Data Representation"
        ATOMARRAY["AtomArray<br/>(biotite-based)"]
    end
    
    subgraph "atomworks.ml - ML Pipeline Layer" 
        TRANSFORMS["Transform System"]
        DATASETS["Dataset Wrappers"]
        ENCODINGS["Token Encodings"]
        PIPELINES["Model Pipelines"]
    end
    
    subgraph "External Models"
        AF3["AlphaFold 3"]
        RF2AA["RoseTTAFold 2 All-Atom"]
        CUSTOM["Custom Models"]
    end
    
    subgraph "Interfaces"
        CLI["CLI Commands"]
        API["Python API"]
        CONFIG["Hydra Configuration"]
    end
    
    PDB --> PARSE
    FASTA --> PARSE
    SMILES --> PARSE
    META --> DATASETS
    
    PARSE --> READERS
    PARSE --> CCD
    PARSE --> UTILS
    PARSE --> RDKIT
    
    READERS --> ATOMARRAY
    CCD --> ATOMARRAY
    UTILS --> ATOMARRAY
    RDKIT --> ATOMARRAY
    
    ATOMARRAY --> TRANSFORMS
    DATASETS --> TRANSFORMS
    TRANSFORMS --> ENCODINGS
    TRANSFORMS --> PIPELINES
    
    PIPELINES --> AF3
    PIPELINES --> RF2AA
    PIPELINES --> CUSTOM
    
    CLI --> PARSE
    API --> PARSE
    API --> TRANSFORMS
    CONFIG --> PIPELINES
```

Sources: [README.md:15-22](), [README.md:26-37](), [README.md:40-52]()

## Component Architecture

### atomworks.io - Data Processing Layer

The `atomworks.io` component provides universal data processing capabilities for biological structures and sequences. It handles format conversion, data cleaning, and standardization around the `AtomArray` representation.

```mermaid
graph TB
    subgraph "Input Processing"
        FORMATS["File Format Detection"]
        PARSERS["Format-Specific Parsers"]
        VALIDATION["Data Validation"]
    end
    
    subgraph "Core Processing Engine"
        PARSE_FUNC["parse() function<br/>atomworks/io/parser.py"]
        LOAD_ANY["load_any() function<br/>atomworks/io/utils/io_utils.py"]
        CIF_READER["CIF/PDB/BCIF readers"]
        ASSEMBLY["Assembly Building"]
    end
    
    subgraph "Data Enhancement"
        CCD_LOOKUP["CCD Integration<br/>Chemical Component Dictionary"]
        SEQ_CONV["Sequence Conversion<br/>1-letter ↔ 3-letter codes"]
        HYDROGEN["Hydrogen Handling"]
        BONDS["Bond Inference"]
    end
    
    subgraph "Output"
        ATOM_ARRAY["AtomArray<br/>Unified Structure Format"]
        METADATA_OUT["Structure Metadata"]
        ASSEMBLIES["Biological Assemblies"]
    end
    
    FORMATS --> PARSERS
    PARSERS --> VALIDATION
    VALIDATION --> PARSE_FUNC
    
    PARSE_FUNC --> LOAD_ANY
    PARSE_FUNC --> CIF_READER
    PARSE_FUNC --> ASSEMBLY
    
    CIF_READER --> CCD_LOOKUP
    CIF_READER --> SEQ_CONV
    CIF_READER --> HYDROGEN
    CIF_READER --> BONDS
    
    CCD_LOOKUP --> ATOM_ARRAY
    SEQ_CONV --> ATOM_ARRAY
    HYDROGEN --> ATOM_ARRAY
    BONDS --> ATOM_ARRAY
    ASSEMBLY --> ASSEMBLIES
    PARSE_FUNC --> METADATA_OUT
```

Sources: [README.md:90-123]()

### atomworks.ml - Machine Learning Pipeline Layer

The `atomworks.ml` component provides modular transformation pipelines for converting `AtomArray` structures into ML-ready features. It supports model-specific preprocessing for various foundation models.

```mermaid
graph TB
    subgraph "Transform Infrastructure"
        BASE_TRANSFORM["Transform Base Class<br/>Abstract interface"]
        COMPOSE["Compose<br/>Pipeline chaining"]
        REGISTRY["Transform Registry"]
    end
    
    subgraph "Data Preparation"
        CLEANING["Structure Cleaning<br/>RemoveHydrogens<br/>FilterUnsupportedChains"]
        TOKENIZATION["Tokenization<br/>AtomizeByCCDName<br/>AddGlobalIDs"]
        ENCODING["Encoding<br/>EncodeAtomArray<br/>TokenLevelFeatures"]
    end
    
    subgraph "Feature Engineering"
        MSA["MSA Processing<br/>LoadMSA<br/>FeaturizeMSA"]
        TEMPLATES["Template Processing<br/>LoadTemplates<br/>FilterTemplates"]
        MOLECULAR["Molecular Features<br/>ChiralCenters<br/>BondFeatures"]
    end
    
    subgraph "Model Pipelines"
        AF3_PIPELINE["AF3 Pipeline<br/>build_af3_transform_pipeline"]
        RF2AA_PIPELINE["RF2AA Pipeline<br/>build_rf2aa_transform_pipeline"]
        CUSTOM_PIPELINE["Custom Pipeline<br/>User-defined"]
    end
    
    subgraph "Dataset Management"
        DATASET_WRAPPERS["StructuralDatasetWrapper<br/>PandasDataset"]
        PARSERS["PNUnitsDFParser<br/>InterfacesDFParser"]
        CONFIG_SYS["Hydra Configuration<br/>YAML-based setup"]
    end
    
    BASE_TRANSFORM --> COMPOSE
    COMPOSE --> REGISTRY
    
    REGISTRY --> CLEANING
    REGISTRY --> TOKENIZATION
    REGISTRY --> ENCODING
    REGISTRY --> MSA
    REGISTRY --> TEMPLATES
    REGISTRY --> MOLECULAR
    
    CLEANING --> AF3_PIPELINE
    TOKENIZATION --> AF3_PIPELINE
    ENCODING --> AF3_PIPELINE
    MSA --> AF3_PIPELINE
    TEMPLATES --> AF3_PIPELINE
    
    CLEANING --> RF2AA_PIPELINE
    TOKENIZATION --> RF2AA_PIPELINE
    ENCODING --> RF2AA_PIPELINE
    MOLECULAR --> RF2AA_PIPELINE
    
    CONFIG_SYS --> DATASET_WRAPPERS
    PARSERS --> DATASET_WRAPPERS
    DATASET_WRAPPERS --> COMPOSE
```

Sources: [README.md:44-51](), [README.md:182-262]()

## Data Flow Architecture

The following diagram illustrates how data flows through the AtomWorks system from input files to ML model inputs:

### End-to-End Data Flow

```mermaid
flowchart LR
    subgraph "Input Stage"
        FILES["Biological Files<br/>(.pdb, .cif, .fasta, .sdf)"]
        METADATA["Metadata Files<br/>(.parquet)"]
    end
    
    subgraph "atomworks.io Processing"
        PARSE_ENTRY["parse() Entry Point<br/>Universal parser"]
        FORMAT_DETECT["File Type Detection<br/>Automatic inference"]
        STRUCT_PARSE["Structure Parsing<br/>Format-specific readers"]
        DATA_CLEAN["Data Cleaning<br/>Validation & normalization"]
    end
    
    subgraph "Core Representation"
        ATOM_ARRAY_CORE["AtomArray<br/>• Coordinates<br/>• Element types<br/>• Chain annotations<br/>• Metadata"]
    end
    
    subgraph "atomworks.ml Processing"
        TRANSFORM_PIPELINE["Transform Pipeline<br/>Configurable via Hydra"]
        DATASET_LOAD["Dataset Loading<br/>PandasDataset filtering"]
        FEATURE_ENG["Feature Engineering<br/>MSA, templates, encodings"]
        MODEL_PREP["Model-Specific Preparation<br/>AF3/RF2AA formatting"]
    end
    
    subgraph "Model Input Stage"
        AF3_FEATURES["AF3 Features<br/>• Token encodings<br/>• MSA features<br/>• Template features"]
        RF2AA_FEATURES["RF2AA Features<br/>• Atom coordinates<br/>• Bond features<br/>• Symmetry features"]
    end
    
    FILES --> PARSE_ENTRY
    METADATA --> DATASET_LOAD
    
    PARSE_ENTRY --> FORMAT_DETECT
    FORMAT_DETECT --> STRUCT_PARSE
    STRUCT_PARSE --> DATA_CLEAN
    DATA_CLEAN --> ATOM_ARRAY_CORE
    
    ATOM_ARRAY_CORE --> TRANSFORM_PIPELINE
    DATASET_LOAD --> TRANSFORM_PIPELINE
    TRANSFORM_PIPELINE --> FEATURE_ENG
    FEATURE_ENG --> MODEL_PREP
    
    MODEL_PREP --> AF3_FEATURES
    MODEL_PREP --> RF2AA_FEATURES
```

Sources: [README.md:94-114](), [README.md:165-262]()

## Configuration and Interface Architecture

AtomWorks provides multiple interfaces for different use cases, with configuration management through Hydra:

### Interface Overview

| Interface Type | Primary Use Case | Key Components |
|---|---|---|
| **Python API** | Programmatic access, custom workflows | `parse()`, `load_any()`, Transform classes |
| **CLI Commands** | Data management, environment setup | `atomworks pdb sync`, `atomworks setup` |
| **Hydra Configuration** | ML pipeline configuration | YAML-based dataset and transform configs |

### CLI Command Architecture

```mermaid
graph TB
    subgraph "CLI Entry Points"
        MAIN_CLI["atomworks CLI<br/>Main command group"]
        PDB_CMD["pdb sync<br/>Data synchronization"]
        SETUP_CMD["setup metadata<br/>Environment configuration"]
        TEST_CMD["setup tests<br/>Test data download"]
    end
    
    subgraph "Data Management"
        PDB_MIRROR["PDB Mirror Creation<br/>Carbon-copy download"]
        METADATA_DL["Metadata Download<br/>Pre-computed datasets"]
        TEST_DATA["Test Data Setup<br/>Mini datasets for testing"]
    end
    
    subgraph "Environment Variables"
        PDB_PATH["PDB_MIRROR_PATH<br/>Local PDB location"]
        ENV_FILE[".env file<br/>Configuration persistence"]
    end
    
    MAIN_CLI --> PDB_CMD
    MAIN_CLI --> SETUP_CMD
    MAIN_CLI --> TEST_CMD
    
    PDB_CMD --> PDB_MIRROR
    SETUP_CMD --> METADATA_DL
    TEST_CMD --> TEST_DATA
    
    PDB_MIRROR --> PDB_PATH
    METADATA_DL --> ENV_FILE
```

Sources: [README.md:128-148](), [README.md:150-163](), [README.md:277-290]()

## Token Encoding System

AtomWorks implements a sophisticated token encoding system to bridge molecular representations with ML model requirements:

### Token Encoding Architecture

```mermaid
graph TB
    subgraph "Token Encoding Classes"
        BASE_ENCODING["TokenEncoding Base<br/>Abstract interface"]
        AF2_ENCODING["AF2 Encodings<br/>ATOM14, ATOM37"]
        AF3_ENCODING["AF3 Encodings<br/>Extended atom sets"]
        RF2AA_ENCODING["RF2AA Encodings<br/>ATOM14, ATOM23, ATOM36"]
    end
    
    subgraph "Sequence Mappings"
        RESIDUE_MAP["Residue → Atom Mappings<br/>3-letter to atom lists"]
        ONE_LETTER["1-letter Code Mappings<br/>Sequence representations"]
        CHEMICAL_MAP["Chemical Component Mappings<br/>Non-standard residues"]
    end
    
    subgraph "Model-Specific Outputs"
        AF3_TOKENS["AF3 Token Features<br/>Model-ready tensors"]
        RF2AA_TOKENS["RF2AA Token Features<br/>Atom-level features"]
        CUSTOM_TOKENS["Custom Token Features<br/>User-defined mappings"]
    end
    
    BASE_ENCODING --> AF2_ENCODING
    BASE_ENCODING --> AF3_ENCODING
    BASE_ENCODING --> RF2AA_ENCODING
    
    AF2_ENCODING --> RESIDUE_MAP
    AF3_ENCODING --> RESIDUE_MAP
    RF2AA_ENCODING --> RESIDUE_MAP
    
    RESIDUE_MAP --> ONE_LETTER
    RESIDUE_MAP --> CHEMICAL_MAP
    
    AF3_ENCODING --> AF3_TOKENS
    RF2AA_ENCODING --> RF2AA_TOKENS
    BASE_ENCODING --> CUSTOM_TOKENS
```

Sources: [README.md:169-181]()

## Infrastructure Components

The AtomWorks system includes several infrastructure components for development, testing, and deployment:

### Development Infrastructure

| Component | Purpose | Key Technologies |
|---|---|---|
| **CI/CD Pipeline** | Automated testing and deployment | GitHub Actions, semantic-release |
| **Documentation System** | API docs and user guides | Sphinx, versioned docs |
| **Package Distribution** | PyPI releases | Python packaging, version management |
| **Code Quality** | Linting and testing | Ruff, pytest |

### External Dependencies

AtomWorks builds upon several key external libraries:

- **biotite**: Core structural biology operations and `AtomArray` representation
- **torch**: Machine learning framework for transforms and models  
- **rdkit**: Chemical informatics and small molecule handling
- **numpy**: Numerical operations and array manipulations
- **hydra**: Configuration management for ML pipelines

Sources: [README.md:1-6](), [.github/workflows/release_and_docs.yaml:1-159](), [docs/conf.py:1-98]()

---