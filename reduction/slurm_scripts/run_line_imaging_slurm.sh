#!/bin/bash
#SBATCH --mail-type=NONE          # Mail events (NONE, BEGIN, END, FAIL, ALL)
#SBATCH --mail-user=adamginsburg@ufl.edu     # Where to send mail
#SBATCH --ntasks=8                    # Run on a single CPU
#SBATCH --nodes=1
#SBATCH --time=96:00:00               # Time limit hrs:min:sec

env
pwd; hostname; date
echo "Memory=${MEM}"

WORK_DIR='/orange/adamginsburg/ALMA_IMF/2017.1.01355.L'

module load git
# for MPI module load cuda/11.0.207  gcc/9.3.0 openmpi/4.0.4

which python
which git

git --version
echo $?



export CASA=/orange/adamginsburg/casa/casa-release-5.6.0-60.el7/bin/casa
export CASA=/orange/adamginsburg/casa/casa-pipeline-release-5.6.1-8.el7/bin/casa


export ALMAIMF_ROOTDIR="/orange/adamginsburg/ALMA_IMF/reduction/reduction"
cd ${ALMAIMF_ROOTDIR}
python getversion.py

cd ${WORK_DIR}
echo ${WORK_DIR}
echo ${LINE_NAME} ${BAND_NUMBERS}

export PYTHONPATH=$ALMAIMF_ROOTDIR
export SCRIPT_DIR=$ALMAIMF_ROOTDIR
export PYTHONPATH=$SCRIPT_DIR

echo $LOGFILENAME

# do one band at a time to enable _disabling_ one or the other
#export BAND_NUMBERS="3"
echo xvfb-run -d ${CASA} --nogui --nologger --logfile=${LOGFILENAME} -c "execfile('$SCRIPT_DIR/line_imaging.py')"
xvfb-run -d ${CASA} --nogui --nologger --logfile=${LOGFILENAME} -c "execfile('$SCRIPT_DIR/line_imaging.py')"

#export BAND_NUMBERS="6"
#xvfb-run -d ${CASA} --nogui --nologger -c "execfile('$SCRIPT_DIR/line_imaging.py')"
