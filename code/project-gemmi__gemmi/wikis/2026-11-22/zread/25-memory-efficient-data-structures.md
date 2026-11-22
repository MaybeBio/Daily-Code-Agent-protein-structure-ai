

Gemmi employs a sophisticated approach to memory management that prioritizes both performance and efficiency when handling large-scale crystallographic and molecular data. The library's data structures are meticulously designed to minimize memory overhead while maintaining rapid access patterns essential for scientific computing workflows.

## Core Memory Design Philosophy

The fundamental principle guiding Gemmi's memory architecture is **contiguous storage with minimal indirection**. Rather than relying heavily on pointer-based structures, Gemmi favors flat arrays and compact representations that leverage cache locality and reduce memory fragmentation.

### Span-Based Memory Management

At the heart of Gemmi's memory-efficient approach lies the custom `Span` implementation [span.hpp](include/gemmi/span.hpp#L19-L91), which provides a lightweight view into contiguous memory regions without ownership semantics. This design enables zero-cost abstractions for array access while maintaining flexibility:

```cpp
template<typename Item> struct Span {
  iterator begin_;
  std::size_t size_;
  // Minimal overhead: just pointer + size
};
```

The `Span` class serves as the foundation for memory views throughout the library, offering constant-time access with minimal memory footprint. For mutable operations, `MutableVectorSpan` extends this concept [span.hpp](include/gemmi/span.hpp#L94-L134) to provide insertion and deletion capabilities while maintaining the underlying vector's contiguity.

## Specialized Data Structures

### Compact Molecular Representation

Gemmi's molecular structures utilize carefully optimized layouts that balance memory efficiency with access patterns. The `SmallStructure` class [small.hpp](include/gemmi/small.hpp#L38-L82) exemplifies this approach with its flat `Site` representation:

```cpp
struct Site {
  std::string label;        // 24 bytes (typical SSO)
  std::string type_symbol;  // 24 bytes (typical SSO)
  Fractional fract;         // 24 bytes (3 doubles)
  double occ = 1.0;         // 8 bytes
  double u_iso = 0.;        // 8 bytes
  SMat33<double> aniso;     // 48 bytes (6 doubles)
  int disorder_group = 0;   // 4 bytes
  Element element = El::X;  // 1 byte + padding
  signed char charge = 0;   // 1 byte
  // Total: ~144 bytes per atom
};
```

This structure achieves memory efficiency through **string small object optimization (SSO)** for short strings and careful member ordering to minimize padding.

### Grid Data Optimization

For 3D grid data used in electron density maps and reciprocal space calculations, Gemmi implements highly optimized storage strategies [grid.hpp](include/gemmi/grid.hpp#L1-L150). The grid system employs:

- **Axis order optimization** with configurable XYZ/ZYX layouts for different FFT algorithms
- **Symmetry-aware grid sizing** that ensures compatibility with space group operations while minimizing memory usage
- **Template-based type flexibility** supporting both real and complex data types without runtime overhead

The `good_grid_size` function [grid.hpp](include/gemmi/grid.hpp#L78-L114) demonstrates sophisticated memory optimization by calculating optimal grid dimensions that balance computational efficiency with minimal memory allocation.

## Iterator Patterns for Memory Efficiency

Gemmi implements advanced iterator patterns that avoid unnecessary memory allocations and provide efficient traversal mechanisms [iterator.hpp](include/gemmi/iterator.hpp#L25-L95):

### Stride Iterators

The `StrideIter` enables memory-efficient access to regularly spaced elements without creating intermediate containers:

```cpp
template<typename Value>
class StrideIterPolicy {
  Value* cur_;
  std::size_t offset_;
  unsigned stride_;
  // Enables O(1) access to every nth element
};
```

### Indirect Iterators

For sparse data access patterns, `IndirectIter` provides virtual indexing without materializing the full dataset:

```cpp
template<typename Redirect, typename Value>
class IndirectIterPolicy {
  Redirect* redir_;
  std::vector<int>::const_iterator cur_;
  // Accesses elements through indirection table
};
```

## Memory Allocation Strategies

### Vector-Based Storage

Gemmi consistently uses `std::vector` as the primary container due to its **contiguous memory allocation** and predictable performance characteristics. The library avoids custom allocators in favor of standard library implementations that benefit from platform-specific optimizations.

### Small Object Optimization

Many Gemmi structures employ small object optimization techniques, particularly for string storage. The `Site` structure's string members benefit from modern C++ library implementations that use stack storage for short strings, avoiding heap allocation for typical atomic labels and type symbols.

## Performance Considerations

### Cache Locality

The flat array design ensures excellent cache locality, critical for performance when processing large molecular structures. Contiguous memory access patterns minimize cache misses and maximize memory bandwidth utilization.

### Memory Bandwidth Optimization

Gemmi's data structures are designed to minimize memory bandwidth requirements through:

- **Structure of Arrays (SoA)** layouts where beneficial for SIMD operations
- **Compact data types** using the smallest sufficient precision (e.g., `float` vs `double` where appropriate)
- **Alignment-aware design** ensuring natural alignment for vectorized operations

## Integration with High-Performance Computing

The memory-efficient design seamlessly integrates with Gemmi's parallel processing capabilities. The contiguous storage patterns enable efficient parallelization without memory contention, while the lightweight iterator patterns facilitate thread-safe operations on shared data structures.

For developers working with large-scale crystallographic datasets, these memory-efficient patterns provide the foundation for scalable applications that can handle gigabyte-scale molecular structures without excessive memory overhead.

---

**Next Steps**: Explore [Parallel Processing Strategies](26-parallel-processing-strategies) to understand how these memory-efficient patterns enable high-performance parallel computing, or examine [High-Performance Computing Considerations](24-high-performance-computing-considerations) for broader optimization strategies.