"""
method5_scores.py - Kaggle script (CPU): Method 5 (local element search) as a full score matrix.

Method 5 (method5.zip, method5_local_motif_search.ipynb) splits each query's ViennaRNA fold into
local elements: every outermost base pair (i, j) closes one element, kept if j - i + 1 >= 15.
Each element is searched against every library chain with the same end-gap-free alignment as
Method 4 (match 2, mismatch -1, gap -2), so the element can match anywhere inside a longer template:
    element score = 0.75 * seq_score / (2 * len(element)) + 0.25 * struct_score / (2 * len(element))
Method 5 returns the top 5 templates per element. The selector needs one score per (query, template),
so here
    m5[q, t] = max over q's elements of the element score
(a template ranks high if it matches any one element well). Queries without an element of 15 nt or
more have no score (0): the selector should treat m5 as hit-only (score > 0).

The folds are method4-scores' ViennaRNA 2.8.0 structures (identical to Method 5's for all 1,884 chains).

Inputs : alizehadeel/dataprep (dataset.jsonl), alizehadeel/build-features (chains.tsv),
         alizehadeel/method4-scores (vienna_mfe_structures.csv)
Outputs: method_scores_m5.npz (chain_ids, m5), elements_m5.csv, element_scores_m5.npz, method5_scores_check.json
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
MATCH, MISMATCH, GAP, W_STRUCT, MIN_SEGMENT = 2.0, -1.0, -2.0, 0.25, 15
BASES, DOT = {"A": 0, "C": 1, "G": 2, "U": 3}, {"(": 0, ")": 1, ".": 2}


def find(name):
    hits = sorted(INPUT.rglob(name))
    if not hits:
        sys.exit(f"{name} not found under {INPUT}")
    return hits[0]


def domains(structure, min_length=MIN_SEGMENT):
    """Method 5's element split: every outermost base pair closes one element."""
    found, depth, start = [], 0, None
    for i, c in enumerate(structure):
        if c == "(":
            if depth == 0:
                start = i
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0 and i - start + 1 >= min_length:
                found.append((start, i))
    return found


@njit(cache=True)
def align(q, t):
    n = len(t)
    prev = np.zeros(n + 1)
    cur = np.zeros(n + 1)
    best = 0.0
    for i in range(len(q)):
        cur[0] = 0.0
        a = q[i]
        for j in range(1, n + 1):
            v = prev[j - 1] + (MATCH if a == t[j - 1] else MISMATCH)
            u = prev[j] + GAP
            if u > v:
                v = u
            u = cur[j - 1] + GAP
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
def element_scores(eq, es, estart, elen, tq, ts, tstart, tlen):
    """(elements, chains): 0.75 * seq / perfect + 0.25 * struct / perfect."""
    out = np.zeros((len(estart), len(tstart)), dtype=np.float32)
    for k in prange(len(estart)):
        a, la = estart[k], elen[k]
        perfect = MATCH * la
        for b in range(len(tstart)):
            sb, lb = tstart[b], tlen[b]
            s = align(eq[a:a + la], tq[sb:sb + lb])
            st = align(es[a:a + la], ts[sb:sb + lb])
            out[k, b] = (1 - W_STRUCT) * s / perfect + W_STRUCT * st / perfect
    return out


def pack(strings, alphabet):
    codes = [np.array([alphabet[c] for c in s], dtype=np.int8) for s in strings]
    length = np.array([len(c) for c in codes], dtype=np.int64)
    start = np.r_[0, np.cumsum(length)[:-1]].astype(np.int64)
    return np.concatenate(codes), start, length


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    ch = pd.read_csv(find("chains.tsv"), sep="\t")
    ids = [str(x) for x in ch.chain_id]
    seqs = {}
    for line in open(find("dataset.jsonl")):
        r = json.loads(line)
        seqs[str(r["chain_id"])] = str(r["sequence"]).upper().replace("T", "U")
    folds = pd.read_csv(find("vienna_mfe_structures.csv"), keep_default_na=False)
    struct = dict(zip(folds.chain_id.astype(str), folds.structure))
    seq = [seqs[c] for c in ids]
    st = [struct[c] for c in ids]
    assert all(len(a) == len(b) for a, b in zip(seq, st))

    rows = []
    for qi, c in enumerate(ids):
        for num, (s, e) in enumerate(domains(st[qi]), 1):
            rows.append({"query": qi, "chain_id": c, "segment": num, "start": s, "end": e, "length": e - s + 1,
                         "sequence": seq[qi][s:e + 1], "structure": st[qi][s:e + 1]})
    el = pd.DataFrame(rows)
    el.drop(columns="query").to_csv(WORK / "elements_m5.csv", index=False)
    print(f"{len(el)} elements in {el['query'].nunique()} of {len(ids)} chains", flush=True)

    eq, estart, elen = pack(el.sequence.tolist(), BASES)
    es, _, _ = pack(el.structure.tolist(), DOT)
    tq, tstart, tlen = pack(seq, BASES)
    ts, _, _ = pack(st, DOT)
    E = element_scores(eq, es, estart, elen, tq, ts, tstart, tlen)
    print(f"element search done, {(time.time() - t0) / 60:.1f} min", flush=True)
    np.savez_compressed(WORK / "element_scores_m5.npz", chain_ids=np.array(ids), element_query=el["query"].to_numpy(),
                        scores=E.astype(np.float16))

    m5 = np.zeros((len(ids), len(ids)), dtype=np.float32)
    for qi, g in el.groupby("query"):
        m5[qi] = E[g.index.to_numpy()].max(0)
    np.savez_compressed(WORK / "method_scores_m5.npz", chain_ids=np.array(ids), m5=m5)
    check = {"chains": len(ids), "elements": len(el), "chains_with_elements": int(el["query"].nunique()),
             "element_length_median": float(el.length.median()),
             "share_of_nucleotides_in_elements": float(el.length.sum() / sum(len(s) for s in seq)),
             "minutes": round((time.time() - t0) / 60, 1)}
    (WORK / "method5_scores_check.json").write_text(json.dumps(check, indent=1))
    print(json.dumps(check, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
