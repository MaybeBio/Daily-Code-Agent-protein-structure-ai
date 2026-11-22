#!/bin/bash
export LC_ALL=C
# Usage:
#   2D Mode: ./filter_beta.sh <var1_file> <secstruct_file> <beta_threshold>
#   1D Mode: ./filter_beta.sh <secstruct_file> <beta_threshold>

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/parameters.in"
SUGGEST_TEMP="310.0"
if [ -f "$CONFIG_FILE" ]; then
    PARSED_TEMP=$(awk -F'=' '/^[[:space:]]*temperature[[:space:]]*=/ {
        val = $2
        sub(/#.*/, "", val)
        gsub(/^[[:space:]]+|[[:space:]]+$/, "", val)
        if (val ~ /^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$/ && (val + 0.0) > 0) {
            print val
        }
    }' "$CONFIG_FILE" | tail -n 1)
    if [ -n "$PARSED_TEMP" ]; then
        SUGGEST_TEMP="$PARSED_TEMP"
    fi
fi

check_secstruct_header_warning() {
    local sec_f="$1"
    if awk '/^[[:space:]]*#/ && tolower($0) ~ /total_count/ { found=1; exit } /^[[:space:]]*[^#@[:space:]]/ { exit } END { exit !found }' "$sec_f"; then
        echo "Warning: '$sec_f' header indicates total secondary structure ('total_count'), not beta-only count."
        echo "         Set secstruct_type=beta in parameters.in to filter strictly by beta-sheet content."
    fi
}

infer_var_label() {
    local b
    b=$(basename "$1" .dat)
    b=${b%_output}
    b=$(printf '%s' "$b" | tr '[:lower:]' '[:upper:]')
    if [[ "$b" =~ ^PCA([0-9]+)$ ]]; then
        b="PC${BASH_REMATCH[1]}"
    fi
    printf '%s' "$b"
}

if [ "$#" -eq 3 ]; then
    # 2D Mode
    VAR1_FILE=$1
    SEC_FILE=$2
    THRESHOLD=$3
    
    if [ ! -f "$VAR1_FILE" ]; then
        echo "Error: File not found: $VAR1_FILE"
        exit 1
    fi
    if [ ! -f "$SEC_FILE" ]; then
        echo "Error: File not found: $SEC_FILE"
        exit 1
    fi
    
    OUT1="${VAR1_FILE%.dat}_filtered.dat"
    OUT2="${SEC_FILE%.dat}_filtered.dat"

    check_secstruct_header_warning "$SEC_FILE"
    echo "--> 2D Mode: Filtering $VAR1_FILE and $SEC_FILE based on threshold >= $THRESHOLD..."
    
    export VAR1_FILE SEC_FILE THRESHOLD OUT1 OUT2
    
    if command -v python3 &>/dev/null && python3 -c "import sys" &>/dev/null; then
        PY_CMD="python3"
    elif command -v python &>/dev/null; then
        PY_CMD="python"
    else
        echo "Error: Neither python3 nor python command was found on this system."
        exit 1
    fi
    
    $PY_CMD -c '
import math
import os
import sys

var1_file = os.environ.get("VAR1_FILE")
sec_file = os.environ.get("SEC_FILE")
raw_thresh = os.environ.get("THRESHOLD")
try:
    threshold = float(raw_thresh)
    if not math.isfinite(threshold):
        raise ValueError
except (TypeError, ValueError):
    sys.stderr.write(f"Error: Invalid finite numeric threshold: {raw_thresh!r}\n")
    sys.exit(1)
out1 = os.environ.get("OUT1")
out2 = os.environ.get("OUT2")

if os.path.abspath(out1) == os.path.abspath(out2):
    sys.stderr.write(f"Error: Output paths collide ({out1} == {out2}). VAR1_FILE and SEC_FILE must be distinct files.\n")
    sys.exit(1)

def read_rows(filepath):
    rows = []
    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("@"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                try:
                    val = float(parts[1])
                except ValueError:
                    continue
                if not math.isfinite(val):
                    continue
                frame_id = None
                try:
                    f_val = float(parts[0])
                    if math.isfinite(f_val) and abs(f_val - round(f_val)) < 1e-9:
                        frame_id = int(round(f_val))
                except ValueError:
                    frame_id = None
                rows.append((frame_id, parts[0], val))
    return rows

rows1 = read_rows(var1_file)
rows2 = read_rows(sec_file)

all_int1 = len(rows1) > 0 and all(r[0] is not None for r in rows1)
all_int2 = len(rows2) > 0 and all(r[0] is not None for r in rows2)

kept = 0
if all_int1 and all_int2:
    var1_data = {}
    dup1 = 0
    for fr, _, val in rows1:
        if fr in var1_data:
            dup1 += 1
        var1_data[fr] = val
    if dup1 > 0:
        sys.stderr.write(f"Warning: {dup1} duplicate frame ID(s) overwritten in {var1_file}.\n")

    sec_data = {}
    dup2 = 0
    for fr, _, val in rows2:
        if fr in sec_data:
            dup2 += 1
        sec_data[fr] = val
    if dup2 > 0:
        sys.stderr.write(f"Warning: {dup2} duplicate frame ID(s) overwritten in {sec_file}.\n")

    min1 = min(var1_data.keys())
    min2 = min(sec_data.keys())
    if (min1 == 0 and min2 == 1) or (min1 == 1 and min2 == 0):
        exact_shift = (
            (min1 == 0 and {k + 1 for k in var1_data.keys()} == set(sec_data.keys()))
            or (min2 == 0 and {k + 1 for k in sec_data.keys()} == set(var1_data.keys()))
        )
        shift_note = " (exact +1 frame shift)" if exact_shift else ""
        sys.stderr.write(
            f"Warning: Potential 0-based vs 1-based Frame ID mismatch between '{var1_file}' (min={min1}) "
            f"and '{sec_file}' (min={min2}){shift_note}. Continuing with Frame ID intersection; "
            "verify whether one dataset needs a +1 frame offset.\n"
        )

    with open(out1, "w") as f1, open(out2, "w") as f2:
        f1.write("#Frame\tVAR1\n")
        f2.write("#Frame\tSECSTRUCT\n")

        common_frames = sorted(set(var1_data.keys()).intersection(sec_data.keys()))
        for frame in common_frames:
            sec_val = sec_data[frame]
            if sec_val >= threshold:
                f1.write(f"{frame}\t{var1_data[frame]}\n")
                f2.write(f"{frame}\t{sec_val}\n")
                kept += 1
else:
    if len(rows1) != len(rows2):
        sys.stderr.write(
            f"Error: Data lengths differ ({var1_file}: {len(rows1)}, {sec_file}: {len(rows2)}) "
            "and files do not share integer frame IDs for alignment.\n"
        )
        sys.exit(1)
    unique_int2 = all_int2 and len({r[0] for r in rows2}) == len(rows2)
    if len(rows1) > 0:
        print("Note: Column 0 contains non-integer values; aligning rows by order instead of integer Frame IDs.")
    with open(out1, "w") as f1, open(out2, "w") as f2:
        f1.write("#Frame\tVAR1\n")
        f2.write("#Frame\tSECSTRUCT\n")
        for (fr1, raw0_1, val1), (fr2, _, val2) in zip(rows1, rows2):
            out_frame = str(fr2) if unique_int2 else raw0_1
            if val2 >= threshold:
                f1.write(f"{out_frame}\t{val1}\n")
                f2.write(f"{out_frame}\t{val2}\n")
                kept += 1

print(f"--> Kept {kept} frames matching threshold >= {threshold}.")
if kept == 0:
    print(f"Warning: 0 frames matched threshold >= {threshold}.")
'
    if [ $? -ne 0 ]; then
        echo "Error: Filtering failed in 2D mode!"
        exit 1
    fi
    VAR1_LBL=$(infer_var_label "$VAR1_FILE")
    SUGGEST_DIR=$(dirname "$SEC_FILE")
    if [ "$SUGGEST_DIR" = "." ]; then
        SUGGEST_PNG="filtered_2d_fel.png"
    else
        SUGGEST_PNG="${SUGGEST_DIR}/filtered_2d_fel.png"
    fi
    echo "--> Filtering completed!"
    echo "Generated files:"
    echo "  - $OUT1"
    echo "  - $OUT2"
    echo "Note: A FEL built from filtered frames is a conditional free energy landscape dG(q | filter)"
    echo "      with a shifted zero reference; do not compare its dG scale directly against unfiltered runs."
    echo ""
    echo "To plot 2D FEL, you can run:"
    echo "python plot_fel.py \"$OUT1\" \"$OUT2\" \"$VAR1_LBL\" SECSTRUCT \"$SUGGEST_PNG\" --temp $SUGGEST_TEMP --config \"$CONFIG_FILE\""

elif [ "$#" -eq 2 ]; then
    # 1D Mode
    SEC_FILE=$1
    THRESHOLD=$2
    
    if [ ! -f "$SEC_FILE" ]; then
        echo "Error: File not found: $SEC_FILE"
        exit 1
    fi

    if ! [[ "$THRESHOLD" =~ ^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$ ]]; then
        echo "Error: Invalid numeric threshold '$THRESHOLD'."
        exit 1
    fi
    
    OUT2="${SEC_FILE%.dat}_filtered.dat"
    
    check_secstruct_header_warning "$SEC_FILE"
    echo "--> 1D Mode: Filtering $SEC_FILE based on threshold >= $THRESHOLD..."
    
    echo -e "#Frame\tSECSTRUCT" > "$OUT2"
    
    KEPT=$(awk -v thresh="$THRESHOLD" -v out2="$OUT2" '
      BEGIN { kept = 0 }
      {
        sub(/\r$/, "")
        if ($0 ~ /^[[:space:]]*$/ || $0 ~ /^[[:space:]]*[#@]/ || NF < 2) next
        if ($2 !~ /^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$/) next
        # $1: Frame, $2: Structure Count
        if (($2 + 0.0) >= (thresh + 0.0)) {
          print $1 "\t" $2 >> out2
          kept++
        }
      }
      END { print kept }
    ' "$SEC_FILE")
    if [ $? -ne 0 ]; then
        echo "Error: Filtering failed in 1D mode!"
        rm -f "$OUT2"
        exit 1
    fi
    echo "--> Kept ${KEPT:-0} frames matching threshold >= $THRESHOLD."
    if [ "${KEPT:-0}" -eq 0 ]; then
        echo "Warning: 0 frames matched threshold >= $THRESHOLD."
    fi

    SUGGEST_DIR=$(dirname "$SEC_FILE")
    if [ "$SUGGEST_DIR" = "." ]; then
        SUGGEST_PNG="filtered_1d_fel.png"
    else
        SUGGEST_PNG="${SUGGEST_DIR}/filtered_1d_fel.png"
    fi
    echo "--> Filtering completed!"
    echo "Generated file:"
    echo "  - $OUT2"
    echo "Note: A FEL built from filtered frames is a conditional free energy landscape dG(q | filter)"
    echo "      with a shifted zero reference; do not compare its dG scale directly against unfiltered runs."
    echo ""
    echo "To plot 1D FEL, you can run:"
    echo "python plot_fel.py \"$OUT2\" SECSTRUCT \"$SUGGEST_PNG\" --temp $SUGGEST_TEMP --config \"$CONFIG_FILE\""

else
    echo "Error: Invalid number of arguments."
    echo "Usage (2D): $0 <var1_file> <secstruct_file> <beta_threshold>"
    echo "Usage (1D): $0 <secstruct_file> <beta_threshold>"
    exit 1
fi
