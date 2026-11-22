# Development

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.github/workflows/mypy.yml](.github/workflows/mypy.yml)
- [.github/workflows/publish-to-pypi.yml](.github/workflows/publish-to-pypi.yml)
- [.github/workflows/ruff.yml](.github/workflows/ruff.yml)
- [Dockerfile.chailab](Dockerfile.chailab)
- [LICENSE](LICENSE)
- [chai_lab/__init__.py](chai_lab/__init__.py)
- [chai_lab/utils/typing.py](chai_lab/utils/typing.py)

</details>



This page provides essential information for developers contributing to the `chai-lab` codebase. It covers the repository structure, development environment setup, key utilities, and coding standards. This guide assumes you are familiar with Python development and want to contribute code, fix bugs, or extend the system.

For end-users looking to use Chai-1 for structure prediction, please refer to [Getting Started](#2). For detailed information on specific development topics, see the subsections: [Type System](#9.1), [Testing Framework](#9.2), and [CI/CD Pipeline](#9.3).

## Repository Structure

The Chai Lab repository follows a modular organization designed to separate concerns and maintain clean interfaces between components.

**Repository Organization Diagram**

```mermaid
graph TD
    subgraph "Repository Root"
        MainPackage["chai_lab/"]
        License["LICENSE"]
        Reqs["requirements.in"]
        Docker["Dockerfile.chailab"]
        Workflows[".github/workflows/"]
    end
    
    subgraph "Core Package"
        MainPackage --> Init["chai_lab/__init__.py"]
        MainPackage --> Utils["chai_lab/utils/"]
    end
    
    subgraph "Utilities"
        Utils --> Typing["typing.py"]
    end

    subgraph "CI/CD Config"
        Workflows --> Ruff["ruff.yml"]
        Workflows --> Mypy["mypy.yml"]
        Workflows --> PyPI["publish-to-pypi.yml"]
    end
```

Sources: [chai_lab/__init__.py:1-6](), [chai_lab/utils/typing.py:1-49](), [.github/workflows/ruff.yml:1-29]()

## Development Environment

To work on the `chai-lab` codebase, you can use the provided `Dockerfile.chailab` to ensure a consistent environment. The environment is based on Ubuntu 22.04 and uses `uv` for fast dependency management [Dockerfile.chailab:1-75]().

### Docker Environment Configuration
The development container sets up several important environment variables to manage caches and Python behavior:

| Variable | Value | Purpose |
|----------|-------|---------|
| `MYPY_CACHE_DIR` | `/tmp/.chai_lab_mypy_cache` | Keeps large mypy cache outside the working tree [Dockerfile.chailab:11-11]() |
| `PYTHONPYCACHEPREFIX` | `/tmp/.chai_lab_pycache` | Keeps `__pycache__` out of the source tree [Dockerfile.chailab:17-17]() |
| `PYTHONFAULTHANDLER` | `1` | Prints tracebacks after segfaults [Dockerfile.chailab:15-15]() |
| `VIRTUAL_ENV` | `/opt/venv` | Location of the virtual environment [Dockerfile.chailab:60-60]() |

Sources: [Dockerfile.chailab:1-85]()

## Type System

Chai-1 uses a robust static and runtime type checking system to ensure code correctness, especially for tensor operations.

### Type Checking Architecture

The codebase uses a combination of `beartype` and `jaxtyping` for runtime type validation and array shape verification. This is controlled by a central `typecheck` decorator.

```mermaid
graph TD
    subgraph "chai_lab.utils.typing"
        TypeCheck["@typecheck decorator"]
        ShouldCheck["should_typecheck (Boolean)"]
    end
    
    subgraph "External Validators"
        JaxTyped["jaxtyped (jaxtyping)"]
        BearType["beartype (beartype)"]
    end
    
    TypeCheck -- "calls if should_typecheck=True" --> JaxTyped
    JaxTyped -- "uses" --> BearType
```

Sources: [chai_lab/utils/typing.py:23-33]()

For details, see [Type System](#9.1).

## Testing Framework

The testing infrastructure ensures that changes do not break existing functionality. It includes unit tests and integration tests that are run locally and in CI.

*   **Local Testing**: Developers are encouraged to run `pytest` before submitting PRs.
*   **Static Analysis**: The project uses `mypy` for static type checking and `ruff` for linting and formatting.

For details, see [Testing Framework](#9.2).

## CI/CD Pipeline

The codebase employs GitHub Actions to automate quality checks and deployment.

### Workflow Integration

```mermaid
graph LR
    subgraph "GitHub Actions"
        PR["Pull Request / Push"] --> RuffJob["Ruff (Lint/Format)"]
        PR --> MypyJob["Mypy (Type Check)"]
        Release["Release Created"] --> PyPIJob["Publish to PyPI"]
    end

    subgraph "Codebase Entities"
        RuffJob -- "runs" --> PreCommit["pre-commit run ruff"]
        MypyJob -- "runs" --> MypyCmd["mypy ."]
        PyPIJob -- "runs" --> HatchBuild["hatch build && hatch publish"]
    end
```

Sources: [.github/workflows/ruff.yml:24-28](), [.github/workflows/mypy.yml:29-29](), [.github/workflows/publish-to-pypi.yml:35-35]()

For details, see [CI/CD Pipeline](#9.3).

## Licensing and Contributions

Chai-1 is licensed under the Apache License 2.0 [LICENSE:1-5]().

### Copyright Header
All source files must include the standard copyright header:
```python
# Copyright (c) 2024 Chai Discovery, Inc.
# Licensed under the Apache License, Version 2.0.
# See the LICENSE file for details.
```
Sources: [chai_lab/__init__.py:1-3](), [chai_lab/utils/typing.py:1-3]()

---