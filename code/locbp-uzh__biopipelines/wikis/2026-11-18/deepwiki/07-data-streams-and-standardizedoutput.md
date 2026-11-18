# Data Streams and StandardizedOutput

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



## Purpose and Scope

BioPipelines uses a **unified I/O system** to standardize how tools communicate. Every tool produces a `StandardizedOutput` object containing **DataStreams** (for file collections like structures, sequences, compounds) and **Tables** (for CSV metrics and metadata). This system enables:

- **Type-safe tool chaining**: Tools know exactly what data types to expect from upstream tools
- **ID-based provenance tracking**: Every output ID traces back to its input sources via `map_table` CSVs
- **Dot-notation access**: Access outputs naturally via `tool.streams.structures` or `tool.tables.confidence`
- **Iteration and slicing**: Iterate over individual items while preserving relationships across streams and tables

For information about how tools produce these outputs, see [Tools and BaseConfig](#3.2). For combinatorics operators that control how multiple inputs combine, see [Combinatorics: Each and Bundle](#3.4).

---

## Data Flow Architecture

The following diagram shows how tools produce and consume `StandardizedOutput` objects:

```mermaid
graph TB
    subgraph "Tool Execution"
        Tool1["Tool (e.g., RFdiffusion)"]
        Tool2["Tool (e.g., ProteinMPNN)"]
        Tool3["Tool (e.g., AlphaFold)"]
    end
    
    subgraph "StandardizedOutput Structure"
        SO1["StandardizedOutput"]
        SC1["StreamContainer<br/>.streams"]
        TC1["TableContainer<br/>.tables"]
        
        DS1["DataStream<br/>name='structures'<br/>ids=['id1', 'id2']<br/>files=[...paths...]<br/>map_table='structures.csv'"]
        
        TI1["TableInfo<br/>name='designed'<br/>path='designed.csv'<br/>columns=['id', 'designed', ...]"]
        
        SO1 --> SC1
        SO1 --> TC1
        SC1 --> DS1
        TC1 --> TI1
    end
    
    subgraph "Usage Patterns"
        Access["Dot Notation:<br/>rfd.streams.structures<br/>rfd.tables.designed"]
        Iteration["Iteration:<br/>for item in rfd:<br/>    process(item)"]
        ColumnRef["Column Reference:<br/>rfd.tables.designed.fixed"]
    end
    
    Tool1 --> SO1
    SO1 --> Access
    SO1 --> Iteration
    SO1 --> ColumnRef
    Access --> Tool2
    ColumnRef --> Tool2
    Tool2 --> Tool3
    
    style SO1 fill:#e1ffe1
    style DS1 fill:#e1f5ff
    style TI1 fill:#fff4e1
```

**Sources**: [biopipelines/base_config.py:1052-1195]()

---

## DataStream: File Collections with ID Tracking

A `DataStream` represents a collection of files (or values) with tracked IDs and provenance. It is the fundamental unit for passing file-based data between tools.

### Structure

| Attribute | Type | Description |
|-----------|------|-------------|
| `name` | `str` | Stream name (e.g., "structures", "sequences", "compounds") |
| `ids` | `List[str]` | List of unique identifiers |
| `files` | `List[str]` | File paths corresponding to each ID (or empty for value-based streams) |
| `format` | `str` | File format ("pdb", "cif", "fasta", "sdf", etc.) |
| `map_table` | `str` | Path to CSV tracking provenance with `{stream_name}.id` columns |

```mermaid
graph LR
    subgraph "DataStream Example"
        DS["DataStream"]
        IDs["ids:<br/>['protein1_lig1',<br/>'protein1_lig2',<br/>'protein2_lig1']"]
        Files["files:<br/>['/path/to/protein1_lig1.pdb',<br/>'/path/to/protein1_lig2.pdb',<br/>'/path/to/protein2_lig1.pdb']"]
        Format["format: 'pdb'"]
        MapTable["map_table:<br/>'structures.csv'"]
    end
    
    DS --> IDs
    DS --> Files
    DS --> Format
    DS --> MapTable
    
    subgraph "structures.csv Contents"
        CSV["id | sequences.id | compounds.id<br/>protein1_lig1 | protein1 | lig1<br/>protein1_lig2 | protein1 | lig2<br/>protein2_lig1 | protein2 | lig1"]
    end
    
    MapTable -.links to.-> CSV
```

**Sources**: [Docs/UserManual.md:176-204](), [biopipelines/base_config.py:1001-1050]()

### Common Stream Types

BioPipelines defines standard stream names accessed via `tool.streams.<name>`:

| Stream Name | Format | Description | Example Tools |
|-------------|--------|-------------|---------------|
| `structures` | `pdb`, `cif`, `pdb\|cif` | Protein/complex structures | RFdiffusion, AlphaFold, Boltz2 |
| `sequences` | CSV with `id`, `sequence` columns | Protein/DNA/RNA sequences | ProteinMPNN, Sequence |
| `compounds` | CSV with `smiles` column, or `sdf`/`pdb` | Small molecules | Ligand, CompoundLibrary |
| `msas` | `a3m`, CSV | Multiple sequence alignments | MMseqs2 |
| `images` | `png`, `jpg`, `svg` | Visualizations | PyMOL, Plot |
| `plots` | `png` | Generated plots | Plot |
| `renders` | `png` | PyMOL renders | PyMOL |

**Sources**: [Docs/UserManual.md:198-204](), [config.yaml:166-187]()

### Iteration Patterns

DataStreams support multiple iteration patterns:

```python
# 1. Iterate over individual items (each is a single-item DataStream)
for structure in boltz.streams.structures:
    print(f"{structure.ids[0]}: {structure.files[0]}")
    # Pass directly to downstream tools
    analysis = SomeTool(structures=structure)

# 2. Count items
num_structures = len(boltz.streams.structures)
print(f"Generated {num_structures} structures")

# 3. Access by index
first_structure = boltz.streams.structures[0]  # Single-item DataStream

# 4. Get all IDs
all_ids = boltz.streams.structures.ids
```

**Sources**: [Docs/UserManual.md:179-196]()

---

## StandardizedOutput: Unified Container

`StandardizedOutput` is the top-level container returned by every tool. It provides unified access to both file-based outputs (streams) and tabular data (tables).

```mermaid
graph TB
    subgraph "StandardizedOutput"
        SO["StandardizedOutput<br/>(returned by tool)"]
        SC["StreamContainer<br/>.streams"]
        TC["TableContainer<br/>.tables"]
    end
    
    subgraph "StreamContainer Contents"
        DS_structures["structures: DataStream"]
        DS_sequences["sequences: DataStream"]
        DS_compounds["compounds: DataStream"]
        DS_msas["msas: DataStream"]
    end
    
    subgraph "TableContainer Contents"
        TI_confidence["confidence: TableInfo"]
        TI_affinity["affinity: TableInfo"]
        TI_results["results: TableInfo"]
    end
    
    SO --> SC
    SO --> TC
    SC --> DS_structures
    SC --> DS_sequences
    SC --> DS_compounds
    SC --> DS_msas
    TC --> TI_confidence
    TC --> TI_affinity
    TC --> TI_results
    
    style SO fill:#e1ffe1
```

### Access Patterns

```python
# Direct stream access
structures = boltz.streams.structures  # DataStream
sequences = boltz.streams.sequences    # DataStream

# Direct table access
confidence = boltz.tables.confidence   # TableInfo
affinity = boltz.tables.affinity       # TableInfo

# Check existence
if boltz.streams.compounds is not None:
    print("Contains compounds")

# Iterate over entire output (all streams must share same IDs)
for item in boltz:
    # Each item is a single-item StandardizedOutput
    print(item.streams.structures.ids[0])  # Same ID across all streams
    downstream_tool = SomeTool(structures=item)
```

**Sources**: [biopipelines/base_config.py:1052-1195](), [Docs/UserManual.md:179-196]()

### Iteration Over StandardizedOutput

When you iterate over a `StandardizedOutput`, each iteration yields a **single-item slice** with the same ID across all streams:

```mermaid
graph LR
    subgraph "Original StandardizedOutput"
        SO1["IDs: [id1, id2, id3]"]
    end
    
    subgraph "Iteration Yields"
        Item1["Item 1<br/>streams.structures.ids = [id1]<br/>streams.sequences.ids = [id1]<br/>tables point to rows where id=id1"]
        Item2["Item 2<br/>streams.structures.ids = [id2]<br/>streams.sequences.ids = [id2]<br/>tables point to rows where id=id2"]
        Item3["Item 3<br/>streams.structures.ids = [id3]<br/>streams.sequences.ids = [id3]<br/>tables point to rows where id=id3"]
    end
    
    SO1 --> Item1
    SO1 --> Item2
    SO1 --> Item3
```

**Sources**: [biopipelines/base_config.py:1126-1195]()

---

## StreamContainer: Named Stream Access

`StreamContainer` provides dot-notation access to named `DataStream` objects.

### Implementation

```mermaid
graph TB
    SC["StreamContainer"]
    Dict["_streams: Dict[str, DataStream]"]
    
    SC --> Dict
    
    subgraph "Dot Notation Attributes"
        Attr1[".structures → DataStream"]
        Attr2[".sequences → DataStream"]
        Attr3[".compounds → DataStream"]
    end
    
    Dict -.creates.-> Attr1
    Dict -.creates.-> Attr2
    Dict -.creates.-> Attr3
```

### Usage

```python
# Access by attribute
structures = tool.streams.structures

# Access by key
structures = tool.streams["structures"]

# Check if stream exists
if "compounds" in tool.streams:
    compounds = tool.streams.compounds

# Iterate over stream names
for name in tool.streams.keys():
    stream = tool.streams[name]
    print(f"{name}: {len(stream)} items")

# Get with default
msas = tool.streams.get("msas", None)
```

**Sources**: [biopipelines/base_config.py:1001-1050]()

---

## TableContainer and TableInfo: CSV Metadata

`TableContainer` holds named `TableInfo` objects, which provide **metadata** about CSV files without loading the full data into memory.

### TableInfo Structure

```mermaid
graph TB
    TI["TableInfo"]
    Meta["TableMetadata<br/>(accessed via .info)"]
    
    TI --> Meta
    
    subgraph "Metadata Fields"
        Name["name: 'confidence'"]
        Path["path: '/path/to/confidence.csv'"]
        Columns["columns: ['id', 'pTM', 'pLDDT', ...]"]
        Desc["description: 'Confidence scores'"]
        Count["count: 100"]
    end
    
    Meta --> Name
    Meta --> Path
    Meta --> Columns
    Meta --> Desc
    Meta --> Count
    
    subgraph "Column References"
        ColRef["Attribute access:<br/>.pTM → TableReference"]
        ColRef2["Enables:<br/>tool.tables.confidence.pTM<br/>→ (path, 'pTM')"]
    end
    
    TI -.provides.-> ColRef
    ColRef --> ColRef2
```

### Access Patterns

```python
# Access metadata via .info
info = boltz.tables.confidence.info
print(info.path)        # /path/to/confidence.csv
print(info.columns)     # ["id", "pTM", "pLDDT", ...]
print(info.count)       # 100

# Column references for downstream tools (see next section)
plddt_ref = boltz.tables.confidence.pLDDT  # TableReference

# Load actual data with pandas
import pandas as pd
df = pd.read_csv(boltz.tables.confidence.info.path)
```

**Sources**: [biopipelines/base_config.py:753-802](), [Docs/UserManual.md:205-218]()

### IndexedTableContainer: Per-ID Tables

Some tools produce **one table per input ID** (e.g., per-structure RMSF, per-trajectory metrics). `IndexedTableContainer` handles this pattern:

```mermaid
graph TB
    ITC["IndexedTableContainer<br/>name='rmsf'"]
    Schema["columns: ['id', 'chain', 'resi', 'rmsf']<br/>description: 'Per-residue RMSF'"]
    
    ITC --> Schema
    
    subgraph "Per-ID Entries"
        E1["'1a2j' → TableInfo<br/>path: '/output/1a2j_RMSF.csv'"]
        E2["'1gfl' → TableInfo<br/>path: '/output/1gfl_RMSF.csv'"]
        E3["'2hhb' → TableInfo<br/>path: '/output/2hhb_RMSF.csv'"]
    end
    
    ITC --> E1
    ITC --> E2
    ITC --> E3
```

**Usage**:

```python
# Access by ID
rmsf_1a2j = cabsflex.tables.rmsf["1a2j"]  # TableInfo
print(rmsf_1a2j.info.path)

# Iterate over all entries
for struct_id, table_info in cabsflex.tables.rmsf:
    df = pd.read_csv(table_info.info.path)
    print(f"{struct_id}: {len(df)} residues")

# Get all IDs
all_ids = cabsflex.tables.rmsf.ids
```

**Sources**: [biopipelines/base_config.py:804-922]()

---

## Table Column References: Metadata-Driven Parameterization

`TableInfo` supports **column references** that enable downstream tools to access per-structure metadata:

```mermaid
graph TB
    subgraph "Upstream Tool: RFdiffusion"
        RFD["RFdiffusion"]
        Table1["tables.structures<br/>columns: ['id', 'designed', 'fixed']"]
    end
    
    subgraph "Column Reference"
        Ref["rfd.tables.structures.designed<br/>→ TableReference(path, 'designed')"]
    end
    
    subgraph "Downstream Tool: LigandMPNN"
        LMPNN["LigandMPNN(structures=rfd,<br/>redesigned=rfd.tables.structures.designed)"]
        Resolution["At execution time:<br/>For each structure ID,<br/>read 'designed' column value"]
    end
    
    RFD --> Table1
    Table1 --> Ref
    Ref --> LMPNN
    LMPNN --> Resolution
```

### Example

```python
# RFdiffusion outputs table with 'designed' column listing designed residues
rfd = RFdiffusion(contigs="50-100", num_designs=5)

# Pass column reference to LigandMPNN
# At runtime, for each structure, the 'designed' value is read from the CSV
lmpnn = LigandMPNN(
    structures=rfd,
    ligand="LIG",
    redesigned=rfd.tables.structures.designed  # Column reference
)

# The reference is a tuple: (TableInfo, "designed")
# Helper scripts resolve it by matching ID and reading the column value
```

**Sources**: [Docs/UserManual.md:373-392](), [biopipelines/biopipelines_io.py]()

---

## ID Tracking and Provenance

Every `DataStream` has an associated **map_table CSV** that tracks provenance through combinatorics axes. This enables filtering and analysis based on which inputs contributed to each output.

### Map Table Structure

When tools use combinatorics (Each/Bundle), the map_table includes `{stream_name}.id` columns:

```mermaid
graph TB
    subgraph "Input Combinatorics"
        Prot["proteins: Each(prot1, prot2)"]
        Lig["ligands: Each(lig1, lig2, lig3)"]
    end
    
    subgraph "Output IDs"
        ID1["prot1_lig1"]
        ID2["prot1_lig2"]
        ID3["prot1_lig3"]
        ID4["prot2_lig1"]
        ID5["prot2_lig2"]
        ID6["prot2_lig3"]
    end
    
    subgraph "structures.csv (map_table)"
        CSV["id | sequences.id | compounds.id | file<br/>prot1_lig1 | prot1 | lig1 | .../prot1_lig1.pdb<br/>prot1_lig2 | prot1 | lig2 | .../prot1_lig2.pdb<br/>prot1_lig3 | prot1 | lig3 | .../prot1_lig3.pdb<br/>prot2_lig1 | prot2 | lig1 | .../prot2_lig1.pdb<br/>prot2_lig2 | prot2 | lig2 | .../prot2_lig2.pdb<br/>prot2_lig3 | prot2 | lig3 | .../prot2_lig3.pdb"]
    end
    
    Prot --> ID1
    Prot --> ID4
    Lig --> ID1
    Lig --> ID2
    Lig --> ID3
    
    ID1 --> CSV
    ID2 --> CSV
    ID3 --> CSV
    ID4 --> CSV
    ID5 --> CSV
    ID6 --> CSV
```

### Provenance Columns

The naming pattern `{stream_name}.id` identifies provenance columns:

| Column | Description |
|--------|-------------|
| `id` | Output ID (always present) |
| `sequences.id` | Which protein/sequence from the input contributed |
| `compounds.id` | Which ligand/compound from the input contributed |
| `structures.id` | Which upstream structure contributed (for multi-stage pipelines) |
| `msas.id` | Which MSA contributed |

**Sources**: [Docs/UserManual.md:359-371]()

### Filtering by Provenance

```python
import pandas as pd

# Load confidence table
df = pd.read_csv(boltz.tables.confidence.info.path)

# Filter results for a specific protein
prot1_results = df[df['sequences.id'] == 'prot1']

# Filter results for a specific ligand
lig2_results = df[df['compounds.id'] == 'lig2']

# Filter for specific protein-ligand pair
specific = df[
    (df['sequences.id'] == 'prot1') & 
    (df['compounds.id'] == 'lig2')
]

# Use Panda tool for filtering within pipeline
filtered = Panda(
    tables=boltz.tables.confidence,
    operations=[Panda.filter("sequences.id == 'prot1'")],
    pool=boltz  # Also copy matching structures
)
```

**Sources**: [Docs/UserManual.md:361-371]()

---

## Complete Data Flow Example

The following example shows how `StandardizedOutput` flows through a multi-tool pipeline:

```mermaid
graph TB
    subgraph "Step 1: Boltz2 Prediction"
        Input1["proteins: Each(prot1, prot2)<br/>ligands: Each(lig1, lig2)"]
        Boltz["Boltz2"]
        Output1["StandardizedOutput<br/>.streams.structures (4 items)<br/>.tables.confidence<br/>.tables.affinity"]
    end
    
    subgraph "Step 2: Distance Analysis"
        Dist["Distance"]
        Output2["StandardizedOutput<br/>.streams.structures (passthrough)<br/>.tables.distances (4 rows)"]
    end
    
    subgraph "Step 3: Panda Filtering"
        Panda["Panda(filter='pLDDT > 0.8')"]
        Output3["StandardizedOutput<br/>.streams.structures (2 items)<br/>.tables.confidence (2 rows)"]
    end
    
    subgraph "Step 4: PyMOL Visualization"
        PyMOL["PyMOL.RenderEach()"]
        Output4["StandardizedOutput<br/>.streams.renders (2 PNGs)"]
    end
    
    Input1 --> Boltz
    Boltz --> Output1
    Output1 --> Dist
    Dist --> Output2
    Output2 --> Panda
    Panda --> Output3
    Output3 --> PyMOL
    PyMOL --> Output4
    
    style Output1 fill:#e1ffe1
    style Output2 fill:#e1ffe1
    style Output3 fill:#e1ffe1
    style Output4 fill:#e1ffe1
```

**Code Example**:

```python
from biopipelines.pipeline import *
from biopipelines.combinatorics import Each

with Pipeline("Example", "DataFlow", "Complete data flow example"):
    Resources(gpu="A100", time="4:00:00")
    
    # Step 1: Predict structures
    proteins = Sequence(["MKTV...", "AETG..."], ids=["prot1", "prot2"])
    ligands = Ligand(["ATP", "GTP"], ids=["lig1", "lig2"])
    
    boltz = Boltz2(
        proteins=Each(proteins),
        ligands=Each(ligands)
    )
    # boltz.streams.structures has 4 items (prot1_lig1, prot1_lig2, prot2_lig1, prot2_lig2)
    # boltz.tables.confidence.info.path points to confidence.csv with provenance columns
    
    # Step 2: Calculate distances
    distances = Distance(
        structures=boltz,
        selection_a="resn LIG",
        selection_b="chain A",
        mode="min"
    )
    # distances.streams.structures is passthrough from boltz
    # distances.tables.distances has min distance for each structure
    
    # Step 3: Filter high-confidence results
    filtered = Panda(
        tables=boltz.tables.confidence,
        operations=[Panda.filter("pLDDT > 0.8")],
        pool=boltz  # Copy matching structures
    )
    # filtered.streams.structures has only structures with pLDDT > 0.8
    
    # Step 4: Render each structure
    renders = PyMOL(
        PyMOL.RenderEach(
            structures=filtered,
            color_protein="plddt",
            color_ligand="byatom"
        )
    )
    # renders.streams.renders has one PNG per filtered structure
```

**Sources**: [Docs/UserManual.md:30-45](), [biopipelines/base_config.py:117-161]()

---

## Summary of Key Classes

| Class | Location | Purpose |
|-------|----------|---------|
| `DataStream` | `biopipelines/datastream.py` | File collection with IDs, files, format, map_table |
| `StandardizedOutput` | `biopipelines/base_config.py:1052-1195` | Top-level container with `.streams` and `.tables` |
| `StreamContainer` | `biopipelines/base_config.py:1001-1050` | Holds named DataStreams with dot notation |
| `TableContainer` | `biopipelines/base_config.py:924-999` | Holds named TableInfo objects with dot notation |
| `TableInfo` | `biopipelines/base_config.py:753-802` | CSV metadata with `.info` and column references |
| `IndexedTableContainer` | `biopipelines/base_config.py:804-922` | Per-ID tables sharing the same schema |
| `TableMetadata` | `biopipelines/base_config.py:738-751` | Metadata fields (name, path, columns, count) |

**Sources**: [biopipelines/base_config.py:738-1195]()

---