parmfile=../pre/*.parm7
rstfile=../pre/*.rst7

pmemd.cuda -O -i min.mdin -p $parmfile -c $rstfile \
  -o min.mdout \
  -r min.mdrst \
  -x min.nc \
  -ref $rstfile
