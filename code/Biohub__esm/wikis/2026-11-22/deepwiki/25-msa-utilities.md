# MSA Utilities

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [esm/models/esmfold2/paired_msa.py](esm/models/esmfold2/paired_msa.py)
- [esm/sdk/base_forge_client.py](esm/sdk/base_forge_client.py)
- [esm/utils/msa/__init__.py](esm/utils/msa/__init__.py)
- [esm/utils/msa/filter_sequences.py](esm/utils/msa/filter_sequences.py)
- [esm/utils/msa/msa.py](esm/utils/msa/msa.py)
- [esm/utils/msa/msa_test.py](esm/utils/msa/msa_test.py)
- [esm/utils/parsing.py](esm/utils/parsing.py)

</details>



The Multiple Sequence Alignment (MSA) utilities provide a robust framework for handling, filtering, and processing protein sequence alignments. These utilities support core ESM operations, including diversity-based sequence selection for MSA Transformer models and taxonomy-based pairing for ESMFold2 multimer structure prediction.

## The MSA Dataclass

The core of the MSA system is the `MSA` class [esm/utils/msa/msa.py:47-196](), a `SequentialDataclass` that provides an object-oriented interface for manipulating alignments. It stores data as a list of `FastaEntry` objects, which contain headers and sequences.

### Key Features and Methods
*   **Factory Methods**: Supports loading from `.a3m` (A3M), `.sto` (Stockholm), and raw sequence lists [esm/utils/msa/msa.py:76-174]().
*   **Serialization**: Implements `to_bytes` and `from_bytes` for efficient storage and transport, preserving both sequences and headers [esm/utils/msa/msa.py:122-160]().
*   **Subselection**: Methods like `select_sequences` and `select_positions` allow for slicing the MSA by rows or columns while maintaining internal consistency [esm/utils/msa/msa.py:200-203]().
*   **Insertion Handling**: Provides `remove_insertions_from_sequence` to strip lowercase letters and dots from A3M formatted sequences [esm/utils/msa/msa.py:23-25]().
*   **Deletion Counts**: The `MSA` class can store per-match-column deletion counts, particularly when loaded from A3M files, which is crucial for ESMFold2's featurization [esm/utils/msa/msa.py:37](). These deletion counts are preserved through slicing, padding, and stacking operations [esm/utils/msa/msa_test.py:87-149]().

### Data Representation
The `MSA` class lazily computes a NumPy character array (`|S1`) of the sequences for high-performance numerical operations [esm/utils/msa/msa.py:177-178]().

| Attribute | Type | Description |
| :--- | :--- | :--- |
| `entries` | `list[FastaEntry]` | Raw header/sequence pairs [esm/utils/msa/msa.py:37](). |
| `deletions` | `np.ndarray | None` | Per-(row, match-column) a3m deletion counts [esm/utils/msa/msa.py:38](). |
| `sequences` | `list[str]` | Property returning all sequence strings [esm/utils/msa/msa.py:40-41](). |
| `headers` | `list[str]` | Property returning all header strings [esm/utils/msa/msa.py:44-45](). |
| `depth` | `int` | Number of sequences in the MSA [esm/utils/msa/msa.py:169-170](). |
| `seqlen` | `int` | Length of the alignment [esm/utils/msa/msa.py:173-174](). |

**Sources:** [esm/utils/msa/msa.py:28-196](), [esm/utils/parsing.py:6-6](), [esm/utils/msa/msa_test.py:87-149]()

---

## Sequence Selection and Filtering

The library provides two primary mechanisms for reducing MSA depth while preserving information: greedy selection and `hhfilter` wrapping.

### Greedy Diversity Selection
The `greedy_select_indices` function [esm/utils/msa/filter_sequences.py:11-45]() implements the algorithm used in the MSA Transformer paper. It iteratively selects sequences that maximize the average Hamming distance to the already selected set.

1.  Start with the query sequence (index 0).
2.  Calculate the Hamming distance between the current set and all remaining sequences using `scipy.spatial.distance.cdist` [esm/utils/msa/filter_sequences.py:38]().
3.  Add the sequence that maximizes the average distance [esm/utils/msa/filter_sequences.py:39]().
4.  Repeat until `num_seqs` is reached.

### HHFilter Wrapper
The `hhfilter` function [esm/utils/msa/filter_sequences.py:48-82]() provides a Python interface to the `hhfilter` binary from the HH-suite. It filters MSAs based on sequence identity, coverage, and diversity. It writes the input sequences to a temporary FASTA file, executes the `hhfilter` command, and then parses the output to return the indices of the filtered sequences [esm/utils/msa/filter_sequences.py:57-82]().

**Sources:** [esm/utils/msa/filter_sequences.py:11-82]()

---

## Paired MSA for ESMFold2

For multimer structure prediction, ESMFold2 requires "paired" MSAs where sequences from different chains are aligned based on their taxonomic origin.

### Taxonomy Extraction
Taxonomy IDs are parsed from FASTA headers using the regex `key=(-?\d+)`. If no key is found, it defaults to `-1` (unpaired) [esm/models/esmfold2/paired_msa.py:35-39]().

### The Pairing Pipeline
The `construct_paired_msa` function [esm/models/esmfold2/paired_msa.py:106-188]() builds the complex MSA features required by the model:

1.  **Per-chain Tables**: For each chain, it converts the `MSA` object into residue type arrays, deletion count arrays, and extracts taxonomy IDs [esm/models/esmfold2/paired_msa.py:137-152]().
2.  **Grouping by Taxonomy**: Sequences from different chains are grouped by their taxonomy ID, excluding the query row and unpaired entries (`key=-1`) [esm/models/esmfold2/paired_msa.py:154-160]().
3.  **Pairing**: Rows are created by combining sequences with matching taxonomy IDs. The function prioritizes taxonomies with more distinct chains [esm/models/esmfold2/paired_msa.py:161-164]().
4.  **Block-Diagonalization**: Sequences that cannot be paired (unpaired or unique to a chain) are placed in the MSA as block-diagonal entries, where the other chain positions are padded with gaps [esm/models/esmfold2/paired_msa.py:1-7]().
5.  **Feature Generation**: Returns `msa_residues` (token IDs), `deletion_value` (insertion counts), and `is_paired` masks [esm/models/esmfold2/paired_msa.py:114-121]().

**Sources:** [esm/models/esmfold2/paired_msa.py:1-188]()

---

## System Integration Diagrams

### MSA Data Flow: From File to Model
This diagram shows how raw MSA files are processed and transformed into the inputs required by structure prediction models like ESMFold2.

```mermaid
graph TD
    subgraph "Natural Language Space (Files)"
        A1[".a3m / .sto Files"]
        A2["FASTA Headers 'key=ID'"]
    end

    subgraph "Code Entity Space (esm.utils.msa)"
        B1["MSA.from_a3m()"]
        B2["MSA Dataclass"]
        B3["greedy_select_indices()"]
        B4["hhfilter()"]
    end

    subgraph "Structure Prediction (esm.models.esmfold2)"
        C1["construct_paired_msa()"]
        C2["msa_to_res_type_and_deletions()"]
        C3["StructurePredictionInput"]
    end

    A1 --> B1
    B1 --> B2
    B2 --> B3
    B2 --> B4
    B2 --> C2
    A2 --> C1
    C2 --> C1
    C1 --> C3
```
**Sources:** [esm/utils/msa/msa.py:56-71](), [esm/utils/msa/filter_sequences.py:11-45](), [esm/models/esmfold2/paired_msa.py:86-121](), [esm/utils/structure/input_builder.py:75-80]()

### MSA Selection Logic
The following diagram details the interaction between the `MSA` class and the filtering utilities.

```mermaid
sequenceDiagram
    participant User
    participant M as MSA Object
    participant F as filter_sequences.py
    participant S as scipy.spatial

    User->>M: select_sequences(indices)
    M->>F: greedy_select_indices(array, num_seqs)
    loop For each sequence to select
        F->>S: cdist(selected, all, 'hamming')
        S-->>F: pairwise_distances
        F->>F: np.argmax(mean_distance)
    end
    F-->>M: selected_indices
    M-->>User: New MSA (subset)
```
**Sources:** [esm/utils/msa/msa.py:184-187](), [esm/utils/msa/filter_sequences.py:11-45]()

---

## Utility Summary Table

| Function | File Path | Description |
| :--- | :--- | :--- |
| `parse_fasta` | `esm/utils/parsing.py` | Generator yielding `FastaEntry` from strings [esm/utils/parsing.py:9-37](). |
| `msa_to_res_type_and_deletions` | `esm/models/esmfold2/paired_msa.py` | Converts MSA to residue IDs and insertion counts, handling a3m insertion conventions [esm/models/esmfold2/paired_msa.py:42-78](). |
| `serialize_structure_prediction_input` | `esm/utils/structure/input_builder.py` | Converts `StructurePredictionInput` (containing MSAs) to JSON-safe dict [esm/utils/structure/input_builder.py:82-153](). |
| `remove_insertions_from_sequence` | `esm/utils/msa/msa.py` | Removes A3M insertion characters (lowercase/dots) [esm/utils/msa/msa.py:23-25](). |
| `a3m_deletion_counts` | `esm/utils/msa/msa.py` | Calculates per-match-column count of preceding a3m insertions [esm/utils/msa/msa.py:32-44](). |

**Sources:** [esm/utils/parsing.py:9-37](), [esm/models/esmfold2/paired_msa.py:42-78](), [esm/utils/structure/input_builder.py:82-153](), [esm/utils/msa/msa.py:23-25](), [esm/utils/msa/msa.py:32-44]()

---