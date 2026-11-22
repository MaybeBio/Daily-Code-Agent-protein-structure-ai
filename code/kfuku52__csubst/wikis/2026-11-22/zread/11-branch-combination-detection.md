

Branch Combination Detection constitutes the computational core of CSUBST's convergence analysis framework. This system systematically identifies phylogenetically independent branch combinations across multiple levels of complexity (arity K), enabling detection of combinatorial substitutions from pairwise interactions through higher-order convergence patterns involving multiple branches. The architecture balances computational efficiency with statistical rigor through strategic search heuristics and dependency filtering mechanisms.

## Architectural Overview

The branch combination detection system operates through a multi-stage pipeline that progressively explores convergence patterns at increasing levels of complexity (arity K). At each arity level, the system generates candidate branch combinations, filters for phylogenetic independence, computes combinatorial substitution statistics, and evaluates convergence metrics. The core architecture integrates tree topology information, foreground lineage specifications, and statistical thresholds to navigate the exponentially growing combinatorial search space.

```mermaid
flowchart TD
    A[Tree + Substitution Tensors] --> B[Arity K=2 Search]
    
    subgraph K2 ["Arity K=2 Mode Selection"]
        B --> C{Foreground Specified?}
        C -->|Yes| D[Foreground-Targeted Search]
        C -->|No| E[Exhaustive Search]
    end
    
    D --> F[Dependency Filtering]
    E --> F
    
    F --> G[Compute Combinatorial Substitutions]
    G --> H[Convergence Metrics<br/>(ωC, dSC, dNC)]
    H --> I{K = max_arity?}
    
    I -->|No| J{K ≥ 3?}
    J -->|Yes| K[Heuristic Branch-and-Bound]
    J -->|No| B
    
    K --> L[Cutoff Statistic Filtering]
    L --> M[Dependency Filtering]
    M --> G
    
    I -->|Yes| N[Output CB Tables]
```

The system processes branch combinations through three primary computational phases: combination generation, independence filtering, and combinatorial substitution computation. Each phase is optimized for parallel execution and memory efficiency through memory-mapped file operations and multi-threaded computation.

## Search Modes and Strategy Selection

The branch combination detection system employs distinct search strategies based on analysis configuration and arity level. These modes balance computational tractability with statistical power for detecting convergent patterns across phylogenetic trees.

### Arity K=2: Pairwise Branch Combinations

At the foundational level (arity K=2), the system operates in either foreground-targeted or exhaustive mode based on whether foreground lineages are specified and the `exhaustive_until` parameter setting. This decision point fundamentally shapes the search space and computational requirements.

**Foreground-Targeted Search** activates when foreground lineages are specified and `exhaustive_until < 2`. In this mode, branch combinations are generated specifically from target foreground branches identified through `get_target_ids()` [main_analyze.py](csubst/main_analyze.py#L29-L35). The `get_node_combinations()` function accepts `target_id_dict` containing foreground branch IDs and generates combinations specifically within each trait, then unions combinations across traits [combination.py](csubst/combination.py#L35-L36). This targeted approach dramatically reduces search space while focusing on biologically relevant convergence scenarios.

**Exhaustive Search** operates when no foreground specification exists or when `exhaustive_until ≥ 2`. In this mode, `get_node_combinations()` with `exhaustive=True` generates all possible pairwise combinations from all non-root tree branches [combination.py](csubst/combination.py#L68-L73). The `check_attr` parameter (typically set to 'name') ensures only valid branch nodes are considered [combination.py](csubst/combination.py#L36). This mode provides comprehensive coverage but scales quadratically with tree size, requiring substantial computational resources for large phylogenies.

### Arity K≥3: Higher-Order Combinatorial Patterns

For higher-order convergence detection (arity K≥3), the system transitions to heuristic search strategies to manage exponential combinatorial explosion. The `cb_search()` function implements a sophisticated branch-and-bound approach that leverages results from lower-arity analyses to prioritize promising higher-order combinations [main_analyze.py](csubst/main_analyze.py#L36-L89).

**Branch-and-Bound Heuristic** applies when `exhaustive_until < current_arity`. The system identifies K-1 arity branch combinations that passed statistical cutoffs defined by `cutoff_stat` parameter [main_analyze.py](csubst/main_analyze.py#L47-L48). The cutoff statistic typically includes metrics such as ωC, dSC, or dNC that indicate strong convergence signals. These high-scoring combinations serve as seeds for generating higher-order combinations, dramatically reducing the search space while maintaining sensitivity to strong convergence patterns.

The cutoff filtering mechanism operates through `table.get_cutoff_stat_bool_array()`, which evaluates boolean expressions against branch combination statistics [table.py](csubst/table.py#L95-L111). When the number of qualifying combinations exceeds `max_combination` parameter, the system selects the top performers sorted by cutoff statistics, ensuring computational feasibility [main_analyze.py](csubst/main_analyze.py#L52-L56).

**Exhaustive Higher-Order Search** activates when `exhaustive_until ≥ current_arity`. In this mode, all K-1 arity combinations serve as candidates for higher-order generation, enabling comprehensive detection of convergence patterns regardless of their statistical strength [main_analyze.py](csubst/main_analyze.py#L83-L88). This approach is computationally intensive but necessary when researchers expect convergence signals distributed across combinations of moderate statistical strength.

### Mode Comparison Matrix

| Search Mode | Activation Condition | Search Space | Computational Complexity | Use Case |
|-------------|-------------------|--------------|------------------------|----------|
| Foreground-Targeted (K=2) | `foreground` specified AND `exhaustive_until < 2` | Foreground branches only | O(n_fg²) | Focused analysis on predefined convergent lineages |
| Exhaustive (K=2) | No foreground OR `exhaustive_until ≥ 2` | All tree branches | O(n²) | Comprehensive pairwise analysis without prior hypotheses |
| Branch-and-Bound (K≥3) | `exhaustive_until < current_arity` | K-1 combinations passing cutoff | O(n_pass^(K-1)) | Scalable higher-order convergence detection |
| Exhaustive (K≥3) | `exhaustive_until ≥ current_arity` | All K-1 combinations | O(n^(K-1)) | Complete higher-order search for smaller trees |

## Phylogenetic Independence Filtering

A critical component of branch combination detection is the filtering of phylogenetically non-independent combinations. Branch combinations that share ancestral dependencies are not independent evolutionary events and must be excluded to maintain statistical validity. CSUBST implements a two-tiered dependency filtering system: global dependency checking and foreground-specific dependency checking.

### Global Dependency Identification

The system automatically identifies phylogenetically dependent branch sets through `get_global_dep_ids()` [combination.py](csubst/combination.py#L268-L293). This function traverses the tree structure to build dependency sets representing groups of branches that cannot be included together in valid combinations:

- **Ancestor-Dependent Sets**: For each leaf node, the function creates a dependency set containing the leaf and all its ancestors [combination.py](csubst/combination.py#L270-L273). Any combination containing multiple branches from the same lineage path violates independence.
- **Sister Pair Dependencies**: When `exclude_sister_pair` is enabled, the system adds dependencies for sister branches (immediate descendants of common parent) [combination.py](csubst/combination.py#L274-L279). Sister branches evolve from a common ancestral state and may share substitution tendencies due to recent common ancestry.
- **Root-Aware Filtering**: If ancestral state reconstruction did not estimate root states (detected by zero sum at root node), the system creates special dependency sets to exclude combinations crossing sub-root lineages [combination.py](csubst/combination.py#L281-L293).

### Foreground-Specific Dependencies

Foreground lineages introduce additional dependency constraints because branches within the same foreground clade may not represent independent evolutionary events. The `get_foreground_dep_ids()` function identifies branch sets that should be considered dependent within specific foreground contexts [combination.py](csubst/combination.py#L298-L324).

For each foreground trait, the function identifies all branches whose leaf descendants are entirely contained within the foreground lineage [combination.py](csubst/combination.py#L307-L310). This creates dependency sets that prevent multiple branches from the same foreground clade from appearing together in a single combination. The function also incorporates marginal groups (identified through `mg_ids`) when `mg_sister` or `mg_parent` parameters are enabled [combination.py](csubst/combination.py#L321-L323).

### Dependency Filtering Implementation

The dependency filtering process occurs in `get_node_combinations()` through a matrix-based filtering approach. After generating candidate node combinations, the system constructs a binary matrix where rows represent branches and columns represent branch combinations [combination.py](csubst/combination.py#L160-L161):

```python
nc_matrix = numpy.zeros(shape=(len(all_nodes), node_combinations.shape[0]), dtype=bool)
for i in numpy.arange(node_combinations.shape[0]):
    nc_matrix[node_combinations[i,:],i] = True
```

Each dependency set (from both global and foreground dependency sets) is then evaluated against this matrix. Columns (combinations) where multiple branches from the same dependency set appear are marked for removal [combination.py](csubst/combination.py#L163-L167):

```python
is_dependent_col = False
for dep_id in g['dep_ids']:
    is_dependent_col = (is_dependent_col)|(nc_matrix[dep_id,:].sum(axis=0)>1)
```

For foreground dependencies during higher-order searches (when `exhaustive_until >= arity`), dependent combinations are not removed but marked as foreground-dependent rather than foreground-specific [combination.py](csubst/combination.py#L169-L176). This preserves the combination for analysis while accurately reflecting its phylogenetic status. During heuristic searches (when `exhaustive_until < arity`), foreground-dependent combinations are removed to maintain strict independence [combination.py](csubst/combination.py#L180-L186).

> [!TIP]
> The dependency filtering mechanism is computationally intensive but essential for statistical validity. The system reports the number of combinations removed at each stage, providing transparency about how phylogenetic constraints affect the analysis. For large trees with complex foreground specifications, this filtering can eliminate millions of candidate combinations, dramatically accelerating downstream computations.

## Combinatorial Substitution Computation

Once phylogenetically independent branch combinations are identified, the system computes combinatorial substitution metrics that quantify convergence patterns across the specified branches. This process integrates pre-computed substitution tensors (S for synonymous, N for non-synonymous) with branch combination identifiers to produce comprehensive statistical summaries.

### Tensor-Based Combinatorial Calculation

The core computation occurs through `substitution.get_cb()`, which processes branch combination identifiers through `sub_tensor2cb()` [substitution.py](csubst/substitution.py#L178-L208). This function implements a tensor-based approach that efficiently computes four fundamental combinatorial metrics for each branch combination:

1. **OC[S|N]any2any**: Total combinatorial substitutions across all sites, including both specific and non-specific substitutions
2. **OC[S|N]spe2any**: Combinatorial substitutions where at least one branch exhibits a specific substitution
3. **OC[S|N]any2spe**: Combinatorial substitutions resulting in specific outcomes
4. **OC[S|N]spe2spe**: Combinatorial substitutions where all branches exhibit specific substitutions to specific outcomes

The computation leverages NumPy's broadcasting and reduction capabilities to process the 5-dimensional substitution tensor efficiently [substitution.py](csubst/combination.py#L147-L166). For each branch combination, the function aggregates across sites and amino acid states:

```python
df[i, arity+0] += sub_tensor[id_combinations[j,:], :, sg, :, :].sum(axis=(2, 3)).prod(axis=0).sum(axis=0)  # any2any
df[i, arity+1] += sub_tensor[id_combinations[j,:], :, sg, :, :].sum(axis=3).prod(axis=0).sum(axis=1).sum(axis=0)  # spe2any
df[i, arity+2] += sub_tensor[id_combinations[j,:], :, sg, :, :].sum(axis=2).prod(axis=0).sum(axis=1).sum(axis=0)  # any2spe
df[i, arity+3] += sub_tensor[id_combinations[j,:], :, sg, :, :].prod(axis=0).sum(axis=(1, 2)).sum(axis=0)  # spe2spe
```

This tensor manipulation efficiently captures the combinatorial nature of substitutions across branches, sites, and amino acid states without requiring explicit iteration over all dimensions.

### Parallel Processing Architecture

The combinatorial computation is parallelized through `joblib.Parallel` with memory-mapped file backing for efficient inter-process communication [substitution.py](csubst/substitution.py#L190-L202). The `parallel.get_chunks()` function divides branch combinations into balanced chunks based on thread count [parallel.py](csubst/parallel.py), ensuring optimal load distribution across processors.

The parallel architecture includes a critical optimization: `threadpoolctl` limits BLAS threading to single-threaded operation during parallel execution [substitution.py](csubst/substitution.py#L193-L194). This prevents thread oversubscription when NumPy operations themselves attempt to parallelize, which would degrade performance. The memory-mapped output file (`tmp.csubst.cb.out.mmap`) enables efficient data sharing across processes without memory duplication.

### Output Table Structure

The combinatorial computation produces tables (cb) with standardized column structures defined by arity level. Each table contains branch identifier columns followed by combinatorial metric columns. The `table.sort_cb()` function organizes columns in a hierarchical order that facilitates downstream analysis [table.py](csubst/table.py#L20-L45):

```python
col_order = []
col_order += [ 'branch_id_'+str(i+1) for i in numpy.arange(num_branch_id_cols) ]  # Branch identifiers
col_order += cb.columns[cb.columns.str.contains('^dist_')].sort_values().tolist()  # Phylogenetic distances
col_order += cb.columns[cb.columns.str.contains('^branch_num_')].sort_values().tolist()  # Branch counts
col_order += cb.columns[cb.columns.str.contains('^is_')].sort_values().tolist()  # Foreground markers
col_order += cb.columns[(is_omega)&(~is_nocalib)].sort_values().tolist()  # Omega statistics (calibrated)
col_order += cb.columns[(is_d)&(~is_nocalib)].sort_values().tolist()  # dN/dS statistics (calibrated)
col_order += cb.columns[cb.columns.str.contains('^OC[NS]CoD$')].sort_values().tolist()  # Convergence coefficients
col_order += cb.columns[cb.columns.str.contains('^OC[NS]_linreg_residual$')].sort_values().tolist()  # Regression residuals
```

The system outputs separate TSV files for each arity level (`csubst_cb_2.tsv`, `csubst_cb_3.tsv`, etc.), enabling detailed examination of convergence patterns at different combinatorial complexities. Each file includes comprehensive metadata about the branch combinations, substitution counts, and derived statistics.

## Iterative Search Process

The branch combination detection system iterates through arity levels from K=2 to the user-specified maximum arity (`max_arity`). This iterative process, managed by `cb_search()` in `main_analyze.py`, enables discovery of convergence patterns at increasing levels of complexity while leveraging results from lower arities to guide higher-order searches [main_analyze.py](csubst/main_analyze.py#L20-L127).

### Arity Progression and Termination Conditions

The main loop processes each arity level sequentially, with specific termination conditions that can halt the search early:

- **Empty Combinations**: If dependency filtering removes all branch combinations at a given arity, the search terminates with a message explaining that no independent combinations were found [main_analyze.py](csubst/main_analyze.py#L98-L101).
- **Insufficient Unique Branches**: For higher-order searches using heuristic mode, if the set of K-1 combinations passing cutoffs contains fewer unique branches than required for K-arity, the search terminates [main_analyze.py](csubst/main_analyze.py#L62-L65).
- **Maximum Arity Reached**: Upon completing the specified `max_arity`, the loop terminates normally [main_analyze.py](csubst/main_analyze.py#L123-L126).

Each iteration begins with timing information and mode identification, stored in a statistics DataFrame (`df_cb_stats`) that tracks computational metrics across arities [main_analyze.py](csubst/main_analyze.py#L25-L27).

### Statistical Evaluation Pipeline

For each arity level, the system executes a comprehensive statistical pipeline after computing combinatorial substitutions:

1. **Differential Statistics**: `substitution.add_dif_stats()` computes differential substitution metrics (dSC, dNC) with specified floating-point tolerance [main_analyze.py](csubst/main_analyze.py#L90-L91).
2. **Omega Estimation**: `omega.calc_omega()` computes ωC (convergence dN/dS) ratios through expectation calculations under site-wise rate heterogeneity [main_analyze.py](csubst/main_analyze.py#L92-L93).
3. **Long-Tail Calibration**: When enabled (`calibrate_longtail`), the system applies statistical calibration to correct for long-tail distributions in convergence coefficients, but only for arities within the `exhaustive_until` range [main_analyze.py](csubst/main_analyze.py#L94-L102).
4. **Branch Distance**: When enabled (`branch_dist`), phylogenetic distances between branch combinations are computed via `tree.get_node_distance()` [main_analyze.py](csubst/main_analyze.py#L104-L105).
5. **Substitution Per Branch**: `substitution.get_substitutions_per_branch()` adds branch-wise substitution breakdowns [main_analyze.py](csubst/main_analyze.py#L107-L108).
6. **Linear Regression**: `table.get_linear_regression()` computes residuals for convergence coefficient regressions (C vs D), identifying outliers [main_analyze.py](csubst/main_analyze.py#L110-L111).
7. **Foreground Annotation**: `foreground.get_foreground_branch_num()` annotates combinations with foreground branch counts [main_analyze.py](csubst/main_analyze.py#L112-L113).

After statistical computation, tables are sorted via `table.sort_cb()` and exported to TSV files with appropriate formatting [main_analyze.py](csubst/main_analyze.py#L114-L121). The system reports memory consumption of each table, providing transparency about computational requirements.

> [!TIP]
> The iterative search process balances comprehensiveness with computational feasibility. Users can control the trade-off through parameters like `exhaustive_until` (which sets the threshold for switching to heuristic search), `max_arity` (maximum combinatorial complexity), and `cutoff_stat` (stringency of heuristic filtering). Understanding these parameters is essential for designing analyses that are both computationally tractable and statistically powerful.

### Statistics Tracking and Reporting

The `initialize_df_cb_stats()` function creates a tracking DataFrame that captures key metrics for each arity iteration [param.py](csubst/param.py#L65-L71). This DataFrame records:

- **Mode**: Search strategy used (foreground, exhaustive, or branch_and_bound)
- **Elapsed Time**: Computation time per arity level
- **Cutoff Statistics**: Stringency settings for heuristic searches
- **Foreground Enrichment**: Relative over-representation of foreground combinations
- **dSC Calibration**: Whether long-tail calibration was applied
- **Combination Counts**: Number of combinations before/after filtering

The `foreground.add_median_cb_stats()` function computes and records summary statistics including median ωC, dSC, and other metrics across all combinations at each arity [foreground.py](csubst/foreground.py#L458-L519). These statistics provide a high-level view of convergence strength across arities and are reported in both the console output and the final `csubst_cb_stats.tsv` file.

## Performance Optimization and Scalability

The branch combination detection system incorporates multiple performance optimizations to handle the computational demands of phylogenetic convergence analysis across trees ranging from dozens to thousands of branches.

### Memory-Mapped File Operations

The system extensively uses NumPy memory-mapped arrays (`numpy.memmap`) to handle large datasets without loading entire datasets into memory. This is particularly important during two operations:

1. **Node Combination Generation**: The union operation creates a memory-mapped file (`tmp.csubst.node_combinations.mmap`) to store intermediate results during the union of branch combinations across traits [combination.py](csubst/combination.py#L51-L52). This enables parallel processing of union operations without memory duplication.

2. **Combinatorial Computation**: The cb table generation uses a memory-mapped output file (`tmp.csubst.cb.out.mmap`) to accumulate results from parallel processes [substitution.py](csubst/substitution.py#L192-L193). After computation completes, the memory-mapped array is converted to a DataFrame and the temporary file is deleted.

Memory mapping enables the system to process millions of branch combinations with linear memory scaling rather than the quadratic or exponential scaling that would be required with in-memory operations.

### Parallel Processing Strategy

The parallel processing architecture divides work along two primary dimensions:

1. **Combination-Level Parallelism**: Branch combinations are divided into chunks, with each process computing combinatorial statistics for a subset of combinations [substitution.py](csubst/substitution.py#L195-L198). This approach is ideal for cb computation because each combination's statistics are independent.

2. **Union Operation Parallelism**: During node combination generation, the union operation across trait combinations is parallelized, with each process handling a subset of index combinations [combination.py](csubst/combination.py#L54-L57).

The `parallel.get_chunks()` function implements load balancing by dividing work into approximately equal-sized chunks based on thread count [parallel.py](csubst/parallel.py). This ensures all processors have roughly equal work, minimizing idle time.

### Computational Complexity Considerations

The computational complexity varies dramatically across arity levels and search modes:

| Arity (K) | Search Mode | Combinatorial Complexity | Typical Runtime Range |
|-----------|-------------|-------------------------|---------------------|
| K=2 | Foreground-Targeted | O(n_fg²) | Seconds to minutes |
| K=2 | Exhaustive | O(n²) | Minutes to hours |
| K=3 | Branch-and-Bound | O(n_pass²) | Minutes to hours |
| K=3 | Exhaustive | O(n³) | Hours to days |
| K=4+ | Branch-and-Bound | O(n_pass^(K-1)) | Hours to days |

The system reports timing information at each stage, enabling users to monitor progress and estimate remaining runtime. For large trees or high arity levels, users should anticipate substantial computational resources and plan analyses accordingly.

## Configuration and Parameter Control

The branch combination detection system offers extensive configuration options through command-line parameters and the parameter tracking system in the global `g` dictionary. Understanding these parameters is essential for tailoring analyses to specific research questions and computational constraints.

### Core Search Parameters

**max_arity**: Controls the maximum combinatorial complexity explored. Higher values enable detection of higher-order convergence patterns but dramatically increase computational requirements. Typical values range from 2-4, with research questions focusing on pairwise convergence using K=2 and those investigating complex multi-branch convergence using K=3 or K=4.

**exhaustive_until**: Sets the arity threshold for switching from exhaustive to heuristic search. Setting this value to 2 forces heuristic search for all K≥3 combinations, while setting it to 3 or higher enables exhaustive search for K=3 before switching to heuristic search at K=4. This parameter balances comprehensiveness with computational efficiency.

**cutoff_stat**: Defines the statistical criterion for selecting K-1 combinations that will serve as seeds for K-arity combinations in heuristic mode. This string can include logical operators (AND, OR) and comparison operators (>, <, >=, <=) applied to columns such as `omegaC`, `dSC`, or `dNC`. Example: `"omegaC>1.0|dSC<0.01"` selects combinations with high convergence ω or very low synonymous distance.

**max_combination**: Limits the number of K-1 combinations used as seeds for K-arity generation when more combinations pass the cutoff statistic than can be computationally processed. The system selects the top combinations sorted by cutoff statistics, ensuring that the most promising candidates are explored.

### Foreground and Dependency Parameters

**exclude_sister_pair**: When enabled, prevents sister branches (immediate descendants of a common parent) from appearing together in combinations. This parameter should be enabled for most analyses to maintain strict phylogenetic independence, but can be disabled for specific research questions involving recent divergence events.

**fg_exclude_wg**: Controls whether foreground-specific dependency filtering is applied. When enabled, branches within the same foreground clade are marked as dependent and excluded from combinations in heuristic mode, ensuring that foreground combinations represent independent evolutionary events.

**mg_sister** and **mg_parent**: Enable inclusion of marginal groups (sister or parent branches) in foreground dependency sets. These parameters are used for specialized analyses examining convergence patterns at the boundaries of foreground lineages.

### Performance Parameters

**threads**: Controls the number of CPU threads used for parallel computations. Optimal values depend on system architecture and dataset size, but typically range from 1-32. The system automatically manages thread limits to prevent oversubscription.

**float_type**: Specifies the floating-point precision used in computations (e.g., `float64`, `float32`). Lower precision reduces memory usage and may accelerate computations at the cost of numerical precision. This parameter is primarily relevant for very large datasets where memory constraints are binding.

## Integration with Analysis Pipeline

Branch combination detection operates as the central component of CSUBST's broader analysis pipeline, integrating with upstream processing (ancestral state reconstruction, substitution tensor computation) and downstream statistical evaluation (convergence rate calculation, significance testing).

### Upstream Dependencies

The branch combination system requires several inputs prepared by earlier pipeline stages:

1. **Substitution Tensors**: The S and N tensors (synonymous and non-synonymous substitution tensors) computed by `substitution.get_substitution_tensor()` must be available [substitution.py](csubst/substitution.py#L31-L63). These 5-dimensional tensors encode site-wise, state-wise substitution information across the phylogeny.

2. **Tree with Numerical Labels**: The phylogenetic tree must have numerical labels assigned to all nodes (stored in `node.numerical_label`). These labels serve as identifiers for branch combinations.

3. **Foreground Annotations**: When using foreground-targeted search, the tree must have foreground annotations applied via `foreground.annotate_foreground()` [foreground.py](csubst/foreground.py#L195-L219).

4. **Dependency Sets**: Global and foreground dependency sets must be pre-computed via `get_dep_ids()` [combination.py](csubst/combination.py#L328-L331).

### Downstream Applications

The output of branch combination detection feeds into multiple downstream analyses:

- **Convergence Rate Calculation**: The cb tables provide the empirical data for error-corrected convergence rate calculations described in [Convergence Rate Calculation](12-convergence-rate-calculation).

- **Structural Mapping**: Branch combinations identified as exhibiting strong convergence can be mapped to protein structures via the site analysis module, as detailed in [Site-Wise Substitution Mapping](20-site-wise-substitution-mapping).

- **Statistical Significance Testing**: The combinatorial statistics are used in null expectation calculations and significance tests described in [Error-Correction and Null Expectations](14-error-correction-and-null-expectations).

- **Visualization**: Results can be visualized through various plotting functions in the site analysis module, enabling exploration of convergence patterns across tree topology and protein structure.

## Practical Considerations and Recommendations

Effective use of the branch combination detection system requires understanding practical trade-offs and implementing best practices based on research objectives and computational constraints.

### Choosing Search Strategy

**For Hypothesis-Driven Research**: If specific convergent lineages are predefined, use foreground-targeted search at K=2 with `exhaustive_until=1`. This approach minimizes computational requirements while focusing on biologically relevant combinations. Specify foreground lineages precisely to include all relevant branches without introducing noise.

**For Exploratory Discovery**: When investigating unexpected convergence patterns, use exhaustive search at K=2 with branch-and-bound search for K≥3. Set `exhaustive_until=2` to ensure comprehensive pairwise analysis while using heuristic methods for higher-order patterns. This strategy balances coverage with computational feasibility.

**For Large Phylogenies**: For trees with >500 branches, limit exhaustive search to K=2 and use relatively stringent cutoff statistics for K≥3 searches. Consider setting `max_combination=10000` to prevent combinatorial explosion. Monitor runtime carefully and be prepared to terminate analyses if early arities indicate impractical scaling.

### Validating Results

**Phylogenetic Independence**: Always verify that results reflect phylogenetically independent events by examining dependency filtering statistics reported in console output. The system reports the number of combinations removed at each filtering stage; high removal rates suggest substantial phylogenetic structure in the tree.

**Foreground Representation**: Check foreground enrichment statistics in the cb_stats output to confirm that foreground lineages are appropriately represented in results. Low enrichment may indicate that foreground definitions need refinement.

**Statistical Distribution**: Examine the distribution of convergence statistics (ωC, dSC) across combinations. Valid convergence signals typically show long-tail distributions with a subset of combinations exhibiting significantly elevated values.

### Common Pitfalls

**Over-Exhaustive Search**: Attempting exhaustive search at K≥3 for large trees (>200 branches) typically results in intractable computational requirements. Use the `exhaustive_until` parameter strategically to limit exhaustive search to lower arities.

**Loose Cutoff Statistics**: Setting permissive cutoff statistics for heuristic searches (e.g., `omegaC>0`) can generate millions of candidate combinations, making higher-order searches impractical. Balance sensitivity with computational feasibility by using more stringent cutoffs.

**Inadequate Dependency Filtering**: Disabling `exclude_sister_pair` without strong justification can produce statistically invalid results by treating non-independent branches as independent replicates. Maintain default dependency filtering unless specific research questions require its modification.

The branch combination detection system provides a powerful framework for identifying convergent substitution patterns across phylogenetic trees. By understanding the interplay between search modes, dependency filtering, and computational constraints, researchers can design analyses that effectively identify and quantify convergence patterns relevant to their evolutionary questions.