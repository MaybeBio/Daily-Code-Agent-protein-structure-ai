

The OpenMM Relaxation Pipeline provides a high-performance alternative to PyRosetta for protein structure relaxation within FreeBindCraft. This implementation leverages OpenMM's molecular dynamics capabilities combined with FASPR side-chain packing to deliver comparable structural optimization while avoiding PyRosetta's licensing constraints and dependency complexity.

## Architecture Overview

The pipeline implements a sophisticated multi-stage relaxation process with intelligent chain handling and performance optimization strategies:

```mermaid
flowchart TD
    A[Input PDB] --> B{De-concatenation Check}
    B -->|ColabDesign chains| C[Split into biological chains]
    B -->|Single chain| D[PDBFixer preparation]
    C --> D
    D --> E[OpenMM System Setup]
    E --> F[Initial Minimization]
    F --> G[Multi-stage Ramp Loop]
    G --> H[MD Shake + Minimization]
    H --> I{More stages?}
    I -->|Yes| G
    I -->|No| J[Optional FASPR Repacking]
    J --> K[Post-FASPR Minimization]
    K --> L[Re-concatenation]
    L --> M[Final Output PDB]
    
    subgraph Platform Selection
        N[OpenCL/CUDA/GPU]
        O[CPU Fallback]
        P[Retry Logic]
    end
    
    E -.-> Platform Selection
```

## Core Implementation

### Main Relaxation Function

The `openmm_relax()` function in [`functions/pr_alternative_utils.py`](functions/pr_alternative_utils.py#L847) serves as the primary entry point, implementing a comprehensive relaxation protocol with the following key characteristics:

**Multi-stage Energy Minimization**: The pipeline uses a configurable 3-stage ramp approach with:
- **Restraint ramp factors**: `(1.0, 0.4, 0.0)` for gradual backbone constraint reduction
- **Lennard-Jones repulsion ramp**: `(0.0, 1.5, 3.0)` for progressive clash resolution
- **MD shake integration**: Applied only to first two stages for performance optimization

**Force Field Configuration**: Uses OpenMM's `amber14-all.xml` force field with OBC2 implicit solvent and custom forces:
- **Backbone restraints**: Harmonic position restraints on heavy atoms (3.0 kcal/mol/Å² default)
- **Custom LJ repulsion**: Additional repulsive force for clash resolution
- **Energy minimization**: L-BFGS optimizer with configurable force tolerances

### Chain Handling Strategy

A critical innovation in this pipeline is the **de-concatenation/re-concatenation** approach that prevents OpenMM from forming inappropriate peptide bonds:

1. **De-concatenation**: When `BINDCRAFT_STARTING_PDB` and `BINDCRAFT_TARGET_CHAINS` environment variables are set, the pipeline splits ColabDesign's concatenated chain 'A' into separate biological chains based on original structure analysis using [`compute_target_segment_lengths()`](functions/pr_alternative_utils.py#L998)

2. **Processing**: Relaxation occurs on properly separated chains to maintain biological fidelity

3. **Re-concatenation**: Final structure is merged back into chain 'A' for downstream compatibility using [`merge_chains_into_single()`](functions/pr_alternative_utils.py#L1478)

This approach ensures that OpenMM treats each biological unit as a separate entity while maintaining compatibility with existing BindCraft scoring pipelines.

> [!TIP]
> The de-concatenation strategy is essential for ColabDesign outputs where multiple biological chains are concatenated into a single chain 'A', preventing OpenMM from inappropriately inferring peptide bonds across biological boundaries or discontinuous segments.

## Performance Optimization

### Platform Selection and Error Handling

The pipeline implements robust platform selection with automatic fallback:

```python
platform_order = ['OpenCL', 'CUDA'] if use_gpu_relax else ['CPU']
```

Each platform gets up to 3 retry attempts with 1-second backoff, handling OpenCL context failures that can occur during long runs. The [`openmm_relax_subprocess()`](functions/pr_alternative_utils.py#L1575) function provides additional isolation by running relaxation in fresh processes to prevent cumulative OpenCL state issues.

### Memory Management

The implementation includes explicit cleanup of OpenMM objects and garbage collection to prevent memory accumulation across multiple relaxation calls:

```python
del positions, simulation, integrator, system, restraint_force, lj_rep_custom_force, fixer
gc.collect()
```

## FASPR Integration

The pipeline optionally integrates FASPR (Fast and Accurate Side-chain Packing with Rotamer library) for enhanced side-chain optimization:

**Preparation**: Creates heavy-atom PDB files using PDBFixer to ensure backbone completeness
**Execution**: Runs FASPR with timeout protection (900 seconds default)
**Post-processing**: Adds hydrogens and performs standardized minimization using [`_add_hydrogens_and_minimize()`](functions/pr_alternative_utils.py#L774)

The FASPR integration is controlled by the `use_faspr_repack=True` parameter and provides significant improvements in side-chain packing quality compared to minimization alone.

## Testing and Validation

The [`extras/test_openmm_relax.py`](extras/test_openmm_relax.py) script provides comprehensive testing capabilities:

**Single Run Testing**: Direct comparison between OpenMM and PyRosetta relaxation
**Performance Sweeping**: Grid search over platform configurations, MD settings, and ramp stages
**Metric Collection**: Detailed timing and energy reporting with JSON output support

The test script supports parameter sweeps across:
- Platform choices (CPU/GPU)
- MD step configurations
- Ramp stage variations (1-3 stages)
- Performance metric collection

## Configuration Parameters

The pipeline exposes numerous configuration options for fine-tuning:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `openmm_max_iterations` | 1000 | Maximum iterations per minimization stage |
| `openmm_ramp_force_tolerance_kj_mol_nm` | 2.0 | Force tolerance for ramp stages |
| `openmm_final_force_tolerance_kj_mol_nm` | 0.1 | Force tolerance for final stage |
| `restraint_k_kcal_mol_A2` | 3.0 | Backbone restraint strength |
| `md_steps_per_shake` | 1000 | MD steps per shake (first 2 stages only) |
| `lj_rep_base_k_kj_mol` | 10.0 | Base LJ repulsion strength |

## Debug and Monitoring

The pipeline provides comprehensive debugging capabilities through environment variables:

**`BINDCRAFT_DEBUG_PDBS=1`**: Saves intermediate structures at each processing stage:
- `.debug_deconcat.pdb`: After de-concatenation
- `.debug_pdbfixer.pdb`: After PDBFixer preparation  
- `.debug_post_initial_relax.pdb`: After OpenMM relaxation
- `.debug_post_faspr.pdb`: After FASPR repacking

**Performance Reporting**: Optional `perf_report` dictionary captures detailed timing and energy metrics for each stage, enabling performance analysis and optimization.

> [!TIP]
> The performance reporting system provides granular insights into each relaxation stage, including energy progression, minimization calls, and timing breakdowns, which are invaluable for pipeline optimization and troubleshooting.

## Integration Points

The OpenMM Relaxation Pipeline integrates seamlessly with the broader FreeBindCraft architecture:

**Input**: Accepts standard PDB files from ColabDesign or other sources
**Output**: Produces relaxed structures compatible with downstream scoring and analysis
**Environment**: Reads `BINDCRAFT_STARTING_PDB` and `BINDCRAFT_TARGET_CHAINS` for chain handling
**Compatibility**: Maintains API compatibility with PyRosetta's `pr_relax()` function

This pipeline represents a significant advancement in making high-quality protein structure relaxation accessible without proprietary dependencies while maintaining performance and accuracy comparable to commercial solutions.

For deeper understanding of the overall architecture, see [PyRosetta Bypass Architecture](6-pyrosetta-bypass-architecture), and for complementary open-source implementations, explore [FreeSASA Surface Analysis](8-freesasa-surface-analysis) and [Shape Complementarity with sc-rs](9-shape-complementarity-with-sc-rs).