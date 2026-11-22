# Simulation Workflows

End-to-end molecular dynamics setup guides, input bundles, and run scripts organized by system type.

| System Type | Directory | Force Field / Engine | Key Files |
| :--- | :--- | :--- | :--- |
| **Protein in Water** | [`protein-only/`](https://github.com/pritampanda15/Molecular-Dynamics/blob/HEAD/workflows/protein-only) | OPLS-AA / GROMACS | [`run_protein_md.sh`](https://github.com/pritampanda15/Molecular-Dynamics/blob/HEAD/workflows/protein-only/run_protein_md.sh) |
| **Protein–Ligand Complex** | [`protein-ligand/`](https://github.com/pritampanda15/Molecular-Dynamics/blob/HEAD/workflows/protein-ligand) | GROMOS96 (ATB/PRODRG) & CHARMM36 (CGenFF) / GROMACS | [`gromos_protein_ligand_guide.md`](https://github.com/pritampanda15/Molecular-Dynamics/blob/HEAD/workflows/protein-ligand/gromos_protein_ligand_guide.md), [`charmm_tetralith_guide.md`](https://github.com/pritampanda15/Molecular-Dynamics/blob/HEAD/workflows/protein-ligand/charmm_tetralith_guide.md), [`charmm_random_ligand_insertion.md`](https://github.com/pritampanda15/Molecular-Dynamics/blob/HEAD/workflows/protein-ligand/charmm_random_ligand_insertion.md) |
| **Lipid Bilayer / Membrane** | [`lipid-bilayer/`](https://github.com/pritampanda15/Molecular-Dynamics/blob/HEAD/workflows/lipid-bilayer) | CHARMM36 (CHARMM-GUI) & InflateGRO / GROMACS | [`run_lipid_bilayer_slurm.sh`](https://github.com/pritampanda15/Molecular-Dynamics/blob/HEAD/workflows/lipid-bilayer/run_lipid_bilayer_slurm.sh), [`inflategro_membrane_protein.md`](https://github.com/pritampanda15/Molecular-Dynamics/blob/HEAD/workflows/lipid-bilayer/inflategro_membrane_protein.md), full CHARMM-GUI inputs |
| **Nanomaterials & 2D Layers** | [`nanomaterials/`](https://github.com/pritampanda15/Molecular-Dynamics/blob/HEAD/workflows/nanomaterials) | CHARMM36 / GROMACS & ASE / LAMMPS | [`charmm_nanomaterials_guide.md`](https://github.com/pritampanda15/Molecular-Dynamics/blob/HEAD/workflows/nanomaterials/charmm_nanomaterials_guide.md), [`build_fluid_on_layer.py`](https://github.com/pritampanda15/Molecular-Dynamics/blob/HEAD/workflows/nanomaterials/build_fluid_on_layer.py), [`build_fluid_on_layer.ipynb`](https://github.com/pritampanda15/Molecular-Dynamics/blob/HEAD/workflows/nanomaterials/build_fluid_on_layer.ipynb) |

See also:
- [`../hpc/`](https://github.com/pritampanda15/Molecular-Dynamics/blob/HEAD/hpc) for reusable SLURM job scripts and batch post-processing.
- [`../analysis/`](https://github.com/pritampanda15/Molecular-Dynamics/blob/HEAD/analysis) for trajectory post-processing, PCA/FEL, entropy, and MM-PBSA/GBSA binding free energy.
