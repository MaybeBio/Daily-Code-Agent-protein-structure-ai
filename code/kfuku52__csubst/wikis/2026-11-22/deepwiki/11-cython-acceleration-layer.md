# Cython Acceleration Layer

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [csubst/combination_cy.pyx](csubst/combination_cy.pyx)
- [csubst/omega_cy.pyx](csubst/omega_cy.pyx)
- [csubst/parser_iqtree_cy.pyx](csubst/parser_iqtree_cy.pyx)
- [csubst/recoding_cy.pyx](csubst/recoding_cy.pyx)
- [csubst/substitution_cy.pyx](csubst/substitution_cy.pyx)
- [csubst/substitution_sparse.py](csubst/substitution_sparse.py)
- [csubst/substitution_sparse_cy.pyx](csubst/substitution_sparse_cy.pyx)
- [reports/issue88/nonsyn_recoding_pca_with_none.png](reports/issue88/nonsyn_recoding_pca_with_none.png)

</details>



## Purpose and Scope
This page details the Cython acceleration layer in `csubst`, which implements performance-critical inner loops for substitution tensor construction, combinatorial branch evaluation, expectation projections, tree dependency bitset filtering, amino acid recoding hill-climbing, and sequence parsing. When compiled extensions are unavailable or bypassed via environment flags, `csubst` falls back to pure-Python/NumPy implementations.

---

## 1. Extension Module Inventory and Fallback Mechanism

`csubst` defines six optional Cython extension modules (`.pyx`) to offload heavy numerical and combinatorial routines from pure Python:
1. `substitution_cy`: Accelerates combinatorial substitution tensor reductions (e.g., arity-2 fast paths) [csubst/substitution_cy.pyx:1-389]().
2. `substitution_sparse_cy`: Builds packed Compressed Sparse Row (CSR) matrices for dense/sparse substitution tensors [csubst/substitution_sparse_cy.pyx:1-931]().
3. `omega_cy`: Computes state expectation projections, sparse projection rows, and null-model permutation tests [csubst/omega_cy.pyx:1-440]().
4. `combination_cy`: Handles independent branch combination generation and dependency bitset marking [csubst/combination_cy.pyx:1-757]().
5. `recoding_cy`: Optimizes nonsynonymous amino acid recoding bins via simulated binning and chi-square/conductance hill-climbing [csubst/recoding_cy.pyx:1-458]().
6. `parser_iqtree_cy`: Fast unambiguous codon sequence parsing for leaf state matrices [csubst/parser_iqtree_cy.pyx:1-60]().

Modules are loaded dynamically using `load_optional_extension` from `csubst/_extensions.py`, allowing graceful fallback to pure-Python routines if compilation fails or if `CSUBST_SKIP_EXTENSIONS` is active [csubst/substitution_sparse.py:5-7]().

```mermaid
graph TD
    subgraph "Python Interface Space"
        A["csubst/_extensions.py"] --> B["csubst/substitution_sparse.py"]
        A --> C["csubst/substitution_sparse_cy.pyx"]
        A --> D["csubst/substitution_cy.pyx"]
        A --> E["csubst/omega_cy.pyx"]
        A --> F["csubst/combination_cy.pyx"]
        A --> G["csubst/recoding_cy.pyx"]
        A --> H["csubst/parser_iqtree_cy.pyx"]
    end
    subgraph "Execution Strategy"
        B -->| "Compiled present" | C
        B -->| "Fallback / Missing" | I["Pure NumPy Fallback"]
    end
    classDef default fill:#fff,stroke:#333,stroke-width:1px;
```
*Sources: [csubst/_extensions.py](), [csubst/substitution_sparse.py:5-7](), [csubst/substitution_sparse_cy.pyx:1-931]()*

---

## 2. Substitution Tensors and Packed CSR Construction

The sparse substitution subsystem avoids per-event dictionary overhead by packing all substitution events into a single branch $\times$ (`event_id` $\times$ `num_site`) CSR matrix inside `SparseSubstitutionTensor` [csubst/substitution_sparse.py:31-75](). 

Cython accelerates this via two-pass algorithms in `substitution_sparse_cy.pyx`:
* `build_packed_sub_tensor_asis_double`: Computes non-synonymous/all substitution event CSR arrays directly from parent and child state tensors [csubst/substitution_sparse_cy.pyx:14-77]().
* `build_packed_sub_tensor_syn_double`: Handles synonymous state grouping maps (`state_indices`) to populate CSR data, indices, and indptr arrays [csubst/substitution_sparse_cy.pyx:82-162]().

```mermaid
graph TD
    subgraph "Data Flow"
        T1["state_tensor (child)"] --> K["substitution_sparse_cy.pyx"]
        T2["state_tensor_anc (parent)"] --> K
        P["branch_pairs"] --> K
        K -->| "Pass 1: Count NNZ per branch" | C1["row_counts"]
        C1 -->| "Build indptr" | IP["indptr"]
        K -->| "Pass 2: Populate values" | D["data, indices, indptr"]
        D --> M["SparseSubstitutionTensor"]
    end
    classDef default fill:#fff,stroke:#333,stroke-width:1px;
```
*Sources: [csubst/substitution_sparse.py:31-75](), [csubst/substitution_sparse_cy.pyx:14-162]()*

---

## 3. Combinatorial Substitution Evaluation

For arity-$K$ searches, evaluating substitution intersections across branches utilizes optimized routines in `substitution_cy.pyx`:
* `calc_combinatorial_sub_double_arity2`: An optimized fast-path for arity-2 branch combinations that bypasses generic multidimensional tensor reductions by unrolling loops over sites, substitution groups, and derived states [csubst/substitution_cy.pyx:42-124]().
* `calc_combinatorial_sub_by_site_double_arity2`: Computes per-site breakdown statistics for arity-2 combinations [csubst/substitution_cy.pyx:129-181]().
* `calc_combinatorial_sub_float32`: Handles arbitrary arity using vectorized NumPy/tensor operations with float32 precision [csubst/substitution_cy.pyx:11-37]().

*Sources: [csubst/substitution_cy.pyx:11-181]()*

---

## 4. Expectation Projections and Permutation Testing

`omega_cy.pyx` accelerates ancestral state transition projections and null-model permutation generation [csubst/omega_cy.pyx:1-440]():
* `project_expected_state_block_double`: Multiplies parent state posterior blocks by transition probability matrices and normalizes row sums [csubst/omega_cy.pyx:43-80]().
* `build_expected_projection_rows_double`: Constructs feature-major sparse projection rows (`any2any`, `spe2any`, `any2spe`, `spe2spe`) without allocating large dense site-by-feature intermediates [csubst/omega_cy.pyx:85-165]().
* `get_permutations`: Generates randomized site-permutation bitsets across multiple iterations for null expectation modeling [csubst/omega_cy.pyx:9-38]().

*Sources: [csubst/omega_cy.pyx:9-165]()*

---

## 5. Branch Combination Generation and Dependency Filtering

`combination_cy.pyx` implements bitset-based filtering and combination generation to prevent redundant or mutually dependent branch combinations [csubst/combination_cy.pyx:1-757]():
* `mark_dependent_combinations_bitset_int64`: Checks pairs within row combinations against a dependency bitset matrix [csubst/combination_cy.pyx:9-42]().
* `generate_independent_combinations_int64`: Recursively generates independent branch combinations of given arity using pruned backtracking [csubst/combination_cy.pyx:158-188]().

*Sources: [csubst/combination_cy.pyx:9-42](), [csubst/combination_cy.pyx:158-188]()*

---

## 6. Nonsynonymous Recoding Optimization

`recoding_cy.pyx` supports automated amino acid grouping strategies [csubst/recoding_cy.pyx:1-458]():
* `random_bin_assignments_int64`: Generates random hierarchical bin assignments for items [csubst/recoding_cy.pyx:10-70]().
* `hill_climb_bins_chisq_double` / `search_initial_bins_chunk_chisq_double`: Optimizes recoding bins by minimizing chi-square divergence criteria through iterative local moves [csubst/recoding_cy.pyx:76-194]().

*Sources: [csubst/recoding_cy.pyx:10-194]()*

---

## 7. IQ-TREE Parsing Acceleration

`parser_iqtree_cy.pyx` accelerates the ingestion of leaf sequences from alignment files [csubst/parser_iqtree_cy.pyx:1-60]():
* `fill_leaf_state_matrix_codon_unambiguous`: Decodes raw codon triplets from byte sequences using ASCII nucleotide lookup (`_nuc_code`) and populates 64-state codon indicator matrices without Python string overhead [csubst/parser_iqtree_cy.pyx:6-60]().

*Sources: [csubst/parser_iqtree_cy.pyx:6-60]()*

---