#$ -S /bin/bash
#$ -cwd
#$ -o output.log
#$ -e output.error
#$ -R y
#$ -j y
#$ -l h_data=6G,h_rt=168:00:00,h=spirit6
#$ -pe smp 5
#$ -l gpu=4
#$ -N bbl_4x_2ns

################################################################################
#RUN PARAMETERS       !!!!! make sure NGPU and phmdparm is correct !!!!!!
################################################################################

NGPU=4
RUN_NVT=0

AMBER_BASE=/opt/shen/shared/pkgs/pmemd24+fstphrex/pmemd24/
export PMEMD=${AMBER_BASE}/bin/pmemd.cuda.MPI

export basecamp=$PWD
export cont_from=${basecamp}/../nvt/nvt
export parmfiles=${basecamp}/../../../../parmfiles

export mdin=${basecamp}/bench.mdin
export phmdin=${parmfiles}/phmdin_restart
export phmdparm=${parmfiles}/c22_pme_dayhoff2026.parm


################################################################################
#SETUP ENVIRONMENT
################################################################################

echo "job name: $JOB_NAME"
source ${AMBER_BASE}/amber.sh

echo "Assigned SGE GPUs: $SGE_GPU"
echo "Assigned HGR GPUs: $SGE_HGR_gpu"

node=$(hostname -s)
echo "hostname: ${node}"

if [[ "${node}" == "spirit6" ]]; then
  echo "Using spirit6 CUDA/Amber setup"
  export CUDA_HOME=/opt/cuda/12.8.1/
  export LD_LIBRARY_PATH=/opt/shen/shared/compilers/gcc/12.1.0/lib64:$CUDA_HOME/lib64
  export PATH=$CUDA_HOME/bin:$PATH
else
  echo "Using OG CUDA/Amber setup"
  export LD_LIBRARY_PATH=/opt/shen/shared/compilers/gcc/12.1.0/lib64:$LD_LIBRARY_PATH
fi


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
  trap 'rm -rf "${scratch}"' EXIT
else
  echo "scratch not created/found"
fi


################################################################################
#DO THE DAMN THING
################################################################################

let NP=${NGPU}+1

time mpirun -np ${NP} bash -c '
rank=${OMPI_COMM_WORLD_RANK}

if [ "${rank}" -eq 0 ]; then
  export CUDA_VISIBLE_DEVICES="-1"
else
  # SGE_GPU may be "4 5 6 7" or "4,5,6,7"; normalize to bash array.
  GPU_LIST_NORMALIZED=$(echo "${SGE_GPU}" | tr "," " ")
  gpus=(${GPU_LIST_NORMALIZED})

  gpu_index=$((rank - 1))

  if [ -z "${gpus[$gpu_index]}" ]; then
    echo "ERROR: rank=${rank} gpu_index=${gpu_index}, but SGE_GPU=${SGE_GPU}" >&2
    exit 1
  fi

  export CUDA_VISIBLE_DEVICES="${gpus[$gpu_index]}"
fi

echo "rank=${rank} host=$(hostname) SGE_GPU=${SGE_GPU} CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES}"

exec ${PMEMD} -O -i ${mdin} \
  -c ${cont_from}.mdrst \
  -p ${basecamp}/../../pre/*.prmtop \
  -ref ${cont_from}.mdrst \
  -phmdin ${phmdin} \
  -phmdparm ${phmdparm} \
  -phmdstrt ${cont_from}.phmdrst \
  -phmdout ${scratch}/arex.lambda \
  -phmdrestrt ${scratch}/arex.phmdrst \
  -r ${scratch}/arex.mdrst \
  -x ${scratch}/arex.nc \
  -o ${scratch}/arex.mdout
'

################################################################################
#HOUSEKEEPING
################################################################################

echo "copying from scratch back to basecamp"
cp -r ${scratch}/* ${basecamp}/. && rm -rf ${scratch}

echo "fin"

