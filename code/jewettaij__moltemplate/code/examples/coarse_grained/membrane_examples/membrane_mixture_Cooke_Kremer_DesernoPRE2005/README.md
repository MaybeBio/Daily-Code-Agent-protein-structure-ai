Cooke & Kremer (2005) coarse grained membrane
=============================================
This is a simulation of phase separation between two different types of lipids in the same coarse-grained membrane.  This example contains an implementation of the DPPC lipid bilayer described in: "Tunable generic model for fluid bilayer membranes" Cooke IR, Kremer K, Deserno M, Physical Review E, 2005.

### Images

<img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/coarse_grained/membrane_examples/membrane_mixture_Cooke_Kremer_DesernoPRE2005/images/CDlipid_A.jpg" height=100> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/coarse_grained/membrane_examples/membrane_mixture_Cooke_Kremer_DesernoPRE2005/images/plus.svg" height=80> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/coarse_grained/membrane_examples/membrane_mixture_Cooke_Kremer_DesernoPRE2005/images/CDlipid_B.jpg" height=100> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/coarse_grained/membrane_examples/membrane_mixture_Cooke_Kremer_DesernoPRE2005/images/rightarrow.svg" height=80> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/coarse_grained/membrane_examples/membrane_mixture_Cooke_Kremer_DesernoPRE2005/images/CDlipid_bilayer_mixture_t%3D0_nopbc_occ_LR.jpg" width=190>  <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/coarse_grained/membrane_examples/membrane_mixture_Cooke_Kremer_DesernoPRE2005/images/rightarrow.svg" height=80> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/coarse_grained/membrane_examples/membrane_mixture_Cooke_Kremer_DesernoPRE2005/images/CDlipid_bilayer_mixture_t%3D40000steps_npt_occ_LR.jpg" width=180>  <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/coarse_grained/membrane_examples/membrane_mixture_Cooke_Kremer_DesernoPRE2005/images/rightarrow.svg" height=80> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/coarse_grained/membrane_examples/membrane_mixture_Cooke_Kremer_DesernoPRE2005/images/CDlipid_bilayer_mixture_t%3D120000steps_npt_occ_LR.jpg" width=180>  <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/coarse_grained/membrane_examples/membrane_mixture_Cooke_Kremer_DesernoPRE2005/images/rightarrow.svg" height=80> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/coarse_grained/membrane_examples/membrane_mixture_Cooke_Kremer_DesernoPRE2005/images/CDlipid_bilayer_mixture_t%3D1000000steps_npt_occ_LR.jpg" width=180>


### Strategy

First, a hexagonal array of lipids is created.  Rectangular periodic boundary conditions are applied, and the system is equilibrated at zero tension and constant temperature.  To change the number of molecules in the system and initial simulation box size, edit the [system.lt](https://github.com/jewettaij/moltemplate/blob/HEAD/examples/coarse_grained/membrane_examples/membrane_mixture_Cooke_Kremer_DesernoPRE2005/moltemplate_files/system.lt) file.  To change the simulation conditions, edit the [run.in.npt](https://github.com/jewettaij/moltemplate/blob/HEAD/examples/coarse_grained/membrane_examples/membrane_mixture_Cooke_Kremer_DesernoPRE2005/run.in.npt) file.


### Instructions

More detailed instructions on how to build LAMMPS input files and run a short simulation are provided in other README files.

1) To build the files which LAMMPS needs, follow the instructions in:
[README_setup.sh](https://github.com/jewettaij/moltemplate/blob/HEAD/examples/coarse_grained/membrane_examples/membrane_mixture_Cooke_Kremer_DesernoPRE2005/README_setup.sh)

2) To run LAMMPS with these files, follow these instructions:
[README_run.sh](https://github.com/jewettaij/moltemplate/blob/HEAD/examples/coarse_grained/membrane_examples/membrane_mixture_Cooke_Kremer_DesernoPRE2005/README_run.sh)
