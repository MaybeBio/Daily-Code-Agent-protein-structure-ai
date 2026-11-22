# Build System

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.astyle.options](.astyle.options)
- [.ci/install.autoconf](.ci/install.autoconf)
- [.codecov.yml](.codecov.yml)
- [.gitignore](.gitignore)
- [Makefile](Makefile)
- [Makefile.conf.in](Makefile.conf.in)
- [astyle/.gitignore](astyle/.gitignore)
- [astyle/Makefile](astyle/Makefile)
- [configure](configure)
- [configure.ac](configure.ac)
- [developer-doc/InstallationLayout.md](developer-doc/InstallationLayout.md)
- [src/Makefile](src/Makefile)
- [src/README](src/README)
- [src/asmjit/COPYRIGHT](src/asmjit/COPYRIGHT)
- [src/asmjit/Makefile](src/asmjit/Makefile)
- [src/asmjit/arm.h](src/asmjit/arm.h)
- [src/asmjit/asmjit.h](src/asmjit/asmjit.h)
- [src/astyle.sh](src/astyle.sh)
- [src/lib/Makefile](src/lib/Makefile)
- [src/maketools/codecheck](src/maketools/codecheck)
- [src/maketools/make.rules](src/maketools/make.rules)
- [src/maketools/plumedcheck](src/maketools/plumedcheck)
- [src/tools/Exception.cpp](src/tools/Exception.cpp)
- [src/tools/Exception.h](src/tools/Exception.h)

</details>



The PLUMED build system configures, compiles, and installs the PLUMED software. It is designed for portability, modularity, and integration with a variety of molecular dynamics (MD) engines. The system is based on GNU Autoconf for configuration and GNU Make for building, and includes code quality checks and installation layout logic.

For an overview of the overall architecture, see [Core Architecture](2).

---

## High-Level Build System Flow

The build system consists of several key stages: configuration, build, and output generation. The following diagram maps the main code entities involved in each stage.

**Diagram: Build System Flow and Code Entities**

```mermaid
flowchart TD
    subgraph "Configuration"
        "configure.ac"["configure.ac"] -->|"autoconf"| "configure"["configure (script)"]
        "configure" -->|"generates"| "Makefile.conf"
        "Makefile.conf.in"["Makefile.conf.in"] -->|"template"| "Makefile.conf"
    end

    subgraph "Build"
        "Makefile.conf" -->|"included by"| "Makefile"
        "Makefile" -->|"calls"| "src/Makefile"
        "src/Makefile" -->|"calls"| "src/lib/Makefile"
    end

    subgraph "Output"
        "src/lib/Makefile" -->|"produces"| "libplumedKernel.so"
        "src/lib/Makefile" -->|"produces"| "libplumed.so"
        "src/lib/Makefile" -->|"produces"| "libplumedWrapper.a"
        "src/lib/Makefile" -->|"produces"| "plumed (executable)"
    end
```

**Key Code Entities:**
- `configure.ac`, `configure`, `Makefile.conf.in`, `Makefile.conf`
- `Makefile`, `src/Makefile`, `src/lib/Makefile`
- Output artifacts: `libplumedKernel.so`, `libplumed.so`, `libplumedWrapper.a`, `plumed`

Sources: [configure.ac:1-146](), [Makefile:1-153](), [src/Makefile:1-72](), [src/lib/Makefile:1-100]()

## Configuration Process

The configuration process is handled by the `configure` script, which is generated from `configure.ac` using Autoconf. This script detects system features, compiler capabilities, and available libraries, and sets up the build environment according to user-specified options.

### Running the Configure Script

Basic usage:

```bash
./configure [options]
```

The script supports a wide range of options for customizing the build. The most important options are summarized below.

| Option | Description |
|--------|-------------|
| `--prefix=DIR` | Install files in DIR (default: `/usr/local`) |
| `--enable-modules=LIST` | Enable/disable modules (see below) |
| `--enable-mpi` | Enable MPI support |
| `--enable-debug` | Enable debugging |
| `--enable-shared` | Build shared libraries (default: yes) |
| `--enable-static-archive` | Build static library archive (default: yes) |
| `--enable-cxx=LEVEL` | Set C++ standard (17, 20, or 23) |
| `--disable-doc` | Disable documentation generation |
| `--disable-libsearch` | Disable automatic library detection |

Sources: [configure.ac:195-327](), [configure:1-500]()

---

### Module Management

PLUMED is organized into modules, which can be enabled or disabled at configuration time. Modules are classified as `always`, `default-on`, or `default-off`. The `--enable-modules` option controls which modules are included.

**Diagram: Module Enable/Disable Logic**

```mermaid
flowchart TD
    "configure.ac"["configure.ac"] -->|"--enable-modules=all"| "Enable all modules"
    "configure.ac" -->|"--enable-modules=none"| "Disable all optional modules"
    "configure.ac" -->|"--enable-modules=reset"| "Reset to default"
    "configure.ac" -->|"--enable-modules=+modA:-modB"| "Enable/disable specific modules"

    subgraph "Module Types"
        "always"["always"]
        "default-on"["default-on"]
        "default-off"["default-off"]
    end
```

**Examples:**
```bash
./configure --enable-modules=all
./configure --enable-modules=none
./configure --enable-modules=+crystallization:-bias
```

Sources: [configure.ac:198-253]()

## Build Process

After configuration, the build process is managed by GNU Make. The main entry points are the top-level `Makefile`, `src/Makefile`, and `src/lib/Makefile`. These Makefiles coordinate the compilation of libraries, executables, and scripts.

### Build Commands

| Command | Description |
|---------|-------------|
| `make` | Build PLUMED libraries and executables |
| `make install` | Install PLUMED to the specified prefix |
| `make clean` | Remove build artifacts |
| `make distclean` | Remove all build and configuration files |
| `make check` | Run tests (non-installed PLUMED) |
| `make installcheck` | Run tests (installed PLUMED) |

Sources: [Makefile:16-77](), [src/Makefile:1-72](), [src/lib/Makefile:1-100]()

---

### Build Outputs and Artifacts

PLUMED produces several libraries and executables to support different integration and usage scenarios.

**Diagram: Build Outputs and Their Relationships**

```mermaid
flowchart TD
    subgraph "Libraries"
        "libplumedKernel.so"["libplumedKernel.so/dylib (core)"]
        "libplumed.so"["libplumed.so/dylib (complete)"]
        "libplumedWrapper.a"["libplumedWrapper.a (static wrapper)"]
    end

    subgraph "Executables"
        "plumed"["plumed (main executable)"]
        "plumed-static"["plumed-static (static)"]
        "plumed-runtime"["plumed-runtime (runtime loading)"]
    end

    "libplumedKernel.so" -->|"linked by"| "libplumed.so"
    "libplumedKernel.so" -->|"linked by"| "plumed-static"
    "libplumed.so" -->|"linked by"| "plumed"
    "libplumedWrapper.a" -->|"runtime loading"| "libplumedKernel.so"
    "plumed-runtime" -->|"loads at runtime"| "libplumedKernel.so"
```

Sources: [src/lib/Makefile:73-99]()

## Integration with MD Engines

PLUMED supports multiple integration methods with molecular dynamics (MD) engines. The build system produces different artifacts to support these methods.

**Diagram: Integration Methods and Code Artifacts**

```mermaid
flowchart LR
    subgraph "IntegrationMethods"
        "RuntimeLoading"["Runtime Loading"]
        "DynamicLinking"["Dynamic Linking"]
        "StaticLinking"["Static Linking"]
    end

    subgraph "PLUMEDLibraries"
        "libplumedKernel.so"["libplumedKernel.so/dylib"]
        "libplumed.so"["libplumed.so/dylib"]
        "libplumedWrapper.a"["libplumedWrapper.a"]
    end

    subgraph "MDEngine"
        "PatchedMDCode"["Patched MD Code"]
    end

    "RuntimeLoading" -->|"uses"| "libplumedWrapper.a"
    "libplumedWrapper.a" -->|"loads"| "libplumedKernel.so"
    "DynamicLinking" -->|"links against"| "libplumed.so"
    "StaticLinking" -->|"embeds"| "libplumedWrapper.a"
    "PatchedMDCode" -->|"calls"| "RuntimeLoading"
    "PatchedMDCode" -->|"calls"| "DynamicLinking"
    "PatchedMDCode" -->|"contains"| "StaticLinking"
```

- **Runtime Loading**: MD code statically links `libplumedWrapper.a` and loads `libplumedKernel.so` at runtime.
- **Dynamic Linking**: MD code links directly against `libplumed.so`.
- **Static Linking**: PLUMED source or objects are compiled directly into the MD code.

Sources: [src/lib/Makefile:434-515]()

## Dependency Management

PLUMED supports a range of optional dependencies, which can be enabled or disabled at configuration time. The build system detects and configures these dependencies as needed.

| Dependency | Configure Option | Purpose |
|------------|-----------------|---------|
| LAPACK/BLAS | `--enable-external-lapack/blas` | Linear algebra |
| MPI | `--enable-mpi` | Parallel execution |
| FFTW | `--enable-fftw` | Fast Fourier Transforms |
| GSL | `--enable-gsl` | Advanced math functions |
| Python | `--enable-python` | Python interface |
| OpenMP | `--enable-openmp` | Shared-memory parallelism |
| zlib | `--enable-zlib` | Compression support |

The `--disable-libsearch` option disables automatic library detection, requiring explicit library paths.

Sources: [configure.ac:514-836]()

## Installation

The installation process copies built files to their final locations as specified by the configuration.

### Installation Paths

| Variable | Default | Description |
|----------|---------|-------------|
| `prefix` | `/usr/local` | Base installation directory |
| `bindir` | `${prefix}/bin` | Executables directory |
| `libdir` | `${prefix}/lib` | Libraries directory |
| `includedir` | `${prefix}/include` | Header files directory |
| `htmldir` | `${datarootdir}/doc/${PACKAGE_TARNAME}` | Documentation directory |

Sources: [Makefile.conf.in:19-50](), [configure.ac:807-825]()

### Installation Steps

The `make install` target performs the following:

1. Creates required directories
2. Installs libraries (`libplumed.so`, `libplumedKernel.so`, `libplumedWrapper.a`)
3. Installs executables (`plumed`, `plumed-patch`, etc.)
4. Installs header files
5. Installs documentation and examples
6. Installs additional tools and scripts

Sources: [src/lib/Makefile:212-386]()

## Distribution and Packaging

PLUMED supports packaging for multiple platforms and package managers.

- **MacPorts**: Templates in `macports/` for MacPorts packaging (`Portfile.in`, `PortfilePython.in`)
- **Conda**: Recipes in `conda/` for Conda packages (`plumed/meta.yaml`, `plumed/build.sh`, `py-plumed/`)
- **Docker**: Dockerfiles in `docker/` for various Linux distributions

Sources: [macports/Portfile.in:1-122](), [conda/plumed/meta.yaml:1-65](), [docker/Makefile:1-24]()

## Continuous Integration

PLUMED uses GitHub Actions for continuous integration (CI) across multiple platforms. The CI system builds, tests, and checks code quality for all supported configurations.

**Diagram: CI Workflow and Code Entities**

```mermaid
flowchart LR
    "GitHubActions"[".github/workflows/ci.yml"] --> "LinuxBuild"["Linux Build"]
    "GitHubActions" --> "CodeCheck"["Code Check"]
    "GitHubActions" --> "macOSBuild"["macOS Build"]
    "GitHubActions" --> "DockerBuild"["Docker Build"]
    "GitHubActions" --> "CondaBuild"["Conda Build"]

    "LinuxBuild" --> "RunTests"["Run Tests"]
    "macOSBuild" --> "RunTests"
    "DockerBuild" --> "RunTests"
    "CondaBuild" --> "RunTests"
```

The CI system performs:
- Compilation with different compilers and options
- Unit and regression tests
- Code style and formatting checks
- Packaging tests

Sources: [.github/workflows/ci.yml:1-37](), [.github/workflows/macWF.yml:1-99](), [.github/workflows/codecheckWF.yml:1-18]()

## Code Quality and Static Analysis

The build system integrates several tools for code quality and static analysis.

| Tool | Command | Description |
|------|---------|-------------|
| astyle | `make astyle` | Enforces code formatting |
| codecheck | `make codecheck` | Runs static analysis (cppcheck, plumedcheck) |
| plumedcheck | `make plumedcheck` | PLUMED-specific code checks |

**Diagram: Code Quality Tools and Scripts**

```mermaid
flowchart TD
    "Makefile"["Makefile"] -->|"make astyle"| "src/astyle.sh"
    "Makefile" -->|"make codecheck"| "src/maketools/codecheck"
    "Makefile" -->|"make plumedcheck"| "src/maketools/plumedcheck"
    "src/maketools/codecheck" -->|"calls"| "src/maketools/plumedcheck"
    "src/maketools/codecheck" -->|"calls"| "cppcheck"
```

Sources: [src/maketools/plumedcheck:1-100](), [src/maketools/codecheck:1-167](), [src/astyle.sh:1-52]()

## Conclusion

The PLUMED build system provides a flexible framework for compiling, installing, and distributing the software. It supports various integration methods with MD engines, platform-specific optimizations, and optional dependencies. By understanding the build system, users can customize PLUMED to their specific needs and environments.

Sources: [configure:1-500](), [configure.ac:1-100](), [Makefile:1-153](), [src/lib/Makefile:1-100]()

---