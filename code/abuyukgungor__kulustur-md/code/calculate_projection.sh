#!/bin/bash
export LC_ALL=C
# MD Analysis - Principal Component Projection (PCA Projection)
# Usage: ./calculate_projection.sh <topology> <traj_list> <pc_num> <out_file>

TOPOLOGY=$1
TRAJ_LIST=$2
PC_NUM=$3
OUT_FILE=$4
MASK=${5:-"@CA"}
MODES_VISUALIZE=${6:-"4"}

# Check arguments
if [ -z "$TOPOLOGY" ] || [ -z "$TRAJ_LIST" ] || [ -z "$PC_NUM" ] || [ -z "$OUT_FILE" ]; then
    echo "Error: Missing arguments."
    echo "Usage: $0 <topology_file> <trajectory_list_file> <pc_number> <output_file>"
    exit 1
fi

if ! [[ "$PC_NUM" =~ ^[0-9]+$ ]] || [ "$PC_NUM" -lt 1 ]; then
    echo "Error: Invalid PC index '$PC_NUM'. Must be a positive integer >= 1."
    exit 1
fi

if ! [[ "$MODES_VISUALIZE" =~ ^[0-9]+$ ]]; then
    echo "Error: Invalid MODES_VISUALIZE '$MODES_VISUALIZE'. Must be a non-negative integer >= 0."
    exit 1
fi

# Extract output directory from the out_file path
OUT_DIR=$(dirname "$OUT_FILE")
VECT_FILE="$OUT_DIR/vect.out"
AVG_FILE="$OUT_DIR/avg_pca.rst7"
AVG_PDB_FILE="$OUT_DIR/avg_pca.pdb"
COVAR_FILE="$OUT_DIR/covar.out"
EIGVAL_FILE="$OUT_DIR/pca_eigenvalues.dat"

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

PCA_MW_LOWER=$(printf '%s' "${PCA_MASS_WEIGHTED:-false}" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')
if [[ "$PCA_MW_LOWER" == "true" || "$PCA_MW_LOWER" == "1" || "$PCA_MW_LOWER" == "yes" || "$PCA_MW_LOWER" == "on" ]]; then
    RMS_MASS_FLAG=" mass"
    MATRIX_TYPE="mwcovar"
    MATRIX_NAME="mwcov"
    DIAG_TEMP_FLAG=" temp $TEMP"
else
    RMS_MASS_FLAG=""
    MATRIX_TYPE="covar"
    MATRIX_NAME="cov"
    DIAG_TEMP_FLAG=""
fi

# Step 1: Average structure calculation and Covariance Matrix / Eigenvectors diagonalization
# (Run if missing, or if cached vect.out lacks enough modes for PC_NUM / MODES_VISUALIZE)
NEED_STEP1=0
if [ ! -f "$VECT_FILE" ] || [ ! -f "$AVG_FILE" ]; then
    NEED_STEP1=1
else
    EXISTING_VECS=$(awk '/^[[:space:]]*\*\*\*\*/ {n++} END {print n+0}' "$VECT_FILE")
    if [ "$EXISTING_VECS" -lt "$PC_NUM" ] 2>/dev/null || [ "$EXISTING_VECS" -lt "$MODES_VISUALIZE" ] 2>/dev/null; then
        echo "--> Cached $VECT_FILE contains only $EXISTING_VECS mode(s) (need >= $PC_NUM and >= $MODES_VISUALIZE). Regenerating..."
        NEED_STEP1=1
    fi
fi

if [ "$NEED_STEP1" -eq 1 ]; then
    echo "--> Step 1a: Calculating average structure ($AVG_FILE)..."
    cat <<EOF > "$OUT_DIR/step1_avg.in"
parm "$TOPOLOGY"
$TRAJIN_LINES$AUTOIMAGE_BLOCK
rms first $MASK$RMS_MASS_FLAG
average "$AVG_FILE" restart
EOF
    cpptraj -i "$OUT_DIR/step1_avg.in" > "$OUT_DIR/cpptraj_avg_pca.log" 2>&1
    if [ $? -ne 0 ]; then
        echo "ERROR: Average structure calculation failed! Details below:"
        cat "$OUT_DIR/cpptraj_avg_pca.log"
        rm -f "$OUT_DIR/step1_avg.in"
        exit 1
    fi
    rm -f "$OUT_DIR/step1_avg.in"
fi

if [ ! -f "$AVG_FILE" ]; then
    echo "Error: PCA average structure file ($AVG_FILE) was not created."
    exit 1
fi

if [ "$NEED_STEP1" -eq 1 ] || [ ! -f "$AVG_PDB_FILE" ]; then
    echo "--> Converting PCA average structure to PDB ($AVG_PDB_FILE)..."
    cat <<EOF > "$OUT_DIR/step1_avg_pdb.in"
parm "$TOPOLOGY"
trajin "$AVG_FILE"
trajout "$AVG_PDB_FILE" pdb
run
EOF
    cpptraj -i "$OUT_DIR/step1_avg_pdb.in" > "$OUT_DIR/cpptraj_avg_pca_pdb.log" 2>&1
    if [ $? -ne 0 ]; then
        echo "ERROR: Average structure PDB conversion failed! Details below:"
        cat "$OUT_DIR/cpptraj_avg_pca_pdb.log"
        rm -f "$OUT_DIR/step1_avg_pdb.in"
        exit 1
    fi
    rm -f "$OUT_DIR/step1_avg_pdb.in"
fi

if [ "$NEED_STEP1" -eq 1 ]; then
    echo "--> Step 1b: Calculating covariance matrix ($MATRIX_TYPE) and eigenvectors ($VECT_FILE)..."
    MAX_VECS=${MAX_PC_REQUESTED:-10}
    if ! [[ "$MAX_VECS" =~ ^[0-9]+$ ]] || [ "$MAX_VECS" -lt 1 ]; then
        MAX_VECS=10
    fi
    if [ "$PC_NUM" -gt "$MAX_VECS" ] 2>/dev/null; then
        MAX_VECS=$PC_NUM
    fi
    if [ "$MODES_VISUALIZE" -gt "$MAX_VECS" ] 2>/dev/null; then
        MAX_VECS=$MODES_VISUALIZE
    fi
    DISPL_LINES=""
    for ((i=1; i<=MODES_VISUALIZE; i++)); do
        DISPL_LINES="${DISPL_LINES}runanalysis modes displ name vector beg $i end $i out \"$OUT_DIR/mode${i}.out\"
"
    done
    cat <<EOF > "$OUT_DIR/step1_cov.in"
parm "$TOPOLOGY"
reference "$AVG_FILE"
$TRAJIN_LINES$AUTOIMAGE_BLOCK
rms reference $MASK$RMS_MASS_FLAG
matrix $MATRIX_TYPE name $MATRIX_NAME $MASK out "$COVAR_FILE"
run
runanalysis diagmatrix $MATRIX_NAME name vector out "$VECT_FILE" vecs $MAX_VECS$DIAG_TEMP_FLAG
$DISPL_LINES
EOF
    cpptraj -i "$OUT_DIR/step1_cov.in" > "$OUT_DIR/cpptraj_cov.log" 2>&1
    if [ $? -ne 0 ]; then
        echo "ERROR: Covariance matrix calculation failed! Details below:"
        cat "$OUT_DIR/cpptraj_cov.log"
        rm -f "$OUT_DIR/step1_cov.in"
        exit 1
    fi
    rm -f "$OUT_DIR/step1_cov.in"
fi

# Validate Step 1 outputs
if [ ! -f "$VECT_FILE" ] || [ ! -f "$AVG_FILE" ] || [ ! -f "$AVG_PDB_FILE" ]; then
    echo "Error: PCA preparation files ($VECT_FILE, $AVG_FILE, or $AVG_PDB_FILE) were not created."
    exit 1
fi

# Compute explained variance (%) per PC mode from covariance trace and vect.out eigenvalues
# (For MWCOVAR, cpptraj converts eigenvalues to cm^-1 frequencies at TEMP; invert back to Da*A^2 variances.)
if [ "$NEED_STEP1" -eq 1 ] || [ ! -f "$EIGVAL_FILE" ]; then
    IS_MW_HINT=0
    if [ "$MATRIX_TYPE" = "mwcovar" ]; then
        IS_MW_HINT=1
    fi
    if [ -f "$COVAR_FILE" ]; then
        HAS_COVAR=1
        AWK_EIG_FILES=("$COVAR_FILE" "$VECT_FILE")
    else
        HAS_COVAR=0
        AWK_EIG_FILES=("$VECT_FILE")
    fi
    awk -v has_covar="$HAS_COVAR" -v is_mw_hint="$IS_MW_HINT" -v temp="$TEMP" '
        BEGIN {
            PI = atan2(0.0, -1.0)
            c_cm = 2.99792458e10
            R_si = 8.314462618
            C0_SQ = (R_si * 1.0e23) / ((2.0 * PI * c_cm) * (2.0 * PI * c_cm))
            is_mw = is_mw_hint + 0
            row = 0
            trace_sum = 0.0
            want_eig = 0
            n_modes = 0
            eig_sum = 0.0
        }
        has_covar == 1 && FNR == NR {
            sub(/\r$/, "")
            if ($0 ~ /^[[:space:]]*$/ || $0 ~ /^[[:space:]]*#/) next
            if ($1 !~ /^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$/) next
            row++
            if (NF >= row && $row ~ /^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$/) {
                trace_sum += ($row + 0.0)
            }
            next
        }
        {
            sub(/\r$/, "")
            low = tolower($0)
            if (low ~ /^[[:space:]]*eigenvector file:[[:space:]]*mwcovar/) {
                is_mw = 1
            } else if (low ~ /^[[:space:]]*eigenvector file:[[:space:]]*covar/) {
                is_mw = 0
            }
            if ($0 ~ /^[[:space:]]*\*\*\*\*/) { want_eig = 1; next }
            if (want_eig == 1) {
                if ($1 ~ /^[0-9]+$/ && NF >= 2 && $2 ~ /^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$/) {
                    n_modes++
                    mode_id[n_modes] = $1 + 0
                    raw_val[n_modes] = $2 + 0.0
                }
                want_eig = 0
            }
        }
        END {
            if (n_modes > 0) {
                t_val = temp + 0.0
                for (k = 1; k <= n_modes; k++) {
                    if (is_mw == 1) {
                        freq_cm[k] = raw_val[k]
                        eig_val[k] = (freq_cm[k] > 0.0) ? ((C0_SQ * t_val) / (freq_cm[k] * freq_cm[k])) : 0.0
                    } else {
                        eig_val[k] = raw_val[k]
                    }
                    eig_sum += (eig_val[k] > 0.0 ? eig_val[k] : 0.0)
                }
                if (has_covar == 1 && trace_sum > 0.0 && trace_sum >= eig_sum - 1e-6) {
                    denom = trace_sum
                    used_fallback = 0
                } else {
                    denom = eig_sum
                    used_fallback = 1
                }
                if (used_fallback == 1) {
                    printf("Warning: Covariance matrix trace unavailable or smaller than extracted eigenvalue sum; explained variance percentages in pca_eigenvalues.dat are normalized over the top %d extracted mode(s) only.\n", n_modes) > "/dev/stderr"
                    printf "# Warning: Normalized over top %d extracted mode(s) only (total covariance trace unavailable)\n", n_modes
                }
                if (is_mw == 1) {
                    printf "#Mode\tEigenvalue_Da_A2\tExplained_Variance_Pct\tCumulative_Variance_Pct\tFrequency_cm-1\n"
                } else {
                    printf "#Mode\tEigenvalue\tExplained_Variance_Pct\tCumulative_Variance_Pct\n"
                }
                cum = 0.0
                for (k = 1; k <= n_modes; k++) {
                    pct = (denom > 0.0) ? (100.0 * eig_val[k] / denom) : 0.0
                    cum += pct
                    if (is_mw == 1) {
                        printf "%d\t%.6g\t%.2f\t%.2f\t%.4f\n", mode_id[k], eig_val[k], pct, cum, freq_cm[k]
                    } else {
                        printf "%d\t%.6g\t%.2f\t%.2f\n", mode_id[k], eig_val[k], pct, cum
                    }
                }
            }
        }
    ' "${AWK_EIG_FILES[@]}" > "$EIGVAL_FILE"
fi

# Step 2: Projection onto the specified PC index
echo "--> Step 2: Projecting trajectory coordinates onto PC$PC_NUM..."
cat <<EOF > "$OUT_DIR/step2.in"
parm "$TOPOLOGY"
reference "$AVG_FILE"
readdata "$VECT_FILE" name map
$TRAJIN_LINES$AUTOIMAGE_BLOCK
rms reference $MASK$RMS_MASS_FLAG
projection proj modes map beg 1 end $PC_NUM $MASK out "$OUT_DIR/temp_proj.dat"
EOF

cpptraj -i "$OUT_DIR/step2.in" > "$OUT_DIR/cpptraj_proj.log" 2>&1
if [ $? -ne 0 ]; then
    echo "ERROR: Coordinate projection failed! Details below:"
    cat "$OUT_DIR/cpptraj_proj.log"
    rm -f "$OUT_DIR/step2.in"
    exit 1
fi
rm -f "$OUT_DIR/step2.in"

# Filter the desired PC mode from the cpptraj output (Column 1: Frame, Column PC_NUM+1: Value)
if ! awk -v col=$((PC_NUM + 1)) -v pc="$PC_NUM" '
    BEGIN { rows = 0; bad = 0 }
    /^#/ {
        if ($1 == "#Frame") { print "#Frame", "PC"pc }
        else { print "#" }
        next
    }
    NF == 0 { next }
    {
        if (NF < col) { bad = 1; exit 1 }
        print $1, $col
        rows++
    }
    END {
        if (bad || rows == 0) exit 1
    }
' "$OUT_DIR/temp_proj.dat" > "$OUT_FILE"; then
    echo "ERROR: Failed to extract PC$PC_NUM projection column from '$OUT_DIR/temp_proj.dat'."
    rm -f "$OUT_DIR/temp_proj.dat" "$OUT_FILE"
    exit 1
fi
rm -f "$OUT_DIR/temp_proj.dat"

PCA_VAR_INFO=""
if [ -f "$EIGVAL_FILE" ]; then
    PCA_VAR_INFO=$(awk -v pc="$PC_NUM" '
        /^[[:space:]]*#/ || NF < 4 { next }
        ($1 + 0) == (pc + 0) {
            printf "eigenvalue=%s, explained variance=%s%%, cumulative=%s%%", $2, $3, $4
            exit
        }
    ' "$EIGVAL_FILE")
fi

if [ -n "$PCA_VAR_INFO" ]; then
    echo "--> PC$PC_NUM projection calculation completed: $OUT_FILE ($PCA_VAR_INFO)"
else
    echo "--> PC$PC_NUM projection calculation completed: $OUT_FILE"
fi
