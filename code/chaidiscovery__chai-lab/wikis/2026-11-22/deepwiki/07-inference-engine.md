# Inference Engine

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [chai_lab/chai1.py](chai_lab/chai1.py)
- [chai_lab/data/dataset/msas/utils.py](chai_lab/data/dataset/msas/utils.py)
- [chai_lab/model/__init__.py](chai_lab/model/__init__.py)
- [chai_lab/model/diffusion_schedules.py](chai_lab/model/diffusion_schedules.py)

</details>



## Purpose and Scope

This document describes the core inference engine of the Chai-1 molecular structure prediction system. The inference engine orchestrates the complete pipeline from feature processing through structure generation, including trunk recycling and diffusion. This page covers the main inference pipeline implementation, trunk recycling mechanisms, and diffusion process integration. For information about input processing, see [Input Processing](#4), for feature generation details, see [Feature Generation](#5), and for structure scoring, see [Structure Ranking](#3.4).

## Inference Engine Architecture

The inference engine coordinates the complete Chai-1 structure prediction pipeline, from feature processing through final structure generation.

```mermaid
flowchart TD
    Input[["Input Processing
    read_inputs()
    load_chains_from_raw()"]] --> AllAtomFeatureContext["AllAtomFeatureContext
    make_all_atom_feature_context()"]
    
    subgraph "Core Inference Pipeline"
        AllAtomFeatureContext --> Collate["Collate
        Collate(feature_factory)"]
        Collate --> FeatureEmbedder["feature_embedding.pt
        embedded_features"]
        FeatureEmbedder --> TokenEmbedder["token_embedder.pt
        token representations"]
        TokenEmbedder --> TrunkRecycles["Trunk Recycles
        trunk.pt (num_trunk_recycles=3)"]
        TrunkRecycles --> DiffusionModule["diffusion_module.pt
        (num_diffn_timesteps=200)"]
        DiffusionModule --> ConfidenceHead["confidence_head.pt
        pLDDT, PAE, PDE"]
    end
    
    subgraph "Output Generation"
        ConfidenceHead --> Ranking["Structure Ranking
        rank()"]
        Ranking --> CIFOutput["CIF Generation
        save_to_cif()"]
        ConfidenceHead --> ScoreOutput["Score Files
        .npz format"]
    end
    
    CIFOutput --> StructureCandidates["StructureCandidates
    cif_paths, ranking_data"]
    ScoreOutput --> StructureCandidates
```

Sources: [chai_lab/chai1.py:498-572](), [chai_lab/chai1.py:579-1059]()

## Main Inference Functions

The inference engine provides two main entry points for structure prediction:

### run_inference
The primary interface for end-to-end structure prediction from FASTA files:

```python
def run_inference(
    fasta_file: Path,
    output_dir: Path,
    use_esm_embeddings: bool = True,
    use_msa_server: bool = False,
    num_trunk_recycles: int = 3,
    num_diffn_timesteps: int = 200,
    num_diffn_samples: int = 5,
    num_trunk_samples: int = 1,
    # ... other parameters
) -> StructureCandidates
```

Sources: [chai_lab/chai1.py:498-572]()

### run_folding_on_context
Lower-level interface for folding when feature context is already prepared:

```python
def run_folding_on_context(
    feature_context: AllAtomFeatureContext,
    output_dir: Path,
    num_trunk_recycles: int = 3,
    num_diffn_timesteps: int = 200,
    num_diffn_samples: int = 5,
    # ... other parameters
) -> StructureCandidates
```

Sources: [chai_lab/chai1.py:579-594]()

## Trunk Recycling Process

The trunk model performs iterative refinement of molecular representations through recycling:

```mermaid
flowchart LR
    subgraph "Trunk Recycle Loop"
        InitialRepr["Initial Representations
        token_single_initial_repr
        token_pair_initial_repr"] --> TrunkForward["trunk.forward()
        trunk.pt model"]
        
        TrunkForward --> TrunkOutput["Trunk Output
        token_single_trunk_repr
        token_pair_trunk_repr"]
        
        TrunkOutput --> RecycleCheck{"Recycle < num_trunk_recycles?"}
        RecycleCheck -->|Yes| TrunkForward
        RecycleCheck -->|No| FinalRepr["Final Trunk Representations"]
        
        subgraph "MSA Subsampling"
            MSASubsample["subsample_and_reorder_msa_feats_n_mask()
            if recycle_msa_subsample > 0"]
        end
        
        MSASubsample --> TrunkForward
    end
```

The trunk recycling process uses:
- `num_trunk_recycles`: Number of recycling iterations (default: 3) [chai_lab/chai1.py:588]().
- `recycle_msa_subsample`: Optional MSA subsampling during recycles [chai_lab/chai1.py:591]().
- Progressive refinement of token representations [chai_lab/chai1.py:744-777]().

Sources: [chai_lab/chai1.py:744-777](), [chai_lab/data/dataset/msas/utils.py:51-86]()

## Exported Model Components

The inference engine uses several exported PyTorch models loaded via `ModuleWrapper` [chai_lab/chai1.py:115-137]():

| Component | File | Purpose |
|-----------|------|---------|
| Feature Embedder | `feature_embedding.pt` | Converts raw features to embedded representations |
| Token Embedder | `token_embedder.pt` | Processes token-level features and atom features |
| Trunk Model | `trunk.pt` | Iterative refinement through recycling |
| Diffusion Module | `diffusion_module.pt` | Denoising diffusion for structure generation |
| Confidence Head | `confidence_head.pt` | Confidence scoring (pLDDT, PAE, PDE) |
| Bond Loss Input Projection | `bond_loss_input_proj.pt` | Bond feature processing |

### Component Loading and Management

Components are loaded using `load_exported()` [chai_lab/chai1.py:139-149]() and managed with `_component_moved_to()` context manager [chai_lab/chai1.py:154-167]():

```python
with _component_moved_to("trunk.pt", device) as trunk:
    (token_single_trunk_repr, token_pair_trunk_repr) = trunk.forward(
        # trunk parameters
    )
```

This allows efficient GPU memory management by temporarily moving components to device only when needed.

Sources: [chai_lab/chai1.py:139-166](), [chai_lab/chai1.py:678-685]()

## Diffusion Process

The diffusion process generates 3D atomic coordinates through iterative denoising.

### DiffusionConfig Parameters

| Parameter | Default Value | Description |
|-----------|---------------|-------------|
| S_churn | 80 | Controls the amount of noise added during steps |
| S_tmin | 4e-4 | Minimum noise scale in schedule |
| S_tmax | 80.0 | Maximum noise scale in schedule |
| S_noise | 1.003 | Noise parameter for added noise during denoising |
| sigma_data | 16.0 | Scaling parameter for data distribution |
| second_order | True | Whether to use second-order update steps for higher accuracy |

Sources: [chai_lab/chai1.py:242-249]()

### Diffusion Implementation Flow

The `InferenceNoiseSchedule` generates the schedule of noise levels (sigmas) [chai_lab/model/diffusion_schedules.py:14-39]().

```mermaid
sequenceDiagram
    participant NS as InferenceNoiseSchedule
    participant DL as Diffusion Loop
    participant DM as diffusion_module.pt
    participant CH as confidence_head.pt
    
    Note over NS,CH: Diffusion Process in run_folding_on_context
    
    NS->>DL: "Generate sigmas and gammas"
    DL->>DL: "Initialize random atom_pos"
    
    loop "num_diffn_timesteps iterations"
        DL->>DL: "center_random_augmentation()"
        DL->>DL: "Add noise: atom_pos_hat"
        DL->>DM: "_denoise(atom_pos_hat, sigma_hat)"
        DM->>DL: "denoised_pos"
        DL->>DL: "First-order update: d_i"
        
        alt "second_order = True"
            DL->>DM: "_denoise(atom_pos, sigma_next)"
            DM->>DL: "denoised_pos"
            DL->>DL: "Second-order update: d_i_prime"
        end
    end
    
    DL->>CH: "Final atom_pos"
    CH->>CH: "Compute pLDDT, PAE, PDE"
```

Sources: [chai_lab/chai1.py:821-885](), [chai_lab/model/diffusion_schedules.py:14-39]()

## Feature Processing Pipeline

The inference engine processes features through several stages before trunk recycling:

### Feature Embedding Stage

```mermaid
flowchart LR
    subgraph "Feature Processing"
        Collate["Collate
        feature_factory"] --> FeatureEmbedding["feature_embedding.pt"]
        FeatureEmbedding --> EmbeddedFeatures["Embedded Features
        TOKEN, TOKEN_PAIR, ATOM, ATOM_PAIR, TEMPLATES, MSA"]
    end
    
    subgraph "Bond Feature Processing"
        TokenBondRestraint["TokenBondRestraint
        bond_ft_gen.generate()"] --> BondLossInputProj["bond_loss_input_proj.pt"]
        BondLossInputProj --> BondFeatures["Bond Features
        trunk_bond_feat, structure_bond_feat"]
    end
    
    subgraph "Token Embedding"
        EmbeddedFeatures --> TokenEmbedder["token_embedder.pt"]
        BondFeatures --> TokenEmbedder
        TokenEmbedder --> TokenRepresentations["Initial Representations
        token_single_initial_repr, token_pair_initial_repr"]
    end
```

Sources: [chai_lab/chai1.py:637-647](), [chai_lab/chai1.py:679-738]()

## Sampling and Output Generation

The inference engine supports multiple sampling strategies.

### Sampling Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `num_trunk_samples` | 1 | Number of independent trunk runs |
| `num_diffn_samples` | 5 | Number of diffusion samples per trunk |
| `num_trunk_recycles` | 3 | Recycling iterations per trunk |
| `num_diffn_timesteps` | 200 | Diffusion denoising steps |

Total structures generated: `num_trunk_samples × num_diffn_samples` [chai_lab/chai1.py:813]().

### Structure Candidate Generation

```mermaid
flowchart TD
    subgraph "Sampling Loop"
        TrunkSample["Trunk Sample Loop
        for trunk_idx in range(num_trunk_samples)"]
        TrunkSample --> DiffusionSamples["Diffusion Samples
        for ds in range(num_diffn_samples)"]
        DiffusionSamples --> ConfidenceScoring["Confidence Scoring
        pLDDT, PAE, PDE per sample"]
        ConfidenceScoring --> StructureRanking["Structure Ranking
        rank() function"]
    end
    
    subgraph "Output Generation"
        StructureRanking --> CIFFiles["CIF Files
        pred.model_idx_{idx}.cif"]
        StructureRanking --> ScoreFiles["Score Files
        scores.model_idx_{idx}.npz"]
        StructureRanking --> MSAPlot["MSA Coverage Plot
        msa_depth.pdf"]
    end
    
    CIFFiles --> StructureCandidates["StructureCandidates
    concat() multiple samples"]
    ScoreFiles --> StructureCandidates
    MSAPlot --> StructureCandidates
```

Sources: [chai_lab/chai1.py:552-572](), [chai_lab/chai1.py:984-1050]()

## Memory Management and Performance

The inference engine implements several memory optimization strategies:

### Low Memory Mode
When `low_memory=True`, tensors are kept on CPU when possible:

```python
if not low_memory:
    batch = move_data_to_device(batch, device=device)
# Components return data on CPU when return_on_cpu=True
```

### Component Management
Components are temporarily moved to device using context managers [chai_lab/chai1.py:154-167]():

```python
with _component_moved_to("trunk.pt", device) as trunk:
    # Component is on device during forward pass
    trunk_output = trunk.forward(...)
# Component automatically moved back to CPU
```

### Memory Clearing
Explicit cache clearing between major stages:

```python
torch.cuda.empty_cache()  # Clear GPU memory
```

Sources: [chai_lab/chai1.py:154-166](), [chai_lab/chai1.py:648-650](), [chai_lab/chai1.py:780]()

## Integration with MSA Sampling

During trunk recycles, the system can optionally subsample the Multiple Sequence Alignment (MSA) inputs using `subsample_and_reorder_msa_feats_n_mask` [chai_lab/data/dataset/msas/utils.py:51-86]():

```python
if recycle_msa_subsample > 0:
    subsampled_msa_input_feats, subsampled_msa_mask = subsample_and_reorder_msa_feats_n_mask(
        msa_input_feats,
        msa_mask,
    )
```

This allows for efficient focusing on the most informative parts of the MSA during recycles.

Sources: [chai_lab/chai1.py:727-734](), [chai_lab/data/dataset/msas/utils.py:51-86]()

## Confidence and Scoring

After the diffusion process completes, the final atom positions are used to generate confidence scores via the `confidence_head.pt` component [chai_lab/chai1.py:888-935]():

1. **pLDDT** (predicted Local Distance Difference Test): Per-residue confidence score.
2. **PAE** (Predicted Aligned Error): Pairwise distance error estimates between residues.
3. **PDE** (Predicted Distance Error): Estimates of distance error.

These scores are used for ranking the generated structures in the `rank()` function [chai_lab/ranking/rank.py:133-157]().

Sources: [chai_lab/chai1.py:872-935](), [chai_lab/ranking/rank.py:133-157]()

---