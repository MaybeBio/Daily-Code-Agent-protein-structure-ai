# Model Architecture

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [omtra/models/omtra.py](omtra/models/omtra.py)
- [omtra/models/self_conditioning.py](omtra/models/self_conditioning.py)
- [omtra/models/vector_field.py](omtra/models/vector_field.py)

</details>



This document provides a technical overview of OMTRA's neural network architecture and its core components. It explains how the model is structured, how data flows through different layers during training and inference, and the key architectural decisions that enable multi-modal molecular generation.

For specific implementation details of individual components, see:
- [OMTRA Generative Model](#4.1) - The main model class and training/sampling logic
- [VectorField Architecture](#4.2) - The GNN that predicts trajectory destinations
- [Self-Conditioning Mechanism](#4.3) - Iterative refinement through self-conditioning
- [Ligand Encoder (VQ-VAE)](#4.4) - Discrete ligand representation learning

For understanding the theoretical foundations, see [Flow Matching for Molecules](#3.2).

---

## Overview

OMTRA uses a **flow matching** framework to generate molecular structures by predicting trajectories from a prior distribution (time `t=0`) to a data distribution (time `t=1`). The core architecture consists of three main components:

| Component | Class | Primary Role | File |
|-----------|-------|--------------|------|
| **Generative Model** | `OMTRA` | Orchestrates training and sampling, manages conditional paths | [omtra/models/omtra.py]() |
| **VectorField** | `VectorField` | Predicts trajectory destinations using heterogeneous GNNs | [omtra/models/vector_field.py]() |
| **Self-Conditioning** | `SelfConditioningResidualLayer` | Optional refinement using previous predictions | [omtra/models/self_conditioning.py]() |

The model operates on **heterogeneous graphs** (via DGL) representing molecular systems with multiple node types (ligand atoms, protein atoms, pharmacophores, non-protein non-drug entities) and edge types (covalent bonds, spatial proximity).

**Sources:** [omtra/models/omtra.py:55-172](), [omtra/models/vector_field.py:40-103]()

---

## High-Level Architecture

```mermaid
graph TB
    subgraph "OMTRA Model (omtra/models/omtra.py)"
        OMTRA["OMTRA<br/>(pl.LightningModule)"]
        
        subgraph "Training Components"
            TaskCoupling["TaskDatasetCoupling<br/>Multi-task configuration"]
            ConditionalPath["Conditional Path Sampling<br/>sample_conditional_path()"]
            LossFns["Loss Functions<br/>configure_loss_fns()"]
        end
        
        subgraph "Sampling Components"
            PriorSampling["Prior Sampling<br/>sample_priors()"]
            Integration["Integration Loop<br/>VectorField.integrate()"]
        end
    end
    
    subgraph "VectorField (omtra/models/vector_field.py)"
        VF["VectorField Module"]
        
        subgraph "Embedding Layers"
            TokenEmbed["Token Embeddings<br/>token_embeddings"]
            ScalarEmbed["Scalar Embeddings<br/>scalar_embedding"]
            EdgeEmbed["Edge Embeddings<br/>edge_embedding"]
            TaskEmbed["Task Embedding<br/>task_embedding"]
        end
        
        subgraph "GNN Layers"
            ConvLayers["HeteroGVPConv Layers<br/>conv_layers<br/>(n_recycles × convs_per_update × n_molecule_updates)"]
            PosUpdate["NodePositionUpdate<br/>node_position_updaters"]
            EdgeUpdate["EdgeUpdate<br/>edge_updaters"]
        end
        
        subgraph "Output Heads"
            NodeHeads["Node Output Heads<br/>node_output_heads"]
            EdgeHeads["Edge Output Heads<br/>edge_output_heads"]
        end
    end
    
    subgraph "Optional: Self-Conditioning"
        SC["SelfConditioningResidualLayer<br/>self_conditioning_residual_layer"]
    end
    
    OMTRA --> TaskCoupling
    OMTRA --> ConditionalPath
    OMTRA --> LossFns
    OMTRA --> PriorSampling
    OMTRA --> Integration
    OMTRA --> VF
    
    VF --> TokenEmbed
    VF --> ScalarEmbed
    VF --> EdgeEmbed
    VF --> TaskEmbed
    
    TokenEmbed --> ConvLayers
    ScalarEmbed --> ConvLayers
    EdgeEmbed --> ConvLayers
    TaskEmbed --> ConvLayers
    
    ConvLayers --> PosUpdate
    ConvLayers --> EdgeUpdate
    ConvLayers --> NodeHeads
    ConvLayers --> EdgeHeads
    
    VF -.->|"if self_conditioning=True"| SC
    SC -.-> ConvLayers
```

**Sources:** [omtra/models/omtra.py:55-186](), [omtra/models/vector_field.py:40-358](), [omtra/models/self_conditioning.py:18-85]()

---

## Data Flow: Training vs Inference

### Training Forward Pass

```mermaid
graph LR
    subgraph "Input (forward)"
        G1["DGL HeteroGraph g<br/>with x_0 (prior) and<br/>x_1_true (data)"]
        T1["Task name"]
    end
    
    subgraph "OMTRA.forward()"
        SampleT["Sample time t<br/>train_t_sampler()"]
        SampleCP["Sample Conditional Path<br/>sample_conditional_path()<br/>→ x_t = α_t·x_0 + β_t·x_1"]
        VFForward["VectorField.forward()<br/>→ dst_dict (predicted x_1)"]
        ComputeLoss["Compute Losses<br/>Flow matching + Auxiliary"]
    end
    
    G1 --> SampleCP
    T1 --> SampleCP
    SampleT --> SampleCP
    SampleCP --> VFForward
    VFForward --> ComputeLoss
    
    ComputeLoss --> Output["Return: Dict of losses"]
```

During training, the model:

1. **Samples a time** `t ~ U(0,1)` or `t ~ Beta(α, 1)` ([omtra/models/omtra.py:388]())
2. **Samples the conditional path** to create intermediate state `x_t` by interpolating between prior `x_0` and data `x_1_true` ([omtra/models/omtra.py:400-402]())
3. **Predicts the destination** `x_1_pred` using `VectorField.forward()` ([omtra/models/omtra.py:415-421]())
4. **Computes losses** comparing predicted and true destinations for all modalities being generated ([omtra/models/omtra.py:455-514]())

**Sources:** [omtra/models/omtra.py:386-516]()

### Sampling/Inference

```mermaid
graph TB
    subgraph "Input (sample)"
        TaskName["task_name"]
        GList["g_list (optional)<br/>Conditional inputs"]
        NReps["n_replicates"]
    end
    
    subgraph "OMTRA.sample()"
        PrepGraphs["Prepare Graphs<br/>- Sample n_atoms<br/>- Build initial graphs<br/>- Add nodes/edges"]
        SamplePriors["Sample Priors<br/>sample_priors()<br/>→ x_0 for all modalities"]
        Integrate["VectorField.integrate()<br/>t: 0 → 1<br/>n_timesteps steps"]
        Unbatch["Unbatch and Convert<br/>→ List[SampledSystem]"]
    end
    
    subgraph "VectorField.integrate()"
        Loop["For each timestep"]
        Step["VectorField.step()<br/>- Predict x_1<br/>- Update x_t → x_s<br/>- Handle continuous & categorical"]
    end
    
    TaskName --> PrepGraphs
    GList --> PrepGraphs
    NReps --> PrepGraphs
    PrepGraphs --> SamplePriors
    SamplePriors --> Integrate
    Integrate --> Unbatch
    
    Integrate --> Loop
    Loop --> Step
    Step --> Loop
    
    Unbatch --> Output2["Return: List[SampledSystem]"]
```

During sampling, the model:

1. **Prepares initial graphs** by sampling number of atoms and building graph structure ([omtra/models/omtra.py:659-852]())
2. **Samples priors** for all modalities being generated ([omtra/models/omtra.py:859-867]())
3. **Integrates the flow** from `t=0` to `t=1` using `VectorField.integrate()` ([omtra/models/omtra.py:908-913]())
4. **Unbatches and converts** to `SampledSystem` objects ([omtra/models/omtra.py:924-939]())

**Sources:** [omtra/models/omtra.py:603-940](), [omtra/models/vector_field.py:778-932]()

---

## VectorField Architecture Details

The `VectorField` is a heterogeneous graph neural network that predicts the trajectory destination given the current state `x_t`.

### Network Structure

```mermaid
graph TB
    subgraph "Input Features"
        CatFeats["Categorical Features<br/>(atom types, charges, etc.)"]
        ContFeats["Continuous Features<br/>(positions, vectors)"]
        TimeEmb["Time Embedding<br/>get_time_embedding()"]
        TaskEmb["Task Embedding<br/>task_embedding()"]
    end
    
    subgraph "Initial Embeddings"
        TokenEmb["Token Embeddings<br/>nn.Embedding<br/>per modality"]
        ScalarEmb["Scalar Embedding MLP<br/>scalar_embedding<br/>per node type"]
    end
    
    subgraph "Message Passing (n_recycles iterations)"
        subgraph "Convolution Block (convs_per_update × n_molecule_updates)"
            Conv["HeteroGVPConv<br/>Updates (s, v) features"]
            
            UpdatePos["NodePositionUpdate<br/>x ← x + GVP(s, v)"]
            UpdateEdge["EdgeUpdate<br/>e ← e + MLP(s_src, s_dst, e, d)"]
        end
        
        Conv --> UpdatePos
        Conv --> UpdateEdge
        UpdatePos --> Conv
        UpdateEdge --> Conv
    end
    
    subgraph "Output Heads"
        NodeCat["Node Categorical<br/>MLP → logits"]
        NodeVec["Node Vectors<br/>GVP → (s_out, v_out)"]
        EdgeCat["Edge Categorical<br/>MLP → logits"]
    end
    
    CatFeats --> TokenEmb
    ContFeats --> ScalarEmb
    TimeEmb --> ScalarEmb
    TaskEmb --> ScalarEmb
    
    TokenEmb --> Conv
    ScalarEmb --> Conv
    
    Conv --> NodeCat
    Conv --> NodeVec
    Conv --> EdgeCat
    
    NodeCat --> DstDict["dst_dict<br/>(predicted x_1)"]
    NodeVec --> DstDict
    EdgeCat --> DstDict
```

**Key architectural parameters:**

| Parameter | Description | Default |
|-----------|-------------|---------|
| `n_hidden_scalars` | Scalar feature dimension | 64 |
| `n_vec_channels` | Vector feature dimension | 16 |
| `n_recycles` | Number of recycling iterations | 1 |
| `n_molecule_updates` | Position/edge updates per recycle | 1 |
| `convs_per_update` | Conv layers between updates | 2 |
| `n_message_gvps` | GVP layers in message function | 3 |
| `n_update_gvps` | GVP layers in update function | 3 |

**Sources:** [omtra/models/vector_field.py:40-103](), [omtra/models/vector_field.py:190-358]()

### Feature Processing Pipeline

The `VectorField.forward()` method processes features in the following sequence:

1. **Build edges** for the task ([omtra/models/vector_field.py:382]())
2. **Extract modality features** from graph nodes and edges ([omtra/models/vector_field.py:387-452]())
3. **Embed features**:
   - Categorical: token embeddings ([omtra/models/vector_field.py:423-426]())
   - Time: sinusoidal embedding ([omtra/models/vector_field.py:468-475]())
   - Task: learned embedding ([omtra/models/vector_field.py:455-463]())
4. **Optionally apply self-conditioning** ([omtra/models/vector_field.py:489-541]())
5. **Call `denoise_graph()`** to run GNN and generate predictions ([omtra/models/vector_field.py:543-555]())

**Sources:** [omtra/models/vector_field.py:360-564]()

### GNN Message Passing

The `denoise_graph()` method implements the core GNN computation:

```mermaid
graph TB
    PrecompDist["Precompute Distances<br/>x_diff, d = precompute_distances()"]
    
    subgraph "Recycle Loop (n_recycles iterations)"
        subgraph "Conv Loop (convs_per_update × n_molecule_updates)"
            HeteroConv["HeteroGVPConv<br/>(s, v) ← conv(g, s, x, v, e, x_diff, d)"]
            
            CheckUpdate{"Update?<br/>(every convs_per_update)"}
            
            UpdateX["Update Positions<br/>x ← NodePositionUpdate(s, x, v)"]
            UpdateE["Update Edges<br/>e ← EdgeUpdate(s, e, d)"]
            RecomputeDist["Recompute Distances<br/>x_diff, d ← precompute_distances()"]
        end
    end
    
    OutputHeads["Apply Output Heads<br/>logits ← node_output_heads(s)<br/>logits ← edge_output_heads(e)"]
    
    PrecompDist --> HeteroConv
    HeteroConv --> CheckUpdate
    CheckUpdate -->|"Yes"| UpdateX
    UpdateX --> UpdateE
    UpdateE --> RecomputeDist
    RecomputeDist --> HeteroConv
    CheckUpdate -->|"No"| HeteroConv
    
    HeteroConv --> OutputHeads
    OutputHeads --> Return["Return dst_dict"]
```

**Sources:** [omtra/models/vector_field.py:567-741]()

### Edge Handling

The model maintains different edge types with different behaviors:

| Edge Type | Modality | Features | Update Strategy |
|-----------|----------|----------|-----------------|
| `lig_to_lig` | Ligand bonds | Edge type (none/single/double/triple) | Updated via `EdgeUpdate` |
| `lig_to_prot` | Ligand-protein interactions | Distance-based (RBF) | Rebuilt each update |
| `prot_to_prot` | Protein structure | Distance-based (RBF) | Static or rebuilt |
| `*_covalent` | Covalent bonds | None | Static |

**Sources:** [omtra/models/vector_field.py:167-183](), [omtra/models/vector_field.py:640-664]()

---

## Self-Conditioning Mechanism

When `self_conditioning=True`, the model uses a two-pass prediction strategy:

```mermaid
graph LR
    subgraph "First Pass (with no_grad)"
        Input1["Input: x_t, t"]
        Forward1["VectorField.forward()<br/>→ dst_dict_prev"]
    end
    
    subgraph "Self-Conditioning Layer"
        Residual["SelfConditioningResidualLayer<br/>Compute residuals from dst_dict_prev"]
        Apply["Apply residuals to<br/>s_t, x_t, v_t, e_t"]
    end
    
    subgraph "Second Pass"
        Forward2["VectorField.forward()<br/>with updated features<br/>→ dst_dict_final"]
    end
    
    Input1 --> Forward1
    Forward1 --> Residual
    Residual --> Apply
    Apply --> Forward2
    Forward2 --> Output["Return dst_dict_final"]
```

The residual layer computes corrections based on:

- **Position changes**: RBF-encoded distances between predicted and current positions ([omtra/models/self_conditioning.py:108-122]())
- **Vector changes**: Pairwise distances between predicted and current vector features ([omtra/models/self_conditioning.py:123-138]())
- **Categorical changes**: Predicted probability distributions ([omtra/models/self_conditioning.py:139-146]())
- **Edge length changes**: Change in bond distances for `lig_to_lig` edges ([omtra/models/self_conditioning.py:163-188]())

During training, self-conditioning is applied with 50% probability. During inference, it's applied at every step except the initial step (t=0).

**Sources:** [omtra/models/vector_field.py:489-541](), [omtra/models/self_conditioning.py:87-199]()

---

## Modality-Specific Output Heads

The model generates predictions for different modalities using specialized output heads:

### Node Modalities

| Modality | Data Key | Output Head | Output Shape |
|----------|----------|-------------|--------------|
| Ligand atom type | `a` | MLP | `(n_nodes, n_atom_types)` |
| Ligand charge | `c` | MLP | `(n_nodes, n_charges)` |
| Ligand position | `x` | `NodePositionUpdate` (GVP) | `(n_nodes, 3)` |
| Pharmacophore type | `a` | MLP | `(n_nodes, n_pharm_types)` |
| Pharmacophore vectors | `v` | GVP | `(n_nodes, 4, 3)` |

**Sources:** [omtra/models/vector_field.py:302-332](), [omtra/models/vector_field.py:1181-1210]()

### Edge Modalities

| Modality | Data Key | Output Head | Output Shape |
|----------|----------|-------------|--------------|
| Ligand bond order | `e` | MLP | `(n_edges, 4)` |

Edge predictions are applied to upper-triangular edges only to avoid redundancy ([omtra/models/vector_field.py:674-679]()).

**Sources:** [omtra/models/vector_field.py:334-344]()

---

## Loss Functions

The model supports multiple loss types configured via `configure_loss_fns()`:

```mermaid
graph TB
    subgraph "Flow Matching Losses"
        ContLoss["Continuous Features<br/>MSELoss<br/>ℓ(x_1_pred, x_1_true)"]
        CatLoss["Categorical Features<br/>CrossEntropyLoss<br/>ℓ(logits, x_1_true)"]
    end
    
    subgraph "Optional: Time-Scaled Weighting"
        TimeWeight["w(t) = 1/(1-t)²<br/>Emphasizes near-data predictions"]
    end
    
    subgraph "Auxiliary Losses"
        AuxLosses["Registered via<br/>aux_loss_name_to_class()<br/>e.g., structure validation"]
    end
    
    ContLoss --> Total["Total Loss"]
    CatLoss --> Total
    AuxLosses --> Total
    
    TimeWeight -.->|"if time_scaled_loss=True"| ContLoss
    TimeWeight -.->|"if time_scaled_loss=True"| CatLoss
```

**Flow matching loss computation:**

For continuous modalities (positions, vectors):
```
loss = MSE(x_1_pred, x_1_true)
```

For categorical modalities (atom types, charges, bond orders):
```
loss = CrossEntropy(logits, x_1_true)
# Note: x_1_true set to -100 (ignore_index) for already-unmasked features
```

With time-scaled loss:
```
loss = weight(t) × base_loss
where weight(t) = clamp(1/(1-t)², max=100)
```

**Sources:** [omtra/models/omtra.py:226-266](), [omtra/models/omtra.py:444-514]()

### Special Loss Handling

- **Masked tokens**: Categorical targets are set to `-100` (ignore index) when the feature is already unmasked at time `t` ([omtra/models/omtra.py:437-442]())
- **Zero bond order**: Optional downweighting via `zero_bo_loss_weight` parameter ([omtra/models/omtra.py:246-250]())
- **Auxiliary losses**: Registered losses that support the task are automatically applied ([omtra/models/omtra.py:501-514]())

**Sources:** [omtra/models/omtra.py:423-516]()

---

## Integration and Sampling

The `VectorField.integrate()` method implements the ODE/SDE solver:

### Time Discretization

The integration supports multiple time spacing strategies:

```python
# Even spacing (default)
t = torch.linspace(0, 1, n_timesteps)

# Uneven spacing (log-dense near t=1)
t = 1.0 - torch.logspace(-2, 0, steps=n_timesteps+1).flip(0)
t = (t - t.min()) / (t.max() - t.min())
```

**Sources:** [omtra/models/vector_field.py:799-806]()

### Integration Step

At each timestep, `VectorField.step()`:

1. **Predicts destination** `x_1` using `VectorField.forward()` ([omtra/models/vector_field.py:966-976]())
2. **Updates continuous features** using the vector field:
   ```
   x_s = x_t + dt × vf(x_t, x_1, α_t, β_t)
   where vf = (α'_t/α_t)×x_t + ((α_t×β'_t - β_t×α'_t)/α_t)×x_1
   ```
   ([omtra/models/vector_field.py:1002-1027]())
3. **Updates categorical features** using Campbell's CTMC step with purity sampling ([omtra/models/vector_field.py:1029-1093]())

**Sources:** [omtra/models/vector_field.py:934-1094](), [omtra/models/vector_field.py:1156-1160]()

### Campbell Step for Categorical Features

The `campbell_step()` method implements discrete-time CTMC sampling:

```mermaid
graph TB
    SampleX1["Sample x_1 ~ Categorical(p_1|t)"]
    
    ComputeProbs["Compute probabilities<br/>unmask_prob = dt × (β'_t + η×β_t)/(1-β_t)<br/>mask_prob = dt × η"]
    
    PuritySample["Purity Sampling<br/>Select nodes to unmask<br/>based on prediction confidence"]
    
    Unmask["Unmask: x_t[will_unmask] = x_1"]
    
    CheckLast{"last_step?"}
    
    Mask["Mask: x_t[will_mask] = mask_token"]
    
    SampleX1 --> ComputeProbs
    ComputeProbs --> PuritySample
    PuritySample --> Unmask
    Unmask --> CheckLast
    CheckLast -->|"No"| Mask
    CheckLast -->|"Yes"| Return["Return x_s, x_1"]
    Mask --> Return
```

**Purity sampling** prioritizes unmasking nodes where the model is most confident, computed per-batch to maintain consistent unmasking rates.

**Sources:** [omtra/models/vector_field.py:1096-1154]()

---

## Multi-Task Architecture

The model supports training on multiple tasks simultaneously via `TaskDatasetCoupling`:

```mermaid
graph LR
    subgraph "Task Configuration"
        Tasks["Task Space<br/>['denovo_ligand',<br/>'fixed_protein_ligand',<br/>...]"]
        Datasets["Dataset Space<br/>['plinder',<br/>'pharmit',<br/>...]"]
        Coupling["Support Matrix<br/>Which (task, dataset) pairs<br/>are valid"]
    end
    
    subgraph "Model Adaptation"
        TaskEmbed["Task Embedding<br/>Learned per-task vector"]
        Modalities["Modality Sets<br/>Different tasks generate<br/>different modalities"]
        Edges["Edge Types<br/>Different tasks require<br/>different edges"]
    end
    
    Tasks --> Coupling
    Datasets --> Coupling
    Coupling --> TaskEmbed
    Coupling --> Modalities
    Coupling --> Edges
```

The architecture automatically adapts to each task by:

- Selecting appropriate **modalities** to generate vs. fix ([omtra/models/vector_field.py:115-136]())
- Building task-specific **edge types** ([omtra/models/vector_field.py:167-183]())
- Injecting **task embeddings** into node features ([omtra/models/vector_field.py:455-479]())
- Using task-specific **interpolant schedules** ([omtra/models/omtra.py:553]())

**Sources:** [omtra/models/omtra.py:111-113](), [omtra/models/vector_field.py:44](), [omtra/models/vector_field.py:115-183]()

---

## Key Architectural Design Decisions

### Heterogeneous Graph Representation

The model operates on **DGL heterogeneous graphs** with multiple node and edge types, enabling:
- Differentiated treatment of ligand atoms vs. protein atoms vs. pharmacophores
- Type-specific message passing and feature updates
- Flexible edge construction based on task requirements

**Sources:** [omtra/models/vector_field.py:40-103]()

### Interleaved Position and Feature Updates

Position updates are interleaved with convolution layers (every `convs_per_update` layers), allowing:
- Geometry-aware message passing with updated coordinates
- Co-evolution of structure and features
- Optional edge rebuilding based on updated positions

**Sources:** [omtra/models/vector_field.py:596-664]()

### GVP (Geometric Vector Perceptron) Layers

The use of GVP layers enables:
- **SE(3)-equivariant** message passing (important for 3D molecular generation)
- Joint processing of **scalar and vector features**
- Geometric reasoning through vector channels

**Sources:** [omtra/models/vector_field.py:224-250](), [omtra/models/vector_field.py:1181-1210]()

### Modular Output Heads

Separate output heads for different modalities allow:
- Task-specific generation (some tasks don't generate all modalities)
- Different output types (categorical vs. continuous vs. vector)
- Easy extension to new modalities

**Sources:** [omtra/models/vector_field.py:302-344]()

### Optional Self-Conditioning

Self-conditioning is implemented as an optional layer that:
- Computes residuals based on previous predictions
- Applies corrections to node and edge features
- Can be enabled/disabled without changing core architecture

**Sources:** [omtra/models/vector_field.py:347-357](), [omtra/models/self_conditioning.py:18-85]()

---