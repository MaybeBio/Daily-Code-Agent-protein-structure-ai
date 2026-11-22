#!/bin/bash
# Prepare QMMM free energy simulations.
# Edit this file for the system, then run write_mdin.sh, gen_inputs.sh, and gen_cvs.sh.

set -euo pipefail

REF="../dft"
init="step3_pbcsetup"
MDRST="prod00.ncrst"

N_WINDOWS=42
CV_MIN=-1.90
RC="409,410,410,6255"

THERMOSTAT="langevin" # langevin, sinr
NSTEPS5=500
NSTEPS6=800
PRINTFREQ=50

##################
# QM Configuration
##################
PROTEIN_RESIDUES="301,322"
METAL_RESIDUES="371"
WATER_RESIDUES="397,398,399,400"
NA_MASK="(:13&@385-409)|(:14&!@417-442)"

# Set QMMASK_OVERRIDE for a fully custom Amber mask; otherwise the named
# components above are combined into a default QM region.
QMMASK_OVERRIDE=""
QMMASK=${QMMASK_OVERRIDE:-(:${PROTEIN_RESIDUES}&!@N,H,CA,HA,C,O)|(${NA_MASK})|:${METAL_RESIDUES},${WATER_RESIDUES}}

QMTHEORY="EXTERN" # EXTERN for QMHub, or an Amber-supported semiempirical method
QMHUB_MODE="DFT"  # DFT or MTS; used only when QMTHEORY=EXTERN
QMCHARGE="+1"

####################
# Don't change this
####################
cwd=$(realpath ..)
inp_dir="${cwd}/input"

for v in N_WINDOWS CV_MIN RC THERMOSTAT NSTEPS5 NSTEPS6 PRINTFREQ QMMASK QMTHEORY QMCHARGE; do
    [ -n "${!v}" ] || { echo "ERROR: missing ${v}" >&2; exit 1; }
done

case "$THERMOSTAT" in
    langevin|sinr) ;;
    *) echo "ERROR: THERMOSTAT must be 'langevin' or 'sinr' (got '$THERMOSTAT')" >&2; exit 1 ;;
esac

if [ "$QMTHEORY" = "EXTERN" ]; then
    case "$QMHUB_MODE" in
        DFT|MTS) ;;
        *) echo "ERROR: QMHUB_MODE must be 'DFT' or 'MTS' when QMTHEORY=EXTERN" >&2; exit 1 ;;
    esac
fi

cat <<_EOF > qm_info.txt
cwd=${cwd}
protein=${PROTEIN_RESIDUES}
na=${NA_MASK}
metal=${METAL_RESIDUES}
water=${WATER_RESIDUES}
qmmask=${QMMASK}
qmtheory=${QMTHEORY}
qmhub_mode=${QMHUB_MODE}
qmcharge=${QMCHARGE}
thermostat=${THERMOSTAT}
nsteps5=${NSTEPS5}
nsteps6=${NSTEPS6}
n_windows=${N_WINDOWS}
cv_min=${CV_MIN}
print_freq=${PRINTFREQ}
rc=${RC}
_EOF

#####################
# Get files from $REF
#####################
echo "copying: files from ${REF}"
cp "${REF}/${init}.parm7" .
cp "${REF}/${MDRST}" .

echo "qmmask=${QMMASK}"
echo "qmcharge=${QMCHARGE}"
if [ "$QMTHEORY" = "EXTERN" ]; then
    echo "qmhub_mode=${QMHUB_MODE}"
fi
