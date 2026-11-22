# DRR and eABF

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [regtest/.gitignore](regtest/.gitignore)
- [regtest/drr/rt-eabf/Makefile](regtest/drr/rt-eabf/Makefile)
- [regtest/drr/rt-eabf/ala12_trajectory.xyz](regtest/drr/rt-eabf/ala12_trajectory.xyz)
- [regtest/drr/rt-eabf/colvar.reference](regtest/drr/rt-eabf/colvar.reference)
- [regtest/drr/rt-eabf/config](regtest/drr/rt-eabf/config)
- [regtest/drr/rt-eabf/eabf.UI.count.reference](regtest/drr/rt-eabf/eabf.UI.count.reference)
- [regtest/drr/rt-eabf/eabf.UI.grad.reference](regtest/drr/rt-eabf/eabf.UI.grad.reference)
- [regtest/drr/rt-eabf/eabf.UI.hist.grad.reference](regtest/drr/rt-eabf/eabf.UI.hist.grad.reference)
- [regtest/drr/rt-eabf/forces.reference](regtest/drr/rt-eabf/forces.reference)
- [regtest/drr/rt-eabf/plumed.dat](regtest/drr/rt-eabf/plumed.dat)
- [regtest/drr/rt-eabf/trajectory.xyz](regtest/drr/rt-eabf/trajectory.xyz)
- [regtest/drr/rt-extract/config](regtest/drr/rt-extract/config)
- [regtest/drr/rt-extract2dpbc/Makefile](regtest/drr/rt-extract2dpbc/Makefile)
- [regtest/drr/rt-extract2dpbc/config](regtest/drr/rt-extract2dpbc/config)
- [regtest/drr/rt-pmf1d/plumed.dat](regtest/drr/rt-pmf1d/plumed.dat)
- [regtest/drr/rt-restart/eabf.UI.count.reference](regtest/drr/rt-restart/eabf.UI.count.reference)
- [regtest/drr/rt-restart/eabf.UI.grad.reference](regtest/drr/rt-restart/eabf.UI.grad.reference)
- [regtest/drr/rt-restart/eabf.UI.hist.grad.reference](regtest/drr/rt-restart/eabf.UI.hist.grad.reference)
- [regtest/drr/rt-restart/eabf_r.UI.grad](regtest/drr/rt-restart/eabf_r.UI.grad)
- [regtest/drr/rt-restart/plumed.dat](regtest/drr/rt-restart/plumed.dat)
- [src/.gitignore](src/.gitignore)
- [src/drr/COPYRIGHT](src/drr/COPYRIGHT)
- [src/drr/DRR.cpp](src/drr/DRR.cpp)
- [src/drr/DRR.h](src/drr/DRR.h)
- [src/drr/DynamicReferenceRestraining.cpp](src/drr/DynamicReferenceRestraining.cpp)
- [src/drr/colvar_UIestimator.cpp](src/drr/colvar_UIestimator.cpp)
- [src/drr/colvar_UIestimator.h](src/drr/colvar_UIestimator.h)
- [src/drr/drrtool.cpp](src/drr/drrtool.cpp)

</details>



This document explains the Dynamic Reference Restraining (DRR) and extended-system Adaptive Biasing Force (eABF) methods implemented in PLUMED. These enhanced sampling methods facilitate the calculation of free energy surfaces along collective variables by improving conformational sampling in molecular dynamics simulations.

## Introduction

The eABF/DRR method introduces fictitious (extended) variables that are harmonically coupled to collective variables through a spring-like potential. By applying biasing forces to these fictitious variables rather than directly to the real collective variables, more efficient sampling can be achieved. This approach was first introduced by Lelièvre et al. and later referred to as DRR by Zheng et al.

Sources: [src/drr/DynamicReferenceRestraining.cpp:45-53]()

## How DRR/eABF Works

For each collective variable (CV) ξᵢ, a fictitious variable λᵢ is attached through a spring with a force constant k. The fictitious variable undergoes overdamped Langevin dynamics similar to the Extended Lagrangian method. The core idea is:

1. Apply bias forces to the fictitious variable λᵢ
2. These bias forces are the negative average spring force on λᵢ
3. This enhances sampling of λᵢ, which in turn improves sampling of the real CV ξᵢ
4. If the spring constant k is large enough, ξᵢ will synchronize with λᵢ

The bias force is calculated as:

```
F_bias(λᵢ) = k(λᵢ - ⟨ξᵢ⟩_λᵢ)
```

Where ⟨ξᵢ⟩_λᵢ is the average value of the real CV when the fictitious variable is at λᵢ.

Sources: [src/drr/DynamicReferenceRestraining.cpp:54-67]()

## DRR/eABF System-to-Code Architecture

**Diagram: DRR/eABF System and Code Entities**

```mermaid
flowchart TD
    subgraph "Input/Output"
        InputFile["\"PLUMED Input File\""]
        DRRState["\".drrstate\" (binary state file)"]
        GradFiles["\".grad/.count\" (text output)"]
        PMFFile["\".pmf\" (1D PMF)"]
        drr_tool["\"drr_tool\" (src/drr/drrtool.cpp)"]
    end

    subgraph "Core Classes"
        DynamicReferenceRestraining["\"DynamicReferenceRestraining\" (src/drr/DynamicReferenceRestraining.cpp)"]
        ABF["\"ABF\" (src/drr/DRR.h)"]
        CZAR["\"CZAR\" (src/drr/DRR.h)"]
        UIestimator["\"UIestimator\" (src/drr/colvar_UIestimator.h)"]
        DRRAxis["\"DRRAxis\" (src/drr/DRR.h)"]
        DRRForceGrid["\"DRRForceGrid\" (src/drr/DRR.h)"]
    end

    subgraph "Simulation"
        CVs["\"Collective Variables\""]
        FictVars["\"Fictitious Variables\""]
        SpringForces["\"Spring Forces\""]
        BiasForces["\"Bias Forces\""]
    end

    InputFile --> DynamicReferenceRestraining
    CVs --> DynamicReferenceRestraining
    DynamicReferenceRestraining --> FictVars
    DynamicReferenceRestraining --> SpringForces
    DynamicReferenceRestraining --> DRRState

    DynamicReferenceRestraining --> ABF
    DynamicReferenceRestraining --> CZAR
    DynamicReferenceRestraining --> UIestimator

    ABF --> BiasForces
    ABF --> GradFiles
    CZAR --> GradFiles
    UIestimator --> GradFiles

    DRRState --> drr_tool
    drr_tool --> GradFiles
    ABF --> PMFFile

    DRRAxis --> DRRForceGrid
    DRRForceGrid --> ABF
    DRRForceGrid --> CZAR
```

**Explanation:**  
- The main entry point is the `DynamicReferenceRestraining` class, which manages the eABF/DRR algorithm.
- `ABF`, `CZAR`, and `UIestimator` are estimator classes for free energy gradients.
- `DRRAxis` and `DRRForceGrid` manage grid axes and force/sample accumulation.
- The `.drrstate` file is the main binary output, processed by the `drr_tool` utility to produce human-readable files.

Sources: [src/drr/DynamicReferenceRestraining.cpp:180-243](), [src/drr/DRR.h:43-378](), [src/drr/drrtool.cpp:78-238]()

## Estimators

DRR/eABF provides three different estimators to calculate free energy gradients:

### 1. Naive (ABF) Estimator

The simplest estimator that uses the negative of the average spring force on λᵢ. Despite being biased, it often gives reasonable results.

### 2. CZAR Estimator (Corrected Z-Average Restraint)

The CZAR estimator corrects for the bias in the naive estimator by incorporating the gradient of the distribution:

```
∂A/∂ξᵢ(ξ) = -1/β ∂ln(ρ̃(ξ))/∂ξᵢ + k(⟨λᵢ⟩_ξ - ξᵢ)
```

Where β is the inverse temperature (1/kBT), ρ̃(ξ) is the biased distribution, and ⟨λᵢ⟩_ξ is the average value of the fictitious variable when the real CV is at ξ.

### 3. UI Estimator (Umbrella Integration)

The UI estimator calculates gradients as:

```
A'(ξ*) = [∑_λ N(ξ*,λ)[(ξ*-⟨ξ⟩_λ)/(β*σ_λ²) - k(ξ*-λ)]] / [∑_λ N(ξ*,λ)]
```

Where N(ξ*,λ) is the number of samples with real CV at ξ* and fictitious variable at λ, ⟨ξ⟩_λ is the average of the real CV when the fictitious variable is at λ, and σ_λ² is the variance.

Sources: [src/drr/DynamicReferenceRestraining.cpp:68-87](), [src/drr/DRR.cpp:429-469](), [src/drr/DRR.cpp:492-517](), [src/drr/colvar_UIestimator.h:221-543]()

## Main Data Structures and Class Relationships

**Diagram: DRR/eABF Class Structure and Relationships**

```mermaid
classDiagram
    class "DynamicReferenceRestraining (src/drr/DynamicReferenceRestraining.cpp)" {
        - vector<double> fictNoPBC
        - vector<double> real
        - vector<double> springlength
        - vector<double> fict
        - vector<double> vfict
        - vector<double> ffict
        - vector<double> fbias
        - vector<double> kappa
        - vector<DRRAxis> delim
        - ABF ABFGrid
        - CZAR CZARestimator
        - UIestimator eabf_UI
        + calculate()
        + update()
        + save()
        + load()
    }
    class "DRRAxis (src/drr/DRR.h)" {
        - double min
        - double max
        - size_t nbins
        - bool periodic
        - double binWidth
        + getMin()
        + getMax()
        + getWidth()
        + isInBoundary()
        + isRealPeriodic()
    }
    class "DRRForceGrid (src/drr/DRR.h)" {
        - vector<DRRAxis> dimensions
        - vector<double> forces
        - vector<unsigned long int> samples
        - vector<size_t> shifts
        + store()
        + getGradient()
        + getCount()
        + writeAll()
    }
    class "ABF (src/drr/DRR.h)" {
        - double mFullSamples
        - vector<double> mMaxFactors
        + getbias()
        + store_force()
    }
    class "CZAR (src/drr/DRR.h)" {
        - double kbt
        + getGradient()
        + writeZCountZGrad()
    }
    class "UIestimator (src/drr/colvar_UIestimator.h)" {
        - n_vector<double> sum_x
        - n_vector<double> sum_x_square
        - n_vector<int> count_y
        - n_matrix distribution_x_y
        + update()
        + calc_pmf()
        + write_files()
    }

    "DynamicReferenceRestraining (src/drr/DynamicReferenceRestraining.cpp)" *-- "DRRAxis (src/drr/DRR.h)"
    "DynamicReferenceRestraining (src/drr/DynamicReferenceRestraining.cpp)" *-- "ABF (src/drr/DRR.h)"
    "DynamicReferenceRestraining (src/drr/DynamicReferenceRestraining.cpp)" *-- "CZAR (src/drr/DRR.h)"
    "DynamicReferenceRestraining (src/drr/DynamicReferenceRestraining.cpp)" *-- "UIestimator (src/drr/colvar_UIestimator.h)"
    "DRRForceGrid (src/drr/DRR.h)" <|-- "ABF (src/drr/DRR.h)"
    "DRRForceGrid (src/drr/DRR.h)" <|-- "CZAR (src/drr/DRR.h)"
    "DRRForceGrid (src/drr/DRR.h)" *-- "DRRAxis (src/drr/DRR.h)"
```

**Explanation:**  
- `DynamicReferenceRestraining` is the main biasing class, holding references to the grid and estimator classes.
- `DRRAxis` describes grid axes for collective variables.
- `DRRForceGrid` is a base class for force and sample accumulation on a grid.
- `ABF` and `CZAR` inherit from `DRRForceGrid` and implement different estimators.
- `UIestimator` is a separate estimator for umbrella integration.

Sources: [src/drr/DynamicReferenceRestraining.cpp:180-243](), [src/drr/DRR.h:50-378](), [src/drr/colvar_UIestimator.h:49-147](), [src/drr/colvar_UIestimator.h:221-367]()

## Using DRR/eABF in PLUMED

### Basic Usage Example

Here's an example of a simple eABF simulation on two torsional angles:

```
phi: TORSION ATOMS=5,7,9,15
psi: TORSION ATOMS=7,9,15,17

DRR ...
LABEL=eabf
ARG=phi,psi
FULLSAMPLES=500
GRID_MIN=-pi,-pi
GRID_MAX=pi,pi
GRID_BIN=180,180
FRICTION=8.0,8.0
TAU=0.5,0.5
OUTPUTFREQ=50000
HISTORYFREQ=500000
... DRR

# monitor variables and forces
PRINT STRIDE=10 ARG=phi,psi,eabf.phi_fict,eabf.psi_fict,eabf.phi_biasforce,eabf.psi_biasforce FILE=COLVAR
```

Sources: [src/drr/DynamicReferenceRestraining.cpp:90-113]()

### Advanced Usage: Restraining with Walls

```
dist1: DISTANCE ATOMS=10,92
eabf_winall: DRR ARG=dist1 FULLSAMPLES=2000 GRID_MIN=1.20 GRID_MAX=3.20 GRID_BIN=200 FRICTION=8.0 TAU=0.5 OUTPUTFREQ=5000 HISTORYFREQ=500000
uwall: UPPER_WALLS ARG=eabf_winall.dist1_fict AT=3.2 KAPPA=418.4
lwall: LOWER_WALLS ARG=eabf_winall.dist1_fict AT=1.2 KAPPA=418.4
PRINT STRIDE=10 ARG=dist1,eabf_winall.dist1_fict,eabf_winall.dist1_biasforce FILE=COLVAR
```

Sources: [src/drr/DynamicReferenceRestraining.cpp:115-124]()

### Running Extended Generalized ABF (egABF)

```
phi: TORSION ATOMS=5,7,9,15
psi: TORSION ATOMS=7,9,15,17

DRR ...
LABEL=gabf_phi
ARG=phi
FULLSAMPLES=500
GRID_MIN=-pi
GRID_MAX=pi
GRID_BIN=180
FRICTION=8.0
TAU=0.5
OUTPUTFREQ=50000
HISTORYFREQ=500000
... DRR

DRR ...
LABEL=gabf_psi
ARG=psi
FULLSAMPLES=500
GRID_MIN=-pi
GRID_MAX=pi
GRID_BIN=180
FRICTION=8.0
TAU=0.5
OUTPUTFREQ=50000
HISTORYFREQ=500000
... DRR

DRR ...
LABEL=gabf_2d
ARG=phi,psi
EXTERNAL_FORCE=gabf_phi.phi_springforce,gabf_psi.psi_springforce
EXTERNAL_FICT=gabf_phi.phi_fictNoPBC,gabf_psi.psi_fictNoPBC
GRID_MIN=-pi,-pi
GRID_MAX=pi,pi
GRID_BIN=180,180
NOBIAS
OUTPUTFREQ=50000
HISTORYFREQ=500000
... DRR
```

Sources: [src/drr/DynamicReferenceRestraining.cpp:126-172]()

## Output Files and Analysis

### DRR State File

The primary output from a DRR/eABF simulation is the `.drrstate` file, which contains:
- The states of the fictitious variables
- Accumulated forces and sample counts for both ABF and CZAR estimators
- Other internal data needed for restarting simulations

This is a binary file that must be processed with the `drr_tool` utility.

### Gradient and Count Files

After processing with `drr_tool`, the following files are generated:

| File Extension | Contents | Estimator |
|----------------|----------|-----------|
| `.abf.grad` | Free energy gradients | Naive (ABF) |
| `.abf.count` | Sample counts | Naive (ABF) |
| `.czar.grad` | Free energy gradients | CZAR |
| `.czar.count` | Sample counts | CZAR |
| `.zcount` | Sample counts of the real CV | (Debugging) |
| `.zgrad` | Negative ξ-averaged spring forces | (Debugging) |
| `.pmf` | 1D PMF (for 1D cases only) | - |

Sources: [src/drr/DynamicReferenceRestraining.cpp:88-90](), [src/drr/drrtool.cpp:40-67]()

## drr_tool Utility: Extraction and Postprocessing

The `drr_tool` command-line utility is used to process `.drrstate` binary files produced by DRR/eABF simulations. It can extract gradient and count files, merge multiple windows, and convert units.

**Key Operations:**

| Operation | Command Example | Description |
|-----------|----------------|-------------|
| Extract gradients/counts | `plumed drr_tool --extract eabf.drrstate` | Extracts `.grad` and `.count` files from a `.drrstate` file. |
| Merge windows | `plumed drr_tool --merge win1.drrstate,win2.drrstate` | Merges multiple `.drrstate` files and outputs combined `.grad`/`.count` files. |
| Specify output units | `plumed drr_tool --extract eabf.drrstate --units kcal/mol` | Converts output to specified energy units. |

After extraction, the `.grad` and `.count` files can be integrated using external tools such as `abf_integrate` from the Colvars package to obtain the free energy surface.

**Relevant Code Entities:**
- `drrtool` class in [src/drr/drrtool.cpp:78-238]()
- Command-line keyword registration in [src/drr/drrtool.cpp:98-107]()
- Extraction and merging logic in [src/drr/drrtool.cpp:141-238]()

Sources: [src/drr/drrtool.cpp:47-67](), [src/drr/drrtool.cpp:77-133]()

## Implementation Details

### DynamicReferenceRestraining Class

This is the main class that implements the eABF/DRR method. It inherits from the `Bias` class and manages:
- Fictitious variables and their dynamics
- Spring forces between real CVs and fictitious variables
- Bias forces applied to fictitious variables
- Grid-based collection of forces and samples
- Output of gradients and PMFs
- Backup and restart functionalities

Sources: [src/drr/DynamicReferenceRestraining.cpp:180-243](), [src/drr/DynamicReferenceRestraining.cpp:333-460]()

### Update and Integration Mechanism

At each simulation step, the following operations are performed by the `DynamicReferenceRestraining` class:

1. Calculate spring forces between real collective variables and fictitious variables.
2. Store instantaneous forces in the ABF and CZAR grids.
3. Compute and apply biasing forces to the fictitious variables (unless `NOBIAS` is set).
4. Integrate the fictitious variables using overdamped Langevin dynamics with thermostatting.
5. Periodically save the state to a `.drrstate` file for restart and analysis.

This logic is implemented in the `calculate()` and `update()` methods.

Sources: [src/drr/DynamicReferenceRestraining.cpp:718-858]()

### DRR/eABF Input Keywords and Parameters

The following table summarizes the main input keywords for configuring the DRR/eABF method in PLUMED:

| Keyword         | Description                                                        | Default/Required                |
|-----------------|--------------------------------------------------------------------|---------------------------------|
| `KAPPA`         | Spring force constant for each variable                            | kBT/(grid spacing)²             |
| `TAU`           | Relaxation time for fictitious variables                           | 0.5                             |
| `FRICTION`      | Langevin friction coefficient for fictitious variables             | 8.0                             |
| `GRID_MIN`      | Lower bounds for the grid                                          | Required                        |
| `GRID_MAX`      | Upper bounds for the grid                                          | Required                        |
| `GRID_BIN`      | Number of bins for the grid                                        | Required (or use GRID_SPACING)  |
| `GRID_SPACING`  | Grid spacing (alternative to GRID_BIN)                             |                                 |
| `FULLSAMPLES`   | Number of samples before full bias is applied                      | 500                             |
| `MAXFACTOR`     | Maximum scaling factor for bias force                              | 1.0                             |
| `OUTPUTFREQ`    | Frequency of writing output files                                  | Required                        |
| `HISTORYFREQ`   | Frequency of writing history files                                 | -                               |
| `NOCZAR`        | Disable CZAR estimator                                             | false                           |
| `UI`            | Enable UI estimator                                                | false                           |
| `TEXTOUTPUT`    | Use text output for grad/count files                               | false                           |
| `NOBIAS`        | Do not apply bias forces                                           | false                           |
| `EXTERNAL_FORCE`| Use forces from other actions (disables extended system)           |                                 |
| `EXTERNAL_FICT` | Position of external fictitious particles (for UI estimator)       |                                 |
| `TEMP`          | System temperature (if not set by MD engine)                       |                                 |
| `DRR_RFILE`     | Restart file for DRR state                                         |                                 |
| `OUTPUTPREFIX`  | Prefix for output files                                            | label name                      |

For a full list and detailed descriptions, see the keyword registration in [src/drr/DynamicReferenceRestraining.cpp:254-344]().

Sources: [src/drr/DynamicReferenceRestraining.cpp:247-344]()

## Conclusions

The DRR/eABF method provides an efficient approach to enhanced sampling and free energy calculations in molecular dynamics simulations. By working with extended (fictitious) variables, it achieves better sampling efficiency while maintaining the accuracy of free energy estimates through various estimators.

Key advantages of the method include:
1. Enhanced sampling of collective variables
2. Multiple estimators for free energy gradients
3. Flexibility in simulation setup
4. Comprehensive tools for analysis

The implementation in PLUMED provides a user-friendly interface to this advanced technique, making it accessible to researchers in computational chemistry and biophysics.

---