# PDL1 Benchmark Results

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [performance_data/pdl1_miniprotein/PDL1-freebindcraft.zip](performance_data/pdl1_miniprotein/PDL1-freebindcraft.zip)
- [performance_data/pdl1_miniprotein/PDL1-pyrosetta.zip](performance_data/pdl1_miniprotein/PDL1-pyrosetta.zip)
- [performance_data/pdl1_miniprotein/README.md](performance_data/pdl1_miniprotein/README.md)
- [performance_data/pdl1_miniprotein/freebindcraft_rosetta_rescore-relax.xlsx](performance_data/pdl1_miniprotein/freebindcraft_rosetta_rescore-relax.xlsx)
- [performance_data/pdl1_miniprotein/pdl1_final_design_stats_freebindcraft.csv](performance_data/pdl1_miniprotein/pdl1_final_design_stats_freebindcraft.csv)

</details>



This document presents quantitative performance and quality comparisons between traditional BindCraft (with PyRosetta) and FreeBindCraft (PyRosetta-free) pipelines using the PDL1 miniprotein design benchmark. The analysis covers runtime performance, trajectory efficiency, design quality metrics, and cross-validation through Rosetta rescoring.

For system architecture overview, see [System Architecture](#1.1). For PyRosetta-free implementation details, see [PyRosetta-Free Alternatives](#4.1).

## Benchmark Overview

The PDL1 miniprotein benchmark provides a direct head-to-head comparison using identical target structures, filter settings, and hardware configurations. Both pipelines utilized the `default_4stage_multimer` advanced settings and default filter thresholds to generate 101 accepted designs each.

### Benchmark Configuration

```mermaid
flowchart TD
    subgraph "Benchmark Setup"
        Target["PDL1 Target<br/>Original BindCraft Example"]
        Hardware["B200-class GPU<br/>Single Node"]
        Settings["default_4stage_multimer<br/>Default Filters"]
    end
    
    subgraph "Traditional Pipeline"
        TP_CMD["bindcraft.py<br/>PyRosetta Enabled"]
        TP_RELAX["PyRosetta FastRelax<br/>CPU-based"]
        TP_METRICS["Rosetta Interface Metrics<br/>Native Scoring"]
        TP_RESULTS["101 Accepted Designs<br/>144 Trajectories<br/>33.19h Runtime"]
    end
    
    subgraph "FreeBindCraft Pipeline"
        FB_CMD["bindcraft.py<br/>--no-pyrosetta Flag"]
        FB_RELAX["OpenMM Relaxation<br/>GPU-accelerated"]
        FB_METRICS["FreeSASA + Biopython<br/>Open-source Metrics"]
        FB_RESULTS["101 Accepted Designs<br/>91 Trajectories<br/>12.25h Runtime"]
    end
    
    Target --> TP_CMD
    Target --> FB_CMD
    Hardware --> TP_CMD
    Hardware --> FB_CMD
    Settings --> TP_CMD
    Settings --> FB_CMD
    
    TP_CMD --> TP_RELAX
    TP_RELAX --> TP_METRICS
    TP_METRICS --> TP_RESULTS
    
    FB_CMD --> FB_RELAX
    FB_RELAX --> FB_METRICS
    FB_METRICS --> FB_RESULTS
    
    FB_RESULTS --> RESCORE["Rosetta Rescoring<br/>Cross-validation"]
```

Sources: [performance_data/pdl1_miniprotein/README.md:16-23]()

## Performance Comparison Results

The FreeBindCraft pipeline demonstrated significant performance improvements in both trajectory efficiency and wall-clock runtime while maintaining equivalent design quality.

### Runtime and Efficiency Metrics

| Metric | Traditional BindCraft | FreeBindCraft | Improvement |
|--------|----------------------|---------------|-------------|
| Accepted designs | 101 | 101 | Equivalent |
| Trajectories needed | 144 | 91 | 37% fewer |
| Runtime (B200 GPU) | 33.19 h | 12.25 h | 63% faster |
| Average ipTM | 0.785 | 0.792 | Equivalent |

### Performance Analysis Diagram

```mermaid
graph TB
    subgraph "Trajectory Efficiency"
        TE_TRAD["Traditional BindCraft<br/>144 trajectories"]
        TE_FREE["FreeBindCraft<br/>91 trajectories"]
        TE_IMPROVEMENT["37% Reduction<br/>53 fewer trajectories"]
        
        TE_TRAD --> TE_IMPROVEMENT
        TE_FREE --> TE_IMPROVEMENT
    end
    
    subgraph "Runtime Performance"
        RT_TRAD["Traditional BindCraft<br/>33.19 hours"]
        RT_FREE["FreeBindCraft<br/>12.25 hours"]
        RT_IMPROVEMENT["63% Faster<br/>20.94 hour savings"]
        
        RT_TRAD --> RT_IMPROVEMENT
        RT_FREE --> RT_IMPROVEMENT
    end
    
    subgraph "Quality Metrics"
        QM_TRAD["Traditional ipTM<br/>0.785 average"]
        QM_FREE["FreeBindCraft ipTM<br/>0.792 average"]
        QM_RESULT["Equivalent Quality<br/>0.007 difference"]
        
        QM_TRAD --> QM_RESULT
        QM_FREE --> QM_RESULT
    end
    
    subgraph "Performance Drivers"
        PD_GPU["GPU-accelerated<br/>OpenMM Relaxation"]
        PD_METRICS["Faster Metric<br/>Calculations"]
        PD_PIPELINE["Streamlined<br/>Processing"]
    end
    
    PD_GPU --> RT_IMPROVEMENT
    PD_METRICS --> RT_IMPROVEMENT
    PD_PIPELINE --> TE_IMPROVEMENT
```

Sources: [performance_data/pdl1_miniprotein/README.md:24-32]()

## Cross-Validation Through Rosetta Rescoring

To assess the compatibility of FreeBindCraft designs with traditional Rosetta-based evaluation criteria, all 101 accepted designs underwent PyRosetta FastRelax followed by standard Rosetta interface metric calculations.

### Rescoring Results

```mermaid
flowchart LR
    subgraph "FreeBindCraft Designs"
        FB_DESIGNS["101 Accepted Designs<br/>OpenMM Relaxed"]
    end
    
    subgraph "Rosetta Rescoring Process"
        RESCORE_RELAX["PyRosetta FastRelax<br/>CPU-based Refinement"]
        RESCORE_METRICS["Rosetta Interface Metrics<br/>Traditional Scoring"]
        RESCORE_FILTERS["Traditional Filter<br/>Threshold Assessment"]
    end
    
    subgraph "Rescoring Outcomes"
        PASS["58 Designs Pass<br/>~58% Success Rate"]
        FAIL_HB["Hydrogen Bond<br/>Network Failures<br/>~67% of failures"]
        FAIL_OTHER["Surface Hydrophobicity<br/>Shape Complementarity<br/>~33% of failures"]
    end
    
    FB_DESIGNS --> RESCORE_RELAX
    RESCORE_RELAX --> RESCORE_METRICS
    RESCORE_METRICS --> RESCORE_FILTERS
    
    RESCORE_FILTERS --> PASS
    RESCORE_FILTERS --> FAIL_HB
    RESCORE_FILTERS --> FAIL_OTHER
```

### Failure Analysis

The 42% of designs that failed traditional Rosetta filters showed specific patterns:

- **Hydrogen Bond Networks (67% of failures)**: Differences in relaxation protocols and geometric optimization between OpenMM and PyRosetta FastRelax
- **Surface Properties (33% of failures)**: Methodological variance between area-weighted SASA calculations and Rosetta's native SASA implementation
- **Shape Complementarity**: Differences between `sc-rs` tool calculations and Rosetta's native shape complementarity scoring

Sources: [performance_data/pdl1_miniprotein/README.md:37-38]()

## Technical Implementation Differences

The performance improvements stem from key architectural differences between the pipelines that affect computational efficiency and throughput.

### Pipeline Architecture Comparison

```mermaid
graph TD
    subgraph "Traditional BindCraft Pipeline"
        TRAD_DESIGN["ColabDesign<br/>AF2 + MPNN"]
        TRAD_RELAX["pyrosetta_utils.py<br/>FastRelax CPU"]
        TRAD_SASA["PyRosetta SASA<br/>Native Calculations"]
        TRAD_SC["Rosetta ShapeComp<br/>Native Scoring"]
        TRAD_INTERFACE["PyRosetta Interface<br/>Comprehensive Metrics"]
    end
    
    subgraph "FreeBindCraft Pipeline"
        FREE_DESIGN["ColabDesign<br/>AF2 + MPNN"]
        FREE_RELAX["pr_alternative_utils.py<br/>OpenMM GPU"]
        FREE_SASA["FreeSASA + Biopython<br/>Area-weighted SASA"]
        FREE_SC["sc-rs Tool<br/>Shape Complementarity"]
        FREE_INTERFACE["Biopython Analysis<br/>Interface Detection"]
    end
    
    subgraph "Performance Impact"
        PERF_RELAX["GPU Acceleration<br/>10-100x Speedup"]
        PERF_METRICS["Streamlined Scoring<br/>Reduced I/O Overhead"]
        PERF_PIPELINE["Fewer Dependencies<br/>Elimination of Rosetta Overhead"]
    end
    
    TRAD_DESIGN --> FREE_DESIGN
    TRAD_RELAX --> FREE_RELAX
    TRAD_SASA --> FREE_SASA
    TRAD_SC --> FREE_SC
    TRAD_INTERFACE --> FREE_INTERFACE
    
    FREE_RELAX --> PERF_RELAX
    FREE_SASA --> PERF_METRICS
    FREE_INTERFACE --> PERF_PIPELINE
```

### Key Performance Drivers

1. **GPU-Accelerated Relaxation**: OpenMM utilizes GPU hardware for molecular dynamics, providing 10-100x speedup over CPU-based PyRosetta FastRelax
2. **Streamlined Metric Calculations**: Direct calculation of interface metrics without Rosetta's complex pose management overhead
3. **Reduced I/O Operations**: Elimination of intermediate PDB file generation and Rosetta score file parsing
4. **Memory Efficiency**: Lower memory footprint due to absence of PyRosetta's extensive data structures

Sources: [performance_data/pdl1_miniprotein/README.md:35-36](), [performance_data/pdl1_miniprotein/README.md:41-42]()

## Design Quality Assessment

Both pipelines produced designs with equivalent AlphaFold confidence scores, indicating similar structural quality and binding interface geometry.

### Quality Metrics Distribution

```mermaid
graph LR
    subgraph "ipTM Score Comparison"
        IPTM_TRAD["Traditional BindCraft<br/>Mean: 0.785<br/>N: 101"]
        IPTM_FREE["FreeBindCraft<br/>Mean: 0.792<br/>N: 101"]
        IPTM_DELTA["Difference: +0.007<br/>Statistically Equivalent"]
    end
    
    subgraph "Design Archive Outputs"
        ARCH_TRAD["PDL1-pyrosetta.zip<br/>101 PDB Structures<br/>Rosetta Refined"]
        ARCH_FREE["PDL1-freebindcraft.zip<br/>101 PDB Structures<br/>OpenMM Refined"]
    end
    
    IPTM_TRAD --> IPTM_DELTA
    IPTM_FREE --> IPTM_DELTA
    
    IPTM_TRAD --> ARCH_TRAD
    IPTM_FREE --> ARCH_FREE
```

The equivalent ipTM scores demonstrate that FreeBindCraft's alternative relaxation and scoring protocols maintain design quality while achieving substantial performance improvements. The minor differences in Rosetta rescoring reflect methodological variance rather than fundamental quality differences.

Sources: [performance_data/pdl1_miniprotein/README.md:26-32](), [performance_data/pdl1_miniprotein/PDL1-freebindcraft.zip:1-50](), [performance_data/pdl1_miniprotein/PDL1-pyrosetta.zip:1-50]()

## Interpretation and Implications

The PDL1 benchmark demonstrates that FreeBindCraft's PyRosetta-free pipeline achieves:

- **Superior Throughput**: 63% runtime reduction and 37% fewer required trajectories
- **Equivalent Quality**: Comparable ipTM scores indicating similar AlphaFold confidence
- **Reasonable Cross-Platform Compatibility**: 58% of designs satisfy traditional Rosetta filter criteria
- **GPU Hardware Utilization**: Effective leveraging of modern accelerated computing infrastructure

The performance gains primarily result from GPU acceleration of relaxation protocols and elimination of computational overhead associated with PyRosetta's comprehensive but resource-intensive implementation. Quality equivalence validates the alternative scoring methodologies while highlighting areas where methodological differences affect cross-platform evaluation.

Sources: [performance_data/pdl1_miniprotein/README.md:33-43]()

---