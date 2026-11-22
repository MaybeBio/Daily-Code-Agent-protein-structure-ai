#pragma once
// Also compiled at run time by NVRTC (src/jit.cu embeds it), which has neither the runtime header nor <cstdint>.
#ifdef __CUDACC_RTC__
typedef long int64_t;
typedef unsigned long uint64_t;
typedef int int32_t;
typedef unsigned int uint32_t;
#else
#include <cuda_runtime.h>
#include <cstdint>
#endif

struct SplineGrid {
    float starts[8];
    float ends[8];
    float inv_h[8];
    int offsets[8];
    int counts[8];
    int n_bands;
    int total_intervals;
};

__device__ __forceinline__ void locate_spline(const SplineGrid& grid, float r, int& iv, float& t, float& sx_inv) {
    int k = 0;
    #pragma unroll
    for (int i = 0; i < 7; ++i) {
        if (i < grid.n_bands - 1 && r >= grid.ends[i]) k = i + 1;
    }
    sx_inv = grid.inv_h[k];
    float u = (r - grid.starts[k]) * sx_inv;
    u = u > 0.0f ? u : 0.0f;
    int il = (int)u;
    int mx = grid.counts[k] - 1;
    il = il < mx ? il : mx;
    t = u - (float)il;
    iv = grid.offsets[k] + il;
}

namespace loup {

constexpr float EPS_SH = 1e-12f;
// Neighbour-list build: lanes per atom in count_neighbors_kernel / fill_neighbors_kernel (a power of two <= 32).
constexpr int kNeighborLanes = 8;
constexpr float SH_S3  = 1.7320508075688772935f;
constexpr float SH_S5  = 2.2360679774997896964f;
constexpr float SH_S56 = 0.91287092917527685576f;  // sqrt(5/6)
constexpr float SH_S38 = 0.61237243569579452455f;  // sqrt(3/8)
constexpr float SH_C1  = 1.7320508075688772935f;  // sqrt(3)
constexpr float SH_C2  = 2.2360679774997896964f;  // sqrt(5)
constexpr float SH_C3  = 2.6457513110645905905f;  // sqrt(7)

__device__ __forceinline__ int sym_pair(int s, int t, int S) {
    int a = s < t ? s : t;
    int b = s < t ? t : s;
    return a * S - (a * (a - 1)) / 2 + (b - a);
}

// Radial-table pair of an edge (sender species s, receiver species t): one table per unordered pair (pair_sym 1), per
// ordered pair (0), or a single table for every pair (2: the bundle's per-pair tables are byte-identical, S116).
__device__ __forceinline__ int table_pair(int pair_sym, int s, int t, int S) {
    return pair_sym == 2 ? 0 : pair_sym ? sym_pair(s, t, S) : s * S + t;
}

// e3nn component-normalized l <= 3 spherical harmonics of the edge vector (vx, vy, vz) of length len (16 values).
// Computed where an edge is staged (i0 forward/backward, spline forward) instead of stored per edge.
__device__ __forceinline__ void edge_sh16(float vx, float vy, float vz, float len, float4 out[4]) {
    const float d = len > EPS_SH ? len : EPS_SH;
    const float inv_d = 1.0f / d;
    const float x = vx * inv_d, y = vy * inv_d, z = vz * inv_d;
    const float s20 = SH_S3 * x * z;
    const float s21 = SH_S3 * x * y;
    const float y2 = y * y;
    const float x2z2 = x * x + z * z;
    const float s22 = y2 - 0.5f * x2z2;
    const float s23 = SH_S3 * y * z;
    const float s24 = (0.5f * SH_S3) * (z * z - x * x);
    const float s30 = SH_S56 * (s20 * z + s24 * x);
    const float s31 = SH_S5 * s20 * y;
    const float s32 = SH_S38 * (4.0f * y2 - x2z2) * x;
    const float s33 = 0.5f * y * (2.0f * y2 - 3.0f * x2z2);
    const float s34 = SH_S38 * z * (4.0f * y2 - x2z2);
    const float s35 = SH_S5 * s24 * y;
    const float s36 = SH_S56 * (s24 * z - s20 * x);
    out[0] = make_float4(1.0f, x * SH_C1, y * SH_C1, z * SH_C1);
    out[1] = make_float4(s20 * SH_C2, s21 * SH_C2, s22 * SH_C2, s23 * SH_C2);
    out[2] = make_float4(s24 * SH_C2, s30 * SH_C3, s31 * SH_C3, s32 * SH_C3);
    out[3] = make_float4(s33 * SH_C3, s34 * SH_C3, s35 * SH_C3, s36 * SH_C3);
}

}  // namespace loup
