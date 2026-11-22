

Gemmi is designed with performance as a core architectural principle, implementing numerous optimizations for high-throughput crystallographic computing applications. The library employs systematic benchmarking, algorithmic optimizations, and memory-efficient data structures to achieve exceptional performance characteristics.

## Performance Benchmarking Framework

Gemmi maintains a comprehensive benchmarking suite that validates and measures performance-critical operations across different domains. The benchmarks use Google Benchmark library and provide insights into algorithmic efficiency and optimization opportunities.

The benchmarking framework covers several key performance areas:

- **Element lookup operations**: Testing `gemmi::find_element()` performance across different element types [benchmarks/elem.cpp](benchmarks/elem.cpp#L12-L16)
- **Modulo arithmetic**: Comparing different implementations of positive modulo operations [benchmarks/mod.cpp](benchmarks/mod.cpp#L14-L38)
- **Symmetry operations**: Measuring space group parsing and generator performance [benchmarks/sym.cpp](benchmarks/sym.cpp#L29-L69)

Performance results demonstrate significant variations based on input characteristics. For element lookup, common elements (C, N, O) achieve 11-16 ns per operation, while heavy elements require 332 ns, and Cromer-Liberman calculations take approximately 81 μs [benchmarks/elem.cpp](benchmarks/elem.cpp#L61-L65).

## Algorithmic Optimizations

### Modulo Arithmetic Optimization

The library extensively benchmarks different modulo implementations to determine the most efficient approach for positive results. Five different algorithms were tested:

```cpp
// Optimized implementation (fastest at 11ns)
static int positive_modulo5(int i) {
  if (i >= n)
    return i % n;
  if (i < 0)
    return ((i+1) % n) + (n - 1);
  return i;
}
```

The benchmark results show conditional logic outperforming mathematical transformations [benchmarks/mod.cpp](benchmarks/mod.cpp#L32-L38), with the fastest implementation achieving 11 ns compared to 32 ns for the naive approach [benchmarks/mod.cpp](benchmarks/mod.cpp#L65-L69).

### Grid Size Optimization

For FFT operations and reciprocal space calculations, Gemmi implements sophisticated grid size optimization algorithms that ensure efficient factorization for numerical methods:

```cpp
inline bool has_small_factorization(int n) {
  while (n % 2 == 0)
    n /= 2;
  for (int k : {3, 5})
    while (n % k == 0)
      n /= k;
  return n == 1 || n == -1;
}
```

This optimization ensures grid dimensions have prime factorizations of only 2, 3, and 5, which significantly improves FFT performance and numerical stability [include/gemmi/grid.hpp](include/gemmi/grid.hpp#L45-L52).

## Memory-Efficient Data Structures

### Compact Vector Representations

Gemmi uses template-based vector classes that minimize memory overhead while maintaining computational efficiency. The `Vec3_` template provides optimized 3D vector operations with minimal memory footprint:

```cpp
template <typename Real>
struct Vec3_ {
  Real x, y, z;
  // Inline operations for maximum performance
  Vec3_ operator+(const Vec3_& o) const { return {x+o.x, y+o.y, z+o.z}; }
  Real dot(const Vec3_& o) const { return x*o.x + y*o.y + z*o.z; }
};
```

This design enables efficient vectorized operations while maintaining cache-friendly memory access patterns [include/gemmi/math.hpp](include/gemmi/math.hpp#L58-L100).

### Axis Order Optimization

The grid system supports different memory layouts optimized for specific computational patterns. The `AxisOrder` enumeration allows selection between XYZ (fast X, slow Z) and ZYX (fast Z, slow X) layouts to optimize for different access patterns:

```cpp
enum class AxisOrder : unsigned char {
  XYZ,  // default, fast X (H in reciprocal space), slow Z (L)
  ZYX   // fast Z (L), may not be fully supported everywhere
};
```

This flexibility enables optimization for different computational kernels and memory access patterns [include/gemmi/grid.hpp](include/gemmi/grid.hpp#L24-L28).

## Mathematical Constant Optimization

Gemmi precomputes and caches frequently used mathematical constants as `constexpr` values to eliminate runtime computation overhead:

```cpp
constexpr double pi() { return 3.1415926535897932384626433832795029; }
constexpr double hc() { return 12398.4197386209; }  // Energy-wavelength conversion
constexpr double bohrradius() { return 0.529177210903; }
constexpr double u_to_b() { return 8 * pi() * pi(); }  // ADP conversion
```

These optimizations eliminate repeated calculations in performance-critical loops [include/gemmi/math.hpp](include/gemmi/math.hpp#L16-L29).

## Computational Intensive Operations

### Scattering Factor Calculations

The Cromer-Liberman method for atomic scattering factor calculations represents one of the most computationally intensive operations. Benchmarks show this operation requires approximately 81 μs per call, making it a primary target for optimization in high-throughput applications [benchmarks/elem.cpp](benchmarks/elem.cpp#L42-L47).

### Eigenvalue Computations

The library implements optimized 3x3 eigenvalue decomposition algorithms using the symmetric tridiagonal reduction method (tred2) and QL algorithm (tql2). These implementations are specifically optimized for the 3x3 case common in crystallographic applications [src/eig3.cpp](src/eig3.cpp#L13-L120).

## Performance Considerations for Different Use Cases

### High-Throughput Processing

For batch processing of large datasets, Gemmi's performance characteristics enable processing of thousands of structures efficiently. The optimized element lookup and symmetry operations provide sub-microsecond performance for individual operations, scaling linearly with dataset size.

### Real-time Applications

For interactive applications requiring sub-second response times, the library's optimized grid operations and mathematical functions provide the necessary performance ceiling. The axis order selection and grid size optimization algorithms enable efficient real-time visualization and analysis.

### Large-Scale Computing

In distributed computing environments, Gemmi's memory-efficient data structures minimize memory bandwidth requirements, while the optimized algorithms reduce CPU utilization. The library's design supports efficient parallelization strategies for cluster computing applications.

> [!TIP]
> The benchmarking results show that algorithmic choice significantly impacts performance - the modulo operation benchmark demonstrates a 3x performance difference between implementations

> [!TIP]
> Grid size optimization with small prime factorizations (2, 3, 5) is crucial for FFT performance and should be considered in any custom grid implementations

For deeper understanding of memory optimization strategies, see [Memory-Efficient Data Structures](25-memory-efficient-data-structures). For parallel processing techniques, refer to [Parallel Processing Strategies](26-parallel-processing-strategies).