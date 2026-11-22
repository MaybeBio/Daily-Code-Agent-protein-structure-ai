"""
build_features.py - Kaggle script: turn every chain into the arrays the two towers read.

Two-tower methodology, step 5 (inputs). Built once, reused by every training run.

Inputs (attached notebooks, nothing downloaded by hand):
    alizehadeel/dataprep        chains/<chain_id>.pdb, dataset.jsonl, residue_map.tsv
    alizehadeel/usalign-labels  chains_index.tsv   (chain order)
    alizehadeel/label-check     chain_lengths.tsv, pairs_train.parquet (used for the checks only)

Outputs in /kaggle/working:
    features.npz          all chains, concatenated; chain i owns the slice off[i]:off[i+1]
    chains.tsv            one row per chain: sizes and offsets
    feature_report.json   checks and statistics

features.npz
    chain_ids   [n]        chain ids, same order as chains_index.tsv
  sequence tower (what is known for a new target: the sequence only)
    seq_off     [n+1]      offsets into seq_tok
    seq_tok     [S]        base per sequence position: 0 A, 1 C, 2 G, 3 U, 4 other
  structure tower (templates: one entry per residue present in the structure file)
    res_off     [n+1]      offsets into the res_* arrays
    res_xyz     [R, 5, 3]  coordinates of P, C4', C1', C3', N (N9 for purines, N1 for pyrimidines); NaN = atom missing
    res_base    [R]        base, coded like seq_tok
    res_seqpos  [R]        0-based sequence position of this residue, -1 = not in the sequence
    res_us      [R]        index of this residue in US-align's numbering, -1 = US-align did not read it
  alignment labels -> residues
    us_off      [n+1]      offsets into us_res
    us_res      [U]        for US-align residue k of a chain: its index among that chain's structure residues

The graph itself (nearest neighbours, edge features) is NOT stored: it is cheap to build from
res_xyz at training time, and keeping it out lets us change the graph design without re-running this.

Why the three index spaces: the labels' alignment strings count the residues US-align read
(residues with a C3' atom); the structure file can have residues US-align skipped; the sequence
has positions with no resolved residue at all. res_us / us_res / res_seqpos convert between them.

Checks:
    hard  - the number of residues US-align would read equals the length US-align reported, per chain
    soft  - residue names agree with residue_map.tsv; structure bases agree with the sequence
    soft  - end to end: for 3000 labelled pairs, superpose the aligned C3' atoms using OUR index
            mapping and compare the RMSD with the one US-align reported. Agreement means the
            alignment strings point at the residues we think they do.
"""
import json
import os
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

INPUT = Path(os.environ.get("BF_INPUT", "/kaggle/input"))      # overridable for local tests
WORK = Path(os.environ.get("BF_WORK", "/kaggle/working"))
ATOMS = ["P", "C4'", "C1'", "C3'", "N"]
BASE = {"A": 0, "C": 1, "G": 2, "U": 3}
N_RMSD_PAIRS = 3000
RE_RUN = re.compile(r"(\d+)([MAB])")


def find(name):
    hits = sorted(INPUT.rglob(name))
    if not hits:
        sys.exit(f"{name} not found under {INPUT}")
    return hits[0]


def read_chain(path):
    """Residues of one chain file, in file order.
    Returns (resname list, xyz [L,5,3] with NaN, c3_atom [L] bool: C3' on an ATOM record,
             c3_any [L] bool: C3' on an ATOM or HETATM record)."""
    names, xyz, c3_atom, c3_any = [], [], [], []
    key = None
    n1 = n9 = None
    for ln in open(path):
        rec = ln[:6]
        if rec == "ENDMDL":
            break
        if rec not in ("ATOM  ", "HETATM"):
            continue
        k = (ln[21], ln[22:27], ln[17:20])
        if k != key:
            if key is not None:
                xyz[-1][4] = n9 if n9 is not None else (n1 if n1 is not None else xyz[-1][4])
            key, n1, n9 = k, None, None
            names.append(ln[17:20].strip())
            xyz.append(np.full((5, 3), np.nan, dtype=np.float32))
            c3_atom.append(False)
            c3_any.append(False)
        if ln[16] not in " A":
            continue
        atom = ln[12:16].strip()
        if atom in ("P", "C4'", "C1'", "C3'", "N1", "N9"):
            p = (float(ln[30:38]), float(ln[38:46]), float(ln[46:54]))
            if atom == "N1":
                n1 = p
            elif atom == "N9":
                n9 = p
            else:
                xyz[-1][ATOMS.index(atom)] = p
                if atom == "C3'":
                    c3_any[-1] = True
                    c3_atom[-1] = c3_atom[-1] or rec == "ATOM  "
    if key is not None:
        xyz[-1][4] = n9 if n9 is not None else (n1 if n1 is not None else xyz[-1][4])
    return names, np.array(xyz, dtype=np.float32).reshape(-1, 5, 3), np.array(c3_atom, bool), np.array(c3_any, bool)


def cigar_pairs(cigar):
    """Alignment string -> (indices in a, indices in b) of the aligned residues (US-align numbering)."""
    ia, ib, a, b = [], [], 0, 0
    for num, op in RE_RUN.findall(cigar):
        num = int(num)
        if op == "M":
            ia.extend(range(a, a + num))
            ib.extend(range(b, b + num))
            a += num
            b += num
        elif op == "A":
            a += num
        else:
            b += num
    return np.array(ia), np.array(ib)


def kabsch_rmsd(x, y):
    """RMSD of two [N,3] point sets after the best rigid superposition."""
    x = x - x.mean(0)
    y = y - y.mean(0)
    s = np.linalg.svd(x.T @ y, compute_uv=False)
    if np.linalg.det(x.T @ y) < 0:
        s[-1] = -s[-1]
    return float(np.sqrt(max((x ** 2).sum() + (y ** 2).sum() - 2 * s.sum(), 0.0) / len(x)))


def main():
    idx = pd.read_csv(find("chains_index.tsv"), sep="\t")
    us_len = pd.read_csv(find("chain_lengths.tsv"), sep="\t").set_index("chain_id").usalign_length
    seqs = {}
    for ln in open(find("dataset.jsonl")):
        r = json.loads(ln)
        seqs[r["chain_id"]] = r["sequence"]
    rmap = pd.read_csv(find("residue_map.tsv"), sep="\t", dtype={"chain_id": str, "cif_resname": str, "base": str},
                       keep_default_na=False, na_values=[""])
    rmap = {c: g for c, g in rmap.groupby("chain_id", sort=False)}
    ch_dir = next(d for d in INPUT.rglob("chains") if d.is_dir())
    n = len(idx)
    print(f"{n} chains; chain files in {ch_dir}", flush=True)

    seq_tok, res_xyz, res_base, res_seqpos, res_us, us_res, rows = [], [], [], [], [], [], []
    rule_count = {"ATOM records only": 0, "ATOM and HETATM records": 0, "neither": 0}
    bad_len, resname_mismatch, base_mismatch, base_compared, map_out_of_range = [], 0, 0, 0, 0

    for i, cid in enumerate(idx.chain_id):
        seq = seqs[cid]
        names, xyz, c3_atom, c3_any = read_chain(ch_dir / f"{cid}.pdb")
        L = len(names)

        # ---- which residues did US-align read?  It reported `want` residues.
        want = int(us_len[cid])
        if int(c3_atom.sum()) == want:
            used = c3_atom
            rule_count["ATOM records only"] += 1
        elif int(c3_any.sum()) == want:
            used = c3_any
            rule_count["ATOM and HETATM records"] += 1
        else:
            used = c3_atom
            rule_count["neither"] += 1
            bad_len.append({"chain_id": cid, "usalign": want, "atom_only": int(c3_atom.sum()),
                            "atom_and_hetatm": int(c3_any.sum()), "residues_in_file": L})
        us = np.full(L, -1, dtype=np.int32)
        us[used] = np.arange(int(used.sum()))

        # ---- sequence position of each structure residue (residue_map: seq_pos is 1-based)
        seqpos = np.full(L, -1, dtype=np.int32)
        g = rmap[cid]
        k = g.cif_res_index.to_numpy()
        ok = k >= 0
        if ok.any() and k[ok].max() >= L:
            map_out_of_range += 1
            ok &= k < L
        seqpos[k[ok]] = g.seq_pos.to_numpy()[ok] - 1
        resname_mismatch += int(sum(a != b for a, b in zip(np.array(names, dtype=object)[k[ok]],
                                                          g.cif_resname.to_numpy()[ok])))

        # ---- base per structure residue: the sequence's base where mapped, else from the residue name
        base = np.full(L, 4, dtype=np.uint8)
        for r in range(L):
            if seqpos[r] >= 0:
                base[r] = BASE.get(seq[seqpos[r]], 4)
                if names[r] in BASE:
                    base_compared += 1
                    base_mismatch += int(BASE[names[r]] != base[r])
            else:
                base[r] = BASE.get(names[r], 4)

        seq_tok.append(np.array([BASE.get(c, 4) for c in seq], dtype=np.uint8))
        res_xyz.append(xyz)
        res_base.append(base)
        res_seqpos.append(seqpos)
        res_us.append(us)
        us_res.append(np.where(used)[0].astype(np.int32))
        rows.append({"index": i, "chain_id": cid, "split": idx.split[i], "family": idx.family[i],
                     "release_date": idx.release_date[i], "seq_len": len(seq), "n_res": L,
                     "n_res_in_sequence": int((seqpos >= 0).sum()), "n_us": int(used.sum())})
        if (i + 1) % 400 == 0:
            print(f"  {i + 1}/{n} chains", flush=True)

    def offsets(parts):
        return np.concatenate([[0], np.cumsum([len(p) for p in parts])]).astype(np.int64)

    seq_off, res_off, us_off = offsets(seq_tok), offsets(res_xyz), offsets(us_res)
    X = np.concatenate(res_xyz)
    np.savez_compressed(
        WORK / "features.npz", chain_ids=np.array(idx.chain_id, dtype=str), atoms=np.array(ATOMS),
        seq_off=seq_off, seq_tok=np.concatenate(seq_tok),
        res_off=res_off, res_xyz=X, res_base=np.concatenate(res_base),
        res_seqpos=np.concatenate(res_seqpos), res_us=np.concatenate(res_us),
        us_off=us_off, us_res=np.concatenate(us_res))
    ch = pd.DataFrame(rows)
    ch["seq_off"], ch["res_off"], ch["us_off"] = seq_off[:-1], res_off[:-1], us_off[:-1]
    ch.to_csv(WORK / "chains.tsv", sep="\t", index=False)

    seq_all = np.concatenate(seq_tok)
    report = {
        "chains": n, "sequence_positions": int(seq_off[-1]), "structure_residues": int(res_off[-1]),
        "usalign_residues": int(us_off[-1]),
        "hard_check_usalign_length_reproduced": rule_count["neither"] == 0,
        "usalign_reading_rule_per_chain": rule_count, "chains_length_not_reproduced": bad_len[:20],
        "residue_names_disagreeing_with_residue_map": resname_mismatch,
        "chains_with_map_index_beyond_file": map_out_of_range,
        "standard_bases_compared_with_sequence": base_compared, "of_which_disagree": base_mismatch,
        "sequence_positions_with_a_structure_residue": float((np.concatenate(res_seqpos) >= 0).sum() / seq_off[-1]),
        "structure_residues_not_in_sequence": int((np.concatenate(res_seqpos) < 0).sum()),
        "structure_residues_not_read_by_usalign": int((np.concatenate(res_us) < 0).sum()),
        "sequence_tokens_other_than_ACGU": int((seq_all == 4).sum()),
        "share_of_residues_missing_atom": {a: float(np.isnan(X[:, j, 0]).mean()) for j, a in enumerate(ATOMS)},
        "seq_len_quantiles": {str(q): float(ch.seq_len.quantile(q)) for q in (0.05, 0.25, 0.5, 0.75, 0.95, 1.0)},
        "n_res_quantiles": {str(q): float(ch.n_res.quantile(q)) for q in (0.05, 0.25, 0.5, 0.75, 0.95, 1.0)},
        "features_npz_mb": (WORK / "features.npz").stat().st_size / 1e6,
    }

    # ---- end-to-end check: our index mapping + the alignment strings reproduce US-align's RMSD
    pairs = pd.read_parquet(find("pairs_train.parquet"),
                            columns=["idx_a", "idx_b", "rmsd", "lali", "tm_max", "cigar"])
    pairs = pairs[pairs.lali >= 10]
    half = N_RMSD_PAIRS // 2
    hi, lo = pairs[pairs.tm_max >= 0.45], pairs[pairs.tm_max < 0.45]
    sample = pd.concat([hi.sample(min(half, len(hi)), random_state=0), lo.sample(min(half, len(lo)), random_state=0)])
    c3 = ATOMS.index("C3'")
    diffs = []
    for r in sample.itertuples():
        ia, ib = cigar_pairs(r.cigar)
        ua = us_res[r.idx_a][ia]
        ub = us_res[r.idx_b][ib]
        mine = kabsch_rmsd(res_xyz[r.idx_a][ua, c3].astype(np.float64), res_xyz[r.idx_b][ub, c3].astype(np.float64))
        diffs.append(mine - r.rmsd)
    d = np.abs(np.array(diffs))
    report["rmsd_check"] = {
        "pairs": len(d), "median_abs_difference_A": float(np.median(d)), "max_abs_difference_A": float(d.max()),
        "share_within_0.05_A": float((d <= 0.05).mean()), "share_within_0.5_A": float((d <= 0.5).mean()),
        "mean_signed_difference_A": float(np.mean(diffs)),
    }

    (WORK / "feature_report.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str), flush=True)
    return 0 if report["hard_check_usalign_length_reproduced"] else 1


if __name__ == "__main__":
    sys.exit(main())
