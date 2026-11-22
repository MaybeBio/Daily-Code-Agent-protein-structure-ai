"""
riboseek_scores.py - Kaggle script (CPU): RiboSeek structural-token search as a full score matrix.

OUR RE-IMPLEMENTATION. The team's template-search code is not available (only its results), so the
search is rebuilt here in the same style as the other team methods: the query's PREDICTED RS-20 tokens
(from riboseek-tokens-oof: out-of-fold for train chains, the released model for val/test) are aligned
against every library template's REAL tokens (from its structure), end-gap-free, gap -2, and the
score is divided by the query's length. Three scoring variants are computed:
    rs80_top1    predicted top token + base (RS-80 = RS-20 x 4 + base) vs the template's real RS-80:
                 match +2, mismatch -1 (as the team's `pred_rs80_top1`, their best predicted variant)
    rs20_logodds log(p(template token) / background frequency), clipped to [-3, 3], using the model's
                 full probabilities (closest to the team's `pred_rs20_logp`)
    rs80_logodds as rs20_logodds where the bases agree, -2 where they differ
Positions without a real template token score 0 (log-odds) or count as a mismatch (rs80_top1).
The variant used as method `rs` is chosen BEFORE the selector sees it: the one with the best mean
best-TM@5 on the 1,549 train queries out-of-fold (templates from the other four folds only).
Validation numbers are printed next to the team's reported ones as a sanity check.

Inputs : alizehadeel/riboseek-tokens-oof (token_probs.npz), alizehadeel/riboseek-tokens (tokens_dataset.jsonl),
         alizehadeel/crossfit-towers (twotower_oof.npz), alizehadeel/label-check (pairs_train/val.parquet),
         alizehadeel/build-features (chains.tsv)
Outputs: method_scores_rs.npz (chain_ids, rs), riboseek_variants.npz, riboseek_scores_check.json
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
GAP, CLIP = -2.0, 3.0
BASE = {"A": 0, "C": 1, "G": 2, "U": 3}
MODES = {"rs80_top1": 0, "rs20_logodds": 1, "rs80_logodds": 2}
TEAM_VAL = {"pred_rs80_top1": {"recall@1": 50.5, "recall@5": 59.8, "mean_top1_tm": 0.348},
            "pred_rs20_logp": {"recall@1": 49.5, "recall@5": 59.8, "mean_top1_tm": 0.344},
            "sequence_only": {"recall@1": 67.0, "recall@5": 85.6, "mean_top1_tm": 0.426}}


def find(name):
    hits = sorted(INPUT.rglob(name))
    if not hits:
        sys.exit(f"{name} not found under {INPUT}")
    return hits[0]


@njit(cache=True)
def align(prof, qtop80, qbase, ttok, ttok80, tbase, mode):
    """End-gap-free alignment of a query profile against a template token string; best score."""
    m, n = prof.shape[0], len(ttok)
    prev = np.zeros(n + 1)
    cur = np.zeros(n + 1)
    best = 0.0
    for i in range(m):
        cur[0] = 0.0
        for j in range(1, n + 1):
            tj = ttok[j - 1]
            if mode == 0:
                s = 2.0 if (ttok80[j - 1] >= 0 and qtop80[i] == ttok80[j - 1]) else -1.0
            elif mode == 1:
                s = prof[i, tj] if tj >= 0 else 0.0
            else:
                if qbase[i] != tbase[j - 1]:
                    s = -2.0
                else:
                    s = prof[i, tj] if tj >= 0 else 0.0
            v = prev[j - 1] + s
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
def all_scores(pflat, pstart, qtop80, qbase, qlen, tflat, t80, tb, tstart, tlen, cols, mode):
    nq, nt = len(pstart), len(cols)
    out = np.zeros((nq, nt), dtype=np.float32)
    for a in prange(nq):
        pa, la = pstart[a], qlen[a]
        prof = pflat[pa:pa + la]
        for k in range(nt):
            b = cols[k]
            sb, lb = tstart[b], tlen[b]
            out[a, k] = align(prof, qtop80[pa:pa + la], qbase[pa:pa + la], tflat[sb:sb + lb], t80[sb:sb + lb],
                              tb[sb:sb + lb], mode)
    return out


def best_tm(score, tm, allowed, ks=(1, 5)):
    s = np.where(allowed, score, -np.inf)
    order = np.argsort(-s, axis=1, kind="stable")
    t = np.take_along_axis(np.where(allowed, tm, -1.0), order, 1)
    return {k: np.clip(t[:, :k].max(1), 0, None) for k in ks}


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    ch = pd.read_csv(find("chains.tsv"), sep="\t")
    ids = [str(x) for x in ch.chain_id]
    n = len(ids)
    data = {d["chain_id"]: d for d in (json.loads(line) for line in open(find("tokens_dataset.jsonl")))}
    probs = np.load(find("token_probs.npz"))
    o = np.load(find("twotower_oof.npz"))
    assert [str(x) for x in o["chain_ids"]] == ids
    tr, va, fold = o["train_idx"].astype(int), o["val_idx"].astype(int), o["fold"].astype(int)

    seqs = [data[c]["sequence"] for c in ids]
    tok = [np.array(data[c]["rs20"], dtype=np.int64) for c in ids]
    tok80 = [np.array(data[c]["rs80"], dtype=np.int64) for c in ids]
    base = [np.array([BASE[x] for x in s], dtype=np.int64) for s in seqs]
    lens = np.array([len(s) for s in seqs], dtype=np.int64)
    start = np.r_[0, np.cumsum(lens)[:-1]].astype(np.int64)
    alltr = np.concatenate([tok[i] for i in tr])
    bg = np.bincount(alltr[alltr >= 0], minlength=20).astype(np.float64)
    bg = bg / bg.sum()

    P = [probs[c].astype(np.float32) for c in ids]
    assert all(len(p) == L for p, L in zip(P, lens))
    prof = np.concatenate([np.clip(np.log(p + 1e-6) - np.log(bg[None, :]), -CLIP, CLIP) for p in P]).astype(np.float64)
    qtop80 = np.concatenate([p.argmax(1) * 4 + b for p, b in zip(P, base)]).astype(np.int64)
    qbase = np.concatenate(base)
    tflat, t80, tb = np.concatenate(tok), np.concatenate(tok80), np.concatenate(base)
    cols = tr.astype(np.int64)

    p = pd.read_parquet(find("pairs_train.parquet"), columns=["idx_a", "idx_b", "tm_a", "tm_b"])
    v = pd.read_parquet(find("pairs_val.parquet"), columns=["idx_q", "idx_t", "tm_q"])
    tm = np.full((n, n), np.nan, dtype=np.float32)
    tm[p.idx_a, p.idx_b], tm[p.idx_b, p.idx_a] = p.tm_a, p.tm_b
    tm[v.idx_q, v.idx_t] = v.tm_q
    tm = np.nan_to_num(tm, nan=0.0)
    date = pd.to_datetime(ch.release_date, errors="coerce").to_numpy()
    with np.errstate(invalid="ignore"):
        before = date[None, :] < date[:, None]
    other = fold[tr][:, None] != fold[tr][None, :]

    variants, report = {}, {}
    for name, mode in MODES.items():
        raw = all_scores(prof, start, qtop80, qbase, lens, tflat, t80, tb, start, lens, cols, mode)
        norm = (2.0 * lens[:, None]) if mode == 0 else lens[:, None].astype(np.float64)
        full = np.zeros((n, n), dtype=np.float32)
        full[:, tr] = raw / norm
        variants[name] = full
        r = {}
        for tag, a_tr, a_va in (("none", other, np.ones((len(va), len(tr)), dtype=bool)),
                                ("date", other & before[np.ix_(tr, tr)], before[np.ix_(va, tr)])):
            b_tr = best_tm(full[np.ix_(tr, tr)], tm[np.ix_(tr, tr)], a_tr)
            b_va = best_tm(full[np.ix_(va, tr)], tm[np.ix_(va, tr)], a_va)
            pos = (np.where(a_va, tm[np.ix_(va, tr)], -1) >= 0.45).any(1)
            r[tag] = {"train_oof_best_tm@1": float(b_tr[1].mean()), "train_oof_best_tm@5": float(b_tr[5].mean()),
                      "val_best_tm@1": float(b_va[1].mean()), "val_best_tm@5": float(b_va[5].mean()),
                      "val_recall@1": float((b_va[1][pos] >= 0.45).mean() * 100),
                      "val_recall@5": float((b_va[5][pos] >= 0.45).mean() * 100)}
        report[name] = r
        print(name, json.dumps(r), f"{(time.time() - t0) / 60:.1f} min", flush=True)

    chosen = max(MODES, key=lambda m: report[m]["none"]["train_oof_best_tm@5"])
    np.savez_compressed(WORK / "method_scores_rs.npz", chain_ids=np.array(ids), rs=variants[chosen])
    np.savez_compressed(WORK / "riboseek_variants.npz", chain_ids=np.array(ids), **variants)
    check = {"chosen_variant": chosen, "chosen_by": "train queries out-of-fold, best TM@5, no date filter",
             "variants": report, "team_reported_val": TEAM_VAL, "background_token_freq": bg.round(4).tolist(),
             "minutes": round((time.time() - t0) / 60, 1)}
    (WORK / "riboseek_scores_check.json").write_text(json.dumps(check, indent=1))
    print(json.dumps(check, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
