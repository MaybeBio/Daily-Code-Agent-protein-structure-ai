# Loss Functions

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [openfold/data/data_modules.py](openfold/data/data_modules.py)
- [openfold/utils/loss.py](openfold/utils/loss.py)
- [train_openfold.py](train_openfold.py)

</details>



## Purpose and Scope

This document explains the loss functions used to train the OpenFold model. The loss system aggregates multiple complementary objectives that guide the model to predict accurate protein structures. For information about the model architecture that these losses train, see [Model Architecture](#5). For training pipeline details, see [Training Pipeline](#4.1).

All loss function implementations are located in [openfold/utils/loss.py](). The main entry point is the `AlphaFoldLoss` class, which combines individual loss components with configurable weights.

---

## Loss System Architecture

The OpenFold training loss consists of multiple components that collectively optimize different aspects of structure prediction:

```mermaid
graph TB
    subgraph "Model Outputs"
        SM["StructureModule outputs<br/>sm['frames'], sm['positions'],<br/>sm['angles']"]
        LOGITS["Auxiliary head outputs<br/>distogram_logits, lddt_logits,<br/>tm_logits, masked_msa_logits"]
        FINAL["final_atom_positions"]
    end
    
    subgraph "Ground Truth (batch)"
        GT_POS["backbone_rigid_tensor<br/>all_atom_positions"]
        GT_ANGLES["chi_angles_sin_cos<br/>chi_mask"]
        GT_MSA["true_msa<br/>bert_mask"]
        GT_OTHER["seq_mask, aatype,<br/>residue_index, asym_id"]
    end
    
    subgraph "AlphaFoldLoss Class"
        AGGREGATOR["loss() method<br/>Computes & weights all losses"]
    end
    
    subgraph "Loss Components"
        FAPE["fape_loss<br/>Backbone + Sidechain FAPE"]
        LDDT["lddt_loss<br/>pLDDT prediction"]
        DIST["distogram_loss<br/>Distance distribution"]
        TM["tm_loss<br/>TM-score prediction"]
        CHI["supervised_chi_loss<br/>Torsion angles"]
        VIOL["violation_loss<br/>Structural violations"]
        MSA["masked_msa_loss<br/>BERT-style MSA"]
        EXP["experimentally_resolved_loss<br/>Atom resolution"]
        COM["chain_center_of_mass_loss<br/>Multimer only"]
    end
    
    SM --> FAPE
    SM --> CHI
    SM --> VIOL
    LOGITS --> LDDT
    LOGITS --> DIST
    LOGITS --> TM
    LOGITS --> MSA
    LOGITS --> EXP
    FINAL --> FAPE
    FINAL --> LDDT
    FINAL --> TM
    FINAL --> VIOL
    FINAL --> COM
    
    GT_POS --> FAPE
    GT_POS --> LDDT
    GT_POS --> DIST
    GT_POS --> TM
    GT_POS --> VIOL
    GT_POS --> COM
    GT_ANGLES --> CHI
    GT_MSA --> MSA
    GT_OTHER --> FAPE
    GT_OTHER --> LDDT
    GT_OTHER --> DIST
    GT_OTHER --> TM
    GT_OTHER --> CHI
    GT_OTHER --> VIOL
    GT_OTHER --> MSA
    GT_OTHER --> EXP
    GT_OTHER --> COM
    
    FAPE --> AGGREGATOR
    LDDT --> AGGREGATOR
    DIST --> AGGREGATOR
    TM --> AGGREGATOR
    CHI --> AGGREGATOR
    VIOL --> AGGREGATOR
    MSA --> AGGREGATOR
    EXP --> AGGREGATOR
    COM --> AGGREGATOR
    
    AGGREGATOR --> TOTAL["Total Loss<br/>Scaled by sqrt(min(seq_len, crop_len))"]
```

**Sources:** [openfold/utils/loss.py:1685-1793](), [train_openfold.py:52](), [train_openfold.py:115-117]()

---

## AlphaFoldLoss Class

The `AlphaFoldLoss` class ([openfold/utils/loss.py:1685-1793]()) aggregates all individual loss components into a single training objective.

### Key Methods

| Method | Purpose |
|--------|---------|
| `__init__(config)` | Initializes with configuration specifying weights and parameters for each loss component |
| `loss(out, batch, _return_breakdown)` | Computes all enabled losses and returns weighted sum |
| `forward(out, batch, _return_breakdown)` | Wrapper around `loss()` for standard PyTorch Module interface |

### Loss Computation Flow

```mermaid
graph LR
    INPUT["Model outputs + batch"] --> PREPROC["Preprocessing"]
    PREPROC --> VIOL_CHECK{"Violations<br/>computed?"}
    VIOL_CHECK -->|No| COMPUTE_VIOL["find_structural_violations()"]
    VIOL_CHECK -->|Yes| RENAME_CHECK
    COMPUTE_VIOL --> RENAME_CHECK
    
    RENAME_CHECK{"Ground truth<br/>renamed?"}
    RENAME_CHECK -->|No| COMPUTE_RENAME["compute_renamed_ground_truth()"]
    RENAME_CHECK -->|Yes| LOSS_FNS
    COMPUTE_RENAME --> LOSS_FNS
    
    LOSS_FNS["Compute individual losses"] --> WEIGHT["Apply config weights"]
    WEIGHT --> SUM["Sum weighted losses"]
    SUM --> SCALE["Scale by sqrt(min(seq_len, crop_len))"]
    SCALE --> OUTPUT["Return total loss + breakdown"]
```

### Usage in Training

The loss is instantiated in `OpenFoldWrapper` ([train_openfold.py:45-60]()):

```python
self.loss = AlphaFoldLoss(config.loss)
```

During training ([train_openfold.py:115-117]()):

```python
loss, loss_breakdown = self.loss(
    outputs, batch, _return_breakdown=True
)
```

**Sources:** [openfold/utils/loss.py:1685-1793](), [train_openfold.py:45-60](), [train_openfold.py:115-117]()

---

## FAPE Loss (Frame Aligned Point Error)

FAPE is the primary geometric loss that measures structural accuracy by comparing predicted and ground truth atomic positions in local reference frames. This makes the loss invariant to global rotations and translations.

### Components

FAPE loss has two main components:
1. **Backbone FAPE**: Measures accuracy of backbone rigid transformations
2. **Sidechain FAPE**: Measures accuracy of all-atom sidechain positions

### Backbone FAPE

The `backbone_loss` function ([openfold/utils/loss.py:169-232]()) computes FAPE for backbone frames:

```mermaid
graph TB
    TRAJ["Trajectory of backbone frames<br/>traj: [*, N_recycle, N_res, 7 or 4x4]"]
    GT_FRAMES["Ground truth backbone frames<br/>backbone_rigid_tensor: [*, N_res, 4, 4]"]
    
    TRAJ --> CONVERT["Convert to Rigid objects<br/>from_tensor_7() or from_tensor_4x4()"]
    GT_FRAMES --> CONVERT_GT["Convert to Rigid objects<br/>from_tensor_4x4()"]
    
    CONVERT --> TRANSFORM["Transform points to local frames<br/>invert()[..., None].apply(positions)"]
    CONVERT_GT --> TRANSFORM_GT["Transform points to local frames<br/>invert()[..., None].apply(positions)"]
    
    TRANSFORM --> DISTANCE["Compute L2 distances<br/>sqrt(sum((pred - gt)^2))"]
    TRANSFORM_GT --> DISTANCE
    
    DISTANCE --> CLAMP{"Clamping<br/>enabled?"}
    CLAMP -->|Yes| CLAMP_DIST["clamp(dist, max=clamp_distance)"]
    CLAMP -->|No| NORM
    CLAMP_DIST --> NORM
    
    NORM["Normalize by length_scale"] --> MASK["Apply masks<br/>frames_mask, positions_mask"]
    MASK --> MULTIMER{"Multimer<br/>mode?"}
    
    MULTIMER -->|Yes| SEPARATE["Compute intra-chain and<br/>interface losses separately"]
    MULTIMER -->|No| MEAN["Compute mean FAPE"]
    SEPARATE --> WEIGHT_MULTI["Apply intra_chain_backbone.weight<br/>and interface_backbone.weight"]
    WEIGHT_MULTI --> FINAL_FAPE
    MEAN --> FINAL_FAPE["Final backbone FAPE loss"]
```

**Key parameters** (from config):
- `length_scale`: Normalizes distances (typically 10.0 Angstroms)
- `clamp_distance`: Maximum distance error to consider (typically 10.0)
- `use_clamped_fape`: Whether to use clamping (can be toggled during training)

For multimer mode ([openfold/utils/loss.py:293-306]()), the loss separates intra-chain and interface regions:
- **Intra-chain**: Atoms within the same chain (same `asym_id`)
- **Interface**: Atoms across different chains

**Sources:** [openfold/utils/loss.py:82-166](), [openfold/utils/loss.py:169-232](), [openfold/utils/loss.py:286-325]()

### Sidechain FAPE

The `sidechain_loss` function ([openfold/utils/loss.py:235-283]()) computes FAPE for all 8 rigid groups per residue (backbone + 7 sidechain torsion frames):

1. Handles alternative ground truth for symmetric sidechains (e.g., Phe, Tyr)
2. Uses the final predicted sidechain frames from `sm["sidechain_frames"][-1]`
3. Compares all atom14 positions in their local rigid group frames

**Sources:** [openfold/utils/loss.py:235-283]()

### FAPE Algorithm

The core FAPE computation ([openfold/utils/loss.py:82-166]()):

$$\text{FAPE} = \frac{1}{N_{\text{frames}} \cdot N_{\text{pts}}} \sum_{f,p} \text{mask}_{f,p} \cdot \frac{\| T_f^{-1}(\mathbf{x}_p^{\text{pred}}) - T_f^{-1}(\mathbf{x}_p^{\text{gt}}) \|}{d_{\text{scale}}}$$

Where:
- $T_f^{-1}$ inverts frame $f$ and transforms points to its local coordinates
- $\mathbf{x}_p$ are 3D positions of atoms
- $d_{\text{scale}}$ is the length scale parameter
- Optional L1 clamping at `l1_clamp_distance`

**Sources:** [openfold/utils/loss.py:82-166]()

---

## LDDT Loss (pLDDT Prediction)

The LDDT loss trains the model to predict per-residue local distance difference test (lDDT) scores, which serve as confidence estimates.

### Computation

```mermaid
graph TB
    PRED_POS["Predicted CA positions<br/>all_atom_pred_pos[..., CA, :]"]
    GT_POS["Ground truth CA positions<br/>all_atom_positions[..., CA, :]"]
    LOGITS["pLDDT logits<br/>lddt_logits: [*, N_res, 50]"]
    
    PRED_POS --> DIST_PRED["Compute pairwise distances<br/>dmat_pred: [*, N_res, N_res]"]
    GT_POS --> DIST_GT["Compute pairwise distances<br/>dmat_true: [*, N_res, N_res]"]
    
    DIST_PRED --> DIFF["Distance differences<br/>|dmat_pred - dmat_true|"]
    DIST_GT --> DIFF
    
    DIFF --> SCORE["Count differences < thresholds<br/>0.5, 1.0, 2.0, 4.0 Angstroms"]
    SCORE --> LDDT_VAL["Average to get lDDT<br/>score: [*, N_res]"]
    
    LDDT_VAL --> DETACH["Detach from graph<br/>(target, not differentiable)"]
    DETACH --> BIN["Convert to bin indices<br/>bin_index = floor(score * 50)"]
    BIN --> ONEHOT["One-hot encode<br/>lddt_ca_one_hot: [*, N_res, 50]"]
    
    LOGITS --> CE["Softmax cross-entropy<br/>with one-hot target"]
    ONEHOT --> CE
    
    CE --> MASK_LOSS["Mask by all_atom_mask<br/>and resolution filter"]
    MASK_LOSS --> FINAL["Mean LDDT loss"]
```

### Key Features

1. **Local metric**: Only considers atom pairs within 15 Angstroms cutoff
2. **Multi-threshold scoring**: Uses 4 distance thresholds (0.5, 1.0, 2.0, 4.0 Å)
3. **Binned prediction**: Model predicts distribution over 50 bins from 0-100
4. **Resolution filtering**: Only applied to structures with resolution between 0.1-3.0 Å

**Implementation:** [openfold/utils/loss.py:428-481]() (`lddt`), [openfold/utils/loss.py:484-504]() (`lddt_ca`), [openfold/utils/loss.py:507-559]() (`lddt_loss`)

**Sources:** [openfold/utils/loss.py:428-481](), [openfold/utils/loss.py:484-504](), [openfold/utils/loss.py:507-559]()

---

## Distogram Loss

The distogram loss trains the model to predict the distribution of C-beta (or C-alpha for glycine) pairwise distances.

### Implementation

The `distogram_loss` function ([openfold/utils/loss.py:562-607]()):

1. **Compute pairwise distances** between pseudo-beta atoms:
   ```
   dists = sum((pseudo_beta[..., None, :] - pseudo_beta[..., None, :, :])^2)
   ```

2. **Bin distances**: 64 bins with boundaries from 2.3125² to 21.6875² Ų

3. **Cross-entropy loss**: Between predicted logits and true distance bins

4. **Masking**: Applied via `pseudo_beta_mask` to exclude missing residues

The distogram provides a differentiable distance restraint that helps the model learn distance geometry principles.

**Sources:** [openfold/utils/loss.py:562-607]()

---

## TM Score Loss

For multimer and some training stages, the model predicts the expected TM-score (Template Modeling score) between predicted and true structures.

### Computation Flow

```mermaid
graph TB
    PRED_AFF["Predicted backbone affines<br/>final_affine_tensor"]
    GT_AFF["Ground truth affines<br/>backbone_rigid_tensor"]
    LOGITS["TM logits<br/>tm_logits: [*, N_res, N_res, 64]"]
    
    PRED_AFF --> INVERT_PRED["Invert & apply to translations<br/>get local frame coordinates"]
    GT_AFF --> INVERT_GT["Invert & apply to translations<br/>get local frame coordinates"]
    
    INVERT_PRED --> SQ_DIFF["Squared distances<br/>sum((pred - gt)^2)"]
    INVERT_GT --> SQ_DIFF
    
    SQ_DIFF --> DETACH["Detach (target)"]
    DETACH --> BIN_TM["Bin squared distances<br/>64 bins from 0 to 31^2"]
    BIN_TM --> ONEHOT_TM["One-hot encode true bins"]
    
    LOGITS --> CE_TM["Softmax cross-entropy"]
    ONEHOT_TM --> CE_TM
    
    CE_TM --> MASK_TM["Mask by backbone_rigid_mask<br/>and resolution filter"]
    MASK_TM --> FINAL_TM["Mean TM loss"]
```

### TM Score Computation

The model can also compute predicted TM-scores from logits using `compute_tm` ([openfold/utils/loss.py:670-718]()):

$$\text{TM} = \frac{1}{N} \sum_{i,j} \frac{1}{1 + (d_{ij} / d_0)^2}$$

Where:
- $d_0 = 1.24 \sqrt[3]{N - 15} - 1.8$ (normalization constant)
- Supports both intra-chain and interface TM-scores (controlled by `asym_id`)

**Sources:** [openfold/utils/loss.py:670-718](), [openfold/utils/loss.py:721-779]()

---

## Supervised Chi Loss (Torsion Angles)

The supervised chi loss trains the model to predict accurate sidechain torsion angles.

### Implementation

The `supervised_chi_loss` function ([openfold/utils/loss.py:328-411]()):

1. **Extract chi angles**: From `sm["angles"]` (predicted) and `chi_angles_sin_cos` (ground truth)
   - Only considers chi angles (indices 3-7), skipping backbone angles

2. **Handle periodicity**: Some chi angles are π-periodic (e.g., Phe, Tyr)
   - Compares both the angle and angle+π, taking the minimum error

3. **Angle normalization**: Penalizes unnormalized angle predictions
   - `angle_norm_loss = |norm(angle_vector) - 1.0|`

4. **Masking**: Uses `chi_mask` to only supervise chi angles that exist for each residue type

**Loss formulation:**
```
loss = chi_weight * chi_loss + angle_norm_weight * norm_loss
```

Typical weights: `chi_weight=0.5`, `angle_norm_weight=0.02`

**Sources:** [openfold/utils/loss.py:328-411]()

---

## Violation Losses

Violation losses penalize physically implausible structures by enforcing geometric constraints.

### Overview

```mermaid
graph TB
    PRED_POS["Predicted atom14 positions<br/>sm['positions'][-1]"]
    BATCH["Batch data<br/>residue_index, aatype,<br/>atom14_atom_exists"]
    
    PRED_POS --> BOND["between_residue_bond_loss<br/>C-N bond length & angles"]
    PRED_POS --> CLASH_INTER["between_residue_clash_loss<br/>Inter-residue clashes"]
    PRED_POS --> CLASH_INTRA["within_residue_violations<br/>Intra-residue clashes & bonds"]
    
    BATCH --> BOND
    BATCH --> CLASH_INTER
    BATCH --> CLASH_INTRA
    
    BOND --> BONDS_LOSS["bonds_c_n_loss_mean"]
    BOND --> ANGLES_LOSS["angles_ca_c_n_loss_mean<br/>angles_c_n_ca_loss_mean"]
    CLASH_INTER --> INTER_CLASH["clashes_mean_loss"]
    CLASH_INTRA --> INTRA_CLASH["per_atom_loss_sum"]
    
    BONDS_LOSS --> AGGREGATE["violation_loss aggregator"]
    ANGLES_LOSS --> AGGREGATE
    INTER_CLASH --> AGGREGATE
    INTRA_CLASH --> AGGREGATE
    
    AGGREGATE --> FINAL_VIOL["Total violation loss"]
```

### Between-Residue Bond Loss

The `between_residue_bond_loss` function ([openfold/utils/loss.py:782-939]()) enforces peptide bond geometry:

**Constraints checked:**
1. **C-N bond length**: ~1.329 Å (1.341 Å for proline)
2. **CA-C-N angle**: Bond angle around C atom
3. **C-N-CA angle**: Bond angle around N atom

**Tolerance:** Uses `tolerance_factor_soft` and `tolerance_factor_hard` (both typically 12.0)
- Soft: Applied with ReLU to compute loss
- Hard: Used to flag violations

**Sources:** [openfold/utils/loss.py:782-939]()

### Between-Residue Clash Loss

The `between_residue_clash_loss` function ([openfold/utils/loss.py:942-1093]()) penalizes steric clashes:

1. **Van der Waals radii**: Uses element-specific radii from `residue_constants`
2. **Distance check**: Flags clashes when atoms closer than sum of radii minus tolerance
3. **Exclusions**:
   - Consecutive C-N bonds (not clashes)
   - Disulfide bonds (CYS SG-SG)
   - Same residue atoms (handled separately)
4. **Multimer support**: Uses `asym_id` to correctly identify consecutive residues across chains

**Sources:** [openfold/utils/loss.py:942-1093]()

### Within-Residue Violations

The `within_residue_violations` function ([openfold/utils/loss.py:1096-1183]()) checks intra-residue geometry:

1. **Distance bounds**: Uses `residue_constants.make_atom14_dists_bounds()`
   - Lower and upper bounds for all atom pairs within each residue
2. **Violations**: Penalizes distances outside bounds
3. **Per-atom aggregation**: Sums violations for each atom

**Sources:** [openfold/utils/loss.py:1096-1183]()

### Violation Loss Aggregation

The `violation_loss` function ([openfold/utils/loss.py:1432-1460]()) combines all violation components:

```python
loss = (
    bonds_c_n_loss_mean +
    angles_ca_c_n_loss_mean +
    angles_c_n_ca_loss_mean +
    l_clash  # Combined inter- and intra-residue clashes
)
```

With optional averaging over number of clashes if `average_clashes=True`.

**Sources:** [openfold/utils/loss.py:1432-1460]()

---

## Masked MSA Loss

The masked MSA loss implements BERT-style pretraining on MSA sequences.

### Implementation

The `masked_msa_loss` function ([openfold/utils/loss.py:1595-1625]()):

1. **Input**: 
   - Predicted residue distributions: `logits` [*, N_seq, N_res, 23]
   - True MSA: `true_msa` [*, N_seq, N_res]
   - Mask indicating masked positions: `bert_mask` [*, N_seq, N_res]

2. **Loss computation**:
   - Softmax cross-entropy between predicted and true amino acids
   - Only at masked positions (where `bert_mask=1`)

3. **Purpose**: Helps the model learn evolutionary patterns from MSAs

**Sources:** [openfold/utils/loss.py:1595-1625]()

---

## Experimentally Resolved Loss

The `experimentally_resolved_loss` function ([openfold/utils/loss.py:1571-1592]()) trains the model to predict which atoms are experimentally resolved (present in the crystal structure).

**Implementation:**
1. Binary classification per atom (resolved vs. unresolved)
2. Uses sigmoid cross-entropy loss
3. Filtered by resolution range (typically 0.1-3.0 Å)

This helps the model learn to predict confidence in individual atom positions.

**Sources:** [openfold/utils/loss.py:1571-1592]()

---

## Chain Center of Mass Loss (Multimer)

For multimer predictions, the `chain_center_of_mass_loss` function ([openfold/utils/loss.py:1628-1682]()) enforces consistency of inter-chain distances.

### Algorithm

```mermaid
graph TB
    PRED_CA["Predicted CA positions"]
    GT_CA["Ground truth CA positions"]
    ASYM["Chain IDs (asym_id)"]
    
    PRED_CA --> COM_PRED["Compute per-chain<br/>center of mass"]
    GT_CA --> COM_GT["Compute per-chain<br/>center of mass"]
    ASYM --> COM_PRED
    ASYM --> COM_GT
    
    COM_PRED --> DIST_PRED["Pairwise chain distances<br/>euclidean_distance()"]
    COM_GT --> DIST_GT["Pairwise chain distances<br/>euclidean_distance()"]
    
    DIST_PRED --> DIFF["Distance differences<br/>(pred - gt - clamp_distance)"]
    DIST_GT --> DIFF
    
    DIFF --> CLAMP["Clamp at max=0<br/>Only penalize distances too short"]
    CLAMP --> SQUARE["Square the error"]
    SQUARE --> WEIGHT_COM["Multiply by weight (0.05)"]
    WEIGHT_COM --> FINAL_COM["Chain COM loss"]
```

**Purpose:** Prevents chains from drifting apart or collapsing together during multimer training.

**Default parameters:**
- `clamp_distance`: -4.0 (negative = allow some compression)
- `weight`: 0.05

**Sources:** [openfold/utils/loss.py:1628-1682]()

---

## Loss Configuration and Weights

Each loss component has configurable parameters set in `model_config` (see [Configuration System](#5.1)). 

### Typical Loss Weights

| Loss Component | Config Key | Typical Weight |
|----------------|-----------|----------------|
| FAPE (backbone) | `fape.backbone.weight` | 0.5 |
| FAPE (sidechain) | `fape.sidechain.weight` | 0.5 |
| LDDT | `plddt_loss.weight` | 0.01 |
| Distogram | `distogram.weight` | 0.3 |
| TM score | `tm.weight` | 0.0 (multimer: varies) |
| Supervised chi | `supervised_chi.weight` | 1.0 |
| Violations | `violation.weight` | 0.0 (enabled later in training) |
| Masked MSA | `masked_msa.weight` | 2.0 |
| Experimentally resolved | `experimentally_resolved.weight` | 0.01 |
| Chain COM | `chain_center_of_mass.weight` | 0.05 |

### Loss Scaling

The final loss is scaled by $\sqrt{\min(L_{\text{seq}}, L_{\text{crop}})}$ where:
- $L_{\text{seq}}$ is the sequence length
- $L_{\text{crop}}$ is the crop size

This normalization ([openfold/utils/loss.py:1776-1778]()):
```python
seq_len = torch.mean(batch["seq_length"].float())
crop_len = batch["aatype"].shape[-1]
cum_loss = cum_loss * torch.sqrt(min(seq_len, crop_len))
```

Ensures that losses for different protein sizes are comparable.

**Sources:** [openfold/utils/loss.py:1712-1780]()

---

## Auxiliary Functions

### Ground Truth Renaming

The `compute_renamed_ground_truth` function ([openfold/utils/loss.py:1463-1568]()) handles symmetric sidechains:

**Problem:** Some amino acids have symmetric atoms (e.g., Phe ring can flip)
**Solution:** Compare predicted positions to both original and "flipped" ground truth, use the better match

**Process:**
1. Compute LDDT-like score for original and alternative ground truth
2. Choose alternative if it gives better score
3. Return renamed ground truth for use in all losses

This prevents the model from being penalized for predicting valid symmetric configurations.

**Sources:** [openfold/utils/loss.py:1463-1568]()

### Structural Violations Detection

The `find_structural_violations` function ([openfold/utils/loss.py:1186-1316]()) computes all violation metrics:

**Outputs:**
```python
{
    "between_residues": {
        "bonds_c_n_loss_mean": ...,
        "angles_ca_c_n_loss_mean": ...,
        "clashes_mean_loss": ...,
        ...
    },
    "within_residues": {
        "per_atom_loss_sum": ...,
        ...
    },
    "total_per_residue_violations_mask": ...
}
```

Used both for computing violation loss and for masking LDDT predictions.

**Sources:** [openfold/utils/loss.py:1186-1316]()

---

## Loss in Training Loop

### Integration with OpenFoldWrapper

The loss is used in the training step ([train_openfold.py:97-122]()):

```mermaid
graph LR
    BATCH["Input batch"] --> FORWARD["model(batch)"]
    FORWARD --> OUTPUTS["Model outputs"]
    
    OUTPUTS --> MULTIMER{"Multimer<br/>mode?"}
    MULTIMER -->|Yes| PERMUTE["multi_chain_permutation_align<br/>Find best chain ordering"]
    MULTIMER -->|No| COMPUTE_LOSS
    PERMUTE --> COMPUTE_LOSS
    
    COMPUTE_LOSS["loss(outputs, batch)"] --> BREAKDOWN["Loss breakdown dict"]
    BREAKDOWN --> LOG["Log to wandb/tensorboard"]
    BREAKDOWN --> BACKWARD["loss.backward()"]
```

### EMA and Validation

During validation ([train_openfold.py:127-156]()):
1. EMA weights are loaded for inference
2. Loss is computed with `use_clamped_fape=0.0` (unclamped FAPE only)
3. Additional metrics computed: `lddt_ca`, `drmsd_ca`, `gdt_ts`, `gdt_ha`
4. Original weights restored after validation

**Sources:** [train_openfold.py:97-122](), [train_openfold.py:127-156]()

---

## Summary Table

| Loss | Purpose | Key Parameters | Output Shape |
|------|---------|----------------|--------------|
| **FAPE** | Geometric accuracy of frames & atoms | `length_scale`, `clamp_distance` | Scalar |
| **LDDT** | Train confidence prediction | `cutoff=15.0`, `no_bins=50` | Scalar |
| **Distogram** | Distance distribution | `min_bin`, `max_bin`, `no_bins=64` | Scalar |
| **TM Score** | Predicted TM-score | `max_bin=31`, `no_bins=64` | Scalar |
| **Supervised Chi** | Torsion angle accuracy | `chi_weight`, `angle_norm_weight` | Scalar |
| **Violations** | Physical plausibility | `tolerance_factor`, `clash_overlap_tolerance` | Scalar |
| **Masked MSA** | MSA representation learning | `num_classes=23` | Scalar |
| **Exp. Resolved** | Atom resolution prediction | `min_resolution`, `max_resolution` | Scalar |
| **Chain COM** | Multimer chain spacing | `clamp_distance=-4.0`, `weight=0.05` | Scalar |

All losses return scalars (averaged over batch) and are combined with configurable weights in `AlphaFoldLoss`.

**Sources:** [openfold/utils/loss.py:1-1793]()

---