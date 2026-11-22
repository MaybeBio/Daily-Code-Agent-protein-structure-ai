# Running Inference

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [README.md](README.md)
- [docs/source/Inference.md](docs/source/Inference.md)
- [docs/source/Multimer_Inference.md](docs/source/Multimer_Inference.md)
- [docs/source/Single_Sequence_Inference.md](docs/source/Single_Sequence_Inference.md)
- [docs/source/conf.py](docs/source/conf.py)
- [openfold/data/data_pipeline.py](openfold/data/data_pipeline.py)
- [openfold/data/templates.py](openfold/data/templates.py)
- [run_pretrained_openfold.py](run_pretrained_openfold.py)
- [scripts/generate_mmcif_cache.py](scripts/generate_mmcif_cache.py)
- [scripts/precompute_alignments.py](scripts/precompute_alignments.py)
- [scripts/utils.py](scripts/utils.py)

</details>



## Purpose and Scope

This page provides an overview of OpenFold's inference capabilities for protein structure prediction. It describes the available inference modes, main entry points, and common workflows. For detailed instructions on specific inference scenarios, see:
- [Inference Pipeline Overview](#3.1) - detailed walkthrough of `run_pretrained_openfold.py`
- [Monomer Inference](#3.2) - single-chain protein prediction
- [Multimer Inference](#3.3) - multi-chain complex prediction  
- [Single Sequence (SoloSeq) Inference](#3.4) - MSA-free prediction with ESM embeddings
- [Jupyter Notebook Interface](#3.5) - interactive Colab-based prediction
- [Performance Optimization](#3.6) - precision settings, kernels, and memory management

For training the model, see [Training OpenFold](#4). For model architecture details, see [Model Architecture](#5).

## Inference Modes

OpenFold supports three primary inference modes, each optimized for different prediction scenarios:

| Mode | Description | Config Preset Pattern | Primary Use Case |
|------|-------------|----------------------|------------------|
| **Monomer** | Single-chain protein prediction with full MSA | `model_[1-5]`, `model_[1-5]_ptm` | Standard protein structure prediction |
| **Multimer** | Multi-chain complex prediction | `model_[1-5]_multimer_v3` | Protein-protein interactions, homo/hetero-oligomers |
| **SoloSeq** | MSA-free prediction using ESM-1b embeddings | `seq_model_esm1b_ptm` | Fast prediction without database searches |

**Sources:** [run_pretrained_openfold.py:181-196](), [docs/source/Inference.md:6-13](), [docs/source/Multimer_Inference.md:1-78]()

## Main Entry Points

### Command-Line Inference Script

The primary entry point for inference is `run_pretrained_openfold.py`, which orchestrates the complete prediction pipeline from FASTA input to PDB/MMCIF output.

```mermaid
graph TB
    subgraph "Entry Point"
        SCRIPT["run_pretrained_openfold.py<br/>main() function"]
    end
    
    subgraph "Input Processing"
        FASTA["FASTA files in<br/>fasta_dir"]
        ALIGN_CHECK{"use_precomputed_<br/>alignments?"}
        GEN_ALIGN["precompute_alignments()<br/>AlignmentRunner"]
        LOAD_ALIGN["Load existing<br/>alignment files"]
    end
    
    subgraph "Feature Generation"
        DATAPIPE["DataPipeline or<br/>DataPipelineMultimer"]
        FEATGEN["generate_feature_dict()<br/>process_fasta()"]
        FEATPROC["FeaturePipeline<br/>process_features()"]
    end
    
    subgraph "Model Execution"
        LOADMODEL["load_models_from_<br/>command_line()"]
        MODEL["AlphaFold model<br/>forward pass"]
        TRACE_CHECK{"trace_model<br/>enabled?"}
        TRACING["trace_model_()<br/>TorchScript compilation"]
    end
    
    subgraph "Output Generation"
        PREP["prep_output()<br/>build protein object"]
        RELAX_CHECK{"skip_relaxation?"}
        AMBER["relax_protein()<br/>AMBER minimization"]
        PDB["Write PDB/MMCIF<br/>output files"]
    end
    
    SCRIPT --> FASTA
    FASTA --> ALIGN_CHECK
    ALIGN_CHECK -->|No| GEN_ALIGN
    ALIGN_CHECK -->|Yes| LOAD_ALIGN
    GEN_ALIGN --> FEATGEN
    LOAD_ALIGN --> FEATGEN
    
    DATAPIPE --> FEATGEN
    FEATGEN --> FEATPROC
    
    FEATPROC --> LOADMODEL
    LOADMODEL --> TRACE_CHECK
    TRACE_CHECK -->|Yes| TRACING
    TRACE_CHECK -->|No| MODEL
    TRACING --> MODEL
    
    MODEL --> PREP
    PREP --> RELAX_CHECK
    RELAX_CHECK -->|No| AMBER
    RELAX_CHECK -->|Yes| PDB
    AMBER --> PDB
```

**Inference Workflow Through run_pretrained_openfold.py**

The script executes the following major phases:

1. **Configuration Setup** ([run_pretrained_openfold.py:184-196]()): Loads model config based on `--config_preset`
2. **Alignment Generation** ([run_pretrained_openfold.py:63-123]()): Runs `AlignmentRunner` via `precompute_alignments()` or loads existing alignments
3. **Feature Dictionary Construction** ([run_pretrained_openfold.py:129-170]()): Converts alignments to features via `DataPipeline.process_fasta()`
4. **Feature Processing** ([run_pretrained_openfold.py:325-327]()): Transforms features for model input via `FeaturePipeline.process_features()`
5. **Model Inference** ([run_pretrained_openfold.py:347]()): Executes forward pass through loaded model
6. **Structure Output** ([run_pretrained_openfold.py:356-377]()): Generates unrelaxed PDB/MMCIF
7. **Optional Relaxation** ([run_pretrained_openfold.py:381-385]()): AMBER energy minimization

**Sources:** [run_pretrained_openfold.py:177-395](), [openfold/utils/script_utils.py]()

### Colab Notebook Interface

For interactive inference with visualization capabilities, OpenFold provides a Jupyter notebook interface accessible via Google Colab. This provides a web-based alternative to the command-line script with integrated visualization of predicted structures.

**Sources:** [docs/source/Inference.md:1-195]()

## Configuration Presets and Model Parameters

### Config Preset System

OpenFold uses a preset-based configuration system that controls model behavior, template usage, and output metrics. Each preset corresponds to specific model architectures and parameter files.

```mermaid
graph LR
    subgraph "Config Presets"
        MONO1["model_1, model_2<br/>With templates"]
        MONO1P["model_1_ptm, model_2_ptm<br/>With templates + pTM"]
        MONO3["model_3, model_4, model_5<br/>No templates"]
        MONO3P["model_3_ptm, model_4_ptm, model_5_ptm<br/>No templates + pTM"]
        MULTI["model_[1-5]_multimer_v3<br/>Multimer mode"]
        SEQ["seq_model_esm1b_ptm<br/>SoloSeq mode"]
    end
    
    subgraph "model_config Function"
        CONFIG["model_config()<br/>openfold/config.py"]
    end
    
    subgraph "Parameter Files"
        AF_PARAMS["AlphaFold params<br/>params_model_*.npz"]
        OF_PARAMS["OpenFold params<br/>finetuning_*.pt"]
        SOLO_PARAMS["SoloSeq params<br/>seq_model_esm1b_ptm.pt"]
    end
    
    MONO1 --> CONFIG
    MONO1P --> CONFIG
    MONO3 --> CONFIG
    MONO3P --> CONFIG
    MULTI --> CONFIG
    SEQ --> CONFIG
    
    CONFIG --> AF_PARAMS
    CONFIG --> OF_PARAMS
    CONFIG --> SOLO_PARAMS
```

**Config Preset to Parameter File Mapping**

| Config Preset | Template Support | pTM Score | Compatible Parameters |
|---------------|------------------|-----------|----------------------|
| `model_1`, `model_2` | Yes | No | `params_model_[1-2].npz`, `finetuning_[2-5].pt` |
| `model_1_ptm`, `model_2_ptm` | Yes | Yes | `params_model_[1-2]_ptm.npz`, `finetuning_ptm_[1-2].pt` |
| `model_3`, `model_4`, `model_5` | No | No | `params_model_[3-5].npz`, `finetuning_no_templ_[1-2].pt` |
| `model_3_ptm`, `model_4_ptm`, `model_5_ptm` | No | Yes | `params_model_[3-5]_ptm.npz`, `finetuning_no_templ_ptm_1.pt` |
| `model_[1-5]_multimer_v3` | Yes (HMMSearch) | Yes | `params_model_[1-5]_multimer_v3.npz` |
| `seq_model_esm1b_ptm` | Optional | Yes | `seq_model_esm1b_ptm.pt` |

The config preset is specified via the `--config_preset` argument. If no parameter path is explicitly provided via `--jax_param_path` or `--openfold_checkpoint_path`, the script automatically selects parameters from `openfold/resources/params/` matching the preset name.

**Sources:** [run_pretrained_openfold.py:184-196](), [run_pretrained_openfold.py:530-534](), [docs/source/Inference.md:106-120]()

## Data Processing Components

### AlignmentRunner and Template Search

The `AlignmentRunner` class orchestrates external bioinformatics tools to generate MSAs and template hits.

```mermaid
graph TB
    subgraph "AlignmentRunner Class"
        AR["AlignmentRunner<br/>openfold/data/data_pipeline.py"]
    end
    
    subgraph "MSA Generation Tools"
        JACK["jackhmmer_uniref90_runner<br/>vs UniRef90"]
        MGN["jackhmmer_mgnify_runner<br/>vs MGnify"]
        BFD_SMALL["jackhmmer_small_bfd_runner<br/>vs BFD (small)"]
        BFD_LARGE["hhblits_bfd_unirefclust_runner<br/>vs BFD+UniRef30/UniClust30"]
        UNI["jackhmmer_uniprot_runner<br/>vs UniProt (multimer)"]
    end
    
    subgraph "Template Search Tools"
        HH["HHSearch<br/>openfold/data/tools/hhsearch.py<br/>vs PDB70 (monomer)"]
        HMM["Hmmsearch<br/>openfold/data/tools/hmmsearch.py<br/>vs PDB SeqRes (multimer)"]
    end
    
    subgraph "Output Files"
        MSA_OUT["*.sto, *.a3m files<br/>alignment_dir"]
        TEMPL_OUT["*.hhr, hmm_output.sto<br/>alignment_dir"]
    end
    
    AR --> JACK
    AR --> MGN
    AR --> BFD_SMALL
    AR --> BFD_LARGE
    AR --> UNI
    AR --> HH
    AR --> HMM
    
    JACK --> MSA_OUT
    MGN --> MSA_OUT
    BFD_SMALL --> MSA_OUT
    BFD_LARGE --> MSA_OUT
    UNI --> MSA_OUT
    
    HH --> TEMPL_OUT
    HMM --> TEMPL_OUT
```

**AlignmentRunner Configuration**

The `AlignmentRunner` is configured differently for monomer vs. multimer modes:

- **Monomer**: Uses Jackhmmer (UniRef90, MGnify, BFD) + HHBlits (BFD+UniRef30/UniClust30) for MSAs, HHSearch (PDB70) for templates
- **Multimer**: Uses Jackhmmer (UniRef90, MGnify, UniProt) for MSAs, Hmmsearch (PDB SeqRes) for templates

**Sources:** [openfold/data/data_pipeline.py:334-563](), [run_pretrained_openfold.py:76-115]()

### DataPipeline and Feature Generation

The `DataPipeline` class converts raw alignment files and template hits into feature dictionaries suitable for model input.

```mermaid
graph TB
    subgraph "Pipeline Classes"
        DP["DataPipeline<br/>process_fasta()"]
        DPM["DataPipelineMultimer<br/>process_fasta()"]
        TF["TemplateHitFeaturizer<br/>HhsearchHitFeaturizer or<br/>HmmsearchHitFeaturizer"]
    end
    
    subgraph "Input Files"
        FASTA["FASTA file"]
        MSA["MSA files<br/>*.sto, *.a3m"]
        TEMPL["Template hits<br/>*.hhr, *.sto"]
        MMCIF["MMCIF files<br/>template structures"]
    end
    
    subgraph "Feature Extraction"
        SEQ["make_sequence_features()<br/>aatype, residue_index"]
        MSA_F["make_msa_features()<br/>msa, deletion_matrix"]
        TEMPL_F["make_template_features()<br/>template_aatype, positions"]
    end
    
    subgraph "Feature Dictionary"
        FD["FeatureDict<br/>np.ndarray mappings"]
    end
    
    subgraph "FeaturePipeline"
        FP["FeaturePipeline<br/>process_features()<br/>data transforms"]
    end
    
    FASTA --> DP
    MSA --> DP
    TEMPL --> DP
    MMCIF --> TF
    TF --> DP
    
    FASTA --> DPM
    MSA --> DPM
    TEMPL --> DPM
    
    DP --> SEQ
    DP --> MSA_F
    DP --> TEMPL_F
    
    DPM --> SEQ
    DPM --> MSA_F
    DPM --> TEMPL_F
    
    SEQ --> FD
    MSA_F --> FD
    TEMPL_F --> FD
    
    FD --> FP
```

**Key Methods:**
- `DataPipeline.process_fasta()` ([openfold/data/data_pipeline.py:864-914]()): Processes single-chain FASTA files
- `DataPipeline._parse_msa_data()` ([openfold/data/data_pipeline.py:714-764]()): Parses MSA files into `Msa` objects
- `DataPipeline._parse_template_hit_files()` ([openfold/data/data_pipeline.py:766-811]()): Parses template search results
- `make_msa_features()` ([openfold/data/data_pipeline.py:224-261]()): Converts MSAs to integer arrays
- `make_template_features()` ([openfold/data/data_pipeline.py:46-63]()): Extracts template atom positions and features
- `FeaturePipeline.process_features()` ([openfold/data/feature_pipeline.py]()): Applies data transforms (cropping, masking, etc.)

**Sources:** [openfold/data/data_pipeline.py:706-914](), [run_pretrained_openfold.py:129-170](), [run_pretrained_openfold.py:236-242]()

## Command-Line Arguments

### Required Arguments

```python
# Positional arguments
fasta_dir              # Directory containing FASTA files (.fasta or .fa)
template_mmcif_dir     # Directory containing template MMCIF files

# Model configuration
--config_preset        # Model preset (default: "model_1")
--model_device         # Device for inference (e.g., "cuda:0", "cpu")
```

### Database Paths (for alignment generation)

```python
--uniref90_database_path       # UniRef90 FASTA database
--mgnify_database_path         # MGnify FASTA database  
--bfd_database_path            # BFD database
--pdb70_database_path          # PDB70 database (monomer)
--pdb_seqres_database_path     # PDB SeqRes database (multimer)
--uniprot_database_path        # UniProt database (multimer)
--uniref30_database_path       # UniRef30 database (optional)
--uniclust30_database_path     # UniClust30 database (optional)
```

### Common Options

```python
--output_dir                   # Output directory (default: current directory)
--use_precomputed_alignments   # Path to precomputed alignment directory
--jax_param_path               # Path to AlphaFold .npz parameters
--openfold_checkpoint_path     # Path to OpenFold .pt checkpoint
--skip_relaxation              # Skip AMBER energy minimization
--save_outputs                 # Save all model outputs (embeddings, etc.)
--cif_output                   # Output MMCIF instead of PDB format
--data_random_seed             # Random seed for reproducibility
```

### Performance Optimization

```python
--trace_model                              # Enable TorchScript tracing
--long_sequence_inference                  # Enable memory-saving options
--precision                                # Compute precision: tf32|fp32|fp16|bf16
--use_deepspeed_evoformer_attention       # Use DeepSpeed attention kernel
--use_cuequivariance_attention            # Use cuEquivariance attention
--use_cuequivariance_multiplicative_update # Use cuEquivariance tri-mult kernel
--trt_mode                                 # TensorRT mode: build|run
--trt_engine_dir                          # TensorRT engine directory
--experiment_config_json                   # Custom config overrides
```

**Sources:** [run_pretrained_openfold.py:398-527](), [scripts/utils.py:13-65]()

## Output Structure

The inference script produces the following output structure:

```
output_dir/
├── alignments/
│   └── {sequence_tag}/
│       ├── uniref90_hits.sto
│       ├── mgnify_hits.sto
│       ├── bfd_uniclust_hits.a3m
│       └── hhsearch_output.hhr (or hmm_output.sto for multimer)
└── predictions/
    ├── {sequence_tag}_{config_preset}_unrelaxed.pdb
    ├── {sequence_tag}_{config_preset}_relaxed.pdb (if relaxation enabled)
    └── {sequence_tag}_{config_preset}_output_dict.pkl (if --save_outputs)
```

### Output Files

- **Unrelaxed PDB/MMCIF**: Raw model prediction with pLDDT scores in B-factor column
- **Relaxed PDB/MMCIF**: Structure after AMBER energy minimization (if `--skip_relaxation` not set)
- **Output Dictionary** (optional): Full model outputs including:
  - `final_atom_positions`: Predicted atomic coordinates
  - `plddt`: Per-residue confidence scores (0-100)
  - `predicted_aligned_error` (PAE): Inter-residue distance error estimates
  - `ptm` / `iptm`: Template modeling scores
  - MSA and pair representations

**Sources:** [run_pretrained_openfold.py:366-394](), [openfold/utils/script_utils.py]()

## Inference Mode Selection

The inference mode is primarily determined by:

1. **Config Preset**: Specified via `--config_preset` argument
   - Monomer: `model_[1-5]`, `model_[1-5]_ptm`
   - Multimer: `model_[1-5]_multimer_v3`
   - SoloSeq: `seq_model_esm1b_ptm`

2. **FASTA Input**: 
   - Single sequence per file → Monomer (unless multimer preset)
   - Multiple sequences per file → Multimer or AlphaFold-Gap mode

3. **Database Configuration**:
   - Multimer requires UniProt and PDB SeqRes databases
   - SoloSeq can skip database searches entirely

The script automatically configures the appropriate `DataPipeline`, `AlignmentRunner`, and template featurizer based on these settings.

**Sources:** [run_pretrained_openfold.py:209-242](), [run_pretrained_openfold.py:267-280](), [run_pretrained_openfold.py:286-295]()

## Related Pages

For more detailed information on specific aspects of inference:

- **[Inference Pipeline Overview](#3.1)**: Complete walkthrough of `run_pretrained_openfold.py` workflow
- **[Monomer Inference](#3.2)**: Detailed guide for single-chain predictions
- **[Multimer Inference](#3.3)**: Multi-chain complex prediction specifics
- **[Single Sequence (SoloSeq) Inference](#3.4)**: MSA-free prediction with ESM embeddings  
- **[Jupyter Notebook Interface](#3.5)**: Interactive Colab-based prediction
- **[Performance Optimization](#3.6)**: Precision, kernels, tracing, and memory management
- **[Data Processing Pipeline](#6)**: Detailed feature generation pipeline
- **[Configuration System](#5.1)**: Model configuration and presets

**Sources:** [docs/source/Inference.md](), [docs/source/Multimer_Inference.md](), [docs/source/Single_Sequence_Inference.md]()

---