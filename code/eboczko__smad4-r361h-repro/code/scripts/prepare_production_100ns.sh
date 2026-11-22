#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
project="$PWD"
trap 'echo "STOP: command failed at line $LINENO. Inspect the relevant log."' ERR

# Prepare both production inputs before starting either simulation.
for system in 03_wt 04_R361H; do
  source="$project/$system/initial_em"
  destination="$project/$system/production"

  test -s "$source/npt_free.gro"
  test -s "$source/npt_free.cpt"
  mkdir "$destination"

  cp -R "$source/charmm36-sp2local.ff" "$destination/"
  cp "$source/residuetypes.dat" "$source/topol.top" "$destination/"
  for chain in A B C; do
    cp "$source/chain_${chain}.itp" "$source/posre_${chain}.itp" "$destination/"
  done
  cp "$source/npt_free.gro" "$destination/start.gro"
  cp "$source/npt_free.cpt" "$destination/start.cpt"
  cp "$source/npt_free.mdp" "$destination/equilibration_settings.mdp"

  (
    cd "$destination"

    python - <<'PY'
from pathlib import Path

settings = {
    "integrator": "md",
    "dt": "0.002",
    "nsteps": "50000000",
    "tinit": "0",
    "init-step": "0",
    "continuation": "yes",
    "gen-vel": "no",
    "nstxout": "0",
    "nstvout": "0",
    "nstfout": "0",
    "nstxout-compressed": "5000",
    "compressed-x-precision": "1000",
    "nstenergy": "5000",
    "nstlog": "5000",
}
remove = {"define", "refcoord-scaling", "gen-temp", "gen-seed"}
lines = []
for line in Path("equilibration_settings.mdp").read_text().splitlines():
    key = line.split("=", 1)[0].strip()
    if key in remove or key in settings:
        continue
    lines.append(line)
lines += [f"{key} = {value}" for key, value in settings.items()]
Path("md_100ns.mdp").write_text("\n".join(lines) + "\n")
PY

    gmx grompp \
      -f md_100ns.mdp \
      -c start.gro -t start.cpt \
      -p topol.top -pp processed_production.top \
      -o md_100ns.tpr \
      > production_preparation.log 2>&1

    python - <<'PY'
from pathlib import Path
import re

text = Path("processed_production.top").read_text()
if re.search(r"^\s*\[\s*position_restraints\s*\]", text, re.M):
    raise SystemExit("STOP: unexpected position restraints.")
print("Production input prepared: 100 ns, no position restraints.", flush=True)
PY
  )
done


echo "Both SMAD3 production inputs prepared. No MD launched."
