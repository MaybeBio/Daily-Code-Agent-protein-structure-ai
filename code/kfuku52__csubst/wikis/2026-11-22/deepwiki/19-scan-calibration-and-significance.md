# Scan Calibration and Significance

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.github/scripts/ci_scope.py](.github/scripts/ci_scope.py)
- [.github/scripts/scan_endpoint_benchmark.py](.github/scripts/scan_endpoint_benchmark.py)
- [.github/scripts/scan_integration_benchmark.py](.github/scripts/scan_integration_benchmark.py)
- [csubst/clade_index.py](csubst/clade_index.py)
- [csubst/epistasis.py](csubst/epistasis.py)
- [csubst/scan_analytic.py](csubst/scan_analytic.py)
- [csubst/scan_bootstrap.py](csubst/scan_bootstrap.py)
- [csubst/scan_permutation.py](csubst/scan_permutation.py)
- [csubst/scan_statistics.py](csubst/scan_statistics.py)
- [docs/SCAN_ANALYTICAL.md](docs/SCAN_ANALYTICAL.md)
- [docs/SCAN_CALIBRATION.md](docs/SCAN_CALIBRATION.md)
- [tests/integration/test_scan_calibration_null.py](tests/integration/test_scan_calibration_null.py)
- [tests/integration/test_scan_endpoint.py](tests/integration/test_scan_endpoint.py)
- [tests/process/test_scan_permutations_process.py](tests/process/test_scan_permutations_process.py)
- [tests/unit/test_ci_artifacts.py](tests/unit/test_ci_artifacts.py)
- [tests/unit/test_iqtree_process.py](tests/unit/test_iqtree_process.py)
- [tests/unit/test_iqtree_state_tensor.py](tests/unit/test_iqtree_state_tensor.py)
- [tests/unit/test_scan_analytic.py](tests/unit/test_scan_analytic.py)
- [tests/unit/test_scan_bootstrap.py](tests/unit/test_scan_bootstrap.py)
- [tests/unit/test_scan_statistics.py](tests/unit/test_scan_statistics.py)
- [tools/validate_scan_calibration.py](tools/validate_scan_calibration.py)

</details>



## Purpose and Scope

This page documents the statistical calibration, significance testing, and correction subsystems used by the `csubst scan` pipeline. Because posterior substitution event masses and rate summaries do not follow independent integer Poisson distributions [csubst/scan_statistics.py:1-5](), `csubst` provides multiple calibration mechanisms: exploratory asymptotic diagnostic scores, conditional uniform clade permutations (`csubst/scan_permutation.py`), fitted-codon parametric bootstraps (`csubst/scan_bootstrap.py`), and closed-form analytic endpoint-enrichment e-values (`docs/SCAN_ANALYTICAL.md` [docs/SCAN_ANALYTICAL.md:1-15]()). This page details the implementation of these scoring functions, permutation engines, bootstrap models, and false discovery rate (FDR) corrections.

---

## Asymptotic Rate Scores and Statistical Contracts

The exploratory substitution scan pipeline evaluates foreground versus background rate enrichment using log-likelihood ratio deviances mapped to one-sided Poisson asymptotic tails [csubst/scan_statistics.py:1-43]().

### Key Functions in `csubst/scan_statistics.py`

- `rate_score(x_target, l_target, x_other, l_other)`: Computes the negative log10 one-sided Poisson asymptotic tail probability and score for target versus control counts and exposures [csubst/scan_statistics.py:18-42](). It uses `scipy.special.log_ndtr` [csubst/scan_statistics.py:10] to avoid underflow in extreme enrichment tails and returns `(0., 1.)` when non-enrichment occurs [csubst/scan_statistics.py:28-29].
- `maximum_score(frame)`: Extracts the maximum `score_rate_enrichment` from a candidate results DataFrame, validating rows via `calibration_score` [csubst/scan_statistics.py:45-54].
- `calibration_score(row)`: Enforces testability rules, returning `-np.inf` for zero-exposure valid contrasts while raising `ValueError` on malformed or undefined rate metrics [csubst/scan_statistics.py:56-72].
- `empirical_pvalue(observed, reference, expected_count, exact)`: Computes an inclusive upper-tail empirical $p$-value against Monte Carlo or enumerated null replicates, applying a conservative offset (`+1`) for Monte Carlo draws [csubst/scan_statistics.py:74-92].

```python
# Example: Computing rate enrichment score and asymptotic P-value
from csubst import scan_statistics
score, p_value = scan_statistics.rate_score(x_target=2.0, l_target=1.0, x_other=0.0, l_other=1.0)
```

Sources: [csubst/scan_statistics.py:1-92](), [tests/unit/test_scan_statistics.py:1-118]()

---

## Non-Overlapping Permutation Engine (`csubst/scan_permutation.py`)

To control for lineage structure and branch distribution without modeling evolutionary sequences, `csubst` implements conditional uniform sampling of non-overlapping foreground configurations [csubst/scan_permutation.py:1-7]().

### Clade Plans and Allocation Sampling

1. **`nonoverlapping(configuration, descendants)`**: Validates that selected foreground components do not share ancestral or descendant branches [csubst/scan_permutation.py:39-47].
2. **`build_plan(bin_array, eligible, observed, descendants)`**: Constructs a `CladePlan` dataclass by identifying eligible branches within rate/length bins, calculating the total proposal space size via multinomial combinations, and fully enumerating valid non-overlapping configurations if the total count is below `ENUMERATION_PROPOSAL_LIMIT` (10,000) [csubst/scan_permutation.py:61-103].
3. **`sample_configuration(plan, rng)`**: Draws a uniform configuration either by random indexing into pre-enumerated configurations or via bounded rejection sampling (`MAX_REJECTION_DRAWS = 10,000`) [csubst/scan_permutation.py:106-130].

```
+-----------------------------------------------------------------+
|                        Natural Language Space                   |
|       "Condition on branch bins and draw non-overlapping"       |
+-----------------------------------------------------------------+
                                 |
                                 v
+-----------------------------------------------------------------+
|                       Code Entity Space                         |
|   csubst/scan_permutation.py:build_plan()                       |
|   - Evaluates eligible[] and bin_array[]                        |
|   - Computes proposal_count using math.comb()                   |
+-----------------------------------------------------------------+
                                 |
        +------------------------+------------------------+
        | (<= 10,000 proposals)                           | (> 10,000 proposals)
        v                                                 v
+---------------------------------+   +---------------------------------+
| Pre-enumerated configurations   |   | csubst/scan_permutation.py:     |
| stored in CladePlan.configurations| | sample_configuration()          |
+---------------------------------+   | - Rejection sampling loop       |
                                      | - Calls nonoverlapping()        |
                                      +---------------------------------+
```

Sources: [csubst/scan_permutation.py:1-129](), [tests/process/test_scan_permutations_process.py:1-42]()

---

## Parametric Bootstrap and Fitted Observation Models (`csubst/scan_bootstrap.py`)

When `--scan_pvalue_calibration parametric_bootstrap` is selected, `csubst` generates model-conditional null distributions by simulating alignments under a fitted homogeneous codon model [csubst/scan_bootstrap.py:1-7]().

### Workflow and Execution Guardrails

- **`capture_options(args, parser)`**: Snapshots original CLI configuration parameters while resolving absolute file paths [csubst/scan_bootstrap.py:27-39].
- **`validate_options(g)`**: Enforces strict prerequisites: requires `--scan_permutation_seed >= 0`, restricts models to `GY+F` or `GY+FQ`, and forbids 3Di observation models or pre-computed IQ-TREE intermediate files [csubst/scan_bootstrap.py:42-60].
- **`require_precise_fit(g)`**: Verifies the presence of IQ-TREE checkpoint files (`.ckp.gz`) and log files containing empirical state frequencies, triggering a refit if necessary [csubst/scan_bootstrap.py:65-81].
- **`alignment_loglikelihood(model, sequences)`**: Performs an independent scaled pruning check on reconstructed fitted generators using matrix exponentials (`scipy.linalg.expm`) across tree branches [csubst/scan_bootstrap.py:104-132].

Sources: [csubst/scan_bootstrap.py:1-368](), [tests/unit/test_scan_bootstrap.py:1-120]()

---

## Analytic Endpoint-Enrichment Inference (`csubst/scan_analytic.py`)

As detailed in [docs/SCAN_ANALYTICAL.md](), `--scan_analytic_pvalue endpoint_mixture` computes a simulation-free, closed-form test integrating ancestral states and rate categories across the full codon tree [docs/SCAN_ANALYTICAL.md:1-24]().

### Mathematical Formulation and E-Values

Instead of treating fractional posterior event masses as integer Poisson observations, analytic inference computes scaled tree-pruning likelihoods $P_0(D)$ under the null and $P_a(D)$ under alternative endpoint tilts [docs/SCAN_ANALYTICAL.md:26-45](). 

Four alternative transition matrices are constructed by multiplying endpoint transition probabilities by factors of $2$, $10$, $100$, and taking the infinite-tilt limit (conditioning rows on matching endpoints) [docs/SCAN_ANALYTICAL.md:29-36](). The mixture expectation $E(D)$ yields a conservative upper bound on the tail probability via Markov's inequality [docs/SCAN_ANALYTICAL.md:46-58]`:

$$\text{p\_endpoint\_enrichment\_analytic} = \min\left(1, \frac{1}{E(D)}\right)$$

### Hypothesis Universe and Benjamini-Hochberg (BH) Corrections

The family size $m$ is fixed *before* site filtering or candidate discovery across all testable dimensions [docs/SCAN_ANALYTICAL.md:69-75]():

$$m = \text{input\_sites} \times \text{traits} \times \text{foreground\_targets} \times \sum (\text{contrasts\_per\_match})$$

Reciprocal e-values are adjusted using Benjamini-Hochberg (BH) corrections across the full run universe ($q\_endpoint\_enrichment\_analytic\_bh$), ensuring valid false discovery rate (FDR) control under arbitrary hypothesis dependence [docs/SCAN_ANALYTICAL.md:82-90]().

```
+-----------------------------------------------------------------+
|                    Natural Language Space                       |
|  "Compute closed-form e-values and adjust FDR across family m"  |
+-----------------------------------------------------------------+
                                 |
                                 v
+-----------------------------------------------------------------+
|                       Code Entity Space                         |
|   docs/SCAN_ANALYTICAL.md / csubst/scan_analytic.py             |
|   - Computes null likelihood P0(D) and tilted alternatives      |
|   - Mixture E(D) = (P2 + P10 + P100 + Pcond) / (4 * P0)         |
|   - Family size m = sites * traits * targets * contrasts        |
|   - q_endpoint_enrichment_analytic_bh via e-BH adjustment       |
+-----------------------------------------------------------------+
```

Sources: [docs/SCAN_ANALYTICAL.md:1-188](), [tests/unit/test_scan_analytic.py:1-100]()

---