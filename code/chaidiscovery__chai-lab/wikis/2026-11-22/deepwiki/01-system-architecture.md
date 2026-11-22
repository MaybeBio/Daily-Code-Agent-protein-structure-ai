# System Architecture

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [chai_lab/chai1.py](chai_lab/chai1.py)
- [chai_lab/data/collate/collate.py](chai_lab/data/collate/collate.py)
- [chai_lab/data/dataset/all_atom_feature_context.py](chai_lab/data/dataset/all_atom_feature_context.py)
- [chai_lab/data/dataset/msas/utils.py](chai_lab/data/dataset/msas/utils.py)

</details>



This document provides a comprehensive overview of the Chai-1 system architecture, covering the core inference pipeline, data processing components, and model structure. For specific implementation details about input processing, see [Input Processing](#4). For feature generation systems, see [Feature Generation](#5).

## Overview

Chai-1 is a multi-modal foundation model for molecular structure prediction that unifies prediction of proteins, small molecules, DNA, RNA, and glycosylations. The system follows a pipeline architecture with distinct stages for input processing, feature generation, model inference, and output generation.

## High-Level System Architecture

### Core Pipeline Components

```mermaid
graph TB
    subgraph "User Interface Layer"
        CLI["chai-lab CLI"]
        WebUI["Web Server<br/>lab.chaidiscovery.com"]
        PythonAPI["Python API<br/>run_inference()"]
    end
    
    subgraph "Input Processing"
        FASTAParser["FASTA Parser<br/>read_inputs()"]
        ChainLoader["Chain Loader<br/>load_chains_from_raw()"]
        Validator["Input Validator<br/>raise_if_too_many_tokens()"]
    end
    
    subgraph "Feature Generation"
        MSAGen["MSA Generator<br/>generate_colabfold_msas()"]
        TemplateLoader["Template Loader<br/>get_template_context()"]
        ESMEmbedder["ESM Embedder<br/>get_esm_embedding_context()"]
        FeatureFactory["FeatureFactory<br/>feature_generators"]
    end
    
    subgraph "Core Inference Engine"
        FeatureEmbed["Feature Embedding<br/>feature_embedding.pt"]
        TokenEmbed["Token Embedder<br/>token_embedder.pt"]
        Trunk["Trunk Module<br/>trunk.pt"]
        Diffusion["Diffusion Module<br/>diffusion_module.pt"]
        Confidence["Confidence Head<br/>confidence_head.pt"]
    end
    
    subgraph "Output Processing"
        Ranking["Structure Ranking<br/>rank()"]
        CIFOutput["CIF Output<br/>save_to_cif()"]
        ScoreCalc["Score Calculation<br/>get_scores()"]
    end
    
    CLI --> FASTAParser
    WebUI --> FASTAParser
    PythonAPI --> FASTAParser
    
    FASTAParser --> ChainLoader
    ChainLoader --> Validator
    Validator --> MSAGen
    Validator --> TemplateLoader
    Validator --> ESMEmbedder
    
    MSAGen --> FeatureFactory
    TemplateLoader --> FeatureFactory
    ESMEmbedder --> FeatureFactory
    FeatureFactory --> FeatureEmbed
    
    FeatureEmbed --> TokenEmbed
    TokenEmbed --> Trunk
    Trunk --> Diffusion
    Diffusion --> Confidence
    
    Confidence --> Ranking
    Ranking --> CIFOutput
    Ranking --> ScoreCalc
```

Sources: [chai_lab/chai1.py:499-1059](), [README.md:23-46]()

### Data Context Architecture

The `AllAtomFeatureContext` serves as the central hub for all molecular and feature data required for inference. It encapsulates various sub-contexts that are eventually collated into tensors for the model.

```mermaid
graph TB
    subgraph "Core Data Structures"
        AllAtomFC["AllAtomFeatureContext<br/>Unified feature container"]
        AllAtomSC["AllAtomStructureContext<br/>Molecular structure data"]
        MSAContext["MSAContext<br/>Multiple sequence alignments"]
        TemplateContext["TemplateContext<br/>Structural templates"]
        EmbeddingContext["EmbeddingContext<br/>ESM embeddings"]
        RestraintContext["RestraintContext<br/>User constraints"]
    end
    
    subgraph "Input Sources"
        FASTAInput["FASTA File<br/>Sequences"]
        MSAFiles["MSA Files<br/>.aligned.pqt"]
        TemplateFiles["Template Files<br/>.m8 hits"]
        RestraintFiles["Restraint Files<br/>User constraints"]
    end
    
    subgraph "Feature Processing"
        Collate["Collate<br/>Batch preparation"]
        FeatureGen["Feature Generators<br/>feature_generators dict"]
    end
    
    FASTAInput --> AllAtomSC
    MSAFiles --> MSAContext
    TemplateFiles --> TemplateContext
    RestraintFiles --> RestraintContext
    
    AllAtomSC --> AllAtomFC
    MSAContext --> AllAtomFC
    TemplateContext --> AllAtomFC
    EmbeddingContext --> AllAtomFC
    RestraintContext --> AllAtomFC
    
    AllAtomFC --> Collate
    Collate --> FeatureGen
```

Sources: [chai_lab/data/dataset/all_atom_feature_context.py:25-40](), [chai_lab/data/collate/collate.py:24-35](), [chai_lab/chai1.py:486-495]()

## Model Inference Pipeline

### Trunk Recycling and Diffusion Process

The inference engine utilizes a sequential execution flow involving feature embedding, trunk recycling, and a diffusion denoising loop. The `ModuleWrapper` handles JIT-loaded components like `trunk.pt` and `diffusion_module.pt`.

```mermaid
graph TB
    subgraph "Model Loading"
        ComponentCache["_component_cache<br/>ModuleWrapper storage"]
        ComponentLoader["load_exported()<br/>JIT module loader"]
    end
    
    subgraph "Feature Embedding"
        FeatureEmbed["feature_embedding.pt<br/>Embed input features"]
        TokenEmbed["token_embedder.pt<br/>Process token representations"]
        BondEmbed["bond_loss_input_proj.pt<br/>Bond feature processing"]
    end
    
    subgraph "Trunk Processing"
        TrunkInit["Initial Representations<br/>token_single_initial_repr"]
        TrunkRecycle["Trunk Recycling<br/>num_trunk_recycles=3"]
        MSASubsample["MSA Subsampling<br/>subsample_and_reorder_msa_feats_n_mask()"]
        TrunkModule["trunk.pt<br/>Core processing module"]
    end
    
    subgraph "Diffusion Denoising"
        NoiseSchedule["InferenceNoiseSchedule<br/>Diffusion timesteps"]
        DiffusionLoop["Diffusion Loop<br/>num_diffn_timesteps=200"]
        DiffusionModule["diffusion_module.pt<br/>Structure denoising"]
        AtomPositions["Atom Positions<br/>3D coordinates"]
    end
    
    subgraph "Confidence Prediction"
        ConfidenceHead["confidence_head.pt<br/>Quality prediction"]
        PAELogits["PAE Logits<br/>Predicted aligned error"]
        PDELogits["PDE Logits<br/>Predicted distance error"]
        PLDDTLogits["pLDDT Logits<br/>Local confidence"]
    end
    
    ComponentLoader --> ComponentCache
    ComponentCache --> FeatureEmbed
    FeatureEmbed --> TokenEmbed
    TokenEmbed --> BondEmbed
    BondEmbed --> TrunkInit
    
    TrunkInit --> TrunkRecycle
    TrunkRecycle --> MSASubsample
    MSASubsample --> TrunkModule
    TrunkModule --> TrunkRecycle
    
    TrunkModule --> NoiseSchedule
    NoiseSchedule --> DiffusionLoop
    DiffusionLoop --> DiffusionModule
    DiffusionModule --> AtomPositions
    
    AtomPositions --> ConfidenceHead
    ConfidenceHead --> PAELogits
    ConfidenceHead --> PDELogits
    ConfidenceHead --> PLDDTLogits
```

Sources: [chai_lab/chai1.py:115-137](), [chai_lab/chai1.py:139-149](), [chai_lab/chai1.py:744-778](), [chai_lab/chai1.py:821-886](), [chai_lab/chai1.py:894-915](), [chai_lab/data/dataset/msas/utils.py:51-86]()

## Feature Generation System

### Feature Factory Architecture

The system uses a `FeatureFactory` that orchestrates multiple `feature_generators` to produce tensors for the model. These generators cover sequence, structure, MSA, and restraint-based features.

| Feature Type | Generator Class | Purpose |
|--------------|----------------|---------|
| Sequence Features | `RelativeSequenceSeparation` | Positional relationships [chai_lab/chai1.py:173]() |
| Token Features | `RelativeTokenSeparation` | Token-level distances [chai_lab/chai1.py:174]() |
| Structure Features | `BlockedAtomPairDistogram` | Atomic distance features [chai_lab/chai1.py:179]() |
| MSA Features | `MSAProfileGenerator` | Sequence alignment profiles [chai_lab/chai1.py:72]() |
| Template Features | `TemplateDistogramGenerator` | Structural template features [chai_lab/chai1.py:86]() |
| Restraint Features | `TokenDistanceRestraint` | User-defined constraints [chai_lab/chai1.py:93]() |

```mermaid
graph LR
    subgraph "Feature Generators"
        SeqGen["Sequence Generators<br/>RelativeSequenceSeparation<br/>RelativeTokenSeparation"]
        StructGen["Structure Generators<br/>BlockedAtomPairDistogram<br/>AtomElementOneHot"]
        MSAGen["MSA Generators<br/>MSAProfileGenerator<br/>MSAFeatureGenerator"]
        TemplateGen["Template Generators<br/>TemplateDistogramGenerator<br/>TemplateMaskGenerator"]
        RestraintGen["Restraint Generators<br/>TokenDistanceRestraint<br/>TokenPairPocketRestraint"]
    end
    
    subgraph "Feature Factory"
        FeatureFactory["FeatureFactory<br/>feature_generators dict"]
        FeatureType["FeatureType<br/>TOKEN, ATOM, ATOM_PAIR, etc."]
    end
    
    SeqGen --> FeatureFactory
    StructGen --> FeatureFactory
    MSAGen --> FeatureFactory
    TemplateGen --> FeatureFactory
    RestraintGen --> FeatureFactory
    
    FeatureFactory --> FeatureType
```

Sources: [chai_lab/chai1.py:172-236](), [chai_lab/data/features/feature_factory.py:13-25]()

## External Service Integration

### ColabFold MSA Generation

MSA generation is integrated via ColabFold, with support for template discovery and processing into the `TemplateContext`.

```mermaid
graph TB
    subgraph "MSA Processing"
        ProteinSeqs["Protein Sequences<br/>EntityType.PROTEIN"]
        ColabFoldAPI["ColabFold API<br/>msa_server_url"]
        A3MFiles["A3M Files<br/>Raw alignments"]
        AlignedPQT["Aligned PQT Files<br/>Processed alignments"]
        MSAContexts["MSA Contexts<br/>get_msa_contexts()"]
    end
    
    subgraph "Template Processing"
        TemplateHits["Template Hits<br/>.m8 format"]
        RCSBDownload["RCSB Download<br/>Structure files"]
        TemplateAlign["Template Alignment<br/>Sequence to structure"]
        TemplateCtx["TemplateContext<br/>Processed templates"]
    end
    
    ProteinSeqs --> ColabFoldAPI
    ColabFoldAPI --> A3MFiles
    A3MFiles --> AlignedPQT
    AlignedPQT --> MSAContexts
    
    ColabFoldAPI --> TemplateHits
    TemplateHits --> RCSBDownload
    RCSBDownload --> TemplateAlign
    TemplateAlign --> TemplateCtx
```

Sources: [chai_lab/chai1.py:389-402](), [chai_lab/chai1.py:422-438](), [chai_lab/data/dataset/msas/colabfold.py:20-45]()

## Configuration and Validation

### System Limits and Validation

The system enforces several limits to ensure computational feasibility, defined in the feature context and model metadata.

| Limit Type | Maximum Value | Source |
|------------|---------------|--------|
| Token Count | `max(AVAILABLE_MODEL_SIZES)` | [chai_lab/data/collate/utils.py:22]() |
| Template Count | `MAX_NUM_TEMPLATES = 4` | [chai_lab/data/dataset/all_atom_feature_context.py:21]() |
| MSA Depth | `MAX_MSA_DEPTH = 16384` | [chai_lab/data/dataset/all_atom_feature_context.py:20]() |

Sources: [chai_lab/chai1.py:255-277](), [chai_lab/data/dataset/all_atom_feature_context.py:20-21]()

## Output Generation and Ranking

### Structure Candidate Processing

The final stage involves ranking predicted structures based on confidence metrics and saving them to standard formats like CIF.

```mermaid
graph TB
    subgraph "Structure Generation"
        DiffusionOutput["Diffusion Output<br/>atom_pos coordinates"]
        ConfidenceScores["Confidence Scores<br/>PAE, PDE, pLDDT"]
        NumSamples["Sample Count<br/>num_diffn_samples"]
    end
    
    subgraph "Ranking System"
        FrameCalc["Frame Calculation<br/>get_frames_and_mask()"]
        RankFunc["Ranking Function<br/>rank()"]
        SampleRanking["SampleRanking<br/>Aggregate scores"]
    end
    
    subgraph "Output Files"
        CIFFiles["CIF Files<br/>save_to_cif()"]
        ScoreFiles["Score Files<br/>scores.model_idx_*.npz"]
        MSAPlot["MSA Plot<br/>plot_msa()"]
    end
    
    subgraph "Final Structure"
        StructureCandidates["StructureCandidates<br/>Sorted by score"]
    end
    
    DiffusionOutput --> FrameCalc
    ConfidenceScores --> RankFunc
    FrameCalc --> RankFunc
    RankFunc --> SampleRanking
    
    SampleRanking --> CIFFiles
    SampleRanking --> ScoreFiles
    SampleRanking --> StructureCandidates
    
    MSAPlot --> StructureCandidates
```

Sources: [chai_lab/chai1.py:989-1051](), [chai_lab/ranking/rank.py:104-105](), [chai_lab/data/io/cif_utils.py:98]()

## Memory Management and Device Handling

The system implements sophisticated memory management for handling large models via a JIT module cache and transient device movement.

### Component Caching and Device Movement

```mermaid
graph TB
    subgraph "Memory Management"
        ComponentCache["_component_cache<br/>dict[str, ModuleWrapper]"]
        ComponentMoved["_component_moved_to()<br/>Context manager"]
        DeviceMovement["Device Movement<br/>CPU ↔ GPU transfers"]
    end
    
    subgraph "Model Loading"
        JITLoad["torch.jit.load<br/>Model deserialization"]
        ModuleWrapper["ModuleWrapper<br/>Forward method wrapper"]
        LowMemory["low_memory flag<br/>CPU offloading"]
    end
    
    subgraph "Inference Components"
        FeatureEmbed["feature_embedding.pt"]
        TokenEmbed["token_embedder.pt"]
        Trunk["trunk.pt"]
        Diffusion["diffusion_module.pt"]
        Confidence["confidence_head.pt"]
    end
    
    ComponentCache --> ComponentMoved
    ComponentMoved --> DeviceMovement
    JITLoad --> ModuleWrapper
    ModuleWrapper --> ComponentCache
    
    ComponentMoved --> FeatureEmbed
    ComponentMoved --> TokenEmbed
    ComponentMoved --> Trunk
    ComponentMoved --> Diffusion
    ComponentMoved --> Confidence
    
    LowMemory --> DeviceMovement
```

Sources: [chai_lab/chai1.py:151-167](), [chai_lab/chai1.py:115-148]()

---