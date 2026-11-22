#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
tool=${1:-all}
shift || true
check_one() {
  local name=$1 kit=$2
  printf '\n== %s ==\n' "$name"
  bash "$ROOT/kits/$kit/run.sh" check --config sm120 --mode fast "$@"
}
case "$tool" in
  af3) check_one af3 af3_torch "$@" ;;
  esmfold2) bash "$ROOT/scripts/esmfold2_50.sh" check "$@" ;;
  boltz2) check_one boltz2 boltz2 "$@" ;;
  boltzgen) check_one boltzgen boltzgen "$@" ;;
  opendde) check_one opendde opendde "$@" ;;
  protenix2) check_one protenix2 protenix_v2 "$@" ;;
  rfd3) check_one rfd3 rfdiffusion3 "$@" ;;
  all)
    for pair in 'af3 af3_torch' 'boltz2 boltz2' 'boltzgen boltzgen' 'opendde opendde' 'protenix2 protenix_v2' 'rfd3 rfdiffusion3'; do
      read -r name kit <<< "$pair"
      check_one "$name" "$kit" "$@"
    done
    ;;
  *) printf 'usage: bash scripts/check.sh [af3|boltz2|boltzgen|opendde|protenix2|rfd3|esmfold2|all]\n' >&2; exit 2 ;;
esac
