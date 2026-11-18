# ID Generation and Provenance Tracking

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [Docs/UserManual.md](Docs/UserManual.md)
- [HelpScripts/pipe_boltz_config_unified.py](HelpScripts/pipe_boltz_config_unified.py)
- [HelpScripts/pipe_boltz_postprocessing.py](HelpScripts/pipe_boltz_postprocessing.py)
- [HelpScripts/pipe_stitch_sequences.py](HelpScripts/pipe_stitch_sequences.py)
- [biopipelines/boltz2.py](biopipelines/boltz2.py)
- [biopipelines/combinatorics.py](biopipelines/combinatorics.py)
- [biopipelines/id_map_utils.py](biopipelines/id_map_utils.py)
- [config.yaml](config.yaml)

</details>



This page explains how BioPipelines systematically generates unique IDs for pipeline outputs and tracks their provenance across multi-axis combinatorics. Understanding these mechanisms is essential for filtering results, joining tables, and debugging ID mismatches.

For combinatorics control (Each/Bundle operators), see [Combinatorics: Each and Bundle](#3.4). For using provenance columns in Panda operations, see [Data Management Tools](#5.6).

---

## ID Generation Fundamentals

BioPipelines generates output IDs at **configuration time** (Python execution) by predicting the cartesian product structure from combinatorics modes. The same IDs are then regenerated at **execution time** (bash script) using identical logic to ensure consistency.

### Multi-Axis Naming Convention

Output IDs are constructed by joining component IDs from all iterated axes using the **`+` separator**:

```
protein1+ligand1
protein1+ligand2
protein2+ligand1
protein2+ligand2
```

**Why `+` instead of `_`?** The `_` separator is reserved for parent→child suffix relationships (e.g., `protein_1`, `protein_2`). Using `+` for multi-axis combinations ensures that suffix-stripping algorithms (`*_<S>` pattern) can distinguish between axes and generations.

**Sources:** [biopipelines/combinatorics.py:520-662](), [biopipelines/id_map_utils.py:184-291]()

### Suffix Patterns for Tool Outputs

When a tool generates multiple outputs per input (e.g., ProteinMPNN generating 10 sequences per structure), child IDs append numeric suffixes:

```
protein → protein_1, protein_2, ..., protein_10
```

Non-numeric suffixes are also supported (e.g., `protein_19A` for mutations at position 19).

**Default ID mapping pattern:** `{"*": "*_<S>"}` — recursively strips any `_suffix` pattern:
- `protein_1_2_3` → `protein_1_2` → `protein_1` → `protein`

**Sources:** [biopipelines/combinatorics.py:752-790](), [biopipelines/id_map_utils.py:130-182]()

---

## Configuration-Time ID Prediction

### The `predict_output_ids_with_provenance()` Function

[biopipelines/combinatorics.py:518-662]() implements the core ID prediction algorithm. It returns both output IDs and provenance mappings.

```mermaid
graph TB
    subgraph "Input Axes (kwargs)"
        Proteins["proteins=(prot_source, 'sequences')"]
        Ligands["ligands=(lig_source, 'compounds')"]
    end
    
    subgraph "Unpacking & Analysis"
        Unpack["_unpack_input()<br/>(value, stream_name, entity_type)"]
        Unwrap["_unwrap_sources()<br/>(mode, sources list)"]
        CollectIDs["_collect_iterated_ids_from_value()<br/>Extract IDs from DataStreams"]
    end
    
    subgraph "Axis Classification"
        Iterated["Iterated axes<br/>(Each or Bundle w/ nested Each)"]
        PureBundle["Pure bundle axes<br/>(Bundle w/o nested Each)"]
    end
    
    subgraph "Cartesian Product"
        FirstAxis["Start with first axis IDs"]
        IterateAxes["For each additional axis:<br/>new_ids = existing × axis_ids<br/>joined with '+'"]
        ApplyStatic["Apply static IDs from<br/>Bundle(Each(...), static)"]
    end
    
    subgraph "Output"
        OutputIDs["output_ids: List[str]"]
        Provenance["provenance: Dict[str, List[str]]<br/>{axis_name: [parent_id per output]}"]
    end
    
    Proteins --> Unpack
    Ligands --> Unpack
    Unpack --> Unwrap
    Unwrap --> CollectIDs
    CollectIDs --> Iterated
    CollectIDs --> PureBundle
    
    Iterated --> FirstAxis
    PureBundle --> FirstAxis
    FirstAxis --> IterateAxes
    IterateAxes --> ApplyStatic
    ApplyStatic --> OutputIDs
    ApplyStatic --> Provenance
```

**Sources:** [biopipelines/combinatorics.py:518-662](), [biopipelines/combinatorics.py:147-173]()

### Example: Two Proteins × Three Ligands

```python
# Configuration time
from biopipelines.combinatorics import predict_output_ids_with_provenance

output_ids, provenance = predict_output_ids_with_provenance(
    proteins=(prot_source, "sequences"),  # prot1, prot2
    ligands=(lig_source, "compounds")      # lig1, lig2, lig3
)

# Result:
output_ids = [
    "prot1+lig1", "prot1+lig2", "prot1+lig3",
    "prot2+lig1", "prot2+lig2", "prot2+lig3"
]

provenance = {
    "proteins": ["prot1", "prot1", "prot1", "prot2", "prot2", "prot2"],
    "ligands":  ["lig1", "lig2", "lig3", "lig1", "lig2", "lig3"]
}
```

**Sources:** [Docs/UserManual.md:359-370]()

---

## Execution-Time ID Generation

Helper scripts regenerate IDs at runtime using `predict_single_output_id()` [biopipelines/combinatorics.py:688-750](). This function takes axis selections (which items were chosen in the current iteration) and produces the same ID that configuration-time prediction would generate.

```mermaid
graph LR
    subgraph "Configuration Time (Python)"
        ConfigPredict["predict_output_ids_with_provenance()<br/>Returns all expected IDs + provenance"]
        WriteConfig["Write combinatorics_config.json<br/>with axes, predicted_ids, provenance"]
    end
    
    subgraph "Execution Time (Bash/Python)"
        LoadConfig["Load combinatorics_config.json"]
        IterateLoops["for each combination in<br/>cartesian product:"]
        RuntimePredict["predict_single_output_id(<br/>  proteins=('each', ['prot1','prot2'], idx=0, [], False),<br/>  ligands=('each', ['lig1','lig2','lig3'], idx=1, [], False)<br/>)"]
        GenerateID["Returns 'prot1+lig2'"]
    end
    
    ConfigPredict --> WriteConfig
    WriteConfig --> LoadConfig
    LoadConfig --> IterateLoops
    IterateLoops --> RuntimePredict
    RuntimePredict --> GenerateID
    
    style RuntimePredict fill:#f0f0f0
    style ConfigPredict fill:#f0f0f0
```

**Sources:** [biopipelines/combinatorics.py:688-750](), [HelpScripts/pipe_boltz_config_unified.py:653-656]()

### Axis Selection Tuple Format

`predict_single_output_id()` receives axis selections as named kwargs where each value is:

```python
(mode, all_ids, selected_idx, static_ids, static_first)
```

| Field | Type | Description |
|-------|------|-------------|
| `mode` | str | `"each"` or `"bundle"` |
| `all_ids` | List[str] | All IDs available on this axis |
| `selected_idx` | Optional[int] | Index of chosen ID (None for bundle) |
| `static_ids` | List[str] | Static IDs from Bundle(Each(...), static) |
| `static_first` | bool | Whether static IDs come before iterated |

**Sources:** [biopipelines/combinatorics.py:688-750]()

---

## Provenance Tracking System

Provenance columns enable downstream tools to filter and join results by tracking which input from each axis produced each output.

### Provenance Column Naming

For each named input axis, BioPipelines adds a `{axis_name}.id` column to output tables:

```csv
id,file,proteins.id,ligands.id,confidence_score
prot1+lig1,prot1+lig1.pdb,prot1,lig1,0.85
prot1+lig2,prot1+lig2.pdb,prot1,lig2,0.79
prot2+lig1,prot2+lig1.pdb,prot2,lig1,0.91
```

**Usage example:**

```python
import pandas as pd

# Filter Boltz2 results for a specific protein
df = pd.read_csv(boltz.tables.confidence.info.path)
prot1_results = df[df['proteins.id'] == 'prot1']

# Filter for a specific ligand
lig2_results = df[df['ligands.id'] == 'lig2']
```

**Sources:** [Docs/UserManual.md:361-370](), [HelpScripts/pipe_boltz_postprocessing.py:242-251]()

### Map Tables and Provenance Storage

Map tables (`.csv` files with `id`, `file`, `value` columns) serve as the canonical storage for provenance:

```mermaid
graph TB
    subgraph "Configuration Time"
        PredictProv["predict_output_ids_with_provenance()<br/>returns (output_ids, provenance)"]
        WriteMapTable["create_map_table()<br/>Write structures_map.csv<br/>with id, file, {axis}.id columns"]
        WriteCombConfig["Save combinatorics_config.json<br/>with provenance dict"]
    end
    
    subgraph "Map Table Structure"
        MapCSV["structures_map.csv<br/>┌────────────┬──────────────┬────────────┬────────────┐<br/>│ id         │ file         │ proteins.id│ ligands.id │<br/>├────────────┼──────────────┼────────────┼────────────┤<br/>│ prot1+lig1 │ prot1+lig1...│ prot1      │ lig1       │<br/>│ prot1+lig2 │ prot1+lig2...│ prot1      │ lig2       │<br/>└────────────┴──────────────┴────────────┴────────────┘"]
    end
    
    subgraph "Execution Time"
        PostProcess["pipe_boltz_postprocessing.py<br/>Load provenance from<br/>combinatorics_config.json"]
        AddProvCols["Add provenance columns to<br/>confidence.csv, affinity.csv"]
    end
    
    PredictProv --> WriteMapTable
    PredictProv --> WriteCombConfig
    WriteMapTable --> MapCSV
    WriteCombConfig --> PostProcess
    PostProcess --> AddProvCols
    
    style MapCSV fill:#f9f9f9
```

**Sources:** [biopipelines/datastream.py:create_map_table](), [HelpScripts/pipe_boltz_postprocessing.py:60-72](), [HelpScripts/pipe_boltz_postprocessing.py:272-310]()

### Provenance in Combinatorics Config

The `combinatorics_config.json` file stores predicted IDs and provenance for use by helper scripts:

```json
{
  "axes": {
    "proteins": {
      "name": "proteins",
      "mode": "each",
      "sources": [{"path": "proteins.csv", "iterate": true}],
      "entity_type": "protein"
    },
    "ligands": {
      "name": "ligands",
      "mode": "each",
      "sources": [{"path": "ligands.csv", "iterate": true}],
      "entity_type": "ligand"
    }
  },
  "predicted_ids": [
    "prot1+lig1", "prot1+lig2", "prot1+lig3",
    "prot2+lig1", "prot2+lig2", "prot2+lig3"
  ],
  "provenance": {
    "proteins": ["prot1", "prot1", "prot1", "prot2", "prot2", "prot2"],
    "ligands": ["lig1", "lig2", "lig3", "lig1", "lig2", "lig3"]
  }
}
```

**Sources:** [biopipelines/combinatorics.py:84-124](), [biopipelines/combinatorics.py:313-325]()

---

## ID Mapping and Lookup

When a tool consumes outputs from upstream tools, it must match IDs between datasets. BioPipelines uses **pattern-based ID mapping** with recursive suffix stripping.

### ID Mapping Pattern Syntax

ID mapping patterns use the format `{"*": "<pattern>"}` where `*` represents the base ID:

| Pattern | Meaning | Example |
|---------|---------|---------|
| `{"*": "*"}` | Identity (no mapping) | `protein_1` → `protein_1` |
| `{"*": "*_<S>"}` | Strip any `_suffix` recursively (DEFAULT) | `protein_1_19A` → `protein_1` → `protein` |
| `{"*": "*_<N>"}` | Strip numeric `_123` suffixes only | `protein_1_2` → `protein_1` → `protein` |
| `{"*": "*-seq-<N>"}` | Strip specific pattern | `protein-seq-42` → `protein` |

**`<N>` placeholder:** Matches one or more digits (`\d+`)  
**`<S>` placeholder:** Matches any non-underscore segment (`[^_]+`)

**Sources:** [biopipelines/id_map_utils.py:13-46](), [biopipelines/id_map_utils.py:53-128]()

### Recursive Suffix Stripping

The `map_table_ids_to_ids()` function [biopipelines/id_map_utils.py:188-291]() generates all candidate IDs by recursively stripping suffixes:

```python
from biopipelines.id_map_utils import map_table_ids_to_ids

# Default pattern: {"*": "*_<S>"}
candidates = map_table_ids_to_ids("protein_1_19A", {"*": "*_<S>"})
# Returns: ['protein_1_19A', 'protein_1', 'protein']

# Multi-axis expansion: "+" components are also candidates
candidates = map_table_ids_to_ids("prot1+lig1_2", {"*": "*_<S>"})
# Returns: ['prot1+lig1_2', 'prot1+lig1', 'prot1', 'lig1_2', 'lig1']
```

**Why multi-axis expansion?** This allows tools to match `prot1+lig1` against tables containing either `prot1` or `lig1` without requiring provenance columns.

**Sources:** [biopipelines/id_map_utils.py:188-291](), [biopipelines/id_map_utils.py:274-289]()

### Priority-Based Matching with `get_mapped_ids()`

[biopipelines/id_map_utils.py:340-534]() implements a priority-based matching strategy:

```mermaid
graph TB
    Input["get_mapped_ids(<br/>  source_ids=['prot1_1'],<br/>  target_ids=['prot1', 'prot1_2'],<br/>  id_map={'*': '*_&lt;S&gt;'},<br/>  map_table_paths=[...]<br/>)"]
    
    Priority1["Priority 1: Exact Match<br/>source_id == target_id?"]
    Priority2["Priority 2: Provenance Match<br/>Check map_table {axis}.id columns"]
    
    BuildCandidates["Build candidate IDs:<br/>• source_id<br/>• + provenance identities<br/>  from map_tables"]
    
    Priority3a["Priority 3a: Child Match<br/>target = candidate + suffix<br/>(e.g., prot1 → prot1_2)"]
    Priority3b["Priority 3b: Parent Match<br/>candidate = target + suffix<br/>(e.g., prot1_1 → prot1)"]
    
    Priority4["Priority 4: Sibling Match<br/>Common ancestor<br/>(e.g., prot1_1 ↔ prot1_2)"]
    
    NoMatch["Return None"]
    ReturnMatch["Return matched target_id"]
    
    Input --> Priority1
    Priority1 -->|Found| ReturnMatch
    Priority1 -->|Not Found| Priority2
    Priority2 -->|Found| ReturnMatch
    Priority2 -->|Not Found| BuildCandidates
    
    BuildCandidates --> Priority3a
    Priority3a -->|Found| ReturnMatch
    Priority3a -->|Not Found| Priority3b
    Priority3b -->|Found| ReturnMatch
    Priority3b -->|Not Found| Priority4
    Priority4 -->|Found| ReturnMatch
    Priority4 -->|Not Found| NoMatch
```

**Matching priority order:**

1. **Exact match:** `source_id == target_id` (highest priority)
2. **Provenance match:** Check `{axis}.id` columns in map_table CSVs (most reliable)
3. **For each candidate** (source_id + provenance identities):
   - **Child match:** Target derives from candidate (`target = candidate + suffix`)
   - **Parent match:** Candidate derives from target (`candidate = target + suffix`)
4. **Sibling match:** Common ancestor (both derive from same base)

**Sources:** [biopipelines/id_map_utils.py:340-534](), [biopipelines/id_map_utils.py:294-337]()

### Provenance-Based Matching

When suffix-based matching fails (e.g., Panda auto-renamed IDs like `Panda_1`), `get_mapped_ids()` falls back to provenance columns in map_tables:

```python
# Panda renamed "LID_001_1" to "Panda_1"
# Panda's map_table preserves provenance:
# id,file,structures.id
# Panda_1,Panda_1.pdb,LID_001_1

get_mapped_ids(
    source_ids=["Panda_1"],
    target_ids=["LID_001_1"],
    map_table_paths=["path/to/Panda/map.csv"]
)
# Returns: {'Panda_1': 'LID_001_1'}  (via provenance column)
```

**Sources:** [biopipelines/id_map_utils.py:437-445](), [biopipelines/biopipelines_io.py:resolve_id_by_provenance]()

---

## Multiplied ID Generation

Some tools multiply inputs (e.g., ProteinMPNN generating 10 sequences per structure). The `generate_multiplied_ids()` function [biopipelines/combinatorics.py:752-790]() handles this:

```python
from biopipelines.combinatorics import generate_multiplied_ids

output_ids, provenance = generate_multiplied_ids(
    input_ids=["prot_1", "prot_2"],
    suffixes=["1", "2", "3"],
    input_stream_name="structures"
)

# Returns:
output_ids = [
    "prot_1_1", "prot_1_2", "prot_1_3",
    "prot_2_1", "prot_2_2", "prot_2_3"
]

provenance = {
    "structures": ["prot_1", "prot_1", "prot_1", 
                   "prot_2", "prot_2", "prot_2"]
}
```

**Pattern-based variant:** `generate_multiplied_ids_pattern()` [biopipelines/combinatorics.py:793-815]() composes ID patterns without expanding them (used when suffixes are dynamic).

**Sources:** [biopipelines/combinatorics.py:752-790](), [biopipelines/combinatorics.py:793-815]()

---

## StitchSequences Special Case

The `StitchSequences` tool demonstrates complex ID generation with template-substitution matching. IDs are constructed from:

1. Template ID (base)
2. Substitution source IDs
3. Indel source IDs

```python
# Example: template "prot1" + substitution from "sub1" + indel from "ind1"
# Output ID: "prot1_1_1"
#            └─┬─┘ │ │
#              │   │ └─ indel index (1st option)
#              │   └─── substitution index (1st option)
#              └─────── template ID
```

For raw (non-ToolOutput) substitutions/indels with fixed positions, all templates get the full cartesian product of options. For ToolOutput substitutions with dynamic positions, matching uses `get_mapped_ids()` to pair templates with substitution sequences by base ID.

**Sources:** [HelpScripts/pipe_stitch_sequences.py:523-596](), [HelpScripts/pipe_stitch_sequences.py:599-786]()

---

## Implementation Code Entities

### Key Functions

| Function | Location | Purpose |
|----------|----------|---------|
| `predict_output_ids_with_provenance()` | [biopipelines/combinatorics.py:518-662]() | Configuration-time ID and provenance prediction |
| `predict_single_output_id()` | [biopipelines/combinatorics.py:688-750]() | Execution-time single ID generation |
| `generate_multiplied_ids()` | [biopipelines/combinatorics.py:752-790]() | Generate parent→child IDs with provenance |
| `map_table_ids_to_ids()` | [biopipelines/id_map_utils.py:188-291]() | Recursive suffix stripping with multi-axis expansion |
| `get_mapped_ids()` | [biopipelines/id_map_utils.py:340-534]() | Priority-based ID matching with provenance fallback |
| `parse_id_map_pattern()` | [biopipelines/id_map_utils.py:53-128]() | Parse ID mapping pattern to regex |
| `create_map_table()` | [biopipelines/datastream.py]() | Write map_table CSV with provenance columns |

### Key Classes and Data Structures

| Entity | Location | Purpose |
|--------|----------|---------|
| `CombinatoricsConfig` | [biopipelines/combinatorics.py:84-145]() | Dataclass storing axes, predicted_ids, provenance |
| `AxisConfig` | [biopipelines/combinatorics.py:66-81]() | Single axis configuration (name, mode, sources, entity_type) |
| `Each` | [biopipelines/combinatorics.py:37-48]() | Wrapper marking input for iteration |
| `Bundle` | [biopipelines/combinatorics.py:51-62]() | Wrapper grouping inputs as one entity |

**Sources:** [biopipelines/combinatorics.py:1-815](), [biopipelines/id_map_utils.py:1-598]()

---

## Provenance Flow Diagram

```mermaid
graph TB
    subgraph "Tool Configuration (Python)"
        ToolInit["Tool.__init__()<br/>Store raw inputs:<br/>proteins, ligands, etc."]
        BuildKwargs["_build_combinatorics_kwargs()<br/>Format as (value, stream, entity_type)"]
        WriteCombConfig["_write_combinatorics_config()<br/>generate_combinatorics_config()"]
        PredictIDs["predict_output_ids_with_provenance()<br/>Returns (ids, provenance)"]
        CreateMapTable["create_map_table()<br/>Write structures_map.csv<br/>with provenance columns"]
    end
    
    subgraph "Combinatorics Config JSON"
        ConfigJSON["combinatorics_config.json<br/>{<br/>  'axes': {...},<br/>  'predicted_ids': [...],<br/>  'provenance': {<br/>    'proteins': [...],<br/>    'ligands': [...]<br/>  }<br/>}"]
    end
    
    subgraph "Execution (Bash + Python)"
        HelpScript["pipe_boltz_config_unified.py<br/>Load combinatorics_config.json"]
        IterateProduct["Iterate cartesian product:<br/>for combo in product(*axes):"]
        RuntimeID["predict_single_output_id(<br/>  proteins=('each', ids, idx, ...),<br/>  ligands=('each', ids, idx, ...)<br/>)"]
        WriteYAML["Write Boltz2 YAML configs<br/>with predicted ID as filename"]
        Boltz2Run["boltz predict config.yaml<br/>Outputs: boltz_results_{id}/"]
    end
    
    subgraph "Post-Processing"
        PostProc["pipe_boltz_postprocessing.py"]
        LoadProvenance["Load provenance from<br/>combinatorics_config.json"]
        RenameFiles["Rename structures:<br/>config_id → sequence_id<br/>using folder_to_sequence_map"]
        AddProvCols["Add provenance columns to:<br/>• confidence_scores.csv<br/>• affinity_scores.csv<br/>• structures_map.csv"]
    end
    
    subgraph "Final Outputs"
        ConfCSV["confidence_scores.csv<br/>id, proteins.id, ligands.id, pTM, ..."]
        MapCSV["structures_map.csv<br/>id, file, proteins.id, ligands.id"]
    end
    
    ToolInit --> BuildKwargs
    BuildKwargs --> WriteCombConfig
    WriteCombConfig --> PredictIDs
    PredictIDs --> CreateMapTable
    WriteCombConfig --> ConfigJSON
    
    ConfigJSON --> HelpScript
    HelpScript --> IterateProduct
    IterateProduct --> RuntimeID
    RuntimeID --> WriteYAML
    WriteYAML --> Boltz2Run
    
    Boltz2Run --> PostProc
    ConfigJSON --> LoadProvenance
    LoadProvenance --> AddProvCols
    PostProc --> RenameFiles
    RenameFiles --> AddProvCols
    
    AddProvCols --> ConfCSV
    CreateMapTable --> MapCSV
    AddProvCols --> MapCSV
```

**Sources:** [biopipelines/boltz2.py:302-323](), [HelpScripts/pipe_boltz_config_unified.py:710-720](), [HelpScripts/pipe_boltz_postprocessing.py:60-72](), [HelpScripts/pipe_boltz_postprocessing.py:236-253](), [HelpScripts/pipe_boltz_postprocessing.py:272-310]()

---

## Best Practices

### Filtering by Provenance

Always use provenance columns for filtering multi-axis results:

```python
# ✅ Correct: Use provenance column
df = pd.read_csv(boltz.tables.confidence.info.path)
prot1_results = df[df['proteins.id'] == 'prot1']

# ❌ Incorrect: String matching on output ID
prot1_results = df[df['id'].str.contains('prot1')]  # Fragile!
```

### Joining Tables from Different Tools

Use provenance columns to join tables that share a common axis:

```python
# Join ProteinMPNN sequences with AlphaFold predictions
pmpnn_df = pd.read_csv(pmpnn.tables.sequences.info.path)
af_df = pd.read_csv(af.tables.confidence.info.path)

# Both have 'structures.id' provenance column
merged = pd.merge(
    pmpnn_df,
    af_df,
    on='structures.id',  # Common parent structure
    suffixes=('_pmpnn', '_af')
)
```

### Handling Missing Matches

When `get_mapped_ids()` returns `None`, it means no valid match was found. Always check for this:

```python
from biopipelines.id_map_utils import get_mapped_ids

matches = get_mapped_ids(
    source_ids=panda_ids,
    target_ids=upstream_ids,
    id_map={"*": "*_<S>"},
    map_table_paths=[panda.streams.structures.map_table]
)

for source_id, target_id in matches.items():
    if target_id is None:
        print(f"Warning: No match found for {source_id}")
```

**Sources:** [Docs/UserManual.md:361-370](), [biopipelines/id_map_utils.py:408-534]()

---