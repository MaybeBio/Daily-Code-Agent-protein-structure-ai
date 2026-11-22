# Molecular Data Structures and Display

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/viamd.cpp](src/viamd.cpp)

</details>



This document covers the core molecular data structures used throughout VIAMD and the interactive display system that presents molecular information to users. This includes the fundamental organization of molecular data (atoms, bonds, residues, chains), the picking system for interactive selection, and the information windows that display detailed molecular component data.

For information about loading molecular data from files, see [File Loading System](#2.2). For details about the graphics rendering pipeline that visualizes these structures, see [Graphics and Visualization Pipeline](#3). For analysis components that operate on this molecular data, see [Analysis and Computation](#4).

## Core Molecular Data Structure Organization

VIAMD organizes molecular data in a hierarchical structure centered around the `md_molecule_t` type from the MDLib library. The data is structured in a structure-of-arrays pattern for efficient memory access and vectorization.

### Molecular Data Hierarchy

```mermaid
graph TD
    subgraph "ApplicationState"
        MOLD["mold (Molecular Data Container)"]
    end
    
    subgraph "md_molecule_t Structure"
        MOL["mol (Main Molecule)"]
        ATOM["atom (Atom Arrays)"]
        BOND["bond (Bond Arrays)"]
        RESIDUE["residue (Residue Arrays)"] 
        CHAIN["chain (Chain Arrays)"]
    end
    
    subgraph "Atom Data Arrays"
        ATOM_X["x[] (X Coordinates)"]
        ATOM_Y["y[] (Y Coordinates)"]
        ATOM_Z["z[] (Z Coordinates)"]
        ATOM_TYPE["type[] (Atom Types)"]
        ATOM_ELEMENT["element[] (Element IDs)"]
        ATOM_FLAGS["flags[] (Property Flags)"]
        ATOM_RES_IDX["res_idx[] (Residue Indices)"]
        ATOM_CHAIN_IDX["chain_idx[] (Chain Indices)"]
    end
    
    subgraph "Bond Data Arrays"
        BOND_PAIRS["pairs[] (Atom Index Pairs)"]
        BOND_ORDER["order[] (Bond Orders)"]
    end
    
    subgraph "Residue Data Arrays"
        RES_NAME["name[] (Residue Names)"]
        RES_ID["id[] (Residue IDs)"]
    end
    
    subgraph "Chain Data Arrays"
        CHAIN_ID["id[] (Chain Identifiers)"]
    end
    
    MOLD --> MOL
    MOL --> ATOM
    MOL --> BOND
    MOL --> RESIDUE
    MOL --> CHAIN
    
    ATOM --> ATOM_X
    ATOM --> ATOM_Y
    ATOM --> ATOM_Z
    ATOM --> ATOM_TYPE
    ATOM --> ATOM_ELEMENT
    ATOM --> ATOM_FLAGS
    ATOM --> ATOM_RES_IDX
    ATOM --> ATOM_CHAIN_IDX
    
    BOND --> BOND_PAIRS
    BOND --> BOND_ORDER
    
    RESIDUE --> RES_NAME
    RESIDUE --> RES_ID
    
    CHAIN --> CHAIN_ID
```

**Sources:** [src/viamd.cpp:9-44]()

### Atom Property Flags System

Atoms contain a comprehensive flags system that categorizes molecular properties and hybridization states:

| Flag Category | Flags | Purpose |
|---------------|-------|---------|
| **Molecular Type** | `MD_FLAG_HETATM`, `MD_FLAG_AMINO_ACID`, `MD_FLAG_NUCLEOTIDE`, `MD_FLAG_NUCLEOBASE`, `MD_FLAG_WATER`, `MD_FLAG_ION` | Classify molecular component types |
| **Hybridization** | `MD_FLAG_SP`, `MD_FLAG_SP2`, `MD_FLAG_SP3` | Indicate atomic hybridization states |
| **Chemical Properties** | `MD_FLAG_AROMATIC` | Mark aromatic atoms |

**Sources:** [src/viamd.cpp:55-72]()

## Interactive Picking System

The picking system enables interactive selection of molecular components through a unified indexing scheme that distinguishes between atoms and bonds.

### Picking Index Encoding

```mermaid
graph LR
    subgraph "Picking Index Range"
        INVALID["INVALID_PICKING_IDX<br/>(No Selection)"]
        ATOMS["0 to atom.count-1<br/>(Atom Indices)"]
        BONDS["0x80000000 + bond_idx<br/>(Bond Indices with High Bit Set)"]
    end
    
    subgraph "Index Decoding Logic"
        CHECK_INVALID["picking_idx == INVALID_PICKING_IDX?"]
        CHECK_ATOM["picking_idx < mol.atom.count?"]
        CHECK_BOND["picking_idx >= 0x80000000?"]
        DECODE_BOND["bond_idx = picking_idx & 0x7FFFFFFF"]
    end
    
    INVALID --> CHECK_INVALID
    ATOMS --> CHECK_ATOM
    BONDS --> CHECK_BOND
    CHECK_BOND --> DECODE_BOND
```

**Sources:** [src/viamd.cpp:11](), [src/viamd.cpp:18](), [src/viamd.cpp:81-82]()

### Molecular Component Access Patterns

The system provides hierarchical access to molecular components through index relationships:

```mermaid
graph TD
    subgraph "Atom Access Pattern"
        ATOM_IDX["atom_idx (Selected Atom)"]
        ATOM_POS["Position: mol.atom.x/y/z[atom_idx]"]
        ATOM_TYPE_DATA["Type: mol.atom.type[atom_idx]"]
        ATOM_ELEMENT_DATA["Element: mol.atom.element[atom_idx]"]
        RES_REF["Residue Reference: mol.atom.res_idx[atom_idx]"]
        CHAIN_REF["Chain Reference: mol.atom.chain_idx[atom_idx]"]
    end
    
    subgraph "Residue Resolution"
        RES_IDX["res_idx (from atom)"]
        RES_NAME_DATA["Name: mol.residue.name[res_idx]"]
        RES_ID_DATA["ID: mol.residue.id[res_idx]"]
        LOCAL_IDX["Local Index: atom_idx - range.beg"]
    end
    
    subgraph "Chain Resolution"
        CHAIN_IDX["chain_idx (from atom)"]
        CHAIN_ID_DATA["ID: mol.chain.id[chain_idx]"]
    end
    
    subgraph "Bond Access Pattern"
        BOND_IDX["bond_idx (from picking_idx)"]
        BOND_PAIR["Pair: mol.bond.pairs[bond_idx]"]
        BOND_ORDER_DATA["Order: mol.bond.order[bond_idx]"]
        BOND_ATOMS["Atom Indices: b.idx[0], b.idx[1]"]
    end
    
    ATOM_IDX --> ATOM_POS
    ATOM_IDX --> ATOM_TYPE_DATA
    ATOM_IDX --> ATOM_ELEMENT_DATA
    ATOM_IDX --> RES_REF
    ATOM_IDX --> CHAIN_REF
    
    RES_REF --> RES_IDX
    RES_IDX --> RES_NAME_DATA
    RES_IDX --> RES_ID_DATA
    RES_IDX --> LOCAL_IDX
    
    CHAIN_REF --> CHAIN_IDX
    CHAIN_IDX --> CHAIN_ID_DATA
    
    BOND_IDX --> BOND_PAIR
    BOND_IDX --> BOND_ORDER_DATA
    BOND_PAIR --> BOND_ATOMS
```

**Sources:** [src/viamd.cpp:19-44](), [src/viamd.cpp:82-100]()

## Information Display System

The `draw_info_window` function implements a context-sensitive tooltip system that displays detailed information about picked molecular components.

### Display Window Implementation

The information window follows an immediate-mode GUI pattern with dynamic positioning and content generation:

```mermaid
graph TB
    subgraph "Window Configuration"
        MOUSE_POS["ImGui::GetMousePos()"]
        OFFSET["offset = {10.f, 18.f}"]
        WINDOW_POS["SetNextWindowPos(mouse + offset)"]
        STYLE["PushStyleColor(WindowBg, transparent)"]
    end
    
    subgraph "Content Generation"
        STR_BUILDER["md_strb_t sb (String Builder)"]
        ATOM_INFO["Generate Atom Information"]
        BOND_INFO["Generate Bond Information"]
        FORMAT_OUTPUT["md_strb_fmt() Formatting"]
    end
    
    subgraph "Window Rendering"
        BEGIN_WINDOW["ImGui::Begin() with Tooltip Flags"]
        DISPLAY_TEXT["ImGui::Text() with Generated Content"]
        END_WINDOW["ImGui::End()"]
        RESTORE_STYLE["PopStyleColor()"]
    end
    
    MOUSE_POS --> WINDOW_POS
    OFFSET --> WINDOW_POS
    WINDOW_POS --> STYLE
    
    STR_BUILDER --> ATOM_INFO
    STR_BUILDER --> BOND_INFO
    ATOM_INFO --> FORMAT_OUTPUT
    BOND_INFO --> FORMAT_OUTPUT
    
    STYLE --> BEGIN_WINDOW
    FORMAT_OUTPUT --> DISPLAY_TEXT
    DISPLAY_TEXT --> END_WINDOW
    END_WINDOW --> RESTORE_STYLE
```

**Sources:** [src/viamd.cpp:103-112]()

### Atom Information Display Format

For selected atoms, the system displays comprehensive information including hierarchy and properties:

| Information Type | Format | Example |
|------------------|--------|---------|
| **Basic Identity** | `atom[global_idx][local_idx]: type element symbol (x, y, z)` | `atom[1234][5]: CA C Carbon (12.34, 56.78, 90.12)` |
| **Residue Context** | `res[res_idx]: name id` | `res[123]: ALA 45` |
| **Chain Context** | `chain[chain_idx]: id` | `chain[1]: A` |
| **Property Flags** | `flags: FLAG1 FLAG2 ...` | `flags: AMINO SP3 AROMATIC` |

**Sources:** [src/viamd.cpp:47-72]()

### Bond Information Display Format

For selected bonds, the system shows bond characteristics and geometry:

| Information Type | Format | Description |
|------------------|--------|-------------|
| **Bond Identity** | `bond: atom1_type{bond_char}atom2_type` | Visual representation of bonded atoms |
| **Bond Order** | `order: {1,2,3,4}` | Chemical bond order |
| **Bond Length** | `length: {distance}` | Calculated 3D distance between atoms |

Bond type characters: `-` (single), `=` (double), `#` (triple), `$` (quadruple), `?` (unknown)

**Sources:** [src/viamd.cpp:84-100]()

## Data Organization and Memory Layout

### Structure-of-Arrays Pattern

The molecular data uses a structure-of-arrays layout optimized for:

- **Cache Efficiency**: Related data elements are stored contiguously
- **Vectorization**: SIMD operations can process multiple elements simultaneously  
- **Memory Access Patterns**: Algorithms can efficiently iterate over specific properties

### Index-Based Relationships

The system maintains relationships through index arrays rather than pointers:

- `mol.atom.res_idx[]` maps atoms to residues
- `mol.atom.chain_idx[]` maps atoms to chains  
- `mol.bond.pairs[]` contains atom index pairs for bonds

This approach enables:
- **Stable References**: Indices remain valid across data modifications
- **Serialization**: Data can be easily saved/loaded without pointer fixup
- **Parallel Access**: Multiple threads can safely read index-based data

**Sources:** [src/viamd.cpp:29-33](), [src/viamd.cpp:39-44](), [src/viamd.cpp:84]()

---