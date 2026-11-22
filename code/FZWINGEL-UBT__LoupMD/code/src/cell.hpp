#pragma once
// The variable cell of a run (plan task S4-T06). While an integrator may change the cell, the cell is a struct on
// the device that the captured step reads and writes; the host's copy follows at every neighbour rebuild and at
// the end of the call. Conventions as everywhere in the engine: row-major 3 x 3, rows are the cell vectors,
// positions are row vectors, x = s h for fractional s.
#include <cuda_runtime.h>

namespace loup {

struct CellDev {
    double h[9];        // the cell now
    double ref_inv[9];  // inverse of the cell the neighbour list was built in
    double f[9];        // ref_inv h: a position x0 of then has moved with the cell to x0 f
    double move[9];     // this step's deformation, set by whoever moves the cell: h <- h move, x <- x move
    double row_scale[3];// has_move == 2: the cell's vectors are scaled, h[a] <- row_scale[a] h[a] (exact for a
                        // factor of 1), while the atoms still go x <- x move with move = h^-1 diag(row_scale) h
    double thr;         // the list holds every pair while no atom is further than this from its x0 f
    double volume;      // |det h| in A^3
    double v0;          // the trajectory's first volume: the run stops outside [v0 / 20, 20 v0]
    double r_list;      // r_max + skin: what the list was built to
    double r_max;
    int has_move;       // 0: no deformation in this step; 1: move; 2: row_scale for the cell, move for the atoms
    int pad;
};

// Testing (LOUP_DEBUG_CELL_RATE): this step's deformation is (1 + rate) times the identity. One thread.
__global__ void cell_debug_rate_kernel(double rate, CellDev* __restrict__ cell);

// x <- x move for every atom, if a deformation is set for this step.
__global__ void cell_move_positions_kernel(int N, const CellDev* __restrict__ cell, double* __restrict__ pos64);

// One thread, after the positions: h <- h move, or its vectors scaled (and the deformation is cleared), then what the step needs from
// the cell: f, the volume and the list check's threshold. With F = f the pair vector of the list's reference,
// r0, has become r0 F + u_j - u_i, where u is an atom's displacement from its x0 f; a pair that was outside the
// list (|r0| > r_list) is still outside r_max while sigma_min(F) r_list - 2 max|u| >= r_max, and
// sigma_min(F) >= 1 - |F - 1| (Frobenius norm). So thr = (r_list (1 - |F - 1|) - r_max) / 2, which is half the
// skin for an undeformed cell. Sets bit 8 of need_rebuild when the volume has left [v0 / 20, 20 v0] or is not
// finite.
__global__ void cell_derive_kernel(CellDev* __restrict__ cell, int* __restrict__ need_rebuild);

// check_skin_kernel for a variable cell: the displacement is measured from where the cell's deformation has taken
// the list's reference position, and the threshold is cell->thr. Sets bit 1 of need_rebuild, as check_skin_kernel.
__global__ void check_skin_cell_kernel(int N, const double* __restrict__ pos64, const double* __restrict__ ref_pos64,
                                       const CellDev* __restrict__ cell, int* __restrict__ need_rebuild);

// In every step: shift_cart = shift h, as sort_gather_rows_kernel forms it at a rebuild, from the edges' integer
// image shifts (cell_shift_codes_kernel). The launch covers the edge bucket a captured graph is made for; n_edges[0]
// is the list's edge count now.
__global__ void shift_cart_kernel(const int* __restrict__ n_edges, const CellDev* __restrict__ cell,
                                  const char4* __restrict__ code, double* __restrict__ shift_cart);

// Berendsen NPT (ASE 3.27's NPTBerendsen and Inhomogeneous_NPTBerendsen), between the thermostat's scale and
// the half-kick. kinetic_diag_kernel sums m v_a^2 per axis into out[0..2] (the ideal-gas part of the stress's
// diagonal; the caller's accumulators, zeroed by berendsen_npt_kernel). berendsen_npt_kernel, one thread, reads
// the thermostat's lambda (work[1]) and the kinetic energy it was made from (work[5]), the virial of the last
// force pass and the cell's volume, and sets this step's deformation:
//   hydrostatic: every length times 1 - dt / taup * kappa / 3 * (P0 - P), P = -trace(stress) / 3;
//   full (the mask's axes): cell vector a times 1 - dt * kappa / taup / 3 * (P0 + stress_aa) mask_a; angles stay;
// with stress = virial / V - lambda^2 sum(m v v) / V, ASE's get_stress(include_ideal_gas=True) after its
// velocity scaling. pressure in eV/A^3, compressibility in A^3/eV.
__global__ void kinetic_diag_kernel(int N, const double* __restrict__ masses, const double* __restrict__ vel64,
                                    double* __restrict__ out);
__global__ void berendsen_npt_kernel(int full, int mask_x, int mask_y, int mask_z, double pressure, double dt,
                                     double taup, double compressibility, double* __restrict__ work,
                                     const double* __restrict__ virial, CellDev* __restrict__ cell);

// x <- x m for every atom (loup_set_cell with scale_atoms: m = old cell^-1 new cell).
struct Mat3 {
    double m[9];
};
__global__ void positions_times_matrix_kernel(int N, Mat3 m, double* __restrict__ pos64);

// At a rebuild (nl_finish): each edge's integer image shift n = rint(shift_cart inv), inv the list's cell's inverse
// (frac = x inv), into code (x, y, z); sets *bad when a component does not fit a signed byte.
__global__ void cell_shift_codes_kernel(int E, Mat3 inv, const double* __restrict__ shift_cart,
                                        char4* __restrict__ code, int* __restrict__ bad);

}  // namespace loup
