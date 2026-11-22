"""
label_check.py - Kaggle script: check the US-align labels and split them into pair sets.

Two-tower methodology, step 4 (second half). Input is the output of the notebook
alizehadeel/usalign-labels: labels.parquet (one row per chain pair) and chains_index.tsv.

Part 1 - checks (the run fails if a hard check fails):
    - every unordered pair is present exactly once, a before b in chains_index.tsv
    - scores are in range (TM in [0,1], lali <= shorter chain, n_close <= lali)
    - every alignment string accounts for all residues of both chains:
          M runs = lali,  M + A = len_a,  M + B = len_b
    - each chain has ONE length across all of its pairs
    Soft check (reported, does not fail): US-align's length vs the length in template_db.

Part 2 - pair sets written to /kaggle/working:
    pairs_train.parquet   train x train pairs, columns as in labels.parquet plus
                          idx_a, idx_b, fam_a, fam_b, same_family, tm_max, tm_min
    pairs_val.parquet     val query  x train template   (oriented, see below)
    pairs_test.parquet    test query x train template   (oriented)
    eval_queries.tsv      one row per val/test chain: how many train templates are
                          structurally similar, with and without the date filter
    chain_lengths.tsv     US-align length vs template_db length per chain
    tm_hist.csv           TM-score histogram per pair set
    check_report.json     every number above in one place

Oriented pairs: the val/test chain is always `query`, the train chain is `template`.
    tm_q, tm_t   TM-score normalised by the query / template length
    cigar        M = aligned, Q = query residue with no partner, T = template residue with no partner
    template_before_query   template released strictly before the query (the date filter)

Val x val, val x test and test x test pairs are not written here; they stay in labels.parquet.
"""
import json
import os
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

INPUT = Path(os.environ.get("LC_INPUT", "/kaggle/input"))     # overridable for local tests
WORK = Path(os.environ.get("LC_WORK", "/kaggle/working"))
POS = 0.45                      # trial threshold from the methodology, not a tuned value
CASP15_CUTOFF = "2022-05-27"    # dataset_info.txt: safe temporal cutoff for the CASP15 validation targets
RE_RUN = re.compile(r"(\d+)([MAB])")

report = {"hard_checks": {}, "soft_checks": {}}


def hard(name, ok, detail=None):
    report["hard_checks"][name] = {"ok": bool(ok), "detail": detail}
    print(("PASS  " if ok else "FAIL  ") + name + (f"  {detail}" if detail is not None else ""), flush=True)


# ------------------------------------------------------------------ load
lab = pd.read_parquet(sorted(INPUT.rglob("labels.parquet"))[0])
idx = pd.read_csv(sorted(INPUT.rglob("chains_index.tsv"))[0], sep="\t")
lab["chain_a"] = lab.chain_a.astype(str)
lab["chain_b"] = lab.chain_b.astype(str)
n = len(idx)
pos_of = dict(zip(idx.chain_id, idx["index"]))
print(f"{len(lab)} label rows, {n} chains", flush=True)

lab["idx_a"] = lab.chain_a.map(pos_of)
lab["idx_b"] = lab.chain_b.map(pos_of)

# ------------------------------------------------------------------ part 1: checks
hard("all chain ids are known", lab.idx_a.notna().all() and lab.idx_b.notna().all())
lab["idx_a"] = lab.idx_a.astype(int)
lab["idx_b"] = lab.idx_b.astype(int)
hard("row count = n(n-1)/2", len(lab) == n * (n - 1) // 2, f"{len(lab)} vs {n * (n - 1) // 2}")
hard("a comes before b", bool((lab.idx_a < lab.idx_b).all()))
hard("no duplicate pairs", not lab.duplicated(["idx_a", "idx_b"]).any())
appear = np.bincount(lab.idx_a, minlength=n) + np.bincount(lab.idx_b, minlength=n)
hard("every chain is in n-1 pairs", bool((appear == n - 1).all()),
     f"min {int(appear.min())}, max {int(appear.max())}")

hard("no missing values", not lab.isna().any().any(), lab.isna().sum()[lab.isna().sum() > 0].to_dict())
hard("TM-scores in [0, 1]", bool(lab[["tm_a", "tm_b"]].min().min() >= 0 and lab[["tm_a", "tm_b"]].max().max() <= 1.0001),
     f"min {lab[['tm_a', 'tm_b']].min().min()}, max {lab[['tm_a', 'tm_b']].max().max()}")
hard("lali <= shorter chain", bool((lab.lali <= lab[["len_a", "len_b"]].min(axis=1)).all()))
hard("n_close <= lali", bool((lab.n_close <= lab.lali).all()))
hard("seqid in [0, 1]", bool(lab.seqid_ali.between(0, 1.0001).all()))

m = np.zeros(len(lab), dtype=np.int64)
a = np.zeros(len(lab), dtype=np.int64)
b = np.zeros(len(lab), dtype=np.int64)
bad_syntax = 0
for k, c in enumerate(lab.cigar.to_numpy()):
    runs = RE_RUN.findall(c)
    if sum(len(x) + 1 for x, _ in runs) != len(c):
        bad_syntax += 1
    for num, op in runs:
        if op == "M":
            m[k] += int(num)
        elif op == "A":
            a[k] += int(num)
        else:
            b[k] += int(num)
hard("alignment strings are well formed", bad_syntax == 0, f"{bad_syntax} malformed")
hard("alignment M = lali", bool((m == lab.lali.to_numpy()).all()), f"{int((m != lab.lali.to_numpy()).sum())} rows differ")
hard("alignment M + A = len_a", bool((m + a == lab.len_a.to_numpy()).all()))
hard("alignment M + B = len_b", bool((m + b == lab.len_b.to_numpy()).all()))

la = lab.groupby("idx_a").len_a.agg(["min", "max"])
lb = lab.groupby("idx_b").len_b.agg(["min", "max"])
both = pd.concat([la, lb]).groupby(level=0).agg({"min": "min", "max": "max"})
hard("each chain has one length", bool((both["min"] == both["max"]).all()),
     f"{int((both['min'] != both['max']).sum())} chains vary")

idx["usalign_length"] = idx["index"].map(both["max"])
idx["length_diff"] = idx.usalign_length - idx.length
idx[["index", "chain_id", "split", "length", "usalign_length", "length_diff"]].to_csv(
    WORK / "chain_lengths.tsv", sep="\t", index=False)
report["soft_checks"]["chains_where_usalign_length_differs_from_template_db"] = int((idx.length_diff != 0).sum())
report["soft_checks"]["largest_length_differences"] = (
    idx.loc[idx.length_diff != 0].assign(absd=lambda d: d.length_diff.abs()).nlargest(10, "absd")
    [["chain_id", "length", "usalign_length"]].to_dict("records"))
print("chains whose US-align length differs from template_db:",
      report["soft_checks"]["chains_where_usalign_length_differs_from_template_db"], flush=True)

# ------------------------------------------------------------------ part 2: pair sets
split = idx.split.to_numpy()
fam = idx.family.to_numpy()
date = pd.to_datetime(idx.release_date, errors="coerce").to_numpy()
report["chains"] = {"per_split": idx.split.value_counts().to_dict(),
                    "missing_release_date": int(pd.isna(date).sum()),
                    "train_released_before_casp15_cutoff":
                        int(((idx.split == "train") & (date < np.datetime64(CASP15_CUTOFF))).sum())}

lab["split_a"] = split[lab.idx_a]
lab["split_b"] = split[lab.idx_b]
lab["fam_a"] = fam[lab.idx_a]
lab["fam_b"] = fam[lab.idx_b]
lab["same_family"] = lab.fam_a == lab.fam_b
lab["tm_max"] = lab[["tm_a", "tm_b"]].max(axis=1)
lab["tm_min"] = lab[["tm_a", "tm_b"]].min(axis=1)
key = np.where(lab.split_a <= lab.split_b, lab.split_a + " x " + lab.split_b, lab.split_b + " x " + lab.split_a)
report["pairs_per_split_combination"] = pd.Series(key).value_counts().to_dict()

# ---- train x train
tt = lab[(lab.split_a == "train") & (lab.split_b == "train")].drop(columns=["split_a", "split_b"])
tt.to_parquet(WORK / "pairs_train.parquet", index=False, compression="zstd")
pos = tt.tm_max >= POS
n_train = int((idx.split == "train").sum())
partners = (np.bincount(tt.idx_a[pos], minlength=n) + np.bincount(tt.idx_b[pos], minlength=n))[split == "train"]
report["train_x_train"] = {
    "pairs": len(tt),
    f"pairs_tm_max_ge_{POS}": int(pos.sum()),
    "share_positive": float(pos.mean()),
    "positives_same_family": int((pos & tt.same_family).sum()),
    "positives_different_family": int((pos & ~tt.same_family).sum()),
    "same_family_pairs": int(tt.same_family.sum()),
    "same_family_pairs_below_threshold": int((tt.same_family & ~pos).sum()),
    "median_tm_max_same_family": float(tt.tm_max[tt.same_family].median()),
    "median_tm_max_different_family": float(tt.tm_max[~tt.same_family].median()),
    "train_chains": n_train,
    "train_chains_with_no_positive_partner": int((partners == 0).sum()),
    "positive_partners_per_chain_quantiles": {str(q): float(np.quantile(partners, q)) for q in (0.25, 0.5, 0.75, 0.95, 1.0)},
}

# ---- val / test queries against train templates (oriented)
SWAP = str.maketrans("AB", "TQ")    # query is chain b: a-only -> template-only, b-only -> query-only
KEEP = str.maketrans("AB", "QT")    # query is chain a


def oriented(which):
    qa = lab[(lab.split_a == which) & (lab.split_b == "train")]
    qb = lab[(lab.split_b == which) & (lab.split_a == "train")]
    cols = ["rmsd", "lali", "seqid_ali", "n_close"]
    x = pd.DataFrame({"query": qa.chain_a, "template": qa.chain_b, "idx_q": qa.idx_a, "idx_t": qa.idx_b,
                      "len_q": qa.len_a, "len_t": qa.len_b, "tm_q": qa.tm_a, "tm_t": qa.tm_b,
                      **{c: qa[c] for c in cols}, "cigar": qa.cigar.str.translate(KEEP)})
    y = pd.DataFrame({"query": qb.chain_b, "template": qb.chain_a, "idx_q": qb.idx_b, "idx_t": qb.idx_a,
                      "len_q": qb.len_b, "len_t": qb.len_a, "tm_q": qb.tm_b, "tm_t": qb.tm_a,
                      **{c: qb[c] for c in cols}, "cigar": qb.cigar.str.translate(SWAP)})
    out = pd.concat([x, y], ignore_index=True)
    out["fam_q"] = fam[out.idx_q]
    out["fam_t"] = fam[out.idx_t]
    out["template_before_query"] = date[out.idx_t] < date[out.idx_q]
    return out.sort_values(["idx_q", "idx_t"]).reset_index(drop=True)


queries = []
for which in ("val", "test"):
    ev = oriented(which)
    ev.to_parquet(WORK / f"pairs_{which}.parquet", index=False, compression="zstd")
    n_q = int((idx.split == which).sum())
    hard(f"{which}: every query has all {n_train} train templates",
         len(ev) == n_q * n_train and bool((ev.groupby("idx_q").size() == n_train).all()), f"{len(ev)} rows")
    report["soft_checks"][f"{which}_pairs_sharing_a_family_with_train"] = int((ev.fam_q == ev.fam_t).sum())
    ev["pos"] = ev.tm_q >= POS
    ev["pos_dated"] = ev.pos & ev.template_before_query
    best = ev.loc[ev.groupby("idx_q").tm_q.idxmax(), ["idx_q", "template", "tm_q"]].set_index("idx_q")
    dated = ev[ev.template_before_query]
    best_d = dated.loc[dated.groupby("idx_q").tm_q.idxmax(), ["idx_q", "template", "tm_q"]].set_index("idx_q")
    g = ev.groupby("idx_q")
    q = pd.DataFrame({"n_templates": g.size(), "n_similar": g.pos.sum(),
                      "best_tm_q": best.tm_q, "best_template": best.template,
                      "n_templates_dated": g.template_before_query.sum(), "n_similar_dated": g.pos_dated.sum(),
                      "best_tm_q_dated": best_d.tm_q, "best_template_dated": best_d.template})
    q.insert(0, "split", which)
    queries.append(q)
    report[f"{which}_x_train"] = {
        "queries": n_q, "pairs": len(ev),
        f"pairs_tm_q_ge_{POS}": int(ev.pos.sum()),
        "queries_with_a_similar_template": int((q.n_similar > 0).sum()),
        "median_best_tm_q": float(q.best_tm_q.median()),
        "best_tm_q_quantiles": {str(x): float(q.best_tm_q.quantile(x)) for x in (0.1, 0.25, 0.5, 0.75, 0.9)},
        "median_similar_templates_per_query": float(q.n_similar.median()),
        "date_filter": {
            "queries_with_no_earlier_template": int((q.n_templates_dated == 0).sum()),
            "median_templates_left": float(q.n_templates_dated.median()),
            "queries_with_a_similar_template": int((q.n_similar_dated > 0).sum()),
            "median_best_tm_q": float(q.best_tm_q_dated.median()),
        },
    }

q = pd.concat(queries)
q.insert(0, "chain_id", idx.chain_id.to_numpy()[q.index])
q.insert(2, "family", fam[q.index])
q.insert(3, "length", idx.usalign_length.to_numpy()[q.index])
q.insert(4, "release_date", idx.release_date.to_numpy()[q.index])
q.to_csv(WORK / "eval_queries.tsv", sep="\t", index_label="index")

# ---- histogram
bins = np.linspace(0, 1, 21)
hist = pd.DataFrame({"tm_from": bins[:-1], "tm_to": bins[1:]})
hist["train_x_train_tm_max"] = np.histogram(tt.tm_max, bins)[0]
hist["train_x_train_same_family"] = np.histogram(tt.tm_max[tt.same_family], bins)[0]
for which in ("val", "test"):
    hist[f"{which}_x_train_tm_q"] = np.histogram(pd.read_parquet(WORK / f"pairs_{which}.parquet").tm_q, bins)[0]
hist.to_csv(WORK / "tm_hist.csv", index=False)

report["all_hard_checks_passed"] = all(v["ok"] for v in report["hard_checks"].values())
(WORK / "check_report.json").write_text(json.dumps(report, indent=2, default=str))
print(json.dumps({k: v for k, v in report.items() if k != "hard_checks"}, indent=2, default=str), flush=True)
print(hist.to_string(index=False), flush=True)
sys.exit(0 if report["all_hard_checks_passed"] else 1)
