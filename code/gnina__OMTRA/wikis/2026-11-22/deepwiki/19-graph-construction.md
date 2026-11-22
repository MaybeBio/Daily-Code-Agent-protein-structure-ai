# Graph Construction

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
- [omtra/priors/prior_factory.py](omtra/priors/prior_factory.py)
- [omtra/priors/priors.py](omtra/priors/priors.py)
- [omtra/priors/sample.py](omtra/priors/sample.py)
- [omtra/tasks/tasks.py](omtra/tasks/tasks.py)
- [omtra/tasks/utils.py](omtra/tasks/utils.py)

</details>



## Purpose and Scope

This page describes how raw molecular data is converted into DGL heterogeneous graphs, which serve as the primary data structure for OMTRA's neural network operations. Graph construction involves defining node types, edge types, and their features, as well as implementing both static (predetermined) and dynamic (computed on-the-fly) edge building strategies.

For information about the molecular featurization that produces the raw node features, see [Molecular Featurization (MolXACE)](#6.3). For details on how tasks determine which graph components are included, see [Tasks and Modalities](#3.1).

---

## Graph Structure Overview

OMTRA uses DGL heterogeneous graphs with multiple node and edge types to represent protein-ligand complexes, pharmacophores, and their relationships.

### Node Types

Five node types are supported in the system:

| Node Type | Entity | Description |
|-----------|--------|-------------|
| `lig` | Ligand atoms | Atoms belonging to the primary ligand molecule |
| `prot_atom` | Protein atoms | All-atom representation of the protein |
| `prot_res` | Protein residues | Coarse-grained backbone representation (Cα atoms) |
| `pharm` | Pharmacophore points | Functional group features with direction vectors |
| `npnde` | Non-polymer entities | Cofactors, ions, or covalently-bound molecules |

**Sources:** [omtra/data/graph/__init__.py:13]()

### Edge Types

Edges fall into three categories:

**1. Self-Edges** (within node type):
- `lig_to_lig`: Ligand molecular bonds
- `prot_atom_to_prot_atom`: Protein atomic interactions
- `prot_res_to_prot_res`: Residue-level interactions
- `pharm_to_pharm`: Pharmacophore interactions
- `npnde_to_npnde`: Non-polymer entity bonds

**2. Cross-Edges** (between node types):
- `lig_to_prot_atom`, `prot_atom_to_lig`: Ligand-protein atomic interactions
- `lig_to_pharm`, `pharm_to_lig`: Ligand-pharmacophore associations
- `prot_atom_to_pharm`, `pharm_to_prot_atom`: Protein-pharmacophore interactions
- Additional permutations for all node type pairs

**3. Covalent Edges** (special chemical bonds):
- `prot_atom_covalent_lig`: Covalent protein-ligand bonds
- `prot_atom_covalent_npnde`: Covalent protein-cofactor bonds
- `prot_res_covalent_lig`, `prot_res_covalent_npnde`: Residue-level covalent edges
- Bidirectional versions: `lig_covalent_prot_atom`, etc.

**Sources:** [omtra/data/graph/__init__.py:14-36]()

```mermaid
graph TB
    subgraph "Node Types"
        lig["lig<br/>(Ligand Atoms)"]
        prot_atom["prot_atom<br/>(Protein Atoms)"]
        prot_res["prot_res<br/>(Protein Residues)"]
        pharm["pharm<br/>(Pharmacophores)"]
        npnde["npnde<br/>(Cofactors/Ions)"]
    end
    
    subgraph "Edge Categories"
        direction LR
        static["Static Edges<br/>lig_to_lig<br/>npnde_to_npnde<br/>(Predetermined)"]
        dynamic["Dynamic Edges<br/>prot_atom_to_lig<br/>lig_to_pharm<br/>(KNN/Radius)"]
        covalent["Covalent Edges<br/>prot_atom_covalent_lig<br/>(Distance-based)"]
    end
    
    lig -.->|"complete"| lig
    prot_atom -.->|"radius"| prot_atom
    prot_res -.->|"complete"| prot_res
    pharm -.->|"complete"| pharm
    npnde -.->|"k-hop"| npnde
    
    lig -->|"knn"| prot_atom
    prot_atom -->|"radius"| lig
    lig -->|"knn"| pharm
    pharm -->|"knn"| prot_atom
    
    prot_atom -.->|"covalent"| lig
    prot_atom -.->|"covalent"| npnde
```

**Diagram:** Node and Edge Type Hierarchy

**Sources:** [omtra/data/graph/__init__.py:13-36](), [configs/graph/default.yaml:1-80]()

---

## Core Construction Function

### `build_complex_graph`

The primary graph construction function is `build_complex_graph`, which assembles heterogeneous graphs from structured node and edge data.

```mermaid
graph LR
    subgraph "Input"
        node_data["node_data<br/>Dict[ntype, Dict[feat, Tensor]]"]
        edge_idxs["edge_idxs<br/>Dict[etype, Tensor]"]
        edge_data["edge_data<br/>Dict[etype, Dict[feat, Tensor]]"]
        task["task: Task"]
        graph_config["graph_config: DictConfig"]
    end
    
    subgraph "build_complex_graph"
        validate["Validate Node/Edge Types"]
        filter["Filter Edges by Task"]
        construct["Construct DGL Heterograph"]
        attach_node["Attach Node Features"]
        attach_edge["Attach Edge Features"]
    end
    
    output["DGL HeteroGraph"]
    
    node_data --> validate
    edge_idxs --> validate
    edge_data --> validate
    validate --> filter
    task --> filter
    graph_config --> filter
    filter --> construct
    construct --> attach_node
    node_data --> attach_node
    attach_node --> attach_edge
    edge_data --> attach_edge
    attach_edge --> output
```

**Diagram:** Graph Construction Pipeline

**Sources:** [omtra/data/graph/__init__.py:74-155]()

#### Function Signature

```python
def build_complex_graph(
    node_data: Dict[str, Dict[str, torch.Tensor]],
    edge_idxs: Dict[str, torch.Tensor],
    edge_data: Dict[str, Dict[str, torch.Tensor]],
    task=None,
    graph_config=None,
) -> dgl.DGLHeteroGraph
```

#### Input Format

**`node_data`**: Dictionary mapping node type to feature dictionaries
```python
{
    'lig': {
        'x_1_true': torch.Tensor,  # [n_atoms, 3] coordinates
        'a_1_true': torch.Tensor,  # [n_atoms] atom types
        'c_1_true': torch.Tensor,  # [n_atoms] charges
    },
    'prot_atom': {
        'x_1_true': torch.Tensor,
        'a_1_true': torch.Tensor,
        'res_id': torch.Tensor,
        # ...
    },
    # ...
}
```

**`edge_idxs`**: Dictionary mapping edge type to index tensors (shape `[2, n_edges]`)
```python
{
    'lig_to_lig': torch.Tensor,  # [2, n_bonds] - molecular bonds
    'prot_atom_covalent_lig': torch.Tensor,  # [2, n_cov] - covalent bonds
    # ...
}
```

**`edge_data`**: Dictionary mapping edge type to feature dictionaries
```python
{
    'lig_to_lig': {
        'e_1_true': torch.Tensor,  # [n_bonds] bond types
    },
}
```

**Sources:** [omtra/data/graph/__init__.py:74-80]()

#### Construction Logic

1. **Validation** [omtra/data/graph/__init__.py:83-95]()
   - Verify all node types are in the allowed set
   - Verify all edge types are in the allowed set
   - Check that edge data matches edge indices

2. **Node Count Determination** [omtra/data/graph/__init__.py:98-103]()
   - Extract number of nodes per type from feature tensor shapes
   - Set count to 0 for missing node types

3. **Edge Filtering** [omtra/data/graph/__init__.py:106-119]()
   - If `task` and `graph_config` provided, call `get_edges_for_task` to filter edges
   - Otherwise, include all edge types
   - Create edge construction dictionary with canonical edge type tuples

4. **Special Handling** [omtra/data/graph/__init__.py:122-137]()
   - Protein covalent bonds: Use radius graph (r=2.1Å) if `cov_prot_edges=True`
   - Stored as `prot_atom_covalent_prot_atom` for later use

5. **Graph Construction** [omtra/data/graph/__init__.py:143]()
   - Call `dgl.heterograph()` with edge dictionary and node counts

6. **Feature Attachment** [omtra/data/graph/__init__.py:146-153]()
   - Add node features to graph
   - Add edge features to graph

**Sources:** [omtra/data/graph/__init__.py:74-155]()

---

## Edge Construction Strategies

Edges are constructed using two fundamentally different approaches: **static** (predetermined from data) and **dynamic** (computed from spatial relationships).

### Static Edges

Static edges are predetermined during data preprocessing and stored directly in the dataset.

| Edge Type | Source | Description |
|-----------|--------|-------------|
| `lig_to_lig` | Molecular topology | Chemical bonds from RDKit/SDF files |
| `npnde_to_npnde` | Molecular topology | Chemical bonds in cofactors/ions |
| Covalent edges | Distance inference | Protein-ligand/cofactor covalent bonds |

Static edges are provided directly in the `edge_idxs` dictionary passed to `build_complex_graph`.

**Sources:** [omtra/dataset/plinder.py:719-735](), [omtra/dataset/pharmit.py:185-192]()

### Dynamic Edge Builders

Dynamic edges are computed on-the-fly based on spatial proximity. Three main builder types are registered:

#### Complete Graph Builder

Connects all nodes within the same type (excluding self-loops).

```python
@register_edge_builder("complete")
def complete_graph(src_pos, dst_pos, src_batch_idx, dst_batch_idx):
    edge_idxs = hetero_radius(src_pos, dst_pos, src_batch_idx, dst_batch_idx, r=float("Inf"))
    return edge_idxs
```

**Usage:** `lig_to_lig`, `pharm_to_pharm` (when not predetermined)

**Sources:** [omtra/data/graph/edge_builders.py:13-16]()

#### Radius Graph Builder

Connects nodes within a specified distance threshold.

```python
@register_edge_builder("radius")
def hetero_radius(src_pos, dst_pos, src_batch_idx, dst_batch_idx, r, max_num_neighbors=1000):
    edge_idxs = tc.radius(x=dst_pos, y=src_pos, batch_x=dst_batch_idx, batch_y=src_batch_idx, r=r, max_num_neighbors=max_num_neighbors)
    return edge_idxs
```

**Usage:** `prot_atom_to_prot_atom` (r=4.5Å), `prot_atom_to_lig` (r=8Å)

**Sources:** [omtra/data/graph/edge_builders.py:18-21]()

#### KNN Graph Builder

Connects each node to its k-nearest neighbors.

```python
@register_edge_builder("knn")
def hetero_knn(src_pos, dst_pos, src_batch_idx, dst_batch_idx, k):
    edge_idxs = tc.knn(x=dst_pos, y=src_pos, batch_x=dst_batch_idx, batch_y=src_batch_idx, k=k)
    return edge_idxs
```

**Usage:** `lig_to_prot_atom` (k=5), `pharm_to_prot_atom` (k=5), `lig_to_pharm` (k=3)

**Sources:** [omtra/data/graph/edge_builders.py:23-26]()

#### Symmetric Edge Builder

Creates the reverse direction of an edge using the inverse builder.

```python
@register_edge_builder("symmetric")
def symmetric(builder_fn, src_pos, dst_pos, src_batch_idx, dst_batch_idx):
    edge_idxs = builder_fn(dst_pos, src_pos, dst_batch_idx, src_batch_idx)
    return edge_idxs[[1,0]]
```

**Usage:** Automatically creates inverse edges for symmetric edge types like `pharm_to_lig` from `lig_to_pharm`.

**Sources:** [omtra/data/graph/edge_builders.py:28-31]()

```mermaid
graph TB
    subgraph "Edge Builder Factory"
        config["graph_config.edges"]
        register["edge_builder_register"]
        
        config -->|"read edge type config"| get_builders["get_edge_builders"]
        register -->|"lookup builder function"| get_builders
        
        get_builders -->|"partial(builder_fn, **params)"| complete["complete_graph<br/>(r=inf)"]
        get_builders -->|"partial(builder_fn, **params)"| radius["hetero_radius<br/>(r=4.5, 8.0, etc.)"]
        get_builders -->|"partial(builder_fn, **params)"| knn["hetero_knn<br/>(k=3, 5, etc.)"]
        get_builders -->|"symmetric wrapper"| sym["symmetric<br/>(wrapped builder)"]
    end
    
    subgraph "Runtime Usage"
        build_edges["build_edges function"]
        pos_data["Node positions<br/>(x_t)"]
        batch_idx["Batch indices"]
        
        complete --> build_edges
        radius --> build_edges
        knn --> build_edges
        sym --> build_edges
        
        pos_data --> build_edges
        batch_idx --> build_edges
        
        build_edges --> new_edges["Edge indices<br/>[2, n_edges]"]
    end
```

**Diagram:** Edge Builder Factory and Runtime Usage

**Sources:** [omtra/data/graph/edge_factory.py:7-31](), [omtra/tasks/utils.py:16-63]()

---

## Task-Specific Edge Filtering

The `get_edges_for_task` function filters the complete set of possible edges based on what node types and modalities are present in a given task.

### Filtering Logic

```mermaid
graph TB
    task["Task Definition"]
    graph_config["Graph Config"]
    
    task -->|"extract"| ntypes["Node Types Present<br/>(from modalities)"]
    task -->|"extract"| mod_edges["Modality Edges<br/>(edges with features)"]
    
    ntypes --> filter["Filter Logic"]
    mod_edges --> filter
    graph_config -->|"configured edges"| filter
    
    filter -->|"check src/dst in ntypes"| valid1["Valid Node Types?"]
    filter -->|"in config OR modality OR covalent"| valid2["Configured or Special?"]
    
    valid1 -->|"yes"| valid2
    valid2 -->|"yes"| include["Include Edge Type"]
    
    include --> output["Set of Edge Types<br/>for Task"]
```

**Diagram:** Task-Based Edge Filtering

**Sources:** [omtra/data/graph/__init__.py:45-72]()

### Filter Rules

1. **Node Type Requirement**: Both source and destination node types must be present in the task's modalities
2. **Configuration Requirement**: Edge must be either:
   - Explicitly listed in `graph_config.edges`
   - A modality edge (has features being predicted)
   - A covalent edge (special handling)
   - Listed in `symmetric_etypes` (creates inverse edge)

**Example:**

For `rigid_docking` task:
- Modalities present: `lig`, `prot_atom`, `prot_res`
- Edges included: `lig_to_lig`, `lig_to_prot_atom`, `prot_atom_to_lig`, `prot_atom_to_prot_atom`, covalent edges
- Edges excluded: Any involving `pharm` or `npnde`

**Sources:** [omtra/data/graph/__init__.py:45-72](), [omtra/tasks/tasks.py:33-44]()

---

## Configuration System

Graph construction behavior is controlled by a YAML configuration file that specifies edge types, builder methods, and parameters.

### Default Configuration Structure

```yaml
edges:
  lig_to_lig:
    type: complete
  
  prot_atom_to_prot_atom:
    type: radius
    params:
      r: 4.5
  
  prot_atom_to_lig:
    type: radius
    params:
      r: 8
  
  lig_to_prot_atom:
    type: knn
    params:
      k: 5
  
  lig_to_pharm:
    type: knn
    params:
      k: 3
  
  pharm_to_pharm:
    type: complete

symmetric_etypes:
  - lig_to_pharm
  - npnde_to_pharm
  - lig_to_npnde
  - prot_atom_to_npnde

cov_prot_edges: true
```

### Configuration Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `edges.{etype}.type` | string | Builder type: `complete`, `knn`, `radius`, `khop` |
| `edges.{etype}.params` | dict | Builder-specific parameters (k, r, etc.) |
| `symmetric_etypes` | list | Edge types that should have inverse edges created |
| `cov_prot_edges` | bool | Whether to infer protein covalent bonds |

**Sources:** [configs/graph/default.yaml:1-80]()

---

## Runtime Edge Computation

While `build_complex_graph` creates the initial graph structure, many edges are recomputed during model execution because node positions change during the flow matching process.

### The `build_edges` Function

Located in `omtra/tasks/utils.py`, this function dynamically rebuilds edges based on current node positions.

```mermaid
graph TB
    input_g["Input Graph<br/>(with x_t positions)"]
    task["Task"]
    config["graph_config"]
    
    input_g --> get_pos["Extract Node Positions<br/>(x_t per node type)"]
    input_g --> get_batch["Extract Batch Indices"]
    
    get_pos --> loop["For Each Edge Type"]
    get_batch --> loop
    task --> loop
    config --> loop
    
    loop --> skip1{"Predetermined?<br/>(lig_to_lig, npnde_to_npnde)"}
    skip1 -->|"yes"| next["Next Edge Type"]
    skip1 -->|"no"| skip2{"Covalent?"}
    skip2 -->|"yes"| next
    skip2 -->|"no"| check_nodes{"Nodes Exist?"}
    
    check_nodes -->|"no"| next
    check_nodes -->|"yes"| get_builder["Get Edge Builder"]
    
    get_builder --> call_builder["Call Builder with<br/>src_pos, dst_pos, batch_idx"]
    call_builder --> special{"prot_atom_to_prot_atom?"}
    
    special -->|"yes"| combine["Combine with<br/>Covalent Edges"]
    special -->|"no"| add["Add Edges to Graph"]
    combine --> add
    
    add --> next
    next --> loop
    
    loop --> output_g["Output Graph<br/>(updated edges)"]
```

**Diagram:** Runtime Edge Rebuilding Process

**Sources:** [omtra/tasks/utils.py:16-63]()

### When Edges are Rebuilt

Dynamic edges are rebuilt:
1. **After Prior Sampling**: Initial positions from prior distributions [omtra/tasks/utils.py:16-63]()
2. **During VectorField Integration**: At each timestep as positions evolve
3. **After Self-Conditioning**: When using self-conditioning refinement

Predetermined edges (`lig_to_lig`, `npnde_to_npnde`) and covalent edges are never rebuilt.

**Sources:** [omtra/tasks/utils.py:27-34]()

### Covalent Edge Combination

For `prot_atom_to_prot_atom` edges, covalent bonds are combined with spatial edges to preserve chemical connectivity:

```python
def get_combined_edges(g, new_edge_idxs: torch.Tensor):
    cov_edge_idxs = torch.stack(g.edges(etype='prot_atom_covalent_prot_atom'), dim=0)
    edges = torch.cat([cov_edge_idxs, new_edge_idxs], dim=1)
    edges_t = edges.t()
    unique_edges_t = torch.unique(edges_t, dim=0)
    return unique_edges_t.t()
```

This ensures that covalently bonded atoms remain connected even if they're beyond the spatial radius threshold.

**Sources:** [omtra/tasks/utils.py:94-106]()

---

## Dataset-Specific Construction

Both Plinder and Pharmit datasets implement graph construction, but with different data sources and complexities.

### Plinder Dataset Construction

The Plinder dataset constructs graphs representing protein-ligand complexes with optional pharmacophores and non-polymer entities.

```mermaid
graph TB
    get_system["get_system<br/>Slice Zarr arrays"]
    
    get_system --> convert_lig["convert_ligand<br/>LigandData → node/edge dicts"]
    get_system --> convert_prot["convert_protein<br/>StructureData → node/edge dicts"]
    get_system --> convert_pharm["convert_pharmacophore<br/>PharmacophoreData → node dict"]
    get_system --> convert_npnde["convert_npndes<br/>Dict[LigandData] → node/edge dicts"]
    
    convert_lig --> merge["Merge Dictionaries"]
    convert_prot --> merge
    convert_pharm --> merge
    convert_npnde --> merge
    
    merge --> build["build_complex_graph"]
    
    subgraph "Special Handling"
        covalent["Infer Covalent Bonds<br/>infer_covalent_bonds"]
        fake_atoms["Add Fake Atoms<br/>(if configured)"]
        extra_feats["Add Extra Features<br/>(hybridization, aromaticity)"]
    end
    
    convert_lig -.-> covalent
    convert_lig -.-> fake_atoms
    convert_lig -.-> extra_feats
    
    build --> sample_priors["sample_priors"]
    sample_priors --> final_graph["Final DGL Graph"]
```

**Diagram:** Plinder Graph Construction Flow

**Sources:** [omtra/dataset/plinder.py:172-430](), [omtra/dataset/plinder.py:902-972]()

#### Key Steps

1. **System Retrieval** [omtra/dataset/plinder.py:172-430]()
   - Load receptor, ligand, pocket, pharmacophore, and npnde data from Zarr
   - Filter pocket residues based on proximity to ligand

2. **Ligand Conversion** [omtra/dataset/plinder.py:667-736]()
   - Convert to MolXACE representation
   - Add fake atoms if configured for de novo generation
   - Encode atom types, charges, bond types
   - Infer covalent bonds to protein

3. **Protein Conversion** [omtra/dataset/plinder.py:492-581]()
   - Create `prot_atom` nodes with all-atom features
   - Create `prot_res` nodes with backbone (Cα) coordinates
   - Encode elements, residues, chain IDs
   - Apply pocket mask to filter residues

4. **Pharmacophore Conversion** [omtra/dataset/plinder.py:877-900]()
   - Sample subset of interacting pharmacophores (up to `max_pharms_sampled`)
   - Create `pharm` nodes with coordinates, types, direction vectors

5. **NPnDE Conversion** [omtra/dataset/plinder.py:738-875]()
   - Combine all non-polymer entities
   - Apply k-hop edge expansion
   - Infer covalent bonds to protein

6. **Graph Construction** [omtra/dataset/plinder.py:959-961]()
   - Call `build_complex_graph` with merged dictionaries

7. **Prior Sampling** [omtra/dataset/plinder.py:964-965]()
   - Sample initial states for generated modalities

**Sources:** [omtra/dataset/plinder.py:74-972]()

### Pharmit Dataset Construction

The Pharmit dataset is simpler, containing only ligand and (optionally) pharmacophore data.

```mermaid
graph TB
    getitem["__getitem__<br/>Slice Zarr arrays"]
    
    getitem --> lig_slice["Slice Ligand Node Data<br/>x, a, c, extra_feats"]
    getitem --> edge_slice["Slice Ligand Edge Data<br/>e, edge_index"]
    getitem --> pharm_slice["Slice Pharmacophore Data<br/>(if task includes pharm)"]
    
    lig_slice --> xace["Create MolXACE Object"]
    edge_slice --> xace
    
    xace --> fake{"Fake Atoms?"}
    fake -->|"yes"| add_fake["add_fake_atoms"]
    fake -->|"no"| dense
    add_fake --> dense["sparse_to_dense"]
    
    dense --> node_dict["Construct node_data dict"]
    dense --> edge_dict["Construct edge_data dict"]
    dense --> idx_dict["Construct edge_idxs dict"]
    
    pharm_slice --> node_dict
    
    node_dict --> build["build_complex_graph"]
    edge_dict --> build
    idx_dict --> build
    
    build --> sample_priors["sample_priors"]
    sample_priors --> final_graph["Final DGL Graph"]
```

**Diagram:** Pharmit Graph Construction Flow

**Sources:** [omtra/dataset/pharmit.py:74-231]()

#### Key Steps

1. **Data Slicing** [omtra/dataset/pharmit.py:89-125]()
   - Use `graph_lookup` arrays to find node/edge ranges for each molecule
   - Slice `x`, `a`, `c`, `e`, `edge_index` arrays

2. **Extra Features** [omtra/dataset/pharmit.py:96-115]()
   - Optionally load hybridization, aromaticity, ring membership, chirality
   - Or convert to condensed atom typing

3. **MolXACE Creation** [omtra/dataset/pharmit.py:137-147]()
   - Construct MolXACE object from sliced arrays
   - Add fake atoms if configured
   - Convert from sparse to dense representation

4. **Pharmacophore Sampling** [omtra/dataset/pharmit.py:195-217]()
   - Sample 1 to `max_pharms_sampled` pharmacophore points
   - Create node features for sampled points

5. **Graph Construction** [omtra/dataset/pharmit.py:219-225]()
   - Assemble dictionaries for `node_data`, `edge_idxs`, `edge_data`
   - Call `build_complex_graph`

6. **Prior Sampling** [omtra/dataset/pharmit.py:228-229]()
   - Sample initial states for generated modalities

**Sources:** [omtra/dataset/pharmit.py:74-231]()

---

## Summary

Graph construction in OMTRA follows a consistent pattern:

1. **Data Preparation**: Datasets convert molecular data into node/edge dictionaries
2. **Static Edges**: Predetermined edges (molecular bonds, covalent bonds) are included directly
3. **Graph Assembly**: `build_complex_graph` validates inputs and creates a DGL heterograph
4. **Dynamic Edges**: Spatial edges are computed at runtime based on node positions
5. **Task Filtering**: Only edges relevant to the current task are included
6. **Prior Sampling**: Initial states are sampled for modalities being generated

This flexible architecture allows the same graph construction code to handle diverse tasks ranging from ligand-only conformer generation to complex protein-ligand-pharmacophore modeling.

**Sources:** [omtra/data/graph/__init__.py:74-155](), [omtra/dataset/plinder.py:74-972](), [omtra/dataset/pharmit.py:74-231](), [omtra/tasks/utils.py:16-63]()

---