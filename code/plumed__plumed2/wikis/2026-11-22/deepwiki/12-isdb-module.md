# ISDB Module

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



The ISDB (Integrative Structural Biology) module in PLUMED provides a framework for integrating experimental data into molecular simulations. It enables the use of diverse experimental measurements as restraints or biases, supporting more accurate and physically consistent modeling of biomolecular systems.

## Overview

The ISDB module is designed to:

- Incorporate experimental data as restraints or biases in molecular simulations.
- Handle noise and uncertainty in experimental measurements using Bayesian and ensemble-based approaches.
- Support ensemble/replica-averaged simulations for heterogeneous systems.
- Interface with a wide range of experimental data types, including NMR, SAXS/SANS, cryo-EM, and more.

### ISDB System Architecture

**ISDB Class Hierarchy and Key Entities**

```mermaid
classDiagram
    class "Action"
    class "ActionAtomistic"
    class "ActionWithArguments"
    class "ActionWithValue"
    class "MetainferenceBase" {
        +bool doscore_
        +std::vector<double> sigma_
        +std::vector<double> sigma_mean2_
        +calculate()
        +update()
        +doMonteCarlo()
    }
    class "Metainference" {
        +calculate()
        +update()
    }
    class "SAXS"
    class "CS2Backbone"
    class "RDC"
    class "NOE"
    class "PRE"
    class "JCoupling"
    class "EMMI"
    class "Caliber"
    class "Selector"
    class "Rescale"
    class "Select"

    "Action" <|-- "ActionAtomistic"
    "Action" <|-- "ActionWithArguments"
    "Action" <|-- "ActionWithValue"
    "ActionAtomistic" <|-- "MetainferenceBase"
    "ActionWithArguments" <|-- "MetainferenceBase"
    "ActionWithValue" <|-- "MetainferenceBase"
    "MetainferenceBase" <|-- "Metainference"
    "MetainferenceBase" <|-- "SAXS"
    "MetainferenceBase" <|-- "CS2Backbone"
    "MetainferenceBase" <|-- "RDC"
    "MetainferenceBase" <|-- "NOE"
    "MetainferenceBase" <|-- "PRE"
    "MetainferenceBase" <|-- "JCoupling"
    "MetainferenceBase" <|-- "EMMI"
    "Caliber" --|> "Action"
    "Selector" --|> "Action"
    "Rescale" --|> "Action"
    "Select" --|> "Action"
```

Sources: [src/isdb/MetainferenceBase.h:22-544](), [src/isdb/Metainference.cpp:22-2285](), [src/isdb/SAXS.cpp:22-1400](), [src/isdb/RDC.cpp:22-180]()

## Experimental Data Integration

The ISDB module provides actions for integrating a variety of experimental data types into molecular simulations. Each data type is implemented as a dedicated class, typically inheriting from `MetainferenceBase`, and is registered as a PLUMED action.

**Mapping Experimental Data Types to Code Entities**

```mermaid
flowchart TD
    subgraph "ISDB Module"
        "MetainferenceBase"
        "Metainference"
        "SAXS"
        "CS2Backbone"
        "RDC"
        "NOE"
        "PRE"
        "JCoupling"
        "EMMI"
        "Caliber"
        "Selector"
        "Rescale"
        "Select"
    end

    "MetainferenceBase" --> "SAXS"
    "MetainferenceBase" --> "CS2Backbone"
    "MetainferenceBase" --> "RDC"
    "MetainferenceBase" --> "NOE"
    "MetainferenceBase" --> "PRE"
    "MetainferenceBase" --> "JCoupling"
    "MetainferenceBase" --> "EMMI"
    "MetainferenceBase" --> "Metainference"
    "Caliber" -.-> "MetainferenceBase"
    "Selector" -.-> "MetainferenceBase"
    "Rescale" -.-> "MetainferenceBase"
    "Select" -.-> "MetainferenceBase"
```

Sources: [src/isdb/SAXS.cpp:22-1400](), [src/isdb/CS2Backbone.cpp:22-180](), [src/isdb/RDC.cpp:22-180](), [src/isdb/NOE.cpp:22-180](), [src/isdb/Jcoupling.cpp:22-180](), [src/isdb/PRE.cpp:22-180](), [src/isdb/EMMI.cpp:22-180](), [src/isdb/Caliber.cpp:22-80](), [src/isdb/Selector.cpp:30-87](), [src/isdb/Rescale.cpp:37-182](), [src/isdb/Select.cpp:32-55]()

### Metainference Framework

The Metainference framework is a Bayesian approach for integrating experimental data with molecular simulations. It models both the experimental uncertainty and the heterogeneity of the system using a set of replicas and explicit noise models.

#### Key Code Components

| Component            | Description                                                      | Code Entity / File |
|----------------------|------------------------------------------------------------------|--------------------|
| `MetainferenceBase`  | Abstract base class for ISDB metainference actions               | [src/isdb/MetainferenceBase.h:44-544]() |
| `Metainference`      | Implements the Metainference algorithm and MC sampling           | [src/isdb/Metainference.cpp:157-281]()  |
| Noise Models         | GAUSS, MGAUSS, OUTLIERS, MOUTLIERS, GENERIC (see below)          | [src/isdb/MetainferenceBase.cpp:184-199]() |
| MC Sampling          | Monte Carlo for noise, scale, and offset parameters              | [src/isdb/Metainference.cpp:250-274]()  |

#### Supported Noise Models

| Noise Type | Description | Code Constant |
|------------|-------------|--------------|
| GAUSS      | Single Gaussian for all data points | `GAUSS` |
| MGAUSS     | Gaussian per data point             | `MGAUSS` |
| OUTLIERS   | Single long-tailed Gaussian         | `OUTLIERS` |
| MOUTLIERS  | Long-tailed Gaussian per data point | `MOUTLIERS` |
| GENERIC    | Two distinct noises (replica and data) | `GENERIC` |

Sources: [src/isdb/MetainferenceBase.cpp:22-450](), [src/isdb/Metainference.cpp:22-285]()

### Data Flow: Simulation, ISDB, and Experimental Data

```mermaid
flowchart LR
    "MD_Engine"["MD Engine"]
    "PLUMED_Core"["PLUMED Core"]
    "Experimental_Data"["Experimental Data"]

    subgraph "ISDB_Module"
        "Calculate_Observable"["Calculate Observable (e.g., SAXS, RDC, etc.)"]
        "Compare_Experiment"["Compare with Experiment"]
        "Estimate_Uncertainty"["Uncertainty Estimation"]
        "Bias_Calculation"["Bias Calculation"]
    end

    "MD_Engine" -->|"Atom positions"| "PLUMED_Core"
    "PLUMED_Core" -->|"Coordinates"| "Calculate_Observable"
    "Experimental_Data" -->|"Reference values"| "Compare_Experiment"
    "Calculate_Observable" -->|"Calculated values"| "Compare_Experiment"
    "Compare_Experiment" -->|"Differences"| "Estimate_Uncertainty"
    "Estimate_Uncertainty" -->|"Weighted differences"| "Bias_Calculation"
    "Bias_Calculation" -->|"Forces"| "PLUMED_Core"
    "PLUMED_Core" -->|"Modified forces"| "MD_Engine"
```

Sources: [src/isdb/MetainferenceBase.cpp:22-450](), [src/isdb/Metainference.cpp:156-185]()

## Supported Experimental Data Types and Corresponding Actions

| Experimental Data Type | PLUMED Action/Class | Description | Key Features | Sources |
|------------------------|--------------------|-------------|--------------|---------|
| Small Angle Scattering (SAXS/SANS) | `SAXS` | Calculates SAXS/SANS intensities for a set of scattering vectors. | Supports atomistic, MARTINI, and ONEBEAD representations; GPU acceleration with ArrayFire. | [src/isdb/SAXS.cpp:67-155](), [src/isdb/SAXS.cpp:242-310]() |
| Chemical Shifts (NMR)  | `CS2Backbone`      | Calculates backbone chemical shifts using the CamShift model. | Supports multiple nuclei (HA, H, N, CA, CB, C); MPI/OpenMP parallelization. | [src/isdb/CS2Backbone.cpp:48-149]() |
| Residual Dipolar Coupling / Pseudocontact Shift | `RDC` | Calculates RDCs and PCS for NMR. | SVD approach (with GSL); supports experimental coupling input. | [src/isdb/RDC.cpp:36-129](), [src/isdb/RDC.cpp:131-172]() |
| Nuclear Overhauser Effect (NOE) | `NOE` | Calculates NOE intensities as sums of 1/r^6. | Handles ambiguous/equivalent atoms; supports metainference. | [src/isdb/NOE.cpp:31-66]() |
| J-Coupling (NMR) | `JCoupling` | Calculates 3J couplings using the Karplus relation. | Multiple coupling types; custom parameters. | [src/isdb/Jcoupling.cpp:30-85]() |
| Paramagnetic Resonance Enhancement (PRE) | `PRE` | Calculates PRE intensity ratios. | Supports INEPT, TAUC, OMEGA, RTWO parameters. | [src/isdb/PRE.cpp:31-66]() |
| Cryo-EM (GMM) | `EMMI` | Fits structures to cryo-EM density maps using Gaussian Mixture Models. | Multi-scale Bayesian approach; neighbor lists; multiple noise models. | [src/isdb/EMMI.cpp:42-108]() |
| Cryo-EM (Voxel) | `EMMIVox` | Fits structures to cryo-EM data using voxel-based maps. | Direct voxel data; B-factor inference; coarse-grained support. | [src/isdb/EMMIVox.cpp:50-69]() |

Sources: see table above.

## Utility Actions and Classes

| Utility         | PLUMED Action/Class | Description | Sources |
|-----------------|--------------------|-------------|---------|
| Maximum Caliber | `Caliber`          | Time-dependent harmonic restraint for time series data; supports replica-averaged simulations. | [src/isdb/Caliber.cpp:31-43]() |
| Selector        | `Selector`          | Defines a variable in PLUMED for use by other actions; enables dynamic bias activation. | [src/isdb/Selector.cpp:30-45]() |
| Rescale         | `Rescale`           | Scales the value of another action (CV or bias) using a parameter grid and MC/WTMetaD. | [src/isdb/Rescale.cpp:37-114]() |
| Select          | `Select`            | Selects an argument based on the value of a `Selector`, enabling dynamic switching. | [src/isdb/Select.cpp:32-40]() |

Sources: see table above.

## Recent Enhancements

Notable recent improvements to the ISDB module include:

- `CS2Backbone` supports MPI parallelization for DOSCORE and CAMSHIFT.
- `SAXS` includes Bessel function-based implementation for large systems, MARTINI bead structure factors, and GPU acceleration via ArrayFire.
- `Metainference` supports the `REGRES_ZERO` keyword for linear scale fitting.
- `Caliber` action added for Maximum Caliber replica-averaged restrained simulations.

Sources: [CHANGES/v2.5.md:60-67]()

## Usage Example

A typical workflow using the ISDB module might look like:

1. Prepare experimental data in the required format
2. Set up PLUMED input file with appropriate ISDB actions
3. Run the simulation with the MD engine of choice
4. Analyze the results

Here's a simple example using SAXS with the MARTINI model:

```
MOLINFO STRUCTURE=template.pdb

SAXS ...
  LABEL=saxs
  ATOMS=1-355
  MARTINI
  SCALE_EXPINT=1.4002
  QVALUE1=0.03 EXPINT1=1.0902
  QVALUE2=0.06 EXPINT2=0.790632
  QVALUE3=0.09 EXPINT3=0.453808
...
SAXS

PRINT ARG=(saxs\.q-.*),(saxs\.exp-.*) FILE=saxsdata STRIDE=1
```

---