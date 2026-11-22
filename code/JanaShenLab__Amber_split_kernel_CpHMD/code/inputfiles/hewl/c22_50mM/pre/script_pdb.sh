#!/bin/bash
set -euo pipefail

###############################################################################
###############################################################################
###############################################################################

# Path to pipeline Bash and CHARMM scripts.
scripts=../../../../charmm_scripts

# Path to CHARMM22 force fields.
toppars=../../../../toppar

###############################################################################
# STRUCTURE INPUT
###############################################################################

# Set exactly one of these:
pdbid=2lzt             # Fetch this PDB ID from RCSB
pdbfile=               # Use an existing PDB file, e.g. ./1ubq_original.pdb

chain=A                # Single protein chain to retain
cushion=15             # Bulk water between heavy atoms and PBC
boxtype=octahedral     # cubic, rhombic, or octahedral
capped=1               # 1 = ACE/CT2; 0 = NTER/CTER
sod=1                  # Number of Na+ ions; ignored if conc is set
cla=0                  # Number of Cl- ions; ignored if conc is set
conc=50                # Concentration in mM; blank uses sod/cla

###############################################################################
##################################### written by Guy W. Dayhoff II ###########
###############################################################################

die() {
  echo "Error: $*" >&2
  exit 1
}

###############################################################################
# VALIDATE AND RESOLVE STRUCTURE INPUT
###############################################################################

if [[ -n ${pdbid} ]] && [[ -n ${pdbfile} ]]; then
  die "Set either pdbid or pdbfile, not both."
fi

if [[ -z ${pdbid} ]] && [[ -z ${pdbfile} ]]; then
  die "Either pdbid or pdbfile must be set."
fi

chain_select=$(echo "${chain}" | tr '[:lower:]' '[:upper:]')
chain_tag=$(echo "${chain}" | tr '[:upper:]' '[:lower:]')

if [[ -n ${pdbid} ]]; then
  pdbid=$(echo "${pdbid}" | tr '[:upper:]' '[:lower:]')

  if ! [[ ${pdbid} =~ ^[[:alnum:]]{4}$ ]]; then
    die "pdbid must contain exactly four alphanumeric characters."
  fi

  pdb_original=${pdbid}_original.pdb

  # Download the original deposited PDB file.
  bash "${scripts}/get_pdb.sh" \
    --pdbid "${pdbid}" \
    --out "${pdb_original}"
else
  if [[ ! -f ${pdbfile} ]]; then
    die "PDB file not found: ${pdbfile}"
  fi

  if [[ ! -s ${pdbfile} ]]; then
    die "PDB file is empty: ${pdbfile}"
  fi

  pdb_original=${pdbfile}
  pdb_basename=$(basename "${pdbfile}")

  # The local filename must begin with its four-character PDB ID.
  # Supported examples:
  #   1ubq.pdb
  #   1ubq_original.pdb
  #   1ubq-downloaded.pdb
  if [[ ${pdb_basename} =~ ^([[:alnum:]]{4})([_\.-]|$) ]]; then
    pdbid=$(echo "${BASH_REMATCH[1]}" | tr '[:upper:]' '[:lower:]')
  else
    die "Local PDB filename must begin with its four-character PDB ID: ${pdb_basename}"
  fi
fi

###############################################################################
# PREPARATION FILENAMES
###############################################################################

pdb_clean=${pdbid}_${chain_tag}_clean.pdb
disulfides=${pdbid}_${chain_tag}_disulfides.dat
prep_report=${pdbid}_${chain_tag}_prep_report.txt

###############################################################################
# EXTRACT, NORMALIZE, AND VALIDATE THE SELECTED CHAIN
###############################################################################

bash "${scripts}/prep_pdb.sh" \
  --in "${pdb_original}" \
  --pdbid "${pdbid}" \
  --chain "${chain_select}" \
  --out "${pdb_clean}" \
  --disu-out "${disulfides}" \
  --report "${prep_report}"

###############################################################################
# GENERATE THE PROTEIN WITH OR WITHOUT ACE/CT2 CAPS
###############################################################################

if [[ ${capped} -eq 1 ]]; then
  termini=capped

  bash "${scripts}/gen_pdb_system.sh" \
    --in "${pdb_clean}" \
    --out "${termini}_${pdbid}_${chain_tag}" \
    --disu "${disulfides}" \
    --capped
else
  termini=uncapped

  bash "${scripts}/gen_pdb_system.sh" \
    --in "${pdb_clean}" \
    --out "${termini}_${pdbid}_${chain_tag}" \
    --disu "${disulfides}" \
    --uncapped
fi

prepared=${termini}_${pdbid}_${chain_tag}

###############################################################################
# SOLVATE AND ADD IONS
###############################################################################

if [[ ${conc} == '' ]]; then
  bash "${scripts}/solvate_sys.sh" \
    --in "${prepared}" \
    --box "${boxtype}" \
    --cushion "${cushion}" \
    --sod "${sod}" \
    --cla "${cla}" \
    --titr 0

  ions=""

  if [[ ${sod} -gt 0 ]]; then
    ions+=${sod}xsod
  fi

  if [[ ${sod} -gt 0 ]] && [[ ${cla} -gt 0 ]]; then
    ions+="_"
  fi

  if [[ ${cla} -gt 0 ]]; then
    ions+=${cla}xcla
  fi

  if [[ ${cla} -eq 0 ]] && [[ ${sod} -eq 0 ]] && [[ ${conc} == '' ]]; then
    ions=0ions
  fi
else
  bash "${scripts}/solvate_sys.sh" \
    --in "${prepared}" \
    --box "${boxtype}" \
    --cushion "${cushion}" \
    --conc "${conc}" \
    --titr 0

  ions=${conc}mm
fi

system=${prepared}_solv_${cushion}a_${boxtype}_${ions}

###############################################################################
# CONVERT FOR PMEMD.CUDA USING CHAMBER
###############################################################################


# AmberTools environment setup references variables that may initially be unset.
set +u
source /opt/shen/shared/apps/amber/ambertools25_gcc12_avx2_sm75_86/amber.sh
set -u

echo "running chamber"
set +e
bash "${scripts}/run_chamber.sh" "${toppars}/" "${system}"
echo "chamber complete"

###############################################################################
# REPORT FINAL WATER AND ION COUNTS FROM THE AMBER TOPOLOGY
###############################################################################

prmtop=${system}.prmtop

if [[ ! -s ${prmtop} ]]; then
  echo "Error: Amber topology not found or empty: ${prmtop}" >&2
  exit 1
fi

echo "found prmtop"

awk '
/^%FLAG RESIDUE_LABEL/ {
    reading = 1
    next
}

/^%FLAG/ && reading {
    reading = 0
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
        } else if (residue == "SOD") {
            sodium++
        } else if (residue == "CLA") {
            chloride++
        }
    }
}

END {
    printf "\n"
    printf "============================================================\n"
    printf "Final Amber System Composition\n"
    printf "Waters        : %d\n", waters + 0
    printf "Sodium ions   : %d\n", sodium + 0
    printf "Chloride ions : %d\n", chloride + 0
    printf "Total ions    : %d\n", sodium + chloride
    printf "============================================================\n"
}
' "${prmtop}"
