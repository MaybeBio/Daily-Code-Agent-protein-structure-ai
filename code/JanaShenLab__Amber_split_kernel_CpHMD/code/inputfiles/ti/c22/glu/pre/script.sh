#!/bin/bash

###############################################################################
###############################################################################
###############################################################################

#path to gen_pep an solvate_sys scripts
scripts=../../../../charmm_scripts

#path to charmm22 forcefield(s)
toppars=../../../../toppar

pep=geg               #peptide sequence
cushion=15            #bulk water between heavy atoms and PBC
boxtype=octahedral    #unit cell type, i.e. cubic, rhomic, octahedral
capped=1              #boolean for capping peptide with ACE/NH2
sod=1                 #number of Na+ ions, ignored if conc is set
cla=0                 #number of Cl- ions, ignored if conc is set
conc=                 #concentration in mM, leave blank to use sod/cla instead

###############################################################################
##################################### written by Guy W. Dayhoff II ###########
###############################################################################

#generate the peptide with or without ACE/NH2 caps
if [[ ${capped} -eq 1 ]]; then
  bash ${scripts}/genpep.sh --pep ${pep} --capped
  termini=capped
else
  bash ${scripts}/genpep.sh --pep ${pep}
  termini=uncapped
fi

#setup system in a box with water and any ions
if [[ ${conc} == '' ]]; then
  bash ${scripts}/solvate_sys.sh \
    --in ${termini}_${pep} \
    --box "${boxtype}" \
    --cushion ${cushion} \
    --sod ${sod} \
    --cla ${cla} \
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

   if [ ${cla} -eq 0 ] && [ ${sod} -eq 0 ] && [ ${conc} == '']; then
      ions=0ions
   fi

else
  bash ${scripts}/solvate_sys.sh \
    --in ${termini}_${pep} \
    --box "${boxtype}" \
    --cushion ${cushion} \
    --conc=${conc} \
    --titr 0
  ions=${conc}mm
fi

system=${termini}_${pep}_solv_${cushion}a_${boxtype}_${ions}

#convert the system for pmemd.cuda run using chamber from ambertools
source /opt/shen/shared/apps/amber/ambertools25_gcc12_avx2_sm75_86/amber.sh 
bash ${scripts}/run_chamber.sh ${toppars}/ ${system}

