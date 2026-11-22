#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
bad=0
while IFS= read -r path; do
  printf 'forbidden release artifact: %s\n' "$path" >&2
  bad=1
done < <(find "$ROOT" -type f \( -name '*.ckpt' -o -name '*.npz' -o -name '*.pt' -o -name '*.bin' -o -name '*.pyc' -o -name '*.so' -o -name '*.o' -o -name '.ninja*' \) -print)
if find "$ROOT" -type f -size +50M -print -quit | grep -q .; then
  printf 'release contains a file larger than 50 MB\n' >&2
  bad=1
fi
exit "$bad"
