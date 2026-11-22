# Metrics and Evaluation

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [models/mpnn/src/mpnn/collate/feature_collator.py](models/mpnn/src/mpnn/collate/feature_collator.py)
- [models/mpnn/src/mpnn/inference.py](models/mpnn/src/mpnn/inference.py)
- [models/mpnn/src/mpnn/metrics/nll.py](models/mpnn/src/mpnn/metrics/nll.py)
- [models/mpnn/src/mpnn/metrics/sequence_recovery.py](models/mpnn/src/mpnn/metrics/sequence_recovery.py)
- [models/mpnn/src/mpnn/model/layers/graph_embeddings.py](models/mpnn/src/mpnn/model/layers/graph_embeddings.py)
- [models/mpnn/src/mpnn/model/layers/message_passing.py](models/mpnn/src/mpnn/model/layers/message_passing.py)
- [models/mpnn/src/mpnn/pipelines/mpnn.py](models/mpnn/src/mpnn/pipelines/mpnn.py)
- [models/mpnn/src/mpnn/samplers/samplers.py](models/mpnn/src/mpnn/samplers/samplers.py)
- [models/mpnn/src/mpnn/train.py](models/mpnn/src/mpnn/train.py)
- [models/rf3/src/rf3/metrics/clashing_chains.py](models/rf3/src/rf3/metrics/clashing_chains.py)
- [models/rf3/src/rf3/metrics/distogram.py](models/rf3/src/rf3/metrics/distogram.py)
- [models/rf3/src/rf3/metrics/lddt.py](models/rf3/src/rf3/metrics/lddt.py)
- [models/rf3/src/rf3/metrics/metadata.py](models/rf3/src/rf3/metrics/metadata.py)
- [models/rf3/src/rf3/metrics/predicted_error.py](models/rf3/src/rf3/metrics/predicted_error.py)
- [models/rf3/src/rf3/metrics/rasa.py](models/rf3/src/rf3/metrics/rasa.py)
- [models/rf3/src/rf3/trainers/rf3.py](models/rf3/src/rf3/trainers/rf3.py)
- [models/rf3/src/rf3/utils/predict_and_score.py](models/rf3/src/rf3/utils/predict_and_score.py)
- [models/rfd3/src/rfd3/metrics/hbonds_hbplus_metrics.py](models/rfd3/src/rfd3/metrics/hbonds_hbplus_metrics.py)

</details>



The Foundry system provides model-specific metrics for assessing prediction quality, validating designs, and ranking outputs. Each model (RFD3, RF3, MPNN) implements metrics tailored to its task, unified through the `MetricManager` infrastructure for training and inference.

---

## Metrics Overview

```mermaid
graph TB
    subgraph "RFD3 Metrics"
        rfd3_hbond["HbondMetrics<br/>Hydrogen bond validation"]
    end
    
    subgraph "RF3 Metrics"
        rf3_plddt["pLDDT<br/>Per-atom confidence"]
        rf3_ptm["pTM/ipTM<br/>TM-score prediction"]
        rf3_pae["PAE/PDE<br/>Error distances"]
        rf3_clash["CountClashingChains<br/>Steric clash detection"]
        rf3_lddt["calc_lddt<br/>Local distance difference test"]
        rf3_rasa["UnresolvedRegionRASA<br/>Solvent accessibility"]
    end
    
    subgraph "MPNN Metrics"
        mpnn_nll["NLL<br/>Negative Log Likelihood"]
        mpnn_seqrec["SequenceRecovery<br/>Identity to ground truth"]
        mpnn_intrec["InterfaceSequenceRecovery<br/>Ligand interface recovery"]
    end
    
    subgraph "Infrastructure"
        manager["MetricManager<br/>foundry.metrics.metric"]
        fabric["FabricTrainer<br/>Training integration"]
    end
    
    rfd3_hbond --> manager
    rf3_plddt --> manager
    rf3_ptm --> manager
    rf3_pae --> manager
    rf3_clash --> manager
    rf3_lddt --> manager
    rf3_rasa --> manager
    mpnn_nll --> manager
    mpnn_seqrec --> manager
    mpnn_intrec --> manager
    
    manager --> fabric
```

| Model | Metrics | Purpose |
|-------|---------|---------|
| **RFD3** | Hydrogen bonds | Validate conditioning constraints (donors/acceptors) |
| **RF3** | pLDDT, pTM, ipTM, PAE, PDE, LDDT, RASA, clashing chains | Confidence scoring, structural accuracy, and ranking |
| **MPNN** | NLL, Perplexity, Sequence recovery, interface recovery | Sequence design quality and likelihood assessment |

**Sources:** [models/rfd3/src/rfd3/metrics/hbonds_hbplus_metrics.py:109-115](), [models/rf3/src/rf3/metrics/lddt.py:18-40](), [models/rf3/src/rf3/metrics/predicted_error.py:9-40](), [models/mpnn/src/mpnn/metrics/nll.py:12-21]()

---

## RF3 Structural Accuracy and Confidence

RF3 produces metrics for both ground-truth comparison (LDDT) and internal confidence scoring (pLDDT, pTM).

### LDDT: Local Distance Difference Test

The `calc_lddt` function calculates structural accuracy by comparing pairwise distances between predicted and ground-truth structures. It excludes same-token (intra-residue) pairs and uses standard thresholds (0.5Å, 1.0Å, 2.0Å, 4.0Å).

**Title: LDDT Calculation Flow**

```mermaid
graph TB
    subgraph "Input Tensors"
        X_L["X_L [D, L, 3]<br/>Predicted coords"]
        X_gt_L["X_gt_L [D, L, 3]<br/>Ground truth coords"]
        tok_idx["tok_idx [L]<br/>Token indices"]
    end
    
    subgraph "Pair Selection"
        dist_mask["Distance Cutoff<br/>(default 15A)"]
        token_mask["Exclude same-token pairs"]
        valid_pairs["valid_pairs<br/>torch.nonzero()"]
    end
    
    subgraph "Scoring"
        delta["abs(pred_dist - gt_dist)"]
        thresh["Thresholds:<br/>0.5, 1.0, 2.0, 4.0"]
        avg["Average fraction preserved"]
    end
    
    X_L & X_gt_L --> delta
    tok_idx --> token_mask
    dist_mask & token_mask --> valid_pairs
    valid_pairs --> delta
    delta --> thresh
    thresh --> avg
```

**Implementation Details:**
- **Feature Extraction:** `extract_lddt_features_from_atom_arrays` handles the conversion from Biotite `AtomArray` to tensors, ensuring coordinate masks are created from occupancy [models/rf3/src/rf3/metrics/lddt.py:116-170]().
- **Symmetry Resolution:** During training and validation, structural metrics like LDDT are computed after symmetry resolution using `SubunitSymmetryResolution` and `ResidueSymmetryResolution` [models/rf3/src/rf3/trainers/rf3.py:85-88]().

**Sources:** [models/rf3/src/rf3/metrics/lddt.py:18-113](), [models/rf3/src/rf3/metrics/lddt.py:116-170]()

### pTM and ipTM: TM-Score Prediction

**Title: TM-Score Metrics and Interface Masks**

```mermaid
graph TB
    subgraph "Input"
        pae["pae tensor<br/>[D, I, I, n_bins]"]
        asym_id["asym_id<br/>[I] chain IDs"]
        is_ligand["is_ligand<br/>[I] boolean"]
    end
    
    subgraph "Logic"
        norm["Normalization factor<br/>1.24 * (L-15)^(1/3) - 1.8"]
        soft["Softmax over bins"]
        mask_logic["Interface Masks:<br/>protein-protein<br/>protein-ligand<br/>ligand-ligand"]
    end
    
    subgraph "Metric Classes"
        ptm_class["ComputePTM"]
        iptm_class["ComputeIPTM"]
    end
    
    pae --> soft
    asym_id --> mask_logic
    is_ligand --> mask_logic
    soft & norm & mask_logic --> ptm_class
    soft & norm & mask_logic --> iptm_class
```

**Metric Definitions:**
- **ComputePTM:** Estimates structural similarity for the whole complex [models/rf3/src/rf3/metrics/predicted_error.py:43-67]().
- **ComputeIPTM:** Specifically measures interface quality by masking for inter-chain pairs (`asym_id[i] != asym_id[j]`). It further categorizes interfaces into protein-protein, protein-ligand, and ligand-ligand [models/rf3/src/rf3/metrics/predicted_error.py:70-134]().

**Sources:** [models/rf3/src/rf3/metrics/predicted_error.py:9-40](), [models/rf3/src/rf3/metrics/predicted_error.py:70-134]()

---

## RFD3 Hydrogen Bond Statistics

RFD3 validates hydrogen bond conditioning using the HBPLUS tool. The system compares specified donors/acceptors in the input against those formed in the generated structure.

**Key Functions:**
- `simplified_processing_atom_array`: Prepares generated structures by inferring residue types from atom names, essential for `calculate_hbonds` to identify potential donors/acceptors [models/rfd3/src/rfd3/metrics/hbonds_hbplus_metrics.py:19-106]().
- `calculate_hbond_stats`: Aggregates percentages of "correct" donors and acceptors (those that appear in the output structure at the designed positions) [models/rfd3/src/rfd3/metrics/hbonds_hbplus_metrics.py:109-183]().

**Sources:** [models/rfd3/src/rfd3/metrics/hbonds_hbplus_metrics.py:19-106](), [models/rfd3/src/rfd3/metrics/hbonds_hbplus_metrics.py:109-183]()

---

## MPNN Likelihood and Recovery

MPNN models use Negative Log Likelihood (NLL) and Perplexity to assess how well the model "expects" a specific sequence given a structure.

### NLL and Perplexity

The `NLL` metric class computes the average negative log probability at the ground-truth token indices.

```python
# From mpnn/metrics/nll.py:113-125
# S_onehot [B, L, vocab_size]
S_onehot = torch.nn.functional.one_hot(S, num_classes=vocab_size).float()

# nll_per_residue [B, L]
nll_per_residue = -torch.sum(S_onehot * log_probs, dim=-1) * per_residue_mask

# nll_per_example [B]
nll_per_example = nll_per_residue.sum(dim=-1) / total_valid_per_example

# perplexity_per_example [B]
perplexity_per_example = torch.exp(nll_per_example)
```

**Sub-interface Masking:**
LigandMPNN often uses specialized masks to compute NLL specifically at the protein-ligand interface [models/mpnn/src/mpnn/metrics/nll.py:4-7]().

**Sources:** [models/mpnn/src/mpnn/metrics/nll.py:12-42](), [models/mpnn/src/mpnn/metrics/nll.py:76-144]()

---

## Advanced Evaluation Metrics

### Clashing Chains
The `CountClashingChains` metric identifies steric overlaps between polymer chains. A clash is defined by a distance `< 1.1Å`. A pair of chains is considered clashing if they have `> 100` clashing atom pairs or if `> 50%` of the atoms in the larger chain are clashing [models/rf3/src/rf3/metrics/clashing_chains.py:10-68]().

### RASA (Relative Solvent Accessible Surface Area)
`UnresolvedRegionRASA` computes the RASA for regions that were unresolved in the ground truth (occupancy 0.0). This is used to evaluate if the model is correctly placing disordered loops on the surface vs. the core [models/rf3/src/rf3/metrics/rasa.py:9-108]().

### Distogram Comparison
`DistogramComparisons` and `DistogramLoss` evaluate the 2D representation within the model's trunk. The `ComparisonConfig` class allows subsetting these comparisons to specific relationships like "inter-chain" vs "intra-chain" or "atomized" vs "non-atomized" tokens [models/rf3/src/rf3/metrics/distogram.py:19-81](), [models/rf3/src/rf3/metrics/distogram.py:173-188]().

**Sources:** [models/rf3/src/rf3/metrics/clashing_chains.py:30-62](), [models/rf3/src/rf3/metrics/rasa.py:56-81](), [models/rf3/src/rf3/metrics/distogram.py:47-80]()

---

## Metric Integration and Data Flow

Metrics are typically managed by the `MetricManager` and executed within the `FabricTrainer`.

**Title: Metric Execution Flow**

```mermaid
graph LR
    subgraph "Trainer Logic"
        trainer["RF3Trainer<br/>rf3.trainers.rf3"]
        val_step["validation_step()"]
    end
    
    subgraph "Information Assembly"
        net_in["_assemble_network_inputs()"]
        net_out["model forward pass"]
        metric_info["_assemble_metrics_extra_info()"]
    end
    
    subgraph "MetricManager"
        manager["MetricManager<br/>foundry.metrics.metric"]
        compute["manager(network_input, network_output, extra_info)"]
    end
    
    trainer --> val_step
    val_step --> net_in & net_out & metric_info
    net_in & net_out & metric_info --> compute
    compute --> manager
```

**Key Code Paths:**
- **Initialization:** `MetricManager.instantiate_from_hydra` is used in the `RF3Trainer` constructor to build metrics from config [models/rf3/src/rf3/trainers/rf3.py:72-80]().
- **Prediction & Scoring Utility:** `predict_and_score_with_rf3` provides a high-level API to run RF3 on a list of `AtomArray` objects and return both structures and computed metrics [models/rf3/src/rf3/utils/predict_and_score.py:42-165]().

**Sources:** [models/rf3/src/rf3/trainers/rf3.py:72-80](), [models/rf3/src/rf3/utils/predict_and_score.py:111-141]()

---