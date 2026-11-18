# Build System

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.bumpversion.cfg](.bumpversion.cfg)
- [.github/ISSUE_TEMPLATE/bug_report.yml](.github/ISSUE_TEMPLATE/bug_report.yml)
- [.github/ISSUE_TEMPLATE/release.md](.github/ISSUE_TEMPLATE/release.md)
- [BUILDING.rst](BUILDING.rst)
- [CMakeLists.txt](CMakeLists.txt)
- [INSTALLING.rst](INSTALLING.rst)
- [hoomd/CMakeLists.txt](hoomd/CMakeLists.txt)
- [hoomd/hpmc/CMakeLists.txt](hoomd/hpmc/CMakeLists.txt)
- [hoomd/hpmc/module.cc](hoomd/hpmc/module.cc)
- [hoomd/hpmc/modules.h](hoomd/hpmc/modules.h)
- [hoomd/md/CMakeLists.txt](hoomd/md/CMakeLists.txt)
- [hoomd/mpcd/CMakeLists.txt](hoomd/mpcd/CMakeLists.txt)
- [hoomd/mpcd/module.cc](hoomd/mpcd/module.cc)
- [sphinx-doc/conf.py](sphinx-doc/conf.py)

</details>



This page documents the build system of HOOMD-blue, including how it is organized, its module structure, and how to compile it from source. The build system uses CMake to configure builds with various options, generate platform-specific build files, and manage dependencies.

## Overview

HOOMD-blue employs a CMake-based build system to provide a cross-platform build process. The system allows for configuring various simulation components and hardware acceleration options.

```mermaid
flowchart TD
    config["Configure with CMake"] --> build["Build Package"]
    build --> test["Run Tests"] 
    test --> install["Install"]
    
    subgraph "Configuration Options"
        gpu["GPU Support\nENABLE_GPU"]
        mpi["MPI Support\nENABLE_MPI"]
        modules["Modules\nBUILD_MD\nBUILD_HPMC\nBUILD_MPCD"]
        precision["Precision\nHOOMD_SHORTREAL_SIZE\nHOOMD_LONGREAL_SIZE"]
    end
    
    config --> gpu
    config --> mpi
    config --> modules
    config --> precision
```

Sources: [CMakeLists.txt:97-123](), [BUILDING.rst:77-150]()

## Project Structure

The build system is organized hierarchically, with the main CMakeLists.txt file in the root directory and subdirectory CMakeLists.txt files for each component.

```mermaid
graph TD
    root["Root CMakeLists.txt"] --> cmake["CMake/"]
    root --> hoomd["hoomd/CMakeLists.txt"]
    
    hoomd --> core["Core Components"]
    hoomd --> md["MD Module\n(if BUILD_MD=ON)"]
    hoomd --> hpmc["HPMC Module\n(if BUILD_HPMC=ON)"]
    hoomd --> mpcd["MPCD Module\n(if BUILD_MPCD=ON)"]
    hoomd --> metal["Metal Module\n(if BUILD_METAL=ON)"]
    hoomd --> plugins["Plugins\n(if specified)"]
    
    core --> Custom["custom/"]
    core --> Data["data/"]
    core --> Filter["filter/"]
    core --> Write["write/"]
    core --> Tune["tune/"]
    core --> Update["update/"]
    core --> Variant["variant/"]
```

Sources: [CMakeLists.txt:184](), [hoomd/CMakeLists.txt:341-348](), [hoomd/CMakeLists.txt:358-373]()

## Core Build Configuration

The main CMakeLists.txt file establishes the fundamental configuration for the build process. It sets up project metadata, compiler options, and makes primary build decisions.

Key features include:

- Project version management (both release version and Git-based versioning)
- Compiler flags and C++ standard settings (C++17)
- Build type selection (Debug, Release, RelWithDebInfo)
- Option definitions for components and features

Sources: [CMakeLists.txt:1-67](), [CMakeLists.txt:97-123](), [CMakeLists.txt:227-229]()

### Version Configuration

The build system automatically configures version information based on:

1. Hard-coded version from CMakeLists.txt
2. Git information using GetGitRevisionDescription module

This ensures each build is properly tagged with version information, supporting both development and release builds.

Sources: [CMakeLists.txt:17-48]()

## Build Options

HOOMD-blue supports multiple configuration options to customize the build:

| Option | Default | Description |
|--------|---------|-------------|
| `CMAKE_BUILD_TYPE` | `Release` | Build type: Debug, Release, RelWithDebInfo |
| `ENABLE_GPU` | `OFF` | Enable GPU acceleration |
| `HOOMD_GPU_PLATFORM` | `CUDA` | Choose GPU backend: CUDA or HIP |
| `ENABLE_MPI` | `OFF` | Enable multi-processor/GPU simulations using MPI |
| `BUILD_MD` | `ON` | Build Molecular Dynamics module |
| `BUILD_HPMC` | `ON` | Build Hard Particle Monte Carlo module |
| `BUILD_MPCD` | `ON` | Build Multi-Particle Collision Dynamics module |
| `BUILD_METAL` | `ON` | Build Metal module |
| `HOOMD_SHORTREAL_SIZE` | `32` | Size of ShortReal type in bits (32 or 64) |
| `HOOMD_LONGREAL_SIZE` | `64` | Size of LongReal type in bits (32 or 64) |
| `BUILD_TESTING` | `ON` | Build unit tests |

Sources: [CMakeLists.txt:97-123](), [BUILDING.rst:77-150](), [BUILDING.rst:219-252]()

## Module System

HOOMD-blue is organized into modules, each with its own CMakeLists.txt file.

```mermaid
graph LR
    core["Core (_hoomd)"]
    
    core --> md["MD (_md)"]
    core --> hpmc["HPMC (_hpmc)"]
    core --> mpcd["MPCD (_mpcd)"]
    core --> metal["Metal (_metal)"]
    
    subgraph "Core Components"
        core_comps["Operations\nForceComputes\nParticleData\nIntegration"]
    end
    
    subgraph "MD Components"
        md_comps["Pair Potentials\nMD Integrators\nForce Fields\nConstraints"]
    end
    
    subgraph "HPMC Components"
        hpmc_comps["Shape Definitions\nMonte Carlo Integrators\nOverlap Detection"]
    end
    
    subgraph "MPCD Components"
        mpcd_comps["Collision Methods\nStreaming Methods\nCell Lists"]
    end
    
    core --- core_comps
    md --- md_comps
    hpmc --- hpmc_comps
    mpcd --- mpcd_comps
```

Sources: [hoomd/CMakeLists.txt:217-222](), [hoomd/md/CMakeLists.txt:627-646](), [hoomd/hpmc/CMakeLists.txt:152-168](), [hoomd/mpcd/CMakeLists.txt:247-258]()

### Core Module

The core module is built as `_hoomd` and contains the fundamental structures needed for all simulations:

- Simulation infrastructure
- Particle data management
- System state tracking
- Operations framework
- Device management

It's implemented in [hoomd/CMakeLists.txt:217-222]() and creates a shared library that all other modules depend on.

### MD Module

The Molecular Dynamics module is built as `_md` and implements:

- Force computation
- MD integrators
- Pair potentials
- Bond/angle forces
- Neighbor lists

Sources: [hoomd/md/CMakeLists.txt:3-653](), [hoomd/md/CMakeLists.txt:627-646]()

### HPMC Module

The Hard Particle Monte Carlo module is built as `_hpmc` and implements:

- Shape definitions
- Overlap detection
- Monte Carlo moves
- Shape unions

Sources: [hoomd/hpmc/CMakeLists.txt:3-207](), [hoomd/hpmc/CMakeLists.txt:152-168](), [hoomd/hpmc/module.cc:4-166]()

### MPCD Module

The Multi-Particle Collision Dynamics module is built as `_mpcd` and implements:

- Collision methods
- Streaming methods
- Cell lists
- Geometry definitions
- Virtual particle fillers

Sources: [hoomd/mpcd/CMakeLists.txt:2-283](), [hoomd/mpcd/CMakeLists.txt:247-258](), [hoomd/mpcd/module.cc:1-336]()

## Build Process

The build process follows these steps:

```mermaid
flowchart TD
    clone["Clone Repository\ngit clone --recursive"] --> configure["Configure\ncmake -B build -S ."]
    configure --> build["Build\nninja"]
    build --> test["Test\npython3 -m pytest hoomd"]
    test --> install["Install\nninja install"]
    
    subgraph "Dependencies"
        deps["Required:\n- C++ Compiler\n- CMake\n- Python\n- NumPy\n- pybind11\n- Eigen"]
        gpu_deps["GPU Support:\n- CUDA Toolkit or\n- AMD ROCm"]
        mpi_deps["MPI Support:\n- MPI Library\n- cereal"]
    end
    
    deps --> clone
    gpu_deps --> configure
    mpi_deps --> configure
```

Sources: [BUILDING.rst:7-68](), [BUILDING.rst:182-269]()

### Building from Source

To build HOOMD-blue from source:

1. Install prerequisites:
   ```bash
   micromamba install cmake eigen git python numpy pybind11
   ```

2. Clone the repository with submodules:
   ```bash
   git clone --recursive git@github.com:glotzerlab/hoomd-blue.git
   ```

3. Configure the build:
   ```bash
   cmake -B build -S . -GNinja
   ```

4. Build the package:
   ```bash
   cd build
   ninja
   ```

5. Run tests:
   ```bash
   python3 -m pytest hoomd
   ```

6. Install:
   ```bash
   ninja install
   ```

Sources: [BUILDING.rst:7-68](), [BUILDING.rst:72-108](), [BUILDING.rst:151-178](), [BUILDING.rst:273-323]()

## GPU Acceleration Configuration

GPU support is a critical feature of HOOMD-blue. The build system manages this in a platform-independent way:

```mermaid
flowchart TD
    enable["ENABLE_GPU=on"] --> platform{HOOMD_GPU_PLATFORM?}
    
    platform -->|"CUDA"| cuda["NVIDIA CUDA Toolkit\ncuFFT, cuSPARSE"]
    platform -->|"HIP"| hip["AMD ROCm\nhipcc, rocFFT"]
    
    cuda --> cuda_compile["Compile CUDA Sources\n.cu Files"]
    hip --> hip_compile["Compile HIP Sources\n.cu -> HIP"]
    
    cuda_compile --> cuda_link["Link with CUDA Libraries"]
    hip_compile --> hip_link["Link with ROCm Libraries"]
    
    cuda_link --> final["Final GPU-enabled Binary"]
    hip_link --> final
```

The build system handles:
- Detection of GPU toolkit
- Setting up appropriate compiler flags
- Linking with GPU libraries
- Conditional compilation of GPU code

Sources: [CMakeLists.txt:101-103](), [hoomd/CMakeLists.txt:180-187](), [hoomd/CMakeLists.txt:267-285]()

## Parallel Computing with MPI

MPI support is configured through the `ENABLE_MPI` option:

```mermaid
flowchart LR
    mpi_option["ENABLE_MPI=on"] --> detect["Detect MPI Installation"]
    detect --> compile["Add MPI Compiler Flags"]
    compile --> dfft["Build Distributed FFT\n(if BUILD_MD=on)"]
    compile --> link["Link with MPI Libraries"]
    link --> enable_features["Enable MPI Communication\nin Components"]
```

When MPI is enabled, the build system:
- Links against MPI libraries
- Adds MPI-specific compilation flags
- Enables MPI-specific code paths in HOOMD-blue components

Sources: [CMakeLists.txt:133](), [hoomd/CMakeLists.txt:289-292](), [hoomd/CMakeLists.txt:358-362]()

## Plugin System

HOOMD-blue allows for building external plugins as part of the build process:

```mermaid
flowchart LR
    plugins["PLUGINS=\"plugin1;plugin2\""] --> core_build["Build Core HOOMD"]
    core_build --> loop["For Each Plugin Entry"]
    loop --> check{"CMakeLists.txt exists?"}
    check -->|"Yes"| build_plugin["Build Plugin"]
    check -->|"No"| skip["Skip"]
    build_plugin --> done{"All Plugins Done?"}
    skip --> done
    done -->|"No"| loop
    done -->|"Yes"| final["Complete Build"]
```

Plugins are specified through the `PLUGINS` variable as a semicolon-separated list of directories.

Sources: [CMakeLists.txt:122](), [hoomd/CMakeLists.txt:375-380]()

## Installation Process

Once built, HOOMD-blue can be installed with the generated build system:

```mermaid
flowchart TD
    build["Build Complete"] --> install["ninja install"]
    
    install --> lib["Install Shared Libraries\n.so/.dylib"]
    install --> py["Install Python Modules"]
    install --> include["Install Header Files"]
    install --> cmake_conf["Install CMake Config Files"]
    
    lib --> prefix["CMAKE_INSTALL_PREFIX/\nPYTHON_SITE_INSTALL_DIR"]
    py --> prefix
    include --> prefix
    cmake_conf --> prefix
```

Key installation targets include:
- Shared libraries for each module
- Python modules
- Header files for C++ development
- CMake configuration files for downstream projects

Sources: [hoomd/CMakeLists.txt:300-304](), [hoomd/CMakeLists.txt:328-331](), [hoomd/CMakeLists.txt:336-338](), [CMakeLists.txt:202-220]()

## Conclusion

HOOMD-blue's build system provides a flexible, modular approach to building a high-performance simulation framework. It accommodates different hardware configurations, simulation methods, and deployment scenarios through a comprehensive set of build options.

The CMake-based build process ensures cross-platform compatibility while managing the complexities of GPU acceleration, parallel computing, and Python integration.

---