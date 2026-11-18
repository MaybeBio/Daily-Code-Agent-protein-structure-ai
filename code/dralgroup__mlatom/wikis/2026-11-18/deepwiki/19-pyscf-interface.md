# PySCF Interface

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [mlatom/interfaces/pyscf_interface.py](mlatom/interfaces/pyscf_interface.py)

</details>



This document covers the PySCF (Python-based Simulations of Chemistry Framework) interface within MLatom, which provides access to a wide range of quantum chemistry methods including DFT, post-Hartree-Fock methods, and time-dependent methods. The interface handles energy calculations, geometry optimizations, frequency analysis, and thermochemical properties.

For information about other quantum chemistry interfaces, see [Gaussian and ASE Interfaces](#6.2) and [DFTB+ and Other Interfaces](#6.3). For details about the core model framework that this interface integrates with, see [Model Framework](#2.2).

## Architecture Overview

The PySCF interface is built around a hierarchical class structure that inherits from MLatom's base model framework while providing threading control and method-specific implementations.

### Class Structure

```mermaid
classDiagram
    class model {
        <<abstract>>
        +predict()
        +set_num_threads()
    }
    
    class OMP_pyscf {
        +set_num_threads(nthreads)
        +nthreads: int
    }
    
    class pyscf_methods {
        +method: str
        +basis: str
        +density_fitting: bool
        +supported_methods: list
        +__init__(method, nthreads, density_fitting)
        +is_method_supported(method)
        +predict_for_molecule(molecule, ...)
        +predict_for_molecule_DM21(molecule, ...)
        +predict(molecular_database, ...)
    }
    
    model <|-- OMP_pyscf
    OMP_pyscf <|-- pyscf_methods
    
    note for pyscf_methods "Supports: HF, MP2, DFT, CISD, FCI,\nCCSD/CCSD(T), TD-DFT/TD-HF, DM21"
```

**Sources:** [mlatom/interfaces/pyscf_interface.py:23-31](), [mlatom/interfaces/pyscf_interface.py:50-90]()

### Integration with MLatom Core

```mermaid
flowchart TD
    A["MLtasks.py"] --> B["pyscf_methods"]
    B --> C["predict()"]
    C --> D["predict_for_molecule()"]
    
    D --> E{Method Type}
    E -->|"Standard QM"| F["Standard PySCF Methods"]
    E -->|"DM21 Family"| G["predict_for_molecule_DM21()"]
    E -->|"TD-DFT/TDA"| H["Time-dependent Methods"]
    
    F --> I["Energy Calculation"]
    G --> I
    H --> I
    
    I --> J{Additional Properties}
    J -->|"Gradients"| K["nuc_grad_method()"]
    J -->|"Hessian"| L["Hessian()"]
    J -->|"Thermochemistry"| M["thermo_calculation()"]
    
    K --> N["molecule.atoms[i].energy_gradients"]
    L --> O["molecule.hessian"]
    M --> P["molecule.frequencies, ZPE, etc."]
    
    N --> Q["data.py molecular structures"]
    O --> Q
    P --> Q
```

**Sources:** [mlatom/interfaces/pyscf_interface.py:91-363](), [mlatom/interfaces/pyscf_interface.py:365-421]()

## Supported Methods and Capabilities

The interface supports a comprehensive range of quantum chemistry methods with varying levels of derivative support.

### Method Support Matrix

| Method Category | Methods | Energy | Gradients | Hessian |
|----------------|---------|---------|-----------|---------|
| **Hartree-Fock** | HF | ✓ | ✓ | ✓ |
| **Post-HF** | MP2, CISD, CCSD, CCSD(T), FCI | ✓ | ✓* | ✗ |
| **DFT** | Any libxc functional | ✓ | ✓ | ✓ |
| **Time-dependent** | TD-DFT, TDA | ✓ | ✓ | ✗ |
| **Neural Functionals** | DM21, DM21m, DM21mc, DM21mu | ✓ | ✗ | ✗ |

*FCI gradients not supported, UCCSD(T) gradients not supported

**Sources:** [mlatom/interfaces/pyscf_interface.py:41-49](), [mlatom/interfaces/pyscf_interface.py:238-292]()

### Method Detection and Initialization

```mermaid
flowchart TD
    A["method string (e.g., 'B3LYP/6-31G')"] --> B["Split on '/'"]
    B --> C["method = parts[0]"]
    B --> D["basis = parts[1]"]
    
    C --> E{Method Type Check}
    E -->|"In supported_methods"| F["Direct Support"]
    E -->|"DM21 variants"| G["Neural Functional"]
    E -->|"TD-/TDA- prefix"| H["Time-dependent"]
    E -->|"Other"| I["Try libxc parse_xc()"]
    
    F --> J["Initialize Standard Method"]
    G --> K["Initialize DM21 Method"]
    H --> L["Initialize TD Method"]
    I --> M{Parse Success?}
    M -->|"Yes"| N["Initialize DFT Method"]
    M -->|"No"| O["Raise ValueError"]
```

**Sources:** [mlatom/interfaces/pyscf_interface.py:68-89](), [mlatom/interfaces/pyscf_interface.py:52-66]()

## Core Implementation Details

### Molecule Processing Pipeline

The interface converts MLatom molecule objects to PySCF format and handles various calculation types through a unified prediction workflow.

```mermaid
sequenceDiagram
    participant M as "MLatom molecule"
    participant P as "pyscf_methods"
    participant G as "gto.Mole"
    participant S as "PySCF Method Object"
    participant R as "Results"

    M->>P: predict_for_molecule()
    P->>G: Create gto.Mole()
    G->>G: Set atoms, basis, charge, spin
    P->>S: Initialize method (HF, DFT, etc.)
    S->>S: kernel() - run calculation
    
    alt Energy only
        S->>R: e_tot
    else Energy + Gradients
        S->>R: e_tot + nuc_grad_method()
    else Energy + Gradients + Hessian
        S->>R: e_tot + gradients + Hessian()
    end
    
    R->>M: Update molecule properties
```

**Sources:** [mlatom/interfaces/pyscf_interface.py:91-103](), [mlatom/interfaces/pyscf_interface.py:220-262]()

### Special Method Implementations

#### Time-Dependent Methods
```mermaid
flowchart TD
    A["TD-DFT/TDA Request"] --> B["Parse method name"]
    B --> C["Remove 'TD-' or 'TDA-' prefix"]
    C --> D["Validate with libxc"]
    D --> E["Initialize DFT ground state"]
    E --> F{Method Type}
    F -->|"TDA"| G["tddft.TDA()"]
    F -->|"TD-DFT"| H["tddft.TDDFT()"]
    
    G --> I["Calculate excited states"]
    H --> I
    I --> J["Store energies in electronic_states"]
    I --> K["Calculate oscillator strengths"]
    
    L["Gradient Request"] --> M["Ground state gradients"]
    L --> N["Excited state gradients (TDA/TDDFT)"]
    M --> O["electronic_states[0].energy_gradients"]
    N --> P["electronic_states[i].energy_gradients"]
```

**Sources:** [mlatom/interfaces/pyscf_interface.py:136-198]()

#### DM21 Neural Functionals
```mermaid
flowchart TD
    A["DM21 Method Request"] --> B["Import density_functional_approximation_dm21"]
    B --> C["Initialize RKS/UKS with B3LYP"]
    C --> D["Run initial B3LYP calculation"]
    D --> E["Get density matrix dm0"]
    E --> F["Replace _numint with NeuralNumInt"]
    F --> G["Set DM21 functional variant"]
    G --> H["Relax convergence tolerances"]
    H --> I["kernel(dm0=dm0)"]
    I --> J{Converged?}
    J -->|"Yes"| K["Return e_tot"]
    J -->|"No"| L["Raise ValueError"]
```

**Sources:** [mlatom/interfaces/pyscf_interface.py:310-351]()

## Thermochemistry and Vibrational Analysis

The interface provides comprehensive thermochemical analysis through integration with PySCF's harmonic analysis capabilities.

### Thermochemistry Calculation Flow

```mermaid
flowchart TD
    A["molecule with hessian"] --> B["thermo_calculation()"]
    B --> C["Create PySCF gto.Mole"]
    C --> D["Reconstruct hessian matrix"]
    D --> E["harmonic_analysis()"]
    E --> F["Extract frequencies"]
    F --> G["Calculate normal modes"]
    G --> H["Thermochemical properties"]
    
    H --> I["ZPE - Zero Point Energy"]
    H --> J["U0, H0 - Internal Energy, Enthalpy at 0K"]
    H --> K["U, H, G, S - 298K thermodynamics"]
    H --> L["frequencies, force_constants"]
    H --> M["reduced_masses, normal_modes"]
    
    I --> N["Update molecule properties"]
    J --> N
    K --> N
    L --> N
    M --> N
```

**Sources:** [mlatom/interfaces/pyscf_interface.py:365-421](), [mlatom/interfaces/pyscf_interface.py:423-524]()

### Thermodynamic Property Calculations

The interface implements a modified version of PySCF's thermochemistry calculations with contributions from electronic, translational, rotational, and vibrational degrees of freedom.

| Property | Components | Storage Location |
|----------|------------|------------------|
| **Zero Point Energy** | 0.5 * Σ(hν) | `molecule.ZPE` |
| **Internal Energy (0K)** | E₀ + ZPE | `molecule.U0` |
| **Enthalpy (298K)** | U + PV terms | `molecule.H` |
| **Gibbs Free Energy** | H - TS | `molecule.G` |
| **Entropy** | Electronic + Trans + Rot + Vib | `molecule.S` |

**Sources:** [mlatom/interfaces/pyscf_interface.py:409-419](), [mlatom/interfaces/pyscf_interface.py:513-522]()

## Advanced Features

### Threading and Performance Optimization

```mermaid
flowchart TD
    A["nthreads parameter"] --> B{nthreads specified?}
    B -->|"No"| C["Use cpu_count()"]
    B -->|"Yes"| D["Use specified value"]
    
    C --> E["self.nthreads = cpu_count()"]
    D --> E
    E --> F["pyscf.lib.misc.num_threads(n)"]
    F --> G["Density fitting check"]
    
    G --> H{Method supports DF?}
    H -->|"Yes & requested"| I["density_fit().run()"]
    H -->|"No"| J["Standard kernel()"]
    I --> K["Performance optimized calculation"]
    J --> K
```

**Sources:** [mlatom/interfaces/pyscf_interface.py:23-30](), [mlatom/interfaces/pyscf_interface.py:62-66](), [mlatom/interfaces/pyscf_interface.py:215-226]()

### Error Handling and Convergence

The interface implements robust error handling for various failure modes:

- **Convergence failures**: Checks `pyscf_method.converged` before storing results
- **Method support validation**: Pre-flight checks using `is_method_supported()`
- **Gradient limitations**: Method-specific restrictions (e.g., no FCI gradients)
- **DM21 requirements**: Dependency checking and installation guidance

**Sources:** [mlatom/interfaces/pyscf_interface.py:231-237](), [mlatom/interfaces/pyscf_interface.py:240-242](), [mlatom/interfaces/pyscf_interface.py:318-322]()

### Dipole Derivatives (Experimental)

```mermaid
flowchart TD
    A["calculate_dipole_derivatives=True"] --> B["Import pyscf.prop infrared"]
    B --> C{Method Type}
    C -->|"RHF"| D["rhf.Infrared()"]
    C -->|"RKS"| E["rks.Infrared()"]
    C -->|"UHF"| F["uhf.Infrared()"]
    C -->|"UKS"| G["uks.Infrared()"]
    
    D --> H["kernel_dipderiv()"]
    E --> H
    F --> H
    G --> H
    
    H --> I["Convert units (Debye)"]
    I --> J["Reshape and store"]
    J --> K["molecule.dipole_derivatives"]
    
    B --> L{Import Success?}
    L -->|"No"| M["Warning: package not found"]
```

**Sources:** [mlatom/interfaces/pyscf_interface.py:528-554]()

---