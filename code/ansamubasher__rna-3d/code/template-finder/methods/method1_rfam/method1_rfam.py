"""
method1_rfam.py - Kaggle script (CPU): Method 1 (Rfam families with Infernal) as a full score matrix.

Method 1 (all_methods.zip, method1/pipeline.py) labels every chain with its Rfam families using
Infernal's cmscan with Rfam's recommended settings
    cmscan --cut_ga --rfam --nohmmonly --fmt 2 --clanin Rfam.clanin -Z <2 x total length / 1e6>
drops hits that overlap a better one ('=') and minus-strand hits, and then ("Rfam + fallback")
ranks library templates that share an Rfam family with the query first, the rest after, both by the
end-gap-free sequence alignment score. As one number per pair, that ranking is exactly
    m1[q, t] = shares_family(q, t) + seqaln[q, t] / (2 * len(q))
since the second term lies in [0, 1]. The sequence scores are the ones of method4-scores (the same
alignment, checked equal to Method 1's saved scores).

Infernal 1.1.5 is built from source (the version Method 1 used). Rfam comes from the EBI "CURRENT"
release; Method 1 did not record which release it used, so its number is saved here.

Inputs : alizehadeel/dataprep (dataset.jsonl), alizehadeel/build-features (chains.tsv),
         alizehadeel/method4-scores (parts_m4.npz: seqaln)
Outputs: method_scores_m1.npz (chain_ids, m1), rfam_hits.csv (filtered hits), rfam_hits_raw.tblout,
         method1_rfam_check.json
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

INPUT = Path(os.environ.get("SV_INPUT", "/kaggle/input"))
WORK = Path(os.environ.get("SV_WORK", "/kaggle/working"))
TOOLS = Path(os.environ.get("M1_TOOLS", "/kaggle/tmp/infernal"))
INFERNAL = "infernal-1.1.5"
RFAM = "https://ftp.ebi.ac.uk/pub/databases/Rfam/CURRENT"
CPU = os.cpu_count() or 4


def find(name):
    hits = sorted(INPUT.rglob(name))
    if not hits:
        sys.exit(f"{name} not found under {INPUT}")
    return hits[0]


def sh(cmd, **kw):
    print("$", cmd, flush=True)
    subprocess.run(cmd, shell=True, check=True, **kw)


# ---------------------------------------------------------------- copied from method1/pipeline.py


def read_tblout(path):
    """Read a cmscan --fmt 2 table. The first 20 columns are fixed in every Infernal 1.1 version."""
    rows = []
    for line in open(path):
        if line.startswith('#') or not line.strip():
            continue
        f = line.split()
        rows.append({'chain_id': f[3], 'rfam_name': f[1], 'rfam_id': f[2], 'clan': f[5],
                     'seq_from': int(f[9]), 'seq_to': int(f[10]), 'strand': f[11],
                     'score': float(f[16]), 'evalue': float(f[17]), 'olp': f[19]})
    return rows


def filter_hits(raw_hits):
    """Rfam's guide: drop hits that overlap a better hit ('='); keep the '+' strand only."""
    return raw_hits[(raw_hits.olp != '=') & (raw_hits.strand == '+')].sort_values(['chain_id', 'evalue'])


# ---------------------------------------------------------------- new here


def scores(ids, hits, seqaln, lengths):
    """m1[q, t] = shares an Rfam family + sequence score / query's perfect self-score."""
    fams = sorted(set(hits.rfam_id))
    col = {f: i for i, f in enumerate(fams)}
    row = {c: i for i, c in enumerate(ids)}
    F = np.zeros((len(ids), max(len(fams), 1)), dtype=np.float32)
    for c, f in zip(hits.chain_id, hits.rfam_id):
        if c in row:
            F[row[c], col[f]] = 1.0
    same = (F @ F.T) > 0
    return same.astype(np.float32) + seqaln / (2.0 * lengths[:, None]), same


def install():
    if (TOOLS / "bin" / "cmscan").exists():
        return
    build = Path("/kaggle/tmp/build")
    build.mkdir(parents=True, exist_ok=True)
    sh(f"wget -q http://eddylab.org/infernal/{INFERNAL}.tar.gz -O {build}/inf.tar.gz && "
       f"tar -xzf {build}/inf.tar.gz -C {build}")
    sh(f"cd {build}/{INFERNAL} && ./configure --prefix={TOOLS} > /dev/null && make -j{CPU} > /dev/null && "
       f"make install > /dev/null")


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    ch = pd.read_csv(find("chains.tsv"), sep="\t")
    ids = [str(x) for x in ch.chain_id]
    seqs = {}
    for line in open(find("dataset.jsonl")):
        r = json.loads(line)
        seqs[str(r["chain_id"])] = str(r["sequence"]).upper().replace("T", "U")
    lengths = np.array([len(seqs[c]) for c in ids], dtype=np.float32)
    p = np.load(find("parts_m4.npz"))
    assert [str(x) for x in p["chain_ids"]] == ids, "parts_m4.npz is in a different chain order"
    seqaln = p["seqaln"].astype(np.float32)

    t0 = time.time()
    install()
    db = Path("/kaggle/tmp/rfam")
    db.mkdir(parents=True, exist_ok=True)
    sh(f"cd {db} && wget -q {RFAM}/Rfam.cm.gz && gunzip -f Rfam.cm.gz && wget -q {RFAM}/Rfam.clanin && "
       f"(wget -q {RFAM}/README -O README || true)")
    sh(f"{TOOLS}/bin/cmpress -F {db}/Rfam.cm > /dev/null")
    release = next((ln.strip() for ln in open(db / "README", errors="ignore") if "release" in ln.lower()), "unknown") \
        if (db / "README").exists() else "unknown"
    n_models = sum(1 for ln in open(db / "Rfam.cm") if ln.startswith("INFERNAL1"))
    setup_min = (time.time() - t0) / 60

    fasta = Path("/kaggle/tmp/chains.fa")
    fasta.write_text("".join(f">{c}\n{seqs[c]}\n" for c in ids))
    Z = 2 * float(lengths.sum()) / 1e6
    tbl = WORK / "rfam_hits_raw.tblout"
    t0 = time.time()
    sh(f"{TOOLS}/bin/cmscan --cut_ga --rfam --nohmmonly --fmt 2 --clanin {db}/Rfam.clanin -Z {Z:.6f} "
       f"--cpu {CPU} --tblout {tbl} {db}/Rfam.cm {fasta} > /dev/null")
    scan_min = (time.time() - t0) / 60

    hits = filter_hits(pd.DataFrame(read_tblout(tbl)))
    hits.to_csv(WORK / "rfam_hits.csv", index=False)
    m1, same = scores(ids, hits, seqaln, lengths)
    np.savez_compressed(WORK / "method_scores_m1.npz", chain_ids=np.array(ids), m1=m1.astype(np.float32))

    labelled = set(hits.chain_id)
    split = ch.split.to_numpy()
    tr = split == "train"
    fam_of = hits.groupby("chain_id").rfam_name.apply(lambda s: sorted(set(s))).to_dict()
    top = pd.Series([f for c in ids for f in fam_of.get(c, [])]).value_counts().head(8)
    covered = {s: int(sum(1 for i in np.where(split == s)[0] if same[i, tr].sum() - (tr[i] and same[i, i]) > 0))
               for s in ("train", "val", "test")}
    check = {"rfam_release": release, "rfam_models": n_models, "infernal": INFERNAL, "Z": Z,
             "setup_minutes": round(setup_min, 1), "scan_minutes": round(scan_min, 1),
             "hits_after_filter": int(len(hits)), "chains_labelled": len(labelled),
             "share_labelled": len(labelled) / len(ids), "top_families": top.to_dict(),
             "queries_sharing_a_family_with_a_train_chain": covered}
    (WORK / "method1_rfam_check.json").write_text(json.dumps(check, indent=1))
    print(json.dumps(check, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
