#!/bin/bash
set -u
A=/root/ALIGN_2026-11-15
L=$A/align.log
log(){ echo "[$(date '+%F %T')] $*" | tee -a $L; }
cd /root/LLM73/train || exit 1
log "armA SFT retry (batch 32 x4 x accum2 = 256), entry = _4"
/root/miniconda3/bin/torchrun --nproc_per_node=4 --master_port=29931 SFT_noCL_5ep.py --ddp \
  --data_path /root/LLM/Model-Heltout/Dataset/finetune_data/sft_0.json \
  --out_dir $A/armA_5ep/out_sft --log_dir $A/armA_5ep/logs \
  --epochs 2 --batch_size 32 --accumulation_steps 2 --max_seq_len 128 \
  --learning_rate 5e-6 --save_interval 20000 >> $A/armA_5ep/logs/train_sft.log 2>&1
[ -f $A/armA_5ep/out_sft/full_sft_512_1.pth ] || { log "FAIL sft retry"; exit 1; }
log "armA SFT done"

sed "s#/root/ESM2_ARM/out_sft#$A/armA_5ep/out_sft#" /root/LLM/Model-Eval/Eval_Model_ESM2.py \
    > /root/LLM/Model-Eval/Eval_Model_noCL_5ep.py
cd /root/LLM/Model-Eval || exit 1
log "armA generation start"
/root/miniconda3/bin/python Eval_Model_noCL_5ep.py --output_file $A/armA_5ep/gen/gen_noCL_5ep.pkl \
   --bias_alpha 2.0 --seed 20030201 >> $A/armA_5ep/logs/gen.log 2>&1
[ -s $A/armA_5ep/gen/gen_noCL_5ep.pkl ] || { log "FAIL gen"; exit 1; }
log "armA gen done, scoring"
/root/miniconda3/bin/python /root/GRACE_ABLATION_2026-11-15/arm_A_noCL/score.py \
   $A/armA_5ep/gen/gen_noCL_5ep.pkl >> $L 2>&1
log "armA SCORED"
