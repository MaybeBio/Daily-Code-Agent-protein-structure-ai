# Cheminformatics on Approved Drugs

Molecules as SMILES and graphs with RDKit: descriptors, Morgan fingerprints, Tanimoto similarity search, clustering chemical space and drug-likeness and PAINS filters, on every approved small-molecule drug.

**Data:** 3,311 approved small-molecule drugs from ChEMBL, in `datasets/`.

| File | What it is |
|---|---|
| `cheminformatics.ipynb` | The complete notebook; it reproduces every number and figure. |
| `animations/chem_lab.html` | Interactive animation (open in a browser). |
| `datasets/` | Cached data, so the notebook runs offline. |
| `images/` | Figures saved by the notebook. |

## Run it

```bash
python3 -m pip install -U jupyter numpy pandas matplotlib scipy scikit-learn biopython rdkit torch
jupyter notebook cheminformatics.ipynb
```
