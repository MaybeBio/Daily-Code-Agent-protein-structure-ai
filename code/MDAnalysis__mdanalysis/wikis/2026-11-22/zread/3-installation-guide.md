

MDAnalysis is a powerful Python library for analyzing molecular dynamics simulations. This guide provides comprehensive instructions for installing MDAnalysis on your system, covering various installation methods and requirements.

## Prerequisites

Before installing MDAnalysis, ensure your system meets the following requirements:

- **Python version**: MDAnalysis requires Python 3.10 or higher. The library is compatible with Python 3.10, 3.11, 3.12, and 3.13. You can check your Python version by running `python --version` in your terminal.

- **Operating System**: MDAnalysis supports POSIX systems (Linux), macOS, and Windows.

- **Compiler**: For installation from source, you'll need a C compiler (GCC on Linux, Xcode Command Line Tools on macOS, or Visual C++ Build Tools on Windows).

## Installation Methods

### Method 1: Installation via pip (Recommended for most users)

The simplest way to install MDAnalysis is using pip, Python's package installer. This method installs the latest stable release from the Python Package Index (PyPI).

```bash
pip install --upgrade MDAnalysis
```

If you plan to run the test cases and examples (recommended for developers and advanced users), also install the test suite:

```bash
pip install --upgrade MDAnalysisTests
python -c 'import MDAnalysisTests; MDAnalysisTests.run()'
```

Note: The full test suite can take a considerable amount of time to complete.

Sources: [package/INSTALL#L12-L17](package/INSTALL#L12-L17), [package/pyproject.toml#L50-51](package/pyproject.toml#L50-51)

> [!TIP]
> If you encounter permission errors during installation, consider using a virtual environment or the `--user` flag: `pip install --user MDAnalysis`

### Method 2: Installation via conda (Recommended for scientific computing environments)

Conda is particularly well-suited for scientific computing environments. To install MDAnalysis using conda:

```bash
conda config --add channels MDAnalysis
conda install mdanalysis
```

To upgrade to the latest stable release:

```bash
conda update mdanalysis
```

*Important note*: The conda packages currently only support serial calculations. If you plan to use the parallel OpenMP algorithms, you need to install MDAnalysis with pip and ensure you have a working OpenMP installation on your system.

Sources: [package/INSTALL#L20-L26](package/INSTALL#L20-L26), [maintainer/conda/environment.yml#L1-L5](maintainer/conda/environment.yml#L1-L5)

### Method 3: Installation from source

For developers or those who need the latest development version, you can install MDAnalysis directly from the source code:

```bash
git clone https://github.com/MDAnalysis/mdanalysis.git
cd mdanalysis
pip install .
```

For a development installation (which creates an editable link to your source code):

```bash
pip install -e .
```

The development installation allows you to modify the code and immediately see the changes without reinstalling the package.

Sources: [package/INSTALL#L72-L74](package/INSTALL#L72-L74), [README.rst#L53-L54](README.rst#L53-L54)

> [!TIP]
> When installing from source, ensure you have the build dependencies installed first. See the "Dependencies" section for details.

## Dependencies

MDAnalysis requires several Python packages to function correctly. These are automatically installed when using pip or conda, but it's useful to be aware of them:

### Required Dependencies

| Package | Minimum Version | Purpose |
|---------|---------------|---------|
| numpy | 1.23.2 | Core array operations and numerical computing |
| GridDataFormats | 0.4.0 | Handling grid-based data formats |
| mmtf-python | 1.0.0 | Macromolecular Transmission Format support |
| joblib | 0.12 | Parallel processing utilities |
| scipy | 1.5.0 | Scientific computing library |
| matplotlib | 1.5.1 | Plotting and visualization |
| tqdm | 4.43.0 | Progress bars for iterative operations |
| threadpoolctl | - | Thread pool utilities |
| packaging | - | Package version handling |
| filelock | - | File locking utilities |
| mda-xdrlib | - | Handling XDR format files |

Sources: [package/pyproject.toml#L54-65](package/pyproject.toml#L54-65), [package/requirements.txt#L1-25](package/requirements.txt#L1-25)

### Optional Dependencies

MDAnalysis offers several optional feature sets that you can install based on your specific needs:

#### Enhanced File Format Support

To install additional file format support:

```bash
pip install MDAnalysis[extra_formats]
```

This installs:
- `netCDF4>=1.0` - For NetCDF trajectory files
- `h5py>=2.10` - For HDF5-based formats
- `chemfiles>=0.10` - Multi-format chemistry file support
- `parmed` - Parameter/topology editor
- `pyedr>=0.7.0` - For EDM file format
- `pytng>=0.2.3` - For TNG trajectory files
- `gsd>3.0.0` - For GSD format
- `rdkit>=2022.09.1` - Cheminformatics toolkit

Sources: [package/pyproject.toml#L67-76](package/pyproject.toml#L67-76)

#### Advanced Analysis Features

For additional analysis capabilities:

```bash
pip install MDAnalysis[analysis]
```

This installs:
- `biopython>=1.80` - Bioinformatics utilities
- `seaborn` - Statistical data visualization
- `scikit-learn` - Machine learning algorithms
- `tidynamics>=1.0.0` - Time series analysis
- `networkx>=2.0` - Graph analysis
- `waterdynamics` - Water dynamics analysis
- `pathsimanalysis` - Path similarity analysis
- `mdahole2` - Hole analysis for membrane proteins

Sources: [package/pyproject.toml#L78-87](package/pyproject.toml#L78-87)

#### Parallel Processing

For parallel processing capabilities:

```bash
pip install MDAnalysis[parallel]
```

This installs:
- `dask` - Parallel computing library

Sources: [package/pyproject.toml#L89-91](package/pyproject.toml#L89-91)

### Build Dependencies

If you're building MDAnalysis from source, you'll need these additional packages:

| Package | Minimum Version | Purpose |
|---------|---------------|---------|
| Cython | 0.28 | C-extension generation |
| packaging | - | Package version handling |
| numpy | 2.0.0 | For building against the NumPy API |
| setuptools | 40.9.0 | Build system |
| wheel | - | Wheel package format |

Sources: [package/pyproject.toml#L5-13](package/pyproject.toml#L5-13)

## Verifying Installation

After installation, you can verify that MDAnalysis is working correctly by running the following Python code:

```python
import MDAnalysis as mda
print(f"MDAnalysis version: {mda.__version__}")

# Create a simple Universe
u = mda.Universe.empty(100, trajectory=True)
print(f"Created Universe with {u.atoms.n_atoms} atoms")
```

This should output the MDAnalysis version number (e.g., "2.10.0-dev0") and confirm that you can create a Universe object. If this runs without errors, your installation is working correctly.

Sources: [package/MDAnalysis/version.py#L64](package/MDAnalysis/version.py#L64), [README.rst#L30-L34](README.rst#L30-L34)

## Troubleshooting

### Common Installation Issues

1. **ImportError: No module named 'MDAnalysis'**: This typically indicates that the package wasn't installed correctly. Try reinstalling with `pip install --force-reinstall MDAnalysis`.

2. **Compilation errors when installing from source**: Make sure you have the necessary compilers installed. On Ubuntu/Debian, you can install them with `sudo apt-get install build-essential`.

3. **Permission errors**: Use a virtual environment or install with the `--user` flag to avoid system-wide permission issues.

### Getting Help

If you encounter any problems during installation:

1. Check the [Installation page on the MDAnalysis website](https://www.mdanalysis.org/pages/installation_quick_start/) for the most up-to-date instructions.

2. Search the [GitHub Discussions](https://github.com/MDAnalysis/mdanalysis/discussions/categories/installation) to see if others have encountered and solved similar issues.

3. When posting for help, include:
   - Your MDAnalysis version (if attempting to upgrade)
   - All commands you typed to install the package
   - The full error output
   - Your operating system (e.g., Ubuntu 22.04)
   - Your Python version (output from `python --version`)

Sources: [package/INSTALL#L42-L56](package/INSTALL#L42-L56), [README.rst#L108-L111](README.rst#L108-L111)

### Next Steps

Once you have successfully installed MDAnalysis, we recommend exploring the [Basic Usage Tutorial](4-basic-usage-tutorial) to get started with loading and analyzing molecular dynamics trajectories.