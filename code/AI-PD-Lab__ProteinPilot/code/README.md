# ProteinPilot

A browser-based graphical interface for adjacency-conditioned protein design with RFdiffusion, RFdiffusion3 and
RFdiffusion4.

[![Open app](https://img.shields.io/badge/Open-ProteinPilot-2ea44f)](https://ai-pd-lab.github.io/ProteinPilot/)
[![Hugging Face Space](https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-Space-yellow)](https://huggingface.co/spaces/AI-PD/ProteinPilot)
[![HARMONIA](https://img.shields.io/badge/GitHub-HARMONIA-181717?logo=github)](https://github.com/AI-PD-Lab/HARMONIA)
[![License: PolyForm Noncommercial 1.0.0](https://img.shields.io/badge/License-PolyForm%20Noncommercial%201.0.0-blue)](LICENSE)

**[Open ProteinPilot](https://ai-pd-lab.github.io/ProteinPilot/)** · no installation, runs in any modern browser


**Draw a protein topology and get ready-to-run adjacency-conditioning inputs for RFdiffusion, RFdiffusion3 and RFdiffusion4.**

## Overview

ProteinPilot is a browser-based graphical interface for adjacency-conditioned protein design. You draw the topology of a protein, and ProteinPilot writes the matching conditioning inputs, contig and run script. Imported structures, fixed motifs and binder interfaces are supported.

Together with ProteinPilot we release HARMONIA, adjacency-conditioned weights for RFdiffusion3 and RFdiffusion4. They recover drawn topologies more consistently than the original RFdiffusion, run faster and open up new conditioning modes such as loop contacts, ligands and nucleic acids.

ProteinPilot is a single self-contained HTML file. It runs entirely in your browser, and nothing you draw or import is uploaded.

## Why ProteinPilot?

Adjacency conditioning describes a fold by its topology. It states which secondary-structure elements a protein contains and which of them are in contact, without fixing their geometry. RFdiffusion reads this as two residue-indexed inputs, a secondary-structure vector and an adjacency matrix. Writing these by hand is slow and error-prone, and the published helper script can only derive them from existing structures.

With ProteinPilot you draw helices, strands and loops instead, connect them and mark which elements touch. The adjacency map shown in the app is built from the same arrays that are exported, so what you see is exactly what the model reads.

## Features

- Draw topologies from helices, strands, loops and masked blocks
- Import a structure as a binding target or as a template to edit
- Use length ranges to generate a series of related variants from one drawing
- Specify contacts made by loops (RFdiffusion3 and RFdiffusion4)
- Fix single residues and ligands of an imported structure (RFdiffusion3) or keep motifs in place (RFdiffusion4)
- Design several new chains in a single run
- Export the conditioning inputs, contig and run script for RFdiffusion, RFdiffusion3 and RFdiffusion4
- Save and reopen projects

## Supported engines

| Engine | Model | Exported files |
|---|---|---|
| **RFD4** (default) | RFdiffusion4 (RFD4-Proteina, flow matching) with the HARMONIA-RFD4 adjacency checkpoint | annotated `.cif`, `.adj.npy`, `.ss.npy`, run script |
| **RFD3** | RFdiffusion3 with the HARMONIA adjacency checkpoint | input `.json`, `ss.pt`, `adj.pt`, run script |
| **RFD1** | [RFdiffusion](https://github.com/RosettaCommons/RFdiffusion), scaffold-guided mode | `_ss.pt`, `_adj.pt`, run script |

All three engines use the same secondary-structure and adjacency definition (contact = any Cβ–Cβ pair within
6 Å), so one drawing can be compared across models. The RFdiffusion3/4 adjacency code (HARMONIA) is at
[github.com/AI-PD-Lab/HARMONIA](https://github.com/AI-PD-Lab/HARMONIA), and the HARMONIA checkpoints are at
[huggingface.co/buckets/AI-PD/Harmonia](https://huggingface.co/buckets/AI-PD/Harmonia).

## Quick start

1. Open ProteinPilot in a browser.
2. Place secondary-structure elements from the toolbox and connect them with loops.
3. Optionally import a target structure.
4. Draw contacts between elements with the Adj tool.
5. Choose the engine and sampling settings in the Flags panel.
6. Click Download → Download all (.zip).

The zip unpacks to a run folder, for example for RFdiffusion4:

```
<name>_rfd4/
  <name>.cif        annotated CIF: structure + per-residue conditions
  <name>.adj.npy    block-adjacency map [L, L]
  <name>.ss.npy     secondary structure [L]
  <name>_rfd4.sh    run script
```

```bash
cd <name>_rfd4
sbatch <name>_rfd4.sh      # SLURM build; plain-bash build: bash <name>_rfd4.sh
```

Results are written to `outputs/` in the run folder. For RFdiffusion, pass the folder holding the tensors as
`--scaffoldguided.scaffold_dir`.

ProteinPilot itself only needs a browser. Running the exports needs the chosen model installed on a GPU
machine; set its paths under **Flags → Environment** before downloading.

## Results in brief

On a benchmark of 49 conditions covering fold conditioning, motif scaffolding, binder interfaces and loop,
ligand and nucleic-acid contacts, all exported from ProteinPilot drawings:
- RFdiffusion4 formed drawn loop contacts far more often than RFdiffusion3 (about 79 % vs 28 % mean recovery).
- RFdiffusion3 and RFdiffusion4 needed less sampling time per design than RFdiffusion.

## References

ProteinPilot's molecular structure viewers use Mol\*:

- Sehnal, D. et al. Mol\* Viewer: modern web app for 3D visualization and analysis of large biomolecular
  structures. *Nucleic Acids Res.* **49**, W431–W437 (2021). https://doi.org/10.1093/nar/gkab314

ProteinPilot writes inputs for the following models:

- **RFdiffusion:** Watson, J. L. et al. De novo design of protein structure and function with RFdiffusion.
  *Nature* **620**, 1089–1100 (2023). https://doi.org/10.1038/s41586-023-06415-8
- **RFdiffusion3:** Butcher, J. et al. Atomic functional site scaffolding in biopolymers with RFdiffusion3.
  *Science* eaeh2982 (2026). https://doi.org/10.1126/science.aeh2982
- **RFdiffusion4:** Corley, N. et al. Biomolecular design through latent reasoning with RFD4-Proteina.
  *bioRxiv* (2026). https://doi.org/10.64898/2026.11.12.766037

## Third-party software

ProteinPilot bundles the following libraries, each under its own licence (see [THIRD_PARTY_LICENSES](https://github.com/AI-PD-Lab/ProteinPilot/blob/HEAD/THIRD_PARTY_LICENSES)):
- [Mol*](https://molstar.org) (MIT) for the molecular viewers
- [three.js](https://threejs.org) (MIT) for the schematic 3D preview
- [JSZip](https://stuk.github.io/jszip/) (MIT) for the PyTorch archives and run-folder downloads

These components remain under their original licences. The PolyForm Noncommercial licence applies only to ProteinPilot's own code.

## License

[PolyForm Noncommercial License 1.0.0](https://github.com/AI-PD-Lab/ProteinPilot/blob/HEAD/LICENSE)
