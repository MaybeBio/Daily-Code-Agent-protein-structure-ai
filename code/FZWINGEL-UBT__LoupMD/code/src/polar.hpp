#pragma once
// MACE-POLAR-1's long-range part (python/export_polar.py): per-layer spin-charge sources, the layer feature mixer, the
// Fukui charge constraint, the self-consistent field update (k-space GTO electrostatic features of the charges, the
// one-body charge update), the local electron energy and the k-space Coulomb energy, forward and reverse. Fully
// periodic cells, neutral singlet systems in zero external field (the engine's inputs). As in PolarMACE, the k-space
// terms see the strained cell (MACE PR 1718, as FastMACE): theta = k . r is strain invariant, so they add the
// cell dependence of the GTO bases, of 1/k^2 and of the volume to the virial.
#include <vector>

#include <cuda_runtime.h>

#include "generic.hpp"

namespace loup {

class Bundle;

class PolarLR {
public:
    PolarLR();
    ~PolarLR();
    PolarLR(const PolarLR&) = delete;
    PolarLR& operator=(const PolarLR&) = delete;

    void load(const Bundle& b, int S, int n_layers);
    // k-vectors of `cell` (row-major lattice vectors); true if the cell changed (captured graphs are then stale).
    // Call outside stream capture.
    bool set_cell(const double* cell);
    void alloc_system(int N);
    void free_system();
    size_t system_bytes() const;  // device bytes of the system's buffers
    // h[t][l] / dh[t][l]: layer t's node features [N, 2l+1, C] and their gradient accumulators
    void record(cudaStream_t st, int N, const GemmFn& gemm,
                const std::function<void()>& fork, const std::function<void(int)>& lane,
                const std::function<void()>& join, const int* species, const double* pos64,
                const std::vector<std::vector<float*>>& h, const std::vector<std::vector<float*>>& dh, double* energy,
                double* forces, int compute_stress, double* virial);
    // Hidden fold (GenericModel::setup_lr_fold): layer t's degree-l mixer weight and source block replaced by weights
    // the caller composed with the hidden chain (float32 device arrays [C, C] and [(2l + 1) C, 8]; the mixer array
    // stays the caller's). Source blocks certified exactly zero are skipped (with LOUP_POLAR_ZBLK). Call after load.
    void set_hidden_fold(int t, int l, const float* mix, const float* src_block);
    // the highest degree of the last layer's features that the electron energy reads (-1 without it)
    int le_lmax() const;

private:
    struct Impl;
    Impl* p_;
};

}  // namespace loup
