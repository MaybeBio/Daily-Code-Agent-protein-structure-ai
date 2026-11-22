The VES code is a module for PLUMED that implements enhanced sampling methods
based on _Variationally Enhanced Sampling_ (VES) (see paper cited below).
The VES code is developed by [Omar Valsson](http://www.valsson.info), 
see the [homepage of the VES code](http://www.ves-code.org) for further information.

The VES code is an optional module that needs to be enabled when configuring the
compilation of PLUMED by using the `--enable-modules=ves` 
(or `--enable-modules=all`) flag when running the 'configure' script. 

## Overview

In VES the bias potential is obtained by minimizing a convex functional, and the module is organized around the building blocks of this minimization.
These building blocks can be found by selecting the corresponding tag in the dropdown on this page:

- __VES_BIAS__: the bias potentials, e.g. [VES_LINEAR_EXPANSION](https://github.com/plumed/plumed2/blob/HEAD/src/ves/VES_LINEAR_EXPANSION.md), where the bias is written as a linear combination of basis functions whose coefficients are optimized.
- __VES_BASISF__: one-dimensional basis functions used in the expansion, e.g. [BF_FOURIER](https://github.com/plumed/plumed2/blob/HEAD/src/ves/BF_FOURIER.md), [BF_LEGENDRE](https://github.com/plumed/plumed2/blob/HEAD/src/ves/BF_LEGENDRE.md) or [BF_CHEBYSHEV](https://github.com/plumed/plumed2/blob/HEAD/src/ves/BF_CHEBYSHEV.md).
- __VES_TARGETDIST__: the target distribution that the sampled CV distribution should converge to, e.g. [TD_UNIFORM](https://github.com/plumed/plumed2/blob/HEAD/src/ves/TD_UNIFORM.md) or [TD_WELLTEMPERED](https://github.com/plumed/plumed2/blob/HEAD/src/ves/TD_WELLTEMPERED.md).
- __VES_OPTIMIZER__: the algorithm that updates the coefficients, e.g. [OPT_AVERAGED_SGD](https://github.com/plumed/plumed2/blob/HEAD/src/ves/OPT_AVERAGED_SGD.md), which is the recommended choice.
- __VES_UTILS__: tools for analysis and post-processing, e.g. [VES_OUTPUT_BASISFUNCTIONS](https://github.com/plumed/plumed2/blob/HEAD/src/ves/VES_OUTPUT_BASISFUNCTIONS.md).

A typical input defines one or more basis functions, a [VES_LINEAR_EXPANSION](https://github.com/plumed/plumed2/blob/HEAD/src/ves/VES_LINEAR_EXPANSION.md) bias that uses them (optionally with a target distribution) and an optimizer, as in the example on the [OPT_AVERAGED_SGD](https://github.com/plumed/plumed2/blob/HEAD/src/ves/OPT_AVERAGED_SGD.md) page.
