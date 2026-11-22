# Changelog

## [2.0.1] - 2026-11-20

Corrections after a post-submission re-analysis of version 2.0.0 (all results re-derived from the raw data; scripts in `analysis_v2/`).

### Corrected
- **Interaction entropy**: version 2.0.0 reported -TdS = -3.87 and dG_eff = -14.90 kcal/mol. These were produced by `interaction_entropy_from_csv.py`
  (now in `legacy/`), which used the wrong sign (-kT ln<exp(+dE/kT)>, always <= 0) and the total dG instead of the gas-phase interaction energy.
  Correct (last 25% of the frames): -TdS = +10.72 kcal/mol (95% bootstrap interval +6.6 to +12.0), dG_eff = -0.31 kcal/mol (-4.5 to +0.8); all 201 frames:
  +13.71 and +3.00 kcal/mol. No net favorable binding free energy.
- **Per-residue decomposition**: the previous values (e.g. Asn268 -81.00 kcal/mol) were complex-only residue energies, not ligand contributions. Redone as
  Delta = complex - receptor - ligand (201 frames): the ligand contributes -5.61 kcal/mol and no residue more than 0.6 kcal/mol; Asn239 never contacts the ligand.
- **Ligand-site distances** recomputed with the minimum-image convention (previous values exceeded the largest possible distance in the box).
- **Hydrogen bonds**: ligand-protein bonds only (the previous definition also counted ligand-water and intramolecular bonds).
- **Docking cross-check**: Vina 1.1.2 and 1.2.5 share the same default scoring function (agreement = software reproducibility only). The independent
  Vinardo scoring function did not reproduce the site. The site is about 1.4 nm from Cys124 and is not the L1/S3 pocket.
- **Zn2+**: minimum-image distances for all five simulations; His179 coordinates through Nd1; the ion never returned to its site.
- **Quinuclidine simulation** re-described as exploratory: protein topology with 2999 atoms (11 atoms of Leu289 missing, net charge +4.017 e), six Cl-, 14,381 waters,
  ligand coupled to the solvent thermostat group.
- **Methods details** from the .tpr/.mdp/.log files: velocity generation, thermostat groups, run lengths, restarts, GROMACS versions (quinuclidine: 2020.1; Replicate 4: 2018.1).
- README: GROMACS 2018.1 was used for Replicate 4 only (not for the quinuclidine simulation).

### Verified unchanged
- PRIMA-1 protein topology (3010 atoms) and ligand topology match the .tpr files atom by atom; MM-PBSA terms (dG = -10.71 +- 2.77 kcal/mol) were reproduced.

### Added
- `analysis_v2/`, `mmpbsa/`, `results/`, `mdp/`, `topology/quinuclidine_exploratory/`, `legacy/`; `scripts/cross_validation/docking_vinardo.sh`; `CITATION.cff`.

## [2.0.0] - 2026-09 (SUPERSEDED: several numbers below are corrected in 2.0.1)
Following a desk rejection from JBSD (concerns: depth of analysis, novelty,
rationale clarity), the following additional analyses and fixes were made.

### Fixed
- **Protein topology (Leu289 truncation)**: `topology/topol_Protein_chain_A.itp`
  was found to be missing 11 atoms (CD1/CD2 side chain + backbone C/O) of the
  C-terminal residue Leu289, apparently truncated during unrelated covalent-
  adduct exploration. Rebuilt and atom-count-verified (194 residues, 3010
  atoms) directly from `structures/2OCJ_chainA_clean.pdb`
  (see `scripts/topology_rebuild/`). This truncation affected only auxiliary
  MM-PBSA/decomposition post-processing on Run1's already-completed
  trajectory, not the trajectories themselves (Run1-3 production used a
  correctly-built system, as independently confirmed from `md.tpr`).

### Added
- **Interaction Entropy** (Duan et al. 2016) computed for Run1's MM-PBSA
  trajectory: -T*dS = -3.87 kcal/mol; dG_eff (dH + IE) = -14.90 kcal/mol
  (see `scripts/mmpbsa_extra/interaction_entropy_from_csv.py`).
- **Per-residue MM-PBSA decomposition** for Run1, identifying Thr102,
  Gln104, Asn131, Asn268, Tyr126, and Leu111 as the principal favorable
  contributors, consistent with the blind-docking pocket
  (see `scripts/mmpbsa_extra/parse_decomp_from_mdout.py`).
- **DSSP secondary-structure analysis** across all three PRIMA-1 replicates:
  stable fold composition (~58-60% coil, ~33-35% beta-sheet, ~6.5-7% helix)
  independent of ligand retention/dissociation.
- **Structural Zn2+ coordination analysis**: the nonbonded Zn2+ ion is found
  to leave its crystallographic coordination site (Cys176/His179/Cys238/
  Cys242) within ~10 ps of NVT equilibration in all three replicates,
  settling into a standard 6-coordinate aqua complex by production
  (see `scripts/zn_analysis/`). This is a known limitation of nonbonded,
  non-polarizable Zn2+ force-field models and is documented as such in the
  revised manuscript's Limitations section; it is independent of and does
  not affect the PRIMA-1 replicate-dependence finding.
- **Negative-control simulation** (quinuclidine, the PRIMA-1 scaffold
  without its hydroxymethyl/ketone substituents): full docking-to-20ns-MD
  pipeline, run independently to test whether pocket dissociation is
  PRIMA-1-specific (see `scripts/negative_control/`).
- **Run4**: a fourth independent 20-ns PRIMA-1 replicate, to strengthen the
  replicate-dependence statistics beyond the original three runs.
- **Cross-engine docking validation**: blind docking repeated with an
  independent AutoDock Vina version (1.1.2, 2011 scoring function) on a
  separate machine, cross-validating the L1/S3 pocket identified with Vina
  1.2.5 (see `scripts/cross_validation/`). Top pose affinity matched exactly
  (-4.50 kcal/mol); 9/9 primary pocket residues independently recovered.

### Reorganized
- Scripts and structures from an abandoned covalent MQ-Cys124 MD attempt
  (not part of the reported results) moved to `archive/covalent_exploration/`
  for transparency, kept out of the main reproducible pipeline.
