#!/bin/sh
# Hydration free energy of one TIP3P water: alchemical windows (charges off,
# then Lennard-Jones off with a soft core) in a box of 500 waters, NPT 298.15 K,
# each window starting from the end of the previous one. Writes run/fep/*.csv;
# analysis/fep.jl turns them into the free energy (MBAR and TI).
set -e
cd "$(dirname "$0")/.."
EXE=engine/build/cm/verlet; [ -f $EXE.exe ] && EXE=$EXE.exe
PY=.venv/bin/python; [ -f .venv/Scripts/python.exe ] && PY=.venv/Scripts/python.exe
STATES="1:1,0.75:1,0.5:1,0.25:1,0:1,0:0.9,0:0.8,0:0.7,0:0.6,0:0.5,0:0.4,0:0.3,0:0.2,0:0.1,0:0"
PROD=${PROD:-100000}
mkdir -p run/fep data/systems
[ -f data/systems/water500.vsys ] || PYTHONPATH=prep $PY -m verlet_prep water 500 --out data/systems/water500.vsys
COMMON="--platform cuda --temperature 298.15 --pressure 1 --solute-molecule 250 --states $STATES"
$EXE run data/systems/water500.vsys --platform cuda --minimize 500 --temperature 298.15 --pressure 1 --steps 50000 --report 10000 --out run/fep/start.pos 2> run/fep/start.log
prev=run/fep/start.pos
for k in $(seq 0 14); do
  $EXE fep data/systems/water500.vsys $COMMON --state $k --positions $prev --equilibrate 10000 --steps $PROD \
       --sample-every 500 --report 50000 --fep-out run/fep/state$k.csv --out run/fep/state$k.pos --seed $((k + 1)) 2> run/fep/state$k.log
  prev=run/fep/state$k.pos
done
echo "all windows done"
