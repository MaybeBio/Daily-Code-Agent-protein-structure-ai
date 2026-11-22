# TP53–PRIMA-1 molecular dynamics simulation

Scripts, structures, topology files, simulation parameters and analysis results for a computational study of PRIMA-1 and the p53 DNA-binding domain
(PDB 2OCJ, chain A) with an open-source docking-to-molecular-dynamics pipeline (AutoDock Vina, GROMACS, AmberTools, RDKit, MDAnalysis).

> **Version 2.0.1** corrects numerical and methodological errors of version 2.0.0 that were found in a post-submission re-analysis
> (interaction entropy, per-residue decomposition, ligand-site distances, hydrogen bonds, the docking cross-check, and the descriptions of the
> quinuclidine simulation and of the structural Zn²⁺ ion). All numbers of the manuscript are re-derived with the scripts in `analysis_v2/`.
> See `CHANGELOG.md`. Superseded scripts are kept in `legacy/` with a description of their problems.

Manuscript: *Replicate-Dependent Retention of PRIMA-1 at a Surface Site of the p53 DNA-Binding Domain: Insights from Four Independent Molecular
Dynamics Replicates and an Exploratory Quinuclidine Simulation* (submitted to Scientific Reports).

## Contents

| folder | content |
|---|---|
| `structures/` | PDB structures (receptor, ligand, docked poses) |
| `topology/` | GROMACS topology of the PRIMA-1 systems (protein: 194 residues, 3010 atoms, net charge +3.000 e; verified against the .tpr files) |
| `topology/quinuclidine_exploratory/` | topology files of the exploratory quinuclidine simulation. **The protein topology there is incomplete (2999 atoms; 11 atoms of Leu289 missing; net charge +4.017 e)** and is provided for transparency only |
| `mdp/` | simulation parameters (.mdp) and the parameters stored in each .tpr (`mdp/tpr_parameters/`) |
| `scripts/` | protein/ligand preparation, docking-box calculation, topology and index utilities, RMSD/Rg/RMSF scripts |
| `scripts/cross_validation/` | docking cross-checks (Vina 1.1.2; Vinardo scoring function) |
| `analysis_v2/` | analysis scripts of version 2.0.1 (see `analysis_v2/README.md`) |
| `mmpbsa/` | gmx_MMPBSA input, the 3010-atom wrapper topology, index file, per-frame energies, per-residue decomposition |
| `results/` | analysis outputs (CSV, text reports), docking outputs, revised figures and tables |
| `legacy/` | superseded scripts of version 2.0.0 with their known problems |
| `archive/covalent_exploration/` | files of an abandoned covalent MQ–Cys124 modeling attempt (not part of the reported results) |

## Simulations

| | Replicate 1 | Replicate 2 | Replicate 3 | Replicate 4 | Quinuclidine (exploratory) |
|---|---|---|---|---|---|
| GROMACS | 2020.1 | 2020.1 | 2020.1 | 2018.1 | 2020.1 |
| start of production | continuation from NPT (velocities kept) | new velocities | new velocities | new velocities | continuation from NPT |
| analyzed length | 20 ns | 20 ns | 20 ns | 20 ns | 20 ns |
| ligand thermostat group | with protein and Zn²⁺ | with protein and Zn²⁺ | with protein and Zn²⁺ | with solvent | with solvent |

Trajectories are not included (size); they are available on request.

## Software

GROMACS 2020.1 and 2018.1; AutoDock Vina 1.2.5 (primary docking) and 1.1.2 (cross-check); AmberTools 23.6 (antechamber, parmchk2, tleap), ACPYPE 2023.10.27;
RDKit 2024.03.5; MDAnalysis 2.9.0; gmx_MMPBSA 1.6.5; Open Babel 3.1.1; Meeko 0.7.1; PyMOL 1.8.4.0.

## Known limitations

The structural Zn²⁺ ion is a non-bonded ion and leaves its site in all simulations; the three coordinating cysteines are neutral thiols. The
quinuclidine simulation is not a matched control (incomplete protein topology, different thermostat group, one trajectory). Run 1–3 were stopped
at about 20 ns although set up for 50 ns. See the manuscript (Limitations).

## Data availability

A permanently archived, citable snapshot of each version is available on Zenodo (v1.0.0: https://doi.org/10.5281/zenodo.21835098;
v2.0.0: https://doi.org/10.5281/zenodo.22330272; v2.0.1: DOI assigned by Zenodo at release, see the repository's Zenodo badge/record).

Repository: https://github.com/RojhanGenomics/tp53-prima1-md-simulation
