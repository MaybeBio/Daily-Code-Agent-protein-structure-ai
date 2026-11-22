#!/bin/bash

mdrst=../../min/min.mdrst

pmemd.cuda -O -i nvt.mdin \
  -c ${mdrst} \
  -p ../../pre/*.prmtop \
  -ref ${mdrst} \
  -phmdin ../../../../../../parmfiles/phmdin_start \
  -phmdparm ../../../../../../parmfiles/c22_pme_dayhoff2027.parm \
  -phmdout nvt.lambda \
  -phmdrestrt nvt.phmdrst \
  -o nvt.mdout  \
  -r nvt.mdrst \
  -x nvt.nc
