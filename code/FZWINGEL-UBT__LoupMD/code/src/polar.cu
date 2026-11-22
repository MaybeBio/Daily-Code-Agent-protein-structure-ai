#include "polar.hpp"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <cstdlib>
#include <stdexcept>
#include <string>

#include "bundle.hpp"
#include "model.hpp"
#include "warp_fold.cuh"

namespace loup {

namespace {

constexpr int KI = 32;   // floats of per-k data: n (3), k (3), kappa (FC / k^2), wproj, Bd re (4), Bd im (4),
                         // Bf re (8), Bf im (8)
constexpr double TWO_PI = 6.283185307179586476925;

__device__ __forceinline__ float silu_f(float x) { return x / (1.0f + expf(-x)); }
__device__ __forceinline__ float sig_f(float x) { return 1.0f / (1.0f + expf(-x)); }
__device__ __forceinline__ float dsilu_f(float x) {
    const float s = sig_f(x);
    return s * (1.0f + x * (1.0f - s));
}

// Fractional coordinates as 32-bit fixed point (s * 2^32 mod 2^32): k . r / 2 pi = n . s mod 1 then comes out of
// wrapping integer arithmetic exactly (to 2^-32), whatever the size of n and of the cell.
__global__ void frac_kernel(int N, const double* __restrict__ pos, const double* __restrict__ minv,
                            unsigned* __restrict__ frac) {
    const int a = blockIdx.x * blockDim.x + threadIdx.x;
    if (a >= N) return;
    const double x = pos[3 * a], y = pos[3 * a + 1], z = pos[3 * a + 2];
    // minv rows: s_d = sum_c minv[d][c] r_c (minv = inv(cell)^T)
    for (int d = 0; d < 3; ++d) {
        double s = minv[3 * d] * x + minv[3 * d + 1] * y + minv[3 * d + 2] * z;
        s -= floor(s);
        frac[3 * a + d] = (unsigned)(long long)(s * 4294967296.0);
    }
}

// sin / cos of 2 pi (n . s) from the fixed-point coordinates
__device__ __forceinline__ void kphase(const float* nk, unsigned s1, unsigned s2, unsigned s3, float& sn, float& cs) {
    const unsigned ph = (unsigned)(int)nk[0] * s1 + (unsigned)(int)nk[1] * s2 + (unsigned)(int)nk[2] * s3;
    // ph / 2^32 in [0, 1): use [-0.5, 0.5) for the best float resolution near 0
    const float f = (float)(int)ph * 2.3283064365386963e-10f;
    sincospif(2.0f * f, &sn, &cs);
}

// Structure factors per k over atoms: SC[k][j] = sum_a X[a][j] cos(theta_ak), SS likewise with sin (NC = 4, 8, 16).
// Accumulates in float32 over 1024-atom chunks (<= 8 terms per thread) and folds into double at each chunk boundary,
// avoiding 1/64-rate FP64 adds in the inner loop while matching feat_pass_kernel / grad_pass_kernel precision.
// NL < NC (S118, `mono`): only the NL columns 4 j are nonzero in X; the others are written as 0 without a pass.
template <int NC, int TK, int NL = NC>
__global__ void __launch_bounds__(TK * 32) sf_kernel_tiled(
    int N, int K, const float* __restrict__ kinfo, const unsigned* __restrict__ frac,
    const float* __restrict__ X, double* __restrict__ SC, double* __restrict__ SS) {
    constexpr int TILE = 128;
    constexpr int N4 = NC / 4;
    constexpr int LS = NL == NC ? 1 : 4;  // column stride of the live channels
    static_assert(NL == NC || NL * 4 <= NC, "live channels: all, or the columns 4 j");
    const int tid = threadIdx.x, lane = tid & 31, warp = tid >> 5;
    const int k = blockIdx.x * TK + warp;
    const bool valid_k = k < K;
    int n0 = 0, n1 = 0, n2 = 0;
    if (valid_k) {
        const float* nk = kinfo + k * KI;
        n0 = (int)nk[0]; n1 = (int)nk[1]; n2 = (int)nk[2];
    }
    __shared__ unsigned s_frac[3][TILE + 1];
    __shared__ float s_X[NL][TILE + 1];
    __shared__ double s_tot[TK][2 * NL];
    if (lane < 2 * NL) s_tot[warp][lane] = 0.0;

    for (int chunk = 0; chunk < N; chunk += 1024) {
        const int chunk_end = min(N, chunk + 1024);
        float fcs[2 * NL];  // the cos partials, then the sin partials
        float* const fc = fcs;
        float* const fs = fcs + NL;
        #pragma unroll
        for (int j = 0; j < 2 * NL; ++j) fcs[j] = 0.0f;

        for (int base = chunk; base < chunk_end; base += TILE) {
            const int cnt = min(TILE, chunk_end - base);
            __syncthreads();
            for (int i = tid; i < cnt * 3; i += TK * 32)
                s_frac[i % 3][i / 3] = __ldg(frac + (size_t)base * 3 + i);
            if constexpr (NL == NC) {
                const float4* X4 = reinterpret_cast<const float4*>(X);
                for (int i = tid; i < cnt * N4; i += TK * 32) {
                    const int al = i / N4, q = (i % N4) * 4;
                    const float4 v = __ldg(X4 + (int64_t)base * N4 + i);
                    s_X[q + 0][al] = v.x;
                    s_X[q + 1][al] = v.y;
                    s_X[q + 2][al] = v.z;
                    s_X[q + 3][al] = v.w;
                }
            } else {
                for (int i = tid; i < cnt * NL; i += TK * 32) {
                    const int al = i / NL, j = i % NL;
                    s_X[j][al] = __ldg(X + (int64_t)(base + al) * NC + j * LS);
                }
            }
            __syncthreads();
            if (valid_k) {
                for (int off = 0; off < cnt; off += 32) {
                    const int al = off + lane;
                    if (al < cnt) {
                        const unsigned ph = (unsigned)n0 * s_frac[0][al] + (unsigned)n1 * s_frac[1][al] +
                                            (unsigned)n2 * s_frac[2][al];
                        float s, c;
                        sincospif(2.0f * ((float)(int)ph * 2.3283064365386963e-10f), &s, &c);
                        #pragma unroll
                        for (int j = 0; j < NL; ++j) {
                            const float v = s_X[j][al];
                            fc[j] = fmaf(v, c, fc[j]);
                            fs[j] = fmaf(v, s, fs[j]);
                        }
                    }
                }
            }
        }
        if (valid_k) {
            // The split warp fold (src/warp_fold.cuh): the plain xor fold's sums, bit for bit, on far fewer FP64 adds.
            // Lane L ends with the sum of partial L >> SH; the first lane of each group adds it to the total.
            constexpr int SH = kWarpFoldShift<2 * NL>;
            const double tot = warp_fold_split<2 * NL>(fcs, lane);
            if ((lane & ((1 << SH) - 1)) == 0) s_tot[warp][lane >> SH] += tot;
        }
    }
    __syncwarp();
    if (valid_k && lane < NC) {
        const bool live = lane % LS == 0 && lane / LS < NL;
        SC[(int64_t)k * NC + lane] = live ? s_tot[warp][lane / LS] : 0.0;
        SS[(int64_t)k * NC + lane] = live ? s_tot[warp][NL + lane / LS] : 0.0;
    }
}

template <int NC, int NL = NC>
__global__ void __launch_bounds__(128) sf_kernel_1(int N, int K, const float* __restrict__ kinfo,
                                                   const unsigned* __restrict__ frac, const float* __restrict__ X,
                                                   double* __restrict__ SC, double* __restrict__ SS) {
    static_assert(NC % 4 == 0, "NC must be a multiple of 4 for float4 loads");
    static_assert(NL == NC || NL * 4 <= NC, "live channels: all, or the columns 4 j");
    constexpr int BLK = 128;
    constexpr int N4 = NC / 4;
    constexpr int LS = NL == NC ? 1 : 4;  // column stride of the live channels
    const int k = blockIdx.x;
    if (k >= K) return;
    const float* nk = kinfo + k * KI;
    const float n0 = nk[0], n1 = nk[1], n2 = nk[2];
    __shared__ unsigned s_frac[BLK * 3];
    __shared__ double red[4][2 * NL];
    __shared__ double tot[2 * NL];
    const int tid = threadIdx.x, lane = tid & 31, warp = tid >> 5;
    if (tid < 2 * NL) tot[tid] = 0.0;
    for (int chunk = 0; chunk < N; chunk += BLK * 8) {
        const int chunk_end = min(N, chunk + BLK * 8);
        float fcs[2 * NL];  // the cos partials, then the sin partials
        float* const fc = fcs;
        float* const fs = fcs + NL;
        #pragma unroll
        for (int j = 0; j < 2 * NL; ++j) fcs[j] = 0.0f;
        for (int base = chunk; base < chunk_end; base += BLK) {
            const int cnt = min(BLK, chunk_end - base);
            __syncthreads();
            for (int i = tid; i < cnt * 3; i += BLK) s_frac[i] = frac[(size_t)base * 3 + i];
            __syncthreads();
            if (tid < cnt) {
                const unsigned ph = (unsigned)(int)n0 * s_frac[3 * tid] + (unsigned)(int)n1 * s_frac[3 * tid + 1] +
                                    (unsigned)(int)n2 * s_frac[3 * tid + 2];
                float s, c;
                sincospif(2.0f * ((float)(int)ph * 2.3283064365386963e-10f), &s, &c);
                const int a = base + tid;
                if constexpr (NL == NC) {
                    const float4* X4 = reinterpret_cast<const float4*>(X);
                    #pragma unroll
                    for (int q = 0; q < N4; ++q) {
                        const float4 v = __ldg(X4 + (int64_t)a * N4 + q);
                        fc[4 * q + 0] = fmaf(v.x, c, fc[4 * q + 0]);
                        fs[4 * q + 0] = fmaf(v.x, s, fs[4 * q + 0]);
                        fc[4 * q + 1] = fmaf(v.y, c, fc[4 * q + 1]);
                        fs[4 * q + 1] = fmaf(v.y, s, fs[4 * q + 1]);
                        fc[4 * q + 2] = fmaf(v.z, c, fc[4 * q + 2]);
                        fs[4 * q + 2] = fmaf(v.z, s, fs[4 * q + 2]);
                        fc[4 * q + 3] = fmaf(v.w, c, fc[4 * q + 3]);
                        fs[4 * q + 3] = fmaf(v.w, s, fs[4 * q + 3]);
                    }
                } else {
                    #pragma unroll
                    for (int j = 0; j < NL; ++j) {
                        const float v = __ldg(X + (int64_t)a * NC + j * LS);
                        fc[j] = fmaf(v, c, fc[j]);
                        fs[j] = fmaf(v, s, fs[j]);
                    }
                }
            }
        }
        {  // the split warp fold, as in sf_kernel_tiled
            constexpr int SH = kWarpFoldShift<2 * NL>;
            const double part = warp_fold_split<2 * NL>(fcs, lane);
            if ((lane & ((1 << SH) - 1)) == 0) red[warp][lane >> SH] = part;
        }
        __syncthreads();
        if (tid < 2 * NL) {
            double v = 0.0;
            #pragma unroll
            for (int w = 0; w < 4; ++w) v += red[w][tid];
            tot[tid] += v;
        }
    }
    __syncthreads();
    if (tid < 2 * NC) {
        const int j = tid % NC;
        const bool live = j % LS == 0 && j / LS < NL;
        (tid < NC ? SC : SS)[(int64_t)k * NC + j] = live ? tot[(tid < NC ? 0 : NL) + j / LS] : 0.0;
    }
}

template <int NC, int NL = NC>
static void launch_sf(cudaStream_t st, int N, int K, const float* kinfo, const unsigned* frac, const float* X,
                      double* SC, double* SS) {
    if (K >= 288) sf_kernel_tiled<NC, 8, NL><<<(K + 7) / 8, 256, 0, st>>>(N, K, kinfo, frac, X, SC, SS);
    else if (K >= 144) sf_kernel_tiled<NC, 4, NL><<<(K + 3) / 4, 128, 0, st>>>(N, K, kinfo, frac, X, SC, SS);
    else sf_kernel_1<NC, NL><<<K, 128, 0, st>>>(N, K, kinfo, frac, X, SC, SS);
}

// Forward feature coefficients per k and spin channel: rho from the structure factors, V = kappa rho,
// AB[k][ch][0..7] = beta w (Vr Pr + Vi Pi), AB[k][ch][8..15] = beta w (Vr Pi - Vi Pr).
__global__ void feat_coef_kernel(int K, const float* __restrict__ kinfo, float alpha, float beta,
                                 const double* __restrict__ SC, const double* __restrict__ SS, float* __restrict__ AB) {
    const int k = blockIdx.x * blockDim.x + threadIdx.x;
    if (k >= K) return;
    const float* ki = kinfo + k * KI;
    const float kap = ki[6], w = ki[7];
    for (int ch = 0; ch < 2; ++ch) {
        double rr = 0.0, ri = 0.0;
        for (int m = 0; m < 4; ++m) {
            const double c = SC[k * 8 + ch * 4 + m], s = SS[k * 8 + ch * 4 + m];
            const double br = ki[8 + m], bi = ki[12 + m];
            rr += br * c + bi * s;
            ri += bi * c - br * s;
        }
        const float vr = (float)(kap * alpha * rr), vi = (float)(kap * alpha * ri);
        for (int j = 0; j < 8; ++j) {
            const float pr = ki[16 + j], pi = ki[24 + j];
            AB[(k * 2 + ch) * 16 + j] = beta * w * (vr * pr + vi * pi);
            AB[(k * 2 + ch) * 16 + 8 + j] = beta * w * (vr * pi - vi * pr);
        }
    }
}

// f[a][ch][j] = sum_k AB_A cos + AB_B sin (2 channels x 8). One thread per atom, k-data tiled in shared memory.
// blockIdx.y takes the k range [y kc, (y + 1) kc): with one thread per atom a few thousand atoms fill under one
// warp per scheduler, so the k sum is split over blocks. With gridDim.y > 1 each chunk writes its double sums to
// part[y][a][16] and k_reduce_kernel adds the chunks in order (deterministic).
// MONO (S118, `mono`): only the raw features j = 0, 4 (the two widths' potentials) reach a nonzero weight; they are
// summed as before and the other 12 are written as 0.
template <bool MONO>
__global__ void __launch_bounds__(128) feat_pass_kernel(int N, int K, int kc, const float* __restrict__ kinfo,
                                                        const unsigned* __restrict__ frac, const float* __restrict__ AB,
                                                        float* __restrict__ f, double* __restrict__ part) {
    constexpr int TK = 64;
    constexpr int FPC = MONO ? 2 : 8;  // summed features per channel: raw j = i JS
    constexpr int JS = MONO ? 4 : 1;
    constexpr int NF = 2 * FPC;
    __shared__ float sk[TK][3];
    __shared__ float sab[TK][2 * NF];  // per k: [ch][A | B][FPC]
    const int a = blockIdx.x * blockDim.x + threadIdx.x;
    unsigned s1 = 0, s2 = 0, s3 = 0;
    if (a < N) {
        s1 = frac[3 * a];
        s2 = frac[3 * a + 1];
        s3 = frac[3 * a + 2];
    }
    double accd[NF];
    #pragma unroll
    for (int j = 0; j < NF; ++j) accd[j] = 0.0;
    const int kb = blockIdx.y * kc, ke = min(K, kb + kc);
    for (int k0 = kb; k0 < ke; k0 += TK) {
        const int nk = min(TK, ke - k0);
        __syncthreads();
        for (int i = threadIdx.x; i < nk * 3; i += blockDim.x) sk[i / 3][i % 3] = kinfo[(k0 + i / 3) * KI + i % 3];
        for (int i = threadIdx.x; i < nk * 2 * NF; i += blockDim.x) {
            const int r = i % (2 * NF), ch = r / (2 * FPC), ab = (r / FPC) % 2, fi = r % FPC;
            sab[i / (2 * NF)][r] = AB[(int64_t)(k0 + i / (2 * NF)) * 32 + ch * 16 + ab * 8 + fi * JS];
        }
        __syncthreads();
        float acc[NF];  // per-tile partial sums, folded into double accumulators
        #pragma unroll
        for (int j = 0; j < NF; ++j) acc[j] = 0.0f;
        for (int kk = 0; kk < nk; ++kk) {
            float s, c;
            kphase(sk[kk], s1, s2, s3, s, c);
            #pragma unroll
            for (int ch = 0; ch < 2; ++ch)
                #pragma unroll
                for (int j = 0; j < FPC; ++j)
                    acc[ch * FPC + j] = fmaf(sab[kk][ch * 2 * FPC + j], c,
                                             fmaf(sab[kk][ch * 2 * FPC + FPC + j], s, acc[ch * FPC + j]));
        }
        #pragma unroll
        for (int j = 0; j < NF; ++j) accd[j] += (double)acc[j];
    }
    if (a < N) {
        #pragma unroll
        for (int j = 0; j < 16; ++j) {
            const int ch = j / 8, jr = j % 8;
            const double v = jr % JS == 0 && jr / JS < FPC ? accd[ch * FPC + jr / JS] : 0.0;
            if (gridDim.y == 1) f[(int64_t)a * 16 + j] = (float)v;
            else part[((int64_t)blockIdx.y * N + a) * 16 + j] = v;
        }
    }
}

// Backward coefficients per k. Features mode (energy_mode 0, 2 channels): from GA/GB (structure factors of the
// feature gradient g, nc = 16 as [ch][j]) -> dV -> drho; energy mode (1 channel): drho = 2 V/(2pi)^6 kappa rho with
// rho from the charge structure factors. Output per k and channel: Dq[4], Eq[4] in dk[k][ch][8].
__global__ void bwd_coef_kernel(int K, int nch, int energy_mode, const float* __restrict__ kinfo, float alpha,
                                float beta, float e_scale, const double* __restrict__ GA, const double* __restrict__ GB,
                                const double* __restrict__ SC, const double* __restrict__ SS, float* __restrict__ dk) {
    const int k = blockIdx.x * blockDim.x + threadIdx.x;
    if (k >= K) return;
    const float* ki = kinfo + k * KI;
    const float kap = ki[6], w = ki[7];
    for (int ch = 0; ch < nch; ++ch) {
        float dvr = 0.0f, dvi = 0.0f;
        if (energy_mode) {
            double rr = 0.0, ri = 0.0;
            for (int m = 0; m < 4; ++m) {
                const double c = SC[k * 4 + m], s = SS[k * 4 + m];
                rr += ki[8 + m] * c + ki[12 + m] * s;
                ri += ki[12 + m] * c - ki[8 + m] * s;
            }
            // E = e_scale sum_k kappa |rho|^2, rho = alpha (rr, ri): dE/drho = 2 e_scale kappa rho; expressed as dV
            // with drho = kappa dV below, so dV = 2 e_scale rho
            dvr = (float)(2.0 * e_scale * alpha * rr);
            dvi = (float)(2.0 * e_scale * alpha * ri);
        } else {
            for (int j = 0; j < 8; ++j) {
                const float ga = (float)GA[(int64_t)k * 16 + ch * 8 + j], gb = (float)GB[(int64_t)k * 16 + ch * 8 + j];
                const float pr = ki[16 + j], pi = ki[24 + j];
                dvr += ga * pr + gb * pi;
                dvi += ga * pi - gb * pr;
            }
            dvr *= beta * w;
            dvi *= beta * w;
        }
        const float drr = kap * dvr, dri = kap * dvi;
        for (int m = 0; m < 4; ++m) {
            const float br = ki[8 + m], bi = ki[12 + m];
            dk[(k * nch + ch) * 8 + m] = alpha * (drr * br + dri * bi);
            dk[(k * nch + ch) * 8 + 4 + m] = alpha * (drr * bi - dri * br);
        }
    }
}

// The k-space terms' strain derivative (MACE PR 1718 / FastMACE: the features and the energy see the strained cell):
// theta = k . r is strain invariant, k -> (I - eps) k and V -> V (1 + tr eps), so
// dE/deps_ab = -sum_k (dE/dk_a) k_b + delta_ab V dE/dV, with dE/dk through the GTO bases and kappa = FC / k^2 and
// dE/dV through alpha = (2 pi)^3 / V and e_scale = V / (2 pi)^6. Features mode (2 channels): SCq/SSq the charge
// structure factors of the step, GA/GB those of the feature gradient; energy mode (1 channel): SCq/SSq of the total
// charge. Accumulated into virial (xx, xy, xz, yy, yz, zz).
struct BasisConsts {
    float a0, a1, sd2;          // density: Br_0 = a0 e, Bi_{1+m} = -a1 e kp_m, e = exp(-sd2 k^2 / 2)
    float b0[2], b1[2], sf2[2]; // features, per sigma
};

__device__ __forceinline__ void basis_grad(float a0, float a1, float s2, float kx, float ky, float kz, float k2,
                                           float gr0, const float* gim, float& gx, float& gy, float& gz) {
    // gr0 = dE/dBr_0, gim[m] = dE/dBi_{1+m}; kp = (ky, kz, kx)
    const float e = expf(-0.5f * s2 * k2);
    const float br0 = a0 * e;
    gx += gr0 * (-s2 * kx * br0);
    gy += gr0 * (-s2 * ky * br0);
    gz += gr0 * (-s2 * kz * br0);
    const float kp[3] = {ky, kz, kx};
    float sdot = 0.0f;
    for (int m = 0; m < 3; ++m) sdot += gim[m] * kp[m];
    // d(-a1 e kp_m)/dk_a = -a1 e (delta(a, perm m) - s2 kp_m k_a)
    gy += -a1 * e * gim[0];
    gz += -a1 * e * gim[1];
    gx += -a1 * e * gim[2];
    gx += a1 * e * s2 * sdot * kx;
    gy += a1 * e * s2 * sdot * ky;
    gz += a1 * e * s2 * sdot * kz;
}

__global__ void lr_virial_kernel(int K, int energy_mode, const float* __restrict__ kinfo, BasisConsts bc, float alpha,
                                 float beta, float e_scale, const double* __restrict__ SCq, const double* __restrict__ SSq,
                                 const double* __restrict__ GA, const double* __restrict__ GB, double* __restrict__ virial) {
    const int k = blockIdx.x * blockDim.x + threadIdx.x;
    double v[6] = {0, 0, 0, 0, 0, 0};
    if (k > 0 && k < K) {  // k = 0 does not move under strain and has kappa = 0
        const float* ki = kinfo + k * KI;
        const float kx = ki[3], ky = ki[4], kz = ki[5];
        const float k2 = kx * kx + ky * ky + kz * kz;
        const float kap = ki[6], w = ki[7];
        float dkap = 0.0f;
        double vol_term = 0.0;  // V dE/dV
        float gBr0 = 0.0f, gBi[3] = {0, 0, 0};
        float gPr[2] = {0, 0}, gPi[2][3] = {{0, 0, 0}, {0, 0, 0}};
        const int nch = energy_mode ? 1 : 2;
        for (int ch = 0; ch < nch; ++ch) {
            const int ld = energy_mode ? 4 : 8;
            float SC[4], SS[4];
            double rrd = 0.0, rid = 0.0;
            for (int m = 0; m < 4; ++m) {
                const double c = SCq[k * ld + ch * 4 + m], s = SSq[k * ld + ch * 4 + m];
                SC[m] = (float)c;
                SS[m] = (float)s;
                rrd += ki[8 + m] * c + ki[12 + m] * s;
                rid += ki[12 + m] * c - ki[8 + m] * s;
            }
            const float rr = (float)rrd, ri = (float)rid;
            const float pr_ = alpha * rr, pi_ = alpha * ri;
            float drr, dri;
            if (energy_mode) {
                // E_k = e_scale kappa alpha^2 |rr|^2 scales as 1 / V: V dE_k/dV = -E_k (no -2E + E cancellation)
                const double rho2 = (double)alpha * alpha * (rrd * rrd + rid * rid);
                dkap += (float)(e_scale * rho2);
                vol_term -= (double)e_scale * kap * rho2;
                drr = 2.0f * e_scale * kap * pr_;
                dri = 2.0f * e_scale * kap * pi_;
            } else {
                const float Vr = kap * pr_, Vi = kap * pi_;
                float dVr = 0.0f, dVi = 0.0f;
                for (int j = 0; j < 8; ++j) {
                    const float ga = GA[(int64_t)k * 16 + ch * 8 + j], gb = GB[(int64_t)k * 16 + ch * 8 + j];
                    const float pr = ki[16 + j], pi = ki[24 + j];
                    dVr += ga * pr + gb * pi;
                    dVi += ga * pi - gb * pr;
                    // dE/dPr_j, dE/dPi_j (Pr only at m = 0, Pi only at m = 1..3)
                    const int s = j / 4, m = j % 4;
                    if (m == 0) gPr[s] += beta * w * (ga * Vr - gb * Vi);
                    else gPi[s][m - 1] += beta * w * (ga * Vi + gb * Vr);
                }
                dVr *= beta * w;
                dVi *= beta * w;
                dkap += dVr * pr_ + dVi * pi_;
                drr = kap * dVr;
                dri = kap * dVi;
                // the features scale as alpha (1 / V): V dE/dV = -alpha dE/dalpha
                vol_term -= (double)drr * rrd * alpha + (double)dri * rid * alpha;
            }
            gBr0 += alpha * (drr * SC[0] - dri * SS[0]);
            for (int m = 1; m < 4; ++m) gBi[m - 1] += alpha * (drr * SS[m] + dri * SC[m]);
        }
        float gx = 0.0f, gy = 0.0f, gz = 0.0f;
        // kappa = FC / k^2
        const float dk = -2.0f * kap / k2 * dkap;
        gx += dk * kx;
        gy += dk * ky;
        gz += dk * kz;
        basis_grad(bc.a0, bc.a1, bc.sd2, kx, ky, kz, k2, gBr0, gBi, gx, gy, gz);
        if (!energy_mode)
            for (int s = 0; s < 2; ++s) basis_grad(bc.b0[s], bc.b1[s], bc.sf2[s], kx, ky, kz, k2, gPr[s], gPi[s], gx, gy, gz);
        v[0] = -(double)gx * kx + vol_term;
        v[1] = -0.5 * ((double)gx * ky + (double)gy * kx);
        v[2] = -0.5 * ((double)gx * kz + (double)gz * kx);
        v[3] = -(double)gy * ky + vol_term;
        v[4] = -0.5 * ((double)gy * kz + (double)gz * ky);
        v[5] = -(double)gz * kz + vol_term;
    }
    #pragma unroll
    for (int c = 0; c < 6; ++c) {
        double x = v[c];
        #pragma unroll
        for (int off = 16; off > 0; off >>= 1) x += __shfl_xor_sync(0xffffffffu, x, off);
        if ((threadIdx.x & 31) == 0 && x != 0.0) atomicAdd(virial + c, x);
    }
}

// Per-atom backward over k: dq[a][ch][m] += sum_k Dq c + Eq s; dtheta = sum_m q (-Dq s + Eq c)
// + sum_j g (-A s + B c) (receiver side, features mode); forces[a] -= sum_k dtheta k.
// k range over blockIdx.y as in feat_pass_kernel; with gridDim.y > 1 the chunk's dq sums (NCH * 4) and force terms
// (3) go to part[y][a][11] and k_reduce_kernel applies them in chunk order.
// MONO (S118, `mono`): q is nonzero on the monopoles only, g on the raw features j = 0, 4 only, and the dipoles' dq
// reaches only zero weights: the sums run over those columns (the dropped terms were fma(0, x, dth) = dth), dq is
// updated on the monopoles only.
template <int NCH, bool RECV, bool MONO = false>
__global__ void __launch_bounds__(128) grad_pass_kernel(int N, int K, int kc, const float* __restrict__ kinfo,
                                                        const unsigned* __restrict__ frac, const float* __restrict__ q,
                                                        int q_stride, const float* __restrict__ dk,
                                                        const float* __restrict__ g, const float* __restrict__ AB,
                                                        float* __restrict__ dq, int dq_stride, double* __restrict__ forces,
                                                        double* __restrict__ part) {
    constexpr int TK = 32;
    constexpr int NM = MONO ? 1 : 4;  // charge components per channel
    constexpr int GF = MONO ? 2 : 8;  // feature-gradient columns per channel: raw j = f GS
    constexpr int GS = MONO ? 4 : 1;
    __shared__ float sk[TK][6];
    __shared__ float sd[TK][NCH * 2 * NM];        // per k: [ch][D | E][NM]
    __shared__ float sab[TK][RECV ? 4 * GF : 1];  // per k: [ch][A | B][GF]
    const int a = blockIdx.x * blockDim.x + threadIdx.x;
    unsigned s1 = 0, s2 = 0, s3 = 0;
    float qa[NCH * NM], ga[RECV ? 2 * GF : 1];
    #pragma unroll
    for (int j = 0; j < NCH * NM; ++j) qa[j] = 0.0f;
    if (a < N) {
        s1 = frac[3 * a];
        s2 = frac[3 * a + 1];
        s3 = frac[3 * a + 2];
        #pragma unroll
        for (int ch = 0; ch < NCH; ++ch)
            #pragma unroll
            for (int m = 0; m < NM; ++m) qa[ch * NM + m] = q[(int64_t)a * q_stride + ch * 4 + m];
        if (RECV)
            #pragma unroll
            for (int j = 0; j < 2 * GF; ++j) ga[j] = g[(int64_t)a * 16 + (j / GF) * 8 + (j % GF) * GS];
    }
    double dqd[NCH * NM], fxd = 0.0, fyd = 0.0, fzd = 0.0;
    #pragma unroll
    for (int j = 0; j < NCH * NM; ++j) dqd[j] = 0.0;
    const int kb = blockIdx.y * kc, ke = min(K, kb + kc);
    for (int k0 = kb; k0 < ke; k0 += TK) {
        float dqa[NCH * NM];  // per-tile partial sums, folded into double accumulators
        #pragma unroll
        for (int j = 0; j < NCH * NM; ++j) dqa[j] = 0.0f;
        float fx = 0.0f, fy = 0.0f, fz = 0.0f;
        const int nk = min(TK, ke - k0);
        __syncthreads();
        for (int i = threadIdx.x; i < nk * 6; i += blockDim.x) sk[i / 6][i % 6] = kinfo[(k0 + i / 6) * KI + i % 6];
        for (int i = threadIdx.x; i < nk * NCH * 2 * NM; i += blockDim.x) {
            const int r = i % (NCH * 2 * NM), ch = r / (2 * NM), de = (r / NM) % 2, m = r % NM;
            sd[i / (NCH * 2 * NM)][r] = dk[(int64_t)(k0 + i / (NCH * 2 * NM)) * NCH * 8 + ch * 8 + de * 4 + m];
        }
        if (RECV)
            for (int i = threadIdx.x; i < nk * 4 * GF; i += blockDim.x) {
                const int r = i % (4 * GF), ch = r / (2 * GF), ab = (r / GF) % 2, f = r % GF;
                sab[i / (4 * GF)][r] = AB[(int64_t)(k0 + i / (4 * GF)) * 32 + ch * 16 + ab * 8 + f * GS];
            }
        __syncthreads();
        for (int kk = 0; kk < nk; ++kk) {
            float s, c;
            kphase(sk[kk], s1, s2, s3, s, c);
            float dth = 0.0f;
            #pragma unroll
            for (int ch = 0; ch < NCH; ++ch)
                #pragma unroll
                for (int m = 0; m < NM; ++m) {
                    const float D = sd[kk][ch * 2 * NM + m], Ee = sd[kk][ch * 2 * NM + NM + m];
                    dqa[ch * NM + m] = fmaf(D, c, fmaf(Ee, s, dqa[ch * NM + m]));
                    dth = fmaf(qa[ch * NM + m], Ee * c - D * s, dth);
                }
            if (RECV) {
                #pragma unroll
                for (int ch = 0; ch < 2; ++ch)
                    #pragma unroll
                    for (int j = 0; j < GF; ++j)
                        dth = fmaf(ga[ch * GF + j], sab[kk][ch * 2 * GF + GF + j] * c - sab[kk][ch * 2 * GF + j] * s,
                                   dth);
            }
            fx = fmaf(dth, sk[kk][3], fx);
            fy = fmaf(dth, sk[kk][4], fy);
            fz = fmaf(dth, sk[kk][5], fz);
        }
        #pragma unroll
        for (int j = 0; j < NCH * NM; ++j) dqd[j] += (double)dqa[j];
        fxd += fx;
        fyd += fy;
        fzd += fz;
    }
    if (a < N) {
        if (gridDim.y == 1) {
            #pragma unroll
            for (int ch = 0; ch < NCH; ++ch)
                #pragma unroll
                for (int m = 0; m < NM; ++m) dq[(int64_t)a * dq_stride + ch * 4 + m] += (float)dqd[ch * NM + m];
            atomicAdd(forces + 3 * a, -fxd);
            atomicAdd(forces + 3 * a + 1, -fyd);
            atomicAdd(forces + 3 * a + 2, -fzd);
        } else {
            double* p = part + ((int64_t)blockIdx.y * N + a) * 11;
            #pragma unroll
            for (int j = 0; j < NCH * 4; ++j) p[j] = j % 4 < NM ? dqd[(j / 4) * NM + j % 4] : 0.0;
            p[8] = fxd;
            p[9] = fyd;
            p[10] = fzd;
        }
    }
}

// The k chunks' partial sums in chunk order. width 16: f[a][j] = sum_y part (feat_pass). width 11: dq[a][j] +=
// sum_y part[..][j] (j < ndq), forces[a] -= sum_y part[..][8..10] (grad_pass).
__global__ void k_reduce_kernel(int N, int ks, int width, int ndq, const double* __restrict__ part,
                                float* __restrict__ out, int out_stride, double* __restrict__ forces) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= N * width) return;
    const int a = i / width, j = i - a * width;
    if (width == 11 && j >= ndq && j < 8) return;  // slots grad_pass<1> does not write
    double s = 0.0;
    for (int y = 0; y < ks; ++y) s += part[((int64_t)y * N + a) * width + j];
    if (width == 16) out[(int64_t)a * 16 + j] = (float)s;
    else if (j < 8) { if (j < ndq) out[(int64_t)a * out_stride + j] += (float)s; }
    else atomicAdd(forces + 3 * a + (j - 8), -s);
}

// SF of the feature gradient needs g [N][16]; the energy needs SF of qt = q_a + q_b [N][4]
__global__ void qtot_kernel(int N, const float* __restrict__ q, float* __restrict__ qt) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= N * 4) return;
    const int a = i / 4, m = i % 4;
    qt[i] = q[a * 8 + m] + q[a * 8 + 4 + m];
}

__global__ void energy_kernel(int K, const float* __restrict__ kinfo, float alpha, float e_scale,
                              const double* __restrict__ SC, const double* __restrict__ SS, double* __restrict__ energy) {
    const int k = blockIdx.x * blockDim.x + threadIdx.x;
    double e = 0.0;
    if (k < K) {
        const float* ki = kinfo + k * KI;
        double rr = 0.0, ri = 0.0;
        for (int m = 0; m < 4; ++m) {
            rr += ki[8 + m] * SC[k * 4 + m] + ki[12 + m] * SS[k * 4 + m];
            ri += ki[12 + m] * SC[k * 4 + m] - ki[8 + m] * SS[k * 4 + m];
        }
        rr *= alpha;
        ri *= alpha;
        e = (double)e_scale * (double)ki[6] * (rr * rr + ri * ri);
    }
    #pragma unroll
    for (int off = 16; off > 0; off >>= 1) e += __shfl_xor_sync(0xffffffffu, e, off);
    if ((threadIdx.x & 31) == 0 && e != 0.0) atomicAdd(energy, e);
}

// pot[a][ch*8+j] = (f[a][ch][perm j] - si_j q[a][ch][idx j]) / norms_j
struct FeatConsts {
    float norms[8], si[8];
    int idx[8], perm[8];
};

__global__ void pot_fwd_kernel(int N, FeatConsts fc, const float* __restrict__ f, const float* __restrict__ q,
                               float* __restrict__ pot) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= N * 16) return;
    const int a = i / 16, ch = (i % 16) / 8, j = i % 8;
    pot[i] = (f[a * 16 + ch * 8 + fc.perm[j]] - fc.si[j] * q[a * 8 + ch * 4 + fc.idx[j]]) / fc.norms[j];
}

// g[a][ch][perm j] = dpot / norms (the gradient of the raw features); dq[a][ch][idx j] -= si_j dpot / norms
__global__ void pot_bwd_kernel(int N, FeatConsts fc, const float* __restrict__ dpot, float* __restrict__ g,
                               float* __restrict__ dq) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= N * 2) return;
    const int a = i / 2, ch = i % 2;
    for (int j = 0; j < 8; ++j) {
        const float d = dpot[a * 16 + ch * 8 + j] / fc.norms[j];
        g[a * 16 + ch * 8 + fc.perm[j]] = d;
        dq[a * 8 + ch * 4 + fc.idx[j]] -= fc.si[j] * d;
    }
}

__global__ void add_bias_kernel(int64_t rows, int cols, const float* __restrict__ b, float* __restrict__ x, int ld) {
    const int64_t i = (int64_t)blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= rows * cols) return;
    x[(i / cols) * ld + i % cols] += b[i % cols];
}

// Bias + LayerNorm (eps 1e-5, biased variance) + SiLU per row, one warp per row (H <= 256). z += b in place (the
// backward reads the biased pre-activation; each lane rereads only the elements it wrote), then out = silu(LN(z)).
__global__ void bias_ln_silu_fwd_kernel(int N, int H, const float* __restrict__ b, float* __restrict__ z,
                                        const float* __restrict__ g, const float* __restrict__ be,
                                        float* __restrict__ out, float* __restrict__ stat) {
    const int r = blockIdx.x * (blockDim.x >> 5) + (threadIdx.x >> 5), lane = threadIdx.x & 31;
    if (r >= N) return;
    float* zr = z + (int64_t)r * H;
    float s = 0.0f;
    for (int j = lane; j < H; j += 32) {
        const float v = zr[j] + b[j];
        zr[j] = v;
        s += v;
    }
    #pragma unroll
    for (int off = 16; off > 0; off >>= 1) s += __shfl_xor_sync(0xffffffffu, s, off);
    const float mean = s / H;
    float s2 = 0.0f;  // two-pass variance (no E[x^2] - mean^2 cancellation)
    for (int j = lane; j < H; j += 32) s2 += (zr[j] - mean) * (zr[j] - mean);
    #pragma unroll
    for (int off = 16; off > 0; off >>= 1) s2 += __shfl_xor_sync(0xffffffffu, s2, off);
    const float var = s2 / H;
    const float rstd = 1.0f / sqrtf(var + 1e-5f);
    for (int j = lane; j < H; j += 32) {
        const float y = g[j] * (zr[j] - mean) * rstd + be[j];
        out[(int64_t)r * H + j] = silu_f(y);
    }
    if (lane == 0) {
        stat[2 * r] = mean;
        stat[2 * r + 1] = rstd;
    }
}

// dz from dout (gradient of the SiLU output)
// May run in place (dz == dout): each element is read before the same thread overwrites it.
__global__ void ln_silu_bwd_kernel(int N, int H, const float* __restrict__ z, const float* __restrict__ g,
                                   const float* __restrict__ be, const float* __restrict__ stat, const float* dout,
                                   float* dz) {
    const int r = blockIdx.x * (blockDim.x >> 5) + (threadIdx.x >> 5), lane = threadIdx.x & 31;
    if (r >= N) return;
    const float mean = stat[2 * r], rstd = stat[2 * r + 1];
    float m1 = 0.0f, m2 = 0.0f;
    for (int j = lane; j < H; j += 32) {
        const float xh = (z[(int64_t)r * H + j] - mean) * rstd;
        const float y = g[j] * xh + be[j];
        const float dxh = dout[(int64_t)r * H + j] * dsilu_f(y) * g[j];
        m1 += dxh;
        m2 += dxh * xh;
    }
    #pragma unroll
    for (int off = 16; off > 0; off >>= 1) {
        m1 += __shfl_xor_sync(0xffffffffu, m1, off);
        m2 += __shfl_xor_sync(0xffffffffu, m2, off);
    }
    m1 /= H;
    m2 /= H;
    for (int j = lane; j < H; j += 32) {
        const float xh = (z[(int64_t)r * H + j] - mean) * rstd;
        const float y = g[j] * xh + be[j];
        const float dxh = dout[(int64_t)r * H + j] * dsilu_f(y) * g[j];
        dz[(int64_t)r * H + j] = rstd * (dxh - m1 - xh * m2);
    }
}

// inv[a][u] = sum_l sum_m fm_l[a][m][u] Z_l[a][m][u]; x0 = [inv, emb[sp[a]]]
__global__ void inv_kernel(int N, int C, int lmax, const float* __restrict__ f0, const float* __restrict__ f1,
                           const float* __restrict__ f2, const float* __restrict__ z0, const float* __restrict__ z1,
                           const float* __restrict__ z2, const float* __restrict__ emb, const int* __restrict__ sp,
                           float* __restrict__ x0) {
    const int64_t i = (int64_t)blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= (int64_t)N * C) return;
    const int a = (int)(i / C), u = (int)(i % C);
    float s = f0[(int64_t)a * C + u] * z0[(int64_t)a * C + u];
    if (lmax >= 1)
        for (int m = 0; m < 3; ++m) s += f1[((int64_t)a * 3 + m) * C + u] * z1[((int64_t)a * 3 + m) * C + u];
    if (lmax >= 2)
        for (int m = 0; m < 5; ++m) s += f2[((int64_t)a * 5 + m) * C + u] * z2[((int64_t)a * 5 + m) * C + u];
    x0[(int64_t)a * 2 * C + u] = s;
    if (emb) x0[(int64_t)a * 2 * C + C + u] = emb[(int64_t)sp[a] * C + u];
}

// out_l[a][m][u] = x_l[a][m][u] * (P[a][u] + pb[u])  (mode "l x 0 -> l"; pb: the folded update's bias, or nullptr)
__global__ void bcast_mul_kernel(int64_t n, int C, int d, const float* __restrict__ x, const float* __restrict__ P,
                                 const float* __restrict__ pb, float* __restrict__ out) {
    const int64_t i = (int64_t)blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= n) return;
    const int64_t a = i / ((int64_t)d * C);
    const int u = (int)(i % C);
    const float p = pb ? P[a * C + u] + pb[u] : P[a * C + u];
    out[i] = x[i] * p;
}

// reverse of bcast_mul and of the inv contraction for one degree: dx += dout * (P + pb) (bcast),
// dP[a][u] += sum_m dout x
__global__ void bcast_mul_bwd_kernel(int N, int C, int d, const float* __restrict__ x, const float* __restrict__ P,
                                     const float* __restrict__ pb, const float* __restrict__ dout,
                                     float* __restrict__ dx, float* __restrict__ dP, int dP_ld) {
    const int64_t i = (int64_t)blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= (int64_t)N * C) return;
    const int a = (int)(i / C), u = (int)(i % C);
    const float p = pb ? P[(int64_t)a * dP_ld + u] + pb[u] : P[(int64_t)a * dP_ld + u];
    float acc = 0.0f;
    for (int m = 0; m < d; ++m) {
        const int64_t idx = ((int64_t)a * d + m) * C + u;
        if (dx) dx[idx] += dout[idx] * p;
        acc += dout[idx] * x[idx];
    }
    if (dP) dP[(int64_t)a * dP_ld + u] = acc;
}

// inv contraction backward for one degree: dfm += dinv * Z (bcast), dZ = dinv * fm
__global__ void inv_bwd_kernel(int64_t n, int C, int d, const float* __restrict__ dinv, int dinv_ld,
                               const float* __restrict__ fm, const float* __restrict__ Z, float* __restrict__ dfm,
                               float* __restrict__ dZ) {
    const int64_t i = (int64_t)blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= n) return;
    const int64_t a = i / ((int64_t)d * C);
    const float g = dinv[a * dinv_ld + i % C];
    dfm[i] += g * Z[i];
    dZ[i] = g * fm[i];
}

// Gated readout of the SCF update (H = 32 scalars, 32 gates, 32 vectors), one warp per atom. S124: without vectors
// (lmax 0, !has_v) both gates multiply zeros, so the scalar path runs alone: s0's gate half is neither computed (the
// GEMM writes the scalar half only) nor read, smid's gate half and vmid are neither written nor read, and ds0's gate
// half is not written (the backward GEMM reads the scalar half only). The sums are the same, minus exact zero terms.
struct RoConsts {
    float cs, cg;
};

__global__ void ro_fwd_kernel(int N, RoConsts rc, int has_v, const float* __restrict__ s0,
                              const float* __restrict__ v1, const float* __restrict__ Wm0, const float* __restrict__ bm,
                              const float* __restrict__ Wm1, const float* __restrict__ W2, const float* __restrict__ b2,
                              float* __restrict__ smid, float* __restrict__ vmid, float* __restrict__ out) {
    const int a = blockIdx.x * (blockDim.x >> 5) + (threadIdx.x >> 5), h = threadIdx.x & 31;
    if (a >= N) return;
    __shared__ float sh[4][4][32];  // per warp: a0 / a1 (3)
    float (*S)[32] = sh[threadIdx.x >> 5];
    const float x = s0[(int64_t)a * 64 + h];
    S[0][h] = rc.cs * silu_f(x);
    if (!has_v) {
        __syncwarp();
        float sm0 = bm[h];
        for (int k = 0; k < 32; ++k) sm0 = fmaf(S[0][k], Wm0[k * 64 + h], sm0);
        smid[(int64_t)a * 64 + h] = sm0;
        __syncwarp();
        S[0][h] = rc.cs * silu_f(sm0);
        __syncwarp();
        if (h < 10) {
            float o = b2[h];
            for (int k = 0; k < 32; ++k) o = fmaf(S[0][k], W2[k * 10 + h], o);
            out[(int64_t)a * 10 + h] = o;
        }
        return;
    }
    const float g = rc.cg * sig_f(s0[(int64_t)a * 64 + 32 + h]);
    for (int m = 0; m < 3; ++m) S[1 + m][h] = g * v1[((int64_t)a * 3 + m) * 32 + h];
    __syncwarp();
    float sm0 = bm[h], sm1 = bm[32 + h], vm[3] = {0.0f, 0.0f, 0.0f};
    for (int k = 0; k < 32; ++k) {
        sm0 = fmaf(S[0][k], Wm0[k * 64 + h], sm0);
        sm1 = fmaf(S[0][k], Wm0[k * 64 + 32 + h], sm1);
        for (int m = 0; m < 3; ++m) vm[m] = fmaf(S[1 + m][k], Wm1[k * 32 + h], vm[m]);
    }
    smid[(int64_t)a * 64 + h] = sm0;
    smid[(int64_t)a * 64 + 32 + h] = sm1;
    for (int m = 0; m < 3; ++m) vmid[((int64_t)a * 3 + m) * 32 + h] = vm[m];
    __syncwarp();
    const float b0 = rc.cs * silu_f(sm0), g2 = rc.cg * sig_f(sm1);
    S[0][h] = b0;
    for (int m = 0; m < 3; ++m) S[1 + m][h] = g2 * vm[m];
    __syncwarp();
    if (h < 10) {
        float o = b2[h];
        for (int k = 0; k < 32; ++k) {
            o = fmaf(S[0][k], W2[k * 10 + h], o);
            for (int m = 0; m < 3; ++m) o = fmaf(S[1 + m][k], W2[(32 + k * 3 + m) * 10 + h], o);
        }
        out[(int64_t)a * 10 + h] = o;
    }
}

__global__ void ro_bwd_kernel(int N, RoConsts rc, int has_v, const float* __restrict__ s0,
                              const float* __restrict__ v1, const float* __restrict__ Wm0,
                              const float* __restrict__ Wm1, const float* __restrict__ W2,
                              const float* __restrict__ smid, const float* __restrict__ vmid,
                              const float* __restrict__ dout, float* __restrict__ ds0, float* __restrict__ dv1) {
    const int a = blockIdx.x * (blockDim.x >> 5) + (threadIdx.x >> 5), h = threadIdx.x & 31;
    if (a >= N) return;
    __shared__ float sh[4][4][32];
    __shared__ float sdo[4][10];
    float (*S)[32] = sh[threadIdx.x >> 5];
    if (h < 10) sdo[threadIdx.x >> 5][h] = dout[(int64_t)a * 10 + h];
    __syncwarp();
    const float* d = sdo[threadIdx.x >> 5];
    if (!has_v) {  // S124: the scalar path alone (see ro_fwd_kernel)
        float db0 = 0.0f;
        for (int k = 0; k < 10; ++k) db0 = fmaf(d[k], W2[h * 10 + k], db0);
        S[0][h] = db0 * rc.cs * dsilu_f(smid[(int64_t)a * 64 + h]);
        __syncwarp();
        float da0 = 0.0f;
        for (int o = 0; o < 32; ++o) da0 = fmaf(S[0][o], Wm0[h * 64 + o], da0);
        ds0[(int64_t)a * 64 + h] = da0 * rc.cs * dsilu_f(s0[(int64_t)a * 64 + h]);
        return;
    }
    // gradient of the second gate outputs b0[h], b1[m][h]
    float db0 = 0.0f, db1[3] = {0.0f, 0.0f, 0.0f};
    for (int k = 0; k < 10; ++k) {
        db0 = fmaf(d[k], W2[h * 10 + k], db0);
        for (int m = 0; m < 3; ++m) db1[m] = fmaf(d[k], W2[(32 + h * 3 + m) * 10 + k], db1[m]);
    }
    const float sm0 = smid[(int64_t)a * 64 + h], sm1 = smid[(int64_t)a * 64 + 32 + h];
    const float sg2 = sig_f(sm1), g2 = rc.cg * sg2;
    float vm[3], dgate2 = 0.0f;
    for (int m = 0; m < 3; ++m) {
        vm[m] = vmid[((int64_t)a * 3 + m) * 32 + h];
        dgate2 = fmaf(db1[m], vm[m], dgate2);
    }
    const float dsm0 = db0 * rc.cs * dsilu_f(sm0);
    const float dsm1 = dgate2 * rc.cg * sg2 * (1.0f - sg2);
    // through the mid linear: da0[k] = sum_o dsm[o] Wm0[k][o], da1[m][k] = sum_o dvm[m][o] Wm1[k][o]
    S[0][h] = dsm0;
    S[1][h] = dsm1;
    __syncwarp();
    float da0 = 0.0f;
    for (int o = 0; o < 32; ++o) da0 = fmaf(S[0][o], Wm0[h * 64 + o], fmaf(S[1][o], Wm0[h * 64 + 32 + o], da0));
    __syncwarp();
    float dvm[3];
    for (int m = 0; m < 3; ++m) dvm[m] = db1[m] * g2;
    float da1[3];
    for (int m = 0; m < 3; ++m) {
        __syncwarp();
        S[0][h] = dvm[m];
        __syncwarp();
        float acc = 0.0f;
        for (int o = 0; o < 32; ++o) acc = fmaf(S[0][o], Wm1[h * 32 + o], acc);
        da1[m] = acc;
    }
    // first gate
    const float x = s0[(int64_t)a * 64 + h], gt = s0[(int64_t)a * 64 + 32 + h];
    const float sg1 = sig_f(gt), g1 = rc.cg * sg1;
    float dg1 = 0.0f;
    for (int m = 0; m < 3; ++m) {
        dg1 = fmaf(da1[m], v1[((int64_t)a * 3 + m) * 32 + h], dg1);
        dv1[((int64_t)a * 3 + m) * 32 + h] = da1[m] * g1;
    }
    ds0[(int64_t)a * 64 + h] = da0 * rc.cs * dsilu_f(x);
    ds0[(int64_t)a * 64 + 32 + h] = dg1 * rc.cg * sg1 * (1.0f - sg1);
}

// Fukui readout tail (H = 16): fk = W2 . c silu(Wm . c silu(x) + bm) + b2; one warp per atom (lanes 0..15).
__global__ void fk_fwd_kernel(int N, float c, const float* __restrict__ x, const float* __restrict__ Wm,
                              const float* __restrict__ bm, const float* __restrict__ W2, const float* __restrict__ b2,
                              float* __restrict__ z2, float* __restrict__ fk) {
    const int a = blockIdx.x * (blockDim.x >> 5) + (threadIdx.x >> 5), h = threadIdx.x & 31;
    if (a >= N) return;
    __shared__ float sh[4][16];
    float* S = sh[threadIdx.x >> 5];
    if (h < 16) S[h] = c * silu_f(x[(int64_t)a * 16 + h]);
    __syncwarp();
    float z = 0.0f;
    if (h < 16) {
        z = bm[h];
        for (int k = 0; k < 16; ++k) z = fmaf(S[k], Wm[k * 16 + h], z);
        z2[(int64_t)a * 16 + h] = z;
    }
    __syncwarp();
    if (h < 16) S[h] = c * silu_f(z);
    __syncwarp();
    if (h < 2) {
        float o = b2[h];
        for (int k = 0; k < 16; ++k) o = fmaf(S[k], W2[k * 2 + h], o);
        fk[(int64_t)a * 2 + h] = o;
    }
}

__global__ void fk_bwd_kernel(int N, float c, const float* __restrict__ x, const float* __restrict__ Wm,
                              const float* __restrict__ W2, const float* __restrict__ z2,
                              const float* __restrict__ dfk, float* __restrict__ dx) {
    const int a = blockIdx.x * (blockDim.x >> 5) + (threadIdx.x >> 5), h = threadIdx.x & 31;
    if (a >= N) return;
    __shared__ float sh[4][16];
    float* S = sh[threadIdx.x >> 5];
    float dz = 0.0f;
    if (h < 16) {
        const float da2 = dfk[(int64_t)a * 2] * W2[h * 2] + dfk[(int64_t)a * 2 + 1] * W2[h * 2 + 1];
        dz = da2 * c * dsilu_f(z2[(int64_t)a * 16 + h]);
        S[h] = dz;
    }
    __syncwarp();
    if (h < 16) {
        float da1 = 0.0f;
        for (int o = 0; o < 16; ++o) da1 = fmaf(S[o], Wm[h * 16 + o], da1);
        dx[(int64_t)a * 16 + h] = da1 * c * dsilu_f(x[(int64_t)a * 16 + h]);
    }
}

// red[0..1] = sum_a q[a][0], q[a][4]; red[2..3] = sum_a fk[a][0..1] (fk_stride 2 or 10, offset given)
__global__ void fukui_sums_kernel(int N, const float* __restrict__ q, const float* __restrict__ fk, int fk_ld,
                                  double* __restrict__ red) {
    const int a = blockIdx.x * blockDim.x + threadIdx.x;
    double v[4] = {0, 0, 0, 0};
    if (a < N) {
        v[0] = q[a * 8];
        v[1] = q[a * 8 + 4];
        v[2] = fk[(int64_t)a * fk_ld];
        v[3] = fk[(int64_t)a * fk_ld + 1];
    }
    for (int k = 0; k < 4; ++k) {
        double x = v[k];
        #pragma unroll
        for (int off = 16; off > 0; off >>= 1) x += __shfl_xor_sync(0xffffffffu, x, off);
        if ((threadIdx.x & 31) == 0) atomicAdd(red + k, x);
    }
}

// q_out = q_in with q[0] += fk_n0 (Q0/2 - Sq0), q[4] += fk_n1 (Q1/2 - Sq1); fk_n = fk / Sf (Sf = 1 if 0). Q = 0.
__global__ void fukui_apply_kernel(int N, const float* __restrict__ q, const float* __restrict__ fk, int fk_ld,
                                   const double* __restrict__ red, float* __restrict__ qo) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= N * 8) return;
    const int a = i / 8, m = i % 8;
    float v = q[i];
    if (m == 0 || m == 4) {
        const int ch = m / 4;
        const double sf = red[2 + ch] == 0.0 ? 1.0 : red[2 + ch];
        v += (float)((double)fk[(int64_t)a * fk_ld + ch] / sf * (0.0 - red[ch]));
    }
    qo[i] = v;
}

// G = dq_out: red[4+ch] = sum_a G[a][4ch] fk[a][ch] (for the backward)
__global__ void fukui_bwd_sums_kernel(int N, const float* __restrict__ G, const float* __restrict__ fk, int fk_ld,
                                      double* __restrict__ red) {
    const int a = blockIdx.x * blockDim.x + threadIdx.x;
    double v[2] = {0, 0};
    if (a < N) {
        v[0] = (double)G[a * 8] * fk[(int64_t)a * fk_ld];
        v[1] = (double)G[a * 8 + 4] * fk[(int64_t)a * fk_ld + 1];
    }
    for (int k = 0; k < 2; ++k) {
        double x = v[k];
        #pragma unroll
        for (int off = 16; off > 0; off >>= 1) x += __shfl_xor_sync(0xffffffffu, x, off);
        if ((threadIdx.x & 31) == 0) atomicAdd(red + 4 + k, x);
    }
}

// dq_in = G - (sum_b G_b fk_n,b) on the monopoles; dfk (into dfk[a][ch], stride fk_ld) from fk_n = fk / Sf
__global__ void fukui_bwd_kernel(int N, const float* __restrict__ G, const float* __restrict__ fk, int fk_ld,
                                 const double* __restrict__ red, float* __restrict__ dq, float* __restrict__ dfk) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= N * 8) return;
    const int a = i / 8, m = i % 8;
    float v = G[i];
    if (m == 0 || m == 4) {
        const int ch = m / 4;
        const bool zero = red[2 + ch] == 0.0;
        const double sf = zero ? 1.0 : red[2 + ch];
        const double T = red[4 + ch] / sf;  // sum_b G_b fk_n,b
        v = (float)(v - T);
        const double cq = 0.0 - red[ch];  // Q/2 - Sq
        // dfk_n[a] = G[a] cq ; dfk[a] = dfk_n[a] / sf - (sum_b dfk_n[b] fk[b]) / sf^2 (no second term when sf == 0)
        double d = (double)G[i] * cq / sf;
        if (!zero) d -= cq * red[4 + ch] / (sf * sf);
        dfk[(int64_t)a * fk_ld + ch] = (float)d;
    }
    dq[i] = v;
}

__global__ void axpy_kernel(int64_t n, float a, const float* __restrict__ x, float* __restrict__ y) {
    const int64_t i = (int64_t)blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n) y[i] += a * x[i];
}

__global__ void sum_rows_kernel(int N, const float* __restrict__ e, double* __restrict__ energy) {
    const int a = blockIdx.x * blockDim.x + threadIdx.x;
    double v = a < N ? (double)e[a] : 0.0;
    #pragma unroll
    for (int off = 16; off > 0; off >>= 1) v += __shfl_xor_sync(0xffffffffu, v, off);
    if ((threadIdx.x & 31) == 0) atomicAdd(energy, v);
}

__global__ void fill_kernel(int64_t n, float v, float* __restrict__ x) {
    const int64_t i = (int64_t)blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n) x[i] = v;
}

// y[a][0..7] += x[a][0..7] (row strides ldx, ldy)
__global__ void add8_kernel(int N, const float* __restrict__ x, int ldx, float* __restrict__ y, int ldy, int assign) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= N * 8) return;
    const int64_t dst = (int64_t)(i / 8) * ldy + i % 8;
    const float v = x[(int64_t)(i / 8) * ldx + i % 8];
    if (assign) y[dst] = v;
    else y[dst] += v;
}

// y[a][0..7] = b[a][0..7] + x[a][0..7] (x row stride ldx; b, y [N, 8]): a copy of b and an add8_kernel in one launch,
// with the same float sum.
__global__ void add8_to_kernel(int N, const float* __restrict__ x, int ldx, const float* __restrict__ b,
                               float* __restrict__ y) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= N * 8) return;
    y[i] = b[i] + x[(int64_t)(i / 8) * ldx + i % 8];
}

// dq[a][ch*4 + m] += g[a][m] for both spin channels (g has row stride 8, its first 4 columns used)
__global__ void spin_grad_kernel(int N, const float* __restrict__ g, float* __restrict__ dq) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= N * 4) return;
    const int a = i / 4, m = i % 4;
    const float v = g[a * 8 + m];
    dq[a * 8 + m] += v;
    dq[a * 8 + 4 + m] += v;
}

inline unsigned blocks_for(int64_t n, int b = 256) { return (unsigned)((n + b - 1) / b); }

// k chunks for the per-atom k passes: enough blocks for ~2 per SM (at most k_splits_max(N) chunks), chunks a
// multiple of 64 (both tiles).
inline int k_splits_max(int N) {
    static int sms = [] { int d = 0, s = 0; cudaGetDevice(&d); cudaDeviceGetAttribute(&s, cudaDevAttrMultiProcessorCount, d); return s > 0 ? s : 1; }();
    const int atom_blocks = (int)blocks_for(N, 128);
    return (2 * sms + atom_blocks - 1) / atom_blocks;
}
inline int k_chunk(int N, int K) {
    int ks = k_splits_max(N);
    const int max_ks = (K + 63) / 64;
    if (ks > max_ks) ks = max_ks;
    if (ks < 1) ks = 1;
    return ((K + ks - 1) / ks + 63) / 64 * 64;
}

// out[j][col0 + s C + n] = sum_c W[j][col0 + s C + c] D[n][c] in double, for every C-wide segment s of the column range
// [col0, col0 + ncols): a linear map W followed by the C x C map D^T, composed once at load (PolarLR::load).
__global__ void fold_dotT_kernel(int rows, int ld, int col0, int ncols, int C, const float* __restrict__ W,
                                 const float* __restrict__ D, float* __restrict__ out) {
    const int64_t idx = (int64_t)blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= (int64_t)rows * ncols) return;
    const int j = (int)(idx / ncols), q = (int)(idx % ncols), s = q / C, n = q % C;
    const float* w = W + (size_t)j * ld + col0 + (size_t)s * C;
    const float* d = D + (size_t)n * C;
    double acc = 0.0;
    for (int c = 0; c < C; ++c) acc = fma((double)w[c], (double)d[c], acc);
    out[(size_t)j * ld + col0 + q] = (float)acc;
}

struct DevTmp {  // load-time scratch, freed on scope exit (also when a check throws)
    void* p = nullptr;
    ~DevTmp() { if (p) cudaFree(p); }
};

}  // namespace

// ------------------------------------------------------------------------------------------------------------ impl
struct PolarLR::Impl {
    struct Mlp {
        int n = 0;
        std::vector<int> in, out;
        std::vector<float*> W, b, g, be;
    };
    // The SCF's Z = (pot Wpot + q Wq + fm Wnf) dot^T and the electron energy's Zq = (q Wq + bq) dotq^T (Zv alike) are
    // linear in their inputs. With `fold` (sm_120 and compute capability 8.0, the GPUs it was measured on;
    // LOUP_POLAR_FOLD=0 disables it, =1 forces it elsewhere) the weights are stored composed with dot^T (`_dot`,
    // fold_dotT_kernel): one C x C product per SCF step and l in each direction instead of two, and none for the
    // electron energy. Likewise the update MLP's last layer (affine, no activation) feeds only P_l = nl tpo_l^T: with
    // `fold` it is composed with tpo_l (`tpo_W`, `tpo_b`, S115), so P_l comes from the last hidden layer (H columns)
    // and nl is never formed. Otherwise the unfolded weights and products.
    bool fold = false;
    // S118: lmax 0, and the weights' structural zeros certified at load (PolarLR::load): only the monopoles
    // q[ch * 4] are nonzero, and only the raw features ch * 8 + {0, 4} (the two widths' potentials) reach a nonzero
    // weight. The k-space passes then run on 2 + 2 + 1 + 4 + 4 channels instead of 8 + 8 + 4 + 16 + 16 (POLAR-1-S).
    bool mono = false;
    struct Update {
        float *Wpot = nullptr, *Wq = nullptr, *Wnf[3] = {}, *dot[3] = {};              // unfolded
        float *Wpot_dot = nullptr, *Wq_dot = nullptr, *Wnf_dot[3] = {};                // folded
        bool zpot[3] = {}, zq[3] = {};  // S123: block l of Wpot / Wq exactly zero (certified at load)
        // P_l for l <= 1 (the readout reads nw_0 and nw_1 only): tpo_l unfolded; folded, tpo_W_l = W tpo_l^T [H, C]
        // and tpo_b_l = b tpo_l^T [C] from the MLP's last layer (W, b)
        bool tpo_fold = false;
        float *tpo[2] = {}, *tpo_W[2] = {}, *tpo_b[2] = {}, *emb = nullptr;
        Mlp mlp;
        float *ro_W1[2] = {}, *ro_Wm0 = nullptr, *ro_bm = nullptr, *ro_Wm1 = nullptr, *ro_W2 = nullptr,
              *ro_b2 = nullptr;
        RoConsts rc{1.0f, 1.0f};
    };
    struct Step {  // saved forward state of one SCF step
        double* SFq = nullptr;  // the step's charge structure factors (cos [K_cap][8], sin [K_cap][8])
        float *qin = nullptr, *pot = nullptr, *AB = nullptr, *mixed[3] = {}, *Z[3] = {}, *x0 = nullptr, *P[2] = {},
              *nw[2] = {}, *s0 = nullptr, *v1 = nullptr, *smid = nullptr, *vmid = nullptr, *out = nullptr,
              *qnew = nullptr, *gmixed_stat = nullptr;
        std::vector<float*> z, act;  // MLP pre-activations and activations
        float* stat = nullptr;
    };

    std::vector<void*> w_, s_;
    int S = 0, L = 0, C = 0, lmax = 0, rows = 0, n_rec = 0, add_le = 0;
    int off[3] = {0, 0, 0};
    std::vector<float*> src;
    // S123 extension: src_zero[t][l], layer t's degree-l source block exactly zero (certified at load and on a hidden
    // fold; not with LOUP_POLAR_ZBLK=0): its source GEMMs are skipped (POLAR-1-L's l = 2 blocks)
    std::vector<std::vector<char>> src_zero;
    bool zblk = true;
    std::vector<std::vector<const float*>> mix;  // a hidden fold's composed mixer belongs to the generic layer
    float *fk_W1 = nullptr, *fk_Wm = nullptr, *fk_bm = nullptr, *fk_W2 = nullptr, *fk_b2 = nullptr;
    float fk_act = 1.0f;
    std::vector<Update> upd;
    float *le_Wq = nullptr, *le_bq = nullptr, *le_Wv = nullptr, *le_bv = nullptr, *le_dotq[3] = {}, *le_dotv[3] = {};
    float *le_Wq_dot = nullptr, *le_bq_dot = nullptr, *le_Wv_dot = nullptr, *le_bv_dot = nullptr;
    // S123: the highest l whose le_Wq / le_Wv block is nonzero (certified at load); the blocks above give Zq_l = 0
    // (Zv_l = 0): their GEMMs, inv terms and reverse are skipped
    int le_lq = 0, le_lv = 0;
    Mlp le_mlp;
    FeatConsts fc{};
    double sigma_d = 0, sigma_f[2] = {}, kcut = 0, FC = 0, cl_d[2] = {}, cl_f[2][2] = {}, p0d = 0, p1d = 0,
           p0f[2] = {}, p1f[2] = {};
    BasisConsts bc{};
    // cell
    double cell[9] = {}, vol = 0;
    bool have_cell = false;
    int K = 0, K_cap = 0;
    float* kinfo = nullptr;
    double* minv = nullptr;
    unsigned* fracu = nullptr;
    // system
    int N = 0;
    float *qsrc = nullptr, *fm[3] = {}, *dfm[3] = {}, *fx1 = nullptr, *fz2 = nullptr,
          *fk = nullptr, *q0 = nullptr, *f16 = nullptr, *g16 = nullptr, *dq = nullptr, *dq2 = nullptr,
          *dq0 = nullptr, *dpot = nullptr, *dfk = nullptr, *dfx = nullptr, *qt = nullptr, *qfin = nullptr;
    double *SC = nullptr, *SS = nullptr;  // per k structure factors
    float* dk = nullptr;                  // per k backward coefficients
    double* red = nullptr;                              // fukui reductions, 8 per use
    double* kpart = nullptr;  // k-split partial sums: [k_splits_max(N)][N][16] (feat_pass) or [..][N][11]
    std::vector<Step> steps;
    // local electron energy state
    float *qin_le = nullptr, *qu[3] = {}, *vu[3] = {}, *Zq[3] = {}, *Zv[3] = {}, *lex0 = nullptr, *le_e = nullptr;
    std::vector<float*> le_z, le_act;
    float* le_stat = nullptr;
    // backward scratch
    float *gA = nullptr, *gB = nullptr, *dmix[3] = {}, *dZ[3] = {}, *dP = nullptr, *dnl = nullptr, *dx0 = nullptr,
          *dnw[3] = {}, *ds0 = nullptr, *dv1 = nullptr, *dout = nullptr, *mlp_d1 = nullptr, *mlp_d2 = nullptr;
    int max_mlp_w = 0;
    void* bwd_zero_slab = nullptr;
    size_t bwd_zero_bytes = 0;

    float* up(const std::vector<float>& v) {
        float* d = nullptr;
        CUDA_CHECK_THROW(cudaMalloc(&d, std::max<size_t>(v.size(), 1) * sizeof(float)));
        if (!v.empty()) CUDA_CHECK_THROW(cudaMemcpy(d, v.data(), v.size() * sizeof(float), cudaMemcpyHostToDevice));
        w_.push_back(d);
        return d;
    }
    size_t sys_bytes = 0;  // the per-system buffers of sys() (PolarLR::system_bytes)
    float* sys(size_t n) {
        float* d = nullptr;
        CUDA_CHECK_THROW(device_malloc(&d, std::max<size_t>(n, 1) * sizeof(float)));
        sys_bytes += std::max<size_t>(n, 1) * sizeof(float);
        s_.push_back(d);
        return d;
    }
    // the degree-l block of a source [R, 8] (blk: its first row, off[l]) exactly zero; never without zblk
    bool src_block_zero(const float* blk, int l) const {
        if (!zblk) return false;
        const size_t n = (size_t)(2 * l + 1) * C * 8;
        for (size_t i = 0; i < n; ++i)
            if (blk[i] != 0.0f) return false;
        return true;
    }
    // W [rows, ld] uploaded with each block's columns [col0, col0 + ncols) composed with its D^T (fold_dotT_kernel).
    struct FoldBlock {
        int col0, ncols;
        const std::vector<float>* D;
    };
    float* up_fold(const std::vector<float>& W, int rows, int ld, const std::vector<FoldBlock>& blocks) {
        float* out = up(W);  // every column is overwritten: the blocks cover [0, ld)
        DevTmp dW, dD;
        CUDA_CHECK_THROW(cudaMalloc(&dW.p, W.size() * sizeof(float)));
        CUDA_CHECK_THROW(cudaMemcpy(dW.p, W.data(), W.size() * sizeof(float), cudaMemcpyHostToDevice));
        CUDA_CHECK_THROW(cudaMalloc(&dD.p, (size_t)C * C * sizeof(float)));
        int covered = 0;
        for (const FoldBlock& fb : blocks) {
            if (fb.D->size() != (size_t)C * C) throw std::runtime_error("polar bundle: dot shape");
            CUDA_CHECK_THROW(cudaMemcpy(dD.p, fb.D->data(), (size_t)C * C * sizeof(float), cudaMemcpyHostToDevice));
            const int64_t n = (int64_t)rows * fb.ncols;
            fold_dotT_kernel<<<(unsigned)((n + 255) / 256), 256>>>(rows, ld, fb.col0, fb.ncols, C,
                                                                   static_cast<const float*>(dW.p),
                                                                   static_cast<const float*>(dD.p), out);
            CUDA_CHECK_THROW(cudaGetLastError());
            CUDA_CHECK_THROW(cudaDeviceSynchronize());  // dD is reused by the next block
            covered += fb.ncols;
        }
        if (covered != ld) throw std::runtime_error("polar: fold blocks do not cover the weight");
        return out;
    }
    void load_mlp(const Bundle& b, const std::string& p, int n, Mlp& m) {
        m.n = n;
        for (int k = 0; k < n; ++k) {
            const BundleEntry& e = b.entry(p + "W" + std::to_string(k));
            if (e.dims.size() != 2) throw std::runtime_error("polar bundle: bad MLP weight");
            const int in = (int)e.dims[0], out = (int)e.dims[1];
            m.in.push_back(in);
            m.out.push_back(out);
            m.W.push_back(up(b.f32(p + "W" + std::to_string(k), {in, out})));
            m.b.push_back(up(b.f32(p + "b" + std::to_string(k), {out})));
            if (k < n - 1) {
                m.g.push_back(up(b.f32(p + "g" + std::to_string(k), {out})));
                m.be.push_back(up(b.f32(p + "beta" + std::to_string(k), {out})));
                if (out > 256) throw std::runtime_error("polar bundle: LayerNorm width above 256");
            }
            max_mlp_w = std::max(max_mlp_w, std::max(in, out));
        }
    }
};

PolarLR::PolarLR() : p_(new Impl()) {}
PolarLR::~PolarLR() {
    free_system();
    for (void* q : p_->w_) cudaFree(q);
    if (p_->kinfo) cudaFree(p_->kinfo);
    if (p_->minv) cudaFree(p_->minv);
    delete p_;
}

void PolarLR::load(const Bundle& b, int S, int n_layers) {
    Impl& P = *p_;
    P.S = S;
    P.L = n_layers;
    P.C = b.meta_int("LR.C");
    P.lmax = b.meta_int("LR.lmax");
    P.n_rec = b.meta_int("LR.n_rec");
    P.add_le = b.meta_int("LR.add_le");
    if (P.lmax < 0 || P.lmax > 2 || P.C < 32 || P.C % 32 || P.n_rec < 1 || P.n_rec > 8)
        throw std::runtime_error("polar bundle: unsupported long-range shape");
    P.rows = 0;
    for (int l = 0; l <= P.lmax; ++l) {
        P.off[l] = P.rows;
        P.rows += (2 * l + 1) * P.C;
    }
    const int C = P.C, R = P.rows;
    {
        int dev = 0, major = 0, minor = 0;
        CUDA_CHECK_THROW(cudaGetDevice(&dev));
        CUDA_CHECK_THROW(cudaDeviceGetAttribute(&major, cudaDevAttrComputeCapabilityMajor, dev));
        CUDA_CHECK_THROW(cudaDeviceGetAttribute(&minor, cudaDevAttrComputeCapabilityMinor, dev));
        P.fold = (major == 12 && minor == 0) || (major == 8 && minor == 0);
        if (const char* e = std::getenv("LOUP_POLAR_FOLD"); e && (e[0] == '0' || e[0] == '1'))
            P.fold = e[0] == '1';  // tests: the unfolded path here, the fold elsewhere
    }
    {
        const char* zb_env = std::getenv("LOUP_POLAR_ZBLK");
        P.zblk = !(zb_env && zb_env[0] == '0');
    }
    for (int t = 0; t < n_layers; ++t) {
        const std::vector<float> src = b.f32("LR.src_" + std::to_string(t), {R, 8});
        P.src.push_back(P.up(src));
        P.src_zero.emplace_back();
        P.mix.emplace_back();
        for (int l = 0; l <= P.lmax; ++l) {
            P.src_zero.back().push_back(P.src_block_zero(src.data() + (size_t)P.off[l] * 8, l));
            P.mix.back().push_back(P.up(b.f32("LR.mix_" + std::to_string(t) + "_" + std::to_string(l), {C, C})));
        }
    }
    P.fk_W1 = P.up(b.f32("LR.fk_W1", {C, 16}));
    P.fk_act = (float)b.f64("LR.fk_act", {1})[0];
    P.fk_Wm = P.up(b.f32("LR.fk_Wm", {16, 16}));
    P.fk_bm = P.up(b.f32("LR.fk_bm", {16}));
    P.fk_W2 = P.up(b.f32("LR.fk_W2", {16, 2}));
    P.fk_b2 = P.up(b.f32("LR.fk_b2", {2}));
    P.sigma_d = b.f64("LR.sigma_d", {1})[0];
    {
        const auto sf = b.f64("LR.sigma_f", {2});
        P.sigma_f[0] = sf[0];
        P.sigma_f[1] = sf[1];
    }
    P.kcut = b.f64("LR.kcut", {1})[0];
    P.FC = b.f64("LR.field_const", {1})[0];
    {
        const auto norms = b.f64("LR.feat_norms", {8});
        const auto si = b.f64("LR.feat_si", {8});
        const auto idx = b.i32("LR.feat_si_idx", {8});
        const auto perm = b.i32("LR.feat_perm", {8});
        for (int j = 0; j < 8; ++j) {
            P.fc.norms[j] = (float)norms[j];
            P.fc.si[j] = (float)si[j];
            P.fc.idx[j] = idx[j];
            P.fc.perm[j] = perm[j];
            if (idx[j] < 0 || idx[j] > 3 || perm[j] < 0 || perm[j] > 7) throw std::runtime_error("polar bundle: index");
        }
        const auto cld = b.f64("LR.cl_d", {1, 2});
        P.cl_d[0] = cld[0];
        P.cl_d[1] = cld[1];
        const auto clf = b.f64("LR.cl_f", {2, 2});
        for (int i = 0; i < 4; ++i) P.cl_f[i / 2][i % 2] = clf[i];
        P.p0d = b.f64("LR.pref0_d", {1})[0];
        P.p1d = b.f64("LR.pref1_d", {1})[0];
        const auto p0f = b.f64("LR.pref0_f", {2}), p1f = b.f64("LR.pref1_f", {2});
        for (int i = 0; i < 2; ++i) {
            P.p0f[i] = p0f[i];
            P.p1f[i] = p1f[i];
        }
        const double y0 = 1.0 / std::sqrt(4.0 * M_PI), y1c = std::sqrt(3.0 / (4.0 * M_PI));
        P.bc.a0 = (float)(P.p0d * P.cl_d[0] * y0);
        P.bc.a1 = (float)(P.p1d * P.cl_d[1] * y1c);
        P.bc.sd2 = (float)(P.sigma_d * P.sigma_d);
        for (int s = 0; s < 2; ++s) {
            P.bc.b0[s] = (float)(P.p0f[s] * P.cl_f[s][0] * y0);
            P.bc.b1[s] = (float)(P.p1f[s] * P.cl_f[s][1] * y1c);
            P.bc.sf2[s] = (float)(P.sigma_f[s] * P.sigma_f[s]);
        }
    }
    // dot_l^T applied to each l's column block of a [rows, R] weight (block l: columns off[l] .. off[l] + (2l + 1) C)
    auto blocks_of = [&](const std::vector<std::vector<float>>& dots) {
        std::vector<Impl::FoldBlock> blk;
        for (int l = 0; l <= P.lmax; ++l) blk.push_back({P.off[l], (2 * l + 1) * C, &dots[l]});
        return blk;
    };
    // S123: block l of a [rows, R] weight exactly zero, so its products are exact zeros and their GEMMs are skipped
    // (POLAR-1-L: the l = 2 blocks of every update's Wpot and Wq and of le_Wq and le_Wv). Folding keeps the zero
    // blocks (W_l dot_l^T = 0). LOUP_POLAR_ZBLK=0 disables the skips (tests, A/B).
    const bool zblk = P.zblk;
    auto zero_block = [&](const std::vector<float>& W, int rows, int l) {
        if (!zblk) return false;
        for (int r = 0; r < rows; ++r)
            for (int c = P.off[l]; c < P.off[l] + (2 * l + 1) * C; ++c)
                if (W[(size_t)r * R + c] != 0.0f) return false;
        return true;
    };
    for (int i = 0; i < P.n_rec; ++i) {
        Impl::Update U;
        const std::string p = "LR.u" + std::to_string(i) + ".";
        std::vector<std::vector<float>> dot(P.lmax + 1);
        for (int l = 0; l <= P.lmax; ++l) dot[l] = b.f32(p + "dot_" + std::to_string(l), {C, C});
        const std::vector<float> Wpot = b.f32(p + "Wpot", {16, R}), Wq = b.f32(p + "Wq", {8, R});
        for (int l = 0; l <= P.lmax; ++l) {
            U.zpot[l] = zero_block(Wpot, 16, l);
            U.zq[l] = zero_block(Wq, 8, l);
        }
        if (P.fold) {
            U.Wpot_dot = P.up_fold(Wpot, 16, R, blocks_of(dot));
            U.Wq_dot = P.up_fold(Wq, 8, R, blocks_of(dot));
        } else {
            U.Wpot = P.up(Wpot);
            U.Wq = P.up(Wq);
        }
        for (int l = 0; l <= P.lmax; ++l) {
            if (P.fold) {
                U.Wnf_dot[l] = P.up_fold(b.f32(p + "Wnf_" + std::to_string(l), {C, C}), C, C, {{0, C, &dot[l]}});
            } else {
                U.Wnf[l] = P.up(b.f32(p + "Wnf_" + std::to_string(l), {C, C}));
                U.dot[l] = P.up(dot[l]);
            }
        }
        U.emb = P.up(b.f32(p + "src_emb", {S, C}));
        P.load_mlp(b, p + "mlp_", b.meta_int(p + "mlp_n"), U.mlp);
        if (U.mlp.in[0] != 2 * C || U.mlp.out.back() != C) throw std::runtime_error("polar bundle: update MLP shape");
        U.tpo_fold = P.fold && U.mlp.n >= 2;
        for (int l = 0; l <= std::min(P.lmax, 1); ++l) {
            const std::vector<float> tpo = b.f32(p + "tpo_" + std::to_string(l), {C, C});
            if (U.tpo_fold) {
                const int k = U.mlp.n - 1, H = U.mlp.in[k];
                U.tpo_W[l] = P.up_fold(b.f32(p + "mlp_W" + std::to_string(k), {H, C}), H, C, {{0, C, &tpo}});
                U.tpo_b[l] = P.up_fold(b.f32(p + "mlp_b" + std::to_string(k), {C}), 1, C, {{0, C, &tpo}});
            } else {
                U.tpo[l] = P.up(tpo);
            }
        }
        if (b.meta_int(p + "ro_H") != 32) throw std::runtime_error("polar bundle: readout width must be 32");
        U.ro_W1[0] = P.up(b.f32(p + "ro_W1_0", {C, 64}));
        if (P.lmax >= 1) U.ro_W1[1] = P.up(b.f32(p + "ro_W1_1", {C, 32}));
        const auto gt = b.f64(p + "ro_gate", {2});
        U.rc.cs = (float)gt[0];
        U.rc.cg = (float)gt[1];
        U.ro_Wm0 = P.up(b.f32(p + "ro_Wm_0", {32, 64}));
        U.ro_bm = P.up(b.f32(p + "ro_bm", {64}));
        U.ro_Wm1 = P.up(b.f32(p + "ro_Wm_1", {32, 32}));
        U.ro_W2 = P.up(b.f32(p + "ro_W2", {128, 10}));
        U.ro_b2 = P.up(b.f32(p + "ro_b2", {10}));
        P.upd.push_back(U);
    }
    {
        std::vector<std::vector<float>> dotq(P.lmax + 1), dotv(P.lmax + 1);
        for (int l = 0; l <= P.lmax; ++l) {
            dotq[l] = b.f32("LR.le_dotq_" + std::to_string(l), {C, C});
            dotv[l] = b.f32("LR.le_dotv_" + std::to_string(l), {C, C});
        }
        const std::vector<float> le_Wq = b.f32("LR.le_Wq", {8, R}), le_Wv = b.f32("LR.le_Wv", {16, R});
        P.le_lq = P.le_lv = 0;
        for (int l = 1; l <= P.lmax; ++l) {
            if (!zero_block(le_Wq, 8, l)) P.le_lq = l;
            if (!zero_block(le_Wv, 16, l)) P.le_lv = l;
        }
        if (P.fold) {
            P.le_Wq_dot = P.up_fold(le_Wq, 8, R, blocks_of(dotq));
            P.le_bq_dot = P.up_fold(b.f32("LR.le_bq", {C}), 1, C, {{0, C, &dotq[0]}});
            P.le_Wv_dot = P.up_fold(le_Wv, 16, R, blocks_of(dotv));
            P.le_bv_dot = P.up_fold(b.f32("LR.le_bv", {C}), 1, C, {{0, C, &dotv[0]}});
        } else {
            P.le_Wq = P.up(le_Wq);
            P.le_bq = P.up(b.f32("LR.le_bq", {C}));
            P.le_Wv = P.up(le_Wv);
            P.le_bv = P.up(b.f32("LR.le_bv", {C}));
            for (int l = 0; l <= P.lmax; ++l) {
                P.le_dotq[l] = P.up(dotq[l]);
                P.le_dotv[l] = P.up(dotv[l]);
            }
        }
    }
    P.load_mlp(b, "LR.le_mlp_", b.meta_int("LR.le_mlp_n"), P.le_mlp);
    if (P.le_mlp.in[0] != 2 * C || P.le_mlp.out.back() != 1) throw std::runtime_error("polar bundle: electron MLP shape");
    // S118 (`mono`): the sources' and the readouts' dipole columns q[ch * 4 + m], m = 1..3, are exactly zero (lmax 0:
    // the readout reads its scalar rows only; the Fukui constraint and the SCF add write the monopoles only), so the
    // charges stay monopoles; and every pot row that reads a raw feature other than ch * 8 + {0, 4} is exactly zero
    // in each update's Wpot and in le_Wv (the folded weights inherit the zero rows), so those features, and their
    // gradients, never reach a nonzero weight. LOUP_POLAR_MONO=0 disables it (tests, A/B).
    P.mono = P.lmax == 0;
    {
        auto dip = [](int m) { return m % 4 != 0; };
        for (int t = 0; t < n_layers && P.mono; ++t) {
            const std::vector<float> src = b.f32("LR.src_" + std::to_string(t), {R, 8});
            for (size_t i = 0; i < src.size(); ++i)
                if (dip((int)(i % 8)) && src[i] != 0.0f) P.mono = false;
        }
        auto dead_rows_zero = [&](const std::vector<float>& W) {  // W [16, R]: row ch * 8 + j reads raw perm[j]
            for (int r = 0; r < 16; ++r)
                if (P.fc.perm[r % 8] % 4 != 0)
                    for (int c = 0; c < R; ++c)
                        if (W[(size_t)r * R + c] != 0.0f) return false;
            return true;
        };
        for (int i = 0; i < P.n_rec && P.mono; ++i) {
            const std::string p = "LR.u" + std::to_string(i) + ".";
            const std::vector<float> W2 = b.f32(p + "ro_W2", {128, 10}), b2 = b.f32(p + "ro_b2", {10});
            for (int m = 0; m < 8; ++m) {
                if (!dip(m)) continue;
                if (b2[m] != 0.0f) P.mono = false;
                for (int k = 0; k < 32; ++k)
                    if (W2[(size_t)k * 10 + m] != 0.0f) P.mono = false;
            }
            if (!dead_rows_zero(b.f32(p + "Wpot", {16, R}))) P.mono = false;
        }
        if (P.mono && P.add_le && !dead_rows_zero(b.f32("LR.le_Wv", {16, R}))) P.mono = false;
        if (const char* e = std::getenv("LOUP_POLAR_MONO"); e && e[0] == '0') P.mono = false;
    }
}

void PolarLR::set_hidden_fold(int t, int l, const float* mix, const float* src_block) {
    Impl& P = *p_;
    if (t < 0 || t >= P.L || l < 0 || l > P.lmax) throw std::runtime_error("polar: hidden fold index");
    const size_t n = (size_t)(2 * l + 1) * P.C * 8;
    float* dst = P.src[t] + (size_t)P.off[l] * 8;
    CUDA_CHECK_THROW(cudaMemcpy(dst, src_block, n * sizeof(float), cudaMemcpyDeviceToDevice));
    std::vector<float> host(n);
    CUDA_CHECK_THROW(cudaMemcpy(host.data(), dst, n * sizeof(float), cudaMemcpyDeviceToHost));
    P.src_zero[t][l] = P.src_block_zero(host.data(), l);
    // the replaced mixer is never read again
    for (auto it = P.w_.begin(); it != P.w_.end(); ++it)
        if (*it == P.mix[t][l]) {
            cudaFree(*it);
            P.w_.erase(it);
            break;
        }
    P.mix[t][l] = mix;
}

int PolarLR::le_lmax() const { return p_->add_le ? std::max(p_->le_lq, p_->le_lv) : -1; }

// k-vectors as graph_longrange.compute_k_vectors_flat (rcell = 2 pi inv(cell^T)), with the GTO basis per k
bool PolarLR::set_cell(const double* c) {
    Impl& P = *p_;
    if (P.have_cell && memcmp(P.cell, c, sizeof(P.cell)) == 0) return false;
    memcpy(P.cell, c, sizeof(P.cell));
    P.have_cell = true;
    // inverse of the cell (rows = lattice vectors a_i)
    const double* a = c;
    const double det = a[0] * (a[4] * a[8] - a[5] * a[7]) - a[1] * (a[3] * a[8] - a[5] * a[6]) +
                       a[2] * (a[3] * a[7] - a[4] * a[6]);
    double inv[9];  // inv(cell)
    inv[0] = (a[4] * a[8] - a[5] * a[7]) / det;
    inv[1] = (a[2] * a[7] - a[1] * a[8]) / det;
    inv[2] = (a[1] * a[5] - a[2] * a[4]) / det;
    inv[3] = (a[5] * a[6] - a[3] * a[8]) / det;
    inv[4] = (a[0] * a[8] - a[2] * a[6]) / det;
    inv[5] = (a[2] * a[3] - a[0] * a[5]) / det;
    inv[6] = (a[3] * a[7] - a[4] * a[6]) / det;
    inv[7] = (a[1] * a[6] - a[0] * a[7]) / det;
    inv[8] = (a[0] * a[4] - a[1] * a[3]) / det;
    P.vol = std::fabs(det);
    // reciprocal rows b_i = 2 pi inv(cell^T) rows = 2 pi inv(cell) columns: b_i[j] = 2 pi inv[j][i]
    double rc[9];
    for (int i = 0; i < 3; ++i)
        for (int j = 0; j < 3; ++j) rc[3 * i + j] = TWO_PI * inv[3 * j + i];
    int nmax[3];
    for (int i = 0; i < 3; ++i) {
        const double norm = std::sqrt(a[3 * i] * a[3 * i] + a[3 * i + 1] * a[3 * i + 1] + a[3 * i + 2] * a[3 * i + 2]);
        const double dot = (rc[3 * i] * a[3 * i] + rc[3 * i + 1] * a[3 * i + 1] + rc[3 * i + 2] * a[3 * i + 2]) / norm;
        nmax[i] = (int)std::ceil(P.kcut / dot);
    }
    std::vector<int> nl;
    auto push = [&](int x, int y, int z) {
        nl.push_back(x);
        nl.push_back(y);
        nl.push_back(z);
    };
    push(0, 0, 0);
    for (int k = 1; k < nmax[2]; ++k) push(0, 0, k);
    for (int j = 1; j < nmax[1]; ++j)
        for (int k = -nmax[2]; k < nmax[2]; ++k) push(0, j, k);
    for (int i = 1; i < nmax[0]; ++i)
        for (int j = -nmax[1]; j < nmax[1]; ++j)
            for (int k = -nmax[2]; k < nmax[2]; ++k) push(i, j, k);
    std::vector<float> info;
    const double y0 = 1.0 / std::sqrt(4.0 * M_PI), y1c = std::sqrt(3.0 / (4.0 * M_PI));
    int K = 0;
    for (size_t e = 0; e < nl.size(); e += 3) {
        double kv[3];
        for (int j = 0; j < 3; ++j) kv[j] = nl[e] * rc[j] + nl[e + 1] * rc[3 + j] + nl[e + 2] * rc[6 + j];
        const double k2 = kv[0] * kv[0] + kv[1] * kv[1] + kv[2] * kv[2];
        const bool k0 = e == 0;
        if (!k0 && k2 > P.kcut * P.kcut) continue;
        const double km = k0 ? 0.0 : std::sqrt(k2);
        // permuted (y, z, x) unit vector for e3nn's l = 1 harmonics
        const double kp[3] = {kv[1], kv[2], kv[0]};
        const double inv_n = km > 0 ? 1.0 / km : 0.0;
        float rec[KI] = {};
        rec[0] = (float)nl[e];
        rec[1] = (float)nl[e + 1];
        rec[2] = (float)nl[e + 2];
        rec[3] = (float)kv[0];
        rec[4] = (float)kv[1];
        rec[5] = (float)kv[2];
        rec[6] = k0 ? 0.0f : (float)(P.FC / k2);
        rec[7] = k0 ? 0.5f : 1.0f;
        {  // density basis (1 sigma): l = 0 real, l = 1 imaginary with phase -1
            const double ex = std::exp(-0.5 * km * km * P.sigma_d * P.sigma_d);
            const double f0 = P.p0d * ex * P.cl_d[0], f1 = P.p1d * km * ex * P.cl_d[1];
            rec[8] = (float)(f0 * y0);
            for (int m = 0; m < 3; ++m) rec[13 + m] = (float)(-f1 * y1c * kp[m] * inv_n);
        }
        for (int s = 0; s < 2; ++s) {  // feature basis, (sigma, m) order
            const double ex = std::exp(-0.5 * km * km * P.sigma_f[s] * P.sigma_f[s]);
            const double f0 = P.p0f[s] * ex * P.cl_f[s][0], f1 = P.p1f[s] * km * ex * P.cl_f[s][1];
            rec[16 + s * 4] = (float)(f0 * y0);
            for (int m = 0; m < 3; ++m) rec[24 + s * 4 + 1 + m] = (float)(-f1 * y1c * kp[m] * inv_n);
        }
        info.insert(info.end(), rec, rec + KI);
        ++K;
    }
    if (K > P.K_cap) {
        if (P.kinfo) cudaFree(P.kinfo);
        P.K_cap = K + K / 4 + 64;
        CUDA_CHECK_THROW(device_malloc(&P.kinfo, (size_t)P.K_cap * KI * sizeof(float)));
        if (P.SC) cudaFree(P.SC);
        if (P.SS) cudaFree(P.SS);
        if (P.dk) cudaFree(P.dk);
        P.SC = P.SS = nullptr;
        P.dk = nullptr;
        for (Impl::Step& s : P.steps) {
            if (s.AB) cudaFree(s.AB);
            if (s.SFq) cudaFree(s.SFq);
            s.AB = nullptr;
            s.SFq = nullptr;
        }
        CUDA_CHECK_THROW(device_malloc(&P.SC, (size_t)P.K_cap * 16 * sizeof(double)));
        CUDA_CHECK_THROW(device_malloc(&P.SS, (size_t)P.K_cap * 16 * sizeof(double)));
        CUDA_CHECK_THROW(device_malloc(&P.dk, (size_t)P.K_cap * 16 * sizeof(float)));
        for (Impl::Step& s : P.steps) {
            CUDA_CHECK_THROW(device_malloc(&s.AB, (size_t)P.K_cap * 32 * sizeof(float)));
            CUDA_CHECK_THROW(device_malloc(&s.SFq, (size_t)P.K_cap * 16 * sizeof(double)));
        }
    }
    if (!P.minv) CUDA_CHECK_THROW(cudaMalloc(&P.minv, 9 * sizeof(double)));
    P.K = K;
    CUDA_CHECK_THROW(cudaMemcpy(P.kinfo, info.data(), info.size() * sizeof(float), cudaMemcpyHostToDevice));
    double minv[9];
    for (int d = 0; d < 3; ++d)
        for (int j = 0; j < 3; ++j) minv[3 * d + j] = inv[3 * j + d];  // s = inv(cell)^T r
    CUDA_CHECK_THROW(cudaMemcpy(P.minv, minv, sizeof(minv), cudaMemcpyHostToDevice));
    // The cell changed, so every captured graph is stale: besides the buffers and the launch sizes (K), record()
    // passes the volume factors alpha = (2 pi)^3 / V and e_scale = V / (2 pi)^6 to its kernels by value. Reporting
    // only a changed K left the first cell's volume in the graph for small cell changes (NaCl 2x2x2, strain 3e-4:
    // 1e-6 eV/atom, 9e-5 eV/A, and an energy that no longer matched the stress).
    return true;
}

// Device bytes of the system's long-range buffers, for the memory plans: the per-atom ones (charges, potentials,
// features and their gradients, one set per SCF step), the zero slab, and the k-space ones, whose length follows the
// cell (a larger cell of the same density has as many k-vectors more as atoms).
size_t PolarLR::system_bytes() const {
    const Impl& P = *p_;
    const size_t per_k = (size_t)KI * sizeof(float) + 2 * 16 * sizeof(double) + 16 * sizeof(float) +
                         P.steps.size() * (32 * sizeof(float) + 16 * sizeof(double));
    return P.sys_bytes + P.bwd_zero_bytes + (size_t)P.K_cap * per_k;
}

void PolarLR::free_system() {
    Impl& P = *p_;
    for (void* q : P.s_) cudaFree(q);
    P.s_.clear();
    P.sys_bytes = 0;
    if (P.bwd_zero_slab) cudaFree(P.bwd_zero_slab);
    P.bwd_zero_slab = nullptr;
    P.bwd_zero_bytes = 0;
    for (Impl::Step& s : P.steps) {
        if (s.AB) cudaFree(s.AB);
        if (s.SFq) cudaFree(s.SFq);
    }
    P.steps.clear();
    P.N = 0;
}

void PolarLR::alloc_system(int N) {
    free_system();
    Impl& P = *p_;
    const size_t n = (size_t)N, C = (size_t)P.C;
    auto align256 = [](size_t b) { return (b + 255) & ~size_t(255); };
    size_t zbytes = align256(n * 8 * sizeof(float)) * 3 + align256(n * 16 * sizeof(float));
    for (int l = 0; l <= P.lmax; ++l) zbytes += align256(n * (2 * l + 1) * C * sizeof(float));
    CUDA_CHECK_THROW(device_malloc(&P.bwd_zero_slab, zbytes));
    P.bwd_zero_bytes = zbytes;
    char* zbase = static_cast<char*>(P.bwd_zero_slab);
    size_t zoff = 0;
    auto zalloc = [&](size_t floats) -> float* {
        float* q = reinterpret_cast<float*>(zbase + zoff);
        zoff += align256(floats * sizeof(float));
        return q;
    };
    P.fracu = reinterpret_cast<unsigned*>(P.sys(n * 3));
    P.qsrc = P.sys(n * 8);
    P.q0 = P.sys(n * 8);
    P.qfin = P.sys(n * 8);
    P.qt = P.sys(n * 4);
    P.f16 = P.sys(n * 16);
    P.kpart = reinterpret_cast<double*>(P.sys(2 * (size_t)k_splits_max(N) * n * 16));
    P.g16 = P.sys(n * 16);
    P.dq = zalloc(n * 8);
    P.dq2 = zalloc(n * 8);
    P.dq0 = zalloc(n * 8);
    P.dpot = zalloc(n * 16);
    P.fx1 = P.sys(n * 16);
    P.fz2 = P.sys(n * 16);
    P.fk = P.sys(n * 2);
    P.dfk = P.sys(n * 10);
    P.dfx = P.sys(n * 16);
    for (int l = 0; l <= P.lmax; ++l) {
        P.fm[l] = P.sys(n * (2 * l + 1) * C);
        P.dfm[l] = zalloc(n * (2 * l + 1) * C);
        P.dZ[l] = P.sys(n * (2 * l + 1) * C);
        P.dnw[l] = (l <= 1) ? P.sys(n * (2 * l + 1) * C) : nullptr;
        P.Zq[l] = P.sys(n * (2 * l + 1) * C);
        P.Zv[l] = P.sys(n * (2 * l + 1) * C);
        if (!P.fold) {
            P.dmix[l] = P.sys(n * (2 * l + 1) * C);
            P.qu[l] = P.sys(n * (2 * l + 1) * C);
            P.vu[l] = P.sys(n * (2 * l + 1) * C);
        }
    }
    P.dP = P.sys(n * C);
    P.dnl = std::any_of(P.upd.begin(), P.upd.end(), [](const Impl::Update& U) { return !U.tpo_fold; })
                ? P.sys(n * C)
                : nullptr;
    P.dx0 = P.sys(n * 2 * C);
    P.ds0 = P.sys(n * 64);
    P.dv1 = P.sys(n * 96);
    P.dout = P.sys(n * 10);
    P.mlp_d1 = P.sys(n * std::max<size_t>(P.max_mlp_w, 2 * C));
    P.mlp_d2 = P.sys(n * std::max<size_t>(P.max_mlp_w, 2 * C));
    P.qin_le = P.sys(n * 8);
    P.lex0 = P.sys(n * 2 * C);
    P.le_e = P.sys(n);
    P.le_z.clear();
    P.le_act.clear();
    for (int k = 0; k < P.le_mlp.n; ++k) {
        P.le_z.push_back(P.sys(n * P.le_mlp.out[k]));
        P.le_act.push_back(k < P.le_mlp.n - 1 ? P.sys(n * P.le_mlp.out[k]) : nullptr);
    }
    P.le_stat = P.sys(n * 2 * P.le_mlp.n);
    {
        double* r = nullptr;
        CUDA_CHECK_THROW(cudaMalloc(&r, 8 * (2 * P.n_rec + 4) * sizeof(double)));
        P.s_.push_back(r);
        P.red = r;
    }
    P.steps.resize(P.n_rec);
    for (int i = 0; i < P.n_rec; ++i) {
        Impl::Step& s = P.steps[i];
        const Impl::Update& U = P.upd[i];
        s.qin = P.sys(n * 8);
        s.qnew = P.sys(n * 8);
        s.pot = P.sys(n * 16);
        if (P.K_cap) {
            CUDA_CHECK_THROW(device_malloc(&s.AB, (size_t)P.K_cap * 32 * sizeof(float)));
            CUDA_CHECK_THROW(device_malloc(&s.SFq, (size_t)P.K_cap * 16 * sizeof(double)));
        }
        for (int l = 0; l <= P.lmax; ++l) {
            s.Z[l] = P.sys(n * (2 * l + 1) * C);
            if (!P.fold) s.mixed[l] = P.sys(n * (2 * l + 1) * C);
            if (l <= 1) {  // the readout reads nw_0 and nw_1 only
                s.P[l] = P.sys(n * C);
                s.nw[l] = P.sys(n * (2 * l + 1) * C);
            }
        }
        s.x0 = P.sys(n * 2 * C);
        s.z.clear();
        s.act.clear();
        for (int k = 0; k < U.mlp.n; ++k) {
            // folded (tpo_fold): the last layer's output nl is never formed
            s.z.push_back(k < U.mlp.n - 1 || !U.tpo_fold ? P.sys(n * U.mlp.out[k]) : nullptr);
            s.act.push_back(k < U.mlp.n - 1 ? P.sys(n * U.mlp.out[k]) : nullptr);
        }
        s.stat = P.sys(n * 2 * U.mlp.n);
        s.s0 = P.sys(n * 64);
        s.v1 = P.sys(n * 96);
        s.smid = P.sys(n * 64);
        s.vmid = P.sys(n * 96);
        s.out = P.sys(n * 10);
    }
    P.N = N;
}

void PolarLR::record(cudaStream_t st, int N, const GemmFn& gemm,
                     const std::function<void()>& fork_fn, const std::function<void(int)>& lane_fn,
                     const std::function<void()>& join_fn, const int* species, const double* pos64,
                     const std::vector<std::vector<float*>>& h, const std::vector<std::vector<float*>>& dh,
                     double* energy, double* forces, int compute_stress, double* virial) {
    Impl& P = *p_;
    if (!P.have_cell) throw std::runtime_error("polar: no cell set");
    const int C = P.C, lm = P.lmax, K = P.K, R = P.rows;
    const float alpha = (float)(std::pow(TWO_PI, 3) / P.vol);
    const float beta = (float)(2.0 / std::pow(TWO_PI, 3));
    const float e_scale = (float)(P.vol / std::pow(TWO_PI, 6));
    const int nred = 8 * (2 * P.n_rec + 4);
    auto dimL = [](int l) { return 2 * l + 1; };
    auto fork = [&] { if (fork_fn) fork_fn(); };
    auto lane = [&](int k) { if (lane_fn) lane_fn(k); };
    auto join = [&] { if (join_fn) join_fn(); };
    CUDA_CHECK_THROW(cudaMemsetAsync(P.red, 0, nred * sizeof(double), st));
    double* red_f0 = P.red;                       // first fukui
    auto red_step = [&](int i) { return P.red + 8 * (1 + i); };
    frac_kernel<<<blocks_for(N), 256, 0, st>>>(N, pos64, P.minv, P.fracu);
    const int kc = k_chunk(N, K);
    const dim3 kgrid(blocks_for(N, 128), (unsigned)((K + kc - 1) / kc));

    const std::vector<float*>& hL = h[P.L - 1];
    // ---------------- sources, mixer, and Fukui projection (independent across lanes); the first source GEMM that
    // runs initialises qsrc (the zero blocks' are skipped)
    bool src_none = true;
    for (int t = 0; t < P.L; ++t)
        for (int l = 0; l <= lm; ++l) src_none = src_none && P.src_zero[t][l];
    if (src_none) CUDA_CHECK_THROW(cudaMemsetAsync(P.qsrc, 0, (size_t)N * 8 * sizeof(float), st));
    fork();
    bool src_first = true;
    for (int t = 0; t < P.L; ++t)
        for (int l = 0; l <= lm; ++l) {
            if (!P.src_zero[t][l]) {
                lane(0);
                gemm(false, N, 8, dimL(l) * C, 1.0f, h[t][l], dimL(l) * C, P.src[t] + (size_t)P.off[l] * 8, 8,
                     src_first ? 0.0f : 1.0f, P.qsrc, 8);
                src_first = false;
            }
            lane(1 + l);
            gemm(false, N * dimL(l), C, C, 1.0f, h[t][l], C, P.mix[t][l], C, t == 0 ? 0.0f : 1.0f, P.fm[l], C);
        }
    lane(4);
    gemm(false, N, 16, C, 1.0f, hL[0], C, P.fk_W1, 16, 0.0f, P.fx1, 16);
    join();
    fk_fwd_kernel<<<blocks_for(N, 4), 128, 0, st>>>(N, P.fk_act, P.fx1, P.fk_Wm, P.fk_bm, P.fk_W2, P.fk_b2, P.fz2, P.fk);
    fukui_sums_kernel<<<blocks_for(N), 256, 0, st>>>(N, P.qsrc, P.fk, 2, red_f0);
    fukui_apply_kernel<<<blocks_for((int64_t)N * 8), 256, 0, st>>>(N, P.qsrc, P.fk, 2, red_f0, P.q0);
    // S118 (`mono`): the passes on the live channels only (the others written as 0), same sums
    const auto sf8 = P.mono ? &launch_sf<8, 2> : &launch_sf<8>;
    const auto sf4 = P.mono ? &launch_sf<4, 1> : &launch_sf<4>;
    const auto sf16 = P.mono ? &launch_sf<16, 4> : &launch_sf<16>;
    const auto feat_pass = P.mono ? &feat_pass_kernel<true> : &feat_pass_kernel<false>;
    const auto grad_pass_e = P.mono ? &grad_pass_kernel<1, false, true> : &grad_pass_kernel<1, false>;
    const auto grad_pass_f = P.mono ? &grad_pass_kernel<2, true, true> : &grad_pass_kernel<2, true>;
    auto features = [&](const float* q, double* SFq, float* AB, float* pot) {
        double* SCq = SFq;
        double* SSq = SFq + (size_t)P.K_cap * 8;
        sf8(st, N, K, P.kinfo, P.fracu, q, SCq, SSq);
        feat_coef_kernel<<<blocks_for(K), 256, 0, st>>>(K, P.kinfo, alpha, beta, SCq, SSq, AB);
        feat_pass<<<kgrid, 128, 0, st>>>(N, K, kc, P.kinfo, P.fracu, AB, P.f16, P.kpart);
        if (kgrid.y > 1)
            k_reduce_kernel<<<blocks_for((int64_t)N * 16), 256, 0, st>>>(N, (int)kgrid.y, 16, 0, P.kpart, P.f16, 16,
                                                                          nullptr);
        pot_fwd_kernel<<<blocks_for((int64_t)N * 16), 256, 0, st>>>(N, P.fc, P.f16, q, pot);
    };
    // the first n_run layers (n_run = m.n - 1: the hidden layers only, the last one folded into the next product)
    auto mlp_fwd = [&](const Impl::Mlp& m, int n_run, const float* x, std::vector<float*>& z, std::vector<float*>& act,
                       float* stat) {
        const float* in = x;
        for (int k = 0; k < n_run; ++k) {
            gemm(false, N, m.out[k], m.in[k], 1.0f, in, m.in[k], m.W[k], m.out[k], 0.0f, z[k], m.out[k]);
            if (k < m.n - 1) {
                bias_ln_silu_fwd_kernel<<<blocks_for(N, 4), 128, 0, st>>>(N, m.out[k], m.b[k], z[k], m.g[k], m.be[k],
                                                                          act[k], stat + (size_t)2 * N * k);
                in = act[k];
            } else {
                add_bias_kernel<<<blocks_for((int64_t)N * m.out[k]), 256, 0, st>>>(N, m.out[k], m.b[k], z[k],
                                                                                   m.out[k]);
            }
        }
    };
    // dz_top: gradient of z[k_top] (the last layer's output for k_top = m.n - 1; the last hidden layer's
    // pre-activation for k_top = m.n - 2, the last layer folded away); returns the gradient of the MLP input in dxout
    auto mlp_bwd = [&](const Impl::Mlp& m, int k_top, const std::vector<float*>& z, const float* stat,
                       const float* dz_top, float* dxout) {
        // dz: gradient of layer k's output (pre-activation for k < n - 1). Each GEMM writes the scratch buffer that
        // does not hold its input; the LayerNorm-SiLU reverse then runs in place on it.
        const float* dz = dz_top;
        for (int k = k_top; k >= 0; --k) {
            float* dst = k > 0 ? (dz == P.mlp_d1 ? P.mlp_d2 : P.mlp_d1) : dxout;
            gemm(true, N, m.in[k], m.out[k], 1.0f, dz, m.out[k], m.W[k], m.out[k], 0.0f, dst, m.in[k]);
            if (k > 0) {
                ln_silu_bwd_kernel<<<blocks_for(N, 4), 128, 0, st>>>(N, m.out[k - 1], z[k - 1], m.g[k - 1],
                                                                     m.be[k - 1], stat + (size_t)2 * N * (k - 1), dst,
                                                                     dst);
                dz = dst;
            }
        }
    };

    // ---------------- SCF
    const float* qcur = P.q0;
    float* pot_last = nullptr;
    for (int i = 0; i < P.n_rec; ++i) {
        Impl::Step& s = P.steps[i];
        const Impl::Update& U = P.upd[i];
        if (qcur != s.qin)
            CUDA_CHECK_THROW(cudaMemcpyAsync(s.qin, qcur, (size_t)N * 8 * sizeof(float), cudaMemcpyDeviceToDevice, st));
        features(s.qin, s.SFq, s.AB, s.pot);
        // pot is (alpha features | beta features): the two spins share the k-space pass via the channel layout
        if (lm > 0) fork();
        for (int l = 0; l <= lm; ++l) {
            if (lm > 0) lane(l);
            // S123: the zero blocks' products are skipped; the first GEMM that runs initialises the sum
            float* sum = P.fold ? s.Z[l] : s.mixed[l];
            float b0 = 0.0f;
            if (!U.zpot[l]) {
                gemm(false, N, dimL(l) * C, 16, 1.0f, s.pot, 16, (P.fold ? U.Wpot_dot : U.Wpot) + P.off[l], R, 0.0f,
                     sum, dimL(l) * C);
                b0 = 1.0f;
            }
            if (!U.zq[l]) {
                gemm(false, N, dimL(l) * C, 8, 1.0f, s.qin, 8, (P.fold ? U.Wq_dot : U.Wq) + P.off[l], R, b0, sum,
                     dimL(l) * C);
                b0 = 1.0f;
            }
            gemm(false, N * dimL(l), C, C, 1.0f, P.fm[l], C, P.fold ? U.Wnf_dot[l] : U.Wnf[l], C, b0, sum, C);
            if (!P.fold) gemm(true, N * dimL(l), C, C, 1.0f, s.mixed[l], C, U.dot[l], C, 0.0f, s.Z[l], C);
        }
        if (lm > 0) join();
        inv_kernel<<<blocks_for((int64_t)N * C), 256, 0, st>>>(N, C, lm, P.fm[0], P.fm[1], P.fm[2], s.Z[0], s.Z[1],
                                                                s.Z[2], U.emb, species, s.x0);
        // P_l = nl tpo_l^T for l <= 1 (the readout reads nw_0 and nw_1 only), nl the MLP's output
        const int lp = std::min(lm, 1);
        if (U.tpo_fold) {  // P_l = h tpo_W_l (+ tpo_b_l, in bcast_mul), h the last hidden layer's activation
            mlp_fwd(U.mlp, U.mlp.n - 1, s.x0, s.z, s.act, s.stat);
            const int k = U.mlp.n - 2, H = U.mlp.out[k];
            if (lp > 0) fork();
            for (int l = 0; l <= lp; ++l) {
                if (lp > 0) lane(l);
                gemm(false, N, C, H, 1.0f, s.act[k], H, U.tpo_W[l], C, 0.0f, s.P[l], C);
            }
            if (lp > 0) join();
        } else {
            mlp_fwd(U.mlp, U.mlp.n, s.x0, s.z, s.act, s.stat);
            const float* nl = s.z.back();
            if (lp > 0) fork();
            for (int l = 0; l <= lp; ++l) {
                if (lp > 0) lane(l);
                gemm(true, N, C, C, 1.0f, nl, C, U.tpo[l], C, 0.0f, s.P[l], C);
            }
            if (lp > 0) join();
        }
        for (int l = 0; l <= lp; ++l)
            bcast_mul_kernel<<<blocks_for((int64_t)N * dimL(l) * C), 256, 0, st>>>(
                (int64_t)N * dimL(l) * C, C, dimL(l), P.fm[l], s.P[l], U.tpo_fold ? U.tpo_b[l] : nullptr, s.nw[l]);
        if (lm >= 1) fork();
        if (lm >= 1) lane(0);
        gemm(false, N, lm >= 1 ? 64 : 32, C, 1.0f, s.nw[0], C, U.ro_W1[0], 64, 0.0f, s.s0, 64);  // S124: scalar half
        if (lm >= 1) {
            lane(1);
            gemm(false, N * 3, 32, C, 1.0f, s.nw[1], C, U.ro_W1[1], 32, 0.0f, s.v1, 32);
            join();
        }
        ro_fwd_kernel<<<blocks_for(N, 4), 128, 0, st>>>(N, U.rc, lm >= 1, s.s0, s.v1, U.ro_Wm0, U.ro_bm, U.ro_Wm1,
                                                        U.ro_W2, U.ro_b2, s.smid, s.vmid, s.out);
        // q_new = q_in + out[:8]; then the Fukui constraint with out[8:10]
        add8_to_kernel<<<blocks_for((int64_t)N * 8), 256, 0, st>>>(N, s.out, 10, s.qin, s.qnew);
        fukui_sums_kernel<<<blocks_for(N), 256, 0, st>>>(N, s.qnew, s.out + 8, 10, red_step(i));
        float* qnext = i + 1 < P.n_rec ? P.steps[i + 1].qin : P.qfin;
        fukui_apply_kernel<<<blocks_for((int64_t)N * 8), 256, 0, st>>>(N, s.qnew, s.out + 8, 10, red_step(i), qnext);
        qcur = qnext;
        pot_last = s.pot;
    }
    // ---------------- local electron energy
    if (P.add_le) {
        add8_to_kernel<<<blocks_for((int64_t)N * 8), 256, 0, st>>>(N, P.q0, 8, P.qfin, P.qin_le);
        if (P.fold) {
            fork();
            for (int l = 0; l <= lm; ++l) {  // S123: Zq_l (Zv_l) for l <= le_lq (le_lv) only, the others are zero
                lane(2 * l);
                if (l <= P.le_lq)
                    gemm(false, N, dimL(l) * C, 8, 1.0f, P.qin_le, 8, P.le_Wq_dot + P.off[l], R, 0.0f, P.Zq[l],
                         dimL(l) * C);
                lane(2 * l + 1);
                if (l <= P.le_lv)
                    gemm(false, N, dimL(l) * C, 16, 1.0f, pot_last, 16, P.le_Wv_dot + P.off[l], R, 0.0f, P.Zv[l],
                         dimL(l) * C);
            }
            join();
            add_bias_kernel<<<blocks_for((int64_t)N * C), 256, 0, st>>>(N, C, P.le_bq_dot, P.Zq[0], C);
            add_bias_kernel<<<blocks_for((int64_t)N * C), 256, 0, st>>>(N, C, P.le_bv_dot, P.Zv[0], C);
        } else {
            fork();
            for (int l = 0; l <= lm; ++l) {
                lane(2 * l);
                if (l <= P.le_lq)
                    gemm(false, N, dimL(l) * C, 8, 1.0f, P.qin_le, 8, P.le_Wq + P.off[l], R, 0.0f, P.qu[l],
                         dimL(l) * C);
                lane(2 * l + 1);
                if (l <= P.le_lv)
                    gemm(false, N, dimL(l) * C, 16, 1.0f, pot_last, 16, P.le_Wv + P.off[l], R, 0.0f, P.vu[l],
                         dimL(l) * C);
            }
            join();
            add_bias_kernel<<<blocks_for((int64_t)N * C), 256, 0, st>>>(N, C, P.le_bq, P.qu[0], C);
            add_bias_kernel<<<blocks_for((int64_t)N * C), 256, 0, st>>>(N, C, P.le_bv, P.vu[0], C);
            fork();
            for (int l = 0; l <= lm; ++l) {
                lane(2 * l);
                if (l <= P.le_lq) gemm(true, N * dimL(l), C, C, 1.0f, P.qu[l], C, P.le_dotq[l], C, 0.0f, P.Zq[l], C);
                lane(2 * l + 1);
                if (l <= P.le_lv) gemm(true, N * dimL(l), C, C, 1.0f, P.vu[l], C, P.le_dotv[l], C, 0.0f, P.Zv[l], C);
            }
            join();
        }
        inv_kernel<<<blocks_for((int64_t)N * C), 256, 0, st>>>(N, C, P.le_lq, hL[0], P.le_lq >= 1 ? hL[1] : nullptr,
                                                                P.le_lq >= 2 ? hL[2] : nullptr, P.Zq[0], P.Zq[1],
                                                                P.Zq[2], nullptr, species, P.lex0);
        inv_kernel<<<blocks_for((int64_t)N * C), 256, 0, st>>>(N, C, P.le_lv, hL[0], P.le_lv >= 1 ? hL[1] : nullptr,
                                                                P.le_lv >= 2 ? hL[2] : nullptr, P.Zv[0], P.Zv[1],
                                                                P.Zv[2], nullptr, species, P.lex0 + C);
        mlp_fwd(P.le_mlp, P.le_mlp.n, P.lex0, P.le_z, P.le_act, P.le_stat);
        sum_rows_kernel<<<blocks_for(N), 256, 0, st>>>(N, P.le_z.back(), energy);
    }
    // ---------------- Coulomb energy
    qtot_kernel<<<blocks_for((int64_t)N * 4), 256, 0, st>>>(N, P.qfin, P.qt);
    sf4(st, N, K, P.kinfo, P.fracu, P.qt, P.SC, P.SS);
    energy_kernel<<<blocks_for(K), 256, 0, st>>>(K, P.kinfo, alpha, e_scale, P.SC, P.SS, energy);

    // ================= backward
    // Coulomb: dqt -> dq (both spins), direct position gradient
    CUDA_CHECK_THROW(cudaMemsetAsync(P.bwd_zero_slab, 0, P.bwd_zero_bytes, st));
    bwd_coef_kernel<<<blocks_for(K), 256, 0, st>>>(K, 1, 1, P.kinfo, alpha, beta, e_scale, nullptr, nullptr, P.SC, P.SS,
                                                   P.dk);
    if (compute_stress)
        lr_virial_kernel<<<blocks_for(K), 256, 0, st>>>(K, 1, P.kinfo, P.bc, alpha, beta, e_scale, P.SC, P.SS, nullptr,
                                                        nullptr, virial);
    grad_pass_e<<<kgrid, 128, 0, st>>>(N, K, kc, P.kinfo, P.fracu, P.qt, 4, P.dk, nullptr, nullptr, P.dq2, 8, forces,
                                       P.kpart);
    if (kgrid.y > 1)
        k_reduce_kernel<<<blocks_for((int64_t)N * 11), 256, 0, st>>>(N, (int)kgrid.y, 11, 4, P.kpart, P.dq2, 8, forces);
    // dq2[:, 0:4] holds dE/dqt: both spins get it
    spin_grad_kernel<<<blocks_for((int64_t)N * 4), 256, 0, st>>>(N, P.dq2, P.dq);
    // local electron energy backward
    if (P.add_le) {
        fill_kernel<<<blocks_for(N), 256, 0, st>>>(N, 1.0f, P.dout);  // dE/de per atom (the MLP's single output)
        mlp_bwd(P.le_mlp, P.le_mlp.n - 1, P.le_z, P.le_stat, P.dout, P.dx0);
        for (int l = 0; l <= lm; ++l) {
            // lex0 = [sum_m hL . Zq, sum_m hL . Zv]: dhL += dZ-weighted, dZq = dlex . hL (S123: l <= le_lq / le_lv)
            if (l <= P.le_lq) {
                inv_bwd_kernel<<<blocks_for((int64_t)N * dimL(l) * C), 256, 0, st>>>(
                    (int64_t)N * dimL(l) * C, C, dimL(l), P.dx0, 2 * C, hL[l], P.Zq[l], dh[P.L - 1][l], P.dZ[l]);
                if (P.fold) {
                    gemm(true, N, 8, dimL(l) * C, 1.0f, P.dZ[l], dimL(l) * C, P.le_Wq_dot + P.off[l], R, 1.0f, P.dq0,
                         8);
                } else {
                    gemm(false, N * dimL(l), C, C, 1.0f, P.dZ[l], C, P.le_dotq[l], C, 0.0f, P.dmix[l], C);
                    gemm(true, N, 8, dimL(l) * C, 1.0f, P.dmix[l], dimL(l) * C, P.le_Wq + P.off[l], R, 1.0f, P.dq0,
                         8);
                }
            }
            if (l <= P.le_lv) {
                inv_bwd_kernel<<<blocks_for((int64_t)N * dimL(l) * C), 256, 0, st>>>(
                    (int64_t)N * dimL(l) * C, C, dimL(l), P.dx0 + C, 2 * C, hL[l], P.Zv[l], dh[P.L - 1][l], P.dZ[l]);
                if (P.fold) {
                    gemm(true, N, 16, dimL(l) * C, 1.0f, P.dZ[l], dimL(l) * C, P.le_Wv_dot + P.off[l], R, 1.0f,
                         P.dpot, 16);
                } else {
                    gemm(false, N * dimL(l), C, C, 1.0f, P.dZ[l], C, P.le_dotv[l], C, 0.0f, P.dmix[l], C);
                    gemm(true, N, 16, dimL(l) * C, 1.0f, P.dmix[l], dimL(l) * C, P.le_Wv + P.off[l], R, 1.0f, P.dpot,
                         16);
                }
            }
        }
        // q_in(le) = qfin + q0
        axpy_kernel<<<blocks_for((int64_t)N * 8), 256, 0, st>>>((int64_t)N * 8, 1.0f, P.dq0, P.dq);
    }
    // SCF reverse: P.dq = dE/d q_{i+1}; P.dpot = dE/d pot_i (only from the electron energy for the last step)
    for (int i = P.n_rec - 1; i >= 0; --i) {
        Impl::Step& s = P.steps[i];
        const Impl::Update& U = P.upd[i];
        double* rs = red_step(i);
        // Fukui constraint reverse: dqnew, dout[8:10]
        fukui_bwd_sums_kernel<<<blocks_for(N), 256, 0, st>>>(N, P.dq, s.out + 8, 10, rs);
        fukui_bwd_kernel<<<blocks_for((int64_t)N * 8), 256, 0, st>>>(N, P.dq, s.out + 8, 10, rs, P.dq2, P.dout + 8);
        // q_new = q_in + out[:8]: dout[:8] = dqnew (assigned directly; fukui_bwd already set dout[8..9])
        add8_kernel<<<blocks_for((int64_t)N * 8), 256, 0, st>>>(N, P.dq2, 8, P.dout, 10, 1);
        // readout reverse -> dnew
        ro_bwd_kernel<<<blocks_for(N, 4), 128, 0, st>>>(N, U.rc, lm >= 1, s.s0, s.v1, U.ro_Wm0, U.ro_Wm1, U.ro_W2,
                                                        s.smid, s.vmid, P.dout, P.ds0, P.dv1);
        if (lm >= 1) fork();
        if (lm >= 1) lane(0);
        gemm(true, N, C, lm >= 1 ? 64 : 32, 1.0f, P.ds0, 64, U.ro_W1[0], 64, 0.0f, P.dnw[0], C);  // S124: scalar half
        if (lm >= 1) {
            lane(1);
            gemm(true, N * 3, C, 32, 1.0f, P.dv1, 32, U.ro_W1[1], 32, 0.0f, P.dnw[1], C);
            join();
        }
        // nw_l = fm_l * P_l (ro_W1 only feeds l = 0, 1). Folded, dP_l tpo_W_l^T is the gradient of the last hidden
        // layer's activation (accumulated over l in mlp_d1), whose LayerNorm-SiLU reverse starts the MLP reverse.
        float* dhid = P.mlp_d1;
        const int kh = U.mlp.n - 2, Hh = U.tpo_fold ? U.mlp.out[kh] : 0;
        for (int l = 0; l <= std::min(lm, 1); ++l) {
            bcast_mul_bwd_kernel<<<blocks_for((int64_t)N * C), 256, 0, st>>>(
                N, C, dimL(l), P.fm[l], s.P[l], U.tpo_fold ? U.tpo_b[l] : nullptr, P.dnw[l], P.dfm[l], P.dP, C);
            if (U.tpo_fold)
                gemm(true, N, Hh, C, 1.0f, P.dP, C, U.tpo_W[l], C, l == 0 ? 0.0f : 1.0f, dhid, Hh);
            else
                gemm(false, N, C, C, 1.0f, P.dP, C, U.tpo[l], C, l == 0 ? 0.0f : 1.0f, P.dnl, C);
        }
        if (U.tpo_fold) {
            ln_silu_bwd_kernel<<<blocks_for(N, 4), 128, 0, st>>>(N, Hh, s.z[kh], U.mlp.g[kh], U.mlp.be[kh],
                                                                 s.stat + (size_t)2 * N * kh, dhid, dhid);
            mlp_bwd(U.mlp, kh, s.z, s.stat, dhid, P.dx0);
        } else {
            mlp_bwd(U.mlp, U.mlp.n - 1, s.z, s.stat, P.dnl, P.dx0);
        }
        // inv = sum fm . Z
        for (int l = 0; l <= lm; ++l)
            inv_bwd_kernel<<<blocks_for((int64_t)N * dimL(l) * C), 256, 0, st>>>(
                (int64_t)N * dimL(l) * C, C, dimL(l), P.dx0, 2 * C, P.fm[l], s.Z[l], P.dfm[l], P.dZ[l]);
        if (P.fold) {
            // dfm += dZ Wnf_dot^T per l; dpot / dq2 from every l on one lane each (they accumulate across l)
            fork();
            for (int l = 0; l <= lm; ++l) {
                lane(l);
                gemm(true, N * dimL(l), C, C, 1.0f, P.dZ[l], C, U.Wnf_dot[l], C, 1.0f, P.dfm[l], C);
            }
            lane(lm + 1);
            for (int l = 0; l <= lm; ++l)  // S123: not the zero blocks
                if (!U.zpot[l])
                    gemm(true, N, 16, dimL(l) * C, 1.0f, P.dZ[l], dimL(l) * C, U.Wpot_dot + P.off[l], R, 1.0f, P.dpot,
                         16);
            lane(lm + 2);
            for (int l = 0; l <= lm; ++l)
                if (!U.zq[l])
                    gemm(true, N, 8, dimL(l) * C, 1.0f, P.dZ[l], dimL(l) * C, U.Wq_dot + P.off[l], R, 1.0f, P.dq2, 8);
            join();
        } else {
            if (lm > 0) fork();
            for (int l = 0; l <= lm; ++l) {
                if (lm > 0) lane(l);
                gemm(false, N * dimL(l), C, C, 1.0f, P.dZ[l], C, U.dot[l], C, 0.0f, P.dmix[l], C);
                gemm(true, N * dimL(l), C, C, 1.0f, P.dmix[l], C, U.Wnf[l], C, 1.0f, P.dfm[l], C);
            }
            if (lm > 0) join();
            fork();
            for (int l = 0; l <= lm; ++l) {  // S123: not the zero blocks
                lane(0);
                if (!U.zpot[l])
                    gemm(true, N, 16, dimL(l) * C, 1.0f, P.dmix[l], dimL(l) * C, U.Wpot + P.off[l], R, 1.0f, P.dpot,
                         16);
                lane(1);
                if (!U.zq[l])
                    gemm(true, N, 8, dimL(l) * C, 1.0f, P.dmix[l], dimL(l) * C, U.Wq + P.off[l], R, 1.0f, P.dq2, 8);
            }
            join();
        }
        // pot = (features(q_in) - si(q_in)) / norms
        pot_bwd_kernel<<<blocks_for((int64_t)N * 2), 256, 0, st>>>(N, P.fc, P.dpot, P.g16, P.dq2);
        sf16(st, N, K, P.kinfo, P.fracu, P.g16, P.SC, P.SS);
        // features_from_q again for rho is not needed: the backward coefficients take GA/GB only
        bwd_coef_kernel<<<blocks_for(K), 256, 0, st>>>(K, 2, 0, P.kinfo, alpha, beta, e_scale, P.SC, P.SS, nullptr,
                                                       nullptr, P.dk);
        if (compute_stress)
            lr_virial_kernel<<<blocks_for(K), 256, 0, st>>>(K, 0, P.kinfo, P.bc, alpha, beta, e_scale, s.SFq,
                                                            s.SFq + (size_t)P.K_cap * 8, P.SC, P.SS, virial);
        grad_pass_f<<<kgrid, 128, 0, st>>>(N, K, kc, P.kinfo, P.fracu, s.qin, 8, P.dk, P.g16, s.AB, P.dq2, 8, forces,
                                           P.kpart);
        if (kgrid.y > 1)
            k_reduce_kernel<<<blocks_for((int64_t)N * 11), 256, 0, st>>>(N, (int)kgrid.y, 11, 8, P.kpart, P.dq2, 8,
                                                                          forces);
        // dq_in -> becomes dE/d q_{i} for the step before
        CUDA_CHECK_THROW(cudaMemcpyAsync(P.dq, P.dq2, (size_t)N * 8 * sizeof(float), cudaMemcpyDeviceToDevice, st));
        if (i > 0) CUDA_CHECK_THROW(cudaMemsetAsync(P.dpot, 0, (size_t)N * 16 * sizeof(float), st));
    }
    // q_0 (after the first Fukui constraint) also feeds the electron energy
    axpy_kernel<<<blocks_for((int64_t)N * 8), 256, 0, st>>>((int64_t)N * 8, 1.0f, P.dq0, P.dq);
    // first Fukui constraint reverse
    CUDA_CHECK_THROW(cudaMemsetAsync(red_f0 + 4, 0, 2 * sizeof(double), st));
    fukui_bwd_sums_kernel<<<blocks_for(N), 256, 0, st>>>(N, P.dq, P.fk, 2, red_f0);
    fukui_bwd_kernel<<<blocks_for((int64_t)N * 8), 256, 0, st>>>(N, P.dq, P.fk, 2, red_f0, P.dq2, P.dfk);
    fk_bwd_kernel<<<blocks_for(N, 4), 128, 0, st>>>(N, P.fk_act, P.fx1, P.fk_Wm, P.fk_W2, P.fz2, P.dfk, P.dfx);
    // sources and mixer backward (+ fk_W1^T on the same lane as (L - 1, 0))
    fork();
    for (int t = 0; t < P.L; ++t)
        for (int l = 0; l <= lm; ++l) {
            lane(t * (lm + 1) + l);
            if (!P.src_zero[t][l])
                gemm(true, N, dimL(l) * C, 8, 1.0f, P.dq2, 8, P.src[t] + (size_t)P.off[l] * 8, 8, 1.0f, dh[t][l],
                     dimL(l) * C);
            gemm(true, N * dimL(l), C, C, 1.0f, P.dfm[l], C, P.mix[t][l], C, 1.0f, dh[t][l], C);
        }
    lane((P.L - 1) * (lm + 1));
    gemm(true, N, C, 16, 1.0f, P.dfx, 16, P.fk_W1, 16, 1.0f, dh[P.L - 1][0], C);
    join();
}

}  // namespace loup
