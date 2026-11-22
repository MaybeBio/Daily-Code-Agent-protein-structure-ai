# Complete Design Pipeline

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [docs/_static/superimposed_80_residue_protein.png](docs/_static/superimposed_80_residue_protein.png)
- [examples/all.ipynb](examples/all.ipynb)
- [examples/ipd_design_pipeline_collab.ipynb](examples/ipd_design_pipeline_collab.ipynb)
- [models/mpnn/README.md](models/mpnn/README.md)
- [models/mpnn/src/mpnn/__init__.py](models/mpnn/src/mpnn/__init__.py)
- [models/mpnn/src/mpnn/loss/nll_loss.py](models/mpnn/src/mpnn/loss/nll_loss.py)
- [models/mpnn/src/mpnn/utils/inference.py](models/mpnn/src/mpnn/utils/inference.py)
- [models/rfd3/src/rfd3/engine.py](models/rfd3/src/rfd3/engine.py)
- [models/rfd3/src/rfd3/inference/datasets.py](models/rfd3/src/rfd3/inference/datasets.py)
- [models/rfd3/src/rfd3/utils/inference.py](models/rfd3/src/rfd3/utils/inference.py)
- [models/rfd3na/src/rfd3na/utils/inference.py](models/rfd3na/src/rfd3na/utils/inference.py)

</details>



## Purpose and Scope

This page documents the end-to-end protein design workflow that combines three deep learning models in sequence: **RFdiffusion3 (RFD3)** for backbone generation, **ProteinMPNN/LigandMPNN** for sequence design, and **RosettaFold3 (RF3)** for structure validation. The pipeline produces novel protein designs and assesses their designability through RMSD comparison between the generated backbone and the predicted structure from the designed sequence.

For detailed documentation on individual models, see **RFD3 Overview**, **MPNN Overview**, and **RF3 Overview**. For model-specific inference parameters, see **RFD3 Inference Pipeline**, **MPNN Inference**, and **RF3 Inference**.

**Sources:** [examples/all.ipynb:8-21]()

---

## Pipeline Overview

The complete design pipeline follows a linear three-step process where each model's output serves as input to the next:

### Pipeline Logic and Data Flow
```mermaid
graph LR
    Input["Design Specification<br/>(length, constraints)"]
    
    RFD3["RFD3InferenceEngine<br/>Diffusion Sampling"]
    RFD3Out["Protein Backbone<br/>AtomArray"]
    
    MPNN["MPNNInferenceEngine<br/>Sequence Design"]
    MPNNOut["Designed Sequences<br/>AtomArray + residue names"]
    
    RF3["RF3InferenceEngine<br/>Structure Prediction"]
    RF3Out["Predicted Structure<br/>AtomArray + confidences"]
    
    Validate["RMSD Calculation<br/>biotite.structure.rmsd"]
    Result["Designability Score<br/>< 2Å = good"]
    
    Input --> RFD3
    RFD3 --> RFD3Out
    RFD3Out --> MPNN
    MPNN --> MPNNOut
    MPNNOut --> RF3
    RF3 --> RF3Out
    
    RFD3Out -.->|superimpose| Validate
    RF3Out -.->|compare| Validate
    Validate --> Result
```

**Sources:** [examples/all.ipynb:24-27]()

---

## Step 1: Backbone Generation with RFD3

The first step generates novel protein backbone structures using RFdiffusion3's conditional diffusion process.

### Configuration and Execution

```mermaid
graph TB
    Config["RFD3InferenceConfig"]
    Spec["specification dict<br/>length, extra"]
    
    Engine["RFD3InferenceEngine"]
    Model["Diffusion Model<br/>checkpoint loaded"]
    
    Run["engine.run()"]
    Output["RFD3Output objects<br/>dict[str, list]"]
    AtomArray["atom_array field<br/>biotite.structure.AtomArray"]
    
    Config --> Spec
    Config --> Engine
    Engine --> Model
    Engine --> Run
    Run --> Output
    Output --> AtomArray
```

The `RFD3InferenceConfig` accepts a `specification` dictionary defining the design parameters:

| Parameter | Type | Description |
|-----------|------|-------------|
| `length` | int | Target protein length in residues | [examples/all.ipynb:93-93]() |
| `diffusion_batch_size` | int | Number of structures to generate per batch | [models/rfd3/src/rfd3/engine.py:48-48]() |
| `extra` | dict | Additional conditioning specifications | [examples/all.ipynb:94-94]() |

**Key Classes:**
- `RFD3InferenceEngine` [models/rfd3/src/rfd3/engine.py:139-140](): Manages model loading and inference execution.
- `RFD3InferenceConfig` [models/rfd3/src/rfd3/engine.py:43-44](): Configuration dataclass for RFD3 inference.
- `RFD3Output` [models/rfd3/src/rfd3/engine.py:90-91](): Contains `atom_array` field with generated backbone.

**Example Usage:**
The engine initializes from a checkpoint path (or registered model name), loads the diffusion model, and executes sampling:
[examples/all.ipynb:84-106]()

**Output Structure:**
The `run()` method returns a dictionary mapping batch identifiers to lists of `RFD3Output` objects. Each output contains an `atom_array` (Biotite `AtomArray`) and generation `metadata` [models/rfd3/src/rfd3/engine.py:91-94]().

**Sources:** [examples/all.ipynb:63-140](), [models/rfd3/src/rfd3/engine.py:139-205]()

---

## Step 2: Sequence Design with MPNN

The second step designs amino acid sequences that will fold into the generated backbone structure.

### Engine Configuration

The `MPNNInferenceEngine` constructor accepts global parameters that apply to all inputs:

| Parameter | Type | Description |
|-----------|------|-------------|
| `model_type` | str | `"protein_mpnn"` or `"ligand_mpnn"` | [models/mpnn/src/mpnn/utils/inference.py:39-40]() |
| `checkpoint_path` | str | Path to model weights | [models/mpnn/src/mpnn/utils/inference.py:39-39]() |
| `is_legacy_weights` | bool | Whether checkpoint uses legacy weight format | [models/mpnn/src/mpnn/utils/inference.py:41-41]() |
| `out_directory` | str \| None | Directory for output files | [models/mpnn/src/mpnn/utils/inference.py:43-43]() |

**Per-Input Configuration:**
Each structure accepts independent design parameters via `input_dicts`:

| Parameter | Type | Description |
|-----------|------|-------------|
| `batch_size` | int | Number of sequences to generate | [models/mpnn/src/mpnn/utils/inference.py:54-54]() |
| `temperature` | float | Sampling temperature | [models/mpnn/src/mpnn/utils/inference.py:84-84]() |
| `designed_residues` | list[str] | Residue IDs to design | [models/mpnn/src/mpnn/utils/inference.py:73-73]() |
| `remove_waters` | bool | Remove water molecules from context | [models/mpnn/src/mpnn/utils/inference.py:58-58]() |

**Sources:** [models/mpnn/src/mpnn/utils/inference.py:35-90](), [examples/all.ipynb:169-192]()

### Data Flow Through MPNN

```mermaid
graph LR
    Input["AtomArray from RFD3"]
    
    InputDict["input_dict<br/>design parameters"]
    
    MPNNInput["MPNNInferenceInput<br/>from_atom_array_and_dict()"]
    
    Annotate["Annotate AtomArray<br/>mpnn_designed_residue_mask<br/>mpnn_temperature<br/>mpnn_bias"]
    
    Pipeline["Transform Pipeline<br/>FeaturizeUserSettings"]
    
    Collate["FeatureCollator<br/>batch network inputs"]
    
    Forward["model.forward()"]
    
    Decode["Decode Sequences<br/>S_sampled tensor"]
    
    Output["MPNNInferenceOutput<br/>list per design"]
    
    Input --> MPNNInput
    InputDict --> MPNNInput
    MPNNInput --> Annotate
    Annotate --> Pipeline
    Pipeline --> Collate
    Collate --> Forward
    Forward --> Decode
    Decode --> Output
```

**Model Execution:**
The engine executes the model through its `run` method, which handles featurization, model forward pass, and sequence sampling [examples/all.ipynb:191-192]().

**Sources:** [examples/all.ipynb:149-216](), [models/mpnn/src/mpnn/utils/inference.py:35-90]()

---

## Step 3: Structure Validation with RF3

The third step predicts the 3D structure from the designed sequence to validate that it folds into the intended backbone.

### RF3 Inference Configuration

```mermaid
graph TB
    Input["Designed Sequence<br/>AtomArray from MPNN"]
    
    InfInput["InferenceInput<br/>from_atom_array()"]
    ExampleID["example_id<br/>structure identifier"]
    
    Engine["RF3InferenceEngine"]
    CheckpointPath["ckpt_path<br/>rf3 / path to weights"]
    
    Pipeline["Transform Pipeline<br/>MSA processing<br/>feature extraction"]
    
    Model["RoseTTAFold3 Model<br/>Evoformer + Structure Module"]
    
    Output["RF3Output objects<br/>dict[example_id, list]"]
    
    AtomArray["atom_array<br/>predicted structure"]
    SummaryConf["summary_confidences<br/>pLDDT, pTM, PAE, ranking_score"]
    Confidences["confidences<br/>per-atom/residue metrics"]
    
    Input --> InfInput
    ExampleID --> InfInput
    InfInput --> Engine
    
    CheckpointPath --> Engine
    Engine --> Pipeline
    Engine --> Model
    Model --> Output
    
    Output --> AtomArray
    Output --> SummaryConf
    Output --> Confidences
```

**Input Construction:**
The `InferenceInput.from_atom_array()` method creates RF3 inputs from MPNN outputs [examples/all.ipynb:252-260]().

**Confidence Metrics:**
RF3 produces comprehensive confidence scores including `overall_plddt`, `ptm`, `iptm`, and `ranking_score` [examples/all.ipynb:294-305]().

**Sources:** [examples/all.ipynb:225-327]()

---

## Step 4: Designability Assessment via RMSD

The final step quantifies design success by comparing the RFD3-generated backbone against the RF3-predicted structure.

### RMSD Calculation Workflow

```mermaid
graph TB
    Generated["RFD3 Generated Backbone<br/>aa_generated"]
    Refolded["RF3 Predicted Structure<br/>aa_refolded"]
    
    Filter["Filter to Backbone Atoms<br/>N, CA, C, O"]
    BBGen["bb_generated<br/>backbone atoms only"]
    BBRefold["bb_refolded<br/>backbone atoms only"]
    
    Superimpose["biotite.structure.superimpose<br/>fit structures"]
    Fitted["bb_refolded_fitted<br/>aligned to bb_generated"]
    
    RMSD["biotite.structure.rmsd<br/>calculate deviation"]
    Score["RMSD Value (Å)"]
    
    Interpret["Interpretation"]
    Excellent["< 1.0 Å: Excellent<br/>High designability"]
    Good["1.0-2.0 Å: Good<br/>Likely designable"]
    Moderate["> 2.0 Å: Moderate<br/>May not fold correctly"]
    
    Generated --> Filter
    Refolded --> Filter
    Filter --> BBGen
    Filter --> BBRefold
    
    BBGen --> Superimpose
    BBRefold --> Superimpose
    Superimpose --> Fitted
    
    BBGen --> RMSD
    Fitted --> RMSD
    RMSD --> Score
    
    Score --> Interpret
    Interpret --> Excellent
    Interpret --> Good
    Interpret --> Moderate
```

**Implementation:**
The RMSD calculation uses Biotite's structure comparison functions [examples/all.ipynb:343-366]().

**RMSD Thresholds:**

| RMSD Range | Designability | Interpretation |
|------------|---------------|----------------|
| < 1.0 Å | Excellent | Designed sequence very likely folds to target |
| 1.0 - 2.0 Å | Good | Designed sequence likely folds to target |
| > 2.0 Å | Moderate/Poor | Redesign or further validation recommended |

**Sources:** [examples/all.ipynb:334-366]()

---

## Data Format Conversions

The pipeline relies on `biotite.structure.AtomArray` as the universal data structure for passing molecular information between models.

### AtomArray as Common Currency

```mermaid
graph LR
    RFD3Out["RFD3Output<br/>atom_array field"]
    AtomArray1["AtomArray<br/>backbone coordinates<br/>chain_id, res_id annotations"]
    
    MPNNIn["MPNNInferenceInput<br/>atom_array + input_dict"]
    Annotated["AtomArray<br/>+ mpnn_designed_residue_mask<br/>+ mpnn_temperature<br/>+ mpnn_bias"]
    
    MPNNOut["MPNNInferenceOutput<br/>atom_array field"]
    Updated["AtomArray<br/>updated res_name<br/>designed sequence applied"]
    
    RF3In["InferenceInput<br/>from_atom_array()"]
    RF3AtomArray["AtomArray<br/>sequence extracted<br/>chain info preserved"]
    
    RF3Out["RF3Output<br/>atom_array field"]
    Predicted["AtomArray<br/>predicted structure<br/>b_factor = pLDDT"]
    
    RFD3Out --> AtomArray1
    AtomArray1 --> MPNNIn
    MPNNIn --> Annotated
    Annotated --> MPNNOut
    MPNNOut --> Updated
    Updated --> RF3In
    RF3In --> RF3AtomArray
    RF3AtomArray --> RF3Out
    RF3Out --> Predicted
```

**Sources:** [examples/all.ipynb:128-140](), [models/rfd3/src/rfd3/engine.py:90-94](), [models/mpnn/src/mpnn/utils/inference.py:24-30]()

---

## Sources
- [examples/all.ipynb:1-426]() - Complete pipeline walkthrough.
- [models/rfd3/src/rfd3/engine.py:1-205]() - RFD3 Inference Engine and configuration.
- [models/mpnn/src/mpnn/utils/inference.py:1-90]() - MPNN inference defaults and parameter specifications.
- [models/rfd3/src/rfd3/utils/inference.py:53-84]() - Annotation utilities for structure arrays.
- [models/mpnn/src/mpnn/loss/nll_loss.py:1-123]() - Model loss and sequence evaluation logic.

---