# Dependencies and Build System

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.github/workflows/lint_and_test.yaml](.github/workflows/lint_and_test.yaml)
- [.gitignore](.gitignore)
- [pyproject.toml](pyproject.toml)
- [src/atomworks/io/utils/ccd.py](src/atomworks/io/utils/ccd.py)
- [src/atomworks/io/utils/sequence.py](src/atomworks/io/utils/sequence.py)
- [src/atomworks/ml/encoding_definitions.py](src/atomworks/ml/encoding_definitions.py)
- [src/atomworks/ml/transforms/msa/_msa_constants.py](src/atomworks/ml/transforms/msa/_msa_constants.py)
- [tests/io/utils/test_sequence_maps.py](tests/io/utils/test_sequence_maps.py)
- [tests/io/utils/test_sequence_utils.py](tests/io/utils/test_sequence_utils.py)

</details>



This document covers the project dependencies, build configuration, and development toolchain for AtomWorks. It explains the package structure, dependency management, optional features, and the build system used to create distributable packages.

For information about testing and code quality practices, see [Code Quality and Testing](#5.2). For details about the CI/CD pipeline implementation, see [CI/CD Pipeline](#5.3).

## Core Dependencies

AtomWorks is built on several foundational scientific computing and bioinformatics libraries. The core dependencies provide essential functionality for molecular data processing and analysis.

### Primary Dependencies

The project's core dependencies are defined in the `dependencies` section of [pyproject.toml:24-44]():

```mermaid
graph TB
    subgraph "Core Scientific Stack"
        numpy["numpy>=1.25.0,<3<br/>Linear algebra & arrays"]
        scipy["scipy>=1.13.1,<2<br/>Scientific computing"]
        pandas["pandas>=2.2,<2.4<br/>Data manipulation"]
        pyarrow["pyarrow==17.0.0<br/>Columnar data format"]
    end
    
    subgraph "Bioinformatics Libraries"
        biotite["biotite>=1.3.0,<2<br/>Protein structure analysis"]
        hydride["hydride>=1.2.3,<2<br/>Hydrogen addition"]
        rdkit["rdkit>=2024.3.5,<2025.9<br/>Cheminformatics"]
    end
    
    subgraph "Visualization & Tools"
        py3dmol["py3Dmol>=2.2.1,<3<br/>3D molecular visualization"]
        pymol["pymol-remote>=0.0.5<br/>Remote PyMOL access"]
    end
    
    subgraph "System & Performance"
        cython["cython>=3.0.0,<4<br/>C extensions compiler"]
        cytoolz["cytoolz>=0.12.3,<1<br/>Functional programming"]
        tqdm["tqdm>=4.65.0,<5<br/>Progress bars"]
        typer["typer>=0.12.5,<1<br/>CLI framework"]
    end
    
    numpy --> biotite
    numpy --> rdkit
    scipy --> rdkit
    pandas --> pyarrow
    cython --> cytoolz
```

Sources: [pyproject.toml:24-44]()

### Key Dependency Relationships

The `biotite` library serves as the foundation for molecular structure handling throughout AtomWorks. It provides the `AtomArray` data structure that is central to the data processing pipeline, as seen in functions like `parse()` in the core parser system.

The `rdkit` library enables small molecule processing and cheminformatics functionality, particularly for handling SMILES strings and molecular descriptors. Integration points are visible in [src/atomworks/io/utils/sequence.py]() and related conversion utilities.

Sources: [src/atomworks/io/utils/ccd.py:8-13](), [src/atomworks/io/utils/sequence.py:11-32]()

## Optional Dependencies

AtomWorks provides several optional dependency groups to support different use cases without requiring all dependencies for basic functionality.

### Machine Learning Dependencies

```mermaid
graph LR
    subgraph "atomworks[ml]"
        torch["torch>=2.2.0,<2.8<br/>Deep learning framework"]
        einops["einops>=0.7.0,<1<br/>Tensor operations"]
    end
    
    subgraph "ML Pipeline Components"
        transforms["atomworks.ml.transforms<br/>Data transformations"]
        encodings["atomworks.ml.encoding_definitions<br/>Token encodings"]
        datasets["atomworks.ml.datasets<br/>Data loading"]
    end
    
    torch --> transforms
    torch --> datasets
    einops --> transforms
    encodings --> transforms
```

The ML dependencies are defined in [pyproject.toml:47-51]() and enable the complete machine learning pipeline functionality documented in the `atomworks.ml` module.

Sources: [pyproject.toml:47-51](), [src/atomworks/ml/encoding_definitions.py:1-30]()

### Development Dependencies

The development dependency group includes tools for code quality, testing, and documentation:

| Category | Dependencies | Purpose |
|----------|-------------|---------|
| Code Quality | `ruff==0.8.3` | Linting and formatting |
| Testing | `pytest>=8.2.0`, `pytest-testmon`, `pytest-xdist`, `pytest-dotenv`, `pytest-cov`, `pytest-benchmark` | Test framework and plugins |
| Documentation | `sphinx>=8.0.0`, `sphinx-gallery`, `pydata-sphinx-theme`, `matplotlib` | Documentation generation |

Sources: [pyproject.toml:58-75]()

### Specialized Dependencies

- **OpenBabel**: `openbabel-wheel==3.1.1.22` for additional chemical file format support
- **Native uv Compatibility**: Dependency groups are duplicated in [pyproject.toml:77-82]() for compatibility with the `uv` package manager

Sources: [pyproject.toml:53-82]()

## Build System Configuration

AtomWorks uses a modern Python build system based on `hatchling` with version control integration.

### Build Backend Configuration

```mermaid
graph TB
    subgraph "Build System"
        requires["Build Requirements<br/>hatchling, hatch-vcs"]
        backend["Build Backend<br/>hatchling.build"]
        metadata["Metadata Configuration<br/>allow-direct-references"]
    end
    
    subgraph "Package Structure"
        src_atomworks["src/atomworks/<br/>Core library"]
        src_cli["src/atomworks_cli/<br/>CLI commands"]
        build_packages["Build Packages<br/>Both included"]
    end
    
    subgraph "Entry Points"
        cli_script["atomworks script<br/>atomworks_cli.__main__:main"]
    end
    
    requires --> backend
    backend --> build_packages
    src_atomworks --> build_packages
    src_cli --> build_packages
    build_packages --> cli_script
```

The build configuration is defined in [pyproject.toml:93-105]() and uses the source layout pattern where code is organized under a `src/` directory.

Sources: [pyproject.toml:93-105]()

### Package Metadata

The project metadata includes comprehensive classification and dependency information:

- **Target Python Version**: `>=3.12` as specified in [pyproject.toml:6]()
- **License**: BSD License as indicated in [pyproject.toml:21]()
- **Platform Support**: Linux, macOS, and Windows as listed in [pyproject.toml:15-17]()
- **CLI Entry Point**: The `atomworks` command is registered in [pyproject.toml:89-90]()

Sources: [pyproject.toml:1-23](), [pyproject.toml:89-90]()

## Development Tools Configuration

AtomWorks includes comprehensive configuration for development tools to maintain code quality and consistency.

### Code Formatting and Linting

The project uses `ruff` for both linting and formatting, configured in [pyproject.toml:108-219]():

```mermaid
graph TB
    subgraph "Ruff Configuration"
        format_config["Format Configuration<br/>line-length: 120<br/>quote-style: double<br/>indent-style: space"]
        lint_rules["Lint Rules<br/>E, F, W: pycodestyle<br/>I: isort<br/>N: pep8-naming<br/>UP, B, C4, SIM: quality"]
        ignore_rules["Ignored Rules<br/>B006, D203, D212<br/>NPY002, E501, etc."]
    end
    
    subgraph "File-Specific Rules"
        init_files["__init__.py<br/>Ignore F401 (unused imports)"]
        test_files["tests/*<br/>Ignore D, E, RUF, ANN"]
        docs_files["docs/**/*.py<br/>Ignore E402"]
    end
    
    format_config --> lint_rules
    lint_rules --> ignore_rules
    ignore_rules --> init_files
    ignore_rules --> test_files
    ignore_rules --> docs_files
```

Sources: [pyproject.toml:108-219]()

### Testing Configuration

The testing setup uses `pytest` with multiple plugins configured in [pyproject.toml:222-233]():

- **Test Discovery**: Tests are located in the `tests/` directory
- **Import Mode**: Uses `importlib` for better module isolation
- **Python Path**: Includes both `src/atomworks` and `tests` directories
- **Custom Markers**: Defines markers for internet-required tests, slow tests, and infrastructure-specific tests

Sources: [pyproject.toml:222-233]()

### Coverage Configuration

Code coverage is configured in [pyproject.toml:235-253]() with:
- **Parallel Execution**: Enabled for multi-process test runs
- **Source Tracking**: Monitors the `src/atomworks` directory
- **Exclusions**: Omits version files, tests, and `__init__.py` files from coverage

Sources: [pyproject.toml:235-253]()

## CI/CD Integration

The project's continuous integration system is implemented through GitHub Actions, with the main workflow defined in [.github/workflows/lint_and_test.yaml]().

### Workflow Structure

```mermaid
graph TB
    subgraph "CI Triggers"
        push_main["Push to main/production"]
        pr_branches["PRs to main/dev/staging"]
        pr_target["PR ready_for_review"]
    end
    
    subgraph "CI Jobs"
        lint["Lint Job<br/>ruff format & check"]
        test_github["Test (GitHub)<br/>Ubuntu runners"]
        test_digs["Test (DIGS)<br/>Internal infrastructure"]
    end
    
    subgraph "Test Environment Setup"
        python_setup["Python 3.12 setup"]
        uv_install["uv dependency installation"]
        test_data["atomworks setup tests"]
    end
    
    push_main --> lint
    pr_branches --> lint
    pr_target --> lint
    lint --> test_github
    lint --> test_digs
    python_setup --> uv_install
    uv_install --> test_data
    test_data --> test_github
```

### Dependency Installation Strategy

The CI pipeline uses `uv` for fast dependency installation as shown in [.github/workflows/lint_and_test.yaml:96-103]():

```bash
uv pip install -e ".[ml,openbabel,dev]" --system
```

This installs AtomWorks in editable mode with all optional dependencies, ensuring comprehensive testing of the full feature set.

Sources: [.github/workflows/lint_and_test.yaml:96-103]()

### Test Execution

The pipeline runs different test configurations:
- **GitHub Runners**: Standard tests excluding slow benchmarks
- **DIGS Infrastructure**: Full test suite including infrastructure-specific tests
- **Parallel Execution**: Uses `pytest-xdist` for faster test execution when multiple CPUs are available

Sources: [.github/workflows/lint_and_test.yaml:109-124]()

## Package Distribution

AtomWorks is configured for distribution through standard Python packaging channels with metadata defined for PyPI compatibility.

### Project URLs and Metadata

The project defines several important URLs in [pyproject.toml:84-87]():
- **Homepage**: Points to the documentation site
- **Repository**: GitHub repository URL
- **Documentation**: Comprehensive documentation site

### Version Management

The project uses `hatch-vcs` for version management, allowing automatic version determination from Git tags and commit history.

Sources: [pyproject.toml:84-87](), [pyproject.toml:94]()

---