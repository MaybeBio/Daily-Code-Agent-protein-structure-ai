#include "loupmd.h"
#include "model.hpp"
#include "kernels_common.cuh"
#include "generic.hpp"
#include "bundle.hpp"
#include "thermo.hpp"
#include "cell.hpp"
#include "tiled.hpp"
#include "dispersion/term.hpp"
#include <cstddef>

#include <cub/cub.cuh>
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <dlfcn.h>
#include <sys/stat.h>
#include <unistd.h>
#include <cuda.h>
#include <cublasLt.h>
#include <type_traits>
#include <map>
#include <memory>
#include <mutex>
#include <shared_mutex>
#include <chrono>
#include <functional>
#include <tuple>
#include <algorithm>
#include <cmath>
#include <initializer_list>
#include <limits>
#include <cstring>
#include <atomic>
#include <future>
#include <thread>
#include <vector>
#include <stdexcept>

// Defined in neighbors.cu & integrator.cu (compiled into same or linked translation units;
// we include or forward-declare cleanly here).
namespace loup {
struct CellMat64 {
    double c[9];
    double inv[9];
};
void compute_cell_mat(const double* cell_row_major, CellMat64& out, double& out_vol, double heights[3]);

__global__ void wrap_and_bin_kernel(int N, CellMat64 cell, int nx, int ny, int nz,
                                    const double* __restrict__ pos64, double* __restrict__ pos_wrapped,
                                    int* __restrict__ atom_wrap, int* __restrict__ atom_bin,
                                    int* __restrict__ bin_counts);
__global__ void atom_order_keys_kernel(int N, int nx, int ny, int nz, const int* __restrict__ species,
                                       const int* __restrict__ atom_bin, unsigned long long* __restrict__ keys,
                                       int* __restrict__ vals);
__global__ void gather_rows_f64_kernel(int n, int width, const int* __restrict__ order,
                                       const double* __restrict__ src, double* __restrict__ dst);
__global__ void scatter_bins_kernel(int N, const double* __restrict__ pos_wrapped,
                                    const int* __restrict__ atom_wrap, const int* __restrict__ species,
                                    const int* __restrict__ atom_bin, int* __restrict__ bin_cursor,
                                    int* __restrict__ bin_atom_id, double* __restrict__ bin_pos, float4* __restrict__ bin_pos_f32,
                                    int* __restrict__ bin_wrap, int* __restrict__ bin_sp);
__global__ void count_neighbors_kernel(int N, CellMat64 cell, int nx, int ny, int nz,
                                       int rx, int ry, int rz, double r_list2, float r_lo2_f32, float r_hi2_f32,
                                       const double* __restrict__ pos_wrapped, const int* __restrict__ atom_bin,
                                       const int* __restrict__ bin_offsets, const int* __restrict__ bin_atom_id,
                                       const double* __restrict__ bin_pos, const float4* __restrict__ bin_pos_f32, int* __restrict__ deg);
__global__ void fill_neighbors_kernel(int N, int S, CellMat64 cell, int nx, int ny, int nz,
                                      int rx, int ry, int rz, double r_list2, float r_lo2_f32, float r_hi2_f32,
                                      const double* __restrict__ pos_wrapped, const int* __restrict__ atom_wrap,
                                      const int* __restrict__ species, const int* __restrict__ atom_bin,
                                      const int* __restrict__ bin_offsets, const int* __restrict__ bin_atom_id,
                                      const double* __restrict__ bin_pos, const float4* __restrict__ bin_pos_f32,
                                      const int* __restrict__ bin_wrap,
                                      const int* __restrict__ bin_sp, const int* __restrict__ row_ptr,
                                      int* __restrict__ tmp_snd, int* __restrict__ tmp_shifts,
                                      uint32_t* __restrict__ sort_keys, const int* __restrict__ go);
__global__ void count_neighbors_scalar_kernel(int N, CellMat64 cell, int nx, int ny, int nz,
                                              int rx, int ry, int rz, double r_list2, float r_lo2_f32, float r_hi2_f32,
                                              const double* __restrict__ pos_wrapped, const int* __restrict__ atom_bin,
                                              const int* __restrict__ bin_offsets, const int* __restrict__ bin_atom_id,
                                              const double* __restrict__ bin_pos, const float4* __restrict__ bin_pos_f32,
                                              int* __restrict__ deg);
__global__ void fill_neighbors_scalar_kernel(int N, int S, CellMat64 cell, int nx, int ny, int nz,
                                             int rx, int ry, int rz, double r_list2, float r_lo2_f32, float r_hi2_f32,
                                             const double* __restrict__ pos_wrapped, const int* __restrict__ atom_wrap,
                                             const int* __restrict__ species, const int* __restrict__ atom_bin,
                                             const int* __restrict__ bin_offsets, const int* __restrict__ bin_atom_id,
                                             const double* __restrict__ bin_pos, const float4* __restrict__ bin_pos_f32,
                                             const int* __restrict__ bin_wrap,
                                             const int* __restrict__ bin_sp, const int* __restrict__ row_ptr,
                                             int* __restrict__ tmp_snd, int* __restrict__ tmp_shifts,
                                             uint32_t* __restrict__ sort_keys, const int* __restrict__ go);
__global__ void max_degree_kernel(int N, const int* __restrict__ deg, int* __restrict__ out);
__global__ void sort_gather_rows_kernel(
    CellMat64 cell, const int* __restrict__ row_ptr, const uint32_t* __restrict__ sort_keys,
    const int* __restrict__ tmp_snd, const int* __restrict__ tmp_shifts, const int* __restrict__ species,
    int* __restrict__ senders, double* __restrict__ shift_cart,
    int* __restrict__ order_err, const int* __restrict__ go);
__global__ void sort_gather_rows_global_kernel(
    CellMat64 cell, const int* __restrict__ row_ptr, const uint32_t* __restrict__ sort_keys,
    const int* __restrict__ tmp_snd, const int* __restrict__ tmp_shifts, const int* __restrict__ species,
    int* __restrict__ senders, double* __restrict__ shift_cart,
    int* __restrict__ order_err, unsigned long long* __restrict__ scratch);
__global__ void compute_and_count_active_kernel(
    int N, float r_max, const double* __restrict__ pos64,
    const int* __restrict__ row_ptr, const int* __restrict__ senders, const double* __restrict__ shift_cart,
    float4* __restrict__ tmp_vec_len, int* __restrict__ act_deg);
__global__ void scatter_active_edges_kernel(
    int N, float r_max, SplineGrid grid, int S, int pair_sym, const int* __restrict__ species,
    const int* __restrict__ row_ptr, const int* __restrict__ act_row_ptr,
    const int* __restrict__ senders, const float4* __restrict__ tmp_vec_len,
    int* __restrict__ act_senders, int* __restrict__ act_receivers,
    float4* __restrict__ act_vec_len,
    int* __restrict__ act_slab, float2* __restrict__ act_t_sx);
__global__ void check_skin_kernel(int N, double half_skin, const double* __restrict__ pos64,
                                  const double* __restrict__ ref_pos64, int* __restrict__ need_rebuild);
// Publications to mapped pinned host memory: the next value of a device counter selects one of four slots (so two
// publications of one MD step cannot overwrite each other before the host reads them), the slot gets the three
// values and then the counter value, which the host polls (wait_published) instead of calling cudaStreamSynchronize,
// whose wake-up leaves the GPU idle for 0.1-0.2 ms under WSL2. One thread; a stream-ordered (or graph-ordered)
// launch sees every earlier write of the stream.
__device__ __forceinline__ void publish3(unsigned int* counter, int* pub, int a, int b, int c) {
    const unsigned int seq = *counter + 1u;
    *counter = seq;
    volatile int* p = pub + 4 * (seq & 3u);
    p[1] = a;
    p[2] = b;
    p[3] = c;
    __threadfence_system();
    reinterpret_cast<volatile unsigned int*>(p)[0] = seq;
}

__global__ void publish_kernel(const int* __restrict__ a, const int* __restrict__ b, const int* __restrict__ c,
                               unsigned int* __restrict__ counter, int* __restrict__ pub) {
    publish3(counter, pub, a ? *a : 0, b ? *b : 0, c ? *c : 0);
}

// The MD step's hinge (run_md_loop): publishes the skin-check flag and the last rebuild's row-order flag, and picks the
// body of the step graph's SWITCH node: 0 the rest (force pass + second half) when no rebuild is needed, 1 the rebuild
// branch (has_rebuild) when one is, none when the rows are invalid or the host rebuilds. The host queues the next step
// while this one's forces run instead of reading the flag at an idle GPU. One SWITCH node rather than an IF node per
// body: every conditional node a step evaluates costs time even when its body does not run.
__global__ void guard_step_kernel(cudaGraphConditionalHandle cond, int has_rebuild, const int* __restrict__ need_rebuild,
                                  const int* __restrict__ order_err, unsigned int* __restrict__ counter,
                                  int* __restrict__ pub) {
    const int flag = *need_rebuild;
    const int bad_rows = *order_err;
    publish3(counter, pub, flag, bad_rows, 0);
    cudaGraphSetConditional(cond, bad_rows ? 2u : !flag ? 0u : has_rebuild ? 1u : 2u);
}

// The step graph's rebuild branch after nl_count: publishes the edge count, the longest row and whether the new list
// fits what the graph was captured for (edge capacity / bucket, row-sort width), and stores that verdict in *go: the
// branch's fill, sort and commit kernels run only then (one nesting level less than an IF node around them);
// otherwise the host finishes the rebuild.
__global__ void rebuild_gate_kernel(const int* __restrict__ row_ptr_end, const int* __restrict__ max_deg, int E_lim,
                                    int P_cap, int* __restrict__ go, unsigned int* __restrict__ counter,
                                    int* __restrict__ pub) {
    const int E = *row_ptr_end;
    const int m = *max_deg;
    const int fits = E > 0 && E <= E_lim && m <= P_cap;
    *go = fits;
    publish3(counter, pub, E, m, fits);
}

// After a rebuild in MD: the force pass (the IF node's body) runs only if the rebuild's rows passed the order check,
// which the host reads with the next step's publication, and (go, the step graph's rebuild branch) were built.
__global__ void rest_guard_kernel(cudaGraphConditionalHandle cond, const int* __restrict__ order_err,
                                  const int* __restrict__ go) {
    cudaGraphSetConditional(cond, (*order_err || (go && !*go)) ? 0u : 1u);
}

// Neighbour-rebuild bookkeeping (nl_bin, nl_count, nl_commit) as kernels rather than memset / memcpy nodes.
__global__ void nl_reset_kernel(int n_bins, int* __restrict__ bin_counts, int* __restrict__ deg_end,
                                int* __restrict__ order_err, int* __restrict__ max_deg) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i <= n_bins) bin_counts[i] = 0;  // [n_bins] too: the bin scan's total
    if (i == 0) {
        *deg_end = 0;  // the row scan's total
        *order_err = 0;
        *max_deg = 0;
    }
}

__global__ void copy_ints_kernel(int n, const int* __restrict__ src, int* __restrict__ dst) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n) dst[i] = src[i];
}

__global__ void nl_commit_kernel(int n, const double* __restrict__ pos, double* __restrict__ ref_pos,
                                 int* __restrict__ need_rebuild, const int* __restrict__ go) {
    if (go && !*go) return;
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n) ref_pos[i] = pos[i];
    if (i == 0) *need_rebuild = 0;
}

constexpr double ASE_FS = 0.09822694788464063;
constexpr double ASE_KB = 8.617330337217213e-5;
constexpr double GPA_PER_EV_A3 = 160.21766208;  // ASE: 1 / units.GPa

__global__ void nve_first_half_kernel(int N, double dt_ase, const double* __restrict__ forces,
                                      const double* __restrict__ inv_masses,
                                      double* __restrict__ pos64, double* __restrict__ vel64,
                                      unsigned int* __restrict__ max_step_disp2);
__global__ void nve_second_half_kernel(int N, double dt_ase, const double* __restrict__ forces,
                                       const double* __restrict__ inv_masses, double* __restrict__ vel64);
__global__ void rotate_step_disp_kernel(unsigned int* __restrict__ max_step_disp2);
__global__ void langevin_first_half_kernel(
    int N, double dt_ase, double c1, double c2,
    const double* __restrict__ target, unsigned long long seed, const unsigned long long* __restrict__ step_counter,
    const double* __restrict__ forces, const double* __restrict__ inv_masses,
    const double* __restrict__ sqrt_inv_masses, double* __restrict__ pos64,
    double* __restrict__ vel64, double* __restrict__ rnd_vel_save, unsigned int* __restrict__ max_step_disp2);
__global__ void langevin_second_half_kernel(
    int N, double c1, double c2, const double* __restrict__ forces,
    const double* __restrict__ inv_masses, const double* __restrict__ rnd_vel_save,
    double* __restrict__ vel64, unsigned long long* __restrict__ step_counter, double* __restrict__ target,
    double a3, double a4, double a5, double two_fr_kb);
__global__ void langevin_noise_kernel(
    int N, const double* __restrict__ target,
    unsigned long long seed, const unsigned long long* __restrict__ step_counter,
    const double* __restrict__ masses, const double* __restrict__ sqrt_inv_masses,
    double* __restrict__ rnd_pos, double* __restrict__ rnd_vel, double* __restrict__ com);
__global__ void langevin_first_half_fixcom_kernel(
    int N, double dt_ase, double c1, double c2, double inv_total_mass, const double* __restrict__ com,
    const double* __restrict__ forces, const double* __restrict__ inv_masses, const double* __restrict__ rnd_pos,
    double* __restrict__ rnd_vel, double* __restrict__ pos64, double* __restrict__ vel64,
    unsigned int* __restrict__ max_step_disp2);
__global__ void momentum_sum_kernel(int N, const double* __restrict__ masses, const double* __restrict__ vel64,
                                    double* __restrict__ com);
__global__ void momentum_remove_kernel(int N, double inv_total_mass, const double* __restrict__ com,
                                       double* __restrict__ vel64);
__global__ void kinetic_energy_kernel(int N, const double* __restrict__ masses,
                                      const double* __restrict__ vel64, double* __restrict__ out_ke);
__global__ void min_gradient_kernel(
    int N, int have_previous, const double* __restrict__ forces, const double* __restrict__ inv_masses,
    const double* __restrict__ pos64, const double* __restrict__ x0, const double* __restrict__ g0,
    double* __restrict__ g, double* __restrict__ s_row, double* __restrict__ y_row,
    unsigned long long* __restrict__ out_fmax2);
__global__ void lbfgs_products_kernel(
    int n3, int stride, const double* __restrict__ S, const double* __restrict__ Y, const double* __restrict__ g,
    const double* __restrict__ s_new, const double* __restrict__ y_new, double* __restrict__ out);
__global__ void lbfgs_direction_kernel(
    int N, int rows, int stride, double h0, const int* __restrict__ row_index, const double* __restrict__ u,
    const double* __restrict__ w, const double* __restrict__ S, const double* __restrict__ Y,
    const double* __restrict__ g, double* __restrict__ p, unsigned long long* __restrict__ out_len2);
__global__ void lbfgs_move_kernel(
    int N, double maxstep, double damping, const unsigned long long* __restrict__ len2,
    const double* __restrict__ p, const double* __restrict__ g, double* __restrict__ pos64,
    double* __restrict__ x0, double* __restrict__ g0);
__global__ void max_displacement2_kernel(int N, const double* __restrict__ pos64,
                                         const double* __restrict__ ref_pos64,
                                         unsigned long long* __restrict__ out_disp2);
__global__ void csvr_noise_debug_kernel(unsigned long long seed, unsigned long long first_step, int n, int ndof,
                                        double* __restrict__ normal, double* __restrict__ chi2);
__global__ void csvr_alpha_kernel(int ndof, double exp_term, double kb, unsigned long long seed,
                                  unsigned long long* __restrict__ step_counter, double* __restrict__ target,
                                  double* __restrict__ work, double* __restrict__ state);
__global__ void nhc_half_kernel(int ndof, int tchain, int tloop, double delta, double q, double kb, int advance,
                                double* __restrict__ target, double* __restrict__ work, double* __restrict__ state);
__global__ void scale_velocities_kernel(int N, const double* __restrict__ work, double* __restrict__ vel64);
__global__ void baoab_cell_first_kernel(
    int full, double dt, double gamma, double ou_unit, double gamma_b, double ou_b_unit, double mass, int ndof,
    double kb, unsigned long long seed, const unsigned long long* __restrict__ step_counter,
    double* __restrict__ target, double* __restrict__ state, double* __restrict__ work, CellDev* __restrict__ cell);
__global__ void baoab_first_kernel(
    int N, double dt, const double* __restrict__ work, unsigned long long seed,
    const unsigned long long* __restrict__ step_counter, const double* __restrict__ forces,
    const double* __restrict__ inv_masses, const double* __restrict__ sqrt_inv_masses,
    double* __restrict__ pos64, double* __restrict__ vel64, unsigned int* __restrict__ max_step_disp2);
__global__ void kinetic_tensor_kernel(int N, const double* __restrict__ masses, const double* __restrict__ vel64,
                                      double* __restrict__ out);
__global__ void baoab_cell_second_kernel(
    int full, int kick, int advance, double dt, int ndof, double ext, const double* __restrict__ virial,
    const CellDev* __restrict__ cell, double* __restrict__ work, double* __restrict__ state,
    unsigned long long* __restrict__ step_counter);
__global__ void mtk_first_kernel(
    int full, double dt, int tchain, int tloop, int pchain, int ploop, int ndof, double q_t, double r_p, double w,
    double kb, double pressure, const double* __restrict__ target, double* __restrict__ state,
    double* __restrict__ work, const double* __restrict__ virial, CellDev* __restrict__ cell);
__global__ void mtk_first_atoms_kernel(
    int N, double dt, const double* __restrict__ work, const double* __restrict__ forces,
    const double* __restrict__ inv_masses, double* __restrict__ pos64, double* __restrict__ vel64,
    unsigned int* __restrict__ max_step_disp2);
__global__ void mtk_kick_kernel(int N, double dt, const double* __restrict__ work, const double* __restrict__ forces,
                                const double* __restrict__ inv_masses, double* __restrict__ vel64);
__global__ void mtk_second_kernel(
    int full, double dt, int tchain, int tloop, int pchain, int ploop, int ndof, double q_t, double r_p, double w,
    double kb, double pressure, double* __restrict__ target, double* __restrict__ state, double* __restrict__ work,
    const double* __restrict__ virial, const CellDev* __restrict__ cell);
__global__ void berendsen_scale_kernel(int ndof, double dt_over_tau, double kb, double* __restrict__ target,
                                       double* __restrict__ work);
__global__ void csvr_first_half_kernel(
    int N, double dt_ase, const double* __restrict__ work, const double* __restrict__ forces,
    const double* __restrict__ inv_masses, double* __restrict__ pos64, double* __restrict__ vel64,
    unsigned int* __restrict__ max_step_disp2);
}  // namespace loup

// Scalars an integrator carries from step to step and a restart needs (the state block holds all of them):
// CSVR: [0] the energy the thermostat has transferred. Nose-Hoover chain: [0] minus the chain's energy, then eta
// and p_eta of each thermostat (nhc_half_kernel). The other slots are for the integrators to come.
constexpr int kIntStateSlots = 64;
constexpr int kIntWorkSlots = 64;  // per-step scratch: CSVR's kinetic energy and alpha; BAOAB NPT's matrices

// loup_minimize's LBFGS (src/minimize.cu). The history and the step's vectors are on the device in the handle's
// atom order; the host keeps what the two triangular solves need. It is valid for the positions the last call
// left (pos_epoch), with the settings of that call.
struct MinState {
    bool valid = false;
    unsigned long long epoch = 0;   // LoupHandle::pos_epoch the state belongs to
    double maxstep = 0.0, damping = 0.0, alpha = 0.0;
    int memory = 0;
    int n3 = 0;                     // 3 N of the buffers
    int count = 0;                  // pairs in the history (rows 0 .. count - 1)
    int head = 0;                   // the row the next pair goes to
    long long iteration = 0;        // steps taken
    std::vector<int> order;         // history rows, oldest first
    std::vector<double> rho;        // [memory]: 1 / (y_i . s_i)
    std::vector<double> gram;       // [memory, memory]: s_i . y_j
    std::vector<double> yy;         // [memory, memory]: y_i . y_j
    double* d_S = nullptr;          // [memory, n3]
    double* d_Y = nullptr;          // [memory, n3]
    double* d_vec = nullptr;        // [4, n3]: g, g0, x0, p
    double* d_small = nullptr;      // [7 memory]: the five products per row, then u and w
    int* d_rows = nullptr;          // [memory]: the rows of u and w
    // [3], bits of doubles: the largest squared force, the largest squared length of the last direction, the
    // largest squared displacement from the neighbour list's reference after the last move
    unsigned long long* d_max = nullptr;
    // Pinned host memory, so that no copy waits for the host: d_max's three values, the energy, the five products
    // per row, then u and w; and the rows of u and w.
    double* h_pin = nullptr;        // [4 + 7 memory]
    int* h_rows = nullptr;          // [memory]
    // What the list check of the next move goes by (minimize_impl): the largest displacement from the list's
    // reference at the current positions and the longest step of an atom in the last move; -1: not known.
    double disp_known = -1.0, step_known = -1.0;
    void release() {
        auto freep = [](auto*& p) {
            if (p) { cudaFree(p); p = nullptr; }
        };
        freep(d_S); freep(d_Y); freep(d_vec); freep(d_small); freep(d_rows); freep(d_max);
        if (h_pin) { cudaFreeHost(h_pin); h_pin = nullptr; }
        if (h_rows) { cudaFreeHost(h_rows); h_rows = nullptr; }
        valid = false;
        n3 = 0;
    }
};

// FNV-1a over a file's bytes (0 if unreadable).
static uint64_t fnv1a_file(const char* path) {
    FILE* fp = fopen(path, "rb");
    if (!fp) return 0;
    uint64_t hsh = 1469598103934665603ULL;
    std::vector<unsigned char> buf(1 << 16);
    size_t n;
    while ((n = fread(buf.data(), 1, buf.size(), fp)) > 0)
        for (size_t i = 0; i < n; ++i) hsh = (hsh ^ buf[i]) * 1099511628211ULL;
    fclose(fp);
    return hsh ? hsh : 1;
}

// Tensor-core GEMM cubin (GEMM autotune candidates). Two formats: the shipped FastMACE builds (cubins/tf32x3_hyb_*,
// fm_tf32x3_info: tiles 64x64, 32x64, 64x32, beta 0 only) and LoupMD's own (cubins/src/gemm_tc.cu,
// loup_gemm_tc_info: math, beta support and up to kMaxTiles tiles; through LOUP_HYBRID_CUBIN for now). Tiles 0-2 are
// the same shapes in both, so a stored plan's tile index means the same kernel shape. Own format 1 passes beta at run
// time to every entry; format 2 fixes it at 0 in the plain entries (tiles 0-2 SASS-identical to the FastMACE ones)
// and adds loup_gemm_tc_{rrb,rcb}_<t> for beta != 0.
struct HybCubin {
    static constexpr int kMaxTiles = 8;
    bool loaded = false;
    bool own_format = false;  // loup_gemm_tc_info
    bool beta_ok = false;     // C = A B + beta C may use it
    int ntiles = 0;
    uint64_t cubin_hash = 0;  // the loaded cubin file's FNV-1a hash (keys the GEMM plan cache)
    std::string path_loaded;  // for diagnostics (the cubin's math: its build, see cubins/src)
    void* lib = nullptr;
    CUmodule mod = nullptr;
    CUfunction fn[kMaxTiles][2] = {};   // [tile][transB ? 1 : 0]: C = A B (format 1: any beta)
    CUfunction fnb[kMaxTiles][2] = {};  // beta != 0 (format 1: the fn entries)
    int threads[kMaxTiles] = {};
    int smem[kMaxTiles][2] = {};
    int tile_m[kMaxTiles] = {};
    int tile_n[kMaxTiles] = {};
    CUresult (*p_cuModuleLoad)(CUmodule*, const char*) = nullptr;
    CUresult (*p_cuModuleUnload)(CUmodule) = nullptr;
    CUresult (*p_cuModuleGetFunction)(CUfunction*, CUmodule, const char*) = nullptr;
    CUresult (*p_cuModuleGetGlobal)(CUdeviceptr*, size_t*, CUmodule, const char*) = nullptr;
    CUresult (*p_cuMemcpyDtoH)(void*, CUdeviceptr, size_t) = nullptr;
    CUresult (*p_cuFuncSetAttribute)(CUfunction, CUfunction_attribute, int) = nullptr;
    CUresult (*p_cuLaunchKernel)(CUfunction, unsigned, unsigned, unsigned, unsigned, unsigned, unsigned, unsigned, CUstream, void**, void**) = nullptr;

    void init(int device_id) {
        const char* no_hyb = std::getenv("LOUP_NO_HYBRID");
        if (no_hyb && no_hyb[0] == '1') return;
        int maj = 0, min = 0;
        if (cudaDeviceGetAttribute(&maj, cudaDevAttrComputeCapabilityMajor, device_id) != cudaSuccess) return;
        if (cudaDeviceGetAttribute(&min, cudaDevAttrComputeCapabilityMinor, device_id) != cudaSuccess) return;
        const char* cname = nullptr;
        // cc 8.0 (A100): LoupMD's own format-2 cubin (cubins/src/gemm_tc.cu: the shipped three tiles SASS-identical
        // plus three larger ones and compile-time beta variants), faster or equal on every family measured (S74a) and
        // gated (S75g); other 8.x GPUs, not measured with it, keep the FastMACE cubin.
        if (maj == 8) cname = (min == 0) ? "gemm_tc_hyb_sm80.cubin" : "tf32x3_hyb_sm80.cubin";
        else if (maj == 9) cname = "tf32x3_hyb_sm90.cubin";
        else if (maj == 12) cname = "tf32x3_hyb_sm120.cubin";
        else return;

        std::string path;
        if (const char* envp = std::getenv("LOUP_HYBRID_CUBIN")) {
            path = envp;
        } else {
            Dl_info dli{};
            if (dladdr((void*)&loup_create, &dli) && dli.dli_fname) {
                std::string so(dli.dli_fname);
                auto slash = so.find_last_of('/');
                std::string dir = (slash == std::string::npos) ? "." : so.substr(0, slash);
                path = dir + "/cubins/" + cname;
            }
        }
        if (path.empty()) return;
        cubin_hash = fnv1a_file(path.c_str());
        path_loaded = path;
        FILE* chk = fopen(path.c_str(), "rb");
        if (!chk) return;
        fclose(chk);

        lib = dlopen("libcuda.so.1", RTLD_LAZY);
        if (!lib) return;
        auto sym = [&](auto& dst, const char* name) {
            dst = reinterpret_cast<std::decay_t<decltype(dst)>>(dlsym(lib, name));
            return dst != nullptr;
        };
        if (!sym(p_cuModuleLoad, "cuModuleLoad") ||
            !sym(p_cuModuleUnload, "cuModuleUnload") ||
            !sym(p_cuModuleGetFunction, "cuModuleGetFunction") ||
            !sym(p_cuModuleGetGlobal, "cuModuleGetGlobal_v2") ||
            !sym(p_cuMemcpyDtoH, "cuMemcpyDtoH_v2") ||
            !sym(p_cuFuncSetAttribute, "cuFuncSetAttribute") ||
            !sym(p_cuLaunchKernel, "cuLaunchKernel")) {
            return;
        }
        if (p_cuModuleLoad(&mod, path.c_str()) != CUDA_SUCCESS) { mod = nullptr; return; }
        CUdeviceptr gptr = 0; size_t gsz = 0;
        if (p_cuModuleGetGlobal(&gptr, &gsz, mod, "loup_gemm_tc_info") == CUDA_SUCCESS && gsz >= 4 * sizeof(int)) {
            std::vector<int> info(gsz / sizeof(int));
            if (p_cuMemcpyDtoH(info.data(), gptr, gsz) != CUDA_SUCCESS || (info[0] != 1 && info[0] != 2)) {
                destroy();
                return;
            }
            own_format = true;
            beta_ok = info[2] != 0;
            ntiles = info[3];
            if (ntiles < 1 || ntiles > kMaxTiles || (int)info.size() < 4 + 5 * ntiles) { destroy(); return; }
            for (int t = 0; t < ntiles; ++t) {
                const int* ti = &info[4 + 5 * t];
                tile_m[t] = ti[0]; tile_n[t] = ti[1]; threads[t] = ti[2]; smem[t][0] = ti[3]; smem[t][1] = ti[4];
                for (int b = 0; b < 2; ++b) {
                    char name[48];
                    snprintf(name, sizeof(name), "loup_gemm_tc_%s_%d", b ? "rc" : "rr", t);
                    if (p_cuModuleGetFunction(&fn[t][b], mod, name) != CUDA_SUCCESS) { destroy(); return; }
                    fnb[t][b] = fn[t][b];
                    if (beta_ok && info[0] == 2) {
                        snprintf(name, sizeof(name), "loup_gemm_tc_%s_%d", b ? "rcb" : "rrb", t);
                        if (p_cuModuleGetFunction(&fnb[t][b], mod, name) != CUDA_SUCCESS) { destroy(); return; }
                    }
                }
            }
        } else {
            if (p_cuModuleGetGlobal(&gptr, &gsz, mod, "fm_tf32x3_info") != CUDA_SUCCESS || gsz < 40) {
                destroy(); return;
            }
            int info[10] = {0};
            if (p_cuMemcpyDtoH(info, gptr, sizeof(info)) != CUDA_SUCCESS) { destroy(); return; }
            ntiles = 3;
            tile_m[0] = 64; tile_n[0] = 64; tile_m[1] = 32; tile_n[1] = 64; tile_m[2] = 64; tile_n[2] = 32;
            threads[0] = info[0]; smem[0][0] = info[1]; smem[0][1] = info[2];
            threads[1] = info[5]; smem[1][0] = info[6]; smem[1][1] = info[7];
            threads[2] = info[5]; smem[2][0] = info[8]; smem[2][1] = info[9];
            const char* names[3][2] = {
                {"fm_tf32x3_rr_64x64", "fm_tf32x3_rc_64x64"},
                {"fm_tf32x3_rr_32x64", "fm_tf32x3_rc_32x64"},
                {"fm_tf32x3_rr_64x32", "fm_tf32x3_rc_64x32"},
            };
            for (int t = 0; t < 3; ++t)
                for (int b = 0; b < 2; ++b)
                    if (p_cuModuleGetFunction(&fn[t][b], mod, names[t][b]) != CUDA_SUCCESS) { destroy(); return; }
        }
        for (int t = 0; t < ntiles; ++t)
            for (int b = 0; b < 2; ++b)
                if (smem[t][b] > 48 * 1024)
                    for (CUfunction f : {fn[t][b], fnb[t][b]})
                        if (f) p_cuFuncSetAttribute(f, CU_FUNC_ATTRIBUTE_MAX_DYNAMIC_SHARED_SIZE_BYTES, smem[t][b]);
        loaded = true;
    }

    // Whether a product with this beta may run on the cubin (alpha 1 always).
    bool takes(float beta) const { return loaded && (beta == 0.0f || beta_ok); }

    void launch(int tile, bool transB, int M, int N, int K,
                const float* A, int lda, const float* B, int ldb, float* C, int ldc, float beta,
                cudaStream_t stream) const {
        void* args[10] = {
            (void*)&M, (void*)&N, (void*)&K,
            (void*)&A, (void*)&lda, (void*)&B, (void*)&ldb, (void*)&C, (void*)&ldc, (void*)&beta
        };
        unsigned gx = (unsigned)((M + tile_m[tile] - 1) / tile_m[tile]);
        unsigned gy = (unsigned)((N + tile_n[tile] - 1) / tile_n[tile]);
        CUresult rc = p_cuLaunchKernel(
            (beta != 0.0f ? fnb : fn)[tile][transB ? 1 : 0], gx, gy, 1,
            (unsigned)threads[tile], 1, 1, (unsigned)smem[tile][transB ? 1 : 0],
            (CUstream)stream, args, nullptr);  // the legacy entries take the first 9 arguments only
        if (rc != CUDA_SUCCESS) throw std::runtime_error("cuLaunchKernel hybrid failed");
    }

    void destroy() {
        if (mod && p_cuModuleUnload) { p_cuModuleUnload(mod); mod = nullptr; }
        if (lib) { dlclose(lib); lib = nullptr; }
        loaded = false;
    }
};

// The device's free and total memory, for every memory plan, budget and peak. CUDA's own figure is not enough under
// WSL2 (WDDM): it leaves out most of what other programs hold on the card. Measured on the RTX 5060 Ti (18 November
// 2026): cudaMemGetInfo gave 15.16 GiB free of 15.90 while Windows programs held 2.9 GiB (NVML: 13.1 GiB free), fell
// by what the process allocated up to 10.2 GiB held, and then by 1.2 GiB more at once. A plan made from it
// overcommits the card, and a peak read from it is 1.2 GiB too high above that step. NVML counts every program's
// memory and followed each allocation exactly: where libnvidia-ml.so.1 is there, the smaller of the two figures is
// the free memory. LOUP_NO_NVML=1 keeps CUDA's figure alone (tests).
struct NvmlMemory {
    unsigned long long total, free, used;
};
struct NvmlLib {
    void* lib = nullptr;
    int (*init)() = nullptr;
    int (*by_pci)(const char*, void**) = nullptr;
    int (*memory)(void*, NvmlMemory*) = nullptr;
    std::map<int, void*> devices;  // CUDA device index -> NVML handle (nullptr: not found)
    std::mutex lock;
    bool tried = false, ok = false;

    // Free bytes of CUDA device `dev` as NVML counts them; false where NVML is not available.
    bool free_bytes(int dev, size_t* out) {
        std::lock_guard<std::mutex> guard(lock);
        if (!tried) {
            tried = true;
            const char* off = std::getenv("LOUP_NO_NVML");
            if (!(off && off[0] == '1')) {
                lib = dlopen("libnvidia-ml.so.1", RTLD_LAZY | RTLD_LOCAL);
                if (lib) {
                    init = reinterpret_cast<int (*)()>(dlsym(lib, "nvmlInit_v2"));
                    by_pci = reinterpret_cast<int (*)(const char*, void**)>(dlsym(lib, "nvmlDeviceGetHandleByPciBusId_v2"));
                    memory = reinterpret_cast<int (*)(void*, NvmlMemory*)>(dlsym(lib, "nvmlDeviceGetMemoryInfo"));
                    ok = init && by_pci && memory && init() == 0;
                }
            }
        }
        if (!ok) return false;
        auto it = devices.find(dev);
        if (it == devices.end()) {
            int domain = 0, bus = 0, device = 0;
            void* handle = nullptr;
            char id[32];
            if (cudaDeviceGetAttribute(&domain, cudaDevAttrPciDomainId, dev) == cudaSuccess &&
                cudaDeviceGetAttribute(&bus, cudaDevAttrPciBusId, dev) == cudaSuccess &&
                cudaDeviceGetAttribute(&device, cudaDevAttrPciDeviceId, dev) == cudaSuccess) {
                std::snprintf(id, sizeof(id), "%08x:%02x:%02x.0", domain, bus, device);
                if (by_pci(id, &handle) != 0) handle = nullptr;
            }
            it = devices.emplace(dev, handle).first;
        }
        NvmlMemory m{};
        if (!it->second || memory(it->second, &m) != 0) return false;
        *out = (size_t)m.free;
        return true;
    }
};
static NvmlLib g_nvml;

static cudaError_t device_memory(size_t* free_b, size_t* total_b) {
    const cudaError_t e = cudaMemGetInfo(free_b, total_b);
    if (e != cudaSuccess) return e;
    int dev = 0;
    size_t nvml_free = 0;
    if (cudaGetDevice(&dev) == cudaSuccess && g_nvml.free_bytes(dev, &nvml_free)) *free_b = std::min(*free_b, nvml_free);
    return cudaSuccess;
}

// model.hpp. NVML's figure alone where it is there: CUDA's falls by 1.2 GiB more than allocated once a process holds
// about 10 GiB (above), which would refuse requests that fit; where NVML is missing CUDA's figure is all there is.
cudaError_t loup::device_malloc(void** p, size_t bytes) {
    *p = nullptr;
    const char* cap = std::getenv("LOUP_DEBUG_ALLOC_FREE");
    if (bytes >= ((size_t)4 << 20) || cap) {
        size_t free_b = 0, total_b = 0;
        int dev = 0;
        bool known = cudaGetDevice(&dev) == cudaSuccess && g_nvml.free_bytes(dev, &free_b);
        if (!known) known = cudaMemGetInfo(&free_b, &total_b) == cudaSuccess;
        if (cap) {
            const size_t c = (size_t)std::max(0LL, std::atoll(cap)) << 20;
            free_b = known ? std::min(free_b, c) : c;
            known = true;
        }
        if (known && bytes > free_b) {
            if (std::getenv("LOUP_DEBUG_PLAN"))
                std::fprintf(stderr, "plan debug: refused %.1f MB with %.1f MB free\n", bytes / 1048576.0,
                             free_b / 1048576.0);
            return cudaErrorMemoryAllocation;
        }
    }
    return cudaMalloc(p, bytes);
}

// FNV-1a over this library's own file: GEMM plans are keyed by it, so a rebuilt library (new kernels, other tile
// code) never reuses plans timed against an older build.
// Test overrides (LOUP_REORDER=0|1, LOUP_ROW_SORT=global, LOUP_MD_REBUILD=host|fallback): pin a path that a size
// threshold or the cadence would otherwise pick, so the tests can cover every one.
struct VariantOverrides {
    int reorder = -1;
    bool row_sort_global = false;  // neighbour rows sorted in global scratch (else only rows over 4096 edges)
    int md_rebuild = 0;  // MD rebuilds: 0 on the GPU in the step graph, 1 host-driven, 2 counted on the GPU, finished on the host
    VariantOverrides() {
        if (const char* s = std::getenv("LOUP_REORDER")) reorder = (s[0] == '1') ? 1 : (s[0] == '0') ? 0 : -1;
        if (const char* s = std::getenv("LOUP_ROW_SORT")) row_sort_global = strcmp(s, "global") == 0;
        if (const char* s = std::getenv("LOUP_MD_REBUILD")) md_rebuild = strcmp(s, "host") == 0 ? 1 : strcmp(s, "fallback") == 0 ? 2 : 0;
    }
};

static uint64_t library_build_hash() {
    static uint64_t cached = 0;
    if (cached) return cached;
    Dl_info info{};
    if (dladdr((void*)&library_build_hash, &info) && info.dli_fname) cached = fnv1a_file(info.dli_fname);
    if (!cached) cached = 1;
    return cached;
}

static uint64_t fnv1a64(const void* data, size_t n, uint64_t hsh = 1469598103934665603ULL) {
    const unsigned char* p = static_cast<const unsigned char*>(data);
    for (size_t i = 0; i < n; ++i) hsh = (hsh ^ p[i]) * 1099511628211ULL;
    return hsh;
}

namespace {
struct TiledState;
struct TiledMD;
}
struct LoupHandle;
static void release_tiled_state(LoupHandle* h);
static void release_tiled_md(LoupHandle* h);

struct LoupHandle {
    std::string last_error;  // text of the last failed call on this handle (loup_last_error); empty after a success
    int device_id = 0;
    int l2_bytes = 0;
    bool is_sm120 = false;
    // The own-SGEMM extensions (sgemm64 / sgemm32 + split-K candidates, the narrow-N rules, N-fastest rasterisation and
    // the N = 96 kernel of sgemm128): on for sm_120 (5060 Ti), and on compute capability 8.0 when no tensor-core cubin
    // is loaded (long-range models, float32 SIMT GEMMs: A100, S82: POLAR-1-S NaCl216 0.870, POLAR-1-M 0.959); with
    // the cubin they lose there (S80: OFF23-S water216 1.034, OMOL-0 1.008). LOUP_OWN_EXT=0|1 forces them (tests).
    bool own_ext = false;
    // The lane-group neighbour count / fill kernels: on for sm_120 and compute capability 8.0 (A100, S80: OFF23-S
    // water216 0.843, OFF23-M water216 0.885, MH-1 NaCl216 0.965, large cells 0.990-0.995; the same lists, so the same
    // forces); LOUP_NB_GROUPS=0|1 forces them (tests).
    bool nb_groups_ok = false;
    // LOUP_FORCE_TC=1 (tests): every GEMM the tensor-core cubin can take runs its fastest cubin tile (no cuBLASLt or own
    // SGEMM candidates), so gates cover the cubin's arithmetic on every eligible shape; no plans are loaded or saved.
    bool force_tc = false;
    // The generic path's gate in the epilogues of own-sgemm128 projections (sgemm128_gate, gemm_gate): the backward in
    // the W_2^T GEMMs, the forward of residual-free degrees l >= 1 in layer 0's lin_l GEMMs. LOUP_GATE_FUSE=0 /
    // LOUP_GATE_FUSE_FWD=0 disable them (tests).
    bool gate_fuse = true, gate_fuse_fwd = true;
    cudaStream_t stream = nullptr;
    cublasHandle_t cublas = nullptr;
    cublasLtHandle_t cublas_lt = nullptr;
    // Host polling of stream positions (loup::publish_kernel, wait_published): mapped pinned words [0] = counter,
    // [1..3] = published values; the device counter's mirror on the host.
    int* h_pub = nullptr;
    int* d_pub = nullptr;
    unsigned int* d_pub_counter = nullptr;
    unsigned int pub_count = 0;
    void* d_cublas_ws = nullptr;
    HybCubin hyb;
    size_t cublas_ws_bytes = 4 << 20;
    // Independent GEMM groups (per l, per species) run on side streams, captured as parallel graph branches, so
    // small products fill the GPU together instead of one under-filled wave after another. Each side stream has its
    // own cuBLASLt workspace. Disabled during the uncaptured autotune pass so timings are not disturbed.
    static constexpr int kSide = 8;
    cudaStream_t side[kSide] = {};
    void* side_ws[kSide] = {};
    cudaEvent_t ev_fork = nullptr;
    cudaEvent_t ev_join[kSide] = {};
    cudaStream_t gemm_stream = nullptr;  // stream sgemm_rm launches on (main stream outside fork groups)
    void* gemm_ws = nullptr;
    bool fork_ok = true;
    struct LtPlan {
        cublasLtMatmulDesc_t desc = nullptr;
        cublasLtMatrixLayout_t layA = nullptr, layB = nullptr, layC = nullptr;
        cublasLtMatmulAlgo_t algo{};
        bool use_hyb = false;
        int hyb_tile = 0;
        int own_mode = 0;      // 1 = sgemm128, 2 = sgemm64, 3..5 = sgemm32 (split_k = 1, 2, 4)
    };
    std::map<std::tuple<int, int, int, bool, bool>, LtPlan> lt_cache;
    std::map<std::tuple<const float*, int, int>, float*> bt_cache;  // [K, N] copies of transposed weights (weight_kn)
    VariantOverrides ovr;         // test overrides from the environment, read at loup_create
    bool variants_tuned = false;  // tune_rebuild_variants ran for this system
    bool variants_early = false;  // tune_early_variants ran for this system (no rebuild came first)
    long long passes_untuned = 0; // force passes on this system before its variants were timed (tune_early_variants)
    struct DiskPlan {
        int M, N, K;
        uint8_t transB, beta_nz, use_hyb, hyb_tile, use_own;
        cublasLtMatmulAlgo_t algo;
    };
    std::string plan_cache_path;
    std::map<std::tuple<int, int, int, bool, bool>, DiskPlan> disk_plans;
    // The tiled call (plan task S5-T10): each tile's row count is a GEMM M of its own and changes with every list
    // build, so a decision timed for one M is taken for every M of its size bucket (four per octave, m_bucket) while
    // the handle holds a tile workspace. Kept in memory for the handle's life (not written to the plan file);
    // LOUP_TILE_GEMM_BUCKETS=0 turns it off (every M timed, as the whole-system path).
    std::map<std::tuple<int, int, int, bool, bool>, DiskPlan> bucket_plans;
    bool gemm_buckets = true;
    bool disk_dirty = false;
    void load_disk_plans(int device_id) {
        if (force_tc) return;  // forced picks must not reach (or come from) the plan cache
        const char* cdir = std::getenv("LOUP_CACHE_DIR");
        std::string dir;
        if (cdir && cdir[0]) dir = cdir;
        else if (const char* hm = std::getenv("HOME")) dir = std::string(hm) + "/.cache/loupmd";
        else return;
        cudaDeviceProp prop{};
        if (cudaGetDeviceProperties(&prop, device_id) != cudaSuccess) return;
        std::string gname;
        for (const char* p = prop.name; *p; ++p) {
            unsigned char c = (unsigned char)*p;
            gname.push_back((isalnum(c) || c == '_') ? (char)c : '_');
        }
        char buf[512];
        // The loaded cubin keys the plans too: a replaced cubin file (other tiles, math or beta support) is re-timed.
        char cub[24] = "";
        if (hyb.loaded) snprintf(cub, sizeof(cub), "_c%016llx", (unsigned long long)hyb.cubin_hash);
        snprintf(buf, sizeof(buf), "%s/plans_%s_sm%d%d_lt%zu_hyb%d_%016llx%s.bin",
                 dir.c_str(), gname.c_str(), prop.major, prop.minor,
                 cublasLtGetVersion(), hyb.loaded ? 1 : 0, (unsigned long long)library_build_hash(), cub);
        plan_cache_path = buf;
        if (std::getenv("LOUP_RETUNE")) return;  // re-time everything; the new plans still overwrite the file
        FILE* fp = fopen(plan_cache_path.c_str(), "rb");
        if (!fp) return;
        char magic[8];
        uint32_t cnt = 0;
        if (fread(magic, 1, 8, fp) == 8 && memcmp(magic, "LOUPPLN4", 8) == 0 && fread(&cnt, 4, 1, fp) == 1) {
            for (uint32_t i = 0; i < cnt && i < 4096; ++i) {
                DiskPlan dp{};
                if (fread(&dp, sizeof(dp), 1, fp) != 1) break;
                disk_plans[std::make_tuple(dp.M, dp.N, dp.K, dp.transB != 0, dp.beta_nz != 0)] = dp;
            }
        }
        fclose(fp);
    }
    void save_disk_plans() {
        if (!disk_dirty || plan_cache_path.empty()) return;
        disk_dirty = false;
        for (size_t pos = 1; (pos = plan_cache_path.find('/', pos)) != std::string::npos; ++pos) {
            mkdir(plan_cache_path.substr(0, pos).c_str(), 0755);
        }
        std::string tmp = plan_cache_path + ".tmp." + std::to_string((long long)getpid());
        FILE* fp = fopen(tmp.c_str(), "wb");
        if (!fp) return;
        uint32_t cnt = (uint32_t)disk_plans.size();
        bool ok = fwrite("LOUPPLN4", 1, 8, fp) == 8 && fwrite(&cnt, 4, 1, fp) == 1;
        for (const auto& kv : disk_plans) {
            if (!ok) break;
            ok = fwrite(&kv.second, sizeof(DiskPlan), 1, fp) == 1;
        }
        fclose(fp);
        if (ok) rename(tmp.c_str(), plan_cache_path.c_str());
        else remove(tmp.c_str());
    }
    void clear_lt_cache() {
        for (auto& kv : lt_cache) {
            if (kv.second.layA) cublasLtMatrixLayoutDestroy(kv.second.layA);
            if (kv.second.layB) cublasLtMatrixLayoutDestroy(kv.second.layB);
            if (kv.second.layC) cublasLtMatrixLayoutDestroy(kv.second.layC);
            if (kv.second.desc) cublasLtMatmulDescDestroy(kv.second.desc);
        }
        lt_cache.clear();
    }
    std::unique_ptr<loup::GenericModel> gen;  // the model (every bundle is arch=generic since JIT_DESIGN.md stage 5)
    int n_species() const { return gen->S(); }
    float cutoff() const { return gen->r_max(); }
    int species_z(int s) const { return gen->atomic_numbers()[s]; }
    double species_e0(int s) const { return gen->e0()[s]; }

    // System topology (atoms grouped by species 0..S-1)
    int N = 0;
    // An open domain (loup_debug_set_domain): the device rows N .. N + n_ghost - 1 are ghost atoms. They take part
    // in the neighbour build as senders and have rows in what senders provide; they receive nothing. 0 for a
    // periodic system, which is all the public calls accept.
    int n_ghost = 0;
    // The rows (locals and ghosts) the per-system buffers were allocated for: a tile workspace (reshape_domain)
    // takes any smaller domain without allocating again.
    int atom_cap = 0;
    bool tile_workspace = false;  // the handle holds the tiled call's workspace (set up by it, kept between calls)
    // loup_set_execution (kept by loup_set_system): mode, receiver cap (0: the plan's), fraction of free device
    // memory a plan may use; and how the last tiled call ran (loup_get_execution).
    int exec_mode = LOUP_EXEC_AUTO;
    int exec_receivers = 0;
    double exec_fraction = 0.9;
    LoupExecution last_exec{};
    TiledState* tiled_state = nullptr;  // the tiled call's plan, kept lists and state buffers (S5-T06)
    // O32: the pinned host buffers of a released tiled state (bytes, pointer), taken again by the next state's set-up
    // instead of new cudaHostAlloc calls (2,560,000 atoms: about 3.8 s of a 7.7 s list rebuild); freed at the end of
    // that set-up when not taken, and with the handle (tile-pinned-reuse)
    struct PinnedSpare {
        std::vector<std::pair<size_t, void*>> bufs, mapped;  // cudaHostAllocDefault; cudaHostAllocMapped
        double bytes() const {
            double b = 0.0;
            for (const auto& x : bufs) b += (double)x.first;
            for (const auto& x : mapped) b += (double)x.first;
            return b;
        }
        void clear() {
            for (const auto& x : bufs) cudaFreeHost(x.second);
            for (const auto& x : mapped) cudaFreeHost(x.second);
            bufs.clear();
            mapped.clear();
        }
        ~PinnedSpare() { clear(); }
    } pinned_spare;
    // The state of tiled MD on the device (loup_tiled_set_state, PLAN.md O31): positions, velocities, masses, forces
    // and the integrator's scalars of a system run tile by tile. It outlives the tiled state (rebuilt at a list
    // rebuild) and the workspace (each tile's domain); loup_set_system and loup_destroy free it.
    TiledMD* tiled_md = nullptr;
    long long tile_list_builds = 0;     // tiled calls that built their lists, since the handle was created
    int tile_host_lists = 0;            // the last loup_plan_execution put the tile lists' edges in host memory (O31)
    int tile_host_state = 0;            // ... and the layer state (O32): 1 plain order, 2 the wavefront's row pool
    double skin = 0.5;
    double e0_total = 0.0;
    std::vector<int> perm;          // device (species-grouped, spatially ordered) index -> caller index
    std::vector<double> atom_e0;    // caller index -> the atom's E0 (0 for ghosts): per-atom energies (S6-T08)
    std::vector<int> h_order;       // scratch: new device index -> old device index at an atom reorder
    std::vector<int> species_start; // [S+1]
    std::vector<int> species_count; // [S]
    loup::CellMat64 cell{};
    double cell_in[9] = {0, 0, 0, 0, 0, 0, 0, 0, 0};  // the cell as the caller last gave it (state blob)
    uint64_t species_hash = 0;                        // of the atomic numbers in caller order (state blob)
    double cell_vol = 0.0;
    double cell_heights[3] = {0, 0, 0};
    // The variable cell (cell.hpp), from the handle's first variable-cell run on: the cell on the device, which the
    // captured step reads and writes, and the edges' integer image shifts in the edges' order (d_cell_codes, 4 B per
    // edge, cell_shift_codes_kernel). Every rebuild refreshes both from the host's cell; the host's cell follows the
    // device's before a rebuild inside such a run and at the end of the call.
    bool var_cell = false;
    loup::CellDev* d_celldev = nullptr;
    char4* d_cell_codes = nullptr;
    int cell_codes_cap = 0;
    // The dispersion term (S6-D04, loup_set_dispersion), added to every whole-system force pass. It reads the cell
    // on the device: d_disp_cell, which follows the host's cell, or the device's own cell inside a variable-cell
    // step (disp_cell_dev while that step is recorded). disp_ready: prepared for this system (the first positions
    // after loup_set_system or loup_set_dispersion prepare it).
    std::unique_ptr<loup::dispersion::Term> disp;
    double* d_disp_cell = nullptr;
    bool disp_ready = false;
    bool disp_cell_dev = false;
    loup::CellDev celldev_host{};
    double cell_v0 = 0.0;          // the volume at loup_set_state / loup_import_state: the cell limits refer to it
    bool cell_ref_stale = false;   // the cell has changed since the list was built (a variable-cell run ended so):
                                   // whoever checks the list without the device's cell rebuilds first
    bool req_var_cell = false;     // this loup_run call goes through the variable-cell step
    double req_cell_rate = 0.0;    // testing: the cell and the positions scaled by 1 + this in every step

    // Atom device buffers
    int* d_species = nullptr;
    double* d_pos64 = nullptr;
    double* d_ref_pos64 = nullptr;
    double* d_vel64 = nullptr;
    double* d_masses = nullptr;
    double* d_inv_masses = nullptr;
    double* d_sqrt_inv_masses = nullptr;
    double* d_rnd_vel = nullptr;
    int* d_need_rebuild = nullptr;
    // Maximum of the squared per-step displacements (float bits) in two windows, [0] current and [1] previous;
    // readers take the larger (loup_get_step_displacement, the saved state). disp_window_steps: steps since the
    // current window began.
    unsigned int* d_max_step_disp2 = nullptr;
    int disp_window_steps = 0;
    unsigned long long* d_step_counter = nullptr;
    double* d_langevin_target = nullptr;  // [5]: the thermostat's target of the next step in K, its change per step,
                                          // and that step's noise coefficients (c3, c4, c5 without the mass factor)
    double* d_int_state = nullptr;        // [kIntStateSlots]: the integrator's scalars (see kIntStateSlots)
    double* d_int_work = nullptr;         // [kIntWorkSlots]
    int int_state_kind = -1;              // the LOUP_* kind whose scalars d_int_state holds; -1: none (all zero)
    MinState min_state;                   // loup_minimize
    unsigned long long pos_epoch = 0;     // counts what moves positions or reorders atoms outside loup_minimize
    bool suppress_reorder = false;        // loup_minimize: its vectors are in the atom order of its start
    // Fixed atoms (loup_set_fixed_atoms): their inverse masses on the device are zero, so no kernel moves them.
    int n_fixed = 0;
    std::vector<double> masses_caller;        // caller order: restores the inverse mass of an atom set free
    std::vector<unsigned char> fixed_caller;  // caller order
    // fix_com (LoupIntegrator.fix_com) of the run in progress or run last: three degrees of freedom fewer.
    bool fix_com = false;
    double total_mass = 0.0;
    double* d_rnd_pos = nullptr;  // [N, 3]: the position noise of a fix_com Langevin step (allocated on first use)
    double* d_com = nullptr;      // [6]: mass-weighted sums of the two noise terms, or the total momentum
    int kinetic_dof() const { return 3 * (N - n_fixed) - (fix_com ? 3 : 0); }
    double* d_ke_f64 = nullptr;

    // Neighbour build scratch
    int max_bins = 0;
    double* d_pos_wrapped = nullptr;
    int* d_atom_wrap = nullptr;
    int* d_atom_bin = nullptr;
    unsigned long long* d_ro_keys = nullptr;  // [2N] atom reorder sort keys (in, out)
    int* d_ro_vals = nullptr;                 // [2N] atom reorder indices (in, out)
    double* d_ro_tmp = nullptr;               // [3N] gather scratch
    int* d_bin_counts = nullptr;
    int* d_bin_offsets = nullptr;
    int* d_bin_cursor = nullptr;
    int* d_bin_atom_id = nullptr;
    double* d_bin_pos = nullptr;
    float4* d_bin_pos_f32 = nullptr;
    int* d_bin_wrap = nullptr;
    int* d_bin_sp = nullptr;
    int* d_deg = nullptr;
    unsigned long long* d_edge_total = nullptr;  // the degrees' sum in 64 bits (rebuild_neighbors)
    // The most edges a whole-system list may have: the edge arrays are indexed e * 3 and e * 4 in int.
    // LOUP_DEBUG_EDGE_LIMIT lowers it for the test of the refusal (read by loup_set_system).
    long long edge_limit = 536870911;
    int* d_row_ptr = nullptr;
    int* d_act_deg = nullptr;
    int* d_act_row_ptr = nullptr;
    void* d_cub_tmp = nullptr;
    size_t cub_tmp_bytes = 0;

    // Edge buffers (capacity >= E_cap >= E_graph >= E_skin)
    int E_skin = 0;
    int E_graph = 0;
    int E_cap = 0;
    // Candidate edges (within r_max + skin), row i holding the edges whose receiver is i (S113: no per-edge receiver
    // or pair index)
    int* d_senders = nullptr;
    double* d_shift_cart = nullptr;  // [E, 3] shift @ cell of each skin edge (float64), set at rebuild
    int* d_tmp_snd = nullptr;
    int* d_tmp_shifts = nullptr;
    uint32_t* d_sort_keys = nullptr;
    float4* d_act_vec_len = nullptr;
    int* d_act_senders = nullptr;
    int* d_act_receivers = nullptr;
    int* d_act_slab = nullptr;
    float2* d_act_t_sx = nullptr;
    float4* d_tmp_vec_len = nullptr;
    float* d_edge_force_1 = nullptr;

    // Zero-initialized per-step slab
    void* d_zero_slab = nullptr;
    size_t zero_slab_bytes = 0;
    double* d_energy_f64 = nullptr;
    double* d_forces_f64 = nullptr;
    double* d_virial_grad_f64 = nullptr;

    // Graph caches
    cudaGraph_t force_graph = nullptr;
    cudaGraphExec_t force_graph_exec = nullptr;
    int force_graph_stress = -1;
    // The energy-only pass (loup_evaluate2 with LOUP_EVAL_ENERGY_ONLY), kept beside the force graph so that
    // alternating the two (Monte Carlo between MD steps) captures neither again.
    cudaGraph_t energy_graph = nullptr;
    cudaGraphExec_t energy_graph_exec = nullptr;
    double* pass_atom_energy = nullptr;  // a per-atom energy pass (S6-T08) is being recorded: its [N] buffer

    // MD step: first half + skin check + guard_step_kernel + one SWITCH node: body 0 the rest (forces + second half)
    // when the list is complete and its rows valid, body 1 (when md_dev_rebuild) the rebuild branch: count +
    // rebuild_gate_kernel, then fill + commit + IF (fits, valid rows) rest. The rebuild runs on the GPU without a host
    // round trip unless the new list outgrows the captured sizes.
    cudaGraph_t md_step_graph = nullptr;
    cudaGraphExec_t md_step_exec = nullptr;
    bool md_dev_rebuild = false;
    // Checked rest, launched after a host-driven rebuild: rest_guard_kernel + IF (valid rows) {forces + second half}.
    cudaGraph_t md_checked_graph = nullptr;
    cudaGraphExec_t md_checked_exec = nullptr;
    // What the MD graphs bake in. They are kept from call to call while all of it is the same: a run in blocks, a
    // schedule's calls, and the caller-integrated steps of loup_compute_device / loup_evaluate (kStepDevice /
    // kStepHost, whose only setting is whether the virial is formed: it stands in the seed's place).
    int md_graph_kind = -1;  // the run_md_loop kind the graphs are for
    double md_graph_dt = 0.0;
    double md_graph_fr = 0.0;
    double md_graph_tau = 0.0;
    double md_graph_mass_temp = 0.0;
    int md_graph_chain = 0;   // 1000 chain_length + chain_loops
    unsigned long long md_graph_seed = 0;
    bool md_graph_thermo = false;  // the graphs carry the two thermo kernels
    bool md_graph_fixcom = false;  // the graphs are the fix_com variant (and its degrees of freedom)
    bool md_graph_varcell = false; // the graphs are the variable-cell step
    double md_graph_cellrate = 0.0;
    double md_graph_npt[7] = {0, 0, 0, 0, 0, 0, 0};  // the barostat's settings the graphs bake in (NptParams)
    bool last_pass_stress = false; // the last force pass carried stress: the virial on the device is current with
                                   // the forces (a barostat's first step needs it)

    // Thermo buffer (thermo.hpp), allocated by the first run that asks for rows. The host knows the step count and
    // the number of unread rows exactly and writes the device's control block at the start of every such run.
    loup::ThermoCtrl* d_thermo_ctrl = nullptr;
    LoupThermoRow* d_thermo_rows = nullptr;
    long long md_steps = 0;       // MD steps completed since the last set_state / import_state
    int thermo_pending = 0;       // unread rows on the device

    void invalidate_graphs() {
        if (force_graph_exec) { cudaGraphExecDestroy(force_graph_exec); force_graph_exec = nullptr; }
        if (force_graph) { cudaGraphDestroy(force_graph); force_graph = nullptr; }
        force_graph_stress = -1;
        if (energy_graph_exec) { cudaGraphExecDestroy(energy_graph_exec); energy_graph_exec = nullptr; }
        if (energy_graph) { cudaGraphDestroy(energy_graph); energy_graph = nullptr; }
        invalidate_md_graphs();
    }
    void invalidate_md_graphs() {
        drain_armed();  // callers settle a queued step first; this is the net under them
        if (md_step_exec) { cudaGraphExecDestroy(md_step_exec); md_step_exec = nullptr; }
        if (md_step_graph) { cudaGraphDestroy(md_step_graph); md_step_graph = nullptr; }
        if (md_checked_exec) { cudaGraphExecDestroy(md_checked_exec); md_checked_exec = nullptr; }
        if (md_checked_graph) { cudaGraphDestroy(md_checked_graph); md_checked_graph = nullptr; }
        md_dev_rebuild = false;
    }

    // loup_compute_device (host codes whose atoms stay on the GPU, e.g. LAMMPS Kokkos): the caller's rows are gathered
    // into the engine's order and the forces added back through a device copy of the inverse permutation.
    int* d_inv_perm = nullptr;    // [N] caller atom -> device index
    int perm_epoch = 0;           // bumped whenever perm changes (set_system, an atom reorder)
    int inv_perm_epoch = -1;      // the perm_epoch d_inv_perm was written for
    int* d_io_bad = nullptr;      // set by io_gather_kernel when an id is outside 0 .. N-1
    // loup_evaluate's host I/O: page-locked staging [3N positions | 3N forces | energy | 6 virial], so the uploads and
    // downloads are asynchronous copies and the host learns that the results have landed from one publication instead
    // of blocking transfers and a stream synchronisation (a host round trip each, 100-200 us under WSL 2). A whole
    // system has it; an open domain (n_ghost > 0, a tile) does not.
    double* h_stage = nullptr;    // [3N positions | a copy of the zeroed slab: energy, forces, virial]
    size_t stage_off_f = 0, stage_off_v = 0;  // doubles from the slab copy's start to the forces / the virial
    double* stage_pos() const { return h_stage; }
    double* stage_out() const { return h_stage + (size_t)3 * N; }  // [0] the energy
    double* stage_f() const { return stage_out() + stage_off_f; }
    double* stage_v() const { return stage_out() + stage_off_v; }
    cudaEvent_t ev_io_in = nullptr, ev_io_out = nullptr;

    // loup_evaluate, armed (LAMMPS_SYMMETRIX_PARITY_PLAN.md L1): after a call, the next call's step graph is queued
    // ahead behind a wait on the host-mapped word *h_go (cuStreamWaitValue32). The next call writes its positions into
    // the staging and stores go_seq there, which lets the graph run with no launch on the call's path (S37: a launch
    // round trip is 156-174 us under WSL 2). While `armed`, the stream is blocked: nothing else may be queued on it or
    // wait for it, so every other entry point first lets the queued step run (settle_armed). The stream is a blocking
    // one, so work on CUDA's default stream anywhere in the process (another handle's set-up, another library) and a
    // device-wide synchronisation would wait for it too, forever: the caller switches this on
    // (loup_set_evaluate_ahead) only when its loup_evaluate calls are the process's only GPU work in between.
    unsigned int* h_go = nullptr;  // mapped page-locked word
    unsigned int* d_go = nullptr;  // its device address
    unsigned int go_seq = 0;       // the value that releases the queued graph
    bool armed = false;
    bool arm_enabled = false;      // loup_set_evaluate_ahead (LOUP_EVAL_ARM=1: on for every handle, tests)
    int armed_stress = 0;
    int arm_state = 0;             // 0 untried, 1 available, -1 not (driver, mapped memory or LOUP_EVAL_ARM=0)
    // LOUP_DEBUG_EVAL_TIMES=1: where a loup_evaluate call's time goes, as means over the handle's calls that took the
    // step graph without a rebuild, printed when the handle goes. us: [0] entry to the launch or release, [1] to the
    // guard's publication, [2] to the results' publication, [3] to the return, [4] return to the next call's entry.
    bool probe = false;
    double probe_us[5] = {0, 0, 0, 0, 0};
    long probe_n = 0, probe_gap_n = 0;
    std::chrono::steady_clock::time_point probe_t[4], probe_ret;
    bool probe_ret_set = false;
    int eval_streak = 0;           // loup_evaluate calls in a row that took the step graph with one virial flag
    int eval_streak_stress = -1;
    int eval_since_run = 0;        // loup_evaluate calls since the last integrator step (evaluate_once: which path)
    // A queued launch whose step can no longer be read in the normal way (an exception, the handle's end): let it
    // run, drain the stream and take the publication counter from the device again.
    void drain_armed() {
        if (!armed) return;
        __atomic_store_n(h_go, go_seq, __ATOMIC_SEQ_CST);
        armed = false;
        cudaStreamSynchronize(stream);
        cudaMemcpy(&pub_count, d_pub_counter, sizeof(unsigned int), cudaMemcpyDeviceToHost);
        eval_streak = 0;
    }

    int n_rebuilds = 0;     // rebuilds since set_system (atom reorder cadence)
    int* d_order_err = nullptr;  // set by sort_gather_rows_kernel when a row breaks the species-run contract
    int* d_max_deg = nullptr;    // [0] longest neighbour row of the current rebuild, [1] the MD rebuild gate's verdict
    int max_deg_last = 0;        // longest row of the last rebuild (sizes the MD step graph's row sort)
    bool nl_valid = false;  // neighbour list built for the current system (ref positions and shifts are set)
    // d_forces_f64 and d_energy_f64 belong to the positions in d_pos64: the last call was a force evaluation or a
    // completed run, with no new positions since. A run then starts without a force pass of its own.
    bool forces_current = false;
    // Bytes of the buffers that scale with the system, counted where they are allocated (loup_plan_memory scales
    // them to another size): per atom (set_system_impl), per edge of capacity (ensure_edge_capacity), and the
    // [K, N] weight copies of the GEMMs, which do not scale.
    size_t sys_atom_bytes = 0, sys_edge_bytes = 0, weight_copy_bytes = 0;
    size_t sys_fixed_bytes = 0;  // buffers of set_system_impl whose size does not depend on the atom count

    void free_system() {
        release_tiled_state(this);
        if (gen) gen->free_system();
        invalidate_graphs();
        clear_lt_cache();
        variants_tuned = false;
        variants_early = false;
        passes_untuned = 0;
        nl_valid = false;
        forces_current = false;
        disp_window_steps = 0;
        n_ghost = 0;
        atom_cap = 0;
        tile_workspace = false;
        sys_atom_bytes = 0;
        sys_edge_bytes = 0;
        sys_fixed_bytes = 0;
        n_rebuilds = 0;
        N = 0;
        auto freep = [](auto*& p) {
            if (p) { cudaFree(p); p = nullptr; }
        };
        freep(d_species); freep(d_pos64); freep(d_ref_pos64); freep(d_vel64);
        freep(d_masses); freep(d_inv_masses); freep(d_sqrt_inv_masses); freep(d_rnd_vel);
        freep(d_need_rebuild); freep(d_max_step_disp2); freep(d_step_counter); freep(d_langevin_target);
        freep(d_int_state); freep(d_int_work);
        int_state_kind = -1;
        min_state.release();
        freep(d_rnd_pos); freep(d_com);
        freep(d_ke_f64);
        freep(d_thermo_ctrl); freep(d_thermo_rows);
        md_steps = 0;
        thermo_pending = 0;
        freep(d_inv_perm); freep(d_io_bad); inv_perm_epoch = -1;
        if (h_stage) { cudaFreeHost(h_stage); h_stage = nullptr; }
        freep(d_pos_wrapped); freep(d_atom_wrap); freep(d_atom_bin);
        freep(d_ro_keys); freep(d_ro_vals); freep(d_ro_tmp); freep(d_order_err); freep(d_max_deg);
        freep(d_bin_counts); freep(d_bin_offsets); freep(d_bin_cursor);
        freep(d_bin_atom_id); freep(d_bin_pos); freep(d_bin_pos_f32); freep(d_bin_wrap); freep(d_bin_sp);
        freep(d_deg); freep(d_edge_total); freep(d_row_ptr); freep(d_cub_tmp); cub_tmp_bytes = 0;
        freep(d_act_deg); freep(d_act_row_ptr);

        freep(d_senders); freep(d_shift_cart);
        freep(d_cell_codes); cell_codes_cap = 0;
        // views into d_tmp_vec_len / d_edge_force_1 (ensure_edge_capacity), freed with them
        d_tmp_snd = d_tmp_shifts = nullptr;
        d_sort_keys = nullptr;
        freep(d_act_vec_len);
        freep(d_act_senders); freep(d_act_receivers);
        freep(d_act_slab); freep(d_act_t_sx);
        freep(d_tmp_vec_len);
        freep(d_edge_force_1);
        E_cap = 0; E_skin = 0;

        freep(d_zero_slab); zero_slab_bytes = 0;
    }
};

namespace loup {
void sgemm128_init();
void sgemm128(int M, int N, int K, const float* A, const float* B, float* C, float beta, bool n_fastest,
              cudaStream_t stream);
void sgemm64(int M, int N, int K, const float* A, const float* B, float* C, float beta, cudaStream_t stream);
void sgemm32(int M, int N, int K, const float* A, const float* B, float* C, float* ws, float beta, int split_k,
             cudaStream_t stream);
void sgemm128_gate(bool fwd, int l, int M, int N, int K, const float* A, const float* B, const GateArgs& g,
                   cudaStream_t stream);
void transpose(int R, int Ccols, const float* in, float* out, cudaStream_t stream);
}

// Scope guards for the tuning paths (a throw from a timed launch must not leak device memory or events).
struct DeviceBufferGuard {
    void* p = nullptr;
    ~DeviceBufferGuard() { if (p) cudaFree(p); }
};
// Pinned host memory mapped into the device's address space (cudaHostAllocMapped): kernels read it over the bus
struct HostBufferGuard {
    void* p = nullptr;
    size_t n = 0;  // O32: the bytes, where pinned_take set it (such a buffer goes back to the handle's spares)
    ~HostBufferGuard() { if (p) cudaFreeHost(p); }
};
struct EventPairGuard {
    cudaEvent_t e0 = nullptr, e1 = nullptr;
    EventPairGuard() {
        CUDA_CHECK_THROW(cudaEventCreate(&e0));
        CUDA_CHECK_THROW(cudaEventCreate(&e1));
    }
    ~EventPairGuard() {
        if (e0) cudaEventDestroy(e0);
        if (e1) cudaEventDestroy(e1);
    }
};

// loup::sgemm128 takes B as [K, N]; a transposed operand of sgemm_rm is always a model weight, so its [K, N] copy is
// made once (on first use, in the uncaptured autotune pass) and kept for the handle's lifetime.
static const float* weight_kn(LoupHandle* h, const float* B, int N, int K, cudaStream_t strm) {
    const auto key = std::make_tuple(B, N, K);
    auto it = h->bt_cache.find(key);
    if (it != h->bt_cache.end()) return it->second;
    float* bt = nullptr;
    CUDA_CHECK_THROW(cudaMalloc(&bt, (size_t)N * K * sizeof(float)));
    h->weight_copy_bytes += (size_t)N * K * sizeof(float);
    loup::transpose(N, K, B, bt, strm);
    cudaStreamCaptureStatus cap = cudaStreamCaptureStatusNone;
    CUDA_CHECK_THROW(cudaStreamIsCapturing(strm, &cap));
    if (cap == cudaStreamCaptureStatusNone) CUDA_CHECK_THROW(cudaStreamSynchronize(strm));
    h->bt_cache.emplace(key, bt);
    return bt;
}

// The legacy handle serves every stream; cublasSetStream resets its workspace to cuBLAS's shared default pool, so the
// lane's own workspace is bound with it (cuBLAS: a workspace per stream, else results may differ from run to run when
// streams run concurrently). Each workspace serves one stream, where cuBLASLt and legacy calls run in order.
static void cublas_bind(LoupHandle* h, cudaStream_t s, void* ws) {
    CUBLAS_CHECK_THROW(cublasSetStream(h->cublas, s));
    CUBLAS_CHECK_THROW(cublasSetWorkspace(h->cublas, ws, h->cublas_ws_bytes));
}

// The size bucket of a GEMM's M in the tiled call: four per octave (M in [2^e, 2^e * 5/4) is one bucket, and so on),
// so a bucket spans at most 25% of its smallest M. Below 64 rows every M is its own bucket.
static inline int m_bucket(int M) {
    if (M < 64) return -M;
    const int e = 31 - __builtin_clz((unsigned)M);
    return e * 4 + (int)(((unsigned)M >> (e - 2)) & 3u);
}

static inline void sgemm_rm(
    LoupHandle* h, bool transA, bool transB,
    int M, int N, int K,
    float alpha, const float* A, int lda,
    const float* B, int ldb,
    float beta, float* C, int ldc
) {
    cudaStream_t strm = h->gemm_stream ? h->gemm_stream : h->stream;
    cublasLtHandle_t lt_h = h->cublas_lt;
    void* ws_p = h->gemm_ws ? h->gemm_ws : h->d_cublas_ws;
    if (transA || lda != K || ldc != N || ldb != (transB ? K : N)) {
        cublasOperation_t opB = transB ? CUBLAS_OP_T : CUBLAS_OP_N;
        cublasOperation_t opA = transA ? CUBLAS_OP_T : CUBLAS_OP_N;
        cublas_bind(h, strm, ws_p);
        CUBLAS_CHECK_THROW(cublasSgemm(h->cublas, opB, opA, N, M, K, &alpha, B, ldb, A, lda, &beta, C, ldc));
        cublas_bind(h, h->stream, h->d_cublas_ws);
        return;
    }
    auto key = std::make_tuple(M, N, K, transB, beta != 0.0f);
    const bool own_ok = alpha == 1.0f && (K % 16) == 0 && (N % 4) == 0 && ((((uintptr_t)A | (uintptr_t)B) & 15) == 0);
    auto own_b = [&] { return transB ? weight_kn(h, B, N, K, strm) : B; };
    auto it = h->lt_cache.find(key);
    if (it == h->lt_cache.end()) {
        LoupHandle::LtPlan plan{};
        cublasOperation_t opA_lt = transB ? CUBLAS_OP_T : CUBLAS_OP_N;
        cublasOperation_t opB_lt = CUBLAS_OP_N;
        CUBLAS_CHECK_THROW(cublasLtMatmulDescCreate(&plan.desc, CUBLAS_COMPUTE_32F, CUDA_R_32F));
        CUBLAS_CHECK_THROW(cublasLtMatmulDescSetAttribute(plan.desc, CUBLASLT_MATMUL_DESC_TRANSA, &opA_lt, sizeof(opA_lt)));
        CUBLAS_CHECK_THROW(cublasLtMatmulDescSetAttribute(plan.desc, CUBLASLT_MATMUL_DESC_TRANSB, &opB_lt, sizeof(opB_lt)));
        if (!transB) CUBLAS_CHECK_THROW(cublasLtMatrixLayoutCreate(&plan.layA, CUDA_R_32F, N, K, N));
        else         CUBLAS_CHECK_THROW(cublasLtMatrixLayoutCreate(&plan.layA, CUDA_R_32F, K, N, K));
        CUBLAS_CHECK_THROW(cublasLtMatrixLayoutCreate(&plan.layB, CUDA_R_32F, K, M, K));
        CUBLAS_CHECK_THROW(cublasLtMatrixLayoutCreate(&plan.layC, CUDA_R_32F, N, M, N));

        cublasLtMatmulPreference_t pref = nullptr;
        CUBLAS_CHECK_THROW(cublasLtMatmulPreferenceCreate(&pref));
        CUBLAS_CHECK_THROW(cublasLtMatmulPreferenceSetAttribute(
            pref, CUBLASLT_MATMUL_PREF_MAX_WORKSPACE_BYTES, &h->cublas_ws_bytes, sizeof(h->cublas_ws_bytes)));
        // No split-K reduction: those algorithms zero a workspace semaphore with a memset node before each GEMM, and
        // the captured memsets left the GPU idle ~120 us per step (5060 Ti, the beta = 1 skip GEMMs); they are also
        // order-nondeterministic. K <= 384 here, so split-K has nothing to gain.
        const uint32_t no_reduction = CUBLASLT_REDUCTION_SCHEME_NONE;
        CUBLAS_CHECK_THROW(cublasLtMatmulPreferenceSetAttribute(
            pref, CUBLASLT_MATMUL_PREF_REDUCTION_SCHEME_MASK, &no_reduction, sizeof(no_reduction)));
        cublasLtMatmulHeuristicResult_t res[32];
        int n_res = 0;
        CUBLAS_CHECK_THROW(cublasLtMatmulAlgoGetHeuristic(
            lt_h, plan.desc, plan.layA, plan.layB, plan.layC, plan.layC, pref, 32, res, &n_res));
        cublasLtMatmulPreferenceDestroy(pref);
        if (n_res <= 0) {
            cublasLtMatrixLayoutDestroy(plan.layA); cublasLtMatrixLayoutDestroy(plan.layB);
            cublasLtMatrixLayoutDestroy(plan.layC); cublasLtMatmulDescDestroy(plan.desc);
            cublasOperation_t opB = transB ? CUBLAS_OP_T : CUBLAS_OP_N;
            cublas_bind(h, strm, ws_p);
            CUBLAS_CHECK_THROW(cublasSgemm(h->cublas, opB, CUBLAS_OP_N, N, M, K, &alpha, B, ldb, A, lda, &beta, C, ldc));
            cublas_bind(h, h->stream, h->d_cublas_ws);
            return;
        }
        plan.algo = res[0].algo;
        bool hit_disk = false;
        const bool bucketed = h->tile_workspace && h->gemm_buckets;
        const auto bkey = std::make_tuple(m_bucket(M), N, K, transB, beta != 0.0f);
        const LoupHandle::DiskPlan* found = nullptr;
        auto dit = h->disk_plans.find(key);
        if (dit != h->disk_plans.end()) {
            found = &dit->second;
        } else if (bucketed) {
            auto bit = h->bucket_plans.find(bkey);
            if (bit != h->bucket_plans.end()) found = &bit->second;
        }
        if (found) {
            const auto& dp = *found;
            auto splitk_ok = [&](uint8_t m) {
                if (m <= 2) return true;
                if (m > 5) return false;
                const int sk = (m == 3) ? 1 : (m == 4 ? 2 : 4);
                return sk == 1 || (K >= 64 * sk && (size_t)sk * M * N * sizeof(float) <= h->cublas_ws_bytes);
            };
            auto narrow_ok = [&](uint8_t m) {
                if (M <= 1600) return true;
                if (m == 2) return N <= 64 || (M <= 2500 && N <= 160);
                return N <= 32 || (M <= 2500 && N <= 160);
            };
            if (dp.use_own == 1 ||
                (dp.use_own >= 2 && dp.use_own <= 5 && h->own_ext && narrow_ok(dp.use_own) && splitk_ok(dp.use_own))) {
                if (own_ok) {
                    plan.own_mode = dp.use_own;
                    hit_disk = true;
                }
            } else if (dp.use_hyb) {
                if (dp.hyb_tile < h->hyb.ntiles && alpha == 1.0f && h->hyb.takes(beta) && (K & 3) == 0 && (N & 3) == 0 &&
                    ((((uintptr_t)A | (uintptr_t)B) & 15) == 0)) {
                    plan.use_hyb = true;
                    plan.hyb_tile = dp.hyb_tile;
                    hit_disk = true;
                }
            } else {
                cublasLtMatmulHeuristicResult_t chk{};
                if (cublasLtMatmulAlgoCheck(lt_h, plan.desc, plan.layA, plan.layB, plan.layC, plan.layC,
                                            &dp.algo, &chk) == CUBLAS_STATUS_SUCCESS &&
                    chk.state == CUBLAS_STATUS_SUCCESS && chk.workspaceSize <= h->cublas_ws_bytes) {
                    plan.algo = dp.algo;
                    plan.use_hyb = false;
                    hit_disk = true;
                }
            }
        }
        cudaStreamCaptureStatus cap_st = cudaStreamCaptureStatusNone;
        cudaStreamIsCapturing(strm, &cap_st);
        if (!hit_disk && cap_st == cudaStreamCaptureStatusNone) {
            // An A larger than half the L2 was written by the preceding kernel among tens of MB of other data and
            // streams from DRAM in the force pass, so it is timed with a cold L2 (flushed before every launch): a
            // hot-L2 loop favours tiles that re-read A per column tile (on Ada the 64x32 hybrid tile won hot for the
            // lin1 l=2/3 products and ran ~2x slower in the pass). Smaller operands stay resident and are timed hot.
            DeviceBufferGuard tmpC_buf, flush_buf;
            float* d_tmpC = nullptr;
            void* d_flush = nullptr;
            const size_t flush_bytes = (size_t)std::max(h->l2_bytes, 1 << 20) * 2;
            const bool cold = (size_t)M * K * sizeof(float) > (size_t)h->l2_bytes / 2;
            if (loup::device_malloc(&tmpC_buf.p, (size_t)M * N * sizeof(float)) == cudaSuccess &&
                (!cold || loup::device_malloc(&flush_buf.p, flush_bytes) == cudaSuccess)) {
                d_tmpC = static_cast<float*>(tmpC_buf.p);
                d_flush = flush_buf.p;
                cudaMemsetAsync(d_tmpC, 0, (size_t)M * N * sizeof(float), strm);
                EventPairGuard ev;
                cudaEvent_t e0 = ev.e0, e1 = ev.e1;
                auto time_min = [&](auto&& launch) -> float {
                    for (int w = 0; w < 2; ++w) launch();
                    float best = 1e30f;
                    const int per_round = cold ? 1 : 5;
                    for (int round = 0; round < 5; ++round) {
                        if (cold) cudaMemsetAsync(d_flush, round, flush_bytes, strm);
                        cudaEventRecord(e0, strm);
                        for (int it_t = 0; it_t < per_round; ++it_t) launch();
                        cudaEventRecord(e1, strm);
                        CUDA_CHECK_THROW(cudaEventSynchronize(e1));
                        float ms = 1e30f;
                        cudaEventElapsedTime(&ms, e0, e1);
                        best = std::min(best, ms / (float)per_round);
                    }
                    return best;
                };
                float best_ms = 1e30f, second_ms = 1e30f;
                auto consider = [&](float ms) {
                    if (ms < best_ms) { second_ms = best_ms; best_ms = ms; return true; }
                    second_ms = std::min(second_ms, ms);
                    return false;
                };
                const bool tc_ok = alpha == 1.0f && h->hyb.takes(beta) && (K & 3) == 0 && (N & 3) == 0 &&
                                   ((((uintptr_t)A | (uintptr_t)B | (uintptr_t)d_tmpC) & 15) == 0);
                const bool only_tc = h->force_tc && tc_ok;
                for (int r = 0; r < (only_tc ? 0 : n_res); ++r) {
                    cublasStatus_t st = cublasLtMatmul(
                        lt_h, plan.desc, &alpha, B, plan.layA, A, plan.layB, &beta,
                        d_tmpC, plan.layC, d_tmpC, plan.layC, &res[r].algo, ws_p, h->cublas_ws_bytes, strm);
                    if (st != CUBLAS_STATUS_SUCCESS) continue;
                    const float ms = time_min([&] {
                        cublasLtMatmul(
                            lt_h, plan.desc, &alpha, B, plan.layA, A, plan.layB, &beta,
                            d_tmpC, plan.layC, d_tmpC, plan.layC, &res[r].algo, ws_p, h->cublas_ws_bytes, strm);
                    });
                    if (consider(ms)) { plan.algo = res[r].algo; plan.use_hyb = false; }
                }
                if (tc_ok) {
                    for (int t = 0; t < h->hyb.ntiles; ++t) {
                        const float ms = time_min([&] { h->hyb.launch(t, transB, M, N, K, A, lda, B, ldb, d_tmpC, ldc, beta, strm); });
                        if (consider(ms)) { plan.use_hyb = true; plan.hyb_tile = t; }
                    }
                }
                if (!only_tc && own_ok && (((uintptr_t)d_tmpC & 15) == 0)) {
                    const float* Bkn = own_b();
                    const float ms128 = time_min([&] { loup::sgemm128(M, N, K, A, Bkn, d_tmpC, beta, h->own_ext, strm); });
                    if (consider(ms128)) { plan.own_mode = 1; plan.use_hyb = false; }
                    if (h->own_ext) {
                        if (M <= 1600 || N <= 64 || (M <= 2500 && N <= 160)) {
                            const float ms64 = time_min([&] { loup::sgemm64(M, N, K, A, Bkn, d_tmpC, beta, strm); });
                            if (consider(ms64)) { plan.own_mode = 2; plan.use_hyb = false; }
                        }
                        if (M <= 1600 || N <= 32 || (M <= 2500 && N <= 160)) {
                            for (int idx = 0; idx < 3; ++idx) {
                                const int sk = 1 << idx;
                                if (sk > 1 && (K < 64 * sk || (size_t)sk * M * N * sizeof(float) > h->cublas_ws_bytes)) continue;
                                const float ms32 = time_min([&] {
                                    loup::sgemm32(M, N, K, A, Bkn, d_tmpC, static_cast<float*>(ws_p), beta, sk, strm);
                                });
                                if (consider(ms32)) { plan.own_mode = 3 + idx; plan.use_hyb = false; }
                            }
                        }
                    }
                }
                if (getenv("LOUP_DEBUG_GEMM")) {
                    const char* tag = plan.own_mode >= 3 ? "own32_"
                                    : plan.own_mode == 2 ? "own64_"
                                    : plan.own_mode == 1 ? "own"
                                    : plan.use_hyb       ? "hyb"
                                                         : "lt";
                    const int sub = plan.own_mode >= 3 ? (1 << (plan.own_mode - 3)) : (plan.use_hyb ? plan.hyb_tile : 0);
                    fprintf(stderr, "gemm M=%d N=%d K=%d transB=%d beta=%g cold=%d -> %s%d %.1f us\n", M, N, K,
                            (int)transB, beta, (int)cold, tag, sub, best_ms * 1e3f);
                }
                LoupHandle::DiskPlan dp{};
                dp.M = M; dp.N = N; dp.K = K;
                dp.transB = transB ? 1 : 0; dp.beta_nz = (beta != 0.0f) ? 1 : 0;
                dp.use_hyb = plan.use_hyb ? 1 : 0; dp.hyb_tile = (uint8_t)plan.hyb_tile;
                dp.use_own = (uint8_t)plan.own_mode;
                dp.algo = plan.algo;
                // A winner within 3% of the runner-up is timing noise: use it in this process but re-time next time
                // instead of pinning it for every later run on this GPU.
                if (best_ms < 0.97f * second_ms) {
                    h->disk_plans[key] = dp;
                    h->disk_dirty = true;
                }
                if (bucketed) h->bucket_plans[bkey] = dp;   // the bucket takes this decision, noise or not
                if (bucketed && getenv("LOUP_DEBUG_GEMM_BUCKETS"))
                    fprintf(stderr, "gemm timed M=%d N=%d K=%d (bucket %d)\n", M, N, K, m_bucket(M));
            }
        }
        it = h->lt_cache.emplace(key, plan).first;
    }
    const auto& plan = it->second;
    if (plan.own_mode && own_ok && (((uintptr_t)C & 15) == 0)) {
        if (plan.own_mode >= 3) {
            loup::sgemm32(M, N, K, A, own_b(), C, static_cast<float*>(ws_p), beta, 1 << (plan.own_mode - 3), strm);
        } else if (plan.own_mode == 2) {
            loup::sgemm64(M, N, K, A, own_b(), C, beta, strm);
        } else {
            loup::sgemm128(M, N, K, A, own_b(), C, beta, h->own_ext, strm);
        }
        return;
    }
    if (plan.use_hyb && alpha == 1.0f && h->hyb.takes(beta) &&
        ((((uintptr_t)A | (uintptr_t)B | (uintptr_t)C) & 15) == 0)) {
        h->hyb.launch(plan.hyb_tile, transB, M, N, K, A, lda, B, ldb, C, ldc, beta, strm);
        return;
    }
    CUBLAS_CHECK_THROW(cublasLtMatmul(
        lt_h, plan.desc, &alpha, B, plan.layA, A, plan.layB, &beta,
        C, plan.layC, C, plan.layC, &plan.algo, ws_p, h->cublas_ws_bytes, strm));
}

// A projection fused with degree l's gate (sgemm128_gate): backward dgout_l = A @ B^T (B [N, K], a model weight),
// forward lin_l = A @ B (B [K, N]), when sgemm_rm's plan for that GEMM is the own sgemm128 with N tiles fastest (whose
// tiles and arithmetic the fused kernel shares) and the shape fits it. False: nothing launched (no plan yet, as in the
// uncaptured autotune pass, or another implementation won). A null: only reports whether it would run.
static bool gemm_gate(LoupHandle* h, bool fwd, int l, int M, int N, int K, const float* A, const float* B,
                      const loup::GateArgs& g) {
    if (!h->own_ext || l < (fwd ? 1 : 0) || l > 3 || M != g.natoms * (2 * l + 1) || N != g.C || (N % 128) != 0 ||
        (K % 16) != 0 || ((((uintptr_t)A | (uintptr_t)B) & 15) != 0))
        return false;
    const auto it = h->lt_cache.find(std::make_tuple(M, N, K, !fwd, false));
    if (it == h->lt_cache.end() || it->second.own_mode != 1) return false;
    if (!A) return true;
    cudaStream_t strm = h->gemm_stream ? h->gemm_stream : h->stream;
    loup::sgemm128_gate(fwd, l, M, N, K, A, fwd ? B : weight_kn(h, B, N, K, strm), g, strm);
    return true;
}

static int ensure_edge_capacity(LoupHandle* h, int needed) {
    if (needed <= h->E_cap) return 0;
    int cap = std::max(needed + needed / 4 + 1024, 4096);
    // Capacity 0 and no graphs until every array is reallocated: after a failed allocation a later call grows again
    // instead of running on freed or null arrays.
    h->invalidate_graphs();
    h->E_cap = 0;
    h->sys_edge_bytes = 0;
    auto reallocp = [&](auto*& p, size_t elem_sz) {
        if (p) cudaFree(p);
        p = nullptr;
        h->sys_edge_bytes += (size_t)cap * elem_sz;
        return loup::device_malloc(&p, (size_t)cap * elem_sz);
    };
    CUDA_CHECK(reallocp(h->d_senders, sizeof(int)));
    CUDA_CHECK(reallocp(h->d_shift_cart, 3 * sizeof(double)));
    // The rebuild's fill / sort temporaries are views into arrays a force pass rewrites before reading and that are
    // dead during a rebuild: senders and sort keys in d_tmp_vec_len (8 of its 16 B per edge), the shifts in
    // d_edge_force_1.
    h->d_tmp_snd = h->d_tmp_shifts = nullptr;
    h->d_sort_keys = nullptr;
    CUDA_CHECK(reallocp(h->d_act_vec_len, sizeof(float4)));
    CUDA_CHECK(reallocp(h->d_act_senders, sizeof(int)));
    CUDA_CHECK(reallocp(h->d_act_receivers, sizeof(int)));
    CUDA_CHECK(reallocp(h->d_act_slab, sizeof(int)));
    CUDA_CHECK(reallocp(h->d_act_t_sx, sizeof(float2)));
    CUDA_CHECK(reallocp(h->d_tmp_vec_len, sizeof(float4)));
    CUDA_CHECK(reallocp(h->d_edge_force_1, 3 * sizeof(float)));
    int* tmp4 = reinterpret_cast<int*>(h->d_tmp_vec_len);
    h->d_tmp_snd = tmp4;
    h->d_sort_keys = reinterpret_cast<uint32_t*>(tmp4 + (size_t)cap);
    h->d_tmp_shifts = reinterpret_cast<int*>(h->d_edge_force_1);
    h->gen->ensure_edges(cap);
    h->E_cap = cap;
    return 0;
}

// The variable-cell step's integer image shifts (d_cell_codes, 4 B per edge), allocated only by variable-cell runs.
// Outside capture; captured graphs bake the pointer in.
static int ensure_cell_codes(LoupHandle* h) {
    if (h->cell_codes_cap >= h->E_cap && h->d_cell_codes) return 0;
    h->invalidate_graphs();
    if (h->d_cell_codes) cudaFree(h->d_cell_codes);
    h->d_cell_codes = nullptr;
    h->cell_codes_cap = 0;
    CUDA_CHECK(cudaMalloc(&h->d_cell_codes, (size_t)h->E_cap * sizeof(char4)));
    h->cell_codes_cap = h->E_cap;
    return 0;
}

static int ensure_cub_tmp(LoupHandle* h, size_t bytes) {
    if (bytes <= h->cub_tmp_bytes) return 0;
    // Queued work (a scan earlier in this rebuild, or the MD step still in flight) may still use the old
    // buffer: wait for it before the free. Growth is rare (only the first rebuilds of a system reach it).
    CUDA_CHECK(cudaStreamSynchronize(h->stream));
    if (h->d_cub_tmp) cudaFree(h->d_cub_tmp);
    h->d_cub_tmp = nullptr;
    h->cub_tmp_bytes = 0;
    CUDA_CHECK(loup::device_malloc(&h->d_cub_tmp, bytes));
    h->cub_tmp_bytes = bytes;
    h->invalidate_graphs();  // the force pass's scan bakes d_cub_tmp into the captured graph
    return 0;
}

// The device's cell from the host's, with the list's reference at this cell (at the end of a rebuild).
static int upload_cell_dev(LoupHandle* h) {
    loup::CellDev& c = h->celldev_host;
    for (int i = 0; i < 9; ++i) {
        c.h[i] = h->cell.c[i];
        c.ref_inv[i] = h->cell.inv[i];
        c.f[i] = c.move[i] = (i % 4 == 0) ? 1.0 : 0.0;
    }
    c.row_scale[0] = c.row_scale[1] = c.row_scale[2] = 1.0;
    c.r_max = (double)h->cutoff();
    c.r_list = c.r_max + h->skin;
    c.thr = 0.5 * h->skin;
    c.volume = h->cell_vol;
    c.v0 = h->cell_v0 > 0.0 ? h->cell_v0 : h->cell_vol;
    c.has_move = 0;
    c.pad = 0;
    CUDA_CHECK(cudaMemcpyAsync(h->d_celldev, &c, sizeof(c), cudaMemcpyHostToDevice, h->stream));
    return 0;
}

// The host's cell from the device's: before a rebuild inside a variable-cell run and at the end of one.
static int download_cell_dev(LoupHandle* h, loup::CellDev* out = nullptr) {
    loup::CellDev c;
    CUDA_CHECK(cudaStreamSynchronize(h->stream));
    CUDA_CHECK(cudaMemcpy(&c, h->d_celldev, sizeof(c), cudaMemcpyDeviceToHost));
    bool finite = true;
    for (int i = 0; i < 9; ++i) finite = finite && std::isfinite(c.h[i]);
    if (finite) {
        memcpy(h->cell_in, c.h, sizeof(h->cell_in));
        loup::compute_cell_mat(c.h, h->cell, h->cell_vol, h->cell_heights);
        if (h->d_disp_cell)
            CUDA_CHECK(cudaMemcpy(h->d_disp_cell, h->cell_in, sizeof(h->cell_in), cudaMemcpyHostToDevice));
    }
    if (out) *out = c;
    return 0;
}

// The dispersion term for the handle's system: the atomic numbers in the device's row order (rows stay grouped by
// species, so they do not change at a rebuild) and the host's cell. Outside capture.
static int prepare_dispersion(LoupHandle* h) {
    if (!h->disp || h->N <= 0) return 0;
    if (h->n_ghost > 0) {
        loup::set_error("the dispersion term has no open domains (PLAN.md S6-D09)");
        return -1;
    }
    std::vector<int32_t> z(h->N);
    for (int s = 0; s < h->n_species(); ++s)
        for (int k = h->species_start[s]; k < h->species_start[s + 1]; ++k) z[k] = h->species_z(s);
    if (!h->d_disp_cell) CUDA_CHECK(cudaMalloc(&h->d_disp_cell, 9 * sizeof(double)));
    try {
        h->disp->prepare(h->N, z.data(), h->cell_in, h->stream);
    } catch (const std::exception& e) {
        loup::set_error("%s", e.what());
        return -1;
    }
    CUDA_CHECK(cudaMemcpyAsync(h->d_disp_cell, h->cell_in, sizeof(h->cell_in), cudaMemcpyHostToDevice, h->stream));
    CUDA_CHECK(cudaStreamSynchronize(h->stream));
    h->disp_ready = true;
    h->invalidate_graphs();
    return 0;
}

// After the host's cell changed: the term's copy, and the first preparation for a new system.
static int dispersion_cell_changed(LoupHandle* h) {
    if (!h->disp) return 0;
    if (!h->disp_ready) return prepare_dispersion(h);
    CUDA_CHECK(cudaMemcpyAsync(h->d_disp_cell, h->cell_in, sizeof(h->cell_in), cudaMemcpyHostToDevice, h->stream));
    return 0;
}

extern "C++" {
// The sum of n int degrees in 64 bits (*out is zeroed by the caller).
__global__ void sum_degrees_kernel(int n, const int* __restrict__ deg, unsigned long long* __restrict__ out) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    unsigned long long d = i < n ? (unsigned long long)(unsigned)deg[i] : 0ull;
    for (int o = 16; o > 0; o >>= 1) d += __shfl_down_sync(0xffffffffu, d, o);
    if ((threadIdx.x & 31) == 0 && d) atomicAdd(out, d);
}
}  // extern "C++"

// Queue loup::publish_kernel(a, b, c) on the main stream (outside capture); returns the counter value it will post.
static unsigned int publish(LoupHandle* h, const int* a, const int* b, const int* c) {
    loup::publish_kernel<<<1, 1, 0, h->stream>>>(a, b, c, h->d_pub_counter, h->d_pub);
    return ++h->pub_count;
}

// Polls the mapped publish slot of publication `want` until it has landed, then copies its values to out[0..2]. The
// stream is queried every few thousand polls so a failed kernel or an emptied queue cannot hang the host.
static int wait_published(LoupHandle* h, unsigned int want, int out[3]) {
    volatile int* p = h->h_pub + 4 * (want & 3u);
    volatile unsigned int* seq = reinterpret_cast<volatile unsigned int*>(p);
    for (unsigned int spins = 1; *seq != want; ++spins) {
        if ((spins & 4095) == 0) {
            const cudaError_t e = cudaStreamQuery(h->stream);
            if (e == cudaSuccess && *seq != want) {
                fprintf(stderr, "loupmd: publish %u never landed (slot has %u)\n", want, *seq);
                return -1;
            }
            if (e != cudaSuccess && e != cudaErrorNotReady) CUDA_CHECK(e);
        }
        __builtin_ia32_pause();
    }
    __atomic_thread_fence(__ATOMIC_ACQUIRE);
    out[0] = p[1];
    out[1] = p[2];
    out[2] = p[3];
    return 0;
}

// Reads up to three device ints at the current end of the main stream (polling the mapped publish words).
static int read_device_ints(LoupHandle* h, const int* a, const int* b, const int* c, int out[3]) {
    return wait_published(h, publish(h, a, b, c), out);
}

static int order_error() {
    fprintf(stderr, "LoupMD: neighbour rows are not grouped by ascending sender species\n");
    return -1;
}

// Geometry of one neighbour-list build for the current cell, skin and N: bin grid, scan ranges, kernel shapes. An
// open domain's ghosts (rows N .. NT - 1) are binned and found as senders like every atom (gridNT); only the first N
// rows are receivers (count, fill and sort).
struct NlGeom {
    int nx, ny, nz, n_bins, rx, ry, rz, gridN, gridNT, NT, blkN, gridNb;
    bool nb_groups;
    size_t nb_smem;
    double r_list2;
    float r_lo2_f32, r_hi2_f32;
};
static constexpr int kNlBlk = 128;

static NlGeom nl_geom(const LoupHandle* h) {
    NlGeom g;
    const int N = h->N;
    const double r_list = (double)h->cutoff() + h->skin;
    g.r_list2 = r_list * r_list;
    g.nx = std::max(1, (int)std::floor(h->cell_heights[0] / 3.25));
    g.ny = std::max(1, (int)std::floor(h->cell_heights[1] / 3.25));
    g.nz = std::max(1, (int)std::floor(h->cell_heights[2] / 3.25));
    while ((int64_t)g.nx * g.ny * g.nz > h->max_bins) {
        if (g.nx >= g.ny && g.nx >= g.nz && g.nx > 1) --g.nx;
        else if (g.ny >= g.nx && g.ny >= g.nz && g.ny > 1) --g.ny;
        else if (g.nz > 1) --g.nz;
        else break;
    }
    g.n_bins = g.nx * g.ny * g.nz;
    g.rx = (int)std::ceil(r_list * g.nx / h->cell_heights[0]);
    g.ry = (int)std::ceil(r_list * g.ny / h->cell_heights[1]);
    g.rz = (int)std::ceil(r_list * g.nz / h->cell_heights[2]);
    g.gridN = (N + kNlBlk - 1) / kNlBlk;
    g.NT = N + h->n_ghost;
    g.gridNT = (g.NT + kNlBlk - 1) / kNlBlk;
    const double max_h = std::max({h->cell_heights[0], h->cell_heights[1], h->cell_heights[2]});
    const float margin = std::max(0.01f, 1e-4f * (float)max_h);
    const float r_lo_f = std::max(0.0f, (float)r_list - margin);
    const float r_hi_f = (float)r_list + margin;
    g.r_lo2_f32 = r_lo_f * r_lo_f;
    g.r_hi2_f32 = r_hi_f * r_hi_f;
    // count / fill: on sm_120 kNeighborLanes lanes per atom (128-thread blocks hold whole lane groups; fill keeps one
    // nscan-int bin-offset table per atom in shared memory); elsewhere, or when that table would exceed 48 KB, the
    // one-thread-per-atom kernels (32-thread blocks), which the lane-group kernels were not measured against.
    const int nscan = (2 * g.rx + 1) * (2 * g.ry + 1) * (2 * g.rz + 1);
    g.nb_smem = (size_t)(128 / loup::kNeighborLanes) * nscan * sizeof(int);
    g.nb_groups = h->nb_groups_ok && g.nb_smem <= 48 * 1024;
    g.blkN = g.nb_groups ? 128 : 32;
    g.gridNb = (int)(((int64_t)N * (g.nb_groups ? loup::kNeighborLanes : 1) + g.blkN - 1) / g.blkN);
    return g;
}

// Scratch of nl_count's two scans.
static size_t nl_cub_bytes(LoupHandle* h, const NlGeom& g) {
    size_t scan_bytes = 0, scanN_bytes = 0;
    cub::DeviceScan::ExclusiveSum(nullptr, scan_bytes, h->d_bin_counts, h->d_bin_offsets, g.n_bins + 1, h->stream);
    cub::DeviceScan::ExclusiveSum(nullptr, scanN_bytes, h->d_deg, h->d_row_ptr, h->N + 1, h->stream);
    return std::max(scan_bytes, scanN_bytes);
}

// Wrapped positions and per-bin atom counts; zeroes the scans' totals, the row-order flag and the longest-row slot
// (kernels, not memset / memcpy nodes: the MD step graph launches this branch from the device, where copy nodes cost
// tens of microseconds each under WSL2).
static int nl_bin(LoupHandle* h, const NlGeom& g) {
    loup::nl_reset_kernel<<<(g.n_bins + 1 + 255) / 256, 256, 0, h->stream>>>(
        g.n_bins, h->d_bin_counts, h->d_deg + h->N, h->d_order_err, h->d_max_deg);
    loup::wrap_and_bin_kernel<<<g.gridNT, kNlBlk, 0, h->stream>>>(
        g.NT, h->cell, g.nx, g.ny, g.nz, h->d_pos64, h->d_pos_wrapped, h->d_atom_wrap, h->d_atom_bin, h->d_bin_counts);
    return 0;
}

// Bin offsets and slots, neighbour counts, row_ptr (edge count in row_ptr[N]) and the longest row. No host round
// trip (d_cub_tmp must hold nl_cub_bytes), so run_md_loop captures it.
static int nl_count(LoupHandle* h, const NlGeom& g) {
    const int N = h->N;
    size_t scan_bytes = h->cub_tmp_bytes;
    cub::DeviceScan::ExclusiveSum(h->d_cub_tmp, scan_bytes, h->d_bin_counts, h->d_bin_offsets, g.n_bins + 1, h->stream);
    loup::copy_ints_kernel<<<(g.n_bins + 255) / 256, 256, 0, h->stream>>>(g.n_bins, h->d_bin_offsets, h->d_bin_cursor);
    loup::scatter_bins_kernel<<<g.gridNT, kNlBlk, 0, h->stream>>>(
        g.NT, h->d_pos_wrapped, h->d_atom_wrap, h->d_species, h->d_atom_bin, h->d_bin_cursor,
        h->d_bin_atom_id, h->d_bin_pos, h->d_bin_pos_f32, h->d_bin_wrap, h->d_bin_sp);
    if (g.nb_groups)
        loup::count_neighbors_kernel<<<g.gridNb, g.blkN, 0, h->stream>>>(
            N, h->cell, g.nx, g.ny, g.nz, g.rx, g.ry, g.rz, g.r_list2, g.r_lo2_f32, g.r_hi2_f32, h->d_pos_wrapped,
            h->d_atom_bin, h->d_bin_offsets, h->d_bin_atom_id, h->d_bin_pos, h->d_bin_pos_f32, h->d_deg);
    else
        loup::count_neighbors_scalar_kernel<<<g.gridNb, g.blkN, 0, h->stream>>>(
            N, h->cell, g.nx, g.ny, g.nz, g.rx, g.ry, g.rz, g.r_list2, g.r_lo2_f32, g.r_hi2_f32, h->d_pos_wrapped,
            h->d_atom_bin, h->d_bin_offsets, h->d_bin_atom_id, h->d_bin_pos, h->d_bin_pos_f32, h->d_deg);
    size_t scanN_bytes = h->cub_tmp_bytes;
    cub::DeviceScan::ExclusiveSum(h->d_cub_tmp, scanN_bytes, h->d_deg, h->d_row_ptr, N + 1, h->stream);
    loup::max_degree_kernel<<<(N + 255) / 256, 256, 0, h->stream>>>(N, h->d_deg, h->d_max_deg);
    return 0;
}

// Smallest power of two >= n (the row sort's width).
static int pow2_at_least(int n) {
    int p = 1;
    while (p < n) p <<= 1;
    return p;
}

// Fills the rows into the edge arrays (capacity >= the edge count), then sorts each receiver's row by key
// (sym_pair << 19 | length bits), ties in fill order, and gathers it. Contract: for a fixed receiver sym_pair grows
// with the sender species, so every row ends up grouped by ascending sender species, which the receiver-owned
// first_fwd_kernel (layer0_kernels.cuh) relies on (it writes each species slot once); the sort kernel flags a row that
// breaks it (a changed key or sym_pair would otherwise corrupt S0 silently). P: the sort width, a power of two >= the
// longest row; rows of P <= 4096 sort in shared memory. go: the MD step graph's rebuild verdict (nullptr: always).
static int nl_fill(LoupHandle* h, const NlGeom& g, int P, const int* go = nullptr) {
    const int N = h->N;
    const int S = h->n_species();
    if (g.nb_groups)
        loup::fill_neighbors_kernel<<<g.gridNb, g.blkN, g.nb_smem, h->stream>>>(
            N, S, h->cell, g.nx, g.ny, g.nz, g.rx, g.ry, g.rz, g.r_list2, g.r_lo2_f32, g.r_hi2_f32,
            h->d_pos_wrapped, h->d_atom_wrap, h->d_species, h->d_atom_bin,
            h->d_bin_offsets, h->d_bin_atom_id, h->d_bin_pos, h->d_bin_pos_f32, h->d_bin_wrap, h->d_bin_sp,
            h->d_row_ptr, h->d_tmp_snd, h->d_tmp_shifts, h->d_sort_keys, go);
    else
        loup::fill_neighbors_scalar_kernel<<<g.gridNb, g.blkN, 0, h->stream>>>(
            N, S, h->cell, g.nx, g.ny, g.nz, g.rx, g.ry, g.rz, g.r_list2, g.r_lo2_f32, g.r_hi2_f32,
            h->d_pos_wrapped, h->d_atom_wrap, h->d_species, h->d_atom_bin,
            h->d_bin_offsets, h->d_bin_atom_id, h->d_bin_pos, h->d_bin_pos_f32, h->d_bin_wrap, h->d_bin_sp,
            h->d_row_ptr, h->d_tmp_snd, h->d_tmp_shifts, h->d_sort_keys, go);
    const int threads = std::min(256, std::max(32, P / 2));
    if (P <= 4096 && !h->ovr.row_sort_global)
        loup::sort_gather_rows_kernel<<<N, threads, P * sizeof(unsigned long long), h->stream>>>(
            h->cell, h->d_row_ptr, h->d_sort_keys, h->d_tmp_snd, h->d_tmp_shifts, h->d_species, h->d_senders,
            h->d_shift_cart, h->d_order_err, go);
    else  // scratch: act_vec_len (16 B per edge) is per-step data, free during a rebuild
        loup::sort_gather_rows_global_kernel<<<N, threads, 0, h->stream>>>(
            h->cell, h->d_row_ptr, h->d_sort_keys, h->d_tmp_snd, h->d_tmp_shifts, h->d_species, h->d_senders,
            h->d_shift_cart, h->d_order_err,
            reinterpret_cast<unsigned long long*>(h->d_act_vec_len));
    return 0;
}

// The list is now the one built at the current positions: they become the reference, and the skin flag clears.
static int nl_commit(LoupHandle* h, const int* go = nullptr) {
    const int n = (h->N + h->n_ghost) * 3;
    loup::nl_commit_kernel<<<(n + 255) / 256, 256, 0, h->stream>>>(n, h->d_pos64, h->d_ref_pos64, h->d_need_rebuild,
                                                                   go);
    return 0;
}

// LOUP_DEBUG_PLAN=1: the device's free memory at a named point of a whole system's set-up and first call (where its
// memory goes), and loup_plan_memory's counters.
static void plan_dbg(const char* what) {
    static const bool on = std::getenv("LOUP_DEBUG_PLAN") != nullptr;
    if (!on) return;
    size_t f = 0, t = 0;
    device_memory(&f, &t);
    std::fprintf(stderr, "plan debug: %-28s %8.1f MB free\n", what, f / 1048576.0);
}

// Host decisions after nl_count (edge capacity, the graphs' edge bucket), then fill, sort and commit.
static int nl_finish(LoupHandle* h, const NlGeom& g, int E_new, int max_deg, bool check_order) {
    h->E_skin = E_new;
    h->max_deg_last = max_deg;
    if (E_new > 0) {
        if (ensure_edge_capacity(h, E_new) != 0) return -1;
        if (E_new > h->E_graph || h->E_graph > E_new + 32768) {
            h->E_graph = std::min(h->E_cap, ((E_new + 8191) & ~8191));
            if (h->E_graph < E_new) h->E_graph = E_new;
            h->invalidate_graphs();
        }
        if (nl_fill(h, g, pow2_at_least(max_deg)) != 0) return -1;
        if (check_order) {
            int vals[3];
            if (read_device_ints(h, h->d_order_err, nullptr, nullptr, vals) != 0) return -1;
            if (vals[0]) return order_error();
        }
    } else if (h->E_graph != 0) {
        h->E_graph = 0;
        h->invalidate_graphs();
    }
    if (h->var_cell && E_new > 0) {
        // The variable-cell step forms the Cartesian shifts from the device's cell every step (shift_cart_kernel):
        // the integer image shifts in the edges' order, from the sorted Cartesian ones and the list's cell.
        if (ensure_cell_codes(h) != 0) return -1;
        CUDA_CHECK(cudaMemsetAsync(h->d_order_err + 2, 0, sizeof(int), h->stream));
        loup::Mat3 inv;
        for (int k = 0; k < 9; ++k) inv.m[k] = h->cell.inv[k];
        loup::cell_shift_codes_kernel<<<(E_new + 255) / 256, 256, 0, h->stream>>>(
            E_new, inv, h->d_shift_cart, h->d_cell_codes, h->d_order_err + 2);
        int vals[3];
        if (read_device_ints(h, h->d_order_err + 2, nullptr, nullptr, vals) != 0) return -1;
        if (vals[0]) {
            loup::set_error("variable cell: an image shift of the neighbour list exceeds 127 cells");
            return -1;
        }
    }
    if (nl_commit(h) != 0) return -1;
    if (h->var_cell && upload_cell_dev(h) != 0) return -1;
    h->cell_ref_stale = false;
    CUDA_CHECK(cudaGetLastError());
    h->nl_valid = true;
    return 0;
}

// Whether rebuilds reorder the atoms spatially (see rebuild_neighbors): a host round trip, so such systems keep the
// host-driven rebuild in MD.
static bool reorder_atoms(const LoupHandle* h) {
    if (h->n_ghost > 0) return false;  // a domain's rows are its caller's
    return h->ovr.reorder >= 0 ? h->ovr.reorder == 1 : (int64_t)h->N * 4096 > (int64_t)h->l2_bytes;
}

// check_order = false (run_md_loop) leaves the sort's contract flag in d_order_err for the caller's next read.
static int rebuild_neighbors(LoupHandle* h, bool check_order = true) {
    h->nl_valid = false;  // set again only when the rebuild completes
    const int N = h->N;
    const int S = h->n_species();
    const NlGeom g = nl_geom(h);
    if (ensure_cub_tmp(h, nl_cub_bytes(h, g)) != 0) return -1;
    if (nl_bin(h, g) != 0) return -1;

    // Reorder atoms inside each species group by the Morton code of their bin, once the per-atom sender working set
    // (x0/x1 rows and their gradients, ~4 KB per atom) outgrows L2: then sender rows and sender-gradient atomics stay
    // in L2 only if neighbours in space are neighbours in memory (a shuffled 40,000-atom input is ~30 % slower
    // otherwise). Below that size the caller's order costs nothing and the reorder's extra sync is pure overhead.
    // Atoms near a bin boundary flip bins thermally, so the order is refreshed only on every 16th rebuild (diffusion
    // is slow on that scale). Per-atom state (positions, velocities, forces, masses) is gathered in place, so every
    // buffer address and every captured graph stays valid; only the host permutation changes.
    if (reorder_atoms(h) && !h->suppress_reorder && (h->n_rebuilds++ % 16) == 0) {
        unsigned long long* keys_in = h->d_ro_keys;
        unsigned long long* keys_out = h->d_ro_keys + N;
        int* vals_in = h->d_ro_vals;
        int* vals_out = h->d_ro_vals + N;
        loup::atom_order_keys_kernel<<<g.gridN, kNlBlk, 0, h->stream>>>(
            N, g.nx, g.ny, g.nz, h->d_species, h->d_atom_bin, keys_in, vals_in);
        int species_bits = 0;
        while ((1 << species_bits) < S) ++species_bits;
        const int end_bit = 48 + species_bits;  // Morton code in bits 0..47, species above
        size_t sort_bytes = 0;
        cub::DeviceRadixSort::SortPairs(nullptr, sort_bytes, keys_in, keys_out, vals_in, vals_out, N, 0, end_bit, h->stream);
        if (ensure_cub_tmp(h, sort_bytes) != 0) return -1;
        cub::DeviceRadixSort::SortPairs(h->d_cub_tmp, sort_bytes, keys_in, keys_out, vals_in, vals_out, N, 0, end_bit, h->stream);
        CUDA_CHECK(cudaMemcpyAsync(h->h_order.data(), vals_out, N * sizeof(int), cudaMemcpyDeviceToHost, h->stream));
        CUDA_CHECK(cudaStreamSynchronize(h->stream));
        bool identity = true;
        for (int i = 0; i < N && identity; ++i) identity = h->h_order[i] == i;
        if (!identity) {
            auto gather = [&](double* arr, int width) -> int {
                loup::gather_rows_f64_kernel<<<(N * width + 255) / 256, 256, 0, h->stream>>>(
                    N, width, vals_out, arr, h->d_ro_tmp);
                CUDA_CHECK(cudaMemcpyAsync(arr, h->d_ro_tmp, (size_t)N * width * sizeof(double),
                                           cudaMemcpyDeviceToDevice, h->stream));
                return 0;
            };
            // d_rnd_vel: a rebuild in a Langevin step falls between the half-kicks, and the second one
            // must reuse the noise the first drew for the same atom.
            if (gather(h->d_pos64, 3) || gather(h->d_vel64, 3) || gather(h->d_forces_f64, 3) ||
                gather(h->d_masses, 1) || gather(h->d_inv_masses, 1) || gather(h->d_sqrt_inv_masses, 1) ||
                gather(h->d_rnd_vel, 3)) return -1;
            std::vector<int> old_perm = h->perm;
            for (int i = 0; i < N; ++i) h->perm[i] = old_perm[h->h_order[i]];
            ++h->pos_epoch;  // per-atom state kept outside this function (loup_minimize's) is in the old order
            ++h->perm_epoch;
            if (nl_bin(h, g) != 0) return -1;
        }
    }

    if (nl_count(h, g) != 0) return -1;
    // The 64-bit edge total: row_ptr's int scan wraps past 2^31 edges.
    if (!h->d_edge_total) CUDA_CHECK(cudaMalloc(&h->d_edge_total, sizeof(unsigned long long)));
    CUDA_CHECK(cudaMemsetAsync(h->d_edge_total, 0, sizeof(unsigned long long), h->stream));
    sum_degrees_kernel<<<(N + 255) / 256, 256, 0, h->stream>>>(N, h->d_deg, h->d_edge_total);
    int vals[3], tot[3];
    if (read_device_ints(h, h->d_row_ptr + N, h->d_max_deg, nullptr, vals) != 0) return -1;
    const int* et = reinterpret_cast<const int*>(h->d_edge_total);
    if (read_device_ints(h, et, et + 1, nullptr, tot) != 0) return -1;
    const unsigned long long E_total =
        (unsigned long long)(unsigned)tot[0] | ((unsigned long long)(unsigned)tot[1] << 32);
    if (E_total > (unsigned long long)h->edge_limit) {
        loup::set_error("the neighbour list has %llu edges, more than the %lld one call can index; run the system "
                        "in tiles (capacity 'auto' or 'tiled')", E_total, h->edge_limit);
        return -1;
    }
    return nl_finish(h, g, vals[0], vals[1], check_order);
}

// Fork: side streams wait for everything queued on the main stream so far.
static void gemm_fork(LoupHandle* h) {
    if (!h->fork_ok) return;
    CUDA_CHECK_THROW(cudaEventRecord(h->ev_fork, h->stream));
    for (int i = 0; i < LoupHandle::kSide; ++i) CUDA_CHECK_THROW(cudaStreamWaitEvent(h->side[i], h->ev_fork, 0));
}

// Route the following sgemm_rm calls to side stream `lane` (calls on one lane stay ordered).
static void gemm_lane(LoupHandle* h, int lane) {
    if (!h->fork_ok) return;
    h->gemm_stream = h->side[lane % LoupHandle::kSide];
    h->gemm_ws = h->side_ws[lane % LoupHandle::kSide];
}

// Join: the main stream waits for every side stream; GEMMs go back to the main stream.
static void gemm_join(LoupHandle* h) {
    if (!h->fork_ok) return;
    for (int i = 0; i < LoupHandle::kSide; ++i) {
        CUDA_CHECK_THROW(cudaEventRecord(h->ev_join[i], h->side[i]));
        CUDA_CHECK_THROW(cudaStreamWaitEvent(h->stream, h->ev_join[i], 0));
    }
    h->gemm_stream = nullptr;
    h->gemm_ws = nullptr;
}

// Kernel variants whose ranking depends on the system, timed once per system at the first MD rebuild (thermalised
// positions) on the last force pass's inputs: the generic layers' conv forward variants
// (GenericModel::tune_conv_variants). The time spent is reported as LoupMDStats::tune_ms and excluded from step_ms.
static void tune_rebuild_variants(LoupHandle* h) {
    if (h->variants_tuned) return;
    // No pair inside r_max + skin: the active-edge arrays were never written. Time later, on a list with edges.
    if (h->E_graph == 0) return;
    const int r = h->gen->tune_conv_variants(h->stream);
    if (r < 0) return;  // no force pass recorded for this system yet: time at a later rebuild
    h->variants_tuned = true;
    if (r > 0) h->invalidate_graphs();
}

// A system whose list is not rebuilt within kTuneEarlyPasses force passes (a solid near its lattice, a short run, NPT
// through LAMMPS's pair style, where every call rebuilds on the host and no MD step's rebuild comes) would keep the
// default variants: they are timed then instead, on the last pass's inputs, after the call's step or evaluation; the
// first rebuild, if one comes, times them again on thermalised positions (timing at set-up picked wrongly for NbCl5,
// the ledger's spl-multi-receiver). Counts the pass it follows; returns the milliseconds spent (0 if nothing ran). The
// stream must be free to wait on (nothing armed behind cuStreamWaitValue32).
constexpr long long kTuneEarlyPasses = 50;
static double tune_early_variants(LoupHandle* h) {
    if (h->variants_tuned || h->variants_early) return 0.0;
    if (++h->passes_untuned < kTuneEarlyPasses || h->E_graph == 0 || !h->gen) return 0.0;
    CUDA_CHECK_THROW(cudaStreamSynchronize(h->stream));  // the step may still run: its time is not the timing's
    const auto t0 = std::chrono::steady_clock::now();
    const int r = h->gen->tune_conv_variants(h->stream);
    if (r < 0) return 0.0;  // no force pass recorded yet: try after the next one
    h->variants_early = true;
    if (r > 0) h->invalidate_graphs();
    return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
}

// One sweep of the generic pass (GenericPassInputs::Sweep), for a driver that runs a domain sweep by sweep.
struct DomainSweep {
    int kind = 0, layer = 0;
    const float* adjoint[4] = {nullptr, nullptr, nullptr, nullptr};
    bool active_ready = false;  // the handle's active-edge buffers already hold this domain's (a tile's later sweep)
    float* keep0 = nullptr;     // O31: the domain's buffer of layer 0's msgf and D (GenericPassInputs::keep0)
    // O32 compact slots: after the compaction, pack each active edge's integer image shift (from the list's `pack_in`)
    // into `pack_out`; or, instead of the compaction, restore the active edges from row pointers and senders already
    // in the handle's active buffers and the shifts in `restore_code`
    const char4* pack_in = nullptr;
    char4* pack_out = nullptr;
    const char4* restore_code = nullptr;
};
__global__ void tile_pack_active_codes_kernel(int N, float r_max, const int* __restrict__ row_ptr,
                                              const int* __restrict__ act_row_ptr,
                                              const float4* __restrict__ tmp_vec_len,
                                              const char4* __restrict__ code, char4* __restrict__ act_code);
__global__ void tile_restore_active_kernel(int N, SplineGrid grid, int S, int pair_sym, loup::CellMat64 cell,
                                           const double* __restrict__ pos64, const int* __restrict__ species,
                                           const int* __restrict__ act_row_ptr, const int* __restrict__ act_senders,
                                           const char4* __restrict__ act_code, int* __restrict__ act_receivers,
                                           float4* __restrict__ act_vec_len, int* __restrict__ act_slab,
                                           float2* __restrict__ act_t_sx);

static_assert(offsetof(loup::CellDev, h) == 0, "record_dispersion reads the device cell at the start of CellDev");

// The dispersion term's share of a whole-system pass, after the model's (which zeroes the accumulators first).
static void record_dispersion(LoupHandle* h, int compute_stress, bool energy_only) {
    if (!h->disp) return;
    if (!h->disp_ready) throw std::logic_error("the dispersion term was not prepared for this system");
    loup::dispersion::Inputs in{h->stream, h->d_pos64,
                                h->disp_cell_dev ? reinterpret_cast<const double*>(h->d_celldev)   // CellDev::h is its first field
                                                  : static_cast<const double*>(h->d_disp_cell),
                                !energy_only, compute_stress != 0 && !energy_only};
    loup::dispersion::Outputs out{h->d_energy_f64, energy_only ? h->pass_atom_energy : nullptr,
                                  energy_only ? nullptr : h->d_forces_f64,
                                  compute_stress && !energy_only ? h->d_virial_grad_f64 : nullptr};
    h->disp->record(in, out);
}

static void record_force_pass(LoupHandle* h, int compute_stress, bool energy_only = false,
                              const DomainSweep* sweep = nullptr) {
    if (h->disp && sweep) throw std::logic_error("the dispersion term has no domain sweeps (PLAN.md S6-D09)");
    const int N = h->N;
    const int S = h->n_species();
    const float r_max = h->cutoff();

    // A sweep adds to energy, forces and virial: its driver zeroes them once.
    if (!sweep) CUDA_CHECK_THROW(cudaMemsetAsync(h->d_zero_slab, 0, h->zero_slab_bytes, h->stream));
    // With no pair within r_max + skin the pass still runs, on the empty edge list: a model can have an energy per
    // isolated atom (residual first block, readout biases, the long-range term: MACE-MH-1 0.56 eV and MACE-POLAR-1-S
    // 0.64 eV).

    SplineGrid sg{};
    int sg_psym = 1;
    if (const SplineGrid* pg = h->gen->preloc_grid()) {
        sg = *pg;
        sg_psym = h->gen->preloc_pair_sym();
    } else {
        sg.n_bands = 1;
        sg.total_intervals = 1;
        sg.counts[0] = 1;
        sg.ends[0] = r_max;
        sg.inv_h[0] = 1.0f / r_max;
    }

    // 1. Compute edge vectors, compact active edges (r < r_max) with their spline locator
    const int warpGridN = (N + 3) / 4;  // 4 warps per 128-thread block (1 warp per atom)
    if (sweep && sweep->restore_code) {
        tile_restore_active_kernel<<<warpGridN, 128, 0, h->stream>>>(
            N, sg, S, sg_psym, h->cell, h->d_pos64, h->d_species, h->d_act_row_ptr, h->d_act_senders,
            sweep->restore_code, h->d_act_receivers, h->d_act_vec_len, h->d_act_slab, h->d_act_t_sx);
    } else if (!(sweep && sweep->active_ready)) {
        loup::compute_and_count_active_kernel<<<warpGridN, 128, 0, h->stream>>>(
            N, r_max, h->d_pos64, h->d_row_ptr, h->d_senders, h->d_shift_cart,
            h->d_tmp_vec_len, h->d_act_deg);
        size_t act_scan_bytes = h->cub_tmp_bytes;
        cub::DeviceScan::ExclusiveSum(
            h->d_cub_tmp, act_scan_bytes, h->d_act_deg, h->d_act_row_ptr, N + 1, h->stream);
        loup::scatter_active_edges_kernel<<<warpGridN, 128, 0, h->stream>>>(
            N, r_max, sg, S, sg_psym, h->d_species, h->d_row_ptr, h->d_act_row_ptr, h->d_senders,
            h->d_tmp_vec_len, h->d_act_senders, h->d_act_receivers, h->d_act_vec_len,
            h->d_act_slab, h->d_act_t_sx);
        if (sweep && sweep->pack_out)
            tile_pack_active_codes_kernel<<<warpGridN, 128, 0, h->stream>>>(
                N, r_max, h->d_row_ptr, h->d_act_row_ptr, h->d_tmp_vec_len, sweep->pack_in, sweep->pack_out);
    }

    const int* d_E_act = h->d_act_row_ptr + N;
    loup::GenericPassInputs in{};
    in.stream = h->stream;
    in.N = N;
    in.n_ghost = h->n_ghost;
    if (sweep) {
        in.sweep = sweep->kind;
        in.sweep_layer = sweep->layer;
        for (int l = 0; l < 4; ++l) in.adjoint_in[l] = sweep->adjoint[l];
        in.keep0 = sweep->keep0;
    }
    in.E_dev = d_E_act;
    in.E_cap = h->E_cap;
    in.act_row_ptr = h->d_act_row_ptr;
    in.act_senders = h->d_act_senders;
    in.act_receivers = h->d_act_receivers;
    in.act_vec_len = h->d_act_vec_len;
    in.act_slab = h->d_act_slab;
    in.act_t_sx = h->d_act_t_sx;
    in.species = h->d_species;
    in.species_start = &h->species_start;
    in.species_count = &h->species_count;
    in.energy = h->d_energy_f64;
    in.forces = h->d_forces_f64;
    in.virial = h->d_virial_grad_f64;
    in.compute_stress = compute_stress;
    in.energy_only = energy_only ? 1 : 0;
    in.atom_energy = energy_only ? h->pass_atom_energy : nullptr;
    in.pos64 = h->d_pos64;
    in.gemm = [h](bool transB, int M, int Nc, int K, float alpha, const float* A, int lda, const float* B, int ldb,
                  float beta, float* C, int ldc) {
        sgemm_rm(h, false, transB, M, Nc, K, alpha, A, lda, B, ldb, beta, C, ldc);
    };
    in.gemm_fork = [h] { gemm_fork(h); };
    in.gemm_lane = [h](int lane) { gemm_lane(h, lane); };
    in.gemm_join = [h] { gemm_join(h); };
    if (h->gate_fuse)
        in.gemm_gate_bwd = [h](int l, int M, int Nc, int K, const float* A, const float* B,
                               const loup::GateArgs& g) { return gemm_gate(h, false, l, M, Nc, K, A, B, g); };
    if (h->gate_fuse_fwd)
        in.gemm_gate_fwd = [h](int l, int M, int Nc, int K, const float* A, const float* B,
                               const loup::GateArgs& g) { return gemm_gate(h, true, l, M, Nc, K, A, B, g); };
    h->gen->record(in);
    if (!sweep) record_dispersion(h, compute_stress, energy_only);
}

// Graph captures and other threads (the tests' fast-tier segmentation fault, 20 November 2026; STATUS §6.39). Python's
// garbage collector can run one engine's loup_destroy in one of the package's output writer threads while another
// engine captures its graphs in the main thread. Two things break such a capture:
// - In CUDA's global capture mode any potentially unsafe call in any thread (a cudaFree of the destroy) invalidates
//   it. Every graph is therefore captured in thread-local mode, where only the capturing thread's own calls are
//   checked.
// - A device-wide synchronisation invalidates every capture in progress on the device, in any mode, and so does work
//   on the legacy default stream, which waits for every blocking stream (h->stream is one). cuBLAS's handle
//   destruction synchronises the device (cuBLAS documents it), and so do the release of a tiled state and the load
//   of a bundle, which also copies on the legacy stream. Measured: with cublasDestroy left out of loup_destroy, 40
//   runs with a destroy in another thread came through, and none did with it.
// DeviceOrder orders them process-wide: every capture holds it shared from its begin to its end (captures in several
// threads still run side by side), and loup_create, loup_set_system, loup_destroy and the release of a tiled state
// hold it exclusively. A thread that holds it already, either way, does not take it again (loup_create's failure
// path calls loup_destroy; nothing that synchronises the device may run inside a capture anyway).
// A failed capture used to stay open: a CUDA_CHECK inside it returned -1 without ending it, and the next call of the
// thread failed with "operation not permitted when stream is capturing"; the clean-up after an exception destroyed the
// graph that cudaStreamEndCapture handed back, which for a capture into a graph is the handle's or a conditional
// node's, destroyed again later ("double free or corruption"). CaptureScope ends every capture on every path.
constexpr cudaStreamCaptureMode kCaptureMode = cudaStreamCaptureModeThreadLocal;

static std::shared_mutex g_device_order;
static thread_local int t_device_order = 0;  // > 0: this thread holds g_device_order

class DeviceOrder {
public:
    explicit DeviceOrder(bool exclusive) : exclusive_(exclusive), held_(t_device_order == 0) {
        if (held_) exclusive_ ? g_device_order.lock() : g_device_order.lock_shared();
        ++t_device_order;
        counted_ = true;
    }
    DeviceOrder(const DeviceOrder&) = delete;
    DeviceOrder& operator=(const DeviceOrder&) = delete;
    void release() {
        if (!counted_) return;
        counted_ = false;
        --t_device_order;
        if (held_) exclusive_ ? g_device_order.unlock() : g_device_order.unlock_shared();
        held_ = false;
    }
    ~DeviceOrder() { release(); }

private:
    bool exclusive_, held_, counted_ = false;
};

// One capture on h->stream, ended on every path: begin() makes a new graph (cudaStreamBeginCapture), begin_into(g)
// captures into g, which its owner (the handle, or a conditional node) keeps. A capture the scope did not end is ended
// in its destructor; the graph that comes back is destroyed only when the capture made it.
class CaptureScope {
public:
    explicit CaptureScope(LoupHandle* h) : h_(h), order_(false) {}
    CaptureScope(const CaptureScope&) = delete;
    CaptureScope& operator=(const CaptureScope&) = delete;
    cudaError_t begin() { return opened(cudaStreamBeginCapture(h_->stream, kCaptureMode), true); }
    cudaError_t begin_into(cudaGraph_t g) {
        return opened(cudaStreamBeginCaptureToGraph(h_->stream, g, nullptr, nullptr, 0, kCaptureMode), false);
    }
    cudaError_t end(cudaGraph_t* out) {
        open_ = false;
        const cudaError_t err = cudaStreamEndCapture(h_->stream, out);
        order_.release();
        return err;
    }
    ~CaptureScope() {
        if (open_) {
            cudaGraph_t g = nullptr;
            cudaStreamEndCapture(h_->stream, &g);
            if (g && own_graph_) cudaGraphDestroy(g);
            (void)cudaGetLastError();
        }
    }

private:
    cudaError_t opened(cudaError_t err, bool own_graph) {
        open_ = err == cudaSuccess;
        own_graph_ = own_graph;
        return err;
    }
    LoupHandle* h_;
    DeviceOrder order_;
    bool open_ = false, own_graph_ = false;
};

static int ensure_force_graph(LoupHandle* h, int compute_stress) {
    h->last_pass_stress = compute_stress != 0;  // every launch of the force graph comes through here first
    if (h->force_graph_exec && h->force_graph_stress == compute_stress) return 0;
    if (h->force_graph_exec) { cudaGraphExecDestroy(h->force_graph_exec); h->force_graph_exec = nullptr; }
    if (h->force_graph) { cudaGraphDestroy(h->force_graph); h->force_graph = nullptr; }

    // One uncaptured pass per system so cuBLAS allocates its internal workspaces and sgemm_rm autotunes every GEMM
    // shape (shapes depend only on N and the species counts; lt_cache is cleared with the system).
    if (h->lt_cache.empty()) {
        struct NoFork {  // autotune timings must not overlap other GEMMs
            LoupHandle* h;
            bool saved;
            explicit NoFork(LoupHandle* h_) : h(h_), saved(h_->fork_ok) { h->fork_ok = false; }
            ~NoFork() { h->fork_ok = saved; }
        } no_fork(h);
        plan_dbg("before the uncaptured pass");
        record_force_pass(h, compute_stress);
        CUDA_CHECK(cudaGetLastError());  // launch errors (e.g. no kernel image for this GPU) surface here, named
        CUDA_CHECK(cudaStreamSynchronize(h->stream));
        h->save_disk_plans();
        plan_dbg("after the uncaptured pass");
    }

    CaptureScope cap(h);
    CUDA_CHECK(cap.begin());
    record_force_pass(h, compute_stress);
    CUDA_CHECK(cap.end(&h->force_graph));
    plan_dbg("after the capture");
    CUDA_CHECK(cudaGraphInstantiate(&h->force_graph_exec, h->force_graph, nullptr, nullptr, 0));
    plan_dbg("after the instantiation");
    h->force_graph_stress = compute_stress;
    return 0;
}

// The energy-only graph. The uncaptured tuning pass is the full one of ensure_force_graph (the energy-only pass has
// a subset of its GEMM shapes).
static int ensure_energy_graph(LoupHandle* h) {
    if (h->energy_graph_exec) return 0;
    if (h->lt_cache.empty() && ensure_force_graph(h, 0) != 0) return -1;
    if (h->energy_graph) { cudaGraphDestroy(h->energy_graph); h->energy_graph = nullptr; }
    CaptureScope cap(h);
    CUDA_CHECK(cap.begin());
    record_force_pass(h, 0, true);
    CUDA_CHECK(cap.end(&h->energy_graph));
    CUDA_CHECK(cudaGraphInstantiate(&h->energy_graph_exec, h->energy_graph, nullptr, nullptr, 0));
    return 0;
}

// The error channel (loup_last_error). A failing call leaves "<entry point>: <reason>" in its handle, or in this
// thread-local string when there is no handle (loup_create, a NULL handle). The reason is the message a refusal or
// a CUDA_CHECK recorded with loup::set_error, or the text of the exception. Nothing goes to stderr unless
// LOUP_DEBUG_ERRORS is set.
static thread_local std::string tl_null_error;

static void store_error(LoupHandle* h, const char* name) {
    std::string& pending = loup::pending_error();
    std::string msg = std::string(name) + ": " + (pending.empty() ? "failed without a message" : pending);
    pending.clear();
    if (std::getenv("LOUP_DEBUG_ERRORS")) fprintf(stderr, "%s\n", msg.c_str());
    (h ? h->last_error : tl_null_error) = std::move(msg);
}

// run_md_loop's step kinds beyond the integrators (LOUP_NVE .. LOUP_MTK_NPT are 0 .. 7): the steps of a caller that
// integrates itself. A step is the list check and the force pass, with the guard, the on-device rebuild and the host
// fallback of an MD step.
constexpr int kStepDevice = 8;  // loup_compute_device: on positions the caller wrote on the device
constexpr int kStepHost = 9;    // loup_evaluate: with the upload from the staging first and the results' copy last

extern "C" {  // as its definition below, inside the entry points' block
static int run_host_step(LoupHandle* h, int stress);  // one kStepHost step (after run_md_loop)
}

// cuStreamWaitValue32 of the driver library (looked up at run time, as the GEMM cubin's calls are): work queued on
// the stream after it runs once the device reads *addr >= value.
typedef CUresult (*StreamWaitValue32Fn)(CUstream, CUdeviceptr, cuuint32_t, unsigned int);
static StreamWaitValue32Fn stream_wait_value32() {
    static const StreamWaitValue32Fn fn = [] {
        void* lib = dlopen("libcuda.so.1", RTLD_LAZY);
        if (!lib) return static_cast<StreamWaitValue32Fn>(nullptr);
        void* f = dlsym(lib, "cuStreamWaitValue32_v2");  // the name cuda.h maps the call to; the unsuffixed one is v1
        if (!f) f = dlsym(lib, "cuStreamWaitValue32");
        return reinterpret_cast<StreamWaitValue32Fn>(f);
    }();
    return fn;
}

// A step that loup_evaluate queued ahead (armed) runs as a step on the positions that are staged, and its
// publications are read as usual. Every entry point other than a matching loup_evaluate calls this first.
static int settle_armed(LoupHandle* h) {
    if (!h) return 0;
    h->eval_streak = 0;
    if (!h->armed) return 0;
    return run_host_step(h, h->armed_stress);
}

// Queues the next loup_evaluate's step graph behind the wait on *h_go. Only with the host step's graphs in place for
// this virial flag and a standing list. A failure (no driver support, no mapped memory) turns the feature off.
static void arm_evaluate(LoupHandle* h, int stress) {
    // (Not with a dispersion term: its cell goes up on the stream at the head of every call, and a copy queued on
    // the waiting stream would block the host.)
    if (!h->arm_enabled || h->arm_state < 0 || h->armed || !h->nl_valid || !h->md_step_exec || h->disp ||
        h->md_graph_kind != kStepHost || h->md_graph_seed != (unsigned long long)stress)
        return;
    if (h->arm_state == 0) {
        h->arm_state = -1;
        if (!stream_wait_value32()) return;
        if (cudaHostAlloc(&h->h_go, 4096, cudaHostAllocMapped) != cudaSuccess) {
            h->h_go = nullptr;
            cudaGetLastError();
            return;
        }
        *h->h_go = 0;
        if (cudaHostGetDevicePointer(reinterpret_cast<void**>(&h->d_go), h->h_go, 0) != cudaSuccess) {
            cudaGetLastError();
            return;
        }
        h->arm_state = 1;
    }
    const unsigned int seq = h->go_seq + 1;
    if (const CUresult r = stream_wait_value32()(h->stream, reinterpret_cast<CUdeviceptr>(h->d_go), seq,
                                                 CU_STREAM_WAIT_VALUE_GEQ);
        r != CUDA_SUCCESS) {
        h->arm_state = -1;  // nothing was queued
        if (const char* d = std::getenv("LOUP_DEBUG_ARM"); d && d[0] == '1')
            fprintf(stderr, "[loupmd] loup_evaluate: no stream wait on a host word here (driver error %d); calls "
                            "launch their graph\n", (int)r);
        return;
    }
    h->go_seq = seq;
    if (cudaGraphLaunch(h->md_step_exec, h->stream) != cudaSuccess) {
        cudaGetLastError();
        __atomic_store_n(h->h_go, seq, __ATOMIC_SEQ_CST);  // the wait is queued alone: let it pass
        h->arm_state = -1;
        return;
    }
    h->armed = true;
    h->armed_stress = stress;
}

// Every exported entry point runs through this: a C++ exception (CUDA/cuBLAS failure inside record_force_pass,
// sgemm_rm or HybCubin::launch) must not unwind into the C caller, and a throw during capture must not leave the
// stream in capture mode.
// Evaluate ahead: a step that loup_evaluate queued ahead runs before anything else an entry point does
// (settle_armed), unless the entry point takes care of it itself (`keep_armed`: loup_evaluate, whose matching call
// releases the queued step as its own).
// A capture still open on h->stream (none should be: CaptureScope ends each on every path) is ended, and the graph
// that comes back is left alone: it may be the handle's or a conditional node's body (a capture into a graph), and a
// graph leaked on an error path costs nothing where a second destroy crashes. True when one was open.
static bool end_open_capture(LoupHandle* h) {
    cudaStreamCaptureStatus st = cudaStreamCaptureStatusNone;
    if (!h || !h->stream || cudaStreamIsCapturing(h->stream, &st) != cudaSuccess || st == cudaStreamCaptureStatusNone)
        return false;
    cudaGraph_t g = nullptr;
    cudaStreamEndCapture(h->stream, &g);
    (void)cudaGetLastError();
    return true;
}

template <class F>
static int guarded(LoupHandle* h, const char* name, F&& f, bool keep_armed = false) {
    loup::pending_error().clear();
    try {
        if (!h) loup::set_error("the handle is NULL");
        int rc = h ? 0 : -1;
        if (h && !keep_armed) rc = settle_armed(h);
        if (rc == 0) rc = f();
        if (rc == 0) {
            h->last_error.clear();
            return 0;
        }
        store_error(h, name);
        if (end_open_capture(h)) {  // a failure inside a capture must not leave the stream capturing
            h->drain_armed();
            h->invalidate_graphs();
            h->gemm_stream = nullptr;
            h->gemm_ws = nullptr;
        }
        return rc;
    } catch (const std::exception& e) {
        loup::pending_error() = e.what();
    } catch (...) {
        loup::pending_error() = "unknown exception";
    }
    store_error(h, name);
    if (h && h->stream) {
        end_open_capture(h);
        h->drain_armed();
        h->invalidate_graphs();
        h->gemm_stream = nullptr;  // a throw between gemm_lane and gemm_join leaves the routing on a side stream
        h->gemm_ws = nullptr;
    }
    return -1;
}

extern "C" {

LoupHandle* loup_create(const char* loup_path, int device_id) {
    const DeviceOrder order(true);  // the bundle's load synchronises the device and copies on the legacy stream
    LoupHandle* h = nullptr;
    loup::pending_error().clear();
    tl_null_error.clear();
    try {
        if (!loup_path) throw std::runtime_error("loup_path is NULL");
        CUDA_CHECK_THROW(cudaSetDevice(device_id));
        h = new LoupHandle();
        h->device_id = device_id;
        CUDA_CHECK_THROW(cudaDeviceGetAttribute(&h->l2_bytes, cudaDevAttrL2CacheSize, device_id));
        bool own_ext_env = false, cc80 = false;
        {
            int cc_maj = 0, cc_min = 0;
            CUDA_CHECK_THROW(cudaDeviceGetAttribute(&cc_maj, cudaDevAttrComputeCapabilityMajor, device_id));
            CUDA_CHECK_THROW(cudaDeviceGetAttribute(&cc_min, cudaDevAttrComputeCapabilityMinor, device_id));
            h->is_sm120 = (cc_maj == 12 && cc_min == 0);
            cc80 = cc_maj == 8 && cc_min == 0;
            h->own_ext = h->is_sm120;
            if (const char* e = std::getenv("LOUP_OWN_EXT"); e && (e[0] == '0' || e[0] == '1')) {
                h->own_ext = e[0] == '1';
                own_ext_env = true;
            }
            h->nb_groups_ok = h->is_sm120 || cc80;
            if (const char* e = std::getenv("LOUP_NB_GROUPS"); e && (e[0] == '0' || e[0] == '1')) h->nb_groups_ok = e[0] == '1';
            if (const char* e = std::getenv("LOUP_FORCE_TC"); e && e[0] == '1') h->force_tc = true;
            if (const char* e = std::getenv("LOUP_GATE_FUSE"); e && e[0] == '0') h->gate_fuse = false;
            if (const char* e = std::getenv("LOUP_GATE_FUSE_FWD"); e && e[0] == '0') h->gate_fuse_fwd = false;
            if (const char* e = std::getenv("LOUP_DEBUG_EVAL_TIMES"); e && e[0] == '1') h->probe = true;
            if (const char* e = std::getenv("LOUP_EVAL_ARM"); e && e[0] == '1') h->arm_enabled = true;
            else if (e && e[0] == '0') h->arm_state = -1;
        }
        CUDA_CHECK_THROW(cudaStreamCreate(&h->stream));
        CUBLAS_CHECK_THROW(cublasCreate(&h->cublas));
        CUBLAS_CHECK_THROW(cublasLtCreate(&h->cublas_lt));
        CUDA_CHECK_THROW(cudaMalloc(&h->d_cublas_ws, h->cublas_ws_bytes));
        cublas_bind(h, h->stream, h->d_cublas_ws);
        // Mapped pinned words for polling stream positions (publish_kernel, guard_step_kernel).
        CUDA_CHECK_THROW(cudaHostAlloc(&h->h_pub, 16 * sizeof(int), cudaHostAllocMapped));
        memset(h->h_pub, 0, 16 * sizeof(int));
        CUDA_CHECK_THROW(cudaHostGetDevicePointer(reinterpret_cast<void**>(&h->d_pub), h->h_pub, 0));
        CUDA_CHECK_THROW(cudaMalloc(&h->d_pub_counter, sizeof(unsigned int)));
        CUDA_CHECK_THROW(cudaMemset(h->d_pub_counter, 0, sizeof(unsigned int)));
        CUDA_CHECK_THROW(cudaEventCreateWithFlags(&h->ev_fork, cudaEventDisableTiming));
        for (int i = 0; i < LoupHandle::kSide; ++i) {
            CUDA_CHECK_THROW(cudaStreamCreateWithFlags(&h->side[i], cudaStreamNonBlocking));
            CUDA_CHECK_THROW(cudaEventCreateWithFlags(&h->ev_join[i], cudaEventDisableTiming));
            CUDA_CHECK_THROW(cudaMalloc(&h->side_ws[i], h->cublas_ws_bytes));
        }
        {
            const loup::Bundle bundle(loup_path);
            if (bundle.meta("arch") != "generic")  // e.g. omat0_medium_spec: the specialised path, retired (stage 5)
                throw std::runtime_error(std::string(loup_path) + ": bundle arch '" + bundle.meta("arch") +
                                         "' is no longer supported; re-export it (every model exports as arch=generic)");
            h->gen = std::make_unique<loup::GenericModel>();
            h->gen->load(bundle);
        }
        // Tensor-core GEMM implementations have failed full-model POLAR accuracy gates. Their rounding depends on
        // the operands and MMA accumulation, not a fixed multiple of FP32 error. Keep long-range models on FP32
        // until a candidate clears both accuracy and performance qualification (see gemm-tc-rounded-polar in the ledger).
        // LOUP_LR_HYBRID=1 (tests): load the GEMM cubin for long-range models too (e.g. a true 3xTF32 build through
        // LOUP_HYBRID_CUBIN, gated before any adoption).
        const char* lr_hyb = std::getenv("LOUP_LR_HYBRID");
        if (!h->gen->has_lr() || (lr_hyb && lr_hyb[0] == '1')) h->hyb.init(device_id);
        if (cc80 && !h->hyb.loaded && !own_ext_env) h->own_ext = true;  // float32 SIMT GEMMs only (see own_ext)
        h->load_disk_plans(device_id);
        if (const char* b = std::getenv("LOUP_TILE_GEMM_BUCKETS")) h->gemm_buckets = std::atoi(b) != 0;
        loup::sgemm128_init();
        return h;
    } catch (const std::exception& e) {
        loup::pending_error() = e.what();
    } catch (...) {
        loup::pending_error() = "unknown exception";
    }
    store_error(nullptr, "loup_create");
    if (h) loup_destroy(h);
    return nullptr;
}

void loup_destroy(LoupHandle* h) {
    if (!h) return;
    const DeviceOrder order(true);  // cuBLAS's handle destruction synchronises the device (see DeviceOrder)
    cudaSetDevice(h->device_id);
    release_tiled_md(h);
    if (h->probe && h->probe_n > 0)
        fprintf(stderr, "[loupmd] loup_evaluate, %ld step-graph calls without a rebuild, mean us: to launch / release %.1f, "
                        "to the guard %.1f, guard to results %.1f, results to return %.1f; between calls %.1f (%ld)\n",
                h->probe_n, h->probe_us[0] / h->probe_n, h->probe_us[1] / h->probe_n, h->probe_us[2] / h->probe_n,
                h->probe_us[3] / h->probe_n, h->probe_gap_n ? h->probe_us[4] / h->probe_gap_n : 0.0, h->probe_gap_n);
    h->drain_armed();
    h->free_system();
    if (h->h_go) cudaFreeHost(h->h_go);
    if (h->ev_fork) cudaEventDestroy(h->ev_fork);
    if (h->ev_io_in) cudaEventDestroy(h->ev_io_in);
    if (h->ev_io_out) cudaEventDestroy(h->ev_io_out);
    for (int i = 0; i < LoupHandle::kSide; ++i) {
        if (h->ev_join[i]) cudaEventDestroy(h->ev_join[i]);
        if (h->side_ws[i]) cudaFree(h->side_ws[i]);
        if (h->side[i]) cudaStreamDestroy(h->side[i]);
    }
    if (h->h_pub) cudaFreeHost(h->h_pub);
    if (h->d_pub_counter) cudaFree(h->d_pub_counter);
    if (h->d_celldev) cudaFree(h->d_celldev);
    h->disp.reset();
    if (h->d_disp_cell) cudaFree(h->d_disp_cell);
    h->hyb.destroy();
    if (h->d_cublas_ws) cudaFree(h->d_cublas_ws);
    for (auto& kv : h->bt_cache) cudaFree(kv.second);
    if (h->cublas_lt) cublasLtDestroy(h->cublas_lt);
    if (h->cublas) cublasDestroy(h->cublas);
    if (h->stream) cudaStreamDestroy(h->stream);
    delete h;
}

// Every cudaMalloc inside set_system_impl is counted into the handle's sys_atom_bytes (for loup_plan_memory): the
// macro spares its sixty allocation lines an edit each. It ends right after the function.
static cudaError_t counted_malloc(size_t& counter, void** p, size_t bytes) {
    const cudaError_t err = loup::device_malloc(p, bytes);
    if (err == cudaSuccess) counter += bytes;
    return err;
}
#define cudaMalloc(p, bytes) counted_malloc(h->sys_atom_bytes, (void**)(p), (bytes))
// n_ghost > 0 makes the last n_ghost atoms ghosts of an open domain (see LoupHandle::n_ghost): the locals are grouped
// by species as always, the ghosts keep their order behind them, and every per-atom buffer has a row for each.
// domain (set_domain_impl: open domains and tiles, which sweep): the generic model's skip-chain fold stays off for
// this system, as sweeps need every layer's output; whole systems fold where the fold was built. A domain's layers
// share one arena for their own buffers (GenericModel::share_layer_buffers).
static int set_system_impl(LoupHandle* h, int n_atoms, const int* atomic_numbers, const double* masses_amu, double skin,
                           int n_ghost = 0, bool domain = false) {
    if (!h) return -1;
    if (n_atoms <= 0) { loup::set_error("n_atoms must be positive, got %d", n_atoms); return -1; }
    if (!atomic_numbers) { loup::set_error("atomic_numbers is NULL"); return -1; }
    if (!(skin >= 0.0) || !std::isfinite(skin)) {
        loup::set_error("skin must be finite and not negative, got %g A", skin);
        return -1;
    }
    if (n_ghost < 0 || n_ghost >= n_atoms) {
        loup::set_error("n_ghost must be between 0 and the atom count less one, got %d of %d", n_ghost, n_atoms);
        return -1;
    }
    {
        const char* lim = std::getenv("LOUP_DEBUG_EDGE_LIMIT");
        h->edge_limit = (lim && *lim) ? std::max(1LL, std::atoll(lim)) : 536870911LL;
    }
    if ((n_ghost > 0 || domain) && !(h->gen && h->gen->sweeps_possible())) {
        loup::set_error("an open domain needs a bundle of the generic path without long range");
        return -1;
    }
    const int n_local = n_atoms - n_ghost;
    CUDA_CHECK(cudaSetDevice(h->device_id));
    if (settle_armed(h) != 0) return -1;
    const int S = h->n_species();

    // Validate everything before touching the handle: on any failure the previous system is gone only if the
    // failure came from allocation, and then N stays 0 so every later call is refused.
    std::vector<int> sp_orig(n_atoms);
    double e0_total = 0.0;
    for (int i = 0; i < n_atoms; ++i) {
        int z = atomic_numbers[i];
        int found = -1;
        for (int s = 0; s < S; ++s) {
            if (h->species_z(s) == z) { found = s; break; }
        }
        if (found < 0) {
            std::string elements;
            for (int s = 0; s < S; ++s) elements += (s ? ", " : "") + std::to_string(h->species_z(s));
            loup::set_error("atomic number %d (atom %d) is not in the bundle, which was exported for %s", z, i,
                            elements.c_str());
            return -1;
        }
        if (masses_amu && !(masses_amu[i] > 0.0 && std::isfinite(masses_amu[i]))) {
            loup::set_error("atom %d has mass %g amu; masses must be finite and positive", i, masses_amu[i]);
            return -1;
        }
        sp_orig[i] = found;
        if (i < n_local) e0_total += h->species_e0(found);
    }
    h->free_system();  // sets N = 0
    if (h->gen) {
        try {
            h->gen->use_chain_fold(!domain);
            h->gen->share_layer_buffers(domain);  // a domain only sweeps: one arena for its layers' own buffers
        } catch (const std::exception& e) {
            loup::set_error("%s", e.what());
            return -1;
        }
    }
    h->disp_ready = false;
    h->skin = skin;
    h->e0_total = e0_total;
    h->atom_e0.assign(n_atoms, 0.0);
    for (int i = 0; i < n_local; ++i) h->atom_e0[i] = h->species_e0(sp_orig[i]);
    h->species_hash = fnv1a64(atomic_numbers, (size_t)n_atoms * sizeof(int), fnv1a64(&n_atoms, sizeof(n_atoms)));

    // Build stable species-grouping permutation (the spatial order inside each group is set at every rebuild)
    ++h->perm_epoch;
    h->perm.resize(n_atoms);
    h->h_order.resize(n_atoms);
    h->masses_caller.assign(n_atoms, 1.0);
    h->fixed_caller.assign(n_atoms, 0);
    h->n_fixed = 0;
    h->fix_com = false;
    h->total_mass = 0.0;
    h->species_start.assign(S + 1, 0);
    h->species_count.assign(S, 0);
    for (int i = 0; i < n_local; ++i) h->species_count[sp_orig[i]]++;
    for (int s = 0; s < S; ++s) h->species_start[s + 1] = h->species_start[s] + h->species_count[s];
    std::vector<int> cursor = h->species_start;
    std::vector<int> sp_sorted(n_atoms);
    std::vector<double> m_sorted(n_atoms), inv_m_sorted(n_atoms), sim_sorted(n_atoms);
    for (int i = 0; i < n_atoms; ++i) {
        int dst = i < n_local ? cursor[sp_orig[i]]++ : i;
        h->perm[dst] = i;
        sp_sorted[dst] = sp_orig[i];
        double m = masses_amu ? masses_amu[i] : 1.0;
        h->masses_caller[i] = m;
        if (i < n_local) h->total_mass += m;
        m_sorted[dst] = m;
        inv_m_sorted[dst] = 1.0 / m;
        sim_sorted[dst] = 1.0 / sqrt(m);
    }

    // Allocate atom device buffers
    CUDA_CHECK(cudaMalloc(&h->d_species, n_atoms * sizeof(int)));
    CUDA_CHECK(cudaMemcpyAsync(h->d_species, sp_sorted.data(), n_atoms * sizeof(int), cudaMemcpyHostToDevice, h->stream));
    CUDA_CHECK(cudaMalloc(&h->d_pos64, (size_t)n_atoms * 3 * sizeof(double)));
    CUDA_CHECK(cudaMalloc(&h->d_ref_pos64, (size_t)n_atoms * 3 * sizeof(double)));
    CUDA_CHECK(cudaMalloc(&h->d_vel64, (size_t)n_atoms * 3 * sizeof(double)));
    CUDA_CHECK(cudaMalloc(&h->d_masses, n_atoms * sizeof(double)));
    CUDA_CHECK(cudaMalloc(&h->d_inv_masses, n_atoms * sizeof(double)));
    CUDA_CHECK(cudaMalloc(&h->d_sqrt_inv_masses, n_atoms * sizeof(double)));
    CUDA_CHECK(cudaMemcpyAsync(h->d_masses, m_sorted.data(), n_atoms * sizeof(double), cudaMemcpyHostToDevice, h->stream));
    CUDA_CHECK(cudaMemcpyAsync(h->d_inv_masses, inv_m_sorted.data(), n_atoms * sizeof(double), cudaMemcpyHostToDevice, h->stream));
    CUDA_CHECK(cudaMemcpyAsync(h->d_sqrt_inv_masses, sim_sorted.data(), n_atoms * sizeof(double), cudaMemcpyHostToDevice, h->stream));
    CUDA_CHECK(cudaMalloc(&h->d_rnd_vel, (size_t)n_atoms * 3 * sizeof(double)));
    // Only set_state writes velocities: an evaluate-then-run sequence starts from rest, not from stale memory.
    CUDA_CHECK(cudaMemsetAsync(h->d_vel64, 0, (size_t)n_atoms * 3 * sizeof(double), h->stream));
    CUDA_CHECK(cudaMemsetAsync(h->d_rnd_vel, 0, (size_t)n_atoms * 3 * sizeof(double), h->stream));
    CUDA_CHECK(cudaMalloc(&h->d_need_rebuild, sizeof(int)));
    CUDA_CHECK(cudaMalloc(&h->d_max_step_disp2, 2 * sizeof(unsigned int)));
    CUDA_CHECK(cudaMemsetAsync(h->d_max_step_disp2, 0, 2 * sizeof(unsigned int), h->stream));
    CUDA_CHECK(cudaMalloc(&h->d_step_counter, sizeof(unsigned long long)));
    CUDA_CHECK(cudaMemsetAsync(h->d_step_counter, 0, sizeof(unsigned long long), h->stream));
    CUDA_CHECK(cudaMalloc(&h->d_langevin_target, 5 * sizeof(double)));
    CUDA_CHECK(cudaMemsetAsync(h->d_langevin_target, 0, 5 * sizeof(double), h->stream));
    CUDA_CHECK(cudaMalloc(&h->d_int_state, kIntStateSlots * sizeof(double)));
    CUDA_CHECK(cudaMemsetAsync(h->d_int_state, 0, kIntStateSlots * sizeof(double), h->stream));
    CUDA_CHECK(cudaMalloc(&h->d_int_work, kIntWorkSlots * sizeof(double)));
    CUDA_CHECK(cudaMemsetAsync(h->d_int_work, 0, kIntWorkSlots * sizeof(double), h->stream));
    CUDA_CHECK(cudaMalloc(&h->d_ke_f64, sizeof(double)));

    // Neighbour scratch
    h->max_bins = 262144;
    CUDA_CHECK(cudaMalloc(&h->d_pos_wrapped, (size_t)n_atoms * 3 * sizeof(double)));
    CUDA_CHECK(cudaMalloc(&h->d_atom_wrap, (size_t)n_atoms * 3 * sizeof(int)));
    CUDA_CHECK(cudaMalloc(&h->d_atom_bin, n_atoms * sizeof(int)));
    CUDA_CHECK(cudaMalloc(&h->d_ro_keys, (size_t)n_atoms * 2 * sizeof(unsigned long long)));
    CUDA_CHECK(cudaMalloc(&h->d_ro_vals, (size_t)n_atoms * 2 * sizeof(int)));
    CUDA_CHECK(cudaMalloc(&h->d_ro_tmp, (size_t)n_atoms * 3 * sizeof(double)));
    // [0] the rows' order flag, [2] the variable-cell shift-code flag (nl_finish)
    CUDA_CHECK(cudaMalloc(&h->d_order_err, 4 * sizeof(int)));
    CUDA_CHECK(cudaMemset(h->d_order_err, 0, 4 * sizeof(int)));
    CUDA_CHECK(cudaMalloc(&h->d_max_deg, 2 * sizeof(int)));
    CUDA_CHECK(cudaMalloc(&h->d_bin_counts, (h->max_bins + 1) * sizeof(int)));
    CUDA_CHECK(cudaMalloc(&h->d_bin_offsets, (h->max_bins + 1) * sizeof(int)));
    CUDA_CHECK(cudaMalloc(&h->d_bin_cursor, (h->max_bins + 1) * sizeof(int)));
    // The three bin arrays above have a fixed size: loup_plan_memory must not scale them with the atom count.
    h->sys_fixed_bytes = 3 * (size_t)(h->max_bins + 1) * sizeof(int);
    h->sys_atom_bytes -= h->sys_fixed_bytes;
    CUDA_CHECK(cudaMalloc(&h->d_bin_atom_id, n_atoms * sizeof(int)));
    CUDA_CHECK(cudaMalloc(&h->d_bin_pos, (size_t)n_atoms * 3 * sizeof(double)));
    CUDA_CHECK(cudaMalloc(&h->d_bin_pos_f32, (size_t)n_atoms * sizeof(float4)));
    CUDA_CHECK(cudaMalloc(&h->d_bin_wrap, (size_t)n_atoms * 3 * sizeof(int)));
    CUDA_CHECK(cudaMalloc(&h->d_bin_sp, n_atoms * sizeof(int)));
    CUDA_CHECK(cudaMalloc(&h->d_deg, (n_atoms + 1) * sizeof(int)));
    CUDA_CHECK(cudaMalloc(&h->d_row_ptr, (n_atoms + 1) * sizeof(int)));
    CUDA_CHECK(cudaMalloc(&h->d_act_deg, (n_atoms + 1) * sizeof(int)));
    CUDA_CHECK(cudaMalloc(&h->d_act_row_ptr, (n_atoms + 1) * sizeof(int)));
    {
        size_t scanN_bytes = 0;
        cub::DeviceScan::ExclusiveSum(nullptr, scanN_bytes, h->d_act_deg, h->d_act_row_ptr, n_atoms + 1, h->stream);
        if (ensure_cub_tmp(h, scanN_bytes) != 0) return -1;
    }

    // energy, forces and virial (zeroed per force pass); the model keeps its own buffers
    auto align256 = [](size_t b) { return (b + 255) & ~size_t(255); };
    const size_t off_f64 = align256(sizeof(double));
    const size_t off_v64 = off_f64 + align256((size_t)n_atoms * 3 * sizeof(double));
    h->zero_slab_bytes = off_v64 + align256(6 * sizeof(double));
    CUDA_CHECK(cudaMalloc(&h->d_zero_slab, h->zero_slab_bytes));
    auto* base = static_cast<char*>(h->d_zero_slab);
    h->d_energy_f64 = reinterpret_cast<double*>(base);
    h->d_forces_f64 = reinterpret_cast<double*>(base + off_f64);
    h->d_virial_grad_f64 = reinterpret_cast<double*>(base + off_v64);
    plan_dbg("before the model's rows");
    h->gen->alloc_system(n_atoms);
    plan_dbg("after the model's rows");
    if (h->E_cap > 0) h->gen->ensure_edges(h->E_cap);
    h->stage_off_f = off_f64 / sizeof(double);
    h->stage_off_v = off_v64 / sizeof(double);
    // loup_evaluate's staging: a whole system only (a domain's rows come and go through its driver's own buffers)
    if (n_ghost == 0)
        CUDA_CHECK(cudaHostAlloc(&h->h_stage, (size_t)3 * n_atoms * sizeof(double) + h->zero_slab_bytes, cudaHostAllocDefault));
    h->N = n_local;
    h->n_ghost = n_ghost;
    h->atom_cap = n_atoms;
    return 0;
}
#undef cudaMalloc

// Upload positions (caller order) and the cell. Returns 1 if the cell changed (the neighbour list's Cartesian
// shifts depend on it, so the list must be rebuilt), 0 if not, -1 on error.
// The engine is always fully periodic: the cell must be finite and non-degenerate (ASE's zero cell for a molecule
// is rejected; put molecules in a box larger than 2 (r_max + skin)), and positions finite.
static bool valid_cell(const double* cell) {
    if (!cell) {
        loup::set_error("cell is NULL");
        return false;
    }
    for (int i = 0; i < 9; ++i) {
        if (!std::isfinite(cell[i])) {
            loup::set_error("non-finite cell entry [%d, %d]", i / 3, i % 3);
            return false;
        }
    }
    const double det = cell[0] * (cell[4] * cell[8] - cell[5] * cell[7]) - cell[1] * (cell[3] * cell[8] - cell[5] * cell[6]) +
                       cell[2] * (cell[3] * cell[7] - cell[4] * cell[6]);
    double scale = 0.0;
    for (int i = 0; i < 9; ++i) scale = std::max(scale, std::fabs(cell[i]));
    if (!(std::fabs(det) > 1e-9 * scale * scale * scale) || scale == 0.0) {
        loup::set_error("singular or zero cell (det = %g A^3); the engine is fully periodic", det);
        return false;
    }
    return true;
}

static bool valid_input(int n, const double* positions, const double* cell, const double* velocities) {
    if (!positions) {
        loup::set_error("positions is NULL");
        return false;
    }
    if (!valid_cell(cell)) return false;
    for (size_t i = 0; i < (size_t)n * 3; ++i) {
        if (!std::isfinite(positions[i])) {
            loup::set_error("non-finite position (atom %zu)", i / 3);
            return false;
        }
        if (velocities && !std::isfinite(velocities[i])) {
            loup::set_error("non-finite velocity (atom %zu)", i / 3);
            return false;
        }
    }
    return true;
}

// Takes the cell and writes the positions, in the engine's order, to `dst` ([3 (N + n_ghost)] doubles). Returns 1 if
// the cell changed, 0 if not, -1 on error.
static int stage_positions(LoupHandle* h, const double* positions, const double* cell, double* dst_rows) {
    const int NT = h->N + h->n_ghost;
    if (!valid_input(NT, positions, cell, nullptr)) return -1;
    h->forces_current = false;
    ++h->pos_epoch;
    memcpy(h->cell_in, cell, sizeof(h->cell_in));
    loup::CellMat64 old_cell = h->cell;
    loup::compute_cell_mat(cell, h->cell, h->cell_vol, h->cell_heights);
    const int cell_changed = memcmp(&old_cell, &h->cell, sizeof(old_cell)) != 0 ? 1 : 0;
    if (h->gen && h->gen->set_cell(cell)) h->invalidate_graphs();
    if (dispersion_cell_changed(h) != 0) return -1;

    for (int dst = 0; dst < NT; ++dst) {
        int src = h->perm[dst];
        dst_rows[dst * 3 + 0] = positions[src * 3 + 0];
        dst_rows[dst * 3 + 1] = positions[src * 3 + 1];
        dst_rows[dst * 3 + 2] = positions[src * 3 + 2];
    }
    return cell_changed;
}

// A whole system's rows go through the page-locked staging, which is free here: every call that fills it has read its
// results back before returning. An open domain (no staging) keeps the pageable copy.
static int upload_positions(LoupHandle* h, const double* positions, const double* cell) {
    const size_t n3 = (size_t)(h->N + h->n_ghost) * 3;
    std::vector<double> pageable;
    if (!h->h_stage) pageable.resize(n3);
    double* rows = h->h_stage ? h->stage_pos() : pageable.data();
    const int cell_changed = stage_positions(h, positions, cell, rows);
    if (cell_changed < 0) return -1;
    CUDA_CHECK(cudaMemcpyAsync(h->d_pos64, rows, n3 * sizeof(double), cudaMemcpyHostToDevice, h->stream));
    return cell_changed;
}

// The refusal shared by every call that needs a system.
static bool has_system(const LoupHandle* h) {
    if (h && h->N > 0 && h->n_ghost == 0) return true;
    if (h && h->n_ghost > 0)
        loup::set_error("the handle holds an open domain (loup_debug_set_domain): only loup_debug_evaluate_domain "
                        "runs on it");
    else
        loup::set_error("no system is set (call loup_set_system first)");
    return false;
}

// Queues (or, during capture, records) the copy of the energy, the forces and the virial into the page-locked
// staging, and behind it a publication of the neighbour rows' order flag: once the host has read that publication
// the results have landed, with no blocking transfer and no stream synchronisation. The three lie in one slab on the
// device (zeroed by every force pass), so it is one copy: under WSL 2 each host copy in the step costs about 10 us at
// 648 atoms and 50 us at 5,000 (S145, three copies before).
static int queue_results(LoupHandle* h) {
    CUDA_CHECK(cudaMemcpyAsync(h->stage_out(), h->d_zero_slab, h->zero_slab_bytes, cudaMemcpyDeviceToHost, h->stream));
    loup::publish_kernel<<<1, 1, 0, h->stream>>>(h->d_order_err, nullptr, nullptr, h->d_pub_counter, h->d_pub);
    return 0;
}

static int set_state_impl(LoupHandle* h, const double* positions, const double* velocities, const double* cell) {
    if (!has_system(h)) return -1;
    CUDA_CHECK(cudaSetDevice(h->device_id));
    if (!valid_input(h->N, positions, cell, velocities)) return -1;
    if (settle_armed(h) != 0) return -1;
    if (upload_positions(h, positions, cell) < 0) return -1;
    h->cell_v0 = h->cell_vol;  // a new trajectory: the cell limits of a variable-cell run refer to this volume
    CUDA_CHECK(cudaMemsetAsync(h->d_max_step_disp2, 0, 2 * sizeof(unsigned int), h->stream));
    CUDA_CHECK(cudaMemsetAsync(h->d_int_state, 0, kIntStateSlots * sizeof(double), h->stream));  // a new trajectory
    h->int_state_kind = -1;
    h->disp_window_steps = 0;
    h->md_steps = 0;
    h->thermo_pending = 0;
    if (velocities) {
        std::vector<double> v_sorted((size_t)h->N * 3);
        for (int dst = 0; dst < h->N; ++dst) {
            int src = h->perm[dst];
            v_sorted[dst * 3 + 0] = velocities[src * 3 + 0];
            v_sorted[dst * 3 + 1] = velocities[src * 3 + 1];
            v_sorted[dst * 3 + 2] = velocities[src * 3 + 2];
            if (h->fixed_caller[src]) v_sorted[dst * 3 + 0] = v_sorted[dst * 3 + 1] = v_sorted[dst * 3 + 2] = 0.0;
        }
        CUDA_CHECK(cudaMemcpyAsync(h->d_vel64, v_sorted.data(), (size_t)h->N * 3 * sizeof(double), cudaMemcpyHostToDevice, h->stream));
    } else {
        CUDA_CHECK(cudaMemsetAsync(h->d_vel64, 0, (size_t)h->N * 3 * sizeof(double), h->stream));
    }
    return rebuild_neighbors(h);
}

// loup_set_fixed_atoms: a fixed atom gets zero inverse mass (and zero 1/sqrt(m), the thermostat's noise factor) and
// zero velocity, so every integrator leaves it where it is without knowing about it. Masses stay, so the kinetic
// energy of the others is unchanged.
static int set_fixed_impl(LoupHandle* h, const int* fixed) {
    if (!has_system(h)) return -1;
    CUDA_CHECK(cudaSetDevice(h->device_id));
    const int N = h->N;
    int n_fixed = 0;
    if (fixed) {
        for (int i = 0; i < N; ++i) n_fixed += fixed[i] != 0;
    }
    if (n_fixed == N) {
        loup::set_error("every atom is fixed (%d atoms): nothing would move", N);
        return -1;
    }
    std::vector<double> inv_m((size_t)N), sim((size_t)N), vel((size_t)N * 3);
    CUDA_CHECK(cudaStreamSynchronize(h->stream));
    CUDA_CHECK(cudaMemcpy(vel.data(), h->d_vel64, vel.size() * sizeof(double), cudaMemcpyDeviceToHost));
    for (int dst = 0; dst < N; ++dst) {
        const int src = h->perm[dst];
        const bool held = fixed && fixed[src] != 0;
        const double m = h->masses_caller[src];
        inv_m[dst] = held ? 0.0 : 1.0 / m;
        sim[dst] = held ? 0.0 : 1.0 / sqrt(m);
        if (held) vel[(size_t)dst * 3 + 0] = vel[(size_t)dst * 3 + 1] = vel[(size_t)dst * 3 + 2] = 0.0;
    }
    CUDA_CHECK(cudaMemcpy(h->d_inv_masses, inv_m.data(), inv_m.size() * sizeof(double), cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(h->d_sqrt_inv_masses, sim.data(), sim.size() * sizeof(double), cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(h->d_vel64, vel.data(), vel.size() * sizeof(double), cudaMemcpyHostToDevice));
    for (int i = 0; i < N; ++i) h->fixed_caller[i] = fixed && fixed[i] != 0;
    h->n_fixed = n_fixed;
    ++h->pos_epoch;  // loup_minimize's gradient leaves fixed atoms out
    h->invalidate_md_graphs();  // the thermo row's degrees of freedom are baked into the captured step
    return 0;
}

// The TF32 + FP16 hybrid GEMMs (gemm-hybrid-cubin) overflow to inf when a GEMM operand element reaches 32,752. A
// non-finite energy, force or stress with the hybrid loaded drops it for this engine: later GEMM plans are re-tuned
// without it (disk plans that chose it are skipped while it is unloaded) and the captured graphs are re-recorded.
// The notice goes to stderr: the call that triggered it goes on and can succeed, so it is not an error of the error
// channel.
static bool drop_hybrid(LoupHandle* h) {
    if (!h->hyb.loaded) return false;
    fprintf(stderr, "loupmd: non-finite energy / forces with the tensor-core GEMM cubin %s: disabled for this engine "
                    "(GEMMs re-tuned without it; the TF32+FP16 hybrid builds overflow at |operand| >= 32,752)\n",
            h->hyb.path_loaded.c_str());
    h->hyb.loaded = false;
    h->clear_lt_cache();
    // The plans in memory and the file were timed with the hybrid: drop them and save nothing from this engine, so a
    // later process (hybrid loaded) still times the hybrid for these shapes.
    h->disk_plans.clear();
    h->bucket_plans.clear();
    h->disk_dirty = false;
    h->plan_cache_path.clear();
    h->invalidate_graphs();
    return true;
}

// What an evaluation that reads its results itself starts with (the energy-only pass): the new positions and cell
// on the device and a neighbour list that is complete for them.
static int prepare_evaluate(LoupHandle* h, const double* positions, const double* cell) {
    if (!has_system(h)) return -1;
    CUDA_CHECK(cudaSetDevice(h->device_id));
    // Positions only: MD velocities are kept. The neighbour list is rebuilt only when the cell changed or an atom
    // moved more than skin/2 since the last build; the force graph is reused unless the rebuild outgrew it.
    plan_dbg("before the upload");
    const int cell_changed = upload_positions(h, positions, cell);
    if (cell_changed < 0) return -1;
    plan_dbg("after the upload");
    bool rebuild = cell_changed != 0 || !h->nl_valid || h->cell_ref_stale;
    if (!rebuild) {
        const double half_skin = 0.5 * h->skin;
        CUDA_CHECK(cudaMemsetAsync(h->d_need_rebuild, 0, sizeof(int), h->stream));
        loup::check_skin_kernel<<<(h->N + 255) / 256, 256, 0, h->stream>>>(h->N, half_skin, h->d_pos64,
                                                                          h->d_ref_pos64, h->d_need_rebuild);
        int v[3];
        if (read_device_ints(h, h->d_need_rebuild, nullptr, nullptr, v) != 0) return -1;
        rebuild = v[0] != 0;
    }
    if (rebuild && rebuild_neighbors(h) != 0) return -1;
    plan_dbg("after the rebuild");
    return 0;
}

static int evaluate_once(
    LoupHandle* h, const double* positions, const double* cell, int compute_stress,
    double* out_energy_ev, double* out_forces, double* out_stress, bool* finite, bool* graph_step
) {
    if (!has_system(h)) return -1;
    CUDA_CHECK(cudaSetDevice(h->device_id));
    const int stress = compute_stress && out_stress ? 1 : 0;
    *graph_step = false;
    if (h->armed) {
        // The step queued by the previous call fits this one only with the same virial flag and cell. Otherwise it
        // runs first, on the positions that call staged.
        if (!valid_cell(cell)) return -1;
        loup::CellMat64 c{};
        double vol = 0.0, heights[3];
        loup::compute_cell_mat(cell, c, vol, heights);
        if ((h->armed_stress != stress || memcmp(&c, &h->cell, sizeof(c)) != 0) && settle_armed(h) != 0) return -1;
    }
    // Positions only: MD velocities are kept. The neighbour list is rebuilt only when the cell changed or an atom
    // moved more than skin/2 since the last build; the force graph is reused unless the rebuild outgrew it.
    plan_dbg("before the upload");
    const int cell_changed = stage_positions(h, positions, cell, h->stage_pos());
    if (cell_changed < 0) return -1;
    plan_dbg("after the upload");
    const double* f_sorted = h->stage_f();
    h->stage_out()[0] = 0.0;
    for (int i = 0; i < 6; ++i) h->stage_v()[i] = 0.0;
    // The MD graphs hold one kind of step at a time. While they hold an integrator's, as between the blocks of a
    // run whose driver evaluates at every output (LAMMPS's run style, the package's own run loop), an evaluation
    // takes the force graph, which stands beside them: capturing the host step over them, and the integrator's
    // step again at the next block, cost four captures per output (measured through LAMMPS on 320 atoms: 0.92
    // against 0.60 ms per step with output every 10 steps). From the third evaluation in a row the host step
    // takes over.
    const bool keep_md = h->md_step_exec && h->md_graph_kind != kStepHost && h->eval_since_run < 2;
    ++h->eval_since_run;
    bool rebuild = cell_changed != 0 || !h->nl_valid || h->cell_ref_stale || h->lt_cache.empty();
    if (rebuild || keep_md) {
        // A new cell (the list's Cartesian shifts depend on it), no list yet, a list whose reference a
        // variable-cell run left behind, or GEMM plans to tune first (no force pass on this system yet, as after
        // loup_set_state; a capture would freeze untuned plans): the host-driven rebuild, then the pass. With
        // keep_md the list is checked first and rebuilt only when an atom has moved more than skin / 2.
        CUDA_CHECK(cudaMemcpyAsync(h->d_pos64, h->stage_pos(), (size_t)h->N * 3 * sizeof(double), cudaMemcpyHostToDevice, h->stream));
        if (!rebuild) {
            CUDA_CHECK(cudaMemsetAsync(h->d_need_rebuild, 0, sizeof(int), h->stream));
            loup::check_skin_kernel<<<(h->N + 255) / 256, 256, 0, h->stream>>>(h->N, 0.5 * h->skin, h->d_pos64,
                                                                              h->d_ref_pos64, h->d_need_rebuild);
            int v[3];
            if (read_device_ints(h, h->d_need_rebuild, nullptr, nullptr, v) != 0) return -1;
            rebuild = v[0] != 0;
        }
        if (rebuild && rebuild_neighbors(h) != 0) return -1;
        plan_dbg("after the rebuild");
        if (ensure_force_graph(h, stress) != 0) return -1;
        CUDA_CHECK(cudaGraphLaunch(h->force_graph_exec, h->stream));
        int fin[3];
        if (queue_results(h) != 0 || wait_published(h, ++h->pub_count, fin) != 0) return -1;
        tune_early_variants(h);  // a caller whose every call takes this path (a new cell each call) is timed too
    } else {
        // One launch of the host step graph (or the release of the one queued ahead): upload, skin check, guard,
        // force pass or on-device rebuild, downloads.
        if (run_host_step(h, stress) != 0) return -1;
        *graph_step = true;
    }
    const double inter_e = h->stage_out()[0];
    const double* v_grad = h->stage_v();

    *finite = std::isfinite(inter_e);
    for (size_t i = 0; *finite && i < (size_t)h->N * 3; ++i) *finite = std::isfinite(f_sorted[i]);
    for (int i = 0; *finite && i < 6; ++i) *finite = std::isfinite(v_grad[i]);
    h->forces_current = *finite;  // a run may start from these forces only if they are usable
    if (out_energy_ev) *out_energy_ev = h->e0_total + inter_e;
    if (out_forces) {
        for (int dst = 0; dst < h->N; ++dst) {
            int orig = h->perm[dst];
            out_forces[orig * 3 + 0] = f_sorted[dst * 3 + 0];
            out_forces[orig * 3 + 1] = f_sorted[dst * 3 + 1];
            out_forces[orig * 3 + 2] = f_sorted[dst * 3 + 2];
        }
    }
    if (stress) {
        double inv_v = 1.0 / h->cell_vol;
        out_stress[0] = v_grad[0] * inv_v; out_stress[1] = v_grad[1] * inv_v; out_stress[2] = v_grad[2] * inv_v;
        out_stress[3] = v_grad[1] * inv_v; out_stress[4] = v_grad[3] * inv_v; out_stress[5] = v_grad[4] * inv_v;
        out_stress[6] = v_grad[2] * inv_v; out_stress[7] = v_grad[4] * inv_v; out_stress[8] = v_grad[5] * inv_v;
    }
    return 0;
}

static int evaluate_impl(
    LoupHandle* h, const double* positions, const double* cell, int compute_stress,
    double* out_energy_ev, double* out_forces, double* out_stress
) {
    bool finite = true, graph_step = false;
    const auto probe_in = std::chrono::steady_clock::now();
    if (h && h->probe) h->probe_t[1] = h->probe_t[2] = h->probe_t[3] = probe_in;  // [1] set: a quiet step ran
    if (h && h->probe) h->probe_t[0] = std::chrono::steady_clock::time_point{};
    int rc = evaluate_once(h, positions, cell, compute_stress, out_energy_ev, out_forces, out_stress, &finite,
                           &graph_step);
    if (rc == 0 && !finite && drop_hybrid(h)) {
        rc = evaluate_once(h, positions, cell, compute_stress, out_energy_ev, out_forces, out_stress, &finite,
                           &graph_step);
    }
    if (rc == 0 && !finite) {
        loup::set_error("non-finite energy, forces or stress (model output; the configuration may be unphysical)");
        rc = -1;
    }
    // Queue the next call's step ahead once two calls in a row took the step graph with one virial flag. A lone
    // evaluate between run calls, or calls that alternate the flag, would only pay for a queued pass they discard.
    const int stress = compute_stress && out_stress ? 1 : 0;
    if (rc != 0 || !graph_step) {
        h->eval_streak = 0;
    } else {
        h->eval_streak = h->eval_streak_stress == stress ? h->eval_streak + 1 : 1;
        h->eval_streak_stress = stress;
        if (h->eval_streak >= 2) arm_evaluate(h, stress);
    }
    if (h && h->probe) {
        const auto now = std::chrono::steady_clock::now();
        auto us = [](std::chrono::steady_clock::time_point a, std::chrono::steady_clock::time_point b) {
            return std::chrono::duration<double, std::micro>(b - a).count();
        };
        if (rc == 0 && graph_step && h->probe_t[0] != std::chrono::steady_clock::time_point{}) {
            h->probe_us[0] += us(probe_in, h->probe_t[0]);
            h->probe_us[1] += us(h->probe_t[0], h->probe_t[1]);
            h->probe_us[2] += us(h->probe_t[1], h->probe_t[2]);
            h->probe_us[3] += us(h->probe_t[2], now);
            ++h->probe_n;
            if (h->probe_ret_set) {
                h->probe_us[4] += us(h->probe_ret, probe_in);
                ++h->probe_gap_n;
            }
        }
        h->probe_ret = now;
        h->probe_ret_set = rc == 0 && graph_step;
    }
    return rc;
}

// Per-atom energies (S6-T08, PLAN.md D70) of the positions the last evaluation uploaded: one uncaptured energy-only
// pass whose readouts and ZBL term also add each row's share into an [N] buffer (MACE's node energies: the readout
// of every layer, and half of each ZBL pair energy on its receiver), plus each atom's E0. They sum to the total
// energy up to float64 rounding. The pass reuses the GEMM plans of the energy graph and leaves the device forces
// stale.
static int per_atom_energies(LoupHandle* h, double* out) {
    if (ensure_energy_graph(h) != 0) return -1;
    const int rows = h->N + h->n_ghost;
    double* d_ae = nullptr;
    CUDA_CHECK(cudaMalloc(&d_ae, (size_t)rows * sizeof(double)));
    struct Pass {  // the buffer goes, and the next recorded pass is a plain one, whatever happens
        LoupHandle* h;
        double* d;
        bool saved_fork;
        Pass(LoupHandle* h_, double* d_) : h(h_), d(d_), saved_fork(h_->fork_ok) {
            h->pass_atom_energy = d;
            h->fork_ok = false;
        }
        ~Pass() {
            h->pass_atom_energy = nullptr;
            h->fork_ok = saved_fork;
            cudaFree(d);
        }
    } pass(h, d_ae);
    CUDA_CHECK(cudaMemsetAsync(d_ae, 0, (size_t)rows * sizeof(double), h->stream));
    record_force_pass(h, 0, true);
    CUDA_CHECK(cudaGetLastError());
    std::vector<double> ae(rows);
    CUDA_CHECK(cudaMemcpyAsync(ae.data(), d_ae, (size_t)rows * sizeof(double), cudaMemcpyDeviceToHost, h->stream));
    CUDA_CHECK(cudaStreamSynchronize(h->stream));
    h->forces_current = false;
    for (int r = 0; r < rows; ++r) {
        const int orig = h->perm[r];
        out[orig] = r < h->N ? ae[r] + h->atom_e0[orig] : 0.0;
        if (!std::isfinite(out[orig])) {
            loup::set_error("non-finite per-atom energy (atom %d)", orig);
            return -1;
        }
    }
    return 0;
}

static int evaluate2_impl(
    LoupHandle* h, const double* positions, const double* cell, int flags, double* out_energy_ev,
    double* out_forces, double* out_stress, double* out_atom_energies
) {
    const int known = LOUP_EVAL_STRESS | LOUP_EVAL_ENERGY_ONLY | LOUP_EVAL_PER_ATOM;
    if (flags & ~known) { loup::set_error("unknown evaluation flags 0x%x", flags & ~known); return -1; }
    if (flags & LOUP_EVAL_PER_ATOM) {
        if (!out_atom_energies) { loup::set_error("LOUP_EVAL_PER_ATOM needs out_atom_energies"); return -1; }
        if (h->gen->has_lr()) {
            loup::set_error("per-atom energies are not built for long-range models (the k-space energy is not "
                            "split by atom)");
            return -1;
        }
        if (evaluate2_impl(h, positions, cell, flags & ~LOUP_EVAL_PER_ATOM, out_energy_ev, out_forces, out_stress,
                           nullptr) != 0)
            return -1;
        if (per_atom_energies(h, out_atom_energies) != 0) return -1;
        // The energy of a per-atom call is the sum of its per-atom energies (the energy-only pass), so the two
        // agree to the rounding of the sum; it differs from the plain call's energy in the float32 rounding of the
        // readouts (measured up to 6e-7 relative on a compressed cell).
        if (out_energy_ev) {
            double sum = 0.0;
            for (int r = 0; r < h->N; ++r) sum += out_atom_energies[h->perm[r]];
            *out_energy_ev = sum;
        }
        return 0;
    }
    (void)out_atom_energies;
    if (!(flags & LOUP_EVAL_ENERGY_ONLY)) {
        return evaluate_impl(h, positions, cell, (flags & LOUP_EVAL_STRESS) ? 1 : 0, out_energy_ev, out_forces,
                             (flags & LOUP_EVAL_STRESS) ? out_stress : nullptr);
    }
    if (flags & LOUP_EVAL_STRESS) {
        loup::set_error("LOUP_EVAL_ENERGY_ONLY excludes LOUP_EVAL_STRESS: the energy-only pass has no gradients");
        return -1;
    }
    // prepare_evaluate has marked the forces on the device as stale; they stay so (a run that follows starts with
    // a force pass). A non-finite energy with the hybrid GEMMs loaded drops them and evaluates once more, as the
    // full call does.
    double inter_e = 0.0;
    for (int attempt = 0; attempt < 2; ++attempt) {
        if (prepare_evaluate(h, positions, cell) != 0) return -1;
        if (ensure_energy_graph(h) != 0) return -1;
        CUDA_CHECK(cudaGraphLaunch(h->energy_graph_exec, h->stream));
        CUDA_CHECK(cudaMemcpyAsync(&inter_e, h->d_energy_f64, sizeof(double), cudaMemcpyDeviceToHost, h->stream));
        CUDA_CHECK(cudaStreamSynchronize(h->stream));
        if (std::isfinite(inter_e) || !drop_hybrid(h)) break;
    }
    if (!std::isfinite(inter_e)) {
        loup::set_error("non-finite energy (model output; the configuration may be unphysical)");
        return -1;
    }
    if (out_energy_ev) *out_energy_ev = h->e0_total + inter_e;
    return 0;
}

// A barostat's settings (Berendsen NPT, kind 5): pressure in eV/A^3, compressibility in A^3/eV.
struct NptParams {
    double pressure = 0.0, tau_p_fs = 0.0, compressibility = 0.0;
    int full = 0;
    int mask[3] = {1, 1, 1};
    int pchain = 0, ploop = 0;  // MTK: the barostat's chain
};

static int run_md_loop(
    LoupHandle* h, int kind, int n_steps, double dt_fs,
    double temp_k, double temp_rate, double friction_per_fs, unsigned long long seed, int thermo_every,
    bool fix_com, LoupMDStats* out_stats, double tau_fs = 0.0, int tchain = 0, int tloop = 1,
    double mass_temp_k = 0.0, const NptParams* npt = nullptr
) {
    // nl_valid: positions and a neighbour list exist (set_state or evaluate ran and its rebuild completed).
    if (!has_system(h)) return -1;
    if (!h->nl_valid) {
        loup::set_error("no positions or neighbour list (call loup_set_state or loup_evaluate first)");
        return -1;
    }
    if (n_steps <= 0) { loup::set_error("n_steps must be positive, got %d", n_steps); return -1; }
    if (!std::isfinite(dt_fs) || !(dt_fs > 0.0)) {
        loup::set_error("dt_fs must be finite and positive, got %g fs", dt_fs);
        return -1;
    }
    if (thermo_every < 0) { loup::set_error("thermo_every must not be negative, got %d", thermo_every); return -1; }
    CUDA_CHECK(cudaSetDevice(h->device_id));
    // kStepDevice, the step of loup_compute_device: the caller integrates and has written the positions, so one step
    // is the skin check and the force pass (with the virial when `seed` is 1), with the same guard, on-device rebuild
    // and host fallback as an MD step. It queues the step and returns: nothing below waits for the forces.
    // kStepHost, the step of loup_evaluate: the same, with the positions' upload from the page-locked staging at the
    // head of the step graph and the results' copy and its publication (queue_results) at its end, so a call is one
    // graph launch. The host reads the guard's publication and then that last one.
    // Both are fixed-cell steps without thermo rows, and neither counts as an MD step (md_steps, the step
    // displacement's windows). Their callers rebuild the list first where a variable-cell run left its reference
    // stale, and make the uncaptured tuning pass first where the GEMM plans are gone (lt_cache).
    const bool ext = kind == kStepDevice || kind == kStepHost;
    const bool host_io = kind == kStepHost;
    const int ext_stress = ext && seed ? 1 : 0;
    // A step that loup_evaluate queued ahead is this call's step when it is a host step with the same virial flag
    // (released below instead of launched). Before any other step it runs first.
    if (!host_io) h->eval_streak = 0;
    if (!ext) h->eval_since_run = 0;
    if (h->armed && !(host_io && h->armed_stress == ext_stress) && settle_armed(h) != 0) return -1;
    const int N = h->N;
    const int gridN = (N + 255) / 256;
    const double dt_ase = dt_fs * loup::ASE_FS;
    const double half_skin = 0.5 * h->skin;
    // The variable-cell step (cell.hpp): the cell on the device, the Cartesian shifts formed from the integer ones
    // in every step, stress in every force pass, the list check against the deformed reference. Its rebuilds run on
    // the host (the cell must come back first). The first such run of a handle rebuilds the list once, which brings the cell and
    // the sorted integer shifts onto the device; a fixed-cell run after a cell change rebuilds for its plain check.
    const bool var_cell = !ext && h->req_var_cell;
    const double cell_rate = var_cell ? h->req_cell_rate : 0.0;
    if (var_cell && !h->var_cell) {
        if (!h->d_celldev) CUDA_CHECK(cudaMalloc(&h->d_celldev, sizeof(loup::CellDev)));
        h->var_cell = true;
        if (rebuild_neighbors(h) != 0) return -1;
    } else if (!ext && !var_cell && h->cell_ref_stale) {
        if (rebuild_neighbors(h) != 0) return -1;
    }
    if (ext && (h->cell_ref_stale || h->lt_cache.empty())) {
        loup::set_error("internal: a caller-integrated step needs a current list reference and tuned GEMM plans");
        return -1;
    }
    // Thermo rows of this call: counted on the host, so a run that would overflow the buffer is refused here.
    int thermo_rows = 0;
    if (thermo_every > 0) {
        thermo_rows = (int)((h->md_steps + n_steps) / thermo_every - h->md_steps / thermo_every);
        if (h->thermo_pending + thermo_rows > loup::kThermoCapacity) {
            loup::set_error("this call would write %d thermo rows and the buffer has room for %d of %d: read the "
                            "rows first (loup_read_thermo) or run fewer steps per call", thermo_rows,
                            loup::kThermoCapacity - h->thermo_pending, loup::kThermoCapacity);
            return -1;
        }
        if (!h->d_thermo_ctrl) CUDA_CHECK(cudaMalloc(&h->d_thermo_ctrl, sizeof(loup::ThermoCtrl)));
        if (!h->d_thermo_rows) {
            CUDA_CHECK(cudaMalloc(&h->d_thermo_rows, (size_t)loup::kThermoCapacity * sizeof(LoupThermoRow)));
        }
        loup::ThermoCtrl ctrl{};
        ctrl.step = (unsigned long long)h->md_steps;
        ctrl.every = thermo_every;
        ctrl.count = h->thermo_pending;
        ctrl.capacity = loup::kThermoCapacity;
        CUDA_CHECK(cudaMemcpy(h->d_thermo_ctrl, &ctrl, sizeof(ctrl), cudaMemcpyHostToDevice));
    }
    // The step-displacement maximum (loup_get_step_displacement, the saved state, the automatic skin) decays in two
    // windows (integrator.cu); the loop itself does not read it. A window ends at a neighbour rebuild once it holds
    // kDispWindowMin steps, so the previous window always stands for that many steps of every atom, and after
    // kDispWindowMax steps without a rebuild, so a system too cold to rebuild forgets a fast start as well. The host
    // ends windows between step launches (a rebuild inside the step graph counts at the step whose flag shows it).
    constexpr int kDispWindowMin = 32, kDispWindowMax = 512;
    auto rotate_disp = [&] {
        loup::rotate_step_disp_kernel<<<1, 1, 0, h->stream>>>(h->d_max_step_disp2);
        h->disp_window_steps = 0;
    };
    auto note_step = [&] {
        if (++h->disp_window_steps >= kDispWindowMax) rotate_disp();
    };
    // One loop. Each step is one launch of the step graph: first half + skin check + guard_step_kernel + an IF node
    // whose body is the rest (force pass + second half). The guard publishes the check's flag to mapped host memory
    // and lets the force pass run only while the list is complete, i.e. no atom has moved more than skin/2 since the
    // last rebuild (exact for any skin, including 0). The host polls the flag, which lands before the force pass
    // starts, and queues the next step while the force pass runs, so the GPU waits for the host only at a rebuild:
    // the guard has skipped the force pass, the host rebuilds the list at the new positions and launches the checked
    // rest graph (rest_guard_kernel + IF (valid rows) rest).

    // Forces at step 0. They are already on the device when the last call on this handle was a force evaluation or
    // a completed run at these positions, so a run made of many short calls pays one force pass per step and none
    // per call. (lt_cache: the uncaptured pass of ensure_force_graph, which the MD graphs' capture relies on.)
    // A caller-integrated step has no step 0: its force pass is the step.
    const bool debug_graphs = std::getenv("LOUP_DEBUG_GRAPHS") != nullptr;
    if (!ext) {
        if (!h->forces_current || h->lt_cache.empty() || (var_cell && !h->last_pass_stress)) {
            if (ensure_force_graph(h, var_cell ? 1 : 0) != 0) return -1;
            if (debug_graphs) fputs("loupmd: initial force pass\n", stderr);
            CUDA_CHECK(cudaGraphLaunch(h->force_graph_exec, h->stream));
        }
        // The Langevin step counter persists across run calls (reset only in loup_set_system), so chunked runs with
        // one seed continue the noise sequence instead of replaying it.
        CUDA_CHECK(cudaStreamSynchronize(h->stream));
    }
    if (!host_io) {  // the host step's caller has noted its new positions (stage_positions); a settled step moves nothing
        h->forces_current = false;  // until this call completes: a failure below leaves positions ahead of the forces
        ++h->pos_epoch;
    }

    // SPDX-SnippetBegin
    // SPDX-License-Identifier: LGPL-2.1-or-later
    // Provenance: the integrators' coefficients and masses, up to the end marker, follow ASE 3.27's ase/md classes
    // (LGPL-2.1-or-later, (c) the ASE developers, https://gitlab.com/ase/ase); see NOTICE.md.
    // ASE's Langevin coefficients. c3, c4, c5 carry sigma = sqrt(2 gamma kB T), which the first half-kick forms from
    // the target on the device; here are their factors of sigma.
    double c1 = 0, c2 = 0, a3 = 0, a4 = 0, a5 = 0, two_fr_kb = 0;
    if (kind == 1) {
        const double fr = friction_per_fs / loup::ASE_FS;  // 1/fs -> 1/(ASE time unit), as ASE's friction=f/units.fs
        c1 = dt_ase / 2.0 - dt_ase * dt_ase * fr / 8.0;
        c2 = dt_ase * fr / 2.0 - dt_ase * dt_ase * fr * fr / 8.0;
        two_fr_kb = 2.0 * fr * loup::ASE_KB;
        a3 = sqrt(dt_ase) / 2.0 - pow(dt_ase, 1.5) * fr / 8.0;
        a5 = pow(dt_ase, 1.5) / (2.0 * sqrt(3.0));
        a4 = (fr / 2.0) * a5;
        // The target of this call's first step (its end point), the change per step, and the first step's noise
        // coefficients; the second half-kick advances all of them.
        const double first = temp_k + temp_rate;
        const double sigma = sqrt(two_fr_kb * (first > 0.0 ? first : 0.0));
        const double target[5] = {first, temp_rate, a3 * sigma, a4 * sigma, a5 * sigma};
        CUDA_CHECK(cudaMemcpy(h->d_langevin_target, target, sizeof(target), cudaMemcpyHostToDevice));
    }
    // CSVR (kind 2): ASE's exp(-dt / taut). The target of the call's first step and its change per step go into the
    // thermostat target's first two slots; the scaling's own kernel advances them. The transferred energy carries
    // on from the last CSVR call on this trajectory.
    double csvr_exp = 0.0;
    if (kind == 2) {
        csvr_exp = exp(-dt_fs / tau_fs);
        const double target[5] = {temp_k + temp_rate, temp_rate, 0.0, 0.0, 0.0};
        CUDA_CHECK(cudaMemcpy(h->d_langevin_target, target, sizeof(target), cudaMemcpyHostToDevice));
        if (h->int_state_kind != LOUP_CSVR) {
            CUDA_CHECK(cudaMemsetAsync(h->d_int_state, 0, kIntStateSlots * sizeof(double), h->stream));
            h->int_state_kind = LOUP_CSVR;
        }
        CUDA_CHECK(cudaMemsetAsync(h->d_int_work, 0, kIntWorkSlots * sizeof(double), h->stream));
    }
    // Berendsen (kind 4, and 5 with its barostat): the target as for CSVR; it has no state of its own.
    if (kind == 4 || kind == 5) {
        const double target[5] = {temp_k + temp_rate, temp_rate, 0.0, 0.0, 0.0};
        CUDA_CHECK(cudaMemcpy(h->d_langevin_target, target, sizeof(target), cudaMemcpyHostToDevice));
        const int state_kind = kind == 4 ? LOUP_BERENDSEN_NVT : LOUP_BERENDSEN_NPT;
        if (h->int_state_kind != state_kind) {
            CUDA_CHECK(cudaMemsetAsync(h->d_int_state, 0, kIntStateSlots * sizeof(double), h->stream));
            h->int_state_kind = state_kind;
        }
        CUDA_CHECK(cudaMemsetAsync(h->d_int_work, 0, kIntWorkSlots * sizeof(double), h->stream));
    }
    // Langevin BAOAB NPT (kind 6): ASE's constants. T_tau = 1 / friction; P_tau = tau_p (0: ASE's default of
    // 20 T_tau); the barostat's mass from ASE's heuristic for a period of P_tau / 4; its thermostat's rate 1 / P_tau.
    // The external stress is minus the target pressure. The barostat's momentum and the cell force carry on from
    // the last such call on this trajectory; a first call forms the cell force from the state it finds.
    double bao_gamma = 0.0, bao_ou = 0.0, bao_gamma_b = 0.0, bao_ou_b = 0.0, bao_mass = 0.0;
    const int bao_ndof = 3 * N;
    bool bao_start = false;
    if (kind == 6) {
        bao_gamma = friction_per_fs / loup::ASE_FS;
        bao_ou = sqrt(1.0 - exp(-2.0 * bao_gamma * dt_ase));
        const double p_tau = (npt->tau_p_fs > 0.0 ? npt->tau_p_fs : 20.0 / friction_per_fs) * loup::ASE_FS;
        const double c = 1.66 * loup::ASE_FS;
        bao_mass = pow((p_tau / 4.0) / c * pow((double)N, 1.0 / 6.0), 2.0);
        bao_gamma_b = 1.0 / p_tau;
        bao_ou_b = sqrt(1.0 - exp(-2.0 * bao_gamma_b * dt_ase)) * sqrt(bao_mass);
        const double target[5] = {temp_k + temp_rate, temp_rate, 0.0, 0.0, 0.0};
        CUDA_CHECK(cudaMemcpy(h->d_langevin_target, target, sizeof(target), cudaMemcpyHostToDevice));
        if (h->int_state_kind != LOUP_BAOAB_NPT) {
            CUDA_CHECK(cudaMemsetAsync(h->d_int_state, 0, kIntStateSlots * sizeof(double), h->stream));
            h->int_state_kind = LOUP_BAOAB_NPT;
            bao_start = true;
        }
        CUDA_CHECK(cudaMemsetAsync(h->d_int_work, 0, kIntWorkSlots * sizeof(double), h->stream));
    }
    // Martyna-Tobias-Klein NPT (kind 7): ASE's masses from the temperature the masses are made for: the
    // thermostat's unit kT tdamp^2, the barostat chain's kT pdamp^2, the cell's W = (N_f + 3) kT pdamp^2
    // (isotropic) or (N_f / 3 + 1) kT pdamp^2 (full cell). Chains and cell momentum carry on from the last such
    // call on this trajectory.
    double mtk_q = 0.0, mtk_r = 0.0, mtk_w = 0.0;
    if (kind == 7) {
        const double tdamp = tau_fs * loup::ASE_FS, pdamp = npt->tau_p_fs * loup::ASE_FS;
        const double kt_mass = loup::ASE_KB * mass_temp_k;
        mtk_q = kt_mass * tdamp * tdamp;
        mtk_r = kt_mass * pdamp * pdamp;
        // N_f of this call: h->fix_com is set for it further down, so h->kinetic_dof() would still be the last call's
        // (a first call with fix_com made W from 3N, later ones from 3N - 3; the tiled MD's W is the same as this one)
        const int n_f = 3 * (N - h->n_fixed) - (fix_com ? 3 : 0);
        mtk_w = (npt->full ? (double)n_f / 3.0 + 1.0 : (double)n_f + 3.0) * mtk_r;
        const double target[5] = {temp_k + temp_rate, temp_rate, 0.0, 0.0, 0.0};
        CUDA_CHECK(cudaMemcpy(h->d_langevin_target, target, sizeof(target), cudaMemcpyHostToDevice));
        if (h->int_state_kind != LOUP_MTK_NPT) {
            CUDA_CHECK(cudaMemsetAsync(h->d_int_state, 0, kIntStateSlots * sizeof(double), h->stream));
            h->int_state_kind = LOUP_MTK_NPT;
        }
        CUDA_CHECK(cudaMemsetAsync(h->d_int_work, 0, kIntWorkSlots * sizeof(double), h->stream));
    }
    // Nose-Hoover chain (kind 3): the thermostat masses' unit kT_mass tdamp^2 (Q_0 = N_f q, the others q), and the
    // target as for CSVR. The chain's variables carry on from the last Nose-Hoover call on this trajectory.
    double nhc_q = 0.0;
    if (kind == 3) {
        const double tdamp = tau_fs * loup::ASE_FS;
        nhc_q = loup::ASE_KB * mass_temp_k * tdamp * tdamp;
        const double target[5] = {temp_k + temp_rate, temp_rate, 0.0, 0.0, 0.0};
        CUDA_CHECK(cudaMemcpy(h->d_langevin_target, target, sizeof(target), cudaMemcpyHostToDevice));
        if (h->int_state_kind != LOUP_NHC) {
            CUDA_CHECK(cudaMemsetAsync(h->d_int_state, 0, kIntStateSlots * sizeof(double), h->stream));
            h->int_state_kind = LOUP_NHC;
        }
        CUDA_CHECK(cudaMemsetAsync(h->d_int_work, 0, kIntWorkSlots * sizeof(double), h->stream));
    }
    // SPDX-SnippetEnd

    // fix_com: the buffers of the two-pass noise, and for NVE the total momentum removed once (the forces of a
    // periodic system sum to zero to rounding, so it stays removed).
    const double inv_total_mass = fix_com ? 1.0 / h->total_mass : 0.0;
    if (fix_com) {
        if (!h->d_com) CUDA_CHECK(cudaMalloc(&h->d_com, 6 * sizeof(double)));
        if (kind == 1 && !h->d_rnd_pos) CUDA_CHECK(cudaMalloc(&h->d_rnd_pos, (size_t)N * 3 * sizeof(double)));
        if (kind != 1) {  // NVE and CSVR (whose scaling keeps a zero total momentum zero)
            CUDA_CHECK(cudaMemsetAsync(h->d_com, 0, 6 * sizeof(double), h->stream));
            loup::momentum_sum_kernel<<<(N + 255) / 256, 256, 0, h->stream>>>(N, h->d_masses, h->d_vel64, h->d_com);
            loup::momentum_remove_kernel<<<(N + 255) / 256, 256, 0, h->stream>>>(N, inv_total_mass, h->d_com,
                                                                                  h->d_vel64);
        }
    }
    if (!ext) h->fix_com = fix_com;

    auto record_move = [&] {
        if (kind == 1 && fix_com) {
            // (No CUDA_CHECK inside this lambda: a failed node fails the capture, which is checked.)
            (void)cudaMemsetAsync(h->d_com, 0, 6 * sizeof(double), h->stream);
            loup::langevin_noise_kernel<<<(N + 31) / 32, 32, 0, h->stream>>>(
                N, h->d_langevin_target, seed, h->d_step_counter, h->d_masses, h->d_sqrt_inv_masses, h->d_rnd_pos,
                h->d_rnd_vel, h->d_com);
            loup::langevin_first_half_fixcom_kernel<<<gridN, 256, 0, h->stream>>>(
                N, dt_ase, c1, c2, inv_total_mass, h->d_com, h->d_forces_f64, h->d_inv_masses, h->d_rnd_pos,
                h->d_rnd_vel, h->d_pos64, h->d_vel64, h->d_max_step_disp2);
        } else if (kind == 0) {
            loup::nve_first_half_kernel<<<gridN, 256, 0, h->stream>>>(
                N, dt_ase, h->d_forces_f64, h->d_inv_masses, h->d_pos64, h->d_vel64, h->d_max_step_disp2);
        } else if (kind == 4) {
            // The kinetic temperature, lambda from it, then the half-kick on the scaled velocities.
            loup::kinetic_energy_kernel<<<gridN, 256, 0, h->stream>>>(N, h->d_masses, h->d_vel64, h->d_int_work);
            loup::berendsen_scale_kernel<<<1, 1, 0, h->stream>>>(h->kinetic_dof(), dt_fs / tau_fs, loup::ASE_KB,
                                                                 h->d_langevin_target, h->d_int_work);
            loup::csvr_first_half_kernel<<<gridN, 256, 0, h->stream>>>(
                N, dt_ase, h->d_int_work, h->d_forces_f64, h->d_inv_masses, h->d_pos64, h->d_vel64,
                h->d_max_step_disp2);
        } else if (kind == 7) {
            // MTK NPT: the kinetic tensor, one thread for both chains, the cell kick and the step's matrices,
            // then every atom's scaling, kick and drift (integrator.cu).
            loup::kinetic_tensor_kernel<<<gridN, 256, 0, h->stream>>>(N, h->d_masses, h->d_vel64,
                                                                      h->d_int_work + 44);
            loup::mtk_first_kernel<<<1, 1, 0, h->stream>>>(
                npt->full, dt_ase, tchain, tloop, npt->pchain, npt->ploop, h->kinetic_dof(), mtk_q, mtk_r, mtk_w,
                loup::ASE_KB, npt->pressure, h->d_langevin_target, h->d_int_state, h->d_int_work,
                h->d_virial_grad_f64, h->d_celldev);
            loup::mtk_first_atoms_kernel<<<gridN, 256, 0, h->stream>>>(
                N, dt_ase, h->d_int_work, h->d_forces_f64, h->d_inv_masses, h->d_pos64, h->d_vel64,
                h->d_max_step_disp2);
        } else if (kind == 6) {
            // Langevin BAOAB NPT: one thread for the barostat and the step's matrices, then every atom's B, A, O, A
            // with the cell's two half steps around them (integrator.cu).
            loup::baoab_cell_first_kernel<<<1, 1, 0, h->stream>>>(
                npt->full, dt_ase, bao_gamma, bao_ou, bao_gamma_b, bao_ou_b, bao_mass, bao_ndof, loup::ASE_KB, seed,
                h->d_step_counter, h->d_langevin_target, h->d_int_state, h->d_int_work, h->d_celldev);
            loup::baoab_first_kernel<<<(N + 31) / 32, 32, 0, h->stream>>>(
                N, dt_ase, h->d_int_work, seed, h->d_step_counter, h->d_forces_f64, h->d_inv_masses,
                h->d_sqrt_inv_masses, h->d_pos64, h->d_vel64, h->d_max_step_disp2);
        } else if (kind == 5) {
            // Berendsen NPT: lambda from the kinetic energy; the barostat's factors from the stress of the last
            // force pass and the scaled velocities' ideal-gas part; the atoms scaled with the cell (the cell
            // itself follows in cell_derive_kernel below); then the half-kick on the scaled velocities and the
            // drift. One force call per step, as FastMACE's port: ASE's class kicks with forces of the scaled cell.
            loup::kinetic_energy_kernel<<<gridN, 256, 0, h->stream>>>(N, h->d_masses, h->d_vel64, h->d_int_work);
            if (npt->full) {
                loup::kinetic_diag_kernel<<<gridN, 256, 0, h->stream>>>(N, h->d_masses, h->d_vel64,
                                                                        h->d_int_work + 2);
            }
            loup::berendsen_scale_kernel<<<1, 1, 0, h->stream>>>(h->kinetic_dof(), dt_fs / tau_fs, loup::ASE_KB,
                                                                 h->d_langevin_target, h->d_int_work);
            loup::berendsen_npt_kernel<<<1, 1, 0, h->stream>>>(
                npt->full, npt->mask[0], npt->mask[1], npt->mask[2], npt->pressure, dt_fs, npt->tau_p_fs,
                npt->compressibility, h->d_int_work, h->d_virial_grad_f64, h->d_celldev);
            loup::cell_move_positions_kernel<<<gridN, 256, 0, h->stream>>>(N, h->d_celldev, h->d_pos64);
            loup::csvr_first_half_kernel<<<gridN, 256, 0, h->stream>>>(
                N, dt_ase, h->d_int_work, h->d_forces_f64, h->d_inv_masses, h->d_pos64, h->d_vel64,
                h->d_max_step_disp2);
        } else if (kind == 3) {
            // The chain for half a step from the kinetic energy; the half-kick on the velocities it scales.
            loup::kinetic_energy_kernel<<<gridN, 256, 0, h->stream>>>(N, h->d_masses, h->d_vel64, h->d_int_work);
            loup::nhc_half_kernel<<<1, 1, 0, h->stream>>>(h->kinetic_dof(), tchain, tloop, 0.5 * dt_ase, nhc_q,
                                                          loup::ASE_KB, 0, h->d_langevin_target, h->d_int_work,
                                                          h->d_int_state);
            loup::csvr_first_half_kernel<<<gridN, 256, 0, h->stream>>>(
                N, dt_ase, h->d_int_work, h->d_forces_f64, h->d_inv_masses, h->d_pos64, h->d_vel64,
                h->d_max_step_disp2);
        } else if (kind == 2) {
            // The kinetic energy, alpha from it and this step's noise, then the half-kick on the scaled velocities.
            loup::kinetic_energy_kernel<<<gridN, 256, 0, h->stream>>>(N, h->d_masses, h->d_vel64, h->d_int_work);
            loup::csvr_alpha_kernel<<<1, 1, 0, h->stream>>>(h->kinetic_dof(), csvr_exp, loup::ASE_KB, seed,
                                                            h->d_step_counter, h->d_langevin_target, h->d_int_work,
                                                            h->d_int_state);
            loup::csvr_first_half_kernel<<<gridN, 256, 0, h->stream>>>(
                N, dt_ase, h->d_int_work, h->d_forces_f64, h->d_inv_masses, h->d_pos64, h->d_vel64,
                h->d_max_step_disp2);
        } else if (kind == 1) {
            // 32 atoms per block: the FP64 Box-Muller (3 curand_normal2_double per atom) is FP64-throughput bound on
            // consumer GPUs, so spread the atoms over every SM instead of N / 256 of them; S106: one thread per draw.
            loup::langevin_first_half_kernel<<<(N + 31) / 32, 96, 0, h->stream>>>(
                N, dt_ase, c1, c2, h->d_langevin_target, seed, h->d_step_counter,
                h->d_forces_f64, h->d_inv_masses, h->d_sqrt_inv_masses,
                h->d_pos64, h->d_vel64, h->d_rnd_vel, h->d_max_step_disp2);
        }
        if (var_cell) {
            // Whoever moves the cell sets this step's deformation; the atoms follow it, then the cell itself and
            // what the step needs from it. The list check measures from the deformed reference.
            if (cell_rate != 0.0) {
                loup::cell_debug_rate_kernel<<<1, 1, 0, h->stream>>>(cell_rate, h->d_celldev);
                loup::cell_move_positions_kernel<<<gridN, 256, 0, h->stream>>>(N, h->d_celldev, h->d_pos64);
            }
            loup::cell_derive_kernel<<<1, 1, 0, h->stream>>>(h->d_celldev, h->d_need_rebuild);
            loup::check_skin_cell_kernel<<<gridN, 256, 0, h->stream>>>(
                N, h->d_pos64, h->d_ref_pos64, h->d_celldev, h->d_need_rebuild);
            return;
        }
        if (host_io)
            CUDA_CHECK_THROW(cudaMemcpyAsync(h->d_pos64, h->stage_pos(), (size_t)N * 3 * sizeof(double),
                                             cudaMemcpyHostToDevice, h->stream));
        loup::check_skin_kernel<<<gridN, 256, 0, h->stream>>>(N, half_skin, h->d_pos64, h->d_ref_pos64,
                                                              h->d_need_rebuild);
    };
    auto record_rest = [&]() {
        if (var_cell && h->E_graph > 0) {  // the edges' Cartesian shifts in the cell of this step
            loup::shift_cart_kernel<<<(h->E_graph + 255) / 256, 256, 0, h->stream>>>(
                h->d_row_ptr + N, h->d_celldev, h->d_cell_codes, h->d_shift_cart);
        }
        h->disp_cell_dev = var_cell;
        record_force_pass(h, var_cell || ext_stress ? 1 : 0);
        h->disp_cell_dev = false;
        if (kind == 6) {  // the cell force from the velocities before the last kick, then barostat B
            loup::kinetic_tensor_kernel<<<gridN, 256, 0, h->stream>>>(N, h->d_masses, h->d_vel64, h->d_int_work);
            loup::baoab_cell_second_kernel<<<1, 1, 0, h->stream>>>(
                npt->full, 1, 1, dt_ase, bao_ndof, -npt->pressure, h->d_virial_grad_f64, h->d_celldev, h->d_int_work,
                h->d_int_state, h->d_step_counter);
        }
        if (kind == 7) {  // the atom kick, the cell kick with the new stress, both chains
            loup::mtk_kick_kernel<<<gridN, 256, 0, h->stream>>>(N, dt_ase, h->d_int_work, h->d_forces_f64,
                                                                h->d_inv_masses, h->d_vel64);
            loup::kinetic_tensor_kernel<<<gridN, 256, 0, h->stream>>>(N, h->d_masses, h->d_vel64,
                                                                      h->d_int_work + 44);
            loup::mtk_second_kernel<<<1, 1, 0, h->stream>>>(
                npt->full, dt_ase, tchain, tloop, npt->pchain, npt->ploop, h->kinetic_dof(), mtk_q, mtk_r, mtk_w,
                loup::ASE_KB, npt->pressure, h->d_langevin_target, h->d_int_state, h->d_int_work,
                h->d_virial_grad_f64, h->d_celldev);
            loup::scale_velocities_kernel<<<gridN, 256, 0, h->stream>>>(N, h->d_int_work, h->d_vel64);
        } else if (ext) {
            // the caller integrates
        } else if (kind != 1) {
            loup::nve_second_half_kernel<<<gridN, 256, 0, h->stream>>>(
                N, dt_ase, h->d_forces_f64, h->d_inv_masses, h->d_vel64);
        } else if (kind == 1) {
            loup::langevin_second_half_kernel<<<gridN, 256, 0, h->stream>>>(
                N, c1, c2, h->d_forces_f64, h->d_inv_masses, h->d_rnd_vel, h->d_vel64, h->d_step_counter,
                h->d_langevin_target, a3, a4, a5, two_fr_kb);
        }
        if (kind == 3) {  // the chain's second half, which also moves the target on
            loup::kinetic_energy_kernel<<<gridN, 256, 0, h->stream>>>(N, h->d_masses, h->d_vel64, h->d_int_work);
            loup::nhc_half_kernel<<<1, 1, 0, h->stream>>>(h->kinetic_dof(), tchain, tloop, 0.5 * dt_ase, nhc_q,
                                                          loup::ASE_KB, 1, h->d_langevin_target, h->d_int_work,
                                                          h->d_int_state);
            loup::scale_velocities_kernel<<<gridN, 256, 0, h->stream>>>(N, h->d_int_work, h->d_vel64);
        }
        if (thermo_every > 0) {  // the row cadence lives on the device: only on / off is baked into the graph
            loup::thermo_kinetic_kernel<<<gridN, 256, 0, h->stream>>>(N, h->d_masses, h->d_vel64, h->d_thermo_ctrl);
            loup::thermo_row_kernel<<<1, 1, 0, h->stream>>>(h->kinetic_dof(), h->e0_total, loup::ASE_KB,
                                                            h->d_energy_f64,
                                                            h->d_thermo_ctrl, h->d_thermo_rows,
                                                            kind >= 2 ? h->d_int_state : nullptr,
                                                            var_cell ? h->d_celldev : nullptr,
                                                            var_cell ? h->d_virial_grad_f64 : nullptr);
        }
    };
    const double npt_key[7] = {npt ? npt->pressure : 0.0, npt ? npt->tau_p_fs : 0.0, npt ? npt->compressibility : 0.0,
                               npt ? (double)npt->full : 0.0,
                               npt ? (double)(npt->mask[0] + 2 * npt->mask[1] + 4 * npt->mask[2]) : 0.0,
                               npt ? (double)npt->pchain : 0.0, npt ? (double)npt->ploop : 0.0};
    // Captures into graph g: prologue(conds) with one new conditional handle per body, then one IF node per handle
    // after the prologue, then each body into its IF node's graph (a body may nest this call). Each level's capture
    // ends before its bodies are captured, as the force pass records on h->stream.
    using Prologue = std::function<void(const cudaGraphConditionalHandle*)>;
    using Body = std::function<int(cudaGraph_t)>;
    std::function<int(cudaGraph_t, const Prologue&, const std::vector<Body>&)> capture_ifs =
        [&](cudaGraph_t g, const Prologue& prologue, const std::vector<Body>& bodies) -> int {
        const size_t n = bodies.size();
        std::vector<cudaGraphConditionalHandle> conds(n);
        for (size_t i = 0; i < n; ++i) CUDA_CHECK(cudaGraphConditionalHandleCreate(&conds[i], g, 0, 0));
        CaptureScope cap(h);
        CUDA_CHECK(cap.begin_into(g));
        prologue(conds.data());
        cudaStreamCaptureStatus status;
        const cudaGraphNode_t* deps_p = nullptr;
        size_t n_deps = 0;
        CUDA_CHECK(cudaStreamGetCaptureInfo(h->stream, &status, nullptr, nullptr, &deps_p, nullptr, &n_deps));
        const std::vector<cudaGraphNode_t> deps(deps_p, deps_p + n_deps);
        std::vector<cudaGraphNode_t> nodes(n);
        std::vector<cudaGraph_t> body_graphs(n);
        for (size_t i = 0; i < n; ++i) {
            cudaGraphNodeParams cp = {};
            cp.type = cudaGraphNodeTypeConditional;
            cp.conditional.handle = conds[i];
            cp.conditional.type = cudaGraphCondTypeIf;
            cp.conditional.size = 1;
            CUDA_CHECK(cudaGraphAddNode(&nodes[i], g, deps.data(), nullptr, deps.size(), &cp));
            body_graphs[i] = cp.conditional.phGraph_out[0];
        }
        CUDA_CHECK(cudaStreamUpdateCaptureDependencies(h->stream, nodes.data(), nullptr, n,
                                                       cudaStreamSetCaptureDependencies));
        cudaGraph_t captured = nullptr;
        CUDA_CHECK(cap.end(&captured));
        for (size_t i = 0; i < n; ++i)
            if (bodies[i](body_graphs[i]) != 0) return -1;
        return 0;
    };
    const Body rest_body = [&](cudaGraph_t g) -> int {
        CaptureScope cap(h);
        CUDA_CHECK(cap.begin_into(g));
        record_rest();
        cudaGraph_t captured = nullptr;
        CUDA_CHECK(cap.end(&captured));
        return 0;
    };
    // The checked rest: rest_guard_kernel + IF (valid rows) rest.
    const Body checked_rest_body = [&](cudaGraph_t g) -> int {
        return capture_ifs(g, [&](const cudaGraphConditionalHandle* c) {
            loup::rest_guard_kernel<<<1, 1, 0, h->stream>>>(c[0], h->d_order_err, nullptr);
        }, {rest_body});
    };
    auto instantiate = [&](cudaGraph_t& g, cudaGraphExec_t& ge, const Body& body) -> int {
        if (ge) { cudaGraphExecDestroy(ge); ge = nullptr; }
        if (g) { cudaGraphDestroy(g); g = nullptr; }
        if (debug_graphs) fputs("loupmd: MD graph capture\n", stderr);
        CUDA_CHECK(cudaGraphCreate(&g, 0));
        if (body(g) != 0) return -1;
        CUDA_CHECK(cudaGraphInstantiate(&ge, g, nullptr, nullptr, 0));
        return 0;
    };
    auto note_params = [&] {
        h->md_graph_kind = kind;
        h->md_graph_dt = dt_fs;
        h->md_graph_fr = friction_per_fs;
        h->md_graph_tau = tau_fs;
        h->md_graph_mass_temp = mass_temp_k;
        h->md_graph_chain = 1000 * tchain + tloop;
        h->md_graph_seed = seed;
        h->md_graph_thermo = thermo_every > 0;
        h->md_graph_fixcom = fix_com;
        h->md_graph_varcell = var_cell;
        h->md_graph_cellrate = cell_rate;
        memcpy(h->md_graph_npt, npt_key, sizeof(npt_key));
    };
    // The step graph's rebuild branch needs fixed sizes: the edge bucket and a row-sort width with a quarter of headroom
    // over the last rebuild's longest row. Systems whose rebuilds reorder the atoms (a host round trip) or sort rows in
    // global scratch keep the host-driven rebuild, as does a system's first rebuild (it times kernel variants), and a
    // variable-cell run (its rebuild needs the device's cell on the host first; its bin grid follows the cell).
    const NlGeom nl_g = nl_geom(h);
    auto rebuild_width = [&] { return pow2_at_least(std::max(32, h->max_deg_last + h->max_deg_last / 4 + 1)); };
    auto device_rebuild_ok = [&] {
        return h->ovr.md_rebuild != 1 && h->variants_tuned && h->E_graph > 0 && !reorder_atoms(h) &&
               !h->ovr.row_sort_global && rebuild_width() <= 4096 && !var_cell;
    };
    auto ensure_graphs = [&]() -> int {
        if (h->md_step_exec && h->md_checked_exec) return 0;
        const bool dev = device_rebuild_ok();
        if (dev && ensure_cub_tmp(h, nl_cub_bytes(h, nl_g)) != 0) return -1;
        const int E_lim = h->ovr.md_rebuild == 2 ? 0 : h->E_graph;  // fallback (tests): never fits
        const int P_cap = rebuild_width();
        // The rebuild branch: count, gate (its verdict in go = d_max_deg + 1), then fill, sort and commit, which skip
        // themselves on a negative verdict, and the checked rest, also gated by the verdict.
        const int* go = h->d_max_deg + 1;
        const Body rebuild_body = [&](cudaGraph_t g) -> int {
            return capture_ifs(g, [&](const cudaGraphConditionalHandle* c) {
                nl_bin(h, nl_g);
                nl_count(h, nl_g);
                loup::rebuild_gate_kernel<<<1, 1, 0, h->stream>>>(h->d_row_ptr + N, h->d_max_deg, E_lim, P_cap,
                                                                   h->d_max_deg + 1, h->d_pub_counter, h->d_pub);
                nl_fill(h, nl_g, P_cap, go);
                nl_commit(h, go);
                loup::rest_guard_kernel<<<1, 1, 0, h->stream>>>(c[0], h->d_order_err, go);
            }, {rest_body});
        };
        // The step graph: move + check + guard_step_kernel, then one SWITCH node (body 0 the rest, body 1 the rebuild
        // branch when dev).
        const Body step_body = [&](cudaGraph_t g) -> int {
            cudaGraphConditionalHandle c;
            CUDA_CHECK(cudaGraphConditionalHandleCreate(&c, g, 0, 0));
            CaptureScope cap(h);
            CUDA_CHECK(cap.begin_into(g));
            record_move();
            loup::guard_step_kernel<<<1, 1, 0, h->stream>>>(c, dev ? 1 : 0, h->d_need_rebuild, h->d_order_err,
                                                             h->d_pub_counter, h->d_pub);
            cudaStreamCaptureStatus status;
            const cudaGraphNode_t* deps_p = nullptr;
            size_t n_deps = 0;
            CUDA_CHECK(cudaStreamGetCaptureInfo(h->stream, &status, nullptr, nullptr, &deps_p, nullptr, &n_deps));
            const std::vector<cudaGraphNode_t> deps(deps_p, deps_p + n_deps);
            cudaGraphNodeParams cp = {};
            cp.type = cudaGraphNodeTypeConditional;
            cp.conditional.handle = c;
            cp.conditional.type = cudaGraphCondTypeSwitch;
            cp.conditional.size = dev ? 2 : 1;
            cudaGraphNode_t node;
            CUDA_CHECK(cudaGraphAddNode(&node, g, deps.data(), nullptr, deps.size(), &cp));
            CUDA_CHECK(cudaStreamUpdateCaptureDependencies(h->stream, &node, nullptr, 1,
                                                           cudaStreamSetCaptureDependencies));
            // After the SWITCH node, whichever body ran (or none): the results' copies and their publication.
            if (host_io && queue_results(h) != 0) return -1;
            cudaGraph_t captured = nullptr;
            CUDA_CHECK(cap.end(&captured));
            if (rest_body(cp.conditional.phGraph_out[0]) != 0) return -1;
            if (dev && rebuild_body(cp.conditional.phGraph_out[1]) != 0) return -1;
            return 0;
        };
        if (instantiate(h->md_step_graph, h->md_step_exec, step_body) != 0) return -1;
        if (instantiate(h->md_checked_graph, h->md_checked_exec, checked_rest_body) != 0) return -1;
        h->md_dev_rebuild = dev;
        note_params();
        return 0;
    };
    // The graphs bake in dt, friction, time constant and seed: those of an earlier call are kept when all are the same
    // (review item S4) and dropped otherwise. The thermostat's temperature is not baked in (d_langevin_target), so a
    // schedule's calls reuse the graphs. Everything else a graph bakes in (edge bucket, scan workspace, kernel
    // variants, the long-range part's cell) drops the graphs where it changes: invalidate_graphs.
    if (h->md_graph_kind != kind || h->md_graph_dt != dt_fs ||
        h->md_graph_fr != friction_per_fs || h->md_graph_tau != tau_fs || h->md_graph_seed != seed ||
        h->md_graph_mass_temp != mass_temp_k || h->md_graph_chain != 1000 * tchain + tloop ||
        h->md_graph_thermo != (thermo_every > 0) ||
        h->md_graph_fixcom != fix_com || h->md_graph_varcell != var_cell || h->md_graph_cellrate != cell_rate ||
        memcmp(h->md_graph_npt, npt_key, sizeof(npt_key)) != 0) {
        h->invalidate_md_graphs();
    }

    int rebuilds = 0;
    double tune_ms = 0.0;
    int host_rebuilds = 0;  // rebuilds the host finished (the GPU waited for them): LoupMDStats::pipelined_steps

    // One step: launch the step graph, read the guard's publication, and on a rebuild that the graph could not finish
    // on the GPU, finish it on the host and launch the checked rest.
    auto step_once = [&](int step) -> int {
        if (h->armed) {
            // queued ahead by the previous loup_evaluate, behind the wait on *h_go: the store lets it run
            __atomic_store_n(h->h_go, h->go_seq, __ATOMIC_SEQ_CST);
            h->armed = false;
        } else {
            if (ensure_graphs() != 0) return -1;
            CUDA_CHECK(cudaGraphLaunch(h->md_step_exec, h->stream));
        }
        const bool probing = h->probe && host_io;
        const auto probe_launched = probing ? std::chrono::steady_clock::now() : std::chrono::steady_clock::time_point{};
        int v[3];
        if (wait_published(h, ++h->pub_count, v) != 0) return -1;
        const auto probe_guard = probing ? std::chrono::steady_clock::now() : std::chrono::steady_clock::time_point{};
        if (v[1]) return order_error();
        // host_io: the step graph ends with the results' copy and its publication `fin` (the rows' order flag),
        // whichever branch ran; the staging holds this step's results once it has landed, if the force pass ran.
        int fin[3] = {0, 0, 0};
        if (!v[0]) {
            if (host_io && wait_published(h, ++h->pub_count, fin) != 0) return -1;
            if (probing) {
                h->probe_t[0] = probe_launched;
                h->probe_t[1] = probe_guard;
                h->probe_t[2] = std::chrono::steady_clock::now();
            }
            if (!ext) note_step();
            return fin[0] ? order_error() : 0;
        }
        if (var_cell && (v[0] & 8)) {  // cell_derive_kernel: the volume left its limits
            loup::CellDev c;
            if (download_cell_dev(h, &c) != 0) return -1;
            h->cell_ref_stale = true;
            loup::set_error("the cell diverged: its volume is %g A^3, outside [V0 / 20, 20 V0] with V0 = %g A^3 "
                            "(step %lld of the trajectory); the state on the handle is that step's",
                            c.volume, c.v0, (long long)(h->md_steps + step + 1));
            return -1;
        }
        ++rebuilds;
        if (!ext) {
            if (h->disp_window_steps >= kDispWindowMin) rotate_disp();
            note_step();
        }
        if (h->md_dev_rebuild) {
            // The step graph's rebuild branch has counted the new rows; it went on to fill them and run the checked
            // rest on the GPU if they fit its captured sizes.
            int w[3];
            if (wait_published(h, ++h->pub_count, w) != 0) return -1;
            h->E_skin = w[0];
            h->max_deg_last = w[1];
            if (host_io && wait_published(h, ++h->pub_count, fin) != 0) return -1;
            if (w[2]) return fin[0] ? order_error() : 0;
            // They did not: once the step graph has drained, finish the rebuild on the host from the counted rows and
            // recapture the graphs for the new sizes.
            int z[3];
            if (read_device_ints(h, nullptr, nullptr, nullptr, z) != 0) return -1;
            ++host_rebuilds;
            h->nl_valid = false;
            if (nl_finish(h, nl_g, w[0], w[1], false) != 0) return -1;
            h->invalidate_md_graphs();
        } else {
            if (host_io && wait_published(h, ++h->pub_count, fin) != 0) return -1;  // of the pass the guard skipped
            ++host_rebuilds;
            // The per-system variant timing (first rebuild only) is not part of the steps: it is timed and excluded.
            if (!h->variants_tuned) {
                const auto t0 = std::chrono::steady_clock::now();
                tune_rebuild_variants(h);
                tune_ms += std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
            }
            if (var_cell && download_cell_dev(h) != 0) return -1;  // the list is built in the cell of now
            // The row-order flag is read with the next step's publication (or at the end of the block); until then
            // the checked rest's guard keeps the force pass off rows that failed it.
            if (rebuild_neighbors(h, false) != 0) return -1;
            if (device_rebuild_ok()) h->invalidate_md_graphs();  // the step graph gains its rebuild branch
        }
        if (ensure_graphs() != 0) return -1;
        CUDA_CHECK(cudaGraphLaunch(h->md_checked_exec, h->stream));
        if (host_io) {
            if (queue_results(h) != 0 || wait_published(h, ++h->pub_count, fin) != 0) return -1;
            if (fin[0]) return order_error();
        }
        return 0;
    };
    // The step, then the variants' timing of a system that has had no rebuild for kTuneEarlyPasses passes (excluded
    // from step_ms with the rebuild's).
    auto one_step = [&](int step) -> int {
        if (step_once(step) != 0) return -1;
        tune_ms += tune_early_variants(h);
        return 0;
    };
    if (ext) {
        if (one_step(0) != 0) return -1;
        h->last_pass_stress = ext_stress != 0;  // the step's force pass, not the force graph's
        return 0;
    }

    if (bao_start) {  // LangevinBAOAB.__init__: the cell force of the forces, stress and velocities it starts from
        loup::kinetic_tensor_kernel<<<gridN, 256, 0, h->stream>>>(N, h->d_masses, h->d_vel64, h->d_int_work);
        loup::baoab_cell_second_kernel<<<1, 1, 0, h->stream>>>(
            npt->full, 0, 0, dt_ase, bao_ndof, -npt->pressure, h->d_virial_grad_f64, h->d_celldev, h->d_int_work,
            h->d_int_state, h->d_step_counter);
    }
    EventPairGuard evg;
    cudaEvent_t ev0 = evg.e0, ev1 = evg.e1;
    CUDA_CHECK(cudaEventRecord(ev0, h->stream));
    for (int step = 0; step < n_steps; ++step)
        if (one_step(step) != 0) return -1;
    CUDA_CHECK(cudaEventRecord(ev1, h->stream));
    CUDA_CHECK(cudaEventSynchronize(ev1));
    float ms = 0.0f;
    CUDA_CHECK(cudaEventElapsedTime(&ms, ev0, ev1));

    // The block's last energy (forces feed it every step): non-finite means the run is lost; with the hybrid GEMMs
    // loaded they are dropped first, so a run restarted from a saved state does not hit the same overflow.
    double inter_e = 0.0;
    int order_err = 0;  // a rebuild in the block's last step is not followed by a flag read
    CUDA_CHECK(cudaMemcpyAsync(&inter_e, h->d_energy_f64, sizeof(double), cudaMemcpyDeviceToHost, h->stream));
    CUDA_CHECK(cudaMemcpyAsync(&order_err, h->d_order_err, sizeof(int), cudaMemcpyDeviceToHost, h->stream));
    CUDA_CHECK(cudaStreamSynchronize(h->stream));
    if (order_err) return order_error();
    if (!std::isfinite(inter_e)) {
        drop_hybrid(h);
        loup::set_error("non-finite potential energy after the MD block: the state is lost; restart from a saved "
                        "state");
        return -1;
    }
    h->last_pass_stress = var_cell;  // the steps' force passes, not the force graph's
    if (var_cell) {  // the host's cell follows; a cell that moved since the list was built makes the plain check stale
        loup::CellDev c;
        if (download_cell_dev(h, &c) != 0) return -1;
        bool moved = false;
        for (int i = 0; i < 9; ++i) moved = moved || c.f[i] != ((i % 4 == 0) ? 1.0 : 0.0);
        h->cell_ref_stale = moved;
    }
    if (out_stats) {
        double ke = 0.0;
        CUDA_CHECK(cudaMemsetAsync(h->d_ke_f64, 0, sizeof(double), h->stream));
        loup::kinetic_energy_kernel<<<gridN, 256, 0, h->stream>>>(N, h->d_masses, h->d_vel64, h->d_ke_f64);
        CUDA_CHECK(cudaMemcpyAsync(&ke, h->d_ke_f64, sizeof(double), cudaMemcpyDeviceToHost, h->stream));
        CUDA_CHECK(cudaStreamSynchronize(h->stream));
        out_stats->step_ms = std::max(0.0, (double)ms - tune_ms) / n_steps;
        out_stats->rebuilds = rebuilds;
        out_stats->final_potential_energy_ev = h->e0_total + inter_e;
        out_stats->final_kinetic_energy_ev = ke;
        out_stats->final_temperature_k = (2.0 * ke) / ((double)h->kinetic_dof() * loup::ASE_KB);
        out_stats->dangerous_builds = 0;  // every force pass follows its own list check
        out_stats->pipelined_steps = n_steps - host_rebuilds;
        out_stats->tune_ms = tune_ms;
    }
    h->forces_current = true;
    h->md_steps += n_steps;
    h->thermo_pending += thermo_rows;
    return 0;
}

static int run_host_step(LoupHandle* h, int stress) {
    return run_md_loop(h, kStepHost, 1, 1.0, 0.0, 0.0, 0.0, (unsigned long long)stress, 0, false, nullptr);
}

static int read_thermo_impl(LoupHandle* h, LoupThermoRow* rows, int max_rows, int* n_rows) {
    if (!has_system(h)) return -1;
    if (!n_rows) { loup::set_error("n_rows is NULL"); return -1; }
    if (max_rows < 0 || (!rows && max_rows > 0)) {
        loup::set_error("rows is NULL or max_rows is negative (max_rows = %d)", max_rows);
        return -1;
    }
    const int have = h->thermo_pending;
    if (!rows) { *n_rows = have; return 0; }
    const int take = std::min(have, max_rows);
    *n_rows = take;
    if (take == 0) return 0;
    CUDA_CHECK(cudaSetDevice(h->device_id));
    CUDA_CHECK(cudaStreamSynchronize(h->stream));
    CUDA_CHECK(cudaMemcpy(rows, h->d_thermo_rows, (size_t)take * sizeof(LoupThermoRow), cudaMemcpyDeviceToHost));
    if (take < have) {  // keep the unread rest at the front
        std::vector<LoupThermoRow> rest((size_t)(have - take));
        CUDA_CHECK(cudaMemcpy(rest.data(), h->d_thermo_rows + take, rest.size() * sizeof(LoupThermoRow), cudaMemcpyDeviceToHost));
        CUDA_CHECK(cudaMemcpy(h->d_thermo_rows, rest.data(), rest.size() * sizeof(LoupThermoRow), cudaMemcpyHostToDevice));
    }
    h->thermo_pending = have - take;  // the device's count is written from this at the start of the next run
    return 0;
}

// loup_compute_device: the caller's rows (row r holds engine atom ids[r], or r without ids) to the engine's atom
// order and back. An id outside 0 .. n-1 sets bit 0 of *bad, a non-finite force bit 1.
static __global__ void io_gather_kernel(int n, const double* __restrict__ pos, long long rs, long long cs,
                                        const int* __restrict__ ids, const int* __restrict__ inv_perm,
                                        double* __restrict__ pos_out, int* bad) {
    const int r = blockIdx.x * blockDim.x + threadIdx.x;
    if (r >= n) return;
    const int a = ids ? ids[r] : r;
    if ((unsigned)a >= (unsigned)n) {
        atomicOr(bad, 1);
        return;
    }
    const int d = inv_perm[a];
    const double* p = pos + (long long)r * rs;
    pos_out[3 * d + 0] = p[0];
    pos_out[3 * d + 1] = p[cs];
    pos_out[3 * d + 2] = p[2 * cs];
}

static __global__ void io_scatter_kernel(int n, const int* __restrict__ ids, const int* __restrict__ inv_perm,
                                         const double* __restrict__ f, double* __restrict__ out, long long rs,
                                         long long cs, int* bad) {
    const int r = blockIdx.x * blockDim.x + threadIdx.x;
    if (r >= n) return;
    const int a = ids ? ids[r] : r;
    if ((unsigned)a >= (unsigned)n) return;
    const int d = inv_perm[a];
    const double fx = f[3 * d + 0], fy = f[3 * d + 1], fz = f[3 * d + 2];
    if (!(isfinite(fx) && isfinite(fy) && isfinite(fz))) atomicOr(bad, 2);
    double* o = out + (long long)r * rs;
    o[0] += fx;
    o[cs] += fy;
    o[2 * cs] += fz;
}

// One force evaluation for a host code that keeps its atoms on the GPU and integrates itself (LAMMPS Kokkos,
// LAMMPS_KOKKOS_PLAN.md stage B). Everything is queued behind the work already on the caller's stream, and the caller's
// stream is made to wait for the forces; the host waits only for the step graph's guard (which lands before the force
// pass starts), for a neighbour rebuild the graph could not finish on the GPU, and for the energy / virial when asked.
// A dispersion term set on the handle is part of the pass, as in every whole-system pass.
static int compute_device_impl(LoupHandle* h, const LoupDeviceIO* io, const double* cell, void* stream,
                               double* out_energy_ev, double* out_virial) {
    if (!has_system(h)) return -1;
    if (!io) {
        loup::set_error("io is NULL");
        return -1;
    }
    CUDA_CHECK(cudaSetDevice(h->device_id));
    const int N = h->N;
    if (io->n_rows != N || !io->positions || io->pos_row_stride <= 0 || io->pos_comp_stride <= 0 ||
        (io->forces && (io->f_row_stride <= 0 || io->f_comp_stride <= 0))) {
        loup::set_error("%d rows for a system of %d atoms, positions %s, strides %lld %lld / %lld %lld", io->n_rows, N,
                        io->positions ? "set" : "null", io->pos_row_stride, io->pos_comp_stride, io->f_row_stride,
                        io->f_comp_stride);
        return -1;
    }
    if ((io->flags & LOUP_IO_ATOM_ENERGY) || io->atom_energy) {
        loup::set_error("per-atom energies are not available on this call (loup_evaluate2 has them)");
        return -1;
    }
    if (!valid_cell(cell)) return -1;
    const bool want_e = (io->flags & LOUP_IO_ENERGY) && out_energy_ev;
    const bool want_v = (io->flags & LOUP_IO_VIRIAL) && out_virial;
    // The virial is formed in every pass: the steps that ask for it (thermo output, barostats) then run the same
    // captured graphs as the others instead of re-capturing them.
    const int stress = 1;
    const cudaStream_t cs = static_cast<cudaStream_t>(stream);

    if (!h->ev_io_in) {
        CUDA_CHECK(cudaEventCreateWithFlags(&h->ev_io_in, cudaEventDisableTiming));
        CUDA_CHECK(cudaEventCreateWithFlags(&h->ev_io_out, cudaEventDisableTiming));
    }
    if (!h->d_inv_perm) {
        CUDA_CHECK(cudaMalloc(&h->d_inv_perm, (size_t)N * sizeof(int)));
        CUDA_CHECK(cudaMalloc(&h->d_io_bad, sizeof(int)));
        CUDA_CHECK(cudaMemsetAsync(h->d_io_bad, 0, sizeof(int), h->stream));
    }
    auto sync_inv_perm = [&]() -> int {
        if (h->inv_perm_epoch == h->perm_epoch) return 0;
        std::vector<int> inv(N);
        for (int d = 0; d < N; ++d) inv[h->perm[d]] = d;
        CUDA_CHECK(cudaMemcpyAsync(h->d_inv_perm, inv.data(), (size_t)N * sizeof(int), cudaMemcpyHostToDevice, h->stream));
        h->inv_perm_epoch = h->perm_epoch;
        return 0;
    };
    if (sync_inv_perm() != 0) return -1;

    // The engine's work starts after everything the caller has queued on its stream.
    CUDA_CHECK(cudaEventRecord(h->ev_io_in, cs));
    CUDA_CHECK(cudaStreamWaitEvent(h->stream, h->ev_io_in, 0));

    // New positions and maybe a new cell, as upload_positions notes them.
    h->forces_current = false;
    ++h->pos_epoch;
    memcpy(h->cell_in, cell, sizeof(h->cell_in));
    loup::CellMat64 old_cell = h->cell;
    loup::compute_cell_mat(cell, h->cell, h->cell_vol, h->cell_heights);
    const bool cell_changed = memcmp(&old_cell, &h->cell, sizeof(old_cell)) != 0;
    if (h->gen->set_cell(cell)) h->invalidate_graphs();
    if (dispersion_cell_changed(h) != 0) return -1;

    const int grid = (N + 255) / 256;
    io_gather_kernel<<<grid, 256, 0, h->stream>>>(N, io->positions, io->pos_row_stride, io->pos_comp_stride, io->ids,
                                                  h->d_inv_perm, h->d_pos64, h->d_io_bad);
    if (cell_changed || !h->nl_valid || h->cell_ref_stale || h->lt_cache.empty()) {
        // A new cell (the list's Cartesian shifts depend on it), no list yet, a list whose reference a variable-cell
        // run left behind, or GEMM plans to tune first: the host-driven rebuild, then the pass.
        if (rebuild_neighbors(h) != 0) return -1;
        if (ensure_force_graph(h, stress) != 0) return -1;
        CUDA_CHECK(cudaGraphLaunch(h->force_graph_exec, h->stream));
    } else if (run_md_loop(h, kStepDevice, 1, 1.0, 0.0, 0.0, 0.0, (unsigned long long)stress, 0, false, nullptr) != 0) {
        return -1;
    }

    double inter_e = 0.0, v_grad[6] = {0, 0, 0, 0, 0, 0};
    if (want_e || want_v) {
        int flags[2] = {0, 0};
        auto fetch = [&]() -> int {
            CUDA_CHECK(cudaMemcpyAsync(&inter_e, h->d_energy_f64, sizeof(double), cudaMemcpyDeviceToHost, h->stream));
            if (want_v)
                CUDA_CHECK(cudaMemcpyAsync(v_grad, h->d_virial_grad_f64, 6 * sizeof(double), cudaMemcpyDeviceToHost, h->stream));
            CUDA_CHECK(cudaMemcpyAsync(&flags[0], h->d_io_bad, sizeof(int), cudaMemcpyDeviceToHost, h->stream));
            CUDA_CHECK(cudaMemcpyAsync(&flags[1], h->d_order_err, sizeof(int), cudaMemcpyDeviceToHost, h->stream));
            CUDA_CHECK(cudaStreamSynchronize(h->stream));
            return 0;
        };
        auto finite = [&] {
            bool ok = std::isfinite(inter_e);
            for (int i = 0; ok && i < 6; ++i) ok = std::isfinite(v_grad[i]);
            return ok;
        };
        if (fetch() != 0) return -1;
        if (flags[0] & 1) {
            loup::set_error("an atom id is outside 0 .. %d", N - 1);
            CUDA_CHECK(cudaMemsetAsync(h->d_io_bad, 0, sizeof(int), h->stream));  // a corrected call is accepted
            return -1;
        }
        if (flags[1]) return order_error();
        // As loup_evaluate: with the tensor-core GEMM cubin loaded, a non-finite result drops it and the pass is run
        // again (the positions are still in place; no force has been added to the caller's rows yet).
        if ((!finite() || (flags[0] & 2)) && drop_hybrid(h)) {
            CUDA_CHECK(cudaMemsetAsync(h->d_io_bad, 0, sizeof(int), h->stream));
            if (ensure_force_graph(h, stress) != 0) return -1;
            CUDA_CHECK(cudaGraphLaunch(h->force_graph_exec, h->stream));
            if (fetch() != 0) return -1;
        }
        if (!finite() || (flags[0] & 2)) {
            loup::set_error("non-finite energy, forces or stress (model output; the configuration may be unphysical)");
            return -1;
        }
    }

    if (sync_inv_perm() != 0) return -1;  // an atom reorder in this step's rebuild changed the permutation
    if (io->forces)
        io_scatter_kernel<<<grid, 256, 0, h->stream>>>(N, io->ids, h->d_inv_perm, h->d_forces_f64, io->forces,
                                                       io->f_row_stride, io->f_comp_stride, h->d_io_bad);
    CUDA_CHECK(cudaGetLastError());
    CUDA_CHECK(cudaEventRecord(h->ev_io_out, h->stream));
    CUDA_CHECK(cudaStreamWaitEvent(cs, h->ev_io_out, 0));

    if (want_e) *out_energy_ev = h->e0_total + inter_e;
    if (want_v) {
        // v_grad = dE/d(strain) as [xx, xy, xz, yy, yz, zz]; the virial is its negative, in the order xx yy zz xy xz yz.
        out_virial[0] = -v_grad[0];
        out_virial[1] = -v_grad[3];
        out_virial[2] = -v_grad[5];
        out_virial[3] = -v_grad[1];
        out_virial[4] = -v_grad[2];
        out_virial[5] = -v_grad[4];
    }
    return 0;
}

// Testing only: the noise CSVR draws in steps first_step .. first_step + n_steps - 1 for `ndof` degrees of freedom,
// as the captured step draws it.
static int csvr_noise_impl(LoupHandle* h, unsigned long long seed, unsigned long long first_step, int n_steps,
                           int ndof, double* out_normal, double* out_chi2) {
    if (!h) { loup::set_error("the handle is NULL"); return -1; }
    if (n_steps <= 0 || ndof <= 0 || !out_normal || !out_chi2) {
        loup::set_error("n_steps and ndof must be positive and both outputs given (n_steps = %d, ndof = %d)", n_steps,
                        ndof);
        return -1;
    }
    CUDA_CHECK(cudaSetDevice(h->device_id));
    double* d_out = nullptr;
    CUDA_CHECK(cudaMalloc(&d_out, (size_t)n_steps * 2 * sizeof(double)));
    loup::csvr_noise_debug_kernel<<<(n_steps + 255) / 256, 256>>>(seed, first_step, n_steps, ndof, d_out,
                                                                  d_out + n_steps);
    cudaError_t rc = cudaMemcpy(out_normal, d_out, (size_t)n_steps * sizeof(double), cudaMemcpyDeviceToHost);
    if (rc == cudaSuccess) {
        rc = cudaMemcpy(out_chi2, d_out + n_steps, (size_t)n_steps * sizeof(double), cudaMemcpyDeviceToHost);
    }
    cudaFree(d_out);
    CUDA_CHECK(rc);
    return 0;
}

// loup_minimize: LBFGS on the device, see src/minimize.cu for the algebra. Per step: one pass over the history
// for every product the host needs, the two triangular solves on the host, one pass for the direction, the move,
// the list check and the force pass. The host waits for the device once per step (for the products) and a second
// time only where the move may have outdated the neighbour list.
static int minimize_impl(LoupHandle* h, const LoupMinimizer* caller, int max_steps, LoupMinStats* out_stats) {
    if (!has_system(h)) return -1;
    if (!caller) { loup::set_error("the minimizer is NULL"); return -1; }
    if (caller->size != sizeof(LoupMinimizer)) {
        loup::set_error("LoupMinimizer.size is %u, and this library's layout has %zu bytes (set size to "
                        "sizeof(LoupMinimizer) of the header the library was built from)", caller->size,
                        sizeof(LoupMinimizer));
        return -1;
    }
    const LoupMinimizer m = *caller;
    if (m.kind != LOUP_MIN_LBFGS) { loup::set_error("unknown minimizer kind %d", m.kind); return -1; }
    if (!h->nl_valid) {
        loup::set_error("no positions or neighbour list (call loup_set_state or loup_evaluate first)");
        return -1;
    }
    if (max_steps < 0) { loup::set_error("max_steps must not be negative, got %d", max_steps); return -1; }
    if (!std::isfinite(m.fmax_ev_a) || !(m.fmax_ev_a > 0.0)) {
        loup::set_error("fmax_ev_a must be finite and positive, got %g eV/A", m.fmax_ev_a);
        return -1;
    }
    if (!std::isfinite(m.maxstep_a) || !(m.maxstep_a > 0.0) || !std::isfinite(m.damping) || !(m.damping > 0.0) ||
        !std::isfinite(m.alpha) || !(m.alpha > 0.0)) {
        loup::set_error("maxstep_a, damping and alpha must be finite and positive, got %g A, %g and %g", m.maxstep_a,
                        m.damping, m.alpha);
        return -1;
    }
    if (m.memory < 1 || m.memory > 1000) {
        loup::set_error("memory must be from 1 to 1000 history pairs, got %d", m.memory);
        return -1;
    }
    CUDA_CHECK(cudaSetDevice(h->device_id));
    const int N = h->N;
    const int n3 = 3 * N;
    const int gridN = (N + 255) / 256;
    const int mem = m.memory;
    MinState& st = h->min_state;
    // A new relaxation unless this call continues the last one: same settings, and nothing moved the atoms since.
    if (!st.valid || st.epoch != h->pos_epoch || st.n3 != n3 || st.memory != mem || st.maxstep != m.maxstep_a ||
        st.damping != m.damping || st.alpha != m.alpha) {
        if (st.n3 != n3 || st.memory != mem) {
            st.release();
            CUDA_CHECK(cudaMalloc(&st.d_S, (size_t)mem * n3 * sizeof(double)));
            CUDA_CHECK(cudaMalloc(&st.d_Y, (size_t)mem * n3 * sizeof(double)));
            CUDA_CHECK(cudaMalloc(&st.d_vec, (size_t)4 * n3 * sizeof(double)));
            CUDA_CHECK(cudaMalloc(&st.d_small, (size_t)7 * mem * sizeof(double)));
            CUDA_CHECK(cudaMalloc(&st.d_rows, (size_t)mem * sizeof(int)));
            CUDA_CHECK(cudaMalloc(&st.d_max, 3 * sizeof(unsigned long long)));
            CUDA_CHECK(cudaMallocHost((void**)&st.h_pin, ((size_t)4 + 7 * (size_t)mem) * sizeof(double)));
            CUDA_CHECK(cudaMallocHost((void**)&st.h_rows, (size_t)mem * sizeof(int)));
            st.n3 = n3;
            st.memory = mem;
        }
        st.maxstep = m.maxstep_a;
        st.damping = m.damping;
        st.alpha = m.alpha;
        st.count = 0;
        st.head = 0;
        st.iteration = 0;
        st.order.clear();
        st.rho.assign((size_t)mem, 0.0);
        st.gram.assign((size_t)mem * mem, 0.0);
        st.yy.assign((size_t)mem * mem, 0.0);
        st.disp_known = st.step_known = -1.0;
        st.valid = true;
    }
    st.epoch = h->pos_epoch;
    double* d_g = st.d_vec;
    double* d_g0 = st.d_vec + n3;
    double* d_x0 = st.d_vec + 2 * (size_t)n3;
    double* d_p = st.d_vec + 3 * (size_t)n3;
    double* d_prod = st.d_small;
    double* d_u = st.d_small + 5 * (size_t)mem;
    double* d_w = st.d_small + 6 * (size_t)mem;
    const double h0 = 1.0 / m.alpha;
    const double half_skin = 0.5 * h->skin;

    struct ReorderOff {  // the optimiser's vectors stay in the atom order of the call
        LoupHandle* h;
        explicit ReorderOff(LoupHandle* handle) : h(handle) { h->suppress_reorder = true; }
        ~ReorderOff() { h->suppress_reorder = false; }
    } reorder_off(h);
    // The optimiser's own time is measured between events on the stream: from the end of a force pass to the end of
    // the history products (ev_products), and from the host's solve to the end of the move (ev_step). Everything
    // else of the call is the force evaluation: force passes, list checks and rebuilds, graph captures.
    EventPairGuard ev_products, ev_step;
    double optimizer_ms = 0.0;
    int rebuilds = 0, passes = 0, repeated = 0;
    auto force_pass = [&]() -> int {
        if (ensure_force_graph(h, 0) != 0) return -1;
        CUDA_CHECK(cudaGraphLaunch(h->force_graph_exec, h->stream));
        ++passes;
        return 0;
    };
    auto add_elapsed = [&](const EventPairGuard& ev) -> int {
        float ms = 0.0f;
        CUDA_CHECK(cudaEventElapsedTime(&ms, ev.e0, ev.e1));
        optimizer_ms += (double)ms;
        return 0;
    };
    const auto t_start = std::chrono::steady_clock::now();
    if (h->cell_ref_stale && rebuild_neighbors(h) != 0) return -1;  // after a variable-cell run: see run_md_loop
    if (!h->forces_current || h->lt_cache.empty()) {
        if (force_pass() != 0) return -1;
    }

    double* pin = st.h_pin;                      // [0..2] d_max's values, [3] the energy
    double* prod = pin + 4;                      // five products per history row
    double* u = pin + 4 + 5 * (size_t)mem;       // u, then w: one upload
    double* w = u + mem;
    std::vector<double> a((size_t)mem), yz((size_t)mem);
    int taken = 0;
    bool converged = false;
    double fmax = 0.0, energy = 0.0;
    // The list check of a move, as an evaluation at new positions makes it: a rebuild once an atom is further than
    // half the skin from where the list was built. Where the displacement before the move plus twice the last
    // step's length stays inside that, the force pass is launched without waiting, and the displacement after the
    // move arrives with the next step's downloads (`unchecked`); should the list have been outdated after all,
    // that force pass is thrown away and run again with a new list. Otherwise (a call's first move of a new
    // relaxation, or a move that may cross the bound) the host waits for the measurement before the force pass.
    // LOUP_MIN_AHEAD=0|1 (testing) forces one of the two ways.
    const char* ahead_env = getenv("LOUP_MIN_AHEAD");
    const int ahead_forced = (ahead_env && *ahead_env) ? (atoi(ahead_env) != 0 ? 1 : 0) : -1;
    bool unchecked = false, step_timed = false;
    for (;;) {
        // The gradient and the largest force; from the second step on the newest pair goes into its row, and one
        // pass over the history gives every product with it and with the gradient.
        const bool have_previous = st.iteration > 0;
        const int row = st.head;
        const int n_rows = have_previous ? std::min(st.count + 1, mem) : 0;  // the history with the new pair
        CUDA_CHECK(cudaEventRecord(ev_products.e0, h->stream));
        CUDA_CHECK(cudaMemsetAsync(st.d_max, 0, sizeof(unsigned long long), h->stream));
        loup::min_gradient_kernel<<<gridN, 256, 0, h->stream>>>(
            N, have_previous ? 1 : 0, h->d_forces_f64, h->d_inv_masses, h->d_pos64, d_x0, d_g0, d_g,
            st.d_S + (size_t)row * n3, st.d_Y + (size_t)row * n3, st.d_max);
        if (have_previous) {
            CUDA_CHECK(cudaMemsetAsync(d_prod, 0, (size_t)5 * mem * sizeof(double), h->stream));
            const dim3 grid((unsigned)((n3 + 256 * 16 - 1) / (256 * 16)), (unsigned)n_rows);
            loup::lbfgs_products_kernel<<<grid, 256, 0, h->stream>>>(
                n3, n3, st.d_S, st.d_Y, d_g, st.d_S + (size_t)row * n3, st.d_Y + (size_t)row * n3, d_prod);
            CUDA_CHECK(cudaMemcpyAsync(prod, d_prod, (size_t)5 * n_rows * sizeof(double), cudaMemcpyDeviceToHost,
                                       h->stream));
        }
        CUDA_CHECK(cudaMemcpyAsync(pin, st.d_max, 3 * sizeof(double), cudaMemcpyDeviceToHost, h->stream));
        CUDA_CHECK(cudaMemcpyAsync(pin + 3, h->d_energy_f64, sizeof(double), cudaMemcpyDeviceToHost, h->stream));
        CUDA_CHECK(cudaEventRecord(ev_products.e1, h->stream));
        CUDA_CHECK(cudaStreamSynchronize(h->stream));
        if (add_elapsed(ev_products) != 0) return -1;
        if (step_timed) {
            if (add_elapsed(ev_step) != 0) return -1;
            step_timed = false;
        }
        if (taken > 0) st.step_known = m.damping * std::min(std::sqrt(pin[1]), m.maxstep_a);
        if (unchecked) {
            unchecked = false;
            if (pin[2] > half_skin * half_skin) {
                // The move outdated the list, so the force pass that followed it does not count: again, with a
                // new list.
                if (rebuild_neighbors(h) != 0) return -1;
                ++rebuilds;
                ++repeated;
                st.disp_known = 0.0;
                if (force_pass() != 0) return -1;
                continue;
            }
            st.disp_known = std::sqrt(pin[2]);
        }
        h->forces_current = true;
        const double inter_e = pin[3];
        if (!std::isfinite(inter_e)) {
            drop_hybrid(h);
            loup::set_error("non-finite potential energy during the relaxation: the step led to a configuration "
                            "the model cannot evaluate");
            return -1;
        }
        fmax = std::sqrt(pin[0]);
        energy = h->e0_total + inter_e;
        converged = fmax < m.fmax_ev_a;
        if (converged || taken >= max_steps) break;

        // The history gains the pair (ASE: from the second step on), the oldest one leaving once it is full.
        CUDA_CHECK(cudaEventRecord(ev_step.e0, h->stream));
        int n = 0;
        if (have_previous) {
            const double sy = prod[(size_t)5 * row + 2];  // s . y of the new pair
            if (!std::isfinite(sy) || sy == 0.0) {
                loup::set_error("the relaxation cannot go on: the last step changed neither positions nor forces "
                                "(s . y = %g)", sy);
                return -1;
            }
            if (st.count == mem) st.order.erase(st.order.begin());
            else ++st.count;
            st.order.push_back(row);
            st.head = (row + 1) % mem;
            st.rho[row] = 1.0 / sy;
            for (int j = 0; j < n_rows; ++j) {
                st.gram[(size_t)j * mem + row] = prod[(size_t)5 * j + 2];  // s_j . y_new
                st.gram[(size_t)row * mem + j] = prod[(size_t)5 * j + 3];  // s_new . y_j
                st.yy[(size_t)j * mem + row] = st.yy[(size_t)row * mem + j] = prod[(size_t)5 * j + 4];
            }
            n = st.count;
            // (I + R triu(G, 1)) a = R S g, newest to oldest; then Y z = H0 (Y g - (Y Y^T) a), and
            // (I + R tril(G^T, -1)) c = a - R Y z, oldest to newest. u = H0 a and w = -c weigh Y and S in p.
            for (int k = n - 1; k >= 0; --k) {
                const int i = st.order[k];
                double sum = prod[(size_t)5 * i + 0];
                for (int l = k + 1; l < n; ++l) sum -= st.gram[(size_t)i * mem + st.order[l]] * a[l];
                a[k] = st.rho[i] * sum;
            }
            for (int k = 0; k < n; ++k) {
                const int i = st.order[k];
                double sum = prod[(size_t)5 * i + 1];
                for (int l = 0; l < n; ++l) sum -= st.yy[(size_t)i * mem + st.order[l]] * a[l];
                yz[k] = h0 * sum;
            }
            for (int k = 0; k < n; ++k) {
                const int i = st.order[k];
                double sum = yz[k];
                for (int l = 0; l < k; ++l) sum -= st.gram[(size_t)st.order[l] * mem + i] * w[l];  // w = -c
                w[k] = -(a[k] - st.rho[i] * sum);
                u[k] = h0 * a[k];
                st.h_rows[k] = i;
            }
            // The host leaves u, w and the rows alone until the next wait, so the copies may run when they will.
            CUDA_CHECK(cudaMemcpyAsync(d_u, u, (size_t)(mem + n) * sizeof(double), cudaMemcpyHostToDevice,
                                       h->stream));
            CUDA_CHECK(cudaMemcpyAsync(st.d_rows, st.h_rows, (size_t)n * sizeof(int), cudaMemcpyHostToDevice,
                                       h->stream));
        }
        CUDA_CHECK(cudaMemsetAsync(st.d_max + 1, 0, 2 * sizeof(unsigned long long), h->stream));
        loup::lbfgs_direction_kernel<<<gridN, 256, 0, h->stream>>>(
            N, n, n3, h0, st.d_rows, d_u, d_w, st.d_S, st.d_Y, d_g, d_p, st.d_max + 1);
        loup::lbfgs_move_kernel<<<gridN, 256, 0, h->stream>>>(
            N, m.maxstep_a, m.damping, st.d_max + 1, d_p, d_g, h->d_pos64, d_x0, d_g0);
        CUDA_CHECK(cudaEventRecord(ev_step.e1, h->stream));
        step_timed = true;
        h->forces_current = false;
        ++st.iteration;
        ++taken;
        // The list at the new positions, then their forces.
        loup::max_displacement2_kernel<<<gridN, 256, 0, h->stream>>>(N, h->d_pos64, h->d_ref_pos64, st.d_max + 2);
        const bool ahead = half_skin > 0.0 &&
                           (ahead_forced >= 0 ? ahead_forced == 1
                                              : st.disp_known >= 0.0 && st.step_known >= 0.0 &&
                                                    st.disp_known + 2.0 * st.step_known < half_skin);
        if (ahead) {
            unchecked = true;
        } else {
            CUDA_CHECK(cudaMemcpyAsync(pin + 2, st.d_max + 2, sizeof(double), cudaMemcpyDeviceToHost, h->stream));
            CUDA_CHECK(cudaStreamSynchronize(h->stream));
            if (add_elapsed(ev_step) != 0) return -1;
            step_timed = false;
            if (!(half_skin > 0.0) || pin[2] > half_skin * half_skin) {
                if (rebuild_neighbors(h) != 0) return -1;
                ++rebuilds;
                st.disp_known = 0.0;
            } else {
                st.disp_known = std::sqrt(pin[2]);
            }
        }
        if (force_pass() != 0) return -1;
    }
    if (out_stats) {
        const double total_ms =
            std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t_start).count();
        out_stats->steps = taken;
        out_stats->converged = converged ? 1 : 0;
        out_stats->total_steps = (int)st.iteration;
        out_stats->rebuilds = rebuilds;
        out_stats->force_passes = passes;
        out_stats->repeated_passes = repeated;
        out_stats->max_force_ev_a = fmax;
        out_stats->potential_energy_ev = energy;
        out_stats->force_ms = std::max(0.0, total_ms - optimizer_ms);
        out_stats->optimizer_ms = optimizer_ms;
    }
    return 0;
}

// loup_set_cell: a new cell for the positions on the handle. With scale_atoms the atoms keep their fractional
// coordinates (x <- x old^-1 new, as ASE's set_cell(scale_atoms=True)). Velocities stay.
static int set_cell_impl(LoupHandle* h, const double* cell, int scale_atoms) {
    if (!has_system(h)) return -1;
    if (!h->nl_valid) {
        loup::set_error("no positions (call loup_set_state or loup_evaluate first)");
        return -1;
    }
    if (!cell) { loup::set_error("cell is NULL"); return -1; }
    if (!valid_input(0, cell, cell, nullptr)) return -1;
    CUDA_CHECK(cudaSetDevice(h->device_id));
    if (scale_atoms) {
        loup::Mat3 m;
        for (int r = 0; r < 3; ++r)
            for (int c = 0; c < 3; ++c)
                m.m[r * 3 + c] = h->cell.inv[r * 3 + 0] * cell[0 * 3 + c] + h->cell.inv[r * 3 + 1] * cell[1 * 3 + c] +
                                 h->cell.inv[r * 3 + 2] * cell[2 * 3 + c];
        loup::positions_times_matrix_kernel<<<(h->N + 255) / 256, 256, 0, h->stream>>>(h->N, m, h->d_pos64);
    }
    memcpy(h->cell_in, cell, sizeof(h->cell_in));
    loup::compute_cell_mat(cell, h->cell, h->cell_vol, h->cell_heights);
    if (h->gen && h->gen->set_cell(cell)) h->invalidate_graphs();
    if (dispersion_cell_changed(h) != 0) return -1;
    h->forces_current = false;
    ++h->pos_epoch;
    return rebuild_neighbors(h);
}

// loup_set_reference_volume: the V0 of the cell limits, for a run that goes on in another process.
static int set_reference_volume_impl(LoupHandle* h, double volume_a3) {
    if (!has_system(h)) return -1;
    if (!std::isfinite(volume_a3) || !(volume_a3 > 0.0)) {
        loup::set_error("the reference volume must be finite and positive, got %g A^3", volume_a3);
        return -1;
    }
    h->cell_v0 = volume_a3;
    if (h->var_cell && h->d_celldev) {  // only this field: the device's cell may be ahead of the list's reference
        CUDA_CHECK(cudaSetDevice(h->device_id));
        CUDA_CHECK(cudaStreamSynchronize(h->stream));
        CUDA_CHECK(cudaMemcpy(reinterpret_cast<char*>(h->d_celldev) + offsetof(loup::CellDev, v0), &volume_a3,
                              sizeof(double), cudaMemcpyHostToDevice));
    }
    return 0;
}

static int get_cell_impl(LoupHandle* h, double* out_cell) {
    if (!has_system(h)) return -1;
    if (!h->nl_valid) {
        loup::set_error("no positions (call loup_set_state or loup_evaluate first)");
        return -1;
    }
    if (!out_cell) { loup::set_error("out_cell is NULL"); return -1; }
    memcpy(out_cell, h->cell_in, sizeof(h->cell_in));
    return 0;
}

static int step_displacement_impl(LoupHandle* h, double* out_max_a) {
    if (!has_system(h)) return -1;
    if (!out_max_a) { loup::set_error("out_max_a is NULL"); return -1; }
    CUDA_CHECK(cudaSetDevice(h->device_id));
    unsigned int bits[2] = {0u, 0u};
    CUDA_CHECK(cudaStreamSynchronize(h->stream));
    CUDA_CHECK(cudaMemcpy(bits, h->d_max_step_disp2, sizeof(bits), cudaMemcpyDeviceToHost));
    const unsigned int larger = bits[0] > bits[1] ? bits[0] : bits[1];
    float d2 = 0.0f;
    memcpy(&d2, &larger, sizeof(d2));
    *out_max_a = std::sqrt((double)d2);
    return 0;
}

// loup_run: every integrator enters here; loup_run_nve and loup_run_langevin fill the struct and call it.
static const char* integrator_name(int kind) {
    switch (kind) {
        case LOUP_NVE: return "LOUP_NVE";
        case LOUP_LANGEVIN: return "LOUP_LANGEVIN";
        case LOUP_CSVR: return "LOUP_CSVR";
        case LOUP_NHC: return "LOUP_NHC";
        case LOUP_BERENDSEN_NVT: return "LOUP_BERENDSEN_NVT";
        case LOUP_BERENDSEN_NPT: return "LOUP_BERENDSEN_NPT";
        case LOUP_BAOAB_NPT: return "LOUP_BAOAB_NPT";
        case LOUP_MTK_NPT: return "LOUP_MTK_NPT";
        default: return nullptr;
    }
}

// One integrator call's settings as run_md_loop takes them: loup_run and loup_tiled_run (LT6 (a)) share their
// validation (integrator_settings).
struct RunSpec {
    int kind = 0;
    double dt_fs = 0.0, temp_k = 0.0, temp_rate = 0.0, friction = 0.0;
    unsigned long long seed = 0;
    int thermo_every = 0;
    bool fix_com = false;
    double tau_fs = 0.0;
    int tchain = 0, tloop = 1;
    double mass_temp_k = 0.0;
    bool has_npt = false;
    NptParams npt;
};
// Fills *out with run_md_loop's arguments (in its order, without the handle, step count and stats) and returns 0.
static int spec(RunSpec* out, int kind, double dt_fs, double temp_k, double temp_rate, double friction,
                unsigned long long seed, int thermo_every, bool fix_com, double tau_fs = 0.0, int tchain = 0,
                int tloop = 1, double mass_temp_k = 0.0, const NptParams* npt = nullptr) {
    RunSpec s;
    s.kind = kind; s.dt_fs = dt_fs; s.temp_k = temp_k; s.temp_rate = temp_rate; s.friction = friction;
    s.seed = seed; s.thermo_every = thermo_every; s.fix_com = fix_com; s.tau_fs = tau_fs; s.tchain = tchain;
    s.tloop = tloop; s.mass_temp_k = mass_temp_k;
    if (npt) { s.has_npt = true; s.npt = *npt; }
    *out = s;
    return 0;
}
// The checks of every integrator's settings; n_fixed: the system's fixed atoms; has_lr: a long-range model.
static int integrator_settings(const LoupIntegrator& it, int n_steps, int n_fixed, bool has_lr, RunSpec* out);

static int run_impl(LoupHandle* h, const LoupIntegrator* caller, int n_steps, LoupMDStats* out_stats) {
    if (!caller) { loup::set_error("the integrator is NULL"); return -1; }
    // Size-versioned: this is the first released layout, so nothing smaller exists, and a larger struct comes from
    // a header this library does not know.
    if (caller->size != sizeof(LoupIntegrator)) {
        loup::set_error("LoupIntegrator.size is %u, and this library's layout has %zu bytes (set size to "
                        "sizeof(LoupIntegrator) of the header the library was built from)", caller->size,
                        sizeof(LoupIntegrator));
        return -1;
    }
    const LoupIntegrator it = *caller;
    const char* name = integrator_name(it.kind);
    if (!name) { loup::set_error("unknown integrator kind %d", it.kind); return -1; }
    (void)name;  // every kind of the enum is built
    if (it.fix_com != 0 && h && h->n_fixed > 0) {
        loup::set_error("fix_com with fixed atoms: %d fixed atoms pin the frame already", h->n_fixed);
        return -1;
    }
    // The variable-cell step. No integrator of this version moves the cell, so it runs for tests only:
    // LOUP_VARIABLE_CELL=1 sends this call through it, and LOUP_DEBUG_CELL_RATE scales the cell and the positions
    // by 1 + rate in every step.
    if (h) {
        h->req_var_cell = false;
        h->req_cell_rate = 0.0;
        if (const char* e = std::getenv("LOUP_VARIABLE_CELL"); e && e[0] == '1') {
            if (h->gen && h->gen->has_lr()) {
                loup::set_error("the variable cell is not built for long-range models (MACE-POLAR-1): their k-space "
                                "terms are set up for one cell");
                return -1;
            }
            h->req_var_cell = true;
            if (const char* r = std::getenv("LOUP_DEBUG_CELL_RATE")) {
                const double rate = atof(r);
                if (!std::isfinite(rate) || std::fabs(rate) > 0.1) {
                    loup::set_error("LOUP_DEBUG_CELL_RATE must be within -0.1 to 0.1 per step, got %s", r);
                    return -1;
                }
                h->req_cell_rate = rate;
            }
        }
    }
    RunSpec s;
    if (integrator_settings(it, n_steps, h ? h->n_fixed : 0, h && h->gen && h->gen->has_lr(), &s) != 0) return -1;
    if (s.has_npt && h) h->req_var_cell = true;
    return run_md_loop(h, s.kind, n_steps, s.dt_fs, s.temp_k, s.temp_rate, s.friction, s.seed, s.thermo_every,
                       s.fix_com, out_stats, s.tau_fs, s.tchain, s.tloop, s.mass_temp_k, s.has_npt ? &s.npt : nullptr);
}

static int integrator_settings(const LoupIntegrator& it, int n_steps, int n_fixed, bool has_lr, RunSpec* out) {
    if (it.kind == LOUP_NVE) {
        return spec(out, 0, it.dt_fs, 0.0, 0.0, 0.0, 0, it.thermo_every, it.fix_com != 0);
    }
    if (!std::isfinite(it.temp_k) || it.temp_k < 0.0) {
        loup::set_error("temp_k must be finite and not negative, got %g K", it.temp_k);
        return -1;
    }
    if (it.kind == LOUP_LANGEVIN && (!std::isfinite(it.friction_per_fs) || it.friction_per_fs < 0.0)) {
        loup::set_error("friction_per_fs must be finite and not negative, got %g /fs", it.friction_per_fs);
        return -1;
    }
    if (it.kind == LOUP_BAOAB_NPT) {
        // ASE's LangevinBAOAB with a barostat: T_tau = 1 / friction_per_fs, P_tau = tau_p_fs (0: 20 T_tau), the
        // external stress minus pressure_gpa, hydrostatic or the full cell.
        if (!std::isfinite(it.friction_per_fs) || !(it.friction_per_fs > 0.0)) {
            loup::set_error("friction_per_fs must be finite and positive for LOUP_BAOAB_NPT (1 / T_tau), got %g /fs",
                            it.friction_per_fs);
            return -1;
        }
        if (!std::isfinite(it.tau_p_fs) || it.tau_p_fs < 0.0) {
            loup::set_error("tau_p_fs must be finite and not negative (0 takes 20 / friction_per_fs), got %g fs",
                            it.tau_p_fs);
            return -1;
        }
        if (!std::isfinite(it.pressure_gpa)) {
            loup::set_error("pressure_gpa must be finite, got %g GPa", it.pressure_gpa);
            return -1;
        }
        if (it.cell_mode != LOUP_CELL_HYDROSTATIC && it.cell_mode != LOUP_CELL_FULL) {
            loup::set_error("unknown cell_mode %d (LOUP_CELL_HYDROSTATIC or LOUP_CELL_FULL)", it.cell_mode);
            return -1;
        }
        if (it.fix_com != 0) {
            loup::set_error("fix_com is not part of LOUP_BAOAB_NPT: ASE's LangevinBAOAB leaves the centre of mass "
                            "to its thermostat");
            return -1;
        }
        if (!std::isfinite(it.temp_rate_k_per_step) ||
            it.temp_k + it.temp_rate_k_per_step * (double)n_steps < 0.0) {
            loup::set_error("temp_rate_k_per_step must be finite and must not take the target below 0 K: %g K + %d "
                            "steps of %g K", it.temp_k, n_steps, it.temp_rate_k_per_step);
            return -1;
        }
        if (n_fixed > 0) {
            loup::set_error("a barostat with fixed atoms: the cell's scaling would move the %d fixed atoms", n_fixed);
            return -1;
        }
        if (has_lr) {
            loup::set_error("the variable cell is not built for long-range models (MACE-POLAR-1): their k-space "
                            "terms are set up for one cell");
            return -1;
        }
        NptParams npt;
        npt.pressure = it.pressure_gpa / loup::GPA_PER_EV_A3;
        npt.tau_p_fs = it.tau_p_fs;
        npt.full = it.cell_mode == LOUP_CELL_FULL ? 1 : 0;
        return spec(out, 6, it.dt_fs, it.temp_k, it.temp_rate_k_per_step, it.friction_per_fs, it.seed,
                    it.thermo_every, false, 0.0, 0, 1, 0.0, &npt);
    }
    if ((it.kind == LOUP_CSVR || it.kind == LOUP_NHC || it.kind == LOUP_BERENDSEN_NVT ||
         it.kind == LOUP_BERENDSEN_NPT || it.kind == LOUP_MTK_NPT) &&
        (!std::isfinite(it.tau_t_fs) || !(it.tau_t_fs > 0.0))) {
        loup::set_error("tau_t_fs must be finite and positive, got %g fs", it.tau_t_fs);
        return -1;
    }
    if (!std::isfinite(it.temp_rate_k_per_step) || it.temp_k + it.temp_rate_k_per_step * (double)n_steps < 0.0) {
        loup::set_error("temp_rate_k_per_step must be finite and must not take the target below 0 K: %g K + %d steps "
                        "of %g K", it.temp_k, n_steps, it.temp_rate_k_per_step);
        return -1;
    }
    if (it.kind == LOUP_CSVR) {
        return spec(out, 2, it.dt_fs, it.temp_k, it.temp_rate_k_per_step, 0.0, it.seed,
                    it.thermo_every, it.fix_com != 0, it.tau_t_fs);
    }
    if (it.kind == LOUP_MTK_NPT) {
        // ASE's IsotropicMTKNPT (LOUP_CELL_HYDROSTATIC) and MTKNPT (LOUP_CELL_FULL): tdamp = tau_t_fs, pdamp =
        // tau_p_fs, tchain / tloop = chain_length / chain_loops, pchain / ploop = p_chain_length / p_chain_loops
        // (0: ASE's 3 and 1).
        if (!std::isfinite(it.tau_p_fs) || !(it.tau_p_fs > 0.0)) {
            loup::set_error("tau_p_fs must be finite and positive, got %g fs", it.tau_p_fs);
            return -1;
        }
        if (!std::isfinite(it.pressure_gpa)) {
            loup::set_error("pressure_gpa must be finite, got %g GPa", it.pressure_gpa);
            return -1;
        }
        const int tchain = it.chain_length == 0 ? 3 : it.chain_length;
        const int pchain = it.p_chain_length == 0 ? 3 : it.p_chain_length;
        if (tchain < 1 || tchain > 8) {
            loup::set_error("chain_length must be from 1 to 8 thermostats for LOUP_MTK_NPT, got %d", it.chain_length);
            return -1;
        }
        if (pchain < 1 || pchain > 8) {
            loup::set_error("p_chain_length must be from 1 to 8 barostat links, got %d", it.p_chain_length);
            return -1;
        }
        if (it.chain_loops < 0 || it.chain_loops > 100 || it.p_chain_loops < 0 || it.p_chain_loops > 100) {
            loup::set_error("%s must be from 0 to 100 (0 is 1), got %d",
                            it.chain_loops < 0 || it.chain_loops > 100 ? "chain_loops" : "p_chain_loops",
                            it.chain_loops < 0 || it.chain_loops > 100 ? it.chain_loops : it.p_chain_loops);
            return -1;
        }
        if (it.cell_mode != LOUP_CELL_HYDROSTATIC && it.cell_mode != LOUP_CELL_FULL) {
            loup::set_error("unknown cell_mode %d (LOUP_CELL_HYDROSTATIC or LOUP_CELL_FULL)", it.cell_mode);
            return -1;
        }
        const double mass_temp = it.mass_temp_k == 0.0 ? it.temp_k : it.mass_temp_k;
        if (!std::isfinite(mass_temp) || !(mass_temp > 0.0) || !(it.temp_k > 0.0)) {
            loup::set_error("temp_k must be positive for LOUP_MTK_NPT (the thermostat's and the barostat's masses "
                            "are made for it), got %g K with mass_temp_k = %g K", it.temp_k, it.mass_temp_k);
            return -1;
        }
        if (n_fixed > 0) {
            loup::set_error("a barostat with fixed atoms: the cell's scaling would move the %d fixed atoms", n_fixed);
            return -1;
        }
        if (has_lr) {
            loup::set_error("the variable cell is not built for long-range models (MACE-POLAR-1): their k-space "
                            "terms are set up for one cell");
            return -1;
        }
        NptParams npt;
        npt.pressure = it.pressure_gpa / loup::GPA_PER_EV_A3;
        npt.tau_p_fs = it.tau_p_fs;
        npt.full = it.cell_mode == LOUP_CELL_FULL ? 1 : 0;
        npt.pchain = pchain;
        npt.ploop = it.p_chain_loops == 0 ? 1 : it.p_chain_loops;
        return spec(out, 7, it.dt_fs, it.temp_k, it.temp_rate_k_per_step, 0.0, 0, it.thermo_every,
                    it.fix_com != 0, it.tau_t_fs, tchain, it.chain_loops == 0 ? 1 : it.chain_loops, mass_temp, &npt);
    }
    if (it.kind == LOUP_BERENDSEN_NVT || it.kind == LOUP_BERENDSEN_NPT) {
        if (it.tau_t_fs < it.dt_fs) {  // sqrt(1 + (T0 / T - 1) dt / taut) needs dt / taut <= 1
            loup::set_error("tau_t_fs must be at least the timestep for the Berendsen thermostat: %g fs against "
                            "dt_fs = %g fs", it.tau_t_fs, it.dt_fs);
            return -1;
        }
        if (it.kind == LOUP_BERENDSEN_NVT) {
            return spec(out, 4, it.dt_fs, it.temp_k, it.temp_rate_k_per_step, 0.0, 0,
                        it.thermo_every, it.fix_com != 0, it.tau_t_fs);
        }
        // The barostat (ASE's NPTBerendsen; with LOUP_CELL_FULL its Inhomogeneous_NPTBerendsen and the mask).
        if (!std::isfinite(it.tau_p_fs) || !(it.tau_p_fs > 0.0)) {
            loup::set_error("tau_p_fs must be finite and positive, got %g fs", it.tau_p_fs);
            return -1;
        }
        if (!std::isfinite(it.pressure_gpa)) {
            loup::set_error("pressure_gpa must be finite, got %g GPa", it.pressure_gpa);
            return -1;
        }
        if (!std::isfinite(it.compressibility_per_gpa) || !(it.compressibility_per_gpa > 0.0)) {
            loup::set_error("compressibility_per_gpa must be finite and positive, got %g per GPa",
                            it.compressibility_per_gpa);
            return -1;
        }
        if (it.cell_mode != LOUP_CELL_HYDROSTATIC && it.cell_mode != LOUP_CELL_FULL) {
            loup::set_error("unknown cell_mode %d (LOUP_CELL_HYDROSTATIC or LOUP_CELL_FULL)", it.cell_mode);
            return -1;
        }
        NptParams npt;
        npt.pressure = it.pressure_gpa / loup::GPA_PER_EV_A3;
        npt.tau_p_fs = it.tau_p_fs;
        npt.compressibility = it.compressibility_per_gpa * loup::GPA_PER_EV_A3;
        npt.full = it.cell_mode == LOUP_CELL_FULL ? 1 : 0;
        if (npt.full) {
            int freed = 0;
            for (int a = 0; a < 3; ++a) {
                if (it.cell_mask[a] != 0 && it.cell_mask[a] != 1) {
                    loup::set_error("cell_mask entries must be 0 or 1, got (%d, %d, %d)", it.cell_mask[0],
                                    it.cell_mask[1], it.cell_mask[2]);
                    return -1;
                }
                npt.mask[a] = it.cell_mask[a];
                freed += it.cell_mask[a];
            }
            if (freed == 0) {
                loup::set_error("cell_mask frees no axis: (0, 0, 0) is a run at fixed cell (LOUP_BERENDSEN_NVT)");
                return -1;
            }
        }
        if (n_fixed > 0) {
            loup::set_error("a barostat with fixed atoms: the cell's scaling would move the %d fixed atoms", n_fixed);
            return -1;
        }
        if (has_lr) {
            loup::set_error("the variable cell is not built for long-range models (MACE-POLAR-1): their k-space "
                            "terms are set up for one cell");
            return -1;
        }
        return spec(out, 5, it.dt_fs, it.temp_k, it.temp_rate_k_per_step, 0.0, 0, it.thermo_every,
                    it.fix_com != 0, it.tau_t_fs, 0, 1, 0.0, &npt);
    }
    if (it.kind == LOUP_NHC) {
        if (it.chain_length < 1 || it.chain_length > 16) {
            loup::set_error("chain_length must be from 1 to 16 thermostats, got %d", it.chain_length);
            return -1;
        }
        if (it.chain_loops < 0 || it.chain_loops > 100) {
            loup::set_error("chain_loops must be from 0 (one) to 100 sub-steps, got %d", it.chain_loops);
            return -1;
        }
        const double mass_temp = it.mass_temp_k != 0.0 ? it.mass_temp_k : it.temp_k;
        if (!std::isfinite(mass_temp) || !(mass_temp > 0.0)) {
            loup::set_error("the thermostat masses of the Nose-Hoover chain need a temperature above 0 K: "
                            "mass_temp_k is %g K and temp_k %g K", it.mass_temp_k, it.temp_k);
            return -1;
        }
        return spec(out, 3, it.dt_fs, it.temp_k, it.temp_rate_k_per_step, 0.0, 0, it.thermo_every,
                    it.fix_com != 0, it.tau_t_fs, it.chain_length, it.chain_loops > 0 ? it.chain_loops : 1, mass_temp);
    }
    return spec(out, 1, it.dt_fs, it.temp_k, it.temp_rate_k_per_step, it.friction_per_fs, it.seed,
                it.thermo_every, it.fix_com != 0);
}

static int run_nve_impl(LoupHandle* h, int n_steps, double dt_fs, LoupMDStats* out_stats) {
    LoupIntegrator it{};
    it.size = sizeof(it);
    it.kind = LOUP_NVE;
    it.dt_fs = dt_fs;
    return run_impl(h, &it, n_steps, out_stats);
}

static int run_langevin_impl(
    LoupHandle* h, int n_steps, double dt_fs, double temp_k,
    double friction_per_fs, unsigned long long seed, LoupMDStats* out_stats
) {
    LoupIntegrator it{};
    it.size = sizeof(it);
    it.kind = LOUP_LANGEVIN;
    it.dt_fs = dt_fs;
    it.temp_k = temp_k;
    it.friction_per_fs = friction_per_fs;
    it.seed = seed;
    return run_impl(h, &it, n_steps, out_stats);
}

static int get_state_impl(LoupHandle* h, double* out_positions, double* out_velocities, double* out_forces, double* out_energy_ev) {
    if (!has_system(h)) return -1;
    CUDA_CHECK(cudaSetDevice(h->device_id));
    std::vector<double> tmp((size_t)h->N * 3);
    if (out_positions) {
        CUDA_CHECK(cudaMemcpyAsync(tmp.data(), h->d_pos64, (size_t)h->N * 3 * sizeof(double), cudaMemcpyDeviceToHost, h->stream));
        CUDA_CHECK(cudaStreamSynchronize(h->stream));
        for (int dst = 0; dst < h->N; ++dst) {
            int orig = h->perm[dst];
            out_positions[orig * 3 + 0] = tmp[dst * 3 + 0];
            out_positions[orig * 3 + 1] = tmp[dst * 3 + 1];
            out_positions[orig * 3 + 2] = tmp[dst * 3 + 2];
        }
    }
    if (out_velocities) {
        CUDA_CHECK(cudaMemcpyAsync(tmp.data(), h->d_vel64, (size_t)h->N * 3 * sizeof(double), cudaMemcpyDeviceToHost, h->stream));
        CUDA_CHECK(cudaStreamSynchronize(h->stream));
        for (int dst = 0; dst < h->N; ++dst) {
            int orig = h->perm[dst];
            out_velocities[orig * 3 + 0] = tmp[dst * 3 + 0];
            out_velocities[orig * 3 + 1] = tmp[dst * 3 + 1];
            out_velocities[orig * 3 + 2] = tmp[dst * 3 + 2];
        }
    }
    if (out_forces) {
        CUDA_CHECK(cudaMemcpyAsync(tmp.data(), h->d_forces_f64, (size_t)h->N * 3 * sizeof(double), cudaMemcpyDeviceToHost, h->stream));
        CUDA_CHECK(cudaStreamSynchronize(h->stream));
        for (int dst = 0; dst < h->N; ++dst) {
            int orig = h->perm[dst];
            out_forces[orig * 3 + 0] = tmp[dst * 3 + 0];
            out_forces[orig * 3 + 1] = tmp[dst * 3 + 1];
            out_forces[orig * 3 + 2] = tmp[dst * 3 + 2];
        }
    }
    if (out_energy_ev) {
        double inter_e = 0.0;
        CUDA_CHECK(cudaMemcpyAsync(&inter_e, h->d_energy_f64, sizeof(double), cudaMemcpyDeviceToHost, h->stream));
        CUDA_CHECK(cudaStreamSynchronize(h->stream));
        *out_energy_ev = h->e0_total + inter_e;
    }
    return 0;
}

// The state blob (loup_export_state / loup_import_state): what a restart needs beyond the system itself, in the
// caller's atom order: positions, velocities, the step counter (the offset of the noise streams) and the
// integrator's scalars (kIntStateSlots: CSVR's transferred energy) with the kind they belong to. Forces and the
// neighbour list are not stored: import rebuilds the list, and the next run starts with a force pass.
//   StateHeader | positions [N, 3] f64 | velocities [N, 3] f64 | FNV-1a of everything before, u64
struct StateHeader {
    char magic[8];            // "LOUPSTA1"
    uint32_t version;         // 1
    uint32_t header_bytes;    // sizeof(StateHeader)
    uint64_t n_atoms;
    uint64_t species_hash;    // atomic numbers in caller order: a blob only fits the system it was written for
    uint64_t step_counter;
    uint32_t max_step_disp2[2];  // the displacement tracker: current and previous window (float bits)
    double cell[9];
    int32_t integrator_kind;     // the LOUP_* kind whose scalars follow; -1: none
    uint32_t reserved;
    double integrator_state[kIntStateSlots];
};
static_assert(sizeof(StateHeader) == 128 + 8 * kIntStateSlots, "StateHeader has padding");
static const char kStateMagic[8] = {'L', 'O', 'U', 'P', 'S', 'T', 'A', '1'};
static size_t state_blob_bytes(int n_atoms) {
    return sizeof(StateHeader) + (size_t)n_atoms * 6 * sizeof(double) + sizeof(uint64_t);
}

static int export_state_impl(LoupHandle* h, void* buffer, size_t capacity, size_t* written) {
    if (!has_system(h)) return -1;
    if (!h->nl_valid) {
        loup::set_error("no positions to export (call loup_set_state or loup_evaluate first)");
        return -1;
    }
    const size_t need = state_blob_bytes(h->N);
    if (written) *written = need;
    if (!buffer && capacity == 0) return 0;  // size query
    if (!buffer || capacity < need) {
        loup::set_error("the buffer holds %zu bytes, and the state of %d atoms needs %zu", buffer ? capacity : (size_t)0,
                        h->N, need);
        return -1;
    }
    CUDA_CHECK(cudaSetDevice(h->device_id));
    const size_t n3 = (size_t)h->N * 3;
    std::vector<double> p_sorted(n3), v_sorted(n3);
    StateHeader hd{};
    memcpy(hd.magic, kStateMagic, 8);
    hd.version = 1;
    hd.header_bytes = sizeof(StateHeader);
    hd.n_atoms = (uint64_t)h->N;
    hd.species_hash = h->species_hash;
    memcpy(hd.cell, h->cell_in, sizeof(hd.cell));
    CUDA_CHECK(cudaMemcpyAsync(p_sorted.data(), h->d_pos64, n3 * sizeof(double), cudaMemcpyDeviceToHost, h->stream));
    CUDA_CHECK(cudaMemcpyAsync(v_sorted.data(), h->d_vel64, n3 * sizeof(double), cudaMemcpyDeviceToHost, h->stream));
    CUDA_CHECK(cudaMemcpyAsync(&hd.step_counter, h->d_step_counter, sizeof(hd.step_counter), cudaMemcpyDeviceToHost, h->stream));
    CUDA_CHECK(cudaMemcpyAsync(hd.max_step_disp2, h->d_max_step_disp2, sizeof(hd.max_step_disp2), cudaMemcpyDeviceToHost, h->stream));
    hd.integrator_kind = h->int_state_kind;
    CUDA_CHECK(cudaMemcpyAsync(hd.integrator_state, h->d_int_state, sizeof(hd.integrator_state), cudaMemcpyDeviceToHost, h->stream));
    CUDA_CHECK(cudaStreamSynchronize(h->stream));
    std::vector<double> body(2 * n3);
    for (int dst = 0; dst < h->N; ++dst) {
        const size_t orig = (size_t)h->perm[dst];
        for (int k = 0; k < 3; ++k) {
            body[orig * 3 + k] = p_sorted[(size_t)dst * 3 + k];
            body[n3 + orig * 3 + k] = v_sorted[(size_t)dst * 3 + k];
        }
    }
    unsigned char* out = static_cast<unsigned char*>(buffer);
    memcpy(out, &hd, sizeof(hd));
    memcpy(out + sizeof(hd), body.data(), body.size() * sizeof(double));
    const uint64_t sum = fnv1a64(out, need - sizeof(uint64_t));
    memcpy(out + need - sizeof(uint64_t), &sum, sizeof(sum));
    return 0;
}

static int import_state_impl(LoupHandle* h, const void* buffer, size_t size) {
    if (!has_system(h)) return -1;
    if (!buffer) { loup::set_error("the buffer is NULL"); return -1; }
    StateHeader hd;
    if (size < sizeof(hd)) {
        loup::set_error("the state blob has %zu bytes, fewer than its header (%zu)", size, sizeof(hd));
        return -1;
    }
    const unsigned char* in = static_cast<const unsigned char*>(buffer);
    memcpy(&hd, in, sizeof(hd));
    if (memcmp(hd.magic, kStateMagic, 8) != 0) { loup::set_error("not a LoupMD state blob"); return -1; }
    if (hd.version != 1) {
        loup::set_error("the state blob has version %u, and this library reads version 1", hd.version);
        return -1;
    }
    if (hd.header_bytes != sizeof(StateHeader)) {
        loup::set_error("the state blob's header has %u bytes, and this library's has %zu (written by another "
                        "build of the library)", hd.header_bytes, sizeof(StateHeader));
        return -1;
    }
    if (hd.n_atoms != (uint64_t)h->N) {
        loup::set_error("the state blob holds %llu atoms, and the handle's system has %d",
                        (unsigned long long)hd.n_atoms, h->N);
        return -1;
    }
    const size_t need = state_blob_bytes(h->N);
    if (size != need) {
        loup::set_error("the state blob has %zu bytes, and %zu are expected for %d atoms (truncated or padded)", size,
                        need, h->N);
        return -1;
    }
    uint64_t sum = 0;
    memcpy(&sum, in + need - sizeof(sum), sizeof(sum));
    if (sum != fnv1a64(in, need - sizeof(sum))) {
        loup::set_error("the state blob is damaged (its checksum does not match)");
        return -1;
    }
    if (hd.species_hash != h->species_hash) {
        loup::set_error("the state blob was written for other atomic numbers or another atom order");
        return -1;
    }
    const size_t n3 = (size_t)h->N * 3;
    std::vector<double> body(2 * n3);  // the caller's buffer need not be aligned
    memcpy(body.data(), in + sizeof(hd), body.size() * sizeof(double));
    const double* positions = body.data();
    const double* velocities = body.data() + n3;
    CUDA_CHECK(cudaSetDevice(h->device_id));
    if (!valid_input(h->N, positions, hd.cell, velocities)) return -1;
    if (upload_positions(h, positions, hd.cell) < 0) return -1;
    if (!(h->cell_v0 > 0.0)) h->cell_v0 = h->cell_vol;  // a handle's first state (loup_set_reference_volume: a resumed run's)
    std::vector<double> v_sorted(n3);
    for (int dst = 0; dst < h->N; ++dst) {
        const size_t src = (size_t)h->perm[dst];
        for (int k = 0; k < 3; ++k) v_sorted[(size_t)dst * 3 + k] = h->fixed_caller[src] ? 0.0 : velocities[src * 3 + k];
    }
    CUDA_CHECK(cudaMemcpyAsync(h->d_vel64, v_sorted.data(), n3 * sizeof(double), cudaMemcpyHostToDevice, h->stream));
    if (rebuild_neighbors(h) != 0) return -1;
    CUDA_CHECK(cudaMemcpyAsync(h->d_step_counter, &hd.step_counter, sizeof(hd.step_counter), cudaMemcpyHostToDevice, h->stream));
    CUDA_CHECK(cudaMemcpyAsync(h->d_max_step_disp2, hd.max_step_disp2, sizeof(hd.max_step_disp2), cudaMemcpyHostToDevice, h->stream));
    CUDA_CHECK(cudaMemcpyAsync(h->d_int_state, hd.integrator_state, sizeof(hd.integrator_state), cudaMemcpyHostToDevice, h->stream));
    h->int_state_kind = hd.integrator_kind;
    h->disp_window_steps = 0;
    h->md_steps = 0;
    h->thermo_pending = 0;
    CUDA_CHECK(cudaStreamSynchronize(h->stream));
    return 0;
}

// ---- Open domains (plan task S1-T09), testing only ----
// A domain whose ghosts are images of its own local atoms needs no other domain to supply its ghost rows: after a
// sweep the ghosts' rows are copied from the locals they are images of, and what a sweep adds to ghost rows (the
// gradient of a layer's output, forces) is folded back onto those locals. With the periodic images of a cell as
// ghosts this must reproduce the periodic call.
extern "C++" {  // kernels, one of them a template: not inside this file's C linkage block
__global__ void ghost_copy_rows_kernel(int n_local, int n_ghost, int width, const int* __restrict__ ghost_of,
                                       float* rows) {
    const int64_t k = (int64_t)blockIdx.x * blockDim.x + threadIdx.x;
    if (k >= (int64_t)n_ghost * width) return;
    const int g = (int)(k / width), c = (int)(k % width);
    rows[(int64_t)(n_local + g) * width + c] = rows[(int64_t)ghost_of[g] * width + c];
}

template <typename T>
__global__ void ghost_fold_rows_kernel(int n_local, int n_ghost, int width, const int* __restrict__ ghost_of, T* rows) {
    const int64_t k = (int64_t)blockIdx.x * blockDim.x + threadIdx.x;
    if (k >= (int64_t)n_ghost * width) return;
    const int g = (int)(k / width), c = (int)(k % width);
    atomicAdd(&rows[(int64_t)ghost_of[g] * width + c], rows[(int64_t)(n_local + g) * width + c]);
}
}  // extern "C++"

static int set_domain_impl(LoupHandle* h, int n_local, int n_ghost, const int* atomic_numbers, double skin) {
    if (n_local <= 0 || n_ghost < 0) {
        loup::set_error("n_local must be positive and n_ghost not negative, got %d and %d", n_local, n_ghost);
        return -1;
    }
    if (!(h->gen && h->gen->sweeps_possible())) {
        loup::set_error("an open domain needs a bundle of the generic path without long range");
        return -1;
    }
    return set_system_impl(h, n_local + n_ghost, atomic_numbers, nullptr, skin, n_ghost, true);
}

static int evaluate_domain_impl(LoupHandle* h, const double* positions, const double* cell, const int* ghost_of,
                                double* out_energy_ev, double* out_forces, double* out_stress) {
    if (!h || h->N <= 0) { loup::set_error("no domain is set (call loup_debug_set_domain first)"); return -1; }
    if (h->disp) { loup::set_error("the dispersion term has no open domains (PLAN.md S6-D09)"); return -1; }
    if (!(h->gen && h->gen->sweeps_available())) {
        loup::set_error("the handle's model has no sweeps (generic path without long range and chain fold)");
        return -1;
    }
    const int N = h->N, G = h->n_ghost;
    if (G > 0 && !ghost_of) { loup::set_error("ghost_of is NULL"); return -1; }
    CUDA_CHECK(cudaSetDevice(h->device_id));
    if (upload_positions(h, positions, cell) < 0) return -1;
    if (rebuild_neighbors(h) != 0) return -1;
    h->invalidate_graphs();  // nothing below is captured, and no graph of another call may outlive this state

    // ghost_of names locals in the caller's order; the device rows of the locals are grouped by species
    std::vector<int> row_of(N);
    for (int dst = 0; dst < N; ++dst) row_of[h->perm[dst]] = dst;
    std::vector<int> map((size_t)std::max(G, 1), 0);
    for (int g = 0; g < G; ++g) {
        if (ghost_of[g] < 0 || ghost_of[g] >= N) {
            loup::set_error("ghost_of[%d] = %d is not a local atom (0 .. %d)", g, ghost_of[g], N - 1);
            return -1;
        }
        map[g] = row_of[ghost_of[g]];
    }
    DeviceBufferGuard d_map;
    CUDA_CHECK(cudaMalloc(&d_map.p, map.size() * sizeof(int)));
    CUDA_CHECK(cudaMemcpy(d_map.p, map.data(), map.size() * sizeof(int), cudaMemcpyHostToDevice));
    const int* dmap = static_cast<const int*>(d_map.p);

    const int L = h->gen->n_layers();
    DeviceBufferGuard adj[4];  // the locals' rows of a layer output's gradient, per degree, between two sweeps
    for (int l = 0; l < 4; ++l) {
        size_t floats = 0;
        for (int t = 0; t + 1 < L; ++t)
            if (l <= h->gen->out_lmax(t)) floats = std::max(floats, (size_t)N * (2 * l + 1) * h->gen->out_width(t));
        if (floats) CUDA_CHECK(cudaMalloc(&adj[l].p, floats * sizeof(float)));
    }
    struct NoFork {  // the GEMMs are tuned on first use here, and their timings must not overlap
        LoupHandle* h;
        bool saved;
        explicit NoFork(LoupHandle* h_) : h(h_), saved(h_->fork_ok) { h->fork_ok = false; }
        ~NoFork() { h->fork_ok = saved; }
    } no_fork(h);
    const int stress = out_stress ? 1 : 0;
    auto grid = [](int64_t n) { return (unsigned)((n + 255) / 256); };

    CUDA_CHECK(cudaMemsetAsync(h->d_zero_slab, 0, h->zero_slab_bytes, h->stream));
    for (int t = 0; t + 1 < L; ++t) {  // forward sweeps: each leaves its layer's output; the ghosts copy theirs
        DomainSweep sw;
        sw.kind = loup::GenericPassInputs::SweepForward;
        sw.layer = t;
        record_force_pass(h, stress, false, &sw);
        for (int l = 0; G > 0 && l <= h->gen->out_lmax(t); ++l) {
            const int width = (2 * l + 1) * h->gen->out_width(t);
            ghost_copy_rows_kernel<<<grid((int64_t)G * width), 256, 0, h->stream>>>(N, G, width, dmap,
                                                                                    h->gen->layer_out(t, l));
        }
    }
    {
        DomainSweep sw;
        sw.kind = loup::GenericPassInputs::SweepLast;
        record_force_pass(h, stress, false, &sw);
    }
    for (int b = L - 2; b >= 0; --b) {  // backward sweeps: fold the ghosts' gradient rows, hand the locals' on
        DomainSweep sw;
        sw.kind = loup::GenericPassInputs::SweepBackward;
        sw.layer = b;
        for (int l = 0; l <= h->gen->out_lmax(b); ++l) {
            const int width = (2 * l + 1) * h->gen->out_width(b);
            float* grad = h->gen->layer_out_grad(b, l);
            if (G > 0)
                ghost_fold_rows_kernel<float><<<grid((int64_t)G * width), 256, 0, h->stream>>>(N, G, width, dmap, grad);
            CUDA_CHECK(cudaMemcpyAsync(adj[l].p, grad, (size_t)N * width * sizeof(float), cudaMemcpyDeviceToDevice,
                                       h->stream));
            sw.adjoint[l] = static_cast<const float*>(adj[l].p);
        }
        record_force_pass(h, stress, false, &sw);
    }
    if (G > 0)
        ghost_fold_rows_kernel<double><<<grid((int64_t)G * 3), 256, 0, h->stream>>>(N, G, 3, dmap, h->d_forces_f64);

    double inter_e = 0.0, v_grad[6] = {0, 0, 0, 0, 0, 0};
    std::vector<double> f_sorted((size_t)N * 3);
    CUDA_CHECK(cudaMemcpyAsync(&inter_e, h->d_energy_f64, sizeof(double), cudaMemcpyDeviceToHost, h->stream));
    CUDA_CHECK(cudaMemcpyAsync(f_sorted.data(), h->d_forces_f64, (size_t)N * 3 * sizeof(double), cudaMemcpyDeviceToHost, h->stream));
    CUDA_CHECK(cudaMemcpyAsync(v_grad, h->d_virial_grad_f64, 6 * sizeof(double), cudaMemcpyDeviceToHost, h->stream));
    CUDA_CHECK(cudaStreamSynchronize(h->stream));
    CUDA_CHECK(cudaGetLastError());
    h->save_disk_plans();
    if (out_energy_ev) *out_energy_ev = h->e0_total + inter_e;
    if (out_forces) {
        for (int dst = 0; dst < N; ++dst) {
            const int orig = h->perm[dst];
            for (int k = 0; k < 3; ++k) out_forces[orig * 3 + k] = f_sorted[(size_t)dst * 3 + k];
        }
    }
    if (out_stress) {  // per volume of the cell given, which for an open domain is only its box
        const double inv_v = 1.0 / h->cell_vol;
        out_stress[0] = v_grad[0] * inv_v; out_stress[1] = v_grad[1] * inv_v; out_stress[2] = v_grad[2] * inv_v;
        out_stress[3] = v_grad[1] * inv_v; out_stress[4] = v_grad[3] * inv_v; out_stress[5] = v_grad[4] * inv_v;
        out_stress[6] = v_grad[2] * inv_v; out_stress[7] = v_grad[4] * inv_v; out_stress[8] = v_grad[5] * inv_v;
    }
    return 0;
}

// ---- A tile's neighbour list (plan task S5-T02), testing only ----
// The list of cutoff plus skin the handle builds for `positions` (a periodic system, or an open domain whose ghosts
// are a tile's ghost candidates), copied out in the caller's order: receivers are locals, senders locals or ghosts
// (n_local + g for ghost g), shifts the Cartesian offsets of the engine's convention (edge vector = receiver -
// sender + shift). ghost_used[g] (optional) is 1 for each ghost that sends along some edge: the others are candidates
// the tile can drop. With capacity below the count nothing but the count is written.
extern "C++" {
__global__ void mark_ghost_senders_kernel(int E, int n_local, const int* __restrict__ senders,
                                          unsigned char* __restrict__ used) {
    const int e = blockIdx.x * blockDim.x + threadIdx.x;
    if (e < E && senders[e] >= n_local) used[senders[e] - n_local] = 1;
}
}  // extern "C++"

static int domain_edges_impl(LoupHandle* h, const double* positions, const double* cell, long long capacity,
                             int* out_receivers, int* out_senders, double* out_shifts, long long* out_count,
                             unsigned char* out_ghost_used) {
    if (!h || h->N <= 0) { loup::set_error("no system is set"); return -1; }
    if (!out_count) { loup::set_error("out_count is NULL"); return -1; }
    const int N = h->N, G = h->n_ghost;
    CUDA_CHECK(cudaSetDevice(h->device_id));
    if (upload_positions(h, positions, cell) < 0) return -1;
    if (rebuild_neighbors(h) != 0) return -1;
    const int E = h->E_skin;
    *out_count = E;
    if (out_ghost_used && G > 0) {
        DeviceBufferGuard used;
        CUDA_CHECK(cudaMalloc(&used.p, G));
        CUDA_CHECK(cudaMemsetAsync(used.p, 0, G, h->stream));
        if (E > 0)
            mark_ghost_senders_kernel<<<(E + 255) / 256, 256, 0, h->stream>>>(
                E, N, h->d_senders, static_cast<unsigned char*>(used.p));
        CUDA_CHECK(cudaMemcpyAsync(out_ghost_used, used.p, G, cudaMemcpyDeviceToHost, h->stream));
        CUDA_CHECK(cudaStreamSynchronize(h->stream));
    }
    if (capacity < E || E == 0) return 0;
    std::vector<int> rcv(E), snd(E), row_ptr((size_t)N + 1);
    std::vector<double> sh((size_t)E * 3);
    // Row i of the list holds the edges whose receiver is i (no per-edge receiver array is kept).
    CUDA_CHECK(cudaMemcpyAsync(row_ptr.data(), h->d_row_ptr, ((size_t)N + 1) * sizeof(int), cudaMemcpyDeviceToHost,
                               h->stream));
    CUDA_CHECK(cudaMemcpyAsync(snd.data(), h->d_senders, (size_t)E * sizeof(int), cudaMemcpyDeviceToHost, h->stream));
    CUDA_CHECK(cudaMemcpyAsync(sh.data(), h->d_shift_cart, (size_t)E * 3 * sizeof(double), cudaMemcpyDeviceToHost,
                               h->stream));
    CUDA_CHECK(cudaStreamSynchronize(h->stream));
    for (int i = 0; i < N; ++i)
        for (int e = row_ptr[i]; e < row_ptr[i + 1]; ++e) rcv[e] = i;
    for (int e = 0; e < E; ++e) {
        if (out_receivers) out_receivers[e] = h->perm[rcv[e]];
        if (out_senders) out_senders[e] = h->perm[snd[e]];
        if (out_shifts)
            for (int k = 0; k < 3; ++k) out_shifts[(size_t)e * 3 + k] = sh[(size_t)e * 3 + k];
    }
    return 0;
}

// ---- The tiled call (plan task S5-T03), testing only until S5-T05 makes it a mode of the public calls ----
// A whole periodic system evaluated tile by tile (src/tiled.hpp): every tile is an open domain of its locals and the
// ghost candidates that send along some edge of its list. The per-layer sweeps run over all tiles in turn, and the
// state between sweeps lives in whole-system arrays on the device: each forward sweep writes its locals' rows of
// the layer's output, the next sweep gathers the rows of its locals and ghosts; the last sweep and each backward
// sweep scatter-add the gradient rows of every row (ghosts fold onto the atom they are an image of), and the
// backward sweep of a layer takes its locals' gradient rows as its adjoint. Forces fold the same way.
// Plain launches, no graphs; every tile sweep sets its domain up again (S5-T06 keeps lists, S5-T10 the speed).
extern "C++" {
__global__ void tile_gather_rows_kernel(int rows, int width, const int* __restrict__ row_atom,
                                        const float* __restrict__ whole, float* __restrict__ tile) {
    const int64_t k = (int64_t)blockIdx.x * blockDim.x + threadIdx.x;
    if (k >= (int64_t)rows * width) return;
    const int r = (int)(k / width), c = (int)(k % width);
    tile[k] = whole[(int64_t)row_atom[r] * width + c];
}

__global__ void tile_scatter_rows_kernel(int rows, int width, const int* __restrict__ row_atom,
                                         const float* __restrict__ tile, float* __restrict__ whole) {
    const int64_t k = (int64_t)blockIdx.x * blockDim.x + threadIdx.x;
    if (k >= (int64_t)rows * width) return;
    const int r = (int)(k / width), c = (int)(k % width);
    whole[(int64_t)row_atom[r] * width + c] = tile[k];
}

template <typename T>
__global__ void tile_scatter_add_rows_kernel(int rows, int width, const int* __restrict__ row_atom,
                                             const T* __restrict__ tile, T* __restrict__ whole) {
    const int64_t k = (int64_t)blockIdx.x * blockDim.x + threadIdx.x;
    if (k >= (int64_t)rows * width) return;
    const int r = (int)(k / width), c = (int)(k % width);
    atomicAdd(&whole[(int64_t)row_atom[r] * width + c], tile[k]);
}

// O32: a device-to-device copy on the SMs (the host state's ring slots; cudaMemcpyAsync would take a copy engine
// and wait behind the host transfers there)
__global__ void tile_copy_floats_kernel(int64_t n4, const float4* __restrict__ src, float4* __restrict__ dst) {
    for (int64_t k = (int64_t)blockIdx.x * blockDim.x + threadIdx.x; k < n4; k += (int64_t)gridDim.x * blockDim.x)
        dst[k] = src[k];
}
__global__ void tile_add_floats_kernel(int64_t n, const float* __restrict__ src, float* __restrict__ dst) {
    for (int64_t k = (int64_t)blockIdx.x * blockDim.x + threadIdx.x; k < n; k += (int64_t)gridDim.x * blockDim.x)
        dst[k] += src[k];
}
__global__ void tile_copy_floats_tail_kernel(int64_t n, const float* __restrict__ src, float* __restrict__ dst) {
    for (int64_t k = (int64_t)blockIdx.x * blockDim.x + threadIdx.x; k < n; k += (int64_t)gridDim.x * blockDim.x)
        dst[k] = src[k];
}

// The wavefront's row pool (S5-T08): zero rows of a pool array, and map a tile's rows to their atoms' pool rows.
__global__ void tile_zero_rows_kernel(int rows, int width, const int* __restrict__ row_slot, float* __restrict__ pool) {
    const int64_t k = (int64_t)blockIdx.x * blockDim.x + threadIdx.x;
    if (k >= (int64_t)rows * width) return;
    const int r = (int)(k / width), c = (int)(k % width);
    pool[(int64_t)row_slot[r] * width + c] = 0.0f;
}

__global__ void tile_map_rows_kernel(int rows, const int* __restrict__ row_atom, const int* __restrict__ slot_of_atom,
                                     int* __restrict__ row_slot) {
    const int r = blockIdx.x * blockDim.x + threadIdx.x;
    if (r < rows) row_slot[r] = slot_of_atom[row_atom[r]];
}
}  // extern "C++"

extern "C++" {
// A kept tile's device positions from the whole system's: row r is atom row_atom[r] moved by its fixed image offset.
__global__ void tile_place_rows_kernel(int rows, const int* __restrict__ row_atom, const double* __restrict__ offset,
                                       const double* __restrict__ whole, double* __restrict__ pos) {
    const int64_t k = (int64_t)blockIdx.x * blockDim.x + threadIdx.x;
    if (k >= (int64_t)rows * 3) return;
    const int r = (int)(k / 3), c = (int)(k % 3);
    pos[k] = whole[(int64_t)row_atom[r] * 3 + c] + offset[k];
}

// LT6 (a): a kept tile's rows in a cell h other than the build's h0. Row r's place is its atom's position + S h - org
// (TileDomain), and offset = S h0 - org was kept at the build, so S = rint((offset + org) h0^-1) and the place in
// h is position + offset + S (h - h0). Every edge of an open domain has a zero shift, so the edges need nothing.
struct TileCellMove {
    double inv0[9];  // h0^-1 (frac = x inv0)
    double dh[9];    // h - h0
    double org[3];   // the tile's origin
};
__global__ void tile_place_rows_cell_kernel(int rows, const int* __restrict__ row_atom,
                                            const double* __restrict__ offset, const double* __restrict__ whole,
                                            TileCellMove m, double* __restrict__ pos) {
    const int r = blockIdx.x * blockDim.x + threadIdx.x;
    if (r >= rows) return;
    const double o0 = offset[(int64_t)r * 3 + 0], o1 = offset[(int64_t)r * 3 + 1], o2 = offset[(int64_t)r * 3 + 2];
    const double a0 = o0 + m.org[0], a1 = o1 + m.org[1], a2 = o2 + m.org[2];
    double s[3];
    for (int k = 0; k < 3; ++k) s[k] = rint(a0 * m.inv0[k] + a1 * m.inv0[3 + k] + a2 * m.inv0[6 + k]);
    const int64_t a = row_atom[r];
    const double o[3] = {o0, o1, o2};
    for (int c = 0; c < 3; ++c)
        pos[(int64_t)r * 3 + c] = whole[a * 3 + c] + o[c] + (s[0] * m.dh[c] + s[1] * m.dh[3 + c] + s[2] * m.dh[6 + c]);
}

// LT6 (a): the displacements d = x - x0 F of a strained cell (F = h0^-1 h, row vectors), summed into sum[0..2] for
// their mean t; then the largest |d - t|^2 as max_disp2_kernel gives it. A common translation moves no pair vector.
struct Mat9 {
    double m[9];
};
__device__ __forceinline__ void strain_disp(const double* __restrict__ pos, const double* __restrict__ ref,
                                            const Mat9& f, int i, double d[3]) {
    const double x0 = ref[i * 3 + 0], y0 = ref[i * 3 + 1], z0 = ref[i * 3 + 2];
    for (int c = 0; c < 3; ++c) d[c] = pos[i * 3 + c] - (x0 * f.m[c] + y0 * f.m[3 + c] + z0 * f.m[6 + c]);
}
__global__ void strain_disp_sum_kernel(int n, const double* __restrict__ pos, const double* __restrict__ ref, Mat9 f,
                                       double* __restrict__ sum) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    double d[3] = {0.0, 0.0, 0.0};
    if (i < n) strain_disp(pos, ref, f, i, d);
    for (int c = 0; c < 3; ++c) {
        double v = d[c];
        for (int o = 16; o > 0; o >>= 1) v += __shfl_down_sync(0xffffffffu, v, o);
        if ((threadIdx.x & 31) == 0) atomicAdd(sum + c, v);
    }
}
__global__ void strain_disp_max_kernel(int n, const double* __restrict__ pos, const double* __restrict__ ref, Mat9 f,
                                       const double* __restrict__ sum, unsigned long long* __restrict__ out) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    double d2 = 0.0;
    if (i < n) {
        double d[3];
        strain_disp(pos, ref, f, i, d);
        const double inv_n = 1.0 / (double)n;
        for (int c = 0; c < 3; ++c) {
            const double e = d[c] - sum[c] * inv_n;
            d2 += e * e;
        }
    }
    for (int o = 16; o > 0; o >>= 1) d2 = fmax(d2, __shfl_down_sync(0xffffffffu, d2, o));
    if ((threadIdx.x & 31) == 0) atomicMax(out, (unsigned long long)__double_as_longlong(d2));
}

// The largest squared displacement of `pos` from `ref` [n, 3], as the bits of a non-negative double (which order
// as unsigned integers).
__global__ void max_disp2_kernel(int n, const double* __restrict__ pos, const double* __restrict__ ref,
                                 unsigned long long* __restrict__ out) {
    const int i = blockIdx.x * blockDim.x + threadIdx.x;
    double d2 = 0.0;
    if (i < n) {
        const double dx = pos[i * 3] - ref[i * 3], dy = pos[i * 3 + 1] - ref[i * 3 + 1],
                     dz = pos[i * 3 + 2] - ref[i * 3 + 2];
        d2 = dx * dx + dy * dy + dz * dz;
    }
    for (int o = 16; o > 0; o >>= 1) d2 = fmax(d2, __shfl_down_sync(0xffffffffu, d2, o));
    if ((threadIdx.x & 31) == 0) atomicMax(out, (unsigned long long)__double_as_longlong(d2));
}
}  // extern "C++"

namespace {
struct TileDomain {        // one tile as an open domain: locals, then the ghosts it keeps
    int n_local = 0;
    std::vector<int> atom;           // [n_local + n_ghost] the whole system's atom of each row (caller order)
    std::vector<int> z;
    std::vector<double> place;       // [rows, 3] positions in the domain's box
    double box[9] = {0, 0, 0, 0, 0, 0, 0, 0, 0};
    double org[3] = {0, 0, 0};       // the domain's origin: a row's place is its atom's position + S h - org
    int n_ghost() const { return (int)atom.size() - n_local; }
};
}  // namespace

// Tile k of `plan` as an open domain on the host: its locals, then all its ghost candidates, placed in a box with
// room for the list's reach on every side.
static void host_domain(const loup::TilePlan& plan, int64_t k, const int* atomic_numbers, const double* positions,
                        const double* cell, double r_list, TileDomain& all) {
    const int64_t l0 = plan.local_ptr[k], l1 = plan.local_ptr[k + 1];
    const int64_t g0 = plan.ghost_ptr[k], g1 = plan.ghost_ptr[k + 1];
    all.n_local = (int)(l1 - l0);
    auto add = [&](int a, const int32_t* s) {
        all.atom.push_back(a);
        all.z.push_back(atomic_numbers[a]);
        for (int c = 0; c < 3; ++c)
            all.place.push_back(positions[(int64_t)a * 3 + c] + s[0] * cell[c] + s[1] * cell[3 + c] +
                                s[2] * cell[6 + c]);
    };
    for (int64_t i = l0; i < l1; ++i) add(plan.local[i], &plan.local_shift[i * 3]);
    for (int64_t i = g0; i < g1; ++i) add(plan.ghost[i], &plan.ghost_shift[i * 3]);
    double lo[3] = {INFINITY, INFINITY, INFINITY}, hi[3] = {-INFINITY, -INFINITY, -INFINITY};
    for (size_t r = 0; r < all.atom.size(); ++r)
        for (int c = 0; c < 3; ++c) {
            lo[c] = std::min(lo[c], all.place[r * 3 + c]);
            hi[c] = std::max(hi[c], all.place[r * 3 + c]);
        }
    const double pad = r_list + 1.0;  // the box's own images then lie beyond the list's reach
    for (size_t r = 0; r < all.atom.size(); ++r)
        for (int c = 0; c < 3; ++c) all.place[r * 3 + c] -= lo[c] - pad;
    for (int c = 0; c < 3; ++c) {
        all.box[c * 4] = hi[c] - lo[c] + 2.0 * pad;
        all.org[c] = lo[c] - pad;
    }
}

// Device bytes of the handle's per-system buffers (released when another system or workspace is set up).
static double handle_system_bytes(const LoupHandle* h) {
    return (double)h->sys_atom_bytes + (double)h->sys_edge_bytes + (double)h->sys_fixed_bytes +
           (double)h->cub_tmp_bytes + (h->gen ? (double)h->gen->system_bytes() + (double)h->gen->edge_bytes() : 0.0);
}

// A tile workspace: the handle holds an open domain whose buffers have room for `atom_cap` rows. Another domain
// of at most that many rows takes them over: only the species grouping, the per-atom constants and the row counts
// change. Buffers, the edge capacity, the GEMM plans and the cuBLASLt cache stay (loup_set_system would free and
// allocate them all, and clear the cache).
static int reshape_domain(LoupHandle* h, int n_local, int n_ghost, const int* atomic_numbers) {
    const int n_atoms = n_local + n_ghost;
    if (!h->gen || h->N <= 0 || n_local <= 0 || n_ghost < 0 || n_atoms > h->atom_cap) {
        loup::set_error("internal error: a tile of %d rows does not fit the workspace of %d", n_atoms, h->atom_cap);
        return -1;
    }
    const int S = h->n_species();
    std::vector<int> sp_orig(n_atoms);
    double e0_total = 0.0;
    for (int i = 0; i < n_atoms; ++i) {
        int found = -1;
        for (int s = 0; s < S; ++s)
            if (h->species_z(s) == atomic_numbers[i]) { found = s; break; }
        if (found < 0) {
            loup::set_error("atomic number %d (atom %d) is not in the bundle", atomic_numbers[i], i);
            return -1;
        }
        sp_orig[i] = found;
        if (i < n_local) e0_total += h->species_e0(found);
    }
    h->perm.resize(n_atoms);
    h->h_order.resize(n_atoms);
    h->species_start.assign(S + 1, 0);
    h->species_count.assign(S, 0);
    for (int i = 0; i < n_local; ++i) h->species_count[sp_orig[i]]++;
    for (int s = 0; s < S; ++s) h->species_start[s + 1] = h->species_start[s] + h->species_count[s];
    std::vector<int> cursor = h->species_start, sp_sorted(n_atoms);
    for (int i = 0; i < n_atoms; ++i) {
        const int dst = i < n_local ? cursor[sp_orig[i]]++ : i;
        h->perm[dst] = i;
        sp_sorted[dst] = sp_orig[i];
    }
    CUDA_CHECK(cudaMemcpyAsync(h->d_species, sp_sorted.data(), (size_t)n_atoms * sizeof(int), cudaMemcpyHostToDevice,
                               h->stream));
    CUDA_CHECK(cudaStreamSynchronize(h->stream));  // `sp_sorted` goes out of scope
    h->e0_total = e0_total;
    h->atom_e0.assign(n_atoms, 0.0);
    for (int i = 0; i < n_local; ++i) h->atom_e0[i] = h->species_e0(sp_orig[i]);
    h->N = n_local;
    h->n_ghost = n_ghost;
    h->nl_valid = false;
    h->forces_current = false;
    h->n_rebuilds = 0;
    h->invalidate_graphs();
    return 0;
}

// A tile's list, kept on the device for the sweeps of one call: everything a sweep reads of the handle's domain.
namespace {
// O32: a view into one allocation cut into several arrays (alloc_slot): not owned. One allocation instead of several
// because each cudaMalloc here took about 2 MB more than asked (tile-slot-block).
struct SlotView {
    void* p = nullptr;
};
// O32: the tile lists' device arrays from a few large chunks instead of an allocation per tile: each allocation of a
// few MB took about 1.3 MB more than asked on the RTX 5060 Ti (WSL), 891 lists of the 2,560,000-atom device plan 1.1
// GB (cudaMalloc alone: 2,606 MB asked, 3,737 MB used; tile-list-arena)
struct DeviceArena {
    std::vector<std::unique_ptr<DeviceBufferGuard>> chunks;
    size_t used = 0, cap = 0;
    size_t chunk = (size_t)128 << 20;  // the size of a new chunk (or the request, when larger)
    void* get(size_t bytes) {  // nullptr when the device is out of memory
        bytes = (bytes + 255) / 256 * 256;
        if (chunks.empty() || used + bytes > cap) {
            const size_t want = std::max<size_t>(bytes, chunk);
            auto g = std::make_unique<DeviceBufferGuard>();
            if (loup::device_malloc(&g->p, want) != cudaSuccess) {
                g->p = nullptr;
                (void)cudaGetLastError();
                return nullptr;
            }
            chunks.push_back(std::move(g));
            used = 0;
            cap = want;
        }
        void* p = static_cast<char*>(chunks.back()->p) + used;
        used += bytes;
        return p;
    }
};
// cuts one allocation (blk, or from the arena when one is given) into views of the given sizes (each at a 256 B
// boundary); false when the device is out of memory
inline bool alloc_slot(DeviceBufferGuard& blk, std::initializer_list<std::pair<SlotView*, size_t>> parts,
                       DeviceArena* arena = nullptr) {
    size_t total = 0;
    for (const auto& pt : parts) total += (pt.second + 255) / 256 * 256;
    total = std::max<size_t>(total, 256);
    char* base = nullptr;
    if (arena) {
        base = static_cast<char*>(arena->get(total));
        if (!base) return false;
    } else {
        if (loup::device_malloc(&blk.p, total) != cudaSuccess) {
            blk.p = nullptr;
            return false;
        }
        base = static_cast<char*>(blk.p);
    }
    size_t off = 0;
    for (const auto& pt : parts) {
        pt.first->p = base + off;
        off += (pt.second + 255) / 256 * 256;
    }
    return true;
}
// The full (not compact) form of a tile list's edges: the Cartesian shift (24 B) and the sender (4 B). A row is one
// receiver's edges and the pair index follows from the species, so neither is stored per edge (S113 of the main
// list; 36 B per edge before the merge of round6-hardening).
constexpr int kTileFullEdgeB = 28;
struct TileList {
    int n_local = 0, rows = 0, E = 0;
    double e0 = 0.0, box[9] = {0, 0, 0, 0, 0, 0, 0, 0, 0};
    double org[3] = {0, 0, 0};  // TileDomain::org: a row's whole-cell image is rint((offset + org) h0^-1) (LT6 (a))
    std::vector<int> perm, species_start, species_count;
    // O32: one allocation (blk) cut into the arrays below (tile-slot-block's rounding: about 2 MB per allocation)
    DeviceBufferGuard blk;
    SlotView species, pos, row_ptr, senders, shift, row_atom;
    // O31 (S5-T07): with host lists the edge arrays (senders, shifts: kTileFullEdgeB per edge) live in one block of
    // mapped pinned host memory instead of `senders` and `shift`, and the pointers below are its device view
    HostBufferGuard host_edges;
    int* h_senders = nullptr;
    double* h_shift = nullptr;
    // O32: the compact form (LOUP_TILE_HOST_COMPACT=0: the full form above): the senders and each edge's integer image
    // shift, 8 B per edge; the compaction's inputs are rebuilt from them on the device (tile_decode_edges_kernel)
    bool compact = false;
    const int* h_csnd = nullptr;  // device views: of host_edges, or of senders and ccode (device lists, compact)
    const char4* h_ccode = nullptr;
    SlotView ccode;      // a compact device list's integer image shifts
    SlotView offset;  // [rows, 3] a row's place in the tile less its atom's position at the build
    DeviceBufferGuard row_slot;  // the wavefront (S5-T08): [rows] each row's atom's row in the pool of x and dx
    // The active edges (r < r_max) of this call's positions: compacted in the tile's first sweep of a call into a
    // slot of TiledState::act_slots when one is free, read from it by its later sweeps (O31: the compaction ran in
    // every sweep); the slot goes back at the tile's last sweep.
    mutable int act_slot = -1;        // the slot, -1 none
    mutable int cact_slot = -1;       // O32: or a compact slot (TiledState::cact_slots), -1 none
    mutable long long act_call = -1;  // the call in whose first sweep the tile took it
    // O31: layer 0's msgf and D from the tile's forward sweep of layer 0, read by its backward sweep of layer 0
    // instead of the replay (GenericModel::sweep_keep_layer0); allocated when the memory allows
    DeviceBufferGuard keep0;
    // O32 (S5-T07 step 2): the host copy of row_atom (until the host state's indices are set), and with the layer
    // state in host memory the first host row of the tile's locals (its rows 0..n_local-1, in order) and the host
    // rows of its ghosts
    std::vector<int> h_row_atom;
    int64_t hbase = 0;
    std::vector<int> h_ghost;
};

// O31 (S5-T07): with host lists, the edge arrays of each sweep that compacts a tile's active edges are copied into
// one of two device buffers on a copy stream, one compaction ahead, instead of the compaction reading them over the bus
struct StageRing {
    DeviceBufferGuard buf[2];
    cudaStream_t copy = nullptr;
    cudaEvent_t copied[2] = {nullptr, nullptr}, used[2] = {nullptr, nullptr};
    StageRing() = default;
    StageRing(const StageRing&) = delete;
    StageRing& operator=(const StageRing&) = delete;
    ~StageRing() {
        for (int i = 0; i < 2; ++i) {
            if (copied[i]) cudaEventDestroy(copied[i]);
            if (used[i]) cudaEventDestroy(used[i]);
        }
        if (copy) cudaStreamDestroy(copy);
    }
};

// O32: the host state's pipeline. The copy streams move rows between the host state and two device ring slots
// (`a`: the last sweep's inputs, the backward sweeps' adjoints; `b`: the forward sweeps' outputs, the last sweep's
// gradients), host threads gather ghost rows into and add gradient rows from pinned staging, one tile ahead or
// behind the sweeps; the events order slot reuse, `tile_out[i]` marks tile i's forward outputs written to the host.
struct HostPipe {
    cudaStream_t copy = nullptr, down = nullptr;  // host to device, device to host
    enum { kIn, kInUsed, kG, kGh, kFwd, kOut, kAdjIn, kAdjUsed, kEv };
    cudaEvent_t ev[kEv][2] = {};
    DeviceBufferGuard a[2], b[2];
    HostBufferGuard in[2], out[2];
    std::vector<cudaEvent_t> tile_out;
    int tile_events(size_t n) {
        while (tile_out.size() < n) {
            cudaEvent_t e = nullptr;
            if (cudaEventCreateWithFlags(&e, cudaEventDisableTiming) != cudaSuccess) return -1;
            tile_out.push_back(e);
        }
        return 0;
    }
    HostPipe() = default;
    HostPipe(const HostPipe&) = delete;
    HostPipe& operator=(const HostPipe&) = delete;
    int init() {
        if (copy) return 0;
        if (cudaStreamCreateWithFlags(&copy, cudaStreamNonBlocking) != cudaSuccess) return -1;
        if (cudaStreamCreateWithFlags(&down, cudaStreamNonBlocking) != cudaSuccess) return -1;
        for (auto& e : ev)
            for (auto& x : e)
                if (cudaEventCreateWithFlags(&x, cudaEventDisableTiming) != cudaSuccess) return -1;
        return 0;
    }
    ~HostPipe() {
        if (copy) cudaStreamSynchronize(copy);
        if (down) cudaStreamSynchronize(down);
        for (auto& e : ev)
            for (auto& x : e)
                if (x) cudaEventDestroy(x);
        for (cudaEvent_t x : tile_out) cudaEventDestroy(x);
        if (copy) cudaStreamDestroy(copy);
        if (down) cudaStreamDestroy(down);
    }
};

// One tile's active edges, sized for the longest list (TileList::act_slot)
// O32: a slot is one allocation (blk) cut into its arrays at 256 B boundaries: six allocations per slot each took
// about 2 MB more than asked (2,560,000 atoms: 125 slots of 74 MB took 10.6 GB, 1.4 GB beyond the plan, into the
// reserve)
struct ActiveSlot {
    DeviceBufferGuard blk;
    SlotView row_ptr, senders, receivers, vec_len, slab, t_sx;
};
// O32: a compact slot (tiles of compact lists): the active edges' row pointers, senders and integer image shifts, 8 B
// per edge instead of ActiveSlot's 40; a later sweep restores the rest (tile_restore_active_kernel)
struct CompactSlot {
    DeviceBufferGuard blk;
    SlotView row_ptr, senders, code;
};

// The tiled call's state kept on the handle between calls (S5-T06). Never copied: its buffers free themselves.
struct TiledState {
    int n = 0, receivers = 0, max_rows = 0, max_edges = 0;
    int act_keep = -1;     // the slots of kept active edges: -1 not decided yet, else their number
    int cact_keep = 0;     // O32: the compact slots
    long long calls = 0;   // tiled calls on these lists
    std::vector<ActiveSlot> act_slots;
    std::vector<int> act_free;  // the slots no tile holds
    std::vector<CompactSlot> cact_slots;  // O32: compact slots for the tiles in flight beyond the full ones
    std::vector<int> cact_free;
    int keep_l0 = -1;           // the tiles keep layer 0's forward results (TileList::keep0): -1 not decided
    int64_t T = 0;
    double skin = 0.0, cell[9] = {0, 0, 0, 0, 0, 0, 0, 0, 0};  // the cell the lists were built in
    double ref_inv[9] = {0, 0, 0, 0, 0, 0, 0, 0, 0};            // its inverse (frac = x ref_inv; LT6 (a))
    double bytes = 0.0;  // device bytes of everything below
    bool host_lists = false;  // the lists' edge arrays in pinned host memory (O31, S5-T07)
    double host_bytes = 0.0;  // their bytes
    int stage = 0;            // the host lists are staged through `ring` (StageRing; decided with the slots)
    // O32: the layer outputs and their gradients in pinned host memory (plain order), rows in tile order
    bool host_state = false;
    std::vector<HostBufferGuard> hx, hdx;
    // dx takes x's rows (two-layer models with the pipeline; hdx not allocated): a block's gradients are added into
    // a window (host memory, reused across calls) until the block's last reader has its inputs, then folded into x
    bool alias = false;
    std::vector<std::unique_ptr<HostBufferGuard>> win;  // pinned (the backward sweeps read kept windows)
    std::vector<size_t> win_floats;
    HostBufferGuard stage_in, stage_out;  // pinned staging: ghost rows in, gradient rows out
    bool pipe = false;                    // the copies and host work overlapped (HostPipe)
    size_t pipe_floats = 0;               // floats per ring slot: the widest tile's rows of a layer's orders
    HostPipe hp;
    StageRing ring;
    std::vector<int> z;
    DeviceArena list_arena;  // O32: the lists' device arrays (tile-list-arena)
    DeviceArena slot_arena, cslot_arena;  // O32: the slots' (act_slots, cact_slots)
    std::vector<TileList> lists;
    DeviceBufferGuard whole_pos, ref_pos, disp2;  // [n, 3] this call's and the build's positions; one 64-bit word
    std::vector<DeviceBufferGuard> x, dx;         // [(L - 1) * 4] layer outputs and their gradients, whole system
    DeviceBufferGuard forces, adj[4];
    // The wavefront (S5-T08, two-layer models): the sweeps in the order of loup::wavefront_schedule, and x and dx
    // in a pool of `pool_rows` rows instead of n (each tile's row_slot gives its rows' places).
    bool wave = false;
    int64_t pool_rows = 0;
    std::vector<loup::SweepStep> steps;
};

// Tiled MD on the device (loup_tiled_set_state / loup_tiled_run, PLAN.md O31). The integrator kernels of the
// whole-system loop (integrator.cu) run on these whole-system arrays; each force call is the tiled call on the device
// positions, so a step moves nothing to the host except at a list rebuild, whose planner reads the positions there.
// Fixed atoms have inverse masses 0 (they neither move nor feel the thermostat's noise) and zero velocities.
struct TiledMD {
    int n = 0, receivers = 0, n_fixed = 0;
    double skin = 0.5, cell[9] = {0, 0, 0, 0, 0, 0, 0, 0, 0}, total_mass = 0.0;
    std::vector<int> z;
    DeviceBufferGuard pos, vel, forces, masses, inv_m, sqrt_inv_m, rnd_vel, rnd_pos;  // [n, 3] or [n]
    DeviceBufferGuard com, target, step, int_state, int_work, disp, ke;                // scalars
    bool forces_current = false;
    double energy = 0.0;
    int state_kind = -1;          // the integrator whose scalars int_state holds
    long long md_steps = 0;       // steps since loup_tiled_set_state (the thermo rows' step)
    // LT6 (a), the barostats: the cell on the device (loup::CellDev), the last force call's virial [6] there (valid
    // while virial_current), the cell check's flag; V0 of the volume limits; the cell the cap was planned or set for
    DeviceBufferGuard celldev, virial, flag;
    bool virial_current = false;
    double virial_h[6] = {0, 0, 0, 0, 0, 0};  // its host copy (the thermo rows' pressure)
    double v0 = 0.0, plan_cell[9] = {0, 0, 0, 0, 0, 0, 0, 0, 0};
};
}  // namespace

extern "C++" {
static void release_tiled_md(LoupHandle* h) {
    delete h->tiled_md;
    h->tiled_md = nullptr;
}

// O32: pinned host memory (cudaHostAllocDefault) for the tiled state: a spare of the handle's of at least `bytes` and
// at most 25% (and 1 MB) more when there is one, else a new allocation; false when none is to be had
static bool pinned_take(LoupHandle* h, HostBufferGuard& g, size_t bytes, bool mapped = false) {
    bytes = std::max<size_t>(bytes, 1);
    auto& v = mapped ? h->pinned_spare.mapped : h->pinned_spare.bufs;
    size_t best = v.size();
    for (size_t i = 0; i < v.size(); ++i)
        if (v[i].first >= bytes && v[i].first <= bytes + bytes / 4 + ((size_t)1 << 20) &&
            (best == v.size() || v[i].first < v[best].first))
            best = i;
    if (best < v.size()) {
        g.p = v[best].second;
        g.n = v[best].first;
        v.erase(v.begin() + (std::ptrdiff_t)best);
        return true;
    }
    // a new buffer has 1/32 room to grow: the first list rebuild after the atoms moved asks a little more than the
    // first call's buffers and found no spare (2,560,000 atoms: 10.22 s, 2.47 s of it host windows and 0.56 s state
    // buffers, against 7.06 s with the room; later rebuilds 7.1-7.2 s either way; tile-pinned-headroom). The plan's
    // host estimate does not count it (3%).
    const size_t want = bytes + bytes / 32;
    if (cudaHostAlloc(&g.p, want, mapped ? cudaHostAllocMapped : cudaHostAllocDefault) != cudaSuccess) {
        g.p = nullptr;
        (void)cudaGetLastError();
        return false;
    }
    g.n = want;
    return true;
}

static void release_tiled_state(LoupHandle* h) {
    if (TiledState* st = h->tiled_state) {  // O32: its pinned buffers become the handle's spares
        {
            const DeviceOrder order(true);  // a device-wide synchronisation (DeviceOrder)
            cudaDeviceSynchronize();        // no copy may still read or write them
        }
        auto keep = [&](HostBufferGuard& g) {
            if (g.p && g.n) {
                h->pinned_spare.bufs.push_back({g.n, g.p});
                g.p = nullptr;
            }
        };
        for (HostBufferGuard& g : st->hx) keep(g);
        for (HostBufferGuard& g : st->hdx) keep(g);
        keep(st->stage_in);
        keep(st->stage_out);
        for (int k = 0; k < 2; ++k) {
            keep(st->hp.in[k]);
            keep(st->hp.out[k]);
        }
        for (auto& w : st->win)
            if (w) keep(*w);
        for (TileList& t : st->lists)  // the host lists' edges (mapped)
            if (t.host_edges.p && t.host_edges.n) {
                h->pinned_spare.mapped.push_back({t.host_edges.n, t.host_edges.p});
                t.host_edges.p = nullptr;
            }
    }
    delete h->tiled_state;
    h->tiled_state = nullptr;
}
}  // extern "C++"

// O32: an edge's Cartesian shift from its integer image shift, component k, with explicit rounding (no FMA
// contraction) so that the encode check, the decode and the compact slots' restore give the same bits.
__device__ __forceinline__ double tile_shift_comp(const loup::CellMat64& cell, double sx, double sy, double sz, int k) {
    return __dadd_rn(__dadd_rn(__dmul_rn(sx, cell.c[k]), __dmul_rn(sy, cell.c[3 + k])), __dmul_rn(sz, cell.c[6 + k]));
}

// O32: compact host lists. The integer image shift of each edge from its Cartesian shift (the box's inverse), kept
// only when it fits a signed byte and gives the Cartesian shift back bit for bit (tile_shift_comp against the list
// build's own value, sort_gather_rows_kernel); `bad` is set otherwise and the tile keeps the full form.
__global__ void tile_encode_edges_kernel(int E, loup::CellMat64 cell, const double* __restrict__ shift,
                                         char4* __restrict__ code, int* __restrict__ bad) {
    const int e = blockIdx.x * blockDim.x + threadIdx.x;
    if (e >= E) return;
    const double v0 = shift[(int64_t)e * 3 + 0], v1 = shift[(int64_t)e * 3 + 1], v2 = shift[(int64_t)e * 3 + 2];
    double n[3];
    for (int k = 0; k < 3; ++k) n[k] = rint(v0 * cell.inv[k] + v1 * cell.inv[3 + k] + v2 * cell.inv[6 + k]);
    const double sx = n[0], sy = n[1], sz = n[2];
    const bool fits = fabs(sx) <= 127.0 && fabs(sy) <= 127.0 && fabs(sz) <= 127.0;
    const bool same = tile_shift_comp(cell, sx, sy, sz, 0) == v0 && tile_shift_comp(cell, sx, sy, sz, 1) == v1 &&
                      tile_shift_comp(cell, sx, sy, sz, 2) == v2;
    if (!(fits && same)) {
        *bad = 1;
        return;
    }
    code[e] = make_char4((signed char)sx, (signed char)sy, (signed char)sz, 0);
}

// The compaction's inputs of a compact host list: one warp per receiver row.
__global__ void tile_decode_edges_kernel(int N, loup::CellMat64 cell, const int* __restrict__ row_ptr,
                                         const int* __restrict__ snd, const char4* __restrict__ code,
                                         int* __restrict__ senders, double* __restrict__ shift) {
    const int tid = blockIdx.x * blockDim.x + threadIdx.x;
    const int i = tid >> 5, lane = tid & 31;
    if (i >= N) return;
    for (int e = row_ptr[i] + lane; e < row_ptr[i + 1]; e += 32) {
        const int j = snd[e];
        const char4 c = code[e];
        senders[e] = j;
        const double sx = (double)c.x, sy = (double)c.y, sz = (double)c.z;
        for (int k = 0; k < 3; ++k) shift[(int64_t)e * 3 + k] = tile_shift_comp(cell, sx, sy, sz, k);
    }
}

extern "C++" {  // declared before record_force_pass, outside this file's C linkage block
// O32 compact slots: after a compaction of a compact list (scatter_active_edges_kernel's order), each active edge's
// integer image shift, beside the senders and row pointers the compaction wrote into the slot.
__global__ void tile_pack_active_codes_kernel(int N, float r_max, const int* __restrict__ row_ptr,
                                              const int* __restrict__ act_row_ptr,
                                              const float4* __restrict__ tmp_vec_len,
                                              const char4* __restrict__ code, char4* __restrict__ act_code) {
    const int tid = blockIdx.x * blockDim.x + threadIdx.x;
    const int i = tid >> 5, lane = tid & 31;
    if (i >= N) return;
    const int eb = row_ptr[i], ee = row_ptr[i + 1];
    int out = act_row_ptr[i];
    for (int base = eb; base < ee; base += 32) {
        const int e = base + lane;
        const bool act = e < ee && tmp_vec_len[e].w < r_max;
        const unsigned mask = __ballot_sync(0xffffffffu, act);
        if (act) act_code[out + __popc(mask & ((1u << lane) - 1u))] = code[e];
        out += __popc(mask);
    }
}

// O32 compact slots: a later sweep's active edges from the slot (row pointers, senders, integer image shifts): the
// receivers, vectors and spline locators of scatter_active_edges_kernel, bit for bit (the vector as
// compute_and_count_active_kernel forms it, the shift as the decode does).
__global__ void tile_restore_active_kernel(int N, SplineGrid grid, int S, int pair_sym, loup::CellMat64 cell,
                                           const double* __restrict__ pos64, const int* __restrict__ species,
                                           const int* __restrict__ act_row_ptr, const int* __restrict__ act_senders,
                                           const char4* __restrict__ act_code, int* __restrict__ act_receivers,
                                           float4* __restrict__ act_vec_len, int* __restrict__ act_slab,
                                           float2* __restrict__ act_t_sx) {
    const int tid = blockIdx.x * blockDim.x + threadIdx.x;
    const int i = tid >> 5, lane = tid & 31;
    if (i >= N) return;
    const double rx = pos64[i * 3 + 0], ry = pos64[i * 3 + 1], rz = pos64[i * 3 + 2];
    const int sp_i = species[i];
    for (int k = act_row_ptr[i] + lane; k < act_row_ptr[i + 1]; k += 32) {
        const int s = act_senders[k];
        const char4 c = act_code[k];
        const double sx = (double)c.x, sy = (double)c.y, sz = (double)c.z;
        const double vx = (rx - pos64[s * 3 + 0]) + tile_shift_comp(cell, sx, sy, sz, 0);
        const double vy = (ry - pos64[s * 3 + 1]) + tile_shift_comp(cell, sx, sy, sz, 1);
        const double vz = (rz - pos64[s * 3 + 2]) + tile_shift_comp(cell, sx, sy, sz, 2);
        const float fx = (float)vx, fy = (float)vy, fz = (float)vz;
        const float len = sqrtf(fx * fx + fy * fy + fz * fz);
        const float4 vl = make_float4(fx, fy, fz, len);
        const int sp_s = species[s];
        const int p_slab = pair_sym ? loup::sym_pair(sp_s, sp_i, S) : (sp_s * S + sp_i);
        act_receivers[k] = i;
        act_vec_len[k] = vl;
        int iv;
        float t, sx_inv;
        locate_spline(grid, vl.w, iv, t, sx_inv);
        act_slab[k] = p_slab * grid.total_intervals + iv;
        act_t_sx[k] = make_float2(t, (vl.w >= grid.starts[0]) ? sx_inv : -sx_inv);
    }
}
}  // extern "C++"

static bool host_compact() {
    const char* e = std::getenv("LOUP_TILE_HOST_COMPACT");
    return !(e && e[0] && std::atoi(e) == 0);
}

// O32: device lists in the same compact form (senders and integer image shifts on the device, decoded per
// compaction); LOUP_TILE_DEVICE_COMPACT=0 keeps the full form (kTileFullEdgeB) there
static bool device_compact() {
    const char* e = std::getenv("LOUP_TILE_DEVICE_COMPACT");
    return !(e && e[0] && std::atoi(e) == 0);
}

// Sets the workspace up as `t`'s domain, builds its list and keeps a copy of it in `out`.
static int build_tile_list(LoupHandle* h, const TileDomain& t, const double* positions, TileList& out,
                           bool host_lists, DeviceArena* arena) {
    if (reshape_domain(h, t.n_local, t.n_ghost(), t.z.data()) != 0) return -1;
    if (upload_positions(h, t.place.data(), t.box) < 0) return -1;
    if (rebuild_neighbors(h) != 0) return -1;
    const int rows = (int)t.atom.size(), N = t.n_local, E = h->E_skin;
    out.n_local = N; out.rows = rows; out.E = E; out.e0 = h->e0_total;
    std::copy(t.box, t.box + 9, out.box);
    std::copy(t.org, t.org + 3, out.org);
    out.perm = h->perm; out.species_start = h->species_start; out.species_count = h->species_count;
    auto keep = [&](SlotView& g, const void* src, size_t bytes) -> int {
        if (bytes) CUDA_CHECK(cudaMemcpyAsync(g.p, src, bytes, cudaMemcpyDeviceToDevice, h->stream));
        return 0;
    };
    // O32: compact on the device too, where every shift fits: the codes first into a scratch buffer, then the tile's
    // one allocation in the form found
    DeviceBufferGuard dcode;
    bool dev_compact = false;
    if (!host_lists && device_compact() && E > 0) {
        CUDA_CHECK(cudaMalloc(&dcode.p, (size_t)E * 4));
        CUDA_CHECK(cudaMemsetAsync(h->d_order_err, 0, sizeof(int), h->stream));
        tile_encode_edges_kernel<<<(E + 255) / 256, 256, 0, h->stream>>>(
            E, h->cell, h->d_shift_cart, static_cast<char4*>(dcode.p), h->d_order_err);
        int bad = 0;
        CUDA_CHECK(cudaMemcpyAsync(&bad, h->d_order_err, sizeof(int), cudaMemcpyDeviceToHost, h->stream));
        CUDA_CHECK(cudaStreamSynchronize(h->stream));
        dev_compact = !bad;
    }
    const size_t eb = (size_t)E * sizeof(int), row_b = (size_t)rows * sizeof(int);
    const bool full_dev = !host_lists && !dev_compact;
    if (!alloc_slot(out.blk, {{&out.species, row_b},
                              {&out.pos, (size_t)rows * 3 * sizeof(double)},
                              {&out.row_ptr, (size_t)(N + 1) * sizeof(int)},
                              {&out.row_atom, row_b},
                              {&out.offset, (size_t)rows * 3 * sizeof(double)},
                              {&out.senders, (dev_compact || full_dev) ? eb : 0},
                              {&out.ccode, dev_compact ? eb : 0},
                              {&out.shift, full_dev ? (size_t)E * 3 * sizeof(double) : 0}},
                    arena)) {
        (void)cudaGetLastError();
        loup::set_error("tile list: out of device memory");
        return -1;
    }
    if (keep(out.species, h->d_species, row_b) || keep(out.pos, h->d_pos64, (size_t)rows * 3 * sizeof(double)) ||
        keep(out.row_ptr, h->d_row_ptr, (size_t)(N + 1) * sizeof(int)))
        return -1;
    if (dev_compact) {
        if (keep(out.ccode, dcode.p, eb) || keep(out.senders, h->d_senders, eb)) return -1;
        out.h_csnd = static_cast<const int*>(out.senders.p);
        out.h_ccode = static_cast<const char4*>(out.ccode.p);
        out.compact = true;
    }
    if (host_lists && host_compact() && E > 0) {  // O32: the compact form where every shift fits
        DeviceBufferGuard code;
        CUDA_CHECK(cudaMalloc(&code.p, (size_t)E * 4));
        CUDA_CHECK(cudaMemsetAsync(h->d_order_err, 0, sizeof(int), h->stream));
        tile_encode_edges_kernel<<<(E + 255) / 256, 256, 0, h->stream>>>(E, h->cell, h->d_shift_cart,
                                                                          static_cast<char4*>(code.p), h->d_order_err);
        int bad = 0;
        CUDA_CHECK(cudaMemcpyAsync(&bad, h->d_order_err, sizeof(int), cudaMemcpyDeviceToHost, h->stream));
        CUDA_CHECK(cudaStreamSynchronize(h->stream));
        if (!bad) {
            const size_t e = (size_t)E;
            if (!pinned_take(h, out.host_edges, e * 8, true)) {
                loup::set_error("tile list: %.2f GB of pinned host memory not available", e * 8 / 1e9);
                return -1;
            }
            void* dev = nullptr;
            CUDA_CHECK(cudaHostGetDevicePointer(&dev, out.host_edges.p, 0));
            char* hp = static_cast<char*>(out.host_edges.p);
            const char* dp = static_cast<const char*>(dev);
            out.h_csnd = reinterpret_cast<const int*>(dp);
            out.h_ccode = reinterpret_cast<const char4*>(dp + e * 4);
            CUDA_CHECK(cudaMemcpyAsync(hp, h->d_senders, e * 4, cudaMemcpyDeviceToHost, h->stream));
            CUDA_CHECK(cudaMemcpyAsync(hp + e * 4, code.p, e * 4, cudaMemcpyDeviceToHost, h->stream));
            CUDA_CHECK(cudaStreamSynchronize(h->stream));  // `code` goes out of scope
            out.compact = true;
        }
    }
    if (out.compact) {
    } else if (host_lists) {
        // shifts first (8-byte aligned), then the senders
        const size_t e = (size_t)E;
        if (!pinned_take(h, out.host_edges, e * kTileFullEdgeB, true)) {
            loup::set_error("tile list: %.2f GB of pinned host memory not available", e * kTileFullEdgeB / 1e9);
            return -1;
        }
        void* dev = nullptr;
        CUDA_CHECK(cudaHostGetDevicePointer(&dev, out.host_edges.p, 0));
        char* hp = static_cast<char*>(out.host_edges.p);
        char* dp = static_cast<char*>(dev);
        out.h_shift = reinterpret_cast<double*>(dp);
        out.h_senders = reinterpret_cast<int*>(dp + e * 24);
        if (E) {
            CUDA_CHECK(cudaMemcpyAsync(hp, h->d_shift_cart, e * 24, cudaMemcpyDeviceToHost, h->stream));
            CUDA_CHECK(cudaMemcpyAsync(hp + e * 24, h->d_senders, e * 4, cudaMemcpyDeviceToHost, h->stream));
        }
    } else if (keep(out.senders, h->d_senders, (size_t)E * sizeof(int)) ||
               keep(out.shift, h->d_shift_cart, (size_t)E * 3 * sizeof(double))) {
        return -1;
    }
    std::vector<int> map(rows);
    std::vector<double> offset((size_t)rows * 3);
    for (int dst = 0; dst < rows; ++dst) {
        const int src = h->perm[dst];
        map[dst] = t.atom[src];
        for (int c = 0; c < 3; ++c)
            offset[(size_t)dst * 3 + c] = t.place[(size_t)src * 3 + c] - positions[(int64_t)map[dst] * 3 + c];
    }
    CUDA_CHECK(cudaMemcpyAsync(out.row_atom.p, map.data(), (size_t)rows * sizeof(int), cudaMemcpyHostToDevice,
                               h->stream));
    out.h_row_atom = map;
    CUDA_CHECK(cudaMemcpyAsync(out.offset.p, offset.data(), offset.size() * sizeof(double), cudaMemcpyHostToDevice,
                               h->stream));
    CUDA_CHECK(cudaStreamSynchronize(h->stream));  // `map` and `offset` go out of scope
    return 0;
}

// Puts a kept tile list back into the workspace: device-to-device copies on the stream, no host sync.
// The handle's own list buffers, saved while restore_tile_list points it at tiles' buffers, and given back at scope
// exit (also on an error path), before anything that rebuilds a list or frees the handle's buffers can run.
struct TileListBorrow {
    LoupHandle* h;
    int *species, *row_ptr, *senders;
    double *pos64, *shift_cart;
    int *act_row_ptr, *act_senders, *act_receivers, *act_slab;
    float4* act_vec_len;
    float2* act_t_sx;
    explicit TileListBorrow(LoupHandle* h_)
        : h(h_), species(h_->d_species), row_ptr(h_->d_row_ptr), senders(h_->d_senders),
          pos64(h_->d_pos64), shift_cart(h_->d_shift_cart),
          act_row_ptr(h_->d_act_row_ptr), act_senders(h_->d_act_senders), act_receivers(h_->d_act_receivers),
          act_slab(h_->d_act_slab), act_vec_len(h_->d_act_vec_len),
          act_t_sx(h_->d_act_t_sx) {}
    // The handle's own active-edge buffers (a tile without kept active edges compacts into them)
    void own_active() const {
        h->d_act_row_ptr = act_row_ptr;
        h->d_act_senders = act_senders;
        h->d_act_receivers = act_receivers;
        h->d_act_slab = act_slab;
        h->d_act_vec_len = act_vec_len;
        h->d_act_t_sx = act_t_sx;
    }
    ~TileListBorrow() {
        own_active();
        h->d_species = species;
        h->d_row_ptr = row_ptr;
        h->d_senders = senders;
        h->d_pos64 = pos64;
        h->d_shift_cart = shift_cart;
        h->nl_valid = false;  // the handle's own buffers hold whatever list was built last, not the last tile's
    }
    TileListBorrow(const TileListBorrow&) = delete;
    TileListBorrow& operator=(const TileListBorrow&) = delete;
};

static int restore_tile_list(LoupHandle* h, const TileList& t) {
    h->N = t.n_local;
    h->n_ghost = t.rows - t.n_local;
    h->perm = t.perm;
    h->species_start = t.species_start;
    h->species_count = t.species_count;
    h->e0_total = t.e0;
    loup::compute_cell_mat(t.box, h->cell, h->cell_vol, h->cell_heights);
    memcpy(h->cell_in, t.box, sizeof(h->cell_in));
    // The sweeps only read the list, so the handle points at the tile's own buffers (TileListBorrow gives the
    // handle its buffers back when the tiled call ends) instead of copying them in: about 170 MB per sweep and tile
    // at 65,536 receivers (O31 profile).
    h->d_species = static_cast<int*>(t.species.p);
    h->d_pos64 = static_cast<double*>(t.pos.p);
    h->d_row_ptr = static_cast<int*>(t.row_ptr.p);
    const bool host = t.host_edges.p != nullptr;  // O31: only the active-edge compaction reads these
    h->d_senders = host ? t.h_senders : static_cast<int*>(t.senders.p);
    h->d_shift_cart = host ? t.h_shift : static_cast<double*>(t.shift.p);
    // a compact list's are decoded into the handle's own buffers before the compaction (the tiled call's stage_use)
    h->E_skin = t.E;
    h->nl_valid = true;
    h->forces_current = false;
    CUDA_CHECK(cudaMemsetAsync(h->d_forces_f64, 0, (size_t)t.rows * 3 * sizeof(double), h->stream));
    return 0;
}

// Tiles are domains: their systems do not fold (set_system_impl), so only the long range rules the sweeps out.
static bool can_tile(const LoupHandle* h) { return h->gen && h->gen->sweeps_possible() && h->gen->n_layers() >= 2; }

// loup_plan_execution (see the header).
// The wavefront (S5-T08) for a tiled call of n atoms: LOUP_TILE_WAVEFRONT=1|0 forces it on or off, else the
// wavefront mode asks for it, else it is on from 2^20 atoms (with 12 layers of tiles along the first axis, which only
// the plan can tell: wave_pool_rows). Two-layer models only.
static bool wave_try(const LoupHandle* h, int64_t n_atoms, bool* forced) {
    const char* env = std::getenv("LOUP_TILE_WAVEFRONT");
    const int ask = (env && env[0]) ? std::atoi(env) : (h->exec_mode == LOUP_EXEC_WAVEFRONT ? 1 : -1);
    *forced = ask == 1;
    return h->gen->n_layers() == 2 && (ask == 1 || (ask < 0 && n_atoms >= (1 << 20)));
}

// The row pool of the wavefront on the plan of `receivers` per tile, or -1 when that plan gets the plain sweeps.
// block_rows (O32, the pool in host memory): the rows of its block form, a block of the most locals per tile in flight.
static int64_t wave_pool_rows(const double* positions, int n_atoms, const double* cell, int receivers, double reach,
                              bool forced, int64_t* block_rows = nullptr) {
    const loup::TilePlan plan = loup::plan_tiles(positions, n_atoms, cell, receivers, 0, nullptr, reach, nullptr, reach);
    const int64_t T = plan.tiles();
    if (!(forced || plan.grid[0] >= 12) || T < 2) return -1;
    std::vector<int64_t> needs_ptr, needs, ready, counts((size_t)T);
    int64_t max_local = 0;
    for (int64_t k = 0; k < T; ++k) {
        counts[(size_t)k] = plan.local_ptr[(size_t)k + 1] - plan.local_ptr[(size_t)k];
        max_local = std::max(max_local, counts[(size_t)k]);
    }
    loup::tile_dependencies(plan, needs_ptr, needs, ready);
    int64_t peak = 0;
    const std::vector<loup::SweepStep> steps =
        loup::wavefront_schedule(T, needs_ptr.data(), needs.data(), ready.data(), counts.data(), 1, &peak);
    if (block_rows) {
        int64_t open = 0, most = 0;
        for (const loup::SweepStep& s : steps) {
            open += s.sweep == 1 ? 1 : s.sweep == 3 ? -1 : 0;
            most = std::max(most, open);
        }
        *block_rows = most * max_local;
    }
    return peak;
}

// tile-plan-exact: the tiles a call at `receivers` will make, as far as its memory goes: how many, the widest
// domain (locals and ghost candidates: the workspace's rows), the most locals in one, every tile's rows together,
// and with the wavefront the row pool and the most tiles in flight at once (those hold slots of kept active edges).
struct TileShape {
    int64_t tiles = 0, widest_rows = 0, max_local = 0, rows_total = 0, in_flight = 0, pool_rows = -1;
    int64_t windows = 0;  // the host state's gradient windows (alias), each of max_local rows: the call's schedule
    bool wave = false;
};
static int tile_shape(const double* positions, int n_atoms, const double* cell, int receivers, double reach,
                      bool wave_on, bool wave_forced, bool count_windows, TileShape* out) {
    loup::TilePlan plan;
    try {
        plan = loup::plan_tiles(positions, n_atoms, cell, receivers, 0, nullptr, reach, nullptr, wave_on ? reach : 0.0);
    } catch (const std::exception& e) {
        loup::set_error("tile plan: %s", e.what());
        return -1;
    }
    TileShape s;
    s.tiles = plan.tiles();
    std::vector<int64_t> counts((size_t)s.tiles);
    for (int64_t k = 0; k < s.tiles; ++k) {
        const int64_t nl = plan.local_ptr[(size_t)k + 1] - plan.local_ptr[(size_t)k];
        const int64_t ng = plan.ghost_ptr[(size_t)k + 1] - plan.ghost_ptr[(size_t)k];
        counts[(size_t)k] = nl;
        s.widest_rows = std::max(s.widest_rows, nl + ng);
        s.max_local = std::max(s.max_local, nl);
        s.rows_total += nl + ng;
    }
    s.in_flight = s.tiles;
    s.wave = wave_on && (wave_forced || plan.grid[0] >= 12) && s.tiles >= 2;  // the tiled call's rule
    if (s.wave) {
        std::vector<int64_t> needs_ptr, needs, ready;
        loup::tile_dependencies(plan, needs_ptr, needs, ready);
        int64_t peak = 0, open = 0, most = 0;
        const std::vector<loup::SweepStep> steps =
            loup::wavefront_schedule(s.tiles, needs_ptr.data(), needs.data(), ready.data(), counts.data(), 1, &peak);
        for (const loup::SweepStep& st : steps) {
            open += st.sweep == 1 ? 1 : st.sweep == 3 ? -1 : 0;
            most = std::max(most, open);
        }
        s.pool_rows = peak;
        s.in_flight = most;
    }
    if (count_windows && !s.wave && s.tiles >= 1) {
        // The tiled call's order of the last sweeps and its windows (the host state's alias): block j's gradients
        // sit in a window from the first to the last of {j} and the tiles that hold ghosts of j; a window is taken
        // again once its block has folded. From the plan's candidates, a superset of the kept ghosts.
        const int64_t T = s.tiles;
        std::vector<int64_t> needs_ptr, needs, ready;
        loup::tile_dependencies(plan, needs_ptr, needs, ready);
        std::vector<std::vector<int>> dep((size_t)T);
        std::vector<int64_t> rdy((size_t)T), pos((size_t)T);
        std::vector<int> ord((size_t)T);
        for (int64_t k = 0; k < T; ++k) {
            ord[(size_t)k] = (int)k;
            rdy[(size_t)k] = k;
            for (int64_t i = needs_ptr[(size_t)k]; i < needs_ptr[(size_t)k + 1]; ++i) {
                const int64_t j = needs[(size_t)i];
                if (j == k) continue;
                dep[(size_t)j].push_back((int)k);
                rdy[(size_t)k] = std::max(rdy[(size_t)k], j);
            }
        }
        std::stable_sort(ord.begin(), ord.end(), [&](int x, int y) { return rdy[(size_t)x] < rdy[(size_t)y]; });
        for (int64_t q = 0; q < T; ++q) pos[(size_t)ord[(size_t)q]] = q;
        std::vector<std::vector<int>> folds((size_t)T), opens((size_t)T);
        std::vector<int> win_of((size_t)T, -1), free_w;
        for (int64_t j = 0; j < T; ++j) {
            int64_t first = pos[(size_t)j], last = pos[(size_t)j];
            for (int k : dep[(size_t)j]) {
                first = std::min(first, pos[(size_t)k]);
                last = std::max(last, pos[(size_t)k]);
            }
            if (counts[(size_t)j] == 0) continue;
            folds[(size_t)last].push_back((int)j);
            if (first < last) opens[(size_t)first].push_back((int)j);
        }
        int n_win = 0;
        for (int64_t q = 0; q < T; ++q) {
            for (int j : folds[(size_t)q])
                if (win_of[(size_t)j] >= 0) free_w.push_back(win_of[(size_t)j]);
            for (int j : opens[(size_t)q]) {
                if (free_w.empty()) free_w.push_back(n_win++);
                win_of[(size_t)j] = free_w.back();
                free_w.pop_back();
            }
        }
        s.windows = n_win;
    }
    *out = s;
    return 0;
}

static int plan_execution_impl(LoupHandle* h, int n_atoms, const int* atomic_numbers, const double* positions,
                               const double* cell, double skin, LoupMemoryPlan* out) {
    if (!h) return -1;
    if (!out) { loup::set_error("out is NULL"); return -1; }
    if (n_atoms <= 0 || !atomic_numbers || !positions || !cell) {
        loup::set_error("n_atoms must be positive and atomic_numbers, positions and cell given");
        return -1;
    }
    if (!(skin >= 0.0) || !std::isfinite(skin)) { loup::set_error("skin must be finite and not negative"); return -1; }
    if ((h->exec_mode == LOUP_EXEC_TILED || h->exec_mode == LOUP_EXEC_WAVEFRONT) && !can_tile(h)) {
        loup::set_error("the tiled mode needs a bundle of the generic path without long range and with two or more "
                        "layers");
        return -1;
    }
    if (h->exec_mode == LOUP_EXEC_WAVEFRONT && h->gen->n_layers() != 2) {
        loup::set_error("the wavefront mode needs a model of two layers (this one has %d); use the tiled mode",
                        h->gen->n_layers());
        return -1;
    }
    CUDA_CHECK(cudaSetDevice(h->device_id));
    LoupMemoryPlan plan{};
    size_t free_b = 0, total_b = 0;
    if (h->exec_mode == LOUP_EXEC_WHOLE || !can_tile(h)) {  // the whole-system call: asked, or all the bundle has
        CUDA_CHECK(device_memory(&free_b, &total_b));
        plan.free_bytes = free_b;
        plan.mode = LOUP_EXEC_WHOLE;
        *out = plan;
        return 0;
    }
    // The probe: the tile with the most rows of a plan at 4,096 receivers, set up and listed on the handle.
    constexpr int kMinReceivers = 4096;
    const double r_list = (double)h->gen->r_max() + skin;
    const int c0 = std::min(kMinReceivers, n_atoms);
    loup::TilePlan tp;
    try {
        tp = loup::plan_tiles(positions, n_atoms, cell, c0, 0, nullptr, r_list + 1e-3, nullptr);
    } catch (const std::exception& e) {
        loup::set_error("tile plan: %s", e.what());
        return -1;
    }
    int64_t widest = 0, widest_rows = -1;
    for (int64_t k = 0; k < tp.tiles(); ++k) {
        const int64_t rows = tp.local_ptr[k + 1] - tp.local_ptr[k] + tp.ghost_ptr[k + 1] - tp.ghost_ptr[k];
        if (rows > widest_rows) { widest_rows = rows; widest = k; }
    }
    TileDomain d;
    host_domain(tp, widest, atomic_numbers, positions, cell, r_list, d);
    if (set_domain_impl(h, d.n_local, d.n_ghost(), d.z.data(), skin) != 0) return -1;
    h->tile_workspace = true;
    if (upload_positions(h, d.place.data(), d.box) < 0) return -1;
    if (rebuild_neighbors(h) != 0) return -1;
    // Bytes per row (locals and ghosts alike), per edge of capacity, and those that do not scale; kPlanAllowance as
    // in loup_plan_memory.
    constexpr double kPlanAllowance = 64.0 * 1024.0 * 1024.0;
    // tile-shared-layers: a row is counted with every layer's buffers its own, as a whole system has them and as
    // the tile workspace had them when the caps below were measured; the workspace's layers share one arena, so
    // it takes less than the plan counts (OMAT-0 medium a third less). What that leaves goes to the kept slots and
    // to a lower peak. Counting the shared size instead moved device plans to larger caps without room for their
    // slots: 320,000 atoms at fraction 0.5 0.581 -> 0.627 s (ledger tile-shared-layers, with a second variant).
    const double row_b = ((double)h->sys_atom_bytes + (double)h->gen->system_bytes_unshared() +
                          (double)h->cub_tmp_bytes) / h->atom_cap;
    const double edge_b = ((double)h->sys_edge_bytes + (double)h->gen->edge_bytes()) / h->E_cap;
    const double fixed_b = (double)h->sys_fixed_bytes + (double)h->weight_copy_bytes + kPlanAllowance;
    // What a first call needs beyond what it keeps: the GEMM timing's scratch output, as large as the model's
    // largest buffer, and its cache-flush buffer (sgemm_rm's autotune). 121,945 atoms whole: 0.9 GiB above the
    // system's 11.2 GiB in the first call (NVML, 18 November 2026).
    const double scratch_row_b = (double)h->gen->largest_buffer_bytes() / h->atom_cap;
    const double scratch_fixed_b = 2.0 * (double)std::max(h->l2_bytes, 1 << 20);
    const double epl = (double)h->E_skin / d.n_local;  // edges per receiver
    auto edge_cap = [](double e) { return std::max(e + std::floor(e / 4.0) + 1024.0, 4096.0); };
    CUDA_CHECK(device_memory(&free_b, &total_b));
    // LOUP_DEBUG_PLAN_FREE=<MiB> (tests of the plan's thresholds): at most that much counts as free here. The true
    // figure moves by MB with what other programs hold, and a threshold is a fraction of it found to 0.1%.
    if (const char* e = std::getenv("LOUP_DEBUG_PLAN_FREE"))
        free_b = std::min(free_b, (size_t)std::max(0LL, std::atoll(e)) << 20);
    const double budget = (double)free_b + handle_system_bytes(h);  // the probe's buffers go when the call sets up
    const double allowed = h->exec_fraction * budget;
    const double n = n_atoms;
    // The tiled call: the whole system's layer outputs, their gradients and the forces; each tile's kept list
    // (rows: species, positions, row map; edges: senders, receivers, pairs, shifts); the workspace for the widest
    // domain, whose ghost rows grow with a tile's surface; the adjoint buffers.
    // With the wavefront (S5-T08) the layer outputs and their gradients take the schedule's row pool instead of the
    // whole system, and each kept row a pool row more.
    const int L = h->gen->n_layers();
    double layer_per_atom = 0.0, adj_per_row = 0.0;
    bool alias_plan = L == 2;  // O32: the host state's dx on x's rows (the call's rule: pipeline, two layers)
    if (const char* e = std::getenv("LOUP_TILE_HOST_PIPE")) alias_plan = alias_plan && std::atoi(e) != 0;
    if (const char* e = std::getenv("LOUP_TILE_HOST_ALIAS")) alias_plan = alias_plan && std::atoi(e) != 0;
    for (int l = 0; l < 4; ++l) {
        double widest_l = 0.0;
        for (int t = 0; t + 1 < L; ++t)
            if (l <= h->gen->out_lmax(t)) {
                const double w = (double)(2 * l + 1) * h->gen->out_width(t);
                layer_per_atom += 2.0 * w * sizeof(float);
                widest_l = std::max(widest_l, w);
            }
        adj_per_row += widest_l * sizeof(float);
    }
    // The whole system: every layer's own buffers, less the non-last layers' outputs and their gradients where the
    // skip-chain fold is built (a whole system folds and never forms them: 4% of OMAT-0 medium's rows, 7% of
    // OMOL-0's). Measured against the system itself: within 1% from 20,000 atoms (status §6.35).
    const double whole = (row_b - (h->gen->chain_fold_built() ? layer_per_atom : 0.0)) * n +
                         edge_b * edge_cap(n * epl) + fixed_b;
    // O32: with the layer state in host memory the device holds four ring slots of a layer's rows instead
    double ring_per_row = 0.0;
    for (int t = 0; t + 1 < L; ++t) {
        double w = 0.0;
        for (int l = 0; l <= h->gen->out_lmax(t); ++l) w += (double)(2 * l + 1) * h->gen->out_width(t) * sizeof(float);
        ring_per_row = std::max(ring_per_row, w);
    }
    bool wave_forced = false;
    const bool wave = wave_try(h, n_atoms, &wave_forced);
    const double ghost0 = (double)widest_rows - c0;
    // O32: the device lists' edge arrays per edge: 8 B compact (10% over, as the host lists'), else kTileFullEdgeB
    const double dev_edge_b = device_compact() ? 8.0 * 1.1 : (double)kTileFullEdgeB;
    double hstate_host = 0.0;  // the host memory of the layer state and its staging at the last cap tried
    auto tiled_at = [&](double c, bool host, double& global, double& ws, int hstate = 0) -> int {
        c = std::min(c, n);
        const double rows = c + ghost0 * std::pow(c / c0, 2.0 / 3.0), T = std::ceil(n / c);
        ws = row_b * rows + edge_b * edge_cap(c * epl) + fixed_b + adj_per_row * rows;
        if (hstate == 2) {  // O32: the wavefront's row pool in host memory, as blocks of a tile's locals (no pipeline)
            int64_t pool = -1, block_rows = 0;
            try {
                pool = wave_pool_rows(positions, n_atoms, cell, (int)c, r_list + 1e-3, wave_forced, &block_rows);
            } catch (const std::exception& e) {
                loup::set_error("tile wavefront: %s", e.what());
                return -1;
            }
            if (pool < 0) {  // the plain sweeps at this cap: not this step
                hstate_host = 0.0;
                global = std::numeric_limits<double>::infinity();
                return 0;
            }
            hstate_host = (double)block_rows * layer_per_atom + 2.0 * ring_per_row * rows;
            global = n * 3.0 * sizeof(double) + 32.0 * (n + T * (rows - c)) + 4.0 * (n + T) +
                     (host ? 0.0 : dev_edge_b * n * epl);
            return 0;
        }
        if (hstate) {  // O32: the layer state in host memory, four ring slots on the device (HostPipe)
            ws += 4.0 * ring_per_row * rows;
            // (the alias: its windows hold up to every block's gradients at once in a grid of tiles, 1,080,000 atoms
            // in 27 tiles 71%, 2,560,000 in 64 nearly all of them, so the search counts both arrays; the plan's own
            // figure follows the call's window schedule: tile_shape)
            hstate_host = n * layer_per_atom + 6.0 * ring_per_row * rows;
            global = n * 3.0 * sizeof(double) + 32.0 * (n + T * (rows - c)) + 4.0 * (n + T) +
                     (host ? 0.0 : dev_edge_b * n * epl);
            return 0;
        }
        // with host lists (O31) the edges' arrays leave the device
        double kept = 32.0 * (n + T * (rows - c)) + 4.0 * (n + T) + (host ? 0.0 : dev_edge_b * n * epl);
        double layer_rows = n;
        if (wave) {
            int64_t pool = -1;
            try {
                pool = wave_pool_rows(positions, n_atoms, cell, (int)c, r_list + 1e-3, wave_forced);
            } catch (const std::exception& e) {
                loup::set_error("tile wavefront: %s", e.what());
                return -1;
            }
            if (pool >= 0) {
                layer_rows = (double)pool;
                kept += 4.0 * (n + T * (rows - c));
            }
        }
        global = n * 3.0 * sizeof(double) + layer_rows * layer_per_atom + kept;
        return 0;
    };
    static const int kCaps[] = {65536, 49152, 32768, 24576, 16384, 12288, 8192, 6144, 4096};
    // O31 (S5-T07): the lists' edge arrays go to pinned host memory only when no cap fits with them on the device,
    // and only within half of the host memory available now (MemAvailable); LOUP_TILE_HOST_LISTS=1|0 forces it.
    const double host_need = (host_compact() ? 8.0 : (double)kTileFullEdgeB) * n * epl * 1.1;  // O32: compact unless turned off
    double host_lists_b = host_need;  // the plan's figure of the lists' edges in host memory (exact below)
    double host_avail = 0.0;
    {
        FILE* f = std::fopen("/proc/meminfo", "r");
        char line[256];
        while (f && std::fgets(line, sizeof(line), f)) {
            long long kb = 0;
            // O32: with the handle's spare pinned buffers (the next state's set-up takes or frees them)
            if (std::sscanf(line, "MemAvailable: %lld kB", &kb) == 1) {
                host_avail = (double)kb * 1024.0 + h->pinned_spare.bytes();
                break;
            }
        }
        if (f) std::fclose(f);
        if (host_avail <= 0.0) host_avail = (double)sysconf(_SC_AVPHYS_PAGES) * (double)sysconf(_SC_PAGESIZE);
    }
    int host_force = -1;
    if (const char* e = std::getenv("LOUP_TILE_HOST_LISTS")) host_force = std::atoi(e) != 0 ? 1 : 0;
    const bool host_ok = host_force == 1 || (host_force < 0 && host_need <= 0.5 * host_avail);
    // O32: the layer state in host memory too (plain order), only when no cap fits with the lists there alone, and
    // the lists, the state and its staging within two thirds of the available host memory (kHostStateShare; 60% of a
    // count that left the alias windows out until tile-plan-exact: up to 96% in fact); LOUP_TILE_HOST_STATE=1|0 forces
    constexpr double kHostStateShare = 2.0 / 3.0;
    int hs_force = -1;
    if (const char* e = std::getenv("LOUP_TILE_HOST_STATE")) hs_force = std::atoi(e) != 0 ? 1 : 0;
    // The host state's form (O32): 1 the plain order's (whole system, pipelined), 2 the wavefront's row pool as blocks
    // (when the wavefront applies: the plain order's first unless the wavefront is forced)
    const int hs_first = wave && wave_forced ? 2 : 1;
    int hstate = hs_force == 1 ? hs_first : 0;
    int cap = 0;
    bool host = host_force == 1;
    double global = 0.0, ws = 0.0;
    // O32: compact slots of kept active edges for every tile in flight (the plain order: all), 8 B per list edge; each
    // slot holds the largest tile's list, so the slots of all tiles come to about 1.4x the edges' 8 B (2,560,000 atoms
    // at cap 65,536: 54 slots of 53 MB for 2,039 MB of compact edges); 1.5x with margin
    const double slot_room = 1.5 * 8.0 * n * epl;
    double shown_g = 0.0, shown_w = 0.0;  // the last estimate tried (for the refusal's message)
    bool host_short = false;              // a host state step was left out for the host memory
    auto fits = [&](double c) {  // the tile's own list stays within the edge limit, with 10% for its densest region
        if (std::isfinite(global)) { shown_g = global; shown_w = ws; }
        return global + ws <= allowed && std::min(c, n) * epl * 1.1 <= (double)h->edge_limit;
    };
    auto hs_room = [&](double c, int form) {  // the host side of the host state's step at cap c
        double g = 0.0, w = 0.0;
        tiled_at(c, true, g, w, form);
        const bool ok = host_need + hstate_host <= kHostStateShare * host_avail;
        host_short |= !ok;
        return ok;
    };
    if (h->exec_receivers > 0) {
        cap = h->exec_receivers;
        if (tiled_at(cap, host, global, ws, hstate) != 0) return -1;
        if (!host && !fits(cap) && host_ok && host_force != 0) {
            host = true;
            if (tiled_at(cap, host, global, ws, hstate) != 0) return -1;
        }
        if (!hstate && !fits(cap) && hs_force != 0)
            for (int form = hs_first; form <= (wave ? 2 : 1); ++form) {
                if (hs_force != 1 && !hs_room(cap, form)) continue;
                double g = 0.0, w = 0.0;
                if (tiled_at(cap, host_force != 0, g, w, form) != 0) return -1;
                if (!std::isfinite(g)) continue;  // the wavefront does not apply at this cap
                host = host_force != 0;
                hstate = form;
                global = g;
                ws = w;
                if (fits(cap)) break;
            }
    } else {
        // pass 0: everything on the device; 1: the lists in host memory; 2: the lists and the layer state there
        // (plain order); 3: the lists and the wavefront's row pool there
        const int first = hstate ? hstate + 1 : host ? 1 : 0;
        for (int pass = first; pass < 4 && cap == 0; ++pass) {
            if (pass == 1 && !(host_ok && host_force != 0)) continue;
            if (pass >= 2 && hs_force == 0) break;
            if (pass == 2 && hs_first == 2) continue;
            if (pass == 3 && !wave) break;
            host = pass >= 1 ? host_force != 0 : false;
            hstate = pass >= 2 ? pass - 1 : 0;
            // the plain host state: the largest cap that leaves compact slots room for every tile (slot_room), unless
            // that is more than 4x below the largest cap that fits at all (5,000,000 atoms at fraction 0.5: slot room
            // at 4,096, 1,362 tiles, 11.24 s; 32,768 fits, 216 tiles, 10.44 s at the same peak; where the slot room
            // costs 1.3x-2x in cap the two tie: tile-slot-room-limit, status §6.34); other passes: the largest that fits
            int any = 0, with_slots = 0;
            for (int c : kCaps) {
                if (pass >= 2 && hs_force != 1 && !hs_room(c, hstate)) continue;
                if (tiled_at(c, host, global, ws, hstate) != 0) return -1;
                if (!fits(c)) continue;
                if (!any) any = c;
                if (pass != 2 || global + ws + slot_room <= allowed) {
                    with_slots = c;
                    break;
                }
            }
            const int pick = with_slots && 4 * with_slots >= any ? with_slots : any;
            if (pick && tiled_at(pick, host, global, ws, hstate) != 0) return -1;
            cap = pick;
        }
        // O32: a device plan in small tiles loses to the plain host state in tiles four times larger or more with
        // room for the slots (2,560,000 atoms: cap 4,096 on the device 5.73-5.75 s, the host state at 49,152 5.23 s;
        // at 65,536 without slot room 6.49 s; status §6.34), measured with 625 tiles and more only: few tiles keep the
        // device plan
        if (cap > 0 && cap < 16384 && n >= 256.0 * cap && hstate == 0 && hs_force != 0 && hs_first == 1) {
            // at most 8x: at 65,536 the call found no memory left for any slot although the plan's estimate left
            // 4 GB (54 tiles, 6.50 s; the grid fit's split blocks, fixed since by tile-grid-rows: 64 tiles, 5.23 s);
            // 49,152 and 32,768 ran with 64 / 125 slots (5.24 / 5.26 s), 32,768 at the lower peak. Down to 2.5x where
            // nothing from 4x fits: 8,008,065 atoms, device cap 6,144 (2,016 tiles) 17.29 / 17.28 s, the host state
            // at 16,384 (512 tiles) 16.60 / 16.64 s, A B B A (tile-host-state-window, status §6.34)
            for (int c : kCaps) {
                if (c > 8 * cap) continue;
                if (2 * c < 5 * cap) break;
                if (hs_force != 1 && !hs_room(c, 1)) continue;
                double g = 0.0, w = 0.0;
                if (tiled_at(c, host_force != 0, g, w, 1) != 0) return -1;
                if (g + w + slot_room <= allowed && std::min<double>(c, n) * epl * 1.1 <= (double)h->edge_limit) {
                    cap = c;
                    hstate = 1;
                    host = host_force != 0;
                    global = g;
                    ws = w;
                    break;
                }
            }
        }
        // O32: a device plan held below the largest cap by the device memory gives way to the plain host state where
        // that reaches a larger cap (the cap search of pass 2): 1,080,000 atoms at fraction 0.9, device 49,152 (45
        // tiles) 2.285 / 2.271 s, peak 11.6-11.9 GiB, the host state at 65,536 (27 tiles) 2.196 / 2.195 s, 10.56 GiB;
        // at 0.75 / 0.5 -2.7% / -4.7%; 8,008,065 at 0.75 6,144 -> 16,384 17.51 -> 16.68 s. From 2^20 atoms only: below,
        // the host copies cost more than the larger tiles save (320,000 at 0.5 / 0.35 +4.2% / +2.9%, 135,000 at 0.25
        // +10%; at the same cap 320,000 at 0.9: 0.613 against 0.593 s): tile-host-state-larger-cap
        if (cap > 0 && cap < kCaps[0] && n >= 1048576.0 && hstate == 0 && hs_force != 0 && hs_first == 1) {
            int any = 0, with_slots = 0;
            double g = 0.0, w = 0.0;
            for (int c : kCaps) {
                if (c <= cap) break;
                if (hs_force != 1 && !hs_room(c, 1)) continue;
                if (tiled_at(c, host_force != 0, g, w, 1) != 0) return -1;
                if (!(g + w <= allowed && std::min<double>(c, n) * epl * 1.1 <= (double)h->edge_limit)) continue;
                if (!any) any = c;
                if (g + w + slot_room <= allowed) {
                    with_slots = c;
                    break;
                }
            }
            const int pick = with_slots && 4 * with_slots >= any ? with_slots : any;
            if (pick > cap) {
                if (tiled_at(pick, host_force != 0, g, w, 1) != 0) return -1;
                cap = pick;
                hstate = 1;
                host = host_force != 0;
                global = g;
                ws = w;
            }
        }
    }
    h->tile_host_lists = (cap > 0 && host) ? 1 : 0;
    h->tile_host_state = (cap > 0 && hstate) ? hstate : 0;  // 2: the wavefront's row pool (the call's rule)
    plan.host_lists = h->tile_host_lists;
    plan.host_state = h->tile_host_state ? 1 : 0;
    if (h->tile_host_state) {
        double g = 0.0, w = 0.0;
        tiled_at(cap, host, g, w, h->tile_host_state);
    }
    if (!std::isfinite(global)) global = 0.0;  // the last cap tried had no wavefront (a refusal follows)
    // tile-plan-exact: the cap above comes from estimates with every layer's buffers its own and n / cap tiles, the
    // quantities its rules were measured with. What the plan reports is what the call will hold at that cap: the
    // workspace of the plan's widest tile (its layers share one arena), every tile's kept rows and edges, the
    // whole-system arrays, and the kept slots, staging buffers and layer-0 results by the call's own rules for the
    // memory the rest leaves. Before, plan and peak differed by -45% to +107% (status §6.35).
    bool exact_fits = true;
    for (int cap_i = 0; cap > 0;) {
        TileShape shape;
        const bool wave_on = wave && (hstate == 0 || wave_forced || hstate == 2);
        if (tile_shape(positions, n_atoms, cell, cap, r_list + 1e-3, wave_on, wave_forced, hstate == 1 && alias_plan,
                       &shape) != 0)
            return -1;
        const double row_ws_b = ((double)h->sys_atom_bytes + (double)h->gen->system_bytes() +
                                 (double)h->cub_tmp_bytes) / h->atom_cap;
        const double rows_max = (double)shape.widest_rows, e_max = (double)shape.max_local * epl;
        const bool compact = host ? host_compact() : device_compact();
        const double exact_ws = row_ws_b * rows_max + edge_b * edge_cap(e_max) + fixed_b;
        // kept lists (rows; edges unless they are in host memory), positions, reference positions and forces, the
        // adjoint rows, the layer state (whole system, the wavefront's pool, or the host state's four ring slots)
        double kept = (double)shape.rows_total * (4 + 24 + 4 + 24) + 4.0 * (n + (double)shape.tiles) +
                      3.0 * n * 3.0 * sizeof(double) + adj_per_row * rows_max;
        if (!host) kept += n * epl * (compact ? 8.0 : (double)kTileFullEdgeB);
        if (shape.wave) kept += 4.0 * (double)shape.rows_total;
        if (hstate == 0) kept += (shape.wave ? (double)shape.pool_rows : n) * layer_per_atom;
        else if (hstate == 1) kept += 4.0 * ring_per_row * rows_max;
        // what the call adds within the fraction's reserve (its rules: the slots' set-up in the tiled call)
        // What the call must hold has to fit as well: the search above counts 32 B a kept row and n / cap tiles, and
        // a plan of thousands of tiles holds more (13,720,000 atoms at cap 4,096: 12.4 GiB against 11.8 allowed).
        // Then the next smaller cap, or the refusal below. A cap the caller set is taken as it is.
        exact_fits = exact_ws + kept <= allowed;
        if (!exact_fits && h->exec_receivers <= 0) {
            while (cap_i < (int)(sizeof(kCaps) / sizeof(kCaps[0])) && kCaps[cap_i] >= cap) ++cap_i;
            if (cap_i < (int)(sizeof(kCaps) / sizeof(kCaps[0]))) {
                cap = kCaps[cap_i];
                continue;
            }
            shown_g = kept;
            shown_w = exact_ws;
            cap = 0;
            break;
        }
        const double reserve =
            std::max({256.0 * 1048576.0, 0.02 * (double)total_b, (1.0 - h->exec_fraction) * budget}) +
            scratch_row_b * rows_max + scratch_fixed_b;  // as the call: its first sweeps time GEMMs
        double avail = budget - exact_ws - kept - reserve;
        if (host) {
            const double stage_b = std::max(e_max, 1.0) * (compact ? 8.0 : (double)kTileFullEdgeB);
            bool on = 2.0 * stage_b <= avail;
            if (const char* e = std::getenv("LOUP_TILE_HOST_STAGE")) on = std::atoi(e) != 0;
            if (on) { kept += 2.0 * stage_b; avail -= 2.0 * stage_b; }
        }
        const double slot_b = std::max(e_max, 1.0) * (16 + 3 * 4 + 8) + (rows_max + 1.0) * 4.0;
        const double cslot_b = std::max(e_max, 1.0) * 8.0 + (rows_max + 1.0) * 4.0;
        const double in_flight = (double)shape.in_flight, room = std::max(0.0, avail);
        double want = std::min(in_flight, std::floor(room / slot_b));
        if (compact && want < in_flight)
            want = in_flight * cslot_b <= room
                       ? std::min(in_flight, std::floor((room - in_flight * cslot_b) / (slot_b - cslot_b)))
                       : 0.0;
        const char* keep_env = std::getenv("LOUP_TILE_KEEP_ACTIVE");
        if (keep_env) want = std::min(in_flight, std::max(0.0, (double)std::atoll(keep_env)));
        double want_c = compact ? std::min(in_flight - want, std::floor(std::max(0.0, avail - want * slot_b) / cslot_b))
                                : 0.0;
        if (keep_env) want_c = 0.0;
        if (const char* e = std::getenv("LOUP_TILE_KEEP_COMPACT"))
            want_c = compact ? std::min(in_flight - want, std::max(0.0, (double)std::atoll(e))) : 0.0;
        kept += want * slot_b + want_c * cslot_b;
        if (!shape.wave && h->gen->sweep_keep_layer0()) {
            const double l0_b = (double)h->gen->sweep_keep_floats(n_atoms) * sizeof(float);
            bool on = l0_b <= budget - exact_ws - kept - reserve;
            if (const char* e = std::getenv("LOUP_TILE_KEEP_L0")) on = std::atoi(e) != 0;
            if (on) kept += l0_b;
        }
        ws = exact_ws;
        global = kept;
        // the pinned host memory: the lists' edges; the layer outputs of every atom, their gradients (with the alias:
        // the windows the call's schedule opens), the two staging rows and the pipeline's four
        // (the lists: every edge once, in pinned buffers that get 1/32 of room to grow: tile-pinned-headroom)
        host_lists_b = n * epl * (compact ? 8.0 : (double)kTileFullEdgeB) * (33.0 / 32.0);
        if (hstate == 1)
            hstate_host = 0.5 * n * layer_per_atom +
                          (alias_plan ? (double)shape.windows * (double)shape.max_local * ring_per_row
                                      : 0.5 * n * layer_per_atom) + 6.0 * ring_per_row * rows_max;
        break;
    }
    if (cap == 0) {  // nothing fits by the exact figures: no tiled plan (the refusal below, or the whole system)
        h->tile_host_lists = h->tile_host_state = 0;
        plan.host_lists = plan.host_state = 0;
    }
    plan.host_bytes = (size_t)((h->tile_host_lists ? host_lists_b : 0.0) + (h->tile_host_state ? hstate_host : 0.0));
    plan.whole_bytes = (size_t)whole;
    plan.tiled_global_bytes = (size_t)global;
    plan.tile_workspace_bytes = (size_t)ws;
    plan.free_bytes = free_b;
    plan.receivers = cap;
    const bool whole_fits = whole + scratch_row_b * n + scratch_fixed_b <= allowed && n * epl <= (double)h->edge_limit;
    plan.mode = (h->exec_mode == LOUP_EXEC_AUTO && whole_fits) ? LOUP_EXEC_WHOLE : LOUP_EXEC_TILED;
    if (plan.mode == LOUP_EXEC_TILED && cap == 0) {
        loup::set_error("%d atoms do not fit the device even in tiles of %d receivers: %.2f GiB of state and "
                        "%.2f GiB of workspace against %.2f GiB allowed (%.0f%% of %.2f GiB)%s%s", n_atoms,
                        kMinReceivers, shown_g / 1073741824.0, shown_w / 1073741824.0, allowed / 1073741824.0,
                        100.0 * h->exec_fraction, budget / 1073741824.0,
                        host ? ", with the tile lists' edges in host memory"
                             : (host_force == 0 ? "; host lists are off (LOUP_TILE_HOST_LISTS=0)"
                                                : "; the tile lists' edges would not fit in half of the free host memory"),
                        host_short ? "; the layer state in host memory would exceed two thirds of the available host memory"
                                   : "");
        return -1;
    }
    // A forced host state skips the share check (hs_room), but no plan may pin more than 90% of the available host
    // memory: 8,008,065 atoms with the wavefront's host pool forced planned 42.1 GB against 40.1 GB available, and
    // pinning it took the WSL distro down (status §6.34)
    if (plan.mode == LOUP_EXEC_TILED && (double)plan.host_bytes > 0.9 * host_avail) {
        loup::set_error("%d atoms in tiles of %d receivers need %.1f GB of pinned host memory against %.1f GB "
                        "available (at most 90%%)%s", n_atoms, cap, (double)plan.host_bytes / 1e9, host_avail / 1e9,
                        hs_force == 1 ? "; LOUP_TILE_HOST_STATE=1 forces the host state past the plan's own limit"
                                      : "");
        return -1;
    }
    *out = plan;
    return 0;
}

static int evaluate_tiled_impl(LoupHandle* h, int n_atoms, const int* atomic_numbers, const double* positions,
                               const double* cell, int receivers, double skin, double* out_energy_ev,
                               double* out_forces, double* out_stress, long long* out_tiles,
                               const double* d_positions = nullptr, double* d_out_forces = nullptr,
                               double* out_virial = nullptr) {
    // d_positions / d_out_forces (tiled MD, PLAN.md O31): the positions on the device instead of `positions`, and
    // the forces left on the device. The positions are copied to the host only when the lists are built.
    // out_virial (tiled MD's barostats, LT6 (a)): with out_stress, the virial [xx, xy, xz, yy, yz, zz] (eV).
    if (!h) return -1;
    if (h->disp) {
        loup::set_error("the tiled call has no dispersion term yet (PLAN.md S6-D09)");
        return -1;
    }
    std::vector<double> host_positions;
    if (n_atoms <= 0 || !atomic_numbers || !(positions || d_positions) || !cell) {
        loup::set_error("n_atoms must be positive and atomic_numbers, positions and cell given");
        return -1;
    }
    if (!(h->gen && h->gen->sweeps_possible())) {
        loup::set_error("the tiled call needs a bundle of the generic path without long range");
        return -1;
    }
    const int L = h->gen->n_layers();
    if (L < 2) { loup::set_error("the tiled call needs a model of two or more layers, this one has %d", L); return -1; }
    if (h->exec_mode == LOUP_EXEC_WAVEFRONT && L != 2) {
        loup::set_error("the wavefront mode needs a model of two layers (this one has %d); use the tiled mode", L);
        return -1;
    }
    if (!(skin >= 0.0) || !std::isfinite(skin)) { loup::set_error("skin must be finite and not negative"); return -1; }
    CUDA_CHECK(cudaSetDevice(h->device_id));
    auto blocks = [](int64_t n) { return (unsigned)((n + 255) / 256); };
    auto width = [&](int t, int l) { return (2 * l + 1) * h->gen->out_width(t); };
    // The tiled state of an earlier call stays while the system, cell, skin and cap are the same and no atom has
    // moved skin/2 since its lists were built (S5-T06): only the tiles' positions are refreshed then.
    TiledState* st = h->tiled_state;
    const double r_max = (double)h->gen->r_max(), r_list = r_max + skin;
    const bool same_atoms = st && h->tile_workspace && st->n == n_atoms && st->skin == skin &&
                            std::equal(st->z.begin(), st->z.end(), atomic_numbers);
    const bool same_cell = same_atoms && memcmp(st->cell, cell, sizeof(st->cell)) == 0;
    // LT6 (a): on another cell the lists stay while the strain since their build leaves a margin (the whole system's
    // variable-cell test, cell.hpp): F = h0^-1 h, thr = (r_list (1 - |F - 1|) - r_max) / 2 > 0, and every atom lies
    // within thr of x0 F + t, t the atoms' mean displacement (a common translation moves no pair vector).
    Mat9 strain{};
    double thr = -1.0;
    if (same_atoms && !same_cell) {
        double dev2 = 0.0;
        for (int r = 0; r < 3; ++r)
            for (int c = 0; c < 3; ++c) {
                double v = 0.0;
                for (int k = 0; k < 3; ++k) v += st->ref_inv[r * 3 + k] * cell[k * 3 + c];
                strain.m[r * 3 + c] = v;
                const double e = v - (r == c ? 1.0 : 0.0);
                dev2 += e * e;
            }
        thr = 0.5 * (r_list * (1.0 - std::sqrt(dev2)) - r_max);
        if (!std::isfinite(thr)) thr = -1.0;
    }
    const bool strained = thr > 0.0;
    const int asked = receivers;
    if ((same_cell || strained) && receivers <= 0) receivers = st->receivers;  // the kept cap while the lists may stay
    bool keep = (same_cell || strained) && receivers == st->receivers;
    if (keep) {
        CUDA_CHECK(cudaMemcpyAsync(st->whole_pos.p, d_positions ? d_positions : positions,
                                   (size_t)n_atoms * 3 * sizeof(double),
                                   d_positions ? cudaMemcpyDeviceToDevice : cudaMemcpyHostToDevice, h->stream));
        CUDA_CHECK(cudaMemsetAsync(st->disp2.p, 0, 4 * sizeof(double), h->stream));
        const double* wp = static_cast<const double*>(st->whole_pos.p);
        const double* rp = static_cast<const double*>(st->ref_pos.p);
        unsigned long long* bits_d = static_cast<unsigned long long*>(st->disp2.p);
        if (same_cell) {
            max_disp2_kernel<<<blocks(n_atoms), 256, 0, h->stream>>>(n_atoms, wp, rp, bits_d);
        } else {
            double* sum = reinterpret_cast<double*>(bits_d + 1);
            strain_disp_sum_kernel<<<blocks(n_atoms), 256, 0, h->stream>>>(n_atoms, wp, rp, strain, sum);
            strain_disp_max_kernel<<<blocks(n_atoms), 256, 0, h->stream>>>(n_atoms, wp, rp, strain, sum, bits_d);
        }
        unsigned long long bits = 0;
        CUDA_CHECK(cudaMemcpyAsync(&bits, bits_d, sizeof(bits), cudaMemcpyDeviceToHost, h->stream));
        CUDA_CHECK(cudaStreamSynchronize(h->stream));
        double d2 = 0.0;
        memcpy(&d2, &bits, sizeof(d2));
        keep = std::isfinite(d2) && (same_cell ? d2 <= 0.25 * skin * skin : d2 <= thr * thr);
    }
    // a changed cell that needs new lists plans again on receivers 0 (LD3), as before LT6 (a)
    if (!keep && !same_cell && asked <= 0) receivers = asked;
    if (!keep) {
        release_tiled_state(h);
        st = nullptr;
        if (!positions) {  // the planner and the list builds read the positions on the host
            host_positions.resize((size_t)n_atoms * 3);
            CUDA_CHECK(cudaMemcpyAsync(host_positions.data(), d_positions, host_positions.size() * sizeof(double),
                                       cudaMemcpyDeviceToHost, h->stream));
            CUDA_CHECK(cudaStreamSynchronize(h->stream));
            positions = host_positions.data();
        }
    }
    if (!keep && receivers <= 0) {  // the memory plan's cap, the mode taken as tiled
        struct Mode {
            LoupHandle* h;
            int saved;
            ~Mode() { h->exec_mode = saved; }
        } mode{h, h->exec_mode};
        if (h->exec_mode != LOUP_EXEC_WAVEFRONT) h->exec_mode = LOUP_EXEC_TILED;
        LoupMemoryPlan mp{};
        if (plan_execution_impl(h, n_atoms, atomic_numbers, positions, cell, skin, &mp) != 0) return -1;
        receivers = mp.receivers;
    }
    size_t free_b = 0, total_b = 0, least_free = 0;
    CUDA_CHECK(device_memory(&free_b, &total_b));
    const double budget = (double)free_b + handle_system_bytes(h) + (st ? st->bytes : 0.0);
    least_free = free_b;
    auto note_free = [&]() -> int {
        size_t f = 0, t = 0;
        CUDA_CHECK(device_memory(&f, &t));
        least_free = std::min(least_free, f);
        return 0;
    };
    const bool tile_times = std::getenv("LOUP_DEBUG_TILE_TIMES") && std::getenv("LOUP_DEBUG_TILE_TIMES")[0] == '1';
    auto tick_last = std::chrono::steady_clock::now();
    auto tick = [&](const char* what) {
        if (!tile_times) return;
        cudaStreamSynchronize(h->stream);
        const auto now = std::chrono::steady_clock::now();
        size_t f = 0, t = 0;
        device_memory(&f, &t);
        std::fprintf(stderr, "tile times: %-28s %9.2f ms (%.0f MB free)\n", what,
                     std::chrono::duration<double, std::milli>(now - tick_last).count(), (double)f / 1e6);
        tick_last = now;
    };
    if (!keep) {
        // The wavefront (S5-T08): two-layer models only (three sweeps). LOUP_TILE_WAVEFRONT=1 forces it, 0 turns it
        // off; otherwise on from 2^20 atoms and 12 layers of tiles along the first axis (the plan's rule). Its plan
        // splits the first and last layer at the faces (boundary skins), so only they stay in the pool all call.
        bool wave_forced = false;
        // O32: the layer state in host memory: the plain order's, or with the wavefront (the plan's form 2, or the
        // wavefront forced) its row pool. LOUP_TILE_HOST_STATE=1|0 forces it.
        bool host_state = h->tile_host_state != 0;
        if (const char* e = std::getenv("LOUP_TILE_HOST_STATE")) host_state = std::atoi(e) != 0;
        const bool wave_ok = wave_try(h, n_atoms, &wave_forced);
        const bool wave_on = wave_ok && (!host_state || wave_forced || h->tile_host_state == 2);
        loup::TilePlan plan;
        try {
            plan = loup::plan_tiles(positions, n_atoms, cell, receivers, 0, nullptr, r_list + 1e-3, nullptr,
                                    wave_on ? r_list + 1e-3 : 0.0);
        } catch (const std::exception& e) {
            loup::set_error("tile plan: %s", e.what());
            return -1;
        }
        // the rule of wave_pool_rows, which the memory plan used
        const bool wave = wave_on && (wave_forced || plan.grid[0] >= 12) && plan.tiles() >= 2;
        const int64_t T = plan.tiles();
        // The tiles' domains; the candidates that send along no edge are dropped (S5-T02).
        std::vector<TileDomain> alls((size_t)T), tiles((size_t)T);
        int max_rows = 0;
        size_t widest = 0;
        for (int64_t k = 0; k < T; ++k) {
            host_domain(plan, k, atomic_numbers, positions, cell, r_list, alls[(size_t)k]);
            if (alls[(size_t)k].atom.size() > alls[widest].atom.size()) widest = (size_t)k;
        }
        tick("plan and host domains");
        // One workspace for every tile: the buffers of the widest domain (all its candidates), set up once. A
        // workspace of an earlier call stays when it is large enough and has the same skin: loup_set_system's path
        // would also empty the cuBLASLt cache, and every tile's GEMM shapes would be looked up again.
        const bool reuse = h->tile_workspace && h->skin == skin && (int)alls[widest].atom.size() <= h->atom_cap;
        if (!reuse) {
            if (set_domain_impl(h, alls[widest].n_local, alls[widest].n_ghost(), alls[widest].z.data(), skin) != 0)
                return -1;
            h->tile_workspace = true;
        }
        tick("workspace set-up");
        if (tile_times)
            std::fprintf(stderr, "tile workspace: widest domain %d locals + %d ghosts (%lld tiles, grid %d x %d x %d)\n",
                         alls[widest].n_local, alls[widest].n_ghost(), (long long)T, plan.grid[0], plan.grid[1],
                         plan.grid[2]);
        for (int64_t k = 0; k < T; ++k) {
            TileDomain& all = alls[(size_t)k];
            TileDomain& t = tiles[(size_t)k];
            const int G = all.n_ghost();
            if (G == 0) { t = std::move(all); max_rows = std::max(max_rows, t.n_local); continue; }
            if (reshape_domain(h, all.n_local, G, all.z.data()) != 0) return -1;
            if (upload_positions(h, all.place.data(), all.box) < 0) return -1;
            if (rebuild_neighbors(h) != 0) return -1;
            std::vector<unsigned char> used((size_t)G, 0);
            DeviceBufferGuard dm;
            CUDA_CHECK(cudaMalloc(&dm.p, G));
            CUDA_CHECK(cudaMemsetAsync(dm.p, 0, G, h->stream));
            if (h->E_skin > 0)
                mark_ghost_senders_kernel<<<(h->E_skin + 255) / 256, 256, 0, h->stream>>>(
                    h->E_skin, h->N, h->d_senders, static_cast<unsigned char*>(dm.p));
            CUDA_CHECK(cudaMemcpyAsync(used.data(), dm.p, G, cudaMemcpyDeviceToHost, h->stream));
            CUDA_CHECK(cudaStreamSynchronize(h->stream));
            t.n_local = all.n_local;
            std::copy(all.box, all.box + 9, t.box);
            std::copy(all.org, all.org + 3, t.org);
            for (int r = 0; r < (int)all.atom.size(); ++r) {
                if (r >= all.n_local && !used[(size_t)(r - all.n_local)]) continue;
                t.atom.push_back(all.atom[r]);
                t.z.push_back(all.z[r]);
                t.place.insert(t.place.end(), &all.place[(size_t)r * 3], &all.place[(size_t)r * 3 + 3]);
            }
            max_rows = std::max(max_rows, (int)t.atom.size());
            TileDomain().atom.swap(all.atom);  // the candidates' host copy is no longer needed
            all.place.clear(); all.place.shrink_to_fit();
        }
        tick("candidate builds");
        // Every tile's list, built once and kept with the rest of the state: on the device, or (O31, the plan's
        // choice when the lists do not fit; LOUP_TILE_HOST_LISTS=1|0 forces it) its edge arrays in host memory
        bool host_lists = h->tile_host_lists != 0;
        if (const char* e = std::getenv("LOUP_TILE_HOST_LISTS")) host_lists = std::atoi(e) != 0;
        st = h->tiled_state = new TiledState();
        st->host_lists = host_lists;
        st->host_state = host_state;
        st->lists = std::vector<TileList>((size_t)T);
        int max_edges = 0;
        for (int64_t k = 0; k < T; ++k) {
            TileList& tl = st->lists[(size_t)k];
            if (build_tile_list(h, tiles[(size_t)k], positions, tl, host_lists, &st->list_arena) != 0) {
                release_tiled_state(h);
                return -1;
            }
            max_edges = std::max(max_edges, tl.E);
            st->bytes += (double)tl.rows * (4 + 24 + 4 + 24) + (double)(tl.n_local + 1) * 4;
            if (host_lists) st->host_bytes += (double)tl.E * (tl.compact ? 8 : kTileFullEdgeB);
            else st->bytes += (double)tl.E * (tl.compact ? 8 : kTileFullEdgeB);
        }
        if (max_edges > h->E_cap) {
            release_tiled_state(h);
            loup::set_error("internal error: a kept tile list outgrew the edge capacity");
            return -1;
        }
        tick(host_lists ? "kept list builds (host edges)" : "kept list builds");
        if (tile_times) {
            int64_t n_compact = 0;
            for (const TileList& tl : st->lists) n_compact += tl.compact;
            std::fprintf(stderr, "tile lists: %s, %lld of %lld compact, %.0f MB of edges\n",
                         host_lists ? "host" : "device", (long long)n_compact, (long long)T,
                         (host_lists ? st->host_bytes : st->bytes) / 1e6);
        }
        st->n = n_atoms; st->receivers = receivers; st->T = T; st->skin = skin;
        st->max_rows = max_rows; st->max_edges = max_edges;
        if (wave) {
            // The schedule from the plan's locals and candidates (a superset of the kept rows), then a pool row for
            // every atom: the host replays the schedule, taking rows at a tile's sweep 1 and giving them back at its
            // sweep 3. Every atom is a local of one tile, so it has one pool row for the whole call.
            std::vector<int64_t> needs_ptr, needs, ready, counts((size_t)T);
            for (int64_t k = 0; k < T; ++k) counts[(size_t)k] = plan.local_ptr[(size_t)k + 1] - plan.local_ptr[(size_t)k];
            int64_t peak = 0;
            try {
                loup::tile_dependencies(plan, needs_ptr, needs, ready);
                st->steps = loup::wavefront_schedule(T, needs_ptr.data(), needs.data(), ready.data(), counts.data(), 1,
                                                     &peak);
            } catch (const std::exception& e) {
                release_tiled_state(h);
                loup::set_error("tile wavefront: %s", e.what());
                return -1;
            }
            std::vector<int> slot_of_atom((size_t)n_atoms, -1), free_rows;
            std::vector<std::vector<int>> taken((size_t)T);
            int next = 0;
            for (const loup::SweepStep& s : st->steps) {
                const int64_t a = plan.local_ptr[(size_t)s.tile], b = plan.local_ptr[(size_t)s.tile + 1];
                if (s.sweep == 1) {
                    for (int64_t i = a; i < b; ++i) {
                        int row;
                        if (!free_rows.empty()) { row = free_rows.back(); free_rows.pop_back(); }
                        else row = next++;
                        slot_of_atom[(size_t)plan.local[(size_t)i]] = row;
                        taken[(size_t)s.tile].push_back(row);
                    }
                } else if (s.sweep == 3) {
                    free_rows.insert(free_rows.end(), taken[(size_t)s.tile].begin(), taken[(size_t)s.tile].end());
                    std::vector<int>().swap(taken[(size_t)s.tile]);
                }
            }
            if (next != peak) {
                release_tiled_state(h);
                loup::set_error("internal error: the row pool took %d rows, the schedule's peak is %lld", next,
                                (long long)peak);
                return -1;
            }
            st->wave = true;
            st->pool_rows = peak;
            if (st->host_state) {
                // O32: the pool in host memory as blocks of the most locals per tile, a tile's locals in one block
                // (its rows in the tile's row order) from its sweep 1 to its sweep 3: the ghost rows' blocks are
                // held as long as the device pool's rows would be (the same schedule)
                int64_t max_local = 0, n_blocks = 0;
                for (const TileList& tl : st->lists) max_local = std::max<int64_t>(max_local, tl.n_local);
                std::vector<int64_t> free_blocks;
                std::vector<int64_t> block_of((size_t)T, -1);
                for (const loup::SweepStep& s : st->steps) {
                    if (s.sweep == 1) {
                        int64_t b;
                        if (!free_blocks.empty()) { b = free_blocks.back(); free_blocks.pop_back(); }
                        else b = n_blocks++;
                        block_of[(size_t)s.tile] = b;
                        st->lists[(size_t)s.tile].hbase = b * max_local;
                    } else if (s.sweep == 3) {
                        free_blocks.push_back(block_of[(size_t)s.tile]);
                    }
                }
                st->pool_rows = n_blocks * max_local;
                if (tile_times)
                    std::fprintf(stderr, "tile wavefront host pool: %lld blocks of %lld rows (device pool %lld)\n",
                                 (long long)n_blocks, (long long)max_local, (long long)peak);
            } else {
                DeviceBufferGuard d_slot;
                CUDA_CHECK(cudaMalloc(&d_slot.p, (size_t)n_atoms * sizeof(int)));
                CUDA_CHECK(cudaMemcpyAsync(d_slot.p, slot_of_atom.data(), (size_t)n_atoms * sizeof(int),
                                           cudaMemcpyHostToDevice, h->stream));
                for (TileList& tl : st->lists) {
                    CUDA_CHECK(cudaMalloc(&tl.row_slot.p, (size_t)tl.rows * sizeof(int)));
                    tile_map_rows_kernel<<<(tl.rows + 255) / 256, 256, 0, h->stream>>>(
                        tl.rows, static_cast<const int*>(tl.row_atom.p), static_cast<const int*>(d_slot.p),
                        static_cast<int*>(tl.row_slot.p));
                    st->bytes += (double)tl.rows * 4;
                }
                CUDA_CHECK(cudaStreamSynchronize(h->stream));  // `slot_of_atom` and `d_slot` go out of scope
            }
            tick("wavefront schedule");
            if (tile_times)
                std::fprintf(stderr, "tile wavefront: %lld tiles, grid %d x %d x %d, row pool %lld of %lld atoms\n",
                             (long long)T, plan.grid[0], plan.grid[1], plan.grid[2], (long long)peak,
                             (long long)n_atoms);
        }
        if (st->host_state) {  // each atom's host row: its tile's block of locals, in the tile's row order
            std::vector<int64_t> hrow((size_t)n_atoms, -1);
            int64_t base = 0, held = 0;
            for (TileList& tl : st->lists) {
                if (!st->wave) tl.hbase = base;
                for (int r = 0; r < tl.n_local; ++r) hrow[(size_t)tl.h_row_atom[(size_t)r]] = tl.hbase + r;
                base += tl.n_local;
            }
            for (int64_t r : hrow) held += r >= 0;
            if (base != n_atoms || held != n_atoms) {
                release_tiled_state(h);
                loup::set_error("internal error: the tiles hold %lld locals (%lld atoms) for %d atoms", (long long)base,
                                (long long)held, n_atoms);
                return -1;
            }
            for (TileList& tl : st->lists) {
                tl.h_ghost.resize((size_t)(tl.rows - tl.n_local));
                for (int r = tl.n_local; r < tl.rows; ++r)
                    tl.h_ghost[(size_t)(r - tl.n_local)] = (int)hrow[(size_t)tl.h_row_atom[(size_t)r]];
            }
        }
        for (TileList& tl : st->lists) std::vector<int>().swap(tl.h_row_atom);
        const int64_t layer_rows = st->wave ? st->pool_rows : n_atoms;
        std::copy(cell, cell + 9, st->cell);
        {
            loup::CellMat64 cm;
            double vol = 0.0, heights[3];
            loup::compute_cell_mat(cell, cm, vol, heights);
            std::copy(cm.inv, cm.inv + 9, st->ref_inv);
        }
        st->z.assign(atomic_numbers, atomic_numbers + n_atoms);
        auto alloc = [&](DeviceBufferGuard& g, size_t bytes) -> int {
            CUDA_CHECK(cudaMalloc(&g.p, std::max<size_t>(bytes, 1)));
            st->bytes += (double)bytes;
            return 0;
        };
        const size_t pos_bytes = (size_t)n_atoms * 3 * sizeof(double);
        // The whole system's positions, layer outputs, their gradients and the forces, on the device
        st->x = std::vector<DeviceBufferGuard>((size_t)(L - 1) * 4);
        st->dx = std::vector<DeviceBufferGuard>((size_t)(L - 1) * 4);
        // disp2: the largest squared displacement's bits, then (LT6 (a)) the summed displacements of a strained cell
        int fail = alloc(st->whole_pos, pos_bytes) | alloc(st->ref_pos, pos_bytes) |
                   alloc(st->disp2, 4 * sizeof(double)) | alloc(st->forces, pos_bytes);
        if (st->host_state) {
            st->hx = std::vector<HostBufferGuard>((size_t)(L - 1) * 4);
            st->hdx = std::vector<HostBufferGuard>((size_t)(L - 1) * 4);
        }
        auto halloc = [&](HostBufferGuard& g, size_t bytes) -> int {
            if (!pinned_take(h, g, bytes)) {
                loup::set_error("tile host state: %.2f GB of pinned host memory not available", bytes / 1e9);
                return 1;
            }
            st->host_bytes += (double)bytes;
            return 0;
        };
        st->pipe = st->host_state && !st->wave;  // the wavefront's host pool: one sweep after another
        if (const char* e = std::getenv("LOUP_TILE_HOST_PIPE")) st->pipe = st->pipe && std::atoi(e) != 0;
        // O32: with the pipeline on a two-layer model dx takes x's rows; LOUP_TILE_HOST_ALIAS=0 keeps both arrays
        st->alias = st->pipe && !st->wave && L == 2;
        if (const char* e = std::getenv("LOUP_TILE_HOST_ALIAS")) st->alias = st->alias && std::atoi(e) != 0;
        size_t widest_w = 0;
        for (int t = 0; t + 1 < L; ++t)
            for (int l = 0; l <= h->gen->out_lmax(t); ++l) {
                const size_t bytes = (size_t)layer_rows * width(t, l) * sizeof(float);
                widest_w = std::max(widest_w, (size_t)width(t, l));
                if (st->host_state)
                    fail |= halloc(st->hx[(size_t)t * 4 + l], bytes) |
                            (st->alias ? 0 : halloc(st->hdx[(size_t)t * 4 + l], bytes));
                else
                    fail |= alloc(st->x[(size_t)t * 4 + l], bytes) | alloc(st->dx[(size_t)t * 4 + l], bytes);
            }
        if (st->host_state)
            fail |= halloc(st->stage_in, (size_t)max_rows * widest_w * sizeof(float)) |
                    halloc(st->stage_out, (size_t)max_rows * widest_w * sizeof(float));
        if (st->pipe && !fail) {
            size_t sumw = 0;
            for (int t = 0; t + 1 < L; ++t) {
                size_t w = 0;
                for (int l = 0; l <= h->gen->out_lmax(t); ++l) w += (size_t)width(t, l);
                sumw = std::max(sumw, w);
            }
            st->pipe_floats = (size_t)max_rows * sumw;
            const size_t bytes = st->pipe_floats * sizeof(float);
            if (st->hp.init() != 0) {
                (void)cudaGetLastError();
                loup::set_error("tile host state: the copy stream could not be set up");
                fail = 1;
            }
            for (int k = 0; k < 2 && !fail; ++k)
                fail |= alloc(st->hp.a[k], bytes) | alloc(st->hp.b[k], bytes) | halloc(st->hp.in[k], bytes) |
                        halloc(st->hp.out[k], bytes);
        }
        for (int l = 0; l < 4; ++l) {
            size_t floats = 0;
            for (int t = 0; t + 1 < L; ++t)
                if (l <= h->gen->out_lmax(t)) floats = std::max(floats, (size_t)max_rows * width(t, l));
            if (floats) fail |= alloc(st->adj[l], floats * sizeof(float));
        }
        if (fail) { release_tiled_state(h); return -1; }
        CUDA_CHECK(cudaMemcpyAsync(st->whole_pos.p, positions, pos_bytes, cudaMemcpyHostToDevice, h->stream));
        CUDA_CHECK(cudaMemcpyAsync(st->ref_pos.p, st->whole_pos.p, pos_bytes, cudaMemcpyDeviceToDevice, h->stream));
        st->act_keep = -1;
        st->act_slots.clear();
        ++h->tile_list_builds;
        tick("state allocations");
    } else if (same_cell) {
        for (TileList& t : st->lists)
            tile_place_rows_kernel<<<blocks((int64_t)t.rows * 3), 256, 0, h->stream>>>(
                t.rows, static_cast<const int*>(t.row_atom.p), static_cast<const double*>(t.offset.p),
                static_cast<const double*>(st->whole_pos.p), static_cast<double*>(t.pos.p));
        tick("kept lists refreshed");
    } else {  // LT6 (a): the kept lists' rows placed in the strained cell
        TileCellMove m{};
        std::copy(st->ref_inv, st->ref_inv + 9, m.inv0);
        for (int i = 0; i < 9; ++i) m.dh[i] = cell[i] - st->cell[i];
        for (TileList& t : st->lists) {
            std::copy(t.org, t.org + 3, m.org);
            tile_place_rows_cell_kernel<<<blocks(t.rows), 256, 0, h->stream>>>(
                t.rows, static_cast<const int*>(t.row_atom.p), static_cast<const double*>(t.offset.p),
                static_cast<const double*>(st->whole_pos.p), m, static_cast<double*>(t.pos.p));
        }
        tick("kept lists refreshed (strained cell)");
    }
    h->E_graph = st->max_edges;  // the edge kernels' grid: every tile's edges
    h->invalidate_graphs();
    const int64_t T = st->T;
    if (out_tiles) *out_tiles = T;
    std::vector<TileList>& lists = st->lists;
    std::vector<DeviceBufferGuard>& x = st->x;
    std::vector<DeviceBufferGuard>& dx = st->dx;
    DeviceBufferGuard& d_forces = st->forces;
    DeviceBufferGuard* adj = st->adj;
    ++st->calls;
    if (st->act_keep < 0) {
        // A tile's active edges are compacted once per call, in its first sweep, into a slot that it holds until its
        // last sweep (the backward sweep of layer 0). As many slots as tiles are in flight at once (all of them in
        // the plain order; the wavefront's schedule says how many), within the free memory less a reserve; a tile that
        // finds no slot free compacts in each of its sweeps. LOUP_TILE_KEEP_ACTIVE=0 keeps none, =k at most k
        // slots whatever the memory.
        int64_t in_flight = st->wave ? 0 : st->T, open = 0;
        for (const loup::SweepStep& s : st->steps) {
            if (!st->wave) break;
            open += s.sweep == 1 ? 1 : s.sweep == 3 ? -1 : 0;
            in_flight = std::max(in_flight, open);
        }
        const double slot_bytes =
            (double)std::max(st->max_edges, 1) * (16 + 3 * 4 + 8) + (double)(st->max_rows + 1) * 4;
        size_t free_b = 0, total_b = 0;
        CUDA_CHECK(device_memory(&free_b, &total_b));
        // within the free memory less a reserve of max(256 MB, 2% of the card): the wavefront at 1,081,600 atoms
        // gains 2.3% from 5 slots (980 of 1,312 MB free) and nothing from 1 (status §6.34). O32: and within the
        // memory fraction (the part of the budget it leaves out stays free): 3,524,845 atoms at fraction 0.75 took 24
        // slots of 221 MB in 5.8 GB free and ran out of memory in the sweeps; with 8 they ran (peak 13.3 of 16 GB).
        // tile-plan-exact: and less the scratch of the GEMM timing in a building call's first sweeps (the model's
        // largest buffer and the cache-flush buffer), so that call stays within the fraction as well
        const double reserve =
            std::max({256.0 * 1048576.0, 0.02 * (double)total_b, (1.0 - h->exec_fraction) * budget}) +
            (double)h->gen->largest_buffer_bytes() + 2.0 * (double)std::max(h->l2_bytes, 1 << 20);
        // Host lists: two staging buffers first (LOUP_TILE_HOST_STAGE=0|1), then the slots in what is left
        st->stage = 0;
        for (DeviceBufferGuard& g : st->ring.buf)
            if (g.p) { cudaFree(g.p); g.p = nullptr; }
        double avail = (double)free_b - reserve;
        if (st->host_lists) {
            bool all_compact = true;
            for (const TileList& tl : st->lists) all_compact = all_compact && tl.compact;
            const size_t stage_b = (size_t)std::max(st->max_edges, 1) * (all_compact ? 8 : kTileFullEdgeB);
            bool on = 2.0 * (double)stage_b <= avail;
            if (const char* e = std::getenv("LOUP_TILE_HOST_STAGE")) on = std::atoi(e) != 0;
            StageRing& r = st->ring;
            bool ok = on;
            if (ok && !r.copy) {
                ok = cudaStreamCreateWithFlags(&r.copy, cudaStreamNonBlocking) == cudaSuccess;
                for (int i = 0; ok && i < 2; ++i)
                    ok = cudaEventCreateWithFlags(&r.copied[i], cudaEventDisableTiming) == cudaSuccess &&
                         cudaEventCreateWithFlags(&r.used[i], cudaEventDisableTiming) == cudaSuccess;
            }
            for (int i = 0; ok && i < 2; ++i)
                if (loup::device_malloc(&r.buf[i].p, stage_b) != cudaSuccess) { r.buf[i].p = nullptr; ok = false; }
            if (on && !ok) {  // out of memory: the compaction reads the host lists over the bus
                (void)cudaGetLastError();
                for (DeviceBufferGuard& g : r.buf)
                    if (g.p) { cudaFree(g.p); g.p = nullptr; }
            }
            st->stage = on && ok ? 1 : 0;
            if (st->stage) {
                st->bytes += 2.0 * (double)stage_b;
                avail -= 2.0 * (double)stage_b;
            }
            if (tile_times)
                std::fprintf(stderr, "tile host lists staged: %s (2 x %.0f MB)%s\n", st->stage ? "yes" : "no",
                             (double)stage_b / 1e6, all_compact ? ", compact" : "");
        }
        // O32: where full slots cannot cover every tile in flight, compact slots (8 B per edge) cover more: the most
        // full slots that leave compact ones for all the others, else compact slots only
        bool any_compact = false;
        for (const TileList& tl : st->lists) any_compact = any_compact || tl.compact;
        const double cslot_bytes = (double)std::max(st->max_edges, 1) * 8 + (double)(st->max_rows + 1) * 4;
        const double room = std::max(0.0, avail);
        int64_t want = std::min<int64_t>(in_flight, (int64_t)(room / slot_bytes));
        if (any_compact && want < in_flight)
            want = (double)in_flight * cslot_bytes <= room
                       ? std::min<int64_t>(in_flight, (int64_t)((room - (double)in_flight * cslot_bytes) /
                                                               (slot_bytes - cslot_bytes)))
                       : 0;
        if (const char* e = std::getenv("LOUP_TILE_KEEP_ACTIVE"))
            want = std::min<int64_t>(in_flight, std::max(0LL, std::atoll(e)));
        // Built in place: DeviceBufferGuard has no move, so the vector must never copy or grow
        st->act_slots = std::vector<ActiveSlot>((size_t)want);
        const size_t E = (size_t)std::max(st->max_edges, 1);
        int got = 0;
        // O32: all slots in one chunk where it fits, else one each (tile-list-arena)
        st->slot_arena.chunk = (size_t)std::max<int64_t>(want, 0) * (size_t)(slot_bytes + 6 * 256);
        for (int64_t k = 0; k < want; ++k) {
            ActiveSlot& sl = st->act_slots[(size_t)k];
            auto take = [&] {
                return alloc_slot(sl.blk, {{&sl.row_ptr, (size_t)(st->max_rows + 1) * sizeof(int)},
                                           {&sl.senders, E * sizeof(int)},
                                           {&sl.receivers, E * sizeof(int)},
                                           {&sl.slab, E * sizeof(int)},  // O32: no pairs (no sweep reads them)
                                           {&sl.vec_len, E * sizeof(float4)},
                                           {&sl.t_sx, E * sizeof(float2)}},
                                  &st->slot_arena);
            };
            bool ok = take();
            if (!ok && st->slot_arena.chunks.empty()) {
                st->slot_arena.chunk = 0;
                ok = take();
            }
            if (!ok) {  // out of memory after all: the slots so far (the rest free their buffers with the state)
                (void)cudaGetLastError();
                break;
            }
            ++got;
            st->bytes += slot_bytes;
        }
        st->act_keep = got;
        // O32: compact slots (8 B per edge) for the tiles in flight beyond the full slots, in what is left; tiles of
        // compact lists only. LOUP_TILE_KEEP_COMPACT=0|k (none, or at most k); none where LOUP_TILE_KEEP_ACTIVE is set
        // and this is not.
        {
            const double left = std::max(0.0, avail - (double)got * slot_bytes);
            int64_t want_c = any_compact ? std::min<int64_t>(in_flight - got, (int64_t)(left / cslot_bytes)) : 0;
            if (std::getenv("LOUP_TILE_KEEP_ACTIVE")) want_c = 0;
            if (const char* e = std::getenv("LOUP_TILE_KEEP_COMPACT"))
                want_c = any_compact ? std::min<int64_t>(in_flight - got, std::max(0LL, std::atoll(e))) : 0;
            st->cact_slots = std::vector<CompactSlot>((size_t)std::max<int64_t>(want_c, 0));
            int got_c = 0;
            st->cslot_arena.chunk = st->cact_slots.size() * (size_t)(cslot_bytes + 3 * 256);
            for (CompactSlot& cs : st->cact_slots) {
                auto take = [&] {
                    return alloc_slot(cs.blk, {{&cs.row_ptr, (size_t)(st->max_rows + 1) * sizeof(int)},
                                               {&cs.senders, E * sizeof(int)},
                                               {&cs.code, E * sizeof(char4)}},
                                      &st->cslot_arena);
                };
                bool ok = take();
                if (!ok && st->cslot_arena.chunks.empty()) {
                    st->cslot_arena.chunk = 0;
                    ok = take();
                }
                if (!ok) {
                    (void)cudaGetLastError();
                    break;
                }
                ++got_c;
                st->bytes += cslot_bytes;
            }
            st->cact_keep = got_c;
            if (tile_times)
                std::fprintf(stderr, "tile compact active slots: %d (%.0f MB each; %.0f MB free less %.0f MB reserve)\n",
                             got_c, cslot_bytes / 1e6, (double)free_b / 1e6, reserve / 1e6);
        }
        // Layer 0's forward results per tile, after the slots, within the same reserve: plain order only (the
        // wavefront's tiles in flight would need them too, and it runs where memory is short). LOUP_TILE_KEEP_L0=0|1.
        st->keep_l0 = 0;
        if (!st->wave && h->gen->sweep_keep_layer0()) {
            double l0_bytes = 0.0;
            for (const TileList& t : lists) l0_bytes += (double)h->gen->sweep_keep_floats(t.n_local) * sizeof(float);
            size_t f2 = 0, t2 = 0;
            CUDA_CHECK(device_memory(&f2, &t2));
            bool on = l0_bytes <= (double)f2 - reserve;
            if (const char* e = std::getenv("LOUP_TILE_KEEP_L0")) on = std::atoi(e) != 0;
            bool ok = on;
            for (TileList& t : lists) {
                if (!ok) break;
                const size_t b = h->gen->sweep_keep_floats(t.n_local) * sizeof(float);
                if (loup::device_malloc(&t.keep0.p, std::max<size_t>(b, 1)) != cudaSuccess) { t.keep0.p = nullptr; ok = false; }
            }
            if (on && !ok) {  // out of memory after all: the replay
                (void)cudaGetLastError();
                for (TileList& t : lists)
                    if (t.keep0.p) { cudaFree(t.keep0.p); t.keep0.p = nullptr; }
            }
            st->keep_l0 = on && ok ? 1 : 0;
            if (st->keep_l0) st->bytes += l0_bytes;
            if (tile_times)
                std::fprintf(stderr, "tile layer 0 kept: %s (%.0f MB, free %.0f MB)\n", st->keep_l0 ? "yes" : "no",
                             l0_bytes / 1e6, (double)f2 / 1e6);
        }
        if (tile_times)
            std::fprintf(stderr, "tile active edges: %d slots, %lld tiles in flight (%.0f MB each, free %.0f MB)\n",
                         st->act_keep, (long long)in_flight, slot_bytes / 1e6, (double)free_b / 1e6);
        tick("slots set up");
    }
    for (const TileList& t : lists) t.act_slot = t.cact_slot = -1;  // a failed call may have left slots taken
    st->act_free.clear();
    st->cact_free.clear();
    for (int k = st->cact_keep - 1; k >= 0; --k) st->cact_free.push_back(k);
    for (int k = st->act_keep - 1; k >= 0; --k) st->act_free.push_back(k);
    const long long call = st->calls;
    const bool wave = st->wave;  // the pool's rows are zeroed tile by tile at each tile's sweep 1
    const bool hs = st->host_state;
    // O32: rows of the host state, split over a few host threads when there are many
    auto par_rows = [](int64_t n, int64_t w, const std::function<void(int64_t, int64_t)>& fn) {
        const int64_t work = n * w;
        int k = (int)std::min<int64_t>(8, std::max<int64_t>(1, work / (1 << 20)));
        k = std::min<int>(k, (int)std::max(1u, std::thread::hardware_concurrency()));
        if (k <= 1) { fn(0, n); return; }
        std::vector<std::thread> th;
        for (int i = 0; i < k; ++i) th.emplace_back(fn, n * i / k, n * (i + 1) / k);
        for (auto& t : th) t.join();
    };
    // O32: the gradient adds of a tile's rows r in [0, n) over a few host threads, split by destination (`key`: the
    // row's host row; a tile's rows may hold one host row more than once where its ghosts are images of its own rows
    // or of one atom, and a split by tile row would add into it from two threads at once). Each host row's adds run on
    // one thread in tile row order, as on one thread.
    auto par_adds = [](int64_t n, int64_t w, const std::function<int64_t(int64_t)>& key,
                       const std::function<void(int64_t)>& add) {
        const int64_t work = n * w;
        int k = (int)std::min<int64_t>(8, std::max<int64_t>(1, work / (1 << 20)));
        k = std::min<int>(k, (int)std::max(1u, std::thread::hardware_concurrency()));
        if (k <= 1) {
            for (int64_t r = 0; r < n; ++r) add(r);
            return;
        }
        std::vector<std::thread> th;
        for (int i = 0; i < k; ++i)
            th.emplace_back([&, i] {
                for (int64_t r = 0; r < n; ++r)
                    if ((key(r) >> 6) % k == i) add(r);
            });
        for (auto& t : th) t.join();
    };
    if (hs) {
        CUDA_CHECK(cudaStreamSynchronize(h->stream));  // an earlier call's copies out of the host state
        for (int t = 0; !st->alias && !wave && t + 1 < L; ++t)  // the wavefront's blocks: zeroed at each sweep 1
            for (int l = 0; l <= h->gen->out_lmax(t); ++l) {
                float* d = static_cast<float*>(st->hdx[(size_t)t * 4 + l].p);
                const int64_t w = width(t, l);
                par_rows(n_atoms, w, [&](int64_t a, int64_t b) { std::memset(d + a * w, 0, (size_t)(b - a) * w * 4); });
            }
    }
    for (int t = 0; !hs && !wave && t + 1 < L; ++t)
        for (int l = 0; l <= h->gen->out_lmax(t); ++l)
            CUDA_CHECK(cudaMemsetAsync(dx[(size_t)t * 4 + l].p, 0, (size_t)n_atoms * width(t, l) * sizeof(float),
                                       h->stream));
    CUDA_CHECK(cudaMemsetAsync(d_forces.p, 0, (size_t)n_atoms * 3 * sizeof(double), h->stream));
    auto fx = [&](int t, int l) { return static_cast<float*>(x[(size_t)t * 4 + l].p); };
    auto fdx = [&](int t, int l) { return static_cast<float*>(dx[(size_t)t * 4 + l].p); };
    auto grid = [](int64_t n) { return (unsigned)((n + 255) / 256); };
    struct NoFork {
        LoupHandle* h;
        bool saved;
        explicit NoFork(LoupHandle* h_) : h(h_), saved(h_->fork_ok) { h->fork_ok = false; }
        ~NoFork() { h->fork_ok = saved; }
    } no_fork(h);
    const int stress = out_stress ? 1 : 0;
    double energy = 0.0, virial[6] = {0, 0, 0, 0, 0, 0};
    // Energy and virial accumulate on the device over every tile sweep; each tile's forces are folded after it.
    CUDA_CHECK(cudaMemsetAsync(h->d_zero_slab, 0, h->zero_slab_bytes, h->stream));
    TileListBorrow borrow(h);  // the sweeps point the handle at each tile's list (restore_tile_list)
    // The sweeps in order (tile, last sweep of the tile), and from them, with use_active's slot rule, the tiles whose
    // sweeps compact active edges, in order: the staging ring copies the k-th one's host lists during the (k-1)-th
    // O32: the tiles' order in each phase. With the host state's pipeline on a two-layer model (flow) the phases are
    // not drained: the last sweeps take first the tiles whose ghost rows' tiles (src_t) wrote their outputs out
    // earliest, the backward sweeps first the tiles whose rows' gradient adds (from the tiles in dep_t) end earliest
    const bool flow = st->pipe && !wave && L == 2;
    std::vector<int> ord_f((size_t)T), ord_l((size_t)T), ord_b((size_t)T);
    std::vector<std::vector<int>> src_t, dep_t, g_own;
    // f_dev: the last forward tile, whose outputs stay in the layer buffer for its last sweep (first of the phase);
    // k_dev: the last last-layer tile, whose own gradient rows stay on the device for its backward sweep (first)
    int f_dev = -1, k_dev = -1;
    for (int64_t i = 0; i < T; ++i) ord_f[(size_t)i] = ord_l[(size_t)i] = ord_b[(size_t)i] = (int)i;
    if (flow) {
        src_t.assign((size_t)T, {});
        dep_t.assign((size_t)T, {});
        g_own.assign((size_t)T, {});
        std::vector<std::pair<int64_t, int>> base;
        for (int64_t i = 0; i < T; ++i)
            if (lists[(size_t)i].n_local > 0) base.push_back({lists[(size_t)i].hbase, (int)i});
        std::sort(base.begin(), base.end());
        std::vector<char> seen((size_t)T), self_ghost((size_t)T, 0);
        for (int64_t k = 0; k < T; ++k) {
            std::fill(seen.begin(), seen.end(), 0);
            g_own[(size_t)k].reserve(lists[(size_t)k].h_ghost.size());
            for (int g : lists[(size_t)k].h_ghost) {
                const auto it = std::upper_bound(base.begin(), base.end(), std::make_pair((int64_t)g, (int)T));
                const int j = it == base.begin() ? -1 : std::prev(it)->second;
                g_own[(size_t)k].push_back(j);
                if (j < 0) continue;
                if (j == (int)k) self_ghost[(size_t)k] = 1;
                if (j != (int)k && !seen[(size_t)j]) {
                    seen[(size_t)j] = 1;
                    src_t[(size_t)k].push_back(j);
                    dep_t[(size_t)j].push_back((int)k);
                }
            }
        }
        std::vector<int64_t> ready((size_t)T), pos((size_t)T);
        if (T >= 2 && !self_ghost[(size_t)(T - 1)]) f_dev = (int)(T - 1);
        for (int64_t k = 0; k < T; ++k) {
            ready[(size_t)k] = k == f_dev ? -1 : k;
            for (int j : src_t[(size_t)k]) ready[(size_t)k] = std::max<int64_t>(ready[(size_t)k], j);
        }
        std::stable_sort(ord_l.begin(), ord_l.end(), [&](int x, int y) { return ready[(size_t)x] < ready[(size_t)y]; });
        if (f_dev >= 0) {  // its outputs survive in the layer buffer only until another tile's last sweep: first
            ord_l.erase(std::find(ord_l.begin(), ord_l.end(), f_dev));
            ord_l.insert(ord_l.begin(), f_dev);
        }
        for (int64_t q = 0; q < T; ++q) pos[(size_t)ord_l[(size_t)q]] = q;
        if (T >= 2 && !self_ghost[(size_t)ord_l[(size_t)(T - 1)]] && ord_l[(size_t)(T - 1)] != f_dev)
            k_dev = ord_l[(size_t)(T - 1)];
        for (int64_t i = 0; i < T; ++i) {
            ready[(size_t)i] = i == k_dev ? -1 : pos[(size_t)i];
            for (int j : dep_t[(size_t)i]) ready[(size_t)i] = std::max(ready[(size_t)i], pos[(size_t)j]);
        }
        std::stable_sort(ord_b.begin(), ord_b.end(), [&](int x, int y) { return ready[(size_t)x] < ready[(size_t)y]; });
        if (tile_times)
            std::fprintf(stderr, "tile host state order: own rows on the device for tiles %d (last sweeps) and %d "
                                 "(backward sweeps)\n", f_dev, k_dev);
    }
    // O32 alias: block j's readers and adders in the last sweeps are the same tiles ({j} and dep_t[j]); from the
    // first of them to the last its gradients go to a window, which the last one folds into x before its own adds
    std::vector<int64_t> fold_at;
    std::vector<int> win_of;
    std::vector<char> win_keep;  // the block's gradients stay in its window (read there by the backward sweeps)
    std::vector<std::vector<int>> folds, opens;
    int64_t max_local = 0, sum_w = 0;
    std::vector<int64_t> cum_w(5, 0);
    if (flow && st->alias) {
        std::vector<int64_t> pos((size_t)T), first((size_t)T);
        for (int64_t q = 0; q < T; ++q) pos[(size_t)ord_l[(size_t)q]] = q;
        fold_at.assign((size_t)T, -1);
        win_of.assign((size_t)T, -1);
        folds.assign((size_t)T, {});
        opens.assign((size_t)T, {});
        for (int64_t j = 0; j < T; ++j) {
            first[(size_t)j] = fold_at[(size_t)j] = pos[(size_t)j];
            for (int k : dep_t[(size_t)j]) {
                first[(size_t)j] = std::min(first[(size_t)j], pos[(size_t)k]);
                fold_at[(size_t)j] = std::max(fold_at[(size_t)j], pos[(size_t)k]);
            }
            max_local = std::max<int64_t>(max_local, lists[(size_t)j].n_local);
            if (lists[(size_t)j].n_local == 0) continue;
            folds[(size_t)fold_at[(size_t)j]].push_back((int)j);
            if (first[(size_t)j] < fold_at[(size_t)j]) opens[(size_t)first[(size_t)j]].push_back((int)j);
        }
        std::vector<int> free_w, holder;  // holder[w]: the block whose last reader freed window w last
        int n_win = 0;
        win_keep.assign((size_t)T, 1);
        for (int64_t q = 0; q < T; ++q) {  // a fold frees its window before this tile's opens take one
            for (int j : folds[(size_t)q])
                if (win_of[(size_t)j] >= 0) {
                    free_w.push_back(win_of[(size_t)j]);
                    holder[(size_t)win_of[(size_t)j]] = j;
                }
            for (int j : opens[(size_t)q]) {
                if (free_w.empty()) {
                    free_w.push_back(n_win++);
                    holder.push_back(-1);
                }
                const int w = free_w.back();
                free_w.pop_back();
                if (holder[(size_t)w] >= 0) win_keep[(size_t)holder[(size_t)w]] = 0;  // that block must fold
                holder[(size_t)w] = -1;
                win_of[(size_t)j] = w;
            }
        }
        // a block keeps its gradients in its window unless a later block takes the window; folds only the others
        for (int64_t q = 0; q < T; ++q) {
            std::vector<int> f;
            for (int j : folds[(size_t)q])
                if (win_of[(size_t)j] < 0 || !win_keep[(size_t)j]) f.push_back(j);
            folds[(size_t)q].swap(f);
        }
        for (int64_t j = 0; j < T; ++j)
            if (win_of[(size_t)j] < 0) win_keep[(size_t)j] = 0;
        for (int l = 0; l <= h->gen->out_lmax(L - 2); ++l) cum_w[(size_t)l + 1] = cum_w[(size_t)l] + width(L - 2, l);
        sum_w = cum_w[(size_t)h->gen->out_lmax(L - 2) + 1];
        while ((int)st->win.size() < n_win) {
            st->win.emplace_back(new HostBufferGuard());
            st->win_floats.push_back(0);
        }
        for (int w = 0; w < n_win; ++w)
            if ((int64_t)st->win_floats[(size_t)w] < max_local * sum_w) {
                HostBufferGuard& g = *st->win[(size_t)w];
                if (g.p) cudaFreeHost(g.p);
                g.p = nullptr;
                g.n = 0;
                st->host_bytes -= (double)st->win_floats[(size_t)w] * sizeof(float);
                st->win_floats[(size_t)w] = 0;
                const size_t bytes = (size_t)(max_local * sum_w) * sizeof(float);
                if (!pinned_take(h, g, bytes)) {
                    loup::set_error("tile host state: %.2f GB of pinned host memory not available", bytes / 1e9);
                    return -1;
                }
                st->win_floats[(size_t)w] = (size_t)(max_local * sum_w);
                st->host_bytes += (double)bytes;
            }
        tick("host windows");
    }
    h->pinned_spare.clear();  // O32: the spares this state's set-up did not take
    if (tile_times)
        std::fprintf(stderr, "tile host memory: %.1f MB pinned (%d windows), %.1f MB of device state\n",
                     st->host_bytes / 1048576.0, (int)st->win.size(), st->bytes / 1048576.0);
    auto win_p = [&](int j) { return static_cast<float*>(st->win[(size_t)win_of[(size_t)j]]->p); };
    if (st->pipe && st->hp.tile_events((size_t)T) != 0) {
        loup::set_error("tile host state: cannot create the copy events");
        return -1;
    }
    std::vector<int> comp_tiles;
    size_t next_comp = 0;
    const bool stage = st->stage == 1;
    if (stage) {
        std::vector<std::pair<int, bool>> seq;
        if (wave) {
            for (const loup::SweepStep& s : st->steps) seq.push_back({s.tile, s.sweep == 3});
        } else {
            for (int k = 0; k < 2 * (L - 1) + 1; ++k)
                for (int i : k < L - 1 ? ord_f : k == L - 1 ? ord_l : ord_b) seq.push_back({i, k == 2 * (L - 1)});
        }
        // use_active's rule: a full slot if one is free, else (compact lists) a compact slot; either keeps the
        // tile's later sweeps from compacting
        std::vector<int> fr = st->act_free, cfr = st->cact_free, slot(lists.size(), -1), cslot(lists.size(), -1);
        std::vector<char> seen(lists.size(), 0);
        for (const auto& [i, is_last] : seq) {
            bool comp;
            if (!seen[(size_t)i]) {
                seen[(size_t)i] = 1;
                comp = true;
                if (!fr.empty()) { slot[(size_t)i] = fr.back(); fr.pop_back(); }
                else if (lists[(size_t)i].compact && !cfr.empty()) { cslot[(size_t)i] = cfr.back(); cfr.pop_back(); }
            } else {
                comp = slot[(size_t)i] < 0 && cslot[(size_t)i] < 0;
            }
            if (comp) comp_tiles.push_back(i);
            if (is_last && slot[(size_t)i] >= 0) { fr.push_back(slot[(size_t)i]); slot[(size_t)i] = -1; }
            if (is_last && cslot[(size_t)i] >= 0) { cfr.push_back(cslot[(size_t)i]); cslot[(size_t)i] = -1; }
        }
        // the buffers are free once the stream reaches here (an earlier call's sweeps read them)
        for (int b = 0; b < 2; ++b) CUDA_CHECK(cudaEventRecord(st->ring.used[b], h->stream));
    }
    auto stage_copy = [&](size_t k) -> int {  // the k-th compaction's lists into buffer k % 2
        if (k >= comp_tiles.size()) return 0;
        const TileList& t = lists[(size_t)comp_tiles[k]];
        StageRing& r = st->ring;
        const int b = (int)(k % 2);
        CUDA_CHECK(cudaStreamWaitEvent(r.copy, r.used[b], 0));
        if (t.E)
            CUDA_CHECK(cudaMemcpyAsync(r.buf[b].p, t.host_edges.p, (size_t)t.E * (t.compact ? 8 : kTileFullEdgeB),
                                       cudaMemcpyHostToDevice, r.copy));
        CUDA_CHECK(cudaEventRecord(r.copied[b], r.copy));
        return 0;
    };
    if (stage && stage_copy(0) != 0) return -1;
    // O32: a compact host list's compaction inputs, decoded into the handle's own list buffers on the stream
    auto host_decode = [&](const TileList& t, const int* snd, const char4* code) {
        tile_decode_edges_kernel<<<(unsigned)((t.n_local + 3) / 4), 128, 0, h->stream>>>(
            t.n_local, h->cell, static_cast<const int*>(t.row_ptr.p), snd, code, borrow.senders,
            borrow.shift_cart);
        h->d_senders = borrow.senders;
        h->d_shift_cart = borrow.shift_cart;
    };
    // A sweep that compacts reads its tile's edges from the staged buffer: returns the buffer (-1 none, -2 error)
    auto stage_use = [&](const TileList& t, DomainSweep& sw) -> int {
        if (sw.active_ready || sw.restore_code) return -1;
        if (!stage) {  // over the bus: a compact list's 8 B per edge, read once by the decode
            if (t.compact) {
                host_decode(t, t.h_csnd, t.h_ccode);
                sw.pack_in = t.h_ccode;
            }
            return -1;
        }
        const size_t k = next_comp++;
        if (k >= comp_tiles.size() || comp_tiles[k] != (int)(&t - lists.data())) {
            std::fprintf(stderr, "loupmd: tile list staging out of step; reading the host lists\n");
            return -1;  // not reached while the slot rule above matches use_active
        }
        StageRing& r = st->ring;
        const int b = (int)(k % 2);
        if (cudaStreamWaitEvent(h->stream, r.copied[b], 0) != cudaSuccess) return -2;
        char* dp = static_cast<char*>(r.buf[b].p);
        const size_t e = (size_t)t.E;
        if (t.compact) {
            host_decode(t, reinterpret_cast<const int*>(dp), reinterpret_cast<const char4*>(dp + e * 4));
            sw.pack_in = reinterpret_cast<const char4*>(dp + e * 4);
        } else {
            h->d_shift_cart = reinterpret_cast<double*>(dp);
            h->d_senders = reinterpret_cast<int*>(dp + e * 24);
        }
        if (stage_copy(k + 1) != 0) return -2;
        return b;
    };
    auto stage_done = [&](int b) -> int {  // after the sweep: its buffer may take the next copy
        if (b >= 0) CUDA_CHECK(cudaEventRecord(st->ring.used[b], h->stream));
        return 0;
    };
    auto row_atom = [](const TileList& t) { return static_cast<const int*>(t.row_atom.p); };
    // The rows of x and dx: the atoms' own rows, or with the wavefront their rows in the pool
    auto row_x = [&](const TileList& t) { return static_cast<const int*>(wave ? t.row_slot.p : t.row_atom.p); };
    auto fold_forces = [&](const TileList& t) {
        tile_scatter_add_rows_kernel<double><<<grid((int64_t)t.rows * 3), 256, 0, h->stream>>>(
            t.rows, 3, row_atom(t), h->d_forces_f64, static_cast<double*>(d_forces.p));
    };
    // O32: the host state's arrays of layer t, order l
    auto hxp = [&](int t, int l) { return static_cast<float*>(st->hx[(size_t)t * 4 + l].p); };
    auto hdxp = [&](int t, int l) { return static_cast<float*>((st->alias ? st->hx : st->hdx)[(size_t)t * 4 + l].p); };
    // O32: n floats from src to dst on the main stream, as a kernel
    auto dcopy = [&](float* dst, const float* src, int64_t n) {
        if (n <= 0) return;
        const bool v = ((((uintptr_t)dst) | ((uintptr_t)src)) & 15) == 0;
        const int64_t n4 = v ? n / 4 : 0;
        if (n4)
            tile_copy_floats_kernel<<<(unsigned)std::min<int64_t>((n4 + 255) / 256, 4096), 256, 0, h->stream>>>(
                n4, reinterpret_cast<const float4*>(src), reinterpret_cast<float4*>(dst));
        if (n - n4 * 4)
            tile_copy_floats_tail_kernel<<<(unsigned)std::min<int64_t>((n - n4 * 4 + 255) / 256, 4096), 256, 0,
                                           h->stream>>>(n - n4 * 4, src + n4 * 4, dst + n4 * 4);
    };
    // O32 pipeline (st->pipe): waits for the host threads and both streams (phase boundaries, synchronous paths)
    const bool pipe = st->pipe;
    HostPipe& P = st->hp;
    std::vector<std::shared_future<int>> in_fut(2);
    std::shared_future<int> g_fut[2], g_last;
    std::vector<std::shared_future<int>> g_tile(flow ? (size_t)T : 0);  // each tile's gradient adds
    int64_t fwd_k = 0;
    // debug: microseconds of the host threads' work (gathers, copy waits, adds) and of the main thread's waits
    std::atomic<long long> us_gather{0}, us_gcopy{0}, us_add{0}, us_wait_in{0}, us_wait_g{0};
    auto now_us = [] {
        return std::chrono::duration_cast<std::chrono::microseconds>(
                   std::chrono::steady_clock::now().time_since_epoch()).count();
    };
    auto drain = [&]() -> int {
        if (!pipe) return 0;
        int bad = 0;
        for (auto& f : in_fut)
            if (f.valid()) { bad |= f.get(); f = std::shared_future<int>(); }
        for (auto& f : g_fut)
            if (f.valid()) { bad |= f.get(); f = std::shared_future<int>(); }
        g_last = std::shared_future<int>();
        CUDA_CHECK(cudaStreamSynchronize(h->stream));
        CUDA_CHECK(cudaStreamSynchronize(P.copy));
        CUDA_CHECK(cudaStreamSynchronize(P.down));
        if (bad) { loup::set_error("tile host state: a host-side copy failed"); return -1; }
        return 0;
    };
    // The last sweep's input for tile i: locals copied from their block, ghosts gathered on a host thread
    auto issue_in = [&](int64_t q) {  // q: the position in ord_l
        if (q >= T) return;
        const int b = (int)(q % 2), ti = ord_l[(size_t)q];
        const TileList* tp = &lists[(size_t)ti];
        const int layer = L - 2, dev = h->device_id;
        in_fut[b] = std::async(std::launch::async, [&, tp, b, ti, layer, dev]() -> int {
            const TileList& t = *tp;
            if (cudaSetDevice(dev) != cudaSuccess) return 1;
            if (cudaEventSynchronize(P.ev[HostPipe::kIn][b]) != cudaSuccess) return 1;  // staging b is free
            if (cudaStreamWaitEvent(P.copy, P.ev[HostPipe::kInUsed][b], 0) != cudaSuccess) return 1;
            // the tile's own rows and its ghosts' tiles' rows are written out (flow: not drained before)
            const bool own_dev = ti == f_dev;  // its own rows are still in the layer buffer
            if (!own_dev && cudaStreamWaitEvent(P.copy, P.tile_out[(size_t)ti], 0) != cudaSuccess) return 1;
            if (flow)
                for (int j : src_t[(size_t)ti])
                    if (cudaEventSynchronize(P.tile_out[(size_t)j]) != cudaSuccess) return 1;
            float* da = static_cast<float*>(P.a[b].p);
            float* sp = static_cast<float*>(P.in[b].p);
            int64_t off = 0;
            const int64_t G = t.rows - t.n_local;
            const long long t0 = now_us();
            for (int l = 0; l <= h->gen->out_lmax(layer); ++l) {
                const int64_t w = width(layer, l);
                const float* src = hxp(layer, l);
                if (!own_dev && cudaMemcpyAsync(da + off, src + t.hbase * w, (size_t)t.n_local * w * 4,
                                                cudaMemcpyHostToDevice, P.copy) != cudaSuccess) return 1;
                if (G) {
                    float* sg = sp + off + (int64_t)t.n_local * w;
                    par_rows(G, w, [&](int64_t a0, int64_t a1) {
                        for (int64_t g = a0; g < a1; ++g)
                            std::memcpy(sg + g * w, src + (int64_t)t.h_ghost[(size_t)g] * w, w * 4);
                    });
                    if (cudaMemcpyAsync(da + off + (int64_t)t.n_local * w, sg, (size_t)G * w * 4,
                                        cudaMemcpyHostToDevice, P.copy) != cudaSuccess) return 1;
                }
                off += (int64_t)t.rows * w;
            }
            us_gather += now_us() - t0;
            return cudaEventRecord(P.ev[HostPipe::kIn][b], P.copy) != cudaSuccess;
        }).share();
    };
    auto take_in = [&](const TileList& t, int64_t q) -> int {  // into the layer's buffers, then the next input starts
        const int b = (int)(q % 2);
        const long long w0 = now_us();
        if (in_fut[b].get() != 0) { loup::set_error("tile host state: a host-side copy failed"); return -1; }
        us_wait_in += now_us() - w0;
        CUDA_CHECK(cudaStreamWaitEvent(h->stream, P.ev[HostPipe::kIn][b], 0));
        int64_t off = 0;
        const int layer = L - 2;
        const int64_t r0 = (&t - lists.data()) == f_dev ? t.n_local : 0;  // the own rows stayed in the buffer
        for (int l = 0; l <= h->gen->out_lmax(layer); ++l) {
            const int64_t w = width(layer, l);
            dcopy(h->gen->layer_out(layer, l) + r0 * w, static_cast<float*>(P.a[b].p) + off + r0 * w,
                  (int64_t)(t.rows - r0) * w);
            off += (int64_t)t.rows * w;
        }
        CUDA_CHECK(cudaEventRecord(P.ev[HostPipe::kInUsed][b], h->stream));
        issue_in(q + 1);
        return 0;
    };
    // The last sweep's gradient rows: out through slot b, added on a host thread after the previous tile's adds
    const bool alias = flow && st->alias;
    auto put_grad = [&](const TileList& t, int64_t q) -> int {
        const int64_t i = &t - lists.data();
        const int b = (int)(q % 2);
        const long long w0 = now_us();
        if (g_fut[b].valid() && g_fut[b].get() != 0) {
            loup::set_error("tile host state: a host-side add failed");
            return -1;
        }
        us_wait_g += now_us() - w0;
        CUDA_CHECK(cudaStreamWaitEvent(h->stream, P.ev[HostPipe::kOut][b], 0));  // the forward outputs left slot b
        const int layer = L - 2;
        int64_t off = 0;
        for (int l = 0; l <= h->gen->out_lmax(layer); ++l) {
            const int64_t w = width(layer, l);
            dcopy(static_cast<float*>(P.b[b].p) + off, h->gen->layer_out_grad(layer, l), (int64_t)t.rows * w);
            off += (int64_t)t.rows * w;
        }
        CUDA_CHECK(cudaEventRecord(P.ev[HostPipe::kG][b], h->stream));
        const TileList* tp = &t;
        const int dev = h->device_id;
        std::shared_future<int> prev = g_last;
        // the copies to and from the host run one at a time, in the order queued: this one waits for its sweep, so
        // it goes after the next tile's input copies (issued by take_in before this sweep), not ahead of them
        std::shared_future<int> next_in = q + 1 < T ? in_fut[(size_t)((q + 1) % 2)] : std::shared_future<int>();
        g_fut[b] = std::async(std::launch::async, [&, tp, b, layer, dev, prev, off, q, next_in]() -> int {
                       const TileList& tt = *tp;
                       if (cudaSetDevice(dev) != cudaSuccess) return 1;
                       if (next_in.valid()) next_in.wait();
                       if (cudaStreamWaitEvent(P.down, P.ev[HostPipe::kG][b], 0) != cudaSuccess) return 1;
                       float* so = static_cast<float*>(P.out[b].p);
                       const long long c0 = now_us();
                       if (cudaMemcpyAsync(so, P.b[b].p, (size_t)off * 4, cudaMemcpyDeviceToHost, P.down) !=
                               cudaSuccess ||
                           cudaEventRecord(P.ev[HostPipe::kGh][b], P.down) != cudaSuccess ||
                           cudaEventSynchronize(P.ev[HostPipe::kGh][b]) != cudaSuccess)
                           return 1;
                       us_gcopy += now_us() - c0;
                       if (prev.valid() && prev.get() != 0) return 1;  // the adds in tile order
                       const long long a0t = now_us();
                       int64_t o = 0;
                       const int N = tt.n_local;
                       if (alias) {
                           const int ti = (int)(tp - lists.data());
                           for (int j : folds[(size_t)q]) {  // block j's last reader has its inputs
                               const TileList& tj = lists[(size_t)j];
                               const int wj = win_of[(size_t)j];
                               for (int l = 0; l <= h->gen->out_lmax(layer); ++l) {
                                   const int64_t w = width(layer, l);
                                   float* xd = hxp(layer, l) + tj.hbase * w;
                                   const float* ws = wj < 0 ? nullptr : win_p(j) + max_local * cum_w[(size_t)l];
                                   par_rows(tj.n_local, w, [&](int64_t a0, int64_t a1) {
                                       if (ws) std::memcpy(xd + a0 * w, ws + a0 * w, (size_t)(a1 - a0) * w * 4);
                                       else std::memset(xd + a0 * w, 0, (size_t)(a1 - a0) * w * 4);
                                   });
                               }
                           }
                           for (int j : opens[(size_t)q]) {
                               float* ws = win_p(j);
                               const int64_t nl = lists[(size_t)j].n_local;
                               for (int l = 0; l <= h->gen->out_lmax(layer); ++l)
                                   std::memset(ws + max_local * cum_w[(size_t)l], 0,
                                               (size_t)(nl * width(layer, l)) * 4);
                           }
                           const std::vector<int>& own = g_own[(size_t)ti];
                           const int64_t r0 = ti == k_dev ? N : 0;  // k_dev: its own rows are added on the device
                           for (int l = 0; l <= h->gen->out_lmax(layer); ++l) {
                               const int64_t w = width(layer, l);
                               float* xl = hxp(layer, l);
                               const float* gsrc = so + o;
                               par_adds(
                                   tt.rows - r0, w,
                                   [&](int64_t i) {
                                       const int64_t r = i + r0;
                                       return r < N ? tt.hbase + r : (int64_t)tt.h_ghost[(size_t)(r - N)];
                                   },
                                   [&](int64_t i) {
                                       const int64_t r = i + r0;
                                       const int j = r < N ? ti : own[(size_t)(r - N)];
                                       const int64_t at = r < N ? r : (int64_t)tt.h_ghost[(size_t)(r - N)] -
                                                                          lists[(size_t)j].hbase;
                                       float* row = (!win_keep[(size_t)j] && fold_at[(size_t)j] <= q)
                                                        ? xl + (lists[(size_t)j].hbase + at) * w
                                                        : win_p(j) + max_local * cum_w[(size_t)l] + at * w;
                                       const float* g = gsrc + r * w;
                                       for (int64_t c = 0; c < w; ++c) row[c] += g[c];
                                   });
                               o += (int64_t)tt.rows * w;
                           }
                           us_add += now_us() - a0t;
                           return 0;
                       }
                       const int64_t r0 = (int)(tp - lists.data()) == k_dev ? N : 0;
                       for (int l = 0; l <= h->gen->out_lmax(layer); ++l) {
                           const int64_t w = width(layer, l);
                           float* d = hdxp(layer, l);
                           const float* gsrc = so + o;
                           auto hrow = [&](int64_t i) {
                               const int64_t r = i + r0;
                               return r < N ? tt.hbase + r : (int64_t)tt.h_ghost[(size_t)(r - N)];
                           };
                           par_adds(tt.rows - r0, w, hrow, [&](int64_t i) {
                               float* row = d + hrow(i) * w;
                               const float* g = gsrc + (i + r0) * w;
                               for (int64_t c = 0; c < w; ++c) row[c] += g[c];
                           });
                           o += (int64_t)tt.rows * w;
                       }
                       us_add += now_us() - a0t;
                       return 0;
                   }).share();
        g_last = g_fut[b];
        if (flow) g_tile[(size_t)i] = g_fut[b];
        return 0;
    };
    // The forward sweeps' outputs: the locals' rows out through slot a
    auto put_out = [&](const TileList& t, int layer) -> int {
        const int b = (int)(fwd_k++ % 2);
        CUDA_CHECK(cudaStreamWaitEvent(h->stream, P.ev[HostPipe::kOut][b], 0));
        int64_t off = 0;
        for (int l = 0; l <= h->gen->out_lmax(layer); ++l) {
            const int64_t w = width(layer, l);
            dcopy(static_cast<float*>(P.b[b].p) + off, h->gen->layer_out(layer, l), (int64_t)t.n_local * w);
            off += (int64_t)t.n_local * w;
        }
        CUDA_CHECK(cudaEventRecord(P.ev[HostPipe::kFwd][b], h->stream));
        CUDA_CHECK(cudaStreamWaitEvent(P.down, P.ev[HostPipe::kFwd][b], 0));
        off = 0;
        for (int l = 0; l <= h->gen->out_lmax(layer); ++l) {
            const int64_t w = width(layer, l);
            CUDA_CHECK(cudaMemcpyAsync(hxp(layer, l) + t.hbase * w, static_cast<float*>(P.b[b].p) + off,
                                       (size_t)t.n_local * w * 4, cudaMemcpyDeviceToHost, P.down));
            off += (int64_t)t.n_local * w;
        }
        CUDA_CHECK(cudaEventRecord(P.ev[HostPipe::kOut][b], P.down));
        CUDA_CHECK(cudaEventRecord(P.tile_out[(size_t)(&t - lists.data())], P.down));
        return 0;
    };
    // The backward sweeps' adjoints: the locals' gradient rows in through slot a, one tile ahead
    auto issue_adj = [&](int64_t q, int layer) -> int {  // q: the position in ord_b
        if (q >= T) return 0;
        const int ti = ord_b[(size_t)q];
        const TileList& t = lists[(size_t)ti];
        const int b = (int)(q % 2);
        if (flow) {  // the adds into the tile's rows: its own and those of the tiles with them as ghosts
            const long long w0 = now_us();
            int bad = (ti != k_dev && g_tile[(size_t)ti].valid()) ? g_tile[(size_t)ti].get() : 0;
            for (int j : dep_t[(size_t)ti])
                if (g_tile[(size_t)j].valid()) bad |= g_tile[(size_t)j].get();
            us_wait_g += now_us() - w0;
            if (bad) { loup::set_error("tile host state: a host-side add failed"); return -1; }
        }
        CUDA_CHECK(cudaStreamWaitEvent(P.copy, P.ev[HostPipe::kAdjUsed][b], 0));
        CUDA_CHECK(cudaStreamWaitEvent(P.copy, P.ev[HostPipe::kInUsed][b], 0));  // the last sweeps' inputs left slot a
        int64_t off = 0;
        for (int l = 0; l <= h->gen->out_lmax(layer); ++l) {
            const int64_t w = width(layer, l);
            // k_dev with the alias: the others' adds went to its window, or nowhere (no window: none came)
            const bool kw = alias && (win_keep[(size_t)ti] || (ti == k_dev && win_of[(size_t)ti] >= 0));
            float* dst = static_cast<float*>(P.a[b].p) + off;
            if (alias && ti == k_dev && win_of[(size_t)ti] < 0) {
                CUDA_CHECK(cudaMemsetAsync(dst, 0, (size_t)t.n_local * w * 4, P.copy));
            } else {
                const float* src = kw ? win_p(ti) + max_local * cum_w[(size_t)l] : hdxp(layer, l) + t.hbase * w;
                CUDA_CHECK(cudaMemcpyAsync(dst, src, (size_t)t.n_local * w * 4, cudaMemcpyHostToDevice, P.copy));
            }
            off += (int64_t)t.n_local * w;
        }
        CUDA_CHECK(cudaEventRecord(P.ev[HostPipe::kAdjIn][b], P.copy));
        return 0;
    };
    auto gather_input = [&](const TileList& t, int layer) -> int {  // layer `layer`'s output rows, locals and ghosts
        for (int l = 0; layer >= 0 && l <= h->gen->out_lmax(layer); ++l) {
            const int64_t w = width(layer, l);
            if (!hs) {
                tile_gather_rows_kernel<<<grid((int64_t)t.rows * w), 256, 0, h->stream>>>(
                    t.rows, (int)w, row_x(t), fx(layer, l), h->gen->layer_out(layer, l));
                continue;
            }
            if (drain() != 0) return -1;
            float* dst = h->gen->layer_out(layer, l);
            CUDA_CHECK(cudaMemcpyAsync(dst, hxp(layer, l) + t.hbase * w, (size_t)t.n_local * w * 4,
                                       cudaMemcpyHostToDevice, h->stream));
            const int64_t G = t.rows - t.n_local;
            if (G == 0) continue;
            CUDA_CHECK(cudaStreamSynchronize(h->stream));  // the staging is free, the host rows written
            float* sp = static_cast<float*>(st->stage_in.p);
            const float* src = hxp(layer, l);
            par_rows(G, w, [&](int64_t a, int64_t b) {
                for (int64_t g = a; g < b; ++g) std::memcpy(sp + g * w, src + (int64_t)t.h_ghost[(size_t)g] * w, w * 4);
            });
            CUDA_CHECK(cudaMemcpyAsync(dst + (int64_t)t.n_local * w, sp, (size_t)G * w * 4, cudaMemcpyHostToDevice,
                                       h->stream));
        }
        return 0;
    };
    auto scatter_grad = [&](const TileList& t, int layer) -> int {  // the gradient of layer `layer`'s output
        for (int l = 0; layer >= 0 && l <= h->gen->out_lmax(layer); ++l) {
            const int64_t w = width(layer, l);
            if (!hs) {
                tile_scatter_add_rows_kernel<float><<<grid((int64_t)t.rows * w), 256, 0, h->stream>>>(
                    t.rows, (int)w, row_x(t), h->gen->layer_out_grad(layer, l), fdx(layer, l));
                continue;
            }
            if (drain() != 0) return -1;
            float* sp = static_cast<float*>(st->stage_out.p);
            CUDA_CHECK(cudaMemcpyAsync(sp, h->gen->layer_out_grad(layer, l), (size_t)t.rows * w * 4,
                                       cudaMemcpyDeviceToHost, h->stream));
            CUDA_CHECK(cudaStreamSynchronize(h->stream));
            float* d = hdxp(layer, l);
            const int N = t.n_local;
            auto hrow = [&](int64_t r) { return r < N ? t.hbase + r : (int64_t)t.h_ghost[(size_t)(r - N)]; };
            par_adds(t.rows, w, hrow, [&](int64_t r) {
                float* row = d + hrow(r) * w;
                const float* g = sp + r * w;
                for (int64_t c = 0; c < w; ++c) row[c] += g[c];
            });
        }
        return 0;
    };
    // The active edges: the tile's kept buffers (compacted in its first sweep of the call, read by the others) or
    // the handle's own (compacted in every sweep)
    auto use_active = [&](const TileList& t, DomainSweep& sw, bool last_sweep) {
        bool first = false;
        if (t.act_call != call) {  // the tile's first sweep of this call: take a slot if one is free
            t.act_call = call;
            t.act_slot = t.cact_slot = -1;
            first = true;
            if (!st->act_free.empty()) {
                t.act_slot = st->act_free.back();
                st->act_free.pop_back();
            } else if (t.compact && !st->cact_free.empty()) {  // O32: else a compact slot
                t.cact_slot = st->cact_free.back();
                st->cact_free.pop_back();
            }
        } else if (t.act_slot >= 0) {
            sw.active_ready = true;
        }
        if (t.act_slot < 0) {
            borrow.own_active();
            if (t.cact_slot >= 0) {  // row pointers and senders in the slot, the rest in the handle's buffers
                const CompactSlot& cs = st->cact_slots[(size_t)t.cact_slot];
                h->d_act_row_ptr = static_cast<int*>(cs.row_ptr.p);
                h->d_act_senders = static_cast<int*>(cs.senders.p);
                if (first) sw.pack_out = static_cast<char4*>(cs.code.p);  // pack_in: stage_use
                else sw.restore_code = static_cast<const char4*>(cs.code.p);
                if (last_sweep) {
                    st->cact_free.push_back(t.cact_slot);
                    t.cact_slot = -1;
                }
            }
            return;
        }
        const ActiveSlot& sl = st->act_slots[(size_t)t.act_slot];
        h->d_act_row_ptr = static_cast<int*>(sl.row_ptr.p);
        h->d_act_senders = static_cast<int*>(sl.senders.p);
        h->d_act_receivers = static_cast<int*>(sl.receivers.p);
        h->d_act_slab = static_cast<int*>(sl.slab.p);
        h->d_act_vec_len = static_cast<float4*>(sl.vec_len.p);
        h->d_act_t_sx = static_cast<float2*>(sl.t_sx.p);
        if (last_sweep) {  // one stream: the next compaction into this slot runs after this sweep
            st->act_free.push_back(t.act_slot);
            t.act_slot = -1;
        }
    };
    auto forward = [&](const TileList& t, int layer) -> int {
        if (restore_tile_list(h, t) != 0) return -1;
        if (layer == 0) energy += t.e0;
        if (gather_input(t, layer - 1) != 0) return -1;
        DomainSweep sw;
        sw.kind = loup::GenericPassInputs::SweepForward;
        sw.layer = layer;
        use_active(t, sw, false);
        if (layer == 0 && st->keep_l0 == 1) sw.keep0 = static_cast<float*>(t.keep0.p);
        const int sb = stage_use(t, sw);
        if (sb == -2) return -1;
        record_force_pass(h, stress, false, &sw);
        if (stage_done(sb) != 0) return -1;
        if (pipe) return put_out(t, layer);
        // the wavefront's host pool: the block may hold an earlier tile's gradients, which its last sweep's copy-in
        // (queued on the stream) may still read
        if (hs && wave) CUDA_CHECK(cudaStreamSynchronize(h->stream));
        for (int l = 0; l <= h->gen->out_lmax(layer); ++l) {
            if (hs) {  // the locals' rows are one block of the host state
                const int64_t w = width(layer, l);
                CUDA_CHECK(cudaMemcpyAsync(hxp(layer, l) + t.hbase * w, h->gen->layer_out(layer, l),
                                           (size_t)t.n_local * w * 4, cudaMemcpyDeviceToHost, h->stream));
                if (wave) std::memset(hdxp(layer, l) + t.hbase * w, 0, (size_t)t.n_local * w * 4);
                continue;
            }
            tile_scatter_rows_kernel<<<grid((int64_t)t.n_local * width(layer, l)), 256, 0, h->stream>>>(
                t.n_local, width(layer, l), row_x(t), h->gen->layer_out(layer, l), fx(layer, l));
            if (wave)  // the pool rows its locals take may hold an earlier tile's gradients
                tile_zero_rows_kernel<<<grid((int64_t)t.n_local * width(layer, l)), 256, 0, h->stream>>>(
                    t.n_local, width(layer, l), row_x(t), fdx(layer, l));
        }
        return 0;
    };
    auto last = [&](const TileList& t, int64_t q) -> int {
        if (restore_tile_list(h, t) != 0) return -1;
        if ((pipe ? take_in(t, q) : gather_input(t, L - 2)) != 0) return -1;
        DomainSweep sw;
        sw.kind = loup::GenericPassInputs::SweepLast;
        use_active(t, sw, false);
        const int sb = stage_use(t, sw);
        if (sb == -2) return -1;
        record_force_pass(h, stress, false, &sw);
        if (stage_done(sb) != 0) return -1;
        if ((pipe ? put_grad(t, q) : scatter_grad(t, L - 2)) != 0) return -1;
        fold_forces(t);
        return 0;
    };
    auto backward = [&](const TileList& t, int layer, int64_t q) -> int {
        if (restore_tile_list(h, t) != 0) return -1;
        if (gather_input(t, layer - 1) != 0) return -1;
        DomainSweep sw;
        sw.kind = loup::GenericPassInputs::SweepBackward;
        sw.layer = layer;
        for (int l = 0; l <= h->gen->out_lmax(layer); ++l) {
            float* a = static_cast<float*>(adj[l].p);
            if (pipe) {
                const int bb = (int)(q % 2);
                if (l == 0) CUDA_CHECK(cudaStreamWaitEvent(h->stream, P.ev[HostPipe::kAdjIn][bb], 0));
                int64_t off = 0;
                for (int k = 0; k < l; ++k) off += (int64_t)t.n_local * width(layer, k);
                a = static_cast<float*>(P.a[bb].p) + off;
            } else if (hs) {
                const int64_t w = width(layer, l);
                CUDA_CHECK(cudaMemcpyAsync(a, hdxp(layer, l) + t.hbase * w, (size_t)t.n_local * w * 4,
                                           cudaMemcpyHostToDevice, h->stream));
            } else {
                tile_gather_rows_kernel<<<grid((int64_t)t.n_local * width(layer, l)), 256, 0, h->stream>>>(
                    t.n_local, width(layer, l), row_x(t), fdx(layer, l), a);
            }
            sw.adjoint[l] = a;
        }
        if (pipe && (&t - lists.data()) == k_dev) {  // its own gradient rows, still in ring slot b
            const float* gb = static_cast<const float*>(P.b[(size_t)((T - 1) % 2)].p);
            int64_t ob = 0;
            for (int l = 0; l <= h->gen->out_lmax(layer); ++l) {
                const int64_t n = (int64_t)t.n_local * width(layer, l);
                tile_add_floats_kernel<<<(unsigned)std::min<int64_t>((n + 255) / 256, 4096), 256, 0, h->stream>>>(
                    n, gb + ob, const_cast<float*>(sw.adjoint[l]));  // ring slot a, written above
                ob += (int64_t)t.rows * width(layer, l);
            }
        }
        use_active(t, sw, layer == 0);
        if (layer == 0 && st->keep_l0 == 1) sw.keep0 = static_cast<float*>(t.keep0.p);
        const int sb = stage_use(t, sw);
        if (sb == -2) return -1;
        record_force_pass(h, stress, false, &sw);
        if (stage_done(sb) != 0) return -1;
        if (pipe) {  // slot a may take the tile after next; the next tile's adjoints start
            CUDA_CHECK(cudaEventRecord(P.ev[HostPipe::kAdjUsed][q % 2], h->stream));
            if (issue_adj(q + 1, layer) != 0) return -1;
        }
        if (scatter_grad(t, layer - 1) != 0) return -1;
        fold_forces(t);
        return 0;
    };

    if (note_free() != 0) return -1;
    tick("state buffers");
    if (wave) {  // two-layer models: sweep 1 is layer 0 forward, 2 the last layer, 3 layer 0 backward
        for (const loup::SweepStep& s : st->steps) {
            const TileList& t = lists[(size_t)s.tile];
            if ((s.sweep == 1 ? forward(t, 0) : s.sweep == 2 ? last(t, 0) : backward(t, 0, 0)) != 0) return -1;
        }
        tick("wavefront sweeps");
    } else {
        for (int layer = 0; layer + 1 < L; ++layer) {  // forward sweeps
            for (int i : ord_f)
                if (forward(lists[(size_t)i], layer) != 0) return -1;
            if (!flow && drain() != 0) return -1;
        }
        tick("forward sweeps");
        if (pipe) issue_in(0);
        for (int64_t q = 0; q < T; ++q)  // the last layer
            if (last(lists[(size_t)ord_l[(size_t)q]], q) != 0) return -1;
        if (!flow && drain() != 0) return -1;
        tick("last-layer sweeps");
        for (int layer = L - 2; layer >= 0; --layer) {  // backward sweeps
            if (pipe && issue_adj(0, layer) != 0) return -1;
            for (int64_t q = 0; q < T; ++q)
                if (backward(lists[(size_t)ord_b[(size_t)q]], layer, q) != 0) return -1;
            if (drain() != 0) return -1;
        }
        if (tile_times && pipe)
            std::fprintf(stderr, "tile host state (ms): gathers %.1f, gradient copy-out waits %.1f, adds %.1f; main "
                                 "waits for inputs %.1f, for adds %.1f\n", us_gather / 1e3, us_gcopy / 1e3,
                         us_add / 1e3, us_wait_in / 1e3, us_wait_g / 1e3);
        tick("backward sweeps");
    }
    if (note_free() != 0) return -1;
    h->last_exec = LoupExecution{wave ? LOUP_EXEC_WAVEFRONT : LOUP_EXEC_TILED, receivers, (long long)T, (size_t)budget,
                                 (size_t)std::max(0.0, budget - (double)least_free), keep ? 1 : 0,
                                 h->tile_list_builds, st->host_lists ? 1 : 0, st->host_state ? 1 : 0};
    {
        double e = 0.0;
        CUDA_CHECK(cudaMemcpyAsync(&e, h->d_energy_f64, sizeof(double), cudaMemcpyDeviceToHost, h->stream));
        CUDA_CHECK(cudaMemcpyAsync(virial, h->d_virial_grad_f64, 6 * sizeof(double), cudaMemcpyDeviceToHost,
                                   h->stream));
        CUDA_CHECK(cudaStreamSynchronize(h->stream));
        CUDA_CHECK(cudaGetLastError());
        energy += e;
    }

    if (out_energy_ev) *out_energy_ev = energy;
    if (out_forces)
        CUDA_CHECK(cudaMemcpyAsync(out_forces, d_forces.p, (size_t)n_atoms * 3 * sizeof(double),
                                   cudaMemcpyDeviceToHost, h->stream));
    if (d_out_forces)
        CUDA_CHECK(cudaMemcpyAsync(d_out_forces, d_forces.p, (size_t)n_atoms * 3 * sizeof(double),
                                   cudaMemcpyDeviceToDevice, h->stream));
    CUDA_CHECK(cudaStreamSynchronize(h->stream));
    if (out_stress) {
        const double vol = std::fabs(cell[0] * (cell[4] * cell[8] - cell[5] * cell[7]) -
                                     cell[1] * (cell[3] * cell[8] - cell[5] * cell[6]) +
                                     cell[2] * (cell[3] * cell[7] - cell[4] * cell[6]));
        const double inv_v = 1.0 / vol;
        const double* v = virial;
        out_stress[0] = v[0] * inv_v; out_stress[1] = v[1] * inv_v; out_stress[2] = v[2] * inv_v;
        out_stress[3] = v[1] * inv_v; out_stress[4] = v[3] * inv_v; out_stress[5] = v[4] * inv_v;
        out_stress[6] = v[2] * inv_v; out_stress[7] = v[4] * inv_v; out_stress[8] = v[5] * inv_v;
        if (out_virial) std::copy(virial, virial + 6, out_virial);
    }
    h->save_disk_plans();
    return 0;
}

// ---- Tiled MD on the device (PLAN.md O31) ----
static int tiled_set_state_impl(LoupHandle* h, int n_atoms, const int* atomic_numbers, const double* masses_amu,
                                const double* positions, const double* velocities, const double* cell,
                                const unsigned char* fixed, int receivers, double skin, unsigned long long noise_step,
                                const double* int_state, int int_state_kind) {
    if (!h) return -1;
    if (!positions && !velocities && h->tiled_md && h->tiled_md->n == n_atoms) {
        // The state stays; only the step count of the thermo rows starts anew (a restart at the same state).
        h->tiled_md->md_steps = 0;
        return 0;
    }
    if (n_atoms <= 0 || !atomic_numbers || !masses_amu || !positions || !velocities || !cell) {
        loup::set_error("n_atoms must be positive and atomic_numbers, masses, positions, velocities and cell given");
        return -1;
    }
    if (receivers < 0) { loup::set_error("receivers must not be negative, got %d", receivers); return -1; }
    if (!(skin >= 0.0) || !std::isfinite(skin)) { loup::set_error("skin must be finite and not negative"); return -1; }
    CUDA_CHECK(cudaSetDevice(h->device_id));
    const int n = n_atoms;
    TiledMD* md = h->tiled_md;
    if (!md || md->n != n) {
        release_tiled_md(h);
        md = h->tiled_md = new TiledMD();
        const size_t v3 = (size_t)n * 3 * sizeof(double), v1 = (size_t)n * sizeof(double);
        DeviceBufferGuard* vec3[] = {&md->pos, &md->vel, &md->forces, &md->rnd_vel, &md->rnd_pos};
        DeviceBufferGuard* vec1[] = {&md->masses, &md->inv_m, &md->sqrt_inv_m};
        // through device_malloc, as every buffer that scales with the system: under WSL 2 a plain cudaMalloc past
        // the free memory pages the card out instead of failing (LAMMPS_TILED_PLAN.md LT0)
        for (DeviceBufferGuard* g : vec3) CUDA_CHECK(loup::device_malloc(&g->p, v3));
        for (DeviceBufferGuard* g : vec1) CUDA_CHECK(loup::device_malloc(&g->p, v1));
        CUDA_CHECK(loup::device_malloc(&md->com.p, 6 * sizeof(double)));
        CUDA_CHECK(loup::device_malloc(&md->target.p, 5 * sizeof(double)));
        CUDA_CHECK(loup::device_malloc(&md->step.p, sizeof(unsigned long long)));
        CUDA_CHECK(loup::device_malloc(&md->int_state.p, kIntStateSlots * sizeof(double)));
        CUDA_CHECK(loup::device_malloc(&md->int_work.p, kIntWorkSlots * sizeof(double)));
        CUDA_CHECK(loup::device_malloc(&md->disp.p, 2 * sizeof(unsigned int)));
        CUDA_CHECK(loup::device_malloc(&md->ke.p, sizeof(double)));
        md->n = n;
    }
    std::vector<double> m((size_t)n), im((size_t)n), sim((size_t)n), v(velocities, velocities + (size_t)n * 3);
    md->n_fixed = 0;
    md->total_mass = 0.0;
    for (int i = 0; i < n; ++i) {
        const double mi = masses_amu[i];
        if (!(mi > 0.0) || !std::isfinite(mi)) { loup::set_error("atom %d has mass %g", i, mi); return -1; }
        const bool f = fixed && fixed[i];
        m[(size_t)i] = mi;
        im[(size_t)i] = f ? 0.0 : 1.0 / mi;
        sim[(size_t)i] = f ? 0.0 : std::sqrt(1.0 / mi);
        if (f) { ++md->n_fixed; v[(size_t)i * 3] = v[(size_t)i * 3 + 1] = v[(size_t)i * 3 + 2] = 0.0; }
        md->total_mass += mi;
    }
    const size_t v3 = (size_t)n * 3 * sizeof(double), v1 = (size_t)n * sizeof(double);
    CUDA_CHECK(cudaMemcpyAsync(md->pos.p, positions, v3, cudaMemcpyHostToDevice, h->stream));
    CUDA_CHECK(cudaMemcpyAsync(md->vel.p, v.data(), v3, cudaMemcpyHostToDevice, h->stream));
    CUDA_CHECK(cudaMemcpyAsync(md->masses.p, m.data(), v1, cudaMemcpyHostToDevice, h->stream));
    CUDA_CHECK(cudaMemcpyAsync(md->inv_m.p, im.data(), v1, cudaMemcpyHostToDevice, h->stream));
    CUDA_CHECK(cudaMemcpyAsync(md->sqrt_inv_m.p, sim.data(), v1, cudaMemcpyHostToDevice, h->stream));
    CUDA_CHECK(cudaMemcpyAsync(md->step.p, &noise_step, sizeof(noise_step), cudaMemcpyHostToDevice, h->stream));
    if (int_state) {
        CUDA_CHECK(cudaMemcpyAsync(md->int_state.p, int_state, kIntStateSlots * sizeof(double),
                                   cudaMemcpyHostToDevice, h->stream));
        md->state_kind = int_state_kind;
    } else {
        CUDA_CHECK(cudaMemsetAsync(md->int_state.p, 0, kIntStateSlots * sizeof(double), h->stream));
        md->state_kind = -1;
    }
    CUDA_CHECK(cudaStreamSynchronize(h->stream));  // the host vectors go out of scope
    md->z.assign(atomic_numbers, atomic_numbers + n);
    std::copy(cell, cell + 9, md->cell);
    std::copy(cell, cell + 9, md->plan_cell);
    md->v0 = std::fabs(cell[0] * (cell[4] * cell[8] - cell[5] * cell[7]) - cell[1] * (cell[3] * cell[8] - cell[5] * cell[6]) +
                       cell[2] * (cell[3] * cell[7] - cell[4] * cell[6]));
    md->receivers = receivers;
    md->skin = skin;
    md->forces_current = false;
    md->virial_current = false;
    md->md_steps = 0;
    return 0;
}

// The tiled call on the device positions; the forces stay in md->forces. With `stress` (the barostats, LT6 (a)) the
// virial goes to md->virial. A call that fails in a cell other than the one the cap was planned or set for plans once
// more at this cell (LAMMPS_TILED_PLAN.md LD3: a compressed cell can make the tiles denser than the plan measured).
static int tiled_md_forces(LoupHandle* h, TiledMD* md, long long* tiles, bool stress = false) {
    double e = 0.0, s[9], vir[6] = {0, 0, 0, 0, 0, 0};
    auto call = [&] {
        return evaluate_tiled_impl(h, md->n, md->z.data(), nullptr, md->cell, md->receivers, md->skin, &e, nullptr,
                                   stress ? s : nullptr, tiles, static_cast<const double*>(md->pos.p),
                                   static_cast<double*>(md->forces.p), stress ? vir : nullptr);
    };
    if (call() != 0) {
        if (!md->receivers || memcmp(md->cell, md->plan_cell, sizeof(md->cell)) == 0) return -1;
        (void)cudaGetLastError();
        md->receivers = 0;
        if (call() != 0) return -1;
        std::copy(md->cell, md->cell + 9, md->plan_cell);
    }
    if (!std::isfinite(e)) { loup::set_error("non-finite energy (%g) in the tiled call", e); return -1; }
    if (!md->receivers) md->receivers = h->last_exec.receivers;  // the plan's cap, kept for the next call
    md->energy = e;
    md->forces_current = true;
    md->virial_current = stress;
    if (stress) {
        std::copy(vir, vir + 6, md->virial_h);
        if (!md->virial.p) CUDA_CHECK(loup::device_malloc(&md->virial.p, 6 * sizeof(double)));
        CUDA_CHECK(cudaMemcpyAsync(md->virial.p, vir, sizeof(vir), cudaMemcpyHostToDevice, h->stream));
        CUDA_CHECK(cudaStreamSynchronize(h->stream));  // `vir` goes out of scope
    }
    return 0;
}

static int tiled_run_impl(LoupHandle* h, const LoupIntegrator* it, int n_steps, LoupMDStats* out_stats,
                          LoupThermoRow* rows, int max_rows, int* out_rows, double* out_max_step_a) {
    if (!h) return -1;
    if (out_rows) *out_rows = 0;
    if (out_max_step_a) *out_max_step_a = 0.0;
    TiledMD* md = h->tiled_md;
    if (!md) { loup::set_error("no tiled MD state: call loup_tiled_set_state first"); return -1; }
    if (!it || it->size < sizeof(unsigned) + sizeof(int)) { loup::set_error("integrator is NULL or too small"); return -1; }
    if (n_steps <= 0) { loup::set_error("n_steps must be positive, got %d", n_steps); return -1; }
    const int kind = it->kind;
    // LT6 (a): the barostats, with loup_run's checks of their settings
    const bool npt_kind = kind == LOUP_BERENDSEN_NPT || kind == LOUP_BAOAB_NPT || kind == LOUP_MTK_NPT;
    RunSpec rs;
    if (npt_kind) {
        if (it->size != sizeof(LoupIntegrator)) {
            loup::set_error("LoupIntegrator.size is %u, and this library's layout has %zu bytes (set size to "
                            "sizeof(LoupIntegrator) of the header the library was built from)", it->size,
                            sizeof(LoupIntegrator));
            return -1;
        }
        if (integrator_settings(*it, n_steps, md->n_fixed, false, &rs) != 0) return -1;
    } else if (kind != LOUP_NVE && kind != LOUP_LANGEVIN && kind != LOUP_CSVR && kind != LOUP_NHC &&
               kind != LOUP_BERENDSEN_NVT) {
        loup::set_error("unknown integrator kind %d", kind);
        return -1;
    }
    const NptParams* npt = npt_kind ? &rs.npt : nullptr;
    const bool fix_com = it->fix_com != 0;
    if (fix_com && md->n_fixed) { loup::set_error("fix_com together with fixed atoms is refused"); return -1; }
    const double dt_fs = it->dt_fs;
    if (!(dt_fs > 0.0) || !std::isfinite(dt_fs)) { loup::set_error("dt_fs must be positive, got %g", dt_fs); return -1; }
    const double temp_k = it->temp_k, temp_rate = it->temp_rate_k_per_step;
    const double tau_fs = it->tau_t_fs;
    if ((kind == LOUP_CSVR || kind == LOUP_NHC || kind == LOUP_BERENDSEN_NVT) && !(tau_fs > 0.0)) {
        loup::set_error("tau_t_fs must be positive for this thermostat, got %g", tau_fs);
        return -1;
    }
    if (kind == LOUP_BERENDSEN_NVT && tau_fs < dt_fs) {
        loup::set_error("Berendsen's tau_t_fs (%g) must be at least dt_fs (%g), as in ASE", tau_fs, dt_fs);
        return -1;
    }
    if (kind == LOUP_LANGEVIN && !(it->friction_per_fs >= 0.0)) {
        loup::set_error("friction_per_fs must not be negative, got %g", it->friction_per_fs);
        return -1;
    }
    const int tchain = npt_kind ? rs.tchain : it->chain_length > 0 ? it->chain_length : 3;
    const int tloop = npt_kind ? rs.tloop : it->chain_loops > 0 ? it->chain_loops : 1;
    if (kind == LOUP_NHC && tchain > 16) { loup::set_error("chain_length must be at most 16"); return -1; }
    const double mass_temp_k = npt_kind ? rs.mass_temp_k : it->mass_temp_k > 0.0 ? it->mass_temp_k : temp_k;
    const int thermo_every = it->thermo_every > 0 ? it->thermo_every : 0;
    CUDA_CHECK(cudaSetDevice(h->device_id));
    const int N = md->n;
    const unsigned gridN = (unsigned)((N + 255) / 256), grid32 = (unsigned)((N + 31) / 32);
    const double dt_ase = dt_fs * loup::ASE_FS;
    const int dof = 3 * (N - md->n_fixed) - (fix_com ? 3 : 0);
    const unsigned long long seed = it->seed;
    double* pos = static_cast<double*>(md->pos.p);
    double* vel = static_cast<double*>(md->vel.p);
    double* frc = static_cast<double*>(md->forces.p);
    const double* masses = static_cast<const double*>(md->masses.p);
    const double* inv_m = static_cast<const double*>(md->inv_m.p);
    const double* sqrt_inv_m = static_cast<const double*>(md->sqrt_inv_m.p);
    double* rnd_vel = static_cast<double*>(md->rnd_vel.p);
    double* rnd_pos = static_cast<double*>(md->rnd_pos.p);
    double* com = static_cast<double*>(md->com.p);
    double* target = static_cast<double*>(md->target.p);
    unsigned long long* step = static_cast<unsigned long long*>(md->step.p);
    double* ist = static_cast<double*>(md->int_state.p);
    double* work = static_cast<double*>(md->int_work.p);
    unsigned int* disp = static_cast<unsigned int*>(md->disp.p);
    double* ke = static_cast<double*>(md->ke.p);

    const long long builds0 = h->tile_list_builds;
    long long tiles = 0;
    // the barostats start from the virial of the forces they start from
    if ((!md->forces_current || (npt_kind && !md->virial_current)) && tiled_md_forces(h, md, &tiles, npt_kind) != 0)
        return -1;

    // The coefficients and targets as loup_run sets them (run_md_loop).
    const bool fresh_state = md->state_kind != kind;  // the integrator's variables start from zero
    double c1 = 0, c2 = 0, a3 = 0, a4 = 0, a5 = 0, two_fr_kb = 0, csvr_exp = 0, nhc_q = 0;
    const double first = temp_k + temp_rate;
    if (kind == LOUP_LANGEVIN) {
        const double fr = it->friction_per_fs / loup::ASE_FS;
        c1 = dt_ase / 2.0 - dt_ase * dt_ase * fr / 8.0;
        c2 = dt_ase * fr / 2.0 - dt_ase * dt_ase * fr * fr / 8.0;
        two_fr_kb = 2.0 * fr * loup::ASE_KB;
        a3 = sqrt(dt_ase) / 2.0 - pow(dt_ase, 1.5) * fr / 8.0;
        a5 = pow(dt_ase, 1.5) / (2.0 * sqrt(3.0));
        a4 = (fr / 2.0) * a5;
        const double sigma = sqrt(two_fr_kb * (first > 0.0 ? first : 0.0));
        const double t[5] = {first, temp_rate, a3 * sigma, a4 * sigma, a5 * sigma};
        CUDA_CHECK(cudaMemcpyAsync(target, t, sizeof(t), cudaMemcpyHostToDevice, h->stream));
    } else if (kind != LOUP_NVE) {
        const double t[5] = {first, temp_rate, 0.0, 0.0, 0.0};
        CUDA_CHECK(cudaMemcpyAsync(target, t, sizeof(t), cudaMemcpyHostToDevice, h->stream));
        if (kind == LOUP_CSVR) csvr_exp = exp(-dt_fs / tau_fs);
        if (kind == LOUP_NHC) {
            const double tdamp = tau_fs * loup::ASE_FS;
            nhc_q = loup::ASE_KB * mass_temp_k * tdamp * tdamp;
        }
        if (md->state_kind != kind) {
            CUDA_CHECK(cudaMemsetAsync(ist, 0, kIntStateSlots * sizeof(double), h->stream));
            md->state_kind = kind;
        }
        CUDA_CHECK(cudaMemsetAsync(work, 0, kIntWorkSlots * sizeof(double), h->stream));
    }
    // LT6 (a): the barostats' constants as run_md_loop makes them, and the cell on the device (cell.hpp). The
    // whole system's kernels run on the tiled MD's arrays; the tiled call stands in for the force pass.
    double bao_gamma = 0.0, bao_ou = 0.0, bao_gamma_b = 0.0, bao_ou_b = 0.0, bao_mass = 0.0;
    double mtk_q = 0.0, mtk_r = 0.0, mtk_w = 0.0;
    const int bao_ndof = 3 * N;
    loup::CellDev* celldev = nullptr;
    double* virial_d = nullptr;
    int* flag = nullptr;
    if (npt_kind) {
        // SPDX-SnippetBegin
        // SPDX-License-Identifier: LGPL-2.1-or-later
        // Provenance: the barostats' constants, up to the end marker, follow ASE 3.27's ase/md classes (LGPL-2.1-or-
        // later, (c) the ASE developers, https://gitlab.com/ase/ase), as run_md_loop's; see NOTICE.md.
        if (kind == LOUP_BAOAB_NPT) {
            bao_gamma = rs.friction / loup::ASE_FS;
            bao_ou = sqrt(1.0 - exp(-2.0 * bao_gamma * dt_ase));
            const double p_tau = (npt->tau_p_fs > 0.0 ? npt->tau_p_fs : 20.0 / rs.friction) * loup::ASE_FS;
            const double c = 1.66 * loup::ASE_FS;
            bao_mass = pow((p_tau / 4.0) / c * pow((double)N, 1.0 / 6.0), 2.0);
            bao_gamma_b = 1.0 / p_tau;
            bao_ou_b = sqrt(1.0 - exp(-2.0 * bao_gamma_b * dt_ase)) * sqrt(bao_mass);
        }
        if (kind == LOUP_MTK_NPT) {
            const double tdamp = tau_fs * loup::ASE_FS, pdamp = npt->tau_p_fs * loup::ASE_FS;
            const double kt_mass = loup::ASE_KB * mass_temp_k;
            mtk_q = kt_mass * tdamp * tdamp;
            mtk_r = kt_mass * pdamp * pdamp;
            mtk_w = (npt->full ? (double)dof / 3.0 + 1.0 : (double)dof + 3.0) * mtk_r;
        }
        // SPDX-SnippetEnd
        if (!md->celldev.p) CUDA_CHECK(loup::device_malloc(&md->celldev.p, sizeof(loup::CellDev)));
        if (!md->flag.p) CUDA_CHECK(loup::device_malloc(&md->flag.p, sizeof(int)));
        loup::CellDev c{};
        loup::CellMat64 cm;
        double vol = 0.0, heights[3];
        loup::compute_cell_mat(md->cell, cm, vol, heights);
        for (int i = 0; i < 9; ++i) {
            c.h[i] = md->cell[i];
            c.ref_inv[i] = cm.inv[i];
            c.f[i] = c.move[i] = (i % 4 == 0) ? 1.0 : 0.0;
        }
        c.row_scale[0] = c.row_scale[1] = c.row_scale[2] = 1.0;
        c.r_max = (double)h->gen->r_max();
        c.r_list = c.r_max + md->skin;
        c.thr = 0.5 * md->skin;
        c.volume = vol;
        c.v0 = md->v0 > 0.0 ? md->v0 : vol;
        c.has_move = 0;
        CUDA_CHECK(cudaMemcpyAsync(md->celldev.p, &c, sizeof(c), cudaMemcpyHostToDevice, h->stream));
        celldev = static_cast<loup::CellDev*>(md->celldev.p);
        virial_d = static_cast<double*>(md->virial.p);
        flag = static_cast<int*>(md->flag.p);
        if (kind == LOUP_BAOAB_NPT && fresh_state) {  // LangevinBAOAB.__init__: the cell force it starts from
            loup::kinetic_tensor_kernel<<<gridN, 256, 0, h->stream>>>(N, masses, vel, work);
            loup::baoab_cell_second_kernel<<<1, 1, 0, h->stream>>>(npt->full, 0, 0, dt_ase, bao_ndof, -npt->pressure,
                                                                   virial_d, celldev, work, ist, step);
        }
        CUDA_CHECK(cudaStreamSynchronize(h->stream));  // `c` goes out of scope
    }
    const double inv_total_mass = fix_com ? 1.0 / md->total_mass : 0.0;
    if (fix_com && kind != LOUP_LANGEVIN) {  // the total momentum removed once (the forces sum to zero)
        CUDA_CHECK(cudaMemsetAsync(com, 0, 6 * sizeof(double), h->stream));
        loup::momentum_sum_kernel<<<gridN, 256, 0, h->stream>>>(N, masses, vel, com);
        loup::momentum_remove_kernel<<<gridN, 256, 0, h->stream>>>(N, inv_total_mass, com, vel);
    }
    CUDA_CHECK(cudaMemsetAsync(disp, 0, 2 * sizeof(unsigned int), h->stream));
    const double volume = std::fabs(md->cell[0] * (md->cell[4] * md->cell[8] - md->cell[5] * md->cell[7]) -
                                    md->cell[1] * (md->cell[3] * md->cell[8] - md->cell[5] * md->cell[6]) +
                                    md->cell[2] * (md->cell[3] * md->cell[7] - md->cell[4] * md->cell[6]));
    auto kinetic = [&](double* out) -> int {
        CUDA_CHECK(cudaMemsetAsync(ke, 0, sizeof(double), h->stream));
        loup::kinetic_energy_kernel<<<gridN, 256, 0, h->stream>>>(N, masses, vel, ke);
        CUDA_CHECK(cudaMemcpyAsync(out, ke, sizeof(double), cudaMemcpyDeviceToHost, h->stream));
        return 0;
    };
    int n_rows = 0;
    const auto t0 = std::chrono::steady_clock::now();
    for (int s = 0; s < n_steps; ++s) {
        // first half: as record_move of run_md_loop
        if (kind == LOUP_MTK_NPT) {
            loup::kinetic_tensor_kernel<<<gridN, 256, 0, h->stream>>>(N, masses, vel, work + 44);
            loup::mtk_first_kernel<<<1, 1, 0, h->stream>>>(npt->full, dt_ase, tchain, tloop, npt->pchain, npt->ploop,
                                                           dof, mtk_q, mtk_r, mtk_w, loup::ASE_KB, npt->pressure,
                                                           target, ist, work, virial_d, celldev);
            loup::mtk_first_atoms_kernel<<<gridN, 256, 0, h->stream>>>(N, dt_ase, work, frc, inv_m, pos, vel, disp);
        } else if (kind == LOUP_BAOAB_NPT) {
            loup::baoab_cell_first_kernel<<<1, 1, 0, h->stream>>>(npt->full, dt_ase, bao_gamma, bao_ou, bao_gamma_b,
                                                                  bao_ou_b, bao_mass, bao_ndof, loup::ASE_KB, seed,
                                                                  step, target, ist, work, celldev);
            loup::baoab_first_kernel<<<grid32, 32, 0, h->stream>>>(N, dt_ase, work, seed, step, frc, inv_m, sqrt_inv_m,
                                                                   pos, vel, disp);
        } else if (kind == LOUP_BERENDSEN_NPT) {
            loup::kinetic_energy_kernel<<<gridN, 256, 0, h->stream>>>(N, masses, vel, work);
            if (npt->full) loup::kinetic_diag_kernel<<<gridN, 256, 0, h->stream>>>(N, masses, vel, work + 2);
            loup::berendsen_scale_kernel<<<1, 1, 0, h->stream>>>(dof, dt_fs / tau_fs, loup::ASE_KB, target, work);
            loup::berendsen_npt_kernel<<<1, 1, 0, h->stream>>>(npt->full, npt->mask[0], npt->mask[1], npt->mask[2],
                                                               npt->pressure, dt_fs, npt->tau_p_fs,
                                                               npt->compressibility, work, virial_d, celldev);
            loup::cell_move_positions_kernel<<<gridN, 256, 0, h->stream>>>(N, celldev, pos);
            loup::csvr_first_half_kernel<<<gridN, 256, 0, h->stream>>>(N, dt_ase, work, frc, inv_m, pos, vel, disp);
        } else if (kind == LOUP_LANGEVIN && fix_com) {
            CUDA_CHECK(cudaMemsetAsync(com, 0, 6 * sizeof(double), h->stream));
            loup::langevin_noise_kernel<<<grid32, 32, 0, h->stream>>>(N, target, seed, step, masses, sqrt_inv_m,
                                                                      rnd_pos, rnd_vel, com);
            loup::langevin_first_half_fixcom_kernel<<<gridN, 256, 0, h->stream>>>(
                N, dt_ase, c1, c2, inv_total_mass, com, frc, inv_m, rnd_pos, rnd_vel, pos, vel, disp);
        } else if (kind == LOUP_LANGEVIN) {
            loup::langevin_first_half_kernel<<<grid32, 96, 0, h->stream>>>(  // S106: 32 atoms, 96 threads per block
                N, dt_ase, c1, c2, target, seed, step, frc, inv_m, sqrt_inv_m, pos, vel, rnd_vel, disp);
        } else if (kind == LOUP_NVE) {
            loup::nve_first_half_kernel<<<gridN, 256, 0, h->stream>>>(N, dt_ase, frc, inv_m, pos, vel, disp);
        } else {
            loup::kinetic_energy_kernel<<<gridN, 256, 0, h->stream>>>(N, masses, vel, work);
            if (kind == LOUP_BERENDSEN_NVT)
                loup::berendsen_scale_kernel<<<1, 1, 0, h->stream>>>(dof, dt_fs / tau_fs, loup::ASE_KB, target, work);
            else if (kind == LOUP_NHC)
                loup::nhc_half_kernel<<<1, 1, 0, h->stream>>>(dof, tchain, tloop, 0.5 * dt_ase, nhc_q, loup::ASE_KB,
                                                              0, target, work, ist);
            else
                loup::csvr_alpha_kernel<<<1, 1, 0, h->stream>>>(dof, csvr_exp, loup::ASE_KB, seed, step, target, work,
                                                                ist);
            loup::csvr_first_half_kernel<<<gridN, 256, 0, h->stream>>>(N, dt_ase, work, frc, inv_m, pos, vel, disp);
        }
        if (npt_kind) {
            // the cell follows this step's deformation (cell_derive_kernel), and the tiled call runs in it
            CUDA_CHECK(cudaMemsetAsync(flag, 0, sizeof(int), h->stream));
            loup::cell_derive_kernel<<<1, 1, 0, h->stream>>>(celldev, flag);
            loup::CellDev c;
            int bad = 0;
            CUDA_CHECK(cudaMemcpyAsync(&c, celldev, sizeof(c), cudaMemcpyDeviceToHost, h->stream));
            CUDA_CHECK(cudaMemcpyAsync(&bad, flag, sizeof(int), cudaMemcpyDeviceToHost, h->stream));
            CUDA_CHECK(cudaStreamSynchronize(h->stream));
            bool finite = std::isfinite(c.volume);
            for (int i = 0; i < 9; ++i) finite = finite && std::isfinite(c.h[i]);
            if ((bad & 8) || !finite) {
                loup::set_error("the cell diverged: its volume is %g A^3, outside [V0 / 20, 20 V0] with V0 = %g A^3 "
                                "(step %lld of the tiled run)", c.volume, c.v0, md->md_steps + 1);
                md->forces_current = md->virial_current = false;
                return -1;
            }
            std::copy(c.h, c.h + 9, md->cell);
        }
        if (tiled_md_forces(h, md, &tiles, npt_kind) != 0) return -1;
        virial_d = static_cast<double*>(md->virial.p);
        // second half: as record_rest
        if (kind == LOUP_MTK_NPT) {  // the atom kick, the cell kick with the new stress, both chains
            loup::mtk_kick_kernel<<<gridN, 256, 0, h->stream>>>(N, dt_ase, work, frc, inv_m, vel);
            loup::kinetic_tensor_kernel<<<gridN, 256, 0, h->stream>>>(N, masses, vel, work + 44);
            loup::mtk_second_kernel<<<1, 1, 0, h->stream>>>(npt->full, dt_ase, tchain, tloop, npt->pchain, npt->ploop,
                                                            dof, mtk_q, mtk_r, mtk_w, loup::ASE_KB, npt->pressure,
                                                            target, ist, work, virial_d, celldev);
            loup::scale_velocities_kernel<<<gridN, 256, 0, h->stream>>>(N, work, vel);
        } else if (kind == LOUP_LANGEVIN) {
            loup::langevin_second_half_kernel<<<gridN, 256, 0, h->stream>>>(N, c1, c2, frc, inv_m, rnd_vel, vel, step,
                                                                            target, a3, a4, a5, two_fr_kb);
        } else {
            if (kind == LOUP_BAOAB_NPT) {  // the cell force from the velocities before the last kick, then barostat B
                loup::kinetic_tensor_kernel<<<gridN, 256, 0, h->stream>>>(N, masses, vel, work);
                loup::baoab_cell_second_kernel<<<1, 1, 0, h->stream>>>(npt->full, 1, 1, dt_ase, bao_ndof,
                                                                       -npt->pressure, virial_d, celldev, work, ist,
                                                                       step);
            }
            loup::nve_second_half_kernel<<<gridN, 256, 0, h->stream>>>(N, dt_ase, frc, inv_m, vel);
        }
        if (kind == LOUP_NHC) {
            loup::kinetic_energy_kernel<<<gridN, 256, 0, h->stream>>>(N, masses, vel, work);
            loup::nhc_half_kernel<<<1, 1, 0, h->stream>>>(dof, tchain, tloop, 0.5 * dt_ase, nhc_q, loup::ASE_KB, 1,
                                                          target, work, ist);
            loup::scale_velocities_kernel<<<gridN, 256, 0, h->stream>>>(N, work, vel);
        }
        ++md->md_steps;
        if (thermo_every && md->md_steps % thermo_every == 0 && rows && n_rows < max_rows) {
            double e_kin = 0.0, transferred = 0.0;
            if (kinetic(&e_kin) != 0) return -1;
            if (kind != LOUP_NVE && kind != LOUP_LANGEVIN)
                CUDA_CHECK(cudaMemcpyAsync(&transferred, ist, sizeof(double), cudaMemcpyDeviceToHost, h->stream));
            CUDA_CHECK(cudaStreamSynchronize(h->stream));
            LoupThermoRow& r = rows[n_rows++];
            r.step = md->md_steps;
            r.e_pot = md->energy;
            r.e_kin = e_kin;
            r.temp_k = dof > 0 ? 2.0 * e_kin / (dof * loup::ASE_KB) : 0.0;
            r.pressure_gpa = 0.0;
            r.volume_a3 = volume;
            if (npt_kind) {  // as thermo_row_kernel: minus a third of the stress's trace plus 2 E_kin / (3 V), in GPa
                const double* c = md->cell;
                r.volume_a3 = std::fabs(c[0] * (c[4] * c[8] - c[5] * c[7]) - c[1] * (c[3] * c[8] - c[5] * c[6]) +
                                        c[2] * (c[3] * c[7] - c[4] * c[6]));
                const double* v = md->virial_h;
                r.pressure_gpa = (2.0 * e_kin - (v[0] + v[3] + v[5])) / (3.0 * r.volume_a3) * 160.21766208;
            }
            r.conserved = md->energy + e_kin - transferred;
        }
    }
    double e_kin = 0.0;
    unsigned int disp_bits = 0u;
    if (kinetic(&e_kin) != 0) return -1;
    CUDA_CHECK(cudaMemcpyAsync(&disp_bits, disp, sizeof(disp_bits), cudaMemcpyDeviceToHost, h->stream));
    CUDA_CHECK(cudaStreamSynchronize(h->stream));
    if (out_max_step_a) {
        float d2 = 0.0f;
        memcpy(&d2, &disp_bits, sizeof(d2));
        *out_max_step_a = std::sqrt((double)d2);
    }
    CUDA_CHECK(cudaGetLastError());
    const double wall = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
    if (out_rows) *out_rows = n_rows;
    if (out_stats) {
        *out_stats = LoupMDStats{};
        out_stats->step_ms = wall / n_steps;
        out_stats->rebuilds = (int)(h->tile_list_builds - builds0);
        out_stats->final_potential_energy_ev = md->energy;
        out_stats->final_kinetic_energy_ev = e_kin;
        out_stats->final_temperature_k = dof > 0 ? 2.0 * e_kin / (dof * loup::ASE_KB) : 0.0;
        out_stats->pipelined_steps = 0;
    }
    return 0;
}

static int tiled_get_state_impl(LoupHandle* h, double* positions, double* velocities, double* forces,
                                double* energy, unsigned long long* noise_step, double* int_state) {
    if (!h) return -1;
    TiledMD* md = h->tiled_md;
    if (!md) { loup::set_error("no tiled MD state: call loup_tiled_set_state first"); return -1; }
    CUDA_CHECK(cudaSetDevice(h->device_id));
    if (forces && !md->forces_current) {
        long long tiles = 0;
        if (tiled_md_forces(h, md, &tiles) != 0) return -1;
    }
    const size_t v3 = (size_t)md->n * 3 * sizeof(double);
    if (positions) CUDA_CHECK(cudaMemcpyAsync(positions, md->pos.p, v3, cudaMemcpyDeviceToHost, h->stream));
    if (velocities) CUDA_CHECK(cudaMemcpyAsync(velocities, md->vel.p, v3, cudaMemcpyDeviceToHost, h->stream));
    if (forces) CUDA_CHECK(cudaMemcpyAsync(forces, md->forces.p, v3, cudaMemcpyDeviceToHost, h->stream));
    if (noise_step)
        CUDA_CHECK(cudaMemcpyAsync(noise_step, md->step.p, sizeof(*noise_step), cudaMemcpyDeviceToHost, h->stream));
    if (int_state)
        CUDA_CHECK(cudaMemcpyAsync(int_state, md->int_state.p, kIntStateSlots * sizeof(double),
                                   cudaMemcpyDeviceToHost, h->stream));
    CUDA_CHECK(cudaStreamSynchronize(h->stream));
    if (energy) *energy = md->forces_current ? md->energy : std::nan("");
    return 0;
}

// loup_plan_memory: the device memory a system of n_atoms would take, scaled from the buffers the handle's current
// system has. Every per-system buffer is proportional to the atom count or to the edge capacity, so the scaling is
// exact up to alignment; what it leaves out is small and does not scale (captured graphs, cuBLAS internals).
static int plan_memory_impl(LoupHandle* h, int n_atoms, double edges_per_atom, LoupMemoryPlan* out) {
    if (!out) { loup::set_error("out is NULL"); return -1; }
    if (!has_system(h)) return -1;
    if (!h->nl_valid || h->E_cap <= 0) {
        loup::set_error("no neighbour list to scale from (call loup_set_state or loup_evaluate on a system with "
                        "neighbours first; a small cell of the same material is enough)");
        return -1;
    }
    if (n_atoms <= 0) { loup::set_error("n_atoms must be positive, got %d", n_atoms); return -1; }
    const double epa = edges_per_atom > 0.0 ? edges_per_atom : (double)h->E_skin / h->N;
    if (!std::isfinite(epa)) { loup::set_error("edges_per_atom must be finite, got %g", edges_per_atom); return -1; }
    CUDA_CHECK(cudaSetDevice(h->device_id));
    const double scale = (double)n_atoms / h->N;
    const double atom_now = (double)h->sys_atom_bytes + (h->gen ? (double)h->gen->system_bytes() : 0.0);
    const double edge_now = (double)h->sys_edge_bytes + (h->gen ? (double)h->gen->edge_bytes() : 0.0);
    const double edges = std::ceil((double)n_atoms * epa);
    const double cap = std::max(edges + std::floor(edges / 4.0) + 1024.0, 4096.0);  // ensure_edge_capacity's rule
    // kPlanAllowance stands for what is not counted (captured graphs, the allocator's rounding of sixty buffers):
    // on SrTiO3 with OMAT-0 medium the counted bytes were 58, -1 and 25 MB below the measured memory at 5,000, 20,480
    // and 40,000 atoms (RTX 5060 Ti, 15 November 2026).
    constexpr double kPlanAllowance = 64.0 * 1024.0 * 1024.0;
    const double whole = atom_now * scale + (double)h->sys_fixed_bytes + edge_now / h->E_cap * cap +
                         (double)h->cub_tmp_bytes * scale + (double)h->weight_copy_bytes + kPlanAllowance;
    size_t free_b = 0, total_b = 0;
    CUDA_CHECK(device_memory(&free_b, &total_b));
    if (const char* e = std::getenv("LOUP_DEBUG_PLAN"); e && e[0] == '1')
        std::fprintf(stderr, "plan memory: N %d (rows %d), edges %d (capacity %d); engine rows %.1f MB, model rows "
                     "%.1f MB, engine edges %.1f MB, model edges %.1f MB, fixed %.1f MB, scan %.1f MB, weight copies "
                     "%.1f MB; device free %.1f of %.1f MB\n", h->N, h->atom_cap, h->E_skin, h->E_cap,
                     h->sys_atom_bytes / 1048576.0, (h->gen ? h->gen->system_bytes() : 0) / 1048576.0,
                     h->sys_edge_bytes / 1048576.0, (h->gen ? h->gen->edge_bytes() : 0) / 1048576.0,
                     h->sys_fixed_bytes / 1048576.0, h->cub_tmp_bytes / 1048576.0, h->weight_copy_bytes / 1048576.0,
                     free_b / 1048576.0, total_b / 1048576.0);
    LoupMemoryPlan plan{};
    plan.whole_bytes = (size_t)whole;
    plan.free_bytes = free_b;
    // The planned system would replace the current one, so its buffers count as free; 10% stay as headroom. Edge
    // indices are 32-bit: beyond that the whole-system call cannot run whatever the memory.
    const double budget = (double)free_b + atom_now + (double)h->sys_fixed_bytes + edge_now + (double)h->cub_tmp_bytes;
    plan.mode = (whole <= 0.9 * budget && edges <= (double)h->edge_limit) ? LOUP_EXEC_WHOLE : LOUP_EXEC_TILED;
    *out = plan;
    return 0;
}

static int profile_force_impl(LoupHandle* h, int warmup, int n_calls, double* out_total_us) {
    if (!has_system(h)) return -1;
    if (!h->nl_valid) {
        loup::set_error("no positions or neighbour list (call loup_set_state or loup_evaluate first)");
        return -1;
    }
    if (warmup < 0 || n_calls <= 0) {
        loup::set_error("warmup must not be negative and n_calls must be positive, got %d and %d", warmup, n_calls);
        return -1;
    }
    CUDA_CHECK(cudaSetDevice(h->device_id));
    if (settle_armed(h) != 0) return -1;
    if (ensure_force_graph(h, 0) != 0) return -1;
    for (int i = 0; i < warmup; ++i) {
        CUDA_CHECK(cudaGraphLaunch(h->force_graph_exec, h->stream));
    }
    CUDA_CHECK(cudaStreamSynchronize(h->stream));
    EventPairGuard evg;
    cudaEvent_t ev0 = evg.e0, ev1 = evg.e1;
    CUDA_CHECK(cudaEventRecord(ev0, h->stream));
    for (int i = 0; i < n_calls; ++i) {
        CUDA_CHECK(cudaGraphLaunch(h->force_graph_exec, h->stream));
    }
    CUDA_CHECK(cudaEventRecord(ev1, h->stream));
    CUDA_CHECK(cudaEventSynchronize(ev1));
    float ms = 0.0f;
    CUDA_CHECK(cudaEventElapsedTime(&ms, ev0, ev1));
    if (out_total_us) *out_total_us = (double)ms * 1000.0 / n_calls;
    return 0;
}

int loup_set_dispersion(LoupHandle* h, const LoupD3Settings* settings, const LoupD3Tables* tables) {
    return guarded(h, "loup_set_dispersion", [&]() -> int {
        CUDA_CHECK(cudaSetDevice(h->device_id));
        CUDA_CHECK(cudaStreamSynchronize(h->stream));
        h->invalidate_graphs();
        h->disp.reset();
        h->disp_ready = false;
        if (!settings) return 0;
        if (!tables) { loup::set_error("tables is NULL"); return -1; }
        if (settings->damping < 0 || settings->damping > 3) {
            loup::set_error("damping must be 0 (BJ), 1 (zero), 2 (modified BJ) or 3 (modified zero), got %d",
                            settings->damping);
            return -1;
        }
        loup::dispersion::Settings s;
        s.damping = static_cast<loup::dispersion::Damping>(settings->damping);
        s.s6 = settings->s6; s.s8 = settings->s8; s.a1 = settings->a1; s.a2 = settings->a2;
        s.rs6 = settings->rs6; s.rs8 = settings->rs8; s.alpha = settings->alpha; s.beta = settings->beta;
        s.pair_cutoff_bohr = settings->pair_cutoff_bohr;
        s.cn_cutoff_bohr = settings->cn_cutoff_bohr;
        s.smoothing_bohr = settings->smoothing_bohr;
        s.three_body = settings->three_body != 0;
        s.three_body_cutoff_bohr = settings->three_body_cutoff_bohr;
        s.long_range = static_cast<loup::dispersion::LongRange>(settings->long_range);
        s.mesh_spacing_A = settings->mesh_spacing_A;
        loup::dispersion::Tables t{tables->nref, tables->cnref, tables->rcov, tables->r2r4, tables->c6ref,
                                   tables->r0ab};
        const char* why = nullptr;
        h->disp.reset(loup::dispersion::make_term(s, t, &why));
        if (!h->disp) { loup::set_error("%s", why ? why : "the dispersion term was refused"); return -1; }
        // a system with positions: prepare now (its cell is known); else at its first positions
        if (h->N > 0 && h->nl_valid) return prepare_dispersion(h);
        return 0;
    });
}

int loup_set_system(LoupHandle* h, int n_atoms, const int* atomic_numbers, const double* masses_amu, double skin) {
    return guarded(h, "loup_set_system", [&] {
        const DeviceOrder order(true);  // the legacy stream's copies and the release of a tiled state (DeviceOrder)
        if (h) release_tiled_md(h);
        return set_system_impl(h, n_atoms, atomic_numbers, masses_amu, skin);
    });
}

int loup_set_state(LoupHandle* h, const double* positions, const double* velocities, const double* cell) {
    return guarded(h, "loup_set_state", [&] { return set_state_impl(h, positions, velocities, cell); });
}

int loup_set_fixed_atoms(LoupHandle* h, const int* fixed) {
    return guarded(h, "loup_set_fixed_atoms", [&] { return set_fixed_impl(h, fixed); });
}

int loup_evaluate(
    LoupHandle* h, const double* positions, const double* cell, int compute_stress,
    double* out_energy_ev, double* out_forces, double* out_stress
) {
    return guarded(h, "loup_evaluate", [&] {
        return evaluate_impl(h, positions, cell, compute_stress, out_energy_ev, out_forces, out_stress);
    }, true);
}

int loup_evaluate2(
    LoupHandle* h, const double* positions, const double* cell, int flags, double* out_energy_ev,
    double* out_forces, double* out_stress, double* out_atom_energies
) {
    // A plain call (no flag but the stress) is loup_evaluate; the energy-only and per-atom passes are not.
    return guarded(h, "loup_evaluate2", [&] {
        return evaluate2_impl(h, positions, cell, flags, out_energy_ev, out_forces, out_stress, out_atom_energies);
    }, (flags & ~LOUP_EVAL_STRESS) == 0);
}

int loup_run_nve(LoupHandle* h, int n_steps, double dt_fs, LoupMDStats* out_stats) {
    return guarded(h, "loup_run_nve", [&] { return run_nve_impl(h, n_steps, dt_fs, out_stats); });
}

int loup_run_langevin(
    LoupHandle* h, int n_steps, double dt_fs, double temp_k,
    double friction_per_fs, unsigned long long seed, LoupMDStats* out_stats
) {
    return guarded(h, "loup_run_langevin", [&] {
        return run_langevin_impl(h, n_steps, dt_fs, temp_k, friction_per_fs, seed, out_stats);
    });
}

int loup_run(LoupHandle* h, const LoupIntegrator* it, int n_steps, LoupMDStats* out_stats) {
    return guarded(h, "loup_run", [&] { return run_impl(h, it, n_steps, out_stats); });
}

int loup_get_state(LoupHandle* h, double* out_positions, double* out_velocities, double* out_forces, double* out_energy_ev) {
    return guarded(h, "loup_get_state", [&] {
        return get_state_impl(h, out_positions, out_velocities, out_forces, out_energy_ev);
    });
}

int loup_set_evaluate_ahead(LoupHandle* h, int on) {
    if (!h) return -1;
    return guarded(h, "loup_set_evaluate_ahead", [&] {
        CUDA_CHECK(cudaSetDevice(h->device_id));
        if (!on && settle_armed(h) != 0) return -1;
        h->arm_enabled = on != 0;
        return 0;
    });
}

double loup_cutoff(const LoupHandle* h) { return h && h->gen ? (double)h->cutoff() : 0.0; }

int loup_species(const LoupHandle* h, int* out_atomic_numbers, int max) {
    if (!h || !h->gen) return 0;
    const int S = h->n_species();
    for (int s = 0; out_atomic_numbers && s < S && s < max; ++s) out_atomic_numbers[s] = h->species_z(s);
    return S;
}

int loup_compute_device(LoupHandle* h, const LoupDeviceIO* io, const double* cell, void* stream,
                        double* out_energy_ev, double* out_virial) {
    return guarded(h, "loup_compute_device", [&] {
        return compute_device_impl(h, io, cell, stream, out_energy_ev, out_virial);
    });
}

int loup_profile_force(LoupHandle* h, int warmup, int n_calls, double* out_total_us) {
    return guarded(h, "loup_profile_force", [&] { return profile_force_impl(h, warmup, n_calls, out_total_us); });
}

int loup_export_state(LoupHandle* h, void* buffer, size_t capacity, size_t* written) {
    return guarded(h, "loup_export_state", [&] { return export_state_impl(h, buffer, capacity, written); });
}

int loup_import_state(LoupHandle* h, const void* buffer, size_t size) {
    return guarded(h, "loup_import_state", [&] { return import_state_impl(h, buffer, size); });
}

int loup_debug_set_domain(LoupHandle* h, int n_local, int n_ghost, const int* atomic_numbers, double skin) {
    return guarded(h, "loup_debug_set_domain", [&] { return set_domain_impl(h, n_local, n_ghost, atomic_numbers, skin); });
}

int loup_debug_evaluate_domain(LoupHandle* h, const double* positions, const double* cell, const int* ghost_of,
                               double* out_energy_ev, double* out_forces, double* out_stress) {
    return guarded(h, "loup_debug_evaluate_domain", [&] {
        return evaluate_domain_impl(h, positions, cell, ghost_of, out_energy_ev, out_forces, out_stress);
    });
}

int loup_debug_domain_edges(LoupHandle* h, const double* positions, const double* cell, long long capacity,
                            int* out_receivers, int* out_senders, double* out_shifts, long long* out_count,
                            unsigned char* out_ghost_used) {
    return guarded(h, "loup_debug_domain_edges", [&] {
        return domain_edges_impl(h, positions, cell, capacity, out_receivers, out_senders, out_shifts, out_count,
                                 out_ghost_used);
    });
}

int loup_evaluate_tiled(LoupHandle* h, int n_atoms, const int* atomic_numbers, const double* positions,
                        const double* cell, int receivers, double skin, double* out_energy_ev, double* out_forces,
                        double* out_stress, long long* out_tiles) {
    return guarded(h, "loup_evaluate_tiled", [&] {
        return evaluate_tiled_impl(h, n_atoms, atomic_numbers, positions, cell, receivers, skin, out_energy_ev,
                                   out_forces, out_stress, out_tiles);
    });
}

int loup_debug_evaluate_tiled(LoupHandle* h, int n_atoms, const int* atomic_numbers, const double* positions,
                              const double* cell, int receivers, double skin, double* out_energy_ev, double* out_forces,
                              double* out_stress, long long* out_tiles) {
    return guarded(h, "loup_debug_evaluate_tiled", [&] {
        return evaluate_tiled_impl(h, n_atoms, atomic_numbers, positions, cell, receivers, skin, out_energy_ev,
                                   out_forces, out_stress, out_tiles);
    });
}

int loup_tiled_set_state(LoupHandle* h, int n_atoms, const int* atomic_numbers, const double* masses_amu,
                         const double* positions, const double* velocities, const double* cell,
                         const unsigned char* fixed, int receivers, double skin, unsigned long long noise_step,
                         const double* int_state, int int_state_kind) {
    return guarded(h, "loup_tiled_set_state", [&] {
        return tiled_set_state_impl(h, n_atoms, atomic_numbers, masses_amu, positions, velocities, cell, fixed,
                                    receivers, skin, noise_step, int_state, int_state_kind);
    });
}

int loup_tiled_run(LoupHandle* h, const LoupIntegrator* integrator, int n_steps, LoupMDStats* out_stats,
                   LoupThermoRow* rows, int max_rows, int* out_rows, double* out_max_step_a) {
    return guarded(h, "loup_tiled_run", [&] {
        return tiled_run_impl(h, integrator, n_steps, out_stats, rows, max_rows, out_rows, out_max_step_a);
    });
}

int loup_tiled_get_state(LoupHandle* h, double* positions, double* velocities, double* forces, double* out_energy_ev,
                         unsigned long long* noise_step, double* int_state, int* int_state_kind) {
    return guarded(h, "loup_tiled_get_state", [&] {
        if (tiled_get_state_impl(h, positions, velocities, forces, out_energy_ev, noise_step, int_state) != 0)
            return -1;
        if (int_state_kind) *int_state_kind = h->tiled_md->state_kind;
        return 0;
    });
}

int loup_tiled_get_cell(LoupHandle* h, double* out_cell) {
    return guarded(h, "loup_tiled_get_cell", [&] {
        if (!h->tiled_md) { loup::set_error("no tiled MD state: call loup_tiled_set_state first"); return -1; }
        if (!out_cell) { loup::set_error("out_cell is NULL"); return -1; }
        std::copy(h->tiled_md->cell, h->tiled_md->cell + 9, out_cell);
        return 0;
    });
}

int loup_set_execution(LoupHandle* h, int mode, int receivers, double memory_fraction) {
    return guarded(h, "loup_set_execution", [&] {
        if (!h) return -1;
        if (mode < LOUP_EXEC_AUTO || mode > LOUP_EXEC_WAVEFRONT) { loup::set_error("unknown mode %d", mode); return -1; }
        if (receivers < 0) { loup::set_error("receivers must not be negative, got %d", receivers); return -1; }
        if (!(memory_fraction > 0.0 && memory_fraction <= 1.0)) {
            loup::set_error("memory_fraction must be above 0 and at most 1, got %g", memory_fraction);
            return -1;
        }
        h->exec_mode = mode;
        h->exec_receivers = receivers;
        h->exec_fraction = memory_fraction;
        return 0;
    });
}

int loup_plan_execution(LoupHandle* h, int n_atoms, const int* atomic_numbers, const double* positions,
                        const double* cell, double skin, LoupMemoryPlan* out) {
    return guarded(h, "loup_plan_execution", [&] {
        return plan_execution_impl(h, n_atoms, atomic_numbers, positions, cell, skin, out);
    });
}

int loup_get_execution(LoupHandle* h, LoupExecution* out) {
    return guarded(h, "loup_get_execution", [&] {
        if (!h) return -1;
        if (!out) { loup::set_error("out is NULL"); return -1; }
        *out = h->last_exec;
        return 0;
    });
}

int loup_read_thermo(LoupHandle* h, LoupThermoRow* rows, int max_rows, int* n_rows) {
    return guarded(h, "loup_read_thermo", [&] { return read_thermo_impl(h, rows, max_rows, n_rows); });
}

int loup_minimize(LoupHandle* h, const LoupMinimizer* minimizer, int max_steps, LoupMinStats* out_stats) {
    return guarded(h, "loup_minimize", [&] { return minimize_impl(h, minimizer, max_steps, out_stats); });
}

int loup_get_step_displacement(LoupHandle* h, double* out_max_a) {
    return guarded(h, "loup_get_step_displacement", [&] { return step_displacement_impl(h, out_max_a); });
}

int loup_set_cell(LoupHandle* h, const double* cell, int scale_atoms) {
    return guarded(h, "loup_set_cell", [&] { return set_cell_impl(h, cell, scale_atoms); });
}

int loup_get_cell(LoupHandle* h, double* out_cell) {
    return guarded(h, "loup_get_cell", [&] { return get_cell_impl(h, out_cell); });
}

int loup_set_reference_volume(LoupHandle* h, double volume_a3) {
    return guarded(h, "loup_set_reference_volume", [&] {
        if (h && h->tiled_md) {  // LT6 (a): the tiled MD's V0 (loup_tiled_set_state takes its cell's volume)
            if (!std::isfinite(volume_a3) || !(volume_a3 > 0.0)) {
                loup::set_error("the reference volume must be finite and positive, got %g A^3", volume_a3);
                return -1;
            }
            h->tiled_md->v0 = volume_a3;
            return 0;
        }
        return set_reference_volume_impl(h, volume_a3);
    });
}

int loup_debug_csvr_noise(LoupHandle* h, unsigned long long seed, unsigned long long first_step, int n_steps,
                          int ndof, double* out_normal, double* out_chi2) {
    return guarded(h, "loup_debug_csvr_noise", [&] {
        return csvr_noise_impl(h, seed, first_step, n_steps, ndof, out_normal, out_chi2);
    });
}

int loup_plan_memory(LoupHandle* h, int n_atoms, double edges_per_atom, LoupMemoryPlan* out) {
    return guarded(h, "loup_plan_memory", [&] { return plan_memory_impl(h, n_atoms, edges_per_atom, out); });
}

const char* loup_last_error(const LoupHandle* h) {
    return h ? h->last_error.c_str() : tl_null_error.c_str();
}

int loup_abi_version(void) { return LOUP_ABI_VERSION; }

const char* loup_version(void) {
    static const std::string version = [] {
        char buf[96];
        snprintf(buf, sizeof(buf), LOUP_VERSION "+%016llx", (unsigned long long)library_build_hash());
        return std::string(buf);
    }();
    return version.c_str();
}

static int get_info_impl(const LoupHandle* h, LoupInfo* out) {
    if (!out) { loup::set_error("out is NULL"); return -1; }
    LoupInfo info{};
    info.abi = LOUP_ABI_VERSION;
    cudaDeviceProp prop{};
    CUDA_CHECK(cudaGetDeviceProperties(&prop, h->device_id));
    info.compute_capability = prop.major * 10 + prop.minor;
    memcpy(info.gpu_name, prop.name, std::min(strnlen(prop.name, sizeof(prop.name)), sizeof(info.gpu_name) - 1));
    info.n_layers = h->gen ? h->gen->n_layers() : 2;
    info.has_long_range = (h->gen && h->gen->has_lr()) ? 1 : 0;
    info.specialised = 0;  // the kernels specialised to MACE-OMAT-0 medium were retired (JIT_DESIGN.md stage 5)
    info.n_species = h->n_species();
    info.r_max = (double)h->cutoff();
    const std::string sig = h->gen ? h->gen->kernel_signature() : std::string();
    const size_t room = sizeof(info.kernel_signature) - 1;
    if (sig.size() <= room) {
        memcpy(info.kernel_signature, sig.data(), sig.size());
    } else {
        memcpy(info.kernel_signature, sig.data(), room - 3);
        memcpy(info.kernel_signature + room - 3, "...", 3);
    }
    *out = info;
    return 0;
}

int loup_get_info(const LoupHandle* h, LoupInfo* out) {
    // The error channel is the only state of the handle this call touches.
    return guarded(const_cast<LoupHandle*>(h), "loup_get_info", [&] { return get_info_impl(h, out); });
}

}  // extern "C"
