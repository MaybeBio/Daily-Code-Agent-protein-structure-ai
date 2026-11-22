#!/usr/bin/env bash
#SBATCH --job-name=boltz-full60-bf16
#SBATCH --nodes=4
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=32
#SBATCH --gpus-per-node=8
#SBATCH --mem=1800G
#SBATCH --time=72:00:00
#SBATCH --no-requeue

set -euo pipefail

: "${FULL60_PYTHON:?Set FULL60_PYTHON to the qualified environment interpreter}"
: "${FULL60_RELEASE:?Set FULL60_RELEASE to the shared release directory}"
: "${SLURM_JOB_ID:?Submit explicitly through Slurm}"
RELEASE="$(realpath -- "$FULL60_RELEASE")"
RUN="$(realpath -- "${1:?Provide the fresh prepared run directory}")"
EXPECTED="${2:?Provide the exact prepared binding SHA256}"
CONTROL="$RELEASE/repro/full60_bf16.py"
[[ "$SLURM_JOB_NUM_NODES" == 4 ]]
[[ "${SLURM_RESTART_COUNT:-0}" == 0 ]]
mkdir -- "$RUN/admission" "$RUN/execution"
MASTER="$(scontrol show hostnames "$SLURM_JOB_NODELIST")"
MASTER="${MASTER%%$'\n'*}"

srun --kill-on-bad-exit=1 --ntasks=4 --ntasks-per-node=1 \
    "$FULL60_PYTHON" "$CONTROL" node-preflight --run "$RUN" --expected-sha "$EXPECTED"
"$FULL60_PYTHON" "$CONTROL" node-gate --run "$RUN" --expected-sha "$EXPECTED"
srun --kill-on-bad-exit=1 --ntasks=4 --ntasks-per-node=1 \
    "$FULL60_PYTHON" "$CONTROL" launch-node --phase gpu-preflight \
    --master "$MASTER" --run "$RUN" --expected-sha "$EXPECTED"
"$FULL60_PYTHON" "$CONTROL" gpu-gate --run "$RUN" --expected-sha "$EXPECTED"
srun --kill-on-bad-exit=1 --ntasks=4 --ntasks-per-node=1 \
    "$FULL60_PYTHON" "$CONTROL" launch-node --phase inference \
    --master "$MASTER" --run "$RUN" --expected-sha "$EXPECTED"
"$FULL60_PYTHON" "$CONTROL" postflight --run "$RUN" --expected-sha "$EXPECTED"