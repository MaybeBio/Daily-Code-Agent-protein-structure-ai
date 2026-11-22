# Integrative Modeling

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [regtest/isdb/rt-bayesgje/BIAS.0.reference](regtest/isdb/rt-bayesgje/BIAS.0.reference)
- [regtest/isdb/rt-bayesgje/BIAS.1.reference](regtest/isdb/rt-bayesgje/BIAS.1.reference)
- [regtest/isdb/rt-bayesspe/BIAS.0.reference](regtest/isdb/rt-bayesspe/BIAS.0.reference)
- [regtest/isdb/rt-bayesspe/BIAS.1.reference](regtest/isdb/rt-bayesspe/BIAS.1.reference)
- [regtest/isdb/rt-emmi-out-mpi/deriva.reference](regtest/isdb/rt-emmi-out-mpi/deriva.reference)
- [regtest/isdb/rt-emmi-out/deriva.reference](regtest/isdb/rt-emmi-out/deriva.reference)
- [regtest/isdb/rt-pre-mi/COLVAR.reference](regtest/isdb/rt-pre-mi/COLVAR.reference)
- [regtest/isdb/rt-rdc-mi/BIAS.0.new.reference](regtest/isdb/rt-rdc-mi/BIAS.0.new.reference)
- [regtest/isdb/rt-rdc-mi/BIAS.0.old.reference](regtest/isdb/rt-rdc-mi/BIAS.0.old.reference)
- [regtest/isdb/rt-rdc-mi/BIAS.1.new.reference](regtest/isdb/rt-rdc-mi/BIAS.1.new.reference)
- [regtest/isdb/rt-rdc-mi/BIAS.1.old.reference](regtest/isdb/rt-rdc-mi/BIAS.1.old.reference)
- [src/isdb/CS2Backbone.cpp](src/isdb/CS2Backbone.cpp)
- [src/isdb/Caliber.cpp](src/isdb/Caliber.cpp)
- [src/isdb/EMMI.cpp](src/isdb/EMMI.cpp)
- [src/isdb/FretEfficiency.cpp](src/isdb/FretEfficiency.cpp)
- [src/isdb/Jcoupling.cpp](src/isdb/Jcoupling.cpp)
- [src/isdb/Metainference.cpp](src/isdb/Metainference.cpp)
- [src/isdb/MetainferenceBase.cpp](src/isdb/MetainferenceBase.cpp)
- [src/isdb/MetainferenceBase.h](src/isdb/MetainferenceBase.h)
- [src/isdb/NOE.cpp](src/isdb/NOE.cpp)
- [src/isdb/PRE.cpp](src/isdb/PRE.cpp)
- [src/isdb/RDC.cpp](src/isdb/RDC.cpp)
- [src/isdb/Rescale.cpp](src/isdb/Rescale.cpp)
- [src/isdb/SAXS.cpp](src/isdb/SAXS.cpp)
- [src/isdb/Select.cpp](src/isdb/Select.cpp)
- [src/isdb/Selector.cpp](src/isdb/Selector.cpp)

</details>



## Overview

Integrative Modeling in PLUMED refers to the set of systems and modules that enable the direct use of experimental data as restraints or biases in molecular simulations. This is achieved by combining simulation data with experimental observables, allowing for more accurate and experimentally consistent structural models.

The main architectural cluster for integrative modeling is the ISDB (Integrative Structural Biology) module, which provides a unified framework for incorporating a wide range of experimental data types. The ISDB module is implemented as a set of classes and actions, each corresponding to a specific experimental observable or method.

For documentation on additional specialized modules (e.g., membrane fusion, SASA), see page [4.2].

Sources: [src/isdb/MetainferenceBase.cpp](), [src/isdb/MetainferenceBase.h]()

## Metainference Framework

The Metainference framework is the core system for Bayesian integration of experimental data with molecular simulations in PLUMED. It is implemented as a set of C++ classes, with `MetainferenceBase` providing the main logic for error modeling, parameter sampling, and ensemble averaging.

### Diagram: ISDB Metainference Class Relationships

```mermaid
classDiagram
    class "ActionWithValue"
    class "ActionAtomistic"
    class "ActionWithArguments"
    class "MetainferenceBase" {
        - doscore_: bool
        - sigma_: vector~double~
        - sigma_mean2_: vector~double~
        - scale_: double
        - offset_: double
        + calculate()
        + doMonteCarlo()
    }
    class "Metainference"
    class "SAXS"
    class "CS2Backbone"
    class "RDC"
    class "NOE"
    class "EMMI"
    class "JCoupling"
    class "PRE"

    "ActionWithValue" <|-- "MetainferenceBase"
    "ActionAtomistic" <|-- "MetainferenceBase"
    "ActionWithArguments" <|-- "MetainferenceBase"

    "MetainferenceBase" <|-- "Metainference"
    "MetainferenceBase" <|-- "SAXS"
    "MetainferenceBase" <|-- "CS2Backbone"
    "MetainferenceBase" <|-- "RDC"
    "MetainferenceBase" <|-- "NOE"
    "MetainferenceBase" <|-- "EMMI"
    "MetainferenceBase" <|-- "JCoupling"
    "MetainferenceBase" <|-- "PRE"
```

Sources: [src/isdb/MetainferenceBase.h](), [src/isdb/Metainference.cpp](), [src/isdb/SAXS.cpp](), [src/isdb/CS2Backbone.cpp](), [src/isdb/RDC.cpp](), [src/isdb/NOE.cpp](), [src/isdb/EMMI.cpp](), [src/isdb/Jcoupling.cpp](), [src/isdb/PRE.cpp]()

The Metainference framework supports:
- Explicit modeling of random and systematic errors
- Bayesian parameter estimation (e.g., error, scale, offset)
- Ensemble averaging over multiple replicas
- Integration with a variety of experimental data types

Sources: [src/isdb/MetainferenceBase.cpp](), [src/isdb/Metainference.cpp]()

### Core Components and Code Mapping

The `MetainferenceBase` class (see [src/isdb/MetainferenceBase.h]()) is the main base class for all ISDB actions that support metainference. It provides:

- Management of error parameters (`sigma_`, `sigma_mean2_`)
- Scaling and offset logic (`scale_`, `offset_`)
- Monte Carlo sampling for parameter optimization (`doMonteCarlo`)
- Replica averaging for ensemble simulations

Each experimental observable is implemented as a derived class (e.g., `SAXS`, `CS2Backbone`, `RDC`, `NOE`, `EMMI`, `JCoupling`, `PRE`), which provides the forward model and observable-specific logic.

#### Diagram: Mapping Experimental Data Types to Code Entities

```mermaid
flowchart TD
    "MetainferenceBase.h"["MetainferenceBase.h"] -->|"base class for"| "SAXS.cpp"["SAXS"]
    "MetainferenceBase.h" -->|"base class for"| "CS2Backbone.cpp"["CS2Backbone"]
    "MetainferenceBase.h" -->|"base class for"| "RDC.cpp"["RDC"]
    "MetainferenceBase.h" -->|"base class for"| "NOE.cpp"["NOE"]
    "MetainferenceBase.h" -->|"base class for"| "EMMI.cpp"["EMMI"]
    "MetainferenceBase.h" -->|"base class for"| "Jcoupling.cpp"["JCoupling"]
    "MetainferenceBase.h" -->|"base class for"| "PRE.cpp"["PRE"]
```

Sources: [src/isdb/MetainferenceBase.h](), [src/isdb/SAXS.cpp](), [src/isdb/CS2Backbone.cpp](), [src/isdb/RDC.cpp](), [src/isdb/NOE.cpp](), [src/isdb/EMMI.cpp](), [src/isdb/Jcoupling.cpp](), [src/isdb/PRE.cpp]()

## Supported Experimental Data Types

PLUMED's integrative modeling supports a range of experimental data types, each implemented as a dedicated class/action. Below is a mapping of data types to code entities and a summary of their computational workflow.

### SAXS/SANS (Small-Angle X-ray/Neutron Scattering)

- **Code:** `SAXS` class ([src/isdb/SAXS.cpp]())
- **Features:** Atomistic, MARTINI, and ONEBEAD representations; GPU acceleration via ArrayFire; support for experimental intensity normalization and solvation corrections.

#### Diagram: SAXS/SANS Data Flow and Code Entities

```mermaid
flowchart TD
    "SAXS.cpp"["SAXS.cpp"] -->|"Implements"| "SAXS"["SAXS Action"]
    "SAXS" -->|"Uses"| "MetainferenceBase"
    "SAXS" -->|"Handles"| "FormFactors"
    "SAXS" -->|"Handles"| "QValues"
    "SAXS" -->|"Handles"| "ExperimentalData"
    "SAXS" -->|"Supports"| "GPU"
    "SAXS" -->|"Supports"| "ONEBEAD"
    "SAXS" -->|"Supports"| "MARTINI"
```

Sources: [src/isdb/SAXS.cpp:66-156](), [src/isdb/SAXS.cpp:242-435]()

### Chemical Shifts (CS2Backbone)

- **Code:** `CS2Backbone` class ([src/isdb/CS2Backbone.cpp]())
- **Features:** CamShift-based prediction, support for multiple nuclei, integration with experimental data files.

#### Diagram: CS2Backbone Data Flow

```mermaid
flowchart TD
    "CS2Backbone.cpp"["CS2Backbone.cpp"] -->|"Implements"| "CS2Backbone"["CS2Backbone Action"]
    "CS2Backbone" -->|"Uses"| "MetainferenceBase"
    "CS2Backbone" -->|"Reads"| "camshift.db"
    "CS2Backbone" -->|"Reads"| "PDB Template"
    "CS2Backbone" -->|"Compares"| "ExperimentalShifts"
```

Sources: [src/isdb/CS2Backbone.cpp:47-151](), [src/isdb/CS2Backbone.cpp:437-476]()

### RDC (Residual Dipolar Coupling)

- **Code:** `RDC` class ([src/isdb/RDC.cpp]())
- **Features:** Direct calculation and SVD-based methods; supports ensemble averaging and metainference.

Sources: [src/isdb/RDC.cpp:36-129](), [src/isdb/RDC.cpp:173-217]()

### NOE (Nuclear Overhauser Effect)

- **Code:** `NOE` class ([src/isdb/NOE.cpp]())
- **Features:** Calculation of NOE intensities as sums of 1/r^6 over atom pairs; supports ambiguous and equivalent groups.

Sources: [src/isdb/NOE.cpp:31-62]()

### EMMI (Cryo-EM Fitting)

- **Code:** `EMMI` class ([src/isdb/EMMI.cpp]())
- **Features:** Multi-scale Bayesian fitting to cryo-EM density maps using Gaussian Mixture Models (GMMs).

#### Diagram: EMMI Workflow and Code Entities

```mermaid
flowchart TD
    "EMMI.cpp"["EMMI.cpp"] -->|"Implements"| "EMMI"["EMMI Action"]
    "EMMI" -->|"Reads"| "GMM_FILE"
    "EMMI" -->|"Calculates"| "Overlap"
    "EMMI" -->|"Scores"| "BayesianScore"
    "EMMI" -->|"Applies"| "BiasForce"
```

Sources: [src/isdb/EMMI.cpp:42-107](), [src/isdb/EMMI.cpp:157-259]()

### J-Coupling

- **Code:** `JCoupling` class ([src/isdb/Jcoupling.cpp]())
- **Features:** Karplus relation for dihedral angle-dependent scalar couplings; supports multiple coupling types.

Sources: [src/isdb/Jcoupling.cpp:30-84]()

### PRE (Paramagnetic Relaxation Enhancement)

- **Code:** `PRE` class ([src/isdb/PRE.cpp]())
- **Features:** Calculation of PRE intensity ratios based on distances to a paramagnetic center.

Sources: [src/isdb/PRE.cpp:31-66]()


## Workflow Integration

The typical workflow for integrative modeling in PLUMED involves the following steps:

#### Diagram: Integrative Modeling Workflow

```mermaid
flowchart TD
    "PrepareExperimentalData"["Prepare Experimental Data (format, scale)"] --> "SetupSimulation"["Setup Simulation System (PDB, forcefield)"]
    "SetupSimulation" --> "DefineCVs"["Define Collective Variables (SAXS, CS2Backbone, RDC, etc.)"]
    "DefineCVs" --> "ConfigureMetainference"["Configure Metainference (parameters, priors)"]
    "ConfigureMetainference" --> "RunSimulation"["Run Simulation with Experimental Bias"]
    "RunSimulation" --> "AnalyzeResults"["Analyze Results (reweighting, validation)"]
```

A typical PLUMED input for integrative modeling includes:

- Calculation of experimental observables (e.g., `CS2BACKBONE`, `SAXS`)
- Metainference or bias setup (e.g., `METAINFERENCE ...`)
- Application of bias (e.g., `BIASVALUE ARG=meta.score`)

Sources: [src/isdb/Metainference.cpp](), [src/isdb/CS2Backbone.cpp](), [src/isdb/SAXS.cpp]()

## Ensemble Averaging

PLUMED's integrative modeling supports ensemble averaging, where experimental observables are averaged over multiple simulation replicas before comparison to experimental data. This is essential for modeling flexible or heterogeneous systems.

#### Diagram: Ensemble Averaging in Metainference

```mermaid
flowchart TD
    "Replica1"["Replica 1"] --> "ForwardModel"["Forward Model Calculation"]
    "Replica2"["Replica 2"] --> "ForwardModel"
    "ReplicaN"["Replica N"] --> "ForwardModel"
    "ForwardModel" --> "EnsembleAveraging"["Ensemble Averaging"]
    "EnsembleAveraging" --> "CompareToExperiment"["Compare to Experimental Data"]
    "CompareToExperiment" --> "BiasUpdate"["Bias Update / Force Application"]
    "BiasUpdate" --> "Replica1"
    "BiasUpdate" --> "Replica2"
    "BiasUpdate" --> "ReplicaN"
```

Sources: [src/isdb/MetainferenceBase.cpp](), [src/isdb/Metainference.cpp]()

## Statistical Treatment of Errors

The Metainference framework provides explicit modeling of multiple error sources:

- **Forward model error:** Uncertainty in the prediction of observables from structure
- **Measurement error:** Uncertainty in the experimental data itself
- **Ensemble error:** Uncertainty due to finite sampling (number of replicas)

Supported noise models (see [src/isdb/MetainferenceBase.cpp:184-196](), [src/isdb/Metainference.cpp:154-196]()):

| Noise Model | Description |
|-------------|-------------|
| GAUSS       | Single Gaussian error parameter for all data points |
| MGAUSS      | Independent Gaussian error for each data point      |
| OUTLIERS    | Long-tailed Gaussian for outlier handling          |
| MOUTLIERS   | Multiple long-tailed Gaussians                     |
| GENERIC     | General model with separate error terms for different sources |

Sources: [src/isdb/MetainferenceBase.cpp:184-196](), [src/isdb/Metainference.cpp:154-196]()

## Conclusion

The Integrative Modeling capabilities in PLUMED provide a powerful framework for incorporating experimental data into molecular simulations. The Metainference approach, with its rigorous Bayesian treatment of errors, allows for meaningful integration of diverse data sources while accounting for the inherent uncertainties in both experiments and simulations.

By combining computational models with experimental constraints, researchers can develop more accurate and reliable structural models, especially for systems that are challenging to characterize by a single method alone.

---