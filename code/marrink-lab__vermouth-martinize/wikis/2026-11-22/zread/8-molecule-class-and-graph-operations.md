

The vermouth library implements a sophisticated graph-based molecular representation system that forms the core of martinize2's molecular processing capabilities. This architecture leverages NetworkX graphs to represent molecular structures while extending them with domain-specific functionality for force field operations and molecular transformations.

## Core Molecule Class Architecture

### Foundation: NetworkX Graph Extension

The `Molecule` class extends `nx.Graph` to provide a robust foundation for molecular representation [molecule.py#L331](vermouth/molecule.py#L331-400). Each atom is stored as a node, bonds as edges, and higher-order interactions (angles, dihedrals, etc.) as specialized interaction data structures:

```python
class Molecule(nx.Graph):
    """
    Represents a molecule as per a specific force field. Consists of atoms
    (nodes), bonds (edges) and interactions such as angle potentials.
    """
    node_dict_factory = OrderedDict  # Ensures ordered atom representation
```

> [!TIP]
> The use of `OrderedDict` as `node_dict_factory` is critical for maintaining consistent atom ordering in output files, which is essential for reproducible molecular simulations.

### Interaction Management System

Molecules maintain a comprehensive interaction system using a dictionary structure where keys represent interaction types following GROMACS conventions ('bonds', 'angles', 'dihedrals', etc.) [molecule.py#L331](vermouth/molecule.py#L331-400):

```python
interactions: dict[str, list[Interaction]]
```

Each interaction is stored as a named tuple containing:
- `atoms`: tuple of atom identifiers involved
- `parameters`: force field parameters
- `meta`: metadata including comments and citations

### Dynamic Interaction API

The molecule class provides a sophisticated dynamic API for interaction management through `__getattr__` method interception [molecule.py#L684](vermouth/molecule.py#L684-697):

```python
def __getattr__(self, name):
    if name.startswith('get_') and name.endswith('s'):
        type_ = name[len('get_'):-len('s')]
        return partial(self.get_interaction, type_)
    elif name.startswith('add_'):
        type_ = name[len('add_'):]
        return partial(self.add_interaction, type_)
```

This enables intuitive method calls like `mol.add_bonds()`, `mol.get_angles()`, and `mol.remove_dihedrals()`.

## Graph Operations and Utilities

### Node and Edge Management

The molecule class overrides critical NetworkX methods to maintain interaction consistency:

- **Node Removal**: `remove_node()` and `remove_nodes_from()` automatically clean up associated interactions [molecule.py#L990](vermouth/molecule.py#L990-1007)
- **Subgraph Creation**: `subgraph()` returns new `Molecule` instances preserving interaction data [molecule.py#L485](vermouth/molecule.py#L485-494)
- **Molecule Merging**: `merge_molecule()` combines molecules with proper index offsetting [molecule.py#L705](vermouth/molecule.py#L705-723)

### Atomic Query System

The `find_atoms()` method provides powerful atomic querying capabilities [molecule.py#L665](vermouth/molecule.py#L665-676):

```python
def find_atoms(self, **attrs):
    """Yields all indices of atoms that match specified attributes"""
    for node_idx in self:
        node = self.nodes[node_idx]
        if attributes_match(node, attrs):
            yield node_idx
```

This enables complex queries like `mol.find_atoms(atomname='CA', resname='ALA')`.

## Specialized Molecular Templates

### Block Class: Residue Templates

The `Block` class extends `Molecule` to represent residue topology templates [molecule.py#L1051](vermouth/molecule.py#L1051-1100):

```python
class Block(Molecule):
    """
    Residue topology template
    
    Attributes
    ----------
    name: str or None
        The name of the residue
    """
```

Blocks include specialized methods for:
- Automatic angle and dihedral generation (`guess_angles()`, `guess_dihedrals()`)
- Residue-specific interaction management
- Template-to-molecule conversion with offset handling

### Link Class: Inter-Residue Connections

The `Link` class extends `Block` to define connections between residues [molecule.py#L1279](vermouth/molecule.py#L1279-1320):

```python
class Link(Block):
    """
    Template link between two residues.
    
    Includes:
    - non_edges: forbidden connections
    - removed_interactions: interactions to delete
    - patterns: matching conditions
    - features: required characteristics
    """
```

Links enable sophisticated molecular transformations by specifying:
- Which connections should NOT be created (`non_edges`)
- Which interactions should be removed (`removed_interactions`)
- Pattern matching conditions for application (`patterns`)
- Required molecular features (`features`)

### Modification Class: Structural Variants

The `Modification` class extends `Link` to represent structural deviations from standard blocks [molecule.py#L1380](vermouth/molecule.py#L1380-1384):

```python
class Modification(Link):
    """
    A modification which describes deviations from a :class:`Block`.
    """
```

## Advanced Graph Algorithms

### Residue Graph Operations

The `graph_utils` module provides sophisticated graph manipulation functions:

#### Residue Graph Creation
The `make_residue_graph()` function creates coarse-grained representations by contracting atoms into residue nodes [graph_utils.py#L230](vermouth/graph_utils.py#L230-280):

```python
def make_residue_graph(graph, attrs=('chain', 'resid', 'resname', 'insertion_code')):
    """Create a new graph where nodes with identical attribute values are contracted"""
```

This function is optimized for performance, using custom partitioning instead of NetworkX's `quotient_graph` to avoid O(N²) scaling.

#### Graph Matching and Isomorphism

The `MappingGraphMatcher` class extends NetworkX's isomorphism algorithms for molecular applications [graph_utils.py#L306](vermouth/graph_utils.py#L306-318):

```python
class MappingGraphMatcher(nx.isomorphism.isomorphvf2.GraphMatcher):
    def semantic_feasibility(self, G1_node, G2_node):
        """Custom semantic feasibility for molecular mapping"""
```

## Pattern Matching and Predicates

### Link Predicate System

The link system uses a sophisticated predicate framework for pattern matching:

#### Choice Predicate
Tests if attributes match predefined values [molecule.py#L94](vermouth/molecule.py#L94-103):

```python
class Choice(LinkPredicate):
    """Test if an attribute is defined and in a predefined list."""
```

#### Regex Predicate
Enables regular expression matching for attribute values [molecule.py#L110](vermouth/molecule.py#L110-119):

```python
class Regex(LinkPredicate):
    """Test if an attribute matches the provided regular expression."""
```

#### Negative Predicates
The `NotDefinedOrNot` predicate provides negation capabilities [molecule.py#L127](vermouth/molecule.py#L127-149).

## Parameter Calculation System

### Geometric Parameter Effectors

The system includes specialized classes for calculating interaction parameters from molecular geometry:

#### Distance Calculation
`ParamDistance` calculates inter-atomic distances [molecule.py#L267](vermouth/molecule.py#L267-276):

```python
class ParamDistance(LinkParameterEffector):
    """Calculate the distance between a pair of nodes."""
    n_keys_asked = 2
```

#### Angle Calculation
`ParamAngle` computes angles between three atoms [molecule.py#L283](vermouth/molecule.py#L283-293):

```python
class ParamAngle(LinkParameterEffector):
    """Calculate the angle in degrees between three consecutive nodes."""
    n_keys_asked = 3
```

#### Dihedral Calculation
`ParamDihedral` and `ParamDihedralPhase` handle torsion angle calculations [molecule.py#L300](vermouth/molecule.py#L300-326).

> [!TIP]
> All parameter effectors raise `ValueError` if atoms are missing or lack position data, ensuring robust error handling in molecular processing pipelines.

## Integration with Force Field System

The molecular graph system integrates seamlessly with the force field infrastructure through:

- **Force Field References**: Each molecule maintains a `_force_field` attribute for parameter resolution
- **Citation Management**: Automatic citation tracking for applied transformations
- **Metadata Propagation**: Rich metadata system for provenance tracking

## Performance Considerations

The architecture prioritizes performance through:

- **Ordered Node Storage**: Using `OrderedDict` for consistent atom ordering
- **Efficient Graph Algorithms**: Custom implementations avoiding NetworkX's O(N²) operations
- **Lazy Evaluation**: Dynamic method generation reducing memory footprint
- **Optimized Matching**: Custom semantic feasibility functions for molecular isomorphism

This graph-based molecular representation provides a flexible, extensible foundation for complex molecular transformations while maintaining the performance characteristics required for large-scale molecular simulations.

## Next Steps

To continue exploring the vermouth architecture, proceed to [Blocks, Links, and Modifications](9-blocks-links-and-modifications) for a deeper understanding of molecular templates and transformation patterns, or examine [Force Field System and Data Management](10-force-field-system-and-data-management) to understand how these graph structures integrate with force field parameters.