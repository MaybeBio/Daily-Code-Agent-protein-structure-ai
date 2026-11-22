# MPNN Overview

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [docs/source/installation_faq.md](docs/source/installation_faq.md)
- [models/mpnn/README.md](models/mpnn/README.md)
- [models/mpnn/docs/index.md](models/mpnn/docs/index.md)
- [models/mpnn/src/mpnn/__init__.py](models/mpnn/src/mpnn/__init__.py)
- [models/mpnn/src/mpnn/loss/nll_loss.py](models/mpnn/src/mpnn/loss/nll_loss.py)
- [models/mpnn/src/mpnn/utils/inference.py](models/mpnn/src/mpnn/utils/inference.py)

</details>



## Purpose and Scope

This document introduces ProteinMPNN and LigandMPNN (collectively referred to as MPNN), which provide fixed-backbone sequence design capabilities within the Foundry framework. MPNN models take protein backbone structures as input and generate amino acid sequences that are predicted to fold into those structures. This page covers the model variants, core capabilities, and system architecture.

MPNN in Foundry is a re-implementation of the original models within the `modelforge`/`atomworks` framework, supporting both legacy weights and newly trained checkpoints [models/mpnn/README.md:9-16]().

**Sources:** [models/mpnn/README.md:1-16]()

## Model Variants

MPNN is available in variants designed for different chemical contexts:

| Model Type | Purpose | Key Features |
|------------|---------|--------------|
| **ProteinMPNN** | Protein-only sequence design | Designs sequences for protein backbones; ignores non-protein context [models/mpnn/README.md:9-12](). |
| **LigandMPNN** | Ligand-aware sequence design | Incorporates atomic context from small molecules, ions, and nucleic acids [models/mpnn/README.md:13-14](). |
| **SolubleMPNN** | Soluble protein design | Specifically trained for designing soluble analogues of membrane proteins [models/mpnn/README.md:14-15](). |

The model type is specified via the `model_type` parameter in the inference configuration [models/mpnn/src/mpnn/utils/inference.py:138-144]().

**Sources:** [models/mpnn/README.md:9-15](), [models/mpnn/src/mpnn/utils/inference.py:138-144]()

## Core Capabilities

### Fixed-Backbone Design
MPNN performs inverse folding, sampling amino acid sequences for a fixed set of backbone coordinates [models/mpnn/README.md:9-10]().

### Selective Design Control
Users define the design scope through several mechanisms:
- **Masking**: `designed_residues` or `fixed_residues` lists [models/mpnn/src/mpnn/utils/inference.py:72-73]().
- **Chain Control**: `designed_chains` or `fixed_chains` [models/mpnn/src/mpnn/utils/inference.py:74-75]().
- **Omission**: `omit` lists (e.g., "UNK") or `omit_per_residue` [models/mpnn/src/mpnn/utils/inference.py:79-80]().

### Sampling Modifiers
- **Temperature**: Global `temperature` or `temperature_per_residue` [models/mpnn/src/mpnn/utils/inference.py:84-85]().
- **Biasing**: `bias_per_residue` and `pair_bias_per_residue_pair` to influence amino acid selection [models/mpnn/src/mpnn/utils/inference.py:77-82]().

### Symmetry and Oligomers
- **Symmetry Groups**: `symmetry_residues` and `symmetry_residues_weights` define equivalent positions [models/mpnn/src/mpnn/utils/inference.py:87-88]().
- **Homo-oligomers**: `homo_oligomer_chains` enforces identical sequences across chains [models/mpnn/src/mpnn/utils/inference.py:89]().

**Sources:** [models/mpnn/src/mpnn/utils/inference.py:70-90]()

## System Architecture

The following diagram maps the logical inference components to specific code entities within the `mpnn` module.

```mermaid
graph TB
    subgraph "Input Layer"
        CLI["mpnn CLI"]
        JSON["config_json"]
        AA["AtomArray (Biotite)"]
    end
    
    subgraph "Data Preparation [mpnn/utils/inference.py]"
        Parser["build_arg_parser()"]
        InfInput["MPNNInferenceInput"]
        Defaults["MPNN_PER_INPUT_INFERENCE_DEFAULTS"]
    end
    
    subgraph "Feature Pipeline [mpnn/transforms]"
        UserTrans["FeaturizeUserSettings"]
        TokenEnc["MPNN_TOKEN_ENCODING"]
    end
    
    subgraph "Model Core [mpnn/inference_engines]"
        Engine["MPNNInferenceEngine"]
        Legacy["is_legacy_weights flag"]
    end
    
    subgraph "Loss & Training [mpnn/loss]"
        NLL["LabelSmoothedNLLLoss"]
    end

    CLI --> Parser
    Parser --> InfInput
    JSON --> InfInput
    AA --> InfInput
    
    InfInput --> UserTrans
    Defaults --> UserTrans
    
    UserTrans --> Engine
    TokenEnc --> Engine
    
    Engine --> NLL
    
    style Engine fill:none
    style InfInput fill:none
    style UserTrans fill:none
```

**Diagram: MPNN Code Entity Map**

**Sources:** [models/mpnn/src/mpnn/utils/inference.py:35-120](), [models/mpnn/src/mpnn/loss/nll_loss.py:5-22](), [models/mpnn/src/mpnn/utils/inference.py:677-680]()

## Data Flow Through MPNN

The data flow highlights how raw structural data is transformed into designable features and finally into sampled sequences.

```mermaid
graph LR
    subgraph "Featurization"
        S1["AtomArray"] --> S2["as_atom_array_plus()"]
        S2 --> S3["MPNN_TOKEN_ENCODING"]
    end
    
    subgraph "User Constraints"
        C1["bias / omit / temp"] --> C2["FeaturizeUserSettings"]
    end
    
    subgraph "Neural Network"
        S3 --> Enc["Encoder"]
        C2 --> Dec["Decoder"]
        Enc --> MP["Message Passing"]
        MP --> Dec
    end
    
    subgraph "Output"
        Dec --> LP["log_probs"]
        LP --> Samp["Autoregressive Sampling"]
        Samp --> Out["MPNNInferenceOutput"]
    end
    
    style Enc fill:none
    style Dec fill:none
    style MP fill:none
```

**Diagram: MPNN Data Flow Pipeline**

1.  **Featurization**: Structural data is converted into `AtomArrayPlus` and tokenized using `MPNN_TOKEN_ENCODING` [models/mpnn/src/mpnn/utils/inference.py:24-31]().
2.  **Constraint Processing**: `FeaturizeUserSettings` maps CLI/JSON settings into tensors for masking and biasing [models/mpnn/src/mpnn/utils/inference.py:63-85]().
3.  **Inference**: The model generates `log_probs` which are sampled autoregressively [models/mpnn/src/mpnn/loss/nll_loss.py:38-40]().

**Sources:** [models/mpnn/src/mpnn/utils/inference.py:24-90](), [models/mpnn/src/mpnn/loss/nll_loss.py:38-40]()

## Training and Loss

MPNN uses a specialized loss function for sequence design:

### LabelSmoothedNLLLoss
The model is trained using a label-smoothed negative log-likelihood loss [models/mpnn/src/mpnn/loss/nll_loss.py:5-15]().
- **Label Smoothing**: Controlled by `label_smoothing_eps` (default 0.1), it distributes probability mass away from the ground truth to prevent over-fitting [models/mpnn/src/mpnn/loss/nll_loss.py:91-95]().
- **Normalization**: Uses a `normalization_constant` (default 6000.0) instead of simple batch averaging to stabilize gradients across varying protein lengths [models/mpnn/src/mpnn/loss/nll_loss.py:112-114]().

**Sources:** [models/mpnn/src/mpnn/loss/nll_loss.py:5-123]()

## Key Implementation Details

### Weight Loading
Foundry supports legacy weights from the original ProteinMPNN/LigandMPNN repositories. When using these, the `is_legacy_weights` flag must be set to `True` to ensure correct parameter mapping [models/mpnn/README.md:121-128]().

### Known Limitations
- **Annotation Shapes**: `mpnn_bias` and `mpnn_pair_bias` annotations cannot currently be saved directly to CIF files due to shape constraints; they must be provided via input dictionaries [models/mpnn/README.md:139-141]().
- **User Annotations**: There is a known issue with loading MPNN user annotations (e.g., temperature) directly from CIF/AtomArray annotations; command-line or `input_dict` specifications are the recommended workarounds [models/mpnn/README.md:121-122]().

**Sources:** [models/mpnn/README.md:121-141]()

---