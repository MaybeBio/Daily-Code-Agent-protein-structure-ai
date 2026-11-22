# Analysis scripts of version 2.0.1

All numbers of the manuscript are re-derived with these scripts from the raw trajectories (not included, size), the gmx_MMPBSA output and the docking outputs.
Environment: Python 3.10, MDAnalysis 2.9.0, NumPy 1.26.4, SciPy 1.14.1, Matplotlib 3.7.3, RDKit 2024.03.5, gmx_MMPBSA 1.6.5, GROMACS 2020.1.

| script | purpose |
|---|---|
| `tp53_checks.py` | self-test; minimum-image ligand-site distances, contacts, pose similarity (`md`); MM-PBSA/interaction entropy (`ie`) |
| `check_top_vs_tpr.py` | atom-by-atom comparison of a topology (.itp/.top) with a .tpr (names, charges, masses, atom types) |
| `audit_setup.py`, `audit_runs.sh`, `audit_runs2.sh` | set-up of the simulations (box, ions, thermostat groups, velocities, run length) from the .tpr/.mdp/.log files |
| `audit_md_metrics.py` | backbone RMSD, Rg, Calpha RMSF, DSSP, Zn2+ coordination (minimum image) |
| `audit_docking.py` | docking poses: clusters, contacts, closest approach to Cys124/Cys277, comparison of two runs |
| `audit_cluster_hbond.py` | GROMOS clustering (all atom sets) and ligand-protein hydrogen bonds |
| `run_mmpbsa_validate.sh`, `run_decomp_quick.sh`, `run_decomp.sh`, `analyze_decomp.py` | MM-PBSA re-run with the 3010-atom topology; per-residue decomposition (Delta) |
| `make_revised_figures.py` | Figures 1-8 and Tables 1-3 of the manuscript |
| `check_stage_structures.py`, `check_cs_bond.py` | ligand-site distance and Zn2+ coordination in stage structures; C-S bond length of the MQ-methanethiol adduct |
