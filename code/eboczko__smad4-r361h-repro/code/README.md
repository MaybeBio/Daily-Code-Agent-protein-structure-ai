# SMAD4(R361H)–SMAD3 restoration — reproducibility deposit (v1: protein systems)

Input files, force field, and run settings to reproduce the molecular-dynamics
systems behind *"In-silico repurposing of FDA-approved drugs to restore the
SMAD4(R361H)–SMAD3 tumor-suppressor complex."*

This v1 covers the **protein (apo) systems** — the wild-type and R361H mutant
SMAD3–SMAD4 heterotrimer MD. Ligand parameterization, docking, and holo/apo
MM/GBSA (Parts C–E of the protocol) will be added in v2.

Large trajectories (`.xtc`, ~7 GB each) are **not** in this repo; they are
deposited separately on Zenodo (DOI: `<add on upload>`).

## What's here

```
forcefield/charmm36-sp2local.ff/   CHARMM36 (Jul-2022) + CGenFF 4.6 GROMACS port,
                                   with the dianionic phosphoserine residue SP2
                                   registered locally. Drop this in the working dir.
charmm2gmx.in                      Reconstructed recipe used to build that force field
                                   (see header; original not retained — rebuilt from
                                   forcefield.doc).
inputs/                            1U7F_original.pdb (the crystal) + the cleaned,
                                   chain-split PDBs fed to pdb2gmx (WT and R361H).
topology/{wt,mut}/                 pdb2gmx output: chain_*.itp, topol.top, complex.pdb,
                                   residuetypes.dat, and the pdb2gmx preparation logs
                                   (record the HSE/terminus/charge assignments).
mdp/{wt,mut}/                      The actual simulation parameter files:
                                   em, ions, nvt, npt, npt_weak, npt_free, md_100ns.
scripts/                           The build/run scripts: prepare_topologies.sh,
                                   run_{initial_em,nvt,npt,npt_weak}.sh,
                                   prepare_production_100ns.sh, meeko_serine_wrapper.py.
frame/                             Mutant snapshots used downstream (incl. the 160 ns
                                   docking receptor frame) + snapshot_centers.csv.
pocket/                            fpocket S2 ranking + the pocket report.
```

## The pipeline (rough path)

The full assume-nothing protocol lives in the project doc *"SMAD4(R361H) system
preparation — step-by-step protocol."* In brief:

1. **Structure.** Start from PDB **1U7F** (2.60 Å phosphorylated SMAD3–SMAD4
   heterotrimer; chains A/C = SMAD3, B = SMAD4). Clean; keep the crystallographic
   phosphoserines (`SEP` at Ser423/425 on each SMAD3 chain).
2. **Mutation.** R361H introduced in SMAD4 (chain B) with the PyMOL mutagenesis
   wizard; wild-type kept as the matched control. Identical coordinates except
   residue 361.
3. **Force field.** `charmm36-sp2local.ff` — stock CHARMM36 (Jul-2022) + CGenFF 4.6
   via awacha `charmm2gmx`, with the dianionic phosphoserine `SP2`
   (from `toppar_all36_prot_na_combined.str`; phospho params: Feng et al.,
   *JACS* 1996). `pdb2gmx` types the crystal `SEP` as `SP2`; His361 → HSE.
4. **Topology.** `prepare_topologies.sh` → `pdb2gmx -ff charmm36-sp2local -water tip3p -ignh`.
5. **Solvate/ionize.** Cubic box, 1.5 nm padding; TIP3P; Na⁺/Cl⁻ to neutral + 0.15 M.
6. **Equilibration ladder.** Restrained EM → 100 ps NVT → 500 ps NPT (full
   restraints) → 500 ps NPT (reduced restraints, k = 100) → 1 ns NPT (free).
7. **Production.** 2 fs timestep, V-rescale / C-rescale at 310 K / 1 bar, CHARMM36
   nonbonded (PME, Force-switch, rvdw = rcoulomb = 1.2 nm, DispCorr = no); 100 ns
   per segment ×2 → 200 ns, GPU. See `mdp/` for exact values.

## Software

GROMACS 2025.4 · CHARMM36 Jul-2022 + CGenFF 4.6 · charmm2gmx 0.7.dev45 · PyMOL
(mutagenesis). Ligand/docking tooling (RDKit, Meeko, AutoDock Vina, CGenFF,
gmx_MMPBSA, MDAnalysis) ships with v2.

## Citing the structure and force field

- Chacko et al., *Mol Cell* 2004, 15:813–823 (PDB 1U7F).
- CHARMM36 protein FF; phosphoamino-acid parameters: Feng, Philippopoulos,
  MacKerell & Lim, *J. Am. Chem. Soc.* 1996, 118:11265–11277.
- GROMACS→CHARMM port: awacha charmm2gmx.
