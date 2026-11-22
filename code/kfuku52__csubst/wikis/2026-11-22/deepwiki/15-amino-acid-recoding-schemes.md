# Amino Acid Recoding Schemes

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [csubst/main_benchmark.py](csubst/main_benchmark.py)
- [csubst/main_benchmark_plot.py](csubst/main_benchmark_plot.py)
- [csubst/plotting.py](csubst/plotting.py)
- [csubst/recoding.py](csubst/recoding.py)
- [csubst/recoding_config.py](csubst/recoding_config.py)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [pyproject.toml](pyproject.toml)
- [reports/issue88/csubst_nonsyn_recoding_kgbauto6_PEPC.tsv](reports/issue88/csubst_nonsyn_recoding_kgbauto6_PEPC.tsv)
- [reports/issue88/csubst_nonsyn_recoding_srchisq6_PEPC.tsv](reports/issue88/csubst_nonsyn_recoding_srchisq6_PEPC.tsv)
- [tests/integration/test_main_benchmark.py](tests/integration/test_main_benchmark.py)
- [tests/unit/test_plotting.py](tests/unit/test_plotting.py)

</details>



## Purpose and Scope

Section 3.6 covers the amino acid recoding subsystem within `csubst`, implemented across `csubst/recoding.py` and `csubst/recoding_config.py`. Recoding reduces the 20 canonical amino acids into smaller discrete state spaces (e.g., 4 to 18 groups, or 20 states for the 3Di structural alphabet) to mitigate substitution saturation, accommodate biochemical property classifications, or optimize grouping bins directly from empirical sequence alignments using chi-squared (`srchisq`) or k-mer/group-based heuristics (`kgbauto`). This page details configuration parsing, scheme validation, automatic optimization routines, and generated output tables.

---

## 1. Recoding Configuration and Fixed Schemes

Argument normalization and static recoding group definitions are decoupled from numerical matrix routines to allow fast command-line startup without importing heavy numerical libraries or compiled Cython extensions unnecessarily.

Option mapping and fixed group definitions reside in `csubst/recoding_config.py`. The dictionary `RECODING_SCHEMES` defines standard literature-based groupings such as `dayhoff6`, `sr6`, `kgb6`, `sr4`, `dayhoff9`, `dayhoff12`, `dayhoff15`, and `dayhoff18` [csubst/recoding_config.py:21-32]. Automatic recoding families (`srchisq6` and `kgbauto6`) are registered in `AUTO_RECODING_SCHEMES` [csubst/recoding_config.py:34-39]. 

User-supplied CLI tokens pass through `normalize_nonsyn_recode`, which consults `_RECODING_ALIASES` to resolve abbreviations (e.g., `d6`, `sr-6`, `3di`) into canonical names [csubst/recoding_config.py:41-103]. 

Once numerical recoding is invoked, `csubst/recoding.py` enforces structural integrity via `_validate_scheme`. This function verifies that every recoding assignment covers the 20 canonical amino acids (`_CANONICAL_AA`) exactly once, raising a `ValueError` if any symbol is missing, duplicated, or unrecognized [csubst/recoding.py:23-57].

```mermaid
graph TD
    A["CLI Argument (--nonsyn_recode)"] --> B["csubst.recoding_config.normalize_nonsyn_recode"]
    B --> C["csubst.recoding_config._RECODING_ALIASES"]
    C --> D{"Scheme Type"}
    D -->|Fixed Group| E["csubst.recoding_config.RECODING_SCHEMES"]
    D -->|Auto Optimization| F["csubst.recoding_config.AUTO_RECODING_SCHEMES"]
    E --> G["csubst.recoding._validate_scheme"]
    G --> H["Canonical 20-AA Coverage Check"]
    
    subD ["Code Entity Space"]
    class B,C,E,F,G,H subD
```
*Sources: [csubst/recoding_config.py:21-103](), [csubst/recoding.py:23-61]()*

---

## 2. Automatic Recoding Schemes (`srchisq` and `kgbauto`)

When automatic recoding schemes (`srchisq` or `kgbauto`) are requested, `csubst` derives grouping partitions dynamically from a training alignment file (`nonsyn_recode_training_alignment` or `alignment_file`) [csubst/recoding.py:102-108].

The alignment parser reads codon sequences, filters out stop codons and ambiguous states, and translates codons into amino acid index matrices via `_build_codon_to_aa_map` and `_encode_alignment_as_aa_matrix` [csubst/recoding.py:87-153]. Alignment caching uses SHA-256 fingerprints of the training file content combined with the genetic code table to prevent stale cache reuse across bootstrap replicates or altered sequence files [csubst/recoding.py:156-170].

```mermaid
graph TD
    A["Training Alignment FASTA"] --> B["csubst.recoding._encode_alignment_as_aa_matrix"]
    B --> C["csubst.recoding._build_codon_to_aa_map"]
    C --> D["Amino Acid Index Matrix & Frequencies"]
    D --> E["Optimization Engine (srchisq / kgbauto)"]

    subD ["Code Entity Space"]
    class B,C,D,E subD
```
*Sources: [csubst/recoding.py:87-170]()*

---

## 3. Hill-Climbing and Optimization Engine

Automatic grouping configurations (`srchisq6` and `kgbauto6`) explore state-space partitions using randomized hill-climbing search strategies [csubst/recoding.py:25-32]. 

Random start allocations (`_DEFAULT_AUTO_RANDOM_STARTS` = 1000, with minimum total starts bounded by `_AUTO_RECODE_MIN_TOTAL_STARTS`) distribute search jobs across available CPU threads [csubst/recoding.py:25-32]. 

Numerical calculations—including objective evaluation and state transition updates—are accelerated by the optional Cython extension `recoding_cy` [csubst/recoding.py:18-21]. If compiled extensions are absent or disabled via environment flags, `_warn_cython_fallback` logs a warning once and routes execution through pure-Python fallback routines [csubst/recoding.py:30-38].

*Sources: [csubst/recoding.py:18-38]()*, [docs/ARCHITECTURE.md:77-90]()

---

## 4. Output Tables and Manifests

Recoding schemes generate persistent summary tables documenting how individual codons and amino acids map to recoded states. These artifacts are written during analysis execution and cataloged in the output manifest (`csubst_outputs.tsv`).

As seen in output artifacts such as `reports/issue88/csubst_nonsyn_recoding_kgbauto6_PEPC.tsv` and `reports/issue88/csubst_nonsyn_recoding_srchisq6_PEPC.tsv`, recoding mapping tables contain the following columns:
- `recode`: Identifier of the applied recoding scheme (e.g., `kgbauto6`, `srchisq6`) [reports/issue88/csubst_nonsyn_recoding_kgbauto6_PEPC.tsv:1-2].
- `state_id`: Numerical identifier of the recoded group state [reports/issue88/csubst_nonsyn_recoding_kgbauto6_PEPC.tsv:2].
- `state_label`: Combined single-letter amino acids belonging to the group state [reports/issue88/csubst_nonsyn_recoding_kgbauto6_PEPC.tsv:2].
- `state_members`: Comma-separated amino acid members of the group state [reports/issue88/csubst_nonsyn_recoding_kgbauto6_PEPC.tsv:2].
- `amino_acid`: Individual canonical amino acid letter [reports/issue88/csubst_nonsyn_recoding_kgbauto6_PEPC.tsv:2].
- `aa_codon_indices` / `aa_codons`: Codon indices and triplet sequences specific to the amino acid [reports/issue88/csubst_nonsyn_recoding_kgbauto6_PEPC.tsv:2].
- `state_codon_indices` / `state_codons`: Codon indices and triplet sequences spanned by the entire recoded state group [reports/issue88/csubst_nonsyn_recoding_kgbauto6_PEPC.tsv:2].

*Sources: [reports/issue88/csubst_nonsyn_recoding_kgbauto6_PEPC.tsv:1-21](), [reports/issue88/csubst_nonsyn_recoding_srchisq6_PEPC.tsv:1-22]*

---