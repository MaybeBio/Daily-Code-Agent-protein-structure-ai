#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
export PYTHONUNBUFFERED=1

kit_run() {
  local kit=$1
  shift
  exec bash "$ROOT/kits/$kit/run.sh" "$@"
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 2
}
