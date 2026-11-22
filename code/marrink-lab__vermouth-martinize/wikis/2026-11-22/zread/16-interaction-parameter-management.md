

The interaction parameter management system in vermouth-martinize provides a sophisticated framework for defining, parsing, and applying molecular interaction parameters across different force fields. This system enables flexible specification of bonds, angles, dihedrals, constraints, and other interaction types with dynamic parameter calculation capabilities.

## Core Architecture

The interaction parameter system is built around several key components that work together to manage force field parameters:

### Parameter Effectors

The system supports dynamic parameter calculation through parameter effectors that can compute values based on molecular geometry at runtime. These effectors are defined in the `PARAMETER_EFFECTORS` dictionary [vermouth/ffinput.py#L55-L62]:

```python
PARAMETER_EFFECTORS = {
    'dist': ParamDistance,
    'angle': ParamAngle,
    'dihedral': ParamDihedral,
    'dihphase': ParamDihedralPhase,
}
```

Each effector class inherits from `LinkParameterEffector` and implements specific geometric calculations:

- **ParamDistance**: Calculates distance between two nodes [vermouth/molecule.py#L267-L282]
- **ParamAngle**: Calculates angle between three consecutive nodes in degrees [vermouth/molecule.py#L283-L299]
- **ParamDihedral**: Calculates dihedral angle defined by four nodes in degrees [vermouth/molecule.py#L300-L315]
- **ParamDihedralPhase**: Calculates dihedral angle shifted by -180 degrees [vermouth/molecule.py#L316-L330]

### Interaction Type Support

The system supports comprehensive interaction types through the `interactions_natoms` mapping [vermouth/ffinput.py#L65-L85]:

| Interaction Type | Number of Atoms | Description |
|------------------|-----------------|-------------|
| bonds | 2 | Bond interactions |
| angles | 3 | Angle interactions |
| dihedrals | 4 | Dihedral angle interactions |
| impropers | 4 | Improper dihedral interactions |
| constraints | 2 | Distance constraints |
| pairs | 2 | Non-bonded pair interactions |
| position_restraints | 1 | Position restraints |
| virtual_sites2-4 | 3-5 | Virtual site definitions |

## Force Field File Structure

### FF File Format

The `.ff` file format provides a structured way to define molecular components and their interactions. The format is built on a subset of the ITP format and includes several key sections:

#### Variables Section
Global variables can be defined for use throughout the force field:
```ff
[ variables ]
elastic_network_bond_type 1
res_min_dist 3
prot_default_bb_type P2
stiff_fc 1000000
```

#### Molecule Definitions
Each molecule type is defined with its atoms and interactions:

```ff
[ moleculetype ]
ALA                1

[ atoms ]
;id type resnr residu atom cgnr   charge
 1   SP2    1   ALA    BB     1      0
 2   TC3    1   ALA    SC1    2      0 

[ constraints ]
;  i     j   funct   length  
  BB   SC1    1       0.270

[ bonds ]
;  i     j   funct   length  force.c.
  BB   SC1    1       0.270  $stiff_fc
```

#### Conditional Interactions
The system supports conditional interactions using meta directives:

```ff
[ constraints ]
#meta {"group": "Side chain bonds", "ifndef": "FLEXIBLE"}
;  i     j   funct   length  
  BB   SC1    1       0.270

[ bonds ]
#meta {"group": "Side chain bonds", "ifdef": "FLEXIBLE"}
;  i     j   funct   length  
  BB   SC1    1       0.270  $stiff_fc
```

## Parameter Parsing System

### Dynamic Parameter Resolution

The parsing system can handle both static parameters and dynamic calculations. When a parameter effector is encountered, it follows this process [vermouth/ffinput.py#L812-L835]:

1. **Effector Detection**: Tokens with parentheses are identified as parameter effectors
2. **Class Resolution**: The effector name is mapped to the appropriate class
3. **Parameter Extraction**: Comma-separated parameters are extracted from within parentheses
4. **Format Specification**: Optional format specifications can be provided using the `|` separator

Example usage in force field files:
```ff
[ bonds ]
;  i     j   funct   length              force.c.
  BB   SC1    1    dist(BB,SC1)|.3f     angle(BB,SC1,SC2)*10
```

### Interaction Management

The `Molecule` class provides comprehensive interaction management methods:

- **add_interaction**: Add new interactions with metadata [vermouth/molecule.py#L522-L553]
- **add_or_replace_interaction**: Add interactions or replace existing ones [vermouth/molecule.py#L554-L595]
- **get_interaction**: Retrieve interactions by type [vermouth/molecule.py#L596-L612]
- **remove_interaction**: Remove specific interactions [vermouth/molecule.py#L613-L643]
- **remove_matching_interaction**: Remove interactions matching templates [vermouth/molecule.py#L644-L664]

## Force Field Organization

### Directory Structure

Force fields are organized in `vermouth/data/force_fields/` with each force field having its own subdirectory:

```
force_fields/
├── martini3001/
│   ├── aminoacids.ff
│   ├── general.ff
│   ├── modifications.ff
│   ├── nucleotides.ff
│   └── citations.bib
├── martini22/
├── charmm/
└── amber/
```

### Modification System

The modification system allows for atomic-level changes to molecular building blocks. Modifications are defined in `.ff` files and can:

- Replace atom types and charges
- Add or remove atoms
- Modify connectivity

Example modification for terminal groups:
```ff
[ modification ]
C-ter
[ atoms ]
BB {"replace": {"atype": "Q5", "charge": -1}}
```

## Integration with Force Field Classes

The `ForceField` class serves as the central hub for managing all force field data [vermouth/forcefield.py#L36-L142]. It provides:

- **File Reading**: Automatic discovery and parsing of force field files
- **Reference Graphs**: Access to all known molecular blocks
- **Feature Management**: Declaration and querying of force field features
- **Citation Management**: Bibliographic information tracking

### Force Field Loading

Force fields are loaded using the `read_from` method which:
1. Scans the directory for supported file types
2. Uses appropriate parsers for each file extension
3. Populates the force field with parsed data
4. Maintains relationships between blocks, links, and modifications

## Advanced Features

### Conditional Compilation

The system supports conditional compilation of interactions based on variables:
- `#ifdef VARIABLE`: Include section if variable is defined
- `#ifndef VARIABLE`: Include section if variable is not defined
- Variables can be set in the `[ variables ]` section

### Meta Information

Interactions can include meta information for organization and debugging:
```ff
#meta {"group": "Side chain bonds", "description": "Backbone-side chain connections"}
```

### Citation Integration

Force fields can include bibliographic information that gets automatically associated with the molecular components that use them.

## Best Practices

1. **Variable Naming**: Use descriptive variable names that reflect their purpose
2. **Parameter Organization**: Group related interactions using meta directives
3. **Conditional Logic**: Use conditional compilation for different simulation scenarios
4. **Documentation**: Include comprehensive comments and meta information
5. **Testing**: Validate parameter calculations across different molecular geometries

This interaction parameter management system provides a robust foundation for defining complex molecular force fields while maintaining flexibility for different scientific applications and simulation requirements.

For more details on related topics, see [Force Field System and Data Management](10-force-field-system-and-data-management) and [Custom Force Field Development](15-custom-force-field-development).