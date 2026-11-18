# File Format Support and Parsing

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [biojava-alignment/src/test/java/org/biojava/nbio/alignment/TestDNAAlignment.java](biojava-alignment/src/test/java/org/biojava/nbio/alignment/TestDNAAlignment.java)
- [biojava-core/src/main/java/org/biojava/nbio/core/sequence/AccessionID.java](biojava-core/src/main/java/org/biojava/nbio/core/sequence/AccessionID.java)
- [biojava-core/src/main/java/org/biojava/nbio/core/sequence/ChromosomeSequence.java](biojava-core/src/main/java/org/biojava/nbio/core/sequence/ChromosomeSequence.java)
- [biojava-core/src/main/java/org/biojava/nbio/core/sequence/ProteinSequence.java](biojava-core/src/main/java/org/biojava/nbio/core/sequence/ProteinSequence.java)
- [biojava-core/src/main/java/org/biojava/nbio/core/sequence/features/DatabaseReferenceInterface.java](biojava-core/src/main/java/org/biojava/nbio/core/sequence/features/DatabaseReferenceInterface.java)
- [biojava-core/src/main/java/org/biojava/nbio/core/sequence/features/FeatureRetriever.java](biojava-core/src/main/java/org/biojava/nbio/core/sequence/features/FeatureRetriever.java)
- [biojava-core/src/main/java/org/biojava/nbio/core/sequence/features/FeaturesKeyWordInterface.java](biojava-core/src/main/java/org/biojava/nbio/core/sequence/features/FeaturesKeyWordInterface.java)
- [biojava-core/src/main/java/org/biojava/nbio/core/sequence/io/GenbankReader.java](biojava-core/src/main/java/org/biojava/nbio/core/sequence/io/GenbankReader.java)
- [biojava-core/src/main/java/org/biojava/nbio/core/sequence/io/GenbankSequenceParser.java](biojava-core/src/main/java/org/biojava/nbio/core/sequence/io/GenbankSequenceParser.java)
- [biojava-core/src/main/java/org/biojava/nbio/core/sequence/io/GenbankWriter.java](biojava-core/src/main/java/org/biojava/nbio/core/sequence/io/GenbankWriter.java)
- [biojava-core/src/main/java/org/biojava/nbio/core/sequence/io/GenbankWriterHelper.java](biojava-core/src/main/java/org/biojava/nbio/core/sequence/io/GenbankWriterHelper.java)
- [biojava-core/src/main/java/org/biojava/nbio/core/sequence/io/GenericGenbankHeaderFormat.java](biojava-core/src/main/java/org/biojava/nbio/core/sequence/io/GenericGenbankHeaderFormat.java)
- [biojava-core/src/main/java/org/biojava/nbio/core/sequence/io/GenericGenbankHeaderParser.java](biojava-core/src/main/java/org/biojava/nbio/core/sequence/io/GenericGenbankHeaderParser.java)
- [biojava-core/src/main/java/org/biojava/nbio/core/sequence/loader/GenbankProxySequenceReader.java](biojava-core/src/main/java/org/biojava/nbio/core/sequence/loader/GenbankProxySequenceReader.java)
- [biojava-core/src/main/java/org/biojava/nbio/core/sequence/location/InsdcParser.java](biojava-core/src/main/java/org/biojava/nbio/core/sequence/location/InsdcParser.java)
- [biojava-core/src/main/java/org/biojava/nbio/core/util/InputStreamProvider.java](biojava-core/src/main/java/org/biojava/nbio/core/util/InputStreamProvider.java)
- [biojava-core/src/test/java/org/biojava/nbio/core/sequence/io/GenbankReaderTest.java](biojava-core/src/test/java/org/biojava/nbio/core/sequence/io/GenbankReaderTest.java)
- [biojava-core/src/test/java/org/biojava/nbio/core/sequence/io/GenbankWriterTest.java](biojava-core/src/test/java/org/biojava/nbio/core/sequence/io/GenbankWriterTest.java)
- [biojava-core/src/test/java/org/biojava/nbio/core/sequence/loader/GenbankProxySequenceReaderTest.java](biojava-core/src/test/java/org/biojava/nbio/core/sequence/loader/GenbankProxySequenceReaderTest.java)
- [biojava-core/src/test/java/org/biojava/nbio/core/sequence/loader/SimpleGenbankProxySequenceReaderTest.java](biojava-core/src/test/java/org/biojava/nbio/core/sequence/loader/SimpleGenbankProxySequenceReaderTest.java)
- [biojava-core/src/test/java/org/biojava/nbio/core/sequence/location/LocationParserTest.java](biojava-core/src/test/java/org/biojava/nbio/core/sequence/location/LocationParserTest.java)
- [biojava-core/src/test/java/org/biojava/nbio/core/sequence/location/LocationTest.java](biojava-core/src/test/java/org/biojava/nbio/core/sequence/location/LocationTest.java)
- [biojava-core/src/test/java/org/biojava/nbio/core/sequence/location/TargetedLocationParserTest.java](biojava-core/src/test/java/org/biojava/nbio/core/sequence/location/TargetedLocationParserTest.java)
- [biojava-core/src/test/resources/with_joins.gb](biojava-core/src/test/resources/with_joins.gb)
- [biojava-integrationtest/src/test/java/org/biojava/nbio/structure/test/io/TestLongPdbVsMmCifParsing.java](biojava-integrationtest/src/test/java/org/biojava/nbio/structure/test/io/TestLongPdbVsMmCifParsing.java)
- [biojava-structure/src/main/java/demo/DemoMmtfWriter.java](biojava-structure/src/main/java/demo/DemoMmtfWriter.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/Model.java](biojava-structure/src/main/java/org/biojava/nbio/structure/Model.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/Structure.java](biojava-structure/src/main/java/org/biojava/nbio/structure/Structure.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/StructureImpl.java](biojava-structure/src/main/java/org/biojava/nbio/structure/StructureImpl.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/StructureTools.java](biojava-structure/src/main/java/org/biojava/nbio/structure/StructureTools.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/SubstructureIdentifier.java](biojava-structure/src/main/java/org/biojava/nbio/structure/SubstructureIdentifier.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/align/util/ResourceManager.java](biojava-structure/src/main/java/org/biojava/nbio/structure/align/util/ResourceManager.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/io/EntityFinder.java](biojava-structure/src/main/java/org/biojava/nbio/structure/io/EntityFinder.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/io/FileConvert.java](biojava-structure/src/main/java/org/biojava/nbio/structure/io/FileConvert.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/io/PDBFileParser.java](biojava-structure/src/main/java/org/biojava/nbio/structure/io/PDBFileParser.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/io/mmtf/MmtfActions.java](biojava-structure/src/main/java/org/biojava/nbio/structure/io/mmtf/MmtfActions.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/io/mmtf/MmtfStructureReader.java](biojava-structure/src/main/java/org/biojava/nbio/structure/io/mmtf/MmtfStructureReader.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/io/mmtf/MmtfStructureWriter.java](biojava-structure/src/main/java/org/biojava/nbio/structure/io/mmtf/MmtfStructureWriter.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/io/mmtf/MmtfSummaryDataBean.java](biojava-structure/src/main/java/org/biojava/nbio/structure/io/mmtf/MmtfSummaryDataBean.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/io/mmtf/MmtfUtils.java](biojava-structure/src/main/java/org/biojava/nbio/structure/io/mmtf/MmtfUtils.java)
- [biojava-structure/src/test/java/org/biojava/nbio/structure/io/TestDifficultMmCIFFiles.java](biojava-structure/src/test/java/org/biojava/nbio/structure/io/TestDifficultMmCIFFiles.java)
- [biojava-structure/src/test/java/org/biojava/nbio/structure/io/TestNonDepositedFiles.java](biojava-structure/src/test/java/org/biojava/nbio/structure/io/TestNonDepositedFiles.java)
- [biojava-structure/src/test/java/org/biojava/nbio/structure/io/TestParseMmCIFFeatures.java](biojava-structure/src/test/java/org/biojava/nbio/structure/io/TestParseMmCIFFeatures.java)
- [biojava-structure/src/test/java/org/biojava/nbio/structure/io/TestTitleParsing.java](biojava-structure/src/test/java/org/biojava/nbio/structure/io/TestTitleParsing.java)
- [biojava-structure/src/test/java/org/biojava/nbio/structure/io/mmtf/TestBondFinding.java](biojava-structure/src/test/java/org/biojava/nbio/structure/io/mmtf/TestBondFinding.java)
- [biojava-structure/src/test/java/org/biojava/nbio/structure/io/mmtf/TestMmtfRoundTrip.java](biojava-structure/src/test/java/org/biojava/nbio/structure/io/mmtf/TestMmtfRoundTrip.java)
- [biojava-structure/src/test/java/org/biojava/nbio/structure/io/mmtf/TestMmtfStructureReader.java](biojava-structure/src/test/java/org/biojava/nbio/structure/io/mmtf/TestMmtfStructureReader.java)
- [biojava-structure/src/test/java/org/biojava/nbio/structure/io/mmtf/TestMmtfStructureWriter.java](biojava-structure/src/test/java/org/biojava/nbio/structure/io/mmtf/TestMmtfStructureWriter.java)
- [biojava-structure/src/test/java/org/biojava/nbio/structure/io/mmtf/TestMmtfUtils.java](biojava-structure/src/test/java/org/biojava/nbio/structure/io/mmtf/TestMmtfUtils.java)
- [biojava-structure/src/test/resources/org/biojava/nbio/structure/io/3zyb_truncated.pdb.gz](biojava-structure/src/test/resources/org/biojava/nbio/structure/io/3zyb_truncated.pdb.gz)
- [biojava-structure/src/test/resources/org/biojava/nbio/structure/io/difficult_mmcif_quoting.cif](biojava-structure/src/test/resources/org/biojava/nbio/structure/io/difficult_mmcif_quoting.cif)
- [biojava-structure/src/test/resources/org/biojava/nbio/structure/io/mmtf/4CUP.cif](biojava-structure/src/test/resources/org/biojava/nbio/structure/io/mmtf/4CUP.cif)

</details>



This document covers BioJava's comprehensive file format support and parsing capabilities for biological data. BioJava provides parsers for multiple structural and sequence file formats, with a unified API for accessing parsed data through common data models.

For information about the core data structures used to represent parsed data, see [Data Model and Structure Representation](#2.1). For details about structure caching and retrieval mechanisms, see [Structure Caching and Retrieval](#2.3).

## Supported File Formats

BioJava supports parsing and writing for the following major biological data formats:

| Format | Type | Parser Class | Writer Support | Description |
|--------|------|--------------|----------------|-------------|
| PDB | Structure | `PDBFileParser` | Yes (`FileConvert`) | Legacy Protein Data Bank format |
| mmCIF | Structure | `SimpleMMcifConsumer` | Yes (`CifStructureConverter`) | Modern crystallographic format |
| MMTF | Structure | `MmtfStructureReader` | Yes (`MmtfStructureWriter`) | Binary compressed format |
| CIF | Structure | `CifStructureConsumerImpl` | Yes | Text-based crystallographic format |
| GenBank | Sequence | `GenbankSequenceParser` | Yes (`GenbankWriter`) | NCBI sequence format |

## Parser Architecture Overview

The following diagram shows the high-level architecture of BioJava's file format parsing system:

```mermaid
graph TD
    subgraph "Input Sources"
        PDBFiles["PDB Files (.pdb)"]
        mmCIFFiles["mmCIF Files (.cif)"] 
        MMTFFiles["MMTF Files (.mmtf)"]
        CIFFiles["CIF Files (.cif)"]
        GenbankFiles["GenBank Files (.gb)"]
    end
    
    subgraph "Format Parsers"
        PDBFileParser["PDBFileParser"]
        SimpleMMcifConsumer["SimpleMMcifConsumer"] 
        MmtfStructureReader["MmtfStructureReader"]
        CifStructureConsumerImpl["CifStructureConsumerImpl"]
        GenbankSequenceParser["GenbankSequenceParser"]
    end
    
    subgraph "Core Data Models"
        Structure["Structure"]
        Chain["Chain"]
        Group["Group"] 
        Atom["Atom"]
        Sequence["AbstractSequence"]
    end
    
    subgraph "Output & Conversion"
        FileConvert["FileConvert"]
        MmtfStructureWriter["MmtfStructureWriter"]
        CifStructureConverter["CifStructureConverter"]
    end
    
    PDBFiles --> PDBFileParser
    mmCIFFiles --> SimpleMMcifConsumer
    MMTFFiles --> MmtfStructureReader
    CIFFiles --> CifStructureConsumerImpl
    GenbankFiles --> GenbankSequenceParser
    
    PDBFileParser --> Structure
    SimpleMMcifConsumer --> Structure
    MmtfStructureReader --> Structure
    CifStructureConsumerImpl --> Structure
    GenbankSequenceParser --> Sequence
    
    Structure --> Chain
    Chain --> Group
    Group --> Atom
    
    Structure --> FileConvert
    Structure --> MmtfStructureWriter
    Structure --> CifStructureConverter
```

Sources: [biojava-structure/src/main/java/org/biojava/nbio/structure/io/PDBFileParser.java:85-137](), [biojava-structure/src/main/java/org/biojava/nbio/structure/io/mmtf/MmtfStructureReader.java:76-138](), [biojava-core/src/main/java/org/biojava/nbio/core/sequence/io/GenbankSequenceParser.java:61-84]()

## Structure File Format Parsers

### PDB Format Parser

The `PDBFileParser` handles the legacy PDB text format, which remains widely used despite its limitations. The parser processes all standard PDB record types including HEADER, ATOM, HETATM, SEQRES, and metadata records.

```mermaid
graph TD
    subgraph "PDB Parsing Pipeline"
        InputPDB["PDB File Input"]
        PDBFileParser["PDBFileParser"]
        RecordHandlers["Record Type Handlers"]
        DataStructures["Intermediate Data"]
        StructureBuilder["Structure Assembly"]
        OutputStructure["Structure Object"]
    end
    
    subgraph "Record Handlers"
        HeaderHandler["pdb_HEADER_Handler"]
        AtomHandler["ATOM/HETATM Processing"] 
        SeqresHandler["pdb_SEQRES_Handler"]
        HelixHandler["pdb_HELIX_Handler"]
        SheetHandler["pdb_SHEET_Handler"]
        ConnectHandler["Connection Processing"]
    end
    
    InputPDB --> PDBFileParser
    PDBFileParser --> RecordHandlers
    RecordHandlers --> HeaderHandler
    RecordHandlers --> AtomHandler
    RecordHandlers --> SeqresHandler
    RecordHandlers --> HelixHandler
    RecordHandlers --> SheetHandler
    RecordHandlers --> ConnectHandler
    RecordHandlers --> DataStructures
    DataStructures --> StructureBuilder
    StructureBuilder --> OutputStructure
```

Key features of the PDB parser:
- **Legacy format detection**: Automatically detects older PDB format versions [biojava-structure/src/main/java/org/biojava/nbio/structure/io/PDBFileParser.java:393-401]()
- **Flexible atom parsing**: Handles both standard and non-standard atom records [biojava-structure/src/main/java/org/biojava/nbio/structure/io/PDBFileParser.java:1845-1920]()
- **Secondary structure**: Parses HELIX, SHEET, and TURN records [biojava-structure/src/main/java/org/biojava/nbio/structure/io/PDBFileParser.java:468-653]()
- **Connection handling**: Processes CONECT records for bond information [biojava-structure/src/main/java/org/biojava/nbio/structure/io/PDBFileParser.java:3119-3156]()

Sources: [biojava-structure/src/main/java/org/biojava/nbio/structure/io/PDBFileParser.java:85-300]()

### MMTF Format Support

MMTF (MacroMolecular Transmission Format) is a binary format designed for efficient storage and transmission of structural data. BioJava provides comprehensive MMTF support through the `MmtfStructureReader` and `MmtfStructureWriter` classes.

```mermaid
graph LR
    subgraph "MMTF Reading"
        MMTFFile["MMTF Binary File"]
        GenericDecoder["GenericDecoder"]
        MmtfStructureReader["MmtfStructureReader"]
        Structure1["Structure"]
    end
    
    subgraph "MMTF Writing" 
        Structure2["Structure"]
        MmtfStructureWriter["MmtfStructureWriter"]
        AdapterToStructureData["AdapterToStructureData"]
        MMTFOutput["MMTF Binary Output"]
    end
    
    MMTFFile --> GenericDecoder
    GenericDecoder --> MmtfStructureReader
    MmtfStructureReader --> Structure1
    
    Structure2 --> MmtfStructureWriter
    MmtfStructureWriter --> AdapterToStructureData
    AdapterToStructureData --> MMTFOutput
```

The MMTF reader implements the `StructureAdapterInterface` and provides callbacks for processing structural data:
- **Initialization**: `initStructure()` sets up containers for bonds, atoms, groups, and chains [biojava-structure/src/main/java/org/biojava/nbio/structure/io/mmtf/MmtfStructureReader.java:167-175]()
- **Hierarchical building**: Processes models, chains, groups, and atoms in sequence [biojava-structure/src/main/java/org/biojava/nbio/structure/io/mmtf/MmtfStructureReader.java:180-260]()
- **Bond reconstruction**: Handles both intra-group and inter-group bonds [biojava-structure/src/main/java/org/biojava/nbio/structure/io/mmtf/MmtfStructureReader.java:338-363]()

Sources: [biojava-structure/src/main/java/org/biojava/nbio/structure/io/mmtf/MmtfStructureReader.java:76-166](), [biojava-structure/src/main/java/org/biojava/nbio/structure/io/mmtf/MmtfStructureWriter.java:51-129]()

### High-Level I/O Operations

BioJava provides convenient high-level classes for common file operations:

```mermaid
graph TD
    subgraph "High-Level I/O API"
        MmtfActions["MmtfActions"]
        FileConvert["FileConvert"]
        StructureIO["StructureIO"]
    end
    
    subgraph "Operations"
        ReadFile["readFromFile()"]
        WriteFile["writeToFile()"]
        ReadStream["readFromInputStream()"]
        WriteStream["writeToOutputStream()"]
        ConvertPDB["toPDB()"]
        ConvertMMCIF["toMMCIF()"]
    end
    
    MmtfActions --> ReadFile
    MmtfActions --> WriteFile
    MmtfActions --> ReadStream
    MmtfActions --> WriteStream
    FileConvert --> ConvertPDB
    FileConvert --> ConvertMMCIF
```

The `MmtfActions` class provides static methods for common MMTF operations:
- Reading from files and streams [biojava-structure/src/main/java/org/biojava/nbio/structure/io/mmtf/MmtfActions.java:48-55]()
- Writing to files and streams [biojava-structure/src/main/java/org/biojava/nbio/structure/io/mmtf/MmtfActions.java:63-86]()

Sources: [biojava-structure/src/main/java/org/biojava/nbio/structure/io/mmtf/MmtfActions.java:40-101](), [biojava-structure/src/main/java/org/biojava/nbio/structure/io/FileConvert.java:53-89]()

## Sequence File Format Parsers

### GenBank Format Parser

The `GenbankSequenceParser` handles NCBI GenBank format files, which contain sequence data along with extensive annotations and metadata. The parser supports both nucleotide and protein sequences.

```mermaid
graph TD
    subgraph "GenBank Parsing Pipeline"
        GenbankFile["GenBank File (.gb)"]
        GenbankSequenceParser["GenbankSequenceParser"]
        SectionParsers["Section Parsers"]
        Features["Feature Extraction"]
        SequenceData["Sequence Assembly"]
        Output["AbstractSequence + Features"]
    end
    
    subgraph "Section Processing"
        LocusHandler["parseLocusTag()"]
        DefinitionHandler["parseDefinitionTag()"]
        FeaturesHandler["parseFeatureTag()"]
        SequenceHandler["parseStartSequenceTag()"]
        ReferenceHandler["parseReferenceTag()"]
    end
    
    GenbankFile --> GenbankSequenceParser
    GenbankSequenceParser --> SectionParsers
    SectionParsers --> LocusHandler
    SectionParsers --> DefinitionHandler
    SectionParsers --> FeaturesHandler
    SectionParsers --> SequenceHandler
    SectionParsers --> ReferenceHandler
    SectionParsers --> Features
    SectionParsers --> SequenceData
    Features --> Output
    SequenceData --> Output
```

Key parsing capabilities:
- **LOCUS detection**: Determines sequence type (DNA, RNA, protein) and length [biojava-core/src/main/java/org/biojava/nbio/core/sequence/io/GenbankSequenceParser.java:308-378]()
- **Feature annotation**: Parses FEATURES section with qualifiers and locations [biojava-core/src/main/java/org/biojava/nbio/core/sequence/io/GenbankSequenceParser.java:192-254]()
- **Reference handling**: Extracts publication information [biojava-core/src/main/java/org/biojava/nbio/core/sequence/io/GenbankSequenceParser.java:260-272]()
- **Sequence reconstruction**: Assembles sequence data from ORIGIN section [biojava-core/src/main/java/org/biojava/nbio/core/sequence/io/GenbankSequenceParser.java:179-190]()

The parser uses regular expressions for structured data extraction:
- Locus line parsing with multiple patterns [biojava-core/src/main/java/org/biojava/nbio/core/sequence/io/GenbankSequenceParser.java:113-115]()
- Version information extraction [biojava-core/src/main/java/org/biojava/nbio/core/sequence/io/GenbankSequenceParser.java:117]()
- Database cross-reference parsing [biojava-core/src/main/java/org/biojava/nbio/core/sequence/io/GenbankSequenceParser.java:122]()

Sources: [biojava-core/src/main/java/org/biojava/nbio/core/sequence/io/GenbankSequenceParser.java:61-500]()

### GenBank Reader Integration

The `GenbankReader` class provides a high-level interface for processing GenBank files, integrating the parser with sequence creation and header processing:

```mermaid
graph LR
    subgraph "GenBank Reader Workflow"
        Input["BufferedReader"]
        GenbankReader["GenbankReader<T,C>"]
        SequenceParser["GenbankSequenceParser"]
        HeaderParser["SequenceHeaderParserInterface"]
        SequenceCreator["SequenceCreatorInterface"]
        OutputMap["Map<String, T>"]
    end
    
    Input --> GenbankReader
    GenbankReader --> SequenceParser
    GenbankReader --> HeaderParser
    GenbankReader --> SequenceCreator
    SequenceParser --> OutputMap
    HeaderParser --> OutputMap
    SequenceCreator --> OutputMap
```

Sources: [biojava-core/src/main/java/org/biojava/nbio/core/sequence/io/GenbankReader.java:56-150]()

## Format Conversion and Interoperability

BioJava provides extensive format conversion capabilities through the `FileConvert` class and format-specific converters:

```mermaid
graph TD
    subgraph "Format Conversion System"
        StructureInput["Structure Object"]
        FileConvert["FileConvert"]
        FormatConverters["Format-Specific Converters"]
        Outputs["Multiple Output Formats"]
    end
    
    subgraph "Conversion Methods"
        ToPDB["toPDB()"]
        ToMMCIF["toMMCIF()"] 
        ToXML["toXML()"]
        ToBinaryCIF["Binary CIF Support"]
    end
    
    subgraph "Writer Classes"
        MmtfStructureWriter["MmtfStructureWriter"]
        CifStructureConverter["CifStructureConverter"]
        PDBWriter["PDB Format Writer"]
    end
    
    StructureInput --> FileConvert
    FileConvert --> ToPDB
    FileConvert --> ToMMCIF
    FileConvert --> ToXML
    
    StructureInput --> MmtfStructureWriter
    StructureInput --> CifStructureConverter
    StructureInput --> PDBWriter
    
    ToPDB --> Outputs
    ToMMCIF --> Outputs
    ToXML --> Outputs
    ToBinaryCIF --> Outputs
```

The conversion system supports:
- **PDB output**: Complete PDB format writing with all record types [biojava-structure/src/main/java/org/biojava/nbio/structure/io/FileConvert.java:137-200]()
- **Connection handling**: CONECT record generation from bond information [biojava-structure/src/main/java/org/biojava/nbio/structure/io/FileConvert.java:115-132]()
- **Header preservation**: Maintains metadata across format conversions [biojava-structure/src/main/java/org/biojava/nbio/structure/io/FileConvert.java:149-171]()

Sources: [biojava-structure/src/main/java/org/biojava/nbio/structure/io/FileConvert.java:53-200](), [biojava-structure/src/main/java/org/biojava/nbio/structure/io/mmtf/MmtfStructureWriter.java:51-129]()

## Parser Configuration and Parameters

Most parsers support extensive configuration through parameter classes:

### File Parsing Parameters

The `FileParsingParameters` class controls parsing behavior across different formats:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `alignSeqRes` | `true` | Align SEQRES and ATOM records |
| `headerOnly` | `false` | Parse only header information |
| `maxAtoms` | `1000000` | Maximum atoms to parse |
| `atomCaThreshold` | `50000` | Switch to CA-only above this limit |
| `parseSecStruc` | `true` | Include secondary structure |
| `createAtomBonds` | `true` | Generate chemical bonds |

These parameters affect memory usage and parsing speed, allowing optimization for different use cases.

Sources: [biojava-structure/src/main/java/org/biojava/nbio/structure/io/PDBFileParser.java:245-296]()

## Error Handling and Validation

BioJava's parsers include comprehensive error handling and validation:

- **Format validation**: Automatic detection of file format issues
- **Graceful degradation**: Continue parsing when encountering minor errors
- **Detailed logging**: Extensive debug information for troubleshooting
- **Exception hierarchy**: Structured exception types for different error conditions

The parsers log warnings for recoverable issues while throwing exceptions for critical parsing failures, ensuring robust handling of real-world data files that may contain format variations or errors.

Sources: [biojava-structure/src/main/java/org/biojava/nbio/structure/io/PDBFileParser.java:141-142](), [biojava-core/src/main/java/org/biojava/nbio/core/sequence/io/GenbankSequenceParser.java:76]()

---