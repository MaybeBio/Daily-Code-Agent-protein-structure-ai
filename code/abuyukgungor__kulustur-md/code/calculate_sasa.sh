#!/bin/bash
export LC_ALL=C
# MD Analysis - Solvent Accessible Surface Area (SASA) Calculation
# Usage: ./calculate_sasa.sh <topology> <traj_list> <out_file> [mask]

TOPOLOGY=$1
TRAJ_LIST=$2
OUT_FILE=$3
MASK=${4:-"!@H*"}

# Check arguments
if [ -z "$TOPOLOGY" ] || [ -z "$TRAJ_LIST" ] || [ -z "$OUT_FILE" ]; then
    echo "Error: Missing arguments."
    echo "Usage: $0 <topology_file> <trajectory_list_file> <output_file> [mask]"
    exit 1
fi

# Extract output directory from the out_file path
OUT_DIR=$(dirname "$OUT_FILE")
OUT_BASE=$(basename "$OUT_FILE" .dat)

# Generate cpptraj trajin lines from trajectory list file
TRAJ_TYPE=$(printf '%s' "${TRAJ_TYPE:-md}" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')
TEMP=${TEMPERATURE:-"310.0"}
if [ "$TRAJ_TYPE" != "md" ] && [ "$TRAJ_TYPE" != "remd" ] && [ "$TRAJ_TYPE" != "mix" ]; then
    echo "ERROR: Invalid TRAJ_TYPE '$TRAJ_TYPE'! Must be 'md', 'remd', or 'mix'."
    exit 1
fi

TRAJIN_LINES=$(awk -v mode="$TRAJ_TYPE" -v t="$TEMP" '
BEGIN { err = 0 }
{
    sub(/\r$/, "")
    line = $0
    sub(/^[[:space:]]+/, "", line)
    if (line == "" || substr(line, 1, 1) == "#") next
    if (tolower(substr(line, 1, 7)) ~ /^trajin[[:space:]]/) {
        sub(/^[Tt][Rr][Aa][Jj][Ii][Nn][[:space:]]+/, "", line)
        sub(/^[[:space:]]+/, "", line)
        if (line == "" || substr(line, 1, 1) == "#") next
    }
    q = substr(line, 1, 1)
    if (q == "\"" || q == "\047") {
        idx = index(substr(line, 2), q)
        if (idx == 0) {
            printf("ERROR: Unclosed quote in trajectory list at line %d: %s\n", NR, $0) > "/dev/stderr"
            err = 2
            exit 2
        }
        f = substr(line, 2, idx - 1)
        rest_str = substr(line, idx + 2)
        sub(/#.*/, "", rest_str)
    } else {
        sub(/#.*/, "", line)
        sub(/[[:space:]]+$/, "", line)
        if (line == "") next
        if (match(line, /[[:space:]]+/)) {
            f = substr(line, 1, RSTART - 1)
            rest_str = substr(line, RSTART + RLENGTH)
        } else {
            f = line
            rest_str = ""
        }
    }
    if (f == "") {
        printf("ERROR: Empty trajectory path in trajectory list at line %d.\n", NR) > "/dev/stderr"
        err = 2
        exit 2
    }
    sub(/^[[:space:]]+/, "", rest_str)
    sub(/[[:space:]]+$/, "", rest_str)
    if (mode == "remd") {
        print "trajin \"" f "\"" (rest_str != "" ? " " rest_str : "") " remdtraj remdtrajtemp " t
    } else if (mode == "mix") {
        n_tok = split(rest_str, toks, /[[:space:]]+/)
        tag = (n_tok >= 1) ? tolower(toks[1]) : ""
        if (tag == "remd") {
            rem_rest = ""
            for (i = 2; i <= n_tok; i++) rem_rest = rem_rest " " toks[i]
            print "trajin \"" f "\"" rem_rest " remdtraj remdtrajtemp " t
        } else if (tag == "md") {
            rem_rest = ""
            for (i = 2; i <= n_tok; i++) rem_rest = rem_rest " " toks[i]
            print "trajin \"" f "\"" rem_rest
        } else {
            print "trajin \"" f "\"" (rest_str != "" ? " " rest_str : "")
        }
    } else {
        print "trajin \"" f "\"" (rest_str != "" ? " " rest_str : "")
    }
}
END { if (err) exit err }
' "$TRAJ_LIST")
AWK_RC=$?
if [ "$AWK_RC" -ne 0 ]; then
    exit 1
fi

if [ -z "$TRAJIN_LINES" ]; then
    echo "ERROR: No trajectory entries found in '$TRAJ_LIST'."
    exit 1
fi

AUTOIMAGE_LOWER=$(printf '%s' "${AUTOIMAGE:-true}" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')
if [[ "$AUTOIMAGE_LOWER" == "true" || "$AUTOIMAGE_LOWER" == "1" || "$AUTOIMAGE_LOWER" == "yes" || "$AUTOIMAGE_LOWER" == "on" ]]; then
    AUTOIMAGE_BLOCK=$'\nautoimage'
else
    AUTOIMAGE_BLOCK=""
fi

STRIP_LOWER=$(printf '%s' "${SASA_STRIP_SOLVENT:-true}" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')
STRIP_DIVALENT_LOWER=$(printf '%s' "${SASA_STRIP_DIVALENT:-false}" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')
if [[ "$STRIP_LOWER" == "true" || "$STRIP_LOWER" == "1" || "$STRIP_LOWER" == "yes" || "$STRIP_LOWER" == "on" ]]; then
    STRIP_MASK=":WAT,HOH,TIP3,TIP3P,TIP4,TIP4P,T4E,TIP5,TIP5P,OPC,SOL,SPC,SPCE,TP3,T3P,H2O,NA,CL,K,Na+,Cl-,K+,NA+,CL-,SOD,CLA,POT,CS,Cs+,CS+,RB,Rb+,RB+,LI,Li+,LI+,F,F-,BR,Br-,BR-,I,I-"
    if [[ "$STRIP_DIVALENT_LOWER" == "true" || "$STRIP_DIVALENT_LOWER" == "1" || "$STRIP_DIVALENT_LOWER" == "yes" || "$STRIP_DIVALENT_LOWER" == "on" ]]; then
        STRIP_MASK="${STRIP_MASK},MG,CA,ZN,Mg2+,Ca2+,Zn2+,MG2+,CA2+,ZN2+,CAL"
    fi
    STRIP_BLOCK=$'\nstrip '"${STRIP_MASK}"
else
    STRIP_BLOCK=""
fi

# Calculate Solvent Accessible Surface Area using LCPO method
echo "--> Calculating Solvent Accessible Surface Area (SASA) for $MASK atoms..."
cat <<EOF > "$OUT_DIR/${OUT_BASE}.in"
parm "$TOPOLOGY"
$TRAJIN_LINES$AUTOIMAGE_BLOCK$STRIP_BLOCK
surf sasa_out $MASK out "$OUT_FILE"
EOF

cpptraj -i "$OUT_DIR/${OUT_BASE}.in" > "$OUT_DIR/cpptraj_${OUT_BASE}.log" 2>&1
if [ $? -ne 0 ]; then
    echo "ERROR: SASA calculation failed! Details below:"
    cat "$OUT_DIR/cpptraj_${OUT_BASE}.log"
    rm -f "$OUT_DIR/${OUT_BASE}.in"
    exit 1
fi
rm -f "$OUT_DIR/${OUT_BASE}.in"

echo "--> SASA calculation completed: $OUT_FILE"
