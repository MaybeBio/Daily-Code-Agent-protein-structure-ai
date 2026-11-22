

Welcome to MDAnalysis! This tutorial will guide you through the fundamental steps of analyzing molecular dynamics simulations using MDAnalysis. By the end of this tutorial, you'll be able to load molecular systems, select specific atoms, perform basic calculations, and run simple analyses on your trajectory data.

## What is MDAnalysis?

MDAnalysis is a powerful Python library designed for analyzing molecular dynamics simulations. Whether you're studying protein folding, ligand binding, or material properties, MDAnalysis provides the tools to extract meaningful insights from your simulation data. The library works with many popular simulation packages including GROMACS, Amber, NAMD, CHARMM, and LAMMPS.

**Key concepts you'll learn:**
- The **Universe**: Your central object containing all simulation data
- **Atom selections**: Powerfully select specific parts of your system
- **Basic calculations**: Compute geometric properties and distances
- **Simple analyses**: Run basic trajectory analyses like RMSD

## Getting Started with Your First Universe

The **Universe** is the heart of MDAnalysis - it's the central object that contains all the information about your molecular system, including both the topology (which atoms exist and how they're connected) and the trajectory (how atoms move over time).

Let's start by loading a molecular system. MDAnalysis comes with example data files you can use to experiment:

```python
import MDAnalysis as mda
from MDAnalysis.tests.datafiles import PSF, DCD

# Create a Universe from topology and trajectory files
u = mda.Universe(PSF, DCD)

print(f"Loaded system with {len(u.atoms)} atoms")
print(f"Trajectory contains {len(u.trajectory)} frames")
```

When you create a `Universe`, you need to provide at least a topology file (like PSF, PDB, or GRO) and optionally a trajectory file (like DCD, XTC, or TRR). The topology defines the molecular structure, while the trajectory contains the atomic positions over time.

Sources: [package/MDAnalysis/__init__.py#L84](package/MDAnalysis/__init__.py#L84), [package/MDAnalysis/core/universe.py#L33](package/MDAnalysis/core/universe.py#L33), [testsuite/MDAnalysisTests/datafiles.py#L40](testsuite/MDAnalysisTests/datafiles.py#L40)

cgx_tip>
If you don't have your own simulation files yet, you can use the built-in test data as shown above. These files are included with MDAnalysis and are perfect for learning!
</CgxTip>

## Exploring Your Molecular System

Once you have a Universe, you'll want to explore its contents. The Universe object contains all the atoms in your system, organized hierarchically into segments, residues, and atoms.

```python
# Basic information about your system
print(f"Number of atoms: {len(u.atoms)}")
print(f"Number of residues: {len(u.residues)}")
print(f"Number of segments: {len(u.segments)}")

# Access the first atom
first_atom = u.atoms[0]
print(f"First atom name: {first_atom.name}")
print(f"First atom residue: {first_atom.resname}")
print(f"First atom position: {first_atom.position}")

# Get all atom positions as a NumPy array
positions = u.atoms.positions
print(f"Shape of positions array: {positions.shape}")
```

The atomic positions are stored as NumPy arrays, which means you can easily perform mathematical operations on them. This is one of the key strengths of MDAnalysis - it leverages NumPy's powerful array operations for efficient computation.

Sources: [package/MDAnalysis/core/groups.py#L29](package/MDAnalysis/core/groups.py#L29), [README.rst#L47](README.rst#L47)

## Making Atom Selections

One of the most powerful features of MDAnalysis is its **atom selection language**. You can select specific atoms based on various criteria like atom name, residue type, position, or more complex conditions.

```python
# Select all C-alpha atoms
ca_atoms = u.select_atoms('name CA')
print(f"Number of C-alpha atoms: {len(ca_atoms)}")

# select all atoms in protein backbone
backbone = u.select_atoms('protein and (name CA or name N or name C or name O)')
print(f"Number of backbone atoms: {len(backbone)}")

# Select atoms within 5 Å of the first residue
residue_1 = u.select_atoms('resid 1')
nearby_atoms = u.select_atoms('around 5 resid 1')
print(f"Atoms within 5 Å of residue 1: {len(nearby_atoms)}")

# Select water molecules (residue name starting with 'W')
water = u.select_atoms('resname W*')
print(f"Number of water molecules: {len(water.residues)}")
```

The selection language is very flexible and supports complex queries. You can combine conditions using `and`, `or`, and `not`, and use spatial operators like `around` to select atoms based on their proximity to other atoms.

```mermaid
flowchart TD
    A[Universe] --> B[select_atoms()]
    B --> C[Selection String]
    C --> D[Atom Properties<br>name, type, mass]
    C --> E[Residue Properties<br>resname, resid, resnum]
    C --> F[Spatial Properties<br>around, point, sphere]
    C --> G[Logical Operators<br>and, or, not]
    B --> H[AtomGroup]
```

Sources: [package/MDAnalysis/__init__.py#L88](package/MDAnalysis/__init__.py#L88), [README.rst#L45](README.rst#L45)

## Performing Basic Calculations

With your selected atoms, you can perform various geometric and physical calculations. Let's explore some common operations:

```python
# Calculate center of mass
com = ca_atoms.center_of_mass()
print(f"Center of mass of C-alpha atoms: {com}")

# Calculate radius of gyration
from MDAnalysis.analysis import rms
rg = rms.radius_of_gyration(ca_atoms)
print(f"Radius of gyration: {rg:.2f} Å")

# Calculate distances between atoms
atom1 = u.atoms[0]
atom2 = u.atoms[10]
distance = mda.lib.distances.distance(atom1.position, atom2.position)
print(f"Distance between atoms 0 and 10: {distance:.2f} Å")

# Calculate end-to-end distance for a chain
end_to_end = np.linalg.norm(ca_atoms[-1].position - ca_atoms[0].position)
print(f"End-to-end distance: {end_to_end:.2f} Å")
```

These calculations give you insights into the structure and geometry of your molecular system. For example, the radius of gyration tells you how compact your protein is, while distances between specific atoms can indicate conformational changes.

> [!TIP]
> All positions in MDAnalysis are stored inAngstroms (Å), which is the standard unit for molecular simulations. Make sure to keep track of units when comparing with experimental data!

Sources: [package/MDAnalysis/__init__.py#L94](package/MDAnalysis/__init__.py#L94), [package/MDAnalysis/analysis/rms.py#L37](package/MDAnalysis/analysis/rms.py#L37)

## Analyzing Trajectory Data

The real power of MDAnalysis comes from analyzing how your molecular system changes over time. Let's walk through the trajectory and compute some properties:

```python
import numpy as np

# Create arrays to store results
times = []
end_to_end_distances = []

# Loop through the trajectory
for ts in u.trajectory:
    # Get current time (in ps)
    current_time = u.trajectory.time
    times.append(current_time)
    
    # Calculate end-to-end distance for C-alpha atoms
    ee_dist = np.linalg.norm(ca_atoms[-1].position - ca_atoms[0].position)
    end_to_end_distances.append(ee_dist)
    
    # Print progress every 10 frames
    if ts.frame % 10 == 0:
        print(f"Frame {ts.frame}: time = {current_time:.1f} ps, EE = {ee_dist:.2f} Å")

# Convert to numpy arrays for easier manipulation
times = np.array(times)
end_to_end_distances = np.array(end_to_end_distances)
```

You can now analyze these time series:

```python
# Calculate basic statistics
print(f"Average end-to-end distance: {np.mean(end_to_end_distances):.2f} ± {np.std(end_to_end_distances):.2f} Å")
print(f"Min/Max end-to-end distance: {np.min(end_to_end_distances):.2f} / {np.max(end_to_end_distances):.2f} Å")

# Find when the system is most compact
most_compact_frame = np.argmin(end_to_end_distances)
print(f"Most compact at frame {most_compact_frame} (t = {times[most_compact_frame]:.1f} ps)")
```

Sources: [package/MDAnalysis/__init__.py#L116](package/MDAnalysis/__init__.py#L116), [package/MDAnalysis/core/universe.py#L78](package/MDAnalysis/core/universe.py#L78)

## Running a Simple RMSD Analysis

Root Mean Square Deviation (RMSD) is one of the most common analyses in molecular dynamics. It measures how much your structure has deviated from a reference structure. Let's perform a basic RMSD analysis:

```python
from MDAnalysis.analysis import rms

# Select atoms for RMSD calculation (usually protein backbone)
protein = u.select_atoms('protein')

# Create arrays to store results
rmsd_values = []

# Use the first frame as reference
u.trajectory[0]  # Go to first frame
reference_positions = protein.positions.copy()

# Loop through trajectory and calculate RMSD
for ts in u.trajectory:
    rmsd = rms.rmsd(protein.positions, reference_positions)
    rmsd_values.append(rmsd)
    if ts.frame % 10 == 0:
        print(f"Frame {ts.frame}: RMSD = {rmsd:.3f} Å")

rmsd_values = np.array(rmsd_values)
```

For a more convenient way to perform RMSD analysis, MDAnalysis provides the RMSD class:

```python
from MDAnalysis.analysis.rms import RMSD

# Run RMSD analysis (select protein backbone atoms)
R = RMSD(u.select_atoms('protein'), 
         u.select_atoms('protein'),
         frame=0,  # reference frame
         ref_frame=0)  # reference frame in reference structure

R.run()

# Get results
rmsd_results = R.rmsd
print(f"RMSD results shape: {rmsd_results.shape}")
# Columns: frame, time (ps), RMSD (Å)
```

This gives you a more structured output with frame numbers, times, and RMSD values for further analysis.

Sources: [package/MDAnalysis/analysis/rms.py#L24](package/MDAnalysis/analysis/rms.py#L24), [README.rst#L16](README.rst#L16)

## Putting It All Together: A Complete Example

Let's combine everything we've learned into a complete analysis script that analyzes a protein's structural properties over time:

```python
import MDAnalysis as mda
from MDAnalysis.tests.datafiles import PSF, DCD
import numpy as np
import matplotlib.pyplot as plt

# 1. Load the system
u = mda.Universe(PSF, DCD)
ca_atoms = u.select_atoms('name CA')
protein = u.select_atoms('protein')

print(f"Analyzing {len(ca_atoms)} C-alpha atoms over {len(u.trajectory)} frames")

# 2. Prepare arrays for results
times = []
rg_values = []
rmsd_values = []
ee_distances = []

# 3. Set reference for RMSD (first frame)
u.trajectory[0]
ref_positions = ca_atoms.positions.copy()

# 4. Loop through trajectory
for ts in u.trajectory:
    current_time = u.trajectory.time
    times.append(current_time)
    
    # Calculate properties
    rg = rms.radius_of_gyration(ca_atoms)
    rg_values.append(rg)
    
    rmsd = rms.rmsd(ca_atoms.positions, ref_positions)
    rmsd_values.append(rmsd)
    
    ee_dist = np.linalg.norm(ca_atoms[-1].position - ca_atoms[0].position)
    ee_distances.append(ee_dist)
    
    # Progress update
    if ts.frame % 20 == 0:
        print(f"Frame {ts.frame}: t={current_time:.0f}ps, RG={rg:.2f}Å, RMSD={rmsd:.3f}Å")

# 5. Convert to numpy arrays
times = np.array(times)
rg_values = np.array(rg_values)
rmsd_values = np.array(rmsd_values)
ee_distances = np.array(ee_distances)

# 6. Print summary statistics
print("\n=== ANALYSIS SUMMARY ===")
print(f"Radius of gyration: {np.mean(rg_values):.2f} ± {np.std(rg_values):.2f} Å")
print(f"RMSD from initial structure: {np.mean(rmsd_values):.3f} ± {np.std(rmsd_values):.3f} Å")
print(f"End-to-end distance: {np.mean(ee_distances):.2f} ± {np.std(ee_distances):.2f} Å")

# 7. Quick visualization (if matplotlib is available)
try:
    plt.figure(figsize=(10, 6))
    plt.plot(times, rg_values, label='Radius of gyration')
    plt.plot(times, rmsd_values * 10, label='RMSD (×10)')
    plt.plot(times, ee_distances, label='End-to-end distance')
    plt.xlabel('Time (ps)')
    plt.ylabel('Distance (Å)')
    plt.title('Protein Structural Properties vs Time')
    plt.legend()
    plt.grid(True)
    plt.show()
except ImportError:
    print("Matplotlib not available for plotting")
```

This complete example demonstrates the typical workflow for analyzing molecular dynamics simulations with MDAnalysis. You can adapt this template for your own research questions and simulation data.

## What's Next?

Congratulations! You've learned the basics of MDAnalysis, including how to:
- Load molecular systems from topology and trajectory files
- Select specific atoms using powerful selection language
- Perform basic geometric calculations
- Analyze changes over time by walking through trajectories
- Run common analyses like RMSD

From here, you might want to explore:
- **Advanced analyses**: Check out the `MDAnalysis.analysis` module for specialized analyses like hydrogen bonding, density calculations, and principal component analysis
- **Visualization**: Integrate with visualization tools like VMD, PyMOL, or NGLView
- **File formats**: Learn about the wide range of file formats supported by MDAnalysis
- **Performance**: Discover optimization techniques for analyzing large systems

Remember, MDAnalysis has excellent documentation and an active community. If you get stuck, check the official documentation or ask questions on GitHub Discussions.
