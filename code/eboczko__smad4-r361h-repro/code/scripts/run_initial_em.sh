#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
project="$PWD"

for system in 03_wt 04_R361H; do
  run="$project/$system/initial_em"
  mkdir "$run"
  cp -R "$project/$system/assembly/." "$run/"

  (
    cd "$run"

    # This temporary input is used only to place ions, never to run dynamics.
    cat > ions.mdp <<'EOF'
integrator = steep
nsteps = 0
cutoff-scheme = Verlet
nstlist = 1
rlist = 1.2
coulombtype = Cut-off
rcoulomb = 1.2
vdwtype = Cut-off
rvdw = 1.2
pbc = xyz
constraints = none
EOF

    cat > em.mdp <<'EOF'
integrator = steep
emtol = 1000
emstep = 0.001
nsteps = 50000
define = -DPOSRES
constraints = none
cutoff-scheme = Verlet
nstlist = 1
rlist = 1.2
coulombtype = PME
rcoulomb = 1.2
vdwtype = Cut-off
vdw-modifier = Force-switch
rvdw-switch = 1.0
rvdw = 1.2
DispCorr = no
pbc = xyz
nstenergy = 100
nstlog = 100
EOF

    gmx editconf -f complex.pdb -o boxed.gro \
      -bt cubic -c -d 1.5 > box.log 2>&1

    gmx solvate -cp boxed.gro -cs spc216.gro \
      -p topol.top -o solvated.gro > solvate.log 2>&1

    gmx grompp -f ions.mdp -c solvated.gro \
      -p topol.top -o ions.tpr > ions_preparation.log 2>&1

    printf 'SOL\n' | gmx genion \
      -s ions.tpr -o solv_ions.gro -p topol.top \
      -pname NA -nname CL -neutral -conc 0.15 \
      -seed 20260910 > ion_placement.log 2>&1

    gmx grompp -f em.mdp \
      -c solv_ions.gro -r solv_ions.gro \
      -p topol.top -pp processed_em.top \
      -o em.tpr > em_preparation.log 2>&1

    echo "$system: running restrained minimization..."
    gmx mdrun -deffnm em -ntmpi 1 -ntomp 4 -nb cpu -pme cpu \
      > em_console.log 2>&1

    python - <<'PY'
from pathlib import Path
import re
import math

text = Path("em.log").read_text()
matches = re.findall(r"Maximum force\s*=\s*([+\-\d.eE]+)", text)
if not matches:
    raise SystemExit("STOP: no final maximum force found; inspect em.log")
force = float(matches[-1])
print("Final maximum force:", force, "kJ/mol/nm")
if not math.isfinite(force) or force >= 1000:
    raise SystemExit("STOP: minimization did not meet the requested force threshold.")
if not Path("em.gro").is_file():
    raise SystemExit("STOP: missing minimized coordinates.")
print("Force threshold met. Structural checks still required before equilibration.")
PY
  )
done

echo "Both restrained minimizations finished. No MD equilibration was launched."
