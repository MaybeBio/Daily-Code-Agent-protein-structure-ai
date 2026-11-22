"""
mmseqs_baseline.py - Kaggle script (CPU): the RNAPro paper's MMseqs2 template search, on OUR chains.

The paper's simple template baseline (Table 2, "MMseqs2") searches the query sequence against
the sequences of known structures with MMseqs2 and takes the best hits as templates
(notebook rhijudas/mmseqs2-3d-rna-template-identification). Here the same search is run on our
1,884 chains and scored exactly like the two-tower: validation queries against the train
structures, hit@k / best_tm@k / Spearman, with and without the date filter.

Two search settings:
    mmseqs_paper       the paper notebook's command: easy-search --search-type 3, defaults
    mmseqs_sensitive   shorter k-mers and maximum sensitivity, so short and remote sequences
                       get a chance too (our own addition, not from the paper)

Score of a (query, template) pair = bit score of the best alignment, 0 if MMseqs2 reports no
hit. Hits to the reverse strand are dropped, as the paper notebook does. Templates with no hit
are tied at 0; ties are broken at random (fixed seed), so a query with no hits gets a random order.

Also written, for the selector work that follows:
    method_scores.npz   every method's score table in ONE format: [all chains x all chains],
                        same chain order as features.npz (mmseqs_paper, mmseqs_sensitive, kmer3)
    union rows          what a PERFECT selector could reach by pooling the top 5 of several
                        methods ("oracle union") - the ceiling of the selector idea
The test split's labels are never read here.

Inputs : alizehadeel/build-features (features.npz), alizehadeel/label-check (pairs_train/val.parquet),
         alizehadeel/train-msa (val_scores.npz: the two-tower's validation scores; optional)
Outputs: mmseqs_summary.csv, mmseqs_union.csv, mmseqs_metrics.json, method_scores.npz, val_method_scores.npz
"""
import json
import os
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

INPUT = Path(os.environ.get("MB_INPUT", "/kaggle/input"))      # overridable for local tests
WORK = Path(os.environ.get("MB_WORK", "/kaggle/working"))
TEMP = Path(os.environ.get("MB_TEMP", "/kaggle/temp"))
HITS_DIR = os.environ.get("MB_HITS_DIR")                       # local tests: read ready-made hit files, skip MMseqs2
MMSEQS_URL = "https://mmseqs.com/latest/mmseqs-linux-avx2.tar.gz"
POS_TM, SHORT_LEN = 0.45, 40
LETTERS = "ACGU"
FMT = "query,target,fident,alnlen,qstart,qend,tstart,tend,evalue,bits,qcov,tcov"
SETTINGS = {
    "mmseqs_paper": [],
    "mmseqs_sensitive": ["-s", "7.5", "-k", "7", "-e", "10", "--max-seqs", "2000"],
}


def find(name, required=True):
    hits = sorted(INPUT.rglob(name))
    if not hits:
        if required:
            sys.exit(f"{name} not found under {INPUT}")
        return None
    return hits[0]


def get_mmseqs():
    TEMP.mkdir(parents=True, exist_ok=True)
    binary = TEMP / "mmseqs" / "bin" / "mmseqs"
    if not binary.exists():
        tar = TEMP / "mmseqs.tar.gz"
        urllib.request.urlretrieve(MMSEQS_URL, tar)
        with tarfile.open(tar) as t:
            t.extractall(TEMP)
        binary.chmod(0o755)
    v = subprocess.run([str(binary), "version"], capture_output=True, text=True)
    print("MMseqs2 version:", v.stdout.strip(), flush=True)
    return binary, v.stdout.strip()


def run_search(binary, name, extra, fasta):
    out = TEMP / f"mmseqs_hits_{name}.tsv"                      # can be large; the score tables are what is kept
    cmd = [str(binary), "easy-search", str(fasta), str(fasta), str(out), str(TEMP / f"tmp_{name}"),
           "--search-type", "3", "--format-output", FMT, "-v", "2"] + extra
    print("running:", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        print(f"  {name} FAILED (exit {r.returncode}):\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}", flush=True)
        return None
    return out


def score_table(path, pos, n):
    """Hit file -> [n, n] bit scores (0 = no hit), and a few counts."""
    h = pd.read_csv(path, sep="\t", names=FMT.split(","))
    total = len(h)
    h = h[h.qend >= h.qstart]                                   # drop reverse-strand hits
    h = h[h["query"] != h["target"]]
    S = np.zeros((n, n), dtype=np.float32)
    q, t = h["query"].map(pos).to_numpy(), h["target"].map(pos).to_numpy()
    np.maximum.at(S, (q, t), h.bits.to_numpy(np.float32))
    return S, {"hit_lines": int(total), "forward_non_self_hits": int(len(h)), "pairs_with_a_hit": int((S > 0).sum())}


def rank_metrics(score, tm, allowed, rng, ks=(1, 5, 10)):
    """Same definitions as train_towers.rank_metrics; ties in the score are broken at random."""
    s = np.where(allowed, score + 1e-6 * rng.random(score.shape), -np.inf)
    t = np.where(allowed, tm, -1.0)
    order = np.argsort(-s, axis=1, kind="stable")
    t_sorted = np.take_along_axis(t, order, 1)
    has_pos = (t >= POS_TM).any(1)
    out = {"queries": int(len(t)), "queries_with_a_similar_template": int(has_pos.sum())}
    for k in ks:
        top = t_sorted[:, :k]
        out[f"hit@{k}"] = float((top[has_pos] >= POS_TM).any(1).mean()) if has_pos.any() else None
        out[f"best_tm@{k}"] = float(np.clip(top.max(1), 0, None).mean()) if len(t) else None
    out["best_tm_possible"] = float(np.clip(t.max(1), 0, None).mean()) if len(t) else None
    rho = []
    for i in range(len(t)):
        a = allowed[i]
        if a.sum() > 2 and np.ptp(score[i][a]) > 0:
            rho.append(pd.Series(score[i][a]).corr(pd.Series(tm[i][a]), method="spearman"))
    out["spearman"] = float(np.mean(rho)) if rho else None
    return out


def union_metrics(scores, tm, allowed, rng, k=5):
    """A perfect selector: pool the top k of every method, keep the best template in the pool."""
    t = np.where(allowed, tm, -1.0)
    pool = np.zeros(t.shape, dtype=bool)
    for sc in scores:
        s = np.where(allowed, sc + 1e-6 * rng.random(sc.shape), -np.inf)
        top = np.argsort(-s, axis=1, kind="stable")[:, :k]
        np.put_along_axis(pool, top, True, 1)
    best = np.where(pool, t, -1.0).max(1)
    has_pos = (t >= POS_TM).any(1)
    return {"queries": int(len(t)), "queries_with_a_similar_template": int(has_pos.sum()),
            "pool_size": float(pool.sum(1).mean()),
            "hit_in_pool": float((best[has_pos] >= POS_TM).mean()) if has_pos.any() else None,
            "best_tm_in_pool": float(np.clip(best, 0, None).mean()),
            "best_tm_possible": float(np.clip(t.max(1), 0, None).mean())}


def kmer_vectors(seqs, k=3):
    v = np.zeros((len(seqs), 4 ** k), dtype=np.float32)
    for i, s in enumerate(seqs):
        for j in range(len(s) - k + 1):
            w = s[j:j + k]
            if (w < 4).all():
                v[i, int((w * 4 ** np.arange(k)).sum())] += 1
    return v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-8)


def z(x):
    return (x - x.mean(1, keepdims=True)) / (x.std(1, keepdims=True) + 1e-8)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    f = np.load(find("features.npz"))
    ids = [str(x) for x in f["chain_ids"]]
    n = len(ids)
    pos = {c: i for i, c in enumerate(ids)}
    tok, off = f["seq_tok"], f["seq_off"]
    toks = [tok[off[i]:off[i + 1]].astype(np.int64) for i in range(n)]
    seqs = ["".join(LETTERS[t] if t < 4 else "N" for t in s) for s in toks]
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
    assert not np.isnan(tm_val).any(), "a validation pair has no TM-score"
    everything = np.ones_like(dated)
    print(f"{n} chains | {len(tr)} train templates | {len(vq)} validation queries", flush=True)

    # ---- run MMseqs2: all chains against all chains, once per setting
    fasta = WORK / "chains.fasta"
    fasta.write_text("".join(f">{c}\n{s}\n" for c, s in zip(ids, seqs)))
    version, tables, search_info = "ready-made hit files", {}, {}
    if HITS_DIR is None:
        binary, version = get_mmseqs()
    for name, extra in SETTINGS.items():
        path = Path(HITS_DIR) / f"mmseqs_hits_{name}.tsv" if HITS_DIR else run_search(binary, name, extra, fasta)
        if path is None or not Path(path).exists():
            continue
        tables[name], search_info[name] = score_table(path, pos, n)
        search_info[name]["options"] = " ".join(extra) or "(defaults)"
        print(name, search_info[name], flush=True)
    if not tables:
        sys.exit("no MMseqs2 search succeeded")

    kv = kmer_vectors(toks)
    full = {**tables, "kmer3": (kv @ kv.T).astype(np.float32)}
    np.savez_compressed(WORK / "method_scores.npz", chain_ids=np.array(ids), train_idx=tr, val_idx=vq, **full)

    # ---- methods on the validation queries
    val = {"3-mer sequence similarity": full["kmer3"][np.ix_(vq, tr)]}
    val.update({k: v[np.ix_(vq, tr)] for k, v in tables.items()})
    tt = find("val_scores.npz", required=False)
    if tt is not None:
        d = np.load(tt)
        key = "no_msa" if "no_msa" in d.files else None
        same = [str(x) for x in d["val_ids"]] == [ids[i] for i in vq] and [str(x) for x in d["train_ids"]] == [ids[i] for i in tr]
        if key and same:
            val["two-tower"] = d[key].astype(np.float32)
        else:
            print("val_scores.npz found but not usable (key or chain order differs)", flush=True)
    best = "mmseqs_sensitive" if "mmseqs_sensitive" in val else "mmseqs_paper"
    fused = {f"{best} + 3-mer": z(val[best]) + z(val["3-mer sequence similarity"])}
    if "two-tower" in val:
        fused[f"two-tower + {best}"] = z(val["two-tower"]) + z(val[best])
        fused["two-tower + 3-mer"] = z(val["two-tower"]) + z(val["3-mer sequence similarity"])
        fused[f"two-tower + {best} + 3-mer"] = z(val["two-tower"]) + z(val[best]) + z(val["3-mer sequence similarity"])

    len_q = length[vq]
    groups = {"all": np.ones(len(vq), dtype=bool), f"short (<= {SHORT_LEN} nt)": len_q <= SHORT_LEN,
              f"long (> {SHORT_LEN} nt)": len_q > SHORT_LEN}
    cols = ["queries", "queries_with_a_similar_template", "hit@1", "hit@5", "hit@10",
            "best_tm@1", "best_tm@5", "best_tm@10", "best_tm_possible", "spearman"]
    summary, metrics = [], {"mmseqs_version": version, "search": search_info, "methods": {}, "union": {}, "coverage": {}}

    def add(name, score, kind):
        res = {}
        for filt, allowed in (("none", everything), ("date", dated)):
            for g, rows in groups.items():
                r = rank_metrics(score[rows], tm_val[rows], allowed[rows], np.random.default_rng(0))
                res[f"{filt}|{g}"] = r
                summary.append({"method": name, "kind": kind, "date_filter": filt, "queries_group": g, **{k: r[k] for k in cols}})
        metrics["methods"][name] = res

    for name, score in val.items():
        add(name, score, "single")
    for name, score in fused.items():
        add(name, score, "sum of standardised scores")

    # ---- how much of the queries does MMseqs2 reach at all
    has_pos = (tm_val >= POS_TM).any(1)
    for name in tables:
        hit = val[name] > 0
        metrics["coverage"][name] = {
            "queries_with_any_hit": int(hit.any(1).sum()), "queries": int(len(vq)),
            "share_short_queries_with_any_hit": float(hit[groups[f"short (<= {SHORT_LEN} nt)"]].any(1).mean()),
            "share_long_queries_with_any_hit": float(hit[groups[f"long (> {SHORT_LEN} nt)"]].any(1).mean()),
            "mean_hits_per_query": float(hit.sum(1).mean()),
            "queries_with_a_similar_template": int(has_pos.sum()),
            "of_those_with_a_hit_to_a_similar_template": int(((hit & (tm_val >= POS_TM)).any(1)).sum()),
            "share_of_hits_that_are_similar": float((tm_val[hit] >= POS_TM).mean()) if hit.any() else None,
        }

    # ---- perfect selector over pooled top-5 lists
    combos = {"3-mer": ["3-mer sequence similarity"], best: [best], f"3-mer + {best}": ["3-mer sequence similarity", best]}
    if "two-tower" in val:
        combos.update({"two-tower": ["two-tower"], "two-tower + 3-mer": ["two-tower", "3-mer sequence similarity"],
                       f"two-tower + {best}": ["two-tower", best],
                       f"two-tower + 3-mer + {best}": ["two-tower", "3-mer sequence similarity", best]})
    union_rows = []
    for name, members in combos.items():
        for filt, allowed in (("none", everything), ("date", dated)):
            r = union_metrics([val[m] for m in members], tm_val, allowed, np.random.default_rng(0))
            metrics["union"][f"{name}|{filt}"] = r
            union_rows.append({"pooled_top5_of": name, "date_filter": filt, **r})

    pd.DataFrame(summary).to_csv(WORK / "mmseqs_summary.csv", index=False)
    pd.DataFrame(union_rows).to_csv(WORK / "mmseqs_union.csv", index=False)
    (WORK / "mmseqs_metrics.json").write_text(json.dumps(metrics, indent=2))
    np.savez_compressed(WORK / "val_method_scores.npz", val_ids=np.array([ids[i] for i in vq]),
                        train_ids=np.array([ids[i] for i in tr]), tm=tm_val, dated=dated, **{k.replace(" ", "_"): v for k, v in val.items()})
    s = pd.DataFrame(summary)
    print(s[(s.date_filter == "none")].drop(columns=["date_filter"]).round(3).to_string(index=False), flush=True)
    print(json.dumps(metrics["coverage"], indent=1), flush=True)
    print(pd.DataFrame(union_rows).round(3).to_string(index=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
