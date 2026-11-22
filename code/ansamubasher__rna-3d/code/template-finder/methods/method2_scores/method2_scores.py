"""
method2_scores.py - Kaggle script (CPU): Method 2 (Rfam family lookup) as a full score matrix.

Method 2 (method2.zip, method2_family_lookup_v2.ipynb) takes every library chain that shares an Rfam
family with the query (families from Method 1's cmscan labels) and ranks them by
    1. |log(template length / query length)|, rounded to 0.1 (closest length first),
    2. then identity to the query (matching letters after alignment / query length, higher first),
    3. then release date (most recent first).
"With fallback" fills the rest by the sequence alignment score. Queries with no family get only the
fallback. As one number per pair (higher = better) that ranking is exactly
    family member:  2 + (50 - 10 * length_step) + 0.9 * identity + 0.001 * date_rank
    otherwise:      sequence alignment score / (2 * len(query))          (in [0, 1])
The length step is at most 3.9 here (lengths 3-498), identity steps are >= 1/498 > 0.0011, and
date_rank is in [0, 1), so the three keys never mix.

The alignment and traceback are Method 2's own (end-gap-free, match 2, mismatch -1, gap -2;
traceback prefers diagonal, then query gap), ported to numba. Sequence scores come from
method4-scores (the same alignment).

Inputs : alizehadeel/dataprep (dataset.jsonl), alizehadeel/build-features (chains.tsv),
         alizehadeel/method1-rfam (rfam_hits.csv), alizehadeel/method4-scores (parts_m4.npz)
Outputs: method_scores_m2.npz (chain_ids, m2), method2_scores_check.json
"""
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit, prange

INPUT = Path(os.environ.get("SV_INPUT", "/kaggle/input"))
WORK = Path(os.environ.get("SV_WORK", "/kaggle/working"))
MATCH, MISMATCH, GAP = 2.0, -1.0, -2.0
BASES = {"A": 0, "C": 1, "G": 2, "U": 3}


def find(name):
    hits = sorted(INPUT.rglob(name))
    if not hits:
        sys.exit(f"{name} not found under {INPUT}")
    return hits[0]


@njit(cache=True)
def identity(q, t):
    """Method 2's align(): fill H, pick the end, trace back; matching letters / len(q)."""
    m, n = len(q), len(t)
    H = np.zeros((m + 1, n + 1))
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            s = MATCH if q[i - 1] == t[j - 1] else MISMATCH
            v = H[i - 1, j - 1] + s
            u = H[i - 1, j] + GAP
            if u > v:
                v = u
            u = H[i, j - 1] + GAP
            if u > v:
                v = u
            H[i, j] = v
    end_j = 0
    for j in range(n + 1):
        if H[m, j] > H[m, end_j]:
            end_j = j
    end_i = 0
    for i in range(m + 1):
        if H[i, n] > H[end_i, n]:
            end_i = i
    if H[m, end_j] >= H[end_i, n]:
        i, j = m, end_j
    else:
        i, j = end_i, n
    same = 0
    while i > 0 and j > 0:
        s = MATCH if q[i - 1] == t[j - 1] else MISMATCH
        if abs(H[i, j] - (H[i - 1, j - 1] + s)) <= 1e-8 + 1e-5 * abs(H[i - 1, j - 1] + s):
            if q[i - 1] == t[j - 1]:
                same += 1
            i -= 1
            j -= 1
        elif abs(H[i, j] - (H[i - 1, j] + GAP)) <= 1e-8 + 1e-5 * abs(H[i - 1, j] + GAP):
            i -= 1
        else:
            j -= 1
    return same / m


@njit(parallel=True, cache=True)
def identities(flat, start, length, qa, ta):
    out = np.zeros(len(qa))
    for k in prange(len(qa)):
        a, b = qa[k], ta[k]
        out[k] = identity(flat[start[a]:start[a] + length[a]], flat[start[b]:start[b] + length[b]])
    return out


def pack(strings):
    codes = [np.array([BASES[c] for c in s], dtype=np.int8) for s in strings]
    length = np.array([len(c) for c in codes], dtype=np.int64)
    start = np.r_[0, np.cumsum(length)[:-1]].astype(np.int64)
    return np.concatenate(codes), start, length


def family_part(ids, seqs, dates, hits):
    """Score for every ordered pair sharing an Rfam family; 0 elsewhere. Returns (fam_score, same)."""
    row = {c: i for i, c in enumerate(ids)}
    fams = sorted(set(hits.rfam_id))
    col = {f: k for k, f in enumerate(fams)}
    F = np.zeros((len(ids), max(len(fams), 1)), dtype=np.float32)
    for c, f in zip(hits.chain_id, hits.rfam_id):
        if c in row:
            F[row[c], col[f]] = 1.0
    same = (F @ F.T) > 0
    np.fill_diagonal(same, False)
    qa, ta = np.nonzero(same)
    seq = [seqs[c] for c in ids]
    ident = identities(*pack(seq), qa.astype(np.int64), ta.astype(np.int64))
    L = np.array([len(s) for s in seq], dtype=np.float64)
    step = np.array([round(abs(np.log(L[b] / L[a])), 1) for a, b in zip(qa, ta)])
    d = pd.to_datetime(pd.Series(dates), errors="coerce")
    ordinal = np.array([x.toordinal() if pd.notna(x) else 0 for x in d], dtype=np.float64)
    date_rank = ordinal / (ordinal.max() + 1.0)
    score = np.zeros(same.shape, dtype=np.float64)
    score[qa, ta] = 2.0 + (50.0 - 10.0 * step) + 0.9 * ident + 0.001 * date_rank[ta]
    return score, same, ident


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    ch = pd.read_csv(find("chains.tsv"), sep="\t")
    ids = [str(x) for x in ch.chain_id]
    seqs = {}
    for line in open(find("dataset.jsonl")):
        r = json.loads(line)
        seqs[str(r["chain_id"])] = str(r["sequence"]).upper().replace("T", "U")
    hits = pd.read_csv(find("rfam_hits.csv"))
    p = np.load(find("parts_m4.npz"))
    assert [str(x) for x in p["chain_ids"]] == ids, "parts_m4.npz is in a different chain order"
    L = np.array([len(seqs[c]) for c in ids], dtype=np.float64)
    fallback = p["seqaln"].astype(np.float64) / (2.0 * L[:, None])
    fam, same, ident = family_part(ids, seqs, ch.release_date.astype(str).tolist(), hits)
    m2 = np.where(same, fam, fallback).astype(np.float32)
    np.savez_compressed(WORK / "method_scores_m2.npz", chain_ids=np.array(ids), m2=m2)
    check = {"chains": len(ids), "family_pairs": int(same.sum()), "chains_with_family_partner": int(same.any(1).sum()),
             "mean_identity_family_pairs": float(ident.mean()) if len(ident) else 0.0,
             "fallback_max": float(fallback.max()), "minutes": round((time.time() - t0) / 60, 1)}
    (WORK / "method2_scores_check.json").write_text(json.dumps(check, indent=1))
    print(json.dumps(check, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
