#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_common.sh"
[[ ${1:-} == -h || ${1:-} == --help ]] && { printf 'usage: bash scripts/boltzgen_50.sh [spec.yaml] [output_dir] [extra BoltzGen flags]\n'; exit 0; }
input=${1:-$ROOT/examples/boltzgen_pdl1.yaml}
output=${2:-$ROOT/outputs/boltzgen}
shift 2 2>/dev/null || true
kit_run boltzgen design --config sm120 --mode fast "$input" --output "$output" --seed 42 "$@"
