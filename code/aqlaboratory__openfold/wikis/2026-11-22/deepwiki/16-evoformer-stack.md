# Evoformer Stack

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



The Evoformer Stack is the central neural network component of AlphaFold 2, responsible for jointly processing Multiple Sequence Alignment (MSA) and pair representations to extract evolutionary and structural information for protein structure prediction. This page explains the architecture, components, and implementation details of the Evoformer Stack in the OpenFold codebase.

For information about the Structure Module that transforms the Evoformer outputs into 3D coordinates, see [Structure Module](#5.2).

## Overview

The Evoformer Stack processes two main tensor representations:
- An MSA representation capturing evolutionary information (shape: `[batch, N_seq, N_res, c_m]`)
- A pair representation capturing residue-pair interactions (shape: `[batch, N_res, N_res, c_z]`)

Through a series of attention and transformation operations, the Evoformer iteratively refines these representations, enabling accurate protein structure prediction.

```mermaid
flowchart LR
    subgraph "Inputs"
        MSA["MSA Representation\n[batch, N_seq, N_res, c_m]"]
        Pair["Pair Representation\n[batch, N_res, N_res, c_z]"]
    end
    
    subgraph "EvoformerStack"
        Block1["EvoformerBlock 1"]
        Block2["EvoformerBlock 2"]
        BlockN["EvoformerBlock n"]
        Dots["..."]
        
        Block1 --> Block2
        Block2 --> Dots
        Dots --> BlockN
    end
    
    MSA --> Block1
    Pair --> Block1
    
    subgraph "Outputs"
        MSA_out["Updated MSA\n[batch, N_seq, N_res, c_m]"]
        Pair_out["Updated Pair\n[batch, N_res, N_res, c_z]"]
        Single["Single Representation\n[batch, N_res, c_s]"]
    end
    
    BlockN --> MSA_out
    BlockN --> Pair_out
    BlockN --> Single
```

Sources: 
- [openfold/model/evoformer.py:124-134]()
- [openfold/model/model.py:416-434]()

## Evoformer Stack Architecture

The Evoformer Stack consists of a series of identical EvoformerBlocks that process MSA and pair representations. The stack architecture is defined in `EvoformerStack` class:

```mermaid
classDiagram
    class EvoformerStack {
        +forward(m, z, msa_mask, pair_mask, chunk_size)
        -blocks_per_ckpt
        -no_blocks
        -layer_norm_m
        -layer_norm_z
        -linear
    }
    
    EvoformerStack *-- EvoformerBlock : contains multiple
    
    class EvoformerBlock {
        +msa_att_row
        +msa_att_col
        +msa_transition
        +outer_product_mean
        +pair_stack
        +forward(m, z, msa_mask, pair_mask)
    }
    
    EvoformerBlock *-- MSARowAttentionWithPairBias : msa_att_row
    EvoformerBlock *-- MSAColumnAttention : msa_att_col
    EvoformerBlock *-- MSATransition : msa_transition
    EvoformerBlock *-- OuterProductMean : outer_product_mean
    EvoformerBlock *-- PairStack : pair_stack
```

Sources:
- [openfold/model/evoformer.py:377-552]()
- [openfold/model/model.py:123-134]()

### Key Parameters and Configuration

The Evoformer Stack has several important parameters that control its size and behavior:

| Parameter | Description | Default Value |
|-----------|-------------|--------------|
| `c_m` | MSA channel dimension | 256 |
| `c_z` | Pair channel dimension | 128 |
| `c_s` | Single representation dimension | 384 |
| `no_heads_msa` | Number of MSA attention heads | 8 |
| `no_heads_pair` | Number of pair attention heads | 4 |
| `no_blocks` | Number of Evoformer blocks | 48 |
| `transition_n` | Multiplier for transition hidden dimension | 4 |
| `blocks_per_ckpt` | Number of blocks per activation checkpoint | Varies |
| `clear_cache_between_blocks` | Whether to clear attention cache | False |

Sources:
- [openfold/config.py:590-611]()
- [openfold/model/evoformer.py:257-264]()

## EvoformerBlock

Each EvoformerBlock contains a series of operations that update the MSA and pair representations. These operations include various forms of attention and information exchange between the representations.

```mermaid
flowchart TB
    subgraph "EvoformerBlock"
        direction TB
        
        subgraph "MSA Processing"
            direction TB
            MSA_row["MSA Row Attention\nwith Pair Bias"]
            MSA_col["MSA Column Attention"]
            MSA_trans["MSA Transition"]
        end
        
        subgraph "Information Exchange"
            direction TB
            OPM["Outer Product Mean"]
        end
        
        subgraph "Pair Processing"
            direction TB
            Tri_mul_out["Triangle Multiplication\nOutgoing"]
            Tri_mul_in["Triangle Multiplication\nIncoming"]
            Tri_att_start["Triangle Attention\nStarting Node"]
            Tri_att_end["Triangle Attention\nEnding Node"]
            Pair_trans["Pair Transition"]
        end
        
        MSA_in["MSA Input"] --> MSA_row
        Pair_in["Pair Input"] --> MSA_row
        
        MSA_row --> MSA_col
        MSA_col --> MSA_trans
        
        MSA_trans --> OPM
        
        OPM --> Pair_in
        
        Pair_in --> Tri_mul_out
        Tri_mul_out --> Tri_mul_in
        Tri_mul_in --> Tri_att_start
        Tri_att_start --> Tri_att_end
        Tri_att_end --> Pair_trans
    end
    
    MSA_trans --> MSA_out["MSA Output"]
    Pair_trans --> Pair_out["Pair Output"]
```

Sources:
- [openfold/model/evoformer.py:397-552]()

### Processing Flow

The EvoformerBlock combines several mechanisms to process the MSA and pair representations:

1. **MSA Processing**:
   - **MSA Row Attention with Pair Bias**: Applies attention along rows of the MSA, biased by the pair representation
   - **MSA Column Attention**: Applies attention along columns of the MSA
   - **MSA Transition**: A feed-forward network applied to the MSA

2. **Information Exchange**:
   - **Outer Product Mean**: Computes the outer product of MSA features and aggregates, updating the pair representation

3. **Pair Processing (PairStack)**:
   - **Triangle Multiplication**: Outgoing and incoming variants for updating pair information
   - **Triangle Attention**: Starting and ending node variants for attending to different parts of the pair matrix
   - **Pair Transition**: A feed-forward network applied to the pair representation

The order of operations can be customized, with the `opm_first` parameter determining whether the Outer Product Mean is applied before or after MSA attention.

Sources:
- [openfold/model/evoformer.py:423-552]()
- [openfold/model/evoformer.py:123-267]()

## MSA Attention Mechanisms

The Evoformer uses several attention mechanisms to process the MSA representation:

### MSA Row Attention with Pair Bias

This mechanism applies attention along the rows of the MSA, with the attention being biased by the pair representation. This allows pair information to influence how MSA rows attend to each other.

```mermaid
flowchart LR
    M["MSA [batch, N_seq, N_res, c_m]"] --> LayerNorm["Layer Norm"]
    Z["Pair [batch, N_res, N_res, c_z]"] --> LayerNormZ["Layer Norm"]
    
    LayerNorm --> Q["Query"]
    LayerNorm --> K["Key"]
    LayerNorm --> V["Value"]
    
    LayerNormZ --> LinearZ["Linear"]
    LinearZ --> ZBias["Pair Bias [batch, 1, H, N_res, N_res]"]
    
    Q --> Attention
    K --> Attention
    V --> Attention
    ZBias --> Attention["Multi-head Attention"]
    
    Attention --> Output["Updated MSA"]
```

Sources:
- [openfold/model/msa.py:295-321]()
- [openfold/model/primitives.py:340-547]()

### MSA Column Attention

This attention mechanism operates along the columns of the MSA, allowing residues to attend to each other across sequences. This helps to capture evolutionary conservation patterns.

```mermaid
flowchart LR
    M["MSA [batch, N_seq, N_res, c_m]"] --> Transpose["Transpose to [batch, N_res, N_seq, c_m]"]
    Transpose --> MSAAttention["MSA Attention"]
    MSAAttention --> TransposeBack["Transpose back to [batch, N_seq, N_res, c_m]"]
    TransposeBack --> Output["Updated MSA"]
```

Sources:
- [openfold/model/msa.py:324-397]()

### MSA Transition

After the attention mechanisms, a feed-forward network is applied to the MSA representation to introduce non-linearity:

```mermaid
flowchart LR
    M["MSA [batch, N_seq, N_res, c_m]"] --> LayerNorm["Layer Norm"]
    LayerNorm --> Linear1["Linear(c_m, n*c_m)"]
    Linear1 --> ReLU["ReLU"]
    ReLU --> Linear2["Linear(n*c_m, c_m)"]
    Linear2 --> Mask["Mask * Dropout"]
    Mask --> Output["Updated MSA"]
```

Sources:
- [openfold/model/evoformer.py:48-120]()

## Pair Processing Components

The pair representation is processed through a series of specialized operations in the `PairStack` class:

### Triangle Multiplication

Triangle multiplication is a unique operation that updates the pair representation by multiplying it with itself in different ways:

```mermaid
flowchart TB
    Z["Pair [batch, N_res, N_res, c_z]"] --> LayerNorm["Layer Norm"]
    
    subgraph "Outgoing Triangle Multiplication"
        Z_i["Z_i"] --> Linear_a["Linear_a"]
        Z_j["Z_j"] --> Linear_b["Linear_b"]
        Linear_a --> MatMul["MatMul(Linear_a(Z_i), Linear_b(Z_j))"]
        MatMul --> Linear_g["Linear_g(gate)"]
        MatMul --> Linear_c["Linear_c"]
        Linear_g --> Sigmoid["Sigmoid"]
        Sigmoid --> Mult["*"]
        Linear_c --> Mult
    end
    
    Mult --> Add["+ Z (residual)"]
    Add --> Output["Updated Z"]
```

Sources:
- [openfold/model/triangular_multiplicative_update.py]()

### Triangle Attention

Triangle attention is a specialized form of attention that operates on the pair representation, with two variants:

1. **Triangle Attention Starting Node**: Attention where each position attends to all other positions (operating row-wise)
2. **Triangle Attention Ending Node**: Attention where all positions attend to each position (operating column-wise)

```mermaid
flowchart LR
    Z["Pair [batch, N_res, N_res, c_z]"] --> LayerNorm["Layer Norm"]
    
    LayerNorm --> Linear["Linear (bias term)"]
    LayerNorm --> Attention["Multi-head Attention"]
    
    Linear --> BiasAdd["Add as bias"]
    BiasAdd --> Attention
    
    Attention --> Output["Updated Z"]
```

Sources:
- [openfold/model/triangular_attention.py:31-164]()

### Pair Transition

Similar to the MSA transition, a feed-forward network is applied to the pair representation:

```mermaid
flowchart LR
    Z["Pair [batch, N_res, N_res, c_z]"] --> LayerNorm["Layer Norm"]
    LayerNorm --> Linear1["Linear(c_z, n*c_z)"]
    Linear1 --> ReLU["ReLU"]
    ReLU --> Linear2["Linear(n*c_z, c_z)"]
    Linear2 --> Mask["Mask * Dropout"]
    Mask --> Output["Updated Z"]
```

Sources:
- [openfold/model/pair_transition.py:24-99]()

## Information Exchange: Outer Product Mean

The Outer Product Mean is a critical operation that allows information to flow from the MSA representation to the pair representation:

```mermaid
flowchart LR
    M["MSA [batch, N_seq, N_res, c_m]"] --> LayerNormM["Layer Norm"]
    
    LayerNormM --> LinearLeft["Linear Left"]
    LayerNormM --> LinearRight["Linear Right"]
    
    LinearLeft --> Reshape1["Reshape [batch, N_seq, N_res, c]"]
    LinearRight --> Reshape2["Reshape [batch, N_seq, N_res, c]"]
    
    Reshape1 --> OuterProduct["Outer Product [batch, N_seq, N_res, N_res, c*c]"]
    Reshape2 --> OuterProduct
    
    OuterProduct --> Mean["Mean across N_seq"]
    Mean --> LinearOut["Linear to c_z"]
    LinearOut --> Output["Pair update [batch, N_res, N_res, c_z]"]
```

Sources:
- [openfold/model/outer_product_mean.py]()

## Single Representation Output

In addition to updating the MSA and pair representations, the EvoformerStack produces a single representation that's used by the Structure Module:

```mermaid
flowchart TB
    M["Final MSA [batch, N_seq, N_res, c_m]"] --> First["First sequence [batch, N_res, c_m]"]
    First --> LayerNormM["Layer Norm"]
    LayerNormM --> LinearM["Linear"]
    
    Z["Final Pair [batch, N_res, N_res, c_z]"] --> Mean["Row-wise Mean [batch, N_res, c_z]"]
    Mean --> LayerNormZ["Layer Norm"]
    LayerNormZ --> LinearZ["Linear"]
    
    LinearM --> Add["Add"]
    LinearZ --> Add
    
    Add --> LayerNormOut["Layer Norm"]
    LayerNormOut --> Output["Single Representation [batch, N_res, c_s]"]
```

Sources:
- [openfold/model/evoformer.py:248-264]()

## Memory Optimization and Performance

The Evoformer Stack is the most computationally intensive part of AlphaFold 2. OpenFold implements several optimizations to improve performance and reduce memory usage:

### Chunking

Operations can be chunked to reduce peak memory usage:

```python
# Chunking allows processing large tensors in smaller pieces
if chunk_size is not None:
    z = self._chunk(z, biases, chunk_size)
else:
    z = self.mha(q_x=z, kv_x=z, biases=biases)
```

Sources:
- [openfold/model/triangular_attention.py:60-147]()

### Activation Checkpointing

The `blocks_per_ckpt` parameter controls how many blocks are included in each activation checkpoint, trading memory for computation:

```python
# Checkpoint blocks to save memory during backpropagation
z, = checkpoint_blocks(
    blocks=blocks,
    args=(z,),
    blocks_per_ckpt=self.blocks_per_ckpt if self.training else None,
)
```

Sources:
- [openfold/model/evoformer.py:590-607]()

### Memory-Efficient Attention

OpenFold provides multiple options for efficient attention computation:

1. Memory-efficient kernel (`use_memory_efficient_kernel`)
2. DeepSpeed Evoformer attention (`use_deepspeed_evo_attention`)
3. Low-memory attention (`use_lma`)
4. FlashAttention (`use_flash`)

```mermaid
flowchart TD
    Attention["Attention"] --> Config{"Choose attention\nimplementation"}
    Config -->|use_flash| FlashAttn["FlashAttention"]
    Config -->|use_lma| LMA["Low-Memory Attention"]
    Config -->|use_deepspeed_evo_attention| DS["DeepSpeed Evoformer Attention"]
    Config -->|use_memory_efficient_kernel| Eff["Memory-Efficient Kernel"]
    Config -->|default| Standard["Standard Attention"]
```

Sources:
- [openfold/model/primitives.py:477-545]()
- [openfold/config.py:465-486]()

## Integration with the Model

The Evoformer Stack is a central component of the AlphaFold model. Here's how it's integrated with the rest of the model:

```mermaid
flowchart TB
    subgraph "Input Embedders"
        InputEmbedder["Input Embedder"]
        RecyclingEmbedder["Recycling Embedder"]
        TemplateEmbedder["Template Embedder"]
        ExtraMSAEmbedder["Extra MSA Embedder"]
    end
    
    subgraph "MSA Processing"
        ExtraMSAStack["Extra MSA Stack"]
    end
    
    subgraph "Core Processing"
        EvoformerStack["Evoformer Stack"]
    end
    
    subgraph "Structure Prediction"
        StructureModule["Structure Module"]
        AuxHeads["Auxiliary Heads"]
    end
    
    InputEmbedder --> EvoformerStack
    RecyclingEmbedder --> EvoformerStack
    TemplateEmbedder --> EvoformerStack
    ExtraMSAEmbedder --> ExtraMSAStack
    ExtraMSAStack --> EvoformerStack
    
    EvoformerStack --> StructureModule
    EvoformerStack --> AuxHeads
```

Sources:
- [openfold/model/model.py:65-461]()

### Model Execution Flow

1. Input representations are generated by the InputEmbedder
2. Previous iteration outputs are incorporated via the RecyclingEmbedder
3. Template information is incorporated via the TemplateEmbedder
4. Extra MSA information is processed by the ExtraMSAStack
5. The Evoformer Stack processes all this information
6. The Structure Module converts the outputs into 3D coordinates
7. Auxiliary heads predict additional properties

Sources:
- [openfold/model/model.py:209-476]()

## Special Modes and Options

### Sequence Embedding Mode

For single-sequence predictions without MSAs, OpenFold provides a sequence embedding mode that disables column attention:

```python
# Specifically, seqemb mode does not use column attention
self.no_column_attention = no_column_attention
```

Sources:
- [openfold/model/evoformer.py:413-421]()
- [openfold/config.py:924-954]()

### Multimer Mode

For predicting multi-chain protein complexes, specialized multimer configurations are used:

```python
# Multimer-specific configuration
c.model.evoformer_stack.fuse_projection_weights = True if re.fullmatch("^model_[1-5]_multimer(_v2)?$", name) else False
```

Sources:
- [openfold/config.py:193-227]()
- [openfold/model/model.py:136-153]()

## Conclusion

The Evoformer Stack is the core neural network component of AlphaFold 2, implemented in OpenFold. It processes MSA and pair representations through a sophisticated series of attention mechanisms and transformations. This architecture effectively captures evolutionary and structural information, enabling accurate protein structure prediction. The OpenFold implementation provides various optimizations for performance and memory efficiency, making it applicable to a wide range of protein structure prediction tasks.

---