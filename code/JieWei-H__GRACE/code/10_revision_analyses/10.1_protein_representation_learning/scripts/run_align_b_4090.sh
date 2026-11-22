#!/bin/bash
set -u
A=/root/ALIGN_B_4090/armB_5ep
L=/root/ALIGN_B_4090/align_B.log
log(){ echo "[$(date '+%F %T')] $*" | tee -a $L; }

log "armB SFT start on 4090D (1 GPU, batch 64 x accum 4 = 256), pretrain entry = _4 (5 epochs)"
cd /root/LLM73/train || exit 1
/root/miniconda3/bin/torchrun --nproc_per_node=1 --master_port=29921 SFT_ESM2_5ep.py --ddp \
  --data_path /root/LLM/Model-Heltout/Dataset/finetune_data/sft_0.json \
  --out_dir $A/out_sft --log_dir $A/logs \
  --epochs 2 --batch_size 64 --accumulation_steps 4 --max_seq_len 128 \
  --learning_rate 5e-6 --save_interval 20000 >> $A/logs/train_sft.log 2>&1
[ -f $A/out_sft/full_sft_512_1.pth ] || { log "FAIL sft"; exit 1; }
log "armB SFT done"

sed "s#/root/ESM2_ARM/out_sft#$A/out_sft#" /root/LLM/Model-Eval/Eval_Model_ESM2.py \
    > /root/LLM/Model-Eval/Eval_Model_ESM2_5ep.py
cd /root/LLM/Model-Eval || exit 1
log "armB generation start (beta=2.0)"
/root/miniconda3/bin/python Eval_Model_ESM2_5ep.py --output_file $A/gen/gen_ESM2_5ep.pkl \
   --bias_alpha 2.0 --seed 20030201 >> $A/logs/gen.log 2>&1
[ -s $A/gen/gen_ESM2_5ep.pkl ] || { log "FAIL gen"; exit 1; }
log "armB gen done, scoring"
/root/miniconda3/bin/python /root/GRACE_ABLATION_2026-11-15/arm_B_ESM2/score.py $A/gen/gen_ESM2_5ep.pkl >> $L 2>&1
log "armB SCORED"
