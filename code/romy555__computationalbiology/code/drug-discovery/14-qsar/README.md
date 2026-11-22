# QSAR and Virtual Screening for EGFR Inhibitors

Predict the potency of EGFR inhibitors from structure with random forests on fingerprints, test honestly with scaffold splits, classify actives, measure virtual-screening enrichment and define an applicability domain.

**Data:** 607 EGFR inhibitors with measured IC50 from ChEMBL, in `datasets/`.

| File | What it is |
|---|---|
| `qsar.ipynb` | The complete notebook; it reproduces every number and figure. |
| `animations/qsar_lab.html` | Interactive animation (open in a browser). |
| `datasets/` | Cached data, so the notebook runs offline. |
| `images/` | Figures saved by the notebook. |

## Run it

```bash
python3 -m pip install -U jupyter numpy pandas matplotlib scipy scikit-learn biopython rdkit torch
jupyter notebook qsar.ipynb
```
