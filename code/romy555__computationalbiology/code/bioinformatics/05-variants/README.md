# Variants and Population Genomics

Genotype calling from read counts, real allele frequencies across populations, the Hardy–Weinberg test, linkage disequilibrium, a genome-wide association study with a population-structure fix by principal components, and polygenic risk scores.

**Data:** population allele frequencies of three medically important variants (rs334, rs7412, rs1801133) from the 1000 Genomes Project via Ensembl, plus simulated cohorts, in `datasets/`.

| File | What it is |
|---|---|
| `variants.ipynb` | The complete notebook; it reproduces every number and figure. |
| `animations/variant_lab.html` | Interactive animation (open in a browser). |
| `datasets/` | Cached data, so the notebook runs offline. |
| `images/` | Figures saved by the notebook. |

## Run it

```bash
python3 -m pip install -U jupyter numpy pandas matplotlib scipy scikit-learn biopython rdkit torch
jupyter notebook variants.ipynb
```
