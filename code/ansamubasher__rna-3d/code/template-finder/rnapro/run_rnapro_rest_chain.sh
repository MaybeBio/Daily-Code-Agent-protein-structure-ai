#!/usr/bin/env bash
# Step 31: RNAPro with plain templates on the other 73 usable validation chains, then score all 123.
#   rnapro-inputs -> rnapro-run-john-plain-rest + rnapro-run-selector-plain-rest (GPU, together) -> rnapro-score
# Usage, from this folder:  bash run_rnapro_rest_chain.sh
set -u
cd "$(dirname "$0")"
wait_for() {
  sleep 90
  while true; do
    s=$(timeout 120 kaggle kernels status "alizehadeel/$1" 2>&1)
    case "$s" in
      *COMPLETE*) echo "$(date +%H:%M) $1 complete"; return 0 ;;
      *ERROR*|*CANCEL*) echo "$(date +%H:%M) $1 FAILED: $s"; return 1 ;;
    esac
    sleep 60
  done
}
echo "$(date +%H:%M) pushing rnapro-inputs"; timeout 300 kaggle kernels push -p rnapro_inputs | tail -1
wait_for rnapro-inputs || exit 1
for d in rnapro_run_john_plain_rest rnapro_run_selector_plain_rest; do
  echo "$(date +%H:%M) pushing $d"; timeout 300 kaggle kernels push -p "$d" | tail -1
done
wait_for rnapro-run-john-plain-rest; a=$?
wait_for rnapro-run-selector-plain-rest; b=$?
[ $a -eq 0 ] && [ $b -eq 0 ] || exit 1
echo "$(date +%H:%M) pushing rnapro-score"; timeout 300 kaggle kernels push -p rnapro_score | tail -1
wait_for rnapro-score || exit 1
echo "$(date +%H:%M) all done: kaggle kernels output alizehadeel/rnapro-score -p rnapro_score_out"
