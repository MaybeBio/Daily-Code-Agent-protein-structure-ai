

Foldseek offers multiple installation methods to suit different use cases, platforms, and user preferences. Whether you're a bioinformatician looking for quick access to protein structure comparison tools or a developer wanting to integrate Foldseek into your workflow, there's an installation option that fits your needs. Let's explore the various ways to get Foldseek up and running on your system.

## Precompiled Binaries (Recommended for Most Users)

For users who want to get started quickly, precompiled binaries are the simplest and most straightforward installation method. These are optimized for different CPU architectures and include GPU support for accelerated performance.

### Linux Installation

Linux users have three precompiled binary options depending on their system architecture and GPU capabilities:

**Linux AVX2 Build** (for modern Intel/AMD processors):
```bash
# Check if your CPU supports AVX2
cat /proc/cpuinfo | grep avx2

# Download and install
wget https://mmseqs.com/foldseek/foldseek-linux-avx2.tar.gz
tar xvzf foldseek-linux-avx2.tar.gz
export PATH=$(pwd)/foldseek/bin/:$PATH
```

**Linux ARM64 Build** (for ARM-based systems like Raspberry Pi or ARM servers):
```bash
wget https://mmseqs.com/foldseek/foldseek-linux-arm64.tar.gz
tar xvzf foldseek-linux-arm64.tar.gz
export PATH=$(pwd)/foldseek/bin/:$PATH
```

**Linux GPU Build** (for NVIDIA GPU acceleration):
```bash
# Requires glibc >= 2.17 and nvidia driver >=525.60.13
wget https://mmseqs.com/foldseek/foldseek-linux-gpu.tar.gz
tar xvfz foldseek-linux-gpu.tar.gz
export PATH=$(pwd)/foldseek/bin/:$PATH
```
Sources: [README.md#L71-L78](README.md#L71-L78)

> [!TIP]
> The GPU build requires an NVIDIA GPU of the Ampere generation or newer for full speed, but also works at reduced speed for Turing-generation GPUs. Make sure you have the appropriate NVIDIA drivers installed before using the GPU version.

### macOS Installation

For macOS users, there's a universal binary that works on both Intel (x86_64) and Apple Silicon (ARM64) Macs:

```bash
wget https://mmseqs.com/foldseek/foldseek-osx-universal.tar.gz
tar xvzf foldseek-osx-universal.tar.gz
export PATH=$(pwd)/foldseek/bin/:$PATH
```
Sources: [README.md#L80-L81](README.md#L80-L81)

### Verifying Your Installation

After installing Foldseek, you can verify it's working correctly by running:

```bash
foldseek version
```

This should display the version information and confirm that the binary is properly installed and accessible in your PATH.

## Conda Installation (Package Manager)

For users who prefer package managers or need to manage dependencies in a conda environment, Foldseek is available through BioConda:

```bash
conda install -c conda-forge -c bioconda foldseek
```

This method works on both Linux and macOS and automatically handles dependencies. It's particularly useful if you're building a bioinformatics pipeline with multiple tools.
Sources: [README.md#L83-L84](README.md#L83-L84)

> [!TIP]
> The conda package may not always have the latest version immediately after release. If you need the newest features or bug fixes, consider using the precompiled binaries or building from source.

## Docker Containers (Reproducible Environments)

Docker containers provide a reproducible environment that works consistently across different systems. Foldseek offers both CPU and GPU-enabled Docker images.

### CPU-based Docker Image

```bash
docker pull steineggerlab/foldseek
docker run -it steineggerlab/foldseek foldseek version
```

### GPU-enabled Docker Image

For GPU acceleration, use the GPU-enabled Docker image:

```bash
docker pull steineggerlab/foldseek:gpu
docker run --gpus all -it steineggerlab/foldseek:gpu foldseek version
```
Sources: [Dockerfile](Dockerfile)

### Using Docker with Local Files

To use Foldseek with your local files, mount them as volumes:

```bash
docker run --rm -v $(pwd)/data:/data -v $(pwd)/results:/results steineggerlab/foldseek \
  foldseek easy-search /data/query.pdb /data/target.pdb /results/alignment.m8 /tmp
```

For GPU-enabled containers:

```bash
docker run --rm --gpus all -v $(pwd)/data:/data -v $(pwd)/results:/results steineggerlab/foldseek:gpu \
  foldseek easy-search /data/query.pdb /data/target.pdb /results/alignment.m8 /tmp --gpu 1
```

The Docker images are built with multi-architecture support, so they work on both x86_64 and ARM64 systems. The GPU version includes CUDA support for NVIDIA GPUs.
Sources: [Dockerfile#L1-L84](Dockerfile#L1-L84)

## Building from Source (Advanced Users)

For developers or users who need to customize Foldseek or want to run it on unsupported platforms, building from source is the most flexible option.

### System Requirements

Before building from source, ensure you have the following dependencies installed:

**For Linux:**
- CMake (version 3.15 or higher)
- GCC or Clang compiler
- Git
- Rust (version 1.68.0 or higher)
- zlib1g-dev, libbz2-dev
- Optional: CUDA toolkit (for GPU support)

**For macOS:**
- Xcode Command Line Tools
- CMake (version 3.15 or higher)
- Rust (version 1.68.0 or higher)

### Linux Build Instructions

1. **Clone the repository:**
```bash
git clone https://github.com/steineggerlab/foldseek.git
cd foldseek
```

2. **Create a build directory:**
```bash
mkdir build && cd build
```

3. **Configure with CMake:**
```bash
# For standard AVX2 build
cmake -DHAVE_AVX2=1 -DHAVE_TESTS=0 -DCMAKE_BUILD_TYPE=Release ..

# For GPU build (requires CUDA)
cmake -DHAVE_AVX2=1 -DHAVE_TESTS=0 -DENABLE_CUDA=1 -DCMAKE_BUILD_TYPE=Release ..

# For SSE4.1 build (for older CPUs)
cmake -DHAVE_SSE4_1=1 -DHAVE_TESTS=0 -DCMAKE_BUILD_TYPE=Release ..
```

4. **Build Foldseek:**
```bash
make -j$(nproc)
```

5. **Install (optional):**
```bash
sudo make install
```
Sources: [CMakeLists.txt#L1-L147](CMakeLists.txt#L1-L147)

### macOS Build Instructions

For macOS, the project provides a dedicated build script that handles the complexity of building universal binaries:

```bash
# Clone the repository
git clone https://github.com/steineggerlab/foldseek.git
cd foldseek

# Run the build script
./util/build_osx.sh . build

# The binary will be in build/foldseek
```

This script builds both x86_64 and ARM64 versions and combines them into a universal binary using the `lipo` tool. It also handles building OpenMP from source, which is required for static linking on macOS.
Sources: [util/build_osx.sh#L1-L119](util/build_osx.sh#L1-L119)

### Build Configuration Options

When building from source, you can customize the build with various CMake options:

| Option | Description | Default |
|--------|-------------|---------|
| `HAVE_AVX2` | Enable AVX2 instruction set optimizations | OFF |
| `HAVE_SSE4_1` | Enable SSE4.1 instruction set optimizations | OFF |
| `HAVE_ARM8` | Enable ARM NEON optimizations (ARM64) | OFF |
| `ENABLE_CUDA` | Enable CUDA support for GPU acceleration | OFF |
| `ENABLE_PROSTT5` | Enable ProstT5 protein language model support | ON |
| `FORCE_STATIC_DEPS` | Force static linking of dependencies | OFF |
| `CMAKE_BUILD_TYPE` | Build type (Debug, Release, etc.) | Release |

Example with custom options:
```bash
cmake -DHAVE_AVX2=1 -DENABLE_PROSTT5=1 -DCMAKE_BUILD_TYPE=Release ..
```
Sources: [CMakeLists.txt#L9-L12](CMakeLists.txt#L9-L12)

## Memory Requirements

Foldseek's memory usage depends on the database size and configuration. For optimal performance, consider these options:

1. **With Cα info (default)**: Requires approximately `(6 bytes Cα + 1 3Di byte + 1 AA byte) * (database residues)`. For example, the 54M AlphaFold DB entries require about 151GB of RAM.

2. **Without Cα info**: By disabling `--sort-by-structure-bits 0`, RAM requirement reduces significantly (e.g., to 35GB for AlphaFold DB). This alters hit rankings and final scores but not E-values.

3. **Single query searches**: Use `--prefilter-mode 1`, which isn't memory-limited and computes all optimal ungapped alignments. This option optimally utilizes Foldseek's multithreading capabilities for single queries and supports GPU acceleration.
Sources: [README.md#L91-L101](README.md#L91-L101)

## Choosing the Right Installation Method

To help you decide which installation method is best for your needs, here's a comparison of the different options:

| Installation Method | Best For | Pros | Cons |
|---------------------|----------|------|------|
| **Precompiled Binaries** | Most users, quick start | Easiest to install, optimized for performance, no compilation required | Limited to supported architectures, may not have latest features |
| **Conda** | Bioinformatics pipelines, dependency management | Handles dependencies automatically, works in conda environments | May lag behind latest releases, larger download size |
| **Docker** | Reproducible environments, CI/CD | Consistent across systems, easy to scale, GPU support | Requires Docker knowledge, larger disk space usage |
| **Build from Source** | Developers, custom builds, unsupported platforms | Full control over features, can optimize for specific hardware | Complex setup, requires development tools, longer installation time |

## Troubleshooting Common Issues

### AVX2 Support Issues

If you're using an older CPU that doesn't support AVX2, you may encounter errors when trying to run the AVX2 binary. In this case:

1. Check your CPU capabilities:
```bash
cat /proc/cpuinfo | grep avx2
```

2. If AVX2 is not supported, use the SSE4.1 build or build from source with SSE4.1 support.

### GPU Issues

If you're having trouble with GPU acceleration:

1. Verify your NVIDIA driver version:
```bash
nvidia-smi
```

2. Ensure you have the CUDA toolkit installed (if building from source).

3. Check GPU visibility:
```bash
CUDA_VISIBLE_DEVICES=0 foldseek easy-search query.pdb target.pdb result.m8 tmp --gpu 1
```

### Memory Issues

If you encounter out-of-memory errors:

1. Reduce memory usage by disabling Cα info:
```bash
foldseek easy-search query.pdb target.pdb result.m8 tmp --sort-by-structure-bits 0
```

2. Use single query mode for large databases:
```bash
foldseek easy-search query.pdb target.pdb result.m8 tmp --prefilter-mode 1
```

## Next Steps

After successfully installing Foldseek, you're ready to start exploring protein structure comparisons. Check out our [Structure Search Basics](4-structure-search-basics) tutorial to learn how to perform your first protein structure search, or explore the [Working with Structure Databases](5-working-with-structure-databases) guide to understand how to work with pre-built databases like AlphaFold DB and PDB.

Remember to refer to the [Foldseek wiki](https://github.com/steineggerlab/foldseek/wiki) for more detailed documentation and the [MMseqs2 wiki](https://github.com/soedinglab/MMseqs2/wiki) for information about modules shared between Foldseek and MMseqs2.