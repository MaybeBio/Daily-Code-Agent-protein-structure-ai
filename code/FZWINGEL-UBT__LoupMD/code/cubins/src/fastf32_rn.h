// 3xTF32 with the big part rounded to nearest (LOUP_TC_MATH=0 with -DLOUP_TC_SPLIT_RN=1). CUTLASS's
// MmaTensorOpFastF32 hard-codes round_toward_zero for the big part (MmaFastF32), so the small part x - big always
// has the sign of x and the dropped small * small term has the sign of the product. Its relative magnitude is
// bounded by 2^-20 for normal finite operands in TF32 range, not an input-independent error constant.
// Nearest splitting halves each residual bound and removes that fixed-sign relation; correlated residuals can still bias it.
// Same fragments and layout as CUTLASS. LOUP_TC_ACC_RN=0 keeps its MMA accumulation sequence;
// LOUP_TC_ACC_RN=1 isolates big/cross partials and combines them with FP32 additions.
// Neither option controls rounding within an MMA instruction: exact TF32 inputs can still produce biased sums.

#include <cutlass/gemm/warp/mma_tensor_op_fast_f32.h>
#include <cutlass/gemm/warp/default_mma_tensor_op.h>

namespace cutlass {
namespace arch {
struct OpMultiplyAddFastF32RN {};
}  // namespace arch

namespace gemm {
namespace warp {

template <typename Shape_, typename LayoutA_, typename LayoutB_, typename LayoutC_, typename Policy_, int PartitionsK_,
          bool AccumulatorsInRowMajor>
class MmaTensorOpFastF32RN
    : public MmaTensorOpFastF32<Shape_, float, LayoutA_, float, LayoutB_, float, LayoutC_, Policy_, PartitionsK_,
                                AccumulatorsInRowMajor> {
 public:
  using Base = MmaTensorOpFastF32<Shape_, float, LayoutA_, float, LayoutB_, float, LayoutC_, Policy_, PartitionsK_,
                                  AccumulatorsInRowMajor>;
  using typename Base::FragmentA;
  using typename Base::FragmentB;
  using typename Base::FragmentC;
  using typename Base::AccessTypeFragmentA;
  using typename Base::AccessTypeFragmentB;
  using typename Base::TransformedFragmentA;
  using typename Base::TransformedFragmentB;

  CUTLASS_DEVICE
  MmaTensorOpFastF32RN() {}

  /// x rounded to TF32 (11 significand bits), to nearest (ties away from zero).
  static CUTLASS_DEVICE uint32_t tf32_rn(float x) { return (__float_as_uint(x) + 0x1000u) & 0xffffe000u; }

  static CUTLASS_DEVICE void split(float x, uint32_t &big, uint32_t &small) {
    big = tf32_rn(x);
    small = tf32_rn(x - __uint_as_float(big));
  }

  /// As MmaTensorOpFastF32::transform: B -> [big | small]; A in two halves -> [big0 | big1 | small0 | small1].
  CUTLASS_DEVICE
  void transform(TransformedFragmentA &dst_A, TransformedFragmentB &dst_B, FragmentA const &A,
                 FragmentB const &B) const {
    uint32_t *b = reinterpret_cast<uint32_t *>(&dst_B);
    CUTLASS_PRAGMA_UNROLL
    for (int i = 0; i < FragmentB::kElements; ++i) split(B[i], b[i], b[FragmentB::kElements + i]);
    uint32_t *a = reinterpret_cast<uint32_t *>(&dst_A);
    int const h = FragmentA::kElements / 2;
    CUTLASS_PRAGMA_UNROLL
    for (int i = 0; i < h; ++i) {
      split(A[i], a[i], a[2 * h + i]);
      split(A[h + i], a[h + i], a[3 * h + i]);
    }
  }

#if defined(LOUP_TC_ACC_RN) && LOUP_TC_ACC_RN
  // Keep cross terms out of the running, much larger accumulator. Combine each k8 result with FP32 RN additions;
  // unlike the hybrid this retains TF32's exponent range for both operands.
  CUTLASS_DEVICE
  void operator()(FragmentC &D, TransformedFragmentA const &A, TransformedFragmentB const &B,
                  FragmentC const &C) const {
    auto const *a = reinterpret_cast<AccessTypeFragmentA const *>(&A);
    auto const *b = reinterpret_cast<AccessTypeFragmentB const *>(&B);
    FragmentC big, cross;
    big.clear();
    cross.clear();
    this->mma_operator(big, a[0], b[0], big);
    this->mma_operator(cross, a[1], b[0], cross);
    this->mma_operator(cross, a[0], b[1], cross);
    CUTLASS_PRAGMA_UNROLL
    for (int i = 0; i < FragmentC::kElements; ++i) D[i] = C[i] + (big[i] + cross[i]);
  }
#endif
};

template <typename WarpShape_, typename LayoutA, typename LayoutB, typename LayoutC, int PartitionsK,
          bool AccumulatorsInRowMajor>
struct DefaultMmaTensorOp<WarpShape_, GemmShape<16, 8, 8>, float, LayoutA, float, LayoutB, float, LayoutC,
                          arch::OpMultiplyAddFastF32RN, PartitionsK, AccumulatorsInRowMajor> {
  using Policy = cutlass::gemm::warp::MmaTensorOpPolicy<
      cutlass::arch::Mma<GemmShape<16, 8, 8>, 32, cutlass::tfloat32_t, cutlass::layout::RowMajor, cutlass::tfloat32_t,
                         cutlass::layout::ColumnMajor, float, cutlass::layout::RowMajor, arch::OpMultiplyAdd>,
      cutlass::MatrixShape<1, 1>>;
  using Type = MmaTensorOpFastF32RN<WarpShape_, LayoutA, LayoutB, LayoutC, Policy, PartitionsK,
                                    AccumulatorsInRowMajor>;
};

}  // namespace warp
}  // namespace gemm
}  // namespace cutlass
