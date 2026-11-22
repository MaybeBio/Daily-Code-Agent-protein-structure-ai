# Build System Deep Dive

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [CMakeLists.txt](CMakeLists.txt)
- [cmake/Msg.cmake](cmake/Msg.cmake)
- [cmake/TorchaniConfig.cmake.in](cmake/TorchaniConfig.cmake.in)
- [cmake/detect_pytorch.py](cmake/detect_pytorch.py)
- [environment.yaml](environment.yaml)

</details>



This document provides a comprehensive overview of the CMake-based build system used in TorchANI-Amber. It covers the build configuration process, dependency resolution, target compilation, and installation procedures. For information about using the build artifacts in simulations, see [Amber Integration](#4). For testing the build outputs, see [Testing Framework](#6.2).

## Build System Architecture

The TorchANI-Amber build system is implemented as a sophisticated CMake project that manages complex dependencies including PyTorch/LibTorch, CUDA toolkit, cuDNN, and Python extensions. The system supports multiple build configurations and deployment scenarios.

### Build Process Overview

```mermaid
flowchart TD
    A["CMakeLists.txt"] --> B["Configuration Validation"]
    B --> C["Environment Detection"]
    C --> D["Dependency Resolution"]
    D --> E["JIT Model Compilation"]
    E --> F["Target Compilation"]
    F --> G["Testing Integration"]
    G --> H["Installation & Packaging"]
    
    B --> B1["Option Validation"]
    B --> B2["Compiler Verification"]
    
    C --> C1["Conda Environment"]
    C --> C2["PyTorch Detection"]
    
    D --> D1["LibTorch/PyTorch"]
    D --> D2["CUDA Toolkit"]
    D --> D3["cuDNN Library"]
    D --> D4["Python Headers"]
    
    F --> F1["libcell_list.so"]
    F --> F2["libcuaev.so"]
    F --> F3["libtorchani.so"]
    
    H --> H1["CMake Config Files"]
    H --> H2["Shared Libraries"]
    H --> H3["Include Headers"]
    H --> H4["Fortran Interface"]
```

Sources: [CMakeLists.txt:1-462]()

### Configuration Options and Flags

The build system provides extensive configuration through CMake options that control dependency handling and compilation behavior:

| Option | Default | Description |
|--------|---------|-------------|
| `LINK_TO_PYTORCH_LIBS` | ON | Link to existing PyTorch installation |
| `DOWNLOAD_AND_INSTALL_LIBTORCH` | OFF | Download LibTorch if PyTorch unavailable |
| `PREFER_CONDA_LIBS` | ON | Prioritize libraries from active conda environment |
| `COMPILE_WITH_CXX11ABI` | OFF | Use C++11 ABI (requires LibTorch mode) |
| `USE_CUSTOM_CUDNN` | OFF | Use cuDNN from `./external/cudnn<version>` |
| `USE_CUSTOM_CUDATK` | OFF | Use CUDA Toolkit from `/usr/local/cuda-<version>` |
| `JIT_COMPILE_MODELS` | ON | JIT-compile ANI models during build |
| `JIT_FORCE_RECOMPILATION` | OFF | Force recompilation of existing `.pt` files |
| `SET_TORCHANI_LIBRARIES_INSTALL_RPATH` | ON | Set RPATH for installed libraries |

Sources: [CMakeLists.txt:38-46](), [CMakeLists.txt:91-93]()

### Dependency Resolution Workflow

```mermaid
flowchart LR
    subgraph "PyTorch Detection"
        A["detect_pytorch.py"] --> B["Extract Versions"]
        B --> C["Validate Compatibility"]
        C --> D["Set CMAKE_PREFIX_PATH"]
    end
    
    subgraph "CUDA Setup"
        E["Environment Check"] --> F{"Conda or Custom?"}
        F -->|Conda| G["CudaToolkitHelper_set_conda_paths"]
        F -->|Custom| H["CudaToolkitHelper_set_custom_paths"]
        G --> I["Set CUDA_TOOLKIT_ROOT_DIR"]
        H --> I
    end
    
    subgraph "cuDNN Setup"
        J["cuDNN Detection"] --> K{"Source Location?"}
        K -->|Conda| L["CudnnHelper_set_conda_paths"]
        K -->|Custom| M["CudnnHelper_set_custom_paths"]
        K -->|System| N["Use CUDA Toolkit Dir"]
        L --> O["Set CUDNN_LIBRARY"]
        M --> O
        N --> O
    end
    
    D --> P["find_package(Torch)"]
    I --> P
    O --> P
```

The dependency resolution process handles three critical components:

**PyTorch/LibTorch Detection**: The system uses [cmake/detect_pytorch.py:1-16]() to extract version information and installation paths from an existing PyTorch installation. This script extracts torch version, CUDA version, cuDNN version, and the PyTorch root directory.

**CUDA Toolkit Resolution**: Depending on configuration, the system either uses CUDA from the active conda environment or searches custom paths. The `CudaToolkitHelper` modules set `CUDA_TOOLKIT_ROOT_DIR` and `CMAKE_CUDA_COMPILER` variables.

**cuDNN Library Management**: Similar to CUDA, cuDNN can be sourced from conda, custom directories, or assumed to be co-located with the CUDA Toolkit.

Sources: [CMakeLists.txt:115-165](), [CMakeLists.txt:167-186](), [CMakeLists.txt:188-212](), [cmake/detect_pytorch.py:1-16]()

## Target Compilation Process

### Library Target Hierarchy

```mermaid
graph TB
    subgraph "External Dependencies"
        TORCH["${TORCH_LIBRARIES}"]
        PYTHON["${Python_LIBRARIES}"]
        CUDA["CUDA Runtime"]
    end
    
    subgraph "TorchANI Libraries"
        CELL["cell_list"]
        CUAEV["cuaev"] 
        TORCHANI["torchani"]
    end
    
    subgraph "Source Locations"
        CELL_SRC["submodules/torchani_sandbox/torchani/csrc/cell_list.cpp"]
        CUAEV_SRC["submodules/torchani_sandbox/torchani/csrc/cuaev.cpp<br/>submodules/torchani_sandbox/torchani/csrc/aev.cu"]
        TORCHANI_SRC["src/*.cpp"]
    end
    
    subgraph "Testing"
        CATCH2["Catch2::Catch2WithMain"]
        TESTS["tests"]
    end
    
    CELL_SRC --> CELL
    CUAEV_SRC --> CUAEV
    TORCHANI_SRC --> TORCHANI
    
    TORCH --> CELL
    PYTHON --> CELL
    TORCH --> CUAEV
    PYTHON --> CUAEV
    TORCH --> TORCHANI
    CUAEV --> TORCHANI
    CELL --> TORCHANI
    
    CATCH2 --> TESTS
    TORCHANI --> TESTS
```

### Compilation Specifications

**cell_list Library**: Built from TorchANI sandbox submodule sources with C++17 standard and PyTorch/Python linking.

**cuaev Library**: CUDA-enabled library with specific optimizations:
- `TORCHANI_OPT` preprocessor definition enables CUDA intrinsics
- `-use_fast_math` NVCC flag for fast math library
- Custom CUB namespace definitions to avoid conflicts with PyTorch

**torchani Library**: Main interface library with comprehensive warning flags and special linking requirements:
- Force-loading of `cuaev` and `cell_list` using `LINKER:-force_load`
- `--no-as-needed` linker flag to ensure proper dependency resolution

Sources: [CMakeLists.txt:234-287](), [CMakeLists.txt:289-323]()

### JIT Model Compilation

The build system includes a JIT compilation step for ANI models when `JIT_COMPILE_MODELS` is enabled:

```mermaid
flowchart LR
    A["TorchScriptUtils_jit_compile_models"] --> B["Python Model Sources"]
    B --> C["JIT Compilation Process"]
    C --> D[".pt Model Files"]
    
    E["JIT_FORCE_RECOMPILATION"] -.-> C
    F["JIT_DISABLE_OPTIMIZATIONS"] -.-> C
    
    D --> G["Runtime Model Loading"]
```

This process converts Python-defined ANI models into TorchScript format for efficient C++ runtime loading.

Sources: [CMakeLists.txt:215-223]()

## Installation and Packaging

### RPATH Configuration

The build system implements sophisticated RPATH handling to ensure runtime library resolution:

```mermaid
graph TD
    A["SET_TORCHANI_LIBRARIES_INSTALL_RPATH"] --> B["Configure Install RPATH"]
    B --> C["${LIBTORCH_LIBRARY_DIR}"]
    B --> D["${CUDA_TOOLKIT_ROOT_DIR}"]
    B --> E["${CMAKE_INSTALL_FULL_LIBDIR}/Torchani"]
    
    C --> F["Runtime Library Resolution"]
    D --> F
    E --> F
    
    G["INSTALL_RPATH_USE_LINK_PATH"] --> F
```

The RPATH configuration prevents re-linking issues during installation and ensures libraries can locate dependencies regardless of system-wide CUDA installations.

Sources: [CMakeLists.txt:340-364]()

### CMake Package Configuration

The build system generates complete CMake package configuration for downstream usage:

| File | Purpose |
|------|---------|
| `TorchaniConfig.cmake` | Main configuration file with paths and targets |
| `TorchaniConfigVersion.cmake` | Version compatibility checking |
| `TorchaniTargets.cmake` | Exported target definitions |

**Installation Structure**:
- Libraries: `${CMAKE_INSTALL_LIBDIR}/Torchani/`
- Headers: `${CMAKE_INSTALL_INCLUDEDIR}/Torchani/`
- CMake files: `${CMAKE_INSTALL_DATAROOTDIR}/cmake/Torchani/`
- Fortran interface: `${CMAKE_INSTALL_DATAROOTDIR}/Torchani/Fortran/`

Sources: [CMakeLists.txt:393-461](), [cmake/TorchaniConfig.cmake.in:1-13]()

## Environment and Dependency Management

### Conda Environment Specification

The project defines a comprehensive conda environment that aligns with build requirements:

```mermaid
graph LR
    subgraph "Core Runtime"
        A["python=3.11"]
        B["pytorch=2.5"]
        C["pytorch-cuda=12.4"]
    end
    
    subgraph "Build Tools"
        D["cmake=3.31.1"]
        E["gxx_linux-64=12.2"]
        F["gcc_linux-64=12.2"]
        G["gfortran_linux-64=12.2"]
    end
    
    subgraph "CUDA Development"
        H["cuda-libraries-dev=12.4"]
        I["cuda-nvcc=12.4"]
        J["cuda-cudart-static=12.4"]
    end
    
    subgraph "Molecular Dynamics"
        K["fftw=3.3.10"]
        L["netcdf-fortran=4.6.1"]
        M["openmpi=4.1.6"]
    end
    
    A --> N["Build Environment"]
    B --> N
    C --> N
    D --> N
    E --> N
    F --> N
    G --> N
    H --> N
    I --> N
    J --> N
    K --> O["Amber Integration"]
    L --> O
    M --> O
```

The environment specification enforces exact version matching for critical components like PyTorch (2.5), CUDA (12.4), and compiler toolchain (GCC 12.2).

Sources: [environment.yaml:1-68]()

### Compiler and Version Validation

The build system includes strict compiler validation:

```mermaid
flowchart TD
    A["Compiler Detection"] --> B{"GNU Compilers?"}
    B -->|No| C["FATAL_ERROR"]
    B -->|Yes| D["Version Check"]
    D --> E{"11.0 <= Version <= 13.2?"}
    E -->|No| F["FATAL_ERROR"]
    E -->|Yes| G["Continue Build"]
    
    H["ALLOW_UNSUPPORTED_COMPILERS"] -.-> I["Skip Validation"]
    I -.-> G
```

This validation ensures compatibility with CUDA toolkit requirements and PyTorch ABI constraints.

Sources: [CMakeLists.txt:74-88]()

---