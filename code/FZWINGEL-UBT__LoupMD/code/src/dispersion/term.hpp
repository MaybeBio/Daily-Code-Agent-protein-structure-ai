// The engine's interface for a dispersion term (plan tasks S6-D03, S6-D04; design docs/design/dispersion.md). It
// fixes what the force pass expects of any dispersion term, so the D3 pair sum, the three-body term and the
// long-range methods (tail, split, mesh) are entries behind one interface. The real-space pair sum
// (src/dispersion/d3_pair.cu) is the first.
//
// Rules every term keeps, the same as the model's force pass (src/generic.hpp):
// - record() is capturable: no host synchronisation, no allocation, no host reads of device data. The cell is read
//   on the device at every evaluation, so a captured step stays right when the cell changes (NPT). prepare() runs
//   outside capture whenever the atoms change (count, species).
// - The term adds to the pass's outputs; it never overwrites them. Energies and virial are summed in float64, pair
//   arithmetic is float32 on relative vectors (S6-D02 measured float32 pairs with float64 sums within 1e-5
//   meV/atom of simple-dftd3).
// - Units at the interface: positions and cell in A, energy in eV, forces in eV/A, virial in eV (dE/d strain; the
//   pass divides by the volume). Cutoffs arrive in bohr.
// - The energy-only path (per-atom energies, MC energy differences) records the energy without forces or virial.
#pragma once

#include <cstddef>
#include <cstdint>
#include <cuda_runtime.h>

namespace loup::dispersion {

enum class Damping : int32_t { BJ = 0, Zero = 1, BJM = 2, ZeroM = 3 };
enum class LongRange : int32_t { None = 0, Tail = 1, Split = 2, Mesh = 3 };  // "auto" is resolved before the term

// One resolved record (loupmd.dispersion.resolve): the functional's parameters are filled in, "auto" is replaced
// by the method the setup check chose (S6-D07).
struct Settings {
    Damping damping = Damping::BJ;
    double s6 = 1.0, s8 = 0.0;
    double a1 = 0.0, a2 = 0.0;                    // BJ, BJM (a2 in bohr)
    double rs6 = 0.0, rs8 = 1.0, alpha = 14.0;    // zero, zerom (alpha8 = alpha + 2)
    double beta = 0.0;                            // zerom (1/bohr)
    double pair_cutoff_bohr = 40.0, cn_cutoff_bohr = 40.0;
    bool three_body = false;
    double three_body_cutoff_bohr = 40.0;
    double smoothing_bohr = 0.0;                  // 0: no switch; else the width of the switch that ends at the cutoff
    LongRange long_range = LongRange::None;
    double mesh_spacing_A = 0.0;                  // 0: the method's default
};

// The D3 reference tables for elements 0..kElements-1 (index = atomic number; torch-dftd 0.5.1's, MIT).
constexpr int kElements = 95;
constexpr int kMaxRef = 5;
struct Tables {
    const int32_t* nref;     // [95] reference systems per element
    const double* cnref;     // [95, 5] their coordination numbers
    const double* rcov;      // [95] covalent radii, bohr, the 4/3 factor included
    const double* r2r4;      // [95] sqrt(0.5 <r4>/<r2> sqrt(Z)): C8 = 3 C6 r2r4_i r2r4_j
    const double* c6ref;     // [95, 95, 5, 5] reference C6, hartree bohr^6 (negative: no reference)
    const double* r0ab;      // [95, 95] cutoff radii of the zero dampings, bohr
};

// What the pass hands the term for one force evaluation. Device pointers, on the pass's stream.
struct Inputs {
    cudaStream_t stream;
    const double* positions;    // [n, 3], A, the pass's atom order (any image: wrapped here)
    const double* cell;         // [9] rows, A, on the device
    bool forces;                // false: the energy-only path (no forces, no virial)
    bool virial;
};

struct Outputs {
    double* energy;             // [1], eV, added to
    double* atom_energy;        // [n] or null, eV, added to (per-atom energies, S6-T08)
    double* forces;             // [n, 3] or null, eV/A, added to
    double* virial;             // [6] or null (xx xy xz yy yz zz), eV, added to
};

class Term {
public:
    virtual ~Term() = default;
    // Outside capture: allocate for these atoms (atomic numbers in the pass's order, host) and a cell like this one
    // (host, A; it sizes the bin grid, later cells of any shape are still summed exactly). Returns true when captured
    // graphs that contain record() must be re-recorded.
    virtual bool prepare(int n_atoms, const int32_t* numbers, const double cell[9], cudaStream_t stream) = 0;
    // Inside capture: the kernels of one evaluation.
    virtual void record(const Inputs& in, const Outputs& out) = 0;
    // Device bytes held (the capacity planner counts them).
    virtual size_t device_bytes() const = 0;
};

// Null with the reason in *why_not when the settings name something not built (three-body term, long-range
// methods). The tables are copied.
Term* make_term(const Settings& settings, const Tables& tables, const char** why_not);

}  // namespace loup::dispersion
