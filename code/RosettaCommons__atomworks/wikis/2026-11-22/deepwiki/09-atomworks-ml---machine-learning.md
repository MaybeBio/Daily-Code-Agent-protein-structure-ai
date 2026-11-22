# atomworks.ml - Machine Learning

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.github/workflows/lint_and_test.yaml](.github/workflows/lint_and_test.yaml)
- [.gitignore](.gitignore)
- [pyproject.toml](pyproject.toml)
- [src/atomworks/io/utils/ccd.py](src/atomworks/io/utils/ccd.py)
- [src/atomworks/io/utils/sequence.py](src/atomworks/io/utils/sequence.py)
- [src/atomworks/ml/encoding_definitions.py](src/atomworks/ml/encoding_definitions.py)
- [src/atomworks/ml/pipelines/af3.py](src/atomworks/ml/pipelines/af3.py)
- [src/atomworks/ml/pipelines/rf2aa.py](src/atomworks/ml/pipelines/rf2aa.py)
- [src/atomworks/ml/transforms/encoding.py](src/atomworks/ml/transforms/encoding.py)
- [src/atomworks/ml/transforms/msa/_msa_constants.py](src/atomworks/ml/transforms/msa/_msa_constants.py)
- [src/atomworks/ml/transforms/template.py](src/atomworks/ml/transforms/template.py)
- [tests/io/components/test_regression.py](tests/io/components/test_regression.py)
- [tests/io/tools/test_rdkit.py](tests/io/tools/test_rdkit.py)
- [tests/io/utils/test_sequence_maps.py](tests/io/utils/test_sequence_maps.py)
- [tests/io/utils/test_sequence_utils.py](tests/io/utils/test_sequence_utils.py)
- [tests/ml/conftest.py](tests/ml/conftest.py)
- [tests/ml/transforms/msa/test_featurize_msa.py](tests/ml/transforms/msa/test_featurize_msa.py)
- [tests/ml/utils/test_io.py](tests/ml/utils/test_io.py)

</details>



The `atomworks.ml` module provides machine learning capabilities for processing biomolecular structures and training foundation models. This system transforms biological data from `atomworks.io` into ML-compatible formats through modular transform pipelines, handles token encodings for different model architectures, and provides pre-built pipelines for specific foundation models like AlphaFold 3 and RoseTTAFold 2 All-Atom.

For information about data parsing and biological file format handling, see [atomworks.io - Data Processing](#2). For details about external tool integration and extending the system, see [External Tool Integration](#6.1) and [Extending AtomWorks](#6.2).

## System Architecture

The `atomworks.ml` system is built around a modular transform pipeline architecture that processes `AtomArray` objects from `atomworks.io` into tensor-based representations suitable for machine learning models.

### Core ML Pipeline Architecture

```mermaid
graph TB
    subgraph "Input Data"
        A1["AtomArray from atomworks.io"]
        A2["Chain Info Metadata"]
        A3["External MSA Files"]
        A4["Template Structures"]
    end
    
    subgraph "Transform Pipeline Engine"
        B1["Transform Base Class"]
        B2["Compose - Pipeline Chaining"]
        B3["ConditionalRoute - Branching Logic"]
        B4["RandomRoute - Stochastic Transforms"]
    end
    
    subgraph "Data Processing Transforms"
        C1["RemoveHydrogens"]
        C2["AtomizeByCCDName"]
        C3["EncodeAtomArray"]
        C4["CropSpatialLikeAF3"]
        C5["LoadPolymerMSAs"]
    end
    
    subgraph "Feature Engineering"
        D1["FeaturizeMSALikeAF3"]
        D2["AddAF3ChiralFeatures"]
        D3["AddAtomFrames"]
        D4["AggregateFeaturesLikeAF3"]
    end
    
    subgraph "Model Outputs"
        E1["AF3 Feature Dict"]
        E2["RF2AA Feature Dict"]
        E3["Custom Model Features"]
    end
    
    A1 --> B1
    A2 --> B1
    A3 --> C5
    A4 --> B1
    
    B1 --> B2
    B2 --> B3
    B3 --> B4
    
    B4 --> C1
    C1 --> C2
    C2 --> C3
    C3 --> C4
    C4 --> C5
    
    C5 --> D1
    D1 --> D2
    D2 --> D3
    D3 --> D4
    
    D4 --> E1
    D4 --> E2
    D4 --> E3
```

**Sources:** [src/atomworks/ml/transforms/base.py:1-50](), [src/atomworks/ml/pipelines/af3.py:84-133](), [src/atomworks/ml/pipelines/rf2aa.py:154-205]()

### Transform System Data Flow

```mermaid
flowchart LR
    subgraph "Data Preparation Stage"
        A1["atom_array_to_encoding()"]
        A2["TokenEncoding.token_to_idx"]
        A3["encoded_coord [N, M, 3]"]
        A4["encoded_mask [N, M]"]
        A5["encoded_seq [N]"]
    end
    
    subgraph "Feature Aggregation Stage"
        B1["AggregateFeaturesLikeAF3"]
        B2["AggregateFeaturesLikeRF2AA"]
        B3["PackageConfidenceFeats"]
    end
    
    subgraph "Model Input Format"
        C1["feats dict with tensors"]
        C2["RF2AAInputs NamedTuple"]
        C3["confidence_feats dict"]
    end
    
    A1 --> A2
    A2 --> A3
    A2 --> A4
    A2 --> A5
    
    A3 --> B1
    A4 --> B1
    A5 --> B1
    
    A3 --> B2
    A4 --> B2
    A5 --> B2
    
    B1 --> C1
    B2 --> C2
    B1 --> C3
```

**Sources:** [src/atomworks/ml/transforms/encoding.py:34-187](), [src/atomworks/ml/transforms/feature_aggregation/af3.py](), [src/atomworks/ml/pipelines/rf2aa.py:71-147]()

## Transform Pipeline System

The transform pipeline system provides a modular framework for data processing through the `Transform` base class and composition utilities. Each transform is a self-contained operation that can be chained together to create complex processing pipelines.

### Core Transform Classes

| Transform Class | Purpose | Key Methods |
|---|---|---|
| `Transform` | Abstract base class for all transforms | `forward()`, `check_input()` |
| `Compose` | Chains multiple transforms sequentially | `__call__()` |
| `ConditionalRoute` | Routes data based on conditions | `condition_func` parameter |
| `RandomRoute` | Stochastic routing between transforms | `probs` parameter |
| `Identity` | Pass-through transform | No-op operation |

### Key Data Processing Transforms

The system includes specialized transforms for different aspects of biomolecular data processing:

**Structural Transforms:**
- `RemoveHydrogens` - Removes hydrogen atoms from structures
- `AtomizeByCCDName` - Converts residues to individual atoms based on CCD codes
- `CropSpatialLikeAF3` - Spatial cropping around regions of interest
- `CropContiguousLikeAF3` - Contiguous sequence cropping

**Encoding Transforms:**
- `EncodeAtomArray` - Converts `AtomArray` to encoded tensors
- `EncodeAF3TokenLevelFeatures` - AF3-specific token encoding
- `EncodeMSA` - Multiple sequence alignment encoding

**Feature Engineering Transforms:**
- `AddAtomFrames` - Computes local coordinate frames
- `AddAF3ChiralFeatures` - Chirality information for AF3
- `AddRF2AABondFeaturesMatrix` - Bond connectivity features

**Sources:** [src/atomworks/ml/transforms/base.py:20-200](), [src/atomworks/ml/transforms/encoding.py:300-400](), [src/atomworks/ml/transforms/atom_array.py:1-50]()

## Token Encoding System

The token encoding system converts molecular structures into fixed-length representations suitable for transformer-based models. The system supports both residue-level and atom-level tokenization.

### TokenEncoding Architecture

```mermaid
graph TB
    subgraph "TokenEncoding Class"
        A1["token_atoms: dict[str, np.ndarray]"]
        A2["chemcomp_type_to_unknown: dict"]
        A3["token_to_idx: dict"]
        A4["atom_to_idx: dict"]
    end
    
    subgraph "Encoding Types"
        B1["AF2_ATOM14_ENCODING"]
        B2["AF2_ATOM37_ENCODING"] 
        B3["RF2AA_ATOM36_ENCODING"]
        B4["AF3SequenceEncoding"]
    end
    
    subgraph "Token Resolution"
        C1["resolve_unknown_token_name()"]
        C2["UNKNOWN_ELEMENT_TOKEN = 0"]
        C3["chemcomp_type mapping"]
    end
    
    A1 --> C1
    A2 --> C1
    A3 --> B1
    A3 --> B2
    A3 --> B3
    A3 --> B4
    
    C1 --> C2
    C1 --> C3
```

### Standard Encodings

The system provides several pre-defined encodings for popular model architectures:

| Encoding | Atoms per Token | Use Case | Special Features |
|---|---|---|---|
| `AF2_ATOM14_ENCODING` | 14 | AlphaFold2 protein models | Standard amino acids only |
| `AF2_ATOM37_ENCODING` | 37 | AlphaFold2 with extended atoms | Includes OXT terminal atom |
| `RF2AA_ATOM36_ENCODING` | 36 | RoseTTAFold All-Atom | Multi-modal (protein/DNA/RNA/atoms) |
| `AF3SequenceEncoding` | Variable | AlphaFold3 sequence encoding | Hierarchical token structure |

### Token Type Handling

The encoding system distinguishes between different token types:

**Residue-level tokens:** Standard 3-letter CCD codes (e.g., "ALA", "GLY", "DA", "C")
**Atom-level tokens:** Atomic numbers as integers (e.g., 6 for Carbon, 7 for Nitrogen)
**Special tokens:** Masked tokens using angle bracket syntax (e.g., "<M>", "<G>")

**Sources:** [src/atomworks/ml/encoding_definitions.py:36-251](), [src/atomworks/ml/encoding_definitions.py:254-332](), [src/atomworks/ml/encoding_definitions.py:422-520]()

## Model-Specific Pipelines

The system provides pre-built pipelines optimized for specific foundation models, handling their unique data requirements and processing steps.

### AF3 Pipeline Architecture

```mermaid
graph TB
    subgraph "AF3 Pipeline build_af3_transform_pipeline()"
        A1["is_inference parameter"]
        A2["crop_size = 384"]
        A3["diffusion_batch_size = 48"]
        A4["run_confidence_head"]
    end
    
    subgraph "AF3 Processing Stages"
        B1["Data Cleaning Stage"]
        B2["Cropping Stage"] 
        B3["Template Loading Stage"]
        B4["MSA Processing Stage"]
        B5["Diffusion Preparation Stage"]
    end
    
    subgraph "AF3 Transform Sequence"
        C1["RemoveHydrogens"]
        C2["FilterToSpecifiedPNUnits"]
        C3["AtomizeByCCDName"]
        C4["CropContiguousLikeAF3 | CropSpatialLikeAF3"]
        C5["LoadPolymerMSAs"]
        C6["GetAF3ReferenceMoleculeFeatures"]
        C7["BatchStructuresForDiffusionNoising"]
        C8["SampleEDMNoise"]
    end
    
    A1 --> B1
    A2 --> B2
    A3 --> B5
    A4 --> B5
    
    B1 --> C1
    B1 --> C2
    B1 --> C3
    B2 --> C4
    B3 --> C5
    B4 --> C6
    B5 --> C7
    B5 --> C8
```

### RF2AA Pipeline Architecture

```mermaid
graph TB
    subgraph "RF2AA Pipeline build_rf2aa_transform_pipeline()"
        A1["crop_size = 256"]
        A2["n_recycles = 5"]
        A3["assert_rf2aa_assumptions"]
        A4["convert_feats_to_rf2aa_input_tuple"]
    end
    
    subgraph "RF2AA Transform Sequence"
        B1["RemoveHydrogens"]
        B2["SortLikeRF2AA"]
        B3["AtomizeByCCDName"]
        B4["EncodeAtomArray with RF2AA_ATOM36_ENCODING"]
        B5["LoadPolymerMSAs"]
        B6["AddRF2AABondFeaturesMatrix"]
        B7["AggregateFeaturesLikeRF2AA"]
        B8["AssertRF2AAAssumptions"]
    end
    
    subgraph "RF2AA Output Format"
        C1["RF2AAInputs NamedTuple"]
        C2["seq: np.ndarray"]
        C3["msa: np.ndarray"] 
        C4["xyz: np.ndarray"]
        C5["mask: np.ndarray"]
        C6["bond_feats: np.ndarray"]
    end
    
    A1 --> B3
    A2 --> B5
    A3 --> B8
    A4 --> C1
    
    B1 --> B2
    B2 --> B3
    B3 --> B4
    B4 --> B5
    B5 --> B6
    B6 --> B7
    B7 --> B8
    B8 --> C1
    
    C1 --> C2
    C1 --> C3
    C1 --> C4
    C1 --> C5
    C1 --> C6
```

### Pipeline Configuration

Both pipelines support extensive configuration through parameters:

**Common Parameters:**
- `protein_msa_dirs` / `rna_msa_dirs` - MSA directory configurations
- `crop_size` - Maximum tokens in cropped structures  
- `n_recycles` - Number of model recycles during training
- `template_lookup_path` / `template_base_dir` - Template structure paths

**AF3-Specific Parameters:**
- `diffusion_batch_size` - Batch size for diffusion noising
- `sigma_data` - Diffusion noise scaling parameter
- `conformer_generation_timeout` - Timeout for ligand conformer generation

**RF2AA-Specific Parameters:**
- `max_automorphs` / `max_isomorphs` - Symmetry resolution limits
- `black_hole_init` - Initialization strategy
- `unclamp_loss_probability` - Training loss unclamping

**Sources:** [src/atomworks/ml/pipelines/af3.py:84-403](), [src/atomworks/ml/pipelines/rf2aa.py:154-350]()

## Dataset Management

The dataset management system provides flexible data loading and preprocessing capabilities through wrapper classes and parsers.

### Dataset Wrapper Architecture

```mermaid
graph TB
    subgraph "Core Dataset Classes"
        A1["PandasDataset"]
        A2["StructuralDatasetWrapper"] 
        A3["ConcatDatasetWithID"]
    end
    
    subgraph "Dataset Parsers"
        B1["PNUnitsDFParser"]
        B2["InterfacesDFParser"]
        B3["ValidationDFParserLikeAF3"]
        B4["GenericDFParser"]
    end
    
    subgraph "Data Sources"
        C1["Parquet metadata files"]
        C2["CIF structure files"]
        C3["Chain info annotations"]
        C4["Filter expressions"]
    end
    
    A2 --> A1
    A2 --> B1
    A2 --> B2
    A2 --> B3
    A2 --> B4
    
    B1 --> C1
    B2 --> C1
    B3 --> C1
    B4 --> C2
    
    C1 --> C3
    C1 --> C4
```

### Key Dataset Components

**PandasDataset:** Base dataset class that loads tabular metadata and applies filters
- `data`: DataFrame with example metadata
- `id_column`: Column name for unique example identifiers  
- `filters`: List of pandas query expressions for data filtering
- `columns_to_load`: Subset of columns to load (memory optimization)

**StructuralDatasetWrapper:** Combines tabular metadata with structural data loading
- `dataset`: Underlying `PandasDataset` instance
- `dataset_parser`: Parser for converting metadata to file paths
- `transform`: Transform pipeline to apply to loaded structures
- `cif_parser_args`: Arguments passed to CIF file parsing

**Dataset Parsers:** Convert metadata rows to structure file paths and parsing arguments
- `PNUnitsDFParser`: Extracts individual polymer-non-polymer units
- `InterfacesDFParser`: Handles protein-protein/protein-nucleic interfaces
- `ValidationDFParserLikeAF3`: Formats validation datasets for AF3-style evaluation

### Usage Example

The system supports complex dataset composition and filtering:

```python
# Create base dataset with filtering
pn_units_dataset = PandasDataset(
    data=metadata_df,
    id_column="example_id", 
    filters=[
        "deposition_date < '2022-01-01'",
        "resolution < 5.0",
        "num_polymer_pn_units <= 20"
    ]
)

# Wrap with structural processing
structural_dataset = StructuralDatasetWrapper(
    dataset=pn_units_dataset,
    dataset_parser=PNUnitsDFParser(),
    transform=build_af3_transform_pipeline(...),
    cif_parser_args={"cache_dir": None}
)
```

**Sources:** [src/atomworks/ml/datasets/datasets.py](), [src/atomworks/ml/datasets/parsers/](), [tests/ml/conftest.py:167-244]()

## MSA and Template Processing

The system provides comprehensive support for Multiple Sequence Alignments (MSAs) and template structure processing, essential for modern protein structure prediction models.

### MSA Processing Pipeline

```mermaid
graph TB
    subgraph "MSA Loading Stage"
        A1["LoadPolymerMSAs"]
        A2["protein_msa_dirs config"]
        A3["rna_msa_dirs config"]
        A4["max_msa_sequences limit"]
    end
    
    subgraph "MSA Pairing and Encoding"
        B1["PairAndMergePolymerMSAs"]
        B2["EncodeMSA"]
        B3["FillFullMSAFromEncoded"]
    end
    
    subgraph "MSA Featurization"
        C1["FeaturizeMSALikeAF3"]
        C2["FeaturizeMSALikeRF2AA"]
        C3["get_full_msa_profile_and_insertion_mean()"]
    end
    
    subgraph "MSA Output Features"
        D1["encoded_msa tensor"]
        D2["msa_mask tensor"]
        D3["full_msa_profile tensor"]
        D4["insertion_mean tensor"]
    end
    
    A1 --> A2
    A1 --> A3
    A1 --> A4
    A1 --> B1
    
    B1 --> B2
    B2 --> B3
    
    B3 --> C1
    B3 --> C2
    B3 --> C3
    
    C1 --> D1
    C1 --> D2
    C2 --> D1
    C2 --> D2
    C3 --> D3
    C3 --> D4
```

### Template Structure Processing

```mermaid
graph TB
    subgraph "Template Loading"
        A1["AddRFTemplates"]
        A2["template_lookup_path"]
        A3["template_base_dir"]
        A4["RF2AATemplate dataclass"]
    end
    
    subgraph "Template Selection"
        B1["max_n_template parameter"]
        B2["seq_similarity filtering"]
        B3["min_template_length filtering"]
        B4["RandomSubsampleTemplates"]
    end
    
    subgraph "Template Featurization"
        C1["FeaturizeTemplatesLikeAF3"]
        C2["FeaturizeTemplatesLikeRF2AA"]
        C3["OneHotTemplateRestype"]
    end
    
    subgraph "Template Features"
        D1["template_xyz tensor"]
        D2["template_mask tensor"]
        D3["template_t1d tensor"]
        D4["template_origin array"]
    end
    
    A1 --> A2
    A1 --> A3
    A1 --> A4
    A4 --> B1
    
    B1 --> B2
    B2 --> B3
    B3 --> B4
    
    B4 --> C1
    B4 --> C2
    B4 --> C3
    
    C1 --> D1
    C1 --> D2
    C2 --> D1
    C2 --> D2
    C3 --> D3
    C3 --> D4
```

### MSA Configuration

MSA directories are configured as lists of dictionaries specifying search paths:

```python
protein_msa_dirs = [
    {
        "dir": "/path/to/protein/msas",
        "extension": ".a3m.gz", 
        "directory_depth": 2
    }
]

rna_msa_dirs = [
    {
        "dir": "/path/to/rna/msas",
        "extension": ".afa",
        "directory_depth": 0  
    }
]
```

### Template Structure Format

The `RF2AATemplate` dataclass encapsulates template information:
- `xyz`: Template coordinates `[1, n_templates × n_atoms, 14, 3]`
- `mask`: Atom presence mask `[1, n_templates × n_atoms, 14]` 
- `qmap`: Query-template alignment mapping `[1, n_templates × n_atoms, 2]`
- `f0d`: Template metadata including sequence similarity `[1, n_templates, 8]`
- `seq`: Template sequence tokens `[1, n_templates × n_atoms]`
- `ids`: Template PDB and chain identifiers

**Sources:** [src/atomworks/ml/transforms/msa/msa.py:1-100](), [src/atomworks/ml/transforms/template.py:42-213](), [tests/ml/transforms/msa/test_featurize_msa.py:46-120]()

---