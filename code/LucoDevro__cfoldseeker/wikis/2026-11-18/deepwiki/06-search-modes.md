# Search Modes

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [cfoldseeker/main.py](cfoldseeker/main.py)
- [docs/guide/usage.rst](docs/guide/usage.rst)

</details>



`cfoldseeker` provides three distinct operational modes to accommodate different search scales and infrastructure availability. All search modes are managed by the `init_search()` factory in `cfoldseeker/main.py` [cfoldseeker/main.py:126-146]() and follow a unified execution contract defined by the `Search` base class.

### The Search Interface

Every search mode inherits from the `Search` abstract base class [cfoldseeker/classes.py:277-314](). This ensures that regardless of the underlying engine (Remote API vs. Local Binary), the workflow remains consistent:

1.  **`run()`**: Orchestrates the specific search logic (e.g., submitting tickets to FoldSeek or executing a subprocess).
2.  **`identify_clusters()`**: A shared method that uses `NetworkX` to group hits into genomic clusters based on intergenic distance and genomic length [cfoldseeker/classes.py:440-520]().
3.  **`generate_output()`**: Standardizes the production of `hits.tsv`, `clusters.tsv`, and optional `cblaster` or `clinker` session files [cfoldseeker/classes.py:522-638]().

### Search Mode Selection

| Mode | Class | Best For | Requirements |
| :--- | :--- | :--- | :--- |
| **Remote** | `RemoteSearch` | Small-scale queries against public databases (AFDB). | Internet access, UniProt mapping table. |
| **Local** | `LocalSearch` | Searching custom or proprietary structural databases. | Local `foldseek` binary, pre-built structural DB, CDS context DB. |
| **Local-Clustered** | `LocalClusteredSearch` | Large-scale genomic searches (e.g., thousands of genomes). | MMseqs2 cluster TSV, FoldSeek DB of representatives, CDS context DB. |

---

### Remote Search Mode

The **Remote** mode (`-m remote`) leverages the FoldSeek webserver to perform structural searches against the AlphaFold Database (AFDB). It is designed for users who do not wish to maintain local structural databases or high-performance computing clusters.

This mode performs complex cross-referencing to bridge structural hits (identified by UniProt/AFDB IDs) to genomic coordinates via KEGG and ENA/GenPept APIs.

*   **Key Component**: `RemoteSearch` class [cfoldseeker/remote.py:20-25]().
*   **Workflow**: Submits queries via `communication.py` [cfoldseeker/communication.py:25-56](), parses JSON results, and resolves metadata through a three-tier hierarchy (KEGG → ENA → UniSave).
*   **Concurrency**: Uses `thread_map` to parallelize API requests across multiple workers [cfoldseeker/remote.py:80-94]().

For details, see [Remote Search Mode (remote.py)](#3.1).

**Sources:** [cfoldseeker/remote.py:20-94](), [cfoldseeker/communication.py:25-56](), [cfoldseeker/main.py:55-55]().

---

### Local Search Mode

The **Local** mode (`-m local`) executes the `foldseek easy-search` binary on the user's local machine. This is the primary mode for searching private structural datasets or large-scale local mirrors of public databases.

*   **Key Component**: `LocalSearch` class [cfoldseeker/local.py:18-23]().
*   **Workflow**: Invokes `foldseek` via `subprocess` [cfoldseeker/local.py:100-141](), then uses `Polars` LazyFrames to join the structural hits against a pre-built CDS coordinate database (`cfoldseeker-cds` output).
*   **Coordinate Resolution**: Maps local sequence identifiers to genomic locations using the `cds_db` [cfoldseeker/local.py:143-176]().

For details, see [Local Search Mode (local.py)](#3.2).

**Sources:** [cfoldseeker/local.py:18-176](), [docs/guide/usage.rst:33-112]().

---

### Local-Clustered Search Mode

The **Local-Clustered** mode (`-m local_clustered`) is an optimized version of the local search designed for massive datasets. It reduces the search space by only searching structural representatives of protein families and then programmatically expanding those hits to all members of the cluster.

*   **Key Component**: `LocalClusteredSearch` class [cfoldseeker/local_clustered.py:15-20]().
*   **Workflow**: Inherits from `LocalSearch` but overrides the hit processing to include an `expand_sequence_clusters()` step [cfoldseeker/local_clustered.py:58-96]().
*   **Optimization**: Significantly reduces the number of structural alignments required by utilizing MMseqs2 pre-clustering results.

For details, see [Local-Clustered Search Mode (local_clustered.py)](#3.3).

**Sources:** [cfoldseeker/local_clustered.py:15-96](), [docs/guide/usage.rst:113-129]().

---

### System Entity Mapping

The following diagrams illustrate the relationship between user-facing search modes and the underlying code entities.

#### Search Factory and Hierarchy
This diagram shows how `main.py` selects a search implementation based on the `--mode` argument.

```mermaid
graph TD
    subgraph "CLI Entrypoint (main.py)"
        [main] --> [init_search]
    end

    subgraph "Search Implementations"
        [init_search] -- "mode='remote'" --> [RemoteSearch]
        [init_search] -- "mode='local'" --> [LocalSearch]
        [init_search] -- "mode='local_clustered'" --> [LocalClusteredSearch]
    end

    subgraph "Inheritance (classes.py)"
        [RemoteSearch] -- "inherits" --> [Search_Base]
        [LocalSearch] -- "inherits" --> [Search_Base]
        [LocalClusteredSearch] -- "inherits" --> [LocalSearch]
    end

    [Search_Base] --> [identify_clusters]
    [Search_Base] --> [generate_output]
```
**Sources:** [cfoldseeker/main.py:126-146](), [cfoldseeker/classes.py:277-314](), [cfoldseeker/local_clustered.py:15-20]().

#### Data Flow and Dependency Mapping
This diagram maps the natural language "Search Modes" to the specific files and external dependencies they interact with.

```mermaid
graph LR
    subgraph "Remote Mode"
        [RemoteSearch] --> [communication.py]
        [communication.py] -- "HTTP" --> [FoldSeek_API]
        [communication.py] -- "HTTP" --> [NCBI_Entrez]
    end

    subgraph "Local Modes"
        [LocalSearch] --> [subprocess_foldseek]
        [LocalClusteredSearch] --> [expand_sequence_clusters]
        [LocalSearch] -- "reads" --> [CDS_Database_TSV]
        [LocalClusteredSearch] -- "reads" --> [MMseqs2_Cluster_TSV]
    end

    [LocalSearch] -- "uses" --> [Polars_LazyFrame]
    [RemoteSearch] -- "uses" --> [thread_map]
```
**Sources:** [cfoldseeker/remote.py:80-94](), [cfoldseeker/local.py:100-141](), [cfoldseeker/local_clustered.py:58-96](), [cfoldseeker/communication.py:25-56]().

---