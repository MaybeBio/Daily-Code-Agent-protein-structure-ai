#!/bin/bash

prmtop=../pre_hmr/*.prmtop
inpcrd=../pre_hmr/*.inpcrd

pmemd.cuda -O -i min.mdin -p $prmtop -c $inpcrd -o min.mdout -r min.mdrst -x min.nc -ref $inpcrd
