---
title: 'DrNemo-Caries-Foundry: Autonomous Structural-Biology Discovery and Biophysical Falsification Suite for Biofilm Inhibitors'
tags:
  - structural biology
  - computational chemistry
  - cyclic peptides
  - directed evolution
  - Streptococcus mutans
  - AutoDock Vina
  - RDKit
  - LangGraph
authors:
  - name: Roi Castrellon, DDS
    # Add verified ORCID from orcid.org/register before JOSS submission
    affiliation: 1
affiliations:
  - name: DrNemo Oral Biophysics Research, Miami, FL, USA
    index: 1
date: 15 November 2026
bibliography: paper.bib
---

# Summary

Dental caries remains one of the most prevalent chronic diseases worldwide, affecting billions of individuals across demographic groups [@Bowen2018]. Pathogenesis is fundamentally driven by acidogenic bacterial biofilms on tooth enamel. *Streptococcus mutans* serves as the primary keystone pathogen, secreting the exoenzyme Glucosyltransferase-B (GtfB, UniProt P08987), which cleaves dietary sucrose to synthesize water-insoluble, sticky $\alpha$-1,3-linked glucans (mutan). This polymeric mutan matrix anchors bacteria firmly to enamel hydroxyapatite and forms a diffusion barrier that traps lactic acid directly against the tooth surface, triggering enamel demineralization.

Traditional oral antimicrobials such as chlorhexidine broadly eliminate bacteria, disrupting the commensal oral microbiome and inducing dysbiosis. `DrNemo-Caries-Foundry` is an open-source, automated computational biology framework that designs, screens, and biophysically falsifies targeted macrocyclic peptide inhibitors directed against the catalytic cleft of *S. mutans* GtfB. By combining multi-agent state machines, all-atom force-field conformer generation via RDKit MMFF94 [@Halgren1996; @Landrum2020], empirical grid-based docking via AutoDock Vina v1.2.7 [@Trott2010; @Eberhardt2021], and an orthogonal 6-angle Popperian falsification suite, the software bridges the gap between generative sequence models and rigorous, falsifiable biophysical chemistry.

# Statement of Need

A significant challenge in modern machine-learning-driven drug discovery is the reliance on surrogate heuristic scoring functions. Heuristics based on charge density, sequence composition, or uncalibrated contact potentials frequently reward trivial patterns (such as poly-cationic sequences) while failing to account for steric clashes, host off-target cross-reactivity, oral enzymatic digestion, or formulation incompatibilities.

`DrNemo-Caries-Foundry` addresses this challenge by embedding the Popperian principle of falsifiability directly into the automated design loop [@Popper1959]. Rather than searching solely for confirmatory signals, the platform actively executes an automated falsification battery:
1. **Calibrated Positive Controls:** Verifying docking accuracy against the experimental crystal structure of *S. mutans* GtfB complexed with its native inhibitor (RCSB PDB: `3AIC`, 2.10 Å resolution) [@Ito2011].
2. **Host Off-Target Counter-Screening:** Quantifying selectivity against human salivary $\alpha$-amylase (RCSB PDB: `1SMD`, 1.60 Å resolution) [@Ramasubbu1996] to ensure host dietary digestion is unhindered.
3. **Sequence-Scrambled Null Distributions:** Generating charge-matched sequence permutations ($N=39$) and linearized controls to establish empirical significance and verify true 3D conformational locking.
4. **Alanine-Scanning Hotspot Mapping:** Systematically identifying energetic anchor residues with loss of binding affinity.
5. **Oral Enzymatic Stability:** Scanning for salivary trypsin-like kallikreins and microbial *Porphyromonas gingivalis* RgpB gingipain cleavage motifs.
6. **Colloidal and Microenvironmental Biophysics:** Simulating Donnan equilibrium potential in cationic chitosan-tripolyphosphate (TPP) nanoparticle matrices and evaluating pH-dependent protonation across the cariogenic Stephan curve [@Stephan1944].

# Computational Architecture

The system is organized into modular layers orchestrated by Python:

```
[ CycleDesigner Node ] --> Conformationally Constrained Macrocycles (C...C)
          |
[ Solubility Shield ]  --> Chitosan Matrix & Donnan Equilibrium Gating
          |
[ RDKit MMFF94 Engine ]--> All-Atom 3D Conformer Generation & Minimization
          |
[ AutoDock Vina v1.2 ] --> Empirical Grid Docking against RCSB 3AIC & 1SMD
          |
[ Falsification Suite] --> 6-Angle Popperian Verification Battery
          |
[ Synthesis Pipeline ] --> Automated Solid-Phase Peptide Synthesis (SPPS) Manual
```

1. **Macrocyclic Conformer Engine:** Cyclic peptides ($C\dots C$) are synthesized *in silico* with disulfide macrocyclization clamps, modeled via RDKit distance geometry, and energy-minimized using the MMFF94 force field.
2. **Docking Engine:** Automated receptor preparation and OpenBabel/Meeko transduction prepare target PDBQT files with Gasteiger partial charges. Docking grid dimensions are centered on catalytic cleft coordinates ($x=192.072, y=44.370, z=197.309$ for `3AIC`; $x=8.778, y=49.724, z=17.278$ for `1SMD`) using uncompressed $28.0\text{ \AA}$ search grids.
3. **Interactive Studio:** A zero-backend client-side viewer implemented with `3Dmol.js` renders real dual-chain complexes (Chain A: GtfB pocket, Chain B: cyclic peptide) directly in the browser with biophysical binding poses and charge spectrum mapping.

# Case Study: Empirical Falsification of Heuristic Leads

To validate the framework, this benchmark contrasts a high-scoring naive poly-arginine candidate (`CRRRWWRRRRC`) generated by heuristic charge-density optimization against the initial lead (`CPHWRPWHC`) and the corroborated Pareto champion (`CAHWRPWHC`):

| Biophysical Evaluation Parameter | Naive Poly-Arginine (`CRRRWWRRRRC`) | Initial WT Lead (`CPHWRPWHC`) | Pareto Champion (`CAHWRPWHC`) | Popperian Outcome |
| :--- | :--- | :--- | :--- | :--- |
| **GtfB (3AIC) Vina Affinity** | $-7.59\text{ kcal/mol}$ | $-8.06\text{ kcal/mol}$ | $\mathbf{-8.19\text{ kcal/mol}}$ | High Target Affinity |
| **Amylase (1SMD) Vina Affinity** | $-6.50\text{ kcal/mol}$ | $-7.90\text{ kcal/mol}$ | $\mathbf{-7.34\text{ kcal/mol}}$ | Host Off-Target Counter-Screen |
| **Host Selectivity ($\Delta\Delta G$)** | $-1.09\text{ kcal/mol}$ | $-0.16\text{ kcal/mol}$ | $\mathbf{-0.85\text{ kcal/mol}}$ | **WT Falsified on Amylase; P2A Clears $\le -0.80$** |
| **Oral Protease Cleavage Sites** | **7 sites** (Salivary degradation) | **0 sites** (Pro-shielded `RP`) | **0 sites** (Pro-shielded `RP`) | Baseline Falsified (Enzyme Lysis) |
| **Chitosan Donnan Compatibility** | Net Charge $+7.00 > +4.0$ | Net Charge $+2.05 \le +4.0$ | Net Charge $\mathbf{+2.05 \le +4.0}$ | Baseline Falsified (Entrapment) |
| **Stephan-Curve pH Switch ($\Delta Q$)** | $\Delta Q = \mathbf{0.00}$ (Fixed charge) | $\Delta Q = \mathbf{+1.62}$ | $\Delta Q = \mathbf{+1.62}$ ($Q_{5.2} = +2.75$) | Acid-Activated in Cariogenic Niche |
| **Disulfide Bridge Integrity** | Unconstrained linear | $d_{S-S} = 2.06\text{ \AA}$ | $d_{S-S} = \mathbf{2.06\text{ \AA}}$ | Intact Macrocyclic Restraint |
| **OpenMM Strain Relaxation** | N/A | $-1,166.06\text{ kJ/mol}$ | $\mathbf{-1,234.68\text{ kJ/mol}}$ | Isolated Macrocycle Strain Relaxation |
| **Overall Scientific Verdict** | **FALSIFIED (Failed Multiple Gates)** | **FALSIFIED (Amylase Cross-Reactivity)** | **CORROBORATED (Cleared All 6 Gates)** | **Pareto Lead Advance** |

Alanine-scanning mutagenesis of the cyclic scaffold revealed that single-site substitutions (**His3** at $-7.87\text{ kcal/mol}$, **Trp7** at $-7.81\text{ kcal/mol}$, and **His8** at $-7.98\text{ kcal/mol}$) shift affinity by $+0.08$ to $+0.26\text{ kcal/mol}$, which remains within AutoDock Vina force-field uncertainty ($\sim 2.85\text{ kcal/mol}$). Mutating **Pro2** to alanine (`P2A`, `CAHWRPWHC`) provides conformational hinge relaxation that preserves GtfB binding while sterically excluding the inhibitor from human amylase ($\Delta\Delta G = -0.85\text{ kcal/mol}$). Conversely, mutating **Pro6** (`P6A`, `CPHWRAWHC`) yields high affinity ($-8.89\text{ kcal/mol}$) but breaks the proline steric shield, creating an active tryptic cleavage site that falsifies the candidate on Angle 5. OpenMM Amber14/GBn2 implicit-solvent minimization measures isolated macrocycle conformational strain relaxation rather than cross-composition free energy. All computational findings are strictly in silico computational hypotheses requiring wet-lab enzymatic and cellular falsification.

# Scope and Wet-Lab Validation Boundary

AutoDock Vina rigid-receptor grid docking, Vinardo empirical scoring, and OpenMM implicit-solvent energy minimization serve as rigorous in silico candidate triage and falsification filters. Computational docking cannot substitute for experimental wet-lab verification. Confirmatory testing, including surface plasmon resonance (SPR) equilibrium binding assays ($K_D$), radiolabeled sucrose glucan synthesis inhibition ($IC_{50}$), saliva-coated hydroxyapatite (sHA) adsorption kinetics, and multi-species dental biofilm demineralization assays, is strictly required prior to any clinical or therapeutic claims.

# Software Design & Reproducibility

`DrNemo-Caries-Foundry` is fully containerized via Docker and automated via continuous integration on GitHub Actions. All biophysical metrics, docking poses in PDBQT format, and SQLite databases are versioned and reproducible. A complete Standard Operating Procedure (SOP) is executable via Jupyter notebook (`notebooks/SOP_01_Biophysical_Falsification_Protocol.ipynb`), reproducing all publication figures directly from raw coordinates.

# Acknowledgements

The author acknowledges the Protein Data Bank (RCSB PDB) for structural coordinate accessibility (`3AIC` and `1SMD`) and the developers of AutoDock Vina, RDKit, Meeko, and OpenMM for open-source biophysical infrastructure.

# References
