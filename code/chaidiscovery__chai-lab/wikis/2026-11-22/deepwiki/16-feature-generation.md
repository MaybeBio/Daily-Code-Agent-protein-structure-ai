# Feature Generation

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [chai_lab/chai1.py](chai_lab/chai1.py)
- [chai_lab/data/dataset/msas/utils.py](chai_lab/data/dataset/msas/utils.py)
- [chai_lab/data/features/generators/__init__.py](chai_lab/data/features/generators/__init__.py)

</details>



Feature Generation is a critical process in the Chai-1 molecular structure prediction pipeline, responsible for transforming raw biological data into structured features that enable accurate structure prediction. This page documents the feature generation process, including how different biological data sources are processed, integrated, and prepared for input to the structure prediction model.

For information about specific feature types, see [Multiple Sequence Alignments](#5.1), [Structural Templates](#5.2), [ESM Embeddings](#5.3), and [Restraints and Constraints](#5.4).

## Feature Generation Overview

The feature generation process integrates information from multiple biological data sources to create a comprehensive representation of the molecular system. This representation captures evolutionary information, structural templates, sequence embeddings, and spatial constraints that guide the structure prediction.

### Feature Generation Pipeline

```mermaid
flowchart TD
    InputData["Input Data\n(FASTA, SMILES, Glycans)"] --> AllAtomStructureContext["AllAtomStructureContext\nmake_all_atom_feature_context()"]
    
    subgraph "MSA Generation"
        MSASource["Protein Sequences"] --> generate_colabfold_msas["generate_colabfold_msas()"]
        generate_colabfold_msas --> _run_mmseqs2["_run_mmseqs2()"]
        _run_mmseqs2 --> A3MFiles["A3M Files\n(pair.a3m, uniref.a3m)"]
        A3MFiles --> AlignedPQT["aligned.pqt Files\n(expected_basename())"]
        AlignedPQT --> MSAContext["MSAContext"]
    end
    
    subgraph "Template Processing"
        TemplateHits["Template Hits\n(pdb70.m8)"] --> parse_m8_file["parse_m8_file()"]
        parse_m8_file --> TemplateContext["TemplateContext"]
    end
    
    subgraph "Other Features"
        ESMSource["ESM Embeddings\nget_esm_embedding_context()"] --> EmbeddingContext["EmbeddingContext"]
        RestraintSource["Restraints\nload_manual_restraints_for_chai1()"] --> RestraintContext["RestraintContext"]
    end
    
    MSAContext --> AllAtomFeatureContext["AllAtomFeatureContext"]
    TemplateContext --> AllAtomFeatureContext
    EmbeddingContext --> AllAtomFeatureContext
    RestraintContext --> AllAtomFeatureContext
    AllAtomStructureContext --> AllAtomFeatureContext
    
    AllAtomFeatureContext --> FeatureProcessing["Feature Processing\nFeatureFactory"]
    FeatureProcessing --> EncodedFeatures["Encoded Features"]
    EncodedFeatures --> ModelInput["Model Input\nfor Structure Prediction"]
```

Sources: [chai_lab/chai1.py:343-498](), [chai_lab/data/dataset/msas/colabfold.py:296-459]()

## Feature Context

The central data structure in the feature generation process is the `AllAtomFeatureContext`, which integrates various types of information about the molecular system:

```mermaid
classDiagram
    class AllAtomFeatureContext {
        +chains
        +structure_context: AllAtomStructureContext
        +msa_context: MSAContext
        +profile_msa_context: MSAContext
        +template_context: TemplateContext
        +embedding_context: EmbeddingContext
        +restraint_context: RestraintContext
    }
    
    class AllAtomStructureContext {
        +token_residue_type
        +token_asym_id
        +atom_token_index
        +atom_ref_element
        +atom_exists_mask
        +drop_glycan_leaving_atoms_inplace()
    }
    
    class MSAContext {
        +tokens
        +mask
        +depth
        +pairing_key_hash
        +deletion_matrix
    }
    
    class TemplateContext {
        +template_mask
        +template_positions
        +template_unit_vector
        +template_residue_type
        +num_templates
    }
    
    class EmbeddingContext {
        +embeddings
    }
    
    class RestraintContext {
        +docking_restraints
        +contact_restraints
        +pocket_restraints
    }
    
    AllAtomFeatureContext *-- AllAtomStructureContext
    AllAtomFeatureContext *-- MSAContext : msa_context
    AllAtomFeatureContext *-- MSAContext : profile_msa_context
    AllAtomFeatureContext *-- TemplateContext
    AllAtomFeatureContext *-- EmbeddingContext
    AllAtomFeatureContext *-- RestraintContext
```

Sources: [chai_lab/chai1.py:490-497](), [chai_lab/data/dataset/all_atom_feature_context.py:33-56]()

The `make_all_atom_feature_context` function constructs this context by:
1. Loading chains from the input sequence data [chai_lab/chai1.py:372-377]()
2. Generating or loading MSAs from a server or local directory [chai_lab/chai1.py:392-414]()
3. Obtaining template information if available [chai_lab/chai1.py:416-432]()
4. Computing ESM embeddings if requested [chai_lab/chai1.py:434-441]()
5. Incorporating any restraints specified in constraint files [chai_lab/chai1.py:443-455]()
6. Processing special structural elements like glycan bonds [chai_lab/chai1.py:465-485]()

## Feature Generators

Chai-1 uses a collection of feature generators to transform the raw biological data into model-ready features. Each generator specializes in producing a specific type of feature:

```mermaid
flowchart LR
    FeatureFactory["FeatureFactory"] --> SequenceFeatures["Sequence Features"]
    FeatureFactory --> MSAFeatures["MSA Features"]
    FeatureFactory --> TemplateFeatures["Template Features"]
    FeatureFactory --> EmbeddingFeatures["Embedding Features"]
    FeatureFactory --> RestraintFeatures["Restraint Features"]
    FeatureFactory --> AtomFeatures["Atom-level Features"]
    
    subgraph "Sequence Feature Generators"
        SequenceFeatures --> ResidueType["ResidueType"]
        SequenceFeatures --> RelSeqSep["RelativeSequenceSeparation"]
        SequenceFeatures --> RelTokenSep["RelativeTokenSeparation"]
        SequenceFeatures --> RelEntity["RelativeEntity"]
        SequenceFeatures --> RelChain["RelativeChain"]
    end
    
    subgraph "MSA Feature Generators"
        MSAFeatures --> MSAProfile["MSAProfile"]
        MSAFeatures --> MSAOneHot["MSAFeatureGenerator"]
        MSAFeatures --> MSADelMean["MSADeletionMeanGenerator"]
        MSAFeatures --> MSADelVal["MSADeletionValueGenerator"]
        MSAFeatures --> MSAHasDel["MSAHasDeletionGenerator"]
        MSAFeatures --> IsPairedMSA["IsPairedMSAGenerator"]
        MSAFeatures --> MSADataSource["MSADataSourceGenerator"]
    end
    
    subgraph "Template Feature Generators"
        TemplateFeatures --> TemplateMask["TemplateMaskGenerator"]
        TemplateFeatures --> TemplateUV["TemplateUnitVectorGenerator"]
        TemplateFeatures --> TemplateRT["TemplateResTypeGenerator"]
        TemplateFeatures --> TemplateDG["TemplateDistogramGenerator"]
    end
    
    subgraph "Restraint Feature Generators"
        RestraintFeatures --> TokenDistRestr["TokenDistanceRestraint"]
        RestraintFeatures --> DockingConstrGen["DockingRestraintGenerator"]
        RestraintFeatures --> TokenPairPocket["TokenPairPocketRestraint"]
        RestraintFeatures --> TokenBondRestr["TokenBondRestraint"]
    end
    
    subgraph "Atom Feature Generators"
        AtomFeatures --> AtomRefPos["RefPos"]
        AtomFeatures --> AtomRefCharge["Identity (atom_ref_charge)"]
        AtomFeatures --> AtomRefMask["Identity (atom_exists_mask)"]
        AtomFeatures --> AtomRefElement["AtomElementOneHot"]
        AtomFeatures --> AtomNameOneHot["AtomNameOneHot"]
        AtomFeatures --> BlockedPairDist["BlockedAtomPairDistogram"]
    end
```

Sources: [chai_lab/chai1.py:172-241]()

## Feature Generation Process Flow

The feature generation process flows from raw inputs to model-ready features:

```mermaid
sequenceDiagram
    participant Input as "Input Data"
    participant Context as "Feature Context Creation"
    participant Processing as "Feature Processing"
    participant Embedder as "Feature Embedder"
    participant Model as "Model Input"
    
    Input ->> Context: FASTA/SMILES sequences
    Input ->> Context: MSA data (if available)
    Input ->> Context: Template structures (if available)
    Input ->> Context: Restraint specifications (if available)
    
    Context ->> Context: Create AllAtomStructureContext
    Context ->> Context: Generate/load MSA context
    Context ->> Context: Get template context
    Context ->> Context: Compute ESM embeddings
    Context ->> Context: Load restraints
    
    Context ->> Processing: AllAtomFeatureContext
    Processing ->> Processing: Apply FeatureFactory.generate_features()
    Processing ->> Embedder: Raw features
    
    Embedder ->> Embedder: token_single_input_feats
    Embedder ->> Embedder: token_pair_input_feats
    Embedder ->> Embedder: atom_single_input_feats
    Embedder ->> Embedder: block_atom_pair_input_feats
    Embedder ->> Embedder: template_input_feats
    Embedder ->> Embedder: msa_input_feats
    
    Embedder ->> Model: Embedded features
```

Sources: [chai_lab/chai1.py:500-755](), [chai_lab/data/features/feature_factory.py:38-54]()

## ColabFold MSA Generation

The system uses ColabFold servers for MSA generation through the `generate_colabfold_msas()` function. This process involves both paired and unpaired MSA generation, followed by conversion to the internal `.aligned.pqt` format.

For details, see [Multiple Sequence Alignments](#5.1).

Sources: [chai_lab/data/dataset/msas/colabfold.py:296-459]()

## MSA Subsampling

For large Multiple Sequence Alignments (MSAs), Chai-1 implements subsampling to reduce computational requirements while maintaining the diversity of evolutionary information. The function `subsample_and_reorder_msa_feats_n_mask` handles this by scoring rows based on size and a random factor to select the most informative hits.

```mermaid
flowchart TD
    FullMSA["Full MSA\n(potentially large)"] --> SubsampleFunc["subsample_and_reorder_msa_feats_n_mask()"]
    SubsampleFunc --> SizeCheck{"MSA depth > select_n_rows?"}
    SizeCheck -- "Yes" --> ScoreMSARows["Score MSA rows\n(msa_sizes * torch.rand)"]
    SizeCheck -- "No" --> ReturnOriginal["Return original MSA"]
    ScoreMSARows --> SelectTopRows["Select top N rows"]
    SelectTopRows --> ReorderFeatures["Reorder features\n(selected rows first)"]
    ReorderFeatures --> PadMask["Pad mask to original size"]
    PadMask --> SubsampledMSA["Subsampled MSA"]
```

Sources: [chai_lab/data/dataset/msas/utils.py:15-86]()

## Feature Embedding

After feature generation, the features are embedded through specialized neural network components. In the inference pipeline, the `feature_factory` is used to generate raw tensors [chai_lab/chai1.py:656-663](), which are then passed to the JIT-loaded model components for embedding.

1. **Token Embedder**: Processes token-level features into initial representations.
2. **Trunk**: Integrates information across tokens through multiple recycles, utilizing MSA and template features.
3. **Diffusion**: Uses the embedded features to guide the prediction of 3D coordinates.

Sources: [chai_lab/chai1.py:656-755]()

## Types of Features and Their Purpose

| Feature Type | Description | Key Generators | Purpose |
|--------------|-------------|----------------|---------|
| Sequence Features | Token-level information about residue types and positions | `ResidueType`, `RelativeSequenceSeparation` | Provide basic sequence information |
| MSA Features | Evolutionary information from homologous sequences | `MSAProfileGenerator`, `MSADeletionMeanGenerator` | Capture evolutionary conservation patterns |
| Template Features | Information from structural templates | `TemplateMaskGenerator`, `TemplateUnitVectorGenerator` | Guide prediction based on similar known structures |
| ESM Embeddings | Representations from protein language models | `ESMEmbeddings` | Capture sequence context and patterns |
| Restraint Features | Spatial constraints to guide prediction | `TokenDistanceRestraint`, `DockingRestraintGenerator` | Enforce spatial relationships between entities |
| Atom-level Features | Information about atoms within residues | `RefPos`, `AtomElementOneHot`, `AtomNameOneHot` | Define chemical properties and initial positions |

Sources: [chai_lab/chai1.py:172-241](), [chai_lab/data/dataset/msas/colabfold.py:296-459]()

---