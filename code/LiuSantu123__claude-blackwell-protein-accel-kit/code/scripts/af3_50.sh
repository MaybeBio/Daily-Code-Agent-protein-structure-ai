#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_common.sh"
[[ ${1:-} == -h || ${1:-} == --help ]] && { printf 'usage: bash scripts/af3_50.sh [input.json] [output_dir] [extra AF3 flags]\n'; exit 0; }
input=${1:-$ROOT/examples/af3_1BRS.json}
output=${2:-$ROOT/outputs/af3}
shift 2 2>/dev/null || true
kit_run af3_torch pred --config sm120 --mode fast --output_dir "$output" --json_path "$input" "$@"
