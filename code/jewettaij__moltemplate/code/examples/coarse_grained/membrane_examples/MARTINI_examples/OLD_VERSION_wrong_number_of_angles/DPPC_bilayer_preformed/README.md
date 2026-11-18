MARTINI bilayer preformed (explicit FF parameters)
===============================
This example of the formation of a coarse-grained DPPC lipid-bilayer uses the Martini force-field v2.0 (2013-10), was provided by Saeed Momeni Bashusqeh.  In this version of the example, the lipids are initially arranged in a periodic lattice in the XY plane, pointing in the same direction.  If you prefer, PACKMOL can be used to assemble flat, 2D lipid bilayers with random orientations.  An example using PACKMOL can be found [here](https://github.com/jewettaij/moltemplate/blob/HEAD/examples/coarse_grained/membrane_examples/MARTINI_examples/OLD_VERSION_wrong_number_of_angles/DPPC_bilayer_formation_PACKMOL/README.md).

### Images
<img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/coarse_grained/membrane_examples/MARTINI_examples/OLD_VERSION_wrong_number_of_angles/DPPC_bilayer_preformed/images/DPPC_martini_LR.jpg" height=110> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/coarse_grained/membrane_examples/MARTINI_examples/OLD_VERSION_wrong_number_of_angles/DPPC_bilayer_preformed/images/plus.svg" height=80> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/coarse_grained/membrane_examples/MARTINI_examples/OLD_VERSION_wrong_number_of_angles/DPPC_bilayer_preformed/images/water_martini_LR.jpg" width=70> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/coarse_grained/membrane_examples/MARTINI_examples/OLD_VERSION_wrong_number_of_angles/DPPC_bilayer_preformed/images/plus.svg" height=80> **PACKMOL** <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/coarse_grained/membrane_examples/MARTINI_examples/OLD_VERSION_wrong_number_of_angles/DPPC_bilayer_preformed/images/rightarrow.svg" height=80> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/coarse_grained/membrane_examples/MARTINI_examples/OLD_VERSION_wrong_number_of_angles/DPPC_bilayer_preformed/images/t%3D0_bilayer_preformed_GL_LR.jpg" width=170> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/coarse_grained/membrane_examples/MARTINI_examples/OLD_VERSION_wrong_number_of_angles/DPPC_bilayer_preformed/images/rightarrow.svg" height=80> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/coarse_grained/membrane_examples/MARTINI_examples/OLD_VERSION_wrong_number_of_angles/DPPC_bilayer_preformed/images/t%3D4ns_bilayer_preformed_GL_LR.jpg" width=170>

The simulation size, number of lipids and water molecules, and initial placement is specified in the [system.lt](https://github.com/jewettaij/moltemplate/blob/HEAD/examples/coarse_grained/membrane_examples/MARTINI_examples/OLD_VERSION_wrong_number_of_angles/DPPC_bilayer_preformed/moltemplate_files/system.lt) file.  The simulation contitions can be controlled by editing the [run.in.npt](https://github.com/jewettaij/moltemplate/blob/HEAD/examples/coarse_grained/membrane_examples/MARTINI_examples/OLD_VERSION_wrong_number_of_angles/DPPC_bilayer_preformed/run.in.npt) and [run.in.nvt](https://github.com/jewettaij/moltemplate/blob/HEAD/examples/coarse_grained/membrane_examples/MARTINI_examples/OLD_VERSION_wrong_number_of_angles/DPPC_bilayer_preformed/run.in.nvt) files.


### Instructions

More detailed instructions on how to build LAMMPS input files and run a short simulation are provided in other README files.

1) To build the files which LAMMPS needs, follow the instructions in:
[README_setup.sh](https://github.com/jewettaij/moltemplate/blob/HEAD/examples/coarse_grained/membrane_examples/MARTINI_examples/OLD_VERSION_wrong_number_of_angles/DPPC_bilayer_preformed/README_setup.sh)

2) To run LAMMPS with these files, follow these instructions:
[README_run.sh](https://github.com/jewettaij/moltemplate/blob/HEAD/examples/coarse_grained/membrane_examples/MARTINI_examples/OLD_VERSION_wrong_number_of_angles/DPPC_bilayer_preformed/README_run.sh)

