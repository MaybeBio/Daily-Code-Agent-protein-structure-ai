#$ -S /bin/bash
#$ -cwd
#$ -o output.log
#$ -e output.error
#$ -R y
#$ -j y
#$ -l h_data=6G,h_rt=168:00:00,h=spirit5
#$ -pe smp 5
#$ -l gpu=4
#$ -N hewl_ff14_rex

################################################################################
#RUN PARAMETERS       !!!!! make sure NGPU and phmdparm is correct !!!!!!
################################################################################

NGPU=4
RUN_NVT=1

AMBER_BASE=/opt/shen/shared/apps/amber/pmemd24.4
export PMEMD=${AMBER_BASE}/bin/pmemd.cuda.MPI

export basecamp=$PWD
export cont_from=${basecamp}/../nvt/nvt
export parmfiles=${basecamp}/../../../../../../parmfiles

export mdin=${basecamp}/AREX.mdin
export phmdin=${parmfiles}/phmdin_start
export phmdparm=${parmfiles}/ff14sb_pme_dayhoff2027.parm
export prmtop=${basecamp}/../../pre/*.prmtop

################################################################################
#SETUP ENVIRONMENT/BE VERBOSE
################################################################################

source ${AMBER_BASE}/amber.sh

echo "job name: $JOB_NAME"
echo "Assigned SGE GPUs: $SGE_GPU"
echo "Assigned HGR GPUs: $SGE_HGR_gpu"

node=$(hostname -s)
echo "hostname: ${node}"


################################################################################
#OPTIONAL NVT EQU
################################################################################

if [[ "${RUN_NVT}" == "1" ]]; then
  echo "nvt equilibration: $(dirname ${cont_from})"
  cd $(dirname ${cont_from}) && bash script.sh
  echo "nvt equilibration: complete"
fi


################################################################################
#SETUP TEMP SCRATCH SPACE
################################################################################

export scratch=$(mktemp -d -t "${USER}_${JOB_NAME}_XXXXXX")
if [ -d ${scratch} ]; then
  echo "scratch: ${scratch}" && cd ${scratch}
else
  echo "scratch not created/found"
fi


################################################################################
#DO THE DAMN THING
################################################################################

let NP=${NGPU}+1

echo "launching"
time mpirun -np ${NP} \
  ${PMEMD} -O -i ${mdin} \
  -c ${cont_from}.mdrst \
  -p ${prmtop} \
  -ref ${cont_from}.mdrst \
  -phmdin ${phmdin} \
  -phmdparm ${phmdparm} \
  -phmdstrt ${cont_from}.phmdrst \
  -phmdout ${scratch}/arex.lambda \
  -phmdrestrt ${scratch}/arex.phmdrst \
  -r ${scratch}/arex.mdrst \
  -x ${scratch}/arex.nc \
  -o ${scratch}/arex.mdout


################################################################################
#HOUSEKEEPING
################################################################################

echo "copying from scratch back to basecamp"
cp -r ${scratch}/* ${basecamp}/. && rm -rf ${scratch}

echo "fin"
