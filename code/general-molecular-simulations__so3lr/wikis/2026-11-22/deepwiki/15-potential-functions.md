# Potential Functions

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [so3lr/potential.py](so3lr/potential.py)
- [tests/test_potential.py](tests/test_potential.py)

</details>



This page documents the SO3LR potential function system, which provides the core interface for creating and configuring molecular potentials. The potential functions combine SO3krates neural networks with universal pairwise force fields to enable energy and force calculations for molecular systems.

For information about how potentials are used in molecular dynamics simulations, see [Command Line Interface](#2). For integration with external frameworks, see [Python API](#3).

## Architecture Overview

The SO3LR potential system is built around a factory function that creates `MLFFPotentialSparse` instances configured with SO3LR-specific parameters. This design allows for consistent potential creation across different usage contexts.

### Potential Function Architecture

```mermaid
graph TB
    subgraph "User Interfaces"
        ASECalc["So3lrCalculator"]
        JAXMDPot["So3lrPotential"]
        DirectAPI["Direct API Usage"]
    end
    
    subgraph "Potential Factory"
        makePotentialFn["make_potential_fn()"]
        ParamConfig["Parameter Configuration"]
    end
    
    subgraph "MLFF Framework"
        MLFFPotentialSparse["MLFFPotentialSparse"]
        WorkdirLoader["Workdir Parameter Loader"]
    end
    
    subgraph "SO3LR Parameters"
        ParamsDir["so3lr/params/"]
        SO3kratesWeights["SO3krates Neural Network Weights"]
        UPFParams["Universal Pairwise Force Field Parameters"]
    end
    
    subgraph "Long-range Configuration"
        LRCutoff["lr_cutoff"]
        DispersionDamping["dispersion_energy_cutoff_lr_damping"]
        CoulombConfig["Coulomb/Ewald Settings"]
    end
    
    ASECalc --> makePotentialFn
    JAXMDPot --> makePotentialFn
    DirectAPI --> makePotentialFn
    
    makePotentialFn --> ParamConfig
    ParamConfig --> MLFFPotentialSparse
    MLFFPotentialSparse --> WorkdirLoader
    
    WorkdirLoader --> ParamsDir
    ParamsDir --> SO3kratesWeights
    ParamsDir --> UPFParams
    
    ParamConfig --> LRCutoff
    ParamConfig --> DispersionDamping
    ParamConfig --> CoulombConfig
```

Sources: [so3lr/potential.py:1-30]()

## Potential Function Factory

The `make_potential_fn` function serves as the primary entry point for creating SO3LR potentials. It abstracts the complexity of parameter loading and configuration from end users.

### Function Signature and Parameters

The function accepts several key parameters for customizing potential behavior:

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `lr_cutoff` | 12.0 | Long-range interaction cutoff distance |
| `dispersion_energy_cutoff_lr_damping` | 2.0 | Damping factor for dispersion energy cutoff |
| `dtype` | `np.float32` | Numerical precision for calculations |
| `coulomb_kspace_do_ewald` | `False` | Enable Ewald summation for Coulomb interactions |
| `coulomb_kspace_interp_nodes` | 4 | Interpolation nodes for k-space Coulomb calculations |

### Implementation Details

The function implementation follows a straightforward pattern:

1. **Parameter Directory Resolution**: Locates the SO3LR parameter directory relative to the package installation
2. **MLFF Potential Creation**: Delegates to `MLFFPotentialSparse.create_from_workdir()` with SO3LR-specific configuration
3. **Long-range Parameter Configuration**: Sets up long-range interaction parameters through the `long_range_kwargs` dictionary

Sources: [so3lr/potential.py:7-29]()

## Parameter Loading Mechanism

The potential function relies on pre-trained parameters stored in the package directory structure. This design ensures that SO3LR potentials are immediately usable after installation without requiring separate parameter downloads.

### Parameter Loading Flow

```mermaid
graph LR
    subgraph "Package Structure"
        PackageRoot["SO3LR Package Root"]
        ParamsDir["so3lr/params/"]
    end
    
    subgraph "Parameter Resolution"
        PathResolution["pathlib.Path(__file__).parent.parent.resolve()"]
        WorkdirPath["package_dir / 'so3lr' / 'params'"]
    end
    
    subgraph "MLFF Loading"
        CreateFromWorkdir["MLFFPotentialSparse.create_from_workdir()"]
        FromFileFlag["from_file=True"]
    end
    
    subgraph "Configuration"
        LongRangeKwargs["long_range_kwargs"]
        DtypeConfig["dtype configuration"]
        AdditionalKwargs["**kwargs passthrough"]
    end
    
    PackageRoot --> PathResolution
    PathResolution --> WorkdirPath
    WorkdirPath --> ParamsDir
    
    ParamsDir --> CreateFromWorkdir
    CreateFromWorkdir --> FromFileFlag
    
    CreateFromWorkdir --> LongRangeKwargs
    CreateFromWorkdir --> DtypeConfig
    CreateFromWorkdir --> AdditionalKwargs
```

Sources: [so3lr/potential.py:15-18]()

## Long-range Interaction Configuration

The potential function configures several aspects of long-range interactions through the `long_range_kwargs` dictionary. This configuration is critical for proper handling of electrostatic and dispersion interactions beyond the neural network's local scope.

### Long-range Parameter Mapping

The function maps input parameters to the MLFF framework's expected configuration:

- **`cutoff_lr`**: Maps from `lr_cutoff` parameter, controls the distance at which long-range interactions are truncated
- **`dispersion_energy_cutoff_lr_damping`**: Direct passthrough for dispersion energy damping
- **`neighborlist_format_lr`**: Fixed to `'ordered_sparse'` for efficient sparse matrix operations
- **`coulomb_kspace_do_ewald`**: Controls whether Ewald summation is used for Coulomb interactions
- **`coulomb_kspace_interp_nodes`**: Sets interpolation grid density for k-space calculations

Sources: [so3lr/potential.py:20-26]()

## Integration with MLFF Framework

The SO3LR potential system builds upon the MLFF (Machine Learning Force Fields) framework, specifically using the `MLFFPotentialSparse` class for sparse matrix-based potential evaluation.

### MLFF Integration Architecture

```mermaid
graph TB
    subgraph "SO3LR Layer"
        MakePotentialFn["make_potential_fn()"]
        SO3LRParams["SO3LR-specific Parameters"]
    end
    
    subgraph "MLFF Framework"
        MLFFPotentialSparse["MLFFPotentialSparse"]
        CreateFromWorkdir["create_from_workdir()"]
        WorkdirLoader["Parameter Loading System"]
    end
    
    subgraph "JAX Backend"
        JAXArrays["JAX Arrays"]
        JITCompilation["JIT Compilation"]
        AutoDiff["Automatic Differentiation"]
    end
    
    subgraph "Computational Graph"
        EnergyCalc["Energy Calculation"]
        ForceCalc["Force Calculation (via autodiff)"]
        StressCalc["Stress Calculation"]
    end
    
    MakePotentialFn --> SO3LRParams
    SO3LRParams --> CreateFromWorkdir
    CreateFromWorkdir --> MLFFPotentialSparse
    MLFFPotentialSparse --> WorkdirLoader
    
    MLFFPotentialSparse --> JAXArrays
    JAXArrays --> JITCompilation
    JITCompilation --> AutoDiff
    
    AutoDiff --> EnergyCalc
    AutoDiff --> ForceCalc
    AutoDiff --> StressCalc
```

Sources: [so3lr/potential.py:4](), [so3lr/potential.py:17-29]()

## Usage Patterns

The potential function is designed to be used across different computational contexts, from interactive ASE calculations to large-scale JAX-MD simulations. The consistent interface allows for seamless integration regardless of the specific use case.

### Common Usage Pattern

```python
# Basic potential creation
potential = make_potential_fn()

# Custom long-range cutoff
potential = make_potential_fn(lr_cutoff=15.0)

# High-precision calculations
potential = make_potential_fn(dtype=np.float64)

# Ewald summation enabled
potential = make_potential_fn(coulomb_kspace_do_ewald=True)
```

The returned potential object provides the standard MLFF interface for energy and force evaluation, making it compatible with various molecular simulation frameworks.

Sources: [so3lr/potential.py:7-29](), [tests/test_potential.py:4-5]()

---