# Testing Framework

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.github/workflows/CI.yml](.github/workflows/CI.yml)
- [.github/workflows/beta_rc.yaml](.github/workflows/beta_rc.yaml)
- [.github/workflows/conda.yml](.github/workflows/conda.yml)
- [.github/workflows/examples.yml](.github/workflows/examples.yml)
- [.github/workflows/installer.yml](.github/workflows/installer.yml)
- [devtools/conda-envs/conda.yaml](devtools/conda-envs/conda.yaml)
- [devtools/conda-envs/conda_oe.yaml](devtools/conda-envs/conda_oe.yaml)
- [devtools/conda-envs/openeye-examples.yaml](devtools/conda-envs/openeye-examples.yaml)
- [devtools/conda-envs/openeye.yaml](devtools/conda-envs/openeye.yaml)
- [devtools/conda-envs/rdkit-examples.yaml](devtools/conda-envs/rdkit-examples.yaml)
- [devtools/conda-envs/rdkit.yaml](devtools/conda-envs/rdkit.yaml)
- [devtools/conda-envs/test_env.yaml](devtools/conda-envs/test_env.yaml)
- [docs/typing.rst](docs/typing.rst)
- [openff/toolkit/_tests/test_forcefield.py](openff/toolkit/_tests/test_forcefield.py)
- [openff/toolkit/_tests/test_molecule.py](openff/toolkit/_tests/test_molecule.py)
- [openff/toolkit/_tests/test_parameters.py](openff/toolkit/_tests/test_parameters.py)

</details>



This document describes the comprehensive testing infrastructure used to ensure code quality and reliability in the OpenFF toolkit. It covers the automated testing pipeline, test environment management, test organization, and how to run tests during development.

For information about building and packaging the toolkit, see [Build and Packaging](#4.2). For details on developing custom plugins, see [Plugin Development](#4.3).

## Overview

The OpenFF toolkit employs a multi-tiered testing strategy that validates functionality across different platforms, Python versions, and cheminformatics toolkit combinations. The testing framework ensures compatibility with various dependency configurations and validates both core functionality and real-world usage scenarios.

```mermaid
graph TB
    subgraph "Testing Infrastructure"
        A["GitHub Actions CI"] --> B["Test Matrix Execution"]
        B --> C["Core Unit Tests"]
        B --> D["Integration Tests"] 
        B --> E["Example Validation"]
        B --> F["Documentation Tests"]
    end
    
    subgraph "Test Environments"
        G["test_env.yaml<br/>Full Environment"] 
        H["rdkit.yaml<br/>RDKit Only"]
        I["openeye.yaml<br/>OpenEye Only"] 
        J["examples environments"]
    end
    
    subgraph "Test Categories"
        K["openff/toolkit/_tests/<br/>Core Tests"]
        L["Notebook Tests<br/>docs/ and examples/"]
        M["Docstring Tests<br/>API Documentation"]
        N["Plugin Tests<br/>utilities/test_plugins"]
    end
    
    A --> G
    A --> H  
    A --> I
    A --> J
    
    C --> K
    E --> L
    F --> M
    E --> N
```

**Testing Infrastructure Overview**

Sources: [.github/workflows/CI.yml:1-183](), [devtools/conda-envs/test_env.yaml:1-51](), [openff/toolkit/_tests/test_molecule.py:1-50]()

## CI/CD Pipeline Architecture

The continuous integration system uses GitHub Actions to orchestrate testing across multiple dimensions of the software stack. The primary workflow is defined in `CI.yml` and executes a comprehensive test matrix.

```mermaid
graph LR
    subgraph "Trigger Events"
        A["Push to main"] 
        B["Pull Request"]
        C["Scheduled Run<br/>Daily 00:21 UTC"]
    end
    
    subgraph "Test Matrix"
        D["OS Matrix<br/>ubuntu-latest<br/>macos-latest"]
        E["Python Matrix<br/>3.11, 3.12, 3.13"]
        F["Toolkit Matrix<br/>RDKit + OpenEye<br/>RDKit Only<br/>OpenEye Only"]
    end
    
    subgraph "Test Execution Steps"
        G["Environment Setup<br/>micromamba"]
        H["Package Installation<br/>pip install ."]
        I["Test Plugin Install<br/>utilities/test_plugins"]
        J["Toolkit Verification"]
        K["Core Test Suite<br/>pytest"]
        L["Coverage Report<br/>codecov"]
    end
    
    A --> D
    B --> D  
    C --> D
    
    D --> G
    E --> G
    F --> G
    
    G --> H
    H --> I
    I --> J
    J --> K
    K --> L
```

**CI/CD Pipeline Flow**

The test matrix systematically excludes invalid combinations, such as configurations with neither RDKit nor OpenEye, and limits OpenEye testing to Python 3.13 due to licensing constraints.

Sources: [.github/workflows/CI.yml:18-43](), [.github/workflows/CI.yml:49-104](), [.github/workflows/CI.yml:149-158]()

## Test Environment Management

The testing framework uses conda environment files to manage dependencies across different testing scenarios. Each environment is tailored for specific testing needs and toolkit combinations.

| Environment File | Purpose | Key Dependencies |
|------------------|---------|------------------|
| `test_env.yaml` | Full testing with all toolkits | `rdkit`, `openeye-toolkits`, `ambertools`, `pytest=8` |
| `rdkit.yaml` | RDKit-only testing | `rdkit`, `ambertools`, `mypy=1.15` |
| `openeye.yaml` | OpenEye-only testing | `openeye-toolkits`, type stubs |
| `rdkit-examples.yaml` | Example testing with RDKit | Additional dependencies for notebooks |
| `openeye-examples.yaml` | Example testing with OpenEye | GROMACS, visualization tools |

```mermaid
graph TB
    subgraph "Environment Selection Logic"
        A["Matrix Configuration"] --> B{"Toolkit Selection"}
        B -->|"rdkit=true, openeye=true"| C["test_env.yaml<br/>ENVFILE=test_env"]
        B -->|"rdkit=false, openeye=true"| D["openeye.yaml<br/>ENVFILE=openeye"] 
        B -->|"rdkit=true, openeye=false"| E["rdkit.yaml<br/>ENVFILE=rdkit"]
    end
    
    subgraph "Package Removal"
        F["Remove Conflicting Packages"] --> G["micromamba remove --force"]
        G --> H["Toolkit Verification"]
    end
    
    C --> F
    D --> F
    E --> F
```

**Test Environment Selection and Configuration**

Sources: [.github/workflows/CI.yml:49-71](), [devtools/conda-envs/test_env.yaml:1-51](), [devtools/conda-envs/rdkit.yaml:1-42](), [devtools/conda-envs/openeye.yaml:1-53]()

## Test Categories and Organization

The test suite is organized into distinct categories that validate different aspects of the toolkit functionality:

```mermaid
graph TB
    subgraph "Core Unit Tests"
        A["test_molecule.py<br/>Molecule and Topology"]
        B["test_parameters.py<br/>SMIRNOFF Parameters"] 
        C["test_forcefield.py<br/>ForceField Engine"]
        D["test_toolkits.py<br/>Toolkit Integration"]
    end
    
    subgraph "Specialized Tests"
        E["test_examples.py<br/>Script Validation"]
        F["test_links.py<br/>URL Validation"]
        G["Plugin Tests<br/>utilities/test_plugins"]
    end
    
    subgraph "Documentation Tests" 
        H["Docstring Examples<br/>--doctest-modules"]
        I["RST/MD Code Blocks<br/>--doctest-glob"]
        J["Jupyter Notebooks<br/>--nbval-lax"]
    end
    
    subgraph "Integration Tests"
        K["System Creation<br/>OpenMM Integration"]
        L["File I/O<br/>Multiple Formats"]
        M["Parameterization<br/>End-to-End Workflows"]
    end
```

**Test Organization and Categories**

### Core Test Execution

The main test execution excludes certain test files that require special handling:

```bash
PYTEST_ARGS+=" --ignore=openff/toolkit/_tests/test_examples.py"
PYTEST_ARGS+=" --ignore=openff/toolkit/_tests/test_links.py"
python -m pytest -x --durations=20 $PYTEST_ARGS $COV openff/toolkit/_tests
```

Sources: [.github/workflows/CI.yml:150-158](), [openff/toolkit/_tests/test_molecule.py:1-100](), [openff/toolkit/_tests/test_parameters.py:1-50](), [openff/toolkit/_tests/test_forcefield.py:1-100]()

## Specialized Testing Workflows

Beyond the main CI pipeline, the toolkit includes specialized testing workflows for different scenarios:

### Example and Notebook Testing

The `examples.yml` workflow specifically validates example scripts and Jupyter notebooks:

```mermaid
graph LR
    subgraph "Example Testing Matrix"
        A["OS: ubuntu, macos"] --> B["Python: 3.11, 3.12"]
        B --> C["Toolkit: RDKit OR OpenEye<br/>(Not Both)"]
    end
    
    subgraph "Test Execution"
        D["Example Scripts<br/>test_examples.py"] 
        E["Jupyter Notebooks<br/>--nbval-lax"]
        F["Ignore Deprecated<br/>examples/deprecated"]
    end
    
    C --> D
    C --> E
    E --> F
```

**Example Testing Pipeline**

### Beta/RC Testing

The `beta_rc.yaml` workflow tests against pre-release versions of dependencies:

- Tests against conda-forge release candidate channels
- Validates compatibility with upcoming dependency versions
- Uses specific micromamba version (`1.5.10-0`) for stability

### Deployment Testing

The `conda.yml` workflow validates conda package installations:

- Tests installation from conda packages rather than source
- Verifies version matching between git tags and installed packages
- Validates toolkit availability in conda-installed environments

Sources: [.github/workflows/examples.yml:1-140](), [.github/workflows/beta_rc.yaml:1-87](), [.github/workflows/conda.yml:1-132]()

## Test Configuration and Quality Assurance

The testing framework includes several quality assurance mechanisms:

### Coverage Reporting
- Uses `pytest-cov` with `--cov=openff/toolkit/` 
- Uploads results to Codecov with token authentication
- Fails CI if coverage upload fails

### Type Checking
- MyPy validation runs on OpenEye-only builds (RDKit builds often have stub issues)
- Validates type annotations in the `openff.toolkit` package

### Performance Monitoring
- `--durations=20` flag reports the 20 slowest tests
- Helps identify performance regressions

### Parallel Execution
- Uses `pytest-xdist` with `-nauto` for parallel test execution
- Includes special handling for Pint cross-interaction issues

```mermaid
graph TB
    subgraph "Quality Gates"
        A["Type Checking<br/>mypy -p openff.toolkit"] --> B["Unit Tests<br/>pytest with coverage"]
        B --> C["Integration Tests<br/>Examples and Notebooks"] 
        C --> D["Link Validation<br/>test_links.py"]
        D --> E["Coverage Upload<br/>codecov"]
    end
    
    subgraph "Test Markers"
        F["@pytest.mark.slow<br/>Long-running tests"]
        G["@pytest.mark.wip<br/>Work in progress"]  
        H["@pytest.mark.xfail<br/>Expected failures"]
    end
    
    B --> F
    B --> G
    B --> H
```

**Quality Assurance Pipeline**

Sources: [.github/workflows/CI.yml:140-147](), [.github/workflows/CI.yml:176-183](), [.github/workflows/CI.yml:133-135]()

## Running Tests Locally

For local development, tests can be run using the same environment configurations as CI:

1. **Set up test environment:**
   ```bash
   micromamba env create -f devtools/conda-envs/test_env.yaml
   micromamba activate openff-toolkit-test
   ```

2. **Install toolkit in development mode:**
   ```bash
   pip install -e .
   ```

3. **Install test plugins:**
   ```bash
   pip install utilities/test_plugins
   ```

4. **Run specific test categories:**
   ```bash
   # Core unit tests
   pytest openff/toolkit/_tests/
   
   # With coverage
   pytest --cov=openff/toolkit/ openff/toolkit/_tests/
   
   # Examples only
   pytest openff/toolkit/_tests/test_examples.py
   
   # Notebooks
   pytest --nbval-lax docs/ examples/
   ```

The test framework supports various pytest markers for controlling test execution, including `@pytest.mark.slow` for time-intensive tests and `@pytest.mark.wip` for work-in-progress functionality.

Sources: [.github/workflows/CI.yml:84-96](), [devtools/conda-envs/test_env.yaml:32-43](), [openff/toolkit/_tests/test_molecule.py:175-236]()

---