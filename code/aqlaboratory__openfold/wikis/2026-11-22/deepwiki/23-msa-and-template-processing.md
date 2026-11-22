# MSA and Template Processing

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

This document details how OpenFold processes Multiple Sequence Alignments (MSAs) and template structures, which are critical inputs for accurate protein structure prediction. It covers the tools used to generate MSAs and find templates, the transformations applied to prepare this data for the model, and how these components integrate into the overall data pipeline. For information about how this data is used in the core model architecture, see [Model Architecture](#5).

## Overview

Protein structure prediction in OpenFold depends on two key sources of evolutionary information:

1. **Multiple Sequence Alignments (MSAs)**: Collections of related protein sequences that reveal patterns of conservation and covariation, highlighting which amino acids are structurally or functionally important.

2. **Template Structures**: Previously determined 3D structures of proteins with sequence similarity to the query protein, providing structural priors.

The processing of these information sources involves several sequential steps, coordinated by the `AlignmentRunner` and `DataPipeline` classes:

**MSA and Template Processing Pipeline**

```mermaid
flowchart TD
    subgraph "Input"
        fasta["FASTA File"]
    end

    subgraph "AlignmentRunner"
        runner["AlignmentRunner.run()"]
        jack_uni["jackhmmer_uniref90_runner"]
        jack_mgn["jackhmmer_mgnify_runner"]
        jack_bfd["jackhmmer_small_bfd_runner"]
        hhb["hhblits_bfd_unirefclust_runner"]
        jack_uniprot["jackhmmer_uniprot_runner"]
        tsearch["template_searcher<br/>(HHSearch or Hmmsearch)"]
    end

    subgraph "Template Featurizers"
        hhsearch_feat["HhsearchHitFeaturizer<br/>(monomer)"]
        hmmsearch_feat["HmmsearchHitFeaturizer<br/>(multimer)"]
        custom_feat["CustomHitFeaturizer<br/>(custom templates)"]
    end

    subgraph "Output"
        msa_files["MSA Files<br/>(uniref90_hits.sto,<br/>mgnify_hits.sto,<br/>bfd_*.a3m)"]
        template_files["Template Hits<br/>(output.hhr or<br/>hmm_output.sto)"]
    end

    subgraph "DataPipeline"
        dp["DataPipeline.process_fasta()"]
        parse_msa["_parse_msa_data()"]
        parse_tmpl["_parse_template_hit_files()"]
        make_msa["make_msa_features()"]
        make_tmpl["make_template_features()"]
    end

    fasta --> runner
    runner --> jack_uni
    runner --> jack_mgn
    runner --> jack_bfd
    runner --> hhb
    runner --> jack_uniprot
    runner --> tsearch
    
    jack_uni --> msa_files
    jack_mgn --> msa_files
    jack_bfd --> msa_files
    hhb --> msa_files
    jack_uniprot --> msa_files
    
    tsearch --> template_files
    tsearch -.-> hhsearch_feat
    tsearch -.-> hmmsearch_feat
    
    msa_files --> dp
    template_files --> dp
    dp --> parse_msa
    dp --> parse_tmpl
    parse_msa --> make_msa
    parse_tmpl --> make_tmpl
    make_tmpl -.-> hhsearch_feat
    make_tmpl -.-> hmmsearch_feat
    make_tmpl -.-> custom_feat
```

Sources: [openfold/data/data_pipeline.py:334-563](), [openfold/data/data_pipeline.py:706-914](), [openfold/data/templates.py:228-235](), [openfold/data/templates.py:930-1011](), [openfold/data/templates.py:1014-1096](), [run_pretrained_openfold.py:63-123]()

## MSA Generation and Processing

### The AlignmentRunner Class

MSA generation is coordinated by the `AlignmentRunner` class, which manages multiple search tools and databases. The runner is configured based on the available databases and whether the prediction is for monomer or multimer mode.

**AlignmentRunner Class Structure**

```mermaid
classDiagram
    class AlignmentRunner {
        +jackhmmer_uniref90_runner: Jackhmmer
        +jackhmmer_mgnify_runner: Jackhmmer
        +jackhmmer_small_bfd_runner: Jackhmmer
        +hhblits_bfd_unirefclust_runner: HHBlits
        +jackhmmer_uniprot_runner: Jackhmmer
        +template_searcher: TemplateSearcher
        +use_small_bfd: bool
        +uniref_max_hits: int
        +mgnify_max_hits: int
        +uniprot_max_hits: int
        +run(fasta_path, output_dir)
    }
    
    class Jackhmmer {
        +binary_path: str
        +database_path: str
        +n_cpu: int
        +query(fasta_path)
    }
    
    class HHBlits {
        +binary_path: str
        +databases: List[str]
        +n_cpu: int
        +query(fasta_path)
    }
    
    class HHSearch {
        +binary_path: str
        +databases: List[str]
        +input_format: str
        +query(msa_sto, output_dir)
    }
    
    class Hmmsearch {
        +binary_path: str
        +hmmbuild_binary_path: str
        +database_path: str
        +query(fasta_path, output_dir)
    }
    
    AlignmentRunner --> Jackhmmer : uses for UniRef90, MGnify, BFD, UniProt
    AlignmentRunner --> HHBlits : uses for BFD+UniRef30+UniClust30
    AlignmentRunner --> HHSearch : template search (monomer)
    AlignmentRunner --> Hmmsearch : template search (multimer)
```

Sources: [openfold/data/data_pipeline.py:334-476](), [openfold/data/data_pipeline.py:477-562](), [openfold/data/tools/hhsearch.py](), [openfold/data/tools/hmmsearch.py]()

### MSA Generation Databases

The `AlignmentRunner.run()` method generates MSAs by querying multiple sequence databases in a specific order:

| Database | Tool | Purpose | Output File | Max Hits |
|----------|------|---------|-------------|----------|
| UniRef90 | Jackhmmer | Primary MSA generation | `uniref90_hits.sto` | 10,000 |
| MGnify | Jackhmmer | Environmental sequences | `mgnify_hits.sto` | 5,000 |
| BFD (small) | Jackhmmer | Deep sequence search | `small_bfd_hits.sto` | unlimited |
| BFD+UniRef30+UniClust30 | HHBlits | Deep sequence search | `bfd_uniref_hits.a3m` or `bfd_uniclust_hits.a3m` | unlimited |
| UniProt (multimer) | Jackhmmer | Multimer-specific MSA | `uniprot_hits.sto` | 50,000 |

The choice between small BFD (Jackhmmer) and full BFD (HHBlits) depends on the `use_small_bfd` parameter, controlled by whether `bfd_database_path` is provided without `uniref30_database_path` or `uniclust30_database_path`.

Sources: [openfold/data/data_pipeline.py:388-404](), [openfold/data/data_pipeline.py:483-562](), [run_pretrained_openfold.py:99-111]()

### MSA File Formats and Parsing

Generated MSAs are stored in two formats:

1. **Stockholm (.sto)**: Used by Jackhmmer output
   - Parsed by `parsers.parse_stockholm()`
   - Contains sequence headers with taxonomic information

2. **A3M (.a3m)**: Used by HHBlits output
   - Parsed by `parsers.parse_a3m()`
   - Compact format with lowercase letters for insertions

The `DataPipeline._parse_msa_data()` method reads these files and converts them into `parsers.Msa` objects containing sequences, deletion matrices, and descriptions.

Sources: [openfold/data/data_pipeline.py:714-764](), [openfold/data/parsers.py]()

### MSA Feature Construction

The `make_msa_features()` function converts parsed MSAs into feature tensors:

```mermaid
flowchart LR
    subgraph "Input"
        msa_obj["List[parsers.Msa]"]
    end
    
    subgraph "Processing"
        dedupe["Deduplicate sequences"]
        convert["Convert to integer IDs<br/>(HHBLITS_AA_TO_ID)"]
        extract["Extract deletion matrix"]
        species["Extract species IDs"]
    end
    
    subgraph "Output Features"
        msa_int["msa: [N_seq, N_res]<br/>int32"]
        del_mat["deletion_matrix_int:<br/>[N_seq, N_res] int32"]
        num_aln["num_alignments:<br/>[N_res] int32"]
        species_id["msa_species_identifiers:<br/>[N_seq] object"]
    end
    
    msa_obj --> dedupe
    dedupe --> convert
    convert --> extract
    extract --> species
    
    convert --> msa_int
    extract --> del_mat
    convert --> num_aln
    species --> species_id
```

Sources: [openfold/data/data_pipeline.py:224-261]()

### MSA Data Structure

MSAs in OpenFold are represented as tensors with specific features:

| Feature Name | Description | Dimensions |
|--------------|-------------|------------|
| `msa` | Sequences in the alignment | `[num_seq, seq_length]` |
| `deletion_matrix` | Deletion indicators | `[num_seq, seq_length]` |
| `msa_mask` | Mask for positions in MSA | `[num_seq, seq_length]` |
| `msa_row_mask` | Mask for entire rows | `[num_seq]` |
| `bert_mask` | Mask for BERT training | `[num_seq, seq_length]` |
| `true_msa` | Original MSA before masking | `[num_seq, seq_length]` |

The MSA is stored as integer tokens representing amino acids, with additional tokens for gaps (21) and unknown residues (20).

Sources: [openfold/data/data_transforms.py:36-43]()

### MSA Transformations

MSAs undergo several transformations before being fed into the model:

1. **Sample MSA** (`sample_msa`): Reduces the MSA size by selecting a subset of sequences.
   - Preserves the query sequence (first row)
   - Randomly samples remaining sequences
   - Option to keep remaining sequences as "extra_msa"

2. **Clustering** (`nearest_neighbor_clusters`, `summarize_clusters`): Groups similar sequences and summarizes them.
   - Calculates sequence similarity using weighted Hamming distance
   - Assigns each sequence to its closest cluster
   - Creates cluster profiles and deletion means

3. **MSA Masking** (`make_masked_msa`): Masks portions of the MSA for BERT-style training.
   - Replaces residues with [MASK] token, unknown amino acids, or profile samples
   - Used during training for the masked MSA prediction task

4. **MSA Featurization** (`make_msa_feat`): Converts the MSA into feature tensors.
   - One-hot encodes sequences
   - Computes deletion statistics
   - Creates cluster profiles

```mermaid
flowchart TD
    subgraph "MSA Processing Pipeline"
        raw["Raw MSA"]
        sample["sample_msa()"]
        cluster["nearest_neighbor_clusters()"]
        summarize["summarize_clusters()"]
        mask["make_masked_msa()"]
        feat["make_msa_feat()"]
        final["Final MSA Features"]
    end
    
    raw --> sample
    sample --> cluster
    cluster --> summarize
    summarize --> mask
    mask --> feat
    feat --> final
    
    subgraph "Feature Descriptions"
        msa_feat["msa_feat: Combined MSA features"]
        target_feat["target_feat: Query sequence features"]
        extra_msa["extra_msa: Additional sequences"]
        cluster_profile["cluster_profile: Per-position aa frequencies"]
    end
```

Sources: [openfold/data/data_transforms.py:185-229](), [openfold/data/data_transforms.py:290-376](), [openfold/data/data_transforms.py:452-501](), [openfold/data/data_transforms.py:544-591](), [openfold/data/input_pipeline.py:70-126]()

## Template Search and Processing

### Template Search: HHSearch vs HMMSearch

OpenFold uses different template search strategies depending on whether it is running in monomer or multimer mode:

**Template Search Mode Selection**

```mermaid
flowchart TD
    config["config_preset parameter"]
    
    is_multimer{"Contains 'multimer'?"}
    
    hmmsearch["Hmmsearch<br/>binary: hmmsearch + hmmbuild<br/>database: pdb_seqres"]
    hhsearch["HHSearch<br/>binary: hhsearch<br/>database: pdb70"]
    
    hmm_output["Output: hmm_output.sto<br/>Parsed by parse_hmmsearch_sto()"]
    hhr_output["Output: output.hhr<br/>Parsed by parse_hhr()"]
    
    config --> is_multimer
    is_multimer -->|Yes| hmmsearch
    is_multimer -->|No| hhsearch
    
    hmmsearch --> hmm_output
    hhsearch --> hhr_output
```

Sources: [run_pretrained_openfold.py:76-86](), [openfold/data/data_pipeline.py:766-810]()

#### HHSearch (Monomer Mode)

- **Input Format**: A3M alignment format (Stockholm MSA converted to A3M)
- **Database**: PDB70 (clustered at 70% sequence identity)
- **Search Method**: HMM-HMM comparison
- **Output Format**: HHR (HHSearch result format)
- **Parsing**: `parsers.parse_hhr()` extracts `TemplateHit` objects

Key characteristics:
- More sensitive for finding remote homologs
- Uses profile-profile comparison
- Returns probability scores and E-values
- Template hits include alignment indices for mapping query to template positions

Sources: [openfold/data/tools/hhsearch.py](), [openfold/data/parsers.py]()

#### HMMSearch (Multimer Mode)

- **Input Format**: FASTA sequence
- **Database**: PDB seqres (full sequence database)
- **Search Method**: Profile HMM search against database
- **Output Format**: Stockholm alignment in `hmm_output.sto`
- **Parsing**: `parsers.parse_hmmsearch_sto()` extracts hits

Key characteristics:
- Builds HMM profile using `hmmbuild`
- Searches using `hmmsearch`
- Returns hits with bit scores and E-values
- More comprehensive search for multimer templates

Sources: [openfold/data/tools/hmmsearch.py](), [openfold/data/parsers.py](), [openfold/data/data_pipeline.py:786-791]()

### TemplateHit Data Structure

Template search results are represented as `TemplateHit` objects:

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Template identifier (PDB ID + chain, e.g., "5xxx_A") |
| `aligned_cols` | `int` | Number of aligned columns |
| `sum_probs` | `float` | Sum of alignment probabilities (confidence score) |
| `query` | `str` | Aligned query sequence with gaps |
| `hit_sequence` | `str` | Aligned template sequence with gaps |
| `indices_query` | `List[int]` | Query position for each alignment column |
| `indices_hit` | `List[int]` | Template position for each alignment column |
| `index` | `int` | Rank in search results |

Sources: [openfold/data/parsers.py]()

### Custom Template Mode

OpenFold also supports using custom templates via the `CustomHitFeaturizer`:

```python
# Initialize custom template featurizer
template_featurizer = templates.CustomHitFeaturizer(
    mmcif_dir=args.template_mmcif_dir,
    max_template_date="9999-12-31",  # dummy, not used
    max_hits=-1,  # dummy, not used
    kalign_binary_path=args.kalign_binary_path
)
```

In this mode:
- No template search is performed
- mmCIF files in `template_mmcif_dir` are directly used as templates
- Useful for providing specific structural templates
- Enabled with `--use_custom_template` flag

Sources: [run_pretrained_openfold.py:211-217](), [openfold/data/templates.py:1151-1237]()

### Template Feature Extraction

Template features are extracted through a multi-step process coordinated by template featurizer classes.

**Template Featurizer Class Hierarchy**

```mermaid
classDiagram
    class TemplateHitFeaturizer {
        <<abstract>>
        +mmcif_dir: str
        +max_template_date: str
        +max_hits: int
        +kalign_binary_path: str
        +release_dates: Dict
        +obsolete_pdbs: Dict
        +get_templates(query_sequence, hits)
    }
    
    class HhsearchHitFeaturizer {
        +strict_error_check: bool
        +get_templates(query_sequence, hits)
        -_process_single_hit()
        -_extract_template_features()
    }
    
    class HmmsearchHitFeaturizer {
        +get_templates(query_sequence, hits)
        -_process_single_hit()
        -_extract_template_features()
    }
    
    class CustomHitFeaturizer {
        +get_templates(query_sequence, hits)
        +get_custom_template_features()
    }
    
    TemplateHitFeaturizer <|-- HhsearchHitFeaturizer
    TemplateHitFeaturizer <|-- HmmsearchHitFeaturizer
    TemplateHitFeaturizer <|-- CustomHitFeaturizer
```

Sources: [openfold/data/templates.py:930-1011](), [openfold/data/templates.py:1014-1096](), [openfold/data/templates.py:1151-1237]()

### Template Feature Extraction Pipeline

The template featurizer processes hits through several stages:

**Template Processing Flow**

```mermaid
flowchart TD
    subgraph "Prefiltering"
        hits["Template Hits"]
        prefilter["_prefilter_hit()"]
        check_date["Check release date"]
        check_align["Check align ratio"]
        check_dup["Check for duplicates"]
        check_len["Check minimum length"]
    end
    
    subgraph "mmCIF Processing"
        read_cif["Read mmCIF file<br/>_read_file()"]
        parse_mmcif["mmcif_parsing.parse()"]
        find_chain["_find_template_in_pdb()"]
        realign["_realign_pdb_template_to_query()<br/>(if needed)"]
    end
    
    subgraph "Feature Extraction"
        extract["_extract_template_features()"]
        get_atoms["_get_atom_positions()"]
        check_dist["_check_residue_distances()"]
        map_query["Map template atoms to query positions"]
    end
    
    subgraph "Output"
        template_features["Template Features:<br/>template_aatype<br/>template_all_atom_positions<br/>template_all_atom_mask<br/>template_domain_names<br/>template_sequence<br/>template_sum_probs"]
    end
    
    hits --> prefilter
    prefilter --> check_date
    check_date --> check_align
    check_align --> check_dup
    check_dup --> check_len
    
    check_len --> read_cif
    read_cif --> parse_mmcif
    parse_mmcif --> find_chain
    find_chain --> realign
    
    realign --> extract
    extract --> get_atoms
    get_atoms --> check_dist
    check_dist --> map_query
    
    map_query --> template_features
```

Sources: [openfold/data/templates.py:780-815](), [openfold/data/templates.py:826-910](), [openfold/data/templates.py:548-705]()

### Template Prefiltering

Before processing mmCIF files, template hits are prefiltered using `_assess_hhsearch_hit()` to eliminate unsuitable templates:

| Filter | Criterion | Threshold |
|--------|-----------|-----------|
| **Release Date** | Template release date must be before cutoff | `max_template_date` parameter |
| **Alignment Ratio** | Aligned columns / query length | min_align_ratio ≥ 0.1 |
| **Duplicate Detection** | Template is subsequence of query | max_subsequence_ratio < 0.95 |
| **Minimum Length** | Template sequence length | ≥ 10 residues |

Filters raise specific exceptions (`DateError`, `AlignRatioError`, `DuplicateError`, `LengthError`) that are caught and logged.

Sources: [openfold/data/templates.py:220-289]()

### Template Sequence Alignment

If the template sequence in the PDB differs from the hit sequence, realignment is performed using Kalign:

1. **Sequence Matching**: `_find_template_in_pdb()` tries to match the hit sequence to chains in the mmCIF:
   - Exact match in chain ID and sequence
   - Exact match in sequence only
   - Fuzzy match with 'X' as wildcard

2. **Realignment**: If sequences differ, `_realign_pdb_template_to_query()` aligns the old and new sequences:
   - Uses Kalign binary
   - Requires ≥90% sequence identity
   - Updates the query-to-template mapping

Sources: [openfold/data/templates.py:292-363](), [openfold/data/templates.py:366-502]()

### Template Feature Tensors

The final template features returned by `_extract_template_features()` include:

| Feature | Shape | Description |
|---------|-------|-------------|
| `template_aatype` | `[N_res, 22]` | One-hot encoded amino acid types |
| `template_all_atom_positions` | `[N_res, 37, 3]` | All-atom coordinates (atom37 representation) |
| `template_all_atom_mask` | `[N_res, 37]` | Mask for present atoms |
| `template_domain_names` | `[]` | String identifier (e.g., "5xxx_a") |
| `template_sequence` | `[]` | Template sequence string |
| `template_sum_probs` | `[1]` | Confidence score from search |

For queries with no templates, `empty_template_feats()` returns zero-filled arrays.

Sources: [openfold/data/templates.py:548-705](), [openfold/data/templates.py:93-108](), [openfold/data/data_pipeline.py:46-63]()

## Integration in the DataPipeline

The `DataPipeline` class coordinates MSA and template feature generation:

**DataPipeline Architecture**

```mermaid
classDiagram
    class DataPipeline {
        +template_featurizer: TemplateHitFeaturizer
        +process_fasta(fasta_path, alignment_dir)
        +process_mmcif(mmcif, alignment_dir, chain_id)
        +process_multiseq_fasta(fasta_path, super_alignment_dir)
        -_parse_msa_data(alignment_dir, alignment_index)
        -_parse_template_hit_files(alignment_dir, input_sequence)
        -_get_msas(alignment_dir, input_sequence)
        -_process_msa_feats(alignment_dir, input_sequence)
        -_process_seqemb_features(alignment_dir)
    }
    
    class DataPipelineMultimer {
        +monomer_data_pipeline: DataPipeline
        +process_fasta(fasta_path, alignment_dir)
        +_process_single_chain(chain_fasta_str, chain_alignment_dir)
        +_pair_and_merge(all_chain_features)
    }
    
    DataPipelineMultimer --> DataPipeline : uses for per-chain processing
```

Sources: [openfold/data/data_pipeline.py:706-914](), [openfold/data/data_pipeline.py:1013-1202]()

### DataPipeline Processing Flow

The `DataPipeline.process_fasta()` method processes a single sequence:

**process_fasta() Execution Flow**

```mermaid
flowchart TD
    subgraph "Input"
        fasta["FASTA file"]
        alignment_dir["Alignment directory<br/>(contains MSA files)"]
    end
    
    subgraph "Sequence Features"
        parse_fasta["parse_fasta()"]
        make_seq["make_sequence_features()"]
    end
    
    subgraph "MSA Processing"
        check_seqemb{"seqemb_mode?"}
        parse_msa["_parse_msa_data()"]
        make_msa["make_msa_features()"]
        make_dummy["make_dummy_msa_feats()"]
        load_emb["_process_seqemb_features()"]
    end
    
    subgraph "Template Processing"
        parse_tmpl["_parse_template_hit_files()"]
        make_tmpl["make_template_features()"]
        featurizer["template_featurizer.get_templates()"]
    end
    
    subgraph "Output"
        feature_dict["FeatureDict:<br/>sequence features<br/>+ MSA features<br/>+ template features<br/>(+ seq embeddings)"]
    end
    
    fasta --> parse_fasta
    parse_fasta --> make_seq
    
    alignment_dir --> check_seqemb
    check_seqemb -->|Yes| make_dummy
    check_seqemb -->|Yes| load_emb
    check_seqemb -->|No| parse_msa
    parse_msa --> make_msa
    
    alignment_dir --> parse_tmpl
    parse_tmpl --> make_tmpl
    make_tmpl --> featurizer
    
    make_seq --> feature_dict
    make_msa --> feature_dict
    make_dummy --> feature_dict
    load_emb --> feature_dict
    featurizer --> feature_dict
```

Sources: [openfold/data/data_pipeline.py:864-914]()

### Multimer Pipeline

For multimer predictions, `DataPipelineMultimer` processes each chain separately, then pairs and merges features:

1. **Per-Chain Processing**: Uses `DataPipeline` to process each chain's MSA and templates
2. **Chain Pairing**: `msa_pairing.create_paired_features()` matches sequences between chains
3. **Feature Merging**: Combines chain features with assembly information

The multimer pipeline adds additional features like `asym_id`, `sym_id`, `entity_id` to distinguish between chains.

Sources: [openfold/data/data_pipeline.py:1013-1202](), [openfold/data/msa_pairing.py]()

### Integration with Inference Script

The inference script (`run_pretrained_openfold.py`) orchestrates the complete workflow:

**Inference Workflow Integration**

```mermaid
flowchart TD
    subgraph "Setup"
        args["Command-line arguments"]
        config["model_config()"]
        featurizer["Template Featurizer<br/>(HhsearchHitFeaturizer or<br/>HmmsearchHitFeaturizer)"]
        data_processor["DataPipeline or<br/>DataPipelineMultimer"]
    end
    
    subgraph "Alignment Generation"
        check_precomp{"Precomputed<br/>alignments?"}
        alignment_runner["AlignmentRunner.run()"]
        use_existing["Use existing alignments"]
    end
    
    subgraph "Feature Generation"
        gen_features["generate_feature_dict()"]
        process_fasta["data_processor.process_fasta()"]
    end
    
    subgraph "Feature Processing"
        feature_pipeline["FeaturePipeline"]
        transforms["Apply data transforms"]
    end
    
    subgraph "Model Execution"
        model["Model forward pass"]
    end
    
    args --> config
    config --> featurizer
    featurizer --> data_processor
    
    args --> check_precomp
    check_precomp -->|No| alignment_runner
    check_precomp -->|Yes| use_existing
    
    alignment_runner --> gen_features
    use_existing --> gen_features
    gen_features --> process_fasta
    
    process_fasta --> feature_pipeline
    feature_pipeline --> transforms
    
    transforms --> model
```

Sources: [run_pretrained_openfold.py:63-170](), [run_pretrained_openfold.py:177-395]()

## Complete Code Structure Map

The following diagram maps the MSA and template processing workflow to specific code entities:

**Code Entity Mapping**

```mermaid
classDiagram
    class AlignmentRunner {
        +jackhmmer_uniref90_runner
        +jackhmmer_mgnify_runner
        +jackhmmer_small_bfd_runner
        +hhblits_bfd_unirefclust_runner
        +jackhmmer_uniprot_runner
        +template_searcher
        +run(fasta_path, output_dir)
    }
    
    class DataPipeline {
        +template_featurizer
        +process_fasta(fasta_path, alignment_dir)
        +_parse_msa_data(alignment_dir)
        +_parse_template_hit_files(alignment_dir)
        +_process_msa_feats(alignment_dir)
    }
    
    class DataPipelineMultimer {
        +monomer_data_pipeline
        +process_fasta(fasta_path, alignment_dir)
        +_process_single_chain()
        +_pair_and_merge()
    }
    
    class HhsearchHitFeaturizer {
        +mmcif_dir
        +max_template_date
        +release_dates
        +obsolete_pdbs
        +get_templates(query_sequence, hits)
        -_prefilter_hit()
        -_process_single_hit()
        -_extract_template_features()
    }
    
    class HmmsearchHitFeaturizer {
        +mmcif_dir
        +max_template_date
        +get_templates(query_sequence, hits)
        -_process_single_hit()
    }
    
    class CustomHitFeaturizer {
        +mmcif_dir
        +kalign_binary_path
        +get_templates(query_sequence, hits)
        +get_custom_template_features()
    }
    
    class Jackhmmer {
        +binary_path
        +database_path
        +n_cpu
        +query(fasta_path)
    }
    
    class HHBlits {
        +binary_path
        +databases
        +n_cpu
        +query(fasta_path)
    }
    
    class HHSearch {
        +binary_path
        +databases
        +query(msa, output_dir)
    }
    
    class Hmmsearch {
        +binary_path
        +hmmbuild_binary_path
        +database_path
        +query(fasta_path, output_dir)
    }
    
    class Parsers {
        +parse_fasta()
        +parse_stockholm()
        +parse_a3m()
        +parse_hhr()
        +parse_hmmsearch_sto()
    }
    
    class mmcif_parsing {
        +parse(file_id, mmcif_string)
        +get_atom_coords()
        +MmcifObject
    }
    
    AlignmentRunner --> Jackhmmer
    AlignmentRunner --> HHBlits
    AlignmentRunner --> HHSearch
    AlignmentRunner --> Hmmsearch
    
    DataPipeline --> Parsers
    DataPipeline --> HhsearchHitFeaturizer
    DataPipeline --> HmmsearchHitFeaturizer
    DataPipeline --> CustomHitFeaturizer
    
    HhsearchHitFeaturizer --> mmcif_parsing
    HmmsearchHitFeaturizer --> mmcif_parsing
    CustomHitFeaturizer --> mmcif_parsing
    
    DataPipelineMultimer --> DataPipeline
```

Sources: [openfold/data/data_pipeline.py:334-563](), [openfold/data/data_pipeline.py:706-914](), [openfold/data/data_pipeline.py:1013-1202](), [openfold/data/templates.py:930-1096](), [openfold/data/templates.py:1151-1237](), [openfold/data/tools/jackhmmer.py](), [openfold/data/tools/hhblits.py](), [openfold/data/tools/hhsearch.py](), [openfold/data/tools/hmmsearch.py](), [openfold/data/parsers.py](), [openfold/data/mmcif_parsing.py]()

## Key Configuration and Command-Line Options

### AlignmentRunner Configuration

The `AlignmentRunner` is configured through command-line arguments or script parameters:

| Parameter | Description | Default |
|-----------|-------------|---------|
| `jackhmmer_binary_path` | Path to jackhmmer executable | `{CONDA_PREFIX}/bin/jackhmmer` |
| `hhblits_binary_path` | Path to hhblits executable | `{CONDA_PREFIX}/bin/hhblits` |
| `hhsearch_binary_path` | Path to hhsearch executable | `{CONDA_PREFIX}/bin/hhsearch` |
| `hmmsearch_binary_path` | Path to hmmsearch executable | `{CONDA_PREFIX}/bin/hmmsearch` |
| `hmmbuild_binary_path` | Path to hmmbuild executable | `{CONDA_PREFIX}/bin/hmmbuild` |
| `uniref90_database_path` | Path to UniRef90 database | Required |
| `mgnify_database_path` | Path to MGnify database | Optional |
| `bfd_database_path` | Path to BFD database | Optional |
| `uniref30_database_path` | Path to UniRef30 database | Optional |
| `uniclust30_database_path` | Path to UniClust30 database | Optional |
| `uniprot_database_path` | Path to UniProt database (multimer) | Optional |
| `pdb70_database_path` | Path to PDB70 database (monomer) | Required for templates |
| `pdb_seqres_database_path` | Path to PDB seqres (multimer) | Required for multimer templates |
| `cpus` | Number of CPUs for alignment tools | 4 |

Sources: [scripts/utils.py:13-65](), [openfold/data/data_pipeline.py:336-387]()

### Template Featurizer Configuration

Template featurizers require additional parameters:

| Parameter | Description | Default |
|-----------|-------------|---------|
| `template_mmcif_dir` | Directory containing mmCIF template files | Required |
| `max_template_date` | Maximum release date for templates | Current date |
| `kalign_binary_path` | Path to kalign executable | `{CONDA_PREFIX}/bin/kalign` |
| `release_dates_path` | Path to PDB release dates JSON | Optional |
| `obsolete_pdbs_path` | Path to obsolete PDB mappings | Optional |
| `max_templates` | Maximum number of templates to use | From config |
| `use_custom_template` | Use custom templates without search | False |

Sources: [run_pretrained_openfold.py:210-243](), [openfold/data/templates.py:930-966]()

### Model Configuration Parameters

The model configuration controls template usage:

| Parameter | Location | Default |
|-----------|----------|---------|
| `data.common.max_recycling_iters` | Model config | 3 |
| `data.predict.max_templates` | Predict config | 4 |
| `data.common.use_templates` | Common config | True |
| `data.common.use_template_torsion_angles` | Common config | True |

These can be overridden using the `--experiment_config_json` flag with a JSON file containing flattened config paths.

Sources: [run_pretrained_openfold.py:198-201](), [openfold/config.py]()

## Conclusion

MSA and template processing are critical components of the OpenFold pipeline that prepare evolutionary information for the neural network model. The system uses a combination of established bioinformatics tools (Jackhmmer, HHBlits, HHSearch) and specialized data transformations to extract and format this information. The processing is organized into nonensembled transformations (applied once) and ensembled transformations (potentially applied multiple times with different random seeds). This carefully engineered pipeline ensures that the model receives high-quality evolutionary information, which is essential for accurate protein structure prediction.

---