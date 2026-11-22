mdrst=../min/min.mdrst

pmemd.cuda -O -i nvt.mdin \
  -c ${mdrst} \
  -p ../pre/*.parm7 \
  -ref ${mdrst} \
  -phmdin phmdin_start \
  -phmdparm c22_pme_dayhoff2026.parm \
  -phmdout nvt.lambda \
  -phmdrestrt nvt.phmdrst \
  -o nvt.mdout  \
  -r nvt.mdrst \
  -x nvt.nc
