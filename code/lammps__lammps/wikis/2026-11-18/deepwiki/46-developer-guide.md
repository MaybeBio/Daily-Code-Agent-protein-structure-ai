# Developer Guide

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [cmake/CMakeLists.txt](cmake/CMakeLists.txt)
- [cmake/LAMMPSConfig.cmake.in](cmake/LAMMPSConfig.cmake.in)
- [cmake/Modules/Documentation.cmake](cmake/Modules/Documentation.cmake)
- [cmake/Modules/FindCythonize.cmake](cmake/Modules/FindCythonize.cmake)
- [cmake/Modules/FindVORO.cmake](cmake/Modules/FindVORO.cmake)
- [cmake/Modules/LAMMPSInterfacePlugin.cmake](cmake/Modules/LAMMPSInterfacePlugin.cmake)
- [cmake/Modules/LAMMPSUtils.cmake](cmake/Modules/LAMMPSUtils.cmake)
- [cmake/Modules/MPI4WIN.cmake](cmake/Modules/MPI4WIN.cmake)
- [cmake/Modules/OpenCLLoader.cmake](cmake/Modules/OpenCLLoader.cmake)
- [cmake/Modules/Packages/COLVARS.cmake](cmake/Modules/Packages/COLVARS.cmake)
- [cmake/Modules/Packages/GPU.cmake](cmake/Modules/Packages/GPU.cmake)
- [cmake/Modules/Packages/KIM.cmake](cmake/Modules/Packages/KIM.cmake)
- [cmake/Modules/Packages/KOKKOS.cmake](cmake/Modules/Packages/KOKKOS.cmake)
- [cmake/Modules/Packages/LEPTON.cmake](cmake/Modules/Packages/LEPTON.cmake)
- [cmake/Modules/Packages/MACHDYN.cmake](cmake/Modules/Packages/MACHDYN.cmake)
- [cmake/Modules/Packages/PYTHON.cmake](cmake/Modules/Packages/PYTHON.cmake)
- [cmake/Modules/Packages/VORONOI.cmake](cmake/Modules/Packages/VORONOI.cmake)
- [cmake/Modules/StyleHeaderUtils.cmake](cmake/Modules/StyleHeaderUtils.cmake)
- [cmake/Modules/Testing.cmake](cmake/Modules/Testing.cmake)
- [cmake/pkgconfig/liblammps.pc.in](cmake/pkgconfig/liblammps.pc.in)
- [cmake/presets/all_off.cmake](cmake/presets/all_off.cmake)
- [cmake/presets/all_on.cmake](cmake/presets/all_on.cmake)
- [cmake/presets/mingw-cross.cmake](cmake/presets/mingw-cross.cmake)
- [cmake/presets/most.cmake](cmake/presets/most.cmake)
- [cmake/presets/nolib.cmake](cmake/presets/nolib.cmake)
- [cmake/presets/windows.cmake](cmake/presets/windows.cmake)
- [doc/.gitignore](doc/.gitignore)
- [doc/Makefile](doc/Makefile)
- [doc/README](doc/README)
- [doc/documentation_conventions.md](doc/documentation_conventions.md)
- [doc/src/404.rst](doc/src/404.rst)
- [doc/src/Build_manual.rst](doc/src/Build_manual.rst)
- [doc/src/Build_windows.rst](doc/src/Build_windows.rst)
- [doc/src/Developer.rst](doc/src/Developer.rst)
- [doc/src/Developer_code_design.rst](doc/src/Developer_code_design.rst)
- [doc/src/Developer_notes.rst](doc/src/Developer_notes.rst)
- [doc/src/Developer_platform.rst](doc/src/Developer_platform.rst)
- [doc/src/Developer_plugins.rst](doc/src/Developer_plugins.rst)
- [doc/src/Developer_updating.rst](doc/src/Developer_updating.rst)
- [doc/src/Errors_bugs.rst](doc/src/Errors_bugs.rst)
- [doc/src/Intro_website.rst](doc/src/Intro_website.rst)
- [doc/src/JPG/lammps-lost-logo-library.jpg](doc/src/JPG/lammps-lost-logo-library.jpg)
- [doc/src/Manual.rst](doc/src/Manual.rst)
- [doc/src/Modify.rst](doc/src/Modify.rst)
- [doc/src/Modify_atom.rst](doc/src/Modify_atom.rst)
- [doc/src/Modify_contribute.rst](doc/src/Modify_contribute.rst)
- [doc/src/Modify_overview.rst](doc/src/Modify_overview.rst)
- [doc/src/Modify_requirements.rst](doc/src/Modify_requirements.rst)
- [doc/src/Modify_style.rst](doc/src/Modify_style.rst)
- [doc/src/Modify_thermo.rst](doc/src/Modify_thermo.rst)
- [doc/src/Modify_variable.rst](doc/src/Modify_variable.rst)
- [doc/src/dumps.rst](doc/src/dumps.rst)
- [doc/src/fix_modify.rst](doc/src/fix_modify.rst)
- [doc/src/fix_reaxff_bonds.rst](doc/src/fix_reaxff_bonds.rst)
- [doc/src/fix_reaxff_species.rst](doc/src/fix_reaxff_species.rst)
- [doc/src/plugin.rst](doc/src/plugin.rst)
- [doc/utils/pandoc.css](doc/utils/pandoc.css)
- [doc/utils/pandoc.html](doc/utils/pandoc.html)
- [doc/utils/requirements.txt](doc/utils/requirements.txt)
- [doc/utils/sphinx-config/_extra/Packages_list.html](doc/utils/sphinx-config/_extra/Packages_list.html)
- [doc/utils/sphinx-config/_extra/robots.txt](doc/utils/sphinx-config/_extra/robots.txt)
- [doc/utils/sphinx-config/_static/css/lammps.css](doc/utils/sphinx-config/_static/css/lammps.css)
- [doc/utils/sphinx-config/_themes/lammps_theme/__init__.py](doc/utils/sphinx-config/_themes/lammps_theme/__init__.py)
- [doc/utils/sphinx-config/_themes/lammps_theme/breadcrumbs.html](doc/utils/sphinx-config/_themes/lammps_theme/breadcrumbs.html)
- [doc/utils/sphinx-config/_themes/lammps_theme/footer.html](doc/utils/sphinx-config/_themes/lammps_theme/footer.html)
- [doc/utils/sphinx-config/_themes/lammps_theme/google_search.html](doc/utils/sphinx-config/_themes/lammps_theme/google_search.html)
- [doc/utils/sphinx-config/_themes/lammps_theme/layout.html](doc/utils/sphinx-config/_themes/lammps_theme/layout.html)
- [doc/utils/sphinx-config/_themes/lammps_theme/local_search.html](doc/utils/sphinx-config/_themes/lammps_theme/local_search.html)
- [doc/utils/sphinx-config/_themes/lammps_theme/locale/en/LC_MESSAGES/sphinx.mo](doc/utils/sphinx-config/_themes/lammps_theme/locale/en/LC_MESSAGES/sphinx.mo)
- [doc/utils/sphinx-config/_themes/lammps_theme/locale/en/LC_MESSAGES/sphinx.po](doc/utils/sphinx-config/_themes/lammps_theme/locale/en/LC_MESSAGES/sphinx.po)
- [doc/utils/sphinx-config/_themes/lammps_theme/static/css/badge_only.css](doc/utils/sphinx-config/_themes/lammps_theme/static/css/badge_only.css)
- [doc/utils/sphinx-config/_themes/lammps_theme/static/css/theme.css](doc/utils/sphinx-config/_themes/lammps_theme/static/css/theme.css)
- [doc/utils/sphinx-config/_themes/lammps_theme/theme.conf](doc/utils/sphinx-config/_themes/lammps_theme/theme.conf)
- [doc/utils/sphinx-config/_themes/lammps_theme/versions.html](doc/utils/sphinx-config/_themes/lammps_theme/versions.html)
- [doc/utils/sphinx-config/conf.py.in](doc/utils/sphinx-config/conf.py.in)
- [examples/plugins/LAMMPSInterfaceCXX.cmake](examples/plugins/LAMMPSInterfaceCXX.cmake)
- [src/.gitignore](src/.gitignore)
- [src/Depend.sh](src/Depend.sh)
- [src/KOKKOS/Install.sh](src/KOKKOS/Install.sh)
- [src/Make.sh](src/Make.sh)
- [src/Makefile](src/Makefile)
- [src/PLUGIN/plugin.cpp](src/PLUGIN/plugin.cpp)
- [src/PLUGIN/plugin.h](src/PLUGIN/plugin.h)
- [src/Purge.list](src/Purge.list)
- [src/REAXFF/compute_spec_atom.h](src/REAXFF/compute_spec_atom.h)
- [src/REAXFF/fix_qeq_reaxff.h](src/REAXFF/fix_qeq_reaxff.h)
- [src/REAXFF/fix_reaxff_bonds.cpp](src/REAXFF/fix_reaxff_bonds.cpp)
- [src/REAXFF/fix_reaxff_bonds.h](src/REAXFF/fix_reaxff_bonds.h)
- [src/REAXFF/fix_reaxff_species.cpp](src/REAXFF/fix_reaxff_species.cpp)
- [src/REAXFF/fix_reaxff_species.h](src/REAXFF/fix_reaxff_species.h)
- [src/REAXFF/pair_reaxff.h](src/REAXFF/pair_reaxff.h)
- [src/creator_registry.cpp](src/creator_registry.cpp)
- [src/fix_store_atom.cpp](src/fix_store_atom.cpp)
- [src/fix_store_global.cpp](src/fix_store_global.cpp)
- [src/platform.cpp](src/platform.cpp)
- [src/platform.h](src/platform.h)
- [tools/json/README.md](tools/json/README.md)
- [tools/json/color-schema.json](tools/json/color-schema.json)
- [tools/json/dump-molecules-schema.json](tools/json/dump-molecules-schema.json)
- [tools/json/reformat-json.cpp](tools/json/reformat-json.cpp)
- [tools/offline/README.md](tools/offline/README.md)
- [tools/offline/init_caches.sh](tools/offline/init_caches.sh)
- [tools/offline/scripts/init_git_cache.sh](tools/offline/scripts/init_git_cache.sh)
- [tools/offline/scripts/init_http_cache.sh](tools/offline/scripts/init_http_cache.sh)
- [tools/offline/scripts/init_pip_cache.sh](tools/offline/scripts/init_pip_cache.sh)
- [tools/offline/scripts/use_git_cache.sh](tools/offline/scripts/use_git_cache.sh)
- [tools/offline/scripts/use_http_cache.sh](tools/offline/scripts/use_http_cache.sh)
- [tools/offline/scripts/use_pip_cache.sh](tools/offline/scripts/use_pip_cache.sh)
- [tools/offline/use_caches.sh](tools/offline/use_caches.sh)
- [tools/singularity/README.md](tools/singularity/README.md)
- [unittest/utils/test_platform.cpp](unittest/utils/test_platform.cpp)

</details>



This section provides a high-level overview of the resources and systems available for extending and maintaining LAMMPS. The codebase is designed with a modular architecture that allows developers to add new features—such as interatomic potentials, time integrators, or diagnostic computations—without modifying the core simulation engine.

### System Overview and Abstraction
LAMMPS utilizes a "Pointers" base class pattern to provide components with access to global simulation state and utility objects [src/REAXFF/fix_reaxff_species.h:50-51](). To maintain portability across different operating systems (Linux, Windows, macOS), the codebase provides a `platform` namespace that abstracts system-level functionality like high-resolution timers, file I/O compression, and directory handling [src/platform.cpp:13-16]().

The following diagram illustrates the relationship between the core developer-facing systems and the underlying code entities.

**Developer System Map**
```mermaid
graph TD
    subgraph "Extension Space"
        [Styles] --> |"Inherit"| [BaseClasses]
        [Plugins] --> |"DSO Loading"| [PLUGIN_Package]
    end

    subgraph "Core Infrastructure"
        [PointersClass] --> |"Provides Access"| [LAMMPS_Instance]
        [PlatformNS] --> |"Abstractions"| [SystemOS]
    end

    subgraph "Documentation & Metadata"
        [Sphinx] --> |"Parses"| [RST_Files]
        [Doxygen] --> |"Parses"| [Header_Files]
    end

    [BaseClasses] --> [src/fix.h]
    [PLUGIN_Package] --> [src/PLUGIN/plugin.cpp]
    [PlatformNS] --> [src/platform.cpp]
    [RST_Files] --> [doc/src/*.rst]
```
Sources: [src/platform.cpp:13-16](), [src/PLUGIN/plugin.cpp:1-10](), [doc/Makefile:10-15]()

---

### Extending LAMMPS
LAMMPS is extended primarily through the addition of new **Styles**. A style is a C++ class that inherits from a specific base class (e.g., `Pair`, `Fix`, `Compute`) and implements a set of required virtual functions.

#### Style Registration and Plugins
Styles are typically integrated into the executable at compile-time using a registration macro, which adds them to the `CreatorRegistry`. For developers who need to add functionality without recompiling the entire LAMMPS binary, the **Plugin System** allows for dynamic loading of styles from shared objects (DSO) at runtime via the `plugin` command [src/PLUGIN/plugin.cpp:1-50]().

For details on implementing new styles, coding standards, and using the plugin infrastructure, see **[Adding New Styles and Plugins](#12.1)**.

| Feature | Implementation | Source |
| :--- | :--- | :--- |
| **New Pair Style** | Inherit from `Pair` class | `src/pair.h` |
| **New Fix** | Inherit from `Fix` class | `src/fix.h` |
| **Dynamic Loading** | `plugin` command / `LoadLib` | [src/PLUGIN/plugin.cpp]() |
| **API Changes** | Follow `Developer_updating` guide | `doc/src/Developer_updating.rst` |

Sources: [src/Makefile:27-32](), [src/PLUGIN/plugin.cpp:37-50]()

---

### Documentation System
The LAMMPS manual is generated using **Sphinx**, which processes reStructuredText (RST) files located in the `doc/src` directory [doc/Makefile:10-11](). The system is highly customized to handle the large number of styles in LAMMPS, including automated style-list checking and a custom theme [doc/utils/sphinx-config/conf.py.in:49-63]().

#### Build Pipeline
1.  **Doxygen**: Extracts API documentation from C++ header files to generate XML [doc/Makefile:105-119]().
2.  **Sphinx**: Combines RST files with Doxygen XML (via Breathe) to produce HTML, PDF, or EPub formats [doc/utils/sphinx-config/conf.py.in:59-63]().
3.  **Maintenance**: Includes tools for spell-checking and anchor validation [doc/Makefile:72-80]().

For details on how to build the manual, contribute new documentation, and use the custom Sphinx extensions, see **[Documentation System](#12.2)**.

**Documentation Data Flow**
```mermaid
graph LR
    [C++_Headers] --> |"Doxygen"| [XML_Files]
    [RST_Sources] --> |"Sphinx-build"| [HTML/PDF]
    [XML_Files] --> |"Breathe"| [Sphinx-build]
    [conf.py.in] --> |"CMake/Sed"| [conf.py]
    [conf.py] --> [Sphinx-build]
```
Sources: [doc/Makefile:96-105](), [doc/utils/sphinx-config/conf.py.in:49-63]()

---

### Platform and Utility Abstractions
To ensure code remains maintainable, developers should use the provided abstractions in `platform.cpp` and `utils.cpp` rather than calling OS-specific APIs directly.

*   **Compression**: The `platform::compressed_write` and `compressed_read` functions handle on-the-fly compression (gzip, bzip2, zstd, etc.) by piping to system commands [src/platform.cpp:85-107]().
*   **Time**: `platform::walltime()` and `platform::cputime()` provide portable high-resolution timing [src/platform.cpp:144-185]().
*   **Error Handling**: The `Error` class (accessible via `error->all()` or `error->one()`) should be used for all fatal exceptions and warnings to ensure proper MPI synchronization during shutdown [src/REAXFF/fix_reaxff_species.cpp:103-107]().

Sources: [src/platform.cpp:13-16](), [src/platform.cpp:85-107](), [src/REAXFF/fix_reaxff_species.cpp:75-76]()

---