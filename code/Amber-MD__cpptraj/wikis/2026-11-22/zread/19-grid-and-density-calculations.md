

Grid and density calculations in CPPTRAJ provide powerful spatial analysis capabilities for molecular dynamics trajectories, enabling researchers to quantify atomic distributions, solvation properties, and energy landscapes across three-dimensional grids. These calculations form the foundation for advanced analyses like Grid Inhomogeneous Solvation Theory (GIST) and volumetric mapping.

## Architectural Overview

CPPTRAJ implements grid and density calculations through a modular architecture that separates spatial discretization, coordinate mapping, and statistical aggregation. The grid system originated from PTRAJ routines adapted for CPPTRAJ, including Action_Grid and GridAction classes, with significant enhancements for parallel processing and flexible output formats [README.md](README.md#L148-L153).

```mermaid
graph TB
    subgraph Input
        A[Trajectory Frames]
        B[Topology/Parameters]
        C[User Masks]
    end
    
    subgrid GridSystem
        D[Grid Generation]
        E[Spatial Binning]
        F[Coordinate Mapping]
        G[Accumulation]
    end
    
    subgrid DensityTypes
        H[Number Density]
        I[Mass Density]
        J[Charge Density]
        K[Electron Density]
    end
    
    subgrid Output
        L[OpenDX Format]
        M[Xplor Format]
        N[ASCII Data]
        O[PDB Visualization]
    end
    
    A --> D
    B --> D
    C --> F
    D --> E
    E --> F
    F --> G
    G --> H
    G --> I
    G --> J
    G --> K
    H --> L
    I --> M
    J --> N
    K --> O
```

The grid system supports multiple density modes (number, mass, charge, electron) and various output formats optimized for different visualization tools [RunTest.sh](test/Test_Density/RunTest.sh#L27-L34).

## Grid Generation and Configuration

Grid generation in CPPTRAJ involves defining a three-dimensional grid that spans the simulation box or a user-defined region. The grid parameters specify spatial resolution and extent through bin counts and spacing, with support for both orthogonal and non-orthogonal simulation boxes.

### Basic Grid Configuration

The fundamental grid command requires specifying output filename and grid dimensions using six parameters (three dimensions with alternating bin count and spacing values):

```bash
grid <output> <nx> <dx> <ny> <dy> <nz> <dz> <mask>
```

For example, to create a 40×40×40 grid with 0.5 Å spacing centered on water oxygen atoms:
```bash
grid out.dx 20 0.5 20 0.5 20 0.5 :WAT@O
```
[RunTest.sh](test/Test_Grid/RunTest.sh#L22-L23)

The grid system accumulates atom occurrences across frames, enabling density calculations that reflect temporal averaging and ensemble statistics.

### Grid Centering Options

CPPTRAJ provides multiple centering strategies to position the grid relative to molecular features:

**Box Center**: Centers the grid on the simulation box boundaries, ideal for bulk solvent analysis:
```bash
grid box.dx 30 0.5 30 0.5 30 0.5 box :WAT
```
[RunTest.sh](test/Test_Grid/RunTest.sh#L52-L53)

**Mask Center**: Positions the grid based on the geometric center of selected atoms, allowing targeted analysis around specific molecular regions:
```bash
grid mask.dx 30 0.5 30 0.5 30 0.5 center :1-12@CA :WAT
```
[RunTest.sh](test/Test_Grid/RunTest.sh#L59-L60)

**Explicit Center**: Specifies exact coordinates for grid origin using the gridcenter keyword:
```bash
grid test.dx 34 0.5 44 0.5 36 0.5 gridcenter 1.5 1.0 0.0 :WAT
```
[RunTest.sh](test/Test_Grid/RunTest.sh#L46-L47)

> [!TIP]
> When analyzing solvation shells around biomolecules, use mask-based centering with appropriate solute selection to ensure the grid captures the complete hydration layer without excessive empty space at boundaries.

### Aggregation Modes

The grid system supports different atomic aggregation strategies that affect how atoms contribute to grid bins:

**byres**: Aggregates atoms by residue, placing the entire residue contribution in the bin containing any residue atom. This is useful for mapping residue-level distributions:
```bash
grid out byres.dx 10 1 10 1 10 1 :WAT byres
```
[RunTest.sh](test/Test_Grid/RunTest.sh#L27)

**bymol**: Aggregates by molecule, grouping all atoms within the same molecular entity. This is particularly valuable for solvent molecules where you want to treat each water molecule as a single unit:
```bash
grid out bymol.dx 10 1 10 1 10 1 :WAT bymol
```
[RunTest.sh](test/Test_Grid/RunTest.sh#L28)

These aggregation modes significantly affect density interpretation—residue-level analysis reveals macromolecular features while molecular-level aggregation is more appropriate for solvent distributions.

### Non-Orthogonal Grid Support

CPPTRAJ handles non-orthogonal simulation boxes (truncated octahedra, rhombic dodecahedra) through the boxref parameter, which references a structure containing the appropriate box vectors:

```bash
grid nonortho.dx boxref [REF] 50 50 50 :WAT@O pdb nonortho.pdb
```
[RunTest.sh](test/Test_Grid/RunTest.sh#L67-L68)

The grid wrapping option (gridwrap) ensures atoms near periodic boundaries are correctly mapped into their periodic images, maintaining consistent density across box edges:
```bash
grid nonortho_wrap.dx boxref [REF] 20 20 20 :WAT@O gridwrap name BC
```
[RunTest.sh](test/Test_Grid/RunTest.sh#L76-L77)

> [!TIP]
> When working with non-orthogonal systems, always verify the box reference structure matches the trajectory geometry to prevent coordinate transformation errors that corrupt density distributions.

### Output Formats

CPPTRAJ generates grids in multiple formats optimized for different analysis workflows:

**OpenDX Format**: Default format for grid data, widely supported by visualization tools like VMD, PyMOL, and Chimera:
```bash
grid out.dx 20 0.5 20 0.5 20 0.5 :WAT@O
```
[RunTest.sh](test/Test_Grid/RunTest.sh#L23)

**Xplor Format**: Alternative format compatible with Xplor-NIH and other structure analysis tools:
```bash
grid out.xplor 20 0.5 20 0.5 20 0.5 :WAT@O name XPLOR
```
[RunTest.sh](test/Test_Grid/RunTest.sh#L22)

**PDB Format**: Generates atomic coordinates representing grid points for quick visualization and validation:
```bash
grid nonortho.dx boxref [REF] 50 50 50 :WAT@O pdb nonortho.pdb
```
[RunTest.sh](test/Test_Grid/RunTest.sh#L67)

The grid system can also read previously generated grids for further processing or comparison:
```bash
readdata out.dx.save
grid out.dx.2 data out.dx.save @CA opendx
```
[RunTest.sh](test/Test_Grid/RunTest.sh#L35-L38)

## Density Calculations Along Axes

While 3D grids provide complete volumetric distributions, density calculations along specific axes offer efficient analysis of directional properties, particularly for membrane systems and anisotropic environments.

### Density Types

CPPTRAJ implements four distinct density calculation modes, each emphasizing different physical properties:

| Density Type | Description | Typical Applications |
|--------------|-------------|---------------------|
| **Number** | Atom count per unit volume | Solvent distribution, occupancy analysis |
| **Mass** | Mass per unit volume | Mass transport, sedimentation studies |
| **Charge** | Charge per unit volume | Electrostatic potential analysis |
| **Electron** | Electron density per unit volume | X-ray scattering calculations |

These modes are specified as keywords in the density command:
```bash
density out number_density.dat number delta 0.25 ":PC@P31" ":PC@N31"
density out mass_density.dat mass delta 0.25 ":PC@P31" ":PC@N31"
density out charge_density.dat charge delta 0.25 ":PC@P31" ":PC@N31"
density out electron_density.dat electron delta 0.25 ":PC@P31" ":PC@N31"
```
[RunTest.sh](test/Test_Density/RunTest.sh#L27-L34)

### Axis Configuration

The delta parameter specifies bin spacing along the calculation axis, determining the resolution of density profiles. For lipid bilayer analysis, finer resolution (0.25-0.5 Å) captures the detailed structure of headgroup regions:

```bash
density :WAT@O out tz2.wato.agr xydy
density :WAT@O out restrict.agr xydy delta 0.5 restrict cylinder cutoff 5.0
```
[RunTest.sh](test/Test_Density/RunTest.sh#L45-L46)

The xydy output format produces Grace-compatible data files containing the axis position and density values suitable for direct plotting.

### Density Restrictions

CPPTRAJ supports spatial restrictions on density calculations, allowing analysis focused on specific regions. The cylinder restriction enables density profiling within a cylindrical volume defined by radius (cutoff) and axis:

```bash
density :WAT@O out restrict.agr xydy delta 0.5 restrict cylinder cutoff 5.0
```
[RunTest.sh](test/Test_Density/RunTest.sh#L46)

This is particularly useful for analyzing water penetration into membrane pores or ion channel selectivity filters where the relevant density is confined to a cylindrical pathway.

### Multi-Frame and Ensemble Density

Density calculations automatically aggregate across multiple frames, providing ensemble-averaged profiles. For comparing different simulation conditions (different box shapes, temperatures, force fields), CPPTRAJ can calculate separate densities and combine them for comparative analysis:

```bash
parm ../tz2.truncoct.parm7 [OCT]
trajin ../tz2.truncoct.nc parm [OCT]
density D1
go
clear trajin

parm ../tz2.ortho.parm7 [ORTHO]
trajin ../tz2.ortho.nc parm [ORTHO]
density D2
go

writedata total.dat D1 D2
```
[RunTest.sh](test/Test_Density/RunTest.sh#L51-L63)

This pattern enables systematic comparison of density profiles across simulation conditions while maintaining the underlying frame-by-frame data for detailed analysis.

## Bounds-Based Grid Generation

For analyses requiring precise spatial control, CPPTRAJ can generate grids based on molecular bounds rather than box dimensions. The bounds command calculates the minimum and maximum coordinates of selected atoms, defining a custom grid region that tightly encompasses the molecular structure:

```bash
bounds :1-13 dx 0.5 name MyGrid out bounds.dat
crdaction MyCoords grid bounds.xplor data MyGrid :WAT@O
```
[RunTest.sh](test/Test_Grid/RunTest.sh#L98-L101)

This two-step approach first defines the grid bounds and data, then applies it to a specific mask, enabling flexible analysis workflows where grid parameters can be defined independently from the density calculation.

## Grid Inhomogeneous Solvation Theory (GIST)

GIST represents the most sophisticated application of grid and density calculations in CPPTRAJ, providing a thermodynamic framework for analyzing solvation structure and energetics. The original Action_Gist implementation was contributed by Crystal N. Nguyen and Romelia F. Salomon from UC San Diego, with subsequent enhancements by Johannes Kraml, Franz Waibl, Klaus R. Liedl, and Steven Ramsey [README.md](README.md#L161-L166).

### GIST Output Components

GIST calculations produce multiple grid-based output files characterizing different aspects of solvation:

**Water Distributions**: Separate grids for water oxygen (gO) and hydrogen (gH) densities reveal spatial localization patterns:
```
Gist2-gO.dx.save
Gist2-gH.dx.save
```
[RunTest.sh](test/Test_GIST)

**Energy Densities**: Solvent-solute (Esw) and solvent-solvent (Eww) energy grids provide thermodynamic insights into local interactions:
```
Gist4-Esw-dens.dx.save
Gist4-Eww-dens.dx.save
Gist5-Solute-Etot-pme-dens.dx.save
Gist5-Water-Etot-pme-dens.dx.save
```
[RunTest.sh](test/Test_GIST)

**Entropic Contributions**: Translational, orientational, and six-component entropic densities decompose solvation entropy into physical components:
```
Gist2-dTStrans-dens.dx.save
Gist2-dTSorient-dens.dx.save
Gist2-dTSsix-dens.dx.save
```
[RunTest.sh](test/Test_GIST)

**Order Parameters**: Molecular orientation and neighbor-count densities quantify water structuring:
```
Gist2-neighbor-norm.dx.save
Gist2-order-norm.dx.save
```
[RunTest.sh](test/Test_GIST)

**Molecular Decomposition**: GIST can generate separate grids for different molecular species (ions, water molecules), enabling species-specific solvation analysis:
```
Gist8-Esw-mol-CL.dx.save
Gist8-Esw-mol-NA.dx.save
Gist8-Esw-mol-WAT.dx.save
```
[RunTest.sh](test/Test_GIST)

### GIST Integration with Grid System

GIST leverages the underlying grid infrastructure for spatial discretization and accumulation but adds specialized calculations for thermodynamic quantities. The multi-file output pattern reflects the complexity of solvation thermodynamics, with each grid representing a different contribution to the overall solvation free energy.

For researchers interested in detailed solvation analysis, the dedicated [GIST (Grid Inhomogeneous Solvation Theory)](23-gist-grid-inhomogeneous-solvation-theory) documentation provides complete coverage of GIST methodology, interpretation guidelines, and practical applications.

## Parallel Processing Considerations

Grid and density calculations in CPPTRAJ are designed for efficient parallelization using both OpenMP and MPI, enabling large-scale analysis of extensive trajectory data. The parallel strategy typically divides spatial domains or trajectory frames across processing elements, with careful handling of boundary conditions and accumulation to ensure correct results.

The grid system's design supports thread-safe accumulation, allowing multiple threads to increment grid bins simultaneously without race conditions when using appropriate synchronization mechanisms. This parallel capability is essential for production-level analysis of high-resolution grids from long trajectories.

## Common Analysis Patterns

### Hydration Shell Analysis

For analyzing water structure around proteins or nucleic acids:

```bash
# Center on solute and map water oxygen positions
autoimage origin
rms first :1-13
grid hydration.dx 40 0.5 40 0.5 40 0.5 center :1-13 :WAT@O
```

This generates a high-resolution density map suitable for identifying hydration sites and water-mediated interactions.

### Membrane Lipid Distributions

For analyzing lipid component distributions along membrane normal:

```bash
# Calculate number density for different lipid components
density PC_P31.dat number delta 0.25 :PC@P31
density PC_N31.dat number delta 0.25 :PC@N31
density OL_O16.dat number delta 0.25 :OL | :OL2
```

The overlapping density profiles reveal lipid component localization and tailgroup ordering.

### Ion Channel Penetration

For analyzing ion distributions in channel systems:

```bash
# Restrict density to cylindrical pathway along channel axis
density ion_density.dat xydy delta 0.5 restrict cylinder cutoff 3.0 :Na+ :Cl-
```

The cylindrical restriction focuses the calculation on the channel pore, avoiding bulk contributions that obscure permeation profiles.

## Integration with Other Analyses

Grid and density calculations often serve as preprocessing steps for more complex analyses:

**Contact Analysis**: Grid-based density maps identify high-probability contact regions that can be quantified using distance-based contact measurements, as detailed in [Contact Analysis and Native Contacts](18-contact-analysis-and-native-contacts).

**Hydrogen Bond Analysis**: Water density maps correlate with hydrogen bond networks, providing spatial context for bond formation and breaking patterns described in [Hydrogen Bond Analysis](15-hydrogen-bond-analysis).

**Energy Analysis**: GIST energy grids complement potential of mean force calculations and free energy methods documented in [Free Energy Calculations (TI, MM/PBSA)](21-free-energy-calculations-ti-mm-pbsa).

**Solvent Analysis**: Density-based solvation patterns provide context for general solvent behavior described in [Energy Extraction and Analysis](20-energy-extraction-and-analysis).

## Performance Optimization

For large-scale grid and density calculations, consider these optimization strategies:

1. **Resolution Balancing**: Use coarser grids for exploratory analysis, then refine around regions of interest identified from initial results.

2. **Mask Pruning**: Restrict density calculations to relevant atoms using precise mask expressions, avoiding unnecessary calculations on non-contributing species.

3. **Frame Subsampling**: For equilibrium properties, analyze representative subsets rather than full trajectories, reducing computational cost while maintaining statistical quality.

4. **Parallel Execution**: Leverage OpenMP or MPI parallelization for production analyses, particularly for high-resolution grids or long trajectories.

## Summary

CPPTRAJ's grid and density calculation capabilities provide a comprehensive toolkit for spatial analysis of molecular dynamics trajectories. The modular architecture supports a wide range of analyses from simple atomic density maps to sophisticated thermodynamic decomposition via GIST. By understanding the available options for grid generation, density types, and output formats, researchers can extract quantitative insights into solvation structure, molecular distributions, and energetic landscapes that complement other trajectory analysis methods.

For detailed information on related topics, refer to [GIST (Grid Inhomogeneous Solvation Theory)](23-gist-grid-inhomogeneous-solvation-theory) for advanced solvation thermodynamics, [Periodic Boundary Conditions and Imaging](9-periodic-boundary-conditions-and-imaging) for handling boundary effects in grid calculations, and [OpenMP Multi-threading](29-openmp-multi-threading) for parallel execution strategies.
