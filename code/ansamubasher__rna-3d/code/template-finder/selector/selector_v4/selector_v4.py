"""
selector_v4.py - Kaggle script (CPU): new keep rule for methods, then a selector that is better at picking.

Part 1. Keep rule (version 5 of this notebook, Step 25): a method is kept if it is the only source of a
    good template (pool best TM >= 0.45, lost by more than 0.01 without it) for MORE train queries
    (out-of-fold) than a random method gets, with and without the date filter, and the selector does not
    get significantly worse with it. The random method pools 10 random allowed templates per
    query on top of all real methods; the bar is the largest count over 20 random seeds.
    Earlier rule (Steps 19-24, still reported as pool_gain_significant):
    A method is kept if it adds better templates to the pool, i.e. the "perfect selector (pool)"
    best TM rises with a 95% paired-bootstrap interval above zero, AND the selector does not get
    significantly worse (top-5 interval not entirely below zero). Both are judged on the 1,549 train
    queries out-of-fold (evaluation B), with and without the date filter.
    Each candidate method (Method 4 = m4, Method 1 = m1, Method 3 = emb) is tested leave-one-out:
    "all methods" against "all methods except this one", so it must add something nobody else finds.

Part 2. Diagnosis: for every query, where did the selector rank the best template in the pool, and
    which methods had pooled it? Shown overall, for queries the selector misses by > 0.05 TM, and for
    queries whose best template only a new method (m4 / m1 / emb) pooled.

Part 3. Selector variants, every combination of three changes (judged like the methods):
    * pick:     "plain" = top k by score; "diverse" = top k skipping a template whose structure is very
                similar (template-template TM >= 0.6) to one already picked (best-of-k rewards variety).
    * model:    "trees" = the v3 larger boosted trees, predicting each candidate's TM (regression);
                "ranker" = LightGBM LambdaRank, trained per query to get the top of the list right.
    * features: "v3" = the v3 features; "new" adds features that do not depend on which method found
                the template: sequence identity, secondary-structure similarity, same Rfam family,
                distance from the query's best score per method, and structural consensus (how similar
                the candidate's structure is to the other pooled / top-5 candidates, and how many
                library templates share its fold).
    Template-template TM uses only library structures (known at prediction time), never the query.

Unchanged from v3: pool = top 10 of every method; evaluation A (fit on 1,549 train queries, score
the 159 validation queries) and B (5-fold out-of-fold on the train queries, same family folds as
the two-tower); paired bootstrap, 2,000 resamples; the test split is never read.
Changed: mmseqs is "hit-only" (its zero-score non-hits are no longer pooled at random), so adding a
method no longer shuffles random filler templates in and out of the pool.

Inputs : as selector_v3, plus alizehadeel/method4-scores (parts_m4.npz) for the new features.
Outputs: selector4_keep.csv, selector4_keep_compare.csv, selector4_diagnosis.csv,
         selector4_diagnosis_summary.csv, selector4_variants.csv, selector4_variant_compare.csv,
         selector4_new_features.csv, selector4_metrics.json
"""
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

INPUT = Path(os.environ.get("SV_INPUT", "/kaggle/input"))
WORK = Path(os.environ.get("SV_WORK", "/kaggle/working"))
POS_TM, POOL_K, BOOT = 0.45, 10, 2000
KS = (1, 5, 10)
BASE = ["twotower", "mmseqs", "kmer3", "john"]
CANDIDATES = ["m4", "m1", "emb", "m2", "m5", "rs"]
SPARSE = {m for m in os.environ.get("SV_SPARSE", "mmseqs,m5").split(",") if m}   # m5: no element = no score
N_RANDOM = 20       # random-method seeds: the keep rule's chance baseline
USABLE = "only_method_and_best_tm_at_least_0.45"
DIV_THR = 0.6
DIV_GRID = (0.4, 0.5, 0.7, 0.8)
CEIL = "perfect selector (pool)"
OOF = "train queries, out-of-fold"
VAL = "validation (selector trained on train queries)"
T0 = time.time()


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


# ---------------------------------------------------------------- models and picking


def fit_predict(model, Xa, ya, qa, Xb):
    if model == "trees":
        return HistGradientBoostingRegressor(max_depth=5, max_iter=400, learning_rate=0.05, min_samples_leaf=20,
                                             l2_regularization=1.0, random_state=0).fit(Xa, ya).predict(Xb)
    import lightgbm as lgb
    lab = np.clip(np.rint(np.asarray(ya) * 20), 0, 20).astype(int)
    _, grp = np.unique(qa, return_counts=True)                 # rows are sorted by query
    r = lgb.LGBMRanker(objective="lambdarank", n_estimators=400, learning_rate=0.05, num_leaves=31,
                       min_child_samples=20, reg_lambda=1.0, label_gain=list(range(21)),
                       lambdarank_truncation_level=10, random_state=0, verbose=-1)
    return r.fit(Xa, lab, group=grp).predict(Xb)


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
        ex_t = {k: D["ex_tr"][k] for k in ("seqid", "struct", "fam")} | {"TT": D["TT"]}
        ex_v = {k: D["ex_va"][k] for k in ("seqid", "struct", "fam")} | {"TT": D["TT"]}
    nf = D["neff"]
    L = D["len"]
    qt, tt, Xt, pool_t, src_t = build(s_tr, a_tr, L[tr], L[tr], None if nf is None else nf[tr], rng, ex_t)
    qv, tv, Xv, pool_v, src_v = build(s_va, a_va, L[va], L[tr], None if nf is None else nf[va], rng, ex_v)
    yt = D["tm_tr"][qt, tt]
    log(f"[{tag}] {len(Xt)} train rows ({pool_t.sum(1).mean():.1f} per query), {len(Xv)} validation rows "
        f"({pool_v.sum(1).mean():.1f} per query), {Xt.shape[1]} features")
    fq = D["fold_tr"][qt]
    preds = {}
    for feats, model in sorted({(v[1], v[2]) for v in variants}):
        cols = [c for c in Xt.columns if feats == "new" or not c.startswith("x_")]
        pv = fit_predict(model, Xt[cols], yt, qt, Xv[cols])
        po = np.zeros(len(Xt))
        for k in np.unique(D["fold_tr"]):
            te = fq == k
            po[te] = fit_predict(model, Xt.loc[~te, cols], yt[~te], qt[~te], Xt.loc[te, cols])
        preds[(feats, model)] = {VAL: pv, OOF: po}
        log(f"[{tag}] fitted {model} on {feats} features ({len(cols)} columns)")
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
    res["_X"], res["_y"] = Xt, yt
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
    tr, va, fold = o["train_idx"].astype(int), o["val_idx"].astype(int), o["fold"].astype(int)
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
    v = pd.read_parquet(find("pairs_val.parquet"), columns=["idx_q", "idx_t", "tm_q"])
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
    D = {"tr": tr, "va": va, "fold_tr": fold[tr], "len": L, "neff": neff, "tm_tr": tm_tr, "tm_va": tm_va,
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
            for seed in range(N_RANDOM):
                # a method that pools 10 random allowed templates per query, added on top of all real methods
                rr = np.random.default_rng(1000 + seed).random(al.shape)
                rpool = (np.argsort(np.argsort(-np.where(al, rr, -1.0), 1), 1) < POOL_K) & al
                best_r = np.where(rpool, t, -1.0).max(1)
                gain = np.clip(best_r - ceil, 0, None) * has
                new_ceil = np.maximum(ceil, best_r)
                rows.append({"date_filter": tag, "queries": set_name, "method": f"random_{seed}",
                             "n_queries": int(has.sum()),
                             "pools_the_best_template": int((has & (best_r >= new_ceil)).sum()),
                             "only_method_with_the_best": int((gain > 0).sum()),
                             "only_method_by_more_than_0.01": int((gain > 0.01).sum()),
                             "only_method_by_more_than_0.05": int((gain > 0.05).sum()),
                             "only_method_and_best_tm_at_least_0.45": int(((gain > 0.01) & (new_ceil >= POS_TM)).sum()),
                             "pool_best_tm_lost_without_it": float(gain.mean())})
    df = pd.DataFrame(rows)
    df.to_csv(WORK / "selector4_method_contribution.csv", index=False)
    print(df.round(4).to_string(index=False), flush=True)
    return df


# ---------------------------------------------------------------- main


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    D, allowed = load()
    metrics = {"pool_k": POOL_K, "sparse": sorted(SPARSE), "diversity_threshold": DIV_THR}
    contrib = contribution(D, allowed)
    oof = contrib[contrib.queries == OOF]
    rnd = oof[oof.method.str.startswith("random_")]
    bar = {tg: int(rnd[rnd.date_filter == tg][USABLE].max()) for tg in allowed}
    rand_summary = {tg: {"mean": float(rnd[rnd.date_filter == tg][USABLE].mean()),
                         "max": bar[tg]} for tg in allowed}
    real = oof[~oof.method.str.startswith("random_")].pivot(index="method", columns="date_filter", values=USABLE)
    rule = pd.DataFrame({"method": real.index, **{f"usable_unique_{tg}": real[tg].to_numpy() for tg in allowed},
                         **{f"random_max_{tg}": bar[tg] for tg in allowed},
                         **{f"random_mean_{tg}": round(rand_summary[tg]["mean"], 2) for tg in allowed}})
    rule["beats_random"] = np.all([rule[f"usable_unique_{tg}"] > bar[tg] for tg in allowed], axis=0)
    rule.to_csv(WORK / "selector4_rule_vs_random.csv", index=False)
    print(rule.to_string(index=False), flush=True)
    metrics["random_baseline"] = rand_summary
    if os.environ.get("SV_ONLY_CONTRIBUTION"):
        return 0

    # ---- part 1: keep rule, leave one out
    sets = {"all": BASE + CANDIDATES, **{f"all-{m}": BASE + [c for c in CANDIDATES if c != m] for m in CANDIDATES}}
    sel = [("selector", "v3", "trees", None)]
    keep_rows, R1 = [], {}
    for tag, (a_tr, a_va) in allowed.items():
        for name, methods in sets.items():
            R1[(tag, name)] = run(f"{name}|{tag}", methods, D, a_tr, a_va, sel, False)
        for m in CANDIDATES:
            for set_name in (OOF, VAL):
                A, B = R1[(tag, "all")][set_name], R1[(tag, f"all-{m}")][set_name]
                for what in ("selector", CEIL):
                    keep_rows.append({"date_filter": tag, "queries": set_name, "method": m, "compared": what,
                                      "pool_size": A["pool_size"], "pool_size_without": B["pool_size"],
                                      **diff(A["pq"][what], B["pq"][what], A["pos"])})
    kc = pd.DataFrame(keep_rows)
    kc.to_csv(WORK / "selector4_keep_compare.csv", index=False)
    decide = []
    for m in CANDIDATES:
        b = kc[(kc.method == m) & (kc.queries == OOF)]
        pool_ok = all(b[(b.compared == CEIL) & (b.date_filter == tg)]["best_tm@5_ci_low"].iloc[0] > 0 for tg in allowed)
        sel_ok = all(b[(b.compared == "selector") & (b.date_filter == tg)]["best_tm@5_ci_high"].iloc[0] >= 0 for tg in allowed)
        g = b.set_index(["compared", "date_filter"])
        beats = bool(rule.set_index("method").loc[m, "beats_random"])
        decide.append({"method": m, "keep": bool(beats and sel_ok), "beats_random": beats,
                       "pool_gain_significant": pool_ok,
                       "selector_not_worse": sel_ok,
                       **{f"pool_gain_{tg}": f"{g.loc[(CEIL, tg), 'best_tm@5_difference']:+.4f} "
                                             f"[{g.loc[(CEIL, tg), 'best_tm@5_ci_low']:+.4f}, {g.loc[(CEIL, tg), 'best_tm@5_ci_high']:+.4f}]"
                          for tg in allowed},
                       **{f"queries_improved_in_pool_{tg}": g.loc[(CEIL, tg), "queries_better_same_worse@5"] for tg in allowed},
                       **{f"selector_top5_{tg}": f"{g.loc[('selector', tg), 'best_tm@5_difference']:+.4f} "
                                                 f"[{g.loc[('selector', tg), 'best_tm@5_ci_low']:+.4f}, {g.loc[('selector', tg), 'best_tm@5_ci_high']:+.4f}]"
                          for tg in allowed}})
    keep = pd.DataFrame(decide)
    keep.to_csv(WORK / "selector4_keep.csv", index=False)
    print(keep.to_string(index=False), flush=True)
    final = BASE + [m for m in CANDIDATES if keep.set_index("method").loc[m, "keep"]]
    metrics["final_methods"] = final
    log(f"final method set: {final}")

    # ---- parts 2 and 3: selector variants on the final set
    variants = []
    for feats in ("v3", "new"):
        for model in ("trees", "ranker"):
            for thr in (None, DIV_THR):
                name = f"{model}, {'v3' if feats == 'v3' else 'new'} features, {'plain' if thr is None else 'diverse'}"
                variants.append((name, feats, model, thr))
    for thr in DIV_GRID:
        variants.append((f"trees, v3 features, diverse {thr}", "v3", "trees", thr))
    REF = "trees, v3 features, plain"
    steps = [("diverse picking", "trees, v3 features, diverse", REF),
             ("ranker (with diverse picking)", "ranker, v3 features, diverse", "trees, v3 features, diverse"),
             ("new features (ranker, diverse)", "ranker, new features, diverse", "ranker, v3 features, diverse"),
             ("new features (trees, diverse)", "trees, new features, diverse", "trees, v3 features, diverse"),
             ("ranker (plain)", "ranker, v3 features, plain", REF),
             ("new features (trees, plain)", "trees, new features, plain", REF)]
    summ, comp, diag, featrows = [], [], [], []
    for tag, (a_tr, a_va) in allowed.items():
        R = run(f"final|{tag}", final, D, a_tr, a_va, variants, True)
        for set_name in (OOF, VAL):
            S = R[set_name]
            for name, pq in S["pq"].items():
                summ.append({"date_filter": tag, "queries": set_name, "variant": name, "pool_size": S["pool_size"],
                             **summarise(pq, S["pos"])})
                if name not in (REF, CEIL):
                    comp.append({"date_filter": tag, "queries": set_name, "comparison": f"{name} vs {REF}",
                                 **diff(pq, S["pq"][REF], S["pos"])})
            for step, a, b in steps:
                comp.append({"date_filter": tag, "queries": set_name, "comparison": f"STEP {step}: {a} vs {b}",
                             **diff(S["pq"][a], S["pq"][b], S["pos"])})
            diag += diagnose(tag, set_name, S, REF, ("v3", "trees"))
            diag += diagnose(tag, set_name, S, "ranker, new features, diverse", ("new", "ranker"))
        X, y = R["_X"], R["_y"]
        for c in [c for c in X.columns if c.startswith("x_")]:
            featrows.append({"date_filter": tag, "feature": c,
                             "correlation_with_tm": float(np.corrcoef(X[c], y)[0, 1]) if X[c].std() > 0 else 0.0})
        pd.DataFrame(summ).to_csv(WORK / "selector4_variants.csv", index=False)
        pd.DataFrame(comp).to_csv(WORK / "selector4_variant_compare.csv", index=False)
    dg = pd.DataFrame(diag)
    dg.to_csv(WORK / "selector4_diagnosis.csv", index=False)
    ds = diag_summary(dg)
    ds.to_csv(WORK / "selector4_diagnosis_summary.csv", index=False)
    pd.DataFrame(featrows).to_csv(WORK / "selector4_new_features.csv", index=False)
    metrics["keep"] = decide
    metrics["minutes"] = round((time.time() - T0) / 60, 1)
    (WORK / "selector4_metrics.json").write_text(json.dumps(metrics, indent=1))

    pd.set_option("display.width", 250)
    sm = pd.DataFrame(summ)
    print(sm[["date_filter", "queries", "variant", "best_tm@1", "best_tm@5", "hit@5"]].round(4).to_string(index=False))
    cp = pd.DataFrame(comp)
    print(cp[["date_filter", "queries", "comparison"] + [f"best_tm@{k}_{s}" for k in (1, 5) for s in ("difference", "ci_low", "ci_high")]]
          .round(4).to_string(index=False))
    print(ds.round(3).to_string(index=False), flush=True)
    log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
