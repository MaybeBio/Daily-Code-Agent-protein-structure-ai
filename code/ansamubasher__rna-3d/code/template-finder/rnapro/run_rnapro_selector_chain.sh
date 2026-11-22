#!/usr/bin/env bash
# Runs the RNAPro-with-selector pipeline on Kaggle, one notebook after the other:
#   selector-v5 (exports the selector's top 5)  ->  rnapro-inputs (adapts them like john's)
#   ->  rnapro-run-selector (GPU, ~1.5 h)  ->  rnapro-score (scores both runs, paired comparison)
# Usage, from this folder:  bash run_rnapro_selector_chain.sh
# Each step is pushed only after the previous one finished with status COMPLETE.
set -u
cd "$(dirname "$0")"

wait_for() {                      # $1 = kernel slug; returns 0 when COMPLETE, 1 on error/cancel
  sleep 90
  while true; do
    s=$(kaggle kernels status "alizehadeel/$1" 2>&1)
    case "$s" in
      *COMPLETE*) echo "$(date +%H:%M) $1 complete"; return 0 ;;
      *ERROR*|*CANCEL*) echo "$(date +%H:%M) $1 FAILED: $s"; return 1 ;;
    esac
    sleep 60
  done
}

for step in ../selector/selector_v5:selector-v5 rnapro_inputs:rnapro-inputs rnapro_run_selector:rnapro-run-selector rnapro_score:rnapro-score; do
  dir=${step%%:*}; slug=${step##*:}
  echo "$(date +%H:%M) pushing $slug"
  kaggle kernels push -p "$dir" | tail -1
  wait_for "$slug" || exit 1
done
echo "$(date +%H:%M) all done: kaggle kernels output alizehadeel/rnapro-score -p rnapro_score_out"
