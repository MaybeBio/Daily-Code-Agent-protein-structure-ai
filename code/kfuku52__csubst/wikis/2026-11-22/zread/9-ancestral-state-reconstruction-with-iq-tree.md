

CSUBST leverages IQ-TREE 2.0+ for ancestral state reconstruction (ASR) to generate probabilistic ancestral state estimates across phylogenetic trees. This integration serves as the foundation for downstream combinatorial substitution detection by providing the probabilistic state distributions at every node for each codon site. The ASR pipeline transforms IQ-TREE's output into structured tensors that capture substitution uncertainty, enabling sophisticated convergence analysis that accounts for reconstruction ambiguity.

## Architecture Overview

The IQ-TREE ASR integration follows a modular pipeline architecture that orchestrates external tool execution, file parsing, tensor construction, and data validation:

```mermaid
graph TB
    subgraph "Input Validation"
        A[Check IQ-TREE Dependency] --> B[Version >= 2.0.0 Required]
        B --> C[Verify Intermediate Files]
    end
    
    subgraph "IQ-TREE Execution"
        C --> D{Files Exist & Model Match?}
        D -->|Yes| E[Skip IQ-TREE Run]
        D -->|No| F[Run IQ-TREE Ancestral]
        F --> G[Write Temporary Tree]
        G --> H[Execute: iqtree -s aln -te tree -m MODEL --ancestral --rate --redo]
    end
    
    subgraph "Output Parsing"
        E --> I[Parse IQ-TREE Outputs]
        H --> I
        I --> J[Read .state File<br/>State Probabilities]
        I --> K[Read .log File<br/>ω, κ, Genetic Code]
        I --> L[Read .rate File<br/>Site-wise Rates]
        I --> M[Read .iqtree File<br/>Model, π Frequencies]
    end
    
    subgraph "Tensor Construction"
        J --> N[Build State Tensor<br/>(node, site, state)]
        N --> O{ML Mode?}
        O -->|No| P[Keep Probabilistic States]
        O -->|Yes| Q[argmax → Binary States]
        P --> R[Mask Missing Sites]
        Q --> R
    end
    
    subgraph "Downstream Processing"
        R --> S[Substitution Tensor Computation]
        S --> T[Combinatorial Substitution Detection]
    end
```

The architecture ensures **idempotent operations** through intelligent caching—IQ-TREE only reruns when input parameters change or intermediate files are missing, while preserving reproducibility across analysis runs. The pipeline bridges external phylogenetic inference with internal tensor-based computations, creating a unified probabilistic framework for convergence detection.

Sources: [parser_iqtree.py](/csubst/parser_iqtree.py#L15-L63), [parser_misc.py](/csubst/parser_misc.py#L14-L36)

## IQ-TREE Execution and Dependency Management

CSUBST enforces strict dependency validation before executing IQ-TREE to ensure compatibility and prevent runtime errors. The dependency checker verifies both IQ-TREE availability and version requirements:

The version validation uses semantic version comparison, requiring IQ-TREE 2.0.0 or later to access the ancestral state reconstruction capabilities and rate estimation features. When IQ-TREE executes, CSUBST constructs a specialized command that includes codon sequence type specification, user-defined genetic code (default NCBI table 1 for standard code), automatic threading configuration, and forced reexecution with the `--redo` flag to overwrite previous outputs.

> [!TIP]
> The `--seqtype CODON{n}` parameter dynamically appends the genetic code identifier (e.g., CODON1 for standard, CODON2 for vertebrate mitochondrial), ensuring IQ-TREE uses the correct codon-to-amino acid mapping throughout reconstruction. This parameter is critical for maintaining consistency between CSUBST's codon table and IQ-TREE's internal translation logic.

CSUBST performs tree-alignment consistency verification before IQ-TREE execution. If the user-provided tree and alignment contain mismatched taxa labels, the pipeline exits with a descriptive error message unless `force_notree_run=True` is specified for simulation parameter estimation. When tree and alignment are consistent, the pipeline provides a fixed topology to IQ-TREE via the `-te` flag, allowing ancestral state estimation under the user-defined tree rather than allowing IQ-TREE to infer an alternative topology.

Sources: [parser_iqtree.py](/csubst/parser_iqtree.py#L40-L63), [parser_misc.py](/csubst/parser_misc.py#L34-L36)

## Intermediate File Management

The intelligent caching system checks for five critical IQ-TREE output files: `.iqtree` (main results), `.log` (run metadata), `.rate` (site-wise rates), `.state` (ancestral probabilities), and `.treefile` (final tree). Users can customize file paths through `--iqtree_{extension}` parameters or accept automatic naming based on the input alignment file:

| File Extension | Content | Default Naming | Custom Parameter |
|----------------|---------|----------------|------------------|
| `.iqtree` | Model parameters, likelihood scores | `{alignment}.iqtree` | `--iqtree_iqtree` |
| `.log` | Execution log, ω and κ estimates | `{alignment}.log` | `--iqtree_log` |
| `.rate` | Site-specific rate categories | `{alignment}.rate` | `--iqtree_rate` |
| `.state` | Ancestral state probabilities per site | `{alignment}.state` | `--iqtree_state` |
| `.treefile` | Newick tree with estimated branch lengths | `{alignment}.treefile` | `--iqtree_treefile` |

The caching logic performs two validation checks: file existence and model compatibility. If all required files exist and the substitution model in the `.iqtree` file matches the user-specified `--iqtree_model`, the pipeline skips IQ-TREE execution entirely, saving significant computational time for large analyses. If files exist but the model has changed (e.g., switching from `ECM+G` to `GY94+G`), CSUBST displays a clear mismatch message and triggers IQ-TREE rerun with the correct model. The `--iqtree_redo` flag forces rerun even when files exist, useful for debugging or when external file corruption is suspected.

Sources: [parser_iqtree.py](/csubst/parser_iqtree.py#L27-L38), [parser_misc.py](/csubst/parser_misc.py#L18-L36)

## State File Parsing and Data Type Detection

The `.state` file from IQ-TREE contains tab-separated ancestral state probability distributions for each internal node across all sites. CSUBST parses this file to extract site-wise state counts and automatically determine the input data type:

- **Nucleotide (4 states)**: When the state table contains 4 probability columns (`p_A`, `p_C`, `p_G`, `p_T`), CSUBST sets `input_data_type = 'nuc'` and stores state orders as `['A', 'C', 'G', 'T']`
- **Protein (20 states)**: When 20 columns corresponding to amino acids are detected, `input_data_type = 'pep'` with state orders as the 20 standard amino acids
- **Codon (61+ states)**: When more than 20 columns exist, `input_data_type = 'cdn'` with full codon orders (excluding stop codons unless specified)

For codon data, CSUBST constructs critical data structures for downstream synonymous/nonsynonymous substitution classification. The codon orders are extracted directly from the `.state` file column headers (stripping the `p_` prefix), and the system builds a **matrix groups** dictionary mapping each amino acid to its constituent codons (e.g., `'A': ['GCT', 'GCC', 'GCA', 'GCG']` for Alanine). Concurrently, a **synonymous indices** dictionary maps amino acids to their column indices in the state tensor, enabling rapid synonymy lookups during substitution tensor computation.

The system validates alignment consistency by checking that the number of codon sites in the user-provided alignment (calculated as sequence length ÷ 3) matches the number of sites in the ancestral state file. This detects corrupted inputs or mismatched preprocessing before tensor construction begins.

Sources: [parser_iqtree.py](/csubst/parser_iqtree.py#L65-L95)

## State Tensor Construction

The state tensor is the core data structure bridging IQ-TREE output and combinatorial substitution analysis. It is a 3-dimensional NumPy array with shape `[num_node, num_site, num_state]` that stores posterior probabilities for each state at each node and site:

```python
axis = [num_node, num_input_site, num_input_state]
state_tensor = numpy.zeros(axis, dtype=g['float_type'])
# state_tensor[node_label, site_index, state_index] = probability
```

Construction proceeds differently for leaf nodes versus internal nodes:

**Leaf Nodes**: CSUBST reads the observed sequences directly from the user-provided alignment and encodes them as deterministic states (probability = 1.0 for the observed codon, 0 for others). Ambiguous nucleotides (R, Y, S, W, K, M, B, D, H, V, N) are handled by distributing probability equally among all compatible states according to the genetic code's ambiguous base table.

**Internal Nodes**: For ancestral nodes, CSUBST extracts the probability vectors from the `.state` file row corresponding to the node name. The parser handles IQ-TREE's special state indicators: `???` (completely uncertain) and `?` (partially uncertain) are masked to zero probability, and nodes present in the tree but absent from the `.state` file generate warnings with node names for debugging.

> [!TIP]
> The numerical label assignment through tree traversal ensures consistent indexing between the state tensor and downstream tensors. CSUBST assigns sequential numerical labels to all non-root nodes during tree annotation, allowing tensor-based computations without repeated string-based node lookups.

After initial population, the tensor undergoes NaN-to-zero conversion and missing site masking. The masking algorithm traverses each internal node and checks if its child clades and sister clades have non-zero probability for each site. If a site shows zero evidence in both children and the sister clade (suggesting missing data rather than true absence), the node's probability for that site is set to zero. This prevents spurious substitution calls from reconstruction uncertainty in poorly aligned regions.

Sources: [parser_iqtree.py](/csubst/parser_iqtree.py#L154-L203)

## Maximum Likelihood Mode

By default, CSUBST operates in probabilistic mode, preserving the full posterior distribution of ancestral states. However, users can enable maximum likelihood mode via the `--ml_anc` flag, which converts probabilistic states to binary discrete states:

```python
if g['ml_anc']:
    idxmax = numpy.argmax(state_tensor, axis=2)
    state_tensor2 = numpy.zeros(state_tensor.shape, dtype=bool)
    for b in numpy.arange(state_tensor2.shape[0]):  # branches
        for s in numpy.arange(state_tensor2.shape[1]):  # sites
            if state_tensor[b,s,:].sum() != 0:
                state_tensor2[b,s,idxmax[b,s]] = 1
```

In this mode, the state tensor becomes a boolean array where each site-node combination has exactly one state with probability 1.0 (the maximum a posteriori estimate). This mode sacrifices uncertainty quantification for computational simplicity and deterministic output. The conversion applies only to sites with non-zero total probability (sites with all-zero rows remain all-zero). Users should be aware that ML mode eliminates the ability to perform uncertainty-aware convergence analysis, potentially biasing results when ancestral state ambiguity is high.

Sources: [parser_iqtree.py](/csubst/parser_iqtree.py#L193-L203)

## Log File Parameter Extraction

The IQ-TREE log file contains critical parameters that CSUBST extracts for downstream model specification and validation:

**Omega (dN/dS)**: The nonsynonymous-to-synonymous rate ratio is extracted via pattern matching on the line containing "Nonsynonymous/synonymous ratio (omega): {value}". This parameter is required when using mechanistic models (GY94, MG94) for instantaneous rate matrix construction. Missing omega values trigger assertion errors with clear error messages indicating that IQ-TREE must be rerun with a GY-based model.

**Kappa (Transition/Transversion Ratio)**: Extracted similarly from the "Transition/transversion ratio (kappa): {value}" line. This parameter scales instantaneous transition rates relative to transversions in mechanistic models and is also required for GY94/MG94-based analyses.

**Reconstruction Codon Table**: The genetic code used by IQ-TREE during reconstruction is parsed from the line "Converting to codon sequences with genetic code {n}...". CSUBST validates that this matches the user-specified `--genetic_code` parameter to prevent mismatches between the reconstruction framework and downstream analysis. The codon table identifier is stored in `g['reconstruction_codon_table']` for reference.

Sources: [parser_iqtree.py](/csubst/parser_iqtree.py#L121-L137)

## Equilibrium Frequency Estimation

When `eq=True` (default), CSUBST parses codon equilibrium frequencies (π) from the IQ-TREE output file. The parser uses regular expressions to extract all frequency values of the form `pi({CODON}) = {value}`, populating a DataFrame indexed by codon orders:

```python
pi = pandas.DataFrame(index=g['codon_orders'], columns=['freq'])
for m in re.finditer(r'  pi\(([A-Z]+)\) = ([0-9.]+)', txt, re.MULTILINE):
    pi.at[m.group(1), 'freq'] = float(m.group(2))
g['equilibrium_frequency'] = pi.loc[:,'freq'].values.astype(g['float_type'])
g['equilibrium_frequency'] /= g['equilibrium_frequency'].sum()
```

The frequencies are normalized to sum to 1.0, ensuring proper probability distributions for instantaneous rate matrix construction. These π values serve as the stationary distribution for time-reversible substitution models and are critical for calculating expected substitution rates under the null model. Users should verify that the codon table specified during IQ-TREE execution matches the codon orders in the `.state` file—mismatches can cause misaligned frequency extraction.

Sources: [parser_iqtree.py](/csubst/parser_iqtree.py#L104-L119)

## Site-wise Rate Heterogeneity

IQ-TREE's `--rate` flag generates site-wise rate categories (typically in a discrete gamma or free-rate distribution). CSUBST reads these rates from the `.rate` file as a vector of length `num_input_site`:

```python
rate_sites = pandas.read_csv(g['path_iqtree_rate'], sep='\t', header=0, comment='#')
rate_sites = rate_sites.loc[:, 'C_Rate'].values
```

If the rate file is empty (e.g., when IQ-TREE is run without rate heterogeneity models), CSUBST defaults to a vector of ones, implying uniform rates across sites. These site-wise rates are stored in `g['iqtree_rate_values']` and are currently used primarily for diagnostic purposes and potential rate-aware substitution weighting in future developments. The rate values preserve the original IQ-TREE scaling, allowing researchers to correlate convergence patterns with site-specific evolutionary rates.

Sources: [parser_iqtree.py](/csubst/parser_iqtree.py#L97-L102)

## State Tensor Translation and Storage

After tensor construction, CSUBST performs data type conversions to support both codon-level and protein-level analyses:

**Codon to Protein State Translation**: For codon data, a protein-level state tensor (`g['state_pep']`) is generated by aggregating codon probabilities to amino acid probabilities. Each amino acid's probability equals the sum of probabilities for all synonymous codons. This enables detection of convergence at the protein level while preserving codon-level uncertainty.

**Storage Assignment**: All state tensors are assigned to the global configuration dictionary for downstream access:
- `g['state_nuc']`: Nucleotide-level tensor (legacy, currently deprecated)
- `g['state_cdn']`: Codon-level tensor (primary for convergence detection)
- `g['state_pep']`: Protein-level tensor (used for protein-specific analyses)

The tensors are then passed to the substitution tensor computation module, where they serve as the probabilistic foundation for calculating substitution probabilities along each branch. The separation of codon and protein tensors allows CSUBST to analyze both synonymous and nonsynonymous convergence simultaneously while maintaining their distinct evolutionary interpretations.

Sources: [parser_misc.py](/csubst/parser_misc.py#L199-L224)

## Visualization of Ancestral States

CSUBST provides optional visualization of ancestral states through tree plotting capabilities. When enabled via `--plot_state_codon` or `--plot_state_aa`, the pipeline generates per-site tree visualizations that map the most probable ancestral state onto each node:

The visualization system creates separate directories (`csubst_plot_state_codon` or `csubst_plot_state_aa`) to organize the large number of output files. For each site, a PDF is generated showing the tree with colored branches and state labels at each node. Internal nodes display only the state character, while leaf nodes show a composite label format: `{state}|{taxon_name}`. This allows quick verification that ancestral reconstruction matches expectations and helps identify sites with ambiguous reconstructions (displayed as `---` for codons or `-` for amino acids when probability is zero or evenly distributed).

The plotting uses ETE3's tree rendering engine with 300 DPI resolution for publication-quality output. Branch colors correspond to foreground/marginal annotations, and state colors indicate the character type. This visualization is particularly valuable for exploring specific sites identified as having high convergence rates, allowing researchers to visually inspect whether the reconstructed states align with known functional or structural hypotheses.

Sources: [tree.py](/csubst/tree.py#L249-L279), [main_analyze.py](/csubst/main_analyze.py#L147-L160)

## Integration with Substitution Tensor Computation

The ancestral state reconstruction pipeline directly feeds into the substitution tensor computation, which calculates the probability of substitutions along each branch. The state tensor's probabilistic nature enables uncertainty-aware substitution detection:

For each branch (parent → child), the substitution tensor computes the outer product of parent and child state probabilities, masked to exclude identity transitions (no substitution). The computation uses Einstein summation notation for efficiency:

```python
# For amino acid substitutions (asis mode)
sub_matrix = numpy.einsum("sa,sd,ad->sad", 
                         state_tensor_anc[parent,:,:],  # parent probs: [site, state_from]
                         state_tensor[child,:,:],        # child probs: [site, state_to]
                         diag_zero)                      # exclude identity
sub_tensor[child, :, 0, :, :] = sub_matrix  # [site, aa_from, aa_to]
```

For synonymous substitutions, the operation groups codons by their amino acid equivalents, computing substitution probabilities within each synonymous codon set. This dual-mode computation enables CSUBST to distinguish between convergent amino acid changes (independently arising in multiple lineages) and convergent synonymous changes (which may indicate selection on codon usage rather than protein function).

The minimum substitution posterior probability threshold (`--min_sub_pp`) applies a filter to the substitution tensor, setting values below the threshold to zero. This controls the sensitivity-specifiedness tradeoff—higher thresholds reduce false positives from reconstruction uncertainty but may miss true convergent events with ambiguous ancestral states.

Sources: [substitution.py](/csubst/substitution.py#L31-L62), [substitution.py](/csubst/substitution.py#L64-L70), [main_analyze.py](/csubst/main_analyze.py#L161-L167)

## Error Handling and Validation

The ASR pipeline implements multi-layer validation to catch errors early with informative messages:

1. **IQ-TREE Version Validation**: Semantic version checking prevents execution with incompatible IQ-TREE versions (<2.0.0), ensuring access to required features like codon ancestral reconstruction
2. **Tree-Alignment Consistency**: Taxon name comparison between the user-provided tree and alignment detects mismatched datasets before expensive computation
3. **Site Count Validation**: Comparison of codon site counts between alignment and `.state` file catches preprocessing errors or corrupted files
4. **Codon Table Consistency**: Verification that the genetic code used in reconstruction matches the user-specified code prevents mistranslation errors
5. **Model Compatibility**: Checks that the substitution model in existing IQ-TREE outputs matches user specifications when using cached results
6. **Parameter Availability**: Validation that omega and kappa are available in the log file when required for mechanistic model construction

When errors are detected, CSUBST provides context-specific error messages that guide users toward solutions. For example, missing omega values include a reminder to rerun IQ-TREE with a GY-based model, while codon table mismatches suggest verifying the `--genetic_code` parameter.

Sources: [parser_iqtree.py](/csubst/parser_iqtree.py#L15-L25), [parser_misc.py](/csubst/parser_misc.py#L83-L85)

## Configuration Parameters

Key parameters controlling IQ-TREE ASR behavior in CSUBST:

| Parameter | Description | Default | Valid Values |
|-----------|-------------|---------|---------------|
| `--iqtree_exe` | Path to IQ-TREE executable | `'iqtree2'` | Any valid path |
| `--iqtree_model` | Codon substitution model | Required | `GY94`, `MG94`, `ECMK07`, `ECMrest` with rate heterogeneity modifiers |
| `--genetic_code` | NCBI genetic code ID | `1` | `1` (standard), `2` (vertebrate mitochondrial), etc. |
| `--iqtree_redo` | Force IQ-TREE rerun even if files exist | `False` | Boolean |
| `--ml_anc` | Convert probabilistic states to ML binary states | `False` | Boolean |
| `--min_sub_pp` | Minimum posterior probability for substitution counting | `0` | [0.0, 1.0] |
| `--threads` | Number of CPU threads for IQ-TREE | System-dependent | Positive integer |
| `--plot_state_codon` | Generate codon-level ancestral state tree plots | `False` | Boolean |
| `--plot_state_aa` | Generate amino acid-level ancestral state tree plots | `False` | Boolean |

Model specifications support IQ-TREE's full syntax, including rate heterogeneity (`+G{n}`, `+R{n}`) and frequency models (`+F`, `+F1x4`, `+F3x4`). For example, `--iqtree_model ECMK07+F+G4` specifies the ECMunrest model with empirical frequencies and 4-category gamma rate heterogeneity.

Sources: [README.md](/README.md#L52-L76), [param.py](/csubst/param.py) (inferred parameter module)

## Next Steps

The ancestral state reconstruction pipeline is a prerequisite for downstream convergence analysis. After successful ASR execution, the state tensors enable:

- **Substitution Tensor Computation**: Calculate probabilistic substitution histories along each branch, forming the foundation for convergence detection. See [Substitution Tensor Computation](10-substitution-tensor-computation)
- **Branch Combination Detection**: Identify independent branches experiencing convergent substitutions at the same sites. See [Branch Combination Detection](11-branch-combination-detection)
- **Convergence Rate Calculation**: Compute error-corrected convergence rates with null expectations. See [Convergence Rate Calculation](12-convergence-rate-calculation)
- **Site-Wise Analysis**: Map combinatorial substitutions onto specific sites for structural interpretation. See [Site-Wise Substitution Mapping](20-site-wise-substitution-mapping)

The modular pipeline design allows researchers to inspect intermediate outputs (state tensors, substitution tensors) before proceeding to full combinatorial analysis, facilitating debugging and method validation at each stage.