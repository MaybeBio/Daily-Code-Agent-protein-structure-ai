#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_common.sh"
[[ ${1:-} == -h || ${1:-} == --help ]] && { printf 'usage: bash scripts/protenix2_50.sh [input.json] [output_dir] [extra Protenix flags]\n'; exit 0; }
input=${1:-$ROOT/examples/protenix_warm.json}
output=${2:-$ROOT/outputs/protenix2}
shift 2 2>/dev/null || true
kit_run protenix_v2 pred --config sm120 --mode fast --input "$input" --out_dir "$output" --model_name protenix-v2 "$@"
