"""
selector_v3.py - Kaggle script (CPU): selector_v2 with a pluggable list of template-finding methods.

What is new against selector_v2 (everything else is unchanged, so the "base" set reproduces v2):
  * Extra methods: any input file method_scores_<name>.npz holding `chain_ids` (chains.tsv order) and a
    full (n, n) array `<name>` with score[q, t], higher = better, is picked up automatically.
  * Method sets: SV_CONFIGS="base=twotower,mmseqs,kmer3,john;emb=twotower,mmseqs,kmer3,john,emb".
    Default: "base", then base + each extra method found, then everything if there are two or more.
    Every set is trained and evaluated exactly like v2, and each set's larger tree selector is compared
    with the first set's on the same queries (paired bootstrap): this is the "does the method help" test.
  * Hit-only pooling: SV_SPARSE="mmseqs,emb" lists methods for which a score <= 0 means "no hit".
    Their non-hits are not pooled and do not count as top 5 / top 10. Default empty (= v2 behaviour).

Outputs: selector3_summary.csv, selector3_metrics.json, selector3_config_compare.csv,
         selector3_features.csv, selector3_val_scores.parquet

--- selector_v2 description (unchanged) ---
Same selector as selector_v1 (pool the top 10 of every method, score each pooled candidate from
what the methods say about it), but it no longer has to learn from the 159 validation queries.
The 5-fold two-tower run gave honest two-tower scores for all 1,549 train chains, and the other
methods (MMseqs2, 3-mer similarity, john's search) need no training, so every train chain can be
a selector training query:

    train query in fold k  ->  candidate templates = train chains of the OTHER four folds
                               (never its own family; the two-tower that scores it never saw it)
    validation query       ->  candidate templates = all train chains

Two evaluations:
    A. train on all 1,549 train queries, test on the 159 validation queries (never used for fitting)
    B. 5-fold cross-validation inside the train queries, using the same family folds as the two-tower
       run: every train query is scored by a selector that never saw its fold. Ten times more
       queries than A, so the intervals are much tighter.

The selector is compared with rules that need no training (each method alone, scores added, rank
fusion), with john's search alone, and with the perfect selector. Differences come with a paired
bootstrap interval over queries. Nothing is tuned on the validation queries: the model settings
are those of selector_v1, plus one larger tree model that should be judged on evaluation B.
The test split's labels are never read here.

Inputs : alizehadeel/crossfit-towers (twotower_oof.npz), alizehadeel/mmseqs-baseline (method_scores.npz),
         alizehadeel/john-search (method_scores_john.npz), alizehadeel/label-check (pairs_train/val.parquet),
         alizehadeel/build-features (chains.tsv), alizehadeel/build-msa-features (msa_features.npz, optional)
Outputs: selector2_summary.csv, selector2_metrics.json, selector2_features.csv, selector2_val_scores.parquet
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
POS_TM, POOL_K, BOOT = 0.45, 10, 2000
KS = (1, 5, 10)
BASE = ["twotower", "mmseqs", "kmer3", "john"]
SPARSE = {m for m in os.environ.get("SV_SPARSE", "").split(",") if m}
KEY_MODEL = "selector (boosted trees, larger)"


def find(name, required=True):
    hits = sorted(INPUT.rglob(name))
    if not hits and required:
        sys.exit(f"{name} not found under {INPUT}")
    return hits[0] if hits else None


def z_rows(x, allowed):
    """Standardise each row over its allowed entries."""
    xa = np.where(allowed, x, np.nan)
    with np.errstate(all="ignore"):
        mu, sd = np.nanmean(xa, 1, keepdims=True), np.nanstd(xa, 1, keepdims=True)
    return (x - np.nan_to_num(mu)) / (np.nan_to_num(sd) + 1e-8)


def ranks(score, allowed, rng):
    """0 = best. Ties broken at random; templates that are not allowed go last."""
    s = np.where(allowed, score + 1e-6 * rng.random(score.shape), -np.inf)
    order = np.argsort(-s, axis=1, kind="stable")
    r = np.empty_like(order)
    np.put_along_axis(r, order, np.arange(score.shape[1])[None].repeat(len(score), 0), 1)
    return r


def per_query(score, tm, allowed, rng):
    """Per-query best TM in the top k of `score` (templates not allowed are removed)."""
    r = ranks(score, allowed, rng)
    t = np.where(allowed, tm, -1.0)
    return {k: np.clip(np.where(r < k, t, -1.0).max(1), 0, None) for k in KS}


def summarise(pq, has_pos):
    out = {}
    for k, v in pq.items():
        out[f"hit@{k}"] = float((v[has_pos] >= POS_TM).mean()) if has_pos.any() else float("nan")
        out[f"best_tm@{k}"] = float(v.mean())
    return out


def build(scores, allowed, len_q, len_t, neff_q, rng):
    """Pool the top POOL_K of every method; one row of features per (query, candidate)."""
    names = list(scores)
    rk = {m: ranks(scores[m], allowed, rng) for m in names}
    zs = {m: z_rows(scores[m], allowed) for m in names}
    hit = {m: (scores[m] > 0) if m in SPARSE else np.ones(allowed.shape, dtype=bool) for m in names}
    pool = np.zeros(allowed.shape, dtype=bool)
    for m in names:
        pool |= (rk[m] < POOL_K) & hit[m]
    pool &= allowed
    q, t = np.nonzero(pool)
    X = {}
    for m in names:
        h = hit[m][q, t]
        X[f"{m}_score"] = scores[m][q, t]
        X[f"{m}_z"] = zs[m][q, t]
        X[f"{m}_logrank"] = np.log1p(rk[m][q, t])
        X[f"{m}_top5"] = ((rk[m][q, t] < 5) & h).astype(np.float32)
        best = np.where(allowed, scores[m], -np.inf).max(1)
        X[f"q_{m}_best"] = np.where(np.isfinite(best), best, 0.0)[q]
    X["n_methods_top10"] = sum(((rk[m][q, t] < POOL_K) & hit[m][q, t]).astype(np.float32) for m in names)
    if "mmseqs" in scores:
        hit = scores["mmseqs"] > 0
        X["mmseqs_hit"] = hit[q, t].astype(np.float32)
        X["q_mmseqs_log_hits"] = np.log1p((hit & allowed).sum(1))[q]
    X["len_q"], X["len_t"] = len_q[q].astype(np.float32), len_t[t].astype(np.float32)
    X["len_ratio"] = np.minimum(len_q[q], len_t[t]) / np.maximum(len_q[q], len_t[t])
    if neff_q is not None:
        X["q_log_neff"] = np.log10(np.maximum(neff_q, 1.0))[q]
    return q, t, pd.DataFrame(X), pool


def models():
    return {
        "selector (ridge)": lambda: make_pipeline(StandardScaler(), Ridge(alpha=10.0)),
        "selector (boosted trees)": lambda: HistGradientBoostingRegressor(
            max_depth=3, max_iter=150, learning_rate=0.05, min_samples_leaf=20, l2_regularization=1.0, random_state=0),
        "selector (boosted trees, larger)": lambda: HistGradientBoostingRegressor(
            max_depth=5, max_iter=400, learning_rate=0.05, min_samples_leaf=20, l2_regularization=1.0, random_state=0),
    }


def rules(scores, tm, allowed, pool, rng):
    """Everything that needs no training, per query."""
    out = {}
    zs = {m: z_rows(scores[m], allowed) for m in scores}
    for m in scores:
        out[m] = ("single method", per_query(scores[m], tm, allowed, rng))
    out["all methods, scores added"] = ("rule", per_query(sum(zs.values()), tm, allowed, rng))
    rrf = sum(1.0 / (60 + ranks(scores[m], allowed, rng)) for m in scores)
    out["all methods, rank fusion"] = ("rule", per_query(rrf, tm, allowed, rng))
    best_in_pool = np.clip(np.where(pool, tm, -1.0).max(1), 0, None)
    out["perfect selector (pool)"] = ("ceiling", {k: best_in_pool for k in KS})
    best_any = np.clip(np.where(allowed, tm, -1.0).max(1), 0, None)
    out["best possible (any template)"] = ("ceiling", {k: best_any for k in KS})
    return out


def compare(pq_all, kinds, names, nq):
    """Paired bootstrap over queries: each selector minus the best rule, and minus john alone."""
    cand = [m for m in pq_all if kinds[m] in ("single method", "rule")]
    best_rule = max(cand, key=lambda m: pq_all[m][5].mean())
    idx = np.random.default_rng(1).integers(0, nq, (BOOT, nq))
    out = {}
    for name in names:
        out[name] = {}
        for ref_name, ref in (("best_rule", best_rule), ("john", "john")):
            if ref not in pq_all:
                continue
            c = {"against": ref}
            for k in KS:
                d = pq_all[name][k] - pq_all[ref][k]
                b = d[idx].mean(1)
                c[f"best_tm@{k}_difference"] = float(d.mean())
                c[f"best_tm@{k}_ci95"] = [float(np.quantile(b, 0.025)), float(np.quantile(b, 0.975))]
                c[f"best_tm@{k}_queries_better_same_worse"] = [int((d > 0.01).sum()), int((np.abs(d) <= 0.01).sum()),
                                                               int((d < -0.01).sum())]
            out[name][ref_name] = c
    return out


def selector_pq(pred, q, t, tm, pool, rng):
    S = np.full(tm.shape, -1e9, dtype=np.float64)
    S[q, t] = pred
    return per_query(S, tm, pool, rng)


def run(tag, sc_tr, sc_va, tm_tr, tm_va, al_tr, al_va, fold_tr, len_all, tr, va, neff):
    rng = np.random.default_rng(0)
    len_t = len_all[tr]
    nf_tr, nf_va = (None, None) if neff is None else (neff[tr], neff[va])
    qt, tt, Xt, pool_t = build(sc_tr, al_tr, len_all[tr], len_t, nf_tr, rng)
    qv, tv, Xv, pool_v = build(sc_va, al_va, len_all[va], len_t, nf_va, rng)
    yt, yv = tm_tr[qt, tt], tm_va[qv, tv]
    pos_t = (np.where(al_tr, tm_tr, -1.0) >= POS_TM).any(1)
    pos_v = (np.where(al_va, tm_va, -1.0) >= POS_TM).any(1)
    print(f"[{tag}] train queries {len(tr)} ({int(pos_t.sum())} with a similar template), {len(Xt)} rows "
          f"({pool_t.sum(1).mean():.1f} per query) | validation queries {len(va)} ({int(pos_v.sum())}), {len(Xv)} rows "
          f"({pool_v.sum(1).mean():.1f} per query) | {Xt.shape[1]} features", flush=True)

    rows, comp, pqs = [], {}, {}
    sets ={"validation (selector trained on train queries)": (sc_va, tm_va, al_va, pool_v, pos_v, {}),
            "train queries, out-of-fold": (sc_tr, tm_tr, al_tr, pool_t, pos_t, {})}

    # ---- A: fit on all train queries, score the validation queries
    val_pred = {}
    for name, make in models().items():
        mdl = make().fit(Xt, yt)
        val_pred[name] = mdl.predict(Xv)
        sets["validation (selector trained on train queries)"][5][name] = selector_pq(val_pred[name], qv, tv, tm_va, pool_v, rng)
    # ---- B: cross-validation inside the train queries, same family folds as the two-tower
    cv_pred = {name: np.zeros(len(Xt), dtype=np.float32) for name in models()}
    fq = fold_tr[qt]
    for k in np.unique(fold_tr):
        te = fq == k
        for name, make in models().items():
            cv_pred[name][te] = make().fit(Xt[~te], yt[~te]).predict(Xt[te])
    for name in cv_pred:
        sets["train queries, out-of-fold"][5][name] = selector_pq(cv_pred[name], qt, tt, tm_tr, pool_t, rng)

    for set_name, (sc, tm, al, pool, pos, sel) in sets.items():
        base = rules(sc, tm, al, pool, rng)
        pq_all = {m: v[1] for m, v in base.items()}
        kinds = {m: v[0] for m, v in base.items()}
        pq_all.update(sel)
        kinds.update({m: "selector" for m in sel})
        for m, pq in pq_all.items():
            rows.append({"date_filter": tag, "queries": set_name, "n_queries": len(tm),
                         "with_similar_template": int(pos.sum()), "method": m, "kind": kinds[m], **summarise(pq, pos)})
        comp[set_name] = compare(pq_all, kinds, list(sel), len(tm))
        pqs[set_name] = (pq_all, pos, float(pool.sum(1).mean()))

    ridge = make_pipeline(StandardScaler(), Ridge(alpha=10.0)).fit(Xt, yt)
    feats = pd.DataFrame({"date_filter": tag, "feature": Xt.columns, "ridge_weight": ridge[-1].coef_,
                          "correlation_with_tm": [float(np.corrcoef(Xt[c], yt)[0, 1]) if Xt[c].std() > 0 else 0.0
                                                  for c in Xt.columns]})
    feats = feats.reindex(feats.ridge_weight.abs().sort_values(ascending=False).index)
    out = pd.DataFrame({"date_filter": tag, "q": va[qv], "t": tr[tv], "tm": yv,
                        **{name.replace(" ", "_"): p for name, p in val_pred.items()}})
    return rows, comp, feats, out, pqs


def config_compare(tag, cfg, base_cfg, pq_cfg, pq_base):
    """Same queries, two method sets: the larger tree selector of `cfg` minus that of `base_cfg`,
    plus how the pool ceiling and pool coverage moved."""
    rows = []
    for set_name in pq_cfg:
        a, pos, size_a = pq_cfg[set_name]
        b, _, size_b = pq_base[set_name]
        idx = np.random.default_rng(1).integers(0, len(pos), (BOOT, len(pos)))
        for what in (KEY_MODEL, "perfect selector (pool)"):
            r = {"date_filter": tag, "queries": set_name, "config": cfg, "against": base_cfg, "compared": what,
                 "pool_size": size_a, "pool_size_against": size_b}
            for k in KS:
                d = a[what][k] - b[what][k]
                bs = d[idx].mean(1)
                r[f"best_tm@{k}_difference"] = float(d.mean())
                r[f"best_tm@{k}_ci_low"], r[f"best_tm@{k}_ci_high"] = float(np.quantile(bs, 0.025)), float(np.quantile(bs, 0.975))
                r[f"hit@{k}_difference"] = float((a[what][k][pos] >= POS_TM).mean() - (b[what][k][pos] >= POS_TM).mean())
                r[f"queries_better_same_worse@{k}"] = f"{int((d > 0.01).sum())}/{int((np.abs(d) <= 0.01).sum())}/{int((d < -0.01).sum())}"
            rows.append(r)
    return rows


def load_extra(ids):
    """Every method_scores_<name>.npz except john's: {name: (n, n) score matrix}."""
    extra = {}
    for path in sorted(INPUT.rglob("method_scores_*.npz")):
        name = path.stem[len("method_scores_"):]
        if name == "john" or name in extra:
            continue
        d = np.load(path)
        assert name in d.files, f"{path.name} has no array called '{name}'"
        assert [str(x) for x in d["chain_ids"]] == ids, f"{path.name} is in a different chain order"
        s = d[name].astype(np.float32)
        assert s.shape == (len(ids), len(ids)), f"{path.name}: shape {s.shape}"
        extra[name] = np.nan_to_num(s, nan=0.0)
        print(f"extra method '{name}' from {path}", flush=True)
    return extra


# Method sets for this run (Kaggle cannot pass env vars; the first set is the reference).
# Step 17: the kept set (base + Method 4, Step 16) against kept + Method 1; base alone for reference.
DEFAULT_CONFIGS = ("kept=twotower,mmseqs,kmer3,john,m4;kept+m1=twotower,mmseqs,kmer3,john,m4,m1;"
                   "base=twotower,mmseqs,kmer3,john")


def configs(available):
    spec = os.environ.get("SV_CONFIGS", DEFAULT_CONFIGS).strip()
    if spec:
        out = {}
        for part in spec.split(";"):
            name, methods = part.split("=")
            out[name.strip()] = [m.strip() for m in methods.split(",") if m.strip()]
    else:
        extra = [m for m in available if m not in BASE]
        out = {"base": BASE, **{f"base+{m}": BASE + [m] for m in extra}}
        if len(extra) > 1:
            out["all"] = BASE + extra
    for name, methods in out.items():
        missing = [m for m in methods if m not in available]
        assert not missing, f"config '{name}' needs methods that were not found: {missing}"
    return out


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    o = np.load(find("twotower_oof.npz"))
    ids = [str(x) for x in o["chain_ids"]]
    n = len(ids)
    tr, va, fold = o["train_idx"].astype(int), o["val_idx"].astype(int), o["fold"].astype(int)
    full = {"twotower": o["score"].astype(np.float32)}
    d = np.load(find("method_scores.npz"))
    assert [str(x) for x in d["chain_ids"]] == ids, "method_scores.npz is in a different chain order"
    full["mmseqs"], full["kmer3"] = d["mmseqs_sensitive"].astype(np.float32), d["kmer3"].astype(np.float32)
    j = np.load(find("method_scores_john.npz"))
    assert [str(x) for x in j["chain_ids"]] == ids, "method_scores_john.npz is in a different chain order"
    full["john"] = j["john"].astype(np.float32)
    full.update(load_extra(ids))
    cfgs = configs(full)

    ch = pd.read_csv(find("chains.tsv"), sep="\t")
    assert [str(x) for x in ch.chain_id] == ids, "chains.tsv is in a different chain order"
    len_all = ch.seq_len.to_numpy()
    date = pd.to_datetime(ch.release_date, errors="coerce").to_numpy()
    with np.errstate(invalid="ignore"):
        before = date[None, :] < date[:, None]                  # before[q, t]: t released strictly before q (False if a date is missing)

    p = pd.read_parquet(find("pairs_train.parquet"), columns=["idx_a", "idx_b", "tm_a", "tm_b"])
    v = pd.read_parquet(find("pairs_val.parquet"), columns=["idx_q", "idx_t", "tm_q"])
    tm = np.full((n, n), np.nan, dtype=np.float32)              # tm[q, t], normalised by q
    tm[p.idx_a, p.idx_b], tm[p.idx_b, p.idx_a] = p.tm_a, p.tm_b
    tm[v.idx_q, v.idx_t] = v.tm_q

    other_fold = fold[tr][:, None] != fold[tr][None, :]
    tm_tr, tm_va = tm[np.ix_(tr, tr)], tm[np.ix_(va, tr)]
    assert not np.isnan(tm_va).any(), "a validation x train pair has no TM-score"
    assert not np.isnan(tm_tr[other_fold]).any(), "a train x train pair has no TM-score"
    tm_tr = np.nan_to_num(tm_tr, nan=0.0)                       # only the diagonal, which is never allowed
    sc_tr = {m: s[np.ix_(tr, tr)] for m, s in full.items()}
    sc_va = {m: s[np.ix_(va, tr)] for m, s in full.items()}
    assert not np.isnan(sc_tr["twotower"][other_fold]).any() and not np.isnan(sc_va["twotower"]).any(), \
        "a two-tower score that should exist is missing"
    sc_tr["twotower"] = np.nan_to_num(sc_tr["twotower"], nan=0.0)   # same-fold pairs: never allowed, never used
    neff, mf = None, find("msa_features.npz", required=False)
    if mf is not None:
        m = np.load(mf)
        if [str(x) for x in m["chain_ids"]] == ids:
            neff = m["neff"].astype(np.float32)
    print(f"methods: {list(full)} | {len(tr)} train queries, {len(va)} validation queries | "
          f"fold sizes {np.bincount(fold[tr]).tolist()} | MSA depth {'yes' if neff is not None else 'no'}", flush=True)

    print(f"method sets: {cfgs} | sparse (hit-only pooling): {sorted(SPARSE) or 'none'}", flush=True)

    summary, metrics, feats, outs, cc = [], {"pool_k": POOL_K, "sparse": sorted(SPARSE), "configs": cfgs, "compare": {}}, [], [], []
    first = next(iter(cfgs))
    for tag, a_tr, a_va in (("none", other_fold, np.ones_like(tm_va, dtype=bool)),
                            ("date", other_fold & before[np.ix_(tr, tr)], before[np.ix_(va, tr)])):
        pq_of = {}
        for cfg, methods in cfgs.items():
            s_tr, s_va = {m: sc_tr[m] for m in methods}, {m: sc_va[m] for m in methods}
            rows, comp, f, out, pq_of[cfg] = run(f"{cfg}|{tag}", s_tr, s_va, tm_tr, tm_va, a_tr, a_va, fold[tr], len_all, tr, va, neff)
            summary += [{"config": cfg, **{**r, "date_filter": tag}} for r in rows]
            metrics["compare"][f"{cfg}|{tag}"] = comp
            feats.append(f.assign(config=cfg, date_filter=tag))
            outs.append(out.assign(config=cfg, date_filter=tag))
            if cfg != first:
                cc += config_compare(tag, cfg, first, pq_of[cfg], pq_of[first])
            pd.DataFrame(summary).to_csv(WORK / "selector3_summary.csv", index=False)
    metrics["summary"] = summary
    (WORK / "selector3_metrics.json").write_text(json.dumps(metrics, indent=2))
    pd.DataFrame(cc).to_csv(WORK / "selector3_config_compare.csv", index=False)
    pd.concat(feats).to_csv(WORK / "selector3_features.csv", index=False)
    pd.concat(outs).to_parquet(WORK / "selector3_val_scores.parquet", index=False)
    show = pd.DataFrame(summary)
    show = show[show.kind.isin(["selector", "ceiling"]) | (show.method == "john")]
    print(show.drop(columns=["n_queries"]).round(3).to_string(index=False), flush=True)
    if cc:
        cols = ["date_filter", "queries", "config", "compared", "pool_size", "pool_size_against"] + \
               [f"best_tm@{k}_{s}" for k in KS for s in ("difference", "ci_low", "ci_high")]
        print(pd.DataFrame(cc)[cols].round(4).to_string(index=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
