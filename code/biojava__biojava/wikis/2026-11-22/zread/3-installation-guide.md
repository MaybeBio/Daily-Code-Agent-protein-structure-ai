

Welcome to the BioJava installation guide! This document will walk you through the process of setting up BioJava in your development environment, whether you're a beginner looking to use BioJava for your bioinformatics projects or a developer planning to contribute to the codebase.

## Prerequisites

Before installing BioJava, ensure you have the following prerequisites in place:

**Java Development Kit (JDK)**: BioJava requires **Java 11 or higher** to run properly. The project is configured to use Java 11 as the minimum version, which provides modern language features and performance improvements for bioinformatics applications.

**Apache Maven**: BioJava is built using Maven, a popular project management and comprehension tool. You'll need Maven 3.0 or higher installed on your system to build BioJava from source or manage dependencies.

**Memory Requirements**: BioJava can be memory-intensive, especially when working with large biological datasets or 3D protein structures. Ensure your system has at least **2GB of RAM** available, though **4GB or more** is recommended for optimal performance.

Sources: [pom.xml#L36](pom.xml#L36), [pom.xml#L41](pom.xml#L41)

## Installation Methods

BioJava offers two primary installation methods depending on your needs:

1. **Using Maven Central** (Recommended for users who want to use BioJava in their projects)
2. **Building from Source** (Required for developers contributing to BioJava)

Let's explore each method in detail.

### Method 1: Installing from Maven Central

For most users, the simplest way to get started with BioJava is by adding it as a dependency to your Maven project. BioJava releases are published to Maven Central, making integration straightforward.

#### Step 1: Configure Your pom.xml

Add the BioJava dependencies to your project's `pom.xml` file. Here's a basic configuration:

```xml
<dependencies>
    <!-- Core BioJava module - required for most functionality -->
    <dependency>
        <groupId>org.biojava</groupId>
        <artifactId>biojava-core</artifactId>
        <version>7.2.2</version>
    </dependency>
    
    <!-- Add additional modules as needed -->
    <dependency>
        <groupId>org.biojava</groupId>
        <artifactId>biojava-structure</artifactId>
        <version>7.2.2</version>
    </dependency>
</dependencies>
```

#### Step 2: Choose Your Modules

BioJava is organized into modular components, each focusing on specific bioinformatics tasks. You only need to include the modules relevant to your work:

| Module | Purpose | Common Use Cases |
|--------|---------|------------------|
| biojava-core | Core functionality and shared utilities | Basic sequence operations, data models |
| biojava-alignment | Sequence alignment algorithms | DNA/protein sequence alignment, BLAST integration |
| biojava-structure | Protein structure analysis | PDB file parsing, 3D structure manipulation |
| biojava-genome | Genome analysis and manipulation | Genome assembly, annotation processing |
| biojava-aa-prop | Amino acid properties calculations | Protein property prediction, analysis |
| biojava-protein-disorder | Protein disorder prediction | Identifying disordered regions in proteins |
| biojava-ontology | Ontology support | GO terms, controlled vocabularies |
| biojava-ws | Web services integration | External API calls, data retrieval |

> [!TIP]
> Start with biojava-core and add additional modules only as needed. This keeps your project lightweight and avoids unnecessary dependencies.

#### Step 3: Verify Installation

Create a simple test to verify BioJava is properly installed:

```java
import org.biojava.nbio.core.sequence.DNASequence;
import org.biojava.nbio.core.sequence.ProteinSequence;
import org.biojava.nbio.core.sequence.compound.AminoAcidCompound;
import org.biojava.nbio.core.sequence.compound.NucleotideCompound;

public class BioJavaTest {
    public static void main(String[] args) {
        try {
            // Test DNA sequence functionality
            DNASequence dnaSequence = new DNASequence("ATGC");
            System.out.println("DNA Sequence: " + dnaSequence.getSequenceAsString());
            
            // Test protein sequence functionality
            ProteinSequence proteinSequence = new ProteinSequence("ACDE");
            System.out.println("Protein Sequence: " + proteinSequence.getSequenceAsString());
            
            System.out.println("BioJava installation successful!");
        } catch (Exception e) {
            System.err.println("Error testing BioJava: " + e.getMessage());
        }
    }
}
```

If this code compiles and runs successfully, BioJava is properly installed in your project.

Sources: [README.md#L23-L36](README.md#L23-L36), [pom.xml#L721-L737](pom.xml#L721-L737)

### Method 2: Building from Source

If you're planning to contribute to BioJava or need the latest development version, you'll need to build it from source.

#### Step 1: Clone the Repository

First, clone the BioJava repository from GitHub:

```bash
git clone https://github.com/biojava/biojava.git
cd biojava
```

#### Step 2: Build the Project

Use Maven to build the entire project:

```bash
# Clean previous builds and compile all modules
mvn clean compile

# Run tests to ensure everything works correctly
mvn test

# Install to your local Maven repository
mvn install
```

The build process may take several minutes as it compiles all modules and runs extensive test suites.

#### Step 3: Build Specific Modules

If you only need to work with specific modules, you can build them individually:

```bash
# Build only the core module
cd biojava-core
mvn clean install

# Build only the structure module
cd ../biojava-structure
mvn clean install
```

> [!TIP]
> When building from source, ensure you have a stable internet connection as Maven needs to download various dependencies during the first build.

#### Step 4: Working with IDEs

BioJava can be imported into popular Java IDEs for development:

**IntelliJ IDEA**:
1. File → Open → Select the biojava root directory
2. Choose "Import from Maven model" when prompted
3. Wait for Maven to download dependencies and index the project

**Eclipse**:
1. File → Import → Maven → Existing Maven Projects
2. Browse to the biojava root directory
3. Select all modules and click Finish

**NetBeans**:
1. File → Open Project
2. Navigate to the biojava root directory
3. Select the pom.xml file and click Open Project

The project includes formatter configurations in the `development/eclipse` directory that can be imported into your IDE to maintain consistent code style.

Sources: [CONTRIBUTING.md#L12](CONTRIBUTING.md#L12), [development/eclipse](development/eclipse)

## Troubleshooting Common Issues

### Java Version Compatibility

If you encounter Java version errors, ensure you're using Java 11 or higher:

```bash
# Check your Java version
java -version
javac -version

# If needed, set JAVA_HOME environment variable
export JAVA_HOME=/path/to/java11
```

### Memory Issues During Build

If you run into memory issues during the build process, increase Maven's memory allocation:

```bash
# For Unix/Linux/Mac
export MAVEN_OPTS="-Xmx2g -XX:MaxPermSize=512m"

# For Windows
set MAVEN_OPTS=-Xmx2g -XX:MaxPermSize=512m

# Then run your Maven commands
mvn clean install
```

### Network/Proxy Issues

If you're behind a corporate proxy, configure Maven's settings.xml file:

```xml
<settings>
  <proxies>
    <proxy>
      <id>my-proxy</id>
      <active>true</active>
      <protocol>http</protocol>
      <host>proxy.company.com</host>
      <port>8080</port>
      <username>proxyuser</username>
      <password>proxypass</password>
    </proxy>
  </proxies>
</settings>
```

### Missing Dependencies

If Maven reports missing dependencies, try cleaning your local repository:

```bash
# Clean Maven's local repository
mvn dependency:purge-local-repository

# Then rebuild
mvn clean install
```

Sources: [pom.xml#L357-L361](pom.xml#L357-L361)

## Next Steps

Congratulations! You now have BioJava installed and ready to use. Here are some recommended next steps:

1. **Explore the Tutorial**: Check out the [BioJava tutorial](https://github.com/biojava/biojava-tutorial) for comprehensive examples and walkthroughs.

2. **Review the Cookbook**: Browse the [BioJava Cookbook](http://biojava.org/wiki/BioJava:CookBook4.0/) for quick solutions to common problems.

3. **Examine the API Documentation**: Full JavaDocs are available at the [BioJava website](http://biojava.org/docs/api).

4. **Join the Community**: Subscribe to the [biojava-l mailing list](http://lists.open-bio.org/mailman/listinfo/biojava-l) to connect with other users and developers.

5. **Start Small**: Begin with simple sequence operations in the core module before moving to more complex functionality like protein structure analysis.

Remember that BioJava is a powerful framework with extensive capabilities. Take your time to explore different modules and find the ones that best suit your bioinformatics needs. The modular design allows you to start simple and gradually incorporate more advanced features as your projects grow.
