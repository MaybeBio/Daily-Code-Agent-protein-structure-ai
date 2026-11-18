# PyRosetta-Free Alternatives

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [functions/pr_alternative_utils.py](functions/pr_alternative_utils.py)

</details>



This document covers the PyRosetta-free alternatives implemented in FreeBindCraft, which enable protein design workflows without requiring PyRosetta installation. These alternatives provide equivalent functionality using open-source tools like OpenMM, FreeSASA, and Biopython.

For information about traditional PyRosetta integration, see [PyRosetta Integration](#4). For shape complementarity tools specifically, see [Shape Complementarity Tools](#4.2).

## Overview

The PyRosetta-free alternatives system provides functionally equivalent replacements for key PyRosetta operations:

- **Structure Relaxation**: OpenMM with GPU acceleration replaces PyRosetta FastRelax
- **Interface Scoring**: Biopython SASA calculations replace PyRosetta interface analysis
- **Shape Complementarity**: External `sc-rs` binary replaces Rosetta shape complementarity
- **SASA Calculations**: FreeSASA and Biopython ShrakeRupley replace PyRosetta SASA

```mermaid
graph TB
    subgraph "Input"
        PDB["PDB Structure"]
    end
    
    subgraph "PyRosetta Path"
        PR_Relax["PyRosetta FastRelax<br/>CPU-Based"]
        PR_SASA["PyRosetta SASA<br/>Native Calculations"] 
        PR_Score["PyRosetta Interface<br/>Native Scoring"]
        PR_SC["Rosetta Shape Comp<br/>Native Algorithm"]
    end
    
    subgraph "PyRosetta-Free Path"
        MM_Relax["openmm_relax<br/>GPU-Accelerated"]
        Bio_SASA["FreeSASA + Biopython<br/>ShrakeRupley SASA"]
        Alt_Score["pr_alternative_score_interface<br/>Biopython Interface"]
        SC_RS["sc-rs Binary<br/>External Tool"]
    end
    
    subgraph "Output"
        Results["Relaxed Structure<br/>+ Interface Metrics"]
    end
    
    PDB --> PR_Relax
    PDB --> MM_Relax
    
    PR_Relax --> PR_SASA
    PR_SASA --> PR_Score
    PR_Score --> PR_SC
    PR_SC --> Results
    
    MM_Relax --> Bio_SASA
    Bio_SASA --> Alt_Score
    Alt_Score --> SC_RS
    SC_RS --> Results
```

**Sources**: [functions/pr_alternative_utils.py:1-24]()

## OpenMM Structure Relaxation

The `openmm_relax` function provides GPU-accelerated structure relaxation as an alternative to PyRosetta's FastRelax protocol. It uses the AMBER14 force field with OBC2 implicit solvent.

### Relaxation Architecture

```mermaid
graph TD
    Input["PDB Input"]
    
    subgraph "Preparation Stage"
        PDBFixer["PDBFixer<br/>Structure Cleanup"]
        FF["_get_openmm_forcefield<br/>AMBER14 + OBC2"]
    end
    
    subgraph "Force System Setup"
        BaseForces["Base System<br/>Bonds, Angles, Dihedrals"]
        Restraints["_create_backbone_restraint_force<br/>Backbone Heavy Atoms"]
        LJRep["_create_lj_repulsive_force<br/>Clash Resolution"]
    end
    
    subgraph "Multi-Stage Relaxation"
        Stage1["Stage 1<br/>Strong Restraints + LJ"]
        Stage2["Stage 2<br/>Medium Restraints + LJ"]  
        Stage3["Stage 3<br/>Weak/No Restraints"]
        MDShake["MD Shake<br/>5000 steps per stage"]
        Minimize["L-BFGS Minimization<br/>Chunked iterations"]
    end
    
    subgraph "Platform Selection"
        OpenCL["OpenCL Platform<br/>Primary GPU Choice"]
        CUDA["CUDA Platform<br/>Secondary GPU Choice"]
        CPU["CPU Platform<br/>Fallback Only"]
    end
    
    Input --> PDBFixer
    PDBFixer --> FF
    FF --> BaseForces
    BaseForces --> Restraints
    Restraints --> LJRep
    
    LJRep --> Stage1
    Stage1 --> Stage2
    Stage2 --> Stage3
    
    Stage1 --> MDShake
    Stage2 --> MDShake
    Stage1 --> Minimize
    Stage2 --> Minimize
    Stage3 --> Minimize
    
    OpenCL --> Stage1
    CUDA --> Stage1  
    CPU --> Stage1
```

### Key Components

The relaxation system consists of several specialized components:

| Component | Function | Purpose |
|-----------|----------|---------|
| **Force Field Singleton** | `_get_openmm_forcefield` | Cached AMBER14-all.xml + OBC2 force field |
| **Backbone Restraints** | `_create_backbone_restraint_force` | Harmonic restraints on N,CA,C,O atoms |
| **LJ Repulsion** | `_create_lj_repulsive_force` | Custom repulsive force for clash resolution |
| **Platform Selection** | Multi-platform fallback | OpenCL → CUDA → CPU priority order |

**Sources**: [functions/pr_alternative_utils.py:62-66](), [functions/pr_alternative_utils.py:122-153](), [functions/pr_alternative_utils.py:74-120]()

### Subprocess Isolation

The `openmm_relax_subprocess` function provides process isolation to prevent OpenCL context accumulation:

```mermaid
graph LR
    Parent["Parent Process<br/>bindcraft.py"]
    
    subgraph "Child Process Isolation"
        Child["subprocess.run<br/>Fresh Python Process"]
        OpenCL["Clean OpenCL Context<br/>Per Relaxation"]
        Relax["openmm_relax<br/>Actual Work"]
    end
    
    Output["Relaxed PDB<br/>Written to Disk"]
    
    Parent --> Child
    Child --> OpenCL
    OpenCL --> Relax
    Relax --> Output
    Output --> Parent
    
    Parent --> Child
```

**Sources**: [functions/pr_alternative_utils.py:1030-1107](), [functions/pr_alternative_utils.py:21-23]()

## Interface Scoring System

The `pr_alternative_score_interface` function provides comprehensive interface analysis without PyRosetta dependency.

### Scoring Components

```mermaid
graph TB
    subgraph "Input Processing"
        PDBFile["PDB Complex File"]
        Chains["Binder Chain B<br/>Target Chain A"]
    end
    
    subgraph "Interface Detection"
        HotspotFunc["hotspot_residues<br/>from biopython_utils"]
        InterfaceRes["Interface Residues<br/>Contact-based Detection"]
        AAComp["Interface AA Composition<br/>20 amino acid counts"]
    end
    
    subgraph "SASA Engine Selection"
        SASAEngine["sasa_engine parameter"]
        FreeSASA["_compute_sasa_metrics_with_freesasa<br/>Primary Choice"]
        Biopython["_compute_sasa_metrics<br/>Fallback Choice"]
    end
    
    subgraph "Shape Complementarity"
        SCBinary["_calculate_shape_complementarity<br/>sc-rs CLI Tool"]
        SCPlaceholder["Fallback SC = 0.70<br/>If binary unavailable"]
    end
    
    subgraph "Score Assembly"
        InterfaceScores["interface_scores dict<br/>14 calculated metrics"]
        Placeholders["Fixed placeholder values<br/>For uncomputed metrics"]
    end
    
    PDBFile --> HotspotFunc
    Chains --> HotspotFunc
    HotspotFunc --> InterfaceRes
    InterfaceRes --> AAComp
    
    SASAEngine --> FreeSASA
    SASAEngine --> Biopython
    FreeSASA --> InterfaceScores
    Biopython --> InterfaceScores
    
    PDBFile --> SCBinary
    SCBinary --> SCPlaceholder
    SCPlaceholder --> InterfaceScores
    
    AAComp --> InterfaceScores
    InterfaceScores --> Placeholders
```

**Sources**: [functions/pr_alternative_utils.py:892-1027](), [functions/pr_alternative_utils.py:922-927](), [functions/pr_alternative_utils.py:934-973]()

### Computed vs Placeholder Metrics

The scoring system provides both computed and placeholder values:

| Metric Type | Implementation | Status |
|-------------|----------------|---------|
| **Interface Residues** | `hotspot_residues` function | ✅ Computed |
| **SASA Calculations** | FreeSASA/Biopython | ✅ Computed |
| **Shape Complementarity** | `sc-rs` binary | ✅ Computed |
| **Surface Hydrophobicity** | Residue-based analysis | ✅ Computed |
| **Hydrogen Bonds** | Fixed placeholder = 5 | ⚠️ Placeholder |
| **PackStat** | Fixed placeholder = 0.65 | ⚠️ Placeholder |
| **dG Energy** | Fixed placeholder = -10.0 | ⚠️ Placeholder |

**Sources**: [functions/pr_alternative_utils.py:994-1002](), [functions/pr_alternative_utils.py:1004-1021]()

## SASA Calculation Methods

FreeBindCraft provides two SASA calculation engines with automatic fallback.

### Engine Selection Logic

```mermaid
flowchart TD
    Start["pr_alternative_score_interface<br/>sasa_engine parameter"]
    
    CheckEngine{"`sasa_engine value?`"}
    
    ForceBio["`sasa_engine = 'biopython'`"]
    ForceFreeSASA["`sasa_engine = 'freesasa'`"]
    AutoSelect["`sasa_engine = 'auto'`"]
    
    CheckFreeSASA{"`_HAS_FREESASA?`"}
    
    RunBiopython["_compute_sasa_metrics<br/>ShrakeRupley algorithm"]
    RunFreeSASA["_compute_sasa_metrics_with_freesasa<br/>FreeSASA library"]
    
    ErrorFallback["FreeSASA Error<br/>Fallback to Biopython"]
    
    Results["SASA Metrics<br/>5-tuple return"]
    
    Start --> CheckEngine
    CheckEngine --> ForceBio
    CheckEngine --> ForceFreeSASA
    CheckEngine --> AutoSelect
    
    ForceBio --> RunBiopython
    ForceFreeSASA --> RunFreeSASA
    AutoSelect --> CheckFreeSASA
    
    CheckFreeSASA -->|True| RunFreeSASA
    CheckFreeSASA -->|False| RunBiopython
    
    RunFreeSASA -->|Success| Results
    RunFreeSASA -->|Error| ErrorFallback
    ErrorFallback --> RunBiopython
    RunBiopython --> Results
```

### SASA Calculation Details

Both engines compute the same 5-tuple output:

1. **Surface Hydrophobicity Fraction**: Hydrophobic residue SASA / Total binder SASA
2. **Binder SASA in Complex**: Binder accessibility in bound state  
3. **Binder SASA Monomer**: Binder accessibility when isolated
4. **Target SASA in Complex**: Target accessibility in bound state
5. **Target SASA Monomer**: Target accessibility when isolated

**Sources**: [functions/pr_alternative_utils.py:287-378](), [functions/pr_alternative_utils.py:380-523](), [functions/pr_alternative_utils.py:54-60]()

## Shape Complementarity Integration

The shape complementarity calculation uses the external `sc-rs` binary with robust fallback handling.

### Binary Resolution Strategy

```mermaid
graph TD
    subgraph "Binary Search Order"
        LocalBin["Local Binary<br/>functions/sc or functions/sc-rs"]
        EnvVars["Environment Variables<br/>SC_RS_BIN or SC_BIN"]  
        PathSearch["PATH Search<br/>sc, sc-rs, shape-complementarity"]
    end
    
    subgraph "Execution"
        Command["sc <pdb> <chainA> <chainB> --json<br/>120 second timeout"]
        JSONParse["JSON Output Parsing<br/>Extract 'sc' or 'sc_value' field"]
    end
    
    subgraph "Fallback Strategy"
        NotFound["Binary Not Found"]
        ParseError["JSON Parse Error"]
        Timeout["Command Timeout"]
        Placeholder["Return SC = 0.70<br/>Conservative fallback"]
    end
    
    LocalBin --> Command
    EnvVars --> Command
    PathSearch --> Command
    
    Command --> JSONParse
    JSONParse --> Placeholder
    
    NotFound --> Placeholder
    ParseError --> Placeholder  
    Timeout --> Placeholder
```

The shape complementarity function handles mixed output by extracting JSON from potentially verbose output:

**Sources**: [functions/pr_alternative_utils.py:185-285](), [functions/pr_alternative_utils.py:211-229](), [functions/pr_alternative_utils.py:253-276]()

## Integration with Main Pipeline

The PyRosetta-free alternatives integrate seamlessly with the main design pipeline through conditional logic.

### Pipeline Integration Points

| Integration Point | Traditional Path | PyRosetta-Free Path |
|------------------|------------------|-------------------|
| **Structure Relaxation** | `pr_relax` function | `openmm_relax_subprocess` |
| **Interface Scoring** | `pr_score_interface` | `pr_alternative_score_interface` |
| **SASA Calculations** | PyRosetta native | FreeSASA or Biopython |
| **Shape Complementarity** | Rosetta protocols | `sc-rs` binary |

The selection between paths is controlled by:
- `--no-pyrosetta` command line flag
- PyRosetta installation detection  
- GPU availability for OpenMM
- Binary availability for shape complementarity

**Sources**: [functions/pr_alternative_utils.py:1-24](), [functions/pr_alternative_utils.py:525-891]()

---