// The CUDA plugin: nonbonded real space, exclusion corrections and smooth PME
// (with an own mixed-radix FFT) on the GPU. See include/verlet/cuda_plugin.h.
#include <cuda_runtime.h>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include "verlet/cuda_plugin.h"

namespace {

constexpr double kPi = 3.14159265358979323846;
constexpr float kOneFourPiEps0 = 138.935456f;
constexpr int kOrder = 5;  // the PME spline order the kernels are written for

#define CK(x)                                                                           \
    do {                                                                                \
        cudaError_t e_ = (x);                                                           \
        if (e_ != cudaSuccess) {                                                        \
            std::snprintf(g_err, sizeof g_err, "%s: %s", #x, cudaGetErrorString(e_));    \
            return 1;                                                                   \
        }                                                                               \
    } while (0)
char g_err[512];

struct Ctx {
    int n = 0;
    float cutoff = 0, skin = 0;
    // device arrays
    float4* pos = nullptr;      // x, y, z, charge
    float2* lj = nullptr;       // sigma/2, sqrt(epsilon)
    float* force = nullptr;     // 3n
    int* excl_start = nullptr;  // CSR of the exclusions
    int* excl = nullptr;
    int2* excl_pairs = nullptr;
    int n_excl = 0;
    int* nbr = nullptr;  // column-major: nbr[k * n + i]
    int* nbr_count = nullptr;
    int max_nbr = 0;
    int* overflow = nullptr;
    // spatial sorting
    float4* spos = nullptr;  // positions in sorted order
    float2* slj = nullptr;
    float* sforce = nullptr;
    int* perm = nullptr;  // sorted slot -> file index
    int* perm_tmp = nullptr;
    int* cell_of = nullptr;
    int* cell_count = nullptr;
    int* cell_start = nullptr;
    int* cell_fill = nullptr;
    int ncell[3] = {0, 0, 0}, cells_alloc = 0;
    double* energy = nullptr;  // 4
    // PME
    float alpha = 0;
    int K[3] = {0, 0, 0};
    float* qgrid = nullptr;
    float2* cgrid = nullptr;
    float* eterm = nullptr;
    float* mod[3] = {nullptr, nullptr, nullptr};
    float2* twiddle[3] = {nullptr, nullptr, nullptr};
    std::vector<int> radices[3];
    int* radix_dev[3] = {nullptr, nullptr, nullptr};
    double eterm_box[3] = {0, 0, 0};
    // host staging (pinned)
    float4* h_pos = nullptr;
    float* h_force = nullptr;
    double h_energy[4];
    std::vector<float> charge;
    double box[3] = {0, 0, 0};
    int want_energy = 0;
    cudaStream_t stream = nullptr;
    std::string device;
};

// ---- nonbonded --------------------------------------------------------------------

__device__ __forceinline__ float3 min_image(float3 d, float3 box, float3 inv) {
    d.x -= box.x * rintf(d.x * inv.x);
    d.y -= box.y * rintf(d.y * inv.y);
    d.z -= box.z * rintf(d.z * inv.z);
    return d;
}

__device__ __forceinline__ int cell_coord(float x, float L, int nc) {
    float u = x / L;
    u -= floorf(u);
    int c = int(u * nc);
    return c >= nc ? nc - 1 : c;
}

// Spatial sorting: atoms are reordered by cell at every neighbor-list
// rebuild, so that the threads of a warp work on nearby atoms (coalesced and
// cached loads); forces are scattered back to the file order at the end.
__global__ void k_cell_of(const float4* pos, int n, float3 box, int3 nc, int* cell_of, int* count) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= n) return;
    float4 p = pos[i];
    int c = (cell_coord(p.x, box.x, nc.x) * nc.y + cell_coord(p.y, box.y, nc.y)) * nc.z + cell_coord(p.z, box.z, nc.z);
    cell_of[i] = c;
    atomicAdd(&count[c], 1);
}

__global__ void k_scan(const int* count, int* start, int* fill, int ncells) {
    if (threadIdx.x == 0 && blockIdx.x == 0) {
        int s = 0;
        for (int c = 0; c < ncells; ++c) {
            start[c] = s;
            fill[c] = 0;
            s += count[c];
        }
        start[ncells] = s;
    }
}

__global__ void k_scatter(const int* cell_of, const int* start, int* fill, int* perm, int n) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= n) return;
    int c = cell_of[i];
    perm[start[c] + atomicAdd(&fill[c], 1)] = i;
}

// deterministic order inside each cell (by file index): one block per cell,
// each element's rank is the number of smaller elements
__global__ void k_sort_cells(const int* start, const int* perm_in, int* perm_out) {
    const int c0 = start[blockIdx.x], c1 = start[blockIdx.x + 1], m = c1 - c0;
    for (int a = threadIdx.x; a < m; a += blockDim.x) {
        const int v = perm_in[c0 + a];
        int rank = 0;
        for (int b = 0; b < m; ++b) rank += perm_in[c0 + b] < v;
        perm_out[c0 + rank] = v;
    }
}

__global__ void k_permute(const float4* pos, const float2* lj, const int* perm, float4* spos, float2* slj, int n) {
    int s = blockIdx.x * blockDim.x + threadIdx.x;
    if (s >= n) return;
    int i = perm[s];
    spos[s] = pos[i];
    if (slj) slj[s] = lj[i];
}

__global__ void k_unsort_forces(const float* sforce, const int* perm, float* force, int n) {
    int s = blockIdx.x * blockDim.x + threadIdx.x;
    if (s >= n) return;
    int i = perm[s];
    force[3 * i] += sforce[3 * s];
    force[3 * i + 1] += sforce[3 * s + 1];
    force[3 * i + 2] += sforce[3 * s + 2];
}

// One thread per atom in sorted order: the threads of a warp mostly share a
// cell, so they walk the same neighboring cells and their loads coincide.
// The list is row-major (nbr[i * max_nbr + k]) for the force kernel.
__global__ void k_neighbors(const float4* spos, const int* perm, int n, float3 box, float3 inv, int3 nc,
                            const int* start, const int* ex_start, const int* ex, float rl2, int* nbr, int* nbr_count, int max_nbr,
                            int* overflow) {
    const int si = blockIdx.x * blockDim.x + threadIdx.x;
    if (si >= n) return;
    const float4 p = spos[si];
    const int hx = cell_coord(p.x, box.x, nc.x), hy = cell_coord(p.y, box.y, nc.y), hz = cell_coord(p.z, box.z, nc.z);
    int ox[3], oy[3], oz[3], nx = 0, ny = 0, nzc = 0;
    for (int d = -1; d <= 1; ++d) {
        if (nc.x >= 3 || (d >= 0 && d < nc.x)) ox[nx++] = (hx + d + nc.x) % nc.x;
        if (nc.y >= 3 || (d >= 0 && d < nc.y)) oy[ny++] = (hy + d + nc.y) % nc.y;
        if (nc.z >= 3 || (d >= 0 && d < nc.z)) oz[nzc++] = (hz + d + nc.z) % nc.z;
    }
    const int oi = perm[si];
    const int e0 = ex_start[oi], e1 = ex_start[oi + 1];
    int* out = nbr + size_t(si) * max_nbr;
    int k = 0;
    for (int a = 0; a < nx; ++a)
        for (int b = 0; b < ny; ++b)
            for (int cz = 0; cz < nzc; ++cz) {
                const int cell = (ox[a] * nc.y + oy[b]) * nc.z + oz[cz];
                const int c1 = __ldg(&start[cell + 1]);
                for (int sj = __ldg(&start[cell]); sj < c1; ++sj) {
                    if (sj == si) continue;
                    const float4 q = __ldg(&spos[sj]);
                    float3 d = min_image(make_float3(q.x - p.x, q.y - p.y, q.z - p.z), box, inv);
                    if (d.x * d.x + d.y * d.y + d.z * d.z > rl2) continue;
                    if (e1 > e0) {
                        const int oj = __ldg(&perm[sj]);
                        bool excluded = false;
                        for (int e = e0; e < e1; ++e)
                            if (__ldg(&ex[e]) == oj) {
                                excluded = true;
                                break;
                            }
                        if (excluded) continue;
                    }
                    if (k < max_nbr) out[k] = sj;
                    ++k;
                }
            }
    nbr_count[si] = k;
    if (k > max_nbr) atomicMax(overflow, k);
}

// erfc(x) for x >= 0 (Abramowitz and Stegun 7.1.26, |error| < 1.5e-7), times exp(-x^2) computed once
__device__ __forceinline__ float erfc_approx(float x, float expmx2) {
    float t = 1.0f / (1.0f + 0.3275911f * x);
    return (((((1.061405429f * t - 1.453152027f) * t) + 1.421413741f) * t - 0.284496736f) * t + 0.254829592f) * t * expmx2;
}

// kTpa threads per atom, each taking every kTpa-th neighbor; the partial
// forces are summed with warp shuffles.
constexpr int kTpa = 8;

__global__ void k_nonbonded(const float4* pos, const float2* lj, int n, float3 box, float3 inv, const int* nbr, const int* nbr_count,
                            int max_nbr, float rc2, float alpha, float* force, double* energy, int want_energy) {
    const int gid = blockIdx.x * blockDim.x + threadIdx.x;
    const int i = gid / kTpa, lane = gid % kTpa;
    float elj = 0, ecl = 0;
    float3 f = make_float3(0, 0, 0);
    if (i < n) {
        float4 p = pos[i];
        float2 li = lj[i];
        int cnt = nbr_count[i];
        const int* list = nbr + size_t(i) * max_nbr;
        const float two_over_sqrtpi = 1.1283791670955126f;
        for (int k = lane; k < cnt; k += kTpa) {
            int j = list[k];
            float4 q = __ldg(&pos[j]);
            float3 d = min_image(make_float3(p.x - q.x, p.y - q.y, p.z - q.z), box, inv);
            float r2 = d.x * d.x + d.y * d.y + d.z * d.z;
            if (r2 >= rc2) continue;
            float inv_r = rsqrtf(r2), r = r2 * inv_r, inv_r2 = inv_r * inv_r;
            float qq = kOneFourPiEps0 * p.w * q.w;
            float ar = alpha * r, e = __expf(-ar * ar);
            float ec = qq * erfc_approx(ar, e) * inv_r;
            float fr = (ec + qq * two_over_sqrtpi * alpha * e) * inv_r2;
            float2 lj_j = __ldg(&lj[j]);
            float eps = li.y * lj_j.y;
            if (eps != 0) {
                float sg = li.x + lj_j.x;
                float s2 = sg * sg * inv_r2, s6 = s2 * s2 * s2;
                fr += 24 * eps * (2 * s6 * s6 - s6) * inv_r2;
                elj += 4 * eps * (s6 * s6 - s6);
            }
            ecl += ec;
            f.x += fr * d.x;
            f.y += fr * d.y;
            f.z += fr * d.z;
        }
    }
    // sum the kTpa partial forces (lanes of one atom are adjacent in the warp)
    for (int off = kTpa / 2; off > 0; off >>= 1) {
        f.x += __shfl_down_sync(0xffffffffu, f.x, off, kTpa);
        f.y += __shfl_down_sync(0xffffffffu, f.y, off, kTpa);
        f.z += __shfl_down_sync(0xffffffffu, f.z, off, kTpa);
    }
    if (i < n && lane == 0) {
        force[3 * i] = f.x;
        force[3 * i + 1] = f.y;
        force[3 * i + 2] = f.z;
    }
    if (want_energy) {
        // each pair was counted from both sides
        __shared__ double s[2][256];
        s[0][threadIdx.x] = 0.5 * elj;
        s[1][threadIdx.x] = 0.5 * ecl;
        __syncthreads();
        for (int w = blockDim.x / 2; w > 0; w >>= 1) {
            if (threadIdx.x < w) {
                s[0][threadIdx.x] += s[0][threadIdx.x + w];
                s[1][threadIdx.x] += s[1][threadIdx.x + w];
            }
            __syncthreads();
        }
        if (threadIdx.x == 0) {
            atomicAdd(&energy[0], s[0][0]);
            atomicAdd(&energy[1], s[1][0]);
        }
    }
}

// excluded pairs: remove the reciprocal-space interaction, - qi qj erf(a r)/r
__global__ void k_exclusions(const float4* pos, const int2* pairs, int m, float3 box, float3 inv, float alpha, float* force, double* energy,
                             int want_energy) {
    int k = blockIdx.x * blockDim.x + threadIdx.x;
    float e_sum = 0;
    if (k < m) {
        int2 pr = pairs[k];
        float4 p = pos[pr.x], q = pos[pr.y];
        float qq = kOneFourPiEps0 * p.w * q.w;
        if (qq != 0) {
            float3 d = min_image(make_float3(p.x - q.x, p.y - q.y, p.z - q.z), box, inv);
            float r2 = d.x * d.x + d.y * d.y + d.z * d.z, r = sqrtf(r2);
            float ar = alpha * r, ex = __expf(-ar * ar);
            // erf(x) = 1 - erfc(x); for the small x of bonded pairs use the series for accuracy
            float erf_ar = ar < 0.5f ? 1.1283791670955126f * ar * (1 + ar * ar * (-1.0f / 3 + ar * ar * (1.0f / 10 + ar * ar * (-1.0f / 42 + ar * ar * (1.0f / 216 - ar * ar / 1320)))))
                                     : 1 - erfc_approx(ar, ex);
            float e = -qq * erf_ar / r;
            float fr = (e + qq * 1.1283791670955126f * alpha * ex) / r2;
            e_sum = e;
            atomicAdd(&force[3 * pr.x], fr * d.x);
            atomicAdd(&force[3 * pr.x + 1], fr * d.y);
            atomicAdd(&force[3 * pr.x + 2], fr * d.z);
            atomicAdd(&force[3 * pr.y], -fr * d.x);
            atomicAdd(&force[3 * pr.y + 1], -fr * d.y);
            atomicAdd(&force[3 * pr.y + 2], -fr * d.z);
        }
    }
    if (want_energy) {
        __shared__ double s[256];
        s[threadIdx.x] = e_sum;
        __syncthreads();
        for (int w = blockDim.x / 2; w > 0; w >>= 1) {
            if (threadIdx.x < w) s[threadIdx.x] += s[threadIdx.x + w];
            __syncthreads();
        }
        if (threadIdx.x == 0) atomicAdd(&energy[3], s[0]);
    }
}

// ---- PME ------------------------------------------------------------------------------

__device__ __forceinline__ void bspline5(float w, float* th, float* dth) {
    // order 5, as in the CPU version: th[k] belongs to grid point floor(u) - 4 + k
    float d[5];
    d[4] = 0;
    d[1] = w;
    d[0] = 1 - w;
    // j = 3
    d[2] = 0.5f * w * d[1];
    d[1] = 0.5f * ((w + 1) * d[0] + (2 - w) * d[1]);
    d[0] = 0.5f * (1 - w) * d[0];
    // j = 4
    d[3] = (1.0f / 3) * w * d[2];
    d[2] = (1.0f / 3) * ((w + 1) * d[1] + (3 - w) * d[2]);
    d[1] = (1.0f / 3) * ((w + 2) * d[0] + (2 - w) * d[1]);
    d[0] = (1.0f / 3) * (1 - w) * d[0];
    dth[0] = -d[0];
    for (int k = 1; k < 5; ++k) dth[k] = d[k - 1] - d[k];
    th[4] = 0.25f * w * d[3];
    th[3] = 0.25f * ((w + 1) * d[2] + (4 - w) * d[3]);
    th[2] = 0.25f * ((w + 2) * d[1] + (3 - w) * d[2]);
    th[1] = 0.25f * ((w + 3) * d[0] + (2 - w) * d[1]);
    th[0] = 0.25f * (1 - w) * d[0];
}

__device__ __forceinline__ void frac(float x, float L, int K, int& base, float& w) {
    float u = x / L;
    u = (u - floorf(u)) * K;
    int iu = int(u);
    if (iu >= K) iu = K - 1;
    w = u - iu;
    base = iu - kOrder + 1;
}

__global__ void k_spread(const float4* pos, int n, float3 box, int3 K, float* grid) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= n) return;
    float4 p = pos[i];
    if (p.w == 0) return;
    float tx[5], ty[5], tz[5], d[5], w;
    int bx, by, bz;
    frac(p.x, box.x, K.x, bx, w);
    bspline5(w, tx, d);
    frac(p.y, box.y, K.y, by, w);
    bspline5(w, ty, d);
    frac(p.z, box.z, K.z, bz, w);
    bspline5(w, tz, d);
    for (int a = 0; a < 5; ++a) {
        int gx = (bx + a + K.x) % K.x;
        for (int b = 0; b < 5; ++b) {
            int gy = (by + b + K.y) % K.y;
            float qab = p.w * tx[a] * ty[b];
            size_t row = (size_t(gx) * K.y + gy) * K.z;
            for (int c = 0; c < 5; ++c) atomicAdd(&grid[row + (bz + c + K.z) % K.z], qab * tz[c]);
        }
    }
}

__global__ void k_real_to_complex(const float* r, float2* c, size_t m) {
    size_t i = blockIdx.x * size_t(blockDim.x) + threadIdx.x;
    if (i < m) c[i] = make_float2(r[i], 0);
}

// One block transforms one line of length L (stride `stride` between elements)
// with the Stockham autosort algorithm, the same as fft.cpp.
__global__ void k_fft_lines(float2* data, int L, int stride, int line_stride_a, int count_b, int line_stride_b, const float2* tw,
                            const int* radices, int nrad, float sign) {
    extern __shared__ float2 sm[];
    float2* a = sm;
    float2* b = sm + L;
    int line = blockIdx.x;
    size_t base = size_t(line / count_b) * line_stride_a + size_t(line % count_b) * line_stride_b;
    for (int t = threadIdx.x; t < L; t += blockDim.x) a[t] = data[base + size_t(t) * stride];
    __syncthreads();
    int Ns = 1;
    for (int s = 0; s < nrad; ++s) {
        int R = radices[s];
        int m = L / R;
        for (int j = threadIdx.x; j < m; j += blockDim.x) {
            int jm = j % Ns;
            float2 v[32], w[32];
            int step = L / (Ns * R);  // twiddle index unit for this stage
            for (int r = 0; r < R; ++r) {
                float2 x = a[j + r * m];
                float2 t = tw[(r * jm * step) % L];
                t.y *= -sign;  // the table holds exp(-i theta)
                v[r] = make_float2(x.x * t.x - x.y * t.y, x.x * t.y + x.y * t.x);
            }
            int unit = L / R;
            for (int k = 0; k < R; ++k) {
                float2 acc = make_float2(0, 0);
                for (int r = 0; r < R; ++r) {
                    float2 t = tw[((r * k) % R) * unit];
                    t.y *= -sign;
                    acc.x += v[r].x * t.x - v[r].y * t.y;
                    acc.y += v[r].x * t.y + v[r].y * t.x;
                }
                w[k] = acc;
            }
            int dst = (j / Ns) * Ns * R + jm;
            for (int r = 0; r < R; ++r) b[dst + r * Ns] = w[r];
        }
        __syncthreads();
        float2* tmp = a;
        a = b;
        b = tmp;
        Ns *= R;
    }
    for (int t = threadIdx.x; t < L; t += blockDim.x) data[base + size_t(t) * stride] = a[t];
}

__global__ void k_eterm(float* eterm, int3 K, float3 box, float alpha, const float* mx, const float* my, const float* mz) {
    size_t g = blockIdx.x * size_t(blockDim.x) + threadIdx.x;
    size_t total = size_t(K.x) * K.y * K.z;
    if (g >= total) return;
    int z = int(g % K.z), y = int((g / K.z) % K.y), x = int(g / (size_t(K.z) * K.y));
    if (x == 0 && y == 0 && z == 0) {
        eterm[g] = 0;
        return;
    }
    double fx = (x <= K.x / 2 ? x : x - K.x) / double(box.x);
    double fy = (y <= K.y / 2 ? y : y - K.y) / double(box.y);
    double fz = (z <= K.z / 2 ? z : z - K.z) / double(box.z);
    double m2 = fx * fx + fy * fy + fz * fz;
    double V = double(box.x) * box.y * box.z;
    double e = 138.935456 / (kPi * V) * exp(-kPi * kPi * m2 / (double(alpha) * alpha)) / (m2 * mx[x] * my[y] * mz[z]);
    eterm[g] = float(e);
}

__global__ void k_convolve(float2* c, const float* eterm, size_t m, double* energy, int want_energy) {
    size_t g = blockIdx.x * size_t(blockDim.x) + threadIdx.x;
    double e = 0;
    if (g < m) {
        float2 v = c[g];
        float t = eterm[g];
        e = 0.5 * double(t) * (double(v.x) * v.x + double(v.y) * v.y);
        c[g] = make_float2(v.x * t, v.y * t);
    }
    if (want_energy) {
        __shared__ double s[256];
        s[threadIdx.x] = e;
        __syncthreads();
        for (int w = blockDim.x / 2; w > 0; w >>= 1) {
            if (threadIdx.x < w) s[threadIdx.x] += s[threadIdx.x + w];
            __syncthreads();
        }
        if (threadIdx.x == 0) atomicAdd(&energy[2], s[0]);
    }
}

__global__ void k_gather(const float4* pos, int n, float3 box, int3 K, const float2* grid, float* force) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= n) return;
    float4 p = pos[i];
    if (p.w == 0) return;
    float tx[5], ty[5], tz[5], dx[5], dy[5], dz[5], w;
    int bx, by, bz;
    frac(p.x, box.x, K.x, bx, w);
    bspline5(w, tx, dx);
    frac(p.y, box.y, K.y, by, w);
    bspline5(w, ty, dy);
    frac(p.z, box.z, K.z, bz, w);
    bspline5(w, tz, dz);
    float fx = 0, fy = 0, fz = 0;
    for (int a = 0; a < 5; ++a) {
        int gx = (bx + a + K.x) % K.x;
        for (int b = 0; b < 5; ++b) {
            int gy = (by + b + K.y) % K.y;
            size_t row = (size_t(gx) * K.y + gy) * K.z;
            for (int c = 0; c < 5; ++c) {
                float phi = grid[row + (bz + c + K.z) % K.z].x;
                fx += dx[a] * ty[b] * tz[c] * phi;
                fy += tx[a] * dy[b] * tz[c] * phi;
                fz += tx[a] * ty[b] * dz[c] * phi;
            }
        }
    }
    force[3 * i] -= p.w * fx * K.x / box.x;
    force[3 * i + 1] -= p.w * fy * K.y / box.y;
    force[3 * i + 2] -= p.w * fz * K.z / box.z;
}

// ---- host helpers ---------------------------------------------------------------------

std::vector<int> radices_of(int n) {
    std::vector<int> r;
    while (n % 4 == 0) { r.push_back(4); n /= 4; }
    for (int p : {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31}) while (n % p == 0) { r.push_back(p); n /= p; }
    if (n != 1) r.clear();  // unsupported factor
    return r;
}

std::vector<double> bspline_moduli(int K) {
    // M_5 at 1, 2, 3, 4 = 1/24, 11/24, 11/24, 1/24
    const double M[4] = {1.0 / 24, 11.0 / 24, 11.0 / 24, 1.0 / 24};
    std::vector<double> mod(K);
    for (int i = 0; i < K; ++i) {
        double sc = 0, ss = 0;
        for (int k = 0; k < 4; ++k) {
            sc += M[k] * std::cos(2 * kPi * i * k / K);
            ss += M[k] * std::sin(2 * kPi * i * k / K);
        }
        mod[i] = sc * sc + ss * ss;
    }
    for (int i = 0; i < K; ++i)
        if (mod[i] < 1e-7) mod[i] = 0.5 * (mod[(i - 1 + K) % K] + mod[(i + 1) % K]);
    return mod;
}

int fft3d(Ctx* c, float sign) {
    const int Kx = c->K[0], Ky = c->K[1], Kz = c->K[2];
    // z lines: contiguous; lines indexed by (x, y)
    struct Pass { int L, stride, sa, cb, sb, nlines, d; };
    Pass passes[3] = {
        {Kz, 1, Ky * Kz, Ky, Kz, Kx * Ky, 2},
        {Ky, Kz, Ky * Kz, Kz, 1, Kx * Kz, 1},
        {Kx, Ky * Kz, 1, 1, 0, Ky * Kz, 0},
    };
    for (auto& p : passes) {
        int threads = std::min(128, std::max(32, p.L / 2));
        k_fft_lines<<<p.nlines, threads, 2 * p.L * sizeof(float2), c->stream>>>(c->cgrid, p.L, p.stride, p.sa, p.cb, p.sb, c->twiddle[p.d],
                                                                             c->radix_dev[p.d], int(c->radices[p.d].size()), sign);
    }
    CK(cudaGetLastError());
    return 0;
}

int build_neighbors(Ctx* c, float3 box, float3 inv) {
    const double rl = c->cutoff + c->skin;
    int nc[3];
    for (int d = 0; d < 3; ++d) nc[d] = std::max(1, int(c->box[d] / rl));
    const int total = nc[0] * nc[1] * nc[2];
    if (total > c->cells_alloc) {
        cudaFree(c->cell_count);
        cudaFree(c->cell_start);
        cudaFree(c->cell_fill);
        CK(cudaMalloc(&c->cell_count, total * sizeof(int)));
        CK(cudaMalloc(&c->cell_start, (total + 1) * sizeof(int)));
        CK(cudaMalloc(&c->cell_fill, total * sizeof(int)));
        c->cells_alloc = total;
    }
    for (int d = 0; d < 3; ++d) c->ncell[d] = nc[d];
    const int3 ncv = make_int3(nc[0], nc[1], nc[2]);
    const int blocks = (c->n + 127) / 128;
    CK(cudaMemsetAsync(c->cell_count, 0, total * sizeof(int), c->stream));
    k_cell_of<<<blocks, 128, 0, c->stream>>>(c->pos, c->n, box, ncv, c->cell_of, c->cell_count);
    k_scan<<<1, 32, 0, c->stream>>>(c->cell_count, c->cell_start, c->cell_fill, total);
    k_scatter<<<blocks, 128, 0, c->stream>>>(c->cell_of, c->cell_start, c->cell_fill, c->perm_tmp, c->n);
    k_sort_cells<<<total, 128, 0, c->stream>>>(c->cell_start, c->perm_tmp, c->perm);
    k_permute<<<blocks, 128, 0, c->stream>>>(c->pos, c->lj, c->perm, c->spos, c->slj, c->n);
    for (int attempt = 0; attempt < 3; ++attempt) {
        CK(cudaMemsetAsync(c->overflow, 0, sizeof(int), c->stream));
        k_neighbors<<<blocks, 128, 0, c->stream>>>(c->spos, c->perm, c->n, box, inv, ncv, c->cell_start, c->excl_start, c->excl,
                                                    float(rl * rl), c->nbr, c->nbr_count, c->max_nbr, c->overflow);
        CK(cudaGetLastError());
        int over = 0;
        CK(cudaMemcpyAsync(&over, c->overflow, sizeof(int), cudaMemcpyDeviceToHost, c->stream));
        CK(cudaStreamSynchronize(c->stream));
        if (over <= c->max_nbr) return 0;
        cudaFree(c->nbr);
        c->max_nbr = int(over * 1.3) + 32;
        CK(cudaMalloc(&c->nbr, size_t(c->max_nbr) * c->n * sizeof(int)));
    }
    std::snprintf(g_err, sizeof g_err, "neighbor list overflow");
    return 1;
}

}  // namespace

extern "C" {

int vc_create(void** out, int n, const double* charge, const double* sigma, const double* epsilon, int n_excl, const int* excl_pairs,
              double cutoff, double skin, char* err, int errlen) {
    auto fail = [&](const char* m) {
        std::snprintf(err, errlen, "%s", m);
        return 1;
    };
    int devices = 0;
    if (cudaGetDeviceCount(&devices) != cudaSuccess || devices == 0) return fail("no CUDA device");
    Ctx* c = new Ctx;
    c->n = n;
    c->cutoff = float(cutoff);
    c->skin = float(skin);
    cudaDeviceProp prop;
    cudaGetDeviceProperties(&prop, 0);
    c->device = prop.name;
    if (cudaStreamCreate(&c->stream) != cudaSuccess) return fail("cannot create a stream");
    std::vector<float2> lj(n);
    c->charge.resize(n);
    for (int i = 0; i < n; ++i) {
        lj[i] = make_float2(float(0.5 * sigma[i]), float(std::sqrt(epsilon[i])));
        c->charge[i] = float(charge[i]);
    }
    std::vector<std::vector<int>> ex(n);
    for (int k = 0; k < n_excl; ++k) {
        ex[excl_pairs[2 * k]].push_back(excl_pairs[2 * k + 1]);
        ex[excl_pairs[2 * k + 1]].push_back(excl_pairs[2 * k]);
    }
    std::vector<int> start(n + 1, 0), flat;
    for (int i = 0; i < n; ++i) {
        start[i + 1] = start[i] + int(ex[i].size());
        flat.insert(flat.end(), ex[i].begin(), ex[i].end());
    }
    if (flat.empty()) flat.push_back(-1);
    c->n_excl = n_excl;
    bool ok = cudaMalloc(&c->pos, n * sizeof(float4)) == cudaSuccess && cudaMalloc(&c->lj, n * sizeof(float2)) == cudaSuccess &&
              cudaMalloc(&c->force, 3 * size_t(n) * sizeof(float)) == cudaSuccess &&
              cudaMalloc(&c->excl_start, (n + 1) * sizeof(int)) == cudaSuccess &&
              cudaMalloc(&c->excl, flat.size() * sizeof(int)) == cudaSuccess &&
              cudaMalloc(&c->excl_pairs, std::max(1, n_excl) * sizeof(int2)) == cudaSuccess &&
              cudaMalloc(&c->nbr_count, n * sizeof(int)) == cudaSuccess && cudaMalloc(&c->overflow, sizeof(int)) == cudaSuccess &&
              cudaMalloc(&c->spos, n * sizeof(float4)) == cudaSuccess && cudaMalloc(&c->slj, n * sizeof(float2)) == cudaSuccess &&
              cudaMalloc(&c->sforce, 3 * size_t(n) * sizeof(float)) == cudaSuccess && cudaMalloc(&c->perm, n * sizeof(int)) == cudaSuccess &&
              cudaMalloc(&c->cell_of, n * sizeof(int)) == cudaSuccess && cudaMalloc(&c->perm_tmp, n * sizeof(int)) == cudaSuccess &&
              cudaMalloc(&c->energy, 4 * sizeof(double)) == cudaSuccess &&
              cudaMallocHost(&c->h_pos, n * sizeof(float4)) == cudaSuccess &&
              cudaMallocHost(&c->h_force, 3 * size_t(n) * sizeof(float)) == cudaSuccess;
    if (!ok) return fail("out of GPU memory");
    double rl = cutoff + skin;
    c->max_nbr = int(4.0 / 3 * kPi * rl * rl * rl * 110 * 1.25) + 32;
    if (cudaMalloc(&c->nbr, size_t(c->max_nbr) * n * sizeof(int)) != cudaSuccess) return fail("out of GPU memory (neighbor list)");
    cudaMemcpy(c->lj, lj.data(), n * sizeof(float2), cudaMemcpyHostToDevice);
    cudaMemcpy(c->excl_start, start.data(), (n + 1) * sizeof(int), cudaMemcpyHostToDevice);
    cudaMemcpy(c->excl, flat.data(), flat.size() * sizeof(int), cudaMemcpyHostToDevice);
    if (n_excl) cudaMemcpy(c->excl_pairs, excl_pairs, n_excl * sizeof(int2), cudaMemcpyHostToDevice);
    *out = c;
    return 0;
}

int vc_set_charges(void* ctx, const double* charge) {
    Ctx* c = static_cast<Ctx*>(ctx);
    for (int i = 0; i < c->n; ++i) c->charge[i] = float(charge[i]);
    return 0;
}

int vc_set_pme(void* ctx, double alpha, int nx, int ny, int nz, int order) {
    Ctx* c = static_cast<Ctx*>(ctx);
    if (order != kOrder) {
        std::snprintf(g_err, sizeof g_err, "the CUDA PME supports order %d only", kOrder);
        return 1;
    }
    c->alpha = float(alpha);
    int K[3] = {nx, ny, nz};
    size_t G = size_t(nx) * ny * nz;
    CK(cudaMalloc(&c->qgrid, G * sizeof(float)));
    CK(cudaMalloc(&c->cgrid, G * sizeof(float2)));
    CK(cudaMalloc(&c->eterm, G * sizeof(float)));
    for (int d = 0; d < 3; ++d) {
        c->K[d] = K[d];
        c->radices[d] = radices_of(K[d]);
        if (c->radices[d].empty()) {
            std::snprintf(g_err, sizeof g_err, "PME grid size %d has a prime factor above 31", K[d]);
            return 1;
        }
        auto mod = bspline_moduli(K[d]);
        std::vector<float> modf(K[d]);
        for (int k = 0; k < K[d]; ++k) modf[k] = float(mod[k]);
        std::vector<float2> tw(K[d]);
        for (int k = 0; k < K[d]; ++k) tw[k] = make_float2(float(std::cos(-2 * kPi * k / K[d])), float(std::sin(-2 * kPi * k / K[d])));
        CK(cudaMalloc(&c->mod[d], K[d] * sizeof(float)));
        CK(cudaMalloc(&c->twiddle[d], K[d] * sizeof(float2)));
        CK(cudaMalloc(&c->radix_dev[d], c->radices[d].size() * sizeof(int)));
        CK(cudaMemcpy(c->mod[d], modf.data(), K[d] * sizeof(float), cudaMemcpyHostToDevice));
        CK(cudaMemcpy(c->twiddle[d], tw.data(), K[d] * sizeof(float2), cudaMemcpyHostToDevice));
        CK(cudaMemcpy(c->radix_dev[d], c->radices[d].data(), c->radices[d].size() * sizeof(int), cudaMemcpyHostToDevice));
    }
    c->eterm_box[0] = c->eterm_box[1] = c->eterm_box[2] = 0;
    return 0;
}

int vc_begin(void* ctx, const double* pos, const double* box, int rebuild, int want_energy) {
    Ctx* c = static_cast<Ctx*>(ctx);
    for (int i = 0; i < c->n; ++i) c->h_pos[i] = make_float4(float(pos[3 * i]), float(pos[3 * i + 1]), float(pos[3 * i + 2]), c->charge[i]);
    bool box_changed = box[0] != c->box[0] || box[1] != c->box[1] || box[2] != c->box[2];
    for (int d = 0; d < 3; ++d) c->box[d] = box[d];
    c->want_energy = want_energy;
    float3 b = make_float3(float(box[0]), float(box[1]), float(box[2]));
    float3 inv = make_float3(1.0f / b.x, 1.0f / b.y, 1.0f / b.z);
    CK(cudaMemcpyAsync(c->pos, c->h_pos, c->n * sizeof(float4), cudaMemcpyHostToDevice, c->stream));
    CK(cudaMemsetAsync(c->energy, 0, 4 * sizeof(double), c->stream));
    if (rebuild || box_changed) {
        if (build_neighbors(c, b, inv)) return 1;
    } else {
        k_permute<<<(c->n + 127) / 128, 128, 0, c->stream>>>(c->pos, nullptr, c->perm, c->spos, nullptr, c->n);
    }
    int blocks = (c->n + 255) / 256;
    k_nonbonded<<<unsigned((size_t(c->n) * kTpa + 255) / 256), 256, 0, c->stream>>>(c->spos, c->slj, c->n, b, inv, c->nbr, c->nbr_count, c->max_nbr, c->cutoff * c->cutoff, c->alpha,
                                               c->sforce, c->energy, want_energy);
    CK(cudaMemsetAsync(c->force, 0, 3 * size_t(c->n) * sizeof(float), c->stream));
    if (c->n_excl)
        k_exclusions<<<(c->n_excl + 255) / 256, 256, 0, c->stream>>>(c->pos, c->excl_pairs, c->n_excl, b, inv, c->alpha, c->force, c->energy,
                                                                       want_energy);
    // PME
    int3 K = make_int3(c->K[0], c->K[1], c->K[2]);
    size_t G = size_t(K.x) * K.y * K.z;
    if (box[0] != c->eterm_box[0] || box[1] != c->eterm_box[1] || box[2] != c->eterm_box[2]) {
        k_eterm<<<unsigned((G + 255) / 256), 256, 0, c->stream>>>(c->eterm, K, b, c->alpha, c->mod[0], c->mod[1], c->mod[2]);
        for (int d = 0; d < 3; ++d) c->eterm_box[d] = box[d];
    }
    CK(cudaMemsetAsync(c->qgrid, 0, G * sizeof(float), c->stream));
    k_spread<<<(c->n + 127) / 128, 128, 0, c->stream>>>(c->spos, c->n, b, K, c->qgrid);
    k_real_to_complex<<<unsigned((G + 255) / 256), 256, 0, c->stream>>>(c->qgrid, c->cgrid, G);
    if (fft3d(c, -1.0f)) return 1;
    k_convolve<<<unsigned((G + 255) / 256), 256, 0, c->stream>>>(c->cgrid, c->eterm, G, c->energy, want_energy);
    if (fft3d(c, +1.0f)) return 1;
    k_gather<<<(c->n + 127) / 128, 128, 0, c->stream>>>(c->spos, c->n, b, K, c->cgrid, c->sforce);
    k_unsort_forces<<<(c->n + 127) / 128, 128, 0, c->stream>>>(c->sforce, c->perm, c->force, c->n);
    CK(cudaGetLastError());
    CK(cudaMemcpyAsync(c->h_force, c->force, 3 * size_t(c->n) * sizeof(float), cudaMemcpyDeviceToHost, c->stream));
    if (want_energy) CK(cudaMemcpyAsync(c->h_energy, c->energy, 4 * sizeof(double), cudaMemcpyDeviceToHost, c->stream));
    return 0;
}

int vc_end(void* ctx, double* forces, double* energy) {
    Ctx* c = static_cast<Ctx*>(ctx);
    CK(cudaStreamSynchronize(c->stream));
    for (size_t k = 0; k < 3 * size_t(c->n); ++k) forces[k] += c->h_force[k];
    for (int k = 0; k < 4; ++k) energy[k] = c->want_energy ? c->h_energy[k] : 0;
    return 0;
}

const char* vc_device(void* ctx) { return ctx ? static_cast<Ctx*>(ctx)->device.c_str() : g_err; }

void vc_destroy(void* ctx) {
    Ctx* c = static_cast<Ctx*>(ctx);
    if (!c) return;
    void* ptrs[] = {c->pos,       c->lj,     c->force,      c->excl_start, c->excl,      c->excl_pairs, c->nbr,    c->nbr_count,
                    c->overflow,  c->spos,   c->slj,        c->sforce,     c->perm,      c->cell_of,    c->cell_count, c->cell_start,
                    c->cell_fill, c->energy, c->qgrid,      c->cgrid,      c->eterm,      c->perm_tmp};
    for (void* p : ptrs) cudaFree(p);
    for (int d = 0; d < 3; ++d) {
        cudaFree(c->mod[d]);
        cudaFree(c->twiddle[d]);
        cudaFree(c->radix_dev[d]);
    }
    cudaFreeHost(c->h_pos);
    cudaFreeHost(c->h_force);
    cudaStreamDestroy(c->stream);
    delete c;
}

}  // extern "C"
