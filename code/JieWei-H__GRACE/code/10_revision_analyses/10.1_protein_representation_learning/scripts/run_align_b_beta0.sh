#!/bin/bash
set -u
A=/root/ALIGN_B_4090/armB_5ep
L=/root/ALIGN_B_4090/align_B.log
log(){ echo "[$(date '+%F %T')] $*" | tee -a $L; }
cd /root/LLM/Model-Eval || exit 1
log "armB beta=0 generation start (5-epoch checkpoint)"
/root/miniconda3/bin/python Eval_Model_ESM2_5ep.py --output_file $A/gen/gen_ESM2_5ep_beta0.pkl \
   --bias_alpha 0.0 --seed 20030201 >> $A/logs/gen_beta0.log 2>&1
[ -s $A/gen/gen_ESM2_5ep_beta0.pkl ] && log "armB beta0 done" || { log "FAIL beta0"; exit 1; }
/root/miniconda3/bin/python /root/GRACE_ABLATION_2026-11-15/arm_B_ESM2/score.py \
   $A/gen/gen_ESM2_5ep_beta0.pkl >> $L 2>&1
log "armB beta0 SCORED"
