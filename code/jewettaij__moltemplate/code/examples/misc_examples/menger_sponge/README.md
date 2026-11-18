Menger sponge (aluminum) example
================================

Moltemplate is useful for building larger molecular structures from smaller pieces.  The purpose of this example is to show how to build large (many-level) heirarchical objects (a Menger sponge) using moltemplate.  A Menger sponge is a fractal composed of subunits that resemble a Rubik's-cubes with a hollow interior.  The smallest cube subunits consist of 4 atoms of Aluminum (arranged in a cubic FCC unit-cell for bulk Aluminum).

### Images

<img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/misc_examples/menger_sponge/images/AlCell_LR.jpg" width=70> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/misc_examples/menger_sponge/images/rightarrow.svg" height=80> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/misc_examples/menger_sponge/images/lvl1_LR.jpg" width=90> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/misc_examples/menger_sponge/images/rightarrow.svg" height=80> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/misc_examples/menger_sponge/images/lvl2_LR.jpg" width=130> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/misc_examples/menger_sponge/images/rightarrow.svg" height=80> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/misc_examples/menger_sponge/images/lvl3_LR.jpg" width=200>
<img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/misc_examples/menger_sponge/images/rightarrow.svg" height=80> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/misc_examples/menger_sponge/images/menger_sponge_lattice_8cells_t%3D0_zoom1_LR2.jpg" width=300>

### Video

A short simulation demonstrates that the resulting construct is not stable.

https://www.youtube.com/watch?v=DfuMBN0OwKc

<img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/misc_examples/menger_sponge/images/rightarrow.svg" height=80> <img src="https://github.com/jewettaij/moltemplate/raw/HEAD/examples/misc_examples/menger_sponge/images/menger_sponge_lattice_8cells_t%3D7400_LR.jpg" width=300>


### Instructions

More detailed instructions on how to build LAMMPS input files and
run a short simulation are provided in other README files.

1) To build the files which LAMMPS needs, follow the instructions in:
[README_setup.sh](https://github.com/jewettaij/moltemplate/blob/HEAD/examples/misc_examples/menger_sponge/README_setup.sh)

2) To run LAMMPS with these files, follow these instructions:
[README_run.sh](https://github.com/jewettaij/moltemplate/blob/HEAD/examples/misc_examples/menger_sponge/README_run.sh)


### Requirements
This example requires the "Al99.eam.alloy" file.  (It was not included in this directory because if its large size.) As of 2012-11, I was able to obtain it [here](http://www.ctcms.nist.gov/~cbecker/Download/Al-YM/Al99.eam.alloy). Copy it to the directory containing this README file.


