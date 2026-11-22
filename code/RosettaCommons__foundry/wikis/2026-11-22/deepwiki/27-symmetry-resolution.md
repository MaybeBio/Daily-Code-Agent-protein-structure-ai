# Symmetry Resolution

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [models/rf3/configs/inference_engine/base.yaml](models/rf3/configs/inference_engine/base.yaml)
- [models/rf3/configs/inference_engine/rf3.yaml](models/rf3/configs/inference_engine/rf3.yaml)
- [models/rf3/src/rf3/data/extra_xforms.py](models/rf3/src/rf3/data/extra_xforms.py)
- [models/rf3/src/rf3/data/pipelines.py](models/rf3/src/rf3/data/pipelines.py)
- [models/rf3/src/rf3/inference.py](models/rf3/src/rf3/inference.py)
- [models/rf3/src/rf3/inference_engines/rf3.py](models/rf3/src/rf3/inference_engines/rf3.py)
- [models/rf3/src/rf3/symmetry/resolve.py](models/rf3/src/rf3/symmetry/resolve.py)
- [models/rf3/src/rf3/utils/inference.py](models/rf3/src/rf3/utils/inference.py)

</details>



## Purpose and Scope

This document explains how RosettaFold3 resolves residue-level and subunit-level symmetries when comparing predicted structures to ground truth coordinates. Symmetry resolution is necessary because molecules often contain symmetric substructures where multiple atom arrangements are chemically equivalent. Without resolution, RMSD-based metrics and coordinate losses would be incorrectly penalized when the model predicts a valid symmetric arrangement that differs from the ground truth.

For information about RF3's confidence metrics that use these resolved coordinates, see [Confidence Metrics](#5.4). For details about RF3 training where symmetry resolution is applied, see [RF3 Training](#5.8).

Sources: [models/rf3/src/rf3/symmetry/resolve.py:1-20]()

## Overview

Symmetry resolution addresses two types of structural symmetries:

1.  **Residue-level symmetries**: Symmetric atoms within individual residues (e.g., the two oxygen atoms in carboxylate groups of Aspartate, or the symmetric ring carbons in Phenylalanine).
2.  **Subunit-level symmetries**: Symmetric chains or subunits in multimeric complexes (e.g., homodimers where chain A and B are identical and interchangeable).

The `resolve_symmetries()` function in `rf3.symmetry.resolve` updates ground truth coordinates to minimize RMSD with predicted structures by permuting symmetric atoms and subunits. This ensures that validation metrics reflect true structural accuracy rather than arbitrary symmetry choices.

Sources: [models/rf3/src/rf3/symmetry/resolve.py:23-42]()

## Symmetry Resolution Architecture

The resolution process bridges raw structural data to permutation-aware coordinate comparison.

**Symmetry Resolution Flow**

```mermaid
graph TB
    Pred["Predicted Structure<br/>(AtomArray/Stack)"]
    GT["Ground Truth Structure<br/>(AtomArray/Stack)"]
    
    subgraph "Symmetry Data Generation"
        GenData["generate_symmetry_resolution_inputs_from_atom_array()"]
        Atomize["AtomizeByCCDName"]
        TokenID["AddGlobalTokenIdAnnotation"]
        Automorph["FindAutomorphismsWithNetworkX"]
    end
    
    subgraph "Core Resolution Logic"
        apply_sym["apply_symmetry_resolution()"]
        SubunitRes["SubunitSymmetryResolution<br/>(af3_losses.py)"]
        ResidueRes["ResidueSymmetryResolution<br/>(af3_losses.py)"]
    end
    
    GT --> GenData
    GenData --> Atomize
    Atomize --> TokenID
    TokenID --> Automorph
    
    Pred --> apply_sym
    GT --> apply_sym
    Automorph --> apply_sym
    
    apply_sym --> SubunitRes
    SubunitRes --> ResidueRes
    
    ResidueRes --> ResolvedGT["Resolved Ground Truth<br/>(Minimized RMSD coords)"]
```

Sources: [models/rf3/src/rf3/symmetry/resolve.py:23-112](), [models/rf3/src/rf3/symmetry/resolve.py:247-284]()

## Core Function: `resolve_symmetries()`

The main entry point for symmetry resolution accepts predicted and ground truth structures and returns an updated `AtomArrayStack`.

### Function Signature

```python
def resolve_symmetries(
    predicted_atom_array: AtomArray | AtomArrayStack,
    ground_truth_atom_array: AtomArray | AtomArrayStack,
    resolve_residue_symmetries: bool = True,
    resolve_subunit_symmetries: bool = True,
) -> AtomArrayStack:
```

### Preprocessing and Masking

Before resolution, the function aligns coordinate masks and handles missing data:
1.  **NaN Synchronization**: Ground truth coordinates are set to `NaN` where the predicted coordinates are `NaN` [models/rf3/src/rf3/symmetry/resolve.py:47-47]().
2.  **NaN-to-Num**: Predicted coordinates are converted from `NaN` to `0` to prevent resolution failure [models/rf3/src/rf3/symmetry/resolve.py:51-51]().
3.  **Occupancy Masking**: If an `occupancy` annotation exists, it is used to create a `crd_mask` (where `occupancy > 0.0`). Otherwise, it falls back to coordinate validity [models/rf3/src/rf3/symmetry/resolve.py:80-87]().

Sources: [models/rf3/src/rf3/symmetry/resolve.py:43-92]()

## Residue-Level Symmetries

Residue-level symmetries arise from chemically equivalent atoms within a single residue.

### Automorphism Detection

The function `generate_symmetry_resolution_inputs_from_atom_array` uses a transform pipeline to detect internal symmetries:
1.  **`AtomizeByCCDName`**: Breaks residues into constituent atoms based on the Chemical Component Dictionary (CCD) [models/rf3/src/rf3/symmetry/resolve.py:142-142]().
2.  **`FindAutomorphismsWithNetworkX`**: Builds a molecular graph and identifies symmetric atom groups using graph isomorphism algorithms [models/rf3/src/rf3/symmetry/resolve.py:147-147]().

### Resolution Logic

The resolution uses the `ResidueSymmetryResolution` class. It iterates through identified automorphism groups and selects the permutation that minimizes the RMSD between the predicted atoms (`X_pred`) and ground truth atoms (`X_gt`) [models/rf3/src/rf3/symmetry/resolve.py:272-281]().

Sources: [models/rf3/src/rf3/symmetry/resolve.py:115-152](), [models/rf3/src/rf3/symmetry/resolve.py:272-281]()

## Subunit-Level Symmetries

Subunit-level symmetries occur when entire chains or molecular entities are interchangeable.

### Entity and Instance Identification

Resolution relies on specific annotations in the `AtomArray`:
*   **`molecule_entity`**: Identifies the chemical type of the molecule [models/rf3/src/rf3/symmetry/resolve.py:164-164]().
*   **`molecule_iid`**: Instance ID distinguishing copies of the same entity (e.g., in a homodimer, both chains share an entity ID but have unique instance IDs) [models/rf3/src/rf3/symmetry/resolve.py:165-165]().

### Resolution Process

The `SubunitSymmetryResolution` logic permutes equivalent subunits:
1.  It identifies subunits belonging to the same `molecule_entity`.
2.  It tests permutations of these subunits.
3.  The permutation that yields the lowest global RMSD is applied to the ground truth coordinates [models/rf3/src/rf3/symmetry/resolve.py:252-271]().

Sources: [models/rf3/src/rf3/symmetry/resolve.py:157-165](), [models/rf3/src/rf3/symmetry/resolve.py:252-271]()

## Implementation Details

### Data Extraction Pipeline

The `generate_symmetry_resolution_inputs_from_atom_array` function prepares the tensors required for the resolution classes.

**Code Entity Space Mapping**

| Data Requirement | Code Entity / Source | Tensor Shape |
| :--- | :--- | :--- |
| Permutations | `FindAutomorphismsWithNetworkX` | `List[np.ndarray]` |
| Entity IDs | `atom_array.molecule_entity` | `[N_atoms]` |
| Instance IDs | `atom_array.molecule_iid` | `[N_atoms]` |
| Coordinates | `atom_array.coord` | `[N_atoms, 3]` |
| Token Mapping | `atom_array.token_id` | `[N_atoms]` |

Sources: [models/rf3/src/rf3/symmetry/resolve.py:115-211]()

### Coordinate Updating

After the optimal permutations are found for both subunits and residues, the function `apply_symmetry_resolution` returns the reordered ground truth coordinates. These are then copied back into a new `AtomArrayStack` [models/rf3/src/rf3/symmetry/resolve.py:109-110]().

Sources: [models/rf3/src/rf3/symmetry/resolve.py:94-112]()

## Integration in Inference

While symmetry resolution is critical for training losses, it is also utilized in the inference engine to provide accurate ground truth comparisons (e.g., when calculating RMSD for a predicted structure against a known crystal structure).

In `RF3InferenceEngine`, symmetry resolution can be configured via `ground_truth_conformer_selection` parameters [models/rf3/src/rf3/inference.py:49-51]().

Sources: [models/rf3/src/rf3/inference.py:49-51](), [models/rf3/src/rf3/utils/inference.py:61-70]()

## Key Code Entities

| Entity | Location | Purpose |
| :--- | :--- | :--- |
| `resolve_symmetries` | [models/rf3/src/rf3/symmetry/resolve.py:23-112]() | High-level API for coordinate resolution. |
| `generate_symmetry_resolution_inputs_from_atom_array` | [models/rf3/src/rf3/symmetry/resolve.py:115-211]() | Prepares tensors and detects automorphisms. |
| `apply_symmetry_resolution` | [models/rf3/src/rf3/symmetry/resolve.py:214-244]() | Orchestrates subunit and residue resolution calls. |
| `SubunitSymmetryResolution` | [models/rf3/src/rf3/symmetry/resolve.py:252-271]() | Permutes interchangeable chains to minimize RMSD. |
| `ResidueSymmetryResolution` | [models/rf3/src/rf3/symmetry/resolve.py:272-281]() | Permutes symmetric atoms within residues. |

Sources: [models/rf3/src/rf3/symmetry/resolve.py:1-284]()

---