# Data Processing Pipeline

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [README.md](README.md)
- [openfold/data/data_pipeline.py](openfold/data/data_pipeline.py)
- [openfold/data/data_transforms.py](openfold/data/data_transforms.py)
- [openfold/data/input_pipeline.py](openfold/data/input_pipeline.py)
- [openfold/data/templates.py](openfold/data/templates.py)
- [run_pretrained_openfold.py](run_pretrained_openfold.py)
- [scripts/generate_mmcif_cache.py](scripts/generate_mmcif_cache.py)
- [scripts/precompute_alignments.py](scripts/precompute_alignments.py)
- [scripts/utils.py](scripts/utils.py)
- [tests/test_data/features.pkl](tests/test_data/features.pkl)
- [tests/test_data_transforms.py](tests/test_data_transforms.py)

</details>



The data processing pipeline transforms raw protein data (sequences, structures, MSAs) into the standardized tensor format required by the AlphaFold model. The pipeline handles both monomer and multimer predictions, supports training and inference modes, and manages the complex workflow of MSA generation, template search, and feature extraction.

## System Architecture

The data processing system consists of three major subsystems that work sequentially:

**High-level Data Processing Architecture**
```mermaid
graph TB
    subgraph "1. Data Acquisition & MSA Generation"
        RAW["Raw Input<br/>FASTA/mmCIF/PDB"]
        ALIGN["AlignmentRunner<br/>MSA generation"]
        TOOLS["External Tools<br/>jackhmmer, hhblits,<br/>hhsearch, hmmsearch"]
        MSA_FILES["Alignment Files<br/>.sto, .a3m, .hhr"]
    end
    
    subgraph "2. Feature Extraction"
        DATAPIPE["DataPipeline /<br/>DataPipelineMultimer"]
        PARSERS["Parsers<br/>parse_fasta, parse_a3m,<br/>parse_stockholm, parse_hhr"]
        SEQ_FEAT["make_sequence_features"]
        MSA_FEAT["make_msa_features"]
        TMPL_FEAT["make_template_features"]
        FEATURE_DICT["FeatureDict<br/>numpy arrays"]
    end
    
    subgraph "3. Feature Transformation"
        FEAT_PIPE["FeaturePipeline"]
        INPUT_PIPE["input_pipeline functions<br/>nonensembled_transform_fns<br/>ensembled_transform_fns"]
        TRANSFORMS["data_transforms module<br/>correct_msa_restypes<br/>sample_msa<br/>make_masked_msa<br/>crop_templates"]
        FINAL_FEAT["Model Input<br/>torch tensors"]
    end
    
    RAW --> ALIGN
    ALIGN --> TOOLS
    TOOLS --> MSA_FILES
    
    RAW --> DATAPIPE
    MSA_FILES --> DATAPIPE
    DATAPIPE --> PARSERS
    PARSERS --> SEQ_FEAT
    PARSERS --> MSA_FEAT
    PARSERS --> TMPL_FEAT
    SEQ_FEAT --> FEATURE_DICT
    MSA_FEAT --> FEATURE_DICT
    TMPL_FEAT --> FEATURE_DICT
    
    FEATURE_DICT --> FEAT_PIPE
    FEAT_PIPE --> INPUT_PIPE
    INPUT_PIPE --> TRANSFORMS
    TRANSFORMS --> FINAL_FEAT
```

Sources:
- [openfold/data/data_pipeline.py:334-475]()
- [openfold/data/data_pipeline.py:706-914]()
- [openfold/data/feature_pipeline.py:1-153]()
- [run_pretrained_openfold.py:63-175]()

## Key Components

The pipeline is organized into several specialized components, each handling a specific aspect of data processing:

| Component | Purpose | Key Classes/Functions | Details |
|-----------|---------|----------------------|---------|
| **MSA Generation** | Generate multiple sequence alignments | `AlignmentRunner`<br/>`Jackhmmer`, `HHBlits` | See [MSA and Template Processing](#6.3) |
| **Data Pipeline** | Convert raw data to FeatureDict | `DataPipeline`<br/>`DataPipelineMultimer` | See [Data Pipeline and Feature Generation](#6.1) |
| **Feature Pipeline** | Apply transforms to features | `FeaturePipeline`<br/>`np_example_to_features` | See [Data Pipeline and Feature Generation](#6.1) |
| **Data Transforms** | Augmentation and normalization | `data_transforms` module<br/>`data_transforms_multimer` module | See [Data Transforms and Augmentation](#6.2) |
| **Template Processing** | Search and featurize templates | `HhsearchHitFeaturizer`<br/>`HmmsearchHitFeaturizer` | See [MSA and Template Processing](#6.3) |
| **Multimer Processing** | Handle multi-chain proteins | `msa_pairing` module<br/>`feature_processing_multimer` module | See [Multimer-Specific Processing](#6.4) |

**Core Classes and Their Relationships**
```mermaid
classDiagram
    class AlignmentRunner {
        +jackhmmer_uniref90_runner
        +hhblits_bfd_unirefclust_runner
        +template_searcher
        +run(fasta_path, output_dir)
    }
    
    class DataPipeline {
        +template_featurizer
        +process_fasta(fasta_path, alignment_dir)
        +process_mmcif(mmcif_object, alignment_dir)
        +_parse_msa_data(alignment_dir)
        +_parse_template_hit_files(alignment_dir)
        +_process_msa_feats(alignment_dir)
    }
    
    class DataPipelineMultimer {
        +monomer_data_pipeline
        +process_fasta(fasta_path, alignment_dir)
    }
    
    class FeaturePipeline {
        +config
        +process_features(raw_features, mode, is_multimer)
    }
    
    class TemplateHitFeaturizer {
        <<abstract>>
        +get_templates(query_sequence, hits)
    }
    
    class HhsearchHitFeaturizer {
        +mmcif_dir
        +kalign_binary_path
        +get_templates(query_sequence, hits)
    }
    
    class HmmsearchHitFeaturizer {
        +mmcif_dir
        +kalign_binary_path
        +get_templates(query_sequence, hits)
    }
    
    AlignmentRunner --> DataPipeline : generates MSAs for
    DataPipeline --> FeaturePipeline : outputs FeatureDict to
    DataPipelineMultimer --> DataPipeline : uses
    DataPipeline --> TemplateHitFeaturizer : uses
    TemplateHitFeaturizer <|-- HhsearchHitFeaturizer
    TemplateHitFeaturizer <|-- HmmsearchHitFeaturizer
```

Sources:
- [openfold/data/data_pipeline.py:334-475]()
- [openfold/data/data_pipeline.py:706-914]()
- [openfold/data/data_pipeline.py:938-1138]()
- [openfold/data/feature_pipeline.py:132-153]()
- [openfold/data/templates.py:738-1068]()

## Data Flow

The pipeline processes data through several distinct stages, each transforming the representation progressively:

**End-to-End Data Flow**
```mermaid
graph TB
    subgraph "Stage 1: Input Parsing"
        FASTA["FASTA file"]
        PARSE["parse_fasta"]
        SEQ["sequence string"]
    end
    
    subgraph "Stage 2: Alignment Generation"
        AR["AlignmentRunner.run"]
        JACK["jackhmmer.query"]
        HHB["hhblits.query"]
        HHS["hhsearch.query"]
        ALIGN_DIR["alignment_dir/<br/>uniref90_hits.sto<br/>mgnify_hits.sto<br/>bfd_hits.a3m<br/>output.hhr"]
    end
    
    subgraph "Stage 3: Feature Extraction"
        DP_PROC["DataPipeline.process_fasta"]
        PARSE_MSA["_parse_msa_data"]
        PARSE_TMPL["_parse_template_hit_files"]
        MAKE_SEQ["make_sequence_features"]
        MAKE_MSA["make_msa_features"]
        MAKE_TMPL["make_template_features"]
        FD["FeatureDict<br/>{aatype, msa,<br/>template_aatype, ...}"]
    end
    
    subgraph "Stage 4: Feature Transformation"
        FP["FeaturePipeline.process_features"]
        CAST["cast_to_64bit_ints"]
        CORRECT["correct_msa_restypes"]
        SAMPLE["sample_msa"]
        MASK["make_masked_msa"]
        CLUSTER["nearest_neighbor_clusters"]
        CROP["random_crop_to_size"]
        FINAL["torch.Tensor features"]
    end
    
    FASTA --> PARSE
    PARSE --> SEQ
    
    SEQ --> AR
    AR --> JACK
    AR --> HHB
    AR --> HHS
    JACK --> ALIGN_DIR
    HHB --> ALIGN_DIR
    HHS --> ALIGN_DIR
    
    FASTA --> DP_PROC
    ALIGN_DIR --> DP_PROC
    DP_PROC --> PARSE_MSA
    DP_PROC --> PARSE_TMPL
    DP_PROC --> MAKE_SEQ
    PARSE_MSA --> MAKE_MSA
    PARSE_TMPL --> MAKE_TMPL
    MAKE_SEQ --> FD
    MAKE_MSA --> FD
    MAKE_TMPL --> FD
    
    FD --> FP
    FP --> CAST
    CAST --> CORRECT
    CORRECT --> SAMPLE
    SAMPLE --> MASK
    MASK --> CLUSTER
    CLUSTER --> CROP
    CROP --> FINAL
```

### FeatureDict Structure

The `FeatureDict` is the intermediate representation between raw data and model input. It contains numpy arrays with standardized shapes:

| Feature Name | Shape | Description |
|--------------|-------|-------------|
| `aatype` | `[N_res, 21]` or `[N_res]` | One-hot or integer amino acid types |
| `residue_index` | `[N_res]` | Residue indices (0 to N_res-1) |
| `msa` | `[N_seq, N_res]` | MSA sequences (integer encoded) |
| `deletion_matrix_int` | `[N_seq, N_res]` | Deletion counts in MSA |
| `template_aatype` | `[N_templ, N_res, 22]` | Template amino acid types |
| `template_all_atom_positions` | `[N_templ, N_res, 37, 3]` | Template atom coordinates |
| `template_all_atom_mask` | `[N_templ, N_res, 37]` | Template atom masks |

Sources:
- [run_pretrained_openfold.py:63-175]()
- [openfold/data/data_pipeline.py:864-914]()
- [openfold/data/data_pipeline.py:111-130]()
- [openfold/data/data_pipeline.py:224-261]()
- [openfold/data/feature_pipeline.py:79-128]()

## MSA and Template Processing

Multiple Sequence Alignments (MSAs) and structural templates are critical components of AlphaFold's accuracy. OpenFold provides robust processing for both:

### MSA Processing

MSAs are generated using tools like Jackhmmer and HHblits, then processed to extract evolutionarily relevant information:

```mermaid
flowchart TD
    subgraph "MSA Generation"
        FASTA["FASTA sequence"]
        Jackhmmer["Jackhmmer search"]
        HHblits["HHblits search"]
        MSA_Files["MSA files (.sto, .a3m)"]
    end
    
    subgraph "MSA Processing"
        ParseMSA["Parse MSA files"]
        DeduplicateMSA["Deduplicate sequences"]
        RemoveEmpty["Remove empty columns"]
        ExtractFeatures["Extract MSA features"]
    end
    
    subgraph "MSA Transformations"
        SampleMSA["Sample MSA sequences"]
        MaskedMSA["Make masked MSA"]
        MSACluster["Nearest neighbor clusters"]
        CreateFeat["Create MSA features"]
    end
    
    FASTA --> Jackhmmer
    FASTA --> HHblits
    Jackhmmer --> MSA_Files
    HHblits --> MSA_Files
    
    MSA_Files --> ParseMSA
    ParseMSA --> DeduplicateMSA
    DeduplicateMSA --> RemoveEmpty
    RemoveEmpty --> ExtractFeatures
    
    ExtractFeatures --> SampleMSA
    SampleMSA --> MaskedMSA
    MaskedMSA --> MSACluster
    MSACluster --> CreateFeat
```

Sources:
- [openfold/data/data_pipeline.py:477-562](openfold/data/data_pipeline.py)
- [openfold/data/data_pipeline.py:224-259](openfold/data/data_pipeline.py)
- [openfold/data/data_transforms_multimer.py:75-125](openfold/data/data_transforms_multimer.py)
- [openfold/data/data_transforms_multimer.py:129-183](openfold/data/data_transforms_multimer.py)
- [openfold/data/data_transforms_multimer.py:257-294](openfold/data/data_transforms_multimer.py)

Key MSA processing steps include:
1. Sequence alignment using external tools
2. Parsing alignment files (.sto, .a3m)
3. Deduplication and filtering
4. Feature extraction (insertions, deletions, conservation)
5. Sampling and cropping for fixed-size inputs
6. BERT-style masking for masked MSA prediction

### Template Processing

Template structures are found and processed to provide structural priors:

```mermaid
flowchart TD
    subgraph "Template Search"
        MSA["MSA data"]
        HHsearch["HHsearch (monomer)"]
        HMMsearch["HMMsearch (multimer)"]
        Hits["Template hits"]
    end
    
    subgraph "Template Processing"
        FilterHits["Filter by date/quality"]
        RankHits["Rank by E-value"]
        SubsampleHits["Subsample hits"]
        AlignHits["Align to query"]
    end
    
    subgraph "Template Featurization"
        FeaturizeTemplate["Template featurization"]
        BuildFeatures["Build template features"]
        CropTemplates["Crop templates"]
    end
    
    MSA --> HHsearch
    MSA --> HMMsearch
    HHsearch --> Hits
    HMMsearch --> Hits
    
    Hits --> FilterHits
    FilterHits --> RankHits
    RankHits --> SubsampleHits
    SubsampleHits --> AlignHits
    
    AlignHits --> FeaturizeTemplate
    FeaturizeTemplate --> BuildFeatures
    BuildFeatures --> CropTemplates
```

Sources:
- [openfold/data/data_pipeline.py:500-518](openfold/data/data_pipeline.py)
- [openfold/data/data_pipeline.py:46-63](openfold/data/data_pipeline.py)
- [openfold/data/data_pipeline.py:159-167](openfold/data/data_pipeline.py)
- [openfold/data/data_pipeline.py:405-413](openfold/data/data_pipeline.py)

Template processing includes:
1. Finding template structures using HHsearch (monomer) or HMMsearch (multimer)
2. Filtering by release date and quality metrics
3. Ranking and selecting the top templates
4. Aligning templates to the target sequence
5. Extracting template features (atom positions, amino acid types, masks)

## Multimer Data Processing

For multi-chain proteins (multimers), OpenFold implements specialized processing:

```mermaid
flowchart TD
    subgraph "Chain Processing"
        ReadChains["Read individual chains"]
        ProcessChains["Process each chain"]
        ChainFeatures["Chain features"]
    end
    
    subgraph "MSA Pairing"
        CreatePaired["Create paired features"]
        DeduplicateUnpaired["Deduplicate unpaired sequences"]
        PairRows["Reorder paired rows"]
    end
    
    subgraph "Feature Merging"
        MergeHomomers["Merge homomers"]
        MergeFeatures["Merge chain features"]
        ConcatFeatures["Concatenate paired/unpaired features"]
    end
    
    subgraph "Post-Processing"
        CorrectFeats["Correct post-merged features"]
        CropChains["Crop chains"]
        FilterFeatures["Filter features"]
    end
    
    ReadChains --> ProcessChains
    ProcessChains --> ChainFeatures
    
    ChainFeatures --> CreatePaired
    CreatePaired --> DeduplicateUnpaired
    DeduplicateUnpaired --> PairRows
    
    PairRows --> MergeHomomers
    MergeHomomers --> MergeFeatures
    MergeFeatures --> ConcatFeatures
    
    ConcatFeatures --> CorrectFeats
    CorrectFeats --> CropChains
    CropChains --> FilterFeatures
```

Sources:
- [openfold/data/msa_pairing.py:56-88](openfold/data/msa_pairing.py)
- [openfold/data/msa_pairing.py:181-232](openfold/data/msa_pairing.py)
- [openfold/data/msa_pairing.py:356-457](openfold/data/msa_pairing.py)
- [openfold/data/feature_processing_multimer.py:50-83](openfold/data/feature_processing_multimer.py)
- [openfold/data/feature_processing_multimer.py:87-116](openfold/data/feature_processing_multimer.py)

Key multimer processing steps include:
1. Processing each chain individually
2. Pairing MSA sequences across chains based on species
3. Merging identical chains (homomers) efficiently
4. Combining features from all chains
5. Special handling for template features across chains
6. Cropping the combined features to manageable sizes

## Data Transformations

The data undergoes various transformations to prepare it for model input:

### Non-ensembled Transforms

Applied once to the input data:
- Converting data types (e.g., 64-bit integers)
- Creating MSA profiles
- Creating target features
- Making atom masks

### Ensembled Transforms

Applied multiple times for recycling:
- MSA sampling
- MSA masking for BERT-style training
- MSA clustering
- Cropping to fixed size

These transformations are implemented in `data_transforms.py` and `data_transforms_multimer.py`.

Sources:
- [openfold/data/input_pipeline_multimer.py:36-45](openfold/data/input_pipeline_multimer.py)
- [openfold/data/input_pipeline_multimer.py:48-113](openfold/data/input_pipeline_multimer.py)
- [openfold/data/data_transforms_multimer.py:75-125](openfold/data/data_transforms_multimer.py)
- [openfold/data/data_transforms_multimer.py:257-294](openfold/data/data_transforms_multimer.py)

## Training Data Handling

For training, the pipeline includes additional components for data filtering, batching, and augmentation:

### Filtering

Training data undergoes both deterministic and stochastic filtering:

```python
# Deterministic filters
resolution_filter(resolution, max_resolution)
aa_count_filter(seqs, max_single_aa_prop)

# Stochastic filters
# Prefer diverse sequences (inversely proportional to cluster size)
# Prefer medium-length chains
```

### Batching and Recycling

The `OpenFoldDataLoader` handles batching and adds batch properties like recycling iterations:

```python
# Add number of recycling iterations
recycling_probs = [1. / (max_iters + 1) for _ in range(max_iters + 1)]
# Or use the maximum number of recycling iterations by default
recycling_probs = [0. for _ in range(max_iters + 1)]
recycling_probs[-1] = 1.
```

Sources:
- [openfold/data/data_modules.py:507-532](openfold/data/data_modules.py)
- [openfold/data/data_modules.py:560-595](openfold/data/data_modules.py)
- [openfold/data/data_modules.py:708-713](openfold/data/data_modules.py)
- [openfold/data/data_modules.py:762-845](openfold/data/data_modules.py)

## Summary

The OpenFold data processing pipeline is a sophisticated system that:
1. Loads protein data from various formats
2. Generates and processes MSAs and templates
3. Extracts and transforms features for model input
4. Handles both monomer and multimer proteins
5. Provides specialized functionality for training data

This pipeline is critical for achieving high-quality protein structure predictions, as it prepares the complex evolutionary and structural information needed by the model.

Sources:
- [openfold/data/data_pipeline.py](openfold/data/data_pipeline.py)
- [openfold/data/feature_pipeline.py](openfold/data/feature_pipeline.py)
- [openfold/data/data_modules.py](openfold/data/data_modules.py)

---