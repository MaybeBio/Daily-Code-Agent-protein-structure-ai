# Reading a Virus Genome: Sequences as Data

Parse real GenBank and FASTA records, measure GC content and GC skew, count k-mers and find over- and under-represented words, and write an open-reading-frame gene finder that is tested against the annotated genes of SARS-CoV-2.

**Data:** the SARS-CoV-2 reference genome (NC_045512), phage lambda and 100 kb of E. coli, from NCBI, in `datasets/`.

| File | What it is |
|---|---|
| `sequences.ipynb` | The complete notebook; it reproduces every number and figure. |
| `animations/seq_lab.html` | Interactive animation (open in a browser). |
| `datasets/` | Cached data, so the notebook runs offline. |
| `images/` | Figures saved by the notebook. |

## Run it

```bash
python3 -m pip install -U jupyter numpy pandas matplotlib scipy scikit-learn biopython rdkit torch
jupyter notebook sequences.ipynb
```
