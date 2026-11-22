// LoupMD's tensor-core GEMM cubins (CUTLASS v4.8.1 sm_80 mainloop): C = A @ B (alpha 1) or C = A @ B + beta C,
// all float32 in memory, built offline into cubins/gemm_tc_<math>_sm<arch>.cubin by cubins/src/build_gemm_tc.sh and
// loaded by src/engine.cu (struct TcCubin) as GEMM autotune candidates, so neither nvcc nor CUTLASS is needed at run
// time. Derived from FastMACE's fastmace/kernels/cutlass/tf32x3_sm80.cu (same owner): the same DefaultGemm
// instantiation and device-side parameter construction.
//
// Math (-DLOUP_TC_MATH): 0 = CUTLASS's 3xTF32 (OpMultiplyAddFastF32: big * big + big * small + small * big on TF32
// tensor cores, FP32 accumulation); 1 = the TF32 + FP16 hybrid (hybrid_f16.h: big * big on TF32, the two cross
// products in one FP16 MMA; every |element| of A and B must stay below 32,752, see the ledger's gemm-hybrid-cubin).
// Tiles (-DLOUP_TC_TILESET): 3 = 64x64, 32x64, 64x32 (warp 32x32x16, 4 stages; FastMACE's three, the tiles of the
// cubins LoupMD shipped before); 6 = those plus 128x64 and 64x128 (warp 32x32, 8 warps) and 128x128 (warp 64x32, 8 warps),
// 3 stages (64x64 warps, CUTLASS example 27, spill with the 3xTF32 fragments: 368 B of stack on sm_80).
// Beta (-DLOUP_TC_BETA=1): the cubin also has entries for C = A @ B + beta C (CUTLASS's epilogue reads C).
//
// Self-description for the loader: loup_gemm_tc_info = {format 2, math, beta_ok, tiles, then per tile: tile M,
// tile N, threads, dynamic shared bytes (B row-major), dynamic shared bytes (B column-major)}.
// Entries loup_gemm_tc_rr_<t> (B row-major [K, N]) and loup_gemm_tc_rc_<t> (B column-major: the transpose of a
// row-major [N, K]) compute C = A @ B with beta fixed at 0 at compile time, so their epilogue has no source path
// (format 1 builds passed beta at run time to every entry: the same results, a slower epilogue on short K); with
// beta_ok, loup_gemm_tc_rrb_<t> / loup_gemm_tc_rcb_<t> take beta at run time. All entries (M, N, K, A, lda, B, ldb,
// C, ldc, beta); grid ceil(M / tile M) x ceil(N / tile N).
// Alignment 4 (128-bit accesses): lda, ldb, ldc multiples of 4, every pointer 16-byte aligned; the caller checks.
// No split-K: each output's K sum runs in one order, the same in every tile.

#include <cutlass/cutlass.h>
#if LOUP_TC_MATH == 1
#include "hybrid_f16.h"
#define LOUP_TC_OP cutlass::arch::OpMultiplyAddHybridF16
#elif LOUP_TC_MATH == 0 && defined(LOUP_TC_SPLIT_RN) && LOUP_TC_SPLIT_RN
#include "fastf32_rn.h"
#define LOUP_TC_OP cutlass::arch::OpMultiplyAddFastF32RN
#elif LOUP_TC_MATH == 0
#define LOUP_TC_OP cutlass::arch::OpMultiplyAddFastF32
#else
#error "LOUP_TC_MATH must be 0 (3xTF32) or 1 (TF32 + FP16 hybrid)"
#endif
#include <cutlass/gemm/kernel/default_gemm.h>
#include <cutlass/gemm/threadblock/threadblock_swizzle.h>
#include <cutlass/epilogue/thread/linear_combination.h>

#ifndef LOUP_TC_TILESET
#error "LOUP_TC_TILESET must be 3 or 6"
#endif
#ifndef LOUP_TC_BETA
#define LOUP_TC_BETA 0
#endif

namespace {

template <typename LayoutB, int TileM, int TileN, int WarpM, int WarpN, int Stages>
using GemmKernel = typename cutlass::gemm::kernel::DefaultGemm<
    float, cutlass::layout::RowMajor, 4,
    float, LayoutB, 4,
    float, cutlass::layout::RowMajor,
    float, cutlass::arch::OpClassTensorOp, cutlass::arch::Sm80,
    cutlass::gemm::GemmShape<TileM, TileN, 16>, cutlass::gemm::GemmShape<WarpM, WarpN, 16>,
    cutlass::gemm::GemmShape<16, 8, 8>,
    cutlass::epilogue::thread::LinearCombination<float, 4, float, float>,
    cutlass::gemm::threadblock::GemmIdentityThreadblockSwizzle<1>, Stages, false,
    LOUP_TC_OP>::GemmKernel;

template <typename Kernel, bool kBeta>
__device__ __forceinline__ void run(int m, int n, int k, float const *a, int lda, float const *b, int ldb, float *c,
                                    int ldc, float beta) {
  extern __shared__ __align__(16) char storage[];
  cutlass::gemm::GemmCoord problem(m, n, k);
  cutlass::gemm::GemmCoord grid(gridDim.x, gridDim.y, 1);
  typename Kernel::Params params(
      problem, grid,
      {const_cast<float *>(a), typename Kernel::Mma::IteratorA::Layout(lda)},
      {const_cast<float *>(b), typename Kernel::Mma::IteratorB::Layout(ldb)},
      {c, typename Kernel::Epilogue::OutputTileIterator::Layout(ldc)},
      {c, typename Kernel::Epilogue::OutputTileIterator::Layout(ldc)},
      typename Kernel::OutputOp::Params(1.0f, kBeta ? beta : 0.0f));
  Kernel op;
  op(params, *reinterpret_cast<typename Kernel::SharedStorage *>(storage));
}

using RR0 = GemmKernel<cutlass::layout::RowMajor, 64, 64, 32, 32, 4>;
using RC0 = GemmKernel<cutlass::layout::ColumnMajor, 64, 64, 32, 32, 4>;
using RR1 = GemmKernel<cutlass::layout::RowMajor, 32, 64, 32, 32, 4>;
using RC1 = GemmKernel<cutlass::layout::ColumnMajor, 32, 64, 32, 32, 4>;
using RR2 = GemmKernel<cutlass::layout::RowMajor, 64, 32, 32, 32, 4>;
using RC2 = GemmKernel<cutlass::layout::ColumnMajor, 64, 32, 32, 32, 4>;
#if LOUP_TC_TILESET == 6
using RR3 = GemmKernel<cutlass::layout::RowMajor, 128, 64, 32, 32, 3>;
using RC3 = GemmKernel<cutlass::layout::ColumnMajor, 128, 64, 32, 32, 3>;
using RR4 = GemmKernel<cutlass::layout::RowMajor, 64, 128, 32, 32, 3>;
using RC4 = GemmKernel<cutlass::layout::ColumnMajor, 64, 128, 32, 32, 3>;
using RR5 = GemmKernel<cutlass::layout::RowMajor, 128, 128, 64, 32, 3>;
using RC5 = GemmKernel<cutlass::layout::ColumnMajor, 128, 128, 64, 32, 3>;
#endif

}  // namespace

#define LOUP_TC_TILE_INFO(RR, RC, TM, TN) \
  TM, TN, RR::kThreadCount, int(sizeof(typename RR::SharedStorage)), int(sizeof(typename RC::SharedStorage))

extern "C" {

__constant__ int loup_gemm_tc_info[4 + 5 * LOUP_TC_TILESET] = {
    2, LOUP_TC_MATH, LOUP_TC_BETA, LOUP_TC_TILESET,
    LOUP_TC_TILE_INFO(RR0, RC0, 64, 64), LOUP_TC_TILE_INFO(RR1, RC1, 32, 64), LOUP_TC_TILE_INFO(RR2, RC2, 64, 32),
#if LOUP_TC_TILESET == 6
    LOUP_TC_TILE_INFO(RR3, RC3, 128, 64), LOUP_TC_TILE_INFO(RR4, RC4, 64, 128), LOUP_TC_TILE_INFO(RR5, RC5, 128, 128),
#endif
};

#define LOUP_TC_ENTRY(name, Kernel, kBeta)                                                                        \
  __global__ void __launch_bounds__(Kernel::kThreadCount)                                                         \
  name(int m, int n, int k, float const *a, int lda, float const *b, int ldb, float *c, int ldc, float beta) {    \
    run<Kernel, kBeta>(m, n, k, a, lda, b, ldb, c, ldc, beta);                                                    \
  }
#if LOUP_TC_BETA
#define LOUP_TC_ENTRIES(t, RR, RC)                                                                                \
  LOUP_TC_ENTRY(loup_gemm_tc_rr_##t, RR, false) LOUP_TC_ENTRY(loup_gemm_tc_rc_##t, RC, false)                     \
  LOUP_TC_ENTRY(loup_gemm_tc_rrb_##t, RR, true) LOUP_TC_ENTRY(loup_gemm_tc_rcb_##t, RC, true)
#else
#define LOUP_TC_ENTRIES(t, RR, RC)                                                                                \
  LOUP_TC_ENTRY(loup_gemm_tc_rr_##t, RR, false) LOUP_TC_ENTRY(loup_gemm_tc_rc_##t, RC, false)
#endif

LOUP_TC_ENTRIES(0, RR0, RC0)
LOUP_TC_ENTRIES(1, RR1, RC1)
LOUP_TC_ENTRIES(2, RR2, RC2)
#if LOUP_TC_TILESET == 6
LOUP_TC_ENTRIES(3, RR3, RC3)
LOUP_TC_ENTRIES(4, RR4, RC4)
LOUP_TC_ENTRIES(5, RR5, RC5)
#endif

}  // extern "C"
