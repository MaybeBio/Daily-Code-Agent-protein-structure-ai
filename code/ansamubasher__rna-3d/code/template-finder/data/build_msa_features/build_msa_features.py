"""
build_msa_features.py - Kaggle script (CPU): MSA features for the sequence tower.

For every chain it finds the competition's alignment (MSA) of that chain's sequence and turns
it into two things the sequence tower can read:

    profile      per position: how often A, C, G, U or a gap occurs there, and how conserved it is
    covariation  per PAIR of positions: do they mutate together? (mutual information with the
                 average-product correction, APC). Pairs that co-vary are usually base-paired.

Finding the alignment: the file named after the chain ({chain_id}.MSA.fasta, MSA_v2 preferred),
else ANY file whose query row is exactly this chain's sequence (the competition stores chains
with identical sequences under one name). Chains with no alignment get a profile made from
their own sequence, zero covariation and has_msa = 0, so the model can tell.

Details: at most 2,000 rows are used per alignment (the query + a random sample). Rows that are
>= 80% identical share their weight, so near-duplicates do not dominate (neff = sum of weights).
Only the query's own columns are kept, so every feature lines up with the sequence positions.

Outputs in /kaggle/working:
    msa_features.npz
        chain_ids [n]            same order as features.npz
        prof      [S, 6]         freq A, C, G, U, gap, conservation; rows line up with seq_tok
        has_msa   [n], neff [n]
        cov_off   [n+1], cov [sum L*L] float16: chain i's L x L table is cov[cov_off[i]:cov_off[i+1]],
                                 standardised per chain (mean 0, sd 1 over off-diagonal pairs)
    msa_features.tsv             per chain: where the alignment came from, rows, neff, contact check
    msa_feature_report.json

Check that the covariation means something: for each chain, take the L/4 strongest co-varying
pairs (at least 4 apart in sequence) and count how many are actually close in the 3D structure
(C1'-C1' under 11.5 A). Compared with the share of ALL such pairs that are close.
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

INPUT = Path(os.environ.get("MF_INPUT", "/kaggle/input"))      # overridable for local tests
WORK = Path(os.environ.get("MF_WORK", "/kaggle/working"))
MAX_ROWS, PSEUDO, CONTACT_A, MIN_SEP = 2000, 1.0, 11.5, 4
CODE = np.full(256, 4, dtype=np.uint8)
for ch, v in (("A", 0), ("C", 1), ("G", 2), ("U", 3), ("T", 3)):
    CODE[ord(ch)] = v
LETTERS = "ACGU"


def read_fasta(path, only_first=False):
    rows, cur = [], []
    with open(path, errors="replace") as fh:
        for ln in fh:
            if ln.startswith(">"):
                if cur:
                    rows.append("".join(cur))
                    if only_first:
                        return rows
                cur = []
            else:
                cur.append(ln.strip())
    if cur:
        rows.append("".join(cur))
    return rows


def ungapped(row):
    return "".join(c for c in row.upper().replace("T", "U") if c in LETTERS)


def msa_features(rows, rng):
    """Aligned rows (first = query) -> (profile [L,6], cov [L,L] or None, neff, rows used)."""
    use = rows if len(rows) <= MAX_ROWS else [rows[0]] + [rows[i] for i in
                                                         rng.choice(np.arange(1, len(rows)), MAX_ROWS - 1, replace=False)]
    X = CODE[np.frombuffer("".join(r.upper() for r in use).encode("latin-1"), dtype=np.uint8)].reshape(len(use), -1)
    X = X[:, X[0] < 4]
    N, L = X.shape
    oh = np.zeros((N, L, 5), dtype=np.float32)
    np.put_along_axis(oh, X[:, :, None].astype(np.int64), 1.0, axis=2)
    nogap = oh.copy()
    nogap[:, :, 4] = 0.0
    flat = nogap.reshape(N, -1)
    w = 1.0 / ((flat @ flat.T) / L >= 0.8).sum(1).clip(min=1)
    neff = float(w.sum())

    fi = (np.einsum("n,nla->la", w, oh) + PSEUDO / 5) / (neff + PSEUDO)             # [L,5]
    ent = -(fi * np.log(fi)).sum(1) / np.log(5)
    prof = np.concatenate([fi, 1.0 - ent[:, None]], 1).astype(np.float32)
    if neff < 2 or L < 3:
        return prof, None, neff, N

    full = oh.reshape(N, -1)
    fij = ((full * w[:, None]).T @ full).reshape(L, 5, L, 5).transpose(0, 2, 1, 3)   # [L,L,5,5]
    fij = (fij + PSEUDO / 25) / (neff + PSEUDO)
    mi = (fij * np.log(fij / (fi[:, None, :, None] * fi[None, :, None, :]))).sum((2, 3))
    off = ~np.eye(L, dtype=bool)
    row_mean = (mi * off).sum(1) / (L - 1)
    apc = mi - np.outer(row_mean, row_mean) / max(row_mean.mean(), 1e-9)
    sd = apc[off].std()
    cov = np.where(off, (apc - apc[off].mean()) / sd, 0.0) if sd > 1e-6 else np.zeros((L, L))
    return prof, np.clip(cov, -5, 10).astype(np.float16), neff, N


def contact_check(cov, xyz_c1, seqpos, L):
    """Share of the L/4 strongest co-varying pairs that are close in 3D, and the background share."""
    P = np.full((L, 3), np.nan)
    ok = seqpos >= 0
    P[seqpos[ok]] = xyz_c1[ok]
    D = np.linalg.norm(P[:, None] - P[None], axis=-1)
    i, j = np.triu_indices(L, MIN_SEP)
    valid = ~np.isnan(D[i, j])
    if valid.sum() < 10:
        return None, None
    i, j = i[valid], j[valid]
    close = D[i, j] < CONTACT_A
    top = np.argsort(-cov[i, j].astype(np.float32), kind="stable")[:max(L // 4, 1)]
    return float(close[top].mean()), float(close.mean())


def main():
    f = np.load(sorted(INPUT.rglob("features.npz"))[0])
    ids = [str(x) for x in f["chain_ids"]]
    n = len(ids)
    seq_off, res_off = f["seq_off"], f["res_off"]
    seqs = ["".join(LETTERS[t] if t < 4 else "N" for t in f["seq_tok"][seq_off[i]:seq_off[i + 1]]) for i in range(n)]
    dirs = {d.name: d for d in INPUT.rglob("MSA*") if d.is_dir()}
    order = [dirs[k] for k in ("MSA_v2", "MSA") if k in dirs]
    if not order:
        sys.exit("no MSA folder found under " + str(INPUT))

    # ---- index every alignment file by its query sequence (first one found wins; MSA_v2 first)
    by_seq, n_files = {}, 0
    for d in order:
        for p in sorted(d.glob("*.fasta")):
            n_files += 1
            first = read_fasta(p, only_first=True)
            if first:
                by_seq.setdefault(ungapped(first[0]), p)
    print(f"{n_files} alignment files, {len(by_seq)} different query sequences", flush=True)

    rng = np.random.default_rng(0)
    prof_all, cov_all, rows = [], [], []
    for i, cid in enumerate(ids):
        seq, L = seqs[i], len(seqs[i])
        path, how = None, "none"
        for d in order:
            p = d / f"{cid}.MSA.fasta"
            if p.exists():
                path, how = p, "own name"
                break
        if path is None and seq in by_seq:
            path, how = by_seq[seq], "same sequence"
        rec = {"chain_id": cid, "seq_len": L, "msa_source": how, "msa_file": path.name if path else "",
               "n_rows": 0, "neff": 1.0, "has_msa": False, "has_cov": False}
        prof = np.zeros((L, 6), dtype=np.float32)                    # default: own sequence only
        for k, c in enumerate(seq):
            if c in LETTERS:
                prof[k, LETTERS.index(c)] = 1.0
        prof[:, 5] = 1.0
        cov = np.zeros((L, L), dtype=np.float16)
        if path is not None:
            msa = read_fasta(path)
            if msa and len({len(r) for r in msa}) == 1 and ungapped(msa[0]) == seq:
                p_, c_, neff, used = msa_features(msa, rng)
                prof = p_
                rec.update(n_rows=len(msa), rows_used=used, neff=neff, has_msa=True)
                if c_ is not None:
                    cov = c_
                    rec["has_cov"] = True
                    s = slice(res_off[i], res_off[i + 1])
                    rec["top_pairs_close"], rec["all_pairs_close"] = contact_check(
                        c_, f["res_xyz"][s][:, 2], f["res_seqpos"][s], L)
            else:
                rec["msa_source"] = how + " (unusable)"
        prof_all.append(prof)
        cov_all.append(cov.ravel())
        rows.append(rec)
        if (i + 1) % 200 == 0:
            print(f"  {i + 1}/{n} chains", flush=True)

    d = pd.DataFrame(rows)
    d.to_csv(WORK / "msa_features.tsv", sep="\t", index=False)
    cov_off = np.concatenate([[0], np.cumsum([len(c) for c in cov_all])]).astype(np.int64)
    np.savez_compressed(WORK / "msa_features.npz", chain_ids=np.array(ids), prof=np.concatenate(prof_all),
                        has_msa=d.has_msa.to_numpy(), neff=d.neff.to_numpy(np.float32),
                        cov_off=cov_off, cov=np.concatenate(cov_all))

    chk = d[d.top_pairs_close.notna()] if "top_pairs_close" in d else d.iloc[:0]

    def contact_rows(g):
        return {"chains": int(len(g)), "top_covarying_pairs_close": float(g.top_pairs_close.mean()),
                "all_pairs_close": float(g.all_pairs_close.mean())} if len(g) else {"chains": 0}

    report = {
        "chains": n, "alignment_files": n_files,
        "msa_source": d.msa_source.value_counts().to_dict(),
        "chains_with_msa": int(d.has_msa.sum()), "chains_with_covariation": int(d.has_cov.sum()),
        "share_of_all_chains_with_neff_at_least": {str(t): float((d.neff >= t).mean()) for t in (2, 10, 30, 100, 1000)},
        "neff_quantiles": {str(q): float(d.neff.quantile(q)) for q in (0.1, 0.25, 0.5, 0.75, 0.9)},
        "profile_rows_equal_sequence_positions": bool(sum(len(p) for p in prof_all) == seq_off[-1]),
        "contact_check": {"neff >= 100": contact_rows(chk[chk.neff >= 100]),
                          "neff 30 to 100": contact_rows(chk[(chk.neff >= 30) & (chk.neff < 100)]),
                          "neff 2 to 30": contact_rows(chk[chk.neff < 30])},
        "msa_features_npz_mb": (WORK / "msa_features.npz").stat().st_size / 1e6,
    }
    (WORK / "msa_feature_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
