# Workflows and Applications

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.github/workflows/test.yml](.github/workflows/test.yml)
- [README.md](README.md)
- [pyproject.toml](pyproject.toml)
- [torch_sim/models/lennard_jones.py](torch_sim/models/lennard_jones.py)
- [torch_sim/models/morse.py](torch_sim/models/morse.py)
- [torch_sim/models/particle_life.py](torch_sim/models/particle_life.py)
- [torch_sim/models/soft_sphere.py](torch_sim/models/soft_sphere.py)
- [torch_sim/workflows/a2c.py](torch_sim/workflows/a2c.py)

</details>



## Purpose and Scope

This page documents the workflow and application-level functionality in torch-sim, which combines core simulation primitives into complete scientific pipelines. Workflows orchestrate multiple simulation steps—structure generation, relaxation, MD simulation, and analysis—to accomplish research objectives.

For information about individual simulation primitives that workflows build upon, see:
- Structure optimization algorithms: [Structure Optimization](#5)
- Molecular dynamics integration: [Molecular Dynamics](#4)
- Classical potentials used in workflows: [Classical Potentials](#6.7)
- I/O for converting workflow results: [I/O and Format Conversion](#3.4)

The workflow module provides functions for generating initial structures, removing atomic overlaps, extracting crystalline subcells from amorphous systems, and validating relaxed structures.

**Sources:** [torch_sim/workflows/a2c.py:1-8]()

## Workflow Architecture

The workflow layer sits above the core simulation API and combines multiple operations into research pipelines:

```mermaid
graph TB
    subgraph "User Level"
        Research["Research Objective"]
    end
    
    subgraph "Workflow Layer"
        StructGen["random_packed_structure()<br/>random_packed_structure_multi()"]
        SubcellExtract["get_subcells_to_crystallize()<br/>subcells_to_structures()"]
        Relax["get_relaxed_structure()<br/>get_unit_cell_relaxed_structure()<br/>get_frechet_cell_relaxed_structure()"]
        Validate["valid_subcell()"]
    end
    
    subgraph "Core Simulation API"
        TsOptimize["ts.optimize()"]
        TsIntegrate["ts.integrate()"]
        TsStatic["ts.static()"]
        FireInit["ts.fire_init()"]
        FireStep["ts.fire_step()"]
    end
    
    subgraph "Classical Potentials"
        SoftSphere["SoftSphereModel<br/>SoftSphereMultiModel"]
        LJ["LennardJonesModel"]
        Morse["MorseModel"]
    end
    
    subgraph "MLIP Models"
        MACE["MaceModel"]
        FairChem["FairChemModel"]
        ORB["OrbModel"]
    end
    
    Research --> StructGen
    Research --> SubcellExtract
    Research --> Relax
    
    StructGen --> SoftSphere
    StructGen --> FireInit
    StructGen --> FireStep
    
    Relax --> FireInit
    Relax --> FireStep
    Relax --> TsOptimize
    
    SubcellExtract --> Relax
    Relax --> Validate
    
    FireInit --> MACE
    FireInit --> FairChem
    FireStep --> MACE
    FireStep --> FairChem
    
    TsOptimize --> MACE
    TsOptimize --> FairChem
```

**Sources:** [torch_sim/workflows/a2c.py:1-893](), [README.md:27-90]()

## Structure Generation Components

### Random Packing Workflow

The structure generation workflow creates initial atomic configurations with controlled interatomic distances:

```mermaid
graph LR
    subgraph "Input"
        Comp["Composition"]
        Cell["Cell Tensor"]
        Params["Parameters:<br/>diameter, seed, max_iter"]
    end
    
    subgraph "Generation Phase"
        RandPos["torch.rand()<br/>Fractional Positions"]
        ToCart["torch.matmul(pos, cell)<br/>Cartesian Conversion"]
    end
    
    subgraph "Overlap Removal Phase"
        SoftSphereModel["SoftSphereModel<br/>or<br/>SoftSphereMultiModel"]
        FireInit["ts.fire_init()"]
        FireLoop["FIRE Loop:<br/>ts.fire_step()"]
        MinDist["min_distance()<br/>Distance Check"]
    end
    
    subgraph "Output"
        FinalState["FireState<br/>Optimized Positions"]
        Log["Position Log"]
    end
    
    Comp --> RandPos
    Cell --> RandPos
    Params --> RandPos
    
    RandPos --> ToCart
    ToCart --> SoftSphereModel
    Cell --> SoftSphereModel
    
    SoftSphereModel --> FireInit
    FireInit --> FireLoop
    FireLoop --> MinDist
    MinDist -->|"dist < 0.95*diameter"| FireLoop
    MinDist -->|"dist >= 0.95*diameter"| FinalState
    FireLoop --> Log
    
    style FinalState fill:#f9f9f9
    style SoftSphereModel fill:#f9f9f9
```

**Key Functions:**

| Function | Purpose | File Location |
|----------|---------|---------------|
| `random_packed_structure()` | Generate single-species random packed structure | [torch_sim/workflows/a2c.py:210-313]() |
| `random_packed_structure_multi()` | Generate multi-species random packed structure | [torch_sim/workflows/a2c.py:316-432]() |
| `min_distance()` | Calculate minimum interatomic distance | [torch_sim/workflows/a2c.py:26-70]() |
| `get_diameter()` | Calculate atomic diameter from composition | [torch_sim/workflows/a2c.py:73-137]() |
| `get_diameter_matrix()` | Calculate diameter matrix for multiple species | [torch_sim/workflows/a2c.py:140-207]() |

**Sources:** [torch_sim/workflows/a2c.py:210-432](), [torch_sim/models/soft_sphere.py:175-246](), [torch_sim/models/soft_sphere.py:248-377]()

### Diameter Calculation

The workflow uses atomic radii from pymatgen to automatically determine appropriate soft-sphere diameters:

```mermaid
graph TB
    subgraph "Single Element"
        Elem["Element"]
        IsMetal{"is_metal?"}
        MetalRad["2 × metallic_radius"]
        AtomRad["2 × atomic_radius<br/>or<br/>2 × average_ionic_radius"]
        SingleDiam["diameter"]
    end
    
    subgraph "Multi Element"
        Elements["elements[0...n]"]
        Pairs["itertools.combinations()<br/>All pairs"]
        IonicSum["Sum ionic radii"]
        MinSum["min(sums)"]
        MultiDiam["diameter"]
    end
    
    Elem --> IsMetal
    IsMetal -->|Yes| MetalRad
    IsMetal -->|No| AtomRad
    MetalRad --> SingleDiam
    AtomRad --> SingleDiam
    
    Elements --> Pairs
    Pairs --> IonicSum
    IonicSum --> MinSum
    MinSum --> MultiDiam
    
    style SingleDiam fill:#f9f9f9
    style MultiDiam fill:#f9f9f9
```

**Sources:** [torch_sim/workflows/a2c.py:73-137](), [torch_sim/workflows/a2c.py:140-207]()

## Amorphous-to-Crystalline (A2C) Pipeline

The A2C workflow extracts crystalline subcells from larger amorphous structures and relaxes them to find stable crystal structures:

```mermaid
graph TB
    subgraph "Input Structure"
        Amorphous["Large Amorphous Structure<br/>fractional_positions, cell, species"]
    end
    
    subgraph "Subcell Extraction"
        Grid["torch.linspace(0, 1, bins)<br/>Create Grid"]
        Bounds["torch.meshgrid()<br/>Generate Bounds"]
        Mask["torch.logical_and()<br/>Find Atoms in Subcell"]
        CompFilter["Composition.reduced_formula<br/>Filter by Composition"]
        Candidates["List of (ids, lower, upper)"]
    end
    
    subgraph "Structure Conversion"
        Shift["pos - lower_bound<br/>Shift to Origin"]
        Scale["pos / (upper - lower)<br/>Normalize to [0,1]"]
        NewCell["cell × (upper - lower)<br/>Scale Cell"]
        Subcells["List of Subcell Structures"]
    end
    
    subgraph "Relaxation"
        FireOpt["get_relaxed_structure()<br/>or<br/>get_unit_cell_relaxed_structure()<br/>or<br/>get_frechet_cell_relaxed_structure()"]
        MLIP["MLIP Model<br/>MaceModel, FairChemModel, etc."]
        Relaxed["Relaxed Structures"]
    end
    
    subgraph "Validation"
        ValidCheck["valid_subcell()"]
        Checks["Energy Checks<br/>Distance Checks<br/>Formation Energy Checks"]
        Valid["Valid Crystals"]
    end
    
    Amorphous --> Grid
    Grid --> Bounds
    Bounds --> Mask
    Mask --> CompFilter
    CompFilter --> Candidates
    
    Candidates --> Shift
    Shift --> Scale
    Scale --> NewCell
    NewCell --> Subcells
    
    Subcells --> FireOpt
    MLIP --> FireOpt
    FireOpt --> Relaxed
    
    Relaxed --> ValidCheck
    ValidCheck --> Checks
    Checks --> Valid
    
    style Valid fill:#f9f9f9
    style Candidates fill:#f9f9f9
```

**Key Functions:**

| Function | Purpose | Return Type |
|----------|---------|-------------|
| `get_subcells_to_crystallize()` | Extract subcell candidates from structure | `list[tuple[torch.Tensor, torch.Tensor, torch.Tensor]]` |
| `subcells_to_structures()` | Convert subcell candidates to structures | `list[tuple[torch.Tensor, torch.Tensor, list[str]]]` |
| `get_relaxed_structure()` | Relax positions at fixed cell | `tuple[FireState, dict, list[float], list[float]]` |
| `get_unit_cell_relaxed_structure()` | Relax positions and cell (unit filter) | `tuple[FireState, dict, list[float], list[float]]` |
| `get_frechet_cell_relaxed_structure()` | Relax positions and cell (Frechet filter) | `tuple[FireState, dict, list[float], list[float]]` |
| `valid_subcell()` | Validate relaxed structure | `bool` |

**Sources:** [torch_sim/workflows/a2c.py:505-658](), [torch_sim/workflows/a2c.py:685-892]()

## Relaxation Workflows

Three relaxation workflow functions provide different levels of cell optimization:

```mermaid
graph TB
    subgraph "Relaxation Workflows"
        FixedCell["get_relaxed_structure()<br/>Fixed Cell"]
        UnitCell["get_unit_cell_relaxed_structure()<br/>Unit Cell Filter"]
        FrechetCell["get_frechet_cell_relaxed_structure()<br/>Frechet Cell Filter"]
    end
    
    subgraph "Common Operations"
        ModelEval["model(state)<br/>Initial Evaluation"]
        FireInit["ts.fire_init()<br/>Initialize FIRE"]
        StepLoop["for step in range(max_iter):<br/>    ts.fire_step()"]
        Logger["logger['energy'][step]<br/>logger['stress'][step]"]
        FinalEval["model(state)<br/>Final Evaluation"]
        Pressure["get_pressure()<br/>Calculate Pressure"]
    end
    
    subgraph "Cell Filter Selection"
        NoFilter["cell_filter=None"]
        UnitFilter["cell_filter=ts.CellFilter.unit"]
        FrechetFilter["cell_filter=ts.CellFilter.frechet"]
    end
    
    subgraph "Output"
        State["FireState"]
        LogDict["Logger Dict"]
        Energy["Final Energy"]
        Press["Final Pressure"]
    end
    
    FixedCell --> ModelEval
    UnitCell --> ModelEval
    FrechetCell --> ModelEval
    
    FixedCell --> NoFilter
    UnitCell --> UnitFilter
    FrechetCell --> FrechetFilter
    
    ModelEval --> FireInit
    NoFilter --> FireInit
    UnitFilter --> FireInit
    FrechetFilter --> FireInit
    
    FireInit --> StepLoop
    StepLoop --> Logger
    Logger --> StepLoop
    StepLoop --> FinalEval
    FinalEval --> Pressure
    
    Pressure --> State
    Pressure --> LogDict
    Pressure --> Energy
    Pressure --> Press
    
    style State fill:#f9f9f9
```

### Relaxation Function Comparison

| Feature | `get_relaxed_structure()` | `get_unit_cell_relaxed_structure()` | `get_frechet_cell_relaxed_structure()` |
|---------|---------------------------|-------------------------------------|----------------------------------------|
| Optimize Positions | ✓ | ✓ | ✓ |
| Optimize Cell | ✗ | ✓ | ✓ |
| Cell Filter | None | `CellFilter.unit` | `CellFilter.frechet` |
| Stress Logging | Initial/Final only | All steps | All steps |
| Use Case | Fixed cell relaxation | Isotropic cell optimization | Anisotropic cell optimization |
| File Location | [a2c.py:830-892]() | [a2c.py:685-754]() | [a2c.py:757-827]() |

**Sources:** [torch_sim/workflows/a2c.py:685-892]()

## Structure Validation

The `valid_subcell()` function implements multi-criteria validation for relaxed structures:

```mermaid
graph TB
    subgraph "Validation Criteria"
        Input["positions, cell<br/>initial_energy, final_energy"]
        
        Check1["final_energy >= e_form_lower_limit<br/>Formation energy not too negative"]
        Check2["final_energy >= initial_energy + e_tol<br/>Energy decreased during relaxation"]
        Check3["final_energy <= fe_upper_limit + e_tol<br/>Final energy low enough"]
        Check4["min_distance() >= fusion_distance<br/>No atomic fusion"]
    end
    
    subgraph "Default Thresholds"
        T1["e_form_lower_limit = -5.0 eV/atom"]
        T2["e_tol = 0.001 eV"]
        T3["fe_upper_limit = 0.0 eV/atom"]
        T4["fusion_distance = 1.5 Å"]
    end
    
    subgraph "Result"
        AllPass{"All Checks<br/>Pass?"}
        Valid["Return True"]
        Invalid["Return False"]
    end
    
    Input --> Check1
    Check1 --> Check2
    Check2 --> Check3
    Check3 --> Check4
    
    T1 --> Check1
    T2 --> Check2
    T2 --> Check3
    T3 --> Check3
    T4 --> Check4
    
    Check4 --> AllPass
    AllPass -->|Yes| Valid
    AllPass -->|No| Invalid
    
    style Valid fill:#f9f9f9
```

**Sources:** [torch_sim/workflows/a2c.py:435-502]()

## Utility Functions

### Distance Calculation

The `min_distance()` function computes minimum interatomic separation using periodic boundary conditions:

```mermaid
graph LR
    subgraph "Input"
        Pos["positions [n_atoms, 3]"]
        Cell["cell [3, 3]"]
        Tol["distance_tolerance<br/>Default: 0.0001 Å"]
    end
    
    subgraph "Computation"
        PairDisp["transforms.get_pair_displacements()<br/>Returns (displacements, distances)"]
        Mask["distances < distance_tolerance<br/>Mask self-interactions"]
        MaskFill["distances.masked_fill(mask, inf)<br/>Replace masked with infinity"]
        Min["distances.min()<br/>Find minimum"]
    end
    
    subgraph "Output"
        MinDist["Minimum Distance<br/>torch.Tensor scalar"]
    end
    
    Pos --> PairDisp
    Cell --> PairDisp
    PairDisp --> Mask
    Tol --> Mask
    Mask --> MaskFill
    MaskFill --> Min
    Min --> MinDist
    
    style MinDist fill:#f9f9f9
```

**Sources:** [torch_sim/workflows/a2c.py:26-70]()

### Temperature Profile

The `get_target_temperature()` function implements a melt-quench-equilibrate temperature schedule:

```mermaid
graph TB
    subgraph "Temperature Profile"
        Step["Current Step"]
        
        Phase1{"step < equi_steps?"}
        HighT["T_high<br/>Equilibration Phase"]
        
        Phase2{"step < cool_steps + equi_steps?"}
        Linear["T_low + (T_high - T_low) × cooling_fraction<br/>Linear Cooling"]
        
        LowT["T_low<br/>Final Equilibration"]
    end
    
    subgraph "Parameters"
        P1["equi_steps<br/>High-T equilibration steps"]
        P2["cool_steps<br/>Cooling steps"]
        P3["T_high<br/>Initial temperature (K)"]
        P4["T_low<br/>Final temperature (K)"]
    end
    
    Step --> Phase1
    P1 --> Phase1
    
    Phase1 -->|Yes| HighT
    Phase1 -->|No| Phase2
    
    P2 --> Phase2
    Phase2 -->|Yes| Linear
    Phase2 -->|No| LowT
    
    P3 --> HighT
    P3 --> Linear
    P4 --> Linear
    P4 --> LowT
    
    style HighT fill:#f9f9f9
    style Linear fill:#f9f9f9
    style LowT fill:#f9f9f9
```

**Sources:** [torch_sim/workflows/a2c.py:661-682]()

## Classical Potentials for Workflows

Workflows frequently use classical potentials for initial structure preparation and overlap removal:

| Model | Use Case | Key Parameters | File Location |
|-------|----------|----------------|---------------|
| `SoftSphereModel` | Single-species overlap removal | `sigma`, `epsilon`, `alpha` | [torch_sim/models/soft_sphere.py:175-246]() |
| `SoftSphereMultiModel` | Multi-species overlap removal | `atomic_numbers`, `sigma_matrix`, `epsilon_matrix` | [torch_sim/models/soft_sphere.py:248-377]() |
| `LennardJonesModel` | Van der Waals interactions | `sigma`, `epsilon`, `cutoff` | [torch_sim/models/lennard_jones.py:74-141]() |
| `MorseModel` | Bonded interactions | `sigma`, `epsilon`, `alpha` | [torch_sim/models/morse.py:78-144]() |
| `ParticleLifeModel` | Emergent behavior simulations | `sigma`, `epsilon`, `beta` | [torch_sim/models/particle_life.py:57-122]() |

**Sources:** [torch_sim/models/soft_sphere.py:1-378](), [torch_sim/models/lennard_jones.py:1-142](), [torch_sim/models/morse.py:1-145](), [torch_sim/models/particle_life.py:1-123]()

## Workflow Data Flow

The complete data flow through a typical workflow pipeline:

```mermaid
graph TB
    subgraph "Initialization"
        PymatgenComp["pymatgen.Composition<br/>'Fe80B20'"]
        CellTensor["torch.Tensor [3,3]<br/>Cell Vectors"]
        Seed["Random Seed"]
    end
    
    subgraph "Structure Generation"
        Diameter["get_diameter()<br/>or get_diameter_matrix()"]
        RandPack["random_packed_structure()<br/>or random_packed_structure_multi()"]
        SoftSphere["SoftSphereModel<br/>SoftSphereMultiModel"]
        InitState["FireState<br/>Initial Structure"]
    end
    
    subgraph "Subcell Extraction"
        GetSubcells["get_subcells_to_crystallize()"]
        ToStructs["subcells_to_structures()"]
        SubcellList["List of Subcell Structures"]
    end
    
    subgraph "MLIP Relaxation"
        MLIP["MLIP Model<br/>MaceModel, FairChemModel, ORB"]
        RelaxFunc["get_relaxed_structure()<br/>get_unit_cell_relaxed_structure()<br/>get_frechet_cell_relaxed_structure()"]
        FireOpt["ts.fire_init()<br/>ts.fire_step() loop"]
        RelaxedStates["List of Relaxed States"]
    end
    
    subgraph "Validation and Analysis"
        ValidFunc["valid_subcell()"]
        FilterValid["Filter Valid Structures"]
        ValidStruct["Valid Crystal Structures"]
        ToAtoms["state.to_atoms()<br/>Convert to ASE"]
    end
    
    PymatgenComp --> Diameter
    CellTensor --> RandPack
    Seed --> RandPack
    Diameter --> RandPack
    
    RandPack --> SoftSphere
    SoftSphere --> InitState
    
    InitState --> GetSubcells
    GetSubcells --> ToStructs
    ToStructs --> SubcellList
    
    SubcellList --> MLIP
    SubcellList --> RelaxFunc
    MLIP --> RelaxFunc
    RelaxFunc --> FireOpt
    FireOpt --> RelaxedStates
    
    RelaxedStates --> ValidFunc
    ValidFunc --> FilterValid
    FilterValid --> ValidStruct
    ValidStruct --> ToAtoms
    
    style InitState fill:#f9f9f9
    style ValidStruct fill:#f9f9f9
```

**Sources:** [torch_sim/workflows/a2c.py:1-893](), [torch_sim/models/soft_sphere.py:1-378]()

## Integration with Core API

Workflows build upon the core torch-sim API functions:

```mermaid
graph TB
    subgraph "Workflow Functions"
        W1["random_packed_structure()"]
        W2["random_packed_structure_multi()"]
        W3["get_relaxed_structure()"]
        W4["get_unit_cell_relaxed_structure()"]
        W5["get_frechet_cell_relaxed_structure()"]
    end
    
    subgraph "Core API ts.*"
        API1["ts.fire_init(state, model, cell_filter)"]
        API2["ts.fire_step(state, model)"]
        API3["ts.optimize(system, model, optimizer)"]
        API4["ts.integrate(system, model, integrator)"]
    end
    
    subgraph "State Types"
        S1["ts.SimState"]
        S2["ts.FireState"]
        S3["ts.MDState"]
    end
    
    subgraph "Model Interface"
        M1["ModelInterface.forward(state)"]
        M2["Returns: energy, forces, stress"]
    end
    
    W1 --> API1
    W2 --> API1
    W3 --> API1
    W4 --> API1
    W5 --> API1
    
    API1 --> S2
    API2 --> S2
    
    W1 --> API2
    W2 --> API2
    W3 --> API2
    W4 --> API2
    W5 --> API2
    
    S1 --> API1
    S2 --> API2
    
    API1 --> M1
    API2 --> M1
    M1 --> M2
    
    style S2 fill:#f9f9f9
    style M1 fill:#f9f9f9
```

**Sources:** [torch_sim/workflows/a2c.py:1-893](), [README.md:36-90]()

---