# File Formats and Data Structures

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [benchmark/proteins/ala2_tip3p.gro](benchmark/proteins/ala2_tip3p.gro)
- [benchmark/proteins/ala2_tip3p.top](benchmark/proteins/ala2_tip3p.top)
- [benchmark/proteins/trp-cage_sol.top](benchmark/proteins/trp-cage_sol.top)

</details>



This page provides an overview of the molecular structure file formats supported by DIMOS and the internal data structures used to represent molecular systems during simulations. It covers the input formats for topology, coordinates, and parameters, as well as how these are converted into PyTorch tensors for efficient GPU-accelerated computation.

For detailed specifications of specific file formats, see:
- [GROMACS File Formats](#7.1) for .gro and .top format details
- [Amber File Formats](#7.2) for .prmtop and .inpcrd format details

For information on using these formats in practice, see:
- [Classical Force Fields](#4.1) for loading topology files
- [Quick Start Tutorial](#1.2) for basic file usage examples

## Overview of Supported Formats

DIMOS supports two primary ecosystem file formats for molecular simulations: GROMACS and Amber. Each ecosystem provides a pair of files—one for topology/parameters and one for coordinates/velocities.

```mermaid
graph LR
    subgraph "GROMACS Ecosystem"
        GRO[".gro file<br/>Coordinates & Box"]
        TOP[".top file<br/>Topology & Parameters"]
    end
    
    subgraph "Amber Ecosystem"
        INPCRD[".inpcrd file<br/>Coordinates"]
        PRMTOP[".prmtop file<br/>Topology & Parameters"]
    end
    
    subgraph "DIMOS Internal"
        GRO_FF["GromacsForceField"]
        AMBER_FF["AmberForceField"]
        TENSORS["PyTorch Tensors<br/>positions, velocities,<br/>forces, box"]
        PARAMS["Parameter Storage<br/>bonds, angles,<br/>nonbonded, etc."]
    end
    
    subgraph "External Tools"
        PARMED["ParmEd Library"]
    end
    
    GRO --> GRO_FF
    TOP --> GRO_FF
    INPCRD --> AMBER_FF
    PRMTOP --> AMBER_FF
    PRMTOP --> PARMED
    PARMED --> AMBER_FF
    
    GRO_FF --> TENSORS
    GRO_FF --> PARAMS
    AMBER_FF --> TENSORS
    AMBER_FF --> PARAMS
```

**Sources:** Based on Diagram 2 (Force Field Architecture) and general system architecture

### File Format Categories

| Format | Type | Contains | Read By |
|--------|------|----------|---------|
| `.gro` | Coordinates | Atomic positions, box dimensions, optionally velocities | `GromacsForceField` |
| `.top` | Topology | Atom types, bonds, angles, dihedrals, force field parameters | `GromacsForceField` |
| `.inpcrd` | Coordinates | Atomic positions, optionally velocities and box | `AmberForceField` |
| `.prmtop` | Topology | Atom types, bonds, angles, dihedrals, force field parameters | `AmberForceField` via `ParmEd` |

**Sources:** benchmark/proteins/ala2_tip3p.gro, benchmark/proteins/ala2_tip3p.top, Diagram 2

## Internal Data Representation

DIMOS converts all input data into PyTorch tensors for GPU acceleration and automatic differentiation. The core data structures represent both the instantaneous state of the system and the static force field parameters.

```mermaid
graph TB
    subgraph "System State Tensors"
        POS["positions<br/>shape: (N, 3)<br/>dtype: float32/64"]
        VEL["velocities<br/>shape: (N, 3)<br/>dtype: float32/64"]
        FORCES["forces<br/>shape: (N, 3)<br/>dtype: float32/64"]
        BOX["box<br/>shape: (3, 3)<br/>dtype: float32/64"]
        MASSES["masses<br/>shape: (N,)<br/>dtype: float32/64"]
    end
    
    subgraph "Force Field Parameter Tensors"
        BOND_PARAMS["bond_params<br/>k, r0 values"]
        ANGLE_PARAMS["angle_params<br/>k, theta0 values"]
        DIHEDRAL_PARAMS["dihedral_params<br/>k, periodicity, phase"]
        LJ_PARAMS["LJ_params<br/>sigma, epsilon values"]
        CHARGES["charges<br/>shape: (N,)"]
    end
    
    subgraph "Connectivity Indices"
        BOND_IDX["bond_indices<br/>shape: (n_bonds, 2)"]
        ANGLE_IDX["angle_indices<br/>shape: (n_angles, 3)"]
        DIHEDRAL_IDX["dihedral_indices<br/>shape: (n_dihedrals, 4)"]
        EXCL["exclusions<br/>nonbonded interaction list"]
    end
    
    POS --> FORCES
    VEL --> POS
    MASSES --> VEL
    
    BOND_IDX --> BOND_PARAMS
    ANGLE_IDX --> ANGLE_PARAMS
    DIHEDRAL_IDX --> DIHEDRAL_PARAMS
    
    BOND_PARAMS --> FORCES
    ANGLE_PARAMS --> FORCES
    DIHEDRAL_PARAMS --> FORCES
    LJ_PARAMS --> FORCES
    CHARGES --> FORCES
```

**Sources:** energy.py (energy calculations), constants.py (unit systems), Diagram 5

### Key Tensor Properties

All tensors maintain the following properties:
- **Device**: Can reside on CPU or CUDA GPU (`device='cuda'` or `device='cpu'`)
- **Precision**: Support for both single precision (`torch.float32`) and double precision (`torch.float64`)
- **Differentiability**: Tensors can have `requires_grad=True` for automatic differentiation
- **Unit System**: Values stored in internal units determined by unit system selection (see [Unit Systems and Physical Constants](#2.3))

**Sources:** constants.py, Diagram 6 (Unit System Management)

## File Reading and Parsing Pipeline

The process of loading molecular systems from files involves several stages of parsing and conversion.

```mermaid
graph TD
    INPUT["Input Files<br/>.gro/.top or<br/>.prmtop/.inpcrd"]
    
    subgraph "Format Detection"
        DETECT["Detect file format<br/>by extension"]
    end
    
    subgraph "Primary Parsing"
        GRO_PARSER["parse .gro<br/>read coordinates,<br/>box, velocities"]
        TOP_PARSER["parse .top<br/>read topology,<br/>atom types,<br/>parameters"]
        AMBER_PARSER["ParmEd.load_file()<br/>read .prmtop"]
        COORD_PARSER["parse .inpcrd<br/>read coordinates"]
    end
    
    subgraph "Validation"
        VALIDATE["Validate consistency<br/>atom counts,<br/>parameter completeness"]
    end
    
    subgraph "Unit Conversion"
        CONVERT["Convert to internal units<br/>nm -> internal length<br/>kJ/mol -> internal energy"]
    end
    
    subgraph "Tensor Creation"
        TENSORIZE["Create PyTorch tensors<br/>set device & dtype<br/>requires_grad if needed"]
    end
    
    subgraph "Force Field Object"
        FF_OBJ["AmberForceField or<br/>GromacsForceField<br/>ready for simulation"]
    end
    
    INPUT --> DETECT
    DETECT -->|GROMACS| GRO_PARSER
    DETECT -->|GROMACS| TOP_PARSER
    DETECT -->|Amber| AMBER_PARSER
    DETECT -->|Amber| COORD_PARSER
    
    GRO_PARSER --> VALIDATE
    TOP_PARSER --> VALIDATE
    AMBER_PARSER --> VALIDATE
    COORD_PARSER --> VALIDATE
    
    VALIDATE --> CONVERT
    CONVERT --> TENSORIZE
    TENSORIZE --> FF_OBJ
```

**Sources:** Diagram 2 (Force Field Architecture), Diagram 5 (Simulation Engine)

### Parsing Implementation Details

The file parsing relies on:
- **Native Python parsers** for GROMACS `.gro` files (simple fixed-width format)
- **Custom parsers** for GROMACS `.top` files (directive-based format)
- **ParmEd library** for Amber `.prmtop` files (complex binary/ASCII format)
- **Simple parsers** for Amber `.inpcrd` files (formatted ASCII)

**Sources:** benchmark/proteins/ala2_tip3p.gro:1-100, benchmark/proteins/ala2_tip3p.top:1-50

## Force Field Parameter Data Structures

Force field parameters are organized by interaction type, with indices pointing into the parameter arrays.

### Bonded Interaction Storage

```mermaid
graph LR
    subgraph "Bond Parameters"
        BOND_K["bond_k<br/>force constants"]
        BOND_R0["bond_r0<br/>equilibrium lengths"]
        BOND_ATOMS["bond_atom_indices<br/>(i, j) pairs"]
    end
    
    subgraph "Angle Parameters"
        ANGLE_K["angle_k<br/>force constants"]
        ANGLE_T0["angle_theta0<br/>equilibrium angles"]
        ANGLE_ATOMS["angle_atom_indices<br/>(i, j, k) triplets"]
    end
    
    subgraph "Dihedral Parameters"
        DIH_K["dihedral_k<br/>barrier heights"]
        DIH_N["dihedral_periodicity<br/>n values"]
        DIH_PHASE["dihedral_phase<br/>phase offsets"]
        DIH_ATOMS["dihedral_atom_indices<br/>(i, j, k, l) quartets"]
    end
    
    BOND_ATOMS -->|index into| BOND_K
    BOND_ATOMS -->|index into| BOND_R0
    ANGLE_ATOMS -->|index into| ANGLE_K
    ANGLE_ATOMS -->|index into| ANGLE_T0
    DIH_ATOMS -->|index into| DIH_K
    DIH_ATOMS -->|index into| DIH_N
    DIH_ATOMS -->|index into| DIH_PHASE
```

**Sources:** benchmark/proteins/ala2_tip3p.top:66-88 (bonds), benchmark/proteins/ala2_tip3p.top:134-172 (angles), benchmark/proteins/ala2_tip3p.top:173-227 (dihedrals)

### Example: Bond Data from ala2_tip3p.top

From [benchmark/proteins/ala2_tip3p.top:66-88](), the bonds section shows:
```
[ bonds ]
;    ai     aj funct         c0         c1
      2      3     1   0.10900 284512.000000
      2      4     1   0.10900 284512.000000
```

This translates to internal storage:
- `bond_atom_indices[0] = [2, 3]` (atoms involved)
- `bond_r0[0] = 0.10900` nm (equilibrium length)
- `bond_k[0] = 284512.0` kJ/(mol·nm²) (force constant)

**Sources:** benchmark/proteins/ala2_tip3p.top:66-88

### Nonbonded Interaction Storage

```mermaid
graph TB
    subgraph "Atom Types and Parameters"
        ATOMTYPES["atomtypes table<br/>name, mass, sigma, epsilon"]
        ATOM_ASSIGNMENT["atom -> type mapping"]
    end
    
    subgraph "Per-Atom Properties"
        CHARGES_ARR["charges array<br/>shape: (N,)"]
        SIGMA_ARR["sigma array<br/>shape: (N,)"]
        EPSILON_ARR["epsilon array<br/>shape: (N,)"]
    end
    
    subgraph "Nonbonded Exclusions"
        EXCL_LIST["exclusion_list<br/>pairs to skip"]
        PAIR_14["1-4 pairs<br/>scaled interactions"]
    end
    
    ATOMTYPES --> ATOM_ASSIGNMENT
    ATOM_ASSIGNMENT --> CHARGES_ARR
    ATOM_ASSIGNMENT --> SIGMA_ARR
    ATOM_ASSIGNMENT --> EPSILON_ARR
    
    EXCL_LIST --> PAIR_14
```

**Sources:** benchmark/proteins/ala2_tip3p.top:21-31 (atomtypes), benchmark/proteins/ala2_tip3p.top:38-64 (atoms)

### Example: Atom Types from ala2_tip3p.top

From [benchmark/proteins/ala2_tip3p.top:21-31](), the atomtypes section defines:
```
[ atomtypes ]
; name    at.num    mass    charge ptype  sigma      epsilon
H1             1   1.007947  0.00000000  A     0.26495328      0.0656888
C1             6  12.010780  0.00000000  A     0.33996695      0.4577296
```

Each atom in the system (lines 38-64) references these types to get its LJ parameters.

**Sources:** benchmark/proteins/ala2_tip3p.top:21-31, benchmark/proteins/ala2_tip3p.top:38-64

## Coordinate and Box Data Structures

### Coordinate File Structure (.gro format)

The `.gro` format stores coordinates in a fixed-width ASCII format:

```mermaid
graph TD
    subgraph ".gro File Structure"
        TITLE["Line 1: Title/comment"]
        NATOMS["Line 2: Number of atoms"]
        COORDS["Lines 3 to N+2:<br/>residue, atom name,<br/>atom number,<br/>x, y, z coordinates,<br/>optionally vx, vy, vz"]
        BOX_LINE["Line N+3:<br/>Box vectors<br/>v1(x) v2(y) v3(z)<br/>or 9 components"]
    end
    
    TITLE --> NATOMS
    NATOMS --> COORDS
    COORDS --> BOX_LINE
```

**Sources:** benchmark/proteins/ala2_tip3p.gro:1-10

### Example: .gro File Header

From [benchmark/proteins/ala2_tip3p.gro:1-10]():
```
GROningen MAchine for Chemical Simulation
 2269
    1ACE     H1    1   1.591   1.197   1.609
    1ACE    CH3    2   1.538   1.290   1.589
```

Line 1: Title
Line 2: 2269 atoms total (22 protein atoms + 749 water molecules × 3 atoms/water)
Lines 3+: Each atom with residue info and coordinates in nm

**Sources:** benchmark/proteins/ala2_tip3p.gro:1-10

### Periodic Box Representation

DIMOS represents periodic boundary conditions using a 3×3 box matrix:

```mermaid
graph LR
    subgraph "Box Matrix"
        BOX_MAT["box tensor<br/>shape: (3, 3)<br/><br/>[[v1x, v1y, v1z],<br/> [v2x, v2y, v2z],<br/> [v3x, v3y, v3z]]"]
    end
    
    subgraph "Common Cases"
        CUBIC["Cubic box:<br/>diagonal matrix<br/>[[L, 0, 0],<br/> [0, L, 0],<br/> [0, 0, L]]"]
        ORTHO["Orthorhombic:<br/>[[Lx, 0, 0],<br/> [0, Ly, 0],<br/> [0, 0, Lz]]"]
        TRICO["Triclinic:<br/>general 3x3<br/>upper triangular"]
    end
    
    BOX_MAT --> CUBIC
    BOX_MAT --> ORTHO
    BOX_MAT --> TRICO
```

**Sources:** Diagram 5 (Simulation Loop shows box dimensions), barostats.py (box scaling)

## Molecule and Residue Organization

Molecular systems are organized hierarchically into residues and molecules.

```mermaid
graph TD
    subgraph "System Level"
        SYSTEM["System<br/>All atoms in simulation"]
    end
    
    subgraph "Molecule Level"
        MOL1["Molecule 1<br/>e.g., protein"]
        MOL2["Molecule 2<br/>e.g., water 1"]
        MOL3["Molecule 3<br/>e.g., water 2"]
        MOLN["Molecule N<br/>e.g., water 749"]
    end
    
    subgraph "Residue Level"
        RES1["Residue 1<br/>ACE"]
        RES2["Residue 2<br/>ALA"]
        RES3["Residue 3<br/>NME"]
    end
    
    subgraph "Atom Level"
        ATOM1["Atom 1: H1"]
        ATOM2["Atom 2: CH3"]
        ATOM3["Atom 3: H2"]
    end
    
    SYSTEM --> MOL1
    SYSTEM --> MOL2
    SYSTEM --> MOL3
    SYSTEM --> MOLN
    
    MOL1 --> RES1
    MOL1 --> RES2
    MOL1 --> RES3
    
    RES1 --> ATOM1
    RES1 --> ATOM2
    RES1 --> ATOM3
```

**Sources:** benchmark/proteins/ala2_tip3p.top:34-64 (molecule definitions), benchmark/proteins/ala2_tip3p.top:229-268 (water molecules)

### Molecule Definitions in Topology Files

From [benchmark/proteins/ala2_tip3p.top:34-36]():
```
[ moleculetype ]
; Name            nrexcl
system1          3
```

The `moleculetype` directive defines a molecule template. The `nrexcl` parameter (3) means bonded neighbors up to 3 bonds apart are excluded from nonbonded interactions.

From [benchmark/proteins/ala2_tip3p.top:274-277]():
```
[ molecules ]
; Compound       #mols
system1              1
HOH                749
```

The `molecules` section specifies how many instances of each molecule type are present in the system.

**Sources:** benchmark/proteins/ala2_tip3p.top:34-36, benchmark/proteins/ala2_tip3p.top:274-277

## Memory Layout and Performance Considerations

DIMOS stores data in contiguous memory layouts for efficient GPU operations:

| Data Structure | Memory Layout | Cache Efficiency |
|----------------|---------------|------------------|
| Positions | (N, 3) contiguous | Sequential access by atom |
| Forces | (N, 3) contiguous | Sequential writes |
| Bond indices | (n_bonds, 2) | Gather operations |
| Angle indices | (n_angles, 3) | Gather operations |
| Dihedral indices | (n_dihedrals, 4) | Gather operations |
| Neighbor lists | Ragged arrays or padded | Depends on implementation |

**Optimization Notes:**
- PyTorch tensors use row-major (C-style) ordering
- Coalesced memory access on GPU requires aligned data
- Parameters stored once and indexed during force calculations
- Neighbor lists rebuilt periodically to maintain performance

**Sources:** Based on energy.py patterns, neighbor list usage in Diagram 1

## Data Validation and Consistency Checks

When loading files, DIMOS performs several validation checks:

1. **Atom Count Consistency**: Number of atoms in coordinate file matches topology
2. **Parameter Completeness**: All referenced atom types have defined parameters
3. **Index Validity**: Bond/angle/dihedral indices reference valid atoms
4. **Unit Consistency**: All parameters in expected units for the file format
5. **Exclusion List Validity**: Exclusion pairs reference valid atom indices
6. **Box Constraints**: Box dimensions compatible with simulation settings

**Sources:** Based on standard MD practice and error handling patterns in parsers

## Conversion Between Formats

DIMOS can internally convert between representations:

```mermaid
graph LR
    AMBER_IN["Amber Files<br/>.prmtop + .inpcrd"]
    GRO_IN["GROMACS Files<br/>.top + .gro"]
    
    INTERNAL["Internal Unified<br/>Representation<br/>PyTorch Tensors"]
    
    ML_SYSTEM["ML System<br/>as_mace_system()<br/>as_orb_system()"]
    HYBRID["Hybrid ML/MM<br/>MLMMsystem"]
    
    AMBER_IN --> INTERNAL
    GRO_IN --> INTERNAL
    INTERNAL --> ML_SYSTEM
    INTERNAL --> HYBRID
```

The `as_mace_system()` and `as_orb_system()` functions convert classical force field representations to ML potential formats, while `MLMMsystem` creates hybrid systems combining both.

**Sources:** Diagram 2 (Force Field Architecture), dimos_water_ml.py:62-76 (ML system conversion)

---