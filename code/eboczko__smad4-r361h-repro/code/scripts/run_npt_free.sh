#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
project="$PWD"

for system in 03_wt 04_R361H; do
  (
    cd "$project/$system/initial_em"
    if [ -e npt_free.tpr ] || [ -e npt_free.log ]; then
      echo "STOP: existing unrestrained-equilibration files in $PWD"
      exit 1
    fi

    python - <<'PY'
from pathlib import Path

lines = []
for line in Path("npt_weak.mdp").read_text().splitlines():
    key = line.split("=", 1)[0].strip()
    if key in {"define", "refcoord-scaling"}:
        continue
    if key == "nsteps":
        line = "nsteps = 500000"
    lines.append(line)
Path("npt_free.mdp").write_text("\n".join(lines) + "\n")
PY

    gmx grompp -f npt_free.mdp \
      -c npt_weak.gro -t npt_weak.cpt \
      -p topol.top -pp processed_free.top \
      -o npt_free.tpr > npt_free_preparation.log 2>&1

    python - <<'PY'
from pathlib import Path
import re

text = Path("processed_free.top").read_text()
if re.search(r"^\s*\[\s*position_restraints\s*\]", text, re.M):
    raise SystemExit("STOP: position restraints remain in the processed topology.")
print("Verified: no position-restraint sections.")
PY

    echo "$system: running 1 ns unrestrained NPT..."
    gmx mdrun -deffnm npt_free -ntmpi 1 -ntomp 8 -nb gpu -pme gpu -pin on \
      > npt_free_console.log 2>&1

    python - <<'PY'
from pathlib import Path
import re

text = Path("npt_free.log").read_text() + Path("npt_free_console.log").read_text()
if re.search(r"LINCS WARNING|SHAKE did not converge|Fatal error", text, re.I):
    raise SystemExit("STOP: numerical warning/error; inspect logs.")
if not all(Path(p).is_file() for p in (
    "npt_free.gro", "npt_free.cpt", "npt_free.edr"
)):
    raise SystemExit("STOP: missing run outputs.")
print("Unrestrained NPT completed without detected constraint warnings.")
PY

    printf 'Temperature\nPressure\nDensity\nVolume\n0\n' | gmx energy \
      -f npt_free.edr -b 500 -o npt_free_properties.xvg \
      > npt_free_properties_summary.log 2>&1

    grep -E '^(Temperature|Pressure|Density|Volume)[[:space:]]' \
      npt_free_properties_summary.log
  )
done

echo "Unrestrained equilibration finished. Production has not started."
