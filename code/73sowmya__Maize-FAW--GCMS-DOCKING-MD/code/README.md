# Maize Resistance to Fall Armyworm: DVCS, GC–MS Volatilomics, Molecular Docking and Molecular Dynamics

## 1. Project Overview

This repository contains the experimental datasets, GC–MS results, statistical analyses, molecular docking outputs, molecular dynamics simulation files, MM/GBSA calculations, figures and supplementary tables associated with the investigation of maize resistance to fall armyworm (FAW), *Spodoptera frugiperda*.

The study integrates conventional host plant resistance (HPR) screening with a novel Dynamic Volatile Collection System (DVCS), GC–MS-based volatilomics, multivariate statistical analyses and computational investigation of potential interactions between maize volatile organic compounds (VOCs) and FAW chemosensory proteins.

The primary objective is to characterize constitutive and herbivore-induced volatile profiles in contrasting maize genotypes, identify volatile signatures associated with resistance, and prioritize candidate semiochemicals based on their predicted interactions with FAW olfactory proteins.

## 2. Major Components of the Study

### 2.1 Host Plant Resistance Screening

Five maize inbred lines with contrasting responses to FAW were evaluated:

- BML 6
- HKI 193-1
- DMRE 63
- CML 336
- CML 337

Resistance was assessed using leaf injury ratings, larval recovery and larval weight following FAW infestation.

### 2.2 Dynamic Volatile Collection System (DVCS)

A novel Dynamic Volatile Collection System was developed and used for simultaneous collection of headspace volatiles from multiple maize plants.

The system incorporates:

- A centralized aeration manifold.
- A vacuum manifold for controlled headspace withdrawal.
- Individual specimen chambers.
- Independent volatile-trapping pathways.
- Tenax TA adsorbent tubes for VOC collection.
- Adjustable and non-adjustable prototype configurations.

The system was used to collect volatile emissions from maize plants at 0, 24 and 48 hours following FAW infestation.

### 2.3 GC–MS-Based Volatilomics

Collected VOCs were analysed using gas chromatography–mass spectrometry (GC–MS).

Compound identification was based on mass spectral comparison with the NIST 2023 library, retention indices and authentic reference standards, where available.

The study investigated genotype-dependent and time-dependent changes in volatile emissions, including constitutive and herbivore-induced VOC signatures.

### 2.4 Statistical and Multivariate Analyses

The volatilomics datasets were analysed using complementary statistical approaches, including:

- Analysis of variance (ANOVA).
- Tukey's honestly significant difference (HSD) test.
- Principal component analysis (PCA).
- Partial least squares-discriminant analysis (PLS-DA).
- Variable Importance in Projection (VIP) analysis.
- Random Forest (RF) classification.

These analyses were used to identify discriminatory volatile compounds and candidate chemical markers associated with maize resistance and herbivory-induced responses.

### 2.5 Molecular Docking

Molecular docking was performed to investigate the predicted interactions of identified maize VOCs with sixteen FAW chemosensory protein targets.

The protein targets included:

- SfruGOBP1 and SfruGOBP2.
- Thirteen odorant receptors (SfruOR5, SfruOR6, SfruOR11, SfruOR13, SfruOR14, SfruOR15, SfruOR16, SfruOR18, SfruOR30, SfruOR38, SfruOR40, SfruOR56 and SfruOR62).
- SfruORco.

Protein structures were modelled using SWISS-MODEL and evaluated using structural quality assessment tools. Molecular docking was performed using AutoDock Vina.

The analysis was intended to prioritize candidate VOCs based on their predicted protein–ligand interactions and binding affinities. These computational predictions do not independently establish olfactory perception or behavioural responses.

### 2.6 Molecular Dynamics (MD) Simulations

Molecular dynamics simulations were performed using GROMACS 2023.3 to investigate selected SfruGOBP1–ligand systems over 100 ns.

The computational workflow included:

- OPLS-AA force field.
- TIP3P water model.
- Energy minimization.
- NVT and NPT equilibration.
- 100 ns production simulations.
- Particle mesh Ewald (PME) electrostatics.
- Structural and interaction analyses.

The trajectories were analysed using:

- Root mean square deviation (RMSD).
- Root mean square fluctuation (RMSF).
- Radius of gyration (Rg).
- Protein–ligand contact occupancy.

### 2.7 MM/GBSA Binding Energy Analysis

Endpoint binding energy calculations were performed using gmx_MMPBSA.

The analysis included:

- van der Waals energy contribution.
- Electrostatic energy contribution.
- Generalized Born (GB) polar solvation contribution.
- Solvent-accessible surface area (SASA)-based nonpolar solvation contribution.

The results provide preliminary estimates of protein–ligand endpoint energy contributions. Conformational entropy was not included.

## 3. Repository Structure

The repository is organized into the following directories:

```text
Maize-FAW-GCMS-DOCKING-MD/
│
├── README.md
│
├── 01_HPR_Data/
│   ├── Raw_Data/
│   └── Statistical_Analysis/
│
├── 02_DVCS/
│   ├── System_Images/
│   ├── Design_Details/
│   └── Prototype_Configurations/
│
├── 03_GCMS_Data/
│   ├── Raw_Data/
│   ├── Processed_Data/
│   └── VOC_Identification/
│
├── 04_Volatilomics_Analysis/
│   ├── PCA/
│   ├── PLS_DA/
│   ├── Random_Forest/
│   └── Statistical_Analysis/
│
├── 05_Molecular_Docking/
│   ├── Protein_Structures/
│   ├── Ligand_Structures/
│   ├── Docking_Results/
│   └── Protein_Ligand_Interactions/
│
├── 06_MD_Simulation/
│   ├── Input_Files/
│   ├── Topology_Files/
│   ├── Trajectories/
│   └── Analysis_Results/
│
├── 07_MMGBSA_Analysis/
│   ├── Input_Files/
│   ├── Energy_Decomposition/
│   └── Results/
│
├── 08_Figures/
│
├── 09_Supplementary_Tables/
│
└── 10_Analysis_Scripts/
```

## 4. Software and Computational Tools

The following tools and software were used in the study:

- Agilent MassHunter Qualitative Analysis.
- NIST 2023 Mass Spectral Library.
- MetaboAnalyst 6.0.
- ACD/ChemSketch 2025.2.5.
- Avogadro 2.0.0.
- SWISS-MODEL.
- ProSA-web.
- CASTp 3.0.
- AutoDock Tools 4.2.6.
- AutoDock Vina 1.2.7.
- Discovery Studio Visualizer.
- GROMACS 2023.3.
- gmx_MMPBSA.

## 5. Contact Information

**Corresponding authors:**

S. B. Suby – sb.suby@icar.org.in  
Megha Sailwal – meghasailwal01@gmail.com

**Institution:** ICAR–Indian Institute of Maize Research, Ludhiana, India.
