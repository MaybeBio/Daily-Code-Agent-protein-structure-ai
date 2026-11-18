# Data Model and Structure Representation

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [biojava-integrationtest/src/test/java/org/biojava/nbio/structure/test/Test1a4w.java](biojava-integrationtest/src/test/java/org/biojava/nbio/structure/test/Test1a4w.java)
- [biojava-integrationtest/src/test/java/org/biojava/nbio/structure/test/io/TestBondParsing.java](biojava-integrationtest/src/test/java/org/biojava/nbio/structure/test/io/TestBondParsing.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/AminoAcid.java](biojava-structure/src/main/java/org/biojava/nbio/structure/AminoAcid.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/AminoAcidImpl.java](biojava-structure/src/main/java/org/biojava/nbio/structure/AminoAcidImpl.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/Atom.java](biojava-structure/src/main/java/org/biojava/nbio/structure/Atom.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/AtomImpl.java](biojava-structure/src/main/java/org/biojava/nbio/structure/AtomImpl.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/Bond.java](biojava-structure/src/main/java/org/biojava/nbio/structure/Bond.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/BondImpl.java](biojava-structure/src/main/java/org/biojava/nbio/structure/BondImpl.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/Calc.java](biojava-structure/src/main/java/org/biojava/nbio/structure/Calc.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/Chain.java](biojava-structure/src/main/java/org/biojava/nbio/structure/Chain.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/ChainImpl.java](biojava-structure/src/main/java/org/biojava/nbio/structure/ChainImpl.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/Group.java](biojava-structure/src/main/java/org/biojava/nbio/structure/Group.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/HetatomImpl.java](biojava-structure/src/main/java/org/biojava/nbio/structure/HetatomImpl.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/NucleotideImpl.java](biojava-structure/src/main/java/org/biojava/nbio/structure/NucleotideImpl.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/StructureIO.java](biojava-structure/src/main/java/org/biojava/nbio/structure/StructureIO.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/align/ce/OptimalCECPMain.java](biojava-structure/src/main/java/org/biojava/nbio/structure/align/ce/OptimalCECPMain.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/align/util/UserConfiguration.java](biojava-structure/src/main/java/org/biojava/nbio/structure/align/util/UserConfiguration.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/io/BondMaker.java](biojava-structure/src/main/java/org/biojava/nbio/structure/io/BondMaker.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/io/StructureSequenceMatcher.java](biojava-structure/src/main/java/org/biojava/nbio/structure/io/StructureSequenceMatcher.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/quaternary/BioAssemblyTools.java](biojava-structure/src/main/java/org/biojava/nbio/structure/quaternary/BioAssemblyTools.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/quaternary/BiologicalAssemblyBuilder.java](biojava-structure/src/main/java/org/biojava/nbio/structure/quaternary/BiologicalAssemblyBuilder.java)
- [biojava-structure/src/main/java/org/biojava/nbio/structure/xtal/SymoplibParser.java](biojava-structure/src/main/java/org/biojava/nbio/structure/xtal/SymoplibParser.java)
- [biojava-structure/src/test/java/org/biojava/nbio/structure/Test4hhb.java](biojava-structure/src/test/java/org/biojava/nbio/structure/Test4hhb.java)
- [biojava-structure/src/test/java/org/biojava/nbio/structure/TestAltLocs.java](biojava-structure/src/test/java/org/biojava/nbio/structure/TestAltLocs.java)
- [biojava-structure/src/test/java/org/biojava/nbio/structure/TestBond.java](biojava-structure/src/test/java/org/biojava/nbio/structure/TestBond.java)
- [biojava-structure/src/test/java/org/biojava/nbio/structure/TestCalc.java](biojava-structure/src/test/java/org/biojava/nbio/structure/TestCalc.java)
- [biojava-structure/src/test/java/org/biojava/nbio/structure/TestCloning.java](biojava-structure/src/test/java/org/biojava/nbio/structure/TestCloning.java)
- [biojava-structure/src/test/java/org/biojava/nbio/structure/TestStructureCrossReferences.java](biojava-structure/src/test/java/org/biojava/nbio/structure/TestStructureCrossReferences.java)
- [biojava-structure/src/test/java/org/biojava/nbio/structure/io/TestParseOnAsymId.java](biojava-structure/src/test/java/org/biojava/nbio/structure/io/TestParseOnAsymId.java)

</details>



This document describes BioJava's core data model for representing biological macromolecular structures, particularly protein and nucleic acid structures. It covers the hierarchical organization from `Structure` down to `Atom` level, different group types, chemical bonds, and coordinate handling. For file format parsing and I/O operations, see [File Format Support and Parsing](#2.2). For structure caching and retrieval mechanisms, see [Structure Caching and Retrieval](#2.3).

## Core Hierarchical Structure

BioJava uses a four-level hierarchical model to represent biological structures:

```mermaid
graph TD
    Structure["Structure"]
    Chain1["Chain"]
    Chain2["Chain"]
    Group1["Group"]
    Group2["Group"]
    Group3["Group"]
    Atom1["Atom"]
    Atom2["Atom"]
    Atom3["Atom"]
    Atom4["Atom"]
    
    Structure --> Chain1
    Structure --> Chain2
    Chain1 --> Group1
    Chain1 --> Group2
    Chain2 --> Group3
    Group1 --> Atom1
    Group1 --> Atom2
    Group2 --> Atom3
    Group3 --> Atom4
    
    Structure -.-> "nrModels()"
    Chain1 -.-> "asymId, authId"
    Group1 -.-> "residueNumber"
    Atom1 -.-> "coordinates, element"
```

### Structure Level

The `Structure` interface represents the top-level container for a macromolecular structure. It manages multiple models (for NMR structures) and provides access to chains through various methods.

**Key Methods:**
- `getChains()` - retrieves all chains in the structure
- `getPolyChainByPDB(String)` - gets polymer chains by PDB chain ID
- `getNonPolyChainsByPDB(String)` - gets non-polymer chains
- `nrModels()` - returns number of models

### Chain Level

The `Chain` interface represents a single chain within a structure, implemented by `ChainImpl`. Each chain has both internal (`asymId`) and external (`authId`) identifiers to handle mmCIF vs PDB naming conventions.

**Key Properties:**
- `getId()` - internal asymmetric unit ID (mmCIF)
- `getName()` - author-assigned chain ID (PDB)
- `getAtomGroups()` - groups with observed coordinates
- `getSeqResGroups()` - groups from sequence records

Sources: [biojava-structure/src/main/java/org/biojava/nbio/structure/Chain.java:74-99](), [biojava-structure/src/main/java/org/biojava/nbio/structure/ChainImpl.java:89-102]()

### Group Level

The `Group` interface represents a residue or molecular group, with three main implementations corresponding to different group types:

```mermaid
graph TD
    Group["Group (interface)"]
    AminoAcidImpl["AminoAcidImpl"]
    NucleotideImpl["NucleotideImpl"] 
    HetatomImpl["HetatomImpl"]
    
    Group --> AminoAcidImpl
    Group --> NucleotideImpl
    Group --> HetatomImpl
    
    AminoAcidImpl -.-> "getN(), getCA(), getC(), getO()"
    NucleotideImpl -.-> "getP(), getO3Prime(), getO5Prime()"
    HetatomImpl -.-> "general atom access"
    
    Group -.-> "getPDBName(), getResidueNumber()"
    Group -.-> "getAtoms(), hasAtom()"
```

**Common Group Methods:**
- `getPDBName()` - three-letter residue name (e.g., "ALA", "ATP")
- `getResidueNumber()` - residue numbering information
- `getAtoms()` - list of atoms in the group
- `getAltLocs()` - alternative location groups

Sources: [biojava-structure/src/main/java/org/biojava/nbio/structure/Group.java:154-162](), [biojava-structure/src/main/java/org/biojava/nbio/structure/HetatomImpl.java:146-162]()

### Atom Level

The `Atom` interface represents individual atoms, implemented by `AtomImpl`. Atoms store coordinates, chemical properties, and connectivity information.

**Key Properties:**
- `getName()` - atom name (e.g., "CA", "N", "O")
- `getElement()` - chemical element
- `getCoords()` - 3D coordinates as double array
- `getCoordsAsPoint3d()` - coordinates as Point3d object
- `getBonds()` - list of chemical bonds

Sources: [biojava-structure/src/main/java/org/biojava/nbio/structure/Atom.java:51-113](), [biojava-structure/src/main/java/org/biojava/nbio/structure/AtomImpl.java:65-158]()

## Group Types and Specializations

BioJava distinguishes between three types of molecular groups based on their chemical nature:

### Amino Acid Groups

`AminoAcidImpl` extends `HetatomImpl` and provides specific methods for protein backbone atoms:

```mermaid
graph LR
    AminoAcid["AminoAcidImpl"]
    N["N atom"]
    CA["CA atom"] 
    C["C atom"]
    O["O atom"]
    CB["CB atom"]
    
    AminoAcid --> N
    AminoAcid --> CA
    AminoAcid --> C
    AminoAcid --> O
    AminoAcid -.-> CB
    
    AminoAcid -.-> "getN(), getCA(), getC(), getO()"
    AminoAcid -.-> "getCB() - side chain carbon"
```

**Key Methods:**
- `getN()`, `getCA()`, `getC()`, `getO()` - backbone atoms
- `getCB()` - beta carbon (null for glycine)

Sources: [biojava-structure/src/main/java/org/biojava/nbio/structure/AminoAcidImpl.java:66-81]()

### Nucleotide Groups

`NucleotideImpl` provides access to nucleic acid-specific atoms:

**Key Methods:**
- `getP()` - phosphate atom
- `getO3Prime()`, `getO5Prime()` - ribose oxygens for backbone connectivity

Sources: [biojava-structure/src/main/java/org/biojava/nbio/structure/NucleotideImpl.java:67-91]()

### Hetatom Groups

`HetatomImpl` handles all non-standard groups including ligands, cofactors, water molecules, and modified residues. It provides the base functionality inherited by amino acid and nucleotide implementations.

**Performance Options:**
The class supports two performance behaviors controlled by `PerformanceBehavior` enum:
- `BETTER_PERFORMANCE_MORE_MEMORY` - uses HashMap for atom lookup
- `LESS_MEMORY_SLOWER_PERFORMANCE` - linear search through atom list

Sources: [biojava-structure/src/main/java/org/biojava/nbio/structure/HetatomImpl.java:84-122]()

## Chemical Bonds and Connectivity

### Bond Representation

The `Bond` interface and `BondImpl` class represent chemical bonds between atoms:

```mermaid
graph TD
    Bond["Bond"]
    AtomA["Atom A"]
    AtomB["Atom B"]
    
    Bond --> AtomA
    Bond --> AtomB
    
    Bond -.-> "bondOrder (1,2,3)"
    Bond -.-> "getOther(atom)"
    
    AtomA --> BondList["List<Bond>"]
    AtomB --> BondList2["List<Bond>"]
```

**Key Properties:**
- `getAtomA()`, `getAtomB()` - bonded atoms
- `getBondOrder()` - single (1), double (2), triple (3) bonds
- `getOther(Atom)` - returns the other atom in the bond

Sources: [biojava-structure/src/main/java/org/biojava/nbio/structure/Bond.java:44-68](), [biojava-structure/src/main/java/org/biojava/nbio/structure/BondImpl.java:36-45]()

### Bond Creation

The `BondMaker` class automatically creates bonds during structure parsing:

**Bond Types Created:**
1. **Peptide bonds** - between consecutive amino acids (C to N, max distance 1.8 Å)
2. **Nucleotide bonds** - between consecutive nucleotides (P to O3', max distance 2.1 Å)  
3. **Intra-residue bonds** - within groups based on Chemical Component Dictionary
4. **Disulfide bonds** - from SSBOND records or struct_conn
5. **LINK record bonds** - explicit inter-residue bonds

**Alternative Location Handling:**
- No bonds between differently named alt locs (except default '.')
- Multiple bonds created for default alt loc to named alt loc

Sources: [biojava-structure/src/main/java/org/biojava/nbio/structure/io/BondMaker.java:104-111](), [biojava-structure/src/main/java/org/biojava/nbio/structure/io/BondMaker.java:206-242]()

## Alternative Locations

BioJava handles alternative conformations (alt locs) where atoms can exist in multiple positions:

```mermaid
graph TD
    MainGroup["Main Group"]
    AltLoc1["Alt Loc Group A"]
    AltLoc2["Alt Loc Group B"]
    
    MainGroup --> AtomDefault["Atom (default)"]
    AltLoc1 --> AtomA["Atom (alt A)"]
    AltLoc2 --> AtomB["Atom (alt B)"]
    
    MainGroup -.-> "getAltLocs()"
    MainGroup -.-> "getAltLocGroup(char)"
    
    AtomDefault -.-> "altLoc = ' '"
    AtomA -.-> "altLoc = 'A'"
    AtomB -.-> "altLoc = 'B'"
```

**Key Methods:**
- `hasAltLoc()` - checks if group has alternative locations
- `getAltLocs()` - returns list of alternative location groups
- `getAltLocGroup(Character)` - gets specific alt loc group

**Alt Loc Rules:**
- Default alt loc is typically space (' ') or period ('.')
- Named alt locs use letters (A, B, C, etc.)
- Bonds are not created between different named alt locs
- All atoms within an alt loc group should have the same alt loc character

Sources: [biojava-structure/src/main/java/org/biojava/nbio/structure/Group.java:339-350](), [biojava-structure/src/test/java/org/biojava/nbio/structure/TestAltLocs.java:181-210]()

## Coordinate Representation and Calculations

### Coordinate Storage

Atoms store coordinates using `javax.vecmath.Point3d` internally:

- `getCoords()` - returns coordinates as `double[]` array
- `getCoordsAsPoint3d()` - returns reference to internal `Point3d`
- `getX()`, `getY()`, `getZ()` - individual coordinate access
- `setX(double)`, `setY(double)`, `setZ(double)` - coordinate modification

### Geometric Calculations

The `Calc` utility class provides extensive geometric operations:

**Distance Calculations:**
- `getDistance(Atom, Atom)` - Euclidean distance between atoms
- `getDistanceFast(Atom, Atom)` - squared distance (faster for comparisons)

**Transformations:**
- `transform(Atom, Matrix4d)` - apply 4x4 transformation matrix
- `rotate(Atom, Matrix)` - apply rotation matrix
- `shift(Atom, Atom)` - translate by vector

**Geometric Properties:**
- `getCentroid(Atom[])` - geometric center of atom set
- `centerOfMass(Atom[])` - mass-weighted center
- `torsionAngle(Atom, Atom, Atom, Atom)` - dihedral angle calculation

Sources: [biojava-structure/src/main/java/org/biojava/nbio/structure/Calc.java:68-76](), [biojava-structure/src/main/java/org/biojava/nbio/structure/Calc.java:509-530]()

## Entity and Metadata Management

### Entity Information

The `EntityInfo` class manages metadata about distinct molecular entities within a structure:

- Entity ID and description
- Chain assignments to entities
- Molecular type classification
- Sequence information

### Residue Numbering

The `ResidueNumber` class handles the complex numbering schemes in PDB files:

- `getSeqNum()` - sequence number
- `getInsCode()` - insertion code
- `getChainName()` - associated chain identifier

**PDB Numbering Challenges:**
- Insertion codes (e.g., 27A, 27B after residue 27)
- Negative residue numbers
- Chain-specific numbering schemes

Sources: [biojava-structure/src/main/java/org/biojava/nbio/structure/ChainImpl.java:171-179](), [biojava-structure/src/main/java/org/biojava/nbio/structure/Group.java:284-297]()

## Summary

BioJava's structure representation provides a comprehensive, hierarchical model that accurately captures the complexity of biological macromolecules while maintaining computational efficiency. The design accommodates the irregularities found in real structural data, including alternative conformations, complex numbering schemes, and diverse molecular types. The integration of bond information and geometric calculations makes it suitable for both structural analysis and visualization applications.

---