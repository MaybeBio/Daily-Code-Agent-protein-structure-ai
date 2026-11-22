# Multiple Sequence Alignments

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [chai_lab/data/dataset/msas/colabfold.py](chai_lab/data/dataset/msas/colabfold.py)
- [chai_lab/data/dataset/msas/load.py](chai_lab/data/dataset/msas/load.py)
- [chai_lab/data/dataset/msas/msa_context.py](chai_lab/data/dataset/msas/msa_context.py)
- [chai_lab/data/dataset/msas/preprocess.py](chai_lab/data/dataset/msas/preprocess.py)
- [chai_lab/data/features/generators/msa.py](chai_lab/data/features/generators/msa.py)
- [chai_lab/data/parsing/fasta.py](chai_lab/data/parsing/fasta.py)
- [chai_lab/data/parsing/msas/a3m.py](chai_lab/data/parsing/msas/a3m.py)
- [chai_lab/data/parsing/msas/aligned_pqt.py](chai_lab/data/parsing/msas/aligned_pqt.py)
- [chai_lab/data/parsing/msas/data_source.py](chai_lab/data/parsing/msas/data_source.py)
- [chai_lab/data/parsing/msas/species.py](chai_lab/data/parsing/msas/species.py)
- [chai_lab/data/parsing/restraints.py](chai_lab/data/parsing/restraints.py)
- [chai_lab/model/utils.py](chai_lab/model/utils.py)
- [examples/msas/predict_with_msas.py](examples/msas/predict_with_msas.py)
- [scripts/stage_colabfold_outputs_for_chai.py](scripts/stage_colabfold_outputs_for_chai.py)
- [tests/test_colabfold_msas.py](tests/test_colabfold_msas.py)

</details>



Multiple Sequence Alignments (MSAs) provide evolutionary information that significantly improves protein structure prediction in Chai-1. This page documents how MSAs are formatted, generated, processed, and integrated into the prediction pipeline.

## MSA Data Format

Chai-1 uses a custom `.aligned.pqt` file format. This is a Parquet dataframe that extends standard alignment information with metadata for pairing and source tracking.

### AlignedParquetModel Schema
The schema is enforced using `AlignedParquetModel` defined in [chai_lab/data/parsing/msas/aligned_pqt.py:37-44]().

| Column | Type | Description |
|--------|------|-------------|
| `sequence` | `str` | Aligned sequence in a3m format (including gaps `-` and deletions). |
| `source_database` | `str` | Database source (e.g., `uniref90`, `mgnify`, `query`). |
| `pairing_key` | `str` | Key for pairing alignments across chains (often species names). |
| `comment` | `str` | Metadata or header information from the original hit. |

The first row of any `.aligned.pqt` file must be the query sequence with `source_database` set to `"query"` [chai_lab/data/parsing/msas/aligned_pqt.py:78-80]().

### File Naming
Files are named based on the SHA256 hash of the uppercased query sequence. The `expected_basename` function handles this mapping [chai_lab/data/parsing/msas/aligned_pqt.py:57-60]().

Sources: [chai_lab/data/parsing/msas/aligned_pqt.py:37-60](), [chai_lab/data/parsing/msas/data_source.py:1-50]()

## MSA Generation via ColabFold

Chai-1 supports automated MSA generation using the ColabFold server API. This is primarily handled by `generate_colabfold_msas` [chai_lab/data/dataset/msas/colabfold.py:296-302]().

### Implementation Details
1. **API Interaction**: The function `_run_mmseqs2` (adapted from ColabFold) handles submission to `api.colabfold.com` [chai_lab/data/dataset/msas/colabfold.py:35-46](). It supports both standard MSA tickets and pairing tickets for multimers [chai_lab/data/dataset/msas/colabfold.py:48-49]().
2. **Tokenization**: Aligned sequences are tokenized into numeric arrays using Numba-accelerated functions in `a3m.py` [chai_lab/data/parsing/msas/a3m.py:97-113](). This process also generates a `deletion_matrix` representing lowercase letters in a3m format [chai_lab/data/parsing/msas/a3m.py:81-91]().
3. **Pairing Logic**: For multimers, sequences are paired based on taxid/species information extracted from headers [chai_lab/data/dataset/msas/colabfold.py:343-350]().

```mermaid
title "ColabFold MSA Generation Flow"
graph TD
    subgraph "Python API Space"
        A["run_inference()"] -- "msa_server=True" --> B["generate_colabfold_msas()"]
    end

    subgraph "Network & External API"
        B -- "POST /ticket/msa" --> C["api.colabfold.com"]
        C -- "Returns .tar.gz" --> B
    end

    subgraph "Processing Space"
        B -- "extracts .a3m" --> D["tokenize_sequences_to_arrays()"]
        D -- "enforce schema" --> E["AlignedParquetModel"]
        E -- "save" --> F[".aligned.pqt files"]
    end
```
Sources: [chai_lab/data/dataset/msas/colabfold.py:35-152](), [chai_lab/data/parsing/msas/a3m.py:57-113](), [chai_lab/data/dataset/msas/colabfold.py:296-458]()

## MSA Integration and Context

Once loaded, MSAs are encapsulated in the `MSAContext` class, which manages tensors for the model trunk [chai_lab/data/dataset/msas/msa_context.py:25-33]().

### MSAContext Structure
| Attribute | Shape | Type | Description |
|-----------|-------|------|-------------|
| `tokens` | `(depth, tokens)` | `uint8` | Integer-encoded amino acids/nucleotides. |
| `pairing_key_hash` | `(depth, tokens)` | `int32` | Hashed pairing keys for cross-chain alignment. |
| `deletion_matrix` | `(depth, tokens)` | `uint8` | Count of deleted residues at each position. |
| `sequence_source` | `(depth, tokens)` | `uint8` | Encoded source database ID. |

### Loading Pipeline
The `get_msa_contexts` function orchestrates the transition from disk to model-ready tensors [chai_lab/data/dataset/msas/load.py:29-32]().

1. **Discovery**: Locates `.aligned.pqt` files in the provided `msa_directory` using `expected_basename` [chai_lab/data/dataset/msas/load.py:49-50]().
2. **Parsing**: Uses `parse_aligned_pqt_to_msa_context` to validate schema and apply database quotas [chai_lab/data/parsing/msas/aligned_pqt.py:63-70]().
3. **Pairing & Merging**: 
   - `pair_and_merge_msas` aligns sequences across different chains if they share a pairing key hash [chai_lab/data/dataset/msas/preprocess.py:86-89]().
   - `merge_main_msas_by_chain` concatenates MSAs along the token dimension for multimer featurization [chai_lab/data/dataset/msas/preprocess.py:23-24]().
4. **Deduplication**: `drop_duplicates` removes identical rows within the context [chai_lab/data/dataset/msas/preprocess.py:36-37]().

```mermaid
title "MSA Loading & Context Assembly"
graph TD
    DIR["msa_directory"] -- "Path" --> LOAD["get_msa_contexts()"]
    LOAD -- "calls" --> PQT["parse_aligned_pqt_to_msa_context()"]
    
    subgraph "Data Structures"
        PQT -- "instantiates" --> CTX["MSAContext"]
    end

    subgraph "Preprocessing Logic"
        CTX --> PAIR["pair_and_merge_msas()"]
        PAIR --> DUP["drop_duplicates()"]
        DUP --> FINAL["joined_msa"]
    end

    FINAL -- "integrated into" --> FEAT["AllAtomFeatureContext"]
```
Sources: [chai_lab/data/dataset/msas/load.py:29-82](), [chai_lab/data/dataset/msas/msa_context.py:25-56](), [chai_lab/data/dataset/msas/preprocess.py:23-133]()

## Technical Implementation Details

### Tokenization Mapping
The mapping from a3m characters to model tokens is handled by `_get_tokenization_mapping` [chai_lab/data/parsing/msas/a3m.py:29-30](). It handles:
- **Uppercase**: Mapped to standard residue types [chai_lab/data/parsing/msas/a3m.py:41-48]().
- **Lowercase**: Mapped as insertions (`MAPPED_TOKEN_INSERTION`) and counted in the deletion matrix [chai_lab/data/parsing/msas/a3m.py:50-51]().
- **Gaps (`-`)**: Assigned a specific gap token [chai_lab/data/parsing/msas/a3m.py:52]().

### Quotas and Priorities
During loading, Chai-1 applies per-database quotas (e.g., limiting hits from `mgnify` or `uniref90`) and sorts sequences by priority [chai_lab/data/parsing/msas/aligned_pqt.py:83-109]().

### Pairing Strategy
Pairing is based on `pairing_key_hash`. The `prepair_ukey` function generates unique keys `(pair_key, rank)` to handle multiple hits from the same species, ensuring stable pairing across chains [chai_lab/data/dataset/msas/preprocess.py:49-52]().

Sources: [chai_lab/data/parsing/msas/a3m.py:29-56](), [chai_lab/data/parsing/msas/aligned_pqt.py:83-109](), [chai_lab/data/dataset/msas/preprocess.py:49-83]()

---