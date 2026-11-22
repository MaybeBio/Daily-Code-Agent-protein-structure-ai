#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Top-level Amber24/ff19SB CpHMD peptide system builder.
###############################################################################

scripts="/home/wayyne/cphmd/amber24/ff19/ti/amber_scripts"

pep="ghg"
cushion="17.675"
boxtype="octahedral"
boxedge=""
capped="1"

sod="0"
cla="0"
conc=""

titr="0"

###############################################################################

seq_up="$(printf "%s" "$pep" | tr '[:lower:]' '[:upper:]')"

if [[ "$capped" -eq 1 ]]; then
    bash "${scripts}/genpep_amber.sh" \
        --pep "$pep" \
        --capped
    inname="capped_${seq_up}"
else
    bash "${scripts}/genpep_amber.sh" \
        --pep "$pep" \
        --uncapped
    inname="zwitter_${seq_up}"
fi

args=(
    --in "$inname"
    --box "$boxtype"
    --cushion "$cushion"
    --titr "$titr"
)

if [[ "$boxedge" != "" ]]; then
    args+=(--box-edge "$boxedge")
fi

if [[ "$conc" == "" ]]; then
    args+=(--sod "$sod")
    args+=(--cla "$cla")
else
    args+=(--conc "$conc")
fi

bash "${scripts}/solvate_sys_amber.sh" "${args[@]}"
