# AutoAnalog v2.0

An Automated Multi-Tool Pipeline for Designing
Improved Small Molecule Analogue Lead Compounds.

Demonstrated on P2Y12 for Endometriosis-Associated Pain.

---

## What it does

Input  : Disease name + Receptor + PDB ID + Known inhibitor
Output : Ranked small molecule analogue lead compounds + PDF report

---

## Pipeline Steps

| Step | Task | Tools |
|------|------|-------|
| 01 | Protein structure prep | PDB / AlphaFold2 / PDBFixer / OpenBabel |
| 02 | Literature mining | PubMed / Semantic Scholar / OpenAlex |
| 03 | Analogue design | RDKit BRICS + R-group permutation |
| 04 | ML activity + IC50 | ChemBERTa + Tanimoto similarity |
| 05 | ADMET Stage 1 | RDKit / PAINS / hERG filter |
| 06 | Virtual screening | Tanimoto + Pharmacophore |
| 07 | Molecular docking | AutoDock Vina + GNINA (GPU) |
| 08 | ADMET Stage 2 | Ligand Efficiency / LipE / BEI |
| 09 | MD simulation | OpenMM 0.1ns @ 300K AMBER14 |
| 10 | Final ranking | Composite score + IC50 comparison |
| 11 | PDF report | ReportLab auto-generated |

---

## Quick Start — Local

```bash
conda activate p2y12
cd ~/Desktop/p2y12
snakemake --forceall --cores 4
```

---

## Quick Start — Docker

### Build
```bash
sudo docker build -t autoanalog:v2.0 .
```

### Run default (P2Y12 / Endometriosis)
```bash
./docker_run.sh
```

### Run custom target
```bash
sudo docker run --rm \
    -v $(pwd)/output:/pipeline/results \
    autoanalog:v2.0 \
    "alzheimer" \
    "BACE1" \
    "2OHU" \
    "CC(C)(C)c1cc(NC(=O)c2cc(F)ccc2F)ccc1S(=O)(=O)N" \
    15 \
    "Verubecestat"
```

---

## Change Target — Edit config only

```bash
nano config/config.yaml
```

Change these lines only:

```yaml
disease: "your_disease"
receptor: "YOUR_RECEPTOR"
pdb_id: "XXXX"
known_inhibitor: "YOUR_SMILES"
reference_ic50_nm: 100
reference_name: "YourInhibitor"
reference_source: "Author et al. Year"
```

Then run:

```bash
snakemake --forceall --cores 4
```

---

## Two Pipeline Modes

### Mode 1 — Known protein + Known inhibitor
```yaml
pdb_id: "4NTJ"
sequence: ""
known_inhibitor: "CC1=CC..."
```

### Mode 2 — Unknown protein
```yaml
pdb_id: ""
sequence: "MKTAYIAKQRQISFVKSH..."
known_inhibitor: ""
```
Pipeline auto-detects and switches mode.

---

## Output Files

```
results/
├── structure/protein.pdbqt
├── literature/papers.csv
├── analogues/descriptors.csv
├── analogues/all_analogues.png
├── models/activity_scores.csv
├── admet/stage1.csv
├── admet/stage2.csv
├── screening/screened.csv
├── docking/scores.csv
├── md/md_results.csv
├── ranking/final_ranking.csv
├── ranking/pareto_plot.png
└── report/final_report.pdf
```

---

## Case Study — P2Y12 / Endometriosis

- Reference: AZD1283 IC50 = 89 nM
- PDB: 4NTJ
- Papers retrieved: 205
- Analogues designed: 10+
- Best docking: F_tolyl -8.079 kcal/mol
- Rank 1: Thiazole composite score 0.928

---

## Requirements

```
Python 3.10
RDKit
OpenMM + PDBFixer
AutoDock Vina v1.2.5
OpenBabel
Snakemake
Transformers (ChemBERTa)
ReportLab
```

---

## Citation

AutoAnalog v2.0 — Computational Drug Discovery Pipeline
Target: P2Y12 for Endometriosis-Associated Pain
Reference: AZD1283 (Springthorpe et al. 2007, J Med Chem)
