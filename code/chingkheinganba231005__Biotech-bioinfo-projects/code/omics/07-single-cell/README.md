# Single-Cell RNA-seq of Human Blood Cells

A full single-cell pipeline on 2,700 real blood cells: quality control, normalisation, highly variable genes, PCA, clustering, t-SNE and marker-gene annotation of the cell types.

**Data:** the PBMC3k dataset from 10x Genomics (sparse count matrix), in `datasets/`.

| File | What it is |
|---|---|
| `single_cell.ipynb` | The complete notebook; it reproduces every number and figure. |
| `animations/sc_lab.html` | Interactive animation (open in a browser). |
| `datasets/` | Cached data, so the notebook runs offline. |
| `images/` | Figures saved by the notebook. |

## Run it

```bash
python3 -m pip install -U jupyter numpy pandas matplotlib scipy scikit-learn biopython rdkit torch
jupyter notebook single_cell.ipynb
```
