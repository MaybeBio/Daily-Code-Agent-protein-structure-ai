# Specialized Analysis Modules

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [biojava-alignment/src/test/java/org/biojava/nbio/alignment/NeedlemanWunschTest.java](biojava-alignment/src/test/java/org/biojava/nbio/alignment/NeedlemanWunschTest.java)
- [biojava-alignment/src/test/java/org/biojava/nbio/alignment/aaindex/TestAAINDEXLoading.java](biojava-alignment/src/test/java/org/biojava/nbio/alignment/aaindex/TestAAINDEXLoading.java)
- [biojava-alignment/src/test/java/org/biojava/nbio/alignment/io/TestStockholmParser.java](biojava-alignment/src/test/java/org/biojava/nbio/alignment/io/TestStockholmParser.java)
- [biojava-genome/src/main/java/org/biojava/nbio/genome/io/fastq/package-info.java](biojava-genome/src/main/java/org/biojava/nbio/genome/io/fastq/package-info.java)
- [biojava-genome/src/main/java/org/biojava/nbio/genome/parsers/twobit/TwoBitFacade.java](biojava-genome/src/main/java/org/biojava/nbio/genome/parsers/twobit/TwoBitFacade.java)
- [biojava-genome/src/main/java/org/biojava/nbio/genome/util/ChromosomeMappingTools.java](biojava-genome/src/main/java/org/biojava/nbio/genome/util/ChromosomeMappingTools.java)
- [biojava-genome/src/main/java/org/biojava/nbio/genome/util/ProteinMappingTools.java](biojava-genome/src/main/java/org/biojava/nbio/genome/util/ProteinMappingTools.java)
- [biojava-genome/src/main/resources/log4j2.xml](biojava-genome/src/main/resources/log4j2.xml)
- [biojava-genome/src/test/java/org/biojava/nbio/genome/FeatureListTest.java](biojava-genome/src/test/java/org/biojava/nbio/genome/FeatureListTest.java)
- [biojava-genome/src/test/java/org/biojava/nbio/genome/TestChromosomeMappingTools.java](biojava-genome/src/test/java/org/biojava/nbio/genome/TestChromosomeMappingTools.java)
- [biojava-genome/src/test/java/org/biojava/nbio/genome/TestGenomeMapping.java](biojava-genome/src/test/java/org/biojava/nbio/genome/TestGenomeMapping.java)
- [biojava-integrationtest/src/test/java/org/biojava/nbio/structure/test/align/TestSimilarityCalc.java](biojava-integrationtest/src/test/java/org/biojava/nbio/structure/test/align/TestSimilarityCalc.java)
- [biojava-structure-gui/src/main/java/org/biojava/nbio/structure/align/gui/jmol/JmolTools.java](biojava-structure-gui/src/main/java/org/biojava/nbio/structure/align/gui/jmol/JmolTools.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/basepairs/BasePairParameters.java](biojava-structure/src/main/java/org/biojava/nbio/structure/basepairs/BasePairParameters.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/basepairs/MismatchedBasePairParameters.java](biojava-structure/src/main/java/org/biojava/nbio/structure/basepairs/MismatchedBasePairParameters.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/basepairs/TertiaryBasePairParameters.java](biojava-structure/src/main/java/org/biojava/nbio/structure/basepairs/TertiaryBasePairParameters.java)
- [biojava-structure/src/test/java/org/biojava/nbio/structure/basepairs/TestBasePairParameters.java](biojava-structure/src/test/java/org/biojava/nbio/structure/basepairs/TestBasePairParameters.java)

</details>



This page documents BioJava's specialized analysis modules that provide domain-specific computational tools for genomics and nucleic acid structural analysis. These modules extend beyond the core data structures and file format support to offer advanced analytical capabilities for biological sequence analysis.

The specialized analysis modules are organized into two main categories: genomic analysis tools for working with chromosomal coordinates and coding sequences, and nucleic acid structure analysis tools for calculating base pair parameters and structural properties. For detailed information about protein structure analysis tools, see [Structural Analysis Tools](#3). For basic sequence alignment algorithms, see [Core Architecture](#2).

## Module Architecture Overview

The specialized analysis modules build upon BioJava's core data structures to provide advanced analytical capabilities:

```mermaid
graph TB
    subgraph "Core Foundation"
        Structure["Structure Objects"]
        Sequences["Sequence Objects"] 
        GenomeData["Genomic Data"]
    end
    
    subgraph "Genomic Analysis Module (4.1)"
        ChromosomeMappingTools["ChromosomeMappingTools"]
        ProteinMappingTools["ProteinMappingTools"]
        TwoBitFacade["TwoBitFacade"]
        GeneChromosomePosition["GeneChromosomePosition"]
    end
    
    subgraph "Nucleic Acid Structure Analysis (4.2)"
        BasePairParameters["BasePairParameters"]
        TertiaryBasePairParameters["TertiaryBasePairParameters"] 
        MismatchedBasePairParameters["MismatchedBasePairParameters"]
    end
    
    subgraph "Analysis Outputs"
        CDSMapping["CDS Coordinate Mapping"]
        ExonStructure["Exon Structure Analysis"]
        BaseParameters["Base Pair Parameters"]
        StepParameters["Base-pair Step Parameters"]
    end
    
    GenomeData --> ChromosomeMappingTools
    GenomeData --> TwoBitFacade
    Sequences --> ProteinMappingTools
    Structure --> BasePairParameters
    Structure --> TertiaryBasePairParameters
    Structure --> MismatchedBasePairParameters
    
    ChromosomeMappingTools --> CDSMapping
    ChromosomeMappingTools --> ExonStructure
    BasePairParameters --> BaseParameters
    BasePairParameters --> StepParameters
    
    style ChromosomeMappingTools fill:#f9f9f9
    style BasePairParameters fill:#f9f9f9
```

Sources: [biojava-genome/src/main/java/org/biojava/nbio/genome/util/ChromosomeMappingTools.java:1-972](), [biojava-structure/src/main/java/org/biojava/nbio/structure/basepairs/BasePairParameters.java:1-805]()

## Genomic Analysis Tools

The genomic analysis module provides sophisticated tools for working with chromosomal coordinates, coding sequences, and genomic feature mapping. The primary entry point is the `ChromosomeMappingTools` class, which handles bidirectional coordinate transformations between genomic and coding sequence positions.

### Coordinate Mapping System

```mermaid
flowchart LR
    subgraph "Input Data"
        ExonStarts["List<Integer> exonStarts"]
        ExonEnds["List<Integer> exonEnds"] 
        CDSStart["int cdsStart"]
        CDSEnd["int cdsEnd"]
        Orientation["Character orientation"]
    end
    
    subgraph "ChromosomeMappingTools"
        GetChromPos["getChromosomePosForCDScoordinate()"]
        GetCDSPos["getCDSPosForChromosomeCoordinate()"]
        GetCDSLength["getCDSLength()"]
        FormatExon["formatExonStructure()"]
        GetCDSRanges["getCDSExonRanges()"]
    end
    
    subgraph "Output Results"
        ChromPos["ChromPos coordinates"]
        CDSPosition["CDS position"]
        CDSLength["CDS length in nucleotides"]
        ExonFormat["Formatted exon display"]
        RangeList["List<Range<Integer>>"]
    end
    
    ExonStarts --> GetChromPos
    ExonEnds --> GetChromPos
    CDSStart --> GetChromPos
    CDSEnd --> GetChromPos
    
    GetChromPos --> ChromPos
    GetCDSPos --> CDSPosition
    GetCDSLength --> CDSLength
    FormatExon --> ExonFormat
    GetCDSRanges --> RangeList
```

The coordinate mapping system handles both forward and reverse strand orientations using specialized algorithms:

| Method | Purpose | Input | Output |
|--------|---------|-------|--------|
| `getChromosomePosForCDScoordinate()` | Maps CDS position to genomic coordinate | CDS nucleotide position, gene data | ChromPos object |
| `getCDSPosForChromosomeCoordinate()` | Maps genomic coordinate to CDS position | Chromosome coordinate, gene data | CDS position (int) |
| `formatExonStructure()` | Creates human-readable exon display | GeneChromosomePosition | Formatted string |
| `getCDSLength()` | Calculates coding sequence length | Gene chromosome position | Length in nucleotides |

Sources: [biojava-genome/src/main/java/org/biojava/nbio/genome/util/ChromosomeMappingTools.java:232-256](), [biojava-genome/src/main/java/org/biojava/nbio/genome/util/ChromosomeMappingTools.java:779-793](), [biojava-genome/src/main/java/org/biojava/nbio/genome/util/ChromosomeMappingTools.java:210-224]()

### Sequence Extraction and Processing

The genomic module integrates with external genome data sources through the `TwoBitFacade` class, which provides efficient access to compressed genome files:

```mermaid
graph TB
    subgraph "Genome Data Sources"
        TwoBitFile["2bit Genome Files"]
        RemoteGenome["Remote Genome URLs"]
    end
    
    subgraph "TwoBitFacade Processing"
        TwoBitParser["TwoBitParser"]
        ChromosomeSelection["setChromosome()"]
        SequenceExtraction["getSequence()"]
    end
    
    subgraph "ChromosomeMappingTools Integration"
        GetTranscriptDNA["getTranscriptDNASequence()"]
        CDSRegions["getCDSRegions()"] 
        DNAConstruction["DNA sequence building"]
    end
    
    subgraph "Output Products"
        DNASequence["DNASequence objects"]
        ReverseComplement["Reverse complement handling"]
        OrientationHandling["Strand orientation support"]
    end
    
    TwoBitFile --> TwoBitParser
    RemoteGenome --> TwoBitParser
    TwoBitParser --> ChromosomeSelection
    ChromosomeSelection --> SequenceExtraction
    
    SequenceExtraction --> GetTranscriptDNA
    CDSRegions --> GetTranscriptDNA
    GetTranscriptDNA --> DNAConstruction
    
    DNAConstruction --> DNASequence
    DNAConstruction --> ReverseComplement
    DNAConstruction --> OrientationHandling
```

Sources: [biojava-genome/src/main/java/org/biojava/nbio/genome/parsers/twobit/TwoBitFacade.java:81-85](), [biojava-genome/src/main/java/org/biojava/nbio/genome/util/ChromosomeMappingTools.java:939-971]()

For comprehensive documentation of genomic coordinate mapping algorithms and CDS analysis workflows, see [Genomic Analysis and Chromosome Mapping](#4.1).

## Nucleic Acid Structure Analysis

The nucleic acid structure analysis module implements the el Hassan-Calladine method for calculating base pair and base-pair step parameters in nucleic acid structures. The analysis supports both DNA and RNA structures with multiple specialized implementations for different analysis scenarios.

### Base Pair Parameter Analysis

The `BasePairParameters` class serves as the foundation for nucleic acid structural analysis:

```mermaid
graph TB
    subgraph "Input Structure Data"
        Structure["Structure objects"]
        NucleicChains["Nucleic acid chains"]
        BaseAtoms["Base ring atoms"]
    end
    
    subgraph "BasePairParameters Analysis"
        FindPairs["findPairs()"]
        ReferenceFrame["basePairReferenceFrame()"]
        CalculateParams["calculateTp()"]
        StandardBases["STANDARD_BASES definitions"]
    end
    
    subgraph "Parameter Categories"
        PairingParams["Pairing Parameters:<br/>buckle, propeller, opening<br/>shear, stretch, stagger"]
        StepParams["Step Parameters:<br/>tilt, roll, twist<br/>shift, slide, rise"]
    end
    
    subgraph "Specialized Implementations"
        TertiaryBPP["TertiaryBasePairParameters<br/>(intra-strand pairs)"]
        MismatchedBPP["MismatchedBasePairParameters<br/>(non-canonical pairs)"]
    end
    
    Structure --> FindPairs
    NucleicChains --> FindPairs
    BaseAtoms --> ReferenceFrame
    StandardBases --> ReferenceFrame
    
    FindPairs --> ReferenceFrame
    ReferenceFrame --> CalculateParams
    CalculateParams --> PairingParams
    CalculateParams --> StepParams
    
    BasePairParameters --> TertiaryBPP
    BasePairParameters --> MismatchedBPP
```

The analysis workflow processes nucleic acid structures through several key stages:

| Analysis Stage | Method | Function |
|----------------|--------|----------|
| Chain identification | `getNucleicChains()` | Identifies nucleic acid chains in structure |
| Base pair detection | `findPairs()` | Locates Watson-Crick and other base pairs |
| Reference frame calculation | `basePairReferenceFrame()` | Establishes coordinate system for each pair |
| Parameter calculation | `calculateTp()` | Computes geometric parameters |

Sources: [biojava-structure/src/main/java/org/biojava/nbio/structure/basepairs/BasePairParameters.java:215-240](), [biojava-structure/src/main/java/org/biojava/nbio/structure/basepairs/BasePairParameters.java:461-525](), [biojava-structure/src/main/java/org/biojava/nbio/structure/basepairs/BasePairParameters.java:533-627]()

### Parameter Calculation Methods

The base pair parameter calculation uses transformation matrices to determine structural relationships:

```mermaid
flowchart TD
    subgraph "Input Processing"
        GroupPairs["Pair<Group> base pairs"]
        StandardBases["Standard base definitions"]
        AtomCoordinates["Atom coordinates"]
    end
    
    subgraph "Transformation Analysis"
        Superposition["SuperPositionQCP alignment"]
        MatrixCalculation["4x4 transformation matrices"]
        ParameterExtraction["calculateTp() method"]
    end
    
    subgraph "Geometric Parameters"
        AngularParams["Angular parameters (degrees):<br/>• buckle • propeller • opening<br/>• tilt • roll • twist"]
        TranslationalParams["Translational parameters (Å):<br/>• shear • stretch • stagger<br/>• shift • slide • rise"]
    end
    
    subgraph "Validation and Filtering"
        DistanceCheck["C1'-C1' distance validation"]
        ParameterThresholds["Parameter threshold checks"]
        QualityFiltering["Base pair quality assessment"]
    end
    
    GroupPairs --> Superposition
    StandardBases --> Superposition
    AtomCoordinates --> Superposition
    
    Superposition --> MatrixCalculation
    MatrixCalculation --> ParameterExtraction
    
    ParameterExtraction --> AngularParams
    ParameterExtraction --> TranslationalParams
    
    AngularParams --> DistanceCheck
    TranslationalParams --> DistanceCheck
    DistanceCheck --> ParameterThresholds
    ParameterThresholds --> QualityFiltering
```

Sources: [biojava-structure/src/main/java/org/biojava/nbio/structure/basepairs/BasePairParameters.java:655-697](), [biojava-structure/src/main/java/org/biojava/nbio/structure/basepairs/TertiaryBasePairParameters.java:80-109](), [biojava-structure/src/main/java/org/biojava/nbio/structure/basepairs/MismatchedBasePairParameters.java:98-131]()

### Specialized Analysis Implementations

The module provides specialized implementations for different analysis scenarios:

**TertiaryBasePairParameters**: Designed for RNA tertiary structure analysis, this implementation relaxes the standard constraints to detect intra-strand base pairs and non-canonical interactions. It uses configurable thresholds for stagger (`maxStagger`) and propeller twist (`maxPropeller`) parameters.

**MismatchedBasePairParameters**: Focuses on inter-strand base pairs that may not follow canonical Watson-Crick pairing rules. This implementation adds additional filtering parameters including maximum shear (`maxShear`) and stretch (`maxStretch`) values to identify structurally valid but non-canonical base pairs.

Sources: [biojava-structure/src/main/java/org/biojava/nbio/structure/basepairs/TertiaryBasePairParameters.java:47-51](), [biojava-structure/src/main/java/org/biojava/nbio/structure/basepairs/MismatchedBasePairParameters.java:52-55]()

For detailed information about base pair parameter calculations and nucleic acid structural analysis algorithms, see [Nucleic Acid Structure Analysis](#4.2).

---