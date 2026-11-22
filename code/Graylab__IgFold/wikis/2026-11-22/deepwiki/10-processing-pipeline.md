# Processing Pipeline

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [igfold/utils/embed.py](igfold/utils/embed.py)
- [igfold/utils/folding.py](igfold/utils/folding.py)

</details>



This document covers IgFold's structure prediction pipeline, detailing the sequence of operations that transform antibody sequences into predicted 3D structures. The pipeline orchestrates input processing, sequence embeddings, model inference, and output generation through a series of well-defined stages.

For information about the neural network model components used within this pipeline, see [IgFold Model](#5.1). For details about the data processing utilities that support the pipeline, see [Data Processing Utilities](#5.3).

## Pipeline Overview

The IgFold processing pipeline consists of two main entry points: the `fold()` function for complete structure prediction and the `embed()` function for embedding generation only. Both pipelines share common input processing stages but differ in their outputs and post-processing steps.

### Main Pipeline Flow

```mermaid
flowchart TD
    INPUT[Input Sequences] --> GET_SEQ_DICT["get_sequence_dict()"]
    FASTA[FASTA File] --> GET_SEQ_DICT
    
    GET_SEQ_DICT --> SEQ_DICT["Sequence Dictionary"]
    
    TEMPLATE_PDB[Template PDB] --> PROCESS_TEMPLATE["process_template()"]
    SEQ_DICT --> PROCESS_TEMPLATE
    
    PROCESS_TEMPLATE --> TEMP_COORDS["Template Coordinates"]
    PROCESS_TEMPLATE --> TEMP_MASK["Template Mask"]
    
    SEQ_DICT --> ANTIBERTY["AntiBERTy Embedding"]
    ANTIBERTY --> EMBEDDINGS["Embeddings"]
    ANTIBERTY --> ATTENTIONS["Attentions"]
    
    EMBEDDINGS --> IGFOLD_INPUT["IgFoldInput Object"]
    ATTENTIONS --> IGFOLD_INPUT
    TEMP_COORDS --> IGFOLD_INPUT
    TEMP_MASK --> IGFOLD_INPUT
    
    IGFOLD_INPUT --> MODEL_INFERENCE["Model Inference Loop"]
    MODEL_INFERENCE --> ENSEMBLE_SELECTION["Best Model Selection"]
    
    ENSEMBLE_SELECTION --> PROCESS_PRED["process_prediction()"]
    PROCESS_PRED --> PDB_OUTPUT["PDB Output"]
    PROCESS_PRED --> REFINED_STRUCTURE["Refined Structure"]
```

*Sources: [igfold/utils/folding.py:153-231](), [igfold/utils/embed.py:7-53]()*

### Function-Level Architecture

```mermaid
graph TD
    subgraph "Entry Points"
        FOLD_FUNC["fold()"]
        EMBED_FUNC["embed()"]
    end
    
    subgraph "Input Processing"
        GET_SEQ["get_sequence_dict()"]
        PROC_TEMPLATE["process_template()"]
    end
    
    subgraph "Model Interface"
        IGFOLD_INPUT_CLASS["IgFoldInput"]
        MODEL_CALL["model(model_in)"]
        GRADIENT_REFINE["model.gradient_refine()"]
    end
    
    subgraph "Post Processing"
        PROC_PREDICTION["process_prediction()"]
        SAVE_PDB["save_PDB()"]
        WRITE_BFACTOR["write_pdb_bfactor()"]
    end
    
    subgraph "Optional Refinement"
        OPENMM_REF["OpenMM refine()"]
        PYROSETTA_REF["PyRosetta refine()"]
        RENUMBER_PDB["renumber_pdb()"]
    end
    
    FOLD_FUNC --> GET_SEQ
    EMBED_FUNC --> GET_SEQ
    
    FOLD_FUNC --> PROC_TEMPLATE
    EMBED_FUNC --> PROC_TEMPLATE
    
    GET_SEQ --> IGFOLD_INPUT_CLASS
    PROC_TEMPLATE --> IGFOLD_INPUT_CLASS
    
    IGFOLD_INPUT_CLASS --> MODEL_CALL
    MODEL_CALL --> GRADIENT_REFINE
    
    FOLD_FUNC --> PROC_PREDICTION
    PROC_PREDICTION --> SAVE_PDB
    PROC_PREDICTION --> WRITE_BFACTOR
    
    PROC_PREDICTION --> OPENMM_REF
    PROC_PREDICTION --> PYROSETTA_REF
    PROC_PREDICTION --> RENUMBER_PDB
```

*Sources: [igfold/utils/folding.py:13-232](), [igfold/utils/embed.py:7-53]()*

## Input Processing

The pipeline begins with sequence input processing through the `get_sequence_dict()` function, which handles multiple input formats and validates the provided data.

### Sequence Input Handling

| Input Type | Processing Method | Output |
|------------|-------------------|--------|
| Direct sequences | Use provided dictionary | `seq_dict` |
| FASTA file | Parse via `get_fasta_chain_dict()` | `seq_dict` |
| Both provided | Prioritize FASTA file with warning | `seq_dict` |
| Neither provided | Exit with error | - |

The function implements a priority system where FASTA files take precedence over direct sequence input when both are provided [igfold/utils/folding.py:13-27]().

### Optional Sequence Truncation

When `truncate_sequences=True`, the pipeline utilizes AbNumber integration to trim sequences to their canonical regions:

```mermaid
flowchart LR
    RAW_SEQ["Raw Sequences"] --> TRUNCATE["truncate_seq()"]
    TRUNCATE --> CANONICAL_SEQ["Canonical Sequences"]
    CANONICAL_SEQ --> EMBEDDING["AntiBERTy Embedding"]
```

This feature requires AbNumber installation and processes each sequence through the `truncate_seq()` function [igfold/utils/folding.py:173-179]().

*Sources: [igfold/utils/folding.py:13-27](), [igfold/utils/folding.py:173-179]()*

## Embedding Generation

The pipeline generates sequence embeddings and attention maps using the AntiBERTy model through a standardized interface.

### AntiBERTy Processing

```mermaid
flowchart TD
    SEQ_VALUES["seq_dict.values()"] --> ANTIBERTY["antiberty.embed()"]
    ANTIBERTY --> RAW_EMBEDDINGS["Raw Embeddings"]
    ANTIBERTY --> RAW_ATTENTIONS["Raw Attentions"]
    
    RAW_EMBEDDINGS --> TRIM_EMB["[1:-1] Trim CLS/SEP"]
    RAW_ATTENTIONS --> TRIM_ATT["[:,∶,1:-1,1:-1] Trim"]
    
    TRIM_EMB --> UNSQUEEZE_EMB["unsqueeze(0)"]
    TRIM_ATT --> UNSQUEEZE_ATT["unsqueeze(0)"]
    
    UNSQUEEZE_EMB --> FINAL_EMBEDDINGS["Final Embeddings"]
    UNSQUEEZE_ATT --> FINAL_ATTENTIONS["Final Attentions"]
```

The embedding process strips special tokens (`[CLS]` and `[SEP]`) and adds batch dimensions to prepare data for model input [igfold/utils/folding.py:190-195]().

*Sources: [igfold/utils/folding.py:190-195](), [igfold/utils/embed.py:22-27]()*

## Template Processing

Optional template PDB files are processed through the `process_template()` function, which extracts coordinates and applies masking based on user specifications.

### Template Coordinate Extraction

```mermaid
flowchart TD
    TEMPLATE_PDB["Template PDB"] --> GET_COORDS["get_atom_coords()"]
    GET_COORDS --> ATOM_COORDS["N, CA, C, CB Coordinates"]
    
    ATOM_COORDS --> STACK_COORDS["torch.stack() + reshape"]
    STACK_COORDS --> TEMP_COORDS["Template Coordinates"]
    
    TEMP_COORDS --> CREATE_MASK["Create Boolean Mask"]
    CREATE_MASK --> INVALID_CHECK["Check NaN & Zero Values"]
    INVALID_CHECK --> TEMP_MASK["Template Mask"]
    
    CDR_IGNORE["ignore_cdrs parameter"] --> CDR_MASKING["CDR Region Masking"]
    CHAIN_IGNORE["ignore_chain parameter"] --> CHAIN_MASKING["Chain Masking"]
    
    CDR_MASKING --> TEMP_MASK
    CHAIN_MASKING --> TEMP_MASK
```

### Template Masking Options

The pipeline supports selective template masking through two parameters:

- **CDR Masking**: `ignore_cdrs` parameter accepts boolean, string, or list values to mask specific CDR regions [igfold/utils/folding.py:54-66]()
- **Chain Masking**: `ignore_chain` parameter masks entire heavy ("H") or light ("L") chains [igfold/utils/folding.py:67-73]()

*Sources: [igfold/utils/folding.py:30-75]()*

## Model Inference

The core prediction phase involves creating an `IgFoldInput` object and running inference through an ensemble of models.

### Model Input Construction

```mermaid
flowchart LR
    EMBEDDINGS["Processed Embeddings"] --> IGFOLD_INPUT["IgFoldInput()"]
    ATTENTIONS["Processed Attentions"] --> IGFOLD_INPUT
    TEMP_COORDS["Template Coordinates"] --> IGFOLD_INPUT
    TEMP_MASK["Template Mask"] --> IGFOLD_INPUT
    
    IGFOLD_INPUT --> MODEL_INPUT["Model Input Object"]
    MODEL_INPUT --> INFERENCE["Model Inference Loop"]
```

### Ensemble Prediction Loop

The pipeline runs multiple models and selects the best prediction based on quantile scoring:

| Step | Operation | Output |
|------|-----------|--------|
| 1 | Forward pass: `model(model_in)` | Raw predictions |
| 2 | Gradient refinement: `model.gradient_refine()` | Refined coordinates |
| 3 | Score calculation: `prmsd.quantile(0.9)` | Quality score |
| 4 | Best model selection: `min(scores)` | Final prediction |

The scoring mechanism uses the 90th percentile of predicted RMSD values to identify the most confident prediction [igfold/utils/folding.py:211-220]().

*Sources: [igfold/utils/folding.py:203-220](), [igfold/utils/embed.py:35-44]()*

## Post-Processing and Output

The `process_prediction()` function handles model output formatting, structure refinement, and file generation.

### Output Processing Flow

```mermaid
flowchart TD
    MODEL_OUT["Model Output"] --> REARRANGE_PRMSD["Rearrange pRMSD"]
    REARRANGE_PRMSD --> COORDS_EXTRACT["Extract Coordinates"]
    COORDS_EXTRACT --> CALC_RMSD["Calculate Residue RMSD"]
    
    CALC_RMSD --> SAVE_PDB_CALL["save_PDB()"]
    SAVE_PDB_CALL --> PDB_STRING["PDB String"]
    
    PDB_STRING --> REFINE_CHECK{"do_refine?"}
    REFINE_CHECK -->|Yes| REFINE_CHOICE{"use_openmm?"}
    REFINE_CHECK -->|No| RENUM_CHECK{"do_renum?"}
    
    REFINE_CHOICE -->|Yes| OPENMM_REF["OpenMM Refinement"]
    REFINE_CHOICE -->|No| PYROSETTA_REF["PyRosetta Refinement"]
    
    OPENMM_REF --> RENUM_CHECK
    PYROSETTA_REF --> RENUM_CHECK
    
    RENUM_CHECK -->|Yes| RENUMBER["renumber_pdb()"]
    RENUM_CHECK -->|No| BFACTOR_WRITE["write_pdb_bfactor()"]
    
    RENUMBER --> BFACTOR_WRITE
    BFACTOR_WRITE --> FINAL_PDB["Final PDB Output"]
```

### Refinement Options

The pipeline supports two refinement backends:

- **OpenMM**: Physics-based energy minimization [igfold/utils/folding.py:118-123]()
- **PyRosetta**: Rosetta-based structure optimization [igfold/utils/folding.py:125-131]()

Both refinement methods require separate installation and are imported dynamically with error handling for missing dependencies.

### Output File Generation

The pipeline generates several output files:

| File Type | Content | Function |
|-----------|---------|----------|
| PDB | 3D coordinates with atoms N, CA, C, CB, O | `save_PDB()` |
| FASTA | Sequence information (auto-generated if needed) | Direct file writing |
| B-factor PDB | Structure with confidence scores | `write_pdb_bfactor()` |

*Sources: [igfold/utils/folding.py:78-150]()*

## Pipeline Variants

The system provides two main pipeline variants optimized for different use cases:

### Structure Prediction Pipeline (`fold()`)
- Complete structure prediction workflow
- Optional template integration
- Ensemble model scoring
- Structure refinement and renumbering
- Full PDB output generation

### Embedding Pipeline (`embed()`)
- Embeddings and attention extraction only
- Minimal post-processing
- Returns `IgFoldOutput` with embedding data
- Useful for downstream analysis or custom modeling

The embedding pipeline shares input processing with the full pipeline but bypasses refinement and file generation steps [igfold/utils/embed.py:7-53]().

*Sources: [igfold/utils/folding.py:153-231](), [igfold/utils/embed.py:7-53]()*

---