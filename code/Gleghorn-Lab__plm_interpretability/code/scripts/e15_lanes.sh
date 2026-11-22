#!/usr/bin/env bash
# E15's stages on its own GH200, in two lanes side by side, each stage in its own container through in_container.sh.
# From tree/projects/representation/plm_interpretability of a shipped run:
#   ws remote run <machine> plm_interpretability --detach --credential HF_TOKEN $SHIP -- bash scripts/e15_lanes.sh lane2
#   ws remote run <machine> plm_interpretability --detach --credential HF_TOKEN $SHIP -- bash scripts/e15_lanes.sh lane1 HOURS_ATTRIBUTION HOURS_TESTS
#   ws remote run <machine> plm_interpretability --detach --credential HF_TOKEN $SHIP -- bash scripts/e15_lanes.sh closeout FOLDER...
# lane1 is E15c after its attribution pilot: the attribution pass, the graph and Leiden, the tests' pilot and the tests.
# lane2 is E15a, then E15b, E15d and E15e, each after its pilot and only when the pilot projects it inside its budget.
# closeout writes E15's readings and sends each named folder of the run to its private Hub dataset.
# The chain lives here and not on the command line because ws.cmd reads `<`, `>` and `&&` in an argument as its own.
set -uo pipefail
preregistration=../../../experiments/representation/plm_interpretability/2026-11-06_esmc_native_units/preregistration.yaml
readings=../../../experiments/representation/plm_interpretability/2026-11-06_esmc_native_units/scripts/e15_readings.py
units="${UNITS:-$HOME/units_run}"
repo=Synthyra/esmc_native_units_20261106

stage() {
    bash scripts/in_container.sh python scripts/units_atlas.py "$@" --root /units --preregistration "$preregistration"
    local status=$?
    echo "STAGE $* exit $status $(date -u +%T)"
    return $status
}

within_budget() {
    # Host python3 only reads the receipt the container wrote.
    python3 -c 'import json, sys
receipt = json.load(open(sys.argv[1]))
print("pilot", sys.argv[1], "projected", receipt["projected_seconds"], "budget", receipt["budget_seconds"])
sys.exit(0 if receipt["projected_seconds"] <= receipt["budget_seconds"] else 3)' "$units/pilots/$1/pilot_receipt.json"
}

hours_until() {
    # The hours from now to a UTC time given as 2026-11-18T04:15, and 0.01 once it has passed.
    python3 -c 'import datetime, sys
end = datetime.datetime.fromisoformat(sys.argv[1]).replace(tzinfo=datetime.timezone.utc)
left = (end - datetime.datetime.now(datetime.timezone.utc)).total_seconds() / 3600
print(f"{max(left, 0.01):.3f}")' "$1"
}

case "${1:-}" in
    lane2)
        export NAME=tap-probing-b CPUS=24 MEMORY=160g
        stage write-sums
        stage sparsify --pilot && within_budget sparsify && stage sparsify
        stage concept-groups --pilot && within_budget concept_groups && stage concept-groups
        stage erasure-levels --pilot && within_budget erasure_levels && stage erasure-levels
        echo LANE2_DONE
        ;;
    lane1)
        stage neuron-attribution --budget-hours "$2" && stage communities && stage community-tests --pilot \
            && stage community-tests --budget-hours "$3"
        echo LANE1_DONE
        ;;
    after)
        # after LOG MARKER STAGE...: once MARKER is in LOG, one more stage in lane 2's container.
        export NAME=tap-probing-b CPUS=24 MEMORY=160g
        until grep -q "$3" "$2" 2>/dev/null; do sleep 15; done
        stage "${@:4}"
        echo AFTER_DONE
        ;;
    lane1b)
        # lane1b HOURS_TESTS CANDIDATES END: the rest of lane 1 in a container of its own, once the attribution pass
        # has written its receipt: the graph and Leiden, the tests' pilot, the tests for HOURS_TESTS, then the tests
        # of CANDIDATES communities a prompt until END (UTC, as 2026-11-18T04:15). It replaces lane1's last three
        # stages when their code changed after lane1 was shipped.
        export NAME=tap-probing-d
        until [ -f "$units/communities/attribution/receipt.json" ]; do sleep 10; done
        echo "ATTRIBUTION_DONE $(date -u +%T)"
        stage communities && stage community-tests --pilot && stage community-tests --budget-hours "$2" \
            && stage community-tests --candidates "$3" --budget-hours "$(hours_until "$4")"
        echo LANE1_DONE
        ;;
    stop)
        # stop CASE: end this script's driver of one case (lane1, after). The stage it is running finishes by itself
        # and none follows. The space after the case keeps `stop lane1` from ending lane1b.
        pkill -f "e15_lanes.sh $2 "
        sleep 2
        pgrep -af "e15_lanes|in_container|docker run"
        echo STOP_DONE
        ;;
    activation)
        # activation END: E15c's second dictionary beside the lanes, from the units of largest activation at the same
        # prompts: the pass, the graph and Leiden, and the tests until END (UTC, as 2026-11-18T04:15).
        export NAME=tap-probing-b CPUS=24 MEMORY=160g
        stage neuron-attribution --dictionary activation && stage communities --dictionary activation \
            && stage community-tests --dictionary activation --budget-hours "$(hours_until "$2")"
        echo ACTIVATION_DONE
        ;;
    one)
        # one NAME STAGE...: one stage in a container of its own name, beside the lanes.
        export NAME="$2" CPUS=16 MEMORY=128g
        stage "${@:3}"
        echo ONE_DONE
        ;;
    check)
        # check TEST...: the named test files in the image, after a change to a stage that the lanes will run.
        export NAME=tap-probing-t CPUS=16 MEMORY=64g
        bash scripts/in_container.sh python -m pytest "${@:2}" -q -p no:cacheprovider
        echo "CHECK exit $? $(date -u +%T)"
        ;;
    closeout)
        export NAME=tap-probing-c CPUS=8 MEMORY=64g
        bash scripts/in_container.sh python "$readings" --root /units
        echo "READINGS exit $? $(date -u +%T)"
        for folder in "${@:2}"; do
            bash scripts/in_container.sh python scripts/units_hub.py --root /units --repo "$repo" --path "$folder"
            echo "HUB $folder exit $? $(date -u +%T)"
        done
        # Then every file of the whole run that the Hub lacks or holds differently, by digest; it sends nothing.
        du -sh "$units"/* 2>/dev/null
        bash scripts/in_container.sh python scripts/units_hub.py --root /units --repo "$repo" --check
        echo "INVENTORY exit $? $(date -u +%T)"
        echo CLOSEOUT_DONE
        ;;
    hub)
        # hub FOLDER...: each named folder of the run to its private Hub dataset, with no readings, beside a lane.
        export NAME=tap-probing-h CPUS=8 MEMORY=64g
        for folder in "${@:2}"; do
            bash scripts/in_container.sh python scripts/units_hub.py --root /units --repo "$repo" --path "$folder"
            echo "HUB $folder exit $? $(date -u +%T)"
        done
        echo HUB_DONE
        ;;
    inventory)
        # inventory: before the machine is given up, the run's size by folder, then every file of the whole run that
        # the Hub lacks or holds differently, by digest. It sends nothing.
        export NAME=tap-probing-i CPUS=16 MEMORY=64g
        du -sh "$units"/* 2>/dev/null
        bash scripts/in_container.sh python scripts/units_hub.py --root /units --repo "$repo" --check
        echo "INVENTORY exit $? $(date -u +%T)"
        echo INVENTORY_DONE
        ;;
    *)
        echo "usage: e15_lanes.sh lane1 HOURS_ATTRIBUTION HOURS_TESTS | lane1b HOURS_TESTS CANDIDATES END | lane2 | activation END | after LOG MARKER STAGE..." \
            "| one NAME STAGE... | stop CASE | closeout FOLDER... | hub FOLDER... | inventory" >&2
        exit 2
        ;;
esac
