cont_from=../nvt/nvt

pmemd.cuda -O -i bench.mdin \
  -c ${cont_from}.mdrst \
  -p ../pre/*.prmtop \
  -ref ${cont_from}.mdrst \
  -phmdin phmdin_start \
  -phmdparm c22_pme_dayhoff2026.parm \
  -phmdout bench.lambda \
  -phmdstrt ${cont_from}.phmdrst \
  -r bench.mdrst \
  -phmdrestrt bench.phmdrst \
  -x bench.nc \
  -o bench.mdout
