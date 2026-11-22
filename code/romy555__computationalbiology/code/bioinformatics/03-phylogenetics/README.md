# Phylogenetics of Coronaviruses

Evolutionary distances with the Jukes–Cantor correction, UPGMA and neighbour joining written from scratch, alignment-free k-mer distances between whole genomes, and bootstrap support for each branch of a tree of real coronaviruses.

**Data:** complete genomes of SARS-CoV-2, its bat and pangolin relatives, SARS-CoV-1 and MERS-CoV (NCBI), in `datasets/`.

| File | What it is |
|---|---|
| `phylogenetics.ipynb` | The complete notebook; it reproduces every number and figure. |
| `animations/tree_lab.html` | Interactive animation (open in a browser). |
| `datasets/` | Cached data, so the notebook runs offline. |
| `images/` | Figures saved by the notebook. |

## Run it

```bash
python3 -m pip install -U jupyter numpy pandas matplotlib scipy scikit-learn biopython rdkit torch
jupyter notebook phylogenetics.ipynb
```
