#!/bin/bash
export LC_ALL=C
# MD Analysis - RMSD Calculation against Average Structure
# Usage: ./calculate_rmsd.sh <topology> <traj_list> <out_file>

TOPOLOGY=$1
TRAJ_LIST=$2
OUT_FILE=$3
MASK=${4:-"@CA"}
REF=${5:-"average"}

# Check arguments
if [ -z "$TOPOLOGY" ] || [ -z "$TRAJ_LIST" ] || [ -z "$OUT_FILE" ]; then
    echo "Error: Missing arguments."
    echo "Usage: $0 <topology_file> <trajectory_list_file> <output_file>"
    exit 1
fi

# Extract output directory from the out_file path
OUT_DIR=$(dirname "$OUT_FILE")
OUT_BASE=$(basename "$OUT_FILE" .dat)
AVG_FILE="$OUT_DIR/avg_rmsd.rst7"
AVG_PDB_FILE="$OUT_DIR/avg_rmsd.pdb"

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

# Check if average structure is needed and exists in the output directory. If not, generate it.
REF_LOWER=$(printf '%s' "$REF" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')
GENERATED_AVG=0
if [ "$REF_LOWER" = "average" ] && [ ! -f "$AVG_FILE" ]; then
    echo "--> Average structure ($AVG_FILE) not found. Generating average structure first..."
    cat <<EOF > "$OUT_DIR/step1_avg.in"
parm "$TOPOLOGY"
$TRAJIN_LINES$AUTOIMAGE_BLOCK
rms first $MASK
average "$AVG_FILE" restart
EOF
    cpptraj -i "$OUT_DIR/step1_avg.in" > "$OUT_DIR/cpptraj_avg_rmsd.log" 2>&1
    if [ $? -ne 0 ]; then
        echo "ERROR: Average structure calculation failed! Details below:"
        cat "$OUT_DIR/cpptraj_avg_rmsd.log"
        rm -f "$OUT_DIR/step1_avg.in"
        exit 1
    fi
    rm -f "$OUT_DIR/step1_avg.in"
    GENERATED_AVG=1
fi

if [ "$REF_LOWER" = "average" ] && { [ "$GENERATED_AVG" -eq 1 ] || [ ! -f "$AVG_PDB_FILE" ]; }; then
    if [ ! -f "$AVG_FILE" ]; then
        echo "ERROR: Average structure file ($AVG_FILE) was not created."
        exit 1
    fi
    echo "--> Converting RMSD average structure to PDB ($AVG_PDB_FILE)..."
    cat <<EOF > "$OUT_DIR/step1_avg_pdb.in"
parm "$TOPOLOGY"
trajin "$AVG_FILE"
trajout "$AVG_PDB_FILE" pdb
run
EOF
    cpptraj -i "$OUT_DIR/step1_avg_pdb.in" > "$OUT_DIR/cpptraj_avg_rmsd_pdb.log" 2>&1
    if [ $? -ne 0 ]; then
        echo "ERROR: RMSD average structure PDB conversion failed! Details below:"
        cat "$OUT_DIR/cpptraj_avg_rmsd_pdb.log"
        rm -f "$OUT_DIR/step1_avg_pdb.in"
        exit 1
    fi
    rm -f "$OUT_DIR/step1_avg_pdb.in"
    if [ ! -f "$AVG_PDB_FILE" ]; then
        echo "ERROR: RMSD average PDB file ($AVG_PDB_FILE) was not created."
        exit 1
    fi
fi

# Calculate RMSD using the specified reference
if [ "$REF_LOWER" = "first" ]; then
    echo "--> Calculating RMSD against the first frame of the trajectory..."
    cat <<EOF > "$OUT_DIR/${OUT_BASE}.in"
parm "$TOPOLOGY"
$TRAJIN_LINES$AUTOIMAGE_BLOCK
rms first $MASK out "$OUT_FILE"
EOF
elif [ "$REF_LOWER" = "average" ]; then
    echo "--> Calculating RMSD against the average structure ($AVG_FILE)..."
    cat <<EOF > "$OUT_DIR/${OUT_BASE}.in"
parm "$TOPOLOGY"
reference "$AVG_FILE"
$TRAJIN_LINES$AUTOIMAGE_BLOCK
rms reference $MASK out "$OUT_FILE"
EOF
else
    # It must be a path to a custom reference PDB file
    if [ ! -f "$REF" ]; then
        echo "ERROR: Custom reference PDB file '$REF' was not found!"
        exit 1
    fi
    echo "--> Calculating RMSD against custom reference structure ($REF)..."
    cat <<EOF > "$OUT_DIR/${OUT_BASE}.in"
parm "$TOPOLOGY" [traj_parm]
parm "$REF" [ref_parm]
reference "$REF" [ref_struct] parm [ref_parm]
$TRAJIN_LINES$AUTOIMAGE_BLOCK
rms rmsd_out $MASK ref [ref_struct] $MASK out "$OUT_FILE"
EOF
fi

cpptraj -i "$OUT_DIR/${OUT_BASE}.in" > "$OUT_DIR/cpptraj_${OUT_BASE}.log" 2>&1
if [ $? -ne 0 ]; then
    echo "ERROR: RMSD calculation failed! Details below:"
    cat "$OUT_DIR/cpptraj_${OUT_BASE}.log"
    rm -f "$OUT_DIR/${OUT_BASE}.in"
    exit 1
fi
rm -f "$OUT_DIR/${OUT_BASE}.in"

echo "--> RMSD calculation completed: $OUT_FILE"
