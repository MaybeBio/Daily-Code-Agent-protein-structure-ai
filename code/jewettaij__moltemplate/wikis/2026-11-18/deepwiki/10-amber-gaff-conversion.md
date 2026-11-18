# AMBER/GAFF Conversion

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [doc/doc_amber2lt.md](doc/doc_amber2lt.md)
- [moltemplate/amber2lt.py](moltemplate/amber2lt.py)
- [moltemplate/force_fields/convert_AMBER_files_to_LT_files/README.txt](moltemplate/force_fields/convert_AMBER_files_to_LT_files/README.txt)
- [moltemplate/force_fields/gaff.lt](moltemplate/force_fields/gaff.lt)
- [moltemplate/force_fields/gaff2.lt](moltemplate/force_fields/gaff2.lt)

</details>



## Overview

This page documents the process and tools for converting AMBER force field files (such as GAFF/GAFF2) into moltemplate format. The conversion enables molecular simulation workflows that originate with AMBER-based tools to seamlessly transition into LAMMPS simulations prepared with moltemplate. 

AMBER (Assisted Model Building with Energy Refinement) is a family of force fields commonly used for molecular dynamics of biomolecules, while GAFF (General AMBER Force Field) and GAFF2 are its extensions designed for small organic molecules. This document focuses specifically on the conversion process and not on the actual usage of these force fields - for information about using specific force fields in simulations, see [Force Fields](#5).

## Conversion Workflow

The conversion from AMBER force field files to moltemplate format is handled by the `amber2lt.py` script, which reads AMBER's `.dat` or `.frcmod` files and generates corresponding `.lt` files that can be used directly with moltemplate.

```mermaid
flowchart LR
    subgraph "Input Files"
        gaff["GAFF Files (.dat)"]
        frcmod["FRCMOD Files (.frcmod)"]
    end
    
    subgraph "Conversion Tool"
        amber2lt["amber2lt.py"]
    end
    
    subgraph "Output Files"
        lt["Force Field Files (.lt)"]
    end
    
    gaff --> amber2lt
    frcmod --> amber2lt
    amber2lt --> lt
    
    lt --> usage["Use in moltemplate files"]
    
    classDef box fill:none,stroke:#333,stroke-width:1px
    class "Input Files" box
    class "Conversion Tool" box
    class "Output Files" box
```

Sources: [moltemplate/amber2lt.py:1-13](), [doc/doc_amber2lt.md:1-21]()

## The amber2lt.py Tool

The `amber2lt.py` script is the primary tool for converting AMBER/GAFF format files to moltemplate format. It extracts information about atom types, masses, bonds, angles, dihedrals, impropers, and non-bonded parameters from AMBER files and reformats them into moltemplate's syntax.

### Basic Usage

The basic command syntax for using `amber2lt.py` is:

```
amber2lt.py --in INPUT_FILE --name FORCE_FIELD_NAME [--out OUTPUT_FILE]
```

Where:
- `INPUT_FILE` is the AMBER format file to convert (e.g., gaff.dat)
- `FORCE_FIELD_NAME` is the name you want to assign to the force field in moltemplate
- `OUTPUT_FILE` is the optional name for the output LT file (defaults to stdout if omitted)

For example, to convert the GAFF force field file to moltemplate format:

```
amber2lt.py --in gaff.dat --name GAFF --out gaff.lt
```

Sources: [moltemplate/amber2lt.py:797-816](), [doc/doc_amber2lt.md:10-29]()

### File Structure Conversion

The conversion process maps AMBER file sections to corresponding moltemplate sections:

```mermaid
flowchart TD
    subgraph "AMBER File Structure"
        a_mass["MASS Section"]
        a_bond["BOND Section"]
        a_angle["ANGLE Section"]
        a_dihedral["DIHEDRAL Section"]
        a_improper["IMPROPER Section"]
        a_pair["NONBONDED Section"]
    end
    
    subgraph "Conversion Process"
        extract["Extract Sections"]
        convert["Convert Parameters"]
        assemble["Assemble LT File"]
    end
    
    subgraph "Moltemplate LT File"
        lt_mass["Data Masses"]
        lt_pair["Pair Coefficients"]
        lt_bond["Bond Coefficients"]
        lt_angle["Angle Coefficients"]
        lt_dihedral["Dihedral Coefficients"]
        lt_improper["Improper Coefficients"]
        lt_init["Init Settings"]
    end
    
    a_mass --> extract
    a_bond --> extract
    a_angle --> extract
    a_dihedral --> extract
    a_improper --> extract
    a_pair --> extract
    
    extract --> convert
    convert --> assemble
    
    assemble --> lt_mass
    assemble --> lt_pair
    assemble --> lt_bond
    assemble --> lt_angle
    assemble --> lt_dihedral
    assemble --> lt_improper
    assemble --> lt_init
    
    classDef box fill:none,stroke:#333,stroke-width:1px
    class "AMBER File Structure" box
    class "Conversion Process" box
    class "Moltemplate LT File" box
```

Sources: [moltemplate/amber2lt.py:699-762](), [moltemplate/amber2lt.py:767-793]()

### Understanding the Conversion Process

The `amber2lt.py` script performs several key tasks during conversion:

1. **Section Extraction**: Identifies and extracts different sections from the AMBER file
2. **Parameter Formatting**: Converts AMBER parameter formats to LAMMPS-compatible formats
3. **Order Arrangement**: Sorts interactions with wildcards to ensure proper precedence
4. **File Generation**: Creates a structured LT file with all necessary components

The script handles specific AMBER conventions like wildcard atoms (`X`) and converts them to the proper syntax for moltemplate.

Sources: [moltemplate/amber2lt.py:105-185](), [moltemplate/amber2lt.py:189-227]()

## Generated Force Field Format

When `amber2lt.py` converts an AMBER force field file, it creates a structured LT file that defines the force field's parameters. This file includes several key sections:

### Atom Type Definitions

The generated file begins with comments describing the atom types defined in the force field, which helps users understand what atom types to assign to their molecules.

For example, from GAFF:

```
  #  @atom:c  Sp2 C carbonyl group
  #  @atom:c1  Sp C
  #  @atom:c2  Sp2 C
  #  @atom:c3  Sp3 C
  #  @atom:ca  Sp2 C in pure aromatic systems
```

### Mass Definitions

The `Data Masses` section defines the mass for each atom type:

```
  write_once("Data Masses") {
    @atom:c 12.01
    @atom:c1 12.01
    @atom:c2 12.01
    @atom:c3 12.01
    @atom:ca 12.01
    ...
  }
```

### Interaction Parameters

The file includes sections for all interaction parameters, such as pair coefficients:

```
  write_once("In Settings") {
    pair_coeff @atom:c @atom:c lj/charmm/coul/long 0.0860 3.3996695084235347
    pair_coeff @atom:c1 @atom:c1 lj/charmm/coul/long 0.2100 3.3996695084235347
    ...
  }
```

And similar sections for bonds, angles, dihedrals, and impropers:

```
  write_once("In Settings") {
    bond_coeff @bond:c-c harmonic 291.7 1.5482
    ...
  }
  
  write_once("Data Bonds By Type") {
    @bond:c-c @atom:c @atom:c
    ...
  }
```

### Initialization Settings

The file ends with initialization settings that define the overall simulation parameters:

```
  write_once("In Init") {
    # Default styles and settings for AMBER based force-fields:
    units           real
    atom_style      full
    bond_style      hybrid harmonic
    angle_style     hybrid harmonic
    dihedral_style  hybrid fourier
    improper_style  hybrid cvff
    pair_style      hybrid lj/charmm/coul/long 9.0 10.0 10.0
    kspace_style    pppm 0.0001
    
    pair_modify     mix arithmetic
    special_bonds   amber
  }
```

Sources: [moltemplate/force_fields/gaff.lt:58-155](), [moltemplate/force_fields/gaff.lt:157-226](), [moltemplate/force_fields/gaff.lt:228-311](), [moltemplate/amber2lt.py:722-743]()

## Using Converted Force Fields

After converting an AMBER force field to moltemplate format, you can use it in your molecular simulations. Here's how:

### Importing Force Fields

To use a converted force field in your moltemplate files, you simply import it at the beginning of your molecule definition:

```
import "gaff.lt"

Benzene inherits GAFF {
  # molecule definition here
}
```

### Inheriting Force Field Parameters

When defining a molecule, you use the `inherits` keyword to apply the force field parameters to your molecule:

```
Benzene inherits GAFF {
  write('Data Atoms') {
    $atom:c1  $mol  @atom:ca  -0.115   -0.739   1.189  -0.00733
    $atom:c2  $mol  @atom:ca  -0.115    0.614   1.208   0.35167
    # more atoms...
  }
  
  write("Data Bond List") {
    $bond:b1 $atom:c1 $atom:c2
    # more bonds...
  }
}
```

The `@atom:ca` syntax in the atom definition references the GAFF atom type for aromatic carbon, which brings in all associated parameters from the force field.

Sources: [moltemplate/force_fields/gaff.lt:13-25](), [doc/doc_amber2lt.md:32-46]()

## Integration with MOL2 Files and AmberTools

A common workflow involves:
1. Using AmberTools to prepare MOL2 files with proper atom typing and charges
2. Converting AMBER force field files to LT format with `amber2lt.py`
3. Converting MOL2 files to LT format with `mol22lt.py`
4. Using these files together in moltemplate

This workflow is illustrated below:

```mermaid
flowchart TB
    subgraph "AmberTools"
        antechamber["antechamber"]
        parmchk["parmchk2"]
    end
    
    subgraph "Input Files"
        mol["Initial Structure"]
        gaff_dat["gaff.dat"]
    end
    
    subgraph "Intermediate Files"
        mol2["Molecule.mol2"]
        frcmod["Molecule.frcmod"]
    end
    
    subgraph "Conversion Tools"
        amber2lt["amber2lt.py"]
        mol22lt["mol22lt.py"]
    end
    
    subgraph "Output Files"
        ff_lt["force_field.lt"]
        mol_lt["molecule.lt"]
    end
    
    subgraph "Moltemplate"
        run["moltemplate.sh"]
        lammps["LAMMPS Input Files"]
    end
    
    mol --> antechamber
    antechamber --> mol2
    mol2 --> parmchk
    parmchk --> frcmod
    
    gaff_dat --> amber2lt
    frcmod --> amber2lt
    amber2lt --> ff_lt
    
    mol2 --> mol22lt
    ff_lt --> mol22lt
    mol22lt --> mol_lt
    
    ff_lt --> run
    mol_lt --> run
    run --> lammps
    
    classDef box fill:none,stroke:#333,stroke-width:1px
    class "AmberTools" box
    class "Input Files" box
    class "Intermediate Files" box
    class "Conversion Tools" box
    class "Output Files" box
    class "Moltemplate" box
```

Sources: [doc/doc_amber2lt.md:50-85](), [moltemplate/force_fields/gaff.lt:26-52]()

## Advanced Uses and Considerations

### Handling Multiple Molecules

When working with multiple molecules that require the same force field:

1. Convert the AMBER force field once to create your base `.lt` file
2. For each molecule, use `mol22lt.py` to convert its MOL2 file to LT format
3. Import the same force field file in each molecule's LT file

This approach ensures consistent force field parameters across all your molecules.

### Dealing with Custom Parameters

If you have custom or modified parameters in a FRCMOD file:

1. Convert your base force field (e.g., GAFF) to LT format
2. Convert your FRCMOD file to LT format
3. Import both files in your molecule definition, with the custom parameters imported last to override the base parameters

### Handling Wildcard Atoms

AMBER force fields often use wildcard atoms (`X`) to represent any atom type in interaction parameters. The `amber2lt.py` script handles these wildcards by:

1. Converting them to the `*` wildcard syntax in moltemplate
2. Sorting interaction parameters so that more specific interactions (without wildcards) take precedence over generic ones (with wildcards)

```
# AMBER format:
X -CA-CA-X    4   14.50        180.0             2.         intrpol.bsd.on C6H6

# Converted to moltemplate format:
dihedral_coeff @dihedral:X-CA-CA-X fourier 1 14.50 180.0 2.0     # intrpol.bsd.on C6H6
```

Sources: [moltemplate/amber2lt.py:512-524](), [doc/doc_amber2lt.md:117-141]()

## Troubleshooting Common Issues

### Section Extraction Failures

Sometimes `amber2lt.py` may fail to correctly identify sections in AMBER files. If this occurs, you can manually extract sections and provide them as separate inputs:

```
amber2lt.py --name FORCE_FIELD_NAME \
           --mass mass.txt \
           --bond bond.txt \
           --angle angle.txt \
           --dihedral dihedral.txt \
           --improper improper.txt \
           --pair pair.txt \
           --out FORCE_FIELD.lt
```

### Conversion Parameter Issues

AMBER uses different conventions for Lennard-Jones parameters than LAMMPS. The `amber2lt.py` script accounts for these differences by:

1. Converting AMBER's atom radii (which is 0.5*sigma) to full sigma values for LAMMPS
2. Adjusting the parameters to account for different energy function forms

If you encounter issues with converted parameters, check the conversion logic in the `ConvertPair2Lt` function.

Sources: [moltemplate/amber2lt.py:633-691](), [doc/doc_amber2lt.md:129-141]()

## Using the Python API

You can also use `amber2lt.py` as a Python module to perform conversions programmatically:

```python
import moltemplate
# Open the file you want to convert
with open('gaff.dat', 'r') as file_in:
    lines_in = file_in.readlines()
# Now create a new moltemplate file
lines_out = ConvertAmber2Lt(object_name, lines_in)
# Write the contents of the new file
with open('gaff.lt', 'w') as file_out:
    file_out.write(''.join(output_lines))
```

For more granular control, you can also use `ConvertAmberSections2Lt()` if you have already extracted the different sections of the file.

Sources: [doc/doc_amber2lt.md:143-168]()

## Conclusion

The `amber2lt.py` tool provides a streamlined way to convert AMBER force field files to moltemplate format, enabling seamless integration of AMBER-based workflows with LAMMPS simulations prepared through moltemplate. This conversion preserves all the force field parameters while reformatting them to be compatible with moltemplate's syntax and LAMMPS' requirements.

---