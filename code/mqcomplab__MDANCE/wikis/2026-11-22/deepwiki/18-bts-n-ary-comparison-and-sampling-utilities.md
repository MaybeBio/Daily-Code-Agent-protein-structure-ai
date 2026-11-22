# bts: N-ary Comparison and Sampling Utilities

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/mdance/tools/bts.py](src/mdance/tools/bts.py)

</details>



The `mdance.tools.bts` module provides the foundational mathematical and sampling utilities for the MDANCE framework. It implements $O(N)$ scaling n-ary comparison algorithms, diversity-based sampling strategies, and trajectory alignment wrappers. The core innovation of this module is the use of condensed data representations (column-wise sums and squared sums) to calculate global properties of an ensemble without requiring pairwise $O(N^2)$ comparisons.

## N-ary Comparison and Condensed Representation

MDANCE achieves efficiency by representing an ensemble of $N$ objects through their aggregate statistics. This allows for the calculation of Mean Square Deviation (MSD) and various extended similarity indices in linear time relative to the number of samples.

### Data Representations
*   **Full**: A standard feature array of shape `(n_samples, n_features)` [src/mdance/tools/bts.py:117-119]().
*   **Condensed**: A representation using `c_sum` (column-wise sum) and `sq_sum` (column-wise sum of squares) [src/mdance/tools/bts.py:118-119]().

### Key Functions
*   `mean_sq_dev`: Calculates the normalized MSD for an ensemble using the full matrix [src/mdance/tools/bts.py:14-51]().
*   `msd_condensed`: Calculates the normalized MSD using pre-computed `c_sum` and `sq_sum` [src/mdance/tools/bts.py:54-93]().
*   `extended_comparison`: A universal wrapper that computes either MSD or extended similarity indices (e.g., Jaccard, Sokal-Michener) for an ensemble [src/mdance/tools/bts.py:96-188]().

### Logic Flow: N-ary Comparison
The diagram below illustrates how `extended_comparison` branches based on the metric and data type.

Title: N-ary Comparison Logic Flow
```mermaid
graph TD
    "InputMatrix"["Input Matrix/Tuple"] --> "CheckType"{"Check data_type"}
    "CheckType" -- "full" --> "CalcSums"["Compute c_sum & sq_sum"]
    "CheckType" -- "condensed" --> "ExtractSums"["Extract c_sum & sq_sum"]
    "CalcSums" --> "CheckMetric"{"Check metric"}
    "ExtractSums" --> "CheckMetric"
    "CheckMetric" -- "MSD" --> "msd_condensed"["msd_condensed()"]
    "CheckMetric" -- "Similarity" --> "esim_dict"["esim.gen_sim_dict()"]
    "msd_condensed" --> "ReturnVal"["Return Comparison Value"]
    "esim_dict" --> "ReturnVal"
```
Sources: [src/mdance/tools/bts.py:96-188](), [src/mdance/tools/bts.py:155-187]()

## Core Sampling and Selection Utilities

These utilities are used by clustering algorithms like NANI and eQual to identify representative frames or seeds.

| Function | Purpose | Implementation Detail |
| :--- | :--- | :--- |
| `calculate_comp_sim` | Measures the contribution of each object to the ensemble similarity. | Calculates similarity of the ensemble excluding the $i$-th object [src/mdance/tools/bts.py:190-208](). |
| `calculate_medoid` | Identifies the most "central" object in an ensemble. | Finds the object whose removal results in the highest ensemble similarity [src/mdance/tools/bts.py:230-264](). |
| `calculate_outlier` | Identifies the most "distant" object in an ensemble. | Finds the object whose removal results in the lowest ensemble similarity [src/mdance/tools/bts.py:267-301](). |
| `diversity_selection` | Selects a diverse subset of frames. | Supports `strat_all`, `strat_reduced`, and `comp_sim` methods [src/mdance/tools/bts.py:304-394](). |
| `quota_sampling` | Selects a specific number of frames from clusters. | Uses a quota system to ensure representation across partitions [src/mdance/tools/bts.py:442-494](). |
| `trim_outliers` | Removes a percentage of the most dissimilar frames. | Iteratively removes outliers based on `calculate_outlier` [src/mdance/tools/bts.py:497-542](). |

Sources: [src/mdance/tools/bts.py:190-542]()

## Trajectory Alignment and Processing

The `bts` module includes wrappers for structural alignment, essential for RMSD-based clustering of Molecular Dynamics trajectories.

### Alignment Methods
*   **`align_traj`**: A wrapper for `shapeGMMTorch`, which performs global alignment of a trajectory represented as a numpy array [src/mdance/tools/bts.py:545-584]().
*   **`equil_align`**: A wrapper for `cpptraj` (AmberTools). It generates a `cpptraj` script to perform RMSD alignment against a reference frame and executes it via subprocess [src/mdance/tools/bts.py:587-654]().

### Refinement
*   **`refine_dis_matrix`**: Takes a distance matrix and replaces specific indices (e.g., diagonal or known values) to ensure consistency [src/mdance/tools/bts.py:657-695]().

## Code Entity Mapping

The following diagram maps the high-level sampling concepts to the specific function implementations within `mdance.tools.bts`.

Title: Sampling and Selection Entity Map
```mermaid
graph LR
    subgraph "Sampling Strategies"
        "Diversity"["Diversity Selection"]
        "Quota"["Quota Sampling"]
        "OutlierRemoval"["Outlier Trimming"]
    end

    subgraph "Code Entities (mdance.tools.bts)"
        "diversity_selection"["diversity_selection()"]
        "quota_sampling"["quota_sampling()"]
        "trim_outliers"["trim_outliers()"]
        "calculate_comp_sim"["calculate_comp_sim()"]
        "calculate_outlier"["calculate_outlier()"]
    end

    "Diversity" --> "diversity_selection"
    "Quota" --> "quota_sampling"
    "OutlierRemoval" --> "trim_outliers"
    "diversity_selection" -- "uses" --> "calculate_comp_sim"
    "trim_outliers" -- "uses" --> "calculate_outlier"
```
Sources: [src/mdance/tools/bts.py:304-542]()

## Mathematical Context: MSD Calculation

The $O(N)$ MSD implementation is based on the following identity for $N$ vectors:
$$MSD = \frac{1}{N^2} \sum_{i=1}^N \sum_{j=1}^N |x_i - x_j|^2 = \frac{2}{N^2} \left( N \sum_{i=1}^N |x_i|^2 - \left| \sum_{i=1}^N x_i \right|^2 \right)$$

In the code, this is implemented as:
`msd = np.sum(2 * (N * sq_sum - c_sum ** 2)) / (N ** 2)` [src/mdance/tools/bts.py:49]() and [src/mdance/tools/bts.py:91]().

Sources: [src/mdance/tools/bts.py:43-51](), [src/mdance/tools/bts.py:89-93]()

---