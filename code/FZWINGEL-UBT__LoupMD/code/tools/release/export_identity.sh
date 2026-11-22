#!/usr/bin/env bash
# The byte-identity check of the vendored FastMACE subset (PLAN.md S2-T03): every bundle below is exported twice,
# once with loupmd/export/_vendor and once with a FastMACE checkout, and the two files must be equal.
#
#   tools/release/export_identity.sh FASTMACE_CHECKOUT MODELS_DIR [OUT_DIR]
#
# PYTHON names the interpreter (default python3; it needs the export extra). CPU only. Exit 1 on any difference.
set -uo pipefail
fastmace=${1:?a FastMACE checkout}
models=${2:?the folder with the model files}
out=${3:-$(mktemp -d)}
py=${PYTHON:-python3}
cd "$(dirname "$0")/../.."
mkdir -p "$out/vendored" "$out/checkout"
export CUDA_VISIBLE_DEVICES= TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1
# name | model file | elements | further arguments
cases="omat0-medium-specialised|mace-omat-0-medium.model|8,22,38|
omat0-medium-generic|mace-omat-0-medium.model|8,22,38|--generic
omat0-small|mace-omat-0-small.model|8,22,38|--generic
off23-medium|MACE-OFF23_medium.model|1,8|--generic
mh1|mace-mh-1.model|8,22,38|--generic
polar1-s|MACE-POLAR-1-S.model|11,17|--generic"
status=0
while IFS='|' read -r name file elements more; do
    if [ ! -f "$models/$file" ]; then echo "$name: $file not found, skipped"; continue; fi
    for side in vendored checkout; do
        if [ "$side" = checkout ]; then export LOUPMD_EXPORT_FASTMACE=$fastmace; else unset LOUPMD_EXPORT_FASTMACE; fi
        if ! "$py" -m loupmd.export --model "$models/$file" --elements "$elements" --output "$out/$side/$name.loup" $more \
                > "$out/$side/$name.log" 2>&1; then
            echo "$name: the export with the $side code failed"; tail -4 "$out/$side/$name.log"; status=1
        fi
    done
    if cmp -s "$out/vendored/$name.loup" "$out/checkout/$name.loup"; then
        echo "$name: identical ($(stat -c %s "$out/vendored/$name.loup") bytes)"
    else
        echo "$name: DIFFERS"; status=1
    fi
done <<< "$cases"
exit $status
