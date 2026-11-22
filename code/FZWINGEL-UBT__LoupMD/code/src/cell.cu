// SPDX-License-Identifier: LGPL-2.1-or-later
// Provenance: the Berendsen barostat of this file follows ASE 3.27's ase/md/nptberendsen.py (NPTBerendsen and
// Inhomogeneous_NPTBerendsen; LGPL-2.1-or-later, (c) the ASE developers, https://gitlab.com/ase/ase); see NOTICE.md.
// The variable cell's kernels (cell.hpp).
#include "cell.hpp"

#include <cmath>

namespace loup {

__global__ void cell_debug_rate_kernel(double rate, CellDev* __restrict__ cell) {
    const double s = 1.0 + rate;
    for (int i = 0; i < 9; ++i) cell->move[i] = (i % 4 == 0) ? s : 0.0;
    cell->has_move = 1;
}

__global__ void cell_move_positions_kernel(int N, const CellDev* __restrict__ cell, double* __restrict__ pos64) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= N || !cell->has_move) return;
    const double* m = cell->move;
    const double x = pos64[i * 3 + 0], y = pos64[i * 3 + 1], z = pos64[i * 3 + 2];
    pos64[i * 3 + 0] = x * m[0] + y * m[3] + z * m[6];
    pos64[i * 3 + 1] = x * m[1] + y * m[4] + z * m[7];
    pos64[i * 3 + 2] = x * m[2] + y * m[5] + z * m[8];
}

__device__ __forceinline__ void mat3_mul(const double* a, const double* b, double* out) {
    for (int r = 0; r < 3; ++r)
        for (int c = 0; c < 3; ++c)
            out[r * 3 + c] = a[r * 3 + 0] * b[0 * 3 + c] + a[r * 3 + 1] * b[1 * 3 + c] + a[r * 3 + 2] * b[2 * 3 + c];
}

__global__ void cell_derive_kernel(CellDev* __restrict__ cell, int* __restrict__ need_rebuild) {
    double h[9];
    if (cell->has_move == 2) {
        for (int i = 0; i < 9; ++i) h[i] = cell->row_scale[i / 3] * cell->h[i];
        for (int i = 0; i < 9; ++i) cell->h[i] = h[i];
        cell->has_move = 0;
    } else if (cell->has_move) {
        mat3_mul(cell->h, cell->move, h);
        for (int i = 0; i < 9; ++i) cell->h[i] = h[i];
        cell->has_move = 0;
    } else {
        for (int i = 0; i < 9; ++i) h[i] = cell->h[i];
    }
    double f[9];
    mat3_mul(cell->ref_inv, h, f);
    double dev2 = 0.0;
    for (int i = 0; i < 9; ++i) {
        cell->f[i] = f[i];
        const double e = f[i] - ((i % 4 == 0) ? 1.0 : 0.0);
        dev2 += e * e;
    }
    cell->thr = 0.5 * (cell->r_list * (1.0 - sqrt(dev2)) - cell->r_max);
    const double det = h[0] * (h[4] * h[8] - h[5] * h[7]) - h[1] * (h[3] * h[8] - h[5] * h[6]) +
                       h[2] * (h[3] * h[7] - h[4] * h[6]);
    const double volume = fabs(det);
    cell->volume = volume;
    if (!(volume >= cell->v0 / 20.0 && volume <= 20.0 * cell->v0)) atomicOr(need_rebuild, 8);
}

__global__ void check_skin_cell_kernel(
    int N, const double* __restrict__ pos64, const double* __restrict__ ref_pos64, const CellDev* __restrict__ cell,
    int* __restrict__ need_rebuild
) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= N) return;
    const double* f = cell->f;
    const double x0 = ref_pos64[i * 3 + 0], y0 = ref_pos64[i * 3 + 1], z0 = ref_pos64[i * 3 + 2];
    const double dx = pos64[i * 3 + 0] - (x0 * f[0] + y0 * f[3] + z0 * f[6]);
    const double dy = pos64[i * 3 + 1] - (x0 * f[1] + y0 * f[4] + z0 * f[7]);
    const double dz = pos64[i * 3 + 2] - (x0 * f[2] + y0 * f[5] + z0 * f[8]);
    const double d2 = dx * dx + dy * dy + dz * dz;
    const double limit = cell->thr;
    // atomicOr, not a store: cell_derive_kernel's bit 8 (the cell diverged) must survive.
    if (limit <= 0.0 || d2 > limit * limit) atomicOr(need_rebuild, 1);
}

__global__ void cell_shift_codes_kernel(int E, Mat3 inv, const double* __restrict__ shift_cart,
                                        char4* __restrict__ code, int* __restrict__ bad) {
    const int e = blockIdx.x * blockDim.x + threadIdx.x;
    if (e >= E) return;
    const double v0 = shift_cart[(size_t)e * 3 + 0], v1 = shift_cart[(size_t)e * 3 + 1],
                 v2 = shift_cart[(size_t)e * 3 + 2];
    double n[3];
    for (int k = 0; k < 3; ++k) n[k] = rint(v0 * inv.m[k] + v1 * inv.m[3 + k] + v2 * inv.m[6 + k]);
    if (fabs(n[0]) > 127.0 || fabs(n[1]) > 127.0 || fabs(n[2]) > 127.0) {
        *bad = 1;
        return;
    }
    code[e] = make_char4((signed char)n[0], (signed char)n[1], (signed char)n[2], 0);
}

__global__ void shift_cart_kernel(
    const int* __restrict__ n_edges, const CellDev* __restrict__ cell,
    const char4* __restrict__ code, double* __restrict__ shift_cart
) {
    const int e = blockIdx.x * blockDim.x + threadIdx.x;
    if (e >= n_edges[0]) return;
    const double* c = cell->h;
    const char4 s = code[e];
    const double x = (double)s.x, y = (double)s.y, z = (double)s.z;
    shift_cart[e * 3 + 0] = x * c[0] + y * c[3] + z * c[6];
    shift_cart[e * 3 + 1] = x * c[1] + y * c[4] + z * c[7];
    shift_cart[e * 3 + 2] = x * c[2] + y * c[5] + z * c[8];
}

__global__ void kinetic_diag_kernel(int N, const double* __restrict__ masses, const double* __restrict__ vel64,
                                    double* __restrict__ out) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    double k[3] = {0.0, 0.0, 0.0};
    if (i < N) {
        #pragma unroll
        for (int a = 0; a < 3; ++a) k[a] = masses[i] * vel64[i * 3 + a] * vel64[i * 3 + a];
    }
    __shared__ double s_k[3][8];
    const int warp = threadIdx.x >> 5;
    #pragma unroll
    for (int a = 0; a < 3; ++a) {
        double v = k[a];
        #pragma unroll
        for (int off = 16; off > 0; off >>= 1) v += __shfl_xor_sync(0xffffffffu, v, off);
        if ((threadIdx.x & 31) == 0) s_k[a][warp] = v;
    }
    __syncthreads();
    if (threadIdx.x < 3) {
        double sum = 0.0;
        const int nw = blockDim.x >> 5;
        for (int w = 0; w < nw; ++w) sum += s_k[threadIdx.x][w];
        atomicAdd(out + threadIdx.x, sum);
    }
}

__global__ void berendsen_npt_kernel(int full, int mask_x, int mask_y, int mask_z, double pressure, double dt,
                                     double taup, double compressibility, double* __restrict__ work,
                                     const double* __restrict__ virial, CellDev* __restrict__ cell) {
    const double lambda2 = work[1] * work[1];
    const double volume = cell->volume;
    double s[3];
    if (!full) {
        // ASE: taupscl = dt / taup; scl = 1 - taupscl * compressibility / 3 * (pressure - old_pressure)
        const double trace = (virial[0] + virial[3] + virial[5]) / volume - lambda2 * 2.0 * work[5] / volume;
        const double old_pressure = -trace / 3.0;
        const double taupscl = dt / taup;
        s[0] = s[1] = s[2] = 1.0 - taupscl * compressibility / 3.0 * (pressure - old_pressure);
    } else {
        // ASE: taupscl = dt * compressibility / taup / 3; scl_a = 1 - taupscl * (pressure - (-stress_aa)) * mask_a
        const double taupscl = dt * compressibility / taup / 3.0;
        const int mask[3] = {mask_x, mask_y, mask_z};
        const int diag[3] = {0, 3, 5};
        for (int a = 0; a < 3; ++a) {
            const double minus_stress = -(virial[diag[a]] / volume - lambda2 * work[2 + a] / volume);
            s[a] = 1.0 - taupscl * (pressure - minus_stress) * (double)mask[a];
        }
    }
    work[2] = work[3] = work[4] = 0.0;
    // The cell's vectors are scaled, h <- diag(s) h, and the atoms keep their fractional coordinates:
    // x <- x h^-1 diag(s) h. For equal factors that is the factor itself.
    if (s[0] == s[1] && s[1] == s[2]) {
        for (int i = 0; i < 9; ++i) cell->move[i] = (i % 4 == 0) ? s[0] : 0.0;
    } else {
        const double* h = cell->h;
        const double c00 = h[4] * h[8] - h[5] * h[7], c01 = h[5] * h[6] - h[3] * h[8], c02 = h[3] * h[7] - h[4] * h[6];
        const double inv_det = 1.0 / (h[0] * c00 + h[1] * c01 + h[2] * c02);
        double inv[9];
        inv[0] = c00 * inv_det;
        inv[1] = (h[2] * h[7] - h[1] * h[8]) * inv_det;
        inv[2] = (h[1] * h[5] - h[2] * h[4]) * inv_det;
        inv[3] = c01 * inv_det;
        inv[4] = (h[0] * h[8] - h[2] * h[6]) * inv_det;
        inv[5] = (h[2] * h[3] - h[0] * h[5]) * inv_det;
        inv[6] = c02 * inv_det;
        inv[7] = (h[1] * h[6] - h[0] * h[7]) * inv_det;
        inv[8] = (h[0] * h[4] - h[1] * h[3]) * inv_det;
        double dh[9];
        for (int r = 0; r < 3; ++r)
            for (int c = 0; c < 3; ++c) dh[r * 3 + c] = s[r] * h[r * 3 + c];
        mat3_mul(inv, dh, cell->move);
    }
    for (int a = 0; a < 3; ++a) cell->row_scale[a] = s[a];
    cell->has_move = 2;
}

__global__ void positions_times_matrix_kernel(int N, Mat3 mat, double* __restrict__ pos64) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= N) return;
    const double* m = mat.m;
    const double x = pos64[i * 3 + 0], y = pos64[i * 3 + 1], z = pos64[i * 3 + 2];
    pos64[i * 3 + 0] = x * m[0] + y * m[3] + z * m[6];
    pos64[i * 3 + 1] = x * m[1] + y * m[4] + z * m[7];
    pos64[i * 3 + 2] = x * m[2] + y * m[5] + z * m[8];
}

}  // namespace loup
