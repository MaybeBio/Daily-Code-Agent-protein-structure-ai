#!/usr/bin/env bash
# Builds LoupMD's tensor-core GEMM cubins from gemm_tc.cu (offline; the repository ships the cubins).
# Needs nvcc (CUDA 13) and CUTLASS v4.8.1's headers (git clone --depth 1 --branch v4.8.1
# https://github.com/NVIDIA/cutlass.git, commit 2c85f497):  CUTLASS=~/src/cutlass-4.8.1 bash cubins/src/build_gemm_tc.sh
#   gemm_tc_hyb_sm80.cubin   TF32 + FP16 hybrid, 6 tiles, beta      (A100 family)
#   gemm_tc_3x_sm80.cubin    3xTF32, 6 tiles, beta                  (A100: long-range models, A/B)
#   gemm_tc_hyb_sm90.cubin   TF32 + FP16 hybrid, 3 tiles, no beta   (as the earlier tf32x3_hyb_sm90.cubin)
#   gemm_tc_hyb_sm120.cubin  TF32 + FP16 hybrid, 3 tiles, no beta   (as the earlier tf32x3_hyb_sm120.cubin)
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
out=$(cd "$here/.." && pwd)
cutlass=${CUTLASS:?set CUTLASS to a CUTLASS v4.8.1 checkout}
nvcc=${NVCC:-nvcc}
build() {  # name arch math tileset beta
  "$nvcc" -cubin -arch=sm_$2 -O3 -std=c++17 -DNDEBUG --expt-relaxed-constexpr -I"$cutlass/include" -I"$here" \
    -DLOUP_TC_MATH=$3 -DLOUP_TC_TILESET=$4 -DLOUP_TC_BETA=$5 -o "$out/$1" "$here/gemm_tc.cu"
}
build gemm_tc_hyb_sm80.cubin 80 1 6 1
build gemm_tc_3x_sm80.cubin 80 0 6 1
build gemm_tc_hyb_sm90.cubin 90 1 3 0
build gemm_tc_hyb_sm120.cubin 120 1 3 0
{
  echo "nvcc: $("$nvcc" --version | tail -n 2 | tr '\n' ' ')"
  echo "cutlass: $(git -C "$cutlass" rev-parse HEAD 2>/dev/null || echo unknown)"
  for f in gemm_tc_hyb_sm80 gemm_tc_3x_sm80 gemm_tc_hyb_sm90 gemm_tc_hyb_sm120; do
    echo "sha256 $f.cubin: $(sha256sum "$out/$f.cubin" | cut -d' ' -f1)"
  done
} > "$here/gemm_tc.build.txt"
cat "$here/gemm_tc.build.txt"
