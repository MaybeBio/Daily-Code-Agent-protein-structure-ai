

Gemmi provides a comprehensive framework for Fast Fourier Transform (FFT) operations and reciprocal space calculations, essential for crystallographic computing including structure factor calculations, electron density map generation, and reciprocal space data manipulation. The implementation leverages the high-performance PocketFFT library while providing crystallography-specific optimizations.

## Core Architecture

The FFT and reciprocal space functionality is built around three main template classes:

- **`Grid<T>`**: Real-space grid for density maps and volumetric data [grid.hpp](include/gemmi/grid.hpp)
- **`ReciprocalGrid<T>`**: Reciprocal space grid for structure factors and frequency domain data [recgrid.hpp](include/gemmi/recgrid.hpp)  
- **`FPhiGrid<T>`**: Specialized reciprocal grid for complex structure factors (amplitude and phase) [recgrid.hpp](include/gemmi/recgrid.hpp#L172)

### Grid Axis Ordering

Gemmi supports two axis ordering schemes with different performance characteristics:

```cpp
enum class AxisOrder : unsigned char {
  XYZ,  // Default: X (H) fast, Z (L) slow - CCP4 compatible
  ZYX   // Fast Z (L), may have limited support in some operations
};
```

The XYZ order corresponds to standard CCP4 map format where the first axis changes most rapidly [grid.hpp](include/gemmi/grid.hpp#L24-L28). This ordering is crucial for FFT performance and compatibility with external crystallographic software.

## Reciprocal Space Grid Operations

### Grid Initialization and Size Calculation

The `get_size_for_hkl()` function determines optimal grid dimensions based on data requirements and sampling rate:

```cpp
template<typename DataProxy>
std::array<int, 3> get_size_for_hkl(const DataProxy& data,
                                    std::array<int, 3> min_size,
                                    double sample_rate);
```

This function analyzes Miller indices in the input data to ensure the grid can accommodate all reflections [fourier.hpp](include/gemmi/fourier.hpp#L48-L74). The sampling rate parameter controls grid density relative to resolution, with higher values providing more detailed maps at increased computational cost.

### Symmetry-Aware Grid Population

The `get_f_phi_on_grid()` function populates reciprocal grids with structure factor data while respecting crystallographic symmetry:

```cpp
template<typename T, typename FPhi>
FPhiGrid<T> get_f_phi_on_grid(const FPhi& fphi,
                              std::array<int, 3> size, bool half_l,
                              AxisOrder axis_order=AxisOrder::XYZ);
```

Key features include:
- **Symmetry expansion**: Applies space group operations to generate symmetrically equivalent reflections [fourier.hpp](include/gemmi/fourier.hpp#L176-L197)
- **Friedel mate handling**: Automatically adds complex conjugates for non-centrosymmetric space groups [fourier.hpp](include/gemmi/fourier.hpp#L198-L199)
- **Half-grid optimization**: Supports Hermitian symmetry for memory efficiency [fourier.hpp](include/gemmi/fourier.hpp#L144-L145)

### Friedel Pair Management

For non-centrosymmetric data, Gemmi provides automatic Friedel mate generation:

```cpp
template<typename T>
void add_friedel_mates(ReciprocalGrid<T>& grid);
```

This function populates missing Friedel pairs using the relationship F(hkl) = F*(-h,-k,-l) [fourier.hpp](include/gemmi/fourier.hpp#L87-L129). The implementation handles both XYZ and ZYX axis orderings efficiently.

## FFT Transform Operations

### Forward Transform: Structure Factors to Maps

The core transformation from reciprocal to real space uses the `transform_f_phi_to_map()` function:

```cpp
template<typename T, typename FPhi>
Grid<T> transform_f_phi_to_map(const FPhi& fphi,
                               std::array<int, 3> size,
                               double sample_rate,
                               bool exact_size=false,
                               AxisOrder order=AxisOrder::XYZ);
```

This operation performs:
1. **Grid preparation**: Creates appropriately sized reciprocal grid [fourier.hpp](include/gemmi/fourier.hpp#L298-L302)
2. **Data population**: Places structure factors with symmetry consideration [fourier.hpp](include/gemmi/fourier.hpp#L170-L200)
3. **FFT execution**: Converts to real space using PocketFFT backend [fourier.hpp](include/gemmi/fourier.hpp#L238-L283)

> [!TIP]
> The implementation uses complex conjugation before FFT (line 245) to handle the crystallographic convention where structure factors represent Fourier coefficients of electron density. This ensures proper phase relationships in the resulting map.

### Inverse Transform: Maps to Structure Factors

The reverse transformation enables structure factor extraction from electron density:

```cpp
template<typename T>
FPhiGrid<T> transform_map_to_f_phi(const Grid<T>& map, bool half_l, bool use_scale=true);
```

Key aspects:
- **Real-to-complex FFT**: Efficiently handles Hermitian symmetry [fourier.hpp](include/gemmi/fourier.hpp#L333-L334)
- **Normalization**: Applies unit cell volume scaling for proper amplitude values [fourier.hpp](include/gemmi/fourier.hpp#L328)
- **Friedel pair reconstruction**: Completes reciprocal space for non-half grids [fourier.hpp](include/gemmi/fourier.hpp#L338-L350)

### Half-Grid Optimization

For centrosymmetric data or when memory efficiency is critical, Gemmi supports half-grid storage:

```cpp
bool half_l = false; // Stores only l>=0 in reciprocal grid
```

This optimization reduces memory usage by approximately 50% while maintaining full information content through Hermitian symmetry [recgrid.hpp](include/gemmi/recgrid.hpp#L22).

## Grid Size Optimization

### Factorization Constraints

FFT algorithms perform best with grid dimensions that factor into small primes (2, 3, 5). Gemmi provides automatic grid size optimization:

```cpp
inline bool has_small_factorization(int n);
inline int round_with_small_factorization(double exact, GridSizeRounding rounding);
```

These functions ensure grid dimensions are FFT-friendly while accommodating crystallographic symmetry requirements [grid.hpp](include/gemmi/grid.hpp#L45-L76).

### Symmetry-Aware Grid Sizing

The `good_grid_size()` function considers space group symmetry when determining optimal grid dimensions:

```cpp
inline std::array<int, 3> good_grid_size(std::array<double, 3> limit,
                                         GridSizeRounding rounding,
                                         const SpaceGroup* sg);
```

This ensures symmetry-related directions have compatible grid sizes, preventing artifacts in downstream calculations [grid.hpp](include/gemmi/grid.hpp#L78-L100).

## Advanced Features

### ASU Data Preparation

Reciprocal grids can extract asymmetric unit data for reflection file generation:

```cpp
template <typename R=T>
AsuData<R> prepare_asu_data(double dmin=0, double unblur=0,
                            bool with_000=false, bool with_sys_abs=false,
                            bool mott_bethe=false);
```

This function handles:
- **Resolution limiting**: Filters reflections by d-spacing [recgrid.hpp](include/gemmi/recgrid.hpp#L115-L121)
- **Systematic absence handling**: Optionally excludes forbidden reflections [recgrid.hpp](include/gemmi/recgrid.hpp#L124-L125)
- **Temperature factor application**: Applies B-factor sharpening or blurring [recgrid.hpp](include/gemmi/recgrid.hpp#L154-L165]

### Value Interpolation and Access

The `get_value_by_hkl()` function provides Miller index-based value access with optional corrections:

```cpp
T get_value_by_hkl(Miller hkl, double unblur=0, bool mott_bethe=false) const;
```

Features include:
- **Automatic Friedel mate lookup**: Handles negative l indices in half-grids [recgrid.hpp](include/gemmi/recgrid.hpp#L80-L81)
- **Temperature factor correction**: Applies exponential B-factor scaling [recgrid.hpp](include/gemmi/recgrid.hpp#L88-L90]
- **Mott-Bethe conversion**: Supports electron scattering calculations [recgrid.hpp](include/gemmi/recgrid.hpp#L91-L93]

## Performance Considerations

### Memory Layout Optimization

Gemmi uses contiguous memory storage with stride-aware FFT operations:

```cpp
pocketfft::stride_t stride{2*s * hkl.nv * hkl.nu, 2*s * hkl.nu, 2*s};
pocketfft::shape_t axes{2, 1, 0};
```

This layout maximizes cache efficiency and enables SIMD optimizations in the underlying PocketFFT library [fourier.hpp](include/gemmi/fourier.hpp#L261-L264].

### Axis Order Impact

The choice between XYZ and ZYX axis ordering affects both performance and compatibility:

| Aspect | XYZ Order | ZYX Order |
|--------|-----------|-----------|
| FFT Performance | Optimal for most libraries | May require axis swapping |
| CCP4 Compatibility | Native | Requires conversion |
| Memory Access | Cache-friendly for X-axis operations | Better for Z-axis operations |

> [!TIP]
> For optimal performance with large datasets, use the default XYZ ordering and ensure grid dimensions are multiples of 2, 3, or 5. This enables the most efficient FFT algorithms and minimizes memory overhead.

## Integration with Crystallographic Workflow

The FFT framework seamlessly integrates with Gemmi's broader crystallographic capabilities:

- **MTZ reflection data**: Direct processing of structure factor columns [mtz.hpp](include/gemmi/mtz.hpp)
- **Map file I/O**: CCP4/MRC format support for real-space grids [ccp4.hpp](include/gemmi/ccp4.hpp]
- **Symmetry operations**: Automatic application of space group symmetries [symmetry.hpp](include/gemmi/symmetry.hpp]

This integration enables end-to-end workflows from reflection data processing through map calculation and model refinement, all within a consistent, high-performance framework.

For further exploration of related topics, see [Electron Density Calculations](15-electron-density-calculations) for map analysis techniques and [Symmetry Operations and Space Groups](12-symmetry-operations-and-space-groups) for deeper understanding of symmetry handling in reciprocal space.