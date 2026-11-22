# inputs
parmFile="tacf.parm7"
init_rstFile="equi3.3.rst7"
prefix="bench"

indx=0
pmemd.cuda -O \
  -i "bench.mdin" \
  -c "${init_rstFile}" \
  -p "${parmFile}" \
  -ref "${init_rstFile}" \
  -phmdin "phmdin_restart" \
  -phmdparm "c22_pme_dayhoff2026.parm" \
  -phmdstrt "equi3.3.phmdrst" \
  -phmdout "${prefix}.lambda" \
  -r "${prefix}.rst7" \
  -phmdrestrt "${prefix}.phmdrst" \
  -x "${prefix}.nc" \
  -o "${prefix}.mdout" 
