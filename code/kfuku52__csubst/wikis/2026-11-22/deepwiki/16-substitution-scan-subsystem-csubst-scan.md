# Substitution Scan Subsystem (csubst scan)

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [csubst/main_scan.py](csubst/main_scan.py)
- [csubst/main_sites.py](csubst/main_sites.py)
- [csubst/substitution_scan.py](csubst/substitution_scan.py)
- [docs/ENDPOINT_POSTERIORS.md](docs/ENDPOINT_POSTERIORS.md)
- [docs/SCAN_INFERENCE.md](docs/SCAN_INFERENCE.md)
- [tests/integration/test_scan_candidates_and_rates.py](tests/integration/test_scan_candidates_and_rates.py)
- [tests/integration/test_scan_ctmc.py](tests/integration/test_scan_ctmc.py)
- [tests/integration/test_scan_execution.py](tests/integration/test_scan_execution.py)
- [tests/unit/test_tree_core.py](tests/unit/test_tree_core.py)

</details>



## Purpose and Scope
The substitution scan subsystem (`csubst scan`) discovers recurrent substitutions occurring in specified foreground lineages or clades. Unlike pairwise combinatorial analyses that examine all branch pairs across the entire tree, `csubst scan` targets specific phenotypic traits or foreground groups, tracking whether amino acid or codon changes are enriched along those lineages relative to background branches. 

This page provides a high-level parent overview of the scan architecture, coordinating modules, observation models, and calibration routines. For in-depth technical details, consult the following child pages:
- [Scan Pipeline and Candidate Detection](#4.1)
- [Observation Methods: Marginal, Joint and Bridge CTMC](#4.2)
- [Scan Calibration and Significance](#4.3)

---

```mermaid
graph TD
    A["User Command: csubst scan"] --> B["Orchestrator: main_scan.py"]
    B --> C["Candidate Extraction: substitution_scan.py"]
    B --> D["CTMC Inference: scan_ctmc.py"]
    C --> E["Output Table: csubst_scan.tsv"]
    D --> E
    
    subgraph "Code Entity Space"
        B
        C
        D
    end

    Sources: csubst/main_scan.py:134-168, csubst/substitution_scan.py:31-70, csubst/scan_ctmc.py:26-36
```

---

## 4.1 Scan Pipeline and Candidate Detection

The scan pipeline is orchestrated by `main_scan` (`csubst/main_scan.py`), which initializes runtime configurations, parses input contexts, and executes candidate substitution identification [csubst/main_scan.py:134-168](). Candidate events are generated, filtered, and aggregated across defined scan unit modes (`lineage`, `stem`, or `clade`).

Key features of this layer include:
- **Scan Matches**: Categorization of substitution events across 9 distinct classes (e.g., `any2any`, `spe2spe`, `dif2spe`) as defined in `substitution_scan.py` [csubst/substitution_scan.py:72-82]().
- **Rate Exposure**: Computation of branch lengths and exposures (`q_weighted`, `state_aware`, `raw_branch_length`, `endpoint`) used for rate ratio contrasts [csubst/substitution_scan.py:85-85]().
- **Candidate Caching**: Bounded caching via `_CandidateCache` to speed up repeated posterior extractions [csubst/substitution_scan.py:31-50]().

For detailed coverage of candidate extraction, unit mode definitions, support calculations, and output table schemas, see [Scan Pipeline and Candidate Detection](#4.1).

Sources: `csubst/main_scan.py:134-168`, `csubst/substitution_scan.py:31-90`

---

## 4.2 Observation Methods: Marginal, Joint and Bridge CTMC

To evaluate substitution probabilities and expected jump counts, `csubst scan` relies on sophisticated Continuous-Time Markov Chain (CTMC) observation frameworks implemented in `scan_ctmc.py` and `scan_endpoint.py`. 

```mermaid
graph TD
    A["Input Tree and States"] --> B["Marginal Posterior: csubst/scan_ctmc.py"]
    A --> C["Joint Endpoint: csubst/scan_endpoint.py"]
    A --> D["Bridge CTMC Process: csubst/scan_ctmc.py"]
    B --> E["Substitution Event Tensors"]
    C --> E
    D --> E

    Sources: csubst/substitution_scan.py:61-70, tests/integration/test_scan_ctmc.py:24-36
```

- **Observation Modes**: Supports marginal posteriors, joint endpoint probabilities, and bridge processes (which account for internal reversions along branches).
- **Endpoint Scaling**: Efficient scaling benchmarks and block-size controls manage memory during large-scale posterior computations.

For full mathematical descriptions, conditional pruning algorithms, and endpoint benchmarks, see [Observation Methods: Marginal, Joint and Bridge CTMC](#4.2).

Sources: `csubst/scan_ctmc.py`, `csubst/scan_endpoint.py`, `docs/ENDPOINT_POSTERIORS.md:1-53`

---

## 4.3 Scan Calibration and Significance

Assessing statistical significance in recurrent substitution scans requires handling multiple testing and null-model calibration. The subsystem provides multiple calibration levels via `scan_analytic.py`, `scan_bootstrap.py`, `scan_permutation.py`, and `scan_statistics.py`:

```mermaid
graph TD
    A["Scan Candidates & Scores"] --> B["Analytic Annotation: scan_analytic.py"]
    A --> C["Permutation Tests: scan_permutation.py"]
    A --> D["Parametric Bootstrap: scan_bootstrap.py"]
    B --> E["Benjamini-Hochberg & maxT Corrections"]
    C --> E
    D --> E
    E --> F["Calibrated p-values & q-values"]

    Sources: docs/SCAN_INFERENCE.md:78-114, csubst/main_scan.py:138-141
```

- **Calibration Modes**: Ranges from uncalibrated `none` and `candidate_fixed` to `full_scan`, `parametric`, and `parametric_bootstrap` [docs/SCAN_INFERENCE.md:106-113]().
- **Multiplicity Corrections**: Implements Benjamini-Hochberg (BH) corrections grouped by trait and match class, alongside `maxT`-based family-wise error rate controls across the entire scan run [docs/SCAN_INFERENCE.md:78-114]().

For detailed breakdowns of permutation algorithms, parametric bootstrap null models, and asymptotic/empirical scoring formulas, see [Scan Calibration and Significance](#4.3).

Sources: `csubst/scan_analytic.py`, `csubst/scan_bootstrap.py`, `csubst/scan_permutation.py`, `docs/SCAN_INFERENCE.md:78-114`

---