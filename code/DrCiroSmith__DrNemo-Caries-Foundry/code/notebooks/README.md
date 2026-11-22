# DrNemo Non-Technical Standard Operating Procedures (SOP) Curriculum
## Streptococcus mutans GtfB Macrocyclic Inhibitor Campaign
**Principal Investigator:** Dr. Roi Castrellon, DDS  
**Affiliation:** DrNemo Oral Biophysics Research, Miami, FL, USA (`roisasha@gmail.com`)  
**Target Receptor:** RCSB PDB 3AIC (2.10 A Resolution) | Counter-Screen: Human Salivary Amylase 1SMD (1.60 A Resolution)  
**Live WebGL 3D Studio:** [Interactive WebGL Viewer](https://drcirosmith.github.io/DrNemo-Caries-Foundry/)  
**Workstation Dashboard:** `streamlit run dashboard.py` (Local Port 8501)  

---

## Educational Curriculum Overview
This curriculum translates advanced computational biophysics, autonomous workflows, and Karl Popper falsification protocols into clear, intuitive Standard Operating Procedures (SOPs). Written specifically for clinicians, dentists, students, recruiters, and executive leaders, each notebook pairs plain-English clinical analogies with **100% executable Python calculations** against real empirical data.

All notebooks adhere strictly to:
- Zero fabricated numbers: all calculations execute against `data/contenders_ledger.csv`, `demo_data/results/falsification_benchmark.json`, `solubility_shield.py`, and `demo_data/results/3AIC_docked_complex_CAHWRPWHC.pdb`.
- Zero em-dashes in prose strings (following canonical `SOUL.md` standards).
- Zero plural authorship pronouns in authorial voice.
- Full self-contained execution with embedded publication-quality visualizations.

---

## Sequence Length vs Database Capacity: An Essential Distinction
A critical distinction in this computational campaign governs molecular size versus repository scalability:
1. **Structural Length (9 Amino Acids per Molecule):** Every macrocycle candidate in this primary series is constrained to 9 residues (`Cys1` through `Cys9`). This physical span (approximately 12 to 14 Angstroms in cyclic diameter) is geometrically tuned to span the catalytic cleft of GtfB without steric clashing or excessive entropic flexibility.
2. **Limitless Candidate Volume (Unlimited Peptides in SQLite Vault):** In contrast to the 9-residue molecular length, the number of candidate peptides that can be generated, screened, and stored in the SQLite database (`data/foundry_contenders.sqlite`) is completely limitless. Indexed by sequence hash (`CREATE INDEX IF NOT EXISTS idx_sequence ON contenders(sequence);`), the vault performs constant-time O(1) lookups and scales to millions of unique macrocycle contenders without memory bottlenecks.

---

## Curriculum Table of Contents

| SOP ID | Notebook File | Notebook Title | Plain-English Summary | Status |
| :--- | :--- | :--- | :--- | :--- |
| **SOP-00** | [`SOP_00_Interactive_Page_and_Platform_Tour.ipynb`](https://github.com/DrCiroSmith/DrNemo-Caries-Foundry/blob/HEAD/notebooks/SOP_00_Interactive_Page_and_Platform_Tour.ipynb) | Interactive Page & Platform Tour | Step-by-step tour of the WebGL 3D Studio and local 9-tab dashboard with live 3-minute presentation script. | Corroborated & Executed |
| **SOP-01** | [`SOP_01_Guide_What_Is_Karl_Popper_Falsification.ipynb`](https://github.com/DrCiroSmith/DrNemo-Caries-Foundry/blob/HEAD/notebooks/SOP_01_Guide_What_Is_Karl_Popper_Falsification.ipynb) | Philosophy of Science: Karl Popper Falsification | Why I try to break my own AI designs and how the 12-angle battery identifies physical failure modes. | Corroborated & Executed |
| **SOP-02** | [`SOP_02_Molecular_Docking_and_Amylase_Selectivity.ipynb`](https://github.com/DrCiroSmith/DrNemo-Caries-Foundry/blob/HEAD/notebooks/SOP_02_Molecular_Docking_and_Amylase_Selectivity.ipynb) | Lock-and-Key Physics & Amylase Selectivity | Understanding 28 A docking boxes, negative kcal/mol, and evaluating the +/-2.85 kcal/mol Vina noise margin. | Corroborated & Executed |
| **SOP-03** | [`SOP_03_Scrambled_Null_Trap_and_Alanine_Scan.ipynb`](https://github.com/DrCiroSmith/DrNemo-Caries-Foundry/blob/HEAD/notebooks/SOP_03_Scrambled_Null_Trap_and_Alanine_Scan.ipynb) | Scrambled Null Trap & Alanine Hotspot Scan | Catching false positives with 39 scrambled letters and identifying catalytic anchors in the GtfB cleft. | Corroborated & Executed |
| **SOP-04** | [`SOP_04_Saliva_Survival_Stephan_pH_Switch_and_Proteases.ipynb`](https://github.com/DrCiroSmith/DrNemo-Caries-Foundry/blob/HEAD/notebooks/SOP_04_Saliva_Survival_Stephan_pH_Switch_and_Proteases.ipynb) | Saliva Survival: Stephan Curve & Proteases | Plaque acid dynamics, Henderson-Hasselbalch charge surge, and trypsin shielding vs chymotrypsin vulnerability. | Corroborated & Executed |
| **SOP-05** | [`SOP_05_In_Silico_Limitations_and_Wet_Lab_Falsification_Roadmap.ipynb`](https://github.com/DrCiroSmith/DrNemo-Caries-Foundry/blob/HEAD/notebooks/SOP_05_In_Silico_Limitations_and_Wet_Lab_Falsification_Roadmap.ipynb) | In Silico Limitations & Wet-Lab Roadmap | Multi-objective Pareto optimization, honest disproof tally (5/6/1/0), and 5-stage wet-lab experimental protocol. | Corroborated & Executed |

---

## How to Execute and Validate the Notebooks

All notebooks run cleanly inside the local project virtual environment:

```bash
# Execute all SOP notebooks in-place with zero cell errors
.venv/bin/jupyter nbconvert --to notebook --execute --inplace notebooks/SOP_00_Interactive_Page_and_Platform_Tour.ipynb
.venv/bin/jupyter nbconvert --to notebook --execute --inplace notebooks/SOP_01_Guide_What_Is_Karl_Popper_Falsification.ipynb
.venv/bin/jupyter nbconvert --to notebook --execute --inplace notebooks/SOP_02_Molecular_Docking_and_Amylase_Selectivity.ipynb
.venv/bin/jupyter nbconvert --to notebook --execute --inplace notebooks/SOP_03_Scrambled_Null_Trap_and_Alanine_Scan.ipynb
.venv/bin/jupyter nbconvert --to notebook --execute --inplace notebooks/SOP_04_Saliva_Survival_Stephan_pH_Switch_and_Proteases.ipynb
.venv/bin/jupyter nbconvert --to notebook --execute --inplace notebooks/SOP_05_In_Silico_Limitations_and_Wet_Lab_Falsification_Roadmap.ipynb

# Verify audit cleanliness
.venv/bin/python scripts/verify_educational_sops.py
```

---

## Epistemological and Clinical Standards
1. **Evidence Before Claims:** Every statement in these SOPs is directly corroborated by fresh executed Python output.
2. **Zero Fabricated Surrogates:** All numbers are derived from verified empirical files (`falsification_benchmark.json`, `contenders_ledger.csv`, and PDB coordinates).
3. **Strict Scientific Skepticism:** All in-silico findings are explicitly labeled as computational hypotheses requiring wet-lab experimental falsification.
