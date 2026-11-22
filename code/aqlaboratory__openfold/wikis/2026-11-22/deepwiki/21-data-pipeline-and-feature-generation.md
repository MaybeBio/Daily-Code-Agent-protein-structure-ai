# Data Pipeline and Feature Generation

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [README.md](README.md)
- [openfold/data/data_pipeline.py](openfold/data/data_pipeline.py)
- [openfold/data/templates.py](openfold/data/templates.py)
- [run_pretrained_openfold.py](run_pretrained_openfold.py)
- [scripts/generate_mmcif_cache.py](scripts/generate_mmcif_cache.py)
- [scripts/precompute_alignments.py](scripts/precompute_alignments.py)
- [scripts/utils.py](scripts/utils.py)

</details>



## Purpose and Scope

This page documents the data processing pipeline that converts raw biological inputs (FASTA sequences, mmCIF/PDB structures) into feature dictionaries suitable for model inference and training. The pipeline orchestrates MSA generation, template search, and feature extraction through the `DataPipeline` and `AlignmentRunner` classes.

For information about data transformations applied after feature generation (sampling, masking, cropping), see [Data Transforms and Augmentation](#6.2). For details on MSA generation tools and template search, see [MSA and Template Processing](#6.3). For multimer-specific processing including chain pairing, see [Multimer-Specific Processing](#6.4).

---

## System Overview

The data pipeline consists of three major stages:

```mermaid
graph LR
    subgraph "Stage 1: Alignment Generation"
        FASTA["FASTA Input"]
        AR["AlignmentRunner"]
        MSA_FILES["MSA Files<br/>(*.sto, *.a3m)"]
        TEMPLATE_FILES["Template Files<br/>(*.hhr, hmm_output.sto)"]
        
        FASTA --> AR
        AR --> MSA_FILES
        AR --> TEMPLATE_FILES
    end
    
    subgraph "Stage 2: Feature Extraction"
        DP["DataPipeline"]
        PARSERS["Parsers<br/>parse_stockholm<br/>parse_a3m<br/>parse_hhr"]
        TF["TemplateFeaturizer"]
        
        MSA_FILES --> PARSERS
        TEMPLATE_FILES --> PARSERS
        PARSERS --> DP
        TF --> DP
    end
    
    subgraph "Stage 3: Feature Dict Assembly"
        SEQ_FEAT["Sequence Features<br/>aatype, residue_index"]
        MSA_FEAT["MSA Features<br/>msa, deletion_matrix"]
        TEMPL_FEAT["Template Features<br/>positions, aatype"]
        EMBED_FEAT["Embeddings<br/>seq_embedding (optional)"]
        
        DP --> SEQ_FEAT
        DP --> MSA_FEAT
        DP --> TEMPL_FEAT
        DP --> EMBED_FEAT
    end
    
    FINAL["FeatureDict<br/>Ready for FeaturePipeline"]
    
    SEQ_FEAT --> FINAL
    MSA_FEAT --> FINAL
    TEMPL_FEAT --> FINAL
    EMBED_FEAT --> FINAL
```

**Sources**: [openfold/data/data_pipeline.py:1-1161](), [run_pretrained_openfold.py:63-170]()

---

## DataPipeline Class

The `DataPipeline` class is the central orchestrator that converts alignment outputs and structural data into standardized feature dictionaries.

### Class Structure

```mermaid
classDiagram
    class DataPipeline {
        +TemplateHitFeaturizer template_featurizer
        +process_fasta(fasta_path, alignment_dir) FeatureDict
        +process_mmcif(mmcif, alignment_dir) FeatureDict
        +process_multiseq_fasta(fasta_path, super_alignment_dir) FeatureDict
        -_parse_msa_data(alignment_dir) Mapping
        -_parse_template_hit_files(alignment_dir) Mapping
        -_process_msa_feats(alignment_dir) FeatureDict
        -_process_seqemb_features(alignment_dir) FeatureDict
        -_get_msas(alignment_dir) List[Msa]
    }
    
    class DataPipelineMultimer {
        +DataPipeline monomer_data_pipeline
        +process_fasta(fasta_path, alignment_dir) FeatureDict
    }
    
    class TemplateHitFeaturizer {
        <<interface>>
        +get_templates(query_sequence, hits) TemplateSearchResult
    }
    
    class HhsearchHitFeaturizer {
        +str mmcif_dir
        +datetime max_template_date
        +int max_hits
        +get_templates() TemplateSearchResult
    }
    
    class HmmsearchHitFeaturizer {
        +str mmcif_dir
        +datetime max_template_date
        +int max_hits
        +get_templates() TemplateSearchResult
    }
    
    class CustomHitFeaturizer {
        +str mmcif_dir
        +str kalign_binary_path
        +get_templates() TemplateSearchResult
    }
    
    DataPipeline --> TemplateHitFeaturizer
    DataPipelineMultimer --> DataPipeline
    TemplateHitFeaturizer <|-- HhsearchHitFeaturizer
    TemplateHitFeaturizer <|-- HmmsearchHitFeaturizer
    TemplateHitFeaturizer <|-- CustomHitFeaturizer
```

**Sources**: [openfold/data/data_pipeline.py:706-915](), [openfold/data/data_pipeline.py:916-1161](), [openfold/data/templates.py:930-1145]()

### Main Processing Methods

The `DataPipeline` class provides three main entry points:

| Method | Input | Purpose | Used For |
|--------|-------|---------|----------|
| `process_fasta()` | FASTA file + alignment directory | Process single-chain sequences | Monomer inference, SoloSeq mode |
| `process_mmcif()` | mmCIF object + alignment directory | Process structure with alignments | Training on PDB structures |
| `process_multiseq_fasta()` | Multi-sequence FASTA + alignments | Process multiple chains | Legacy multi-chain (pre-multimer) |

**Sources**: [openfold/data/data_pipeline.py:864-914](), [openfold/data/data_pipeline.py:916-999](), [openfold/data/data_pipeline.py:1001-1046]()

---

## AlignmentRunner

The `AlignmentRunner` class orchestrates external bioinformatics tools to generate MSAs and template search results.

### Tool Configuration

```mermaid
graph TB
    subgraph "AlignmentRunner Configuration"
        AR["AlignmentRunner"]
        
        subgraph "MSA Search Tools"
            JACK_U90["jackhmmer_uniref90_runner<br/>Jackhmmer vs UniRef90"]
            JACK_MGN["jackhmmer_mgnify_runner<br/>Jackhmmer vs MGnify"]
            JACK_BFD["jackhmmer_small_bfd_runner<br/>Jackhmmer vs small BFD"]
            HHB["hhblits_bfd_unirefclust_runner<br/>HHBlits vs BFD+UniRef30/UniClust30"]
            JACK_UNI["jackhmmer_uniprot_runner<br/>Jackhmmer vs UniProt (multimer)"]
        end
        
        subgraph "Template Search"
            HHS["HHSearch<br/>vs PDB70"]
            HMS["Hmmsearch<br/>vs pdb_seqres"]
        end
        
        AR --> JACK_U90
        AR --> JACK_MGN
        AR --> JACK_BFD
        AR --> HHB
        AR --> JACK_UNI
        AR --> HHS
        AR --> HMS
    end
    
    subgraph "Output Files"
        U90_OUT["uniref90_hits.sto"]
        MGN_OUT["mgnify_hits.sto"]
        BFD_OUT["bfd_*_hits.a3m / small_bfd_hits.sto"]
        UNI_OUT["uniprot_hits.sto"]
        TEMPL_OUT["output.hhr / hmmsearch_output.sto"]
    end
    
    JACK_U90 --> U90_OUT
    JACK_MGN --> MGN_OUT
    JACK_BFD --> BFD_OUT
    HHB --> BFD_OUT
    JACK_UNI --> UNI_OUT
    HHS --> TEMPL_OUT
    HMS --> TEMPL_OUT
```

**Sources**: [openfold/data/data_pipeline.py:334-476]()

### AlignmentRunner.run() Workflow

The `run()` method executes the full alignment pipeline:

```mermaid
sequenceDiagram
    participant C as Caller
    participant AR as AlignmentRunner
    participant J as Jackhmmer
    participant H as HHBlits/HHSearch/Hmmsearch
    participant FS as File System
    
    C->>AR: run(fasta_path, output_dir)
    
    alt UniRef90 Search
        AR->>J: query(fasta_path, max_sto_sequences)
        J->>FS: Write uniref90_hits.sto
        
        alt Template Search Enabled
            AR->>AR: deduplicate_stockholm_msa()
            AR->>AR: remove_empty_columns_from_stockholm_msa()
            
            alt HHSearch (monomer)
                AR->>H: query(template_msa, output_dir)
                H->>FS: Write output.hhr
            else Hmmsearch (multimer)
                AR->>H: query(template_msa, output_dir)
                H->>FS: Write hmmsearch_output.sto
            end
        end
    end
    
    alt MGnify Search
        AR->>J: query(fasta_path, max_sto_sequences)
        J->>FS: Write mgnify_hits.sto
    end
    
    alt BFD Search
        alt use_small_bfd
            AR->>J: query(fasta_path)
            J->>FS: Write small_bfd_hits.sto
        else use_full_bfd
            AR->>H: query(fasta_path)
            H->>FS: Write bfd_uniref_hits.a3m / bfd_uniclust_hits.a3m
        end
    end
    
    alt UniProt Search (multimer only)
        AR->>J: query(fasta_path, max_sto_sequences)
        J->>FS: Write uniprot_hits.sto
    end
    
    AR->>C: Return (all files written)
```

**Sources**: [openfold/data/data_pipeline.py:477-563]()

### Integration with Inference

In the inference script, alignment generation is handled by `precompute_alignments()`:

```mermaid
graph TB
    FASTA["FASTA File(s)"]
    CHECK{"use_precomputed_<br/>alignments?"}
    
    subgraph "Alignment Generation"
        CREATE_AR["Create AlignmentRunner<br/>with tool binaries & DBs"]
        SEL_SEARCHER{"multimer<br/>mode?"}
        HMS_S["Hmmsearch<br/>template_searcher"]
        HHS_S["HHSearch<br/>template_searcher"]
        RUN["alignment_runner.run()<br/>fasta_path, output_dir"]
    end
    
    ALIGN_DIR["Alignment Directory<br/>per-sequence subdirs"]
    
    FASTA --> CHECK
    CHECK -->|No| CREATE_AR
    CREATE_AR --> SEL_SEARCHER
    SEL_SEARCHER -->|Yes| HMS_S
    SEL_SEARCHER -->|No| HHS_S
    HMS_S --> RUN
    HHS_S --> RUN
    RUN --> ALIGN_DIR
    CHECK -->|Yes| ALIGN_DIR
```

**Sources**: [run_pretrained_openfold.py:63-123]()

---

## Feature Generation Components

### Sequence Features

Basic sequence-level features are created by `make_sequence_features()`:

| Feature Name | Shape | Type | Description |
|--------------|-------|------|-------------|
| `aatype` | `(num_res, 21)` | `float32` | One-hot encoded amino acid types |
| `residue_index` | `(num_res,)` | `int32` | Residue indices (0 to num_res-1) |
| `seq_length` | `(num_res,)` | `int32` | Sequence length broadcast to all residues |
| `sequence` | `(1,)` | `object` | Raw amino acid sequence (encoded bytes) |
| `domain_name` | `(1,)` | `object` | Sequence description/ID (encoded bytes) |
| `between_segment_residues` | `(num_res,)` | `int32` | Zeros (used in multimer for chain breaks) |

**Sources**: [openfold/data/data_pipeline.py:111-130]()

### MSA Features

MSA features are constructed by `make_msa_features()` from parsed MSA objects:

```mermaid
graph LR
    subgraph "Input: List of Msa Objects"
        MSA1["Msa 1<br/>sequences<br/>deletion_matrix<br/>descriptions"]
        MSA2["Msa 2"]
        MSAN["Msa N"]
    end
    
    subgraph "Processing"
        DEDUP["Deduplicate sequences<br/>across all MSAs"]
        CONVERT["Convert to integer encoding<br/>HHBLITS_AA_TO_ID"]
        EXTRACT["Extract species identifiers<br/>from descriptions"]
    end
    
    subgraph "Output Features"
        MSA_FEAT["msa<br/>(num_alignments, num_res)<br/>int32"]
        DEL_FEAT["deletion_matrix_int<br/>(num_alignments, num_res)<br/>int32"]
        NUM_FEAT["num_alignments<br/>(num_res,)<br/>int32"]
        SPEC_FEAT["msa_species_identifiers<br/>(num_alignments,)<br/>object"]
    end
    
    MSA1 --> DEDUP
    MSA2 --> DEDUP
    MSAN --> DEDUP
    DEDUP --> CONVERT
    DEDUP --> EXTRACT
    CONVERT --> MSA_FEAT
    CONVERT --> DEL_FEAT
    CONVERT --> NUM_FEAT
    EXTRACT --> SPEC_FEAT
```

**Sources**: [openfold/data/data_pipeline.py:224-261]()

### Template Features

Template features are generated through a multi-step process involving alignment to query and extraction of structural information:

```mermaid
graph TB
    subgraph "Input"
        HITS["Template Hits<br/>from HHSearch/Hmmsearch"]
        QUERY["Query Sequence"]
    end
    
    subgraph "Template Featurizer"
        PREFILT["_prefilter_hit()<br/>Check date, align ratio<br/>duplicates, length"]
        PROCESS["_process_single_hit()<br/>Parse mmCIF<br/>Extract features"]
        
        subgraph "Feature Extraction"
            FIND["_find_template_in_pdb()<br/>Match template chain"]
            REALIGN["_realign_pdb_template_to_query()<br/>Align with Kalign"]
            EXTRACT["_extract_template_features()<br/>Map atoms to query indices"]
            CHECK["_check_residue_distances()<br/>Validate CA-CA distances"]
        end
    end
    
    subgraph "Output Features"
        T_AATYPE["template_aatype<br/>(num_templates, num_res, 22)<br/>float32"]
        T_POS["template_all_atom_positions<br/>(num_templates, num_res, 37, 3)<br/>float32"]
        T_MASK["template_all_atom_mask<br/>(num_templates, num_res, 37)<br/>float32"]
        T_SEQ["template_sequence<br/>(num_templates,)<br/>object"]
        T_DOMAIN["template_domain_names<br/>(num_templates,)<br/>object"]
        T_PROBS["template_sum_probs<br/>(num_templates, 1)<br/>float32"]
    end
    
    HITS --> PREFILT
    QUERY --> PREFILT
    PREFILT -->|valid| PROCESS
    PROCESS --> FIND
    FIND --> REALIGN
    REALIGN --> EXTRACT
    EXTRACT --> CHECK
    CHECK --> T_AATYPE
    CHECK --> T_POS
    CHECK --> T_MASK
    CHECK --> T_SEQ
    CHECK --> T_DOMAIN
    CHECK --> T_PROBS
```

**Sources**: [openfold/data/templates.py:826-930](), [openfold/data/templates.py:548-706](), [openfold/data/templates.py:292-364]()

### Template Feature Details

Templates contain structural information extracted from mmCIF files:

| Feature Name | Shape | Type | Description |
|--------------|-------|------|-------------|
| `template_aatype` | `(num_templates, num_res, 22)` | `float32` | One-hot amino acid types (HHBLITS encoding) |
| `template_all_atom_positions` | `(num_templates, num_res, 37, 3)` | `float32` | Atom37 coordinates, aligned to query |
| `template_all_atom_mask` | `(num_templates, num_res, 37)` | `float32` | Mask indicating which atoms are present |
| `template_domain_names` | `(num_templates,)` | `object` | PDB_ID + chain ID (e.g., "4hhb_a") |
| `template_sequence` | `(num_templates,)` | `object` | Aligned template sequence |
| `template_sum_probs` | `(num_templates, 1)` | `float32` | HHSearch sum of probabilities score |

**Sources**: [openfold/data/templates.py:83-90](), [openfold/data/templates.py:93-108]()

### ESM-1b Embeddings (SoloSeq Mode)

When `seqemb_mode=True`, single-sequence embeddings replace MSA features:

```mermaid
graph LR
    subgraph "ESM-1b Embedding Generation"
        FASTA["FASTA File"]
        EMB_GEN["EmbeddingGenerator<br/>scripts/precompute_embeddings.py"]
        ESM["ESM-1b Model"]
        EMB_FILE["*.pt file<br/>representations[33]"]
    end
    
    subgraph "Feature Processing"
        LOAD["Load *.pt file"]
        EXTRACT["Extract layer 33<br/>representation"]
        DUMMY["Generate dummy MSA<br/>single sequence"]
    end
    
    subgraph "Output"
        SEQ_EMB["seq_embedding<br/>(num_res, 1280)<br/>float32"]
        MSA_DUMMY["msa (single-sequence)<br/>(1, num_res)<br/>int32"]
    end
    
    FASTA --> EMB_GEN
    EMB_GEN --> ESM
    ESM --> EMB_FILE
    EMB_FILE --> LOAD
    LOAD --> EXTRACT
    EXTRACT --> SEQ_EMB
    FASTA --> DUMMY
    DUMMY --> MSA_DUMMY
```

**Sources**: [openfold/data/data_pipeline.py:849-862](), [openfold/data/data_pipeline.py:284-294](), [run_pretrained_openfold.py:89-97]()

---

## Input Format Processing

### FASTA Processing

The `process_fasta()` method handles single-chain FASTA inputs:

```mermaid
sequenceDiagram
    participant C as Caller
    participant DP as DataPipeline
    participant P as Parsers
    participant TF as TemplateFeaturizer
    
    C->>DP: process_fasta(fasta_path, alignment_dir, seqemb_mode)
    DP->>P: parse_fasta(fasta_str)
    P-->>DP: input_sequence, description
    
    DP->>DP: _parse_template_hit_files(alignment_dir)
    DP->>DP: make_sequence_features(sequence, description, num_res)
    
    alt seqemb_mode
        DP->>DP: make_dummy_msa_feats(input_sequence)
        DP->>DP: _process_seqemb_features(alignment_dir)
        Note over DP: Load ESM-1b embeddings
    else normal mode
        DP->>DP: _process_msa_feats(alignment_dir, input_sequence)
        Note over DP: Parse MSA files
    end
    
    DP->>TF: get_templates(input_sequence, hits)
    TF-->>DP: template_features
    
    DP->>C: Return FeatureDict (sequence + MSA/embeddings + templates)
```

**Sources**: [openfold/data/data_pipeline.py:864-914]()

### mmCIF Processing

The `process_mmcif()` method processes structural data with alignments:

```mermaid
graph TB
    subgraph "Input"
        MMCIF["MmcifObject<br/>parsed structure"]
        CHAIN["chain_id<br/>(optional)"]
        ALIGN["alignment_dir"]
    end
    
    subgraph "Processing Steps"
        SELECT["Select chain<br/>or use single chain"]
        MMCIF_FEAT["make_mmcif_features()<br/>Extract structure features"]
        SEQ_EXTRACT["Extract input_sequence<br/>from chain_to_seqres"]
        MSA_PROC["_process_msa_feats()<br/>Parse MSA files"]
        TEMPL_PROC["_parse_template_hit_files()<br/>Parse template hits"]
    end
    
    subgraph "Output Features"
        BASE["Basic sequence features<br/>aatype, residue_index"]
        STRUCT["Structure features<br/>all_atom_positions<br/>all_atom_mask"]
        METADATA["Metadata<br/>resolution<br/>release_date<br/>is_distillation"]
        MSA_F["MSA features"]
        TEMPL_F["Template features"]
    end
    
    MMCIF --> SELECT
    CHAIN --> SELECT
    SELECT --> MMCIF_FEAT
    SELECT --> SEQ_EXTRACT
    MMCIF_FEAT --> BASE
    MMCIF_FEAT --> STRUCT
    MMCIF_FEAT --> METADATA
    ALIGN --> MSA_PROC
    SEQ_EXTRACT --> MSA_PROC
    ALIGN --> TEMPL_PROC
    MSA_PROC --> MSA_F
    TEMPL_PROC --> TEMPL_F
```

**Sources**: [openfold/data/data_pipeline.py:916-999](), [openfold/data/data_pipeline.py:133-166]()

### Custom Template Processing

For custom template inputs (using `--use_custom_template`), the pipeline uses `CustomHitFeaturizer`:

```mermaid
graph LR
    subgraph "Input"
        SEQ["Query Sequence"]
        MMCIF["Custom mmCIF File"]
        PDB_ID["PDB ID"]
        CHAIN_ID["Chain ID"]
    end
    
    subgraph "Processing"
        CREATE["make_sequence_features_with_custom_template()"]
        ALIGN["Align query to template<br/>with Kalign"]
        EXTRACT["get_custom_template_features()<br/>Extract atom positions"]
        DUMMY["Create single-sequence MSA"]
    end
    
    subgraph "Output"
        SEQ_FEAT["Sequence Features"]
        MSA_FEAT["MSA Features (single seq)"]
        TEMPL_FEAT["Template Features<br/>from custom structure"]
    end
    
    SEQ --> CREATE
    MMCIF --> CREATE
    PDB_ID --> CREATE
    CHAIN_ID --> CREATE
    CREATE --> ALIGN
    ALIGN --> EXTRACT
    CREATE --> DUMMY
    EXTRACT --> TEMPL_FEAT
    DUMMY --> MSA_FEAT
    CREATE --> SEQ_FEAT
```

**Sources**: [openfold/data/data_pipeline.py:297-331](), [openfold/data/templates.py:1051-1145](), [run_pretrained_openfold.py:210-217]()

---

## Feature Dictionary Structure

The complete `FeatureDict` output contains the following feature groups:

### Complete Feature Set

```mermaid
graph TB
    subgraph "FeatureDict"
        subgraph "Sequence Features"
            AATYPE["aatype<br/>(num_res, 21)"]
            RES_IDX["residue_index<br/>(num_res,)"]
            SEQ_LEN["seq_length<br/>(num_res,)"]
            SEQ["sequence<br/>(1,)"]
            DOMAIN["domain_name<br/>(1,)"]
            BETWEEN["between_segment_residues<br/>(num_res,)"]
        end
        
        subgraph "MSA Features"
            MSA["msa<br/>(num_alignments, num_res)"]
            DEL_MAT["deletion_matrix_int<br/>(num_alignments, num_res)"]
            NUM_ALIGN["num_alignments<br/>(num_res,)"]
            MSA_SPEC["msa_species_identifiers<br/>(num_alignments,)"]
        end
        
        subgraph "Template Features"
            T_AATYPE["template_aatype<br/>(num_templates, num_res, 22)"]
            T_POS["template_all_atom_positions<br/>(num_templates, num_res, 37, 3)"]
            T_MASK["template_all_atom_mask<br/>(num_templates, num_res, 37)"]
            T_SEQ["template_sequence<br/>(num_templates,)"]
            T_DOMAIN["template_domain_names<br/>(num_templates,)"]
            T_PROBS["template_sum_probs<br/>(num_templates, 1)"]
        end
        
        subgraph "Optional: Embeddings"
            SEQ_EMB["seq_embedding<br/>(num_res, 1280)"]
        end
        
        subgraph "Optional: Structure (Training)"
            ALL_ATOM["all_atom_positions<br/>(num_res, 37, 3)"]
            ALL_MASK["all_atom_mask<br/>(num_res, 37)"]
            RESOLUTION["resolution<br/>(1,)"]
            RELEASE["release_date<br/>(1,)"]
            IS_DISTILL["is_distillation<br/>(1,)"]
        end
    end
```

**Sources**: [openfold/data/data_pipeline.py:111-130](), [openfold/data/data_pipeline.py:224-261](), [openfold/data/templates.py:83-108](), [openfold/data/data_pipeline.py:133-166]()

### Feature Types by Use Case

| Use Case | Sequence | MSA | Templates | Embeddings | Structure |
|----------|----------|-----|-----------|------------|-----------|
| Standard Inference | ✓ | ✓ | ✓ | ✗ | ✗ |
| SoloSeq Inference | ✓ | ✓ (dummy) | ✓ | ✓ | ✗ |
| Custom Template | ✓ | ✓ (dummy) | ✓ | ✗ | ✗ |
| Training (mmCIF) | ✓ | ✓ | ✓ | ✗ | ✓ |
| Training (PDB) | ✓ | ✓ | ✓ | ✗ | ✓ |

---

## Monomer vs Multimer Pipeline

The pipeline has different implementations for monomer and multimer predictions:

```mermaid
graph TB
    subgraph "Monomer Pipeline"
        M_FASTA["Single-chain FASTA"]
        M_ALIGN["Per-sequence alignment<br/>directories"]
        M_DP["DataPipeline"]
        M_FEAT["FeatureDict<br/>single chain"]
    end
    
    subgraph "Multimer Pipeline"
        MM_FASTA["Multi-chain FASTA"]
        MM_ALIGN["Per-sequence alignment<br/>directories"]
        MM_DP["DataPipelineMultimer"]
        MM_MONO["monomer_data_pipeline<br/>DataPipeline"]
        MM_PROC["Process each chain"]
        MM_PAIR["Pair MSAs<br/>add_assembly_features()"]
        MM_FEAT["FeatureDict<br/>multiple chains"]
    end
    
    M_FASTA --> M_ALIGN
    M_ALIGN --> M_DP
    M_DP --> M_FEAT
    
    MM_FASTA --> MM_ALIGN
    MM_ALIGN --> MM_DP
    MM_DP --> MM_MONO
    MM_MONO --> MM_PROC
    MM_PROC --> MM_PAIR
    MM_PAIR --> MM_FEAT
```

**Sources**: [openfold/data/data_pipeline.py:706-915](), [openfold/data/data_pipeline.py:916-1161](), [run_pretrained_openfold.py:236-242]()

### Multimer-Specific Processing

The `DataPipelineMultimer` class extends the monomer pipeline:

1. **Per-Chain Processing**: Each chain is processed independently using `monomer_data_pipeline`
2. **Chain Feature Conversion**: `convert_monomer_features()` reshapes features for multimer models
3. **Assembly Features**: `add_assembly_features()` adds chain identity markers (`asym_id`, `sym_id`, `entity_id`)
4. **MSA Pairing**: Uses `pair_and_merge()` to create paired MSAs from UniProt hits

See [Multimer-Specific Processing](#6.4) for detailed information.

**Sources**: [openfold/data/data_pipeline.py:1048-1161](), [openfold/data/data_pipeline.py:600-624](), [openfold/data/data_pipeline.py:649-691]()

---

## Integration with Inference Script

The inference script (`run_pretrained_openfold.py`) orchestrates the data pipeline:

### Inference Workflow

```mermaid
sequenceDiagram
    participant Script as run_pretrained_openfold.py
    participant AR as AlignmentRunner
    participant DP as DataPipeline
    participant FP as FeaturePipeline
    participant Model as AlphaFold Model
    
    Script->>Script: Parse command-line args
    Script->>Script: Create DataPipeline with TemplateFeaturizer
    
    loop For each FASTA file
        Script->>AR: precompute_alignments(tags, seqs, alignment_dir)
        AR-->>Script: Alignments written to disk
        
        Script->>DP: generate_feature_dict(tags, seqs, alignment_dir)
        DP-->>Script: raw_feature_dict
        
        Script->>FP: process_features(feature_dict, mode='predict')
        FP-->>Script: processed_feature_dict (with recycling dims)
        
        Script->>Model: forward(processed_feature_dict)
        Model-->>Script: predictions
        
        Script->>Script: prep_output() -> Protein object
        Script->>Script: Write PDB/mmCIF + optional relaxation
    end
```

**Sources**: [run_pretrained_openfold.py:177-395]()

### Key Functions in Inference

| Function | Location | Purpose |
|----------|----------|---------|
| `precompute_alignments()` | [run_pretrained_openfold.py:63-123]() | Create or load MSA/template alignments |
| `generate_feature_dict()` | [run_pretrained_openfold.py:129-170]() | Call DataPipeline to create FeatureDict |
| `FeaturePipeline.process_features()` | Used via import | Apply data transforms and prepare for model |

---

## Parsing Infrastructure

The pipeline relies on specialized parsers for different file formats:

```mermaid
graph TB
    subgraph "Parser Functions"
        subgraph "MSA Parsers"
            STOCKHOLM["parse_stockholm()<br/>*.sto files"]
            A3M["parse_a3m()<br/>*.a3m files"]
        end
        
        subgraph "Template Parsers"
            HHR["parse_hhr()<br/>HHSearch output"]
            HMS["parse_hmmsearch_sto()<br/>Hmmsearch output"]
        end
        
        subgraph "Sequence Parsers"
            FASTA["parse_fasta()<br/>FASTA files"]
        end
        
        subgraph "Structure Parsers"
            MMCIF["mmcif_parsing.parse()<br/>mmCIF files"]
            PDB["protein.from_pdb_string()<br/>PDB files"]
        end
    end
    
    subgraph "Parsed Objects"
        MSA_OBJ["Msa<br/>sequences<br/>deletion_matrix<br/>descriptions"]
        HIT_OBJ["TemplateHit<br/>name, query, hit_sequence<br/>indices, sum_probs"]
        MMCIF_OBJ["MmcifObject<br/>chain_to_seqres<br/>header, structure"]
        PROT_OBJ["Protein<br/>aatype, atom_positions<br/>atom_mask, b_factors"]
    end
    
    STOCKHOLM --> MSA_OBJ
    A3M --> MSA_OBJ
    HHR --> HIT_OBJ
    HMS --> HIT_OBJ
    FASTA --> MSA_OBJ
    MMCIF --> MMCIF_OBJ
    PDB --> PROT_OBJ
```

**Sources**: [openfold/data/parsers.py:1-500](), [openfold/data/mmcif_parsing.py:1-500]()

---

## Helper Scripts

Several utility scripts support the data pipeline:

### precompute_alignments.py

Batch precomputation of alignments for datasets:

```mermaid
graph LR
    INPUT["Input Directory<br/>*.cif, *.fasta, *.core"]
    PARSE["Parse files<br/>extract sequences"]
    GROUP["Group by sequence<br/>deduplicate"]
    ALIGN["Run AlignmentRunner<br/>for each group"]
    OUTPUT["Output Directory<br/>per-chain subdirs"]
    
    INPUT --> PARSE
    PARSE --> GROUP
    GROUP --> ALIGN
    ALIGN --> OUTPUT
```

**Usage**: Precompute alignments for training datasets to avoid redundant alignment searches.

**Sources**: [scripts/precompute_alignments.py:1-268]()

### generate_mmcif_cache.py

Create metadata cache for mmCIF files:

```mermaid
graph LR
    MMCIF_DIR["mmCIF Directory"]
    PARSE["Parse all mmCIF files<br/>in parallel"]
    EXTRACT["Extract metadata<br/>release_date, chains<br/>sequences, resolution"]
    CACHE["JSON Cache File"]
    
    MMCIF_DIR --> PARSE
    PARSE --> EXTRACT
    EXTRACT --> CACHE
```

**Usage**: Speed up dataset filtering by caching mmCIF metadata without parsing full structures every time.

**Sources**: [scripts/generate_mmcif_cache.py:1-108]()

---

## Error Handling and Edge Cases

The data pipeline includes extensive error handling:

### Template Processing Errors

| Error Class | Cause | Handling |
|-------------|-------|----------|
| `DateError` | Template released after cutoff | Filtered in prefilter, logged |
| `AlignRatioError` | Insufficient alignment coverage | Filtered in prefilter, logged |
| `DuplicateError` | Template is subsequence of query | Filtered in prefilter, logged |
| `LengthError` | Template too short (< 10 residues) | Filtered in prefilter, logged |
| `SequenceNotInTemplateError` | Chain not found in mmCIF | Triggers realignment attempt |
| `QueryToTemplateAlignError` | Realignment failed or < 90% identity | Template skipped, warning logged |
| `NoAtomDataInTemplateError` | Missing atom coordinates | Template skipped, warning logged |
| `TemplateAtomMaskAllZerosError` | All atoms masked | Template skipped, warning logged |

**Sources**: [openfold/data/templates.py:62-81](), [openfold/data/templates.py:220-289](), [openfold/data/templates.py:780-816]()

### Empty MSA Handling

When no MSA files are found, the pipeline creates a dummy single-sequence MSA:

```python
# If no MSAs found and input_sequence provided
msa_data["dummy"] = make_dummy_msa_obj(input_sequence)
```

**Sources**: [openfold/data/data_pipeline.py:813-830](), [openfold/data/data_pipeline.py:284-294]()

---

## Performance Considerations

### MSA Size Limits

The `AlignmentRunner` accepts parameters to limit MSA sizes:

- `uniref_max_hits`: Default 10,000 sequences
- `mgnify_max_hits`: Default 5,000 sequences  
- `uniprot_max_hits`: Default 50,000 sequences (multimer)

These limits prevent excessive MSA sizes that would slow down downstream processing.

**Sources**: [openfold/data/data_pipeline.py:349-351](), [openfold/data/data_pipeline.py:413-415]()

### Parallelization

The `AlignmentRunner` uses the `no_cpus` parameter to parallelize external tool execution (jackhmmer, hhblits). The `precompute_alignments.py` script further parallelizes across multiple sequences using threading.

**Sources**: [openfold/data/data_pipeline.py:418-420](), [scripts/precompute_alignments.py:223-231]()

### File Caching

The template extraction system uses `functools.lru_cache` on file reading operations to avoid redundant disk I/O when multiple hits reference the same mmCIF file:

```python
@functools.lru_cache(16, typed=False)
def _read_file(path):
    with open(path, 'r') as f:
        file_data = f.read()
    return file_data
```

**Sources**: [openfold/data/templates.py:818-823]()

---