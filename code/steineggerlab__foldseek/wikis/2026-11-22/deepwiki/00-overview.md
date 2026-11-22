# Overview

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.github/results.png](.github/results.png)
- [LICENSE.md](LICENSE.md)
- [README.md](README.md)
- [data/structdatabases.sh](data/structdatabases.sh)
- [src/foldseek.cpp](src/foldseek.cpp)
- [src/strucclustutils/LoLAlign.cpp](src/strucclustutils/LoLAlign.cpp)
- [src/strucclustutils/LoLAlign.h](src/strucclustutils/LoLAlign.h)
- [src/strucclustutils/LoLAlignProbability.h](src/strucclustutils/LoLAlignProbability.h)
- [src/strucclustutils/LoLAlignProbabilityWeights.h](src/strucclustutils/LoLAlignProbabilityWeights.h)

</details>



Foldseek is a high-performance tool designed for fast and sensitive comparisons of large protein structure sets. It enables rapid searching and clustering of protein structures with performance up to 20,000 times faster than traditional structural aligners while maintaining comparable sensitivity [README.md:2-7](). Foldseek supports monomer and multimer searches, runs on CPU, and leverages GPU acceleration for enhanced speed [README.md:3]().

Sources: [README.md:2-11](), [src/foldseek.cpp:5-9]()

## What is Foldseek?

Foldseek is specialized software for structural bioinformatics that allows users to:

- **Search**: Compare protein structures against massive databases such as AlphaFoldDB or the Protein Data Bank (PDB), quickly retrieving structural homologs [README.md:66-67]().
- **Cluster**: Group similar protein structures into clusters to reduce redundancy and analyze structural diversity at large scale [README.md:42-47]().
- **Multimer Support**: Perform complex alignments and scoring on multi-chain protein complexes (multimers), enabling analysis beyond monomers [README.md:51-58]().
- **Sequence-to-Structure Search**: Efficiently predict 3Di structural sequences from raw amino acid sequences using an integrated protein language model, enabling ultra-fast and sensitive structure searches without available 3D coordinates [README.md:3](), [src/foldseek.cpp:15-21]().

Sources: [README.md:2-11](), [src/foldseek.cpp:5-21]()

## System Architecture

Foldseek's architecture is modular and command-driven, extending the MMseqs2 framework to handle large structural databases, parameter management, and parallel execution efficiently. Commands are registered and dispatched dynamically, supported by a shared parameter singleton (`LocalParameters`) [src/foldseek.cpp:15-22]().

### Code-to-System Mapping

This diagram maps core system concepts to corresponding key source files and components in the codebase:

```mermaid
flowchart TD
    subgraph "Entry_Point"
        CLI["\"foldseek.cpp (main executable)\""]
    end

    subgraph "Command_System"
        Registry["\"foldseekCommands (foldseek.cpp)\""]
        Params["\"LocalParameters (LocalParameters.cpp)\""]
    end

    subgraph "Workflow_Scripts"
        SearchSH["\"structuresearch.sh\""]
        ClusterSH["\"structurecluster.sh\""]
        MultiSH["\"multimersearch.sh\""]
    end

    subgraph "Core_Modules"
        SearchCPP["\"StructureSearch.cpp\""]
        ClusterCPP["\"StructureCluster.cpp\""]
        AlignCPP["\"LoLAlign.cpp\""]
        LMCPP["\"ProstT5 (Language Model)\""]
    end

    CLI --> Registry
    Registry --> Params
    Registry --> SearchSH
    Registry --> ClusterSH
    Registry --> MultiSH

    SearchSH --> SearchCPP
    ClusterSH --> ClusterCPP
    SearchCPP --> AlignCPP
    SearchCPP --> LMCPP
```

Sources: [src/foldseek.cpp:15-22](), [data/structdatabases.sh:1-30]()

## Command System Overview

Foldseek organizes functionality into a layered command hierarchy to balance usability and advanced control. It offers simplified `easy-*` workflows, core structural analysis commands, database management tools, multimer analysis utilities, and format converters [src/foldseek.cpp:15-22]().

"Easy" commands wrap complex pipelines into a single user-facing interface for convenience, while core commands provide granular control and extension points [src/foldseek.cpp:15-22]().

For installation details and initial setup guidance, see [Installation and Getting Started](#1.1). For an explanation of command organization and workflows, see [Command Structure](#1.2). For common usage examples and command patterns, see [Basic Usage Examples](#1.3).

Sources: [src/foldseek.cpp:15-22](), [README.md:59-60]()

## Database System

Foldseek stores structural data in a custom multi-file database format combining amino acid sequences, 3Di structural descriptors, and Cα coordinates for spatial context [README.md:94-100]().

The database is constructed via database creation modules, converting PDB, mmCIF, tar archives, or TSV lists into indexed Foldseek structure databases with efficient coordinate compression and feature encoding [data/structdatabases.sh:89-178](), [README.md:94-100]().

### Data Flow Diagram for Database Creation and Usage

```mermaid
flowchart LR
    subgraph "Input_Formats"
        PDB["\".pdb / .cif files\""]
        FASTA["\".fasta files\""]
    end

    subgraph "Pipeline"
        Enc["\"3Di Encoder\""]
        Comp["\"Coordinate Compression\""]
    end

    subgraph "Database_Files"
        AA["\"_seq (Amino Acid sequences)\""]
        SS["\"_ss (3Di sequences)\""]
        CA["\"_ca (Ca coordinates)\""]
        HDR["\"_h (Headers / metadata)\""]
    end

    PDB --> createdb
    FASTA --> createdb
    createdb --> Enc --> Comp --> AA & SS & CA & HDR
```

Foldseek provides automated download scripts (`structdatabases.sh`) with a selection of pre-built public structural databases available for download, such as AlphaFoldDB variants, PDB, CATH50, and others [data/structdatabases.sh:89-178]().

Sources: [data/structdatabases.sh:89-178](), [README.md:38-41, 94-100]()

## Performance Features and Hardware Support

- **GPU Acceleration:** Foldseek supports Nvidia GPU acceleration (Ampere generation or newer recommended) for faster search computations, with fallback to CPU-only mode [README.md:13, 91-93]().
- **Memory Management Options:** Users can configure different memory modes, such as disabling Cα coordinate details to save RAM at some cost to hit ranking precision, or fully exhaustive single-query modes using prefilter adjustments [README.md:95-104]().
- **High Parallelism:** Designed to scale to large protein structure datasets with multithreading and optimized SIMD support [README.md:3]().

Sources: [README.md:3, 13, 91-104]()

## Related Pages

For in-depth details on these topics, consult the child pages:

- **[Installation and Getting Started](#1.1)** — Covers build options, usage of precompiled binaries, Docker, Conda installation, and basic setup instructions [README.md:72-88]().
- **[Command Structure](#1.2)** — Detailed explanation of Foldseek's command and parameter systems, including command registration and usage patterns [src/foldseek.cpp:15-22]().
- **[Basic Usage Examples](#1.3)** — Common command invocations, typical workflows for searching and clustering, and sample input/output examples [README.md:30-69]().

Sources: [README.md:30-88](), [src/foldseek.cpp:15-22]()

---