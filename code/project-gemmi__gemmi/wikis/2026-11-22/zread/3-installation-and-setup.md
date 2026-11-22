

This guide covers the complete installation process for Gemmi, a comprehensive C++ library for structural biology. Whether you need the C++ library, Python bindings, command-line tools, or WebAssembly compilation, this documentation provides step-by-step instructions for all supported platforms and use cases.

## Installation Overview

Gemmi offers multiple installation methods depending on your needs:

| Installation Method | Use Case | Dependencies | Complexity |
|-------------------|----------|--------------|------------|
| **PyPI (pip)** | Python development | Python 3.8+, C++ compiler | Low |
| **CMake** | C++ development | CMake 3.15+, C++ compiler | Medium |
| **Conda** | Scientific environments | Conda package manager | Low |
| **Binary distributions** | Quick deployment | Platform-specific | Very Low |
| **WebAssembly** | Browser applications | Emscripten | High |

## C++ Library Installation

### Header-Only Usage (Limited)

For basic CIF parsing operations, Gemmi can be used as a header-only library:

```bash
git clone https://github.com/project-gemmi/gemmi.git
c++ -Igemmi/include -O2 my_program.cpp
```

> [!TIP]
> Header-only mode only supports CIF syntax parsing and similar basic operations. Full functionality requires building the complete library.

### CMake Integration

**Method 1: Install and Find Package**
```cmake
find_package(gemmi 0.7.0 CONFIG REQUIRED)
target_link_libraries(example PRIVATE gemmi::gemmi_cpp)
```

**Method 2: Git Submodule**
```cmake
add_subdirectory(gemmi EXCLUDE_FROM_ALL)
target_link_libraries(example PRIVATE gemmi::gemmi_cpp)
```

**Method 3: FetchContent**
```cmake
include(FetchContent)
FetchContent_Declare(
  gemmi
  GIT_REPOSITORY https://github.com/project-gemmi/gemmi.git
  GIT_TAG        ...
)
FetchContent_GetProperties(gemmi)
if (NOT gemmi_POPULATED)
  FetchContent_Populate(gemmi)
  add_subdirectory(${gemmi_SOURCE_DIR} ${gemmi_BINARY_DIR} EXCLUDE_FROM_ALL)
endif()
target_link_libraries(example PRIVATE gemmi::gemmi_cpp)
```

For header-only usage:
```cmake
target_link_libraries(example PRIVATE gemmi::headers)
```

### Compression Library Options

Gemmi supports multiple zlib implementations, configurable via CMake options:

| Option | Description | Performance |
|--------|-------------|-------------|
| `FETCH_ZLIB_NG` | Download and build zlib-ng statically | Fastest |
| `USE_ZLIB_NG` | Use system-installed zlib-ng | Fast |
| `INTERNAL_ZLIB` | Use bundled zlib subset | Good |
| Default | Use system zlib, fallback to internal | Standard |

**Windows Recommendation**: Use `-D FETCH_ZLIB_NG=ON` to avoid DLL dependencies.

## Python Module Installation

### From PyPI (Recommended)

```bash
pip install gemmi
```

Binary wheels are available for all supported Python versions (3.8+), eliminating compilation requirements. If no matching wheel is found, pip will compile from source automatically.

### Alternative Distribution Channels

**Conda:**
```bash
conda install -c conda-forge gemmi
```

**CCP4 Suite:** Gemmi is included in the CCP4 software distribution.

### Development Installation

**Direct from Git:**
```bash
pip install git+https://github.com/project-gemmi/gemmi.git
```

**Local Development:**
```bash
git clone https://github.com/project-gemmi/gemmi.git
cd gemmi
pip install .
```

**With Custom CMake Options:**
```bash
pip install . --config-settings="cmake.args=-DFETCH_ZLIB_NG=ON"
```

> [!TIP]
> When upgrading from an existing installation, use `pip install --upgrade` or uninstall the old version first with `pip uninstall gemmi`.

## Command-Line Program

### Binary Distributions

| Source | Platform | Notes |
|--------|----------|-------|
| **PyPI** | Cross-platform | `pip install gemmi-program` |
| **Conda-forge** | Cross-platform | `conda install -c conda-forge gemmi` |
| **CCP4 Suite** | Cross-platform | Included in CCP4 |
| **Linux Distros** | Various | Check package manager |
| **CI Artifacts** | Windows/Linux/Mac | Latest builds |

### Building from Source

**Basic Build:**
```bash
git clone https://github.com/project-gemmi/gemmi.git
cd gemmi
cmake .
make
```

**Program-Only Build (via pip):**
```bash
pip install git+https://github.com/project-gemmi/gemmi.git --config-settings=cmake.args=-DONLY_PROGRAM=ON
```

## Advanced Installation Options

### WebAssembly Compilation

Gemmi can be compiled to WebAssembly using Emscripten for browser-based applications. Two approaches are supported:

**1. Embind Bindings**
- Located in `wasm/` directory
- Exposes C++ classes directly to JavaScript
- Includes Structure and Mtz class bindings
- Example: `make -C wasm`

**2. C API Approach**
- Used in web tools repository
- Better performance for computationally intensive tasks
- Minimizes JS/WASM boundary crossings

### Fortran Bindings

Fortran 2003+ bindings are available but considered experimental:

```bash
cmake -D USE_FORTRAN=1 .
make
```

The bindings use ISO_C_BINDING and are built with Shroud. See the `fortran/` directory for examples and Makefile.

## Testing and Verification

### Python Tests
```bash
python3 -m unittest discover -v tests/
```

### Comprehensive Testing
```bash
./run-tests.sh
```

This script runs all test suites including:
- Python unit tests
- Documentation doctests
- Additional validation routines

## Project Structure

```
gemmi/
├── include/gemmi/          # C++ headers
├── src/                    # C++ source files  
├── python/                 # Python binding source
├── prog/                   # Command-line tools
├── examples/               # Usage examples
├── tests/                  # Test suite
├── docs/                   # Documentation source
├── wasm/                   # WebAssembly bindings
├── fortran/                # Fortran bindings
└── third_party/           # Dependencies
```

## Next Steps

After successful installation, you can:

- **Explore the library structure**: [Library Structure and Design Philosophy](5-library-structure-and-design-philosophy)
- **Learn command-line tools**: [Command Line Tools Introduction](4-command-line-tools-introduction)
- **Start with examples**: Check the `examples/` directory for practical usage patterns
- **Browse documentation**: Visit [http://gemmi.readthedocs.io/en/latest/](http://gemmi.readthedocs.io/en/latest/) for comprehensive API documentation

## Troubleshooting

**Common Issues:**

1. **Compilation fails on Windows**: Ensure you have Visual Studio with C++ support and use `-D FETCH_ZLIB_NG=ON`
2. **Python wheel not found**: Install a C++ compiler (GCC/Clang/MSVC) and ensure Python 3.8+
3. **CMake cannot find Gemmi**: Use `CONFIG` mode: `find_package(gemmi CONFIG REQUIRED)`
4. **Unicode filename issues**: Ensure filenames are UTF-8 encoded when passing to Gemmi functions

**Getting Help:**
- GitHub Issues: [project-gemmi/gemmi](https://github.com/project-gemmi/gemmi/issues)
- Documentation: [ReadTheDocs](http://gemmi.readthedocs.io/en/latest/)
- Web Tools: [project-gemmi.github.io/wasm](https://project-gemmi.github.io/wasm/)
