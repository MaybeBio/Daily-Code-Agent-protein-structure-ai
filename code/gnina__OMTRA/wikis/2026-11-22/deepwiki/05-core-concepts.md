# Core Concepts

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [configs/graph/default.yaml](configs/graph/default.yaml)
- [omtra/data/graph/__init__.py](omtra/data/graph/__init__.py)
- [omtra/data/graph/edge_builders.py](omtra/data/graph/edge_builders.py)
- [omtra/data/graph/edge_factory.py](omtra/data/graph/edge_factory.py)
- [omtra/data/graph/register.py](omtra/data/graph/register.py)
- [omtra/dataset/pharmit.py](omtra/dataset/pharmit.py)
- [omtra/dataset/plinder.py](omtra/dataset/plinder.py)
- [omtra/models/omtra.py](omtra/models/omtra.py)
- [omtra/models/self_conditioning.py](omtra/models/self_conditioning.py)
- [omtra/models/vector_field.py](omtra/models/vector_field.py)
- [omtra/priors/prior_factory.py](omtra/priors/prior_factory.py)
- [omtra/priors/priors.py](omtra/priors/priors.py)
- [omtra/priors/sample.py](omtra/priors/sample.py)
- [omtra/tasks/tasks.py](omtra/tasks/tasks.py)
- [omtra/tasks/utils.py](omtra/tasks/utils.py)

</details>



This page introduces the fundamental concepts that underpin OMTRA's architecture and operation. Understanding these concepts is essential for working with the codebase, whether you're training models, running inference, or extending the system.

**Scope**: This page provides a high-level overview of tasks, modalities, flow matching, graph representation, priors, and conditional paths. For detailed information, see:
- [Tasks and Modalities](#3.1) for comprehensive task definitions and modality specifications
- [Flow Matching for Molecules](#3.2) for the mathematical formulation and implementation details
- [Graph Representation](#3.3) for graph construction and edge building mechanics

---

## Overview: The Task-Modality-Flow Matching Framework

OMTRA generates molecular structures using a task-based framework built on flow matching. Each **task** defines what to generate and what to condition on by specifying which **modalities** (molecular features) are fixed versus generated. The model learns to transform samples from a **prior distribution** at time t=0 to the target distribution at t=1 through a learned **vector field**.

### Core Architecture Flow

```mermaid
graph TB
    Task["Task Definition<br/>(e.g., rigid_docking)"]
    Modalities["Modality Specification<br/>groups_fixed + groups_generated"]
    Graph["DGL HeteroGraph<br/>node types: lig, prot_atom, pharm<br/>edge types: lig_to_lig, prot_atom_to_lig"]
    Priors["Prior Sampling<br/>x_0 ~ p_0"]
    FlowMatch["Flow Matching<br/>x_t = α_t·x_0 + β_t·x_1"]
    VectorField["VectorField.forward<br/>predicts x_1"]
    
    Task --> Modalities
    Modalities --> Graph
    Modalities --> Priors
    Graph --> Priors
    Priors --> FlowMatch
    FlowMatch --> VectorField
    VectorField --> |"integration"| FlowMatch
    
    style Task fill:#f9f9f9
    style VectorField fill:#f9f9f9
```

**Sources**: [omtra/models/omtra.py:55-186](), [omtra/tasks/tasks.py:1-226]()

---

## Tasks: Defining What to Generate

A **task** in OMTRA specifies a molecular generation problem by declaring which modality groups are fixed (provided as input) versus generated (predicted by the model).

### Task Definition Structure

```mermaid
graph LR
    TaskClass["Task Class<br/>(e.g., RigidDocking)"]
    FixedGroups["groups_fixed<br/>['ligand_identity',<br/>'protein_identity',<br/>'protein_structure']"]
    GeneratedGroups["groups_generated<br/>['ligand_structure']"]
    Priors["priors<br/>Dict[modality_name, prior_config]"]
    CondPaths["conditional_paths<br/>Dict[modality_name, path_fn]"]
    
    TaskClass --> FixedGroups
    TaskClass --> GeneratedGroups
    TaskClass --> Priors
    TaskClass --> CondPaths
```

**Sources**: [omtra/tasks/tasks.py:33-60](), [omtra/tasks/base_task.py]()

### Key Task Examples

| Task Name | Fixed Groups | Generated Groups | Use Case |
|-----------|-------------|------------------|----------|
| `denovo_ligand` | `[]` | `ligand_identity`, `ligand_structure` | Unconditional ligand generation |
| `rigid_docking` | `ligand_identity`, `protein_identity`, `protein_structure` | `ligand_structure` | Pose prediction with fixed protein |
| `flexible_docking` | `ligand_identity`, `protein_identity` | `ligand_structure`, `protein_structure` | Pose prediction with flexible protein |
| `fixed_protein_ligand_denovo` | `protein_identity`, `protein_structure` | `ligand_identity`, `ligand_structure` | De novo design for binding pocket |

**Sources**: [omtra/tasks/tasks.py:13-70]()

### Code Entity Mapping

Tasks are defined as classes inheriting from `Task` and registered using the `@register_task` decorator:

```python
@register_task("rigid_docking")
class RigidDocking(Task):
    groups_fixed = ["ligand_identity", "protein_identity", "protein_structure"]
    groups_generated = ["ligand_structure"]
```

- Task classes are located in [omtra/tasks/tasks.py]()
- Task registry: [omtra/tasks/register.py]()
- Task retrieval: `task_name_to_class(task_name)` function

**Sources**: [omtra/tasks/tasks.py:33-45](), [omtra/tasks/register.py]()

---

## Modalities and Modality Groups

**Modalities** are the fundamental features of molecular systems that OMTRA models. Each modality represents a specific type of data defined on graph nodes or edges.

### Modality Structure

```mermaid
graph TB
    Modality["Modality Object"]
    Name["name: str<br/>(e.g., 'lig_x', 'lig_a')"]
    Entity["entity_name: str<br/>(e.g., 'lig', 'prot_atom')"]
    GraphEntity["graph_entity: str<br/>('node' or 'edge')"]
    DataKey["data_key: str<br/>('x', 'a', 'c', 'e', 'v')"]
    IsCategorical["is_categorical: bool"]
    NumCategories["n_categories: int<br/>(if categorical)"]
    
    Modality --> Name
    Modality --> Entity
    Modality --> GraphEntity
    Modality --> DataKey
    Modality --> IsCategorical
    Modality --> NumCategories
```

**Sources**: [omtra/tasks/modalities.py]()

### Modality Data Keys

| Data Key | Meaning | Entity Types | Example Modality |
|----------|---------|--------------|------------------|
| `x` | 3D coordinates | `lig`, `prot_atom`, `pharm` | `lig_x`, `prot_atom_x` |
| `a` | Atom types | `lig`, `prot_atom`, `pharm` | `lig_a`, `pharm_a` |
| `c` | Formal charges | `lig` | `lig_c` |
| `e` | Bond orders | `lig_to_lig` | `lig_e` |
| `v` | Direction vectors | `pharm` | `pharm_v` |

**Sources**: [omtra/tasks/modalities.py]()

### Modality Groups

Modalities are organized into **groups** that represent coherent aspects of molecular systems:

| Group Name | Modalities Included | Description |
|------------|-------------------|-------------|
| `ligand_identity` | `lig_a`, `lig_c`, `lig_e` | Atom types, charges, bonds |
| `ligand_structure` | `lig_x` | 3D coordinates |
| `protein_identity` | `prot_atom_a`, `prot_res_a` | Protein sequence |
| `protein_structure` | `prot_atom_x` | Protein 3D structure |
| `pharmacophore` | `pharm_x`, `pharm_a`, `pharm_v` | Pharmacophore positions, types, vectors |

**Sources**: [omtra/tasks/modalities.py]()

### Modality Access in Code

```python
# Get modality object by name
modality = name_to_modality("lig_x")

# Access modality properties
entity_name = modality.entity_name  # "lig"
data_key = modality.data_key        # "x"
is_categorical = modality.is_categorical  # False

# Iterate over task modalities
for m in task_class.modalities_generated:
    print(f"Generating {m.name}")
```

**Sources**: [omtra/tasks/modalities.py](), [omtra/models/omtra.py:424-442]()

---

## Flow Matching: The Generative Process

OMTRA uses **flow matching** to generate molecular structures. This approach learns a time-dependent vector field that transports samples from a simple prior distribution at t=0 to the complex target distribution at t=1.

### Flow Matching Overview

```mermaid
graph LR
    Prior["Prior Distribution<br/>x_0 ~ p_0<br/>(e.g., Gaussian, Masked)"]
    Path["Conditional Path<br/>x_t = α_t·x_0 + β_t·x_1<br/>t ∈ [0,1]"]
    VF["Vector Field<br/>predicts x_1<br/>from x_t"]
    Target["Target Distribution<br/>x_1 ~ p_data"]
    
    Prior -->|"t=0"| Path
    Path -->|"sample t ~ U(0,1)"| VF
    VF -->|"integration"| Target
    Target -->|"t=1"| Path
    
    style Prior fill:#f9f9f9
    style Target fill:#f9f9f9
```

**Sources**: [omtra/models/omtra.py:386-516](), [omtra/models/vector_field.py:360-565]()

### Conditional Path Functions

The **conditional path** defines how features interpolate between prior (x_0) and target (x_1) states:

**Continuous Features** (positions):
```
x_t = α_t · x_0 + β_t · x_1
```

**Categorical Features** (atom types, bond orders):
```
x_t = {
    x_1           with probability β_t
    mask_token    with probability α_t
}
```

The interpolation weights α_t and β_t are computed by `InterpolantScheduler` based on time t.

**Sources**: [omtra/models/omtra.py:542-600](), [omtra/models/interpolant_scheduler.py]()

### Training Process

```mermaid
graph TB
    SampleT["Sample t ~ U(0,1)<br/>or Beta(α,1)"]
    SamplePath["Sample conditional path<br/>x_t = α_t·x_0 + β_t·x_1"]
    Forward["VectorField.forward<br/>predicts x_1_pred"]
    Loss["Compute Losses<br/>MSE for continuous<br/>CrossEntropy for categorical"]
    
    SampleT --> SamplePath
    SamplePath --> Forward
    Forward --> Loss
```

During training:
1. Sample time t from a distribution (uniform or beta)
2. Sample conditional path to get x_t
3. Predict x_1 using the vector field
4. Compute losses comparing predicted vs true x_1

**Sources**: [omtra/models/omtra.py:269-322](), [omtra/models/omtra.py:386-516]()

### Inference Process

```mermaid
graph LR
    SamplePrior["Sample x_0<br/>from prior"]
    InitTime["t = 0"]
    Step["VectorField.step<br/>update x_t"]
    CheckT{"t < 1?"}
    Output["x_1"]
    
    SamplePrior --> InitTime
    InitTime --> Step
    Step --> CheckT
    CheckT -->|"Yes"| Step
    CheckT -->|"No"| Output
```

During inference, the model integrates the vector field from t=0 to t=1:
1. Sample from prior distribution: x_0 ~ p_0
2. Integrate using `VectorField.integrate` with n_timesteps steps
3. At each step, predict x_1 and update x_t

**Sources**: [omtra/models/omtra.py:602-899](), [omtra/models/vector_field.py:902-1122]()

---

## Graph Representation

OMTRA represents molecular systems as **heterogeneous DGL graphs** with different node types and edge types.

### Graph Node Types

```mermaid
graph TB
    HeteroGraph["DGL HeteroGraph"]
    
    Lig["lig<br/>(ligand atoms)"]
    ProtAtom["prot_atom<br/>(protein atoms)"]
    ProtRes["prot_res<br/>(protein residues)"]
    Pharm["pharm<br/>(pharmacophores)"]
    Npnde["npnde<br/>(non-polymer entities)"]
    
    HeteroGraph --> Lig
    HeteroGraph --> ProtAtom
    HeteroGraph --> ProtRes
    HeteroGraph --> Pharm
    HeteroGraph --> Npnde
```

**Sources**: [omtra/data/graph/__init__.py:13-18]()

### Graph Edge Types

Edges connect nodes and enable message passing:

| Edge Type | Connection | Graph Type | Purpose |
|-----------|-----------|------------|---------|
| `lig_to_lig` | Ligand-Ligand | Complete | Bond structure |
| `prot_atom_to_prot_atom` | Protein-Protein | Radius (4.5Å) | Local protein structure |
| `lig_to_prot_atom` | Ligand-Protein | KNN (k=5) | Binding interactions |
| `prot_atom_to_lig` | Protein-Ligand | Radius (8Å) | Binding interactions |
| `lig_to_pharm` | Ligand-Pharmacophore | KNN (k=3) | Constraint satisfaction |
| `prot_atom_covalent_lig` | Protein-Ligand | Inferred | Covalent bonds |

**Sources**: [configs/graph/default.yaml:1-80](), [omtra/data/graph/__init__.py:13-42]()

### Graph Construction Process

```mermaid
graph TB
    NodeData["Node Data<br/>Dict[ntype, Dict[feature, Tensor]]"]
    EdgeIdxs["Edge Indices<br/>Dict[etype, Tensor]"]
    EdgeData["Edge Data<br/>Dict[etype, Dict[feature, Tensor]]"]
    
    BuildGraph["build_complex_graph()"]
    
    DGLGraph["DGL HeteroGraph"]
    
    AddEdges["build_edges()<br/>Add radius/KNN edges<br/>based on task config"]
    
    FinalGraph["Complete Graph"]
    
    NodeData --> BuildGraph
    EdgeIdxs --> BuildGraph
    EdgeData --> BuildGraph
    BuildGraph --> DGLGraph
    DGLGraph --> AddEdges
    AddEdges --> FinalGraph
```

**Process**:
1. `build_complex_graph()` creates initial graph with pre-computed edges (e.g., `lig_to_lig`)
2. `build_edges()` adds dynamic edges (radius, KNN) based on current node positions
3. Edge builders are configured per task in [configs/graph/default.yaml]()

**Sources**: [omtra/data/graph/__init__.py:74-155](), [omtra/tasks/utils.py:16-63]()

### Graph Data Storage

Node and edge features are stored as tensors in `g.nodes[ntype].data` and `g.edges[etype].data`:

```python
# Node features
g.nodes['lig'].data['x_t']        # Current positions
g.nodes['lig'].data['a_t']        # Current atom types
g.nodes['lig'].data['x_1_true']   # Target positions

# Edge features  
g.edges['lig_to_lig'].data['e_t']  # Current bond orders
```

Features are named with suffixes:
- `_0`: Prior/initial state
- `_t`: Current state at time t
- `_1_true`: Target/ground truth state
- `_1_pred`: Predicted final state

**Sources**: [omtra/models/omtra.py:388-402](), [omtra/dataset/plinder.py:667-830]()

---

## Priors: Initial Distributions

**Priors** define the initial distribution p_0 from which generation starts at t=0. Different modalities use different prior types.

### Prior Types

```mermaid
graph TB
    Priors["Prior Distributions"]
    
    Gaussian["gaussian<br/>x_0 ~ N(0, σ²I)<br/>for continuous features"]
    Masked["masked (CTMC)<br/>x_0 = mask_token<br/>for categorical features"]
    TargetDep["target_dependent_gaussian<br/>x_0 = x_1 + noise<br/>for protein flexibility"]
    Apo["apo_exp / apo_pred<br/>x_0 = apo_structure<br/>for protein conformations"]
    
    Priors --> Gaussian
    Priors --> Masked
    Priors --> TargetDep
    Priors --> Apo
```

**Sources**: [omtra/priors/priors.py:1-102]()

### Prior Configuration

Priors are configured per-modality in task definitions:

```python
# Example from RigidDocking task
priors = {
    'lig_x': {
        'type': 'gaussian',
        'params': {'std': 1.0}
    },
    'lig_a': {
        'type': 'masked',
    },
    'prot_atom_x': {
        'type': 'target_dependent_gaussian',
        'params': {'std': 0.1}
    }
}
```

**Sources**: [omtra/tasks/tasks.py:33-60](), [omtra/priors/prior_factory.py:5-34]()

### Prior Sampling

The `sample_priors()` function samples from configured priors and stores results in graph:

```python
# During training
g = sample_priors(g, task_class, prior_fns, training=True)

# After sampling, priors are stored as:
g.nodes['lig'].data['x_0']  # Sampled ligand positions
g.nodes['lig'].data['a_0']  # Sampled ligand atom types (mask tokens)
```

**Sources**: [omtra/priors/sample.py:10-113]()

### Prior Types and Use Cases

| Prior Type | Modalities | Training Behavior | Inference Behavior |
|------------|-----------|-------------------|-------------------|
| `gaussian` | `lig_x`, `pharm_x` | Sample from N(0,σ²) with OT alignment | Sample from N(0,σ²) |
| `masked` | `lig_a`, `lig_c`, `lig_e` | All tokens → mask | All tokens → mask |
| `target_dependent_gaussian` | `prot_atom_x` (flexible) | x_0 = x_1 + noise | x_0 = x_1 + noise |
| `apo_exp` | `prot_atom_x` (apo) | x_0 = apo structure | x_0 = apo structure |

**Sources**: [omtra/priors/priors.py:11-101](), [omtra/tasks/tasks.py:33-143]()

---

## Putting It All Together

### Complete Generation Pipeline

```mermaid
graph TB
    TaskDef["1. Task Definition<br/>RigidDocking:<br/>generate lig_x<br/>fix lig_a, prot_x"]
    
    DataLoad["2. Load Data<br/>Protein structure<br/>Ligand graph"]
    
    BuildGraph["3. Build Graph<br/>Add nodes/edges<br/>Store x_1_true"]
    
    SamplePrior["4. Sample Priors<br/>lig_x: x_0 ~ N(0,1)<br/>lig_a: fixed at x_1"]
    
    Training{"Training or<br/>Inference?"}
    
    TrainLoop["5a. Training Loop<br/>Sample t<br/>x_t = α_t·x_0 + β_t·x_1<br/>Predict x_1<br/>Compute loss"]
    
    InferLoop["5b. Inference Loop<br/>Integrate VectorField<br/>from t=0 to t=1<br/>n_timesteps steps"]
    
    Output["6. Output<br/>Generated ligand pose<br/>as SampledSystem"]
    
    TaskDef --> DataLoad
    DataLoad --> BuildGraph
    BuildGraph --> SamplePrior
    SamplePrior --> Training
    Training -->|"Train"| TrainLoop
    Training -->|"Infer"| InferLoop
    TrainLoop --> Output
    InferLoop --> Output
```

**Sources**: [omtra/models/omtra.py:269-899]()

### Key Classes and Functions

| Component | Primary Class/Function | File Location |
|-----------|----------------------|---------------|
| Main Model | `OMTRA` | [omtra/models/omtra.py:55]() |
| Vector Field | `VectorField` | [omtra/models/vector_field.py:40]() |
| Task Definitions | `Task` subclasses | [omtra/tasks/tasks.py]() |
| Graph Building | `build_complex_graph()` | [omtra/data/graph/__init__.py:74]() |
| Prior Sampling | `sample_priors()` | [omtra/priors/sample.py:10]() |
| Conditional Paths | `sample_conditional_path()` | [omtra/models/omtra.py:542]() |

**Sources**: [omtra/models/omtra.py](), [omtra/models/vector_field.py](), [omtra/tasks/tasks.py](), [omtra/data/graph/__init__.py](), [omtra/priors/sample.py]()

---

## Summary

The OMTRA system is built on four core concepts:

1. **Tasks** define molecular generation problems by specifying which modalities to generate versus fix
2. **Modalities** represent molecular features (positions, atom types, bonds, etc.) organized into coherent groups
3. **Flow Matching** provides the generative mechanism, learning to transform priors to targets through a vector field
4. **Graph Representation** uses heterogeneous DGL graphs to encode molecular structure and enable message passing

These concepts work together: tasks determine which modalities appear in graphs, priors initialize those modalities, and flow matching generates final structures by integrating a learned vector field over time.

For detailed information on specific aspects, see the child pages:
- [Tasks and Modalities](#3.1)
- [Flow Matching for Molecules](#3.2)
- [Graph Representation](#3.3)

**Sources**: [omtra/models/omtra.py](), [omtra/tasks/tasks.py](), [omtra/models/vector_field.py](), [omtra/data/graph/__init__.py]()

---