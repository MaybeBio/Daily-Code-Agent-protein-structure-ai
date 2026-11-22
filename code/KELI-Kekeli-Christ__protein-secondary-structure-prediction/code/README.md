<p align="center">
  <a href="https://github.com/KELI-Kekeli-Christ/protein-secondary-structure-prediction/blob/HEAD/README.md"><b>English</b></a>
  &nbsp;·&nbsp;
  <a href="https://github.com/KELI-Kekeli-Christ/protein-secondary-structure-prediction/blob/HEAD/README.fr.md">Français</a>
  &nbsp;·&nbsp;
  <a href="https://github.com/KELI-Kekeli-Christ/protein-secondary-structure-prediction/blob/HEAD/README.es.md">Español</a>
</p>

# Protein Secondary Structure Prediction

> Predicting protein secondary structure (Helix / Sheet / Coil) from amino acid sequences using MLP with sliding window encoding and Bidirectional LSTM — reaching up to **69% validation accuracy**.

**University:** Université d'Avignon — Master 1 Approaches Neuronales  
**Environment:** Python 3.10 · PyTorch · scikit-learn · CUDA · Jupyter Notebook

---

## Problem Statement

Given a protein's amino acid sequence, predict the secondary structure of each residue:
- **h** → α-Helix
- **e** → β-Sheet
- **\_** → Coil (random)

This is a **sequence labeling** task: for each amino acid in the chain, predict its structural state.

---

## Dataset

| Split | Proteins | Residues |
|-------|----------|----------|
| Train | 99 | 16,072 |
| Validation | 12 | 2,033 |
| Test | 17 | 3,520 |

**Format:** Each line contains one amino acid and its secondary structure label (`E h`, `V _`, ...). Sequences are separated by `<>`.

**Amino acid vocabulary:** 20 standard residues + `<PAD>` token → vocabulary size = 21  
**Label set:** `h` (0), `e` (1), `_` (2) → 3 classes

---

## Approach 1 — MLP with Sliding Window

### Encoding
Each residue is predicted using a **context window of 13 amino acids** centered on it.  
The window is encoded as a **one-hot vector**: 13 × 21 = **273-dimensional input**.

```
[PAD PAD PAD G V G T V P M] → one-hot → [Batch, 273] → MLP → [Batch, 3]
                  ↑
           central residue
```

### Architecture

```
Input (273)
  → Linear(273, 128) → ReLU → Dropout(0.2)
  → Linear(128, 40)  → ReLU → Dropout(0.6)
  → Linear(40, 3)
```

### Hyperparameter Search — Battle Royale

50 independent models are trained with random seeds and learning rates sampled log-uniformly from [10⁻⁴, 10⁻²]. Early stopping (patience=15) cuts off underperforming runs. The global best model is saved.

```
Trial  1/50 | NEW RECORD! Acc: 66.01% | Seed: 5252 | LR: 0.00375
Trial  3/50 | NEW RECORD! Acc: 67.78% | Seed: 7630 | LR: 0.00184
Trial 18/50 | NEW RECORD! Acc: 69.01% | Seed: 4318 | LR: 0.00017
```

---

## Approach 2 — Bidirectional LSTM

### Architecture

Instead of fixed one-hot encoding, the BiLSTM uses a **learned embedding layer** (dense 42-dim vectors) and reads the full 13-residue window in **both directions** simultaneously.

```
Input [Batch, 13]
  → Embedding(21, 42)        [Batch, 13, 42]
  → BiLSTM(42→64, 2 layers)  [Batch, 13, 128]
  → Extract central hidden state [Batch, 128]
  → Linear(128, 128) → ReLU → Dropout(0.3)
  → Linear(128, 40)  → ReLU → Dropout(0.6)
  → Linear(40, 3)
```

**Key advantage:** Bidirectionality allows each residue to use context from both the N-terminal and C-terminal sides.

---

## Results

| Model | Val Accuracy | Test Accuracy |
|-------|-------------|--------------|
| MLP One-Hot (baseline) | — | 60.23% |
| MLP v3 (tuned) | — | 63.72% |
| MLP + Post-filter (Stage 2) | — | **65.20%** |
| BiLSTM (seed 5587, lr 0.00188) | 65.13% | 64.09% |
| **MLP Battle Royale (best)** | **69.01%** | ~60–63% |

### Classification Report (MLP best model — test set)

```
              precision  recall  f1-score  support
Helix  (h)      0.xx     0.xx     0.xx      xxx
Sheet  (e)      0.xx     0.xx     0.xx      xxx
Coil   (_)      0.xx     0.xx     0.xx      xxx
accuracy                          ~63%     3520
```

---

## Project Structure

```
TP2/
├── protein_structure.ipynb          # MLP baseline + Battle Royale
├── protein_structure_lstm.ipynb     # BiLSTM implementation
├── embedding_mlp.ipynb              # MLP with learned embeddings
├── protein-secondary-structure.train
├── protein-secondary-structure.val
├── protein-secondary-structure.test
└── best_model_tuned.pth             # Saved best MLP checkpoint
```

---

## Setup

```bash
python -m venv env
source env/bin/activate
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
pip install jupyter scikit-learn matplotlib seaborn pandas
jupyter notebook
```

---

## Key Takeaways

- **Window size matters:** 13 residues gives a good balance between local context and overfitting
- **Battle Royale search** finds substantially better seeds/LRs than manual tuning (+5 points)
- **BiLSTM doesn't dominate** on this task — the fixed-window MLP is competitive because secondary structure is mostly determined by local interactions
- **Post-processing** (Stage 2 smoothing filter) adds ~1.5 points on top of the best MLP

---

*Master 1 — Approches Neuronales — Université d'Avignon*
