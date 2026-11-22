# Genome Assembly and Read Mapping from Scratch

Simulated sequencing reads with Phred qualities, a de Bruijn graph assembler, why repeats break assembly, N50, a k-mer index read mapper and pileup-based variant calling, all on the SARS-CoV-2 genome.

**Data:** the SARS-CoV-2 reference genome (NCBI), from which reads are simulated, in `datasets/`.

| File | What it is |
|---|---|
| `assembly.ipynb` | The complete notebook; it reproduces every number and figure. |
| `animations/assembly_lab.html` | Interactive animation (open in a browser). |
| `datasets/` | Cached data, so the notebook runs offline. |
| `images/` | Figures saved by the notebook. |

## Run it

```bash
python3 -m pip install -U jupyter numpy pandas matplotlib scipy scikit-learn biopython rdkit torch
jupyter notebook assembly.ipynb
```
