#!/usr/bin/env bash
# Step 32 control: rnapro-inputs (writes native_templates.csv) -> rnapro-run-native (GPU) -> rnapro-score
# Usage, from this folder:  bash run_rnapro_native_chain.sh
set -u
cd "$(dirname "$0")"
done_ok() { timeout 120 kaggle kernels status "alizehadeel/$1" 2>&1 | grep -qE "$2"; }
wait_for() {
  sleep 90
  until done_ok "$1" 'COMPLETE|ERROR|CANCEL'; do sleep 60; done
  if done_ok "$1" COMPLETE; then echo "$(date +%H:%M) $1 complete"; else echo "$(date +%H:%M) $1 FAILED"; return 1; fi
}
for step in rnapro_inputs:rnapro-inputs rnapro_run_native:rnapro-run-native rnapro_score:rnapro-score; do
  dir=${step%%:*}; slug=${step##*:}
  echo "$(date +%H:%M) pushing $slug"; timeout 300 kaggle kernels push -p "$dir" | tail -1
  wait_for "$slug" || exit 1
done
echo "$(date +%H:%M) all done"
