#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_common.sh"
[[ ${1:-} == -h || ${1:-} == --help ]] && { printf 'usage: bash scripts/rfd3_50.sh [input.json] [output_dir] [extra RFdiffusion3 overrides]\n'; exit 0; }
input=${1:-$ROOT/examples/rfd3_binder.json}
output=${2:-$ROOT/outputs/rfd3}
shift 2 2>/dev/null || true
kit_run rfdiffusion3 design --config sm120 --mode fast inputs="$input" out_dir="$output" n_batches=1 seed=42 "$@"
