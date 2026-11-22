// SPDX-License-Identifier: LGPL-2.1-or-later
// Provenance: LBFGS as ASE 3.27's ase/optimize/lbfgs.py does it (LGPL-2.1-or-later, (c) the ASE developers,
// https://gitlab.com/ase/ase), through loupmd/optimize/lbfgs.py; see NOTICE.md.
// Structure relaxation on the device (loup_minimize): the kernels of LBFGS as ASE 3.27 does it, in the matrix form
// of loupmd/optimize/lbfgs.py. The optimiser's vectors live on the device in the engine's atom order; the host
// solves the two small triangular systems of the history (at most `memory` unknowns) and decides convergence.
//
// A step with gradient g (minus the forces, zero on fixed atoms), positions x and the previous x0, g0:
//   the history gains s = x - x0, y = g - g0;
//   with S, Y the history rows, G_ij = s_i . y_j, R = diag(1 / (y_i . s_i)) and H0 = 1 / alpha:
//     (I + R triu(G, 1)) a = R S g,   z = H0 (g - Y^T a),   (I + R tril(G^T, -1)) c = a - R Y z,   p = -(z + S^T c);
//   Y z = H0 (Y g - (Y Y^T) a), so one pass over the history gives every product the host needs (S g, Y g and the
//   new row and column of G and Y Y^T) and a second pass forms p = -H0 g + Y^T (H0 a) - S^T c;
//   if the longest per-atom length of p reaches maxstep the whole step is scaled to it; x += damping p.
//
// The host waits for the device once per step (for the products). Its downloads and uploads use pinned memory, and
// the list check of a move comes with the next step's downloads where the move cannot have outdated the list by
// much (engine.cu, minimize_impl).
#include <cuda_runtime.h>
#include <cmath>
#include <cstdint>

namespace loup {

// Non-negative doubles order like their bit patterns, so a maximum over atoms is one atomicMax per warp.
__device__ __forceinline__ void atomic_max_f64(unsigned long long* target, double value) {
    #pragma unroll
    for (int off = 16; off > 0; off >>= 1) value = fmax(value, __shfl_xor_sync(0xffffffffu, value, off));
    if ((threadIdx.x & 31) == 0 && value > 0.0) atomicMax(target, (unsigned long long)__double_as_longlong(value));
}

// The gradient of the step, g = -f on free atoms and 0 on fixed ones (inverse mass 0), and the largest squared
// force on a free atom (out_fmax2, bits of a double, zeroed by the caller). With `have_previous`, the new history
// pair goes into its rows: s_row = x - x0, y_row = g - g0.
__global__ void min_gradient_kernel(
    int N, int have_previous,
    const double* __restrict__ forces, const double* __restrict__ inv_masses, const double* __restrict__ pos64,
    const double* __restrict__ x0, const double* __restrict__ g0,
    double* __restrict__ g, double* __restrict__ s_row, double* __restrict__ y_row,
    unsigned long long* __restrict__ out_fmax2
) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    double f2 = 0.0;
    if (i < N) {
        const bool free_atom = inv_masses[i] > 0.0;
        #pragma unroll
        for (int c = 0; c < 3; ++c) {
            const int idx = i * 3 + c;
            const double grad = free_atom ? -forces[idx] : 0.0;
            g[idx] = grad;
            f2 += grad * grad;
            if (have_previous) {
                s_row[idx] = pos64[idx] - x0[idx];
                y_row[idx] = grad - g0[idx];
            }
        }
    }
    atomic_max_f64(out_fmax2, f2);
}

// One pass over the history: for row j (blockIdx.y), the five products S_j . g, Y_j . g, S_j . y, Y_j . s and
// Y_j . y with the newest pair (s, y), summed into out[5 j + q] (zeroed by the caller). 256 threads take
// kMinStrip consecutive elements each.
constexpr int kMinStrip = 16;

__global__ void lbfgs_products_kernel(
    int n3, int stride,
    const double* __restrict__ S, const double* __restrict__ Y,
    const double* __restrict__ g, const double* __restrict__ s_new, const double* __restrict__ y_new,
    double* __restrict__ out
) {
    const int row = blockIdx.y;
    const double* __restrict__ s_row = S + (size_t)row * stride;
    const double* __restrict__ y_row = Y + (size_t)row * stride;
    double acc[5] = {0.0, 0.0, 0.0, 0.0, 0.0};
    const int first = (blockIdx.x * blockDim.x + threadIdx.x) * kMinStrip;
    for (int k = first; k < first + kMinStrip && k < n3; ++k) {
        const double sv = s_row[k], yv = y_row[k];
        acc[0] += sv * g[k];
        acc[1] += yv * g[k];
        acc[2] += sv * y_new[k];
        acc[3] += yv * s_new[k];
        acc[4] += yv * y_new[k];
    }
    __shared__ double s_acc[5][8];
    const int warp = threadIdx.x >> 5;
    #pragma unroll
    for (int q = 0; q < 5; ++q) {
        double v = acc[q];
        #pragma unroll
        for (int off = 16; off > 0; off >>= 1) v += __shfl_xor_sync(0xffffffffu, v, off);
        if ((threadIdx.x & 31) == 0) s_acc[q][warp] = v;
    }
    __syncthreads();
    if (threadIdx.x < 5) {
        double sum = 0.0;
        const int nw = blockDim.x >> 5;
        for (int w = 0; w < nw; ++w) sum += s_acc[threadIdx.x][w];
        atomicAdd(out + 5 * row + threadIdx.x, sum);
    }
}

// The direction p = -H0 g + sum_j (u_j Y_j + w_j S_j) over the `rows` history rows listed in row_index, per atom,
// and the largest squared per-atom length of p (out_len2, bits of a double, zeroed by the caller).
__global__ void lbfgs_direction_kernel(
    int N, int rows, int stride, double h0,
    const int* __restrict__ row_index, const double* __restrict__ u, const double* __restrict__ w,
    const double* __restrict__ S, const double* __restrict__ Y, const double* __restrict__ g,
    double* __restrict__ p, unsigned long long* __restrict__ out_len2
) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    double len2 = 0.0;
    if (i < N) {
        double px = -h0 * g[i * 3 + 0], py = -h0 * g[i * 3 + 1], pz = -h0 * g[i * 3 + 2];
        for (int k = 0; k < rows; ++k) {
            const size_t base = (size_t)row_index[k] * stride + (size_t)i * 3;
            const double uk = u[k], wk = w[k];
            px += uk * Y[base + 0] + wk * S[base + 0];
            py += uk * Y[base + 1] + wk * S[base + 1];
            pz += uk * Y[base + 2] + wk * S[base + 2];
        }
        p[i * 3 + 0] = px;
        p[i * 3 + 1] = py;
        p[i * 3 + 2] = pz;
        len2 = px * px + py * py + pz * pz;
    }
    atomic_max_f64(out_len2, len2);
}

// The step: remembers x and g as x0 and g0, then x += damping p, scaled so that the longest per-atom step is
// maxstep if it would be longer (len2: the largest squared length of p, from lbfgs_direction_kernel).
__global__ void lbfgs_move_kernel(
    int N, double maxstep, double damping, const unsigned long long* __restrict__ len2,
    const double* __restrict__ p, const double* __restrict__ g,
    double* __restrict__ pos64, double* __restrict__ x0, double* __restrict__ g0
) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= N) return;
    const double longest = sqrt(__longlong_as_double((long long)len2[0]));
    const double scale = damping * (longest >= maxstep ? maxstep / longest : 1.0);
    #pragma unroll
    for (int c = 0; c < 3; ++c) {
        const int idx = i * 3 + c;
        x0[idx] = pos64[idx];
        g0[idx] = g[idx];
        pos64[idx] += scale * p[idx];
    }
}

// The largest squared displacement of an atom from the positions the neighbour list was built at (out_disp2, bits
// of a double, zeroed by the caller). The list holds every pair while its root is at most half the skin.
__global__ void max_displacement2_kernel(
    int N, const double* __restrict__ pos64, const double* __restrict__ ref_pos64,
    unsigned long long* __restrict__ out_disp2
) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    double d2 = 0.0;
    if (i < N) {
        const double dx = pos64[i * 3 + 0] - ref_pos64[i * 3 + 0];
        const double dy = pos64[i * 3 + 1] - ref_pos64[i * 3 + 1];
        const double dz = pos64[i * 3 + 2] - ref_pos64[i * 3 + 2];
        d2 = dx * dx + dy * dy + dz * dz;
    }
    atomic_max_f64(out_disp2, d2);
}

}  // namespace loup
