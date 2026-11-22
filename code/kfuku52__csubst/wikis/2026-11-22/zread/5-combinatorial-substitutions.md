

Combinatorial substitutions represent the core analytical framework of CSUBST, defined as recurrent substitutions that occur at the same protein site across multiple independent branches in a phylogenetic tree. This concept extends traditional convergence detection by systematically quantifying the probability and patterns of substitutions occurring simultaneously across branch combinations. The framework distinguishes between different substitution types based on ancestral and derived state specificity, enabling sophisticated evolutionary analyses that account for convergent, parallel, and directional evolutionary scenarios.

Sources: [README.md](README.md#L9-L15), [substitution.py](csubst/substitution.py#L118-L135)

## Substitution Tensor Architecture

The foundation of combinatorial substitution analysis is the substitution tensor, a multi-dimensional data structure that encodes the probability and count of substitutions across all branches, sites, and state transitions. The tensor follows a consistent coordinate system: [branch, site, matrix_group, state_from, state_to], where matrix_group partitions substitutions by synonymous codon groups when operating in 'syn' mode or maintains a single group in 'asis' mode. This architecture enables efficient computation of complex substitution patterns through tensor operations without iterative branch-by-branch calculations.

Two operational modes govern tensor construction: 'asis' mode preserves the full 61-sense-codon state space, while 'syn' mode collapses states into amino acid groupings based on synonymous codon relationships. The syn mode partitions the 20 amino acids into separate matrix groups, each containing only codons encoding that amino acid, which is essential for discriminating between synonymous and non-synonymous substitution patterns. Tensor initialization leverages memory-mapped files to handle large datasets without exceeding RAM capacity.

Sources: [substitution.py](csubst/substitution.py#L12-L30), [substitution.py](csubst/substitution.py#L31-L63)

## Combinatorial Substitution Types

The framework categorizes combinatorial substitutions into four distinct classes based on the specificity of ancestral and derived states across the branch combination:

- **any2any**: Aggregates all substitutions regardless of ancestral or derived state specificity. Calculated by summing over all state transitions and taking the product across branches: `sum(axis=(2, 3)).prod(axis=0)`. This represents the broadest measure of convergent activity at a site.

- **spe2any**: Requires a specific ancestral state but permits any derived state. Computed as `sum(axis=3).prod(axis=0).sum(axis=1)`, this pattern detects directional convergence where different branches start from the same ancestral codon but may diverge to multiple derived states.

- **any2spe**: Permits any ancestral state but requires convergence to a specific derived state. The calculation `sum(axis=2).prod(axis=0).sum(axis=1)` identifies parallel evolution toward the same amino acid or codon from different starting points.

- **spe2spe**: The most restrictive pattern requiring both specific ancestral and specific derived states. Computed as `prod(axis=0).sum(axis=(1, 2))`, this detects precise convergent substitutions where multiple branches undergo identical codon transitions.

These four metrics provide complementary perspectives on convergence patterns, with any2any serving as a sensitive but non-specific detector, while spe2spe offers high specificity for detecting exact convergence events.

Sources: [substitution.py](csubst/substitution.py#L118-L135), [substitution.py](csubst/substitution.py#L147-L178)

## Branch Combination Generation and Independence Filtering

The analytical power of combinatorial substitutions depends critically on generating appropriate branch combinations while ensuring statistical independence. The `get_node_combinations` function supports three generation strategies: exhaustive enumeration of all possible branch combinations, targeted combinations based on user-specified foreground lineages, or extension of previously computed combinations. All strategies produce combinations of a specified arity (number of branches), enabling detection of higher-order convergence beyond pairwise comparisons.

Independence filtering removes branch combinations that share evolutionary history, which would violate statistical assumptions. The algorithm identifies dependent branch sets by traversing the phylogenetic tree: leaf branches share ancestry with all ancestral branches on their path to the root, and sister branch pairs represent the most obvious dependency. When configured, sister pair exclusion removes these direct dependencies, while root-level handling addresses incomplete ancestral state reconstruction. The filtering process constructs a binary incidence matrix where rows represent branches and columns represent combinations, then removes columns where multiple dependent branches co-occur.

Foreground-dependent branch identification further refines combinations by recognizing branch groups within user-defined foreground lineages. These groups include all branches within monophyletic foreground clades, enabling analysis of whether convergence is concentrated within specific evolutionary contexts versus distributed across the entire tree.

Sources: [combination.py](csubst/get_node_combinations#L35-L177), [combination.py](csubst/combination.py#L268-L328)

## Substitution Pattern Quantification

Once branch combinations are established, the framework quantifies substitution patterns through `sub_tensor2cb`, which computes combinatorial substitution counts for each branch combination. This function operates on the substitution tensor, performing tensor product operations that aggregate substitution probabilities across specified branches while maintaining site-wise resolution. The output is a matrix where each row represents one branch combination and columns contain branch identifiers plus the four combinatorial substitution type counts.

Site-wise combinatorial substitution analysis via `get_cs` provides complementary branch-agnostic perspective by aggregating across all combinations at each site. This function produces a five-column DataFrame with site index and counts for each substitution type, enabling identification of sites exhibiting high convergence rates irrespective of branch identity. The site-wise metric is particularly useful for protein structure mapping, where convergent sites are examined for spatial clustering and functional relevance.

Substitution pattern analysis extends to pattern identification through `calc_substitution_patterns`, which clusters combinations based on their S_sub and N_sub count vectors. By sorting counts within each combination and identifying unique patterns, the algorithm reduces the combinatorial space to tractable pattern categories, revealing whether convergence occurs through similar or divergent substitution mechanisms across different branch combinations.

Sources: [substitution.py](csubst/substitution.py#L147-L178), [substitution.py](csubst/substitution.py#L118-L135), [combination.py](csubst/combination.py#L249-L267)

## Higher-Order Convergence Detection

The framework's support for arbitrary arity combinations enables detection of higher-order convergence involving more than two branches. While pairwise convergence detection (arity=2) is most common and computationally tractable, higher arity values reveal more complex evolutionary scenarios where the same site undergoes substitutions across multiple independent lineages. The computational complexity scales combinatorially with arity and branch count, necessitating efficient tensor operations and parallel processing.

The heuristic approach to higher-order convergence operates through incremental expansion: first detecting significant pairwise convergence events, then testing whether those sites exhibit additional substitutions on third or fourth branches. The `exhaustive_until` parameter controls the maximum arity for exhaustive search, with higher arities optionally restricted to foreground-dependent combinations to maintain computational feasibility. This strategy balances comprehensiveness against the exponential growth of the combination space.

Sources: [combination.py](csubst/combination.py#L35-L177), [README.md](README.md#L12)

## Statistical and Computational Considerations

Combinatorial substitution computation leverages multiple optimization strategies for performance: memory-mapped tensors enable analysis of large datasets exceeding RAM capacity, parallel processing via joblib distributes combination-level computations across multiple CPUs, and Cython acceleration (where available) speeds up tensor product operations. The combination generation uses `nc_matrix2id_combinations` to efficiently convert binary incidence matrices to branch ID combinations through parallel chunk processing.

Error correction through minimum posterior probability thresholds prevents spurious substitution counts from uncertain ancestral state reconstructions. The `apply_min_sub_pp` function filters substitution tensors based on confidence thresholds, ensuring that only well-supported substitutions contribute to combinatorial metrics. This is critical for convergence detection, as false positives from reconstruction artifacts would otherwise inflate apparent convergence rates.

The framework's integration with both empirical and mechanistic codon substitution models enables users to match the null expectations to their evolutionary questions. Empirical models derived from observed substitution frequencies provide data-driven baselines, while mechanistic models based on mutation-selection theory offer theoretical expectations under specific evolutionary regimes.
