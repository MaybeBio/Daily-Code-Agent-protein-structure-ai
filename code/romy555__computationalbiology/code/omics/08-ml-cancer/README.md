# Machine Learning for Breast Cancer Subtypes

Classify four breast-cancer subtypes from 5,993 genes with honest cross-validation: the p ≫ n problem, a demonstration of feature-selection leakage, L1 and L2 logistic regression, random forests, regularisation curves and the genes behind each prediction.

**Data:** gene counts for 408 TCGA breast tumours with PAM50 subtype labels, in `datasets/`.

| File | What it is |
|---|---|
| `ml_cancer.ipynb` | The complete notebook; it reproduces every number and figure. |
| `animations/ml_lab.html` | Interactive animation (open in a browser). |
| `datasets/` | Cached data, so the notebook runs offline. |
| `images/` | Figures saved by the notebook. |

## Run it

```bash
python3 -m pip install -U jupyter numpy pandas matplotlib scipy scikit-learn biopython rdkit torch
jupyter notebook ml_cancer.ipynb
```
