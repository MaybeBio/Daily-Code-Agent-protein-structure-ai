"""
method3_scores.py - Kaggle script (CPU): Method 3 (RibonanzaNet2 embedding similarity) as a full score matrix.

Turns the teammate's per-chain embeddings (ribonanzanet2_mean_l2.npz: `chain_ids`, `vectors`, one mean-pooled
final-layer RibonanzaNet2 vector per chain) into score[q, t] for every pair of our chains, so the selector
can use Method 3 like any other method.

The variant is the one Method 3 chose on its validation split: "standardised" (subtract the mean and divide
by the standard deviation of each dimension, then unit length). The statistics come from the train chains
only, as in method3/pipeline.py `adjusted`. No labels are used, so the scores are honest for every query.
The plain (un-standardised) cosine is saved too, as plain_scores_embplain.npz, which the selector ignores.

Inputs : a dataset with ribonanzanet2_mean_l2.npz, alizehadeel/build-features (chains.tsv)
Outputs: method_scores_emb.npz (chain_ids, emb), plain_scores_embplain.npz, method3_scores_check.json
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

INPUT = Path(os.environ.get("SV_INPUT", "/kaggle/input"))
WORK = Path(os.environ.get("SV_WORK", "/kaggle/working"))


def find(name):
    hits = sorted(INPUT.rglob(name))
    if not hits:
        sys.exit(f"{name} not found under {INPUT}")
    return hits[0]


def unit(X):
    return (X / np.linalg.norm(X, axis=1, keepdims=True)).astype(np.float32)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    ch = pd.read_csv(find("chains.tsv"), sep="\t")
    ids = [str(x) for x in ch.chain_id]
    train = np.where(ch.split.to_numpy() == "train")[0]

    d = np.load(find("ribonanzanet2_mean_l2.npz"), allow_pickle=False)
    order = {str(c): i for i, c in enumerate(d["chain_ids"])}
    missing = [c for c in ids if c not in order]
    if missing:
        sys.exit(f"{len(missing)} chains have no embedding, e.g. {missing[:5]}")
    V = d["vectors"][[order[c] for c in ids]].astype(np.float64)

    mean, sd = V[train].mean(0), V[train].std(0)
    S = unit((V - mean) / np.where(sd > 0, sd, 1.0))
    P = unit(V)
    emb, plain = S @ S.T, P @ P.T
    np.savez_compressed(WORK / "method_scores_emb.npz", chain_ids=np.array(ids), emb=emb)
    # named so the selector does NOT pick it up; rename to method_scores_embplain.npz to try it
    np.savez_compressed(WORK / "plain_scores_embplain.npz", chain_ids=np.array(ids), embplain=plain)

    off = ~np.eye(len(ids), dtype=bool)
    check = {"chains": len(ids), "train_chains_for_statistics": int(len(train)), "dimensions": int(V.shape[1]),
             "embeddings_in_file": int(len(order)), "emb_offdiag_mean": float(emb[off].mean()),
             "emb_offdiag_sd": float(emb[off].std()), "plain_offdiag_mean": float(plain[off].mean()),
             "plain_offdiag_sd": float(plain[off].std())}
    (WORK / "method3_scores_check.json").write_text(json.dumps(check, indent=1))
    print(json.dumps(check, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
