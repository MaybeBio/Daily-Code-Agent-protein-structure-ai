# Examples and Tutorials

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [examples/README.md](examples/README.md)
- [examples/all_atom/force_field_OPLSAA/README.md](examples/all_atom/force_field_OPLSAA/README.md)
- [examples/all_atom/force_field_OPLSAA/alkane_chain_single/README.md](examples/all_atom/force_field_OPLSAA/alkane_chain_single/README.md)
- [examples/all_atom/force_field_OPLSAA/butane/README.md](examples/all_atom/force_field_OPLSAA/butane/README.md)
- [examples/all_atom/force_field_OPLSAA/ethylene+benzene/README.md](examples/all_atom/force_field_OPLSAA/ethylene+benzene/README.md)
- [examples/all_atom/force_field_OPLSAA/ethylene+benzene_PACKMOL/README.md](examples/all_atom/force_field_OPLSAA/ethylene+benzene_PACKMOL/README.md)
- [examples/all_atom/force_field_OPLSAA/functionalized_nanotubes_NH2/README.md](examples/all_atom/force_field_OPLSAA/functionalized_nanotubes_NH2/README.md)
- [examples/all_atom/force_field_OPLSAA/hexadecane/README.md](examples/all_atom/force_field_OPLSAA/hexadecane/README.md)
- [examples/all_atom/force_field_OPLSAA/star_polymer/README.md](examples/all_atom/force_field_OPLSAA/star_polymer/README.md)
- [examples/all_atom/force_field_OPLSAA/waterSPCE+methane/README.md](examples/all_atom/force_field_OPLSAA/waterSPCE+methane/README.md)
- [examples/all_atom/force_field_OPLSAA/waterTIP5P+ethanol/README.md](examples/all_atom/force_field_OPLSAA/waterTIP5P+ethanol/README.md)
- [examples/coarse_grained/DNA_models/dsDNA_only/2strands/3bp_2particles/README.md](examples/coarse_grained/DNA_models/dsDNA_only/2strands/3bp_2particles/README.md)
- [examples/coarse_grained/DNA_models/dsDNA_only/2strands/3bp_2particles/confined_viral_DNA/README.md](examples/coarse_grained/DNA_models/dsDNA_only/2strands/3bp_2particles/confined_viral_DNA/README.md)
- [examples/coarse_grained/DNA_models/dsDNA_only/2strands/3bp_2particles/confined_viral_DNA/images/plus.svg](examples/coarse_grained/DNA_models/dsDNA_only/2strands/3bp_2particles/confined_viral_DNA/images/plus.svg)
- [examples/coarse_grained/DNA_models/dsDNA_only/2strands/3bp_2particles/confined_viral_DNA/images/rightarrow.svg](examples/coarse_grained/DNA_models/dsDNA_only/2strands/3bp_2particles/confined_viral_DNA/images/rightarrow.svg)
- [examples/coarse_grained/DNA_models/dsDNA_only/2strands/3bp_2particles/images/twist_motor_3bp2p_LLR.jpg](examples/coarse_grained/DNA_models/dsDNA_only/2strands/3bp_2particles/images/twist_motor_3bp2p_LLR.jpg)
- [examples/coarse_grained/DNA_models/dsDNA_only/2strands/3bp_2particles/simple_dna_example/README.md](examples/coarse_grained/DNA_models/dsDNA_only/2strands/3bp_2particles/simple_dna_example/README.md)
- [examples/coarse_grained/DNA_models/dsDNA_only/2strands/3bp_2particles/twist_motor_supercoiling/README.md](examples/coarse_grained/DNA_models/dsDNA_only/2strands/3bp_2particles/twist_motor_supercoiling/README.md)
- [examples/coarse_grained/DNA_models/dsDNA_only/twistable_Kratky-Porod/42bp_3particles/nucleoid_Ccrescentus_DNA_only/README.md](examples/coarse_grained/DNA_models/dsDNA_only/twistable_Kratky-Porod/42bp_3particles/nucleoid_Ccrescentus_DNA_only/README.md)
- [examples/coarse_grained/DNA_models/dsDNA_only/twistable_Kratky-Porod/42bp_3particles/twist_motor_supercoiling/README.md](examples/coarse_grained/DNA_models/dsDNA_only/twistable_Kratky-Porod/42bp_3particles/twist_motor_supercoiling/README.md)
- [examples/coarse_grained/DNA_models/dsDNA_only/twistable_Kratky-Porod/images/DNA_models_similar_to_Benedetti++Stasiak_NAR2014.jpg](examples/coarse_grained/DNA_models/dsDNA_only/twistable_Kratky-Porod/images/DNA_models_similar_to_Benedetti++Stasiak_NAR2014.jpg)
- [examples/coarse_grained/DNA_models/dsDNA_only/twistable_Kratky-Porod/images/twist_motor_LLR.jpg](examples/coarse_grained/DNA_models/dsDNA_only/twistable_Kratky-Porod/images/twist_motor_LLR.jpg)
- [examples/coarse_grained/simple_examples/polymer_translocation/README.md](examples/coarse_grained/simple_examples/polymer_translocation/README.md)
- [examples/coarse_grained/solvent_models/ELBAwater+methanol/README.md](examples/coarse_grained/solvent_models/ELBAwater+methanol/README.md)
- [examples/coarse_grained/solvent_models/manybodywaterMW+hydrocarbonsTraPPE/README.md](examples/coarse_grained/solvent_models/manybodywaterMW+hydrocarbonsTraPPE/README.md)

</details>



This page provides an overview of the examples and tutorials included in the moltemplate repository. These examples demonstrate how to use moltemplate to prepare a wide variety of molecular systems for simulation with LAMMPS. From simple molecules to complex biological structures, these examples serve as both reference implementations and starting points for your own simulations.

For information about specific force fields, see [Force Fields](#5).

## Example Directory Structure

Each example directory in the moltemplate repository follows a consistent structure designed to guide you through the process of building and running molecular simulations.

```mermaid
flowchart LR
    subgraph "Example Directory Structure"
        images["images/"]
        moltemplate_files["moltemplate_files/"]
        readme_setup["README_setup.sh"]
        readme_run["README_run.sh"]
        readme_viz["README_visualize.txt"]
        lammps_scripts["LAMMPS input scripts
        (run.in.*)"]
    end
    
    moltemplate_files --> readme_setup
    readme_setup --> lammps_scripts
    lammps_scripts --> readme_run
    readme_run --> readme_viz
    
    class moltemplate_files,lammps_scripts,readme_setup,readme_run,readme_viz,images "node"
```

| Directory/File | Purpose |
|----------------|---------|
| `images/` | Contains visual representations of the molecules in the system |
| `moltemplate_files/` | Contains LT files and other auxiliary files needed by moltemplate |
| `README_setup.sh` | Instructions for using moltemplate to create LAMMPS input files |
| `README_run.sh` | Instructions for running LAMMPS with the generated files |
| `README_visualize.txt` | Instructions for viewing DATA/DUMP files in VMD |
| `run.in.*` | LAMMPS input scripts for different simulation phases (minimization, equilibration, etc.) |

Sources: [examples/README.md]()

## Two-Step Example Workflow

Running examples in moltemplate follows a consistent two-step process:

```mermaid
flowchart LR
    subgraph "Step 1: System Setup"
        lt_files["LT Files
        (molecule definitions)"]
        moltemplate["moltemplate.sh"]
        lammps_data["LAMMPS Data Files
        system.data"]
        lammps_settings["LAMMPS Settings
        system.in.*"]
    end
    
    subgraph "Step 2: Simulation Run"
        lammps["LAMMPS Simulator"]
        results["Simulation Results
        (trajectory, measurements)"]
    end
    
    lt_files --> moltemplate
    moltemplate --> lammps_data
    moltemplate --> lammps_settings
    lammps_data --> lammps
    lammps_settings --> lammps
    lammps --> results
    
    class lt_files,moltemplate,lammps_data,lammps_settings,lammps,results "node"
```

1. **System Setup**: Use moltemplate to convert LT files to LAMMPS input files
   ```bash
   moltemplate.sh system.lt
   ```

2. **Simulation Run**: Run LAMMPS with the generated files
   ```bash
   lmp_mpi -i run.in.min    # Initial minimization
   lmp_mpi -i run.in.nvt    # Constant volume simulation
   lmp_mpi -i run.in.npt    # Constant pressure simulation
   ```

Sources: [examples/README.md]()

## All-Atom Simulation Examples

Moltemplate includes numerous examples of all-atom simulations using various force fields. These examples demonstrate how to model small molecules, polymers, and complex systems at the atomic level.

### OPLSAA Force Field Examples

The OPLSAA force field is commonly used for all-atom simulations of organic molecules. Moltemplate provides a comprehensive implementation of this force field with examples ranging from simple alkanes to complex polymers.

```mermaid
flowchart TD
    subgraph "OPLSAA Examples"
        butane["Butane"]
        alkane_chain["Alkane Chain"]
        star_polymer["Star Polymer"]
        benzene["Benzene+Ethylene"]
        functionalized["Functionalized Nanotubes"]
    end
    
    subgraph "Water Models"
        spce["SPC/E Water"]
        tip3p["TIP3P"]
        tip5p["TIP5P"]
    end
    
    subgraph "Mixtures"
        water_methane["Water+Methane"]
        water_ethanol["Water+Ethanol"]
    end
    
    OPLSAA --> butane
    OPLSAA --> alkane_chain
    OPLSAA --> star_polymer
    OPLSAA --> benzene
    OPLSAA --> functionalized
    
    Water --> spce
    Water --> tip3p
    Water --> tip5p
    
    spce --> water_methane
    tip5p --> water_ethanol
    OPLSAA --> water_methane
    OPLSAA --> water_ethanol
    
    class OPLSAA,Water,butane,alkane_chain,star_polymer,benzene,functionalized,spce,tip3p,tip5p,water_methane,water_ethanol "node"
```

#### Key OPLSAA Examples:

1. **Butane**: Simple example of short alkane chains in a box at atmospheric pressure
   - Location: `examples/all_atom/force_field_OPLSAA/butane/`
   - Features: Demonstrates basic molecule construction and simulation

2. **Alkane Chains**: Long hydrocarbon chains with realistic physical properties
   - Location: `examples/all_atom/force_field_OPLSAA/alkane_chain_single/`
   - Features: Uses LOPLSAA variant for improved alkane modeling

3. **Hexadecane**: Multiple long alkane chains in a box near the boiling point
   - Location: `examples/all_atom/force_field_OPLSAA/hexadecane/`
   - Features: Demonstrates phase behavior of alkanes

4. **Star Polymer**: Complex polymer structure with multiple chains attached to a central particle
   - Location: `examples/all_atom/force_field_OPLSAA/star_polymer/`
   - Features: Shows hierarchical molecule construction

5. **Functionalized Nanotubes**: Carbon nanotubes with attached amine groups
   - Location: `examples/all_atom/force_field_OPLSAA/functionalized_nanotubes_NH2/`
   - Features: Demonstrates the "new random" command for random placement of functional groups

Sources: [examples/all_atom/force_field_OPLSAA/README.md](), [examples/all_atom/force_field_OPLSAA/butane/README.md](), [examples/all_atom/force_field_OPLSAA/alkane_chain_single/README.md](), [examples/all_atom/force_field_OPLSAA/hexadecane/README.md](), [examples/all_atom/force_field_OPLSAA/star_polymer/README.md](), [examples/all_atom/force_field_OPLSAA/functionalized_nanotubes_NH2/README.md]()

### Customizing Atomic Charges in OPLSAA

In the OPLSAA force field, atomic charges are determined by atom types according to a lookup table in the `oplsaa2024.lt` file. Moltemplate provides several ways to customize these charges:

1. **Specify charges in DATA file**: Edit the charges in the "Data Atoms" section of your LT file and prevent LAMMPS from overriding them by removing the `include system.in.charges` line from your LAMMPS input script.

2. **Override specific atom charges**: Add an "In Charges" section to your LT file with custom charges for specific atoms, as demonstrated in the functionalized nanotubes example:

```
write("In Charges") {
  set atom $atom:c1 charge -0.115
}
```

3. **Mix OPLSAA and non-OPLSAA molecules**: For molecules that don't use OPLSAA, specify charges directly in the "Data Atoms" section of their LT files.

Sources: [examples/all_atom/force_field_OPLSAA/README.md](), [examples/all_atom/force_field_OPLSAA/functionalized_nanotubes_NH2/README.md](), [examples/all_atom/force_field_OPLSAA/waterSPCE+methane/README.md]()

### Water Models

Moltemplate includes examples of various water models for use in simulations:

1. **SPC/E Water**: Simple point charge model with fixed geometry
   - Location: `examples/all_atom/force_field_OPLSAA/waterSPCE+methane/`
   - Features: Simple, computationally efficient water model

2. **TIP3P**: Three-site model commonly used with OPLSAA
   - Location: Various examples in the OPLSAA directory

3. **TIP5P**: Five-site model with improved water properties
   - Location: `examples/all_atom/force_field_OPLSAA/waterTIP5P+ethanol/`
   - Features: Better representation of water structure and thermodynamic properties

Sources: [examples/all_atom/force_field_OPLSAA/waterSPCE+methane/README.md](), [examples/all_atom/force_field_OPLSAA/waterTIP5P+ethanol/README.md]()

## Coarse-Grained Simulation Examples

Coarse-grained models represent groups of atoms as single interaction sites, allowing simulation of larger systems and longer timescales. Moltemplate includes various coarse-grained examples, with a particular focus on DNA models.

### DNA Models

Moltemplate provides sophisticated coarse-grained DNA models with realistic mechanical properties.

```mermaid
flowchart TD
    subgraph "DNA Models"
        direction TB
        bp3p2["3bp2p Model
        (3 base pairs = 2 particles)"]
        bp42p3["42bp3p Model
        (42 base pairs = 3 particles)"]
    end
    
    subgraph "3bp2p Applications"
        simple_dna["Simple DNA Example"]
        confined_dna["Confined Viral DNA"]
        twist_motor_3bp["Twist Motor (3bp2p)"]
    end
    
    subgraph "42bp3p Applications"
        nucleoid["Bacterial Nucleoid"]
        twist_motor_42bp["Twist Motor (42bp3p)"]
    end
    
    bp3p2 --> simple_dna
    bp3p2 --> confined_dna
    bp3p2 --> twist_motor_3bp
    
    bp42p3 --> nucleoid
    bp42p3 --> twist_motor_42bp
    
    class bp3p2,bp42p3,simple_dna,confined_dna,twist_motor_3bp,nucleoid,twist_motor_42bp "node"
```

#### 3bp2p DNA Model

The "3bp2p" model represents 3 base pairs with 2 particles and has a double-helical structure with major and minor grooves.

**Key Features:**
- Persistence length: 48.71 nm (experimental: 46-48 nm)
- Torsional persistence length: 109.98 nm (experimental: 100-110 nm)
- Helical twist angle per base pair: 34.26° (experimental: 34.3°)
- Distance along axis per base pair: 0.328 nm (experimental: 0.332 nm)

**Examples:**
1. **Simple DNA**: Basic demonstration of the model
   - Location: `examples/coarse_grained/DNA_models/dsDNA_only/2strands/3bp_2particles/simple_dna_example/`

2. **Confined Viral DNA**: DNA polymer confined within a viral capsid
   - Location: `examples/coarse_grained/DNA_models/dsDNA_only/2strands/3bp_2particles/confined_viral_DNA/`
   - Features: Uses `ndmansfield` to generate a random curve, `interpolate_curve.py` to smooth it, and `genpoly_lt.py` to create a polymer along the curve

3. **Twist Motor**: DNA with applied torsional torque
   - Location: `examples/coarse_grained/DNA_models/dsDNA_only/2strands/3bp_2particles/twist_motor_supercoiling/`
   - Features: Demonstrates supercoiling through applied torque

Sources: [examples/coarse_grained/DNA_models/dsDNA_only/2strands/3bp_2particles/README.md](), [examples/coarse_grained/DNA_models/dsDNA_only/2strands/3bp_2particles/simple_dna_example/README.md](), [examples/coarse_grained/DNA_models/dsDNA_only/2strands/3bp_2particles/confined_viral_DNA/README.md](), [examples/coarse_grained/DNA_models/dsDNA_only/2strands/3bp_2particles/twist_motor_supercoiling/README.md]()

#### 42bp3p DNA Model

The "42bp3p" model represents 42 base pairs with 3 particles and is suitable for very large-scale simulations.

**Examples:**
1. **Bacterial Nucleoid**: Simulation of an entire bacterial chromosome (4Mbp)
   - Location: `examples/coarse_grained/DNA_models/dsDNA_only/twistable_Kratky-Porod/42bp_3particles/nucleoid_Ccrescentus_DNA_only/`
   - Features: Demonstrates DNA relaxation and supercoiling during replication

2. **Twist Motor**: Similar to the 3bp2p version but with the coarser 42bp3p model
   - Location: `examples/coarse_grained/DNA_models/dsDNA_only/twistable_Kratky-Porod/42bp_3particles/twist_motor_supercoiling/`

Sources: [examples/coarse_grained/DNA_models/dsDNA_only/twistable_Kratky-Porod/42bp_3particles/nucleoid_Ccrescentus_DNA_only/README.md](), [examples/coarse_grained/DNA_models/dsDNA_only/twistable_Kratky-Porod/42bp_3particles/twist_motor_supercoiling/README.md]()

### Other Coarse-Grained Examples

In addition to DNA models, moltemplate includes examples of other coarse-grained systems:

1. **Polymer Translocation**: Demonstration of a polymer passing through a hole in a wall
   - Location: `examples/coarse_grained/simple_examples/polymer_translocation/`

2. **Many-Body Water with Hydrocarbons**: Mixing of the MW water model with TraPPE hydrocarbons
   - Location: `examples/coarse_grained/solvent_models/manybodywaterMW+hydrocarbonsTraPPE/`
   - Features: Shows how to combine different force fields with radically different pair styles

3. **ELBA Water with All-Atom Solute**: Coarse-grained water with an all-atom methanol molecule
   - Location: `examples/coarse_grained/solvent_models/ELBAwater+methanol/`
   - Features: Demonstrates mixing different levels of detail in the same simulation

Sources: [examples/coarse_grained/simple_examples/polymer_translocation/README.md](), [examples/coarse_grained/solvent_models/manybodywaterMW+hydrocarbonsTraPPE/README.md](), [examples/coarse_grained/solvent_models/ELBAwater+methanol/README.md]()

## Polymer Generation Tools and Workflows

Moltemplate includes powerful tools for generating complex polymer structures. The following workflow shows how to create a polymer that follows a specified curve:

```mermaid
flowchart LR
    subgraph "Polymer Generation Workflow"
        curve_gen["Generate Curve
        (ndmansfield or manual)"]
        interpolate["Smooth Curve
        (interpolate_curve.py)"]
        genpoly["Generate Polymer
        (genpoly_lt.py)"]
        moltemplate["Create LAMMPS Files
        (moltemplate.sh)"]
        lammps["Run Simulation
        (LAMMPS)"]
    end
    
    curve_gen --> interpolate
    interpolate --> genpoly
    genpoly --> moltemplate
    moltemplate --> lammps
    
    class curve_gen,interpolate,genpoly,moltemplate,lammps "node"
```

### Key Tools:

1. **ndmansfield**: Generates random self-avoiding curves
   - Usage: `./ndmansfield -box $Nx $Ny $Nz -seed 0 -tstart 1 -tsave 1000000 -tstop 1000000 > curve_lattice.txt`

2. **interpolate_curve.py**: Smooths and rescales coordinates
   - Usage: `interpolate_curve.py $NMONOMERS $SCALE < curve_lattice.txt > curve_smooth.txt`

3. **genpoly_lt.py**: Creates a moltemplate file for a polymer along a curve
   - Usage:
   ```bash
   genpoly_lt.py -helix 102.7797 \
                 -polymer-name 'DNAPolymer' \
                 -monomer-name 'DNAMonomer' \
                 -inherits 'DNAForceField' \
                 -header 'import "dna_monomer.lt"' \
                 -bond Backbone a a \
                 -bond Backbone b b \
                 -dihedral MajorGroove b b a a 0 1 1 2 \
                 -dihedral Torsion a a b b 1 0 0 1 \
                 -padding 20,20,20 \
                 < curve_smooth.txt > dna_polymer.lt
   ```

The confined viral DNA example demonstrates this complete workflow, showing how to create a DNA polymer confined within an arbitrary shape.

Sources: [examples/coarse_grained/DNA_models/dsDNA_only/2strands/3bp_2particles/confined_viral_DNA/README.md]()

## Package Requirements for Examples

Many examples require specific LAMMPS packages to be enabled. Here's a summary of common requirements:

| Example Type | Required LAMMPS Packages |
|--------------|--------------------------|
| DNA Models | MOLECULE, EXTRA-MOLECULE |
| Twist Motors | MOLECULE, EXTRA-PAIR, USER-MISC (fix_twist) |
| Rigid Bodies | RIGID |
| Many-Body Water | MANYBODY |
| ELBA Water | DIPOLE |
| Functionalized Nanotubes | MOLECULE, RIGID |

To enable these packages, follow the instructions at the [LAMMPS Build Package documentation](https://docs.lammps.org/Build_package.html).

Sources: [examples/coarse_grained/DNA_models/dsDNA_only/2strands/3bp_2particles/simple_dna_example/README.md](), [examples/coarse_grained/DNA_models/dsDNA_only/twistable_Kratky-Porod/42bp_3particles/twist_motor_supercoiling/README.md](), [examples/coarse_grained/simple_examples/polymer_translocation/README.md](), [examples/coarse_grained/solvent_models/manybodywaterMW+hydrocarbonsTraPPE/README.md](), [examples/coarse_grained/solvent_models/ELBAwater+methanol/README.md](), [examples/all_atom/force_field_OPLSAA/functionalized_nanotubes_NH2/README.md]()

## Example-Driven Learning Path

For users new to moltemplate, we recommend following this learning path through the examples:

1. **Start with Butane**: Simple example demonstrating basic moltemplate concepts
   - Location: `examples/all_atom/force_field_OPLSAA/butane/`

2. **Move to Alkane Chains**: Learn how to build polymers from subunits
   - Location: `examples/all_atom/force_field_OPLSAA/alkane_chain_single/`

3. **Explore Water Models**: Understand how to work with different force fields
   - Location: `examples/all_atom/force_field_OPLSAA/waterSPCE+methane/`

4. **Try Coarse-Grained Models**: Simplify complex systems for larger simulations
   - Location: `examples/coarse_grained/DNA_models/dsDNA_only/2strands/3bp_2particles/simple_dna_example/`

5. **Advanced Techniques**: Experiment with complex geometries and specialized features
   - Location: `examples/coarse_grained/DNA_models/dsDNA_only/2strands/3bp_2particles/confined_viral_DNA/`

This progression builds from simple to complex, introducing new concepts at each step.

Sources: [examples/all_atom/force_field_OPLSAA/alkane_chain_single/README.md](), [examples/all_atom/force_field_OPLSAA/hexadecane/README.md]()

## Advanced Topics and Customization

### Customizing Bonds, Angles, and Dihedrals

The OPLSAA force field contains many alternative parameter choices for interactions. Moltemplate attempts to make reasonable guesses, but you can override these:

1. Run moltemplate with the `-report-duplicates bytype __` flag to detect ambiguous interactions
2. Look for warning files like `warning_duplicate_dihedrals.txt`
3. Add custom interaction specifications to your LT files

Example for customizing a dihedral:
```
write("Data Dihedrals") {
  $dihedral:d1 @dihedral:OPLSAA/c3-c4-c4-c3 $atom:c1 $atom:c2 $atom:c3 $atom:c4
}
```

Sources: [examples/all_atom/force_field_OPLSAA/README.md]()

### Using PACKMOL with Moltemplate

For complex mixtures, PACKMOL can be used to generate initial coordinates:

1. Create individual molecule LT files
2. Use PACKMOL to arrange molecules and generate a PDB or XYZ file
3. Import these coordinates into moltemplate

The ethylene+benzene example demonstrates this workflow:
- Location: `examples/all_atom/force_field_OPLSAA/ethylene+benzene_PACKMOL/`

Sources: [examples/all_atom/force_field_OPLSAA/ethylene+benzene_PACKMOL/README.md]()

### Working with Rigid Bodies

Several examples demonstrate how to use rigid bodies in moltemplate:

1. **Functionalized Nanotubes**: Carbon nanotubes with rigid carbon atoms
   - Location: `examples/all_atom/force_field_OPLSAA/functionalized_nanotubes_NH2/`

2. **TIP5P Water**: Rigid water molecules with OPLSAA ethanol
   - Location: `examples/all_atom/force_field_OPLSAA/waterTIP5P+ethanol/`
   - Features: Uses "fix rigid" or "fix rigid/nph/small" for rigid body dynamics

Sources: [examples/all_atom/force_field_OPLSAA/functionalized_nanotubes_NH2/README.md](), [examples/all_atom/force_field_OPLSAA/waterTIP5P+ethanol/README.md]()

## Conclusion

The examples and tutorials provided with moltemplate cover a wide range of molecular systems and simulation techniques. By exploring these examples, users can learn how to effectively use moltemplate to prepare complex molecular simulations for LAMMPS.

Remember that these examples are intended to be modified and adapted to your specific needs. The modular nature of moltemplate makes it easy to combine elements from different examples to create new molecular systems.

For more information on force fields, see [Force Fields](#5), and for details on specific conversion tools, see [File Format Converters](#4).

---