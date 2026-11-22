"""
msa_depth.py - Kaggle script (CPU): how deep are the competition's MSAs for OUR chains?

Go / no-go check before adding MSA features to the sequence tower. Covariation between
positions (the base-pair signal) needs many DIFFERENT sequences in an alignment; an alignment
that holds little beyond the query itself adds nothing.

Inputs : competition stanford-rna-3d-folding   MSA/ and MSA_v2/ ({target_id}.MSA.fasta)
         alizehadeel/build-features            chains.tsv, features.npz (our chains and sequences)

Per chain it records:
    found            an MSA file exists for this chain (MSA_v2 preferred, else MSA)
    n_rows           sequences in the file
    first_is_query   the first row, gaps removed, equals our sequence
    n_unique         different aligned rows
    neff80           "effective" number of sequences: rows that are >= 80% identical to each other
                     count as one. This is the usual measure of how much covariation signal there is.
                     Computed on at most 2,000 rows (a random sample if the file has more).
    mean_identity_to_query, mean_coverage   over the rows used

Outputs: msa_depth.tsv (one row per chain), msa_report.json (summary), and the first lines of
         three files printed to the log so the file format can be seen.
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

INPUT = Path(os.environ.get("MD_INPUT", "/kaggle/input"))      # overridable for local tests
WORK = Path(os.environ.get("MD_WORK", "/kaggle/working"))
MAX_ROWS = 2000
CODE = np.full(256, 4, dtype=np.uint8)                         # everything else (gaps, N, ...) = 4
for ch, v in (("A", 0), ("C", 1), ("G", 2), ("U", 3), ("T", 3)):
    CODE[ord(ch)] = v
LETTERS = "ACGU"


def read_fasta(path):
    rows, cur = [], []
    with open(path, errors="replace") as fh:
        for ln in fh:
            if ln.startswith(">"):
                if cur:
                    rows.append("".join(cur))
                cur = []
            else:
                cur.append(ln.strip())
    if cur:
        rows.append("".join(cur))
    return rows


def analyse(path, seq, rng):
    rows = read_fasta(path)
    out = {"n_rows": len(rows), "file_kb": round(path.stat().st_size / 1024, 1)}
    if not rows:
        return out
    lens = {len(r) for r in rows}
    out["rows_same_length"] = len(lens) == 1
    if len(lens) > 1:                                          # a3m style: lower-case letters are insertions
        rows = ["".join(c for c in r if not c.islower()) for r in rows]
        lens = {len(r) for r in rows}
        out["same_length_after_dropping_lowercase"] = len(lens) == 1
        if len(lens) > 1:
            return out
    q = rows[0].upper().replace("T", "U")
    out["ali_len"] = len(q)
    out["first_is_query"] = "".join(c for c in q if c in LETTERS) == seq
    out["n_unique"] = len(set(rows))
    use = rows if len(rows) <= MAX_ROWS else [rows[0]] + [rows[i] for i in
                                                         rng.choice(np.arange(1, len(rows)), MAX_ROWS - 1, replace=False)]
    X = CODE[np.frombuffer("".join(r.upper() for r in use).encode("latin-1"), dtype=np.uint8)].reshape(len(use), -1)
    cols = X[0] < 4                                            # keep the query's own positions
    X = X[:, cols]
    L = X.shape[1]
    if L == 0:
        return out
    onehot = np.zeros((len(use), L, 5), dtype=np.float32)
    np.put_along_axis(onehot, X[:, :, None].astype(np.int64), 1.0, axis=2)
    onehot[:, :, 4] = 0.0                                      # a gap never counts as a match
    flat = onehot.reshape(len(use), -1)
    ident = flat @ flat.T / L                                  # share of query positions where two rows agree
    out["rows_used"] = len(use)
    out["neff80"] = float((1.0 / (ident >= 0.8).sum(1).clip(min=1)).sum())
    if len(rows) > MAX_ROWS:
        out["neff80"] *= len(rows) / MAX_ROWS                  # rough scale-up for the rows not sampled
        out["neff80_extrapolated"] = True
    out["mean_identity_to_query"] = float(ident[0, 1:].mean()) if len(use) > 1 else None
    out["mean_coverage"] = float((X < 4).mean())
    return out


def main():
    ch = pd.read_csv(sorted(INPUT.rglob("chains.tsv"))[0], sep="\t")
    f = np.load(sorted(INPUT.rglob("features.npz"))[0])
    seqs = ["".join(LETTERS[t] if t < 4 else "N" for t in f["seq_tok"][f["seq_off"][i]:f["seq_off"][i + 1]])
            for i in range(len(ch))]
    dirs = {d.name: d for d in INPUT.rglob("MSA*") if d.is_dir()}
    print("MSA folders:", {k: str(v) for k, v in dirs.items()}, flush=True)
    for name, d in dirs.items():
        files = sorted(d.glob("*"))
        print(f"  {name}: {len(files)} files, e.g. {[p.name for p in files[:3]]}", flush=True)
    order = [dirs[k] for k in ("MSA_v2", "MSA") if k in dirs]
    if not order:
        sys.exit("no MSA folder found under " + str(INPUT))

    rng = np.random.default_rng(0)
    rows, shown = [], 0
    for i, cid in enumerate(ch.chain_id):
        rec = {"chain_id": cid, "split": ch.split[i], "seq_len": int(ch.seq_len[i]), "found": False}
        for d in order:
            p = d / f"{cid}.MSA.fasta"
            if p.exists():
                rec.update(found=True, source=d.name, **analyse(p, seqs[i], rng))
                if shown < 3:
                    shown += 1
                    print(f"----- {p} (first 6 lines, cut to 120 characters)", flush=True)
                    with open(p, errors="replace") as fh:
                        for _ in range(6):
                            print("   ", fh.readline().rstrip()[:120], flush=True)
                break
        rows.append(rec)
        if (i + 1) % 300 == 0:
            print(f"  {i + 1}/{len(ch)} chains", flush=True)

    d = pd.DataFrame(rows)
    d.to_csv(WORK / "msa_depth.tsv", sep="\t", index=False)
    ok = d[d.found & d.neff80.notna()] if "neff80" in d else d.iloc[:0]
    qs = (0.1, 0.25, 0.5, 0.75, 0.9, 1.0)

    def share(frame, col, thr):
        return float((frame[col] >= thr).mean()) if len(frame) else None

    report = {
        "chains": len(d), "msa_file_found": int(d.found.sum()), "analysed": len(ok),
        "source_folder": d.source.value_counts().to_dict() if "source" in d else {},
        "first_row_is_our_sequence": int(ok.first_is_query.sum()) if len(ok) else 0,
        "rows_quantiles": {str(q): float(ok.n_rows.quantile(q)) for q in qs} if len(ok) else {},
        "neff80_quantiles": {str(q): float(ok.neff80.quantile(q)) for q in qs} if len(ok) else {},
        "share_of_ALL_chains_with_neff80_at_least": {str(t): float((ok.neff80 >= t).sum() / len(d)) for t in (2, 10, 30, 100, 1000)},
        "chains_with_only_the_query": int((ok.n_unique <= 1).sum()) if len(ok) else 0,
        "by_split_share_neff80_ge_30": {s: share(g, "neff80", 30) for s, g in ok.groupby("split")},
        "by_length_share_neff80_ge_30": {str(k): share(g, "neff80", 30) for k, g in
                                         ok.groupby(pd.cut(ok.seq_len, [0, 30, 60, 100, 200, 1000]), observed=True)},
        "by_length_chains": {str(k): int(len(g)) for k, g in
                             ok.groupby(pd.cut(ok.seq_len, [0, 30, 60, 100, 200, 1000]), observed=True)},
        "total_mb_read": float(d.file_kb.sum() / 1024) if "file_kb" in d else 0.0,
    }
    (WORK / "msa_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
