Ethylene, Benzene mixture using PACKMOL
==============
This example also shows how to use moltemplate in together with PACKMOL to create mixture of two small organic molecules using the *OPLSAA* force field.  [PACKMOL](http://m3g.iqm.unicamp.br/packmol/home.shtml) was used to generate the initial coordinates of the system.  PACKMOL is a useful program for generating atomic coordinates.  In this example, moltemplate.sh is only used to create the topology, force-field and charges, and PACKMOL generates the coordinates, which moltemplate reads (in "step 1").  Moltemplate can also be used for generating atomic coordinates, especially for mixing many small molecules together.  However I wanted to demonstrate how to combine PACKMOL with moltemplate.sh.  In some other scenarios, such as protein solvation, PACKMOL does a much better job than moltemplate.


#### Images
<img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/all_atom/legacy_force_field_examples/force_field_OPLSAA_2008/ethylene%2Bbenzene_PACKMOL/images/ethylene.jpg" width=110> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/all_atom/legacy_force_field_examples/force_field_OPLSAA_2008/ethylene%2Bbenzene_PACKMOL/images/plus.svg" height=80> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/all_atom/legacy_force_field_examples/force_field_OPLSAA_2008/ethylene%2Bbenzene_PACKMOL/images/benzene.jpg" width=110> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/all_atom/legacy_force_field_examples/force_field_OPLSAA_2008/ethylene%2Bbenzene_PACKMOL/images/rightarrow.svg" height=80> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/all_atom/legacy_force_field_examples/force_field_OPLSAA_2008/ethylene%2Bbenzene_PACKMOL/images/ethylene%2Bbenzene_box80x80x80_LR.jpg" width=200>

The simulation size and number of ethylene and benzene is specified in the [mix_ethylene+benzene.inp](https://github.com/jewettaij/moltemplate/blob/HEAD/examples/all_atom/legacy_force_field_examples/force_field_OPLSAA_2008/ethylene%2Bbenzene_PACKMOL/packmol_files/mix_ethylene%2Bbenzene.inp) and [system.lt](https://github.com/jewettaij/moltemplate/blob/HEAD/examples/all_atom/legacy_force_field_examples/force_field_OPLSAA_2008/ethylene%2Bbenzene_PACKMOL/moltemplate_files/system.lt) files.  (The numbers in these files must agree.)  The simulation contitions can be controlled by editing the [run.in.npt](https://github.com/jewettaij/moltemplate/blob/HEAD/examples/all_atom/legacy_force_field_examples/force_field_OPLSAA_2008/ethylene%2Bbenzene_PACKMOL/run.in.npt) file.

## Instructions

1) To build the files which LAMMPS needs, follow the instructions in:
[README_setup.sh](https://github.com/jewettaij/moltemplate/blob/HEAD/examples/all_atom/legacy_force_field_examples/force_field_OPLSAA_2008/ethylene%2Bbenzene_PACKMOL/README_setup.sh)

2) To run LAMMPS with these files, follow these instructions:
[README_run.sh](https://github.com/jewettaij/moltemplate/blob/HEAD/examples/all_atom/legacy_force_field_examples/force_field_OPLSAA_2008/ethylene%2Bbenzene_PACKMOL/README_run.sh)

(The instructions in "README_remove_irrelevant_info.sh" are optional.  *(If you notice a problem with this example, please [report it](https://github.com/jewettaij/moltemplate/blob/HEAD/examples/all_atom/legacy_force_field_examples/force_field_OPLSAA_2008/README.md).*)



### Customizing atomic charges

In this example, atomic charge for OPLSAA atoms is determined by @atom type
*(...according to a lookup table located at the beginning of the
["oplsaa2008.lt"](https://github.com/jewettaij/moltemplate/blob/HEAD/examples/all_atom/moltemplate/force_fields/oplsaa2008.lt) file)*.
*(Any atomic charges listed in the "Data Atoms" section of your molecules'
LT files will be ignored.)*
**These charges can be overridden.**
See [here](https://github.com/jewettaij/moltemplate/blob/HEAD/examples/all_atom/legacy_force_field_examples/force_field_OPLSAA_2008/README.md#Customizing-atomic-charges-in-OPLSAA-molecules)
for instructions explaining how to customize atomic charge.
