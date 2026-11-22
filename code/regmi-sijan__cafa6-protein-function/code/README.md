# CAFA 6 Protein Function Prediction: ESM2 + MLP/kNN blend

Predict Gene Ontology terms (MFO / BPO / CCO) from amino-acid sequences for the Kaggle
[CAFA 6](https://www.kaggle.com/competitions/cafa-6-protein-function-prediction) competition.
The competition is closed, so this was never scored on the leaderboard; all numbers below come from a
local holdout.

## Approach
1. `make_labels.py` - parse `go-basic.obo` (is_a + part_of), propagate train labels to ancestors (true-path rule).
2. `embed.py` (+ `run_embed_2gpu.py`) - mean-pooled ESM2 embeddings (fp16) for all sequences:
   ESM2-150M (640-d) and ESM2-650M (1280-d; see the comment at the top of `embed.py`).
3. `train_blend.py` - MLP on the concatenated, standardized embeddings (2 hidden layers of 1536,
   BCE loss, AdamW + OneCycle) blended with cosine-kNN label transfer (k=30, p=12), with a per-ontology
   blend weight; scores are max-propagated up the GO graph; top 100 terms/protein with score >= 0.03.

Validation is a KMeans-cluster holdout (30 of 300 clusters held out) to limit homolog leakage.
The metric is my own simplified IA-weighted max-F1, **not** the official scorer, so treat it as relative.

## Holdout results (mean of BPO/MFO/CCO)
| Model | Mean |
|---|---|
| Frequency prior | 0.32 |
| MLP, ESM2-150M | 0.519 |
| Blend, ESM2-150M | 0.545 |
| MLP, 150M+650M | 0.542 |
| **Blend, 150M+650M** | **0.560** |

Going from 2 to 5 final MLP seeds did not change the holdout score (the holdout uses a single fit).

## Running it
The scripts were written for Kaggle notebooks (2x T4 GPUs) and hard-code Kaggle paths
(`/kaggle/input/...`, `/kaggle/working`). Competition data is not included. Rough order:
`make_labels.py` -> `embed.py` (150M, then 650M) -> `train_blend.py`. Adjust the input paths to wherever
you saved the earlier outputs.

Large outputs (embeddings, `labels.pkl`, `submission_blend.tsv` ~490 MB) are not in the repo
(GitHub's file limit is 100 MB).
