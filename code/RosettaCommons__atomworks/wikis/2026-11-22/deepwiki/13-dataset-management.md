# Dataset Management

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



This page documents the dataset management system in `atomworks.ml`, which provides infrastructure for loading, filtering, and wrapping biological datasets for machine learning workflows. The system handles both metadata-driven sampling from large databases like the PDB and direct data loading for training and inference.

For information about the transform pipelines that process dataset outputs, see [Transform Pipeline](#3.1). For model-specific pipeline configurations, see [Model-Specific Pipelines](#3.3).

## Core Architecture

The dataset management system consists of three main layers: dataset parsers that extract examples from data sources, dataset wrappers that apply transforms and handle batching, and configuration systems that coordinate the components.

```mermaid
graph TB
    subgraph "Data Sources"
        A["pn_units_df.parquet"]
        B["interfaces_df.parquet"] 
        C["PDB mmCIF files"]
        D["MSA files"]
    end
    
    subgraph "Dataset Parsers"
        E["PNUnitsDFParser"]
        F["InterfacesDFParser"]
    end
    
    subgraph "Dataset Wrappers"
        G["PandasDataset"]
        H["StructuralDatasetWrapper"]
        I["ConcatDatasetWithID"]
    end
    
    subgraph "Transform Integration"
        J["Transform Pipeline"]
        K["AtomArray Output"]
    end
    
    A --> E
    B --> F
    E --> G
    F --> G
    G --> H
    H --> I
    H --> J
    J --> K
    C --> H
    D --> H
```

**Dataset Management Architecture**

Sources: [README.md:182-262]()

## Dataset Parsers

Dataset parsers extract individual examples from structured data sources and convert them into loadable formats for ML workflows.

### PNUnitsDFParser

The `PNUnitsDFParser` processes metadata for individual polymer and non-polymer units (chains, ligands) from PDB structures. It reads from parquet files containing per-unit metadata and generates example IDs that can be loaded as individual structures.

```mermaid
graph LR
    A["pn_units_df.parquet"] --> B["PNUnitsDFParser"]
    B --> C["Example IDs"]
    C --> D["Individual PDB chains/ligands"]
    
    subgraph "Metadata Columns"
        E["deposition_date"]
        F["resolution"] 
        G["method"]
        H["cluster"]
        I["q_pn_unit_type"]
    end
    
    A -.-> E
    A -.-> F
    A -.-> G
    A -.-> H
    A -.-> I
```

**PNUnitsDFParser Data Flow**

The parser supports filtering based on metadata columns such as resolution, deposition date, experimental method, and chain type. Common filters include excluding NMR structures, setting resolution cutoffs, and selecting specific polymer types.

Sources: [README.md:186-221]()

### InterfacesDFParser

The `InterfacesDFParser` handles binary interface metadata, processing parquet files that contain information about protein-protein, protein-ligand, and other molecular interfaces within PDB structures.

```mermaid
graph LR
    A["interfaces_df.parquet"] --> B["InterfacesDFParser"]
    B --> C["Interface Example IDs"]
    C --> D["PDB interface regions"]
    
    subgraph "Interface Metadata"
        E["pn_unit_1_type"]
        F["pn_unit_2_type"]
        G["interface_area"]
        H["num_polymer_pn_units"]
    end
    
    A -.-> E
    A -.-> F
    A -.-> G
    A -.-> H
```

**InterfacesDFParser Data Flow**

Interface examples include spatial cropping around interaction regions and support filtering based on interface properties, partner types, and structural quality metrics.

Sources: [README.md:223-261]()

## Dataset Wrappers

Dataset wrappers coordinate between parsers, transforms, and the broader ML pipeline, handling data loading, filtering, and preprocessing.

### PandasDataset

The `PandasDataset` class provides the foundation for metadata-driven dataset loading. It loads parquet files, applies user-defined filters, and generates example IDs for downstream processing.

| Configuration | Purpose | Example |
|---------------|---------|---------|
| `data` | Path to parquet file | `/path/to/metadata/pn_units_df.parquet` |
| `filters` | List of pandas query strings | `["resolution < 5.0", "method in ['X-RAY_DIFFRACTION']"]` |
| `id_column` | Column containing example IDs | `"example_id"` |
| `columns_to_load` | Subset of columns to load | `null` (load all) |

```mermaid
graph TB
    A["Parquet File"] --> B["PandasDataset"]
    B --> C["Apply Filters"]
    C --> D["Extract Example IDs"]
    D --> E["StructuralDatasetWrapper"]
    
    subgraph "Filter Examples"
        F["deposition_date < '2022-01-01'"]
        G["resolution < 5.0"]
        H["method in ['X-RAY_DIFFRACTION']"]
        I["q_pn_unit_type in [5, 6]"]
    end
    
    C -.-> F
    C -.-> G
    C -.-> H
    C -.-> I
```

**PandasDataset Processing Flow**

Sources: [README.md:205-220](), [README.md:242-258]()

### StructuralDatasetWrapper

The `StructuralDatasetWrapper` coordinates between dataset parsers and transform pipelines, loading structural data based on example IDs and applying the configured transform pipeline.

```mermaid
graph TB
    A["Dataset Parser"] --> B["StructuralDatasetWrapper"]
    B --> C["Load PDB/mmCIF"]
    C --> D["Apply Transform Pipeline"]
    D --> E["Output AtomArray"]
    
    subgraph "Components"
        F["dataset_parser"]
        G["transform"] 
        H["dataset"]
        I["cif_parser_args"]
    end
    
    B -.-> F
    B -.-> G
    B -.-> H
    B -.-> I
    
    subgraph "Error Handling"
        J["save_failed_examples_to_dir"]
        K["Log parsing failures"]
    end
    
    D -.-> J
    D -.-> K
```

**StructuralDatasetWrapper Architecture**

The wrapper handles file loading from PDB mirrors, applies data cleaning and featurization transforms, and manages error handling for failed examples.

Sources: [README.md:185-188](), [README.md:224-227]()

### ConcatDatasetWithID

The `ConcatDatasetWithID` class combines multiple dataset sources (e.g., single chains and interfaces) into a unified training dataset while preserving example identification.

```mermaid
graph TB
    subgraph "Dataset Sources"
        A["PN Units Dataset"]
        B["Interfaces Dataset"]
        C["Custom Dataset"]
    end
    
    D["ConcatDatasetWithID"] 
    A --> D
    B --> D
    C --> D
    
    subgraph "Unified Output"
        E["Combined Example Stream"]
        F["Preserved IDs"]
        G["Mixed Sampling"]
    end
    
    D --> E
    D --> F
    D --> G
```

**ConcatDatasetWithID Structure**

This enables training on diverse example types within a single pipeline, supporting mixed sampling strategies across different data modalities.

Sources: [README.md:183-184]()

## Configuration Patterns

Dataset management integrates with Hydra configuration to enable declarative pipeline definition through YAML files.

### Hydra Integration

```yaml
af3_pdb_dataset:
  _target_: atomworks.ml.datasets.datasets.ConcatDatasetWithID
  datasets:
    - _target_: atomworks.ml.datasets.datasets.StructuralDatasetWrapper
      dataset_parser:
        _target_: atomworks.ml.datasets.parsers.PNUnitsDFParser
      dataset:
        _target_: atomworks.ml.datasets.datasets.PandasDataset
        data: /path/to/metadata/pn_units_df.parquet
        filters:
          - "deposition_date < '2022-01-01'"
          - "resolution < 5.0"
```

### Transform Pipeline Integration

Dataset wrappers connect to transform pipelines through the `transform` parameter, enabling model-specific data processing:

```mermaid
graph LR
    A["StructuralDatasetWrapper"] --> B["AF3 Transform Pipeline"]
    A --> C["RF2AA Transform Pipeline"] 
    A --> D["Custom Transform Pipeline"]
    
    subgraph "Transform Outputs"
        E["AF3 Features"]
        F["RF2AA Features"]
        G["Custom Features"]
    end
    
    B --> E
    C --> F
    D --> G
```

**Transform Pipeline Integration**

Sources: [README.md:189-200](), [README.md:228-241]()

## Usage Examples

### Basic Single Dataset

```yaml
single_chain_dataset:
  _target_: atomworks.ml.datasets.datasets.StructuralDatasetWrapper
  dataset_parser:
    _target_: atomworks.ml.datasets.parsers.PNUnitsDFParser
  dataset:
    _target_: atomworks.ml.datasets.datasets.PandasDataset
    data: /path/to/pn_units_df.parquet
    filters:
      - "q_pn_unit_type in [5, 6]"  # Polypeptides only
  transform:
    _target_: atomworks.ml.pipelines.af3.build_af3_transform_pipeline
```

### Multi-Source Training Dataset

The system supports combining multiple data sources with different sampling strategies:

```mermaid
graph TB
    subgraph "Training Configuration"
        A["Single Chains"]
        B["Binary Interfaces"] 
        C["Custom Examples"]
    end
    
    D["ConcatDatasetWithID"]
    A --> D
    B --> D
    C --> D
    
    subgraph "Shared Components"
        E["Common Transform Pipeline"]
        F["Unified Batching"]
        G["Error Handling"]
    end
    
    D --> E
    D --> F
    D --> G
```

**Multi-Source Dataset Architecture**

This enables training on diverse molecular contexts while maintaining consistent preprocessing and batching across example types.

Sources: [README.md:165-275]()

## Error Handling and Debugging

The dataset system includes comprehensive error handling for production ML workflows:

| Feature | Purpose | Configuration |
|---------|---------|---------------|
| Failed example logging | Track parsing failures | `save_failed_examples_to_dir` |
| Parser arguments | Custom CIF parsing | `cif_parser_args` |
| Cache control | Manage temporary files | `cache_dir` |
| Column filtering | Reduce memory usage | `columns_to_load` |

Failed examples are logged with detailed error information to enable debugging and data quality analysis.

Sources: [README.md:221](), [README.md:260-261]()

---