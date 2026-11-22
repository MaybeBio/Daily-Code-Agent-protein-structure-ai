# IgFoldRunner API

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [igfold/IgFoldRunner.py](igfold/IgFoldRunner.py)
- [igfold/utils/embed.py](igfold/utils/embed.py)
- [igfold/utils/folding.py](igfold/utils/folding.py)

</details>



The `IgFoldRunner` class provides the primary programmatic interface for antibody structure prediction and embedding generation using IgFold. This API encapsulates model loading, sequence processing, and prediction workflows in a convenient Python interface.

This documentation covers the core API methods `fold()` and `embed()` and their parameters. For interactive usage through Jupyter notebooks, see [Jupyter Notebook Interface](#4.2). For details on input data formats, see [Input Formats and Data Preparation](#4.3).

## Class Initialization

The `IgFoldRunner` class manages multiple pre-trained IgFold models and the AntiBERTy embedding model required for predictions.

### Constructor Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `num_models` | `int` | `4` | Number of pre-trained IgFold models to load (1-4) |
| `model_ckpts` | `List[str]` | `None` | Custom model checkpoint paths (overrides `num_models`) |
| `try_gpu` | `bool` | `True` | Whether to attempt GPU usage for acceleration |

### Initialization Process

```mermaid
flowchart TD
    init["IgFoldRunner.__init__()"] --> license["display_license()"]
    license --> check_ckpts{"model_ckpts provided?"}
    
    check_ckpts -->|Yes| load_custom["Load custom checkpoints"]
    check_ckpts -->|No| validate["Validate num_models (1-4)"]
    
    validate --> find_ckpts["Find pre-trained models in trained_models/IgFold/"]
    find_ckpts --> load_custom
    
    load_custom --> device_check["Detect CUDA device"]
    device_check --> load_igfold["Load IgFold models to device"]
    
    load_igfold --> load_antiberty["Load AntiBERTy model"]
    load_antiberty --> ready["IgFoldRunner ready"]
    
    style init fill:#f9f9f9
    style ready fill:#e8f5e8
```

Sources: [igfold/IgFoldRunner.py:26-76]()

## Core API Methods

### fold() Method

The `fold()` method performs complete antibody structure prediction, including coordinate generation, refinement, and PDB output.

#### Method Signature

```python
def fold(
    self,
    pdb_file,
    fasta_file=None,
    sequences=None,
    template_pdb=None,
    ignore_cdrs=None,
    ignore_chain=None,
    skip_pdb=False,
    do_refine=True,
    use_openmm=False,
    do_renum=True,
    truncate_sequences=False,
) -> IgFoldOutput
```

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `pdb_file` | `str` | Required | Output PDB file path |
| `fasta_file` | `str` | `None` | Input FASTA file containing sequences |
| `sequences` | `Dict[str, str]` | `None` | Dictionary mapping chain IDs to sequences |
| `template_pdb` | `str` | `None` | Template PDB file for structure guidance |
| `ignore_cdrs` | `List[str]` or `str` or `bool` | `None` | CDR regions to ignore in template |
| `ignore_chain` | `str` | `None` | Chain to ignore in template ("H" or "L") |
| `skip_pdb` | `bool` | `False` | Skip PDB file writing and processing |
| `do_refine` | `bool` | `True` | Perform structure refinement |
| `use_openmm` | `bool` | `False` | Use OpenMM instead of PyRosetta for refinement |
| `do_renum` | `bool` | `True` | Renumber output PDB using AbNumber |
| `truncate_sequences` | `bool` | `False` | Truncate sequences to antibody variable domains |

#### Processing Pipeline

```mermaid
flowchart TD
    fold_call["fold()"] --> get_seq["get_sequence_dict()"]
    get_seq --> trunc_check{"truncate_sequences?"}
    
    trunc_check -->|Yes| truncate["truncate_seq() via AbNumber"]
    trunc_check -->|No| create_fasta["Create FASTA file if needed"]
    truncate --> create_fasta
    
    create_fasta --> antiberty["AntiBERTy.embed()"]
    antiberty --> process_template["process_template()"]
    
    process_template --> create_input["Create IgFoldInput"]
    create_input --> model_ensemble["Run model ensemble"]
    
    model_ensemble --> select_best["Select best model by pRMSD"]
    select_best --> process_pred["process_prediction()"]
    
    process_pred --> refine_check{"do_refine?"}
    refine_check -->|Yes| refine_type{"use_openmm?"}
    refine_check -->|No| renum_check
    
    refine_type -->|Yes| openmm["OpenMM refinement"]
    refine_type -->|No| pyrosetta["PyRosetta refinement"]
    
    openmm --> renum_check{"do_renum?"}
    pyrosetta --> renum_check
    
    renum_check -->|Yes| abnumber["AbNumber renumbering"]
    renum_check -->|No| bfactor["Write B-factors"]
    abnumber --> bfactor
    
    bfactor --> return_output["Return IgFoldOutput"]
    
    style antiberty fill:#e1f5fe
    style model_ensemble fill:#fff3e0
    style openmm fill:#ffcc99
    style pyrosetta fill:#ffcc99
```

Sources: [igfold/IgFoldRunner.py:77-124](), [igfold/utils/folding.py:153-231]()

### embed() Method

The `embed()` method generates structural embeddings without full coordinate prediction, useful for analysis and feature extraction.

#### Method Signature

```python
def embed(
    self,
    model_idx=0,
    fasta_file=None,
    sequences=None,
    template_pdb=None,
    ignore_cdrs=None,
    ignore_chain=None,
) -> IgFoldOutput
```

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `model_idx` | `int` | `0` | Index of loaded model to use for embedding |
| `fasta_file` | `str` | `None` | Input FASTA file containing sequences |
| `sequences` | `Dict[str, str]` | `None` | Dictionary mapping chain IDs to sequences |
| `template_pdb` | `str` | `None` | Template PDB file for structure guidance |
| `ignore_cdrs` | `List[str]` or `str` or `bool` | `None` | CDR regions to ignore in template |
| `ignore_chain` | `str` | `None` | Chain to ignore in template ("H" or "L") |

#### Embedding Pipeline

```mermaid
flowchart TD
    embed_call["embed()"] --> get_seq_emb["get_sequence_dict()"]
    get_seq_emb --> antiberty_emb["AntiBERTy.embed()"]
    
    antiberty_emb --> process_template_emb["process_template()"]
    process_template_emb --> create_input_emb["Create IgFoldInput"]
    
    create_input_emb --> single_model["Run single IgFold model"]
    single_model --> reshape_prmsd["Reshape pRMSD output"]
    
    reshape_prmsd --> return_embeddings["Return embeddings + pRMSD"]
    
    style antiberty_emb fill:#e1f5fe
    style single_model fill:#fff3e0
```

Sources: [igfold/IgFoldRunner.py:126-158](), [igfold/utils/embed.py:7-53]()

## Parameter Details

### CDR Specification

The `ignore_cdrs` parameter accepts multiple formats:

- `False`: No CDRs ignored (include all)
- `List[str]`: Specific CDRs to ignore (e.g., `["h1", "h3", "l2"]`)
- `str`: Single CDR to ignore (e.g., `"h3"`)
- Default `None`: Uses default CDR masking

Valid CDR identifiers: `["h1", "h2", "h3", "l1", "l2", "l3"]`

### Input Source Priority

When both `sequences` and `fasta_file` are provided, the FASTA file takes precedence:

```mermaid
flowchart LR
    input_check{"Input provided?"} --> both["Both sequences + fasta_file"]
    input_check --> fasta_only["fasta_file only"]
    input_check --> seq_only["sequences only"]
    input_check --> none["Neither"]
    
    both --> use_fasta["Use FASTA file"]
    fasta_only --> use_fasta
    seq_only --> use_seq["Use sequences dict"]
    none --> error["Exit with error"]
    
    style use_fasta fill:#e8f5e8
    style error fill:#ffebee
```

Sources: [igfold/utils/folding.py:13-27]()

## Return Values

Both methods return an `IgFoldOutput` object containing:

| Attribute | Type | Description |
|-----------|------|-------------|
| `coords` | `torch.Tensor` | Predicted 3D coordinates |
| `prmsd` | `torch.Tensor` | Per-residue predicted RMSD values |
| `embeddings` | `torch.Tensor` | Structural embeddings (when requested) |
| Additional model outputs | Various | Intermediate representations and predictions |

## Usage Examples

### Basic Structure Prediction

```python
from igfold import IgFoldRunner

# Initialize runner
igfold = IgFoldRunner(num_models=2)

# Predict structure from sequences
sequences = {
    "H": "QVQLVQSGAEVKKPGASVKVSCKASGYTFT...",
    "L": "DIQMTQSPSSLSASVGDRVTITC..."
}

result = igfold.fold(
    pdb_file="antibody.pdb",
    sequences=sequences,
    do_refine=True,
    do_renum=True
)
```

### Template-Guided Prediction

```python
# Use template structure for guidance
result = igfold.fold(
    pdb_file="predicted.pdb",
    fasta_file="input.fasta",
    template_pdb="template.pdb",
    ignore_cdrs=["h3", "l3"],  # Ignore hypervariable regions
    do_refine=False
)
```

Sources: [igfold/IgFoldRunner.py:77-158]()

---