#pragma once
// Layer 0's edge kernels (first_fwd_kernel, first_bwd_edge_kernel) and the ZBL pair term. Compiled twice: ahead of
// time by nvcc (generic.cu includes this header) and at run time by NVRTC (src/jit.cu embeds it, JIT_DESIGN.md), where
// a prelude defines LOUP_JIT_L0 and the LOUP_JIT_L0_* constants of one model's layer 0 (kernel_ir.hpp) and the
// arguments they replace are ignored. One source for both; the arithmetic and its order are the same.
#include "kernels_common.cuh"
#include "generated_sh16.cuh"

// A layer-0 constant: the kernel argument (ahead of time), or the JIT prelude's compile-time value; the spline lookup:
// locate_spline on the argument grid, or the prelude's loup_jit_l0_locate with the grid's numbers as literals.
#ifdef LOUP_JIT_L0
#define LOUP_L0_INT(name, arg) constexpr int name = LOUP_JIT_L0_##name; (void)arg
#else
#define LOUP_L0_INT(name, arg) const int name = arg
#endif
#ifdef LOUP_JIT_L0_GRID
#define LOUP_L0_LOCATE(g, r, iv, t, sxi) loup_jit_l0_locate(r, iv, t, sxi)
#else
#define LOUP_L0_LOCATE(g, r, iv, t, sxi) locate_spline(g, r, iv, t, sxi)
#endif
#define LOUP_L0_INTS                                                                                                    \
    LOUP_L0_INT(S, S_a);                                                                                                \
    LOUP_L0_INT(I, I_a);                                                                                                \
    LOUP_L0_INT(Jt, Jt_a);                                                                                              \
    LOUP_L0_INT(K0, K0_a);                                                                                              \
    LOUP_L0_INT(sh_perm, sh_perm_a);                                                                                    \
    LOUP_L0_INT(pair_sym, pair_sym_a)

// ZBL per edge (ordered pair tables), float32 as in MACE's float32 model (the gate's yardstick; FP64 runs at 1/64
// rate on GeForce parts). Callers skip edges beyond the largest ZBL cutoff (ZblParams::r_max, 0 without ZBL)
// before reading the tables. Returns false outside the pair's cutoff; otherwise en = the pair energy, dE/dvec = g vec.
struct ZblParams {
    const float *rc = nullptr, *inv_a = nullptr, *pref = nullptr;
    float c0 = 0, c1 = 0, c2 = 0, c3 = 0, p = 5.0f, r_max = 0.0f;
};
__device__ __forceinline__ bool zbl_pair(const ZblParams& z, int p, float r, float& en, float& g) {
    const float rc = z.rc[p];
    if (!(r > 0.0f && r < rc)) return false;
    const float inv_a = z.inv_a[p], pref = z.pref[p], zp = z.p;
    const float u = r * inv_a;
    const float e0 = expf(-3.2f * u), e1 = expf(-0.9423f * u), e2 = expf(-0.4028f * u), e3 = expf(-0.2016f * u);
    const float phi = z.c0 * e0 + z.c1 * e1 + z.c2 * e2 + z.c3 * e3;
    const float dphi = -inv_a * (3.2f * z.c0 * e0 + 0.9423f * z.c1 * e1 + 0.4028f * z.c2 * e2 + 0.2016f * z.c3 * e3);
    const float inv_r = 1.0f / r;
    const float vz = pref * inv_r * phi;
    const float dv = pref * inv_r * (dphi - phi * inv_r);
    const float sr = r / rc;
    const float s2 = sr * sr;
    const float sp = zp == 5.0f ? s2 * s2 * sr : powf(sr, zp);
    const float env = 1.0f - ((zp + 1.0f) * (zp + 2.0f) * 0.5f) * sp + (zp * (zp + 2.0f)) * sp * sr -
                      (zp * (zp + 1.0f) * 0.5f) * sp * sr * sr;
    const float denv = -(zp * (zp + 1.0f) * (zp + 2.0f) * 0.5f) * (sp / sr) * (1.0f - sr) * (1.0f - sr) / rc;
    en = vz * env;
    g = (dv * env + vz * denv) * inv_r;
    return true;
}

// S131: layer 0's table rows hold the J - 1 radial columns even ones first, then the odd ones (column j at
// first_col_pos(j, Jh), Jh = ceil((J - 1) / 2)), then the density column if kept: first_bwd_edge_kernel's lanes read
// columns 2 lane and 2 lane + 1, now one contiguous 512 B run per load (16 sectors) instead of two loads that each
// touch the same 32 sectors; first_fwd / first_bwd still read two contiguous runs per warp.
__device__ __forceinline__ int first_col_pos(int j, int Jh) { return (j & 1) ? Jh + (j >> 1) : (j >> 1); }

// Layer 0 (input = species embedding): S0_l[a][m][s (J-1) + j] = sum over the active edges of receiver a whose sender
// has species s of col_j(r) Y_lm, with col the radial chain's columns [h c, c] (j < J - 1); column J - 1 is the edge
// density, summed into D. One block per receiver, one thread per column j < J - 1 (S105: the density column is summed
// by warp 0, one lane per staged edge, instead of by a warp of its own); a receiver's edges are grouped by ascending
// sender species (the neighbour list's contract), so each species slot is written once (zeros if it has no edge).
// S128: Jt = the table's row stride in float4: J, or J - 1 when the layer reads no density (agnostic kinds: the
// column is dropped at load, rows of 1,024 B at 64 columns), and then neither D nor the density sum is formed.
__global__ void __launch_bounds__(256) first_fwd_kernel(
    int N, int S_a, int I_a, int J_a, int Jt_a, int K0_a, SplineGrid grid, int sh_perm_a, int pair_sym_a,
    const int* __restrict__ row_ptr, const int* __restrict__ senders, const float4* __restrict__ vec_len,
    const int* __restrict__ species, const float4* __restrict__ table,
    float* __restrict__ s0, float* __restrict__ s1, float* __restrict__ s2, float* __restrict__ s3, float* __restrict__ D) {
    LOUP_L0_INTS;
    LOUP_L0_INT(J, J_a);
    // s_ee alternates by species parity: with no edge of species s there is no barrier between this iteration's read
    // and thread 0's write for s + 1, but the next barrier bounds thread 0's lead to one slot.
    __shared__ int s_iv[32], s_ee[2];
    __shared__ float s_t[32];
    __shared__ __align__(16) float s_sh[32 * 16];
    const int a = blockIdx.x, tid = threadIdx.x;
    if (a >= N) return;
    const int Jp = J - 1, Jh = (Jp + 1) >> 1, K = S * Jp, sa = species[a];
    const int e_end = row_ptr[a + 1];
    int e_cur = row_ptr[a];
    float dsum = 0.0f;  // S105: warp 0 sums the density column in edge order (the order of the former density thread)
    for (int s = 0; s < S; ++s) {
        if (tid < 32) {
            int p = e_cur;
            while (p < e_end) {
                const int idx = p + tid;
                const bool ok = (idx < e_end) && (species[senders[idx]] == s);
                const unsigned mask = __ballot_sync(0xffffffffu, ok);
                if (mask != 0xffffffffu) { p += __ffs(~mask) - 1; break; }
                p += 32;
            }
            if (p > e_end) p = e_end;
            if (tid == 0) s_ee[s & 1] = p;
        }
        __syncthreads();
        const int e_s_end = s_ee[s & 1];
        float acc[16];
        #pragma unroll
        for (int m = 0; m < 16; ++m) acc[m] = 0.0f;
        const int pr = loup::table_pair(pair_sym, s, sa, S);
        for (int base = e_cur; base < e_s_end; base += 32) {
            const int cnt = (e_s_end - base < 32) ? (e_s_end - base) : 32;
            if (tid < cnt) {
                const float4 vl = __ldg(vec_len + base + tid);
                int iv; float t, sxi;
                LOUP_L0_LOCATE(grid, vl.w, iv, t, sxi);
                s_iv[tid] = iv;
                s_t[tid] = t;
            }
            if (tid >= 32 && tid - 32 < cnt) {
                const float4 vl = __ldg(vec_len + base + (tid - 32));
                if (sh_perm) loup::edge_sh16(vl.y, vl.z, vl.x, vl.w, reinterpret_cast<float4*>(s_sh + (tid - 32) * 16));
                else         loup::edge_sh16(vl.x, vl.y, vl.z, vl.w, reinterpret_cast<float4*>(s_sh + (tid - 32) * 16));
            }
            __syncthreads();
            float dv = 0.0f;
            if (Jt > Jp && tid < cnt) {
                const float4 dc = __ldg(table + ((int64_t)pr * I + s_iv[tid]) * Jt + Jp);
                const float t = s_t[tid];
                dv = fmaf(t, fmaf(t, fmaf(t, dc.w, dc.z), dc.y), dc.x);
            }
            if (tid < Jp) {
                for (int k = 0; k < cnt; ++k) {
                    const float4 cf = __ldg(table + ((int64_t)pr * I + s_iv[k]) * Jt + first_col_pos(tid, Jh));
                    const float t = s_t[k];
                    const float v = fmaf(t, fmaf(t, fmaf(t, cf.w, cf.z), cf.y), cf.x);
                    const float* sh = s_sh + k * 16;
                    #pragma unroll
                    for (int m = 0; m < 16; ++m) acc[m] = fmaf(v, sh[m], acc[m]);
                }
            }
            if (Jt > Jp && tid < 32)
                for (int k = 0; k < cnt; ++k) dsum += __shfl_sync(0xffffffffu, dv, k);
            __syncthreads();
        }
        if (tid < Jp) {
            s0[(int64_t)a * K0 + s * Jp + tid] = acc[0];
            #pragma unroll
            for (int m = 0; m < 3; ++m) s1[((int64_t)a * 3 + m) * K0 + s * Jp + tid] = acc[1 + m];
            #pragma unroll
            for (int m = 0; m < 5; ++m) s2[((int64_t)a * 5 + m) * K0 + s * Jp + tid] = acc[4 + m];
            #pragma unroll
            for (int m = 0; m < 7; ++m) s3[((int64_t)a * 7 + m) * K0 + s * Jp + tid] = acc[9 + m];
        }
        e_cur = e_s_end;
    }
    if (tid < K0 - K) {
        s0[(int64_t)a * K0 + K + tid] = 0.0f;
        #pragma unroll
        for (int m = 0; m < 3; ++m) s1[((int64_t)a * 3 + m) * K0 + K + tid] = 0.0f;
        #pragma unroll
        for (int m = 0; m < 5; ++m) s2[((int64_t)a * 5 + m) * K0 + K + tid] = 0.0f;
        #pragma unroll
        for (int m = 0; m < 7; ++m) s3[((int64_t)a * 7 + m) * K0 + K + tid] = 0.0f;
    }
    if (tid == 0 && Jt > Jp) D[a] = dsum;
}

// Edge-parallel layer-0 backward + ZBL + force/virial assembly (as the retired OMAT-0 path's):
// 4 warps x 32 edges/warp, COLS columns/lane (2 for Jp <= 64, 3 for Jp <= 96); caches dS0 across consecutive
// active edges with the same (rcv, snd_sp), folds SH gradients in s_edge[4][32][20], then all 32 lanes assemble
// forces, ZBL and virial in parallel. Bound by its load/store pipe (ncu, OMAT-0 generic SrTiO3: LSU 71% of peak, two
// thirds of it shuffles; FMA pipe 30%), hence S140's broadcast reads from shared memory and the radial pull riding in
// the fold. On sm_120, COLS = 2 is capped at 80 registers (6 blocks / SM, no spills; 92-96 registers uncapped).
// COLS = 3 would spill under the cap, and other architectures (not measured) keep the uncapped kernel.
// S142: J_FIX = 65 (64 radial columns, two per lane: OMAT-0 medium / small, ...) compiles the table width in, so the
// column predicates, the even-width test and first_col_pos fold away (1,984 -> 1,568 static instructions, same 80
// registers; OMAT-0 generic SrTiO3 424 -> 375 us per force call, 5060 Ti). J_FIX = 0 reads J at run time.
#if defined(__CUDA_ARCH__) && __CUDA_ARCH__ == 1200
#define LOUP_FIRST_BWD_EDGE_MINB2 6
#else
#define LOUP_FIRST_BWD_EDGE_MINB2 0
#endif
template <int COLS, bool HAS_ZBL, bool STRESS, int J_FIX = 0>
__global__ void __launch_bounds__(128, COLS == 2 ? LOUP_FIRST_BWD_EDGE_MINB2 : 0) first_bwd_edge_kernel(
    const int* __restrict__ E_dev, int S_a, int I_a, int J_arg, int Jt_a, int K0_a, SplineGrid grid, int sh_perm_a,
    int pair_sym_a,
    const int* __restrict__ senders, const int* __restrict__ receivers, const float4* __restrict__ vec_len,
    const int* __restrict__ species, const float4* __restrict__ table,
    const float* __restrict__ g0, const float* __restrict__ g1, const float* __restrict__ g2, const float* __restrict__ g3,
    const float* __restrict__ dD, const float* __restrict__ edge_dvec, ZblParams zbl,
    double* __restrict__ energy, double* __restrict__ forces, double* __restrict__ virial) {
    static_assert(J_FIX == 0 || (COLS == 2 && J_FIX == 65), "fixed width: 64 columns, two per lane");
    LOUP_L0_INTS;
#ifdef LOUP_JIT_L0
    constexpr int J = LOUP_JIT_L0_J;
    (void)J_arg;
#else
    const int J = J_FIX ? J_FIX : J_arg;
#endif
    constexpr int CHUNK = 32;
    const int E = *E_dev;
    const int tid = threadIdx.x, warp = tid >> 5, warp_id = blockIdx.x * 4 + warp, lane = tid & 31;
    const int start = warp_id * CHUNK;
    const int Jp = J - 1, Jh = (Jp + 1) >> 1;

    __shared__ __align__(16) float s_edge[4][CHUNK][20];
    // S140: each staged edge's receiver, sender species, slab (pr * I + iv) and t, read by the whole warp in the edge
    // loop as two broadcast shared loads instead of six shuffles
    __shared__ __align__(16) int4 s_meta[4][CHUNK];
    __shared__ float s_sxi[4][CHUNK];
    double v00 = 0.0, v01 = 0.0, v02 = 0.0, v11 = 0.0, v12 = 0.0, v22 = 0.0;
    double e_zbl_thread = 0.0;

    if (start < E) {
        const int stop = (start + CHUNK < E) ? (start + CHUNK) : E;
        const int cnt = stop - start;
        int m_iv = 0, m_pr = 0, m_rcv = -1, m_snd = -1, m_sp = -1, m_rcv_sp = -1;
        float m_t = 0.0f, m_sxi = 0.0f;
        if (lane < cnt) {
            const int e = start + lane;
            const float4 vl = __ldg(vec_len + e);
            const float ux = sh_perm ? vl.y : vl.x, uy = sh_perm ? vl.z : vl.y, uz = sh_perm ? vl.x : vl.z;
            loup::edge_sh16(ux, uy, uz, vl.w, reinterpret_cast<float4*>(s_edge[warp][lane]));
            LOUP_L0_LOCATE(grid, vl.w, m_iv, m_t, m_sxi);
            m_rcv = receivers[e];
            m_snd = senders[e];
            m_sp = species[m_snd];
            m_rcv_sp = species[m_rcv];
            m_pr = loup::table_pair(pair_sym, m_sp, m_rcv_sp, S);
            s_meta[warp][lane] = make_int4(m_rcv, m_sp, m_pr * I + m_iv, __float_as_int(m_t));
            s_sxi[warp][lane] = m_sxi;
        }
        __syncwarp();

        float blk[COLS][16];
        #pragma unroll
        for (int c = 0; c < COLS; ++c)
            #pragma unroll
            for (int d = 0; d < 16; ++d) blk[c][d] = 0.0f;
        float dD_r = 0.0f;
        int cur_rcv = -1, cur_snd_sp = -1;

        for (int k = 0; k < cnt; ++k) {
            const int4 mk = s_meta[warp][k];
            const int rcv = mk.x, snd_sp = mk.y;
            if (rcv != cur_rcv || snd_sp != cur_snd_sp) {
                cur_rcv = rcv;
                cur_snd_sp = snd_sp;
                if (COLS == 2 && (Jp & 1) == 0 && (K0 & 1) == 0) {
                    const int off = snd_sp * Jp + 2 * lane;
                    const bool ok = 2 * lane + 1 < Jp;
                    auto ld2 = [&](const float* base, int64_t row, int d) {
                        if (ok) {
                            const float2 v = __ldg(reinterpret_cast<const float2*>(base + row * K0 + off));
                            blk[0][d] = v.x;
                            blk[1][d] = v.y;
                        } else {
                            blk[0][d] = 2 * lane < Jp ? __ldg(base + row * K0 + off) : 0.0f;
                            blk[1][d] = 0.0f;
                        }
                    };
                    ld2(g0, rcv, 0);
                    #pragma unroll
                    for (int d = 0; d < 3; ++d) ld2(g1, (int64_t)rcv * 3 + d, 1 + d);
                    #pragma unroll
                    for (int d = 0; d < 5; ++d) ld2(g2, (int64_t)rcv * 5 + d, 4 + d);
                    #pragma unroll
                    for (int d = 0; d < 7; ++d) ld2(g3, (int64_t)rcv * 7 + d, 9 + d);
                } else {
                    #pragma unroll
                    for (int c = 0; c < COLS; ++c) {
                        const int col = (COLS == 2) ? (2 * lane + c) : (c * 32 + lane);
                        if (col < Jp) {
                            const int off = snd_sp * Jp + col;
                            blk[c][0] = __ldg(g0 + (int64_t)rcv * K0 + off);
                            #pragma unroll
                            for (int d = 0; d < 3; ++d) blk[c][1 + d] = __ldg(g1 + ((int64_t)rcv * 3 + d) * K0 + off);
                            #pragma unroll
                            for (int d = 0; d < 5; ++d) blk[c][4 + d] = __ldg(g2 + ((int64_t)rcv * 5 + d) * K0 + off);
                            #pragma unroll
                            for (int d = 0; d < 7; ++d) blk[c][9 + d] = __ldg(g3 + ((int64_t)rcv * 7 + d) * K0 + off);
                        }
                    }
                }
                if (dD) dD_r = __ldg(dD + rcv);
            }

            const float t = __int_as_float(mk.w);
            const float sxi = s_sxi[warp][k];
            const float4* tb = table + (int64_t)mk.z * Jt;
            float pa[COLS], pd[COLS];
            #pragma unroll
            for (int c = 0; c < COLS; ++c) {
                const int col = (COLS == 2) ? (2 * lane + c) : (c * 32 + lane);
                if (col < Jp) {
                    const float4 cf = __ldg(tb + first_col_pos(col, Jh));
                    pa[c] = fmaf(t, fmaf(t, fmaf(t, cf.w, cf.z), cf.y), cf.x);
                    pd[c] = fmaf(t, fmaf(t, 3.0f * cf.w, 2.0f * cf.z), cf.y) * sxi;
                } else {
                    pa[c] = 0.0f;
                    pd[c] = 0.0f;
                }
            }

            const float4* shv = reinterpret_cast<const float4*>(s_edge[warp][k]);
            const float4 Y0 = shv[0], Y1 = shv[1], Y2 = shv[2], Y3 = shv[3];
            const float shk[16] = {Y0.x, Y0.y, Y0.z, Y0.w, Y1.x, Y1.y, Y1.z, Y1.w,
                                   Y2.x, Y2.y, Y2.z, Y2.w, Y3.x, Y3.y, Y3.z, Y3.w};
            float grad_a[COLS];
            #pragma unroll
            for (int c = 0; c < COLS; ++c) grad_a[c] = 0.0f;
            float gy[16];
            #pragma unroll
            for (int d = 0; d < 16; ++d) {
                const float sd = shk[d];
                float gsum = 0.0f;
                #pragma unroll
                for (int c = 0; c < COLS; ++c) {
                    grad_a[c] = fmaf(blk[c][d], sd, grad_a[c]);
                    gsum = fmaf(blk[c][d], pa[c], gsum);
                }
                gy[d] = gsum;
            }
            // S140: slot 0 of the fold (the gradient of the constant Y0, never read) carries the radial pull, so the fold
            // also reduces it (lane 0 ends with its sum) and its separate five-shuffle butterfly is gone
            float dr_p = 0.0f;
            #pragma unroll
            for (int c = 0; c < COLS; ++c) dr_p = fmaf(grad_a[c], pd[c], dr_p);
            gy[0] = dr_p;

            // 16-shuffle fold of gy[0..15] across 32 lanes -> lane 1..15 holds dsh[lane], lane 0 the radial pull
            float g8[8];
            const bool odd = (lane & 1) != 0;
            #pragma unroll
            for (int q = 0; q < 8; ++q)
                g8[q] = (odd ? gy[2 * q + 1] : gy[2 * q]) + __shfl_xor_sync(0xffffffffu, odd ? gy[2 * q] : gy[2 * q + 1], 1);
            float g4[4];
            const bool h2 = (lane & 2) != 0;
            #pragma unroll
            for (int q = 0; q < 4; ++q)
                g4[q] = (h2 ? g8[2 * q + 1] : g8[2 * q]) + __shfl_xor_sync(0xffffffffu, h2 ? g8[2 * q] : g8[2 * q + 1], 2);
            float g2[2];
            const bool h4 = (lane & 4) != 0;
            #pragma unroll
            for (int q = 0; q < 2; ++q)
                g2[q] = (h4 ? g4[2 * q + 1] : g4[2 * q]) + __shfl_xor_sync(0xffffffffu, h4 ? g4[2 * q] : g4[2 * q + 1], 4);
            const bool h8 = (lane & 8) != 0;
            float g1 = (h8 ? g2[1] : g2[0]) + __shfl_xor_sync(0xffffffffu, h8 ? g2[0] : g2[1], 8);
            g1 += __shfl_xor_sync(0xffffffffu, g1, 16);
            if (lane >= 1 && lane < 16) s_edge[warp][k][lane] = g1;
            if (lane == 0) {
                float dr_v = g1;
                if (dD && dD_r != 0.0f) {
                    const float4 cd = __ldg(tb + Jp);
                    const float dvd = fmaf(t, fmaf(t, 3.0f * cd.w, 2.0f * cd.z), cd.y) * sxi;
                    dr_v = fmaf(dD_r, dvd, dr_v);
                }
                s_edge[warp][k][0] = dr_v;
            }
        }
        __syncwarp();

        if (lane < cnt) {
            const int e = start + lane;
            const float4 vl = __ldg(vec_len + e);
            const float dd = vl.w > loup::EPS_SH ? vl.w : loup::EPS_SH;
            const float inv_d = 1.0f / dd;
            const float ux = sh_perm ? vl.y : vl.x, uy = sh_perm ? vl.z : vl.y, uz = sh_perm ? vl.x : vl.z;
            const float x = ux * inv_d, y = uy * inv_d, z = uz * inv_d;
            float gx, gy, gz;
            ::sh16_grad(x, y, z, s_edge[warp][lane], gx, gy, gz);
            const float er = s_edge[warp][lane][0];
            const float dot = x * gx + y * gy + z * gz;
            float fx = x * er + (gx - x * dot) * inv_d;
            float fy = y * er + (gy - y * dot) * inv_d;
            float fz = z * er + (gz - z * dot) * inv_d;
            if (sh_perm) { const float tx = fx, ty = fy, tz = fz; fx = tz; fy = tx; fz = ty; }
            fx += edge_dvec[(int64_t)e * 3 + 0];
            fy += edge_dvec[(int64_t)e * 3 + 1];
            fz += edge_dvec[(int64_t)e * 3 + 2];
            if (HAS_ZBL && vl.w < zbl.r_max) {
                float zen, zg;
                if (zbl_pair(zbl, m_sp * S + m_rcv_sp, vl.w, zen, zg)) {
                    e_zbl_thread += zen;
                    fx += zg * vl.x;
                    fy += zg * vl.y;
                    fz += zg * vl.z;
                }
            }
            atomicAdd(forces + m_rcv * 3 + 0, -(double)fx);
            atomicAdd(forces + m_rcv * 3 + 1, -(double)fy);
            atomicAdd(forces + m_rcv * 3 + 2, -(double)fz);
            atomicAdd(forces + m_snd * 3 + 0, (double)fx);
            atomicAdd(forces + m_snd * 3 + 1, (double)fy);
            atomicAdd(forces + m_snd * 3 + 2, (double)fz);
            if (STRESS) {
                v00 = (double)vl.x * (double)fx;
                v01 = 0.5 * ((double)vl.x * (double)fy + (double)vl.y * (double)fx);
                v02 = 0.5 * ((double)vl.x * (double)fz + (double)vl.z * (double)fx);
                v11 = (double)vl.y * (double)fy;
                v12 = 0.5 * ((double)vl.y * (double)fz + (double)vl.z * (double)fy);
                v22 = (double)vl.z * (double)fz;
            }
        }
    }
    if (HAS_ZBL && __any_sync(0xffffffffu, e_zbl_thread != 0.0)) {
        #pragma unroll
        for (int off = 16; off > 0; off >>= 1) e_zbl_thread += __shfl_xor_sync(0xffffffffu, e_zbl_thread, off);
        if (lane == 0) atomicAdd(energy, e_zbl_thread);
    }
    if (STRESS) {
        #pragma unroll
        for (int off = 16; off > 0; off >>= 1) {
            v00 += __shfl_xor_sync(0xffffffffu, v00, off);
            v01 += __shfl_xor_sync(0xffffffffu, v01, off);
            v02 += __shfl_xor_sync(0xffffffffu, v02, off);
            v11 += __shfl_xor_sync(0xffffffffu, v11, off);
            v12 += __shfl_xor_sync(0xffffffffu, v12, off);
            v22 += __shfl_xor_sync(0xffffffffu, v22, off);
        }
        __shared__ double s_v[4][6];
        if (lane == 0) {
            s_v[warp][0] = v00; s_v[warp][1] = v01; s_v[warp][2] = v02;
            s_v[warp][3] = v11; s_v[warp][4] = v12; s_v[warp][5] = v22;
        }
        __syncthreads();
        if (tid < 6) {
            double sum = 0.0;
            #pragma unroll
            for (int w = 0; w < 4; ++w) sum += s_v[w][tid];
            if (sum != 0.0) atomicAdd(virial + tid, sum);
        }
    }
}
