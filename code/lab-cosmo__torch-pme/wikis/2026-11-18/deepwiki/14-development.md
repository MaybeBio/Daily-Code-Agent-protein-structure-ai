# Development

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.codecov.yml](.codecov.yml)
- [.github/workflows/build.yml](.github/workflows/build.yml)
- [.github/workflows/docs.yml](.github/workflows/docs.yml)
- [.github/workflows/lint.yml](.github/workflows/lint.yml)
- [.github/workflows/release.yml](.github/workflows/release.yml)
- [.github/workflows/tests.yml](.github/workflows/tests.yml)
- [.readthedocs.yaml](.readthedocs.yaml)
- [CITATION.cff](CITATION.cff)
- [CONTRIBUTING.rst](CONTRIBUTING.rst)
- [MANIFEST.in](MANIFEST.in)
- [README.rst](README.rst)
- [docs/src/contributing.rst](docs/src/contributing.rst)
- [pyproject.toml](pyproject.toml)
- [tests/requirements.txt](tests/requirements.txt)
- [tox.ini](tox.ini)

</details>



This page provides information on development processes, testing, and contributing to torch-pme. It is intended for developers who want to understand the project structure, set up a development environment, run tests, and contribute to the codebase.

## Project Setup

torch-pme uses modern Python packaging tools and follows best practices for project organization. The project requires Python 3.9 or newer and uses PyTorch 2.3 or newer as its primary dependency.

### Dependencies

The core dependencies for torch-pme are defined in `pyproject.toml`:

- **Required**: PyTorch 2.3+
- **Optional**:
  - For examples: ASE, chemiscope, matplotlib, metatensor-operations, scipy, vesin, vesin-torch
  - For metatensor integration: metatensor-torch

### Development Environment

To set up a development environment for torch-pme, you need to:

1. Clone the repository
2. Install `tox` for managing tests and linting
3. Run development commands using `tox`

```mermaid
flowchart TD
    A["Clone Repository"] --> B["Install tox: pip install tox"]
    B --> C["Run Tests: tox -e tests"]
    B --> D["Run Linting: tox -e lint"]
    B --> E["Build Docs: tox -e docs"]
    B --> F["Format Code: tox -e format"]
```

Sources: [pyproject.toml:23-45](), [tox.ini:1-14](), [CONTRIBUTING.rst:26-36]()

## Development Workflow

The recommended workflow for contributing to torch-pme involves creating a fork of the repository, making changes, running tests, and submitting a pull request.

```mermaid
flowchart LR
    A["Fork Repository"] --> B["Clone Locally"]
    B --> C["Create Branch"]
    C --> D["Make Changes"]
    D --> E["Run Tests: tox -e tests"]
    E --> F["Run Linting: tox -e lint"]
    F --> G["Commit Changes"]
    G --> H["Push to Fork"]
    H --> I["Open Pull Request"]
    I --> J["CI Runs Tests"]
    J --> K["Review Process"]
    K --> L["Merge to Main"]
```

Sources: [CONTRIBUTING.rst:38-70]()

### Code Style

torch-pme uses `ruff` for code formatting and linting. The configuration is defined in `pyproject.toml` and enforced by CI checks. To ensure your code meets the project standards:

```bash
# Check code style without making changes
tox -e lint

# Automatically format code
tox -e format
```

Sources: [pyproject.toml:100-144](), [tox.ini:53-76]()

## Testing Framework

torch-pme uses pytest for testing. Tests are organized in the `tests/` directory and can be run using tox.

### Running Tests

```bash
# Run all tests
tox -e tests

# Run minimal tests (without optional dependencies)
tox -e tests-min

# Run doctests in modules and README
tox -e tests -- --doctest-modules --pyargs torchpme --doctest-glob=*.rst README.rst
```

Sources: [tox.ini:31-51](), [CONTRIBUTING.rst:72-96]()

### Test Infrastructure

The testing system in torch-pme is designed to ensure code quality and correctness. It includes:

1. Unit tests for core functionality
2. Doctests for documentation examples
3. Coverage reporting via Codecov

```mermaid
graph TD
    subgraph "Test Infrastructure"
        A["pytest"]
        B["coverage.py"]
        C["codecov"]
    end
    
    subgraph "Test Types"
        D["Unit Tests"]
        E["Doctests"]
    end
    
    subgraph "Test Commands"
        F["tox -e tests"]
        G["tox -e tests-min"]
    end
    
    F --> A
    G --> A
    A --> D
    A --> E
    A --> B
    B --> C
```

Sources: [tox.ini:31-51](), [tests/requirements.txt:1-9](), [.codecov.yml:1-11]()

## Continuous Integration

torch-pme uses GitHub Actions for continuous integration. The CI pipelines automatically run tests, check code style, build documentation, and handle releases.

### CI Workflows

```mermaid
flowchart TD
    subgraph "GitHub Actions"
        A["tests.yml: Run Tests"]
        B["lint.yml: Check Code Style"]
        C["docs.yml: Build Documentation"]
        D["build.yml: Check Package Build"]
        E["release.yml: Publish Package"]
    end
    
    subgraph "Events"
        F["Push to main"]
        G["Pull Request"]
        H["Tag Release"]
    end
    
    F --> A & C & D
    G --> A & B & C & D
    H --> E & C
    
    A --> I["Run tests on multiple OS/Python combinations"]
    A --> J["Upload coverage to Codecov"]
    C --> K["Build and deploy docs"]
    E --> L["Publish to PyPI"]
    E --> M["Create GitHub Release"]
```

Sources: [.github/workflows/tests.yml:1-69](), [.github/workflows/lint.yml:1-20](), [.github/workflows/docs.yml:1-48](), [.github/workflows/build.yml:1-25](), [.github/workflows/release.yml:1-42]()

### CI Matrix Testing

torch-pme tests on multiple operating systems and Python versions to ensure compatibility:

| OS | Python Versions |
|----|----------------|
| Ubuntu 22.04 | 3.9, 3.13 |
| macOS 14 | 3.13 |
| Windows 2022 | 3.13 |

Sources: [.github/workflows/tests.yml:10-48]()

## Documentation

The documentation for torch-pme is built using Sphinx and hosted on GitHub Pages. It includes API reference, examples, and user guides.

### Building Documentation

To build the documentation locally:

```bash
tox -e docs
```

This will generate the HTML documentation in `docs/build/html/`. You can view it by opening `docs/build/html/index.html` in your browser.

Sources: [tox.ini:78-89](), [CONTRIBUTING.rst:98-120]()

### Documentation Structure

```mermaid
graph TD
    A["docs/src/"] --> B["conf.py: Configuration"]
    A --> C["examples/: Code Examples"]
    A --> D["references/: API Reference"]
    A --> E["contributing.rst"]
    
    F["sphinx-gallery"] --> C
    G["sphinx-build"] --> H["HTML Output"]
    B --> G
    C --> G
    D --> G
    E --> G
```

Sources: [.readthedocs.yaml:14-16](), [tox.ini:78-89]()

## Release Process

torch-pme follows a structured release process to ensure quality and stability of releases.

### Release Workflow

```mermaid
flowchart LR
    A["Prepare Release PR"] --> B["Update Changelog"]
    B --> C["Merge PR to main"]
    C --> D["Create Git Tag: v0.1.1"]
    D --> E["Push Tag to GitHub"]
    E --> F["GitHub Actions: release.yml"]
    F --> G["Build Package"]
    G --> H["Publish to PyPI"]
    G --> I["Create GitHub Release"]
    I --> J["Update Conda Recipe"]
```

Sources: [CONTRIBUTING.rst:122-169](), [.github/workflows/release.yml:1-42]()

### Release Artifacts

When a release is created, the following artifacts are produced:

1. PyPI package (`torch-pme-x.y.z.tar.gz` and wheel)
2. GitHub Release with attached artifacts
3. Documentation version on the project website
4. Conda-forge package (via automated PR)

Sources: [.github/workflows/release.yml:28-41](), [CONTRIBUTING.rst:156-168]()

## References

For detailed information on specific aspects of development, please refer to:

- [Project Setup](#5.1) - For more details on project structure and configuration
- [Testing](#5.2) - For a comprehensive overview of the testing framework
- [CI/CD](#5.3) - For details on continuous integration and deployment
- [Documentation](#5.4) - For information on the documentation system

---