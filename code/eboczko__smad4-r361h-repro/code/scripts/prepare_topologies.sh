#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."

prepare_chain() {
    local input="$1" destination="$2"
    mkdir "$destination"
    if gmx pdb2gmx \
        -f "$input" \
        -o "$destination/processed.pdb" \
        -p "$destination/topol.top" \
        -i "$destination/posre.itp" \
        -ff charmm36-sp2local -water tip3p -ignh \
        > "$destination/preparation.log" 2>&1
    then
        echo "SUCCESS: $destination"
        grep -E 'Start terminus|End terminus|Total charge' \
            "$destination/preparation.log" || true
    else
        tail -50 "$destination/preparation.log"
        exit 1
    fi
}

prepare_chain 02_prepared/WT/gromacs_inputs/smad3A.pdb 03_wt/topology_A
prepare_chain 02_prepared/WT/gromacs_inputs/smad3C.pdb 03_wt/topology_C
prepare_chain 02_prepared/WT/gromacs_inputs/smad4B_WT.pdb 03_wt/topology_B
prepare_chain 02_prepared/R361H/gromacs_inputs/smad4B_R361H.pdb 04_R361H/topology_B
