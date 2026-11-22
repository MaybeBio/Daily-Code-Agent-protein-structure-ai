# RFD3 Inference Pipeline

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.gitignore](.gitignore)
- [examples/all.ipynb](examples/all.ipynb)
- [models/rfd3/configs/inference_engine/base.yaml](models/rfd3/configs/inference_engine/base.yaml)
- [models/rfd3/src/rfd3/engine.py](models/rfd3/src/rfd3/engine.py)
- [models/rfd3/src/rfd3/inference/datasets.py](models/rfd3/src/rfd3/inference/datasets.py)
- [models/rfd3/src/rfd3/inference/input_parsing.py](models/rfd3/src/rfd3/inference/input_parsing.py)
- [models/rfd3/src/rfd3/inference/legacy_input_parsing.py](models/rfd3/src/rfd3/inference/legacy_input_parsing.py)
- [models/rfd3/src/rfd3/model/layers/chunked_pairwise.py](models/rfd3/src/rfd3/model/layers/chunked_pairwise.py)
- [models/rfd3/src/rfd3/model/layers/encoders.py](models/rfd3/src/rfd3/model/layers/encoders.py)
- [models/rfd3/src/rfd3/run_inference.py](models/rfd3/src/rfd3/run_inference.py)
- [models/rfd3/src/rfd3/trainer/rfd3.py](models/rfd3/src/rfd3/trainer/rfd3.py)
- [models/rfd3/src/rfd3/utils/inference.py](models/rfd3/src/rfd3/utils/inference.py)
- [models/rfd3/tests/test_bond_preservation_cases.py](models/rfd3/tests/test_bond_preservation_cases.py)
- [models/rfd3/tests/test_conditioning.py](models/rfd3/tests/test_conditioning.py)
- [models/rfd3/tests/test_legacy_ptm_bonds.py](models/rfd3/tests/test_legacy_ptm_bonds.py)
- [models/rfd3na/src/rfd3na/utils/inference.py](models/rfd3na/src/rfd3na/utils/inference.py)

</details>



This page documents the RFD3 inference pipeline architecture, detailing how inputs are processed, validated, and transformed into protein backbone designs. This covers the complete flow from input specification to final output generation.

For information about the RFD3 model architecture and diffusion sampling, see [4.3](). For input specification syntax and examples, see [4.2](). For training RFD3 models, see [4.6]().

## Overview

The RFD3 inference pipeline orchestrates the end-to-end process of generating protein backbones. It accepts flexible input specifications (JSON, YAML, CIF/PDB files, or programmatic objects), validates and normalizes them, constructs annotated atom arrays with conditioning information, passes them through the model's diffusion sampler, and produces structured outputs with metadata.

The pipeline enforces strict validation, supports batch processing, handles symmetry, and manages both regular diffusion and partial diffusion modes.

**Sources**: [models/rfd3/src/rfd3/engine.py:1-561](), [models/rfd3/src/rfd3/inference/input_parsing.py:1-124]()

---

## Core Components

### RFD3InferenceEngine

The `RFD3InferenceEngine` class is the main entry point for inference operations. It inherits from `BaseInferenceEngine` and coordinates all aspects of the inference workflow.

**Key Responsibilities:**
- Input canonicalization and specification management [models/rfd3/src/rfd3/engine.py:422-541]()
- Pipeline initialization and dataloader setup [models/rfd3/src/rfd3/engine.py:206-253]()
- Model forward passes and output generation [models/rfd3/src/rfd3/engine.py:272-333]()
- File I/O and checkpoint management [models/rfd3/src/rfd3/engine.py:103-134]()

**Key Methods:**
- `run()` - Main execution method accepting various input types [models/rfd3/src/rfd3/engine.py:206-333]()
- `_canonicalize_inputs()` - Normalizes inputs to specification dictionaries [models/rfd3/src/rfd3/engine.py:422-541]()
- `_multiply_specifications()` - Creates n_batches copies with skip-existing logic [models/rfd3/src/rfd3/engine.py:379-420]()
- `_model_forward()` - Executes model inference and packages outputs [models/rfd3/src/rfd3/engine.py:272-333]()

**Sources**: [models/rfd3/src/rfd3/engine.py:139-420]()

### RFD3InferenceConfig

Configuration dataclass storing all inference parameters:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `ckpt_path` | str \| Path | "rfd3" | Path to model checkpoint [models/rfd3/src/rfd3/engine.py:45-47]() |
| `diffusion_batch_size` | int | 16 | Number of samples per batch [models/rfd3/src/rfd3/engine.py:48]() |
| `skip_existing` | bool | True | Skip if output already exists [models/rfd3/src/rfd3/engine.py:51]() |
| `specification` | dict | {} | Per-example specification overrides [models/rfd3/src/rfd3/engine.py:53]() |
| `inference_sampler` | dict | {} | Sampler configuration overrides [models/rfd3/src/rfd3/engine.py:54]() |
| `cleanup_guideposts` | bool | True | Remove unindexed guideposts from output [models/rfd3/src/rfd3/engine.py:57]() |
| `cleanup_virtual_atoms` | bool | True | Remove virtual atoms from output [models/rfd3/src/rfd3/engine.py:58]() |
| `dump_trajectories` | bool | False | Save diffusion trajectories [models/rfd3/src/rfd3/engine.py:69]() |
| `low_memory_mode` | bool | False | Enable memory-efficient tokenization [models/rfd3/src/rfd3/engine.py:72-74]() |

**Sources**: [models/rfd3/src/rfd3/engine.py:43-89]()

### DesignInputSpecification

Pydantic model providing validated input specification with comprehensive validation logic. This is the canonical representation of a design task.

**Major Field Categories:**

1. **Data Inputs & Motif Selection** [models/rfd3/src/rfd3/inference/input_parsing.py:129-144]()
   - `input` - Path to PDB/CIF file
   - `atom_array_input` - Pre-loaded AtomArray (internal use)
   - `contig` - Indexed motif specification (InputSelection)
   - `unindex` - Unindexed motif components (InputSelection)
   - `length` - Length constraint string (e.g., "100-200")
   - `ligand` - Ligand names to include

2. **Conditioning Annotations** [models/rfd3/src/rfd3/inference/input_parsing.py:150-184]()
   - `select_fixed_atoms` - Atoms with fixed coordinates
   - `select_unfixed_sequence` - Residues with flexible sequence
   - `select_buried/partially_buried/exposed` - RASA bins
   - `select_hbond_acceptor/donor` - Hydrogen bond conditioning
   - `select_hotspots` - Hotspot atoms for PPI design

3. **Global Settings** [models/rfd3/src/rfd3/inference/input_parsing.py:186-213]()
   - `symmetry` - SymmetryConfig for symmetric assemblies
   - `ori_token` - Origin coordinates
   - `partial_t` - Noise level for partial diffusion
   - `plddt_enhanced` - Enable pLDDT enhancement
   - `is_non_loopy` - Encourage helical/sheet structure

**Sources**: [models/rfd3/src/rfd3/inference/input_parsing.py:113-777]()

### RFD3Output

Output dataclass encapsulating all results from a single design:

```python
@dataclass
class RFD3Output:
    atom_array: AtomArray              # Final predicted structure
    metadata: dict                      # Input spec, seed, checkpoint info
    example_id: str                     # Unique identifier
    denoised_trajectory_stack: Optional[AtomArrayStack]  # Forward trajectory
    noisy_trajectory_stack: Optional[AtomArrayStack]     # Noisy trajectory
```
[models/rfd3/src/rfd3/engine.py:90-97]()

The `dump()` method writes outputs to disk:
- `{example_id}.cif.gz` - Main structure file [models/rfd3/src/rfd3/engine.py:105-111]()
- `{example_id}.json` - Metadata including input specification [models/rfd3/src/rfd3/engine.py:112-114]()
- `{example_id}_denoised_model_{idx}.cif.gz` - Optional denoised trajectory [models/rfd3/src/rfd3/engine.py:119-125]()
- `{example_id}_noisy_model_{idx}.cif.gz` - Optional noisy trajectory [models/rfd3/src/rfd3/engine.py:127-133]()

**Sources**: [models/rfd3/src/rfd3/engine.py:90-138]()

---

## Inference Pipeline Flow

The following diagram maps the high-level inference flow to specific code entities within the `RFD3InferenceEngine` and `DesignInputSpecification`.

### Data Flow Diagram

```mermaid
graph TB
    subgraph "Input Layer"
        UserInput["User Inputs<br/>(JSON/YAML/CIF/PDB/<br/>DesignInputSpecification)"]
        ProcessInput["RFD3InferenceEngine._canonicalize_inputs()"]
        SpecDict["Dict[str, DesignInputSpecification]"]
    end
    
    subgraph "Validation & Building"
        Validate["DesignInputSpecification.safe_init()"]
        LoadAtom["inference_load_()"]
        ParseSelect["InputSelection.from_any()"]
        ValidateSchema["validate_input_schema()"]
        AssignTypes["_assign_types_to_input()"]
        BuildInit["DesignInputSpecification.build()"]
        ApplyPost["_apply_symmetry() / _set_origin()"]
    end
    
    subgraph "Pipeline Execution"
        ToInput["to_pipeline_input()"]
        Dataset["ContigJsonDataset.__getitem__()"]
        Transform["Transform Pipeline"]
        Loader["assemble_distributed_inference_loader_from_json()"]
    end
    
    subgraph "Model & Output"
        Forward["RFD3InferenceEngine._model_forward()"]
        BuildOutput["RFD3Output creation"]
        Dump["RFD3Output.dump()"]
    end
    
    UserInput --> ProcessInput
    ProcessInput --> SpecDict
    SpecDict --> Validate
    Validate --> LoadAtom
    Validate --> ParseSelect
    LoadAtom --> ValidateSchema
    ParseSelect --> ValidateSchema
    ValidateSchema --> AssignTypes
    AssignTypes --> BuildInit
    BuildInit --> ApplyPost
    ApplyPost --> ToInput
    ToInput --> Dataset
    Dataset --> Transform
    Transform --> Loader
    Loader --> Forward
    Forward --> BuildOutput
    BuildOutput --> Dump
```

**Sources**: [models/rfd3/src/rfd3/engine.py:206-333](), [models/rfd3/src/rfd3/inference/input_parsing.py:504-777](), [models/rfd3/src/rfd3/inference/datasets.py:156-173]()

---

## Input Processing Pipeline

### Input Canonicalization

The `_canonicalize_inputs()` method normalizes various input types into a unified dictionary structure [models/rfd3/src/rfd3/engine.py:422-541]().

```mermaid
graph LR
    subgraph "Input Types"
        JSON["JSON/YAML files"]
        Spec["DesignInputSpecification"]
        NullInput["None (unconditional)"]
    end
    
    subgraph "Processing"
        ProcessFunc["_canonicalize_inputs()"]
        MergeFunc["toolz.merge_with()"]
    end
    
    subgraph "Output"
        SpecDict["Dict[example_id, DesignInputSpecification]"]
    end
    
    JSON --> ProcessFunc
    Spec --> ProcessFunc
    NullInput --> ProcessFunc
    
    ProcessFunc --> MergeFunc
    MergeFunc --> SpecDict
```

**Key Logic:**
- Loads JSON/YAML and applies global overrides [models/rfd3/src/rfd3/engine.py:433-463]().
- Ensures relative paths in JSON files are converted to absolute paths using `ensure_input_is_abspath` [models/rfd3/src/rfd3/inference/datasets.py:163]().
- Generates unique example IDs based on file basenames and JSON keys [models/rfd3/src/rfd3/engine.py:448-463]().

**Sources**: [models/rfd3/src/rfd3/engine.py:422-541](), [models/rfd3/src/rfd3/inference/datasets.py:156-173]()

### Specification Multiplication

The `_multiply_specifications()` method creates multiple copies for batch sampling [models/rfd3/src/rfd3/engine.py:379-420]().

1. Scans the output directory to identify existing example IDs if `skip_existing=True` [models/rfd3/src/rfd3/engine.py:383-388]().
2. Iterates through requested `n_batches` [models/rfd3/src/rfd3/engine.py:397]().
3. Creates unique IDs for each batch (e.g., `id_batch_0`) [models/rfd3/src/rfd3/engine.py:403]().
4. Filters out specifications that have already been processed [models/rfd3/src/rfd3/engine.py:410-413]().

**Sources**: [models/rfd3/src/rfd3/engine.py:379-420]()

---

## DesignInputSpecification Building

The `DesignInputSpecification` class performs extensive validation and builds annotated atom arrays.

### Building Stages

1. **Pre-validation**: `validate_input_schema()` ensures mutual exclusivity of inputs (e.g., cannot specify both `input` and `length` for unconditional generation) [models/rfd3/src/rfd3/inference/input_parsing.py:234-315]().
2. **Input Loading**: `load_input()` uses `inference_load_()` to parse PDB/CIF files into Biotite `AtomArray` objects [models/rfd3/src/rfd3/inference/input_parsing.py:317-360]().
3. **Conditioning Assignment**: `_assign_types_to_input()` maps `InputSelection` strings to internal conditioning annotations [models/rfd3/src/rfd3/inference/input_parsing.py:419-498]().
4. **Structure Assembly**: `build()` iterates through contig components to construct the initial design state [models/rfd3/src/rfd3/inference/input_parsing.py:504-749]().

### Conditioning Annotation Assignment

Annotations are applied to the `AtomArray` during the building process:

| Selection Field | Annotation Name | Description |
|-----------------|-----------------|-------------|
| `select_fixed_atoms` | `is_motif_atom_with_fixed_coord` | Atoms with frozen 3D coordinates [models/rfd3/src/rfd3/inference/input_parsing.py:423-426]() |
| `select_unfixed_sequence` | `is_motif_atom_with_fixed_seq` | Residues where the model samples sequence [models/rfd3/src/rfd3/inference/input_parsing.py:428-431]() |
| `unindex` | `is_motif_atom_unindexed` | Motif components without fixed sequence positions [models/rfd3/src/rfd3/inference/input_parsing.py:133-137]() |
| `select_buried` | `rasa_bin` | Forces RASA bin 0 (buried) [models/rfd3/src/rfd3/inference/input_parsing.py:433-436]() |
| `select_hotspots` | `is_atom_level_hotspot` | Marks hotspot atoms for PPI design [models/rfd3/src/rfd3/inference/input_parsing.py:453-456]() |

**Sources**: [models/rfd3/src/rfd3/inference/input_parsing.py:419-498](), [models/rfd3/src/rfd3/utils/inference.py:53-84]()

---

## Dataset and DataLoader

### ContigJsonDataset

The `ContigJsonDataset` class enables efficient loading of design tasks from JSON/YAML files [models/rfd3/src/rfd3/inference/datasets.py:31-173]().

- **Lazy Loading**: `__getitem__` initializes the `DesignInputSpecification` and builds the `AtomArray` on-demand [models/rfd3/src/rfd3/inference/datasets.py:156-168]().
- **Pipeline Preparation**: Calls `to_pipeline_input()` to convert the `AtomArray` into a dictionary of features ready for model transforms [models/rfd3/src/rfd3/inference/datasets.py:168]().

### Distributed Inference

The `assemble_distributed_inference_loader_from_json()` function creates a `DataLoader` that respects DDP rank and world size [models/rfd3/src/rfd3/inference/datasets.py:175-194]().

- Uses `SequentialSampler` to ensure deterministic ordering [models/rfd3/src/rfd3/inference/datasets.py:187]().
- Rank-based splitting ensures each GPU processes a unique subset of designs [models/rfd3/src/rfd3/inference/datasets.py:188-193]().

**Sources**: [models/rfd3/src/rfd3/inference/datasets.py:31-194]()

---

## Model Execution and Trajectories

### Model Forward Pass

The `_model_forward()` method executes the actual inference [models/rfd3/src/rfd3/engine.py:272-333]().

1. Moves batch data to the correct device using `fabric.to_device()` [models/rfd3/src/rfd3/engine.py:273]().
2. Calls `trainer.validation_step()` which invokes the `ConditionalDiffusionSampler` [models/rfd3/src/rfd3/engine.py:275]().
3. Collects predicted coordinates, metadata, and optional trajectories [models/rfd3/src/rfd3/engine.py:276-284]().

### Trajectory Processing

If `dump_trajectories` is enabled, the engine reshapes and aligns the diffusion steps [models/rfd3/src/rfd3/engine.py:286-318]().

- **Subsampling**: Trajectories are limited to 100 frames to save space [models/rfd3/src/rfd3/engine.py:545]().
- **Alignment**: If `align_trajectory_structures=True`, frames are aligned to the final prediction using `weighted_rigid_align()` [models/rfd3/src/rfd3/engine.py:295-310]().
- **Stacking**: `build_stack_from_atom_array_and_batched_coords()` converts raw coordinates into a `biotite.structure.AtomArrayStack` [models/rfd3/src/rfd3/engine.py:312-317]().

**Sources**: [models/rfd3/src/rfd3/engine.py:272-333](), [models/rfd3/src/rfd3/utils/io.py:34]()

---

## Output Generation

The `RFD3Output` object manages the persistence of results [models/rfd3/src/rfd3/engine.py:90-138]().

### File Formats

- **CIF**: Structures are saved using `to_cif_file()` with `extra_fields=SAVED_CONDITIONING_ANNOTATIONS` to preserve conditioning info for inspection [models/rfd3/src/rfd3/engine.py:105-111]().
- **JSON**: Metadata containing the full input specification, seed, and model parameters is dumped for reproducibility [models/rfd3/src/rfd3/engine.py:112-114]().

### Cleanup Operations

The pipeline performs automated cleanup before saving unless disabled for debugging [models/rfd3/src/rfd3/trainer/rfd3.py:65-68]():
- **Guideposts**: Removes virtual tokens used for unindexed components [models/rfd3/src/rfd3/engine.py:57]().
- **Virtual Atoms**: Removes internal model atoms (e.g., atom14 representations) to produce standard PDB-compatible outputs [models/rfd3/src/rfd3/engine.py:58]().

**Sources**: [models/rfd3/src/rfd3/engine.py:90-138](), [models/rfd3/src/rfd3/trainer/rfd3.py:61-74]()

---