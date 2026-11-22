// Prototype real-space D3(BJ) for the dispersion bake-off (plan task S6-D02). Not part of libloupmd.so: built on
// its own (tools/dev/d3_bakeoff.py) and called through ctypes, so candidates can be timed and checked against
// simple-dftd3 before the framework (S6-D03) exists.
//
// Method (Grimme et al. 2010, 2011; the tables are torch-dftd 0.5.1's, MIT): coordination numbers
// CN_i = sum_j 1 / (1 + exp(-k1 (rco_ij / r_ij - 1))) within cn_cut; per atom Gaussian weights of its reference
// CNs, w_ia = exp(-k3 (CN_i - CNref_a)^2) / sum; C6_ij = sum_ab w_ia w_jb C6ref_ab; C8 = 3 C6 Q_i Q_j;
// E = -sum_{i<j} s6 C6 / (r^6 + f^6) + s8 C8 / (r^8 + f^8), f = a1 sqrt(3 Q_i Q_j) + a2 (BJ). Forces: the direct
// r-derivative, then the CN chain rule dE/dCN_i dCN_i/dr in a third pass.
//
// Layout: one warp per receiving atom over a full neighbour set found by walking a grid of bins in fractional
// coordinates; a bin offset o along an axis is the bin (b + o) mod nb with the image floor((b + o) / nb), so every
// (atom, image) pair within the cutoff is visited once even when the cutoff exceeds half the cell. Pair arithmetic
// in float32 (relative vectors), sums in float64. Units inside: bohr and hartree.
#include <cuda_runtime.h>
#include <cub/cub.cuh>

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <vector>

namespace {

constexpr int MAXREF = 5;
constexpr double BOHR = 0.529177210903;          // A
constexpr double HARTREE = 27.211386245988;      // eV

struct Grid {
    int nb[3];          // bins per axis
    int reach[3];       // bin offsets to walk per axis
    float cell[9];      // rows: lattice vectors (bohr)
};

struct Params {
    float s6, s8, a1, a2;
    float k1, k3;
    float cut2, cn_cut2;   // bohr^2
    float lo2;             // bohr^2: pairs below this distance are left out (the shell of a split sum)
};

__device__ __forceinline__ void cart(const float* c, float fx, float fy, float fz, float& x, float& y, float& z) {
    x = fx * c[0] + fy * c[3] + fz * c[6];
    y = fx * c[1] + fy * c[4] + fz * c[7];
    z = fx * c[2] + fy * c[5] + fz * c[8];
}

// Walk the bins around atom i's bin; fn(j, dx, dy, dz, r2) for every (j, image) within cut2, j != i at image 0.
template <typename F>
__device__ __forceinline__ void walk(int i, const float3* __restrict__ pos, const float3* __restrict__ frac,
                                     const int* __restrict__ bin_start, const int* __restrict__ bin_atoms,
                                     const Grid& g, float cut2, int lane, F&& fn) {
    const float3 fi = frac[i];
    const float3 pi = pos[i];
    const int bx = min((int)(fi.x * g.nb[0]), g.nb[0] - 1);
    const int by = min((int)(fi.y * g.nb[1]), g.nb[1] - 1);
    const int bz = min((int)(fi.z * g.nb[2]), g.nb[2] - 1);
    for (int ox = -g.reach[0]; ox <= g.reach[0]; ++ox) {
        int tx = bx + ox, ix = (tx % g.nb[0] + g.nb[0]) % g.nb[0], sx = (tx - ix) / g.nb[0];
        for (int oy = -g.reach[1]; oy <= g.reach[1]; ++oy) {
            int ty = by + oy, iy = (ty % g.nb[1] + g.nb[1]) % g.nb[1], sy = (ty - iy) / g.nb[1];
            for (int oz = -g.reach[2]; oz <= g.reach[2]; ++oz) {
                int tz = bz + oz, iz = (tz % g.nb[2] + g.nb[2]) % g.nb[2], sz = (tz - iz) / g.nb[2];
                float shx, shy, shz;
                cart(g.cell, (float)sx, (float)sy, (float)sz, shx, shy, shz);
                const int b = (ix * g.nb[1] + iy) * g.nb[2] + iz;
                const int lo = bin_start[b], hi = bin_start[b + 1];
                const bool home = sx == 0 && sy == 0 && sz == 0;
                for (int k = lo + lane; k < hi; k += 32) {
                    const int j = bin_atoms[k];
                    if (home && j == i) continue;
                    const float3 pj = pos[j];
                    const float dx = pj.x + shx - pi.x, dy = pj.y + shy - pi.y, dz = pj.z + shz - pi.z;
                    const float r2 = dx * dx + dy * dy + dz * dz;
                    if (r2 < cut2) fn(j, dx, dy, dz, r2);
                }
            }
        }
    }
}

__device__ __forceinline__ double warp_sum(double v) {
    for (int o = 16; o; o >>= 1) v += __shfl_xor_sync(0xffffffffu, v, o);
    return v;
}

__global__ void bin_kernel(int n, const float3* __restrict__ frac, Grid g, int* __restrict__ bin_of) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= n) return;
    const float3 f = frac[i];
    const int bx = min((int)(f.x * g.nb[0]), g.nb[0] - 1);
    const int by = min((int)(f.y * g.nb[1]), g.nb[1] - 1);
    const int bz = min((int)(f.z * g.nb[2]), g.nb[2] - 1);
    bin_of[i] = (bx * g.nb[1] + by) * g.nb[2] + bz;
}

// Pass 1: coordination numbers.
__global__ void cn_kernel(int n, const float3* __restrict__ pos, const float3* __restrict__ frac,
                          const int* __restrict__ bin_start, const int* __restrict__ bin_atoms, Grid g, Params p,
                          const int* __restrict__ sp, const float* __restrict__ rcov, double* __restrict__ cn) {
    const int warp = (blockIdx.x * blockDim.x + threadIdx.x) >> 5, lane = threadIdx.x & 31;
    if (warp >= n) return;
    const int i = warp;
    const float ri = rcov[sp[i]];
    double acc = 0.0;
    walk(i, pos, frac, bin_start, bin_atoms, g, p.cn_cut2, lane, [&](int j, float, float, float, float r2) {
        const float r = sqrtf(r2);
        acc += (double)(1.0f / (1.0f + __expf(-p.k1 * ((ri + rcov[sp[j]]) / r - 1.0f))));
    });
    acc = warp_sum(acc);
    if (lane == 0) cn[i] = acc;
}

// Per atom: the normalised Gaussian weights of its reference CNs and their CN derivatives.
__global__ void weight_kernel(int n, const int* __restrict__ sp, const int* __restrict__ nref,
                              const float* __restrict__ cnref, float k3, const double* __restrict__ cn,
                              float* __restrict__ w, float* __restrict__ dw) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= n) return;
    const int s = sp[i], m = nref[s];
    double e[MAXREF], de[MAXREF], norm = 0.0, dnorm = 0.0;
    double best = 1e300;
    int arg = 0;
    for (int a = 0; a < m; ++a) {
        const double d = cn[i] - cnref[s * MAXREF + a];
        e[a] = exp(-k3 * d * d);
        de[a] = -2.0 * k3 * d * e[a];
        norm += e[a];
        dnorm += de[a];
        if (fabs(d) < best) { best = fabs(d); arg = a; }
    }
    for (int a = 0; a < MAXREF; ++a) {
        float wa = 0.0f, dwa = 0.0f;
        if (a < m) {
            if (norm > 1e-300) {
                wa = (float)(e[a] / norm);
                dwa = (float)((de[a] - e[a] / norm * dnorm) / norm);   // norm^2 underflows far from every reference
            } else {
                wa = a == arg ? 1.0f : 0.0f;    // every weight underflowed: the nearest reference
            }
        }
        w[i * MAXREF + a] = wa;
        dw[i * MAXREF + a] = dwa;
    }
}

// Pass 2: pair energies, direct forces and virial, and dE/dCN_i. Full neighbour set: each pair is seen from both
// ends, so energy and virial are halved; atom i's own force and its dE/dCN are complete.
__global__ void pair_kernel(int n, const float3* __restrict__ pos, const float3* __restrict__ frac,
                            const int* __restrict__ bin_start, const int* __restrict__ bin_atoms, Grid g, Params p,
                            const int* __restrict__ sp, int S, const float* __restrict__ c6ref,
                            const float* __restrict__ q, const float* __restrict__ w, const float* __restrict__ dw,
                            double* __restrict__ energy, double* __restrict__ force, double* __restrict__ virial,
                            double* __restrict__ dedcn) {
    const int warp = (blockIdx.x * blockDim.x + threadIdx.x) >> 5, lane = threadIdx.x & 31;
    if (warp >= n) return;
    const int i = warp, si = sp[i];
    float wi[MAXREF], dwi[MAXREF];
    for (int a = 0; a < MAXREF; ++a) { wi[a] = w[i * MAXREF + a]; dwi[a] = dw[i * MAXREF + a]; }
    const float qi = q[si];
    double e = 0.0, fx = 0.0, fy = 0.0, fz = 0.0, dcn = 0.0;
    double v[6] = {0, 0, 0, 0, 0, 0};
    walk(i, pos, frac, bin_start, bin_atoms, g, p.cut2, lane, [&](int j, float dx, float dy, float dz, float r2) {
        if (r2 < p.lo2) return;
        const int sj = sp[j];
        const float* tab = c6ref + ((size_t)si * S + sj) * MAXREF * MAXREF;
        float c6 = 0.0f, dc6i = 0.0f, dc6j = 0.0f;
        for (int a = 0; a < MAXREF; ++a) {
            float row = 0.0f, drow = 0.0f;
            for (int b = 0; b < MAXREF; ++b) {
                const float t = tab[a * MAXREF + b];
                row += t * w[j * MAXREF + b];
                drow += t * dw[j * MAXREF + b];
            }
            c6 += wi[a] * row;
            dc6i += dwi[a] * row;
            dc6j += wi[a] * drow;
        }
        (void)dc6j;
        const float qq = 3.0f * qi * q[sj];
        const float r0 = p.a1 * sqrtf(qq) + p.a2;
        const float r02 = r0 * r0, r06 = r02 * r02 * r02, r08 = r06 * r02;
        const float r4 = r2 * r2, r6 = r4 * r2, r8 = r6 * r2;
        const float t6 = 1.0f / (r6 + r06), t8 = 1.0f / (r8 + r08);
        // E_ij = -c6 (s6 t6 + s8 qq t8)
        const float g6 = p.s6 * t6 + p.s8 * qq * t8;
        const float eij = -c6 * g6;
        // dE/dr / r = c6 (s6 6 r^4 t6^2 + s8 qq 8 r^6 t8^2)
        const float de_r = c6 * (p.s6 * 6.0f * r4 * t6 * t6 + p.s8 * qq * 8.0f * r6 * t8 * t8);
        e += 0.5 * (double)eij;
        // force on i: -dE/dr_i = +dE/dr * (r_j - r_i)/r ... d = r_j - r_i
        fx += (double)(de_r * dx);
        fy += (double)(de_r * dy);
        fz += (double)(de_r * dz);
        // virial W = -sum_pairs d (x) dE/dd: half per side
        v[0] += 0.5 * (double)(de_r * dx * dx);
        v[1] += 0.5 * (double)(de_r * dx * dy);
        v[2] += 0.5 * (double)(de_r * dx * dz);
        v[3] += 0.5 * (double)(de_r * dy * dy);
        v[4] += 0.5 * (double)(de_r * dy * dz);
        v[5] += 0.5 * (double)(de_r * dz * dz);
        dcn += (double)(-dc6i * g6);       // dE_ij / dCN_i (the full pair energy: i's share of both directions)
    });
    e = warp_sum(e); fx = warp_sum(fx); fy = warp_sum(fy); fz = warp_sum(fz); dcn = warp_sum(dcn);
    for (int k = 0; k < 6; ++k) v[k] = warp_sum(v[k]);
    if (lane == 0) {
        atomicAdd(energy, e);
        force[3 * i + 0] += fx;
        force[3 * i + 1] += fy;
        force[3 * i + 2] += fz;
        for (int k = 0; k < 6; ++k) atomicAdd(&virial[k], v[k]);
        dedcn[i] = dcn;
    }
}

// Pass 3: the CN chain rule. dE/dr_ij through CN = (dE/dCN_i + dE/dCN_j) dcn_ij/dr.
__global__ void cn_force_kernel(int n, const float3* __restrict__ pos, const float3* __restrict__ frac,
                                const int* __restrict__ bin_start, const int* __restrict__ bin_atoms, Grid g,
                                Params p, const int* __restrict__ sp, const float* __restrict__ rcov,
                                const double* __restrict__ dedcn, double* __restrict__ force,
                                double* __restrict__ virial) {
    const int warp = (blockIdx.x * blockDim.x + threadIdx.x) >> 5, lane = threadIdx.x & 31;
    if (warp >= n) return;
    const int i = warp;
    const float ri = rcov[sp[i]];
    const float di = (float)dedcn[i];
    double fx = 0.0, fy = 0.0, fz = 0.0;
    double v[6] = {0, 0, 0, 0, 0, 0};
    walk(i, pos, frac, bin_start, bin_atoms, g, p.cn_cut2, lane, [&](int j, float dx, float dy, float dz, float r2) {
        const float r = sqrtf(r2);
        const float rco = ri + rcov[sp[j]];
        const float ex = __expf(-p.k1 * (rco / r - 1.0f));
        const float den = 1.0f + ex;
        // dcn/dr = -k1 rco / r^2 * ex / den^2
        const float dcdr = -p.k1 * rco / r2 * ex / (den * den);
        const float s = (di + (float)dedcn[j]) * dcdr / r;   // dE/dr / r for this pair through CN
        fx += (double)(s * dx);
        fy += (double)(s * dy);
        fz += (double)(s * dz);
        v[0] += 0.5 * (double)(s * dx * dx);
        v[1] += 0.5 * (double)(s * dx * dy);
        v[2] += 0.5 * (double)(s * dx * dz);
        v[3] += 0.5 * (double)(s * dy * dy);
        v[4] += 0.5 * (double)(s * dy * dz);
        v[5] += 0.5 * (double)(s * dz * dz);
    });
    fx = warp_sum(fx); fy = warp_sum(fy); fz = warp_sum(fz);
    for (int k = 0; k < 6; ++k) v[k] = warp_sum(v[k]);
    if (lane == 0) {
        force[3 * i + 0] += fx;
        force[3 * i + 1] += fy;
        force[3 * i + 2] += fz;
        for (int k = 0; k < 6; ++k) atomicAdd(&virial[k], v[k]);
    }
}

// ---- variant 1: atoms in bin order, a walk over rows of bins that are contiguous in memory, and per receiver the
// projections u_i(s) = w_i^T C6ref[s_i, s] (and du with dw_i) in shared memory, so a pair costs a 5-term dot product.
constexpr int MAXS = 8;
constexpr int WPB = 4;     // warps per block

// starts[b] = first sorted index of bin b; starts[nbins] = n
__global__ void bin_start_kernel(int n, int nbins, const int* __restrict__ keys, int* __restrict__ starts) {
    const int k = blockIdx.x * blockDim.x + threadIdx.x;
    if (k > n) return;
    const int prev = k == 0 ? -1 : keys[k - 1];
    const int cur = k == n ? nbins : keys[k];
    for (int b = prev + 1; b <= cur; ++b) starts[b] = k;
}

__global__ void gather_kernel(int n, const float3* __restrict__ pos, const int* __restrict__ sp,
                              const int* __restrict__ order, float4* __restrict__ ps) {
    const int k = blockIdx.x * blockDim.x + threadIdx.x;
    if (k >= n) return;
    const int a = order[k];
    const float3 p = pos[a];
    ps[k] = make_float4(p.x, p.y, p.z, __int_as_float(sp[a]));
}

template <typename F>
__device__ __forceinline__ void walk_rows(int k, int home, const float4* __restrict__ ps,
                                          const int* __restrict__ bin_start, const Grid& g, float cut2, int lane,
                                          F&& fn) {
    const float4 pi = ps[k];
    const int nb1 = g.nb[1], nb2 = g.nb[2];
    const int bz = home % nb2, by = (home / nb2) % nb1, bx = home / (nb1 * nb2);
    for (int ox = -g.reach[0]; ox <= g.reach[0]; ++ox) {
        const int tx = bx + ox, ix = (tx % g.nb[0] + g.nb[0]) % g.nb[0], sx = (tx - ix) / g.nb[0];
        for (int oy = -g.reach[1]; oy <= g.reach[1]; ++oy) {
            const int ty = by + oy, iy = (ty % nb1 + nb1) % nb1, sy = (ty - iy) / nb1;
            int tz = bz - g.reach[2];
            while (tz <= bz + g.reach[2]) {
                const int iz = (tz % nb2 + nb2) % nb2, sz = (tz - iz) / nb2;
                const int len = min(bz + g.reach[2] - tz, nb2 - 1 - iz) + 1;
                float shx, shy, shz;
                cart(g.cell, (float)sx, (float)sy, (float)sz, shx, shy, shz);
                const float ox_ = shx - pi.x, oy_ = shy - pi.y, oz_ = shz - pi.z;
                const int b0 = (ix * nb1 + iy) * nb2 + iz;
                const int lo = bin_start[b0], hi = bin_start[b0 + len];
                const bool home_img = sx == 0 && sy == 0 && sz == 0;
                for (int j = lo + lane; j < hi; j += 32) {
                    if (home_img && j == k) continue;
                    const float4 pj = ps[j];
                    const float dx = pj.x + ox_, dy = pj.y + oy_, dz = pj.z + oz_;
                    const float r2 = dx * dx + dy * dy + dz * dz;
                    if (r2 < cut2) fn(j, __float_as_int(pj.w), dx, dy, dz, r2);
                }
                tz += len;
            }
        }
    }
}

__global__ void cn_kernel_s(int n, const float4* __restrict__ ps, const int* __restrict__ keys,
                            const int* __restrict__ bin_start, Grid g, Params p, const float* __restrict__ rcov,
                            double* __restrict__ cn) {
    const int k = (blockIdx.x * blockDim.x + threadIdx.x) >> 5, lane = threadIdx.x & 31;
    if (k >= n) return;
    const float ri = rcov[__float_as_int(ps[k].w)];
    float acc = 0.0f;   // per lane: a few hundred terms below 1
    double tot = 0.0;
    int cnt = 0;
    walk_rows(k, keys[k], ps, bin_start, g, p.cn_cut2, lane, [&](int, int sj, float, float, float, float r2) {
        acc += 1.0f / (1.0f + __expf(-p.k1 * ((ri + rcov[sj]) * rsqrtf(r2) - 1.0f)));
        if (++cnt == 64) { tot += acc; acc = 0.0f; cnt = 0; }
    });
    tot = warp_sum(tot + acc);
    if (lane == 0) cn[k] = tot;
}

__global__ void weight_kernel_s(int n, const float4* __restrict__ ps, const int* __restrict__ nref,
                                const float* __restrict__ cnref, float k3, const double* __restrict__ cn,
                                float* __restrict__ w, float* __restrict__ dw) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= n) return;
    const int s = __float_as_int(ps[i].w), m = nref[s];
    double e[MAXREF], de[MAXREF], norm = 0.0, dnorm = 0.0, best = 1e300;
    int arg = 0;
    for (int a = 0; a < m; ++a) {
        const double d = cn[i] - cnref[s * MAXREF + a];
        e[a] = exp(-k3 * d * d);
        de[a] = -2.0 * k3 * d * e[a];
        norm += e[a];
        dnorm += de[a];
        if (fabs(d) < best) { best = fabs(d); arg = a; }
    }
    for (int a = 0; a < 8; ++a) {
        float wa = 0.0f, dwa = 0.0f;
        if (a < m) {
            if (norm > 1e-300) {
                wa = (float)(e[a] / norm);
                dwa = (float)((de[a] - e[a] / norm * dnorm) / norm);   // norm^2 underflows far from every reference
            } else {
                wa = a == arg ? 1.0f : 0.0f;
            }
        }
        w[i * 8 + a] = wa;
        if (a < MAXREF) dw[i * MAXREF + a] = dwa;
    }
}

__global__ void __launch_bounds__(WPB * 32) pair_kernel_s(
        int n, const float4* __restrict__ ps, const int* __restrict__ keys, const int* __restrict__ bin_start, Grid g,
        Params p, int S, const float* __restrict__ c6ref, const float* __restrict__ q, const float* __restrict__ w,
        const float* __restrict__ dw, double* __restrict__ energy, double* __restrict__ force,
        double* __restrict__ virial, double* __restrict__ dedcn) {
    __shared__ float s_u[WPB][MAXS][MAXREF], s_du[WPB][MAXS][MAXREF], s_q[MAXS];
    const int wib = threadIdx.x >> 5, lane = threadIdx.x & 31;
    const int k = blockIdx.x * WPB + wib;
    if (threadIdx.x < S) s_q[threadIdx.x] = q[threadIdx.x];
    if (k < n) {
        const int si = __float_as_int(ps[k].w);
        for (int t = lane; t < S * MAXREF; t += 32) {
            const int s = t / MAXREF, b = t % MAXREF;
            const float* tab = c6ref + ((size_t)si * S + s) * MAXREF * MAXREF;
            float u = 0.0f, du = 0.0f;
            for (int a = 0; a < MAXREF; ++a) {
                u += w[k * 8 + a] * tab[a * MAXREF + b];
                du += dw[k * MAXREF + a] * tab[a * MAXREF + b];
            }
            s_u[wib][s][b] = u;
            s_du[wib][s][b] = du;
        }
    }
    __syncthreads();
    if (k >= n) return;
    const float qi = s_q[__float_as_int(ps[k].w)];
    double e = 0.0, fx = 0.0, fy = 0.0, fz = 0.0, dcn = 0.0;
    double v[6] = {0, 0, 0, 0, 0, 0};
    walk_rows(k, keys[k], ps, bin_start, g, p.cut2, lane, [&](int j, int sj, float dx, float dy, float dz, float r2) {
        if (r2 < p.lo2) return;
        const float4 w0 = *reinterpret_cast<const float4*>(w + 8 * (size_t)j);
        const float w4 = w[8 * (size_t)j + 4];
        const float* u = s_u[wib][sj];
        const float* du = s_du[wib][sj];
        const float c6 = u[0] * w0.x + u[1] * w0.y + u[2] * w0.z + u[3] * w0.w + u[4] * w4;
        const float dc6i = du[0] * w0.x + du[1] * w0.y + du[2] * w0.z + du[3] * w0.w + du[4] * w4;
        const float qq = 3.0f * qi * s_q[sj];
        const float r0 = p.a1 * sqrtf(qq) + p.a2;
        const float r02 = r0 * r0, r06 = r02 * r02 * r02, r08 = r06 * r02;
        const float r4 = r2 * r2, r6 = r4 * r2, r8 = r6 * r2;
        const float t6 = 1.0f / (r6 + r06), t8 = 1.0f / (r8 + r08);
        const float g6 = p.s6 * t6 + p.s8 * qq * t8;
        const float de_r = c6 * (p.s6 * 6.0f * r4 * t6 * t6 + p.s8 * qq * 8.0f * r6 * t8 * t8);
        e += (double)(-0.5f * c6 * g6);
        fx += (double)(de_r * dx);
        fy += (double)(de_r * dy);
        fz += (double)(de_r * dz);
        const float h = 0.5f * de_r;
        v[0] += (double)(h * dx * dx);
        v[1] += (double)(h * dx * dy);
        v[2] += (double)(h * dx * dz);
        v[3] += (double)(h * dy * dy);
        v[4] += (double)(h * dy * dz);
        v[5] += (double)(h * dz * dz);
        dcn += (double)(-dc6i * g6);
    });
    e = warp_sum(e); fx = warp_sum(fx); fy = warp_sum(fy); fz = warp_sum(fz); dcn = warp_sum(dcn);
    for (int c = 0; c < 6; ++c) v[c] = warp_sum(v[c]);
    if (lane == 0) {
        atomicAdd(energy, e);
        force[3 * k + 0] = fx;
        force[3 * k + 1] = fy;
        force[3 * k + 2] = fz;
        for (int c = 0; c < 6; ++c) atomicAdd(&virial[c], v[c]);
        dedcn[k] = dcn;
    }
}

__global__ void cn_force_kernel_s(int n, const float4* __restrict__ ps, const int* __restrict__ keys,
                                  const int* __restrict__ bin_start, Grid g, Params p, const float* __restrict__ rcov,
                                  const double* __restrict__ dedcn, const int* __restrict__ order,
                                  const double* __restrict__ force_s, double* __restrict__ force,
                                  double* __restrict__ virial) {
    const int k = (blockIdx.x * blockDim.x + threadIdx.x) >> 5, lane = threadIdx.x & 31;
    if (k >= n) return;
    const float ri = rcov[__float_as_int(ps[k].w)];
    const float di = (float)dedcn[k];
    double fx = 0.0, fy = 0.0, fz = 0.0;
    double v[6] = {0, 0, 0, 0, 0, 0};
    walk_rows(k, keys[k], ps, bin_start, g, p.cn_cut2, lane, [&](int j, int sj, float dx, float dy, float dz, float r2) {
        const float ir = rsqrtf(r2);
        const float rco = ri + rcov[sj];
        const float ex = __expf(-p.k1 * (rco * ir - 1.0f));
        const float den = 1.0f + ex;
        const float s = (di + (float)dedcn[j]) * (-p.k1 * rco * ir * ir * ex / (den * den)) * ir;
        if (s == 0.0f) return;
        fx += (double)(s * dx);
        fy += (double)(s * dy);
        fz += (double)(s * dz);
        const float h = 0.5f * s;
        v[0] += (double)(h * dx * dx);
        v[1] += (double)(h * dx * dy);
        v[2] += (double)(h * dx * dz);
        v[3] += (double)(h * dy * dy);
        v[4] += (double)(h * dy * dz);
        v[5] += (double)(h * dz * dz);
    });
    fx = warp_sum(fx); fy = warp_sum(fy); fz = warp_sum(fz);
    for (int c = 0; c < 6; ++c) v[c] = warp_sum(v[c]);
    if (lane == 0) {
        const int a = order[k];
        force[3 * a + 0] = force_s[3 * k + 0] + fx;
        force[3 * a + 1] = force_s[3 * k + 1] + fy;
        force[3 * a + 2] = force_s[3 * k + 2] + fz;
        for (int c = 0; c < 6; ++c) atomicAdd(&virial[c], v[c]);
    }
}

__global__ void scatter_cn_kernel(int n, const int* __restrict__ order, const double* __restrict__ cn_s,
                                  double* __restrict__ cn) {
    const int k = blockIdx.x * blockDim.x + threadIdx.x;
    if (k < n) cn[order[k]] = cn_s[k];
}

#define CK(x) do { cudaError_t e_ = (x); if (e_ != cudaSuccess) { \
    std::fprintf(stderr, "d3_proto: %s (%s:%d)\n", cudaGetErrorString(e_), __FILE__, __LINE__); return -1; } } while (0)

}  // namespace

extern "C" {

// One evaluation. positions [n,3] A, cell [3,3] A (rows), species [n] in 0..S-1; tables per species: nref [S],
// cnref [S,5], rcov [S] (bohr, k2 included), q [S] (the r2r4 factor), c6ref [S,S,5,5] (hartree bohr^6).
// cut, cut_lo (pairs closer than cut_lo are left out) and cn_cut in bohr. Outputs: energy eV, forces [n,3] eV/A, virial [6] eV (xx xy xz yy yz zz; stress =
// virial / V: the virial here is dE/d strain), times_ms [4]: bins, CN + weights, pairs, CN forces. repeat > 1 runs the passes that many times and
// reports the mean times. cn_out [n] (may be null): the coordination numbers. variant 0: atom order, one bin per
// inner loop, the 5x5 C6 contraction per pair; 1: bin order, rows of bins, per-receiver C6 projections.
int d3_eval(int n, const double* positions, const double* cell, const int* species, int S, const int* nref,
            const double* cnref, const double* rcov, const double* q, const double* c6ref, double s6, double s8,
            double a1, double a2, double cut, double cut_lo, double cn_cut, int repeat, double* energy_ev, double* forces,
            double* virial_ev, double* times_ms, double* cn_out, int variant) {
    // host: fractional coordinates, bohr positions, the grid
    double inv[9], c[9];
    for (int k = 0; k < 9; ++k) c[k] = cell[k] / BOHR;
    const double det = c[0] * (c[4] * c[8] - c[5] * c[7]) - c[1] * (c[3] * c[8] - c[5] * c[6]) +
                       c[2] * (c[3] * c[7] - c[4] * c[6]);
    inv[0] = (c[4] * c[8] - c[5] * c[7]) / det; inv[1] = (c[2] * c[7] - c[1] * c[8]) / det;
    inv[2] = (c[1] * c[5] - c[2] * c[4]) / det; inv[3] = (c[5] * c[6] - c[3] * c[8]) / det;
    inv[4] = (c[0] * c[8] - c[2] * c[6]) / det; inv[5] = (c[2] * c[3] - c[0] * c[5]) / det;
    inv[6] = (c[3] * c[7] - c[4] * c[6]) / det; inv[7] = (c[1] * c[6] - c[0] * c[7]) / det;
    inv[8] = (c[0] * c[4] - c[1] * c[3]) / det;
    const double rmax = cut > cn_cut ? cut : cn_cut;
    Grid g{};
    for (int k = 0; k < 9; ++k) g.cell[k] = (float)c[k];
    for (int ax = 0; ax < 3; ++ax) {
        // the height of the cell along axis ax: V / |a_b x a_c|
        const double* u = c + 3 * ((ax + 1) % 3);
        const double* w = c + 3 * ((ax + 2) % 3);
        const double cx = u[1] * w[2] - u[2] * w[1], cy = u[2] * w[0] - u[0] * w[2], cz = u[0] * w[1] - u[1] * w[0];
        const double h = std::fabs(det) / std::sqrt(cx * cx + cy * cy + cz * cz);
        int nb = (int)(h / (rmax / 4.0));          // bins of at least a quarter of the cutoff
        if (nb < 1) nb = 1;
        if (nb > 64) nb = 64;
        g.nb[ax] = nb;
        g.reach[ax] = (int)std::ceil(rmax / (h / nb));
    }
    std::vector<float3> hp(n), hf(n);
    for (int i = 0; i < n; ++i) {
        double x = positions[3 * i] / BOHR, y = positions[3 * i + 1] / BOHR, z = positions[3 * i + 2] / BOHR;
        double f[3] = {x * inv[0] + y * inv[3] + z * inv[6], x * inv[1] + y * inv[4] + z * inv[7],
                       x * inv[2] + y * inv[5] + z * inv[8]};
        for (double& v : f) v -= std::floor(v);
        hf[i] = make_float3((float)f[0], (float)f[1], (float)f[2]);
        hp[i] = make_float3((float)(f[0] * c[0] + f[1] * c[3] + f[2] * c[6]),
                            (float)(f[0] * c[1] + f[1] * c[4] + f[2] * c[7]),
                            (float)(f[0] * c[2] + f[1] * c[5] + f[2] * c[8]));
    }
    const int nbins = g.nb[0] * g.nb[1] * g.nb[2];
    std::vector<float> h_cnref(S * MAXREF), h_rcov(S), h_q(S), h_c6((size_t)S * S * 25);
    for (int k = 0; k < S * MAXREF; ++k) h_cnref[k] = (float)cnref[k];
    for (int k = 0; k < S; ++k) { h_rcov[k] = (float)rcov[k]; h_q[k] = (float)q[k]; }
    for (size_t k = 0; k < h_c6.size(); ++k) h_c6[k] = (float)c6ref[k];

    float3 *d_pos, *d_frac;
    int *d_sp, *d_nref, *d_bin_of, *d_order, *d_sorted_bins, *d_bin_atoms, *d_bin_start, *d_iota;
    float *d_cnref, *d_rcov, *d_q, *d_c6, *d_w, *d_dw;
    double *d_cn, *d_dedcn, *d_force, *d_e, *d_vir;
    CK(cudaMalloc(&d_pos, n * sizeof(float3)));
    CK(cudaMalloc(&d_frac, n * sizeof(float3)));
    CK(cudaMalloc(&d_sp, n * sizeof(int)));
    CK(cudaMalloc(&d_nref, S * sizeof(int)));
    CK(cudaMalloc(&d_bin_of, n * sizeof(int)));
    CK(cudaMalloc(&d_sorted_bins, n * sizeof(int)));
    CK(cudaMalloc(&d_order, n * sizeof(int)));
    CK(cudaMalloc(&d_iota, n * sizeof(int)));
    CK(cudaMalloc(&d_bin_atoms, n * sizeof(int)));
    CK(cudaMalloc(&d_bin_start, (nbins + 1) * sizeof(int)));
    CK(cudaMalloc(&d_cnref, S * MAXREF * sizeof(float)));
    CK(cudaMalloc(&d_rcov, S * sizeof(float)));
    CK(cudaMalloc(&d_q, S * sizeof(float)));
    CK(cudaMalloc(&d_c6, h_c6.size() * sizeof(float)));
    CK(cudaMalloc(&d_w, (size_t)n * MAXREF * sizeof(float)));
    CK(cudaMalloc(&d_dw, (size_t)n * MAXREF * sizeof(float)));
    CK(cudaMalloc(&d_cn, n * sizeof(double)));
    CK(cudaMalloc(&d_dedcn, n * sizeof(double)));
    CK(cudaMalloc(&d_force, 3 * n * sizeof(double)));
    CK(cudaMalloc(&d_e, sizeof(double)));
    CK(cudaMalloc(&d_vir, 6 * sizeof(double)));
    CK(cudaMemcpy(d_pos, hp.data(), n * sizeof(float3), cudaMemcpyHostToDevice));
    CK(cudaMemcpy(d_frac, hf.data(), n * sizeof(float3), cudaMemcpyHostToDevice));
    CK(cudaMemcpy(d_sp, species, n * sizeof(int), cudaMemcpyHostToDevice));
    CK(cudaMemcpy(d_nref, nref, S * sizeof(int), cudaMemcpyHostToDevice));
    CK(cudaMemcpy(d_cnref, h_cnref.data(), S * MAXREF * sizeof(float), cudaMemcpyHostToDevice));
    CK(cudaMemcpy(d_rcov, h_rcov.data(), S * sizeof(float), cudaMemcpyHostToDevice));
    CK(cudaMemcpy(d_q, h_q.data(), S * sizeof(float), cudaMemcpyHostToDevice));
    CK(cudaMemcpy(d_c6, h_c6.data(), h_c6.size() * sizeof(float), cudaMemcpyHostToDevice));
    std::vector<int> iota(n);
    for (int i = 0; i < n; ++i) iota[i] = i;
    CK(cudaMemcpy(d_iota, iota.data(), n * sizeof(int), cudaMemcpyHostToDevice));
    size_t sort_bytes = 0;
    cub::DeviceRadixSort::SortPairs(nullptr, sort_bytes, d_bin_of, d_sorted_bins, d_iota, d_bin_atoms, n);
    void* d_tmp;
    CK(cudaMalloc(&d_tmp, sort_bytes));
    if (variant == 1 && S > MAXS) {
        std::fprintf(stderr, "d3_proto: variant 1 takes at most %d species\n", MAXS);
        return -1;
    }
    float4* d_ps;
    float* d_w8;
    double *d_cn_s, *d_force_s;
    CK(cudaMalloc(&d_ps, n * sizeof(float4)));
    CK(cudaMalloc(&d_w8, (size_t)n * 8 * sizeof(float)));
    CK(cudaMalloc(&d_cn_s, n * sizeof(double)));
    CK(cudaMalloc(&d_force_s, 3 * (size_t)n * sizeof(double)));

    Params p{};
    p.s6 = (float)s6; p.s8 = (float)s8; p.a1 = (float)a1; p.a2 = (float)a2;
    p.k1 = 16.0f; p.k3 = 4.0f;
    p.cut2 = (float)(cut * cut); p.cn_cut2 = (float)(cn_cut * cn_cut);
    p.lo2 = (float)(cut_lo * cut_lo);

    cudaEvent_t ev[5];
    for (auto& e : ev) CK(cudaEventCreate(&e));
    double t[4] = {0, 0, 0, 0};
    const int warps_per_block = 4, threads = 32 * warps_per_block, grid_w = (n + warps_per_block - 1) / warps_per_block;
    if (repeat < 1) repeat = 1;
    for (int rep = 0; rep < repeat + 1; ++rep) {          // the first round warms up and is not timed
        CK(cudaEventRecord(ev[0]));
        bin_kernel<<<(n + 255) / 256, 256>>>(n, d_frac, g, d_bin_of);
        cub::DeviceRadixSort::SortPairs(d_tmp, sort_bytes, d_bin_of, d_sorted_bins, d_iota, d_bin_atoms, n);
        if (variant == 1) {
            bin_start_kernel<<<(n + 256) / 256, 256>>>(n, nbins, d_sorted_bins, d_bin_start);
            gather_kernel<<<(n + 255) / 256, 256>>>(n, d_pos, d_sp, d_bin_atoms, d_ps);
            CK(cudaMemsetAsync(d_e, 0, sizeof(double)));
            CK(cudaMemsetAsync(d_vir, 0, 6 * sizeof(double)));
            CK(cudaEventRecord(ev[1]));
            cn_kernel_s<<<grid_w, threads>>>(n, d_ps, d_sorted_bins, d_bin_start, g, p, d_rcov, d_cn_s);
            weight_kernel_s<<<(n + 127) / 128, 128>>>(n, d_ps, d_nref, d_cnref, p.k3, d_cn_s, d_w8, d_dw);
            CK(cudaEventRecord(ev[2]));
            pair_kernel_s<<<grid_w, threads>>>(n, d_ps, d_sorted_bins, d_bin_start, g, p, S, d_c6, d_q, d_w8, d_dw,
                                               d_e, d_force_s, d_vir, d_dedcn);
            CK(cudaEventRecord(ev[3]));
            cn_force_kernel_s<<<grid_w, threads>>>(n, d_ps, d_sorted_bins, d_bin_start, g, p, d_rcov, d_dedcn,
                                                   d_bin_atoms, d_force_s, d_force, d_vir);
            CK(cudaEventRecord(ev[4]));
            scatter_cn_kernel<<<(n + 255) / 256, 256>>>(n, d_bin_atoms, d_cn_s, d_cn);
        } else {
        // bin starts: lower bound of each bin in the sorted keys
        {
            std::vector<int> keys(n), starts(nbins + 1, 0);
            CK(cudaMemcpy(keys.data(), d_sorted_bins, n * sizeof(int), cudaMemcpyDeviceToHost));
            for (int i = 0; i < n; ++i) starts[keys[i] + 1]++;
            for (int b = 0; b < nbins; ++b) starts[b + 1] += starts[b];
            CK(cudaMemcpy(d_bin_start, starts.data(), (nbins + 1) * sizeof(int), cudaMemcpyHostToDevice));
        }
        CK(cudaMemset(d_force, 0, 3 * n * sizeof(double)));
        CK(cudaMemset(d_e, 0, sizeof(double)));
        CK(cudaMemset(d_vir, 0, 6 * sizeof(double)));
        CK(cudaEventRecord(ev[1]));
        cn_kernel<<<grid_w, threads>>>(n, d_pos, d_frac, d_bin_start, d_bin_atoms, g, p, d_sp, d_rcov, d_cn);
        weight_kernel<<<(n + 127) / 128, 128>>>(n, d_sp, d_nref, d_cnref, p.k3, d_cn, d_w, d_dw);
        CK(cudaEventRecord(ev[2]));
        pair_kernel<<<grid_w, threads>>>(n, d_pos, d_frac, d_bin_start, d_bin_atoms, g, p, d_sp, S, d_c6, d_q, d_w,
                                         d_dw, d_e, d_force, d_vir, d_dedcn);
        CK(cudaEventRecord(ev[3]));
        cn_force_kernel<<<grid_w, threads>>>(n, d_pos, d_frac, d_bin_start, d_bin_atoms, g, p, d_sp, d_rcov,
                                             d_dedcn, d_force, d_vir);
        CK(cudaEventRecord(ev[4]));
        }
        CK(cudaEventSynchronize(ev[4]));
        CK(cudaGetLastError());
        if (rep == 0) continue;
        for (int k = 0; k < 4; ++k) {
            float ms = 0.0f;
            CK(cudaEventElapsedTime(&ms, ev[k], ev[k + 1]));
            t[k] += ms;
        }
    }
    double e = 0.0, vir[6];
    std::vector<double> f(3 * n);
    CK(cudaMemcpy(&e, d_e, sizeof(double), cudaMemcpyDeviceToHost));
    CK(cudaMemcpy(f.data(), d_force, 3 * n * sizeof(double), cudaMemcpyDeviceToHost));
    CK(cudaMemcpy(vir, d_vir, 6 * sizeof(double), cudaMemcpyDeviceToHost));
    *energy_ev = e * HARTREE;
    for (int k = 0; k < 3 * n; ++k) forces[k] = f[k] * HARTREE / BOHR;
    for (int k = 0; k < 6; ++k) virial_ev[k] = vir[k] * HARTREE;
    for (int k = 0; k < 4; ++k) times_ms[k] = t[k] / repeat;
    if (cn_out) CK(cudaMemcpy(cn_out, d_cn, n * sizeof(double), cudaMemcpyDeviceToHost));
    for (auto& ev_ : ev) cudaEventDestroy(ev_);
    void* bufs[] = {d_pos, d_frac, d_sp, d_nref, d_bin_of, d_order, d_sorted_bins, d_bin_atoms, d_bin_start, d_iota,
                    d_cnref, d_rcov, d_q, d_c6, d_w, d_dw, d_cn, d_dedcn, d_force, d_e, d_vir, d_tmp,
                    d_ps, d_w8, d_cn_s, d_force_s};
    for (void* b : bufs) cudaFree(b);
    return 0;
}

}  // extern "C"
