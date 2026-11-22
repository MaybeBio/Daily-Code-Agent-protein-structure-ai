

This page introduces the fundamental syntax and structure of Moltemplate LT (LAMMPS Template) files. LT files are text-based templates that define molecular systems, force fields, and simulation parameters for LAMMPS molecular dynamics simulations. Understanding LT file syntax is essential for building custom molecular systems, from simple molecules to complex multi-component materials.

## The Conceptual Foundation

Moltemplate uses a tree-based template system that transforms compact, human-readable definitions into complete LAMMPS input files. The system operates on two fundamental object types: **Static Objects** (class definitions) and **Instance Objects** (copies of those classes). This separation allows you to define a molecule once and create multiple copies with different positions and orientations, all while maintaining references to the same underlying force field parameters.

The syntax draws inspiration from directory paths, object-oriented programming concepts, and LAMMPS data file formats. When you write LT files, you're essentially building a hierarchical tree structure where nodes represent molecules, atoms, bonds, and other molecular components, and edges represent relationships like inheritance and composition.

Sources: [ttree.py](moltemplate/ttree.py#L10-L45)

## Basic File Structure

An LT file consists of comments, import statements, class definitions, variable declarations, and commands. Comments begin with the `#` character and continue to the end of the line. Import statements load external LT files, enabling modular organization of molecular definitions.

The most common structure follows this pattern:

```lt
# Import force field or molecule definitions
import "filename.lt"

# Define a new class
ClassName inherits ParentClass {
  # Variable declarations
  # Write commands
  # Instance creation
  # Transformation commands
}
```

The `ClassName` identifies your definition, `inherits ParentClass` establishes inheritance (optional), and everything within the curly braces belongs to that class definition. This hierarchical organization allows you to build complex systems from simple, reusable components.

Sources: [forcefield.lt](examples/coarse_grained/simple_examples/2bead_polymer/moltemplate_files/forcefield.lt#L1-L20), [ch2.lt](examples/all_atom/force_field_OPLSAA/alkane_chain_single/moltemplate_files/ch2.lt#L1-L25)

## Variable Categories and Prefixes

Moltemplate organizes variables into categories, each identified by a prefix that determines its behavior and where it appears in the generated LAMMPS files. The three primary prefixes are:

- **`@` (At-sign)**: Static variables defined in class definitions. These represent types, force field parameters, or other properties shared across all instances. Examples include `@atom:CA` (atom type CA), `@bond:OH` (bond type OH), and `@angle:HOH` (angle type HOH).
- **`$` (Dollar-sign)**: Instance variables unique to each specific instantiation. These represent actual atoms, bonds, and interactions in your system. Examples include `$atom:O` (a specific oxygen atom), `$bond:OH1` (a specific OH bond), and `$mol:...` (molecule ID references).
- **No prefix**: Special variables used for system-level settings and parameters that don't fit into the static/instance dichotomy.

The naming convention follows the pattern `prefix:category:name` or `prefix:name`, where the category organizes related variables and the name provides a unique identifier within that category. For example, `@atom:CA` represents a static atom type named "CA", while `$atom:ca` represents a specific instance of an atom.

Sources: [ttree.py](moltemplate/ttree.py#L27-L42), [spce.lt](moltemplate/force_fields/spce.lt#L4-L33)

## The Write Commands

The `write()` and `write_once()` commands control what content appears in the generated LAMMPS files and how it's formatted. These are the primary mechanism for outputting data to LAMMPS data files and input scripts.

```lt
write("Section Name") {
  variable1  value1  value2  value3
  variable2  value4  value5  value6
}

write_once("Section Name") {
  variable3  value7  value8
}
```

The **`write()`** command outputs content for every instance of a class. If you create 10 water molecules, each will write its atom coordinates through a `write("Data Atoms")` block. This is perfect for instance-specific data like atom positions.

The **`write_once()`** command outputs content only once, regardless of how many instances exist. This is ideal for global settings like force field parameters, masses, and simulation styles that shouldn't be duplicated. For example, atom masses and pair coefficients should use `write_once()`.

Common section names include `"Data Atoms"`, `"Data Masses"`, `"Data Bonds"`, `"In Settings"`, `"In Init"`, and `"Data Boundary"`. These correspond to sections in LAMMPS data files and commands in LAMMPS input scripts.

Sources: [forcefield.lt](examples/coarse_grained/simple_examples/2bead_polymer/moltemplate_files/forcefield.lt#L23-L28), [spce.lt](moltemplate/force_fields/spce.lt#L4-L33)

## Import Statements and Modular Organization

Import statements enable modular file organization, allowing you to separate force field definitions, molecule templates, and system configurations into different files. This promotes code reuse and makes large projects more manageable.

```lt
import "forcefield.lt"
import "monomer.lt"
```

Moltemplate searches for imported files in the current directory and in the `moltemplate/force_fields/` directory. You can also specify relative or absolute paths. The import system processes files recursively, so imported files can themselves contain additional imports.

This modular approach is evident in the examples, where force fields are defined once and imported by multiple molecule definitions. For instance, many examples import `oplsaa2024.lt` or `spce.lt` to access pre-defined force field parameters rather than redefining them.

Sources: [ch2.lt](examples/all_atom/force_field_OPLSAA/alkane_chain_single/moltemplate_files/ch2.lt#L4-L10), [polymer.lt](examples/coarse_grained/simple_examples/2bead_polymer/moltemplate_files/polymer.lt#L1-L2)

## Class Definitions and Inheritance

Class definitions create reusable templates for molecules or molecular components. The inheritance mechanism allows you to extend existing definitions, adding new atoms, bonds, or behaviors while inheriting all properties from the parent class.

```lt
ClassName inherits ParentClass {
  # Class content
}
```

Inheritance is powerful for creating specialized molecules from general templates. For example, a `Monomer` class might inherit from `ForceField`, gaining access to all atom types and force field parameters, while defining its own atom positions and internal bonds. This eliminates duplication and ensures consistency across related molecules.

Multiple classes can inherit from the same parent, creating a family of related molecules that all use consistent parameters. This is particularly useful in polymer systems where monomers share force field parameters but have different geometries.

Sources: [monomer.lt](examples/coarse_grained/simple_examples/2bead_polymer/moltemplate_files/monomer.lt#L2-L21), [forcefield.lt](examples/coarse_grained/simple_examples/2bead_polymer/moltemplate_files/forcefield.lt#L1-L10)

## The New Command and Instance Creation

The `new` command creates instances (copies) of classes, which you can then position, rotate, and manipulate independently. This is the primary mechanism for building systems from molecular components.

```lt
instanceName = new ClassName
instanceArray[index] = new ClassName
```

When you create an instance, Moltemplate instantiates the entire class hierarchy, including any nested objects. For example, creating a `Polymer` instance automatically creates all its constituent `Monomer` instances, which in turn create their individual atoms and bonds.

Instance names can be simple identifiers or array elements, enabling systematic organization of multiple instances. Arrays support range syntax and wildcards for batch operations. For instance, `monomers[0-9]` refers to the first 10 elements of an array, while `polymers[*][*][1]` selects specific slices.

Sources: [polymer.lt](examples/coarse_grained/simple_examples/2bead_polymer/moltemplate_files/polymer.lt#L8-L14), [alkane50.lt](examples/all_atom/force_field_OPLSAA/alkane_chain_single/moltemplate_files/alkane50.lt#L19-L70)

## Transformation Commands: rot() and move()

Transformation commands modify the positions and orientations of instances and their contained atoms. These commands are essential for assembling molecules into complex structures and positioning them in simulation boxes.

```lt
instanceName.rot(angle, x, y, z).move(dx, dy, dz)
instanceName.move(x, y, z)
```

The **`rot()`** command applies a rotation around an axis defined by the vector `(x, y, z)`. The angle is specified in degrees. Rotations are applied relative to the current orientation, allowing you to chain multiple rotations for complex repositioning. For example, `.rot(180.0, 1, 0, 0)` rotates 180 degrees around the X-axis.

The **`move()`** command translates the object by the specified vector. Like rotations, moves can be chained and are applied in the order they appear. Transformations are applied to all atoms and coordinate data within the transformed object.

These transformations are particularly powerful when building polymers, where each monomer might be rotated relative to the previous one and translated along the chain axis. The `alkane50.lt` example demonstrates this extensively, creating a 50-carbon alkane chain by sequentially positioning CH2 monomers.

Sources: [alkane50.lt](examples/all_atom/force_field_OPLSAA/alkane_chain_single/moltemplate_files/alkane50.lt#L19-L70), [polymer.lt](examples/coarse_grained/simple_examples/2bead_polymer/moltemplate_files/polymer.lt#L8-L14)

## Variable References and Path Syntax

Moltemplate uses a directory-like path syntax to reference variables across the class hierarchy. This allows you to reference atoms and bonds defined in one class when creating bonds or interactions in another.

```lt
$atom:mon1/ca
$atom:monomers[0]/c
@bond:Backbone
```

The path syntax works like file system paths, with forward slashes separating levels in the hierarchy. Instance variables use `$` prefix, while static variables use `@` prefix. The path traverses down the instance tree, allowing you to reference atoms in nested instances.

When creating bonds between monomers in a polymer, you reference atoms in different monomer instances using these paths. For example, `$atom:mon1/ca` refers to the atom named "ca" within the instance named "mon1". This path-based reference system makes it easy to connect molecules that were created independently.

Sources: [polymer.lt](examples/coarse_grained/simple_examples/2bead_polymer/moltemplate_files/polymer.lt#L16-L25), [alkane50.lt](examples/all_atom/force_field_OPLSAA/alkane_chain_single/moltemplate_files/alkane50.lt#L72-L124)

## The create_var Command

The `create_var` command controls variable sharing between instances, particularly useful for managing molecule IDs across polymer systems.

```lt
create_var {$mol}
```

When you use `create_var {$mol}`, all instances within that class hierarchy share the same molecule ID variable. This ensures that all atoms in a polymer belong to the same molecule as defined by LAMMPS, rather than each monomer being assigned a separate molecule ID.

This is essential for polymers and other multi-monomer structures where the entire chain should be treated as a single molecule. Without this command, each monomer instance would receive its own molecule ID, potentially affecting how LAMMPS handles molecular motion and analysis.

Sources: [polymer.lt](examples/coarse_grained/simple_examples/2bead_polymer/moltemplate_files/polymer.lt#L7), [alkane50.lt](examples/all_atom/force_field_OPLSAA/alkane_chain_single/moltemplate_files/alkane50.lt#L16)

## Atom Type and Force Field Parameter Definitions

Defining atom types and force field parameters is fundamental to creating functional molecular systems. These definitions typically live in force field files and are referenced by molecule definitions.

```lt
write_once("Data Masses") {
  @atom:CA    13.0
  @atom:R     50.0
}

write_once("In Settings") {
  bond_coeff  @bond:Sidechain   15.0   3.4
  angle_coeff @angle:Backbone   30.00  114
  pair_coeff  @atom:CA @atom:CA  0.10   2.0
}
```

**Masses** define the atomic weight for each atom type. These are written once using `write_once()`.

**Bond coefficients** define harmonic bond parameters (force constant and equilibrium distance). Multiple bond types can be defined, each representing a different chemical environment.

**Angle and dihedral coefficients** define parameters for three- and four-body interactions, governing molecular flexibility and torsional behavior.

**Pair coefficients** define non-bonded interactions between atom types, typically using Lennard-Jones or similar potentials. These determine van der Waals interactions between atoms.

The `@` prefix indicates these are static definitions shared across all instances, ensuring consistent force field application throughout the system.

Sources: [forcefield.lt](examples/coarse_grained/simple_examples/2bead_polymer/moltemplate_files/forcefield.lt#L30-L80), [spce.lt](moltemplate/force_fields/spce.lt#L14-L57)

## Atom Definition Syntax

Defining individual atoms involves specifying their type, charge, and position. The exact format depends on the LAMMPS atom style being used, but the general pattern is consistent.

```lt
write("Data Atoms") {
  $atom:O  $mol:. @atom:O -0.8476  0.0000000 0.00000 0.000000
  $atom:H1 $mol:. @atom:H  0.4238  0.8164904 0.00000  0.5773590
}
```

Each line in the `Data Atoms` section defines one atom:

- **Instance variable** (`$atom:O`): A unique name for this specific atom instance
- **Molecule ID** (`$mol:.`): References the molecule containing this atom (use `...` for hierarchical membership)
- **Atom type** (`@atom:O`): The static atom type defining force field parameters
- **Charge** (`-0.8476`): Partial atomic charge (can be omitted if auto-generated)
- **Coordinates** (`0.0000000 0.00000 0.000000`): X, Y, Z positions in Angstroms

The atom style determines the exact number and order of fields. Common styles include `full` (atom ID, molecule ID, atom type, charge, x, y, z) and `molecular` (atom ID, molecule ID, atom type, x, y, z).

Sources: [spce.lt](moltemplate/force_fields/spce.lt#L4-L11), [monomer.lt](examples/coarse_grained/simple_examples/2bead_polymer/moltemplate_files/monomer.lt#L5-L8)

## Bond, Angle, and Dihedral Definitions

Defining interactions between atoms follows similar patterns across bond, angle, and dihedral types. These definitions connect the atoms you've defined and specify the interaction parameters.

```lt
write("Data Bonds") {
  $bond:OH1 @bond:OH $atom:O $atom:H1
  $bond:OH2 @bond:OH $atom:O $atom:H2
}

write("Data Angles") {
  $angle:HOH @angle:HOH $atom:H1 $atom:O $atom:H2
}
```

Each interaction definition includes:

- **Instance variable** (`$bond:OH1`): Unique name for this specific interaction
- **Interaction type** (`@bond:OH`): The static type defining force field parameters
- **Atom references** (`$atom:O $atom:H1`): Pointers to the atoms involved

Bonds connect two atoms, angles connect three atoms, and dihedrals connect four atoms. The atom references use the path syntax described earlier, allowing connections between atoms in different parts of the molecule hierarchy.

Sources: [spce.lt](moltemplate/force_fields/spce.lt#L12-L21), [monomer.lt](examples/coarse_grained/simple_examples/2bead_polymer/moltemplate_files/monomer.lt#L10-L12)

## Automatic Interaction Generation

Moltemplate can automatically generate bonds, angles, and dihedrals based on atom types and connection patterns, reducing manual specification effort.

```lt
write_once("Data Angles By Type") {
  @angle:Backbone  @atom:CA  @atom:CA  @atom:CA   @bond:*   @bond:*
  @angle:Sidechain @atom:CA  @atom:CA  @atom:R    @bond:*   @bond:*
}

write_once("Data Dihedrals By Type") {
  @dihedral:CCCC @atom:CA @atom:CA @atom:CA @atom:CA  @bond:* @bond:* @bond:*
  @dihedral:RCCR @atom:R  @atom:CA @atom:CA @atom:R   @bond:* @bond:* @bond:*
}
```

These rules define patterns for automatic interaction generation:

- **Atom type sequences** specify which atom combinations create interactions
- **Bond type patterns** (`@bond:*`) match any bond type, allowing flexible matching
- **Wildcards** (`*`) in bond types match any bond, making rules more general

When Moltemplate processes these rules, it searches the molecular structure for matching patterns and creates the corresponding interactions automatically. This is particularly valuable for complex molecules with many repeating interaction patterns.

Sources: [forcefield.lt](examples/coarse_grained/simple_examples/2bead_polymer/moltemplate_files/forcefield.lt#L68-L82)

## System-Level Configuration

System-level commands define simulation box boundaries, global settings, and other properties that apply to the entire system rather than individual molecules.

```lt
write_once("Data Boundary") {
  0 90.0 xlo xhi
  0 90.0 ylo yhi
  0 90.0 zlo zhi
}

write_once("In Init") {
  units        real
  atom_style   full
  pair_style   lj/charmm/coul/long 9.0 10.0 10.0
  bond_style   harmonic
  angle_style  harmonic
  kspace_style pppm 0.0001
}
```

**Boundary definitions** specify the simulation box dimensions. LAMMPS uses periodic boundary conditions by default, so atoms that move past one boundary re-enter from the opposite side.

**Initialization commands** define global simulation parameters. These include units (`real`, `lj`, etc.), atom styles (determining what information each atom carries), interaction styles (equations for calculating forces), and long-range solvers.

System-level settings typically use `write_once()` since they should appear only once in the generated files, regardless of how many molecules are present.

Sources: [system.lt](examples/coarse_grained/simple_examples/2bead_polymer/moltemplate_files/system.lt#L4-L7), [spce.lt](moltemplate/force_fields/spce.lt#L40-L50)

## Best Practices and Common Patterns

Effective LT file development follows several established patterns that improve maintainability and reduce errors:

**Start simple**: Begin with a minimal working example, then incrementally add complexity. Test after each addition to isolate problems quickly. The 2bead_polymer example is an excellent starting point for understanding the basics.

**Use inheritance wisely**: Create base classes for common components (force fields, standard monomers) and inherit to create specialized versions. This reduces duplication and ensures consistency. The OPLSAA force field files demonstrate this pattern extensively.

**Modular organization**: Separate force fields, molecule definitions, and system configurations into different files. Use imports to assemble them. This makes projects easier to navigate and modify.

**Meaningful naming**: Use descriptive names for atoms, bonds, and interactions. Names like `$atom:ca` and `$bond:backbone1` are more informative than `$atom:a1` and `$bond:b1`.

**Comment generously**: Document the purpose of each class, the chemistry being represented, and any non-obvious design decisions. Comments help others (and your future self) understand the code.

**Leverage existing force fields**: Don't redefine parameters that already exist in standard force field files. Import and reference them instead. The `moltemplate/force_fields/` directory contains many ready-to-use force fields.

> [!TIP]
> When building polymers, the `create_var {$mol}` command is essential to ensure all monomers share the same molecule ID. Without it, each monomer would be assigned a separate molecule ID, potentially affecting molecular dynamics calculations and analysis.

> [!TIP]
> The path syntax `$atom:instanceName/atomName` is powerful but can be confusing. Remember that paths traverse down the instance hierarchy, not up. When creating bonds between molecules, reference atoms in each molecule using their full paths from the current context.

## Complete Example: Simple Polymer System

Putting all the concepts together, here's a simplified view of how a polymer system is built from LT files:

```lt
# forcefield.lt - Force field definitions
ForceField {
  write_once("Data Masses") {
    @atom:CA  13.0
    @atom:R   50.0
  }
  write_once("In Settings") {
    bond_coeff  @bond:Backbone   15.0   3.7
  }
}

# monomer.lt - Monomer definition
import "forcefield.lt"
Monomer inherits ForceField {
  write("Data Atoms") {
    $atom:ca $mol:. @atom:CA   0.0   0.0  1.0  0.0
    $atom:r  $mol:. @atom:R    0.0   0.0  4.4  0.0
  }
  write("Data Bonds") {
    $bond:cr  @bond:Sidechain  $atom:ca  $atom:r
  }
}

# polymer.lt - Polymer assembly
import "monomer.lt"
Polymer inherits ForceField {
  create_var {$mol}
  mon1 = new Monomer
  mon2 = new Monomer.rot(180, 1,0,0).move(3.2,0,0)
  write("Data Bonds") {
    $bond:b1  @bond:Backbone  $atom:mon1/ca  $atom:mon2/ca
  }
}

# system.lt - System configuration
import "polymer.lt"
write_once("Data Boundary") {
  0 90.0 xlo xhi
  0 90.0 ylo yhi
  0 90.0 zlo zhi
}
polymers = new Polymer[3].move(0,0,30)
```

This example demonstrates the complete workflow: define force field parameters, create a monomer building block, assemble monomers into a polymer, and configure the simulation system.

Sources: [forcefield.lt](examples/coarse_grained/simple_examples/2bead_polymer/moltemplate_files/forcefield.lt), [monomer.lt](examples/coarse_grained/simple_examples/2bead_polymer/moltemplate_files/monomer.lt), [polymer.lt](examples/coarse_grained/simple_examples/2bead_polymer/moltemplate_files/polymer.lt), [system.lt](examples/coarse_grained/simple_examples/2bead_polymer/moltemplate_files/system.lt)

## Next Steps

Now that you understand the LT file syntax fundamentals, explore these related topics:

- **[Core Template System Architecture](7-core-template-system-architecture)**: Deep dive into how the template engine processes LT files and builds the instance tree
- **[Static Objects and Class Definitions](8-static-objects-and-class-definitions)**: Learn advanced class definition patterns and inheritance strategies
- **[Instance Objects and Instantiation](9-instance-objects-and-instantiation)**: Understand the instantiation process and instance variable handling
- **[Your First Moltemplate Simulation](5-your-first-moltemplate-simulation)**: Walk through creating and running your first simulation

For practical examples, explore the [examples directory](../examples) which contains approximately 50 working examples ranging from simple water boxes to complex membrane systems.