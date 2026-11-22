#!/usr/bin/env bash
# run_decomp.sh -- per-residue decomposition with the VALIDATED setup, followed by analyze_decomp.py
#
#   bash run_decomp.sh quick    11 frames (1000,1100,...,2000)       ~15-30 min   -> mmpbsa_decomp_all_quick/
#   bash run_decomp.sh full     201 frames (mmpbsa.in = 25 Aug-style 1000-2000 every 5)   ~3-4 h  -> mmpbsa_decomp_full/
#
# Settings: idecomp=2, dec_verbose=3 (accepted by your gmx_MMPBSA in the quick test), print_res="all"
#           (all residues are printed so that the sum of the per-residue Delta values can be checked against the total Delta G).
#           If print_res="all" is rejected, print_res="1-195" (all residues of the complex) is tried.
# Receptor = group 1 (Protein), ligand = group 14 (UNL), topology mmpbsa_complex_3010.top  (see run_mmpbsa_validate.sh).
#
# Optional:  NP=4 bash run_decomp.sh full      -> runs gmx_MMPBSA with 4 MPI processes (faster; default is 1)
# For the full run use:   nohup bash run_decomp.sh full > decomp_full_console.txt 2>&1 &     then   tail -f decomp_full_console.txt
#
# Report: <output folder>/decomp_report.txt   <- send me this one file
# Only files inside the output folder are written.

MODE="${1:-}"
case "$MODE" in
  quick) IN_FILE="mmpbsa_quick.in"; OUTNAME="mmpbsa_decomp_all_quick";;
  full)  IN_FILE="mmpbsa.in";       OUTNAME="mmpbsa_decomp_full";;
  *) echo "usage: bash run_decomp.sh quick|full"; exit 1;;
esac
NP="${NP:-1}"
ROOT="${ROOT:-$HOME/tp53_md_project}"
cd "$ROOT" || { echo "Project folder not found: $ROOT"; exit 1; }
OUT="$ROOT/$OUTNAME"
mkdir -p "$OUT"
REPORT="$OUT/decomp_report.txt"
: > "$REPORT"
say() { echo "$@" | tee -a "$REPORT"; }
die() { say ""; say "STOP: $*"; say "(report saved in $REPORT)"; exit 1; }

say "=== decomposition ($MODE): $(date) ==="
say "[0] checking input files"
need=( run1_20ns/md.tpr run1_20ns/md_fixed.xtc index_run1_clean.ndx mmpbsa_complex_3010.top "$IN_FILE"
       mmpbsa_run1_energy.csv analyze_decomp.py tp53_checks.py )
missing=0
for f in "${need[@]}"; do
  if [ -e "$f" ]; then say "  ok       $f"; else say "  MISSING  $f"; missing=1; fi
done
[ $missing -eq 0 ] || die "missing file(s) listed above (analyze_decomp.py must be copied into the project folder)"
command -v gmx_MMPBSA >/dev/null 2>&1 || die "gmx_MMPBSA not found - run 'conda activate tp53_md' first"
if [ "$MODE" = "full" ]; then
  grep -q "interval=5" "$IN_FILE" || die "$IN_FILE does not contain interval=5 (expected the original 201-frame setup)"
fi
RUN=(gmx_MMPBSA)
[ "$NP" -gt 1 ] && RUN=(mpirun -np "$NP" gmx_MMPBSA)
say "  processes: $NP"

cd "$OUT" || die "cannot enter $OUT"
used=""
for pr in "all" "1-195"; do
  say ""
  say "[1] gmx_MMPBSA decomposition with print_res=\"$pr\""
  cat "$ROOT/$IN_FILE" > decomp.in
  cat >> decomp.in <<EOF

&decomp
  idecomp=2,
  dec_verbose=3,
  print_res="$pr",
/
EOF
  rm -f DECOMP.dat DECOMP.csv ENERGY.csv RESULTS.dat
  "${RUN[@]}" -O -i decomp.in \
    -cs "$ROOT/run1_20ns/md.tpr" \
    -ct "$ROOT/run1_20ns/md_fixed.xtc" \
    -ci "$ROOT/index_run1_clean.ndx" -cg 1 14 \
    -cp "$ROOT/mmpbsa_complex_3010.top" \
    -o RESULTS.dat -eo ENERGY.csv -do DECOMP.dat -deo DECOMP.csv -nogui > "gmx_mmpbsa_stdout_${pr}.txt" 2>&1
  rc=$?
  if [ $rc -eq 0 ] && [ -s DECOMP.csv ] && [ -s ENERGY.csv ]; then used="$pr"; say "  success (print_res=\"$pr\")"; break; fi
  say "  failed (exit code $rc); last lines:"
  tail -8 "gmx_mmpbsa_stdout_${pr}.txt" | tee -a "$REPORT"
done
[ -n "$used" ] || die "gmx_MMPBSA failed for both print_res values (see lines above)"

say ""
say "[2] output files"
ls -l DECOMP.csv DECOMP.dat ENERGY.csv RESULTS.dat 2>&1 | tee -a "$REPORT"

say ""
say "[3] totals still identical to the original run?"
cd "$ROOT"
python tp53_checks.py compare-csv --csv-a mmpbsa_run1_energy.csv --csv-b "$OUT/ENERGY.csv" 2>&1 | tail -11 | tee -a "$REPORT"

say ""
say "[4] per-residue Delta analysis"
OCC="analysis_checks/Run1_residue_occupancy.csv"
[ -e "$OCC" ] || { say "  (no $OCC: contact occupancy will be n/a; run: python tp53_checks.py md --root ~/tp53_md_project --only Run1)"; OCC=""; }
python analyze_decomp.py --decomp-csv "$OUT/DECOMP.csv" --energy-csv "$OUT/ENERGY.csv" --occupancy "$OCC" --out "$OUT" 2>&1 | tee -a "$REPORT"

say ""
say "=== finished: $(date) ==="
say "Send me: $REPORT"
