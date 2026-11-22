# Model Architecture

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [openfold/config.py](openfold/config.py)
- [openfold/model/dropout.py](openfold/model/dropout.py)
- [openfold/model/evoformer.py](openfold/model/evoformer.py)
- [openfold/model/model.py](openfold/model/model.py)
- [openfold/model/template.py](openfold/model/template.py)
- [openfold/model/triangular_attention.py](openfold/model/triangular_attention.py)
- [openfold/utils/tensor_utils.py](openfold/utils/tensor_utils.py)

</details>



The Model Architecture page describes the core neural network design and components that comprise the OpenFold implementation of AlphaFold 2 in PyTorch. This document covers the overall model structure, key components, and their interactions during protein structure prediction. For information about training the model, see [Training OpenFold](#4); for details about running inference, see [Running Inference](#3).

## Overall Architecture Overview

OpenFold's model architecture closely mirrors AlphaFold 2's design, implementing a deep learning system that predicts protein structures from sequence information, multiple sequence alignments (MSAs), and optional template information.

```mermaid
flowchart TD
    subgraph "Input Data"
        input["Input Features"]
        msa["MSA Features"]
        templ["Template Features"]
        seq["Sequence Features"]
    end

    subgraph "AlphaFold Model" 
        subgraph "Embedders"
            in_emb["InputEmbedder"]
            rec_emb["RecyclingEmbedder"]
            templ_emb["TemplateEmbedder"]
            ex_msa_emb["ExtraMSAEmbedder"]
        end
        
        subgraph "Processing Modules"
            evo["EvoformerStack"]
            ex_msa_stack["ExtraMSAStack"]
            templ_stack["TemplatePairStack"]
            struct["StructureModule"]
        end
        
        subgraph "Outputs"
            aux["AuxiliaryHeads"]
            coords["3D Coordinates"]
        end
    end
    
    input --> in_emb
    msa --> in_emb
    seq --> in_emb
    
    in_emb --> m["MSA Representation (m)"]
    in_emb --> z["Pair Representation (z)"]
    
    templ --> templ_emb
    templ_emb --> templ_stack
    templ_stack --> z
    
    ex_msa_emb --> ex_msa_stack
    ex_msa_stack --> z
    
    m --> evo
    z --> evo
    evo --> m_out["Updated MSA"]
    evo --> z_out["Updated Pair"]
    evo --> s["Single Representation (s)"]
    
    m_out --> struct
    z_out --> struct
    s --> struct
    
    struct --> coords
    
    m_out --> aux
    z_out --> aux
    s --> aux
    coords --> aux
    
    coords --> rec["Recycling Input"]
    z_out --> rec
    m_out --> rec
    rec --> rec_emb
    rec_emb --> m
    rec_emb --> z
```

Sources: [openfold/model/model.py:65-492](), [openfold/config.py:61-260]()

## Model Components and Data Flow

The OpenFold architecture consists of the following key components that process data through the system:

| Component | Purpose | Implementation |
|-----------|---------|----------------|
| InputEmbedder | Embeds sequence and MSA features into initial representations | [model/embedders.py]() |
| RecyclingEmbedder | Incorporates information from previous iterations | [model/embedders.py]() |
| TemplateEmbedder | Processes template information | [model/template.py]() |
| ExtraMSAEmbedder | Embeds additional MSA sequences | [model/embedders.py]() |
| EvoformerStack | Core processing module for MSA and pair representations | [model/evoformer.py]() |
| ExtraMSAStack | Processes extra MSA information | [model/evoformer.py]() |
| StructureModule | Converts embeddings to 3D coordinates | [model/structure_module.py]() |
| AuxiliaryHeads | Produces additional outputs like confidence scores | [model/heads.py]() |

The AlphaFold class ([openfold/model/model.py:65-591]()) orchestrates these components, implementing the recycling mechanism that allows the model to refine its predictions over multiple iterations.

## Code Structure and Class Relationships

This diagram maps the model components to their corresponding classes in the codebase:

```mermaid
classDiagram
    AlphaFold --> InputEmbedder
    AlphaFold --> RecyclingEmbedder
    AlphaFold --> TemplateEmbedder
    AlphaFold --> ExtraMSAEmbedder
    AlphaFold --> ExtraMSAStack
    AlphaFold --> EvoformerStack
    AlphaFold --> StructureModule
    AlphaFold --> AuxiliaryHeads
    
    EvoformerStack --> EvoformerBlock
    EvoformerBlock --> MSARowAttentionWithPairBias
    EvoformerBlock --> MSAColumnAttention
    EvoformerBlock --> MSATransition
    EvoformerBlock --> OuterProductMean
    EvoformerBlock --> PairStack
    
    PairStack --> TriangleMultiplicationOutgoing
    PairStack --> TriangleMultiplicationIncoming
    PairStack --> TriangleAttentionStartingNode
    PairStack --> TriangleAttentionEndingNode
    PairStack --> PairTransition
    
    ExtraMSAStack --> ExtraMSABlock
    
    TemplateEmbedder --> TemplatePairStack
    TemplateEmbedder --> TemplatePointwiseAttention
    TemplatePairStack --> TemplatePairStackBlock
    
    StructureModule --> InvariantPointAttention
    StructureModule --> BackboneUpdate
    StructureModule --> AngleResnet
    
    AuxiliaryHeads --> DistogramHead
    AuxiliaryHeads --> PredictedLDDTHead
    AuxiliaryHeads --> TMScoreHead
    AuxiliaryHeads --> MaskedMSAHead
    
    class AlphaFold {
        forward(batch)
        iteration(feats, prevs)
        embed_templates(batch, z, pair_mask)
    }
    
    class EvoformerStack {
        c_m: int
        c_z: int
        no_blocks: int
        forward(m, z, msa_mask, pair_mask)
    }
    
    class StructureModule {
        forward(s, z, aatype, mask)
    }
```

Sources: [openfold/model/model.py:65-492](), [openfold/model/evoformer.py:748-1025]()

## Model Initialization and Configuration

The model is initialized with a comprehensive configuration object defined in [openfold/config.py]() that controls all architectural aspects. Different model presets are available, including:

- Model variants (1-5) with different architectural choices
- PTM variants with template modeling score prediction
- Multimer variants for multi-chain protein complexes
- Sequence embedding variants for no-MSA inference

The `model_config` function in [openfold/config.py:61-260]() provides these preset configurations.

```python
model = AlphaFold(config)
```

## Input Processing and Embedding

The model processes several types of input features:

1. **Target sequence features**: One-hot encoded sequence information
2. **MSA features**: Multiple sequence alignment information
3. **Template features**: Structural templates from similar proteins
4. **Extra MSA features**: Additional sequences for evolutionary information

These inputs are embedded into initial representations by specialized embedders:

```mermaid
flowchart TD
    subgraph "Input Embedders"
        direction LR
        input_standard["InputEmbedder"]
        input_multimer["InputEmbedderMultimer"]
        input_seqemb["PreembeddingEmbedder"]
    end
    
    seqemb_input["Sequence Embeddings"] --> input_seqemb
    target_feat["Target Features"] --> input_standard
    residue_index["Residue Index"] --> input_standard
    msa_feat["MSA Features"] --> input_standard
    
    multimer_inputs["Multimer Features"] --> input_multimer
    
    input_standard --> pair_repr["Pair Representation (z)"]
    input_standard --> msa_repr["MSA Representation (m)"]
    input_multimer --> pair_repr
    input_multimer --> msa_repr
    input_seqemb --> pair_repr
    input_seqemb --> msa_repr
    
    recycling["Recycling Embedder"] --> pair_repr
    recycling --> msa_repr
    
    prev_m["Previous MSA"] --> recycling
    prev_z["Previous Pair"] --> recycling
    prev_x["Previous Coords"] --> pseudo_beta["Pseudo-Beta Calculation"]
    pseudo_beta --> recycling
```

Sources: [openfold/model/model.py:87-100](), [openfold/model/model.py:232-258]()

## The Evoformer Stack

The Evoformer is the core processing module in OpenFold, responsible for iteratively refining the MSA and pair representations. It consists of multiple EvoformerBlocks stacked together.

```mermaid
flowchart TB
    subgraph "EvoformerStack"
        direction TB
        
        subgraph "EvoformerBlock 1..N"
            direction LR
            
            msa_input["MSA Input (m)"] --> msa_row["MSA Row Attention"]
            pair_input["Pair Input (z)"] --> msa_row
            
            msa_row --> msa_col["MSA Column Attention"]
            msa_col --> msa_trans["MSA Transition"]
            
            msa_trans --> opm["Outer Product Mean"]
            opm --> pair_update["Pair Update"]
            pair_input --> pair_stack["Pair Stack"]
            pair_update --> pair_stack
            
            subgraph "Pair Stack"
                direction TB
                tri_mul_out["Triangle Multiplication Outgoing"]
                tri_mul_in["Triangle Multiplication Incoming"]
                tri_att_start["Triangle Attention Starting Node"]
                tri_att_end["Triangle Attention Ending Node"]
                pair_trans["Pair Transition"]
                
                tri_mul_out --> tri_mul_in
                tri_mul_in --> tri_att_start
                tri_att_start --> tri_att_end
                tri_att_end --> pair_trans
            end
            
            msa_trans --> msa_output["MSA Output"]
            pair_stack --> pair_output["Pair Output"]
        end
        
        linear["Linear Projection"] --> single["Single Representation (s)"]
    end
    
    msa_in["Input MSA Representation"] --> EvoformerStack
    pair_in["Input Pair Representation"] --> EvoformerStack
    
    EvoformerStack --> msa_out["Output MSA Representation"]
    EvoformerStack --> pair_out["Output Pair Representation"]
    EvoformerStack --> single_out["Single Representation"]
```

Sources: [openfold/model/evoformer.py:747-1025](), [openfold/model/evoformer.py:377-552]()

The EvoformerStack typically consists of 48 identical blocks, each performing several transformations on the MSA and pair representations:

1. **MSA Row Attention with Pair Bias**: Attention between sequences, biased by pair information
2. **MSA Column Attention**: Attention between positions in the sequence
3. **MSA Transition**: Feed-forward network applied to MSA
4. **Outer Product Mean**: Connects MSA and pair representations
5. **Pair Stack**: Series of operations on the pair representation
   - Triangle Multiplication: Outgoing and Incoming variants
   - Triangle Attention: Starting Node and Ending Node variants
   - Pair Transition: Feed-forward network for pairs

## Template Processing

Template information provides structural priors derived from similar proteins. This information is processed through several specialized modules:

```mermaid
flowchart TB
    template_feats["Template Features"] --> template_pair_feat["build_template_pair_feat()"]
    template_feats --> template_angle_feat["build_template_angle_feat()"]
    
    template_pair_feat --> template_pair_embedder["Template Pair Embedder"]
    template_angle_feat --> template_single_embedder["Template Single Embedder"]
    
    template_pair_embedder --> template_pair_stack["Template Pair Stack"]
    
    template_pair_stack --> template_pointwise_att["Template Pointwise Attention"]
    z["Pair Representation (z)"] --> template_pointwise_att
    
    template_pointwise_att --> z_update["Updated Pair Representation"]
    template_single_embedder --> msa_update["Updated MSA Representation"]
    
    subgraph "Memory Optimization Variants"
        embed_templates_offload["embed_templates_offload()"]
        embed_templates_average["embed_templates_average()"]
    end
```

Sources: [openfold/model/template.py:136-692](), [openfold/model/model.py:325-342]()

OpenFold implements two memory-efficient template processing methods:
1. `embed_templates_offload`: Offloads template tensors to CPU to save GPU memory
2. `embed_templates_average`: Processes templates in groups and averages them

## Structure Module

The Structure Module transforms the embeddings from the Evoformer into 3D atomic coordinates, predicting the protein structure:

```mermaid
flowchart TB
    s["Single Representation (s)"] --> struct_module["Structure Module"]
    z["Pair Representation (z)"] --> struct_module
    aatype["Amino Acid Types"] --> struct_module
    
    subgraph "Structure Module"
        ipa["Invariant Point Attention (IPA)"]
        angle_resnet["Angle Resnet"]
        backbone_update["Backbone Update"]
        
        ipa --> angle_resnet
        angle_resnet --> backbone_update
    end
    
    struct_module --> final_atom_pos["Final Atom Positions"]
    struct_module --> final_affine["Final Affine Tensor"]
```

Sources: [openfold/model/model.py:442-454]()

## Recycling Mechanism

OpenFold implements an iterative refinement process called recycling. In each recycling iteration:

1. The model generates MSA, pair representations, and 3D coordinates
2. These outputs are used as inputs for the next iteration
3. The process continues for a fixed number of iterations or until convergence

```mermaid
sequenceDiagram
    participant Input as Input Features
    participant Model as AlphaFold Model
    participant RecycleEmbed as Recycling Embedder
    participant Output as Final Output
    
    Input->>Model: Initial features
    Model->>+RecycleEmbed: MSA (m_1_prev)
    Model->>RecycleEmbed: Pair (z_prev)
    Model->>RecycleEmbed: Coords (x_prev)
    RecycleEmbed-->>-Model: Updated embeddings
    
    loop Recycling Iterations
        Input->>Model: Features
        Model->>+RecycleEmbed: Updated MSA (m_1_prev)
        Model->>RecycleEmbed: Updated Pair (z_prev)
        Model->>RecycleEmbed: Updated Coords (x_prev)
        RecycleEmbed-->>-Model: Updated embeddings
    end
    
    Model->>Output: Final structure & confidence
```

Sources: [openfold/model/model.py:209-473](), [openfold/model/model.py:544-586]()

The `recycle_early_stop_tolerance` parameter allows early stopping when consecutive iterations produce similar structures, improving efficiency.

## Auxiliary Outputs

In addition to the 3D structure, OpenFold produces several auxiliary outputs:

1. **pLDDT**: Per-residue confidence scores
2. **Distogram**: Distance distribution predictions between residues
3. **TM-score**: Template modeling score prediction (in PTM variants)
4. **Masked MSA**: Used during training for MSA completion tasks

These outputs are generated by specialized heads in the `AuxiliaryHeads` class.

## Memory Optimization Techniques

OpenFold incorporates several memory optimization techniques to enable processing of long sequences and multi-chain complexes:

1. **Activation checkpointing**: Reduces memory during backpropagation
2. **Chunk-based processing**: Splits computations into manageable chunks
3. **Template offloading**: Moves template tensors to CPU when not needed
4. **Low-memory attention**: Optional memory-efficient attention implementations
5. **DeepSpeed integration**: For memory-efficient attention kernels

Sources: [openfold/model/evoformer.py:876-895](), [openfold/model/template.py:472-580](), [openfold/config.py:230-236]()

## Model Variants and Configuration

OpenFold supports various model configurations through the configuration system in [openfold/config.py:61-260]():

| Model Variant | Description |
|---------------|-------------|
| Model_1 to Model_5 | Different architectural settings matching AlphaFold2 presets |
| PTM variants | Include template modeling score prediction |
| Multimer variants | For multi-chain protein complexes |
| Sequence embedding | For running without MSAs using ESM-1b embeddings |

These configurations control architectural choices like:
- Number of Evoformer blocks
- Use of templates
- Size of extra MSA inputs
- Attention mechanism details

The `model_config` function provides these preset configurations, which can be further customized.

---