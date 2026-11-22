# Data Processing Pipelines

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [omtra/data/xace_ligand.py](omtra/data/xace_ligand.py)
- [omtra/utils/misc.py](omtra/utils/misc.py)
- [omtra_pipelines/pharmit_dataset/guts/phase1.py](omtra_pipelines/pharmit_dataset/guts/phase1.py)
- [omtra_pipelines/pharmit_dataset/guts/phase2.py](omtra_pipelines/pharmit_dataset/guts/phase2.py)
- [omtra_pipelines/pharmit_dataset/readme.md](omtra_pipelines/pharmit_dataset/readme.md)
- [omtra_pipelines/pharmit_dataset/run_phase1.py](omtra_pipelines/pharmit_dataset/run_phase1.py)
- [omtra_pipelines/pharmit_dataset/run_phase2.py](omtra_pipelines/pharmit_dataset/run_phase2.py)
- [omtra_pipelines/plinder_dataset/plinder_pipeline.py](omtra_pipelines/plinder_dataset/plinder_pipeline.py)
- [omtra_pipelines/plinder_dataset/plinder_tutorial.ipynb](omtra_pipelines/plinder_dataset/plinder_tutorial.ipynb)

</details>



## Purpose and Scope

This document describes the data processing pipelines that transform raw molecular datasets into the Zarr-based storage format used by OMTRA for training. Two main pipelines are implemented: the **Plinder pipeline** for processing protein-ligand complexes and the **Pharmit pipeline** for processing ligand-only conformer libraries.

For information about how the processed data is loaded during training, see [Datasets and Data Loading](#5). For details on the specific dataset classes that read from Zarr stores, see [Zarr Storage System](#5.4). For graph construction from the processed data, see [Graph Construction](#5.5).

---

## Overview

The data processing pipelines convert raw structural data into featurized representations suitable for graph neural network training. Both pipelines share common molecular featurization components but differ in their data sources and processing stages.

| Pipeline | Input Source | Key Processing Steps | Output |
|----------|-------------|---------------------|---------|
| **Plinder** | Protein-ligand complexes from PDB | Ligand filtering, pocket extraction, covalent bond inference, pharmacophore generation, ESM3 embeddings | `receptor/`, `ligand/`, `pocket/`, `pharmacophore/`, `npnde/` Zarr arrays |
| **Pharmit** | Conformer database | Database labeling, molecular featurization, pharmacophore generation, aggregation | `lig/node`, `lig/edge`, `pharm/node`, `db/` Zarr arrays |

**Shared Components:**
- **MolXACE**: Molecular representation encoding positions (x), atom types (a), charges (c), and bond orders (e)
- **Pharmacophore Extraction**: SMARTS-based pattern matching to identify interaction features with direction vectors
- **Graph Preparation**: Utilities for creating lookup tables and organizing data for efficient graph construction

Sources: [omtra_pipelines/plinder_dataset/plinder_pipeline.py](), [omtra_pipelines/pharmit_dataset/run_phase1.py](), [omtra_pipelines/pharmit_dataset/run_phase2.py](), [omtra/data/xace_ligand.py]()

---

## Pipeline Architecture

```mermaid
graph TB
    subgraph Plinder["Plinder Pipeline (omtra_pipelines/plinder_dataset/)"]
        PlinderDB[("Plinder Database<br/>PDB complexes")]
        SystemProc["SystemProcessor<br/>plinder_pipeline.py"]
        
        Filter["filter_ligands()<br/>Filter valid ligands"]
        Receptor["process_receptor()<br/>Extract protein structure"]
        Pocket["extract_pocket()<br/>cutoff=8.0Å"]
        Covalent["infer_covalent_linkages()<br/>Bond detection"]
        ESM["ESM3_embed()<br/>Protein embeddings"]
        LigTensor["process_ligands()<br/>MoleculeTensorizer"]
        PharmExtract["get_pharmacophores()<br/>SMARTS patterns"]
        
        PlinderZarr[("Plinder Zarr Store<br/>receptor/, ligand/,<br/>pocket/, pharmacophore/")]
        
        PlinderDB --> SystemProc
        SystemProc --> Filter
        Filter --> Receptor
        Filter --> LigTensor
        Receptor --> Pocket
        LigTensor --> PharmExtract
        Receptor --> Covalent
        Pocket --> ESM
        LigTensor --> PlinderZarr
        PharmExtract --> PlinderZarr
        Receptor --> PlinderZarr
        Pocket --> PlinderZarr
        ESM --> PlinderZarr
    end
    
    subgraph Pharmit["Pharmit Pipeline (omtra_pipelines/pharmit_dataset/)"]
        PharmitDB[("Pharmit Database<br/>Conformer structures")]
        
        subgraph Phase1["Phase 1: run_phase1.py"]
            DBCrawler["DBCrawler<br/>Query conformers"]
            NameFinder["NameFinder<br/>Database labeling"]
            MolTensor["MoleculeTensorizer<br/>featurize_molecules()"]
            PharmData["get_pharmacophore_data()<br/>Pharmacophore features"]
            ChunkSaver["ChunkSaver<br/>Save to .npz chunks"]
        end
        
        subgraph Phase2["Phase 2: run_phase2.py"]
            ChunkInfo["ChunkInfoManager<br/>Read chunk metadata"]
            DistCalc["compute_num_node_dists()<br/>compute_valency_dists()"]
            ZarrInit["init_zarr_store()<br/>Initialize arrays"]
            ParallelWrite["write_data_to_store()<br/>Parallel Zarr writes"]
        end
        
        PharmitZarr[("Pharmit Zarr Store<br/>lig/node, lig/edge,<br/>pharm/node, db/")]
        
        PharmitDB --> DBCrawler
        DBCrawler --> NameFinder
        NameFinder --> MolTensor
        MolTensor --> PharmData
        PharmData --> ChunkSaver
        ChunkSaver --> ChunkInfo
        ChunkInfo --> DistCalc
        DistCalc --> ZarrInit
        ZarrInit --> ParallelWrite
        ParallelWrite --> PharmitZarr
    end
    
    subgraph Shared["Shared Components (omtra/data/)"]
        MolXACE["MolXACE<br/>xace_ligand.py<br/>positions, atom_types,<br/>charges, bonds"]
        PharmShared["get_pharmacophores()<br/>pharmacophores.py<br/>SMARTS patterns,<br/>direction vectors"]
        GraphUtils["build_lookup_table()<br/>omtra/utils/graph.py"]
    end
    
    SystemProc -.-> MolXACE
    SystemProc -.-> PharmShared
    MolTensor -.-> MolXACE
    PharmData -.-> PharmShared
    ChunkInfo -.-> GraphUtils
```

Sources: [omtra_pipelines/plinder_dataset/plinder_pipeline.py:67-793](), [omtra_pipelines/pharmit_dataset/run_phase1.py](), [omtra_pipelines/pharmit_dataset/run_phase2.py](), [omtra/data/xace_ligand.py:108-153]()

---

## Plinder Processing Pipeline

The Plinder pipeline processes protein-ligand complex structures from the Plinder database. The main processing class is `SystemProcessor` in [omtra_pipelines/plinder_dataset/plinder_pipeline.py:67-793]().

### Key Processing Steps

```mermaid
graph LR
    Input["PlinderSystem<br/>system_id"] --> FilterLig["filter_ligands()<br/>Remove invalid ligands"]
    
    FilterLig --> ProcessLig["process_ligands()<br/>MoleculeTensorizer"]
    FilterLig --> ProcessRec["process_receptor()<br/>Extract structure"]
    
    ProcessLig --> LigData["LigandData<br/>coords, atom_types,<br/>charges, bonds"]
    ProcessLig --> PharmData["PharmacophoreData<br/>coords, types, vectors"]
    
    ProcessRec --> RecData["StructureData<br/>coords, atom_names,<br/>res_ids, chain_ids"]
    RecData --> ExtractPocket["extract_pocket()<br/>cutoff=8.0Å"]
    ExtractPocket --> PocketData["StructureData<br/>+ pocket_embedding"]
    
    ProcessRec --> InferCov["infer_covalent_linkages()<br/>Distance-based detection"]
    
    ProcessLig --> ProcessNPNDE["process_npndes()<br/>Non-polymer entities"]
    
    LigData --> Output["SystemData<br/>Zarr Store"]
    PharmData --> Output
    RecData --> Output
    PocketData --> Output
    ProcessNPNDE --> Output
```

**SystemProcessor Constructor Parameters:**
- `system_id`: Plinder system identifier
- `ligand_atom_map`: Atom types for ligands (default: `lig_atom_type_map`)
- `npnde_atom_map`: Atom types for non-polymer entities (default: `npnde_atom_type_map`)
- `pocket_cutoff`: Distance cutoff for pocket extraction (default: 8.0 Å)
- `link_type`: Optional linked structure type (`"apo"`, `"pred"`, or `None`)

**Processing Workflow:**
1. **Ligand Filtering** [plinder_pipeline.py:712-741](): Loads ligand molecules and filters based on quality criteria
2. **Receptor Processing** [plinder_pipeline.py:141-176](): Extracts protein structure, checks backbone atom ordering
3. **Pocket Extraction** [plinder_pipeline.py:654-710](): Identifies residues within cutoff distance of ligand
4. **ESM3 Embedding** [plinder_pipeline.py:593-652](): Generates protein sequence embeddings for pockets
5. **Ligand Featurization** [plinder_pipeline.py:412-495](): Converts RDKit molecules to MolXACE format
6. **Pharmacophore Generation** [plinder_pipeline.py:458-481](): Identifies interaction features
7. **Covalent Bond Inference** [plinder_pipeline.py:377-410](): Detects protein-ligand covalent bonds

Sources: [omtra_pipelines/plinder_dataset/plinder_pipeline.py:67-793](), [omtra/data/xace_ligand.py:108-153](), [omtra/data/pharmacophores.py]()

---

## Pharmit Processing Pipeline

The Pharmit pipeline processes conformer libraries in a two-phase approach: featurization and aggregation.

### Phase 1: Featurization

Phase 1 processes conformer files in batches, generating molecular features and saving them to compressed `.npz` chunks. This phase is implemented in [omtra_pipelines/pharmit_dataset/run_phase1.py]().

```mermaid
graph TB
    DB[("Pharmit MySQL DB<br/>conformers.structures<br/>conformers.names")]
    
    DBCrawler["DBCrawler<br/>Batch query iterator<br/>query_size batches"]
    
    NameFinder["NameFinder<br/>query_name_from_smiles()<br/>Extract database labels"]
    
    ReadMol["read_mol_from_conf_file()<br/>Parse .sdf.gz conformers"]
    
    Filter["Filter steps:<br/>- max_num_atoms<br/>- min_num_atoms<br/>- RDKit validation"]
    
    MolTensor["MoleculeTensorizer<br/>featurize_molecules()<br/>Returns: MolXACE list"]
    
    PharmData["get_pharmacophore_data()<br/>get_pharmacophores() per mol"]
    
    DBLabel["generate_library_tensor()<br/>One-hot database encoding"]
    
    ChunkDict["Tensor Dictionary:<br/>positions, atom_types,<br/>atom_charges, bond_types,<br/>x_pharm, a_pharm, v_pharm,<br/>databases, tcv_counts"]
    
    ChunkSaver["ChunkSaver<br/>save_chunk_to_disk()<br/>chunk_data_*.npz<br/>chunk_info_*.pkl"]
    
    DB --> DBCrawler
    DBCrawler --> NameFinder
    DBCrawler --> ReadMol
    NameFinder --> DBLabel
    ReadMol --> Filter
    Filter --> MolTensor
    MolTensor --> PharmData
    PharmData --> ChunkDict
    DBLabel --> ChunkDict
    ChunkDict --> ChunkSaver
```

**Key Classes and Functions:**

- **`DBCrawler`** [guts/phase1.py:175-237](): Iterates over database in batches using cursor-based pagination
- **`NameFinder`** [guts/phase1.py:103-172](): Queries molecule names from database to extract source labels (e.g., PubChem, ZINC)
- **`process_batch()`** [run_phase1.py:65-162](): Main processing function applied to each batch
- **`ChunkSaver`** [guts/phase1.py:350-531](): Manages chunk storage with automatic offloading when threshold exceeded

**Chunk Data Structure:**

Each `.npz` chunk contains:
- `lig_x`: Atom positions (float32)
- `lig_a`: Atom types (int8)
- `lig_c`: Atom charges (int8)
- `lig_e`: Bond types (int8)
- `lig_edge_idx`: Bond indices (int32)
- `node_lookup`: Graph lookup table (int64, shape: [n_mols, 2])
- `edge_lookup`: Edge lookup table (int64, shape: [n_mols, 2])
- `pharm_x`, `pharm_a`, `pharm_v`: Pharmacophore data
- `pharm_lookup`: Pharmacophore lookup table
- `database`: Database one-hot encoding

Each `.pkl` chunk info file contains:
- `n_mols`, `n_atoms`, `n_edges`, `n_pharm`: Counts
- `p_atoms`: Distribution of atoms per molecule
- `p_pharms_given_atoms`: Conditional distribution p(n_pharms | n_atoms)
- `tcv_counts`: Type-charge-valency statistics

Sources: [omtra_pipelines/pharmit_dataset/run_phase1.py](), [omtra_pipelines/pharmit_dataset/guts/phase1.py]()

### Phase 2: Aggregation

Phase 2 reads all chunk metadata, computes global distributions, and writes data to a unified Zarr store with parallel writes. This phase is implemented in [omtra_pipelines/pharmit_dataset/run_phase2.py]().

```mermaid
graph TB
    ChunkData[("Phase 1 Output<br/>chunk_data/*.npz<br/>chunk_info/*.pkl")]
    
    ChunkInfo["ChunkInfoManager<br/>Read all chunk_info/*.pkl<br/>Build DataFrame"]
    
    ComputeDist["compute_num_node_dists()<br/>Merge p(n_atoms, n_pharms)<br/><br/>compute_valency_dists()<br/>Merge p(type, charge, valency)"]
    
    ComputeBound["compute_write_boundaries()<br/>Build lookup tables<br/>Compute global offsets"]
    
    InitStore["init_zarr_store()<br/>Create array hierarchy:<br/>lig/node/{x,a,c,graph_lookup}<br/>lig/edge/{e,edge_index,graph_lookup}<br/>pharm/node/{x,a,v,graph_lookup}<br/>db/db"]
    
    BuildLocks["build_lock_register()<br/>Lock per Zarr chunk<br/>for parallel writes"]
    
    Pool["Multiprocessing Pool<br/>n_cpus workers<br/>init_worker(locks, store_path)"]
    
    Write["write_data_to_store()<br/>Acquire locks<br/>Write to Zarr arrays<br/>with global offsets"]
    
    ZarrOut[("Zarr Store<br/>train.zarr")]
    DistOut[("Distribution Files<br/>*_dists.npz<br/>*_valency_table.yml")]
    
    ChunkData --> ChunkInfo
    ChunkInfo --> ComputeDist
    ComputeDist --> ComputeBound
    ComputeBound --> InitStore
    InitStore --> BuildLocks
    BuildLocks --> Pool
    Pool --> Write
    ChunkInfo --> Write
    Write --> ZarrOut
    ComputeDist --> DistOut
```

**Key Processing Steps:**

1. **Metadata Aggregation** [guts/phase2.py:18-204](): 
   - `ChunkInfoManager` reads all chunk info files into a DataFrame
   - Computes global distributions for p(n_atoms, n_pharms) and p(type, charge, valency)

2. **Boundary Computation** [guts/phase2.py:149-187]():
   - Calculates start/end indices for each chunk in the global Zarr arrays
   - Computes offset values to convert local indices to global indices

3. **Zarr Store Initialization** [guts/phase2.py:253-312]():
   - Creates hierarchical array structure with appropriate chunk sizes
   - Arrays automatically chunked for efficient access

4. **Parallel Writing** [run_phase2.py:79-179]():
   - Each worker acquires locks for affected Zarr chunks
   - Writes data with computed global offsets
   - Lock ordering prevents deadlocks

**Zarr Array Structure:**

| Array Path | Shape | Dtype | Chunk Size | Description |
|------------|-------|-------|------------|-------------|
| `lig/node/x` | `(n_atoms, 3)` | float32 | `(nodes_per_chunk, 3)` | Atom positions |
| `lig/node/a` | `(n_atoms,)` | int8 | `(nodes_per_chunk,)` | Atom types |
| `lig/node/c` | `(n_atoms,)` | int8 | `(nodes_per_chunk,)` | Atom charges |
| `lig/node/graph_lookup` | `(n_graphs, 2)` | int64 | `(graphs_per_chunk, 2)` | Node index ranges per graph |
| `lig/edge/e` | `(n_edges,)` | int8 | `(edges_per_chunk,)` | Bond types |
| `lig/edge/edge_index` | `(n_edges, 2)` | int32 | `(edges_per_chunk, 2)` | Bond connectivity |
| `lig/edge/graph_lookup` | `(n_graphs, 2)` | int64 | `(graphs_per_chunk, 2)` | Edge index ranges per graph |
| `pharm/node/x` | `(n_pharms, 3)` | float32 | `(pharm_per_chunk, 3)` | Pharmacophore positions |
| `pharm/node/a` | `(n_pharms,)` | int8 | `(pharm_per_chunk,)` | Pharmacophore types |
| `pharm/node/v` | `(n_pharms, 4, 3)` | float32 | `(pharm_per_chunk, 4, 3)` | Direction vectors |
| `pharm/node/graph_lookup` | `(n_graphs, 2)` | int64 | `(graphs_per_chunk, 2)` | Pharm index ranges per graph |
| `db/db` | `(n_graphs, 14)` | bool | `(graphs_per_chunk, 14)` | Database one-hot labels |

Sources: [omtra_pipelines/pharmit_dataset/run_phase2.py](), [omtra_pipelines/pharmit_dataset/guts/phase2.py]()

---

## Molecular Featurization (MolXACE)

The `MolXACE` data structure and `MoleculeTensorizer` class provide the core molecular featurization used by both pipelines. This representation is defined in [omtra/data/xace_ligand.py]().

### MolXACE Data Structure

```mermaid
graph LR
    RDKitMol["RDKit Mol<br/>3D coordinates"] --> Tensorizer["MoleculeTensorizer<br/>rdmol_to_xace()"]
    
    Tensorizer --> MolXACE["MolXACE Dataclass"]
    
    MolXACE --> x["x: positions<br/>np.ndarray (n_atoms, 3)<br/>float32"]
    MolXACE --> a["a: atom_types<br/>np.ndarray (n_atoms,)<br/>int (index in atom_map)"]
    MolXACE --> c["c: atom_charges<br/>np.ndarray (n_atoms,)<br/>int (formal charge)"]
    MolXACE --> e["e: bond_types<br/>np.ndarray (n_bonds,)<br/>int (1=single, 2=double, 3=triple)"]
    MolXACE --> edge_idxs["edge_idxs: bond_indices<br/>np.ndarray (n_bonds, 2)<br/>Upper triangular only"]
    MolXACE --> tcv["tcv_counts: dict<br/>(type, charge, valency) -> count<br/>Valency statistics"]
```

**MolXACE Fields:**
- **`x`**: Atom positions from conformer (float32, shape: [n_atoms, 3])
- **`a`**: Atom types mapped to integer indices (int8)
- **`c`**: Formal atom charges (int8)
- **`e`**: Bond orders for upper-triangular edges (int8)
- **`edge_idxs`**: Bond connectivity, upper-triangular portion only (int32, shape: [n_bonds, 2])
- **`tcv_counts`**: Dictionary mapping (type_idx, charge, valency) tuples to occurrence counts

**Featurization Process** [xace_ligand.py:155-231]():

1. **Sanitization & Kekulization**: Standardize molecule representation
2. **Hydrogen Removal**: Remove explicit hydrogens unless `explicit_hydrogens=True`
3. **Position Extraction**: Get 3D coordinates from conformer
4. **Atom Featurization**: Map atom symbols to integer indices, extract formal charges
5. **Bond Extraction**: Build adjacency matrix, extract upper-triangular portion
6. **Valency Computation**: Calculate atom valencies and collect statistics
7. **Validation**: Check for invalid patterns (e.g., trivalent oxygen)

**MoleculeTensorizer** [xace_ligand.py:108-153]():
- Parallelizes featurization across multiple molecules
- Collects failure modes and statistics
- Returns: `(valid_molecules, failed_idxs, failure_counts, tcv_counts)`

**Common Failure Modes:**
- `"sanitization/kekulization"`: RDKit cannot process molecule
- `"multiple fragments"`: Molecule contains disconnected components
- `"positions"`: No 3D conformer available
- `"atom map"`: Atom type not in `atom_map`
- `"trivalent oxygen"`: Invalid valency detected

Sources: [omtra/data/xace_ligand.py:22-232]()

---

## Pharmacophore Extraction

Pharmacophore features are extracted using SMARTS pattern matching to identify interaction points and compute direction vectors. The main function is `get_pharmacophores()` in [omtra/data/pharmacophores.py]().

### Pharmacophore Types and SMARTS Patterns

| Type | Description | Example SMARTS |
|------|-------------|----------------|
| **Aromatic** | Aromatic ring centers | `a1aaaaa1`, `a1aaaa1` |
| **HydrogenDonor** | H-bond donors | `[!#6;!H0]`, `[#7&!H0]` |
| **HydrogenAcceptor** | H-bond acceptors | `[!$([#6,F,Cl,Br,I,o,s,nX3,#7v5,#15v5,#16v4,#16v6,*+1,*+2,*+3])]` |
| **Hydrophobic** | Hydrophobic features | `a1aaaaa1`, alkyl carbons |
| **PositiveIon** | Positive charges | `[+,+2,+3,+4]` |
| **NegativeIon** | Negative charges | `[-,-2,-3,-4]` |
| **LumpedHydrophobe** | Hydrophobic clusters | Combined hydrophobic atoms |

### Direction Vector Computation

```mermaid
graph TB
    Mol["RDKit Mol<br/>+ Optional Receptor"] --> MatchSMARTS["Match SMARTS Patterns<br/>Find pharmacophore atoms"]
    
    MatchSMARTS --> Centers["Compute Centers<br/>Mean position of matched atoms"]
    
    Centers --> Vectors["Compute Direction Vectors"]
    
    subgraph VectorCalc["Vector Calculation"]
        Donor["H-Donor: N/O -> H direction"]
        Acceptor["H-Acceptor: Lone pair direction"]
        Aromatic["Aromatic: Ring normal"]
        Ion["Ions: Nearest heavy atom direction"]
    end
    
    Vectors --> VectorCalc
    VectorCalc --> Normalize["Normalize Vectors<br/>Unit length"]
    
    Normalize --> Output["PharmacophoreData<br/>coords: (n_pharm, 3)<br/>types: (n_pharm,)<br/>vectors: (n_pharm, 4, 3)<br/>interactions: (n_pharm,)"]
    
    Mol --> CheckInteract["Check Receptor Interactions<br/>(if receptor provided)"]
    CheckInteract --> Output
```

**Direction Vector Details:**

Each pharmacophore center can have up to 4 direction vectors [pharmacophores.py]:
- **Hydrogen Donors**: Vector from heavy atom toward hydrogen
- **Hydrogen Acceptors**: Vector along lone pair direction (computed from geometry)
- **Aromatic Rings**: Vector perpendicular to ring plane
- **Ions**: Vector toward nearest heavy atom
- **Hydrophobic**: No specific direction (zero vectors)

**Interaction Detection** (when receptor provided):
- For each pharmacophore, checks if corresponding atoms are within 4.5 Å of receptor atoms
- Sets `interactions[i] = True` if interaction detected
- Used to filter pharmacophores that are actually engaging with the binding pocket

**Output Structure:**
- `coords`: Pharmacophore center positions (float32, shape: [n_pharm, 3])
- `types`: Pharmacophore type indices (int8, shape: [n_pharm])
- `vectors`: Direction vectors (float32, shape: [n_pharm, 4, 3])
- `interactions`: Boolean interaction flags (bool, shape: [n_pharm])

Sources: [omtra/data/pharmacophores.py](), [omtra_pipelines/plinder_dataset/plinder_pipeline.py:458-481](), [omtra_pipelines/pharmit_dataset/guts/phase1.py:288-318]()

---

## Data Processing Workflow Summary

```mermaid
graph TB
    subgraph Sources["Raw Data Sources"]
        PDB[("Plinder Database<br/>Protein-ligand<br/>complexes")]
        Pharmit[("Pharmit Database<br/>Conformer<br/>libraries")]
    end
    
    subgraph Processing["Processing Pipelines"]
        PlinderProc["Plinder Pipeline<br/>SystemProcessor<br/>- Filter ligands<br/>- Extract pockets<br/>- ESM3 embeddings<br/>- Featurization"]
        
        PharmitP1["Pharmit Phase 1<br/>- Database labeling<br/>- Featurization<br/>- Chunk to .npz"]
        
        PharmitP2["Pharmit Phase 2<br/>- Aggregate metadata<br/>- Compute distributions<br/>- Parallel Zarr write"]
    end
    
    subgraph Shared["Shared Components"]
        MolXACE["MolXACE<br/>Molecular representation<br/>(x, a, c, e)"]
        Pharm["Pharmacophore Extraction<br/>SMARTS patterns<br/>Direction vectors"]
        Graph["Graph Utilities<br/>Lookup tables<br/>Build functions"]
    end
    
    subgraph Output["Zarr Stores"]
        PlinderZ[("plinder.zarr<br/>receptor/, ligand/,<br/>pocket/, pharmacophore/,<br/>npnde/")]
        PharmitZ[("pharmit.zarr<br/>lig/node, lig/edge,<br/>pharm/node, db/")]
    end
    
    PDB --> PlinderProc
    Pharmit --> PharmitP1
    PharmitP1 --> PharmitP2
    
    PlinderProc -.-> MolXACE
    PlinderProc -.-> Pharm
    PharmitP1 -.-> MolXACE
    PharmitP1 -.-> Pharm
    PharmitP2 -.-> Graph
    
    PlinderProc --> PlinderZ
    PharmitP2 --> PharmitZ
    
    PlinderZ --> Training["Training Pipeline<br/>(see Dataset Loading)"]
    PharmitZ --> Training
```

**Key Differences Between Pipelines:**

| Aspect | Plinder | Pharmit |
|--------|---------|---------|
| **Processing Model** | Single-pass per system | Two-phase (featurize → aggregate) |
| **Parallelization** | System-level parallelization | Batch-level (Phase 1) + chunk-level (Phase 2) |
| **Additional Features** | Protein structures, pockets, ESM3 embeddings | Database labels, valency distributions |
| **Primary Use Case** | Protein-ligand tasks | Ligand-only generation |
| **Covalent Handling** | Detects and records covalent bonds | Not applicable |

Sources: [omtra_pipelines/plinder_dataset/plinder_pipeline.py](), [omtra_pipelines/pharmit_dataset/run_phase1.py](), [omtra_pipelines/pharmit_dataset/run_phase2.py](), [omtra/data/xace_ligand.py]()

---