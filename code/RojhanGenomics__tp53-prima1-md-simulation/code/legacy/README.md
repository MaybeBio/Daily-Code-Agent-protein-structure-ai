# Superseded scripts (kept for transparency)

These scripts produced numbers of version 2.0.0 that were found to be wrong or ill-defined during a post-submission re-analysis.
They are **not** part of the reproducible pipeline of version 2.0.1; use the scripts in `analysis_v2/` instead.

| file | problem | replacement |
|---|---|---|
| `analyze_ligand_distance.py`, `analyze_ligand_location.py` | distances without the minimum-image convention (values above the largest possible distance in the box) | `analysis_v2/tp53_checks.py md` |
| `analyze_hbonds.py` | MDAnalysis `guess_*` selections assigned after the object was built; every bond with the ligand as donor or acceptor was counted, including ligand-water and intramolecular bonds (77% of the frames of Replicate 3 instead of 51% for ligand-protein bonds) | `analysis_v2/audit_cluster_hbond.py` |
| `analyze_clustering.py` | not the source of the reported cluster numbers (those came from `gmx cluster` on all protein heavy atoms, mass-weighted) | `analysis_v2/audit_cluster_hbond.py --atoms heavy --mass-weighted` |
| `mmpbsa_extra/interaction_entropy_from_csv.py` | wrong sign: `-kT ln<exp(+dE/kT)>` is always <= 0; the total dG was used instead of the gas-phase interaction energy (vdW + electrostatics). It produced -TdS = -3.87 and dG_eff = -14.90 kcal/mol | `analysis_v2/tp53_checks.py ie` (-TdS = +10.72 kcal/mol, dG_eff = -0.31 kcal/mol, last 25% of the frames) |
| `mmpbsa_extra/parse_decomp_from_mdout.py` | sums the complex-only TDC energies of each residue and drops the ligand: these are total residue energies in the complex, not binding contributions | `analysis_v2/run_decomp.sh` and `analyze_decomp.py` (Delta = complex - receptor - ligand) |
| `zn_analysis/analyze_zn_coordination.py` | final distances not reproduced with the minimum-image convention | `analysis_v2/audit_md_metrics.py` |
