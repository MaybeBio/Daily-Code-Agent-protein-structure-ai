# Utilities

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [Docs/Tool/Analysis.md](Docs/Tool/Analysis.md)
- [Docs/Tool/DataManagement.md](Docs/Tool/DataManagement.md)
- [Docs/ToolReference.md](Docs/ToolReference.md)
- [HelpScripts/pipe_ligand.py](HelpScripts/pipe_ligand.py)
- [HelpScripts/pipe_pdb.py](HelpScripts/pipe_pdb.py)
- [HelpScripts/pipe_rfdaa_prepare_ligand.py](HelpScripts/pipe_rfdaa_prepare_ligand.py)
- [HelpScripts/pipe_rfdiffusion3_postprocess.py](HelpScripts/pipe_rfdiffusion3_postprocess.py)
- [HelpScripts/pipe_rfdiffusion3_table.py](HelpScripts/pipe_rfdiffusion3_table.py)
- [HelpScripts/pipe_sequence.py](HelpScripts/pipe_sequence.py)
- [biopipelines/entities.py](biopipelines/entities.py)
- [biopipelines/pdb.py](biopipelines/pdb.py)
- [biopipelines/rcsb.py](biopipelines/rcsb.py)

</details>



Utility tools provide data input and loading functionality for BioPipelines workflows. They fetch, create, or load input entities (structures, sequences, ligands, compounds) that serve as starting points for design and prediction tools. All utility tools output `StandardizedOutput` objects with typed streams (`DataStream`) and tables (`TableInfo`), enabling seamless integration with downstream tools.

For visualization tools (PyMOL, Plot), see [Visualization Tools](#5.7). For data transformation tools (Panda, ReMap, Selection), see [Data Management Tools](#5.6).

---

## Architecture Overview

All utility tools follow a common two-phase execution model: configuration (Python) predicts outputs and generates scripts, execution (Bash) performs actual work via helper scripts.

```mermaid
graph TB
    subgraph "Utility Tool Categories"
        StructInput["Structure Input<br/>PDB, RCSB"]
        SeqInput["Sequence Input<br/>Sequence"]
        LigandInput["Ligand Input<br/>Ligand, CompoundLibrary"]
        MSAInput["MSA Input<br/>MMseqs2"]
        LoadInput["Pipeline Input<br/>Load, LoadMultiple"]
    end
    
    subgraph "Common Output Types"
        Structures["DataStream: structures<br/>.pdb or .cif files"]
        Sequences["DataStream: sequences<br/>.fasta or .csv"]
        Compounds["DataStream: compounds<br/>.pdb/.cif or .sdf"]
        MSAs["DataStream: msas<br/>.a3m files"]
    end
    
    subgraph "Downstream Tools"
        StructGen["Structure Generation<br/>RFdiffusion, BoltzGen"]
        SeqDesign["Sequence Design<br/>ProteinMPNN, LigandMPNN"]
        Prediction["Structure Prediction<br/>AlphaFold, Boltz2"]
    end
    
    StructInput --> Structures
    SeqInput --> Sequences
    LigandInput --> Compounds
    MSAInput --> MSAs
    LoadInput --> Structures
    LoadInput --> Sequences
    LoadInput --> Compounds
    
    Structures --> StructGen
    Structures --> Prediction
    Sequences --> SeqDesign
    Sequences --> Prediction
    Compounds --> StructGen
    Compounds --> Prediction
    MSAs --> Prediction
```

**Sources:** Docs/ToolReference.md:1-98, High-level diagrams (Diagram 1, Diagram 3)

---

## PDB: Structure Fetching

The `PDB` tool fetches protein structures using a priority-based lookup: local folder → repository `PDBs/` folder → RCSB download. Downloads are cached in `PDBs/` for reuse across pipelines.

### Priority-Based Lookup

```mermaid
graph LR
    Request["PDB(pdbs='4UFC')"]
    
    CheckLocal["Check local_folder<br/>(if provided)"]
    CheckRepo["Check PDBs/<br/>(repository cache)"]
    DownloadRCSB["Download from RCSB<br/>data.rcsb.org"]
    
    CacheRepo["Cache to PDBs/"]
    CopyOutput["Copy to ToolOutputs/"]
    
    Success["Return structure path<br/>+ metadata"]
    
    Request --> CheckLocal
    CheckLocal -->|"Not found"| CheckRepo
    CheckLocal -->|"Found"| CopyOutput
    CheckRepo -->|"Not found"| DownloadRCSB
    CheckRepo -->|"Found"| CopyOutput
    DownloadRCSB --> CacheRepo
    CacheRepo --> CopyOutput
    CopyOutput --> Success
```

**Sources:** HelpScripts/pipe_pdb.py:569-628, biopipelines/pdb.py:304-396

### Format Conversion

The `PDB` tool supports flexible format handling via the `convert` parameter:

| `convert` value | Behavior |
|-----------------|----------|
| `None` (default) | Keep whatever format found locally or downloaded (no conversion) |
| `"pdb"` | Convert to PDB format (CIF → PDB if needed) |
| `"cif"` | Convert to CIF format (PDB → CIF not yet implemented) |

CIF to PDB conversion uses BioPython's `MMCIFParser` and `PDBIO`.

**Sources:** HelpScripts/pipe_pdb.py:28-78, biopipelines/pdb.py:109-223

### Operations

PDB supports post-load operations via positional arguments. Currently supports `PDB.Rename(old, new)` for residue renaming.

```python
from biopipelines.pdb import PDB

# Rename ligand residue (useful for RFdiffusion3 compatibility)
pdb = PDB(
    pdbs="rifampicin.pdb",
    PDB.Rename("LIG", ":L:")
)

# Multiple renames
pdb = PDB(
    pdbs="4ufc",
    PDB.Rename("ATP", ":A:"),
    PDB.Rename("GDP", ":G:")
)
```

Operations are applied in sequence after fetching/conversion. The rename operation modifies PDB residue name field (columns 17-19, 0-indexed 17:20).

**Sources:** biopipelines/pdb.py:27-106, HelpScripts/pipe_pdb.py:119-174

### Sequence Extraction

PDB automatically extracts protein sequences from structures. By default, returns the longest chain to avoid inflating memory in downstream tools (multi-chain complexes often contain identical chains).

```python
# Default: longest chain
pdb = PDB(pdbs="4ufc")  # Extracts sequence from longest chain

# Specific chain
pdb = PDB(pdbs="4ufc", chain="A")  # Extract chain A only

# Keep entire structure but extract specific chain sequence
pdb = PDB(pdbs="4ufc", chain="E")  # Sequence from chain E
```

**Sources:** HelpScripts/pipe_pdb.py:279-337, HelpScripts/pipe_pdb.py:339-433

### Ligand Detection

PDB automatically detects ligands (HETATM records excluding waters, ions, crystallization agents) and fetches SMILES strings from RCSB REST API.

**Exclusion list:** HOH, WAT, H2O, SOL, NA, CL, K, CA, MG, ZN, SO4, PO4, GOL, EDO, PEG, ACT, BME, etc.

**Sources:** HelpScripts/pipe_pdb.py:436-567, HelpScripts/pipe_pdb.py:515-566

### Output Specification

```mermaid
graph TB
    PDBTool["PDB tool instance"]
    
    subgraph "Streams"
        S_structures["structures<br/>format: 'pdb' | 'cif' | 'pdb|cif'<br/>map_table: structures.csv"]
        S_sequences["sequences<br/>format: 'csv'<br/>map_table: sequences.csv"]
        S_compounds["compounds<br/>format: 'pdb' | 'cif'<br/>map_table: compounds.csv"]
    end
    
    subgraph "Tables"
        T_structures["structures.csv<br/>id | pdb_id | file_path | format | file_size | source"]
        T_sequences["sequences.csv<br/>id | sequence | length"]
        T_compounds["compounds.csv<br/>id | code | format | smiles | ccd"]
        T_failed["failed_downloads.csv<br/>pdb_id | error_message | source | attempted_path"]
    end
    
    PDBTool --> S_structures
    PDBTool --> S_sequences
    PDBTool --> S_compounds
    
    S_structures -.references.-> T_structures
    S_sequences -.references.-> T_sequences
    S_compounds -.references.-> T_compounds
    PDBTool --> T_failed
```

**Sources:** biopipelines/pdb.py:77-83, HelpScripts/pipe_pdb.py:1445-1513

### Helper Script: pipe_pdb.py

The runtime execution is handled by `pipe_pdb.py`, which implements:

- **Priority lookup logic:** [HelpScripts/pipe_pdb.py:569-628]()
- **RCSB download:** [HelpScripts/pipe_pdb.py:738-930]()
- **CIF→PDB conversion:** [HelpScripts/pipe_pdb.py:28-78]()
- **Water removal:** [HelpScripts/pipe_pdb.py:177-203]()
- **Chain filtering:** [HelpScripts/pipe_pdb.py:206-276]()
- **Sequence extraction:** [HelpScripts/pipe_pdb.py:279-337]()
- **Ligand detection:** [HelpScripts/pipe_pdb.py:436-512]()
- **SMILES fetching:** [HelpScripts/pipe_pdb.py:515-566]()
- **Operations (rename):** [HelpScripts/pipe_pdb.py:97-174]()

**Sources:** HelpScripts/pipe_pdb.py:1-1513

---

## RCSB: Search API Integration

The `RCSB` tool provides programmatic access to the RCSB PDB Search API v2, enabling structure discovery based on text, attributes, sequence similarity, structure similarity, and chemical similarity.

### Query Construction

RCSB uses a typed attribute system via `StructureAttribute` namespace, which mirrors the RCSB advanced search interface:

```python
from biopipelines.rcsb import RCSB, StructureAttribute, PolymerEntityType, SymmetryType

# Attribute-based search
results = RCSB(
    StructureAttribute.NonpolymerFeatures.ComponentIdentifier.is_any("FMN", "FAD"),
    StructureAttribute.PolymerMolecularFeatures.PolymerEntityType.equals(PolymerEntityType.PROTEIN),
    StructureAttribute.AssemblyFeatures.SymmetryType.equals(SymmetryType.ASYMMETRIC),
    StructureAttribute.PolymerMolecularFeatures.PolymerEntitySequenceLength.between(80, 300),
    max_results=100
)
```

### Attribute Categories

```mermaid
graph TB
    StructAttr["StructureAttribute namespace"]
    
    IDsKw["IDsAndKeywords<br/>EntryId, StructureKeywords"]
    Details["StructureDetails<br/>StructureTitle, DepositDate, ReleaseDate"]
    EntryFeat["EntryFeatures<br/>MolecularWeight, NumberOfProteinEntities"]
    PolymerFeat["PolymerMolecularFeatures<br/>PolymerEntityType, SequenceLength, GeneName"]
    NonPolymer["NonpolymerFeatures<br/>ComponentIdentifier, FormulaWeight"]
    Assembly["AssemblyFeatures<br/>SymmetryType, OligomericState"]
    Methods["Methods<br/>ExperimentalMethod, Resolution"]
    
    StructAttr --> IDsKw
    StructAttr --> Details
    StructAttr --> EntryFeat
    StructAttr --> PolymerFeat
    StructAttr --> NonPolymer
    StructAttr --> Assembly
    StructAttr --> Methods
```

**Sources:** biopipelines/rcsb.py:169-252

### Comparison Methods

Each attribute descriptor exposes typed comparison methods:

| Method | Description | Example |
|--------|-------------|---------|
| `equals(value)` | Exact match | `.equals(PolymerEntityType.PROTEIN)` |
| `is_any(*values)` | One of multiple values | `.is_any("FMN", "FAD")` |
| `contains(text)` | Case-insensitive substring | `.contains("kinase")` |
| `contains_phrase(text)` | Exact phrase | `.contains_phrase("insulin receptor")` |
| `between(low, high)` | Numeric/date range | `.between(80, 300)` |
| `greater_than(value)` | Numeric comparison | `.greater_than(2.5)` |
| `less_than(value)` | Numeric comparison | `.less_than(2.0)` |
| `exists()` | Attribute has value | `.exists()` |
| `not_equals(value)` | Negation | `.not_equals(PolymerEntityType.DNA)` |
| `not_any(*values)` | Exclude values | `.not_any("HOH", "WAT")` |

**Sources:** biopipelines/rcsb.py:80-167

### Static Query Constructors

For non-attribute searches, use static methods:

```python
# Text search (full-text)
RCSB(RCSB.Text("insulin receptor + human"), max_results=10)

# Sequence similarity (BLAST-like)
RCSB(RCSB.Sequence("MKTVRQERLK...", identity_cutoff=0.9), max_results=50)

# Structure similarity
RCSB(RCSB.Structure("4HHB", assembly_id=1), max_results=10)

# Sequence motif (PROSITE format)
RCSB(RCSB.SeqMotif("C-x(2,4)-C-x(3)-[LIVMFYWC]-x(8)-H", pattern_type="prosite"))

# Chemical similarity (SMILES-based)
RCSB(RCSB.Chemical("c1ccc(cc1)C(=O)O", match_type="fingerprint-similarity"))
```

**Sources:** biopipelines/rcsb.py:350-467

### Execution Flow

```mermaid
sequenceDiagram
    participant User
    participant RCSBTool["RCSB tool"]
    participant SearchAPI["RCSB Search API v2"]
    participant PipePDB["pipe_pdb.py"]
    participant RCSBFiles["files.rcsb.org"]
    
    User->>RCSBTool: RCSB(query, max_results=100)
    
    rect rgb(230, 245, 255)
        Note over RCSBTool: Configuration Phase
        RCSBTool->>SearchAPI: POST query JSON
        SearchAPI-->>RCSBTool: Return PDB IDs
        RCSBTool->>RCSBTool: Predict output files
        RCSBTool->>RCSBTool: Generate fetch_config.json
    end
    
    rect rgb(255, 245, 230)
        Note over PipePDB: Execution Phase
        RCSBTool->>PipePDB: python pipe_pdb.py --config fetch_config.json
        loop For each PDB ID
            PipePDB->>PipePDB: Check local / PDBs/
            PipePDB->>RCSBFiles: Download if needed
            PipePDB->>PipePDB: Extract sequence, ligands
        end
        PipePDB->>PipePDB: Write structures.csv, sequences.csv
    end
```

**Sources:** biopipelines/rcsb.py:254-721

### Output

RCSB produces identical output to PDB tool:
- **Streams:** `structures`, `sequences`, `compounds`
- **Tables:** `structures.csv`, `sequences.csv`, `compounds.csv`, `failed_downloads.csv`, `search_results.csv`

The `search_results.csv` contains the raw search API response with scores and metadata.

**Sources:** biopipelines/rcsb.py:341-348, biopipelines/rcsb.py:671-721

---

## Ligand: Small Molecule Fetching

The `Ligand` tool fetches small molecules from multiple sources with automatic format detection and 3D coordinate generation.

### Lookup Type Detection

```mermaid
graph TB
    Input["Ligand lookup value"]
    
    DetectType["detect_lookup_type()"]
    
    CCD["CCD code<br/>1-3 uppercase alphanumeric<br/>not purely numeric<br/>Example: ATP, FMN"]
    CID["PubChem CID<br/>purely numeric<br/>Example: 5957"]
    CAS["CAS number<br/>XX-XX-X format<br/>Example: 50-81-7"]
    Name["Compound name<br/>default fallback<br/>Example: 'aspirin'"]
    SMILES["SMILES string<br/>Ligand(smiles='...')"]
    
    Input --> DetectType
    DetectType --> CCD
    DetectType --> CID
    DetectType --> CAS
    DetectType --> Name
    Input --> SMILES
```

**Sources:** HelpScripts/pipe_ligand.py:25-49

### Priority-Based Lookup (Non-SMILES)

Similar to PDB, Ligand uses priority-based file lookup:

1. **local_folder** (if provided)
2. **Ligands/** (repository cache)
3. **RCSB CCD** (for CCD codes) or **PubChem** (for CID/CAS/name)

**Sources:** HelpScripts/pipe_ligand.py:51-83

### SMILES to 3D Conversion

For direct SMILES input or when downloading from PubChem/RCSB returns only SMILES, the tool generates 3D coordinates:

```mermaid
graph TB
    SMILES["SMILES string"]
    
    RDKit["RDKit available?"]
    OpenBabel["OpenBabel available?"]
    
    RDKitConv["convert_smiles_to_pdb_rdkit()<br/>or convert_smiles_to_cif_rdkit()"]
    OBConv["convert_smiles_to_sdf_openbabel()<br/>then sdf_to_pdb()"]
    
    PDB["Output: .pdb or .cif<br/>with 3D coordinates"]
    
    SMILES --> RDKit
    RDKit -->|"Yes"| RDKitConv
    RDKit -->|"No"| OpenBabel
    OpenBabel -->|"Yes"| OBConv
    OpenBabel -->|"No"| Error["Error: No converter available"]
    
    RDKitConv --> PDB
    OBConv --> PDB
```

**RDKit method (preferred):**
- Parse SMILES with `Chem.MolFromSmiles()`
- Add hydrogens: `Chem.AddHs()`
- Generate 3D: `AllChem.EmbedMolecule()` with ETKDG v3
- Optimize: `AllChem.MMFFOptimizeMolecule()`
- Remove hydrogens: `Chem.RemoveHs()`
- Export: `Chem.MolToPDBBlock()` or custom CIF generation

**Important:** RDKit atom naming is preserved for compatibility with tools like RFdiffusion3 that internally regenerate conformers.

**Sources:** HelpScripts/pipe_ligand.py:171-240, HelpScripts/pipe_ligand.py:243-385

### Format Conversion

The `convert` parameter controls output format:

| Value | Behavior |
|-------|----------|
| `None` (default) | Keep source format (PDB or CIF) |
| `"pdb"` | Convert to PDB |
| `"cif"` | Convert to CIF |

CIF output includes explicit bond information via `_chem_comp_bond` category (required by some tools like RFdiffusion3).

**Sources:** HelpScripts/pipe_ligand.py:243-385

### Residue Renaming

Ligand tool automatically renames residue codes to match the `residue_code` parameter:

```python
from biopipelines.ligand import Ligand

# Fetch ATP but rename to :A: for RFdiffusion3
lig = Ligand(ligands="ATP", residue_code=":A:")

# Custom SMILES with custom residue code
lig = Ligand(smiles="CCO", residue_code=":L:")
```

**Sources:** HelpScripts/pipe_ligand.py:388-491, HelpScripts/pipe_ligand.py:494-532

### Output Specification

```mermaid
graph TB
    LigandTool["Ligand tool instance"]
    
    subgraph "Streams"
        S_compounds["compounds<br/>format: 'pdb' | 'cif'<br/>map_table: compounds.csv"]
    end
    
    subgraph "Tables"
        T_compounds["compounds.csv<br/>id | code | format | smiles | ccd | name | formula"]
        T_failed["failed.csv<br/>lookup | error_message | source"]
    end
    
    LigandTool --> S_compounds
    S_compounds -.references.-> T_compounds
    LigandTool --> T_failed
```

**Sources:** HelpScripts/pipe_ligand.py:1240-1320

---

## Sequence: Sequence Creation

The `Sequence` tool creates sequence entities from raw amino acid or nucleotide strings.

### Usage

```python
from biopipelines.sequence import Sequence

# Single sequence
seq = Sequence(sequences="MKTVRQERLK", ids="kinase")

# Multiple sequences
seqs = Sequence(
    sequences=["MKTVRQERLK", "AAAAAAA"],
    ids=["seq1", "seq2"]
)

# Auto-numbering
seqs = Sequence(
    sequences=["MKTVRQERLK", "AAAAAAA"],
    ids="design"  # Outputs: design_1, design_2
)

# Specify type
dna = Sequence(sequences="ATCGATCG", type="dna")
```

### Execution Flow

```mermaid
sequenceDiagram
    participant User
    participant SeqTool["Sequence tool"]
    participant PipeSeq["pipe_sequence.py"]
    
    User->>SeqTool: Sequence(sequences=["MKTVR..."], ids=["seq1"])
    
    rect rgb(230, 245, 255)
        Note over SeqTool: Configuration Phase
        SeqTool->>SeqTool: Validate sequences (amino acid alphabet)
        SeqTool->>SeqTool: Predict IDs (auto-number if needed)
        SeqTool->>SeqTool: Generate config JSON
    end
    
    rect rgb(255, 245, 230)
        Note over PipeSeq: Execution Phase
        SeqTool->>PipeSeq: python pipe_sequence.py --config config.json
        PipeSeq->>PipeSeq: Read sequences from config
        PipeSeq->>PipeSeq: Clean whitespace
        PipeSeq->>PipeSeq: Write sequences.csv
        PipeSeq->>PipeSeq: Write sequences.fasta (80 char lines)
    end
```

**Sources:** HelpScripts/pipe_sequence.py:1-124

### Output

- **DataStream:** `sequences` (format: `"csv"`, map_table: `"sequences.csv"`)
- **TableInfo:** `sequences.csv` with columns: `id`, `sequence`, `type`, `length`
- **File:** `sequences.fasta` (FASTA format, not exposed as DataStream)

**Sources:** HelpScripts/pipe_sequence.py:20-80

---

## CompoundLibrary: Compound Collections

The `CompoundLibrary` tool creates collections of small molecules, either from explicit lists or from compound libraries (e.g., fragment libraries, drug-like compounds).

### Usage

```python
from biopipelines.compound_library import CompoundLibrary

# From explicit SMILES list
library = CompoundLibrary(
    smiles=["CCO", "c1ccccc1", "CC(=O)O"],
    ids=["ethanol", "benzene", "acetate"]
)

# From library name (predefined collections)
library = CompoundLibrary(library="fragments")

# With filters
library = CompoundLibrary(
    library="drugbank",
    mw_range=(200, 500),
    logp_range=(-1, 5)
)
```

### Output

Similar to Ligand tool:
- **DataStream:** `compounds` (3D structures as PDB/CIF)
- **TableInfo:** `compounds.csv` with SMILES, molecular properties

---

## Load / LoadMultiple: Pipeline Output Reuse

The `Load` and `LoadMultiple` tools enable reusing outputs from previous pipeline runs.

### Load: Single Tool Output

```python
from biopipelines.load import Load

# Load by job name
previous = Load(job="MyPreviousJob", tool="RFdiffusion", batch=1)

# Load by absolute path
previous = Load(folder="/path/to/ToolOutputs/Job_Tool_batch1")

# Access streams
previous.streams.structures
previous.tables.results
```

### LoadMultiple: Multiple Outputs

```python
from biopipelines.load import LoadMultiple

# Load multiple batches
all_batches = LoadMultiple(
    job="MyJob",
    tool="ProteinMPNN",
    batches=[1, 2, 3]
)

# Access merged streams
all_batches.streams.sequences  # All sequences combined
```

### Implementation

Load tools read the `ToolOutputs/` directory structure and reconstruct `StandardizedOutput` objects by parsing CSV files and discovering file streams.

---

## MMseqs2: Distributed MSA Generation

The `MMseqs2` tool generates Multiple Sequence Alignments via a client-server architecture that supports GPU acceleration and automatic server management.

### Client-Server Architecture

```mermaid
graph TB
    subgraph "Pipeline Execution"
        MMseqs2Tool["MMseqs2 tool instance"]
        PipeMMseqs2["pipe_mmseqs2_sequences.py<br/>(client script)"]
    end
    
    subgraph "Shared Server Folder"
        Queue["Queue/<br/>*.fasta (input sequences)"]
        Results["Results/<br/>*.a3m (MSA outputs)"]
        Status["Status/<br/>*.status (job tracking)"]
        ServerLock["server.lock<br/>(server PID)"]
    end
    
    subgraph "MMseqs2 Server"
        ServerScript["mmseqs2_server_gpu.sh<br/>or mmseqs2_server_cpu.sh"]
        MMseqs2Bin["mmseqs binary<br/>easy-search or createdb"]
    end
    
    MMseqs2Tool -->|"generate_script()"| PipeMMseqs2
    PipeMMseqs2 -->|"Submit .fasta"| Queue
    PipeMMseqs2 -->|"Poll status"| Status
    Status -.->|"Monitor"| PipeMMseqs2
    
    ServerScript -->|"Watch"| Queue
    Queue -->|"Pick up jobs"| ServerScript
    ServerScript -->|"Run"| MMseqs2Bin
    MMseqs2Bin -->|"Write"| Results
    ServerScript -->|"Update"| Status
    
    Results -->|"Download when complete"| PipeMMseqs2
    
    PipeMMseqs2 -->|"Check server.lock"| ServerLock
    PipeMMseqs2 -->|"Auto-restart if dead"| ServerScript
```

**Sources:** High-level diagram (Diagram 5)

### Server Management

The client script automatically manages the server:

1. **Check server health:** Read `server.lock` for PID, verify process exists
2. **Start server if needed:** Submit SLURM job with `mmseqs2_server_gpu.sh`
3. **Submit jobs:** Write FASTA to `Queue/`
4. **Poll for completion:** Check `Status/*.status` files
5. **Download results:** Copy from `Results/*.a3m`

**Auto-restart logic:** If server PID is stale (process doesn't exist), client resubmits server job.

### MSA Masking

MMseqs2 tool supports masking specific regions during MSA search to prevent bias:

```python
from biopipelines.mmseqs2 import MMseqs2

# Mask designed regions (only search fixed scaffold)
msas = MMseqs2(
    sequences=designs,
    mask_regions=designs.tables.structures.designed  # Column reference
)
```

Masked regions are converted to 'X' during search, then restored in output MSAs.

### Output

- **DataStream:** `msas` (format: `"a3m"`, map_table: `"msas.csv"`)
- **TableInfo:** `msas.csv` with columns: `id`, `file`, `num_sequences`, `coverage`

**Sources:** High-level diagram (Diagram 5), MMseqs2 section

---

## Helper Script Patterns

All utility tools follow a common helper script pattern:

```mermaid
graph TB
    ToolClass["Tool class<br/>(e.g., PDB, Ligand)"]
    
    GenConfig["generate_script()<br/>Write config JSON"]
    GenBash["generate_script()<br/>Write bash wrapper"]
    
    ConfigJSON["config.json<br/>{ids, params, folders}"]
    BashScript["tool.sh<br/>Activate env + run helper"]
    
    HelperScript["pipe_*.py<br/>(e.g., pipe_pdb.py)"]
    
    ReadConfig["Read config JSON"]
    ProcessData["Process data<br/>(download, convert, extract)"]
    WriteOutputs["Write CSV tables + files"]
    
    ToolClass --> GenConfig
    ToolClass --> GenBash
    GenConfig --> ConfigJSON
    GenBash --> BashScript
    
    BashScript -->|"Execute"| HelperScript
    HelperScript --> ReadConfig
    ReadConfig --> ProcessData
    ProcessData --> WriteOutputs
    
    ConfigJSON -.->|"Read"| ReadConfig
```

**Configuration JSON** contains all parameters needed for execution (IDs, source paths, conversion settings, etc.)

**Bash wrapper** activates the appropriate conda/mamba environment and invokes the Python helper script.

**Helper script** reads config, performs the actual work (fetching, conversion, parsing), and writes standardized outputs.

**Sources:** HelpScripts/pipe_pdb.py:1445-1513, HelpScripts/pipe_ligand.py:1240-1320, HelpScripts/pipe_sequence.py:83-123

---

## Summary

Utility tools provide typed, reusable data input for BioPipelines workflows:

| Tool | Primary Purpose | Key Feature |
|------|-----------------|-------------|
| **PDB** | Fetch structures | Priority-based lookup, format conversion, operations |
| **RCSB** | Search & download | Advanced search API, typed attributes, query composition |
| **Ligand** | Fetch ligands | Multi-source lookup, SMILES→3D conversion, residue renaming |
| **Sequence** | Create sequences | Simple string→FASTA/CSV conversion |
| **CompoundLibrary** | Compound collections | Library support, property filtering |
| **Load/LoadMultiple** | Reuse outputs | Read previous pipeline results |
| **MMseqs2** | Generate MSAs | Client-server, GPU acceleration, masking |

All produce `StandardizedOutput` with typed streams and tables for seamless downstream integration.

---