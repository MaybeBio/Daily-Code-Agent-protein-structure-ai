# Deep Learning on DNA: a CNN that Finds Binding Sites

One-hot encode DNA, train a small convolutional network in PyTorch to detect a transcription-factor binding site, and read the learned filter back as a sequence motif.

**Data:** real CTCF and other motifs from the JASPAR database, used to plant binding sites in sequences, in `datasets/`.

| File | What it is |
|---|---|
| `deep_dna.ipynb` | The complete notebook; it reproduces every number and figure. |
| `animations/dna_cnn_lab.html` | Interactive animation (open in a browser). |
| `datasets/` | Cached data, so the notebook runs offline. |
| `images/` | Figures saved by the notebook. |

## Run it

```bash
python3 -m pip install -U jupyter numpy pandas matplotlib scipy scikit-learn biopython rdkit torch
jupyter notebook deep_dna.ipynb
```
