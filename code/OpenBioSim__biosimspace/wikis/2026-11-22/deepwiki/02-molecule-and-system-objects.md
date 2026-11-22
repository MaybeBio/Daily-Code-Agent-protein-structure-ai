# Molecule and System Objects

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [python/BioSimSpace/IO/_io.py](python/BioSimSpace/IO/_io.py)
- [python/BioSimSpace/Sandpit/Exscientia/IO/_io.py](python/BioSimSpace/Sandpit/Exscientia/IO/_io.py)
- [python/BioSimSpace/Sandpit/Exscientia/_SireWrappers/_molecule.py](python/BioSimSpace/Sandpit/Exscientia/_SireWrappers/_molecule.py)
- [python/BioSimSpace/Sandpit/Exscientia/_SireWrappers/_system.py](python/BioSimSpace/Sandpit/Exscientia/_SireWrappers/_system.py)
- [python/BioSimSpace/_SireWrappers/_molecule.py](python/BioSimSpace/_SireWrappers/_molecule.py)
- [python/BioSimSpace/_SireWrappers/_system.py](python/BioSimSpace/_SireWrappers/_system.py)

</details>



This page documents the fundamental data structures that form the backbone of BioSimSpace: the `Molecule` and `System` classes. These objects represent molecular data and provide the core abstractions for all molecular simulations in BioSimSpace. For information about reading and writing these objects to files, see [IO Operations](#2.3). For details about physical unit types used by these objects, see [Types and Units System](#2.2).

## Core Architecture

BioSimSpace's molecular data structures are built as thin wrapper classes around the Sire molecular simulation library. The wrapper design provides a simplified, consistent interface while leveraging Sire's powerful underlying functionality.

```mermaid
graph TB
    subgraph "BioSimSpace Layer"
        MOL["Molecule"]
        SYS["System"]
        MOLS["Molecules"]
    end
    
    subgraph "Sire Layer"
        SIREMOL["sire.legacy.Mol.Molecule"]
        SIRESYS["sire.legacy.System.System"]
        SIREMOLGRP["sire.legacy.Mol.MoleculeGroup"]
    end
    
    subgraph "Data Flow"
        IO_READ["readMolecules()"]
        IO_SAVE["saveMolecules()"]
    end
    
    MOL --> SIREMOL
    SYS --> SIRESYS
    MOLS --> SIREMOLGRP
    
    IO_READ --> MOL
    IO_READ --> SYS
    MOL --> IO_SAVE
    SYS --> IO_SAVE
    
    MOL -.->|"toSystem()"| SYS
    SYS -.->|"getMolecules()"| MOLS
    MOL -.->|"__add__()"| MOLS
```

**Wrapper Architecture**
Sources: [python/BioSimSpace/_SireWrappers/_molecule.py:48-49](), [python/BioSimSpace/_SireWrappers/_system.py:48-49]()

## Molecule Objects

The `Molecule` class represents a single molecular entity with all its associated properties, atoms, residues, and chains.

### Molecule Class Structure

```mermaid
graph TB
    subgraph "Molecule Class"
        MOLECULE["Molecule"]
        
        subgraph "Core Properties"
            NUM["number()"]
            NATOMS["nAtoms()"]
            NRES["nResidues()"]
            NCHAIN["nChains()"]
        end
        
        subgraph "Structural Access"
            GETATOMS["getAtoms()"]
            GETRES["getResidues()"]
            COORDS["coordinates()"]
            EXTRACT["extract()"]
        end
        
        subgraph "Special Types"
            ISPERT["isPerturbable()"]
            ISWATER["isWater()"]
            MOL0["molecule0()"]
            MOL1["molecule1()"]
        end
        
        subgraph "Operations"
            COPY["copy()"]
            SEARCH["search()"]
            TOSYS["toSystem()"]
            MAKECOMPAT["makeCompatibleWith()"]
        end
    end
    
    MOLECULE --> NUM
    MOLECULE --> NATOMS
    MOLECULE --> NRES
    MOLECULE --> NCHAIN
    
    MOLECULE --> GETATOMS
    MOLECULE --> GETRES
    MOLECULE --> COORDS
    MOLECULE --> EXTRACT
    
    MOLECULE --> ISPERT
    MOLECULE --> ISWATER
    MOLECULE --> MOL0
    MOLECULE --> MOL1
    
    MOLECULE --> COPY
    MOLECULE --> SEARCH
    MOLECULE --> TOSYS
    MOLECULE --> MAKECOMPAT
```

**Molecule Class Methods and Properties**
Sources: [python/BioSimSpace/_SireWrappers/_molecule.py:51-584]()

### Key Molecule Operations

| Method | Purpose | Return Type |
|--------|---------|-------------|
| `number()` | Get unique molecule identifier | `int` |
| `nAtoms()` | Count atoms in molecule | `int` |
| `getAtoms()` | Access all atoms | `List[Atom]` |
| `getResidues()` | Access all residues | `List[Residue]` |
| `coordinates()` | Get atomic coordinates | `List[Coordinate]` |
| `extract(indices)` | Create new molecule from subset | `Molecule` |
| `search(query)` | Find atoms/residues by query | `SearchResult` |
| `copy()` | Deep copy with unique number | `Molecule` |
| `toSystem()` | Convert to single-molecule system | `System` |

Sources: [python/BioSimSpace/_SireWrappers/_molecule.py:207-584]()

### Perturbable Molecules

BioSimSpace supports perturbable molecules for free energy calculations, which contain dual topologies representing different chemical states.

```mermaid
graph LR
    subgraph "Perturbable Molecule"
        PERTMOL["Perturbable Molecule"]
        LAMBDA0["molecule0()"]
        LAMBDA1["molecule1()"]
    end
    
    subgraph "End States"
        MOL0["Molecule (λ=0)"]
        MOL1["Molecule (λ=1)"]
    end
    
    subgraph "Properties"
        PROP0["Properties with '0' suffix"]
        PROP1["Properties with '1' suffix"]
        ISPROP["is_perturbable = True"]
    end
    
    PERTMOL --> LAMBDA0
    PERTMOL --> LAMBDA1
    LAMBDA0 --> MOL0
    LAMBDA1 --> MOL1
    
    PERTMOL --> PROP0
    PERTMOL --> PROP1
    PERTMOL --> ISPROP
```

**Perturbable Molecule Support**
Sources: [python/BioSimSpace/_SireWrappers/_molecule.py:82-95](), [python/BioSimSpace/_SireWrappers/_molecule.py:428-452](), [python/BioSimSpace/_SireWrappers/_molecule.py:490-501]()

## System Objects

The `System` class represents collections of molecules, providing the primary interface for molecular systems in simulations.

### System Class Structure

```mermaid
graph TB
    subgraph "System Class"
        SYSTEM["System"]
        
        subgraph "Size Properties"
            NMOLS["nMolecules()"]
            NATOMS_SYS["nAtoms()"]
            NRES_SYS["nResidues()"]
            NCHAIN_SYS["nChains()"]
        end
        
        subgraph "Molecule Management"
            ADDMOLS["addMolecules()"]
            REMOVEMOLS["removeMolecules()"]
            UPDATEMOLS["updateMolecules()"]
            GETMOLS["getMolecules()"]
        end
        
        subgraph "Access Operations"
            GETITEM["__getitem__()"]
            GETMOL["getMolecule()"]
            GETATOM["getAtom()"]
            GETRES_SYS["getResidue()"]
        end
        
        subgraph "System Operations"
            SEARCH_SYS["search()"]
            COPY_SYS["copy()"]
            CHARGE["charge()"]
            ISSAME["isSame()"]
        end
    end
    
    SYSTEM --> NMOLS
    SYSTEM --> NATOMS_SYS
    SYSTEM --> NRES_SYS
    SYSTEM --> NCHAIN_SYS
    
    SYSTEM --> ADDMOLS
    SYSTEM --> REMOVEMOLS
    SYSTEM --> UPDATEMOLS
    SYSTEM --> GETMOLS
    
    SYSTEM --> GETITEM
    SYSTEM --> GETMOL
    SYSTEM --> GETATOM
    SYSTEM --> GETRES_SYS
    
    SYSTEM --> SEARCH_SYS
    SYSTEM --> COPY_SYS
    SYSTEM --> CHARGE
    SYSTEM --> ISSAME
```

**System Class Methods and Properties**
Sources: [python/BioSimSpace/_SireWrappers/_system.py:54-2079]()

### System Construction and Manipulation

Systems can be constructed from various molecular inputs:

```mermaid
graph TB
    subgraph "System Construction"
        SIRESYS_INPUT["sire.legacy.System.System"]
        SIREMOL_INPUT["sire.legacy.Mol.Molecule"] 
        BSS_SYS_INPUT["BioSimSpace System"]
        BSS_MOL_INPUT["BioSimSpace Molecule"]
        BSS_MOLS_INPUT["BioSimSpace Molecules"]
        MOL_LIST["List[Molecule]"]
    end
    
    subgraph "System Constructor"
        SYS_INIT["System.__init__()"]
    end
    
    subgraph "Resulting System"
        FINAL_SYS["System Object"]
    end
    
    SIRESYS_INPUT --> SYS_INIT
    SIREMOL_INPUT --> SYS_INIT
    BSS_SYS_INPUT --> SYS_INIT
    BSS_MOL_INPUT --> SYS_INIT
    BSS_MOLS_INPUT --> SYS_INIT
    MOL_LIST --> SYS_INIT
    
    SYS_INIT --> FINAL_SYS
```

**System Construction**
Sources: [python/BioSimSpace/_SireWrappers/_system.py:57-154]()

### Key System Operations

| Method | Purpose | Parameters | Return Type |
|--------|---------|------------|-------------|
| `addMolecules(molecules)` | Add molecules to system | `Molecule`, `Molecules`, `System`, or list | `None` |
| `removeMolecules(molecules)` | Remove molecules from system | `Molecule`, `Molecules`, or list | `None` |
| `updateMolecules(molecules)` | Update existing molecules | `Molecule` or list | `None` |
| `getMolecules(group)` | Get molecules by group | `str` (default "all") | `Molecules` |
| `search(query)` | Search for atoms/residues | `str` | `SearchResult` |
| `charge()` | Calculate total charge | `property_map`, `is_lambda1` | `Charge` |

Sources: [python/BioSimSpace/_SireWrappers/_system.py:555-898](), [python/BioSimSpace/_SireWrappers/_system.py:917-1081]()

## Object Relationships and Data Flow

The relationship between BioSimSpace's core objects follows a hierarchical pattern:

```mermaid
graph TB
    subgraph "Hierarchical Structure"
        SYSTEM_TOP["System"]
        MOLECULES["Molecules Collection"]
        MOLECULE_SINGLE["Individual Molecule"]
        RESIDUES["Residues"]
        ATOMS["Atoms"]
    end
    
    subgraph "Inter-object Operations"
        SYS_TO_MOL["system[index] → Molecule"]
        MOL_TO_SYS["molecule.toSystem() → System"]
        MOL_ADD["molecule1 + molecule2 → Molecules"]
        EXTRACT_OP["molecule.extract(indices) → Molecule"]
    end
    
    subgraph "IO Integration"
        READ_FILES["readMolecules(files)"]
        SAVE_FILES["saveMolecules(filebase, system, format)"]
    end
    
    SYSTEM_TOP --> MOLECULES
    MOLECULES --> MOLECULE_SINGLE
    MOLECULE_SINGLE --> RESIDUES
    RESIDUES --> ATOMS
    
    SYSTEM_TOP -.-> SYS_TO_MOL
    MOLECULE_SINGLE -.-> MOL_TO_SYS
    MOLECULE_SINGLE -.-> MOL_ADD
    MOLECULE_SINGLE -.-> EXTRACT_OP
    
    READ_FILES --> SYSTEM_TOP
    READ_FILES --> MOLECULE_SINGLE
    SYSTEM_TOP --> SAVE_FILES
    MOLECULE_SINGLE --> SAVE_FILES
```

**Object Relationships and Operations**
Sources: [python/BioSimSpace/_SireWrappers/_molecule.py:132-175](), [python/BioSimSpace/_SireWrappers/_molecule.py:574-583](), [python/BioSimSpace/_SireWrappers/_system.py:202-257]()

## Property Management

Both `Molecule` and `System` objects support flexible property management through property maps, allowing users to customize how molecular properties are accessed and stored.

```mermaid
graph LR
    subgraph "Property System"
        PROP_MAP["property_map = {...}"]
        USER_NAMES["User Property Names"]
        INTERNAL_NAMES["Internal Property Names"]
    end
    
    subgraph "Common Properties"
        COORDS_PROP["coordinates"]
        CHARGE_PROP["charge"]
        MASS_PROP["mass"]
        LJ_PROP["LJ"]
        BOND_PROP["bond"]
        ANGLE_PROP["angle"]
    end
    
    subgraph "Access Methods"
        COORDINATES["molecule.coordinates(property_map)"]
        ATOM_CHARGE["atom.charge(property_map)"]
        SYS_CHARGE["system.charge(property_map)"]
    end
    
    PROP_MAP --> USER_NAMES
    PROP_MAP --> INTERNAL_NAMES
    
    USER_NAMES -.-> COORDS_PROP
    USER_NAMES -.-> CHARGE_PROP
    USER_NAMES -.-> MASS_PROP
    USER_NAMES -.-> LJ_PROP
    USER_NAMES -.-> BOND_PROP
    USER_NAMES -.-> ANGLE_PROP
    
    COORDS_PROP --> COORDINATES
    CHARGE_PROP --> ATOM_CHARGE
    CHARGE_PROP --> SYS_CHARGE
```

**Property Management System**
Sources: [python/BioSimSpace/_SireWrappers/_molecule.py:220-256](), [python/BioSimSpace/_SireWrappers/_system.py:329-359]()

## Integration with IO Operations

The `Molecule` and `System` objects are tightly integrated with BioSimSpace's IO system for reading and writing molecular data:

| Function | Purpose | Input | Output |
|----------|---------|-------|--------|
| `readMolecules(files)` | Load system from files | File paths or URLs | `System` |
| `saveMolecules(base, system, format)` | Save system to files | System + format | File paths |
| `readPerturbableSystem()` | Load perturbable system | End state files | `System` |
| `savePerturbableSystem()` | Save perturbable system | System + base name | File paths |

Sources: [python/BioSimSpace/IO/_io.py:345-591](), [python/BioSimSpace/IO/_io.py:594-861](), [python/BioSimSpace/IO/_io.py:946-1145](), [python/BioSimSpace/IO/_io.py:864-944]()

The `Molecule` and `System` classes form the foundation for all molecular operations in BioSimSpace, providing consistent interfaces for molecular manipulation, property access, and integration with simulation workflows.

---