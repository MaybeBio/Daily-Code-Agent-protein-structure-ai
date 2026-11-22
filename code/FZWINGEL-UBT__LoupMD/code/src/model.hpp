#pragma once
// Error-check macros and the 8-byte table error guard, shared by the engine, the generic model and POLAR (the
// specialised OMAT-0 model that gave the file its name was retired in JIT_DESIGN.md stage 5).

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>

#include <cublas_v2.h>
#include <cuda_runtime.h>

#include "error.hpp"

#define CUDA_CHECK(call)                                                                                \
    do {                                                                                                \
        cudaError_t err__ = (call);                                                                     \
        if (err__ != cudaSuccess) {                                                                     \
            loup::set_error("CUDA error at %s:%d: %s", __FILE__, __LINE__, cudaGetErrorString(err__));  \
            return -1;                                                                                  \
        }                                                                                               \
    } while (0)

#define CUDA_CHECK_THROW(call)                                                                          \
    do {                                                                                                \
        cudaError_t err__ = (call);                                                                     \
        if (err__ != cudaSuccess) {                                                                     \
            throw std::runtime_error(std::string("CUDA error: ") + cudaGetErrorString(err__));          \
        }                                                                                               \
    } while (0)

#define CUBLAS_CHECK(call)                                                                              \
    do {                                                                                                \
        cublasStatus_t st__ = (call);                                                                   \
        if (st__ != CUBLAS_STATUS_SUCCESS) {                                                            \
            loup::set_error("cuBLAS error at %s:%d: status=%d", __FILE__, __LINE__, (int)st__);         \
            return -1;                                                                                  \
        }                                                                                               \
    } while (0)

#define CUBLAS_CHECK_THROW(call)                                                                        \
    do {                                                                                                \
        cublasStatus_t st__ = (call);                                                                   \
        if (st__ != CUBLAS_STATUS_SUCCESS) {                                                            \
            throw std::runtime_error("cuBLAS error");                                                   \
        }                                                                                               \
    } while (0)

namespace loup {
// cudaMalloc for the buffers that grow with the system (a system's rows and neighbour edges, POLAR's per-atom and
// k-space buffers, the GEMM timing's scratch, the tiled call's arenas, slots and kept layer-0 buffers): a request
// larger than the card's free memory is refused with cudaErrorMemoryAllocation, as a native driver refuses it. Under
// WSL 2 such a cudaMalloc can succeed: Windows' video memory manager pages allocations out to system memory, and every
// kernel then runs at bus speed (20 November 2026, RTX 5060 Ti: MACE-MH-1 at 98,415 atoms, whole, filled the card and
// ran for minutes per step; at 50,820 atoms the model's rows took the card's last 14.3 GB and a later allocation
// failed after 34 s). The free figure is NVML's where libnvidia-ml loads (it follows each allocation exactly), else
// CUDA's. Requests under 4 MiB are not checked. LOUP_DEBUG_ALLOC_FREE=<MiB> (tests): at most that much counts as free,
// and every request is checked. Defined in engine.cu, beside the NVML reader.
cudaError_t device_malloc(void** p, size_t bytes);
template <class T>
inline cudaError_t device_malloc(T** p, size_t bytes) {
    return device_malloc(reinterpret_cast<void**>(p), bytes);
}

// Largest accepted error of the 8-byte cubic tables (CUBIC_PACKED8), per column relative to the column's largest
// value or slope (d/dr) over all intervals and pairs. The bundles gated so far measure 2.7e-5 (POLAR-1-L) to 1.7e-4
// (OFF23 medium); OMAT-0 small's 1.0e-4 costs about 1.2 of the gate's 3 units. A guard against tables far outside what
// has been gated, not a certificate: the gate stays the acceptance test. Measured over the whole table and,
// separately, over the intervals lying wholly in r >= kPackedPhysicalR (the export certificate's second region, where MD
// edges lie), so large short-range values cannot hide a larger relative error in the physical range.
constexpr double kPackedTableMaxRelErr = 5e-4;
constexpr double kPackedPhysicalR = 1.0;

// max |c0 + c1 s + c2 s^2 + c3 s^3| over s in [lo, hi]: the endpoints and the real roots of the derivative.
inline double max_abs_cubic(double c0, double c1, double c2, double c3, double lo, double hi) {
    auto f = [&](double s) { return std::abs(c0 + s * (c1 + s * (c2 + s * c3))); };
    double m = std::max(f(lo), f(hi));
    const double A = 3.0 * c3, B = 2.0 * c2, C = c1;  // derivative A s^2 + B s + C
    if (A != 0.0) {
        const double disc = B * B - 4.0 * A * C;
        if (disc >= 0.0) {
            const double r = std::sqrt(disc);
            for (const double s : {(-B + r) / (2.0 * A), (-B - r) / (2.0 * A)})
                if (s > lo && s < hi) m = std::max(m, f(s));
        }
    } else if (B != 0.0) {
        const double s = -C / B;
        if (s > lo && s < hi) m = std::max(m, f(s));
    }
    return m;
}
// max |d0 + d1 s + d2 s^2| over s in [lo, hi]: the endpoints and the vertex.
inline double max_abs_quad(double d0, double d1, double d2, double lo, double hi) {
    auto f = [&](double s) { return std::abs(d0 + s * (d1 + s * d2)); };
    double m = std::max(f(lo), f(hi));
    if (d2 != 0.0) {
        const double s = -d1 / (2.0 * d2);
        if (s > lo && s < hi) m = std::max(m, f(s));
    }
    return m;
}

// Per-column maxima of |value|, |d/dr| and of their packing errors, over the whole table and over the physical
// region r >= kPackedPhysicalR (an interval straddling it contributes its part above); rel() is the worst
// error / maximum ratio of either region (see kPackedTableMaxRelErr).
struct PackErrTracker {
    int cols;
    std::vector<double> m[2][4];  // [all, physical][value, slope, value error, slope error]
    explicit PackErrTracker(int n) : cols(n) {
        for (auto& region : m)
            for (auto& v : region) v.assign((size_t)n, 0.0);
    }
    // a: original cubic and d: decoded - original, both in s = t - 1/2 on [-1/2, 1/2]; inv_h: 1 / interval width (A);
    // r0: the interval's start (A). The physical part is s >= (kPackedPhysicalR - r0) inv_h - 1/2.
    void add(int col, double r0, double inv_h, const double a[4], const double d[4]) {
        const double s_phys = std::max(-0.5, (kPackedPhysicalR - r0) * inv_h - 0.5);
        const int regions = s_phys < 0.5 ? 2 : 1;
        for (int r = 0; r < regions; ++r) {
            const double lo = r == 0 ? -0.5 : s_phys;
            const double x[4] = {max_abs_cubic(a[0], a[1], a[2], a[3], lo, 0.5),
                                 inv_h * max_abs_quad(a[1], 2 * a[2], 3 * a[3], lo, 0.5),
                                 max_abs_cubic(d[0], d[1], d[2], d[3], lo, 0.5),
                                 inv_h * max_abs_quad(d[1], 2 * d[2], 3 * d[3], lo, 0.5)};
            for (int k = 0; k < 4; ++k) m[r][k][(size_t)col] = std::max(m[r][k][(size_t)col], x[k]);
        }
    }
    double rel() const {
        double w = 0.0;
        for (const auto& region : m)
            for (int c = 0; c < cols; ++c) {
                if (region[0][(size_t)c] > 0.0) w = std::max(w, region[2][(size_t)c] / region[0][(size_t)c]);
                if (region[1][(size_t)c] > 0.0) w = std::max(w, region[3][(size_t)c] / region[1][(size_t)c]);
            }
        return w;
    }
};
}  // namespace loup
