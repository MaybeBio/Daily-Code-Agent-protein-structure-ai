#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
export PYTHONPATH="$ROOT/kits/common/opt_core${PYTHONPATH:+:$PYTHONPATH}"
export TRITON_CACHE_DIR="${TRITON_CACHE_DIR:-${MODEL_OPT_JIT_ROOT:-$ROOT/.jit}/esmfold2}"
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"
export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
if [[ ${1:-} == check ]]; then
  shift
  exec "${ESMFOLD2_PYTHON:-python}" "$ROOT/kits/esmfold2/run.py" --check "$@"
fi
if [[ $# -lt 2 && ${1:-} != --help && ${1:-} != -h ]]; then
  printf 'usage: bash scripts/esmfold2_50.sh {check|INPUT_DIR OUTPUT_DIR} [options]\n' >&2
  exit 2
fi
exec "${ESMFOLD2_PYTHON:-python}" "$ROOT/kits/esmfold2/run.py" "$@"
