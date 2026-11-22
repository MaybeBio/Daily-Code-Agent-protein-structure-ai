# Molecule Representation

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [vermouth/molecule.py](vermouth/molecule.py)
- [vermouth/processors/make_bonds.py](vermouth/processors/make_bonds.py)
- [vermouth/processors/name_moltype.py](vermouth/processors/name_moltype.py)
- [vermouth/tests/data/2dn2.pdb](vermouth/tests/data/2dn2.pdb)
- [vermouth/tests/molecule_strategies.py](vermouth/tests/molecule_strategies.py)
- [vermouth/tests/test_make_bonds.py](vermouth/tests/test_make_bonds.py)
- [vermouth/tests/test_molecule.py](vermouth/tests/test_molecule.py)
- [vermouth/tests/test_utils.py](vermouth/tests/test_utils.py)
- [vermouth/utils.py](vermouth/utils.py)

</details>



## Introduction

This page describes the graph-based representation of molecules in the VerMoUTH & martinize2 system. The molecule representation is a fundamental component that serves as the core data structure for all molecular operations, transformations, and simulations. The `Molecule` class extends NetworkX's Graph class to provide specialized functionality for molecular structures, where atoms are represented as nodes and bonds as edges.

For information about force fields that define the rules for these molecules, see [Force Fields](#2.2). For understanding how the system stores multiple molecules, see [System and Topology](#2.3).

Sources: [vermouth/molecule.py:313-363](vermouth/molecule.py:313-363)

## Molecule Data Model

### Graph Representation

The core architecture of the `Molecule` class uses a graph-based representation that leverages NetworkX, a powerful Python graph library:

```mermaid
classDiagram
    class NetworkX_Graph {
        +nodes(data)
        +edges(data)
        +add_node()
        +add_edge()
    }
    
    class Molecule {
        +meta: dict
        +nrexcl: int
        +interactions: dict[str, list[Interaction]]
        +force_field
        +box
        +citations: set[str]
        +add_interaction()
        +remove_interaction()
        +merge_molecule()
        +copy()
        +subgraph()
    }
    
    class Interaction {
        +atoms: tuple
        +parameters
        +meta: dict
    }
    
    NetworkX_Graph <|-- Molecule
    Molecule *-- "*" Interaction
```

In this model:
- Atoms are nodes in the graph, with attributes like positions, names, types, and charges
- Bonds are edges in the graph, with optional attributes like bond parameters
- Additional interactions like angles, dihedrals, and non-bonded terms are stored separately

The `Molecule` class maintains an ordered dictionary of nodes to ensure consistent ordering, which is important for output file generation.

Sources: [vermouth/molecule.py:313-363](vermouth/molecule.py:313-363), [vermouth/molecule.py:29-32](vermouth/molecule.py:29-32)

## Key Attributes and Properties

### Core Attributes

```mermaid
graph TD
    subgraph "Molecule Core Properties"
        A["meta: dict"] --> A1["Arbitrary metadata"]
        B["nrexcl: int"] --> B1["Exclusion distance for<br/>non-bonded interactions"]
        C["interactions: dict"] --> C1["Bonded and non-bonded<br/>interaction parameters"]
        D["force_field"] --> D1["Reference to parent<br/>force field"]
        E["citations: set"] --> E1["Citation keys for<br/>scientific references"]
        F["box"] --> F1["Simulation box dimensions"]
    end
```

Each `Molecule` instance has several key attributes:

| Attribute | Type | Description |
|-----------|------|-------------|
| `meta` | dict | Metadata about the molecule (e.g., name, type) |
| `nrexcl` | int | Number of bonds to exclude for non-bonded interactions |
| `interactions` | dict[str, list[Interaction]] | Stores interactions by type (bonds, angles, etc.) |
| `force_field` | ForceField | Reference to the force field the molecule is described for |
| `citations` | set[str] | Citation keys for scientific references related to the molecule |
| `box` | array | Simulation box dimensions (if applicable) |

Sources: [vermouth/molecule.py:346-364](vermouth/molecule.py:346-364)

### Interactions

Interactions represent various bonded and non-bonded terms in the molecule, including:
- Bonds between atom pairs
- Angles between atom triplets
- Dihedrals between four consecutive atoms
- Improper dihedrals
- Other specialized interactions defined by the force field

Each interaction is represented as a named tuple `Interaction` with fields:
- `atoms`: Tuple of atoms involved in the interaction
- `parameters`: Values defining the interaction (e.g., force constants, equilibrium values)
- `meta`: Dictionary of metadata about the interaction

```mermaid
graph TB
    subgraph "Molecule"
        A[Molecule] --> B["interactions: dict"]
    end
    
    subgraph "Interaction Types"
        B --> C["bonds: list[Interaction]"]
        B --> D["angles: list[Interaction]"]
        B --> E["dihedrals: list[Interaction]"]
        B --> F["impropers: list[Interaction]"]
        B --> G["constraints: list[Interaction]"]
        B --> H["other types..."]
    end
    
    subgraph "Interaction Structure"
        C --> I["Interaction(atoms=(0,1), parameters=['1', '0.2'], meta={})"]
        D --> J["Interaction(atoms=(0,1,2), parameters=['2', '120.0'], meta={})"]
    end
```

Sources: [vermouth/molecule.py:29-32](vermouth/molecule.py:29-32), [vermouth/molecule.py:490-520](vermouth/molecule.py:490-520)

## Working with Molecules

### Creating and Modifying Molecules

Creating a molecule and adding atoms and bonds:

```python
# Create a new molecule
molecule = Molecule()

# Add atoms (nodes)
molecule.add_node(0, atomname='C', element='C', position=[0, 0, 0])
molecule.add_node(1, atomname='H', element='H', position=[0, 0, 1.1])

# Add a bond (edge)
molecule.add_edge(0, 1)

# Add an interaction
molecule.add_interaction(
    type_='bonds',
    atoms=(0, 1),
    parameters=['1', '0.2', '200'],
    meta={'comment': 'C-H bond'}
)
```

The `Molecule` class also provides methods to remove atoms and bonds, and to manipulate interactions:

```mermaid
flowchart LR
    subgraph "Molecule Modification Methods"
        A["add_node()"] --> A1["Add an atom"]
        B["add_edge()"] --> B1["Add a bond"]
        C["add_interaction()"] --> C1["Add bonded/non-bonded term"]
        
        D["remove_node()"] --> D1["Remove atom and<br/>related interactions"]
        E["remove_edge()"] --> E1["Remove a bond"]
        F["remove_interaction()"] --> F1["Remove a specific<br/>interaction"]
    end
```

Sources: [vermouth/molecule.py:490-520](vermouth/molecule.py:490-520), [vermouth/molecule.py:580-610](vermouth/molecule.py:580-610), [vermouth/molecule.py:954-974](vermouth/molecule.py:954-974)

### Automatic Bond Generation

The system can automatically generate bonds based on:

1. **Distance criteria**: Using van der Waals radii to estimate when atoms are close enough to be bonded
2. **Reference structures**: Using known molecular topologies to define bonds

```mermaid
flowchart TD
    A["Input Molecule<br/>(atoms with 3D positions)"] --> B["MakeBonds Processor"]
    
    subgraph "Bond Generation Strategies"
        B --> C["By Distance"]
        B --> D["By Reference Block"]
        
        C --> C1["Use van der Waals radii<br/>to determine bond distance"]
        C --> C2["Filter H-H bonds<br/>and cross-residue H bonds"]
        
        D --> D1["Match atoms by name<br/>to reference block"]
        D --> D2["Apply same connectivity<br/>as reference"]
    end
    
    C2 --> E["Generated bonds<br/>(edges in graph)"]
    D2 --> E
```

The `MakeBonds` processor can use a combination of geometric and topological criteria to create bonds between atoms, with customizable parameters to control the process.

Sources: [vermouth/processors/make_bonds.py:222-306](vermouth/processors/make_bonds.py:222-306)

## Advanced Features

### Molecule Comparison and Equality

The `Molecule` class provides methods to compare molecules at different levels:

1. **Full equality** (`__eq__`): Compares all aspects including node order, edges, and interactions
2. **Topology equality** (`share_moltype_with`): Checks if two molecules have the same topological structure (useful for grouping similar molecules)

```mermaid
flowchart LR
    A["Molecule Comparison"] --> B["__eq__()"]
    A --> C["share_moltype_with()"]
    
    B --> B1["Compare nrexcl"]
    B --> B2["Compare force_field"]
    B --> B3["Compare nodes (ordered)"]
    B --> B4["Compare edges (unordered)"]
    B --> B5["Compare interactions"]
    
    C --> C1["Compare nodes (ignore position)"]
    C --> C2["Compare edges"]
    C --> C3["Compare interactions"]
```

These comparison methods support efficient molecule grouping and classification, which is critical for operations like creating molecular dynamics topology files.

Sources: [vermouth/molecule.py:366-373](vermouth/molecule.py:366-373), [vermouth/molecule.py:748-773](vermouth/molecule.py:748-773)

### Molecule Copying and Subgraphs

The `Molecule` class provides methods to create copies and subgraphs:

1. **Copy** (`copy`): Creates a complete copy of the molecule
2. **Subgraph** (`subgraph`): Creates a molecule containing only the specified subset of atoms

```mermaid
flowchart TD
    A["Original Molecule"] --> B["copy()"]
    A --> C["subgraph([node_indices])"]
    
    B --> B1["Complete duplicate<br/>with same nodes, edges,<br/>and interactions"]
    
    C --> C1["Node subset"]
    C --> C2["Edges between selected nodes"]
    C --> C3["Interactions involving<br/>only selected nodes"]
```

These methods are essential for operations like extracting specific residues, creating fragments, or duplicating molecules for mutation.

Sources: [vermouth/molecule.py:439-488](vermouth/molecule.py:439-488)

### Merging Molecules

The `merge_molecule` method allows combining two molecules into one:

```mermaid
flowchart LR
    A["Molecule A"] --> C["A.merge_molecule(B)"]
    B["Molecule B"] --> C
    C --> D["Combined Molecule"]
    
    subgraph "Merge Process"
        E["Offset atom indices"]
        F["Offset residue numbers"]
        G["Combine interactions"]
        H["Combine edges"]
        I["Merge citations"]
    end
    
    C --> E
    C --> F
    C --> G
    C --> H
    C --> I
```

This is useful for building larger structures from smaller components, such as constructing a protein from individual residues or creating multi-component systems.

Sources: [vermouth/molecule.py:673-746](vermouth/molecule.py:673-746)

## Dynamic Parameter Calculation

The `LinkParameterEffector` system provides a way to calculate interaction parameters dynamically based on the molecular structure:

```mermaid
classDiagram
    class LinkParameterEffector {
        +keys: list
        +format: str
        +__call__(molecule, match)
        +_apply(molecule, keys) abstract
    }
    
    class ParamDistance {
        +n_keys_asked = 2
        +_apply(molecule, keys)
    }
    
    class ParamAngle {
        +n_keys_asked = 3
        +_apply(molecule, keys)
    }
    
    class ParamDihedral {
        +n_keys_asked = 4
        +_apply(molecule, keys)
    }
    
    LinkParameterEffector <|-- ParamDistance
    LinkParameterEffector <|-- ParamAngle
    LinkParameterEffector <|-- ParamDihedral
```

These parameter effectors can compute:
- Bond distances between atoms
- Angles between three atoms
- Dihedral angles between four atoms

This system allows for dynamic parameter generation based on molecular geometry, which is particularly useful when applying force field transformations or when constructing force field parameters based on the current conformation.

Sources: [vermouth/molecule.py:134-246](vermouth/molecule.py:134-246), [vermouth/molecule.py:249-310](vermouth/molecule.py:249-310)

## Implementation Details

### Attribute Comparison

The system uses specialized comparison mechanisms to handle different attribute types:

1. **Attribute equality**: The `are_different` utility provides sophisticated equality testing for various data types
2. **LinkPredicate**: Defines special comparison criteria for node attributes in links

```mermaid
flowchart TD
    A["Attribute Comparison"] --> B["are_different()"]
    A --> C["LinkPredicate classes"]
    
    B --> B1["Numbers: numpy.isclose()"]
    B --> B2["Arrays: element-wise comparison"]
    B --> B3["Dictionaries: key and value comparison"]
    B --> B4["Iterables: element by element"]
    
    C --> C1["Choice: value in list"]
    C --> C2["NotDefinedOrNot: value != reference"]
```

These mechanisms support flexible pattern matching when applying force field transformations and when comparing molecule structures.

Sources: [vermouth/molecule.py:34-132](vermouth/molecule.py:34-132), [vermouth/utils.py:147-199](vermouth/utils.py:147-199)

### Node and Edge Management

The `Molecule` class extends NetworkX's graph management but adds specialized behaviors:

1. Removing nodes also removes associated interactions
2. Adding nodes updates atom indexing
3. Making edges from interactions automatically converts interaction definitions to graph connectivity

These behaviors ensure the graph structure remains consistent with the chemical understanding of the molecule.

Sources: [vermouth/molecule.py:935-1012](vermouth/molecule.py:935-1012)

## Integration with Other Components

The molecule representation serves as the foundation for nearly all operations in the vermouth-martinize system:

```mermaid
flowchart TD
    A["Molecule Representation"] --> B["PDB/GRO/CIF Parsers"]
    A --> C["Force Field Application"]
    A --> D["Graph Repair"]
    A --> E["Mapping Transformations"]
    A --> F["Structural Features<br/>(Elastic Networks, Go Models)"]
    A --> G["Topology Output"]
```

This central role makes the `Molecule` class one of the most critical components of the entire system, with its design influencing all downstream processing and analysis.

Sources: [vermouth/molecule.py:313-363](vermouth/molecule.py:313-363)

---