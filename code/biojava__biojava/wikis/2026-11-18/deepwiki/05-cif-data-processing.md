# CIF Data Processing

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [biojava-integrationtest/src/test/java/org/biojava/nbio/structure/test/io/cif/CifFileConsumerIntegrationTest.java](biojava-integrationtest/src/test/java/org/biojava/nbio/structure/test/io/cif/CifFileConsumerIntegrationTest.java)
- [biojava-integrationtest/src/test/java/org/biojava/nbio/structure/test/io/cif/CifFileSupplierIntegrationTest.java](biojava-integrationtest/src/test/java/org/biojava/nbio/structure/test/io/cif/CifFileSupplierIntegrationTest.java)
- [biojava-integrationtest/src/test/resources/1a4w.bcif](biojava-integrationtest/src/test/resources/1a4w.bcif)
- [biojava-integrationtest/src/test/resources/1fdo.bcif](biojava-integrationtest/src/test/resources/1fdo.bcif)
- [biojava-integrationtest/src/test/resources/1j59.bcif](biojava-integrationtest/src/test/resources/1j59.bcif)
- [biojava-integrationtest/src/test/resources/2kc9.bcif](biojava-integrationtest/src/test/resources/2kc9.bcif)
- [biojava-integrationtest/src/test/resources/5pti.bcif](biojava-integrationtest/src/test/resources/5pti.bcif)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/PDBHeader.java](biojava-structure/src/main/java/org/biojava/nbio/structure/PDBHeader.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/io/BcifFileReader.java](biojava-structure/src/main/java/org/biojava/nbio/structure/io/BcifFileReader.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/io/CifFileReader.java](biojava-structure/src/main/java/org/biojava/nbio/structure/io/CifFileReader.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/io/cif/AbstractCifFileSupplier.java](biojava-structure/src/main/java/org/biojava/nbio/structure/io/cif/AbstractCifFileSupplier.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/io/cif/CifFileConsumer.java](biojava-structure/src/main/java/org/biojava/nbio/structure/io/cif/CifFileConsumer.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/io/cif/CifFileSupplier.java](biojava-structure/src/main/java/org/biojava/nbio/structure/io/cif/CifFileSupplier.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/io/cif/CifStructureConsumer.java](biojava-structure/src/main/java/org/biojava/nbio/structure/io/cif/CifStructureConsumer.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/io/cif/CifStructureConsumerImpl.java](biojava-structure/src/main/java/org/biojava/nbio/structure/io/cif/CifStructureConsumerImpl.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/io/cif/CifStructureConverter.java](biojava-structure/src/main/java/org/biojava/nbio/structure/io/cif/CifStructureConverter.java)
- [biojava-structure/src/test/java/org/biojava/nbio/structure/io/cif/CifFileConsumerImplTest.java](biojava-structure/src/test/java/org/biojava/nbio/structure/io/cif/CifFileConsumerImplTest.java)
- [biojava-structure/src/test/java/org/biojava/nbio/structure/io/cif/CifFileSupplierImplTest.java](biojava-structure/src/test/java/org/biojava/nbio/structure/io/cif/CifFileSupplierImplTest.java)

</details>



## Purpose and Scope

This document covers BioJava's modern CIF (Crystallographic Information Framework) data processing system, focusing on the `CifStructureConsumer` architecture and support for both text-based mmCIF and binary CIF (BCIF) formats. This system handles the conversion of CIF files into BioJava `Structure` objects through a category-based consumer pattern.

For general file format support across all biological data formats, see [File Format Support and Parsing](#2.2). For structure caching and retrieval mechanisms, see [Structure Caching and Retrieval](#2.3).

## CIF Format Architecture Overview

BioJava's CIF processing system supports both traditional text-based mmCIF files and the more efficient binary CIF (BCIF) format. The architecture is built around a consumer pattern that processes different CIF categories independently.

```mermaid
graph TB
    subgraph "Input Sources"
        TextCIF["mmCIF Text Files<br/>(.cif, .mmcif)"]
        BinaryCIF["Binary CIF Files<br/>(.bcif)"]
        URLs["Remote URLs"]
        Streams["Input Streams"]
    end
    
    subgraph "File Readers"
        CifFileReader["CifFileReader"]
        BcifFileReader["BcifFileReader"]
    end
    
    subgraph "Core Processing"
        CifStructureConverter["CifStructureConverter"]
        CifIO["org.rcsb.cif.CifIO"]
        CifFile["CifFile Object"]
    end
    
    subgraph "Consumer System"
        CifStructureConsumer["CifStructureConsumer<br/>(interface)"]
        CifStructureConsumerImpl["CifStructureConsumerImpl"]
    end
    
    subgraph "Output"
        Structure["BioJava Structure"]
        PDBHeader["PDBHeader"]
        Chains["Chain Objects"]
        EntityInfo["EntityInfo"]
    end
    
    TextCIF --> CifFileReader
    BinaryCIF --> BcifFileReader
    URLs --> CifStructureConverter
    Streams --> CifStructureConverter
    
    CifFileReader --> CifStructureConverter
    BcifFileReader --> CifStructureConverter
    
    CifStructureConverter --> CifIO
    CifIO --> CifFile
    CifFile --> CifStructureConsumerImpl
    
    CifStructureConsumerImpl -.implements.-> CifStructureConsumer
    
    CifStructureConsumerImpl --> Structure
    CifStructureConsumerImpl --> PDBHeader
    CifStructureConsumerImpl --> Chains
    CifStructureConsumerImpl --> EntityInfo
```

**Sources:** [biojava-structure/src/main/java/org/biojava/nbio/structure/io/CifFileReader.java:1-61](), [biojava-structure/src/main/java/org/biojava/nbio/structure/io/BcifFileReader.java:1-59](), [biojava-structure/src/main/java/org/biojava/nbio/structure/io/cif/CifStructureConverter.java:1-242]()

## CifStructureConsumer System

The core of BioJava's CIF processing is the `CifStructureConsumer` interface, which defines methods for consuming individual CIF categories. The main implementation `CifStructureConsumerImpl` processes these categories to build complete `Structure` objects.

```mermaid
graph TD
    subgraph "Consumer Interface Hierarchy"
        CifFileConsumer["CifFileConsumer&lt;S&gt;<br/>Generic interface"]
        CifStructureConsumer["CifStructureConsumer<br/>extends CifFileConsumer&lt;Structure&gt;"]
        CifStructureConsumerImpl["CifStructureConsumerImpl<br/>implements CifStructureConsumer"]
    end
    
    subgraph "Category Processing Methods"
        consumeAtomSite["consumeAtomSite()"]
        consumeCell["consumeCell()"]
        consumeEntity["consumeEntity()"]
        consumeEntityPoly["consumeEntityPoly()"]
        consumeRefine["consumeRefine()"]
        consumePdbxStructAssembly["consumePdbxStructAssembly()"]
        consumeSymmetry["consumeSymmetry()"]
        OtherMethods["... 25+ other consume methods"]
    end
    
    subgraph "Core Lifecycle"
        prepare["prepare()"]
        finish["finish()"]
        getContainer["getContainer()"]
    end
    
    CifFileConsumer --> CifStructureConsumer
    CifStructureConsumer --> CifStructureConsumerImpl
    
    CifStructureConsumerImpl --> consumeAtomSite
    CifStructureConsumerImpl --> consumeCell
    CifStructureConsumerImpl --> consumeEntity
    CifStructureConsumerImpl --> consumeEntityPoly
    CifStructureConsumerImpl --> consumeRefine
    CifStructureConsumerImpl --> consumePdbxStructAssembly
    CifStructureConsumerImpl --> consumeSymmetry
    CifStructureConsumerImpl --> OtherMethods
    
    CifStructureConsumerImpl --> prepare
    CifStructureConsumerImpl --> finish
    CifStructureConsumerImpl --> getContainer
```

**Sources:** [biojava-structure/src/main/java/org/biojava/nbio/structure/io/cif/CifFileConsumer.java:1-27](), [biojava-structure/src/main/java/org/biojava/nbio/structure/io/cif/CifStructureConsumer.java:1-333](), [biojava-structure/src/main/java/org/biojava/nbio/structure/io/cif/CifStructureConsumerImpl.java:111-1533]()

## Data Processing Pipeline

The CIF data processing follows a systematic pipeline that transforms CIF category data into BioJava's object model through the consumer pattern.

```mermaid
flowchart TD
    subgraph "Initialization Phase"
        PrepareStructure["prepare()<br/>Initialize Structure, PDBHeader<br/>and working collections"]
    end
    
    subgraph "Category Processing Phase"
        AtomSiteProcessing["consumeAtomSite()<br/>Process atomic coordinates<br/>Build Atom, Group, Chain objects"]
        HeaderProcessing["consumeStruct()<br/>consumeAuditAuthor()<br/>Process metadata"]
        EntityProcessing["consumeEntity()<br/>consumeEntityPoly()<br/>Process entity information"]
        CrystalProcessing["consumeCell()<br/>consumeSymmetry()<br/>Process crystallographic data"]
        RefinementProcessing["consumeRefine()<br/>consumeEm3dReconstruction()<br/>Process resolution/quality"]
        AssemblyProcessing["consumePdbxStructAssembly()<br/>Process biological assemblies"]
    end
    
    subgraph "Integration Phase"
        FinishProcessing["finish()<br/>Integrate SeqRes with AtomRes<br/>Create bonds, clean up"]
        ReturnStructure["getContainer()<br/>Return complete Structure"]
    end
    
    PrepareStructure --> AtomSiteProcessing
    PrepareStructure --> HeaderProcessing
    PrepareStructure --> EntityProcessing
    PrepareStructure --> CrystalProcessing
    PrepareStructing --> RefinementProcessing
    PrepareStructure --> AssemblyProcessing
    
    AtomSiteProcessing --> FinishProcessing
    HeaderProcessing --> FinishProcessing
    EntityProcessing --> FinishProcessing
    CrystalProcessing --> FinishProcessing
    RefinementProcessing --> FinishProcessing
    AssemblyProcessing --> FinishProcessing
    
    FinishProcessing --> ReturnStructure
```

**Sources:** [biojava-structure/src/main/java/org/biojava/nbio/structure/io/cif/CifStructureConsumerImpl.java:160-174](), [biojava-structure/src/main/java/org/biojava/nbio/structure/io/cif/CifStructureConsumerImpl.java:1523-1533](), [biojava-structure/src/main/java/org/biojava/nbio/structure/io/cif/CifStructureConverter.java:102-163]()

## Key CIF Categories and Processing

The `CifStructureConsumerImpl` handles numerous CIF categories, each responsible for different aspects of molecular structure data. Here are the most critical categories:

| Category | Method | Purpose | Key Data Processed |
|----------|--------|---------|-------------------|
| `_atom_site` | `consumeAtomSite()` | Core atomic data | Coordinates, occupancy, B-factors, chain/residue IDs |
| `_cell` | `consumeCell()` | Unit cell parameters | a, b, c lengths and α, β, γ angles |
| `_symmetry` | `consumeSymmetry()` | Space group info | Space group symbol and crystallographic symmetry |
| `_entity` | `consumeEntity()` | Molecular entities | Entity types (polymer, non-polymer, water) |
| `_entity_poly` | `consumeEntityPoly()` | Polymer sequences | Sequence information for protein/DNA chains |
| `_refine` | `consumeRefine()` | Refinement statistics | Resolution, R-factors, refinement quality |
| `_struct` | `consumeStruct()` | Structure metadata | PDB ID, title, classification |
| `_pdbx_struct_assembly` | `consumePdbxStructAssembly()` | Biological assemblies | Quaternary structure information |

**Sources:** [biojava-structure/src/main/java/org/biojava/nbio/structure/io/cif/CifStructureConsumerImpl.java:177-370](), [biojava-structure/src/main/java/org/biojava/nbio/structure/io/cif/CifStructureConsumerImpl.java:538-577](), [biojava-structure/src/main/java/org/biojava/nbio/structure/io/cif/CifStructureConsumerImpl.java:892-913]()

## Atom Site Processing Details

The `consumeAtomSite()` method is the most complex part of CIF processing, handling the conversion of atomic coordinate data into BioJava's hierarchical Structure → Chain → Group → Atom model.

```mermaid
graph TD
    subgraph "Input CIF Columns"
        labelAsymId["label_asym_id<br/>(Chain ID)"]
        labelCompId["label_comp_id<br/>(Residue name)"]
        labelAtomId["label_atom_id<br/>(Atom name)"]
        cartnXYZ["Cartn_x/y/z<br/>(Coordinates)"]
        authSeqId["auth_seq_id<br/>(Residue number)"]
        groupPDB["group_PDB<br/>(ATOM/HETATM)"]
        labelAltId["label_alt_id<br/>(Alt location)"]
    end
    
    subgraph "Processing Logic"
        ChainLookup["Find or create Chain<br/>by label_asym_id"]
        GroupCreation["Create Group based on<br/>record type and comp_id"]
        AtomCreation["Create Atom with<br/>coordinates and properties"]
        AltLocHandling["Handle alternate<br/>locations if present"]
        ModelHandling["Handle multiple<br/>NMR models"]
    end
    
    subgraph "Output Objects"
        ChainImpl["ChainImpl objects"]
        GroupObjects["AminoAcidImpl<br/>NucleotideImpl<br/>HetatomImpl"]
        AtomImpl["AtomImpl objects"]
        AltLocGroups["Alternate location groups"]
    end
    
    labelAsymId --> ChainLookup
    labelCompId --> GroupCreation
    authSeqId --> GroupCreation
    groupPDB --> GroupCreation
    
    labelAtomId --> AtomCreation
    cartnXYZ --> AtomCreation
    labelAltId --> AltLocHandling
    
    ChainLookup --> ChainImpl
    GroupCreation --> GroupObjects
    AtomCreation --> AtomImpl
    AltLocHandling --> AltLocGroups
    ModelHandling --> ChainImpl
```

**Sources:** [biojava-structure/src/main/java/org/biojava/nbio/structure/io/cif/CifStructureConsumerImpl.java:177-370](), [biojava-structure/src/main/java/org/biojava/nbio/structure/io/cif/CifStructureConsumerImpl.java:412-460]()

## Binary vs Text CIF Processing

BioJava supports both text-based mmCIF and binary CIF formats through unified interfaces, with format-specific optimizations handled by the underlying RCSB CIF library.

| Aspect | Text CIF (mmCIF) | Binary CIF (BCIF) |
|--------|------------------|-------------------|
| **File Extensions** | `.cif`, `.mmcif`, `.cif.gz`, `.mmcif.gz` | `.bcif`, `.bcif.gz` |
| **Reader Class** | `CifFileReader` | `BcifFileReader` |
| **Processing** | Same `CifStructureConsumerImpl` | Same `CifStructureConsumerImpl` |
| **Performance** | Standard text parsing | Optimized binary parsing |
| **File Size** | Larger (human-readable) | Smaller (compressed binary) |
| **Encoding** | UTF-8 text | Binary with compression |

The key insight is that both formats converge to the same `CifFile` object representation after parsing, allowing the same consumer implementation to handle both formats transparently.

**Sources:** [biojava-structure/src/main/java/org/biojava/nbio/structure/io/CifFileReader.java:33-39](), [biojava-structure/src/main/java/org/biojava/nbio/structure/io/BcifFileReader.java:33-37]()

## CIF Writing and Export

BioJava also supports writing Structure objects back to CIF format through the `AbstractCifFileSupplier` system and `CifStructureConverter` utilities.

```mermaid
graph LR
    subgraph "Input"
        Structure["Structure Object"]
        Chain["Individual Chain"]
    end
    
    subgraph "Conversion Layer"
        CifStructureSupplierImpl["CifStructureSupplierImpl"]
        CifChainSupplierImpl["CifChainSupplierImpl"]
        AbstractCifFileSupplier["AbstractCifFileSupplier"]
    end
    
    subgraph "Output Formats"
        TextOutput["toText()<br/>mmCIF String"]
        BinaryOutput["toBinary()<br/>BCIF bytes"]
        FileOutput["toTextFile()<br/>toBinaryFile()"]
    end
    
    Structure --> CifStructureSupplierImpl
    Chain --> CifChainSupplierImpl
    
    CifStructureSupplierImpl --> AbstractCifFileSupplier
    CifChainSupplierImpl --> AbstractCifFileSupplier
    
    AbstractCifFileSupplier --> TextOutput
    AbstractCifFileSupplier --> BinaryOutput
    AbstractCifFileSupplier --> FileOutput
```

**Sources:** [biojava-structure/src/main/java/org/biojava/nbio/structure/io/cif/AbstractCifFileSupplier.java:30-137](), [biojava-structure/src/main/java/org/biojava/nbio/structure/io/cif/CifStructureConverter.java:171-241]()

## Integration with File Parsing Parameters

The CIF processing system integrates with BioJava's `FileParsingParameters` to control parsing behavior:

- **Header-only parsing**: When `params.isHeaderOnly()` is true, `consumeAtomSite()` returns early, processing only metadata
- **CA-only parsing**: When `params.isParseCAOnly()` is true, only CA atoms are processed for protein structures
- **SeqRes alignment**: The `params.isAlignSeqRes()` controls whether sequence alignment between SEQRES and ATOM records is performed

**Sources:** [biojava-structure/src/main/java/org/biojava/nbio/structure/io/cif/CifStructureConsumerImpl.java:156-158](), [biojava-structure/src/main/java/org/biojava/nbio/structure/io/cif/CifStructureConsumerImpl.java:178-180](), [biojava-structure/src/main/java/org/biojava/nbio/structure/io/cif/CifStructureConsumerImpl.java:321-325]()

---