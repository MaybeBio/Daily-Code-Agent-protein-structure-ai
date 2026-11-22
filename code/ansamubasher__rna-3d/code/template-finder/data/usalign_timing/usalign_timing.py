"""
usalign_timing.py - Kaggle script: build US-align and time pairwise RNA alignments.

Purpose (two-tower methodology, step 4): before labelling every chain pair with a
TM-score and a residue alignment, measure how long ONE pair takes, so we know how
many pairs are affordable.

Inputs (attached to the notebook, nothing downloaded by hand):
    output of the notebook alizehadeel/dataprep  ->  chains/<chain_id>.pdb, template_db.tsv

What it does:
    1. Finds the chain PDB folder and template_db.tsv under /kaggle/input.
    2. Clones US-align at the commit the validation engine pins, and compiles it.
    3. Times 200 random train-train pairs, one process per pair:
         a) -outfmt 2  (one tab-separated line: TM-scores, RMSD, lengths)
         b) default    (full text output, which includes the residue alignment)
    4. Times US-align's own all-against-all mode (-dir) on 40 chains, which avoids
       starting a new process for every pair.
    5. Writes timing_pairs.csv, sample_outputs.txt and summary.json to /kaggle/working.
"""
import itertools
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

INPUT = Path("/kaggle/input")
WORK = Path("/kaggle/working")
USALIGN_COMMIT = "97325d3aad852f8a4407649f25e697bbaa17e186"   # same as validation_engine/environment.md
N_PAIRS = 200
N_DIR_CHAINS = 40
SEED = 0


def sh(cmd, **kw):
    print("$", " ".join(map(str, cmd)), flush=True)
    return subprocess.run(cmd, check=True, **kw)


# ---------------------------------------------------------------- 1. locate inputs
print("=== /kaggle/input (3 levels) ===")
for p in sorted(INPUT.glob("*")) + sorted(INPUT.glob("*/*")) + sorted(INPUT.glob("*/*/*")):
    if p.is_dir() or p.suffix in {".tsv", ".zip", ".jsonl", ".csv"}:
        print("  ", p)

db_files = sorted(INPUT.rglob("template_db.tsv"))
if not db_files:
    sys.exit("template_db.tsv not found under /kaggle/input")
db = pd.read_csv(db_files[0], sep="\t")
print("template_db:", db_files[0], db.shape, db.split.value_counts().to_dict())

chain_dirs = [d for d in INPUT.rglob("chains") if d.is_dir()]
if chain_dirs:
    CH = chain_dirs[0]
else:
    zips = sorted(INPUT.rglob("alizeh.zip"))
    if not zips:
        sys.exit("neither a chains/ folder nor alizeh.zip found under /kaggle/input")
    sh(["unzip", "-q", str(zips[0]), "-d", "/kaggle/temp"])
    CH = next(d for d in Path("/kaggle/temp").rglob("chains") if d.is_dir())
print("chains dir:", CH)

db["pdb_path"] = [str(CH / f"{c}.pdb") for c in db.chain_id]
db["exists"] = [os.path.exists(p) for p in db.pdb_path]
print("chain files present:", int(db.exists.sum()), "of", len(db))
db = db[db.exists].reset_index(drop=True)

# ---------------------------------------------------------------- 2. build US-align
SRC = Path("/kaggle/temp/USalign")
if not SRC.exists():
    SRC.parent.mkdir(parents=True, exist_ok=True)
    sh(["git", "clone", "-q", "https://github.com/pylelab/USalign.git", str(SRC)])
    sh(["git", "-C", str(SRC), "checkout", "-q", USALIGN_COMMIT])
BIN = SRC / "USalign"
t0 = time.time()
sh(["g++", "-static", "-O3", "-ffast-math", "-o", str(BIN), str(SRC / "USalign.cpp"), "-lm"])
print(f"compiled in {time.time() - t0:.0f} s")
help_txt = subprocess.run([str(BIN), "-h"], capture_output=True, text=True).stdout
print("\n".join(help_txt.splitlines()[:6]))
(WORK / "usalign_help.txt").write_text(help_txt)

# ---------------------------------------------------------------- 3. time single pairs
train = db[db.split == "train"].reset_index(drop=True)
rng = random.Random(SEED)
pairs = set()
while len(pairs) < N_PAIRS:
    i, j = rng.sample(range(len(train)), 2)
    pairs.add((min(i, j), max(i, j)))
pairs = sorted(pairs)

rows, samples = [], []
for n, (i, j) in enumerate(pairs):
    a, b = train.iloc[i], train.iloc[j]
    rec = {"chain_a": a.chain_id, "chain_b": b.chain_id, "len_a": int(a.length), "len_b": int(b.length)}
    for tag, extra in (("tab", ["-outfmt", "2"]), ("full", [])):
        t = time.perf_counter()
        r = subprocess.run([str(BIN), a.pdb_path, b.pdb_path, "-mol", "RNA", *extra],
                           capture_output=True, text=True)
        rec[f"sec_{tag}"] = time.perf_counter() - t
        rec[f"rc_{tag}"] = r.returncode
        if tag == "tab" and r.returncode == 0:
            data = [ln for ln in r.stdout.splitlines() if ln.strip() and not ln.startswith("#")]
            if data:
                f = data[0].split("\t")
                rec.update(tm_a=float(f[2]), tm_b=float(f[3]), rmsd=float(f[4]), lali=int(f[10]))
        if n < 3:
            samples.append(f"##### {a.chain_id} vs {b.chain_id}  [{tag}]  rc={r.returncode}\n"
                           f"{r.stdout}\n--- stderr ---\n{r.stderr}\n")
    rows.append(rec)
    if (n + 1) % 50 == 0:
        print(f"  {n + 1}/{len(pairs)} pairs", flush=True)

t = pd.DataFrame(rows)
t.to_csv(WORK / "timing_pairs.csv", index=False)
(WORK / "sample_outputs.txt").write_text("\n".join(samples))
print(t[["len_a", "len_b", "sec_tab", "sec_full"]].describe().round(3))
print("failures: tab", int((t.rc_tab != 0).sum()), "| full", int((t.rc_full != 0).sum()))
if "tm_a" in t:
    tm_max = t[["tm_a", "tm_b"]].max(axis=1)
    print("max(TM) quantiles:", tm_max.quantile([.5, .9, .99]).round(3).to_dict(),
          "| pairs with max TM >= 0.45:", int((tm_max >= 0.45).sum()), "of", len(t))

# ---------------------------------------------------------------- 4. time -dir mode
sub = train.sample(N_DIR_CHAINS, random_state=SEED)
lst = WORK / "dir_list.txt"
lst.write_text("\n".join(f"{c}.pdb" for c in sub.chain_id) + "\n")
t0 = time.perf_counter()
r = subprocess.run([str(BIN), "-dir", str(CH) + "/", str(lst), "-mol", "RNA", "-outfmt", "2"],
                   capture_output=True, text=True)
dir_sec = time.perf_counter() - t0
dir_lines = [ln for ln in r.stdout.splitlines() if ln.strip() and not ln.startswith("#")]
(WORK / "dir_mode_output.tsv").write_text(r.stdout)
print(f"-dir mode: rc={r.returncode}, {len(dir_lines)} result lines for {N_DIR_CHAINS} chains "
      f"in {dir_sec:.1f} s; stderr tail: {r.stderr[-300:]!r}")

# ---------------------------------------------------------------- 5. summary
n_all, n_train = len(db), len(train)
n_eval = int((db.split != "train").sum())
cores = os.cpu_count()
summary = {
    "usalign_commit": USALIGN_COMMIT, "cpu_cores": cores,
    "chains_total": n_all, "chains_train": n_train, "chains_val_test": n_eval,
    "pairs_timed": len(t),
    "sec_per_pair_tab_mean": float(t.sec_tab.mean()), "sec_per_pair_tab_median": float(t.sec_tab.median()),
    "sec_per_pair_full_mean": float(t.sec_full.mean()), "sec_per_pair_full_median": float(t.sec_full.median()),
    "dir_mode_chains": N_DIR_CHAINS, "dir_mode_result_lines": len(dir_lines), "dir_mode_sec": dir_sec,
    "dir_mode_sec_per_result": dir_sec / len(dir_lines) if dir_lines else None,
    "pair_counts": {
        "all_vs_all": n_all * (n_all - 1) // 2,
        "train_vs_train": n_train * (n_train - 1) // 2,
        "val_test_vs_train": n_eval * n_train,
    },
}
per = summary["sec_per_pair_full_mean"]
summary["est_hours_one_core_full_output"] = {k: v * per / 3600 for k, v in summary["pair_counts"].items()}
summary["est_hours_all_cores_full_output"] = {k: v / cores for k, v in summary["est_hours_one_core_full_output"].items()}
(WORK / "summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))
