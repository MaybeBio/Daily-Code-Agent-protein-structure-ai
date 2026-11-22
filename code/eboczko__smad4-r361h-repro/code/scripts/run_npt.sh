#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
project="$PWD"

for system in 03_wt 04_R361H; do
  (
    cd "$project/$system/initial_em"
    if [ -e npt.tpr ] || [ -e npt.log ]; then
      echo "STOP: existing NPT files in $PWD"
      exit 1
    fi

    python - <<'PY'
from pathlib import Path

settings = {
    "nsteps": "250000",
    "continuation": "yes",
    "pcoupl": "C-rescale",
    "gen-vel": "no",
}
remove = {"gen-temp", "gen-seed"}
lines = []
for line in Path("nvt.mdp").read_text().splitlines():
    key = line.split("=", 1)[0].strip()
    if key in remove:
        continue
    if key in settings:
        line = f"{key} = {settings[key]}"
    lines.append(line)

lines += [
    "pcoupltype = isotropic",
    "tau-p = 5.0",
    "ref-p = 1.0",
    "compressibility = 4.5e-5",
    "refcoord-scaling = com",
]
Path("npt.mdp").write_text("\n".join(lines) + "\n")
PY

    gmx grompp -f npt.mdp \
      -c nvt.gro -t nvt.cpt -r em.gro \
      -p topol.top -o npt.tpr \
      > npt_preparation.log 2>&1

    echo "$system: running 500 ps restrained NPT..."
    gmx mdrun -deffnm npt -ntmpi 1 -ntomp 4 -nb cpu -pme cpu -bonded cpu -update cpu \
      > npt_console.log 2>&1

    python - <<'PY'
from pathlib import Path
import re

text = Path("npt.log").read_text() + Path("npt_console.log").read_text()
if re.search(r"LINCS WARNING|SHAKE did not converge|Fatal error", text, re.I):
    raise SystemExit("STOP: numerical warning/error; inspect NPT logs.")
if not all(Path(p).is_file() for p in ("npt.gro", "npt.cpt", "npt.edr")):
    raise SystemExit("STOP: missing NPT output files.")
print("NPT outputs present; no detected constraint warnings.")
PY

    printf 'Temperature\nPressure\nDensity\nVolume\n0\n' | gmx energy \
      -f npt.edr -b 250 -o npt_properties.xvg \
      > npt_properties_summary.log 2>&1

    grep -E '^(Temperature|Pressure|Density|Volume)[[:space:]]' \
      npt_properties_summary.log
  )
done

echo "Restrained NPT finished. No production MD launched."
