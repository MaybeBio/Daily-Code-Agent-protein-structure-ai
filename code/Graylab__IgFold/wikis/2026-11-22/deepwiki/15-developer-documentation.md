# Developer Documentation

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [igfold/model/__init__.py](igfold/model/__init__.py)
- [igfold/model/components/GraphTransformer.py](igfold/model/components/GraphTransformer.py)
- [igfold/model/components/TriangleGraphTransformer.py](igfold/model/components/TriangleGraphTransformer.py)
- [igfold/training/utils.py](igfold/training/utils.py)

</details>



This document provides technical documentation for developers working on IgFold's internal architecture, model components, training systems, and extensibility. It covers the core neural network implementations, training utilities, loss functions, and package organization from a developer perspective.

For user-facing API documentation, see [User Guide](#4). For high-level architecture concepts, see [Core Architecture](#5). For specific neural network component details, see [Model Components](#7.1). For training system specifics, see [Training and Loss Functions](#7.2).

## Development Architecture Overview

IgFold's development architecture centers around modular neural network components, training utilities, and a structured package hierarchy that enables extensibility and experimentation.

```mermaid
graph TB
    subgraph "Core Model Development"
        IGFOLD_MODEL["IgFoldModel"]
        GRAPH_TRANS["GraphTransformer"]
        TRI_GRAPH_TRANS["TriangleGraphTransformer"] 
        IPA_TRANS["IPATransformer"]
        ATTENTION["Attention"]
    end
    
    subgraph "Training Infrastructure"
        TRAIN_UTILS["training/utils.py"]
        KABSCH["kabsch()"]
        LOSS_FUNCS["Loss Functions"]
        METRICS["Structural Metrics"]
    end
    
    subgraph "Component Architecture"
        PRENORM["PreNorm"]
        GATED_RES["GatedResidual"]
        RESIDUAL["Residual"]
        FEEDFORWARD["FeedForward"]
    end
    
    subgraph "Geometric Processing"
        KABSCH_MSE["kabsch_mse()"]
        BOND_LOSS["bond_length_l1()"]
        ANGLE_LOSS["bond_angle_loss()"]
        VDW_LOSS["vdw_clash_loss()"]
    end
    
    IGFOLD_MODEL --> GRAPH_TRANS
    IGFOLD_MODEL --> TRI_GRAPH_TRANS
    IGFOLD_MODEL --> IPA_TRANS
    
    GRAPH_TRANS --> ATTENTION
    GRAPH_TRANS --> PRENORM
    GRAPH_TRANS --> GATED_RES
    
    TRI_GRAPH_TRANS --> GRAPH_TRANS
    
    TRAIN_UTILS --> KABSCH
    TRAIN_UTILS --> LOSS_FUNCS
    TRAIN_UTILS --> METRICS
    
    LOSS_FUNCS --> KABSCH_MSE
    LOSS_FUNCS --> BOND_LOSS
    LOSS_FUNCS --> ANGLE_LOSS
    LOSS_FUNCS --> VDW_LOSS
    
    style IGFOLD_MODEL fill:#f9f9f9
    style TRAIN_UTILS fill:#f9f9f9
    style GRAPH_TRANS fill:#f9f9f9
```

**Sources:** [igfold/training/utils.py:1-287](), [igfold/model/components/GraphTransformer.py:1-255](), [igfold/model/components/TriangleGraphTransformer.py:1-63]()

## Core Neural Network Components

The model architecture implements a hierarchical transformer design with geometric constraints and structural loss functions. Key components follow a modular pattern enabling easy modification and extension.

```mermaid
graph TB
    subgraph "Transformer Components"
        GT[GraphTransformer]
        TGT[TriangleGraphTransformer] 
        ATT[Attention]
        PN[PreNorm]
        GR[GatedResidual]
        FF[FeedForward]
    end
    
    subgraph "Geometric Operations"
        KABSCH_FUNC[kabsch]
        DO_KABSCH[do_kabsch]
        KABSCH_MSE_FUNC[kabsch_mse]
    end
    
    subgraph "Structural Constraints"
        BOND_LEN[bond_len_loss]
        BOND_ANG[bond_angle_loss]
        VDW_CLASH[vdw_clash_loss]
        CIS_PEP[cis_peptide_loss]
        VIOLATION[violation_loss]
    end
    
    GT --> ATT
    GT --> PN
    GT --> GR
    GT --> FF
    
    TGT --> GT
    TGT --> TMM[TriangleMultiplicativeModule]
    
    KABSCH_FUNC --> DO_KABSCH
    DO_KABSCH --> KABSCH_MSE_FUNC
    
    VIOLATION --> BOND_LEN
    VIOLATION --> BOND_ANG  
    VIOLATION --> VDW_CLASH
    VIOLATION --> CIS_PEP
    
    style GT fill:#f9f9f9
    style KABSCH_FUNC fill:#f9f9f9
    style VIOLATION fill:#f9f9f9
```

**Sources:** [igfold/model/components/GraphTransformer.py:187-255](), [igfold/model/components/TriangleGraphTransformer.py:8-63](), [igfold/training/utils.py:277-286]()

### Key Component Classes

| Component | File Location | Purpose |
|-----------|---------------|---------|
| `GraphTransformer` | [igfold/model/components/GraphTransformer.py:187-255]() | Multi-head attention over graph nodes with edge features |
| `TriangleGraphTransformer` | [igfold/model/components/TriangleGraphTransformer.py:8-63]() | Combines graph attention with triangle multiplicative updates |
| `Attention` | [igfold/model/components/GraphTransformer.py:70-177]() | Multi-head attention with edge incorporation |
| `GatedResidual` | [igfold/model/components/GraphTransformer.py:50-65]() | Learned gating for residual connections |
| `PreNorm` | [igfold/model/components/GraphTransformer.py:14-36]() | Layer normalization before operations |

## Training and Loss Function Systems

The training system implements geometric loss functions that enforce protein structural constraints while enabling gradient-based optimization of 3D coordinates.

### Geometric Loss Functions

The training utilities provide several specialized loss functions for structural validation:

| Function | Purpose | Key Parameters |
|----------|---------|----------------|
| `kabsch_mse()` | Optimal alignment RMSE | `align_mask`, `clamp`, `sqrt` |
| `bond_len_loss()` | Bond length constraints | `seq_lens`, `mask` |
| `bond_angle_loss()` | Bond angle constraints | `seq_lens`, `mask` |
| `vdw_clash_loss()` | Van der Waals clash detection | `tol=1.5` |
| `violation_loss()` | Combined structural violations | `seq_lens`, `mask` |

The `violation_loss()` function [igfold/training/utils.py:277-286]() combines all structural constraints:

```python
def violation_loss(pred, seq_lens, mask, eps=EPS):
    bl_loss = bond_len_loss(pred, seq_lens, mask, eps=eps)
    ba_loss = bond_angle_loss(pred, seq_lens, mask, eps=eps)
    vdw_loss = vdw_clash_loss(pred, mask)
    cis_loss = cis_peptide_loss(pred, seq_lens, mask, eps=eps)
    loss = bl_loss + ba_loss + vdw_loss + cis_loss
    return loss
```

**Sources:** [igfold/training/utils.py:194-286]()

### Kabsch Alignment System

The Kabsch algorithm implementation [igfold/training/utils.py:11-76]() provides optimal superposition for structure comparison:

```mermaid
graph LR
    MOBILE["mobile coords"] --> KABSCH["kabsch()"]
    STATIONARY["stationary coords"] --> KABSCH
    KABSCH --> TRANSFORM["transformation"]
    KABSCH --> ALIGNED["aligned coords"]
    
    ALIGNED --> DO_KABSCH["do_kabsch()"]
    ALIGN_MASK["align_mask"] --> DO_KABSCH
    
    DO_KABSCH --> KABSCH_MSE["kabsch_mse()"]
    MASK["mask"] --> KABSCH_MSE
    KABSCH_MSE --> LOSS["RMSE loss"]
```

**Sources:** [igfold/training/utils.py:11-136]()

## Development Workflow

### Model Component Development

1. **Transformer Components**: Extend `GraphTransformer` [igfold/model/components/GraphTransformer.py:187-255]() for new attention mechanisms
2. **Loss Functions**: Add new structural constraints to [igfold/training/utils.py]()
3. **Geometric Operations**: Modify Kabsch alignment in [igfold/training/utils.py:11-98]()

### Testing and Validation

Key functions for structural validation:
- `kabsch_mse()` for alignment quality [igfold/training/utils.py:100-136]()
- `violation_loss()` for structural constraints [igfold/training/utils.py:277-286]()
- `bb_prmsd_l1()` for predicted RMSD validation [igfold/training/utils.py:159-192]()

## Code Organization for Developers

### Package Structure

```mermaid
graph TB
    subgraph "Model Components"
        MODEL_INIT["model/__init__.py"]
        GRAPH_TRANS_FILE["model/components/GraphTransformer.py"]
        TRI_GRAPH_FILE["model/components/TriangleGraphTransformer.py"]
    end
    
    subgraph "Training Systems"
        TRAIN_UTILS_FILE["training/utils.py"]
        LOSS_FUNCTIONS["Loss Functions"]
        GEOMETRY["Geometric Operations"]
    end
    
    subgraph "Core Classes"
        GRAPH_TRANSFORMER["GraphTransformer"]
        ATTENTION_CLASS["Attention"]
        GATED_RESIDUAL["GatedResidual"]
        PRENORM_CLASS["PreNorm"]
    end
    
    GRAPH_TRANS_FILE --> GRAPH_TRANSFORMER
    GRAPH_TRANS_FILE --> ATTENTION_CLASS
    GRAPH_TRANS_FILE --> GATED_RESIDUAL
    GRAPH_TRANS_FILE --> PRENORM_CLASS
    
    TRI_GRAPH_FILE --> TRIANGLE_GT["TriangleGraphTransformer"]
    
    TRAIN_UTILS_FILE --> LOSS_FUNCTIONS
    TRAIN_UTILS_FILE --> GEOMETRY
    
    style MODEL_INIT fill:#f9f9f9
    style TRAIN_UTILS_FILE fill:#f9f9f9
```

**Sources:** [igfold/model/__init__.py:1](), [igfold/model/components/GraphTransformer.py:1-255](), [igfold/training/utils.py:1-287]()

### Extension Points

For developers extending IgFold:

1. **New Attention Mechanisms**: Inherit from `Attention` class [igfold/model/components/GraphTransformer.py:70-177]()
2. **Custom Loss Functions**: Add to training utilities [igfold/training/utils.py]()
3. **Geometric Constraints**: Extend violation functions [igfold/training/utils.py:194-286]()
4. **Transformer Variants**: Modify `GraphTransformer` parameters [igfold/model/components/GraphTransformer.py:187-255]()

For detailed component specifications, see [Model Components](#7.1). For training system details, see [Training and Loss Functions](#7.2). For package organization, see [Package Structure and Utilities](#7.3).

**Sources:** [igfold/model/components/GraphTransformer.py:1-255](), [igfold/model/components/TriangleGraphTransformer.py:1-63](), [igfold/training/utils.py:1-287]()

---