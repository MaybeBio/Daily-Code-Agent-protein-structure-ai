# Substitution Tensors

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [csubst/combination.py](csubst/combination.py)
- [csubst/endpoint.py](csubst/endpoint.py)
- [csubst/foreground.py](csubst/foreground.py)
- [csubst/main_analyze.py](csubst/main_analyze.py)
- [csubst/omega.py](csubst/omega.py)
- [csubst/param.py](csubst/param.py)
- [csubst/parser_iqtree.py](csubst/parser_iqtree.py)
- [csubst/parser_misc.py](csubst/parser_misc.py)
- [csubst/substitution.py](csubst/substitution.py)
- [csubst/substitution_sparse.py](csubst/substitution_sparse.py)
- [csubst/substitution_sparse_cy.pyx](csubst/substitution_sparse_cy.pyx)
- [csubst/tree.py](csubst/tree.py)
- [reports/efficiency_20261015/README.md](reports/efficiency_20261015/README.md)
- [reports/efficiency_20261015/benchmark.py](reports/efficiency_20261015/benchmark.py)
- [reports/efficiency_20261015/profile_summary.json](reports/efficiency_20261015/profile_summary.json)
- [reports/efficiency_20261015/results.json](reports/efficiency_20261015/results.json)
- [reports/efficiency_20261015/scan_core.json](reports/efficiency_20261015/scan_core.json)
- [reports/efficiency_20261015/trees.json](reports/efficiency_20261015/trees.json)
- [reports/efficiency_20261015/verification.json](reports/efficiency_20261015/verification.json)

</details>



## Purpose and Scope

Substitution tensors are core data structures in `csubst` designed to store, project, and manipulate branch-site substitution events. They map ancestral states at parent nodes to descendant states at child nodes across all sequence sites and phylogenetic branches. This page provides a high-level overview of dense and sparse tensor architectures, projection strategies, site storage mechanisms, and endpoint posteriors. 

For deep technical details, refer to the child pages:
- [SparseSubstitutionTensor and Packed CSR Design](#3.2.1)
- [Cython Acceleration Layer](#3.2.2)

---

## 1. Dense and Sparse Substitution Tensors

The substitution tensor characterizes evolutionary transitions across branches and sites. Historically maintained as multi-dimensional dense arrays or event-specific dictionaries (`csubst/substitution.py:1-40`), modern implementations leverage a high-performance sparse architecture (`csubst/substitution_sparse.py:31-75`).

A sparse substitution tensor (`SparseSubstitutionTensor`) encapsulates a 5-D conceptual space—`(num_branch, num_site, num_group, num_state_from, num_state_to)`—into a single flattened Compressed Sparse Row (CSR) matrix (`csubst/substitution_sparse.py:31-42`). This design eliminates Python object overhead and redundant pointer arrays per substitution category.

```mermaid
graph TD
    A["StateTensorAnc" <br/> "csubst/substitution.py"] --> C["SparseSubstitutionTensor" <br/> "csubst/substitution_sparse.py"]
    B["StateTensorDesc" <br/> "csubst/substitution.py"] --> C
    C --> D["PackedCSRMatrix" <br/> "csubst/substitution_sparse.py:73"]
    D --> E["CythonBuilders" <br/> "csubst/substitution_sparse_cy.pyx"]
    
    style C fill:none,stroke:#000,stroke-width:1px
    style D fill:none,stroke:#000,stroke-width:1px
    style E fill:none,stroke:#000,stroke-width:1px
```

Sources: `csubst/substitution.py:1-40`, `csubst/substitution_sparse.py:31-75`, `csubst/substitution_sparse_cy.pyx:1-76`

---

## 2. Sparse Substitution Tensor and Packed CSR Design

The packed CSR layout encodes substitution events into columns defined by `event_id * num_site + site`, where `event_id` merges group, from-state, and to-state indices (`csubst/substitution_sparse.py:31-40`). 

For details on the packed CSR layout, event ID encoding formulas, projection statistics (`spe2spe`, `any2any`, etc.), and reducer subclasses, see [SparseSubstitutionTensor and Packed CSR Design](#3.2.1).

```mermaid
graph TD
    F["TensorDimensions" <br/> "SparseSubstitutionTensor"] --> G["EventIDEncoding" <br/> "csubst/substitution_sparse.py:100"]
    G --> H["PackedCSRRow" <br/> "branch_id"]
    H --> I["ColumnIndex" <br/> "event_id * num_site + site"]
    
    style F fill:none,stroke:#000,stroke-width:1px
    style G fill:none,stroke:#000,stroke-width:1px
    style H fill:none,stroke:#000,stroke-width:1px
    style I fill:none,stroke:#000,stroke-width:1px
```

Sources: `csubst/substitution_sparse.py:31-111`, `csubst/substitution_sparse_cy.pyx:14-160`

---

## 3. Cython Acceleration Layer

To prevent performance bottlenecks during tensor construction and combination evaluations, performance-critical routines are implemented in Cython extensions (`csubst/_extensions.py`). Modules such as `substitution_sparse_cy.pyx` provide optimized fast paths for unrolling loops over branch pairs, states, and sites (`csubst/substitution_sparse_cy.pyx:14-160`).

For details on compilation flags, specific `.pyx` modules (`substitution_cy`, `omega_cy`, `combination_cy`, etc.), and pure-Python fallback mechanisms, see [Cython Acceleration Layer](#3.2.2).

Sources: `csubst/substitution.py:20-22`, `csubst/substitution_sparse_cy.pyx:1-160`

---

## 4. Projections, Site Storage, and Endpoint Posteriors

Substitution tensors are projected along branch combinations to generate combinatoric substitution tables (`csubst/substitution.py:63-82`, `csubst/main_analyze.py:54-105`). Site storage modules manage site-filtering masks and alignment indices (`csubst/substitution.py:18`), while endpoint modules compute continuous-time Markov chain (CTMC) branch endpoints and marginal rate category posteriors conditioned on a fitted model (`csubst/endpoint.py:1-40`).

```mermaid
graph TD
    J["cb_search" <br/> "csubst/main_analyze.py:140"] --> K["get_cbs" <br/> "csubst/substitution.py:73"]
    K --> L["SparseSubstitutionTensor.project" <br/> "csubst/substitution_sparse.py"]
    K --> M["EndpointModel" <br/> "csubst/endpoint.py:30"]
    M --> N["UniformizationTransition" <br/> "csubst/endpoint.py:91"]

    style J fill:none,stroke:#000,stroke-width:1px
    style K fill:none,stroke:#000,stroke-width:1px
    style L fill:none,stroke:#000,stroke-width:1px
    style M fill:none,stroke:#000,stroke-width:1px
    style N fill:none,stroke:#000,stroke-width:1px
```

Sources: `csubst/substitution.py:63-82`, `csubst/main_analyze.py:54-105`, `csubst/endpoint.py:1-50`

---