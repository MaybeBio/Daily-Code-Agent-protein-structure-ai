# Setting Up a Development Environment

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.github/CONTRIBUTING.md](.github/CONTRIBUTING.md)
- [.github/ISSUE_TEMPLATE/bug_report.md](.github/ISSUE_TEMPLATE/bug_report.md)
- [.github/ISSUE_TEMPLATE/feature_request.md](.github/ISSUE_TEMPLATE/feature_request.md)
- [.github/ISSUE_TEMPLATE/questions.md](.github/ISSUE_TEMPLATE/questions.md)
- [.github/PULL_REQUEST_TEMPLATE.md](.github/PULL_REQUEST_TEMPLATE.md)
- [.github/actions/build-src/action.yaml](.github/actions/build-src/action.yaml)
- [.github/actions/setup-deps/action.yaml](.github/actions/setup-deps/action.yaml)
- [.github/workflows/deploy.yaml](.github/workflows/deploy.yaml)
- [.github/workflows/gh-ci-cron.yaml](.github/workflows/gh-ci-cron.yaml)
- [.github/workflows/gh-ci.yaml](.github/workflows/gh-ci.yaml)
- [.github/workflows/labels.yaml](.github/workflows/labels.yaml)
- [.github/workflows/linters.yaml](.github/workflows/linters.yaml)
- [.readthedocs.yml](.readthedocs.yml)
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- [GOVERNANCE.md](GOVERNANCE.md)
- [azure-pipelines.yml](azure-pipelines.yml)
- [maintainer/conda/environment.yml](maintainer/conda/environment.yml)
- [package/AUTHORS](package/AUTHORS)
- [package/CHANGELOG](package/CHANGELOG)
- [package/LICENSE](package/LICENSE)
- [package/MDAnalysis/__init__.py](package/MDAnalysis/__init__.py)
- [package/MDAnalysis/lib/formats/include/trr_seek.h](package/MDAnalysis/lib/formats/include/trr_seek.h)
- [package/MDAnalysis/lib/formats/include/xdrfile.h](package/MDAnalysis/lib/formats/include/xdrfile.h)
- [package/MDAnalysis/lib/formats/include/xdrfile_trr.h](package/MDAnalysis/lib/formats/include/xdrfile_trr.h)
- [package/MDAnalysis/lib/formats/include/xdrfile_xtc.h](package/MDAnalysis/lib/formats/include/xdrfile_xtc.h)
- [package/MDAnalysis/lib/formats/include/xtc_seek.h](package/MDAnalysis/lib/formats/include/xtc_seek.h)
- [package/MDAnalysis/lib/formats/src/trr_seek.c](package/MDAnalysis/lib/formats/src/trr_seek.c)
- [package/MDAnalysis/lib/formats/src/xdrfile.c](package/MDAnalysis/lib/formats/src/xdrfile.c)
- [package/MDAnalysis/lib/formats/src/xdrfile_trr.c](package/MDAnalysis/lib/formats/src/xdrfile_trr.c)
- [package/MDAnalysis/lib/formats/src/xdrfile_xtc.c](package/MDAnalysis/lib/formats/src/xdrfile_xtc.c)
- [package/MDAnalysis/lib/formats/src/xtc_seek.c](package/MDAnalysis/lib/formats/src/xtc_seek.c)
- [package/MDAnalysis/version.py](package/MDAnalysis/version.py)
- [package/doc/sphinx/source/conf.py](package/doc/sphinx/source/conf.py)
- [package/pyproject.toml](package/pyproject.toml)
- [package/requirements.txt](package/requirements.txt)
- [package/setup.cfg](package/setup.cfg)
- [package/setup.py](package/setup.py)
- [testsuite/LICENSE](testsuite/LICENSE)
- [testsuite/MDAnalysisTests/__init__.py](testsuite/MDAnalysisTests/__init__.py)
- [testsuite/MDAnalysisTests/datafiles.py](testsuite/MDAnalysisTests/datafiles.py)
- [testsuite/pyproject.toml](testsuite/pyproject.toml)
- [testsuite/setup.py](testsuite/setup.py)

</details>



This document provides a comprehensive guide for setting up a development environment for contributing to MDAnalysis. It covers the installation of dependencies, building the source code, and configuring your environment for testing and development.

For information about running tests, see [Testing Framework](#6.2). For information about the continuous integration pipeline, see [Continuous Integration](#6.3).

## Overview of the Development Environment

MDAnalysis is a Python package with C extensions that requires specific dependencies for development. The project is organized into two main components:

1. **Main package (`package/`)**: Contains the core MDAnalysis library and its build system defined in `pyproject.toml` [package/pyproject.toml:1-114]().
2. **Test suite (`testsuite/`)**: Contains tests and test data, maintained as a separate package that must match the version of the main library [testsuite/MDAnalysisTests/__init__.py:24-33]().

### Code Entity Space to System Mapping

The following diagram maps high-level system components to specific code entities and directories in the repository.

Title: Repository Architecture Mapping
```mermaid
graph TD
    subgraph "MDAnalysis_Repository_Structure"
        [MainPackage]["Main Package (package/)"]
        [Tests]["Test Suite (testsuite/)"]
        [CI]["CI Configuration (.github/workflows/)"]
        [Docs]["Documentation (package/doc/sphinx/)"]
    end
    
    [MainPackage] --> [Core]["Core Library (MDAnalysis/)"]
    [MainPackage] --> [BuildSys]["Build System (pyproject.toml, setup.py)"]
    [Tests] --> [TestCode]["MDAnalysisTests/"]
    [Tests] --> [DataFiles]["datafiles.py (Data Manifest)"]
    [CI] --> [GHActions]["gh-ci.yaml (GitHub Actions)"]
    [CI] --> [Azure]["azure-pipelines.yml (Azure Pipelines)"]
    [Docs] --> [Conf]["conf.py (Sphinx Config)"]
```

Sources: [package/pyproject.toml:1-151](), [testsuite/MDAnalysisTests/__init__.py:24-106](), [.github/workflows/gh-ci.yaml:1-242](), [azure-pipelines.yml:1-140](), [package/doc/sphinx/source/conf.py:1-50]()

## Prerequisites

Before setting up the development environment, ensure you have the following installed:

- **Python 3.11 or newer**: MDAnalysis supports Python 3.11, 3.12, 3.13, and 3.14 [package/pyproject.toml:30-30](), [package/pyproject.toml:58-61]().
- **C Compiler**: Required to compile Cython extensions and external C code such as `libmdaxdr` (derived from `xdrfile` 1.1.4) [package/AUTHORS:304-309]().
- **Git**: For version control.

Sources: [package/pyproject.toml:30-61](), [.github/workflows/gh-ci.yaml:31-43](), [package/AUTHORS:294-309]()

## Obtaining the Source Code

Clone the MDAnalysis repository from GitHub:

```bash
git clone https://github.com/MDAnalysis/mdanalysis.git
cd mdanalysis
```

The repository uses a specific release versioning scheme (e.g., `2.11.0-dev0`) which is synchronized across `package/setup.py`, `package/MDAnalysis/version.py`, and `testsuite/MDAnalysisTests/__init__.py` [package/setup.py:61-61](), [package/MDAnalysis/version.py:70-70](), [testsuite/MDAnalysisTests/__init__.py:100-100]().

## Setting Up Dependencies

MDAnalysis has both required and optional dependencies.

### Core Dependencies

The following dependencies are required for a basic installation. Note that `numpy` is required both at build-time and run-time [package/pyproject.toml:3-16]().

| Dependency | Purpose | Minimum Version |
|------------|---------|----------------|
| `numpy` | Array operations | 1.26.0 [package/pyproject.toml:32-32]() |
| `Cython` | C extension compilation | 0.28 [package/pyproject.toml:4-4]() |
| `scipy` | Scientific computing | 1.5.0 [package/pyproject.toml:36-36]() |
| `GridDataFormats`| Grid data handling | 0.4.0 [package/pyproject.toml:33-33]() |
| `joblib` | Parallel computing | 0.12 [package/pyproject.toml:35-35]() |
| `tqdm` | Progress bars | 4.43.0 [package/pyproject.toml:38-38]() |
| `mda-xdrlib` | XDR file support | - [package/pyproject.toml:42-42]() |

### Optional Dependencies

MDAnalysis provides several optional dependency groups in `pyproject.toml` [package/pyproject.toml:69-102]():

- **`extra_formats`**: Includes `netCDF4`, `h5py`, `chemfiles`, `parmed`, `pytng`, `gsd`, and `rdkit` [package/pyproject.toml:70-81]().
- **`analysis`**: Includes `biopython`, `scikit-learn`, `networkx`, and legacy redirects like `waterdynamics` [package/pyproject.toml:82-91]().
- **`doc`**: Includes `sphinx`, `mdanalysis-sphinx-theme`, and `sphinxcontrib-bibtex` [package/pyproject.toml:92-99]().
- **`parallel`**: Includes `dask` [package/pyproject.toml:100-102]().

Sources: [package/pyproject.toml:31-102]()

## Build System Configuration

The build process is managed by `setuptools` and `Cython`.

### Cython Compilation Logic
The `package/setup.py` script handles the detection and configuration of Cython. It checks for a minimum version of `0.28` to support `cython.parallel` [package/setup.py:66-84]().

Title: Build and Installation Data Flow
```mermaid
graph LR
    subgraph "Build_Environment"
        [PyProj]["pyproject.toml"]
        [SetupPy]["setup.py"]
        [Config]["Config Class (setup.py)"]
    end

    subgraph "Compilation"
        [Cythonize]["Cython.Build.cythonize"]
        [MDAExt]["MDAExtension Class"]
        [CComp]["C Compiler"]
    end

    [PyProj] --> [SetupPy]
    [SetupPy] --> [Config]
    [Config] --> |"MDA_*" env vars| [MDAExt]
    [MDAExt] --> |"numpy.get_include()"| [Cythonize]
    [Cythonize] --> [CComp]
    [CComp] --> |"*.so / *.pyd"| [MDAnalysis_Package]["MDAnalysis Package"]
```

The `Config` class in `setup.py` allows developers to override build options using environment variables prefixed with `MDA_` (e.g., `MDA_CYTHON_TRACE_NOGIL`) [package/setup.py:100-137]().

Sources: [package/setup.py:66-190](), [package/pyproject.toml:1-18]()

## Building for Development

To set up an editable development environment, run the following from the repository root:

1. **Install MDAnalysis in editable mode**:
   ```bash
   pip install -e ./package
   ```
   This triggers the `MDAExtension` logic in `setup.py` to handle setup-time dependencies like `numpy` via `get_numpy_include` [package/setup.py:139-169](), [package/setup.py:170-190]().

2. **Install the test suite**:
   ```bash
   pip install -e ./testsuite
   ```
   The `testsuite/setup.py` ensures that the installed `MDAnalysis` version matches the `testsuite` version [testsuite/setup.py:78-84]().

Sources: [package/setup.py:139-190](), [testsuite/setup.py:76-88]()

## Verifying the Environment

The primary way to verify the environment is running the test suite using `pytest`.

```bash
pytest --pyargs MDAnalysisTests
```

For parallel execution, the `pytest-xdist` plugin is recommended [testsuite/MDAnalysisTests/__init__.py:38-51](). The test suite also relies on a manifest of data files provided by `MDAnalysisTestData` [testsuite/MDAnalysisTests/datafiles.py:24-37]().

Sources: [testsuite/MDAnalysisTests/__init__.py:38-51](), [testsuite/MDAnalysisTests/datafiles.py:24-37]()

## Continuous Integration and Automation

MDAnalysis uses multiple CI platforms to validate the development environment:

- **GitHub Actions (`gh-ci.yaml`)**: Primary CI for Linux and macOS, testing multiple Python versions (3.11-3.13, and experimental 3.14) and dependency configurations [ .github/workflows/gh-ci.yaml:23-77]().
- **Azure Pipelines (`azure-pipelines.yml`)**: Used for Windows-specific testing and wheel build verification, including ABI compatibility checks with older NumPy versions [azure-pipelines.yml:23-57](), [azure-pipelines.yml:95-102]().
- **cibuildwheel**: Used in `deploy.yaml` to build distribution wheels for PyPI across Linux, Windows, and macOS [.github/workflows/deploy.yaml:52-60]().

Sources: [.github/workflows/gh-ci.yaml:1-155](), [azure-pipelines.yml:1-140](), [.github/workflows/deploy.yaml:1-60]()

---