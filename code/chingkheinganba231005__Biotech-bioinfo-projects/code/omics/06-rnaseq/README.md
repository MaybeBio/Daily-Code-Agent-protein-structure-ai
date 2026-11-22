# Differential Expression in Breast Cancer RNA-seq

From raw counts to biology: library-size normalisation, overdispersion, per-gene tests between two tumour subtypes, Benjamini–Hochberg false-discovery control, a volcano plot and a pathway enrichment test.

**Data:** RSEM gene counts for 200 TCGA breast tumours (100 Basal-like, 100 Luminal A), in `datasets/`.

| File | What it is |
|---|---|
| `rnaseq.ipynb` | The complete notebook; it reproduces every number and figure. |
| `animations/rnaseq_lab.html` | Interactive animation (open in a browser). |
| `datasets/` | Cached data, so the notebook runs offline. |
| `images/` | Figures saved by the notebook. |

## Run it

```bash
python3 -m pip install -U jupyter numpy pandas matplotlib scipy scikit-learn biopython rdkit torch
jupyter notebook rnaseq.ipynb
```
