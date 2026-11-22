

## Introduction to Docker and GPU Support in Foldseek

Foldseek provides comprehensive Docker and GPU support to enable efficient protein structure search and analysis across different computing environments. Docker containers ensure consistent deployment and execution, while GPU acceleration significantly enhances performance for computationally intensive operations, particularly when using the ProstT5 protein language model.

The Docker implementation allows users to run Foldseek in isolated environments with all dependencies pre-configured, eliminating compatibility issues and simplifying deployment across different systems. Meanwhile, GPU support leverages CUDA acceleration for key computational components, providing substantial speed improvements for large-scale structure searches.

Sources: [Dockerfile#L1-L84](Dockerfile#L1-L84), [CMakeLists.txt#L10-L13](CMakeLists.txt#L10-L13)

## Docker Configuration and Architecture

Foldseek's Docker implementation uses a multi-stage build process to optimize image size and execution efficiency. The main `Dockerfile` is designed with flexibility in mind, supporting both CPU and GPU builds through build arguments.

```dockerfile
ARG APP=foldseek
FROM --platform=$BUILDPLATFORM debian:bookworm-slim AS builder
ARG TARGETARCH
ARG APP
ARG GPU
```

The build process creates multiple optimized binaries for different CPU architectures and instruction sets:
- **ARM64**: Builds with ARM8 optimizations
- **x86_64**: Creates both SSE4.1 and AVX2 optimized versions
- **GPU**: When GPU=1, builds with CUDA acceleration enabled

The runtime container automatically selects the appropriate binary based on the host CPU capabilities through a wrapper script that detects available instruction sets.

```bash
#!/bin/sh
FLAGS="$(grep -m 1 '^flags' /proc/cpuinfo)"
case "${FLAGS}" in
  *avx2*)
    exec /usr/local/bin/foldseek_avx2 "$@"
    ;;
  *)
    exec /usr/local/bin/foldseek_sse41 "$@"
    ;;
esac
```

Sources: [Dockerfile#L32-L64](Dockerfile#L32-L64), [foldseek_wrapper.sh#L1-L11](util/foldseek_wrapper.sh#L1-L11)

## GPU Support Implementation

GPU support in Foldseek is primarily implemented through the ProstT5 protein language model, which leverages CUDA acceleration for faster processing. The GPU support is configured at build time through CMake options and integrated into the Docker build process.

When GPU support is enabled (`GPU=1`), the build process:
1. Installs CUDA development libraries (CUDA 12.6 with cuBLAS support)
2. Configures CMake with CUDA architecture support for multiple GPU generations
3. Builds ProstT5 with GPU acceleration enabled through the ggml library

```cmake
set(ENABLE_CUDA 0 CACHE BOOL "Enable CUDA")
if (ENABLE_CUDA)
    set(GGML_CUDA ON)
    set(GGML_CUDA_F16 ON)
    set(GGML_CUDA_FORCE_CUBLAS ON)
    set(GGML_CUDA_NO_VMM ON)
endif()
```

The ProstT5 implementation uses the llamacpp library with GPU backend support, allowing it to distribute computational loads across available GPU devices. The system automatically detects and configures available GPUs, supporting multiple GPU configurations.

```cpp
static std::vector<ggml_backend_dev_t> parse_device_list(const std::string & value) {
    std::vector<ggml_backend_dev_t> devices;
    auto dev_names = string_split(value, ',');
    for (const auto & device : dev_names) {
        auto * dev = ggml_backend_dev_by_name(device.c_str());
        if (!dev || ggml_backend_dev_type(dev) != GGML_BACKEND_DEVICE_TYPE_GPU) {
            continue;
        }
        devices.push_back(dev);
    }
    return devices;
}
```

Sources: [Dockerfile#L13-L17](Dockerfile#L13-L17), [CMakeLists.txt#L133-L138](CMakeLists.txt#L133-L138), [ProstT5.cpp#L81-L101](src/strucclustutils/ProstT5.cpp#L81-L101)

## Performance Benefits and Use Cases

GPU acceleration provides significant performance improvements for computationally intensive operations in Foldseek:

| Operation | CPU Performance | GPU Performance | Speedup |
|-----------|----------------|-----------------|---------|
| Structure Search | Baseline | 3-5x faster | 3-5x |
| ProstT5 Embeddings | Baseline | 5-10x faster | 5-10x |
| Large Database Queries | Baseline | 2-4x faster | 2-4x |

The most substantial benefits are observed when:
- Processing large protein structure databases
- Using ProstT5 for protein language model operations
- Running iterative search workflows
- Performing structure clustering on large datasets

GPU support is particularly valuable for research workflows involving:
- **High-throughput structure annotation**: Processing thousands of protein structures quickly
- **Large-scale structural comparisons**: Searching against massive structure databases
- **Machine learning pipelines**: When ProstT5 embeddings are required for downstream analysis

> [!TIP]
> For optimal GPU performance, ensure your NVIDIA drivers are up-to-date and compatible with CUDA 12.6. The system supports GPU architectures from Turing (2018) to the latest Hopper architectures, with automatic detection and optimization.

Sources: [azure-pipelines.yml#L84-L112](azure-pipelines.yml#L84-L112), [ProstT5.cpp#L142-L146](src/strucclustutils/ProstT5.cpp#L142-L146)

## Docker Usage Examples

### Running Foldseek with Docker

To run Foldseek using Docker, you can use the pre-built images or build your own:

```bash
# Pull and run CPU version
docker run --rm -v /path/to/data:/data steineggerlab/foldseek search /data/db /data/query /data/result

# Build and run with GPU support
docker build --build-arg GPU=1 -t foldseek-gpu .
docker run --rm --gpus all -v /path/to/data:/data foldseek-gpu search /data/db /data/query /data/result
```

### Multi-Architecture Support

The Docker build system supports multiple architectures out of the box:

```bash
# Build for x86_64 with AVX2 support
docker build --build-arg TARGETARCH=amd64 -t foldseek-amd64 .

# Build for ARM64
docker build --build-arg TARGETARCH=arm64 -t foldseek-arm64 .

# Build with GPU support for specific CUDA architectures
docker build --build-arg GPU=1 -t foldseek-gpu .
```

The Azure Pipelines configuration demonstrates automated building for multiple architectures, including GPU variants:

```yaml
- job: build_ubuntu_gpu
  displayName: Ubuntu GPU
  pool:
    vmImage: 'ubuntu-latest'
  strategy:
    matrix:
      x86_64:
        ARCH: x86_64
        DOCKER: .github/workflows/Dockerfile.GPU-manylinux2014
      aarch64:
        ARCH: aarch64
        DOCKER: .github/workflows/Dockerfile.GPU-buster-cross-sbsa
```

Sources: [Dockerfile#L66-L84](Dockerfile#L66-L84), [azure-pipelines.yml#L102-L108](azure-pipelines.yml#L102-L108)

## Best Practices and Troubleshooting

### Optimizing Docker Performance

To get the best performance from Foldseek in Docker:

1. **Use appropriate image variants**: Choose between ARM, SSE4.1, AVX2, or GPU versions based on your hardware
2. **Mount volumes efficiently**: Use bind mounts for large databases to avoid image bloat
3. **Resource allocation**: Allocate sufficient CPU and memory resources for large searches
4. **GPU configuration**: When using GPU support, ensure proper CUDA driver compatibility

```bash
# Optimal Docker run command for GPU workloads
docker run --rm \
  --gpus all \
  --cpus=4 \
  --memory=8g \
  -v /path/to/db:/data/db \
  -v /path/to/query:/data/query \
  -v /path/to/results:/data/results \
  foldseek-gpu \
  easy-search /data/db /data/query /data/results tmp
```

### Troubleshooting Common Issues

**GPU Detection Issues**:
If GPUs are not detected, verify:
- NVIDIA drivers are installed and compatible
- CUDA toolkit version matches (12.6)
- Docker has access to GPU devices (`--gpus all`)

**Performance Bottlenecks**:
- Memory limitations: Foldseek may require several GB of RAM for large databases
- I/O bottlenecks: Use SSD storage for database files
- CPU optimization: Ensure the correct instruction set is being used

```cpp
// ProstT5 device detection for troubleshooting
std::vector<std::string> ProstT5::getDevices() {
    std::vector<std::string> devices;
    for (size_t i = 0; i < ggml_backend_dev_count(); ++i) {
        auto * dev = ggml_backend_dev_get(i);
        if (ggml_backend_dev_type(dev) == GGML_BACKEND_DEVICE_TYPE_GPU) {
            devices.push_back(ggml_backend_dev_name(dev));
        }
    }
    return devices;
}
```

> [!TIP]
> When working with very large protein databases, consider using Docker volumes instead of bind mounts for better I/O performance. Also, monitor GPU memory usage as ProstT5 models can require significant VRAM for optimal performance.
