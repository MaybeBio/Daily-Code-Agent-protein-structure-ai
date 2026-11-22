// Row-major SIMT SGEMM C[M, N] = A[M, K] * B[K, N] + beta * C: 128 x 128 x 16 block tiles, 256 threads with 8 x 8
// outputs each, 3-stage cp.async pipeline (A kept m-major: a warp's fragment reads are 2-address broadcasts; B
// k-major), 126 registers and 48 KB shared memory, 2 blocks (16 warps) per SM. One more autotune candidate for
// sgemm_rm: on the tall-skinny products here (N = 128-384, K = 128-384) cuBLAS' SIMT kernels reach ~50% of the FMA
// pipe at 200+ registers and 8 warps per SM. Products with a transposed B use a transposed copy of B (always a model
// weight; see sgemm_rm). Every output is one in-order fmaf chain over k, as in cuBLAS' SIMT kernels (bit-identical
// results on the tested shapes).
#include <cuda_runtime.h>
#include <cstddef>
#include <cstdint>

#include "generic.hpp"

namespace loup {

namespace {

constexpr int kBK = 16, kStages = 3;
template <int BN>
constexpr int smem_bytes() { return kStages * (128 * kBK + kBK * BN) * (int)sizeof(float); }  // 48 KB / 36 KB

__device__ __forceinline__ void cp_async16(void* smem, const void* gmem, bool full) {
    const unsigned s = (unsigned)__cvta_generic_to_shared(smem);
    const int n = full ? 16 : 0;  // 0 source bytes: zero-fill (rows >= M, columns >= N)
    asm volatile("cp.async.cg.shared.global [%0], [%1], 16, %2;" ::"r"(s), "l"(gmem), "r"(n));
}
__device__ __forceinline__ void cp_async_commit() { asm volatile("cp.async.commit_group;"); }
__device__ __forceinline__ void cp_async_wait_one_pending() { asm volatile("cp.async.wait_group %0;" ::"n"(kStages - 2)); }

__device__ __forceinline__ float sigmoid_f(float x) { return 1.0f / (1.0f + expf(-x)); }
__device__ __forceinline__ float dsilu_f(float x) {
    const float s = sigmoid_f(x);
    return s * (1.0f + x * (1.0f - s));
}

// Epilogue of sgemm128_kernel<8, true, true, DEG> for dgout_l = A @ W_2[l]^T (B: its [K, N] copy, N = g.C): degree
// l's share of gate_bwd_kernel (generic.cu) instead of the dgout_l store. DEG = 2l + 1 rows per atom; the tile's
// 128 rows start at atom a0, its first 128 / DEG * DEG rows (128 / 126 / 125 / 126) hold whole atoms and the rest (the
// next tile's) were computed and are dropped. The tile is staged in shared memory one 64-column half at a time;
// thread (grp, cl) = (tid >> 6, tid & 63) then runs the tile's atoms grp, grp + 4, .. for column cl of the half with
// gate_bwd_kernel's arithmetic in its order (the dgout_l values are the plain GEMM's: each output is the same in-order
// fmaf chain over k). Only the dD sum is reassociated: per atom over the degree's terms and the block's 128 columns
// (warp shuffle, shared memory), then one atomic per atom and block. g.vform: as gate_bwd_kernel's vform degrees.
template <int DEG>
__device__ __forceinline__ void gate_bwd_epilogue(const float (&acc)[8][8], float* smem, int a0, int n0,
                                                  const GateArgs& g) {
    constexpr int APT = 128 / DEG;
    const int N = g.C;
    const int tid = threadIdx.x, tx = tid & 15, ty = tid >> 4, cl = tid & 63, grp = tid >> 6;
    float* sC = smem;                       // [128][64]: one half of the tile
    float* s_acc = smem + 128 * 64;         // [APT]: per-atom dD partials (factor -beta s^2)
    float* s_accq = smem + 128 * 64 + 128;  // [APT]: per-atom dD partials of vform degrees (factor -beta s)
    const int na = min(APT, g.natoms - a0);
    __syncthreads();  // every warp is done with the pipeline buffers
    if (tid < APT) s_acc[tid] = s_accq[tid] = 0.0f;
#pragma unroll
    for (int hh = 0; hh < 2; ++hh) {
        if (hh) __syncthreads();  // the first half is consumed
#pragma unroll
        for (int i = 0; i < 8; ++i)
            *reinterpret_cast<float4*>(sC + ((i < 4 ? 0 : 60) + ty * 4 + i) * 64 + tx * 4) =
                make_float4(acc[i][4 * hh], acc[i][4 * hh + 1], acc[i][4 * hh + 2], acc[i][4 * hh + 3]);
        __syncthreads();
        const int c = n0 + hh * 64 + cl;
        for (int ai = grp; ai < na; ai += 4) {
            const int a = a0 + ai;
            const float s = 1.0f / (g.D[a] * g.beta + g.alpha);
            const int64_t r0 = (int64_t)a * 4 * N, q0 = g.res0_sp ? (int64_t)g.res0_sp[a] * 4 * N : r0;
            auto pre0 = [&](int col) { return g.lin0[r0 + col] * s + (g.res0 ? g.res0[q0 + col] : 0.0f); };
            const float* go = sC + ai * DEG * 64 + cl;
            float part = 0.0f, partq = 0.0f;
            if (DEG == 1) {
                const float p = pre0(c);
                const float d = go[0] * g.cs * dsilu_f(p);
                if (g.dp0) g.dp0[r0 + c] = d;
                g.dl0[r0 + c] = d * s;
                part = fmaf(d, g.lin0[r0 + c], part);
            } else {
                constexpr int l = DEG / 2;
                const float gp = pre0(l * N + c);
                const float sg = sigmoid_f(gp);
                const float gt = g.cg * sg;
                float dgp;
                if (g.vform) {  // lin_l holds v = gt (lin * s): d gp = (1 - sg) sum dgout v, dD += -beta s sum dgout v
#pragma unroll
                    for (int m = 0; m < DEG; ++m) {
                        const int64_t idx = ((int64_t)a * DEG + m) * N + c;
                        const float o = go[m * 64];
                        partq = fmaf(o, g.lin_l[idx], partq);
                        g.dl_l[idx] = o * gt * s;
                    }
                    dgp = (1.0f - sg) * partq;
                } else {
                    float dg = 0.0f;
#pragma unroll
                    for (int m = 0; m < DEG; ++m) {
                        const int64_t idx = ((int64_t)a * DEG + m) * N + c;
                        const float li = g.lin_l[idx];
                        const float p = li * s + (g.res_l ? g.res_l[idx] : 0.0f);
                        const float o = go[m * 64];
                        dg = fmaf(o, p, dg);
                        const float d = o * gt;
                        if (g.dp_l) g.dp_l[idx] = d;
                        g.dl_l[idx] = d * s;
                        part = fmaf(d, li, part);
                    }
                    dgp = dg * g.cg * sg * (1.0f - sg);
                }
                if (g.dp0) g.dp0[r0 + l * N + c] = dgp;
                g.dl0[r0 + l * N + c] = dgp * s;
                part = fmaf(dgp, g.lin0[r0 + l * N + c], part);
            }
#pragma unroll
            for (int off = 16; off > 0; off >>= 1) {
                part += __shfl_xor_sync(0xffffffffu, part, off);
                partq += __shfl_xor_sync(0xffffffffu, partq, off);
            }
            if ((tid & 31) == 0) {
                atomicAdd(s_acc + ai, part);
                if (DEG > 1 && g.vform) atomicAdd(s_accq + ai, partq);
            }
        }
    }
    __syncthreads();
    if (tid < na) {
        const int a = a0 + tid;
        const float s = 1.0f / (g.D[a] * g.beta + g.alpha);
        atomicAdd(g.dD + a, -g.beta * s * s * s_acc[tid] - g.beta * s * s_accq[tid]);
    }
}

// Epilogue of sgemm128_kernel<8, true, true, DEG, true> for lin_l = A @ B (N = g.C) of a degree l >= 1 without
// residual: stores gate_fwd_kernel's gout_l = g * (lin_l * s), g = cs_g sigmoid(pre0[l C + c]), to g.out instead of
// lin_l, bit for bit (the same lin_l values and the same operations). Atom-aligned tiles as gate_bwd_epilogue; the
// tile's gates (one sigmoid per atom and column, as gate_fwd_kernel) and s go through shared memory first.
template <int DEG>
__device__ __forceinline__ void gate_fwd_epilogue(const float (&acc)[8][8], float* smem, int a0, int n0,
                                                  const GateArgs& g) {
    static_assert(DEG > 1, "gate_fwd_epilogue: degrees l >= 1");
    constexpr int APT = 128 / DEG, l = DEG / 2;
    const int N = g.C;
    const int tid = threadIdx.x, tx = tid & 15, ty = tid >> 4;
    float* sG = smem;              // [APT][128]: gates of the tile's atoms and columns
    float* sS = smem + APT * 128;  // [APT]: s of the tile's atoms
    const int na = min(APT, g.natoms - a0);
    __syncthreads();  // every warp is done with the pipeline buffers
    for (int e = tid; e < na * 128; e += 256) {
        const int ai = e >> 7, c = n0 + (e & 127), a = a0 + ai;
        const float s = 1.0f / (g.D[a] * g.beta + g.alpha);
        const int64_t r0 = (int64_t)a * 4 * N, q0 = g.res0_sp ? (int64_t)g.res0_sp[a] * 4 * N : r0;
        const float pre = g.lin0[r0 + l * N + c] * s + (g.res0 ? g.res0[q0 + l * N + c] : 0.0f);
        sG[e] = g.cg * sigmoid_f(pre);
        if ((e & 127) == 0) sS[ai] = s;
    }
    __syncthreads();
#pragma unroll
    for (int i = 0; i < 8; ++i) {
        const int rl = (i < 4 ? 0 : 60) + ty * 4 + i, ai = rl / DEG;
        if (ai >= na) continue;  // also every row past the tile's whole atoms (ai >= APT)
        const float s = sS[ai];
        float* o = g.out + ((int64_t)a0 * DEG + rl) * N + n0;
#pragma unroll
        for (int hh = 0; hh < 2; ++hh) {
            const int n = hh * 64 + tx * 4;
            const float4 gt = *reinterpret_cast<const float4*>(sG + ai * 128 + n);
            *reinterpret_cast<float4*>(o + n) =
                make_float4(gt.x * (acc[i][4 * hh] * s), gt.y * (acc[i][4 * hh + 1] * s),
                            gt.z * (acc[i][4 * hh + 2] * s), gt.w * (acc[i][4 * hh + 3] * s));
        }
    }
}

// TN: 8 (128 x 128 tiles) or 4 (128 x 64 tiles, for N = 192 without padding). FULL_N: N % (16 TN) == 0, no
// column guards. GATE_DEG 0: the plain store of C (g unused); 1 / 3 / 5 / 7 (with TN 8, FULL_N, N_FASTEST): row tiles
// of 128 / GATE_DEG whole atoms and gate_bwd_epilogue<GATE_DEG> (gate_fwd_epilogue with GATE_FWD) instead of the store
// (C, beta unused).
template <int TN, bool FULL_N, bool N_FASTEST, int GATE_DEG = 0, bool GATE_FWD = false>
__global__ void __launch_bounds__(256, 2) sgemm128_kernel(int M, int N, int K, const float* __restrict__ A,
                                                          const float* __restrict__ B, float* __restrict__ C,
                                                          float beta, GateArgs g) {
    extern __shared__ __align__(16) float smem[];
    float(*As)[128][kBK] = reinterpret_cast<float(*)[128][kBK]>(smem);
    constexpr int BN = 16 * TN;
    float(*Bs)[kBK][BN] = reinterpret_cast<float(*)[kBK][BN]>(smem + kStages * 128 * kBK);
    const int tid = threadIdx.x, tx = tid & 15, ty = tid >> 4;
    // N_FASTEST (sm_120 only): the N tiles of one A row block run together, so a cold A streams from DRAM once.
    // Otherwise the original M-tile-fastest order: other GPUs run the kernel they were tuned with.
    constexpr int MT = GATE_DEG ? 128 / GATE_DEG * GATE_DEG : 128;
    const int m0 = (N_FASTEST ? blockIdx.y : blockIdx.x) * MT, n0 = (N_FASTEST ? blockIdx.x : blockIdx.y) * BN;
    // Copy roles: A rows ar and ar + 64 (one 16-byte k chunk each); B rows bk (and bk + 8 for BN = 128), one 16-byte
    // n chunk each.
    const int ar = tid >> 2, ac = (tid & 3) * 4;
    const int bk = TN == 8 ? tid >> 5 : tid >> 4, bc = TN == 8 ? (tid & 31) * 4 : (tid & 15) * 4;
    const bool a_ok0 = m0 + ar < M, a_ok1 = m0 + ar + 64 < M;
    const bool b_ok = FULL_N || n0 + bc < N;
    const float* a0 = A + (size_t)(a_ok0 ? m0 + ar : 0) * K + ac;
    const float* a1 = A + (size_t)(a_ok1 ? m0 + ar + 64 : 0) * K + ac;
    const float* b0 = B + (size_t)bk * N + (b_ok ? n0 + bc : 0);
    const int nk = K / kBK;
    auto issue = [&](int kt) {
        const int st = kt % kStages;
        cp_async16(&As[st][ar][ac], a0 + kt * kBK, a_ok0);
        cp_async16(&As[st][ar + 64][ac], a1 + kt * kBK, a_ok1);
        cp_async16(&Bs[st][bk][bc], b0 + (size_t)kt * kBK * N, b_ok);
        if (TN == 8) cp_async16(&Bs[st][bk + 8][bc], b0 + (size_t)(kt * kBK + 8) * N, b_ok);
    };
#pragma unroll
    for (int st = 0; st < kStages - 1; ++st) {
        if (st < nk) {
            issue(st);
            cp_async_commit();
        }
    }
    float acc[8][TN];
#pragma unroll
    for (int i = 0; i < 8; ++i)
#pragma unroll
        for (int j = 0; j < TN; ++j) acc[i][j] = 0.0f;
    for (int kt = 0; kt < nk; ++kt) {
        if (kt + 1 == nk) asm volatile("cp.async.wait_group 0;");
        else cp_async_wait_one_pending();
        __syncthreads();  // stage kt landed for every thread; stage kt - 1 is free for reuse
        if (kt + kStages - 1 < nk) {
            issue(kt + kStages - 1);
            cp_async_commit();
        }
        const int st = kt % kStages;
#pragma unroll
        for (int kk = 0; kk < kBK; kk += 4) {
            float4 af[8];
#pragma unroll
            for (int i = 0; i < 8; ++i) af[i] = *reinterpret_cast<const float4*>(&As[st][(i < 4 ? 0 : 60) + ty * 4 + i][kk]);
#pragma unroll
            for (int q = 0; q < 4; ++q) {
                float bv[TN];
                const float4 bl = *reinterpret_cast<const float4*>(&Bs[st][kk + q][tx * 4]);
                bv[0] = bl.x; bv[1] = bl.y; bv[2] = bl.z; bv[3] = bl.w;
                if (TN == 8) {
                    const float4 bh = *reinterpret_cast<const float4*>(&Bs[st][kk + q][(TN == 8 ? 64 : 0) + tx * 4]);
                    bv[TN - 4] = bh.x; bv[TN - 3] = bh.y; bv[TN - 2] = bh.z; bv[TN - 1] = bh.w;
                }
#pragma unroll
                for (int i = 0; i < 8; ++i) {
                    const float a = q == 0 ? af[i].x : q == 1 ? af[i].y : q == 2 ? af[i].z : af[i].w;
#pragma unroll
                    for (int j = 0; j < TN; ++j) acc[i][j] = fmaf(a, bv[j], acc[i][j]);
                }
            }
        }
    }
    if constexpr (GATE_DEG != 0) {
        static_assert(TN == 8 && FULL_N, "gate epilogue: 128 x 128 tiles, N % 128 == 0");
        if constexpr (GATE_FWD) gate_fwd_epilogue<GATE_DEG>(acc, smem, m0 / GATE_DEG, n0, g);
        else gate_bwd_epilogue<GATE_DEG>(acc, smem, m0 / GATE_DEG, n0, g);
    } else {
#pragma unroll
        for (int i = 0; i < 8; ++i) {
            const int r = m0 + (i < 4 ? 0 : 60) + ty * 4 + i;
            if (r >= M) continue;
#pragma unroll
            for (int hh = 0; hh < TN / 4; ++hh) {
                const int n = n0 + hh * 64 + tx * 4;
                if (!FULL_N && n >= N) continue;
                float* cp = C + (size_t)r * N + n;
                float4 v = make_float4(acc[i][4 * hh], acc[i][4 * hh + 1], acc[i][4 * hh + 2], acc[i][4 * hh + 3]);
                if (beta != 0.0f) {
                    const float4 o = *reinterpret_cast<const float4*>(cp);
                    v.x = fmaf(beta, o.x, v.x);
                    v.y = fmaf(beta, o.y, v.y);
                    v.z = fmaf(beta, o.z, v.z);
                    v.w = fmaf(beta, o.w, v.w);
                }
                *reinterpret_cast<float4*>(cp) = v;
            }
        }
    }
}

// 128 x 96 tiles (8 x 6 outputs per thread) for N == 96 (the C = 96 models), where
// sgemm128_kernel<8> spends a quarter of its FMAs on padding columns. sm_120 only (launched with N tiles fastest, as
// sgemm128_kernel<.., true>); same in-order fmaf chain per output, so results are bit-identical. 43 KB shared memory.
__global__ void __launch_bounds__(256, 2) sgemm96_kernel(int M, int N, int K, const float* __restrict__ A,
                                                         const float* __restrict__ B, float* __restrict__ C,
                                                         float beta) {
    constexpr int BN = 96;
    extern __shared__ __align__(16) float smem[];
    float(*As)[128][kBK] = reinterpret_cast<float(*)[128][kBK]>(smem);
    float(*Bs)[kBK][BN] = reinterpret_cast<float(*)[kBK][BN]>(smem + kStages * 128 * kBK);
    const int tid = threadIdx.x, tx = tid & 15, ty = tid >> 4;
    const int m0 = blockIdx.y * 128, n0 = blockIdx.x * BN;
    // Copy roles: A as in sgemm128_kernel; B's 16 x 96 tile is 384 16-byte chunks, two for the first 128 threads.
    const int ar = tid >> 2, ac = (tid & 3) * 4;
    const int bk0 = tid / 24, bc0 = (tid % 24) * 4;
    const int i1 = tid + 256, bk1 = i1 / 24, bc1 = (i1 % 24) * 4;
    const bool b1 = i1 < kBK * BN / 4;
    const bool a_ok0 = m0 + ar < M, a_ok1 = m0 + ar + 64 < M;
    const float* a0 = A + (size_t)(a_ok0 ? m0 + ar : 0) * K + ac;
    const float* a1 = A + (size_t)(a_ok1 ? m0 + ar + 64 : 0) * K + ac;
    const float* bp0 = B + (size_t)bk0 * N + n0 + bc0;
    const float* bp1 = B + (size_t)(b1 ? bk1 : 0) * N + n0 + (b1 ? bc1 : 0);
    const int nk = K / kBK;
    auto issue = [&](int kt) {
        const int st = kt % kStages;
        cp_async16(&As[st][ar][ac], a0 + kt * kBK, a_ok0);
        cp_async16(&As[st][ar + 64][ac], a1 + kt * kBK, a_ok1);
        cp_async16(&Bs[st][bk0][bc0], bp0 + (size_t)kt * kBK * N, true);
        if (b1) cp_async16(&Bs[st][bk1][bc1], bp1 + (size_t)kt * kBK * N, true);
    };
#pragma unroll
    for (int st = 0; st < kStages - 1; ++st) {
        if (st < nk) {
            issue(st);
            cp_async_commit();
        }
    }
    float acc[8][6];
#pragma unroll
    for (int i = 0; i < 8; ++i)
#pragma unroll
        for (int j = 0; j < 6; ++j) acc[i][j] = 0.0f;
    for (int kt = 0; kt < nk; ++kt) {
        if (kt + 1 == nk) asm volatile("cp.async.wait_group 0;");
        else cp_async_wait_one_pending();
        __syncthreads();
        if (kt + kStages - 1 < nk) {
            issue(kt + kStages - 1);
            cp_async_commit();
        }
        const int st = kt % kStages;
#pragma unroll
        for (int kk = 0; kk < kBK; kk += 4) {
            float4 af[8];
#pragma unroll
            for (int i = 0; i < 8; ++i) af[i] = *reinterpret_cast<const float4*>(&As[st][(i < 4 ? 0 : 60) + ty * 4 + i][kk]);
#pragma unroll
            for (int q = 0; q < 4; ++q) {
                const float4 bl = *reinterpret_cast<const float4*>(&Bs[st][kk + q][tx * 4]);
                const float2 bh = *reinterpret_cast<const float2*>(&Bs[st][kk + q][64 + tx * 2]);
                const float bv[6] = {bl.x, bl.y, bl.z, bl.w, bh.x, bh.y};
#pragma unroll
                for (int i = 0; i < 8; ++i) {
                    const float a = q == 0 ? af[i].x : q == 1 ? af[i].y : q == 2 ? af[i].z : af[i].w;
#pragma unroll
                    for (int j = 0; j < 6; ++j) acc[i][j] = fmaf(a, bv[j], acc[i][j]);
                }
            }
        }
    }
#pragma unroll
    for (int i = 0; i < 8; ++i) {
        const int r = m0 + (i < 4 ? 0 : 60) + ty * 4 + i;
        if (r >= M) continue;
        float* cp = C + (size_t)r * N + n0;
        float4 v = make_float4(acc[i][0], acc[i][1], acc[i][2], acc[i][3]);
        float2 w = make_float2(acc[i][4], acc[i][5]);
        if (beta != 0.0f) {
            const float4 o = *reinterpret_cast<const float4*>(cp + tx * 4);
            const float2 p = *reinterpret_cast<const float2*>(cp + 64 + tx * 2);
            v.x = fmaf(beta, o.x, v.x);
            v.y = fmaf(beta, o.y, v.y);
            v.z = fmaf(beta, o.z, v.z);
            v.w = fmaf(beta, o.w, v.w);
            w.x = fmaf(beta, p.x, w.x);
            w.y = fmaf(beta, p.y, w.y);
        }
        *reinterpret_cast<float4*>(cp + tx * 4) = v;
        *reinterpret_cast<float2*>(cp + 64 + tx * 2) = w;
    }
}

__global__ void transpose_kernel(int R, int Ccols, const float* __restrict__ in, float* __restrict__ out) {
    const int c = blockIdx.x * blockDim.x + threadIdx.x, r = blockIdx.y;
    if (c < Ccols) out[(size_t)c * R + r] = in[(size_t)r * Ccols + c];
}


// 64 x 64 x 16 block tile, 128 threads with 8 x 4 outputs each, 3-stage cp.async pipeline (24 KB shared memory).
template <bool FULL_N>
__global__ void __launch_bounds__(128, 4) sgemm64_kernel(int M, int N, int K, const float* __restrict__ A,
                                                         const float* __restrict__ B, float* __restrict__ C,
                                                         float beta) {
    __shared__ __align__(16) float As[kStages][64][kBK];
    __shared__ __align__(16) float Bs[kStages][kBK][64];
    const int tid = threadIdx.x, tx = tid & 15, ty = tid >> 4;
    const int m0 = blockIdx.y * 64, n0 = blockIdx.x * 64;
    const int ar = tid >> 2, ac = (tid & 3) * 4;
    const int bk = tid >> 4, bc = (tid & 15) * 4;
    const bool a_ok0 = m0 + ar < M, a_ok1 = m0 + ar + 32 < M;
    const bool b_ok = FULL_N || n0 + bc < N;
    const float* a0 = A + (size_t)(a_ok0 ? m0 + ar : 0) * K + ac;
    const float* a1 = A + (size_t)(a_ok1 ? m0 + ar + 32 : 0) * K + ac;
    const float* b0 = B + (size_t)bk * N + (b_ok ? n0 + bc : 0);
    const int nk = K / kBK;
    auto issue = [&](int kt) {
        const int st = kt % kStages;
        cp_async16(&As[st][ar][ac], a0 + kt * kBK, a_ok0);
        cp_async16(&As[st][ar + 32][ac], a1 + kt * kBK, a_ok1);
        cp_async16(&Bs[st][bk][bc], b0 + (size_t)kt * kBK * N, b_ok);
        cp_async16(&Bs[st][bk + 8][bc], b0 + (size_t)(kt * kBK + 8) * N, b_ok);
    };
#pragma unroll
    for (int st = 0; st < kStages - 1; ++st) {
        if (st < nk) {
            issue(st);
            cp_async_commit();
        }
    }
    float acc[8][4];
#pragma unroll
    for (int i = 0; i < 8; ++i)
#pragma unroll
        for (int j = 0; j < 4; ++j) acc[i][j] = 0.0f;
    for (int kt = 0; kt < nk; ++kt) {
        if (kt + 1 == nk) asm volatile("cp.async.wait_group 0;");
        else cp_async_wait_one_pending();
        __syncthreads();
        if (kt + kStages - 1 < nk) {
            issue(kt + kStages - 1);
            cp_async_commit();
        }
        const int st = kt % kStages;
#pragma unroll
        for (int kk = 0; kk < kBK; kk += 4) {
            float4 af[8];
#pragma unroll
            for (int i = 0; i < 8; ++i) af[i] = *reinterpret_cast<const float4*>(&As[st][(i < 4 ? 0 : 28) + ty * 4 + i][kk]);
#pragma unroll
            for (int q = 0; q < 4; ++q) {
                const float4 bl = *reinterpret_cast<const float4*>(&Bs[st][kk + q][tx * 4]);
                const float bv[4] = {bl.x, bl.y, bl.z, bl.w};
#pragma unroll
                for (int i = 0; i < 8; ++i) {
                    const float a = q == 0 ? af[i].x : q == 1 ? af[i].y : q == 2 ? af[i].z : af[i].w;
#pragma unroll
                    for (int j = 0; j < 4; ++j) acc[i][j] = fmaf(a, bv[j], acc[i][j]);
                }
            }
        }
    }
#pragma unroll
    for (int i = 0; i < 8; ++i) {
        const int r = m0 + (i < 4 ? 0 : 28) + ty * 4 + i;
        if (r >= M) continue;
        const int n = n0 + tx * 4;
        if (!FULL_N && n >= N) continue;
        float* cp = C + (size_t)r * N + n;
        float4 v = make_float4(acc[i][0], acc[i][1], acc[i][2], acc[i][3]);
        if (beta != 0.0f) {
            const float4 o = *reinterpret_cast<const float4*>(cp);
            v.x = fmaf(beta, o.x, v.x);
            v.y = fmaf(beta, o.y, v.y);
            v.z = fmaf(beta, o.z, v.z);
            v.w = fmaf(beta, o.w, v.w);
        }
        *reinterpret_cast<float4*>(cp) = v;
    }
}

// 32 x 32 x 16 block tile, 64 threads with 4 x 4 outputs each, 3-stage cp.async pipeline (12 KB shared memory).
// Deterministic split-K (blockIdx.z in 0..split_k-1) writes partial slices into ws when split_k > 1.
template <bool FULL_N>
__global__ void __launch_bounds__(64) sgemm32_kernel(int M, int N, int K, const float* __restrict__ A,
                                                     const float* __restrict__ B, float* __restrict__ C,
                                                     float* __restrict__ ws, float beta, int split_k) {
    __shared__ __align__(16) float As[kStages][32][kBK];
    __shared__ __align__(16) float Bs[kStages][kBK][32];
    const int tid = threadIdx.x, tx = tid & 7, ty = tid >> 3;
    const int m0 = blockIdx.y * 32, n0 = blockIdx.x * 32;
    const int ar = tid >> 2, ac = (tid & 3) * 4;
    const int bk = tid >> 3, bc = (tid & 7) * 4;
    const bool a_ok0 = m0 + ar < M, a_ok1 = m0 + ar + 16 < M;
    const bool b_ok = FULL_N || n0 + bc < N;
    const int nk_tot = K / kBK, sk = blockIdx.z;
    const int k_per = (nk_tot + split_k - 1) / split_k;
    const int kb = sk * k_per, ke = min(nk_tot, kb + k_per), nk = ke - kb;
    if (nk <= 0) return;
    const float* a0 = A + (size_t)(a_ok0 ? m0 + ar : 0) * K + kb * kBK + ac;
    const float* a1 = A + (size_t)(a_ok1 ? m0 + ar + 16 : 0) * K + kb * kBK + ac;
    const float* b0 = B + (size_t)(kb * kBK + bk) * N + (b_ok ? n0 + bc : 0);
    auto issue = [&](int kt) {
        const int st = kt % kStages;
        cp_async16(&As[st][ar][ac], a0 + kt * kBK, a_ok0);
        cp_async16(&As[st][ar + 16][ac], a1 + kt * kBK, a_ok1);
        cp_async16(&Bs[st][bk][bc], b0 + (size_t)kt * kBK * N, b_ok);
        cp_async16(&Bs[st][bk + 8][bc], b0 + (size_t)(kt * kBK + 8) * N, b_ok);
    };
#pragma unroll
    for (int st = 0; st < kStages - 1; ++st) {
        if (st < nk) {
            issue(st);
            cp_async_commit();
        }
    }
    float acc[4][4];
#pragma unroll
    for (int i = 0; i < 4; ++i)
#pragma unroll
        for (int j = 0; j < 4; ++j) acc[i][j] = 0.0f;
    for (int kt = 0; kt < nk; ++kt) {
        if (kt + 1 == nk) asm volatile("cp.async.wait_group 0;");
        else cp_async_wait_one_pending();
        __syncthreads();
        if (kt + kStages - 1 < nk) {
            issue(kt + kStages - 1);
            cp_async_commit();
        }
        const int st = kt % kStages;
#pragma unroll
        for (int kk = 0; kk < kBK; kk += 4) {
            float4 af[4];
#pragma unroll
            for (int i = 0; i < 4; ++i) af[i] = *reinterpret_cast<const float4*>(&As[st][ty * 4 + i][kk]);
#pragma unroll
            for (int q = 0; q < 4; ++q) {
                const float4 bl = *reinterpret_cast<const float4*>(&Bs[st][kk + q][tx * 4]);
                const float bv[4] = {bl.x, bl.y, bl.z, bl.w};
#pragma unroll
                for (int i = 0; i < 4; ++i) {
                    const float a = q == 0 ? af[i].x : q == 1 ? af[i].y : q == 2 ? af[i].z : af[i].w;
#pragma unroll
                    for (int j = 0; j < 4; ++j) acc[i][j] = fmaf(a, bv[j], acc[i][j]);
                }
            }
        }
    }
    float* dst = (split_k > 1) ? (ws + (size_t)sk * M * N) : C;
    const float b_eff = (split_k > 1) ? 0.0f : beta;
#pragma unroll
    for (int i = 0; i < 4; ++i) {
        const int r = m0 + ty * 4 + i;
        if (r >= M) continue;
        const int n = n0 + tx * 4;
        if (!FULL_N && n >= N) continue;
        float* cp = dst + (size_t)r * N + n;
        float4 v = make_float4(acc[i][0], acc[i][1], acc[i][2], acc[i][3]);
        if (b_eff != 0.0f) {
            const float4 o = *reinterpret_cast<const float4*>(cp);
            v.x = fmaf(b_eff, o.x, v.x);
            v.y = fmaf(b_eff, o.y, v.y);
            v.z = fmaf(b_eff, o.z, v.z);
            v.w = fmaf(b_eff, o.w, v.w);
        }
        *reinterpret_cast<float4*>(cp) = v;
    }
}

__global__ void splitk_reduce_kernel(int mn4, int split_k, const float4* __restrict__ ws, float4* __restrict__ C,
                                     float beta) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= mn4) return;
    float4 sum = make_float4(0.0f, 0.0f, 0.0f, 0.0f);
    for (int s = 0; s < split_k; ++s) {
        const float4 v = ws[(size_t)s * mn4 + i];
        sum.x += v.x;
        sum.y += v.y;
        sum.z += v.z;
        sum.w += v.w;
    }
    if (beta != 0.0f) {
        const float4 o = C[i];
        sum.x = fmaf(beta, o.x, sum.x);
        sum.y = fmaf(beta, o.y, sum.y);
        sum.z = fmaf(beta, o.z, sum.z);
        sum.w = fmaf(beta, o.w, sum.w);
    }
    C[i] = sum;
}

}  // namespace
// Prefer the maximum shared-memory carveout so two blocks (48 / 36 KB) fit per SM.
void sgemm128_init() {
    cudaFuncSetAttribute(sgemm128_kernel<8, true, false>, cudaFuncAttributePreferredSharedMemoryCarveout, 100);
    cudaFuncSetAttribute(sgemm128_kernel<8, false, false>, cudaFuncAttributePreferredSharedMemoryCarveout, 100);
    cudaFuncSetAttribute(sgemm128_kernel<4, true, false>, cudaFuncAttributePreferredSharedMemoryCarveout, 100);
    cudaFuncSetAttribute(sgemm128_kernel<4, false, false>, cudaFuncAttributePreferredSharedMemoryCarveout, 100);
    cudaFuncSetAttribute(sgemm128_kernel<8, true, true>, cudaFuncAttributePreferredSharedMemoryCarveout, 100);
    cudaFuncSetAttribute(sgemm128_kernel<8, false, true>, cudaFuncAttributePreferredSharedMemoryCarveout, 100);
    cudaFuncSetAttribute(sgemm128_kernel<4, true, true>, cudaFuncAttributePreferredSharedMemoryCarveout, 100);
    cudaFuncSetAttribute(sgemm128_kernel<4, false, true>, cudaFuncAttributePreferredSharedMemoryCarveout, 100);
    cudaFuncSetAttribute(sgemm64_kernel<true>, cudaFuncAttributePreferredSharedMemoryCarveout, 100);
    cudaFuncSetAttribute(sgemm64_kernel<false>, cudaFuncAttributePreferredSharedMemoryCarveout, 100);
    cudaFuncSetAttribute(sgemm32_kernel<true>, cudaFuncAttributePreferredSharedMemoryCarveout, 100);
    cudaFuncSetAttribute(sgemm32_kernel<false>, cudaFuncAttributePreferredSharedMemoryCarveout, 100);
    cudaFuncSetAttribute(sgemm96_kernel, cudaFuncAttributePreferredSharedMemoryCarveout, 100);
    cudaFuncSetAttribute(sgemm128_kernel<8, true, true, 1>, cudaFuncAttributePreferredSharedMemoryCarveout, 100);
    cudaFuncSetAttribute(sgemm128_kernel<8, true, true, 3>, cudaFuncAttributePreferredSharedMemoryCarveout, 100);
    cudaFuncSetAttribute(sgemm128_kernel<8, true, true, 5>, cudaFuncAttributePreferredSharedMemoryCarveout, 100);
    cudaFuncSetAttribute(sgemm128_kernel<8, true, true, 7>, cudaFuncAttributePreferredSharedMemoryCarveout, 100);
    cudaFuncSetAttribute(sgemm128_kernel<8, true, true, 3, true>, cudaFuncAttributePreferredSharedMemoryCarveout, 100);
    cudaFuncSetAttribute(sgemm128_kernel<8, true, true, 5, true>, cudaFuncAttributePreferredSharedMemoryCarveout, 100);
    cudaFuncSetAttribute(sgemm128_kernel<8, true, true, 7, true>, cudaFuncAttributePreferredSharedMemoryCarveout, 100);
}

namespace {
template <bool NF>
void sgemm128_launch(int M, int N, int K, const float* A, const float* B, float* C, float beta, cudaStream_t stream) {
    auto grid_of = [&](int bn) {
        const unsigned mt = (M + 127) / 128, nt = (N + bn - 1) / bn;
        return NF ? dim3(nt, mt) : dim3(mt, nt);
    };
    const GateArgs g{};  // unused by the plain store
    if (NF && N == 96) {  // sm_120: 128 x 96 tiles instead of a padded 128 x 128 one (only N = 96 was measured)
        constexpr int smem96 = kStages * (128 * kBK + kBK * 96) * (int)sizeof(float);
        sgemm96_kernel<<<dim3(N / 96, (M + 127) / 128), 256, smem96, stream>>>(M, N, K, A, B, C, beta);
        return;
    }
    if ((N % 128) != 0 && (N % 128) <= 64) {  // e.g. N = 144, 192: 128 x 64 tiles instead of a mostly-empty 128 x 128 tile
        const dim3 grid = grid_of(64);
        if ((N % 64) == 0) sgemm128_kernel<4, true, NF><<<grid, 256, smem_bytes<64>(), stream>>>(M, N, K, A, B, C, beta, g);
        else               sgemm128_kernel<4, false, NF><<<grid, 256, smem_bytes<64>(), stream>>>(M, N, K, A, B, C, beta, g);
        return;
    }
    const dim3 grid = grid_of(128);
    if ((N % 128) == 0) sgemm128_kernel<8, true, NF><<<grid, 256, smem_bytes<128>(), stream>>>(M, N, K, A, B, C, beta, g);
    else                sgemm128_kernel<8, false, NF><<<grid, 256, smem_bytes<128>(), stream>>>(M, N, K, A, B, C, beta, g);
}
}  // namespace

// Requirements (checked by the caller): K % 16 == 0, N % 4 == 0, lda = K, ldb = ldc = N, A / B / C 16-byte aligned.
void sgemm128(int M, int N, int K, const float* A, const float* B, float* C, float beta, bool n_fastest,
              cudaStream_t stream) {
    if (n_fastest) sgemm128_launch<true>(M, N, K, A, B, C, beta, stream);
    else           sgemm128_launch<false>(M, N, K, A, B, C, beta, stream);
}

// The gate-fused sgemm128 (N tiles fastest, row tiles of whole atoms). Backward (fwd false, l in 0..3): dgout_l =
// A[M, K] @ B[K, N] with degree l's gate backward (gate_bwd_epilogue); forward (fwd true, l in 1..3): lin_l = A @ B
// stored as gout_l (gate_fwd_epilogue). Requirements (checked by the caller): M = g.natoms (2l + 1), N = g.C,
// N % 128 == 0, K % 16 == 0, lda = K, ldb = N, A / B 16-byte aligned.
void sgemm128_gate(bool fwd, int l, int M, int N, int K, const float* A, const float* B, const GateArgs& g,
                   cudaStream_t stream) {
    const int apt = 128 / (2 * l + 1);
    const dim3 grid(N / 128, (g.natoms + apt - 1) / apt);
    auto kern = fwd ? (l == 1 ? sgemm128_kernel<8, true, true, 3, true>
                     : l == 2 ? sgemm128_kernel<8, true, true, 5, true>
                              : sgemm128_kernel<8, true, true, 7, true>)
                    : (l == 0 ? sgemm128_kernel<8, true, true, 1>
                     : l == 1 ? sgemm128_kernel<8, true, true, 3>
                     : l == 2 ? sgemm128_kernel<8, true, true, 5>
                              : sgemm128_kernel<8, true, true, 7>);
    kern<<<grid, 256, smem_bytes<128>(), stream>>>(M, N, K, A, B, nullptr, 0.0f, g);
}

void sgemm64(int M, int N, int K, const float* A, const float* B, float* C, float beta, cudaStream_t stream) {
    const dim3 grid((N + 63) / 64, (M + 63) / 64);
    if ((N % 64) == 0) sgemm64_kernel<true><<<grid, 128, 0, stream>>>(M, N, K, A, B, C, beta);
    else               sgemm64_kernel<false><<<grid, 128, 0, stream>>>(M, N, K, A, B, C, beta);
}

void sgemm32(int M, int N, int K, const float* A, const float* B, float* C, float* ws, float beta, int split_k,
             cudaStream_t stream) {
    if (M <= 0 || N <= 0 || K <= 0) return;
    const dim3 grid((N + 31) / 32, (M + 31) / 32, split_k);
    if ((N % 32) == 0) sgemm32_kernel<true><<<grid, 64, 0, stream>>>(M, N, K, A, B, C, ws, beta, split_k);
    else               sgemm32_kernel<false><<<grid, 64, 0, stream>>>(M, N, K, A, B, C, ws, beta, split_k);
    if (split_k > 1) {
        const int mn4 = (int)(((size_t)M * N) >> 2);
        if (mn4 > 0)
            splitk_reduce_kernel<<<(mn4 + 255) / 256, 256, 0, stream>>>(
                mn4, split_k, reinterpret_cast<const float4*>(ws), reinterpret_cast<float4*>(C), beta);
    }
}
// out[C, R] = in[R, C]^T (row-major).
void transpose(int R, int Ccols, const float* in, float* out, cudaStream_t stream) {
    transpose_kernel<<<dim3((Ccols + 127) / 128, R), 128, 0, stream>>>(R, Ccols, in, out);
}

}  // namespace loup
