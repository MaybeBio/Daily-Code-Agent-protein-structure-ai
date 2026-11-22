#!/usr/bin/env bash
# run_decomp_quick.sh
# Quick (11-frame) per-residue DECOMPOSITION test with the validated setup, before the long 201-frame run.
#
# Same inputs as run_mmpbsa_validate.sh (tpr, trajectory, index groups 1 14, topology wrapper), plus a decomposition block:
#   idecomp=2   per-residue decomposition, 1-4 terms added to EEL/VDW (this setup already ran with '&decomp' on 25 Aug)
#   print_res   residues within 6 A of the ligand
#   dec_verbose is tried as 3, then 1, then 0 (the help file in the project gives no meaning for the values),
#               the first value gmx_MMPBSA accepts is used and reported.
#
# Usage:   conda activate tp53_md
#          cd ~/tp53_md_project
#          bash run_decomp_quick.sh
# Result:  mmpbsa_decomp_quick/decomp_quick_report.txt   <- send me this one file
#
# Only files inside mmpbsa_decomp_quick/ are written.

ROOT="${ROOT:-$HOME/tp53_md_project}"
cd "$ROOT" || { echo "Project folder not found: $ROOT"; exit 1; }

OUT="$ROOT/mmpbsa_decomp_quick"
mkdir -p "$OUT"
REPORT="$OUT/decomp_quick_report.txt"
: > "$REPORT"
say() { echo "$@" | tee -a "$REPORT"; }
die() { say ""; say "STOP: $*"; say "(report saved in $REPORT)"; exit 1; }

say "=== quick decomposition test: $(date) ==="

say ""
say "[0] checking input files"
need=( run1_20ns/md.tpr run1_20ns/md_fixed.xtc index_run1_clean.ndx mmpbsa_complex_3010.top
       mmpbsa_quick.in mmpbsa_run1_energy.csv tp53_checks.py )
missing=0
for f in "${need[@]}"; do
  if [ -e "$f" ]; then say "  ok       $f"; else say "  MISSING  $f"; missing=1; fi
done
[ $missing -eq 0 ] || die "missing file(s) listed above (run run_mmpbsa_validate.sh first: it creates mmpbsa_complex_3010.top)"
command -v gmx_MMPBSA >/dev/null 2>&1 || die "gmx_MMPBSA not found - run 'conda activate tp53_md' first"

cd "$OUT" || die "cannot enter $OUT"
used=""
for decv in 3 1 0; do
  say ""
  say "[1] gmx_MMPBSA with idecomp=2, dec_verbose=$decv (11 frames; roughly 10-20 minutes)"
  cat "$ROOT/mmpbsa_quick.in" > decomp_quick.in
  cat >> decomp_quick.in <<EOF

&decomp
  idecomp=2,
  dec_verbose=$decv,
  print_res="within 6",
/
EOF
  rm -f DECOMP_QUICK.dat DECOMP_QUICK.csv DECOMP_QUICK_ENERGY.csv
  gmx_MMPBSA -O -i decomp_quick.in \
    -cs "$ROOT/run1_20ns/md.tpr" \
    -ct "$ROOT/run1_20ns/md_fixed.xtc" \
    -ci "$ROOT/index_run1_clean.ndx" -cg 1 14 \
    -cp "$ROOT/mmpbsa_complex_3010.top" \
    -o DECOMP_QUICK_RESULTS.dat -eo DECOMP_QUICK_ENERGY.csv \
    -do DECOMP_QUICK.dat -deo DECOMP_QUICK.csv -nogui > "gmx_mmpbsa_decomp_stdout_v$decv.txt" 2>&1
  rc=$?
  if [ $rc -eq 0 ] && [ -s DECOMP_QUICK.dat ]; then used=$decv; say "  success with dec_verbose=$decv"; break; fi
  say "  failed (exit code $rc); last lines:"
  tail -8 "gmx_mmpbsa_decomp_stdout_v$decv.txt" | tee -a "$REPORT"
done
[ -n "$used" ] || die "gmx_MMPBSA decomposition failed for dec_verbose 3, 1 and 0 (see the lines above)"

say ""
say "[2] output files"
ls -l DECOMP_QUICK* 2>&1 | tee -a "$REPORT"

say ""
say "[3] first 45 lines of DECOMP_QUICK.dat"
head -n 45 DECOMP_QUICK.dat | tee -a "$REPORT"

say ""
say "[4] lines of DECOMP_QUICK.dat that mention Delta (line number: text)"
grep -n -i "delta" DECOMP_QUICK.dat | head -15 | tee -a "$REPORT"

say ""
say "[5] first 12 lines of DECOMP_QUICK.csv (cut to 220 characters per line)"
head -n 12 DECOMP_QUICK.csv | cut -c1-220 | tee -a "$REPORT"

say ""
say "[6] do the totals of this decomposition run still equal the original run?"
cd "$ROOT"
python tp53_checks.py compare-csv --csv-a mmpbsa_run1_energy.csv --csv-b "$OUT/DECOMP_QUICK_ENERGY.csv" 2>&1 | tail -12 | tee -a "$REPORT"

say ""
say "=== finished: $(date) ==="
say "Send me: $REPORT"
