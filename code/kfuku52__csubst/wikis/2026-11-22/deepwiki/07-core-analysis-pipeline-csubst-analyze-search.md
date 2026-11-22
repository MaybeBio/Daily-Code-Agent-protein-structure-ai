# Core Analysis Pipeline (csubst analyze/search)

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [csubst/combination.py](csubst/combination.py)
- [csubst/foreground.py](csubst/foreground.py)
- [csubst/main_analyze.py](csubst/main_analyze.py)
- [csubst/omega.py](csubst/omega.py)
- [csubst/param.py](csubst/param.py)
- [csubst/parser_iqtree.py](csubst/parser_iqtree.py)
- [csubst/parser_misc.py](csubst/parser_misc.py)
- [csubst/substitution.py](csubst/substitution.py)
- [csubst/tree.py](csubst/tree.py)

</details>



The core analysis pipeline of `csubst` (executed via `csubst analyze` or `csubst search`) orchestrates the end-to-end transformation of phylogenetic input files into combinatorial substitution (`cb`) tables. The pipeline parses tree topologies and ancestral state distributions, constructs high-dimensional dense and sparse substitution tensors, evaluates expected substitution rates under codon or urn null models, exhaustively or selectively searches branch combinations up to arity $K$, and computes combinatorial convergence metrics ($\omega_C$, OCN, OCS).

For complete technical specifications, refer to the child pages linked throughout this document.

```mermaid
graph TD
    subdata[""Input Data Files (.treefile, .state, .rate)""] --> parser[""parser_misc.py: prepare_input_context()""]
    parser --> tensors[""substitution.py: Substitution Tensor Construction""]
    tensors --> search[""main_analyze.py: cb_search()""]
    search --> stats[""omega.py: Omega & Null Expectations""]
    stats --> cb[""Combinatorial Substitution Tables (.tsv)""]

    classDef default fill:#fff,stroke:#000,stroke-width:1px;
```
*Diagram 1: End-to-end architecture of the `csubst analyze` pipeline bridging conceptual phases to code entities.*
Sources: `csubst/parser_misc.py:105-128`, `csubst/substitution.py:132-151`, `csubst/main_analyze.py:140-163`, `csubst/omega.py:1-50`

---

## 3.1 Input Parsing and Ancestral States

The input parsing stage validates user arguments, loads phylogenetic trees via `ete`, invokes or interfaces with IQ-TREE outputs (`.state`, `.rate`, `.treefile`), manages genetic codes, and builds internal alignment-to-site index mappings.

For detailed documentation on input handling, subprocess management, and sequence I/O, see [Input Parsing and Ancestral States](#3.1).

Sources: `csubst/parser_misc.py:105-128`, `csubst/parser_iqtree.py:126-139`, `csubst/tree.py:124-147`

---

## 3.2 Substitution Tensors

Substitution events across sites and branches are represented as multidimensional tensors. `csubst` supports both dense NumPy arrays and memory-efficient sparse representations (`SparseSubstitutionTensor`) using packed Compressed Sparse Row (CSR) layouts to track state transitions (`any2any`, `spe2any`, `any2spe`, `spe2spe`).

For detailed tensor construction algorithms, memory optimization strategies, and projection projections, see [Substitution Tensors](#3.2).

Sources: `csubst/substitution.py:20-43`, `csubst/substitution.py:132-151`

### 3.2.1 SparseSubstitutionTensor and Packed CSR Design

To scale to large phylogenies and genome-scale alignments, sparse substitution tensors use `event_id` encoding and compressed sparse row structures. Reducer subclasses aggregate event counts across branch subsets while minimizing memory footprint and maintaining floating-point precision.

For detailed sparse data structures and memory caps, see [Substitution Tensors](#3.2).

Sources: `csubst/substitution.py:25-42`, `csubst/substitution_sparse.py`

### 3.2.2 Cython Acceleration Layer

Performance-critical inner loops—such as state matching, tensor projections, null expectation accumulation, and combination generation—are accelerated via compiled Cython extension modules (`substitution_cy`, `substitution_sparse_cy`, `omega_cy`, `combination_cy`, `recoding_cy`, `parser_iqtree_cy`). Robust pure-Python fallbacks ensure compatibility when extensions are unavailable.

For build processes, fallback handlers, and Cython signatures, see [Substitution Tensors](#3.2).

Sources: `csubst/substitution.py:20-22`, `csubst/combination.py:16-27`, `csubst/omega.py:48-65`

---

## 3.3 Omega Statistics, Expectations and Calibration

The calculation of combinatorial omega ($\omega_C$) requires robust statistical expectations of substitution counts under neutrality. The `omega` module coordinates empirical null models, codon-model expected substitution counts, urn models (Wallenius/Fisher), ancestor-state-reconstruction variance (ASRV) adjustments, pseudocount strategies, and $d_{SC}$ long-tail calibration to generate accurate empirical $p$-values and false-discovery rate (FDR) q-values.

For detailed mathematical formulations of null expectations and calibration procedures, see [Omega Statistics, Expectations and Calibration](#3.3).

Sources: `csubst/omega.py:19-48`, `csubst/param.py:118-163`

---

## 3.4 Branch Combinations, Foreground and Higher-Order Search

Branch combinations are generated incrementally by arity $K$ (starting from $K=2$ up to `max_arity`). The search subsystem handles exhaustive combinatorial generation as well as targeted foreground searches, clade permutations, trait-based masking, and parallel chunking across CPU cores.

For detailed combination generation algorithms and parallelization schemes, see [Branch Combinations, Foreground and Higher-Order Search](#3.4).

```mermaid
graph TD
    init[""main_analyze.py: cb_search()""] --> arityLoop[""Loop current_arity from 2 to max_arity""]
    arityLoop --> modeCheck[""foreground.py / combination.py: Generate/Filter Combinations""]
    modeCheck --> subTensor[""substitution.py: Extract Branch Combinations (cbs)""]
    subTensor --> computeOmega[""omega.py: Calculate Omega & Statistics""]
    computeOmega --> nextArity[""Next Arity or Output cb Table""]

    classDef default fill:#fff,stroke:#000,stroke-width:1px;
```
*Diagram 2: Data flow and execution hierarchy of the combinatorial branch search pipeline.*
Sources: `csubst/main_analyze.py:140-163`, `csubst/combination.py:59-84`, `csubst/substitution.py:73-75`, `csubst/foreground.py:1-22`

Sources: `csubst/main_analyze.py:140-163`, `csubst/combination.py:59-84`, `csubst/foreground.py:1-22`

---

## 3.5 Epistasis and Structure Weighting

Structural context and pairwise epistasis models allow `csubst` to weight substitution events using protein 3D structural data (PDB/AlphaFold) or predicted structural alphabets (3Di). Site-specific contact degrees and cross-fitted structural state probabilities modify expectation calculations to detect structurally constrained co-substitutions.

For detailed epistasis weighting rules and 3Di integration, see [Epistasis and Structure Weighting](#3.5).

Sources: `csubst/omega.py:45-46`, `csubst/omega.py:112-166`

---

## 3.6 Amino Acid Recoding Schemes

To mitigate compositional bias and saturation at deep evolutionary timescales, `csubst` supports fixed and automated nonsynonymous amino acid recoding schemes (such as `srchisq`, `kgbauto`, and `3di20`). Hill-climbing optimization routines group amino acids based on substitution matrix properties, generating recoded states and output conversion tables.

For detailed recoding configuration options, optimization algorithms, and PCA output generation, see [Amino Acid Recoding Schemes](#3.6).

Sources: `csubst/parser_misc.py:33-102`, `csubst/recoding_config.py`

---