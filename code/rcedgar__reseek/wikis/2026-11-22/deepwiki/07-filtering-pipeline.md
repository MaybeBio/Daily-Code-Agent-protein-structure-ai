# Filtering Pipeline

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/mufilter.cpp](src/mufilter.cpp)
- [src/mukmerfilter.cpp](src/mukmerfilter.cpp)
- [src/mukmerfilter.h](src/mukmerfilter.h)
- [src/mukmerfilter2.cpp](src/mukmerfilter2.cpp)
- [src/postmufilter.cpp](src/postmufilter.cpp)
- [src/search.cpp](src/search.cpp)

</details>



## Purpose and Scope

The filtering pipeline implements a two-stage pre-filtering system designed to efficiently reduce the search space before performing expensive structural alignments. This system balances speed and sensitivity by using fast k-mer matching followed by detailed alignment of promising candidates.

For information about the core alignment algorithms that process the filtered results, see [Core Alignment Engine](#3). For database search orchestration and threading models, see [DBSearcher and ProfileLoader](#4.1).

## Architecture Overview

The filtering pipeline consists of two main stages that work together to identify promising alignment candidates:

```mermaid
graph TB
    subgraph "Stage 1: Fast K-mer Pre-filtering"
        A[MuSeqSource] --> B[MuKmerFilter]
        B --> C[Hash Table Lookup]
        C --> D[X-drop Extension]
        D --> E[HSP Chaining]
        E --> F[Filter Results TSV]
    end
    
    subgraph "Stage 2: Detailed Alignment"
        F --> G[PostMuFilter]
        G --> H[Multi-threaded Query Indexing]
        H --> I[DSSAligner]
        I --> J[Statistical Scoring]
        J --> K[Final Results]
    end
    
    subgraph "Input Data"
        L[Query Chains] --> A
        M[Database Chains] --> A
        N[MuLetters] --> B
        O[MuKmers] --> B
    end
    
    subgraph "Configuration"
        P[DSSParams] --> B
        P --> G
        Q[E-value Thresholds] --> J
        R[Threading Parameters] --> H
    end
    
    L --> H
    M --> I
```

**Two-Stage Filtering Architecture**

Sources: [src/search.cpp:64-115](), [src/postmufilter.cpp:195-284](), [src/mukmerfilter.cpp:314-387]()

## Stage 1: MuKmerFilter

The first stage performs rapid k-mer based screening using hash tables and X-drop extension algorithms.

### Core Components

```mermaid
graph LR
    subgraph "MuKmerFilter Class"
        A[m_ptrKmerHashTableQ] --> B[Hash Table Lookup]
        C[m_ptrMuLettersQ] --> D[X-drop Extension]
        E[m_ptrMuKmersQ] --> B
        F[m_DictSize] --> B
        G[Chainer] --> H[HSP Chaining]
    end
    
    subgraph "Key Methods"
        I[SetQ] --> J[SetHashTable]
        K[GetMaxHSPScore] --> L[MuXDrop]
        M[Align] --> N[ChainHSPs]
        O[AlignBag] --> K
    end
    
    subgraph "Data Structures"
        P[m_MuKmerHSPLois] --> Q[HSP Coordinates]
        R[m_MuKmerHSPScores] --> S[HSP Scores]
        T[m_ChainHSPLois] --> U[Chained HSPs]
    end
    
    J --> B
    L --> H
    N --> U
```

**MuKmerFilter Internal Architecture**

The `MuKmerFilter` class implements the core k-mer matching algorithm:

| Component | Type | Purpose |
|-----------|------|---------|
| `m_ptrKmerHashTableQ` | `uint16_t*` | Hash table for query k-mers |
| `m_DictSize` | `uint` | Size of k-mer dictionary (36^k) |
| `m_ptrMuLettersQ` | `vector<byte>*` | Query sequence in reduced alphabet |
| `m_ptrMuKmersQ` | `vector<uint>*` | Query k-mers |
| `m_C` | `Chainer` | Chains HSPs into longer alignments |

Sources: [src/mukmerfilter.h:9-97](), [src/mukmerfilter.cpp:96-102]()

### X-drop Extension Algorithm

The `MuXDrop` method implements bidirectional X-drop extension from k-mer seeds:

```mermaid
graph TD
    A[K-mer Match] --> B[Forward Extension]
    A --> C[Reverse Extension]
    B --> D[Score Tracking]
    C --> E[Score Tracking]
    D --> F[X-drop Termination]
    E --> G[X-drop Termination]
    F --> H[Best Forward Score]
    G --> I[Best Reverse Score]
    H --> J[Combined HSP Score]
    I --> J
    J --> K[HSP Coordinates]
```

**X-drop Extension Process**

The algorithm extends matches in both directions until the score drops more than X below the best score seen so far. This efficiently identifies high-scoring local alignments without exhaustive dynamic programming.

Sources: [src/mukmerfilter.cpp:104-174]()

## Stage 2: PostMuFilter

The second stage performs detailed structural alignment on candidates identified by the first stage.

### Threading Architecture

```mermaid
graph TB
    subgraph "Multi-threaded Processing"
        A[LineReader2] --> B[s_ScanLock]
        B --> C[ThreadBody_Scan]
        C --> D[BCAData]
        D --> E[DSSAligner]
        E --> F[Statistical Scoring]
        F --> G[Output Files]
    end
    
    subgraph "Query Indexing"
        H[s_IndexQueryLock] --> I[ThreadBody_IndexQuery]
        I --> J[DSS Profile Generation]
        J --> K[ChainBag Creation]
        K --> L[Parasail Profiles]
    end
    
    subgraph "Synchronization"
        M[s_QueryIdx] --> N[Query Processing]
        O[s_LineIdx] --> P[Target Processing]
        Q[s_ScannedCount] --> R[Progress Tracking]
    end
    
    I --> C
    K --> E
```

**PostMuFilter Threading Model**

The `PostMuFilter` uses a two-phase threading approach:

1. **Index Phase**: Multi-threaded query indexing using `ThreadBody_IndexQuery`
2. **Scan Phase**: Multi-threaded scanning using `ThreadBody_Scan`

Sources: [src/postmufilter.cpp:36-101](), [src/postmufilter.cpp:103-192]()

### Key Data Structures

| Structure | Purpose | Thread Safety |
|-----------|---------|---------------|
| `s_ptrChainBagsQ` | Pre-computed query profiles | Protected by `s_IndexQueryLock` |
| `s_ptrLR` | Line reader for filter results | Protected by `s_ScanLock` |
| `s_fTsv` | Output file handles | Protected by `s_ScanLock` |
| `s_MaxEvalue` | E-value threshold | Read-only after initialization |

Sources: [src/postmufilter.cpp:19-34]()

## Integration with Search System

The filtering pipeline integrates with the broader search system through the `cmd_search` function:

```mermaid
graph LR
    subgraph "Search Command Flow"
        A[cmd_search] --> B{optset_fast?}
        B -->|true| C[Two-stage Pipeline]
        B -->|false| D[Search_NoMuFilter]
        C --> E[MuPreFilter]
        E --> F[PostMuFilter]
        F --> G[Final Results]
        D --> G
    end
    
    subgraph "Configuration"
        H[DSSParams] --> I[DM_UseCommandLineOption]
        H --> J[DM_AlwaysSensitive]
        I --> E
        J --> F
    end
    
    subgraph "Data Flow"
        K[MuSeqSource] --> E
        L[SeqDB] --> E
        M[Filter Results TSV] --> F
        N[BCA Database] --> F
    end
```

**Search System Integration**

The pipeline is activated when the `--fast` option is specified, using different parameter sets for each stage:
- Stage 1: `DM_UseCommandLineOption` for fast filtering
- Stage 2: `DM_AlwaysSensitive` for accurate alignment

Sources: [src/search.cpp:64-115]()

## Performance Considerations

### Memory Management

The filtering pipeline uses several memory optimization strategies:

| Strategy | Implementation | Benefit |
|----------|---------------|---------|
| Hash Table Reuse | `CreateEmptyHashTable()` | Reduces allocations |
| Profile Caching | `ChainBag` structures | Avoids recomputation |
| Thread-local Storage | Per-thread `DSSAligner` | Eliminates contention |

### Statistical Tracking

The `MuKmerFilter` maintains performance statistics:

```cpp
static uint m_PairCount;
static uint m_PairWithHSPCount;
static uint m_ChainCount;
static uint m_ChainHSPCount;
```

These metrics help optimize the balance between speed and sensitivity.

Sources: [src/mukmerfilter.h:49-55](), [src/mukmerfilter.cpp:456-465]()

### Filtering Thresholds

Key parameters that control the filtering stringency:

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `m_MKF_MinHSPScore` | 30 | Minimum HSP score to retain |
| `m_MKF_X1` | 12 | X-drop threshold |
| `s_MaxEvalue` | 10.0 | E-value cutoff for final results |
| `HASHW` | 4 | Hash table width for collision handling |

Sources: [src/mukmerfilter.cpp:337-338](), [src/postmufilter.cpp:31-32](), [src/mukmerfilter.h:7]()

---