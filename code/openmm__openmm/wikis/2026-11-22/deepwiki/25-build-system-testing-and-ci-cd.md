# Build System and CI/CD

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.travis.yml](.travis.yml)
- [CMakeLists.txt](CMakeLists.txt)
- [appveyor.yml](appveyor.yml)
- [devtools/run-ctest.py](devtools/run-ctest.py)
- [examples/python-examples/argon-chemical-potential.py](examples/python-examples/argon-chemical-potential.py)
- [platforms/cpu/CMakeLists.txt](platforms/cpu/CMakeLists.txt)
- [plugins/amoeba/CMakeLists.txt](plugins/amoeba/CMakeLists.txt)
- [plugins/amoeba/platforms/reference/CMakeLists.txt](plugins/amoeba/platforms/reference/CMakeLists.txt)
- [plugins/drude/CMakeLists.txt](plugins/drude/CMakeLists.txt)
- [plugins/drude/platforms/reference/CMakeLists.txt](plugins/drude/platforms/reference/CMakeLists.txt)
- [plugins/drude/wrappers/CMakeLists.txt](plugins/drude/wrappers/CMakeLists.txt)
- [plugins/drude/wrappers/Doxyfile.in](plugins/drude/wrappers/Doxyfile.in)
- [plugins/drude/wrappers/generateDrudeWrappers.py](plugins/drude/wrappers/generateDrudeWrappers.py)
- [plugins/rpmd/CMakeLists.txt](plugins/rpmd/CMakeLists.txt)
- [plugins/rpmd/platforms/reference/CMakeLists.txt](plugins/rpmd/platforms/reference/CMakeLists.txt)
- [serialization/CMakeLists.txt](serialization/CMakeLists.txt)
- [wrappers/python/openmm/unit/mymatrix.py](wrappers/python/openmm/unit/mymatrix.py)
- [wrappers/python/openmm/unit/quantity.py](wrappers/python/openmm/unit/quantity.py)
- [wrappers/python/openmm/unit/unit.py](wrappers/python/openmm/unit/unit.py)
- [wrappers/python/tests/TestUnits.py](wrappers/python/tests/TestUnits.py)
- [wrappers/python/tests/pytest.ini](wrappers/python/tests/pytest.ini)

</details>



This page documents the build system and continuous integration/continuous deployment (CI/CD) setup used in OpenMM. It covers how OpenMM is built using CMake, how the CI/CD pipeline is configured to test and deploy the software across multiple platforms, and how these systems enable the development workflow.

## Overview of Build System

OpenMM uses CMake as its build system, which provides a platform-independent way to configure, build, and install the software. The build system handles compilation of the core library, platform-specific implementations, plugins, and language wrappers.

```mermaid
flowchart TD
    subgraph "CMake Configuration"
        CMake["CMakeLists.txt"] --> Config["Configuration Options"]
        Config --> CoreLib["Core Library"]
        Config --> Platforms["Platform Libraries"]
        Config --> Plugins["Plugin Libraries"]
        Config --> Wrappers["Language Wrappers"]
    end

    subgraph "Main Components"
        CoreLib --> OpenMM["libOpenMM.so/OpenMM.dll"]
        Platforms --> Reference["Reference Platform"]
        Platforms --> CPU["CPU Platform"]
        Platforms --> CUDA["CUDA Platform"]
        Platforms --> OpenCL["OpenCL Platform"]
        Platforms --> HIP["HIP Platform"]
        
        Plugins --> Amoeba["Amoeba Force Field"]
        Plugins --> Drude["Drude Force Field"]
        Plugins --> RPMD["RPMD Plugin"]
        Plugins --> PME["PME Plugin"]
        
        Wrappers --> C_Wrappers["C API"]
        Wrappers --> Fortran_Wrappers["Fortran API"]
        Wrappers --> Python_Wrappers["Python API"]
    end

    subgraph "Test Suite"
        OpenMM --> Tests["Unit Tests"]
        Reference --> Tests
        Plugins --> Tests
    end
```

Sources: [CMakeLists.txt:13-38](), [CMakeLists.txt:78-198]()

## Core Build System Architecture

The OpenMM build system is configured through a main CMakeLists.txt file at the root of the project, with additional CMakeLists.txt files in various subdirectories for platforms and plugins. The build process determines which components to build based on available dependencies and user configuration.

### Major Build Components

| Component | Description | Build Option |
|-----------|-------------|--------------|
| Core Library | The core OpenMM API and implementation | Always built |
| Reference Platform | CPU-based reference implementation | Always built |
| CPU Platform | Optimized CPU implementation | `OPENMM_BUILD_CPU_LIB` |
| CUDA Platform | NVIDIA GPU implementation | `OPENMM_BUILD_CUDA_LIB` |
| OpenCL Platform | OpenCL-based GPU implementation | `OPENMM_BUILD_OPENCL_LIB` |
| HIP Platform | AMD GPU implementation | `OPENMM_BUILD_HIP_LIB` |
| Amoeba Plugin | Polarizable force field | `OPENMM_BUILD_AMOEBA_PLUGIN` |
| Drude Plugin | Polarizable force field | `OPENMM_BUILD_DRUDE_PLUGIN` |
| RPMD Plugin | Ring-polymer molecular dynamics | `OPENMM_BUILD_RPMD_PLUGIN` |
| PME Plugin | CPU-based PME implementation | `OPENMM_BUILD_PME_PLUGIN` |
| C/Fortran Wrappers | API bindings for C and Fortran | `OPENMM_BUILD_C_AND_FORTRAN_WRAPPERS` |
| Python Wrappers | API bindings for Python | `OPENMM_BUILD_PYTHON_WRAPPERS` |

Sources: [CMakeLists.txt:317-370](), [CMakeLists.txt:376-408](), [CMakeLists.txt:437-448]()

### Target Architecture Detection

The build system automatically detects the target architecture (x86_64, ARM64, PPC) and enables architecture-specific optimizations.

```mermaid
flowchart TD
    TargetArch["target_architecture() Detection"] --> Decision{"Which architecture?"}
    Decision -->|"x86_64/i386"| X86["X86 Mode\n- SSE2 Optimizations\n- SIMD Operations"]
    Decision -->|"arm"| ARM["ARM64 Mode\n- NEON Instructions\n- ARM-specific Optimizations"]
    Decision -->|"ppc"| PPC["PPC Mode\n- Power Architecture Optimizations"]
    Decision -->|"loongarch64"| LOONGARCH["LoongArch64 Mode\n- LASX Instructions"]
```

Sources: [CMakeLists.txt:36-53]()

## Build Configuration Options

OpenMM's build system provides numerous configuration options to customize the build process. These are set through CMake variables.

### Key Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `CMAKE_BUILD_TYPE` | Release | Debug or Release build |
| `OPENMM_BUILD_SHARED_LIB` | ON | Build shared libraries |
| `OPENMM_BUILD_STATIC_LIB` | OFF | Build static libraries |
| `OPENMM_BUILD_C_AND_FORTRAN_WRAPPERS` | ON | Build API wrappers for C and Fortran |
| `OPENMM_BUILD_PYTHON_WRAPPERS` | ON | Build Python API bindings |
| `OPENMM_BUILD_REFERENCE_TESTS` | TRUE | Build Reference platform test cases |
| `OPENMM_BUILD_CUDA_LIB` | Auto | Build CUDA platform for NVIDIA GPUs |
| `OPENMM_BUILD_OPENCL_LIB` | Auto | Build OpenCL platform |
| `OPENMM_BUILD_HIP_LIB` | Auto | Build HIP platform for AMD GPUs |
| `OPENMM_BUILD_CPU_LIB` | ON | Build optimized CPU platform |
| `OPENMM_BUILD_EXAMPLES` | ON | Build example executables |

Sources: [CMakeLists.txt:72-74](), [CMakeLists.txt:134-136](), [CMakeLists.txt:253-254](), [CMakeLists.txt:316-317](), [CMakeLists.txt:437-438](), [CMakeLists.txt:468-471]()

### Platform-Specific Dependencies

The build system automatically detects the availability of platform-specific dependencies:

```mermaid
flowchart TD
    subgraph "Platform Detection"
        CUDA_Find["FIND_PACKAGE(CUDAToolkit)"] -->|"Found"| CUDA_Option["OPENMM_BUILD_CUDA_LIB=ON"]
        CUDA_Find -->|"Not Found"| CUDA_Disable["OPENMM_BUILD_CUDA_LIB=OFF"]
        
        OpenCL_Find["FIND_PACKAGE(OpenCL)"] -->|"Found"| OpenCL_Option["OPENMM_BUILD_OPENCL_LIB=ON"]
        OpenCL_Find -->|"Not Found"| OpenCL_Disable["OPENMM_BUILD_OPENCL_LIB=OFF"]
        
        HIP_Find["FIND_PACKAGE(HIP)"] -->|"Found"| HIP_Option["OPENMM_BUILD_HIP_LIB=ON"]
        HIP_Find -->|"Not Found"| HIP_Disable["OPENMM_BUILD_HIP_LIB=OFF"]
    end
    
    subgraph "Platform Building"
        CUDA_Option --> CUDA_Build["ADD_SUBDIRECTORY(platforms/cuda)"]
        OpenCL_Option --> OpenCL_Build["ADD_SUBDIRECTORY(platforms/opencl)"]
        HIP_Option --> HIP_Build["ADD_SUBDIRECTORY(platforms/hip)"]
    end
```

Sources: [CMakeLists.txt:324-357]()

## Plugin Build System Integration

Plugins in OpenMM have their own CMakeLists.txt files but are integrated with the main build system. The main CMakeLists.txt enables plugins and includes their directories based on configuration options.

```mermaid
flowchart TD
    MainCMake["Main CMakeLists.txt"] --> EnablePlugins["Enable Plugins\n(OPENMM_BUILD_*_PLUGIN)"]
    
    EnablePlugins --> |"OPENMM_BUILD_AMOEBA_PLUGIN=ON"| AmoebaPlugin["ADD_SUBDIRECTORY(plugins/amoeba)"]
    EnablePlugins --> |"OPENMM_BUILD_DRUDE_PLUGIN=ON"| DrudePlugin["ADD_SUBDIRECTORY(plugins/drude)"]
    EnablePlugins --> |"OPENMM_BUILD_RPMD_PLUGIN=ON"| RPMDPlugin["ADD_SUBDIRECTORY(plugins/rpmd)"]
    EnablePlugins --> |"OPENMM_BUILD_PME_PLUGIN=ON"| PMEPlugin["ADD_SUBDIRECTORY(plugins/cpupme)"]
    
    subgraph "Amoeba Plugin"
        AmoebaPlugin --> AmoebaLib["OpenMMAmoeba Library"]
        AmoebaLib --> AmoebaRef["Reference Platform"]
        AmoebaLib --> AmoebaHardware["Hardware Platforms"]
        AmoebaHardware --> |"If CUDA available"| AmoebaCUDA["ADD_SUBDIRECTORY(platforms/cuda)"]
        AmoebaHardware --> |"If OpenCL available"| AmoebaOpenCL["ADD_SUBDIRECTORY(platforms/opencl)"]
        AmoebaHardware --> |"If HIP available"| AmoebaHIP["ADD_SUBDIRECTORY(platforms/hip)"]
    end
```

Sources: [CMakeLists.txt:376-408](), [plugins/amoeba/CMakeLists.txt:126-166]()

### Plugin Platform Dependency

The plugin build system checks if the corresponding main platform is being built before enabling the platform-specific implementation for the plugin:

```mermaid
flowchart TD
    subgraph "Plugin Platform Dependencies"
        CUDA_Main["OPENMM_BUILD_CUDA_LIB"] -->|"ON"| CUDA_Plugin["OPENMM_BUILD_*_CUDA_LIB=ON"]
        CUDA_Main -->|"OFF"| CUDA_Plugin_Off["OPENMM_BUILD_*_CUDA_LIB=OFF"]
        
        OpenCL_Main["OPENMM_BUILD_OPENCL_LIB"] -->|"ON"| OpenCL_Plugin["OPENMM_BUILD_*_OPENCL_LIB=ON"]
        OpenCL_Main -->|"OFF"| OpenCL_Plugin_Off["OPENMM_BUILD_*_OPENCL_LIB=OFF"]
        
        HIP_Main["OPENMM_BUILD_HIP_LIB"] -->|"ON"| HIP_Plugin["OPENMM_BUILD_*_HIP_LIB=ON"]
        HIP_Main -->|"OFF"| HIP_Plugin_Off["OPENMM_BUILD_*_HIP_LIB=OFF"]
    end
    
    CUDA_Plugin -->|"Build"| CUDA_Plugin_Build["Plugin CUDA Implementation"]
    OpenCL_Plugin -->|"Build"| OpenCL_Plugin_Build["Plugin OpenCL Implementation"]
    HIP_Plugin -->|"Build"| HIP_Plugin_Build["Plugin HIP Implementation"]
```

Sources: [plugins/amoeba/CMakeLists.txt:129-145](), [plugins/drude/CMakeLists.txt:124-149](), [plugins/rpmd/CMakeLists.txt:112-138]()

## Wrapper Generation System

OpenMM includes API wrappers for C, Fortran, and Python. The C and Fortran wrappers are generated using a custom process that parses the C++ API with Doxygen.

```mermaid
flowchart TD
    subgraph "API Wrapper Generation"
        Config["Wrapper Configuration"] --> Doxygen["Doxygen API Parsing"]
        Doxygen --> XML["XML API Documentation"]
        XML --> PythonGen["Python Generator Script"]
        PythonGen --> CHeader["C API Header"]
        PythonGen --> CSource["C API Source"]
        PythonGen --> FortranModule["Fortran Module"]
        PythonGen --> FortranSource["Fortran Wrapper Source"]
    end

    subgraph "Plugin Wrapper Integration"
        CMake["Plugin CMakeLists.txt"] --> WrapperDir["ADD_SUBDIRECTORY(wrappers)"]
        WrapperDir --> DoxyConfig["Configure Doxyfile.in"]
        DoxyConfig --> RunDoxygen["Run Doxygen Command"]
        RunDoxygen --> GenerateWrappers["Run generateWrappers.py"]
        GenerateWrappers --> PluginWrappers["Plugin API Wrappers"]
    end
```

Sources: [CMakeLists.txt:253-258](), [plugins/drude/wrappers/CMakeLists.txt:1-27](), [plugins/drude/wrappers/generateDrudeWrappers.py:64-912]()

## Continuous Integration and Testing

OpenMM uses Travis CI for Linux and macOS builds, and Appveyor for Windows builds. The CI systems run multiple build configurations to ensure cross-platform compatibility and test various feature combinations.

### Travis CI Build Matrix

Travis CI runs several build jobs with different configurations:

| Job Name | Platform | Configuration | Purpose |
|----------|----------|---------------|---------|
| CPU OpenCL | Linux (Xenial) | OpenCL on CPU | Test OpenCL platform without GPU |
| CUDA Compile | Linux (Xenial) | CUDA 7.5 | Verify CUDA compilation |
| Mac OS | macOS (Xcode 9.3) | Default | Test macOS builds |
| Static Lib | Linux (Xenial), Python 3.6 | Static library build | Test static linking |
| Python 3.6 | Linux (Xenial) | Python 3.6 with docs | Main Linux build + documentation |
| Python 3.8 | Linux (Xenial) | Python 3.8 | Test newer Python version |
| PPC | Linux (Bionic), Python 3.8 | PowerPC architecture | Test PPC64LE builds |
| ARM | Linux (Bionic), Python 3.8 | ARM64 architecture | Test ARM64 builds |

```mermaid
flowchart TD
    subgraph "Travis CI Pipeline"
        TravisYML[".travis.yml"] --> JobMatrix["Build Job Matrix"]
        
        JobMatrix --> LinuxJobs["Linux Jobs"]
        JobMatrix --> MacJob["macOS Job"]
        
        LinuxJobs --> OpenCL["CPU OpenCL Job"]
        LinuxJobs --> CUDA["CUDA Compile Job"]
        LinuxJobs --> StaticLib["Static Lib Job"]
        LinuxJobs --> Py36["Python 3.6 Job"]
        LinuxJobs --> Py38["Python 3.8 Job"]
        LinuxJobs --> PPC["PPC Job"]
        LinuxJobs --> ARM["ARM Job"]
        
        OpenCL --> BuildInstall["cmake + make install"]
        CUDA --> BuildInstall
        MacJob --> BuildInstall
        StaticLib --> BuildInstall
        Py36 --> BuildInstall
        Py38 --> BuildInstall
        PPC --> BuildInstall
        ARM --> BuildInstall
        
        BuildInstall --> PythonInstall["make PythonInstall"]
        PythonInstall --> TestInstall["python -m openmm.testInstallation"]
        TestInstall --> RunCTest["python devtools/run-ctest.py"]
        RunCTest --> PyTest["pytest python/tests"]
        
        Py36 --> BuildDocs["Build Documentation"]
        BuildDocs --> DeployS3["Deploy to S3"]
    end
```

Sources: [.travis.yml:16-248]()

### Appveyor Windows CI

Appveyor handles Windows builds using Visual Studio 2019:

```mermaid
flowchart TD
    subgraph "Appveyor Pipeline"
        AppveyorYML["appveyor.yml"] --> Setup["Setup Environment"]
        Setup --> InstallDeps["Install Dependencies"]
        
        InstallDeps --> Doxygen["choco install doxygen"]
        InstallDeps --> SWIG["choco install swig"]
        InstallDeps --> OpenCLHeaders["Download OpenCL Headers"]
        InstallDeps --> BuildICD["Build OpenCL ICD Loader"]
        
        BuildICD --> ConfigureCMake["cmake -G 'NMake Makefiles'"]
        ConfigureCMake --> BuildProject["cmake --build . --target install"]
        BuildProject --> PythonInstall["cmake --build . --target PythonInstall"]
        
        PythonInstall --> RunTests["python devtools/run-ctest.py"]
        RunTests --> PyTest["pytest python/tests"]
    end
```

Sources: [appveyor.yml:1-65]()

### CI Environment Setup

Both CI systems perform similar setup steps:

1. **Install ccache**: For faster rebuilds (Travis only)
2. **Install dependencies**: 
   - Doxygen for API documentation
   - SWIG for wrapper generation
   - Python packages (numpy, scipy, pytest, cython)
   - Platform SDKs (CUDA, OpenCL, AMD APP SDK)
3. **Configure CMake**: With platform-specific flags via `CMAKE_FLAGS` environment variable
4. **Build**: Using `make` (Travis) or `nmake` (Appveyor)
5. **Install**: Using `make install` or `cmake --build . --target install`
6. **Test**: Run CTest suite and pytest tests

Sources: [.travis.yml:124-220](), [appveyor.yml:5-56]()

## Testing Infrastructure

OpenMM uses a multi-layered testing approach with CTest for C++ tests and pytest for Python tests. Tests are organized by component and can be selectively enabled or disabled.

### Test Organization and Build Options

```mermaid
flowchart TD
    subgraph "Test Build Configuration"
        CTest["include(CTest)"] --> EnableTesting["ENABLE_TESTING()"]
        BuildTesting["BUILD_TESTING variable"] --> TestDecision{"Tests Enabled?"}
        
        TestDecision -->|"ON"| CoreTests["Core Library Tests\nADD_SUBDIRECTORY(tests)"]
        TestDecision -->|"ON"| PlatformTests["Platform Tests"]
        TestDecision -->|"ON"| PluginTests["Plugin Tests"]
        
        PlatformTests --> RefTests["OPENMM_BUILD_REFERENCE_TESTS\nplatforms/reference/tests"]
        PlatformTests --> CPUTests["OPENMM_BUILD_CPU_TESTS\nplatforms/cpu/tests"]
        PlatformTests --> CUDATests["OPENMM_BUILD_CUDA_TESTS\nplatforms/cuda/tests"]
        PlatformTests --> OpenCLTests["OPENMM_BUILD_OPENCL_TESTS\nplatforms/opencl/tests"]
        
        PluginTests --> AmoebaTests["OPENMM_BUILD_SERIALIZATION_TESTS\nplugins/amoeba/serialization/tests"]
        PluginTests --> DrudeTests["plugins/drude/serialization/tests"]
        PluginTests --> RPMDTests["plugins/rpmd tests"]
    end
```

Sources: [CMakeLists.txt:30](), [CMakeLists.txt:312-320](), [CMakeLists.txt:455-469](), [serialization/CMakeLists.txt:9-13](), [plugins/amoeba/CMakeLists.txt:191-193]()

### CTest Runner Script

The `devtools/run-ctest.py` script provides advanced test execution features for CI environments:

#### CTest Runner Architecture

```mermaid
flowchart TD
    subgraph "run-ctest.py Execution Flow"
        Args["Command Line Arguments"] --> ParseArgs["ArgumentParser"]
        ParseArgs --> TimeCalc["Calculate Time Budget"]
        
        TimeCalc --> MainRun["execute_tests()"]
        MainRun --> CleanDir["Remove Testing/ directory"]
        CleanDir --> RunCTest["ctest --output-on-failure"]
        
        RunCTest --> CheckResults["Check Exit Status"]
        CheckResults -->|"Success"| Exit0["Return 0"]
        CheckResults -->|"Failure"| ParseXML["Parse Testing/*/Test.xml"]
        
        ParseXML --> FindFailed["Find Failed Tests\n(exclude timeouts)"]
        FindFailed --> RerunTests["execute_failed_tests()"]
        
        RerunTests --> RerunCTest["ctest -R 'test1|test2|...'"]
        RerunCTest --> FinalStatus["Return Exit Status"]
    end
```

#### Key Features

| Feature | Description | Command Line Argument |
|---------|-------------|----------------------|
| Time Management | Allocates percentage of CI job time to test run | `--job-duration`, `--run-percent` |
| Test Timeout | Sets per-test timeout | `--timeout` (default: 180s) |
| Parallel Execution | Runs tests in parallel | `--parallel` (default: 1) |
| Failure Retry | Reruns failed tests (excluding timeouts) | `--attempts` (default: 1) |
| Random Scheduling | Randomizes test order unless disabled | `--in-order` |

Sources: [devtools/run-ctest.py:1-125]()

#### Time Budget Management

The script manages CI time budgets to prevent jobs from timing out:

```python
# Calculate stop time based on job duration and run percentage
stop_time = start_time + timedelta(
    seconds=(options.run_percent / 100.0) * remaining.seconds)

# Pass to ctest
ctest [...] --stop-time stop_time.strftime('%H:%M:%S')
```

This ensures tests complete within Travis/Appveyor time limits (typically 30-50 minutes per job).

Sources: [devtools/run-ctest.py:72-92]()

### Python Test Suite

Python tests use pytest and are located in `wrappers/python/tests/`. Tests are organized by module:

| Test File | Coverage |
|-----------|----------|
| `TestUnits.py` | Unit system, quantity operations, dimensional analysis |
| `TestForceField.py` | ForceField XML parsing and system creation |
| `TestModeller.py` | Structure editing and solvation |
| `TestSerialization.py` | Object serialization/deserialization |
| `Test*.py` | Various OpenMM API functionality |

Example test structure from `TestUnits.py`:

```python
class QuantityTestCase(unittest.TestCase):
    def assertAlmostEqualQuantities(self, item1, item2, places=6):
        # Custom assertion for quantities with units
        ...

class TestUnits(QuantityTestCase):
    def testBaseUnit(self):
        """Tests the creation of a base unit furlong"""
        furlong = u.BaseUnit(u.length_dimension, "furlong", "fur")
        furlong.define_conversion_factor_to(u.meter_base_unit, 201.168)
        self.assertEqual(furlong.conversion_factor_to(u.angstrom_base_unit),
                         201.168e10)
```

Sources: [wrappers/python/tests/TestUnits.py:1-1050](), [wrappers/python/tests/pytest.ini:1-2]()

### Test Configuration Files

- **pytest.ini**: Configures pytest to discover test files matching `Test*.py` pattern
- **CMakeLists.txt in test directories**: Define CTest test cases using `ADD_TEST()` commands
- **Test enabling flags**: Control which test suites are built (e.g., `OPENMM_BUILD_CPU_TESTS`)

Sources: [wrappers/python/tests/pytest.ini:1-2](), [platforms/cpu/CMakeLists.txt:15-19]()

## Installation and Packaging

The build system handles installation of libraries, headers, and supporting files, and supports multiple distribution methods.

### Installation Targets

```mermaid
flowchart TD
    subgraph "Installation Process"
        MakeInstall["make install"] --> InstallLibs["INSTALL_TARGETS(/lib)"]
        MakeInstall --> InstallHeaders["INSTALL_FILES(/include)"]
        MakeInstall --> InstallPlugins["INSTALL_TARGETS(/lib/plugins)"]
        
        InstallLibs --> CoreLib["libOpenMM.so/OpenMM.dll\nlibOpenMM_static.a"]
        InstallLibs --> PlatformLibs["libOpenMMCPU.so\nlibOpenMMCUDA.so\nlibOpenMMOpenCL.so"]
        
        InstallPlugins --> AmoebaPlugin["libOpenMMAmoeba.so\nplatform implementations"]
        InstallPlugins --> DrudePlugin["libOpenMMDrude.so\nplatform implementations"]
        InstallPlugins --> RPMDPlugin["libOpenMMRPMD.so\nplatform implementations"]
        
        InstallHeaders --> CoreHeaders["include/openmm/*.h"]
        InstallHeaders --> InternalHeaders["include/openmm/internal/*.h"]
        InstallHeaders --> LeptonHeaders["include/lepton/*.h"]
        InstallHeaders --> PlatformHeaders["include/openmm/reference/*.h\ninclude/openmm/cpu/*.h"]
    end
    
    subgraph "Python Installation"
        PythonInstall["make PythonInstall"] --> SetupPy["wrappers/python/setup.py"]
        SetupPy --> SitePackages["site-packages/openmm/"]
        SitePackages --> OpenMMModule["openmm module"]
        SitePackages --> AppModule["openmm.app module"]
        SitePackages --> UnitModule["openmm.unit module"]
    end
```

Sources: [CMakeLists.txt:410-427](), [plugins/amoeba/CMakeLists.txt:168-177](), [plugins/drude/CMakeLists.txt:151-160](), [plugins/rpmd/CMakeLists.txt:140-152]()

### Installation Paths

The default installation prefix varies by platform:

| Platform | Default Path | CMake Variable |
|----------|--------------|----------------|
| Windows | `C:/Program Files/OpenMM` | `OPENMM_INSTALL_PREFIX` |
| Linux/macOS | `/usr/local/openmm` | `OPENMM_INSTALL_PREFIX` |
| User Override | Custom path | `CMAKE_INSTALL_PREFIX` |

Installation subdirectories:
- `/lib` - Shared and static libraries
- `/lib/plugins` - Plugin libraries
- `/include` - Public API headers
- Python site-packages - Python modules

Sources: [CMakeLists.txt:57-88]()

### Conda Package Distribution

OpenMM is distributed via Conda packages built from the `tools/conda-recipe/` directory:

```mermaid
flowchart TD
    subgraph "Conda Packaging"
        Recipe["tools/conda-recipe/"] --> CondaBuild["conda build"]
        CondaBuild --> CondaPackage["openmm conda package"]
        
        CondaPackage --> CondaInstall["conda install openmm"]
        CondaInstall --> UserEnv["User's conda environment"]
        
        UserEnv --> Libraries["OpenMM libraries"]
        UserEnv --> PythonBindings["Python bindings"]
        UserEnv --> Dependencies["Dependencies\n(CUDA, OpenCL, etc.)"]
    end
```

The Conda package includes:
- Pre-compiled binaries for multiple platforms (Linux, macOS, Windows)
- Python bindings for multiple Python versions
- Platform-specific optimizations (CUDA, OpenCL)
- All dependencies properly linked

Sources: [CMakeLists.txt:410-427]() (references conda packaging in comments)

### Documentation Deployment

Documentation is built and deployed as part of the CI process:

```mermaid
flowchart TD
    subgraph "Documentation Build and Deployment"
        BuildDocs["DOCS_DEPLOY=true"] --> SphinxHTML["make sphinxhtml"]
        SphinxHTML --> SphinxPDF["make sphinxpdf"]
        SphinxPDF --> CppDocs["make C++ApiDocs"]
        CppDocs --> PyDocs["make PythonApiDocs"]
        
        PyDocs --> OrganizeDocs["Organize api-docs/"]
        OrganizeDocs --> UserGuide["api-docs/userguide/"]
        OrganizeDocs --> DevGuide["api-docs/developerguide/"]
        OrganizeDocs --> APIDocs["api-docs/api-python/\napi-docs/api-c++/"]
        
        APIDocs --> DeployS3["Deploy to S3"]
        DeployS3 --> DocsWebsite["docs.openmm.org"]
    end
```

Documentation deployment occurs on successful builds of the master branch when `DOCS_DEPLOY=true`.

Sources: [.travis.yml:222-232](), [.travis.yml:234-247]()

## Cross-Platform Considerations

The build system includes specific handling for different operating systems and architectures:

### Platform-Specific Compiler Flags

```mermaid
flowchart TD
    Platform{"Platform Detection"} --> Apple["Apple/macOS"]
    Platform --> Windows["Windows/MSVC"]
    Platform --> Linux["Linux/Unix"]
    
    Apple --> AppleFlags["- OSX Deployment Target\n- Architecture Flags\n- libc++ Standard Library"]
    Windows --> WindowsFlags["- Warning Level Settings\n- Specific Warning Suppressions"]
    Linux --> LinuxFlags["- pthread Support\n- Specific Linker Flags"]
    
    Architecture{"Architecture Detection"} --> X86["x86_64/i386"]
    Architecture --> ARM["ARM64"]
    Architecture --> Power["PowerPC"]
    Architecture --> LoongArch["LoongArch64"]
    
    X86 --> X86Flags["- SSE2 Instructions\n- SIMD Optimizations"]
    ARM --> ARMFlags["- NEON Instructions"]
    Power --> PowerFlags["- PPC-specific Flags"]
    LoongArch --> LoongArchFlags["- LSX Instructions"]
```

Sources: [CMakeLists.txt:98-132](), [CMakeLists.txt:36-53]()

## Conclusion

OpenMM's build system is designed to be flexible and support multiple platforms, architectures, and configuration options. The CMake-based system automatically detects available dependencies and enables the corresponding features. The CI/CD pipeline ensures that the code builds and passes tests on various platforms, providing reliability for the library across different environments.

For information on the development workflow and contributing to OpenMM, see [Development Workflow](#1.2).