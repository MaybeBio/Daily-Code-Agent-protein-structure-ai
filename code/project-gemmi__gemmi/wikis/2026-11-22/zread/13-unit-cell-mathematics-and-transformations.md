

The Unit Cell Mathematics and Transformations module in Gemmi provides a comprehensive framework for handling crystallographic coordinate systems, cell parameter calculations, and symmetry operations. This documentation covers the mathematical foundations, coordinate transformations, and practical implementations for advanced crystallographic computing.

## Core Mathematical Framework

### Unit Cell Parameters and Properties

The `UnitCell` class serves as the central data structure, encapsulating six fundamental parameters (a, b, c, α, β, γ) along with pre-calculated mathematical properties essential for crystallographic computations [include/gemmi/unitcell.hpp#L165-L180].

```cpp
struct UnitCell : UnitCellParameters {
  Transform orth;  // Orthogonalization matrix
  Transform frac;  // Fractionalization matrix  
  double volume = 1.0;
  double ar = 1.0, br = 1.0, cr = 1.0;  // Reciprocal parameters
  double cos_alphar = 0.0, cos_betar = 0.0, cos_gammar = 0.0;
  bool explicit_matrices = false;
  std::vector<FTransform> images;  // Symmetry operations
};
```

The mathematical foundation follows the International Tables for Crystallography conventions, implementing the orthogonalization matrix that aligns the a₁ axis with the Cartesian X₁ axis and the a*₃ axis with the Cartesian X₃ axis [include/gemmi/unitcell.hpp#L226-L235].

### Volume and Reciprocal Cell Calculations

The cell volume calculation uses the formula from Giacovazzo p.62:

$$V = abc \sqrt{1 - \cos^2\alpha - \cos^2\beta - \cos^2\gamma + 2\cos\alpha\cos\beta\cos\gamma}$$

This implementation handles edge cases for right angles by using exact values (0.0 for cos, 1.0 for sin) to avoid numerical precision issues [include/gemmi/unitcell.hpp#L198-L211].

Reciprocal cell parameters are calculated using the standard relationships:

- $a^* = \frac{bc\sin\alpha}{V}$
- $b^* = \frac{ac\sin\beta}{V}$  
- $c^* = \frac{ab\sin\gamma}{V}$

## Coordinate System Transformations

### Position and Fractional Coordinate Types

Gemmi provides type-safe coordinate representations through `Position` (Cartesian/orthogonal) and `Fractional` coordinate systems [include/gemmi/unitcell.hpp#L31-L74]:

```cpp
struct Position : Vec3 {
  // Cartesian coordinates in Angstroms
  Position operator*(double d) const;
  Position operator/(double d) const;
};

struct Fractional : Vec3 {
  Fractional wrap_to_unit() const;
  Fractional wrap_to_zero() const;
  void move_toward_zero_by_one();
};
```

### Orthogonalization and Fractionalization

The core transformation methods convert between coordinate systems:

```cpp
Position orthogonalize(const Fractional& f) const;
Fractional fractionalize(const Position& o) const;
```

These utilize pre-calculated transformation matrices for optimal performance. The library also provides specialized methods for coordinate differences that avoid applying translation components when computing vector differences [include/gemmi/unitcell.hpp#L398-L407].

### Metric Tensors

The library implements both direct and reciprocal metric tensors following IUCr conventions [include/gemmi/unitcell.hpp#L588-L596]:

```cpp
SMat33<double> metric_tensor() const;
SMat33<double> reciprocal_metric_tensor() const;
```

The metric tensor elements are ordered as (a·a, b·b, c·c, a·b, a·c, b·c) following the Voigt notation convention.

## Symmetry Operations and Crystallographic Transformations

### Symmetry Image Management

The `UnitCell` class manages crystallographic symmetry operations through the `images` vector, storing fractional-space transformations [include/gemmi/unitcell.hpp#L181-L181]. The `NearestImage` structure provides comprehensive information about symmetry-related positions:

```cpp
struct NearestImage {
  double dist_sq;
  int pbc_shift[3] = { 0, 0, 0 };
  int sym_idx = 0;
  std::string symmetry_code(bool underscore) const;
};
```

### Periodic Boundary Condition Handling

Advanced algorithms handle periodic boundary conditions for finding nearest symmetry mates [include/gemmi/unitcell.hpp#L466-L484]:

```cpp
NearestImage find_nearest_image(const Position& ref, const Position& pos, Asu asu) const;
```

The `Asu` enum controls whether to search within the same asymmetric unit, different asymmetric units, or both [include/gemmi/unitcell.hpp#L76-L76].

### Special Position Detection

The library includes sophisticated algorithms for detecting special positions based on symmetry equivalence:

```cpp
int is_special_position(const Fractional& fpos, double max_dist) const;
int is_special_position(const Position& pos, double max_dist = 0.8) const;
```

This counts nearby symmetry mates to identify positions on symmetry elements (0 = none, 3 = 4-fold axis, etc.) [include/gemmi/unitcell.hpp#L547-L559].

## Reciprocal Space Calculations

### Miller Index Operations

Comprehensive support for Miller index calculations includes d-spacing and structure factor computations:

```cpp
double calculate_1_d2(const Miller& hkl) const;
double calculate_d(const Miller& hkl) const;
double calculate_stol_sq(const Miller& hkl) const;
```

The 1/d² calculation follows the standard formula:

$$\frac{1}{d^2} = (a^*h)^2 + (b^*k)^2 + (c^*l)^2 + 2[a^*b^*hk\cos\gamma^* + a^*c^*hl\cos\beta^* + b^*c^*kl\cos\alpha^*]$$

### HKL Limit Determination

The library provides practical utilities for determining reflection limits based on resolution:

```cpp
Miller get_hkl_limits(double dmin) const;
```

## Cell Reduction and Basis Transformations

### Niggli and Gruber Reduction

Advanced cell reduction algorithms are implemented through the `GruberVector` class, supporting both Niggli and Buerger reduction methods [python/unitcell.cpp#L345-L376]:

```cpp
class GruberVector {
  void niggli_reduce(double epsilon = 1e-9, int iteration_limit = 100);
  void buerger_reduce();
  bool is_niggli(double epsilon = 1e-9) const;
};
```

### Basis Change Operations

The library supports forward and backward basis transformations for changing crystallographic settings:

```cpp
UnitCell changed_basis_forward(const Op& op, bool set_images);
UnitCell changed_basis_backward(const Op& op, bool set_images);
```

These methods properly transform both cell parameters and symmetry operations [include/gemmi/unitcell.hpp#L315-L333].

## Python Interface and Bindings

### Comprehensive Python API

The Python bindings provide complete access to unit cell functionality with NumPy integration for array operations [python/unitcell.cpp#L259-L341]. Key features include:

- NumPy array support for Miller index operations
- Efficient array-based calculations for bulk operations
- Type-safe coordinate system handling

### Performance Optimizations

The Python interface includes specialized array functions for bulk calculations:

```python
def calculate_1_d2_array(self, hkl_array):
    # Efficient NumPy-based calculation
def calculate_d_array(self, hkl_array):
    # Bulk d-spacing computation
```

## Advanced Applications

### Space Group Compatibility

The library includes algorithms for verifying unit cell compatibility with space groups:

```cpp
bool is_compatible_with_spacegroup(const SpaceGroup* sg, double eps = 1e-3) const;
```

This checks metric tensor invariance under all symmetry operations [include/gemmi/unitcell.hpp#L335-L352].

### Non-Crystallographic Symmetry

Support for NCS operations allows handling of non-crystallographic symmetry transformations:

```cpp
void add_ncs_images_to_cs_images(const std::vector<NcsOp>& ncs);
std::vector<FTransform> get_ncs_transforms() const;
```

These methods integrate NCS operations with crystallographic symmetry for comprehensive symmetry handling [include/gemmi/unitcell.hpp#L372-L389].

The Unit Cell Mathematics and Transformations module provides a robust foundation for crystallographic computing, combining mathematical rigor with practical performance optimizations. For deeper understanding of symmetry operations, see [Symmetry Operations and Space Groups](12-symmetry-operations-and-space-groups), and for coordinate file handling, refer to [PDB and mmCIF Coordinate File Handling](9-pdb-and-mmcif-coordinate-file-handling).