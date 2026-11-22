"""
usalign_labels.py - Kaggle script: US-align labels for EVERY pair of chains.

Two-tower methodology, step 4: for each pair of RNA chains (a, b) record how similar
their 3D structures are (TM-score) and which residues correspond (the alignment).
These are the training labels for the retriever (TM-score) and the aligner (alignment).

Input  : output of the notebook alizehadeel/dataprep (chains/<chain_id>.pdb, template_db.tsv)
Output : /kaggle/working/parts/part_XXXX.parquet   one file per batch of query chains
         /kaggle/working/labels.parquet             all pairs, written when every batch is done
         /kaggle/working/chains_index.tsv           chain order used (pair = index a < index b)
         /kaggle/working/summary.json, errors.csv

One row per unordered pair (a, b), a before b in chains_index.tsv:
    chain_a, chain_b   chain ids
    len_a, len_b       residues US-align read from each file
    tm_a, tm_b         TM-score normalised by the length of a / of b
    rmsd, lali         RMSD over aligned residues, number of aligned residues
    seqid_ali          identical bases / aligned residues
    n_close            aligned pairs closer than 5 A (the ':' marks in US-align's output)
    cigar              the alignment, run-length encoded, walking both chains 5'->3':
                         M = residue of a aligned to residue of b
                         A = residue of a with no partner
                         B = residue of b with no partner
                       e.g. "7M2A10M5B" . Residue k of a chain = k-th residue US-align read.

How it runs: for query chain i, ONE US-align process aligns it against all chains j > i
(`USalign a.pdb -dir2 chains/ list`). 4 such processes run in parallel.

Resumable: a batch whose part file already exists is skipped. To continue after a
time-out, attach this notebook's own output as an input and run again.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from multiprocessing import Pool
from pathlib import Path

INPUT = Path("/kaggle/input")
WORK = Path("/kaggle/working")
TEMP = Path("/kaggle/temp")
PARTS = WORK / "parts"
LOCAL_CH = TEMP / "chains"
LISTS = TEMP / "lists"
BIN = TEMP / "USalign" / "USalign"
USALIGN_COMMIT = "97325d3aad852f8a4407649f25e697bbaa17e186"   # same as validation_engine/environment.md
BATCH = 32                 # query chains per part file
TIME_BUDGET_H = 10.5       # stop starting new batches after this, so outputs are saved (limit is 12 h)

COLUMNS = ["chain_a", "chain_b", "len_a", "len_b", "tm_a", "tm_b", "rmsd", "lali",
           "seqid_ali", "n_close", "cigar"]

RE_NAME1 = re.compile(r"Name of Structure_1:\s*(\S+)")
RE_NAME2 = re.compile(r"Name of Structure_2:\s*(\S+)")
RE_LEN1 = re.compile(r"Length of Structure_1:\s*(\d+)")
RE_LEN2 = re.compile(r"Length of Structure_2:\s*(\d+)")
RE_ALI = re.compile(r"Aligned length=\s*(\d+),\s*RMSD=\s*([\d.]+),\s*Seq_ID=n_identical/n_aligned=\s*([\d.]+)")
RE_TM1 = re.compile(r"TM-score=\s*([\d.]+)\s*\(normalized by length of Structure_1")
RE_TM2 = re.compile(r"TM-score=\s*([\d.]+)\s*\(normalized by length of Structure_2")


def chain_from_name(token: str) -> str:
    """'/path/1BAU_A.pdb:A' -> '1BAU_A'."""
    name = token.replace("\\", "/").rsplit("/", 1)[-1]
    return name.split(".pdb", 1)[0]


def to_cigar(ali_a: str, ali_b: str) -> str:
    """Run-length encode two gapped alignment rows (see module docstring)."""
    if len(ali_a) != len(ali_b):
        raise ValueError("alignment rows differ in length")
    out, prev, run = [], "", 0
    for x, y in zip(ali_a, ali_b):
        if x != "-" and y != "-":
            op = "M"
        elif x != "-":
            op = "A"
        elif y != "-":
            op = "B"
        else:
            raise ValueError("column with two gaps")
        if op == prev:
            run += 1
        else:
            if prev:
                out.append(f"{run}{prev}")
            prev, run = op, 1
    if prev:
        out.append(f"{run}{prev}")
    return "".join(out)


def parse_full_output(stdout: str) -> list:
    """Parse US-align's default (full) text output for one or many pairs."""
    rows = []
    for block in stdout.split("Name of Structure_1:")[1:]:
        block = "Name of Structure_1:" + block
        lines = block.splitlines()
        k = next(i for i, ln in enumerate(lines) if ln.startswith('(":" denotes'))
        ali_a, marks, ali_b = lines[k + 1], lines[k + 2], lines[k + 3]
        lali, rmsd, seqid = RE_ALI.search(block).groups()
        len_a, len_b = int(RE_LEN1.search(block).group(1)), int(RE_LEN2.search(block).group(1))
        cigar = to_cigar(ali_a, ali_b)
        # Internal checks: the alignment must contain every residue of both chains,
        # and as many aligned columns as US-align reports.
        n_m = sum(int(n) for n, op in re.findall(r"(\d+)([MAB])", cigar) if op == "M")
        if (len(ali_a.replace("-", "")) != len_a or len(ali_b.replace("-", "")) != len_b
                or n_m != int(lali)):
            raise ValueError("alignment rows do not match the reported lengths")
        rows.append({
            "chain_a": chain_from_name(RE_NAME1.search(block).group(1)),
            "chain_b": chain_from_name(RE_NAME2.search(block).group(1)),
            "len_a": len_a, "len_b": len_b,
            "tm_a": float(RE_TM1.search(block).group(1)), "tm_b": float(RE_TM2.search(block).group(1)),
            "rmsd": float(rmsd), "lali": int(lali), "seqid_ali": float(seqid),
            "n_close": marks.count(":"), "cigar": cigar,
        })
    return rows


def run_query(job):
    """Align chain i against all chains after it. Returns (i, rows, error_text)."""
    i, chain, n_expected = job
    if n_expected == 0:
        return i, [], ""
    cmd = [str(BIN), str(LOCAL_CH / f"{chain}.pdb"), "-dir2", str(LOCAL_CH) + "/",
           str(LISTS / f"{i}.txt"), "-mol", "RNA"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
        rows = parse_full_output(r.stdout)
    except Exception as exc:
        return i, [], f"{type(exc).__name__}: {exc}"
    err = ""
    if r.returncode != 0 or len(rows) != n_expected or any(x["chain_a"] != chain for x in rows):
        err = f"rc={r.returncode}, {len(rows)} rows for {n_expected} pairs; stderr: {r.stderr[-200:]!r}"
    return i, rows, err


def main() -> int:
    import pandas as pd

    t_start = time.time()
    PARTS.mkdir(parents=True, exist_ok=True)

    # ---- inputs
    db = pd.read_csv(sorted(INPUT.rglob("template_db.tsv"))[0], sep="\t")
    src = next(d for d in INPUT.rglob("chains") if d.is_dir())
    db = db[[(src / f"{c}.pdb").exists() for c in db.chain_id]].reset_index(drop=True)
    chains = db.chain_id.tolist()
    n = len(chains)
    print(f"{n} chains, {n * (n - 1) // 2} pairs; splits {db.split.value_counts().to_dict()}", flush=True)
    db[["chain_id", "split", "family", "length", "release_date"]].to_csv(
        WORK / "chains_index.tsv", sep="\t", index_label="index")

    # ---- copy chain files to local disk once (reads from the mounted input are slow)
    t0 = time.time()
    if not LOCAL_CH.exists():
        shutil.copytree(src, LOCAL_CH)
    print(f"chains copied to local disk in {time.time() - t0:.0f} s", flush=True)

    # ---- parts from an earlier run attached as input (resume)
    for p in INPUT.rglob("part_*.parquet"):
        if not (PARTS / p.name).exists():
            shutil.copy(p, PARTS / p.name)
    print("parts already present:", len(list(PARTS.glob("part_*.parquet"))), flush=True)

    # ---- build US-align
    if not BIN.exists():
        subprocess.run(["git", "clone", "-q", "https://github.com/pylelab/USalign.git", str(BIN.parent)], check=True)
        subprocess.run(["git", "-C", str(BIN.parent), "checkout", "-q", USALIGN_COMMIT], check=True)
        subprocess.run(["g++", "-static", "-O3", "-ffast-math", "-o", str(BIN),
                        str(BIN.parent / "USalign.cpp"), "-lm"], check=True)
    print("US-align built", flush=True)

    # ---- one list file per query: the chains after it
    LISTS.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (LISTS / f"{i}.txt").write_text("".join(f"{c}.pdb\n" for c in chains[i + 1:]))

    # ---- preflight: 5 pairs through the same code path; stop now if anything is off
    (LISTS / "preflight.txt").write_text("".join(f"{c}.pdb\n" for c in chains[1:6]))
    r = subprocess.run([str(BIN), str(LOCAL_CH / f"{chains[0]}.pdb"), "-dir2", str(LOCAL_CH) + "/",
                        str(LISTS / "preflight.txt"), "-mol", "RNA"], capture_output=True, text=True)
    pre = parse_full_output(r.stdout)
    print("preflight:", [(x["chain_a"], x["chain_b"], x["tm_a"], x["tm_b"], x["cigar"][:30]) for x in pre], flush=True)
    if r.returncode != 0 or [x["chain_b"] for x in pre] != chains[1:6] or any(x["chain_a"] != chains[0] for x in pre):
        print("PREFLIGHT FAILED\n--- stdout ---\n", r.stdout[:3000], "\n--- stderr ---\n", r.stderr[:1000], flush=True)
        return 1

    # ---- run
    batches =[list(range(s, min(s + BATCH, n))) for s in range(0, n, BATCH)]
    errors, done_pairs, done_sec, stopped = [], 0, 0.0, False
    with Pool(os.cpu_count()) as pool:
        for k, idxs in enumerate(batches):
            part = PARTS / f"part_{k:04d}.parquet"
            if part.exists():
                continue
            if (time.time() - t_start) / 3600 > TIME_BUDGET_H:
                stopped = True
                print(f"time budget reached before batch {k}; run again with this output attached", flush=True)
                break
            t0 = time.time()
            res = pool.map(run_query, [(i, chains[i], n - 1 - i) for i in idxs], chunksize=1)
            rows = []
            for i, r, err in sorted(res, key=lambda x: x[0]):
                rows += r
                if err:
                    errors.append({"index": i, "chain": chains[i], "error": err})
                    print(f"  ERROR query {i} {chains[i]}: {err}", flush=True)
            df = pd.DataFrame(rows, columns=COLUMNS)
            tmp = part.with_suffix(".tmp")
            df.to_parquet(tmp, index=False, compression="zstd")
            tmp.rename(part)
            done_pairs += len(df)
            done_sec += time.time() - t0
            left = sum(n - 1 - i for b in batches[k + 1:] for i in b
                       if not (PARTS / f"part_{batches.index(b):04d}.parquet").exists())
            rate = done_sec / max(done_pairs, 1)
            print(f"batch {k + 1}/{len(batches)}: {len(df)} pairs in {time.time() - t0:.0f} s "
                  f"| {rate * 1000:.1f} ms/pair wall | about {left * rate / 3600:.2f} h left", flush=True)

    pd.DataFrame(errors, columns=["index", "chain", "error"]).to_csv(WORK / "errors.csv", index=False)

    # ---- merge when complete
    present = sorted(PARTS.glob("part_*.parquet"))
    summary = {"usalign_commit": USALIGN_COMMIT, "chains": n, "pairs_expected": n * (n - 1) // 2,
               "batches_total": len(batches), "batches_present": len(present),
               "errors_this_run": len(errors), "stopped_for_time": stopped,
               "hours_this_run": (time.time() - t_start) / 3600}
    if len(present) == len(batches):
        all_df = pd.concat([pd.read_parquet(p) for p in present], ignore_index=True)
        for c in ("chain_a", "chain_b"):
            all_df[c] = all_df[c].astype("category")
        all_df.to_parquet(WORK / "labels.parquet", index=False, compression="zstd")
        tm_max = all_df[["tm_a", "tm_b"]].max(axis=1)
        summary.update(
            pairs_written=len(all_df),
            duplicate_pairs=int(all_df.duplicated(["chain_a", "chain_b"]).sum()),
            tm_max_quantiles={str(q): float(tm_max.quantile(q)) for q in (0.5, 0.9, 0.99, 0.999)},
            pairs_tm_max_ge_045=int((tm_max >= 0.45).sum()),
            chains_with_a_partner_ge_045=int(pd.concat(
                [all_df.chain_a[tm_max >= 0.45].astype(str), all_df.chain_b[tm_max >= 0.45].astype(str)]).nunique()),
            labels_parquet_mb=(WORK / "labels.parquet").stat().st_size / 1e6)
    (WORK / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
