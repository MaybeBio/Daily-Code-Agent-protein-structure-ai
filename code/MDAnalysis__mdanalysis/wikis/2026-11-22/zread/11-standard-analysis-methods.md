

MDAnalysis provides a comprehensive suite of standard analysis methods that are essential for molecular dynamics simulations. These methods allow researchers to extract meaningful insights from simulation data, ranging from basic structural properties to complex dynamic behaviors. In this guide, we'll explore the most commonly used analysis methods and demonstrate how to apply them effectively to your research.

## The Analysis Framework

Before diving into specific methods, it's important to understand the unified analysis framework that all MDAnalysis analysis methods share. Every analysis class inherits from the `AnalysisBase` class, which provides a consistent workflow and API for users.

```python
# Standard workflow for any analysis method
import MDAnalysis as mda
from MDAnalysis.analysis import rms

# 1. Load your universe
u = mda.Universe("topology.psf", "trajectory.dcd")

# 2. Instantiate the analysis
rmsd_analysis = rms.RMSD(u, select="protein and name CA")

# 3. Run the analysis
rmsd_analysis.run()

# 4. Access results
results = rmsd_analysis.results.rmsd
```

This consistent pattern makes it easy to learn new analysis methods once you understand the basic workflow. The `run()` method automatically handles frame iteration, progress reporting, and result storage. All results are stored in the `results` attribute, which is a special `Results` object that allows access via both dictionary and attribute syntax.

Sources: [base.py#L23-48](package/MDAnalysis/analysis/base.py#L23-48), [results.py#L57-100](package/MDAnalysis/analysis/results.py#L57-100)

## Structural Analysis Methods

### Root Mean Square Deviation (RMSD)

RMSD is one of the most fundamental analysis methods in molecular dynamics. It measures the average distance between atoms of superimposed structures, providing insight into the structural stability and conformational changes of your system.

```python
from MDAnalysis.analysis import rms

# Calculate RMSD for protein backbone
rmsd = rms.RMSD(u, 
                select="backbone",  # atoms to analyze
                ref_frame=0)        # reference frame

rmsd.run()

# Access results: frame, time, RMSD
print(f"RMSD values: {rmsd.results.rmsd[:, 2]}")
```

RMSD is particularly useful for:
- Monitoring protein stability during simulations
- Comparing different conformational states
- Assessing equilibration of your system

> [!TIP]
> For more detailed analysis, you can calculate RMSD for specific domains or regions of your molecule using the `groupselections` parameter. This allows you to track relative movements between different parts of your system.

Sources: [rms.py#L23-39](package/MDAnalysis/analysis/rms.py#L23-39), [rms.py#L86-91](package/MDAnalysis/analysis/rms.py#L86-91)

### Radial Distribution Function (RDF)

The Radial Distribution Function (RDF) describes how particle density varies as a function of distance from a reference particle. It's essential for understanding solvation structure, ion pairing, and other spatial arrangements in your system.

```python
from MDAnalysis.analysis import rdf

# Calculate RDF between protein and water
protein = u.select_atoms("protein")
water = u.select_atoms("resname SOL and name OW")

rdf_analysis = rdf.InterRDF(protein, water,
                            nbins=100,     # number of bins
                            range=(0, 10)) # distance range in Angstroms

rdf_analysis.run()

# Plot RDF
import matplotlib.pyplot as plt
plt.plot(rdf_analysis.results.bins, rdf_analysis.results.rdf)
plt.xlabel("Distance (Å)")
plt.ylabel("g(r)")
plt.show()
```

RDF analysis is commonly used for:
- Studying solvation shells around proteins
- Analyzing ion distributions
- Investigating liquid structure
- Validating force fields against experimental data

The mathematical foundation of RDF calculates the probability of finding particle B at distance r from particle A, normalized by the ideal gas distribution.

Sources: [rdf.py#L24-60](package/MDAnalysis/analysis/rdf.py#L24-60), [rdf.py#L86-100](package/MDAnalysis/analysis/rdf.py#L86-100)

## Geometric Analysis Methods

### Distance Analysis

Distance calculations are fundamental to many types of molecular analysis. MDAnalysis provides efficient methods for calculating distances between atoms or groups of atoms, with proper handling of periodic boundary conditions.

```python
from MDAnalysis.analysis import distances

# Calculate distances between two groups
group1 = u.select_atoms("resname ARG and name NH1")
group2 = u.select_atoms("resname GLU and name OE1")

# Calculate minimum distances
min_distances = []
for ts in u.trajectory:
    dist = distances.dist(group1, group2)
    min_distances.append(dist.min())

# For contact analysis
contact_matrix = distances.contact_matrix(
    group1.positions, 
    cutoff=4.0,  # 4 Angstrom cutoff
    box=u.dimensions
)
```

Distance analysis is versatile and used for:
- Monitoring specific interactions (e.g., hydrogen bonds)
- Calculating binding distances
- Analyzing contact maps
- Studying conformational changes

Sources: [distances.py#L26-39](package/MDAnalysis/analysis/distances.py#L26-39), [distances.py#L71-100](package/MDAnalysis/analysis/distances.py#L71-100)

### Dihedral Angle Analysis

Dihedral angles are crucial for understanding the conformational states of molecules, particularly proteins and nucleic acids. MDAnalysis provides specialized classes for analyzing dihedral angles, including Ramachandran plots for proteins.

```python
from MDAnalysis.analysis.dihedrals import Dihedral, Ramachandran

# General dihedral analysis
# Select phi angles for residues 5-10
phi_selections = [res.phi_selection() for res in u.residues[4:9]]
dihedral = Dihedral(phi_selections).run()

# Ramachandran analysis for protein backbone
protein = u.select_atoms("protein")
rama = Ramachandran(protein).run()

# Plot Ramachandran plot
import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(8, 8))
rama.plot(ax=ax, ref=True)
plt.show()
```

Dihedral analysis is essential for:
- Characterizing protein secondary structure
- Monitoring conformational transitions
- Studying nucleic acid structure
- Analyzing ligand binding modes

Sources: [dihedrals.py#L23-39](package/MDAnalysis/analysis/dihedrals.py#L23-39), [dihedrals.py#L54-69](package/MDAnalysis/analysis/dihedrals.py#L54-69)

## Density Analysis

### Volumetric Density Analysis

Density analysis allows you to calculate and visualize the three-dimensional distribution of particles in your system. This is particularly useful for studying solvent organization, ion channels, and binding pockets.

```python
from MDAnalysis.analysis.density import DensityAnalysis

# Calculate water density around protein
water = u.select_atoms("resname SOL and name OW")

density_analysis = DensityAnalysis(water,
                                  delta=1.0,  # 1 Angstrom grid spacing
                                  padding=2.0) # padding in Angstroms

density_analysis.run()

# Convert to physical units and export
density = density_analysis.results.density
density.convert_density('TIP4P')  # Convert to relative density
density.export("water_density.dx", type="double")
```

Density analysis is valuable for:
- Mapping solvent density around proteins
- Identifying binding sites and pockets
- Studying membrane systems
- Visualizing ion channels

The resulting density files can be visualized in programs like VMD, PyMOL, or Chimera, providing intuitive 3D representations of particle distributions.

Sources: [density.py#L28-46](package/MDAnalysis/analysis/density.py#L28-46), [density.py#L72-78](package/MDAnalysis/analysis/density.py#L72-78)

## Advanced Analysis Features

### Parallel Analysis

For computationally intensive analyses, MDAnalysis supports parallel processing to significantly reduce computation time:

```python
# Run analysis in parallel using multiple cores
rmsd_analysis.run(n_jobs=4)  # Use 4 CPU cores
```

### Frame Selection

All analysis methods provide flexible frame selection options:

```python
# Analyze specific frames
rmsd_analysis.run(start=100, stop=200, step=5)  # Frames 100-200, every 5th frame

# Or provide a list of specific frames
rmsd_analysis.run(frames=[0, 10, 20, 30, 40])
```

### Result Management

The `Results` object provides convenient access to analysis outputs:

```python
# Access results as attributes
rmsd_values = rmsd_analysis.results.rmsd

# Or as dictionary items
rmsd_values = rmsd_analysis.results['rmsd']

# Results also include time information
times = rmsd_analysis.times
```

> [!TIP]
> When working with large trajectories, consider using the `start`, `stop`, and `step` parameters to analyze a representative subset of frames. This can significantly reduce computation time while still providing meaningful insights.

## Best Practices for Analysis

1. **Always check your selections**: Verify that your atom selections are correct before running lengthy analyses.

2. **Consider periodic boundary conditions**: Ensure your system is properly prepared with molecules made whole and centered appropriately.

3. **Use appropriate reference frames**: Choose meaningful reference structures for comparative analyses like RMSD.

4. **Validate your results**: Compare with known values or literature when possible to ensure your analysis is correct.

5. **Document your parameters**: Keep track of analysis parameters for reproducibility.

## Conclusion

MDAnalysis provides a powerful and consistent framework for molecular dynamics analysis. The standard methods covered here—RMSD, RDF, distances, dihedrals, and density analysis—form the foundation of most MD analysis workflows. By understanding these methods and the unified analysis framework, you'll be well-equipped to extract meaningful insights from your simulation data.

Remember that these methods can be combined and extended to address specific research questions. The modular nature of MDAnalysis makes it easy to build custom analysis workflows while leveraging the robust, tested implementations of standard methods.
