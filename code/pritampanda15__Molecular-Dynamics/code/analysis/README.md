# Trajectory Post-Processing & Analysis

Scripts, input templates, and command guides for analyzing GROMACS MD trajectories.

| Topic | Directory | Key Files |
| :--- | :--- | :--- |
| **Post-Processing & Trajectory Utilities** | [`post-processing/`](https://github.com/pritampanda15/Molecular-Dynamics/blob/HEAD/analysis/post-processing) | [`README.md`](https://github.com/pritampanda15/Molecular-Dynamics/blob/HEAD/analysis/post-processing/README.md) (PBC removal, centering, RMSD, snapshots, extending/restarting runs, batch shell helpers) |
| **PCA, Free Energy Landscape (FEL) & Entropy** | [`pca-fel-entropy/`](https://github.com/pritampanda15/Molecular-Dynamics/blob/HEAD/analysis/pca-fel-entropy) | [`run_pca_fel_windows.sh`](https://github.com/pritampanda15/Molecular-Dynamics/blob/HEAD/analysis/pca-fel-entropy/run_pca_fel_windows.sh), [`README.md`](https://github.com/pritampanda15/Molecular-Dynamics/blob/HEAD/analysis/pca-fel-entropy/README.md), [`PCA.pptx`](https://github.com/pritampanda15/Molecular-Dynamics/blob/HEAD/analysis/pca-fel-entropy/PCA.pptx) |
| **MM-PBSA / MM-GBSA Binding Free Energy** | [`mmpbsa-gbsa/`](https://github.com/pritampanda15/Molecular-Dynamics/blob/HEAD/analysis/mmpbsa-gbsa) | [`mmpbsa.in`](https://github.com/pritampanda15/Molecular-Dynamics/blob/HEAD/analysis/mmpbsa-gbsa/mmpbsa.in), [`env.yml`](https://github.com/pritampanda15/Molecular-Dynamics/blob/HEAD/analysis/mmpbsa-gbsa/env.yml), [`README.md`](https://github.com/pritampanda15/Molecular-Dynamics/blob/HEAD/analysis/mmpbsa-gbsa/README.md), [`example-results/`](https://github.com/pritampanda15/Molecular-Dynamics/blob/HEAD/analysis/mmpbsa-gbsa/example-results) |

For running post-processing across many simulation directories at once, see [`../hpc/batch_postprocess.sh`](https://github.com/pritampanda15/Molecular-Dynamics/blob/HEAD/hpc/batch_postprocess.sh).
