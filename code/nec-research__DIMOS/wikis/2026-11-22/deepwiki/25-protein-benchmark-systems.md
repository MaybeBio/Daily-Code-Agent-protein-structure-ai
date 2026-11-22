# Protein Benchmark Systems

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [benchmark/proteins/ala2_tip3p.gro](benchmark/proteins/ala2_tip3p.gro)
- [benchmark/proteins/ala2_tip3p.top](benchmark/proteins/ala2_tip3p.top)
- [benchmark/proteins/benchmark_proteins.py](benchmark/proteins/benchmark_proteins.py)
- [benchmark/proteins/dhfr.gro](benchmark/proteins/dhfr.gro)
- [benchmark/proteins/dhfr.top](benchmark/proteins/dhfr.top)
- [benchmark/proteins/trp-cage_sol.gro](benchmark/proteins/trp-cage_sol.gro)
- [benchmark/proteins/trp-cage_sol.top](benchmark/proteins/trp-cage_sol.top)

</details>



## Purpose and Scope

This document describes the protein benchmark systems included in DIMOS for performance testing and validation. These benchmarks test molecular dynamics simulations of protein systems with varying complexity, constraint configurations, and force field types. The protein benchmarks complement the water system benchmarks (see [6.2](#6.2)) and are used for platform comparison (see [6.3](#6.3)).

The three protein test systems—alanine dipeptide, DHFR, and Trp-cage—span a range of system sizes and computational complexity. Each system can be simulated using classical molecular mechanics (MM), hybrid ML/MM, or pure machine learning force fields with or without constraints.

## Benchmark Test Systems

DIMOS includes three standard protein systems for benchmarking, each representing different complexity levels and simulation characteristics:

```mermaid
graph TB
    subgraph "Alanine Dipeptide (ala2_tip3p)"
        ALA2_SIZE["22 protein atoms<br/>749 TIP3P waters<br/>2,269 total atoms"]
        ALA2_USE["Small, fast-folding<br/>Basic validation<br/>Quick performance tests"]
    end
    
    subgraph "DHFR (dhfr)"
        DHFR_SIZE["~2,500 protein atoms<br/>~7,000 water molecules<br/>23,558 total atoms"]
        DHFR_USE["Medium-sized enzyme<br/>Representative biomolecule<br/>Standard MD benchmark"]
    end
    
    subgraph "Trp-cage (trp-cage_sol)"
        TRPCAGE_SIZE["304 protein atoms<br/>2,199 solvent atoms<br/>7,660 total atoms"]
        TRPCAGE_USE["20-residue miniprotein<br/>Fast-folding dynamics<br/>Intermediate complexity"]
    end
    
    ALA2_SIZE --> ALA2_USE
    DHFR_SIZE --> DHFR_USE
    TRPCAGE_SIZE --> TRPCAGE_USE
    
    style ALA2_SIZE fill:#f9f9f9
    style DHFR_SIZE fill:#f9f9f9
    style TRPCAGE_SIZE fill:#f9f9f9
```

**Sources:** [benchmark/proteins/ala2_tip3p.gro:1-2](), [benchmark/proteins/dhfr.gro:1-2](), [benchmark/proteins/trp-cage_sol.gro:1-2]()

### Alanine Dipeptide (ala2_tip3p)

The smallest benchmark system consists of an alanine dipeptide capped with ACE and NME groups, solvated in 749 TIP3P water molecules. This system contains 2,269 atoms total with 22 protein atoms.

| Property | Value |
|----------|-------|
| Protein atoms | 22 (ACE-ALA-NME) |
| Water molecules | 749 (TIP3P model) |
| Total atoms | 2,269 |
| Box dimensions | ~3.0 nm cubic |
| Primary use | Fast validation, constraint testing |

The structure file [benchmark/proteins/ala2_tip3p.gro]() contains coordinates in GROMACS format, and the topology [benchmark/proteins/ala2_tip3p.top]() defines the Amber force field parameters including atom types, bonds, angles, dihedrals, and the TIP3P water model.

**Sources:** [benchmark/proteins/ala2_tip3p.gro:1-2269](), [benchmark/proteins/ala2_tip3p.top:1-278]()

### DHFR (dhfr)

DHFR (dihydrofolate reductase) is a medium-sized enzyme with approximately 160 residues, representing a realistic biomolecular system. The complete system includes roughly 7,000 water molecules for a total of 23,558 atoms.

| Property | Value |
|----------|-------|
| Protein residues | ~160 (full enzyme) |
| Protein atoms | ~2,500 |
| Water molecules | ~7,000 |
| Total atoms | 23,558 |
| Primary use | Standard MD benchmark, realistic system size |

This system tests performance on typical protein simulations encountered in computational biology research. The larger system size better represents production MD workloads.

**Sources:** [benchmark/proteins/dhfr.gro:1-2](), [benchmark/proteins/dhfr.top:1-40]()

### Trp-cage (trp-cage_sol)

Trp-cage is a 20-residue miniprotein known for its fast folding dynamics. The benchmark includes 304 protein atoms and 2,199 solvent atoms, totaling 7,660 atoms. This intermediate-sized system bridges the gap between the minimal alanine dipeptide and the larger DHFR enzyme.

| Property | Value |
|----------|-------|
| Protein residues | 20 |
| Protein atoms | 304 |
| Solvent atoms | 2,199 |
| Total atoms | 7,660 |
| Primary use | Folding studies, intermediate-size benchmark |

**Sources:** [benchmark/proteins/trp-cage_sol.gro:1-2](), [benchmark/proteins/trp-cage_sol.top:1-40]()

## Benchmark Configurations

The protein benchmarking script [benchmark/proteins/benchmark_proteins.py]() tests six different simulation configurations for each protein system, varying the force field type and constraint settings:

```mermaid
graph LR
    subgraph "Force Field Types"
        MM["Classical MM<br/>GromacsForceField"]
        MLMM["Hybrid ML/MM<br/>MLMMsystem"]
        ML["Pure ML<br/>as_mace_system"]
    end
    
    subgraph "Constraint Options"
        NOCONST["No Constraints<br/>timestep=0.5 fs"]
        CONST["H-angle Constraints<br/>timestep=2.0 fs"]
    end
    
    MM --> NOCONST
    MM --> CONST
    MLMM --> NOCONST
    MLMM --> CONST
    ML --> NOCONST
    ML --> CONST
    
    NOCONST --> NO_MM["no_constraints_mm"]
    CONST --> C_MM["constraints_mm"]
    NOCONST --> NO_MLMM["no_constraints_mlmm"]
    CONST --> C_MLMM["constraints_mlmm"]
    NOCONST --> NO_ML["no_constraints_ml"]
    CONST --> C_ML["constraints_ml"]
```

**Sources:** [benchmark/proteins/benchmark_proteins.py:21-44]()

### Configuration Details

The benchmark script accepts two command-line arguments: the system name and the configuration name.

**System names:**
- `ala2_tip3p` - Alanine dipeptide with TIP3P water
- `dhfr` - DHFR enzyme
- `trp-cage_sol` - Trp-cage miniprotein

**Configuration names:**
- `no_constraints_mm` - Classical MM without constraints (0.5 fs timestep)
- `constraints_mm` - Classical MM with H-angle constraints (2.0 fs timestep)
- `no_constraints_mlmm` - Hybrid ML/MM without constraints (0.5 fs timestep)
- `constraints_mlmm` - Hybrid ML/MM with H-angle constraints (2.0 fs timestep)
- `no_constraints_ml` - Pure ML without constraints (0.5 fs timestep)
- `constraints_ml` - Pure ML with H-angle constraints (2.0 fs timestep)

The constraint option `constraint_option="h_angles"` constrains hydrogen bonds and angles, enabling a 4× larger timestep (2.0 fs vs 0.5 fs) for improved performance without sacrificing accuracy.

**Sources:** [benchmark/proteins/benchmark_proteins.py:16-29]()

### Force Field Implementations

Each configuration uses a different force field setup, implemented through distinct code paths:

**Classical MM (no_constraints_mm, constraints_mm):**
```python
# Line 31
base_sys = dimos.GromacsForceField(f"{system}.top", f"{system}.gro",
                                    cutoff=10, switch_distance=7.5, 
                                    nonbonded_type="PME", 
                                    constraint_option=constraint_option)
```

**Hybrid ML/MM (no_constraints_mlmm, constraints_mlmm):**
```python
# Lines 36-41
ml_atoms = base_sys.other_molecules[0]
system_excluding_protein = dimos.GromacsForceField(..., 
                                                     excluded_bonded_atoms=ml_atoms)
smaller_gromacs_ml_system = system_excluding_protein.as_mace_system(
                                "mace-mp-large", atom_range=(0,len(ml_atoms)))
syst = dimos.mlmm.MLMMsystem(ml_atoms, smaller_gromacs_ml_system, 
                              system_excluding_protein)
```

**Pure ML (no_constraints_ml, constraints_ml):**
```python
# Lines 43-44
syst = base_sys.as_mace_system("mace-mp-large")
syst.constraint_handler = base_sys.constraint_handler
```

The hybrid ML/MM approach treats the protein with the MACE machine learning potential while using classical force fields for the solvent environment, providing a balance between accuracy and computational cost.

**Sources:** [benchmark/proteins/benchmark_proteins.py:31-44]()

## Benchmark Execution Workflow

The benchmarking process follows a structured workflow to ensure accurate performance measurements:

```mermaid
flowchart TD
    START["Start: benchmark_proteins.py<br/>system + config arguments"]
    SETUP["Setup Phase<br/>torch.set_default_dtype(float32)<br/>torch.set_default_device(cuda:0)"]
    LOAD["Load System<br/>dimos.read_positions()<br/>GromacsForceField()"]
    
    FFSELECT{"Force Field Type"}
    MM["Classical MM<br/>base_sys"]
    MLMM["Hybrid ML/MM<br/>MLMMsystem"]
    ML["Pure ML<br/>as_mace_system()"]
    
    INTEGRATOR["Create Integrator<br/>NoseHooverDynamics<br/>timestep, T=300K, tau=0.05"]
    SIMULATION["Create Simulation<br/>MDSimulation(syst, integrator)"]
    
    COMPILE["Compile Simulation<br/>torch.compile(sim.step)<br/>mode='max-autotune-no-cudagraphs'"]
    
    WARMUP["Warmup Phase<br/>50 iterations<br/>25 steps each"]
    MEASURE["Measurement Phase<br/>50 iterations<br/>50 steps each<br/>Record timing & energy"]
    
    OUTPUT["Write Results<br/>{system}_{config}_benchmark.dat<br/>ns/day ± std"]
    
    START --> SETUP
    SETUP --> LOAD
    LOAD --> FFSELECT
    FFSELECT -->|MM| MM
    FFSELECT -->|ML/MM| MLMM
    FFSELECT -->|ML| ML
    MM --> INTEGRATOR
    MLMM --> INTEGRATOR
    ML --> INTEGRATOR
    INTEGRATOR --> SIMULATION
    SIMULATION --> COMPILE
    COMPILE --> WARMUP
    WARMUP --> MEASURE
    MEASURE --> OUTPUT
```

**Sources:** [benchmark/proteins/benchmark_proteins.py:1-73]()

### Initialization Parameters

The benchmark script uses consistent parameters across all configurations:

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `torch.float32` | Default dtype | Balance precision and performance |
| `cuda:0` | Default device | GPU acceleration |
| `c_graph` | `False` | Disable CUDA graphs |
| `warmup_iterations` | 50 | Stabilize compilation and caching |
| `steps_per_warmup` | 25 | Steps per warmup iteration |
| `measure_iterations` | 50 | Number of timed measurements |
| `steps_per_measure` | 50 | Steps per measurement iteration |
| Temperature | 300.0 K | Thermostat temperature |
| Nose-Hoover tau | 0.05 | Coupling time constant |

**Sources:** [benchmark/proteins/benchmark_proteins.py:8-15](), [benchmark/proteins/benchmark_proteins.py:46-47]()

### Compilation Strategy

The benchmark uses PyTorch's `torch.compile()` to optimize the simulation step function:

```python
# Lines 49-51
torch.compiler.reset()
torch._dynamo.reset()
sim_step = torch.compile(sim.step, mode="max-autotune-no-cudagraphs")
```

The `"max-autotune-no-cudagraphs"` mode enables aggressive optimizations without CUDA graphs, which provides better compatibility while maintaining high performance. The compiler is reset before compilation to ensure clean state.

**Sources:** [benchmark/proteins/benchmark_proteins.py:49-51]()

### Warmup and Measurement Phases

The benchmark separates warmup and measurement to account for compilation overhead:

**Warmup Phase (50 iterations × 25 steps):**
- Allows PyTorch compilation to complete
- Stabilizes GPU kernel caching
- Ensures thermal equilibrium of hardware

**Measurement Phase (50 iterations × 50 steps):**
- Records wall-clock time per iteration
- Calculates ns/day throughput
- Measures potential energy for validation

Each measurement iteration records:
- Total elapsed time
- Time per step
- Throughput in ns/day (nanoseconds simulated per 24-hour period)
- Current potential energy

**Sources:** [benchmark/proteins/benchmark_proteins.py:53-69]()

## File Structure and Formats

Each protein benchmark system consists of paired GROMACS-format files:

```mermaid
graph TB
    subgraph "System Files"
        GRO[".gro File<br/>Coordinate file<br/>Atomic positions + box"]
        TOP[".top File<br/>Topology file<br/>Force field parameters"]
    end
    
    subgraph "GRO Contents"
        GRO_HEADER["Header line: system name"]
        GRO_NATOMS["Atom count"]
        GRO_COORDS["Atom records:<br/>resnum, resname, atomname<br/>x, y, z coordinates"]
        GRO_BOX["Box vectors"]
    end
    
    subgraph "TOP Contents"
        TOP_DEFAULTS["[defaults] section<br/>Combination rules"]
        TOP_ATOMTYPES["[atomtypes] section<br/>sigma, epsilon parameters"]
        TOP_MOLTYPE["[moleculetype] section<br/>Protein definition"]
        TOP_ATOMS["[atoms] section<br/>Charges, masses"]
        TOP_BONDS["[bonds] section<br/>Bond parameters"]
        TOP_ANGLES["[angles] section<br/>Angle parameters"]
        TOP_DIHEDRALS["[dihedrals] section<br/>Torsion parameters"]
        TOP_MOLECULES["[molecules] section<br/>Molecule counts"]
    end
    
    GRO --> GRO_HEADER
    GRO_HEADER --> GRO_NATOMS
    GRO_NATOMS --> GRO_COORDS
    GRO_COORDS --> GRO_BOX
    
    TOP --> TOP_DEFAULTS
    TOP_DEFAULTS --> TOP_ATOMTYPES
    TOP_ATOMTYPES --> TOP_MOLTYPE
    TOP_MOLTYPE --> TOP_ATOMS
    TOP_ATOMS --> TOP_BONDS
    TOP_BONDS --> TOP_ANGLES
    TOP_ANGLES --> TOP_DIHEDRALS
    TOP_DIHEDRALS --> TOP_MOLECULES
```

**Sources:** [benchmark/proteins/ala2_tip3p.gro:1-2269](), [benchmark/proteins/ala2_tip3p.top:1-278]()

### GROMACS Structure File (.gro)

The `.gro` file contains atomic coordinates in a fixed-format ASCII layout:

**Line 1:** System description (comment line)
**Line 2:** Total number of atoms
**Lines 3-N:** Atom records with format:
- Residue number (5 digits)
- Residue name (5 characters)
- Atom name (5 characters)
- Atom serial number (5 digits)
- x, y, z coordinates (3 × 8.3 format, nm)

**Last line:** Box vectors (3 or 9 values, nm)

Example from ala2_tip3p.gro:
```
GROningen MAchine for Chemical Simulation
 2269
    1ACE     H1    1   1.591   1.197   1.609
    1ACE    CH3    2   1.538   1.290   1.589
    ...
   3.088000   3.088000   3.088000
```

**Sources:** [benchmark/proteins/ala2_tip3p.gro:1-10]()

### GROMACS Topology File (.top)

The `.top` file defines the force field in multiple sections:

**`[defaults]`** - Fundamental parameters:
- `nbfunc=1`: Lennard-Jones 12-6 potential
- `comb-rule=2`: Lorentz-Berthelot combining rules
- `gen-pairs=no`: Explicit 1-4 interactions
- `fudgeLJ=1.0`, `fudgeQQ=0.833333`: 1-4 scaling factors

**`[atomtypes]`** - Defines atom types with sigma and epsilon parameters

**`[moleculetype]`** - Declares molecule definitions

**`[atoms]`** - Lists atoms with charges and masses

**`[bonds]`, `[angles]`, `[dihedrals]`** - Bonded interaction parameters

**`[pairs]`** - 1-4 nonbonded interactions

**`[molecules]`** - Final section listing molecule counts

**Sources:** [benchmark/proteins/ala2_tip3p.top:17-278]()

## Force Field Parameters

The topology files use Amber-compatible force field parameters with specific conventions:

### Nonbonded Parameters

Atom types are defined with Lennard-Jones parameters:

| Parameter | Unit | Description |
|-----------|------|-------------|
| sigma | nm | Distance parameter (σ) |
| epsilon | kJ/mol | Well depth (ε) |

Example from ala2_tip3p.top:
```
[ atomtypes ]
; name    at.num    mass    charge ptype  sigma      epsilon
H1             1   1.007947  0.00000000  A     0.26495328      0.0656888
C1             6  12.010780  0.00000000  A     0.33996695      0.4577296
O1             8  15.999430  0.00000000  A     0.29599219        0.87864
```

**Sources:** [benchmark/proteins/ala2_tip3p.top:22-31]()

### Bonded Parameters

**Bonds** use harmonic potential: V = (k/2) × (r - r₀)²
```
[ bonds ]
;    ai     aj funct         c0         c1
      2      3     1   0.10900 284512.000000
```
- `c0` = equilibrium length (nm)
- `c1` = force constant (kJ/mol/nm²)

**Angles** use harmonic potential: V = (k/2) × (θ - θ₀)²
```
[ angles ]
;    ai     aj     ak funct         c0         c1
      5      7      8     1   120.0000514 251.040000
```
- `c0` = equilibrium angle (degrees)
- `c1` = force constant (kJ/mol/rad²)

**Dihedrals** use periodic potential: V = k × [1 + cos(nφ - φ₀)]
```
[ dihedrals ]
;    ai     aj     ak     al funct         c0         c1         c2
      6      5      7      8     1  0.0000000  8.3680000  1
```
- `c0` = phase angle (degrees)
- `c1` = force constant (kJ/mol)
- `c2` = multiplicity (n)

**Sources:** [benchmark/proteins/ala2_tip3p.top:66-227]()

## Running Protein Benchmarks

### Command-Line Usage

Execute the benchmark script with system and configuration arguments:

```bash
cd benchmark/proteins
python benchmark_proteins.py <system> <configuration>
```

Example commands:
```bash
# Classical MM with constraints
python benchmark_proteins.py ala2_tip3p constraints_mm

# Hybrid ML/MM without constraints
python benchmark_proteins.py dhfr no_constraints_mlmm

# Pure ML with constraints
python benchmark_proteins.py trp-cage_sol constraints_ml
```

**Sources:** [benchmark/proteins/benchmark_proteins.py:16-17]()

### Code Entity Mapping

The benchmark script maps system names to file paths and configurations to force field setups:

```mermaid
graph TB
    subgraph "Command Line Arguments"
        ARG_SYS["sys.argv[1]<br/>system name"]
        ARG_CONFIG["sys.argv[2]<br/>configuration"]
    end
    
    subgraph "File Loading"
        READ_POS["dimos.read_positions()<br/>{system}.gro"]
        GROMACS_FF["dimos.GromacsForceField()<br/>{system}.top, {system}.gro"]
    end
    
    subgraph "Force Field Selection"
        CHECK_CONST["'no_constraints' in name?"]
        CHECK_TYPE["name in list?"]
        
        MM_PATH["MM: base_sys"]
        MLMM_PATH["ML/MM: MLMMsystem()<br/>ml_atoms = base_sys.other_molecules[0]"]
        ML_PATH["ML: base_sys.as_mace_system()<br/>'mace-mp-large'"]
    end
    
    subgraph "Integrator & Simulation"
        INTEGRATOR["dimos.NoseHooverDynamics<br/>timestep, 300K, tau=0.05"]
        SIM["dimos.MDSimulation<br/>syst, integrator, positions"]
        COMPILED["torch.compile(sim.step)"]
    end
    
    ARG_SYS --> READ_POS
    ARG_SYS --> GROMACS_FF
    ARG_CONFIG --> CHECK_CONST
    ARG_CONFIG --> CHECK_TYPE
    
    READ_POS --> SIM
    GROMACS_FF --> CHECK_TYPE
    
    CHECK_CONST -->|No| CONST_YES["constraint_option='h_angles'<br/>timestep=2.0"]
    CHECK_CONST -->|Yes| CONST_NO["constraint_option=None<br/>timestep=0.5"]
    
    CHECK_TYPE -->|"_mm"| MM_PATH
    CHECK_TYPE -->|"_mlmm"| MLMM_PATH
    CHECK_TYPE -->|"_ml"| ML_PATH
    
    CONST_YES --> GROMACS_FF
    CONST_NO --> GROMACS_FF
    
    MM_PATH --> INTEGRATOR
    MLMM_PATH --> INTEGRATOR
    ML_PATH --> INTEGRATOR
    
    INTEGRATOR --> SIM
    SIM --> COMPILED
```

**Sources:** [benchmark/proteins/benchmark_proteins.py:16-51]()

### Output Format

The benchmark produces a `.dat` file with performance statistics:

**Filename:** `{system}_{configuration}_benchmark.dat`

**Content:** Two tab-separated values per line:
```
<mean_ns_per_day>    <std_error_ns_per_day>
```

Example output file `ala2_tip3p_constraints_mm_benchmark.dat`:
```
45.3    0.8
```

The standard error is calculated as: `std_dev / sqrt(N)` where N is the number of measurement iterations (50).

**Console output during measurement:**
```
constraints_mm 1.234 0.0247 45.3 -12345.67
```
- Configuration name
- Total time (seconds)
- Time per step (seconds)
- Throughput (ns/day)
- Potential energy (kJ/mol or kcal/mol)

**Sources:** [benchmark/proteins/benchmark_proteins.py:57-73]()

## Performance Metrics and Interpretation

### Throughput Calculation

The primary performance metric is throughput measured in nanoseconds per day (ns/day):

```
ns/day = (timestep × steps_per_measure × 1e-6) / (time_period / 86400)
```

Where:
- `timestep`: Integration timestep in femtoseconds
- `steps_per_measure`: Number of MD steps (50)
- `time_period`: Wall-clock time in seconds
- `86400`: Seconds per day

This metric represents how much simulation time can be produced in 24 hours of computation.

**Sources:** [benchmark/proteins/benchmark_proteins.py:65-68]()

### Expected Performance Characteristics

Different configurations exhibit characteristic performance profiles:

| Configuration | Typical Speed | Constraint Benefit | Notes |
|--------------|---------------|-------------------|-------|
| `constraints_mm` | Baseline | 4× faster | Reference classical MD |
| `no_constraints_mm` | Baseline/4 | N/A | Smaller timestep required |
| `constraints_mlmm` | 0.3-0.5× MM | 4× faster | ML overhead on protein |
| `no_constraints_mlmm` | 0.1-0.2× MM | N/A | Small timestep + ML cost |
| `constraints_ml` | 0.1-0.3× MM | 4× faster | Full ML potential |
| `no_constraints_ml` | 0.03-0.1× MM | N/A | Most expensive option |

The constraint benefit (4×) comes from the larger timestep (2.0 fs vs 0.5 fs) when hydrogen bonds/angles are constrained.

**Sources:** [benchmark/proteins/benchmark_proteins.py:24-29]()

### System Size Scaling

Performance scales with system size:

```mermaid
graph LR
    subgraph "System Sizes"
        ALA2["ala2_tip3p<br/>2,269 atoms<br/>Fastest"]
        TRP["trp-cage_sol<br/>7,660 atoms<br/>Medium"]
        DHFR["dhfr<br/>23,558 atoms<br/>Slowest"]
    end
    
    subgraph "Scaling Factors"
        NEIGHBOR["Neighbor list:<br/>O(N) with cutoff"]
        BONDED["Bonded terms:<br/>O(N)"]
        NONBOND["Nonbonded:<br/>O(N) with cutoff<br/>O(N log N) with PME"]
        ML["ML inference:<br/>O(N) per atom"]
    end
    
    ALA2 --> NEIGHBOR
    TRP --> NEIGHBOR
    DHFR --> NEIGHBOR
    
    NEIGHBOR --> BONDED
    NEIGHBOR --> NONBOND
    NEIGHBOR --> ML
```

For classical MM with PME electrostatics, performance typically scales between O(N) and O(N log N) due to the fast Fourier transform. For ML potentials, the scaling depends on the model architecture and message-passing depth.

**Sources:** [benchmark/proteins/benchmark_proteins.py:31]()

### Energy Conservation

The potential energy output serves as a validation metric:

- **Classical MM:** Energy should be stable (constant mean, small fluctuations)
- **With thermostat:** Total energy fluctuates, potential energy should be reasonable
- **Constraints:** May show small energy drift due to constraint violations
- **ML potentials:** Energy depends on training data quality

Large energy changes or unphysical values indicate:
- Numerical instability
- Incorrect force field setup
- Constraint failures
- ML model artifacts

**Sources:** [benchmark/proteins/benchmark_proteins.py:65]()

## Integration with DIMOS Components

The protein benchmarks exercise multiple DIMOS subsystems:

### Force Field System Integration

```mermaid
graph TB
    BENCH["benchmark_proteins.py"]
    
    subgraph "Force Field Layer"
        GROMACS_FF["dimos.GromacsForceField<br/>Classical topology"]
        MACE_SYS["as_mace_system()<br/>ML potential"]
        MLMM["dimos.mlmm.MLMMsystem<br/>Hybrid system"]
    end
    
    subgraph "Energy Calculation"
        BONDED["Bonded energy terms<br/>bonds, angles, dihedrals"]
        NONBOND["Nonbonded terms<br/>LJ, electrostatics"]
        PME["PME long-range<br/>Ewald summation"]
        ML_CALC["MACE calculator<br/>Neural network inference"]
    end
    
    subgraph "Constraint System"
        CONSTRAINT_HANDLER["constraint_handler<br/>CCMA or SETTLE"]
        H_ANGLES["h_angles option<br/>Constrain H-bonds/angles"]
    end
    
    subgraph "Integration"
        NOSE_HOOVER["NoseHooverDynamics<br/>Thermostat integrator"]
        MD_SIM["MDSimulation<br/>Simulation loop"]
    end
    
    BENCH --> GROMACS_FF
    GROMACS_FF --> MACE_SYS
    GROMACS_FF --> MLMM
    
    GROMACS_FF --> BONDED
    GROMACS_FF --> NONBOND
    NONBOND --> PME
    
    MACE_SYS --> ML_CALC
    MLMM --> ML_CALC
    MLMM --> BONDED
    
    GROMACS_FF --> CONSTRAINT_HANDLER
    CONSTRAINT_HANDLER --> H_ANGLES
    
    BONDED --> NOSE_HOOVER
    NONBOND --> NOSE_HOOVER
    ML_CALC --> NOSE_HOOVER
    PME --> NOSE_HOOVER
    
    NOSE_HOOVER --> MD_SIM
    CONSTRAINT_HANDLER --> MD_SIM
```

**Sources:** [benchmark/proteins/benchmark_proteins.py:31-47]()

### Compilation and Optimization

The benchmarks test PyTorch compilation effectiveness:

- **`torch.compile()`** with `"max-autotune-no-cudagraphs"` mode
- **Compiler reset** before compilation for clean state
- **Warmup iterations** to complete compilation
- **float32 precision** for GPU performance
- **CUDA device** placement

The compilation strategy is critical for ML and ML/MM configurations where the neural network inference must be optimized.

**Sources:** [benchmark/proteins/benchmark_proteins.py:8-9](), [benchmark/proteins/benchmark_proteins.py:49-51]()

---

This completes the documentation for protein benchmark systems in DIMOS. For water-based benchmarks, see [6.2](#6.2). For detailed platform comparison results and optimization strategies, see [6.3](#6.3). For information on the force field systems themselves, see [4.1](#4.1) (Classical), [4.2](#4.2) (ML), and [4.3](#4.3) (Hybrid).

---