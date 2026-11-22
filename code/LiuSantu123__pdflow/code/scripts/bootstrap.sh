#!/usr/bin/env bash
# Bootstrap pdflow on a fresh machine.
#
#   bash scripts/bootstrap.sh                 # native profile
#   bash scripts/bootstrap.sh -- --profile kit
#
# Creates the `pdflow` conda environment from environment.yml, installs the
# package editable, then runs the first-time configuration wizard.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ENV_NAME=${PD_FLOW_ENV:-pdflow}

# Allow `bootstrap.sh -- --profile kit` without forwarding the separator.
if [ "${1:-}" = "--" ]; then
  shift
fi

if ! command -v conda >/dev/null 2>&1; then
  echo "conda is required; install miniconda or micromamba first" >&2
  exit 2
fi

if conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
  conda env update -n "$ENV_NAME" -f "$ROOT/environment.yml" --prune
else
  conda env create -n "$ENV_NAME" -f "$ROOT/environment.yml"
fi

conda run -n "$ENV_NAME" python -m pip install -e "$ROOT"
conda run -n "$ENV_NAME" pdflow setup "$@"

cat <<EOF

pdflow installed in conda env: $ENV_NAME
Next:
  conda activate $ENV_NAME
  pdflow doctor
  pdflow new --campaign runs/demo
EOF
