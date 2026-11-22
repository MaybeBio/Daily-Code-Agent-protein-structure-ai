<p align="center">
  <a href="https://github.com/KELI-Kekeli-Christ/protein-structure-rnn-lstm/blob/HEAD/README.md"><b>English</b></a>
  &nbsp;·&nbsp;
  <a href="https://github.com/KELI-Kekeli-Christ/protein-structure-rnn-lstm/blob/HEAD/README.fr.md">Français</a>
  &nbsp;·&nbsp;
  <a href="https://github.com/KELI-Kekeli-Christ/protein-structure-rnn-lstm/blob/HEAD/README.es.md">Español</a>
</p>

# Protein Secondary Structure Prediction — Recurrent Neural Networks

> Predicting protein secondary structure (Helix / Sheet / Coil) using Bidirectional LSTM and GRU architectures with learned embeddings — reaching **60.85% test accuracy**.

**University:** Université d'Avignon — Master 1 Approaches Neuronales  
**Environment:** Python 3.10 · PyTorch · torcheval · Google Colab · Jupyter Notebook

---

## Problem Statement

This project revisits the protein secondary structure prediction task (see also [protein-secondary-structure-mlp](../TP2/)) but from a **sequence modeling perspective**: instead of a fixed-size sliding window, the full protein sequence is processed end-to-end using Recurrent Neural Networks.

For each residue in the sequence, predict:
- **h** → α-Helix
- **e** → β-Sheet
- **\_** → Coil (random)

---

## Dataset

| Split | Proteins | Notes |
|-------|----------|-------|
| Train | 99 | Last 10 proteins reserved for dev set |
| Dev | 10 | Carved out from train for validation |
| Test | 17 | Never seen during training |

**Format:** Protein sequences in file format with `<>` separators. Each line: `<amino_acid> <label>`.

**Vocabulary:** 20 standard amino acids + `<PAD>` (index 0) + `<UNK>` for unseen residues.

---

## Architecture — Bidirectional LSTM / GRU / RNN

The model supports three recurrent cell types (controlled by `rnn_type`):

```
Amino acid indices [Batch, Seq_len]
    ↓
Embedding(vocab_size, emb_size=64)     [Batch, Seq_len, 64]
    ↓
Bidirectional RNN/LSTM/GRU             [Batch, Seq_len, 2×hidden_size]
    ↓
LayerNorm(2×hidden_size)
    ↓
Dropout(0.2)
    ↓
Linear(2×hidden_size → 3)             [Batch, Seq_len, 3]
```

**Key design choices:**
- **Bidirectional**: reads each sequence both left-to-right and right-to-left, doubling the hidden state dimension
- **Xavier uniform initialization** on the linear layer for stable training
- **Padding + masking**: sequences of varying length are padded to the same length in each batch; `ignore_index=-1` in CrossEntropyLoss ignores padded positions
- **`pad_sequence`** handles variable-length proteins inside the DataLoader

### Model Configuration (best result)

| Parameter | Value |
|-----------|-------|
| RNN type | LSTM |
| Embedding size | 64 |
| Hidden size | 64 |
| Num layers | 1 |
| Bidirectional | ✅ |
| Optimizer | AdamW |
| Learning rate | 0.001 |
| Weight decay | 0.001 |
| Epochs | 200 |
| Batch size | 64 |

---

## Training Loop

```python
for epoch in range(nb_epochs):
    model.train()
    for x, y in train_dataloader:
        pred, _ = model.forward(x)      # (B, T, 3)
        pred = pred.permute(0, 2, 1)    # (B, 3, T) — required by CrossEntropyLoss
        loss = loss_fn(pred, y)         # y has -1 for padding
        loss.backward()
        optimizer.step()

    # Validation with masking
    mask = y >= 0                       # True for real residues
    y_clean = y[mask]
    pred_clean = argmax_pred[mask]
    accuracy = MulticlassAccuracy(y_clean, pred_clean)
```

---

## Results

| Model | Dev Accuracy | Test Accuracy |
|-------|-------------|--------------|
| BiLSTM (1 layer, hidden=64) | **59.70%** | **60.85%** |
| MLP sliding window (TP2 reference) | — | 63.72% |
| BiLSTM window-based (TP2) | — | 64.09% |

**Training output (final epoch):**
```
Best model at epoch 199
Dev Accuracy: 0.5970 (59.70%)
Test Accuracy: tensor(0.6085)  →  60.85%
```

### Comparison with Window-Based MLP (TP2)

| Approach | Test Accuracy | Context | Input |
|----------|--------------|---------|-------|
| MLP (one-hot window) | 63.72% | Fixed 13-residue window | 273-dim one-hot |
| BiLSTM (window-based, TP2) | 64.09% | Full sequence | Embeddings |
| **BiLSTM (full sequence, TP4)** | **60.85%** | Full sequence | Embeddings |

The full-sequence BiLSTM is slightly below the window-based approach on this dataset, suggesting that **local context** (captured by the sliding window) is more informative than long-range dependencies for this task.

---

## Project Structure

```
TP4/
├── proteinesLSTM.ipynb          # Full LSTM implementation
├── Coding attention mechanisms.pdf  # Reference paper
└── README.md
```

---

## Setup

```bash
# Local setup
python -m venv env
source env/bin/activate
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
pip install jupyter torcheval-nightly
jupyter notebook proteinesLSTM.ipynb

# Google Colab (used for training)
# Data must be mounted from Google Drive
```

---

## Key Takeaways

1. **Variable-length sequences** require careful handling: padding + masking is essential to avoid teaching the model on `<PAD>` tokens.
2. **`permute` before loss** — PyTorch's `CrossEntropyLoss` expects `(Batch, Classes, Time)`, not `(Batch, Time, Classes)`.
3. **Bidirectionality helps**: accessing both N-terminal and C-terminal context is physically meaningful for secondary structure (α-helices and β-sheets span multiple consecutive residues).
4. **LSTM vs GRU vs RNN**: on this small dataset (99 proteins), performance differences are marginal; LSTM is the most robust choice.
5. **Early stopping via dev set** prevents overfitting on the small training set.

---

*Master 1 — Approches Neuronales — Université d'Avignon*
