#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
project="$PWD"

for system in 03_wt 04_R361H; do
  (
    cd "$project/$system/initial_em"

    if [ -e npt_weak.tpr ] || [ -e npt_weak.log ]; then
      echo "STOP: existing reduced-restraint run in $PWD"
      exit 1
    fi

    python - <<'PY'
from pathlib import Path

for chain in "ABC":
    source = Path(f"posre_{chain}.itp")
    lines = []
    for line in source.read_text().splitlines():
        fields = line.split()
        if fields and fields[0].isdigit():
            assert len(fields) >= 5
            line = f"{fields[0]} {fields[1]} 100 100 100"
        lines.append(line)
    Path(f"posre_{chain}_weak.itp").write_text("\n".join(lines) + "\n")

    text = Path(f"chain_{chain}.itp").read_text()
    old = f'"posre_{chain}.itp"'
    assert old in text
    Path(f"chain_{chain}_weak.itp").write_text(
        text.replace(old, f'"posre_{chain}_weak.itp"')
    )

text = Path("topol.top").read_text()
for chain in "ABC":
    old = f'"chain_{chain}.itp"'
    assert old in text
    text = text.replace(old, f'"chain_{chain}_weak.itp"')
Path("topol_weak.top").write_text(text)

# Keep the same NPT settings; checkpoint supplies velocities.
Path("npt_weak.mdp").write_text(Path("npt.mdp").read_text())
PY

    gmx grompp -f npt_weak.mdp \
      -c npt.gro -t npt.cpt -r em.gro \
      -p topol_weak.top -o npt_weak.tpr \
      > npt_weak_preparation.log 2>&1

    echo "$system: running 500 ps with reduced restraints..."
    gmx mdrun -deffnm npt_weak -ntmpi 1 -ntomp 8 -nb gpu -pme gpu -pin on \
      > npt_weak_console.log 2>&1

    python - <<'PY'
from pathlib import Path
import re

text = Path("npt_weak.log").read_text() + Path("npt_weak_console.log").read_text()
if re.search(r"LINCS WARNING|SHAKE did not converge|Fatal error", text, re.I):
    raise SystemExit("STOP: numerical warning/error; inspect logs.")
if not all(Path(p).is_file() for p in (
    "npt_weak.gro", "npt_weak.cpt", "npt_weak.edr"
)):
    raise SystemExit("STOP: missing run outputs.")
print("Reduced-restraint NPT completed without detected constraint warnings.")
PY

    printf 'Temperature\nPressure\nDensity\nVolume\n0\n' | gmx energy \
      -f npt_weak.edr -b 250 -o npt_weak_properties.xvg \
      > npt_weak_properties_summary.log 2>&1

    grep -E '^(Temperature|Pressure|Density|Volume)[[:space:]]' \
      npt_weak_properties_summary.log
  )
done

echo "Reduced-restraint stage finished. No production MD launched."
