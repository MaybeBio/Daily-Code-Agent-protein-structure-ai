# Protein Contacts from Coevolution

Conservation and coevolution in a real protein family alignment, direct coupling analysis to predict 3D contacts from sequence alone, checked against the crystal structure, and how the idea leads to AlphaFold and protein language models.

**Data:** an alignment of 1,500 ubiquitin-family sequences (Pfam PF00240) and the ubiquitin structure (PDB 1UBQ), in `datasets/`.

| File | What it is |
|---|---|
| `protein_ml.ipynb` | The complete notebook; it reproduces every number and figure. |
| `animations/protein_lab.html` | Interactive animation (open in a browser). |
| `datasets/` | Cached data, so the notebook runs offline. |
| `images/` | Figures saved by the notebook. |

## Run it

```bash
python3 -m pip install -U jupyter numpy pandas matplotlib scipy scikit-learn biopython rdkit torch
jupyter notebook protein_ml.ipynb
```
