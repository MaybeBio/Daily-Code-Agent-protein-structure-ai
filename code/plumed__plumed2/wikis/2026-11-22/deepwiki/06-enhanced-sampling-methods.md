# Enhanced Sampling Methods

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [CHANGES/v2.0.md](CHANGES/v2.0.md)
- [CHANGES/v2.1.md](CHANGES/v2.1.md)
- [CHANGES/v2.10.md](CHANGES/v2.10.md)
- [CHANGES/v2.11.md](CHANGES/v2.11.md)
- [CHANGES/v2.2.md](CHANGES/v2.2.md)
- [CHANGES/v2.3.md](CHANGES/v2.3.md)
- [CHANGES/v2.4.md](CHANGES/v2.4.md)
- [CHANGES/v2.5.md](CHANGES/v2.5.md)
- [CHANGES/v2.7.md](CHANGES/v2.7.md)
- [CHANGES/v2.8.md](CHANGES/v2.8.md)
- [CHANGES/v2.9.md](CHANGES/v2.9.md)
- [README.md](README.md)
- [VERSION.txt](VERSION.txt)
- [docker/.gitignore](docker/.gitignore)
- [docker/Dockerfile](docker/Dockerfile)

</details>



This document provides a comprehensive overview of the enhanced sampling methods implemented in PLUMED. Enhanced sampling methods help overcome energy barriers in molecular dynamics simulations, allowing for more efficient exploration of the conformational space and calculation of free energies. PLUMED offers a variety of these methods with different strengths and applications.

For implementation details on specific enhanced sampling methods, see their dedicated pages:
- [Metadynamics (3.1)](#3.1)
- [OPES (3.2)](#3.2)
- [DRR and eABF (3.3)](#3.3)
- [VES (3.4)](#3.4)

## Enhanced Sampling Methods Overview

Enhanced sampling methods in PLUMED are designed to accelerate the exploration of free energy landscapes by applying bias forces to selected collective variables. These methods overcome the limitations of standard molecular dynamics simulations, which can get trapped in local energy minima for extended periods.

```mermaid
flowchart TD
    subgraph "Enhanced Sampling Methods"
        MetaD["Metadynamics\n(MetaD, PBMetaD)"]
        OPES["On-the-fly Probability\nEnhanced Sampling\n(OPES)"]
        DRR["Dynamic Reference\nRestraining\n(DRR/eABF)"]
        VES["Variational Enhanced\nSampling\n(VES)"]
    end
    
    subgraph "Common Mechanisms"
        CV["Collective Variables"]
        Bias["Bias Potential"]
        FES["Free Energy Surface"]
    end
    
    CV --> Bias
    Bias --> FES
    
    MetaD --> Bias
    OPES --> Bias
    DRR --> Bias
    VES --> Bias
    
    style MetaD fill:#f9f9f9,stroke:#333,stroke-width:1px
    style OPES fill:#f9f9f9,stroke:#333,stroke-width:1px
    style DRR fill:#f9f9f9,stroke:#333,stroke-width:1px
    style VES fill:#f9f9f9,stroke:#333,stroke-width:1px
    style CV fill:#f9f9f9,stroke:#333,stroke-width:1px
    style Bias fill:#f9f9f9,stroke:#333,stroke-width:1px
    style FES fill:#f9f9f9,stroke:#333,stroke-width:1px
```

Sources: [src/bias/MetaD.cpp](). [src/bias/PBMetaD.cpp](). [src/opes/OPESmetad.cpp](). [src/opes/OPESexpanded.cpp](). [src/drr/DynamicReferenceRestraining.cpp]().

## Metadynamics

Metadynamics enhances sampling by adding a history-dependent bias potential composed of Gaussian functions to discourage the system from revisiting already sampled configurations. 

In standard metadynamics, the bias potential is given by:

$$V(\vec{s},t) = \sum_{ k \tau < t} W(k \tau) \exp\left(-\sum_{i=1}^{d} \frac{(s_i-s_i^{(0)}(k \tau))^2}{2\sigma_i^2}\right)$$

This bias gradually fills energy minima, pushing the system to explore new regions of the configurational space.

```mermaid
classDiagram
    Bias <|-- MetaD
    Bias <|-- PBMetaD
    Bias <|-- OPES_METAD
    Bias <|-- DRR
    
    class Bias {
        <<Abstract>>
        +calculate()
        +update()
    }
    
    class MetaD {
        -hills_
        -grid_
        +addGaussian()
        +calculate()
        +update()
    }
    
    class PBMetaD {
        -hills_[]
        -grids_[]
        +calculate()
        +update()
    }
    
    class OPES_METAD {
        -kernels_
        -compress()
        +calculate()
        +update()
    }
    
    class DRR {
        -fictNoPBC_
        -real_
        -fbias_
        +calculate()
        +update()
    }
```

Sources: [src/bias/MetaD.cpp:482-633](). [src/bias/PBMetaD.cpp:238-337](). [src/opes/OPESmetad.cpp:166-250](). [src/drr/DynamicReferenceRestraining.cpp:180-243]().

### Well-Tempered Metadynamics

A popular variant of metadynamics is well-tempered metadynamics, where the height of Gaussian hills decreases with time according to:

$$W(k\tau) = W_0 e^{-V(s,k\tau)/\Delta T}$$

This ensures that the bias potential converges more smoothly to the negative of the free energy.

### Multiple Walker Metadynamics

PLUMED also supports multiple walker approaches where several simulations (walkers) contribute to the same bias potential, enhancing convergence through collaborative sampling.

```mermaid
flowchart TD
    subgraph "Metadynamics Variants"
        Standard["Standard Metadynamics"]
        WellTemp["Well-Tempered\nMetadynamics"]
        PBM["Parallel Bias\nMetadynamics"]
        Multi["Multiple Walkers\nMetadynamics"]
        Transition["Transition-Tempered\nMetadynamics"]
    end
    
    subgraph "Implementation Components"
        Hills["Gaussian Hills\nRepresentation"]
        Grids["Grid Storage"]
        NList["Neighbor Lists"]
        Reweighting["Reweighting Tools"]
    end
    
    Standard --> Hills
    WellTemp --> Hills
    PBM --> Hills
    Multi --> Hills
    Transition --> Hills
    
    Hills --> Grids
    Grids --> NList
    Hills --> Reweighting
    
    style Standard fill:#f9f9f9,stroke:#333,stroke-width:1px
    style WellTemp fill:#f9f9f9,stroke:#333,stroke-width:1px
    style PBM fill:#f9f9f9,stroke:#333,stroke-width:1px
    style Multi fill:#f9f9f9,stroke:#333,stroke-width:1px
    style Transition fill:#f9f9f9,stroke:#333,stroke-width:1px
    style Hills fill:#f9f9f9,stroke:#333,stroke-width:1px
    style Grids fill:#f9f9f9,stroke:#333,stroke-width:1px
    style NList fill:#f9f9f9,stroke:#333,stroke-width:1px
    style Reweighting fill:#f9f9f9,stroke:#333,stroke-width:1px
```

Sources: [src/bias/MetaD.cpp:187-207](). [src/bias/MetaD.cpp:291-317](). [src/bias/PBMetaD.cpp:40-95](). [src/bias/PBMetaD.cpp:195-234]().

## On-the-fly Probability Enhanced Sampling (OPES)

OPES is a more recent enhanced sampling method that optimizes the bias on-the-fly through probability density estimation. Two main variants are implemented:

### OPES_METAD

This variant uses a metadynamics-like target distribution with the bias at step n given by:

$$V_n(\mathbf{s}) = (1-1/\gamma)\frac{1}{\beta}\log\left(\frac{P_n(\mathbf{s})}{Z_n}+\epsilon\right)$$

OPES_METAD aims to quickly get a coarse estimate of the full free energy surface and then refine its details. It uses a compression algorithm to limit the number of kernels.

### OPES_EXPANDED

This variant works with expanded ensembles, allowing simulation of multiple thermodynamic conditions. The bias is:

$$V_n(\mathbf{x})=-\frac{1}{\beta}\log \left(\frac{1}{N_{\{\lambda\}}}\sum_\lambda e^{-\Delta u_\lambda(\mathbf{x})+\beta\Delta F_n(\lambda)}\right)$$

This allows for sampling a range of temperatures, pressures, or other conditions within a single simulation.

```mermaid
flowchart TD
    subgraph "OPES Variants"
        OPES_M["OPES_METAD\n(Metadynamics-like target)"]
        OPES_E["OPES_EXPANDED\n(Expanded ensemble target)"]
        OPES_ME["OPES_METAD_EXPLORE\n(Exploration mode)"]
    end
    
    subgraph "Expansion Collective Variables"
        ECV_MT["ECV_MULTITHERMAL\n(Multiple temperatures)"]
        ECV_MTB["ECV_MULTITHERMAL_MULTIBARIC\n(Multiple temperatures & pressures)"]
        ECV_UL["ECV_UMBRELLAS_LINE\n(Umbrella sampling along line)"]
        ECV_UF["ECV_UMBRELLAS_FILE\n(Umbrella sampling from file)"]
    end
    
    OPES_E --> ECV_MT
    OPES_E --> ECV_MTB
    OPES_E --> ECV_UL
    OPES_E --> ECV_UF
    
    style OPES_M fill:#f9f9f9,stroke:#333,stroke-width:1px
    style OPES_E fill:#f9f9f9,stroke:#333,stroke-width:1px
    style OPES_ME fill:#f9f9f9,stroke:#333,stroke-width:1px
    style ECV_MT fill:#f9f9f9,stroke:#333,stroke-width:1px
    style ECV_MTB fill:#f9f9f9,stroke:#333,stroke-width:1px
    style ECV_UL fill:#f9f9f9,stroke:#333,stroke-width:1px
    style ECV_UF fill:#f9f9f9,stroke:#333,stroke-width:1px
```

Sources: [src/opes/OPESmetad.cpp:29-164](). [src/opes/OPESmetad.cpp:261-297](). [src/opes/OPESexpanded.cpp:32-113](). [src/opes/ECVmultiThermal.cpp](). [src/opes/ECVmultiThermalBaric.cpp:25-72](). [src/opes/ECVumbrellasLine.cpp](). [src/opes/ECVumbrellasFile.cpp]().

## Dynamic Reference Restraining (DRR)

DRR, also known as extended-system Adaptive Biasing Force (eABF), attaches fictitious variables to collective variables through springs. The bias force acts on the fictitious variables rather than directly on the collective variables.

For each collective variable \(ξ_i\), a fictitious variable \(λ_i\) is attached through a spring. The bias force on \(λ_i\) is the negative average spring force, enhancing the sampling of \(λ_i\):

$$F_{bias}(λ_i) = k(λ_i - \langle ξ_i \rangle_{λ_i})$$

DRR supports multiple estimators:
- Naïve (ABF) estimator: negative average spring force
- CZAR (Corrected z-averaged restraint) estimator
- UI (Umbrella Integration) estimator

```mermaid
flowchart LR
    subgraph "DRR/eABF Components"
        ABFGrid["ABFGrid"]
        CZAR["CZAR Estimator"]
        UI["UI Estimator"]
        Langevin["Extended Langevin\nDynamics"]
    end
    
    subgraph "DRR Implementation"
        drrMain["DynamicReferenceRestraining\nClass"]
        ABF["ABF on Fictitious\nVariables"]
        Biasforces["Bias Forces"]
        OutputFiles["Output Files\n(.drrstate, .grad, .count)"]
    end
    
    drrMain --> ABFGrid
    drrMain --> CZAR
    drrMain --> UI
    drrMain --> Langevin
    
    ABFGrid --> ABF
    CZAR --> Biasforces
    UI --> Biasforces
    Langevin --> Biasforces
    Biasforces --> OutputFiles
    
    style drrMain fill:#f9f9f9,stroke:#333,stroke-width:1px
    style ABFGrid fill:#f9f9f9,stroke:#333,stroke-width:1px
    style CZAR fill:#f9f9f9,stroke:#333,stroke-width:1px
    style UI fill:#f9f9f9,stroke:#333,stroke-width:1px
    style Langevin fill:#f9f9f9,stroke:#333,stroke-width:1px
    style ABF fill:#f9f9f9,stroke:#333,stroke-width:1px
    style Biasforces fill:#f9f9f9,stroke:#333,stroke-width:1px
    style OutputFiles fill:#f9f9f9,stroke:#333,stroke-width:1px
```

Sources: [src/drr/DynamicReferenceRestraining.cpp:45-95](). [src/drr/DRR.cpp:30-48](). [src/drr/DRR.cpp:77-113](). [src/drr/DRR.h:50-163]().

## Variational Enhanced Sampling (VES)

Variational Enhanced Sampling (VES) uses a variational approach to optimize bias potentials. It minimizes a functional related to the free energy to determine the optimal bias.

## Common Utilities for Enhanced Sampling

Several utilities and tools are shared across enhanced sampling methods:

### Grid System

Grid-based storage of bias potentials is a crucial optimization in many enhanced sampling methods, as it reduces the computational cost of evaluating the bias:

```mermaid
classDiagram
    class GridBase {
        <<Abstract>>
        +std::vector<double> min_
        +std::vector<double> max_
        +std::vector<double> dx_
        +std::vector<unsigned> nbin_
        +getIndex()
        +getValue()
        +setValue()
        +getGridSpacing()
    }
    
    GridBase <|-- Grid
    GridBase <|-- SparseGrid
    
    class Grid {
        -std::vector<double> grid_
        +getValue()
        +setValue()
        +getBilinearInterpolation()
    }
    
    class SparseGrid {
        -std::map<index_t, double> map_
        +getValue()
        +setValue()
        +getSize()
    }
```

Sources: [src/tools/Grid.h:91-140](). [src/tools/Grid.h:201-379](). [src/tools/Grid.cpp:22-40]().

### Hills and Kernel Functions

Gaussian hills and other kernel functions are fundamental building blocks in metadynamics and OPES:

```mermaid
flowchart TD
    subgraph "Kernel Functions"
        Gaussian["Gaussian Kernels"]
        Stretched["Stretched Gaussians"]
        Periodic["Periodic Kernels"]
        Cutoff["Kernel Cutoffs"]
    end
    
    subgraph "Metadynamics Hills"
        AddHill["Add Hill\naddGaussian()"]
        EvalHill["Evaluate Hill\nevaluateGaussian()"]
        Compress["Compress Hills\nmergeKernels()"]
    end
    
    Gaussian --> AddHill
    Stretched --> EvalHill
    Periodic --> EvalHill
    Cutoff --> Compress
    
    style Gaussian fill:#f9f9f9,stroke:#333,stroke-width:1px
    style Stretched fill:#f9f9f9,stroke:#333,stroke-width:1px
    style Periodic fill:#f9f9f9,stroke:#333,stroke-width:1px
    style Cutoff fill:#f9f9f9,stroke:#333,stroke-width:1px
    style AddHill fill:#f9f9f9,stroke:#333,stroke-width:1px
    style EvalHill fill:#f9f9f9,stroke:#333,stroke-width:1px
    style Compress fill:#f9f9f9,stroke:#333,stroke-width:1px
```

Sources: [src/bias/MetaD.cpp:482-534](). [src/opes/OPESmetad.cpp:202-215]().

### Post-Processing Tools

The `sum_hills` and `drr_tool` utilities provide essential post-processing capabilities:

| Tool | Purpose | Key Features |
|------|---------|--------------|
| `sum_hills` | Process HILLS files from metadynamics | - Integrate bias potential<br>- Generate free energy surface<br>- Calculate multiple dimensionalities |
| `drr_tool` | Process DRR output files | - Extract gradients and counts<br>- Merge windows<br>- Calculate force field divergence |

Sources: [src/function/FuncSumHills.cpp:37-49](). [src/cltools/SumHills.cpp](). [src/drr/drrtool.cpp:40-67]().

## Summary of Enhanced Sampling Implementations

PLUMED provides a comprehensive set of enhanced sampling methods, each with unique strengths and appropriate use cases:

| Method | Key Class | Use Cases | Key Features |
|--------|-----------|-----------|--------------|
| Metadynamics | `MetaD` | - Free energy calculations<br>- Exploring unknown landscapes | - Well-tempered variant<br>- Multiple walkers<br>- Grid acceleration |
| Parallel Bias MetaD | `PBMetaD` | - High-dimensional systems | - Parallel mono-dimensional biases<br>- Partitioned families |
| OPES | `OPESmetad`,<br>`OPESexpanded` | - Fast exploration<br>- Multiple thermodynamic states | - Kernel compression<br>- Multiple expanded variables |
| DRR/eABF | `DynamicReferenceRestraining` | - More direct FES estimation | - Various estimators (CZAR, UI)<br>- Integrated with mainstream MD codes |
| VES | | - Complex target distributions | - Variational approach to bias optimization |

Sources: [src/bias/MetaD.cpp](). [src/bias/PBMetaD.cpp](). [src/opes/OPESmetad.cpp](). [src/opes/OPESexpanded.cpp](). [src/drr/DynamicReferenceRestraining.cpp]().

These enhanced sampling methods enable the efficient calculation of free energy surfaces and the exploration of complex energy landscapes in molecular systems, which would be prohibitively expensive with standard molecular dynamics.

---