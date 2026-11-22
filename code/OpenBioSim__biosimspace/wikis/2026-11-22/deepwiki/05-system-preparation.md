# System Preparation

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [doc/source/tutorials/hydration_freenrg.rst](doc/source/tutorials/hydration_freenrg.rst)
- [doc/source/tutorials/images/ethane_methanol_mapping.png](doc/source/tutorials/images/ethane_methanol_mapping.png)
- [python/BioSimSpace/IO/__init__.py](python/BioSimSpace/IO/__init__.py)
- [python/BioSimSpace/Parameters/_Protocol/_amber.py](python/BioSimSpace/Parameters/_Protocol/_amber.py)
- [python/BioSimSpace/Parameters/_Protocol/_openforcefield.py](python/BioSimSpace/Parameters/_Protocol/_openforcefield.py)
- [python/BioSimSpace/Parameters/_Protocol/_protocol.py](python/BioSimSpace/Parameters/_Protocol/_protocol.py)
- [python/BioSimSpace/Parameters/__init__.py](python/BioSimSpace/Parameters/__init__.py)
- [python/BioSimSpace/Parameters/_parameters.py](python/BioSimSpace/Parameters/_parameters.py)
- [python/BioSimSpace/Parameters/_process.py](python/BioSimSpace/Parameters/_process.py)
- [python/BioSimSpace/Process/_task.py](python/BioSimSpace/Process/_task.py)
- [python/BioSimSpace/Sandpit/Exscientia/Parameters/_Protocol/_amber.py](python/BioSimSpace/Sandpit/Exscientia/Parameters/_Protocol/_amber.py)
- [python/BioSimSpace/Sandpit/Exscientia/Parameters/_Protocol/_openforcefield.py](python/BioSimSpace/Sandpit/Exscientia/Parameters/_Protocol/_openforcefield.py)
- [python/BioSimSpace/Sandpit/Exscientia/Parameters/_Protocol/_protocol.py](python/BioSimSpace/Sandpit/Exscientia/Parameters/_Protocol/_protocol.py)
- [python/BioSimSpace/Sandpit/Exscientia/Parameters/_parameters.py](python/BioSimSpace/Sandpit/Exscientia/Parameters/_parameters.py)
- [python/BioSimSpace/Sandpit/Exscientia/Parameters/_process.py](python/BioSimSpace/Sandpit/Exscientia/Parameters/_process.py)
- [python/BioSimSpace/Solvent/__init__.py](python/BioSimSpace/Solvent/__init__.py)
- [tests/Parameters/test_parameters.py](tests/Parameters/test_parameters.py)
- [tests/Sandpit/Exscientia/Parameters/test_parameters.py](tests/Sandpit/Exscientia/Parameters/test_parameters.py)

</details>



System preparation encompasses the tools and workflows required to transform raw molecular structures into simulation-ready systems. This includes applying force field parameters to molecules, adding solvent environments, and creating perturbable molecules for free energy calculations. For information about reading molecular data, see [IO Operations](#2.3). For details about running simulations with prepared systems, see [Simulation Execution](#4).

## Overview

System preparation in BioSimSpace bridges the gap between initial molecular structures and simulation-ready systems through three primary operations: parameterization (applying force field parameters), solvation (adding solvent molecules and ions), and molecular alignment/merging (creating perturbable molecules for alchemical calculations).

```mermaid
graph TD
    subgraph Input["Input Molecules"]
        RAW["Raw Structures<br/>(PDB, MOL2, SDF)"]
        SMILES["SMILES Strings"]
    end
    
    subgraph Preparation["System Preparation"]
        PARAM["Parameterization<br/>BioSimSpace.Parameters"]
        SOLV["Solvation<br/>BioSimSpace.Solvent"]
        ALIGN["Alignment & Merging<br/>BioSimSpace.Align"]
    end
    
    subgraph Output["Simulation-Ready Systems"]
        PARAM_MOL["Parameterized Molecules"]
        SOLV_SYS["Solvated Systems"]
        PERT_SYS["Perturbable Systems"]
    end
    
    RAW --> PARAM
    SMILES --> PARAM
    PARAM --> PARAM_MOL
    PARAM_MOL --> SOLV
    PARAM_MOL --> ALIGN
    SOLV --> SOLV_SYS
    ALIGN --> PERT_SYS
    
    SOLV_SYS --> SIM["Simulation Execution"]
    PERT_SYS --> SIM
```

**Sources:** [python/BioSimSpace/Parameters/_parameters.py:68-131](), [python/BioSimSpace/Solvent/__init__.py:22-113](), [doc/source/tutorials/hydration_freenrg.rst:20-93]()

## Parameterization Workflow

The parameterization system applies force field parameters to molecules using various computational chemistry tools. The process is handled asynchronously through the `Process` class, allowing users to continue working while parameterization runs in the background.

```mermaid
graph TD
    subgraph API["User Interface"]
        PARAMETERISE["parameterise()"]
        GAFF["gaff()"]
        GAFF2["gaff2()"]
        FF14SB["ff14SB()"]
        OPENFF["openff_*()"]
    end
    
    subgraph Core["Core Processing"]
        PROCESS["Parameters._process.Process"]
        PROTOCOL["Parameters._Protocol"]
        VALIDATE["_validate()"]
    end
    
    subgraph Protocols["Force Field Protocols"]
        AMBER_PROT["_Protocol.AmberProtein"]
        GAFF_PROT["_Protocol.GAFF"]
        OPENFF_PROT["_Protocol.OpenForceField"]
    end
    
    subgraph External["External Tools"]
        TLEAP["tLEaP (AmberTools)"]
        ANTECHAMBER["antechamber"]
        PDB2GMX["pdb2gmx (GROMACS)"]
        OPENFF_TOOLKIT["OpenFF Toolkit"]
    end
    
    PARAMETERISE --> VALIDATE
    GAFF --> VALIDATE
    GAFF2 --> VALIDATE
    FF14SB --> VALIDATE
    OPENFF --> VALIDATE
    
    VALIDATE --> PROCESS
    PROCESS --> PROTOCOL
    
    PROTOCOL --> AMBER_PROT
    PROTOCOL --> GAFF_PROT
    PROTOCOL --> OPENFF_PROT
    
    AMBER_PROT --> TLEAP
    AMBER_PROT --> PDB2GMX
    GAFF_PROT --> ANTECHAMBER
    OPENFF_PROT --> OPENFF_TOOLKIT
```

**Sources:** [python/BioSimSpace/Parameters/_parameters.py:68-131](), [python/BioSimSpace/Parameters/_process.py:95-334](), [python/BioSimSpace/Parameters/_Protocol/_amber.py:116-613]()

## Force Field Support Matrix

BioSimSpace supports multiple force field families through a unified interface:

| Force Field | Type | Tool | Compatibility |
|-------------|------|------|---------------|
| GAFF/GAFF2 | Small molecules | antechamber | Full support |
| ff14SB | Protein | tLEaP/pdb2gmx | Full support |
| ff99SB | Protein | tLEaP/pdb2gmx | Full support |
| ff03 | Protein | tLEaP/pdb2gmx | Full support |
| OpenFF | Small molecules | OpenFF Toolkit | Full support |

The parameterization process handles charge calculation, atom typing, and parameter assignment automatically. For AMBER force fields, the system can detect disulfide bonds and structural ions, requiring water model specification for ion parameters.

**Sources:** [python/BioSimSpace/Parameters/_parameters.py:44-50](), [python/BioSimSpace/Parameters/_parameters.py:588-625](), [python/BioSimSpace/Parameters/_Protocol/_amber.py:444-452]()

## Solvation System

The solvation system adds water molecules and ions to create simulation-ready systems. It provides both box-based and shell-based solvation with automatic ion placement for charge neutralization.

```mermaid
graph TD
    subgraph Interface["Solvation Interface"]
        SOLVATE["solvate(water_model, molecule, ...)"]
        TIP3P["tip3p(molecule, box/shell, ...)"]
        TIP4P["tip4p(molecule, box/shell, ...)"]
        SPC["spc(molecule, box/shell, ...)"]
        SPCE["spce(molecule, box/shell, ...)"]
    end
    
    subgraph Parameters["Solvation Parameters"]
        BOX["box: [Length, Length, Length]"]
        SHELL["shell: Length"]
        ION_CONC["ion_conc: float"]
        NEUTRALISE["neutralise: bool"]
    end
    
    subgraph Processing["Internal Processing"]
        WATER_MODELS["waterModels()"]
        VALIDATE_MODEL["_validate_water_model()"]
        ION_PLACEMENT["Ion placement algorithm"]
    end
    
    subgraph Output["Solvated System"]
        WATER_BOX["Water molecules"]
        IONS["Counterions (Na+, Cl-)"]
        SOLUTE["Original molecule(s)"]
    end
    
    SOLVATE --> VALIDATE_MODEL
    TIP3P --> VALIDATE_MODEL
    TIP4P --> VALIDATE_MODEL
    SPC --> VALIDATE_MODEL
    SPCE --> VALIDATE_MODEL
    
    BOX --> SOLVATE
    SHELL --> SOLVATE
    ION_CONC --> ION_PLACEMENT
    NEUTRALISE --> ION_PLACEMENT
    
    VALIDATE_MODEL --> WATER_MODELS
    SOLVATE --> WATER_BOX
    ION_PLACEMENT --> IONS
    WATER_BOX --> Output
    IONS --> Output
    SOLUTE --> Output
```

**Sources:** [python/BioSimSpace/Solvent/__init__.py:31-37](), [python/BioSimSpace/Solvent/_solvent.py](), [doc/source/tutorials/hydration_freenrg.rst:89-92]()

## Alignment and Merging for Free Energy Calculations

The alignment and merging system creates perturbable molecules for alchemical free energy calculations by finding atom mappings between molecules and creating dual-topology systems.

```mermaid
graph TD
    subgraph Input["Input Molecules"]
        MOL_A["Molecule A<br/>(e.g., ethane)"]
        MOL_B["Molecule B<br/>(e.g., methanol)"]
    end
    
    subgraph Alignment["BioSimSpace.Align"]
        MATCH["matchAtoms(mol_a, mol_b)"]
        RMSD_ALIGN["rmsdAlign(mol_a, mol_b, mapping)"]
        FLEX_ALIGN["flexAlign(mol_a, mol_b, mapping)"]
        MERGE["merge(mol_a, mol_b, mapping)"]
    end
    
    subgraph Mapping["Atom Mapping"]
        MCS["Maximum Common Substructure"]
        SCORING["Mapping score calculation"]
        INDICES["Index mapping dict"]
    end
    
    subgraph Output["Perturbable Molecule"]
        LAMBDA_0["λ=0 state (Molecule A)"]
        LAMBDA_1["λ=1 state (Molecule B)"]
        DUMMY_ATOMS["Dummy atoms"]
        DUAL_TOPOLOGY["Dual topology parameters"]
    end
    
    MOL_A --> MATCH
    MOL_B --> MATCH
    MATCH --> MCS
    MCS --> SCORING
    SCORING --> INDICES
    
    INDICES --> RMSD_ALIGN
    INDICES --> FLEX_ALIGN
    RMSD_ALIGN --> MERGE
    FLEX_ALIGN --> MERGE
    
    MERGE --> LAMBDA_0
    MERGE --> LAMBDA_1
    MERGE --> DUMMY_ATOMS
    MERGE --> DUAL_TOPOLOGY
```

**Sources:** [doc/source/tutorials/hydration_freenrg.rst:25-87](), [python/BioSimSpace/Align](), [tests/Parameters/test_parameters.py:146-174]()

## Integration with Simulation Workflow

System preparation components integrate seamlessly with the broader BioSimSpace simulation workflow:

```mermaid
graph LR
    subgraph Preparation["System Preparation"]
        PARAM_FUNC["Parameters.gaff()"]
        SOLV_FUNC["Solvent.tip3p()"]
        ALIGN_FUNC["Align.merge()"]
    end
    
    subgraph DataStructures["Core Data"]
        MOLECULE["_SireWrappers.Molecule"]
        SYSTEM["_SireWrappers.System"]
        TYPES["Types (Length, Charge, etc.)"]
    end
    
    subgraph Simulation["Simulation Setup"]
        PROTOCOL["Protocol classes"]
        PROCESS["Process classes"]
        CONFIG["_Config generation"]
    end
    
    PARAM_FUNC --> MOLECULE
    SOLV_FUNC --> SYSTEM
    ALIGN_FUNC --> MOLECULE
    
    MOLECULE --> PROTOCOL
    SYSTEM --> PROTOCOL
    TYPES --> PROTOCOL
    
    PROTOCOL --> PROCESS
    PROCESS --> CONFIG
```

**Sources:** [python/BioSimSpace/Parameters/_parameters.py:370-404](), [python/BioSimSpace/Parameters/_process.py:198-248](), [doc/source/tutorials/hydration_freenrg.rst:94-153]()

The system preparation workflow is designed to be both user-friendly and computationally efficient, with automatic background processing, comprehensive error handling, and support for multiple molecular dynamics engines downstream. All parameterization processes return `Process` objects that can be queried for status and results, enabling interactive workflows in Jupyter notebooks and other interactive environments.

---