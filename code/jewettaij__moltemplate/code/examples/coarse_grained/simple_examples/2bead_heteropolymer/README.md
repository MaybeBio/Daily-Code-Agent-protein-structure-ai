2-bead Heteropolymer Example
====================

#### Images

<img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/coarse_grained/simple_examples/2bead_heteropolymer/images/monomer_H.png" height=70> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/coarse_grained/simple_examples/2bead_heteropolymer/images/plus.svg" height=80>
<img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/coarse_grained/simple_examples/2bead_heteropolymer/images/monomer_P.png" height=70> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/coarse_grained/simple_examples/2bead_heteropolymer/images/rightarrow.svg" height=80>
<img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/coarse_grained/simple_examples/2bead_heteropolymer/images/polymer_LR.png" width=180> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/coarse_grained/simple_examples/2bead_heteropolymer/images/rightarrow.svg" height=80>

<img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/coarse_grained/simple_examples/2bead_heteropolymer/images/trajectory.png" width=650>

This directory contains an example of a couarse-grained (vaguely protein-like)
heteropolymer consisting of 14 residues, each of which has 2 particles
(one backbone bead, CA, one residue bead, R).
There are 27 copies of this polymer in the simulation.

There are two types of residues, H and P.
The sidechain beads from the H residue
are attracted to each other ("HR", orange).
All other particles are repulsive.

### Instructions 
Instructions on how to build LAMMPS input files and
run a short simulation are provided in other README files.

#### Step 1) README_setup.sh
This file explains how to use moltemplate.sh to build the files that
LAMMPS needs.

#### Step 2) README_run.sh
This file explains how to use LAMMPS to run a simulation using the
files you created in step 1.

