# Glossary

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.env](.env)
- [.gitignore](.gitignore)
- [README.md](README.md)
- [models/mpnn/README.md](models/mpnn/README.md)
- [models/mpnn/src/mpnn/__init__.py](models/mpnn/src/mpnn/__init__.py)
- [models/mpnn/src/mpnn/loss/nll_loss.py](models/mpnn/src/mpnn/loss/nll_loss.py)
- [models/mpnn/src/mpnn/utils/inference.py](models/mpnn/src/mpnn/utils/inference.py)
- [models/rf3/configs/inference_engine/base.yaml](models/rf3/configs/inference_engine/base.yaml)
- [models/rf3/configs/inference_engine/rf3.yaml](models/rf3/configs/inference_engine/rf3.yaml)
- [models/rf3/src/rf3/data/extra_xforms.py](models/rf3/src/rf3/data/extra_xforms.py)
- [models/rf3/src/rf3/data/pipelines.py](models/rf3/src/rf3/data/pipelines.py)
- [models/rf3/src/rf3/inference.py](models/rf3/src/rf3/inference.py)
- [models/rf3/src/rf3/inference_engines/rf3.py](models/rf3/src/rf3/inference_engines/rf3.py)
- [models/rf3/src/rf3/symmetry/resolve.py](models/rf3/src/rf3/symmetry/resolve.py)
- [models/rf3/src/rf3/utils/inference.py](models/rf3/src/rf3/utils/inference.py)
- [models/rfd3/README.md](models/rfd3/README.md)
- [models/rfd3/configs/inference_engine/base.yaml](models/rfd3/configs/inference_engine/base.yaml)
- [models/rfd3/configs/inference_engine/rfdiffusion3.yaml](models/rfd3/configs/inference_engine/rfdiffusion3.yaml)
- [models/rfd3/configs/trainer/loss/losses/diffusion_loss.yaml](models/rfd3/configs/trainer/loss/losses/diffusion_loss.yaml)
- [models/rfd3/docs/.assets/input_selection_large.png](models/rfd3/docs/.assets/input_selection_large.png)
- [models/rfd3/docs/input.md](models/rfd3/docs/input.md)
- [models/rfd3/src/rfd3/model/RFD3_diffusion_module.py](models/rfd3/src/rfd3/model/RFD3_diffusion_module.py)
- [models/rfd3/src/rfd3/model/inference_sampler.py](models/rfd3/src/rfd3/model/inference_sampler.py)
- [models/rfd3/src/rfd3/model/layers/block_utils.py](models/rfd3/src/rfd3/model/layers/block_utils.py)
- [models/rfd3/src/rfd3/model/layers/chunked_pairwise.py](models/rfd3/src/rfd3/model/layers/chunked_pairwise.py)
- [models/rfd3/src/rfd3/model/layers/encoders.py](models/rfd3/src/rfd3/model/layers/encoders.py)
- [models/rfd3/src/rfd3/run_inference.py](models/rfd3/src/rfd3/run_inference.py)
- [models/rfd3/src/rfd3/trainer/rfd3.py](models/rfd3/src/rfd3/trainer/rfd3.py)
- [src/foundry/inference_engines/base.py](src/foundry/inference_engines/base.py)
- [src/foundry/inference_engines/checkpoint_registry.py](src/foundry/inference_engines/checkpoint_registry.py)
- [src/foundry_cli/__init__.py](src/foundry_cli/__init__.py)
- [src/foundry_cli/download_checkpoints.py](src/foundry_cli/download_checkpoints.py)

</details>



This glossary provides technical definitions for codebase-specific terms, domain jargon, and architectural concepts within the Foundry repository.

## Core Data Structures & Representations

### AtomArray
The primary data structure used for representing molecular systems, provided by the [AtomWorks](https://github.com/RosettaCommons/atomworks) library and based on `biotite.structure.AtomArray` [models/rf3/src/rf3/inference_engines/rf3.py:18-18](). It is a structure-oriented NumPy-like array where each row represents an atom and columns represent attributes (coordinates, chain ID, residue name, atom name, etc.).

### Atom14
A standardized representation of protein residues using a maximum of 14 heavy atoms. This fixed-size representation allows for efficient tensorized operations in neural networks like RFdiffusion3 and RosettaFold3 [models/rfd3/README.md:56-57]().

### Contig String
A mini-language used to specify the composition of a protein design target. It defines which parts of a structure are fixed (motif) and which are to be generated (diffused).
*   **Example**: `50-80,/0,A1-100` means: diffuse a monomer of length 50-80, followed by a chain break, then use residues 1-100 of chain A from the input structure as a fixed motif [models/rfd3/docs/input.md:39-39]().

### InputSelection
A mini-language used within the `InputSpecification` to select specific subsets of atoms or residues for conditioning (e.g., selecting ligands by name or specific residue ranges) [models/rfd3/docs/input.md:18-18]().

## Diffusion Terminology (RFD3)

### Classifier-Free Guidance (CFG)
A technique used during the reverse diffusion process to steer the model toward specific conditions (like hydrogen bond donors/acceptors) without requiring a separate classifier network [models/rfd3/docs/input.md:85-85](). It involves interpolating between a conditional and unconditional model prediction using a `cfg_scale` [models/rfd3/src/rfd3/model/inference_sampler.py:51-51]().

### Noise Schedule
A sequence of noise levels ($t$) defined from $T$ (pure noise) to $0$ (clean structure). RFD3 uses an EDM-style schedule [models/rfd3/src/rfd3/model/inference_sampler.py:66-75]().
*   **$p$**: Power constant determining the "shape" of the noise schedule (default: 7) [models/rfd3/docs/input.md:97-97]().
*   **$\gamma_0$**: A parameter influencing design diversity vs. designability [models/rfd3/docs/input.md:98-98]().

### Partial Diffusion
A mode where the process starts from a partially noised structure rather than pure Gaussian noise. This is used for "refining" or diversifying an existing structure [models/rfd3/src/rfd3/model/inference_sampler.py:89-93]().

### Recycling
An iterative process where the model's own outputs are fed back as inputs within a single denoising step to refine the structural prediction [models/rfd3/docs/input.md:83-83](). Controlled by `n_recycle` (default: 2) [models/rfd3/configs/inference_engine/rfdiffusion3.yaml:41-41]().

**Sources:** [models/rfd3/src/rfd3/model/inference_sampler.py:25-131](), [models/rfd3/docs/input.md:68-101](), [models/rfd3/configs/inference_engine/rfdiffusion3.yaml:24-51]()

## Model Architecture & Training

### Inference Engine
A high-level class abstraction (`BaseInferenceEngine`) that encapsulates the logic for loading checkpoints, preprocessing inputs, executing model forward passes, and saving outputs [src/foundry/inference_engines/base.py:22-22]().
*   **RFD3InferenceEngine**: Handles diffusion sampling and contig parsing [models/rfd3/configs/inference_engine/rfdiffusion3.yaml:6-6]().
*   **RF3InferenceEngine**: Handles structure prediction, MSA processing, and confidence scoring [models/rf3/src/rf3/inference_engines/rf3.py:222-222]().

### Tokenization
The process of grouping atoms into discrete units (tokens) for the transformer blocks. In Foundry, this often involves grouping atoms by residue [models/rfd3/src/rfd3/model/layers/block_utils.py:33-54]().
*   **Low Memory Mode**: A memory-efficient tokenization strategy for handling large systems on limited GPU RAM [models/rfd3/docs/input.md:70-70]().

### Structure to Code Mapping

The following diagram maps high-level concepts to the specific classes and files implementing them.

**Conceptual Entity to Code Mapping**
```mermaid
graph TD
    subgraph "Natural Language Space"
        A["Inference Execution"]
        B["Checkpoint Storage"]
        C["Diffusion Logic"]
        D["Input Spec"]
    end

    subgraph "Code Entity Space"
        A1["BaseInferenceEngine"]
        A2["RF3InferenceEngine"]
        B1["REGISTERED_CHECKPOINTS"]
        B2["FOUNDRY_CHECKPOINT_DIRS"]
        C1["SampleDiffusionWithMotif"]
        D1["InputSpecification"]
    end

    A --- A1
    A1 --- A2
    B --- B1
    B1 --- B2
    C --- C1
    D --- D1

    style A1 stroke-dasharray: 5 5
    style B1 stroke-dasharray: 5 5
```
**Sources:** [src/foundry/inference_engines/base.py:22-22](), [models/rf3/src/rf3/inference_engines/rf3.py:222-222](), [src/foundry/inference_engines/checkpoint_registry.py:80-122](), [models/rfd3/src/rfd3/model/inference_sampler.py:58-58]()

## RosettaFold3 (RF3) Confidence Metrics

RF3 outputs several metrics to validate the quality of predicted structures [models/rf3/src/rf3/inference_engines/rf3.py:99-110]():

| Metric | Definition | Implementation |
| :--- | :--- | :--- |
| **pLDDT** | Predicted Local Distance Difference Test; measures per-residue confidence. | `get_mean_atomwise_plddt` [models/rf3/src/rf3/inference_engines/rf3.py:39-39]() |
| **pTM** | Predicted Template Modeling score; measures global topology confidence. | `ComputePTM` [models/rf3/src/rf3/inference_engines/rf3.py:51-51]() |
| **ipTM** | Interface pTM; measures confidence in the relative orientation of chains. | `ComputeIPTM` [models/rf3/src/rf3/inference_engines/rf3.py:52-52]() |
| **Ranking Score** | Weighted sum of ipTM and pTM used to select the best design. | `compute_ranking_score` [models/rf3/src/rf3/inference_engines/rf3.py:79-95]() |

## Infrastructure & Environment

### Checkpoint Registry
A centralized mapping of model names (e.g., `rfd3`, `rf3`, `proteinmpnn`) to their remote URLs, local filenames, and SHA256 hashes [src/foundry/inference_engines/checkpoint_registry.py:80-122]().

### .env Configuration
A local file used to define paths to external tools and data mirrors [README.md:112-115]().
*   **PDB_MIRROR_PATH**: Path to a local mirror of the Protein Data Bank [env:13-13]().
*   **CCD_MIRROR_PATH**: Path to a local mirror of the Chemical Component Dictionary [env:22-22]().
*   **HBPLUS_PATH**: Path to the `hbplus` executable for hydrogen bond calculation [env:32-32]().

### Data Flow Diagram
This diagram illustrates how an input specification moves through the system components to produce a design.

**Foundry Data Pipeline**
```mermaid
graph LR
    Input["JSON/YAML Spec"] --> Engine["RFD3InferenceEngine"]
    Engine --> Sampler["SampleDiffusionWithMotif"]
    Sampler --> Model["RFD3_diffusion_module"]
    Model --> Output["RFD3Output (CIF + JSON)"]
    
    subgraph "Infrastructure"
        Registry["checkpoint_registry.py"] -.-> Engine
        Env[".env Paths"] -.-> Engine
    end
```
**Sources:** [models/rfd3/src/rfd3/run_inference.py](), [models/rfd3/src/rfd3/model/inference_sampler.py:58-156](), [src/foundry/inference_engines/checkpoint_registry.py:80-122](), [models/rf3/src/rf3/inference_engines/rf3.py:99-110]()