

Rosetta's build system is built on top of [SCons](https://scons.org/), an open-source software construction tool implemented in Python. Rather than relying on a simple Makefile hierarchy, Rosetta wraps SCons with a sophisticated multi-layer settings cascade that resolves compiler flags, platform paths, and project configurations through an algorithmic merge of dozens of `.settings` files. This architecture allows a single invocation of `scons` to produce platform-aware builds across Linux, macOS, Windows, and various HPC environments without manual Makefile editing. The entire build infrastructure lives under `source/tools/build/`, with the two top-level orchestrators — `source/SConstruct` and `source/SConscript` — serving as the entry points that bootstrap and dispatch the build graph.

Sources: [SConstruct](source/SConstruct#L1-L206), [SConscript](source/SConscript#L1-L76)

## Architecture Overview

The SCons build system operates as a multi-stage pipeline. When you invoke `scons`, control flows through a carefully ordered sequence: option parsing → settings resolution → environment construction → project dispatch → compilation. The following diagram illustrates this architecture at a macro level.

```mermaid
flowchart TD
    A["scons [options] [targets]"] --> B["SConstruct (entry point)"]
    B --> C["tools/build/setup.py :: setup()"]
    C --> D["copy_template_files()"]
    C --> E["setup_build_options()"]
    C --> F["setup_build_settings()"]
    C --> G["setup_environment()"]
    C --> H["setup_platform_path()"]
    C --> I["setup_projects()"]
    E --> E1["basic.options (defaults)"]
    E --> E2["site.options / user.options"]
    E --> E3["options.settings (validation)"]
    F --> F1["basic.settings (~3000 lines)"]
    F --> F2["site.settings"]
    F --> F3["user.settings"]
    F --> F4["Algorithmic key merging"]
    G --> G1["SCons Environment construction"]
    H --> I
    I --> J["SConscript (main dispatcher)"]
    J --> K{"project kind?"}
    K -->|src (apps/pilot_apps)| K1["src/SConscript.apps → executables"]
    K -->|src (lib projects)| K2["src/SConscript.src → libraries"]
    K -->|test| K3["test/SConscript.test"]
    K -->|external| K4["external/SConscript.external"]
    K -->|doc| K5["doc/SConscript.doc"]
    K1 & K2 & K3 & K4 & K5 --> L["build/&lt;mode&gt;/&lt;platform&gt;/"]
```

The `BuildState` object — defined in [settings.py](source/tools/build/settings.py#L437-L452) — is the central data structure threading through every stage. It carries the resolved environment, platform path, option set, project list, and all accumulated build settings from the top-level `SConstruct` down into every sub-project `SConscript`.

Sources: [settings.py — BuildState](source/tools/build/settings.py#L437-L452), [setup.py — setup()](source/tools/build/setup.py#L497-L516)

## Build Configuration Pipeline

### Prerequisites and Invocation

The build system requires **SCons ≥ 0.98.1** and **Python ≥ 2.7** ([SConstruct#L8-L12](source/SConstruct#L8-L12)). The canonical production build command is:

```bash
./scons.py -j 8 mode=release bin
```

where `-j 8` controls parallel compilation threads and `bin` is the target that installs all executables into the output directory. The basic invocation form follows this pattern:

```
scons [flags] [<options>] [<targets>]
```

SCons flags (prefixed with `-`) control the SCons engine itself (e.g., `-j`, `-D`, `-H`), while Rosetta options are `key=value` pairs that configure the build type. Targets specify which projects or directories to compile.

Sources: [SConstruct — help text](source/SConstruct#L63-L178)

### Options System

Build options are defined across three layers, each with increasing specificity:

| File | Purpose | Modified by |
|---|---|---|
| `basic.options` | Default values for all options | **Never** — repository-controlled |
| `site.options` | Site-wide defaults (cluster-specific) | System administrators |
| `user.options` | Per-developer defaults | Individual developers |
| Command line | Runtime overrides | Build invocation |

The supported option keys and their permissible values are enumerated in [options.settings](source/tools/build/options.settings#L9-L196). The six primary option dimensions are:

| Option | Description | Key Values |
|---|---|---|
| `cxx` | C++ compiler family | `gcc`, `clang`, `icc`, `msvc`, `xlc` |
| `cxx_ver` | Compiler version | e.g., `5.1`, `6.3`, `*` (auto-detect) |
| `os` | Target operating system | `linux`, `macos`, `windows`, `cygwin` |
| `arch` | Processor architecture | `x86`, `amd`, `ppc`, `arm`, `aarch64` |
| `mode` | Build optimization level | `debug`, `release`, `release_native`, `release_symbols`, `profile`, `coverage`, `addsane`, `memsan`, `tsan`, `ubsan` |
| `cat` | Build category | `src`, `external`, `test`, `doc` |

Options use `*` as a wildcard, resolved automatically by [setup_platforms.py](source/tools/build/setup_platforms.py). For instance, macOS 10.9+ (Darwin kernel version ≥ 13) defaults to `clang` rather than `gcc` ([basic.options#L23-L27](source/tools/build/basic.options#L23-L27)).

Sources: [basic.options](source/tools/build/basic.options#L1-L46), [options.settings](source/tools/build/options.settings#L9-L196)

### Settings Cascade and Resolution

The settings system is the most architecturally distinctive component. Rather than using static Makefile rules, Rosetta resolves compiler flags through an **algorithmic cascade** that merges settings dictionaries based on a computed set of identifier keys. The resolution process works as follows:

1. A set of **possible setting IDs** is generated from combinations of the current options — for example `"gcc, linux, release"`, `"gcc, 6.3, linux, release"`, `"gcc, x86, 64"`, etc.
2. Each ID is looked up in the aggregated settings pool (from `basic.settings`, `site.settings`, and `user.settings`).
3. Matching settings are wrapped in `BuildSettingsCombined` objects, each carrying four merge strategies: **prepends**, **appends**, **overrides**, and **removes**.
4. These are applied sequentially to a fresh `SCons Environment` in [setup_environment()](source/tools/build/setup.py#L440-L494).

The merge precedence (last writer wins) follows this order, from lowest to highest priority:

```mermaid
flowchart LR
    A["base"] --> B["os"]
    B --> C["os, os_ver"]
    C --> D["compiler"]
    D --> E["compiler, version"]
    E --> F["compiler, os"]
    F --> G["compiler, ver, os, ver"]
    G --> H["compiler, arch, size"]
    H --> I["compiler, mode"]
    I --> J["compiler, os, arch"]
    J --> K["compiler, extra"]
    K --> L["site.settings"]
    L --> M["user.settings"]
```

The `basic.settings` file spans over **3,000 lines** and defines everything from base include paths and preprocessor defines ([basic.settings#L66-L104](source/tools/build/basic.settings#L66-L104)) to per-compiler flag sets — for instance, the GCC configuration includes `-std=c++0x`, warning flags (`-Wall -Wextra -Werror`), and `-isystem` directives for suppressing warnings from external headers like Boost ([basic.settings#L145-L193](source/tools/build/basic.settings#L145-L193)).

> [!TIP]
> When adding a new external dependency, use `overrides` in `user.settings` to add include/library paths, or `appends` to add linker flags. Never modify `basic.settings` directly — it is repository-controlled and shared across all developers.

Sources: [basic.settings — merge order documentation](source/tools/build/basic.settings#L9-L56), [basic.settings — base settings](source/tools/build/basic.settings#L66-L193), [setup.py — setup_build_settings()](source/tools/build/setup.py#L212-L328)

### Environment Construction

The `setup_environment()` function ([setup.py#L440-L494](source/tools/build/setup.py#L440-L494)) translates the merged `BuildSettingsCombined` objects into a concrete SCons `Environment`. This is where the four merge strategies take effect:

- **`appends`**: Adds flags to the end of existing lists (e.g., adding `-O2` to the existing optimization flags).
- **`prepends`**: Adds flags to the beginning of existing lists (e.g., putting a custom include path before system defaults).
- **`overrides`**: Replaces existing values entirely (e.g., setting a specific compiler command).
- **`removes`**: Strips individual values from existing lists (e.g., removing a conflicting `-D` define).

The `BuildSettings.symbols()` method ([settings.py#L260-L349](source/tools/build/settings.py#L260-L349)) converts the high-level flag categories (`cc`, `cxx`, `compile`, `link`, `warn`, `mode`) into SCons-native symbols like `CCFLAGS`, `CXXFLAGS`, `CFLAGS`, `LINKFLAGS`, `CPPPATH`, `LIBPATH`, and `LIBS`. It also handles SCons version-specific bugs (#846 and #1971) by branching on the detected SCons version.

Sources: [setup.py — setup_environment()](source/tools/build/setup.py#L440-L494), [settings.py — BuildSettings.symbols()](source/tools/build/settings.py#L260-L349)

## Extras System

The `extras` option ([options.settings#L71-L196](source/tools/build/options.settings#L71-L196)) is the primary extension mechanism for enabling optional features. Extras are specified as a comma-separated list and each one injects additional compiler flags, library dependencies, and preprocessor defines through the settings cascade. Multiple extras can be combined in a single build:

```bash
scons mode=release extras=mpi,serialization bin
```

The following table summarizes the most commonly used extras:

| Extra | Purpose | Notes |
|---|---|---|
| `static` | Static linking instead of shared libraries | More portable, larger binaries |
| `mpi` | MPI-based parallelism | Requires MPI runtime installed |
| `serialization` | Boost serialization support | Needed for distributed protocols |
| `cxx11thread` | C++11 threading utilities | Multi-threaded execution support |
| `omp` | OpenMP parallelism | Compiler-specific OpenMP flags |
| `python` | Link to Python interpreter | For embedded Python extensions |
| `cuda` / `opencl` | GPU computing support | Requires CUDA/OpenCL toolkits |
| `hdf5` | HDF5 data stores | For structured data I/O |
| `tensorflow` / `tensorflow_gpu` | TensorFlow integration | ML extension linking |
| `torch` / `torch_gpu` | LibTorch integration | PyTorch C++ backend |
| `cxx14` / `cxx17` / `cxx20` | C++ standard level | Defines `CXX14_OR_LATER`, etc. |
| `boinc` | BOINC support | Used by Rosetta@home |
| `valgrind` | Valgrind-compatible build | Adds `--valgrind` flags |
| `lto` | Link-time optimization | Slower build, faster runtime |

Each extra activates a corresponding settings key in `basic.settings` (e.g., `"gcc, mpi"` or `"clang, cuda"`) that appends the necessary flags and libraries to the build environment.

Sources: [options.settings — extras list](source/tools/build/options.settings#L71-L196), [SConstruct — examples](source/SConstruct#L150-L177)

## Platform Path Convention

The build output directory follows a structured platform path generated by `setup_platform_path()` ([setup.py#L331-L349](source/tools/build/setup.py#L331-L349)). The format is:

```
build/<mode>/<os>/<os_ver>/<arch_size>/<arch>/<cxx>/<cxx_ver>/<extras>
```

For example, a release build with GCC 6.3 on 64-bit Linux would produce:

```
build/release/linux/x86_64/64/x86/gcc/6.3/default/
```

The `<os_ver>` component is omitted when set to `*` (auto-detected), and `<extras>` defaults to `"default"` when no extras are specified. This naming convention ensures that builds for different platforms, compiler versions, and feature sets never collide in the same source tree, enabling simultaneous multi-configuration builds.

Sources: [setup.py — setup_platform_path()](source/tools/build/setup.py#L331-L349)

## Project Dispatch and SConscript Hierarchy

The top-level `SConscript` ([source/SConscript](source/SConscript#L1-L76)) is responsible for dispatching the build to sub-project SConscripts. Before dispatching, it performs three critical pre-build steps:

1. **Version generation** — runs `version.py` to embed the SVN/Git revision into `src/core/svn_version.cc` (skippable with `--nover`)
2. **Options update** — executes `update_options.sh` to synchronize option definitions
3. **Submodule initialization** — runs `update_submodules.sh` to fetch required git submodules

Each project kind is then dispatched to its own SConscript with a `variant_dir` mapping that redirects build artifacts into the platform-specific `build/` subdirectory:

```python
SConscript(script, exports=["build", "project"],
           variant_dir=build_path, duplicate=False)
```

The `duplicate=False` parameter is significant — it tells SCons to reference source files in-place rather than copying them into the build directory, keeping the build tree shallow.

Sources: [SConscript — dispatch logic](source/SConscript#L46-L68)

## User Customization

Developers customize their builds through two mechanisms that sit at the top of the settings cascade:

**`user.settings`** — Created from `user.settings.template` ([user.settings.template](source/tools/build/user.settings.template#L1-L52)), this file allows you to prepend, append, override, or remove any build setting. Common use cases include adding custom include paths for external libraries, importing the full OS environment (`"ENV" : os.environ`), or enabling experimental preprocessor defines.

**`user.options`** — Created from `user.options.template`, this file sets default option values so you don't need to specify them on every `scons` invocation. For example, a developer on a cluster with Intel MPI might set `extras = "mpi"` here.

Both files are gitignored and never checked into the repository. Template files are auto-copied on first build via `copy_template_files()` in [setup.py#L17-L23](source/tools/build/setup.py#L17-L23).

> [!TIP]
> During rapid development iteration, use `scons --nover` to skip the versioning and submodule update scripts. This avoids recompiling files that depend on `svn_version.cc` and can significantly reduce incremental build times — but **never** use it for production builds.

Sources: [user.settings.template](source/tools/build/user.settings.template#L1-L52), [setup.py — copy_template_files()](source/tools/build/setup.py#L17-L23)

## Core Settings Classes

The settings infrastructure is implemented through a class hierarchy in [settings.py](source/tools/build/settings.py#L1-L452) that provides structured, validated access to build configuration:

| Class | Purpose | Key Slot Fields |
|---|---|---|
| `Settings` | Base dictionary with attribute access | Dynamic via `__slots__` |
| `BuildOptionsSupported` | Enumerates all valid option values | `cxx`, `os`, `arch`, `mode`, `cat`, `extras` |
| `BuildOptions` | Resolved options for current build | `cxx`, `cxx_ver`, `os`, `os_ver`, `arch`, `arch_size`, `mode`, `cat`, `extras` |
| `BuildFlags` | Categorized compiler flags | `cc`, `cxx`, `compile`, `link`, `shlink`, `mode`, `warn` |
| `BuildSettings` | Single setting layer with symbols | `flags`, `defines`, `include_path`, `library_path`, `libraries` |
| `BuildSettingsCombined` | Wraps a setting with merge strategy | `id`, `appends`, `prepends`, `overrides`, `removes` |
| `ProjectSettings` | Per-project settings from `.src.settings` | `sources`, `defines`, `include_path`, `libraries` |
| `BuildState` | Global build state passed through SConscripts | `environment`, `platform`, `options`, `projects`, `settings` |

All classes inherit from Python's `dict` and use `__slots__` to enforce a fixed schema, catching typos at attribute-access time rather than silently storing incorrect keys.

Sources: [settings.py — class hierarchy](source/tools/build/settings.py#L65-L452)

## Common Build Recipes

The following table provides a quick reference for typical build scenarios:

| Goal | Command |
|---|---|
| Default debug build | `scons` |
| Production release build | `scons -j 8 mode=release bin` |
| Build a specific project | `scons mode=release <project_name>` |
| Build a specific executable | `scons mode=release bin/<exec_name>` |
| Enable MPI + serialization | `scons mode=release extras=mpi,serialization bin` |
| Static linking (portable binaries) | `scons mode=release extras=static bin` |
| Build unit tests | `scons cat=test` then `python test/run.py` |
| Fast incremental dev build | `scons --nover` |
| Debug logging of build decisions | `scons log=toplevel,platform,options,settings` |
| Native-optimized (run on compile machine only) | `scons mode=release_native bin` |

## Relationship to CMake

Rosetta also ships with a CMake-based build configuration. The SCons system is the older, more established build path and remains the default for many HPC and cluster environments. The CMake system provides a more conventional alternative that may be preferred for IDE integration and cross-platform workflows. For a full comparison and CMake-specific guidance, see [CMake Build Configuration](7-cmake-build-configuration).
