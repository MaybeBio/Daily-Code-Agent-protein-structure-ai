# Protein Structure and the EGFR Drug Pocket

Parse PDB structures, assign secondary structure from Cα geometry, build contact maps, find and characterise the binding pocket of the lung-cancer drug erlotinib in EGFR, detect pockets without a ligand, and compare structures by RMSD.

**Data:** experimental structures from the Protein Data Bank (EGFR with erlotinib, haemoglobin and others), in `datasets/`.

| File | What it is |
|---|---|
| `structure.ipynb` | The complete notebook; it reproduces every number and figure. |
| `animations/structure_lab.html` | Interactive animation (open in a browser). |
| `datasets/` | Cached data, so the notebook runs offline. |
| `images/` | Figures saved by the notebook. |

## Run it

```bash
python3 -m pip install -U jupyter numpy pandas matplotlib scipy scikit-learn biopython rdkit torch
jupyter notebook structure.ipynb
```
