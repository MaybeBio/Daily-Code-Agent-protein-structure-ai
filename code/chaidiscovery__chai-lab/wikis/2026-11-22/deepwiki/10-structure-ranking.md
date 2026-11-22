# Structure Ranking

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [chai_lab/ranking/clashes.py](chai_lab/ranking/clashes.py)
- [chai_lab/ranking/frames.py](chai_lab/ranking/frames.py)
- [chai_lab/ranking/plddt.py](chai_lab/ranking/plddt.py)
- [chai_lab/ranking/ptm.py](chai_lab/ranking/ptm.py)
- [chai_lab/ranking/rank.py](chai_lab/ranking/rank.py)
- [chai_lab/ranking/utils.py](chai_lab/ranking/utils.py)

</details>



Structure ranking is a critical component of the Chai-1 molecular structure prediction system. It evaluates and scores predicted 3D structures using a combination of confidence metrics (pLDDT, pTM, ipTM) and physical plausibility checks (clash detection). This system allows the pipeline to rank multiple structure candidates and select the highest-quality predictions for the final output.

## Overview

The structure ranking process takes coordinates and confidence logits produced by the model and assigns them quality scores. These scores are then combined into an aggregate score that determines the final ranking of structure candidates.

```mermaid
flowchart TD
    subgraph "Natural Language Space"
    A["Predicted Structures"]
    B["Quality Assessment"]
    C["Physical Validity"]
    D["Final Ranking"]
    end

    subgraph "Code Entity Space"
    A --> E["rank() in rank.py"]
    E --> F["get_scores() in ptm.py"]
    E --> G["get_scores() in plddt.py"]
    E --> H["get_scores() in clashes.py"]
    F & G & H --> I["SampleRanking dataclass"]
    I --> J["aggregate_score"]
    end

    style A fill:none
    style B fill:none
    style C fill:none
    style D fill:none
```

Sources: [chai_lab/ranking/rank.py:38-112](), [chai_lab/ranking/rank.py:115-125]()

## Ranking Process Implementation

The entry point for structure evaluation is the `rank` function in `chai_lab/ranking/rank.py`. It coordinates the execution of specific scoring modules and calculates the final aggregate score.

### Data Flow in `rank()`

The function accepts 3D coordinates, masks, and logits for both LDDT (Local Distance Difference Test) and PAE (Predicted Alignment Error).

```mermaid
flowchart TD
    Input["atom_coords, atom_mask,\nlddt_logits, pae_logits"] --> PTM["ptm.get_scores()"]
    Input --> PLDDT["plddt.get_scores()"]
    Input --> Clashes["clashes.get_scores()"]
    
    PTM --> |"complex_ptm, interface_ptm"| Agg["Aggregate Score Calculation"]
    Clashes --> |"has_inter_chain_clashes"| Agg
    
    Agg --> Output["SampleRanking"]
    PLDDT --> Output
    PTM --> Output
    Clashes --> Output
```

Sources: [chai_lab/ranking/rank.py:38-92](), [chai_lab/ranking/rank.py:106-112]()

### Input Requirements
The `rank` function requires several specific tensors to handle multi-entity complexes:
- `atom_token_index`: Maps atoms back to their parent tokens [chai_lab/ranking/rank.py:41]().
- `token_asym_id`: Identifies which chain (asymmetric unit) a token belongs to [chai_lab/ranking/rank.py:43]().
- `token_entity_type`: Used to distinguish between polymers (Protein, DNA, RNA) and ligands during clash detection [chai_lab/ranking/rank.py:44]().

## Quality Metrics

### pLDDT (Predicted Local Distance Difference Test)
pLDDT measures local confidence for each atom. The score is calculated as the expected value of the `lddt_logits` over the `lddt_bin_centers` [chai_lab/ranking/plddt.py:30-40]().

The `PLDDTScores` dataclass stores:
- `complex_plddt`: Mean pLDDT across all valid atoms [chai_lab/ranking/plddt.py:24]().
- `per_chain_plddt`: Mean pLDDT for each individual chain [chai_lab/ranking/plddt.py:25]().
- `per_atom_plddt`: Raw pLDDT values for every atom [chai_lab/ranking/plddt.py:26]().

Sources: [chai_lab/ranking/plddt.py:17-26](), [chai_lab/ranking/plddt.py:56-81]()

### PTM and iPTM (Predicted TM-score)
These metrics assess global structural accuracy and relative orientation of chains using `pae_logits`.

- **pTM (Predicted TM-score)**: Evaluates the global topology of the complex [chai_lab/ranking/ptm.py:74-87]().
- **ipTM (Interface pTM)**: Measures the quality of interactions between different chains. It is calculated by taking the maximum TM-score over chains while restricting interactions to the interface between a chain and the rest of the complex [chai_lab/ranking/ptm.py:91-115]().

The system also calculates `per_chain_pair_iptm` to evaluate specific interfaces in multi-component assemblies [chai_lab/ranking/ptm.py:119-160]().

Sources: [chai_lab/ranking/ptm.py:18-30](), [chai_lab/ranking/ptm.py:40-70]()

### Clash Detection
Clashes are identified based on a distance threshold (default 1.1 Å) between non-bonded atoms [chai_lab/ranking/clashes.py:34-44]().

The `has_inter_chain_clashes` logic determines if a structure is physically invalid based on:
1. **Absolute count**: If a chain pair has more than `max_clashes` (default 100) [chai_lab/ranking/clashes.py:66]().
2. **Clash ratio**: If clashes exceed `max_clash_ratio` (default 0.5) of the smaller chain's total atoms [chai_lab/ranking/clashes.py:76-83]().
3. **Entity filter**: Only clashes between polymer chains (Protein, RNA, DNA, Hybrid) are considered for the binary `has_inter_chain_clashes` flag [chai_lab/ranking/clashes.py:86-94]().

Sources: [chai_lab/ranking/clashes.py:18-30](), [chai_lab/ranking/clashes.py:48-94](), [chai_lab/ranking/clashes.py:98-163]()

## Aggregate Score Computation

The final ranking is determined by the `aggregate_score`, which combines global confidence, interface confidence, and physical validity.

```python
aggregate_score = (
    0.2 * ptm_scores.complex_ptm
    + 0.8 * ptm_scores.interface_ptm
    - 100 * clash_scores.has_inter_chain_clashes.float()
)
```

This formula prioritizes interface quality (`ipTM`) while applying a heavy penalty to structures with significant inter-chain clashes.

Sources: [chai_lab/ranking/rank.py:95-99]()

## Core Data Structures

The following classes define the data flow within the ranking system:

| Class | Purpose | Key Attributes |
| :--- | :--- | :--- |
| `SampleRanking` | Main container for all ranking results | `aggregate_score`, `ptm_scores`, `clash_scores`, `plddt_scores` |
| `PTMScores` | Global and interface TM-scores | `complex_ptm`, `interface_ptm`, `per_chain_pair_iptm` |
| `PLDDTScores` | Local confidence scores | `complex_plddt`, `per_chain_plddt`, `per_atom_plddt` |
| `ClashScores` | Physical validity metrics | `total_inter_chain_clashes`, `has_inter_chain_clashes`, `chain_chain_clashes` |

Sources: [chai_lab/ranking/rank.py:20-35](), [chai_lab/ranking/ptm.py:18-30](), [chai_lab/ranking/plddt.py:17-26](), [chai_lab/ranking/clashes.py:18-30]()

## Utility Functions

The `chai_lab/ranking/utils.py` module provides shared logic for ranking:
- `get_chain_masks_and_asyms`: Extracts boolean masks for each chain based on asymmetric IDs [chai_lab/ranking/utils.py:15-27]().
- `chain_is_polymer`: Uses `EntityType` to determine if a chain consists of polymer entities [chai_lab/ranking/utils.py:67-86]().
- `expectation`: Computes the expected value over discrete bins (used for pLDDT and PAE) [chai_lab/ranking/utils.py:49-54]().
- `get_interface_mask`: Identifies atoms at the interface between chains based on a distance threshold [chai_lab/ranking/utils.py:31-45]().

Sources: [chai_lab/ranking/utils.py:9-86]()

---