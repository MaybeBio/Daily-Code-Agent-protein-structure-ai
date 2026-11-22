"""
john_search.py - Kaggle script (CPU): the template search of the competition winner ("john"), on OUR chains.

The RNAPro paper picks its five inference templates with the template discovery of john's
notebook (jaejohn/rna-3d-folds-tbm-only-approach, function find_similar_sequences). This script
re-implements that search and scores it like every other method here.

john's score for a (query, template) pair, copied from the notebook:
    length filter   skip the template if the lengths differ too much
                    (> 60% if either is under 50 nt, > 20% if either is over 1000 nt, else > 40%)
    composite    =  0.4 * global alignment score   (match 2.9, mismatch -1, gap open -10, extend -0.5,
                                                    divided by 2 * the shorter length)
                  + 0.3 * local alignment score    (same scoring and normalisation)
                  + 0.2 * cosine similarity of 21 composition features
                  + 0.1 * shared 3-mers (Jaccard)
    kept only if composite > 0
john's final five: the best 50 of the top 20% by score are clustered into 5 groups by their
composition features, and the best of each group is taken (for diversity).

Two ways it is scored here:
    john (score order)   templates ranked by the composite score - this is what goes to the selector
    john (final five)    exactly john's five picks after the diversity step

The alignments use parasail (fast, exact) instead of Biopython's pairwise2; scores are scaled
by 10 to be integers. A sample of pairs is re-computed with pairwise2 and the largest
difference is reported; if they disagree, pairwise2 is used for the validation queries.

Inputs : alizehadeel/build-features (features.npz), alizehadeel/label-check (pairs_val/train.parquet),
         alizehadeel/mmseqs-baseline (val_method_scores.npz, method_scores.npz: the other methods)
Outputs: john_summary.csv, john_metrics.json,
         val_method_scores.npz   (the other methods' validation scores PLUS john; read by the selector)
         method_scores_john.npz  (john's score for all chains x all chains, same order as features.npz)
The test split's labels are never read here.
"""
import json
import os
import subprocess
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

INPUT = Path(os.environ.get("JS_INPUT", "/kaggle/input"))      # overridable for local tests
WORK = Path(os.environ.get("JS_WORK", "/kaggle/working"))
ALL_PAIRS = os.environ.get("JS_ALL_PAIRS", "1") == "1"         # also score train and test chains as queries
POS_TM, WORKERS = 0.45, int(os.environ.get("JS_WORKERS", 4))
LETTERS = "ACGU"
MATCH, MISMATCH, GAP_OPEN, GAP_EXT, SCALE = 2.9, -1.0, -10.0, -0.5, 10

for extra in (os.environ.get("JS_PYLIB"),):
    if extra:
        sys.path.insert(0, extra)


def need(pkg):
    try:
        return __import__(pkg)
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", pkg], check=False)
        try:
            return __import__(pkg)
        except ImportError:
            return None


def find(name, required=True):
    hits = sorted(INPUT.rglob(name))
    if not hits and required:
        sys.exit(f"{name} not found under {INPUT}")
    return hits[0] if hits else None


# =============================================================================== john's features
def repeat_content(s):
    if len(s) < 6:
        return 0.0
    n, count = len(s) - 3 + 1, 0
    for i in range(n):
        if s.find(s[i:i + 3], i + 3) != -1:
            count += 1
    return count / n


def rna_features(s):
    """The 21 numbers of _extract_enhanced_rna_features, in the notebook's order."""
    L = len(s)
    f = [s.count(x) / L for x in "AUGC"]
    for d in ("AU", "UA", "GC", "CG", "GU", "UG", "AA", "UU", "GG", "CC"):
        f.append(sum(1 for i in range(L - 1) if s[i:i + 2] == d) / (L - 1) if L > 1 else 0.0)
    a, u, g, c = f[0], f[1], f[2], f[3]
    f += [g + c, a + u, a + g, u + c, min(L / 1000.0, 1.0)]
    f.append(-sum(p * np.log2(p) for p in (a, u, g, c) if p > 0) / 2.0)
    f.append(repeat_content(s))
    return f


def length_ok(lq, lt):
    """john's multi-tier length filter, for a query length against an array of template lengths."""
    ratio = np.abs(lt - lq) / np.maximum(lt, lq)
    limit = np.where((lq < 50) | (lt < 50), 0.6, np.where((lq > 1000) | (lt > 1000), 0.2, 0.4))
    return ratio <= limit


# =============================================================================== alignments
G = {}                                                          # worker globals


def _init(seqs, use_parasail, pylib):
    if pylib:
        sys.path.insert(0, pylib)
    G["seqs"] = seqs
    if use_parasail:
        import parasail
        G["ps"], G["M"] = parasail, parasail.matrix_create("ACGU", int(MATCH * SCALE), int(MISMATCH * SCALE))
    else:
        from Bio import pairwise2
        G["pw"] = pairwise2


def _align_row(job):
    """(query index, template indices) -> global and local raw scores for each template."""
    q, ts = job
    a, seqs = G["seqs"][q], G["seqs"]
    g, l = np.zeros(len(ts), dtype=np.float32), np.zeros(len(ts), dtype=np.float32)
    if "ps" in G:
        ps, M, o, e = G["ps"], G["M"], int(-GAP_OPEN * SCALE), int(-GAP_EXT * SCALE)
        for k, t in enumerate(ts):
            g[k] = ps.nw_striped_16(a, seqs[t], o, e, M).score / SCALE
            l[k] = ps.sw_striped_16(a, seqs[t], o, e, M).score / SCALE
    else:
        pw = G["pw"]
        for k, t in enumerate(ts):
            g[k] = pw.align.globalms(a, seqs[t], MATCH, MISMATCH, GAP_OPEN, GAP_EXT, score_only=True)
            l[k] = pw.align.localms(a, seqs[t], MATCH, MISMATCH, GAP_OPEN, GAP_EXT, score_only=True)
    return q, ts, g, l


# =============================================================================== john's final five
def diversity_labels(F, k):
    n = len(F)
    if n <= k:
        return np.arange(n)
    chosen = [0]
    for _ in range(1, k):
        d = np.min(np.linalg.norm(F[:, None] - F[chosen][None], axis=-1), 1)
        d[chosen] = -1
        chosen.append(int(np.argmax(d)))
    lab = np.argmin(np.linalg.norm(F[:, None] - F[chosen][None], axis=-1), 1)
    lab[chosen] = np.arange(k)
    return lab


def final_five(score_row, allowed_row, feats, top_n=5):
    """john's selection for one query: template indices, best first."""
    cand = np.nonzero((score_row > 0) & allowed_row)[0]
    cand = cand[np.argsort(-score_row[cand], kind="stable")]
    count = min(50, len(cand))
    if len(cand) > 10:
        thr = np.percentile(score_row[cand], 80)
        keep = cand[score_row[cand] >= thr]
        top = keep[:min(count, len(keep))]
    else:
        top = cand[:count]
    if len(top) <= top_n:
        return top[:top_n]
    F = feats[top]
    if len(top) >= 15:
        from sklearn.cluster import KMeans
        lab = KMeans(n_clusters=top_n, random_state=42, n_init=10).fit_predict(F)
    else:
        lab = diversity_labels(F, top_n)
    picks = [top[lab == c][0] for c in range(top_n) if (lab == c).any()]      # `top` is already best-first
    return np.array(sorted(picks, key=lambda t: -score_row[t])[:top_n])


# =============================================================================== scoring
def rank_metrics(score, tm, allowed, rng, ks=(1, 5, 10)):
    s = np.where(allowed, score + 1e-6 * rng.random(score.shape), -np.inf)
    t = np.where(allowed, tm, -1.0)
    t_sorted = np.take_along_axis(t, np.argsort(-s, axis=1, kind="stable"), 1)
    has_pos = (t >= POS_TM).any(1)
    out = {"queries": int(len(t)), "queries_with_a_similar_template": int(has_pos.sum())}
    for k in ks:
        top = t_sorted[:, :k]
        out[f"hit@{k}"] = float((top[has_pos] >= POS_TM).any(1).mean()) if has_pos.any() else None
        out[f"best_tm@{k}"] = float(np.clip(top.max(1), 0, None).mean())
    rho = []
    for i in range(len(t)):
        a = allowed[i]
        if a.sum() > 2 and np.ptp(score[i][a]) > 0:
            rho.append(pd.Series(score[i][a]).corr(pd.Series(tm[i][a]), method="spearman"))
    out["spearman"] = float(np.mean(rho)) if rho else None
    return out


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    f = np.load(find("features.npz"))
    ids = [str(x) for x in f["chain_ids"]]
    n = len(ids)
    tok, off = f["seq_tok"], f["seq_off"]
    seqs = ["".join(LETTERS[t] if t < 4 else "A" for t in tok[off[i]:off[i + 1]]) for i in range(n)]
    length = np.array([len(s) for s in seqs])

    tr_pairs = pd.read_parquet(find("pairs_train.parquet"), columns=["idx_a", "idx_b"])
    va = pd.read_parquet(find("pairs_val.parquet"), columns=["idx_q", "idx_t", "tm_q", "template_before_query"])
    tr = np.unique(np.concatenate([tr_pairs.idx_a, tr_pairs.idx_b]))
    vq = np.unique(va.idx_q)
    tm = np.full((n, n), np.nan, dtype=np.float32)
    before = np.zeros((n, n), dtype=bool)
    tm[va.idx_q, va.idx_t] = va.tm_q
    before[va.idx_q, va.idx_t] = va.template_before_query
    tm_val, dated = tm[np.ix_(vq, tr)], before[np.ix_(vq, tr)]
    everything = np.ones_like(dated)
    print(f"{n} chains | {len(tr)} train templates | {len(vq)} validation queries", flush=True)

    # ---- composition features and 3-mer sets, all chains at once
    feats = np.array([rna_features(s) for s in seqs], dtype=np.float64)
    fn = feats / (np.linalg.norm(feats, axis=1, keepdims=True) + 1e-12)
    feat_sim = fn @ fn.T
    B = np.zeros((n, 64), dtype=np.float32)
    code = {c: i for i, c in enumerate(LETTERS)}
    for i, s in enumerate(seqs):
        for j in range(len(s) - 2):
            B[i, code[s[j]] * 16 + code[s[j + 1]] * 4 + code[s[j + 2]]] = 1.0
    inter = B @ B.T
    union = B.sum(1)[:, None] + B.sum(1)[None, :] - inter
    kmer_sim = np.where(union > 0, inter / np.maximum(union, 1), 0.0)

    # ---- alignments: parasail if it reproduces pairwise2 on a sample
    parasail, bio = need("parasail"), need("Bio")
    pylib = os.environ.get("JS_PYLIB")
    info = {"aligner": None, "all_pairs": ALL_PAIRS}
    use_parasail = parasail is not None
    queries = np.arange(n) if ALL_PAIRS else vq
    targets_of = {int(q): np.nonzero(length_ok(length[q], length) & (np.arange(n) != q))[0] for q in queries}
    if use_parasail and bio is not None:
        rng = np.random.default_rng(0)
        sample_q = rng.choice(vq, min(20, len(vq)), replace=False)
        jobs = [(int(q), rng.choice(targets_of[int(q)], min(10, len(targets_of[int(q)])), replace=False)) for q in sample_q
                if len(targets_of[int(q)])]
        _init(seqs, True, pylib)
        fast = [_align_row(j) for j in jobs]
        G.clear()
        _init(seqs, False, pylib)
        slow = [_align_row(j) for j in jobs]
        G.clear()
        diff = max(max(np.abs(a[2] - b[2]).max(), np.abs(a[3] - b[3]).max()) for a, b in zip(fast, slow))
        info["parasail_vs_pairwise2_max_difference"] = float(diff)
        info["pairs_compared"] = int(sum(len(j[1]) for j in jobs))
        print(f"parasail vs pairwise2 on {info['pairs_compared']} pairs: max difference {diff:.4f}", flush=True)
        if diff > 0.051:
            use_parasail = False
    if not use_parasail:
        if bio is None:
            sys.exit("neither parasail nor Biopython is available")
        queries = vq                                              # pairwise2 is slow: validation queries only
        targets_of = {int(q): np.intersect1d(targets_of[int(q)], tr) for q in queries}
        info["all_pairs"] = False
    info["aligner"] = "parasail" if use_parasail else "pairwise2"

    t0 = time.time()
    S = np.zeros((n, n), dtype=np.float32)
    jobs = [(int(q), targets_of[int(q)]) for q in queries if len(targets_of[int(q)])]
    info["pairs_aligned"] = int(sum(len(j[1]) for j in jobs))
    print(f"aligning {info['pairs_aligned']} pairs with {info['aligner']} on {WORKERS} workers", flush=True)
    with Pool(WORKERS, initializer=_init, initargs=(seqs, use_parasail, pylib)) as pool:
        for done, (q, ts, g, l) in enumerate(pool.imap_unordered(_align_row, jobs, chunksize=8)):
            norm = 2.0 * np.minimum(length[q], length[ts])
            comp = 0.4 * g / norm + 0.3 * l / norm + 0.2 * feat_sim[q, ts] + 0.1 * kmer_sim[q, ts]
            S[q, ts] = np.where(comp > 0, comp, 0.0)
            if (done + 1) % 300 == 0:
                print(f"  {done + 1}/{len(jobs)} queries, {time.time() - t0:.0f} s", flush=True)
    info["align_minutes"] = (time.time() - t0) / 60
    np.savez_compressed(WORK / "method_scores_john.npz", chain_ids=np.array(ids), train_idx=tr, val_idx=vq,
                        queries_scored=queries, john=S)

    # ---- validation: john against the other methods
    val = {}
    prev = find("val_method_scores.npz", required=False)
    if prev is not None:
        d = np.load(prev)
        if [str(x) for x in d["val_ids"]] == [ids[i] for i in vq] and [str(x) for x in d["train_ids"]] == [ids[i] for i in tr]:
            val = {k: d[k].astype(np.float32) for k in d.files if k not in ("val_ids", "train_ids", "tm", "dated", "john")}
        else:
            print("val_method_scores.npz found but in a different chain order; john is reported alone", flush=True)
    val["john"] = S[np.ix_(vq, tr)]
    np.savez_compressed(WORK / "val_method_scores.npz", val_ids=np.array([ids[i] for i in vq]),
                        train_ids=np.array([ids[i] for i in tr]), tm=tm_val, dated=dated, **val)

    summary, metrics = [], {"info": info, "methods": {}, "john_final_five": {}, "coverage": {}}
    for filt, allowed in (("none", everything), ("date", dated)):
        for name, score in val.items():
            r = rank_metrics(score, tm_val, allowed, np.random.default_rng(0))
            metrics["methods"][f"{name}|{filt}"] = r
            summary.append({"date_filter": filt, "method": name + (" (score order)" if name == "john" else ""), **r})
        # john's own five picks
        t = np.where(allowed, tm_val, -1.0)
        has_pos = (t >= POS_TM).any(1)
        best1, best5, npick = np.zeros(len(vq)), np.zeros(len(vq)), np.zeros(len(vq))
        for i in range(len(vq)):
            picks = final_five(val["john"][i], allowed[i], feats[tr])
            npick[i] = len(picks)
            if len(picks):
                best1[i], best5[i] = max(t[i, picks[0]], 0), max(t[i, picks].max(), 0)
        r = {"queries": int(len(vq)), "queries_with_a_similar_template": int(has_pos.sum()),
             "hit@1": float((best1[has_pos] >= POS_TM).mean()), "best_tm@1": float(best1.mean()),
             "hit@5": float((best5[has_pos] >= POS_TM).mean()), "best_tm@5": float(best5.mean()),
             "mean_templates_picked": float(npick.mean()), "queries_with_no_template": int((npick == 0).sum())}
        metrics["john_final_five"][filt] = r
        summary.append({"date_filter": filt, "method": "john (final five)", **r})
        # what john adds to the pool of the other methods (top 5 of each)
        others = [k for k in val if k not in ("john", "mmseqs_paper")]
        if others:
            def pool_best(names):
                pool = np.zeros(t.shape, dtype=bool)
                rng = np.random.default_rng(0)
                for m in names:
                    s = np.where(allowed, val[m] + 1e-6 * rng.random(t.shape), -np.inf)
                    np.put_along_axis(pool, np.argsort(-s, axis=1, kind="stable")[:, :5], True, 1)
                b = np.where(pool, t, -1.0).max(1)
                return {"hit_in_pool": float((b[has_pos] >= POS_TM).mean()), "best_tm_in_pool": float(np.clip(b, 0, None).mean()),
                        "pool_size": float(pool.sum(1).mean())}
            metrics["coverage"][filt] = {"others": others, "top5 of the others": pool_best(others),
                                         "top5 of the others + john": pool_best(others + ["john"]),
                                         "john alone": pool_best(["john"])}
    kept = val["john"] > 0
    metrics["john_kept"] = {"mean_templates_passing_filter_per_query": float(kept.sum(1).mean()),
                            "queries_with_none": int((kept.sum(1) == 0).sum())}
    pd.DataFrame(summary).to_csv(WORK / "john_summary.csv", index=False)
    (WORK / "john_metrics.json").write_text(json.dumps(metrics, indent=2))
    print(pd.DataFrame(summary).round(3).to_string(index=False), flush=True)
    print(json.dumps({k: metrics[k] for k in ("info", "coverage", "john_kept")}, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
