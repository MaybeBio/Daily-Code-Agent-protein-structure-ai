#!/usr/bin/env bash
# Step 33, the final test run: selector-test (already pushed) -> rnapro-inputs-test
#   -> rnapro-run-john-test + rnapro-run-selector-test (GPU, together) -> rnapro-score-test
# Usage, from this folder:  bash run_rnapro_test_chain.sh   (skip steps already COMPLETE by pushing the rest by hand)
set -u
cd "$(dirname "$0")"
st() { timeout 120 kaggle kernels status "alizehadeel/$1" 2>&1; }
wait_for() {
  sleep 60
  until st "$1" | grep -qE 'COMPLETE|ERROR|CANCEL'; do sleep 60; done
  if st "$1" | grep -q COMPLETE; then echo "$(date +%H:%M) $1 complete"; else echo "$(date +%H:%M) $1 FAILED"; return 1; fi
}
push() { echo "$(date +%H:%M) pushing $1"; timeout 300 kaggle kernels push -p "$1" | tail -1; }
wait_for selector-test || exit 1
push rnapro_inputs_test; wait_for rnapro-inputs-test || exit 1
push rnapro_run_john_test; push rnapro_run_selector_test
wait_for rnapro-run-john-test; a=$?
wait_for rnapro-run-selector-test; b=$?
[ $a -eq 0 ] && [ $b -eq 0 ] || exit 1
push rnapro_score_test; wait_for rnapro-score-test || exit 1
echo "$(date +%H:%M) all done"
