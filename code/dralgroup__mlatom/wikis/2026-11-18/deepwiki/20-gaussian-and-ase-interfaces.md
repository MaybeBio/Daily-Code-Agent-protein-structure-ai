# Gaussian and ASE Interfaces

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [mlatom/interfaces/ase_interface.py](mlatom/interfaces/ase_interface.py)
- [mlatom/interfaces/gaussian_interface.py](mlatom/interfaces/gaussian_interface.py)

</details>



This document covers the integration interfaces between MLatom and external quantum chemistry and molecular simulation packages, specifically the Gaussian quantum chemistry program and the Atomic Simulation Environment (ASE) library. These interfaces enable MLatom to leverage external computational engines for quantum mechanical calculations and advanced molecular simulations.

For information about other quantum chemistry interfaces like PySCF, see [PySCF Interface](#6.1). For DFTB+ and other interfaces, see [DFTB+ and Other Interfaces](#6.3).

## Interface Architecture Overview

The quantum chemistry and simulation interfaces in MLatom follow a consistent pattern where external programs are wrapped by interface classes that conform to MLatom's model framework.

```mermaid
graph TB
    subgraph "MLatom Core"
        MODEL[method_model<br/>Base Class]
        DATA[data.molecule<br/>data.molecular_database]
        TASKS[MLtasks.py<br/>Task Management]
    end
    
    subgraph "External Program Interfaces"
        GAUSS[gaussian_methods<br/>Gaussian Interface]
        ASE_CALC[MLatomCalculator<br/>ASE Calculator]
    end
    
    subgraph "External Programs"
        GAUSS_BIN["Gaussian g16/g09<br/>Binary Executable"]
        ASE_LIB["ASE Library<br/>Optimization Algorithms"]
    end
    
    subgraph "Interface Functions"
        RUN_GAUSS[run_gaussian_job<br/>Job Execution]
        PARSE_GAUSS[parse_gaussian_output<br/>Result Parsing]
        OPT_GEOM[optimize_geometry<br/>ASE Optimization]
        TS_SEARCH[transition_state<br/>TS Methods]
    end
    
    MODEL --> GAUSS
    MODEL --> ASE_CALC
    
    GAUSS --> RUN_GAUSS
    GAUSS --> PARSE_GAUSS
    ASE_CALC --> OPT_GEOM
    ASE_CALC --> TS_SEARCH
    
    RUN_GAUSS --> GAUSS_BIN
    PARSE_GAUSS --> GAUSS_BIN
    OPT_GEOM --> ASE_LIB
    TS_SEARCH --> ASE_LIB
    
    DATA --> GAUSS
    DATA --> ASE_CALC
    TASKS --> GAUSS
    TASKS --> ASE_CALC
```

Sources: [mlatom/interfaces/gaussian_interface.py:1-1035](), [mlatom/interfaces/ase_interface.py:1-261]()

## Gaussian Interface

The Gaussian interface provides comprehensive integration with the Gaussian quantum chemistry package, supporting both single-point calculations and complex workflows.

### Core Components

```mermaid
graph TB
    subgraph "gaussian_methods Class"
        INIT["__init__()<br/>Setup & Validation"]
        PREDICT["predict()<br/>Main Calculation Method"]
        IS_FOUND["is_program_found()<br/>Program Detection"]
    end
    
    subgraph "Job Management"
        RUN_JOB[run_gaussian_job<br/>Input Generation & Execution]
        WRITE_INPUT[write_gaussian_input_file<br/>Input File Creation]
        CHECK_GAUSS[check_gaussian<br/>Environment Validation]
    end
    
    subgraph "Result Processing"
        PARSE_OUTPUT[parse_gaussian_output<br/>Output File Parsing]
        READ_HESS[read_Hessian_matrix_from_Gaussian_chkfile<br/>Checkpoint File Reading]
    end
    
    subgraph "Gaussian Program"
        G16_G09["Gaussian g16/g09<br/>$GAUSS_EXEDIR"]
        CHK_UTILS["chkchk Utility<br/>Checkpoint Processing"]
    end
    
    INIT --> CHECK_GAUSS
    PREDICT --> RUN_JOB
    RUN_JOB --> WRITE_INPUT
    RUN_JOB --> G16_G09
    PARSE_OUTPUT --> READ_HESS
    READ_HESS --> CHK_UTILS
    RUN_JOB --> PARSE_OUTPUT
```

Sources: [mlatom/interfaces/gaussian_interface.py:18-142]()

### Calculation Types and Features

| Feature | Implementation | Key Parameters |
|---------|---------------|----------------|
| **Single Point Energy** | Direct method specification | `method='B3LYP/6-31G*'` |
| **Geometry Optimization** | External potential interface | `external_task='opt'` |
| **Frequency Analysis** | Harmonic and anharmonic | `calculate_hessian=True` |
| **Excited States** | TD-DFT calculations | `nstates>1`, TD method parsing |
| **Thermochemistry** | Complete property extraction | ZPE, enthalpies, free energies |
| **Forces** | Energy gradient calculations | `calculate_energy_gradients=True` |

Sources: [mlatom/interfaces/gaussian_interface.py:70-112](), [mlatom/interfaces/gaussian_interface.py:143-240]()

### Advanced Features

The Gaussian interface supports sophisticated quantum chemistry workflows:

```mermaid
graph LR
    subgraph "Calculation Types"
        SP["Single Point<br/>Energy & Properties"]
        OPT["Geometry<br/>Optimization"]
        FREQ["Frequency<br/>Analysis"]
        TD["Excited States<br/>TD-DFT"]
        IRC["Reaction Path<br/>IRC Calculations"]
    end
    
    subgraph "Property Extraction"
        ENERGY["SCF Energies<br/>Multiple Levels"]
        GRAD["Energy Gradients<br/>Forces"]
        HESS["Hessian Matrix<br/>Second Derivatives"]
        THERMO["Thermochemistry<br/>G, H, S, ZPE"]
        ANHARM["Anharmonic<br/>Frequencies & IR"]
    end
    
    subgraph "File Management"
        CHK["Checkpoint Files<br/>%chk directive"]
        LOG["Output Parsing<br/>Archive extraction"]
        TRAJ["Optimization<br/>Trajectories"]
    end
    
    SP --> ENERGY
    OPT --> GRAD
    OPT --> TRAJ
    FREQ --> HESS
    FREQ --> THERMO
    FREQ --> ANHARM
    TD --> ENERGY
    IRC --> TRAJ
    
    HESS --> CHK
    ANHARM --> LOG
```

Sources: [mlatom/interfaces/gaussian_interface.py:322-950]()

## ASE Interface

The ASE interface integrates MLatom models with the Atomic Simulation Environment, enabling advanced molecular simulations and optimization algorithms.

### Architecture

```mermaid
graph TB
    subgraph "ASE Integration Layer"
        CALC[MLatomCalculator<br/>ASE Calculator Implementation]
        OPT_GEOM[optimize_geometry<br/>General Optimization]
        TS_FUNC[transition_state<br/>TS Search Dispatcher]
        THERMO[thermochemistry<br/>Statistical Mechanics]
    end
    
    subgraph "Optimization Methods"
        LBFGS["LBFGS<br/>Quasi-Newton"]
        BFGS["BFGS<br/>Newton Method"]
        FIRE["FIRE<br/>Fast Relaxation"]
        CG["ConjugateGradient<br/>CG Method"]
    end
    
    subgraph "Transition State Methods"
        DIMER[dimer_method<br/>Dimer Algorithm]
        NEB[nudged_elastic_band<br/>NEB Method]
    end
    
    subgraph "ASE Core"
        ASE_OPT["ase.optimize<br/>Optimization Engines"]
        ASE_DIMER["ase.dimer<br/>Dimer Implementation"]
        ASE_NEB["ase.neb<br/>NEB Implementation"]
        ASE_THERMO["ase.thermochemistry<br/>IdealGasThermo"]
    end
    
    OPT_GEOM --> CALC
    TS_FUNC --> DIMER
    TS_FUNC --> NEB
    
    OPT_GEOM --> LBFGS
    OPT_GEOM --> BFGS
    OPT_GEOM --> FIRE
    OPT_GEOM --> CG
    
    LBFGS --> ASE_OPT
    DIMER --> ASE_DIMER
    NEB --> ASE_NEB
    THERMO --> ASE_THERMO
```

Sources: [mlatom/interfaces/ase_interface.py:23-213]()

### MLatomCalculator Implementation

The `MLatomCalculator` class bridges MLatom models with ASE's calculator interface:

| Method | Purpose | Key Implementation |
|--------|---------|-------------------|
| `__init__()` | Calculator setup | Model storage, trajectory tracking |
| `calculate()` | Energy/forces computation | Model prediction, unit conversion |
| `implemented_properties` | Supported properties | `['energy', 'forces']` |

The calculator handles coordinate conversion between ASE atoms objects and MLatom molecules through temporary XYZ files.

Sources: [mlatom/interfaces/ase_interface.py:172-213]()

### Constrained Optimization

The ASE interface supports various geometric constraints:

```mermaid
graph TB
    subgraph "Constraint Types"
        BOND[FixBondLengths<br/>Bond Length Constraints]
        INTERNAL[FixInternals<br/>Internal Coordinates]
        CUSTOM["Custom Constraints<br/>User-Defined"]
    end
    
    subgraph "Internal Coordinates"
        BONDS["bonds<br/>Bond Distances"]
        ANGLES["angles_deg<br/>Bond Angles"]
        DIHEDRALS["dihedrals_deg<br/>Dihedral Angles"]
    end
    
    subgraph "Implementation"
        CONSTRAINTS["constraints kwarg<br/>User Specification"]
        ASE_CONST["ase.constraints<br/>ASE Implementation"]
        ATOMS_SET["atoms.set_constraint()<br/>Application"]
    end
    
    CONSTRAINTS --> BOND
    CONSTRAINTS --> INTERNAL
    
    INTERNAL --> BONDS
    INTERNAL --> ANGLES
    INTERNAL --> DIHEDRALS
    
    BOND --> ASE_CONST
    INTERNAL --> ASE_CONST
    ASE_CONST --> ATOMS_SET
```

Sources: [mlatom/interfaces/ase_interface.py:42-68]()

### Transition State Methods

The interface provides two primary transition state search methods:

#### Dimer Method
- **Purpose**: Local transition state optimization
- **Implementation**: Uses `ase.dimer.DimerControl` and `MinModeAtoms`
- **Key Features**: Random seed control, displacement calculations
- **Usage**: Single saddle point searches

#### Nudged Elastic Band (NEB)
- **Purpose**: Reaction pathway and transition state finding
- **Implementation**: Uses `ase.neb.NEB` with interpolated images
- **Key Features**: Multiple image optimization, pathway visualization
- **Usage**: Connecting reactants to products via minimum energy path

Sources: [mlatom/interfaces/ase_interface.py:91-169]()

## Integration with MLatom Core Systems

Both interfaces integrate seamlessly with MLatom's core data structures and task management:

```mermaid
graph TB
    subgraph "MLatom Core Data"
        MOL[data.molecule<br/>Molecular Structure]
        MOLDB[data.molecular_database<br/>Multiple Molecules]
        TRAJ[data.molecular_trajectory<br/>Optimization Paths]
    end
    
    subgraph "Interface Operations"
        GAUSS_PRED[gaussian_methods.predict<br/>QM Calculations]
        ASE_OPT[ase_interface.optimize_geometry<br/>Structure Optimization]
        ASE_TS[ase_interface.transition_state<br/>TS Searches]
    end
    
    subgraph "Property Updates"
        ENERGY["energy<br/>Electronic Energy"]
        GRAD["energy_gradients<br/>Forces"]
        HESS["hessian<br/>Second Derivatives"]
        FREQ["frequencies<br/>Vibrational Modes"]
        THERMO_PROPS["G, H, S, ZPE<br/>Thermochemistry"]
    end
    
    MOL --> GAUSS_PRED
    MOL --> ASE_OPT
    MOL --> ASE_TS
    
    GAUSS_PRED --> ENERGY
    GAUSS_PRED --> GRAD
    GAUSS_PRED --> HESS
    GAUSS_PRED --> FREQ
    GAUSS_PRED --> THERMO_PROPS
    
    ASE_OPT --> TRAJ
    ASE_TS --> TRAJ
    
    TRAJ --> MOLDB
```

Sources: [mlatom/interfaces/gaussian_interface.py:84-142](), [mlatom/interfaces/ase_interface.py:32-89]()

## Usage Patterns and Workflows

### Gaussian Workflow
1. **Initialization**: Set up `gaussian_methods` with method specification
2. **Environment Check**: Validate `GAUSS_EXEDIR` environment variable
3. **Job Execution**: Generate input files, run calculations, parse outputs
4. **Result Integration**: Update molecule objects with computed properties

### ASE Workflow  
1. **Calculator Setup**: Create `MLatomCalculator` with MLatom model
2. **Geometry Conversion**: Convert between MLatom molecules and ASE atoms
3. **Optimization/Search**: Run ASE algorithms with trajectory tracking
4. **Result Extraction**: Update MLatom data structures with optimized geometries

Both interfaces maintain full compatibility with MLatom's task management system and can be invoked through the standard CLI or programmatic interfaces.

Sources: [mlatom/interfaces/gaussian_interface.py:38-61](), [mlatom/interfaces/ase_interface.py:23-89]()

---