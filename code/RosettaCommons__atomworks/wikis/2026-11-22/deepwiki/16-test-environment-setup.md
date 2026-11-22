# Test Environment Setup

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



This document covers setting up the test environment for AtomWorks development and evaluation. The test environment provides a minimal dataset with representative samples from the PDB, MSA data, templates, and metadata that enables testing and validation of ML pipelines without requiring full dataset downloads.

For information about setting up production PDB mirrors and metadata, see [Data Synchronization](#4.1). For overall project configuration and development setup, see [Project Configuration and Development](#5).

## Purpose and Scope

The test environment setup provides a streamlined way to:

- Download and configure test data (~500 MB) for development and validation
- Create a miniature version of the full PDB processing pipeline
- Test ML workflows including AF3 and RF2AA pipelines without full dataset requirements
- Validate data processing transforms and dataset loading functionality

## Test Data CLI Command

The primary interface for test environment setup is the `atomworks setup tests` command, which downloads and extracts a curated test dataset.

```bash
atomworks setup tests  # Downloads test pack to `tests/data` and unpacks it there (~500 MB)
```

This command creates a complete test environment with representative biological data samples that mirror the structure of production datasets.

Sources: [README.md:277-283]()

## Test Data Structure

The test setup creates a hierarchical directory structure that mirrors production data organization:

```mermaid
graph TB
    subgraph "Test Data Directory Structure"
        TestsData["tests/data/"]
        
        subgraph "Structure Data"
            PDB["tests/data/pdb/"]
            CCD["tests/data/ccd/"]
        end
        
        subgraph "ML Support Data"
            Shared["tests/data/shared/"]
            Templates["Template data"]
            MSAs["MSA data"]
        end
        
        subgraph "Metadata"
            AF2Dist["data/ml/af2_distillation/"]
            PNUnits["data/ml/pdb_pn_units/"]
            Interfaces["data/ml/pdb_interfaces/"]
        end
    end
    
    TestsData --> PDB
    TestsData --> CCD
    TestsData --> Shared
    Shared --> Templates
    Shared --> MSAs
    TestsData --> AF2Dist
    TestsData --> PNUnits
    TestsData --> Interfaces
```

**Test Data Components:**

| Component | Location | Purpose |
|-----------|----------|---------|
| Mini PDB | `tests/data/pdb/` | Representative protein structure files |
| Custom CCD | `tests/data/ccd/` | Chemical Component Dictionary for ligands |
| MSA Data | `tests/data/shared/` | Multiple Sequence Alignments |
| Templates | `tests/data/shared/` | Template structures for modeling |
| AF2 Distillation | `data/ml/af2_distillation/` | AlphaFold2 distillation data |
| PN Units Metadata | `data/ml/pdb_pn_units/` | Polymer/non-polymer unit metadata |
| Interface Metadata | `data/ml/pdb_interfaces/` | Protein-protein interface data |

Sources: [README.md:280-283]()

## Test Environment Components

The test environment integrates with the core AtomWorks systems to provide a complete testing framework:

```mermaid
flowchart LR
    subgraph "Test Data Setup"
        CLI["atomworks setup tests"]
        Download["Download test pack"]
        Extract["Extract to tests/data/"]
    end
    
    subgraph "Test Data Sources"
        TestPDB["Mini PDB files"]
        TestCCD["Custom CCD"]
        TestMSA["MSA samples"]
        TestTemplates["Template data"]
        TestMetadata["Metadata samples"]
    end
    
    subgraph "Testing Integration"
        ConfTest["tests/ml/conftest.py"]
        DatasetConfig["Dataset configuration"]
        PipelineTest["Pipeline testing"]
    end
    
    subgraph "ML Pipeline Testing"
        AF3Pipeline["AF3 transform pipeline"]
        RF2AATestPipeline["RF2AA transform pipeline"]
        DataLoading["Dataset loading tests"]
    end
    
    CLI --> Download
    Download --> Extract
    Extract --> TestPDB
    Extract --> TestCCD
    Extract --> TestMSA
    Extract --> TestTemplates
    Extract --> TestMetadata
    
    TestPDB --> ConfTest
    TestCCD --> ConfTest
    TestMSA --> ConfTest
    TestTemplates --> ConfTest
    TestMetadata --> ConfTest
    
    ConfTest --> DatasetConfig
    DatasetConfig --> PipelineTest
    PipelineTest --> AF3Pipeline
    PipelineTest --> RF2AATestPipeline
    PipelineTest --> DataLoading
```

**Key Integration Points:**

- **Dataset Configuration**: Test datasets configured in `tests/ml/conftest.py` line 300
- **Transform Pipeline Testing**: Validates AF3 and RF2AA transform pipelines with test data
- **Data Loading Validation**: Tests PandasDataset and StructuralDatasetWrapper functionality
- **Environment Variables**: Test setup respects `PDB_MIRROR_PATH` and other configuration

Sources: [README.md:283]()

## Running Test Pipelines

Once the test environment is set up, you can run comprehensive pipeline tests:

```bash
# Set up environment (if not already configured)
export PDB_MIRROR_PATH=/path/to/test/pdb

# Run ML pipeline tests
pytest tests/ml/test_data_loading_pipelines.py
```

The test framework validates:

- Data parsing and loading from test PDB files
- Transform pipeline execution with representative data
- Dataset filtering and sampling functionality
- MSA and template integration
- Metadata handling and validation

```mermaid
graph TB
    subgraph "Test Execution Flow"
        TestCommand["pytest tests/ml/test_data_loading_pipelines.py"]
        
        subgraph "Data Loading Tests"
            ParseTest["Test file parsing"]
            FilterTest["Test dataset filtering"]
            TransformTest["Test transform pipelines"]
        end
        
        subgraph "Pipeline Validation"
            AF3Test["AF3 pipeline validation"]
            RF2AATest["RF2AA pipeline validation"]
            FeatureTest["Feature engineering validation"]
        end
        
        subgraph "Integration Testing"
            MSATest["MSA integration test"]
            TemplateTest["Template integration test"]
            MetadataTest["Metadata validation test"]
        end
    end
    
    TestCommand --> ParseTest
    TestCommand --> FilterTest
    TestCommand --> TransformTest
    
    ParseTest --> AF3Test
    FilterTest --> RF2AATest
    TransformTest --> FeatureTest
    
    AF3Test --> MSATest
    RF2AATest --> TemplateTest
    FeatureTest --> MetadataTest
```

Sources: [README.md:285-290]()

## Test vs Production Environment Mapping

The test environment provides a scaled-down version of the production data processing pipeline:

| Production Component | Test Equivalent | Scale Factor |
|---------------------|----------------|--------------|
| Full PDB mirror (~100 GB) | `tests/data/pdb/` | ~500 MB total |
| Complete metadata | Sample metadata files | Representative subset |
| Full MSA databases | `tests/data/shared/` MSAs | Selected examples |
| Template databases | `tests/data/shared/` templates | Curated samples |
| Production configs | Test configurations | Simplified parameters |

```mermaid
graph LR
    subgraph "Production Pipeline"
        ProdPDB["Full PDB Mirror"]
        ProdMetadata["Complete Metadata"]
        ProdMSA["Full MSA Databases"]
        ProdTemplates["Template Databases"]
    end
    
    subgraph "Test Environment"
        TestPDB["Mini PDB"]
        TestMetadata["Sample Metadata"]
        TestMSA["Sample MSAs"]
        TestTemplates["Sample Templates"]
    end
    
    subgraph "Validation"
        SameAPI["Same API"]
        SameTransforms["Same Transforms"]
        SameWorkflows["Same Workflows"]
    end
    
    ProdPDB -.->|"Representative samples"| TestPDB
    ProdMetadata -.->|"Subset"| TestMetadata
    ProdMSA -.->|"Examples"| TestMSA
    ProdTemplates -.->|"Curated"| TestTemplates
    
    TestPDB --> SameAPI
    TestMetadata --> SameTransforms
    TestMSA --> SameWorkflows
    TestTemplates --> SameWorkflows
```

The test environment ensures that development and validation can proceed with the same APIs and workflows as production, while requiring significantly less storage and download time.

Sources: [README.md:277-283](), [README.md:128-164]()

---