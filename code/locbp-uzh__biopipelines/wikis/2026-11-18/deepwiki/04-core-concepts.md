# Core Concepts

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [Docs/UserManual.md](Docs/UserManual.md)
- [HelpScripts/pipe_plot.py](HelpScripts/pipe_plot.py)
- [biopipelines/base_config.py](biopipelines/base_config.py)
- [biopipelines/plot.py](biopipelines/plot.py)
- [biopipelines/pymol.py](biopipelines/pymol.py)
- [config.yaml](config.yaml)

</details>



This page introduces the fundamental architectural concepts that underpin BioPipelines. These concepts define how pipelines are structured, how tools interact, how data flows between components, and how the framework manages execution.

**Scope**: This page provides conceptual overviews with diagrams and examples. For detailed documentation on specific aspects, see:
- Pipeline context and resource management → [Pipeline Context and Resources](#3.1)
- Tool architecture and implementation → [Tools and BaseConfig](#3.2)
- Data structures and I/O patterns → [Data Streams and StandardizedOutput](#3.3)
- Input combination logic → [Combinatorics: Each and Bundle](#3.4)
- ID naming and tracking → [ID Generation and Provenance Tracking](#3.5)

---

## The Two-Phase Execution Model

BioPipelines operates in two distinct phases: **Configuration** (Python) and **Execution** (Bash/external tools). This separation enables the framework to predict the complete filesystem structure, validate dependencies, and generate executable scripts without running any actual computation.

```mermaid
sequenceDiagram
    participant User as "User Script<br/>(pipeline.py)"
    participant Pipeline as "Pipeline Context"
    participant Tool as "BaseConfig Subclass<br/>(e.g., RFdiffusion)"
    participant FS as "Filesystem"
    participant Bash as "Bash Executor"
    participant Helper as "Helper Script<br/>(pipe_*.py)"
    
    rect rgb(240, 248, 255)
        Note over User,FS: CONFIGURATION PHASE (Python)
        User->>Pipeline: with Pipeline(project, job):
        Pipeline->>Pipeline: Create job folder structure
        User->>Tool: RFdiffusion(pdb=lysozyme, ...)
        Tool->>Tool: __new__() checks for active pipeline
        Tool->>Pipeline: Auto-register via _auto_register()
        Pipeline->>Tool: Set output_folder, execution_order
        Tool->>Tool: validate_params()
        Tool->>Tool: Predict output IDs/files
        Tool->>FS: Write config JSON
        Tool->>FS: Write bash script
        Tool->>Pipeline: Return StandardizedOutput
        Pipeline->>User: Exit context, return RunTime paths
    end
    
    rect rgb(255, 250, 240)
        Note over Bash,Helper: EXECUTION PHASE (Bash + Python)
        Bash->>Helper: Execute generated script
        Helper->>Helper: Read config JSON
        Helper->>Helper: Load input DataStreams
        Helper->>Helper: Run tool logic
        Helper->>FS: Write outputs
        Helper->>FS: Create completion marker
    end
```

**Sources**: [Docs/UserManual.md:157-171](), [biopipelines/base_config.py:117-160]()

### Configuration Phase (Python)

During this phase, BioPipelines:
1. **Predicts the filesystem structure**: Output folders, file paths, and IDs are determined before execution
2. **Validates parameters**: Tool configurations are checked for consistency
3. **Generates scripts**: Bash wrappers and JSON configs are written to disk
4. **Tracks dependencies**: Tool execution order is determined based on data flow

No actual computation occurs. The `BaseConfig.__new__()` method intercepts tool instantiation and returns a `StandardizedOutput` object instead of the tool instance itself, enabling method chaining while maintaining full prediction capabilities.

**Sources**: [biopipelines/base_config.py:117-160]()

### Execution Phase (Bash)

The generated scripts execute sequentially or via SLURM, reading configurations and performing actual work. Helper scripts in `HelpScripts/` implement tool-specific logic in Python, reading JSON configs generated during configuration.

**Sources**: [Docs/UserManual.md:157-171]()

---

## Core Abstractions

BioPipelines is built on four primary abstractions that work together to create a composable pipeline framework:

```mermaid
graph TB
    subgraph "Pipeline Layer"
        Pipeline["Pipeline Context<br/>(context manager)"]
    end
    
    subgraph "Tool Layer"
        BaseConfig["BaseConfig<br/>(abstract base class)"]
        RFdiffusion["RFdiffusion"]
        ProteinMPNN["ProteinMPNN"]
        Boltz2["Boltz2"]
        Panda["Panda"]
        
        BaseConfig -.inherits.-> RFdiffusion
        BaseConfig -.inherits.-> ProteinMPNN
        BaseConfig -.inherits.-> Boltz2
        BaseConfig -.inherits.-> Panda
    end
    
    subgraph "Data Layer"
        StandardizedOutput["StandardizedOutput<br/>(unified output interface)"]
        StreamContainer["StreamContainer<br/>(.streams.structures, etc.)"]
        TableContainer["TableContainer<br/>(.tables.confidence, etc.)"]
        DataStream["DataStream<br/>(ids, files, format)"]
        TableInfo["TableInfo<br/>(path, columns, count)"]
        
        StandardizedOutput --> StreamContainer
        StandardizedOutput --> TableContainer
        StreamContainer --> DataStream
        TableContainer --> TableInfo
    end
    
    subgraph "Combinatorics Layer"
        Each["Each<br/>(Cartesian product)"]
        Bundle["Bundle<br/>(grouping)"]
    end
    
    Pipeline --> BaseConfig
    BaseConfig --> StandardizedOutput
    Each --> BaseConfig
    Bundle --> BaseConfig
    
    style Pipeline fill:#e1f5ff
    style BaseConfig fill:#ffe1e1
    style StandardizedOutput fill:#e1ffe1
    style DataStream fill:#fff4e1
```

**Sources**: [biopipelines/base_config.py:34-657](), [biopipelines/base_config.py:924-1050]()

### Pipeline Context

The `Pipeline` context manager serves as the orchestration layer. It:
- Creates the job folder structure (`<project>/<job>_NNN/`)
- Registers tools automatically via `__new__()` interception
- Assigns execution order and output folders
- Generates the master execution script
- Manages resource allocation per batch

**Sources**: [Docs/UserManual.md:32-46]()

### BaseConfig Abstract Class

All tools inherit from `BaseConfig`, which provides:
- **Parameter validation** via `validate_params()`
- **Input configuration** via `configure_inputs()`
- **Script generation** via `generate_script()`
- **Output prediction** via `get_output_files()`
- **Auto-registration** via `__new__()` method override

The `__new__()` method enables declarative syntax by intercepting instantiation and returning `StandardizedOutput` instead of the tool instance when called within a `Pipeline` context.

**Sources**: [biopipelines/base_config.py:34-160]()

### StandardizedOutput

`StandardizedOutput` provides a unified interface to tool outputs with two containers:
- **StreamContainer** (`.streams`): File-based outputs (structures, sequences, compounds, MSAs, images)
- **TableContainer** (`.tables`): CSV-based metrics and metadata

This abstraction enables tools to consume outputs from any other tool without knowing implementation details.

**Sources**: [biopipelines/base_config.py:1052-1127]()

---

## Data Flow Architecture

Data flows through BioPipelines via typed containers that track IDs, files, and provenance:

```mermaid
graph LR
    subgraph "Input Types"
        PDB["PDB(code)"]
        Sequence["Sequence(seq)"]
        Ligand["Ligand(smiles)"]
    end
    
    subgraph "Combinatorics"
        Each["Each(...)"]
        Bundle["Bundle(...)"]
    end
    
    subgraph "Tool Execution"
        Tool["Tool Instance<br/>(e.g., Boltz2)"]
    end
    
    subgraph "StandardizedOutput"
        SO["StandardizedOutput"]
        SC["StreamContainer<br/>.streams"]
        TC["TableContainer<br/>.tables"]
    end
    
    subgraph "DataStream"
        DS["DataStream<br/>ids: ['id1', 'id2']<br/>files: ['p1.pdb', 'p2.pdb']<br/>format: 'pdb'<br/>map_table: 'structures.csv'"]
    end
    
    subgraph "TableInfo"
        TI["TableInfo<br/>path: 'results.csv'<br/>columns: ['id', 'plddt', ...]<br/>count: 100<br/>.info metadata<br/>.column_name reference"]
    end
    
    PDB --> Each
    Sequence --> Each
    Ligand --> Bundle
    
    Each --> Tool
    Bundle --> Tool
    
    Tool --> SO
    SO --> SC
    SO --> TC
    
    SC --> DS
    TC --> TI
    
    DS -.feeds into.-> Tool
    TI -.column refs.-> Tool
```

**Sources**: [biopipelines/base_config.py:924-1127](), [Docs/UserManual.md:172-219]()

### DataStream

`DataStream` represents a collection of related files (structures, sequences, compounds, etc.) with:
- **IDs**: List of unique identifiers for each item
- **Files**: Corresponding file paths (or sequences as values)
- **Format**: File format (`pdb`, `cif`, `fasta`, `sdf`, etc.)
- **map_table**: CSV file linking IDs to provenance columns

DataStreams support iteration, indexing, and slicing:

```python
for structure in boltz.streams.structures:
    print(f"{structure.ids[0]}: {structure.files[0]}")
    downstream_tool = SomeTool(structures=structure)
```

**Sources**: [Docs/UserManual.md:176-204]()

### TableInfo

`TableInfo` represents CSV files with metadata:
- **path**: File path to the CSV
- **columns**: List of column names
- **count**: Number of rows
- **Column references**: `table.column_name` returns `TableReference` for per-structure data

Table column references enable metadata-driven parameterization:

```python
rfd = RFdiffusion(contigs="50-100", num_designs=5)
# rfd.tables.structures has column "designed" with residue ranges

lmpnn = LigandMPNN(
    structures=rfd,
    redesigned=rfd.tables.structures.designed  # Per-structure column
)
```

**Sources**: [biopipelines/base_config.py:753-801](), [Docs/UserManual.md:373-391]()

### StreamContainer and TableContainer

These containers provide dot-notation access to named streams and tables:

```python
output.streams.structures  # DataStream
output.streams.sequences   # DataStream
output.tables.confidence   # TableInfo
output.tables.affinity     # TableInfo
```

**Sources**: [biopipelines/base_config.py:924-999](), [biopipelines/base_config.py:1001-1050]()

---

## Combinatorics System

The combinatorics system controls how multiple inputs combine when passed to tools. Two operators define the combination logic:

| Operator | Behavior | Example |
|----------|----------|---------|
| `Each` | Cartesian product (default) | 2 proteins × 3 ligands = 6 predictions |
| `Bundle` | Group as single entity | 2 proteins bundled + 3 ligands = 3 predictions |

```mermaid
graph TB
    subgraph "Each: Cartesian Product"
        P1["Protein A"]
        P2["Protein B"]
        L1["Ligand 1"]
        L2["Ligand 2"]
        
        P1 --> O1["A_1"]
        P1 --> O2["A_2"]
        P2 --> O3["B_1"]
        P2 --> O4["B_2"]
        
        L1 -.-> O1
        L2 -.-> O2
        L1 -.-> O3
        L2 -.-> O4
    end
    
    subgraph "Bundle: Grouped"
        BP1["Protein A"]
        BP2["Protein B"]
        BL1["Ligand 1"]
        BL2["Ligand 2"]
        
        BP1 --> BO1["A+B_1"]
        BL1 -.-> BO1
        
        BP2 -.-> BO1
        
        BP1 --> BO2["A+B_2"]
        BP2 -.-> BO2
        BL2 -.-> BO2
    end
```

**Sources**: [Docs/UserManual.md:327-371]()

### Usage Examples

```python
# Default: Each protein with each ligand (6 predictions)
Boltz2(
    proteins=Each(protein_a, protein_b),
    ligands=Each(ligand1, ligand2, ligand3)
)

# Bundle ligands: Each protein with all ligands together (2 predictions)
Boltz2(
    proteins=Each(protein_a, protein_b),
    ligands=Bundle(ligand1, ligand2, ligand3)
)

# Nested: Each ligand paired with cofactor (3 predictions per protein)
Boltz2(
    proteins=protein_a,
    ligands=Bundle(Each(ligand1, ligand2, ligand3), cofactor)
)
```

**Sources**: [Docs/UserManual.md:336-357]()

### Output ID Naming

Output IDs are always the **full Cartesian product** of all iterated axis IDs, joined with `_`:

- 1 protein (`prot1`) × 3 ligands (`lig1`, `lig2`, `lig3`) → `prot1_lig1`, `prot1_lig2`, `prot1_lig3`
- Even with a single input, the ID is included: `prot1_lig1` (never shortened to `lig1`)

**Sources**: [Docs/UserManual.md:359]()

---

## Provenance Tracking

Every output table includes provenance columns (`{stream_name}.id`) that track which input from each axis produced each output row:

```mermaid
graph LR
    subgraph "Inputs"
        Proteins["proteins<br/>prot1, prot2"]
        Ligands["ligands<br/>lig1, lig2"]
    end
    
    subgraph "Tool"
        Boltz2Tool["Boltz2"]
    end
    
    subgraph "Outputs"
        OutputIDs["Output IDs<br/>prot1_lig1<br/>prot1_lig2<br/>prot2_lig1<br/>prot2_lig2"]
    end
    
    subgraph "Provenance Table"
        Table["confidence.csv<br/>id | sequences.id | compounds.id | plddt<br/>prot1_lig1 | prot1 | lig1 | 0.85<br/>prot1_lig2 | prot1 | lig2 | 0.82<br/>prot2_lig1 | prot2 | lig1 | 0.79<br/>prot2_lig2 | prot2 | lig2 | 0.88"]
    end
    
    Proteins --> Boltz2Tool
    Ligands --> Boltz2Tool
    Boltz2Tool --> OutputIDs
    Boltz2Tool --> Table
```

**Sources**: [Docs/UserManual.md:361-371]()

This enables filtering by input source:

```python
import pandas as pd

df = pd.read_csv(boltz.tables.confidence.info.path)

# Filter for specific protein
prot1_results = df[df['sequences.id'] == 'prot1']

# Filter for specific ligand
lig2_results = df[df['compounds.id'] == 'lig2']
```

**Sources**: [Docs/UserManual.md:363-371]()

---

## Tool Registration and Auto-Chaining

Tools automatically register with the active `Pipeline` context via the `__new__()` method override in `BaseConfig`:

```mermaid
sequenceDiagram
    participant User
    participant Pipeline
    participant BaseConfig
    participant ToolInstance
    participant StandardizedOutput
    
    User->>Pipeline: with Pipeline(...):
    Pipeline->>Pipeline: Set as active pipeline
    
    User->>BaseConfig: RFdiffusion(...)
    Note over BaseConfig: __new__() intercepts instantiation
    
    BaseConfig->>Pipeline: get_active_pipeline()
    Pipeline-->>BaseConfig: Return active pipeline
    
    BaseConfig->>ToolInstance: Create instance
    BaseConfig->>ToolInstance: __init__(...)
    ToolInstance->>ToolInstance: validate_params()
    
    BaseConfig->>Pipeline: _auto_register(instance)
    Pipeline->>ToolInstance: set_pipeline_context(...)
    Pipeline->>ToolInstance: configure_inputs(...)
    Pipeline->>ToolInstance: generate_script(...)
    
    Pipeline->>StandardizedOutput: Create from get_output_files()
    Pipeline-->>BaseConfig: Return StandardizedOutput
    
    BaseConfig-->>User: Return StandardizedOutput
    Note over User: Can chain: tool2 = Tool2(input=tool1)
```

**Sources**: [biopipelines/base_config.py:117-160]()

This design enables:
1. **Declarative syntax**: Tools are instantiated and immediately usable
2. **Automatic dependency tracking**: Inputs are resolved from prior tool outputs
3. **Method chaining**: `StandardizedOutput` can be passed directly to downstream tools
4. **IDE support**: Type hints preserve autocomplete despite runtime transformation

**Sources**: [biopipelines/base_config.py:50-59](), [biopipelines/base_config.py:117-160]()

---

## Filesystem Structure

BioPipelines creates a predictable folder hierarchy:

```
<biopipelines_output>/<project>/<job>_<NNN>/
├── RunTime/              # Generated scripts
│   ├── pipeline.sh       # Master execution script
│   ├── 001_RFdiffusion.sh
│   └── 002_ProteinMPNN.sh
├── Logs/                 # Execution logs
│   ├── 001_RFdiffusion.log
│   └── 002_ProteinMPNN.log
├── ToolOutputs/          # Predicted output metadata (JSON)
│   ├── 001_RFdiffusion.json
│   └── 002_ProteinMPNN.json
├── 001_RFdiffusion/      # Tool outputs
│   ├── .expected_outputs.json
│   ├── .log
│   ├── structures.csv    # map_table with provenance
│   └── *.pdb             # Output structures
└── 002_ProteinMPNN/
    └── ...
```

**Sources**: [Docs/UserManual.md:554-577]()

Each tool folder contains:
- **Output files**: PDB, CIF, FASTA, CSV, etc.
- **map_table CSVs**: Link IDs to files and track provenance
- **.expected_outputs.json**: Metadata for validation and `Load()`
- **Completion markers**: `<NNN>_<Tool>_COMPLETED` or `_WARNING` in parent folder

**Sources**: [biopipelines/base_config.py:499-649]()

---

## Summary

BioPipelines' core architecture separates **configuration** (pure Python prediction) from **execution** (bash + tool logic), enabling:

1. **Predictable file paths**: All outputs known before execution
2. **Composable tools**: Standardized I/O via `StandardizedOutput`
3. **Flexible input combination**: `Each`/`Bundle` combinatorics
4. **Automatic dependency tracking**: Via `Pipeline` context and `__new__()` interception
5. **Provenance preservation**: ID-based tracking through all transformations

The sub-pages provide detailed documentation on each concept:
- [Pipeline Context and Resources](#3.1)
- [Tools and BaseConfig](#3.2)
- [Data Streams and StandardizedOutput](#3.3)
- [Combinatorics: Each and Bundle](#3.4)
- [ID Generation and Provenance Tracking](#3.5)

**Sources**: [Docs/UserManual.md:155-220](), [biopipelines/base_config.py:1-657]()

---