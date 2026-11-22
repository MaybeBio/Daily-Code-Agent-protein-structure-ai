# Multimer-Specific Processing

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [openfold/data/data_modules.py](openfold/data/data_modules.py)
- [openfold/utils/loss.py](openfold/utils/loss.py)
- [openfold/utils/multi_chain_permutation.py](openfold/utils/multi_chain_permutation.py)
- [tests/test_permutation.py](tests/test_permutation.py)
- [train_openfold.py](train_openfold.py)

</details>



## Purpose and Scope

This page documents the specialized data processing and alignment logic required for predicting multi-chain protein complexes. When training or running inference on protein complexes with multiple chains, OpenFold must handle:

1. **Multi-chain data loading** - Reading and organizing features for all chains in a complex
2. **Chain permutation alignment** - Resolving the ambiguity of which predicted chain corresponds to which ground truth chain
3. **Inter-chain feature computation** - Distinguishing intra-chain vs inter-chain interactions
4. **Multimer-specific loss calculations** - Computing separate losses for chain interfaces vs chain interiors

For information about the base data pipeline, see [Data Pipeline and Feature Generation](#6.1). For MSA and template processing differences in multimer mode, see [MSA and Template Processing](#6.3). For the AlphaFold model itself, see [AlphaFold Model Overview](#5.2).

**Sources:** [openfold/data/data_modules.py:292-504](), [openfold/utils/multi_chain_permutation.py:1-543](), [train_openfold.py:109-112]()

---

## Multimer Data Loading Architecture

### Dataset Classes

```mermaid
graph TB
    subgraph "Monomer Pipeline"
        SingleDataset["OpenFoldSingleDataset<br/>Per-chain loading"]
        DataPipeline["DataPipeline<br/>HhsearchHitFeaturizer"]
    end
    
    subgraph "Multimer Pipeline"
        SingleMultimerDataset["OpenFoldSingleMultimerDataset<br/>Whole-complex loading"]
        MultimerDataPipeline["DataPipelineMultimer<br/>HmmsearchHitFeaturizer"]
    end
    
    subgraph "Filtering & Sampling"
        FilteredDataset["OpenFoldDataset<br/>(monomer)"]
        MultimerDataset["OpenFoldMultimerDataset<br/>(multimer filtering)"]
    end
    
    subgraph "PyTorch Lightning"
        DataModule["OpenFoldDataModule"]
        MultimerDataModule["OpenFoldMultimerDataModule"]
    end
    
    SingleDataset --> DataPipeline
    SingleMultimerDataset --> MultimerDataPipeline
    
    SingleDataset --> FilteredDataset
    SingleMultimerDataset --> MultimerDataset
    
    FilteredDataset --> DataModule
    MultimerDataset --> MultimerDataModule
    
    DataModule --> Training["Training Loop"]
    MultimerDataModule --> Training
    
    style SingleMultimerDataset fill:#e1ffe1
    style MultimerDataset fill:#e1ffe1
    style MultimerDataModule fill:#e1ffe1
```

**Analysis:** The multimer pipeline uses parallel classes to the monomer pipeline but with key differences. `OpenFoldSingleMultimerDataset` loads entire PDB structures with all chains, while `OpenFoldSingleDataset` loads individual chains. The multimer dataset uses `HmmsearchHitFeaturizer` for template search instead of `HhsearchHitFeaturizer`. The `OpenFoldMultimerDataset` applies multimer-specific stochastic filtering based on per-chain cluster sizes.

**Sources:** [openfold/data/data_modules.py:292-354](), [openfold/data/data_modules.py:664-754](), [openfold/data/data_modules.py:1062-1133]()

---

### Key Differences from Monomer Mode

| Aspect | Monomer | Multimer |
|--------|---------|----------|
| **Data Unit** | Individual chain | Entire complex |
| **Cache File** | `chain_data_cache_path` | `mmcif_data_cache_path` |
| **Cache Structure** | `{chain_id: metadata}` | `{pdb_id: {chain_ids, seqs, ...}}` |
| **Template Search** | HHSearch | HMMSearch |
| **Identifier** | `{pdb_id}_{chain_id}` | `{pdb_id}` |
| **Filtering** | Per-chain cluster size | Per-chain cluster sizes (list) |
| **Min Residues** | No requirement | 200 residues (distillation only) |

**Sources:** [openfold/data/data_modules.py:26-290](), [openfold/data/data_modules.py:292-504]()

---

### OpenFoldSingleMultimerDataset

The `OpenFoldSingleMultimerDataset` class handles loading multi-chain complexes from mmCIF files. Key features:

```mermaid
graph LR
    subgraph "Input"
        MMCIF["mmCIF File<br/>{pdb_id}.cif"]
        AlignDir["Alignment Directory<br/>{pdb_id}_{chain_id}/"]
        Cache["mmcif_data_cache<br/>{pdb_id: {chain_ids, seqs}}"]
    end
    
    subgraph "Processing"
        Parse["mmcif_parsing.parse()"]
        Pipeline["DataPipelineMultimer<br/>process_mmcif()"]
        Features["FeaturePipeline<br/>process_features()"]
    end
    
    subgraph "Output"
        AllChain["all_chain_features<br/>Concatenated chains"]
        AsymID["asym_id<br/>Chain identifiers"]
        EntityID["entity_id<br/>Sequence identifiers"]
    end
    
    MMCIF --> Parse
    AlignDir --> Pipeline
    Cache --> Pipeline
    Parse --> Pipeline
    Pipeline --> Features
    Features --> AllChain
    Features --> AsymID
    Features --> EntityID
```

**Key implementation details:**

- **Line 405-413:** Uses `HmmsearchHitFeaturizer` instead of `HhsearchHitFeaturizer`
- **Line 418-420:** Wraps monomer `DataPipeline` in `DataPipelineMultimer`
- **Line 452-458:** Loads all chains sharing the same PDB ID using alignment index filtering
- **Line 490-493:** Calls `FeaturePipeline.process_features()` with `is_multimer=True` flag

**Sources:** [openfold/data/data_modules.py:292-504]()

---

### Multimer-Specific Filtering

The `OpenFoldMultimerDataset` applies additional filtering criteria beyond the monomer dataset:

```python
# Hard filters (deterministic)
- resolution <= 9.0 Å
- No single amino acid > 80% of total sequence
- Total residues >= 200 (distillation only)

# Stochastic filters
- Per-chain cluster size: P(sample chain) = 1 / cluster_size
```

**Implementation:**

[openfold/data/data_modules.py:684-706]() - `deterministic_train_filter` checks resolution, amino acid composition, and minimum residue count.

[openfold/data/data_modules.py:707-719]() - `get_stochastic_train_filter_prob` returns a list of probabilities, one per chain, based on cluster sizes.

[openfold/data/data_modules.py:737-741]() - Extends weights list with one entry per chain rather than one per complex.

**Sources:** [openfold/data/data_modules.py:664-754]()

---

## Chain Permutation Alignment

### The Permutation Problem

During training, the model predicts chains in an arbitrary order, but the ground truth has a fixed order. Without permutation alignment, the model would be penalized for predicting the correct structure in the "wrong" order.

```mermaid
graph TB
    subgraph "Example: Hetero-pentamer A2B3"
        PredOrder["Predicted Order:<br/>A2 - A1 - B2 - B3 - B1"]
        GTOrder["Ground Truth Order:<br/>A1 - A2 - B1 - B2 - B3"]
        Problem["Problem: Direct comparison<br/>would compute wrong loss"]
    end
    
    subgraph "Solution: Permutation Alignment"
        FindPerm["Find optimal permutation<br/>that minimizes RMSD"]
        Reorder["Reorder ground truth<br/>to match prediction"]
        ComputeLoss["Compute loss with<br/>aligned ground truth"]
    end
    
    PredOrder --> Problem
    GTOrder --> Problem
    Problem --> FindPerm
    FindPerm --> Reorder
    Reorder --> ComputeLoss
```

**Sources:** [openfold/utils/multi_chain_permutation.py:430-512](), [tests/test_permutation.py:80-174]()

---

### Permutation Alignment Algorithm

The chain permutation alignment follows Algorithm 4 from the AlphaFold-Multimer supplement:

```mermaid
graph TB
    Start["Input:<br/>Predicted positions<br/>Ground truth positions"]
    
    SelectAnchor["1. Select anchor chain<br/>get_least_asym_entity_or_longest_length()"]
    
    LoopAnchors["2. For each candidate anchor:"]
    
    ComputeTransform["3. Compute optimal transform<br/>calculate_optimal_transform()<br/>Uses Kabsch algorithm"]
    
    AlignTransform["4. Apply transform to all GT chains<br/>Rotate and translate"]
    
    GreedyMatch["5. Greedy chain matching<br/>greedy_align()<br/>Match chains by minimum RMSD"]
    
    ComputeRMSD["6. Compute total RMSD<br/>for this permutation"]
    
    BestPerm["7. Select permutation<br/>with lowest RMSD"]
    
    ReorderGT["8. Reorder ground truth<br/>merge_labels()"]
    
    Output["Output:<br/>Aligned ground truth features"]
    
    Start --> SelectAnchor
    SelectAnchor --> LoopAnchors
    LoopAnchors --> ComputeTransform
    ComputeTransform --> AlignTransform
    AlignTransform --> GreedyMatch
    GreedyMatch --> ComputeRMSD
    ComputeRMSD --> BestPerm
    BestPerm --> ReorderGT
    ReorderGT --> Output
```

**Sources:** [openfold/utils/multi_chain_permutation.py:430-512]()

---

### Key Functions in Chain Permutation

#### Anchor Selection

**Function:** `get_least_asym_entity_or_longest_length()`

**Purpose:** Select a stable reference chain for alignment that minimizes permutation ambiguity.

**Algorithm:**
1. Count how many copies of each unique sequence exist (entity counts)
2. Select entity with fewest copies (e.g., in A2B3, select A)
3. If tie, select entity with longest sequence
4. Return one ground truth chain and all matching predicted chains

**Example:** For A2B3 complex:
- Entity A has 2 chains → count = 2
- Entity B has 3 chains → count = 3
- Select entity A (fewer copies)
- Return: `anchor_gt_asym=1` (or 2), `anchor_pred_asym=[1,2]`

**Sources:** [openfold/utils/multi_chain_permutation.py:111-164](), [tests/test_permutation.py:60-78]()

---

#### Optimal Transform Computation

**Function:** `get_optimal_transform()` and `kabsch_rotation()`

**Purpose:** Compute rotation matrix R and translation vector x that best align predicted anchor to ground truth anchor.

**Kabsch Algorithm:**
```
Input: Source points P, Target points Q
1. Center both: P' = P - mean(P), Q' = Q - mean(Q)
2. Compute covariance: H = P'^T · Q'
3. SVD: H = U · Σ · V^T
4. Construct correction: S = diag(1, 1, sign(det(U·V^T)))
5. Optimal rotation: R = U · S · V^T
6. Translation: x = mean(Q) - mean(P) · R
```

**Sources:** [openfold/utils/multi_chain_permutation.py:35-62](), [openfold/utils/multi_chain_permutation.py:64-108]()

---

#### Greedy Chain Matching

**Function:** `greedy_align()`

**Purpose:** Match remaining chains to minimize total RMSD using greedy algorithm.

**Algorithm:**
```
For each predicted chain i:
    best_rmsd = infinity
    best_match = None
    
    For each unused ground truth chain j with same sequence:
        Compute RMSD between i and j
        If RMSD < best_rmsd:
            best_rmsd = RMSD
            best_match = j
    
    Mark best_match as used
    Record alignment (i, best_match)

Return: List of (pred_idx, gt_idx) tuples
```

**Sources:** [openfold/utils/multi_chain_permutation.py:167-228](), [tests/test_permutation.py:80-174]()

---

### Permutation Alignment Flow

```mermaid
sequenceDiagram
    participant Train as train_openfold.py
    participant Wrapper as OpenFoldWrapper
    participant Perm as multi_chain_permutation_align()
    participant Compute as compute_permutation_alignment()
    participant Merge as merge_labels()
    
    Train->>Wrapper: training_step(batch)
    Wrapper->>Wrapper: outputs = model(batch)
    Wrapper->>Perm: multi_chain_permutation_align(<br/>out=outputs, features=batch,<br/>ground_truth=gt_features)
    
    Perm->>Perm: labels = split_ground_truth_labels()
    
    Perm->>Compute: compute_permutation_alignment()
    
    Compute->>Compute: Select anchor chains
    Compute->>Compute: For each anchor candidate:
    Compute->>Compute: - compute optimal transform
    Compute->>Compute: - apply transform to GT
    Compute->>Compute: - greedy_align chains
    Compute->>Compute: - compute total RMSD
    Compute->>Compute: Return best permutation
    
    Compute-->>Perm: align, per_asym_residue_index
    
    Perm->>Merge: merge_labels(align, labels)
    Merge-->>Perm: reordered ground truth
    
    Perm-->>Wrapper: updated batch with aligned GT
    
    Wrapper->>Wrapper: loss = compute_loss(outputs, batch)
```

**Sources:** [train_openfold.py:109-112](), [openfold/utils/multi_chain_permutation.py:515-542]()

---

### Label Merging After Permutation

**Function:** `merge_labels()`

After determining the optimal permutation, ground truth features must be reordered to match the predicted structure:

**Process:**
1. Split original ground truth by chain using `asym_id`
2. For each permutation tuple `(pred_idx, gt_idx)`:
   - Select ground truth chain `gt_idx`
   - Index it using residues from predicted chain `pred_idx`
   - Append to new concatenated tensor
3. Pad if necessary to match input size

**Example:**
```
Alignment: [(0,1), (1,0), (2,3), (3,4), (4,2)]

Original GT: [Chain0, Chain1, Chain2, Chain3, Chain4]
Reordered GT: [Chain1, Chain0, Chain3, Chain4, Chain2]
                  ↑       ↑       ↑       ↑       ↑
              pred 0   pred 1  pred 2  pred 3  pred 4
```

**Sources:** [openfold/utils/multi_chain_permutation.py:249-286](), [tests/test_permutation.py:175-254]()

---

## Inter-Chain Feature Pairing

### Asymmetric ID (asym_id)

The `asym_id` tensor identifies which chain each residue belongs to. It is the primary mechanism for distinguishing intra-chain from inter-chain pairs:

```mermaid
graph LR
    subgraph "Feature Tensors"
        AsymID["asym_id<br/>[1,1,1,2,2,2,3,3,3,3]"]
        Residues["residues<br/>[0,1,2,0,1,2,0,1,2,3]"]
    end
    
    subgraph "Pair Mask Construction"
        SameChain["intra_chain_mask<br/>asym_id[i] == asym_id[j]"]
        DiffChain["interface_mask<br/>asym_id[i] != asym_id[j]"]
    end
    
    subgraph "Applications"
        Loss["Separate FAPE losses:<br/>intra_chain_bb_loss<br/>interface_bb_loss"]
        TM["Interface pTM:<br/>Only inter-chain pairs"]
        Clash["Clash detection:<br/>Respect chain boundaries"]
    end
    
    AsymID --> SameChain
    AsymID --> DiffChain
    SameChain --> Loss
    DiffChain --> Loss
    DiffChain --> TM
    AsymID --> Clash
```

**Sources:** [openfold/utils/loss.py:291-312]()

---

### Entity ID (entity_id)

The `entity_id` tensor groups chains with identical sequences. Multiple chains can share the same `entity_id`:

```
Example: A2B3 complex
asym_id:   [1, 1, 1, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5]
entity_id: [1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2]
            └─ Chain A1 ┘ └─ Chain A2 ┘ └─────────── Chains B1, B2, B3 ──────────┘
```

**Usage:**
- **Permutation alignment:** Group chains by entity for matching
- **Anchor selection:** Select entity with fewest chains
- **Filtering:** Validate sequence composition per entity

**Sources:** [openfold/utils/multi_chain_permutation.py:336-353]()

---

### Symmetry ID (sym_id)

The `sym_id` (not extensively used in current code) can mark symmetric chains for specialized handling. In most cases, `sym_id` equals `asym_id`.

**Sources:** [tests/test_permutation.py:54-58]()

---

## Multimer-Specific Loss Components

### Backbone FAPE Loss Separation

The backbone FAPE loss is computed separately for intra-chain and inter-chain residue pairs:

```mermaid
graph TB
    subgraph "Input"
        Traj["Structure Module trajectory<br/>Predicted frames"]
        AsymID["asym_id<br/>Chain assignments"]
        GT["Ground truth<br/>backbone_rigid_tensor"]
    end
    
    subgraph "Mask Construction"
        IntraMask["intra_chain_mask<br/>asym_id[..., i] == asym_id[..., j]"]
        InterMask["interface_mask<br/>1 - intra_chain_mask"]
    end
    
    subgraph "Loss Computation"
        IntraLoss["backbone_loss()<br/>pair_mask=intra_chain_mask<br/>config.intra_chain_backbone"]
        InterLoss["backbone_loss()<br/>pair_mask=interface_mask<br/>config.interface_backbone"]
    end
    
    subgraph "Weighted Sum"
        FinalLoss["weighted_bb_loss =<br/>intra_weight × intra_loss +<br/>inter_weight × inter_loss"]
    end
    
    Traj --> IntraLoss
    Traj --> InterLoss
    AsymID --> IntraMask
    AsymID --> InterMask
    GT --> IntraLoss
    GT --> InterLoss
    IntraMask --> IntraLoss
    InterMask --> InterLoss
    IntraLoss --> FinalLoss
    InterLoss --> FinalLoss
```

**Implementation:** [openfold/utils/loss.py:291-312]()

**Configuration:**
```python
# From config files
config.loss.fape.intra_chain_backbone.weight = 0.5
config.loss.fape.intra_chain_backbone.clamp_distance = 10.0
config.loss.fape.intra_chain_backbone.loss_unit_distance = 10.0

config.loss.fape.interface_backbone.weight = 0.5
config.loss.fape.interface_backbone.clamp_distance = 30.0
config.loss.fape.interface_backbone.loss_unit_distance = 20.0
```

**Sources:** [openfold/utils/loss.py:286-325]()

---

### Interface Predicted TM Score (ipTM)

The interface pTM score measures confidence in inter-chain relative positioning:

**Computation:**
1. Compute pairwise distance error logits
2. Construct pair mask: `asym_id[i] != asym_id[j]`
3. Calculate TM score using only inter-chain pairs
4. Weight by `1 / (1 + (d/d0)²)` where d0 depends on protein size

**Implementation:** [openfold/utils/loss.py:670-719]()

**Key code:**
```python
if interface and (asym_id is not None):
    pair_mask *= (asym_id[..., None] != asym_id[..., None, :])
```

The `interface=True` flag triggers inter-chain only computation.

**Sources:** [openfold/utils/loss.py:670-719]()

---

### Clash Loss with Chain Boundaries

The between-residue clash loss respects chain boundaries to avoid penalizing C-N bonds between chains:

**Logic:**
1. Compute all pairwise atom distances
2. Check if consecutive residues are in same chain:
   ```python
   neighbour_mask = (residue_index[i] + 1 == residue_index[j])
   if asym_id is not None:
       neighbour_mask = neighbour_mask & (asym_id[i] == asym_id[j])
   ```
3. Exclude C-N bonds across chain boundaries from penalties

**Implementation:** [openfold/utils/loss.py:1022-1034]()

**Sources:** [openfold/utils/loss.py:942-1094]()

---

## Training Integration

### Training Step with Permutation

```python
def training_step(self, batch, batch_idx):
    ground_truth = batch.pop('gt_features', None)
    outputs = self(batch)
    batch = tensor_tree_map(lambda t: t[..., -1], batch)
    
    if self.is_multimer:
        batch = multi_chain_permutation_align(
            out=outputs,
            features=batch,
            ground_truth=ground_truth
        )
    
    loss, loss_breakdown = self.loss(outputs, batch, _return_breakdown=True)
    return loss
```

**Key points:**
1. Ground truth is popped before model forward pass
2. Model predicts without seeing ground truth labels
3. After prediction, permutation alignment reorders ground truth
4. Loss is computed against aligned ground truth

**Sources:** [train_openfold.py:97-122]()

---

### Data Flow Diagram

```mermaid
graph TB
    subgraph "Data Loading"
        MMCIF["mmCIF File<br/>Multiple chains"]
        Dataset["OpenFoldSingleMultimerDataset"]
        Collate["Batch Collator"]
    end
    
    subgraph "Training Loop"
        Batch["Batch with gt_features"]
        PopGT["Pop ground_truth<br/>from batch"]
        Forward["model.forward(batch)"]
        Output["Model outputs"]
    end
    
    subgraph "Permutation"
        Split["split_ground_truth_labels()"]
        Align["compute_permutation_alignment()"]
        Reorder["merge_labels()"]
    end
    
    subgraph "Loss"
        IntraLoss["Intra-chain FAPE"]
        InterLoss["Inter-chain FAPE"]
        OtherLoss["LDDT, distogram, etc."]
        TotalLoss["Total weighted loss"]
    end
    
    MMCIF --> Dataset
    Dataset --> Collate
    Collate --> Batch
    Batch --> PopGT
    PopGT --> Forward
    Forward --> Output
    
    Output --> Split
    PopGT --> Split
    Split --> Align
    Align --> Reorder
    
    Reorder --> IntraLoss
    Reorder --> InterLoss
    Reorder --> OtherLoss
    
    IntraLoss --> TotalLoss
    InterLoss --> TotalLoss
    OtherLoss --> TotalLoss
```

**Sources:** [train_openfold.py:97-122](), [openfold/utils/loss.py:286-326]()

---

## Summary of Key Code Entities

### Data Classes
| Class | Purpose | Key Methods |
|-------|---------|-------------|
| `OpenFoldSingleMultimerDataset` | Load multi-chain complexes | `__getitem__()`, `_parse_mmcif()` |
| `OpenFoldMultimerDataset` | Stochastic filtering for multimers | `deterministic_train_filter()`, `looped_samples()` |
| `OpenFoldMultimerDataModule` | PyTorch Lightning data module | `setup()`, `train_dataloader()` |

### Permutation Functions
| Function | Purpose | Location |
|----------|---------|----------|
| `multi_chain_permutation_align()` | Main entry point | [multi_chain_permutation.py:515-542]() |
| `compute_permutation_alignment()` | Compute optimal permutation | [multi_chain_permutation.py:430-512]() |
| `get_least_asym_entity_or_longest_length()` | Select anchor chain | [multi_chain_permutation.py:111-164]() |
| `get_optimal_transform()` | Kabsch alignment | [multi_chain_permutation.py:64-108]() |
| `greedy_align()` | Greedy chain matching | [multi_chain_permutation.py:167-228]() |
| `merge_labels()` | Reorder ground truth | [multi_chain_permutation.py:249-286]() |

### Loss Functions
| Function | Purpose | Multimer-Specific |
|----------|---------|-------------------|
| `fape_loss()` | FAPE with chain separation | Lines 291-312 check `asym_id` |
| `compute_tm()` | pTM/ipTM calculation | `interface=True` for ipTM |
| `between_residue_clash_loss()` | Clash detection | Lines 1024-1025 respect chain boundaries |

**Sources:** [openfold/data/data_modules.py:1-1133](), [openfold/utils/multi_chain_permutation.py:1-543](), [openfold/utils/loss.py:1-1304]()

---