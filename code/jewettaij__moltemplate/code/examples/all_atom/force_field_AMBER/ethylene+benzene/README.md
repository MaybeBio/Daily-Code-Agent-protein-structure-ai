Ethylene, Benzene mixture
==============
A mixture of two small organic molecules using the *OPLSAA* force field.  In this example, the ethylene molecules were initially arranged in a rectangular lattice.  The benzene molecules were also arranged in a lattice, and were shifted to avoid overlap with the ethylene molecules.  *(Alternatively, you can create a single lattice and specify the number of ethelene and benzene molecules you want in it using moltemplate's "new random([],[])" command, which is explained in [the manual](https://moltemplate.org/doc/moltemplate_manual.pdf#subsubsection.8.9.1).  This gives you more control over the concentration of each ingredient.  You can also use PACKMOL to create random mixtures of molecules.)*


#### Images

<img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/all_atom/force_field_AMBER/ethylene%2Bbenzene/images/ethylene.jpg" width=110> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/all_atom/force_field_AMBER/ethylene%2Bbenzene/images/plus.svg" height=80> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/all_atom/force_field_AMBER/ethylene%2Bbenzene/images/benzene.jpg" width=110> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/all_atom/force_field_AMBER/ethylene%2Bbenzene/images/rightarrow.svg" height=80> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/all_atom/force_field_AMBER/ethylene%2Bbenzene/images/ethylene%2Bbenzene_t%3D0_LR.jpg" width=150> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/all_atom/force_field_AMBER/ethylene%2Bbenzene/images/rightarrow.svg" height=80> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/all_atom/force_field_AMBER/ethylene%2Bbenzene/images/ethylene%2Bbenzene_50bar_t%3D100000_LR.jpg" width=150>

The number of molecules, positions, and simulation box size can be controlled by editing the [system.lt file](https://github.com/jewettaij/moltemplate/blob/HEAD/examples/all_atom/force_field_AMBER/ethylene%2Bbenzene/moltemplate_files/system.lt).  The simulation contitions can be controlled by editing the [run.in.npt file](https://github.com/jewettaij/moltemplate/blob/HEAD/examples/all_atom/force_field_AMBER/ethylene%2Bbenzene/run.in.npt).


### *WARNING: The atomic charges in this examples are not correct*

The AMBER for field does not include charge information.  (In this example, they were borrowed from the corresponding atoms in the ["oplsaa2024.lt" file](https://github.com/jewettaij/moltemplate/blob/HEAD/moltemplate/force_fields/oplsaa2024.lt).  Do not do this!)

The generation of atomic partial charges requires 3rd party software.

For suggestions how to calculate charges correctly, see [README.md](https://github.com/jewettaij/moltemplate/blob/HEAD/examples/all_atom/force_field_AMBER/README.md).  Then choose a 3rd party program to calculate partial charges for the atoms in each type of molecule.  Then edit the corresponding ".lt" files in the "moltemplate_files" directory accordingly.


## Instructions

1) To build the files which LAMMPS needs, follow the instructions in:
[README_setup.sh](https://github.com/jewettaij/moltemplate/blob/HEAD/examples/all_atom/force_field_AMBER/ethylene%2Bbenzene/README_setup.sh)

2) To run LAMMPS with these files, follow these instructions:
[README_run.sh](https://github.com/jewettaij/moltemplate/blob/HEAD/examples/all_atom/force_field_AMBER/ethylene%2Bbenzene/README_run.sh)

(The instructions in "README_remove_irrelevant_info.sh" are optional.  *(If you notice a problem with this example, please [report it](https://github.com/jewettaij/moltemplate/blob/HEAD/examples/all_atom/force_field_AMBER/README.md).*)


### Requirements

This example requires a version of LAMMPS compiled with support for the optional "EXTRA-MOLECULE" package (because the AMBER force field currently uses *dihedral_style fourier*).  If you encounter the error *"Invalid dihedral_style"*, then see [this page](https://docs.lammps.org/Build_package.html) for instructions to compile LAMMPS to support this package.
