# Process Classes and MD Engines

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [python/BioSimSpace/Process/_amber.py](python/BioSimSpace/Process/_amber.py)
- [python/BioSimSpace/Process/_gromacs.py](python/BioSimSpace/Process/_gromacs.py)
- [python/BioSimSpace/Process/_namd.py](python/BioSimSpace/Process/_namd.py)
- [python/BioSimSpace/Process/_openmm.py](python/BioSimSpace/Process/_openmm.py)
- [python/BioSimSpace/Process/_process.py](python/BioSimSpace/Process/_process.py)
- [python/BioSimSpace/Process/_somd.py](python/BioSimSpace/Process/_somd.py)
- [python/BioSimSpace/Sandpit/Exscientia/Align/_alch_ion.py](python/BioSimSpace/Sandpit/Exscientia/Align/_alch_ion.py)
- [python/BioSimSpace/Sandpit/Exscientia/Process/_amber.py](python/BioSimSpace/Sandpit/Exscientia/Process/_amber.py)
- [python/BioSimSpace/Sandpit/Exscientia/Process/_gromacs.py](python/BioSimSpace/Sandpit/Exscientia/Process/_gromacs.py)
- [python/BioSimSpace/Sandpit/Exscientia/Process/_namd.py](python/BioSimSpace/Sandpit/Exscientia/Process/_namd.py)
- [python/BioSimSpace/Sandpit/Exscientia/Process/_openmm.py](python/BioSimSpace/Sandpit/Exscientia/Process/_openmm.py)
- [python/BioSimSpace/Sandpit/Exscientia/Process/_process.py](python/BioSimSpace/Sandpit/Exscientia/Process/_process.py)
- [python/BioSimSpace/Sandpit/Exscientia/Units/Volume/__init__.py](python/BioSimSpace/Sandpit/Exscientia/Units/Volume/__init__.py)
- [tests/Sandpit/Exscientia/Align/test_alchemical_ion.py](tests/Sandpit/Exscientia/Align/test_alchemical_ion.py)
- [tests/Sandpit/Exscientia/Process/test_amber.py](tests/Sandpit/Exscientia/Process/test_amber.py)
- [tests/Sandpit/Exscientia/Process/test_gromacs.py](tests/Sandpit/Exscientia/Process/test_gromacs.py)
- [tests/Sandpit/Exscientia/Process/test_position_restraint.py](tests/Sandpit/Exscientia/Process/test_position_restraint.py)
- [tests/Sandpit/Exscientia/Process/test_restart.py](tests/Sandpit/Exscientia/Process/test_restart.py)
- [tests/Sandpit/Exscientia/output/amber_fep.out](tests/Sandpit/Exscientia/output/amber_fep.out)
- [tests/Sandpit/Exscientia/output/amber_fep_min.out](tests/Sandpit/Exscientia/output/amber_fep_min.out)

</details>



This page documents BioSimSpace's unified interface for running molecular dynamics simulations with different engines. Process classes provide a consistent API that abstracts engine-specific details while allowing users to leverage the unique capabilities of each MD software package. For information about defining simulation parameters, see [Simulation Protocols](#4.1). For details about trajectory analysis, see [Trajectory Analysis](#6.1).

## Supported MD Engines

BioSimSpace provides process classes for five major molecular dynamics engines, each with their own strengths and use cases:

| Engine | Process Class | Primary Use Cases | Key Features |
|--------|---------------|-------------------|--------------|
| GROMACS | `Gromacs` | High-performance MD, FEP | GPU acceleration, free energy perturbation |
| AMBER | `Amber` | Biomolecular simulation, FEP | PMEMD variants, TI calculations |
| OpenMM | `OpenMM` | GPU-accelerated MD | Cross-platform, Python integration |
| SOMD | `Somd` | Free energy calculations | Monte Carlo sampling, alchemical FEP |
| NAMD | `Namd` | Large-scale simulations | Scalable parallelization |

Sources: [python/BioSimSpace/Process/_gromacs.py:72-73](), [python/BioSimSpace/Process/_amber.py:66-67](), [python/BioSimSpace/Process/_openmm.py:64-65](), [python/BioSimSpace/Process/_somd.py:64-65](), [python/BioSimSpace/Process/_namd.py:59-60]()

## Process Class Architecture

```mermaid
classDiagram
    class Process {
        +__init__(system, protocol, work_dir, seed)
        +start()
        +wait()
        +getSystem()
        +getTrajectory()
        +getTime()
        +setArg(key, value)
        +setConfig(config)
        +writeConfig(file)
        #_generate_config()
        #_generate_args()
    }
    
    class Gromacs {
        +__init__(system, protocol, exe, ignore_warnings)
        +_generate_binary_run_file()
        +addToConfig(config)
        +resetConfig()
        -_tpr_file: str
        -_mdp_file: str
        -_gro_file: str
        -_top_file: str
    }
    
    class Amber {
        +__init__(system, protocol, exe, is_gpu, explicit_dummies)
        +getCurrentRecord(record)
        +getGradient()
        -_rst_file: str
        -_prm_file: str
        -_cfg_file: str
        -_is_pmemd_cuda: bool
    }
    
    class OpenMM {
        +__init__(system, protocol, exe, platform)
        +_add_config_imports()
        +_add_config_platform()
        +_add_config_reporters()
        -_script_file: str
        -_platform: str
    }
    
    class Somd {
        +__init__(system, protocol, exe, platform)
        +getGradient()
        -_pert_file: str
        -_cfg_file: str
        -_platform: str
    }
    
    class Namd {
        +__init__(system, protocol, exe)
        -_psf_file: str
        -_pdb_file: str
        -_param_file: str
        -_cfg_file: str
    }
    
    Process <|-- Gromacs
    Process <|-- Amber
    Process <|-- OpenMM
    Process <|-- Somd
    Process <|-- Namd
```

Sources: [python/BioSimSpace/Process/_process.py:66-308](), [python/BioSimSpace/Process/_gromacs.py:72-249](), [python/BioSimSpace/Process/_amber.py:66-259](), [python/BioSimSpace/Process/_openmm.py:64-232](), [python/BioSimSpace/Process/_somd.py:64-276](), [python/BioSimSpace/Process/_namd.py:59-172]()

## Engine-Specific File Formats and Executables

```mermaid
graph TD
    subgraph "Input System + Protocol"
        SYS["System Object"]
        PROT["Protocol Object"]
    end
    
    subgraph "GROMACS Process"
        GMX_EXE["gmx mdrun"]
        GMX_FILES["GRO87 + TOP + MDP → TPR"]
        GMX_OUT["TRR + EDR + LOG"]
    end
    
    subgraph "AMBER Process"  
        AMB_EXE["sander/pmemd[.cuda]"]
        AMB_FILES["RST7 + PRM7 + CFG"]
        AMB_OUT["NC + OUT + CRD"]
    end
    
    subgraph "OpenMM Process"
        OMM_EXE["sire_python"]
        OMM_FILES["RST7 + PRM7 → Python Script"]
        OMM_OUT["DCD + LOG"]
    end
    
    subgraph "SOMD Process"
        SOMD_EXE["somd-freenrg"]
        SOMD_FILES["RST7 + PRM7 + PERT + CFG"]
        SOMD_OUT["DCD + PDB + gradients.dat"]
    end
    
    subgraph "NAMD Process"
        NAMD_EXE["namd2"]
        NAMD_FILES["PSF + PDB + PARAMS + CFG"]
        NAMD_OUT["DCD + LOG"]
    end
    
    SYS --> GMX_FILES
    SYS --> AMB_FILES  
    SYS --> OMM_FILES
    SYS --> SOMD_FILES
    SYS --> NAMD_FILES
    
    PROT --> GMX_FILES
    PROT --> AMB_FILES
    PROT --> OMM_FILES
    PROT --> SOMD_FILES
    PROT --> NAMD_FILES
    
    GMX_FILES --> GMX_EXE
    AMB_FILES --> AMB_EXE
    OMM_FILES --> OMM_EXE
    SOMD_FILES --> SOMD_EXE
    NAMD_FILES --> NAMD_EXE
    
    GMX_EXE --> GMX_OUT
    AMB_EXE --> AMB_OUT
    OMM_EXE --> OMM_OUT
    SOMD_EXE --> SOMD_OUT
    NAMD_EXE --> NAMD_OUT
```

Sources: [python/BioSimSpace/Process/_gromacs.py:210-226](), [python/BioSimSpace/Process/_amber.py:241-249](), [python/BioSimSpace/Process/_openmm.py:208-219](), [python/BioSimSpace/Process/_somd.py:242-257](), [python/BioSimSpace/Process/_namd.py:150-169]()

## Configuration Generation Workflow

Each process class implements engine-specific configuration generation through the `_generate_config()` method. This method converts the generic protocol parameters into engine-specific configuration files:

```mermaid
flowchart TD
    PROTO["Protocol Object"] --> CONFIG_GEN["_generate_config()"]
    SYSTEM["System Object"] --> CONFIG_GEN
    
    CONFIG_GEN --> GMX_CONFIG["GROMACS MDP"]
    CONFIG_GEN --> AMB_CONFIG["AMBER CFG"] 
    CONFIG_GEN --> OMM_CONFIG["OpenMM Python Script"]
    CONFIG_GEN --> SOMD_CONFIG["SOMD CFG"]
    CONFIG_GEN --> NAMD_CONFIG["NAMD CFG"]
    
    GMX_CONFIG --> GMX_OPTS["integrator = md<br/>dt = 0.002<br/>nsteps = 50000"]
    AMB_CONFIG --> AMB_OPTS["imin = 0<br/>dt = 0.002<br/>nstlim = 50000"]
    OMM_CONFIG --> OMM_OPTS["integrator = LangevinMiddleIntegrator<br/>simulation.step(steps)"]
    SOMD_CONFIG --> SOMD_OPTS["coordinate file = input.rst7<br/>timestep = 2.0 femtosecond"]
    NAMD_CONFIG --> NAMD_OPTS["timestep 2.0<br/>run 50000"]
    
    GMX_OPTS --> GROMPP["gmx grompp → TPR"]
    AMB_OPTS --> AMBER_RUN["Direct execution"]
    OMM_OPTS --> PYTHON_RUN["Python execution"]
    SOMD_OPTS --> SOMD_RUN["Direct execution"]
    NAMD_OPTS --> NAMD_RUN["Direct execution"]
```

Sources: [python/BioSimSpace/Process/_gromacs.py:334-456](), [python/BioSimSpace/Process/_amber.py:389-446](), [python/BioSimSpace/Process/_openmm.py:337-698](), [python/BioSimSpace/Process/_somd.py:419-471](), [python/BioSimSpace/Process/_namd.py:291-440]()

## Common Process Interface

Despite engine differences, all process classes provide the same core interface methods:

### Process Lifecycle

| Method | Purpose | Returns |
|--------|---------|---------|
| `start()` | Launch the simulation | Process object |
| `wait()` | Block until completion | None |
| `isRunning()` | Check if process is active | bool |
| `isError()` | Check for errors | bool |
| `kill()` | Terminate the process | None |

### Data Retrieval

| Method | Purpose | Engine Support |
|--------|---------|----------------|
| `getSystem(block=True)` | Get final/current system | All engines |
| `getTrajectory()` | Get trajectory object | All engines |
| `getFrame(index)` | Get specific trajectory frame | All engines |
| `getTime()` | Get simulation time | All engines |
| `getRecord(record)` | Get energy/property records | GROMACS, AMBER |

### Configuration Management

| Method | Purpose | Notes |
|--------|---------|-------|
| `setConfig(config)` | Set configuration strings | Engine-specific format |
| `addToConfig(line)` | Add configuration line | String or list |
| `writeConfig(file)` | Write config to file | Auto-generated filename |
| `setArg(key, value)` | Set command-line argument | Engine-specific |

Sources: [python/BioSimSpace/Process/_process.py:737-1124]()

## Free Energy Calculation Support

Different engines provide varying levels of support for alchemical free energy calculations:

| Engine | FEP Support | Perturbation Types | Lambda Coupling |
|--------|-------------|-------------------|-----------------|
| GROMACS | Full | `full` | All parameters |
| AMBER | Full | `full` | All parameters |
| SOMD | Full | `full`, multistep | Selective coupling |
| OpenMM | Limited | End states only | Basic support |
| NAMD | None | N/A | N/A |

For SOMD specifically, perturbable molecules require generation of `.pert` files:

```mermaid
graph LR
    PERT_MOL["Perturbable Molecule"] --> PERT_FILE["molecule.pert"]
    PERT_FILE --> SOMD_PROC["SOMD Process"]
    LAMBDA["Lambda Values"] --> SOMD_PROC
    SOMD_PROC --> GRAD_FILE["gradients.dat"]
    GRAD_FILE --> FE_ANALYSIS["Free Energy Analysis"]
```

Sources: [python/BioSimSpace/Process/_somd.py:329-355](), [python/BioSimSpace/Process/_gromacs.py:258-274](), [python/BioSimSpace/Process/_amber.py:275-290]()

## Platform and Hardware Support

### GPU Acceleration

| Engine | GPU Support | Platform Selection |
|--------|-------------|-------------------|
| GROMACS | CUDA | Automatic detection |
| AMBER | CUDA (pmemd.cuda) | Executable selection |
| OpenMM | CUDA, OpenCL | `platform` parameter |
| SOMD | CUDA, OpenCL | `platform` parameter |
| NAMD | CUDA | Compile-time option |

### Executable Detection

Process classes automatically detect available executables using different strategies:

- **GROMACS**: Uses `_gmx_exe` global variable
- **AMBER**: Searches `AMBERHOME/bin` and `PATH`  
- **OpenMM**: Uses bundled `sire_python`
- **SOMD**: Uses bundled executable from Sire
- **NAMD**: Searches `PATH` for `namd2`

Sources: [python/BioSimSpace/Process/_gromacs.py:176-184](), [python/BioSimSpace/Process/_amber.py:176-191](), [python/BioSimSpace/Process/_openmm.py:168-181](), [python/BioSimSpace/Process/_somd.py:198-232](), [python/BioSimSpace/Process/_namd.py:131-144]()

## Error Handling and Validation

Process classes implement several validation mechanisms:

### System Validation
- Check for parameterized molecules
- Validate coordinate properties
- Ensure topology consistency
- Verify perturbable molecule requirements for FEP

### Engine-Specific Validation
- **GROMACS**: Binary run file generation with `grompp`, warning handling
- **AMBER**: Executable variant detection (sander vs pmemd)
- **OpenMM**: Platform availability checking
- **SOMD**: Platform environment variable validation

### Runtime Monitoring
All process classes provide methods to monitor simulation progress and detect errors through log file parsing and process status checking.

Sources: [python/BioSimSpace/Process/_process.py:132-216](), [python/BioSimSpace/Process/_gromacs.py:477-662]()

---