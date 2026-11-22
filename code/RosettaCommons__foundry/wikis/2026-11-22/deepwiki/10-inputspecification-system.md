# InputSpecification System

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [models/rfd3/configs/inference_engine/rfdiffusion3.yaml](models/rfd3/configs/inference_engine/rfdiffusion3.yaml)
- [models/rfd3/configs/trainer/loss/losses/diffusion_loss.yaml](models/rfd3/configs/trainer/loss/losses/diffusion_loss.yaml)
- [models/rfd3/docs/.assets/input_selection_large.png](models/rfd3/docs/.assets/input_selection_large.png)
- [models/rfd3/docs/examples/demo.json](models/rfd3/docs/examples/demo.json)
- [models/rfd3/docs/input.md](models/rfd3/docs/input.md)
- [models/rfd3/src/rfd3/inference/input_parsing.py](models/rfd3/src/rfd3/inference/input_parsing.py)
- [models/rfd3/src/rfd3/inference/legacy_input_parsing.py](models/rfd3/src/rfd3/inference/legacy_input_parsing.py)
- [models/rfd3/src/rfd3/model/RFD3_diffusion_module.py](models/rfd3/src/rfd3/model/RFD3_diffusion_module.py)
- [models/rfd3/tests/test_bond_preservation_cases.py](models/rfd3/tests/test_bond_preservation_cases.py)
- [models/rfd3/tests/test_conditioning.py](models/rfd3/tests/test_conditioning.py)
- [models/rfd3/tests/test_legacy_ptm_bonds.py](models/rfd3/tests/test_legacy_ptm_bonds.py)

</details>



## Purpose and Scope

The InputSpecification System is RFdiffusion3's declarative interface for defining protein design tasks. It provides a validated, type-safe specification language for describing what structures to generate, what constraints to apply, and how to condition the diffusion process. The system translates user-provided JSON/YAML configurations into annotated `AtomArray` objects ready for model inference.

This page covers the specification schema, validation pipeline, and the `InputSelection` mini-language. For information about running inference with these specifications, see [4.5](). For training-time usage, see [4.6](). For symmetry configuration details, see [4.3]().

---

## System Architecture

The InputSpecification System consists of three major components: specification parsing, validation, and atom array construction.

```mermaid
graph TB
    subgraph "Input Sources"
        JSON["JSON/YAML Files<br/>(user-provided)"]
        CLI["CLI Arguments<br/>(Hydra overrides)"]
        AtomArrayInput["Pre-loaded AtomArray<br/>(programmatic)"]
    end
    
    subgraph "Parsing Layer"
        ProcessInput["process_input()<br/>engine.py"]
        NormalizeInputs["normalize_inputs()<br/>engine.py"]
        EnsureAbsPath["ensure_input_is_abspath()<br/>input_parsing.py"]
    end
    
    subgraph "Specification Core"
        DesignInputSpec["DesignInputSpecification<br/>input_parsing.py:113-231"]
        InputSelection["InputSelection<br/>parsing.py"]
        SymmetryConfig["SymmetryConfig<br/>symmetry_utils.py"]
    end
    
    subgraph "Validation Pipeline"
        SchemaValidation["validate_input_schema()<br/>input_parsing.py:234-274"]
        Canonicalize["canonicalize()<br/>input_parsing.py:276-284"]
        LoadInput["load_input()<br/>input_parsing.py:286-362"]
        AssignTypes["_assign_types_to_input()<br/>input_parsing.py:417-498"]
        AssertExclusivity["assert_exclusivity()<br/>input_parsing.py:368-404"]
    end
    
    subgraph "Building Phase"
        BuildInit["_build_init()<br/>input_parsing.py:543-630"]
        AccumulateComponents["accumulate_components()<br/>input_parsing.py"]
        AppendLigand["_append_ligand()<br/>input_parsing.py:661-683"]
        ApplySymmetry["_apply_symmetry()<br/>input_parsing.py:685-694"]
        SetOrigin["_set_origin()<br/>input_parsing.py:696-720"]
        ApplyGlobals["_apply_globals()<br/>input_parsing.py:722-749"]
    end
    
    subgraph "Output"
        AnnotatedAtomArray["AtomArray<br/>with conditioning annotations"]
        Metadata["Specification Metadata<br/>(for reproducibility)"]
    end
    
    JSON --> ProcessInput
    CLI --> ProcessInput
    AtomArrayInput --> DesignInputSpec
    
    ProcessInput --> NormalizeInputs
    NormalizeInputs --> EnsureAbsPath
    EnsureAbsPath --> DesignInputSpec
    
    DesignInputSpec --> SchemaValidation
    SchemaValidation --> Canonicalize
    Canonicalize --> LoadInput
    LoadInput --> AssignTypes
    AssignTypes --> AssertExclusivity
    
    InputSelection -.->|"used by"| LoadInput
    SymmetryConfig -.->|"used by"| ApplySymmetry
    
    DesignInputSpec --> BuildInit
    BuildInit --> AccumulateComponents
    AccumulateComponents --> AppendLigand
    AppendLigand --> ApplySymmetry
    ApplySymmetry --> SetOrigin
    SetOrigin --> ApplyGlobals
    
    ApplyGlobals --> AnnotatedAtomArray
    DesignInputSpec --> Metadata
```

**Sources:** [models/rfd3/src/rfd3/inference/input_parsing.py:113-777](), [models/rfd3/docs/input.md:1-25]()

---

## Core Components

### DesignInputSpecification Class

The `DesignInputSpecification` is a Pydantic `BaseModel` that defines the complete schema for RFD3 input specifications [models/rfd3/src/rfd3/inference/input_parsing.py:113-123](). It enforces strict validation at initialization time and provides methods for building annotated atom arrays.

```mermaid
graph TB
    subgraph "DesignInputSpecification Fields"
        DataInputs["Data Inputs<br/>input: str<br/>atom_array_input: AtomArray<br/>contig: InputSelection<br/>unindex: InputSelection"]
        
        Constraints["Constraints<br/>length: str<br/>ligand: str<br/>cif_parser_args: dict"]
        
        Conditioning["Conditioning Selections<br/>select_fixed_atoms: InputSelection<br/>select_unfixed_sequence: InputSelection<br/>select_buried/exposed: InputSelection<br/>select_hbond_donor/acceptor: InputSelection<br/>select_hotspots: InputSelection"]
        
        Globals["Global Conditioning<br/>symmetry: SymmetryConfig<br/>ori_token: list[float]<br/>infer_ori_strategy: str<br/>plddt_enhanced: bool<br/>is_non_loopy: bool<br/>partial_t: float"]
        
        Meta["Metadata<br/>extra: dict<br/>dialect: int"]
    end
    
    subgraph "Validators (model_validator)"
        PreValidation["Pre-Validation<br/>validate_input_schema()<br/>canonicalize()<br/>load_input()"]
        
        PostValidation["Post-Validation<br/>assert_exclusivity()<br/>attempt_expansion()<br/>_assign_types_to_input()"]
    end
    
    subgraph "Build Methods"
        Build["build()<br/>→ AtomArray + metadata"]
        BuildInit["_build_init()<br/>→ initial AtomArray"]
        Setters["_append_ligand()<br/>_apply_symmetry()<br/>_set_origin()<br/>_apply_globals()"]
    end
    
    DataInputs --> PreValidation
    Constraints --> PreValidation
    Conditioning --> PreValidation
    Globals --> PreValidation
    Meta --> PreValidation
    
    PreValidation --> PostValidation
    PostValidation --> Build
    
    Build --> BuildInit
    BuildInit --> Setters
```

**Key Validation Rules:**

| Validator | Purpose | File Location |
|-----------|---------|---------------|
| `validate_input_schema` | Ensures either `input` or `contig`/`length` provided; validates usage consistency | [models/rfd3/src/rfd3/inference/input_parsing.py:234-274]() |
| `canonicalize` | Normalizes `length` to string format, `input` to absolute path | [models/rfd3/src/rfd3/inference/input_parsing.py:276-284]() |
| `load_input` | Loads atom array from file, initializes `InputSelection` objects | [models/rfd3/src/rfd3/inference/input_parsing.py:286-362]() |
| `assert_exclusivity` | Validates mutually exclusive selections (RASA bins, motifs) | [models/rfd3/src/rfd3/inference/input_parsing.py:368-404]() |
| `_assign_types_to_input` | Applies selection masks to atom array annotations | [models/rfd3/src/rfd3/inference/input_parsing.py:417-498]() |

**Sources:** [models/rfd3/src/rfd3/inference/input_parsing.py:113-231](), [models/rfd3/src/rfd3/inference/input_parsing.py:234-404]()

---

### InputSelection Mini-Language

The `InputSelection` class provides a flexible mini-language for selecting atoms and residues within input structures [models/rfd3/src/rfd3/inference/parsing.py](). It accepts three input formats: booleans, contig strings, or dictionaries with atom-level granularity.

```mermaid
graph LR
    subgraph "Input Formats"
        BoolInput["Boolean<br/>true/false"]
        StringInput["Contig String<br/>'A1-10,B5-8'"]
        DictInput["Dictionary<br/>{'A1-2': 'BKBN',<br/>'B5': 'N,CA,C'}"]
    end
    
    subgraph "InputSelection Class"
        FromAny["from_any()<br/>Factory method"]
        ParseContig["Parse contig string"]
        ParseDict["Parse dictionary"]
        Storage["Internal Storage<br/>dict[str, list[str]]"]
    end
    
    subgraph "Query Methods"
        GetMask["get_mask()<br/>→ np.ndarray[bool]"]
        GetTokens["get_tokens()<br/>→ dict[str, AtomArray]"]
        GetKey["get(key)<br/>→ list[str] | None"]
    end
    
    subgraph "Special Values"
        ShorthandValues["Shorthand Values<br/>ALL → all atoms<br/>BKBN → N,CA,C,O<br/>TIP → residue-specific tip atom"]
    end
    
    BoolInput --> FromAny
    StringInput --> FromAny
    DictInput --> FromAny
    
    FromAny --> ParseContig
    FromAny --> ParseDict
    ParseContig --> Storage
    ParseDict --> Storage
    
    Storage --> GetMask
    Storage --> GetTokens
    Storage --> GetKey
    
    ShorthandValues -.->|"expanded during"| ParseDict
```

**Example Usage:**

```python
# Boolean: select all/none
select_fixed_atoms = InputSelection.from_any(True, atom_array)

# Contig string: select residues
select_fixed_atoms = InputSelection.from_any("A1-10,B5-8", atom_array)

# Dictionary: atom-level control
select_fixed_atoms = InputSelection.from_any({
    "A1-2": "BKBN",      # N,CA,C,O for residues A1-2
    "A3": "N,CA,C,O,CB", # Explicit atom list
    "B5-7": "ALL",       # All atoms
    "B10": "TIP"         # Residue-specific tip atom
}, atom_array)
```

**Sources:** [models/rfd3/src/rfd3/inference/input_parsing.py:150-165](), [models/rfd3/docs/input.md:95-110]()

---

## Input File Format

The InputSpecification System accepts JSON or YAML files containing one or more design specifications. Each top-level key becomes an independent design task [models/rfd3/docs/input.md:34-47]().

### JSON Structure

```mermaid
graph TB
    subgraph "JSON/YAML File Structure"
        Root["Root Object"]
        GlobalArgs["global_args<br/>(optional)<br/>Applied to all specs"]
        Spec1["'spec-1': {...}"]
        Spec2["'spec-2': {...}"]
        SpecN["'spec-N': {...}"]
    end
    
    subgraph "Individual Specification"
        Input["input: 'path/to/pdb'"]
        Contig["contig: '50-80,/0,A1-100'"]
        SelectUnfixed["select_unfixed_sequence: 'A20-35'"]
        Ligand["ligand: 'HAX,OAA'"]
        Symmetry["symmetry: {...}"]
        Other["... other fields"]
    end
    
    Root --> GlobalArgs
    Root --> Spec1
    Root --> Spec2
    Root --> SpecN
    
    Spec1 --> Input
    Spec1 --> Contig
    Spec1 --> SelectUnfixed
    Spec1 --> Ligand
    Spec1 --> Symmetry
    Spec1 --> Other
    
    GlobalArgs -.->|"merged into"| Spec1
    GlobalArgs -.->|"merged into"| Spec2
    GlobalArgs -.->|"merged into"| SpecN
```

**Example JSON:**

```json
{
  "M0255_1mg5_unfixed": {
    "input": "../input_pdbs/M0255_1mg5.pdb", 
    "ligand": "NAI,ACT",    
    "unindex": "A108,A139,A152,A156",
    "length": "180-200",
    "select_fixed_atoms": {
      "A108": "ND2,CG",
      "A139": "OG,CB,CA",
      "A152": "OH,CZ",
      "A156": "NZ,CE,CD",
      "ACT": "OXT",
      "NAI": ""
    },
    "allow_ligand_on_existing_chain": true
  }
}
```

**Sources:** [models/rfd3/docs/examples/demo.json:1-16](), [models/rfd3/docs/input.md:34-47]()

---

## Processing Pipeline

The InputSpecification System processes inputs through a multi-stage pipeline that validates, loads, and constructs annotated atom arrays.

```mermaid
graph TB
    subgraph "Stage 1: File Loading"
        LoadJSON["Load JSON/YAML"]
        ApplyGlobalArgs["Apply global_args"]
        SubsetKeys["Subset to keys"]
        MakeAbsolute["Make paths absolute"]
    end
    
    subgraph "Stage 2: Specification Creation"
        SafeInit["DesignInputSpecification.safe_init()"]
        CheckDialect["Check dialect field"]
        LegacyPath["dialect=1<br/>→ LegacySpecification"]
        ModernPath["dialect=2<br/>→ DesignInputSpecification"]
    end
    
    subgraph "Stage 3: Pre-Validation"
        ValidateSchema["validate_input_schema()"]
        Canonicalize["canonicalize()"]
        LoadAtomArray["load_input()"]
        CoerceSelections["Coerce to InputSelection"]
    end
    
    subgraph "Stage 4: Post-Validation"
        CheckExclusivity["assert_exclusivity()"]
        AttemptExpansion["attempt_expansion()"]
        AssignTypes["_assign_types_to_input()"]
    end
    
    subgraph "Stage 5: Building"
        BuildInit["_build_init()"]
        GetTokens["Get indexed/unindexed tokens"]
        SampleContig["Sample contig pattern"]
        Accumulate["accumulate_components()"]
        PostProcess["Post-process:<br/>append ligand,<br/>apply symmetry,<br/>set origin,<br/>apply globals"]
    end
    
    subgraph "Stage 6: Output"
        ValidateAnnotations["Validate annotations"]
        ConvertBool["Convert to bool"]
        ReturnArray["Return AtomArray + metadata"]
    end
    
    LoadJSON --> ApplyGlobalArgs
    ApplyGlobalArgs --> SubsetKeys
    SubsetKeys --> MakeAbsolute
    MakeAbsolute --> SafeInit
    
    SafeInit --> CheckDialect
    CheckDialect --> LegacyPath
    CheckDialect --> ModernPath
    
    ModernPath --> ValidateSchema
    ValidateSchema --> Canonicalize
    Canonicalize --> LoadAtomArray
    LoadAtomArray --> CoerceSelections
    
    CoerceSelections --> CheckExclusivity
    CheckExclusivity --> AttemptExpansion
    AttemptExpansion --> AssignTypes
    
    AssignTypes --> BuildInit
    BuildInit --> GetTokens
    GetTokens --> SampleContig
    SampleContig --> Accumulate
    Accumulate --> PostProcess
    
    PostProcess --> ValidateAnnotations
    ValidateAnnotations --> ConvertBool
    ConvertBool --> ReturnArray
```

**Key Functions:**

| Function | Purpose | Location |
|----------|---------|----------|
| `DesignInputSpecification.safe_init()` | Factory method handling legacy/modern dialects | [models/rfd3/src/rfd3/inference/input_parsing.py:752-762]() |
| `validate_input_schema()` | Validates field requirements and usage | [models/rfd3/src/rfd3/inference/input_parsing.py:234-274]() |
| `load_input()` | Loads atom array and initializes selections | [models/rfd3/src/rfd3/inference/input_parsing.py:286-362]() |
| `_assign_types_to_input()` | Applies selection masks to annotations | [models/rfd3/src/rfd3/inference/input_parsing.py:417-498]() |
| `build()` | Orchestrates atom array construction | [models/rfd3/src/rfd3/inference/input_parsing.py:504-537]() |

**Sources:** [models/rfd3/src/rfd3/inference/input_parsing.py:504-777]()

---

## Conditioning Annotations

The InputSpecification System assigns conditioning annotations to atoms based on the provided selections [models/rfd3/src/rfd3/inference/input_parsing.py:417-498](). These annotations control the diffusion process.

```mermaid
graph TB
    subgraph "Selection Fields"
        FixedAtoms["select_fixed_atoms<br/>→ is_motif_atom_with_fixed_coord"]
        UnfixedSeq["select_unfixed_sequence<br/>→ is_motif_atom_with_fixed_seq"]
        Unindex["unindex<br/>→ is_motif_atom_unindexed"]
        Hotspots["select_hotspots<br/>→ is_atom_level_hotspot"]
        HbondDonor["select_hbond_donor<br/>→ active_donor"]
        HbondAcceptor["select_hbond_acceptor<br/>→ active_acceptor"]
        Buried["select_buried<br/>→ rasa_bin=0"]
        PartialBuried["select_partially_buried<br/>→ rasa_bin=1"]
        Exposed["select_exposed<br/>→ rasa_bin=2"]
    end
    
    subgraph "Application Logic"
        InitDefaults["Initialize defaults"]
        PerTokenLoop["For each token (residue)"]
        RedesignCheck["Check redesign_motif_sidechains"]
        ApplyMask["Apply selection mask"]
    end
    
    subgraph "Final Annotations"
        CoordFixed["is_motif_atom_with_fixed_coord"]
        SeqFixed["is_motif_atom_with_fixed_seq"]
        Unindexed["is_motif_atom_unindexed"]
        AtomHotspot["is_atom_level_hotspot"]
        ActiveDonor["active_donor"]
        ActiveAcceptor["active_acceptor"]
        RASABin["rasa_bin"]
    end
    
    FixedAtoms --> InitDefaults
    UnfixedSeq --> InitDefaults
    Unindex --> InitDefaults
    Hotspots --> InitDefaults
    HbondDonor --> InitDefaults
    HbondAcceptor --> InitDefaults
    Buried --> InitDefaults
    PartialBuried --> InitDefaults
    Exposed --> InitDefaults
    
    InitDefaults --> PerTokenLoop
    PerTokenLoop --> RedesignCheck
    RedesignCheck --> ApplyMask
    
    ApplyMask --> CoordFixed
    ApplyMask --> SeqFixed
    ApplyMask --> Unindexed
    ApplyMask --> AtomHotspot
    ApplyMask --> ActiveDonor
    ApplyMask --> ActiveAcceptor
    ApplyMask --> RASABin
```

**Required Annotations:**

| Annotation | Type | Purpose |
|------------|------|---------|
| `is_motif_atom_with_fixed_coord` | `int` (bool) | Whether atom coordinates are fixed during diffusion |
| `is_motif_atom_with_fixed_seq` | `int` (bool) | Whether atom sequence identity is fixed |
| `is_motif_atom_unindexed` | `int` (bool) | Whether motif position is unknown to model |
| `is_atom_level_hotspot` | `int` (bool) | PPI hotspot conditioning |
| `active_donor` | `int` (bool) | Hydrogen bond donor atom |
| `active_acceptor` | `int` (bool) | Hydrogen bond acceptor atom |
| `rasa_bin` | `int` | Solvent accessibility: 0=buried, 1=partial, 2=exposed, 3=unconditioned |

**Sources:** [models/rfd3/src/rfd3/inference/input_parsing.py:417-498](), [models/rfd3/src/rfd3/constants.py:30-34]()

---

## Partial Diffusion Mode

When `partial_t` is specified, the InputSpecification System operates in partial diffusion mode [models/rfd3/docs/input.md:121-147]().

```mermaid
graph TB
    subgraph "Partial Diffusion Detection"
        CheckPartialT["Check partial_t field"]
        RequireInput["Require input file"]
        DisallowLength["Disallow length argument"]
    end
    
    subgraph "Modified Building"
        SkipSampling["Skip contig sampling"]
        AssignTypes["assign_types_()"]
        SubsetProtein["Subset to protein"]
        AppendUnindexed["Append unindexed components"]
    end
    
    subgraph "Modified Origin Setting"
        CheckSymmetry["Check if symmetry present"]
        SkipCOMCenter["Skip COM centering"]
        UseCOM["Use COM for origin"]
        KeepCoords["Keep all coordinates"]
    end
    
    subgraph "Partial T Annotation"
        SetPartialT["Set partial_t annotation"]
    end
    
    CheckPartialT --> RequireInput
    RequireInput --> DisallowLength
    
    DisallowLength --> SkipSampling
    SkipSampling --> AssignTypes
    AssignTypes --> SubsetProtein
    SubsetProtein --> AppendUnindexed
    
    AppendUnindexed --> CheckSymmetry
    CheckSymmetry --> SkipCOMCenter
    CheckSymmetry --> UseCOM
    SkipCOMCenter --> KeepCoords
    UseCOM --> KeepCoords
    
    KeepCoords --> SetPartialT
```

**Sources:** [models/rfd3/src/rfd3/inference/input_parsing.py:195-198](), [models/rfd3/docs/input.md:121-147]()

---

## Legacy Compatibility

The system maintains backwards compatibility with original input formats through the `LegacySpecification` class [models/rfd3/src/rfd3/inference/input_parsing.py:78-105]().

```mermaid
graph LR
    subgraph "Dialect Selection"
        CheckDialect["Check 'dialect' field"]
        Dialect1["dialect=1<br/>(Legacy)"]
        Dialect2["dialect=2<br/>(Modern)"]
    end
    
    subgraph "Legacy Path"
        LegacySpec["LegacySpecification"]
        LegacyBuild["create_atom_array_from_design_specification_legacy()"]
    end
    
    subgraph "Modern Path"
        ModernSpec["DesignInputSpecification"]
        ModernBuild["build()"]
    end
    
    CheckDialect --> Dialect1
    CheckDialect --> Dialect2
    
    Dialect1 --> LegacySpec
    LegacySpec --> LegacyBuild
    
    Dialect2 --> ModernSpec
    ModernSpec --> ModernBuild
```

**Migration Guide:**

| Legacy Field | Modern Field | Notes |
|--------------|--------------|-------|
| `unfix_sequence` | `select_unfixed_sequence` | Now uses `InputSelection` |
| `contig_atoms` | `select_fixed_atoms` | Now uses `InputSelection` |
| `atomwise_rasa` | `select_buried`/`select_exposed` | Split into explicit fields |

**Sources:** [models/rfd3/src/rfd3/inference/input_parsing.py:78-105](), [models/rfd3/src/rfd3/inference/legacy_input_parsing.py:416-611]()

---

## Field Reference

### Complete Field Table

| Field | Type | Description |
|-------|------|-------------|
| `input` | `str` | Path to input PDB/CIF file [models/rfd3/src/rfd3/inference/input_parsing.py:130]() |
| `contig` | `InputSelection` | Contig specification string [models/rfd3/src/rfd3/inference/input_parsing.py:132]() |
| `unindex` | `InputSelection` | Unindexed components selection [models/rfd3/src/rfd3/inference/input_parsing.py:133]() |
| `length` | `str` | Length range as 'min-max' or int [models/rfd3/src/rfd3/inference/input_parsing.py:139]() |
| `ligand` | `str` | Ligand name or index to include [models/rfd3/src/rfd3/inference/input_parsing.py:140]() |
| `select_fixed_atoms` | `InputSelection` | Atoms to fix coordinates for [models/rfd3/src/rfd3/inference/input_parsing.py:150]() |
| `select_unfixed_sequence` | `InputSelection` | Components to unfix sequence for [models/rfd3/src/rfd3/inference/input_parsing.py:158]() |
| `select_buried` | `InputSelection` | Selection of RASA buried conditioning [models/rfd3/src/rfd3/inference/input_parsing.py:168]() |
| `select_hotspots` | `InputSelection` | Selection of hotspot residues [models/rfd3/src/rfd3/inference/input_parsing.py:182]() |
| `partial_t` | `float` | Partial diffusion noise level [models/rfd3/src/rfd3/inference/input_parsing.py:198]() |
| `dialect` | `int` | RFdiffusion3 input dialect (1: legacy, 2: release) [models/rfd3/src/rfd3/inference/input_parsing.py:144]() |

**Sources:** [models/rfd3/src/rfd3/inference/input_parsing.py:121-229]()

---