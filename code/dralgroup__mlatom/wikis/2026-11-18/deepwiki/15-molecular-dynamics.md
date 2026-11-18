# Molecular Dynamics

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [mlatom/constants.py](mlatom/constants.py)
- [mlatom/initial_conditions.py](mlatom/initial_conditions.py)
- [mlatom/interfaces/sparrow_interface.py](mlatom/interfaces/sparrow_interface.py)
- [mlatom/md_cmd.py](mlatom/md_cmd.py)

</details>



This document covers the molecular dynamics (MD) simulation capabilities in MLatom, including initial condition generation, classical MD propagation, and integration with quantum chemistry methods for force calculations. For advanced dynamics like nonadiabatic molecular dynamics and surface hopping, see [Advanced Dynamics](#5.3). For core simulation utilities like geometry optimization, see [Core Simulations](#5.1).

## System Architecture

The molecular dynamics system in MLatom consists of several interconnected components that handle initial condition sampling, trajectory propagation, and integration with various computational methods.

### MD System Components

```mermaid
graph TD
    subgraph "Initial Conditions"
        generate_initial_conditions["generate_initial_conditions()"]
        wigner_sampling["wigner_sampling class"]
        harmonic_quantum_Boltzmann_sampling["harmonic_quantum_Boltzmann_sampling class"]
        random_velocities["generate_random_velocities()"]
    end
    
    subgraph "MD Command Interface"
        MD_CMD["MD_CMD class"]
        Args["Args class"]
        dynamics["dynamics() method"]
    end
    
    subgraph "Thermostats & Ensembles"
        andersen["Andersen_thermostat"]
        nose_hoover["Nose_Hoover_thermostat"]
        nve["NVE ensemble"]
        nvt["NVT ensemble"]
    end
    
    subgraph "QM Interfaces"
        sparrow_interface["sparrow_methods class"]
        pyscf_interface["PySCF interface"]
        gaussian_interface["Gaussian interface"]
        other_qm["Other QM methods"]
    end
    
    subgraph "Core Data"
        molecule["data.molecule"]
        molecular_database["data.molecular_database"]
        trajectories["trajectory data"]
    end
    
    MD_CMD --> Args
    Args --> dynamics
    dynamics --> generate_initial_conditions
    generate_initial_conditions --> wigner_sampling
    generate_initial_conditions --> harmonic_quantum_Boltzmann_sampling
    generate_initial_conditions --> random_velocities
    
    dynamics --> andersen
    dynamics --> nose_hoover
    dynamics --> nve
    dynamics --> nvt
    
    dynamics --> sparrow_interface
    dynamics --> pyscf_interface
    dynamics --> gaussian_interface
    dynamics --> other_qm
    
    generate_initial_conditions --> molecular_database
    molecular_database --> molecule
    dynamics --> trajectories
```

**Sources:** [mlatom/md_cmd.py:1-241](), [mlatom/initial_conditions.py:1-764]()

### Data Flow in MD Simulations

```mermaid
flowchart TD
    A["User Input: MD Parameters"] --> B["MD_CMD.dynamics()"]
    B --> C["Args.parse()"]
    C --> D{"Initial Condition Method"}
    
    D -->|user-defined| E["Read XYZ + velocities"]
    D -->|random| F["generate_random_velocities()"]
    D -->|wigner| G["wigner_sampling.sample()"]
    D -->|harmonic-quantum-boltzmann| H["harmonic_quantum_Boltzmann_sampling.sample()"]
    
    E --> I["molecular_database with init conditions"]
    F --> I
    G --> I
    H --> I
    
    I --> J["Select thermostat"]
    J --> K{"Ensemble Type"}
    K -->|NVE| L["No thermostat"]
    K -->|NVT| M["Andersen or Nose-Hoover"]
    
    L --> N["md() propagation"]
    M --> N
    
    N --> O["QM Method for Forces"]
    O --> P["Update positions/velocities"]
    P --> Q["Write trajectory"]
    
    Q --> R{"Continue?"}
    R -->|Yes| O
    R -->|No| S["Final trajectory output"]
```

**Sources:** [mlatom/md_cmd.py:58-221](), [mlatom/initial_conditions.py:69-264]()

## Initial Conditions Generation

The `generate_initial_conditions()` function provides multiple methods for sampling initial molecular configurations and velocities for MD simulations.

### Supported Sampling Methods

| Method | Description | Key Parameters |
|--------|-------------|----------------|
| `user-defined` | Read from XYZ and velocity files | `file_with_initial_xyz_coordinates`, `file_with_initial_xyz_velocities` |
| `random` | Random velocities from temperature | `initial_temperature`, `degrees_of_freedom` |
| `maxwell-boltzmann` | Maxwell-Boltzmann velocity distribution | `initial_temperature` |
| `wigner` | Quantum mechanical Wigner sampling | `temperature`, `use_hessian` |
| `harmonic-quantum-boltzmann` | Quantum Boltzmann distribution | `temperature`, `use_hessian` |

**Sources:** [mlatom/initial_conditions.py:96-106]()

### Wigner Sampling Implementation

The `wigner_sampling` class implements quantum mechanical Wigner sampling based on normal modes and frequencies:

```mermaid
graph TB
    subgraph "Wigner Sampling Process"
        A["molecule with hessian/frequencies"] --> B["wigner_sampling.sample()"]
        B --> C["Calculate normal modes"]
        C --> D["Remove negative frequencies"] 
        D --> E["Generate Gaussian parameters"]
        E --> F["Sample coordinates/momenta"]
        F --> G["Transform to Cartesian"]
        G --> H["Apply reaction coordinate momentum"]
        H --> I["Return coordinates + velocities"]
    end
    
    subgraph "Key Methods"
        rdmol["rdmol(): molecular setup"]
        inqp["inqp(): coordinate/momentum sampling"]
        nm2cart["nm2cart(): normal mode transformation"]
        sample_coor["sample_coor(): harmonic oscillator sampling"]
    end
    
    B --> rdmol
    F --> inqp
    C --> nm2cart
    F --> sample_coor
```

**Sources:** [mlatom/initial_conditions.py:362-589]()

### Energy Window Filtering

The system supports filtering initial conditions by excitation energy windows using `excitation_energy_window_filter()`:

- Calculates excitation energies and oscillator strengths
- Filters configurations within specified energy window
- Applies statistical weighting based on oscillator strengths
- Iteratively generates sufficient configurations

**Sources:** [mlatom/initial_conditions.py:17-67]()

## MD Command Interface

The `MD_CMD` class provides a command-line interface for setting up and running MD simulations.

### Key Parameters

The `Args` class defines essential MD parameters:

```python
# Time integration
'dt': 0.1,                    # Time step in fs
'trun': 1000,                 # Trajectory length in fs

# Initial conditions
'initConditions': '',         # Sampling method
'initTemperature': 300,       # Initial temperature in K

# Thermostats
'ensemble': 'nve',           # NVE or NVT
'thermostat': '',            # Thermostat type
'temperature': 300,          # Target temperature
'gamma': 0.2,               # Andersen thermostat parameter

# File I/O
'trajH5MDout': 'traj.h5',   # H5MD trajectory output
'trajTextOut': 'traj',      # Plain text trajectory
```

**Sources:** [mlatom/md_cmd.py:17-46]()

### Thermostat Integration

The system supports multiple thermostats for temperature control:

```mermaid
graph LR
    subgraph "NVE Ensemble"
        A["No thermostat"] --> B["Energy conservation"]
    end
    
    subgraph "NVT Ensemble"
        C["Andersen thermostat"] --> D["Stochastic collisions"]
        E["Nose-Hoover thermostat"] --> F["Deterministic coupling"]
    end
    
    G["MD simulation"] --> A
    G --> C
    G --> E
```

**Sources:** [mlatom/md_cmd.py:192-208]()

## Integration with Quantum Chemistry Methods

MD simulations can use various quantum chemistry methods for energy and force calculations. The `sparrow_interface` demonstrates this integration pattern.

### QM Method Interface Pattern

```mermaid
graph TD
    A["MD step"] --> B["QM method.predict()"]
    B --> C["calculate_energy=True"]
    B --> D["calculate_energy_gradients=True"]
    C --> E["Update potential energy"]
    D --> F["Update forces"]
    E --> G["Integrate equations of motion"]
    F --> G
    G --> H["Update positions/velocities"]
    H --> A
```

**Sources:** [mlatom/interfaces/sparrow_interface.py:59-163]()

### Supported QM Methods

The system integrates with multiple quantum chemistry programs:
- **Sparrow**: Semi-empirical methods (DFTB, MNDO, AM1, PM3, etc.)
- **PySCF**: DFT and post-HF methods
- **Gaussian**: Various quantum chemistry methods
- **xTB**: Extended tight-binding methods

**Sources:** [mlatom/interfaces/sparrow_interface.py:42-47]()

## Constants and Unit Conversions

Physical constants and unit conversions are centralized in the `constants` module:

```python
# Time conversions
au2fs = 2.4188843265857E-2     # Atomic units to femtoseconds
fs2au = 1.0 / au2fs

# Energy conversions  
Hartree2kcalpermol = 627.509474
kB_in_Hartree = ...            # Boltzmann constant in Hartree/K

# Distance conversions
Bohr2Angstrom = 0.52917721092
Angstrom2Bohr = 1.0 / Bohr2Angstrom
```

**Sources:** [mlatom/constants.py:10-49]()

---