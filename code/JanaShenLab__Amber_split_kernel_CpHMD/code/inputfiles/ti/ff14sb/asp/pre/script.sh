#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Top-level Amber24 CpHMD peptide system builder.
###############################################################################

# ff="ff19sb"
 ff="ff14sb"

case "$ff" in
    ff19sb|ff19)
        ff="ff19sb"
        ff_dir="ff19"
        ;;
    ff14sb|ff14)
        ff="ff14sb"
        ff_dir="ff14"
        ;;
    *)
        echo "Error: ff must be ff19sb or ff14sb."
        exit 1
        ;;
esac

scripts="/home/wayyne/cphmd/amber24/${ff_dir}/ti/amber_scripts"

pep="gdg"
cushion="18.005568"
boxtype="octahedral"
boxedge=""
capped="1"

sod="1"
cla="0"
conc=""

titr="0"

###############################################################################

seq_up="$(printf "%s" "$pep" | tr '[:lower:]' '[:upper:]')"

if [[ "$capped" -eq 1 ]]; then
    bash "${scripts}/genpep_amber.sh" \
        --pep "$pep" \
        --ff "$ff" \
        --capped

    inname="capped_${seq_up}"
else
    bash "${scripts}/genpep_amber.sh" \
        --pep "$pep" \
        --ff "$ff" \
        --uncapped

    inname="zwitter_${seq_up}"
fi

args=(
    --in "$inname"
    --ff "$ff"
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
