#!/bin/bash
set -u
B=/root/FIG4_73
L=$B/run.log
log(){ echo "[$(date '+%F %T')] $*" | tee -a $L; }
cd /root/LLM/Model-Eval || exit 1
log "start on 4090D, 9 groups"
for name in fig4a_training fig4a_overlap fig4a_unseen fig4b_size_2-3 fig4b_size_4-5 fig4b_size_6+ fig4b_degree_low fig4b_degree_mid fig4b_degree_high; do
  if [ -s $B/gen/$name.pkl ]; then log "skip $name"; continue; fi
  log "gen $name"
  /root/miniconda3/bin/python Eval_Model_73_seedset.py \
     --prompt_pkl $B/seeds/$name.pkl --output_file $B/gen/$name.pkl \
     --bias_alpha 2.0 --temperature 0.85 --top_p 0.85 --top_k 10 --seed 20030201 \
     > $B/logs/$name.log 2>&1
  [ -s $B/gen/$name.pkl ] && log "ok $name ($(grep -c . $B/logs/$name.log) log lines)" || log "FAIL $name"
done
log "scoring"
/root/miniconda3/bin/python $B/make_fig4_table.py >> $L 2>&1
log "FIG4 DONE"
