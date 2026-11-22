#!/bin/bash

prmtop=../pre/*.prmtop
inpcrd=../pre/*.inpcrd

pmemd.cuda -O -i min.mdin -p $prmtop -c $inpcrd -o min.mdout -r min.mdrst -x min.nc -ref $inpcrd
