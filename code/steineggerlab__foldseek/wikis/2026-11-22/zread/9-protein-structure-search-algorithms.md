

Protein structure comparison is a fundamental task in bioinformatics, enabling researchers to understand evolutionary relationships, predict functions, and discover distant homologs. Foldseek revolutionizes this field by achieving sensitivities comparable to state-of-the-art structural aligners while being **20,000 times faster**. This breakthrough is made possible through innovative algorithms that transform the complex 3D structure comparison problem into an efficient sequence-like search problem.

## The Core Innovation: 3Di Descriptors

At the heart of Foldseek's speed lies its revolutionary approach to representing protein structures. Instead of directly comparing 3D coordinates, Foldseek converts each protein structure into a **1D sequence of structural states** called 3Di (3D interaction) descriptors. This transformation is the key innovation that enables the use of ultra-fast sequence search algorithms for structural comparisons.

The 3Di alphabet consists of **20 discrete states**, each representing a specific local structural conformation. These states are derived from the spatial relationships between residues, capturing essential geometric information while discarding redundant details. The conversion process involves several sophisticated steps:

1. **Virtual Center Calculation**: For each residue, Foldseek calculates a virtual center point that represents the optimal position for structural interactions. This virtual center is computed using the Cα, Cβ, and N atom coordinates with specific geometric parameters. `Sources: [structureto3di.h#L15-L16](lib/3di/structureto3di.h#L15-L16)`

2. **Feature Extraction**: For each pair of interacting residues, Foldseek computes **10 geometric features** that capture their spatial relationship. These features include distances, angles, and other geometric descriptors that encode the local structural environment. `Sources: [structureto3di.h#L12](lib/3di/structureto3di.h#L12-L13)`

3. **Neural Network Encoding**: The extracted features are fed into a **neural network encoder** (implemented using Kerasify) that transforms them into 2D embeddings. This step reduces dimensionality while preserving the essential structural information. `Sources: [structureto3di.h#L113-L115](lib/3di/structureto3di.h#L113-L115)`

4. **State Discretization**: The continuous 2D embeddings are then mapped to the nearest of the **20 predefined centroid states** in the 3Di alphabet. This discretization creates the final 1D sequence representation that can be searched using sequence-based algorithms. `Sources: [structureto3di.h#L18-L39](lib/3di/structureto3di.h#L18-L39)`

```cpp
// Example of 3Di state centroids in 2D embedding space
const double centroids[CENTROID_CNT][EMBEDDING_DIM] = {
    { -1.0729,  -0.3600},  // State 0
    { -0.1356,  -1.8914},  // State 1
    {  0.4948,  -0.4205},  // State 2
    // ... 17 more states
};
```

## Multi-Stage Search Pipeline

Foldseek employs a sophisticated multi-stage search pipeline that balances sensitivity and speed. This approach allows it to quickly eliminate non-matching structures while carefully examining promising candidates.

### Stage 1: Prefiltering

The first stage uses **k-mer matching** or **ungapped alignment** to rapidly identify potential matches. Foldseek offers three prefiltering modes:

1. **KMER Mode**: Uses traditional k-mer based prefiltering for fast initial screening
2. **UNGAPPED Mode**: Performs ungapped alignments for higher sensitivity
3. **EXHAUSTIVE Mode**: Skips prefiltering entirely for maximum sensitivity (much slower)

```cpp
switch(par.prefMode){
    case LocalParameters::PREF_MODE_KMER:
        cmd.addVariable("PREFMODE", "KMER");
        break;
    case LocalParameters::PREF_MODE_UNGAPPED:
        cmd.addVariable("PREFMODE", "UNGAPPED");
        break;
    case LocalParameters::PREF_MODE_EXHAUSTIVE:
        cmd.addVariable("PREFMODE", "EXHAUSTIVE");
        break;
}
```
`Sources: [StructureSearch.cpp#L114-L127](src/workflow/StructureSearch.cpp#L114-L127)`

The prefiltering stage is designed to be extremely fast, reducing the search space by orders of magnitude while retaining most true positives. This is where Foldseek achieves its dramatic speed improvements over traditional structural alignment methods.

### Stage 2: Structural Alignment

After prefiltering, promising candidates undergo more detailed structural alignment. Foldseek supports **three different alignment algorithms**, each optimized for different use cases:

1. **3Di+AA Alignment**: The default mode that combines 3Di structural states with amino acid sequence information using a modified Smith-Waterman algorithm. This provides an excellent balance of speed and sensitivity.

2. **TM-align**: A global structural alignment algorithm that superimposes structures and computes the TM-score, a measure of structural similarity. This mode is more sensitive but significantly slower.

3. **3Di-only Alignment**: Uses only the structural state information without amino acid sequence, useful for detecting very distant structural relationships.

```cpp
if(par.alignmentType == LocalParameters::ALIGNMENT_TYPE_TMALIGN){
    cmd.addVariable("ALIGNMENT_ALGO", "tmalign");
    // ... TM-align specific parameters
}else if(par.alignmentType == LocalParameters::ALIGNMENT_TYPE_3DI_AA){
    cmd.addVariable("ALIGNMENT_ALGO", "structurealign");
    // ... 3Di+AA alignment parameters
}
```
`Sources: [StructureSearch.cpp#L128-L152](src/workflow/StructureSearch.cpp#L128-L152)`

### Stage 3: Iterative Search (Optional)

For detecting very distant structural relationships, Foldseek supports **iterative search** workflows. This approach builds profiles from initial search results and uses them for subsequent rounds of searching, progressively expanding the sensitivity of the search.

The iterative search can be configured with different numbers of iterations and E-value thresholds for each round, allowing users to balance between sensitivity and computational resources.

```cpp
if(par.numIterations > 1 || par.numIterations == 0){
    for (int i = 0; i < par.numIterations; i++) {
        if (i == (par.numIterations - 1)) {
            par.evalThr = originalEval;  // Use final threshold for last iteration
        }
        // Configure parameters for each iteration
        cmd.addVariable(std::string("PREFILTER_PAR_" + SSTR(i)).c_str(),
                        par.createParameterString(par.prefilter).c_str());
    }
}
```
`Sources: [StructureSearch.cpp#L158-L192](src/workflow/StructureSearch.cpp#L158-L192)`

## Advanced Features and Optimizations

### GPU Acceleration

Foldseek leverages modern GPU hardware to further accelerate the prefiltering stage. The ungapped prefilter can be offloaded to NVIDIA GPUs, providing significant speedups for large-scale searches. This requires an NVIDIA GPU of the Ampere generation or newer for optimal performance.

```cpp
// GPU can only use the ungapped prefilter
if (par.gpu == 1 && par.PARAM_PREF_MODE.wasSet == false) {
    par.prefMode = Parameters::PREF_MODE_UNGAPPED;
}
```
`Sources: [StructureSearch.cpp#L109-L112](src/workflow/StructureSearch.cpp#L109-L112)`

### Memory Optimization

Foldseek provides several memory optimization strategies to handle large databases:

1. **Cα Coordinate Storage**: Optionally includes Cα coordinates for more accurate hit ranking (requires more memory)
2. **Structure Bits**: A compact representation that reduces memory usage while maintaining sensitivity
3. **Single Query Mode**: Optimized for searching single queries against large databases

The memory requirements scale with the database size, with typical usage ranging from **35GB to 151GB** for the entire AlphaFold database, depending on the optimization level chosen.

### Multimer Support

Foldseek extends its algorithms to handle **protein complexes** through specialized multimer search and clustering workflows. These consider the spatial arrangement of multiple chains and can identify evolutionary relationships between entire protein complexes.

## Algorithm Selection Guide

Choosing the right algorithm configuration depends on your specific needs:

| Use Case | Recommended Algorithm | Reason |
|----------|----------------------|---------|
| **Fast screening** | 3Di+AA with KMER prefilter | Maximum speed for initial screening |
| **Sensitive search** | TM-align with iterative search | Highest sensitivity for distant relationships |
| **Large-scale search** | 3Di+AA with GPU acceleration | Best balance of speed and sensitivity |
| **Complex comparison** | Multimer search | Specialized for protein complexes |
| **Memory-constrained** | 3Di-only without Cα | Minimal memory footprint |

> [!TIP]
> For most use cases, the default 3Di+AA alignment with sensitivity setting 9.5 provides the best balance of speed and sensitivity. Only switch to TM-align if you need maximum sensitivity and have computational resources to spare.

## Performance Characteristics

Foldseek's algorithms are designed to scale efficiently with database size, making it suitable for searching against massive structural databases like AlphaFold DB (54 million structures). Key performance characteristics include:

- **Search Speed**: Up to 20,000x faster than traditional structural alignment methods
- **Sensitivity**: Comparable to state-of-the-art structural aligners like TM-align
- **Memory Usage**: Configurable from 35GB to 151GB for full AlphaFold DB
- **Scalability**: Linear scaling with database size for prefiltering stage

The combination of innovative 3Di descriptors, multi-stage search pipeline, and hardware acceleration makes Foldseek the tool of choice for large-scale protein structure analysis and discovery.
