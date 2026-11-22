# Getting Started

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [CMakeLists.txt](CMakeLists.txt)
- [README.md](README.md)
- [ani-amber-logo-dark.png](ani-amber-logo-dark.png)
- [ani-amber-logo-light.png](ani-amber-logo-light.png)
- [environment.yaml](environment.yaml)

</details>



This page provides an overview of the steps required to install, build, and configure TorchANI-Amber for your first molecular dynamics simulations. TorchANI-Amber integrates neural network potentials with the Amber molecular dynamics suite, enabling both full-ML simulations and ML/MM hybrid approaches.

For detailed installation and build instructions, see [Installation and Build](#2.1). For a complete step-by-step tutorial to run your first simulation, see [Quick Start Tutorial](#2.2). For information about the underlying architecture and API details, see [Core Architecture](#3).

## Prerequisites Overview

Before beginning the installation process, ensure you have access to the following system requirements:

| Component | Requirement | Purpose |
|-----------|-------------|---------|
| **Operating System** | Linux | Required by build system validation |
| **Compiler** | GNU GCC 11.0-13.2 | C++17 support for core libraries |
| **Python Environment** | Conda/Mamba | Dependency management |
| **CUDA Toolkit** | 12.4 | GPU acceleration (optional but recommended) |
| **Memory** | 8GB+ RAM | Model loading and tensor operations |
| **Storage** | 10GB+ free space | Dependencies and compiled libraries |

The system enforces these requirements through validation checks in the build configuration, as seen in [CMakeLists.txt:75-88]().

**Sources:** [CMakeLists.txt:75-88](), [README.md:35-37](), [environment.yaml:34-46]()

## Getting Started Workflow

The TorchANI-Amber setup process follows a structured workflow that ensures all dependencies are properly configured:

#### High-Level Installation Flow
```mermaid
graph TD
    A["Clone Repository<br/>git clone --recurse-submodules"] --> B["Create Conda Environment<br/>conda env create -f environment.yaml"]
    B --> C["Activate Environment<br/>conda activate ani-amber"]
    C --> D["Install TorchANI Python<br/>pip install torchani_sandbox_pub"]
    D --> E["Build TorchANI-Amber<br/>./run-cmake"]
    E --> F["Build Amber<br/>cmake with CMAKE_PREFIX_PATH"]
    F --> G["Configure Simulation<br/>Create mdin files"]
    G --> H["Run Simulation<br/>sander/pmemd with TorchANI"]
    
    style A fill:#e1f5fe
    style E fill:#e8f5e8
    style H fill:#fff3e0
```

**Sources:** [README.md:39-83](), [CMakeLists.txt:1-12]()

## System Components and Build Targets

TorchANI-Amber consists of several interconnected components that work together to provide neural network potential calculations within Amber:

#### Core Build Architecture
```mermaid
graph TB
    subgraph "Source Components"
        REPO["torchani-amber Repository"]
        SUBMODS["Git Submodules<br/>torchani_sandbox<br/>Catch2"]
        CONDA_ENV["Conda Environment<br/>ani-amber"]
    end
    
    subgraph "Build System"
        CMAKE["CMakeLists.txt<br/>Build Configuration"]
        JIT_SCRIPT["jit.py<br/>Model Compilation"]
        RUN_CMAKE["run-cmake<br/>Build Script"]
    end
    
    subgraph "Generated Libraries"
        LIBTORCHANI["libtorchani.so<br/>Main C++ Interface"]
        LIBCUAEV["libcuaev.so<br/>CUDA AEV Extension"]
        LIBCELL["libcell_list.so<br/>Neighbor Lists"]
        JIT_MODELS["*.pt Files<br/>JIT-Compiled Models"]
    end
    
    subgraph "Integration Points"
        C_API["torchani.h<br/>C Interface"]
        F90_API["torchani.F90<br/>Fortran Interface"]
        AMBER_LINK["Amber Integration<br/>CMAKE_PREFIX_PATH"]
    end
    
    REPO --> CMAKE
    SUBMODS --> CMAKE
    CONDA_ENV --> CMAKE
    CMAKE --> RUN_CMAKE
    CMAKE --> JIT_SCRIPT
    JIT_SCRIPT --> JIT_MODELS
    RUN_CMAKE --> LIBTORCHANI
    RUN_CMAKE --> LIBCUAEV
    RUN_CMAKE --> LIBCELL
    LIBTORCHANI --> C_API
    C_API --> F90_API
    LIBTORCHANI --> AMBER_LINK
    JIT_MODELS --> AMBER_LINK
```

**Sources:** [CMakeLists.txt:234-323](), [CMakeLists.txt:439-461](), [README.md:58-64]()

## Configuration Overview

TorchANI-Amber simulations are configured through Amber's `mdin` input files using specific namelists. The configuration approach differs depending on the simulation type:

#### Simulation Configuration Patterns
```mermaid
graph LR
    subgraph "Full-ML Configuration"
        A["&cntrl<br/>iextpot = 1"] --> B["&extpot<br/>extprog = 'TORCHANI'"]
        B --> C["&ani<br/>model_type<br/>use_cuda_device<br/>use_double_precision"]
    end
    
    subgraph "ML/MM Configuration"
        D["&cntrl<br/>ifqnt = 1"] --> E["&qmmm<br/>qm_theory = 'EXTERN'<br/>qmmask = ':1'"]
        E --> F["&ani<br/>model_type<br/>use_torchani_charges<br/>mlmm_coupling"]
    end
    
    subgraph "Available Models"
        G["ani1x<br/>ANI-1x Ensemble"]
        H["ani2x<br/>ANI-2x Ensemble"]
        I["ani1ccx<br/>ANI-1ccx Ensemble"]
        J["animbis<br/>MBIS Charge Model"]
    end
    
    C --> G
    C --> H
    C --> I
    F --> G
    F --> H
    F --> I
    F --> J
```

**Sources:** [README.md:116-169](), [README.md:172-257]()

## Environment and Dependencies

The build process relies on a carefully configured conda environment that provides all necessary dependencies:

| Dependency Category | Key Components | Purpose |
|-------------------|----------------|---------|
| **Python Runtime** | `python=3.11`, `pip>=24.0` | Core interpreter and package management |
| **PyTorch Stack** | `pytorch=2.5`, `pytorch-cuda=12.4` | Neural network backend and GPU support |
| **CUDA Toolkit** | `cuda-libraries-dev=12.4`, `cuda-nvcc=12.4` | GPU compilation and runtime |
| **Build Tools** | `cmake=3.31.1`, `gxx_linux-64=12.2` | Build system and compilers |
| **Amber Dependencies** | `fftw=3.3.10`, `netcdf-fortran=4.6.1` | MD simulation support |

The environment configuration is defined in [environment.yaml:1-68]() and automatically validated during the build process through [CMakeLists.txt:95-113]().

**Sources:** [environment.yaml:8-46](), [CMakeLists.txt:95-113]()

## Next Steps

To proceed with your TorchANI-Amber installation and setup:

1. **Installation**: Follow the detailed build instructions in [Installation and Build](#2.1), which covers environment setup, dependency resolution, and compilation of all required libraries.

2. **First Simulation**: Complete the hands-on tutorial in [Quick Start Tutorial](#2.2) to configure and run your first simulation with step-by-step guidance.

3. **Advanced Configuration**: For detailed information about simulation parameters, model options, and ML/MM setup, see [Simulation Configuration](#4.1).

4. **Performance Optimization**: To benchmark your installation and optimize performance, consult the [Benchmarking System](#5) documentation.

The build process typically takes 15-30 minutes depending on your system specifications and whether you're using GPU acceleration. Ensure you have a stable internet connection for downloading dependencies during the conda environment creation phase.

**Sources:** [README.md:29-95](), [CMakeLists.txt:214-224]()

---