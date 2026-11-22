# Core Data Structures

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [docs/code/sym.cpp](docs/code/sym.cpp)
- [docs/mol.rst](docs/mol.rst)
- [docs/symmetry.rst](docs/symmetry.rst)
- [include/gemmi/calculate.hpp](include/gemmi/calculate.hpp)
- [include/gemmi/cellred.hpp](include/gemmi/cellred.hpp)
- [include/gemmi/floodfill.hpp](include/gemmi/floodfill.hpp)
- [include/gemmi/math.hpp](include/gemmi/math.hpp)
- [include/gemmi/mmcif.hpp](include/gemmi/mmcif.hpp)
- [include/gemmi/model.hpp](include/gemmi/model.hpp)
- [include/gemmi/pdb.hpp](include/gemmi/pdb.hpp)
- [include/gemmi/symmetry.hpp](include/gemmi/symmetry.hpp)
- [include/gemmi/to_mmcif.hpp](include/gemmi/to_mmcif.hpp)
- [include/gemmi/to_pdb.hpp](include/gemmi/to_pdb.hpp)
- [include/gemmi/twin.hpp](include/gemmi/twin.hpp)
- [include/gemmi/unitcell.hpp](include/gemmi/unitcell.hpp)
- [prog/sg.cpp](prog/sg.cpp)
- [python/mol.cpp](python/mol.cpp)
- [python/sym.cpp](python/sym.cpp)
- [python/unitcell.cpp](python/unitcell.cpp)
- [src/calculate.cpp](src/calculate.cpp)
- [src/symmetry.cpp](src/symmetry.cpp)
- [tests/main.cpp](tests/main.cpp)
- [tests/test_mol.py](tests/test_mol.py)
- [tests/test_symmetry.py](tests/test_symmetry.py)
- [tests/test_twin.py](tests/test_twin.py)
- [tests/test_unitcell.py](tests/test_unitcell.py)

</details>



This document provides an overview of the fundamental data structures in the Gemmi library, which forms the backbone of its crystallographic computing capabilities. These core data structures include macromolecular model representations, grid systems for volumetric data, crystallographic symmetry operations, and unit cell definitions.

## Structure Hierarchy

Gemmi uses a hierarchical organization for macromolecular structures that follows the standard PDB hierarchy.

```mermaid
classDiagram
    class Structure["gemmi::Structure"] {
        +std::string name
        +UnitCell cell
        +std::string spacegroup_hm
        +std::vector~Model~ models
        +std::vector~Entity~ entities
        +std::vector~Connection~ connections
        +first_model()
        +setup_entities()
    }
    
    class Model["gemmi::Model"] {
        +int num
        +std::vector~Chain~ chains
        +find_chain(name)
    }
    
    class Chain["gemmi::Chain"] {
        +std::string name
        +std::vector~Residue~ residues
        +get_polymer()
    }
    
    class Residue["gemmi::Residue"] {
        +std::string name
        +SeqId seqid
        +std::string subchain
        +std::string entity_id
        +EntityType entity_type
        +std::vector~Atom~ atoms
    }
    
    class Atom["gemmi::Atom"] {
        +std::string name
        +char altloc
        +Element element
        +Position pos
        +float occ
        +float b_iso
        +SMat33~float~ aniso
    }
    
    Structure "1" *-- "1..*" Model : contains
    Model "1" *-- "0..*" Chain : contains
    Chain "1" *-- "0..*" Residue : contains
    Residue "1" *-- "0..*" Atom : contains
```

The hierarchy starts with `Structure`, which contains multiple `Model` instances. Each `Model` contains `Chain` objects, each `Chain` contains `Residue` objects, and each `Residue` contains `Atom` objects. For details, see [Structure and Model System](#3.1).

### Structure
The top-level container representing a macromolecular structure [include/gemmi/model.hpp:882-1056](). It holds global information such as the unit cell, space group, and entity information.

### Model
Represents a single conformation of the structure [include/gemmi/model.hpp:718-868](). Multi-model files are common in NMR or ensembles.

### Chain
Represents a polymer chain, ligand, or water molecules [include/gemmi/model.hpp:482-610]().

### Residue
An amino acid, nucleotide, or ligand [include/gemmi/model.hpp:183-288](). It contains metadata like `entity_id` and `label_seq`.

### Atom
The basic unit containing coordinates (`pos`), occupancy (`occ`), and thermal parameters (`b_iso`, `aniso`) [include/gemmi/model.hpp:119-164]().

**Sources:** [include/gemmi/model.hpp:119-1056](), [docs/mol.rst:1-100]()

## Grid System

Gemmi's grid system handles 3D volumetric data such as electron density maps and masks.

```mermaid
classDiagram
    class GridMeta["gemmi::GridMeta"] {
        +UnitCell unit_cell
        +const SpaceGroup* spacegroup
        +int nu, nv, nw
        +point_count()
    }
    
    class GridBase["gemmi::GridBase&lt;T&gt;"] {
        +std::vector~T~ data
    }
    
    class Grid["gemmi::Grid&lt;T&gt;"] {
        +interpolate_value()
        +get_value(u, v, w)
    }
    
    GridMeta <|-- GridBase : inherits
    GridBase <|-- Grid : inherits
```

The system is built on `GridMeta` (metadata), `GridBase` (data storage), and `Grid` (interpolation and logic). For details, see [Grid and Map System](#3.2).

**Sources:** [include/gemmi/grid.hpp:168-550]()

## Symmetry System

The symmetry system represents crystallographic symmetry operations and space groups.

```mermaid
classDiagram
    class Op["gemmi::Op"] {
        +Rot rot
        +Tran tran
        +inverse()
        +apply_to_xyz(xyz)
    }
    
    class GroupOps["gemmi::GroupOps"] {
        +std::vector~Op~ sym_ops
        +std::vector~Op::Tran~ cen_ops
        +is_centrosymmetric()
    }
    
    class SpaceGroup["gemmi::SpaceGroup"] {
        +int number
        +std::string hm
        +operations()
    }
    
    SpaceGroup --> GroupOps : provides
    GroupOps "1" o-- "1..*" Op : contains
```

### Op
Represents a symmetry operation using an integer rotation matrix and translation vector with a fixed denominator `DEN=24` [include/gemmi/symmetry.hpp:30-216]().

### GroupOps
A collection of `Op` objects representing a symmetry group [include/gemmi/symmetry.hpp:254-478]().

### SpaceGroup
High-level representation of a space group including symbols and lookup tables [include/gemmi/symmetry.hpp:1089-1184](). For details, see [Symmetry Operations](#3.3).

**Sources:** [include/gemmi/symmetry.hpp:30-1184](), [python/sym.cpp:15-150]()

## Unit Cell and Coordinates

Gemmi provides primitives for handling unit cell parameters and coordinate transformations.

```mermaid
classDiagram
    class Vec3["gemmi::Vec3"] {
        +double x, y, z
    }
    
    class Position["gemmi::Position"] {
        +Cartesian coordinates
    }
    
    class Fractional["gemmi::Fractional"] {
        +Fractional coordinates
        +wrap_to_unit()
    }
    
    class UnitCell["gemmi::UnitCell"] {
        +double a, b, c
        +Transform orth
        +Transform frac
        +orthogonalize(f)
        +fractionalize(p)
    }
    
    Vec3 <|-- Position : inherits
    Vec3 <|-- Fractional : inherits
    UnitCell o-- Position : uses
```

### UnitCell
Stores cell parameters and pre-calculated `Transform` matrices for converting between `Position` (orthogonal) and `Fractional` coordinates [include/gemmi/unitcell.hpp:165-374](). For details, see [Unit Cell and Coordinate Transformations](#3.4).

**Sources:** [include/gemmi/unitcell.hpp:32-374](), [include/gemmi/math.hpp:142-489]()

## Reflection Data

Reflection data is handled primarily through the `Mtz` class for binary files and `AsuData` for organized reciprocal space data. For details, see [Reflection Data](#3.5).

**Sources:** [include/gemmi/model.hpp:27-28](), [python/unitcell.cpp:103-180]()

---