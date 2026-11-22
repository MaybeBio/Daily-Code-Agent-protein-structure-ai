#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
tool=${1:-}
shift || true
case "$tool" in
  af3) kit=af3_torch ;;
  boltz2) kit=boltz2 ;;
  boltzgen) kit=boltzgen ;;
  opendde) kit=opendde ;;
  protenix2) kit=protenix_v2 ;;
  rfd3) kit=rfdiffusion3 ;;
  *) printf 'usage: bash scripts/install.sh {af3|boltz2|boltzgen|opendde|protenix2|rfd3} [--weights DIR]\n' >&2; exit 2 ;;
esac
exec bash "$ROOT/kits/$kit/run.sh" install "$@"
