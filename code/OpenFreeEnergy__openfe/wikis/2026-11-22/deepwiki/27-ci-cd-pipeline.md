# CI/CD Pipeline

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.github/workflows/check_for_api_break.yaml](.github/workflows/check_for_api_break.yaml)
- [.github/workflows/ci.yaml](.github/workflows/ci.yaml)
- [.github/workflows/conda_cron.yaml](.github/workflows/conda_cron.yaml)
- [.github/workflows/cpu-long-tests.yaml](.github/workflows/cpu-long-tests.yaml)
- [.github/workflows/gen-lock-file.yaml](.github/workflows/gen-lock-file.yaml)
- [.github/workflows/gpu-integration-tests.yaml](.github/workflows/gpu-integration-tests.yaml)
- [.github/workflows/installer.yaml](.github/workflows/installer.yaml)
- [.github/workflows/mypy.yaml](.github/workflows/mypy.yaml)

</details>



This document describes the Continuous Integration and Continuous Deployment (CI/CD) pipeline used by the OpenFE project. The pipeline ensures code quality, test coverage, and proper packaging of the software through automated processes.

## Overview

OpenFE employs GitHub Actions to manage its CI/CD pipeline, with multiple workflows that handle different aspects of testing, validation, and deployment. These workflows automatically run when code changes are pushed, pull requests are created, or on a scheduled basis.

```mermaid
flowchart TD
    subgraph "GitHub Repository"
        PR["Pull Request"]
        Push["Push to main"]
        Schedule["Scheduled Run"]
        Release["Release Event"]
    end
    
    subgraph "CI Workflows"
        MainCI["Main CI Tests"]
        TypeCheck["Type Checking"]
        PkgTests["Package Tests"]
    end
    
    subgraph "Documentation Pipeline"
        DocsBuild["Documentation Build"]
        RTD["ReadTheDocs Deployment"]
    end
    
    subgraph "Coverage & Analysis"
        CodeCov["Codecov Analysis"]
    end
    
    PR --> MainCI
    PR --> TypeCheck
    PR --> PkgTests
    
    Push --> MainCI
    Push --> TypeCheck
    Push --> PkgTests
    Push --> DocsBuild
    
    Schedule --> MainCI
    Schedule --> PkgTests
    
    Release --> MainCI
    
    MainCI --> CodeCov
    
    DocsBuild --> RTD
```

Sources: [.github/workflows/ci.yaml:1-146](), [.github/workflows/mypy.yaml:1-57](), [.github/workflows/package-tests.yaml:1-76](), [docs/conf.py:1-252]()

## Main CI Workflow

The core CI workflow performs comprehensive testing across multiple configurations to ensure the codebase works correctly in various environments.

### Workflow Triggers

The main CI workflow (`ci.yaml`) runs:
- On all pull requests to the main branch
- When code is pushed to the main branch
- On a daily schedule at 07:00 UTC
- When manually triggered using the workflow_dispatch event
- When a release is published

```mermaid
stateDiagram-v2
    [*] --> Triggered
    
    state Triggered {
        [*] --> PR_Created
        [*] --> Push_to_Main
        [*] --> Daily_Schedule
        [*] --> Manual_Trigger
        [*] --> Release_Published
    }
    
    Triggered --> Setup
    
    state Setup {
        [*] --> Checkout_Code
        Checkout_Code --> Setup_Environment
        Setup_Environment --> Install_Package
    }
    
    Setup --> Tests
    
    state Tests {
        [*] --> Run_Tests
        Run_Tests --> Generate_Coverage
    }
    
    Tests --> Upload_Results
    
    state Upload_Results {
        [*] --> Upload_to_Codecov
    }
    
    Upload_Results --> [*]
```

Sources: [.github/workflows/ci.yaml:1-20]()

### Matrix Strategy

One of the most important features of the CI pipeline is its matrix testing strategy, which runs tests across multiple combinations of:
- Operating systems (Ubuntu and macOS)
- Python versions (3.10, 3.11, 3.12)
- Pydantic versions (version 1 and version 2 compatibility)
- With and without OpenEye toolkit

```mermaid
flowchart LR
    subgraph "Matrix Configurations"
        subgraph "Operating Systems"
            Ubuntu["ubuntu-latest"]
            macOS["macos-latest"]
        end
        
        subgraph "Python Versions"
            Py310["Python 3.10"]
            Py311["Python 3.11"]
            Py312["Python 3.12"]
        end
        
        subgraph "Pydantic Versions"
            PydanticV1["Pydantic <2"]
            PydanticV2["Pydantic >1"]
        end
        
        subgraph "Optional Dependencies"
            WithOE["With OpenEye"]
            WithoutOE["Without OpenEye"]
        end
    end
    
    subgraph "Test Job"
        Setup["Setup Environment"]
        Install["Install OpenFE"]
        Test["Run Tests"]
        Coverage["Generate Coverage"]
    end
    
    Ubuntu & macOS --> Setup
    Py310 & Py311 & Py312 --> Setup
    PydanticV1 & PydanticV2 --> Setup
    WithOE & WithoutOE --> Setup
    
    Setup --> Install --> Test --> Coverage
```

Sources: [.github/workflows/ci.yaml:31-59]()

## Type Checking Workflow

A separate workflow performs static type checking using mypy to ensure type safety across the codebase.

```mermaid
flowchart TD
    PRorPush["PR or Push to main"] --> Checkout["Checkout Code"]
    Checkout --> SetupEnv["Setup Micromamba Environment"]
    SetupEnv --> InstallMypy["Install mypy"]
    InstallMypy --> RunMypy["Run mypy Type Checking"]
```

Sources: [.github/workflows/mypy.yaml:1-57]()

## Package Installation Tests

This workflow verifies that the package can be properly built, installed, and used by end-users.

```mermaid
flowchart TD
    Trigger["PR, Push, Schedule, or Manual Trigger"] --> Checkout["Checkout Code"]
    Checkout --> Setup["Setup Environment"]
    Setup --> BuildSDist["Build Source Distribution"]
    BuildSDist --> CheckPackage["Check Package with twine"]
    CheckPackage --> InstallFromSDist["Install from Source Distribution"]
    InstallFromSDist --> RunTests["Run Tests on Installed Package"]
```

Sources: [.github/workflows/package-tests.yaml:1-76]()

## Environment Management

The CI/CD pipeline uses Micromamba (a lightweight version of Conda) to manage test environments, ensuring consistent dependency versions across all test runs.

### Dependencies Specification

The environment is defined in the `environment.yml` file which lists all the dependencies required to build, test, and run OpenFE.

```mermaid
flowchart LR
    subgraph "Environment Setup Process"
        EnvFile["environment.yml"]
        MicromambaAction["mamba-org/setup-micromamba@v1"]
        CacheEnv["Cache Environment"]
        CacheDownloads["Cache Downloads"]
        InstallDeps["Install Dependencies"]
    end
    
    EnvFile --> MicromambaAction
    MicromambaAction --> CacheEnv
    MicromambaAction --> CacheDownloads
    MicromambaAction --> InstallDeps
```

Sources: [environment.yml:1-56](), [.github/workflows/ci.yaml:73-87](), [.github/workflows/mypy.yaml:28-41](), [.github/workflows/package-tests.yaml:39-51]()

## Documentation Pipeline

Documentation for OpenFE is built using Sphinx and deployed to ReadTheDocs.

### Documentation Build Process

```mermaid
flowchart TD
    subgraph "Documentation Sources"
        DocFiles["Documentation Files"]
        SourceCode["Source Code (docstrings)"]
        Notebooks["Example Notebooks"]
    end
    
    subgraph "Sphinx Build"
        SphinxConf["conf.py Configuration"]
        Extensions["Sphinx Extensions"]
        ThemeConfig["Theme Configuration"]
    end
    
    subgraph "Output"
        HTML["HTML Documentation"]
        RTD["ReadTheDocs Deployment"]
    end
    
    DocFiles --> SphinxConf
    SourceCode --> SphinxConf
    Notebooks --> SphinxConf
    
    SphinxConf --> Extensions
    SphinxConf --> ThemeConfig
    
    Extensions --> HTML
    ThemeConfig --> HTML
    
    HTML --> RTD
```

Sources: [docs/conf.py:1-252](), [docs/environment.yaml:1-38](), [docs/_ext/sass.py:1-89]()

## Code Coverage Analysis

OpenFE uses Codecov to track code coverage across the codebase, with different reporting strategies for pull requests vs. main branch updates.

```mermaid
flowchart TD
    Tests["Run tests with pytest-cov"] --> CoverageXML["Generate coverage.xml"]
    
    CoverageXML --> PRCoverage["Upload to Codecov (PR)"]
    CoverageXML --> MainCoverage["Upload to Codecov (main branch)"]
    
    PRCoverage -- "fast-tests flag" --> Codecov["Codecov Dashboard"]
    MainCoverage -- "slow-tests flag" --> Codecov
```

Sources: [.github/workflows/ci.yaml:118-145]()

## Workflow Dependencies and Integration

The following diagram shows how the different workflows in the CI/CD pipeline interact with each other and with the development workflow:

```mermaid
flowchart TD
    Developer["Developer"] --> CreatePR["Create Pull Request"]
    
    CreatePR --> MainCI["Main CI Workflow"]
    CreatePR --> TypeCheck["Type Checking Workflow"]
    CreatePR --> PkgTests["Package Tests Workflow"]
    
    MainCI --> CodeCov["Coverage Report"]
    
    MainCI & TypeCheck & PkgTests --> PRApproval["PR Approval Process"]
    
    PRApproval --> MergePR["Merge PR to main"]
    
    MergePR --> MainCI_Main["Main CI on main"]
    MergePR --> TypeCheck_Main["Type Check on main"]
    MergePR --> PkgTests_Main["Package Tests on main"]
    MergePR --> DocsBuild["Documentation Build"]
    
    MainCI_Main --> Release["Create Release"]
    
    Release --> ReleaseCI["CI on Release"]
```

Sources: [.github/workflows/ci.yaml:1-146](), [.github/workflows/mypy.yaml:1-57](), [.github/workflows/package-tests.yaml:1-76]()

## Slow Tests Strategy

OpenFE differentiates between fast and slow tests, running all tests for main branch and scheduled runs, but only fast tests for pull requests. This is controlled by the `OFE_SLOW_TESTS` environment variable.

```mermaid
flowchart LR
    subgraph "Test Execution Strategy"
        PRBuild["PR Build"]
        MainBuild["Main Branch Build"]
        ScheduledBuild["Scheduled Build"]
        
        PRBuild --> FastTestsOnly["OFE_SLOW_TESTS=false\nRun Fast Tests Only"]
        MainBuild --> AllTests["OFE_SLOW_TESTS=true\nRun All Tests"]
        ScheduledBuild --> AllTests
    end
```

Sources: [.github/workflows/ci.yaml:114-117](), [.github/workflows/package-tests.yaml:71-75]()

## Scheduling Strategy

The CI pipeline includes scheduled runs to catch issues that might arise from external dependency changes or intermittent failures.

```mermaid
flowchart TD
    DailyRun["Daily Run at 07:00 UTC"] --> MainCI["Run Main CI"]
    DailyRun --> PkgTests["Run Package Tests"]
    
    MainCI --> SlowTests["Run Slow Tests"]
    PkgTests --> BuildCheck["Check Package Building"]
```

Sources: [.github/workflows/ci.yaml:14-16](), [.github/workflows/package-tests.yaml:16-18]()

---