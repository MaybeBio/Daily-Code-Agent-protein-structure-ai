

Welcome to BioJava! This guide will help you get up and running with BioJava in just a few minutes. BioJava is a powerful open-source Java framework for processing biological data, providing tools for sequence analysis, structure manipulation, and much more.

## What is BioJava?

BioJava is a comprehensive Java library designed specifically for bioinformatics applications. It provides analytical and statistical routines, parsers for common file formats, reference implementations of popular algorithms, and allows the manipulation of sequences and 3D structures. Whether you're working with DNA, RNA, proteins, or complex biological structures, BioJava offers the tools you need.

Sources: [README.md#L7](README.md#L7), [pom.xml#L17-L21](pom.xml#L17-L21)

## Setting Up BioJava

### Prerequisites

Before you begin, ensure you have:
- Java Development Kit (JDK) 11 or higher
- Apache Maven (recommended for dependency management)

### Adding BioJava to Your Project

The easiest way to include BioJava in your project is through Maven. Add the following dependency to your `pom.xml` file:

```xml
<dependencies>
  <dependency>
    <groupId>org.biojava</groupId>
    <artifactId>biojava-core</artifactId>
    <version>7.2.2</version>
  </dependency>
  <!-- Add other modules as needed -->
</dependencies>
```

This will include the core module of BioJava, which provides fundamental functionality for sequence handling and basic bioinformatics operations.

Sources: [README.md#L27-L36](README.md#L27-L36)

## Your First BioJava Program

Let's start with a simple example: parsing a FASTA file containing protein sequences. This is a common task in bioinformatics, and BioJava makes it straightforward.

### Example: Parsing a FASTA File

```java
import org.biojava.nbio.core.sequence.ProteinSequence;
import org.biojava.nbio.core.sequence.compound.AminoAcidCompound;
import org.biojava.nbio.core.sequence.io.FastaReader;
import org.biojava.nbio.core.sequence.io.GenericFastaHeaderParser;
import org.biojava.nbio.core.sequence.io.ProteinSequenceCreator;
import org.biojava.nbio.core.sequence.compound.AminoAcidCompoundSet;

import java.io.File;
import java.io.InputStream;
import java.util.Map;
import org.biojava.nbio.core.util.InputStreamProvider;

public class FastaParser {
    public static void main(String[] args) throws Exception {
        // Provide path to your FASTA file
        File fastaFile = new File("path/to/your/protein.fasta");
        
        // Automatically handle compressed files
        InputStreamProvider isp = new InputStreamProvider();
        InputStream inStream = isp.getInputStream(fastaFile);
        
        // Create a FASTA reader
        FastaReader<ProteinSequence, AminoAcidCompound> fastaReader = new FastaReader<>(
            inStream,
            new GenericFastaHeaderParser<ProteinSequence, AminoAcidCompound>(),
            new ProteinSequenceCreator(AminoAcidCompoundSet.getAminoAcidCompoundSet())
        );
        
        // Read all sequences
        Map<String, ProteinSequence> sequences = fastaReader.process();
        
        // Print sequence information
        for (String header : sequences.keySet()) {
            ProteinSequence sequence = sequences.get(header);
            System.out.println("Header: " + header);
            System.out.println("Sequence: " + sequence.getSequenceAsString());
            System.out.println("Length: " + sequence.getLength());
            System.out.println("---");
        }
    }
}
```

This program demonstrates how to:
1. Read a FASTA file (even if it's compressed)
2. Parse protein sequences
3. Access sequence information including headers and sequence data

Sources: [ParseFastaFileDemo.java](biojava-core/src/main/java/demo/ParseFastaFileDemo.java)

### Example: DNA Translation

Another common bioinformatics task is translating DNA sequences to protein sequences. Here's how to do it with BioJava:

```java
import org.biojava.nbio.core.sequence.DNASequence;
import org.biojava.nbio.core.sequence.ProteinSequence;
import org.biojava.nbio.core.sequence.compound.AmbiguityDNACompoundSet;
import org.biojava.nbio.core.sequence.compound.NucleotideCompound;
import org.biojava.nbio.core.sequence.io.DNASequenceCreator;
import org.biojava.nbio.core.sequence.io.FastaReader;
import org.biojava.nbio.core.sequence.io.GenericFastaHeaderParser;
import org.biojava.nbio.core.sequence.transcription.TranscriptionEngine;
import org.biojava.nbio.core.sequence.transcription.Frame;

import java.io.ByteArrayInputStream;
import java.io.InputStream;
import java.util.Map;

public class DNATranslator {
    public static void main(String[] args) throws Exception {
        // Example DNA sequence in FASTA format
        String dnaFasta = ">example_dna\n" +
                         "ATGGCCATTGTAATGGGCCGCTGAAAGGGTGCCCGATAG";
        
        // Parse the DNA sequence
        InputStream stream = new ByteArrayInputStream(dnaFasta.getBytes());
        
        FastaReader<DNASequence, NucleotideCompound> fastaReader = new FastaReader<>(
            stream,
            new GenericFastaHeaderParser<DNASequence, NucleotideCompound>(),
            new DNASequenceCreator(AmbiguityDNACompoundSet.getDNACompoundSet())
        );
        
        Map<String, DNASequence> dnaSequences = fastaReader.process();
        
        // Initialize the transcription engine
        TranscriptionEngine engine = new TranscriptionEngine.Builder()
            .dnaCompounds(AmbiguityDNACompoundSet.getDNACompoundSet())
            .build();
        
        // Translate DNA to protein
        for (DNASequence dna : dnaSequences.values()) {
            ProteinSequence protein = dna.getRNASequence().getProteinSequence(engine);
            System.out.println("DNA: " + dna.getSequenceAsString());
            System.out.println("Protein: " + protein.getSequenceAsString());
        }
    }
}
```

This example shows how to:
1. Parse a DNA sequence
2. Use BioJava's transcription engine
3. Translate DNA to protein sequence

Sources: [DemoSixFrameTranslation.java](biojava-core/src/main/java/demo/DemoSixFrameTranslation.java)

## BioJava Module Overview

BioJava is organized into several modules, each providing specific functionality:

| Module | Description |
|--------|-------------|
| biojava-core | Core functionality including sequence handling and basic operations |
| biojava-alignment | Sequence alignment algorithms and tools |
| biojava-structure | Protein structure analysis and manipulation |
| biojava-genome | Genome analysis tools |
| biojava-ontology | Ontology support |
| biojava-ws | Web services integration |
| biojava-protein-disorder | Protein disorder prediction |
| biojava-aa-prop | Amino acid properties calculation |
| biojava-survival | Survival analysis tools |
| biojava-modfinder | Post-translational modification finder |
| biojava-protein-comparison-tool | Protein structure comparison |
| biojava-structure-gui | GUI components for structure visualization |

You can include additional modules by adding their dependencies to your `pom.xml` file. For example, to include the structure module:

```xml
<dependency>
    <groupId>org.biojava</groupId>
    <artifactId>biojava-structure</artifactId>
    <version>7.2.2</version>
</dependency>
```

Sources: [pom.xml#L721-L737](pom.xml#L721-L737)

## Next Steps

Congratulations! You've successfully set up BioJava and run your first bioinformatics programs. Here are some suggestions for what to explore next:

1. **Explore the Core API**: Dive deeper into the sequence manipulation capabilities in the `biojava-core` module.
2. **Try Sequence Alignment**: Use the `biojava-alignment` module to perform sequence alignments.
3. **Work with Protein Structures**: If you're interested in structural biology, explore the `biojava-structure` module.
4. **Check the Documentation**: Visit the [BioJava tutorial](https://github.com/biojava/biojava-tutorial) for more detailed examples and guides.
5. **Join the Community**: Participate in the [BioJava mailing list](http://lists.open-bio.org/mailman/listinfo/biojava-l) for support and discussions.

> [!TIP]
> Remember that BioJava has extensive Javadoc documentation available at the [BioJava website](http://biojava.org/docs/api). When working with a new class or method, always check the documentation for detailed information and additional examples.
