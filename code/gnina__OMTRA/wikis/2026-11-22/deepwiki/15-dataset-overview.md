# Dataset Overview

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [notebooks/working_with_graphs.ipynb](notebooks/working_with_graphs.ipynb)
- [notebooks/zarr_dev.ipynb](notebooks/zarr_dev.ipynb)
- [notebooks/zarr_memory_investigation.ipynb](notebooks/zarr_memory_investigation.ipynb)
- [omtra/dataset/dataset.py](omtra/dataset/dataset.py)
- [omtra/dataset/pharmit.py](omtra/dataset/pharmit.py)
- [omtra/dataset/plinder.py](omtra/dataset/plinder.py)
- [omtra/dataset/zarr_dataset.py](omtra/dataset/zarr_dataset.py)
- [omtra/tasks/tasks.py](omtra/tasks/tasks.py)

</details>



This page provides a high-level overview of the dataset system in OMTRA, including the available datasets, storage architecture, and access patterns. For detailed information about specific datasets, see [Plinder Dataset](#5.2), [Pharmit Dataset](#5.3), [Zarr Storage System](#5.4), and [Graph Construction](#5.5).

## Purpose and Scope

OMTRA uses two primary datasets for training multi-task generative models:
- **Plinder**: Protein-ligand complexes with structural information
- **Pharmit**: Ligand-only conformer data with pharmacophore annotations

All datasets inherit from a common interface and use Zarr-based storage for efficient chunk-cached access to large-scale molecular data. Datasets return DGL heterogeneous graphs that encode molecular structure according to task-specific requirements.

## Dataset Class Hierarchy

```mermaid
graph TB
    OMTRADataset["OMTRADataset<br/>(Abstract Base)<br/>omtra/dataset/dataset.py"]
    ZarrDataset["ZarrDataset<br/>(Zarr Storage Base)<br/>omtra/dataset/zarr_dataset.py"]
    PlinderDataset["PlinderDataset<br/>omtra/dataset/plinder.py"]
    PharmitDataset["PharmitDataset<br/>omtra/dataset/pharmit.py"]
    
    OMTRADataset --> ZarrDataset
    ZarrDataset --> PlinderDataset
    ZarrDataset --> PharmitDataset
    
    OMTRADataset -.->|"Defines"| Interface["__len__()<br/>__getitem__()<br/>get_num_nodes()<br/>get_num_edges()"]
    ZarrDataset -.->|"Adds"| ZarrFeatures["Zarr store access<br/>Chunk caching<br/>slice_array()"]
    PlinderDataset -.->|"Implements"| PlinderData["Protein+Ligand<br/>Pharmacophores<br/>Apo/Pred structures"]
    PharmitDataset -.->|"Implements"| PharmitData["Ligand conformers<br/>Pharmacophores"]
```

**Dataset Class Hierarchy**

Sources: [omtra/dataset/dataset.py:1-56](), [omtra/dataset/zarr_dataset.py:1-117](), [omtra/dataset/plinder.py:1-53](), [omtra/dataset/pharmit.py:1-24]()

## Available Datasets

| Dataset | Data Type | Node Types | Key Features | Storage Format |
|---------|-----------|------------|--------------|----------------|
| **Plinder** | Protein-ligand complexes | `lig`, `prot_atom`, `prot_res`, `npnde`, `pharm` | Holo/Apo/Pred structures, pockets, covalent bonds, pharmacophores | Zarr (by system) |
| **Pharmit** | Ligand conformers | `lig`, `pharm` | Small molecule conformers, pharmacophore features | Zarr (by molecule) |

Both datasets support:
- Multiple training splits (`train`, `val`, `test`)
- Chunk-based caching for efficient disk access
- Task-specific graph construction
- Prior sampling for generative modeling

Sources: [omtra/dataset/plinder.py:53-104](), [omtra/dataset/pharmit.py:24-55]()

## Task-Based Data Access

OMTRA datasets are accessed using `(task_name, idx)` tuples rather than simple integer indices. This design allows:
1. Task-specific feature generation (fixed vs. generated modalities)
2. Conditional path sampling based on task requirements
3. Prior distribution selection per task
4. Dynamic graph structure based on task needs

```mermaid
graph LR
    Input["(task_name, idx)"]
    TaskClass["Task Class<br/>from task_name_to_class()"]
    DataRetrieval["Retrieve Data<br/>from Zarr store"]
    GraphBuild["build_complex_graph()<br/>task-specific edges"]
    PriorSample["sample_priors()<br/>task-specific x_0"]
    Output["DGL HeteroGraph"]
    
    Input --> TaskClass
    Input --> DataRetrieval
    TaskClass --> GraphBuild
    DataRetrieval --> GraphBuild
    GraphBuild --> PriorSample
    TaskClass --> PriorSample
    PriorSample --> Output
```

**Task-Based Dataset Access Pattern**

Sources: [omtra/dataset/plinder.py:965-1032](), [omtra/dataset/pharmit.py:74-231](), [omtra/tasks/tasks.py:1-226]()

### Example Tasks and Dataset Usage

```mermaid
graph TB
    subgraph "Ligand-Only Tasks"
        DeNovoLigand["denovo_ligand<br/>Uses: Pharmit"]
        LigandConformer["ligand_conformer<br/>Uses: Pharmit"]
    end
    
    subgraph "Protein+Ligand Tasks"
        RigidDocking["rigid_docking<br/>Uses: Plinder"]
        FlexibleDocking["flexible_docking<br/>Uses: Plinder"]
        FixedProteinLigand["fixed_protein_ligand_denovo<br/>Uses: Plinder"]
    end
    
    subgraph "Pharmacophore Tasks"
        DeNovoPharm["denovo_ligand_pharmacophore<br/>Uses: Pharmit"]
        ProteinPharm["protein_pharmacophore<br/>Uses: Plinder"]
    end
    
    Pharmit["PharmitDataset"] -.-> DeNovoLigand
    Pharmit -.-> LigandConformer
    Pharmit -.-> DeNovoPharm
    
    Plinder["PlinderDataset"] -.-> RigidDocking
    Plinder -.-> FlexibleDocking
    Plinder -.-> FixedProteinLigand
    Plinder -.-> ProteinPharm
```

**Task-Dataset Coupling Examples**

Sources: [omtra/tasks/tasks.py:13-183]()

## Dataset Interface

All datasets implement the `OMTRADataset` abstract interface:

| Method | Purpose | Returns |
|--------|---------|---------|
| `__len__()` | Number of examples in dataset | `int` |
| `__getitem__((task, idx))` | Retrieve graph for task/index | `dgl.DGLHeteroGraph` |
| `get_num_nodes(task, start, end)` | Count nodes in index range | `torch.Tensor` or `dict` |
| `get_num_edges(task, start, end)` | Estimate edges in index range | `torch.Tensor` |
| `name` (property) | Dataset identifier | `str` ("plinder" or "pharmit") |

Sources: [omtra/dataset/dataset.py:7-56]()

## Zarr-Based Storage Architecture

Both Plinder and Pharmit datasets use Zarr for efficient storage and retrieval:

```mermaid
graph TB
    subgraph "Zarr Store Structure"
        Root["zarr.Group<br/>(root)"]
        
        subgraph "Node Data Groups"
            LigNode["lig/node/<br/>x, a, c, e, graph_lookup"]
            ProtNode["prot_atom/node/<br/>coords, elements, res_ids"]
            PharmNode["pharm/node/<br/>x, a, v, graph_lookup"]
        end
        
        subgraph "Edge Data Groups"
            LigEdge["lig/edge/<br/>edge_index, e, graph_lookup"]
        end
        
        Root --> LigNode
        Root --> ProtNode
        Root --> PharmNode
        Root --> LigEdge
    end
    
    subgraph "Caching System"
        ChunkFetcher["ChunkFetcher<br/>LRU cache<br/>cache_size=4"]
        SliceArray["slice_array()<br/>Multi-chunk slicing"]
    end
    
    LigNode -.-> ChunkFetcher
    ChunkFetcher --> SliceArray
    SliceArray --> Graph["Assembled Graph Data"]
```

**Zarr Storage and Caching Architecture**

Key features:
- **Chunked arrays**: Data split into chunks (e.g., 500 graphs per chunk)
- **LRU caching**: Recently accessed chunks kept in memory
- **Multi-chunk slicing**: `slice_array()` efficiently retrieves data spanning multiple chunks
- **Graph lookup tables**: Map graph indices to node/edge data ranges

Sources: [omtra/dataset/zarr_dataset.py:14-117]()

## Data Processing Pipeline

```mermaid
graph LR
    RawData["Raw Data<br/>PDB, SDF, CIF"]
    Process["Processing Pipeline<br/>SystemProcessor<br/>MoleculeTensorizer"]
    ZarrStore["Zarr Store<br/>{split}.zarr"]
    Dataset["Dataset Class<br/>PlinderDataset<br/>PharmitDataset"]
    Graph["DGL HeteroGraph"]
    
    RawData --> Process
    Process --> ZarrStore
    ZarrStore --> Dataset
    Dataset --> Graph
    
    Process -.->|"Generates"| Features["• MolXACE (x,a,c,e)<br/>• Pharmacophores<br/>• Pocket extraction<br/>• ESM3 embeddings"]
```

**Data Flow from Raw Files to Graphs**

The processing pipeline converts raw molecular data into Zarr stores during preprocessing. At training/inference time, datasets read from Zarr and construct task-specific DGL graphs.

Sources: [omtra/dataset/plinder.py:172-430](), [omtra/dataset/pharmit.py:74-231]()

## Output Format: DGL Heterographs

All datasets return `dgl.DGLHeteroGraph` objects with:

**Node Types**:
- `lig`: Ligand atoms
- `prot_atom`: Protein atoms
- `prot_res`: Protein residues (backbone)
- `npnde`: Non-polymer/non-drug entities (cofactors, ions)
- `pharm`: Pharmacophore points

**Node Features** (task-dependent):
- `x_1_true`: 3D coordinates
- `a_1_true`: Atom/residue types
- `c_1_true`: Charges (ligand atoms)
- `v_1_true`: Direction vectors (pharmacophores)
- Prior samples: `x_0`, `a_0`, etc.

**Edge Types** (task-dependent):
- `lig_to_lig`: Chemical bonds
- `prot_atom_to_prot_atom`: Protein contacts
- `lig_to_prot_atom`: Ligand-protein interactions
- `pharm_to_lig`: Pharmacophore-ligand relationships
- Covalent edges: Special handling for covalent bonds

Sources: [omtra/data/graph.py]() (referenced in build_complex_graph calls), [omtra/dataset/plinder.py:902-963]()

## Key Dataset Properties

### PlinderDataset Specific

| Property | Description |
|----------|-------------|
| `link_version` | Specifies Plinder database linking version |
| `system_lookup` | DataFrame mapping system indices to data ranges |
| `npnde_lookup` | DataFrame for non-polymer entities |
| `weighted_sampling` | Optional cluster-based sampling (controlled by `pskip_factor`) |
| `fake_atom_p` | Probability of adding fake atoms for de novo generation |

Sources: [omtra/dataset/plinder.py:54-104]()

### PharmitDataset Specific

| Property | Description |
|----------|-------------|
| `max_pharms_sampled` | Max pharmacophore points per molecule (default: 8) |
| `n_categories_dict` | Vocabulary sizes for categorical features |
| `graphs_per_chunk` | Number of graphs per Zarr chunk |

Sources: [omtra/dataset/pharmit.py:24-55]()

## Chunk-Based Batching

Datasets support efficient batching aligned with Zarr chunk boundaries:

```mermaid
graph LR
    ChunkIndex["retrieve_graph_chunks()<br/>frac_start, frac_end"]
    ChunkRanges["Chunk Index Tensor<br/>(n_chunks, 2)"]
    NumNodes["get_num_nodes()<br/>per chunk"]
    NumEdges["get_num_edges()<br/>per chunk"]
    Sampler["MultiTaskSampler<br/>edge-aware batching"]
    
    ChunkIndex --> ChunkRanges
    ChunkRanges --> NumNodes
    ChunkRanges --> NumEdges
    NumNodes --> Sampler
    NumEdges --> Sampler
```

**Chunk-Based Batch Construction**

This enables:
- Distributed training across chunk ranges
- Memory-efficient batch construction
- Edge-aware batching (keep batches under max edge count)

Sources: [omtra/dataset/pharmit.py:237-287](), [omtra/dataset/zarr_dataset.py:37-38]()

## Integration with Training

Datasets integrate with the training system through:

1. **MultiTaskDataModule**: Combines multiple datasets with task-specific sampling
2. **TaskDatasetCoupling**: Maps tasks to datasets and sampling probabilities
3. **MultiTaskSampler**: Creates batches respecting edge budgets and chunk boundaries
4. **Prior sampling**: Each `__getitem__` call samples priors based on task configuration

For more details on training integration, see [Multi-Task Learning](#7.3).

Sources: [omtra/dataset/plinder.py:965-1032](), [omtra/dataset/pharmit.py:74-231]()

---