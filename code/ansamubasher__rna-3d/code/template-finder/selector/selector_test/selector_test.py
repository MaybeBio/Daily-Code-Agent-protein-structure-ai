"""
selector_test.py - Kaggle script (CPU): the FINAL test-set evaluation (Step 33), run once.

The current selector (LambdaRank, ten methods, v4 + base-pair features) is trained on the 1,549 train
chains exactly as for validation, then scored on the 176 TEST chains (labels from pairs_test.parquet).
Also: every method on its own, the pool ceiling, the best template in the library, how many test chains
only one method found a good template for, and the selector's test top 5 for RNAPro
(selector_top5_test.csv). Everything labelled "validation" in the shared code means the test chains here.

selector_v6.py - Kaggle script (CPU): training tweaks and ensembles for the selector (Step 29).

Same data, pool (all ten methods), features (new + base pairs) and evaluation as selector_v5; only the
model changes. Reference = the current selector (LambdaRank, the one whose picks went to RNAPro).
Training tweaks (each one change from the reference):
    ranker-steep  gains 2^(label/4) - 1 instead of linear: getting the very best template right counts more
    ranker-t5     LambdaRank looks only at the top 5 (truncation 5 instead of 10), the list we hand on
    ranker-slow   more, smaller trees (1000 x 15 leaves, rate 0.02) on 80% of rows / features each
    regress       plain regression on TM (pointwise, not ranking)
    xendcg        LightGBM's other ranking loss (rank_xendcg)
    trees         the earlier HistGradientBoosting regressor
    bag           five ranker-slow models with different seeds, averaged
Ensembles: each model's scores turned into within-query percentile ranks, then averaged.

(The selector_v5 notes below describe the shared code.)

selector_v5.py - Kaggle script (CPU): the experiment harness for improving the selector.

Fixed: the eight kept methods (twotower, mmseqs, kmer3, john, m4, emb, m2, m5; Steps 19-20), the pool
(top 10 of each, mmseqs and m5 hit-only), evaluations A and B, the paired bootstrap, both date settings.
Reference = the v4 selector (LambdaRank ranker + new features, plain top k). Each improvement step adds
variants and compares them with the reference on the same queries.

Step 1 (this version): diagnosis of the misses. For every query: the pool's best template, the
selector's first pick, where the best was ranked, and the features of both (length, identity, structure
similarity, family, consensus, each method's rank). Then a summary of what the missed best templates
look like compared with what the selector picked instead.

Steps 2 and 3 (this version): coverage features c_* (share of the query and template the sequence
alignment covers, identity on the aligned part, internal gaps) and query features g_* (pool size, how
many different top-1 picks the methods make, share of lone finds, the pool's best consensus / identity /
coverage and each candidate's distance from them, best rank over methods, paired share of the query's
fold, log length). Variants: reference, + coverage, + query, + both (all LambdaRank, plain top 5).

Step 9 brought forward (this version): keep slots for lone finds. The reference model is unchanged;
only how the five templates are chosen from its scores changes (top 1 stays the same):
    lone-score k: top (5 - k) by score, then the k best-scored candidates pooled by one method only
    lone-rank k:  the same, but the lone finds ordered by their rank in the method that found them
    different k:  top (5 - k), then the k best-scored candidates whose structure differs from every
                  one already picked (template-template TM < 0.5)

Step 7 brought forward (this version): base-pair agreement, b_* features. Each library template's REAL
base pairs are read from its 3D structure (chains/<id>.pdb): canonical and G-U pairs whose N1 (purine)
to N3 (pyrimidine) distance is under 3.5 A, at least 4 apart, each residue in at most one pair
(closest first). The query only has its ViennaRNA fold. Through the end-gap-free sequence alignment:
    b_recall      share of the query's predicted pairs that land on real template pairs
    b_precision   share of the template's real pairs (both ends aligned) that land on predicted pairs
    b_compat      share of the template's real pairs whose two aligned query bases can pair (A-U, G-C, G-U)
    b_compat_q    the same count divided by half the query length
    b_struct_true dot-bracket alignment of the query's fold against the template's REAL structure / 2 Lq
    b_tpl_paired  share of the template's residues in a real pair
The query's own structure is never used. Variants: reference, + base-pair features.

Outputs: selector_top5_val.csv (the EXPORT selector's top 5 per validation query, both date settings),
         selector5_variants.csv, selector5_variant_compare.csv, selector5_misses.csv,
         selector5_miss_summary.csv, selector5_metrics.json
"""
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit, prange
from sklearn.ensemble import HistGradientBoostingRegressor

INPUT = Path(os.environ.get("SV_INPUT", "/kaggle/input"))
WORK = Path(os.environ.get("SV_WORK", "/kaggle/working"))
POS_TM, POOL_K, BOOT = 0.45, 10, 2000
KS = (1, 5, 10)
BASE = ["twotower", "mmseqs", "kmer3", "john"]
CANDIDATES = ["m4", "m1", "emb", "m2", "m5", "rs"]
SPARSE = {m for m in os.environ.get("SV_SPARSE", "mmseqs,m5").split(",") if m}   # m5: no element = no score
DIV_THR = 0.6
DIV_GRID = (0.4, 0.5, 0.7, 0.8)
CEIL = "perfect selector (pool)"
OOF = "train queries, out-of-fold"
VAL = "validation (selector trained on train queries)"
T0 = time.time()
BP_CHECK = {}
EXTRA = ("x_", "c_", "g_", "b_")      # x_ = v4 new features, c_ = coverage (step 2), g_ = query (step 3)
FEATSETS = {"v3": (), "new": ("x_",), "new+cov": ("x_", "c_"), "new+qry": ("x_", "g_"),
            "new+cov+qry": ("x_", "c_", "g_"), "new+bp": ("x_", "b_")}
PAIRS = {(0, 3), (3, 0), (1, 2), (2, 1), (2, 3), (3, 2)}   # A-U, G-C, G-U with A0 C1 G2 U3
PAIR_CUTOFF = 3.5
MATCH, MISMATCH, GAP = 2.0, -1.0, -2.0


def log(msg):
    print(f"[{(time.time() - T0) / 60:5.1f} min] {msg}", flush=True)


def find(name, required=True):
    hits = sorted(INPUT.rglob(name))
    if not hits and required:
        sys.exit(f"{name} not found under {INPUT}")
    return hits[0] if hits else None


def z_rows(x, allowed):
    xa = np.where(allowed, x, np.nan)
    with np.errstate(all="ignore"):
        mu, sd = np.nanmean(xa, 1, keepdims=True), np.nanstd(xa, 1, keepdims=True)
    return (x - np.nan_to_num(mu)) / (np.nan_to_num(sd) + 1e-8)


def ranks(score, allowed, rng):
    s = np.where(allowed, score + 1e-6 * rng.random(score.shape), -np.inf)
    order = np.argsort(-s, axis=1, kind="stable")
    r = np.empty_like(order)
    np.put_along_axis(r, order, np.arange(score.shape[1])[None].repeat(len(score), 0), 1)
    return r


def per_query(score, tm, allowed, rng):
    r = ranks(score, allowed, rng)
    t = np.where(allowed, tm, -1.0)
    return {k: np.clip(np.where(r < k, t, -1.0).max(1), 0, None) for k in KS}


# ---------------------------------------------------------------- pool and features


def build(scores, allowed, len_q, len_t, neff_q, rng, ex=None):
    """Pool the top POOL_K of every method; one feature row per (query, candidate).
    `ex` (optional) adds the new features, all named x_*. Returns q, t, X, pool, src (who pooled it)."""
    names = list(scores)
    rk = {m: ranks(scores[m], allowed, rng) for m in names}
    zs = {m: z_rows(scores[m], allowed) for m in names}
    hit = {m: (scores[m] > 0) if m in SPARSE else np.ones(allowed.shape, dtype=bool) for m in names}
    pooled = {m: (rk[m] < POOL_K) & hit[m] & allowed for m in names}
    pool = np.zeros(allowed.shape, dtype=bool)
    for m in names:
        pool |= pooled[m]
    q, t = np.nonzero(pool)
    src = {m: pooled[m][q, t] for m in names}
    X, qbest = {}, {}
    for m in names:
        h = hit[m][q, t]
        X[f"{m}_score"] = scores[m][q, t]
        X[f"{m}_z"] = zs[m][q, t]
        X[f"{m}_logrank"] = np.log1p(rk[m][q, t])
        X[f"{m}_top5"] = ((rk[m][q, t] < 5) & h).astype(np.float32)
        best = np.where(allowed, scores[m], -np.inf).max(1)
        qbest[m] = np.where(np.isfinite(best), best, 0.0)
        X[f"q_{m}_best"] = qbest[m][q]
    X["n_methods_top10"] = sum(src[m].astype(np.float32) for m in names)
    if "mmseqs" in scores:
        mh = scores["mmseqs"] > 0
        X["mmseqs_hit"] = mh[q, t].astype(np.float32)
        X["q_mmseqs_log_hits"] = np.log1p((mh & allowed).sum(1))[q]
    X["len_q"], X["len_t"] = len_q[q].astype(np.float32), len_t[t].astype(np.float32)
    X["len_ratio"] = np.minimum(len_q[q], len_t[t]) / np.maximum(len_q[q], len_t[t])
    if neff_q is not None:
        X["q_log_neff"] = np.log10(np.maximum(neff_q, 1.0))[q]
    if ex is not None:
        X.update(new_features(q, t, scores, allowed, pool, rk, qbest, ex))
        if "codes" in ex:
            X.update(cov_features(q, t, ex))
            X.update(bp_features(q, t, ex))
            X.update(query_features(q, t, X, names, rk, ex, allowed.shape[0]))
    return q, t, pd.DataFrame(X), pool, src


def new_features(q, t, scores, allowed, pool, rk, qbest, ex):
    """Features that describe the pair itself, not which method found it."""
    X = {"x_seq_identity": ex["seqid"][q, t], "x_struct_similarity": ex["struct"][q, t],
         "x_same_family": ex["fam"][q, t].astype(np.float32),
         "x_q_has_family_template": (ex["fam"] & allowed).any(1)[q].astype(np.float32)}
    for m in scores:
        X[f"x_{m}_gap_to_best"] = qbest[m][q] - scores[m][q, t]
    TT = ex["TT"]
    near = (TT >= DIV_THR).astype(np.float32)
    X["x_t_log_fold_size"] = np.log1p((allowed.astype(np.float32) @ near)[q, t])
    fusion = sum(1.0 / (60 + rk[m]) for m in scores)          # rank fusion, needs no training
    cons_pool = np.zeros(len(q), dtype=np.float32)
    cons_top = np.zeros(len(q), dtype=np.float32)
    starts = np.searchsorted(q, np.arange(pool.shape[0]))
    ends = np.searchsorted(q, np.arange(pool.shape[0]), side="right")
    for i in range(pool.shape[0]):
        rows = np.arange(starts[i], ends[i])
        if len(rows) < 2:
            continue
        ts = t[rows]
        sub = TT[np.ix_(ts, ts)].astype(np.float64)
        np.fill_diagonal(sub, np.nan)
        cons_pool[rows] = np.nanmean(sub, 1)
        top = np.argsort(-fusion[i, ts], kind="stable")[:5]
        cons_top[rows] = np.nanmean(sub[:, top], 1)
    X["x_consensus_pool"] = np.nan_to_num(cons_pool)
    X["x_consensus_top5"] = np.nan_to_num(cons_top)
    return X


@njit(cache=True)
def aln_stats(q, t):
    """End-gap-free alignment (match 2, mismatch -1, gap -2) with traceback, as Methods 2 and 4.
    Returns aligned columns, identical columns, internal gap runs, internal gap columns."""
    m, n = len(q), len(t)
    H = np.zeros((m + 1, n + 1))
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            v = H[i - 1, j - 1] + (MATCH if q[i - 1] == t[j - 1] else MISMATCH)
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
    moves = np.zeros(m + n, dtype=np.int8)      # 0 diagonal, 1 gap in template, 2 gap in query
    k = 0
    same = 0
    while i > 0 and j > 0:
        s = MATCH if q[i - 1] == t[j - 1] else MISMATCH
        if H[i, j] == H[i - 1, j - 1] + s:
            if q[i - 1] == t[j - 1]:
                same += 1
            moves[k] = 0
            i -= 1
            j -= 1
        elif H[i, j] == H[i - 1, j] + GAP:
            moves[k] = 1
            i -= 1
        else:
            moves[k] = 2
            j -= 1
        k += 1
    first, last = -1, -1
    for a in range(k):
        if moves[a] == 0:
            if first < 0:
                first = a
            last = a
    aligned, runs, gaps = 0, 0, 0
    if first >= 0:
        prev = 0
        for a in range(first, last + 1):
            if moves[a] == 0:
                aligned += 1
            else:
                gaps += 1
                if prev == 0:
                    runs += 1
            prev = moves[a]
    return aligned, same, runs, gaps


@njit(parallel=True, cache=True)
def pair_stats(flat, start, length, qa, ta):
    out = np.zeros((len(qa), 4))
    for k in prange(len(qa)):
        a, b = qa[k], ta[k]
        r = aln_stats(flat[start[a]:start[a] + length[a]], flat[start[b]:start[b] + length[b]])
        out[k, 0] = r[0]
        out[k, 1] = r[1]
        out[k, 2] = r[2]
        out[k, 3] = r[3]
    return out


@njit(cache=True)
def aln_map(q, t):
    """Same alignment as aln_stats; returns for each query position its template position (-1 = gap)."""
    m, n = len(q), len(t)
    H = np.zeros((m + 1, n + 1))
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            v = H[i - 1, j - 1] + (MATCH if q[i - 1] == t[j - 1] else MISMATCH)
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
    mp = np.full(m, -1, dtype=np.int64)
    while i > 0 and j > 0:
        s = MATCH if q[i - 1] == t[j - 1] else MISMATCH
        if H[i, j] == H[i - 1, j - 1] + s:
            mp[i - 1] = j - 1
            i -= 1
            j -= 1
        elif H[i, j] == H[i - 1, j] + GAP:
            i -= 1
        else:
            j -= 1
    return mp


@njit(cache=True)
def db_score(a, b):
    """End-gap-free alignment score of two dot-bracket codes (0 '(' 1 ')' 2 '.'), as Method 4."""
    n = len(b)
    prev = np.zeros(n + 1)
    cur = np.zeros(n + 1)
    best = 0.0
    for i in range(len(a)):
        cur[0] = 0.0
        for j in range(1, n + 1):
            v = prev[j - 1] + (MATCH if a[i] == b[j - 1] else MISMATCH)
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
def bp_stats(flat, start, length, qpart, tpart, qdb, tdb, qa, ta):
    out = np.zeros((len(qa), 6))
    for k in prange(len(qa)):
        a, b = qa[k], ta[k]
        sa, la, sb, lb = start[a], length[a], start[b], length[b]
        qs, ts = flat[sa:sa + la], flat[sb:sb + lb]
        mp = aln_map(qs, ts)
        qp, tp = qpart[sa:sa + la], tpart[sb:sb + lb]
        inv = np.full(lb, -1, dtype=np.int64)
        for i in range(la):
            if mp[i] >= 0:
                inv[mp[i]] = i
        nq = 0
        hit = 0
        for i in range(la):
            j = qp[i]
            if j > i:
                nq += 1
                if mp[i] >= 0 and mp[j] >= 0 and tp[mp[i]] == mp[j]:
                    hit += 1
        nt_all = 0
        nt_al = 0
        compat = 0
        for x in range(lb):
            y = tp[x]
            if y > x:
                nt_all += 1
                if inv[x] >= 0 and inv[y] >= 0:
                    nt_al += 1
                    u, v = qs[inv[x]], qs[inv[y]]
                    if (u == 0 and v == 3) or (u == 3 and v == 0) or (u == 1 and v == 2) or (u == 2 and v == 1) \
                            or (u == 2 and v == 3) or (u == 3 and v == 2):
                        compat += 1
        paired = 0
        for x in range(lb):
            if tp[x] >= 0:
                paired += 1
        out[k, 0] = hit / max(nq, 1)
        out[k, 1] = hit / max(nt_al, 1)
        out[k, 2] = compat / max(nt_all, 1)
        out[k, 3] = compat / max(la / 2.0, 1.0)
        out[k, 4] = db_score(qdb[sa:sa + la], tdb[sb:sb + lb]) / (2.0 * la)
        out[k, 5] = paired / max(lb, 1)
    return out


def bp_features(q, t, ex):
    """Step 7: does the template's REAL base pairing agree with the query's predicted fold?"""
    flat, start, length = ex["codes"]
    qa, ta = ex["qg"][q].astype(np.int64), ex["tg"][t].astype(np.int64)
    st = bp_stats(flat, start, length, ex["qpart"], ex["tpart"], ex["qdb"], ex["tdb"], qa, ta)
    names = ["b_recall", "b_precision", "b_compat", "b_compat_q", "b_struct_true", "b_tpl_paired"]
    return {nm: st[:, i] for i, nm in enumerate(names)}


def read_real_pairs(path, n_res_seq, seq, cif_idx, seq_pos):
    """Real canonical / G-U base pairs of one chain, as a partner array over sequence positions."""
    res, last = [], None
    for line in open(path):
        if line.startswith("ENDMDL"):
            break
        if line[:6] not in ("ATOM  ", "HETATM"):
            continue
        key = (line[22:26], line[26], line[17:20])
        if key != last:
            res.append({})
            last = key
        name = line[12:16].strip()
        if name in ("N1", "N3"):
            res[-1][name] = (float(line[30:38]), float(line[38:46]), float(line[46:54]))
    xyz = np.full((n_res_seq, 3), np.nan)
    for ci, sp in zip(cif_idx, seq_pos):
        if 0 <= ci < len(res) and 0 <= sp < n_res_seq:
            atom = "N1" if seq[sp] in "AG" else "N3"
            if atom in res[ci]:
                xyz[sp] = res[ci][atom]
    code = np.array(["ACGU".index(c) for c in seq])
    ok = np.isfinite(xyz[:, 0])
    idx = np.where(ok)[0]
    part = np.full(n_res_seq, -1, dtype=np.int64)
    if len(idx) < 2:
        return part, len(res)
    d = np.sqrt(((xyz[idx][:, None, :] - xyz[idx][None, :, :]) ** 2).sum(-1))
    a, b = np.nonzero(np.triu(d < PAIR_CUTOFF, 1))
    cand = sorted((d[x, y], idx[x], idx[y]) for x, y in zip(a, b)
                  if idx[y] - idx[x] >= 4 and (int(code[idx[x]]), int(code[idx[y]])) in PAIRS)
    for _, i, j in cand:
        if part[i] < 0 and part[j] < 0:
            part[i], part[j] = j, i
    return part, len(res)


def partners_from_db(db):
    part, stack = np.full(len(db), -1, dtype=np.int64), []
    for i, c in enumerate(db):
        if c == "(":
            stack.append(i)
        elif c == ")" and stack:
            j = stack.pop()
            part[i], part[j] = j, i
    return part


def db_codes(part):
    return np.array([0 if p > i else (1 if 0 <= p < i else 2) for i, p in enumerate(part)], dtype=np.int8)


def cov_features(q, t, ex):
    """Step 2: how much of the query the template actually covers, and how cleanly."""
    flat, start, length = ex["codes"]
    qa, ta = ex["qg"][q].astype(np.int64), ex["tg"][t].astype(np.int64)
    st = pair_stats(flat, start, length, qa, ta)
    Lq, Lt = length[qa].astype(np.float64), length[ta].astype(np.float64)
    al = np.maximum(st[:, 0], 1.0)
    return {"c_cov_query": st[:, 0] / Lq, "c_cov_template": st[:, 0] / Lt, "c_identity_aligned": st[:, 1] / al,
            "c_gap_runs": st[:, 2], "c_gap_share": st[:, 3] / Lq, "c_matched_share_query": st[:, 1] / Lq}


def query_features(q, t, X, names, rk, ex, nq):
    """Step 3: how hard the query is, and how a candidate stands against the rest of its pool."""
    starts, ends = np.searchsorted(q, np.arange(nq)), np.searchsorted(q, np.arange(nq), side="right")
    keys = ("g_pool_size", "g_top1_distinct", "g_lone_share", "g_max_consensus_top5", "g_max_seq_identity",
            "g_max_cov_query", "g_rel_consensus_top5", "g_rel_seq_identity", "g_rel_cov_query")
    out = {k: np.zeros(len(q), dtype=np.float32) for k in keys}
    cons, ident = np.asarray(X["x_consensus_top5"]), np.asarray(X["x_seq_identity"])
    cov = np.asarray(X["c_cov_query"]) if "c_cov_query" in X else None
    lone = (np.asarray(X["n_methods_top10"]) <= 1).astype(np.float32)
    for i in range(nq):
        r = np.arange(starts[i], ends[i])
        if len(r) == 0:
            continue
        ts = t[r]
        out["g_pool_size"][r] = len(r)
        out["g_top1_distinct"][r] = len({int(ts[np.argmin(rk[m][i, ts])]) for m in names})
        out["g_lone_share"][r] = lone[r].mean()
        out["g_max_consensus_top5"][r] = cons[r].max()
        out["g_max_seq_identity"][r] = ident[r].max()
        out["g_rel_consensus_top5"][r] = cons[r] - cons[r].max()
        out["g_rel_seq_identity"][r] = ident[r] - ident[r].max()
        if cov is not None:
            out["g_max_cov_query"][r] = cov[r].max()
            out["g_rel_cov_query"][r] = cov[r] - cov[r].max()
    out["g_min_method_rank"] = np.log1p(np.min(np.stack([rk[m][q, t] for m in names]), 0)).astype(np.float32)
    out["g_paired_share"] = ex["paired"][ex["qg"][q]].astype(np.float32)
    out["g_log_len_q"] = np.log(ex["codes"][2][ex["qg"][q]]).astype(np.float32)
    return out


# ---------------------------------------------------------------- models and picking


def fit_predict(model, Xa, ya, qa, Xb):
    if model == "trees":
        return HistGradientBoostingRegressor(max_depth=5, max_iter=400, learning_rate=0.05, min_samples_leaf=20,
                                             l2_regularization=1.0, random_state=0).fit(Xa, ya).predict(Xb)
    import lightgbm as lgb
    if model == "regress":
        return lgb.LGBMRegressor(n_estimators=400, learning_rate=0.05, num_leaves=31, min_child_samples=20,
                                 reg_lambda=1.0, random_state=0, verbose=-1).fit(Xa, ya).predict(Xb)
    if model == "bag":
        return np.mean([fit_predict(f"ranker-slow:{s}", Xa, ya, qa, Xb) for s in range(5)], 0)
    lab = np.clip(np.rint(np.asarray(ya) * 20), 0, 20).astype(int)
    _, grp = np.unique(qa, return_counts=True)                 # rows are sorted by query
    kw = dict(objective="lambdarank", n_estimators=400, learning_rate=0.05, num_leaves=31,
              min_child_samples=20, reg_lambda=1.0, label_gain=list(range(21)),
              lambdarank_truncation_level=10, random_state=0, verbose=-1)
    if model == "ranker-steep":
        kw["label_gain"] = [2 ** (g / 4) - 1 for g in range(21)]
    elif model == "ranker-t5":
        kw["lambdarank_truncation_level"] = 5
    elif model.startswith("ranker-slow"):
        seed = int(model.split(":")[1]) if ":" in model else 0
        kw.update(n_estimators=1000, learning_rate=0.02, num_leaves=15, min_child_samples=40, subsample=0.8,
                  subsample_freq=1, colsample_bytree=0.8, random_state=seed)
    elif model == "xendcg":
        kw["objective"] = "rank_xendcg"
        del kw["label_gain"], kw["lambdarank_truncation_level"]
    elif model != "ranker":
        raise ValueError(model)
    return lgb.LGBMRanker(**kw).fit(Xa, lab, group=grp).predict(Xb)


def qrank(pred, q):
    """Within-query percentile rank (0 = worst, 1 = best), so different models can be averaged."""
    return pd.Series(pred).groupby(q).rank(pct=True).to_numpy()


def picks(pred, q, t, nq, TT, thr, kmax=max(KS)):
    """Per query, the template indices picked in order (-1 = none). thr=None: plain top k."""
    P = np.full((nq, kmax), -1, dtype=np.int64)
    starts, ends = np.searchsorted(q, np.arange(nq)), np.searchsorted(q, np.arange(nq), side="right")
    for i in range(nq):
        rows = np.arange(starts[i], ends[i])
        ts = t[rows[np.argsort(-pred[rows], kind="stable")]]
        if thr is None:
            ch = list(ts[:kmax])
        else:
            ch, skipped = [], []
            for x in ts:
                if not ch or TT[x, ch].max() < thr:
                    ch.append(x)
                    if len(ch) == kmax:
                        break
                else:
                    skipped.append(x)
            ch += skipped[:kmax - len(ch)]
        P[i, :len(ch)] = ch
    return P


def pq_from_picks(P, tm):
    got = np.where(P >= 0, np.take_along_axis(tm, np.maximum(P, 0), 1), -1.0)
    return {k: np.clip(got[:, :k].max(1), 0, None) for k in KS}


def summarise(pq, pos):
    out = {}
    for k, v in pq.items():
        out[f"hit@{k}"] = float((v[pos] >= POS_TM).mean()) if pos.any() else float("nan")
        out[f"best_tm@{k}"] = float(v.mean())
    return out


def diff(a, b, pos):
    """a minus b, per query, with a paired bootstrap interval."""
    idx = np.random.default_rng(1).integers(0, len(pos), (BOOT, len(pos)))
    r = {}
    for k in KS:
        d = a[k] - b[k]
        bs = d[idx].mean(1)
        r[f"best_tm@{k}_difference"] = float(d.mean())
        r[f"best_tm@{k}_ci_low"], r[f"best_tm@{k}_ci_high"] = float(np.quantile(bs, 0.025)), float(np.quantile(bs, 0.975))
        r[f"hit@{k}_difference"] = float((a[k][pos] >= POS_TM).mean() - (b[k][pos] >= POS_TM).mean())
        r[f"queries_better_same_worse@{k}"] = f"{int((d > 0.01).sum())}/{int((np.abs(d) <= 0.01).sum())}/{int((d < -0.01).sum())}"
    return r


# ---------------------------------------------------------------- one evaluation


def run(tag, methods, D, a_tr, a_va, variants, with_new):
    """variants: [(name, features 'v3'|'new', model 'trees'|'ranker', diversity threshold or None)]."""
    rng = np.random.default_rng(0)
    tr, va = D["tr"], D["va"]
    s_tr = {m: D["sc_tr"][m] for m in methods}
    s_va = {m: D["sc_va"][m] for m in methods}
    ex_t = ex_v = None
    if with_new:
        common = {"TT": D["TT"], "codes": D["codes"], "paired": D["paired"], "tg": tr,
                  "qpart": D["qpart"], "tpart": D["tpart"], "qdb": D["qdb"], "tdb": D["tdb"]}
        ex_t = {k: D["ex_tr"][k] for k in ("seqid", "struct", "fam")} | common | {"qg": tr}
        ex_v = {k: D["ex_va"][k] for k in ("seqid", "struct", "fam")} | common | {"qg": va}
    nf = D["neff"]
    L = D["len"]
    qt, tt, Xt, pool_t, src_t = build(s_tr, a_tr, L[tr], L[tr], None if nf is None else nf[tr], rng, ex_t)
    qv, tv, Xv, pool_v, src_v = build(s_va, a_va, L[va], L[tr], None if nf is None else nf[va], rng, ex_v)
    yt = D["tm_tr"][qt, tt]
    log(f"[{tag}] {len(Xt)} train rows ({pool_t.sum(1).mean():.1f} per query), {len(Xv)} validation rows "
        f"({pool_v.sum(1).mean():.1f} per query), {Xt.shape[1]} features")
    fq = D["fold_tr"][qt]
    preds = {}
    for feats, model in sorted({(v[1], v[2]) for v in variants if not v[2].startswith("ens:")}):
        cols = [c for c in Xt.columns if not c.startswith(EXTRA) or c.startswith(FEATSETS[feats])]
        pv = fit_predict(model, Xt[cols], yt, qt, Xv[cols])
        po = np.zeros(len(Xt))
        for k in np.unique(D["fold_tr"]):
            te = fq == k
            po[te] = fit_predict(model, Xt.loc[~te, cols], yt[~te], qt[~te], Xt.loc[te, cols])
        preds[(feats, model)] = {VAL: pv, OOF: po}
        log(f"[{tag}] fitted {model} on {feats} features ({len(cols)} columns)")
    for _, feats, model, _ in variants:
        if model.startswith("ens:") and (feats, model) not in preds:
            parts = model[4:].split("+")
            preds[(feats, model)] = {s: np.mean([qrank(preds[(feats, m)][s], qq) for m in parts], 0)
                                     for s, qq in ((VAL, qv), (OOF, qt))}
    res = {}
    for set_name, q, t, tm, al, pool, src, sc in ((VAL, qv, tv, D["tm_va"], a_va, pool_v, src_v, s_va),
                                                   (OOF, qt, tt, D["tm_tr"], a_tr, pool_t, src_t, s_tr)):
        nq = len(tm)
        pos = (np.where(al, tm, -1.0) >= POS_TM).any(1)
        pq, pk = {}, {}
        for name, feats, model, thr in variants:
            pk[name] = picks(preds[(feats, model)][set_name], q, t, nq, D["TT"], thr)
            pq[name] = pq_from_picks(pk[name], tm)
        pq[CEIL] = {k: np.clip(np.where(pool, tm, -1.0).max(1), 0, None) for k in KS}
        pq["john"] = per_query(sc["john"], tm, al, rng)
        res[set_name] = {"pq": pq, "pos": pos, "pool_size": float(pool.sum(1).mean()), "q": q, "t": t, "tm": tm,
                         "src": src, "picks": pk, "preds": {k: v[set_name] for k, v in preds.items()}}
    res["_X"], res["_y"], res["_Xv"] = Xt, yt, Xv
    return res


# ---------------------------------------------------------------- part 2: diagnosis


def diagnose(tag, set_name, R, variant, feats_model):
    """Where did the selector rank the pool's best template, and which methods had pooled it?"""
    q, t, tm, src = R["q"], R["t"], R["tm"], R["src"]
    pred = R["preds"][feats_model]
    best5 = R["pq"][variant][5]
    ceil = R["pq"][CEIL][5]
    rows = []
    starts, ends = np.searchsorted(q, np.arange(len(tm))), np.searchsorted(q, np.arange(len(tm)), side="right")
    for i in range(len(tm)):
        r = np.arange(starts[i], ends[i])
        if len(r) == 0:                                             # no allowed template (date filter)
            continue
        y = tm[i, t[r]]
        order = np.argsort(-pred[r], kind="stable")
        rank = np.empty(len(r), dtype=int)
        rank[order] = np.arange(1, len(r) + 1)
        good = y >= y.max() - 0.01                                  # the best template, or one as good
        j = r[good][np.argmin(rank[good])]
        who = [m for m in src if src[m][j]]
        rows.append({"date_filter": tag, "queries": set_name, "variant": variant, "query": i,
                     "pool_best_tm": float(y.max()), "selector_best_tm@5": float(best5[i]),
                     "missed_by": float(ceil[i] - best5[i]), "rank_of_pool_best": int(rank[good].min()),
                     "pool_size": len(r), "pooled_by": ",".join(who),
                     "only_new_methods": bool(who) and all(m not in BASE for m in who)})
    return rows


def diag_summary(df):
    bins = [0, 1, 5, 10, 20, 10 ** 6]
    labels = ["1", "2-5", "6-10", "11-20", ">20"]
    out = []
    for (tag, qs, var), g in df.groupby(["date_filter", "queries", "variant"], sort=False):
        for who, h in (("all queries", g), ("missed by > 0.05 TM at top 5", g[g.missed_by > 0.05]),
                       ("best template pooled only by new methods", g[g.only_new_methods]),
                       ("... and missed by > 0.05", g[g.only_new_methods & (g.missed_by > 0.05)])):
            c = pd.cut(h.rank_of_pool_best, bins, labels=labels).value_counts().reindex(labels).fillna(0).astype(int)
            out.append({"date_filter": tag, "queries": qs, "variant": var, "group": who, "n": len(h),
                        "mean_missed_by": float(h.missed_by.mean()) if len(h) else 0.0,
                        **{f"rank_{b}": int(c[b]) for b in labels}})
    return pd.DataFrame(out)


# ---------------------------------------------------------------- data


def load():
    o = np.load(find("twotower_oof.npz"))
    ids = [str(x) for x in o["chain_ids"]]
    n = len(ids)
    tr, va, fold = o["train_idx"].astype(int), o["test_idx"].astype(int), o["fold"].astype(int)   # va = TEST chains
    full = {"twotower": o["score"].astype(np.float32)}
    d = np.load(find("method_scores.npz"))
    assert [str(x) for x in d["chain_ids"]] == ids
    full["mmseqs"], full["kmer3"] = d["mmseqs_sensitive"].astype(np.float32), d["kmer3"].astype(np.float32)
    j = np.load(find("method_scores_john.npz"))
    assert [str(x) for x in j["chain_ids"]] == ids
    full["john"] = j["john"].astype(np.float32)
    for name in CANDIDATES:
        path = find(f"method_scores_{name}.npz")
        z = np.load(path)
        assert [str(x) for x in z["chain_ids"]] == ids, f"{path.name} is in a different chain order"
        full[name] = np.nan_to_num(z[name].astype(np.float32), nan=0.0)
        log(f"method '{name}' from {path}")

    ch = pd.read_csv(find("chains.tsv"), sep="\t")
    assert [str(x) for x in ch.chain_id] == ids
    L = ch.seq_len.to_numpy()
    date = pd.to_datetime(ch.release_date, errors="coerce").to_numpy()
    with np.errstate(invalid="ignore"):
        before = date[None, :] < date[:, None]

    p = pd.read_parquet(find("pairs_train.parquet"), columns=["idx_a", "idx_b", "tm_a", "tm_b"])
    v = pd.read_parquet(find("pairs_test.parquet"), columns=["idx_q", "idx_t", "tm_q"])
    tm = np.full((n, n), np.nan, dtype=np.float32)
    tm[p.idx_a, p.idx_b], tm[p.idx_b, p.idx_a] = p.tm_a, p.tm_b
    tm[v.idx_q, v.idx_t] = v.tm_q

    other_fold = fold[tr][:, None] != fold[tr][None, :]
    tm_tr, tm_va = tm[np.ix_(tr, tr)], tm[np.ix_(va, tr)]
    assert not np.isnan(tm_va).any()
    assert not np.isnan(tm_tr[other_fold]).any()
    off = ~np.eye(len(tr), dtype=bool)
    nan_off = int(np.isnan(tm_tr[off]).sum())
    TT = np.nan_to_num((tm_tr + tm_tr.T) / 2, nan=0.0)           # template-template structure similarity
    np.fill_diagonal(TT, 1.0)
    tm_tr = np.nan_to_num(tm_tr, nan=0.0)

    pm = np.load(find("parts_m4.npz"))
    assert [str(x) for x in pm["chain_ids"]] == ids
    norm = 2.0 * L[:, None].astype(np.float32)
    seqid = pm["seqaln"].astype(np.float32) / norm
    struct = pm["struct"].astype(np.float32) / norm
    fam = (full["m1"] - seqid) > 0.5                              # m1 = same family + seqaln / (2 len q)

    sc_tr = {m: s[np.ix_(tr, tr)] for m, s in full.items()}
    sc_va = {m: s[np.ix_(va, tr)] for m, s in full.items()}
    sc_tr["twotower"] = np.nan_to_num(sc_tr["twotower"], nan=0.0)
    neff, mf = None, find("msa_features.npz", required=False)
    if mf is not None:
        m = np.load(mf)
        if [str(x) for x in m["chain_ids"]] == ids:
            neff = m["neff"].astype(np.float32)
    seqs = {}
    for line in open(find("dataset.jsonl")):
        rec = json.loads(line)
        seqs[str(rec["chain_id"])] = str(rec["sequence"]).upper().replace("T", "U")
    codes = [np.array(["ACGU".index(ch) for ch in seqs[cid]], dtype=np.int8) for cid in ids]
    clen = np.array([len(c) for c in codes], dtype=np.int64)
    cstart = np.r_[0, np.cumsum(clen)[:-1]].astype(np.int64)
    vf = pd.read_csv(find("vienna_mfe_structures.csv"), keep_default_na=False)
    mfe = dict(zip(vf.chain_id.astype(str), vf.structure))
    paired = np.array([1 - mfe[cid].count(".") / len(mfe[cid]) for cid in ids], dtype=np.float32)
    qparts = [partners_from_db(mfe[cid]) for cid in ids]
    rmap = pd.read_csv(find("residue_map.tsv"), sep="\t", dtype={"chain_id": str}, keep_default_na=False,
                       na_values=[""], usecols=["chain_id", "seq_pos", "cif_res_index"])
    rmap = {c: g for c, g in rmap.groupby("chain_id", sort=False)}
    ch_dir = next(d for d in INPUT.rglob("chains") if d.is_dir())
    tparts, f1s, nres_ok = [], [], 0
    for k_, cid in enumerate(ids):
        g = rmap[cid]
        tp, nres = read_real_pairs(ch_dir / f"{cid}.pdb", len(seqs[cid]), seqs[cid],
                                   g.cif_res_index.to_numpy(), g.seq_pos.to_numpy() - 1)
        nres_ok += int(nres > 0)
        tparts.append(tp)
        real = {(i, j) for i, j in enumerate(tp) if j > i}
        pred = {(i, j) for i, j in enumerate(qparts[k_]) if j > i}
        f1s.append(2 * len(real & pred) / max(len(real) + len(pred), 1))
    real_paired = np.array([(tp >= 0).mean() for tp in tparts])
    log(f"real base pairs read for {nres_ok} chains: paired share mean {real_paired.mean():.3f} "
        f"(ViennaRNA predicts {paired.mean():.3f}); ViennaRNA vs real pairs F1 mean {np.mean(f1s):.3f}, "
        f"median {np.median(f1s):.3f}; chains with no real pair {int((real_paired == 0).sum())}")
    BP_CHECK.update({"real_paired_share_mean": float(real_paired.mean()), "vienna_paired_share_mean": float(paired.mean()),
                     "vienna_vs_real_f1_mean": float(np.mean(f1s)), "vienna_vs_real_f1_median": float(np.median(f1s)),
                     "chains_with_no_real_pair": int((real_paired == 0).sum())})
    D = {"ids": ids, "codes": (np.concatenate(codes), cstart, clen), "paired": paired, "tr": tr, "va": va,
         "qpart": np.concatenate(qparts), "tpart": np.concatenate(tparts),
         "qdb": np.concatenate([db_codes(p_) for p_ in qparts]), "tdb": np.concatenate([db_codes(p_) for p_ in tparts]), "fold_tr": fold[tr], "len": L, "neff": neff, "tm_tr": tm_tr, "tm_va": tm_va,
         "sc_tr": sc_tr, "sc_va": sc_va, "TT": TT.astype(np.float32),
         "ex_tr": {"seqid": seqid[np.ix_(tr, tr)], "struct": struct[np.ix_(tr, tr)], "fam": fam[np.ix_(tr, tr)]},
         "ex_va": {"seqid": seqid[np.ix_(va, tr)], "struct": struct[np.ix_(va, tr)], "fam": fam[np.ix_(va, tr)]}}
    allowed = {"none": (other_fold, np.ones_like(tm_va, dtype=bool)),
               "date": (other_fold & before[np.ix_(tr, tr)], before[np.ix_(va, tr)])}
    log(f"{len(tr)} train / {len(va)} validation queries | methods {list(full)} | sparse {sorted(SPARSE)} | "
        f"train-train TM missing off the diagonal: {nan_off} | MSA depth {'yes' if neff is not None else 'no'}")
    return D, allowed


# ---------------------------------------------------------------- per-method contribution to the pool


def contribution(D, allowed):
    """For every method: for how many queries is it the only method that pooled the pool's best
    template (so the pool's best TM drops without it), and by how much. Same pool as run()."""
    methods = BASE + CANDIDATES
    rows = []
    for tag, (a_tr, a_va) in allowed.items():
        for set_name, sc, tm, al in ((OOF, D["sc_tr"], D["tm_tr"], a_tr), (VAL, D["sc_va"], D["tm_va"], a_va)):
            rng = np.random.default_rng(0)
            rk = {m: ranks(sc[m], al, rng) for m in methods}          # same random tie-breaks as build()
            pooled = {m: (rk[m] < POOL_K) & ((sc[m] > 0) if m in SPARSE else True) & al for m in methods}
            t = np.where(al, tm, -1.0)
            best_by = {m: np.where(pooled[m], t, -1.0).max(1) for m in methods}
            ceil = np.max(np.stack(list(best_by.values())), 0)
            has = ceil >= 0
            for m in methods:
                without = np.max(np.stack([best_by[o] for o in methods if o != m]), 0)
                drop = np.clip(ceil - np.maximum(without, 0), 0, None) * has
                rows.append({"date_filter": tag, "queries": set_name, "method": m, "n_queries": int(has.sum()),
                             "pools_the_best_template": int((has & (best_by[m] >= ceil)).sum()),
                             "only_method_with_the_best": int((drop > 0).sum()),
                             "only_method_by_more_than_0.01": int((drop > 0.01).sum()),
                             "only_method_by_more_than_0.05": int((drop > 0.05).sum()),
                             "only_method_and_best_tm_at_least_0.45": int(((drop > 0.01) & (ceil >= POS_TM)).sum()),
                             "pool_best_tm_lost_without_it": float(drop.mean())})
    df = pd.DataFrame(rows)
    df.to_csv(WORK / "selector4_method_contribution.csv", index=False)
    print(df.round(4).to_string(index=False), flush=True)
    return df


# ---------------------------------------------------------------- main


FINAL = BASE + ["m4", "emb", "m2", "m5"]
REF = "ranker, new features, plain"
FINAL = BASE + ["m4", "m1", "emb", "m2", "m5", "rs"]   # all ten methods (Step 27; drop decision postponed)
REF = "ranker (current selector)"
_SINGLE = ["ranker", "ranker-steep", "ranker-t5", "ranker-slow", "regress", "xendcg", "trees", "bag"]
_ENS = ["ens:ranker+regress", "ens:ranker+xendcg", "ens:ranker+regress+trees", "ens:ranker+bag+regress",
        "ens:ranker+ranker-steep+ranker-t5+bag+regress+xendcg+trees"]
VARIANTS = [(REF if m == "ranker" else m, "new+bp", m, None) for m in _SINGLE] + \
           [(("ensemble: all seven" if m.count("+") == 6 else "ensemble: " + m[4:].replace("+", " + ")), "new+bp", m, None)
            for m in _ENS]
FEATS = ["len_q", "len_t", "len_ratio", "x_seq_identity", "x_struct_similarity", "x_same_family",
         "x_consensus_pool", "x_consensus_top5", "x_t_log_fold_size", "n_methods_top10"]


HEDGES = []          # Step 23: lone-find slots did not help


def hedge_picks(pred, q, t, nq, X, TT, mode, k, kmax=max(KS)):
    """Top (5 - k) by score, then k hedge slots, then the rest by score (for top 10)."""
    lone = np.asarray(X["n_methods_top10"]) <= 1
    mrank = np.asarray(X["g_min_method_rank"])
    P = np.full((nq, kmax), -1, dtype=np.int64)
    starts, ends = np.searchsorted(q, np.arange(nq)), np.searchsorted(q, np.arange(nq), side="right")
    for i in range(nq):
        r = np.arange(starts[i], ends[i])
        if len(r) == 0:
            continue
        order = r[np.argsort(-pred[r], kind="stable")]
        chosen = list(order[:5 - k])
        rest = [j for j in order if j not in chosen]
        if mode == "lone-score":
            cand = [j for j in rest if lone[j]]
        elif mode == "lone-rank":
            cand = sorted([j for j in rest if lone[j]], key=lambda j: (mrank[j], -pred[j]))
        else:
            cand = [j for j in rest if TT[t[j], [t[c] for c in chosen]].max() < 0.5]
        hedge = cand[:k]
        chosen += hedge
        chosen += [j for j in rest if j not in hedge][:5 - len(chosen)]
        chosen += [j for j in rest if j not in chosen][:kmax - len(chosen)]
        P[i, :len(chosen)] = t[np.array(chosen, dtype=np.int64)]
    return P


def misses(tag, set_name, S, X, D, methods):
    """Per query: the pool's best template vs the selector's first pick, with their features."""
    q, t, tm = S["q"], S["t"], S["tm"]
    pred = S["preds"][("new", "ranker")]
    best5 = S["pq"][REF][5]
    tr = D["tr"]
    starts, ends = np.searchsorted(q, np.arange(len(tm))), np.searchsorted(q, np.arange(len(tm)), side="right")
    out = []
    for i in range(len(tm)):
        r = np.arange(starts[i], ends[i])
        if len(r) == 0:
            continue
        y = tm[i, t[r]]
        order = np.argsort(-pred[r], kind="stable")
        rank = np.empty(len(r), dtype=int)
        rank[order] = np.arange(1, len(r) + 1)
        good = y >= y.max() - 0.01
        jb = r[good][np.argmin(rank[good])]
        jp = r[order[0]]
        rec = {"date_filter": tag, "queries": set_name, "query": i,
               "pool_best_tm": float(y.max()), "pick_tm": float(tm[i, t[jp]]),
               "selector_best_tm@5": float(best5[i]), "missed_by_at_5": float(y.max() - best5[i]),
               "rank_of_best": int(rank[good].min()), "pool_size": len(r),
               "best_template": D["ids"][tr[t[jb]]], "pick_template": D["ids"][tr[t[jp]]],
               "best_pooled_by": ",".join(m for m in methods if S["src"][m][jb]),
               "q_has_family_template": float(X["x_q_has_family_template"].iat[jb]),
               "q_log_neff": float(X["q_log_neff"].iat[jb]) if "q_log_neff" in X else np.nan}
        for who, j in (("best", jb), ("pick", jp)):
            for f in FEATS:
                rec[f"{who}_{f}"] = float(X[f].iat[j])
            for m in methods:
                rec[f"{who}_rank_{m}"] = int(round(np.expm1(X[f"{m}_logrank"].iat[j]))) + 1
        out.append(rec)
    return out


def miss_summary(df, methods):
    """What the missed best templates look like next to the selector's first pick."""
    rows = []
    for (tag, qs), g in df.groupby(["date_filter", "queries"], sort=False):
        groups = {"missed by > 0.05 at top 5": g[g.missed_by_at_5 > 0.05],
                  "not missed (<= 0.01)": g[g.missed_by_at_5 <= 0.01]}
        for name, h in groups.items():
            if not len(h):
                continue
            r = {"date_filter": tag, "queries": qs, "group": name, "n": len(h),
                 "mean_pool_best_tm": h.pool_best_tm.mean(), "mean_pick_tm": h.pick_tm.mean(),
                 "median_rank_of_best": h.rank_of_best.median(),
                 "share_best_ranked_over_20": (h.rank_of_best > 20).mean(),
                 "share_query_has_family_template": h.q_has_family_template.mean()}
            for f in FEATS:
                r[f"best_{f}"] = h[f"best_{f}"].median()
                r[f"pick_{f}"] = h[f"pick_{f}"].median()
            r["share_best_shorter_than_0.7q"] = (h.best_len_ratio < 0.7).mean()
            r["share_best_same_family_pick_not"] = ((h.best_x_same_family > 0) & (h.pick_x_same_family == 0)).mean()
            r["share_best_lower_identity"] = (h.best_x_seq_identity < h.pick_x_seq_identity - 0.1).mean()
            r["share_best_lower_consensus"] = (h.best_x_consensus_pool < h.pick_x_consensus_pool - 0.05).mean()
            r["share_best_pooled_by_one_method"] = (h.best_n_methods_top10 <= 1).mean()
            for m in methods:
                r[f"share_best_in_top5_of_{m}"] = (h[f"best_rank_{m}"] <= 5).mean()
            rows.append(r)
    return pd.DataFrame(rows)


def main_selector():
    WORK.mkdir(parents=True, exist_ok=True)
    D, allowed = load()
    summ, comp, export = [], [], []
    for tag, (a_tr, a_va) in allowed.items():
        R = run(f"final|{tag}", FINAL, D, a_tr, a_va, VARIANTS, True)
        # every variant's top 5 for every validation query, in case one replaces the current selector
        for name, P in R[VAL]["picks"].items():
            for i in range(P.shape[0]):
                for r in range(5):
                    if P[i, r] >= 0:
                        export.append({"variant": name, "date_filter": tag, "target_id": D["ids"][D["va"][i]],
                                       "rank": r + 1, "template": D["ids"][D["tr"][P[i, r]]],
                                       "tm_to_query": float(D["tm_va"][i, P[i, r]])})
        for set_name in (OOF, VAL):
            S = R[set_name]
            for name, pq in S["pq"].items():
                summ.append({"date_filter": tag, "queries": set_name, "variant": name, "pool_size": S["pool_size"],
                             **summarise(pq, S["pos"])})
                if name != REF:
                    comp.append({"date_filter": tag, "queries": set_name, "comparison": f"{name} vs {REF}",
                                 **diff(pq, S["pq"][REF], S["pos"])})
        pd.DataFrame(summ).to_csv(WORK / "selector6_variants.csv", index=False)
        pd.DataFrame(comp).to_csv(WORK / "selector6_variant_compare.csv", index=False)
    pd.DataFrame(export).to_csv(WORK / "selector6_top5_val.csv", index=False)
    (WORK / "selector6_metrics.json").write_text(json.dumps({"methods": FINAL, "reference": REF,
                                                              "variants": [v[0] for v in VARIANTS],
                                                              "minutes": round((time.time() - T0) / 60, 1)}, indent=1))
    pd.set_option("display.width", 250)
    sm = pd.DataFrame(summ)
    print(sm[["date_filter", "queries", "variant", "best_tm@1", "best_tm@5", "hit@5"]].round(4).to_string(index=False))
    cm = pd.DataFrame(comp)
    print(cm[["date_filter", "queries", "comparison", "best_tm@5_difference", "best_tm@5_ci_low",
              "best_tm@5_ci_high", "queries_better_same_worse@5"]].round(4).to_string(index=False), flush=True)
    log("done")
    return 0


TEST = "test chains (selector trained on train chains)"


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    D, allowed = load()
    log(f"TEST chains: {len(D['va'])}; method rows with any score: " +
        ", ".join(f"{m} {int((D['sc_va'][m] != 0).any(1).sum())}" for m in FINAL))
    variants = [(REF, "new+bp", "ranker", None)]
    summ, comp, export, meth = [], [], [], []
    for tag, (a_tr, a_va) in allowed.items():
        R = run(f"test|{tag}", FINAL, D, a_tr, a_va, variants, True)
        S = R[VAL]
        P = S["picks"][REF]
        for i in range(P.shape[0]):
            for r in range(5):
                if P[i, r] >= 0:
                    export.append({"date_filter": tag, "target_id": D["ids"][D["va"][i]], "rank": r + 1,
                                   "template": D["ids"][D["tr"][P[i, r]]], "tm_to_query": float(D["tm_va"][i, P[i, r]])})
        best = np.clip(np.where(a_va, D["tm_va"], -1.0).max(1), 0, None)
        S["pq"]["best template in library"] = {k: best for k in KS}
        for name, pq in S["pq"].items():
            summ.append({"date_filter": tag, "variant": name, "pool_size": S["pool_size"], "chains": len(best),
                         "chains_with_good_template": int(S["pos"].sum()), **summarise(pq, S["pos"])})
        for name in ("john", CEIL):
            comp.append({"date_filter": tag, "comparison": f"selector minus {name}",
                         **diff(S["pq"][REF], S["pq"][name], S["pos"])})
        rng = np.random.default_rng(0)
        for m in FINAL:
            sc = D["sc_va"][m]
            if m in SPARSE:
                r = ranks(sc, a_va, np.random.default_rng(0))
                pq = {k: np.clip(np.where((r < k) & (sc > 0) & a_va, D["tm_va"], -1.0).max(1), 0, None) for k in KS}
            else:
                pq = per_query(sc, D["tm_va"], a_va, rng)
            meth.append({"date_filter": tag, "method": m, **summarise(pq, S["pos"])})
    pd.DataFrame(export).to_csv(WORK / "selector_top5_test.csv", index=False)
    sm, cm, mm = pd.DataFrame(summ), pd.DataFrame(comp), pd.DataFrame(meth)
    sm.to_csv(WORK / "test_selector.csv", index=False)
    cm.to_csv(WORK / "test_selector_compare.csv", index=False)
    mm.to_csv(WORK / "test_methods.csv", index=False)
    ct = contribution(D, allowed)
    ct = ct[ct.queries == VAL]
    ct.to_csv(WORK / "test_method_contribution.csv", index=False)
    pd.set_option("display.width", 250)
    print(sm.round(4).to_string(index=False))
    print(cm.round(4).to_string(index=False))
    print(mm.round(4).to_string(index=False), flush=True)
    log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
