# Charge Generation

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [openfe/protocols/openmm_utils/charge_generation.py](openfe/protocols/openmm_utils/charge_generation.py)
- [openfe/tests/conftest.py](openfe/tests/conftest.py)
- [openfe/tests/protocols/openmm_ahfe/test_ahfe_protocol.py](openfe/tests/protocols/openmm_ahfe/test_ahfe_protocol.py)
- [openfe/tests/protocols/openmm_md/test_plain_md_protocol.py](openfe/tests/protocols/openmm_md/test_plain_md_protocol.py)
- [openfe/tests/protocols/openmm_rfe/test_hybrid_top_protocol.py](openfe/tests/protocols/openmm_rfe/test_hybrid_top_protocol.py)
- [openfe/tests/protocols/test_openmm_settings.py](openfe/tests/protocols/test_openmm_settings.py)
- [openfe/tests/protocols/test_openmmutils.py](openfe/tests/protocols/test_openmmutils.py)
- [openfecli/commands/generate_partial_charges.py](openfecli/commands/generate_partial_charges.py)
- [openfecli/commands/plan_rbfe_network.py](openfecli/commands/plan_rbfe_network.py)
- [openfecli/commands/plan_rhfe_network.py](openfecli/commands/plan_rhfe_network.py)
- [openfecli/parameters/__init__.py](openfecli/parameters/__init__.py)
- [openfecli/parameters/misc.py](openfecli/parameters/misc.py)
- [openfecli/parameters/plan_network_options.py](openfecli/parameters/plan_network_options.py)
- [openfecli/plan_alchemical_networks_utils.py](openfecli/plan_alchemical_networks_utils.py)
- [openfecli/tests/commands/test_plan_rbfe_network.py](openfecli/tests/commands/test_plan_rbfe_network.py)
- [openfecli/tests/commands/test_plan_rhfe_network.py](openfecli/tests/commands/test_plan_rhfe_network.py)

</details>



## Purpose and Scope

This page documents the partial charge generation system in OpenFE, which assigns atomic partial charges to small molecules prior to simulation. Partial charges are essential for non-bonded electrostatic interactions in molecular dynamics and free energy calculations. The system supports multiple charge assignment methods (AM1-BCC, NAGL, Espaloma) and toolkit backends (AmberTools, OpenEye, RDKit), with automatic conformer generation and parallel processing capabilities.

For information about force field settings and system parameterization, see [Protocol Settings and Configuration](#2.5). For network planning workflows that utilize charge generation, see [Alchemical Network Planning](#3.3).

---

## System Architecture

```mermaid
graph TB
    subgraph "User Interface"
        CLI["CLI: charge-molecules<br/>openfecli.commands.generate_partial_charges"]
        PythonAPI["Python API:<br/>bulk_assign_partial_charges()<br/>assign_offmol_partial_charges()"]
        NetworkPlanners["Network Planning Commands:<br/>plan-rbfe-network<br/>plan-rhfe-network"]
    end
    
    subgraph "Core Charge Generation"
        BulkAssign["bulk_assign_partial_charges()<br/>openfe/protocols/openmm_utils/charge_generation.py:434-521"]
        AssignOffmol["assign_offmol_partial_charges()<br/>openfe/protocols/openmm_utils/charge_generation.py:285-431"]
        ConfGen["_generate_offmol_conformers()<br/>openfe/protocols/openmm_utils/charge_generation.py:206-282"]
    end
    
    subgraph "Charge Methods"
        AM1BCC["assign_offmol_am1bcc_charges()<br/>am1bcc / am1bccelf10"]
        NAGL["assign_offmol_nagl_charges()<br/>nagl method"]
        Espaloma["assign_offmol_espaloma_charges()<br/>espaloma method"]
    end
    
    subgraph "Toolkit Backends"
        AmberTools["AmberTools + RDKit<br/>BACKEND_OPTIONS['ambertools']"]
        OpenEye["OpenEye Toolkit<br/>BACKEND_OPTIONS['openeye']"]
        RDKit["RDKit Only<br/>BACKEND_OPTIONS['rdkit']"]
    end
    
    subgraph "Configuration"
        YAMLSettings["YAML Settings File<br/>partial_charge section"]
        OpenFFPartialChargeSettings["OpenFFPartialChargeSettings<br/>omm_settings.py"]
    end
    
    CLI --> BulkAssign
    PythonAPI --> BulkAssign
    NetworkPlanners --> BulkAssign
    
    BulkAssign --> AssignOffmol
    AssignOffmol --> ConfGen
    AssignOffmol --> AM1BCC
    AssignOffmol --> NAGL
    AssignOffmol --> Espaloma
    
    AM1BCC --> AmberTools
    AM1BCC --> OpenEye
    NAGL --> AmberTools
    NAGL --> OpenEye
    NAGL --> RDKit
    Espaloma --> RDKit
    Espaloma --> AmberTools
    
    YAMLSettings --> OpenFFPartialChargeSettings
    OpenFFPartialChargeSettings --> BulkAssign
    
    style BulkAssign fill:#f9f9f9
    style AssignOffmol fill:#f9f9f9
```

**System Overview**: The charge generation system provides a unified interface for assigning partial charges to molecules using different methods and backends. The workflow flows from user input (CLI or Python API) through the core assignment logic, which delegates to specific charge methods based on configuration. Each method uses one or more toolkit backends for the actual computation.

**Sources**: [openfe/protocols/openmm_utils/charge_generation.py:1-522](), [openfecli/commands/generate_partial_charges.py:1-97](), [openfecli/commands/plan_rbfe_network.py:74-90]()

---

## Charge Assignment Methods

OpenFE supports four partial charge assignment methods, each with different computational requirements and accuracy profiles:

| Method | Description | Max Conformers | Required Backend(s) | Notes |
|--------|-------------|----------------|---------------------|-------|
| `am1bcc` | AM1-BCC semi-empirical charges | 1 | ambertools, openeye | Default method, good balance of speed/accuracy |
| `am1bccelf10` | AM1-BCC with ELF10 conformer ensemble | unlimited | openeye only | Requires OpenEye license, uses multiple conformers |
| `nagl` | Graph neural network charges | 1 | ambertools, openeye, rdkit | Requires openff-nagl package |
| `espaloma` | Machine learning charges | 1 | rdkit, ambertools | Requires espaloma_charge package, experimental |

**Method Selection Logic**:

```mermaid
graph TB
    Start["Input: method, toolkit_backend"]
    ValidateMethod{"method in<br/>CHARGE_METHODS?"}
    ValidateBackend{"toolkit_backend<br/>compatible?"}
    CheckDeps{"Dependencies<br/>available?"}
    BuildRegistry["Build ToolkitRegistry<br/>from BACKEND_OPTIONS"]
    GenerateConf["_generate_offmol_conformers()"]
    AssignCharges["Call method-specific<br/>charge assignment"]
    CopyCharges["Copy charges to<br/>input molecule"]
    End["Return charged molecule"]
    
    Error1["ValueError:<br/>Unknown method"]
    Error2["ValueError:<br/>Incompatible backend"]
    Error3["ImportError:<br/>Missing dependency"]
    
    Start --> ValidateMethod
    ValidateMethod -->|No| Error1
    ValidateMethod -->|Yes| ValidateBackend
    ValidateBackend -->|No| Error2
    ValidateBackend -->|Yes| CheckDeps
    CheckDeps -->|No| Error3
    CheckDeps -->|Yes| BuildRegistry
    BuildRegistry --> GenerateConf
    GenerateConf --> AssignCharges
    AssignCharges --> CopyCharges
    CopyCharges --> End
```

**Sources**: [openfe/protocols/openmm_utils/charge_generation.py:353-382](), [openfe/protocols/openmm_utils/charge_generation.py:285-334]()

---

## Toolkit Backend Selection

The system uses the OpenFF Toolkit's wrapper architecture to support multiple cheminformatics toolkits:

```mermaid
graph LR
    subgraph "BACKEND_OPTIONS Dictionary"
        BEDict["charge_generation.py:66-70"]
    end
    
    subgraph "Backend: ambertools"
        AT_RDKit["RDKitToolkitWrapper"]
        AT_Amber["AmberToolsToolkitWrapper"]
    end
    
    subgraph "Backend: openeye"
        OE["OpenEyeToolkitWrapper"]
    end
    
    subgraph "Backend: rdkit"
        RD["RDKitToolkitWrapper"]
    end
    
    BEDict --> AT_RDKit
    BEDict --> AT_Amber
    BEDict --> OE
    BEDict --> RD
    
    AT_RDKit --> Registry1["ToolkitRegistry<br/>[RDKit, AmberTools]"]
    AT_Amber --> Registry1
    OE --> Registry2["ToolkitRegistry<br/>[OpenEye]"]
    RD --> Registry3["ToolkitRegistry<br/>[RDKit]"]
    
    Registry1 --> Methods1["am1bcc<br/>nagl<br/>espaloma"]
    Registry2 --> Methods2["am1bcc<br/>am1bccelf10<br/>nagl"]
    Registry3 --> Methods3["nagl<br/>espaloma"]
```

**Backend Compatibility Matrix**:

The `BACKEND_OPTIONS` dictionary ([charge_generation.py:66-70]()) defines which toolkit wrappers are instantiated for each backend choice. The compatibility is enforced at runtime by checking the method's allowed backends against the selected backend ([charge_generation.py:392-398]()).

**Special Considerations**:
- **OpenEye**: Requires a commercial license. Availability checked via `HAS_OPENEYE` flag ([charge_generation.py:24-29]())
- **AmberTools**: Provides AM1-BCC through sqm; thread limits applied to avoid concurrency issues ([charge_generation.py:420-421]())
- **RDKit**: Cannot compute AM1-BCC charges directly, only used for conformer generation with other methods

**Sources**: [openfe/protocols/openmm_utils/charge_generation.py:66-70](), [openfe/protocols/openmm_utils/charge_generation.py:392-403](), [openfe/protocols/openmm_utils/charge_generation.py:24-59]()

---

## Conformer Generation Workflow

Charge methods require molecular conformers. The system handles conformer generation automatically:

```mermaid
graph TB
    Input["Input: offmol, max_conf,<br/>generate_n_conformers, toolkit_registry"]
    
    CheckGenerate{"generate_n_conformers<br/>is None?"}
    CheckExisting{"offmol.n_conformers<br/>== 0?"}
    CheckTooMany{"offmol.n_conformers<br/>> max_conf?"}
    
    CheckRequested{"generate_n_conformers<br/>> max_conf?"}
    
    CheckCarboxy{"OpenEyeToolkitWrapper<br/>in registry?"}
    
    Generate["offmol.generate_conformers()<br/>n_conformers=generate_n_conformers<br/>rms_cutoff=0.25 Å"]
    GenerateCis["offmol.generate_conformers()<br/>make_carboxylic_acids_cis=True"]
    
    Return["Return (use existing conformers)"]
    
    Error1["ValueError:<br/>No conformers"]
    Error2["ValueError:<br/>Too many conformers"]
    Error3["ValueError:<br/>Too many requested"]
    
    Input --> CheckGenerate
    
    CheckGenerate -->|Yes| CheckExisting
    CheckGenerate -->|No| CheckRequested
    
    CheckExisting -->|Yes| Error1
    CheckExisting -->|No| CheckTooMany
    
    CheckTooMany -->|Yes| Error2
    CheckTooMany -->|No| Return
    
    CheckRequested -->|Yes| Error3
    CheckRequested -->|No| CheckCarboxy
    
    CheckCarboxy -->|Yes| GenerateCis
    CheckCarboxy -->|No| Generate
    
    Generate --> Return
    GenerateCis --> Return
```

**Implementation Details**:

The `_generate_offmol_conformers()` function ([charge_generation.py:206-282]()) handles several cases:

1. **No generation requested** (`generate_n_conformers=None`): Validates existing conformers
2. **Generation requested**: Creates new conformers with RMS cutoff of 0.25 Å
3. **OpenEye backend**: Sets `make_carboxylic_acids_cis=True` for correct AM1-BCC geometry

**Maximum Conformer Limits**:
- `am1bcc`: 1 conformer
- `am1bccelf10`: unlimited (`sys.maxsize`)
- `nagl`: 1 conformer
- `espaloma`: 1 conformer (actually requires 0, handled specially)

**Sources**: [openfe/protocols/openmm_utils/charge_generation.py:206-282](), [openfe/protocols/openmm_utils/charge_generation.py:353-382]()

---

## Method-Specific Implementation

### AM1-BCC Charges

```mermaid
graph TB
    Start["assign_offmol_am1bcc_charges()"]
    CheckConf{"offmol.n_conformers<br/>== 0?"}
    Registry["toolkit_registry_manager<br/>context"]
    Assign["offmol.assign_partial_charges()<br/>method=am1bcc or am1bccelf10<br/>use_conformers=offmol.conformers"]
    End["Charges assigned to offmol"]
    
    Error["ValueError:<br/>No conformers"]
    
    Start --> CheckConf
    CheckConf -->|Yes| Error
    CheckConf -->|No| Registry
    Registry --> Assign
    Assign --> End
```

**Function**: `assign_offmol_am1bcc_charges()` ([charge_generation.py:163-203]())

**Parameters**:
- `partial_charge_method`: Either `"am1bcc"` or `"am1bccelf10"`
- `toolkit_registry`: ToolkitRegistry with appropriate backend(s)

**Behavior**:
- Requires at least one conformer on the input molecule
- Uses `toolkit_registry_manager` context to strictly control available toolkits
- For `am1bccelf10`, uses ensemble of conformers if multiple provided

**Sources**: [openfe/protocols/openmm_utils/charge_generation.py:163-203]()

### NAGL Charges

```mermaid
graph TB
    Start["assign_offmol_nagl_charges()"]
    CheckInstall{"HAS_NAGL?"}
    CheckModel{"nagl_model<br/>is None?"}
    GetModels["get_models_by_type()<br/>model_type='am1bcc'<br/>production_only=True"]
    CheckFound{"Models<br/>found?"}
    SelectLatest["Select latest model<br/>prod_models[-1]"]
    ValidatePath["validate_nagl_model_path()"]
    Registry["toolkit_registry_manager<br/>context"]
    Assign["offmol.assign_partial_charges()<br/>method=model_path<br/>toolkit=NAGLToolkitWrapper"]
    End["Charges assigned"]
    
    Error1["ImportError:<br/>NAGL not available"]
    Error2["ValueError:<br/>No production models"]
    
    Start --> CheckInstall
    CheckInstall -->|No| Error1
    CheckInstall -->|Yes| CheckModel
    CheckModel -->|Yes| GetModels
    CheckModel -->|No| ValidatePath
    GetModels --> CheckFound
    CheckFound -->|No| Error2
    CheckFound -->|Yes| SelectLatest
    SelectLatest --> ValidatePath
    ValidatePath --> Registry
    Registry --> Assign
    Assign --> End
```

**Function**: `assign_offmol_nagl_charges()` ([charge_generation.py:111-160]())

**Parameters**:
- `nagl_model`: Optional path to NAGL model; if `None`, fetches latest production am1bcc model
- `toolkit_registry`: ToolkitRegistry (backend doesn't matter for NAGL)

**Model Selection**:
- Automatic: Uses `get_models_by_type()` from openff-nagl-models package
- Manual: User can specify model path via `nagl_model` parameter

**Sources**: [openfe/protocols/openmm_utils/charge_generation.py:111-160](), [openfe/protocols/openmm_utils/charge_generation.py:42-51]()

### Espaloma Charges

```mermaid
graph TB
    Start["assign_offmol_espaloma_charges()"]
    CheckInstall{"HAS_ESPALOMA_CHARGE?"}
    Warn["RuntimeWarning:<br/>Not well tested"]
    Copy["Deep copy offmol"]
    ClearConf["offmol_copy._conformers = None"]
    Registry["toolkit_registry_manager<br/>context"]
    Assign["offmol_copy.assign_partial_charges()<br/>method='espaloma-am1bcc'<br/>toolkit=EspalomaChargeToolkitWrapper"]
    CopyBack["offmol.partial_charges =<br/>offmol_copy.partial_charges"]
    End["Charges assigned"]
    
    Error["ImportError:<br/>Espaloma not available"]
    
    Start --> CheckInstall
    CheckInstall -->|No| Error
    CheckInstall -->|Yes| Warn
    Warn --> Copy
    Copy --> ClearConf
    ClearConf --> Registry
    Registry --> Assign
    Assign --> CopyBack
    CopyBack --> End
```

**Function**: `assign_offmol_espaloma_charges()` ([charge_generation.py:73-108]())

**Special Handling**:
- Espaloma requires **zero** conformers, enforced by deep copying and clearing
- Issues a `RuntimeWarning` that method is not well tested
- Uses `EspalomaChargeToolkitWrapper` from espaloma_charge package

**Sources**: [openfe/protocols/openmm_utils/charge_generation.py:73-108](), [openfe/protocols/openmm_utils/charge_generation.py:54-59]()

---

## Bulk Charge Assignment

For efficiency when charging multiple molecules (common in network planning), the system provides parallel processing:

```mermaid
graph TB
    Input["bulk_assign_partial_charges()<br/>molecules, method, backend, processors"]
    
    CheckProc{"processors > 1?"}
    
    subgraph "Single Process"
        Loop1["for mol in molecules"]
        Assign1["assign_offmol_partial_charges()"]
        Progress1["tqdm progress bar"]
        Convert1["SmallMoleculeComponent.from_openff()"]
    end
    
    subgraph "Multiprocess"
        Pool["ProcessPoolExecutor<br/>max_workers=processors"]
        Submit["Submit charge jobs<br/>for each molecule"]
        Progress2["tqdm progress bar<br/>as_completed()"]
        Convert2["SmallMoleculeComponent.from_openff()"]
    end
    
    Output["Return list of<br/>charged SmallMoleculeComponents"]
    
    Input --> CheckProc
    CheckProc -->|No| Loop1
    CheckProc -->|Yes| Pool
    
    Loop1 --> Assign1
    Assign1 --> Progress1
    Progress1 --> Convert1
    Convert1 --> Output
    
    Pool --> Submit
    Submit --> Progress2
    Progress2 --> Convert2
    Convert2 --> Output
```

**Function**: `bulk_assign_partial_charges()` ([charge_generation.py:434-521]())

**Parallel Processing**:
- Uses `ProcessPoolExecutor` when `processors > 1`
- Each molecule charged in separate process to avoid GIL contention
- Progress tracked via `tqdm` with total molecule count

**Overwrite Behavior**:
- If `overwrite=False`: Skips molecules that already have non-zero partial charges
- If `overwrite=True`: Regenerates charges for all molecules
- Zero charges are always overwritten regardless of setting

**Sources**: [openfe/protocols/openmm_utils/charge_generation.py:434-521](), [openfe/protocols/openmm_utils/charge_generation.py:335-340]()

---

## Command Line Interface

### charge-molecules Command

```mermaid
graph TB
    CLI["openfecli charge-molecules"]
    
    ParseInput["Parse input molecules<br/>MOL_DIR.get()"]
    ParseSettings["Parse YAML settings<br/>YAML_OPTIONS.get()"]
    ExtractCharge["Extract partial_charge section"]
    
    CallBulk["bulk_assign_partial_charges()<br/>with settings"]
    
    WriteOutput["Write to SDF file<br/>mol.to_sdf() for each"]
    
    CLI --> ParseInput
    CLI --> ParseSettings
    ParseSettings --> ExtractCharge
    ParseInput --> CallBulk
    ExtractCharge --> CallBulk
    CallBulk --> WriteOutput
```

**Command**: `charge-molecules` ([openfecli/commands/generate_partial_charges.py:30-95]())

**Usage**:
```bash
openfecli charge-molecules -M molecules/*.sdf -o charged.sdf -s settings.yaml -n 4
```

**Arguments**:
- `-M, --molecules`: Input SDF files containing molecules to charge
- `-o, --output`: Output SDF file path
- `-s, --settings`: YAML file with partial charge configuration
- `-n, --n-cores`: Number of parallel processes (default: 1)
- `--overwrite-charges`: Flag to overwrite existing charges

**Sources**: [openfecli/commands/generate_partial_charges.py:30-95]()

### Integration with Network Planning

Network planning commands automatically charge molecules before building networks:

```mermaid
graph TB
    PlanCmd["plan-rbfe-network or<br/>plan-rhfe-network"]
    
    ParseMols["Parse ligands and cofactors"]
    ParseSettings["Parse YAML settings"]
    
    ChargeLigs["bulk_assign_partial_charges()<br/>for ligands"]
    ChargeCof["bulk_assign_partial_charges()<br/>for cofactors (if present)"]
    
    NetworkPlan["RBFEAlchemicalNetworkPlanner() or<br/>RHFEAlchemicalNetworkPlanner()"]
    
    Output["Write alchemicalNetwork.json<br/>and transformation files"]
    
    PlanCmd --> ParseMols
    PlanCmd --> ParseSettings
    ParseMols --> ChargeLigs
    ParseSettings --> ChargeLigs
    ChargeLigs --> ChargeCof
    ChargeCof --> NetworkPlan
    NetworkPlan --> Output
```

**Automatic Charging**: Network planning commands invoke `bulk_assign_partial_charges()` before constructing the network to ensure consistent charges across all transformations.

**Location**: 
- RBFE: [openfecli/commands/plan_rbfe_network.py:74-103]()
- RHFE: [openfecli/commands/plan_rhfe_network.py:74-84]()

**Sources**: [openfecli/commands/plan_rbfe_network.py:74-103](), [openfecli/commands/plan_rhfe_network.py:74-84]()

---

## Configuration via YAML

Charge generation settings are specified in the `partial_charge` section of YAML configuration files:

**Example Configuration**:
```yaml
partial_charge:
  method: nagl
  settings:
    nagl_model: openff-gnn-am1bcc-0.1.0-rc.3.pt
    off_toolkit_backend: rdkit
    number_of_conformers: null
```

**Settings Structure**:

| Field | Type | Description | Default |
|-------|------|-------------|---------|
| `method` | str | Charge method: am1bcc, am1bccelf10, nagl, espaloma | am1bcc |
| `settings.off_toolkit_backend` | str | Backend: ambertools, openeye, rdkit | ambertools |
| `settings.number_of_conformers` | int or null | Number of conformers to generate | null |
| `settings.nagl_model` | str or null | NAGL model path (for nagl method) | null |

**Parser Implementation**:

```mermaid
graph TB
    YAMLFile["YAML File"]
    Parse["parse_yaml_planner_options()<br/>plan_network_options.py:55-85"]
    Validate["CliYaml Pydantic model<br/>plan_network_options.py:47-53"]
    Load["load_yaml_planner_options()<br/>plan_network_options.py:88-201"]
    Create["OpenFFPartialChargeSettings<br/>omm_settings.py"]
    Apply["Apply settings to<br/>bulk_assign_partial_charges()"]
    
    YAMLFile --> Parse
    Parse --> Validate
    Validate --> Load
    Load --> Create
    Create --> Apply
```

**Settings Class**: `OpenFFPartialChargeSettings` is a Pydantic model in [openfe/protocols/openmm_utils/omm_settings.py]() that defines:
- `partial_charge_method`: Method name
- `off_toolkit_backend`: Toolkit backend name
- `number_of_conformers`: Conformer count or None
- `nagl_model`: NAGL model specification

**Sources**: [openfecli/parameters/plan_network_options.py:40-53](), [openfecli/parameters/plan_network_options.py:182-190]()

---

## Error Handling and Validation

The charge generation system implements several validation checks:

**Validation Flow**:

| Check | Location | Error Type | Message |
|-------|----------|------------|---------|
| Unknown method | [charge_generation.py:385-389]() | ValueError | "Unknown partial charge method {method}" |
| Incompatible backend | [charge_generation.py:392-398]() | ValueError | "Selected toolkit_backend ({backend}) cannot be used with ({method})" |
| OpenEye not available | [charge_generation.py:401-403]() | ImportError | "OpenEye is not available" |
| NAGL not installed | [charge_generation.py:132-138]() | ImportError | "NAGL toolkit is not available" |
| Espaloma not installed | [charge_generation.py:87-89]() | ImportError | "Espaloma ToolkitWrapper is not available" |
| No conformers | [charge_generation.py:238-245]() | ValueError | "No conformers are associated with input" |
| Too many conformers | [charge_generation.py:246-253]() | ValueError | "OpenFF Molecule has too many conformers" |
| Requested > max | [charge_generation.py:257-263]() | ValueError | "{n} conformers were requested but method supports {max}" |

**Dependency Detection**:

```mermaid
graph LR
    subgraph "Module Imports"
        CheckOE["try: import openeye"]
        CheckNAGL["try: import openff.toolkit.utils.nagl_wrapper"]
        CheckEsp["try: import espaloma_charge"]
    end
    
    subgraph "Global Flags"
        HAS_OPENEYE["HAS_OPENEYE<br/>charge_generation.py:24-29"]
        HAS_NAGL["HAS_NAGL<br/>charge_generation.py:42-51"]
        HAS_ESPALOMA_CHARGE["HAS_ESPALOMA_CHARGE<br/>charge_generation.py:54-59"]
    end
    
    CheckOE --> HAS_OPENEYE
    CheckNAGL --> HAS_NAGL
    CheckEsp --> HAS_ESPALOMA_CHARGE
```

**Sources**: [openfe/protocols/openmm_utils/charge_generation.py:24-59](), [openfe/protocols/openmm_utils/charge_generation.py:385-403](), [openfe/protocols/openmm_utils/charge_generation.py:236-263]()

---

## Testing and Validation

The test suite validates charge generation across multiple dimensions:

**Test Coverage**:

```mermaid
graph TB
    subgraph "Unit Tests"
        TestMethod["test_am1bcc_reference<br/>test_openmmutils.py:936-963"]
        TestBackend["test_incompatible_backend_am1bcc<br/>test_openmmutils.py:729-738"]
        TestConf["test_am1bcc_conformer_nochange<br/>test_openmmutils.py:791-827"]
        TestOverwrite["test_offmol_chg_gen_charged_overwrite<br/>test_openmmutils.py:693-707"]
    end
    
    subgraph "Integration Tests"
        TestCLI["test_plan_rbfe_network<br/>test_plan_rbfe_network.py:141-189"]
        TestBulk["test_plan_rbfe_network_main<br/>test_plan_rbfe_network.py:75-127"]
        TestCLICharge["test_plan_rbfe_network_charge_overwrite<br/>test_plan_rbfe_network.py:222-258"]
    end
    
    subgraph "Reference Data"
        RefCharges["am1bcc_ref_charges fixture<br/>conftest.py:340-359"]
    end
    
    TestMethod --> RefCharges
    TestBulk --> RefCharges
```

**Reference Charges**: The test suite includes reference partial charges for a CN molecule computed with different methods ([conftest.py:340-359]()):
- AmberTools: Used as baseline reference
- OpenEye: Validated against AmberTools (small differences expected)
- NAGL: Validates neural network predictions
- Espaloma: Validates ML-based charges

**Platform-Specific Skipping**: Tests are conditionally skipped based on:
- `HAS_OPENEYE`: OpenEye-dependent tests
- `HAS_NAGL`: NAGL-dependent tests  
- `HAS_ESPALOMA_CHARGE`: Espaloma-dependent tests
- `sys.platform.startswith("darwin")`: macOS-specific issues with NAGL

**Sources**: [openfe/tests/protocols/test_openmmutils.py:687-1014](), [openfe/tests/conftest.py:340-359](), [openfecli/tests/commands/test_plan_rbfe_network.py:75-258]()

---