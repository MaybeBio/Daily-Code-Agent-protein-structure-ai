# Development

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



This document provides a comprehensive guide for developers contributing to the OpenFF toolkit repository. It covers the testing infrastructure, development workflows, environment setup, and quality assurance processes that ensure the toolkit maintains high standards across multiple platforms and toolkit combinations.

For information about the core toolkit architecture and design patterns, see [Core Architecture](#2). For user-focused guidance on installation and usage, see [Getting Started](#3.1).

## Overview

The OpenFF toolkit development process is built around a robust continuous integration system that validates code changes across multiple dimensions: operating systems, Python versions, and cheminformatics toolkit combinations. The development workflow ensures compatibility with both open-source (RDKit, AmberTools) and commercial (OpenEye) backend toolkits while maintaining comprehensive test coverage.

Sources: [.github/workflows/CI.yml:1-183](), [devtools/conda-envs/test_env.yaml:1-51]()

## Continuous Integration Architecture

The CI system forms the backbone of the development process, orchestrating testing across multiple configurations and ensuring code quality before integration.

### CI Workflow Matrix

```mermaid
graph TD
    A["CI Trigger"] --> B["Matrix Strategy"]
    B --> C["OS Matrix"]
    B --> D["Python Matrix"] 
    B --> E["Toolkit Matrix"]
    
    C --> C1["ubuntu-latest"]
    C --> C2["macos-latest"]
    
    D --> D1["Python 3.11"]
    D --> D2["Python 3.12"]
    D --> D3["Python 3.13"]
    
    E --> E1["RDKit + AmberTools"]
    E --> E2["OpenEye Only"]
    E --> E3["RDKit Only"]
    
    C1 --> F["Environment Setup"]
    C2 --> F
    D1 --> F
    D2 --> F
    D3 --> F
    E1 --> F
    E2 --> F
    E3 --> F
    
    F --> G["Test Execution"]
    G --> H["Quality Checks"]
    H --> I["Coverage Report"]
```

Sources: [.github/workflows/CI.yml:18-37](), [.github/workflows/CI.yml:49-70]()

### Environment Configuration System

```mermaid
graph LR
    A["Environment Files"] --> B["test_env.yaml"]
    A --> C["rdkit.yaml"]
    A --> D["openeye.yaml"]
    A --> E["rdkit-examples.yaml"]
    A --> F["openeye-examples.yaml"]
    
    B --> G["Full Testing"]
    C --> H["RDKit Testing"]
    D --> I["OpenEye Testing"]
    E --> J["RDKit Examples"]
    F --> K["OpenEye Examples"]
    
    G --> L["Core Test Suite"]
    H --> L
    I --> L
    J --> M["Example Validation"]
    K --> M
    
    L --> N["Unit Tests"]
    L --> O["Integration Tests"]
    M --> P["Notebook Tests"]
    M --> Q["Script Tests"]
```

Sources: [devtools/conda-envs/test_env.yaml:1-51](), [devtools/conda-envs/rdkit.yaml:1-42](), [devtools/conda-envs/openeye.yaml:1-53]()

## Testing Framework

The testing system is organized around comprehensive validation of molecular representations, force field parameterization, and toolkit integrations.

### Test Organization Structure

```mermaid
graph TD
    A["Test Suite"] --> B["Core Tests"]
    A --> C["Integration Tests"]
    A --> D["Example Tests"]
    A --> E["Documentation Tests"]
    
    B --> B1["test_molecule.py"]
    B --> B2["test_parameters.py"]
    B --> B3["test_forcefield.py"]
    B --> B4["test_topology.py"]
    
    C --> C1["test_toolkits.py"]
    C --> C2["test_links.py"]
    C --> C3["Cross-toolkit validation"]
    
    D --> D1["test_examples.py"]
    D --> D2["Notebook validation"]
    D --> D3["Script execution"]
    
    E --> E1["Docstring examples"]
    E --> E2["RST/MD doctests"]
    E --> E3["API documentation"]
    
    B1 --> F["Molecule serialization"]
    B1 --> G["SMILES parsing"]
    B1 --> H["Conformer handling"]
    
    B2 --> I["Parameter validation"]
    B2 --> J["Handler behavior"]
    B2 --> K["SMIRNOFF compliance"]
    
    B3 --> L["System creation"]
    B3 --> M["Force assignment"]
    B3 --> N["Charge methods"]
```

Sources: [openff/toolkit/_tests/test_molecule.py:1-50](), [openff/toolkit/_tests/test_parameters.py:1-50](), [openff/toolkit/_tests/test_forcefield.py:1-50]()

### Test Execution Pipeline

```mermaid
graph LR
    A["pytest"] --> B["PYTEST_ARGS"]
    B --> C["-r fE --tb=short -nauto"]
    C --> D["Test Discovery"]
    
    D --> E["Unit Tests"]
    D --> F["Integration Tests"]
    D --> G["Slow Tests"]
    
    E --> H["Fast Validation"]
    F --> I["Toolkit Integration"]
    G --> J["--runslow marker"]
    
    H --> K["Coverage Collection"]
    I --> K
    J --> K
    
    K --> L["COV"]
    L --> M["--cov=openff/toolkit/"]
    M --> N["coverage.xml"]
    
    N --> O["Codecov Upload"]
```

Sources: [.github/workflows/CI.yml:41-42](), [.github/workflows/CI.yml:149-158](), [.github/workflows/CI.yml:176-182]()

## Environment Management

The development environment system supports multiple toolkit combinations and testing scenarios through carefully configured conda environments.

### Dependency Resolution Matrix

| Environment | RDKit | OpenEye | AmberTools | Purpose |
|-------------|--------|---------|------------|---------|
| `test_env.yaml` | ✓ | ✓ | ✓ | Full testing matrix |
| `rdkit.yaml` | ✓ | ✗ | ✓ | RDKit-only validation |
| `openeye.yaml` | ✗ | ✓ | ✗ | OpenEye-only validation |
| `rdkit-examples.yaml` | ✓ | ✗ | ✓ | Example notebooks (RDKit) |
| `openeye-examples.yaml` | ✗ | ✓ | ✗ | Example notebooks (OpenEye) |

Sources: [devtools/conda-envs/test_env.yaml:25-31](), [devtools/conda-envs/rdkit.yaml:25-27](), [devtools/conda-envs/openeye.yaml:26-26]()

### Toolkit Validation System

```mermaid
graph TD
    A["Toolkit Setup"] --> B["Environment Variables"]
    B --> C["TOOLKIT_CHECKS"]
    B --> D["PACKAGES_TO_REMOVE"]
    
    C --> E["RDKIT_AVAILABLE"]
    C --> F["OPENEYE_AVAILABLE"]
    
    D --> G["Package Removal"]
    G --> H["micromamba remove --force"]
    
    E --> I["Validation Check"]
    F --> I
    I --> J["python -c 'from openff.toolkit.utils.toolkits import ...'"]
    
    J --> K["Assert Available"]
    J --> L["Assert Not Available"]
    
    K --> M["Test Execution"]
    L --> M
```

Sources: [.github/workflows/CI.yml:109-122](), [.github/workflows/CI.yml:97-103]()

## Quality Assurance Pipeline

The quality assurance system ensures code correctness, style compliance, and comprehensive validation across all supported configurations.

### Code Quality Checks

```mermaid
graph LR
    A["Code Quality"] --> B["Type Checking"]
    A --> C["Test Coverage"]
    A --> D["Link Validation"]
    A --> E["Documentation Tests"]
    
    B --> B1["mypy -p openff.toolkit"]
    C --> C1["pytest --cov"]
    D --> D1["test_links.py"]
    E --> E1["doctest-glob"]
    
    B1 --> F["Static Analysis"]
    C1 --> G["Coverage Report"]
    D1 --> H["URL Validation"]
    E1 --> I["Example Validation"]
    
    F --> J["Type Safety"]
    G --> K["codecov/codecov-action"]
    H --> L["Documentation Integrity"]
    I --> M["Code Snippet Testing"]
```

Sources: [.github/workflows/CI.yml:140-147](), [.github/workflows/CI.yml:136-138](), [.github/workflows/CI.yml:159-175]()

### Testing Specialization

```mermaid
graph TD
    A["Specialized Testing"] --> B["Examples Workflow"]
    A --> C["Beta/RC Testing"]
    A --> D["Conda Testing"]
    A --> E["Installer Testing"]
    
    B --> B1[".github/workflows/examples.yml"]
    C --> C1[".github/workflows/beta_rc.yaml"]
    D --> D2[".github/workflows/conda.yml"]
    E --> E1[".github/workflows/installer.yml"]
    
    B1 --> F["Notebook Validation"]
    B1 --> G["Script Execution"]
    
    C1 --> H["RC Channel Testing"]
    C1 --> I["Beta Dependency Testing"]
    
    D2 --> J["Release Validation"]
    D2 --> K["Conda Package Testing"]
    
    E1 --> L["Single-File Installer"]
    E1 --> M["Standalone Distribution"]
```

Sources: [.github/workflows/examples.yml:1-140](), [.github/workflows/beta_rc.yaml:1-87](), [.github/workflows/conda.yml:1-132](), [.github/workflows/installer.yml:1-112]()

## Development Workflow

The development process integrates multiple validation stages to ensure code quality and compatibility across the supported ecosystem.

### Contribution Pipeline

```mermaid
graph LR
    A["Code Changes"] --> B["Pre-commit Hooks"]
    B --> C["Local Testing"]
    C --> D["Pull Request"]
    
    D --> E["CI Triggers"]
    E --> F["Matrix Testing"]
    F --> G["Quality Checks"]
    
    G --> H["Unit Tests"]
    G --> I["Integration Tests"]
    G --> J["Example Tests"]
    
    H --> K["Core Validation"]
    I --> L["Toolkit Integration"]
    J --> M["Documentation Validation"]
    
    K --> N["Coverage Analysis"]
    L --> N
    M --> N
    
    N --> O["Merge Approval"]
```

Sources: [.github/workflows/CI.yml:4-11](), [.github/workflows/examples.yml:4-11]()

### Package Installation Process

```mermaid
graph TD
    A["Installation Steps"] --> B["Environment Setup"]
    B --> C["micromamba remove --force openff-toolkit"]
    C --> D["python -m pip install ."]
    
    D --> E["Test Plugin Installation"]
    E --> F["python -m pip install utilities/test_plugins"]
    
    F --> G["Toolkit Validation"]
    G --> H["Check installed toolkits"]
    G --> I["Check uninstalled toolkits"]
    
    H --> J["TOOLKIT_CHECKS loop"]
    I --> K["PACKAGES_TO_REMOVE validation"]
    
    J --> L["Assert toolkit availability"]
    K --> M["Assert toolkit absence"]
    
    L --> N["Test Execution"]
    M --> N
```

Sources: [.github/workflows/CI.yml:84-96](), [.github/workflows/CI.yml:94-96](), [.github/workflows/CI.yml:109-122]()

This development infrastructure ensures that the OpenFF toolkit maintains high quality standards while supporting a diverse ecosystem of cheminformatics backends and deployment environments. The comprehensive testing matrix validates functionality across all supported configurations, while the quality assurance pipeline ensures code correctness and documentation integrity.

---