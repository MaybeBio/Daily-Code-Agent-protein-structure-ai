#!/usr/bin/env bash
# E16's stages on the GH200 the native-unit study runs on, each in its own container through in_container.sh, beside
# whatever else the machine runs. From tree/projects/representation/plm_interpretability of a shipped run:
#   ws remote run <machine> plm_interpretability --detach --credential HF_TOKEN $SHIP -- bash scripts/e16_lanes.sh check TEST...
#   ws remote run <machine> plm_interpretability --detach --credential HF_TOKEN $SHIP -- bash scripts/e16_lanes.sh stage STAGE [ARGUMENT...]
#   ws remote run <machine> plm_interpretability --detach --credential HF_TOKEN $SHIP -- bash scripts/e16_lanes.sh hub FOLDER...
# The chain lives here and not on the command line because ws.cmd reads `<`, `>` and `&&` in an argument as its own.
set -uo pipefail
preregistration=../../../experiments/representation/plm_interpretability/2026-11-06_esmc_native_units/preregistration.yaml
readings=../../../experiments/representation/plm_interpretability/2026-11-06_esmc_native_units/scripts/e16_readings.py
repo=Synthyra/esmc_native_units_20261106

case "${1:-}" in
    check)
        # check TEST...: the named test files in the image.
        export NAME=tap-probing-e16-check CPUS=16 MEMORY=64g
        bash scripts/in_container.sh python -m pytest "${@:2}" -q -p no:cacheprovider
        echo "CHECK exit $? $(date -u +%T)"
        ;;
    stage)
        # stage STAGE [ARGUMENT...]: one stage of units_atlas.py, as `stage prune-static --pilot`. Two runs of one stage
        # side by side need a NAME each: `env NAME=tap-probing-e16-b bash scripts/e16_lanes.sh stage ...`.
        export NAME="${NAME:-tap-probing-e16-$2}" CPUS="${CPUS:-16}" MEMORY="${MEMORY:-128g}"
        bash scripts/in_container.sh python scripts/units_atlas.py "${@:2}" --root /units --preregistration "$preregistration"
        echo "STAGE ${*:2} exit $? $(date -u +%T)"
        ;;
    control)
        # control: E16b's control, ESMC-300 itself distilled from ESMC-600. Three probes of 300 steps choose the peak
        # rate by validation loss, then the full run at that rate, one after another beside the resized model's run.
        export NAME=tap-probing-e16-control CPUS="${CPUS:-16}" MEMORY="${MEMORY:-128g}"
        units="${UNITS:-$HOME/units_run}"
        for rate in 3e-5 1e-4 3e-4; do
            WANDB_MODE=disabled bash scripts/in_container.sh python scripts/units_atlas.py prune-heal --control --steps 300 \
                --learning-rate "$rate" --run-name "probe_control_lr$rate" --root /units --preregistration "$preregistration"
            echo "PROBE $rate exit $? $(date -u +%T)"
        done
        # Host python3 only reads the receipts the containers wrote.
        best=$(python3 -c 'import json, sys
rates = sys.argv[2:]
losses = {rate: json.load(open(f"{sys.argv[1]}/prune_heal/probe_control_lr{rate}/receipt.json"))["kept_validation_loss"] for rate in rates}
print(min(rates, key=losses.get))' "$units" 3e-5 1e-4 3e-4)
        echo "CONTROL_RATE $best $(date -u +%T)"
        bash scripts/in_container.sh python scripts/units_atlas.py prune-heal --control --learning-rate "$best" \
            --root /units --preregistration "$preregistration"
        echo "CONTROL exit $? $(date -u +%T)"
        ;;
    finish)
        # finish: once E16b's run has left its receipt, the probes again, which add the healed model; the weights of the
        # short probes and of the pilot deleted, with any probe folder that has no receipt; the readings; the Hub.
        units="${UNITS:-$HOME/units_run}"
        until [ -f "$units/prune_heal/pruned/receipt.json" ]; do sleep 20; done
        echo "HEALED $(date -u +%T)"
        NAME=tap-probing-e16-probes CPUS=16 MEMORY=128g bash scripts/in_container.sh python scripts/units_atlas.py prune-probes \
            --root /units --preregistration "$preregistration"
        echo "PROBES exit $? $(date -u +%T)"
        NAME=tap-probing-e16-clean CPUS=2 MEMORY=8g bash scripts/in_container.sh bash -c \
            'rm -f /units/prune_heal/probe_*/best.safetensors /units/pilots/prune_heal/*/best.safetensors
             for run in /units/prune_heal/probe_*/; do [ -f "$run/receipt.json" ] || rm -rf "$run"; done
             du -sh /units/prune_heal /units/pilots/prune_heal'
        echo "CLEAN exit $? $(date -u +%T)"
        NAME=tap-probing-e16-readings CPUS=8 MEMORY=64g bash scripts/in_container.sh python "$readings" --root /units
        echo "READINGS exit $? $(date -u +%T)"
        for folder in e16 prune_static prune_sequential prune_heal prune_probes pilots; do
            NAME=tap-probing-e16-hub CPUS=8 MEMORY=64g bash scripts/in_container.sh python scripts/units_hub.py --root /units \
                --repo "$repo" --path "$folder"
            echo "HUB $folder exit $? $(date -u +%T)"
        done
        echo FINISH_DONE
        ;;
    readings)
        # readings FOLDER...: E16's readings, then RUN/e16 and each named folder to the run's private Hub dataset.
        export NAME=tap-probing-e16-readings CPUS=8 MEMORY=64g
        bash scripts/in_container.sh python "$readings" --root /units
        echo "READINGS exit $? $(date -u +%T)"
        for folder in e16 "${@:2}"; do
            bash scripts/in_container.sh python scripts/units_hub.py --root /units --repo "$repo" --path "$folder"
            echo "HUB $folder exit $? $(date -u +%T)"
        done
        echo READINGS_DONE
        ;;
    hub)
        # hub FOLDER...: each named folder of the run to its private Hub dataset.
        export NAME=tap-probing-e16-hub CPUS=8 MEMORY=64g
        for folder in "${@:2}"; do
            bash scripts/in_container.sh python scripts/units_hub.py --root /units --repo "$repo" --path "$folder"
            echo "HUB $folder exit $? $(date -u +%T)"
        done
        echo HUB_DONE
        ;;
    *)
        echo "usage: e16_lanes.sh check TEST... | stage STAGE [ARGUMENT...] | control | finish | readings FOLDER... | hub FOLDER..." >&2
        exit 2
        ;;
esac
