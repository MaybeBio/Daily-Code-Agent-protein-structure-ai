# Build and Packaging

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
- [devtools/conda-envs/release-build.yaml](devtools/conda-envs/release-build.yaml)
- [devtools/conda-envs/test_env.yaml](devtools/conda-envs/test_env.yaml)

</details>



This document explains the build and packaging infrastructure for the OpenFF toolkit, including continuous integration workflows, environment management, testing matrices, and distribution processes. The system ensures code quality across multiple platforms, Python versions, and optional dependencies through automated testing and packaging.

For information about the actual testing framework and test organization, see [Testing Framework](#4.1). For plugin development and extension mechanisms, see [Plugin Development](#4.3).

## CI/CD Architecture

The OpenFF toolkit uses a comprehensive GitHub Actions-based CI/CD system that validates code across multiple dimensions: operating systems, Python versions, and optional toolkit dependencies.

```mermaid
graph TB
    subgraph "GitHub Actions Workflows"
        CI["CI.yml<br/>Primary testing workflow"]
        CONDA["conda.yml<br/>Conda package validation"]
        EXAMPLES["examples.yml<br/>Example notebook testing"]
        INSTALLER["installer.yml<br/>Single-file installer creation"]
        BETA["beta_rc.yaml<br/>Beta/RC dependency testing"]
    end
    
    subgraph "Trigger Events"
        PUSH["Push to main branch"]
        PR["Pull requests"]
        SCHEDULE["Nightly scheduled runs"]
        RELEASE["Release events"]
        MANUAL["Manual workflow dispatch"]
    end
    
    subgraph "Testing Matrix"
        OS["ubuntu-latest<br/>macos-latest"]
        PYTHON["Python 3.11, 3.12, 3.13"]
        RDKIT["RDKit true/false"]
        OPENEYE["OpenEye true/false"]
    end
    
    PUSH --> CI
    PR --> CI
    SCHEDULE --> CI
    PUSH --> EXAMPLES
    PR --> EXAMPLES
    SCHEDULE --> EXAMPLES
    RELEASE --> CONDA
    SCHEDULE --> CONDA
    MANUAL --> INSTALLER
    SCHEDULE --> BETA
    MANUAL --> BETA
    
    CI --> OS
    CI --> PYTHON
    CI --> RDKIT
    CI --> OPENEYE
```

The primary workflow excludes invalid combinations where both RDKit and OpenEye are disabled, and restricts OpenEye testing to Python 3.11 due to licensing constraints.

**Sources:** [.github/workflows/CI.yml:1-183](), [.github/workflows/conda.yml:1-132](), [.github/workflows/examples.yml:1-140](), [.github/workflows/installer.yml:1-112](), [.github/workflows/beta_rc.yaml:1-87]()

## Environment Management

The toolkit uses conda environment files to manage complex dependency combinations across different testing scenarios.

```mermaid
graph TB
    subgraph "Core Environment Files"
        TEST_ENV["test_env.yaml<br/>Full testing environment<br/>RDKit + OpenEye + AmberTools"]
        RDKIT_ENV["rdkit.yaml<br/>RDKit-only environment"]
        OPENEYE_ENV["openeye.yaml<br/>OpenEye-only environment"]
    end
    
    subgraph "Example Environment Files"
        RDKIT_EX["rdkit-examples.yaml<br/>RDKit + example dependencies"]
        OPENEYE_EX["openeye-examples.yaml<br/>OpenEye + example dependencies"]
    end
    
    subgraph "Deployment Environment Files"
        CONDA_DEPLOY["conda.yaml<br/>Conda package testing"]
        CONDA_OE["conda_oe.yaml<br/>Conda + OpenEye testing"]
        INSTALLER_ENV["installer.yaml<br/>Single-file installer"]
        RELEASE_BUILD["release-build.yaml<br/>Release building tools"]
    end
    
    subgraph "Common Dependencies"
        CORE["Core: numpy, networkx, openmm<br/>openff-forcefields, openff-units"]
        TESTING["Testing: pytest, pytest-cov<br/>pytest-xdist, nbval"]
        OPTIONAL["Optional: qcelemental, qcportal<br/>mdtraj, nglview"]
    end
    
    TEST_ENV --> CORE
    RDKIT_ENV --> CORE
    OPENEYE_ENV --> CORE
    RDKIT_EX --> CORE
    OPENEYE_EX --> CORE
    
    TEST_ENV --> TESTING
    RDKIT_ENV --> TESTING
    OPENEYE_ENV --> TESTING
    
    TEST_ENV --> OPTIONAL
    RDKIT_EX --> OPTIONAL
    OPENEYE_EX --> OPTIONAL
```

### Environment Configuration Matrix

| Environment | RDKit | OpenEye | AmberTools | Primary Use |
|-------------|-------|---------|------------|-------------|
| `test_env.yaml` | ✓ | ✓ | ✓ | Full CI testing |
| `rdkit.yaml` | ✓ | ✗ | ✓ | RDKit-only CI |
| `openeye.yaml` | ✗ | ✓ | ✗ | OpenEye-only CI |
| `rdkit-examples.yaml` | ✓ | ✗ | ✓ | Example notebooks |
| `openeye-examples.yaml` | ✗ | ✓ | ✗ | Example notebooks |
| `conda.yaml` | ✓ | ✗ | ✓ | Conda deployment |
| `conda_oe.yaml` | ✗ | ✓ | ✗ | Conda + OpenEye |

**Sources:** [devtools/conda-envs/test_env.yaml:1-53](), [devtools/conda-envs/rdkit.yaml:1-42](), [devtools/conda-envs/openeye.yaml:1-53](), [devtools/conda-envs/rdkit-examples.yaml:1-45](), [devtools/conda-envs/openeye-examples.yaml:1-44]()

## Testing Matrix and Workflow Logic

The CI system implements sophisticated logic to handle different toolkit combinations and their dependencies.

```mermaid
graph TB
    subgraph "Matrix Strategy"
        MATRIX_DEF["Strategy Matrix<br/>os: ubuntu-latest, macos-latest<br/>python-version: 3.11, 3.12, 3.13<br/>rdkit: true, false<br/>openeye: true, false"]
    end
    
    subgraph "Environment Selection Logic"
        CONDITION1["rdkit=true && openeye=true<br/>→ ENVFILE=test_env<br/>→ TOOLKIT_CHECKS=RDKIT OPENEYE"]
        CONDITION2["rdkit=false && openeye=true<br/>→ ENVFILE=openeye<br/>→ TOOLKIT_CHECKS=OPENEYE<br/>→ PACKAGES_TO_REMOVE=ambertools rdkit"]
        CONDITION3["rdkit=true && openeye=false<br/>→ ENVFILE=rdkit<br/>→ TOOLKIT_CHECKS=RDKIT<br/>→ PACKAGES_TO_REMOVE=openeye-toolkits"]
    end
    
    subgraph "Package Management"
        INSTALL["python -m pip install ."]
        REMOVE["micromamba remove --force<br/>openff-toolkit openff-toolkit-base"]
        SELECTIVE_REMOVE["Remove packages in PACKAGES_TO_REMOVE"]
        NAGL_REMOVE["Remove NAGL if no RDKit"]
    end
    
    subgraph "Validation Steps"
        TOOLKIT_CHECK["Check installed toolkits<br/>Assert toolkit availability"]
        TOOLKIT_UNCHECK["Check uninstalled toolkits<br/>Assert toolkit unavailability"]
        MYPY["mypy -p openff.toolkit<br/>Only with OpenEye-only builds"]
    end
    
    MATRIX_DEF --> CONDITION1
    MATRIX_DEF --> CONDITION2
    MATRIX_DEF --> CONDITION3
    
    CONDITION1 --> INSTALL
    CONDITION2 --> INSTALL
    CONDITION3 --> INSTALL
    
    INSTALL --> REMOVE
    REMOVE --> SELECTIVE_REMOVE
    SELECTIVE_REMOVE --> NAGL_REMOVE
    NAGL_REMOVE --> TOOLKIT_CHECK
    TOOLKIT_CHECK --> TOOLKIT_UNCHECK
    TOOLKIT_UNCHECK --> MYPY
```

The workflow implements several exclusion rules:
- Excludes combinations where both `rdkit=false` and `openeye=false`
- Restricts OpenEye testing to Python 3.11 only
- Conditionally runs MyPy type checking only on OpenEye-only builds due to RDKit stub issues

**Sources:** [.github/workflows/CI.yml:22-36](), [.github/workflows/CI.yml:49-122](), [.github/workflows/CI.yml:140-147]()

## Package Distribution

The toolkit supports multiple distribution mechanisms to accommodate different user needs and deployment scenarios.

```mermaid
graph TB
    subgraph "Source Code"
        REPO["GitHub Repository<br/>openforcefield/openff-toolkit"]
        RELEASE_TAG["Release Tags<br/>Version tagging"]
    end
    
    subgraph "Build Artifacts"
        WHEEL["Python Wheel<br/>pip installable"]
        CONDA_PKG["Conda Package<br/>conda installable"]
        SINGLE_INSTALLER["Single-file Installer<br/>Standalone executable"]
    end
    
    subgraph "Distribution Channels"
        PYPI["PyPI<br/>pip install openff-toolkit"]
        CONDA_FORGE["conda-forge<br/>conda install openff-toolkit"]
        GITHUB_RELEASES["GitHub Releases<br/>Installer downloads"]
    end
    
    subgraph "Validation Workflows"
        CONDA_VALIDATION["conda.yml<br/>Validates conda packages<br/>against latest releases"]
        INSTALLER_BUILD["installer.yml<br/>Creates and tests<br/>single-file installers"]
    end
    
    REPO --> RELEASE_TAG
    RELEASE_TAG --> WHEEL
    RELEASE_TAG --> CONDA_PKG
    RELEASE_TAG --> SINGLE_INSTALLER
    
    WHEEL --> PYPI
    CONDA_PKG --> CONDA_FORGE
    SINGLE_INSTALLER --> GITHUB_RELEASES
    
    CONDA_PKG --> CONDA_VALIDATION
    SINGLE_INSTALLER --> INSTALLER_BUILD
```

### Single-file Installer Process

The single-file installer workflow creates standalone executables that bundle the toolkit with all dependencies:

1. **Version Detection**: Automatically detects latest release tag using `git ls-remote`
2. **Constructor Integration**: Uses `toolkit-installer-constructor` repository for build configuration
3. **Build Process**: Generates platform-specific installers via `run.py`
4. **Validation**: Installs and tests the generated installer

**Sources:** [.github/workflows/installer.yml:46-112](), [.github/workflows/conda.yml:34-132]()

## Release Processes

The release workflow ensures quality and consistency across all distribution channels.

```mermaid
graph TB
    subgraph "Release Triggers"
        RELEASE_EVENT["GitHub Release<br/>released/prereleased events"]
        SCHEDULE_NIGHTLY["Nightly Schedule<br/>0 20 * * *"]
        MANUAL_DISPATCH["Manual Workflow Dispatch"]
    end
    
    subgraph "Version Management"
        TAG_DETECTION["Latest Tag Detection<br/>git ls-remote --tags<br/>grep -E '([0-9]+)\.([0-9]+)\.([0-9]+)$'"]
        VERSION_VALIDATION["Version Validation<br/>Compare installed vs expected"]
    end
    
    subgraph "Quality Assurance"
        CONDA_INSTALL["Fresh Conda Install<br/>Test against conda-forge"]
        FULL_TEST_SUITE["Full Test Suite<br/>Core + Examples + Notebooks"]
        PLUGIN_TESTING["Plugin Testing<br/>utilities/test_plugins"]
        CROSS_PLATFORM["Cross-platform Testing<br/>ubuntu-latest, macos-latest"]
    end
    
    subgraph "Beta/RC Testing"
        BETA_CHANNELS["Beta Channel Testing<br/>conda-forge/label/openmm_rc<br/>conda-forge/label/openff-toolkit_rc<br/>openeye/label/rc"]
        DEPENDENCY_VALIDATION["Dependency Validation<br/>Test against upstream betas"]
    end
    
    RELEASE_EVENT --> TAG_DETECTION
    SCHEDULE_NIGHTLY --> TAG_DETECTION
    MANUAL_DISPATCH --> TAG_DETECTION
    
    TAG_DETECTION --> VERSION_VALIDATION
    VERSION_VALIDATION --> CONDA_INSTALL
    CONDA_INSTALL --> FULL_TEST_SUITE
    FULL_TEST_SUITE --> PLUGIN_TESTING
    PLUGIN_TESTING --> CROSS_PLATFORM
    
    SCHEDULE_NIGHTLY --> BETA_CHANNELS
    BETA_CHANNELS --> DEPENDENCY_VALIDATION
```

### Release Validation Steps

The conda workflow performs comprehensive validation of released packages:

1. **Environment Setup**: Creates clean conda environment with released package
2. **Version Verification**: Ensures installed version matches expected release tag
3. **Toolkit Validation**: Confirms proper toolkit availability/unavailability
4. **Test Execution**: Runs core test suite and example notebooks
5. **Cross-platform Testing**: Validates on both Ubuntu and macOS

**Sources:** [.github/workflows/conda.yml:71-132](), [.github/workflows/beta_rc.yaml:29-87]()

## Build Tools and Dependencies

The build system relies on specific tools and configurations for different aspects of the packaging process.

| Tool | Purpose | Configuration |
|------|---------|---------------|
| `micromamba` | Conda environment management | `mamba-org/setup-micromamba@v2` |
| `pytest` | Test execution | `pytest=8` with various plugins |
| `versioningit` | Version management | Dynamic versioning from git |
| `constructor` | Single-file installer creation | External repository integration |
| `anaconda-client` | Conda package upload | Release build environment |

### Environment Pinning Strategy

The toolkit uses careful dependency pinning to ensure reproducible builds:

- **NumPy**: Pinned to `<2.3` due to downstream compatibility issues
- **OpenMM**: Minimum version `>=7.6` for API compatibility
- **RDKit**: Excludes specific versions with known issues (`!=2024.03.6,!=2024.09.1`)
- **Python**: Supports 3.11, 3.12, and 3.13 with matrix testing

**Sources:** [devtools/conda-envs/test_env.yaml:10-53](), [devtools/conda-envs/release-build.yaml:1-10]()

---