# Restraint Search and Absolute Free Energy

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [python/BioSimSpace/Sandpit/Exscientia/Align/_decouple.py](python/BioSimSpace/Sandpit/Exscientia/Align/_decouple.py)
- [python/BioSimSpace/Sandpit/Exscientia/FreeEnergy/_restraint.py](python/BioSimSpace/Sandpit/Exscientia/FreeEnergy/_restraint.py)
- [python/BioSimSpace/Sandpit/Exscientia/FreeEnergy/_restraint_search.py](python/BioSimSpace/Sandpit/Exscientia/FreeEnergy/_restraint_search.py)
- [python/BioSimSpace/Sandpit/Exscientia/Process/_somd.py](python/BioSimSpace/Sandpit/Exscientia/Process/_somd.py)
- [tests/Sandpit/Exscientia/FreeEnergy/test_restraint.py](tests/Sandpit/Exscientia/FreeEnergy/test_restraint.py)
- [tests/Sandpit/Exscientia/FreeEnergy/test_restraint_search.py](tests/Sandpit/Exscientia/FreeEnergy/test_restraint_search.py)
- [tests/Sandpit/Exscientia/Protocol/test_config.py](tests/Sandpit/Exscientia/Protocol/test_config.py)

</details>



## Purpose and Scope

This document covers the automated selection of receptor-ligand restraints for absolute binding free energy (ABFE) calculations in BioSimSpace. The system provides tools to run unrestrained simulations, analyze conformational sampling, and automatically identify optimal restraint anchor points with appropriate force constants. For relative free energy perturbation calculations, see [Relative Free Energy Perturbation](#5.1). For ATM-based binding free energy calculations, see [ATM Method](#5.2).

The restraint search functionality enables:
- Automated selection of Boresch or multiple distance restraints
- Analysis of molecular dynamics trajectories to identify stable receptor-ligand interactions
- Calculation of thermodynamic corrections for restraint imposition and release
- Generation of engine-specific restraint configurations for GROMACS and SOMD

## Restraint Search Workflow

The restraint search process follows a systematic workflow from system preparation through restraint selection to final ABFE calculation setup:

```mermaid
flowchart TD
    subgraph "System Preparation"
        SYS["Solvated System<br/>with Decoupled Molecule"]
        PROTO["Production Protocol<br/>short unrestrained MD"]
    end
    
    subgraph "Restraint Search Execution"
        RS["RestraintSearch"]
        ENGINE["MD Engine<br/>(GROMACS/SOMD)"]
        SIM["Unrestrained Simulation<br/>conformational sampling"]
    end
    
    subgraph "Trajectory Analysis"
        TRAJ["MD Trajectory"]
        METHODS["Analysis Methods<br/>BSS | MDRestraintsGenerator"]
        SELECT["Restraint Selection<br/>anchor point identification"]
    end
    
    subgraph "Restraint Generation"
        RESTRAINT["Restraint Object"]
        CORRECTION["Standard State Correction<br/>analytical/numerical"]
        CONFIG["Engine Configuration<br/>GROMACS .top | SOMD .cfg"]
    end
    
    SYS --> RS
    PROTO --> RS
    RS --> ENGINE
    ENGINE --> SIM
    SIM --> TRAJ
    TRAJ --> METHODS
    METHODS --> SELECT
    SELECT --> RESTRAINT
    RESTRAINT --> CORRECTION
    RESTRAINT --> CONFIG
```

Sources: [python/BioSimSpace/Sandpit/Exscientia/FreeEnergy/_restraint_search.py:106-295](), [tests/Sandpit/Exscientia/FreeEnergy/test_restraint_search.py:47-66]()

## Supported Restraint Types

BioSimSpace supports two primary restraint types for ABFE calculations, each with specific use cases and theoretical foundations:

| Restraint Type | Description | Components | Use Case |
|----------------|-------------|------------|----------|
| **Boresch** | Harmonic restraints on 1 bond, 2 angles, 3 dihedrals | 6 DOF reduction | Standard ABFE protocol |
| **Multiple Distance** | Flat-bottom distance restraints between atom pairs | Variable number of distance restraints | Alternative ABFE approach |

### Boresch Restraints

Boresch restraints utilize six harmonic restraints to reduce translational and rotational degrees of freedom:

```mermaid
graph TD
    subgraph "Receptor Anchors"
        R3["r3<br/>atom"]
        R2["r2<br/>atom"] 
        R1["r1<br/>atom"]
    end
    
    subgraph "Ligand Anchors"
        L1["l1<br/>atom"]
        L2["l2<br/>atom"]
        L3["l3<br/>atom"]
    end
    
    subgraph "Restraint Components"
        BOND["Bond: r1-l1<br/>(r0, kr)"]
        ANGLE1["Angle: r2-r1-l1<br/>(thetaA0, kthetaA)"]
        ANGLE2["Angle: r1-l1-l2<br/>(thetaB0, kthetaB)"]
        DIHED1["Dihedral: r3-r2-r1-l1<br/>(phiA0, kphiA)"]
        DIHED2["Dihedral: r2-r1-l1-l2<br/>(phiB0, kphiB)"]
        DIHED3["Dihedral: r1-l1-l2-l3<br/>(phiC0, kphiC)"]
    end
    
    R1 --- L1
    R2 --- R1
    R1 --- L1
    L1 --- L2
    
    R1 -.-> BOND
    R2 -.-> ANGLE1
    L2 -.-> ANGLE2
    R3 -.-> DIHED1
    L3 -.-> DIHED3
```

Sources: [python/BioSimSpace/Sandpit/Exscientia/FreeEnergy/_restraint.py:84-115](), [python/BioSimSpace/Sandpit/Exscientia/FreeEnergy/_restraint_search.py:721-827]()

## RestraintSearch Class

The `RestraintSearch` class manages the execution of unrestrained simulations and subsequent restraint analysis:

### Class Architecture

```mermaid
classDiagram
    class RestraintSearch {
        -_system: System
        -_protocol: Protocol
        -_process: Process
        -_engine: str
        -_restraint_types: list
        +__init__(system, protocol, engine)
        +start()
        +wait()
        +analyse(restraint_type, method)
        +_initialise_process()
        +_boresch_restraint()
        +_multiple_distance_restraint()
    }
    
    class Process {
        +getTrajectory()
        +isRunning()
        +isError()
    }
    
    class Trajectory {
        +getTrajectory(format)
        +nFrames()
    }
    
    class Restraint {
        +getCorrection()
        +toString()
    }
    
    RestraintSearch --> Process
    RestraintSearch --> Restraint
    Process --> Trajectory
```

Sources: [python/BioSimSpace/Sandpit/Exscientia/FreeEnergy/_restraint_search.py:106-295]()

### Initialization and Execution

The `RestraintSearch` constructor validates system requirements and initializes the appropriate MD engine:

```python
# System must contain exactly one decoupled molecule
if system.nDecoupledMolecules() != 1:
    raise ValueError("The system must contain a single molecule to be decoupled!")
```

Supported engines are limited to those compatible with restraint analysis:

```python
_engines = ["GROMACS", "SOMD"]
```

Sources: [python/BioSimSpace/Sandpit/Exscientia/FreeEnergy/_restraint_search.py:112-276]()

## Restraint Analysis Methods

The analysis phase supports two distinct approaches for restraint selection, each with different theoretical foundations and implementation details:

### Method Comparison

| Method | Implementation | Restraint Types | Selection Algorithm |
|--------|----------------|-----------------|-------------------|
| **MDRestraintsGenerator** | External package | Boresch only | Stability-based clustering |
| **BSS** | Native BioSimSpace | Boresch, Multiple Distance | Statistical analysis + clustering |

### BSS Method Implementation

The native BioSimSpace method performs statistical analysis of conformational fluctuations:

```mermaid
flowchart LR
    subgraph "Trajectory Processing"
        TRAJ["MD Trajectory<br/>MDAnalysis Universe"]
        ATOMS["Anchor Atom Selection<br/>ligand: 'not name H*'<br/>receptor: 'protein and name CA C N'"]
    end
    
    subgraph "Statistical Analysis"
        DIST["Distance Matrix<br/>all pairwise distances"]
        CLUSTER["K-means Clustering<br/>identify stable pairs"]
        STATS["Statistical Metrics<br/>mean, std, fluctuations"]
    end
    
    subgraph "Force Constant Estimation"
        FLUCT["Fluctuation Analysis<br/>σ² from trajectory"]
        KC["Force Constants<br/>k = kT/σ²"]
        EQUIL["Equilibrium Values<br/>time-averaged"]
    end
    
    TRAJ --> ATOMS
    ATOMS --> DIST
    DIST --> CLUSTER
    CLUSTER --> STATS
    STATS --> FLUCT
    FLUCT --> KC
    FLUCT --> EQUIL
```

Sources: [python/BioSimSpace/Sandpit/Exscientia/FreeEnergy/_restraint_search.py:816-827](), [python/BioSimSpace/Sandpit/Exscientia/FreeEnergy/_restraint_search.py:1010-1200]()

### MDRestraintsGenerator Integration

When using the external `MDRestraintsGenerator` package, the workflow delegates to specialized algorithms:

```python
# Find ligand atoms compatible with restraint attachment
ligand_atoms = _search.find_ligand_atoms(
    u, l_selection=ligand_selection_str, p_align=receptor_selection_str
)

# Create Boresch restraint finder
boresch = _FindBoreschRestraint(u, atom_set)
boresch.run()
```

Sources: [python/BioSimSpace/Sandpit/Exscientia/FreeEnergy/_restraint_search.py:888-902]()

## Restraint Class and Corrections

The `Restraint` class encapsulates restraint parameters and provides methods for calculating thermodynamic corrections required for ABFE calculations.

### Class Structure

```mermaid
classDiagram
    class Restraint {
        -_restraint_dict: dict
        -_restraint_type: str
        -_system: System
        -T: Temperature
        +__init__(system, restraint_dict, temperature, restraint_type)
        +getCorrection(method, flavour)
        +toString(engine, perturbation_type)
        +_numerical_correction()
        +_analytical_correction()
        +_gromacs_boresch()
        +_somd_boresch()
        +_gromacs_multiple_distance()
        +_somd_multiple_distance()
    }
    
    class System {
        +getDecoupledMolecules()
        +getIndex(atom)
    }
    
    Restraint --> System
```

Sources: [python/BioSimSpace/Sandpit/Exscientia/FreeEnergy/_restraint.py:75-340]()

### Standard State Corrections

The restraint class provides both numerical and analytical methods for calculating the free energy correction required when imposing or releasing restraints:

#### Numerical Integration
```python
def _numerical_correction(self):
    """Calculate correction using numerical integration over phase space"""
    # Integration bounds and quadrature methods
    # Account for restraint potential in configurational integral
```

#### Analytical Formulae
For Boresch restraints, analytical expressions are available:
- **Boresch flavour**: Uses original Boresch derivation
- **Schrodinger flavour**: Uses alternative analytical form

Sources: [python/BioSimSpace/Sandpit/Exscientia/FreeEnergy/_restraint.py:1247-1500]()

## Engine-Specific Configuration Generation

The `Restraint` class generates engine-specific configuration strings that can be directly incorporated into simulation input files.

### GROMACS Integration

```mermaid
flowchart TD
    subgraph "GROMACS Output Generation"
        RESTRAINT["Restraint Object"]
        BONDS["[ bonds ]<br/>harmonic bond restraints"]
        ANGLES["[ angles ]<br/>harmonic angle restraints"]
        DIHEDRALS["[ dihedrals ]<br/>harmonic dihedral restraints"]
        DISTANCE["[ distance_restraints ]<br/>flat-bottom distance restraints"]
    end
    
    subgraph "Configuration Options"
        LAMBDA["restraint_lambda=True<br/>[ dihedral_restraints ]"]
        PERT["perturbation_type<br/>determines restraint groups"]
    end
    
    RESTRAINT --> BONDS
    RESTRAINT --> ANGLES
    RESTRAINT --> DIHEDRALS
    RESTRAINT --> DISTANCE
    LAMBDA -.-> DIHEDRALS
    PERT -.-> DISTANCE
```

### SOMD Integration

For SOMD simulations, restraints are encoded as configuration dictionary entries:

```python
# Boresch restraints encoded as nested dictionary
boresch_restraints_dictionary = {
    "anchor_points": {"r1": 1, "r2": 2, "r3": 3, "l1": 4, "l2": 5, "l3": 6},
    "equilibrium_values": {"r0": 5.08, "thetaA0": 1.12, ...},
    "force_constants": {"kr": 5.00, "kthetaA": 5.00, ...}
}
```

Sources: [python/BioSimSpace/Sandpit/Exscientia/FreeEnergy/_restraint.py:408-629](), [python/BioSimSpace/Sandpit/Exscientia/FreeEnergy/_restraint.py:1580-1650]()

---