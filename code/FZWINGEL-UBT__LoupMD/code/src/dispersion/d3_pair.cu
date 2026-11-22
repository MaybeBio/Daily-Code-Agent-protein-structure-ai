// Real-space two-body D3 (plan task S6-D04; design docs/design/dispersion.md; the S6-D02 bake-off's variant 1).
//
// Method (Grimme, Antony, Ehrlich, Krieg 2010; Grimme, Ehrlich, Goerigk 2011; Smith et al. 2016 for the modified
// dampings): coordination numbers CN_i = sum_j 1 / (1 + exp(-k1 (rco_ij / r_ij - 1))) within cn_cut; per atom the
// normalised Gaussian weights of its reference CNs, w_ia = exp(-k3 (CN_i - CNref_a)^2) / sum; C6_ij = sum_ab w_ia
// w_jb C6ref_ab; C8 = 3 C6 Q_i Q_j. E = -sum_{i<j} (s6 C6 g6(r) + s8 C8 g8(r)) S(r), with
//   BJ, BJM:   g_n = 1 / (r^n + f^n),  f = a1 sqrt(3 Q_i Q_j) + a2
//   zero:      g_n = d_n / r^n,  d_n = 1 / (1 + 6 (rs_n R0_ij / r)^alpha_n)
//   zerom:     g_n = d_n / r^n,  d_n = 1 / (1 + 6 (r / (rs_n R0_ij) + beta R0_ij)^-alpha_n)
// alpha_6 = alpha, alpha_8 = alpha + 2, and S(r) = 1, or with smoothing a quintic switch from 1 at cut - w to 0 at
// cut. Forces: the direct r-derivative, then the CN chain rule dE/dCN_i dCN_i/dr in a third pass.
//
// Layout: atoms sorted by bin of a grid in fractional coordinates; one warp per receiver walks the rows of bins
// within reach, a bin offset o along an axis being bin (b + o) mod nb at image floor((b + o) / nb), so every (atom,
// image) pair within the cutoff is visited once even when the cutoff exceeds the cell. The grid's bin counts are
// fixed by prepare(); the cell, its inverse and the reach are computed on the device at every evaluation, so a
// captured evaluation stays exact when the cell changes. Pair arithmetic in float32 on relative vectors, sums in
// float64. Units inside: bohr and hartree.
#include "dispersion/term.hpp"
#include "loupmd.h"

#include <cub/cub.cuh>
#include <cufft.h>
#include <dlfcn.h>

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace loup::dispersion {
namespace {

constexpr int MAXREF = kMaxRef;
constexpr int WSTRIDE = 8;       // per-atom weight row: a float4 and one more
constexpr int WPB = 4;           // warps per block in the walking kernels
constexpr int MAXBINS = 64;      // per axis
#ifndef D3_FLUSH
#define D3_FLUSH 32              // pairs per lane summed in float32 before they go to the float64 totals
#endif
constexpr double BOHR = 0.529177210903;          // A
constexpr double HARTREE = 27.211386245988;      // eV
constexpr float K1 = 16.0f, K3 = 4.0f;

struct Grid {
    int nb[3];
    int reach[3];       // bins along each axis that cover rmax
    float hb[3];        // the bins' heights (bohr): a pass with a shorter cutoff walks fewer
    float cell[9];      // rows, bohr
    double inv[9];      // inverse of the cell in bohr
    double vol;         // bohr^3
};

struct PairParams {
    float s6, s8, a1, a2, rs6, rs8, alpha6, alpha8, beta;
    float cut2, cn_cut2;
    float sw_on, sw_width;      // switch on [sw_on, sw_on + sw_width]; width 0: none
    float ew_b2;                // the split sum's beta^2 (1/bohr^2): the pair kernel subtracts the smooth part; 0: none
};

#define CK(x) do { cudaError_t e_ = (x); if (e_ != cudaSuccess) \
    throw std::runtime_error(std::string("D3: ") + cudaGetErrorString(e_) + " at " + __FILE__ + ":" + \
                             std::to_string(__LINE__)); } while (0)

__device__ __forceinline__ double warp_sum(double v) {
    for (int o = 16; o; o >>= 1) v += __shfl_xor_sync(0xffffffffu, v, o);
    return v;
}

// One thread: the cell in bohr, its inverse, and how many bins along each axis cover rmax.
__global__ void grid_kernel(const double* __restrict__ cell_A, int nb0, int nb1, int nb2, double rmax,
                            Grid* __restrict__ g) {
    double c[9];
    for (int k = 0; k < 9; ++k) c[k] = cell_A[k] / BOHR;
    const double det = c[0] * (c[4] * c[8] - c[5] * c[7]) - c[1] * (c[3] * c[8] - c[5] * c[6]) +
                       c[2] * (c[3] * c[7] - c[4] * c[6]);
    double inv[9];
    inv[0] = (c[4] * c[8] - c[5] * c[7]) / det; inv[1] = (c[2] * c[7] - c[1] * c[8]) / det;
    inv[2] = (c[1] * c[5] - c[2] * c[4]) / det; inv[3] = (c[5] * c[6] - c[3] * c[8]) / det;
    inv[4] = (c[0] * c[8] - c[2] * c[6]) / det; inv[5] = (c[2] * c[3] - c[0] * c[5]) / det;
    inv[6] = (c[3] * c[7] - c[4] * c[6]) / det; inv[7] = (c[1] * c[6] - c[0] * c[7]) / det;
    inv[8] = (c[0] * c[4] - c[1] * c[3]) / det;
    const int nb[3] = {nb0, nb1, nb2};
    for (int ax = 0; ax < 3; ++ax) {
        const double* u = c + 3 * ((ax + 1) % 3);
        const double* w = c + 3 * ((ax + 2) % 3);
        const double cx = u[1] * w[2] - u[2] * w[1], cy = u[2] * w[0] - u[0] * w[2], cz = u[0] * w[1] - u[1] * w[0];
        const double h = fabs(det) / sqrt(cx * cx + cy * cy + cz * cz);       // the cell's height along ax
        g->nb[ax] = nb[ax];
        g->reach[ax] = (int)ceil(rmax / (h / nb[ax]) * (1.0 + 1e-6));        // float32 pair vectors: a margin
        g->hb[ax] = (float)(h / nb[ax]);
    }
    for (int k = 0; k < 9; ++k) { g->cell[k] = (float)c[k]; g->inv[k] = inv[k]; }
    g->vol = fabs(det);
}

// Per atom: wrap into the cell, its bin, its wrapped position (bohr).
__global__ void wrap_kernel(int n, const double* __restrict__ pos_A, const Grid* __restrict__ gp,
                            float3* __restrict__ pw, int* __restrict__ bin_of) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= n) return;
    const Grid& g = *gp;
    const double x = pos_A[3 * i] / BOHR, y = pos_A[3 * i + 1] / BOHR, z = pos_A[3 * i + 2] / BOHR;
    double f[3] = {x * g.inv[0] + y * g.inv[3] + z * g.inv[6], x * g.inv[1] + y * g.inv[4] + z * g.inv[7],
                   x * g.inv[2] + y * g.inv[5] + z * g.inv[8]};
    int b[3];
    for (int a = 0; a < 3; ++a) {
        f[a] -= floor(f[a]);
        if (f[a] >= 1.0) f[a] = 0.0;
        b[a] = min((int)(f[a] * g.nb[a]), g.nb[a] - 1);
    }
    bin_of[i] = (b[0] * g.nb[1] + b[1]) * g.nb[2] + b[2];
    // the wrapped Cartesian position from the float64 fractional one
    double cx = 0, cy = 0, cz = 0;
    for (int a = 0; a < 3; ++a) {
        cx += f[a] * (double)g.cell[3 * a];
        cy += f[a] * (double)g.cell[3 * a + 1];
        cz += f[a] * (double)g.cell[3 * a + 2];
    }
    pw[i] = make_float3((float)cx, (float)cy, (float)cz);
}

// starts[b] = first sorted index of bin b; starts[nbins] = n
__global__ void bin_start_kernel(int n, int nbins, const int* __restrict__ keys, int* __restrict__ starts) {
    const int k = blockIdx.x * blockDim.x + threadIdx.x;
    if (k > n) return;
    const int prev = k == 0 ? -1 : keys[k - 1];
    const int cur = k == n ? nbins : keys[k];
    for (int b = prev + 1; b <= cur; ++b) starts[b] = k;
}

__global__ void gather_kernel(int n, const float3* __restrict__ pw, const int* __restrict__ sp,
                              const int* __restrict__ order, float4* __restrict__ ps) {
    const int k = blockIdx.x * blockDim.x + threadIdx.x;
    if (k >= n) return;
    const int a = order[k];
    const float3 p = pw[a];
    ps[k] = make_float4(p.x, p.y, p.z, __int_as_float(sp[a]));
}

// Walk the rows of bins around sorted atom k (in bin `home`); fn(j, species_j, dx, dy, dz, r2) for each (atom,
// image) within cut2 other than k itself.
template <typename F>
__device__ __forceinline__ void walk_rows(int k, int home, const float4* __restrict__ ps,
                                          const int* __restrict__ bin_start, const Grid& g, float cut2, int lane,
                                          F&& fn) {
    const float4 pi = ps[k];
    const int nb0 = g.nb[0], nb1 = g.nb[1], nb2 = g.nb[2];
    const int bz = home % nb2, by = (home / nb2) % nb1, bx = home / (nb1 * nb2);
    int rc_[3];
    const float rcut = sqrtf(cut2);
    for (int a = 0; a < 3; ++a)
        rc_[a] = min(g.reach[a], (int)ceilf(rcut / g.hb[a] * (1.0f + 1e-5f)));
    // The column of bins (tx, ty, *) is the line C + u e2 thickened by its cross-section (radius rx); a bin tz holds
    // u in [tz, tz + 1]. Columns whose line is farther than rcut + rx are skipped, and each column's z range is cut to
    // the chord |u - u0| <= sqrt((rcut + rx)^2 - d_perp^2) / |e2|, one bin of margin each side (status 6.33).
    const float e0x = g.cell[0] / nb0, e0y = g.cell[1] / nb0, e0z = g.cell[2] / nb0;
    const float e1x = g.cell[3] / nb1, e1y = g.cell[4] / nb1, e1z = g.cell[5] / nb1;
    const float e2x = g.cell[6] / nb2, e2y = g.cell[7] / nb2, e2z = g.cell[8] / nb2;
    const float e2n2 = e2x * e2x + e2y * e2y + e2z * e2z, ie2n = rsqrtf(e2n2);
    const float pxp = e0x + e1x, pyp = e0y + e1y, pzp = e0z + e1z, pxm = e0x - e1x, pym = e0y - e1y, pzm = e0z - e1z;
    const float rx = 0.5f * sqrtf(fmaxf(pxp * pxp + pyp * pyp + pzp * pzp, pxm * pxm + pym * pym + pzm * pzm));
    const float R = (rcut + rx) * (1.0f + 1e-4f) + 1e-3f, R2 = R * R;
    for (int ox = -rc_[0]; ox <= rc_[0]; ++ox) {
        const int tx = bx + ox, ix = (tx % nb0 + nb0) % nb0, sx = (tx - ix) / nb0;
        for (int oy = -rc_[1]; oy <= rc_[1]; ++oy) {
            const int ty = by + oy, iy = (ty % nb1 + nb1) % nb1, sy = (ty - iy) / nb1;
            const float cx = (tx + 0.5f) * e0x + (ty + 0.5f) * e1x - pi.x;
            const float cy = (tx + 0.5f) * e0y + (ty + 0.5f) * e1y - pi.y;
            const float cz = (tx + 0.5f) * e0z + (ty + 0.5f) * e1z - pi.z;
            const float u0 = -(cx * e2x + cy * e2y + cz * e2z) / e2n2;       // the atom's parameter on the line
            const float px = cx + u0 * e2x, py = cy + u0 * e2y, pz = cz + u0 * e2z;
            const float dp2 = px * px + py * py + pz * pz;
            if (dp2 > R2) continue;
            const float half = sqrtf(R2 - dp2) * ie2n;
            const int zlo = max(bz - rc_[2], (int)floorf(u0 - half) - 1);
            const int zhi = min(bz + rc_[2], (int)floorf(u0 + half) + 1);
            int tz = zlo;
            while (tz <= zhi) {
                const int iz = (tz % nb2 + nb2) % nb2, sz = (tz - iz) / nb2;
                const int len = min(zhi - tz, nb2 - 1 - iz) + 1;
                const float shx = sx * g.cell[0] + sy * g.cell[3] + sz * g.cell[6];
                const float shy = sx * g.cell[1] + sy * g.cell[4] + sz * g.cell[7];
                const float shz = sx * g.cell[2] + sy * g.cell[5] + sz * g.cell[8];
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

// Pass 1: coordination numbers (sorted order).
__global__ void __launch_bounds__(WPB * 32) cn_kernel(int n, const float4* __restrict__ ps,
                                                      const int* __restrict__ keys, const int* __restrict__ bin_start,
                                                      const Grid* __restrict__ gp, float cn_cut2,
                                                      const float* __restrict__ rcov, double* __restrict__ cn) {
    const int k = (blockIdx.x * blockDim.x + threadIdx.x) >> 5, lane = threadIdx.x & 31;
    if (k >= n) return;
    const Grid g = *gp;
    const float ri = rcov[__float_as_int(ps[k].w)];
    float acc = 0.0f;   // per lane: flushed to float64 every 64 terms below 1
    double tot = 0.0;
    int cnt = 0;
    walk_rows(k, keys[k], ps, bin_start, g, cn_cut2, lane, [&](int, int sj, float, float, float, float r2) {
        acc += 1.0f / (1.0f + __expf(-K1 * ((ri + rcov[sj]) * rsqrtf(r2) - 1.0f)));
        if (++cnt == 64) { tot += acc; acc = 0.0f; cnt = 0; }
    });
    tot = warp_sum(tot + acc);
    if (lane == 0) cn[k] = tot;
}

// Per atom: the normalised Gaussian weights of its reference CNs and their CN derivatives.
__global__ void weight_kernel(int n, const float4* __restrict__ ps, const int* __restrict__ nref,
                              const float* __restrict__ cnref, const double* __restrict__ cn,
                              float* __restrict__ w, float* __restrict__ dw) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= n) return;
    const int s = __float_as_int(ps[i].w), m = nref[s];
    double e[MAXREF], de[MAXREF], norm = 0.0, dnorm = 0.0, best = 1e300;
    int arg = 0;
    for (int a = 0; a < m; ++a) {
        const double d = cn[i] - cnref[s * MAXREF + a];
        e[a] = exp(-(double)K3 * d * d);
        de[a] = -2.0 * K3 * d * e[a];
        norm += e[a];
        dnorm += de[a];
        if (fabs(d) < best) { best = fabs(d); arg = a; }
    }
    for (int a = 0; a < WSTRIDE; ++a) {
        float wa = 0.0f, dwa = 0.0f;
        if (a < m) {
            if (norm > 1e-300) {
                wa = (float)(e[a] / norm);
                dwa = (float)((de[a] - e[a] / norm * dnorm) / norm);   // norm^2 underflows far from every reference
            } else {
                wa = a == arg ? 1.0f : 0.0f;    // every weight underflowed: the nearest reference
            }
        }
        w[i * WSTRIDE + a] = wa;
        if (a < MAXREF) dw[i * MAXREF + a] = dwa;
    }
}

enum DampKind { kBJ = 0, kZero = 1, kZeroM = 2 };

// G = s6 g6 + s8 qq g8 and dG/dr / r for one pair.
template <int DAMP>
__device__ __forceinline__ void damping(const PairParams& p, float r2, float qq, float r0, float& G, float& dG_r) {
    if (DAMP == kBJ) {
        const float f = p.a1 * sqrtf(qq) + p.a2;
        const float f2 = f * f, f6 = f2 * f2 * f2, f8 = f6 * f2;
        const float r4 = r2 * r2, r6 = r4 * r2, r8 = r6 * r2;
        const float t6 = 1.0f / (r6 + f6), t8 = 1.0f / (r8 + f8);
        G = p.s6 * t6 + p.s8 * qq * t8;
        dG_r = -(p.s6 * 6.0f * r4 * t6 * t6 + p.s8 * qq * 8.0f * r6 * t8 * t8);
    } else {
        const float r = sqrtf(r2), ir = 1.0f / r, ir2 = ir * ir, ir6 = ir2 * ir2 * ir2, ir8 = ir6 * ir2;
        float d6, dd6, d8, dd8;
        if (DAMP == kZero) {
            const float t6 = 6.0f * __powf(p.rs6 * r0 * ir, p.alpha6);
            const float t8 = 6.0f * __powf(p.rs8 * r0 * ir, p.alpha8);
            d6 = 1.0f / (1.0f + t6);
            d8 = 1.0f / (1.0f + t8);
            dd6 = p.alpha6 * t6 * d6 * d6 * ir;          // dd/dr
            dd8 = p.alpha8 * t8 * d8 * d8 * ir;
        } else {
            const float x6 = r / (p.rs6 * r0) + p.beta * r0, x8 = r / (p.rs8 * r0) + p.beta * r0;
            const float t6 = 6.0f * __powf(x6, -p.alpha6), t8 = 6.0f * __powf(x8, -p.alpha8);
            d6 = 1.0f / (1.0f + t6);
            d8 = 1.0f / (1.0f + t8);
            dd6 = p.alpha6 * t6 * d6 * d6 / (x6 * p.rs6 * r0);
            dd8 = p.alpha8 * t8 * d8 * d8 / (x8 * p.rs8 * r0);
        }
        const float g6 = d6 * ir6, g8 = d8 * ir8;
        const float dg6 = dd6 * ir6 - 6.0f * g6 * ir, dg8 = dd8 * ir8 - 8.0f * g8 * ir;
        G = p.s6 * g6 + p.s8 * qq * g8;
        dG_r = (p.s6 * dg6 + p.s8 * qq * dg8) * ir;
    }
}

// The split sum's smooth long-range parts h_l6, h_l8 (d3_split.cuh) and their r-derivatives over r, for subtraction
// from the damped pair term. 1 - e^-x P(x) by its series below x = 1 (float32 cancellation), directly above.
__device__ __forceinline__ void split_long(float b2, float r2, float& h6, float& h8, float& dh6_r, float& dh8_r) {
    const float x = b2 * r2, e = expf(-x);
    float p6, p8;
    if (x < 1.0f) {
        const float x3 = x * x * x;
        p6 = e * x3 / 6.0f * (1.0f + x * (1.0f / 4 + x * (1.0f / 20 + x * (1.0f / 120 + x * (1.0f / 840 + x *
                (1.0f / 6720 + x * (1.0f / 60480 + x * (1.0f / 604800))))))));
        p8 = e * x3 * x / 24.0f * (1.0f + x * (1.0f / 5 + x * (1.0f / 30 + x * (1.0f / 210 + x * (1.0f / 1680 + x *
                (1.0f / 15120 + x * (1.0f / 151200 + x * (1.0f / 1663200))))))));
    } else {
        p6 = 1.0f - e * (1.0f + x * (1.0f + x * 0.5f));
        p8 = 1.0f - e * (1.0f + x * (1.0f + x * (0.5f + x * (1.0f / 6))));
    }
    const float ir2 = 1.0f / r2, ir6 = ir2 * ir2 * ir2, ir8 = ir6 * ir2;
    h6 = p6 * ir6;
    h8 = p8 * ir8;
    dh6_r = b2 * e * x * x * ir6 - 6.0f * h6 * ir2;
    dh8_r = b2 * e * x * x * x / 3.0f * ir8 - 8.0f * h8 * ir2;
}

// Pass 2: pair energies (halved: each pair is seen from both ends), the direct forces and virial, dE/dCN_i.
// Shared: s_q[S], then per warp the projections u_i(s, b) = sum_a w_ia C6ref[s_i, s](a, b) and du with dw.
template <int DAMP, bool FORCES>
__global__ void __launch_bounds__(WPB * 32) pair_kernel(
        int n, const float4* __restrict__ ps, const int* __restrict__ keys, const int* __restrict__ bin_start,
        const Grid* __restrict__ gp, PairParams p, int S, const float* __restrict__ c6ref,
        const float* __restrict__ q, const float* __restrict__ r0ab, const float* __restrict__ w,
        const float* __restrict__ dw, double* __restrict__ acc, double* __restrict__ eatom,
        double* __restrict__ force_s, double* __restrict__ dedcn) {
    extern __shared__ float smem[];
    float* s_q = smem;
    const int wib = threadIdx.x >> 5, lane = threadIdx.x & 31;
    float* s_u = smem + S + wib * 2 * S * MAXREF;
    float* s_du = s_u + S * MAXREF;
    const int k = blockIdx.x * WPB + wib;
    for (int t = threadIdx.x; t < S; t += blockDim.x) s_q[t] = q[t];
    if (k < n) {
        const int si = __float_as_int(ps[k].w);
        for (int t = lane; t < S * MAXREF; t += 32) {
            const int s = t / MAXREF, b = t % MAXREF;
            const float* tab = c6ref + ((size_t)si * S + s) * MAXREF * MAXREF;
            float u = 0.0f, du = 0.0f;
            for (int a = 0; a < MAXREF; ++a) {
                u += w[k * WSTRIDE + a] * tab[a * MAXREF + b];
                if (FORCES) du += dw[k * MAXREF + a] * tab[a * MAXREF + b];
            }
            s_u[t] = u;
            s_du[t] = du;
        }
    }
    __syncthreads();
    if (k >= n) return;
    const Grid g = *gp;
    const int si = __float_as_int(ps[k].w);
    const float qi = s_q[si];
    // Per lane: float32 partial sums of the forces, virial and dE/dCN, added to the float64 totals every D3_FLUSH
    // pairs (float64 runs at a fraction of float32's rate on consumer GPUs; status 6.33). The energy is summed in
    // float64 per pair, so that the energy-only path gives the same energy.
    double e = 0.0, fx = 0.0, fy = 0.0, fz = 0.0, dcn = 0.0;
    double v[6] = {0, 0, 0, 0, 0, 0};
    float pfx = 0.0f, pfy = 0.0f, pfz = 0.0f, pdcn = 0.0f;
    float pv[6] = {0, 0, 0, 0, 0, 0};
    int cnt = 0;
    auto flush = [&]() {
        if (FORCES) {
            fx += pfx; fy += pfy; fz += pfz; dcn += pdcn;
            pfx = pfy = pfz = pdcn = 0.0f;
            for (int c = 0; c < 6; ++c) { v[c] += pv[c]; pv[c] = 0.0f; }
        }
        cnt = 0;
    };
    walk_rows(k, keys[k], ps, bin_start, g, p.cut2, lane, [&](int j, int sj, float dx, float dy, float dz, float r2) {
        const float4 w0 = *reinterpret_cast<const float4*>(w + WSTRIDE * (size_t)j);
        const float w4 = w[WSTRIDE * (size_t)j + 4];
        const float* u = s_u + sj * MAXREF;
        const float c6 = u[0] * w0.x + u[1] * w0.y + u[2] * w0.z + u[3] * w0.w + u[4] * w4;
        const float qq = 3.0f * qi * s_q[sj];
        float G, dG_r;
        damping<DAMP>(p, r2, qq, DAMP == kBJ ? 0.0f : r0ab[si * S + sj], G, dG_r);
        if (p.ew_b2 > 0.0f) {
            float h6, h8, dh6, dh8;
            split_long(p.ew_b2, r2, h6, h8, dh6, dh8);
            G -= p.s6 * h6 + p.s8 * qq * h8;
            dG_r -= p.s6 * dh6 + p.s8 * qq * dh8;
        }
        float sw = 1.0f, dsw_r = 0.0f;
        if (p.sw_width > 0.0f) {
            const float r = sqrtf(r2);
            if (r > p.sw_on) {
                const float x = (r - p.sw_on) / p.sw_width;
                sw = 1.0f - x * x * x * (10.0f - 15.0f * x + 6.0f * x * x);
                dsw_r = -30.0f * x * x * (1.0f - x) * (1.0f - x) / (p.sw_width * r);
            }
        }
        e += (double)(-0.5f * c6 * G * sw);
        if (FORCES) {
            const float* du = s_du + sj * MAXREF;
            const float dc6i = du[0] * w0.x + du[1] * w0.y + du[2] * w0.z + du[3] * w0.w + du[4] * w4;
            const float de_r = -c6 * (dG_r * sw + G * dsw_r);       // dE_ij/dr / r
            pfx += de_r * dx;
            pfy += de_r * dy;
            pfz += de_r * dz;
            const float h = 0.5f * de_r;
            pv[0] += h * dx * dx;
            pv[1] += h * dx * dy;
            pv[2] += h * dx * dz;
            pv[3] += h * dy * dy;
            pv[4] += h * dy * dz;
            pv[5] += h * dz * dz;
            pdcn += -dc6i * G * sw;      // dE_ij/dCN_i: the whole pair energy, i's share of both directions
        }
        if (++cnt == D3_FLUSH) flush();
    });
    flush();
    e = warp_sum(e);
    if (FORCES) {
        fx = warp_sum(fx); fy = warp_sum(fy); fz = warp_sum(fz); dcn = warp_sum(dcn);
        for (int c = 0; c < 6; ++c) v[c] = warp_sum(v[c]);
    }
    if (lane == 0) {
        atomicAdd(&acc[0], e);
        if (eatom) eatom[k] = e;
        if (FORCES) {
            force_s[3 * k + 0] = fx;
            force_s[3 * k + 1] = fy;
            force_s[3 * k + 2] = fz;
            for (int c = 0; c < 6; ++c) atomicAdd(&acc[1 + c], v[c]);
            dedcn[k] = dcn;
        }
    }
}

// Pass 3: the CN chain rule, dE/dr_ij through CN = (dE/dCN_i + dE/dCN_j) dcn_ij/dr; then the force of sorted atom
// k goes to the pass's atom order[k] in eV/A.
__global__ void __launch_bounds__(WPB * 32) cn_force_kernel(
        int n, const float4* __restrict__ ps, const int* __restrict__ keys, const int* __restrict__ bin_start,
        const Grid* __restrict__ gp, float cn_cut2, const float* __restrict__ rcov, const float* __restrict__ dedcn,
        const int* __restrict__ order, const double* __restrict__ force_s, double* __restrict__ forces,
        double* __restrict__ acc) {
    const int k = (blockIdx.x * blockDim.x + threadIdx.x) >> 5, lane = threadIdx.x & 31;
    if (k >= n) return;
    const Grid g = *gp;
    const float ri = rcov[__float_as_int(ps[k].w)];
    const float di = dedcn[k];
    double fx = 0.0, fy = 0.0, fz = 0.0;
    double v[6] = {0, 0, 0, 0, 0, 0};
    float pfx = 0.0f, pfy = 0.0f, pfz = 0.0f;       // float32 partials, as in pair_kernel
    float pv[6] = {0, 0, 0, 0, 0, 0};
    int cnt = 0;
    auto flush = [&]() {
        fx += pfx; fy += pfy; fz += pfz;
        pfx = pfy = pfz = 0.0f;
        for (int c = 0; c < 6; ++c) { v[c] += pv[c]; pv[c] = 0.0f; }
        cnt = 0;
    };
    walk_rows(k, keys[k], ps, bin_start, g, cn_cut2, lane, [&](int j, int sj, float dx, float dy, float dz, float r2) {
        const float ir = rsqrtf(r2);
        const float rco = ri + rcov[sj];
        const float ex = __expf(-K1 * (rco * ir - 1.0f));
        const float den = 1.0f + ex;
        const float s = (di + dedcn[j]) * (-K1 * rco * ir * ir * ex / (den * den)) * ir;
        if (s == 0.0f) return;
        pfx += s * dx;
        pfy += s * dy;
        pfz += s * dz;
        const float h = 0.5f * s;
        pv[0] += h * dx * dx;
        pv[1] += h * dx * dy;
        pv[2] += h * dx * dz;
        pv[3] += h * dy * dy;
        pv[4] += h * dy * dz;
        pv[5] += h * dz * dz;
        if (++cnt == D3_FLUSH) flush();
    });
    flush();
    fx = warp_sum(fx); fy = warp_sum(fy); fz = warp_sum(fz);
    for (int c = 0; c < 6; ++c) v[c] = warp_sum(v[c]);
    if (lane == 0) {
        const int a = order[k];
        constexpr double F = HARTREE / BOHR;
        forces[3 * a + 0] += (force_s[3 * k + 0] + fx) * F;
        forces[3 * a + 1] += (force_s[3 * k + 1] + fy) * F;
        forces[3 * a + 2] += (force_s[3 * k + 2] + fz) * F;
        for (int c = 0; c < 6; ++c) atomicAdd(&acc[1 + c], v[c]);
    }
}

// ---------------------------------------------------------------------------------------- three-body term (S6-D08)
// Axilrod-Teller-Muto with simple-dftd3's convention for every damping: for each triangle of (atom, image) points
// whose three sides lie within the three-body cutoff,
//   E_ijk = s9 sqrt(C6_ij C6_ik C6_jk) (3 cos a cos b cos c + 1) / (r_ij r_ik r_jk)^3 f(R) S,
//   f = 1 / (1 + 6 (R0 / R)^((alpha + 2) / 3)),  R = r_ij r_ik r_jk,  R0 = prod (4/3 R0ab) over the sides,
// S the product of the switch of each side (the pair term's width, if any, at the three-body cutoff). One block per
// atom i: its neighbours within the cutoff are listed in warp order into shared memory in chunks of ATM_CHUNK, and
// the block runs over the pairs (j, k) of the list. Each triangle is seen from each of its corners; corner i keeps
// E/3 and its share of the virial, and the force and dE/dCN_i in full, both of which only involve its own two sides.
constexpr int ATM_THREADS = 128;
constexpr int ATM_CHUNK = 384;
constexpr int ATM_FIELDS = 12;          // per entry: dx dy dz species | w[5] | c6_ij dc6_ij/dCN_i r0_ij

struct AtmParams {
    float cut2, sw_on, sw_width, beta, s9;
};

// The warp-ordered list of the (atom, image) neighbours of sorted atom k within cut2: fn(slot, j, sj, dx, dy, dz)
// for the entries with running index in [first, first + count); returns the total number.
template <typename F>
__device__ __forceinline__ int walk_list(int k, int home, const float4* __restrict__ ps,
                                         const int* __restrict__ bin_start, const Grid& g, float cut2, int lane,
                                         int first, int count, F&& fn) {
    const float4 pi = ps[k];
    const int nb0 = g.nb[0], nb1 = g.nb[1], nb2 = g.nb[2];
    const int bz = home % nb2, by = (home / nb2) % nb1, bx = home / (nb1 * nb2);
    int base = 0;
    int rc_[3];
    const float rcut = sqrtf(cut2);
    for (int a = 0; a < 3; ++a)
        rc_[a] = min(g.reach[a], (int)ceilf(rcut / g.hb[a] * (1.0f + 1e-5f)));
    // The column of bins (tx, ty, *) is the line C + u e2 thickened by its cross-section (radius rx); a bin tz holds
    // u in [tz, tz + 1]. Columns whose line is farther than rcut + rx are skipped, and each column's z range is cut to
    // the chord |u - u0| <= sqrt((rcut + rx)^2 - d_perp^2) / |e2|, one bin of margin each side (status 6.33).
    const float e0x = g.cell[0] / nb0, e0y = g.cell[1] / nb0, e0z = g.cell[2] / nb0;
    const float e1x = g.cell[3] / nb1, e1y = g.cell[4] / nb1, e1z = g.cell[5] / nb1;
    const float e2x = g.cell[6] / nb2, e2y = g.cell[7] / nb2, e2z = g.cell[8] / nb2;
    const float e2n2 = e2x * e2x + e2y * e2y + e2z * e2z, ie2n = rsqrtf(e2n2);
    const float pxp = e0x + e1x, pyp = e0y + e1y, pzp = e0z + e1z, pxm = e0x - e1x, pym = e0y - e1y, pzm = e0z - e1z;
    const float rx = 0.5f * sqrtf(fmaxf(pxp * pxp + pyp * pyp + pzp * pzp, pxm * pxm + pym * pym + pzm * pzm));
    const float R = (rcut + rx) * (1.0f + 1e-4f) + 1e-3f, R2 = R * R;
    for (int ox = -rc_[0]; ox <= rc_[0]; ++ox) {
        const int tx = bx + ox, ix = (tx % nb0 + nb0) % nb0, sx = (tx - ix) / nb0;
        for (int oy = -rc_[1]; oy <= rc_[1]; ++oy) {
            const int ty = by + oy, iy = (ty % nb1 + nb1) % nb1, sy = (ty - iy) / nb1;
            const float cx = (tx + 0.5f) * e0x + (ty + 0.5f) * e1x - pi.x;
            const float cy = (tx + 0.5f) * e0y + (ty + 0.5f) * e1y - pi.y;
            const float cz = (tx + 0.5f) * e0z + (ty + 0.5f) * e1z - pi.z;
            const float u0 = -(cx * e2x + cy * e2y + cz * e2z) / e2n2;       // the atom's parameter on the line
            const float px = cx + u0 * e2x, py = cy + u0 * e2y, pz = cz + u0 * e2z;
            const float dp2 = px * px + py * py + pz * pz;
            if (dp2 > R2) continue;
            const float half = sqrtf(R2 - dp2) * ie2n;
            const int zlo = max(bz - rc_[2], (int)floorf(u0 - half) - 1);
            const int zhi = min(bz + rc_[2], (int)floorf(u0 + half) + 1);
            int tz = zlo;
            while (tz <= zhi) {
                const int iz = (tz % nb2 + nb2) % nb2, sz = (tz - iz) / nb2;
                const int len = min(zhi - tz, nb2 - 1 - iz) + 1;
                const float shx = sx * g.cell[0] + sy * g.cell[3] + sz * g.cell[6];
                const float shy = sx * g.cell[1] + sy * g.cell[4] + sz * g.cell[7];
                const float shz = sx * g.cell[2] + sy * g.cell[5] + sz * g.cell[8];
                const float ox_ = shx - pi.x, oy_ = shy - pi.y, oz_ = shz - pi.z;
                const int b0 = (ix * nb1 + iy) * nb2 + iz;
                const int lo = bin_start[b0], hi = bin_start[b0 + len];
                const bool home_img = sx == 0 && sy == 0 && sz == 0;
                for (int j0 = lo; j0 < hi; j0 += 32) {
                    const int j = j0 + lane;
                    bool ok = false;
                    float dx = 0.0f, dy = 0.0f, dz = 0.0f;
                    int sj = 0;
                    if (j < hi && !(home_img && j == k)) {
                        const float4 pj = ps[j];
                        dx = pj.x + ox_; dy = pj.y + oy_; dz = pj.z + oz_;
                        ok = dx * dx + dy * dy + dz * dz < cut2;
                        sj = __float_as_int(pj.w);
                    }
                    const unsigned m = __ballot_sync(0xffffffffu, ok);
                    const int idx = base + __popc(m & ((1u << lane) - 1u));
                    if (ok && idx >= first && idx < first + count) fn(idx - first, j, sj, dx, dy, dz);
                    base += __popc(m);
                }
                tz += len;
            }
        }
    }
    return base;
}

__device__ __forceinline__ void atm_switch(const AtmParams& p, float r2, float& s, float& ds_a) {
    // s(r) and ds/d(r^2)
    s = 1.0f;
    ds_a = 0.0f;
    if (p.sw_width > 0.0f) {
        const float r = sqrtf(r2);
        if (r > p.sw_on) {
            const float x = (r - p.sw_on) / p.sw_width;
            s = 1.0f - x * x * x * (10.0f - 15.0f * x + 6.0f * x * x);
            ds_a = -30.0f * x * x * (1.0f - x) * (1.0f - x) / (p.sw_width * 2.0f * r);
        }
    }
}

template <bool FORCES>
__global__ void __launch_bounds__(ATM_THREADS) atm_kernel(
        int n, const float4* __restrict__ ps, const int* __restrict__ keys, const int* __restrict__ bin_start,
        const Grid* __restrict__ gp, AtmParams p, int S, const float* __restrict__ c6ref,
        const float* __restrict__ r0ab, const float* __restrict__ w, const float* __restrict__ dw,
        double* __restrict__ acc, double* __restrict__ eatom, double* __restrict__ force_s,
        double* __restrict__ dedcn, int proj) {
    extern __shared__ float sm[];
    __shared__ int s_count;
    __shared__ double s_red[11];
    const int k = blockIdx.x, warp = threadIdx.x >> 5, lane = threadIdx.x & 31;
    const Grid g = *gp;
    const int si = __float_as_int(ps[k].w);
    float wk[MAXREF], dwk[MAXREF];
    for (int a = 0; a < MAXREF; ++a) { wk[a] = w[k * WSTRIDE + a]; dwk[a] = dw[k * MAXREF + a]; }
    if (threadIdx.x < 11) s_red[threadIdx.x] = 0.0;
    if (warp == 0) {
        const int c = walk_list(k, keys[k], ps, bin_start, g, p.cut2, lane, 0, 0,
                                [](int, int, int, float, float, float) {});
        if (lane == 0) s_count = c;
    }
    __syncthreads();
    const int N = s_count, chunks = (N + ATM_CHUNK - 1) / ATM_CHUNK;
    // fill chunk c into the buffer at `buf` (one warp)
    auto fill = [&](float* buf, int c) {
        float4* pos = reinterpret_cast<float4*>(buf);
        float* rest = buf + 4 * ATM_CHUNK;
        walk_list(k, keys[k], ps, bin_start, g, p.cut2, lane, c * ATM_CHUNK, ATM_CHUNK,
                  [&](int slot, int j, int sj, float dx, float dy, float dz) {
            pos[slot] = make_float4(dx, dy, dz, __int_as_float(sj));
            const float* tab = c6ref + ((size_t)si * S + sj) * MAXREF * MAXREF;
            float wj[MAXREF];
            for (int b = 0; b < MAXREF; ++b) { wj[b] = w[j * WSTRIDE + b]; rest[b * ATM_CHUNK + slot] = wj[b]; }
            float c6 = 0.0f, dc6 = 0.0f;
            for (int a = 0; a < MAXREF; ++a) {
                float t = 0.0f;
                for (int b = 0; b < MAXREF; ++b) t += tab[a * MAXREF + b] * wj[b];
                c6 += wk[a] * t;
                dc6 += dwk[a] * t;
            }
            rest[5 * ATM_CHUNK + slot] = c6;
            rest[6 * ATM_CHUNK + slot] = dc6;
            rest[7 * ATM_CHUNK + slot] = (4.0f / 3.0f) * r0ab[si * S + sj];
        });
    };
    float* bufA = sm;
    float* bufB = sm + ATM_FIELDS * ATM_CHUNK;
    double e = 0.0, fx = 0.0, fy = 0.0, fz = 0.0, dcn = 0.0;
    double v[6] = {0, 0, 0, 0, 0, 0};
    float pfx = 0.0f, pfy = 0.0f, pfz = 0.0f, pdcn = 0.0f;   // float32 partials, as in pair_kernel; the energy
    float pv[6] = {0, 0, 0, 0, 0, 0};                         // is summed in float64 per triangle
    int cnt = 0;
    auto flush = [&]() {
        fx += pfx; fy += pfy; fz += pfz; dcn += pdcn;
        pfx = pfy = pfz = pdcn = 0.0f;
        for (int c = 0; c < 6; ++c) { v[c] += pv[c]; pv[c] = 0.0f; }
        cnt = 0;
    };
    for (int A = 0; A < chunks; ++A) {
        for (int B = A; B < chunks; ++B) {
            __syncthreads();
            if (warp == 0 && B == A) fill(bufA, A);
            if (warp == 1 && B != A) fill(bufB, B);
            __syncthreads();
            const int nA = min(ATM_CHUNK, N - A * ATM_CHUNK), nB = min(ATM_CHUNK, N - B * ATM_CHUNK);
            const float* X = bufA;
            const float* Y = B == A ? bufA : bufB;
            const float4* Xp = reinterpret_cast<const float4*>(X);
            const float4* Yp = reinterpret_cast<const float4*>(Y);
            for (int a = threadIdx.x; a < nA; a += ATM_THREADS) {
                const float4 pj = Xp[a];
                const int sj = __float_as_int(pj.w);
                float wj[MAXREF];
                for (int t = 0; t < MAXREF; ++t) wj[t] = X[(4 + t) * ATM_CHUNK + a];
                // proj: u_j(s, y) = sum_x w_j[x] C6ref[s_j, s](x, y) once per entry, so that C6_jk takes 5 FMA per
                // triangle instead of 25 (status 6.33); this thread's column of the shared table
                float* uj = sm + 2 * ATM_FIELDS * ATM_CHUNK + threadIdx.x;
                if (proj) {
                    for (int s2 = 0; s2 < S; ++s2) {
                        const float* tab = c6ref + ((size_t)sj * S + s2) * MAXREF * MAXREF;
                        for (int y = 0; y < MAXREF; ++y) {
                            float u = 0.0f;
                            for (int x = 0; x < MAXREF; ++x) u += wj[x] * tab[x * MAXREF + y];
                            uj[(s2 * MAXREF + y) * ATM_THREADS] = u;
                        }
                    }
                }
                const float c6ij = X[9 * ATM_CHUNK + a], dc6ij = X[10 * ATM_CHUNK + a];
                const float r0ij = X[11 * ATM_CHUNK + a];
                const float ra = pj.x * pj.x + pj.y * pj.y + pj.z * pj.z;
                float swa, dswa;
                atm_switch(p, ra, swa, dswa);
                for (int b = B == A ? a + 1 : 0; b < nB; ++b) {
                    const float4 pk = Yp[b];
                    const float jx = pk.x - pj.x, jy = pk.y - pj.y, jz = pk.z - pj.z;
                    const float rc = jx * jx + jy * jy + jz * jz;
                    if (rc >= p.cut2 || rc <= 1e-12f) continue;
                    const int sk = __float_as_int(pk.w);
                    float c6jk = 0.0f;
                    if (proj) {
                        for (int y = 0; y < MAXREF; ++y)
                            c6jk += uj[(sk * MAXREF + y) * ATM_THREADS] * Y[(4 + y) * ATM_CHUNK + b];
                    } else {
                        const float* tab = c6ref + ((size_t)sj * S + sk) * MAXREF * MAXREF;
                        for (int x = 0; x < MAXREF; ++x) {
                            float t = 0.0f;
                            for (int y = 0; y < MAXREF; ++y) t += tab[x * MAXREF + y] * Y[(4 + y) * ATM_CHUNK + b];
                            c6jk += wj[x] * t;
                        }
                    }
                    const float c6ik = Y[9 * ATM_CHUNK + b];
                    const float c9 = p.s9 * sqrtf(c6ij * c6ik * c6jk);
                    if (!(c9 > 0.0f)) continue;
                    const float rb = pk.x * pk.x + pk.y * pk.y + pk.z * pk.z;
                    const float R = sqrtf(ra * rb * rc), iR = 1.0f / R, iR3 = iR * iR * iR;
                    const float X1 = ra + rc - rb, Y1 = ra - rc + rb, Z1 = -ra + rc + rb;
                    const float P = X1 * Y1 * Z1;
                    const float ang = 0.375f * P * iR3 * iR * iR + iR3;
                    const float r0 = r0ij * Y[11 * ATM_CHUNK + b] * (4.0f / 3.0f) * r0ab[sj * S + sk];
                    const float t = 6.0f * __powf(r0 * iR, p.beta);
                    const float f = 1.0f / (1.0f + t);
                    float swb, dswb, swc, dswc;
                    atm_switch(p, rb, swb, dswb);
                    atm_switch(p, rc, swc, dswc);
                    const float sw = swa * swb * swc;
                    const float E = c9 * ang * f * sw;
                    e += (double)(E * (1.0f / 3.0f));
                    if (FORCES) {
                        // dE/d(r^2) of the sides ij (a) and ik (b): R depends on each as R / (2 r^2)
                        const float hR = 0.375f * P * iR3 * iR * iR * 5.0f + 3.0f * iR3;   // -dang/dR * R
                        const float dfR = f * f * t * p.beta;                             // df/dR * R
                        const float dPa = Y1 * Z1 + X1 * Z1 - X1 * Y1;
                        const float dPb = -Y1 * Z1 + X1 * Z1 + X1 * Y1;
                        const float ga = c9 * ((0.375f * dPa * iR3 * iR * iR - hR / (2.0f * ra)) * f * sw +
                                               ang * dfR / (2.0f * ra) * sw + ang * f * dswa * swb * swc);
                        const float gb = c9 * ((0.375f * dPb * iR3 * iR * iR - hR / (2.0f * rb)) * f * sw +
                                               ang * dfR / (2.0f * rb) * sw + ang * f * swa * dswb * swc);
                        pfx += 2.0f * (ga * pj.x + gb * pk.x);
                        pfy += 2.0f * (ga * pj.y + gb * pk.y);
                        pfz += 2.0f * (ga * pj.z + gb * pk.z);
                        pv[0] += ga * pj.x * pj.x + gb * pk.x * pk.x;
                        pv[1] += ga * pj.x * pj.y + gb * pk.x * pk.y;
                        pv[2] += ga * pj.x * pj.z + gb * pk.x * pk.z;
                        pv[3] += ga * pj.y * pj.y + gb * pk.y * pk.y;
                        pv[4] += ga * pj.y * pj.z + gb * pk.y * pk.z;
                        pv[5] += ga * pj.z * pj.z + gb * pk.z * pk.z;
                        pdcn += 0.5f * E * (dc6ij / c6ij + Y[10 * ATM_CHUNK + b] / c6ik);
                        if (++cnt == D3_FLUSH) flush();
                    }
                }
            }
        }
    }
    if (FORCES) flush();
    e = warp_sum(e);
    if (FORCES) {
        fx = warp_sum(fx); fy = warp_sum(fy); fz = warp_sum(fz); dcn = warp_sum(dcn);
        for (int c = 0; c < 6; ++c) v[c] = warp_sum(v[c]);
    }
    if (lane == 0) {
        atomicAdd(&s_red[0], e);
        if (FORCES) {
            atomicAdd(&s_red[1], fx); atomicAdd(&s_red[2], fy); atomicAdd(&s_red[3], fz);
            atomicAdd(&s_red[4], dcn);
            for (int c = 0; c < 6; ++c) atomicAdd(&s_red[5 + c], v[c]);
        }
    }
    __syncthreads();
    if (threadIdx.x == 0) {
        atomicAdd(&acc[0], s_red[0]);
        if (eatom) eatom[k] += s_red[0];
        if (FORCES) {
            force_s[3 * k + 0] += s_red[1];
            force_s[3 * k + 1] += s_red[2];
            force_s[3 * k + 2] += s_red[3];
            dedcn[k] += s_red[4];
            for (int c = 0; c < 6; ++c) atomicAdd(&acc[1 + c], s_red[5 + c]);
        }
    }
}

// dE/dCN in float32 for the chain rule, which reads it once per pair (a conversion per pair costs as much as a
// float64 add on consumer GPUs; status 6.33).
__global__ void to_float_kernel(int n, const double* __restrict__ x, float* __restrict__ y) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n) y[i] = (float)x[i];
}

__global__ void finish_kernel(const double* __restrict__ acc, double* __restrict__ energy,
                              double* __restrict__ virial) {
    const int t = threadIdx.x;
    if (t == 0 && energy) energy[0] += acc[0] * HARTREE;
    if (t < 6 && virial) virial[t] += acc[1 + t] * HARTREE;
}

__global__ void atom_energy_kernel(int n, const int* __restrict__ order, const double* __restrict__ eatom_s,
                                   double* __restrict__ atom_energy) {
    const int k = blockIdx.x * blockDim.x + threadIdx.x;
    if (k < n) atom_energy[order[k]] += eatom_s[k] * HARTREE;
}

__global__ void iota_kernel(int n, int* __restrict__ out) {
    const int k = blockIdx.x * blockDim.x + threadIdx.x;
    if (k < n) out[k] = k;
}

#include "dispersion/d3_split.cuh"
#include "dispersion/d3_mesh.cuh"

int bins_for(const double cell_A[9], double rmax_bohr, int nb[3]) {
    double c[9];
    for (int k = 0; k < 9; ++k) c[k] = cell_A[k] / BOHR;
    const double det = c[0] * (c[4] * c[8] - c[5] * c[7]) - c[1] * (c[3] * c[8] - c[5] * c[6]) +
                       c[2] * (c[3] * c[7] - c[4] * c[6]);
    if (!(std::fabs(det) > 1e-12)) throw std::invalid_argument("D3: the cell has no volume (a periodic cell is needed)");
    for (int ax = 0; ax < 3; ++ax) {
        const double* u = c + 3 * ((ax + 1) % 3);
        const double* w = c + 3 * ((ax + 2) % 3);
        const double cx = u[1] * w[2] - u[2] * w[1], cy = u[2] * w[0] - u[0] * w[2], cz = u[0] * w[1] - u[1] * w[0];
        const double h = std::fabs(det) / std::sqrt(cx * cx + cy * cy + cz * cz);
        nb[ax] = std::max(1, std::min(MAXBINS, (int)(h / (rmax_bohr / 4.0))));   // bins of at least a quarter cutoff
    }
    return nb[0] * nb[1] * nb[2];
}

template <class T>
struct DevBuf {
    T* p = nullptr;
    size_t count = 0;
    void alloc(size_t n, size_t& bytes) {
        free();
        if (n == 0) n = 1;
        CK(cudaMalloc(&p, n * sizeof(T)));
        count = n;
        bytes += n * sizeof(T);
    }
    void upload(const std::vector<T>& h, cudaStream_t s) {
        CK(cudaMemcpyAsync(p, h.data(), h.size() * sizeof(T), cudaMemcpyHostToDevice, s));
    }
    void free() {
        if (p) cudaFree(p);
        p = nullptr;
        count = 0;
    }
    ~DevBuf() { free(); }
};

class D3Pair final : public Term {
public:
    D3Pair(const Settings& s, const Tables& t) : s_(s) {
        nref_.assign(t.nref, t.nref + kElements);
        cnref_.assign(t.cnref, t.cnref + kElements * MAXREF);
        rcov_.assign(t.rcov, t.rcov + kElements);
        r2r4_.assign(t.r2r4, t.r2r4 + kElements);
        c6ref_.assign(t.c6ref, t.c6ref + (size_t)kElements * kElements * MAXREF * MAXREF);
        r0ab_.assign(t.r0ab, t.r0ab + kElements * kElements);
        damp_ = s.damping == Damping::Zero ? kZero : s.damping == Damping::ZeroM ? kZeroM : kBJ;
        p_.s6 = (float)s.s6; p_.s8 = (float)s.s8; p_.a1 = (float)s.a1; p_.a2 = (float)s.a2;
        p_.rs6 = (float)s.rs6; p_.rs8 = (float)s.rs8; p_.alpha6 = (float)s.alpha; p_.alpha8 = (float)(s.alpha + 2.0);
        p_.beta = (float)s.beta;
        p_.cut2 = (float)(s.pair_cutoff_bohr * s.pair_cutoff_bohr);
        p_.cn_cut2 = (float)(s.cn_cutoff_bohr * s.cn_cutoff_bohr);
        p_.sw_width = (float)s.smoothing_bohr;
        p_.sw_on = (float)(s.pair_cutoff_bohr - s.smoothing_bohr);
        rmax_ = std::max(s.pair_cutoff_bohr, s.cn_cutoff_bohr);
        three_ = s.three_body;
        a3_.cut2 = (float)(s.three_body_cutoff_bohr * s.three_body_cutoff_bohr);
        a3_.sw_width = (float)s.smoothing_bohr;
        a3_.sw_on = (float)(s.three_body_cutoff_bohr - s.smoothing_bohr);
        a3_.beta = (float)((s.alpha + 2.0) / 3.0);
        a3_.s9 = 1.0f;
        split_ = s.long_range == LongRange::Split;
        ew_beta_ = split_ ? SPLIT_BETA_RC / s.pair_cutoff_bohr : 0.0;
        p_.ew_b2 = (float)(ew_beta_ * ew_beta_);
        const char* ksum = std::getenv("LOUP_D3_KSUM");         // testing: "direct" sums reciprocal space directly
        mesh_ = split_ && !(ksum && std::string(ksum) == "direct");
        const char* order = std::getenv("LOUP_D3_PME_ORDER");   // testing: the B-spline order (4, 5, 6 or 8)
        order_p_ = order ? std::atoi(order) : 8;
        if (order_p_ != 4 && order_p_ != 5 && order_p_ != 6 && order_p_ != 8) order_p_ = 8;
        spacing_A_ = s.mesh_spacing_A > 0.0 ? s.mesh_spacing_A : 0.8;   // with order 8: status 6.31
    }

    ~D3Pair() override { destroy_plans(); }

    bool prepare(int n, const int32_t* numbers, const double cell[9], cudaStream_t stream) override {
        if (n < 1) throw std::invalid_argument("D3: no atoms");
        std::map<int, int> index;
        for (int i = 0; i < n; ++i) {
            const int z = numbers[i];
            if (z < 1 || z >= kElements || nref_[z] < 1)
                throw std::invalid_argument("D3: no reference C6 for atomic number " + std::to_string(z));
            index.emplace(z, 0);
        }
        std::vector<int> zs;
        for (auto& kv : index) { kv.second = (int)zs.size(); zs.push_back(kv.first); }
        const int S = (int)zs.size();
        std::vector<int> sp(n);
        for (int i = 0; i < n; ++i) sp[i] = index[numbers[i]];
        std::vector<int> nref(S);
        std::vector<float> cnref(S * MAXREF, 0.0f), rcov(S), q(S), r0((size_t)S * S),
            c6((size_t)S * S * MAXREF * MAXREF, 0.0f);
        for (int a = 0; a < S; ++a) {
            const int za = zs[a];
            nref[a] = nref_[za];
            for (int r = 0; r < MAXREF; ++r) cnref[a * MAXREF + r] = (float)cnref_[za * MAXREF + r];
            rcov[a] = (float)rcov_[za];
            q[a] = (float)r2r4_[za];
            for (int b = 0; b < S; ++b) {
                const int zb = zs[b];
                r0[a * S + b] = (float)r0ab_[za * kElements + zb];
                for (int x = 0; x < MAXREF * MAXREF; ++x) {
                    const double v = c6ref_[((size_t)za * kElements + zb) * MAXREF * MAXREF + x];
                    c6[((size_t)a * S + b) * MAXREF * MAXREF + x] = v > 0.0 ? (float)v : 0.0f;
                }
            }
        }
        int nb[3];
        const int nbins = bins_for(cell, rmax_, nb);
        bytes_ = 0;
        n_ = n;
        S_ = S;
        nbins_ = nbins;
        for (int a = 0; a < 3; ++a) nb_[a] = nb[a];
        grid_.alloc(1, bytes_);
        pw_.alloc(n, bytes_);
        bin_of_.alloc(n, bytes_);
        keys_.alloc(n, bytes_);
        iota_.alloc(n, bytes_);
        order_.alloc(n, bytes_);
        bin_start_.alloc(nbins + 1, bytes_);
        species_.alloc(n, bytes_);
        ps_.alloc(n, bytes_);
        cn_.alloc(n, bytes_);
        w_.alloc((size_t)n * WSTRIDE, bytes_);
        dw_.alloc((size_t)n * MAXREF, bytes_);
        dedcn_.alloc(n, bytes_);
        dedcn_f_.alloc(n, bytes_);
        force_s_.alloc(3 * (size_t)n, bytes_);
        eatom_.alloc(n, bytes_);
        acc_.alloc(7, bytes_);
        nref_d_.alloc(S, bytes_);
        cnref_d_.alloc(cnref.size(), bytes_);
        rcov_d_.alloc(S, bytes_);
        q_d_.alloc(S, bytes_);
        r0_d_.alloc(r0.size(), bytes_);
        c6_d_.alloc(c6.size(), bytes_);
        species_.upload(sp, stream);
        nref_d_.upload(nref, stream);
        cnref_d_.upload(cnref, stream);
        rcov_d_.upload(rcov, stream);
        q_d_.upload(q, stream);
        r0_d_.upload(r0, stream);
        c6_d_.upload(c6, stream);
        iota_kernel<<<(n + 255) / 256, 256, 0, stream>>>(n, iota_.p);
        end_bit_ = 1;
        while ((1 << end_bit_) < nbins) ++end_bit_;
        sort_bytes_ = 0;
        CK(cub::DeviceRadixSort::SortPairs(nullptr, sort_bytes_, bin_of_.p, keys_.p, iota_.p, order_.p, n, 0,
                                           end_bit_, stream));
        sort_tmp_.alloc(sort_bytes_, bytes_);
        smem_ = (size_t)(S + 2 * WPB * S * MAXREF) * sizeof(float);
        smem3_ = (size_t)2 * ATM_FIELDS * ATM_CHUNK * sizeof(float);
        {   // the three-body projections (atm_kernel's proj) when they fit the shared memory of a block;
            // LOUP_D3_ATM_PROJ=0 (testing) keeps the per-triangle table walk
            const size_t with = smem3_ + (size_t)S * MAXREF * ATM_THREADS * sizeof(float);
            int dev = 0, optin = 0;
            CK(cudaGetDevice(&dev));
            CK(cudaDeviceGetAttribute(&optin, cudaDevAttrMaxSharedMemoryPerBlockOptin, dev));
            const char* env = std::getenv("LOUP_D3_ATM_PROJ");
            atm_proj_ = with <= (size_t)optin && !(env && std::string(env) == "0") ? 1 : 0;
            if (atm_proj_) {
                smem3_ = with;
                CK(cudaFuncSetAttribute(atm_kernel<true>, cudaFuncAttributeMaxDynamicSharedMemorySize, (int)with));
                CK(cudaFuncSetAttribute(atm_kernel<false>, cudaFuncAttributeMaxDynamicSharedMemorySize, (int)with));
            }
        }
        if (split_) {
            std::vector<float> chan;
            std::vector<double> lam;
            nc_ = split_channels(S, nref, c6, chan, lam);
            lam_h_ = lam;
            const std::vector<int3> ks = mesh_ ? std::vector<int3>{} : split_kset(cell, ew_beta_);
            nk_ = (int)ks.size();
            // the direct k sum costs n * nk * channels sincos-and-sums twice per evaluation (nk grows with the
            // volume): refused where one evaluation would take seconds (it is the mesh's reference)
            if ((double)n * nk_ * nc_ > 4e10)
                throw std::invalid_argument("D3 split sum: " + std::to_string(n) + " atoms with " +
                                            std::to_string(nk_) + " k-vectors is too large for the direct k sum; "
                                            "unset LOUP_D3_KSUM to use the mesh");
            if (mesh_) prepare_mesh(cell);
            chan_d_.alloc(chan.size(), bytes_);
            lam_d_.alloc(lam.size(), bytes_);
            kidx_d_.alloc(ks.size(), bytes_);
            kvec_d_.alloc(ks.size(), bytes_);
            rho6_d_.alloc((size_t)nk_ * nc_, bytes_);
            rho8_d_.alloc((size_t)nk_ * nc_, bytes_);
            frac_d_.alloc(n, bytes_);
            qc_d_.alloc((size_t)n * nc_, bytes_);
            dqc_d_.alloc((size_t)n * nc_, bytes_);
            chan_d_.upload(chan, stream);
            lam_d_.upload(lam, stream);
            kidx_d_.upload(ks, stream);
            CK(cudaStreamSynchronize(stream));
        }
        CK(cudaStreamSynchronize(stream));      // the host vectors above go out of scope
        return true;
    }

    void record(const Inputs& in, const Outputs& out) override {
        if (n_ < 1) throw std::logic_error("D3: record() before prepare()");
        const int n = n_;
        cudaStream_t st = in.stream;
        const bool forces = in.forces && out.forces;
        grid_kernel<<<1, 1, 0, st>>>(in.cell, nb_[0], nb_[1], nb_[2], rmax_, grid_.p);
        wrap_kernel<<<(n + 255) / 256, 256, 0, st>>>(n, in.positions, grid_.p, pw_.p, bin_of_.p);
        CK(cub::DeviceRadixSort::SortPairs(sort_tmp_.p, sort_bytes_, bin_of_.p, keys_.p, iota_.p, order_.p, n, 0,
                                           end_bit_, st));
        bin_start_kernel<<<(n + 256) / 256, 256, 0, st>>>(n, nbins_, keys_.p, bin_start_.p);
        gather_kernel<<<(n + 255) / 256, 256, 0, st>>>(n, pw_.p, species_.p, order_.p, ps_.p);
        CK(cudaMemsetAsync(acc_.p, 0, 7 * sizeof(double), st));
        const int blocks = (n + WPB - 1) / WPB, threads = WPB * 32;
        cn_kernel<<<blocks, threads, 0, st>>>(n, ps_.p, keys_.p, bin_start_.p, grid_.p, p_.cn_cut2, rcov_d_.p, cn_.p);
        weight_kernel<<<(n + 127) / 128, 128, 0, st>>>(n, ps_.p, nref_d_.p, cnref_d_.p, cn_.p, w_.p, dw_.p);
        double* eatom = out.atom_energy ? eatom_.p : nullptr;
#define LOUP_D3_PAIR(D, F) pair_kernel<D, F><<<blocks, threads, smem_, st>>>(n, ps_.p, keys_.p, bin_start_.p, \
            grid_.p, p_, S_, c6_d_.p, q_d_.p, r0_d_.p, w_.p, dw_.p, acc_.p, eatom, force_s_.p, dedcn_.p)
        if (forces) {
            if (damp_ == kBJ) LOUP_D3_PAIR(kBJ, true);
            else if (damp_ == kZero) LOUP_D3_PAIR(kZero, true);
            else LOUP_D3_PAIR(kZeroM, true);
        } else {
            if (damp_ == kBJ) LOUP_D3_PAIR(kBJ, false);
            else if (damp_ == kZero) LOUP_D3_PAIR(kZero, false);
            else LOUP_D3_PAIR(kZeroM, false);
        }
#undef LOUP_D3_PAIR
        if (three_) {
            // after the pair kernel (it adds to the forces, dE/dCN and per-atom energies), before the CN chain rule
            if (forces)
                atm_kernel<true><<<n, ATM_THREADS, smem3_, st>>>(n, ps_.p, keys_.p, bin_start_.p, grid_.p, a3_, S_,
                                                                c6_d_.p, r0_d_.p, w_.p, dw_.p, acc_.p, eatom,
                                                                force_s_.p, dedcn_.p, atm_proj_);
            else
                atm_kernel<false><<<n, ATM_THREADS, smem3_, st>>>(n, ps_.p, keys_.p, bin_start_.p, grid_.p, a3_, S_,
                                                                 c6_d_.p, r0_d_.p, w_.p, dw_.p, acc_.p, eatom,
                                                                 force_s_.p, dedcn_.p, atm_proj_);
        }
        if (split_) {
            // the k sum and the self term: after the pair kernels (they add to forces, dE/dCN and per-atom energies)
            split_atom_kernel<<<(n + 127) / 128, 128, 0, st>>>(n, nc_, ps_.p, grid_.p, chan_d_.p, w_.p, dw_.p,
                                                               frac_d_.p, qc_d_.p, dqc_d_.p);
            if (mesh_) {
                record_mesh(st, forces, eatom);
            } else {
                split_kvec_kernel<<<(nk_ + 127) / 128, 128, 0, st>>>(nk_, kidx_d_.p, grid_.p, ew_beta_, s_.s6, s_.s8,
                                                                     kvec_d_.p);
                const int nkc = nk_ * nc_;
                split_rho_kernel<<<(nkc + 127) / 128, 128, 0, st>>>(n, nk_, nc_, kidx_d_.p, frac_d_.p, ps_.p, q_d_.p,
                                                                    qc_d_.p, rho6_d_.p, rho8_d_.p);
                split_energy_kernel<<<(nkc + 127) / 128, 128, 0, st>>>(nk_, nc_, kvec_d_.p, lam_d_.p, rho6_d_.p,
                                                                       rho8_d_.p, acc_.p);
            }
            // with the mesh, nk_ = 0: the self term only
#define LOUP_D3_SPLIT(F) split_force_kernel<F><<<(n + 127) / 128, 128, 0, st>>>(n, nk_, nc_, kidx_d_.p, kvec_d_.p, \
            lam_d_.p, rho6_d_.p, rho8_d_.p, frac_d_.p, ps_.p, q_d_.p, qc_d_.p, dqc_d_.p, ew_beta_, s_.s6, s_.s8, \
            acc_.p, eatom, force_s_.p, dedcn_.p)
            if (forces) LOUP_D3_SPLIT(true);
            else LOUP_D3_SPLIT(false);
#undef LOUP_D3_SPLIT
        }
        if (forces) {
            to_float_kernel<<<(n + 255) / 256, 256, 0, st>>>(n, dedcn_.p, dedcn_f_.p);
            cn_force_kernel<<<blocks, threads, 0, st>>>(n, ps_.p, keys_.p, bin_start_.p, grid_.p, p_.cn_cut2,
                                                        rcov_d_.p, dedcn_f_.p, order_.p, force_s_.p, out.forces,
                                                        acc_.p);
        }
        finish_kernel<<<1, 32, 0, st>>>(acc_.p, out.energy, forces && in.virial ? out.virial : nullptr);
        if (out.atom_energy)
            atom_energy_kernel<<<(n + 255) / 256, 256, 0, st>>>(n, order_.p, eatom_.p, out.atom_energy);
        CK(cudaGetLastError());
    }

    size_t device_bytes() const override { return bytes_; }

private:
    void destroy_plans() {
        if (!plans_) return;
        const CufftApi& api = cufft_api();
        api.destroy(plan_f_);
        api.destroy(plan_b_);
        plans_ = false;
    }

    // The mesh for this cell: K_a points along each axis at the spacing (2-3-5 sizes, at least twice the order),
    // the moduli, the grids and the two cuFFT plans (their work areas are allocated here, outside capture).
    void prepare_mesh(const double cell[9]) {
        const CufftApi& api = cufft_api();
        if (!api.error.empty()) throw std::invalid_argument("D3 split sum: " + api.error);
        for (int a = 0; a < 3; ++a) {
            const double len = std::sqrt(cell[3 * a] * cell[3 * a] + cell[3 * a + 1] * cell[3 * a + 1] +
                                         cell[3 * a + 2] * cell[3 * a + 2]);
            md_.k[a] = pme_good_size(std::max(2 * order_p_, (int)std::ceil(len / spacing_A_)));
        }
        const size_t pts = (size_t)md_.k[0] * md_.k[1] * md_.k[2];
        const size_t half = (size_t)md_.k[0] * md_.k[1] * (md_.k[2] / 2 + 1);
        mesh_grid_.alloc(pts, bytes_);
        mesh_spec_.alloc(half, bytes_);
        for (int a = 0; a < 3; ++a) {
            const std::vector<double> b = pme_moduli(md_.k[a], order_p_);
            bmod_[a].alloc(b.size(), bytes_);
            CK(cudaMemcpy(bmod_[a].p, b.data(), b.size() * sizeof(double), cudaMemcpyHostToDevice));
        }
        destroy_plans();
        CF(api.plan3d(&plan_f_, md_.k[0], md_.k[1], md_.k[2], CUFFT_D2Z));
        if (api.plan3d(&plan_b_, md_.k[0], md_.k[1], md_.k[2], CUFFT_Z2D) != CUFFT_SUCCESS) {
            api.destroy(plan_f_);
            throw std::runtime_error("D3 mesh: cuFFT could not plan the inverse transform");
        }
        plans_ = true;
        bytes_ += 2 * pts * sizeof(double);         // about what the two plans' work areas hold
    }

    template <int P>
    void record_mesh_p(cudaStream_t st, bool forces, double* eatom) {
        const CufftApi& api = cufft_api();
        CF(api.set_stream(plan_f_, st));
        CF(api.set_stream(plan_b_, st));
        const size_t pts = (size_t)md_.k[0] * md_.k[1] * md_.k[2];
        const long long half = (long long)md_.k[0] * md_.k[1] * (md_.k[2] / 2 + 1);
        const int n = n_;
        for (int comp = 0; comp < 2 * nc_; ++comp) {
            const int c = comp % nc_;
            const bool c8 = comp >= nc_;
            CK(cudaMemsetAsync(mesh_grid_.p, 0, pts * sizeof(double), st));
            pme_spread_kernel<P><<<(n + 127) / 128, 128, 0, st>>>(n, nc_, c, c8, md_, frac_d_.p, ps_.p, q_d_.p,
                                                                   qc_d_.p, mesh_grid_.p);
            CF(api.d2z(plan_f_, mesh_grid_.p, mesh_spec_.p));
            pme_kspace_kernel<<<(unsigned)((half + 127) / 128), 128, 0, st>>>(
                md_, grid_.p, ew_beta_, c8 ? s_.s8 : s_.s6, c8 ? 8 : 6, lam_h_[c], bmod_[0].p, bmod_[1].p,
                bmod_[2].p, mesh_spec_.p, acc_.p);
            CF(api.z2d(plan_b_, mesh_spec_.p, mesh_grid_.p));
            if (forces)
                pme_gather_kernel<P, true><<<(n + 127) / 128, 128, 0, st>>>(n, nc_, c, c8, md_, grid_.p, frac_d_.p,
                    ps_.p, q_d_.p, qc_d_.p, dqc_d_.p, mesh_grid_.p, eatom, force_s_.p, dedcn_.p);
            else if (eatom)
                pme_gather_kernel<P, false><<<(n + 127) / 128, 128, 0, st>>>(n, nc_, c, c8, md_, grid_.p, frac_d_.p,
                    ps_.p, q_d_.p, qc_d_.p, dqc_d_.p, mesh_grid_.p, eatom, force_s_.p, dedcn_.p);
        }
    }

    void record_mesh(cudaStream_t st, bool forces, double* eatom) {
        switch (order_p_) {
            case 4: record_mesh_p<4>(st, forces, eatom); break;
            case 5: record_mesh_p<5>(st, forces, eatom); break;

            case 6: record_mesh_p<6>(st, forces, eatom); break;
            default: record_mesh_p<8>(st, forces, eatom); break;
        }
    }

    Settings s_;
    std::vector<int> nref_;
    std::vector<double> cnref_, rcov_, r2r4_, c6ref_, r0ab_;
    int damp_ = kBJ;
    PairParams p_{};
    AtmParams a3_{};
    bool three_ = false, split_ = false;
    double rmax_ = 0.0, ew_beta_ = 0.0;
    int nc_ = 0, nk_ = 0;
    bool mesh_ = false;
    int order_p_ = 8;
    double spacing_A_ = 0.8;
    std::vector<double> lam_h_;
    MeshDims md_{};
    DevBuf<double> mesh_grid_, bmod_[3];
    DevBuf<cufftDoubleComplex> mesh_spec_;
    cufftHandle plan_f_ = 0, plan_b_ = 0;
    bool plans_ = false;
    DevBuf<float> chan_d_, qc_d_, dqc_d_;
    DevBuf<double> lam_d_;
    DevBuf<int3> kidx_d_;
    DevBuf<KVec> kvec_d_;
    DevBuf<double2> rho6_d_, rho8_d_;
    DevBuf<float3> frac_d_;
    int atm_proj_ = 0;
    int n_ = 0, S_ = 0, nbins_ = 0, nb_[3] = {1, 1, 1}, end_bit_ = 1;
    size_t bytes_ = 0, sort_bytes_ = 0, smem_ = 0, smem3_ = 0;
    DevBuf<Grid> grid_;
    DevBuf<float3> pw_;
    DevBuf<int> bin_of_, keys_, iota_, order_, bin_start_, species_, nref_d_;
    DevBuf<float4> ps_;
    DevBuf<double> cn_, dedcn_, force_s_, eatom_, acc_;
    DevBuf<float> w_, dw_, cnref_d_, rcov_d_, q_d_, r0_d_, c6_d_, dedcn_f_;
    DevBuf<unsigned char> sort_tmp_;
};

thread_local std::string tl_d3_error;

}  // namespace

Term* make_term(const Settings& settings, const Tables& tables, const char** why_not) {
    static thread_local std::string reason;
    auto refuse = [&](const char* text) -> Term* {
        reason = text;
        if (why_not) *why_not = reason.c_str();
        return nullptr;
    };
    if (settings.three_body && !(settings.three_body_cutoff_bohr > 0.0 &&
                                 settings.three_body_cutoff_bohr <= settings.pair_cutoff_bohr))
        return refuse("the three-body cutoff must be positive and no longer than the pair cutoff");
    if (settings.three_body && settings.smoothing_bohr >= settings.three_body_cutoff_bohr)
        return refuse("the switch width must be shorter than the three-body cutoff");
    if (settings.long_range != LongRange::None && settings.long_range != LongRange::Split)
        return refuse("the tail and mesh methods are not built in this version (PLAN.md S6-D05, S6-D06)");
    if (!(settings.pair_cutoff_bohr > 0.0) || !(settings.cn_cutoff_bohr > 0.0))
        return refuse("the cutoffs must be positive");
    if (settings.smoothing_bohr < 0.0 || settings.smoothing_bohr >= settings.pair_cutoff_bohr)
        return refuse("the switch width must lie between 0 and the pair cutoff");
    const bool zero = settings.damping == Damping::Zero || settings.damping == Damping::ZeroM;
    if (zero && !(settings.rs6 > 0.0 && settings.rs8 > 0.0))
        return refuse("the zero dampings need rs6 > 0 and rs8 > 0");
    return new D3Pair(settings, tables);
}

}  // namespace loup::dispersion

extern "C" {

const char* loup_d3_last_error(void) { return loup::dispersion::tl_d3_error.c_str(); }

int loup_d3_evaluate(const LoupD3Settings* settings, const LoupD3Tables* tables, int n_atoms,
                     const int* atomic_numbers, const double* positions, const double* cell, int repeat,
                     double* out_energy_ev, double* out_forces, double* out_virial, double* out_atom_energies,
                     double* out_ms) {
    using namespace loup::dispersion;
    tl_d3_error.clear();
    cudaStream_t st = nullptr;
    cudaGraph_t graph = nullptr;
    cudaGraphExec_t exec = nullptr;
    double *d_pos = nullptr, *d_cell = nullptr, *d_e = nullptr, *d_f = nullptr, *d_v = nullptr, *d_ae = nullptr;
    int rc = 0;
    try {
        if (!settings || !tables || !atomic_numbers || !positions || !cell || !out_energy_ev)
            throw std::invalid_argument("a required pointer is NULL");
        Settings s;
        s.damping = static_cast<Damping>(settings->damping);
        if (settings->damping < 0 || settings->damping > 3) throw std::invalid_argument("damping must be 0..3");
        s.s6 = settings->s6; s.s8 = settings->s8; s.a1 = settings->a1; s.a2 = settings->a2;
        s.rs6 = settings->rs6; s.rs8 = settings->rs8; s.alpha = settings->alpha; s.beta = settings->beta;
        s.pair_cutoff_bohr = settings->pair_cutoff_bohr;
        s.cn_cutoff_bohr = settings->cn_cutoff_bohr;
        s.smoothing_bohr = settings->smoothing_bohr;
        s.three_body = settings->three_body != 0;
        s.three_body_cutoff_bohr = settings->three_body_cutoff_bohr;
        s.long_range = static_cast<LongRange>(settings->long_range);
        s.mesh_spacing_A = settings->mesh_spacing_A;
        Tables t{tables->nref, tables->cnref, tables->rcov, tables->r2r4, tables->c6ref, tables->r0ab};
        const char* why = nullptr;
        std::unique_ptr<Term> term(make_term(s, t, &why));
        if (!term) throw std::invalid_argument(why);
        CK(cudaStreamCreateWithFlags(&st, cudaStreamNonBlocking));
        std::vector<int32_t> z(atomic_numbers, atomic_numbers + n_atoms);
        term->prepare(n_atoms, z.data(), cell, st);
        const size_t n = (size_t)n_atoms;
        CK(cudaMalloc(&d_pos, 3 * n * sizeof(double)));
        CK(cudaMalloc(&d_cell, 9 * sizeof(double)));
        CK(cudaMalloc(&d_e, sizeof(double)));
        CK(cudaMalloc(&d_f, 3 * n * sizeof(double)));
        CK(cudaMalloc(&d_v, 6 * sizeof(double)));
        CK(cudaMalloc(&d_ae, n * sizeof(double)));
        CK(cudaMemcpyAsync(d_pos, positions, 3 * n * sizeof(double), cudaMemcpyHostToDevice, st));
        CK(cudaMemcpyAsync(d_cell, cell, 9 * sizeof(double), cudaMemcpyHostToDevice, st));
        CK(cudaMemsetAsync(d_e, 0, sizeof(double), st));
        CK(cudaMemsetAsync(d_f, 0, 3 * n * sizeof(double), st));
        CK(cudaMemsetAsync(d_v, 0, 6 * sizeof(double), st));
        CK(cudaMemsetAsync(d_ae, 0, n * sizeof(double), st));
        const bool forces = out_forces || out_virial;
        Inputs in{st, d_pos, d_cell, forces, out_virial != nullptr};
        Outputs out{d_e, out_atom_energies ? d_ae : nullptr, forces ? d_f : nullptr, out_virial ? d_v : nullptr};
        // the evaluation is captured and replayed: the term must be capturable
        CK(cudaStreamBeginCapture(st, cudaStreamCaptureModeThreadLocal));
        try {
            term->record(in, out);
        } catch (...) {
            cudaStreamEndCapture(st, &graph);
            throw;
        }
        CK(cudaStreamEndCapture(st, &graph));
        CK(cudaGraphInstantiate(&exec, graph, 0));
        CK(cudaGraphLaunch(exec, st));
        CK(cudaStreamSynchronize(st));
        CK(cudaMemcpy(out_energy_ev, d_e, sizeof(double), cudaMemcpyDeviceToHost));
        if (out_forces) CK(cudaMemcpy(out_forces, d_f, 3 * n * sizeof(double), cudaMemcpyDeviceToHost));
        if (out_virial) CK(cudaMemcpy(out_virial, d_v, 6 * sizeof(double), cudaMemcpyDeviceToHost));
        if (out_atom_energies) CK(cudaMemcpy(out_atom_energies, d_ae, n * sizeof(double), cudaMemcpyDeviceToHost));
        if (repeat > 0 && out_ms) {
            cudaEvent_t a, b;
            CK(cudaEventCreate(&a));
            CK(cudaEventCreate(&b));
            CK(cudaGraphLaunch(exec, st));                     // warm
            CK(cudaEventRecord(a, st));
            for (int r = 0; r < repeat; ++r) CK(cudaGraphLaunch(exec, st));
            CK(cudaEventRecord(b, st));
            CK(cudaEventSynchronize(b));
            float ms = 0.0f;
            CK(cudaEventElapsedTime(&ms, a, b));
            *out_ms = ms / repeat;
            cudaEventDestroy(a);
            cudaEventDestroy(b);
        }
    } catch (const std::exception& e) {
        tl_d3_error = std::string("loup_d3_evaluate: ") + e.what();
        rc = -1;
    }
    if (exec) cudaGraphExecDestroy(exec);
    if (graph) cudaGraphDestroy(graph);
    for (double* p : {d_pos, d_cell, d_e, d_f, d_v, d_ae}) if (p) cudaFree(p);
    if (st) cudaStreamDestroy(st);
    return rc;
}

// A term kept across calls (the tiled execution, S6-D09): prepared once for the atoms and the cell's bin counts,
// recorded on its own stream at each call (not captured: one call per host step).
struct LoupD3 {
    std::unique_ptr<loup::dispersion::Term> term;
    cudaStream_t stream = nullptr;
    int n = 0;
    double *pos = nullptr, *cell = nullptr, *e = nullptr, *f = nullptr, *v = nullptr, *ae = nullptr;
};

LoupD3* loup_d3_create(const LoupD3Settings* settings, const LoupD3Tables* tables, int n_atoms,
                       const int* atomic_numbers, const double* cell) {
    using namespace loup::dispersion;
    tl_d3_error.clear();
    LoupD3* ctx = new LoupD3();
    try {
        if (!settings || !tables || !atomic_numbers || !cell || n_atoms < 1)
            throw std::invalid_argument("a required pointer is NULL, or no atoms");
        if (settings->damping < 0 || settings->damping > 3) throw std::invalid_argument("damping must be 0..3");
        Settings s;
        s.damping = static_cast<Damping>(settings->damping);
        s.s6 = settings->s6; s.s8 = settings->s8; s.a1 = settings->a1; s.a2 = settings->a2;
        s.rs6 = settings->rs6; s.rs8 = settings->rs8; s.alpha = settings->alpha; s.beta = settings->beta;
        s.pair_cutoff_bohr = settings->pair_cutoff_bohr;
        s.cn_cutoff_bohr = settings->cn_cutoff_bohr;
        s.smoothing_bohr = settings->smoothing_bohr;
        s.three_body = settings->three_body != 0;
        s.three_body_cutoff_bohr = settings->three_body_cutoff_bohr;
        s.long_range = static_cast<LongRange>(settings->long_range);
        s.mesh_spacing_A = settings->mesh_spacing_A;
        Tables t{tables->nref, tables->cnref, tables->rcov, tables->r2r4, tables->c6ref, tables->r0ab};
        const char* why = nullptr;
        ctx->term.reset(make_term(s, t, &why));
        if (!ctx->term) throw std::invalid_argument(why);
        CK(cudaStreamCreateWithFlags(&ctx->stream, cudaStreamNonBlocking));
        std::vector<int32_t> z(atomic_numbers, atomic_numbers + n_atoms);
        ctx->term->prepare(n_atoms, z.data(), cell, ctx->stream);
        const size_t n = (size_t)n_atoms;
        ctx->n = n_atoms;
        CK(cudaMalloc(&ctx->pos, 3 * n * sizeof(double)));
        CK(cudaMalloc(&ctx->cell, 9 * sizeof(double)));
        CK(cudaMalloc(&ctx->e, sizeof(double)));
        CK(cudaMalloc(&ctx->f, 3 * n * sizeof(double)));
        CK(cudaMalloc(&ctx->v, 6 * sizeof(double)));
        CK(cudaMalloc(&ctx->ae, n * sizeof(double)));
        return ctx;
    } catch (const std::exception& e) {
        tl_d3_error = std::string("loup_d3_create: ") + e.what();
        loup_d3_destroy(ctx);
        return nullptr;
    }
}

int loup_d3_compute(LoupD3* ctx, const double* positions, const double* cell, double* out_energy_ev,
                    double* out_forces, double* out_virial, double* out_atom_energies) {
    using namespace loup::dispersion;
    tl_d3_error.clear();
    try {
        if (!ctx || !ctx->term || !positions || !cell || !out_energy_ev)
            throw std::invalid_argument("a required pointer is NULL");
        cudaStream_t st = ctx->stream;
        const size_t n = (size_t)ctx->n;
        CK(cudaMemcpyAsync(ctx->pos, positions, 3 * n * sizeof(double), cudaMemcpyHostToDevice, st));
        CK(cudaMemcpyAsync(ctx->cell, cell, 9 * sizeof(double), cudaMemcpyHostToDevice, st));
        CK(cudaMemsetAsync(ctx->e, 0, sizeof(double), st));
        CK(cudaMemsetAsync(ctx->f, 0, 3 * n * sizeof(double), st));
        CK(cudaMemsetAsync(ctx->v, 0, 6 * sizeof(double), st));
        CK(cudaMemsetAsync(ctx->ae, 0, n * sizeof(double), st));
        const bool forces = out_forces || out_virial;
        Inputs in{st, ctx->pos, ctx->cell, forces, out_virial != nullptr};
        Outputs out{ctx->e, out_atom_energies ? ctx->ae : nullptr, forces ? ctx->f : nullptr,
                    out_virial ? ctx->v : nullptr};
        ctx->term->record(in, out);
        CK(cudaMemcpyAsync(out_energy_ev, ctx->e, sizeof(double), cudaMemcpyDeviceToHost, st));
        if (out_forces) CK(cudaMemcpyAsync(out_forces, ctx->f, 3 * n * sizeof(double), cudaMemcpyDeviceToHost, st));
        if (out_virial) CK(cudaMemcpyAsync(out_virial, ctx->v, 6 * sizeof(double), cudaMemcpyDeviceToHost, st));
        if (out_atom_energies)
            CK(cudaMemcpyAsync(out_atom_energies, ctx->ae, n * sizeof(double), cudaMemcpyDeviceToHost, st));
        CK(cudaStreamSynchronize(st));
        return 0;
    } catch (const std::exception& e) {
        tl_d3_error = std::string("loup_d3_compute: ") + e.what();
        return -1;
    }
}

size_t loup_d3_device_bytes(const LoupD3* ctx) {
    if (!ctx || !ctx->term) return 0;
    return ctx->term->device_bytes() + (size_t)ctx->n * 8 * sizeof(double) + 16 * sizeof(double);
}

void loup_d3_destroy(LoupD3* ctx) {
    if (!ctx) return;
    if (ctx->stream) cudaStreamSynchronize(ctx->stream);
    ctx->term.reset();
    for (double* p : {ctx->pos, ctx->cell, ctx->e, ctx->f, ctx->v, ctx->ae}) if (p) cudaFree(p);
    if (ctx->stream) cudaStreamDestroy(ctx->stream);
    delete ctx;
}

}  // extern "C"
