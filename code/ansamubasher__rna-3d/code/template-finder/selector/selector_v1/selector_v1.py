"""
selector_v1.py - Kaggle script (CPU): first template selector, on the validation queries.

Every template-finding method proposes its top 10 templates for a query. The candidates are
pooled (about 25 per query) and a small model scores each (query, candidate) pair from what the
methods say about it; the best-scored candidates are the selected templates.

    methods      two-tower, MMseqs2 (sensitive), 3-mer similarity, john's search (whatever val_method_scores.npz holds)
    features     per method: score, score standardised within the query, rank, in-top-5 flag;
                 how many methods propose the candidate; MMseqs2 hit or not; lengths;
                 per query: its best score under each method, its number of MMseqs2 hits, MSA depth
    target       TM-score of the candidate to the query (normalised by the query)
    models       ridge regression, and small gradient-boosted trees

Honest evaluation with only 159 queries: 5-fold cross-validation where a whole query FAMILY is
held out together, repeated with 5 different fold assignments. Every query is scored by a model
that never saw its family. Nothing is tuned on these scores. The methods' own scores are honest
here because none of them was trained on the validation queries.

The selector is compared with rules that need no training (each method alone, and adding the
standardised scores), and with the perfect selector (always keeps the best pooled candidate).
The difference to the best rule comes with a paired bootstrap interval over queries.
The test split is never read here.

Inputs : alizehadeel/john-search (val_method_scores.npz: every method so far), alizehadeel/label-check (pairs_val.parquet),
         alizehadeel/build-msa-features (msa_features.npz, optional)
Outputs: selector_summary.csv, selector_metrics.json, selector_features.csv, selector_oof.parquet
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

INPUT = Path(os.environ.get("SV_INPUT", "/kaggle/input"))      # overridable for local tests
WORK = Path(os.environ.get("SV_WORK", "/kaggle/working"))
POS_TM, POOL_K, FOLDS, REPEATS, BOOT = 0.45, 10, 5, 5, 2000
SKIP = {"mmseqs_paper"}                                        # the paper setting adds nothing beyond the sensitive one
NICE = {"3-mer_sequence_similarity": "kmer3", "mmseqs_sensitive": "mmseqs", "two-tower": "twotower"}


def find(name, required=True):
    hits = sorted(INPUT.rglob(name))
    if not hits and required:
        sys.exit(f"{name} not found under {INPUT}")
    return hits[0] if hits else None


def z_rows(x, allowed):
    """Standardise each row over its allowed entries."""
    xa = np.where(allowed, x, np.nan)
    return (x - np.nanmean(xa, 1, keepdims=True)) / (np.nanstd(xa, 1, keepdims=True) + 1e-8)


def ranks(score, allowed, rng):
    """0 = best. Ties broken at random; templates that are not allowed go last."""
    s = np.where(allowed, score + 1e-6 * rng.random(score.shape), -np.inf)
    order = np.argsort(-s, axis=1, kind="stable")
    r = np.empty_like(order)
    np.put_along_axis(r, order, np.arange(score.shape[1])[None].repeat(len(score), 0), 1)
    return r


def per_query(score, tm, allowed, rng, ks=(1, 5, 10)):
    """Per-query best TM in the top k of `score` (templates not allowed are removed)."""
    r = ranks(score, allowed, rng)
    t = np.where(allowed, tm, -1.0)
    return {k: np.clip(np.where(r < k, t, -1.0).max(1), 0, None) for k in ks}


def summarise(pq, has_pos):
    out = {}
    for k, v in pq.items():
        out[f"hit@{k}"] = float((v[has_pos] >= POS_TM).mean())
        out[f"best_tm@{k}"] = float(v.mean())
    return out


def build(scores, tm, allowed, len_q, len_t, neff_q, rng):
    """Pool the top POOL_K of every method; one row of features per (query, candidate)."""
    names = list(scores)
    rk = {m: ranks(scores[m], allowed, rng) for m in names}
    zs = {m: z_rows(scores[m], allowed) for m in names}
    pool = np.zeros(tm.shape, dtype=bool)
    for m in names:
        pool |= rk[m] < POOL_K
    pool &= allowed
    q, t = np.nonzero(pool)
    X = {}
    for m in names:
        X[f"{m}_score"] = scores[m][q, t]
        X[f"{m}_z"] = zs[m][q, t]
        X[f"{m}_logrank"] = np.log1p(rk[m][q, t])
        X[f"{m}_top5"] = (rk[m][q, t] < 5).astype(np.float32)
        X[f"q_{m}_best"] = np.where(allowed, scores[m], -np.inf).max(1)[q]
    X["n_methods_top10"] = sum((rk[m][q, t] < POOL_K).astype(np.float32) for m in names)
    if "mmseqs" in scores:
        hit = scores["mmseqs"] > 0
        X["mmseqs_hit"] = hit[q, t].astype(np.float32)
        X["q_mmseqs_log_hits"] = np.log1p((hit & allowed).sum(1))[q]
    X["len_q"], X["len_t"] = len_q[q].astype(np.float32), len_t[t].astype(np.float32)
    X["len_ratio"] = np.minimum(len_q[q], len_t[t]) / np.maximum(len_q[q], len_t[t])
    if neff_q is not None:
        X["q_log_neff"] = np.log10(np.maximum(neff_q, 1.0))[q]
    X = pd.DataFrame(X)
    return q, t, X, pool


def models():
    return {
        "selector (ridge)": lambda: make_pipeline(StandardScaler(), Ridge(alpha=10.0)),
        "selector (boosted trees)": lambda: HistGradientBoostingRegressor(
            max_depth=3, max_iter=150, learning_rate=0.05, min_samples_leaf=20, l2_regularization=1.0, random_state=0),
    }


def run(tag, scores, tm, allowed, fam, len_q, len_t, neff_q):
    rng = np.random.default_rng(0)
    nq = len(tm)
    has_pos = (np.where(allowed, tm, -1.0) >= POS_TM).any(1)
    q, t, X, pool = build(scores, tm, allowed, len_q, len_t, neff_q, rng)
    y = tm[q, t]
    print(f"[{tag}] {nq} queries, {int(has_pos.sum())} with a similar template | {len(X)} candidate rows "
          f"({pool.sum(1).mean():.1f} per query) | {X.shape[1]} features", flush=True)

    rows, pq_all = [], {}

    def add(name, kind, pq):
        pq_all[name] = pq
        rows.append({"date_filter": tag, "method": name, "kind": kind, **summarise(pq, has_pos)})

    # ---- rules that need no training
    zs = {m: z_rows(scores[m], allowed) for m in scores}
    for m in scores:
        add(m, "single method", per_query(scores[m], tm, allowed, rng))
    if len(scores) > 1:
        add("all methods, scores added", "rule", per_query(sum(zs.values()), tm, allowed, rng))
        if {"twotower", "mmseqs"} <= set(scores):
            add("twotower + mmseqs, scores added", "rule", per_query(zs["twotower"] + zs["mmseqs"], tm, allowed, rng))
        rrf = sum(1.0 / (60 + ranks(scores[m], allowed, rng)) for m in scores)
        add("all methods, rank fusion", "rule", per_query(rrf, tm, allowed, rng))
    best_in_pool = np.clip(np.where(pool, tm, -1.0).max(1), 0, None)
    add("perfect selector (pool)", "ceiling", {k: best_in_pool for k in (1, 5, 10)})
    best_any = np.clip(np.where(allowed, tm, -1.0).max(1), 0, None)
    add("best possible (any template)", "ceiling", {k: best_any for k in (1, 5, 10)})

    # ---- selectors: family-grouped cross-validation, repeated
    fams = np.unique(fam)
    oof = {name: np.zeros((REPEATS, len(X)), dtype=np.float32) for name in models()}
    for rep in range(REPEATS):
        order = np.random.default_rng(100 + rep).permutation(fams)
        fold_of = {f: i % FOLDS for i, f in enumerate(order)}
        fold_q = np.array([fold_of[f] for f in fam])
        for fold in range(FOLDS):
            te = fold_q[q] == fold
            for name, make in models().items():
                mdl = make().fit(X[~te], y[~te])
                oof[name][rep, te] = mdl.predict(X[te])
    for name in oof:
        per_rep = []
        for rep in range(REPEATS):
            S = np.full(tm.shape, -1e9, dtype=np.float64)
            S[q, t] = oof[name][rep]
            per_rep.append(per_query(S, tm, pool, rng))
        add(name, "selector", {k: np.mean([p[k] for p in per_rep], 0) for k in (1, 5, 10)})

    # ---- paired bootstrap: selector minus the best rule, per query
    rules = [r["method"] for r in rows if r["kind"] in ("single method", "rule")]
    best_rule = max(rules, key=lambda m: pq_all[m][5].mean())
    brng, compare = np.random.default_rng(1), {}
    idx = brng.integers(0, nq, (BOOT, nq))
    for name in oof:
        compare[name] = {"best_rule": best_rule}
        for k in (1, 5, 10):
            d = pq_all[name][k] - pq_all[best_rule][k]
            b = d[idx].mean(1)
            compare[name][f"best_tm@{k}_difference"] = float(d.mean())
            compare[name][f"best_tm@{k}_ci95"] = [float(np.quantile(b, 0.025)), float(np.quantile(b, 0.975))]
            compare[name][f"best_tm@{k}_queries_better_same_worse"] = [int((d > 0.01).sum()), int((np.abs(d) <= 0.01).sum()), int((d < -0.01).sum())]

    # ---- which features the ridge selector leans on (fitted on everything, for reading only)
    ridge = make_pipeline(StandardScaler(), Ridge(alpha=10.0)).fit(X, y)
    feats = pd.DataFrame({"date_filter": tag, "feature": X.columns, "ridge_weight": ridge[-1].coef_,
                          "correlation_with_tm": [float(np.corrcoef(X[c], y)[0, 1]) if X[c].std() > 0 else 0.0 for c in X.columns]})
    feats = feats.reindex(feats.ridge_weight.abs().sort_values(ascending=False).index)
    out = pd.DataFrame({"date_filter": tag, "q": q, "t": t, "tm": y,
                        **{name.replace(" ", "_"): oof[name].mean(0) for name in oof}})
    return rows, compare, feats, out


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    d = np.load(find("val_method_scores.npz"))
    val_ids, train_ids = [str(x) for x in d["val_ids"]], [str(x) for x in d["train_ids"]]
    tm, dated = d["tm"].astype(np.float32), d["dated"].astype(bool)
    scores = {NICE.get(k, k): d[k].astype(np.float32) for k in d.files
              if k not in ("val_ids", "train_ids", "tm", "dated") and k not in SKIP}
    print("methods:", list(scores), "| queries x templates:", tm.shape, flush=True)

    cols = pd.read_parquet(find("pairs_val.parquet")).columns
    want = [c for c in ("query", "template", "len_q", "len_t", "fam_q") if c in cols]
    pv = pd.read_parquet(find("pairs_val.parquet"), columns=want)
    qinfo, tinfo = pv.drop_duplicates("query").set_index("query"), pv.drop_duplicates("template").set_index("template")
    len_q, len_t = qinfo.len_q.reindex(val_ids).to_numpy(), tinfo.len_t.reindex(train_ids).to_numpy()
    assert not (np.isnan(len_q).any() or np.isnan(len_t).any()), "a chain has no length in pairs_val.parquet"
    fam = qinfo.fam_q.reindex(val_ids).to_numpy() if "fam_q" in qinfo else np.arange(len(val_ids))
    print("query families:", len(np.unique(fam)), flush=True)
    neff_q, mf = None, find("msa_features.npz", required=False)
    if mf is not None:
        m = np.load(mf)
        neff = dict(zip((str(x) for x in m["chain_ids"]), m["neff"]))
        if all(v in neff for v in val_ids):
            neff_q = np.array([neff[v] for v in val_ids], dtype=np.float32)

    summary, metrics, feats, oofs = [], {"pool_k": POOL_K, "folds": FOLDS, "repeats": REPEATS, "compare": {}}, [], []
    for tag, allowed in (("none", np.ones_like(dated)), ("date", dated)):
        rows, compare, f, o = run(tag, scores, tm, allowed, fam, len_q, len_t, neff_q)
        summary += rows
        metrics["compare"][tag] = compare
        feats.append(f)
        oofs.append(o)
        pd.DataFrame(summary).to_csv(WORK / "selector_summary.csv", index=False)
    metrics["summary"] = summary
    (WORK / "selector_metrics.json").write_text(json.dumps(metrics, indent=2))
    pd.concat(feats).to_csv(WORK / "selector_features.csv", index=False)
    pd.concat(oofs).to_parquet(WORK / "selector_oof.parquet", index=False)
    print(pd.DataFrame(summary).round(3).to_string(index=False), flush=True)
    print(json.dumps(metrics["compare"], indent=1), flush=True)
    print(pd.concat(feats).round(3).to_string(index=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
