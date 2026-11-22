#!/usr/bin/env bash
# Run one command of the native-unit study in the tap-probing image, from a directory `ws remote run` shipped. Its
# working directory there is tree/projects/representation/plm_interpretability, four levels below the run directory:
#   ws remote run <machine> plm_interpretability --detach -- bash scripts/in_container.sh python scripts/units_atlas.py <stage> --root /units ...
# The run directory mounts read-only at /workspace and the launcher's import roots become container paths, so the
# container imports exactly what was shipped. UNITS (default ~/units_run, on the machine's local disk) mounts at /units
# for every stage's outputs, and CACHE (default ~/units_cache) at /cache for Hugging Face. The credentials the launcher
# forwards reach the container by name, never on a command line. CPUS (default 32) and MEMORY (default 256g) cap the
# container inside the machine's ceilings; NAME and IMAGE default to tap-probing.
set -euo pipefail
here="$(cd ../../../.. && pwd)"
if [[ ! -d "$here/tree/projects/representation/plm_interpretability" ]]; then
    echo "in_container.sh runs from tree/projects/representation/plm_interpretability of a shipped run" >&2
    exit 1
fi
units="${UNITS:-$HOME/units_run}"
cache="${CACHE:-$HOME/units_cache}"
mkdir -p "$units" "$cache"
names=()
for name in HF_TOKEN WANDB_API_KEY WS_PILOT WANDB_MODE; do
    if [[ -n "${!name:-}" ]]; then
        names+=("$name")
    fi
done
passed=()
for name in "${names[@]}"; do
    passed+=(-e "$name")
done
preserve=$(IFS=,; echo "${names[*]}")
exec sudo ${preserve:+--preserve-env="$preserve"} docker run --rm --gpus all --ipc=host --name "${NAME:-tap-probing}" \
    --cpus "${CPUS:-32}" --memory "${MEMORY:-256g}" \
    -v "$here:/workspace:ro" -v "$units:/units" -v "$cache:/cache" "${passed[@]}" \
    -e PYTHONPATH="${PYTHONPATH//"$here"//workspace}" -e OMP_NUM_THREADS="${CPUS:-32}" \
    -e PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
    -w /workspace/tree/projects/representation/plm_interpretability "${IMAGE:-tap-probing}" "$@"
