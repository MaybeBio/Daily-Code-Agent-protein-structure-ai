# Development

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.github/workflows/ci.yml](.github/workflows/ci.yml)
- [.github/workflows/github-to-gitlab-push-sync.yml](.github/workflows/github-to-gitlab-push-sync.yml)
- [.github/workflows/pages.yml](.github/workflows/pages.yml)
- [.github/workflows/validate_citation.yml](.github/workflows/validate_citation.yml)
- [devtools/build_defaults_rst.py](devtools/build_defaults_rst.py)
- [docs/modules/index.rst](docs/modules/index.rst)
- [setup.py](setup.py)
- [src/haddock/modules/_template_cat/README.md](src/haddock/modules/_template_cat/README.md)
- [src/haddock/modules/_template_cat/_template_mod/defaults.yaml](src/haddock/modules/_template_cat/_template_mod/defaults.yaml)
- [tests/test_examples_general.py](tests/test_examples_general.py)
- [tests/test_modules_general.py](tests/test_modules_general.py)
- [tests/test_validations.py](tests/test_validations.py)

</details>



This section provides technical guidance for developers who want to contribute to or extend HADDOCK3. It covers the build system, testing infrastructure, module creation, and documentation generation. For information about using HADDOCK3 as an end-user, see [Getting Started](#2). For information about the module architecture from an execution perspective, see [Module Architecture](#3.2).

## Purpose and Scope

This page provides an architectural overview of HADDOCK3's development infrastructure, explaining how the various development components work together. Detailed information about specific subsystems is available in:

- **Build System** ([8.1](#8.1)): Compilation, binary downloads, and installation modes
- **Testing Infrastructure** ([8.2](#8.2)): Unit tests, integration tests, and CI/CD pipelines  
- **Creating New Modules** ([8.3](#8.3)): Step-by-step guide for implementing custom modules
- **Documentation System** ([8.4](#8.4)): Automated documentation generation from code and YAML

## Development Architecture Overview

HADDOCK3's development infrastructure is organized into four major subsystems that ensure code quality, enable extensibility, and maintain comprehensive documentation. The system supports three installation modes (`pip install`, `pip install -e`, `pip install '[mpi]'`) and validates all code changes through automated testing pipelines.

```mermaid
graph TB
    subgraph "Development Entry Points"
        DevInstall["Developer Installation<br/>pip install -e '.[mpi,dev,docs,notebooks]'"]
        StandardInstall["Standard Installation<br/>pip install ."]
        ContributePR["Contribute Pull Request<br/>Fork & PR to main"]
    end
    
    subgraph "Build System"
        SetupPy["setup.py<br/>CustomBuild class"]
        CompileBinaries["Compile C/C++ Binaries<br/>contact_fcc<br/>fast-rmsdmatrix"]
        DownloadBinaries["Download External Binaries<br/>CNS (SURFdrive)<br/>haddock-restraints (GitHub)"]
        PlatformDetect["Platform Detection<br/>get_arch()<br/>x86_64/arm64/aarch64"]
    end
    
    subgraph "Testing System"
        UnitTests["Unit Tests<br/>tests/*.py<br/>pytest"]
        IntegrationTests["Integration Tests<br/>integration_tests/*.py"]
        ValidationTests["Validation Tests<br/>test_modules_general.py<br/>test_examples_general.py"]
        CI["GitHub Actions CI<br/>ci.yml<br/>Python 3.9-3.14"]
    end
    
    subgraph "Documentation System"
        YAMLDefaults["Module YAML Configs<br/>*/defaults.yaml"]
        BuildDefaultsRst["build_defaults_rst.py<br/>Generate parameter docs"]
        SphinxApidoc["sphinx-apidoc<br/>Generate API docs"]
        SphinxBuild["sphinx-build<br/>Generate HTML"]
    end
    
    subgraph "Module Development"
        Template["Module Template<br/>_template_cat/_template_mod/"]
        ModuleREADME["Development Guide<br/>_template_cat/README.md"]
        DefaultsYAML["Parameter Definition<br/>defaults.yaml"]
        ModuleCode["Module Implementation<br/>__init__.py"]
    end
    
    subgraph "Quality Gates"
        CoverageCheck["Coverage Report<br/>Upload to Codacy"]
        LintCheck["Code Linting<br/>Style checks"]
        DocsCheck["Documentation Build<br/>Verify completeness"]
        ConfigValidation["Configuration Validation<br/>validate_cfg_file()"]
    end
    
    DevInstall --> SetupPy
    StandardInstall --> SetupPy
    ContributePR --> CI
    
    SetupPy --> CompileBinaries
    SetupPy --> DownloadBinaries
    SetupPy --> PlatformDetect
    
    CompileBinaries --> DevInstall
    DownloadBinaries --> DevInstall
    
    CI --> UnitTests
    CI --> IntegrationTests
    CI --> ValidationTests
    
    UnitTests --> CoverageCheck
    IntegrationTests --> CoverageCheck
    ValidationTests --> ConfigValidation
    
    CI --> DocsCheck
    DocsCheck --> BuildDefaultsRst
    DocsCheck --> SphinxApidoc
    
    BuildDefaultsRst --> SphinxBuild
    SphinxApidoc --> SphinxBuild
    YAMLDefaults --> BuildDefaultsRst
    
    Template --> ModuleCode
    ModuleREADME --> ModuleCode
    DefaultsYAML --> ModuleCode
    ModuleCode --> ValidationTests
    
    CoverageCheck --> QualityGates{Quality Gates Pass?}
    LintCheck --> QualityGates
    DocsCheck --> QualityGates
    ConfigValidation --> QualityGates
    
    QualityGates -->|Yes| Merge[Merge to main]
    QualityGates -->|No| Block[Block PR]
    
    Merge --> SphinxBuild
    SphinxBuild --> GitHubPages["GitHub Pages<br/>bonvinlab.org/haddock3"]
```

**Sources:** [setup.py:1-296](), [.github/workflows/ci.yml:1-120](), [devtools/build_defaults_rst.py:1-527](), [src/haddock/modules/_template_cat/README.md:1-31]()

## Development Workflow

The typical development workflow involves setting up a development environment, making changes, running tests locally, and submitting a pull request. The CI/CD pipeline automatically validates all changes before they can be merged.

```mermaid
flowchart TB
    Start([Developer Starts]) --> Clone["git clone<br/>haddocking/haddock3"]
    
    Clone --> SetupEnv["Setup Development Environment<br/>pip install -e '.[mpi,dev,docs,notebooks]'"]
    
    SetupEnv --> BuildProcess["CustomBuild.run()<br/>DevelopCommand.run()"]
    
    BuildProcess --> CompileLocal["Compile Binaries<br/>build_executable('contact_fcc')<br/>build_executable('fast-rmsdmatrix')"]
    
    CompileLocal --> DownloadLocal["Download Binaries<br/>download_binaries()"]
    
    DownloadLocal --> VerifyBins["Verify src/haddock/bin/<br/>contact_fcc, cns,<br/>haddock-restraints,<br/>fast-rmsdmatrix"]
    
    VerifyBins --> DevChoice{Development Task?}
    
    DevChoice -->|New Module| CreateModule["Follow Template<br/>_template_cat/_template_mod/"]
    DevChoice -->|Bug Fix| ModifyCode["Modify Existing Code"]
    DevChoice -->|Documentation| UpdateDocs["Update Docs/YAML"]
    
    CreateModule --> WriteCode["Implement Module<br/>__init__.py<br/>defaults.yaml"]
    ModifyCode --> WriteCode
    UpdateDocs --> WriteCode
    
    WriteCode --> LocalTest["Run Local Tests<br/>pytest tests/<br/>pytest integration_tests/"]
    
    LocalTest --> TestPass{Tests Pass?}
    TestPass -->|No| FixCode["Fix Issues"]
    FixCode --> WriteCode
    
    TestPass -->|Yes| BuildDocs["Build Documentation<br/>sphinx-apidoc<br/>sphinx-build"]
    
    BuildDocs --> DocsPass{Docs Build?}
    DocsPass -->|No| FixDocs["Fix Documentation"]
    FixDocs --> WriteCode
    
    DocsPass -->|Yes| CommitPush["git commit<br/>git push"]
    
    CommitPush --> CreatePR["Create Pull Request"]
    
    CreatePR --> CITrigger["GitHub Actions Triggered<br/>ci.yml"]
    
    CITrigger --> Matrix["Test Matrix<br/>Python 3.9-3.14<br/>Ubuntu Linux"]
    
    Matrix --> RunTests["Run All Tests<br/>Unit + Integration"]
    
    RunTests --> Coverage["Generate Coverage<br/>coverage xml"]
    
    Coverage --> CheckDocs["Check Documentation<br/>sphinx-build docs"]
    
    CheckDocs --> CIPass{CI Pass?}
    
    CIPass -->|No| ReviewFail["Review Failure Logs<br/>Fix Issues"]
    ReviewFail --> FixCode
    
    CIPass -->|Yes| CodeReview["Code Review<br/>by Maintainers"]
    
    CodeReview --> Approved{Approved?}
    Approved -->|No| AddressComments["Address Comments"]
    AddressComments --> WriteCode
    
    Approved -->|Yes| MergeMain["Merge to main"]
    
    MergeMain --> DeployDocs["Deploy Documentation<br/>pages.yml<br/>GitHub Pages"]
    
    DeployDocs --> End([Complete])
```

**Sources:** [.github/workflows/ci.yml:19-120](), [setup.py:183-221](), [src/haddock/modules/_template_cat/README.md:1-31]()

## Build System Architecture

The build system handles compilation of performance-critical C/C++ binaries and downloading of platform-specific external binaries. It supports three installation modes through custom command classes.

### Installation Modes and Custom Commands

| Installation Mode | Command | Purpose | Build Location |
|------------------|---------|---------|----------------|
| Standard | `pip install .` | Production install | `build_lib/haddock/bin/` |
| Editable | `pip install -e .` | Development with live code changes | `src/haddock/bin/` |
| MPI-enabled | `pip install '.[mpi]'` | Parallel execution support | `build_lib/haddock/bin/` + mpi4py |

```mermaid
graph TB
    subgraph "setup.py Command Classes"
        CustomBuild["CustomBuild(build_ext)<br/>setup.py:50-181"]
        DevelopCommand["DevelopCommand(develop)<br/>setup.py:183-221"]
        PostInstallCommand["PostInstallCommand(install)<br/>setup.py:223-287"]
    end
    
    subgraph "Build Operations"
        BuildExec["build_executable(name, cmd)<br/>setup.py:80-104"]
        DownloadBins["download_binaries()<br/>setup.py:106-163"]
        GetArch["get_arch()<br/>setup.py:174-180"]
        CheckCNS["check_cns_binary()<br/>setup.py:232-246"]
    end
    
    subgraph "Compiled Binaries"
        ContactFCC["contact_fcc<br/>C++ source: deps/contact_fcc.cpp<br/>Compiler: g++ -O2"]
        FastRMSD["fast-rmsdmatrix<br/>C source: deps/fast-rmsdmatrix.c<br/>Compiler: gcc -O3 -march=native"]
    end
    
    subgraph "Downloaded Binaries"
        CNS["CNS Binary<br/>SURFdrive URLs<br/>x86_64/arm64 Linux/macOS"]
        HaddockRestraints["haddock-restraints<br/>GitHub Releases v0.10.0<br/>Rust binary .tar.gz"]
    end
    
    subgraph "Binary Dictionary Lookups"
        CNSBinaries["CNS_BINARIES<br/>setup.py:18-23"]
        RestraintsBinaries["HADDOCK_RESTRAINTS_BINARIES<br/>setup.py:25-32"]
    end
    
    subgraph "Output Location"
        SrcBin["src/haddock/bin/<br/>Editable mode"]
        BuildBin["build_lib/haddock/bin/<br/>Standard mode"]
    end
    
    CustomBuild --> BuildExec
    CustomBuild --> DownloadBins
    DevelopCommand --> BuildExec
    DevelopCommand --> DownloadBins
    PostInstallCommand --> CheckCNS
    
    BuildExec --> ContactFCC
    BuildExec --> FastRMSD
    
    DownloadBins --> GetArch
    GetArch --> CNSBinaries
    GetArch --> RestraintsBinaries
    
    CNSBinaries --> CNS
    RestraintsBinaries --> HaddockRestraints
    
    ContactFCC --> SrcBin
    FastRMSD --> SrcBin
    CNS --> SrcBin
    HaddockRestraints --> SrcBin
    
    ContactFCC --> BuildBin
    FastRMSD --> BuildBin
    CNS --> BuildBin
    HaddockRestraints --> BuildBin
    
    CheckCNS --> CNSValid["CNS execution passed ✅<br/>setup.py:277-286"]
    CheckCNS --> CNSWarning["⚠️ CNS could not be executed<br/>setup.py:249-275"]
```

**Sources:** [setup.py:18-296](), [.github/workflows/ci.yml:38-44]()

### Platform Detection and Binary Downloads

The build system detects the platform architecture and downloads appropriate pre-compiled binaries. For non-x86_64 Linux systems, it also downloads the Linux binary for GRID execution compatibility.

| Platform | Architecture | CNS URL | Restraints URL |
|----------|--------------|---------|----------------|
| Linux x86_64 | `x86_64-linux` | SURFdrive/BWa5OimzbNliTi6 | GitHub/x86_64-unknown-linux-musl.tar.gz |
| macOS x86_64 | `x86_64-darwin` | SURFdrive/3Fzzte0Zx0L8GTY | GitHub/x86_64-apple-darwin.tar.gz |
| macOS ARM64 | `arm64-darwin` | SURFdrive/bYB3xPWf7iwo07X | GitHub/aarch64-apple-darwin.tar.gz |
| Linux ARM64 | `aarch64-linux` | SURFdrive/3rHpxcufHGrntHn | GitHub/aarch64-unknown-linux-musl.tar.gz |

**Sources:** [setup.py:18-32](), [setup.py:106-163](), [setup.py:174-180]()

## Testing Infrastructure

HADDOCK3 employs a comprehensive three-tier testing system: unit tests for individual components, integration tests for complete workflows, and validation tests for module structure compliance.

### CI/CD Pipeline Matrix

```mermaid
graph TB
    subgraph "GitHub Actions Triggers"
        PushMain["Push to main<br/>paths: src/, tests/, docs/"]
        PullRequest["Pull Request<br/>Any branch"]
        Schedule["Scheduled Run<br/>Every 6 hours"]
        Manual["Workflow Dispatch<br/>Manual trigger"]
    end
    
    subgraph "Test Matrix Execution"
        Matrix["Test Matrix Strategy<br/>ci.yml:26-29"]
        Py39["Python 3.9<br/>Ubuntu latest"]
        Py310["Python 3.10<br/>Ubuntu latest"]
        Py311["Python 3.11<br/>Ubuntu latest"]
        Py312["Python 3.12<br/>Ubuntu latest"]
        Py313["Python 3.13<br/>Ubuntu latest"]
        Py314["Python 3.14<br/>Ubuntu latest"]
    end
    
    subgraph "Test Execution Steps"
        InstallDeps["Install System Dependencies<br/>openmpi-bin, libopenmpi3"]
        InstallHaddock["pip install '.[mpi,dev,docs,notebooks]'<br/>ci.yml:44"]
        RunUnit["pytest tests/<br/>--random-order --cov<br/>ci.yml:46-49"]
        RunIntegration["pytest integration_tests/<br/>--random-order --cov<br/>ci.yml:51-54"]
        GenerateCoverage["coverage report<br/>coverage xml<br/>ci.yml:56-59"]
        CheckDocs["sphinx-apidoc + sphinx-build<br/>ci.yml:68-72"]
    end
    
    subgraph "Validation Test Types"
        ModuleValidation["Module Structure Validation<br/>test_modules_general.py"]
        ConfigValidation["Configuration File Validation<br/>test_examples_general.py"]
        ParamValidation["Parameter Validation<br/>validate_param_range()"]
    end
    
    subgraph "Coverage Reporting"
        UploadArtifact["Upload coverage.xml<br/>Python 3.14 only"]
        CodacyUpload["Upload to Codacy<br/>coverage-upload job"]
    end
    
    PushMain --> Matrix
    PullRequest --> Matrix
    Schedule --> Matrix
    Manual --> Matrix
    
    Matrix --> Py39
    Matrix --> Py310
    Matrix --> Py311
    Matrix --> Py312
    Matrix --> Py313
    Matrix --> Py314
    
    Py39 --> InstallDeps
    Py310 --> InstallDeps
    Py311 --> InstallDeps
    Py312 --> InstallDeps
    Py313 --> InstallDeps
    Py314 --> InstallDeps
    
    InstallDeps --> InstallHaddock
    InstallHaddock --> RunUnit
    RunUnit --> RunIntegration
    RunIntegration --> GenerateCoverage
    GenerateCoverage --> CheckDocs
    
    RunUnit --> ModuleValidation
    RunUnit --> ConfigValidation
    RunUnit --> ParamValidation
    
    GenerateCoverage --> UploadArtifact
    UploadArtifact --> CodacyUpload
    
    CheckDocs --> Result{All Tests Pass?}
    Result -->|Yes| Success["✅ CI Success"]
    Result -->|No| Failure["❌ CI Failure"]
```

**Sources:** [.github/workflows/ci.yml:1-120](), [tests/test_modules_general.py:1-277](), [tests/test_examples_general.py:1-122]()

### Module Validation Tests

The test suite automatically validates that all modules conform to the required structure. This ensures consistency across the module ecosystem.

```mermaid
graph TB
    subgraph "Module Structure Validation"
        LoadModule["Load Module<br/>importlib.import_module()"]
        CheckDefaults["Check DEFAULT_CONFIG exists<br/>test_all_defaults_have_the_same_name()"]
        ReadYAML["Read defaults.yaml<br/>read_from_yaml_config()"]
    end
    
    subgraph "Parameter Validation"
        CheckKeys["Check Required Keys<br/>inspect_commons()<br/>DOC_KEYS: title, short, long, group, explevel"]
        CheckTypes["Check Type-Specific Keys<br/>inspect_int(), inspect_float(), inspect_list()"]
        CheckDefaults["Check Default Values<br/>inspect_default_value()<br/>validate_param_range()"]
    end
    
    subgraph "Type-Specific Requirements"
        IntParams["Integer Parameters<br/>min, max"]
        FloatParams["Float Parameters<br/>min, max, precision"]
        ListParams["List Parameters<br/>minitems, maxitems"]
        StringParams["String Parameters<br/>minchars, maxchars"]
    end
    
    subgraph "Configuration Validation"
        ValidateModuleNames["validate_module_names_are_not_misspelled()<br/>test_examples_general.py:104"]
        ValidateParamNames["validate_parameters_are_not_misspelled()<br/>test_examples_general.py:111"]
        ValidateModuleParams["validate_modules_params()<br/>test_examples_general.py:116"]
    end
    
    LoadModule --> CheckDefaults
    CheckDefaults --> ReadYAML
    ReadYAML --> CheckKeys
    
    CheckKeys --> CheckTypes
    CheckTypes --> CheckDefaults
    
    CheckTypes --> IntParams
    CheckTypes --> FloatParams
    CheckTypes --> ListParams
    CheckTypes --> StringParams
    
    ReadYAML --> ValidateModuleNames
    ValidateModuleNames --> ValidateParamNames
    ValidateParamNames --> ValidateModuleParams
```

**Sources:** [tests/test_modules_general.py:32-205](), [tests/test_examples_general.py:69-122]()

## Module Development System

HADDOCK3 provides a template-based system for creating new modules. The module template includes all required files and extensive documentation.

### Module Template Structure

```mermaid
graph TB
    subgraph "Template Location"
        TemplateDir["src/haddock/modules/<br/>_template_cat/_template_mod/"]
    end
    
    subgraph "Required Files"
        InitPy["__init__.py<br/>Module implementation<br/>HaddockModule class"]
        DefaultsYAML["defaults.yaml<br/>Parameter definitions<br/>Type specifications"]
        README["README.md<br/>Development instructions"]
    end
    
    subgraph "Parameter Types Supported"
        IntegerType["integer<br/>default, min, max"]
        FloatType["float<br/>default, min, max, precision"]
        StringType["string<br/>default, minchars, maxchars, choices"]
        ListType["list<br/>default, minitems, maxitems"]
        BooleanType["boolean<br/>default"]
        FileType["file<br/>default (path)"]
        DictType["dict<br/>Nested parameters"]
    end
    
    subgraph "Expertise Levels"
        Easy["easy<br/>Basic parameters<br/>Shown by default"]
        Expert["expert<br/>Advanced parameters<br/>For experienced users"]
        Guru["guru<br/>Expert parameters<br/>For specialists"]
        Hidden["hidden<br/>Internal parameters<br/>Not shown in docs"]
    end
    
    subgraph "Development Steps"
        Step1["1. Create category folder<br/>if new category"]
        Step2["2. Create module folder<br/>with module name"]
        Step3["3. Copy template files<br/>__init__.py, defaults.yaml"]
        Step4["4. Implement module logic<br/>Inherit BaseHaddockModule"]
        Step5["5. Define parameters<br/>Complete defaults.yaml"]
        Step6["6. Write tests<br/>tests/test_module_*.py"]
        Step7["7. Add example<br/>examples/module-example-test.cfg"]
    end
    
    TemplateDir --> InitPy
    TemplateDir --> DefaultsYAML
    TemplateDir --> README
    
    DefaultsYAML --> IntegerType
    DefaultsYAML --> FloatType
    DefaultsYAML --> StringType
    DefaultsYAML --> ListType
    DefaultsYAML --> BooleanType
    DefaultsYAML --> FileType
    DefaultsYAML --> DictType
    
    IntegerType --> Easy
    FloatType --> Expert
    StringType --> Guru
    ListType --> Hidden
    
    README --> Step1
    Step1 --> Step2
    Step2 --> Step3
    Step3 --> Step4
    Step4 --> Step5
    Step5 --> Step6
    Step6 --> Step7
```

**Sources:** [src/haddock/modules/_template_cat/_template_mod/defaults.yaml:1-107](), [src/haddock/modules/_template_cat/README.md:1-31]()

### Parameter Definition Example

The template provides examples for all supported parameter types with required fields:

| Parameter Type | Required Fields | Optional Fields | Example Default |
|---------------|----------------|-----------------|-----------------|
| `integer` | `default`, `type`, `min`, `max` | `choices` | `42` |
| `float` | `default`, `type`, `min`, `max`, `precision` | - | `0.2` |
| `string` | `default`, `type`, `minchars`, `maxchars` | `choices` | `"keep"` |
| `list` | `default`, `type`, `minitems`, `maxitems` | - | `[]` |
| `boolean` | `default`, `type` | - | `true` |
| `file` | `default`, `type` | - | `"path/to/file"` |
| `dict` | `explevel`, `title`, `short`, `long`, `group` | - | `{}` |

All parameters require documentation fields: `title`, `short`, `long`, `group`, `explevel`.

**Sources:** [src/haddock/modules/_template_cat/_template_mod/defaults.yaml:10-107]()

## Documentation Generation System

HADDOCK3 automatically generates comprehensive documentation from YAML configuration files and Python docstrings. The system organizes documentation by module category and expertise level.

```mermaid
graph TB
    subgraph "Documentation Sources"
        YAMLConfigs["Module defaults.yaml<br/>All modules/*/defaults.yaml"]
        PythonCode["Python Source Code<br/>src/haddock/**/*.py"]
        RSTFiles["Manual RST Files<br/>docs/**/*.rst"]
    end
    
    subgraph "build_defaults_rst.py"
        Main["main()<br/>devtools/build_defaults_rst.py:267"]
        LoopModules["Loop Module Configs<br/>Path('modules/*/*/**.yaml')"]
        ProcessCategory["process_category_file()<br/>Create category/index.rst"]
        ProcessModule["process_module_file()<br/>Create category/module.rst"]
        BuildRST["build_rst(module_params)<br/>Generate parameter docs"]
    end
    
    subgraph "RST Generation"
        LoopParams["loop_params(config)<br/>Sort and categorize"]
        EasySection["Easy Parameters<br/>explevel='easy'"]
        ExpertSection["Expert Parameters<br/>explevel='expert'"]
        GuruSection["Guru Parameters<br/>explevel='guru'"]
        DoText["do_text(name, param)<br/>Format parameter entry"]
    end
    
    subgraph "sphinx-apidoc"
        GenerateAPI["sphinx-apidoc -f -e<br/>-o docs/ src/haddock -d 1"]
        APIModules["API Documentation<br/>Auto-generated RST"]
    end
    
    subgraph "sphinx-build"
        BuildHTML["sphinx-build docs haddock3-docs"]
        StaticHTML["HTML Documentation<br/>haddock3-docs/"]
    end
    
    subgraph "Title Mapping"
        ModuleDict["MODULE_TITLE_DICT<br/>devtools/build_defaults_rst.py:22-47"]
        CategoryDict["CATEGORY_TITLE_DICT<br/>devtools/build_defaults_rst.py:49-56"]
        ReferenceDict["REFERENCE_TITLE_DICT<br/>devtools/build_defaults_rst.py:58-104"]
        CLIDict["CLI_TITLE_DICT<br/>devtools/build_defaults_rst.py:106-123"]
    end
    
    subgraph "Deployment"
        GitHubPages["GitHub Pages<br/>bonvinlab.org/haddock3<br/>pages.yml"]
    end
    
    YAMLConfigs --> LoopModules
    LoopModules --> ProcessCategory
    ProcessCategory --> ProcessModule
    ProcessModule --> BuildRST
    
    BuildRST --> LoopParams
    LoopParams --> EasySection
    LoopParams --> ExpertSection
    LoopParams --> GuruSection
    LoopParams --> DoText
    
    ModuleDict --> ProcessModule
    CategoryDict --> ProcessCategory
    ReferenceDict --> ProcessModule
    CLIDict --> ProcessModule
    
    PythonCode --> GenerateAPI
    GenerateAPI --> APIModules
    
    EasySection --> BuildHTML
    ExpertSection --> BuildHTML
    GuruSection --> BuildHTML
    RSTFiles --> BuildHTML
    APIModules --> BuildHTML
    
    BuildHTML --> StaticHTML
    StaticHTML --> GitHubPages
```

**Sources:** [devtools/build_defaults_rst.py:1-527](), [.github/workflows/pages.yml:33-37]()

### Documentation Organization

The documentation system organizes content hierarchically:

1. **Module Documentation** (organized by category):
   - `docs/modules/topology/` - Topology module docs
   - `docs/modules/sampling/` - Sampling module docs
   - `docs/modules/refinement/` - Refinement module docs
   - `docs/modules/scoring/` - Scoring module docs
   - `docs/modules/analysis/` - Analysis module docs
   - `docs/modules/extras/` - Extra module docs

2. **Parameter Documentation** (organized by expertise level):
   - Easy parameters appear first
   - Expert parameters in second section
   - Guru parameters in third section
   - Hidden parameters excluded from docs

3. **Reference Documentation**:
   - `docs/reference/core/` - Core system reference
   - `docs/reference/gear/` - Workflow orchestration reference
   - `docs/reference/libs/` - Library utilities reference

4. **Command-Line Documentation**:
   - `docs/clients/` - CLI tool documentation

**Sources:** [devtools/build_defaults_rst.py:188-388](), [docs/modules/index.rst:1-42]()

## Quality Assurance System

HADDOCK3 enforces quality through multiple automated validation layers that run on every commit and pull request.

### Validation Layers

```mermaid
graph TB
    subgraph "Code Quality Checks"
        Linting["Code Linting<br/>Style enforcement"]
        TypeChecking["Type Checking<br/>Type hints validation"]
    end
    
    subgraph "Structural Validation"
        ModuleStructure["Module Structure<br/>test_modules_general.py<br/>Check __init__.py, defaults.yaml"]
        CategoryHierarchy["Category Hierarchy<br/>test_category_hierarchy()<br/>Validate category_hierarchy"]
        ConfigReaders["Config Readers<br/>test_config_readers_keys()<br/>Validate .yaml, .cfg support"]
    end
    
    subgraph "Configuration Validation"
        YAMLValidation["YAML Parameter Validation<br/>inspect_types(d, module)<br/>Check all required keys"]
        DefaultValidation["Default Value Validation<br/>inspect_default_value()<br/>validate_param_range()"]
        ExampleValidation["Example Config Validation<br/>test_validate_cfg_files()<br/>Validate all examples/*.cfg"]
    end
    
    subgraph "Functional Testing"
        UnitTests["Unit Tests<br/>tests/*.py<br/>Test individual components"]
        IntegrationTests["Integration Tests<br/>integration_tests/*.py<br/>Test complete workflows"]
        BinaryVerification["Binary Verification<br/>Check executability<br/>src/haddock/bin/*"]
    end
    
    subgraph "Documentation Validation"
        SphinxBuild["Sphinx Build Check<br/>sphinx-build docs<br/>continue-on-error: true"]
        CompletenessCheck["Completeness Check<br/>Verify all modules documented"]
    end
    
    subgraph "Coverage Requirements"
        CoverageReport["Coverage Report<br/>coverage report<br/>coverage xml"]
        CodacyUpload["Codacy Upload<br/>Track coverage trends"]
    end
    
    Linting --> QualityGates{Quality Gates}
    TypeChecking --> QualityGates
    
    ModuleStructure --> QualityGates
    CategoryHierarchy --> QualityGates
    ConfigReaders --> QualityGates
    
    YAMLValidation --> QualityGates
    DefaultValidation --> QualityGates
    ExampleValidation --> QualityGates
    
    UnitTests --> CoverageReport
    IntegrationTests --> CoverageReport
    BinaryVerification --> QualityGates
    
    SphinxBuild --> QualityGates
    CompletenessCheck --> QualityGates
    
    CoverageReport --> CodacyUpload
    CodacyUpload --> QualityGates
    
    QualityGates -->|Pass| MergePR["✅ Allow Merge"]
    QualityGates -->|Fail| BlockPR["❌ Block Merge"]
```

**Sources:** [tests/test_modules_general.py:1-277](), [tests/test_examples_general.py:1-122](), [.github/workflows/ci.yml:46-72]()

## Continuous Integration Matrix

HADDOCK3 tests against six Python versions to ensure broad compatibility. Each version runs the complete test suite independently.

| Python Version | Test Status | Coverage | Notes |
|---------------|-------------|----------|-------|
| 3.9 | ✅ Required | Included | Minimum supported version |
| 3.10 | ✅ Required | Included | Documentation build version |
| 3.11 | ✅ Required | Included | Stable release |
| 3.12 | ✅ Required | Included | Recent stable |
| 3.13 | ✅ Required | Included | Latest stable |
| 3.14 | ✅ Required | **Uploaded to Codacy** | Latest Python version |

The CI pipeline runs:
- On every push to `main` branch
- On every pull request
- Every 6 hours (scheduled)
- On manual trigger (`workflow_dispatch`)

**Sources:** [.github/workflows/ci.yml:26-87]()

## Additional Infrastructure

### Repository Synchronization

HADDOCK3 maintains a mirror on GitLab for specific user communities:

- **Primary Repository**: `github.com/haddocking/haddock3`
- **Mirror Repository**: `codehub.hlrs.de/coes/bioexcel/haddock3.git`
- **Sync Trigger**: On tag creation
- **Implementation**: [.github/workflows/github-to-gitlab-push-sync.yml:1-26]()

### Citation Validation

The repository validates citation metadata on every change to `CITATION.cff`:

- **Validator**: `dieghernan/cff-validator@v3`
- **Trigger**: Pull requests modifying `CITATION.cff`
- **Implementation**: [.github/workflows/validate_citation.yml:1-18]()

**Sources:** [.github/workflows/github-to-gitlab-push-sync.yml:1-26](), [.github/workflows/validate_citation.yml:1-18]()

## Getting Started with Development

To begin developing HADDOCK3:

1. **Clone the repository**: `git clone https://github.com/haddocking/haddock3.git`
2. **Install development dependencies**: `pip install -e '.[mpi,dev,docs,notebooks]'`
3. **Verify installation**: Check that binaries exist in `src/haddock/bin/`
4. **Run tests**: `pytest tests/ integration_tests/`
5. **Build documentation**: `sphinx-apidoc -f -e -o docs/ src/haddock -d 1 && sphinx-build docs haddock3-docs`

For detailed information about specific development tasks:
- **Building and installing**: See [Build System](#8.1)
- **Writing and running tests**: See [Testing Infrastructure](#8.2)
- **Creating a new module**: See [Creating New Modules](#8.3)
- **Updating documentation**: See [Documentation System](#8.4)

**Sources:** [.github/workflows/ci.yml:38-72](), [setup.py:1-296](), [src/haddock/modules/_template_cat/README.md:1-31]()

---