#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_common.sh"
[[ ${1:-} == -h || ${1:-} == --help ]] && { printf 'usage: bash scripts/opendde_50.sh [input.json] [output_dir] [extra OpenDDE flags]\n'; exit 0; }
input=${1:-$ROOT/examples/opendde_example.json}
output=${2:-$ROOT/outputs/opendde}
shift 2 2>/dev/null || true
kit_run opendde pred --config sm120 --mode fast -i "$input" -o "$output" --use_msa 0 --use_template 0 "$@"
