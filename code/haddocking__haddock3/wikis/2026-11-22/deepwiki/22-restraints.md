# Restraints

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [CHANGELOG.md](CHANGELOG.md)
- [notebooks/HADDOCK3-antibody-antigen.ipynb](notebooks/HADDOCK3-antibody-antigen.ipynb)
- [notebooks/README.md](notebooks/README.md)
- [pyproject.toml](pyproject.toml)
- [src/haddock/clis/wrapper_haddock_restraints.py](src/haddock/clis/wrapper_haddock_restraints.py)
- [src/haddock/libs/libnotebooks.py](src/haddock/libs/libnotebooks.py)
- [src/haddock/modules/analysis/clustfcc/__init__.py](src/haddock/modules/analysis/clustfcc/__init__.py)
- [src/haddock/modules/analysis/seletop/__init__.py](src/haddock/modules/analysis/seletop/__init__.py)
- [src/haddock/modules/analysis/seletopclusts/__init__.py](src/haddock/modules/analysis/seletopclusts/__init__.py)
- [src/haddock/modules/refinement/emref/__init__.py](src/haddock/modules/refinement/emref/__init__.py)
- [src/haddock/modules/refinement/flexref/__init__.py](src/haddock/modules/refinement/flexref/__init__.py)
- [src/haddock/modules/refinement/mdref/__init__.py](src/haddock/modules/refinement/mdref/__init__.py)
- [src/haddock/modules/sampling/gdock/__init__.py](src/haddock/modules/sampling/gdock/__init__.py)
- [src/haddock/modules/sampling/lightdock/__init__.py](src/haddock/modules/sampling/lightdock/__init__.py)
- [src/haddock/modules/sampling/rigidbody/__init__.py](src/haddock/modules/sampling/rigidbody/__init__.py)
- [src/haddock/modules/scoring/emscoring/__init__.py](src/haddock/modules/scoring/emscoring/__init__.py)
- [src/haddock/modules/scoring/mdscoring/__init__.py](src/haddock/modules/scoring/mdscoring/__init__.py)
- [src/haddock/modules/topology/topoaa/__init__.py](src/haddock/modules/topology/topoaa/__init__.py)

</details>



## Purpose and Scope

This page documents the restraint system in HADDOCK3, including restraint types, file formats, and how restraints are used throughout the docking workflow. Restraints guide the docking process by encoding experimental or predicted interface information as distance constraints applied during sampling and refinement.

For information about configuring restraint parameters in workflows, see [Parameter System](#5.2). For details on how restraints are used in specific modules, see [Sampling Modules](#4.2) and [Refinement Modules](#4.3).

---

## Restraint Types

HADDOCK3 supports multiple types of restraints that encode different kinds of interface information:

| Restraint Type | Parameter Name | Description | Typical Use Case |
|----------------|----------------|-------------|------------------|
| **Ambiguous Interaction Restraints (AIRs)** | `ambig_fname` | Distance restraints between sets of interface residues with OR logic | Experimental epitope/paratope data, predictions |
| **Unambiguous Restraints** | `unambig_fname` | Explicit distance restraints between specific atom pairs | Cross-linking data, specific contacts |
| **Hydrogen Bond Restraints** | `hbond_fname` | Distance and angle restraints enforcing H-bonds | NMR NOE data, predicted H-bonds |
| **Center of Mass Restraints** | `cmrest` (boolean) | Restraints between molecular centers of mass | Ab-initio docking |
| **Random AIRs** | `ranair` (boolean) | Randomly selected surface patches as AIRs | Ab-initio docking |
| **Surface Restraints** | `surfrest` (boolean) | Restraints to solvent-accessible surface residues | Ab-initio docking |

Sources: [src/haddock/modules/sampling/rigidbody/__init__.py:174-194]()

### Restraint Type Decision Flow

```mermaid
flowchart TD
    Start["Docking Scenario"] --> HasData{"Experimental<br/>Interface Data?"}
    
    HasData -->|Yes| DataType{"Data Type?"}
    HasData -->|No| AbInitio["Ab-initio Mode"]
    
    DataType -->|"Epitope/Paratope<br/>Residues"| AIRs["Use ambig_fname<br/>Ambiguous Restraints"]
    DataType -->|"Specific<br/>Atom Pairs"| Unambig["Use unambig_fname<br/>Unambiguous Restraints"]
    DataType -->|"H-bond<br/>Information"| HBond["Use hbond_fname<br/>Hydrogen Bond Restraints"]
    
    AbInitio --> AbInitioType{"Strategy?"}
    AbInitioType -->|"Center of Mass"| CM["Set cmrest = true"]
    AbInitioType -->|"Random Surface"| RanAIR["Set ranair = true"]
    AbInitioType -->|"Surface Residues"| Surf["Set surfrest = true"]
    
    AIRs --> Apply["Applied in Sampling<br/>and Refinement"]
    Unambig --> Apply
    HBond --> Apply
    CM --> Apply
    RanAIR --> Apply
    Surf --> Apply
```

Sources: [src/haddock/modules/sampling/rigidbody/__init__.py:172-194]()

---

## CNS Restraint File Format

HADDOCK3 uses the CNS restraint format (`.tbl` files). Distance restraints follow this syntax:

```
assign (selection1) (selection2) distance, lower-bound correction, upper-bound correction
```

Where:
- **selection1/selection2**: CNS atom selection statements
- **distance**: Target distance in Angstroms
- **lower-bound correction**: Subtracted from distance to get lower limit
- **upper-bound correction**: Added to distance to get upper limit

### Selection Syntax

CNS selections combine multiple keywords:

| Keyword | Description | Example |
|---------|-------------|---------|
| `segid` | Chain/segment identifier | `segid A` |
| `resid` | Residue number | `resid 42` |
| `name` | Atom name | `name CA` |
| `resname` | Residue type | `resname ALA` |

Selections can use boolean operators: `and`, `or`, `not`

### Example: Unambiguous Restraint

```
assign (segid A and resid 10 and name CB) 
       (segid B and resid 200 and name CB) 
       20.0 10.0 0.0
```

This restraint:
- Targets CB atoms of residues A:10 and B:200
- Allowed distance range: 10.0Å to 20.0Å (20.0 - 10.0 to 20.0 + 0.0)

### Example: Ambiguous Restraint (AIR)

```
assign (
    (segid A and resid 10) or
    (segid A and resid 11) or
    (segid A and resid 12)
) (
    (segid B and resid 200) or
    (segid B and resid 201)
) 2.0 2.0 0.0
```

This AIR:
- Defines OR logic between multiple residues on each side
- Satisfied if ANY residue pair comes within range
- Distance range: 0.0Å to 4.0Å

Sources: [notebooks/HADDOCK3-antibody-antigen.ipynb:366-390]()

---

## Restraints in the Module Workflow

```mermaid
flowchart LR
    subgraph "Input"
        TBL["Restraint Files<br/>.tbl format"]
        Config["Configuration<br/>ambig_fname<br/>unambig_fname<br/>hbond_fname"]
    end
    
    subgraph "Sampling Stage"
        RB["rigidbody Module"]
        LD["lightdock Module"]
        GD["gdock Module"]
        RBCheck["restraints_guardrail()<br/>Validates presence"]
    end
    
    subgraph "Refinement Stage"
        FlexRef["flexref Module"]
        EMRef["emref Module"]
        MDRef["mdref Module"]
    end
    
    subgraph "Scoring Stage"
        EMScore["emscoring Module"]
        MDScore["mdscoring Module"]
    end
    
    subgraph "Data Flow"
        PDBFile["PDBFile Object<br/>restr_fname attribute"]
        PrepCNS["prepare_cns_input()<br/>Embeds restraints<br/>in CNS script"]
        CNSExec["CNS Execution<br/>Applies restraints<br/>during dynamics"]
    end
    
    TBL --> Config
    Config --> RB
    Config --> FlexRef
    Config --> EMRef
    Config --> MDRef
    
    RB --> RBCheck
    RBCheck --> PDBFile
    
    PDBFile --> FlexRef
    FlexRef --> PrepCNS
    PrepCNS --> CNSExec
    
    CNSExec --> EMScore
    CNSExec --> MDScore
    
    PDBFile -.->|"Carries restr_fname<br/>through pipeline"| EMScore
```

Sources: [src/haddock/modules/sampling/rigidbody/__init__.py:172-194](), [src/haddock/modules/refinement/flexref/__init__.py:87-104](), [src/haddock/modules/refinement/emref/__init__.py:74-90](), [src/haddock/modules/refinement/mdref/__init__.py:86-103]()

### Parameter Propagation

Restraints are specified at the module level in the configuration file:

```toml
[rigidbody]
ambig_fname = "restraints/ambig.tbl"
unambig_fname = "restraints/unambig.tbl"

[flexref]
ambig_fname = "restraints/ambig.tbl"
```

The `BaseCNSModule` class provides the `get_ambig_fnames()` method to retrieve restraint files from previous modules:

[src/haddock/modules/sampling/rigidbody/__init__.py:222-233]()

This allows restraints to be:
1. Specified explicitly via parameters
2. Inherited from previous module output
3. Mixed (different restraints per model when using multiple files)

Sources: [src/haddock/modules/sampling/rigidbody/__init__.py:222-233](), [src/haddock/modules/refinement/flexref/__init__.py:87-94]()

### PDBFile Restraint Tracking

The `PDBFile` class carries restraint information through the workflow:

```mermaid
classDiagram
    class PDBFile {
        +file_name: str
        +restr_fname: str
        +topology: TopologyFile
        +seed: int
        +score: float
        +unw_energies: dict
        +md5: str
    }
    
    class TopologyFile {
        +file_name: str
        +path: str
    }
    
    class Module {
        +output_models: list[PDBFile]
        +get_ambig_fnames()
        +prepare_cns_input()
    }
    
    PDBFile --> TopologyFile : "has"
    Module --> PDBFile : "produces"
    
    note for PDBFile "restr_fname attribute stores<br/>the restraint file path<br/>used for this model"
```

When creating expected output models, modules set the `restr_fname` attribute:

[src/haddock/modules/sampling/rigidbody/__init__.py:81]()
[src/haddock/modules/refinement/flexref/__init__.py:126]()

Sources: [src/haddock/modules/sampling/rigidbody/__init__.py:76-87](), [src/haddock/modules/refinement/flexref/__init__.py:124-127]()

---

## Restraint Validation

The `rigidbody` module includes a guardrail to ensure at least one restraint type is specified:

```mermaid
flowchart TD
    Start["rigidbody._run()"] --> Guard["restraints_guardrail()"]
    
    Guard --> Check{"Any restraint<br/>type present?"}
    
    Check -->|No| Error["finish_with_error()<br/>Terminate with message"]
    Check -->|Yes| Continue["Proceed with docking"]
    
    Check -.->|"Checks"| Types["ambig_fname<br/>unambig_fname<br/>hbond_fname<br/>cmrest<br/>ranair<br/>surfrest"]
    
    Error --> ErrorMsg["'No restraints found for [rigidbody] module.<br/>For targeted docking, supply CNS-valid restraints...<br/>For ab-initio docking, set cmrest or ranair...'"]
```

Implementation:

[src/haddock/modules/sampling/rigidbody/__init__.py:172-194]()

This validation prevents users from accidentally running docking without any guidance, which would produce meaningless results.

Sources: [src/haddock/modules/sampling/rigidbody/__init__.py:172-194]()

---

## The haddock3-restraints CLI

HADDOCK3 provides command-line tools for generating and manipulating restraints.

### CLI Structure

```mermaid
flowchart TD
    subgraph "Python Entry Points"
        CLI1["haddock3-restraints<br/>Python wrapper CLI"]
        CLI2["haddock-restraints<br/>Rust binary wrapper"]
    end
    
    subgraph "Rust Binary"
        Binary["haddock-restraints<br/>binary executable<br/>in haddock/bin/"]
        Subcommands["Sub-commands:<br/>- active-passive-to-ambig<br/>- passive-from-active<br/>- validate<br/>- restrain_ligand<br/>- random_removal"]
    end
    
    CLI1 --> CLI2
    CLI2 --> Binary
    Binary --> Subcommands
    
    subgraph "Installation"
        Setup["setup.py build"]
        Download["Download pre-built<br/>haddock-restraints<br/>from GitHub releases"]
        BinDir["Install to<br/>src/haddock/bin/"]
    end
    
    Setup --> Download
    Download --> BinDir
    BinDir -.->|"Package includes"| Binary
```

The `haddock3-restraints` entry point is defined in:

[pyproject.toml:96]()

The wrapper implementation:

[src/haddock/clis/wrapper_haddock_restraints.py:1-21]()

This wrapper locates the binary in the package and executes it with the provided arguments.

Sources: [pyproject.toml:96-97](), [src/haddock/clis/wrapper_haddock_restraints.py:1-21](), [CHANGELOG.md:9](), [CHANGELOG.md:19]()

### Common Use Cases

The `haddock-restraints` binary provides utilities for restraint generation:

| Sub-command | Purpose | Input | Output |
|-------------|---------|-------|--------|
| `active-passive-to-ambig` | Generate AIR file from active/passive residues | Residue lists, PDB files | `ambig.tbl` |
| `passive-from-active` | Calculate passive residues from actives | Active residues, PDB file | Passive residue list |
| `validate` | Check restraint file syntax | `.tbl` file | Validation report |
| `restrain_ligand` | Generate ligand restraints | Ligand PDB, receptor PDB | `ambig.tbl` |
| `random_removal` | Randomly remove restraints for testing | `.tbl` file, percentage | Modified `.tbl` |

Sources: [CHANGELOG.md:19](), [CHANGELOG.md:22]()

---

## Restraints in Third-Party Modules

### gdock Module

The `gdock` module parses `.tbl` files to extract restraint information:

```mermaid
flowchart LR
    TBL[".tbl file<br/>CNS format"] --> Parse["ambig2dic()<br/>Parse with regex"]
    Parse --> Dict["Dictionary<br/>{chain: [resids]}"]
    Dict --> TOML["Convert to TOML<br/>for gdock"]
    TOML --> Exec["gdock.py execution"]
    
    subgraph "Parsing Logic"
        Regex["Regex Pattern:<br/>resid\\s*(\\d*)\\s*and\\s*segid\\s*(\\w)"]
        Extract["Extract resid and segid<br/>for each match"]
    end
    
    Parse --> Regex
    Regex --> Extract
    Extract --> Dict
```

Implementation:

[src/haddock/modules/sampling/gdock/__init__.py:23-37]()

The parsed restraints are then converted to the format expected by the `gdock` executable:

[src/haddock/modules/sampling/gdock/__init__.py:99-117]()

Sources: [src/haddock/modules/sampling/gdock/__init__.py:23-37](), [src/haddock/modules/sampling/gdock/__init__.py:99-117]()

---

## Active and Passive Residues

AIRs are typically defined using the active-passive paradigm:

- **Active residues**: Directly involved in binding (experimentally determined or predicted)
- **Passive residues**: Surface-exposed neighbors of active residues (automatically calculated)

The restraint generation workflow:

```mermaid
flowchart TD
    Start["Identify Active Residues"] --> Method{"How?"}
    
    Method -->|"Experimental"| Exp["NMR Chemical Shift<br/>Mutagenesis<br/>Cross-linking"]
    Method -->|"Computational"| Comp["ProABC-2<br/>Surface Patches<br/>Conservation"]
    
    Exp --> Active["Active Residues<br/>e.g., 31,32,33,34,35"]
    Comp --> Active
    
    Active --> CalcPassive["passive-from-active<br/>haddock-restraints"]
    CalcPassive --> Passive["Passive Residues<br/>Surface neighbors<br/>of actives"]
    
    Active --> Generate["active-passive-to-ambig<br/>haddock-restraints"]
    Passive --> Generate
    
    Generate --> AIR["ambig.tbl<br/>AIR restraints file"]
    
    AIR --> Workflow["HADDOCK3 Workflow"]
```

The calculation of passive residues typically uses:
- Distance cutoff (e.g., 6.5Å from active residues)
- Solvent accessibility criteria
- Surface exposure thresholds

Sources: [notebooks/HADDOCK3-antibody-antigen.ipynb:400-420]()

---

## Integration with CNS

When modules execute CNS jobs, restraints are embedded in the CNS input script via `libcns.prepare_cns_input()`:

```mermaid
flowchart TD
    subgraph "Input"
        Model["PDBFile Object"]
        Restraints["Restraint Files<br/>ambig_fname<br/>unambig_fname<br/>hbond_fname"]
        Recipe["CNS Recipe<br/>rigidbody.cns<br/>flexref.cns<br/>etc."]
        Params["Module Parameters"]
    end
    
    subgraph "prepare_cns_input()"
        Header["generate_default_header()<br/>Link files, topology paths"]
        LoadParams["load_workflow_params()<br/>Format parameters"]
        PrepInput["prepare_single_input()<br/>or prepare_multiple_input()"]
        PrepRestr["Format restraint file paths<br/>for CNS inline statement"]
    end
    
    subgraph "CNS Input Structure"
        ParamSec["Parameter Section<br/>Set CNS variables"]
        InputSec["Input Section<br/>structure @file.pdb"]
        RestrSec["Restraint Section<br/>noe @@restraints.tbl end"]
        ScriptSec["Recipe Section<br/>Minimization/MD protocol"]
    end
    
    Model --> PrepInput
    Restraints --> PrepRestr
    Recipe --> ScriptSec
    Params --> LoadParams
    
    Header --> ParamSec
    LoadParams --> ParamSec
    PrepInput --> InputSec
    PrepRestr --> RestrSec
    
    ParamSec --> CNSScript[".inp file"]
    InputSec --> CNSScript
    RestrSec --> CNSScript
    ScriptSec --> CNSScript
    
    CNSScript --> CNSJob["CNSJob object"]
    CNSJob --> Execute["CNS Execution"]
```

The restraint file paths are passed to CNS using inline file inclusion:

```
noe
  @@ambig.tbl
end
```

CNS then parses the `.tbl` file during execution and applies the distance restraints to the energy function.

Sources: [src/haddock/modules/sampling/rigidbody/__init__.py:106-120](), [src/haddock/modules/refinement/flexref/__init__.py:108-119]()

---

## Best Practices

### Restraint File Organization

Recommended directory structure:

```
run_directory/
├── pdbs/
│   ├── molecule_A.pdb
│   └── molecule_B.pdb
├── restraints/
│   ├── ambig.tbl
│   ├── unambig.tbl
│   └── hbond.tbl
└── workflow.cfg
```

### Parameter Configuration

For targeted docking with experimental data:

```toml
[rigidbody]
ambig_fname = "restraints/ambig.tbl"
unambig_fname = "restraints/unambig.tbl"
sampling = 1000

[flexref]
ambig_fname = "restraints/ambig.tbl"
```

For ab-initio docking:

```toml
[rigidbody]
cmrest = true
sampling = 10000

[flexref]
ambig_fname = false  # No restraints in refinement
```

### Restraint Validation

Always validate restraint files before running workflows:

```bash
haddock-restraints validate restraints/ambig.tbl
```

Sources: [notebooks/HADDOCK3-antibody-antigen.ipynb:360-394]()

---

## Troubleshooting

### Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| "No restraints found for [rigidbody] module" | No restraint parameters specified | Set `ambig_fname` or enable `cmrest`/`ranair` |
| CNS parsing error in `.tbl` file | Invalid selection syntax | Check CNS selection keywords and boolean operators |
| "restr_fname not found" | Missing restraint file | Verify file path in configuration |
| Restraint not applied | Atom selection doesn't match structure | Check segid/chain IDs and residue numbering |

### Debugging Restraint Application

To verify restraints are being used:

1. Enable debug mode: `debug = true` in module configuration
2. Check generated `.inp` files for restraint sections
3. Examine CNS output (`.out` files) for "NOE restraints" section
4. Verify violation statistics in output

Sources: [src/haddock/modules/sampling/rigidbody/__init__.py:172-194]()

---