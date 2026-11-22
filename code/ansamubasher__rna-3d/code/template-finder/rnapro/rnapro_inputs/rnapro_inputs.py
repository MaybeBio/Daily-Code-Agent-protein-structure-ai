"""
rnapro_inputs.py - Kaggle script (CPU): RNAPro inputs for a subset of validation chains, with john's templates.

RNAPro (NVIDIA-Digital-Bio/RNAPro) needs, for every query chain:
    sequences csv        target_id, sequence
    templates            C1' coordinates of up to 5 templates, already mapped onto the query's
                         residues, in the format of john's submission.csv
                         (ID = <target>_<resid>, resname, resid, x_1..z_5); RNAPro turns that into a .pt file
    MSA                  <target_id>.MSA.fasta (the competition's alignment of the chain)

The templates are made exactly as in john's notebook (jaejohn/rna-3d-folds-tbm-only-approach),
which is how the RNAPro paper picked its inference templates:
    search       john's score against our 1,549 train chains (method_scores_john.npz), date filter
                 (only templates released before the query), john's final five (diversity step)
    adapt        global alignment query vs template (Biopython pairwise2, 2.9 / -1 / -10 / -0.5),
                 template C1' copied to aligned query residues, gaps filled along a backbone path
    refine       john's adaptive_rna_constraints with confidence = his similarity score
    noise        Gaussian, sd = max(0.05, 0.8 - score), fixed seed (john adds it; kept for fidelity)
Template C1' coordinates come from our own structures (features.npz), so the template library is
the same one every other method and the selector choose from.

Which chains: validation chains that have a competition MSA, shuffled with a fixed seed.
    subset_smoke.csv   3 short chains, to check that RNAPro runs at all
    subset_50.csv      50 chains (the smoke chains are among them)
Outputs: subset_smoke.csv, subset_50.csv, john_templates.csv, msa/<id>.MSA.fasta, chosen_templates.csv,
         rnapro_inputs.json; and, when selector-v5 is attached, selector_templates.csv and
         chosen_templates_selector.csv (the selector's top 5, adapted exactly like john's)
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import distance_matrix

INPUT = Path(os.environ.get("RI_INPUT", "/kaggle/input"))
WORK = Path(os.environ.get("RI_WORK", "/kaggle/working"))
N_SUBSET, N_SMOKE, SEED = int(os.environ.get("RI_N", 50)), 3, 0
LETTERS = "ACGU"
C1 = 2                                                          # index of C1' in features.npz ATOMS = [P, C4', C1', C3', N]


def find(name, required=True):
    hits = sorted(INPUT.rglob(name))
    if not hits and required:
        sys.exit(f"{name} not found under {INPUT}")
    return hits[0] if hits else None


def need(pkg, pip_name=None):
    try:
        return __import__(pkg)
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", pip_name or pkg], check=False)
        return __import__(pkg)


# =============================================================================== john's search (as in john_search.py)
def repeat_content(s):
    if len(s) < 6:
        return 0.0
    n, count = len(s) - 3 + 1, 0
    for i in range(n):
        if s.find(s[i:i + 3], i + 3) != -1:
            count += 1
    return count / n


def rna_features(s):
    L = len(s)
    f = [s.count(x) / L for x in "AUGC"]
    for d in ("AU", "UA", "GC", "CG", "GU", "UG", "AA", "UU", "GG", "CC"):
        f.append(sum(1 for i in range(L - 1) if s[i:i + 2] == d) / (L - 1) if L > 1 else 0.0)
    a, u, g, c = f[0], f[1], f[2], f[3]
    f += [g + c, a + u, a + g, u + c, min(L / 1000.0, 1.0)]
    f.append(-sum(p * np.log2(p) for p in (a, u, g, c) if p > 0) / 2.0)
    f.append(repeat_content(s))
    return f


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
    picks = [top[lab == c][0] for c in range(top_n) if (lab == c).any()]
    return np.array(sorted(picks, key=lambda t: -score_row[t])[:top_n])


# =============================================================================== john's template -> query coordinates
def adaptive_rna_constraints(coordinates, sequence, confidence=1.0):
    """Copied from john's notebook."""
    refined = coordinates.copy()
    n = len(sequence)
    strength = 0.8 * (1.0 - min(confidence, 0.8))
    lo, hi = 5.5, 6.5
    for i in range(n - 1):
        cur, nxt = refined[i], refined[i + 1]
        dist = np.linalg.norm(nxt - cur)
        if dist < lo or dist > hi:
            target = (lo + hi) / 2
            direction = (nxt - cur) / (np.linalg.norm(nxt - cur) + 1e-10)
            refined[i + 1] = cur + direction * (dist + (target - dist) * strength)
    min_d = 3.8
    dm = distance_matrix(refined, refined)
    clashes = np.where((dm < min_d) & (dm > 0))
    for idx in range(len(clashes[0])):
        i, j = clashes[0][idx], clashes[1][idx]
        if abs(i - j) <= 1 or i >= j:
            continue
        pi, pj = refined[i], refined[j]
        direction = (pj - pi) / (np.linalg.norm(pj - pi) + 1e-10)
        adj = (min_d - dm[i, j]) * strength
        refined[i] = pi - direction * (adj / 2)
        refined[j] = pj + direction * (adj / 2)
    if strength > 0.3:
        pairs = {"A": "U", "U": "A", "G": "C", "C": "G"}
        for i in range(n):
            comp = pairs.get(sequence[i])
            if not comp:
                continue
            for j in range(i + 3, min(i + 20, n)):
                if sequence[j] == comp:
                    dist = np.linalg.norm(refined[i] - refined[j])
                    if 8.0 < dist < 14.0:
                        adj = (10.5 - dist) * (strength * 0.3)
                        direction = (refined[j] - refined[i]) / (np.linalg.norm(refined[j] - refined[i]) + 1e-10)
                        refined[i] = refined[i] - direction * (adj / 2)
                        refined[j] = refined[j] + direction * (adj / 2)
                        break
    return refined


def adapt_template_to_query(query_seq, template_seq, template_coords, pairwise2):
    """Copied from john's notebook (template_coords: [len(template_seq), 3], NaN = residue not resolved)."""
    aln = pairwise2.align.globalms(query_seq, template_seq, 2.9, -1, -10, -0.5, one_alignment_only=True)[0]
    aq, at = aln.seqA, aln.seqB
    q = np.full((len(query_seq), 3), np.nan)
    qi = ti = 0
    for a, b in zip(aq, at):
        if a != "-" and b != "-":
            if ti < len(template_coords):
                q[qi] = template_coords[ti]
            ti += 1
            qi += 1
        elif a != "-":
            qi += 1
        elif b != "-":
            ti += 1
    bb = 5.9
    for i in range(len(q)):
        if np.isnan(q[i, 0]):
            prev_v = next((j for j in range(i - 1, -1, -1) if not np.isnan(q[j, 0])), None)
            next_v = next((j for j in range(i + 1, len(q)) if not np.isnan(q[j, 0])), None)
            if prev_v is not None and next_v is not None:
                gap = next_v - prev_v
                total = np.linalg.norm(q[next_v] - q[prev_v])
                expected = gap * bb
                if total < expected * 0.7:
                    direction = (q[next_v] - q[prev_v]) / (np.linalg.norm(q[next_v] - q[prev_v]) + 1e-10)
                    for k, idx in enumerate(range(prev_v + 1, next_v)):
                        prog = (k + 1) / gap
                        base = q[prev_v] + direction * expected * prog
                        perp = np.cross(direction, [0, 0, 1])
                        if np.linalg.norm(perp) < 1e-6:
                            perp = np.cross(direction, [1, 0, 0])
                        perp = perp / (np.linalg.norm(perp) + 1e-10)
                        q[idx] = base + perp * 2.0 * np.sin(prog * np.pi)
                else:
                    for k, idx in enumerate(range(prev_v + 1, next_v)):
                        w = (k + 1) / gap
                        q[idx] = (1 - w) * q[prev_v] + w * q[next_v]
            elif prev_v is not None:
                if prev_v > 0 and not np.isnan(q[prev_v - 1, 0]):
                    direction = (q[prev_v] - q[prev_v - 1]) / (np.linalg.norm(q[prev_v] - q[prev_v - 1]) + 1e-10)
                else:
                    direction = np.array([1.0, 0.0, 0.0])
                for step in range(1, i - prev_v + 1):
                    if prev_v + step < len(q):
                        q[prev_v + step] = q[prev_v] + direction * bb * step
            elif next_v is not None:
                direction = np.array([-1.0, 0.0, 0.0])
                for step in range(next_v - i, 0, -1):
                    if next_v - step >= 0:
                        q[next_v - step] = q[next_v] - direction * bb * step
    return np.nan_to_num(q)


# =============================================================================== MSAs
def read_fasta(p, only_first=False):
    seqs, cur = [], []
    with open(p) as fh:
        for line in fh:
            line = line.strip()
            if line.startswith(">"):
                if cur:
                    seqs.append("".join(cur))
                    if only_first:
                        return seqs
                cur = []
            elif line:
                cur.append(line)
    if cur:
        seqs.append("".join(cur))
    return seqs


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    pairwise2 = need("Bio", "biopython") and __import__("Bio.pairwise2", fromlist=["pairwise2"])
    f = np.load(find("features.npz"))
    ids = [str(x) for x in f["chain_ids"]]
    n = len(ids)
    tok, so = f["seq_tok"], f["seq_off"]
    seqs = ["".join(LETTERS[t] if t < 4 else "A" for t in tok[so[i]:so[i + 1]]) for i in range(n)]
    ro, xyz, seqpos = f["res_off"], f["res_xyz"], f["res_seqpos"]
    assert [str(a) for a in f["atoms"]][C1] == "C1'", f["atoms"]

    def c1_by_position(i):
        """C1' of chain i at every sequence position (NaN where no residue was resolved)."""
        out = np.full((len(seqs[i]), 3), np.nan)
        sl = slice(ro[i], ro[i + 1])
        pos, c = seqpos[sl], xyz[sl][:, C1]
        ok = (pos >= 0) & ~np.isnan(c[:, 0])
        out[pos[ok]] = c[ok]
        return out

    va = pd.read_parquet(find("pairs_val.parquet"), columns=["idx_q", "idx_t", "tm_q", "template_before_query"])
    j = np.load(find("method_scores_john.npz"))
    assert [str(x) for x in j["chain_ids"]] == ids, "method_scores_john.npz is in a different chain order"
    S, tr, vq = j["john"], j["train_idx"].astype(int), j["val_idx"].astype(int)
    before = np.zeros((n, n), dtype=bool)
    tm = np.full((n, n), np.nan, dtype=np.float32)
    before[va.idx_q, va.idx_t] = va.template_before_query
    tm[va.idx_q, va.idx_t] = va.tm_q
    feats = np.array([rna_features(s) for s in seqs], dtype=np.float64)

    # ---- MSAs: own name first, else the file whose query row is this chain's sequence (as in build_msa_features)
    dirs = {d.name: d for d in INPUT.rglob("MSA*") if d.is_dir()}
    order = [dirs[k] for k in ("MSA_v2", "MSA") if k in dirs]
    by_seq = {}
    for d in order:
        for p in sorted(d.glob("*.fasta")):
            first = read_fasta(p, only_first=True)
            if first:
                by_seq.setdefault(first[0].replace("-", "").upper(), p)

    def msa_of(i):
        for d in order:
            p = d / f"{ids[i]}.MSA.fasta"
            if p.exists():
                return p
        return by_seq.get(seqs[i])

    def msa_ok(p, s):
        rows = read_fasta(p)
        return bool(rows) and len({len(r) for r in rows}) == 1 and rows[0].replace("-", "").upper() == s

    has = [i for i in vq if msa_of(i) is not None and msa_ok(msa_of(i), seqs[i])]
    print(f"{len(vq)} validation chains, {len(has)} with a usable MSA", flush=True)
    rng = np.random.default_rng(SEED)
    chosen = list(rng.permutation(has))       # all usable chains; the first N_SUBSET are the original 50 (same order)
    smoke = sorted(chosen[:N_SUBSET], key=lambda i: len(seqs[i]))[:N_SMOKE]

    msa_dir = WORK / "msa"
    msa_dir.mkdir(exist_ok=True)
    rows, picks_log, prows = [], [], []

    def add_rows(out, cid, qs, cs):
        cs = list(cs)
        while len(cs) < 5:
            cs.append(cs[-1].copy())
        for r in range(len(qs)):
            d = {"ID": f"{cid}_{r + 1}", "resname": qs[r], "resid": r + 1}
            for m in range(5):
                d[f"x_{m + 1}"], d[f"y_{m + 1}"], d[f"z_{m + 1}"] = (float(v) for v in cs[m][r])
            out.append(d)

    np.random.seed(SEED)
    tr_pos = {t: k for k, t in enumerate(tr)}
    for i in chosen:
        (msa_dir / f"{ids[i]}.MSA.fasta").write_text(msa_of(i).read_text())
        qs = seqs[i]
        row = S[i, tr]
        picks = final_five(row, before[i, tr], feats[tr])
        coords, plain = [], []
        for rank, k in enumerate(picks):
            t = tr[k]
            sc = float(row[k])
            c = adapt_template_to_query(qs, seqs[t], c1_by_position(t), pairwise2)
            plain.append(c.copy())                                # alignment only: no refinement, no noise
            c = adaptive_rna_constraints(c, qs, confidence=sc)
            c = c + np.random.normal(0, max(0.05, 0.8 - sc), c.shape)
            coords.append(c)
            picks_log.append({"target_id": ids[i], "rank": rank + 1, "template": ids[t], "john_score": sc,
                              "tm_to_query": float(tm[i, t]), "template_len": len(seqs[t])})
        while len(coords) < 5:                                    # john would add de novo models; repeat the last template
            coords.append(coords[-1].copy())
        for r in range(len(qs)):
            d = {"ID": f"{ids[i]}_{r + 1}", "resname": qs[r], "resid": r + 1}
            for m in range(5):
                d[f"x_{m + 1}"], d[f"y_{m + 1}"], d[f"z_{m + 1}"] = (float(v) for v in coords[m][r])
            rows.append(d)
        add_rows(prows, ids[i], qs, plain)

    pd.DataFrame(rows).to_csv(WORK / "john_templates.csv", index=False)
    pd.DataFrame(prows).to_csv(WORK / "john_templates_plain.csv", index=False)

    # Step 32 control: each of the first N_SUBSET chains gets its OWN experimental structure as all five
    # templates (unresolved residues filled by the same gap filling), to test whether RNAPro uses templates
    nrows = []
    for i in chosen[:N_SUBSET]:
        own = adapt_template_to_query(seqs[i], seqs[i], c1_by_position(i), pairwise2)
        add_rows(nrows, ids[i], seqs[i], [own])
    pd.DataFrame(nrows).to_csv(WORK / "native_templates.csv", index=False)

    # ---- the selector's top 5 (selector-v5, date filter), adapted EXACTLY like john's: same alignment, same
    # refinement and noise, both driven by john's score of that query-template pair (a property of the pair,
    # not of which method picked it), same seed
    sel_file = find("selector_top5_val.csv", required=False)
    sel_info = {}
    if sel_file is not None:
        sel = pd.read_csv(sel_file)
        sel = sel[sel.date_filter == "date"]
        pos_of = {c: k for k, c in enumerate(ids)}
        np.random.seed(SEED)
        srows, slog, sprows = [], [], []
        for i in chosen:
            qs = seqs[i]
            got = sel[sel.target_id == ids[i]].sort_values("rank")
            coords, plain = [], []
            for rank, tid in enumerate(got.template):
                t = pos_of[tid]
                sc = float(S[i, t])
                c = adapt_template_to_query(qs, seqs[t], c1_by_position(t), pairwise2)
                plain.append(c.copy())
                c = adaptive_rna_constraints(c, qs, confidence=sc)
                c = c + np.random.normal(0, max(0.05, 0.8 - sc), c.shape)
                coords.append(c)
                slog.append({"target_id": ids[i], "rank": rank + 1, "template": tid, "john_score": sc,
                             "tm_to_query": float(tm[i, t]), "template_len": len(seqs[t])})
            while len(coords) < 5:
                coords.append(coords[-1].copy())
            for r in range(len(qs)):
                d = {"ID": f"{ids[i]}_{r + 1}", "resname": qs[r], "resid": r + 1}
                for m in range(5):
                    d[f"x_{m + 1}"], d[f"y_{m + 1}"], d[f"z_{m + 1}"] = (float(v) for v in coords[m][r])
                srows.append(d)
            add_rows(sprows, ids[i], qs, plain)
        pd.DataFrame(srows).to_csv(WORK / "selector_templates.csv", index=False)
        pd.DataFrame(sprows).to_csv(WORK / "selector_templates_plain.csv", index=False)
        slog = pd.DataFrame(slog)
        slog.to_csv(WORK / "chosen_templates_selector.csv", index=False)
        sb = slog.groupby("target_id").tm_to_query.agg(["first", "max"])
        sel_info = {"selector_top1_tm_mean": float(sb["first"].mean()), "selector_best_of_5_tm_mean": float(sb["max"].mean()),
                    "selector_chains": int(len(sb))}
    log = pd.DataFrame(picks_log)
    log.to_csv(WORK / "chosen_templates.csv", index=False)
    sub = pd.DataFrame({"target_id": [ids[i] for i in chosen], "sequence": [seqs[i] for i in chosen]})
    sub["length"] = sub.sequence.str.len()
    sub.iloc[:N_SUBSET].to_csv(WORK / f"subset_{N_SUBSET}.csv", index=False)
    sub.iloc[N_SUBSET:].to_csv(WORK / "subset_rest.csv", index=False)      # Step 31: the other usable chains
    sub.to_csv(WORK / "subset_all.csv", index=False)
    sub[sub.target_id.isin([ids[i] for i in smoke])].to_csv(WORK / "subset_smoke.csv", index=False)

    best = log.groupby("target_id").tm_to_query.agg(["first", "max"])
    info = {"validation_chains": int(len(vq)), "with_usable_msa": int(len(has)), "subset": int(len(chosen)),
            "smoke": [ids[i] for i in smoke], "smoke_lengths": [len(seqs[i]) for i in smoke],
            "length_min_median_max": [int(sub.length.min()), int(sub.length.median()), int(sub.length.max())],
            "john_top1_tm_mean": float(best["first"].mean()), "john_best_of_5_tm_mean": float(best["max"].mean()),
            "queries_with_fewer_than_5_templates": int((log.groupby("target_id").size() < 5).sum()),
            "date_filter": True, **sel_info}
    (WORK / "rnapro_inputs.json").write_text(json.dumps(info, indent=2))
    print(json.dumps(info, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
