#!/bin/bash
set -u
A=/root/ALIGN_2026-11-15
mkdir -p $A/armA_5ep/out_pre $A/armA_5ep/out_sft $A/armA_5ep/logs $A/armA_5ep/gen
L=$A/align.log
log(){ echo "[$(date '+%F %T')] $*" | tee -a $L; }

# 等臂 B 的 SFT 让出 GPU（4 卡各 ~8GB 才够）
log "waiting for armB SFT to release GPUs"
for i in $(seq 1 60); do
  if [ -f $A/armB_5ep/out_sft/full_sft_512_1.pth ]; then break; fi
  sleep 30
done
sleep 20
log "armA pretrain start (10-epoch schedule, stop after epoch 5 checkpoint), batch 32 x4 x accum16 = 2048"
cd /root/LLM73/train || exit 1
setsid /root/miniconda3/bin/torchrun --nproc_per_node=4 --master_port=29911 Pretrain_Cosine.py --ddp \
  --data_path /root/LLM/Model-Heltout/Dataset/pretrain_data/pretrain_combined.json \
  --out_dir $A/armA_5ep/out_pre --log_dir $A/armA_5ep/logs \
  --epochs 10 --batch_size 32 --accumulation_steps 16 --max_seq_len 256 \
  --learning_rate 5e-4 --save_interval 20000 \
  --external_embedding_path /root/LLM/node_embeddings_PPI.pt \
  >> $A/armA_5ep/logs/train_pre.log 2>&1 &
PIDS=$!
log "pretrain launched, waiting for pretrain_512_4.pth"
for i in $(seq 1 800); do
  [ -f $A/armA_5ep/out_pre/pretrain_512_4.pth ] && { log "epoch5 checkpoint found, stopping pretrain"; break; }
  sleep 30
done
pkill -f "armA_5ep/out_pre" 2>/dev/null
pkill -f "master_port=29911" 2>/dev/null
sleep 8
log "pretrain stopped; files: $(ls $A/armA_5ep/out_pre | tr '\n' ' ')"

log "armA SFT start (from _4)"
R=/root/GRACE_ABLATION_2026-11-15/arm_A_noCL
ln -sfn $A/armA_5ep/out_pre/pretrain_512_4.pth $A/armA_5ep/out_pre/pretrain_512_9.pth
sed "s#../out_pre_noCL/#$A/armA_5ep/out_pre/#" /root/LLM73/train/SFT_noCL.py > /root/LLM73/train/SFT_noCL_5ep.py
/root/miniconda3/bin/torchrun --nproc_per_node=4 --master_port=29912 SFT_noCL_5ep.py --ddp \
  --data_path /root/LLM/Model-Heltout/Dataset/finetune_data/sft_0.json \
  --out_dir $A/armA_5ep/out_sft --log_dir $A/armA_5ep/logs \
  --epochs 2 --batch_size 32 --accumulation_steps 2 --max_seq_len 128 \
  --learning_rate 5e-6 --save_interval 20000 >> $A/armA_5ep/logs/train_sft.log 2>&1
[ -f $A/armA_5ep/out_sft/full_sft_512_1.pth ] || { log "FAIL armA sft"; exit 1; }
log "armA SFT done"

sed "s#/root/LLM73/out_sft_noCL#$A/armA_5ep/out_sft#" /root/LLM/Model-Eval/Eval_Model_noCL.py \
    > /root/LLM/Model-Eval/Eval_Model_noCL_5ep.py 2>/dev/null || \
sed "s#/root/ESM2_ARM/out_sft#$A/armA_5ep/out_sft#" /root/LLM/Model-Eval/Eval_Model_ESM2.py \
    > /root/LLM/Model-Eval/Eval_Model_noCL_5ep.py
cd /root/LLM/Model-Eval || exit 1
log "armA generation start (beta=2.0)"
/root/miniconda3/bin/python Eval_Model_noCL_5ep.py --output_file $A/armA_5ep/gen/gen_noCL_5ep.pkl \
   --bias_alpha 2.0 --seed 20030201 >> $A/armA_5ep/logs/gen.log 2>&1
[ -s $A/armA_5ep/gen/gen_noCL_5ep.pkl ] || { log "FAIL armA gen"; exit 1; }
log "armA gen done, scoring"
/root/miniconda3/bin/python $R/score.py $A/armA_5ep/gen/gen_noCL_5ep.pkl >> $L 2>&1
log "armA SCORED"
