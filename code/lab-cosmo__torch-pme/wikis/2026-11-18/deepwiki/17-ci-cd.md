# CI/CD

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

</details>



This document details the Continuous Integration (CI) and Continuous Deployment (CD) pipelines used in the torch-pme project. These automated workflows help ensure code quality, test coverage, and streamline the release process. For information about test structure and writing tests, see [Testing](#5.2). For project setup details, see [Project Setup](#5.1).

## CI/CD Infrastructure Overview

The torch-pme project uses GitHub Actions as its primary CI/CD platform. All workflows are defined in the `.github/workflows/` directory.

```mermaid
flowchart TB
    subgraph "GitHub Actions Workflows"
        tests["tests.yml: Testing"]
        docs["docs.yml: Documentation"]
        build["build.yml: Package Building"]
        lint["lint.yml: Code Quality"]
        release["release.yml: Releases"]
    end

    subgraph "External Services"
        codecov["Codecov: Coverage Reporting"]
        ghpages["GitHub Pages: Docs Hosting"]
        pypi["PyPI: Package Distribution"]
        ghrel["GitHub Releases: Package Artifacts"]
    end

    tests --> codecov
    docs --> ghpages
    release --> pypi
    release --> ghrel

    subgraph "Triggers"
        pr["Pull Requests"]
        main["Push to main"]
        tag["Push tags"]
    end

    pr --> tests & docs & build & lint
    main --> tests & docs & build
    tag --> docs & release
```

Sources: [.github/workflows/tests.yml](), [.github/workflows/docs.yml](), [.github/workflows/build.yml](), [.github/workflows/lint.yml](), [.github/workflows/release.yml]()

## Continuous Integration Workflows

### Testing Workflow

The testing workflow ensures that the codebase works correctly across different operating systems and Python versions.

```mermaid
flowchart TD
    trigger["Trigger: 
    - Push to main
    - Pull Request"]

    subgraph "Job: min"
        min_checkout["Checkout code"]
        min_setup["Setup Python"]
        min_install["Install tox"]
        min_test["Run minimal tests: 
        tox -e tests-min"]
    end

    subgraph "Job: all"
        all_checkout["Checkout code"]
        all_setup["Setup Python"] 
        all_install["Install tox"]
        all_test["Run all tests: 
        tox -e tests"]
        all_coverage["Generate coverage XML"]
        all_upload["Upload to codecov.io"]
    end

    trigger --> min_checkout & all_checkout
    min_checkout --> min_setup --> min_install --> min_test
    all_checkout --> all_setup --> all_install --> all_test --> all_coverage --> all_upload

    subgraph "Matrix Strategy"
        ubuntu9["Ubuntu 22.04, Python 3.9"]
        ubuntu13["Ubuntu 22.04, Python 3.13"]
        macos["macOS 14, Python 3.13"]
        windows["Windows 2022, Python 3.13"]
    end

    min_checkout -.-> ubuntu9 & ubuntu13 & macos & windows
    all_checkout -.-> ubuntu9 & ubuntu13 & macos & windows
```

The testing workflow runs two jobs:
1. **min**: Runs minimal tests across all platform configurations
2. **all**: Runs comprehensive tests and collects coverage data

Both jobs are executed on a matrix of operating systems and Python versions to ensure compatibility across environments.

Sources: [.github/workflows/tests.yml]()

### Documentation Workflow

The documentation workflow builds the project's documentation and deploys it to GitHub Pages.

```mermaid
flowchart TD
    trigger["Trigger:
    - Push to main
    - Push tags
    - Pull Request"]
    
    checkout["Checkout code"]
    setup["Setup Python 3.13"]
    install["Install tox"]
    build["Build docs: tox -e docs"]
    prepare["Prepare for deployment"]
    
    subgraph "Conditional Steps"
        direction TB
        if_tag{"Is tag?"}
        tag_action["Move docs to version-specific directory"]
        main_action["Move docs to 'latest' directory"]
        if_tag -->|Yes| tag_action
        if_tag -->|No| main_action
    end
    
    deploy{"Is push event?"}
    gh_pages["Deploy to GitHub Pages"]
    
    trigger --> checkout --> setup --> install --> build --> prepare
    prepare --> if_tag
    tag_action & main_action --> deploy
    deploy -->|Yes| gh_pages
```

The documentation workflow:
1. Builds the documentation using Sphinx via tox
2. For tags, creates version-specific documentation
3. For pushes to main, updates the "latest" documentation
4. Deploys the documentation to GitHub Pages for push events

Sources: [.github/workflows/docs.yml]()

### Build Workflow

The build workflow ensures the package can be built properly.

```mermaid
flowchart TD
    trigger["Trigger:
    - Push to main
    - Pull Request"]
    checkout["Checkout code"]
    setup["Setup Python 3.13"]
    install["Install tox"]
    build["Build package: tox -e build"]
    
    trigger --> checkout --> setup --> install --> build
```

This workflow verifies that the package can be built successfully but does not publish it.

Sources: [.github/workflows/build.yml]()

### Linting Workflow

The linting workflow checks code quality.

```mermaid
flowchart TD
    trigger["Trigger:
    - Pull Request to main"]
    checkout["Checkout code"]
    setup["Setup Python 3.13"]
    install["Install tox"]
    lint["Run linting: tox -e lint"]
    
    trigger --> checkout --> setup --> install --> lint
```

This workflow runs code quality checks for pull requests to ensure they meet the project's standards before merging.

Sources: [.github/workflows/lint.yml]()

## Continuous Deployment Workflow

### Release Workflow

The release workflow automates the process of publishing new releases.

```mermaid
flowchart TD
    trigger["Trigger:
    - Push tags"]
    checkout["Checkout code"]
    setup["Setup Python 3.13"]
    install["Install tox"]
    build["Build package: tox -e build"]
    
    if_tag{"Tag starts with 'v'?"}
    pypi["Publish to PyPI"]
    github["Create GitHub Release"]
    
    trigger --> checkout --> setup --> install --> build --> if_tag
    if_tag -->|Yes| pypi & github
```

The release workflow:
1. Builds the package when a tag is pushed
2. If the tag starts with 'v', publishes the package to PyPI
3. Creates a GitHub release with the package artifacts

Sources: [.github/workflows/release.yml]()

## Additional CI Services

### Codecov Integration

Codecov is used for tracking code coverage. Its configuration is defined in `.codecov.yml`.

Key settings include:
- **Ignore pattern**: Tests directory (`tests/.*`) is excluded from coverage calculations
- **Coverage target**: 90% project-wide coverage
- **Patch status**: Disabled
- **Comments**: Disabled

Sources: [.codecov.yml]()

### ReadTheDocs Integration

While GitHub Pages is the primary documentation hosting, the project also has ReadTheDocs configuration in `.readthedocs.yaml`.

Key settings include:
- **Python version**: 3.13
- **Documentation location**: `docs/src/conf.py`
- **Additional formats**: PDF
- **Installation requirements**: Requirements from `docs/requirements.txt`
- **Extra requirements**: `examples` and `metatensor`

Sources: [.readthedocs.yaml]()

## CI/CD Workflow Matrix

The following table summarizes when each workflow is triggered:

| Workflow | Push to main | Pull Request | Push tags |
|----------|--------------|--------------|-----------|
| Tests    | ✅           | ✅           | ❌        |
| Documentation | ✅      | ✅           | ✅        |
| Build    | ✅           | ✅           | ❌        |
| Lint     | ❌           | ✅           | ❌        |
| Release  | ❌           | ❌           | ✅        |

## Workflow to Code Mapping

The following diagram maps workflow files to their corresponding functionality:

```mermaid
classDiagram
    class WorkflowFiles {
        tests.yml
        docs.yml
        build.yml
        lint.yml
        release.yml
    }
    
    class TestingSystem {
        tox -e tests-min
        tox -e tests
        coverage xml
        codecov upload
    }
    
    class DocumentationSystem {
        tox -e docs
        gh-pages deployment
        version directories
    }
    
    class BuildSystem {
        tox -e build
    }
    
    class LintSystem {
        tox -e lint
    }
    
    class ReleaseSystem {
        PyPI publishing
        GitHub Releases
    }
    
    WorkflowFiles --> TestingSystem: "tests.yml"
    WorkflowFiles --> DocumentationSystem: "docs.yml"
    WorkflowFiles --> BuildSystem: "build.yml"
    WorkflowFiles --> LintSystem: "lint.yml"
    WorkflowFiles --> ReleaseSystem: "release.yml"
    
    TestingSystem --> CodecovConfig: ".codecov.yml"
    DocumentationSystem --> ReadTheDocsConfig: ".readthedocs.yaml"
```

Sources: [.github/workflows/tests.yml](), [.github/workflows/docs.yml](), [.github/workflows/build.yml](), [.github/workflows/lint.yml](), [.github/workflows/release.yml](), [.codecov.yml](), [.readthedocs.yaml]()

---