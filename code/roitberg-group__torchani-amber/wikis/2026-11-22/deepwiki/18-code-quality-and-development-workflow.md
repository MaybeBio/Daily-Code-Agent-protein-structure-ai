# Code Quality and Development Workflow

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.flake8](.flake8)
- [.gitignore](.gitignore)
- [.pre-commit-config.yaml](.pre-commit-config.yaml)
- [benchmark/environment.yaml](benchmark/environment.yaml)
- [benchmark/utils.py](benchmark/utils.py)
- [external/README.md](external/README.md)

</details>



This document covers the development workflow, code quality tools, pre-commit hooks, and contribution guidelines for TorchANI-Amber. It provides essential information for developers contributing to the codebase, including automated quality checks, git workflows, and environment management practices.

For information about the build system and dependency management, see [Build System Deep Dive](#6.1). For testing infrastructure and test execution, see [Testing Framework](#6.2).

## Development Workflow Overview

TorchANI-Amber employs a structured development workflow that emphasizes code quality, automated testing, and systematic integration practices. The workflow integrates multiple quality assurance tools and follows established patterns for collaborative development.

### Pre-commit Hook System

The development workflow centers around a comprehensive pre-commit hook system that enforces code quality standards before changes enter the repository.

```mermaid
flowchart TD
    DEV["Developer Makes Changes"] --> STAGE["git add files"]
    STAGE --> COMMIT["git commit"]
    
    COMMIT --> PRECOMMIT["Pre-commit Hooks Trigger"]
    
    PRECOMMIT --> BRANCH_CHECK["no-commit-to-branch"]
    BRANCH_CHECK --> BRANCH_PASS{"Branch Check Pass?"}
    BRANCH_PASS -->|No| ABORT_COMMIT["Commit Aborted"]
    BRANCH_PASS -->|Yes| PUSH_ATTEMPT["git push"]
    
    PUSH_ATTEMPT --> PREPUSH["Pre-push Hooks Trigger"]
    
    PREPUSH --> SYNTAX_CHECKS["File Syntax Validation"]
    SYNTAX_CHECKS --> CHECK_YAML["check-yaml"]
    CHECK_YAML --> CHECK_TOML["check-toml"] 
    CHECK_TOML --> CHECK_JSON["check-json"]
    
    SYNTAX_CHECKS --> QUALITY_CHECKS["Code Quality Checks"]
    QUALITY_CHECKS --> LARGE_FILES["check-added-large-files"]
    LARGE_FILES --> MERGE_CONFLICT["check-merge-conflict"]
    MERGE_CONFLICT --> DEBUG_STMT["debug-statements"]
    
    QUALITY_CHECKS --> PYTHON_TOOLS["Python Code Quality"]
    PYTHON_TOOLS --> BLACK["black formatter"]
    BLACK --> FLAKE8["flake8 linter"]
    FLAKE8 --> AUTOFLAKE["autoflake unused imports"]
    
    AUTOFLAKE --> CHECKS_PASS{"All Checks Pass?"}
    CHECKS_PASS -->|No| FIX_ISSUES["Fix Issues & Retry"]
    CHECKS_PASS -->|Yes| PUSH_SUCCESS["Push Successful"]
    
    FIX_ISSUES --> STAGE
    ABORT_COMMIT --> DEV
```

Sources: [.pre-commit-config.yaml:1-40]()

### Code Quality Tools Configuration

The project employs several code quality tools with specific configurations tailored to the codebase requirements.

| Tool | Purpose | Configuration File | Key Settings |
|------|---------|-------------------|--------------|
| `black` | Python code formatting | `.pre-commit-config.yaml` | Version 22.6.0, runs on pre-push |
| `flake8` | Python linting | `.flake8` | Max line length 88, ignores W503 |
| `autoflake` | Remove unused imports | `.pre-commit-config.yaml` | Version v1.4, runs on pre-push |
| `pre-commit` | Hook orchestration | `.pre-commit-config.yaml` | Multiple stages and repositories |

The `flake8` configuration specifically addresses Python coding standards:

```mermaid
graph LR
    FLAKE8_CONFIG[".flake8 Configuration"] --> IGNORE["ignore = W503"]
    FLAKE8_CONFIG --> MAXLINE["max-line-length = 88"]
    FLAKE8_CONFIG --> EXCLUDE["exclude patterns"]
    
    IGNORE --> W503_REASON["Line break before binary operator<br/>conflicts with PEP8 preference"]
    MAXLINE --> BLACK_COMPAT["Matches black formatter settings"]
    
    EXCLUDE --> GIT_DIR[".git"]
    EXCLUDE --> PYCACHE["__pycache__"]
    EXCLUDE --> EGGS[".eggs"]
    EXCLUDE --> BUILD["build"]
    EXCLUDE --> EGGINFO["torchani.egg-info"]
    EXCLUDE --> DOCS["docs/examples"]
    EXCLUDE --> TOOLS["tools/dump_dispersion_constants.py"]
```

Sources: [.flake8:1-15](), [.pre-commit-config.yaml:23-40]()

## Repository Management

### Git Ignore Patterns

The repository maintains strict control over tracked files through comprehensive ignore patterns that prevent accidental inclusion of generated content and development artifacts.

| Category | Patterns | Purpose |
|----------|----------|---------|
| Build artifacts | `build/*`, `*.x`, `*.mod` | CMake and compilation outputs |
| Generated models | `jit/*.pt`, `aimnet2/`, `nutmeg/` | JIT-compiled neural network models |
| Development cache | `.mypy_cache/`, `__pycache__/`, `.ccls-cache` | Language server and Python caches |
| Test outputs | `test/test_values*.txt`, `tests/dump_*` | Temporary test result files |
| Benchmark results | `benchmark/*` (selective) | Performance test outputs |
| Runtime artifacts | `*.mdcrd`, `*.restart`, `*mdout` | Amber simulation outputs |

The selective inclusion pattern for benchmark directory preserves essential development tools while excluding generated results:

```mermaid
graph TD
    BENCHMARK_DIR["benchmark/ directory"] --> EXCLUDED["Excluded by default"]
    EXCLUDED --> INCLUDE_ENV["!benchmark/environment.yaml"]
    EXCLUDED --> INCLUDE_BENCH["!benchmark/bench"]
    EXCLUDED --> INCLUDE_UTILS["!benchmark/utils.py"]
    EXCLUDED --> INCLUDE_SYSTEMS["!benchmark/systems/"]
    EXCLUDED --> INCLUDE_TEMPLATES["!benchmark/templates/"]
    
    INCLUDE_ENV --> ENV_PURPOSE["Conda environment specification"]
    INCLUDE_BENCH --> BENCH_PURPOSE["CLI benchmarking tool"]
    INCLUDE_UTILS --> UTILS_PURPOSE["Development utilities"]
    INCLUDE_SYSTEMS --> SYS_PURPOSE["Test system configurations"]
    INCLUDE_TEMPLATES --> TMPL_PURPOSE["Jinja2 job templates"]
```

Sources: [.gitignore:1-51]()

### Branch Protection and Workflow

The pre-commit configuration enforces branch protection policies that prevent direct commits to primary branches, encouraging a proper development workflow through feature branches and pull requests.

```mermaid
sequenceDiagram
    participant DEV as "Developer"
    participant FEATURE as "Feature Branch"
    participant PRECOMMIT as "Pre-commit Hooks"
    participant MAIN as "main/master Branch"
    
    DEV->>FEATURE: "git checkout -b feature-branch"
    DEV->>FEATURE: "Make changes"
    DEV->>PRECOMMIT: "git commit"
    
    PRECOMMIT->>PRECOMMIT: "no-commit-to-branch check"
    Note over PRECOMMIT: "Allows commit to feature branch"
    PRECOMMIT->>FEATURE: "Commit allowed"
    
    DEV->>MAIN: "Attempt direct commit"
    PRECOMMIT->>PRECOMMIT: "no-commit-to-branch check"
    Note over PRECOMMIT: "args: ['--branch', 'main', '--branch', 'master']"
    PRECOMMIT->>DEV: "Commit blocked"
```

Sources: [.pre-commit-config.yaml:6-8]()

## Environment Management

### Development Environment Specification

The project provides standardized environment specifications for consistent development setups across different systems and contributors.

The benchmark environment configuration demonstrates the project's approach to dependency management:

```mermaid
graph LR
    ENV_YAML["benchmark/environment.yaml"] --> NAME["name: ani-amber-bench"]
    ENV_YAML --> CHANNELS["Channel Configuration"]
    ENV_YAML --> DEPS["Dependencies"]
    
    CHANNELS --> NODEFAULTS["- nodefaults"]
    CHANNELS --> CONDA_FORGE["- conda-forge"]
    
    DEPS --> PYTHON["python=3.11"]
    DEPS --> CORE_LIBS["Core Libraries"]
    DEPS --> DEV_TOOLS["Development Tools"]
    DEPS --> ANALYSIS["Analysis Tools"]
    
    CORE_LIBS --> NUMPY["numpy"]
    CORE_LIBS --> SCIPY["scipy"]
    
    DEV_TOOLS --> PIP["pip>=24.0"]
    DEV_TOOLS --> TYPER["typer"]
    DEV_TOOLS --> RICH["rich"]
    DEV_TOOLS --> JINJA2["jinja2"]
    
    ANALYSIS --> MATPLOTLIB["matplotlib"]
    ANALYSIS --> PANDAS["pandas"]
    ANALYSIS --> TYPING_EXT["typing_extensions>=4.0.0"]
```

Sources: [benchmark/environment.yaml:1-16]()

## Development Utilities

### Scheduler Integration for HPC Development

The development workflow includes sophisticated utilities for high-performance computing environments, particularly for testing and benchmarking on cluster systems.

The `send_to_scheduler` function in `benchmark/utils.py` demonstrates the integration between development tools and HPC infrastructure:

```mermaid
flowchart TD
    CLI_ARGS["CLI Arguments"] --> PARSE_ARGS["Argument Parsing"]
    PARSE_ARGS --> CLUSTER_CONFIG["Cluster Configuration"]
    
    CLUSTER_CONFIG --> HPG_CHECK{"cluster == 'hpg'?"}
    HPG_CHECK -->|Yes| GPU_MAPPING["GPU to Partition Mapping"]
    HPG_CHECK -->|No| UNKNOWN_CLUSTER["Unknown cluster error"]
    
    GPU_MAPPING --> GPU_2080TI["2080ti → gpu partition"]
    GPU_MAPPING --> GPU_B200["b200 → hpg-b200 partition"]
    GPU_MAPPING --> GPU_L4["l4 → hpg-turin partition"]
    
    CLUSTER_CONFIG --> TEMPLATE_ENV["Jinja2 Environment Setup"]
    TEMPLATE_ENV --> SCHED_ROOT["~/Sched/ani-amber/"]
    SCHED_ROOT --> VERSION_CHECK["Version Increment Logic"]
    
    VERSION_CHECK --> TEMPLATE_RENDER["Template Rendering"]
    TEMPLATE_RENDER --> SLURM_SCRIPT["Generate .slurm.sh file"]
    SLURM_SCRIPT --> SBATCH["subprocess.run(['sbatch', script])"]
```

Sources: [benchmark/utils.py:14-79]()

### Model Support Matrix

The development framework supports a comprehensive range of neural network models through a standardized interface:

| Model Family | Variants | Purpose |
|--------------|----------|---------|
| ANI | `ani1x`, `ani1ccx`, `ani2x`, `ani2xr`, `ani2dr` | Legacy ANI models |
| ANI Specialized | `animbis`, `aniala`, `anir2s` variants | Specialized systems |
| AIMNet2 | `b973c` and `wb97m` functionals | Advanced charge prediction |
| NutMeg | `small`, `medium`, `large` | Variable complexity models |

The `SUPPORTED_MODELS` list serves as the authoritative registry for model validation and benchmarking workflows.

Sources: [benchmark/utils.py:82-109]()

## Contribution Guidelines

### Code Quality Standards

Contributors must ensure their code adheres to the established quality standards enforced by the automated toolchain:

1. **Python Code Formatting**: All Python code must pass `black` formatting with default settings
2. **Linting Compliance**: Code must satisfy `flake8` requirements with project-specific configurations
3. **Import Management**: Unused imports are automatically detected and must be removed
4. **Branch Workflow**: Direct commits to `main` or `master` branches are prohibited
5. **File Size Limits**: Large files are blocked from commits to maintain repository efficiency

### Development Environment Setup

New contributors should establish their development environment using the provided specifications:

1. Create conda environment: `conda env create -f benchmark/environment.yaml`
2. Install pre-commit hooks: `pre-commit install`
3. Verify tool functionality: `pre-commit run --all-files`
4. Configure IDE/editor to use project-specific settings (88-character line limit, etc.)

### Integration Testing

Before submitting contributions, developers should run the full suite of quality checks locally to ensure compatibility with the automated systems. The pre-commit framework provides immediate feedback on code quality issues, enabling rapid iteration during development.

Sources: [.pre-commit-config.yaml:1-40](), [.flake8:1-15](), [benchmark/environment.yaml:1-16]()