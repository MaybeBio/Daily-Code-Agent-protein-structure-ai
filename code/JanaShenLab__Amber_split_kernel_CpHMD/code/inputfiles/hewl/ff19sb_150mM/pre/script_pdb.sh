#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Top-level Amber24/ff19SB CpHMD PDB system builder.
###############################################################################

scripts="/home/wayyne/cphmd/amber24/ff19/ti/amber_scripts"

###############################################################################
# STRUCTURE INPUT
###############################################################################

# Set exactly one:
pdbid="2lzt"          # Fetch this PDB ID from RCSB
pdbfile=""            # Existing PDB, e.g. ./1ubq_original.pdb

chain="A"             # One protein chain
cushion="22.8875"      # LEaP water cushion in Angstrom
boxtype="octahedral"  # cubic or octahedral
boxedge=""            # Optional requested final box edge in Angstrom
capped="1"            # 1 = ACE/NHE; 0 = no caps

sod="50"               # Exact Na+ count when conc is blank
cla="58"               # Exact Cl- count when conc is blank
conc=""                # Salt concentration in mM; blank uses sod/cla

titr="0"              # -1 acidic co-ions; 0 none; 1 basic co-ions

###############################################################################

die() {
    echo "Error: $*" >&2
    exit 1
}

sanitize_num_tag() {
    local value="$1"

    value="$(printf "%s" "$value" | sed -E 's/\.0+$//')"
    value="${value//./p}"

    printf "%s" "$value"
}

format_mM_tag() {
    local value="$1"

    awk -v mm="$value" '
        BEGIN {
            if (mm == int(mm)) {
                printf "%dmM", mm
            } else {
                s = sprintf("%.3f", mm)
                sub(/0+$/, "", s)
                sub(/\.$/, "", s)
                gsub(/\./, "p", s)
                printf "%smM", s
            }
        }'
}

normalize_box_type() {
    case "$(printf "%s" "$1" | tr '[:upper:]' '[:lower:]')" in
        cubic|cube|cub|1)
            printf "cubic"
            ;;
        octahedral|octa|oct|truncated_octahedral|truncated-octahedral|2)
            printf "octahedral"
            ;;
        *)
            die "boxtype must be cubic or octahedral"
            ;;
    esac
}

[[ -d "$scripts" ]] || die "script directory not found: $scripts"

for required_script in \
    get_pdb.sh \
    prep_pdb_amber.sh \
    gen_pdb_system_amber.sh \
    solvate_sys_amber.sh
do
    [[ -f "${scripts}/${required_script}" ]] ||
        die "required script not found: ${scripts}/${required_script}"
done

if [[ -n "$pdbid" && -n "$pdbfile" ]]; then
    die "set either pdbid or pdbfile, not both"
fi

if [[ -z "$pdbid" && -z "$pdbfile" ]]; then
    die "either pdbid or pdbfile must be set"
fi

[[ "$chain" =~ ^[[:alnum:]]$ ]] ||
    die "chain must contain exactly one alphanumeric character"

[[ "$capped" == "0" || "$capped" == "1" ]] ||
    die "capped must be 0 or 1"

[[ "$titr" == "-1" || "$titr" == "0" || "$titr" == "1" ]] ||
    die "titr must be -1, 0, or 1"

if ! [[ "$cushion" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    die "cushion must be a non-negative number"
fi

if [[ -n "$boxedge" ]] &&
   ! [[ "$boxedge" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    die "boxedge must be a positive number or blank"
fi

if [[ -n "$conc" ]]; then
    if ! [[ "$conc" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
        die "conc must be a non-negative concentration in mM"
    fi
else
    [[ "$sod" =~ ^[0-9]+$ ]] ||
        die "sod must be a non-negative integer"

    [[ "$cla" =~ ^[0-9]+$ ]] ||
        die "cla must be a non-negative integer"
fi

chain_select="$(printf "%s" "$chain" | tr '[:lower:]' '[:upper:]')"
chain_tag="$(printf "%s" "$chain" | tr '[:upper:]' '[:lower:]')"
boxtype="$(normalize_box_type "$boxtype")"

###############################################################################
# RESOLVE INPUT PDB
###############################################################################

if [[ -n "$pdbid" ]]; then
    pdbid="$(printf "%s" "$pdbid" | tr '[:upper:]' '[:lower:]')"

    [[ "$pdbid" =~ ^[[:alnum:]]{4}$ ]] ||
        die "pdbid must contain exactly four alphanumeric characters"

    pdb_original="${pdbid}_original.pdb"

    bash "${scripts}/get_pdb.sh" \
        --pdbid "$pdbid" \
        --out "$pdb_original"
else
    [[ -f "$pdbfile" ]] || die "PDB file not found: $pdbfile"
    [[ -s "$pdbfile" ]] || die "PDB file is empty: $pdbfile"

    pdb_original="$pdbfile"
    pdb_basename="$(basename -- "$pdbfile")"

    if [[ "$pdb_basename" =~ ^([[:alnum:]]{4})([_\.-]|$) ]]; then
        pdbid="$(
            printf "%s" "${BASH_REMATCH[1]}" |
                tr '[:upper:]' '[:lower:]'
        )"
    else
        die \
            "local PDB filename must begin with its four-character PDB ID: " \
            "$pdb_basename"
    fi
fi

###############################################################################
# CLEAN AND MAP THE SELECTED CHAIN
###############################################################################

pdb_clean="${pdbid}_${chain_tag}_amber_clean.pdb"
disulfides="${pdbid}_${chain_tag}_amber_disulfides.dat"
prep_report="${pdbid}_${chain_tag}_amber_prep_report.txt"

bash "${scripts}/prep_pdb_amber.sh" \
    --in "$pdb_original" \
    --pdbid "$pdbid" \
    --chain "$chain_select" \
    --out "$pdb_clean" \
    --disu-out "$disulfides" \
    --report "$prep_report"

###############################################################################
# BUILD THE DRY ff19SB SYSTEM
###############################################################################

if [[ "$capped" == "1" ]]; then
    termini="capped"
    prepared="${termini}_${pdbid}_${chain_tag}"

    bash "${scripts}/gen_pdb_system_amber.sh" \
        --in "$pdb_clean" \
        --out "$prepared" \
        --disu "$disulfides" \
        --capped
else
    termini="uncapped"
    prepared="${termini}_${pdbid}_${chain_tag}"

    bash "${scripts}/gen_pdb_system_amber.sh" \
        --in "$pdb_clean" \
        --out "$prepared" \
        --disu "$disulfides" \
        --uncapped
fi

###############################################################################
# SOLVATE AND ADD IONS WITH THE EXISTING AMBER SOLVATION SCRIPT
###############################################################################

solvate_args=(
    --in "$prepared"
    --box "$boxtype"
    --cushion "$cushion"
    --titr "$titr"
)

if [[ -n "$boxedge" ]]; then
    solvate_args+=(--box-edge "$boxedge")
fi

if [[ -n "$conc" ]]; then
    solvate_args+=(--conc "$conc")
else
    solvate_args+=(--sod "$sod")
    solvate_args+=(--cla "$cla")
fi

bash "${scripts}/solvate_sys_amber.sh" "${solvate_args[@]}"

###############################################################################
# RESOLVE THE FINAL OUTPUT PREFIX
###############################################################################

if [[ -n "$conc" ]]; then
    ion_tag="$(format_mM_tag "$conc")"
else
    ion_tag=""

    if [[ "$sod" -gt 0 ]]; then
        ion_tag="${sod}xsod"
    fi

    if [[ "$cla" -gt 0 ]]; then
        if [[ -n "$ion_tag" ]]; then
            ion_tag="${ion_tag}_${cla}xcla"
        else
            ion_tag="${cla}xcla"
        fi
    fi

    if [[ -z "$ion_tag" ]]; then
        ion_tag="0ions"
    fi
fi

if [[ -n "$boxedge" ]]; then
    edge_tag="$(sanitize_num_tag "$boxedge")"
    system="${prepared}_solv_${edge_tag}Aedge_${boxtype}_${ion_tag}"
else
    cushion_tag="$(sanitize_num_tag "$cushion")"
    system="${prepared}_solv_${cushion_tag}A_${boxtype}_${ion_tag}"
fi

prmtop="${system}.prmtop"
inpcrd="${system}.inpcrd"
final_pdb="${system}.pdb"

[[ -s "$prmtop" ]] ||
    die "final Amber topology not found or empty: $prmtop"

[[ -s "$inpcrd" ]] ||
    die "final Amber coordinates not found or empty: $inpcrd"

[[ -s "$final_pdb" ]] ||
    die "final Amber PDB not found or empty: $final_pdb"

###############################################################################
# REPORT FINAL COMPOSITION
###############################################################################

awk -v sysname="$system" '
/^%FLAG RESIDUE_LABEL/ {
    reading = 1
    next
}

/^%FLAG/ && reading {
    exit
}

reading && /^%FORMAT/ {
    next
}

reading {
    for (i = 1; i <= length($0); i += 4) {
        residue = substr($0, i, 4)
        gsub(/[[:space:]]/, "", residue)
        residue = toupper(residue)

        if (residue == "WAT") {
            waters++
        } else if (residue == "NA+" || residue == "NA" || residue == "SOD") {
            sodium++
        } else if (residue == "CL-" || residue == "CL" || residue == "CLA") {
            chloride++
        }
    }
}

END {
    printf "\n"
    printf "============================================================\n"
    printf "Final Amber ff19SB System Composition\n"
    printf "System         : %s\n", sysname
    printf "Waters         : %d\n", waters + 0
    printf "Sodium ions    : %d\n", sodium + 0
    printf "Chloride ions  : %d\n", chloride + 0
    printf "Total ions     : %d\n", sodium + chloride
    printf "============================================================\n"
}
' "$prmtop"
echo
echo "Final topology    : $prmtop"
echo "Final coordinates : $inpcrd"
echo "Final PDB         : $final_pdb"
echo "Preparation report: $prep_report"
