#!/usr/bin/env bash
# audit_runs2.sh -- second part of the run audit (answers the questions left open by audit_runs_report.txt)
#
#   [1] the real mdrun command lines, how each log ended, and the last logged step/time
#   [2] tpr vs tpr: ONLY the differences in the input record (the first report was cut off by the GROMACS banner)
#   [3] index files: how many atoms are in the thermostat groups (Protein_ZN_UNL, SOL_CL, Protein_ZN_QNC ...)
#   [4] temperature during the first 10 ps of every production run (does Run1 start at ~300 K like the others?)
#
# Usage:   conda activate tp53_md
#          cd ~/tp53_md_project
#          bash audit_runs2.sh
# Result:  audit_runs2_report.txt   <- send me this one file
# Nothing is modified (temperature files are written to audit_runs2_out/).

ROOT="${ROOT:-$HOME/tp53_md_project}"
cd "$ROOT" || { echo "Project folder not found: $ROOT"; exit 1; }
REPORT="$ROOT/audit_runs2_report.txt"
OUT="$ROOT/audit_runs2_out"
mkdir -p "$OUT"
: > "$REPORT"
say() { echo "$@" | tee -a "$REPORT"; }
command -v gmx >/dev/null 2>&1 || { echo "gmx not found"; exit 1; }

say "=== audit of the runs, part 2: $(date) ==="

say ""
say "[1] mdrun command lines and endings"
for l in md.log run1_20ns/md.log md_run2.log run2_20ns/md_run2.log md_run3.log run3_20ns/md_run3.log \
         run4_20ns/md_run4.log negative_control/v2_correct/md_negctrl.log; do
  [ -e "$l" ] || continue
  say "--- $l  ($(stat -c %y "$l" | cut -c1-16))"
  say "  mdrun command line(s):"
  grep -A1 "^Command line:" "$l" | grep -v -E "^Command line:|^--" | sed 's/^ */    /' | cut -c1-170 | tee -a "$REPORT"
  say "  starts / endings:"
  grep -E "Started mdrun|Statistics over|Finished mdrun|maximum number of steps|Received the (TERM|INT)|Received signal" "$l" \
    | sed 's/^ */    /' | cut -c1-120 | tee -a "$REPORT"
  say "  last logged step/time:"
  grep -A1 -E "^ +Step +Time" "$l" | tail -n 2 | sed 's/^/    /' | tee -a "$REPORT"
done

say ""
say "[2] tpr vs tpr: differences in the input record only"
cmp_tpr() {
  if [ ! -e "$1" ] || [ ! -e "$2" ]; then say "--- $1 vs $2: one of the files is missing"; return; fi
  say "--- $1  vs  $2"
  res=$(gmx check -s1 "$1" -s2 "$2" 2>&1 | sed -n '/^comparing inputrec/,$p' | grep -v -E "^comparing (mtop|force|molecule|atoms|t_resinfo|t_pdbinfo|bonded|state|topology|X|V)" | head -60)
  if [ -z "$(echo "$res" | grep -v '^comparing inputrec')" ]; then say "    no differences found in inputrec"; else echo "$res" | sed 's/^/    /' | tee -a "$REPORT"; fi
}
cmp_tpr md.tpr run1_20ns/md.tpr
cmp_tpr md_run2.tpr run2_20ns/md_run2.tpr
cmp_tpr md_run3.tpr run3_20ns/md_run3.tpr
cmp_tpr md.tpr md_run2.tpr
cmp_tpr md_run2.tpr md_run3.tpr
cmp_tpr md_run2.tpr run4_20ns/md_run4.tpr

say ""
say "[3] atoms per thermostat group in every index file"
for f in $(find . -maxdepth 3 -name "*.ndx" -not -name "_GMXMMPBSA*" | sort); do
  say "--- $f  ($(stat -c %y "$f" | cut -c1-16))"
  awk '/^\[/{if(name!="")print name, n; name=$0; n=0; next} {n+=NF} END{if(name!="")print name, n}' "$f" \
    | grep -E "Protein_ZN_UNL|Protein_ZN_QNC|SOL_CL|\[ UNL |\[ QNC |\[ Protein \]|\[ System \]" | sed 's/^/    /' | tee -a "$REPORT"
done
say "  expected for PRIMA-1 (Run1-4): Protein_ZN_UNL = 3039 atoms (3010 protein + 1 Zn + 28 ligand); SOL_CL = 43043 atoms (14346 waters x 3 + 5 Cl-)"
say "  expected for the negative control: Protein_ZN_QNC = 3021 atoms (2999 + 1 + 21); SOL_CL = 43149 atoms (14381 x 3 + 6)"

say ""
say "[4] temperature of the first 10 ps of each production run (kelvin; time in ps)"
tmp_run() {  # name edr
  if [ ! -e "$2" ]; then say "--- $1: $2 not found"; return; fi
  printf "Temperature\n\n" | gmx energy -f "$2" -b 0 -e 10 -o "$OUT/T_$1.xvg" > "$OUT/T_$1.log" 2>&1
  if [ -s "$OUT/T_$1.xvg" ]; then
    say "--- $1  ($2)"
    grep -v '^[#@]' "$OUT/T_$1.xvg" | head -4 | sed 's/^/    /' | tee -a "$REPORT"
    grep -v '^[#@]' "$OUT/T_$1.xvg" | awk '{s+=$2;n++} END{printf "    mean over the first 10 ps: %.1f K (%d points)\n", s/n, n}' | tee -a "$REPORT"
  else
    say "--- $1: gmx energy failed; last lines:"; tail -4 "$OUT/T_$1.log" | sed 's/^/    /' | tee -a "$REPORT"
  fi
}
tmp_run Run1 md.edr
tmp_run Run1_folder run1_20ns/md.edr
tmp_run Run2 md_run2.edr
tmp_run Run3 md_run3.edr
tmp_run Run4 run4_20ns/md_run4.edr
tmp_run NegCtrl negative_control/v2_correct/md_negctrl.edr

say ""
say "=== finished: $(date) ==="
say "Send me: $REPORT"
