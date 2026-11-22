#pragma once
// The generic MACE path: any bundle with arch=generic (python/export_generic.py) — MACE-OMAT-0 small/medium,
// MACE-OFF, MACE-MH-1 and MACE-POLAR-1's local part. Layer by layer: linear_up GEMMs, the fused conv tensor
// product with radial splines (generated_generic.cuh), message linears, density / avg-neighbour / gated
// normalisations, the factored symmetric contraction, skip connections and readouts; then the same in reverse for
// forces and stress. engine.cu owns the neighbour list, the MD loop and the GEMM autotuning; it calls in here.
#include <cstdint>
#include <functional>
#include <string>
#include <vector>

#include <cuda_runtime.h>

#include "kernels_common.cuh"

namespace loup {

class Bundle;

// row-major C[M, N] = alpha * A[M, K] @ op(B) + beta * C, op(B) = B [K, N] or B^T for B [N, K]
using GemmFn = std::function<void(bool transB, int M, int N, int K, float alpha, const float* A, int lda,
                                  const float* B, int ldb, float beta, float* C, int ldc)>;

// One degree l of the nonlinear (kind 4) block's gate in the epilogue of an own-SGEMM projection (sgemm.cu):
// - forward (gemm_gate_fwd: lin_l = A @ B for a degree l >= 1 without residual): writes gate_fwd_kernel's gout_l =
//   cs_g sigmoid(pre0[l C + c]) * (lin_l * s) to `out` instead of storing lin_l; reads D, lin0, res0 / res0_sp;
// - backward (gemm_gate_bwd: dgout_l = A @ W_2[l]^T): what gate_bwd_kernel computes for degree l's columns from
//   dgout_l, without writing dgout_l. lin_l / res_l / dp_l / dl_l are degree l's arrays (lin0 / res0 / dp0 / dl0 for
//   l = 0); res_l, dp0 and dp_l may be null. vform: lin_l is the forward's saved gout_l (a degree whose lin_l the
//   forward never stored; no residual), the reverse taken through it.
struct GateArgs {
    int natoms = 0, C = 0;
    const float* D = nullptr;
    float alpha = 1.0f, beta = 0.0f, cs = 1.0f, cg = 1.0f;
    const float* lin0 = nullptr;
    const float* lin_l = nullptr;
    const float* res0 = nullptr;
    const int* res0_sp = nullptr;
    const float* res_l = nullptr;
    float* dp0 = nullptr;
    float* dp_l = nullptr;
    float* dl0 = nullptr;
    float* dl_l = nullptr;
    float* dD = nullptr;  // += the degree's terms of dE/dD, atomically
    float* out = nullptr;
    int vform = 0;
};
// Runs the projection fused with degree l's gate (M = natoms (2l + 1), N = C) when the GEMM's plan and shape allow;
// false: nothing launched (the caller runs the plain GEMM and the gate kernel for l). Backward: dgout_l = A[M, K] @
// B[N, K]^T; forward: lin_l = A[M, K] @ B[K, N]. A null: only reports whether it would run.
using GemmGateFn = std::function<bool(int l, int M, int N, int K, const float* A, const float* B, const GateArgs& g)>;

struct GenericPassInputs {
    cudaStream_t stream;
    int N;                     // receivers: the atoms of a periodic system, the local atoms of a domain
    int n_ghost = 0;           // a domain's ghost atoms, rows N .. N + n_ghost - 1: they only send. Their rows of a
                               // layer's input and of its gradient exist; nothing else is computed for them
    const int* E_dev;          // device: number of active edges (act_row_ptr[N])
    int E_cap;                 // capacity of the edge arrays
    const int* act_row_ptr;    // [N + 1], receiver rows
    const int* act_senders;    // [E]
    const int* act_receivers;  // [E]
    const float4* act_vec_len; // [E] (pos[rcv] - pos[snd] + shift, |v|)
    const int* act_slab;       // [E] prelocated (pair * I + iv) for preloc_grid()/preloc_pair_sym(), or nullptr
    const float2* act_t_sx;    // [E] prelocated (t, +/- sx_inv)
    const int* species;        // [N], atoms grouped by species
    const std::vector<int>* species_start;
    const std::vector<int>* species_count;
    double* energy;            // [1] accumulated (zeroed here)
    double* forces;            // [N, 3] (zeroed here)
    double* virial;            // [6] (zeroed here)
    const double* pos64;       // [N, 3] positions (device order; the long-range k-space terms read them)
    int compute_stress;
    int energy_only = 0;       // forward of every layer and the ZBL energy only: no forces, no stress
    double* atom_energy = nullptr;  // energy_only (S6-T08): also each row's readout and ZBL energy [N], added
                                    // to (the caller zeroes it); the fused product + readout kernel is not used
    // Which part of the pass record() runs (PLAN.md 4.4). SweepAll is the whole pass. The others are one sweep of a
    // domain with ghost atoms; the caller carries the layer outputs and their gradients from sweep to sweep:
    //   SweepForward t (t < L - 1): needs layer t - 1's output rows (receivers and ghosts) in layer_out(t - 1, l);
    //                               leaves layer t's output for the receivers in layer_out(t, l); adds the
    //                               readout's energy.
    //   SweepLast:                  layer L - 1 forward and backward; needs layer L - 2's output as above; leaves
    //                               the gradient of it (receivers and ghosts) in layer_out_grad(L - 2, l), and
    //                               this sweep's forces.
    //   SweepBackward t:            replays layer t forward and runs its backward; needs layer t - 1's output and,
    //                               in adjoint_in[l], the receivers' rows of the gradient of layer t's output that
    //                               the later sweeps left (summed over every domain that holds the atom); leaves
    //                               the gradient of layer t - 1's output and this sweep's forces. ZBL comes with
    //                               t = 0.
    // A sweep writes the forces of its own edges only (receiver and sender rows), zeroing nothing of `forces`,
    // `virial` and `energy`: the caller zeroes them once.
    enum Sweep { SweepAll = 0, SweepForward = 1, SweepLast = 2, SweepBackward = 3 };
    int sweep = SweepAll;
    int sweep_layer = 0;
    const float* adjoint_in[4] = {nullptr, nullptr, nullptr, nullptr};
    // O31 (tiled): a buffer of GenericModel::sweep_keep_floats(N) floats the caller keeps per domain for layer 0's
    // forward results that its backward reads. SweepForward 0 writes them there; SweepBackward 0 reads them there
    // and does not replay layer 0's forward. Only where sweep_keep_layer0(); nullptr: the replay.
    float* keep0 = nullptr;
    GemmFn gemm;
    std::function<void()> gemm_fork;
    std::function<void(int)> gemm_lane;
    std::function<void()> gemm_join;
    GemmGateFn gemm_gate_bwd;  // empty: never fused (LOUP_GATE_FUSE=0)
    GemmGateFn gemm_gate_fwd;  // empty: never fused (LOUP_GATE_FUSE_FWD=0)
};

struct GenericLayer;

class PolarLR;

class GenericModel {
public:
    GenericModel() = default;
    ~GenericModel();
    GenericModel(const GenericModel&) = delete;
    GenericModel& operator=(const GenericModel&) = delete;

    void load(const Bundle& b);
    int S() const { return S_; }
    float r_max() const { return r_max_; }
    const std::vector<int>& atomic_numbers() const { return Z_; }
    const std::vector<double>& e0() const { return e0_; }
    int n_layers() const { return n_layers_; }
    // Bytes of the per-system buffers (alloc_system) and of the edge buffers (ensure_edges), for loup_plan_memory,
    // the long-range part's (polar.cu) included.
    size_t system_bytes() const;
    // The same with every layer's buffers its own: what a whole system of as many rows allocates where this one
    // shares them (share_layer_buffers); equal to system_bytes() otherwise.
    size_t system_bytes_unshared() const { return sys_bytes_unshared_; }
    // The largest single buffer of the system: the first pass times every GEMM shape into a scratch copy of its
    // output, so a system's first call needs that much more for a moment (the engine's memory plans).
    size_t largest_buffer_bytes() const { return sys_max_alloc_; }
    size_t edge_bytes() const { return edge_bytes_; }
    // For a sweep driver: layer t's output rows of degree l ([rows, 2l + 1, out_width(t)]; nullptr when the model
    // does not form them) and the buffer the next layer's sweep leaves their gradient in.
    float* layer_out(int t, int l) const;
    float* layer_out_grad(int t, int l) const;
    int out_width(int t) const;
    int out_lmax(int t) const;
    // Sweeps need every layer's output to exist: not with the long range, nor with the skip-chain fold.
    bool sweeps_available() const { return lr_ == nullptr && !chain_fold_; }
    // Whether the model can sweep once the fold is off (use_chain_fold(false)): every model without long range.
    bool sweeps_possible() const { return lr_ == nullptr; }
    // The skip-chain fold (S57, S73) of the systems allocated from now on: on only where setup_chain_fold built it.
    // The fold's composed weights sit beside the plain ones, so a handle switches per system: whole systems fold,
    // tile domains (which sweep) do not. Call with no system allocated (before alloc_system).
    void use_chain_fold(bool on);
    bool chain_fold_built() const { return chain_fold_built_; }
    // The layers' own buffers of the systems allocated from now on in one shared arena (tile-shared-layers): a sweep
    // runs one layer and needs nothing of another layer but its output and that output's gradient, which stay
    // buffers of their own, so the arena is as large as the largest layer instead of all of them. Such a system runs
    // sweeps and energy-only passes, not the whole pass (its backward of a layer would read what a later layer's
    // forward overwrote). Only without the fold and the long range, from two layers; LOUP_TILE_SHARE_LAYERS=0 keeps
    // every buffer its own. Call with no system allocated (before alloc_system).
    void share_layer_buffers(bool on);
    bool layers_shared() const { return layers_shared_; }
    // O31: whether layer 0's backward sweep reads nothing of its forward but msgf[0..3] and D (the density layer 0
    // with the hidden table, skip folded, linear readout: MACE-MP-0b3 / MPA-0 / OMAT-0 / MatPES), so a domain can
    // keep them (GenericPassInputs::keep0) instead of the replay; and their floats for N receivers.
    bool sweep_keep_layer0() const;
    size_t sweep_keep_floats(int N) const;
    // The compiled product kernels this bundle uses, one signature per layer, joined by ';' (loup_get_info).
    std::string kernel_signature() const;

    // Per-system buffers (N atoms); edge buffers grow with ensure_edges (call outside graph capture).
    void alloc_system(int N);
    void free_system();
    void ensure_edges(int E_cap);
    // The long-range (POLAR) k-vectors follow the cell: call on every cell change, outside stream capture; true if
    // captured graphs must be re-recorded.
    bool set_cell(const double* cell);
    bool has_lr() const { return lr_ != nullptr; }
    const SplineGrid* preloc_grid() const;
    int preloc_pair_sym() const;
    // Records the whole force pass on in.stream (capturable; no host syncs, no allocation).
    void record(const GenericPassInputs& in);
    // S64: times each layer's conv forward variants on the last recorded pass's inputs (outside capture; sm_120) and
    // keeps the fastest. -1: no pass recorded for this system yet (call again later); 0: unchanged; 1: a variant
    // changed (captured graphs must be re-recorded).
    int tune_conv_variants(cudaStream_t st);
private:
    struct ConvTuneArgs {
        bool valid = false;
        int N = 0;
        const int* row_ptr = nullptr;
        const int* senders = nullptr;
        const float4* vec_len = nullptr;
        const int* slab = nullptr;
        const float2* t_sx = nullptr;
        const int* species = nullptr;
    };
    ConvTuneArgs conv_args_;
    int conv_var_override_ = -1;  // S64: LOUP_CONV_FWD_VARIANT (test override), -1 none
    int conv_tune_env_ = -1;      // LOUP_CONV_TUNE at load: -1 unset (sm_120 only), 0 off, 1 any GPU (tests)
    void free_model();
    // S57 skip-chain fold (sm_120, cc 8.0; LOUP_CHAIN_FOLD=0 disables): see setup_chain_fold in generic.cu.
    void setup_chain_fold(const Bundle& b);
    bool chain_fold_ = false;        // the fold of the allocated system (use_chain_fold)
    bool chain_fold_built_ = false;  // setup_chain_fold composed the fold's weights
    bool share_layers_ = false;      // asked for the systems to come (share_layer_buffers)
    bool share_layers_env_ = true;   // LOUP_TILE_SHARE_LAYERS != 0, read at load
    bool layers_shared_ = false;     // the allocated system's layers share their arena
    size_t sys_bytes_unshared_ = 0;  // sys_bytes_ with every layer's buffers its own
    size_t sys_max_alloc_ = 0;       // the largest single buffer of alloc_system
    void update_h0_read();           // h0_read_ for the current chain_fold_ (S97)
    // S59 layer-0 species tables (sm_120, cc 8.0; LOUP_SPECIES_TABLES=0 disables): see setup_species_tables.
    void setup_species_tables(const Bundle& b);
    bool species_tables_ = false;
    // Long-range hidden fold (sm_120; LOUP_POLAR_HFOLD=0 disables, 1 / 2 / 3 picks the degrees): see setup_lr_fold.
    void setup_lr_fold(const Bundle& b);
    // JIT_DESIGN.md stage 1 (LOUP_JIT=1): layer 0's kernels compiled for this model at load; see setup_jit in generic.cu.
    void setup_jit();
    int S_ = 0, n_layers_ = 0, sh_perm_ = 0, has_zbl_ = 0;
    float r_max_ = 0.0f;
    std::vector<int> Z_;
    std::vector<double> e0_;
    float* d_embedding_ = nullptr;  // [S, C0]
    int C0_ = 0;
    std::vector<GenericLayer*> layers_;
    PolarLR* lr_ = nullptr;
    // ZBL per ordered pair
    float zbl_c_[4] = {0, 0, 0, 0};
    float zbl_p_ = 5.0f, zbl_rmax_ = 0.0f;
    float *d_zbl_rc_ = nullptr, *d_zbl_inv_a_ = nullptr, *d_zbl_pref_ = nullptr;
    // system buffers
    int N_ = 0, E_cap_ = 0;
    size_t sys_bytes_ = 0, edge_bytes_ = 0;
    // LOUP_SWEEP_REPLAY=1 (testing): record() runs the per-layer sweep schedule of a domain with ghost atoms on the
    // whole system; see record(). sys_alloc_bytes_ parallels sys_allocs_.
    bool sweep_replay_ = false;
    double* d_energy_sink_ = nullptr;  // a replayed forward adds its readout's energy here: it is already counted
    std::vector<size_t> sys_alloc_bytes_;
    std::vector<void*> sys_allocs_;
    // The buffers whose zeros alloc_system writes once and every pass reads (a pruned conv layer's skipped
    // projections, a compact layer's pad columns): no sweep writes them, so the sweep schedule's test leaves them.
    std::vector<const void*> sys_zero_once_;
    float* d_edge_dvec_ = nullptr;  // [E_cap, 3]
    void* d_zero_slab_ = nullptr;
    size_t zero_slab_bytes_ = 0;
    float* d_h0_ = nullptr;         // [N, C0] layer-0 node features
    bool h0_read_ = true;           // S97: some consumer reads d_h0_ (else record skips its gather)
    float* d_scratch_ = nullptr;    // gradient scratch
    size_t scratch_floats_ = 0;
};

}  // namespace loup
