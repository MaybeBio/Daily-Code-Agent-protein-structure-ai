# System Architecture

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [README.md](README.md)
- [functions/__init__.py](functions/__init__.py)

</details>



This document provides a comprehensive overview of FreeBindCraft's modular architecture, explaining how the system's components interact to provide both traditional PyRosetta-based and PyRosetta-free protein design capabilities. For installation and deployment details, see [Installation](#2.1) and [Docker Deployment](#2.2). For configuration specifics, see [Configuration System](#5).

## Overview

FreeBindCraft implements a dual-path architecture that allows users to choose between PyRosetta-based traditional methods or open-source alternatives. The system is built around a modular design with clear separation between core pipeline logic, computational backends, configuration management, and analysis tools.

## High-Level System Architecture

**System Components Overview**

```mermaid
graph TB
    subgraph "Orchestration Layer"
        BC["bindcraft.py<br/>Main Pipeline Orchestrator"]
        CLI["Interactive CLI<br/>--interactive flag"]
        Docker["docker_cli.py<br/>Container Wrapper"]
    end
    
    subgraph "Core Function Modules"
        CD["colabdesign_utils.py<br/>AF2 + MPNN Design Engine"]
        PR["pyrosetta_utils.py<br/>Traditional Scoring/Relax"]
        PA["pr_alternative_utils.py<br/>OpenMM + FreeSASA Alternatives"]
        BP["biopython_utils.py<br/>Structure Analysis"]
        GU["generic_utils.py<br/>Infrastructure Services"]
    end
    
    subgraph "Configuration System"
        TS["settings_target/<br/>Target Definitions"]
        FS["settings_filters/<br/>Filter Criteria"]
        AS["settings_advanced/<br/>Algorithm Parameters"]
    end
    
    subgraph "Analysis & Validation"
        Extras["extras/<br/>Post-processing Tools"]
        Rescore["rescore_accepted_with_rosetta.py"]
        Analyze["analyze_bindcraft_rejections.py"]
        Compare["compare_interface_metrics_all.py"]
    end
    
    BC --> CD
    BC --> PR
    BC --> PA
    BC --> BP
    BC --> GU
    
    CLI --> BC
    Docker --> BC
    
    TS --> BC
    FS --> BC
    AS --> BC
    
    BC --> Extras
    Extras --> Rescore
    Extras --> Analyze
    Extras --> Compare
    
    CD -.-> PA
    PR -.-> PA
```

Sources: [README.md:1-303](), [functions/__init__.py:11-15]()

## Core Module Architecture

The system's functionality is organized into five primary modules under the `functions/` directory, each with distinct responsibilities:

**Module Dependencies and Interactions**

```mermaid
graph TD
    subgraph "bindcraft.py Main Pipeline"
        MP["Main Pipeline Execution"]
    end
    
    subgraph "functions/ Module System"
        GU["generic_utils<br/>• perform_input_check<br/>• generate_directories<br/>• check_jax_gpu<br/>• ensure_binaries_executable"]
        
        CD["colabdesign_utils<br/>• Hallucination with AF2<br/>• MPNN sequence generation<br/>• Structure prediction<br/>• Trajectory analysis"]
        
        BP["biopython_utils<br/>• Secondary structure calc<br/>• Interface residue detection<br/>• RMSD calculations<br/>• PDB alignment"]
        
        PR["pyrosetta_utils<br/>• FastRelax protocol<br/>• Interface scoring<br/>• Native SASA calculations<br/>• Shape complementarity"]
        
        PA["pr_alternative_utils<br/>• OpenMM relaxation<br/>• FreeSASA calculations<br/>• sc-rs shape complementarity<br/>• Biopython fallbacks"]
    end
    
    MP --> GU
    GU --> CD
    GU --> BP
    
    MP --> CD
    CD --> BP
    
    MP --> PR
    MP --> PA
    
    PR -.-> PA
    BP --> PA
    
    style MP fill:#f9f9f9
    style GU fill:#f0f0f0
```

| Module | Primary Functions | Key Dependencies |
|--------|------------------|------------------|
| `generic_utils` | System setup, validation, directory management | Core infrastructure |
| `colabdesign_utils` | Design engine, hallucination, MPNN | JAX, ColabDesign |
| `biopython_utils` | Structure analysis, alignment, secondary structure | Biopython, NumPy |
| `pyrosetta_utils` | Traditional scoring, relaxation, interface metrics | PyRosetta |
| `pr_alternative_utils` | OpenMM relaxation, FreeSASA, open-source tools | OpenMM, FreeSASA, sc-rs |

Sources: [functions/__init__.py:11-15](), [README.md:15-21]()

## Dual-Path Design Philosophy

FreeBindCraft's core innovation is providing computational alternatives to PyRosetta-dependent operations through the `--no-pyrosetta` flag:

**PyRosetta vs PyRosetta-Free Execution Paths**

```mermaid
flowchart TD
    Start["bindcraft.py execution"] --> Flag{"`--no-pyrosetta flag?`"}
    
    Flag -->|"True or PyRosetta unavailable"| FreeP["PyRosetta-Free Path"]
    Flag -->|"False and PyRosetta available"| TradP["Traditional PyRosetta Path"]
    
    subgraph "PyRosetta-Free Pipeline"
        FreeP --> OMM["OpenMM Relaxation<br/>pr_alternative_utils.py<br/>• GPU-accelerated<br/>• PDBFixer preparation<br/>• OBC2 implicit solvation"]
        FreeP --> FSASA["FreeSASA + Biopython<br/>• freesasa binary<br/>• Shrake-Rupley fallback<br/>• Interface calculations"]
        FreeP --> SCRS["sc-rs Shape Complementarity<br/>• Open-source implementation<br/>• Nearly identical to PyRosetta<br/>• Binary execution"]
        FreeP --> BPAlign["Biopython Alignment<br/>• Interface residue ID<br/>• RMSD calculations<br/>• PDB alignment"]
    end
    
    subgraph "Traditional Pipeline"
        TradP --> PRRelax["PyRosetta FastRelax<br/>pyrosetta_utils.py<br/>• CPU-based protocol<br/>• Rosetta scoring"]
        TradP --> PRSASA["Native Rosetta SASA<br/>• Built-in calculations<br/>• Rosetta scoring terms"]
        TradP --> PRSC["Rosetta Shape Comp<br/>• Native implementation<br/>• Integrated scoring"]
        TradP --> PRInt["PyRosetta Interface<br/>• Native analysis<br/>• Rosetta metrics"]
    end
    
    OMM --> Results["Design Results"]
    FSASA --> Results
    SCRS --> Results
    BPAlign --> Results
    
    PRRelax --> Results
    PRSASA --> Results
    PRSC --> Results
    PRInt --> Results
```

Sources: [README.md:13-21](), [README.md:66-77]()

## Configuration and Orchestration Layer

The system uses a three-tier JSON configuration system that controls all aspects of the design process:

**Configuration Flow and Validation**

```mermaid
graph TB
    subgraph "User Input Sources"
        CmdLine["Command Line Arguments<br/>argparse in bindcraft.py"]
        Interactive["Interactive CLI<br/>--interactive or TTY detection"]
        Docker["docker_cli.py<br/>Container Configuration"]
    end
    
    subgraph "Configuration Files"
        Target["settings_target/*.json<br/>• Target PDB path<br/>• Chain specifications<br/>• Hotspot definitions"]
        Filters["settings_filters/*.json<br/>• default_filters<br/>• peptide_filters<br/>• relaxed_filters"]
        Advanced["settings_advanced/*.json<br/>• 4stage_multimer<br/>• Algorithm parameters<br/>• Pipeline settings"]
    end
    
    subgraph "Validation Layer"
        InputCheck["perform_input_check()<br/>generic_utils.py"]
        AdvCheck["perform_advanced_settings_check()<br/>generic_utils.py"]
        SystemCheck["System Validation<br/>• check_jax_gpu<br/>• ensure_binaries_executable"]
    end
    
    subgraph "Runtime Initialization"
        DirGen["generate_directories()<br/>File system setup"]
        LabelGen["generate_dataframe_labels()<br/>Data schema setup"]
        Pipeline["bindcraft.py<br/>Main pipeline execution"]
    end
    
    CmdLine --> InputCheck
    Interactive --> InputCheck
    Docker --> InputCheck
    
    Target --> InputCheck
    Filters --> InputCheck
    Advanced --> AdvCheck
    
    InputCheck --> AdvCheck
    AdvCheck --> SystemCheck
    SystemCheck --> DirGen
    SystemCheck --> LabelGen
    
    DirGen --> Pipeline
    LabelGen --> Pipeline
```

Sources: [README.md:82-100](), [README.md:235-249]()

## Deployment Architecture

FreeBindCraft supports multiple deployment scenarios with consistent interfaces:

**Deployment Options and Container Integration**

```mermaid
graph TB
    subgraph "Local Installation"
        InstallScript["install_bindcraft.sh<br/>• --no-pyrosetta flag<br/>• CUDA version selection<br/>• Package manager choice"]
        CondaEnv["BindCraft Conda Environment<br/>Activated environment"]
    end
    
    subgraph "Container Deployment"
        DockerBuild["Docker Build<br/>• Dockerfile<br/>• WITH_PYROSETTA build arg<br/>• GPU-enabled base"]
        DockerHub["Docker Hub Image<br/>cytokineking/freebindcraft-no-pyrosetta"]
        DockerCLI["docker_cli.py<br/>Interactive container wizard"]
    end
    
    subgraph "HPC Integration"
        SlurmScripts["SLURM Job Scripts<br/>Cluster execution"]
        GPUAllocation["GPU Resource Management<br/>--gpus device=idx"]
    end
    
    subgraph "Runtime Environment"
        MainExec["bindcraft.py<br/>Main execution entry"]
        VolumeMount["Volume Mounting<br/>• Input PDB files<br/>• Output directories<br/>• Configuration files"]
        UlimitConfig["File Descriptor Limits<br/>--ulimit nofile=65536:65536"]
    end
    
    InstallScript --> CondaEnv
    DockerBuild --> MainExec
    DockerHub --> MainExec
    DockerCLI --> DockerHub
    DockerCLI --> DockerBuild
    
    CondaEnv --> MainExec
    SlurmScripts --> MainExec
    
    VolumeMount --> MainExec
    UlimitConfig --> MainExec
    GPUAllocation --> MainExec
```

Sources: [README.md:28-51](), [README.md:118-250]()

## Analysis and Validation Architecture

The system includes comprehensive post-processing tools for design validation and comparison:

| Tool | Purpose | Key Features |
|------|---------|--------------|
| `analyze_bindcraft_rejections.py` | Rejection analysis | Filter failure quantification, hypothetical ranking |
| `rescore_accepted_with_rosetta.py` | PyRosetta validation | Re-score PyRosetta-free designs with traditional methods |
| `compare_interface_metrics_all.py` | Engine comparison | Side-by-side PyRosetta vs FreeSASA vs Biopython metrics |
| `test_openmm_relax.py` | Relaxation testing | OpenMM vs PyRosetta relaxation comparison |

Sources: [README.md:257-270]()

The architecture demonstrates a well-designed separation of concerns, enabling users to leverage both traditional computational biology tools and modern open-source alternatives while maintaining compatibility and providing comprehensive analysis capabilities.

---