#!/bin/sh
# Speed of Verlet and OpenMM on the same system (our parameters), the same
# settings (2 fs, LangevinMiddle 1/ps, PME 5e-4, cutoff 0.9 nm, rigid water)
# and the same GPU. Writes results/speed_<system>.json.
#   eval/benchmark.sh data/systems/water2180.vsys [STEPS]
set -e
cd "$(dirname "$0")/.."
SYS=$1; STEPS=${2:-10000}
NAME=$(basename "$SYS" .vsys)
EXE=engine/build/cm/verlet; [ -f $EXE.exe ] && EXE=$EXE.exe
PY=.venv/bin/python; [ -f .venv/Scripts/python.exe ] && PY=.venv/Scripts/python.exe
mkdir -p results
OURS=$($EXE run "$SYS" --platform cuda --minimize 500 --equilibrate 2000 --steps "$STEPS" --report "$STEPS" 2>/dev/null | tail -1)
THEIRS=$($PY eval/openmm_run.py "$SYS" --equilibrate 2000 --steps "$STEPS" --report "$STEPS" | tail -1)
GPU=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)
printf '{"system": "%s", "gpu": "%s", "verlet": %s, "openmm": %s}\n' "$NAME" "$GPU" "$OURS" "$THEIRS" > results/speed_$NAME.json
cat results/speed_$NAME.json
