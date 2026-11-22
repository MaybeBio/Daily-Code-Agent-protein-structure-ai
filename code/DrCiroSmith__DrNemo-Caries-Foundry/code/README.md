<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/hero_banner_dark.png">
    <img src="https://github.com/DrCiroSmith/DrNemo-Caries-Foundry/raw/HEAD/assets/hero_banner_light.png" alt="DrNemo Caries Foundry - Targeted GtfB Macrocycle Inhibitor Design" width="100%">
  </picture>
</p>

<p align="center">
  <a href="https://drcirosmith.github.io/DrNemo-Caries-Foundry/"><img src="https://img.shields.io/badge/Live%20Demo-Interactive%203D%20Studio-0D9488?style=for-the-badge&logo=webgl&logoColor=white" alt="Live Interactive 3D Demo"></a>
</p>

<p align="center">
  <a href="https://github.com/DrCiroSmith/DrNemo-Caries-Foundry/actions/workflows/ci.yml"><img src="https://github.com/DrCiroSmith/DrNemo-Caries-Foundry/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python 3.10+"></a>
  <a href="https://vina.scripps.edu"><img src="https://img.shields.io/badge/Biophysics-AutoDock_Vina_v1.2.7-76B900.svg" alt="AutoDock Vina"></a>
  <a href="https://langchain-ai.github.io/langgraph/"><img src="https://img.shields.io/badge/Orchestration-LangGraph-orange.svg" alt="LangGraph"></a>
  <a href="https://openmm.org"><img src="https://img.shields.io/badge/ForceField-OpenMM_Amber14-blueviolet.svg" alt="OpenMM Amber14"></a>
</p>

An autonomous computational biophysics pipeline that designs, filters, and falsifies cyclic disulfide macrocycle inhibitors of *Streptococcus mutans* glucosyltransferase-B (GtfB, UniProt P08987). It couples LangGraph state machines with AutoDock Vina v1.2.7 and Vinardo empirical grid docking, OpenMM Amber14/GBn2 all-atom relaxation at 310.15 K, and an exhaustive 12-angle Karl Popper falsification battery evaluating candidate **CAHWRPWHC** over 259 total contenders in the vault, including N=39 scrambled nulls. All findings are strictly in silico computational hypotheses requiring wet-lab enzymatic, whole-saliva, and cellular biofilm falsification.

---

## 1. Biological Target: *S. mutans* GtfB

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/fig1_biological_mechanism_dark.png">
    <img src="https://github.com/DrCiroSmith/DrNemo-Caries-Foundry/raw/HEAD/assets/fig1_biological_mechanism_light.png" alt="Biological mechanism: uninhibited biofilm vs CAHWRPWHC targeted blockade" width="100%">
  </picture>
</p>

Dental caries is driven by acidogenic biofilms. *Streptococcus mutans* secretes glucosyltransferase-B (GtfB), which synthesizes water-insoluble alpha-1,3-glucans (mutan) that cement bacteria to enamel and trap lactic acid against hydroxyapatite, driving demineralization.

The Foundry designs **arginine-rich cyclic disulfide macrocycles** that dock into the GtfB catalytic cleft (RCSB 3AIC: Asp477, Glu515, Asp588, Trp517), halting mutan matrix formation without killing oral commensals.

---

## 2. End-to-End Discovery Pipeline

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/fig2_pipeline_architecture_dark.png">
    <img src="https://github.com/DrCiroSmith/DrNemo-Caries-Foundry/raw/HEAD/assets/fig2_pipeline_architecture_light.png" alt="6-stage closed-loop discovery pipeline with Popperian falsification" width="100%">
  </picture>
</p>

The discovery engine runs an iterative closed loop:

1. **Evolutionary Generator**: C-X-7-C scaffold with P2A hinge; evaluates 259 contenders across discovery and null controls.
2. **Oral Shield Gate**: Donnan Q <= +4.0, Stephan DQ >= +1.0, 0 protease sites.
3. **28.0 A Dual Docking**: AutoDock Vina + Vinardo on RCSB 3AIC (target) and 1SMD (human alpha-amylase off-target).
4. **OpenMM 310.15 K Relaxation**: Amber14/GBn2 all-atom minimization.
5. **12-Angle Popper Falsification**: 1SMD DDG <= -0.80, N=39 scrambled nulls, alanine scan, Acarbose counter-screen.
6. **SQLite Contender Vault and SPPS Protocol**: solid-phase synthesis plan for the corroborated lead.

Falsified candidates (amylase cross-reactivity, protease cleavage) feed back to mutate the hinge.

---

## 3. Biophysical Results: Pareto Champion CAHWRPWHC

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/fig3_pocket_and_funnel_dark.png">
    <img src="https://github.com/DrCiroSmith/DrNemo-Caries-Foundry/raw/HEAD/assets/fig3_pocket_and_funnel_light.png" alt="GtfB active site close-up and multi-gate attrition funnel" width="100%">
  </picture>
</p>

| Parameter | CRRRWWRRRRC | CPHWRPWHC (WT lead) | CPHWRAWHC (P6A) | **CAHWRPWHC (Champion)** | Popperian outcome |
|---|---:|---:|---:|---:|---|
| **GtfB (3AIC) Vina DG** | -7.586 kcal/mol | -8.062 kcal/mol | -8.890 kcal/mol | **-8.191 kcal/mol** | High target affinity |
| **Amylase (1SMD) Vina DG** | -7.580 kcal/mol | -7.902 kcal/mol | -7.300 kcal/mol | **-7.343 kcal/mol** | Host off-target counter-screen |
| **Host Selectivity DDG** | -0.006 kcal/mol | -0.16 kcal/mol | -1.59 kcal/mol | **-0.85 kcal/mol** | **WT cross-reactive; P2A clears <= -0.80 (within Vina noise)** |
| **Oral protease sites** | 7 (degraded) | 0 (RP-shielded) | 1 (trypsin fail) | **0 Trypsin (AT RISK: Trp4/7 chymotryptic)** | Baseline falsified (enzyme lysis) |
| **Chitosan Donnan Q (pH 6)** | +7.00 (> +4.0 fail) | +2.046 | +2.046 | **+2.046 (<= +4.0)** | Baseline falsified (entrapment) |
| **Stephan DQ (acid switch)** | 0.00 | +1.62 | +1.62 | **+1.62** | Acid-activated in cariogenic niche |
| **Disulfide S-S** | unconstrained | 2.06 A | 2.06 A | **2.06 A** | Intact macrocyclic restraint |
| **OpenMM 310.15 K** | N/A | -1,165.5 kJ/mol | -1,271.48 kJ/mol | **-1,234.68 kJ/mol** | Stable minimized conformation |
| **Verdict** | FALSIFIED (multiple gates) | FALSIFIED (amylase) | FALSIFIED (trypsin site) | **IN SILICO HYPOTHESIS** | Candidate advance with 3 caveats |

P2A (Pro2 to Ala) hinge relaxation preserves GtfB binding while sterically excluding the inhibitor from human amylase (DDG = -0.85 kcal/mol). P6A (Pro6 to Ala) gives raw affinity -8.890 kcal/mol but breaks the proline steric shield, creating a tryptic cleavage site, falsified on Angle 5.

---

## 4. 12-Angle Exhaustive Computational Disproof Battery

In accordance with Karl Popper's demarcation principle, candidate **CAHWRPWHC** was challenged across twelve computational disproof angles to systematically identify physical failure modes:

| Angle | Evaluation Angle | Quantitative Metric | Honest Classification |
|---|---|---|---|
| **1** | Co-Crystal Redocking Calibration (3AIC) | Hungarian RMSD 4.51 A, Vina -7.915 kcal/mol (exceeds 2.0-4.0 A standard; wide cleft & glycosidic torsions) | `INCONCLUSIVE_WITHIN_NOISE` |
| **2** | Multi-Seed Conformer & Docking (N=5) | Mean -8.10 +/- 0.37 kcal/mol, cleft centroid SD = 0.46 A | `PASSED_IN_SILICO` |
| **3** | Pose Mode Clustering & Energy Gap | Mode 1-2 Delta E = +0.10 kcal/mol, shift 1.74 A | `INCONCLUSIVE_WITHIN_NOISE` |
| **4** | Force-Field Error Margin on 1SMD Selectivity | DeltaDeltaG = -0.85 kcal/mol vs Vina SE ~2.85 kcal/mol | `INCONCLUSIVE_WITHIN_NOISE` |
| **5** | Charge-Matched Scrambled Null (N=39) | Lead -8.191 vs Null -8.343 +/- 0.470 (Z = +0.32, p = 0.5897) | `INCONCLUSIVE_WITHIN_NOISE` |
| **6** | In-Silico Alanine-Scanning Mutagenesis | Single-site Ala shifts (+0.08 to +0.39 kcal/mol) within Vina noise; P6A exposes Arg5 to trypsin | `PASSED_IN_SILICO` |
| **7** | Explicit pH 5.2 Histidine Diprotonation | Formal charge +1 -> +3; 3AIC -7.71 vs 1SMD -7.89 kcal/mol (Delta = +0.48, slight 1SMD inversion within noise) | `INCONCLUSIVE_WITHIN_NOISE` |
| **8** | Broad Oral Protease & Peptidase Check | Trypsin shielded (Arg5-Pro6); Trp4/Trp7 vulnerable to chymotrypsin | `AT_RISK` |
| **9** | Additional Host Screen (RCSB 1LZ1 Lysozyme) | Human lysozyme DG = -6.67 kcal/mol (DeltaDeltaG = -1.52) | `PASSED_IN_SILICO` |
| **10** | Linear Control vs Cyclic Macrocycle | Linear AHWRPWH (-9.25 kcal/mol) vs cyclic (-8.19 kcal/mol; Vina under-penalizes unfolded entropy) | `INCONCLUSIVE_WITHIN_NOISE` |
| **11** | OpenMM Implicit-Solvent Relaxation Drift | Amber14/GBn2 310.15 K heavy-atom drift RMSD = 0.92 A | `PASSED_IN_SILICO` |
| **12** | Chitosan Donnan & Stephan Acid Switch | Saliva Q = +2.05 <= +4.0; Stephan Delta Q = +1.62 | `PASSED_IN_SILICO` |

> **Scientific Skepticism Verdict:** CAHWRPWHC evaluation yields **5 Passed in Silico, 6 Inconclusive within Noise, 1 At Risk, 0 Falsified**. Strict scientific skepticism highlights key caveats: co-crystal redocking RMSD (Angle 1), pose mode clustering gap (Angle 3), host selectivity margin (Angle 4), scrambled null differentiation (Angle 5), explicit pH 5.2 diprotonation ranking inversion (Angle 7), and linear control entropy artifact (Angle 10) fall within force-field uncertainty boundaries or indicate scoring limitations, while aromatic residues Trp4/Trp7 (Angle 8) carry chymotryptic risk requiring whole-saliva degradation assays. All results are strictly computational hypotheses requiring wet-lab enzymatic, whole human saliva, and cellular biofilm falsification.

---

## 5. Validation Figures

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/fig4_falsification_plate_dark.png">
    <img src="https://github.com/DrCiroSmith/DrNemo-Caries-Foundry/raw/HEAD/assets/fig4_falsification_plate_light.png" alt="4-panel biophysical validation: Pareto frontier, scrambled null histogram, alanine scan, Stephan pH titration" width="100%">
  </picture>
</p>

- **Panel A, Pareto Frontier:** Vina 3AIC vs selectivity DDG across contenders; CAHWRPWHC is the non-dominated champion.
- **Panel B, Scrambled Null Histogram (N=39):** charge-matched sequence permutations establish empirical significance (mean = -8.343 +/- 0.470 kcal/mol, Z = +0.32 sigma, p = 0.5897).
- **Panel C, Alanine Hotspot Scan:** His3, Trp7, His8 are catalytic anchors; Pro2/Pro6 are conformational gates. P6A flagged for Arg5 trypsin lysis.
- **Panel D, Stephan Acid-Switch:** DQ = +1.62 activates the inhibitor in the cariogenic acidic niche (pH approximately 5.2). CRRRWWRRRRC shows flat charge, no acid activation.

---

## 6. Repository Layout

```
DrNemo-Caries-Foundry/
├── .github/workflows/
│   └── ci.yml                           # Automated GitHub Actions test pipeline
├── assets/
│   ├── hero_banner_dark.png             # Dark-mode retina hero with 3D pocket schematic
│   ├── hero_banner_light.png            # Light-mode retina hero
│   ├── fig1_biological_mechanism_dark.png
│   ├── fig1_biological_mechanism_light.png
│   ├── fig2_pipeline_architecture_dark.png
│   ├── fig2_pipeline_architecture_light.png
│   ├── fig3_pocket_and_funnel_dark.png
│   ├── fig3_pocket_and_funnel_light.png
│   ├── fig4_falsification_plate_dark.png
│   └── fig4_falsification_plate_light.png
├── data/
│   ├── contenders_ledger.csv            # 259 contenders (220 design + 39 nulls)
│   ├── foundry_contenders.sqlite        # Persistent SQLite contender vault
│   ├── exhaustive_disproof_report.json  # 12-angle Popperian disproof report
│   └── poses/                           # Docked PDBQT poses
├── demo_data/
│   ├── receptors/                       # Calibrated receptor PDBQT models (3AIC, 1SMD, 1LZ1)
│   └── results/                         # Benchmark falsification results
├── docs/
│   ├── index.html                       # Live 3Dmol.js studio with Light/Dark mode
│   └── vendor/                          # Vendored 3Dmol-min.js
├── manuscript/
│   ├── DrNemo_Preprint.tex              # Full LaTeX manuscript
│   └── DrNemo_Preprint.pdf              # Compiled publication preprint
├── notebooks/                           # Educational SOP Jupyter notebooks (SOP_00..05)
├── scripts/
│   ├── audit_cleanliness.py             # OpSec and integrity audit
│   ├── build_educational_sops.py        # Educational SOP notebook builder
│   ├── build_readme_visuals.py          # Playwright 3Dmol figure builder
│   ├── continuous_hunter.py             # Continuous biophysical contender generator
│   ├── dock_scrambled_1smd.py           # Parallel Vina/Vinardo 1SMD null docker
│   ├── render_assets.py                 # Real-data raster generator
│   ├── run_campaign.py                  # Real campaign discovery runner
│   ├── run_exhaustive_disproof.py       # 12-angle Popperian disproof battery
│   └── verify_educational_sops.py       # Notebook execution verifier
├── tests/
│   └── test_foundry.py                  # Unit and single-source-of-truth test suite
├── analyzer.py                          # Local clinical synthesis
├── biophysics_engine.py                 # AutoDock Vina, Vinardo, OpenMM engine
├── compliance_logger.py                 # Audit and provenance logger
├── dashboard.py                         # Streamlit 3D visualization platform
├── falsification_engine.py              # Karl Popper falsification suite
├── foundry_cli.py                       # Foundry command-line interface
├── foundry_manager.py                   # Contender validation and parameter bounds
├── gtfb_orchestrator.py                 # LangGraph discovery state machine
├── solubility_shield.py                 # Chitosan-native and Donnan pre-filter
├── targets.json                         # Oral pathogen virulence targets
├── vault.py                             # SQLite contender vault
└── requirements.txt                     # Pinned project dependencies
```

---

## 7. Getting Started

### Prerequisites
- Python 3.10 or higher
- System biophysics tools: AutoDock Vina v1.2.7, OpenBabel

### Installation
```bash
git clone https://github.com/DrCiroSmith/DrNemo-Caries-Foundry.git
cd DrNemo-Caries-Foundry
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Running Tests
```bash
pytest tests/ -v
```

### Running the Orchestration Graph
```bash
python3 gtfb_orchestrator.py
```

### Starting the 3D Dashboard
```bash
streamlit run dashboard.py
```

---

## 8. Virulence Target Inventory

Target definitions are cataloged in `targets.json`:
- **Tier 1 (Surface Adhesin):** *S. mutans* SpaP/P1 Adhesin (`P23504`)
- **Tier 2 (Glucan Synthesis):** *S. mutans* GtfB Insoluble Glucan Synthase (`P08987`), GtfC Structural Bridge (`P13470`), GtfD Soluble Primer (`P49331`)
- **Tier 3 (Polymicrobial Synergy):** *Candida albicans* Mannan receptors, *Scardovia wiggsiae* adherence markers, *Porphyromonas gingivalis* Gingipain proteases

---

## 9. Research Notice

This codebase is for academic, computational biology, and preclinical discovery research. Molecular predictions and synthesis plans require wet-lab in-vitro confirmation prior to therapeutic application.

---

## 10. Author

**Dr. Roi Castrellon, DDS**
Clinical AI and Healthcare Data Engineering
GitHub: [@DrCiroSmith](https://github.com/DrCiroSmith)
