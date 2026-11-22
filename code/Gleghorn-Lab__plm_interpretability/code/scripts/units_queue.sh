#!/usr/bin/env bash
# Run the native-unit study's steps one after another on the machine, each in its own container through
# in_container.sh, so the machine keeps working while the laptop that launched it sleeps. From
# tree/projects/representation/plm_interpretability of a shipped run:
#   ws remote run <machine> plm_interpretability --detach --credential HF_TOKEN $SHIP -- bash scripts/units_queue.sh [<step>...]
# The steps wait in UNITS/queue.steps, one a line; arguments given here are appended to it, and lines may be added,
# removed or reordered there while the queue runs, since it takes the first line only when a step ends. A step is a
# units_atlas.py stage and its arguments joined by commas, such as `pass,--experiment,e2,--pilot`, run with --root /units
# and the shipped preregistration, or `hub,` and units_hub.py's arguments, run with --root /units. The queue stops at the
# first step that fails, after a pilot whose projection passes its budget or that wrote no receipt, and before any step
# once the disk holding UNITS is CEILING percent used (default 85, the GH200 suite's ceiling); the steps not yet taken
# stay in the file. It appends each step's start, end and status, and each pilot's projection, to UNITS/queue.log
# (UNITS as in in_container.sh, default ~/units_run). A second queue for CPU steps, such as Hub uploads, runs beside the
# first under its own QUEUE name (files UNITS/<QUEUE>.steps and .log) and container NAME, with smaller CPUS and MEMORY.
set -euo pipefail
units="${UNITS:-$HOME/units_run}"
ceiling="${CEILING:-85}"
queue="${QUEUE:-queue}"
preregistration=../../../experiments/representation/plm_interpretability/2026-11-06_esmc_native_units/preregistration.yaml
mkdir -p "$units"
steps="$units/$queue.steps"
log="$units/$queue.log"
marker="$units/.${queue}_marker"
touch "$steps"
for step in "$@"; do
    echo "$step" >> "$steps"
done
note() { echo "$(date -u +%FT%TZ) $*" >> "$log"; }
note "queue from $(cd ../../../.. && pwd), $(grep -c . "$steps" || true) steps waiting"
while step=$(grep -m1 . "$steps"); do
    # The exact share used, since df's own percentage rounds up.
    used=$(df -B1 --output=used,size "$units" | tail -1 | awk '{ printf "%.2f", 100 * $1 / $2 }')
    if awk -v used="$used" -v ceiling="$ceiling" 'BEGIN { exit !(used >= ceiling) }'; then
        note "queue stopped before $step: disk ${used}% used, at the ${ceiling}% ceiling"
        exit 4
    fi
    # Take the first non-empty line off the file, keeping the rest as they stand now.
    awk -v taken="$step" 'done || $0 != taken { print; next } { done = 1 }' "$steps" > "$steps.next"
    mv "$steps.next" "$steps"
    IFS=, read -r -a arguments <<< "$step"
    touch "$marker"
    note "start ${arguments[*]}"
    status=0
    if [[ "${arguments[0]}" == hub ]]; then
        bash scripts/in_container.sh python scripts/units_hub.py "${arguments[@]:1}" --root /units || status=$?
    else
        bash scripts/in_container.sh python scripts/units_atlas.py "${arguments[@]}" --root /units \
            --preregistration "$preregistration" || status=$?
    fi
    note "end ${arguments[*]}: status $status"
    if (( status != 0 )); then
        note "queue stopped: ${arguments[*]} failed"
        exit "$status"
    fi
    if [[ " ${arguments[*]} " == *" --pilot "* ]]; then
        # Every stage's pilot writes under UNITS/pilots; the rest of UNITS holds folders the containers' root made
        # unreadable to this user (MMseqs2's temporary search folders), which stopped a search of all of it at 01:42
        # UTC on 2026-11-07.
        receipt=$(find "$units/pilots" -name pilot.json -newer "$marker" -print -quit)
        if [[ -z "$receipt" ]]; then
            note "queue stopped: the pilot of ${arguments[*]} wrote no pilot.json"
            exit 3
        fi
        # Host python3 only reads the receipt the container wrote.
        if ! verdict=$(python3 -c 'import json, sys
report = json.load(open(sys.argv[1]))
projected, budget, findings = report["projected_seconds"], report["budget_seconds"], report["findings"]
print("projected %s s against a budget of %s s; findings: %s" % (projected, budget, findings))
sys.exit(0 if projected is not None and budget is not None and projected <= budget else 3)' "$receipt"); then
            note "queue stopped: pilot over budget, $verdict"
            exit 3
        fi
        note "pilot $receipt: $verdict"
    fi
done
note "queue done"
