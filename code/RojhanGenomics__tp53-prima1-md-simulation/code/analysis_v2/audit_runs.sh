#!/usr/bin/env bash
# audit_runs.sh -- facts about HOW each run was really made (needed to write an honest Methods section)
#
# Collects, read-only, into one report:
#   [1] thermostat groups, continuation, velocity generation, steps ... from every .mdp that exists
#   [2] the real length of every trajectory (gmx check: number of frames, first/last time)
#   [3] how each mdrun ended (Statistics over / Finished mdrun lines of the log files)
#   [4] differences between tpr files that should be identical (gmx check -s1 -s2)
#   [5] the output of your own scripts compare_initial_states.py and compare_tpr_velocities.py (if present)
#
# Usage:   conda activate tp53_md
#          cd ~/tp53_md_project
#          bash audit_runs.sh
# Result:  audit_runs_report.txt   <- send me this one file
# Nothing is modified.

ROOT="${ROOT:-$HOME/tp53_md_project}"
cd "$ROOT" || { echo "Project folder not found: $ROOT"; exit 1; }
REPORT="$ROOT/audit_runs_report.txt"
: > "$REPORT"
say() { echo "$@" | tee -a "$REPORT"; }
command -v gmx >/dev/null 2>&1 || { echo "gmx not found"; exit 1; }

say "=== audit of how the runs were made: $(date) ==="

say ""
say "[1] settings in the .mdp files (file: key = value)"
for f in $(ls -1 *.mdp run*_20ns/*.mdp negative_control/*.mdp negative_control/v2_correct/*.mdp 2>/dev/null); do
  say "--- $f  ($(stat -c %y "$f" | cut -c1-16))"
  grep -i -E "^\s*(tc[-_]grps|tau[-_]t|ref[-_]t|continuation|gen[-_]vel|gen[-_]seed|gen[-_]temp|nsteps|define|pcoupl |pcoupl=|tau[-_]p|nstlist|nsttcouple|nstpcouple|constraints|nstxout[-_]compressed)\s*=" "$f" 2>/dev/null \
    | sed 's/;.*//' | sed 's/^\s*//' | tee -a "$REPORT"
done

say ""
say "[2] real length of each trajectory (gmx check -f)"
for x in md.xtc run1_20ns/md.xtc run1_20ns/md_fixed.xtc md_run2.xtc run2_20ns/md_run2.xtc run2_20ns/md_run2_fixed.xtc \
         md_run3.xtc run3_20ns/md_run3.xtc run3_20ns/md_run3_fixed.xtc run4_20ns/md_run4.xtc run4_20ns/md_run4_fixed.xtc \
         negative_control/v2_correct/md_negctrl.xtc negative_control/v2_correct/md_negctrl_final_fixed.xtc; do
  [ -e "$x" ] || continue
  say "--- $x  ($(stat -c %y "$x" | cut -c1-16), $(du -h "$x" | cut -f1))"
  gmx check -f "$x" 2>&1 | grep -E "^Coords|^Last frame|^Reading frame|Item +#frames" | head -4 | tee -a "$REPORT"
done

say ""
say "[3] how each mdrun ended (log files)"
for l in md.log md_run_log md_run_log_continued md_run_log_continued2 run1_20ns/md.log md_run2.log md_run2_log md_run2_log_continued \
         md_run3.log md_run3_log md_run3_log_continued run4_20ns/md_run4.log md_run4.log \
         negative_control/v2_correct/md_negctrl.log negative_control/v2_correct/md_negctrl_run.log negative_control/v2_correct/md_negctrl_resume.log; do
  [ -e "$l" ] || continue
  say "--- $l  ($(stat -c %y "$l" | cut -c1-16))"
  grep -E "Statistics over|Finished mdrun|^Command line|-nsteps|-maxh|Started mdrun on" "$l" 2>/dev/null | head -6 | tee -a "$REPORT"
done

say ""
say "[4] tpr files that should describe the same run (gmx check -s1 -s2; first 25 lines of the differences)"
cmp_tpr() {
  [ -e "$1" ] && [ -e "$2" ] || { say "--- $1 vs $2: one of the files is missing"; return; }
  say "--- $1  vs  $2"
  gmx check -s1 "$1" -s2 "$2" 2>&1 | grep -v -E "^$|GROMACS|Copyright|Uppsala|check out|Executable|Data prefix|Working dir|Command line|reminds you|Reading file" | head -25 | tee -a "$REPORT"
}
cmp_tpr md.tpr run1_20ns/md.tpr
cmp_tpr md_run2.tpr run2_20ns/md_run2.tpr
cmp_tpr md_run3.tpr run3_20ns/md_run3.tpr
cmp_tpr md_run4.tpr run4_20ns/md_run4.tpr

say ""
say "[5] your own comparison scripts"
for s in compare_initial_states.py compare_tpr_velocities.py; do
  if [ -e "$s" ]; then
    say "--- python $s (last 40 lines)"
    python "$s" 2>&1 | tail -40 | tee -a "$REPORT"
  else
    say "--- $s not found"
  fi
done

say ""
say "=== finished: $(date) ==="
say "Send me: $REPORT"
