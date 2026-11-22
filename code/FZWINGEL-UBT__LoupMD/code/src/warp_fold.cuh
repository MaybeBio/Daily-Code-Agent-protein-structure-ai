#pragma once
// The warp fold of V float partials per lane (V a power of two, 2 .. 32) into double sums, on few FP64 adds.
//
// The plain fold `d += __shfl_xor_sync(full, d, off)` for off = 16 .. 1, read at lane 0, issues 5 V FP64 adds per
// warp; all but V - 1 of each value's 160 lane-adds form sums nobody reads. The FP64 unit runs at 1/64 rate on the
// RTX 5060 Ti and was the structure-factor kernels' limit (ncu, 19 November 2026: FP64 pipe 63-71% busy, FMA pipe
// 10-18%).
//
// Here a stage that still has two or more slots keeps half of them per lane (the lanes with bit `off` set keep the
// upper half) and sends the other half to the partner lane, so the five stages issue V/2, V/4, .. adds (at least one).
// Value c is summed over the same pairs in the same tree as in the plain fold, and IEEE addition commutes, so its
// bits are the plain fold's. warp_fold_split returns value c = lane >> kWarpFoldShift<V>; every lane of that
// group holds it. Every lane of the warp must call it (full-mask shuffles).
namespace loup {

template <int SLOTS, int OFF>
__device__ __forceinline__ void warp_fold_rest(double* d, int lane) {
    if constexpr (OFF > 0) {
        if constexpr (SLOTS >= 2) {
            constexpr int h = SLOTS / 2;
            const bool up = (lane & OFF) != 0;
            #pragma unroll
            for (int j = 0; j < h; ++j) {
                const double mine = up ? d[j + h] : d[j];
                const double send = up ? d[j] : d[j + h];
                d[j] = mine + __shfl_xor_sync(0xffffffffu, send, OFF);
            }
            warp_fold_rest<h, OFF / 2>(d, lane);
        } else {
            d[0] += __shfl_xor_sync(0xffffffffu, d[0], OFF);
            warp_fold_rest<1, OFF / 2>(d, lane);
        }
    }
}

template <int V>
__device__ __forceinline__ double warp_fold_split(const float* v, int lane) {
    static_assert(V >= 2 && V <= 32 && (V & (V - 1)) == 0, "2 .. 32 partials, a power of two");
    constexpr int H = V / 2;
    double d[H];
    const bool up = (lane & 16) != 0;
    #pragma unroll
    for (int j = 0; j < H; ++j) {
        const float mine = up ? v[j + H] : v[j];
        const float send = up ? v[j] : v[j + H];
        d[j] = (double)mine + (double)__shfl_xor_sync(0xffffffffu, send, 16);
    }
    warp_fold_rest<H, 8>(d, lane);
    return d[0];
}

template <int V>
constexpr int kWarpFoldShift = V == 32 ? 0 : V == 16 ? 1 : V == 8 ? 2 : V == 4 ? 3 : 4;

}  // namespace loup
