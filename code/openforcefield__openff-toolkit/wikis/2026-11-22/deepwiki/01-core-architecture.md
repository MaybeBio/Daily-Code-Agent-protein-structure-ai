# Core Architecture

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.pre-commit-config.yaml](.pre-commit-config.yaml)
- [The-SMIRNOFF-force-field-format.md](The-SMIRNOFF-force-field-format.md)
- [docs/releasehistory.md](docs/releasehistory.md)
- [openff/toolkit/_tests/test_toolkits.py](openff/toolkit/_tests/test_toolkits.py)
- [openff/toolkit/_tests/test_topology.py](openff/toolkit/_tests/test_topology.py)
- [openff/toolkit/topology/molecule.py](openff/toolkit/topology/molecule.py)
- [openff/toolkit/topology/topology.py](openff/toolkit/topology/topology.py)
- [openff/toolkit/typing/engines/smirnoff/forcefield.py](openff/toolkit/typing/engines/smirnoff/forcefield.py)
- [openff/toolkit/typing/engines/smirnoff/parameters.py](openff/toolkit/typing/engines/smirnoff/parameters.py)
- [openff/toolkit/utils/exceptions.py](openff/toolkit/utils/exceptions.py)
- [openff/toolkit/utils/openeye_wrapper.py](openff/toolkit/utils/openeye_wrapper.py)
- [openff/toolkit/utils/rdkit_wrapper.py](openff/toolkit/utils/rdkit_wrapper.py)
- [openff/toolkit/utils/serialization.py](openff/toolkit/utils/serialization.py)
- [openff/toolkit/utils/toolkits.py](openff/toolkit/utils/toolkits.py)
- [openff/toolkit/utils/utils.py](openff/toolkit/utils/utils.py)
- [setup.cfg](setup.cfg)

</details>



This document describes the fundamental architectural components of the OpenFF Toolkit and how they interact to provide force field parametrization capabilities. It covers the core data models for chemical representation, the SMIRNOFF force field engine, and the toolkit integration layer that enables interoperability with external cheminformatics libraries.

For information about specific parameter handlers and force field implementation details, see [SMIRNOFF Force Field System](#2.2). For toolkit wrapper implementations and usage patterns, see [Toolkit Integration System](#2.3).

## Core Chemical Representation System

The OpenFF Toolkit's chemical representation is built around three fundamental classes that form a hierarchical object model: `Molecule`, `Topology`, and their constituent `Atom` and `Bond` objects.

### Molecule and Atom/Bond Architecture

```mermaid
graph TB
    subgraph "Chemical Representation Core"
        FrozenMolecule["FrozenMolecule<br/>Immutable chemical structure"]
        Molecule["Molecule<br/>Extends FrozenMolecule"]
        Atom["Atom<br/>Chemical atom representation"]
        Bond["Bond<br/>Chemical bond representation"]
        
        FrozenMolecule --> Atom
        FrozenMolecule --> Bond
        Molecule --> FrozenMolecule
        
        Atom --> |"bonded_atoms"| Atom
        Bond --> |"atoms"| Atom
    end
    
    subgraph "Metadata and Properties"
        AtomMetadataDict["AtomMetadataDict<br/>Atom-level metadata"]
        HierarchyElement["HierarchyElement<br/>Residue/chain info"]
        
        Atom --> AtomMetadataDict
        Atom --> HierarchyElement
    end
    
    subgraph "Conformer and Charge Data"
        Conformers["_conformers: list[Quantity]<br/>3D coordinates"]
        PartialCharges["_partial_charges: Quantity<br/>Atomic charges"]
        
        FrozenMolecule --> Conformers
        FrozenMolecule --> PartialCharges
    end
```

The `FrozenMolecule` class [openff/toolkit/topology/molecule.py:865-908]() serves as the immutable base class containing atoms, bonds, and molecular properties. The `Molecule` class extends this to provide mutable operations for building and modifying chemical structures.

### Topology System Architecture

```mermaid
graph TB
    subgraph "Topology Container"
        Topology["Topology<br/>System-level container"]
        molecules["_molecules: list[MoleculeLike]<br/>Component molecules"]
        
        Topology --> molecules
    end
    
    subgraph "Valence Dictionaries"
        ValenceDict["ValenceDict<br/>Bond/angle indexing"]
        ImproperDict["ImproperDict<br/>Improper torsion indexing"]  
        TagSortedDict["TagSortedDict<br/>Tagged parameter ordering"]
        SortedDict["SortedDict<br/>General sorted indexing"]
        
        Topology --> ValenceDict
        Topology --> ImproperDict
        Topology --> TagSortedDict
    end
    
    subgraph "System Properties"
        BoxVectors["box_vectors: Quantity<br/>Periodic boundary conditions"]
        ConstrainedPairs["constrained_atom_pairs<br/>Distance constraints"]
        
        Topology --> BoxVectors
        Topology --> ConstrainedPairs
    end
    
    subgraph "Molecule Types"
        MoleculeLike["MoleculeLike<br/>Union type"]
        RegularMolecule["Molecule"]
        SimpleMolecule["_SimpleMolecule<br/>Lightweight representation"]
        
        MoleculeLike --> RegularMolecule
        MoleculeLike --> SimpleMolecule
        molecules --> MoleculeLike
    end
```

The `Topology` class [openff/toolkit/topology/topology.py:394-431]() acts as a container for one or more molecules, managing system-level properties like periodic boundary conditions and constraints. It uses specialized dictionary classes to efficiently handle valence term indexing with proper symmetry considerations.

Sources: [openff/toolkit/topology/molecule.py:865-908](), [openff/toolkit/topology/topology.py:394-431](), [openff/toolkit/topology/topology.py:160-392]()

## SMIRNOFF Force Field Engine

The SMIRNOFF force field system implements a modular, plugin-based architecture for parameter assignment using SMIRKS pattern matching.

### ForceField and ParameterHandler Architecture

```mermaid
graph TB
    subgraph "Force Field Core"
        ForceField["ForceField<br/>Main force field class"]
        ParameterIOHandler["ParameterIOHandler<br/>Serialization interface"]
        
        ForceField --> ParameterIOHandler
    end
    
    subgraph "Parameter Handler System"
        ParameterHandler["ParameterHandler<br/>Base parameter class"]
        BondHandler["BondHandler<br/>Bond parameters"]
        AngleHandler["AngleHandler<br/>Angle parameters"] 
        ProperTorsionHandler["ProperTorsionHandler<br/>Torsion parameters"]
        vdWHandler["vdWHandler<br/>van der Waals parameters"]
        ElectrostaticsHandler["ElectrostaticsHandler<br/>Electrostatic methods"]
        
        ForceField --> ParameterHandler
        ParameterHandler --> BondHandler
        ParameterHandler --> AngleHandler
        ParameterHandler --> ProperTorsionHandler
        ParameterHandler --> vdWHandler
        ParameterHandler --> ElectrostaticsHandler
    end
    
    subgraph "Parameter Types"
        ParameterType["ParameterType<br/>Individual parameter"]
        BondType["BondType"]
        AngleType["AngleType"]
        ProperTorsionType["ProperTorsionType"]
        vdWType["vdWType"]
        
        BondHandler --> BondType
        AngleHandler --> AngleType
        ProperTorsionHandler --> ProperTorsionType
        vdWHandler --> vdWType
        ParameterType --> BondType
        ParameterType --> AngleType
        ParameterType --> ProperTorsionType
        ParameterType --> vdWType
    end
```

The `ForceField` class [openff/toolkit/typing/engines/smirnoff/forcefield.py:137-223]() serves as the main entry point for SMIRNOFF parameter assignment. It manages a collection of `ParameterHandler` objects that each handle specific types of interactions through SMIRKS pattern matching.

### Parameter Attribute System

```mermaid
graph TB
    subgraph "Parameter Descriptors"
        ParameterAttribute["ParameterAttribute<br/>Basic parameter descriptor"]
        IndexedParameterAttribute["IndexedParameterAttribute<br/>Multiple term parameters"]
        MappedParameterAttribute["MappedParameterAttribute<br/>Key-value parameters"]
        IndexedMappedParameterAttribute["IndexedMappedParameterAttribute<br/>Sequence of mappings"]
        
        ParameterAttribute --> IndexedParameterAttribute
        ParameterAttribute --> MappedParameterAttribute
        ParameterAttribute --> IndexedMappedParameterAttribute
    end
    
    subgraph "Validation and Conversion"
        UnitValidation["Unit validation<br/>_validate_units()"]
        CustomConverter["Custom converter<br/>_call_converter()"]
        ValidatedList["ValidatedList<br/>Sequence validation"]
        ValidatedDict["ValidatedDict<br/>Mapping validation"]
        
        ParameterAttribute --> UnitValidation
        ParameterAttribute --> CustomConverter
        IndexedParameterAttribute --> ValidatedList
        MappedParameterAttribute --> ValidatedDict
    end
    
    subgraph "Usage in Parameter Types"
        smirks["smirks: ParameterAttribute<br/>SMIRKS pattern"]
        length["length: ParameterAttribute<br/>Bond length parameter"]
        k["k: IndexedParameterAttribute<br/>Force constants"]
        
        ParameterType --> smirks
        BondType --> length
        ProperTorsionType --> k
    end
```

The parameter system uses descriptor classes [openff/toolkit/typing/engines/smirnoff/parameters.py:225-436]() to provide automatic unit validation, type conversion, and constraints on parameter values.

Sources: [openff/toolkit/typing/engines/smirnoff/forcefield.py:137-223](), [openff/toolkit/typing/engines/smirnoff/parameters.py:225-436](), [openff/toolkit/typing/engines/smirnoff/parameters.py:438-585]()

## Toolkit Integration Layer

The toolkit integration system provides a unified interface to multiple cheminformatics libraries through a registry pattern and wrapper classes.

### ToolkitRegistry and Wrapper Architecture

```mermaid
graph TB
    subgraph "Registry System"
        ToolkitRegistry["ToolkitRegistry<br/>Manages toolkit precedence"]
        GLOBAL_TOOLKIT_REGISTRY["GLOBAL_TOOLKIT_REGISTRY<br/>Default global instance"]
        toolkit_registry_manager["toolkit_registry_manager<br/>Context manager"]
        
        GLOBAL_TOOLKIT_REGISTRY --> ToolkitRegistry
        toolkit_registry_manager --> ToolkitRegistry
    end
    
    subgraph "Base Wrapper System"
        ToolkitWrapper["ToolkitWrapper<br/>Abstract base class"]
        toolkit_name["_toolkit_name: str"]
        toolkit_version["_toolkit_version: str"]
        is_available["is_available(): bool"]
        
        ToolkitWrapper --> toolkit_name
        ToolkitWrapper --> toolkit_version
        ToolkitWrapper --> is_available
    end
    
    subgraph "Concrete Wrappers"
        OpenEyeToolkitWrapper["OpenEyeToolkitWrapper<br/>Commercial toolkit"]
        RDKitToolkitWrapper["RDKitToolkitWrapper<br/>Open source toolkit"]
        AmberToolsToolkitWrapper["AmberToolsToolkitWrapper<br/>Charge calculation"]
        NAGLToolkitWrapper["NAGLToolkitWrapper<br/>Neural network charges"]
        BuiltInToolkitWrapper["BuiltInToolkitWrapper<br/>Basic operations"]
        
        ToolkitWrapper --> OpenEyeToolkitWrapper
        ToolkitWrapper --> RDKitToolkitWrapper
        ToolkitWrapper --> AmberToolsToolkitWrapper
        ToolkitWrapper --> NAGLToolkitWrapper
        ToolkitWrapper --> BuiltInToolkitWrapper
        
        ToolkitRegistry --> OpenEyeToolkitWrapper
        ToolkitRegistry --> RDKitToolkitWrapper
        ToolkitRegistry --> AmberToolsToolkitWrapper
    end
```

The `ToolkitRegistry` class [openff/toolkit/utils/toolkit_registry.py]() manages the precedence order of available toolkits and dispatches method calls to the first capable toolkit. The `GLOBAL_TOOLKIT_REGISTRY` [openff/toolkit/utils/toolkits.py:102-110]() provides a default instance used throughout the codebase.

### Toolkit Method Dispatch

```mermaid
graph TB
    subgraph "Method Categories"
        MoleculeIO["Molecule I/O<br/>from_file, to_file"]
        ConformerGen["Conformer Generation<br/>generate_conformers"]
        ChargeCalc["Charge Calculation<br/>assign_partial_charges"]
        Stereochemistry["Stereochemistry<br/>assign_stereochemistry_from_3d"]
        Aromaticity["Aromaticity<br/>assign_aromaticity"]
    end
    
    subgraph "Dispatch Pattern"
        RegistryCall["registry.call(method_name, *args)"]
        FirstAvailable["Find first available toolkit"]
        MethodExecution["Execute toolkit method"]
        FallbackLogic["Try next toolkit on failure"]
        
        RegistryCall --> FirstAvailable
        FirstAvailable --> MethodExecution
        MethodExecution --> FallbackLogic
    end
    
    subgraph "Supported File Formats"
        toolkit_file_read_formats["_toolkit_file_read_formats<br/>Input format list"]
        toolkit_file_write_formats["_toolkit_file_write_formats<br/>Output format list"]
        
        OpenEyeToolkitWrapper --> toolkit_file_read_formats
        RDKitToolkitWrapper --> toolkit_file_write_formats
    end
```

Each toolkit wrapper implements a standard interface for common operations, with the registry automatically selecting the appropriate toolkit based on availability and method support.

Sources: [openff/toolkit/utils/toolkits.py:102-110](), [openff/toolkit/utils/openeye_wrapper.py:89-227](), [openff/toolkit/utils/rdkit_wrapper.py:73-132]()

## Data Flow and System Integration

The OpenFF Toolkit follows a clear data flow from input molecular representations through force field parametrization to simulation-ready output.

### Parametrization Pipeline

```mermaid
graph LR
    subgraph "Input Sources"
        SMILES["SMILES strings"]
        SDF["SDF files"]
        PDB["PDB files"] 
        OtherFormats["Other formats"]
    end
    
    subgraph "Chemical Representation"
        from_smiles["Molecule.from_smiles()"]
        from_file["Molecule.from_file()"]
        from_pdb["Topology.from_pdb()"]
        
        SMILES --> from_smiles
        SDF --> from_file
        PDB --> from_pdb
        OtherFormats --> from_file
    end
    
    subgraph "Force Field Application"
        create_interchange["ForceField.create_interchange()"]
        parameter_assignment["Parameter assignment via SMIRKS"]
        
        from_smiles --> create_interchange
        from_file --> create_interchange
        from_pdb --> create_interchange
        create_interchange --> parameter_assignment
    end
    
    subgraph "Output Generation"
        Interchange["Interchange object"]
        to_openmm["to_openmm()"]
        to_gromacs["to_gromacs()"]
        to_amber["to_amber()"]
        
        parameter_assignment --> Interchange
        Interchange --> to_openmm
        Interchange --> to_gromacs
        Interchange --> to_amber
    end
```

### Component Interaction Flow

```mermaid
graph TB
    subgraph "User Interface Layer"
        UserCode["User application code"]
        HighLevelAPI["High-level API calls"]
    end
    
    subgraph "Core Processing"
        MoleculeCreation["Molecule/Topology creation"]
        ToolkitDispatch["Toolkit method dispatch"]
        ParameterMatching["SMIRKS pattern matching"]
        ForceFieldAssignment["Parameter assignment"]
    end
    
    subgraph "External Dependencies"
        CheminformaticsToolkits["RDKit, OpenEye, etc."]
        SimulationPackages["OpenMM, GROMACS, Amber"]
    end
    
    UserCode --> HighLevelAPI
    HighLevelAPI --> MoleculeCreation
    MoleculeCreation --> ToolkitDispatch
    ToolkitDispatch --> CheminformaticsToolkits
    ToolkitDispatch --> ParameterMatching
    ParameterMatching --> ForceFieldAssignment
    ForceFieldAssignment --> SimulationPackages
```

The system maintains clear separation between chemical representation, force field logic, and external toolkit integration, enabling modularity and extensibility while providing a unified user interface.

Sources: [openff/toolkit/topology/molecule.py:865-908](), [openff/toolkit/typing/engines/smirnoff/forcefield.py:137-223](), [openff/toolkit/utils/toolkits.py:102-110]()

---