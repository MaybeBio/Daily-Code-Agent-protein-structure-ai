# RFdiffusion3 (RFD3)

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.gitignore](.gitignore)
- [examples/all.ipynb](examples/all.ipynb)
- [models/rfd3/configs/inference_engine/base.yaml](models/rfd3/configs/inference_engine/base.yaml)
- [models/rfd3/configs/inference_engine/rfdiffusion3.yaml](models/rfd3/configs/inference_engine/rfdiffusion3.yaml)
- [models/rfd3/configs/trainer/loss/losses/diffusion_loss.yaml](models/rfd3/configs/trainer/loss/losses/diffusion_loss.yaml)
- [models/rfd3/docs/.assets/input_selection_large.png](models/rfd3/docs/.assets/input_selection_large.png)
- [models/rfd3/docs/input.md](models/rfd3/docs/input.md)
- [models/rfd3/src/rfd3/engine.py](models/rfd3/src/rfd3/engine.py)
- [models/rfd3/src/rfd3/inference/datasets.py](models/rfd3/src/rfd3/inference/datasets.py)
- [models/rfd3/src/rfd3/model/RFD3_diffusion_module.py](models/rfd3/src/rfd3/model/RFD3_diffusion_module.py)
- [models/rfd3/src/rfd3/model/layers/chunked_pairwise.py](models/rfd3/src/rfd3/model/layers/chunked_pairwise.py)
- [models/rfd3/src/rfd3/model/layers/encoders.py](models/rfd3/src/rfd3/model/layers/encoders.py)
- [models/rfd3/src/rfd3/run_inference.py](models/rfd3/src/rfd3/run_inference.py)
- [models/rfd3/src/rfd3/trainer/rfd3.py](models/rfd3/src/rfd3/trainer/rfd3.py)
- [models/rfd3/src/rfd3/utils/inference.py](models/rfd3/src/rfd3/utils/inference.py)
- [models/rfd3na/src/rfd3na/utils/inference.py](models/rfd3na/src/rfd3na/utils/inference.py)

</details>



RFdiffusion3 (RFD3) is an all-atom generative diffusion model for protein structure design under complex constraints. It enables unconditional protein generation, motif scaffolding, partial diffusion, symmetric design, and conditioning on various biophysical properties including hydrogen bonds, hotspots, and solvent accessibility.

This page provides comprehensive documentation of the RFD3 model architecture, core components, and usage patterns within the Foundry framework. For specific topics:
- Input specification details: see [InputSpecification System](#4.2)
- Diffusion sampling and symmetry: see [Diffusion Sampling and Symmetry](#4.3)
- Application-specific guides: see [Design Applications](#4.4)
- Inference pipeline details: see [RFD3 Inference Pipeline](#4.5)
- Training and fine-tuning: see [RFD3 Training](#4.6)
- Multipolymer (Protein-DNA-RNA) design: see [RFdiffusion3NA (RFD3NA)](#4.7)

---

## RFD3 in the Foundry Ecosystem

RFD3 is the backbone generation module in the Foundry design pipeline. It generates all-atom backbones that are then passed to MPNN for sequence design and RosettaFold3 for structure validation.

**Diagram: RFD3 in the Foundry Pipeline**

```mermaid
graph LR
    User["User Input<br/>(JSON/CIF/PDB)"]
    RFD3["RFdiffusion3<br/>Backbone Generation"]
    MPNN["ProteinMPNN/LigandMPNN<br/>Sequence Design"]
    RF3["RosettaFold3<br/>Structure Validation"]
    Output["Designed Proteins<br/>(CIF + metadata)"]
    
    User --> RFD3
    RFD3 --> MPNN
    MPNN --> RF3
    RF3 --> Output
    
    RFD3 -.->|"Optional:<br/>Direct output"| Output
```

**Sources:** [examples/all.ipynb:12-27](), [models/rfd3/docs/input.md:3-5]()

---

## Core Architecture

RFD3 is built on a diffusion transformer architecture. It uses a UNet-like structure that processes information across both token (residue) and atom levels, allowing for precise all-atom conditioning.

**Diagram: RFD3 System Architecture**

```mermaid
graph TB
    subgraph "Entry Points"
        CLI["rfd3 CLI<br/>models/rfd3/src/rfd3/run_inference.py"]
        API["Python API<br/>RFD3InferenceEngine"]
    end
    
    subgraph "Inference Engine"
        Engine["RFD3InferenceEngine<br/>engine.py"]
        Config["RFD3InferenceConfig<br/>engine.py"]
        Spec["DesignInputSpecification<br/>input_parsing.py"]
    end
    
    subgraph "Model Components"
        DiffMod["RFD3DiffusionModule<br/>RFD3_diffusion_module.py"]
        Init["TokenInitializer<br/>encoders.py"]
        Sampler["SampleDiffusionConfig<br/>inference_sampler.py"]
    end
    
    subgraph "Memory Optimization"
        Chunk["ChunkedPairwiseEmbedder<br/>chunked_pairwise.py"]
    end
    
    CLI --> Engine
    API --> Engine
    Engine --> Config
    Engine --> Spec
    
    Engine --> Init
    Init --> DiffMod
    DiffMod --> Sampler
    
    Init -.->|"If low_memory_mode"| Chunk
```

**Sources:** [models/rfd3/src/rfd3/engine.py:139-175](), [models/rfd3/src/rfd3/model/RFD3_diffusion_module.py:32-125](), [models/rfd3/src/rfd3/model/layers/encoders.py:36-156]()

---

## Key Classes and Their Roles

### RFD3InferenceEngine

The `RFD3InferenceEngine` is the central orchestrator. It handles input validation, model loading, and the execution of the diffusion sampling loop.

| Component | Class/File | Purpose |
|-----------|------------|---------|
| **Main Engine** | `RFD3InferenceEngine` | Manages the inference lifecycle and batching [models/rfd3/src/rfd3/engine.py:139]() |
| **Configuration** | `RFD3InferenceConfig` | Holds hyperparameters like `diffusion_batch_size` and `low_memory_mode` [models/rfd3/src/rfd3/engine.py:44]() |
| **Output Container** | `RFD3Output` | Wraps generated `AtomArray` and prediction metadata [models/rfd3/src/rfd3/engine.py:91]() |
| **Input Parser** | `DesignInputSpecification` | Pydantic model for validating design requirements [models/rfd3/src/rfd3/engine.py:25]() |

**Key Methods:**
- `run()`: Entry point for starting design jobs [models/rfd3/src/rfd3/engine.py:205]().
- `RFD3Output.dump()`: Writes structures to `.cif.gz` and metadata to `.json` [models/rfd3/src/rfd3/engine.py:98]().

**Sources:** [models/rfd3/src/rfd3/engine.py:43-175]()

### Model Architecture (RFD3DiffusionModule)

The core neural network is a diffusion transformer that iteratively predicts denoised coordinates.

- **TokenInitializer**: Encodes 1D and 2D features into initial representations [models/rfd3/src/rfd3/model/layers/encoders.py:36]().
- **ChunkedPairwiseEmbedder**: A memory-optimized embedder that reduces complexity from $O(L^2)$ to $O(L \times k)$ for large structures [models/rfd3/src/rfd3/model/layers/chunked_pairwise.py:142]().
- **LocalAtomTransformer**: Processes all-atom geometric information locally [models/rfd3/src/rfd3/model/RFD3_diffusion_module.py:99]().

**Sources:** [models/rfd3/src/rfd3/model/RFD3_diffusion_module.py:32-125](), [models/rfd3/src/rfd3/model/layers/chunked_pairwise.py:1-150]()

---

## Input Specification System

RFD3 uses a flexible JSON/YAML input format. Users define "contigs" (structural regions) and conditioning constraints.

**Diagram: Input Data Space to Code Entity Space**

```mermaid
graph TB
    subgraph "Natural Language / User Input"
        ContigStr["'50-80,/0,A1-100'<br/>Contig String"]
        LigandStr["'HAX,OAA'<br/>Ligand Name"]
        FixedSel["'A20-35'<br/>Fixed Atoms"]
    end
    
    subgraph "Code Entities (rfd3.inference.input_parsing)"
        DIS["DesignInputSpecification<br/>(Pydantic Model)"]
        ISel["InputSelection<br/>(Mini-language parser)"]
    end
    
    subgraph "Foundry Internal Representation"
        AA["Biotite AtomArray<br/>with conditioning annotations"]
        Map["atom_to_token_map<br/>(Mapping tensor)"]
    end
    
    ContigStr --> DIS
    LigandStr --> DIS
    FixedSel --> DIS
    
    DIS --> ISel
    ISel --> AA
    AA --> Map
```

**Sources:** [models/rfd3/docs/input.md:34-47](), [models/rfd3/src/rfd3/engine.py:24-27](), [models/rfd3/src/rfd3/utils/inference.py:92-138]()

---

## Diffusion and Sampling

The sampling process is governed by the `SampleDiffusionConfig`. It controls the reverse diffusion schedule and conditioning guidance.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `num_timesteps` | 200 | Number of denoising steps [models/rfd3/configs/inference_engine/rfdiffusion3.yaml:44]() |
| `step_scale` | 1.5 | Scales step size; higher is less diverse but more designable [models/rfd3/configs/inference_engine/rfdiffusion3.yaml:45]() |
| `kind` | "default" | Sampler type ("default" or "symmetry") [models/rfd3/configs/inference_engine/rfdiffusion3.yaml:25]() |
| `cfg_scale` | 1.5 | Strength of classifier-free guidance [models/rfd3/configs/inference_engine/rfdiffusion3.yaml:34]() |

**Sources:** [models/rfd3/configs/inference_engine/rfdiffusion3.yaml:23-51](), [models/rfd3/src/rfd3/model/RFD3_diffusion_module.py:171-214]()

---

## Design Applications

RFD3 supports a variety of design tasks by modifying the `InputSpecification`:

- **Unconditional Generation**: Set `inputs=null` and specify `length` [examples/all.ipynb:101-105]().
- **Motif Scaffolding**: Provide a PDB input and define fixed regions in the `contig` string [models/rfd3/docs/input.md:39]().
- **Ligand Binding**: Specify ligand residue names via the `ligand` field [models/rfd3/docs/input.md:41]().
- **Partial Diffusion**: Add noise to an existing structure and denoise from `partial_t` [models/rfd3/docs/input.md:22]().

For details, see [Design Applications](#4.4).

---

## RFD3 Training

Training involves a `FabricTrainer` (specifically `AADesignTrainer`) and a complex featurization pipeline.

- **AADesignTrainer**: Handles the training step, including recycling schedules and all-atom loss computation [models/rfd3/src/rfd3/trainer/rfd3.py:33]().
- **Recycling**: RFD3 uses recycling during training to improve structure quality [models/rfd3/src/rfd3/trainer/rfd3.py:154]().
- **Loss**: Coordinate prediction is supervised via a specialized diffusion loss [models/rfd3/configs/trainer/loss/losses/diffusion_loss.yaml:1-12]().

For details, see [RFD3 Training](#4.6).

---

## RFdiffusion3NA (RFD3NA)

RFD3NA extends the base model to support Nucleic Acids (DNA/RNA). It uses a specialized inference engine and CLI (`rfd3na`).

- **Capabilities**: Co-designing proteins with DNA/RNA chains.
- **Input Differences**: Requires NA-specific specifications in the contig and ligand strings.

For details, see [RFdiffusion3NA (RFD3NA)](#4.7).

**Sources:** [models/rfd3/src/rfd3/utils/inference.py:141-164]() (NA extraction logic)

---