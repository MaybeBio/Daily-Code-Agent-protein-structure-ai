"""
method4_scores.py - Kaggle script (CPU): Method 4 (secondary structure, ViennaRNA) as a full score matrix.

Method 4 (all_methods.zip, method4/pipeline.py) ranks templates by
    0.25 * structure_score / (2 * len(q)) + 0.75 * sequence_score / (2 * len(q))
where both scores come from the same alignment: free gaps at both ends, match +2, mismatch -1,
gap -2 (linear). The sequence score aligns the bases A C G U; the structure score aligns the
dot-bracket letters ( ) . of the ViennaRNA minimum-free-energy fold. Weight 0.25 was chosen by
Method 4 on its validation split. Method 4 only scored its 166 test and 122 validation queries;
the selector needs every pair, so this script folds all chains and scores all ~1.8 million pairs
with numba (the alignment score is symmetric, so each pair is aligned once per alphabet).

The DP is the textbook form of method1/pipeline.py `alignment_score`:
    H[0, *] = H[*, 0] = 0,  H[i, j] = max(H[i-1, j-1] + s(i, j), H[i-1, j] + gap, H[i, j-1] + gap)
    score = max(0, max_i H[i, n], max_j H[m, j])

Env: M4_LIMIT=n scores only the first n chains (smoke test).
Inputs : alizehadeel/dataprep (dataset.jsonl), alizehadeel/build-features (chains.tsv)
Outputs: method_scores_m4.npz (chain_ids, m4 = Method 4's combined score, row-normalised by the query),
         parts_m4.npz (chain_ids, seqaln, struct: raw alignment scores; not picked up by the selector),
         vienna_mfe_structures.csv, method4_scores_check.json
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

INPUT = Path(os.environ.get("SV_INPUT", "/kaggle/input"))
WORK = Path(os.environ.get("SV_WORK", "/kaggle/working"))
LIMIT = int(os.environ.get("M4_LIMIT", "0"))
MATCH, MISMATCH, GAP, W_STRUCT = 2.0, -1.0, -2.0, 0.25
BASES, DOT = {"A": 0, "C": 1, "G": 2, "U": 3}, {"(": 0, ")": 1, ".": 2}

try:
    import RNA
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "ViennaRNA==2.8.0"], check=True)
    import RNA

from numba import njit, prange  # noqa: E402


def find(name):
    hits = sorted(INPUT.rglob(name))
    if not hits:
        sys.exit(f"{name} not found under {INPUT}")
    return hits[0]


@njit(cache=True)
def align(q, t, match, mismatch, gap):
    n = len(t)
    prev = np.zeros(n + 1)
    cur = np.zeros(n + 1)
    best = 0.0
    for i in range(len(q)):
        cur[0] = 0.0
        a = q[i]
        for j in range(1, n + 1):
            s = match if a == t[j - 1] else mismatch
            v = prev[j - 1] + s
            u = prev[j] + gap
            if u > v:
                v = u
            u = cur[j - 1] + gap
            if u > v:
                v = u
            cur[j] = v
        if cur[n] > best:
            best = cur[n]
        prev, cur = cur, prev
    for j in range(n + 1):
        if prev[j] > best:
            best = prev[j]
    return best


@njit(parallel=True, cache=True)
def all_pairs(flat, start, length, match, mismatch, gap):
    n = len(start)
    out = np.zeros((n, n), dtype=np.float32)
    for a in prange(n):
        qa = flat[start[a]:start[a] + length[a]]
        for b in range(a, n):
            s = align(qa, flat[start[b]:start[b] + length[b]], match, mismatch, gap)
            out[a, b] = s
            out[b, a] = s
    return out


def pack(strings, alphabet):
    codes = [np.array([alphabet[c] for c in s], dtype=np.int8) for s in strings]
    length = np.array([len(c) for c in codes], dtype=np.int64)
    start = np.r_[0, np.cumsum(length)[:-1]].astype(np.int64)
    return np.concatenate(codes), start, length


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    ch = pd.read_csv(find("chains.tsv"), sep="\t")
    ids = [str(x) for x in ch.chain_id]
    seqs = {}
    for line in open(find("dataset.jsonl")):
        r = json.loads(line)
        seqs[str(r["chain_id"])] = str(r["sequence"]).upper().replace("T", "U")
    if LIMIT:
        ids = ids[:LIMIT]
    seq = [seqs[c] for c in ids]

    t0 = time.time()
    folds = [RNA.fold_compound(s).mfe() for s in seq]
    struct = [f[0] for f in folds]
    pd.DataFrame({"chain_id": ids, "structure": struct, "mfe": [float(f[1]) for f in folds]}).to_csv(
        WORK / "vienna_mfe_structures.csv", index=False)
    fold_s = time.time() - t0
    print(f"ViennaRNA {RNA.__version__}: folded {len(ids)} chains in {fold_s:.0f} s", flush=True)

    t0 = time.time()
    seqaln = all_pairs(*pack(seq, BASES), MATCH, MISMATCH, GAP)
    print(f"sequence alignments done, {time.time() - t0:.0f} s", flush=True)
    st = all_pairs(*pack(struct, DOT), MATCH, MISMATCH, GAP)
    align_s = time.time() - t0
    print(f"structure alignments done, {align_s:.0f} s", flush=True)

    perfect = MATCH * np.array([len(s) for s in seq], dtype=np.float32)[:, None]   # query's self-score
    m4 = (W_STRUCT * st + (1 - W_STRUCT) * seqaln) / perfect
    np.savez_compressed(WORK / "method_scores_m4.npz", chain_ids=np.array(ids), m4=m4.astype(np.float32))
    np.savez_compressed(WORK / "parts_m4.npz", chain_ids=np.array(ids), seqaln=seqaln, struct=st)
    check = {"chains": len(ids), "vienna_version": RNA.__version__, "fold_seconds": round(fold_s, 1),
             "align_seconds": round(align_s, 1), "paired_share": float(np.mean([s.count("(") * 2 / len(s) for s in struct])),
             "m4_offdiag_mean": float(m4[~np.eye(len(ids), dtype=bool)].mean()),
             "self_score_equals_perfect": bool(np.allclose(np.diag(seqaln), perfect[:, 0]))}
    (WORK / "method4_scores_check.json").write_text(json.dumps(check, indent=1))
    print(json.dumps(check, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
