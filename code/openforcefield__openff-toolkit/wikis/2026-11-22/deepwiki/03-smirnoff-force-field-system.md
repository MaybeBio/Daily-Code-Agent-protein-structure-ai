# SMIRNOFF Force Field System

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [The-SMIRNOFF-force-field-format.md](The-SMIRNOFF-force-field-format.md)
- [docs/typing.rst](docs/typing.rst)
- [openff/toolkit/_tests/test_forcefield.py](openff/toolkit/_tests/test_forcefield.py)
- [openff/toolkit/_tests/test_molecule.py](openff/toolkit/_tests/test_molecule.py)
- [openff/toolkit/_tests/test_parameters.py](openff/toolkit/_tests/test_parameters.py)

</details>



## Purpose and Scope

The SMIRNOFF Force Field System is the core parameterization engine of the OpenFF toolkit, responsible for applying molecular mechanics parameters to chemical systems using SMIRKS-based pattern matching. This system implements the SMIRNOFF (SMIRks Native Open Force Field) specification, which uses chemical perception via SMIRKS patterns rather than atom types for parameter assignment.

This document covers the force field architecture, parameter handlers, SMIRKS pattern matching, and the parameter application process. For information about the underlying molecule and topology representations, see [Molecule and Topology System](#2.1). For details about cheminformatics toolkit integration, see [Toolkit Integration System](#2.3).

## Core Architecture

The SMIRNOFF system is built around three main components: the `ForceField` class that orchestrates parameter assignment, `ParameterHandler` classes that manage specific types of parameters, and `ParameterType` classes that represent individual parameter definitions.

### ForceField Class Structure

```mermaid
graph TD
    FF["ForceField"] --> PH1["BondHandler"]
    FF --> PH2["AngleHandler"] 
    FF --> PH3["ProperTorsionHandler"]
    FF --> PH4["ImproperTorsionHandler"]
    FF --> PH5["vdWHandler"]
    FF --> PH6["ElectrostaticsHandler"]
    FF --> PH7["LibraryChargeHandler"]
    FF --> PH8["ToolkitAM1BCCHandler"]
    
    PH1 --> PT1["BondType parameters"]
    PH2 --> PT2["AngleType parameters"]
    PH3 --> PT3["ProperTorsionType parameters"]
    PH4 --> PT4["ImproperTorsionType parameters"]
    PH5 --> PT5["vdWType parameters"]
    PH6 --> PT6["Electrostatics settings"]
    PH7 --> PT7["LibraryChargeType parameters"]
    PH8 --> PT8["AM1BCC settings"]
```

**Core ForceField Architecture**

The `ForceField` class serves as the central coordinator, maintaining a registry of `ParameterHandler` instances. Each handler manages parameters for a specific energy term (bonds, angles, etc.) and contains a list of `ParameterType` objects that define the actual parameter values and their associated SMIRKS patterns.

Sources: [openff/toolkit/_tests/test_forcefield.py:782-901](), [docs/typing.rst:16-31]()

### Parameter Handler Registration

```mermaid
graph LR
    FF["ForceField"] --> Registry["_parameter_handlers dict"]
    Registry --> BH["'Bonds': BondHandler"]
    Registry --> AH["'Angles': AngleHandler"]
    Registry --> TH["'ProperTorsions': ProperTorsionHandler"]
    Registry --> VH["'vdW': vdWHandler"]
    
    FF --> Classes["_parameter_handler_classes dict"]
    Classes --> BC["'Bonds': BondHandler class"]
    Classes --> AC["'Angles': AngleHandler class"]
    Classes --> TC["'ProperTorsions': ProperTorsionHandler class"]
    Classes --> VC["'vdW': vdWHandler class"]
```

**Parameter Handler Registration System**

Parameter handlers are registered by their `TAGNAME` attribute and can be accessed using the `get_parameter_handler()` method or dictionary-style lookup. The force field maintains both handler instances and handler classes for dynamic instantiation.

Sources: [openff/toolkit/_tests/test_forcefield.py:653-683](), [openff/toolkit/_tests/test_forcefield.py:1672-1702]()

## SMIRKS Pattern Matching System

The SMIRNOFF system uses SMIRKS (SMILES arbitrary target specification) patterns to identify chemical environments for parameter assignment. Each parameter includes a SMIRKS pattern that defines which molecular substructures it applies to.

### Pattern Hierarchy and Precedence

```mermaid
graph TD
    Mol["Molecule topology"] --> Match["SMIRKS pattern matching"]
    Match --> Generic["[*:1]~[*:2] (generic bonds)"]
    Match --> Specific1["[#6:1]-[#6:2] (C-C bonds)"]
    Match --> Specific2["[#6X4:1]-[#6X4:2] (sp3 C-C bonds)"]
    
    Generic --> Apply1["Lower precedence"]
    Specific1 --> Apply2["Higher precedence"]
    Specific2 --> Apply3["Highest precedence"]
    
    Apply3 --> Result["Final parameter assignment"]
    Apply2 -.-> Result
    Apply1 -.-> Result
```

**SMIRKS Pattern Precedence System**

Parameters are applied in order of specificity, with more specific patterns overriding more general ones. The last matching parameter in the handler's parameter list is used for each chemical environment.

Sources: [openff/toolkit/_tests/test_forcefield.py:1725-1741](), [openff/toolkit/_tests/test_parameters.py:826-913]()

### Tagged Atom System

SMIRKS patterns use numbered tags (`:1`, `:2`, etc.) to identify specific atoms that receive parameters. Each parameter type defines how many tagged atoms it expects and what parameters apply to each.

```mermaid
graph LR
    SMIRKS["[#6X4:1]-[#6X4:2]"] --> Atom1[":1 tagged atom"]
    SMIRKS --> Atom2[":2 tagged atom"]
    
    Atom1 --> Param1["BondType.length"]
    Atom1 --> Param2["BondType.k"]
    Atom2 --> Param1
    Atom2 --> Param2
```

**Tagged Atom Parameter Assignment**

Sources: [openff/toolkit/_tests/test_parameters.py:1098-1140]()

## Parameter Types and Handlers

The SMIRNOFF system includes handlers for all major molecular mechanics energy terms, each with specialized parameter types and validation logic.

### Core Parameter Handlers

| Handler | Purpose | Parameter Attributes |
|---------|---------|---------------------|
| `BondHandler` | Harmonic bond potentials | `length`, `k`, bond order interpolation |
| `AngleHandler` | Harmonic angle potentials | `angle`, `k` |
| `ProperTorsionHandler` | Proper dihedral terms | `periodicity`, `phase`, `k`, `idivf` |
| `ImproperTorsionHandler` | Improper dihedral terms | `periodicity`, `phase`, `k`, `idivf` |
| `vdWHandler` | van der Waals parameters | `sigma`, `epsilon`, combining rules |
| `ElectrostaticsHandler` | Electrostatic settings | `method`, `cutoff`, scaling factors |

Sources: [docs/typing.rst:56-81](), [openff/toolkit/_tests/test_parameters.py:1183-1201]()

### Parameter Attributes and Validation

```mermaid
graph TD
    ParamType["ParameterType"] --> PA["ParameterAttribute"]
    ParamType --> IPA["IndexedParameterAttribute"]
    
    PA --> Unit["Unit validation"]
    PA --> Convert["Type conversion"]
    PA --> Default["Default values"]
    
    IPA --> Sequence["Sequence validation"]
    IPA --> Index["Indexed access (k1, k2, etc.)"]
    IPA --> Length["Length constraints"]
```

**Parameter Attribute System**

The `ParameterAttribute` and `IndexedParameterAttribute` descriptors provide automatic validation, unit checking, and type conversion for parameter values. Indexed attributes support multiple values (e.g., `k1`, `k2`, `k3` for torsions).

Sources: [openff/toolkit/_tests/test_parameters.py:52-181](), [openff/toolkit/_tests/test_parameters.py:184-267]()

### Advanced Parameter Features

#### Fractional Bond Order Interpolation

```mermaid
graph LR
    Bond["Bond"] --> FBO["Fractional bond order"]
    FBO --> Interp["Linear interpolation"]
    
    Param["Parameter"] --> K1["k_bondorder1"]
    Param --> K2["k_bondorder2"]
    
    K1 --> Interp
    K2 --> Interp
    Interp --> Final["Final parameter value"]
```

**Fractional Bond Order Parameter Interpolation**

Bond and torsion parameters can be interpolated based on fractional bond order values computed by quantum chemistry methods, allowing for more accurate representation of conjugated systems.

Sources: [openff/toolkit/_tests/test_parameters.py:269-322](), [openff/toolkit/_tests/test_forcefield.py:289-309]()

#### Charge Assignment Methods

The system supports multiple charge assignment methods:

- **Library charges**: Pre-computed charges for specific molecular fragments
- **Toolkit-based methods**: AM1-BCC, Gasteiger, etc. via external toolkits
- **Charge increment models**: Systematic charge adjustments based on chemical environment

Sources: [openff/toolkit/_tests/test_forcefield.py:1935-2023](), [openff/toolkit/_tests/test_forcefield.py:2084-2333]()

## Force Field Application Process

### Parameter Assignment Workflow

```mermaid
graph TD
    Top["Topology"] --> Mol["Extract molecules"]
    Mol --> Match["SMIRKS pattern matching"]
    Match --> Assign["Parameter assignment"]
    Assign --> Validate["Validation"]
    Validate --> System["OpenMM System"]
    
    FF["ForceField"] --> Handlers["ParameterHandlers"]
    Handlers --> Match
    
    Charges["Charge assignment"] --> System
    Assign --> Charges
```

**Force Field Application Pipeline**

The `create_openmm_system()` method orchestrates the complete parameterization process, calling each registered parameter handler to assign parameters and generate the final OpenMM System object.

Sources: [openff/toolkit/_tests/test_forcefield.py:1284-1325]()

### Parameter Lookup and Precedence

```mermaid
graph TD
    Handler["ParameterHandler"] --> List["ParameterList"]
    List --> P1["Parameter 1 (generic)"]
    List --> P2["Parameter 2 (specific)"]
    List --> P3["Parameter 3 (very specific)"]
    
    Env["Chemical environment"] --> Match1["Matches P1"]
    Env --> Match2["Matches P2"]
    Env --> Match3["Matches P3"]
    
    Match3 --> Use["Use P3 (last match wins)"]
```

**Parameter Precedence Resolution**

When multiple parameters match the same chemical environment, the last (most specific) parameter in the list is used. This allows general parameters to be overridden by more specific ones.

Sources: [openff/toolkit/_tests/test_parameters.py:826-870]()

## File Format and I/O

### OFFXML Structure

The SMIRNOFF specification is implemented through OFFXML files with a hierarchical structure:

```mermaid
graph TD
    SMIRNOFF["SMIRNOFF root"] --> Meta["Metadata (Author, Date)"]
    SMIRNOFF --> Bonds["Bonds section"]
    SMIRNOFF --> Angles["Angles section"]
    SMIRNOFF --> Torsions["ProperTorsions section"]
    SMIRNOFF --> VDW["vdW section"]
    
    Bonds --> Bond1["Bond parameter 1"]
    Bonds --> Bond2["Bond parameter 2"]
    
    Bond1 --> Attrs["smirks, length, k, id"]
```

**OFFXML File Structure**

Each section corresponds to a parameter handler, and individual parameter elements contain SMIRKS patterns and parameter values with units.

Sources: [openff/toolkit/_tests/test_forcefield.py:64-194]()

### XML Serialization and Cosmetic Attributes

```mermaid
graph LR
    FF["ForceField"] --> Serialize["to_string()/to_file()"]
    Serialize --> Keep["Keep cosmetic attributes"]
    Serialize --> Discard["Discard cosmetic attributes"]
    
    Keep --> XML1["Full XML with comments"]
    Discard --> XML2["Clean XML"]
```

**XML Serialization Options**

The force field supports round-trip serialization with optional preservation of cosmetic attributes (comments, formatting, etc.) that don't affect parameterization but aid human readability.

Sources: [openff/toolkit/_tests/test_forcefield.py:1002-1056](), [openff/toolkit/_tests/test_forcefield.py:1159-1214]()

## Advanced Features

### Plugin System

The force field system supports dynamic loading of custom parameter handler plugins, allowing extension with new parameter types without modifying core code.

```mermaid
graph TD
    FF["ForceField"] --> Core["Core handlers"]
    FF --> Plugin["Plugin handlers"]
    
    Plugin --> Load["load_handler_plugins()"]
    Load --> Custom["Custom ParameterHandler"]
    Custom --> Register["Auto-registration"]
```

**Parameter Handler Plugin Architecture**

Sources: [openff/toolkit/_tests/test_forcefield.py:1911-1925]()

### Virtual Sites

The system supports virtual sites for representing lone pairs, bond charge sites, and other off-atom charge distributions.

```mermaid
graph TD
    VH["VirtualSiteHandler"] --> BC["BondCharge"]
    VH --> ML["MonovalentLonePair"]
    VH --> DL["DivalentLonePair"]
    VH --> TL["TrivalentLonePair"]
    
    BC --> Params1["distance, charge_increment"]
    ML --> Params2["distance, inPlaneAngle, outOfPlaneAngle"]
```

**Virtual Site Types**

Sources: [openff/toolkit/_tests/test_forcefield.py:437-661]()

### Version Management and Compatibility

The system includes comprehensive version checking for both the overall SMIRNOFF specification version and individual parameter handler section versions.

```mermaid
graph TD
    Load["Load OFFXML"] --> Check["Version validation"]
    Check --> Compatible["Compatible version"]
    Check --> Error["SMIRNOFFVersionError"]
    
    Compatible --> Handlers["Handler initialization"]
    Handlers --> SectionCheck["Section version check"]
```

**Version Validation System**

Sources: [openff/toolkit/_tests/test_parameters.py:657-708](), [openff/toolkit/_tests/test_forcefield.py:842-854]()

---