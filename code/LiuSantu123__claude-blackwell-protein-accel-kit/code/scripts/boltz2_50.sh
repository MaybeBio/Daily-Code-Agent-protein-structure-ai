#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_common.sh"
[[ ${1:-} == -h || ${1:-} == --help ]] && { printf 'usage: bash scripts/boltz2_50.sh [input.yaml] [output_dir] [extra Boltz2 flags]\n'; exit 0; }
input=${1:-$ROOT/examples/boltz2_1BRS.yaml}
output=${2:-$ROOT/outputs/boltz2}
shift 2 2>/dev/null || true
kit_run boltz2 pred --config sm120 --mode fast --input "$input" --out_dir "$output" --seed 42 --diffusion_samples 1 "$@"
