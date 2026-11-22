// Bit-exactness of warp_fold_split against the plain xor fold it replaces (src/warp_fold.cuh).
//   nvcc -O3 -std=c++17 -arch=sm_120 -Isrc tests/fold_check.cu -o build/fold_check && build/fold_check
// One warp per block; every lane holds V float partials. Inputs: normal deviates over twelve decades with both signs
// (so sums cancel), exact zeros, and subnormal floats.
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <random>
#include <vector>

#include <cuda_runtime.h>

#include "warp_fold.cuh"

template <int V>
__global__ void fold_both(const float* __restrict__ in, double* __restrict__ plain, double* __restrict__ split) {
    const int lane = threadIdx.x;
    const float* p = in + ((size_t)blockIdx.x * 32 + lane) * V;
    float v[V];
    #pragma unroll
    for (int j = 0; j < V; ++j) v[j] = p[j];
    #pragma unroll
    for (int j = 0; j < V; ++j) {
        double d = (double)v[j];
        #pragma unroll
        for (int off = 16; off > 0; off >>= 1) d += __shfl_xor_sync(0xffffffffu, d, off);
        if (lane == 0) plain[(size_t)blockIdx.x * V + j] = d;
    }
    constexpr int SH = loup::kWarpFoldShift<V>;
    const double t = loup::warp_fold_split<V>(v, lane);
    if ((lane & ((1 << SH) - 1)) == 0) split[(size_t)blockIdx.x * V + (lane >> SH)] = t;
}

template <int V>
static long check(int blocks, unsigned seed) {
    std::mt19937_64 rng(seed);
    std::normal_distribution<float> normal(0.0f, 1.0f);
    std::uniform_real_distribution<float> decade(-6.0f, 6.0f);
    std::uniform_int_distribution<int> kind(0, 19);
    std::vector<float> in((size_t)blocks * 32 * V);
    for (float& x : in) {
        const int k = kind(rng);
        if (k == 0) x = 0.0f;
        else if (k == 1) x = normal(rng) * 1e-41f;  // subnormal
        else x = normal(rng) * std::pow(10.0f, decade(rng));
    }
    float* d_in;
    double *d_plain, *d_split;
    const size_t n_out = (size_t)blocks * V;
    cudaMalloc(&d_in, in.size() * sizeof(float));
    cudaMalloc(&d_plain, n_out * sizeof(double));
    cudaMalloc(&d_split, n_out * sizeof(double));
    cudaMemcpy(d_in, in.data(), in.size() * sizeof(float), cudaMemcpyHostToDevice);
    cudaMemset(d_plain, 0xff, n_out * sizeof(double));
    cudaMemset(d_split, 0xee, n_out * sizeof(double));
    fold_both<V><<<blocks, 32>>>(d_in, d_plain, d_split);
    if (cudaDeviceSynchronize() != cudaSuccess) {
        std::printf("V %2d: the kernel failed\n", V);
        return -1;
    }
    std::vector<double> plain(n_out), split(n_out);
    cudaMemcpy(plain.data(), d_plain, n_out * sizeof(double), cudaMemcpyDeviceToHost);
    cudaMemcpy(split.data(), d_split, n_out * sizeof(double), cudaMemcpyDeviceToHost);
    cudaFree(d_in);
    cudaFree(d_plain);
    cudaFree(d_split);
    long bad = 0;
    double sum = 0.0;
    for (size_t i = 0; i < n_out; ++i) {
        bad += std::memcmp(&plain[i], &split[i], sizeof(double)) != 0;
        sum += std::fabs(plain[i]);
    }
    std::printf("V %2d: %zu sums, %ld differ in bits (mean |sum| %.3e)\n", V, n_out, bad, sum / (double)n_out);
    return bad;
}

int main() {
    long bad = 0;
    bad += check<2>(20000, 1);
    bad += check<4>(20000, 2);
    bad += check<8>(20000, 3);
    bad += check<16>(20000, 4);
    bad += check<32>(20000, 5);
    std::printf(bad == 0 ? "PASS: the split fold gives the plain fold's bits\n" : "FAIL\n");
    return bad == 0 ? 0 : 1;
}
