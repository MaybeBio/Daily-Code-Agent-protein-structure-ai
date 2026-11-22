# Development and Deployment

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



This document covers the development setup, build system, and deployment infrastructure for BioSimSpace. It details the package installation process, conda recipe management, continuous integration workflows, and deployment strategies across different channels and environments.

For information about experimental features and the Sandpit branch, see [Sandpit and Experimental Features](#8.1). For details about the conda build recipes and CI/CD automation, see [Build System and CI/CD](#8.2).

## Build System Architecture

BioSimSpace uses a multi-layered build and deployment system centered around conda packaging, with different workflows for development and production releases.

### Package Installation Flow

```mermaid
graph TD
    subgraph "Installation Entry Points"
        SETUP["setup.py"]
        CONDA_RECIPE["recipes/biosimspace/meta.yaml"]
    end
    
    subgraph "Dependency Resolution"
        SIRE_CHECK["Sire Version Check"]
        REQ_PARSE["requirements.txt Parsing"]
        PLATFORM_CHECK["Platform Detection"]
    end
    
    subgraph "Installation Methods"
        DIRECT["Direct Python Install"]
        CONDA_BUILD["Conda Build"]
        DEV_INSTALL["Development Install"]
    end
    
    subgraph "Environment Setup"
        CONDA_DEPS["Conda Dependencies"]
        CHANNELS["Channel Configuration"]
        JUPYTER_EXT["Jupyter Extensions"]
    end
    
    SETUP --> SIRE_CHECK
    SETUP --> REQ_PARSE
    SETUP --> PLATFORM_CHECK
    
    CONDA_RECIPE --> REQ_PARSE
    
    SIRE_CHECK --> DIRECT
    SIRE_CHECK --> DEV_INSTALL
    CONDA_RECIPE --> CONDA_BUILD
    
    DIRECT --> CONDA_DEPS
    DEV_INSTALL --> CONDA_DEPS
    CONDA_BUILD --> CHANNELS
    
    CONDA_DEPS --> JUPYTER_EXT
    CHANNELS --> JUPYTER_EXT
    
    style REQ_PARSE fill:#e1f5fe
    style CONDA_DEPS fill:#f3e5f5
    style JUPYTER_EXT fill:#e8f5e8
```

Sources: [python/setup.py:1-273](), [recipes/biosimspace/template.yaml:1-78](), [requirements.txt:1-31]()

### Dependency Management System

The build system implements sophisticated dependency resolution with platform-specific handling and multiple installation pathways.

```mermaid
graph LR
    subgraph "Dependency Sources"
        REQ_TXT["requirements.txt"]
        REQ_BUILD["requirements_build.txt"]
        SETUP_DEPS["setup.py conda_deps"]
    end
    
    subgraph "Platform Filtering"
        ARCH_FILTER["aarch64 Exclusions"]
        OS_FILTER["Windows/macOS/Linux"]
        PYTHON_FILTER["Python Version Filter"]
    end
    
    subgraph "Installation Tools"
        MAMBA["mamba"]
        CONDA["conda"]
        PIP["pip (fallback)"]
    end
    
    subgraph "Package Categories"
        CORE_DEPS["Core Dependencies<br/>sire, configargparse, networkx"]
        OPTIONAL_DEPS["Optional Dependencies<br/>alchemlyb, mdanalysis, mdtraj"]
        JUPYTER_DEPS["Jupyter Dependencies<br/>nglview, py3dmol, ipywidgets"]
    end
    
    REQ_TXT --> ARCH_FILTER
    REQ_BUILD --> OS_FILTER
    SETUP_DEPS --> PYTHON_FILTER
    
    ARCH_FILTER --> CORE_DEPS
    OS_FILTER --> OPTIONAL_DEPS
    PYTHON_FILTER --> JUPYTER_DEPS
    
    CORE_DEPS --> MAMBA
    OPTIONAL_DEPS --> CONDA
    JUPYTER_DEPS --> PIP
    
    style CORE_DEPS fill:#e1f5fe
    style OPTIONAL_DEPS fill:#fff3e0
    style JUPYTER_DEPS fill:#e8f5e8
```

Sources: [python/setup.py:109-131](), [python/setup.py:148-157](), [requirements.txt:25-31]()

## Development Setup Process

The `setup.py` script provides comprehensive development environment configuration with automatic dependency resolution and platform-specific optimizations.

### Installation Configuration

| Configuration Option | Purpose | Environment Variable |
|---------------------|---------|---------------------|
| Skip Dependencies | Bypass automatic dependency installation | `BSS_SKIP_DEPENDENCIES=1` |
| Conda Install Mode | Use conda-specific installation path | `BSS_CONDA_INSTALL=1` |
| Sire Integration | Enable mixed API compatibility mode | `SIRE_DONT_PHONEHOME=1` |

The setup process performs several critical validations:

1. **Sire Compatibility**: Verifies minimum Sire version requirement ([python/setup.py:26-43]())
2. **Python Environment**: Ensures proper Sire Python interpreter usage ([python/setup.py:30-39]())
3. **Dependency Resolution**: Handles platform-specific package availability ([python/setup.py:148-157]())

### Conda Channel Management

The installation process automatically configures conda channels with proper priority ordering:

```mermaid
graph TD
    subgraph "Channel Configuration"
        OPENBIOSIM_DEV["openbiosim/label/dev"]
        OPENBIOSIM_MAIN["openbiosim/label/main"]
        CONDA_FORGE["conda-forge"]
        DEFAULTS["defaults"]
    end
    
    subgraph "Channel Operations"
        ADD_CHANNELS["Add Channels"]
        SET_PRIORITY["Set Priority Order"]
        DISABLE_AUTO["Disable Auto-update"]
    end
    
    subgraph "Installation Flow"
        BATCH_INSTALL["Batch Installation"]
        FALLBACK_INSTALL["Individual Fallback"]
        VERIFY_INSTALL["Installation Verification"]
    end
    
    ADD_CHANNELS --> OPENBIOSIM_DEV
    ADD_CHANNELS --> CONDA_FORGE
    SET_PRIORITY --> ADD_CHANNELS
    DISABLE_AUTO --> SET_PRIORITY
    
    OPENBIOSIM_DEV --> BATCH_INSTALL
    CONDA_FORGE --> BATCH_INSTALL
    BATCH_INSTALL --> FALLBACK_INSTALL
    FALLBACK_INSTALL --> VERIFY_INSTALL
    
    style OPENBIOSIM_DEV fill:#e1f5fe
    style CONDA_FORGE fill:#f3e5f5
```

Sources: [python/setup.py:162-194](), [python/setup.py:195-248]()

## CI/CD Pipeline Architecture

BioSimSpace implements a multi-branch CI/CD strategy with different deployment targets and approval workflows.

### Workflow Trigger Strategy

```mermaid
graph TD
    subgraph "Branch Workflows"
        PR_WORKFLOW[".github/workflows/pr.yaml"]
        DEVEL_WORKFLOW[".github/workflows/devel.yaml"]
        MAIN_WORKFLOW[".github/workflows/main.yaml"]
    end
    
    subgraph "Trigger Conditions"
        PR_TRIGGER["Pull Request<br/>to devel/main"]
        DEVEL_PUSH["Push to devel<br/>Auto-trigger"]
        MAIN_MANUAL["Manual Dispatch<br/>Approval Required"]
    end
    
    subgraph "Build Matrix"
        PYTHON_VERSIONS["Python 3.10, 3.11, 3.12"]
        PLATFORMS["Windows, Linux, macOS"]
        EXCLUSIONS["Platform/Version Exclusions"]
    end
    
    subgraph "Deployment Targets"
        NO_DEPLOY["Testing Only"]
        DEV_CHANNEL["openbiosim/label/dev"]
        MAIN_CHANNEL["openbiosim/label/main"]
    end
    
    PR_TRIGGER --> PR_WORKFLOW
    DEVEL_PUSH --> DEVEL_WORKFLOW
    MAIN_MANUAL --> MAIN_WORKFLOW
    
    PR_WORKFLOW --> PYTHON_VERSIONS
    DEVEL_WORKFLOW --> PLATFORMS
    MAIN_WORKFLOW --> EXCLUSIONS
    
    PR_WORKFLOW --> NO_DEPLOY
    DEVEL_WORKFLOW --> DEV_CHANNEL
    MAIN_WORKFLOW --> MAIN_CHANNEL
    
    style DEVEL_WORKFLOW fill:#e1f5fe
    style MAIN_WORKFLOW fill:#f3e5f5
    style DEV_CHANNEL fill:#e8f5e8
```

Sources: [.github/workflows/pr.yaml:1-69](), [.github/workflows/devel.yaml:1-67](), [.github/workflows/main.yaml:1-65]()

### Build Process Flow

Each CI/CD workflow follows a standardized build process with environment-specific configurations:

```mermaid
graph LR
    subgraph "Environment Setup"
        CONDA_SETUP["setup-miniconda@v3"]
        CLONE_REPO["git clone"]
        INSTALL_TOOLS["conda install boa<br/>anaconda-client"]
    end
    
    subgraph "Recipe Generation"
        UPDATE_RECIPE["update_recipe.py"]
        PARSE_REQUIREMENTS["parse_requirements"]
        TEMPLATE_POPULATE["template.yaml → meta.yaml"]
    end
    
    subgraph "Package Build"
        CONDA_BUILD["conda build"]
        CHANNEL_SELECT["Channel Selection<br/>dev vs main"]
        TEST_EXECUTION["pytest Test Suite"]
    end
    
    subgraph "Deployment"
        UPLOAD_PACKAGE["upload_package.py"]
        ANACONDA_DEPLOY["Anaconda Cloud"]
        LABEL_MANAGEMENT["Label Assignment"]
    end
    
    CONDA_SETUP --> CLONE_REPO
    CLONE_REPO --> INSTALL_TOOLS
    INSTALL_TOOLS --> UPDATE_RECIPE
    
    UPDATE_RECIPE --> PARSE_REQUIREMENTS
    PARSE_REQUIREMENTS --> TEMPLATE_POPULATE
    TEMPLATE_POPULATE --> CONDA_BUILD
    
    CONDA_BUILD --> CHANNEL_SELECT
    CHANNEL_SELECT --> TEST_EXECUTION
    TEST_EXECUTION --> UPLOAD_PACKAGE
    
    UPLOAD_PACKAGE --> ANACONDA_DEPLOY
    ANACONDA_DEPLOY --> LABEL_MANAGEMENT
    
    style UPDATE_RECIPE fill:#e1f5fe
    style CONDA_BUILD fill:#f3e5f5
    style ANACONDA_DEPLOY fill:#e8f5e8
```

Sources: [.github/workflows/devel.yaml:40-67](), [actions/update_recipe.py:1-81]()

## Conda Recipe Management

The conda packaging system uses a template-based approach with dynamic requirement injection and git-based versioning.

### Recipe Template System

The recipe generation process transforms the template into a complete conda recipe:

| Template Variable | Source | Purpose |
|------------------|--------|---------|
| `BSS_REMOTE` | `git config remote.origin.url` | Source repository URL |
| `BSS_BRANCH` | `git rev-parse --abbrev-ref HEAD` | Current branch name |
| `BSS_BUILD_REQUIREMENTS` | `requirements_build.txt` | Build-time dependencies |
| `BSS_RUN_REQUIREMENTS` | `requirements.txt` | Runtime dependencies |

### Package Metadata Configuration

```mermaid
graph TD
    subgraph "Version Control"
        GIT_TAG["GIT_DESCRIBE_TAG"]
        GIT_NUMBER["GIT_DESCRIBE_NUMBER"]
        VERSION_STRING["Package Version"]
    end
    
    subgraph "Requirements Processing"
        PARSE_REQ["parse_requirements.py"]
        BUILD_DEPS["requirements_build.txt"]
        RUN_DEPS["requirements.txt"]
    end
    
    subgraph "Template Processing"
        TEMPLATE_YAML["template.yaml"]
        SUBSTITUTION["Variable Substitution"]
        META_YAML["meta.yaml"]
    end
    
    subgraph "Test Configuration"
        TEST_MATRIX["Platform/Python Matrix"]
        OPTIONAL_TESTS["Black Formatting<br/>Linux x86_64 Only"]
        INTEGRATION_TESTS["pytest Suite"]
    end
    
    GIT_TAG --> VERSION_STRING
    GIT_NUMBER --> VERSION_STRING
    VERSION_STRING --> TEMPLATE_YAML
    
    PARSE_REQ --> BUILD_DEPS
    PARSE_REQ --> RUN_DEPS
    BUILD_DEPS --> SUBSTITUTION
    RUN_DEPS --> SUBSTITUTION
    
    TEMPLATE_YAML --> SUBSTITUTION
    SUBSTITUTION --> META_YAML
    META_YAML --> TEST_MATRIX
    
    TEST_MATRIX --> OPTIONAL_TESTS
    OPTIONAL_TESTS --> INTEGRATION_TESTS
    
    style PARSE_REQ fill:#e1f5fe
    style SUBSTITUTION fill:#f3e5f5
    style INTEGRATION_TESTS fill:#e8f5e8
```

Sources: [recipes/biosimspace/template.yaml:1-78](), [actions/update_recipe.py:31-81]()

## Deployment Strategies

BioSimSpace uses a multi-channel deployment strategy with different stability guarantees and approval processes.

### Channel Management Strategy

| Channel | Purpose | Deployment Trigger | Stability |
|---------|---------|-------------------|-----------|
| `openbiosim/label/dev` | Development releases | Automatic on devel push | Experimental |
| `openbiosim/label/main` | Stable releases | Manual approval required | Production-ready |
| `conda-forge` | Community distribution | External maintenance | Stable |

### Platform Support Matrix

The build system supports multiple platforms with specific exclusions for compatibility:

```mermaid
graph TD
    subgraph "Supported Platforms"
        LINUX["Linux (ubuntu-latest)"]
        WINDOWS["Windows (windows-latest)"]
        MACOS["macOS (macos-latest)"]
    end
    
    subgraph "Python Versions"
        PY310["Python 3.10"]
        PY311["Python 3.11"]
        PY312["Python 3.12"]
    end
    
    subgraph "Platform Exclusions"
        MACOS_312["macOS + Python 3.12<br/>Not Supported"]
        WIN_REDUCED["Windows<br/>Limited Python Versions"]
        LINUX_FULL["Linux<br/>Full Support"]
    end
    
    subgraph "Architecture Support"
        X86_64["x86_64<br/>Full Feature Set"]
        AARCH64["aarch64<br/>Limited Dependencies"]
    end
    
    LINUX --> PY310
    LINUX --> PY311
    LINUX --> PY312
    WINDOWS --> PY312
    MACOS --> PY310
    MACOS --> PY311
    
    LINUX --> LINUX_FULL
    WINDOWS --> WIN_REDUCED
    MACOS --> MACOS_312
    
    LINUX_FULL --> X86_64
    LINUX_FULL --> AARCH64
    
    style LINUX_FULL fill:#e8f5e8
    style AARCH64 fill:#fff3e0
    style MACOS_312 fill:#ffcdd2
```

Sources: [.github/workflows/main.yaml:15-32](), [requirements.txt:25-31]()

The deployment system ensures comprehensive testing across platforms while maintaining compatibility with the diverse ecosystem of molecular dynamics software that BioSimSpace integrates with.

Sources: [.github/workflows/pr.yaml:14-32](), [.github/workflows/devel.yaml:15-31](), [recipes/biosimspace/build.sh:1-6]()

---