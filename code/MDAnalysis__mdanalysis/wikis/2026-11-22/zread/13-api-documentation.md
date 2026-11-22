

The **MDAnalysis** library provides a comprehensive Python toolkit for analyzing molecular dynamics simulations. This documentation serves as a technical reference to the core API components and their usage patterns.

## Core Architecture Overview

MDAnalysis follows a hierarchical object model that represents molecular systems at different levels of granularity. The architecture centers around a few fundamental classes that work together to provide a flexible framework for trajectory analysis.

The **Universe** class serves as the main container for all molecular system information. It ties together topology data (connectivity, atom types, etc.) with coordinate data from trajectory files. Think of the Universe as your entry point to all analysis operations - almost everything in MDAnalysis begins by creating or accessing a Universe object.

```python
import MDAnalysis as mda

# Create a Universe from topology and trajectory files
u = mda.Universe("topology.psf", "trajectory.dcd")
```

From the Universe, you can access the primary components of your molecular system: atoms, residues, and segments, each organized into their respective group classes.

Sources: [package/MDAnalysis/__init__.py#L24-151](package/MDAnalysis/__init__.py#L24-151), [package/MDAnalysis/core/universe.py#L307-486](package/MDAnalysis/core/universe.py#L307-486)

## The Universe Class

The **Universe** class is the central object in MDAnalysis. It contains all the information describing the molecular system and provides methods for manipulating and analyzing this data.

### Key Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `atoms` | AtomGroup | All particles in the system |
| `residues` | ResidueGroup | All residues in the system |
| `segments` | SegmentGroup | All segments in the system |
| `trajectory` | ReaderBase | Currently loaded trajectory reader |
| `dimensions` | numpy.ndarray | System dimensions at current timestep |

The Universe object maintains the current state of your simulation, including coordinates, topology information, and system dimensions. As you iterate through trajectory frames, these properties update to reflect the current timestep.

### Constructor Parameters

Creating a Universe requires understanding a few key parameters:

```python
u = mda.Universe(
    topology="topology.psf",           # Topology file (required)
    coordinates="trajectory.dcd",      # Trajectory file (optional)
    topology_format=None,              # Auto-detected by default
    format=None,                       # Auto-detected by default
    in_memory=False,                   # Keep trajectory in memory
    transformations=None               # Apply transformations on load
)
```

> [!TIP]
> When loading trajectories, MDAnalysis automatically detects file formats from extensions, but you can explicitly specify formats for faster loading or ambiguous cases.

The topology parameter defines the chemical system - atom types, bonds, residues, etc. The coordinates parameter provides the actual atomic positions that change over time. Many common file formats are supported for both topology and coordinates.

Sources: [package/MDAnalysis/core/universe.py#L328-447](package/MDAnalysis/core/universe.py#L328-447)

## AtomGroup: The Workhorse Class

The **AtomGroup** class is arguably the most important object in MDAnalysis. It represents collections of atoms and provides the primary interface for selecting, analyzing, and manipulating atomic data.

An AtomGroup can be obtained in several ways:

```python
# All atoms in the system
all_atoms = u.atoms

# Selection using selection language
protein = u.select_atoms("protein")

# Slicing existing AtomGroups
first_10 = u.atoms[:10]

# By attribute
backbone = u.select_atoms("name CA or name N or name O")
```

### Essential AtomGroup Properties

```python
# Basic information
ag.n_atoms                  # Number of atoms
ag.total_mass()            # Total mass of the group
ag.center_of_mass()        # Center of mass coordinates
ag.center_of_geometry()    # Geometric center
ag.charges                 # Atomic charges as numpy array
ag.masses                  # Atomic masses as numpy array

# Coordinate access
ag.positions              # Current coordinates (N x 3 array)
ag.velocities             # Current velocities (if available)
ag.forces                 # Current forces (if available)
```

The real power of AtomGroup lies in how it seamlessly integrates coordinate data with topological information. Positions are returned as numpy arrays, enabling easy mathematical operations and integration with Python's scientific computing ecosystem.

```python
# Example: Calculate radius of gyration
import numpy as np

def radius_of_gyration(atomgroup):
    com = atomgroup.center_of_mass()
    positions = atomgroup.positions
    squared_distances = np.sum((positions - com)**2, axis=1)
    return np.sqrt(np.mean(squared_distances))
```

Sources: [package/MDAnalysis/core/groups.py#L24-92](package/MDAnalysis/core/groups.py#L24-92), [package/MDAnalysis/core/__init__.py#L25-51](package/MDAnalysis/core/__init__.py#L25-51)

## Selection Language

MDAnalysis provides a powerful atom selection language that allows you to create AtomGroups based on complex criteria. This selection language supports various syntaxes including CHARMM, VMD, Gromacs, and Jmol styles.

### Selection Examples

```python
# Basic selections
water = u.select_atoms("resname SOL")           # By residue name
protein = u.select_atoms("protein")              # All protein atoms
backbone = u.select_atoms("name CA or name N")   # By atom names

# Geometric selections
around5 = u.select_atoms("around 5 protein")     # Within 5Å of protein
zone = u.select_atoms("point 10 20 30 5")        # Within 5Å of point

# Combined selections
phosphate = u.select_atoms("(resname DNA) and (name P or name OP1 or name OP2)")
```

The selection language is parsed at runtime and converted to efficient operations on the underlying data. This provides both flexibility and performance for common analysis tasks.

Sources: [package/MDAnalysis/__init__.py#L86-123](package/MDAnalysis/__init__.py#L86-123)

## Trajectory Handling

The trajectory system in MDAnalysis provides flexible access to coordinate data across simulation timesteps. The Universe's trajectory attribute manages coordinate data with an efficient iterator interface.

### Navigating Trajectories

```python
# Basic iteration
for ts in u.trajectory:
    print(f"Frame {ts.frame}, time: {ts.time} ps")
    # Current coordinates are automatically updated
    
# Access specific frames
u.trajectory[50]        # Go to frame 50
u.trajectory.frame = 0  # Go to first frame
u.trajectory.rewind()   # Alternative way to rewind

# Frame properties
current_frame = u.trajectory.frame      # Current frame number
total_frames = u.trajectory.n_frames    # Total number of frames
current_time = u.trajectory.time        # Current simulation time
```

The trajectory iterator automatically updates the coordinates accessible through AtomGroup objects, making it easy to perform analyses across all frames without manual coordinate management.

> [!TIP]
> For large trajectories, consider using MDAnalysis' frame skipping or memory mapping features to reduce memory usage while maintaining performance.

Sources: [package/MDAnalysis/core/universe.py#L451-453](package/MDAnalysis/core/universe.py#L451-453), [package/MDAnalysis/__init__.py#L115-123](package/MDAnalysis/__init__.py#L115-123)

## File Format Support

MDAnalysis supports a wide range of file formats for both topology and coordinate data. The library uses a plugin-based architecture to handle different formats, making it extensible for new or custom formats.

### Supported Topology Formats

Common topology formats include:
- **CHARMM/NAMD**: PSF files
- **AMBER**: PRMTOP, PARM7 files  
- **GROMACS**: TOP, TPR files
- **PDB**: Protein Data Bank format
- **GRO**: GROMACS structure files

### Supported Coordinate Formats

Coordinate/trajectory formats include:
- **DCD**: CHARMM/NAMD trajectories
- **XTC/TRR**: GROMACS compressed trajectories
- **XYZ**: Generic coordinate format
- **PDB**: Single-frame structure files
- **TRJ**: LAMMPS trajectory format

The library automatically detects file formats from extensions but allows explicit specification when needed:

```python
# Auto-detection (default)
u = mda.Universe("system.psf", "trajectory.xtc")

# Explicit format specification  
u = mda.Universe("system.top", "trajectory.dcd", 
                 topology_format="AMBER", format="DCD")
```

Sources: [package/MDAnalysis/__init__.py#L314-344](package/MDAnalysis/__init__.py#L314-344)

## Analysis Framework Landscape

Beyond the core data structures, MDAnalysis provides extensive analysis capabilities organized into logical modules. These modules build on the foundation provided by the Universe and AtomGroup classes.

### Analysis Module Structure

```
MDAnalysis.analysis/
├── align.py          # Structural alignment and fitting
├── rms.py           # RMSD calculations
├── distances.py    # Distance-based analyses
├── rdf.py          # Radial distribution functions
├── hbonds/         # Hydrogen bond analysis
├── pca.py          # Principal component analysis
└── ...             # Many more specialized analysis tools
```

Each analysis module follows a similar pattern: create an analysis object with parameters, run the analysis, and access results:

```python
import MDAnalysis.analysis.rms as rms

# Set up RMSD analysis
rmsd_analysis = rms.RMSD(u, select="protein").run()

# Access results
times = rmsd_analysis.times
rmsd_values = rmsd_analysis.rmsd
```

This modular design allows for easy extension and customization while maintaining consistent usage patterns across different analysis types.

Sources: [package/MDAnalysis/](package/MDAnalysis/)

## Best Practices and Common Patterns

When working with MDAnalysis, several patterns emerge as best practices for efficient and maintainable code.

### Memory and Performance Considerations

```python
# Good: Use selections and avoid storing all coordinate data
protein_frames = []
for ts in u.trajectory[::10]:  # Sample every 10th frame
    protein_com = u.select_atoms("protein").center_of_mass()
    protein_frames.append(protein_com)

# Avoid: Loading entire trajectory into memory
# all_coords = [u.atoms.positions.copy() for ts in u.trajectory]
```

### Error Handling

MDAnalysis provides specific exceptions for common issues:

```python
from MDAnalysis.exceptions import NoDataError, SelectionError

try:
    ag = u.select_atoms("resname NONEXISTENT")
except SelectionError:
    print("Invalid selection criteria")
```

### Integration with Scientific Python Stack

```python
import numpy as np
import matplotlib.pyplot as plt

# Calculate RMS fluctuations
positions = []
for ts in u.trajectory:
    positions.append(u.select_atoms("protein CA").positions.copy())
positions = np.array(positions)  # Shape: (n_frames, n_atoms, 3)
rmsf = np.sqrt(np.mean(np.var(positions, axis=0), axis=1))

# Plot results
plt.plot(rmsf)
plt.xlabel("Atom index")
plt.ylabel("RMS fluctuation (Å)")
plt.show()
```

Sources: [package/MDAnalysis/exceptions.py#L189-198](package/MDAnalysis/exceptions.py#L189-198)

## Next Steps in the Documentation

This API reference covers the fundamental components of MDAnalysis. For more specific topics, consider exploring:

- **File Format Support**: Detailed information on supported file formats and their limitations
- **Performance Optimization**: Techniques for handling large trajectories efficiently
- **Extending MDAnalysis**: Creating custom readers, writers, and analysis components

The modularity of MDAnalysis means you can start with simple analyses and gradually adopt more advanced features as needed. The core API patterns demonstrated here remain consistent throughout the library's extensive functionality.