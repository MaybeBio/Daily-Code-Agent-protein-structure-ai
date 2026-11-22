#include "kernels_common.cuh"
#include "model.hpp"
#include <cub/cub.cuh>
#include <cmath>

namespace loup {

struct CellMat64 {
    double c[9];     // row-major: row k is lattice vector a_k
    double inv[9];   // row-major inverse: frac = pos @ inv
};

__device__ __forceinline__ int floor_div(int a, int b) {
    int q = a / b;
    int r = a % b;
    if (r != 0 && ((r < 0) != (b < 0))) --q;
    return q;
}

__device__ __forceinline__ uint32_t float_to_ordered_uint(float f) {
    uint32_t u = __float_as_uint(f);
    uint32_t mask = -int32_t(u >> 31) | 0x80000000u;
    return u ^ mask;
}

__global__ void wrap_and_bin_kernel(
    int N, CellMat64 cell, int nx, int ny, int nz,
    const double* __restrict__ pos64,
    double* __restrict__ pos_wrapped,
    int* __restrict__ atom_wrap,
    int* __restrict__ atom_bin,
    int* __restrict__ bin_counts
) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= N) return;
    double x = pos64[i * 3 + 0], y = pos64[i * 3 + 1], z = pos64[i * 3 + 2];
    double fx = x * cell.inv[0] + y * cell.inv[3] + z * cell.inv[6];
    double fy = x * cell.inv[1] + y * cell.inv[4] + z * cell.inv[7];
    double fz = x * cell.inv[2] + y * cell.inv[5] + z * cell.inv[8];
    int wx = (int)floor(fx);
    int wy = (int)floor(fy);
    int wz = (int)floor(fz);
    fx -= (double)wx;
    fy -= (double)wy;
    fz -= (double)wz;
    // Handle tiny negative rounding like -1e-16 -> wrap
    if (fx >= 1.0) { fx -= 1.0; wx += 1; } else if (fx < 0.0) { fx += 1.0; wx -= 1; }
    if (fy >= 1.0) { fy -= 1.0; wy += 1; } else if (fy < 0.0) { fy += 1.0; wy -= 1; }
    if (fz >= 1.0) { fz -= 1.0; wz += 1; } else if (fz < 0.0) { fz += 1.0; wz -= 1; }

    pos_wrapped[i * 3 + 0] = fx * cell.c[0] + fy * cell.c[3] + fz * cell.c[6];
    pos_wrapped[i * 3 + 1] = fx * cell.c[1] + fy * cell.c[4] + fz * cell.c[7];
    pos_wrapped[i * 3 + 2] = fx * cell.c[2] + fy * cell.c[5] + fz * cell.c[8];
    atom_wrap[i * 3 + 0] = wx;
    atom_wrap[i * 3 + 1] = wy;
    atom_wrap[i * 3 + 2] = wz;

    int bx = min(nx - 1, max(0, (int)(fx * nx)));
    int by = min(ny - 1, max(0, (int)(fy * ny)));
    int bz = min(nz - 1, max(0, (int)(fz * nz)));
    int bid = (bx * ny + by) * nz + bz;
    atom_bin[i] = bid;
    atomicAdd(bin_counts + bid, 1);
}

__device__ __forceinline__ unsigned long long spread_bits16(unsigned v) {
    unsigned long long x = v & 0xFFFFu;
    x = (x | (x << 16)) & 0x0000FF0000FFull;
    x = (x | (x << 8)) & 0x00F00F00F00Full;
    x = (x | (x << 4)) & 0x0C30C30C30C3ull;
    x = (x | (x << 2)) & 0x249249249249ull;
    return x;
}

// Atom order key: species in the top bits (keeps the species groups the GEMMs rely on), then the Morton code of the
// atom's cell-list bin, so atoms close in space are close in memory (sender rows and sender-gradient atomics of an
// edge tile then stay in L2 for large or shuffled systems).
__global__ void atom_order_keys_kernel(
    int N, int nx, int ny, int nz,
    const int* __restrict__ species,
    const int* __restrict__ atom_bin,
    unsigned long long* __restrict__ keys,
    int* __restrict__ vals
) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= N) return;
    const int bid = atom_bin[i];
    const unsigned bz = (unsigned)(bid % nz);
    const unsigned by = (unsigned)((bid / nz) % ny);
    const unsigned bx = (unsigned)(bid / (ny * nz));
    const unsigned long long m = spread_bits16(min(bx, 0xFFFFu)) | (spread_bits16(min(by, 0xFFFFu)) << 1) |
                                 (spread_bits16(min(bz, 0xFFFFu)) << 2);
    keys[i] = ((unsigned long long)species[i] << 48) | m;
    vals[i] = i;
}

// dst[i, :] = src[order[i], :] for a row-major [n, width] float64 array.
__global__ void gather_rows_f64_kernel(int n, int width, const int* __restrict__ order,
                                       const double* __restrict__ src, double* __restrict__ dst) {
    int k = blockIdx.x * blockDim.x + threadIdx.x;
    if (k >= n * width) return;
    const int i = k / width, c = k - i * width;
    dst[k] = src[(int64_t)order[i] * width + c];
}

__global__ void scatter_bins_kernel(
    int N,
    const double* __restrict__ pos_wrapped,
    const int* __restrict__ atom_wrap,
    const int* __restrict__ species,
    const int* __restrict__ atom_bin,
    int* __restrict__ bin_cursor,
    int* __restrict__ bin_atom_id,
    double* __restrict__ bin_pos,
    float4* __restrict__ bin_pos_f32,
    int* __restrict__ bin_wrap,
    int* __restrict__ bin_sp
) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= N) return;
    int bid = atom_bin[i];
    int slot = atomicAdd(bin_cursor + bid, 1);
    const double px = pos_wrapped[i * 3 + 0];
    const double py = pos_wrapped[i * 3 + 1];
    const double pz = pos_wrapped[i * 3 + 2];
    bin_atom_id[slot] = i;
    bin_pos[slot * 3 + 0] = px;
    bin_pos[slot * 3 + 1] = py;
    bin_pos[slot * 3 + 2] = pz;
    bin_pos_f32[slot] = make_float4((float)px, (float)py, (float)pz, 0.0f);
    bin_wrap[slot * 3 + 0] = atom_wrap[i * 3 + 0];
    bin_wrap[slot * 3 + 1] = atom_wrap[i * 3 + 1];
    bin_wrap[slot * 3 + 2] = atom_wrap[i * 3 + 2];
    bin_sp[slot] = species[i];
}

// count / fill: kNeighborLanes consecutive lanes share one atom and split its neighbouring bins round-robin (lane g
// scans scan-order bins g, g + G, ...), so each lane does a 1/G share of the per-atom work without duplicating the
// per-bin bookkeeping (one thread per atom left the grid at N / 32 warps, ~8% occupancy for 5,000 atoms).
// fill_neighbors_kernel keeps the exact row order of the one-thread kernels (bins in scan order, slots in bin order):
// it counts each bin's candidates into shared memory, turns the counts into running offsets from row_ptr[i], and
// then writes every bin's edges from its offset. The candidate tests are repeated, but in parallel.
__device__ __forceinline__ unsigned neighbor_group_mask() {
    constexpr unsigned G = kNeighborLanes;
    constexpr unsigned ones = G == 32 ? 0xffffffffu : ((1u << G) - 1u);
    return ones << ((threadIdx.x & 31u) & ~(G - 1u));
}

// Walks the scan-order bins b = first, first + step, ... of atom i's (2rx+1)(2ry+1)(2rz+1) neighbourhood and calls
// visit(b, slot, j, r, ix, iy, iz) for every candidate within the list radius (same float pre-test / double band as the
// one-thread kernels).
// S120: a bin that cannot hold a candidate is skipped. Along cell axis a the atom sits at u_a (in bin units) inside its
// own bin, so a bin at offset o lies at least L_a = (o > 0 ? o - u_a : o < 0 ? u_a - o - 1 : 0) bin heights h_a / n_a
// away (h_a the spacing of the lattice planes): the box is at least max_a L_a away, and sqrt(sum_a L_a^2) in an
// orthogonal cell. Bins whose bound reaches r_hi (the float pre-test's radius, r_list plus its margin) hold no atom
// within r_list, so the rows (and their order) are unchanged.
template <class Visit>
__device__ __forceinline__ void scan_neighbor_bins(
    int i, int first, int step, const CellMat64& cell, int nx, int ny, int nz, int rx, int ry, int rz, double r_list2,
    float r_lo2_f32, float r_hi2_f32, double xi, double yi, double zi, int bid, const int* __restrict__ bin_offsets,
    const int* __restrict__ bin_atom_id, const double* __restrict__ bin_pos, const float4* __restrict__ bin_pos_f32,
    Visit&& visit) {
    const float fxi = (float)xi, fyi = (float)yi, fzi = (float)zi;
    const int bxi = bid / (ny * nz);
    const int rem = bid - bxi * (ny * nz);
    const int byi = rem / nz;
    const int bzi = rem - byi * nz;
    // All in float (sm_120's FP64 rate is 1/64): the rounding of u_a and of the bound (~1e-5 A at 100 A positions) is
    // far inside r_hi's margin (>= 0.01 A).
    const int nb[3] = {nx, ny, nz}, bi[3] = {bxi, byi, bzi};
    float u[3], bh[3];
    #pragma unroll
    for (int a = 0; a < 3; ++a) {
        // column a of inv: f_a = pos . (inv[a], inv[3 + a], inv[6 + a])
        const float v0 = (float)cell.inv[a], v1 = (float)cell.inv[3 + a], v2 = (float)cell.inv[6 + a];
        u[a] = fmaf(fxi, v0, fmaf(fyi, v1, fzi * v2)) * (float)nb[a] - (float)bi[a];
        bh[a] = 1.0f / ((float)nb[a] * sqrtf(fmaf(v0, v0, fmaf(v1, v1, v2 * v2))));
    }
    const bool ortho = cell.c[1] == 0.0 && cell.c[2] == 0.0 && cell.c[3] == 0.0 && cell.c[5] == 0.0 &&
                       cell.c[6] == 0.0 && cell.c[7] == 0.0;
    auto gap = [](int o, float ua) { return o > 0 ? (float)o - ua : (o < 0 ? ua - (float)(o + 1) : 0.0f); };
    const int wy = 2 * ry + 1, wz = 2 * rz + 1, nscan = (2 * rx + 1) * wy * wz;
    for (int b = first; b < nscan; b += step) {
        const int qx = b / (wy * wz), qr = b - qx * (wy * wz), qy = qr / wz, qz = qr - qy * wz;
        {
            const float lx = gap(qx - rx, u[0]) * bh[0], ly = gap(qy - ry, u[1]) * bh[1],
                        lz = gap(qz - rz, u[2]) * bh[2];
            const float lb2 = ortho ? lx * lx + ly * ly + lz * lz : fmaxf(lx * lx, fmaxf(ly * ly, lz * lz));
            if (lb2 >= r_hi2_f32) continue;
        }
        const int raw_x = bxi + qx - rx, raw_y = byi + qy - ry, raw_z = bzi + qz - rz;
        const int ix = floor_div(raw_x, nx), iy = floor_div(raw_y, ny), iz = floor_div(raw_z, nz);
        const int bxj = raw_x - ix * nx, byj = raw_y - iy * ny, bzj = raw_z - iz * nz;
        // Same evaluation order as the one-thread kernels (product, then the hierarchical sums), so the float shift and
        // every distance, and therefore the sort keys, are bit-identical.
        const double sx_x = (double)ix * cell.c[0], sx_y = (double)ix * cell.c[1], sx_z = (double)ix * cell.c[2];
        const double sxy_x = sx_x + (double)iy * cell.c[3];
        const double sxy_y = sx_y + (double)iy * cell.c[4];
        const double sxy_z = sx_z + (double)iy * cell.c[5];
        const double s_x = sxy_x + (double)iz * cell.c[6];
        const double s_y = sxy_y + (double)iz * cell.c[7];
        const double s_z = sxy_z + (double)iz * cell.c[8];
        const float fs_x = (float)s_x, fs_y = (float)s_y, fs_z = (float)s_z;
        const int nbid = (bxj * ny + byj) * nz + bzj;
        const int b0 = bin_offsets[nbid], b1 = bin_offsets[nbid + 1];
        const bool zero_img = (ix == 0 && iy == 0 && iz == 0);
        for (int slot = b0; slot < b1; ++slot) {
            const float4 pj = __ldg(bin_pos_f32 + slot);
            const float fx = fxi - (pj.x + fs_x);
            const float fy = fyi - (pj.y + fs_y);
            const float fz = fzi - (pj.z + fs_z);
            const float fr2 = fx * fx + fy * fy + fz * fz;
            if (fr2 >= r_hi2_f32) continue;
            const int j = bin_atom_id[slot];
            if (zero_img && j == i) continue;
            float r;
            if (fr2 < r_lo2_f32) {
                r = sqrtf(fr2);
            } else {
                const double vx = xi - (bin_pos[slot * 3 + 0] + s_x);
                const double vy = yi - (bin_pos[slot * 3 + 1] + s_y);
                const double vz = zi - (bin_pos[slot * 3 + 2] + s_z);
                const double r2 = vx * vx + vy * vy + vz * vz;
                if (!(r2 < r_list2)) continue;
                r = (float)sqrt(r2);
            }
            visit(b, slot, j, r, ix, iy, iz);
        }
    }
}

__global__ void count_neighbors_kernel(
    int N, CellMat64 cell, int nx, int ny, int nz,
    int rx, int ry, int rz, double r_list2, float r_lo2_f32, float r_hi2_f32,
    const double* __restrict__ pos_wrapped,
    const int* __restrict__ atom_bin,
    const int* __restrict__ bin_offsets,
    const int* __restrict__ bin_atom_id,
    const double* __restrict__ bin_pos,
    const float4* __restrict__ bin_pos_f32,
    int* __restrict__ deg
) {
    constexpr int G = kNeighborLanes;
    const int t = blockIdx.x * blockDim.x + threadIdx.x;
    const int i = t / G, g = t % G;
    if (i >= N) return;  // N * G threads cover whole groups, so a group exits together
    int count = 0;
    scan_neighbor_bins(i, g, G, cell, nx, ny, nz, rx, ry, rz, r_list2, r_lo2_f32, r_hi2_f32,
                       pos_wrapped[i * 3 + 0], pos_wrapped[i * 3 + 1], pos_wrapped[i * 3 + 2], atom_bin[i],
                       bin_offsets, bin_atom_id, bin_pos, bin_pos_f32,
                       [&](int, int, int, float, int, int, int) { ++count; });
    #pragma unroll
    for (int off = G / 2; off > 0; off >>= 1) count += __shfl_xor_sync(neighbor_group_mask(), count, off);
    if (g == 0) deg[i] = count;
}

// Dynamic shared memory: (blockDim.x / kNeighborLanes) * nscan ints (one bin-offset table per atom of the block).
__global__ void fill_neighbors_kernel(
    int N, int S, CellMat64 cell, int nx, int ny, int nz,
    int rx, int ry, int rz, double r_list2, float r_lo2_f32, float r_hi2_f32,
    const double* __restrict__ pos_wrapped,
    const int* __restrict__ atom_wrap,
    const int* __restrict__ species,
    const int* __restrict__ atom_bin,
    const int* __restrict__ bin_offsets,
    const int* __restrict__ bin_atom_id,
    const double* __restrict__ bin_pos,
    const float4* __restrict__ bin_pos_f32,
    const int* __restrict__ bin_wrap,
    const int* __restrict__ bin_sp,
    const int* __restrict__ row_ptr,
    int* __restrict__ tmp_snd,
    int* __restrict__ tmp_shifts,
    uint32_t* __restrict__ sort_keys,
    const int* __restrict__ go  // MD step graph: run only if *go (the rebuild gate's verdict); nullptr = always
) {
    if (go && !*go) return;
    extern __shared__ int s_bin_off[];
    constexpr int G = kNeighborLanes;
    const int t = blockIdx.x * blockDim.x + threadIdx.x;
    const int i = t / G, g = t % G;
    if (i >= N) return;  // whole groups exit together; no block-wide barrier below
    const unsigned gmask = neighbor_group_mask();
    const int nscan = (2 * rx + 1) * (2 * ry + 1) * (2 * rz + 1);
    int* off = s_bin_off + (threadIdx.x / G) * nscan;
    const double xi = pos_wrapped[i * 3 + 0], yi = pos_wrapped[i * 3 + 1], zi = pos_wrapped[i * 3 + 2];
    const int bid = atom_bin[i];
    // Pass 1: per-bin candidate counts (lane g owns bins g, g + G, ...).
    for (int b = g; b < nscan; b += G) off[b] = 0;
    scan_neighbor_bins(i, g, G, cell, nx, ny, nz, rx, ry, rz, r_list2, r_lo2_f32, r_hi2_f32, xi, yi, zi, bid,
                       bin_offsets, bin_atom_id, bin_pos, bin_pos_f32,
                       [&](int b, int, int, float, int, int, int) { ++off[b]; });
    __syncwarp(gmask);
    // Running offsets in scan order (as the one-thread kernels' cursor walk).
    if (g == 0) {
        int run = row_ptr[i];
        for (int b = 0; b < nscan; ++b) {
            const int c = off[b];
            off[b] = run;
            run += c;
        }
    }
    __syncwarp(gmask);
    // Pass 2: each bin's edges from its offset, in slot order.
    const int row_end = row_ptr[i + 1];
    const int wi_x = atom_wrap[i * 3 + 0], wi_y = atom_wrap[i * 3 + 1], wi_z = atom_wrap[i * 3 + 2];
    const int sp_i = species[i];
    scan_neighbor_bins(i, g, G, cell, nx, ny, nz, rx, ry, rz, r_list2, r_lo2_f32, r_hi2_f32, xi, yi, zi, bid,
                       bin_offsets, bin_atom_id, bin_pos, bin_pos_f32,
                       [&](int b, int slot, int j, float r, int ix, int iy, int iz) {
                           const int pos = off[b]++;
                           if (pos >= row_end) return;
                           const int p = sym_pair(bin_sp[slot], sp_i, S);
                           tmp_snd[pos] = j;
                           tmp_shifts[pos * 3 + 0] = bin_wrap[slot * 3 + 0] - wi_x - ix;
                           tmp_shifts[pos * 3 + 1] = bin_wrap[slot * 3 + 1] - wi_y - iy;
                           tmp_shifts[pos * 3 + 2] = bin_wrap[slot * 3 + 2] - wi_z - iz;
                           sort_keys[pos] = ((uint32_t)p << 19) | (__float_as_uint(r) >> 12);
                       });
}

// One thread per atom (32-thread blocks): the build used on GPUs other than sm_120, where the lane-group kernels
// above have not been measured. Rows are written in sequential (bin, slot) order.
__global__ void count_neighbors_scalar_kernel(
    int N, CellMat64 cell, int nx, int ny, int nz,
    int rx, int ry, int rz, double r_list2, float r_lo2_f32, float r_hi2_f32,
    const double* __restrict__ pos_wrapped,
    const int* __restrict__ atom_bin,
    const int* __restrict__ bin_offsets,
    const int* __restrict__ bin_atom_id,
    const double* __restrict__ bin_pos,
    const float4* __restrict__ bin_pos_f32,
    int* __restrict__ deg
) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= N) return;
    double xi = pos_wrapped[i * 3 + 0];
    double yi = pos_wrapped[i * 3 + 1];
    double zi = pos_wrapped[i * 3 + 2];
    float fxi = (float)xi, fyi = (float)yi, fzi = (float)zi;
    int bid = atom_bin[i];
    int bxi = bid / (ny * nz);
    int rem = bid - bxi * (ny * nz);
    int byi = rem / nz;
    int bzi = rem - byi * nz;

    int count = 0;
    for (int dx = -rx; dx <= rx; ++dx) {
        int raw_x = bxi + dx;
        int ix = floor_div(raw_x, nx);
        int bxj = raw_x - ix * nx;
        double sx_x = (double)ix * cell.c[0];
        double sx_y = (double)ix * cell.c[1];
        double sx_z = (double)ix * cell.c[2];
        for (int dy = -ry; dy <= ry; ++dy) {
            int raw_y = byi + dy;
            int iy = floor_div(raw_y, ny);
            int byj = raw_y - iy * ny;
            double sxy_x = sx_x + (double)iy * cell.c[3];
            double sxy_y = sx_y + (double)iy * cell.c[4];
            double sxy_z = sx_z + (double)iy * cell.c[5];
            for (int dz = -rz; dz <= rz; ++dz) {
                int raw_z = bzi + dz;
                int iz = floor_div(raw_z, nz);
                int bzj = raw_z - iz * nz;
                double s_x = sxy_x + (double)iz * cell.c[6];
                double s_y = sxy_y + (double)iz * cell.c[7];
                double s_z = sxy_z + (double)iz * cell.c[8];
                float fs_x = (float)s_x, fs_y = (float)s_y, fs_z = (float)s_z;
                int nbid = (bxj * ny + byj) * nz + bzj;
                int b0 = bin_offsets[nbid];
                int b1 = bin_offsets[nbid + 1];
                bool zero_img = (ix == 0 && iy == 0 && iz == 0);
                for (int slot = b0; slot < b1; ++slot) {
                    const float4 pj = __ldg(bin_pos_f32 + slot);
                    const float fx = fxi - (pj.x + fs_x);
                    const float fy = fyi - (pj.y + fs_y);
                    const float fz = fzi - (pj.z + fs_z);
                    const float fr2 = fx * fx + fy * fy + fz * fz;
                    if (fr2 >= r_hi2_f32) continue;
                    if (zero_img && bin_atom_id[slot] == i) continue;
                    if (fr2 < r_lo2_f32) {
                        ++count;
                    } else {
                        double vx = xi - (bin_pos[slot * 3 + 0] + s_x);
                        double vy = yi - (bin_pos[slot * 3 + 1] + s_y);
                        double vz = zi - (bin_pos[slot * 3 + 2] + s_z);
                        if (vx * vx + vy * vy + vz * vz < r_list2) ++count;
                    }
                }
            }
        }
    }
    deg[i] = count;
}

__global__ void fill_neighbors_scalar_kernel(
    int N, int S, CellMat64 cell, int nx, int ny, int nz,
    int rx, int ry, int rz, double r_list2, float r_lo2_f32, float r_hi2_f32,
    const double* __restrict__ pos_wrapped,
    const int* __restrict__ atom_wrap,
    const int* __restrict__ species,
    const int* __restrict__ atom_bin,
    const int* __restrict__ bin_offsets,
    const int* __restrict__ bin_atom_id,
    const double* __restrict__ bin_pos,
    const float4* __restrict__ bin_pos_f32,
    const int* __restrict__ bin_wrap,
    const int* __restrict__ bin_sp,
    const int* __restrict__ row_ptr,
    int* __restrict__ tmp_snd,
    int* __restrict__ tmp_shifts,
    uint32_t* __restrict__ sort_keys,
    const int* __restrict__ go  // as fill_neighbors_kernel
) {
    if (go && !*go) return;
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= N) return;
    double xi = pos_wrapped[i * 3 + 0];
    double yi = pos_wrapped[i * 3 + 1];
    double zi = pos_wrapped[i * 3 + 2];
    float fxi = (float)xi, fyi = (float)yi, fzi = (float)zi;
    int wi_x = atom_wrap[i * 3 + 0];
    int wi_y = atom_wrap[i * 3 + 1];
    int wi_z = atom_wrap[i * 3 + 2];
    int sp_i = species[i];

    int bid = atom_bin[i];
    int bxi = bid / (ny * nz);
    int rem = bid - bxi * (ny * nz);
    int byi = rem / nz;
    int bzi = rem - byi * nz;

    int cursor = row_ptr[i];
    const int row_end = row_ptr[i + 1];
    for (int dx = -rx; dx <= rx; ++dx) {
        int raw_x = bxi + dx;
        int ix = floor_div(raw_x, nx);
        int bxj = raw_x - ix * nx;
        double sx_x = (double)ix * cell.c[0];
        double sx_y = (double)ix * cell.c[1];
        double sx_z = (double)ix * cell.c[2];
        for (int dy = -ry; dy <= ry; ++dy) {
            int raw_y = byi + dy;
            int iy = floor_div(raw_y, ny);
            int byj = raw_y - iy * ny;
            double sxy_x = sx_x + (double)iy * cell.c[3];
            double sxy_y = sx_y + (double)iy * cell.c[4];
            double sxy_z = sx_z + (double)iy * cell.c[5];
            for (int dz = -rz; dz <= rz; ++dz) {
                int raw_z = bzi + dz;
                int iz = floor_div(raw_z, nz);
                int bzj = raw_z - iz * nz;
                double s_x = sxy_x + (double)iz * cell.c[6];
                double s_y = sxy_y + (double)iz * cell.c[7];
                double s_z = sxy_z + (double)iz * cell.c[8];
                float fs_x = (float)s_x, fs_y = (float)s_y, fs_z = (float)s_z;
                int nbid = (bxj * ny + byj) * nz + bzj;
                int b0 = bin_offsets[nbid];
                int b1 = bin_offsets[nbid + 1];
                bool zero_img = (ix == 0 && iy == 0 && iz == 0);
                for (int slot = b0; slot < b1; ++slot) {
                    const float4 pj = __ldg(bin_pos_f32 + slot);
                    const float fx = fxi - (pj.x + fs_x);
                    const float fy = fyi - (pj.y + fs_y);
                    const float fz = fzi - (pj.z + fs_z);
                    const float fr2 = fx * fx + fy * fy + fz * fz;
                    if (fr2 >= r_hi2_f32) continue;
                    int j = bin_atom_id[slot];
                    if (zero_img && j == i) continue;
                    float r;
                    if (fr2 < r_lo2_f32) {
                        r = sqrtf(fr2);
                    } else {
                        double vx = xi - (bin_pos[slot * 3 + 0] + s_x);
                        double vy = yi - (bin_pos[slot * 3 + 1] + s_y);
                        double vz = zi - (bin_pos[slot * 3 + 2] + s_z);
                        double r2 = vx * vx + vy * vy + vz * vz;
                        if (!(r2 < r_list2)) continue;
                        r = (float)sqrt(r2);
                    }
                    if (cursor < row_end) {
                        int shx = bin_wrap[slot * 3 + 0] - wi_x - ix;
                        int shy = bin_wrap[slot * 3 + 1] - wi_y - iy;
                        int shz = bin_wrap[slot * 3 + 2] - wi_z - iz;
                        int sp_j = bin_sp[slot];
                        int p = sym_pair(sp_j, sp_i, S);
                        tmp_snd[cursor] = j;
                        tmp_shifts[cursor * 3 + 0] = shx;
                        tmp_shifts[cursor * 3 + 1] = shy;
                        tmp_shifts[cursor * 3 + 2] = shz;
                        sort_keys[cursor] = ((uint32_t)p << 19) | (__float_as_uint(r) >> 12);
                        ++cursor;
                    }
                }
            }
        }
    }
}

// Largest row length (count kernels' degrees) into *out (zeroed by the caller): sizes sort_gather_rows_kernel's
// shared memory.
__global__ void max_degree_kernel(int N, const int* __restrict__ deg, int* __restrict__ out) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    const int d = __reduce_max_sync(0xffffffffu, i < N ? deg[i] : 0);
    if ((threadIdx.x & 31) == 0 && d > 0) atomicMax(out, d);
}

// One block per receiver row: sorts the row's edges by (key, fill position) -- the order of a stable segmented sort,
// as each edge's index is its fill position -- with a bitonic network over the row padded to a power of two, gathers
// the sorted edges (each integer image shift turned into its Cartesian offset shift @ cell in float64, so the per-step
// edge-vector kernel does six float64 additions instead of the full shift-cell product) and flags a row whose sender
// species decreases (the contract of layer 0's receiver-owned first_fwd_kernel). The network runs in shared
// memory sized for the longest row, or (kGlobal, rows too long for it) in `scratch` at 2 x the row start (a row padded
// to P < 2L entries stays inside its own 2L slots). Unlike cub::DeviceSegmentedSort, which reads its segment partition
// back to the host, it needs no host round trip.
template <bool kGlobal>
__device__ __forceinline__ void sort_gather_row(
    CellMat64 cell, const int* __restrict__ row_ptr, const uint32_t* __restrict__ sort_keys,
    const int* __restrict__ tmp_snd, const int* __restrict__ tmp_shifts, const int* __restrict__ species,
    int* __restrict__ senders, double* __restrict__ shift_cart,
    int* __restrict__ order_err, unsigned long long* __restrict__ scratch
) {
    extern __shared__ unsigned long long smem_keys[];
    const int b = row_ptr[blockIdx.x];
    const int L = row_ptr[blockIdx.x + 1] - b;
    if (L == 0) return;
    unsigned long long* sk = kGlobal ? scratch + 2 * (size_t)b : smem_keys;
    int P = 1;
    while (P < L) P <<= 1;
    for (int t = threadIdx.x; t < P; t += blockDim.x)
        sk[t] = t < L ? ((unsigned long long)sort_keys[b + t] << 32) | (unsigned int)(b + t) : ~0ull;
    __syncthreads();
    for (int k = 2; k <= P; k <<= 1) {
        for (int j = k >> 1; j > 0; j >>= 1) {
            for (int q = threadIdx.x; q < (P >> 1); q += blockDim.x) {
                const int t = 2 * q - (q & (j - 1));  // lower index of the q-th pair at distance j
                const unsigned long long x = sk[t], y = sk[t + j];
                if ((x > y) == ((t & k) == 0)) {
                    sk[t] = y;
                    sk[t + j] = x;
                }
            }
            __syncthreads();
        }
    }
    for (int t = threadIdx.x; t < L; t += blockDim.x) {
        const int src = (int)(unsigned int)sk[t];
        const int e = b + t;
        const int snd = tmp_snd[src];
        senders[e] = snd;
        const double sx = (double)tmp_shifts[src * 3 + 0];
        const double sy = (double)tmp_shifts[src * 3 + 1];
        const double sz = (double)tmp_shifts[src * 3 + 2];
        shift_cart[e * 3 + 0] = sx * cell.c[0] + sy * cell.c[3] + sz * cell.c[6];
        shift_cart[e * 3 + 1] = sx * cell.c[1] + sy * cell.c[4] + sz * cell.c[7];
        shift_cart[e * 3 + 2] = sx * cell.c[2] + sy * cell.c[5] + sz * cell.c[8];
        if (t > 0 && species[snd] < species[tmp_snd[(int)(unsigned int)sk[t - 1]]]) *order_err = 1;
    }
}
__global__ void sort_gather_rows_kernel(
    CellMat64 cell, const int* __restrict__ row_ptr, const uint32_t* __restrict__ sort_keys,
    const int* __restrict__ tmp_snd, const int* __restrict__ tmp_shifts, const int* __restrict__ species,
    int* __restrict__ senders, double* __restrict__ shift_cart,
    int* __restrict__ order_err, const int* __restrict__ go  // as fill_neighbors_kernel
) {
    if (go && !*go) return;
    sort_gather_row<false>(cell, row_ptr, sort_keys, tmp_snd, tmp_shifts, species, senders, shift_cart, order_err,
                           nullptr);
}
__global__ void sort_gather_rows_global_kernel(
    CellMat64 cell, const int* __restrict__ row_ptr, const uint32_t* __restrict__ sort_keys,
    const int* __restrict__ tmp_snd, const int* __restrict__ tmp_shifts, const int* __restrict__ species,
    int* __restrict__ senders, double* __restrict__ shift_cart,
    int* __restrict__ order_err, unsigned long long* __restrict__ scratch
) {
    sort_gather_row<true>(cell, row_ptr, sort_keys, tmp_snd, tmp_shifts, species, senders, shift_cart, order_err,
                          scratch);
}

__global__ void compute_and_count_active_kernel(
    int N, float r_max,
    const double* __restrict__ pos64,
    const int* __restrict__ row_ptr,
    const int* __restrict__ senders,
    const double* __restrict__ shift_cart,
    float4* __restrict__ tmp_vec_len,
    int* __restrict__ act_deg
) {
    const int tid = blockIdx.x * blockDim.x + threadIdx.x;
    const int i = tid >> 5;
    const int lane = tid & 31;
    if (i >= N) return;
    if (i == 0 && lane == 0) act_deg[N] = 0;
    const int eb = row_ptr[i];
    const int ee = row_ptr[i + 1];
    const double rx = pos64[i * 3 + 0];
    const double ry = pos64[i * 3 + 1];
    const double rz = pos64[i * 3 + 2];
    int count = 0;
    for (int base = eb; base < ee; base += 32) {
        const int e = base + lane;
        bool act = false;
        if (e < ee) {
            const int s = senders[e];
            const double vx = (rx - pos64[s * 3 + 0]) + shift_cart[e * 3 + 0];
            const double vy = (ry - pos64[s * 3 + 1]) + shift_cart[e * 3 + 1];
            const double vz = (rz - pos64[s * 3 + 2]) + shift_cart[e * 3 + 2];
            const float fx = (float)vx, fy = (float)vy, fz = (float)vz;
            const float len = sqrtf(fx * fx + fy * fy + fz * fz);
            tmp_vec_len[e] = make_float4(fx, fy, fz, len);
            act = (len < r_max);
        }
        const unsigned mask = __ballot_sync(0xffffffffu, act);
        count += __popc(mask);
    }
    if (lane == 0) act_deg[i] = count;
}

// Compacts the active edges (r < r_max) of each receiver row, in row order, with their spline locator. Row i holds the
// edges whose receiver is i, so neither the receiver nor the pair index is stored per candidate edge. The SH of an
// edge are not stored: its consumers compute them from act_vec_len where they stage the edge (edge_sh16).
__global__ void scatter_active_edges_kernel(
    int N, float r_max, SplineGrid grid, int S, int pair_sym,
    const int* __restrict__ species,
    const int* __restrict__ row_ptr,
    const int* __restrict__ act_row_ptr,
    const int* __restrict__ senders,
    const float4* __restrict__ tmp_vec_len,
    int* __restrict__ act_senders,
    int* __restrict__ act_receivers,
    float4* __restrict__ act_vec_len,
    int* __restrict__ act_slab,
    float2* __restrict__ act_t_sx
) {
    const int tid = blockIdx.x * blockDim.x + threadIdx.x;
    const int i = tid >> 5;
    const int lane = tid & 31;
    if (i >= N) return;
    const int eb = row_ptr[i];
    const int ee = row_ptr[i + 1];
    int out_cursor = act_row_ptr[i];
    const int sp_i = species[i];
    for (int base = eb; base < ee; base += 32) {
        const int e = base + lane;
        bool act = false;
        float4 vl = make_float4(0.0f, 0.0f, 0.0f, 0.0f);
        if (e < ee) {
            vl = __ldg(tmp_vec_len + e);
            act = (vl.w < r_max);
        }
        const unsigned mask = __ballot_sync(0xffffffffu, act);
        if (act) {
            const int dst = out_cursor + __popc(mask & ((1u << lane) - 1u));
            const int snd = senders[e];
            const int p_slab = table_pair(pair_sym, species[snd], sp_i, S);
            act_senders[dst] = snd;
            act_receivers[dst] = i;
            act_vec_len[dst] = vl;
            // Fused spline locator (the PRELOC conv kernels' table slab and t)
            int iv;
            float t, sx_inv;
            locate_spline(grid, vl.w, iv, t, sx_inv);
            act_slab[dst] = p_slab * grid.total_intervals + iv;
            act_t_sx[dst] = make_float2(t, (vl.w >= grid.starts[0]) ? sx_inv : -sx_inv);
        }
        out_cursor += __popc(mask);
    }
}

// The list built at ref_pos64 holds every pair within r_max + skin then, so it stays complete while every atom has
// moved at most skin/2. Sets *need_rebuild when some atom has moved further (always at skin 0); every force pass of
// the MD loop follows its own check, and a rebuild clears the flag.
__global__ void check_skin_kernel(
    int N, double half_skin,
    const double* __restrict__ pos64,
    const double* __restrict__ ref_pos64,
    int* __restrict__ need_rebuild
) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= N) return;
    double dx = pos64[i * 3 + 0] - ref_pos64[i * 3 + 0];
    double dy = pos64[i * 3 + 1] - ref_pos64[i * 3 + 1];
    double dz = pos64[i * 3 + 2] - ref_pos64[i * 3 + 2];
    const double d2 = dx * dx + dy * dy + dz * dz;
    if (half_skin <= 0.0 || d2 > half_skin * half_skin) *need_rebuild = 1;
}

void compute_cell_mat(const double* cell_row_major, CellMat64& out, double& out_vol, double heights[3]) {
    for (int i = 0; i < 9; ++i) out.c[i] = cell_row_major[i];
    const double* a = out.c;
    // Cofactors for transpose inverse
    double c00 = a[4] * a[8] - a[5] * a[7];
    double c01 = a[5] * a[6] - a[3] * a[8];
    double c02 = a[3] * a[7] - a[4] * a[6];
    double c10 = a[7] * a[2] - a[8] * a[1];
    double c11 = a[8] * a[0] - a[6] * a[2];
    double c12 = a[6] * a[1] - a[7] * a[0];
    double c20 = a[1] * a[5] - a[2] * a[4];
    double c21 = a[2] * a[3] - a[0] * a[5];
    double c22 = a[0] * a[4] - a[1] * a[3];
    double det = a[0] * c00 + a[1] * c01 + a[2] * c02;
    out_vol = fabs(det);
    double inv_det = 1.0 / det;
    // out.inv = a^{-1} = cof^T / det
    out.inv[0] = c00 * inv_det; out.inv[1] = c10 * inv_det; out.inv[2] = c20 * inv_det;
    out.inv[3] = c01 * inv_det; out.inv[4] = c11 * inv_det; out.inv[5] = c21 * inv_det;
    out.inv[6] = c02 * inv_det; out.inv[7] = c12 * inv_det; out.inv[8] = c22 * inv_det;

    double area0 = sqrt(c00 * c00 + c01 * c01 + c02 * c02);
    double area1 = sqrt(c10 * c10 + c11 * c11 + c12 * c12);
    double area2 = sqrt(c20 * c20 + c21 * c21 + c22 * c22);
    heights[0] = out_vol / area0;
    heights[1] = out_vol / area1;
    heights[2] = out_vol / area2;
}

}  // namespace loup
