# Development Guide

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [CMakeLists.txt](CMakeLists.txt)
- [environment.yaml](environment.yaml)
- [src/electro.cpp](src/electro.cpp)
- [src/electro.h](src/electro.h)
- [tests/templates/input.mdin.jinja](tests/templates/input.mdin.jinja)
- [tests/test_amber_integration.py](tests/test_amber_integration.py)

</details>



This guide provides essential information for developers contributing to TorchANI-Amber, covering the development environment, build system, testing infrastructure, and contribution workflow. This document focuses on the technical aspects of working with the codebase and build system.

For detailed build system configuration options, see [Build System Deep Dive](#6.1). For comprehensive testing procedures and framework details, see [Testing Framework](#6.2). For development workflow and code quality standards, see [Code Quality and Development Workflow](#6.3).

## Development Environment Setup

TorchANI-Amber requires a carefully configured development environment due to its complex dependency chain involving PyTorch, CUDA, cuDNN, and Amber molecular dynamics engines.

### Conda Environment Configuration

The project uses a conda environment specification that ensures compatibility across all components:

```mermaid
graph TB
    subgraph "Base Dependencies"
        PYTHON["python=3.11"]
        PYTORCH["pytorch=2.5"]
        NUMPY["numpy=1.26"]
    end
    
    subgraph "CUDA Stack"
        PYTORCH_CUDA["pytorch-cuda=12.4"]
        CUDA_LIBS["cuda-libraries-dev=12.4"]
        CUDA_NVCC["cuda-nvcc=12.4"]
        CUDNN["cudnn"]
    end
    
    subgraph "Compilers"
        GXX["gxx_linux-64=12.2"]
        GCC["gcc_linux-64=12.2"]
        GFORTRAN["gfortran_linux-64=12.2"]
    end
    
    subgraph "Build Tools"
        CMAKE["cmake=3.31.1"]
        SETUPTOOLS["setuptools>=64"]
    end
    
    subgraph "Amber Dependencies"
        FFTW["fftw=3.3.10"]
        NETCDF["netcdf-fortran=4.6.1"]
        OPENMPI["openmpi=4.1.6"]
    end
    
    PYTHON --> PYTORCH
    PYTORCH --> PYTORCH_CUDA
    PYTORCH_CUDA --> CUDA_LIBS
    CUDA_LIBS --> CUDA_NVCC
    GCC --> CMAKE
    CMAKE --> FFTW
    FFTW --> NETCDF
```

Sources: [environment.yaml:1-68]()

The environment enforces strict version compatibility, particularly for the CUDA stack where PyTorch 2.5 must match CUDA 12.4 and the corresponding cuDNN version.

### Compiler Requirements

The build system enforces specific compiler versions to ensure compatibility with CUDA and PyTorch:

```mermaid
graph LR
    COMPILERS["GNU Compilers"] --> VERSION_CHECK{"Version 11.0-13.2?"}
    VERSION_CHECK -->|Yes| CUDA_COMPAT["CUDA nvcc Compatibility"]
    VERSION_CHECK -->|No| ERROR["Build Error"]
    CUDA_COMPAT --> PYTORCH_ABI["PyTorch ABI Compatibility"]
    PYTORCH_ABI --> BUILD_SUCCESS["Build Success"]
```

Sources: [CMakeLists.txt:74-88]()

## Build System Architecture

The CMake build system is designed to handle the complex dependency resolution required for a project that bridges Python ML frameworks with high-performance C++ execution.

### Build Configuration Flow

```mermaid
flowchart TD
    START["cmake_minimum_required(3.24)"] --> OPTIONS["Build Options"]
    OPTIONS --> VALIDATION["Option Validation"]
    VALIDATION --> PYTORCH_SETUP["PyTorch/LibTorch Setup"]
    PYTORCH_SETUP --> CUDA_SETUP["CUDA Dependencies"]
    CUDA_SETUP --> JIT_COMPILE["JIT Model Compilation"]
    JIT_COMPILE --> LIBRARIES["Library Compilation"]
    LIBRARIES --> TESTS["Test Setup"]
    TESTS --> INSTALL["Installation Config"]
    
    subgraph "Key Options"
        LINK_PYTORCH["LINK_TO_PYTORCH_LIBS"]
        DOWNLOAD_LIBTORCH["DOWNLOAD_AND_INSTALL_LIBTORCH"]
        PREFER_CONDA["PREFER_CONDA_LIBS"]
        USE_CUSTOM_CUDA["USE_CUSTOM_CUDNN/CUDATK"]
        JIT_MODELS["JIT_COMPILE_MODELS"]
    end
    
    OPTIONS --> LINK_PYTORCH
    OPTIONS --> DOWNLOAD_LIBTORCH
    OPTIONS --> PREFER_CONDA
    OPTIONS --> USE_CUSTOM_CUDA
    OPTIONS --> JIT_MODELS
```

Sources: [CMakeLists.txt:36-93]()

### Library Compilation Targets

The build system creates three main shared libraries:

```mermaid
graph TB
    subgraph "Library Targets"
        CELL_LIST["libcell_list.so"]
        CUAEV["libcuaev.so"] 
        TORCHANI["libtorchani.so"]
    end
    
    subgraph "Source Files"
        CELL_SRC["torchani_sandbox/torchani/csrc/cell_list.cpp"]
        CUAEV_SRC["torchani_sandbox/torchani/csrc/cuaev.cpp"]
        CUAEV_CUDA["torchani_sandbox/torchani/csrc/aev.cu"]
        TORCHANI_SRC["src/*.cpp"]
    end
    
    subgraph "Dependencies"
        TORCH_LIBS["TORCH_LIBRARIES"]
        PYTHON_LIBS["Python_LIBRARIES"]
        CUDA_RUNTIME["CUDA Runtime"]
    end
    
    CELL_SRC --> CELL_LIST
    CUAEV_SRC --> CUAEV
    CUAEV_CUDA --> CUAEV
    TORCHANI_SRC --> TORCHANI
    
    TORCH_LIBS --> CELL_LIST
    TORCH_LIBS --> CUAEV
    TORCH_LIBS --> TORCHANI
    
    PYTHON_LIBS --> CELL_LIST
    PYTHON_LIBS --> CUAEV
    
    CUDA_RUNTIME --> CUAEV
```

Sources: [CMakeLists.txt:234-323]()

The `libcuaev.so` library includes CUDA-specific optimizations with the `TORCHANI_OPT` flag and fast math compilation options.

## Testing Infrastructure

TorchANI-Amber employs a comprehensive testing strategy that validates integration with Amber MD engines across multiple configuration combinations.

### Test Configuration Matrix

The testing framework uses parameterized tests to validate functionality across different runtime configurations:

```mermaid
graph TD
    CONFIG_GEN["Test Configuration Generator"] --> CUDA_OPTS["CUDA Options"]
    CONFIG_GEN --> MLMM_OPTS["ML/MM Options"]
    CONFIG_GEN --> RUNTIME_OPTS["Runtime Options"]
    
    subgraph "CUDA Configurations"
        CUDA_NONE["None (CPU)"]
        CUDA_CUAEV["CudaConfig(cuaev=True)"]
        CUDA_NO_CUAEV["CudaConfig(cuaev=False)"]
    end
    
    subgraph "ML/MM Configurations"
        FULLML["None (Full-ML)"]
        MLMM_ME["MlmmConfig('me')"]
        MLMM_MBISPOL["MlmmConfig('mbispol')"]
        MLMM_TORCH["MlmmConfig(use_torch_coupling=True)"]
    end
    
    subgraph "Runtime Options"
        SHAKE["shake: True/False"]
        VACUUM["vacuum: True/False"]
        FLOAT64["float64: True/False"]
        AMBER_NL["use_amber_neighborlist: True/False"]
    end
    
    CUDA_OPTS --> CUDA_NONE
    CUDA_OPTS --> CUDA_CUAEV
    CUDA_OPTS --> CUDA_NO_CUAEV
    
    MLMM_OPTS --> FULLML
    MLMM_OPTS --> MLMM_ME
    MLMM_OPTS --> MLMM_MBISPOL
    MLMM_OPTS --> MLMM_TORCH
    
    RUNTIME_OPTS --> SHAKE
    RUNTIME_OPTS --> VACUUM
    RUNTIME_OPTS --> FLOAT64
    RUNTIME_OPTS --> AMBER_NL
```

Sources: [tests/test_amber_integration.py:77-111]()

### Test Execution Framework

```mermaid
sequenceDiagram
    participant TF as "Test Framework"
    participant JT as "Jinja2 Template"
    participant AE as "Amber Engine"
    participant VO as "Validation Oracle"
    
    TF->>JT: render("input.mdin.jinja", config)
    JT->>TF: input.mdin file
    TF->>AE: execute pmemd/sander
    AE->>TF: output files (.dat, .mdcrd, .xyz)
    TF->>VO: compare with expected outputs
    VO->>TF: assertion results
```

The test framework generates Amber input files using Jinja2 templates that adapt to different configuration combinations:

Sources: [tests/test_amber_integration.py:113-125](), [tests/templates/input.mdin.jinja:1-98]()

### Unit Test Infrastructure

The project uses Catch2 for C++ unit testing with CMake integration:

```mermaid
graph LR
    CATCH2_SUB["Catch2 Submodule"] --> CATCH2_BUILD["Catch2 Build"]
    CATCH2_BUILD --> TEST_TARGET["tests executable"]
    TEST_TARGET --> TEST_DISCOVERY["catch_discover_tests()"]
    TEST_DISCOVERY --> CTEST["CTest Integration"]
    
    subgraph "Test Sources"
        TEST_CPP["tests/tests.cpp"]
        TORCHANI_LIB["libtorchani.so"]
    end
    
    TEST_CPP --> TEST_TARGET
    TORCHANI_LIB --> TEST_TARGET
```

Sources: [CMakeLists.txt:378-391]()

## Code Organization

The codebase follows a multi-language architecture with clear separation between computational kernels, interfaces, and integration layers.

### Core Implementation Structure

```mermaid
graph TB
    subgraph "C++ Core (src/)"
        TORCHANI_CPP["torchani.cpp"]
        ELECTRO_CPP["electro.cpp"]
        ELECTRO_H["electro.h"]
    end
    
    subgraph "Interfaces (include/)"
        TORCHANI_H["torchani.h"]
    end
    
    subgraph "Fortran Interface (src-fortran/)"
        TORCHANI_F90["torchani.F90"]
    end
    
    subgraph "CUDA Extensions (submodules/)"
        CUAEV_CPP["cuaev.cpp"]
        AEV_CU["aev.cu"]
        CELL_LIST_CPP["cell_list.cpp"]
    end
    
    subgraph "Test Infrastructure (tests/)"
        INTEGRATION_TESTS["test_amber_integration.py"]
        UNIT_TESTS["tests.cpp"]
        INPUT_TEMPLATES["templates/input.mdin.jinja"]
    end
    
    TORCHANI_H --> TORCHANI_F90
    TORCHANI_CPP --> TORCHANI_H
    ELECTRO_CPP --> ELECTRO_H
    CUAEV_CPP --> AEV_CU
```

Sources: [CMakeLists.txt:289-323](), [src/electro.cpp:1-90](), [src/electro.h:1-19]()

### Key Computational Modules

The `electro` namespace provides core electrostatic calculation functionality:

- `coulombic_embedding_energy()`: Calculates Coulombic QM/MM interaction energy
- `polarizable_embedding_energy()`: Computes polarizable embedding energy using atomic polarizabilities

Sources: [src/electro.h:4-18](), [src/electro.cpp:78-89]()

## Development Workflow

### Build Process

1. **Environment Setup**: Activate the `ani-amber` conda environment
2. **Configuration**: Run CMake with appropriate options for your development setup
3. **Compilation**: Build the shared libraries and test executables
4. **Testing**: Execute the test suite to validate functionality

### Common Development Scenarios

```mermaid
flowchart LR
    subgraph "Development Tasks"
        NEW_FEATURE["New Feature"]
        BUG_FIX["Bug Fix"]
        PERF_OPT["Performance Optimization"]
    end
    
    subgraph "Workflow Steps"
        BRANCH["Create Branch"]
        CODE["Code Changes"]
        BUILD["Build & Test"]
        VALIDATE["Integration Tests"]
        PR["Pull Request"]
    end
    
    NEW_FEATURE --> BRANCH
    BUG_FIX --> BRANCH
    PERF_OPT --> BRANCH
    
    BRANCH --> CODE
    CODE --> BUILD
    BUILD --> VALIDATE
    VALIDATE --> PR
```

### Testing Strategy

The testing approach validates both individual components and full system integration:

- **Unit Tests**: C++ components tested with Catch2 framework
- **Integration Tests**: Full Amber MD simulations with expected output comparison
- **Configuration Tests**: Parameterized testing across CUDA/CPU, ML/MM modes
- **Regression Tests**: Automated comparison against reference outputs

Sources: [tests/test_amber_integration.py:127-383]()

The development environment supports rapid iteration through automated build configuration detection and comprehensive test coverage across deployment scenarios.

---