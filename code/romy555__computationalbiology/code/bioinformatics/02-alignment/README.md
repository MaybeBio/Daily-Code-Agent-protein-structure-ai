# Sequence Alignment from Scratch

Needleman–Wunsch and Smith–Waterman alignment by dynamic programming, BLOSUM62 scoring, affine gaps, dot plots, the BLAST seeding idea and a multiple alignment of the human globins, applied to the spike proteins of SARS-CoV-1 and SARS-CoV-2.

**Data:** spike protein sequences of SARS-CoV-1 and SARS-CoV-2 and five human globins (NCBI / UniProt), in `datasets/`.

| File | What it is |
|---|---|
| `alignment.ipynb` | The complete notebook; it reproduces every number and figure. |
| `animations/align_lab.html` | Interactive animation (open in a browser). |
| `datasets/` | Cached data, so the notebook runs offline. |
| `images/` | Figures saved by the notebook. |

## Run it

```bash
python3 -m pip install -U jupyter numpy pandas matplotlib scipy scikit-learn biopython rdkit torch
jupyter notebook alignment.ipynb
```
