# BioEmu2 on Colab

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/CSB-KaracaLab/bioemu2-colab/blob/main/BioEmu2_Colab.ipynb)

A single notebook that runs [BioEmu2](https://github.com/microsoft/bioemu2), Microsoft Research's biomolecular emulator, on a Google Colab GPU. The code follows the usage examples in the BioEmu2 repository; this notebook turns them into a Colab form with input fields, plots and a download step, so that the model can be tried without a local GPU or a local installation.

## What it does

The notebook walks through the three things BioEmu2 was trained for:

1. **Structure prediction** — one sharp, most likely structure.
2. **Equilibrium sampling** — an ensemble of independent conformations, filtered by BioEmu2's physicality checks.
3. **Time propagation** — chains of time-lagged endpoints (1 ns to 1 µs per step), a coarse picture of how the system moves.

It also plots the Cα RMSD to the predicted structure and the radius of gyration over the ensemble, shows the structures in the browser with py3Dmol, and packs everything into a zip file at the end. Each output folder holds `topology.cif` and `samples.xtc`, which open in PyMOL, ChimeraX or VMD, or load with MDTraj; `equilibrium/physicality.json` records which samples failed the checks and why.

## How to use it

Open the notebook in Colab with the badge above, set **Runtime → Change runtime type → GPU**, and run the cells from top to bottom. A free T4 works for small proteins; an L4 or A100 is better for complexes. The install takes about three minutes and the weights are downloaded from Hugging Face on first use.

The system is defined either by a **PDB ID** or by **sequences** separated by `:`, with optional ligands by CCD code or SMILES. By default the multiple sequence alignment is built on the public ColabFold MMseqs2 server, which means the sequence you enter is sent to that service; you can upload your own A3M file instead.

## What to keep in mind

BioEmu2 is research software, and its model card is explicit that it is released for research purposes rather than for commercial or real-world applications without further testing. Two consequences are worth repeating here:

- The frequencies with which conformations appear are **not calibrated Boltzmann probabilities**, and there is no confidence score of the pLDDT or PAE kind.
- In the time-propagation mode, each step is an **independent endpoint** at the chosen lag, not a frame of a continuous trajectory.

Generated structures are computational hypotheses and should be validated before they inform anything downstream.

## The example and its MD reference
The notebook's example is a complex, HPr kinase with HPr ([1KKL](https://www.rcsb.org/structure/1KKL)): three copies of the kinase plus one HPr, 614 residues. A single protein is what BioEmu2's own [examples](https://github.com/microsoft/bioemu2/tree/main/examples) already show, so this notebook spends its example on the case that is harder and more interesting, a protein-protein interface.

Section 8 then asks whether that interface is *consistent* across the ensemble, rather than only showing it: an ensemble can have contact in every sample and still be telling you nothing, if the chains meet somewhere different each time. It also draws the ensemble next to molecular dynamics of the same complex, 21 frames from the [DynaBench](https://doi.org/10.1016/j.jmb.2026.169650) dataset of three 100 ns replicas per complex of Docking Benchmark 5.5. Those frames live in `md_reference/` and are **not** covered by the MIT licence of this repository; if you use them, cite Barlas AB, Laurent B, Karaca E, Prévost C, Sacquin-Mora S, *DynaBench: Dynamic data for the docking benchmark*, Journal of Molecular Biology 438 (2026) 169650, [doi:10.1016/j.jmb.2026.169650](https://doi.org/10.1016/j.jmb.2026.169650). The full trajectories are at [www-lbt.ibpc.fr/DynaBench](http://www-lbt.ibpc.fr/DynaBench).

## Credits and licence

BioEmu2 is developed by Microsoft Research and released under the MIT licence; its weights are published under the MIT licence on [Hugging Face](https://huggingface.co/microsoft/bioemu2). This repository contains neither: the notebook installs BioEmu2 from its own GitHub repository (pinned to commit `6d1ca74`, 3 November 2026) and downloads the weights at run time.

Portions of the notebook are adapted from the examples in microsoft/bioemu2, which carry the following notice, repeated in [NOTICE](https://github.com/CSB-KaracaLab/bioemu2-colab/blob/HEAD/NOTICE):

> Copyright (c) Microsoft Corporation. Licensed under the MIT License.

The notebook itself is released under the MIT licence, see [LICENSE](https://github.com/CSB-KaracaLab/bioemu2-colab/blob/HEAD/LICENSE).

Please cite BioEmu2 as its [repository](https://github.com/microsoft/bioemu2) and [model card](https://huggingface.co/microsoft/bioemu2) ask, not this notebook.

---

Maintained by the [Computational Structural Biology Lab](https://csb-karacalab.github.io/), Izmir Biomedicine and Genome Center.
