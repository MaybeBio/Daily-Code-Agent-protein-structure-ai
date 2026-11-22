#!/usr/bin/env bash
# run_mmpbsa_validate.sh
# One-shot validation of the corrected MM-PBSA setup (Run1, 11 frames) against the original Aug-4 results.
#
# What it does (stops at the first problem, with a clear message):
#   0. checks that every input file exists
#   1. (re)writes mmpbsa_complex_3010.top  (Protein 3010 atoms + Zn + PRIMA1, same order as md.tpr)
#   2. checks protein / Zn / ligand topologies atom-by-atom against run1_20ns/md.tpr
#   3. runs gmx_MMPBSA on frames 1000,1100,...,2000 (the same frames exist in mmpbsa_run1_energy.csv)
#   4. compares the new per-frame energies with the original ones
#
# Usage:   conda activate tp53_md
#          cd ~/tp53_md_project
#          bash run_mmpbsa_validate.sh
# Result:  mmpbsa_validate/validate_report.txt   <- send me this one file
#
# Nothing in your existing files is modified (only mmpbsa_complex_3010.top and mmpbsa_validate/* are written).

ROOT="${ROOT:-$HOME/tp53_md_project}"
cd "$ROOT" || { echo "Project folder not found: $ROOT"; exit 1; }

OUT="$ROOT/mmpbsa_validate"
mkdir -p "$OUT"
REPORT="$OUT/validate_report.txt"
: > "$REPORT"
say() { echo "$@" | tee -a "$REPORT"; }
die() { say ""; say "STOP: $*"; say "(report saved in $REPORT)"; exit 1; }

say "=== MM-PBSA validation run: $(date) ==="
say "project folder: $ROOT"

# ---------------------------------------------------------------- 0. inputs
say ""
say "[0] checking input files"
need=(
  run1_20ns/md.tpr
  run1_20ns/md_fixed.xtc
  index_run1_clean.ndx
  mmpbsa_quick.in
  topol_Protein_3010.itp
  PRIMA1_july.itp
  topol_Ion_chain_A2.itp
  mmpbsa_run1_energy.csv
  check_top_vs_tpr.py
  tp53_checks.py
)
missing=0
for f in "${need[@]}"; do
  if [ -e "$f" ]; then say "  ok       $f"; else say "  MISSING  $f"; missing=1; fi
done
[ $missing -eq 0 ] || die "missing file(s) listed above. (mmpbsa_quick.in: sed 's/interval=5/interval=100/' mmpbsa.in > mmpbsa_quick.in)"
command -v gmx_MMPBSA >/dev/null 2>&1 || die "gmx_MMPBSA not found - run 'conda activate tp53_md' first"
command -v python >/dev/null 2>&1 || die "python not found"
grep -q "interval=100" mmpbsa_quick.in || die "mmpbsa_quick.in does not contain interval=100"

# ---------------------------------------------------------------- 1. wrapper topology
say ""
say "[1] writing mmpbsa_complex_3010.top"
cat > mmpbsa_complex_3010.top <<'EOF'
#include "amber99sb-ildn.ff/forcefield.itp"

#include "PRIMA1_july.itp"

#include "topol_Protein_3010.itp"

#include "topol_Ion_chain_A2.itp"

[ system ]
Protein-Zn-PRIMA1 complex

[ molecules ]
Protein_chain_A     1
Ion_chain_A2        1
PRIMA1              1
EOF
cat mmpbsa_complex_3010.top | tee -a "$REPORT" >/dev/null
say "  written"

# ---------------------------------------------------------------- 2. topology vs tpr
say ""
say "[2] topology vs run1_20ns/md.tpr (atom names, charges, masses)"
check() {   # $1 = itp file, $2 = MDAnalysis selection of the matching tpr atoms
  local out
  out=$(python check_top_vs_tpr.py run1_20ns/md.tpr "$1" --select "$2" --ignore-resname 2>/dev/null)
  if echo "$out" | grep -q "agree one-to-one"; then
    say "  OK    $1   ($(echo "$out" | grep -E 'net charge' | sed 's/^ *//'))"
  else
    say "  FAIL  $1"; echo "$out" | tail -20 | tee -a "$REPORT"
    die "$1 does not match md.tpr"
  fi
}
check topol_Protein_3010.itp "protein"
check topol_Ion_chain_A2.itp  "resname ZN"
check PRIMA1_july.itp         "resname UNL"

# ---------------------------------------------------------------- 3. gmx_MMPBSA
say ""
say "[3] running gmx_MMPBSA (11 frames; a few minutes)"
cd "$OUT" || die "cannot enter $OUT"
rm -f QUICK_ENERGY.csv QUICK_RESULTS.dat
gmx_MMPBSA -O -i "$ROOT/mmpbsa_quick.in" \
  -cs "$ROOT/run1_20ns/md.tpr" \
  -ct "$ROOT/run1_20ns/md_fixed.xtc" \
  -ci "$ROOT/index_run1_clean.ndx" -cg 1 14 \
  -cp "$ROOT/mmpbsa_complex_3010.top" \
  -o QUICK_RESULTS.dat -eo QUICK_ENERGY.csv -nogui > gmx_mmpbsa_stdout.txt 2>&1
rc=$?
if [ $rc -ne 0 ] || [ ! -s QUICK_ENERGY.csv ]; then
  say "  gmx_MMPBSA FAILED (exit code $rc). Last 25 lines of its output:"
  tail -25 gmx_mmpbsa_stdout.txt | tee -a "$REPORT"
  die "gmx_MMPBSA did not produce QUICK_ENERGY.csv"
fi
say "  done: $(grep -c '^[0-9]' QUICK_ENERGY.csv) data rows written to QUICK_ENERGY.csv"
cd "$ROOT"

# ---------------------------------------------------------------- 4. compare with the original run
say ""
say "[4] comparison with the original Aug-4 per-frame energies"
python tp53_checks.py compare-csv --csv-a mmpbsa_run1_energy.csv --csv-b "$OUT/QUICK_ENERGY.csv" 2>&1 | tee -a "$REPORT"

say ""
say "=== finished: $(date) ==="
say "Send me: $REPORT"
