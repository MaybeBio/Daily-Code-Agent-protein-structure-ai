#!/usr/bin/env bash
# The full experiment: every arm, every seed.
#
#   bash scripts/run_grid.sh                     # all arms, seeds 0 1 2, SCOPe
#   SEEDS="1 2" bash scripts/run_grid.sh         # only the seeds still missing
#   ARMS="b d" bash scripts/run_grid.sh
#   CORPUS=alphafold bash scripts/run_grid.sh    # the same grid on the other corpus
#
# Checkpoints and logs are named by arm, corpus and seed, so the two corpora never
# overwrite each other and runs.csv records which corpus each row came from.
#
# Safe to run again after an interruption. Pretraining resumes from its last saved epoch,
# and a run whose encoder checkpoint already exists is skipped, so nothing is repeated.
# Fine-tuning is cheap enough to always redo.
#
# Roughly 45 to 70 min of pretraining per arm-seed, plus 2 min of fine-tuning, so the
# nine pretraining runs are about eight hours on the Mac. Run it under `caffeinate -i -s`
# or the laptop will sleep through it.
set -uo pipefail

ARMS=${ARMS:-"a b c d"}
SEEDS=${SEEDS:-"0 1 2"}
CORPUS=${CORPUS:-scope}
LOG_DIR=results/logs
mkdir -p "$LOG_DIR" results/checkpoints

started=$(date +%s)
failed=()

for seed in $SEEDS; do
  for arm in $ARMS; do
    config=configs/arm_${arm}.yaml
    tag=${arm}_${CORPUS}_seed${seed}
    log=$LOG_DIR/${tag}.log
    echo "=== arm ${arm}, ${CORPUS}, seed ${seed}  ($(date +%H:%M))"

    # Arm A has no pretraining stage; the others skip it if the encoder is already there.
    if [ "$arm" != "a" ]; then
      encoder="results/checkpoints/encoder_$(echo "$arm" | tr a-z A-Z)_${CORPUS}_seed${seed}.pt"
      if [ -f "$encoder" ]; then
        echo "    pretrained encoder exists, skipping"
      else
        echo "    pretraining -> $log"
        if ! python -m pobj.train.pretrain --config "$config" --seed "$seed" \
             --corpus "$CORPUS" >>"$log" 2>&1; then
          echo "    PRETRAIN FAILED, see $log"
          failed+=("pretrain ${tag}")
          continue
        fi
      fi
    fi

    echo "    fine-tuning"
    if ! python -m pobj.train.finetune --config "$config" --seed "$seed" \
         --corpus "$CORPUS" >>"$log" 2>&1; then
      echo "    FINETUNE FAILED, see $log"
      failed+=("finetune ${tag}")
      continue
    fi
    tail -2 "$log" | head -1 | sed 's/^/    /'
  done
done

echo
echo "finished in $(( ($(date +%s) - started) / 60 )) min"
if [ ${#failed[@]} -gt 0 ]; then
  printf 'failed: %s\n' "${failed[@]}"
  exit 1
fi

echo "rows in results/runs.csv: $(( $(wc -l < results/runs.csv) - 1 ))"
echo "now run: python scripts/make_report.py"
