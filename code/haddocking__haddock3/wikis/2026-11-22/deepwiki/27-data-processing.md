# Data Processing

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/haddock/core/cns_paths.py](src/haddock/core/cns_paths.py)
- [src/haddock/core/supported_molecules.py](src/haddock/core/supported_molecules.py)
- [src/haddock/gear/preprocessing.py](src/haddock/gear/preprocessing.py)
- [src/haddock/libs/libcns.py](src/haddock/libs/libcns.py)
- [src/haddock/libs/libfunc.py](src/haddock/libs/libfunc.py)
- [src/haddock/libs/libontology.py](src/haddock/libs/libontology.py)
- [src/haddock/libs/libpdb.py](src/haddock/libs/libpdb.py)
- [src/haddock/modules/analysis/clustfcc/__init__.py](src/haddock/modules/analysis/clustfcc/__init__.py)
- [src/haddock/modules/analysis/seletop/__init__.py](src/haddock/modules/analysis/seletop/__init__.py)
- [src/haddock/modules/analysis/seletopclusts/__init__.py](src/haddock/modules/analysis/seletopclusts/__init__.py)
- [src/haddock/modules/base_cns_module.py](src/haddock/modules/base_cns_module.py)
- [src/haddock/modules/refinement/emref/__init__.py](src/haddock/modules/refinement/emref/__init__.py)
- [src/haddock/modules/refinement/flexref/__init__.py](src/haddock/modules/refinement/flexref/__init__.py)
- [src/haddock/modules/refinement/mdref/__init__.py](src/haddock/modules/refinement/mdref/__init__.py)
- [src/haddock/modules/sampling/gdock/__init__.py](src/haddock/modules/sampling/gdock/__init__.py)
- [src/haddock/modules/sampling/lightdock/__init__.py](src/haddock/modules/sampling/lightdock/__init__.py)
- [src/haddock/modules/sampling/rigidbody/__init__.py](src/haddock/modules/sampling/rigidbody/__init__.py)
- [src/haddock/modules/scoring/emscoring/__init__.py](src/haddock/modules/scoring/emscoring/__init__.py)
- [src/haddock/modules/scoring/mdscoring/__init__.py](src/haddock/modules/scoring/mdscoring/__init__.py)
- [src/haddock/modules/topology/topoaa/__init__.py](src/haddock/modules/topology/topoaa/__init__.py)
- [tests/data/broken.pdb](tests/data/broken.pdb)
- [tests/data/corrected.pdb](tests/data/corrected.pdb)
- [tests/data/residues.top](tests/data/residues.top)
- [tests/test_cns_paths.py](tests/test_cns_paths.py)
- [tests/test_core_supported_molecules.py](tests/test_core_supported_molecules.py)
- [tests/test_gear_preprocessing.py](tests/test_gear_preprocessing.py)

</details>



This page explains how HADDOCK3 processes and prepares molecular structures for computation. Data processing in HADDOCK3 encompasses the transformation of raw PDB files into CNS-compatible structures, the generation of topology files, and the progressive enrichment of structural metadata as models flow through the workflow pipeline.

For detailed information about specific processing stages, see:
- PDB preprocessing operations: [PDB Preprocessing](#7.1)
- CNS script generation and execution: [CNS Integration](#7.2)
- Supported molecule definitions: [Supported Molecules](#7.3)

## Data Processing Architecture

The data processing system in HADDOCK3 operates at multiple stages of the workflow, transforming molecular structures from user inputs to fully annotated output models.

```mermaid
graph TB
    subgraph "Input Stage"
        RawPDB["Raw PDB Files<br/>(user-provided)"]
        ConfigTOML["Configuration TOML"]
        Restraints["Restraint Files<br/>(.tbl format)"]
    end
    
    subgraph "Preprocessing Layer"
        ProcessPDBs["process_pdbs()<br/>gear/preprocessing.py"]
        Sanitize["sanitize()<br/>libs/libpdb.py"]
        ValidateRes["validate residues<br/>supported_molecules.py"]
    end
    
    subgraph "Topology Generation"
        GenTopo["generate_topology()<br/>modules/topology/topoaa"]
        PrepCNSInput["prepare_cns_input()<br/>libs/libcns.py"]
        CNSExec["CNS Execution<br/>(generate PSF)"]
    end
    
    subgraph "Module Execution"
        ModuleIO["ModuleIO.retrieve_models()"]
        PrepInput["prepare_cns_input()<br/>(per module)"]
        ExecuteJobs["Execute CNS/Analysis Jobs"]
        UpdatePDB["Update PDBFile metadata<br/>(scores, clusters, etc)"]
    end
    
    subgraph "Output Stage"
        ExportIO["ModuleIO.save()<br/>(io.json)"]
        TSVFiles["TSV result files"]
        FinalPDB["Final PDB structures"]
    end
    
    RawPDB --> ProcessPDBs
    ProcessPDBs --> Sanitize
    Sanitize --> ValidateRes
    ValidateRes --> GenTopo
    ConfigTOML --> PrepCNSInput
    Restraints --> PrepCNSInput
    GenTopo --> PrepCNSInput
    PrepCNSInput --> CNSExec
    
    CNSExec --> ModuleIO
    ModuleIO --> PrepInput
    PrepInput --> ExecuteJobs
    ExecuteJobs --> UpdatePDB
    
    UpdatePDB --> ExportIO
    UpdatePDB --> TSVFiles
    UpdatePDB --> FinalPDB
```

**Sources:** [src/haddock/gear/preprocessing.py:326-437](), [src/haddock/libs/libcns.py:321-424](), [src/haddock/libs/libontology.py:121-240](), [src/haddock/modules/topology/topoaa/__init__.py:54-100]()

## Three-Stage Preprocessing Pipeline

HADDOCK3 implements a three-stage preprocessing pipeline that ensures PDB file compatibility. This processing occurs automatically when reading input molecules unless `skip_preprocess = True` is set in the configuration.

### Processing Stages

| Stage | Function | Operations Performed |
|-------|----------|---------------------|
| **Line-by-Line** | 18 operations | `pdb_keepcoord`, `pdb_tidy`, `pdb_element`, `pdb_selaltloc`, `pdb_occ`, MSE→MET, HSD/HSE/HID/HIE→HIS, ion charge addition, ATOM↔HETATM conversion, `pdb_fixinsert`, unsupported molecule removal, `pdb_reatom` |
| **Whole-PDB** | 3 operations | `models_should_have_the_same_labels`, `solve_no_chainID_no_segID`, `homogenize_chains` |
| **Combined-PDB** | 1 operation | `correct_equal_chain_segids` |

```mermaid
graph LR
    Input["Raw PDB Lines"] --> LineByLine["Line-by-Line Processing<br/>18 steps"]
    LineByLine --> WholePDB["Whole-PDB Processing<br/>3 steps"]
    WholePDB --> Combined["Combined-PDB Processing<br/>1 step"]
    Combined --> Output["Clean PDB Files"]
    
    LineByLine -.->|"pdb_keepcoord<br/>pdb_tidy<br/>pdb_element<br/>pdb_selaltloc<br/>pdb_occ<br/>replace_MSE_to_MET<br/>replace_HSD_to_HIS<br/>replace_HSE_to_HIS<br/>replace_HID_to_HIS<br/>replace_HIE_to_HIS<br/>add_charges_to_ions<br/>convert_ATOM_to_HETATM<br/>convert_HETATM_to_ATOM<br/>pdb_fixinsert<br/>remove_unsupported_hetatm<br/>remove_unsupported_atom<br/>pdb_reatom<br/>pdb_tidy"| Funcs1[" "]
    
    WholePDB -.->|"models_should_have_the_same_labels<br/>solve_no_chainID_no_segID<br/>homogenize_chains"| Funcs2[" "]
    
    Combined -.->|"correct_equal_chain_segids"| Funcs3[" "]
    
    style Funcs1 fill:none,stroke:none
    style Funcs2 fill:none,stroke:none
    style Funcs3 fill:none,stroke:none
```

**Sources:** [src/haddock/gear/preprocessing.py:1-85](), [src/haddock/gear/preprocessing.py:371-437]()

### Key Preprocessing Functions

The `process_pdbs()` function orchestrates all preprocessing stages:

```mermaid
graph TB
    ProcessPDBs["process_pdbs()"]
    OpenOrGive["_open_or_give()<br/>Normalize input formats"]
    ChainF["chainf()<br/>Apply function chain"]
    
    ProcessPDBs --> OpenOrGive
    OpenOrGive --> LineSteps["line_by_line_processing_steps<br/>(list of 18 functions)"]
    LineSteps --> ChainF
    ChainF --> WholePDB["whole_pdb_processing_steps<br/>(list of 3 functions)"]
    WholePDB --> ChainF2["chainf()<br/>Apply function chain"]
    ChainF2 --> Combined["processed_combined_steps<br/>(list of 1 function)"]
    Combined --> Result["List of processed PDB lines"]
    
    LineSteps -.->|"wrep_pdb_keepcoord<br/>wrep_pdb_tidy_strict<br/>wrep_pdb_element<br/>..."| Detail1[" "]
    WholePDB -.->|"models_should_have_the_same_labels<br/>solve_no_chainID_no_segID<br/>homogenize_chains"| Detail2[" "]
    Combined -.->|"correct_equal_chain_segids"| Detail3[" "]
    
    style Detail1 fill:none,stroke:none
    style Detail2 fill:none,stroke:none
    style Detail3 fill:none,stroke:none
```

**Sources:** [src/haddock/gear/preprocessing.py:326-437](), [src/haddock/libs/libfunc.py:13-38]()

### Ion Charge Processing

HADDOCK3 automatically adds or corrects charges for ions using a three-case priority system:

```mermaid
graph TD
    Ion["Ion in PDB line"]
    CheckAtom{"Charge in<br/>atom name?"}
    CheckRes{"Charge in<br/>resname?"}
    CheckElem{"Charge in<br/>element + charge fields?"}
    
    ProcessAtom["_process_ion_case_atom()<br/>Use atom name"]
    ProcessRes["_process_ion_case_resname()<br/>Use resname"]
    ProcessElem["_process_ion_case_element_charge()<br/>Use element + charge"]
    
    Lookup1["supported_single_ions_atoms_map"]
    Lookup2["supported_single_ions_resnames_map"]
    
    Output["Corrected PDB line<br/>(atom, resname, element, charge)"]
    
    Ion --> CheckAtom
    CheckAtom -->|Yes| ProcessAtom
    CheckAtom -->|No| CheckRes
    CheckRes -->|Yes| ProcessRes
    CheckRes -->|No| CheckElem
    CheckElem -->|Yes| ProcessElem
    CheckElem -->|No| Unchanged["Yield unchanged"]
    
    ProcessAtom --> Lookup1
    ProcessRes --> Lookup2
    ProcessElem --> Lookup1
    
    Lookup1 --> Output
    Lookup2 --> Output
```

**Sources:** [src/haddock/gear/preprocessing.py:673-829](), [src/haddock/core/supported_molecules.py:420-427]()

## CNS Input Generation

HADDOCK3 generates CNS input files dynamically by assembling multiple components into a single `.inp` file.

### CNS Input Structure

```mermaid
graph TB
    PrepCNS["prepare_cns_input()"]
    
    subgraph "Header Components"
        DefaultParams["load_workflow_params()<br/>(module parameters)"]
        AmbigRestr["write_eval_line('ambig_fname')"]
    end
    
    subgraph "Input Section"
        PrepMulti["prepare_multiple_input()<br/>(PDB and PSF paths)"]
        NComponents["write_eval_line('ncomponents')"]
        SegIDs["write_eval_line('prot_segid_N')"]
    end
    
    subgraph "Output Section"
        OutputPDB["write_eval_line('output_pdb_filename')"]
        Count["write_eval_line('count')"]
    end
    
    subgraph "Execution"
        Seed["write_eval_line('seed')"]
        RecipeStr["recipe_str<br/>(CNS protocol from .cns file)"]
    end
    
    PrepCNS --> DefaultParams
    PrepCNS --> AmbigRestr
    PrepCNS --> PrepMulti
    PrepCNS --> NComponents
    PrepCNS --> SegIDs
    PrepCNS --> OutputPDB
    PrepCNS --> Count
    PrepCNS --> Seed
    PrepCNS --> RecipeStr
    
    DefaultParams --> Combine["Concatenate all sections"]
    AmbigRestr --> Combine
    PrepMulti --> Combine
    NComponents --> Combine
    SegIDs --> Combine
    OutputPDB --> Combine
    Count --> Combine
    Seed --> Combine
    RecipeStr --> Combine
    
    Combine --> INPFile["CNS .inp file<br/>(or string if debug=False)"]
```

**Sources:** [src/haddock/libs/libcns.py:321-424](), [src/haddock/libs/libcns.py:151-210]()

### CNS Header Generation

The `generate_default_header()` function loads six types of support files required by CNS:

| File Type | Function | Purpose |
|-----------|----------|---------|
| **Link Files** | `load_link()` | Protein/nucleic acid linkage definitions |
| **Translation Vectors** | `load_trans_vectors()` | Initial position definitions (51 files) |
| **Tensors** | `load_tensor()` | Tensor parameter files (6 files) |
| **Scatter Library** | `load_scatter()` | Scattering data for SAXS/SANS |
| **Axis Definitions** | `load_axis()` | Axis parameter files (3 files) |
| **Water Box** | `load_boxtyp20()` | Water box topology |

**Sources:** [src/haddock/libs/libcns.py:23-53](), [src/haddock/core/cns_paths.py:45-99]()

### Parameter Filtering

The `load_workflow_params()` function filters parameters using `filter_empty_vars()` to exclude:
- NaN values
- Empty strings
- `None` values

```mermaid
graph LR
    Params["Module Parameters<br/>(dict)"]
    Filter["filter_empty_vars()<br/>for each parameter"]
    
    CheckNaN{"Is NaN?"}
    CheckEmpty{"Is empty string?"}
    CheckNone{"Is None?"}
    CheckBool{"Is bool?"}
    CheckPath{"Is Path?"}
    CheckNum{"Is int/float?"}
    
    Params --> Filter
    Filter --> CheckNaN
    CheckNaN -->|Yes| Exclude["Exclude (return False)"]
    CheckNaN -->|No| CheckEmpty
    CheckEmpty -->|Yes| Exclude
    CheckEmpty -->|No| CheckNone
    CheckNone -->|Yes| Exclude
    CheckNone -->|No| CheckBool
    CheckBool -->|Yes| Include["Include (return True)"]
    CheckNum -->|Yes| Include
    CheckPath -->|Yes| Include
    
    Include --> WriteEval["write_eval_line()<br/>Format as CNS eval"]
    WriteEval --> CNSParam["eval ($param=value)"]
```

**Sources:** [src/haddock/libs/libcns.py:114-183](), [src/haddock/libs/libcns.py:185-210]()

## Topology Generation

The `topoaa` module generates CNS topology (`.psf`) and coordinate (`.pdb`) files with rebuilt missing atoms.

### Topology Generation Workflow

```mermaid
graph TB
    Input["Input PDB Files<br/>(from molecules parameter)"]
    
    SplitEns["libpdb.split_ensemble()<br/>Split multi-model files"]
    GetMD5["get_md5()<br/>Extract MD5 hashes"]
    GetOrigin["get_ensemble_origin()<br/>Extract origin info"]
    
    Sanitize["libpdb.sanitize()<br/>Remove unsupported residues"]
    
    GenTopoFunc["generate_topology()"]
    
    subgraph "CNS Input Assembly"
        LoadParams["load_workflow_params()<br/>(module defaults)"]
        GenHeader["generate_default_header()<br/>(6 file types)"]
        FindLink["find_desired_linkfiles()<br/>(termini states)"]
        PrepOutput["prepare_output()<br/>(output filenames)"]
        PrepSingle["prepare_single_input()<br/>(input PDB path)"]
    end
    
    CNSJob["CNSJob<br/>(execute topology generation)"]
    Engine["get_engine()<br/>local/mpi/grid"]
    
    Output["PSF + PDB files<br/>with rebuilt atoms"]
    CreatePDBFile["Create PDBFile objects<br/>with topology references"]
    ExportIO["export_io_models()"]
    
    Input --> SplitEns
    SplitEns --> GetMD5
    SplitEns --> GetOrigin
    SplitEns --> Sanitize
    
    Sanitize --> GenTopoFunc
    GenTopoFunc --> LoadParams
    GenTopoFunc --> GenHeader
    GenTopoFunc --> FindLink
    GenTopoFunc --> PrepOutput
    GenTopoFunc --> PrepSingle
    
    LoadParams --> CNSJob
    GenHeader --> CNSJob
    FindLink --> CNSJob
    PrepOutput --> CNSJob
    PrepSingle --> CNSJob
    
    CNSJob --> Engine
    Engine --> Output
    
    Output --> CreatePDBFile
    GetMD5 --> CreatePDBFile
    GetOrigin --> CreatePDBFile
    CreatePDBFile --> ExportIO
```

**Sources:** [src/haddock/modules/topology/topoaa/__init__.py:54-100](), [src/haddock/modules/topology/topoaa/__init__.py:174-357](), [src/haddock/libs/libpdb.py:117-206]()

### Link File Selection

The `find_desired_linkfiles()` function selects appropriate link files based on termini states:

| Termini State | Protein Link File | Nucleic Link File |
|---------------|------------------|-------------------|
| N-ter: charged, C-ter: charged | `protein-allhdg5-4.link` | `dna-rna-pho-1.3.link` (if 5' phosphate) |
| N-ter: uncharged, C-ter: charged | `protein-allhdg5-4-noNter.link` | `dna-rna-1.3.link` (if 5' OH) |
| N-ter: charged, C-ter: uncharged | `protein-allhdg5-4-noCter.link` | |
| N-ter: uncharged, C-ter: uncharged | `protein-allhdg5-4-noter.link` | |

**Sources:** [src/haddock/libs/libcns.py:56-103](), [src/haddock/core/cns_paths.py:29-38]()

## PDBFile Object and Data Flow

The `PDBFile` class is the core data structure that flows between modules, accumulating metadata throughout the workflow.

### PDBFile Class Structure

```mermaid
classDiagram
    class Persistent {
        +str file_name
        +Format file_type
        +str path
        +str full_name
        +Path rel_path
        +str md5
        +FilePath restr_fname
        +is_present() bool
    }
    
    class PDBFile {
        +topology TopologyFile or list
        +float score
        +str ori_name
        +int or str clt_id
        +int clt_rank
        +int clt_model_rank
        +dict unw_energies
        +int seed
    }
    
    class TopologyFile {
        +str file_name
        +Format file_type = TOPOLOGY
    }
    
    Persistent <|-- PDBFile
    Persistent <|-- TopologyFile
    PDBFile --> TopologyFile : references
```

**Sources:** [src/haddock/libs/libontology.py:34-101](), [src/haddock/libs/libontology.py:114-119]()

### Progressive Enrichment Through Modules

```mermaid
graph LR
    subgraph "topoaa"
        PDB1["PDBFile<br/>+ file_name<br/>+ path<br/>+ md5<br/>+ topology<br/>+ ori_name"]
    end
    
    subgraph "rigidbody/flexref/emref"
        PDB2["PDBFile<br/>+ seed<br/>+ restr_fname<br/>+ unw_energies<br/>+ score"]
    end
    
    subgraph "clustfcc/clustrmsd"
        PDB3["PDBFile<br/>+ clt_id<br/>+ clt_rank<br/>+ clt_model_rank"]
    end
    
    subgraph "caprieval"
        PDB4["PDBFile<br/>+ capri_ss<br/>+ irmsd<br/>+ fnat<br/>+ dockq<br/>+ caprieval_rank"]
    end
    
    PDB1 -->|"ModuleIO.save()<br/>ModuleIO.retrieve_models()"| PDB2
    PDB2 -->|"ModuleIO.save()<br/>ModuleIO.retrieve_models()"| PDB3
    PDB3 -->|"ModuleIO.save()<br/>ModuleIO.retrieve_models()"| PDB4
```

**Sources:** [src/haddock/libs/libontology.py:65-101](), [src/haddock/modules/topology/topoaa/__init__.py:344-356](), [src/haddock/modules/sampling/rigidbody/__init__.py:80-85](), [src/haddock/modules/analysis/clustfcc/__init__.py:161-172]()

## ModuleIO System

The `ModuleIO` class manages inter-module data exchange by serializing and deserializing `PDBFile` objects to JSON format.

### ModuleIO Operations

```mermaid
graph TB
    subgraph "Module N"
        RunN["Module._run()"]
        OutputN["self.output_models<br/>(list of PDBFile)"]
        ExportN["self.export_io_models()"]
    end
    
    subgraph "ModuleIO Serialization"
        ModION["ModuleIO()"]
        AddOutput["add(persistent, mode='o')"]
        CheckFaulty["check_faulty()<br/>Calculate missing %"]
        RemoveMiss["remove_missing()<br/>Filter non-existent"]
        SaveJSON["save()<br/>Write io.json"]
    end
    
    subgraph "Module N+1"
        PrevIO["self.previous_io"]
        Retrieve["retrieve_models()<br/>crossdock/individualize"]
        ProcessNext["Process models"]
    end
    
    RunN --> OutputN
    OutputN --> ExportN
    ExportN --> ModION
    ModION --> AddOutput
    AddOutput --> CheckFaulty
    CheckFaulty --> RemoveMiss
    RemoveMiss --> SaveJSON
    
    SaveJSON -->|"io.json file"| LoadJSON["load()<br/>Read io.json"]
    LoadJSON --> PrevIO
    PrevIO --> Retrieve
    Retrieve --> ProcessNext
```

**Sources:** [src/haddock/libs/libontology.py:121-240](), [src/haddock/modules/base_cns_module.py:40-62]()

### Retrieve Models Options

The `retrieve_models()` method supports three retrieval modes:

| Parameter | Default | Behavior |
|-----------|---------|----------|
| `crossdock` | `False` | If `True`, generates all combinations using `itertools.product()` |
| `individualize` | `False` | If `True`, flattens nested structures using `itertools.chain()` |
| Default | - | Returns pairwise combinations using `zip()` |

**Sources:** [src/haddock/libs/libontology.py:157-192]()

## File Path Management

HADDOCK3 maintains both absolute and relative paths for portability:

```mermaid
graph LR
    PDBFile["PDBFile object"]
    
    subgraph "Path Attributes"
        FileName["file_name<br/>(basename only)"]
        Path["path<br/>(absolute path to dir)"]
        FullName["full_name<br/>(absolute: path + file_name)"]
        RelPath["rel_path<br/>(relative: ../module_name/file_name)"]
    end
    
    PDBFile --> FileName
    PDBFile --> Path
    PDBFile --> FullName
    PDBFile --> RelPath
    
    Usage1["CNS execution<br/>(uses rel_path)"]
    Usage2["File existence check<br/>(uses rel_path.resolve())"]
    Usage3["Module export<br/>(uses rel_path)"]
    
    RelPath --> Usage1
    RelPath --> Usage2
    RelPath --> Usage3
```

**Sources:** [src/haddock/libs/libontology.py:34-62]()

## Sanitization and Validation

### Sanitize Function

The `sanitize()` function removes unsupported residues and corrects naming:

```mermaid
graph TB
    Input["PDB file"]
    ReadLines["Read all lines"]
    
    CheckTag{"Line contains<br/>removal tag?"}
    RenameRes{"Residue needs<br/>renaming?"}
    CheckSupport{"Residue in<br/>supported list?"}
    
    Skip["Skip line"]
    Rename["Apply rename<br/>(e.g., MSE→MET)"]
    Keep["Keep line"]
    
    AddEND["Add END statement"]
    WriteFile["Write cleaned PDB"]
    
    Input --> ReadLines
    ReadLines --> CheckTag
    CheckTag -->|Yes| Skip
    CheckTag -->|No| RenameRes
    RenameRes -->|Yes| Rename
    RenameRes -->|No| CheckSupport
    Rename --> CheckSupport
    CheckSupport -->|Yes| Keep
    CheckSupport -->|No| Skip
    
    Keep --> AddEND
    AddEND --> WriteFile
```

**Removal tags:** `REMAR`, `CTERB`, `CTERA`, `NTERA`, `NTERB`, `CONECT`

**Rename mappings:** `HSD`→`HIS`, `HSE`→`HIS`, `HID`→`HIS`, `HIE`→`HIS`, `WAT`→`TIP3`

**Sources:** [src/haddock/libs/libpdb.py:166-206](), [src/haddock/libs/libpdb.py:102-114]()

### Chain/Segment ID Resolution

The `solve_no_chainID_no_segID()` function ensures consistent identifiers:

```mermaid
graph TD
    CheckChain{"Has chainID?"}
    CheckSeg{"Has segID?"}
    
    CopyChain["pdb_chainxseg.run()<br/>Copy chainID to segID"]
    CopySeg["pdb_segxchain.run()<br/>Copy segID to chainID"]
    AddChain["pdb_chain.run()<br/>Add chainID (A, B, ...)"]
    AddSeg["pdb_chainxseg.run()<br/>Copy to segID"]
    PrioritizeChain["pdb_chainxseg.run()<br/>Copy chainID to segID"]
    
    NoChange["Return unchanged"]
    
    CheckChain -->|No| CheckSeg
    CheckChain -->|Yes| CheckSeg
    CheckSeg -->|No chainID, Yes segID| CopySeg
    CheckSeg -->|Yes chainID, No segID| CopyChain
    CheckSeg -->|No chainID, No segID| AddChain
    CheckSeg -->|Both differ| PrioritizeChain
    CheckSeg -->|Both same| NoChange
    
    AddChain --> AddSeg
```

**Sources:** [src/haddock/gear/preprocessing.py:896-937]()

## Data Processing in Module Execution

Each CNS-based module follows a standard data processing pattern:

```mermaid
sequenceDiagram
    participant Module
    participant PrevIO as previous_io
    participant PrepCNS as prepare_cns_input
    participant Engine
    participant CNS
    participant HaddockModel
    participant ModuleIO
    
    Module->>PrevIO: retrieve_models()
    PrevIO-->>Module: list[PDBFile]
    
    loop For each model
        Module->>PrepCNS: prepare_cns_input(model, params)
        PrepCNS-->>Module: .inp file or string
        Module->>Module: create CNSJob
    end
    
    Module->>Engine: get_engine(mode, params)
    Engine-->>Module: Scheduler/MPIScheduler/GRIDScheduler
    
    Module->>Engine: engine.run(jobs)
    Engine->>CNS: Execute CNS jobs
    CNS-->>Engine: Output PDB files
    
    loop For each output
        Module->>HaddockModel: HaddockModel(pdb_file)
        HaddockModel-->>Module: energies dict
        Module->>Module: calc_haddock_score(energies)
        Module->>Module: Update PDBFile.score, unw_energies
    end
    
    Module->>ModuleIO: export_io_models()
    ModuleIO->>ModuleIO: save(io.json)
```

**Sources:** [src/haddock/modules/sampling/rigidbody/__init__.py:196-271](), [src/haddock/modules/refinement/flexref/__init__.py:56-159](), [src/haddock/modules/scoring/emscoring/__init__.py:39-102]()

## Error Handling and Tolerance

HADDOCK3 implements fault tolerance through the `faulty_tolerance` parameter:

```mermaid
graph TB
    ExportIO["export_io_models(faulty_tolerance)"]
    CheckFaulty["ModuleIO.check_faulty()"]
    
    CountTotal["Count total expected outputs"]
    CountPresent["Count present outputs"]
    CalcPercent["faulty_per = (1 - present/total) * 100"]
    
    Compare{"faulty_per ><br/>faulty_tolerance?"}
    
    RemoveMissing["remove_missing()<br/>Filter out absent structures"]
    SaveIO["save(io.json)"]
    
    RaiseError["Raise Exception<br/>'X% structures missing'"]
    
    ExportIO --> CheckFaulty
    CheckFaulty --> CountTotal
    CheckFaulty --> CountPresent
    CountTotal --> CalcPercent
    CountPresent --> CalcPercent
    
    CalcPercent --> Compare
    Compare -->|"faulty_per <= tolerance"| RemoveMissing
    Compare -->|"faulty_per > tolerance"| RaiseError
    
    RemoveMissing --> SaveIO
```

**Sources:** [src/haddock/libs/libontology.py:194-237](), [src/haddock/modules/base_cns_module.py:40-62]()

---