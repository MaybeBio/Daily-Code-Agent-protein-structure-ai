

The vermouth-martinize framework employs a sophisticated graph-based molecular representation system that forms the foundation for molecular coarse-graining and force field application. This architecture leverages NetworkX graphs to represent molecular topology, enabling powerful graph algorithms for structure analysis, manipulation, and transformation.

## Core Graph Architecture

### Molecule Class Foundation

The `Molecule` class extends `nx.Graph` to represent molecular structures as mathematical graphs where atoms are nodes and bonds are edges [molecule.py#L331](vermouth/molecule.py#L331-L400). This inheritance provides immediate access to NetworkX's extensive graph algorithms while adding molecular-specific functionality:

```python
class Molecule(nx.Graph):
    """
    Represents a molecule as per a specific force field. Consists of atoms
    (nodes), bonds (edges) and interactions such as angle potentials.
    """
    # As the particles are stored as nodes, we want the nodes to stay
    # ordered.
    node_dict_factory = OrderedDict
```

The molecule maintains several key attributes that extend beyond basic graph structure:

- **interactions**: Dictionary storing force field interactions (bonds, angles, dihedrals, etc.)
- **meta**: Metadata container for molecule-level information
- **nrexcl**: Exclusion distance for non-bonded interactions
- **citations**: Bibliographic references for the molecular description

### Interaction Management System

The framework implements a sophisticated interaction system that stores force field parameters separately from the graph topology [molecule.py#L522](vermouth/molecule.py#L522-L580):

```python
def add_interaction(self, type_, atoms, parameters, meta=None):
    """
    Add an interaction of the specified type with the specified parameters
    involving the specified atoms.
    """
    for atom in atoms:
        if atom not in self:
            raise KeyError('Unknown atom {}'.format(atom))
    self.interactions[type_].append(
        Interaction(atoms=tuple(atoms), parameters=parameters, meta=meta)
    )
```

This design separates topological connectivity (graph edges) from force field interactions, allowing flexible representation of different force field conventions while maintaining a clean graph structure.

## Hierarchical Graph Organization

### Residue-Level Abstraction

The system provides powerful tools for working with molecular hierarchies through residue graph construction [graph_utils.py#L230](vermouth/graph_utils.py#L230-L280):

```python
def make_residue_graph(graph, attrs=('chain', 'resid', 'resname', 'insertion_code')):
    """
    Create a new graph based on `graph`, where nodes with identical attribute
    values for the attribute names in `attrs` will be contracted into a single,
    coarser node. With the default arguments it will create a graph with one
    node per residue.
    """
```

This function enables multi-scale analysis by collapsing atomic-level graphs into residue-level representations, essential for coarse-graining workflows where individual atoms become beads.

### Block Template System

The `Block` class extends `Molecule` to represent residue topology templates [molecule.py#L1051](vermouth/molecule.py#L1051-L1100):

```python
class Block(Molecule):
    """
    Residue topology template

    Two blocks are equal if the underlying molecules are equal, and if the
    block names are equal.
    """
```

Blocks serve as templates that can be instantiated and modified to create specific molecular instances, providing a foundation for systematic molecular construction.

## Advanced Graph Algorithms

### Maximum Common Subgraph Detection

The framework implements categorical graph algorithms for molecular comparison and mapping [graph_utils.py#L92](vermouth/graph_utils.py#L92-L100):

```python
def categorical_maximum_common_subgraph(graph1, graph2, attributes=tuple()):
    """
    Find maximum common subgraphs between two graphs based on categorical
    attribute matching.
    """
    product = categorical_modular_product(graph1, graph2, attributes)
    cliques = nx.find_cliques(product)
    largest = maxes(cliques, key=len)
    matches = [dict(clique) for clique in largest]
    return matches
```

This algorithm is crucial for molecular mapping operations, enabling the identification of structural similarities between different molecular representations.

### Semantic Graph Matching

The `MappingGraphMatcher` class extends NetworkX's VF2 algorithm with semantic feasibility checking [graph_utils.py#L306](vermouth/graph_utils.py#L306-L318):

```python
class MappingGraphMatcher(nx.isomorphism.isomorphvf2.GraphMatcher):
    def semantic_feasibility(self, G1_node, G2_node):
        """
        Returns True if mapping G1_node to G2_node is semantically feasible.
        Adapted from networkx.algorithms.isomorphism.vf2userfunc._semantic_feasibility.
        """
```

This enables intelligent graph matching that considers molecular semantics beyond pure topological structure.

## Multi-Molecule System Management

### System-Level Organization

The `System` class provides container functionality for managing collections of molecules [system.py#L21](vermouth/system.py#L21-L30):

```python
class System:
    """
    A system of molecules.

    Attributes
    ----------
    molecules: list[:class:`~vermouth.molecule.Molecule`]
        The molecules in the system.
    """
```

This enables processing of complex molecular systems containing multiple molecules, chains, or domains while maintaining individual molecule integrity.

> [!TIP]
> The graph-based representation enables powerful molecular transformations through NetworkX algorithms. Operations like subgraph extraction, graph composition, and isomorphism testing become trivial once molecules are represented as graphs, facilitating complex coarse-graining workflows.

## Integration with Force Field System

The graph representation seamlessly integrates with the force field system, where nodes carry atom types, charges, and other force field parameters as attributes. This tight coupling enables automatic parameter assignment and validation during molecular transformations.

The separation of graph topology from interaction storage provides flexibility in supporting different force field formats while maintaining a consistent internal representation that can be efficiently manipulated and analyzed.

## Next Steps

To understand how these graph representations are transformed and processed, explore the [Processor Pipeline System](6-processor-pipeline-system) documentation. For detailed information about molecular operations and graph manipulations, see [Molecule Class and Graph Operations](8-molecule-class-and-graph-operations).