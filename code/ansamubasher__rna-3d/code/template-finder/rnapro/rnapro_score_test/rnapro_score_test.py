"""
rnapro_score_test.py - rnapro_score.py on the TEST runs (Step 33): rnapro-run-john-test and
rnapro-run-selector-test, plain templates from rnapro-inputs-test.

rnapro_score.py - Kaggle script (CPU): score predicted structures against the true ones, as in the paper.

Scoring as in the competition and the RNAPro paper: US-align on C1' atoms only
(USalign pred.pdb native.pdb -atom " C1'"), TM-score normalised by the native structure.
For every chain: TM of prediction 1, and the best of the 5 predictions (the competition metric).

Sources scored (whatever is attached):
    predictions_<tag>.csv   RNAPro outputs from alizehadeel/rnapro-run (x_1..z_5 = C1' of 5 predictions)
    john_templates.csv      john's adapted templates themselves, no RNAPro (john's TBM-only approach)
Native C1' coordinates come from features.npz (alizehadeel/build-features); unresolved residues are left out.
Means are reported over the chains every source has (a paired comparison).

Also scored when attached: selector_templates.csv (the selector's adapted templates, no RNAPro), and the
selector run's predictions; paired comparisons selector minus john in rnapro_compare.csv.

Outputs: rnapro_scores.csv (one row per source x chain), rnapro_score_summary.csv, rnapro_compare.csv,
         rnapro_score.json
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

INPUT = Path(os.environ.get("RS_INPUT", "/kaggle/input"))
WORK = Path(os.environ.get("RS_WORK", "/kaggle/working"))
TEMP = Path(os.environ.get("RS_TEMP", "/kaggle/temp"))
USALIGN_COMMIT = "97325d3aad852f8a4407649f25e697bbaa17e186"
BIN = TEMP / "USalign" / "USalign"
LETTERS, C1 = "ACGU", 2
RES3 = {"A": "  A", "C": "  C", "G": "  G", "U": "  U"}


def find(name):
    hits = sorted(INPUT.rglob(name))
    if not hits:
        sys.exit(f"{name} not found under {INPUT}")
    return hits[0]


def write_pdb(path, seq, coords, keep=None):
    lines, k = [], 0
    for i, (c, xyz) in enumerate(zip(seq, coords)):
        if keep is not None and not keep[i]:
            continue
        k += 1
        lines.append(f"ATOM  {k:5d}  C1'{RES3.get(c, '  N')} A{i + 1:4d}    "
                     f"{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}  1.00  0.00           C")
    Path(path).write_text("\n".join(lines) + "\nTER\nEND\n")


def tm_native(pred, native):
    out = subprocess.run([str(BIN), str(pred), str(native), "-atom", " C1'", "-outfmt", "2"],
                         capture_output=True, text=True).stdout.splitlines()
    rows = [l for l in out if l and not l.startswith("#")]
    return float(rows[0].split("\t")[3]) if rows else np.nan          # TM2 = normalised by the native


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    TEMP.mkdir(parents=True, exist_ok=True)
    if not BIN.exists():
        subprocess.run(["git", "clone", "-q", "https://github.com/pylelab/USalign.git", str(BIN.parent)], check=True)
        subprocess.run(["git", "-C", str(BIN.parent), "checkout", "-q", USALIGN_COMMIT], check=True)
        subprocess.run(["g++", "-static", "-O3", "-ffast-math", "-o", str(BIN), str(BIN.parent / "USalign.cpp"), "-lm"],
                       check=True)

    f = np.load(find("features.npz"))
    ids = [str(x) for x in f["chain_ids"]]
    pos_of = {c: i for i, c in enumerate(ids)}
    tok, so, ro, xyz, sp = f["seq_tok"], f["seq_off"], f["res_off"], f["res_xyz"], f["res_seqpos"]

    def native(cid):
        i = pos_of[cid]
        seq = "".join(LETTERS[t] if t < 4 else "N" for t in tok[so[i]:so[i + 1]])
        c = np.full((len(seq), 3), np.nan)
        sl = slice(ro[i], ro[i + 1])
        p, x = sp[sl], xyz[sl][:, C1]
        ok = (p >= 0) & ~np.isnan(x[:, 0])
        c[p[ok]] = x[ok]
        return seq, c

    sources = {p.stem.replace("predictions_", "rnapro ").replace("_", " "): p for p in INPUT.rglob("predictions_*.csv")}
    sources["john templates, no RNAPro"] = find("john_templates.csv")
    sel_tpl = sorted(INPUT.rglob("selector_templates.csv"))
    if sel_tpl:
        sources["selector templates, no RNAPro"] = sel_tpl[0]
    nat_tpl = sorted(INPUT.rglob("native_templates.csv"))   # Step 32 control: each chain's own structure
    if nat_tpl:
        sources["native templates, no RNAPro"] = nat_tpl[0]
    for who in ("john", "selector"):                       # alignment only: no refinement, no noise
        p = sorted(INPUT.rglob(f"{who}_templates_plain.csv"))
        if p:
            sources[f"{who} templates plain, no RNAPro"] = p[0]
    rows = []
    with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
        tmp = Path(tmp)
        for name, path in sources.items():
            df = pd.read_csv(path)
            df["target_id"] = df.ID.str.rsplit("_", n=1).str[0]
            for cid, g in df.groupby("target_id", sort=False):
                if cid not in pos_of:
                    continue
                seq, nat = native(cid)
                if len(g) != len(seq):
                    rows.append({"source": name, "target_id": cid, "error": f"length {len(g)} vs native {len(seq)}"})
                    continue
                g = g.sort_values("resid")
                write_pdb(tmp / "native.pdb", seq, nat, keep=~np.isnan(nat[:, 0]))
                tms = []
                for m in range(1, 6):
                    p = g[[f"x_{m}", f"y_{m}", f"z_{m}"]].to_numpy(dtype=float)
                    if not np.isfinite(p).all() or np.abs(p).sum() == 0:   # RNAPro writes zeros for skipped chains
                        tms.append(np.nan)
                        continue
                    write_pdb(tmp / "pred.pdb", seq, p)
                    tms.append(tm_native(tmp / "pred.pdb", tmp / "native.pdb"))
                rows.append({"source": name, "target_id": cid, "length": len(seq),
                             **{f"tm_{m}": t for m, t in enumerate(tms, 1)},
                             "tm_first": tms[0], "tm_best_of_5": np.nanmax(tms) if np.isfinite(tms).any() else np.nan})
            print(f"{name}: {sum(r['source'] == name for r in rows)} chains scored", flush=True)

    sc = pd.DataFrame(rows)
    for base in ("john plain", "selector plain"):          # Step 31: the first 50 + the other usable chains
        parts = sc[sc.source.isin([f"rnapro {base} 50", f"rnapro {base} rest"])]
        if parts.source.nunique() == 2:
            sc = pd.concat([sc, parts.assign(source=f"rnapro {base} all")], ignore_index=True)
            sources[f"rnapro {base} all"] = Path("combined")
    sc.to_csv(WORK / "rnapro_scores.csv", index=False)
    ok = sc.dropna(subset=["tm_best_of_5"])
    common = set.intersection(*(set(ok[ok.source == s].target_id) for s in sources))
    summ = (ok.groupby("source")[["tm_first", "tm_best_of_5"]].mean()          # each source on its own chains
            .join(ok.groupby("source").size().rename("chains"))
            .join(ok.assign(h=ok.tm_best_of_5 >= 0.45).groupby("source").h.mean().rename("share_best_tm_0.45"))
            .reset_index())
    summ.to_csv(WORK / "rnapro_score_summary.csv", index=False)
    info = {"sources": {k: str(v.name) for k, v in sources.items()}, "chains_in_common": len(common),
            "summary": summ.to_dict(orient="records"),
            "missing_or_failed": sc[sc.tm_best_of_5.isna()][["source", "target_id"]].to_dict(orient="records")
            if "tm_best_of_5" in sc else []}
    # ---- paired comparisons (same chains), 95% bootstrap interval over chains
    comps = []
    for a, b in (("rnapro selector test", "rnapro john test"),
                 ("rnapro native 50", "rnapro john plain 50"), ("rnapro native 50", "rnapro selector plain 50"),
                 ("rnapro selector plain all", "rnapro john plain all"), ("rnapro selector plain rest", "rnapro john plain rest"),
                 ("rnapro selector 50", "rnapro john 50"), ("selector templates, no RNAPro", "john templates, no RNAPro"),
                 ("rnapro selector plain 50", "rnapro john plain 50"), ("rnapro john plain 50", "rnapro john 50"),
                 ("rnapro selector plain 50", "rnapro selector 50"),
                 ("selector templates plain, no RNAPro", "john templates plain, no RNAPro"),
                 ("john templates plain, no RNAPro", "john templates, no RNAPro"),
                 ("selector templates plain, no RNAPro", "selector templates, no RNAPro")):
        if a not in sources or b not in sources:
            continue
        A = ok[ok.source == a].set_index("target_id")
        B = ok[ok.source == b].set_index("target_id")
        both = sorted(set(A.index) & set(B.index))
        idx = np.random.default_rng(1).integers(0, len(both), (2000, len(both)))
        for col in ("tm_first", "tm_best_of_5"):
            d = A.loc[both, col].to_numpy() - B.loc[both, col].to_numpy()
            bs = d[idx].mean(1)
            comps.append({"comparison": f"{a} minus {b}", "metric": col, "chains": len(both),
                          "mean_a": float(A.loc[both, col].mean()), "mean_b": float(B.loc[both, col].mean()),
                          "difference": float(d.mean()), "ci_low": float(np.quantile(bs, 0.025)),
                          "ci_high": float(np.quantile(bs, 0.975)), "better_same_worse":
                          f"{int((d > 0.01).sum())}/{int((abs(d) <= 0.01).sum())}/{int((d < -0.01).sum())}"})
    if comps:
        pd.DataFrame(comps).to_csv(WORK / "rnapro_compare.csv", index=False)
        print(pd.DataFrame(comps).round(4).to_string(index=False), flush=True)
    info["comparisons"] = comps
    (WORK / "rnapro_score.json").write_text(json.dumps(info, indent=2, default=float))
    print(summ.round(3).to_string(index=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
