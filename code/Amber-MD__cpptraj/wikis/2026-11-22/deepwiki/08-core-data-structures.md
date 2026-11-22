# Core Data Structures

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/Action_AtomicFluct.cpp](src/Action_AtomicFluct.cpp)
- [src/Action_AtomicFluct.h](src/Action_AtomicFluct.h)
- [src/Action_Average.cpp](src/Action_Average.cpp)
- [src/Action_Average.h](src/Action_Average.h)
- [src/Action_Outtraj.cpp](src/Action_Outtraj.cpp)
- [src/Action_Outtraj.h](src/Action_Outtraj.h)
- [src/Atom.cpp](src/Atom.cpp)
- [src/Atom.h](src/Atom.h)
- [src/AtomMask.cpp](src/AtomMask.cpp)
- [src/AtomMask.h](src/AtomMask.h)
- [src/DataFile.cpp](src/DataFile.cpp)
- [src/DataFile.h](src/DataFile.h)
- [src/DataFileList.cpp](src/DataFileList.cpp)
- [src/DataFileList.h](src/DataFileList.h)
- [src/DataSet.cpp](src/DataSet.cpp)
- [src/DataSet.h](src/DataSet.h)
- [src/DataSetList.cpp](src/DataSetList.cpp)
- [src/DataSetList.h](src/DataSetList.h)
- [src/Frame.cpp](src/Frame.cpp)
- [src/Frame.h](src/Frame.h)
- [src/ParameterTypes.h](src/ParameterTypes.h)
- [src/Parm_Amber.cpp](src/Parm_Amber.cpp)
- [src/Parm_Amber.h](src/Parm_Amber.h)
- [src/Topology.cpp](src/Topology.cpp)
- [src/Topology.h](src/Topology.h)

</details>



This document describes the fundamental data structures that CPPTRAJ uses to represent molecular systems and analysis data. These structures form the foundation for all trajectory processing, analysis, and data management operations within the software. For information about the overall system architecture, see [Overview](#1).

## Molecular Representation

CPPTRAJ uses several core classes to represent molecular systems, with `Topology` as the central container that holds information about atoms, residues, molecules, and their connectivity.

```mermaid
classDiagram
    class Topology {
        +std::vector<Atom> atoms_
        +std::vector<Residue> residues_
        +std::vector<Molecule> molecules_
        +Box parmBox_
        +BondArray bonds_
        +BondArray bondsh_
        +AngleArray angles_
        +DihedralArray dihedrals_
        +NonbondParmType nonbond_
        +int Natom()
        +int Nres()
        +int Nmol()
        +DetermineMolecules()
        +SetupIntegerMask(AtomMask&)
    }
    
    class Atom {
        +NameType name_
        +double mass_
        +double charge_
        +AtomicElementType element_
        +int resNum_
        +int atomNum_
        +std::vector<int> bondArray_
        +DetermineElement()
        +AddBondToIdx(int)
    }
    
    class Residue {
        +NameType name_
        +int firstAtom_
        +int lastAtom_
        +int originalResNum_
        +char icode_
        +std::string chainID_
        +bool terminal_
        +NameName()
        +NameIsSolvent()
    }
    
    class Molecule {
        +Unit molUnit_
        +bool isSolvent_
        +NumAtoms()
        +MolUnit()
        +SetSolvent()
    }
    
    Topology *-- "many" Atom : contains
    Topology *-- "many" Residue : contains
    Topology *-- "many" Molecule : contains
    Topology *-- "many" BondType : contains
    Topology *-- "many" AngleType : contains
    Topology *-- "many" DihedralType : contains
    Atom -- Residue : belongs to
    Residue -- Molecule : part of
```

The `Topology` class is the central container that holds all information about the molecular system structure. It manages collections of atoms, residues, molecules, and their connectivity through bonds, angles, and dihedrals.

Sources: [src/Topology.h:16-255](), [src/Topology.cpp:15-183]()

### Atom

The `Atom` class represents individual atoms and stores properties such as name, mass, charge, and element type. It also maintains bonding information through a list of indices to atoms it is bonded to.

```mermaid
classDiagram
    class Atom {
        +NameType name_
        +double mass_
        +double charge_
        +AtomicElementType element_
        +int resNum_
        +int molNum_
        +std::vector<int> bondArray_
        +Name()
        +SetName()
        +Mass()
        +SetMass()
        +Charge()
        +SetCharge()
        +Element()
        +DetermineElement()
        +AddBondToIdx(int)
        +RemoveBondToIdx(int)
    }
    
    class AtomicElementType {
        <<enumeration>>
        UNKNOWN_ELEMENT
        HYDROGEN
        CARBON
        NITROGEN
        OXYGEN
        etc...
    }
    
    Atom -- AtomicElementType : has
```

Sources: [src/Atom.h:6-89](), [src/Atom.cpp:6-22]()

### Residue and Molecule

Residues are groups of atoms that form functional units (like amino acids or nucleotides), while molecules are collections of atoms connected by bonds.

```mermaid
classDiagram
    class Residue {
        +NameType name_
        +int firstAtom_
        +int lastAtom_
        +int originalResNum_
        +char icode_
        +std::string chainID_
        +bool terminal_
        +FirstAtom()
        +LastAtom()
        +SetFirstAtom()
        +SetLastAtom()
        +NameIsSolvent()
    }
    
    class Molecule {
        +Unit molUnit_
        +bool isSolvent_
        +NumAtoms()
        +MolUnit()
        +SetSolvent()
        +IsSolvent()
    }
    
    class Unit {
        +SegIdxArray segidx_
        +nSegments()
        +Front()
        +Back()
    }
    
    Molecule *-- Unit : contains
    Unit -- Residue : references
```

Molecules track their constituent atoms through the `Unit` class, which maintains segments of contiguous atom indices.

Sources: [src/Topology.h:90-105](), [src/Topology.cpp:90-176]()

### Connectivity: Bonds, Angles, and Dihedrals

Molecular connectivity is represented by classes for bonds, angles, and dihedrals, along with their associated parameters.

```mermaid
classDiagram
    class BondType {
        +int a1_
        +int a2_
        +int idx_
        +A1()
        +A2()
        +SetIdx()
    }
    
    class AngleType {
        +int a1_
        +int a2_
        +int a3_
        +int idx_
        +A1()
        +A2()
        +A3()
    }
    
    class DihedralType {
        +int a1_
        +int a2_
        +int a3_
        +int a4_
        +int idx_
        +A1()
        +A2()
        +A3()
        +A4()
    }
    
    class BondParmType {
        +double rk_
        +double req_
        +Rk()
        +Req()
    }
    
    class AngleParmType {
        +double tk_
        +double teq_
        +Tk()
        +Teq()
    }
    
    class DihedralParmType {
        +double pk_
        +double pn_
        +double phase_
        +double scee_
        +double scnb_
        +Pk()
        +Pn()
        +Phase()
    }
    
    BondType -- BondParmType : references
    AngleType -- AngleParmType : references
    DihedralType -- DihedralParmType : references
```

Sources: [src/ParameterTypes.h:22-45](), [src/Topology.h:111-147]()

## Coordinate Management

### Frame

The `Frame` class is a fundamental data structure that stores the coordinates, velocities, and forces for all atoms in a molecular system at a single point in time.

```mermaid
classDiagram
    class Frame {
        +double* X_
        +double* V_
        +double* F_
        +std::vector<double> Mass_
        +Box box_
        +double T_
        +double pH_
        +double time_
        +int natom_
        +int ncoord_
        +int step_
        +SetupFrame(int)
        +AddXYZ(double*)
        +SetCoordinates(Frame, AtomMask)
        +RMSD(Frame, bool)
        +MaskCenter(AtomMask)
        +Translate(Vec3)
        +Rotate(Matrix33)
    }
    
    class Box {
        +double boxX_
        +double boxY_
        +double boxZ_
        +double alpha_
        +double beta_
        +double gamma_
        +CellShape type_
        +HasBox()
        +SetBox(double, double, double)
        +SetTruncOct()
        +SetNoBox()
    }
    
    class CoordinateInfo {
        +Box box_
        +bool hasVel_
        +bool hasForce_
        +bool hasTemp_
        +bool hasTime_
        +HasVel()
        +HasForce()
        +TrajBox()
    }
    
    Frame *-- Box : contains
    Frame -- CoordinateInfo : describes
```

The `Frame` class is designed to efficiently store and manipulate atomic coordinates (X_), velocities (V_), and forces (F_). It supports various operations like RMSD calculations, translations, and rotations.

Sources: [src/Frame.h:9-193](), [src/Frame.cpp:9-117]()

### AtomMask

`AtomMask` provides a way to select specific atoms from a topology using mask expressions.

```mermaid
classDiagram
    class AtomMask {
        +std::vector<int> Selected_
        +int Natom_
        +char maskChar_
        +std::string maskString_
        +Nselected()
        +AddSelectedAtom(int)
        +AddAtomRange(int, int)
        +SetupMask(Topology)
        +MaskString()
        +SetMaskString(string)
        +ResetMask()
        +InvertMask()
    }
    
    class MaskToken {
        +std::string Token
        +std::vector<std::string> tokens_
        +Type tokenType_
        +ParseMask(std::string)
        +MaskTokens()
    }
    
    AtomMask --|> MaskToken : inherits
```

`AtomMask` is used throughout CPPTRAJ to select subsets of atoms for various operations. It can be created from mask expressions like `:1-10@CA,C,N` (selecting backbone atoms from residues 1-10).

Sources: [src/AtomMask.h:6-104](), [src/AtomMask.cpp:6-54]()

## Data Management

CPPTRAJ uses a sophisticated data management system centered around the `DataSet` hierarchy to store and process analysis results.

### DataSet Hierarchy

`DataSet` is the base class for all types of data that can be collected during analysis. Specific types inherit from this base class.

```mermaid
classDiagram
    class DataSet {
        <<abstract>>
        +MetaData meta_
        +TextFormat format_
        +std::vector<Dimension> dim_
        +DataType dType_
        +DataGroup dGroup_
        +virtual Size()
        +virtual Info()
        +virtual WriteBuffer()
        +virtual Allocate()
        +virtual Add()
        +virtual Append()
    }
    
    class DataSet_1D {
        <<abstract>>
        +Xcrd(int)
        +Dcrd(int)
        +Dval(int)
        +SetDval(int, double)
        +AssignWithLabels(DataSet_1D)
    }
    
    class DataSet_double {
        +std::vector<double> Data_
        +Add(size_t, void*)
        +operator[](int)
        +Append(DataSet*)
    }
    
    class DataSet_Vector {
        +std::vector<Vec3> Data_
        +Add(size_t, void*)
        +Append(DataSet*)
    }
    
    class DataSet_Matrix_3D {
        +MatrixType matrix_
        +MatrixIdx()
        +SetElement()
        +GetElement()
    }
    
    class DataSet_Coords {
        <<abstract>>
        +LoadFrame(int, Frame&)
        +CoordsSetup(Topology)
        +Top()
    }
    
    DataSet <|-- DataSet_1D : inherits
    DataSet <|-- DataSet_Matrix_3D : inherits
    DataSet <|-- DataSet_Coords : inherits
    DataSet_1D <|-- DataSet_double : inherits
    DataSet_1D <|-- DataSet_Vector : inherits
```

The `DataSet` hierarchy supports many data types, from simple 1D arrays to complex structures like coordinate sets and matrices.

Sources: [src/DataSet.h:13-166](), [src/DataSet.cpp:5-37]()

### DataSetList

`DataSetList` manages collections of DataSet objects, providing functions for adding, finding, and accessing datasets.

```mermaid
classDiagram
    class DataSetList {
        +std::vector<DataSet*> DataList_
        +std::vector<DataSet*> RefList_
        +std::vector<DataSet*> TopList_
        +bool hasCopies_
        +int ensembleNum_
        +bool dataSetsPending_
        +AddSet(DataSet::DataType, MetaData)
        +AddSetAsCopy(DataSet*)
        +GetDataSet(std::string)
        +FindSetOfType(std::string, DataType)
        +RemoveSet(DataSet*)
        +Clear()
        +ClearAll()
    }
    
    DataSetList o-- "many" DataSet : manages
```

Sources: [src/DataSetList.h:22-103](), [src/DataSetList.cpp:43-126]()

### DataFile and DataFileList

The `DataFile` class handles writing data to files in various formats, while `DataFileList` manages multiple output files.

```mermaid
classDiagram
    class DataFile {
        +DataSetList SetList_
        +FileName filename_
        +DataIO* dataio_
        +DataFormatType dfType_
        +bool dflWrite_
        +bool sortSets_
        +SetupDatafile(FileName, ArgList)
        +AddDataSet(DataSet*)
        +WriteDataOut()
        +ProcessArgs(ArgList)
    }
    
    class DataFileList {
        +std::vector<DataFile*> fileList_
        +std::vector<CpptrajFile*> cfList_
        +int debug_
        +int ensembleNum_
        +bool ensembleExt_
        +AddDataFile(FileName, ArgList)
        +GetDataFile(FileName)
        +WriteAllDF()
        +ProcessDataFileArgs(ArgList)
    }
    
    class DataIO {
        <<abstract>>
        +virtual ReadData(FileName, DataSetList)
        +virtual WriteData(FileName, DataSetList)
        +virtual processReadArgs(ArgList)
        +virtual processWriteArgs(ArgList)
    }
    
    DataFileList o-- "many" DataFile : manages
    DataFile *-- DataIO : uses
    DataFile o-- "many" DataSet : contains
```

Sources: [src/DataFile.h:8-111](), [src/DataFile.cpp:38-142](), [src/DataFileList.h:9-39](), [src/DataFileList.cpp:10-43]()

## Integration of Core Structures

The following diagram illustrates how these core data structures interact within CPPTRAJ:

```mermaid
flowchart TB
    subgraph "Molecular Representation"
        Topology --> Atom
        Topology --> Residue
        Topology --> Molecule
        Topology --> BondType
        Topology --> AngleType
        Topology --> DihedralType
    end
    
    subgraph "Coordinate Management"
        Frame
        AtomMask
    end
    
    subgraph "Data Management"
        DataSet
        DataSetList --> DataSet
        DataFile --> DataSet
        DataFileList --> DataFile
    end
    
    Topology --> AtomMask
    Frame --> AtomMask
    DataSet --> Frame
    DataSet --> Topology
```

Sources: [src/Topology.cpp:358-403](), [src/Frame.cpp:264-284](), [src/DataSetList.cpp:298-351]()

## Memory Management and Performance Considerations

CPPTRAJ's core data structures are designed with performance in mind, particularly for large molecular systems and trajectory analysis.

### Frame Memory Layout

The `Frame` class uses contiguous arrays for coordinates, velocities, and forces to maximize cache efficiency and enable vectorized operations:

```mermaid
flowchart LR
    subgraph Frame
        X["X_[natom*3]"]
        V["V_[natom*3] (optional)"]
        F["F_[natom*3] (optional)"]
        Mass["Mass_[natom]"]
    end
    
    subgraph "Memory Layout"
        XLayout["x1 y1 z1 x2 y2 z2 ... xN yN zN"]
        VLayout["vx1 vy1 vz1 ... vxN vyN vzN"]
        FLayout["fx1 fy1 fz1 ... fxN fyN fzN"]
    end
    
    X --> XLayout
    V --> VLayout
    F --> FLayout
```

Sources: [src/Frame.h:33-103](), [src/Frame.cpp:371-407]()

### Data Sets and Disk Caching

For memory-intensive analyses, CPPTRAJ provides options for disk caching of large datasets:

```mermaid
flowchart TD
    DataSetList --> |"useDiskCache_=true"| DiskCache["Disk-Cached Sets"]
    DataSetList --> |"useDiskCache_=false"| MemorySets["Memory-Resident Sets"]
    
    DiskCache --> |"Integer"| DataSet_integer_disk
    DiskCache --> |"Matrices"| DataSet_MatrixDbl
    
    MemorySets --> DataSet_integer_mem
    MemorySets --> OtherSets["Other Memory Sets"]
```

Sources: [src/DataSetList.cpp:40-108]()

This summarizes the core data structures in CPPTRAJ and their relationships. These structures form the foundation for all molecular system representation, coordinate manipulation, and data analysis capabilities within the software.

---