#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
project="$PWD"

for system in 03_wt 04_R361H; do
  (
    cd "$project/$system/initial_em"
    if [ -e nvt.tpr ] || [ -e nvt.log ]; then
      echo "STOP: existing NVT files in $PWD"
      exit 1
    fi

    seed=20260931
    if [ "$system" = "04_R361H" ]; then
      seed=20260932
    fi

    cat > nvt.mdp <<EOF
integrator = md
dt = 0.002
nsteps = 50000
continuation = no
define = -DPOSRES

constraints = h-bonds
constraint-algorithm = lincs
lincs-iter = 1
lincs-order = 4

cutoff-scheme = Verlet
nstlist = 20
rlist = 1.2
coulombtype = PME
rcoulomb = 1.2
vdwtype = Cut-off
vdw-modifier = Force-switch
rvdw-switch = 1.0
rvdw = 1.2
DispCorr = no
pbc = xyz

tcoupl = V-rescale
tc-grps = Protein Water_and_ions
tau-t = 1.0 1.0
ref-t = 310 310
pcoupl = no

gen-vel = yes
gen-temp = 310
gen-seed = $seed
ld-seed = $seed

nstenergy = 500
nstlog = 500
nstxout-compressed = 5000
comm-mode = Linear
nstcomm = 100
EOF

    gmx grompp -f nvt.mdp \
      -c em.gro -r em.gro \
      -p topol.top -o nvt.tpr \
      > nvt_preparation.log 2>&1

    echo "$system: running 100 ps restrained NVT..."
    gmx mdrun -deffnm nvt -ntmpi 1 -ntomp 4 -nb cpu -pme cpu -bonded cpu -update cpu \
      > nvt_console.log 2>&1

    python - <<'PY'
from pathlib import Path
import re

text = Path("nvt.log").read_text()
console = Path("nvt_console.log").read_text()
if re.search(r"LINCS WARNING|SHAKE did not converge|Fatal error",
             text + console, re.I):
    raise SystemExit("STOP: numerical warning/error; inspect NVT logs.")
if not all(Path(p).is_file() for p in ("nvt.gro", "nvt.cpt", "nvt.edr")):
    raise SystemExit("STOP: missing NVT output files.")
print("NVT outputs present; no detected constraint warnings.")
PY

    printf 'Temperature\n0\n' | gmx energy \
      -f nvt.edr -b 50 -o nvt_temperature.xvg \
      > nvt_temperature_summary.log 2>&1

    grep -E '^Temperature[[:space:]]' nvt_temperature_summary.log
  )
done

echo "NVT finished for both systems. No NPT or production MD launched."
