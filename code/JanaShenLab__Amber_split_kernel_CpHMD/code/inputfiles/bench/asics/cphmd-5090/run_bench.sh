#prep env

export basecamp=$PWD
export mdin=${basecamp}/bench.mdin
export cont_from=e1_5

#do the damn thing
pmemd.cuda -O -i ${mdin} \
  -c ${cont_from}.rst7 \
  -p ${basecamp}/*.parm7 \
  -ref ${cont_from}.rst7 \
  -phmdin ${basecamp}/phmdin_start \
  -phmdparm ${basecamp}/c22_pme_dayhoff2026.parm \
  -phmdstrt ${cont_from}.phmdrst \
  -phmdout bench.lambda \
  -phmdrestrt bench.phmdrst \
  -r bench.mdrst \
  -x bench.nc \
  -o bench.mdout
