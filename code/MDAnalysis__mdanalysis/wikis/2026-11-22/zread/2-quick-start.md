

Welcome to MDAnalysis, a powerful Python library for analyzing molecular dynamics simulations! This Quick Start guide will help you get up and running with MDAnalysis in just a few minutes, walking you through installation and your first analysis.

## What is MDAnalysis?

MDAnalysis is a Python toolkit designed to analyze molecular dynamics trajectories from popular simulation packages like GROMACS, Amber, NAMD, CHARMM, and many others. It allows you to read simulation data, access atomic coordinates through NumPy arrays, and perform complex analysis tasks with ease. Whether you're studying protein folding, drug interactions, or material properties, MDAnalysis provides the tools you need.

## Installation

Getting MDAnalysis installed is straightforward. You can choose between two popular package managers:

### Option 1: Using pip (Recommended)

Install the latest stable release with pip:

```bash
pip install --upgrade MDAnalysis
```

For testing and examples, you can also install the test suite:

```bash
pip install --upgrade MDAnalysisTests
```

### Option 2: Using conda

If you prefer conda, first add the MDAnalysis channel and then install:

```bash
conda config --add channels MDAnalysis
conda install mdanalysis
```

To upgrade to the latest version:

```bash
conda update mdanalysis
```

> [!TIP]
> Note: Conda packages currently only support serial calculations. If you plan to use parallel OpenMP algorithms, install with pip instead and ensure you have a working OpenMP installation.

Sources: [package/INSTALL#L9-L76](package/INSTALL#L9-L76), [README.rst#L51-L59](README.rst#L51-L59)

## Your First Analysis

Let's dive into your first molecular dynamics analysis with MDAnalysis. We'll load a simulation, select specific atoms, and calculate some basic properties.

### Step 1: Load Your Simulation

The core of MDAnalysis is the `Universe` object, which combines topology (atom information) and trajectory (coordinate data). You can create a Universe from your simulation files:

```python
import MDAnalysis as mda

# Load simulation results with a single line
u = mda.Universe('topology.psf', 'trajectory.dcd')
```

The first argument is your topology file (PSF, PDB, GRO, etc.), and the second is your trajectory file (DCD, XTC, TRR, etc.). MDAnalysis automatically detects the file format and loads the appropriate reader.

Sources: [package/MDAnalysis/__init__.py#L58-L61](package/MDAnalysis/__init__.py#L58-L61), [package/MDAnalysis/core/universe.py#L25-L29](package/MDAnalysis/core/universe.py#L25-L29)

### Step 2: Select Atoms

MDAnalysis provides powerful atom selection capabilities using a syntax similar to CHARMM. Let's select all alpha-carbon atoms:

```python
# Select alpha-carbon atoms
ca = u.select_atoms('name CA')
print(f"Found {len(ca)} alpha-carbon atoms")
```

You can also combine selection criteria:

```python
# Select all protein atoms within 5 Angstroms of residue 50
protein_near_res50 = u.select_atoms('protein and around 5 (resid 50)')
```

Sources: [package/MDAnalysis/__init__.py#L63-L65](package/MDAnalysis/__init__.py#L63-L65), [README.rst#L32-L34](README.rst#L32-L34)

### Step 3: Access Atomic Data

Once you have selected atoms, you can easily access their properties as NumPy arrays:

```python
# Get positions, velocities, and forces
positions = ca.positions  # Shape: (n_atoms, 3)
velocities = ca.velocities  # If available in trajectory
forces = ca.forces  # If available in trajectory

# Calculate center of mass
com = ca.center_of_mass()
print(f"Center of mass: {com}")
```

All atomic properties are returned as NumPy arrays, making it easy to perform mathematical operations and integrate with other scientific Python libraries.

Sources: [README.rst#L35-L40](README.rst#L35-L40), [package/MDAnalysis/__init__.py#L67-L73](package/MDAnalysis/__init__.py#L67-L73)

### Step 4: Analyze the Trajectory

Now let's iterate through the trajectory frames and analyze how the system evolves over time:

```python
import numpy as np

# Calculate end-to-end distance for each frame
def end_to_end_distance(atomgroup):
    """Calculate the end-to-end distance of an atom group."""
    coords = atomgroup.positions
    vector = coords[-1] - coords[0]  # Last atom minus first atom
    return np.sqrt(np.dot(vector, vector))

# Analyze all frames in the trajectory
distances = []
for ts in u.trajectory:
    distance = end_to_end_distance(ca)
    distances.append(distance)
    print(f"Frame {ts.frame}: Distance = {distance:.2f} Å")

print(f"Average end-to-end distance: {np.mean(distances):.2f} Å")
```

The `u.trajectory` object allows you to iterate through all frames in your simulation, with each iteration updating the coordinates of all atoms in the Universe.

Sources: [package/MDAnalysis/__init__.py#L75-L85](package/MDAnalysis/__init__.py#L75-L85), [README.rst#L41-L46](README.rst#L41-L46)

## Working with Test Data

Don't have simulation data handy? MDAnalysis comes with test trajectories you can use to explore the functionality:

```python
from MDAnalysis.tests.datafiles import PSF, DCD, PDB, XTC

# Load test data (Adenylate Kinase simulations)
u_charmm = mda.Universe(PSF, DCD)  # CHARMM format
u_gromacs = mda.Universe(PDB, XTC)  # GROMACS format

# Now you can analyze these test systems
print(f"CHARMM system has {len(u_charmm.atoms)} atoms")
print(f"GROMACS system has {len(u_gromacs.atoms)} atoms")
```

These test files represent Adenylate Kinase simulations in different formats, perfect for learning and testing your analysis workflows.

Sources: [package/MDAnalysis/__init__.py#L90-L98](package/MDAnalysis/__init__.py#L90-L98), [testsuite/MDAnalysisTests/datafiles.py#L1-L40](testsuite/MDAnalysisTests/datafiles.py#L1-L40)

## Next Steps

Congratulations! You've completed your first MDAnalysis workflow. Here are some suggestions for what to explore next:

1. **Try different selection commands**: MDAnalysis supports a rich selection language. Experiment with selections like `resname ALA and (name CA or name N or name C)` or `around 5 protein`.

2. **Explore built-in analyses**: Check out the `MDAnalysis.analysis` module for pre-built analysis methods like RMSD calculation, radius of gyration, and more.

3. **Visualize your results**: Use MDAnalysis's visualization capabilities or export data to your favorite plotting library.

4. **Read the User Guide**: For more detailed information and tutorials, visit the [MDAnalysis User Guide](https://userguide.mdanalysis.org).

Remember, the MDAnalysis community is here to help! If you run into issues or have questions, check out the [GitHub Discussions](https://github.com/MDAnalysis/mdanalysis/discussions) or [documentation](https://docs.mdanalysis.org).
