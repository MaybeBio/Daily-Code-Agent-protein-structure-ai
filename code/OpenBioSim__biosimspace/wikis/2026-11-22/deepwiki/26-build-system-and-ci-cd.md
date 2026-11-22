# Build System and CI/CD

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.github/workflows/devel.yaml](.github/workflows/devel.yaml)
- [.github/workflows/main.yaml](.github/workflows/main.yaml)
- [.github/workflows/pr.yaml](.github/workflows/pr.yaml)
- [actions/update_recipe.py](actions/update_recipe.py)
- [python/BioSimSpace/Sandpit/Exscientia/_SireWrappers/_utils.py](python/BioSimSpace/Sandpit/Exscientia/_SireWrappers/_utils.py)
- [python/BioSimSpace/_SireWrappers/_utils.py](python/BioSimSpace/_SireWrappers/_utils.py)
- [python/setup.py](python/setup.py)
- [recipes/biosimspace/LICENSE](recipes/biosimspace/LICENSE)
- [recipes/biosimspace/build.sh](recipes/biosimspace/build.sh)
- [recipes/biosimspace/template.yaml](recipes/biosimspace/template.yaml)
- [requirements.txt](requirements.txt)

</details>



This document covers the build system, packaging, and continuous integration/continuous deployment (CI/CD) infrastructure for BioSimSpace. It explains how the Python package is built, packaged for conda distribution, and automatically tested and deployed across multiple platforms.

For information about experimental features and development branches, see [Sandpit and Experimental Features](#8.1).

## Build System Overview

BioSimSpace uses a setuptools-based build system with conda packaging for distribution. The build process handles Python package installation, dependency management, and cross-platform compatibility.

```mermaid
graph TD
    subgraph "Source Code"
        SETUP["setup.py"]
        REQ["requirements.txt"]
        PYTHON["python/BioSimSpace/"]
    end
    
    subgraph "Build Tools"
        SETUPTOOLS["setuptools"]
        VERSIONEER["versioneer"]
        CONDA_BUILD["conda-build"]
    end
    
    subgraph "Packaging"
        RECIPE_TEMPLATE["recipes/biosimspace/template.yaml"]
        RECIPE_GENERATED["recipes/biosimspace/meta.yaml"]
        BUILD_SCRIPT["recipes/biosimspace/build.sh"]
    end
    
    subgraph "Artifacts"
        CONDA_PKG["conda package"]
        WHEEL["wheel package"]
    end
    
    SETUP --> SETUPTOOLS
    REQ --> SETUPTOOLS
    PYTHON --> SETUPTOOLS
    
    SETUPTOOLS --> VERSIONEER
    VERSIONEER --> WHEEL
    
    RECIPE_TEMPLATE --> RECIPE_GENERATED
    REQ --> RECIPE_GENERATED
    RECIPE_GENERATED --> CONDA_BUILD
    BUILD_SCRIPT --> CONDA_BUILD
    PYTHON --> CONDA_BUILD
    
    CONDA_BUILD --> CONDA_PKG
```

**Sources:** [python/setup.py:1-273](), [recipes/biosimspace/template.yaml:1-78](), [recipes/biosimspace/build.sh:1-6]()

## Package Setup and Dependencies

The main package configuration is handled by `setup.py`, which includes dependency management and cross-platform installation logic.

### Core Setup Configuration

The `setup()` function defines the basic package metadata:

| Configuration | Value |
|---------------|-------|
| Package Name | `BioSimSpace` |
| Version | Dynamic via `versioneer.get_version()` |
| License | `GPLv3` |
| URL | `https://github.com/openbiosim/biosimspace` |
| Dependencies | Managed via `requirements.txt` |

### Dependency Management

The setup script implements conditional dependency installation based on platform and installation context:

```mermaid
flowchart TD
    START["setup.py execution"]
    CHECK_CONDA["Check BSS_CONDA_INSTALL env var"]
    CHECK_SKIP["Check BSS_SKIP_DEPENDENCIES env var"]
    
    INSTALL_DEPS["Install conda dependencies"]
    SKIP_DEPS["Skip dependency installation"]
    
    DETECT_CONDA["Detect mamba/conda executable"]
    CHECK_INSTALLED["Check existing packages"]
    INSTALL_MISSING["Install missing packages"]
    
    CONFIGURE_CHANNELS["Configure conda channels"]
    CLEAN_ENV["Clean conda environment"]
    
    START --> CHECK_CONDA
    CHECK_CONDA --> CHECK_SKIP
    CHECK_SKIP --> SKIP_DEPS
    CHECK_SKIP --> INSTALL_DEPS
    
    INSTALL_DEPS --> DETECT_CONDA
    DETECT_CONDA --> CHECK_INSTALLED
    CHECK_INSTALLED --> CONFIGURE_CHANNELS
    CONFIGURE_CHANNELS --> INSTALL_MISSING
    INSTALL_MISSING --> CLEAN_ENV
```

**Sources:** [python/setup.py:25-273](), [requirements.txt:1-31]()

## CI/CD Pipeline Architecture

BioSimSpace uses GitHub Actions for continuous integration across three main workflows corresponding to different branches and triggers.

### Workflow Structure

```mermaid
graph TB
    subgraph "Triggers"
        PR["Pull Request"]
        DEVEL_PUSH["Push to devel"]
        MAIN_DISPATCH["Manual dispatch on main"]
    end
    
    subgraph "Workflows"
        PR_WORKFLOW[".github/workflows/pr.yaml"]
        DEVEL_WORKFLOW[".github/workflows/devel.yaml"]
        MAIN_WORKFLOW[".github/workflows/main.yaml"]
    end
    
    subgraph "Build Matrix"
        PLATFORMS["windows-latest<br/>ubuntu-latest<br/>macos-latest"]
        PYTHON_VERSIONS["Python 3.10<br/>Python 3.11<br/>Python 3.12"]
    end
    
    subgraph "Build Steps"
        SETUP_CONDA["Setup Miniconda"]
        CLONE_REPO["Clone Repository"]
        UPDATE_RECIPE["Update Conda Recipe"]
        BUILD_PKG["Build Conda Package"]
        UPLOAD_PKG["Upload Package"]
    end
    
    PR --> PR_WORKFLOW
    DEVEL_PUSH --> DEVEL_WORKFLOW
    MAIN_DISPATCH --> MAIN_WORKFLOW
    
    PR_WORKFLOW --> PLATFORMS
    DEVEL_WORKFLOW --> PLATFORMS
    MAIN_WORKFLOW --> PLATFORMS
    
    PLATFORMS --> PYTHON_VERSIONS
    PYTHON_VERSIONS --> SETUP_CONDA
    
    SETUP_CONDA --> CLONE_REPO
    CLONE_REPO --> UPDATE_RECIPE
    UPDATE_RECIPE --> BUILD_PKG
    BUILD_PKG --> UPLOAD_PKG
```

**Sources:** [.github/workflows/pr.yaml:1-69](), [.github/workflows/devel.yaml:1-67](), [.github/workflows/main.yaml:1-65]()

### Build Matrix Configuration

Each workflow builds across multiple platform and Python version combinations:

| Platform | Python Versions | Shell |
|----------|----------------|-------|
| `windows-latest` | 3.11, 3.12 | `pwsh` |
| `ubuntu-latest` | 3.10, 3.11, 3.12 | `bash -l {0}` |
| `macos-latest` | 3.10, 3.11 | `bash -l {0}` |

The matrix excludes certain combinations to optimize build times while maintaining comprehensive coverage.

**Sources:** [.github/workflows/pr.yaml:15-32](), [.github/workflows/devel.yaml:15-30](), [.github/workflows/main.yaml:18-27]()

## Conda Recipe System

The conda packaging system uses a template-based approach to generate platform-specific recipes.

### Recipe Generation Process

```mermaid
flowchart LR
    subgraph "Input Files"
        TEMPLATE["template.yaml"]
        REQUIREMENTS["requirements.txt"]
        BUILD_REQS["requirements_build.txt"]
    end
    
    subgraph "Generation Script"
        UPDATE_SCRIPT["actions/update_recipe.py"]
        PARSE_REQS["parse_requirements()"]
        GIT_INFO["Git metadata extraction"]
    end
    
    subgraph "Output"
        META_YAML["meta.yaml"]
        CONDA_BUILD["conda build"]
        PACKAGE["conda package"]
    end
    
    TEMPLATE --> UPDATE_SCRIPT
    REQUIREMENTS --> PARSE_REQS
    BUILD_REQS --> PARSE_REQS
    PARSE_REQS --> UPDATE_SCRIPT
    GIT_INFO --> UPDATE_SCRIPT
    
    UPDATE_SCRIPT --> META_YAML
    META_YAML --> CONDA_BUILD
    CONDA_BUILD --> PACKAGE
```

The `update_recipe.py` script performs template substitution to generate the final `meta.yaml`:

- Replaces `BSS_REMOTE` with git repository URL
- Replaces `BSS_BRANCH` with current git branch
- Replaces `BSS_RUN_REQUIREMENTS` with parsed runtime dependencies
- Replaces `BSS_BUILD_REQUIREMENTS` with parsed build dependencies

**Sources:** [actions/update_recipe.py:1-81](), [recipes/biosimspace/template.yaml:1-78]()

### Conda Package Metadata

The conda recipe defines comprehensive package metadata:

| Field | Value |
|-------|-------|
| Name | `biosimspace` |
| Version | `{{ environ.get('GIT_DESCRIBE_TAG', 'PR') }}` |
| License | `GPL-3.0-or-later` |
| Home | `https://biosimspace.openbiosim.org` |
| Dev URL | `https://github.com/openbiosim/biosimspace` |

**Sources:** [recipes/biosimspace/template.yaml:1-78]()

## Dependency Resolution

BioSimSpace manages dependencies through multiple mechanisms to handle platform-specific requirements.

### Runtime Dependencies

The `requirements.txt` file specifies both universal and platform-conditional dependencies:

```mermaid
graph TD
    subgraph "Universal Dependencies"
        SIRE["sire==2025.1.0.dev"]
        CONFIG["configargparse"]
        WIDGETS["ipywidgets"]
        KCOMBU["kcombu_bss"]
        LOMAP["lomap2"]
        NETWORKX["networkx"]
        NGLVIEW["nglview"]
        OPENFF_INT["openff-interchange-base"]
        OPENFF_TK["openff-toolkit-base"]
        PARMED["parmed"]
        PYARROW["pyarrow"]
        PY3DMOL["py3dmol"]
        PYDOT["pydot"]
        PYGTAIL["pygtail"]
        PYYAML["pyyaml"]
        RDKIT["rdkit"]
    end
    
    subgraph "Platform-Conditional Dependencies"
        ALCHEMLYB["alchemlyb ; platform_machine != 'aarch64'"]
        MDANALYSIS["mdanalysis ; platform_machine != 'aarch64'"]
        MDTRAJ["mdtraj ; platform_machine != 'aarch64'"]
    end
    
    subgraph "Architecture Exclusions"
        AARCH64["Linux/aarch64 platform"]
        X86_64["x86_64 platforms"]
    end
    
    ALCHEMLYB -.-> AARCH64
    MDANALYSIS -.-> AARCH64
    MDTRAJ -.-> AARCH64
    
    ALCHEMLYB --> X86_64
    MDANALYSIS --> X86_64
    MDTRAJ --> X86_64
```

**Sources:** [requirements.txt:1-31]()

### Build Environment Setup

The CI workflows configure the build environment with specific conda channels and tools:

```bash
conda install -y -c conda-forge boa anaconda-client packaging pip-requirements-parser
```

Channel priority is configured as:
1. `conda-forge` (base packages)
2. `openbiosim/label/main` (main releases)
3. `openbiosim/label/dev` (development releases)

**Sources:** [.github/workflows/pr.yaml:54](), [.github/workflows/devel.yaml:51](), [.github/workflows/main.yaml:48]()

## Testing and Quality Assurance

The conda recipe includes comprehensive testing specifications:

### Test Configuration

| Test Type | Configuration |
|-----------|---------------|
| Import Tests | `BioSimSpace` module import |
| Pytest Execution | `pytest -vvv --color=yes --import-mode=importlib tests` |
| Code Formatting | `pytest --black python/BioSimSpace` (Linux x86_64 Python 3.12 only) |
| Test Dependencies | `pytest <8`, `black 25`, `pytest-black` |
| External Tools | `ambertools`, `gromacs` (Linux x86_64 only) |

### Environment Variables

Testing is configured with specific environment variables to prevent telemetry:
- `SIRE_DONT_PHONEHOME=1`
- `SIRE_SILENT_PHONEHOME=1`

**Sources:** [recipes/biosimspace/template.yaml:24-42]()

## Package Upload and Distribution

The CI/CD system handles automatic package distribution to conda channels based on the branch:

### Upload Strategy

```mermaid
graph TD
    subgraph "Branches"
        MAIN_BRANCH["main branch"]
        DEVEL_BRANCH["devel branch"]
        PR_BRANCH["PR branches"]
    end
    
    subgraph "Conda Channels"
        MAIN_CHANNEL["openbiosim/label/main"]
        DEV_CHANNEL["openbiosim/label/dev"]
        NO_UPLOAD["No upload"]
    end
    
    subgraph "Upload Scripts"
        UPLOAD_SCRIPT["actions/upload_package.py"]
        ANACONDA_TOKEN["ANACONDA_TOKEN secret"]
    end
    
    MAIN_BRANCH --> MAIN_CHANNEL
    DEVEL_BRANCH --> DEV_CHANNEL
    PR_BRANCH --> NO_UPLOAD
    
    MAIN_CHANNEL --> UPLOAD_SCRIPT
    DEV_CHANNEL --> UPLOAD_SCRIPT
    UPLOAD_SCRIPT --> ANACONDA_TOKEN
```

Upload is conditional based on:
- Manual approval for main branch (`github.event.inputs.upload_packages == 'true'`)
- Automatic for devel branch pushes
- No upload for pull requests (build verification only)

**Sources:** [.github/workflows/main.yaml:59-64](), [.github/workflows/devel.yaml:62-66]()