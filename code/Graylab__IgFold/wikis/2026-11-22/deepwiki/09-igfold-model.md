# IgFold Model

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [igfold/model/IgFold.py](igfold/model/IgFold.py)
- [igfold/model/components/IPABlock.py](igfold/model/components/IPABlock.py)
- [igfold/model/components/IPATransformer.py](igfold/model/components/IPATransformer.py)
- [igfold/model/interface.py](igfold/model/interface.py)
- [igfold/utils/transforms.py](igfold/utils/transforms.py)

</details>



The IgFold model is the core deep learning architecture for antibody structure prediction. This document covers the neural network components, forward pass flow, and architectural design of the main prediction model. For information about the processing pipeline that feeds into this model, see [Processing Pipeline](#5.2). For details about training and optimization, see [Training and Loss Functions](#7.2).

## Architecture Overview

The IgFold model follows a multi-stage architecture that combines sequence embeddings, template information, and geometric constraints to predict 3D antibody structures. The model is implemented as a PyTorch Lightning module in the `IgFold` class.

```mermaid
graph TD
    subgraph "Input Processing"
        INPUT[IgFoldInput] --> CLEAN[clean_input]
        CLEAN --> BERT_FEATS["BERT Features"]
        CLEAN --> BERT_ATTN["BERT Attentions"]
        CLEAN --> TEMP_COORDS["Template Coordinates"]
    end
    
    subgraph "Feature Transformation"
        BERT_FEATS --> STR_NODE[str_node_transform]
        BERT_ATTN --> STR_EDGE[str_edge_transform] 
        STR_NODE --> NODES["Node Features"]
        STR_EDGE --> EDGES["Edge Features"]
    end
    
    subgraph "Graph Processing"
        NODES --> MAIN_BLOCK[main_block]
        EDGES --> MAIN_BLOCK
        MAIN_BLOCK --> GT_EMBS["Graph Transformer Embeddings"]
    end
    
    subgraph "Template Processing"
        TEMP_COORDS --> KABSCH[get_coords_tran_rot]
        KABSCH --> TEMP_TRANS["Template Translations"]
        KABSCH --> TEMP_ROT["Template Rotations"]
        GT_EMBS --> TEMPLATE_IPA[template_ipa]
        TEMP_TRANS --> TEMPLATE_IPA
        TEMP_ROT --> TEMPLATE_IPA
        TEMPLATE_IPA --> STRUCT_EMBS["Structure Embeddings"]
    end
    
    subgraph "Structure Prediction"
        STRUCT_EMBS --> STRUCTURE_IPA[structure_ipa]
        GT_EMBS --> STRUCTURE_IPA
        STRUCTURE_IPA --> COORDS["3D Coordinates"]
        STRUCTURE_IPA --> TRANSLATIONS["Translations"]
        STRUCTURE_IPA --> QUATERNIONS["Quaternions"]
    end
    
    subgraph "Confidence Prediction"
        BERT_FEATS --> DEV_NODE[dev_node_transform]
        BERT_ATTN --> DEV_EDGE[dev_edge_transform]
        DEV_NODE --> DEV_IPA[dev_ipa]
        DEV_EDGE --> DEV_IPA
        TRANSLATIONS --> DEV_IPA
        QUATERNIONS --> DEV_IPA
        DEV_IPA --> DEV_LINEAR[dev_linear]
        DEV_LINEAR --> PRMSD["Predicted RMSD"]
    end
    
    subgraph "Output"
        COORDS --> OUTPUT[IgFoldOutput]
        PRMSD --> OUTPUT
        TRANSLATIONS --> OUTPUT
        QUATERNIONS --> OUTPUT
    end
```

Sources: [igfold/model/IgFold.py:19-488]()

## Input and Output Interfaces

The model uses structured dataclasses to define its input and output specifications.

### IgFoldInput

| Field | Type | Description |
|-------|------|-------------|
| `embeddings` | `List[List[torch.FloatTensor]]` | BERT embeddings for each chain |
| `attentions` | `List[List[torch.FloatTensor]]` | BERT attention matrices |
| `template_coords` | `Optional[torch.FloatTensor]` | Template structure coordinates |
| `template_mask` | `Optional[torch.BoolTensor]` | Mask for valid template positions |
| `batch_mask` | `Optional[torch.BoolTensor]` | Mask for valid sequence positions |
| `align_mask` | `Optional[torch.BoolTensor]` | Mask for alignment during training |
| `coords_label` | `Optional[torch.FloatTensor]` | Ground truth coordinates for training |
| `return_embeddings` | `Optional[bool]` | Whether to return intermediate embeddings |

### IgFoldOutput

| Field | Type | Description |
|-------|------|-------------|
| `coords` | `torch.FloatTensor` | Predicted 3D coordinates |
| `prmsd` | `torch.FloatTensor` | Predicted RMSD confidence scores |
| `translations` | `torch.FloatTensor` | Rigid body translations |
| `rotations` | `torch.FloatTensor` | Rigid body rotations |
| `coords_loss` | `Optional[torch.FloatTensor]` | Coordinate prediction loss |
| `bondlen_loss` | `Optional[torch.FloatTensor]` | Bond length constraint loss |
| `prmsd_loss` | `Optional[torch.FloatTensor]` | Confidence prediction loss |
| `loss` | `Optional[torch.FloatTensor]` | Total training loss |

Sources: [igfold/model/interface.py:1-40]()

## Core Components

### Graph Transformer Block

The `main_block` is a `TriangleGraphTransformer` that processes sequence-level features extracted from BERT embeddings and attentions.

```mermaid
graph LR
    subgraph "Graph Transformer Processing"
        BERT_FEATS["BERT Features<br/>(B, L, 512)"] --> STR_NODE_TRANS[str_node_transform]
        BERT_ATTN["BERT Attentions<br/>(B, L, L, 64)"] --> STR_EDGE_TRANS[str_edge_transform]
        
        STR_NODE_TRANS --> NODE_DIM["Node Features<br/>(B, L, node_dim)"]
        STR_EDGE_TRANS --> EDGE_DIM["Edge Features<br/>(B, L, L, node_dim)"]
        
        NODE_DIM --> TRIANGLE_GT[TriangleGraphTransformer]
        EDGE_DIM --> TRIANGLE_GT
        
        TRIANGLE_GT --> GT_NODES["Updated Nodes"]
        TRIANGLE_GT --> GT_EDGES["Updated Edges"]
    end
```

The transformations use linear layers followed by ReLU activation and LayerNorm:

```mermaid
graph LR
    INPUT["Input Features"] --> LINEAR[Linear Layer]
    LINEAR --> RELU[ReLU Activation]
    RELU --> LAYERNORM[LayerNorm]
    LAYERNORM --> OUTPUT["Transformed Features"]
```

Sources: [igfold/model/IgFold.py:50-75](), [igfold/model/IgFold.py:239-245]()

### Invariant Point Attention (IPA) Components

The model employs three different IPA modules for different purposes:

1. **Template IPA** (`template_ipa`): Processes template structural information
2. **Structure IPA** (`structure_ipa`): Predicts 3D coordinates with rigid body transformations  
3. **Deviation IPA** (`dev_ipa`): Estimates confidence scores

```mermaid
graph TD
    subgraph "IPA Architecture Components"
        NODES["Node Features"] --> IPA_ENCODER[IPAEncoder]
        TRANSLATIONS["Translations"] --> IPA_ENCODER
        ROTATIONS["Rotations"] --> IPA_ENCODER
        PAIRWISE["Pairwise Repr"] --> IPA_ENCODER
        
        IPA_ENCODER --> UPDATED_NODES["Updated Node Features"]
        
        NODES2["Node Features"] --> IPA_TRANSFORMER[IPATransformer]
        PAIRWISE2["Pairwise Repr"] --> IPA_TRANSFORMER
        
        IPA_TRANSFORMER --> COORDS["3D Coordinates"]
        IPA_TRANSFORMER --> NEW_TRANS["New Translations"]
        IPA_TRANSFORMER --> QUATERNIONS["Quaternions"]
    end
```

Sources: [igfold/model/IgFold.py:76-88](), [igfold/model/IgFold.py:103-108](), [igfold/model/components/IPATransformer.py:16-174]()

## Forward Pass Flow

The model's forward pass follows a structured pipeline:

### 1. Input Processing and Cleaning

The `clean_input` method processes raw inputs, handling missing values and ensuring proper tensor shapes and masks.

```mermaid
graph TD
    INPUT[IgFoldInput] --> EXTRACT["Extract Components"]
    EXTRACT --> CHECK_NONE["Check for None Values"]
    CHECK_NONE --> CREATE_DEFAULTS["Create Default Tensors"]
    CREATE_DEFAULTS --> APPLY_MASKS["Apply Batch/Align Masks"]  
    APPLY_MASKS --> CENTER_COORDS["Center Template Coords"]
    CENTER_COORDS --> CLEANED[Cleaned Input]
```

Sources: [igfold/model/IgFold.py:144-194]()

### 2. Feature Processing

BERT embeddings and attentions are concatenated and transformed into the model's internal feature space.

| Configuration Parameter | Default Value | Description |
|------------------------|---------------|-------------|
| `bert_feat_dim` | 512 | BERT feature dimension |
| `bert_attn_dim` | 64 | BERT attention dimension |
| `node_dim` | configurable | Internal node feature dimension |

Sources: [igfold/model/IgFold.py:32-36](), [igfold/model/IgFold.py:223-245]()

### 3. Template Coordinate Processing

Template coordinates are processed using Kabsch alignment to extract rigid body transformations:

```mermaid
graph LR
    TEMP_COORDS["Template Coords<br/>(B, L*4, 3)"] --> RESHAPE["Reshape to<br/>(B, L, 4, 3)"]
    RESHAPE --> IDEAL_COORDS["Get Ideal Coords"]
    IDEAL_COORDS --> KABSCH[Kabsch Alignment]
    KABSCH --> TRANSLATIONS["Translations<br/>(B, L, 3)"]
    KABSCH --> ROTATIONS["Rotations<br/>(B, L, 3, 3)"]
```

Sources: [igfold/model/IgFold.py:114-142](), [igfold/model/IgFold.py:233-237]()

### 4. Structure Prediction

The `structure_ipa` (`IPATransformer`) predicts final coordinates by iteratively refining translations and quaternions:

```mermaid
graph TD
    STRUCT_NODES["Structure Node Features"] --> IPA_LAYERS["IPA Layers"]
    PAIRWISE["Pairwise Features"] --> IPA_LAYERS
    
    IPA_LAYERS --> LAYER_BLOCK[IPABlock]
    LAYER_BLOCK --> LINEAR_UPDATE[Linear Update]
    LINEAR_UPDATE --> QUAT_UPDATE["Quaternion Update"]
    LINEAR_UPDATE --> TRANS_UPDATE["Translation Update"] 
    
    QUAT_UPDATE --> MULTIPLY[Quaternion Multiply]
    TRANS_UPDATE --> ADD[Translation Add]
    
    MULTIPLY --> NEXT_LAYER["Next Layer or Output"]
    ADD --> NEXT_LAYER
    
    NEXT_LAYER --> FINAL_COORDS["Final 3D Coordinates"]
```

Sources: [igfold/model/IgFold.py:256-263](), [igfold/model/components/IPATransformer.py:83-174]()

### 5. Confidence Prediction

A separate deviation pathway predicts per-residue confidence using the `dev_ipa`:

```mermaid
graph LR
    BERT_FEATS --> DEV_NODE[dev_node_transform]
    BERT_ATTN --> DEV_EDGE[dev_edge_transform]
    PRED_TRANS["Predicted Translations<br/>(detached)"] --> DEV_IPA[dev_ipa]
    PRED_ROT["Predicted Rotations<br/>(detached)"] --> DEV_IPA
    DEV_NODE --> DEV_IPA
    DEV_EDGE --> DEV_IPA
    DEV_IPA --> DEV_LINEAR[dev_linear]
    DEV_LINEAR --> RELU[ReLU]
    RELU --> PRMSD["Predicted RMSD"]
```

Sources: [igfold/model/IgFold.py:265-275]()

## Loss Functions

During training, multiple loss components are computed:

| Loss Component | Function | Purpose |
|---------------|----------|---------|
| `coords_loss` | `kabsch_mse` | Coordinate prediction accuracy |
| `bondlen_loss` | `bond_length_l1` | Bond length constraints |
| `prmsd_loss` | `bb_prmsd_l1` | Confidence prediction accuracy |

Sources: [igfold/model/IgFold.py:287-346]()

## Advanced Features

### Coordinate Scoring

The `score_coords` method allows re-evaluation of confidence scores for given coordinates without full forward pass:

Sources: [igfold/model/IgFold.py:372-403]()

### Gradient Refinement

The `gradient_refine` method performs iterative optimization of predicted structures using violation constraints:

```mermaid
graph TD
    INPUT_COORDS["Input Coordinates"] --> ENABLE_GRAD["Enable Gradients"]
    ENABLE_GRAD --> OPTIMIZER["Adam Optimizer<br/>(lr=2e-2)"]
    OPTIMIZER --> ITER_START["Iteration Loop<br/>(80 steps)"]
    
    ITER_START --> TRANSFORM[transform_ideal_coords]
    TRANSFORM --> CALC_VIOL[violation_loss]
    TRANSFORM --> CALC_RMSD[kabsch_mse]
    
    CALC_VIOL --> TOTAL_LOSS["Total Loss"]
    CALC_RMSD --> TOTAL_LOSS
    TOTAL_LOSS --> BACKWARD[loss.backward]
    BACKWARD --> STEP[optimizer.step]
    STEP --> ITER_END{"More Steps?"}
    
    ITER_END -->|Yes| ITER_START
    ITER_END -->|No| FINAL_COORDS["Refined Coordinates"]
```

Sources: [igfold/model/IgFold.py:427-488]()

## Model Configuration

Key hyperparameters control the model architecture:

| Parameter | Description | Typical Range |
|-----------|-------------|---------------|
| `depth` | Main transformer depth | 4-8 |
| `gt_depth` | Graph transformer depth | 2-4 |
| `gt_heads` | Graph transformer heads | 8-16 |
| `temp_ipa_depth` | Template IPA depth | 2-4 |
| `str_ipa_depth` | Structure IPA depth | 4-8 |
| `dev_ipa_depth` | Deviation IPA depth | 2-4 |

Sources: [igfold/model/IgFold.py:37-48]()

---